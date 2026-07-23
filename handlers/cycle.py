"""handlers/cycle.py — /cycle command and salary-save cycle-boundary prompt."""

import re
from datetime import date

from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import ContextTypes

import settings
from config import auth_write, log
from data import now_utc

# Category name that triggers the cycle prompt (case-insensitive comparison).
_SALARY_CATEGORY = "salary"

_MONTH_ABBREVS: dict[str, int] = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
    "january": 1, "february": 2, "march": 3, "april": 4, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10,
    "november": 11, "december": 12,
}

_DATE_SHORT_RE = re.compile(r"^(\d{1,2})\s+([a-zA-Z]{3,})$")


def _parse_cycle_date(text: str) -> date | None:
    """Accept 'today', ISO '2026-07-23', or short form '23 Jul'."""
    t = text.strip().lower()
    if t == "today":
        return now_utc().date()
    try:
        return date.fromisoformat(t)
    except ValueError:
        pass
    m = _DATE_SHORT_RE.match(t)
    if m:
        month = _MONTH_ABBREVS.get(m.group(2).lower()[:9])
        if month:
            try:
                return date(now_utc().year, month, int(m.group(1)))
            except ValueError:
                pass
    return None


def _cycle_label(d: date) -> str:
    return f"{d.strftime('%b')} {d.year}"


def _fmt_date(d: date) -> str:
    return f"{d.day} {d.strftime('%b %Y')}"


def is_salary_income(transaction_type: str, category: str) -> bool:
    """True when the transaction is an income entry in the salary category."""
    return (
        transaction_type.strip() == "Income"
        and category.strip().lower() == _SALARY_CATEGORY
    )


@auth_write
async def cmd_cycle(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """/cycle started [date]  —  record a new budget-cycle boundary (owner only)."""
    if not settings.BUDGET_CYCLE:
        return

    args = ctx.args or []
    if not args or args[0].lower() != "started":
        await update.message.reply_text(
            "Usage: /cycle started [date]\n"
            "Date: 'today', '2026-07-23', or '23 Jul'."
        )
        return

    date_str = " ".join(args[1:]) if len(args) > 1 else "today"
    cycle_date = _parse_cycle_date(date_str)
    if cycle_date is None:
        await update.message.reply_text(
            "❌ Could not parse date. Use 'today', '2026-07-23', or '23 Jul'."
        )
        return

    label = _cycle_label(cycle_date)
    try:
        from file_storage import append_cycle_boundary
        append_cycle_boundary(cycle_date, label)
    except Exception as e:
        log.exception("Failed to record cycle boundary")
        await update.message.reply_text(f"❌ Could not save cycle: {e}")
        return

    await update.message.reply_text(
        f"✅ New budget cycle started from {_fmt_date(cycle_date)}."
    )


async def maybe_prompt_cycle(
    update: Update, ctx: ContextTypes.DEFAULT_TYPE, txn_date: date
) -> None:
    """
    After a salary-income save, offer to open a new budget cycle.
    Fires only when BUDGET_CYCLE=1 and no cycle was recorded within
    CYCLE_PROMPT_COOLDOWN_DAYS days.
    """
    if not settings.BUDGET_CYCLE:
        return

    from file_storage import get_excel_path_for_reading, get_last_cycle_boundary
    last = get_last_cycle_boundary(get_excel_path_for_reading())

    if last is not None:
        last_date, _ = last
        days_since = (now_utc().date() - last_date).days
        if days_since < settings.CYCLE_PROMPT_COOLDOWN_DAYS:
            return

    ctx.user_data["cycle_prompt_pending"] = {"date": txn_date}
    await update.message.reply_text(
        f"💰 Salary received. Start the new budget cycle from {_fmt_date(txn_date)}?"
        " (yes / no / different date)",
        reply_markup=ReplyKeyboardMarkup(
            [["yes", "no"]], one_time_keyboard=True, resize_keyboard=True
        ),
    )


async def handle_cycle_prompt_response(
    update: Update, ctx: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handle yes / no / date reply to the salary cycle prompt."""
    if not ctx.user_data.get("cycle_prompt_pending"):
        return

    text = update.message.text.strip()
    pending = ctx.user_data.pop("cycle_prompt_pending")
    txn_date: date = pending["date"]

    if text.lower() == "no":
        await update.message.reply_text("OK.", reply_markup=ReplyKeyboardRemove())
        return

    if text.lower() == "yes":
        cycle_date = txn_date
    else:
        cycle_date = _parse_cycle_date(text)
        if cycle_date is None:
            ctx.user_data["cycle_prompt_pending"] = pending  # restore for retry
            await update.message.reply_text(
                "❌ Could not parse date. Reply 'yes', 'no', or a date like '23 Jul'."
            )
            return

    label = _cycle_label(cycle_date)
    try:
        from file_storage import append_cycle_boundary
        append_cycle_boundary(cycle_date, label)
    except Exception as e:
        log.exception("Failed to record cycle boundary from prompt")
        await update.message.reply_text(
            f"❌ Could not save cycle: {e}", reply_markup=ReplyKeyboardRemove()
        )
        return

    await update.message.reply_text(
        f"✅ New budget cycle started from {_fmt_date(cycle_date)}.",
        reply_markup=ReplyKeyboardRemove(),
    )
