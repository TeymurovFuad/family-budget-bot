"""Natural-language quick-add conversation."""

import asyncio
import re
from datetime import datetime, timezone

from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import ContextTypes, ConversationHandler

from ai_parser import parse_quick
from config import auth, auth_write, get_display_currency, log
from data import load_rates, load_reference_data
from excel_ops import append_transaction
from formatters import format_base_as_currency, sanitize_description
import merchant_map
import settings
from handlers.cycle import maybe_prompt_cycle_start
from handlers.reports import check_budget_alert
from models import Transaction
from states import QUICK_CONFIRM
from validators import MAX_PAST_DAYS, parse_amount, validate_parsed_row

RECURRING_YES_BUTTON = "Yes — recurring 🔁"

# A bare "<amount>" message ("89.50") — needs only a category pick.
_BARE_AMOUNT_RE = re.compile(r"^\d+(?:[.,]\d{1,2})?$")

# Single quick-add grammar, shared with the merchant-memory fast path
# ("[YYYY-MM-DD] <merchant words> <amount> [CCY]") so the two zero-token
# parsers can never drift apart.
_QUICK_SHAPE_RE = merchant_map._QUICK_RE


def _local_fast_parse(text: str, lists: dict, rates: dict) -> tuple[dict | None, bool]:
    """
    Zero-AI pre-parser for the most common quick-add shapes.

    Returns (parsed_row, needs_category):
      - ("groceries 89")  → fully-resolved row when the words match a known
        category (case-insensitive) — skip the AI entirely.
      - ("89.50")         → partial row + needs_category=True so the caller
        can offer the category keyboard — still no AI call.
      - anything else     → (None, False): fall through to the AI.

    Reuses merchant_map's quick-add grammar so the two zero-token paths
    (merchant memory and category words) can never drift apart.
    """
    raw = str(text or "").strip()
    if _BARE_AMOUNT_RE.match(raw):
        value, _ = parse_amount(raw)
        return {
            "date": "", "value": value, "currency": settings.DISPLAY_CURRENCY, "type": "Expense",
            "category": "", "description": "", "person": "", "is_recurring": False,
        }, True
    match = _QUICK_SHAPE_RE.match(raw)
    if not match:
        return None, False
    date_s, desc, amount_s, ccy = match.groups()
    desc = (desc or "").strip()
    ccy = (ccy or "").upper()
    if ccy and ccy not in rates:
        # Trailing 3-letter word isn't a currency — treat it as ambiguous text.
        return None, False
    try:
        # Shared normalizer — same separator handling as /add and /bulk.
        value, _ = parse_amount(amount_s)
    except (ValueError, TypeError):
        return None, False
    row = {
        "date": date_s or "",
        "value": value,
        "currency": ccy or settings.DISPLAY_CURRENCY,
        "type": "Expense",
        "category": "",
        "description": desc,
        "person": "",
        "is_recurring": False,
    }
    cat_map = {str(c).strip().lower(): str(c).strip() for c in lists.get("categories", [])}
    category = cat_map.get(desc.lower())
    if category is None:
        return None, False  # unknown merchant/phrasing — let the AI decide
    row["category"] = category
    return row, False


async def _propose_recurring(normalized: dict) -> bool:
    """Best-effort history lookup — never blocks or breaks the confirm step."""
    if normalized.get("is_recurring"):
        return False
    try:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            lambda: merchant_map.detect_recurring(
                normalized.get("description", ""), normalized.get("value")
            ),
        )
    except Exception:
        log.debug("Recurring detection failed", exc_info=True)
        return False


