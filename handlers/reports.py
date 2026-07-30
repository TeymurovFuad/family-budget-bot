"""/summary /week /budget /top /savings /report /rates /chart + budget alert."""

import calendar
import io
import os
from datetime import date, datetime, timedelta

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationHandlerStop, ContextTypes
from telegram.helpers import escape_markdown

import settings
from settings import TIMEZONE
from config import auth, get_display_currency, SAVINGS_TARGET, log
from cycles import (
    BEFORE_CYCLES_LABEL, load_cycles, current_cycle_start, cycle_totals,
    cycle_periods, detect_missing_boundaries,
)
from log_decorators import log_call
from data import (
    load_data, load_rates, load_budgets, load_reference_data,
    now_utc, current_year_and_month, month_name, get_rate,
)
from excel_ops import async_update_currency_rates
from file_storage import get_excel_path_for_reading, load_budgets_from_excel
from formatters import (
    format_amount, format_base_as_currency, budget_progress_bar, savings_emoji,
)


# Telegram hard limit is 4096 chars; leave headroom for Markdown overhead.
_REPORT_MSG_LIMIT_CHARS = 4000
# Telegram's absolute per-message character cap.
_TELEGRAM_HARD_LIMIT = 4096
# Section-break prefix used to detect safe chunk split points.
_SECTION_BREAK_PREFIX = "━━━"
# Timeout for the frankfurter.dev live-rates HTTP call, in seconds.
_RATES_HTTP_TIMEOUT_S = 10.0


def _current_cycle_bounds() -> tuple[date, date, str] | None:
    """(start, today, label) for the current cycle, or None → calendar fallback."""
    if not settings.BUDGET_CYCLE:
        return None
    # Local calendar date, consistent with handlers/cycle.py — a UTC date can
    # lag/lead the user's day around midnight.
    today = datetime.now(TIMEZONE).date()
    current = current_cycle_start(today)
    if current is None:
        return None
    start, label = current
    return start, today, label


async def _send_cycle_summary(msg, ccy: str, df, rates,
                              start: date, end: date, label: str,
                              extra_keywords: list[str] | None = None) -> None:
    """msg is anything with reply_text — update.message or query.message."""
    if label == BEFORE_CYCLES_LABEL:
        # Implicit bucket for rows older than the first boundary — it has no
        # salary anchor, so salary/unaccounted math is excluded on purpose.
        totals  = cycle_totals(df, start, end, extra_keywords)
        income  = totals["income"]
        expense = totals["expense"]
        savings = totals["savings"]
        net     = income - expense - savings
        await msg.reply_text(
            f"📊 *{BEFORE_CYCLES_LABEL} — Summary* ({ccy})\n"
            f"_{start.isoformat()} → {end.isoformat()} (before the first recorded cycle)_\n\n"
            f"💰 Income:   `{format_base_as_currency(income, ccy, rates)}`\n"
            f"💸 Expenses: `{format_base_as_currency(expense, ccy, rates)}`\n"
            f"🏦 Savings:  `{format_base_as_currency(savings, ccy, rates)}`\n"
            f"📈 Net:      `{format_base_as_currency(net, ccy, rates)}`",
            parse_mode="Markdown",
        )
        return
    totals  = cycle_totals(df, start, end, extra_keywords)
    income  = totals["income"]
    expense = totals["expense"]
    savings = totals["savings"]
    net     = income - expense - savings
    rate    = savings / income if income > 0 else 0
    days_elapsed = (end - start).days + 1
    daily_avg    = expense / days_elapsed if days_elapsed > 0 else 0
    unaccounted  = totals["unaccounted"]
    unacc_note   = " (over-reported)" if unaccounted < 0 else ""

    net_line = (f"✅ *Net:* {format_base_as_currency(net, ccy, rates)}" if net >= 0
                else f"⚠️ *Net:* {format_base_as_currency(net, ccy, rates)}")

    await msg.reply_text(
        f"📊 *Cycle {escape_markdown(label)} — Summary* ({ccy})\n"
        f"_{start.isoformat()} → {'today' if end == now_utc().date() else end.isoformat()}, day {days_elapsed}_\n\n"
        f"💰 Income:   `{format_base_as_currency(income, ccy, rates)}`\n"
        f"💸 Expenses: `{format_base_as_currency(expense, ccy, rates)}`\n"
        f"🏦 Savings:  `{format_base_as_currency(savings, ccy, rates)}`\n"
        f"{net_line}\n\n"
        f"{savings_emoji(rate)} Savings rate: *{rate:.0%}*\n"
        f"💼 Salary received: `{format_base_as_currency(totals['salary'], ccy, rates)}`\n"
        f"❓ Unaccounted: `{format_base_as_currency(unaccounted, ccy, rates)}`{unacc_note}\n"
        f"📉 Daily average spend: `{format_base_as_currency(daily_avg, ccy, rates)}`",
        parse_mode="Markdown",
    )


async def _send_month_summary(msg, ccy: str, df, rates, year: int, month: str) -> None:
    """Calendar-month summary. Projection line only for the current month."""
    sub     = df[(df["Year"] == year) & (df["Month"] == month) & df["IsDone"]]
    income  = sub[sub["Type"] == "Income"]["_base"].sum()
    expense = sub[sub["Type"] == "Expense"]["_base"].sum()
    savings = sub[sub["Type"] == "Savings"]["_base"].sum()
    net     = income - expense - savings
    rate    = savings / income if income > 0 else 0

    net_line = (f"✅ *Net:* {format_base_as_currency(net, ccy, rates)}" if net >= 0
                else f"⚠️ *Net:* {format_base_as_currency(net, ccy, rates)}")

    summary_text = (
        f"📊 *{month} {year} — Summary* ({ccy})\n\n"
        f"💰 Income:   `{format_base_as_currency(income, ccy, rates)}`\n"
        f"💸 Expenses: `{format_base_as_currency(expense, ccy, rates)}`\n"
        f"🏦 Savings:  `{format_base_as_currency(savings, ccy, rates)}`\n"
        f"{net_line}\n\n"
        f"{savings_emoji(rate)} Savings rate: *{rate:.0%}*"
    )

    if (year, month) == current_year_and_month():
        now           = now_utc()
        days_elapsed  = now.day
        days_in_month = calendar.monthrange(now.year, now.month)[1]
        projected     = expense / days_elapsed * days_in_month if days_elapsed > 0 else 0
        summary_text += (
            f"\n📈 Projected month-end spend: `{format_base_as_currency(projected, ccy, rates)}`"
        )

    await msg.reply_text(summary_text, parse_mode="Markdown")


