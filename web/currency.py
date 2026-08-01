"""
web/currency.py — session-scoped display-currency preference (redesign
foundation).

The bot has a per-Telegram-user currency preference; the web UI has no
per-user identity (shared-password session), so the preference lives in
the signed session cookie instead. Display-only: conversion never writes
anything back to the database.
"""

import logging
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse

import settings
import sqlite_ops
import storage_facade
from web import auth

log = logging.getLogger(__name__)

router = APIRouter()


def available_currencies() -> list[str]:
    """Currency codes with known rates; safe fallback when the DB is absent."""
    try:
        currencies = storage_facade.load_reference_data()["currencies"]
    except Exception:
        currencies = []
    display = str(settings.DISPLAY_CURRENCY).strip().upper()
    if display not in currencies:
        currencies = [display, *currencies]
    return currencies


def convert_from_base(value_base: float, target_currency: str,
                      rates: dict[str, float]) -> float:
    """
    Convert a stored value_base (denominated in settings.DISPLAY_CURRENCY)
    into `target_currency` using the rates table (rate_to_base: 1 unit of
    currency = rate units of base). Display-only — never persisted.
    Unknown currency or non-positive rate falls back to the base value.
    """
    target = str(target_currency or "").strip().upper()
    display = str(settings.DISPLAY_CURRENCY).strip().upper()
    if not target or target == display:
        return float(value_base)
    rate = rates.get(target)
    if not rate or float(rate) <= 0:
        return float(value_base)
    return float(value_base) / float(rate)


def load_rates() -> dict[str, float]:
    """{currency: rate_to_base} for convert_from_base; empty when DB absent."""
    try:
        conn = storage_facade._conn()
        try:
            return sqlite_ops.load_rates_dict(conn)
        finally:
            conn.close()
    except Exception:
        return {}


def _safe_referer(request: Request) -> str:
    """Same-origin path from the Referer header; '/' otherwise (no open redirect)."""
    parts = urlsplit(request.headers.get("referer") or "")
    if parts.netloc and parts.netloc != request.url.netloc:
        return "/"
    path = parts.path or "/"
    if not path.startswith("/") or path.startswith("//"):
        return "/"
    return f"{path}?{parts.query}" if parts.query else path


@router.post("/currency", dependencies=[Depends(auth.require_session)])
async def set_currency(request: Request, currency: str = Form("")):
    target = str(currency).strip().upper()
    if target not in available_currencies():
        target = str(settings.DISPLAY_CURRENCY).strip().upper()
    payload = auth._session_payload(request) or {}
    payload.update({"ok": True, "currency": target})
    resp = RedirectResponse(_safe_referer(request), status_code=303)
    auth.set_session_cookie(resp, payload)
    return resp
