"""
tests/test_auth_config.py — Auth fail-closed behavior for config.py / settings.py,
and the @auth decorator's rejection reply.

config.py raises RuntimeError at IMPORT time when ALLOWED_TELEGRAM_IDS is empty.
Because that check runs at module import, the startup scenarios are exercised in
a fresh subprocess so we don't fight Python's module cache or leak state between
tests.
"""

import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import config as _config

# Capture the REAL auth decorator at import time: test_handlers_full.py starts a
# module-level patch that replaces config.auth with a pass-through, and that
# patch is active while other tests run. This module imports before it
# (alphabetical collection order), so the reference below is the real thing.
_REAL_AUTH = _config.auth

_IMPORT_CONFIG_SNIPPET = "import config"


def _run(env_overrides: dict[str, str]) -> subprocess.CompletedProcess:
    # NOTE: every auth-relevant env var is set EXPLICITLY here. settings.py calls
    # load_dotenv(), which does NOT override variables already present in the
    # environment — so a developer's local .env cannot leak into these tests and
    # flip their outcome.
    env = {
        "PATH": os.environ.get("PATH", ""),
        "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
        "TELEGRAM_BOT_TOKEN": "dummy",
        "STORAGE_BACKEND": "local",
        "ALLOWED_TELEGRAM_IDS": "",
    }
    env.update(env_overrides)
    return subprocess.run(
        [sys.executable, "-c", _IMPORT_CONFIG_SNIPPET],
        cwd=str(PROJECT_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_empty_allowed_ids_fails_closed():
    """No ALLOWED_TELEGRAM_IDS → startup must fail with actionable guidance."""
    result = _run({"ALLOWED_TELEGRAM_IDS": ""})
    assert result.returncode != 0
    assert "RuntimeError" in result.stderr
    assert "ALLOWED_TELEGRAM_IDS" in result.stderr
    assert ".env" in result.stderr
    assert "@userinfobot" in result.stderr


def test_non_empty_allowed_ids_unaffected():
    """Normal configuration (non-empty ALLOWED_TELEGRAM_IDS) starts cleanly."""
    result = _run({"ALLOWED_TELEGRAM_IDS": "123,456"})
    assert result.returncode == 0, result.stderr


@pytest.mark.asyncio
async def test_auth_rejects_unauthorized_user_with_their_id(monkeypatch):
    """An unauthorized update gets a rejection reply containing the user's own ID."""
    monkeypatch.setattr(_config, "ALLOWED_USERS", {999})

    handler = AsyncMock()
    handler.__name__ = "handler"
    wrapped = _REAL_AUTH(handler)

    update = MagicMock()
    update.effective_user.id = 424242
    update.message.reply_text = AsyncMock()

    await wrapped(update, MagicMock())

    handler.assert_not_awaited()
    update.message.reply_text.assert_awaited_once()
    reply = update.message.reply_text.call_args[0][0]
    assert "not authorized" in reply.lower()
    assert "424242" in reply
    assert "ALLOWED_TELEGRAM_IDS" in reply