def _summary_years(df) -> list[int]:
    """Actual MasterData years, newest first, years with data only."""
    return sorted({int(y) for y in df["Year"].dropna().unique()}, reverse=True)


def _summary_months(df, year: int) -> list[int]:
    """Month numbers with data for one year, ascending."""
    from handlers.summary_picker import MONTHS_BY_NAME
    names = df[df["Year"] == year]["Month"].dropna().unique()
    return sorted({MONTHS_BY_NAME[str(n).lower()] for n in names
                   if str(n).lower() in MONTHS_BY_NAME})


def _resolve_ledger_first(resolution: dict, cycles, today: date) -> dict:
    """
    Item: past-period walk. '/summary aug 2025' resolves against the cycle
    ledger first — a month+year resolution whose label matches a recorded
    cycle ('Aug 2025') maps to that cycle; calendar month otherwise.
    """
    if not cycles or resolution.get("kind") != "month":
        return resolution
    from handlers.summary_picker import cycle_bounds
    wanted = date(resolution["year"], resolution["month"], 1).strftime("%b %Y")
    for i in range(len(cycles) - 1, -1, -1):
        if cycles[i][0] <= today and cycles[i][1] == wanted:
            start, end = cycle_bounds(cycles, i, today)
            return {"kind": "cycle", "start": start, "end": end, "label": cycles[i][1]}
    return resolution


async def _maybe_prompt_backfill(msg, ctx, resolution: dict, cycles) -> bool:
    """
    Lazy backfill: when a range/entire-period report covers months with no
    recorded cycle boundary, ask once before rendering. Returns True when a
    prompt was sent (rendering deferred to the sum:bf callback).
    """
    if not settings.BUDGET_CYCLE or not cycles:
        return False
    if resolution.get("kind") not in ("range", "entire"):
        return False
    missing = detect_missing_boundaries(resolution["start"], resolution["end"], cycles)
    if not missing:
        return False
    ctx.user_data["sum_pending"] = resolution
    months = ", ".join(m.strftime("%b %Y") for m in missing[:6])
    if len(missing) > 6:
        months += f" (+{len(missing) - 6} more)"
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Yes, fill them in", callback_data="sum:bf:yes"),
        InlineKeyboardButton("⏭ Skip", callback_data="sum:bf:skip"),
    ]])
    await msg.reply_text(
        f"🔍 Found missing cycle boundaries for {months} — fill them in first?",
        reply_markup=keyboard,
    )
    return True


async def _send_entire_period(msg, ccy: str, df, rates, cycles, today: date,
                              extra_keywords: list[str] | None = None) -> None:
    """One summary per cycle, oldest first, incl. the 'Before cycles' bucket."""
    periods = [p for p in cycle_periods(df, cycles, today) if p[0] <= today]
    if not periods:
        await msg.reply_text(
            "No cycles recorded yet — use `/cycle started` or `/cycle detect` first.",
            parse_mode="Markdown",
        )
        return
    for start, end, label in periods:
        await _send_cycle_summary(msg, ccy, df, rates, start, end, label, extra_keywords)


async def _render_summary_resolution(msg, ccy: str, df, rates, resolution: dict,
                                      extra_keywords: list[str] | None = None) -> None:
    """Dispatch a parse_summary_args() result to the right report."""
    kind = resolution["kind"]
    if kind == "month":
        await _send_month_summary(msg, ccy, df, rates,
                                  resolution["year"], month_name(resolution["month"]))
    elif kind == "cycle":
        await _send_cycle_summary(msg, ccy, df, rates,
                                  resolution["start"], resolution["end"], resolution["label"],
                                  extra_keywords)
    elif kind == "entire":
        today = now_utc().date()
        cycles = load_cycles() if settings.BUDGET_CYCLE else []
        await _send_entire_period(msg, ccy, df, rates, cycles, today, extra_keywords)
    else:  # range
        budgets = load_budgets()
        text = _build_range_report(df, rates, budgets, ccy,
                                   resolution["start"], resolution["end"], resolution["label"])
        await msg.reply_text(text, parse_mode="Markdown")


