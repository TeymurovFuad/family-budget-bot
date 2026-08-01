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
  - offset is a clamped integer;
  - per_page must be one of PER_PAGE_OPTIONS, else the default.

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
from datetime import date, datetime, timedelta
from math import ceil
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse

import cycles
import settings
from storage_facade import (
    ConflictError,
    add_web_transaction,
    count_transactions,
    delete_web_transaction,
    load_reference_data,
    load_transaction_by_id,
    load_transactions,
    update_web_transaction,
)
from validators import validate_web_transaction_form
from web.auth import get_session_currency, require_session
from web.currency import convert_from_base, load_rates

router = APIRouter()

# Rows-per-page whitelist. per_page is validated against this tuple BEFORE
# it reaches storage_facade/sqlite_ops (whose `limit` param is a raw int
# with no validation of its own) — anything off-list falls back to the
# default, same posture as every other param on this route.
PER_PAGE_OPTIONS = (25, 50, 100)
PER_PAGE_DEFAULT = 50

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


def _current_cycle_start(today: date) -> date | None:
    """Current cycle boundary, resolved ONCE per request (loading the cycle
    ledger is an Excel read — callers pass the result around, they don't
    re-derive it)."""
    if not settings.BUDGET_CYCLE:
        return None
    current = cycles.current_cycle_start(today)
    return current[0] if current is not None else None


def _default_range(today: date, cycle_start: date | None) -> tuple[date, date]:
    """Current budget cycle when enabled and recorded, else calendar month."""
    if cycle_start is not None:
        return cycle_start, today
    first = today.replace(day=1)
    last = today.replace(day=calendar.monthrange(today.year, today.month)[1])
    return first, last


def _preset_ranges(today: date, cycle_start: date | None,
                   ) -> list[tuple[str, str, date | None, date | None]]:
    """(key, label, date_from, date_to) for the preset range chips.
    'This cycle' only appears when a current cycle boundary exists; None
    dates mean an open bound ('All time' is both-None → empty params, the
    existing 'present-but-empty means all time' semantics)."""
    presets: list[tuple[str, str, date | None, date | None]] = []
    if cycle_start is not None:
        presets.append(("cycle", "This cycle", cycle_start, today))
    month_first = today.replace(day=1)
    month_last = today.replace(
        day=calendar.monthrange(today.year, today.month)[1])
    presets.extend([
        ("month", "This month", month_first, month_last),
        ("last30", "Last 30 days", today - timedelta(days=29), today),
        ("year", "This year",
         today.replace(month=1, day=1), today.replace(month=12, day=31)),
        ("all", "All time", None, None),
    ])
    return presets


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


def _query_string(q, date_from, date_to, person, category, sort_key,
                  per_page=PER_PAGE_DEFAULT) -> str:
    """Canonical query string for pagination/chip-clear links. The date keys
    are always present (present-but-empty means an explicit 'all time');
    sort and per_page appear only when non-default."""
    params = [("q", q), ("date_from", date_from), ("date_to", date_to),
              ("person", person), ("category", category)]
    pairs = [(k, v) for k, v in params
             if v or k in ("date_from", "date_to")]
    if sort_key != DEFAULT_SORT:
        pairs.append(("sort", sort_key))
    if per_page != PER_PAGE_DEFAULT:
        pairs.append(("per_page", per_page))
    return urlencode(pairs)


@router.get("/transactions", response_class=HTMLResponse,
            dependencies=[Depends(require_session)])
