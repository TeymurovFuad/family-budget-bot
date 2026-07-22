"""
config.py — environment, constants, auth, and display-currency state.
All other modules import from here; this module has no project imports.
"""

import logging
from zoneinfo import ZoneInfo

import settings
from telegram import Update
from telegram.ext import ContextTypes

from file_storage import load_user_prefs, save_user_prefs

# ── env ───────────────────────────────────────────────────────────────────────

BOT_TOKEN         = settings.BOT_TOKEN
ALLOWED_USERS: list[int] = settings.ALLOWED_TELEGRAM_IDS
TIMEZONE          = settings.TIMEZONE
_DISPLAY_CURRENCY = settings.DISPLAY_CURRENCY
SAVINGS_TARGET    = settings.SAVINGS_RATE_TARGET

# ── logging ───────────────────────────────────────────────────────────────────
# Single owner of logging setup is logger.init_logging() (called from bot.py
# before this module is imported). Do not call logging.basicConfig here —
# it would install a second console handler and partially override the
# level/format that init_logging() configured on the root logger.

log = logging.getLogger("budget_bot")

if not ALLOWED_USERS:
    raise RuntimeError(
        "ALLOWED_TELEGRAM_IDS is not set — refusing to start with the bot "
        "open to ALL Telegram users. Fix: set ALLOWED_TELEGRAM_IDS in .env to "
        "a comma-separated list of allowed Telegram user IDs (get your ID "
        "from @userinfobot) and restart."
    )

# ── display-currency state ────────────────────────────────────────────────────

_prefs = load_user_prefs()
_runtime_currency: dict[int, str] = {
    int(k): v for k, v in _prefs.get("currency", {}).items()
}


def get_display_currency(user_id: int) -> str:
    return _runtime_currency.get(user_id, _DISPLAY_CURRENCY)


def set_display_currency(user_id: int, ccy: str) -> None:
    _runtime_currency[user_id] = ccy.upper()
    _prefs.setdefault("currency", {})[str(user_id)] = ccy.upper()
    save_user_prefs(_prefs)


# ── duplicate-detection state ─────────────────────────────────────────────────

_last_saved: dict[int, tuple] = {}  # uid → (value, currency, category, datetime)


# ── auth decorator ────────────────────────────────────────────────────────────

def auth(func):
    """Restrict handler to ALLOWED_USERS. Unauthorized users get a reply with their ID."""
    async def wrapper(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        uid = update.effective_user.id
        if uid not in ALLOWED_USERS:
            msg = update.message or (update.callback_query and update.callback_query.message)
            if msg:
                await msg.reply_text(
                    f"⛔ You're not authorized to use this bot. Your Telegram ID is {uid}. "
                    "If you own this bot, add it to ALLOWED_TELEGRAM_IDS in the "
                    "server's .env and restart."
                )
            return
        return await func(update, ctx)
    wrapper.__name__ = func.__name__
    return wrapper


def auth_write(func):
    """
    Restrict handler to the PRIMARY allowed user (ALLOWED_USERS[0]).

    Non-listed users get the same not-authorized reply as `auth`. Listed but
    non-primary users get an owner-only rejection — they can still use every
    @auth (read) command, just not this write-path one.
    """
    async def wrapper(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        uid = update.effective_user.id
        if uid not in ALLOWED_USERS:
            msg = update.message or (update.callback_query and update.callback_query.message)
            if msg:
                await msg.reply_text(
                    f"⛔ You're not authorized to use this bot. Your Telegram ID is {uid}. "
                    "If you own this bot, add it to ALLOWED_TELEGRAM_IDS in the "
                    "server's .env and restart."
                )
            return
        if uid != ALLOWED_USERS[0]:
            msg = update.message or (update.callback_query and update.callback_query.message)
            if msg:
                await msg.reply_text(
                    "⛔ Only the bot owner can make changes. "
                    "You can view reports and data, but not add, edit, or delete."
                )
            return
        return await func(update, ctx)
    wrapper.__name__ = func.__name__
    return wrapper
