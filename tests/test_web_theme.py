"""
tests/test_web_theme.py — light/dark theme preference + category colors.

Mirrors the currency-preference tests in test_web_foundation.py: the
theme lives in the same signed session cookie, POST /theme uses the same
open-redirect guard, and cat_color_idx must be process-stable (crc32,
never PYTHONHASHSEED-dependent hash()).
"""

import os
import re
import subprocess
import sys
import zlib

import pytest

import settings
import sqlite_ops


@pytest.fixture()
def web_client(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "WEB_PASSWORD", "hunter2")
    monkeypatch.setattr(settings, "WEB_SESSION_SECRET", "s3cret")
    monkeypatch.setattr(settings, "SQLITE_DB_PATH", tmp_path / "web.db")
    conn = sqlite_ops.init_db(settings.SQLITE_DB_PATH)
    sqlite_ops.upsert_rate(conn, "USD", 4.0)
    conn.close()
    from fastapi.testclient import TestClient
    from web.app import create_app
    client = TestClient(create_app())
    client.post("/login", data={"password": "hunter2"}, follow_redirects=False)
    return client


# ── theme: session cookie round-trip ─────────────────────────────────────────

def test_theme_round_trips_in_session_cookie(web_client):
    from web import auth

    resp = web_client.post("/theme", data={"theme": "dark"},
                           follow_redirects=False)
    assert resp.status_code == 303
    token = web_client.cookies.get(auth.SESSION_COOKIE)
    payload = auth._serializer().loads(token, max_age=auth.SESSION_MAX_AGE)
    assert payload["theme"] == "dark"
    assert payload["ok"] is True

    web_client.post("/theme", data={"theme": "light"}, follow_redirects=False)
    token = web_client.cookies.get(auth.SESSION_COOKIE)
    payload = auth._serializer().loads(token, max_age=auth.SESSION_MAX_AGE)
    assert payload["theme"] == "light"


def test_get_session_theme_reads_cookie(web_client):
    from unittest.mock import Mock

    from web import auth

    web_client.post("/theme", data={"theme": "dark"}, follow_redirects=False)
    request = Mock()
    request.cookies = {
        auth.SESSION_COOKIE: web_client.cookies.get(auth.SESSION_COOKIE)}
    assert auth.get_session_theme(request) == "dark"


def test_theme_invalid_value_clears_preference(web_client):
    from web import auth

    web_client.post("/theme", data={"theme": "dark"}, follow_redirects=False)
    resp = web_client.post("/theme", data={"theme": "hotdog-stand"},
                           follow_redirects=False)
    assert resp.status_code == 303
    token = web_client.cookies.get(auth.SESSION_COOKIE)
    payload = auth._serializer().loads(token, max_age=auth.SESSION_MAX_AGE)
    assert "theme" not in payload


def test_theme_preserves_currency_preference(web_client):
    from web import auth

    web_client.post("/currency", data={"currency": "USD"},
                    follow_redirects=False)
    web_client.post("/theme", data={"theme": "dark"}, follow_redirects=False)
    token = web_client.cookies.get(auth.SESSION_COOKIE)
    payload = auth._serializer().loads(token, max_age=auth.SESSION_MAX_AGE)
    assert payload["currency"] == "USD"
    assert payload["theme"] == "dark"


def test_get_session_theme_unset_or_invalid_returns_none():
    from unittest.mock import Mock

    from web import auth

    request = Mock()
    request.cookies = {}
    assert auth.get_session_theme(request) is None


# ── theme: security (same guarantees as /currency) ───────────────────────────

def test_theme_route_redirects_to_referer_same_origin_only(web_client):
    resp = web_client.post("/theme", data={"theme": "dark"},
                           headers={"referer": "http://testserver/transactions?year=2024"},
                           follow_redirects=False)
    assert resp.headers["location"] == "/transactions?year=2024"
    resp = web_client.post("/theme", data={"theme": "dark"},
                           headers={"referer": "https://evil.example/phish"},
                           follow_redirects=False)
    assert resp.headers["location"] == "/"
    resp = web_client.post("/theme", data={"theme": "dark"},
                           follow_redirects=False)
    assert resp.headers["location"] == "/"


