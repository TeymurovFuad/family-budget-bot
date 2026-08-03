"""/delete conversation."""

import asyncio

from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import ContextTypes, ConversationHandler

from config import auth, auth_write, log
from log_decorators import log_call
from storage_facade import RowMismatchError, RowMovedError, delete_transaction_row, get_recent_transactions
from states import DELETE_PICK
import settings


@log_call()
@auth_write
async def cmd_delete(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if ctx.args and ctx.args[0].lower() == "help":
        await update.message.reply_text(
            "🗑 */delete* — Delete a transaction\n\n"
            "Shows the last 5 transactions\\. Pick one by number to remove it permanently\\.",
            parse_mode="MarkdownV2",
        )
        return ConversationHandler.END

    try:
        # SQLite-sourced: each row's _row_idx is the real SQLite id, the same
        # keyspace delete_transaction_row expects at pick time.
        recent = get_recent_transactions(n=5)
    except Exception as e:
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
        txn_ccy  = str(txn.get("Currency") or settings.DISPLAY_CURRENCY)
        cat      = str(txn.get("Category", "") or "—")
        label    = str(txn.get("Description", "") or cat)
        lines.append(f"{i}. `{val} {txn_ccy}` — {cat} — {label} ({date_str})")

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
        # storage_facade.delete_transaction_row is sync (SQLite) — run it in
        # the executor so the async handler never blocks the event loop
        # (same pattern edit_conv uses for update_transaction_field).
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, delete_transaction_row, row_idx, expected)
        val   = txn.get("Value", "?")
        d_ccy = str(txn.get("Currency") or settings.DISPLAY_CURRENCY)
        label = str(txn.get("Description", "") or txn.get("Category", "") or "—")
        await update.message.reply_text(
            f"✅ Deleted: `{val} {d_ccy}` — {label}",
            parse_mode="Markdown",
            reply_markup=ReplyKeyboardRemove(),
        )
    except (RowMovedError, RowMismatchError):
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
