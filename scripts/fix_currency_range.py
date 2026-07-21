import sys, openpyxl

from _repair_guard import repair_guard
from file_storage import atomic_save

sys.stdout.reconfigure(encoding='utf-8')
PATH = "data/Expenses_Improved.xlsx"

with repair_guard():
    wb = openpyxl.load_workbook(PATH, data_only=False)

    ws_li = wb["Lists"]
    # Find last real currency row in col H (3-letter alpha codes only)
    last_ccy_row = 1
    for r in range(2, ws_li.max_row + 1):
        val = ws_li.cell(r, 8).value  # col H = 8
        if val is None:
            break
        if isinstance(val, str) and len(val.strip()) == 3 and val.strip().isalpha():
            last_ccy_row = r

    print(f"Last currency row: {last_ccy_row}")

    ws_md = wb["MasterData"]
    for dv in ws_md.data_validations.dataValidation:
        f = dv.formula1 or ""
        if "Lists!$H$2:$H$" in f and "K2" in str(dv.sqref):
            old = dv.formula1
            dv.formula1 = f"Lists!$H$2:$H${last_ccy_row}"
            print(f"Fixed: {old} -> {dv.formula1}")

    atomic_save(wb, PATH)
    print("Saved.")
