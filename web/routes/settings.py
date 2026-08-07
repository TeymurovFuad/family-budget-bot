"""
web/routes/settings.py — GET /settings and sub-routes for managing
categories (list/add/rename/budget), persons (list/add), display currency
(view/change), and on-demand Excel sync.

All writes go through storage_facade — never directly to sqlite_ops.
Dual-write: SQLite first (atomic), then Excel Lists sheet (best-effort).
"""

import logging
from urllib.parse import quote as _urlquote

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse

import settings as app_settings
from storage_facade import (
    add_category,
    add_person,
    get_last_export_time,
    get_owner_display_currency,
    load_category_budgets,
    load_reference_data,
    refresh_currency_rates,
    rename_category,
    set_category_budget,
    set_owner_display_currency,
    trigger_excel_export,
)
from validators import parse_amount
from web.auth import require_session

log = logging.getLogger(__name__)
router = APIRouter()

_AVAILABLE_CURRENCIES = ["PLN", "USD", "EUR", "GBP", "CHF", "CZK", "SEK", "NOK", "DKK", "HUF"]


def _currencies_from_ref() -> list[str]:
    """Return available currencies from reference data, falling back to hardcoded list."""
    try:
        ref = load_reference_data()
        ccys = ref.get("currencies", [])
        if ccys:
            return sorted(ccys)
    except Exception:
        pass
    return _AVAILABLE_CURRENCIES


def _settings_ctx(request: Request) -> dict:
    """Base context for the full settings page and all fragment re-renders."""
    ref = load_reference_data()
    budgets = load_category_budgets()
    return {
        "categories": ref["categories"],
        "persons": ref["persons"],
        "display_currency": get_owner_display_currency(),
        "setting_currencies": _currencies_from_ref(),
        "category_budgets": budgets,
        "last_sync": get_last_export_time(),
        "error": None,
        "success": None,
    }


# ── GET /settings ──────────────────────────────────────────────────────────────

@router.get("/settings", response_class=HTMLResponse,
            dependencies=[Depends(require_session)])
async def settings_page(request: Request):
    ctx = _settings_ctx(request)
    return request.app.state.templates.TemplateResponse(request, "settings.html", ctx)


# ── Sync ───────────────────────────────────────────────────────────────────────

@router.post("/settings/sync", response_class=HTMLResponse,
             dependencies=[Depends(require_session)])
async def settings_sync(request: Request):
    error = None
    try:
        await trigger_excel_export()
    except Exception:
        log.exception("Web-triggered Excel sync failed")
        error = "Sync failed — check server logs."
    last_sync = get_last_export_time()
    ctx = {"last_sync": last_sync, "error": error}
    return request.app.state.templates.TemplateResponse(
        request, "_sync_status.html", ctx)


# ── Categories ─────────────────────────────────────────────────────────────────

@router.get("/settings/categories", response_class=HTMLResponse,
            dependencies=[Depends(require_session)])
async def settings_categories(request: Request):
    ctx = _settings_ctx(request)
    return request.app.state.templates.TemplateResponse(
        request, "_settings_categories.html", ctx)


@router.post("/settings/categories/add", response_class=HTMLResponse,
             dependencies=[Depends(require_session)])
async def settings_categories_add(request: Request, name: str = Form("")):
    ctx = _settings_ctx(request)
    name = name.strip()
    if not name:
        ctx["error"] = "Category name cannot be empty."
    else:
        try:
            added = add_category(name)
            if not added:
                ctx["error"] = f"'{name}' already exists."
            else:
                ctx = _settings_ctx(request)
        except ValueError as exc:
            ctx["error"] = str(exc)
        except Exception as exc:
            ctx["error"] = f"Could not add category: {exc}"
    return request.app.state.templates.TemplateResponse(
        request, "_settings_categories.html", ctx)


@router.get("/settings/categories/{name}/rename-form", response_class=HTMLResponse,
            dependencies=[Depends(require_session)])
async def settings_categories_rename_form(request: Request, name: str):
    return request.app.state.templates.TemplateResponse(
        request, "_settings_cat_rename_form.html", {"name": name})


@router.post("/settings/categories/{name}/rename", response_class=HTMLResponse,
             dependencies=[Depends(require_session)])
