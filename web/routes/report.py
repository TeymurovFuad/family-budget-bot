"""web/routes/report.py — GET /report — analytics report page.

Provides a comprehensive analytics view for a selected period with:
- Summary stats (income/expense/savings/net/daily_avg/savings_rate)
- Category breakdown with optional budget markers
- Category trend table (up to 6 prior periods)
- Person breakdown
- Type split (expense/savings/remaining)
- Recurring vs one-off summary
- Top 10 transactions
- Daily spend chart
- Multi-period trend bars
- Currency mix (when multiple currencies present)
- Warnings for budget overruns, negative net, low savings rate, etc.

HTMX: full page on direct request, _report_content.html fragment on HX-Request.
"""

import logging
import zlib
from datetime import date, datetime, timedelta
from typing import Any

import pandas as pd
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse

log = logging.getLogger(__name__)

import settings
from cycles import cycle_periods, salary_mask
from storage_facade import load_category_budgets, load_cycles, load_transactions
from web.auth import get_session_currency, require_session
from web.currency import convert_from_base, load_rates

router = APIRouter()

_N_CAT_COLORS = 8
_CAT_TREND_PERIODS = 6


def _cat_color_idx(name: str) -> int:
    """Stable 0-7 color index for a category — matches web/app.py cat_color_idx."""
    return zlib.crc32(str(name).strip().lower().encode()) % _N_CAT_COLORS


def _parse_date(raw: str) -> date | None:
    try:
        return date.fromisoformat(raw.strip())
    except (ValueError, AttributeError):
        return None


def _filter_df(
    df: pd.DataFrame,
    date_from: date,
    date_to: date,
    txn_type: str,
    person: str,
    categories: list[str],
) -> pd.DataFrame:
    dates = pd.to_datetime(df["Date"], errors="coerce")
    mask = (
        dates.notna()
        & (dates.dt.date >= date_from)
        & (dates.dt.date <= date_to)
        & df["IsDone"]
    )
    sub = df[mask].copy()

    if txn_type and txn_type.lower() not in ("all", ""):
        type_map = {"income": "Income", "expense": "Expense", "savings": "Savings"}
        mapped = type_map.get(txn_type.lower(), txn_type)
        sub = sub[sub["Type"] == mapped]

    if person and person.lower() not in ("all", ""):
        sub = sub[sub["Person"].str.strip().str.lower() == person.strip().lower()]

    if categories:
        cats_lower = [c.strip().lower() for c in categories if c.strip()]
        if cats_lower:
            sub = sub[sub["Category"].str.strip().str.lower().isin(cats_lower)]

    return sub


