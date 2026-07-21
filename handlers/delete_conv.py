"""/delete conversation."""

from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import ContextTypes, ConversationHandler

from config import auth, log
from log_decorators import log_call
from excel_ops import async_delete_transaction_row
from file_storage import get_excel_path_for_reading, get_recent_transactions, RowMovedError
from states import DELETE_PICK


@log_call()
@auth
async def cmd_delete(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    try:
        recent = get_recent_transactions(get_excel_path_for_reading(), n=5)
    except FileNotFoundError as e:
        await update.message.reply_text(f"❌ {e}"); return

    if not recent:
        await update.message.reply_text("No transactions found.")
        return

    recent_reversed = list(reversed(recent))
    ctx.user_data["delete_candidates"] = recent_reversed

    lines = ["🗑 *Pick a transaction to delete:*\n"]
    for i, txn in enumerate(recent_reversed, 1):
        raw_date = txn.get("Date", "?")
        date_str = raw_date.strftime("%Y-%m-%d") if hasattr(raw_date, "strftime") else str(raw_date)
        val      = txn.get("Value", "?")
        txn_ccy  = str(txn.get("Currency", "PLN") or "PLN")
        cat      = str(txn.get("Category", "") or "—")
        person   = str(txn.get("Person", "") or "—")
        label    = str(txn.get("Description", "") or cat)
        lines.append(f"{i}. `{val} {txn_ccy}` — {cat} / {person} — {label} ({date_str})")

    lines.append("\nSend the number, or /cancel")
    kb = [[str(i) for i in range(1, len(recent_reversed) + 1)]]
    await update.message.reply_text(
        "\n".join(lines), parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup(kb, one_time_keyboard=True, resize_keyboard=True),
    )
    return DELETE_PICK


@log_call()
@auth
async def delete_pick(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text       = update.message.text.strip()
    candidates = ctx.user_data.get("delete_candidates", [])
    try:
        choice = int(text)
        if choice < 1 or choice > len(candidates):
            raise ValueError
    except ValueError:
        await update.message.reply_text(f"❌ Pick 1–{len(candidates)} or /cancel.")
        return DELETE_PICK

    txn      = candidates[choice - 1]
    row_idx  = txn["_row_idx"]
    expected = {"Date": txn.get("Date"), "Value": txn.get("Value"), "Description": txn.get("Description")}
    try:
        await async_delete_transaction_row(row_idx, expected)
        val   = txn.get("Value", "?")
        d_ccy = str(txn.get("Currency", "PLN") or "PLN")
        label = str(txn.get("Description", "") or txn.get("Category", "") or "—")
        await update.message.reply_text(
            f"✅ Deleted: `{val} {d_ccy}` — {label}",
            parse_mode="Markdown",
            reply_markup=ReplyKeyboardRemove(),
        )
    except RowMovedError:
        log.warning("Delete aborted, row %d moved before it could be applied", row_idx)
        await update.message.reply_text(
            "⚠️ That transaction moved (another edit/delete happened first). Please run /delete again.",
            reply_markup=ReplyKeyboardRemove(),
        )
    except Exception as e:
        log.exception("Failed to delete row %d", row_idx)
        await update.message.reply_text(f"❌ Failed to delete: {e}", reply_markup=ReplyKeyboardRemove())

    ctx.user_data.pop("delete_candidates", None)
    return ConversationHandler.END
