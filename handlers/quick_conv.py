"""Natural-language quick-add conversation."""

import asyncio
from datetime import datetime, timezone

from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import ContextTypes, ConversationHandler

from ai_parser import parse_quick
from config import auth, get_display_currency, log
from data import load_rates, load_reference_data
from excel_ops import append_transaction
from formatters import format_pln_as_currency, sanitize_description
import merchant_map
from handlers.reports import check_budget_alert
from models import Transaction
from states import QUICK_CONFIRM
from validators import MAX_PAST_DAYS, validate_parsed_row


@auth
async def handle_quick_add(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text  = update.message.text.strip()
    lists = ctx.user_data.get("lists") or load_reference_data()
    try:
        loop = asyncio.get_running_loop()
        # Known merchant + amount → deterministic parse from merchant memory,
        # zero AI tokens. Falls through to the AI for anything unrecognized.
        parsed = await loop.run_in_executor(
            None, lambda: merchant_map.try_local_quick_parse(text)
        )
        from_memory = parsed is not None
        if parsed is None:
            parsed = await loop.run_in_executor(None, lambda: parse_quick(text, lists))
    except Exception:
        log.exception("Quick-add parse failed")
        await update.message.reply_text(
            "❌ I couldn't understand that transaction. Use /add to enter it manually."
        )
        return
    if parsed is None:
        # AI says this isn't a transaction — never fail silently.
        await update.message.reply_text(
            "🤔 That doesn't look like a transaction to me. "
            "Try something like `groceries 89` or use /menu.",
            parse_mode="Markdown",
        )
        return

    valid, reason, normalized, corrections = validate_parsed_row(
        parsed, lists, max_past_days=MAX_PAST_DAYS
    )
    if not valid and from_memory:
        # Stale memory (e.g. category renamed in Lists) must never block the
        # user — fall back to the AI and report the detour.
        log.warning("Merchant-memory parse failed validation (%s) — falling back to AI", reason)
        try:
            parsed = await asyncio.get_running_loop().run_in_executor(
                None, lambda: parse_quick(text, lists)
            )
        except Exception:
            parsed = None
        from_memory = False
        if parsed is not None:
            valid, reason, normalized, corrections = validate_parsed_row(
                parsed, lists, max_past_days=MAX_PAST_DAYS
            )
    if parsed is None:
        await update.message.reply_text(
            "🤔 That doesn't look like a transaction to me. "
            "Try something like `groceries 89` or use /menu.",
            parse_mode="Markdown",
        )
        return
    if not valid:
        log.warning("Quick-add rejected invalid parse: %s", reason)
        await update.message.reply_text(
            f"❌ {reason}\n"
            "Use /add to pick from your existing categories, or send a clearer description.",
            reply_markup=ReplyKeyboardRemove(),
        )
        return

    # Same junk-stripping as /add and /bulk — MasterData never sees raw
    # statement noise regardless of entry path.
    normalized["description"] = sanitize_description(str(normalized.get("description") or ""))
    ctx.user_data["quick_parsed"] = normalized

    if from_memory:
        await update.message.reply_text(
            "🧠 Categorized from merchant memory — no AI call needed."
        )
        log.info("Quick-add served from merchant memory: %s", text)

    if corrections:
        shown = "\n".join(f"  • {c}" for c in corrections)
        await update.message.reply_text(f"🛡 Auto-corrected:\n{shown}")
        log.info("Quick-add auto-corrections: %s", "; ".join(corrections))

    # Build a presentation layer for user confirmation.
    ccy   = get_display_currency(update.effective_user.id)
    rates = load_rates()
    val_pln = normalized["value"]
    if normalized["currency"] != "PLN" and normalized["currency"] in rates:
        val_pln = normalized["value"] * rates[normalized["currency"]]

    label    = format_pln_as_currency(val_pln, ccy, rates)
    desc     = normalized.get("description", "")
    cat      = normalized.get("category", "")
    person   = normalized.get("person", "") or "household"
    txn_type = normalized.get("type", "Expense")

    await update.message.reply_text(
        f"💳 *{label}* — {cat} / {person} — {desc} ({txn_type})\nSave?",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup([["Yes", "No"]], one_time_keyboard=True, resize_keyboard=True),
    )
    return QUICK_CONFIRM


@auth
async def quick_confirm(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    response = update.message.text.strip().lower()
    if response == "yes":
        confirmed = True
    elif response == "no":
        confirmed = False
    else:
        await update.message.reply_text(
            "Please use the buttons to confirm or cancel.",
            reply_markup=ReplyKeyboardMarkup([['Yes', 'No']], one_time_keyboard=True, resize_keyboard=True),
        )
        return QUICK_CONFIRM

    if not confirmed:
        log.info("User %s quick-add cancelled", update.effective_user.id)
        await update.message.reply_text("Cancelled.", reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END

    parsed = ctx.user_data.get("quick_parsed", {})
    rates  = load_rates()
    uid    = update.effective_user.id
    ccy    = get_display_currency(uid)

    transaction_date = parsed.get("date")
    if transaction_date is None:
        transaction_date = datetime.now(timezone.utc).date()
    elif isinstance(transaction_date, str):
        transaction_date = datetime.fromisoformat(transaction_date).date()

    try:
        transaction = Transaction(
            date=transaction_date,
            value=float(parsed["value"]),
            currency=parsed.get("currency", "PLN").upper(),
            transaction_type=parsed.get("type", "Expense"),
            category=parsed.get("category", "Other"),
            person=parsed.get("person", ""),
            description=parsed.get("description", ""),
            is_recurring=bool(parsed.get("is_recurring", False)),
        )
        log.info(
            "User %s quick-add transaction saved: value=%s currency=%s category=%s person=%s",
            uid, transaction.value, transaction.currency, transaction.category, transaction.person,
        )
        await append_transaction(transaction)
        log.info("User %s quick-add saved", uid)
        await update.message.reply_text("✅ Saved.", reply_markup=ReplyKeyboardRemove())
        await check_budget_alert(update, transaction.category, ccy, rates)
    except Exception as e:
        log.exception("quick_confirm failed for user %s", uid)
        await update.message.reply_text(f"❌ Failed: {e}", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END
