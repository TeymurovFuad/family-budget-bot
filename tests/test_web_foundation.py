"""
test_web_foundation.py — web UI redesign foundation:
extended list_transactions (date range, search, sort, pagination),
count_transactions, session-cookie currency preference, and the
display-only conversion helper.
"""

import pytest

import settings
import sqlite_ops
import storage_facade


@pytest.fixture()
def db(tmp_path):
    conn = sqlite_ops.init_db(tmp_path / "test.db")
    yield conn
    conn.close()


def _txn(**overrides) -> dict:
    row = {
        "date": "2024-06-15", "year": 2024, "month": "Jun", "value": 150.5,
        "currency": "PLN", "value_base": 150.5, "rate_used": 1.0,
        "type": "Expense", "category": "Groceries", "person": "Alice",
        "description": "weekly shop", "is_recurring": False, "is_done": True,
        "source": "test",
    }
    row.update(overrides)
    return row


def _seed(db, n=5):
    ids = []
    for i in range(n):
        ids.append(sqlite_ops.insert_transaction(db, _txn(
            date=f"2024-06-{10 + i:02d}", value=100.0 + i,
            description=f"item {i}",
            person="Alice" if i % 2 == 0 else "Bob")))
    return ids


# ── date range ────────────────────────────────────────────────────────────────

def test_date_range_inclusive(db):
    _seed(db)  # dates 2024-06-10 .. 2024-06-14
    rows = sqlite_ops.list_transactions(db, date_from="2024-06-11", date_to="2024-06-13")
    assert [r["date"] for r in rows] == ["2024-06-11", "2024-06-12", "2024-06-13"]


def test_date_range_open_ended(db):
    _seed(db)
    assert len(sqlite_ops.list_transactions(db, date_from="2024-06-13")) == 2
    assert len(sqlite_ops.list_transactions(db, date_to="2024-06-10")) == 1
    assert sqlite_ops.list_transactions(db, date_from="2025-01-01") == []


def test_date_range_combines_with_equality_filters(db):
    _seed(db)
    rows = sqlite_ops.list_transactions(
        db, {"person": "Alice"}, date_from="2024-06-11", date_to="2024-06-14")
    assert [r["date"] for r in rows] == ["2024-06-12", "2024-06-14"]


# ── description search ────────────────────────────────────────────────────────

def test_description_contains_substring(db):
    _seed(db)
    sqlite_ops.insert_transaction(db, _txn(description="Biedronka groceries",
                                           date="2024-06-20"))
    rows = sqlite_ops.list_transactions(db, description_contains="Biedronka")
    assert len(rows) == 1
    assert rows[0]["description"] == "Biedronka groceries"


def test_description_search_is_ascii_case_insensitive(db):
    # SQLite's default LIKE is case-insensitive for ASCII characters only —
    # documented actual behavior, not an assumption.
    sqlite_ops.insert_transaction(db, _txn(description="Biedronka groceries"))
    assert len(sqlite_ops.list_transactions(db, description_contains="biedronka")) == 1
    assert len(sqlite_ops.list_transactions(db, description_contains="GROCERIES")) == 1


def test_description_search_injection_attempt_is_inert(db):
    _seed(db)
    hostile = "'; DROP TABLE transactions; --"
    assert sqlite_ops.list_transactions(db, description_contains=hostile) == []
    assert sqlite_ops.count_transactions(db, description_contains=hostile) == 0
    assert len(sqlite_ops.list_transactions(db)) == 5  # table intact


# ── sorting ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("column", ["date", "value", "category", "person", "description"])
def test_sort_by_each_whitelisted_column_both_directions(db, column):
    _seed(db)
    asc = [r[column] for r in sqlite_ops.list_transactions(db, sort_by=column, sort_dir="asc")]
    desc = [r[column] for r in sqlite_ops.list_transactions(db, sort_by=column, sort_dir="desc")]
    assert asc == sorted(asc)
    assert desc == sorted(desc, reverse=True)


