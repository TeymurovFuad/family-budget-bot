"""/start, /help, /setcurrency, /export handlers."""

from datetime import datetime, timezone

from telegram import (
    InlineKeyboardButton, InlineKeyboardMarkup, Update,
    ReplyKeyboardMarkup, ReplyKeyboardRemove,
)
from telegram.ext import ContextTypes, ConversationHandler

from config import auth, auth_write, get_display_currency, set_display_currency, log
from log_decorators import log_call
from data import load_budgets, load_rates, load_reference_data
from file_storage import get_excel_path_for_reading, update_category_budget_in_excel
from formatters import format_amount
from validators import parse_amount
from states import SET_CCY, SET_BUDGET_PICK, SET_BUDGET_AMOUNT


@auth
@log_call()
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    name = update.effective_user.first_name
    ccy  = get_display_currency(update.effective_user.id)
    await update.message.reply_text(
        f"👋 Hi *{name}*\\! I'm your *Budget Bot*\\.\n\n"
        f"Currently showing amounts in *{ccy}*\\. "
        f"Use /setcurrency to change\\.\n\n"
        "Try /summary to start\\.",
        parse_mode="MarkdownV2",
    )


@auth
@log_call()
async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ccy = get_display_currency(update.effective_user.id)
    await update.message.reply_text(
        f"📋 *Commands* (showing in {ccy})\n\n"
        "*Add transactions*\n"
        "/add — log one transaction step by step\n"
        "/bulk — import many transactions from photo, file or text; review the parsed rows, reply with edits like `2 category=Transport`, then `save` or `cancel`; unfinished drafts resume with /bulk\n"
        "Or just type naturally: \"groceries 89 PLN\" to quick-add.\n\n"
        "*Reports*\n"
        "/summary — this month at a glance: income, expenses, savings\n"
        "/week — last 7 days of spending by category\n"
        "/budget — budget vs actual for every category\n"
        "/top — top 5 biggest expenses this month\n"
        "/report — full monthly report with month-over-month deltas\n"
        "/chart — spending by category as a chart\n"
        "/range — report for a custom date range\n"
        "/savings — savings rate for the last 6 months vs target\n"
        "/rates — exchange rates (/rates refresh for live)\n\n"
        "*Manage*\n"
        "/edit — edit a field on one of the last 10 transactions\n"
        "/delete — remove one of the last 5 transactions\n"
        "/export — download your Excel workbook\n\n"
        "*Settings*\n"
        "/setcurrency — change the display currency\n"
        "/setbudget — set the monthly budget limit for a category (owner only)\n"
        "/menu — show the button menu\n"
        "/start — welcome message and main menu\n"
        "/help — this list\n",
        parse_mode="Markdown",
    )


