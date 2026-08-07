"""
test_web_auth.py — Cycle S2 auth: fail-closed startup + session gating.
"""

import pytest

import settings
from web.auth import validate_web_settings


@pytest.fixture()
def web_creds(monkeypatch):
    monkeypatch.setattr(settings, "WEB_PASSWORD", "hunter2")
    monkeypatch.setattr(settings, "WEB_SESSION_SECRET", "s3cret")


def _client():
    from fastapi.testclient import TestClient
    from web.app import create_app
    return TestClient(create_app())


# ── Fail-closed: app refuses to start without password/secret ────────────────

@pytest.mark.parametrize("password,secret", [
    ("", ""), ("", "s3cret"), ("hunter2", ""),
])
def test_app_refuses_to_start_without_auth_settings(monkeypatch, password, secret):
    from web.app import create_app
    monkeypatch.setattr(settings, "WEB_PASSWORD", password)
    monkeypatch.setattr(settings, "WEB_SESSION_SECRET", secret)
    with pytest.raises(RuntimeError, match="Refusing to start"):
        create_app()
    with pytest.raises(RuntimeError):
        validate_web_settings()


def test_app_starts_with_auth_settings(web_creds):
    assert _client() is not None


# ── Session gating: every protected route redirects when logged out ─────────

@pytest.mark.parametrize("path", ["/", "/transactions", "/cycles"])
def test_routes_require_session(web_creds, path):
    resp = _client().get(path, follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login"


def test_tampered_cookie_rejected(web_creds):
    client = _client()
    client.cookies.set("budgetweb_session", "forged-token")
    resp = client.get("/", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login"


def test_wrong_password_rejected(web_creds):
    resp = _client().post("/login", data={"password": "nope"})
    assert resp.status_code == 401


def test_login_logout_cycle(web_creds, monkeypatch):
    import web.routes.summary as summary_mod
    monkeypatch.setattr(
        summary_mod, "build_summary_context",
        lambda today=None: {"cards": [], "today": None, "currency": "PLN"})
    client = _client()
    resp = client.post("/login", data={"password": "hunter2"}, follow_redirects=False)
    assert resp.status_code == 303
    assert client.get("/").status_code == 200
    client.post("/logout", follow_redirects=False)
    resp = client.get("/", follow_redirects=False)
    assert resp.status_code == 303