async def transactions(request: Request, q: str = "", date_from: str = "",
                       date_to: str = "", person: str = "", category: str = "",
                       sort: str = DEFAULT_SORT, offset: int = 0,
                       per_page: int = PER_PAGE_DEFAULT):
    today = datetime.now(settings.TIMEZONE).date()
    cycle_start = _current_cycle_start(today)
    ref = load_reference_data()

    # Whitelist filter values against reference data (defense in depth on
    # top of the parameterized SQL in sqlite_ops).
    person = person if person in ref["persons"] else ""
    category = category if category in ref["categories"] else ""
    q = str(q).strip()
    sort_key = sort if sort in SORT_OPTIONS else DEFAULT_SORT
    per_page = per_page if per_page in PER_PAGE_OPTIONS else PER_PAGE_DEFAULT
    sort_by, sort_dir, _ = SORT_OPTIONS[sort_key]

    # Date range: absent params → defaults; present-but-empty → all time;
    # present-but-invalid → treated as empty (open-ended).
    if "date_from" in request.query_params or "date_to" in request.query_params:
        d_from, d_to = _parse_iso_date(date_from), _parse_iso_date(date_to)
    else:
        d_from, d_to = _default_range(today, cycle_start)

    filters = {}
    if person:
        filters["person"] = person
    if category:
        filters["category"] = category

    total = count_transactions(filters or None,
                               date_from=d_from, date_to=d_to,
                               description_contains=q or None)
    total_pages = max(1, ceil(total / per_page))
    offset = max(0, int(offset))
    offset = min(offset, (total_pages - 1) * per_page)
    page = offset // per_page + 1

    df = load_transactions(filters or None,
                           date_from=d_from, date_to=d_to,
                           description_contains=q or None,
                           sort_by=sort_by, sort_dir=sort_dir,
                           limit=per_page, offset=offset)

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
            "id": r["_id"] if "_id" in df.columns else None,
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
    query = _query_string(q, date_from_str, date_to_str, person, category,
                          sort_key, per_page)
    base_url = f"/transactions?{query}"

    def _clear_url(**removed) -> str:
        kept = {"q": q, "date_from": date_from_str, "date_to": date_to_str,
                "person": person, "category": category}
        kept.update(removed)
        return "/transactions?" + _query_string(
            kept["q"], kept["date_from"], kept["date_to"],
            kept["person"], kept["category"], sort_key, per_page)

    chips = []
    if q:
        chips.append({"text": f"“{q}”", "clear_url": _clear_url(q="")})
    if person:
        chips.append({"text": person, "clear_url": _clear_url(person="")})
    if category:
        chips.append({"text": category, "clear_url": _clear_url(category="")})

    # Preset range chips: server-rendered links, each carrying the current
    # non-date filters with its own date bounds. active_preset highlights an
    # exact match (best-effort — custom ranges highlight nothing).
    presets = [{
        "key": key, "label": label,
        "dates": (p_from.isoformat() if p_from else "",
                  p_to.isoformat() if p_to else ""),
    } for key, label, p_from, p_to in _preset_ranges(today, cycle_start)]
    for p in presets:
        p["url"] = "/transactions?" + _query_string(
            q, p["dates"][0], p["dates"][1], person, category, sort_key,
            per_page)
    active_preset = next((p["key"] for p in presets
                          if p["dates"] == (date_from_str, date_to_str)), "")

    any_filter = bool(q or person or category
                      or (d_from, d_to) != _default_range(today, cycle_start))

    # Current filter state for the rows-per-page form's hidden inputs —
    # same emission rules as _query_string (dates always present, q/person/
    # category only when set, sort only when non-default), so a plain
    # non-JS submit of that form reproduces the canonical URL.
    current_filters = {k: v for k, v in
                       [("q", q), ("date_from", date_from_str),
                        ("date_to", date_to_str), ("person", person),
                        ("category", category)]
                       if v or k in ("date_from", "date_to")}
    if sort_key != DEFAULT_SORT:
        current_filters["sort"] = sort_key

    ctx = {
        "rows": rows, "groups": groups, "grouped": grouped,
        "persons": ref["persons"], "categories": ref["categories"],
        "q": q, "person": person, "category": category,
        "date_from": date_from_str, "date_to": date_to_str,
        "sort": sort_key, "sort_options": SORT_OPTIONS,
        "total": total, "page": page, "total_pages": total_pages,
        "per_page": per_page, "per_page_options": PER_PAGE_OPTIONS,
        "per_page_default": PER_PAGE_DEFAULT,
        "current_filters": current_filters, "base_url": base_url,
        "range_label": _range_label(d_from, d_to, today),
        "chips": chips, "any_filter": any_filter,
        "presets": presets, "active_preset": active_preset,
        "display_currency": display_currency,
    }
    template = ("_txn_list.html" if request.headers.get("HX-Request")
                else "transactions.html")
    return request.app.state.templates.TemplateResponse(request, template, ctx)


# ── GET /transactions/new ──────────────────────────────────────────────────────

@router.get("/transactions/new", response_class=HTMLResponse,
            dependencies=[Depends(require_session)])
async def txn_new_form(request: Request):
    ref = load_reference_data()
    ctx = {
        "errors": {},
        "values": {},
        "categories": ref["categories"],
        "persons": ref["persons"],
        "txn_types": ref["txn_types"],
    }
    return request.app.state.templates.TemplateResponse(
        request, "_txn_form.html", ctx)


# ── POST /transactions/new ─────────────────────────────────────────────────────

@router.post("/transactions/new", response_class=HTMLResponse,
             dependencies=[Depends(require_session)])
async def txn_new_submit(
    request: Request,
    date: str = Form(""),
    amount: str = Form(""),
    type: str = Form(""),
    category: str = Form(""),
    person: str = Form(""),
    description: str = Form(""),
    currency: str = Form(""),
):
    data = {
        "date": date, "amount": amount, "type": type,
        "category": category, "person": person,
        "description": description, "currency": currency or None,
    }
    cleaned, errors = validate_web_transaction_form(data)
    if errors:
        ref = load_reference_data()
        ctx = {
            "errors": errors,
            "values": data,
            "categories": ref["categories"],
            "persons": ref["persons"],
            "txn_types": ref["txn_types"],
        }
        return request.app.state.templates.TemplateResponse(
            request, "_txn_form.html", ctx, status_code=422)
    await add_web_transaction(cleaned)
    from fastapi.responses import Response
    resp = Response(status_code=200)
    resp.headers["HX-Trigger"] = '{"txnSaved":true}'
    return resp


