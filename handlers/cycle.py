"""/cycle command and the salary-triggered new-cycle prompt."""

import asyncio
import re
from datetime import date, datetime, timedelta

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

import settings
from config import TIMEZONE, auth_write, log
from data import load_data
from log_decorators import log_call
from cycles import (
    async_record_cycle_start, async_remove_cycle_start, current_cycle_start,
    cycle_label, cycle_detect_keywords, detect_cycle_candidates, load_cycles,
    record_cycle_starts_batch, should_prompt_new_cycle,
)

_CYCLE_USAGE = (
    "💰 *Budget cycles* — track spending per salary period instead of "
    "calendar months. A cycle starts when your salary arrives and ends "
    "when the next one does.\n\n"
    "*Commands:*\n"
    "`/cycle` — show the current cycle: label, start date, day count\n"
    "`/cycle started` — record a new cycle starting today\n"
    "`/cycle started YYYY-MM-DD` — record a new cycle from that date "
    "(e.g. `/cycle started 2026-07-01`)\n"
    "`/cycle detect` — scan the whole transaction history for salary "
    "arrivals and backfill missing cycle boundaries; you review and "
    "confirm every date before anything is written\n"
    "`/cycle detect <word> ...` — add extra search words for the scan, "
    "e.g. `/cycle detect wynagrodzenie premia` if your bank titles the "
    "salary transfer in another language\n"
    "`/cycle list` — show every recorded cycle boundary\n"
    "`/cycle remove YYYY-MM-DD` — delete a wrongly recorded boundary "
    "(fix a wrong date with remove + `/cycle started` the right one)\n\n"
    "*How detection matches a salary:* an Income transaction whose "
    "Category equals the salary category, or whose Description contains "
    "any search word (default: salary; extend permanently via "
    "`CYCLE_DETECT_KEYWORDS` in .env, or per-scan with `/cycle detect <word>`).\n\n"
    "*Reports:* with cycles enabled, /summary and /budget cover the "
    "current cycle (last boundary → today) instead of the calendar month."
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

    if args[0].lower() == "list":
        cycles_ledger = load_cycles()
        if not cycles_ledger:
            await update.message.reply_text("No cycle boundaries recorded yet.")
            return
        lines = ["💰 *Recorded cycle boundaries:*"]
        for i, (start, label) in enumerate(cycles_ledger):
            end = (
                cycles_ledger[i + 1][0] - timedelta(days=1)
                if i + 1 < len(cycles_ledger)
                else None
            )
            span = f"{start.isoformat()} → {end.isoformat()}" if end else f"{start.isoformat()} → today"
            lines.append(f"• *{label}* — {span}")
        lines.append("\nRemove one with `/cycle remove YYYY-MM-DD`.")
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
        return

    if args[0].lower() == "remove":
        if len(args) < 2:
            await update.message.reply_text(
                "Usage: `/cycle remove YYYY-MM-DD` — see dates with `/cycle list`.",
                parse_mode="Markdown",
            )
            return
        try:
            start = date.fromisoformat(args[1])
        except ValueError:
            await update.message.reply_text(
                "❌ Could not parse the date. Use `/cycle remove YYYY-MM-DD`.",
                parse_mode="Markdown",
            )
            return
        removed = await async_remove_cycle_start(start)
        if removed:
            await update.message.reply_text(
                f"🗑 Removed the cycle boundary on {start.isoformat()}. "
                f"Transactions from that period now belong to the previous cycle."
            )
        else:
            await update.message.reply_text(
                f"No cycle boundary on {start.isoformat()} — check `/cycle list`.",
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


async def _cmd_cycle_detect(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle /cycle detect — scan history and backfill cycle boundaries."""
    if not settings.BUDGET_CYCLE:
        await update.message.reply_text(
            "Budget cycles are disabled\\. Set `BUDGET_CYCLE=1` in \\.env and restart\\.",
            parse_mode="MarkdownV2",
        )
        return

    extra_keywords = list((ctx.args or [])[1:])
    keywords = cycle_detect_keywords(extra_keywords)
    await update.message.reply_text(
        f"🔍 Scanning transaction history — matching: {_esc(', '.join(keywords))}\\.\\.\\.",
        parse_mode="MarkdownV2",
    )

    loop = asyncio.get_running_loop()
    df, cycles = await loop.run_in_executor(None, lambda: (load_data(), load_cycles()))
    candidates = await loop.run_in_executor(
        None, lambda: detect_cycle_candidates(df, cycles, extra_keywords)
    )

    if not candidates:
        await update.message.reply_text(
            "✅ Nothing to backfill — no unrecorded salary payments found\\.\n"
            "If a salary is missing, add its transfer title as a search word: "
            "`/cycle detect wynagrodzenie`\\.",
            parse_mode="MarkdownV2",
        )
        return

    ctx.user_data["detect_candidates"] = [
        {"date_str": c["date"].isoformat(), "amounts": c["amounts"], "unambiguous": c["unambiguous"]}
        for c in candidates
    ]

    n = len(candidates)
    lines = []
    for c in candidates:
        amounts_str = " \\+ ".join(_esc(f"{a:,.0f}") for a in c["amounts"])
        flag = " ⚠️" if not c["unambiguous"] else ""
        lines.append(f"• {_esc(c['date'].isoformat())} — {amounts_str}{flag}")

    text = (
        f"🔍 Found *{_esc(str(n))}* unrecorded {'salary' if n == 1 else 'salaries'}\\.\n\n"
        + "\n".join(lines)
    )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Confirm all", callback_data="detect:confirm_all")],
        [InlineKeyboardButton("🔍 Review one by one", callback_data="detect:review")],
        [InlineKeyboardButton("🛑 Cancel", callback_data="detect:cancel")],
    ])
    await update.message.reply_text(text, parse_mode="MarkdownV2", reply_markup=keyboard)


async def _send_detect_prompt(message, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Send a Yes/Skip/Stop prompt for the next candidate in the review queue."""
    queue = ctx.user_data.get("detect_queue", [])
    if not queue:
        return
    entry = queue[0]
    total = ctx.user_data.get("detect_total", len(queue))
    idx = total - len(queue) + 1

    d = _esc(entry["date_str"])
    if entry["unambiguous"]:
        amounts_str = _esc(f"{entry['amounts'][0]:,.0f}")
        text = f"💰 *{idx} of {total}* — {d}\nSalary · {amounts_str}\n\nDoes this start a new budget cycle?"
    else:
        amounts_str = " \\+ ".join(_esc(f"{a:,.0f}") for a in entry["amounts"])
        text = (
            f"💰 *{idx} of {total}* — {d}\n"
            f"{len(entry['amounts'])} salary payments: {amounts_str}\n\n"
            "Does this date start a new budget cycle?"
        )

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Yes",  callback_data=f"detect:pick:{entry['date_str']}"),
        InlineKeyboardButton("⏭ Skip", callback_data=f"detect:skip:{entry['date_str']}"),
        InlineKeyboardButton("🛑 Stop", callback_data="detect:stop"),
    ]])
    await message.reply_text(text, parse_mode="MarkdownV2", reply_markup=keyboard)


