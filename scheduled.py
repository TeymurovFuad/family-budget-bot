"""APScheduler job functions — weekly report, monthly summary, daily reminder, weekly nudge."""

import calendar
from datetime import timedelta

import pandas as pd
from telegram.ext import Application

from config import ALLOWED_USERS, get_display_currency, log
from data import load_data, load_rates, load_budgets, now_utc, current_year_and_month, month_name
from formatters import format_base_as_currency, savings_emoji


async def send_weekly_report(app: Application):
    log.info("Sending scheduled weekly report")
    try:
        df      = load_data()
        rates   = load_rates()
        budgets = load_budgets()
    except Exception:
        log.exception("Failed to load data for weekly report"); return

    year, month = current_year_and_month()
    now         = now_utc()

    for uid in ALLOWED_USERS:
        ccy = get_display_currency(uid)
        try:
            sub        = df[(df["Year"] == year) & (df["Month"] == month) & df["IsDone"]]
            expense    = sub[sub["Type"] == "Expense"]["_base"].sum()
            income     = sub[sub["Type"] == "Income"]["_base"].sum()
            savings    = sub[sub["Type"] == "Savings"]["_base"].sum()
            by_cat     = sub[sub["Type"] == "Expense"].groupby("Category")["_base"].sum()
            daily_rate = expense / now.day if now.day > 0 else 0
            projected  = daily_rate * calendar.monthrange(now.year, now.month)[1]

            lines = [
                f"📅 *Weekly check-in — {month} {year}* ({ccy})\n",
                f"💸 Spent so far:  `{format_base_as_currency(expense, ccy, rates)}`",
                f"💰 Income so far: `{format_base_as_currency(income, ccy, rates)}`",
                f"🏦 Saved:         `{format_base_as_currency(savings, ccy, rates)}`",
                f"📈 Projected monthly spend: `{format_base_as_currency(projected, ccy, rates)}`\n",
                "Top categories:",
            ]
            for cat, amt in by_cat.sort_values(ascending=False).head(4).items():
                flag = " 🔴" if budgets.get(cat, 0) and amt > budgets[cat] else ""
                lines.append(f"• {cat}: `{format_base_as_currency(amt, ccy, rates)}`{flag}")

            await app.bot.send_message(chat_id=uid, text="\n".join(lines), parse_mode="Markdown")
        except Exception:
            log.exception("Failed sending weekly report to %s", uid)


async def send_monthly_summary(app: Application):
    log.info("Sending scheduled monthly summary")
    try:
        df    = load_data()
        rates = load_rates()
    except Exception:
        log.exception("Failed to load data for monthly summary"); return

    now   = now_utc()
    prev  = now.replace(day=1) - timedelta(days=1)
    year  = prev.year
    month = month_name(prev.month)

    for uid in ALLOWED_USERS:
        ccy = get_display_currency(uid)
        try:
            sub     = df[(df["Year"] == year) & (df["Month"] == month) & df["IsDone"]]
            income  = sub[sub["Type"] == "Income"]["_base"].sum()
            expense = sub[sub["Type"] == "Expense"]["_base"].sum()
            savings = sub[sub["Type"] == "Savings"]["_base"].sum()
            net     = income - expense - savings
            rate    = savings / income if income > 0 else 0
            await app.bot.send_message(
                chat_id=uid,
                text=(
                    f"🗓 *{month} {year} — Final Report* ({ccy})\n\n"
                    f"💰 Income:   `{format_base_as_currency(income, ccy, rates)}`\n"
                    f"💸 Expenses: `{format_base_as_currency(expense, ccy, rates)}`\n"
                    f"🏦 Savings:  `{format_base_as_currency(savings, ccy, rates)}`\n"
                    f"📈 Net:      `{format_base_as_currency(net, ccy, rates)}`\n\n"
                    f"{savings_emoji(rate)} Savings rate: *{rate:.0%}*\n\n"
                    "Use /report for the full breakdown."
                ),
                parse_mode="Markdown",
            )
        except Exception:
            log.exception("Failed sending monthly summary to %s", uid)


async def send_daily_reminder(app):
    try:
        df = load_data()
    except Exception:
        return
    today = now_utc().date()
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    if not df[df["Date"].dt.date == today].empty:
        return
    for uid in ALLOWED_USERS:
        try:
            await app.bot.send_message(
                uid, "📝 Reminder: you haven't logged any transactions today. Use /add to log an expense."
            )
        except Exception:
            log.exception("daily reminder failed for user %s", uid)


async def send_weekly_nudge(app):
    try:
        df = load_data()
    except Exception:
        return
    now        = now_utc()
    week_start = (now - timedelta(days=now.weekday())).date()
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    n = len(df[df["Date"].dt.date >= week_start])
    if n >= 3:
        return
    for uid in ALLOWED_USERS:
        try:
            await app.bot.send_message(
                uid,
                f"📋 Weekly check-in: only {n} transaction(s) logged this week. "
                "Don't forget to catch up with /add before the Sunday report!"
            )
        except Exception:
            log.exception("weekly nudge failed for user %s", uid)
