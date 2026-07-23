"""/summary /week /budget /top /savings /report /rates /chart + budget alert."""

import calendar
import io
import os
from datetime import date, timedelta

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

import settings
from config import auth, get_display_currency, SAVINGS_TARGET, log
from log_decorators import log_call
from data import (
    load_data, load_rates, load_budgets, load_reference_data,
    now_utc, current_year_and_month, month_name, get_rate,
)
from excel_ops import async_update_currency_rates
from file_storage import get_excel_path_for_reading, load_budgets_from_excel
from formatters import (
    format_amount, format_pln_as_currency, budget_progress_bar, savings_emoji,
)


def _current_cycle_bounds() -> tuple[date, date, str] | None:
    """(start, today, label) for the current cycle, or None → calendar fallback."""
    if not settings.BUDGET_CYCLE:
        return None
    from cycles import current_cycle_start
    today = now_utc().date()
    current = current_cycle_start(today)
    if current is None:
        return None
    start, label = current
    return start, today, label


async def _send_cycle_summary(update, ccy: str, df, rates,
                              start: date, end: date, label: str) -> None:
    from cycles import cycle_totals
    totals  = cycle_totals(df, start, end)
    income  = totals["income"]
    expense = totals["expense"]
    savings = totals["savings"]
    net     = income - expense - savings
    rate    = savings / income if income > 0 else 0
    days_elapsed = (end - start).days + 1
    daily_avg    = expense / days_elapsed if days_elapsed > 0 else 0
    unaccounted  = totals["unaccounted"]
    unacc_note   = " (over-reported)" if unaccounted < 0 else ""

    net_line = (f"✅ *Net:* {format_pln_as_currency(net, ccy, rates)}" if net >= 0
                else f"⚠️ *Net:* {format_pln_as_currency(net, ccy, rates)}")

    await update.message.reply_text(
        f"📊 *Cycle {label} — Summary* ({ccy})\n"
        f"_{start.isoformat()} → today, day {days_elapsed}_\n\n"
        f"💰 Income:   `{format_pln_as_currency(income, ccy, rates)}`\n"
        f"💸 Expenses: `{format_pln_as_currency(expense, ccy, rates)}`\n"
        f"🏦 Savings:  `{format_pln_as_currency(savings, ccy, rates)}`\n"
        f"{net_line}\n\n"
        f"{savings_emoji(rate)} Savings rate: *{rate:.0%}*\n"
        f"💼 Salary received: `{format_pln_as_currency(totals['salary'], ccy, rates)}`\n"
        f"❓ Unaccounted: `{format_pln_as_currency(unaccounted, ccy, rates)}`{unacc_note}\n"
        f"📉 Daily average spend: `{format_pln_as_currency(daily_avg, ccy, rates)}`",
        parse_mode="Markdown",
    )


