"""
web/routes/transactions.py — GET /transactions — current month, newest first.

Filtering: person/category go through storage_facade.load_transactions
(filters= → sqlite_ops.list_transactions, which whitelists filter columns
and uses parameterized SQL — query params never reach SQL text). Values not
present in the reference data are rejected up-front, so arbitrary strings
never even reach the storage layer.

HTMX: requests carrying the HX-Request header get just the table fragment;
plain requests get the full page.
"""

from datetime import datetime

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

import settings
from models import MONTH_NAMES
from storage_facade import load_reference_data, load_transactions
from web.auth import require_session

router = APIRouter()


@router.get("/transactions", response_class=HTMLResponse,
            dependencies=[Depends(require_session)])
async def transactions(request: Request, person: str = "", category: str = ""):
    today = datetime.now(settings.TIMEZONE).date()
    ref = load_reference_data()
    # Whitelist filter values against reference data (defense in depth on
    # top of the parameterized SQL in sqlite_ops.list_transactions).
    person = person if person in ref["persons"] else ""
    category = category if category in ref["categories"] else ""

    filters = {"year": today.year, "month": MONTH_NAMES[today.month - 1]}
    if person:
        filters["person"] = person
    if category:
        filters["category"] = category
    df = load_transactions(filters=filters)
    df = df.sort_values("Date", ascending=False)
    rows = [{
        "date": d.date().isoformat() if hasattr(d, "date") else str(d)[:10],
        "value": r["Value"],
        "currency": r["Currency"],
        "type": r["Type"],
        "category": r["Category"],
        "person": r["Person"],
        "description": r["Description"] or "",
    } for d, (_, r) in zip(df["Date"], df.iterrows())]

    ctx = {
        "rows": rows, "persons": ref["persons"], "categories": ref["categories"],
        "person": person, "category": category,
        "month_label": today.strftime("%B %Y"),
    }
    template = ("_txn_table.html" if request.headers.get("HX-Request")
                else "transactions.html")
    return request.app.state.templates.TemplateResponse(request, template, ctx)
