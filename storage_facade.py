"""
storage_facade.py — the single storage interface future bot code will call
(Cycle S1 Phase 1 foundation; unused by the running bot until Phase 2).

Backed by SQLite (sqlite_ops.py). Function signatures deliberately mirror
today's Excel-backed call sites so the Phase 2 swap is mechanical:

  append_transaction(txn)          ↔ excel_ops.append_transaction
  delete_transaction_row(id, ...)  ↔ file_storage.delete_transaction_row
  update_transaction_field(...)    ↔ file_storage.update_transaction_field
  get_recent_transactions(n)       ↔ file_storage.get_recent_transactions
  load_transactions()              ↔ data.load_data() (same DataFrame columns)
  load_reference_data()            ↔ data.load_reference_data() (same keys)

This module structurally satisfies storage_protocol.StorageBackend — any
future backend must expose the same five callables.
"""

from pathlib import Path

import pandas as pd

import settings
import sqlite_ops
from models import MONTH_NAMES
from sqlite_types import TransactionRow, TransactionSource, TransactionType


def _conn():
    return sqlite_ops.init_db(settings.SQLITE_DB_PATH)


def _require_db() -> None:
    """
    Read-path guard: refuse to read from a DB that was never seeded.

    _conn() auto-creates an empty DB (correct for write paths, which should
    create the DB on first write) — but a read against a never-seeded DB
    would silently return empty reports instead of an error.
    """
    if not Path(settings.SQLITE_DB_PATH).exists():
        raise FileNotFoundError(
            f"SQLite DB not found at {settings.SQLITE_DB_PATH} — "
            f"run scripts/import_excel_to_sqlite.py to seed it"
        )


class RowMismatchError(Exception):
    """The row no longer matches the snapshot the caller captured — aborted."""


def _to_row_dict(transaction) -> dict:
    """Accept a models.Transaction or a plain to_row()-style dict."""
    return transaction.to_row() if hasattr(transaction, "to_row") else dict(transaction)


def append_transaction(transaction) -> None:
    """Compute value_base/rate_used and insert into SQLite."""
    row = _to_row_dict(transaction)
    conn = _conn()
    try:
        rates = sqlite_ops.load_rates_dict(conn)
        value_base, rate_used = sqlite_ops.compute_value_base(
            row["value"], row.get("currency"), rates, settings.DISPLAY_CURRENCY,
            conn=conn)
        date = row.get("date")
        sqlite_ops.insert_transaction(conn, TransactionRow(
            date=date.isoformat() if hasattr(date, "isoformat") else date,
            year=row.get("year"),
            month=row.get("month"),
            value=row.get("value"),
            currency=row.get("currency") or settings.DISPLAY_CURRENCY,
            value_base=value_base,
            rate_used=rate_used,
            type=row.get("type"),
            category=row.get("category"),
            person=row.get("person"),
            description=row.get("description"),
            is_recurring=row.get("is_recurring"),
            is_done=True if row.get("is_done") is None else row.get("is_done"),
            source=row.get("source", TransactionSource.BOT),
        ))
    finally:
        conn.close()


def _check_expected(conn, id: int, expected: dict | None) -> None:
    """Mirror file_storage._row_matches_snapshot: verify Date/Value/Description."""
    if expected is None:
        return
    row = conn.execute(
        f"SELECT * FROM {sqlite_ops.TABLE_TRANSACTIONS} WHERE id = ?", (id,)).fetchone()
    if row is None:
        raise RowMismatchError(f"Transaction {id} no longer exists.")
    mapping = {"Date": "date", "Value": "value", "Description": "description"}
    for label, col in mapping.items():
        if label not in expected:
            continue
        current, target = row[col], expected[label]
        if label == "Date":
            target = target.date().isoformat() if hasattr(target, "date") else \
                     target.isoformat() if hasattr(target, "isoformat") else str(target)
            current = str(current or "")[:10]
            target = str(target)[:10]
        elif label == "Value":
            try:
                current, target = round(float(current), 2), round(float(target), 2)
            except (TypeError, ValueError):
                pass
        else:
            current, target = str(current or ""), str(target or "")
        if current != target:
            raise RowMismatchError(
                f"Transaction {id} no longer matches the selected transaction.")


def delete_transaction_row(id: int, expected: dict | None = None) -> None:
    conn = _conn()
    try:
        _check_expected(conn, id, expected)
        sqlite_ops.delete_transaction(conn, id)
    finally:
        conn.close()


# Excel header name → SQLite column name (for update_transaction_field callers
# that still pass MasterData header names).
_HEADER_TO_COL = {
    "Date": "date", "Year": "year", "Month": "month", "Value": "value",
    "Type": "type", "Category": "category", "Person": "person",
    "Description": "description", "IsRecurring": "is_recurring",
    "IsDone": "is_done", "Currency": "currency", "Value (base)": "value_base",
    "Date Modified (UTC)": "date_modified_utc",
}


