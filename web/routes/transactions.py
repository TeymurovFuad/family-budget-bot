"""
web/routes/transactions.py — GET /transactions — v2 "Ledger" page.

Date-grouped transaction list with date-range filtering, description
search, combined sort control, pagination, and session-currency display
conversion. All query params are validated/whitelisted here before they
reach storage_facade (which itself only builds parameterized SQL through
sqlite_ops — user input never lands in SQL text):

  - person/category are checked against reference data;
  - dates must parse as ISO dates;
  - sort is a fixed token → (sort_by, sort_dir) map;
  - offset is a clamped integer.

Default date range on a param-less first load: the current budget cycle
when settings.BUDGET_CYCLE is on and a boundary exists, else the current
calendar month. The form always submits the date fields, so explicitly
cleared dates (present-but-empty params) mean "all time".

Currency: stored value_base (settings.DISPLAY_CURRENCY) is converted for
display into the session currency via web.currency.convert_from_base —
display-only, nothing persisted.

HTMX: requests carrying the HX-Request header get just the #txn-list
fragment; plain requests get the full page.
"""

import calendar
from datetime import date, datetime
from math import ceil
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

import cycles
import settings
from storage_facade import count_transactions, load_reference_data, load_transactions
from web.auth import get_session_currency, require_session
from web.currency import convert_from_base, load_rates

router = APIRouter()

PER_PAGE = 50

# Combined sort token → (sort_by column, sort_dir). Tokens are the only
# accepted values; anything else falls back to the default. The columns
# mirror sqlite_ops._SORT_COLUMNS — never widen this map without
# whitelisting the column there first.
SORT_OPTIONS: dict[str, tuple[str, str, str]] = {
    "date_desc":        ("date",        "desc", "Newest first"),
    "date_asc":         ("date",        "asc",  "Oldest first"),
    "value_desc":       ("value",       "desc", "Largest amount"),
    "value_asc":        ("value",       "asc",  "Smallest amount"),
    "category_asc":     ("category",    "asc",  "Category A–Z"),
    "person_asc":       ("person",      "asc",  "Person A–Z"),
    "description_asc":  ("description", "asc",  "Description A–Z"),
}
DEFAULT_SORT = "date_desc"

_TYPE_KIND = {"Expense": "neg", "Income": "pos", "Savings": "save"}


def _parse_iso_date(raw: str) -> date | None:
    try:
        return date.fromisoformat(str(raw).strip())
    except (ValueError, TypeError):
        return None


def _default_range(today: date) -> tuple[date, date]:
    """Current budget cycle when enabled and recorded, else calendar month."""
    if settings.BUDGET_CYCLE:
        current = cycles.current_cycle_start(today)
        if current is not None:
            return current[0], today
    first = today.replace(day=1)
    last = today.replace(day=calendar.monthrange(today.year, today.month)[1])
    return first, last


def _fmt_day(d: date, today: date) -> str:
    """'1 Jun' within the current year, '1 Jun 2024' otherwise."""
    label = f"{d.day} {d.strftime('%b')}"
    return label if d.year == today.year else f"{label} {d.year}"


def _range_label(date_from: date | None, date_to: date | None, today: date) -> str:
    if date_from and date_to:
        return f"{_fmt_day(date_from, today)} – {_fmt_day(date_to, today)}"
    if date_from:
        return f"from {_fmt_day(date_from, today)}"
    if date_to:
        return f"until {_fmt_day(date_to, today)}"
    return "all time"


def _query_string(q, date_from, date_to, person, category, sort_key) -> str:
    """Canonical query string for pagination/chip-clear links. The date keys
    are always present (present-but-empty means an explicit 'all time')."""
    params = [("q", q), ("date_from", date_from), ("date_to", date_to),
              ("person", person), ("category", category)]
    pairs = [(k, v) for k, v in params
             if v or k in ("date_from", "date_to")]
    if sort_key != DEFAULT_SORT:
        pairs.append(("sort", sort_key))
    return urlencode(pairs)


@router.get("/transactions", response_class=HTMLResponse,
            dependencies=[Depends(require_session)])