@auth
@log_call()
async def cmd_summary(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if ctx.args and ctx.args[0].lower() == "help":
        await update.message.reply_text(
            "📊 */summary* — Monthly summary\n\n"
            "Bare /summary opens a picker: quick buttons plus history drill\\-down\\.\n"
            "Or type a period directly: `/summary aug 2025`, `/summary 08.2025`, "
            "`/summary jul`, `/summary aug 2025 \\- jan 2026`\\.",
            parse_mode="MarkdownV2",
        )
        return

    from handlers.summary_picker import build_summary_keyboard, parse_summary_args

    uid = update.effective_user.id
    ccy = get_display_currency(uid)
    try:
        df    = load_data()
        rates = load_rates()
    except FileNotFoundError as e:
        await update.message.reply_text(f"❌ {e}"); return

    today = now_utc().date()

    if ctx.args:
        # Typed argument → render the report directly, no buttons.
        cycles = None
        if settings.BUDGET_CYCLE:
            cycles = load_cycles()

        if ctx.args[0].lower() in ("all", "entire") and settings.BUDGET_CYCLE:
            # Entire-period walk over the whole cycle ledger.
            dates = pd.to_datetime(df["Date"], errors="coerce").dt.date.dropna()
            earliest = dates.min() if not dates.empty else today
            resolution = {"kind": "entire", "start": earliest, "end": today}
            if await _maybe_prompt_backfill(update.message, ctx, resolution, cycles):
                return
            await _send_entire_period(update.message, ccy, df, rates, cycles or [], today,
                                      ctx.user_data.get("detect_extra_keywords"))
            return

        resolution = parse_summary_args(ctx.args, today, cycles)
        if resolution is None:
            await update.message.reply_text(
                "❌ Could not understand that period. Try `/summary aug 2025`, "
                "`/summary 08.2025`, `/summary jul`, or `/summary aug 2025 - jan 2026`.",
                parse_mode="Markdown",
            )
            return
        resolution = _resolve_ledger_first(resolution, cycles, today)
        if await _maybe_prompt_backfill(update.message, ctx, resolution, cycles):
            return
        await _render_summary_resolution(update.message, ccy, df, rates, resolution,
                                         ctx.user_data.get("detect_extra_keywords"))
        return

    # Bare /summary → one message, three zones.
    keyboard = build_summary_keyboard(bool(settings.BUDGET_CYCLE), _summary_years(df))
    await update.message.reply_text(
        "📊 *Summary* — pick a period:",
        parse_mode="Markdown",
        reply_markup=keyboard,
    )


@log_call()
async def handle_summary_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Handle inline button taps from the /summary picker (callback data 'sum:…')."""
    from handlers.summary_picker import (
        build_cycle_keyboard, build_month_keyboard, build_year_keyboard,
        cycle_bounds,
    )

    query = update.callback_query
    await query.answer()
    msg  = query.message
    ccy  = get_display_currency(query.from_user.id)
    try:
        df    = load_data()
        rates = load_rates()
    except FileNotFoundError as e:
        await msg.reply_text(f"❌ {e}")
        return

    today = now_utc().date()
    parts = query.data.split(":")
    action = parts[1]

    if action == "bf":
        # Lazy-backfill prompt answer (item: missing cycle boundaries).
        pending = ctx.user_data.pop("sum_pending", None)
        if parts[2] == "yes":
            await msg.edit_text(
                "🔍 Run /cycle detect to review and record the missing "
                "boundaries, then rerun the report."
            )
            return
        # Skip → render the deferred report with the gaps as they are.
        await msg.edit_reply_markup(reply_markup=None)
        if pending is None:
            await msg.reply_text("Nothing pending to render — run the report again.")
            return
        await _render_summary_resolution(msg, ccy, df, rates, pending,
                                         ctx.user_data.get("detect_extra_keywords"))
        return

    if action in ("tm", "lm"):
        year, month = current_year_and_month()
        if action == "lm":
            prev = today.replace(day=1) - timedelta(days=1)
            year, month = prev.year, month_name(prev.month)
        await _send_month_summary(msg, ccy, df, rates, year, month)
        return

    if action in ("tc", "lc"):
        cycles = [c for c in load_cycles() if c[0] <= today]
        need = 1 if action == "tc" else 2
        if len(cycles) < need:
            await msg.reply_text("❌ Not enough cycles recorded yet.")
            return
        index = len(cycles) - need
        start, end = cycle_bounds(cycles, index, today)
        await _send_cycle_summary(msg, ccy, df, rates, start, end, cycles[index][1],
                                  ctx.user_data.get("detect_extra_keywords"))
        return

    if action == "cal" or action == "yrs":
        page = int(parts[2]) if action == "yrs" else 0
        years = _summary_years(df)
        if not years:
            await msg.reply_text("No data recorded yet.")
            return
        stage = (ctx.user_data.get("sum_range") or {}).get("stage")
        prompt = {"from": "📊 *Range — From:* pick a year:",
                  "to":   "📊 *Range — To:* pick a year:"}.get(stage, "📊 *History* — pick a year:")
        await msg.edit_text(prompt, parse_mode="Markdown",
                            reply_markup=build_year_keyboard(years, page))
        return

    if action == "y":
        year = int(parts[2])
        months = _summary_months(df, year)
        if not months:
            await msg.reply_text(f"No data for {year}.")
            return
        stage = (ctx.user_data.get("sum_range") or {}).get("stage")
        prompt = {"from": f"📊 *Range — From:* pick a month of {year}:",
                  "to":   f"📊 *Range — To:* pick a month of {year}:"}.get(
            stage, f"📊 *{year}* — pick a month:")
        await msg.edit_text(prompt, parse_mode="Markdown",
                            reply_markup=build_month_keyboard(year, months))
        return

    if action == "m":
        year, month = int(parts[2]), int(parts[3])
        state = ctx.user_data.get("sum_range")
        if state and state.get("stage") == "from":
            ctx.user_data["sum_range"] = {"stage": "to", "from": (year, month)}
            years = _summary_years(df)
            await msg.edit_text(
                f"📊 *Range — From:* {month_name(month)} {year} ✓\n*To:* pick a year:",
                parse_mode="Markdown",
                reply_markup=build_year_keyboard(years, 0),
            )
            return
        if state and state.get("stage") == "to":
            ctx.user_data.pop("sum_range", None)
            fy, fm = state["from"]
            start = date(fy, fm, 1)
            end   = date(year, month, calendar.monthrange(year, month)[1])
            if start > end:
                start, end = date(year, month, 1), date(fy, fm, calendar.monthrange(fy, fm)[1])
                fy, fm, year, month = year, month, fy, fm
            budgets = load_budgets()
            label = f"{month_name(fm)} {fy} – {month_name(month)} {year}"
            text = _build_range_report(df, rates, budgets, ccy, start, end, label)
            await msg.reply_text(text, parse_mode="Markdown")
            return
        await _send_month_summary(msg, ccy, df, rates, year, month_name(month))
        return

    if action == "cyc":
        cycles = [c for c in load_cycles() if c[0] <= today]
        if not cycles:
            await msg.reply_text("❌ No cycles recorded yet.")
            return
        page = int(parts[2]) if len(parts) > 2 else 0
        await msg.edit_text("📊 *Cycles* — pick one:", parse_mode="Markdown",
                            reply_markup=build_cycle_keyboard(cycles, today, page))
        return

    if action == "cs":
        start = date.fromisoformat(parts[2])
        cycles = [c for c in load_cycles() if c[0] <= today]
        for i, (c_start, label) in enumerate(cycles):
            if c_start == start:
                s, e = cycle_bounds(cycles, i, today)
                await _send_cycle_summary(msg, ccy, df, rates, s, e, label,
                                          ctx.user_data.get("detect_extra_keywords"))
                return
        await msg.reply_text("❌ That cycle is no longer in the ledger.")
        return

    if action == "rng":
        years = _summary_years(df)
        if not years:
            await msg.reply_text("No data recorded yet.")
            return
        ctx.user_data["sum_range"] = {"stage": "from"}
        await msg.edit_text("📊 *Range — From:* pick a year:", parse_mode="Markdown",
                            reply_markup=build_year_keyboard(years, 0))
        return

    await msg.reply_text("Unknown summary option.")


@auth
@log_call()
async def cmd_week(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if ctx.args and ctx.args[0].lower() == "help":
        await update.message.reply_text(
            "📅 */week* — Last 7 days\n\n"
            "Shows total spending broken down by category over the last 7 days\\.",
            parse_mode="MarkdownV2",
        )
        return

    from datetime import timedelta
    uid = update.effective_user.id
    ccy = get_display_currency(uid)
    try:
        df    = load_data()
        rates = load_rates()
    except FileNotFoundError as e:
        await update.message.reply_text(f"❌ {e}"); return

    now    = now_utc()
    cutoff = now.date() - timedelta(days=7)
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    sub = df[(df["Date"].dt.date >= cutoff) & (df["Type"] == "Expense") & df["IsDone"]]

    if sub.empty:
        await update.message.reply_text("No expense data found for the last 7 days."); return

    by_cat = sub.groupby("Category")["_base"].sum().sort_values(ascending=False)
    total  = by_cat.sum()

    lines = [f"📅 *Last 7 days — {format_base_as_currency(total, ccy, rates)} total*\n"]
    for cat, amt in by_cat.items():
        pct = amt / total * 100 if total > 0 else 0
        lines.append(f"• {cat}: `{format_base_as_currency(amt, ccy, rates)}` ({pct:.0f}%)")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


@auth
@log_call()
async def cmd_budget(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if ctx.args and ctx.args[0].lower() == "help":
        await update.message.reply_text(
            "💰 */budget* — Budget vs actual\n\n"
            "Compares your monthly budget limits against actual spend per category\\.\n"
            "🟢 within budget  🔴 over budget\\.\n"
            "Set limits with /setbudget \\(owner only\\)\\.",
            parse_mode="MarkdownV2",
        )
        return

    year, month = current_year_and_month()
    uid = update.effective_user.id
    ccy = get_display_currency(uid)
    try:
        df      = load_data()
        rates   = load_rates()
        budgets = load_budgets()
    except FileNotFoundError as e:
        await update.message.reply_text(f"❌ {e}"); return

    cycle = _current_cycle_bounds()
    if cycle is not None:
        start, end, label = cycle
        dates = pd.to_datetime(df["Date"], errors="coerce")
        sub = df[dates.notna() & (dates.dt.date >= start) & (dates.dt.date <= end)
                 & (df["Type"] == "Expense") & df["IsDone"]]
        title = (f"📋 *Budget vs Actual — Cycle {escape_markdown(label)}* ({ccy})\n"
                 f"_{start.isoformat()} → today_\n")
    else:
        sub = df[(df["Year"] == year) & (df["Month"] == month)
                 & (df["Type"] == "Expense") & df["IsDone"]]
        title = f"📋 *Budget vs Actual — {month} {year}* ({ccy})\n"
    by_cat = sub.groupby("Category")["_base"].sum()
    rate   = get_rate(ccy, rates)

    lines        = [title]
    total_budget = 0
    total_actual = 0

    for cat in load_reference_data()["categories"]:
        budget_base = budgets.get(cat, 0)
        actual_base = by_cat.get(cat, 0)
        if budget_base == 0 and actual_base == 0:
            continue
        budget = budget_base / rate
        actual = actual_base / rate
        total_budget += budget
        total_actual += actual
        over     = actual > budget > 0
        diff     = actual - budget
        diff_str = f"+{format_amount(diff, ccy)}" if diff > 0 else format_amount(diff, ccy)
        lines.append(
            f"{'🔴' if over else '🟢'} *{cat}*\n"
            f"   {budget_progress_bar(actual, budget)} "
            f"{format_amount(actual, ccy)} / {format_amount(budget, ccy)} ({diff_str})\n"
        )

    over_total = total_actual - total_budget
    lines.append(
        f"\n{'🔴' if over_total > 0 else '🟢'} "
        f"*Total: {format_amount(total_actual, ccy)} / {format_amount(total_budget, ccy)}*"
    )
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


@auth
@log_call()
async def cmd_top(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if ctx.args and ctx.args[0].lower() == "help":
        await update.message.reply_text(
            "🏆 */top* — Top 5 expenses\n\n"
            "Shows the 5 biggest expenses this month, sorted by amount\\.\n"
            "With budget cycles enabled, covers the current cycle instead of the calendar month\\.",
            parse_mode="MarkdownV2",
        )
        return

    year, month = current_year_and_month()
    uid = update.effective_user.id
    ccy = get_display_currency(uid)
    try:
        df    = load_data()
        rates = load_rates()
    except FileNotFoundError as e:
        await update.message.reply_text(f"❌ {e}"); return

    cycle = _current_cycle_bounds()
    if cycle is not None:
        start, end, label = cycle
        dates = pd.to_datetime(df["Date"], errors="coerce")
        sub = (df[dates.notna() & (dates.dt.date >= start) & (dates.dt.date <= end)
                  & (df["Type"] == "Expense") & df["IsDone"]]
               .sort_values("_base", ascending=False).head(5))
        empty_msg = "No expenses found this cycle."
        title = f"🏆 *Top 5 expenses — Cycle {escape_markdown(label)}* ({ccy})\n"
    else:
        sub = (df[(df["Year"] == year) & (df["Month"] == month)
                  & (df["Type"] == "Expense") & df["IsDone"]]
               .sort_values("_base", ascending=False).head(5))
        empty_msg = "No expenses found this month."
        title = f"🏆 *Top 5 expenses — {month} {year}* ({ccy})\n"

    if sub.empty:
        await update.message.reply_text(empty_msg); return

    lines = [title]
    for i, (_, row) in enumerate(sub.iterrows(), 1):
        desc     = row.get("Description", "") or ""
        cat      = row.get("Category", "?")
        orig_ccy = str(row.get("Currency") or settings.DISPLAY_CURRENCY)
        orig_val = row.get("Value", row["_base"])
        extra    = f" ({orig_val:,.0f} {orig_ccy})" if orig_ccy != settings.DISPLAY_CURRENCY and orig_ccy != ccy else ""
        lines.append(
            f"{i}. `{format_base_as_currency(row['_base'], ccy, rates)}`{extra} — "
            f"{desc or cat} _{cat}_"
        )

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


@auth
@log_call()
async def cmd_savings(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if ctx.args and ctx.args[0].lower() == "help":
        await update.message.reply_text(
            "📈 */savings* — Savings rate trend\n\n"
            "Shows a chart of your savings rate for the last 6 months vs your target\\.",
            parse_mode="MarkdownV2",
        )
        return

    try:
        df = load_data()
    except FileNotFoundError as e:
        await update.message.reply_text(f"❌ {e}"); return

    labels: list[str] = []
    rate_values: list[float] = []
    period_word = "month"
    title = "Savings Rate — Last 6 Months"

    cycles = load_cycles() if settings.BUDGET_CYCLE else []
    if cycles:
        # Cycle mode: last 6 recorded cycles (the "Before cycles" bucket has
        # no salary anchor and is skipped for trend purposes).
        today = datetime.now(TIMEZONE).date()
        periods = [
            p for p in cycle_periods(df, cycles, today)
            if p[2] != BEFORE_CYCLES_LABEL and p[0] <= today
        ][-6:]
        for start, end, label in periods:
            totals = cycle_totals(df, start, end,
                                  ctx.user_data.get("detect_extra_keywords"))
            income = totals["income"]
            rate   = totals["savings"] / income * 100 if income > 0 else 0
            labels.append(label)
            rate_values.append(round(rate, 1))
        period_word = "cycle"
        title = f"Savings Rate — Last {len(labels)} Cycle{'s' if len(labels) != 1 else ''}"
    else:
        now = now_utc()
        for delta in range(5, -1, -1):
            m  = (now.month - delta - 1) % 12
            y  = now.year + ((now.month - delta - 1) // 12)
            ms = month_name(m + 1)
            sub    = df[(df["Year"] == y) & (df["Month"] == ms) & df["IsDone"]]
            income  = sub[sub["Type"] == "Income"]["_base"].sum()
            savings_amt = sub[sub["Type"] == "Savings"]["_base"].sum()
            rate    = savings_amt / income * 100 if income > 0 else 0
            labels.append(ms[:3])   # abbreviated month name
            rate_values.append(round(rate, 1))

    if not rate_values:
        await update.message.reply_text("No data to chart yet.")
        return

    buf = _build_savings_chart(labels, rate_values, title=title)

    current_rate = rate_values[-1]
    prior_rate   = rate_values[-2] if len(rate_values) >= 2 else current_rate
    if current_rate > prior_rate:
        arrow = "↑"
    elif current_rate < prior_rate:
        arrow = "↓"
    else:
        arrow = "→"
    caption = (
        f"Savings rate this {period_word}: {current_rate:.1f}% {arrow}\n"
        f"vs prior {period_word}: {prior_rate:.1f}%"
    )
    await update.message.reply_photo(photo=buf, caption=caption)


@auth
@log_call()
async def cmd_report(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if ctx.args and ctx.args[0].lower() == "help":
        await update.message.reply_text(
            "📑 */report* — Full monthly report\n\n"
            "Income, expenses \\(fixed vs variable\\), savings, net, and savings rate\\.\n"
            "Breaks down spend by category with month\\-over\\-month deltas\\.\n"
            "With budget cycles enabled, covers the current cycle with "
            "cycle\\-over\\-cycle deltas\\.\n"
            "Over\\-budget categories are flagged 🔴\\.",
            parse_mode="MarkdownV2",
        )
        return

    year, month = current_year_and_month()
    uid = update.effective_user.id
    ccy = get_display_currency(uid)
    try:
        df      = load_data()
        rates   = load_rates()
        budgets = load_budgets()
    except FileNotFoundError as e:
        await update.message.reply_text(f"❌ {e}"); return

    cycle = _current_cycle_bounds()
    if cycle is not None:
        start, end, label = cycle
        dates = pd.to_datetime(df["Date"], errors="coerce")
        sub = df[dates.notna() & (dates.dt.date >= start) & (dates.dt.date <= end)
                 & df["IsDone"]]
        header = (f"📑 *Cycle Report — {escape_markdown(label)}* ({ccy})\n"
                  f"_{start.isoformat()} → today_")
    else:
        sub = df[(df["Year"] == year) & (df["Month"] == month) & df["IsDone"]]
        header = f"📑 *Monthly Report — {month} {year}* ({ccy})"
    income   = sub[sub["Type"] == "Income"]["_base"].sum()
    expense  = sub[sub["Type"] == "Expense"]["_base"].sum()
    savings  = sub[sub["Type"] == "Savings"]["_base"].sum()
    net      = income - expense - savings
    rate     = savings / income if income > 0 else 0
    by_cat   = sub[sub["Type"] == "Expense"].groupby("Category")["_base"].sum()
    recur    = sub[(sub["Type"] == "Expense") & sub["IsRecurring"].fillna(False).astype(bool)]["_base"].sum()
    discret  = expense - recur

    if cycle is not None:
        # Compare against the previous cycle (boundary before this one → day
        # before this cycle's start); no previous cycle → no deltas.
        prev_label = "previous cycle"
        prior = [c for c in load_cycles() if c[0] < start]
        if prior:
            p_start = prior[-1][0]
            p_end   = start - timedelta(days=1)
            dates   = pd.to_datetime(df["Date"], errors="coerce")
            prev_sub = df[dates.notna() & (dates.dt.date >= p_start)
                          & (dates.dt.date <= p_end) & df["IsDone"]]
        else:
            prev_sub = df.iloc[0:0]
    else:
        now             = now_utc()
        prev_month_num  = now.month - 1 if now.month > 1 else 12
        prev_year       = year if now.month > 1 else year - 1
        prev_label      = month_name(prev_month_num)
        prev_sub        = df[(df["Year"] == prev_year) & (df["Month"] == prev_label) & df["IsDone"]]
    prev_by_cat = prev_sub[prev_sub["Type"] == "Expense"].groupby("Category")["_base"].sum()

    by_input_ccy = sub[sub["Type"] == "Expense"].groupby("Currency")["Value"].sum()
    multi_ccy    = len(by_input_ccy) > 1

    lines = [
        header,
        "━━━━━━━━━━━━━━━━━━━",
        f"💰 Income:      `{format_base_as_currency(income, ccy, rates)}`",
        f"💸 Expenses:    `{format_base_as_currency(expense, ccy, rates)}`",
        f"   ↳ Fixed:     `{format_base_as_currency(recur, ccy, rates)}`",
        f"   ↳ Variable:  `{format_base_as_currency(discret, ccy, rates)}`",
        f"🏦 Savings:     `{format_base_as_currency(savings, ccy, rates)}`",
        f"📈 Net:         `{format_base_as_currency(net, ccy, rates)}`",
        f"📊 Savings rate: *{rate:.0%}* {savings_emoji(rate)}",
        "",
        f"━━━ By Category (vs {prev_label}) ━━━",
    ]
    for cat, amt in by_cat.sort_values(ascending=False).items():
        budget_base = budgets.get(cat, 0)
        pct        = amt / expense * 100 if expense > 0 else 0
        flag       = " 🔴" if budget_base and amt > budget_base else ""
        prev_amt   = prev_by_cat.get(cat, 0)
        if prev_amt > 0:
            delta     = amt - prev_amt
            delta_fmt = format_base_as_currency(abs(delta), ccy, rates)
            mom       = f" ({'+' if delta >= 0 else '-'}{delta_fmt})"
        else:
            mom = ""
        lines.append(f"• {cat}: `{format_base_as_currency(amt, ccy, rates)}` ({pct:.0f}%){flag}{mom}")

    if multi_ccy:
        lines += ["", "━━━ Original currencies ━━━"]
        for input_ccy, total in by_input_ccy.items():
            lines.append(f"• {input_ccy}: {total:,.0f}")

    report_text = "\n".join(lines)
    if len(report_text) <= _REPORT_MSG_LIMIT_CHARS:
        await update.message.reply_text(report_text, parse_mode="Markdown")
    else:
        # Split only at section-break lines (━━━…) to avoid breaking Markdown
        # spans across messages (Telegram rejects unmatched bold/code markers).
        chunks: list[str] = []
        current_lines: list[str] = []
        current_len = 0
        for line in report_text.split("\n"):
            line_len = len(line) + 1  # +1 for the joining newline
            if (line.startswith(_SECTION_BREAK_PREFIX)
                    and current_lines
                    and current_len + line_len > _REPORT_MSG_LIMIT_CHARS):
                chunks.append("\n".join(current_lines))
                current_lines = [line]
                current_len = line_len
            else:
                current_lines.append(line)
                current_len += line_len
        if current_lines:
            chunks.append("\n".join(current_lines))
        # Fallback: if no section break split the report and it's still too
        # long, send as a single message truncated to Telegram's hard limit.
        if len(chunks) == 1 and len(chunks[0]) > _TELEGRAM_HARD_LIMIT:
            text = report_text[:_TELEGRAM_HARD_LIMIT - 50] + "\n⚠️ Output too long — some data was omitted."  # 50-char buffer for the truncation suffix
            await update.message.reply_text(text, parse_mode="Markdown")
        else:
            for chunk in chunks:
                if len(chunk) > _TELEGRAM_HARD_LIMIT:
                    chunk = chunk[:_TELEGRAM_HARD_LIMIT - 50] + "\n⚠️ Output too long — some data was omitted."  # 50-char buffer for the truncation suffix
                await update.message.reply_text(chunk, parse_mode="Markdown")


@auth
@log_call()
async def cmd_rates(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if ctx.args and ctx.args[0].lower() == "help":
        await update.message.reply_text(
            "💱 */rates* — Exchange rates\n\n"
            "Shows exchange rates stored in your Excel \\(EUR per 1 unit\\)\\.\n"
            "Use `/rates refresh` to fetch live rates from frankfurter\\.dev and update Excel\\.",
            parse_mode="MarkdownV2",
        )
        return

    rates = load_rates()

    if ctx.args and ctx.args[0].lower() == "refresh":
        await update.message.reply_text("🔄 Fetching live rates from frankfurter.dev…")
        try:
            import httpx
            primary_url  = f"https://api.frankfurter.dev/v1/latest?from={settings.DISPLAY_CURRENCY}"
            fallback_url = f"https://api.frankfurter.app/latest?from={settings.DISPLAY_CURRENCY}"
            async with httpx.AsyncClient(follow_redirects=True, timeout=_RATES_HTTP_TIMEOUT_S) as client:
                try:
                    resp = await client.get(primary_url)
                    resp.raise_for_status()
                except Exception:
                    resp = await client.get(fallback_url)
                    resp.raise_for_status()
                data = resp.json()

            live: dict[str, float] = {
                raw_ccy.upper(): round(1 / raw_rate, 4)
                for raw_ccy, raw_rate in data["rates"].items() if raw_rate > 0
            }
            live[settings.DISPLAY_CURRENCY] = 1.0

            lines   = [f"📡 *Live rates vs Excel* ({settings.DISPLAY_CURRENCY} per 1 unit)\n"
                       f"_Source: frankfurter.dev — {data.get('date', 'today')}_\n"]
            updated: dict[str, float] = {}
            for cur_ccy, old_rate in sorted(rates.items()):
                if cur_ccy in live:
                    new_rate = live[cur_ccy]
                    diff     = new_rate - old_rate
                    sign     = "+" if diff >= 0 else ""
                    lines.append(f"`{cur_ccy}`: {old_rate:.4f} → *{new_rate:.4f}* ({sign}{diff:.4f})")
                    updated[cur_ccy] = new_rate
                else:
                    lines.append(f"`{cur_ccy}`: {old_rate:.4f} _(no live data, unchanged)_")

            if updated:
                await async_update_currency_rates(updated)
                lines.append(f"\n✅ Updated {len(updated)} rates in Excel.")
            else:
                lines.append("\n⚠️ No currencies could be matched to live data.")

            await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

        except Exception as e:
            log.exception("Live rate fetch failed")
            await update.message.reply_text(f"❌ Failed to fetch live rates: {e}")

    else:
        lines = [f"💱 *Current exchange rates* ({settings.DISPLAY_CURRENCY} per 1 unit)\n"]
        for cur_ccy, r in sorted(rates.items()):
            lines.append(f"`{cur_ccy}`: {r:.4f} {settings.DISPLAY_CURRENCY}")
        lines.append("\n_Tip: `/rates refresh` fetches live rates from frankfurter.dev and updates Excel._")
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


def _bar_color(spend: float, budget: float) -> str:
    """Return hex color for a chart bar based on spend vs budget."""
    if budget == 0:
        return "#9E9E9E"
    pct = spend / budget
    if pct <= 0.80:
        return "#4CAF50"
    if pct <= 1.00:
        return "#FF9800"
    return "#F44336"


def _build_savings_chart(
    months: list, rates: list, title: str = "Savings Rate — Last 6 Months"
) -> io.BytesIO:
    """Build a savings-rate line chart and return a PNG BytesIO buffer."""
    target = int(SAVINGS_TARGET * 100)

    fig, ax = plt.subplots(figsize=(8, 4))
    ax.plot(months, rates, "bo-", linewidth=2, markersize=7, label="Savings rate %")
    ax.axhline(target, color="grey", linestyle="--", linewidth=1.5, label=f"Target {target}%")
    ax.set_ylim(0, max(100, max(rates) + 10) if rates else 100)
    ax.set_ylabel("Savings rate (%)")
    ax.set_title(title, fontsize=13, fontweight="bold")
    ax.legend(fontsize=9)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    plt.tight_layout()

    buf = io.BytesIO()
    plt.savefig(buf, format="png", dpi=150)
    plt.close(fig)
    buf.seek(0)
    return buf


@auth
@log_call()
async def cmd_chart(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if ctx.args and ctx.args[0].lower() == "help":
        await update.message.reply_text(
            "📊 */chart* — Spending chart\n\n"
            "Shows a horizontal bar chart of this month's expenses by category\\.\n"
            "Bars are colour\\-coded: 🟢 under 80%  🟡 80\\-100%  🔴 over budget\\.",
            parse_mode="MarkdownV2",
        )
        return

    uid = update.effective_user.id
    ccy = get_display_currency(uid)
    try:
        df      = load_data()
        rates   = load_rates()
        budgets = load_budgets()
    except Exception as e:
        await update.message.reply_text(f"❌ {e}"); return

    now   = now_utc()
    year, month = now.year, month_name(now.month)

    sub = df[(df["Year"] == year) & (df["Month"] == month) & (df["Type"] == "Expense") & df["IsDone"]]
    if sub.empty:
        await update.message.reply_text("No expense data for this month."); return

    by_cat = sub.groupby("Category")["_base"].sum().sort_values(ascending=False)

    def to_display(base_val):
        r = rates.get(ccy, 1)
        return base_val if ccy == settings.DISPLAY_CURRENCY else (base_val / r if r else base_val)

    values  = [to_display(v) for v in by_cat.values]
    labels  = list(by_cat.index)
    colors  = [_bar_color(by_cat[cat], budgets.get(cat, 0)) for cat in labels]

    fig, ax = plt.subplots(figsize=(8, max(4, len(labels) * 0.5 + 1)))
    bars = ax.barh(labels[::-1], values[::-1], color=colors[::-1])
    ax.set_xlabel(ccy)
    ax.set_title(f"Expenses — {month} {year}", fontsize=13, fontweight="bold")
    ax.bar_label(bars, fmt=f"%.0f {ccy}", padding=4, fontsize=9)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    plt.tight_layout()

    buf = io.BytesIO()
    plt.savefig(buf, format="png", dpi=150)
    plt.close(fig)
    buf.seek(0)
    legend = "🟢 <80%  🟡 80-100%  🔴 >100%  ⬜ no budget"
    await update.message.reply_photo(photo=buf, caption=legend)


# ── Range report ─────────────────────────────────────────────────────────────

@auth
@log_call()
async def cmd_range(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Show an inline keyboard with preset date ranges for a filtered report."""
    if ctx.args and ctx.args[0].lower() == "help":
        await update.message.reply_text(
            "📅 */range* — Range report\n\n"
            "Pick a preset period \\(this month, last month, last 3 or 6 months, this year\\) or enter a custom date range\\.\n"
            "Shows income, expenses, savings, net, and top categories for the chosen period\\.",
            parse_mode="MarkdownV2",
        )
        return

    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("This month",    callback_data="range:this_month"),
            InlineKeyboardButton("Last month",    callback_data="range:last_month"),
        ],
        [
            InlineKeyboardButton("Last 3 months", callback_data="range:last_3_months"),
            InlineKeyboardButton("Last 6 months", callback_data="range:last_6_months"),
        ],
        [
            InlineKeyboardButton("This year",     callback_data="range:this_year"),
            InlineKeyboardButton("Custom…",       callback_data="range:custom"),
        ],
    ])
    await update.message.reply_text(
        "📅 *Range report* — choose a period:",
        parse_mode="Markdown",
        reply_markup=keyboard,
    )