def build_report_context(
    today: date | None = None,
    selected_period: str | None = None,
    date_from_param: date | None = None,
    date_to_param: date | None = None,
    txn_type: str = "all",
    person: str = "all",
    categories: list[str] | None = None,
) -> dict[str, Any]:
    if today is None:
        today = datetime.now(settings.TIMEZONE).date()

    categories = [c for c in (categories or []) if c and c.strip()]

    df = load_transactions()
    cycles_ledger = load_cycles() if settings.BUDGET_CYCLE else []
    all_periods = [p for p in cycle_periods(df, cycles_ledger, today) if p[0] <= today]

    # Fallback to calendar month when no cycle boundaries exist
    if not all_periods:
        start_fb = today.replace(day=1)
        all_periods = [(start_fb, today, f"{today.strftime('%B %Y')} (calendar month)")]

    # Newest-first for UI navigation (index 0 = most recent)
    periods_newest_first = list(reversed(all_periods))
    selected_index = 0

    if date_from_param and date_to_param and not selected_period:
        # Custom date range takes priority when explicitly provided without period
        pass
    elif selected_period:
        for i, (s, _e, _lbl) in enumerate(periods_newest_first):
            if s.isoformat() == selected_period:
                selected_index = i
                break
    elif date_from_param or date_to_param:
        probe = date_from_param or date_to_param
        for i, (s, e, _lbl) in enumerate(periods_newest_first):
            if s <= probe <= e:
                selected_index = i
                break

    # Resolve effective date range
    if date_from_param and date_to_param and not selected_period:
        date_from = date_from_param
        date_to = date_to_param
        period_label = f"{date_from.strftime('%d %b').lstrip('0')} – {date_to.strftime('%d %b %Y').lstrip('0')}"
    else:
        sel_start, sel_end, sel_label = periods_newest_first[selected_index]
        date_from = sel_start
        date_to = sel_end
        period_label = (
            f"{sel_label} · "
            f"{sel_start.strftime('%d %b').lstrip('0')} – "
            f"{sel_end.strftime('%d %b %Y').lstrip('0')}"
        )

    days_elapsed = max((date_to - date_from).days + 1, 1)

    # ── Main filtered sub-frame ────────────────────────────────────────────
    sub = _filter_df(df, date_from, date_to, txn_type, person, categories)

    income = float(sub[sub["Type"] == "Income"]["_base"].sum())
    expense = float(sub[sub["Type"] == "Expense"]["_base"].sum())
    savings_val = float(sub[sub["Type"] == "Savings"]["_base"].sum())
    net = income - expense - savings_val
    daily_avg = expense / days_elapsed
    savings_rate = savings_val / income if income > 0 else 0.0

    # Unaccounted only when type filter is 'all'
    unaccounted: float | None = None
    if txn_type.lower() in ("all", "") and income > 0:
        sal = float(sub[salary_mask(sub)]["_base"].sum())
        unaccounted = sal - expense - savings_val

    summary = {
        "income": income,
        "expense": expense,
        "savings": savings_val,
        "net": net,
        "daily_avg": daily_avg,
        "savings_rate": savings_rate,
        "unaccounted": unaccounted,
    }

    # ── Category breakdown ─────────────────────────────────────────────────
    try:
        cat_budgets: dict[str, float] = load_category_budgets()
    except Exception:
        log.warning("Failed to load category budgets", exc_info=True)
        cat_budgets = {}

    exp_sub = sub[sub["Type"] == "Expense"]
    cat_groups = exp_sub.groupby("Category")["_base"].agg(["sum", "count"])
    total_expense_for_cat = float(exp_sub["_base"].sum()) or 1.0

    cat_list: list[dict] = []
    for cat_name, row_data in cat_groups.iterrows():
        spend = float(row_data["sum"])
        budget = cat_budgets.get(str(cat_name))
        pct_of_budget = (spend / budget) if budget and budget > 0 else None
        cat_list.append({
            "name": str(cat_name),
            "spend": spend,
            "budget": budget,
            "pct_of_budget": pct_of_budget,
            "pct_of_expense": spend / total_expense_for_cat,
            "color_idx": _cat_color_idx(str(cat_name)),
            "txn_count": int(row_data["count"]),
        })
    cat_list.sort(key=lambda c: c["spend"], reverse=True)

    # ── Category trends (up to 6 prior periods, including selected) ────────
    trend_window = periods_newest_first[selected_index: selected_index + _CAT_TREND_PERIODS]
    trend_window = list(reversed(trend_window))  # oldest first

    cat_trend_periods_labels = [lbl for _, _, lbl in trend_window]
    cat_names_for_trend = [c["name"] for c in cat_list[:10]]

    cat_trend_rows: list[dict] = []
    max_trend_val = 0.0
    for cat_name in cat_names_for_trend:
        values = []
        for ts, te, _ in trend_window:
            period_sub = _filter_df(df, ts, te, "expense", person, [])
            val = float(period_sub[period_sub["Category"] == cat_name]["_base"].sum())
            values.append(val)
            max_trend_val = max(max_trend_val, val)
        cat_trend_rows.append({
            "name": cat_name,
            "values": values,
            "color_idx": _cat_color_idx(cat_name),
        })

    cat_trends = {
        "periods": cat_trend_periods_labels,
        "rows": cat_trend_rows,
        "max_val": max_trend_val,
    }

    # ── Person breakdown ───────────────────────────────────────────────────
    person_groups = (
        sub.groupby(["Person", "Type"])["_base"]
        .sum()
        .unstack(fill_value=0)
    )
    persons: list[dict] = []
    for p_name in person_groups.index:
        pg = person_groups.loc[p_name]
        persons.append({
            "name": str(p_name),
            "income": float(pg.get("Income", 0)),
            "expense": float(pg.get("Expense", 0)),
            "savings": float(pg.get("Savings", 0)),
        })
    persons.sort(key=lambda p: p["expense"], reverse=True)

    # ── Type split ─────────────────────────────────────────────────────────
    income_anchor = income if income > 0 else ((expense + savings_val) or 1.0)
    expense_pct = min(expense / income_anchor * 100, 100)
    savings_pct = min(savings_val / income_anchor * 100, max(100 - expense_pct, 0))
    remain_pct = max(100 - expense_pct - savings_pct, 0)

    type_split = {
        "expense_pct": round(expense_pct, 1),
        "savings_pct": round(savings_pct, 1),
        "remain_pct": round(remain_pct, 1),
    }

    # ── Recurring vs one-off ───────────────────────────────────────────────
    if "IsRecurring" in sub.columns:
        rec_sub = sub[sub["IsRecurring"] == True]  # noqa: E712
        oneoff_sub = sub[sub["IsRecurring"] != True]  # noqa: E712
    else:
        rec_sub = sub.iloc[0:0]
        oneoff_sub = sub

    recurring = {"total": float(rec_sub["_base"].sum()), "count": int(len(rec_sub))}
    oneoff = {"total": float(oneoff_sub["_base"].sum()), "count": int(len(oneoff_sub))}

    # ── Top 10 expenses ────────────────────────────────────────────────────
    top_df = sub[sub["Type"] == "Expense"].copy()
    top_df = top_df.sort_values("_base", ascending=False).head(10)
    top_txns: list[dict] = []
    for rank, (_, txn_row) in enumerate(top_df.iterrows(), 1):
        top_txns.append({
            "date": str(txn_row.get("Date", ""))[:10],
            "description": str(txn_row.get("Description", "")),
            "category": str(txn_row.get("Category", "")),
            "person": str(txn_row.get("Person", "")),
            "amount": float(txn_row["_base"]),
            "color_idx": _cat_color_idx(str(txn_row.get("Category", ""))),
            "rank": rank,
        })

    # ── Daily spend chart ──────────────────────────────────────────────────
    sub_copy = sub.copy()
    sub_copy["_date"] = pd.to_datetime(sub_copy["Date"], errors="coerce").dt.date
    exp_daily = (
        sub_copy[sub_copy["Type"] == "Expense"]
        .groupby("_date")["_base"]
        .sum()
    )
    day_range = [date_from + timedelta(days=i) for i in range((date_to - date_from).days + 1)]
    daily_amounts = [float(exp_daily.get(d, 0.0)) for d in day_range]
    max_daily = max(daily_amounts) if daily_amounts else 0.0
    max_daily_safe = max_daily if max_daily > 0 else 1.0

    daily_spend: list[dict] = [
        {
            "day": d.day,
            "date_str": d.isoformat(),
            "amount": amt,
            "pct_of_max": round(amt / max_daily_safe * 100, 1),
            "is_today": d == today,
            "is_max": amt == max_daily and amt > 0,
        }
        for d, amt in zip(day_range, daily_amounts)
    ]

    # ── Multi-period trend (all periods, oldest first) ─────────────────────
    trend_income_vals: list[float] = []
    trend_expense_vals: list[float] = []
    trend_savings_vals: list[float] = []
    trend_labels: list[str] = []
    trend_short: list[str] = []

    for ts, te, tlbl in all_periods:
        t_sub = _filter_df(df, ts, te, "all", "all", [])
        trend_income_vals.append(float(t_sub[t_sub["Type"] == "Income"]["_base"].sum()))
        trend_expense_vals.append(float(t_sub[t_sub["Type"] == "Expense"]["_base"].sum()))
        trend_savings_vals.append(float(t_sub[t_sub["Type"] == "Savings"]["_base"].sum()))
        trend_labels.append(tlbl)
        trend_short.append(ts.strftime("%b %y"))

    trend_max = max([0.0] + trend_income_vals + trend_expense_vals + trend_savings_vals)
    current_idx = len(all_periods) - 1 - selected_index

    trend = {
        "periods": trend_labels,
        "short_labels": trend_short,
        "income": trend_income_vals,
        "expense": trend_expense_vals,
        "savings": trend_savings_vals,
        "max_val": trend_max,
        "current_idx": current_idx,
    }

    # ── Currency mix ───────────────────────────────────────────────────────
    currency_mix = None
    if "Currency" in sub.columns:
        cur_groups = sub.groupby("Currency")["_base"].sum()
        if len(cur_groups) > 1:
            total_base_all = float(cur_groups.sum()) or 1.0
            currency_mix = [
                {
                    "code": str(code),
                    "total_base": float(val),
                    "pct": round(float(val) / total_base_all * 100, 1),
                    "color_idx": i % _N_CAT_COLORS,
                }
                for i, (code, val) in enumerate(
                    cur_groups.sort_values(ascending=False).items()
                )
            ]

    # ── Warnings ───────────────────────────────────────────────────────────
    warnings: list[dict] = []
    over_cats = [
        c["name"] for c in cat_list
        if c.get("pct_of_budget") and c["pct_of_budget"] > 1.0
    ]
    if over_cats:
        warnings.append({"level": "error", "message": f"{', '.join(over_cats)} over budget"})

    if net < 0:
        warnings.append({
            "level": "error",
            "message": f"Expenses exceeded income by {abs(net):.0f} {settings.DISPLAY_CURRENCY}",
        })

    if income > 0 and savings_rate < 0.05:
        warnings.append({
            "level": "warn",
            "message": f"Savings rate is {savings_rate*100:.1f}% — below 5% target",
        })

    if income > 0 and days_elapsed > 0 and daily_avg > income / days_elapsed * 1.1:
        warnings.append({"level": "warn", "message": "Daily spending is running above income pace"})

    if income == 0:
        warnings.append({"level": "warn", "message": "No income recorded for this period"})

    # ── URL helper to retain active filters across period navigation ───────
    def _make_report_url(p_iso: str | None = None, t_val: str = "all", pers_val: str = "all", cats_val: list[str] | None = None) -> str:
        cats_val = cats_val or []
        params = []
        if p_iso:
            params.append(f"period={p_iso}")
        if t_val and t_val.lower() != "all":
            params.append(f"type={t_val.lower()}")
        if pers_val and pers_val.lower() != "all":
            params.append(f"person={pers_val}")
        for c in cats_val:
            params.append(f"category={c}")
        return "/report?" + "&".join(params) if params else "/report"

    cur_period_iso = periods_newest_first[selected_index][0].isoformat()

    prev_url = _make_report_url(
        periods_newest_first[selected_index + 1][0].isoformat(),
        txn_type, person, categories
    ) if selected_index + 1 < len(periods_newest_first) else None

    next_url = _make_report_url(
        periods_newest_first[selected_index - 1][0].isoformat(),
        txn_type, person, categories
    ) if selected_index > 0 else None

    available_periods_nav = [
        {
            "label": lbl,
            "value": s.isoformat(),
            "url": _make_report_url(s.isoformat(), txn_type, person, categories),
            "is_selected": i == selected_index,
        }
        for i, (s, _e, lbl) in enumerate(periods_newest_first)
    ]

    period_nav = {
        "prev_url": prev_url,
        "next_url": next_url,
        "available_periods": available_periods_nav,
        "selected_period": cur_period_iso,
    }

    # ── Active filter chips with accurate clear URLs ───────────────────────
    active_chips = []
    if txn_type and txn_type.lower() != "all":
        active_chips.append({
            "label": txn_type.capitalize(),
            "clear_url": _make_report_url(cur_period_iso, "all", person, categories),
        })
    if person and person.lower() != "all":
        active_chips.append({
            "label": person,
            "clear_url": _make_report_url(cur_period_iso, txn_type, "all", categories),
        })
    for cat in categories:
        remaining_cats = [c for c in categories if c != cat]
        active_chips.append({
            "label": cat,
            "clear_url": _make_report_url(cur_period_iso, txn_type, person, remaining_cats),
        })

    # ── Filter lists ───────────────────────────────────────────────────────
    all_persons = sorted(df["Person"].dropna().unique().tolist()) if "Person" in df.columns else []
    all_categories = (
        sorted(df["Category"].dropna().unique().tolist()) if "Category" in df.columns else []
    )

    return {
        "period_label": period_label,
        "date_from": date_from,
        "date_to": date_to,
        "days_elapsed": days_elapsed,
        "currency": settings.DISPLAY_CURRENCY,
        "summary": summary,
        "categories": cat_list,
        "cat_trends": cat_trends,
        "persons": persons,
        "type_split": type_split,
        "recurring": recurring,
        "oneoff": oneoff,
        "top_txns": top_txns,
        "daily_spend": daily_spend,
        "trend": trend,
        "currency_mix": currency_mix,
        "goals": None,
        "warnings": warnings,
        "persons_list": all_persons,
        "categories_list": all_categories,
        "txn_types": ["Income", "Expense", "Savings"],
        "active_filters": {
            "type": txn_type,
            "person": person,
            "categories": categories,
        },
        "active_chips": active_chips,
        "period_nav": period_nav,
    }


