"""
import_excel_to_sqlite.py — one-time Excel → SQLite migration (Cycle S1 Phase 1).

Reads MasterData + Lists via the existing readers (data.load_data,
excel_schema.load_currency_rates_from_path, file_storage.load_lists),
computes value_base/rate_used via sqlite_ops.compute_value_base, and inserts
into the SQLite store. Safe to re-run: the content_hash UNIQUE constraint
skips rows already imported (skip count is reported).

Usage:
    python scripts/import_excel_to_sqlite.py [--db PATH] [--dry-run]
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

import settings
import sqlite_ops
from excel_schema import load_currency_rates_from_path
from sqlite_types import SyncDirection, SyncStatus, TransactionRow, TransactionSource


def _clean(v):
    """NaN/NaT → None; pandas scalars → python scalars."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    return v


def df_row_to_txn(row, rates: dict[str, float]) -> TransactionRow:
    """Map one data.load_data() DataFrame row to a TransactionRow."""
    value = float(row["Value"])
    currency = str(_clean(row.get("Currency")) or settings.DISPLAY_CURRENCY).strip().upper()
    value_base, rate_used = sqlite_ops.compute_value_base(
        value, currency, rates, settings.DISPLAY_CURRENCY)

    date = _clean(row.get("Date"))
    if hasattr(date, "date"):
        date = date.date()
    date_modified = _clean(row.get("Date Modified (UTC)"))

    return TransactionRow(
        date=date.isoformat() if date is not None else None,
        year=int(row["Year"]),
        month=_clean(row.get("Month")),
        value=value,
        currency=currency,
        value_base=value_base,
        rate_used=rate_used,
        type=_clean(row.get("Type")),
        category=_clean(row.get("Category")),
        person=_clean(row.get("Person")),
        description=_clean(row.get("Description")),
        is_recurring=bool(_clean(row.get("IsRecurring")) or False),
        is_done=bool(row.get("IsDone", True)),
        date_modified_utc=str(date_modified) if date_modified is not None else None,
        source=TransactionSource.EXCEL_IMPORT,
    )


def run_import(db_path=None, dry_run: bool = False) -> dict:
    """Import the current workbook into SQLite. Returns counters."""
    from data import load_data
    from file_storage import get_excel_path_for_reading, load_lists

    excel_path = get_excel_path_for_reading()
    df = load_data()
    rates = load_currency_rates_from_path(excel_path)
    lists = load_lists(excel_path)

    db_path = db_path or settings.SQLITE_DB_PATH
    stats = {"total": len(df), "inserted": 0, "skipped": 0}

    if dry_run:
        # Report against the current DB state without writing.
        conn = sqlite_ops.init_db(db_path)
        try:
            existing = {r["content_hash"] for r in conn.execute(
                f"SELECT content_hash FROM {sqlite_ops.TABLE_TRANSACTIONS}")}
        finally:
            conn.close()
        for _, row in df.iterrows():
            txn = df_row_to_txn(row, rates)
            h = sqlite_ops.content_hash_for_row(
                txn.date, txn.value, txn.currency, txn.type,
                txn.category, txn.person, txn.description,
                txn.date_modified_utc)
            stats["skipped" if h in existing else "inserted"] += 1
        return stats

    conn = sqlite_ops.init_db(db_path)
    try:
        count_sql = f"SELECT COUNT(*) FROM {sqlite_ops.TABLE_TRANSACTIONS}"
        before = conn.execute(count_sql).fetchone()[0]
        for _, row in df.iterrows():
            sqlite_ops.insert_transaction(conn, df_row_to_txn(row, rates))
        after = conn.execute(count_sql).fetchone()[0]
        stats["inserted"] = after - before
        stats["skipped"] = stats["total"] - stats["inserted"]

        for ccy, rate in rates.items():
            sqlite_ops.upsert_rate(conn, ccy, rate)
        budgets = lists.get("budgets", {})
        for cat in lists.get("categories", []):
            sqlite_ops.upsert_category(conn, str(cat), budgets.get(str(cat)))
        for person in lists.get("persons", []):
            sqlite_ops.upsert_person(conn, str(person))

        sqlite_ops.log_sync(conn, SyncDirection.IMPORT, SyncStatus.OK,
                            f"inserted={stats['inserted']} skipped={stats['skipped']}")
    finally:
        conn.close()
    return stats


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Import Excel workbook into SQLite")
    parser.add_argument("--db", default=None, help="SQLite path (default: settings.SQLITE_DB_PATH)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Report what would be imported without writing")
    args = parser.parse_args(argv)

    stats = run_import(db_path=args.db, dry_run=args.dry_run)
    mode = "DRY RUN — would import" if args.dry_run else "Imported"
    print(f"{mode}: {stats['inserted']} new, {stats['skipped']} skipped "
          f"(already present), {stats['total']} total rows read")
    return 0


if __name__ == "__main__":
    sys.exit(main())