async def _send_confirm_card(update: Update, ctx: ContextTypes.DEFAULT_TYPE,
                             normalized: dict, rates: dict | None = None):
    """Store the row and ask the user to confirm it. Returns QUICK_CONFIRM."""
    ctx.user_data["quick_parsed"] = normalized

    ccy = get_display_currency(update.effective_user.id)
    if rates is None:
        rates = load_rates()
    val_base = normalized["value"]
    if normalized["currency"] != settings.DISPLAY_CURRENCY and normalized["currency"] in rates:
        val_base = normalized["value"] * rates[normalized["currency"]]

    label = format_base_as_currency(val_base, ccy, rates)
    desc = normalized.get("description", "")
    cat = normalized.get("category", "")
    txn_type = normalized.get("type", "Expense")

    recurring_note = ""
    buttons = [["Yes", "No"]]
    if await _propose_recurring(normalized):
        recurring_note = "\n🔁 _Looks recurring — seen in 2+ past months at a similar amount._"
        buttons = [["Yes", RECURRING_YES_BUTTON], ["No"]]

    await update.message.reply_text(
        f"💳 *{label}* — {cat} — {desc} ({txn_type}){recurring_note}\nSave?",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup(buttons, one_time_keyboard=True, resize_keyboard=True),
    )
    return QUICK_CONFIRM


def _category_keyboard(lists: dict) -> ReplyKeyboardMarkup:
    kb = [[c] for c in lists.get("categories", [])] + [["Cancel"]]
    return ReplyKeyboardMarkup(kb, one_time_keyboard=True, resize_keyboard=True)


async def _offer_category_fix(update, ctx, row: dict, lists: dict, intro: str):
    """One-tap recovery: keep what parsed, ask only for the category."""
    ctx.user_data["quick_fix"] = row
    ccy = str(row.get("currency") or settings.DISPLAY_CURRENCY).upper()
    await update.message.reply_text(
        f"{intro}\n"
        f"Amount: *{float(row['value']):,.2f} {ccy}*"
        # Code span, not italic — user text may contain Markdown chars like `_`.
        + (f" — `{row['description']}`" if row.get("description") else "")
        + "\n\nWhich *category*?",
        parse_mode="Markdown",
        reply_markup=_category_keyboard(lists),
    )
    return QUICK_CONFIRM


def _has_usable_amount(row: dict | None) -> bool:
    try:
        return row is not None and float(row.get("value")) > 0
    except (TypeError, ValueError):
        return False


