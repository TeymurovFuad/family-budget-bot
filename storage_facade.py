"""
storage_facade.py — the single storage interface the bot (and the S2 web UI)
calls (Cycle S1 foundation, wired into the handlers in Phase 2).

Backed by SQLite (sqlite_ops.py). Function signatures deliberately mirror
today's Excel-backed call sites so the Phase 2 swap is mechanical:

  append_transaction(txn)          ↔ excel_ops.append_transaction
  append_transactions_batch(txns)  ↔ file_storage.append_transactions_batch
  delete_transaction_row(id, ...)  ↔ file_storage.delete_transaction_row
  update_transaction_field(...)    ↔ file_storage.update_transaction_field
  get_recent_transactions(n)       ↔ file_storage.get_recent_transactions
  load_transactions()              ↔ data.load_data() (same DataFrame columns)
  load_reference_data()            ↔ data.load_reference_data() (same keys)

This module structurally satisfies storage_protocol.StorageBackend — any
future backend must expose the same five callables.
"""

import asyncio
import logging
from datetime import date as _date, datetime, timezone
from pathlib import Path

import pandas as pd

import settings
import sqlite_ops
from models import MONTH_NAMES
from validators import make_dedup_key, make_loose_dedup_key
from sqlite_types import (
    SyncDirection, SyncStatus, TransactionRow, TransactionSource, TransactionType,
)

log = logging.getLogger(__name__)


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


class ConflictError(Exception):
    """Optimistic lock mismatch — another writer modified the row first."""


def _to_row_dict(transaction) -> dict:
    """Accept a models.Transaction or a plain to_row()-style dict."""
    return transaction.to_row() if hasattr(transaction, "to_row") else dict(transaction)


def _build_txn_row(row: dict, value_base: float, rate_used: float) -> TransactionRow:
    date = row.get("date")
    return TransactionRow(
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
    )


def append_transaction(transaction) -> None:
    """Compute value_base/rate_used and insert into SQLite."""
    row = _to_row_dict(transaction)
    conn = _conn()
    try:
        rates = sqlite_ops.load_rates_dict(conn)
        value_base, rate_used = sqlite_ops.compute_value_base(
            row["value"], row.get("currency"), rates, settings.DISPLAY_CURRENCY,
            conn=conn)
        sqlite_ops.insert_transaction(conn, _build_txn_row(row, value_base, rate_used))
    finally:
        conn.close()


def append_transactions_batch(transactions: list) -> None:
    """
    Insert multiple transactions in ONE SQLite transaction (all-or-nothing).

    Mirrors file_storage.append_transactions_batch's guarantee: the Excel
    version writes every row to the in-memory workbook and saves once at the
    end, so a mid-batch failure persists nothing. Here every insert runs with
    commit=False inside a single implicit transaction; any exception rolls
    the whole batch back before re-raising.
    """
    if not transactions:
        return
    conn = _conn()
    try:
        rates = sqlite_ops.load_rates_dict(conn)
        display = str(settings.DISPLAY_CURRENCY).strip().upper()
        unknown_ccys: set[str] = set()
        try:
            for transaction in transactions:
                row = _to_row_dict(transaction)
                # conn=None: compute_value_base's unknown-currency sync_log
                # write would COMMIT mid-batch and break atomicity. Collect
                # unknown currencies and log them after the batch commits.
                value_base, rate_used = sqlite_ops.compute_value_base(
                    row["value"], row.get("currency"), rates,
                    settings.DISPLAY_CURRENCY, conn=None)
                ccy = str(row.get("currency") or "").strip().upper()
                if ccy and ccy != display and ccy not in rates:
                    unknown_ccys.add(ccy)
                sqlite_ops.insert_transaction(
                    conn, _build_txn_row(row, value_base, rate_used), commit=False)
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        for ccy in sorted(unknown_ccys):
            sqlite_ops.log_sync(
                conn, SyncDirection.IMPORT, SyncStatus.ERROR,
                f"unknown currency '{ccy}' — no rate found, fell back to "
                f"rate 1.0 (Excel VLOOKUP would be #N/A)")
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


