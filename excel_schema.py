"""
excel_schema.py
===============
Column declarations for every Excel sheet the bot reads or writes.

Each schema class is a plain dataclass where every field carries the exact
header text of the corresponding Excel column via metadata={"excel_header": ...}.
This replaces all hardcoded column positions across the codebase.

Usage
-----
    from excel_schema import ListsSchema, MasterDataSchema, find_col, col_indices

    # Find one column
    ccy_col = find_col(ws, ListsSchema.currency)   # returns int | None

    # Build full index for a sheet
    idx = col_indices(ws, MasterDataSchema)         # {field_name: col_int}
    ws.cell(row, idx["year"], 2025)
"""

from dataclasses import dataclass, field, fields
from typing import Any


# ── Field helper ──────────────────────────────────────────────────────────────

def col(header: str) -> Any:
    """Declare an Excel column by its exact header text (case-insensitive match)."""
    return field(default=None, metadata={"excel_header": header})


# ── Lookup helpers ────────────────────────────────────────────────────────────

def find_col(ws, header: str) -> int | None:
    """Return the 1-based column index whose row-1 value matches header (case-insensitive)."""
    needle = header.strip().lower()
    for c in range(1, ws.max_column + 1):
        if str(ws.cell(1, c).value or "").strip().lower() == needle:
            return c
    return None


def col_indices(ws, schema_cls) -> dict[str, int]:
    """
    Return {field_name: column_index} for every declared field in schema_cls
    whose header is found in ws row 1.  Missing columns are silently omitted.
    """
    result = {}
    for f in fields(schema_cls):
        header = f.metadata.get("excel_header")
        if header:
            c = find_col(ws, header)
            if c is not None:
                result[f.name] = c
    return result


def header_of(schema_cls, field_name: str) -> str:
    """Return the declared excel_header string for a given field name."""
    for f in fields(schema_cls):
        if f.name == field_name:
            return f.metadata.get("excel_header", field_name)
    raise KeyError(f"Field {field_name!r} not found in {schema_cls.__name__}")


def load_currency_rates_from_path(excel_path) -> dict[str, float]:
    """
    Read {currency_code: rate_to_base} from the Lists sheet.
    Uses ListsSchema to locate columns by header name — no positional assumptions.
    Returns {"PLN": 1.0} on any failure.
    """
    import re
    try:
        from openpyxl import load_workbook
        wb = load_workbook(excel_path, data_only=True)
        ws = wb["Lists"]
        idx      = col_indices(ws, ListsSchema)
        ccy_col  = idx.get("currency")
        rate_col = idx.get("rate_to_base")
        if not ccy_col or not rate_col:
            return {"PLN": 1.0}
        rates: dict[str, float] = {}
        for row in range(2, ws.max_row + 1):
            ccy  = ws.cell(row, ccy_col).value
            rate = ws.cell(row, rate_col).value
            if ccy is None:
                break
            ccy_str = str(ccy).strip().upper()
            if re.match(r"^[A-Z]{3}$", ccy_str) and rate is not None:
                try:
                    rates[ccy_str] = float(rate)
                except (TypeError, ValueError):
                    pass
        return rates or {"PLN": 1.0}
    except Exception:
        return {"PLN": 1.0}


# ── Shared MasterData row writer ──────────────────────────────────────────────

def lists_currency_range(wb) -> str:
    """VLOOKUP range for Currency→Rate on the Lists sheet, e.g. '$H$2:$I$100'."""
    from openpyxl.utils import get_column_letter
    idx      = col_indices(wb["Lists"], ListsSchema)
    ccy_col  = idx.get("currency",    8)
    rate_col = idx.get("rate_to_base", 9)
    return f"${get_column_letter(ccy_col)}$2:${get_column_letter(rate_col)}$100"


def find_next_data_row(ws) -> int:
    """
    Next writable MasterData row based on actual content (Date/Value columns).
    ws.max_row lies when empty rows carry styling or data validations.
    """
    idx = col_indices(ws, MasterDataSchema)
    value_col = idx.get("value", 4)
    date_col  = idx.get("date", 1)
    last_data_row = 1
    for row in range(2, ws.max_row + 1):
        if ws.cell(row, value_col).value is not None or ws.cell(row, date_col).value is not None:
            last_data_row = row
    return last_data_row + 1


_VALIDATION_MARGIN_ROWS = 500