@auth
@log_call()
async def cmd_summary(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
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
        await _send_cycle_summary(update, ccy, df, rates, *cycle)
        return

    sub     = df[(df["Year"] == year) & (df["Month"] == month) & df["IsDone"]]
    income  = sub[sub["Type"] == "Income"]["_pln"].sum()
    expense = sub[sub["Type"] == "Expense"]["_pln"].sum()
    savings = sub[sub["Type"] == "Savings"]["_pln"].sum()
    net     = income - expense - savings
    rate    = savings / income if income > 0 else 0

    now           = now_utc()
    days_elapsed  = now.day
    days_in_month = calendar.monthrange(now.year, now.month)[1]
    projected     = expense / days_elapsed * days_in_month if days_elapsed > 0 else 0

    net_line = (f"✅ *Net:* {format_pln_as_currency(net, ccy, rates)}" if net >= 0
                else f"⚠️ *Net:* {format_pln_as_currency(net, ccy, rates)}")

    summary_text = (
        f"📊 *{month} {year} — Summary* ({ccy})\n\n"
        f"💰 Income:   `{format_pln_as_currency(income, ccy, rates)}`\n"
        f"💸 Expenses: `{format_pln_as_currency(expense, ccy, rates)}`\n"
        f"🏦 Savings:  `{format_pln_as_currency(savings, ccy, rates)}`\n"
        f"{net_line}\n\n"
        f"{savings_emoji(rate)} Savings rate: *{rate:.0%}*\n"
        f"📈 Projected month-end spend: `{format_pln_as_currency(projected, ccy, rates)}`"
    )
    await update.message.reply_text(summary_text, parse_mode="Markdown")


@auth
@log_call()
async def cmd_week(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
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

    by_cat = sub.groupby("Category")["_pln"].sum().sort_values(ascending=False)
    total  = by_cat.sum()

    lines = [f"📅 *Last 7 days — {format_pln_as_currency(total, ccy, rates)} total*\n"]
    for cat, amt in by_cat.items():
        pct = amt / total * 100 if total > 0 else 0
        lines.append(f"• {cat}: `{format_pln_as_currency(amt, ccy, rates)}` ({pct:.0f}%)")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


@auth
@log_call()
async def cmd_budget(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
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
        title = f"📋 *Budget vs Actual — Cycle {label}* ({ccy})\n_{start.isoformat()} → today_\n"
    else:
        sub = df[(df["Year"] == year) & (df["Month"] == month)
                 & (df["Type"] == "Expense") & df["IsDone"]]
        title = f"📋 *Budget vs Actual — {month} {year}* ({ccy})\n"
    by_cat = sub.groupby("Category")["_pln"].sum()
    rate   = get_rate(ccy, rates)

    lines        = [title]
    total_budget = 0
    total_actual = 0

    for cat in load_reference_data()["categories"]:
        budget_pln = budgets.get(cat, 0)
        actual_pln = by_cat.get(cat, 0)
        if budget_pln == 0 and actual_pln == 0:
            continue
        budget = budget_pln / rate
        actual = actual_pln / rate
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
    year, month = current_year_and_month()
    uid = update.effective_user.id
    ccy = get_display_currency(uid)
    try:
        df    = load_data()
        rates = load_rates()
    except FileNotFoundError as e:
        await update.message.reply_text(f"❌ {e}"); return

    sub = (df[(df["Year"] == year) & (df["Month"] == month)
              & (df["Type"] == "Expense") & df["IsDone"]]
           .sort_values("_pln", ascending=False).head(5))

    if sub.empty:
        await update.message.reply_text("No expenses found this month."); return

    lines = [f"🏆 *Top 5 expenses — {month} {year}* ({ccy})\n"]
    for i, (_, row) in enumerate(sub.iterrows(), 1):
        desc     = row.get("Description", "") or ""
        cat      = row.get("Category", "?")
        orig_ccy = str(row.get("Currency", "PLN"))
        orig_val = row.get("Value", row["_pln"])
        extra    = f" ({orig_val:,.0f} {orig_ccy})" if orig_ccy != "PLN" and orig_ccy != ccy else ""
        lines.append(
            f"{i}. `{format_pln_as_currency(row['_pln'], ccy, rates)}`{extra} — "
            f"{desc or cat} _{cat}_"
        )

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


@auth
@log_call()
async def cmd_savings(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        df = load_data()
    except FileNotFoundError as e:
        await update.message.reply_text(f"❌ {e}"); return

    now  = now_utc()
    month_labels = []
    rate_values  = []
    for delta in range(5, -1, -1):
        m  = (now.month - delta - 1) % 12
        y  = now.year + ((now.month - delta - 1) // 12)
        ms = month_name(m + 1)
        sub    = df[(df["Year"] == y) & (df["Month"] == ms) & df["IsDone"]]
        income  = sub[sub["Type"] == "Income"]["_pln"].sum()
        expense = sub[sub["Type"] == "Expense"]["_pln"].sum()
        savings_amt = sub[sub["Type"] == "Savings"]["_pln"].sum()
        rate    = savings_amt / income * 100 if income > 0 else 0
        month_labels.append(ms[:3])   # abbreviated month name
        rate_values.append(round(rate, 1))

    buf = _build_savings_chart(month_labels, rate_values)

    current_rate = rate_values[-1]
    prior_rate   = rate_values[-2] if len(rate_values) >= 2 else current_rate
    if current_rate > prior_rate:
        arrow = "↑"
    elif current_rate < prior_rate:
        arrow = "↓"
    else:
        arrow = "→"
    caption = (
        f"Savings rate this month: {current_rate:.1f}% {arrow}\n"
        f"vs prior month: {prior_rate:.1f}%"
    )
    await update.message.reply_photo(photo=buf, caption=caption)


@auth
@log_call()
async def cmd_report(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    year, month = current_year_and_month()
    uid = update.effective_user.id
    ccy = get_display_currency(uid)
    try:
        df      = load_data()
        rates   = load_rates()
        budgets = load_budgets()
    except FileNotFoundError as e:
        await update.message.reply_text(f"❌ {e}"); return

    sub      = df[(df["Year"] == year) & (df["Month"] == month) & df["IsDone"]]
    income   = sub[sub["Type"] == "Income"]["_pln"].sum()
    expense  = sub[sub["Type"] == "Expense"]["_pln"].sum()
    savings  = sub[sub["Type"] == "Savings"]["_pln"].sum()
    net      = income - expense - savings
    rate     = savings / income if income > 0 else 0
    by_cat   = sub[sub["Type"] == "Expense"].groupby("Category")["_pln"].sum()
    by_person = sub[sub["Type"] == "Expense"].groupby("Person")["_pln"].sum()
    recur    = sub[(sub["Type"] == "Expense") & sub["IsRecurring"].fillna(False).astype(bool)]["_pln"].sum()
    discret  = expense - recur

    now             = now_utc()
    prev_month_num  = now.month - 1 if now.month > 1 else 12
    prev_year       = year if now.month > 1 else year - 1
    prev_month_name = month_name(prev_month_num)
    prev_sub        = df[(df["Year"] == prev_year) & (df["Month"] == prev_month_name) & df["IsDone"]]
    prev_by_cat     = prev_sub[prev_sub["Type"] == "Expense"].groupby("Category")["_pln"].sum()

    by_input_ccy = sub[sub["Type"] == "Expense"].groupby("Currency")["Value"].sum()
    multi_ccy    = len(by_input_ccy) > 1

    lines = [
        f"📑 *Monthly Report — {month} {year}* ({ccy})",
        "━━━━━━━━━━━━━━━━━━━",
        f"💰 Income:      `{format_pln_as_currency(income, ccy, rates)}`",
        f"💸 Expenses:    `{format_pln_as_currency(expense, ccy, rates)}`",
        f"   ↳ Fixed:     `{format_pln_as_currency(recur, ccy, rates)}`",
        f"   ↳ Variable:  `{format_pln_as_currency(discret, ccy, rates)}`",
        f"🏦 Savings:     `{format_pln_as_currency(savings, ccy, rates)}`",
        f"📈 Net:         `{format_pln_as_currency(net, ccy, rates)}`",
        f"📊 Savings rate: *{rate:.0%}* {savings_emoji(rate)}",
        "",
        f"━━━ By Category (vs {prev_month_name}) ━━━",
    ]
    for cat, amt in by_cat.sort_values(ascending=False).items():
        budget_pln = budgets.get(cat, 0)
        pct        = amt / expense * 100 if expense > 0 else 0
        flag       = " 🔴" if budget_pln and amt > budget_pln else ""
        prev_amt   = prev_by_cat.get(cat, 0)
        if prev_amt > 0:
            delta     = amt - prev_amt
            delta_fmt = format_pln_as_currency(abs(delta), ccy, rates)
            mom       = f" ({'+' if delta >= 0 else '-'}{delta_fmt})"
        else:
            mom = ""
        lines.append(f"• {cat}: `{format_pln_as_currency(amt, ccy, rates)}` ({pct:.0f}%){flag}{mom}")

    if multi_ccy:
        lines += ["", "━━━ Original currencies ━━━"]
        for input_ccy, total in by_input_ccy.items():
            lines.append(f"• {input_ccy}: {total:,.0f}")

    if not by_person.empty:
        lines += ["", "━━━ By Person ━━━"]
        for person, amt in by_person.sort_values(ascending=False).items():
            if person:
                lines.append(f"• {person}: `{format_pln_as_currency(amt, ccy, rates)}`")

    report_text = "\n".join(lines)
    MAX = 4000
    if len(report_text) <= MAX:
        await update.message.reply_text(report_text, parse_mode="Markdown")
    else:
        chunks = []
        current = ""
        for line in report_text.split("\n"):
            if len(current) + len(line) + 1 > MAX:
                chunks.append(current)
                current = line
            else:
                current += ("\n" if current else "") + line
        if current:
            chunks.append(current)
        for chunk in chunks:
            await update.message.reply_text(chunk, parse_mode="Markdown")


@auth
@log_call()
async def cmd_rates(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    rates = load_rates()

    if ctx.args and ctx.args[0].lower() == "refresh":
        await update.message.reply_text("🔄 Fetching live rates from frankfurter.dev…")
        try:
            import httpx
            primary_url  = "https://api.frankfurter.dev/v1/latest?from=PLN"
            fallback_url = "https://api.frankfurter.app/latest?from=PLN"
            async with httpx.AsyncClient(follow_redirects=True, timeout=10.0) as client:
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
            live["PLN"] = 1.0

            lines   = [f"📡 *Live rates vs Excel* (PLN per 1 unit)\n"
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
        lines = ["💱 *Current exchange rates* (PLN per 1 unit)\n"]
        for cur_ccy, r in sorted(rates.items()):
            lines.append(f"`{cur_ccy}`: {r:.4f} PLN")
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


def _build_savings_chart(months: list, rates: list) -> io.BytesIO:
    """Build a 6-month savings rate line chart and return a PNG BytesIO buffer."""
    target = int(SAVINGS_TARGET * 100)

    fig, ax = plt.subplots(figsize=(8, 4))
    ax.plot(months, rates, "bo-", linewidth=2, markersize=7, label="Savings rate %")
    ax.axhline(target, color="grey", linestyle="--", linewidth=1.5, label=f"Target {target}%")
    ax.set_ylim(0, max(100, max(rates) + 10) if rates else 100)
    ax.set_ylabel("Savings rate (%)")
    ax.set_title("Savings Rate — Last 6 Months", fontsize=13, fontweight="bold")
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

    by_cat = sub.groupby("Category")["_pln"].sum().sort_values(ascending=False)

    def to_display(pln_val):
        r = rates.get(ccy, 1)
        return pln_val if ccy == "PLN" else (pln_val / r if r else pln_val)

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

    income   = sub[sub["Type"] == "Income"]["_pln"].sum()
    expense  = sub[sub["Type"] == "Expense"]["_pln"].sum()
    savings  = sub[sub["Type"] == "Savings"]["_pln"].sum()
    net      = income - expense - savings
    rate     = savings / income if income > 0 else 0
    by_cat   = sub[sub["Type"] == "Expense"].groupby("Category")["_pln"].sum()

    lines = [
        f"📅 *Range Report — {label}* ({ccy})",
        f"_{start} → {end}_",
        "━━━━━━━━━━━━━━━━━━━",
        f"💰 Income:   `{format_pln_as_currency(income, ccy, rates)}`",
        f"💸 Expenses: `{format_pln_as_currency(expense, ccy, rates)}`",
        f"🏦 Savings:  `{format_pln_as_currency(savings, ccy, rates)}`",
        f"📈 Net:      `{format_pln_as_currency(net, ccy, rates)}`",
        f"📊 Savings rate: *{rate:.0%}* {savings_emoji(rate)}",
    ]

    if not by_cat.empty:
        lines.append("\n━━━ Top Categories ━━━")
        for cat, amt in by_cat.sort_values(ascending=False).head(8).items():
            pct = amt / expense * 100 if expense > 0 else 0
            budget_pln = budgets.get(cat, 0)
            flag       = " 🔴" if budget_pln and amt > budget_pln else ""
            lines.append(f"• {cat}: `{format_pln_as_currency(amt, ccy, rates)}` ({pct:.0f}%){flag}")

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
        ctx.user_data["awaiting_range"] = True
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
    """Handle free-text custom date range input (YYYY-MM-DD to YYYY-MM-DD)."""
    if not ctx.user_data.get("awaiting_range"):
        return  # not our message

    ctx.user_data.pop("awaiting_range", None)
    uid  = update.effective_user.id
    ccy  = get_display_currency(uid)
    text = update.message.text.strip()

    import re
    m = re.match(r"(\d{4}-\d{2}-\d{2})\s+to\s+(\d{4}-\d{2}-\d{2})", text)
    if not m:
        await update.message.reply_text(
            "❌ Could not parse range. Use format: `YYYY-MM-DD to YYYY-MM-DD`",
            parse_mode="Markdown",
        )
        return

    try:
        start = date.fromisoformat(m.group(1))
        end   = date.fromisoformat(m.group(2))
    except ValueError as e:
        await update.message.reply_text(f"❌ Invalid date: {e}")
        return

    if start > end:
        await update.message.reply_text("❌ Start date must be before end date.")
        return

    try:
        df      = load_data()
        rates   = load_rates()
        budgets = load_budgets()
    except FileNotFoundError as e:
        await update.message.reply_text(f"❌ {e}")
        return

    label = f"{start} to {end}"
    report_text = _build_range_report(df, rates, budgets, ccy, start, end, label)
    await update.message.reply_text(report_text, parse_mode="Markdown")


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
        now  = now_utc()
        year, month = now.year, month_name(now.month)
        spent_pln = df[
            (df["Year"] == year) & (df["Month"] == month) &
            (df["Category"] == category) & (df["Type"] == "Expense") & df["IsDone"]
        ]["_pln"].sum()
        pct = spent_pln / budget if budget > 0 else 0
        if pct >= 1.0:
            await update.message.reply_text(
                f"🚨 *{category}* budget exceeded!\n"
                f"{format_pln_as_currency(spent_pln, ccy, rates)} spent of "
                f"{format_pln_as_currency(budget, ccy, rates)} ({pct*100:.0f}%)",
                parse_mode="Markdown"
            )
        elif pct >= 0.8:
            await update.message.reply_text(
                f"⚠️ *{category}* at {pct*100:.0f}% of budget — "
                f"{format_pln_as_currency(budget - spent_pln, ccy, rates)} remaining",
                parse_mode="Markdown"
            )
    except Exception as e:
        log.warning("Budget alert failed: %s", e)
