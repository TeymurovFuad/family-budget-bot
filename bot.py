"""
bot.py — entry point. Wires all handlers and starts the bot.

Run with:  python bot.py

Module layout
─────────────
  config.py          env, auth, display-currency state
  data.py            read-only Excel helpers
  formatters.py      display helpers
  excel_ops.py       async write operations
  states.py          conversation-state constants
  handlers/
    misc.py          /start  /help  /setcurrency
    reports.py       /summary /week /budget /top /savings /report /rates /chart
    add_conv.py      /add  (9-step conversation)
    edit_conv.py     /edit conversation
    delete_conv.py   /delete conversation
    bulk_conv.py     /bulk conversation
    quick_conv.py    NL quick-add
  scheduled.py       APScheduler jobs
  file_storage.py    Excel / GCS / S3 backend
  ai_parser.py       AI provider abstraction (DeepSeek by default)
  models.py          Pydantic models
"""

from logger import init_logging
import settings

# Initialize logging early so other modules get configured handlers
init_logging()

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram import BotCommand
from telegram.ext import (
    Application, CallbackQueryHandler, CommandHandler, ConversationHandler,
    MessageHandler, filters,
)

from config import BOT_TOKEN, TIMEZONE, log
from excel_ops import replay_recovery_queue
from handlers.add_conv import (
    cmd_add, add_value, add_currency, add_type, add_category,
    add_person, add_date, add_desc, add_skip_desc, add_recurring,
    add_confirm, add_cancel,
)
from handlers.bulk_conv import (
    cmd_bulk, bulk_receive, bulk_confirm, bulk_timeout,
    bulk_profile_callback, bulk_profile_name,
    bulk_profile_list_callback,
)
from handlers.cycle import cmd_cycle, handle_cycle_callback, handle_detect_callback, handle_detect_text
from handlers.delete_conv import cmd_delete, delete_pick
from handlers.edit_conv import (
    cmd_edit, edit_pick, edit_field, edit_value, edit_confirm,
)
from handlers.menu import cmd_menu, handle_menu_buttons, MENU_BUTTON_FILTER
from handlers.misc import (
    cmd_help, cmd_setcurrency, cmd_export, setcurrency_pick,
    cmd_setbudget, setbudget_pick, setbudget_amount,
)
from handlers.quick_conv import handle_quick_add, quick_confirm
from handlers.reports import (
    cmd_summary, cmd_week, cmd_budget, cmd_top,
    cmd_savings, cmd_report, cmd_rates, cmd_chart,
    cmd_range, handle_range_callback, handle_range_text,
)
from scheduled import (
    send_weekly_report, send_monthly_summary,
    send_daily_reminder, send_weekly_nudge,
)
from states import (
    ADD_VALUE, ADD_CURRENCY, ADD_TYPE, ADD_CATEGORY,
    ADD_PERSON, ADD_DATE, ADD_DESC, ADD_RECURRING, ADD_CONFIRM,
    DELETE_PICK, SET_CCY,
    EDIT_PICK, EDIT_FIELD, EDIT_VALUE, EDIT_CONFIRM,
    BULK_RECEIVE, BULK_CONFIRM,
    BULK_PROFILE_CONFIRM, BULK_PROFILE_NAME, BULK_PROFILE_FIX_COL, BULK_PROFILE_FIX_FIELD,
    QUICK_CONFIRM,
    SET_BUDGET_PICK, SET_BUDGET_AMOUNT,
)



# ── Conversation timeouts (seconds) ──────────────────────────────────────────
EDIT_TIMEOUT_SECONDS        = 5 * 60    # /edit — short guided flow
BULK_REVIEW_TIMEOUT_SECONDS = 30 * 60   # /bulk — reviewing 100+ parsed rows takes time
QUICK_CONFIRM_TIMEOUT_SECONDS = 60      # quick-add — single yes/no confirmation


# ── Telegram command menu (the "/" button) ────────────────────────────────────
# Every user-facing command, ordered by frequency of use. Registered at startup
# via set_my_commands — no manual BotFather step needed. Conversation-internal
# commands (/cancel, /skip, /save) are deliberately excluded.
BOT_COMMANDS = [
    BotCommand("summary",     "This month at a glance: income, expenses, savings"),
    BotCommand("add",         "Log one transaction step by step"),
    BotCommand("bulk",        "Import many transactions from photo, file or text"),
    BotCommand("week",        "Last 7 days of spending by category"),
    BotCommand("budget",      "Budget vs actual for every category"),
    BotCommand("top",         "Top 5 biggest expenses this month"),
    BotCommand("report",      "Full monthly report with month-over-month deltas"),
    BotCommand("chart",       "Spending by category as a chart"),
    BotCommand("range",       "Report for a custom date range"),
    BotCommand("savings",     "Savings rate for the last 6 months vs target"),
    BotCommand("rates",       "Exchange rates (add 'refresh' for live rates)"),
    BotCommand("edit",        "Edit a field on one of the last 10 transactions"),
    BotCommand("delete",      "Remove one of the last 5 transactions"),
    BotCommand("export",      "Download your Excel workbook"),
    BotCommand("setcurrency", "Change the display currency"),
    BotCommand("setbudget",   "Set the monthly budget for a category (owner only)"),
    BotCommand("cycle",       "Show or start a budget cycle (owner only, needs BUDGET_CYCLE=1)"),
    BotCommand("menu",        "Show the button menu"),
    BotCommand("help",        "List all commands with what they do"),
    BotCommand("start",       "Welcome message and main menu"),
]