@auth_write
@log_call()
async def cmd_setcurrency(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    rates     = load_rates()
    available = sorted(rates.keys())
    current   = get_display_currency(update.effective_user.id)

    if ctx.args:
        ccy = ctx.args[0].upper()
        if ccy in rates:
            set_display_currency(update.effective_user.id, ccy)
            note = "" if ccy == "PLN" else f" (1 {ccy} = {rates[ccy]} PLN)"
            await update.message.reply_text(
                f"✅ Display currency set to *{ccy}*{note}\\.\n"
                f"All amounts will now show in {ccy}\\.",
                parse_mode="MarkdownV2",
            )
        else:
            await update.message.reply_text(
                f"❌ Unknown currency `{ccy}`\\.\n"
                f"Available: {', '.join(available)}\n\n"
                "To add a new currency, update the Lists sheet in Excel\\.",
                parse_mode="MarkdownV2",
            )
        return

    kb = [[c for c in available[i:i+3]] for i in range(0, len(available), 3)]
    await update.message.reply_text(
        f"Current display currency: *{current}*\n\nPick a new one:",
        parse_mode="Markdown",
        reply_markup=ReplyKeyboardMarkup(kb, one_time_keyboard=True, resize_keyboard=True),
    )
    return SET_CCY


@auth
@log_call()
async def cmd_export(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Send the current live Excel workbook back to the requesting user."""
    try:
        excel_path = get_excel_path_for_reading()
        if not excel_path.exists():
            await update.message.reply_text("❌ Workbook not found on the server.")
            return
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        filename = f"Expenses_Improved_{today}.xlsx"
        with open(excel_path, "rb") as fh:
            await update.message.reply_document(document=fh, filename=filename)
    except Exception as e:
        log.exception("Failed to export workbook")
        await update.message.reply_text(f"❌ Could not export the workbook: {e}")


@log_call()
async def setcurrency_pick(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ccy   = update.message.text.strip().upper()
    rates = load_rates()
    if ccy in rates:
        set_display_currency(update.effective_user.id, ccy)
        note = "" if ccy == "PLN" else f"\nRate: 1 {ccy} = {rates[ccy]:.4f} PLN"
        await update.message.reply_text(
            f"✅ Display currency set to *{ccy}*{note}",
            parse_mode="Markdown",
            reply_markup=ReplyKeyboardRemove(),
        )
    else:
        await update.message.reply_text(
            "❌ Not recognised. Try again or /cancel.",
            reply_markup=ReplyKeyboardRemove(),
        )
    return ConversationHandler.END


# ── /setbudget conversation (owner only) ──────────────────────────────────────

def _build_setbudget_keyboard() -> InlineKeyboardMarkup:
    """Build the category picker, 2 buttons per row, each showing the current
    Budget (PLN) value for that category."""
    categories = load_reference_data().get("categories", [])
    budgets = load_budgets()
    buttons = [
        InlineKeyboardButton(
            f"{cat} — {format_amount(budgets.get(cat, 0), 'PLN')}",
            callback_data=f"setbudget:{cat}",
        )
        for cat in categories
    ]
    rows = [buttons[i:i + 2] for i in range(0, len(buttons), 2)]
    return InlineKeyboardMarkup(rows)


@auth_write
@log_call()
async def cmd_setbudget(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "💰 *Set a category budget*\n\nPick a category to update (or /cancel):",
        parse_mode="Markdown",
        reply_markup=_build_setbudget_keyboard(),
    )
    return SET_BUDGET_PICK


@log_call()
async def setbudget_pick(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    category = query.data.split(":", 1)[1]
    budgets = load_budgets()
    current = budgets.get(category, 0)
    ctx.user_data["setbudget_category"] = category
    ctx.user_data["setbudget_current"] = current

    await query.message.reply_text(
        f"*{category}* — currently {format_amount(current, 'PLN')}\\.\n"
        "Send the new monthly budget \\(PLN\\):",
        parse_mode="MarkdownV2",
    )
    return SET_BUDGET_AMOUNT


@log_call()
async def setbudget_amount(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    category = ctx.user_data.get("setbudget_category")
    old_value = ctx.user_data.get("setbudget_current", 0)

    try:
        new_value = parse_amount(update.message.text)
        if new_value < 0:
            raise ValueError
    except (ValueError, TypeError):
        await update.message.reply_text(
            "❌ Please enter a non-negative number for the budget (PLN):"
        )
        return SET_BUDGET_AMOUNT

    try:
        update_category_budget_in_excel(category, new_value)
    except Exception as e:
        log.exception("Failed to update budget for category %s", category)
        await update.message.reply_text(f"❌ Failed to save: {e}")
        return ConversationHandler.END

    await update.message.reply_text(
        f"✅ *{category}* budget: {format_amount(old_value, 'PLN')} → {format_amount(new_value, 'PLN')}",
        parse_mode="Markdown",
    )
    ctx.user_data.pop("setbudget_category", None)
    ctx.user_data.pop("setbudget_current", None)

    await update.message.reply_text(
        "Pick another category to update (or /cancel):",
        reply_markup=_build_setbudget_keyboard(),
    )
    return SET_BUDGET_PICK
