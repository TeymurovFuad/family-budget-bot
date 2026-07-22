"""/edit conversation."""

import asyncio
from datetime import datetime, date, timedelta, timezone

from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import ContextTypes, ConversationHandler

from config import auth_write, get_display_currency, log
from log_decorators import log_call
from data import load_rates, load_reference_data, now_utc
from file_storage import get_excel_path_for_reading, get_recent_transactions, update_transaction_field, RowMovedError, _excel_write_lock
from formatters import format_pln_as_currency, format_amount
from states import EDIT_PICK, EDIT_FIELD, EDIT_VALUE, EDIT_CONFIRM

EDIT_FIELD_MAP = {
    "Amount":      "Value",
    "Currency":    "Currency",
    "Category":    "Category",
    "Description": "Description",
    "Date":        "Date",
    "Person":      "Person",
}


@log_call()
@auth_write
async def cmd_edit(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        txns = get_recent_transactions(get_excel_path_for_reading(), n=10)
    except Exception as e:
        await update.message.reply_text(f"❌ {e}"); return
    if not txns:
        await update.message.reply_text("No transactions found."); return

    ctx.user_data["edit_txns"] = txns

    lines = ["Pick a transaction to edit:\n"]
    for i, txn in enumerate(txns, 1):
        raw_val  = txn.get("Value", 0)
        raw_ccy  = txn.get("Currency", "PLN")
        label    = format_amount(raw_val or 0, raw_ccy or "PLN")
        cat      = txn.get("Category", "")
        person   = txn.get("Person", "") or "household"
        desc     = txn.get("Description", "") or ""
        date_str = str(txn.get("Date", ""))[:10]
        lines.append(f"{i}. `{label}` — {cat} / {person} — {desc} ({date_str})")

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
        [["Amount", "Currency", "Category"], ["Description", "Date", "Person"], ["Cancel"]],
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
        keyboard = ReplyKeyboardMarkup([ccy_list[:3], ccy_list[3:], ["Cancel"]], one_time_keyboard=True, resize_keyboard=True)
        await update.message.reply_text(f"Current: `{current}`\nPick new currency:", parse_mode="Markdown", reply_markup=keyboard)
    elif text == "Person":
        persons = load_reference_data().get("persons", [])
        rows = [[p] for p in persons] + [["Nobody", "Cancel"]]
        keyboard = ReplyKeyboardMarkup(rows, one_time_keyboard=True, resize_keyboard=True)
        msg = f"Current: `{current}`\nPick person:" if persons else (
            f"Current: `{current}`\nType a name or tap Nobody.\n\n"
            "_Tip: pre-add family members to the Lists sheet in Excel for quick buttons._"
        )
        await update.message.reply_text(msg, parse_mode="Markdown", reply_markup=keyboard)
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
    if field == "Amount":
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

    try:
        async with _excel_write_lock:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, update_transaction_field, row_idx, excel_col, new_value, expected)
        await update.message.reply_text("✅ Updated.", reply_markup=ReplyKeyboardRemove())
    except RowMovedError:
        log.warning("Edit aborted, row %d moved before it could be applied", row_idx)
        await update.message.reply_text(
            "⚠️ That transaction moved (another edit/delete happened first). Please run /edit again.",
            reply_markup=ReplyKeyboardRemove(),
        )
    except Exception as e:
        log.exception("edit_confirm failed")
        await update.message.reply_text(f"❌ Failed to save: {e}", reply_markup=ReplyKeyboardRemove())
    return ConversationHandler.END
