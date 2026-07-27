"""/add conversation — two-tap flow: amount → category → confirm (with defaults)."""

import asyncio
from datetime import datetime, date, timezone

from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import ContextTypes, ConversationHandler

from config import TIMEZONE, auth_write, get_display_currency, _last_saved, log
from data import load_rates, load_reference_data, now_utc, get_rate
from excel_ops import append_transaction
from formatters import sanitize_description
from handlers.cycle import maybe_prompt_cycle_start
from handlers.reports import check_budget_alert
from handlers.setup_conv import CATEGORY_TYPE_HINTS
import merchant_map
from models import Transaction, AddTransactionState
from validators import parse_amount
from states import (
    ADD_VALUE, ADD_CURRENCY, ADD_TYPE, ADD_CATEGORY,
    ADD_DATE, ADD_DESC, ADD_RECURRING, ADD_CONFIRM,
)

SAVE_BUTTON   = "✅ Save"
EDIT_BUTTON   = "✏️ Edit a field"
CANCEL_BUTTON = "❌ Cancel"
BACK_BUTTON   = "← Back"

# Fields editable from the confirm card. Person is deliberately here (and not
# a conversation step): it defaults to "" = household and is opt-in only.
EDITABLE_FIELDS = ["Amount", "Currency", "Type", "Category",
                   "Date", "Description", "Person", "Recurring"]


@auth_write
async def cmd_add(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if ctx.args and ctx.args[0].lower() == "help":
        await update.message.reply_text(
            "➕ */add* — Add a transaction\n\n"
            "Two steps: amount → category → confirm\\. Everything else "
            "\\(currency, type, date, …\\) is pre\\-filled and editable from "
            "the confirm card\\.\nYou can /cancel at any step\\.",
            parse_mode="MarkdownV2",
        )
        return ConversationHandler.END

    uid   = update.effective_user.id
    rates = load_rates()
    ctx.user_data["state"] = AddTransactionState(
        display_currency=get_display_currency(uid),
        rates=rates,
    )
    ctx.user_data["lists"] = load_reference_data()
    ctx.user_data.pop("dup_warned", None)
    ctx.user_data.pop("add_edit", None)
    await update.message.reply_text(
        "➕ *Log a transaction*\n\nEnter the *amount* (numbers only):",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove(),
    )
    return ADD_VALUE


def _apply_defaults(state: AddTransactionState) -> None:
    """Fill every remaining field with a sensible default (two-tap flow)."""
    if state.currency is None:
        display = state.display_currency
        state.currency = display if display in state.rates else "PLN"
    if state.transaction_type is None:
        state.transaction_type = CATEGORY_TYPE_HINTS.get(state.category or "", "Expense")
    if state.date is None:
        state.date = datetime.now(TIMEZONE).date()
    if state.description is None:
        state.description = ""
    if state.person is None:
        state.person = ""  # household — the family budgets as one unit
    if state.is_recurring is None:
        state.is_recurring = False


async def _detect_recurring(state: AddTransactionState) -> bool:
    """Best-effort 🔁 proposal from MasterData history — never blocks /add."""
    if state.is_recurring or not (state.description or "").strip():
        return False
    try:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, lambda: merchant_map.detect_recurring(state.description, state.value)
        )
    except Exception:
        log.debug("Recurring detection failed", exc_info=True)
        return False