def update_transaction_field(id: int, field, value=None, expected: dict | None = None) -> None:
    """
    Update one field (field, value) or several (field as a dict).
    Accepts either MasterData header names or SQLite column names.
    Recomputes value_base/rate_used when value or currency changes.
    """
    updates = dict(field) if isinstance(field, dict) else {field: value}
    updates = {_HEADER_TO_COL.get(k, k): v for k, v in updates.items()}
    conn = _conn()
    try:
        _check_expected(conn, id, expected)
        if "value" in updates or "currency" in updates:
            row = conn.execute(
                f"SELECT value, currency FROM {sqlite_ops.TABLE_TRANSACTIONS} WHERE id = ?",
                (id,)).fetchone()
            if row is None:
                raise RowMismatchError(f"Transaction {id} no longer exists.")
            new_value = updates.get("value", row["value"])
            new_ccy = updates.get("currency", row["currency"])
            rates = sqlite_ops.load_rates_dict(conn)
            vb, rate = sqlite_ops.compute_value_base(
                new_value, new_ccy, rates, settings.DISPLAY_CURRENCY, conn=conn)
            updates.setdefault("value_base", vb)
            updates.setdefault("rate_used", rate)
        sqlite_ops.update_transaction(conn, id, updates)
    finally:
        conn.close()


def get_recent_transactions(n: int = 5) -> list[dict]:
    """
    Return the N most recent transactions as MasterData-header-keyed dicts,
    oldest-first (mirroring file_storage.get_recent_transactions, which
    returns the last N Excel rows in sheet order).

    Each dict carries '_row_idx' — here the real SQLite primary key `id`,
    the same keyspace update_transaction_field / delete_transaction_row
    expect. Used by the /edit and /delete pickers.
    """
    conn = _conn()
    try:
        rows = sqlite_ops.list_transactions(conn, newest_first=True, limit=n)
    finally:
        conn.close()
    rows.reverse()  # oldest-first, like the Excel tail
    return [{
        "Date":                r["date"],
        "Year":                r["year"],
        "Month":               r["month"],
        "Value":               r["value"],
        "Type":                r["type"],
        "Category":            r["category"],
        "Person":              r["person"],
        "Description":         r["description"],
        "IsRecurring":         r["is_recurring"],
        "IsDone":              r["is_done"],
        "Currency":            r["currency"],
        "Value (base)":        r["value_base"],
        "Date Modified (UTC)": r["date_modified_utc"],
        "_row_idx":            r["id"],
    } for r in rows]


# Column order matches the MasterData sheet that data.load_data() reads.
_DF_COLUMNS = [
    "Date", "Year", "Month", "Value", "Type", "Category", "Person",
    "Description", "IsRecurring", "IsDone", "Currency", "Value (base)",
    "Date Modified (UTC)", "_base",
]


def load_transactions(filters: dict | None = None) -> pd.DataFrame:
    """
    Return transactions as a DataFrame shape-compatible with data.load_data():
    same column names, plus the '_base' aggregation column, Year as Int64,
    IsDone as bool, rows without _base/Type/Year/Month dropped.
    """
    _require_db()
    conn = _conn()
    try:
        rows = sqlite_ops.list_transactions(conn, filters)
    finally:
        conn.close()

    df = pd.DataFrame([{
        "Date":                r["date"],
        "Year":                r["year"],
        "Month":               r["month"],
        "Value":               r["value"],
        "Type":                r["type"],
        "Category":            r["category"],
        "Person":              r["person"],
        "Description":         r["description"],
        "IsRecurring":         r["is_recurring"],
        "IsDone":              r["is_done"],
        "Currency":            r["currency"],
        "Value (base)":        r["value_base"],
        "Date Modified (UTC)": r["date_modified_utc"],
        "_base":               r["value_base"],
    } for r in rows], columns=_DF_COLUMNS)

    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    df["Value"] = pd.to_numeric(df["Value"], errors="coerce")
    df["_base"] = pd.to_numeric(df["_base"], errors="coerce")
    df["Currency"] = df["Currency"].fillna(settings.DISPLAY_CURRENCY)
    df["Year"] = pd.to_numeric(df["Year"], errors="coerce").astype("Int64")
    df = df.dropna(subset=["_base", "Type", "Year", "Month"])
    df["IsDone"] = df["IsDone"].fillna(True).astype(bool)
    return df


def load_reference_data() -> dict:
    """
    Mirror data.load_reference_data()'s return shape, sourced from the
    categories / persons / rates / goals tables:

      {months, txn_types, categories, persons, years, budgets, currencies}
    """
    _require_db()
    conn = _conn()
    try:
        cats = conn.execute(
            f"SELECT name, budget_base FROM {sqlite_ops.TABLE_CATEGORIES} "
            f"WHERE active = 1 ORDER BY rowid"
        ).fetchall()
        persons = [r["name"] for r in conn.execute(
            f"SELECT name FROM {sqlite_ops.TABLE_PERSONS} WHERE active = 1 ORDER BY rowid")]
        rates = sqlite_ops.load_rates_dict(conn)
        years = [r["year"] for r in conn.execute(
            f"SELECT DISTINCT year FROM {sqlite_ops.TABLE_TRANSACTIONS} "
            f"WHERE year IS NOT NULL ORDER BY year")]
    finally:
        conn.close()
    return {
        "months":     list(MONTH_NAMES),
        "txn_types":  [t.value for t in TransactionType],
        "categories": [r["name"] for r in cats],
        "persons":    persons,
        "years":      years,
        "budgets":    {r["name"]: r["budget_base"] for r in cats
                       if r["budget_base"] and r["budget_base"] > 0},
        "currencies": list(rates.keys()),
    }
