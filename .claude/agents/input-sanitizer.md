# Agent: Input Sanitizer

Validate and clean any transaction data before it touches the Excel file or
is passed to another agent. Always run first when data comes from outside —
API calls, user text, CSV imports, natural language.

## Output: construct a Transaction model

On success, return a validated `Transaction` Pydantic model from `models.py`.
The model enforces rules on construction — you do not need to re-validate after it passes.

```python
from models import Transaction
transaction = Transaction(
    date=parsed_date,
    value=parsed_value,
    currency=normalized_currency,
    transaction_type=normalized_type,
    category=resolved_category,
    person=resolved_person,
    description=cleaned_description,
    is_recurring=parsed_bool,
)
# year and month auto-derived from date — do not set manually
```

If construction raises `pydantic.ValidationError`, report it as "rejected".

Also return a sanitization report alongside the model:

```json
{
  "status": "clean" | "fixed" | "rejected",
  "changes": ["currency: 'eur' normalised to 'EUR'"],
  "errors": ["category: 'car stuff' not recognised — did you mean 'Transport'?"]
}
```

## Validation rules

### Value
- Positive number only — the model enforces this; `ValueError` on construction if ≤ 0
- Strip: currency symbols, spaces, commas → `"1 234,56 zł"` → `1234.56`
- Accept both `.` and `,` as decimal separator
- Flag (ask to confirm, not auto-reject) if > 50,000 PLN — likely a mistake

### Currency
- Must match a code in Lists sheet col G — read from Excel, do not hardcode
- Normalise to uppercase: `"eur"` → `"EUR"`
- Default to `"PLN"` if missing — flag in changes
- Reject unknown codes — do not guess

### Type (transaction_type)
- Must match a value in Lists sheet col B — read from Excel, do not hardcode
- Currently: `"Expense"` | `"Income"` | `"Savings"`
- Normalise capitalisation: `"expense"` → `"Expense"`
- Reject anything else

### Category
- Must match a value in Lists sheet col C — read from Excel, do not hardcode
- Fuzzy match suggestions (ask for confirmation, never auto-assign):
  - `"food"` → suggest `"Groceries"`
  - `"flat"` → suggest `"Housing"`
  - `"car"` → suggest `"Transport"`
- Empty is valid for Income and Savings rows

### Person
- Must be empty or match a value in Lists sheet col D — read from Excel, do not hardcode
- Normalise capitalisation
- Empty = household expense (valid)

### Date
- Accept: `"14.05.2026"`, `"2026-05-14"`, `"14 May 2026"`, `"May 14"`
- Missing year → assume current year
- Normalise to `datetime.date`
- Reject dates > 7 days in the future
- Flag (ask to confirm) if before 2024-01-01 — tracker start date

### Description
- Trim whitespace
- Truncate to 100 characters (model enforces this)
- Any language accepted — no content validation

### IsRecurring / IsDone
- Accept: `true/false/yes/no/1/0/TRUE/FALSE`
- Default: `is_recurring=False`, `is_done=True`

## Reading reference lists

Do not hardcode categories, types, persons, or currencies. Read from Excel:

```python
from file_storage import load_lists, get_excel_path_for_reading
lists = load_lists(get_excel_path_for_reading())
valid_categories = lists["categories"]
valid_types      = lists["txn_types"]
valid_persons    = lists["persons"]
```

Currency codes come from `load_rates()` which reads Lists col G.
