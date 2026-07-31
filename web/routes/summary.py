"""
web/routes/summary.py — GET / — cycle summaries.

Same math as the bot's /summary (handlers/reports.py _send_cycle_summary):
totals come from cycles.cycle_totals over cycles.cycle_periods boundaries,
fed by storage_facade.load_transactions(). No reimplemented aggregation —
build_summary_context() below is the single computation path, and the
golden-master test asserts its numbers equal direct cycle_totals() calls.
"""

from datetime import date, datetime

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

import settings
from cycles import BEFORE_CYCLES_LABEL, cycle_periods, cycle_totals, load_cycles
from storage_facade import load_transactions
from web.auth import require_session

router = APIRouter()


def build_summary_context(today: date | None = None) -> dict:
    """Computed summary data, separated from rendering so tests can call it."""
    if today is None:
        today = datetime.now(settings.TIMEZONE).date()
    df = load_transactions()
    cycles_ledger = load_cycles() if settings.BUDGET_CYCLE else []
    periods = [p for p in cycle_periods(df, cycles_ledger, today) if p[0] <= today]
    if not periods:
        # Calendar fallback (cycles disabled or no boundaries recorded):
        # current calendar month, same cycle_totals math over month bounds.
        start = today.replace(day=1)
        periods = [(start, today, f"{today.strftime('%B %Y')} (calendar month)")]
    cards = []
    for start, end, label in reversed(periods):  # newest first
        totals = cycle_totals(df, start, end)
        income, expense = totals["income"], totals["expense"]
        savings = totals["savings"]
        net = income - expense - savings
        days_elapsed = (end - start).days + 1
        card = {
            "label": label, "start": start, "end": end,
            "income": income, "expense": expense, "savings": savings,
            "net": net,
            "daily_avg": expense / days_elapsed if days_elapsed > 0 else 0,
            "savings_rate": savings / income if income > 0 else 0,
            # The "Before cycles" bucket has no salary anchor — the bot
            # excludes salary/unaccounted math there; mirror that.
            "unaccounted": (None if label == BEFORE_CYCLES_LABEL
                            else totals["unaccounted"]),
        }
        cards.append(card)
    return {"cards": cards, "today": today, "currency": settings.DISPLAY_CURRENCY}


@router.get("/", response_class=HTMLResponse, dependencies=[Depends(require_session)])
async def summary(request: Request):
    ctx = build_summary_context()
    return request.app.state.templates.TemplateResponse(
        request, "summary.html", ctx)
