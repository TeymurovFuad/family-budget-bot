"""
web/app.py — read-only web UI for budget-bot (Cycle S2).

Run as its own service (deploy/budget-web.service), completely separate
from the bot process:

    uvicorn --factory web.app:create_app --host $WEB_BIND_HOST --port $WEB_PORT

Bind only to a private/WireGuard address — never 0.0.0.0 (see
settings.WEB_BIND_HOST). Fails closed: create_app() raises when
WEB_PASSWORD / WEB_SESSION_SECRET are unset.
"""

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from web import auth
from web.auth import AuthRedirect, validate_web_settings
from web.routes import cycles as cycles_routes
from web.routes import summary as summary_routes
from web.routes import transactions as transactions_routes

_WEB_DIR = Path(__file__).resolve().parent


def create_app() -> FastAPI:
    validate_web_settings()  # fail closed — no password/secret, no app

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.state.templates = Jinja2Templates(directory=str(_WEB_DIR / "templates"))
    app.mount("/static", StaticFiles(directory=str(_WEB_DIR / "static")), name="static")

    app.include_router(auth.router)
    app.include_router(summary_routes.router)
    app.include_router(transactions_routes.router)
    app.include_router(cycles_routes.router)

    @app.exception_handler(AuthRedirect)
    async def _auth_redirect(request, exc):
        return RedirectResponse("/login", status_code=303)

    return app
