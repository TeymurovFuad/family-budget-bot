import sys, openpyxl

from _repair_guard import repair_guard
from file_storage import atomic_save

sys.stdout.reconfigure(encoding='utf-8')
PATH = 'data/Expenses_Improved.xlsx'

with repair_guard():
    wb = openpyxl.load_workbook(PATH, data_only=False)
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
    atomic_save(wb, PATH)
    print('Saved.')