def test_theme_route_requires_session(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "WEB_PASSWORD", "hunter2")
    monkeypatch.setattr(settings, "WEB_SESSION_SECRET", "s3cret")
    from fastapi.testclient import TestClient
    from web.app import create_app
    client = TestClient(create_app())
    resp = client.post("/theme", data={"theme": "dark"},
                       follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login"


def test_tampered_theme_cookie_rejected(web_client):
    from web import auth

    token = web_client.cookies.get(auth.SESSION_COOKIE)
    web_client.cookies.set(auth.SESSION_COOKIE, token[:-3] + "xyz")
    resp = web_client.post("/theme", data={"theme": "dark"},
                           follow_redirects=False)
    assert resp.headers["location"] == "/login"


# ── theme: data-theme attribute rendering ────────────────────────────────────

def test_data_theme_absent_when_unset(web_client):
    resp = web_client.get("/")
    assert "data-theme" not in resp.text


def test_data_theme_rendered_when_set(web_client):
    web_client.post("/theme", data={"theme": "dark"}, follow_redirects=False)
    resp = web_client.get("/")
    assert 'data-theme="dark"' in resp.text
    # The toggle now offers the opposite theme.
    assert 'value="light"' in resp.text
    web_client.post("/theme", data={"theme": "light"}, follow_redirects=False)
    resp = web_client.get("/")
    assert 'data-theme="light"' in resp.text
    assert 'value="dark"' in resp.text


# ── login page: theme tokens, no raw system colors ───────────────────────────

def test_login_page_uses_tokens_not_canvas(web_client):
    html = web_client.get("/login").text
    # No raw system-color keywords left from before the light-dark()
    # migration ("Canvas" also catches "CanvasText").
    assert "Canvas" not in html
    assert "var(--bg)" in html and "var(--ink)" in html
    assert "light-dark(" in html
    assert "color-scheme: light dark" in html


# ── OS-preference coin flip (CSS-only) ────────────────────────────────────────
# Actual @media behavior needs a real browser; a Python suite can only
# assert the rule's presence and selector scoping, which we do here.

def test_os_dark_coin_flip_rule_scoped_to_no_explicit_theme():
    css = open("web/static/style.css", encoding="utf-8").read()
    # Explicit user choice keeps its own rule…
    assert '[data-theme="dark"] .theme-toggle svg { transform: scaleX(-1); }' in css
    # …and the OS-preference rule only applies when NO explicit data-theme
    # attribute exists, so it can never override the user's toggle.
    assert re.search(
        r'@media \(prefers-color-scheme: dark\) \{\s*'
        r'html:not\(\[data-theme\]\) \.theme-toggle svg '
        r'\{ transform: scaleX\(-1\); \}', css)


# ── category colors: deterministic, process-stable ───────────────────────────

def test_cat_color_idx_deterministic_and_in_range():
    from web.app import cat_color_idx

    for name in ("Groceries", "transport", "Eating Out", "zażółć"):
        idx = cat_color_idx(name)
        assert idx == cat_color_idx(name)
        assert 0 <= idx <= 7
    # Normalization: case/whitespace-insensitive.
    assert cat_color_idx(" Groceries ") == cat_color_idx("groceries")


def test_cat_color_idx_matches_crc32_not_hash():
    from web.app import cat_color_idx

    # Known crc32 values — fails if the implementation drifts to hash().
    assert cat_color_idx("groceries") == zlib.crc32(b"groceries") % 8 == 7
    assert cat_color_idx("transport") == zlib.crc32(b"transport") % 8 == 6


def test_cat_color_idx_stable_across_fresh_process():
    from web.app import cat_color_idx

    def run(seed: str) -> int:
        env = dict(os.environ, PYTHONHASHSEED=seed)
        out = subprocess.run(
            [sys.executable, "-c",
             "from web.app import cat_color_idx; print(cat_color_idx('Groceries'))"],
            capture_output=True, text=True, check=True, env=env,
        )
        return int(out.stdout.strip())

    assert run("1") == run("2") == cat_color_idx("Groceries")


# ── category chips render with the palette variable ──────────────────────────

def _render_chip(**kwargs):
    from jinja2 import Environment, FileSystemLoader

    env = Environment(loader=FileSystemLoader("web/templates"))
    tpl = env.from_string(
        "{% from '_macros.html' import chip %}{{ chip(text, clear_url=clear_url, cat_idx=cat_idx) }}")
    return tpl.render(text=kwargs.get("text", "Groceries"),
                      clear_url=kwargs.get("clear_url"),
                      cat_idx=kwargs.get("cat_idx"))


def test_category_chip_gets_palette_variable():
    html = _render_chip(text="Groceries", cat_idx=7)
    assert 'class="chip chip--cat"' in html
    assert "--cat: var(--cat-7)" in html


def test_cat_idx_zero_is_not_treated_as_unset():
    html = _render_chip(text="Transport", cat_idx=0)
    assert "--cat: var(--cat-0)" in html


def test_filter_and_plain_chips_unaffected():
    html = _render_chip(text="2024", clear_url="/transactions")
    assert "chip--cat" not in html and "--cat:" not in html
    html = _render_chip(text="plain")
    assert html == '<span class="chip">plain</span>'
