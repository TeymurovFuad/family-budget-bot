"""
rename_category.py — atomically rename a category everywhere in a workbook:
Lists Categories column, all MasterData rows, and the Dashboard budget table.

Usage:  python scripts/rename_category.py "Old Name" "New Name" [path-to-xlsx]
"""
import os
import shutil
import sys

import openpyxl

# Scripts share the bot's configuration — .env is the single source of truth.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import settings

sys.stdout.reconfigure(encoding="utf-8")

if len(sys.argv) < 3:
    print('Usage: python scripts/rename_category.py "Old Name" "New Name" [xlsx]')
    sys.exit(1)

old_name, new_name = sys.argv[1], sys.argv[2]
path = sys.argv[3] if len(sys.argv) > 3 else str(settings.XLSX_PATH)

shutil.copy2(path, path + ".bak")
print(f"Backup: {path}.bak")

wb = openpyxl.load_workbook(path, data_only=False)
counts = {"Lists": 0, "MasterData": 0, "Dashboard": 0}

# Lists: Categories column
ws = wb["Lists"]
cat_col = next((c for c in range(1, ws.max_column + 1)
                if str(ws.cell(1, c).value or "").strip() == "Categories"), None)
if cat_col:
    for r in range(2, ws.max_row + 1):
        if str(ws.cell(r, cat_col).value or "").strip() == old_name:
            ws.cell(r, cat_col, new_name)
            counts["Lists"] += 1

# MasterData: Category column, all rows
ws = wb["MasterData"]
cat_col = next((c for c in range(1, ws.max_column + 1)
                if str(ws.cell(1, c).value or "").strip() == "Category"), None)
if cat_col:
    for r in range(2, ws.max_row + 1):
        if str(ws.cell(r, cat_col).value or "").strip() == old_name:
            ws.cell(r, cat_col, new_name)
            counts["MasterData"] += 1

# Dashboard: category names appear as plain values in the budget table
ws = wb["Dashboard"]
for r in range(1, ws.max_row + 1):
    for c in range(1, ws.max_column + 1):
        if str(ws.cell(r, c).value or "").strip() == old_name:
            ws.cell(r, c, new_name)
            counts["Dashboard"] += 1

wb.save(path)
for sheet, n in counts.items():
    print(f"{sheet}: {n} cell(s) renamed")
print(f"Done: '{old_name}' -> '{new_name}'")
