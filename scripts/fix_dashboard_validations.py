import sys, openpyxl
sys.stdout.reconfigure(encoding='utf-8')
wb = openpyxl.load_workbook('data/Expenses_Improved.xlsx', data_only=False)
ws = wb['Dashboard']
for dv in ws.data_validations.dataValidation:
    f = dv.formula1 or ''
    sqref = str(dv.sqref)
    if 'Lists!$E$2:$E$' in f and 'B2' in sqref:
        dv.formula1 = f.replace('Lists!$E$2:$E$', 'Lists!$F$2:$F$')
        print('Fixed Year:', dv.formula1)
    elif 'Lists!$G$2:$G$' in f and 'F2' in sqref:
        dv.formula1 = f.replace('Lists!$G$2:$G$', 'Lists!$H$2:$H$')
        print('Fixed Currency:', dv.formula1)
wb.save('data/Expenses_Improved.xlsx')
print('Saved.')