async def settings_categories_rename(request: Request, name: str,
                                     new_name: str = Form("")):
    ctx = _settings_ctx(request)
    new_name = new_name.strip()
    if not new_name:
        ctx["error"] = "New name cannot be empty."
    elif new_name == name:
        pass
    else:
        try:
            rename_category(name, new_name)
            ctx = _settings_ctx(request)
        except ValueError as exc:
            ctx["error"] = str(exc)
        except Exception as exc:
            ctx["error"] = f"Could not rename category: {exc}"
    return request.app.state.templates.TemplateResponse(
        request, "_settings_categories.html", ctx)


@router.get("/settings/categories/{name}/row", response_class=HTMLResponse,
            dependencies=[Depends(require_session)])
async def settings_categories_row(request: Request, name: str):
    budgets = load_category_budgets()
    return request.app.state.templates.TemplateResponse(
        request, "_settings_cat_row.html",
        {"name": name, "budget": budgets.get(name)})


@router.get("/settings/categories/{name}/budget-form", response_class=HTMLResponse,
            dependencies=[Depends(require_session)])
async def settings_categories_budget_form(request: Request, name: str):
    budgets = load_category_budgets()
    return request.app.state.templates.TemplateResponse(
        request, "_settings_cat_budget_form.html",
        {"name": name, "budget": budgets.get(name)})


@router.post("/settings/categories/{name}/budget", response_class=HTMLResponse,
             dependencies=[Depends(require_session)])
async def settings_categories_budget(request: Request, name: str,
                                     budget: str = Form("")):
    ctx = _settings_ctx(request)
    budget_str = budget.strip()
    amount: float | None = None
    if budget_str:
        try:
            amount, _ = parse_amount(budget_str)
            if amount < 0:
                raise ValueError("Budget must be a positive number.")
        except ValueError as exc:
            ctx["error"] = str(exc)
            return request.app.state.templates.TemplateResponse(
                request, "_settings_categories.html", ctx)
    try:
        set_category_budget(name, amount)
        ctx = _settings_ctx(request)
    except Exception as exc:
        ctx["error"] = f"Could not update budget: {exc}"
    return request.app.state.templates.TemplateResponse(
        request, "_settings_categories.html", ctx)


# ── Persons ────────────────────────────────────────────────────────────────────

@router.get("/settings/persons", response_class=HTMLResponse,
            dependencies=[Depends(require_session)])
async def settings_persons(request: Request):
    ctx = _settings_ctx(request)
    return request.app.state.templates.TemplateResponse(
        request, "_settings_persons.html", ctx)


@router.post("/settings/persons/add", response_class=HTMLResponse,
             dependencies=[Depends(require_session)])
async def settings_persons_add(request: Request, name: str = Form("")):
    ctx = _settings_ctx(request)
    name = name.strip()
    if not name:
        ctx["error"] = "Person name cannot be empty."
    else:
        try:
            added = add_person(name)
            if not added:
                ctx["error"] = f"'{name}' already exists."
            else:
                ctx = _settings_ctx(request)
        except ValueError as exc:
            ctx["error"] = str(exc)
        except Exception as exc:
            ctx["error"] = f"Could not add person: {exc}"
    return request.app.state.templates.TemplateResponse(
        request, "_settings_persons.html", ctx)


# ── Display currency ──────────────────────────────────────────────────────────

@router.post("/settings/rates", response_class=HTMLResponse,
             dependencies=[Depends(require_session)])
async def settings_rates_refresh(request: Request):
    ctx = _settings_ctx(request)
    try:
        await refresh_currency_rates()
        ctx = _settings_ctx(request)
        ctx["rates_success"] = True
    except Exception as exc:
        ctx["rates_error"] = str(exc)
    return request.app.state.templates.TemplateResponse(
        request, "_settings_currency.html", ctx)


@router.post("/settings/currency", response_class=HTMLResponse,
             dependencies=[Depends(require_session)])
async def settings_currency_set(request: Request, currency: str = Form("")):
    ctx = _settings_ctx(request)
    ccy = currency.strip().upper()
    if not ccy:
        ctx["error"] = "Currency code cannot be empty."
    else:
        try:
            set_owner_display_currency(ccy)
            ctx = _settings_ctx(request)
            ctx["success"] = True
        except Exception as exc:
            ctx["error"] = f"Could not update currency: {exc}"
    return request.app.state.templates.TemplateResponse(
        request, "_settings_currency.html", ctx)
