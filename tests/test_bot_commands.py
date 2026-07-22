"""
tests/test_bot_commands.py — Guard against Telegram command-menu drift.

bot.BOT_COMMANDS is published via set_my_commands at startup. These tests
verify it exactly matches the commands actually registered on the Application,
so a new CommandHandler without a menu entry (or a stale menu entry) fails CI.

Importing bot here would import every handler module and bake in the real
@auth decorator before test_handlers_full.py gets a chance to patch it
(alphabetical collection order). So — like test_auth_config.py — the bot
module is inspected in a fresh subprocess and the results come back as JSON.
"""

import json
import os
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Commands that only exist inside conversations (fallbacks / states) and must
# NOT appear in the global Telegram command menu.
CONVERSATION_INTERNAL = {"cancel", "save", "skip"}

_INSPECT_SNIPPET = """
import asyncio, json
from unittest.mock import AsyncMock, MagicMock

from telegram.ext import CommandHandler, ConversationHandler

import bot

registered = set()
app = bot.build_application()
for group in app.handlers.values():
    for handler in group:
        if isinstance(handler, CommandHandler):
            registered |= set(handler.commands)
        elif isinstance(handler, ConversationHandler):
            for entry in handler.entry_points:
                if isinstance(entry, CommandHandler):
                    registered |= set(entry.commands)

fake_app = MagicMock()
fake_app.bot.set_my_commands = AsyncMock()
asyncio.run(bot.register_commands(fake_app))
call_args = fake_app.bot.set_my_commands.await_args
set_my_commands_arg = [c.command for c in call_args.args[0]]

print(json.dumps({
    "registered": sorted(registered),
    "menu": [{"command": c.command, "description": c.description} for c in bot.BOT_COMMANDS],
    "set_my_commands_arg": set_my_commands_arg,
}))
"""


@lru_cache(maxsize=1)
def _inspect_bot() -> dict:
    env = {
        "PATH": os.environ.get("PATH", ""),
        "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
        "TELEGRAM_BOT_TOKEN": "dummy",
        "STORAGE_BACKEND": "local",
        "ALLOWED_TELEGRAM_IDS": "123",
    }
    result = subprocess.run(
        [sys.executable, "-c", _INSPECT_SNIPPET],
        cwd=str(PROJECT_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, f"bot inspection subprocess failed:\n{result.stderr}"
    return json.loads(result.stdout.strip().splitlines()[-1])


def test_menu_matches_registered_handlers():
    """set_my_commands list must exactly match the registered CommandHandlers."""
    data = _inspect_bot()
    registered = set(data["registered"]) - CONVERSATION_INTERNAL
    in_menu = {c["command"] for c in data["menu"]}
    missing_from_menu = registered - in_menu
    stale_in_menu = in_menu - registered
    assert not missing_from_menu, (
        f"Commands registered but missing from BOT_COMMANDS menu: {sorted(missing_from_menu)}"
    )
    assert not stale_in_menu, (
        f"Commands in BOT_COMMANDS menu but not registered: {sorted(stale_in_menu)}"
    )


def test_menu_has_no_duplicates():
    names = [c["command"] for c in _inspect_bot()["menu"]]
    assert len(names) == len(set(names)), "Duplicate commands in BOT_COMMANDS"


def test_descriptions_are_clear_and_within_limits():
    """Telegram requires descriptions between 1 and 256 characters."""
    for c in _inspect_bot()["menu"]:
        assert c["description"].strip(), f"/{c['command']} has an empty description"
        assert 3 <= len(c["description"]) <= 256, (
            f"/{c['command']} description length {len(c['description'])} outside 3..256"
        )


def test_register_commands_publishes_full_menu():
    """register_commands must call bot.set_my_commands with BOT_COMMANDS."""
    data = _inspect_bot()
    assert data["set_my_commands_arg"] == [c["command"] for c in data["menu"]]
