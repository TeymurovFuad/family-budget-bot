import sys, openpyxl
sys.stdout.reconfigure(encoding='utf-8')

wb = openpyxl.load_workbook('data/Expenses_Improved.xlsx', data_only=False)
ws_db = wb['Dashboard']

# Rows with hardcoded budget amounts in col I (Budget column of Expenses by Category)
# H col = category name, I col = budget amount
# Replace =<hardcoded>/$N$2 with VLOOKUP into Lists!$C:$D (Categories / Budget PLN)
fixed = 0
for r in range(11, 28):  # rows 11-27 are the category rows; 28 is TOTAL (SUM)
    cell_h = ws_db.cell(r, 8)   # col H = category name
    cell_i = ws_db.cell(r, 9)   # col I = budget
    val = cell_i.value
    # Only replace hardcoded number formulas (e.g. =2100/$N$2), not SUM rows
    if isinstance(val, str) and val.startswith('=') and 'SUM' not in val and '$N$2' in val:
        cell_i.value = f'=IFERROR(VLOOKUP(H{r},Lists!$C$2:$D$100,2,0),0)/$N$2'
        print(f'  Row {r} ({cell_h.value}): {val} -> {cell_i.value}')
        fixed += 1

print(f'\nFixed {fixed} budget formulas.')
wb.save('data/Expenses_Improved.xlsx')
print('Saved.')
