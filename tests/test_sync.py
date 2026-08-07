"""
test_sync.py — on-demand Excel sync: storage facade helpers,
web endpoint (GET /settings, POST /settings/sync),
and the /sync Telegram bot command.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

import settings
import sqlite_ops
import storage_facade

PASSWORD = "hunter2"


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "SQLITE_DB_PATH", tmp_path / "sync_test.db")
    conn = sqlite_ops.init_db(settings.SQLITE_DB_PATH)
    yield conn
    conn.close()


@pytest.fixture()
def web_client(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "WEB_PASSWORD", PASSWORD)
    monkeypatch.setattr(settings, "WEB_SESSION_SECRET", "s3cret")
    monkeypatch.setattr(settings, "SQLITE_DB_PATH", tmp_path / "web_sync.db")
    sqlite_ops.init_db(settings.SQLITE_DB_PATH).close()

    from fastapi.testclient import TestClient
    from web.app import create_app
    c = TestClient(create_app())
    c.post("/login", data={"password": PASSWORD}, follow_redirects=False)
    return c


# ── get_last_export_time ──────────────────────────────────────────────────────

def test_get_last_export_time_returns_none_when_empty(db):
    assert storage_facade.get_last_export_time() is None


def test_get_last_export_time_returns_ts_after_export(db):
    from sqlite_types import SyncDirection, SyncStatus
    sqlite_ops.log_sync(db, SyncDirection.EXPORT, SyncStatus.OK, "test export")
    result = storage_facade.get_last_export_time()
    assert result is not None
    assert len(result) >= 19  # ISO ts with at least YYYY-MM-DDTHH:MM:SS


# ── web: GET /settings ────────────────────────────────────────────────────────

def test_settings_page_returns_200(web_client):
    resp = web_client.get("/settings")
    assert resp.status_code == 200
    assert "Sync to Excel" in resp.text


def test_settings_page_shows_never_when_no_export(web_client):
    resp = web_client.get("/settings")
    assert "Never" in resp.text


# ── web: POST /settings/sync ──────────────────────────────────────────────────

def test_settings_sync_calls_trigger_and_returns_fragment(web_client):
    with patch("web.routes.settings.trigger_excel_export", new_callable=AsyncMock) as mock_export, \
         patch("web.routes.settings.get_last_export_time", return_value="2025-01-15T12:00:00+00:00"):
        resp = web_client.post("/settings/sync")
    assert resp.status_code == 200
    mock_export.assert_called_once()
    assert "Last synced" in resp.text


def test_settings_sync_returns_error_fragment_on_failure(web_client):
    async def _fail():
        raise RuntimeError("disk full")

    with patch("web.routes.settings.trigger_excel_export", side_effect=_fail), \
         patch("web.routes.settings.get_last_export_time", return_value=None):
        resp = web_client.post("/settings/sync")
    assert resp.status_code == 200
    assert "Sync failed" in resp.text


# ── /sync bot command ─────────────────────────────────────────────────────────

def _make_update():
    """Build a minimal fake Telegram Update with a mocked reply_text."""
    msg = MagicMock()
    msg.reply_text = AsyncMock()
    sent = MagicMock()
    sent.edit_text = AsyncMock()
    msg.reply_text.return_value = sent
    update = MagicMock()
    update.message = msg
    return update, sent


@pytest.mark.asyncio
async def test_cmd_sync_success():
    import config
    import handlers.misc as misc_mod

    # Bypass auth decorators — this test exercises the command logic only.
    with patch.object(config, "auth_write", lambda f: f):
        import importlib
        importlib.reload(misc_mod)
        cmd_sync_bare = misc_mod.cmd_sync

    update, sent = _make_update()
    ctx = MagicMock()

    with patch("storage_facade.trigger_excel_export", new_callable=AsyncMock), \
         patch("storage_facade.get_last_export_time", return_value="2025-01-15T12:00:00"):
        await cmd_sync_bare(update, ctx)

    text = sent.edit_text.call_args[0][0]
    assert "Export complete" in text


@pytest.mark.asyncio
async def test_cmd_sync_failure():
    import config
    import handlers.misc as misc_mod

    with patch.object(config, "auth_write", lambda f: f):
        import importlib
        importlib.reload(misc_mod)
        cmd_sync_bare = misc_mod.cmd_sync

    update, sent = _make_update()
    ctx = MagicMock()

    async def _fail():
        raise RuntimeError("no template")

    with patch("storage_facade.trigger_excel_export", side_effect=_fail):
        await cmd_sync_bare(update, ctx)

    text = sent.edit_text.call_args[0][0]
    assert "Sync failed" in text
