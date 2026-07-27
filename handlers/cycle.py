"""/cycle command and the salary-triggered new-cycle prompt."""

import asyncio
import re
from datetime import date, timedelta

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes
from telegram.helpers import escape_markdown

import settings
from config import ALLOWED_USERS, auth, auth_write, get_display_currency, log
from data import load_data, load_rates, now_utc
from formatters import format_base_as_currency
from log_decorators import log_call
from cycles import (
    async_record_cycle_start, async_remove_cycle_start, current_cycle_start,
    cycle_label, cycle_detect_keywords, detect_cycle_candidates,
    fallback_income_candidates, load_cycles,
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
    "any search word (default: salary; extend permanently via /keywords, "
    "or per-scan with `/cycle detect <word>`).\n\n"
    "*Reports:* with cycles enabled, /summary, /budget, /report, /top and "
    "budget alerts cover the current cycle (last boundary → today) instead "
    "of the calendar month."
)


def _esc(text: str) -> str:
    """Escape a plain-text string for MarkdownV2."""
    return re.sub(r"([_*\[\]()~`>#+\-=|{}.!\\])", r"\\\1", str(text))


def _day_month(d: date) -> str:
    return f"{d.day} {d.strftime('%b')}"


async def _deny_non_owner(update: Update) -> bool:
    """True (and replies) when the caller is not the bot owner."""
    # TODO: consolidate into config.auth_owner decorator when multiple-owner
    # support is added.
    if update.effective_user.id == ALLOWED_USERS[0]:
        return False
    msg = update.message or (update.callback_query and update.callback_query.message)
    if msg:
        await msg.reply_text(
            "⛔ Only the bot owner can make changes. "
            "You can view reports and data, but not add, edit, or delete."
        )
    if update.callback_query:
        await update.callback_query.answer("⛔ Owner only", show_alert=True)
    return True