async def transactions(request: Request, q: str = "", date_from: str = "",
                       date_to: str = "", person: str = "", category: str = "",
                       sort: str = DEFAULT_SORT, offset: int = 0):
    today = datetime.now(settings.TIMEZONE).date()
    ref = load_reference_data()

    # Whitelist filter values against reference data (defense in depth on
    # top of the parameterized SQL in sqlite_ops).
    person = person if person in ref["persons"] else ""
    category = category if category in ref["categories"] else ""
    q = str(q).strip()
    sort_key = sort if sort in SORT_OPTIONS else DEFAULT_SORT
    sort_by, sort_dir, _ = SORT_OPTIONS[sort_key]

    # Date range: absent params → defaults; present-but-empty → all time;
    # present-but-invalid → treated as empty (open-ended).
    if "date_from" in request.query_params or "date_to" in request.query_params:
        d_from, d_to = _parse_iso_date(date_from), _parse_iso_date(date_to)
    else:
        d_from, d_to = _default_range(today)

    filters = {}
    if person:
        filters["person"] = person
    if category:
        filters["category"] = category

    total = count_transactions(filters or None,
                               date_from=d_from, date_to=d_to,
                               description_contains=q or None)
    total_pages = max(1, ceil(total / PER_PAGE))
    offset = max(0, int(offset))
    offset = min(offset, (total_pages - 1) * PER_PAGE)
    page = offset // PER_PAGE + 1

    df = load_transactions(filters or None,
                           date_from=d_from, date_to=d_to,
                           description_contains=q or None,
                           sort_by=sort_by, sort_dir=sort_dir,
                           limit=PER_PAGE, offset=offset)

    # Display currency: convert each row's stored base value into the
    # session currency (display-only; see web/currency.py).
    display_currency = str(get_session_currency(request)).strip().upper()
    base_currency = str(settings.DISPLAY_CURRENCY).strip().upper()
    rates = load_rates() if display_currency != base_currency else {}

    rows = []
    for d, (_, r) in zip(df["Date"], df.iterrows()):
        row_date = _parse_iso_date(str(d)[:10])
        kind = _TYPE_KIND.get(r["Type"], "neutral")
        converted = convert_from_base(float(r["_base"]), display_currency, rates)
        rows.append({
            "date": str(d)[:10],
            "date_label": _fmt_day(row_date, today) if row_date else str(d)[:10],
            # amount() renders pos/neg with an explicit %+.2f sign — pass
            # expenses as negative so they display "-…" not "+…".
            "amount": -converted if kind == "neg" else converted,
            "kind": kind,
            "category": r["Category"],
            "person": r["Person"],
            "description": r["Description"] or "",
        })

    # Grouped (date sorts) vs flat (all other sorts) rendering.
    grouped = sort_by == "date"
    groups = []
    if grouped:
        for r in rows:
            row_date = _parse_iso_date(r["date"])
            label = row_date.strftime("%a ") + _fmt_day(row_date, today) if row_date else r["date"]
            if not groups or groups[-1]["date"] != r["date"]:
                groups.append({"date": r["date"], "label": label, "rows": []})
            groups[-1]["rows"].append(r)

    date_from_str = d_from.isoformat() if d_from else ""
    date_to_str = d_to.isoformat() if d_to else ""
    query = _query_string(q, date_from_str, date_to_str, person, category, sort_key)
    base_url = f"/transactions?{query}"

    def _clear_url(**removed) -> str:
        kept = {"q": q, "date_from": date_from_str, "date_to": date_to_str,
                "person": person, "category": category}
        kept.update(removed)
        return "/transactions?" + _query_string(
            kept["q"], kept["date_from"], kept["date_to"],
            kept["person"], kept["category"], sort_key)

    chips = []
    if q:
        chips.append({"text": f"“{q}”", "clear_url": _clear_url(q="")})
    if person:
        chips.append({"text": person, "clear_url": _clear_url(person="")})
    if category:
        chips.append({"text": category, "clear_url": _clear_url(category="")})

    any_filter = bool(q or person or category
                      or (d_from, d_to) != _default_range(today))

    ctx = {
        "rows": rows, "groups": groups, "grouped": grouped,
        "persons": ref["persons"], "categories": ref["categories"],
        "q": q, "person": person, "category": category,
        "date_from": date_from_str, "date_to": date_to_str,
        "sort": sort_key, "sort_options": SORT_OPTIONS,
        "total": total, "page": page, "total_pages": total_pages,
        "per_page": PER_PAGE, "base_url": base_url,
        "range_label": _range_label(d_from, d_to, today),
        "chips": chips, "any_filter": any_filter,
        "display_currency": display_currency,
    }
    template = ("_txn_list.html" if request.headers.get("HX-Request")
                else "transactions.html")
    return request.app.state.templates.TemplateResponse(request, template, ctx)
