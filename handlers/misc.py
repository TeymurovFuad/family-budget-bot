"""/start, /help, /setcurrency handlers."""

from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import ContextTypes, ConversationHandler

from config import auth, get_display_currency, set_display_currency
from log_decorators import log_call
from data import load_rates
from states import SET_CCY


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
        "/summary — this month at a glance + burn rate\n"
        "/week — last 7 days spending\n"
        "/budget — budget vs actual (all categories)\n"
        "/top — top 5 biggest expenses this month\n"
        "/savings — savings rate last 6 months vs target\n"
        "/report — full monthly report with MoM deltas\n"
        "/rates — exchange rates (/rates refresh for live)\n"
        "/add — log a new transaction\n"
        "/delete — remove one of the last 5 transactions\n"
        "/edit — edit a field on one of the last 10 transactions\n"
        "/bulk — import transactions from a photo, a plain-text file (.txt), or pasted text; review the parsed rows and reply with edits like `2 category=Transport`, then `save` or `cancel`; unfinished drafts resume with /bulk\n"
        "/chart — spending by category as a chart\n"
        "/setcurrency — change display currency\n\n"
        "Or just type naturally: \"groceries 89 PLN\" to quick-add a transaction.\n",
        parse_mode="Markdown",
    )


@auth
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