@auth_write
async def handle_quick_add(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text  = update.message.text.strip()
    lists = ctx.user_data.get("lists") or load_reference_data()
    if not lists.get("categories"):
        # Reference data unavailable (file locked, Lists sheet renamed, …).
        # Without categories, every downstream lookup would KeyError and the
        # user would get no reply at all — fail loudly instead.
        log.error("Quick-add aborted: reference lists are empty — Excel file unreadable?")
        await update.message.reply_text(
            "❌ I can't read your Excel file right now, so I can't add "
            "transactions. Check that the workbook is available (not locked "
            "or renamed) and try again."
        )
        return
    try:
        loop = asyncio.get_running_loop()
        rates = await loop.run_in_executor(None, load_rates)
        # Known merchant + amount → deterministic parse from merchant memory,
        # zero AI tokens. Falls through to the AI for anything unrecognized.
        parsed = await loop.run_in_executor(
            None, lambda: merchant_map.try_local_quick_parse(text)
        )
        source = "memory" if parsed is not None else "ai"
        if parsed is None:
            # Regex fast path: "groceries 89", "89.50" — still zero AI tokens.
            parsed, needs_category = _local_fast_parse(text, lists, rates)
            if parsed is not None:
                source = "fast"
                if needs_category:
                    return await _offer_category_fix(
                        update, ctx, parsed, lists, "Got the amount — no category yet."
                    )
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
    if not valid and source != "ai":
        # Stale memory (e.g. category renamed in Lists) must never block the
        # user — fall back to the AI and report the detour.
        log.warning("Local quick parse failed validation (%s) — falling back to AI", reason)
        try:
            parsed = await asyncio.get_running_loop().run_in_executor(
                None, lambda: parse_quick(text, lists)
            )
        except Exception:
            parsed = None
        source = "ai"
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
        # One-tap recovery: when only the category is bad but the amount
        # parsed fine, keep everything and ask just for the category —
        # don't eject the user to the full /add flow.
        if "category" in reason.lower() and _has_usable_amount(parsed):
            return await _offer_category_fix(
                update, ctx, dict(parsed), lists,
                f"⚠️ {reason}\nHere's what I understood so far:",
            )
        await update.message.reply_text(
            f"❌ {reason}\n"
            "Use /add to pick from your existing categories, or send a clearer description.",
            reply_markup=ReplyKeyboardRemove(),
        )
        return

    # Same junk-stripping as /add and /bulk — MasterData never sees raw
    # statement noise regardless of entry path.
    normalized["description"] = sanitize_description(str(normalized.get("description") or ""))

    if source == "memory":
        await update.message.reply_text(
            "🧠 Categorized from merchant memory — no AI call needed."
        )
        log.info("Quick-add served from merchant memory: %s", text)

    if corrections:
        shown = "\n".join(f"  • {c}" for c in corrections)
        await update.message.reply_text(f"🛡 Auto-corrected:\n{shown}")
        log.info("Quick-add auto-corrections: %s", "; ".join(corrections))

    return await _send_confirm_card(update, ctx, normalized, rates=rates)


@auth
async def quick_confirm(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    response = update.message.text.strip()

    # Category-fix leg: the user is picking a category for a partial parse.
    fix = ctx.user_data.get("quick_fix")
    if fix is not None:
        if response.lower() == "cancel":
            del ctx.user_data["quick_fix"]
            await update.message.reply_text("Cancelled.", reply_markup=ReplyKeyboardRemove())
            return ConversationHandler.END
        lists = ctx.user_data.get("lists") or load_reference_data()
        fix["category"] = response
        valid, reason, normalized, _ = validate_parsed_row(
            fix, lists, max_past_days=MAX_PAST_DAYS
        )
        if not valid:
            if "category" in reason.lower():
                await update.message.reply_text(  # stay — pick from the keyboard
                    "Please pick a category from the keyboard.",
                    reply_markup=_category_keyboard(lists),
                )
                return QUICK_CONFIRM
            del ctx.user_data["quick_fix"]
            await update.message.reply_text(
                f"❌ {reason}\nUse /add to enter it manually.",
                reply_markup=ReplyKeyboardRemove(),
            )
            return ConversationHandler.END
        del ctx.user_data["quick_fix"]
        normalized["description"] = sanitize_description(str(normalized.get("description") or ""))
        return await _send_confirm_card(update, ctx, normalized)

    lowered = response.lower()
    if lowered in ("yes", RECURRING_YES_BUTTON.lower()):
        confirmed = True
    elif lowered == "no":
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
    if lowered == RECURRING_YES_BUTTON.lower():
        parsed["is_recurring"] = True  # user accepted the 🔁 proposal
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
            currency=(parsed.get("currency") or settings.DISPLAY_CURRENCY).upper(),
            transaction_type=parsed.get("type", "Expense"),
            category=parsed.get("category", "Other"),
            person=parsed.get("person", ""),
            description=parsed.get("description", ""),
            is_recurring=bool(parsed.get("is_recurring", False)),
        )
        log.info(
            "User %s quick-add transaction saved: value=%s currency=%s category=%s",
            uid, transaction.value, transaction.currency, transaction.category,
        )
        await append_transaction(transaction)
        log.info("User %s quick-add saved", uid)
        await update.message.reply_text("✅ Saved.", reply_markup=ReplyKeyboardRemove())
        await check_budget_alert(update, transaction.category, ccy, rates)
        await maybe_prompt_cycle_start(update, transaction)
    except Exception as e:
        log.exception("quick_confirm failed for user %s", uid)
        await update.message.reply_text(f"❌ Failed: {e}", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END