@pytest.mark.parametrize("bad", ["id; DROP TABLE transactions", "content_hash", "", "Date"])
def test_sort_by_rejects_unlisted_columns(db, bad):
    with pytest.raises(ValueError):
        sqlite_ops.list_transactions(db, sort_by=bad)


@pytest.mark.parametrize("bad", ["ASC; --", "up", "", "descending"])
def test_sort_dir_rejects_unlisted_values(db, bad):
    with pytest.raises(ValueError):
        sqlite_ops.list_transactions(db, sort_by="date", sort_dir=bad)


# ── pagination ────────────────────────────────────────────────────────────────

def test_limit_offset_page_slices(db):
    _seed(db)
    all_rows = sqlite_ops.list_transactions(db)
    page1 = sqlite_ops.list_transactions(db, limit=2, offset=0)
    page2 = sqlite_ops.list_transactions(db, limit=2, offset=2)
    page3 = sqlite_ops.list_transactions(db, limit=2, offset=4)
    assert [r["id"] for r in page1 + page2 + page3] == [r["id"] for r in all_rows]
    assert len(page3) == 1


def test_offset_without_limit(db):
    _seed(db)
    assert len(sqlite_ops.list_transactions(db, offset=3)) == 2


def test_offset_beyond_total_returns_empty(db):
    _seed(db)
    assert sqlite_ops.list_transactions(db, limit=10, offset=99) == []


def test_count_transactions_matches_totals(db):
    _seed(db)
    assert sqlite_ops.count_transactions(db) == 5
    assert sqlite_ops.count_transactions(db, {"person": "Alice"}) == 3
    assert sqlite_ops.count_transactions(db, date_from="2024-06-12") == 3
    assert sqlite_ops.count_transactions(db, description_contains="item") == 5
    with pytest.raises(ValueError):
        sqlite_ops.count_transactions(db, {"description": "x"})


# ── storage_facade passthrough ────────────────────────────────────────────────

@pytest.fixture()
def facade_db(tmp_path, monkeypatch):
    path = tmp_path / "facade.db"
    monkeypatch.setattr(settings, "SQLITE_DB_PATH", path)
    conn = sqlite_ops.init_db(path)
    _seed(conn)
    conn.close()


def test_facade_load_transactions_new_params(facade_db):
    df = storage_facade.load_transactions(
        date_from="2024-06-11", date_to="2024-06-13",
        description_contains="item", sort_by="value", sort_dir="desc",
        limit=2, offset=1)
    assert list(df["Value"]) == [102.0, 101.0]


def test_facade_load_transactions_old_callers_unchanged(facade_db):
    assert len(storage_facade.load_transactions()) == 5
    assert len(storage_facade.load_transactions({"person": "Bob"})) == 2


def test_facade_count_transactions(facade_db):
    assert storage_facade.count_transactions() == 5
    assert storage_facade.count_transactions({"person": "Alice"},
                                             date_from="2024-06-12") == 2


# ── currency: conversion helper ───────────────────────────────────────────────

def test_convert_from_base_known_rate():
    from web.currency import convert_from_base
    rates = {"USD": 4.0, "EUR": 4.3}
    assert convert_from_base(400.0, "USD", rates) == pytest.approx(100.0)
    assert convert_from_base(430.0, "eur", rates) == pytest.approx(100.0)


def test_convert_from_base_display_or_unknown_returns_value(monkeypatch):
    from web.currency import convert_from_base
    monkeypatch.setattr(settings, "DISPLAY_CURRENCY", "PLN")
    assert convert_from_base(123.4, "PLN", {"USD": 4.0}) == 123.4
    assert convert_from_base(123.4, "", {"USD": 4.0}) == 123.4
    assert convert_from_base(123.4, "XXX", {"USD": 4.0}) == 123.4
    assert convert_from_base(123.4, "BAD", {"BAD": 0}) == 123.4