@auth
@log_call()
async def cmd_cycle(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not settings.BUDGET_CYCLE:
        await update.message.reply_text(
            "Budget cycles are disabled. Set `BUDGET_CYCLE=1` in .env and restart to enable them.",
            parse_mode="Markdown",
        )
        return

    today = now_utc().date()
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
                f"💰 Current cycle: *{escape_markdown(label)}* — started {start.isoformat()}, "
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
            lines.append(f"• *{escape_markdown(label)}* — {span}")
        lines.append("\nRemove one with `/cycle remove YYYY-MM-DD`.")
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
        return

    if args[0].lower() == "remove":
        if await _deny_non_owner(update):
            return
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

    if await _deny_non_owner(update):
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

    label = await async_record_cycle_start(start)
    if label:
        await update.message.reply_text(
            f"✅ New budget cycle *{escape_markdown(label)}* started from {start.isoformat()}.",
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

    # Clear any state left over from a previous detect session.
    ctx.user_data.pop("detect_candidates", None)
    ctx.user_data.pop("detect_queue", None)
    ctx.user_data.pop("detect_total", None)
    ctx.user_data.pop("detect_recorded", None)

    extra_keywords = list((ctx.args or [])[1:])
    keywords = cycle_detect_keywords(extra_keywords)
    await update.message.reply_text(
        f"🔍 Scanning transaction history — matching: {_esc(', '.join(keywords))}\\.\\.\\.",
        parse_mode="MarkdownV2",
    )

    loop = asyncio.get_running_loop()
    df, rates, cycles = await loop.run_in_executor(
        None, lambda: (load_data(), load_rates(), load_cycles())
    )
    candidates = await loop.run_in_executor(
        None, lambda: detect_cycle_candidates(df, cycles, extra_keywords)
    )

    ccy = get_display_currency(update.effective_user.id)

    def _fmt_amount(a: float) -> str:
        return format_base_as_currency(a, ccy, rates)

    def _entries(cands: list[dict]) -> list[dict]:
        return [
            {
                "date_str": c["date"].isoformat(),
                "amounts": c["amounts"],
                "amounts_fmt": [_fmt_amount(a) for a in c["amounts"]],
                "unambiguous": c["unambiguous"],
            }
            for c in cands
        ]

    if not candidates:
        # No salary-category rows — offer the largest Income rows in the
        # ±20-day window around the 1st of the current month as candidates.
        # Catches salaries filed under non-salary categories.
        anchor = now_utc().date().replace(day=1)
        fallback = await loop.run_in_executor(
            None, lambda: fallback_income_candidates(df, anchor, cycles)
        )
        if not fallback:
            await update.message.reply_text(
                "✅ Nothing to backfill — no unrecorded salary payments found\\.\n"
                "If a salary is missing, add its transfer title as a search word: "
                "`/cycle detect wynagrodzenie`\\.",
                parse_mode="MarkdownV2",
            )
            return
        ctx.user_data["detect_queue"] = [_entries(fallback)]
        ctx.user_data["detect_total"] = 1
        ctx.user_data["detect_recorded"] = 0
        await update.message.reply_text(
            f"🔍 No salary\\-category rows found\\. Largest income near "
            f"{_esc(anchor.strftime('%b %Y'))} — maybe one of these started the cycle:",
            parse_mode="MarkdownV2",
        )
        await _send_detect_prompt(update.message, ctx)
        return

    ctx.user_data["detect_candidates"] = _entries(candidates)

    n = len(candidates)
    lines = []
    for c in candidates:
        amounts_str = " \\+ ".join(_esc(_fmt_amount(a)) for a in c["amounts"])
        flag = " ⚠️" if not c["unambiguous"] else ""
        lines.append(f"• {_esc(c['date'].isoformat())} — {amounts_str}{flag}")

    text = (
        f"🔍 Found *{_esc(str(n))}* unrecorded {'salary' if n == 1 else 'salaries'}\\.\n\n"
        + "\n".join(lines)
    )
    if extra_keywords:
        text += (
            "\n\n⚠️ These keywords apply to this scan only\\. "
            "Use /keywords to save them permanently\\."
        )
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Confirm all", callback_data="detect:confirm_all")],
        [InlineKeyboardButton("🔍 Review one by one", callback_data="detect:review")],
        [InlineKeyboardButton("🛑 Cancel", callback_data="detect:cancel")],
    ])
    await update.message.reply_text(text, parse_mode="MarkdownV2", reply_markup=keyboard)


def _group_by_month(entries: list[dict]) -> list[list[dict]]:
    """Group review entries into per-calendar-month lists, oldest first —
    input order does not matter."""
    groups: list[list[dict]] = []
    for e in sorted(entries, key=lambda e: e["date_str"]):
        key = e["date_str"][:7]
        if groups and groups[-1][0]["date_str"][:7] == key:
            groups[-1].append(e)
        else:
            groups.append([e])
    return groups


def _month_of(group: list[dict]) -> str:
    return date.fromisoformat(group[0]["date_str"]).strftime("%b %Y")


