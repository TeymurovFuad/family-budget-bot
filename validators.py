"""
validators.py — shared validation and normalization for all transaction entry
paths (/add, quick-add, /bulk). No I/O, no side effects.

Every entry path funnels AI or user input through validate_parsed_row() so a
typo'd category ("Grocries") or an incoherent type/category pair can never
reach MasterData and break the Dashboard SUMIFS.
"""

import hashlib
import re
from datetime import date, datetime, timezone

# Person values that mean "household / nobody specific".
HOUSEHOLD_ALIASES = {"household", "nobody", "none", ""}

# Quick-add / /add date sanity: how far back a date may be without confirmation.
MAX_PAST_DAYS = 90

# Type↔Category coherence: category names that imply a specific transaction
# type regardless of what the AI (or user) claimed. Keys are lowercase.
CATEGORY_IMPLIES_TYPE = {
    "savings": "Savings",
    "salary": "Income",
}

_TRUE_WORDS = {"yes", "y", "true", "1"}
_FALSE_WORDS = {"no", "n", "false", "0"}


def parse_amount(raw) -> float:
    """
    Parse a human-entered amount into a signed float rounded to 2 decimals.

    Handles thousands/decimal separator ambiguity: `1 234,56`, `1.234,56`,
    `1,234.56`, `-45.00`. Rule: when both `.` and `,` appear, the LAST
    separator is the decimal mark; a separator repeated more than once is a
    thousands separator. Raises ValueError when no number can be extracted.
    """
    s = str(raw or "").strip()
    negative = s.lstrip().startswith("-")
    s = re.sub(r"[^\d.,]", "", s)
    if not s.strip(".,"):
        raise ValueError(f"not a number: {raw!r}")

    if "." in s and "," in s:
        decimal_sep = "." if s.rfind(".") > s.rfind(",") else ","
        thousands_sep = "," if decimal_sep == "." else "."
        s = s.replace(thousands_sep, "").replace(decimal_sep, ".")
    elif "," in s:
        s = s.replace(",", "") if s.count(",") > 1 else s.replace(",", ".")
    elif s.count(".") > 1:
        s = s.replace(".", "")

    value = float(s)
    return round(-value if negative else value, 2)


def coerce_bool(raw) -> bool:
    """Coerce yes/no/true/false/1/0 (any case) to bool. Raises ValueError otherwise."""
    if isinstance(raw, bool):
        return raw
    word = str(raw or "").strip().lower()
    if word in _TRUE_WORDS:
        return True
    if word in _FALSE_WORDS:
        return False
    raise ValueError(f"expected yes/no/true/false, got {raw!r}")


def _normalize_str(value) -> str:
    return str(value or "").strip()


def make_dedup_key(txn_date, value, currency, description) -> str:
    """
    Stable identity key for a transaction: sha1(date|value|currency|cleaned-description).

    Used to detect re-imports of the same bank-statement rows. Uses the RAW
    Value + Currency as stored (that is what a re-import would duplicate),
    never the PLN conversion. Description is normalized (whitespace collapsed,
    case-folded) so trivially different formatting doesn't defeat dedup.
    """
    d = str(txn_date or "").strip()[:10]
    try:
        v = f"{float(str(value).replace(',', '.')):.2f}"
    except (TypeError, ValueError):
        v = _normalize_str(value)
    ccy = _normalize_str(currency).upper() or "PLN"
    desc = re.sub(r"\s+", " ", _normalize_str(description)).lower()
    return hashlib.sha1(f"{d}|{v}|{ccy}|{desc}".encode("utf-8")).hexdigest()