def load_transactions(filters: dict | None = None, *,
                      date_from=None, date_to=None,
                      description_contains: str | None = None,
                      sort_by: str | None = None, sort_dir: str = "asc",
                      limit: int | None = None,
                      offset: int | None = None) -> pd.DataFrame:
    """
    Return transactions as a DataFrame shape-compatible with data.load_data():
    same column names, plus the '_base' aggregation column, Year as Int64,
    IsDone as bool, rows without _base/Type/Year/Month dropped.

    Keyword-only params pass straight through to sqlite_ops.list_transactions
    (date range, description search, whitelisted sorting, pagination).
    """
    _require_db()
    conn = _conn()
    try:
        rows = sqlite_ops.list_transactions(
            conn, filters, date_from=date_from, date_to=date_to,
            description_contains=description_contains,
            sort_by=sort_by, sort_dir=sort_dir, limit=limit, offset=offset)
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

    # "_id" carries the SQLite primary key for write-path operations (edit/delete).
    # It lives outside _DF_COLUMNS so the golden master column test (which compares
    # sqlite_df.columns to excel_df.columns) continues to pass.
    df["_id"] = [r["id"] for r in rows]

    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    df["Value"] = pd.to_numeric(df["Value"], errors="coerce")
    df["_base"] = pd.to_numeric(df["_base"], errors="coerce")
    df["Currency"] = df["Currency"].fillna(settings.DISPLAY_CURRENCY)
    df["Year"] = pd.to_numeric(df["Year"], errors="coerce").astype("Int64")
    df = df.dropna(subset=["_base", "Type", "Year", "Month"])
    df["IsDone"] = df["IsDone"].fillna(True).astype(bool)
    return df


def count_transactions(filters: dict | None = None, *,
                       date_from=None, date_to=None,
                       description_contains: str | None = None) -> int:
    """Total matching row count for pagination — same filter surface as
    load_transactions minus sort/pagination."""
    _require_db()
    conn = _conn()
    try:
        return sqlite_ops.count_transactions(
            conn, filters, date_from=date_from, date_to=date_to,
            description_contains=description_contains)
    finally:
        conn.close()


def load_dedup_evidence(start=None, end=None) -> dict:
    """
    SQLite twin of data.load_dedup_evidence(): multiset evidence of stored
    transactions for dedup-v2's count-aware, two-pass scan. Returns:

        {
          "strict": {strict_key: [(date_iso, description), ...]},
          "loose":  {loose_key:  [(date_iso, description), ...]},
        }

    strict_key = date|value|currency|cleaned-description (validators.make_dedup_key)
    loose_key  = date|value|currency, no description (validators.make_loose_dedup_key)

    len(evidence["strict"][key]) / len(evidence["loose"][key]) is that key's
    multiset count in the transactions table. Only rows whose date falls in
    [start, end] (date objects, both optional/inclusive) are counted; dates
    are compared on their first 10 chars so a stray time component never
    excludes a boundary day. Returns empty dicts on any read failure —
    dedup never blocks an import, it just stops flagging anything.
    """
    empty = {"strict": {}, "loose": {}}
    try:
        # Read-path guard (consistent with load_transactions/load_reference_data):
        # never auto-create the DB from a read. Unlike those, a missing DB is
        # not fatal here — the except below turns it into empty evidence,
        # because dedup must never block an import.
        _require_db()
        conn = _conn()
        try:
            where = ["date IS NOT NULL", "value IS NOT NULL"]
            params: list = []
            if start is not None:
                where.append("substr(date, 1, 10) >= ?")
                params.append(start.isoformat() if hasattr(start, "isoformat") else str(start)[:10])
            if end is not None:
                where.append("substr(date, 1, 10) <= ?")
                params.append(end.isoformat() if hasattr(end, "isoformat") else str(end)[:10])
            rows = conn.execute(
                f"SELECT date, value, currency, description "
                f"FROM {sqlite_ops.TABLE_TRANSACTIONS} WHERE {' AND '.join(where)}",
                params,
            ).fetchall()
        finally:
            conn.close()
        strict: dict[str, list[tuple[str, str]]] = {}
        loose: dict[str, list[tuple[str, str]]] = {}
        for r in rows:
            try:
                date_iso = _date.fromisoformat(str(r["date"])[:10]).isoformat()
            except ValueError:
                continue  # unparseable date — mirror the Excel reader's coerce+drop
            value = r["value"]
            ccy = r["currency"] or settings.DISPLAY_CURRENCY
            desc = r["description"] if r["description"] is not None else ""
            strict_key = make_dedup_key(date_iso, value, ccy, desc)
            loose_key = make_loose_dedup_key(date_iso, value, ccy)
            strict.setdefault(strict_key, []).append((date_iso, str(desc)))
            loose.setdefault(loose_key, []).append((date_iso, str(desc)))
        return {"strict": strict, "loose": loose}
    except Exception as e:
        log.warning("Could not load dedup evidence from SQLite: %s", e)
        return empty