def extend_validation_ranges(ws, last_row: int, margin: int = _VALIDATION_MARGIN_ROWS) -> None:
    """
    Dropdown validations are static ranges (e.g. F2:F103) — appended rows fall
    outside them and show no list in Excel. Extend every single-column range
    on the sheet so it covers at least last_row + margin.
    """
    import re
    target = last_row + margin
    for dv in ws.data_validations.dataValidation:
        parts = []
        changed = False
        for rng in str(dv.sqref).split():
            m = re.fullmatch(r"([A-Z]+)(\d+):([A-Z]+)(\d+)", rng)
            if m and m.group(1) == m.group(3) and int(m.group(4)) < target:
                rng = f"{m.group(1)}{m.group(2)}:{m.group(3)}{target}"
                changed = True
            parts.append(rng)
        if changed:
            dv.sqref = " ".join(parts)


def write_transaction_row(ws, r: int, row: dict, lu_range: str) -> None:
    """
    Write one transaction dict into MasterData row r.
    The single source of truth for column layout and the Value (base) formula —
    used by single append, batch append, and recovery-queue replay.
    """
    from datetime import datetime, timezone
    from openpyxl.utils import get_column_letter

    idx = col_indices(ws, MasterDataSchema)
    c = lambda field, fallback: idx.get(field, fallback)

    # Older live files predate the Date Modified column — writing values into a
    # headerless column looks like a stray column in Excel. Create the header.
    if "date_modified" not in idx:
        hdr_col = ws.max_column + 1 if ws.cell(1, 13).value not in (None, "") else 13
        ws.cell(1, hdr_col, header_of(MasterDataSchema, "date_modified"))
        idx["date_modified"] = hdr_col

    ws.cell(r, c("date",         1),  row.get("date"))
    ws.cell(r, c("year",         2),  row.get("year"))
    ws.cell(r, c("month",        3),  row.get("month"))
    ws.cell(r, c("value",        4),  row.get("value"))
    ws.cell(r, c("type",         5),  row.get("type"))
    ws.cell(r, c("category",     6),  row.get("category"))
    ws.cell(r, c("person",       7),  row.get("person"))
    # Formula-injection guard: descriptions come from untrusted sources (AI
    # output, bank statements). A leading = + - @ becomes a live Excel formula.
    desc = row.get("description")
    if isinstance(desc, str) and desc[:1] in ("=", "+", "-", "@"):
        desc = "'" + desc
    ws.cell(r, c("description",  8),  desc)
    ws.cell(r, c("is_recurring", 9),  row.get("is_recurring"))
    is_done = row.get("is_done")
    ws.cell(r, c("is_done",      10), True if is_done is None else bool(is_done))

    ccy_col = c("currency", 11)
    ws.cell(r, ccy_col, row.get("currency", "PLN"))

    vbase_col    = c("value_base", 12)
    value_letter = get_column_letter(c("value", 4))
    ccy_letter   = get_column_letter(ccy_col)
    ws.cell(r, vbase_col,
        f'=IF(OR({ccy_letter}{r}="",{ccy_letter}{r}="PLN"),'
        f'{value_letter}{r},'
        f'{value_letter}{r}*VLOOKUP({ccy_letter}{r},Lists!{lu_range},2,0))'
    )
    ws.cell(r, c("date_modified", 13), datetime.now(timezone.utc).replace(tzinfo=None))
    extend_validation_ranges(ws, r)


# ── MasterData sheet ──────────────────────────────────────────────────────────

@dataclass
class MasterDataSchema:
    """Column declarations for the MasterData sheet."""
    date:          Any = col("Date")
    year:          Any = col("Year")
    month:         Any = col("Month")
    value:         Any = col("Value")
    type:          Any = col("Type")
    category:      Any = col("Category")
    person:        Any = col("Person")
    description:   Any = col("Description")
    is_recurring:  Any = col("IsRecurring")
    is_done:       Any = col("IsDone")
    currency:      Any = col("Currency")
    value_base:    Any = col("Value (base)")
    date_modified: Any = col("Date Modified (UTC)")


# ── Lists sheet ───────────────────────────────────────────────────────────────

@dataclass
class ListsSchema:
    """Column declarations for the Lists sheet."""
    months:      Any = col("Months")
    txn_types:   Any = col("TxnTypes")
    categories:  Any = col("Categories")
    budget_base: Any = col("Budget (base)")
    persons:     Any = col("Persons")
    years:       Any = col("Years")
    currency:    Any = col("Currency")
    rate_to_base: Any = col("Rate to base")
    goal_name:   Any = col("Goal Name")
    alloc_pct:   Any = col("Alloc %")
    goal_pln:    Any = col("Goal (PLN)")


# ── Cycles sheet ──────────────────────────────────────────────────────────────

@dataclass
class CyclesSchema:
    """Column declarations for the Cycles sheet (one row per budget cycle)."""
    start_date: Any = col("StartDate")
    label:      Any = col("Label")
