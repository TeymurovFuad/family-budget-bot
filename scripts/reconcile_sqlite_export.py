"""
reconcile_sqlite_export.py — verify SQLite ↔ Excel export consistency.

Generates an export workbook from the current SQLite state, then compares
SQLite's own aggregate totals (SUM(value_base) grouped by year/month)
against the generated workbook's MasterData sheet totals.

Exits 0 when everything matches, 1 on any mismatch.

Usage:
    python scripts/reconcile_sqlite_export.py [--db PATH] [--template PATH] [--out PATH]
"""

import argparse
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import settings
import sqlite_ops
from excel_export import generate_excel_from_sqlite

_TOLERANCE = 0.01


def sqlite_totals(db_path) -> dict[tuple, float]:
    conn = sqlite_ops.init_db(db_path)
    try:
        return {
            (r["year"], r["month"]): r["total"]
            for r in conn.execute(
                f"SELECT year, month, SUM(value_base) AS total "
                f"FROM {sqlite_ops.TABLE_TRANSACTIONS} GROUP BY year, month")
        }
    finally:
        conn.close()


def workbook_totals(xlsx_path) -> dict[tuple, float]:
    import pandas as pd
    df = pd.read_excel(xlsx_path, sheet_name="MasterData")
    df = df.dropna(subset=["Value (base)"])
    if df.empty:
        return {}
    grouped = df.groupby(["Year", "Month"], dropna=False)["Value (base)"].sum()
    return {(int(y), m): float(t) for (y, m), t in grouped.items()}


def reconcile(db_path, template_path, output_path) -> list[str]:
    """Return a list of mismatch descriptions (empty = fully reconciled)."""
    generate_excel_from_sqlite(db_path, template_path, output_path)
    db_tot = sqlite_totals(db_path)
    wb_tot = workbook_totals(output_path)

    mismatches = []
    for key in sorted(set(db_tot) | set(wb_tot), key=str):
        a, b = db_tot.get(key), wb_tot.get(key)
        if a is None or b is None or abs(a - b) > _TOLERANCE:
            mismatches.append(f"{key}: sqlite={a} workbook={b}")
    return mismatches


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Reconcile SQLite totals against a generated Excel export")
    parser.add_argument("--db", default=None)
    parser.add_argument("--template", default=None)
    parser.add_argument("--out", default=None,
                        help="Export path (default: a temp file, discarded after the check)")
    args = parser.parse_args(argv)

    db_path = args.db or settings.SQLITE_DB_PATH
    template = args.template or settings.DEFAULT_TEMPLATE_PATH
    out = Path(args.out) if args.out else Path(tempfile.mkdtemp()) / "reconcile_export.xlsx"

    mismatches = reconcile(db_path, template, out)
    if mismatches:
        print(f"MISMATCH — {len(mismatches)} (year, month) group(s) differ:")
        for m in mismatches:
            print(f"  {m}")
        return 1
    print("OK — SQLite totals match the generated workbook.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