# ── GET /transactions/{id}/edit ────────────────────────────────────────────────

@router.get("/transactions/{id}/edit", response_class=HTMLResponse,
            dependencies=[Depends(require_session)])
async def txn_edit_form(request: Request, id: int):
    row = await load_transaction_by_id(id)
    if row is None:
        from fastapi.responses import Response
        return Response(status_code=404)
    ref = load_reference_data()
    ctx = {
        "row": row,
        "errors": {},
        "categories": ref["categories"],
        "persons": ref["persons"],
        "txn_types": ref["txn_types"],
    }
    return request.app.state.templates.TemplateResponse(
        request, "_txn_edit_form.html", ctx)


# ── POST /transactions/{id}/edit ───────────────────────────────────────────────

@router.post("/transactions/{id}/edit", response_class=HTMLResponse,
             dependencies=[Depends(require_session)])
async def txn_edit_submit(
    request: Request,
    id: int,
    lock_token: str = Form(""),
    date: str = Form(""),
    amount: str = Form(""),
    type: str = Form(""),
    category: str = Form(""),
    person: str = Form(""),
    description: str = Form(""),
    currency: str = Form(""),
):
    row = await load_transaction_by_id(id)
    if row is None:
        from fastapi.responses import Response
        return Response(status_code=404)

    data = {
        "date": date, "amount": amount, "type": type,
        "category": category, "person": person,
        "description": description, "currency": currency or None,
    }
    cleaned, errors = validate_web_transaction_form(data)
    if errors:
        ref = load_reference_data()
        ctx = {
            "row": {**row, **{"id": id}},
            "errors": errors,
            "categories": ref["categories"],
            "persons": ref["persons"],
            "txn_types": ref["txn_types"],
        }
        return request.app.state.templates.TemplateResponse(
            request, "_txn_edit_form.html", ctx, status_code=422)

    try:
        await update_web_transaction(id, lock_token, cleaned)
    except KeyError:
        from fastapi.responses import Response
        return Response(status_code=404)
    except ConflictError as exc:
        ctx = {"id": id, "message": str(exc), "row": row}
        return request.app.state.templates.TemplateResponse(
            request, "_txn_conflict.html", ctx, status_code=409)

    updated_row = await load_transaction_by_id(id)
    display_currency = str(get_session_currency(request)).strip().upper()
    ctx = {"row": updated_row, "id": id, "display_currency": display_currency}
    return request.app.state.templates.TemplateResponse(
        request, "_txn_row.html", ctx)


# ── GET /transactions/{id}/row ─────────────────────────────────────────────────

@router.get("/transactions/{id}/row", response_class=HTMLResponse,
            dependencies=[Depends(require_session)])
async def txn_row_fragment(request: Request, id: int):
    row = await load_transaction_by_id(id)
    if row is None:
        from fastapi.responses import Response
        return Response(status_code=404)
    display_currency = str(get_session_currency(request)).strip().upper()
    ctx = {"row": row, "id": id, "display_currency": display_currency}
    return request.app.state.templates.TemplateResponse(
        request, "_txn_row.html", ctx)


# ── GET /transactions/{id}/delete-confirm ─────────────────────────────────────

@router.get("/transactions/{id}/delete-confirm", response_class=HTMLResponse,
            dependencies=[Depends(require_session)])
async def txn_delete_confirm(request: Request, id: int):
    row = await load_transaction_by_id(id)
    if row is None:
        from fastapi.responses import Response
        return Response(status_code=404)
    ctx = {"row": row, "id": id}
    return request.app.state.templates.TemplateResponse(
        request, "_txn_delete_confirm.html", ctx)


# ── POST /transactions/{id}/delete ────────────────────────────────────────────

@router.post("/transactions/{id}/delete", response_class=HTMLResponse,
             dependencies=[Depends(require_session)])
async def txn_delete_submit(
    request: Request,
    id: int,
    lock_token: str = Form(""),
):
    try:
        await delete_web_transaction(id, lock_token)
    except KeyError:
        from fastapi.responses import Response
        return Response(status_code=404)
    except ConflictError as exc:
        row = await load_transaction_by_id(id)
        ctx = {"id": id, "message": str(exc), "row": row}
        return request.app.state.templates.TemplateResponse(
            request, "_txn_conflict.html", ctx, status_code=409)
    return HTMLResponse(
        f'<div id="txn-{id}" style="display:none" aria-hidden="true"></div>')
