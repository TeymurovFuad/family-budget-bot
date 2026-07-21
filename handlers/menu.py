"""
handlers/menu.py — Persistent bottom keyboard navigation.

Defines three ReplyKeyboardMarkup menus and handlers that route button taps
to the correct command handlers without requiring the user to type commands.
"""

from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import ContextTypes, filters

from config import auth, get_display_currency
from log_decorators import log_call

# ── Keyboard definitions ──────────────────────────────────────────────────────

MAIN_MENU = ReplyKeyboardMarkup(
    [["➕ Add", "📊 Reports", "⚙️ More"]],
    resize_keyboard=True,
    is_persistent=True,
)

REPORTS_MENU = ReplyKeyboardMarkup(
    [
        ["📅 Summary", "📆 Week", "💰 Budget"],
        ["🏆 Top", "💾 Savings", "📋 Report"],
        ["📊 Chart", "📅 Range", "← Back"],
    ],
    resize_keyboard=True,
    is_persistent=True,
)

MORE_MENU = ReplyKeyboardMarkup(
    [
        ["💱 Rates", "🔄 Rates Refresh", "✏️ Edit Last"],
        ["← Back"],
    ],
    resize_keyboard=True,
    is_persistent=True,
)

# ── Helper ────────────────────────────────────────────────────────────────────


@log_call()
async def show_main_menu(update: Update, text: str = "Done. What next?"):
    await update.message.reply_text(text, reply_markup=MAIN_MENU)


# ── /menu command handler ─────────────────────────────────────────────────────


@auth
@log_call()
async def cmd_menu(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    name = update.effective_user.first_name
    ccy  = get_display_currency(update.effective_user.id)
    await update.message.reply_text(
        f"👋 Hi *{name}*! I'm your *Budget Bot*.\n\n"
        f"Currently showing amounts in *{ccy}*. "
        f"Use /setcurrency to change.\n\n"
        "What would you like to do?",
        parse_mode="Markdown",
        reply_markup=MAIN_MENU,
    )


# ── Button tap router ─────────────────────────────────────────────────────────

# Map of button label → keyboard to show (navigation-only buttons)
_NAV_BUTTONS = {
    "📊 Reports": REPORTS_MENU,
    "⚙️ More":    MORE_MENU,
    "← Back":    MAIN_MENU,
}

# Map of button label → command handler function name (resolved lazily to avoid
# circular imports — handlers/reports.py already imports config, data, etc.)
_ACTION_BUTTONS = {
    "📅 Summary":      "cmd_summary",
    "📆 Week":         "cmd_week",
    "💰 Budget":       "cmd_budget",
    "🏆 Top":          "cmd_top",
    "💾 Savings":      "cmd_savings",
    "📋 Report":       "cmd_report",
    "📊 Chart":        "cmd_chart",
    "📅 Range":        "cmd_range",
    "💱 Rates":        "cmd_rates",
    "🔄 Rates Refresh": "cmd_rates_refresh",
    "✏️ Edit Last":    "cmd_edit",
    "➕ Add":          "cmd_add",
}


@auth
@log_call()
async def handle_menu_buttons(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    ctx.user_data.pop("awaiting_range", None)
    text = update.message.text.strip()

    # Navigation-only: show a different keyboard
    if text in _NAV_BUTTONS:
        label = "What would you like to do?" if text == "← Back" else f"{text} — choose:"
        await update.message.reply_text(label, reply_markup=_NAV_BUTTONS[text])
        return

    # Action buttons: delegate to the appropriate command handler
    if text in _ACTION_BUTTONS:
        func_name = _ACTION_BUTTONS[text]

        # Import lazily to avoid circular import at module load time
        if func_name in ("cmd_summary", "cmd_week", "cmd_budget", "cmd_top",
                         "cmd_savings", "cmd_report", "cmd_chart", "cmd_rates",
                         "cmd_range", "cmd_rates_refresh"):
            from handlers.reports import (
                cmd_summary, cmd_week, cmd_budget, cmd_top,
                cmd_savings, cmd_report, cmd_chart, cmd_rates,
                cmd_range, cmd_rates_refresh,
            )
            handlers = {
                "cmd_summary":       cmd_summary,
                "cmd_week":          cmd_week,
                "cmd_budget":        cmd_budget,
                "cmd_top":           cmd_top,
                "cmd_savings":       cmd_savings,
                "cmd_report":        cmd_report,
                "cmd_chart":         cmd_chart,
                "cmd_rates":         cmd_rates,
                "cmd_range":         cmd_range,
                "cmd_rates_refresh": cmd_rates_refresh,
            }
            await handlers[func_name](update, ctx)

        elif func_name == "cmd_edit":
            from handlers.edit_conv import cmd_edit
            await cmd_edit(update, ctx)

        elif func_name == "cmd_add":
            from handlers.add_conv import cmd_add
            await cmd_add(update, ctx)

        return



# ── Custom filter: only match known button texts ──────────────────────────────

_ALL_BUTTON_TEXTS = set(_NAV_BUTTONS) | set(_ACTION_BUTTONS)


class _MenuButtonFilter(filters.MessageFilter):
    """Matches messages whose text is exactly one of the known menu button labels."""

    def filter(self, message):
        return bool(message.text and message.text.strip() in _ALL_BUTTON_TEXTS)


MENU_BUTTON_FILTER = _MenuButtonFilter()