@log_call()
def _build_range_report(
    df: pd.DataFrame,
    rates: dict,
    budgets: dict,
    ccy: str,
    start: date,
    end: date,
    label: str,
) -> str:
    """Build a report string for transactions in [start, end] (inclusive)."""
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    mask = (
        (df["Date"].dt.date >= start) &
        (df["Date"].dt.date <= end) &
        df["IsDone"]
    )
    sub = df[mask]

    income   = sub[sub["Type"] == "Income"]["_base"].sum()
    expense  = sub[sub["Type"] == "Expense"]["_base"].sum()
    savings  = sub[sub["Type"] == "Savings"]["_base"].sum()
    net      = income - expense - savings
    rate     = savings / income if income > 0 else 0
    by_cat   = sub[sub["Type"] == "Expense"].groupby("Category")["_base"].sum()

    lines = [
        f"📅 *Range Report — {label}* ({ccy})",
        f"_{start} → {end}_",
        "━━━━━━━━━━━━━━━━━━━",
        f"💰 Income:   `{format_base_as_currency(income, ccy, rates)}`",
        f"💸 Expenses: `{format_base_as_currency(expense, ccy, rates)}`",
        f"🏦 Savings:  `{format_base_as_currency(savings, ccy, rates)}`",
        f"📈 Net:      `{format_base_as_currency(net, ccy, rates)}`",
        f"📊 Savings rate: *{rate:.0%}* {savings_emoji(rate)}",
    ]

    if not by_cat.empty:
        lines.append("\n━━━ Top Categories ━━━")
        for cat, amt in by_cat.sort_values(ascending=False).head(8).items():
            pct = amt / expense * 100 if expense > 0 else 0
            budget_base = budgets.get(cat, 0)
            flag       = " 🔴" if budget_base and amt > budget_base else ""
            lines.append(f"• {cat}: `{format_base_as_currency(amt, ccy, rates)}` ({pct:.0f}%){flag}")

    return "\n".join(lines)


