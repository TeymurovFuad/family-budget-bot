"""
web/app.py — read-only web UI for budget-bot (Cycle S2).

Run as its own service (deploy/budget-web.service), completely separate
from the bot process:

    uvicorn --factory web.app:create_app --host $WEB_BIND_HOST --port $WEB_PORT

Bind only to a private/WireGuard address — never 0.0.0.0 (see
settings.WEB_BIND_HOST). Fails closed: create_app() raises when
WEB_PASSWORD / WEB_SESSION_SECRET are unset.
"""

import zlib
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from logger import init_logging
from web import auth
from web import currency as currency_routes
from web import theme as theme_routes
from web.auth import AuthRedirect, validate_web_settings
from web.routes import cycles as cycles_routes
from web.routes import drafts as drafts_routes
from web.routes import settings as settings_routes
from web.routes import report as report_routes
from web.routes import summary as summary_routes
from web.routes import transactions as transactions_routes

_WEB_DIR = Path(__file__).resolve().parent


def cat_color_idx(name: str) -> int:
    """Stable 0-7 palette index for a category name (drives --cat-N).

    crc32, not built-in hash(): hash() is randomized per process
    (PYTHONHASHSEED) and would recolor every category on each restart.
    """
    return zlib.crc32(str(name).strip().lower().encode()) % 8


def create_app() -> FastAPI:
    # Ensure web routes use the same file/console logging setup as the bot.
    init_logging()
    validate_web_settings()  # fail closed — no password/secret, no app

    # One-time DB schema init at startup — avoids re-running CREATE TABLE IF
    # NOT EXISTS DDL on every _conn() call (8 statements × 4-5 calls/request).
    import settings as _settings
    import sqlite_ops as _sqlite_ops
    import storage_facade as _sf
    try:
        _sqlite_ops.init_db(_settings.SQLITE_DB_PATH)
        _sf._db_initialized = True
    except Exception:
        pass  # DB may not exist yet on first boot; _conn() falls back to init_db

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.state.templates = Jinja2Templates(directory=str(_WEB_DIR / "templates"))
    # Nav-level currency switcher (base.html) — resolved per request without
    # every page route having to pass currency context explicitly.
    app.state.templates.env.globals.update(
        session_currency=auth.get_session_currency,
        available_currencies=currency_routes.available_currencies,
        session_theme=auth.get_session_theme,
    )
    app.state.templates.env.filters["cat_color_idx"] = cat_color_idx
    app.mount("/static", StaticFiles(directory=str(_WEB_DIR / "static")), name="static")

    app.include_router(auth.router)
    app.include_router(currency_routes.router)
    app.include_router(theme_routes.router)
    app.include_router(summary_routes.router)
    app.include_router(report_routes.router)
    app.include_router(transactions_routes.router)
    app.include_router(drafts_routes.router)
    app.include_router(cycles_routes.router)
    app.include_router(settings_routes.router)

    @app.exception_handler(AuthRedirect)
    async def _auth_redirect(request, exc):
        return RedirectResponse("/login", status_code=303)

    return app
