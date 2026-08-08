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


def _category_breakdown(sel: dict, currency: str, top_n: int = 6) -> list[dict]:
    """Top spending categories for the selected period."""
    import pandas as pd
    from storage_facade import load_budgets
    from web.currency import convert_from_base, load_rates

    df = load_transactions()
    # Normalise date column to date objects
    dates = pd.to_datetime(df["date"]).dt.date
    mask = (dates >= sel["start"]) & (dates <= sel["end"])
    period_df = df[mask]
    # Expense rows only — match however type is stored (capitalisation)
    exp_df = period_df[period_df["type"].str.lower() == "expense"]
    if exp_df.empty:
        return []
    grouped = (
        exp_df.groupby("category")["value_base"]
        .sum()
        .sort_values(ascending=False)
        .head(top_n)
    )
    total_exp = sel["expense"] or 1
    budgets = load_budgets()
    rates = load_rates()
    target = str(currency).strip().upper()
    base_ccy = str(settings.DISPLAY_CURRENCY).strip().upper()

    def conv(v: float) -> float:
        return convert_from_base(v, target, rates) if target != base_ccy else v

    rows = []
    for i, (cat, base_amt) in enumerate(grouped.items()):
        amt = conv(base_amt)
        bgt_base = budgets.get(cat)
        bgt = conv(bgt_base) if bgt_base else None
        rows.append({
            "category":   cat,
            "amount":     amt,
            "pct_of_exp": round(min(amt / conv(total_exp) * 100, 100), 1),
            "budget":     bgt,
            "over":       bgt is not None and amt > bgt,
            "color_idx":  i % 8,
        })
    return rows


def _compute_warnings(sel: dict, prev: dict | None, cat_rows: list[dict]) -> list[dict]:
    warnings = []
    if sel["net"] < 0:
        warnings.append({"kind": "danger", "icon": "🔴",
                          "text": "You spent more than you earned this period."})
    if sel.get("unaccounted") is not None and sel["unaccounted"] < 0:
        warnings.append({"kind": "warn", "icon": "⚠️",
                          "text": "Unaccounted income is negative — check whether all salary transactions were recorded."})
    if sel["savings_rate"] < 0.10 and sel["income"] > 0:
        warnings.append({"kind": "tip", "icon": "💡",
                          "text": f"Savings rate is {sel['savings_rate']*100:.1f}% — below the 10% target."})
    if prev and prev.get("daily_avg", 0) > 0:
        pace_ratio = sel["daily_avg"] / prev["daily_avg"]
        if pace_ratio > 1.20:
            warnings.append({"kind": "warn", "icon": "📈",
                              "text": f"Daily spend pace is {(pace_ratio-1)*100:.0f}% higher than last period."})
    over_cats = [r for r in cat_rows if r["over"]]
    if over_cats:
        names = ", ".join(r["category"] for r in over_cats[:3])
        tail = f" (+{len(over_cats)-3} more)" if len(over_cats) > 3 else ""
        warnings.append({"kind": "warn", "icon": "⚠️",
                          "text": f"{len(over_cats)} categor{'y' if len(over_cats)==1 else 'ies'} over budget: {names}{tail}."})
    return warnings


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

    import pandas as pd
    sel = ctx["cards"][ctx["selected_index"]]
    prev = ctx["cards"][ctx["selected_index"] + 1] if ctx["selected_index"] + 1 < len(ctx["cards"]) else None

    cat_rows = _category_breakdown(sel, ctx["currency"])
    ctx["cat_rows"] = cat_rows
    ctx["warnings"] = _compute_warnings(sel, prev, cat_rows)

    df_all = load_transactions()
    dates_all = pd.to_datetime(df_all["date"]).dt.date
    ctx["txn_count"] = int(((dates_all >= sel["start"]) & (dates_all <= sel["end"])).sum())

    period_len = (sel["end"] - sel["start"]).days + 1
    days_elapsed = min((ctx["today"] - sel["start"]).days + 1, period_len)
    ctx["period_days_total"] = period_len
    ctx["period_days_elapsed"] = max(days_elapsed, 1)
    ctx["is_current_period"] = (ctx["selected_index"] == 0)

    i = ctx["selected_index"]
    spark_slice = ctx["cards"][max(0, i - 5):i + 1][::-1]
    ctx["spark_periods"] = [
        {"label": c["label"], "income": c["income"],
         "expense": c["expense"], "savings": c["savings"]}
        for c in spark_slice
    ]
    ctx["history_cards"] = ctx["cards"][i + 1:i + 6]
    ctx["prev_card"] = prev

    return request.app.state.templates.TemplateResponse(
        request, "summary.html", ctx)