def _add_web_transaction_sync(fields: dict) -> int:
    """Blocking insert for a web-sourced transaction. Returns the new row id."""
    row = dict(fields)
    row["source"] = TransactionSource.WEB
    conn = _conn()
    try:
        rates = sqlite_ops.load_rates_dict(conn)
        value = row.get("value", 0.0)
        currency = row.get("currency") or settings.DISPLAY_CURRENCY
        value_base, rate_used = sqlite_ops.compute_value_base(
            value, currency, rates, settings.DISPLAY_CURRENCY, conn=conn)
        txn_row = TransactionRow(
            date=row.get("date"),
            year=row.get("year"),
            month=row.get("month"),
            value=value,
            currency=currency,
            value_base=value_base,
            rate_used=rate_used,
            type=row.get("type"),
            category=row.get("category"),
            person=row.get("person"),
            description=row.get("description"),
            is_recurring=False,
            is_done=True,
            source=TransactionSource.WEB,
        )
        return sqlite_ops.insert_transaction(conn, txn_row)
    finally:
        conn.close()


async def add_web_transaction(fields: dict) -> int:
    """Insert a web-sourced transaction. Returns the new row id."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _add_web_transaction_sync, fields)


def _update_web_transaction_sync(id: int, lock_token: str, fields: dict) -> None:
    """Blocking update with BEGIN IMMEDIATE and optimistic-lock check."""
    conn = _conn()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            f"SELECT date_modified_utc FROM {sqlite_ops.TABLE_TRANSACTIONS} WHERE id = ?",
            (id,)).fetchone()
        if row is None:
            conn.rollback()
            raise KeyError(f"Transaction {id} not found.")
        stored_token = row["date_modified_utc"] or ""
        if stored_token != lock_token:
            conn.rollback()
            raise ConflictError(
                f"Transaction {id} was modified by another writer. Reload and retry.")
        updates = dict(fields)
        updates["date_modified_utc"] = datetime.now(timezone.utc).isoformat()
        bad = [k for k in updates if k not in sqlite_ops._TXN_COLUMNS]
        if bad:
            conn.rollback()
            raise ValueError(f"Unknown transaction column(s): {bad}")
        assignments = ", ".join(f"{k} = ?" for k in updates)
        conn.execute(
            f"UPDATE {sqlite_ops.TABLE_TRANSACTIONS} SET {assignments} WHERE id = ?",
            [*updates.values(), id])
        conn.commit()
    except (ConflictError, KeyError, ValueError):
        raise
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


async def update_web_transaction(id: int, lock_token: str, fields: dict) -> None:
    """Update a transaction with optimistic-lock check. Raises ConflictError on mismatch."""
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _update_web_transaction_sync, id, lock_token, fields)


def _delete_web_transaction_sync(id: int, lock_token: str) -> None:
    """Blocking delete with BEGIN IMMEDIATE and optimistic-lock check."""
    conn = _conn()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            f"SELECT date_modified_utc FROM {sqlite_ops.TABLE_TRANSACTIONS} WHERE id = ?",
            (id,)).fetchone()
        if row is None:
            conn.rollback()
            raise KeyError(f"Transaction {id} not found.")
        stored_token = row["date_modified_utc"] or ""
        if stored_token != lock_token:
            conn.rollback()
            raise ConflictError(
                f"Transaction {id} was modified by another writer. Reload and retry.")
        conn.execute(
            f"DELETE FROM {sqlite_ops.TABLE_TRANSACTIONS} WHERE id = ?", (id,))
        conn.commit()
    except (ConflictError, KeyError):
        raise
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


async def delete_web_transaction(id: int, lock_token: str) -> None:
    """Delete a transaction with optimistic-lock check. Raises ConflictError on mismatch."""
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _delete_web_transaction_sync, id, lock_token)


def _load_transaction_by_id_sync(txn_id: int) -> dict | None:
    import sqlite3 as _sqlite3
    conn = _sqlite3.connect(settings.SQLITE_DB_PATH)
    conn.row_factory = _sqlite3.Row
    row = conn.execute(
        f"SELECT * FROM {sqlite_ops.TABLE_TRANSACTIONS} WHERE id = ?", (txn_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


async def load_transaction_by_id(txn_id: int) -> dict | None:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _load_transaction_by_id_sync, txn_id)


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


# ── Context-manager connection helper ─────────────────────────────────────────

from contextlib import contextmanager as _contextmanager


@_contextmanager
def _get_conn():
    """Open a connection and ensure it is closed on exit."""
    conn = _conn()
    try:
        yield conn
    finally:
        conn.close()


# ── Excel export hook ─────────────────────────────────────────────────────────

def _schedule_excel_export() -> None:
    """Hook for triggering an async Excel re-export after writes.

    Calls excel_export.schedule_export() if that function exists; otherwise
    a no-op placeholder until the export job is wired up.
    """
    try:
        import excel_export as _excel_export
        if hasattr(_excel_export, "schedule_export"):
            _excel_export.schedule_export()
    except Exception:
        pass


# ── Aliases ───────────────────────────────────────────────────────────────────

RowMovedError = RowMismatchError


# ── Sync reads ────────────────────────────────────────────────────────────────

def load_rates() -> dict[str, float]:
    with _get_conn() as conn:
        return sqlite_ops.load_rates_dict(conn)


def load_budgets() -> dict[str, float]:
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT name, budget_base FROM categories WHERE active=1 AND budget_base > 0"
        ).fetchall()
        return {r["name"]: r["budget_base"] for r in rows}


def load_cycles() -> list[tuple]:
    from datetime import date as _date2
    with _get_conn() as conn:
        return [(_date2.fromisoformat(r["start_date"]), r["label"])
                for r in sqlite_ops.list_cycles(conn)]


def load_salary_keywords() -> list[str]:
    with _get_conn() as conn:
        return sqlite_ops.list_salary_keywords(conn)


def load_category_types() -> dict[str, str]:
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT name, category_type FROM categories WHERE active=1"
        ).fetchall()
        return {r["name"]: r["category_type"] or "Expense" for r in rows}


def get_recent_transactions_raw(n: int = 5) -> list[dict]:
    """Return the N most-recent transactions as plain dicts (SQLite column names)."""
    with _get_conn() as conn:
        rows = conn.execute(
            f"SELECT * FROM {sqlite_ops.TABLE_TRANSACTIONS} ORDER BY id DESC LIMIT ?", (n,)
        ).fetchall()
        return list(reversed([dict(r) for r in rows]))


# ── Async writes ──────────────────────────────────────────────────────────────

async def async_update_currency_rates(new_rates: dict, user=None) -> None:
    def _sync():
        with _get_conn() as conn:
            for currency, rate in new_rates.items():
                sqlite_ops.upsert_rate(conn, currency, float(rate))
        _schedule_excel_export()
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _sync)


async def async_update_category_budget(category: str, new_budget_base: float) -> None:
    def _sync():
        with _get_conn() as conn:
            sqlite_ops.upsert_category(conn, category, budget_base=new_budget_base)
        _schedule_excel_export()
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _sync)


async def async_record_cycle_start(start, label: str) -> bool:
    def _sync():
        with _get_conn() as conn:
            existing_rows = sqlite_ops.list_cycles(conn)
            existing_dates_iso = [r["start_date"] for r in existing_rows]
            if start.isoformat() in existing_dates_iso:
                return False
            sqlite_ops.upsert_cycle(conn, start.isoformat(), label)
            _schedule_excel_export()
            return True
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _sync)


async def async_remove_cycle_start(start) -> bool:
    def _sync():
        with _get_conn() as conn:
            result = sqlite_ops.delete_cycle(conn, start.isoformat())
        _schedule_excel_export()
        return result
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _sync)


async def async_save_salary_keyword(keyword: str) -> bool:
    def _sync():
        with _get_conn() as conn:
            return sqlite_ops.insert_salary_keyword(conn, keyword)
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _sync)


async def async_delete_salary_keyword(keyword: str) -> bool:
    def _sync():
        with _get_conn() as conn:
            return sqlite_ops.delete_salary_keyword_row(conn, keyword)
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, _sync)


async def async_apply_category_setup(
    categories: list[tuple[str, str]], renames: list[tuple[str, str]]
) -> None:
    def _sync():
        with _get_conn() as conn:
            for old, new in renames:
                sqlite_ops.rename_category(conn, old, new)
            rows = conn.execute(
                "SELECT name, budget_base FROM categories WHERE active=1 AND budget_base > 0"
            ).fetchall()
            existing_budgets = {r["name"]: r["budget_base"] for r in rows}
            sqlite_ops.replace_categories(conn, categories, existing_budgets)
        _schedule_excel_export()
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _sync)