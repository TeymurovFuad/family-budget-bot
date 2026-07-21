"""/add conversation — 9-step flow to log a new transaction."""

from datetime import datetime, date, timezone

from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import ContextTypes, ConversationHandler

from config import TIMEZONE, auth, get_display_currency, _last_saved, log
from data import load_rates, load_reference_data, now_utc, get_rate
from excel_ops import append_transaction
from formatters import sanitize_description
from handlers.reports import check_budget_alert
from models import Transaction, AddTransactionState
from validators import parse_amount
from states import (
    ADD_VALUE, ADD_CURRENCY, ADD_TYPE, ADD_CATEGORY,
    ADD_PERSON, ADD_DATE, ADD_DESC, ADD_RECURRING, ADD_CONFIRM,
)


@auth
async def cmd_add(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uid   = update.effective_user.id
    rates = load_rates()
    ctx.user_data["state"] = AddTransactionState(
        display_currency=get_display_currency(uid),
        rates=rates,
    )
    ctx.user_data["lists"] = load_reference_data()
    ctx.user_data.pop("dup_warned", None)
    await update.message.reply_text(
        "➕ *Log a transaction*\n\nEnter the *amount* (numbers only):",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove(),
    )
    return ADD_VALUE


async def add_value(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    try:
        # Shared normalizer — handles `1 234,56`, `1.234,56`, `1,234.56` alike.
        value = parse_amount(text)
        if value <= 0:
            raise ValueError
    except (ValueError, TypeError):
        await update.message.reply_text("❌ Please enter a valid positive number:")
        return ADD_VALUE

    state: AddTransactionState = ctx.user_data["state"]
    state.value = value
    ccys = sorted(state.rates.keys())
    display = state.display_currency
    if display in ccys:
        ccys.remove(display)
        ccys = [display] + ccys
    kb = [ccys[i:i+3] for i in range(0, len(ccys), 3)]
    ctx.user_data["state"] = state
    await update.message.reply_text(
        f"Got *{value:,.2f}*. Which currency?",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup(kb, one_time_keyboard=True, resize_keyboard=True),
    )
    return ADD_CURRENCY


async def add_currency(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ccy   = update.message.text.strip().upper()
    state: AddTransactionState = ctx.user_data["state"]
    if ccy not in state.rates:
        await update.message.reply_text("❌ Unknown currency. Pick from the keyboard:")
        return ADD_CURRENCY
    state.currency = ccy
    pln_equiv = state.value * get_rate(ccy, state.rates)
    note = "" if ccy == "PLN" else f"\n_= {pln_equiv:,.0f} PLN at current rate_"
    lists = ctx.user_data.get("lists") or load_reference_data()
    await update.message.reply_text(
        f"*{state.value:,.2f} {ccy}*{note}\n\nWhat type?",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup([lists["txn_types"]], one_time_keyboard=True, resize_keyboard=True),
    )
    return ADD_TYPE


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

    cat_list = lists.get("categories", [])

    if not cat_list:
        await update.message.reply_text("_(No categories configured — saving without category.)_")
        state.category = ""
        await update.message.reply_text(
            "No categories configured. "
            "Skipping category — add entries to column C in your Excel Lists sheet."
        )
        await update.message.reply_text(
            "Date? (YYYY-MM-DD or 'today'):",
            reply_markup=ReplyKeyboardMarkup([["today"]], one_time_keyboard=True, resize_keyboard=True),
        )
        return ADD_DATE

    kb = [[c] for c in cat_list]
    await update.message.reply_text(
        "Which *category*?",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup(kb, one_time_keyboard=True, resize_keyboard=True),
    )
    return ADD_CATEGORY


async def add_category(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    cat   = update.message.text.strip()
    lists = ctx.user_data.get("lists") or load_reference_data()
    state: AddTransactionState = ctx.user_data["state"]
    valid_cats = lists.get("categories", [])
    if cat not in valid_cats:
        await update.message.reply_text("Please choose from the list.")
        return ADD_CATEGORY
    state.category = cat
    persons = lists["persons"]
    if persons:
        keyboard = ReplyKeyboardMarkup(
            [persons, ["— nobody specific —"]], one_time_keyboard=True, resize_keyboard=True
        )
        msg = "For *whom*?"
    else:
        keyboard = ReplyKeyboardMarkup(
            [["— nobody specific —"]], one_time_keyboard=True, resize_keyboard=True
        )
        msg = (
            "For *whom*? Type a name or tap skip.\n\n"
            "_Tip: you can pre-add family members to the Lists sheet in Excel "
            "so they appear as quick buttons here._"
        )
    await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=keyboard)
    return ADD_PERSON


async def add_person(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    p = update.message.text.strip()
    state: AddTransactionState = ctx.user_data["state"]
    state.person = "" if "nobody" in p.lower() else p
    await update.message.reply_text(
        "Date? (YYYY-MM-DD or 'today'):",
        reply_markup=ReplyKeyboardMarkup([["today"]], one_time_keyboard=True, resize_keyboard=True),
    )
    return ADD_DATE


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
        days_ago = (today - parsed).days
        if parsed > today:
            await update.message.reply_text("⚠️ Future dates (UTC) aren't allowed. Enter a date or 'today':")
            return ADD_DATE
        if days_ago > 90:
            if ctx.user_data.get("_date_confirmed"):
                ctx.user_data.pop("_date_confirmed", None)
                # proceed — user confirmed
            else:
                ctx.user_data["_date_confirmed"] = True
                await update.message.reply_text(
                    f"⚠️ That's {days_ago} days ago. "
                    "Send the same date again to confirm, or enter a different date:"
                )
                return ADD_DATE
        ctx.user_data.pop("_date_confirmed", None)
        state.date = parsed
    await update.message.reply_text(
        "Short *description* (or /skip):",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardRemove(),
    )
    return ADD_DESC


async def add_desc(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    state: AddTransactionState = ctx.user_data["state"]
    state.description = sanitize_description(update.message.text)
    await update.message.reply_text(
        "Is this a *recurring* expense?",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup(
            [["Yes — recurring", "No — one-off"]], one_time_keyboard=True, resize_keyboard=True
        ),
    )
    return ADD_RECURRING


async def add_skip_desc(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    state: AddTransactionState = ctx.user_data["state"]
    state.description = ""
    await update.message.reply_text(
        "Is this a *recurring* expense?",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup(
            [["Yes — recurring", "No — one-off"]], one_time_keyboard=True, resize_keyboard=True
        ),
    )
    return ADD_RECURRING


async def add_recurring(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    state: AddTransactionState = ctx.user_data["state"]
    state.is_recurring = "yes" in update.message.text.lower()
    ccy      = state.currency or "PLN"
    pln_equiv = state.value * get_rate(ccy, state.rates)
    txn_date  = state.date or now_utc().date()
    pln_note  = f"\n_PLN equivalent: {pln_equiv:,.0f}_" if ccy != "PLN" else ""
    summary = (
        f"📝 *Confirm transaction*\n\n"
        f"Amount:      `{state.value:,.2f} {ccy}`{pln_note}\n"
        f"Type:        `{state.transaction_type}`\n"
        f"Category:    `{state.category or '—'}`\n"
        f"Person:      `{state.person or '—'}`\n"
        f"Date:        `{txn_date.strftime('%Y-%m-%d')}`\n"
        f"Description: `{state.description or '—'}`\n"
        f"Recurring:   `{'Yes' if state.is_recurring else 'No'}`"
    )
    await update.message.reply_text(
        summary, parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup([["✅ Save", "❌ Cancel"]], one_time_keyboard=True, resize_keyboard=True),
    )
    return ADD_CONFIRM


async def add_confirm(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if "save" not in update.message.text.lower():
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
    except Exception as e:
        log.exception("Failed to save transaction for user %s", uid)
        await update.message.reply_text(f"❌ Failed to save: {e}", reply_markup=ReplyKeyboardRemove())

    ctx.user_data.clear()
    return ConversationHandler.END


async def add_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Cancelled.", reply_markup=ReplyKeyboardRemove())
    ctx.user_data.clear()
    return ConversationHandler.END