def validate_parsed_row(
    row: dict,
    lists: dict,
    *,
    max_past_days: int | None = None,
    today: date | None = None,
) -> tuple[bool, str, dict, list[str]]:
    """
    Validate and normalize one parsed transaction row against the Lists sheet.

    Ensures exact list values for type, category, currency and person, a
    positive numeric value, a sane date, and type↔category coherence.
    Unambiguous problems are auto-corrected (negative value → Expense,
    category Savings ⇒ type Savings) and reported in `corrections`.

    Returns (ok, reason, normalized, corrections). On failure normalized is {}.
    """
    txn_types = [str(t).strip() for t in lists.get("txn_types", []) if t is not None]
    categories = [str(c).strip() for c in lists.get("categories", []) if c is not None]
    currencies = [str(c).strip() for c in lists.get("currencies", []) if c is not None]
    persons = [str(p).strip() for p in lists.get("persons", []) if p is not None]
    if not row:
        return False, "Could not parse a transaction.", {}, []

    corrections: list[str] = []

    value = row.get("value")
    try:
        value = value if isinstance(value, (int, float)) else parse_amount(value)
        value = float(value)
    except (TypeError, ValueError):
        return False, "Transaction value must be a positive number.", {}, []
    if value == 0:
        return False, "Transaction value must be greater than zero.", {}, []

    txn_type_raw = _normalize_str(row.get("type", ""))
    category_raw = _normalize_str(row.get("category", ""))
    currency_raw = _normalize_str(row.get("currency", "PLN")).upper()
    person_raw = _normalize_str(row.get("person", ""))
    date_raw = _normalize_str(row.get("date", ""))

    txn_type_map = {t.lower(): t for t in txn_types}
    category_map = {c.lower(): c for c in categories}
    currency_map = {c.upper(): c for c in currencies}
    person_map = {p.lower(): p for p in persons}

    # Signed amounts come from bank exports — negative means money out.
    if value < 0:
        value = abs(value)
        expense = txn_type_map.get("expense", "Expense")
        if txn_type_raw.lower() != "expense":
            corrections.append(f"negative amount → type '{expense}'")
        txn_type_raw = expense

    if txn_type_raw.lower() not in txn_type_map:
        return False, (
            f"Unknown transaction type '{txn_type_raw}'. Use one of: {', '.join(txn_types)}."
            if txn_types else "Unknown transaction type."
        ), {}, []

    if categories and category_raw.lower() not in category_map:
        return False, (
            f"Unknown category '{category_raw}'. Use one of: {', '.join(categories)}."
        ), {}, []

    if currencies and currency_raw not in currency_map:
        return False, f"Unknown currency '{currency_raw}'. Use one of: {', '.join(currencies)}.", {}, []

    if persons:
        if person_raw.lower() in HOUSEHOLD_ALIASES:
            normalized_person = ""
        elif person_raw.lower() not in person_map:
            return False, (
                f"Unknown person '{person_raw}'. Use one of: {', '.join(persons)} or leave blank for household."
            ), {}, []
        else:
            normalized_person = person_map[person_raw.lower()]
    else:
        normalized_person = "" if person_raw.lower() in HOUSEHOLD_ALIASES else person_raw

    parsed_date = None
    if date_raw:
        try:
            parsed_date = datetime.fromisoformat(date_raw).date()
        except ValueError:
            return False, f"Invalid date '{date_raw}'. Use YYYY-MM-DD.", {}, []
        today = today or datetime.now(timezone.utc).date()
        if parsed_date > today:
            return False, f"Date '{date_raw}' is in the future (UTC).", {}, []
        if max_past_days is not None and (today - parsed_date).days > max_past_days:
            return False, (
                f"Date '{date_raw}' is more than {max_past_days} days ago. "
                f"Use /add to confirm old dates."
            ), {}, []

    normalized_type = txn_type_map[txn_type_raw.lower()]
    normalized_category = category_map.get(category_raw.lower(), category_raw)

    # Type↔Category coherence: some categories dictate the transaction type.
    implied = CATEGORY_IMPLIES_TYPE.get(normalized_category.lower())
    if implied and implied.lower() in txn_type_map and normalized_type.lower() != implied.lower():
        corrections.append(
            f"type '{normalized_type}' → '{txn_type_map[implied.lower()]}' (category {normalized_category})"
        )
        normalized_type = txn_type_map[implied.lower()]

    normalized = row.copy()
    normalized["value"] = round(value, 2)
    normalized["type"] = normalized_type
    normalized["category"] = normalized_category
    normalized["currency"] = currency_map.get(currency_raw, currency_raw)
    normalized["person"] = normalized_person
    normalized["date"] = parsed_date
    return True, "", normalized, corrections