@log_call()
async def handle_range_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Handle inline button taps from the range report keyboard."""
    query = update.callback_query
    await query.answer()

    uid  = query.from_user.id
    ccy  = get_display_currency(uid)
    data = query.data  # e.g. "range:this_month"

    if data == "range:custom":
        # Store the chat id (not just True) so the free-text listener only
        # consumes messages from the chat where the custom range was requested.
        ctx.user_data["awaiting_range"] = query.message.chat.id
        await query.message.reply_text(
            "📅 Enter your custom range in the format:\n`YYYY-MM-DD to YYYY-MM-DD`",
            parse_mode="Markdown",
        )
        return

    today = now_utc().date()

    if data == "range:this_month":
        start = today.replace(day=1)
        end   = today
        label = "This month"
    elif data == "range:last_month":
        first_of_this = today.replace(day=1)
        last_of_prev  = first_of_this - timedelta(days=1)
        start = last_of_prev.replace(day=1)
        end   = last_of_prev
        label = "Last month"
    elif data == "range:last_3_months":
        end = today
        start = today.replace(day=1)
        for _ in range(3):
            start = (start - timedelta(days=1)).replace(day=1)
        label = "Last 3 months"
    elif data == "range:last_6_months":
        end = today
        start = today.replace(day=1)
        for _ in range(6):
            start = (start - timedelta(days=1)).replace(day=1)
        label = "Last 6 months"
    elif data == "range:this_year":
        start = today.replace(month=1, day=1)
        end   = today
        label = f"Year {today.year}"
    else:
        await query.message.reply_text("Unknown range option.")
        return

    try:
        df      = load_data()
        rates   = load_rates()
        budgets = load_budgets()
    except FileNotFoundError as e:
        await query.message.reply_text(f"❌ {e}")
        return

    text = _build_range_report(df, rates, budgets, ccy, start, end, label)
    await query.message.reply_text(text, parse_mode="Markdown")


@log_call()
async def handle_range_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Handle free-text custom date range input (YYYY-MM-DD to YYYY-MM-DD).

    Registered in a group that runs BEFORE the conversation handlers. To avoid
    crosstalk with /add, quick-add, etc. it only acts when:
      - the 'awaiting_range' flag is set for this user AND belongs to this chat;
      - the message actually looks like a date-range attempt.
    Unrelated messages pass through untouched (flag kept), and consumed
    messages raise ApplicationHandlerStop so no other handler double-replies.
    """
    flag = ctx.user_data.get("awaiting_range")
    if not flag:
        return  # not our message
    chat = update.effective_chat
    if flag is not True and chat is not None and flag != chat.id:
        return  # custom range was requested in a different chat

    import re
    text = update.message.text.strip()
    m = re.match(r"(\d{4}-\d{2}-\d{2})\s+to\s+(\d{4}-\d{2}-\d{2})", text)
    if not m:
        if re.search(r"\d{4}-\d{2}-\d{2}", text):
            # Looks like a range attempt with a format mistake — keep the flag
            # so the user can retry, and stop other handlers replying too.
            await update.message.reply_text(
                "❌ Could not parse range. Use format: `YYYY-MM-DD to YYYY-MM-DD`",
                parse_mode="Markdown",
            )
            raise ApplicationHandlerStop
        # Unrelated text (menu tap, quick-add, mid-/add answer): don't consume
        # it and don't pop the flag — let the normal handlers process it.
        return

    ctx.user_data.pop("awaiting_range", None)
    uid  = update.effective_user.id
    ccy  = get_display_currency(uid)

    try:
        start = date.fromisoformat(m.group(1))
        end   = date.fromisoformat(m.group(2))
    except ValueError as e:
        await update.message.reply_text(f"❌ Invalid date: {e}")
        raise ApplicationHandlerStop

    if start > end:
        await update.message.reply_text("❌ Start date must be before end date.")
        raise ApplicationHandlerStop

    try:
        df      = load_data()
        rates   = load_rates()
        budgets = load_budgets()
    except FileNotFoundError as e:
        await update.message.reply_text(f"❌ {e}")
        raise ApplicationHandlerStop

    label = f"{start} to {end}"
    report_text = _build_range_report(df, rates, budgets, ccy, start, end, label)
    await update.message.reply_text(report_text, parse_mode="Markdown")
    raise ApplicationHandlerStop


