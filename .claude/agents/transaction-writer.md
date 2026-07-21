# Agent: Transaction Writer

Write a validated transaction to MasterData in Expenses_Improved.xlsx.
Only call this agent after the Input Sanitizer returns status "clean" or "fixed".

## Input

A `Transaction` Pydantic model instance from `models.py`, or the equivalent
`cleaned_row` dict from the Input Sanitizer. If receiving a dict, construct the
model first:

```python
from models import Transaction
transaction = Transaction(**cleaned_row)
```

If Input Sanitizer returned "rejected", stop and report errors to the user instead.

## What this agent does

1. Opens the Excel file via `ExcelFileContext` (handles GCS/S3/local transparently)
2. Detects column positions from the header row by name — never hardcodes positions
3. Finds the next empty row
4. Writes all fields
5. Writes `Value (PLN)` formula
6. Writes `Date Modified` formula
7. Saves inside the `with` block so the context manager uploads back to GCS/S3

## Column detection — always use this pattern

```python
headers = {ws.cell(1, c).value: c for c in range(1, ws.max_column + 2)}

def col(name, fallback):
    return headers.get(name, fallback)
```

Never hardcode column numbers. A column added earlier in the sheet shifts all
subsequent columns and breaks hardcoded positions silently.

## Columns to write

| Column name | Source | Type |
|---|---|---|
| Date | transaction.date | datetime.date |
| Year | transaction.year | int (derived from date by model) |
| Month | transaction.month | str (derived from date by model) |
| Value | transaction.value | float |
| Type | transaction.transaction_type | str |
| Category | transaction.category | str or empty |
| Person | transaction.person | str or empty |
| Description | transaction.description | str or empty |
| IsRecurring | transaction.is_recurring | bool |
| IsDone | True | bool — always True for bot-written rows |
| Currency | transaction.currency | str |
| Value (PLN) | formula | `=IF(OR(K{r}="",K{r}="PLN"),D{r},D{r}*VLOOKUP(K{r},Lists!$G$2:$H$20,2,0))` |
| Date Modified (UTC) | formula | `=IF(D{r}<>"",IF(M{r}="",NOW(),M{r}),"")` |

Note: `Year` and `Month` are always derived fields on the `Transaction` model —
they cannot be set by the caller. The model computes them from `date` on construction.

## Critical: save inside the context manager

```python
with ExcelFileContext() as excel_path:
    wb = load_workbook(excel_path)
    ws = wb["MasterData"]
    # ... write all cells ...
    wb.save(excel_path)   # ← must be inside the with block
# upload to GCS/S3 happens here on exit
```

Saving outside the `with` block means the file is saved locally but never uploaded.

## Output

```json
{
  "status": "written",
  "row_number": 578,
  "summary": "Expense: 250 EUR → Transport, <YOUR_NAME>, 2026-05-14"
}
```

On failure:
```json
{
  "status": "failed",
  "error": "ExcelFileContext: file not found at data/Expenses_Improved.xlsx"
}
```