def _apply_display_currency(ctx: dict, target: str) -> dict:
    """Convert all monetary context values from base to display currency."""
    display = str(settings.DISPLAY_CURRENCY).strip().upper()
    target = str(target or "").strip().upper() or display
    ctx["currency"] = target

    if target == display:
        return ctx

    rates = load_rates()
    if not rates.get(target):
        ctx["currency"] = display
        return ctx

    def conv(v: float | None) -> float | None:
        if v is None:
            return None
        return convert_from_base(v, target, rates)

    # Summary
    s = ctx["summary"]
    for field in ("income", "expense", "savings", "daily_avg", "unaccounted"):
        s[field] = conv(s[field])
    s["net"] = (s["income"] or 0) - (s["expense"] or 0) - (s["savings"] or 0)

    # Categories
    for c in ctx["categories"]:
        c["spend"] = conv(c["spend"]) or 0.0
        if c["budget"] is not None:
            c["budget"] = conv(c["budget"])

    # Cat trends
    for row in ctx["cat_trends"]["rows"]:
        row["values"] = [conv(v) or 0.0 for v in row["values"]]
    ctx["cat_trends"]["max_val"] = conv(ctx["cat_trends"]["max_val"]) or 0.0

    # Persons
    for p in ctx["persons"]:
        p["income"] = conv(p["income"]) or 0.0
        p["expense"] = conv(p["expense"]) or 0.0
        p["savings"] = conv(p["savings"]) or 0.0

    # Recurring / oneoff
    ctx["recurring"]["total"] = conv(ctx["recurring"]["total"]) or 0.0
    ctx["oneoff"]["total"] = conv(ctx["oneoff"]["total"]) or 0.0

    # Top txns
    for t in ctx["top_txns"]:
        t["amount"] = conv(t["amount"]) or 0.0

    # Daily spend — recalculate pct after conversion
    for d in ctx["daily_spend"]:
        d["amount"] = conv(d["amount"]) or 0.0

    max_daily = max((d["amount"] for d in ctx["daily_spend"]), default=0.0)
    max_daily_safe = max_daily if max_daily > 0 else 1.0
    for d in ctx["daily_spend"]:
        d["pct_of_max"] = round(d["amount"] / max_daily_safe * 100, 1)
        d["is_max"] = d["amount"] == max_daily and d["amount"] > 0

    # Trend
    for attr in ("income", "expense", "savings"):
        ctx["trend"][attr] = [conv(v) or 0.0 for v in ctx["trend"][attr]]
    ctx["trend"]["max_val"] = conv(ctx["trend"]["max_val"]) or 0.0

    # Currency mix
    if ctx["currency_mix"]:
        for cm in ctx["currency_mix"]:
            cm["total_base"] = conv(cm["total_base"]) or 0.0

    return ctx


