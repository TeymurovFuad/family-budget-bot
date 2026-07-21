"""
fix_validation_ranges.py — extend MasterData dropdown validation ranges so
every data row (and headroom below) shows its dropdown list again.

Usage:  python scripts/fix_validation_ranges.py [path-to-xlsx]
"""
import os
import sys

import openpyxl

# Scripts share the bot's configuration — .env is the single source of truth.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import settings
from excel_schema import extend_validation_ranges, find_next_data_row
from _repair_guard import repair_guard
from file_storage import atomic_save

sys.stdout.reconfigure(encoding="utf-8")


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else str(settings.XLSX_PATH)

    with repair_guard():
        wb = openpyxl.load_workbook(path)
        ws = wb["MasterData"]

        last_row = find_next_data_row(ws) - 1
        print(f"Last data row: {last_row}")
        print("Before:")
        for dv in ws.data_validations.dataValidation:
            print(f"  {dv.sqref}: {dv.formula1}")

        extend_validation_ranges(ws, last_row)

        print("After:")
        for dv in ws.data_validations.dataValidation:
            print(f"  {dv.sqref}: {dv.formula1}")

        atomic_save(wb, path)
        print("Saved.")


if __name__ == "__main__":
    main()