async def register_commands(app: Application) -> None:
    """post_init hook: publish the command menu so Telegram shows it on '/'."""
    await app.bot.set_my_commands(BOT_COMMANDS)
    log.info("Registered %d bot commands with Telegram", len(BOT_COMMANDS))


def build_application() -> Application:
    """Build the Application and wire every handler. Split from main() so tests
    can inspect the registered handlers without starting the bot."""
    app = Application.builder().token(BOT_TOKEN).post_init(register_commands).build()

    # ── command handlers ──────────────────────────────────────────────────────
    app.add_handler(CommandHandler("start",   cmd_menu))
    app.add_handler(CommandHandler("menu",    cmd_menu))
    app.add_handler(CommandHandler("help",    cmd_help))
    app.add_handler(CommandHandler("summary", cmd_summary))
    app.add_handler(CommandHandler("week",    cmd_week))
    app.add_handler(CommandHandler("budget",  cmd_budget))
    app.add_handler(CommandHandler("top",     cmd_top))
    app.add_handler(CommandHandler("savings", cmd_savings))
    app.add_handler(CommandHandler("report",  cmd_report))
    app.add_handler(CommandHandler("rates",   cmd_rates))
    app.add_handler(CommandHandler("chart",   cmd_chart))
    app.add_handler(CommandHandler("range",   cmd_range))
    app.add_handler(CommandHandler("export",  cmd_export))
    app.add_handler(CommandHandler("cycle",   cmd_cycle))

    # ── profile list / delete inline callbacks (global — outside any conversation) ──
    app.add_handler(CallbackQueryHandler(bulk_profile_list_callback, pattern="^profile_del[_:]"))

    # ── range report inline callback ──────────────────────────────────────────
    app.add_handler(CallbackQueryHandler(handle_range_callback, pattern="^range:"))

    # ── budget-cycle boundary confirmation callback ───────────────────────────
    app.add_handler(CallbackQueryHandler(handle_cycle_callback, pattern="^cycle:"))

    # ── cycle detect inline callbacks ─────────────────────────────────────────
    app.add_handler(CallbackQueryHandler(handle_detect_callback, pattern="^detect:"))

    # ── custom range text input ───────────────────────────────────────────────
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        handle_range_text,
    ), group=1)

    # ── cycle detect custom-date text input ───────────────────────────────────
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        handle_detect_text,
    ), group=2)

    # ── /setcurrency conversation ─────────────────────────────────────────────
    app.add_handler(ConversationHandler(
        entry_points=[CommandHandler("setcurrency", cmd_setcurrency)],
        states={SET_CCY: [MessageHandler(filters.TEXT & ~filters.COMMAND, setcurrency_pick)]},
        fallbacks=[CommandHandler("cancel", add_cancel)],
    ))

    # ── /setbudget conversation ───────────────────────────────────────────────
    app.add_handler(ConversationHandler(
        entry_points=[CommandHandler("setbudget", cmd_setbudget)],
        states={
            SET_BUDGET_PICK:   [CallbackQueryHandler(setbudget_pick, pattern="^setbudget:")],
            SET_BUDGET_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, setbudget_amount)],
        },
        fallbacks=[CommandHandler("cancel", add_cancel)],
    ))

    # ── /add conversation ─────────────────────────────────────────────────────
    app.add_handler(ConversationHandler(
        entry_points=[CommandHandler("add", cmd_add)],
        states={
            ADD_VALUE:     [MessageHandler(filters.TEXT & ~filters.COMMAND, add_value)],
            ADD_CURRENCY:  [MessageHandler(filters.TEXT & ~filters.COMMAND, add_currency)],
            ADD_TYPE:      [MessageHandler(filters.TEXT & ~filters.COMMAND, add_type)],
            ADD_CATEGORY:  [MessageHandler(filters.TEXT & ~filters.COMMAND, add_category)],
            ADD_PERSON:    [MessageHandler(filters.TEXT & ~filters.COMMAND, add_person)],
            ADD_DATE:      [MessageHandler(filters.TEXT & ~filters.COMMAND, add_date)],
            ADD_DESC:      [
                CommandHandler("skip", add_skip_desc),
                MessageHandler(filters.TEXT & ~filters.COMMAND, add_desc),
            ],
            ADD_RECURRING: [MessageHandler(filters.TEXT & ~filters.COMMAND, add_recurring)],
            ADD_CONFIRM:   [MessageHandler(filters.TEXT & ~filters.COMMAND, add_confirm)],
        },
        fallbacks=[CommandHandler("cancel", add_cancel)],
    ))

    # ── /delete conversation ──────────────────────────────────────────────────
    app.add_handler(ConversationHandler(
        entry_points=[CommandHandler("delete", cmd_delete)],
        states={DELETE_PICK: [MessageHandler(filters.TEXT & ~filters.COMMAND, delete_pick)]},
        fallbacks=[CommandHandler("cancel", add_cancel)],
    ))

    # ── /edit conversation ────────────────────────────────────────────────────
    app.add_handler(ConversationHandler(
        entry_points=[CommandHandler("edit", cmd_edit)],
        states={
            EDIT_PICK:    [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_pick)],
            EDIT_FIELD:   [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_field)],
            EDIT_VALUE:   [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_value)],
            EDIT_CONFIRM: [MessageHandler(filters.TEXT & ~filters.COMMAND, edit_confirm)],
        },
        fallbacks=[CommandHandler("cancel", add_cancel)],
        conversation_timeout=EDIT_TIMEOUT_SECONDS,
    ))

    # ── /bulk conversation ────────────────────────────────────────────────────
    app.add_handler(ConversationHandler(
        entry_points=[CommandHandler("bulk", cmd_bulk)],
        states={
            BULK_RECEIVE: [MessageHandler(
                filters.PHOTO | filters.Document.ALL | (filters.TEXT & ~filters.COMMAND),
                bulk_receive,
            )],
            BULK_CONFIRM: [
                # /save and /cancel must reach bulk_confirm — users type them
                # with the slash even though the keyboard sends plain text.
                CommandHandler("save", bulk_confirm),
                CommandHandler("cancel", bulk_confirm),
                MessageHandler(filters.TEXT & ~filters.COMMAND, bulk_confirm),
            ],
            BULK_PROFILE_CONFIRM: [CallbackQueryHandler(bulk_profile_callback)],
            BULK_PROFILE_FIX_COL: [CallbackQueryHandler(bulk_profile_callback)],
            BULK_PROFILE_FIX_FIELD: [CallbackQueryHandler(bulk_profile_callback)],
            BULK_PROFILE_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, bulk_profile_name),
            ],
            ConversationHandler.TIMEOUT: [
                MessageHandler(filters.ALL, bulk_timeout),
            ],
        },
        fallbacks=[CommandHandler("cancel", add_cancel)],
        conversation_timeout=BULK_REVIEW_TIMEOUT_SECONDS,
    ))

    # ── menu button tap handler (must be before quick-add) ───────────────────
    app.add_handler(MessageHandler(MENU_BUTTON_FILTER, handle_menu_buttons))

    # ── quick NL-add conversation ─────────────────────────────────────────────
    app.add_handler(ConversationHandler(
        entry_points=[MessageHandler(filters.TEXT & ~filters.COMMAND, handle_quick_add)],
        states={QUICK_CONFIRM: [MessageHandler(filters.TEXT & ~filters.COMMAND, quick_confirm)]},
        fallbacks=[CommandHandler("cancel", add_cancel)],
        conversation_timeout=QUICK_CONFIRM_TIMEOUT_SECONDS,
    ))

    return app


def main():
    if not BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN not set in .env")

    replay_recovery_queue()
    log.info("Using storage backend=%s, xlsx_path=%s", settings.STORAGE_BACKEND, settings.XLSX_PATH)

    app = build_application()

    # ── scheduler ─────────────────────────────────────────────────────────────
    scheduler = AsyncIOScheduler(timezone=str(TIMEZONE))
    scheduler.add_job(send_weekly_report,   "cron", day_of_week="sun", hour=18, minute=0, args=[app])
    scheduler.add_job(send_monthly_summary, "cron", day=1,             hour=8,  minute=0, args=[app])
    scheduler.add_job(send_daily_reminder,  "cron", hour=21, minute=0, timezone=TIMEZONE, args=[app])
    scheduler.add_job(send_weekly_nudge,    "cron", day_of_week="sun", hour=9, minute=0, timezone=TIMEZONE, args=[app])
    scheduler.start()

    log.info("Bot starting — polling")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
