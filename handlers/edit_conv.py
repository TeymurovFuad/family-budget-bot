"""/edit conversation."""

import asyncio
from datetime import datetime, date, timedelta, timezone

from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import ContextTypes, ConversationHandler

from config import auth_write, get_display_currency, log
from log_decorators import log_call
from data import now_utc
from storage_facade import (
    RowMismatchError, RowMovedError, get_recent_transactions, load_rates,
    load_reference_data, update_transaction_field,
)
from formatters import format_base_as_currency, format_amount, sanitize_description
from models import MONTH_NAMES
from states import EDIT_PICK, EDIT_FIELD, EDIT_VALUE, EDIT_CONFIRM
import settings

EDIT_FIELD_MAP = {
    "Amount":      "Value",
    "Currency":    "Currency",
    "Category":    "Category",
    "Description": "Description",
    "Date":        "Date",
}


@log_call()
@auth_write
async def cmd_edit(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if ctx.args and ctx.args[0].lower() == "help":
        await update.message.reply_text(
            "✏️ */edit* — Edit a transaction\n\n"
            "Shows the last 10 transactions\\. Pick one by number, then choose a field to change: Amount, Currency, Category, Description, or Date\\.",
            parse_mode="MarkdownV2",
        )
        return ConversationHandler.END

    try:
        # SQLite-sourced: each row's _row_idx is the real SQLite id, the same
        # keyspace update_transaction_field expects at confirm time.
        txns = get_recent_transactions(n=10)
    except Exception as e:
        await update.message.reply_text(f"❌ {e}"); return
    if not txns:
        await update.message.reply_text("No transactions found."); return

    ctx.user_data["edit_txns"] = txns

    lines = ["Pick a transaction to edit:\n"]
    for i, txn in enumerate(txns, 1):
        raw_val  = txn.get("Value", 0)
        raw_ccy  = txn.get("Currency") or settings.DISPLAY_CURRENCY
        label    = format_amount(raw_val or 0, raw_ccy or settings.DISPLAY_CURRENCY)
        cat      = txn.get("Category", "")
        desc     = txn.get("Description", "") or ""
        date_str = str(txn.get("Date", ""))[:10]
        lines.append(f"{i}. `{label}` — {cat} — {desc} ({date_str})")

    keyboard = ReplyKeyboardMarkup(
        [[str(i) for i in range(1, 6)], [str(i) for i in range(6, 11)], ["Cancel"]],
        one_time_keyboard=True, resize_keyboard=True,
    )
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown", reply_markup=keyboard)
    return EDIT_PICK


@log_call()
async def edit_pick(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text.lower() == "cancel":
        await update.message.reply_text("Cancelled.", reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END
    if not text.isdigit() or not (1 <= int(text) <= len(ctx.user_data.get("edit_txns", []))):
        await update.message.reply_text("Pick a number from the list.")
        return EDIT_PICK
    idx = int(text) - 1
    ctx.user_data["edit_idx"] = idx
    ctx.user_data["edit_txn"] = ctx.user_data["edit_txns"][idx]
    keyboard = ReplyKeyboardMarkup(
        [["Amount", "Currency", "Category"], ["Description", "Date"], ["Cancel"]],
        one_time_keyboard=True, resize_keyboard=True,
    )
    await update.message.reply_text("Which field do you want to change?", reply_markup=keyboard)
    return EDIT_FIELD


@log_call()
async def edit_field(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text.lower() == "cancel":
        await update.message.reply_text("Cancelled.", reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END
    if text not in EDIT_FIELD_MAP:
        await update.message.reply_text("Pick a field from the keyboard.")
        return EDIT_FIELD
    ctx.user_data["edit_field"] = text
    current = ctx.user_data["edit_txn"].get(EDIT_FIELD_MAP[text], "")

    if text == "Category":
        cats = load_reference_data().get("categories", [])
        keyboard = ReplyKeyboardMarkup([[c] for c in cats] + [["Cancel"]], one_time_keyboard=True, resize_keyboard=True)
        await update.message.reply_text(f"Current: `{current}`\nPick new category:", parse_mode="Markdown", reply_markup=keyboard)
    elif text == "Currency":
        ccy_list = sorted(load_rates().keys())
        # Rows derived from the actual currency count (2 per row) — a fixed
        # 3-column split breaks whenever there aren't exactly 6 currencies.
        rows = [ccy_list[i:i + 2] for i in range(0, len(ccy_list), 2)]
        keyboard = ReplyKeyboardMarkup(rows + [["Cancel"]], one_time_keyboard=True, resize_keyboard=True)
        await update.message.reply_text(f"Current: `{current}`\nPick new currency:", parse_mode="Markdown", reply_markup=keyboard)
    else:
        await update.message.reply_text(f"Current: `{current}`\nEnter new value:", parse_mode="Markdown", reply_markup=ReplyKeyboardRemove())
    return EDIT_VALUE


@log_call()
async def edit_value(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text.lower() == "cancel":
        await update.message.reply_text("Cancelled.", reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END

    field   = ctx.user_data["edit_field"]
    current = ctx.user_data["edit_txn"].get(EDIT_FIELD_MAP[field], "")

    new_value = text
    if field == "Description":
        new_value = sanitize_description(text)
    elif field == "Amount":
        try:
            new_value = float(text.replace(",", "."))
            if new_value <= 0:
                raise ValueError
        except ValueError:
            await update.message.reply_text("Enter a positive number.")
            return EDIT_VALUE
    elif field == "Date":
        if text.lower() == "today":
            new_value = datetime.now(timezone.utc).date()
        elif text.lower() == "yesterday":
            new_value = datetime.now(timezone.utc).date() - timedelta(days=1)
        else:
            try:
                new_value = date.fromisoformat(text)
                if new_value > now_utc().date():
                    await update.message.reply_text("Date cannot be in the future.")
                    return EDIT_VALUE
            except ValueError:
                await update.message.reply_text("Use YYYY-MM-DD, 'today', or 'yesterday'.")
                return EDIT_VALUE

    ctx.user_data["edit_new_value"] = new_value
    await update.message.reply_text(
        f"Change *{field}* from `{current}` to `{new_value}`?",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup([["Yes", "No"]], one_time_keyboard=True, resize_keyboard=True),
    )
    return EDIT_CONFIRM


@log_call()
async def edit_confirm(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.message.text.strip().lower() != "yes":
        await update.message.reply_text("Cancelled.", reply_markup=ReplyKeyboardRemove())
        return ConversationHandler.END

    txn       = ctx.user_data["edit_txn"]
    field     = ctx.user_data["edit_field"]
    new_value = ctx.user_data["edit_new_value"]
    row_idx   = txn["_row_idx"]
    excel_col = EDIT_FIELD_MAP[field]
    expected  = {"Date": txn.get("Date"), "Value": txn.get("Value"), "Description": txn.get("Description")}

    # Reports filter on Year/Month — when the Date changes, recompute both in
    # the same atomic write so a re-dated row doesn't keep counting in its old
    # month. This domain rule lives here, not in the storage layer.
    if excel_col == "Date" and hasattr(new_value, "year") and hasattr(new_value, "month"):
        updates = {
            "Date": new_value,
            "Year": new_value.year,
            "Month": MONTH_NAMES[new_value.month - 1],
        }
    else:
        updates = {excel_col: new_value}

    try:
        # storage_facade.update_transaction_field is sync (SQLite handles its
        # own locking) — run it in the executor to keep the event loop free.
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, update_transaction_field, row_idx, updates, None, expected)
        await update.message.reply_text("✅ Updated.", reply_markup=ReplyKeyboardRemove())
    except (RowMovedError, RowMismatchError):
        log.warning("Edit aborted, row %d moved before it could be applied", row_idx)
        await update.message.reply_text(
            "⚠️ That transaction moved (another edit/delete happened first). Please run /edit again.",
            reply_markup=ReplyKeyboardRemove(),
        )
    except Exception as e:
        log.exception("edit_confirm failed")
        await update.message.reply_text(f"❌ Failed to save: {e}", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END
