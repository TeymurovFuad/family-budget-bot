"""
web/routes/summary.py — GET / — cycle summaries.

Same math as the bot's /summary (handlers/reports.py _send_cycle_summary):
totals come from cycles.cycle_totals over cycles.cycle_periods boundaries,
fed by storage_facade.load_transactions(). No reimplemented aggregation —
build_summary_context() below is the single computation path, and the
golden-master test asserts its numbers equal direct cycle_totals() calls.

v2 additions (Ledger redesign):
- period selection: ?period=<ISO start> or ?date_from/?date_to jump to the
  period containing that date. Default (no params) is byte-for-byte the old
  behaviour — the route calls build_summary_context() with NO extra kwargs
  then, so tests may monkeypatch it with a today-only callable.
- session display currency: every monetary value is converted from the
  base currency via web.currency.convert_from_base before rendering.
  Derived values (net) are recomputed FROM the converted parts so the
  displayed numbers always reconcile in whichever currency is shown.
"""

from datetime import date, datetime

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

import settings
from cycles import BEFORE_CYCLES_LABEL, cycle_periods, cycle_totals
from storage_facade import load_cycles
from storage_facade import load_transactions
from web.auth import get_session_currency, require_session
from web.currency import convert_from_base, load_rates

router = APIRouter()


def build_summary_context(today: date | None = None, *,
                          selected_period: str | None = None,
                          jump_from: date | None = None,
                          jump_to: date | None = None) -> dict:
    """
    Computed summary data, separated from rendering so tests can call it.
    All monetary values are in the base currency (settings.DISPLAY_CURRENCY);
    display conversion happens in the route, never here — this function is
    the golden-master parity surface.
    """
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
    selected_index = 0
    if selected_period:
        for i, card in enumerate(cards):
            if card["start"].isoformat() == selected_period:
                selected_index = i
                break
    elif jump_from or jump_to:
        probe = jump_from or jump_to
        for i, card in enumerate(cards):
            if card["start"] <= probe <= card["end"]:
                selected_index = i
                break
    return {"cards": cards, "today": today,
            "selected_index": selected_index,
            "currency": settings.DISPLAY_CURRENCY}


def _parse_date(raw: str) -> date | None:
    try:
        return date.fromisoformat(raw.strip())
    except (ValueError, AttributeError):
        return None


def apply_display_currency(ctx: dict, target: str) -> dict:
    """
    Convert every monetary card value from base into `target` (display-only).
    net is recomputed from the converted income/expense/savings so the shown
    numbers reconcile exactly; savings_rate is a ratio and needs no
    conversion. No-op when target is the base currency.
    """
    display = str(settings.DISPLAY_CURRENCY).strip().upper()
    target = str(target or "").strip().upper() or display
    ctx["currency"] = target
    if target == display:
        return ctx
    rates = load_rates()
    if not rates.get(target):
        ctx["currency"] = display  # unknown rate — show honest base values
        return ctx
    for card in ctx.get("cards", []):
        for field in ("income", "expense", "savings", "daily_avg", "unaccounted"):
            if card.get(field) is not None:
                card[field] = convert_from_base(card[field], target, rates)
        card["net"] = card["income"] - card["expense"] - card["savings"]
    return ctx


@router.get("/", response_class=HTMLResponse, dependencies=[Depends(require_session)])
async def summary(request: Request, period: str = "",
                  date_from: str = "", date_to: str = ""):
    # Default case MUST call build_summary_context() with no kwargs —
    # the golden-master test monkeypatches it with a today-only callable.
    kwargs = {}
    if period:
        kwargs["selected_period"] = period.strip()
    else:
        jf, jt = _parse_date(date_from), _parse_date(date_to)
        if jf or jt:
            kwargs.update(jump_from=jf, jump_to=jt)
    ctx = build_summary_context(**kwargs) if kwargs else build_summary_context()
    ctx = apply_display_currency(ctx, get_session_currency(request))
    return request.app.state.templates.TemplateResponse(
        request, "summary.html", ctx)
