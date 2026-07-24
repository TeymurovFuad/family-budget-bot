"""/cycle command and the salary-triggered new-cycle prompt."""

from datetime import date, datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

import settings
from config import TIMEZONE, auth_write, log
from log_decorators import log_call
from cycles import (
    async_record_cycle_start, current_cycle_start, cycle_label,
    should_prompt_new_cycle,
)

_CYCLE_USAGE = (
    "Usage:\n"
    "`/cycle` — show the current budget cycle\n"
    "`/cycle started` — start a new cycle from today\n"
    "`/cycle started YYYY-MM-DD` — start a new cycle from that date"
)


def _day_month(d: date) -> str:
    return f"{d.day} {d.strftime('%b')}"


@auth_write
@log_call()
async def cmd_cycle(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not settings.BUDGET_CYCLE:
        await update.message.reply_text(
            "Budget cycles are disabled. Set `BUDGET_CYCLE=1` in .env and restart to enable them.",
            parse_mode="Markdown",
        )
        return

    today = datetime.now(TIMEZONE).date()
    args = ctx.args or []

    if not args:
        current = current_cycle_start(today)
        if current is None:
            await update.message.reply_text(
                "No budget cycle recorded yet. Use `/cycle started` (or "
                "`/cycle started YYYY-MM-DD`) to record the first one.",
                parse_mode="Markdown",
            )
        else:
            start, label = current
            await update.message.reply_text(
                f"💰 Current cycle: *{label}* — started {start.isoformat()}, "
                f"day {(today - start).days + 1}.",
                parse_mode="Markdown",
            )
        return

    if args[0].lower() != "started":
        await update.message.reply_text(_CYCLE_USAGE, parse_mode="Markdown")
        return

    if len(args) >= 2:
        try:
            start = date.fromisoformat(args[1])
        except ValueError:
            await update.message.reply_text(
                "❌ Could not parse the date. Use `/cycle started YYYY-MM-DD`.",
                parse_mode="Markdown",
            )
            return
        if start > today:
            await update.message.reply_text("❌ A cycle cannot start in the future.")
            return
    else:
        start = today

    recorded = await async_record_cycle_start(start)
    if recorded:
        await update.message.reply_text(
            f"✅ New budget cycle *{cycle_label(start)}* started from {start.isoformat()}.",
            parse_mode="Markdown",
        )
    else:
        await update.message.reply_text(
            f"A cycle boundary on {start.isoformat()} is already recorded — nothing changed."
        )


async def maybe_prompt_cycle_start(update: Update, transaction) -> None:
    """
    Called after a transaction is saved. If it is a Salary income, the flag is
    on, and the current cycle is old enough, propose a new cycle boundary —
    only the user's confirmation records it; the bot never guesses.
    """
    if not settings.BUDGET_CYCLE:
        return
    if transaction.transaction_type != "Income":
        return
    if (transaction.category or "").strip().lower() != settings.SALARY_CATEGORY.strip().lower():
        return
    today = datetime.now(TIMEZONE).date()
    if not should_prompt_new_cycle(today):
        return
    proposed = transaction.date or today
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("Yes",            callback_data=f"cycle:yes:{proposed.isoformat()}"),
        InlineKeyboardButton("No",             callback_data="cycle:no"),
        InlineKeyboardButton("Different date", callback_data="cycle:diff"),
    ]])
    await update.message.reply_text(
        f"💰 Salary received. Start the new budget cycle from {_day_month(proposed)}? "
        "(yes / no / different date)",
        reply_markup=keyboard,
    )


@auth_write
@log_call()
async def handle_cycle_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.split(":")
    action = parts[1] if len(parts) > 1 else ""

    if action == "yes" and len(parts) > 2:
        try:
            start = date.fromisoformat(parts[2])
        except ValueError:
            await query.message.reply_text("❌ Could not read the proposed date.")
            return
        recorded = await async_record_cycle_start(start)
        if recorded:
            await query.message.reply_text(
                f"✅ New budget cycle *{cycle_label(start)}* started from {start.isoformat()}.",
                parse_mode="Markdown",
            )
        else:
            await query.message.reply_text(
                f"A cycle boundary on {start.isoformat()} is already recorded — nothing changed."
            )
    elif action == "no":
        await query.message.reply_text("👍 Okay — the current cycle continues.")
    elif action == "diff":
        await query.message.reply_text(
            "📅 Send `/cycle started YYYY-MM-DD` with the date the new cycle should start from.",
            parse_mode="Markdown",
        )
    else:
        log.warning("Unknown cycle callback: %s", query.data)
