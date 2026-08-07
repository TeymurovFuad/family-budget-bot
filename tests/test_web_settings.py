"""
test_web_settings.py — route-level tests for the /settings page:
categories (list/add/rename/budget), persons (list/add), display currency,
and exchange-rate refresh.
"""

import pytest
from unittest.mock import AsyncMock, patch

import settings
import sqlite_ops

PASSWORD = "hunter2"


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "WEB_PASSWORD", PASSWORD)
    monkeypatch.setattr(settings, "WEB_SESSION_SECRET", "s3cret")
    monkeypatch.setattr(settings, "SQLITE_DB_PATH", tmp_path / "settings_test.db")
    monkeypatch.setattr(settings, "ALLOWED_TELEGRAM_IDS", [12345])
    # Patch Excel write functions so tests don't need a real .xlsx file.
    monkeypatch.setattr(
        "file_storage.append_category_to_lists_sheet", lambda name: None)
    monkeypatch.setattr(
        "file_storage.rename_category_in_lists_sheet", lambda old, new: None)
    monkeypatch.setattr(
        "file_storage.append_person_to_lists_sheet", lambda name: None)
    monkeypatch.setattr(
        "file_storage.update_category_budget_in_excel", lambda cat, budget: None)

    conn = sqlite_ops.init_db(settings.SQLITE_DB_PATH)
    sqlite_ops.upsert_category(conn, "Groceries", budget_base=500.0)
    sqlite_ops.upsert_category(conn, "Fun")
    sqlite_ops.upsert_person(conn, "Alice")
    sqlite_ops.upsert_rate(conn, "USD", 4.0)
    sqlite_ops.upsert_rate(conn, "EUR", 4.3)
    conn.close()

    from fastapi.testclient import TestClient
    from web.app import create_app
    c = TestClient(create_app())
    c.post("/login", data={"password": PASSWORD}, follow_redirects=False)
    return c


# ── Authentication guard ───────────────────────────────────────────────────────

def test_settings_unauthenticated_redirects(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "WEB_PASSWORD", PASSWORD)
    monkeypatch.setattr(settings, "WEB_SESSION_SECRET", "s3cret")
    monkeypatch.setattr(settings, "SQLITE_DB_PATH", tmp_path / "auth_test.db")
    sqlite_ops.init_db(settings.SQLITE_DB_PATH).close()
    from fastapi.testclient import TestClient
    from web.app import create_app
    c = TestClient(create_app(), follow_redirects=False)
    resp = c.get("/settings")
    assert resp.status_code == 303


# ── Full page load ─────────────────────────────────────────────────────────────

def test_settings_page_renders_all_sections(client):
    resp = client.get("/settings")
    assert resp.status_code == 200
    assert "Categories" in resp.text
    assert "Persons" in resp.text
    assert "Display Currency" in resp.text
    assert "<html" in resp.text  # full page, not a fragment


def test_settings_page_shows_existing_data(client):
    resp = client.get("/settings")
    assert resp.status_code == 200
    assert "Groceries" in resp.text
    assert "Fun" in resp.text
    assert "Alice" in resp.text


# ── Categories — add ──────────────────────────────────────────────────────────

def test_add_category_valid(client):
    resp = client.post("/settings/categories/add", data={"name": "Transport"})
    assert resp.status_code == 200
    assert "Transport" in resp.text


def test_add_category_empty_name_returns_error(client):
    resp = client.post("/settings/categories/add", data={"name": ""})
    assert resp.status_code == 200
    assert "error-msg" in resp.text or "cannot be empty" in resp.text.lower()


def test_add_category_duplicate_returns_error(client):
    resp = client.post("/settings/categories/add", data={"name": "Groceries"})
    assert resp.status_code == 200
    assert "already exists" in resp.text.lower() or "error-msg" in resp.text


# ── Categories — rename form ───────────────────────────────────────────────────

def test_rename_form_returns_input(client):
    resp = client.get("/settings/categories/Groceries/rename-form")
    assert resp.status_code == 200
    assert 'name="new_name"' in resp.text
    assert "Groceries" in resp.text


# ── Categories — rename ───────────────────────────────────────────────────────

def test_rename_category_valid(client):
    resp = client.post("/settings/categories/Groceries/rename",
                       data={"new_name": "Food"})
    assert resp.status_code == 200
    assert "Food" in resp.text


def test_rename_category_to_existing_returns_error(client):
    resp = client.post("/settings/categories/Groceries/rename",
                       data={"new_name": "Fun"})
    assert resp.status_code == 200
    assert "error-msg" in resp.text or "already exists" in resp.text.lower()


# ── Categories — budget ───────────────────────────────────────────────────────

def test_set_budget_valid(client):
    resp = client.post("/settings/categories/Groceries/budget",
                       data={"budget": "600"})
    assert resp.status_code == 200
    assert "600" in resp.text


def test_set_budget_clear(client):
    resp = client.post("/settings/categories/Groceries/budget",
                       data={"budget": ""})
    assert resp.status_code == 200
    assert resp.status_code == 200  # no error


def test_set_budget_invalid_returns_error(client):
    resp = client.post("/settings/categories/Groceries/budget",
                       data={"budget": "not_a_number"})
    assert resp.status_code == 200
    assert "error-msg" in resp.text


# ── Persons — add ─────────────────────────────────────────────────────────────

def test_add_person_valid(client):
    resp = client.post("/settings/persons/add", data={"name": "Bob"})
    assert resp.status_code == 200
    assert "Bob" in resp.text


def test_add_person_empty_returns_error(client):
    resp = client.post("/settings/persons/add", data={"name": ""})
    assert resp.status_code == 200
    assert "error-msg" in resp.text or "cannot be empty" in resp.text.lower()


def test_add_person_duplicate_returns_error(client):
    resp = client.post("/settings/persons/add", data={"name": "Alice"})
    assert resp.status_code == 200
    assert "already exists" in resp.text.lower() or "error-msg" in resp.text


# ── Currency ──────────────────────────────────────────────────────────────────

def test_set_currency_updates_and_shows_success(client):
    resp = client.post("/settings/currency", data={"currency": "USD"})
    assert resp.status_code == 200
    assert "success-msg" in resp.text


# ── Exchange rate refresh ─────────────────────────────────────────────────────

def test_refresh_rates_success(client, monkeypatch):
    async def _mock_refresh():
        return {"USD": 4.0, "EUR": 4.3}
    monkeypatch.setattr("web.routes.settings.refresh_currency_rates", _mock_refresh)
    resp = client.post("/settings/rates")
    assert resp.status_code == 200
    assert "success-msg" in resp.text or "Rates updated" in resp.text


def test_refresh_rates_failure_shows_error(client, monkeypatch):
    async def _mock_fail():
        raise RuntimeError("no rate source reachable")
    monkeypatch.setattr("web.routes.settings.refresh_currency_rates", _mock_fail)
    resp = client.post("/settings/rates")
    assert resp.status_code == 200
    assert "error-msg" in resp.text