# ── Rates Refresh button helper ───────────────────────────────────────────────

@log_call()
async def cmd_rates_refresh(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Wrapper called by the '🔄 Rates Refresh' menu button."""
    ctx.args = ["refresh"]
    await cmd_rates(update, ctx)


@log_call()
async def check_budget_alert(update, category: str, ccy: str, rates: dict) -> None:
    if not category or category in ("Income", "Savings"):
        return
    try:
        df      = load_data()
        budgets = load_budgets_from_excel(get_excel_path_for_reading())
        budget  = budgets.get(category)
        if not budget:
            return
        cycle = _current_cycle_bounds()
        if cycle is not None:
            start, end, _label = cycle
            dates = pd.to_datetime(df["Date"], errors="coerce")
            spent_base = df[
                dates.notna() & (dates.dt.date >= start) & (dates.dt.date <= end) &
                (df["Category"] == category) & (df["Type"] == "Expense") & df["IsDone"]
            ]["_base"].sum()
        else:
            now  = now_utc()
            year, month = now.year, month_name(now.month)
            spent_base = df[
                (df["Year"] == year) & (df["Month"] == month) &
                (df["Category"] == category) & (df["Type"] == "Expense") & df["IsDone"]
            ]["_base"].sum()
        pct = spent_base / budget if budget > 0 else 0
        if pct >= 1.0:
            await update.message.reply_text(
                f"🚨 *{category}* budget exceeded!\n"
                f"{format_base_as_currency(spent_base, ccy, rates)} spent of "
                f"{format_base_as_currency(budget, ccy, rates)} ({pct*100:.0f}%)",
                parse_mode="Markdown"
            )
        elif pct >= 0.8:
            await update.message.reply_text(
                f"⚠️ *{category}* at {pct*100:.0f}% of budget — "
                f"{format_base_as_currency(budget - spent_base, ccy, rates)} remaining",
                parse_mode="Markdown"
            )
    except Exception as e:
        log.warning("Budget alert failed: %s", e)
