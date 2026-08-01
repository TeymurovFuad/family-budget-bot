"""
web/auth.py — shared-password session auth for the read-only web UI.

Intentionally minimal for a 2-5 person household behind WireGuard:
one shared password (settings.WEB_PASSWORD), an itsdangerous-signed
session cookie, no user accounts, no reset flow.

Fail-closed: web/app.py refuses to start when WEB_PASSWORD or
WEB_SESSION_SECRET is empty — validate_web_settings() below.
"""

import secrets

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

import settings

SESSION_COOKIE = "budgetweb_session"
SESSION_MAX_AGE = 30 * 24 * 3600  # 30 days

router = APIRouter()


def validate_web_settings() -> None:
    """Raise unless both auth settings are configured — never run open."""
    if not settings.WEB_PASSWORD or not settings.WEB_SESSION_SECRET:
        raise RuntimeError(
            "Refusing to start: WEB_PASSWORD and WEB_SESSION_SECRET must both "
            "be set (non-empty) in the environment. The web UI never runs "
            "without authentication."
        )


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(settings.WEB_SESSION_SECRET, salt="budget-web-session")


class AuthRedirect(Exception):
    """Raised by require_session; handled in app.py → redirect to /login."""


def require_session(request: Request) -> None:
    """FastAPI dependency — every protected route must depend on this."""
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise AuthRedirect()
    try:
        _serializer().loads(token, max_age=SESSION_MAX_AGE)
    except (BadSignature, SignatureExpired):
        raise AuthRedirect()


def _session_payload(request: Request) -> dict | None:
    """Verified cookie payload as a dict, or None when absent/invalid.

    Pre-currency cookies carry the plain string "ok"; treat them as an
    empty dict so old sessions keep working with default preferences.
    """
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        return None
    try:
        data = _serializer().loads(token, max_age=SESSION_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None
    return data if isinstance(data, dict) else {}


def get_session_currency(request: Request) -> str:
    """Display currency stored in the signed session cookie, or the default."""
    payload = _session_payload(request) or {}
    return payload.get("currency") or settings.DISPLAY_CURRENCY


def get_session_theme(request: Request) -> str | None:
    """Theme stored in the signed session cookie ("light"/"dark"), or None.

    None means "no explicit preference" — the UI omits data-theme and
    follows the OS via `color-scheme: light dark`.
    """
    payload = _session_payload(request) or {}
    theme = payload.get("theme")
    return theme if theme in ("light", "dark") else None


def set_session_cookie(resp, payload: dict) -> None:
    """Sign and set the session cookie with the given payload dict."""
    resp.set_cookie(
        SESSION_COOKIE, _serializer().dumps(payload),
        max_age=SESSION_MAX_AGE, httponly=True, samesite="lax")


def _templates(request: Request):
    return request.app.state.templates


@router.get("/login", response_class=HTMLResponse)
async def login_form(request: Request):
    return _templates(request).TemplateResponse(
        request, "login.html", {"error": None})


@router.post("/login")
async def login(request: Request, password: str = Form("")):
    if not settings.WEB_PASSWORD or not secrets.compare_digest(
            password.encode(), settings.WEB_PASSWORD.encode()):
        return _templates(request).TemplateResponse(
            request, "login.html", {"error": "Wrong password."}, status_code=401)
    resp = RedirectResponse("/", status_code=303)
    set_session_cookie(resp, {"ok": True, "currency": settings.DISPLAY_CURRENCY})
    return resp


@router.post("/logout")
async def logout():
    resp = RedirectResponse("/login", status_code=303)
    resp.delete_cookie(SESSION_COOKIE)
    return resp