async def _send_detect_prompt(message, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Prompt for the next month group in the review queue. A single candidate
    gets Yes/Skip; several candidates in one month get one button per
    candidate (largest first). Both get "No cycle this month" — extending the
    previous cycle is valid data, not an error.
    """
    queue = ctx.user_data.get("detect_queue", [])
    if not queue:
        return
    group = queue[0]
    total = ctx.user_data.get("detect_total", len(queue))
    idx = total - len(queue) + 1
    month = group[0]["date_str"][:7]

    def _fmt(entry):
        return entry.get("amounts_fmt") or [f"{a:,.0f}" for a in entry["amounts"]]

    none_row = [InlineKeyboardButton(
        "🚫 No cycle this month", callback_data=f"detect:none:{month}"
    )]

    if len(group) == 1:
        entry = group[0]
        d = _esc(entry["date_str"])
        amounts_fmt = _fmt(entry)
        if entry["unambiguous"]:
            amounts_str = _esc(amounts_fmt[0])
            text = f"💰 *{idx} of {total}* — {d}\nSalary · {amounts_str}\n\nDoes this start a new budget cycle?"
        else:
            amounts_str = " \\+ ".join(_esc(a) for a in amounts_fmt)
            text = (
                f"💰 *{idx} of {total}* — {d}\n"
                f"{len(amounts_fmt)} salary payments: {amounts_str}\n\n"
                "Does this date start a new budget cycle?"
            )
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Yes",  callback_data=f"detect:pick:{entry['date_str']}"),
                InlineKeyboardButton("⏭ Skip", callback_data=f"detect:skip:{entry['date_str']}"),
                InlineKeyboardButton("🛑 Stop", callback_data="detect:stop"),
            ],
            none_row,
        ])
        await message.reply_text(text, parse_mode="MarkdownV2", reply_markup=keyboard)
        return

    # Several candidate dates in one month — one tap picks the boundary.
    ordered = sorted(group, key=lambda e: max(e["amounts"]), reverse=True)
    text = (
        f"💰 *{idx} of {total}* — {_esc(_month_of(group))}\n"
        f"{len(group)} salary candidates this month\\. "
        "Which one starts the budget cycle?"
    )
    rows = []
    for entry in ordered:
        d = date.fromisoformat(entry["date_str"])
        amounts_str = " + ".join(_fmt(entry))
        rows.append([InlineKeyboardButton(
            f"{_day_month(d)} — {amounts_str}",
            callback_data=f"detect:pick:{entry['date_str']}",
        )])
    rows.append(none_row)
    rows.append([
        InlineKeyboardButton("📅 Custom date", callback_data="detect:custom"),
        InlineKeyboardButton("🛑 Stop", callback_data="detect:stop"),
    ])
    await message.reply_text(text, parse_mode="MarkdownV2",
                             reply_markup=InlineKeyboardMarkup(rows))


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
        ctx.user_data.pop("detect_recorded", None)
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
        groups = _group_by_month(candidates)
        ctx.user_data["detect_queue"] = groups
        ctx.user_data["detect_total"] = len(groups)
        ctx.user_data["detect_recorded"] = 0
        await query.edit_message_reply_markup(reply_markup=None)
        await _send_detect_prompt(query.message, ctx)
        return

    if data == "detect:cancel":
        ctx.user_data.pop("detect_candidates", None)
        await query.edit_message_text("🛑 Cancelled\\.", parse_mode="MarkdownV2")
        return

    if data.startswith("detect:pick:"):
        if update.effective_user.id != ALLOWED_USERS[0]:
            await query.answer(
                "⛔ Only the bot owner can record cycle boundaries.", show_alert=True
            )
            return
        date_str = data[len("detect:pick:"):]
        start = date.fromisoformat(date_str)
        if await async_record_cycle_start(start):
            ctx.user_data["detect_recorded"] = ctx.user_data.get("detect_recorded", 0) + 1
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

    if data.startswith("detect:none:"):
        # "No cycle this month" — a valid answer, not a skip: the previous
        # cycle simply runs longer (a 60-day cycle is data, not an error).
        month_key = data[len("detect:none:"):]
        try:
            month_label = date.fromisoformat(month_key + "-01").strftime("%b %Y")
        except ValueError:
            month_label = month_key
        await query.edit_message_text(
            f"🚫 No cycle in {_esc(month_label)} — the previous cycle "
            f"extends through it\\.",
            parse_mode="MarkdownV2",
        )
        await _advance_detect_queue(query.message, ctx)
        return

    if data == "detect:custom":
        await query.edit_message_text(
            "📅 Send `/cycle started YYYY\\-MM\\-DD` with the date the cycle "
            "should start from\\.",
            parse_mode="MarkdownV2",
        )
        await _advance_detect_queue(query.message, ctx)
        return

    if data == "detect:stop":
        recorded = ctx.user_data.get("detect_recorded", 0)
        ctx.user_data.pop("detect_queue", None)
        ctx.user_data.pop("detect_total", None)
        ctx.user_data.pop("detect_recorded", None)
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
    today = now_utc().date()
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
        label = await async_record_cycle_start(start)
        if label:
            await query.message.reply_text(
                f"✅ New budget cycle *{escape_markdown(label)}* started from {start.isoformat()}.",
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