async def _show_confirm_card(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Render the confirm card with all current values. Returns ADD_CONFIRM."""
    state: AddTransactionState = ctx.user_data["state"]
    _apply_defaults(state)

    proposed = await _detect_recurring(state)
    if proposed:
        state.is_recurring = True  # proposal — one tap away from override
        ctx.user_data["recurring_proposed"] = True

    ccy       = state.currency or "PLN"
    pln_equiv = state.value * get_rate(ccy, state.rates)
    pln_note  = f"\n_PLN equivalent: {pln_equiv:,.0f}_" if ccy != "PLN" else ""
    recurring = "Yes" if state.is_recurring else "No"
    if state.is_recurring and ctx.user_data.get("recurring_proposed"):
        recurring += " 🔁 (detected from history)"
    summary = (
        f"📝 *Confirm transaction*\n\n"
        f"Amount:      `{state.value:,.2f} {ccy}`{pln_note}\n"
        f"Type:        `{state.transaction_type}`\n"
        f"Category:    `{state.category or '—'}`\n"
        f"Date:        `{state.date.strftime('%Y-%m-%d')}`\n"
        f"Description: `{state.description or '—'}`\n"
        f"Person:      `{state.person or 'household'}`\n"
        f"Recurring:   `{recurring}`"
    )
    await update.message.reply_text(
        summary, parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup(
            [[SAVE_BUTTON, EDIT_BUTTON], [CANCEL_BUTTON]],
            one_time_keyboard=True, resize_keyboard=True,
        ),
    )
    return ADD_CONFIRM


async def add_value(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    try:
        # Shared normalizer — handles `1 234,56`, `1.234,56`, `1,234.56` alike.
        value, _ = parse_amount(text)
        if value <= 0:
            raise ValueError
    except (ValueError, TypeError):
        await update.message.reply_text("❌ Please enter a valid positive number:")
        return ADD_VALUE

    state: AddTransactionState = ctx.user_data["state"]
    state.value = value
    lists = ctx.user_data.get("lists") or load_reference_data()
    cat_list = lists.get("categories", [])

    if not cat_list:
        await update.message.reply_text(
            "No categories configured — saving without category. "
            "Add entries to column C in your Excel Lists sheet."
        )
        state.category = ""
        return await _show_confirm_card(update, ctx)

    kb = [[c] for c in cat_list]
    await update.message.reply_text(
        f"Got *{value:,.2f}*. Which *category*?",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup(kb, one_time_keyboard=True, resize_keyboard=True),
    )
    return ADD_CATEGORY


async def add_category(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cat   = update.message.text.strip()
    lists = ctx.user_data.get("lists") or load_reference_data()
    state: AddTransactionState = ctx.user_data["state"]
    if cat not in lists.get("categories", []):
        await update.message.reply_text("Please choose from the list.")
        return ADD_CATEGORY
    state.category = cat
    # Everything else is defaulted — jump straight to the confirm card
    # (2 round-trips instead of 9 for the common case).
    return await _show_confirm_card(update, ctx)


# ── Edit-a-field-from-confirm ─────────────────────────────────────────────────

def _field_picker_keyboard() -> ReplyKeyboardMarkup:
    rows = [EDITABLE_FIELDS[i:i + 3] for i in range(0, len(EDITABLE_FIELDS), 3)]
    return ReplyKeyboardMarkup(rows + [[BACK_BUTTON]], one_time_keyboard=True, resize_keyboard=True)


async def _prompt_field_value(update: Update, ctx: ContextTypes.DEFAULT_TYPE, field: str):
    state: AddTransactionState = ctx.user_data["state"]
    lists = ctx.user_data.get("lists") or load_reference_data()
    prompts = {
        "Amount":      ("Enter the new *amount*:", ReplyKeyboardRemove()),
        "Currency":    ("Pick a *currency*:", ReplyKeyboardMarkup(
            [sorted(state.rates.keys())[i:i + 3] for i in range(0, len(state.rates), 3)],
            one_time_keyboard=True, resize_keyboard=True)),
        "Type":        ("Pick a *type*:", ReplyKeyboardMarkup(
            [lists.get("txn_types", ["Expense", "Income", "Savings"])],
            one_time_keyboard=True, resize_keyboard=True)),
        "Category":    ("Pick a *category*:", ReplyKeyboardMarkup(
            [[c] for c in lists.get("categories", [])],
            one_time_keyboard=True, resize_keyboard=True)),
        "Date":        ("Date? (YYYY-MM-DD or 'today'):", ReplyKeyboardMarkup(
            [["today"]], one_time_keyboard=True, resize_keyboard=True)),
        "Description": ("Enter a *description* (or '-' to clear):", ReplyKeyboardRemove()),
        "Person":      ("Who is this for? (or '-' for household):", ReplyKeyboardRemove()),
        "Recurring":   ("Is this *recurring*?", ReplyKeyboardMarkup(
            [["Yes — recurring", "No — one-off"]], one_time_keyboard=True, resize_keyboard=True)),
    }
    text, kb = prompts[field]
    ctx.user_data["add_edit"] = {"stage": "value", "field": field}
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=kb)
    return ADD_CONFIRM


async def _apply_field_value(update: Update, ctx: ContextTypes.DEFAULT_TYPE, field: str):
    """Validate and store one edited field, then re-show the confirm card."""
    text  = update.message.text.strip()
    state: AddTransactionState = ctx.user_data["state"]
    lists = ctx.user_data.get("lists") or load_reference_data()

    if field == "Amount":
        try:
            value, _ = parse_amount(text)
            if value <= 0:
                raise ValueError
        except (ValueError, TypeError):
            await update.message.reply_text("❌ Please enter a valid positive number:")
            return ADD_CONFIRM
        state.value = value
    elif field == "Currency":
        ccy = text.upper()
        if ccy not in state.rates:
            await update.message.reply_text("❌ Unknown currency. Pick from the keyboard:")
            return ADD_CONFIRM
        state.currency = ccy
    elif field == "Type":
        if text not in lists.get("txn_types", []):
            await update.message.reply_text("Please choose from the keyboard.")
            return ADD_CONFIRM
        state.transaction_type = text
    elif field == "Category":
        if text not in lists.get("categories", []):
            await update.message.reply_text("Please choose from the list.")
            return ADD_CONFIRM
        state.category = text
    elif field == "Date":
        today = datetime.now(TIMEZONE).date()
        if text.lower() == "today":
            state.date = today
        else:
            try:
                parsed = date.fromisoformat(text)
            except ValueError:
                await update.message.reply_text("❌ Use YYYY-MM-DD format or 'today':")
                return ADD_CONFIRM
            if parsed > today:
                await update.message.reply_text("⚠️ Future dates aren't allowed. Enter a date or 'today':")
                return ADD_CONFIRM
            state.date = parsed
    elif field == "Description":
        state.description = "" if text == "-" else sanitize_description(text)
        # Detection re-runs in _show_confirm_card with the new text.
        ctx.user_data.pop("recurring_proposed", None)
    elif field == "Person":
        state.person = "" if text == "-" else text
    elif field == "Recurring":
        state.is_recurring = "yes" in text.lower()
        ctx.user_data.pop("recurring_proposed", None)  # explicit user choice

    ctx.user_data.pop("add_edit", None)
    return await _show_confirm_card(update, ctx)


async def add_confirm(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()

    # Field-edit mini-flow (stays inside the ADD_CONFIRM state).
    edit = ctx.user_data.get("add_edit")
    if edit:
        if edit["stage"] == "field":
            if text == BACK_BUTTON:
                ctx.user_data.pop("add_edit", None)
                return await _show_confirm_card(update, ctx)
            if text not in EDITABLE_FIELDS:
                await update.message.reply_text("Pick a field from the keyboard.")
                return ADD_CONFIRM
            return await _prompt_field_value(update, ctx, text)
        return await _apply_field_value(update, ctx, edit["field"])

    if "edit" in text.lower():
        ctx.user_data["add_edit"] = {"stage": "field"}
        await update.message.reply_text(
            "Which field do you want to change?", reply_markup=_field_picker_keyboard()
        )
        return ADD_CONFIRM

    if "save" not in text.lower():
        await update.message.reply_text("❌ Cancelled.", reply_markup=ReplyKeyboardRemove())
        ctx.user_data.clear()
        return ConversationHandler.END

    state: AddTransactionState = ctx.user_data["state"]
    uid = update.effective_user.id

    if not ctx.user_data.get("dup_warned"):
        last = _last_saved.get(uid)
        if last:
            lval, lccy, lcat, ltime = last
            age_secs = (datetime.now(timezone.utc) - ltime).total_seconds()
            if (abs((state.value or 0) - lval) < 0.01
                    and (state.currency or "PLN") == lccy
                    and (state.category or "") == lcat
                    and age_secs < 60):
                ctx.user_data["dup_warned"] = True
                await update.message.reply_text(
                    f"⚠️ Possible duplicate — you just saved "
                    f"`{lval:,.2f} {lccy}` → _{lcat}_ {int(age_secs)}s ago.\n\nSave anyway?",
                    parse_mode="Markdown",
                    reply_markup=ReplyKeyboardMarkup(
                        [["✅ Yes, save anyway", "❌ Cancel"]], one_time_keyboard=True, resize_keyboard=True
                    ),
                )
                return ADD_CONFIRM

    try:
        transaction = state.to_transaction()
        log.info("User %s saving transaction: %s %s %s", uid, transaction.value, transaction.currency, transaction.category)
        await append_transaction(transaction)
        log.info("User %s transaction saved: %s %s %s", uid, transaction.value, transaction.currency, transaction.category)
        _last_saved[uid] = (
            transaction.value, transaction.currency,
            transaction.category, datetime.now(timezone.utc),
        )
        ccy      = transaction.currency
        pln      = transaction.value * get_rate(ccy, state.rates)
        suffix   = f" ({pln:,.0f} PLN)" if ccy != "PLN" else ""
        disp_ccy = get_display_currency(uid)
        await update.message.reply_text(
            f"✅ Saved: *{transaction.value:,.2f} {ccy}*{suffix} → {transaction.category}",
            parse_mode="Markdown",
            reply_markup=ReplyKeyboardRemove(),
        )
        await check_budget_alert(update, transaction.category, disp_ccy, state.rates)
        await maybe_prompt_cycle_start(update, transaction)
    except Exception as e:
        log.exception("Failed to save transaction for user %s", uid)
        await update.message.reply_text(f"❌ Failed to save: {e}", reply_markup=ReplyKeyboardRemove())

    ctx.user_data.clear()
    return ConversationHandler.END


async def add_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Cancelled.", reply_markup=ReplyKeyboardRemove())
    ctx.user_data.clear()
    return ConversationHandler.END


# ── Legacy step handlers ──────────────────────────────────────────────────────
# bot.py still imports and registers these for the retired 9-step flow states.
# The two-tap flow no longer routes through them, but they must keep working
# for any conversation resumed mid-flight (and for import compatibility).

async def add_currency(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ccy   = update.message.text.strip().upper()
    state: AddTransactionState = ctx.user_data["state"]
    if ccy not in state.rates:
        await update.message.reply_text("❌ Unknown currency. Pick from the keyboard:")
        return ADD_CURRENCY
    state.currency = ccy
    return await _show_confirm_card(update, ctx)


async def add_type(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    t     = update.message.text.strip()
    lists = ctx.user_data.get("lists") or load_reference_data()
    if t not in lists["txn_types"]:
        await update.message.reply_text(
            f"Please choose {' | '.join(lists['txn_types'])}."
        )
        return ADD_TYPE
    state: AddTransactionState = ctx.user_data["state"]
    state.transaction_type = t
    return await _show_confirm_card(update, ctx)


async def add_date(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text  = update.message.text.strip().lower()
    state: AddTransactionState = ctx.user_data["state"]
    today = datetime.now(TIMEZONE).date()
    if text in ("today", ""):
        state.date = today
    else:
        try:
            parsed = date.fromisoformat(text)
        except ValueError:
            await update.message.reply_text("❌ Use YYYY-MM-DD format or 'today':")
            return ADD_DATE
        if parsed > today:
            await update.message.reply_text("⚠️ Future dates (UTC) aren't allowed. Enter a date or 'today':")
            return ADD_DATE
        state.date = parsed
    return await _show_confirm_card(update, ctx)


async def add_desc(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    state: AddTransactionState = ctx.user_data["state"]
    state.description = sanitize_description(update.message.text)
    return await _show_confirm_card(update, ctx)


async def add_skip_desc(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    state: AddTransactionState = ctx.user_data["state"]
    state.description = ""
    return await _show_confirm_card(update, ctx)


async def add_recurring(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    state: AddTransactionState = ctx.user_data["state"]
    state.is_recurring = "yes" in update.message.text.lower()
    return await _show_confirm_card(update, ctx)