@router.get("/report", response_class=HTMLResponse, dependencies=[Depends(require_session)])
async def report(
    request: Request,
    period: str = "",
    date_from: str = "",
    date_to: str = "",
    txn_type: str = Query(default="all", alias="type"),
    person: str = "all",
    category: list[str] | None = Query(default=None),
):
    kwargs: dict = {}
    if period:
        kwargs["selected_period"] = period.strip()
    else:
        jf, jt = _parse_date(date_from), _parse_date(date_to)
        if jf:
            kwargs["date_from_param"] = jf
        if jt:
            kwargs["date_to_param"] = jt

    cat_list = category or []
    if isinstance(cat_list, str):
        cat_list = [cat_list]

    ctx = build_report_context(
        txn_type=txn_type or "all",
        person=person or "all",
        categories=cat_list,
        **kwargs,
    )
    ctx["active_filters"]["date_from"] = date_from
    ctx["active_filters"]["date_to"] = date_to
    ctx = _apply_display_currency(ctx, get_session_currency(request))

    is_htmx = request.headers.get("HX-Request") == "true"
    template = "_report_content.html" if is_htmx else "report.html"
    return request.app.state.templates.TemplateResponse(request, template, ctx)


@router.get(
    "/report/section/categories",
    response_class=HTMLResponse,
    dependencies=[Depends(require_session)],)
async def report_categories(
    request: Request,
    period: str = "",
    date_from: str = "",
    date_to: str = "",
    txn_type: str = Query(default="all", alias="type"),
    person: str = "all",
    category: list[str] | None = Query(default=None),
):
    kwargs: dict = {}
    if period:
        kwargs["selected_period"] = period.strip()
    else:
        jf, jt = _parse_date(date_from), _parse_date(date_to)
        if jf:
            kwargs["date_from_param"] = jf
        if jt:
            kwargs["date_to_param"] = jt

    cat_list = category or []
    if isinstance(cat_list, str):
        cat_list = [cat_list]

    ctx = build_report_context(
        txn_type=txn_type or "all",
        person=person or "all",
        categories=cat_list,
        **kwargs,
    )
    ctx = _apply_display_currency(ctx, get_session_currency(request))
    return request.app.state.templates.TemplateResponse(
        request, "_report_categories.html", ctx
    )