def test_conversion_is_display_only_never_persisted(db, monkeypatch):
    from web.currency import convert_from_base
    sqlite_ops.upsert_rate(db, "USD", 4.0)
    rid = sqlite_ops.insert_transaction(db, _txn(value_base=400.0))
    before = dict(sqlite_ops.list_transactions(db)[0])
    convert_from_base(before["value_base"], "USD", sqlite_ops.load_rates_dict(db))
    after = dict(sqlite_ops.list_transactions(db)[0])
    assert after == before
    assert after["value_base"] == 400.0
    assert after["id"] == rid


# ── currency: session cookie ──────────────────────────────────────────────────

@pytest.fixture()
def web_client(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "WEB_PASSWORD", "hunter2")
    monkeypatch.setattr(settings, "WEB_SESSION_SECRET", "s3cret")
    monkeypatch.setattr(settings, "SQLITE_DB_PATH", tmp_path / "web.db")
    conn = sqlite_ops.init_db(settings.SQLITE_DB_PATH)
    sqlite_ops.upsert_rate(conn, "USD", 4.0)
    sqlite_ops.upsert_rate(conn, "EUR", 4.3)
    conn.close()
    from fastapi.testclient import TestClient
    from web.app import create_app
    client = TestClient(create_app())
    client.post("/login", data={"password": "hunter2"}, follow_redirects=False)
    return client


def test_currency_round_trips_in_session_cookie(web_client):
    from web import auth

    resp = web_client.post("/currency", data={"currency": "USD"},
                           follow_redirects=False)
    assert resp.status_code == 303
    token = web_client.cookies.get(auth.SESSION_COOKIE)
    payload = auth._serializer().loads(token, max_age=auth.SESSION_MAX_AGE)
    assert payload["currency"] == "USD"
    assert payload["ok"] is True


def test_currency_route_redirects_to_referer(web_client):
    resp = web_client.post("/currency", data={"currency": "EUR"},
                           headers={"referer": "http://testserver/transactions?year=2024"},
                           follow_redirects=False)
    assert resp.headers["location"] == "/transactions?year=2024"
    resp = web_client.post("/currency", data={"currency": "EUR"},
                           headers={"referer": "https://evil.example/phish"},
                           follow_redirects=False)
    assert resp.headers["location"] == "/"
    resp = web_client.post("/currency", data={"currency": "EUR"},
                           follow_redirects=False)
    assert resp.headers["location"] == "/"


def test_currency_unknown_code_falls_back_to_default(web_client, monkeypatch):
    from web import auth

    resp = web_client.post("/currency", data={"currency": "NOPE"},
                           follow_redirects=False)
    assert resp.status_code == 303
    token = web_client.cookies.get(auth.SESSION_COOKIE)
    payload = auth._serializer().loads(token, max_age=auth.SESSION_MAX_AGE)
    assert payload["currency"] == str(settings.DISPLAY_CURRENCY).upper()


def test_currency_route_requires_session(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "WEB_PASSWORD", "hunter2")
    monkeypatch.setattr(settings, "WEB_SESSION_SECRET", "s3cret")
    from fastapi.testclient import TestClient
    from web.app import create_app
    client = TestClient(create_app())
    resp = client.post("/currency", data={"currency": "USD"},
                       follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login"


def test_tampered_currency_cookie_rejected(web_client):
    from web import auth

    token = web_client.cookies.get(auth.SESSION_COOKIE)
    web_client.cookies.set(auth.SESSION_COOKIE, token[:-3] + "xyz")
    resp = web_client.post("/currency", data={"currency": "USD"},
                           follow_redirects=False)
    assert resp.headers["location"] == "/login"


def test_legacy_ok_string_cookie_still_valid(web_client):
    # Pre-currency sessions signed the plain string "ok"; they must keep
    # working and read as the default currency.
    from unittest.mock import Mock

    from web import auth

    legacy = auth._serializer().dumps("ok")
    request = Mock()
    request.cookies = {auth.SESSION_COOKIE: legacy}
    auth.require_session(request)  # must not raise
    assert auth.get_session_currency(request) == settings.DISPLAY_CURRENCY
