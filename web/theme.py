"""
web/theme.py — session-scoped light/dark theme preference.

Mirrors web/currency.py exactly: no per-user identity on the web UI,
so the preference lives in the signed session cookie. When unset, the
UI omits the data-theme attribute and follows the OS color scheme.
"""

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse

from web import auth
from web.currency import _safe_referer

router = APIRouter()

VALID_THEMES = ("light", "dark")


@router.post("/theme", dependencies=[Depends(auth.require_session)])
async def set_theme(request: Request, theme: str = Form("")):
    target = str(theme).strip().lower()
    payload = auth._session_payload(request) or {}
    payload["ok"] = True
    if target in VALID_THEMES:
        payload["theme"] = target
    else:
        payload.pop("theme", None)  # invalid → back to follow-system
    resp = RedirectResponse(_safe_referer(request), status_code=303)
    auth.set_session_cookie(resp, payload)
    return resp
