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
ALLOWED_USERS: set[int] = settings.ALLOWED_TELEGRAM_IDS
ALLOW_ALL_USERS   = settings.ALLOW_ALL_USERS
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
    if not ALLOW_ALL_USERS:
        raise RuntimeError(
            "ALLOWED_TELEGRAM_IDS is not set — refusing to start with the bot "
            "open to ALL Telegram users. Set ALLOWED_TELEGRAM_IDS to a "
            "comma-separated list of allowed user IDs, or set ALLOW_ALL_USERS=1 "
            "to explicitly opt in to an open bot."
        )
    log.warning("ALLOWED_TELEGRAM_IDS is not set — bot is open to ALL users")

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
    """Restrict handler to ALLOWED_USERS. Empty set → everyone allowed (testing)."""
    async def wrapper(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        uid = update.effective_user.id
        if ALLOWED_USERS and uid not in ALLOWED_USERS:
            msg = update.message or (update.callback_query and update.callback_query.message)
            if msg:
                await msg.reply_text("⛔ Not authorised.")
            return
        return await func(update, ctx)
    wrapper.__name__ = func.__name__
    return wrapper
