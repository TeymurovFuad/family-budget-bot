"""
migrate_pln_headers_to_base.py — one-time migration for pre-existing workbooks
created before the PLN -> base currency rename.

Older workbooks have header cells literally named "Value (PLN)",
"Budget (PLN)", and "Rate to PLN" (row 1 of MasterData / Lists). The bot's
schema now looks up "Value (base)", "Budget (base)", and "Rate to base"
instead, so on an un-migrated workbook those header lookups silently miss:
budget writes become no-ops and currency-rate loading falls back to a
default {"PLN": 1.0} rate table.

Run this ONCE, after upgrading to a version of the bot that expects the
"(base)" headers, against any workbook created with an older version.
Freshly generated workbooks (from the current Expenses_Template.xlsx) are
unaffected and do not need this script.

Usage:  python scripts/migrate_pln_headers_to_base.py [path-to-xlsx]
        (defaults to settings.XLSX_PATH if no path is given)
"""
import os
import shutil
import sys

import openpyxl

# Scripts share the bot's configuration — .env is the single source of truth.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import settings
from _repair_guard import repair_guard
from file_storage import atomic_save

sys.stdout.reconfigure(encoding="utf-8")

RENAMES = {
    "Value (PLN)": "Value (base)",
    "Budget (PLN)": "Budget (base)",
    "Rate to PLN": "Rate to base",
}


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else str(settings.XLSX_PATH)

    if not os.path.exists(path):
        print(f"File not found: {path}")
        sys.exit(1)

    with repair_guard():
        shutil.copy2(path, path + ".bak")
        print(f"Backup: {path}.bak")

        wb = openpyxl.load_workbook(path, data_only=False)
        counts = {old: 0 for old in RENAMES}

        for ws in wb.worksheets:
            for row in ws.iter_rows(max_row=1):
                for cell in row:
                    val = str(cell.value or "").strip()
                    if val in RENAMES:
                        cell.value = RENAMES[val]
                        counts[val] += 1
                        print(f"  {ws.title}!{cell.coordinate}: '{val}' -> '{RENAMES[val]}'")

        atomic_save(wb, path)

        total = sum(counts.values())
        if total == 0:
            print("No old-style headers found — workbook already migrated (or never affected).")
        else:
            for old, n in counts.items():
                if n:
                    print(f"{old}: {n} header(s) renamed")
            print(f"Done: {total} header(s) migrated in {path}")


if __name__ == "__main__":
    main()
