"""
fix_formula_bounds.py
=====================
One-time repair for live workbooks created before the open-ended formula fix.

What it does:
  1. Rewrites bounded Dashboard ranges like MasterData!$L$2:$L$2000 and
     Lists!$C$2:$D$100 to use Excel's max row ($1048576) in every formula cell
     across all sheets.
  2. Ensures Monthly Summary has a formula row for every (Year, Month)
     combination already in MasterData, so historical imports are visible
     immediately.

Safe to run multiple times — it skips already-fixed formulas and already-present
Monthly Summary rows. Writes a .bak backup before saving.

Usage (on the bot machine):
  python scripts/fix_formula_bounds.py
  python scripts/fix_formula_bounds.py --path /path/to/Expenses_Improved.xlsx
"""

import sys
import shutil
import argparse
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from _repair_guard import repair_guard


def main(xlsx_path: Path) -> None:
    if not xlsx_path.exists():
        print(f"ERROR: file not found: {xlsx_path}")
        sys.exit(1)

    bak = xlsx_path.with_suffix(f".bak_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx")
    shutil.copy2(xlsx_path, bak)
    print(f"Backup: {bak.name}")

    import openpyxl
    from file_storage import atomic_save
    from excel_schema import repair_dashboard_bounds, ensure_monthly_summary_rows_from_masterdata

    wb = openpyxl.load_workbook(xlsx_path, data_only=False)

    n_formulas = repair_dashboard_bounds(wb)
    print(f"Formula bounds updated: {n_formulas} cell(s)")

    n_ms = ensure_monthly_summary_rows_from_masterdata(wb)
    print(f"Monthly Summary rows added: {n_ms}")

    if n_formulas or n_ms:
        atomic_save(wb, xlsx_path)
        print(f"Saved: {xlsx_path}")
    else:
        print("Nothing to fix — workbook already up to date.")


if __name__ == "__main__":
    from settings import XLSX_PATH as DEFAULT_PATH

    parser = argparse.ArgumentParser(description="Fix formula bounds and Monthly Summary gaps.")
    parser.add_argument("--path", type=Path, default=DEFAULT_PATH,
                        help="Path to Excel file (default: from XLSX_PATH env / settings)")
    args = parser.parse_args()

    with repair_guard():
        main(args.path)
