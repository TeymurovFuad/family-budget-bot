"""Natural-language quick-add conversation."""

import asyncio
from datetime import datetime, timezone

from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import ContextTypes, ConversationHandler

from ai_parser import parse_quick
from config import auth, get_display_currency, log
from data import load_rates, load_reference_data
from excel_ops import append_transaction
from formatters import format_pln_as_currency
from handlers.reports import check_budget_alert
from models import Transaction
from states import QUICK_CONFIRM


# ── Constants ───────────────────────────────────────────────────────────────────
HOUSEHOLD_ALIASES = {"household", "nobody", "none", ""}


# ── Helpers ─────────────────────────────────────────────────────────────────────

def _normalize_str(value: str) -> str:
    return str(value or "").strip()


def _validate_quick_parsed(parsed: dict, lists: dict) -> tuple[bool, str, dict]:
    """Validate and normalize the AI quick-add parse result.

    This function ensures the parsed transaction uses exact list values for:
    - transaction type
    - category
    - currency
    - person (when known persons exist)
    It also enforces a positive numeric value.
    """
    txn_types = [str(t).strip() for t in lists.get("txn_types", []) if t is not None]
    categories = [str(c).strip() for c in lists.get("categories", []) if c is not None]
    currencies = [str(c).strip() for c in lists.get("currencies", []) if c is not None]
    persons = [str(p).strip() for p in lists.get("persons", []) if p is not None]
    if not parsed:
        return False, "Could not parse a transaction.", {}

    value = parsed.get("value")
    try:
        value = float(value)
    except (TypeError, ValueError):
        return False, "Transaction value must be a positive number.", {}
    if value <= 0:
        return False, "Transaction value must be greater than zero.", {}

    txn_type_raw = _normalize_str(parsed.get("type", ""))
    category_raw = _normalize_str(parsed.get("category", ""))
    currency_raw = _normalize_str(parsed.get("currency", "PLN")).upper()
    person_raw = _normalize_str(parsed.get("person", ""))
    date_raw = _normalize_str(parsed.get("date", ""))

    txn_type_map = {t.lower(): t for t in txn_types}
    category_map = {c.lower(): c for c in categories}
    currency_map = {c.upper(): c for c in currencies}
    person_map = {p.lower(): p for p in persons}

    if txn_type_raw.lower() not in txn_type_map:
        return False, (
            f"Unknown transaction type '{txn_type_raw}'. Use one of: {', '.join(txn_types)}."
            if txn_types else "Unknown transaction type."
        ), {}

    if categories and category_raw.lower() not in category_map:
        return False, (
            f"Unknown category '{category_raw}'. Use one of: {', '.join(categories)}."
        ), {}

    if currencies and currency_raw not in currency_map:
        return False, f"Unknown currency '{currency_raw}'. Use one of: {', '.join(currencies)}.", {}

    if persons:
        if person_raw.lower() in HOUSEHOLD_ALIASES:
            normalized_person = ""
        elif person_raw.lower() not in person_map:
            return False, (
                f"Unknown person '{person_raw}'. Use one of: {', '.join(persons)} or leave blank for household."
            ), {}
        else:
            normalized_person = person_map[person_raw.lower()]
    else:
        normalized_person = "" if person_raw.lower() in HOUSEHOLD_ALIASES else person_raw

    parsed_date = None
    if date_raw:
        try:
            parsed_date = datetime.fromisoformat(date_raw).date()
        except ValueError:
            return False, (
                f"Invalid date '{date_raw}'. Use YYYY-MM-DD."
            ), {}

    normalized = parsed.copy()
    normalized["value"] = value
    normalized["type"] = txn_type_map[txn_type_raw.lower()]
    normalized["category"] = category_map[category_raw.lower()]
    normalized["currency"] = currency_map.get(currency_raw, currency_raw)
    normalized["person"] = normalized_person
    normalized["date"] = parsed_date
    return True, "", normalized


@auth
async def handle_quick_add(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text  = update.message.text.strip()
    lists = ctx.user_data.get("lists") or load_reference_data()
    try:
        loop   = asyncio.get_running_loop()
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

    valid, reason, normalized = _validate_quick_parsed(parsed, lists)
    if not valid:
        log.warning("Quick-add rejected invalid parse: %s", reason)
        await update.message.reply_text(
            f"❌ {reason}\n"
            "Use /add to pick from your existing categories, or send a clearer description.",
            reply_markup=ReplyKeyboardRemove(),
        )
        return

    ctx.user_data["quick_parsed"] = normalized

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
            is_recurring=False,
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