async def _advance_detect_queue(message, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """Pop the front of the review queue and send the next prompt or completion."""
    queue = ctx.user_data.get("detect_queue", [])
    if queue:
        queue.pop(0)
    if queue:
        await _send_detect_prompt(message, ctx)
    else:
        ctx.user_data.pop("detect_queue", None)
        ctx.user_data.pop("detect_total", None)
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
        candidates = ctx.user_data.get("detect_candidates") or []
        loop = asyncio.get_running_loop()
        n = await loop.run_in_executor(
            None,
            lambda: record_cycle_starts_batch(
                [date.fromisoformat(c["date_str"]) for c in candidates]
            ),
        )
        ctx.user_data.pop("detect_candidates", None)
        await query.edit_message_text(
            _esc(f"✅ Confirmed {n} {'boundary' if n == 1 else 'boundaries'}."),
            parse_mode="MarkdownV2",
        )
        await query.message.reply_text(
            "✅ Backfill complete\\! All boundaries have been recorded\\.",
            parse_mode="MarkdownV2",
        )
        return

    if data == "detect:review":
        candidates = ctx.user_data.pop("detect_candidates", None) or []
        ctx.user_data["detect_queue"] = list(candidates)
        ctx.user_data["detect_total"] = len(candidates)
        await query.edit_message_reply_markup(reply_markup=None)
        await _send_detect_prompt(query.message, ctx)
        return

    if data == "detect:cancel":
        ctx.user_data.pop("detect_candidates", None)
        await query.edit_message_text("🛑 Cancelled\\.", parse_mode="MarkdownV2")
        return

    if data.startswith("detect:pick:"):
        date_str = data[len("detect:pick:"):]
        start = date.fromisoformat(date_str)
        await async_record_cycle_start(start)
        await query.edit_message_text(
            f"✅ Recorded — cycle started {_esc(date_str)}\\.",
            parse_mode="MarkdownV2",
        )
        await _advance_detect_queue(query.message, ctx)
        return

    if data.startswith("detect:skip:"):
        date_str = data[len("detect:skip:"):]
        await query.edit_message_text(
            f"⏭ Skipped — {_esc(date_str)} stays in the previous cycle as regular income\\.",
            parse_mode="MarkdownV2",
        )
        await _advance_detect_queue(query.message, ctx)
        return

    if data == "detect:stop":
        recorded = ctx.user_data.get("detect_total", 0) - len(ctx.user_data.get("detect_queue", []))
        ctx.user_data.pop("detect_queue", None)
        ctx.user_data.pop("detect_total", None)
        ctx.user_data.pop("detect_candidates", None)
        await query.edit_message_text(
            _esc(f"🛑 Stopped. Recorded {recorded} {'boundary' if recorded == 1 else 'boundaries'} so far."),
            parse_mode="MarkdownV2",
        )
        return

    log.warning("Unknown detect callback: %s", data)


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
    keywords = cycle_detect_keywords()
    category = str(transaction.category or "").strip().lower()
    description = str(getattr(transaction, "description", "") or "").lower()
    in_category = any(
        re.search(r"\b" + re.escape(k) + r"\b", category) for k in keywords
    )
    in_description = not category and any(
        re.search(r"\b" + re.escape(k) + r"\b", description) for k in keywords
    )
    if not in_category and not in_description:
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
