"""/cycle command and the salary-triggered new-cycle prompt."""

import asyncio
import re
from datetime import date, datetime

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

import settings
from config import TIMEZONE, auth_write, log
from data import load_data
from log_decorators import log_call
from cycles import (
    async_record_cycle_start, current_cycle_start, cycle_label,
    detect_cycle_candidates, load_cycles, record_cycle_starts_batch,
    should_prompt_new_cycle,
)

_CYCLE_USAGE = (
    "Usage:\n"
    "`/cycle` — show the current budget cycle\n"
    "`/cycle started` — start a new cycle from today\n"
    "`/cycle started YYYY-MM-DD` — start a new cycle from that date\n"
    "`/cycle detect` — scan transaction history and backfill cycle boundaries"
)


def _esc(text: str) -> str:
    """Escape a plain-text string for MarkdownV2."""
    return re.sub(r"([_*\[\]()~`>#+\-=|{}.!\\])", r"\\\1", str(text))


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

    if args[0].lower() == "detect":
        await _cmd_cycle_detect(update, ctx)
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


async def _cmd_cycle_detect(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /cycle detect — scan history and backfill cycle boundaries."""
    if not settings.BUDGET_CYCLE:
        await update.message.reply_text(
            "Budget cycles are disabled\\. Set `BUDGET_CYCLE=1` in \\.env and restart\\.",
            parse_mode="MarkdownV2",
        )
        return

    await update.message.reply_text("🔍 Scanning transaction history\\.\\.\\.", parse_mode="MarkdownV2")

    loop = asyncio.get_running_loop()
    df, cycles = await loop.run_in_executor(
        None, lambda: (load_data(), load_cycles())
    )
    candidates = await loop.run_in_executor(
        None, lambda: detect_cycle_candidates(df, cycles)
    )

    if not candidates:
        await update.message.reply_text(
            "✅ Nothing to backfill — all months are already recorded\\.",
            parse_mode="MarkdownV2",
        )
        return

    unambiguous = [c for c in candidates if c["unambiguous"]]
    ambiguous = [c for c in candidates if not c["unambiguous"]]

    if unambiguous:
        ctx.user_data["detect_unambiguous"] = [
            {
                "date_str": c["candidates"][0]["date"].isoformat(),
                "month_label": c["month_label"],
                "amount": c["candidates"][0]["amount"],
            }
            for c in unambiguous
        ]
        lines = [
            f"• {_esc(u['month_label'])} — "
            f"{_esc(u['candidates'][0]['date'].strftime('%d %b'))}, "
            f"{u['candidates'][0]['amount']:,.0f} PLN"
            for u in unambiguous
        ]
        note = "\n\n_No months need manual review\\._" if not ambiguous else ""
        text = "*✅ Auto\\-detected salary arrivals*\n\n" + "\n".join(lines) + note
        keyboard = InlineKeyboardMarkup(
            [[InlineKeyboardButton("✅ Confirm all", callback_data="detect:confirm_all")]]
        )
        await update.message.reply_text(text, parse_mode="MarkdownV2", reply_markup=keyboard)

    ctx.user_data["detect_queue"] = ambiguous

    if ambiguous:
        await _send_detect_prompt(update, ctx)


async def _send_detect_prompt(update_or_msg, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Send an inline-button prompt for the first ambiguous month in the queue."""
    queue = ctx.user_data.get("detect_queue", [])
    if not queue:
        return
    entry = queue[0]

    month_label = _esc(entry["month_label"])
    window_start = _esc(str(entry["window_start"]))
    window_end = _esc(str(entry["window_end"]))
    text = (
        f"📅 *{month_label}* — Which income was your salary?\n"
        f"Payday window: {window_start} → {window_end}"
    )

    buttons: list[list[InlineKeyboardButton]] = []
    for cand in entry["candidates"]:
        d = cand["date"]
        label = f"{d.isoformat()} — {cand['amount']:,.0f} PLN"
        buttons.append([InlineKeyboardButton(label, callback_data=f"detect:pick:{d.isoformat()}")])
    buttons.append(
        [InlineKeyboardButton("No cycle this month", callback_data=f"detect:none:{entry['month_key']}")]
    )
    buttons.append(
        [InlineKeyboardButton("Custom date", callback_data=f"detect:custom:{entry['month_key']}")]
    )
    keyboard = InlineKeyboardMarkup(buttons)

    if isinstance(update_or_msg, Update):
        await update_or_msg.message.reply_text(text, parse_mode="MarkdownV2", reply_markup=keyboard)
    else:
        await update_or_msg.reply_text(text, parse_mode="MarkdownV2", reply_markup=keyboard)


async def _advance_detect_queue(message, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """After answering a month, send the next prompt or declare completion."""
    if ctx.user_data.get("detect_queue"):
        await _send_detect_prompt(message, ctx)
    else:
        ctx.user_data.pop("detect_queue", None)
        await message.reply_text(
            "✅ Backfill complete\\! All boundaries have been reviewed\\.",
            parse_mode="MarkdownV2",
        )


@auth_write
@log_call()
async def handle_detect_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Inline-button callbacks for /cycle detect flow (pattern ^detect:)."""
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "detect:confirm_all":
        unambiguous = ctx.user_data.get("detect_unambiguous") or []
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None,
            lambda: record_cycle_starts_batch(
                [date.fromisoformat(u["date_str"]) for u in unambiguous]
            ),
        )
        ctx.user_data.pop("detect_unambiguous", None)
        n = len(unambiguous)
        await query.edit_message_text(
            _esc(f"✅ Confirmed {n} {'boundary' if n == 1 else 'boundaries'}."),
            parse_mode="MarkdownV2",
        )
        await _advance_detect_queue(query.message, ctx)
        return

    if data.startswith("detect:pick:"):
        date_str = data[len("detect:pick:"):]
        start = date.fromisoformat(date_str)
        await async_record_cycle_start(start)
        if ctx.user_data.get("detect_queue"):
            ctx.user_data["detect_queue"].pop(0)
        await query.edit_message_text(
            f"✅ Recorded {_esc(cycle_label(start))} from {_esc(date_str)}\\.",
            parse_mode="MarkdownV2",
        )
        await _advance_detect_queue(query.message, ctx)
        return

    if data.startswith("detect:none:"):
        if ctx.user_data.get("detect_queue"):
            ctx.user_data["detect_queue"].pop(0)
        await query.edit_message_text("👍 No cycle for this month\\.", parse_mode="MarkdownV2")
        await _advance_detect_queue(query.message, ctx)
        return

    if data.startswith("detect:custom:"):
        month_key = data[len("detect:custom:"):]
        ctx.user_data["awaiting_detect_date"] = month_key
        await query.edit_message_text(
            "📅 Send the date as `YYYY\\-MM\\-DD`:", parse_mode="MarkdownV2"
        )
        return

    log.warning("Unknown detect callback: %s", data)


async def handle_detect_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle a free-text date reply for /cycle detect custom date flow."""
    month_key = ctx.user_data.get("awaiting_detect_date")
    if not month_key:
        return

    text = update.message.text.strip()
    try:
        start = date.fromisoformat(text)
    except ValueError:
        await update.message.reply_text("❌ Use `YYYY\\-MM\\-DD`\\.", parse_mode="MarkdownV2")
        return

    if start > date.today():
        await update.message.reply_text("❌ Cannot be in the future\\.", parse_mode="MarkdownV2")
        return

    await async_record_cycle_start(start)
    if ctx.user_data.get("detect_queue"):
        ctx.user_data["detect_queue"].pop(0)
    ctx.user_data.pop("awaiting_detect_date", None)
    await update.message.reply_text(
        f"✅ Recorded {_esc(cycle_label(start))} from {_esc(text)}\\.",
        parse_mode="MarkdownV2",
    )
    await _advance_detect_queue(update.message, ctx)


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
