"""
web/routes/cycles.py — cycle-ledger view with full CRUD + detect flow.

GET  /cycles              — list with current cycle card, history table, and controls
POST /cycles/add          — add a new boundary (date + optional label)
POST /cycles/{date}/rename — rename an existing boundary's label
POST /cycles/{date}/delete — delete a boundary
POST /cycles/detect       — scan transactions for unrecorded salary arrivals;
                            renders a detect results page with Record buttons

All writes go through storage_facade; the page redirects back to GET /cycles
on success, or to GET /cycles?msg=...&level=error on validation failure.
"""

import logging
from datetime import date, datetime, timedelta
from urllib.parse import quote as _urlquote

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

import settings
from cycles import (
    _dedup_cycle_label,
    current_cycle_start,
    detect_cycle_candidates,
    fallback_income_candidates,
)
from storage_facade import (
    delete_cycle_boundary,
    load_cycles,
    load_transactions,
    rename_cycle_boundary,
    save_cycle_boundary,
)
from web.auth import require_session

log = logging.getLogger(__name__)
router = APIRouter()

_MAX_LABEL = 64


def _redirect(msg: str = "", level: str = "error") -> RedirectResponse:
    if msg:
        return RedirectResponse(
            f"/cycles?msg={_urlquote(msg)}&level={level}", status_code=303)
    return RedirectResponse("/cycles", status_code=303)


def _typical_cycle_length(ledger: list) -> int | None:
    """
    Median length in days of COMPLETED cycles; None with fewer than 2
    completed cycles — a single data point is not reliable, so the progress
    bar is omitted instead.
    """
    lengths = sorted((ledger[i + 1][0] - ledger[i][0]).days
                     for i in range(len(ledger) - 1))
    if len(lengths) < 2:
        return None
    mid = len(lengths) // 2
    if len(lengths) % 2:
        return lengths[mid]
    return round((lengths[mid - 1] + lengths[mid]) / 2)


def _cycles_ctx(today: date) -> dict:
    """Build the base context for GET /cycles."""
    ledger = load_cycles()
    current = current_cycle_start(today, ledger)
    rows = []
    for i, (start, label) in enumerate(ledger):
        end = ledger[i + 1][0] - timedelta(days=1) if i + 1 < len(ledger) else None
        rows.append({
            "start": start, "end": end, "label": label,
            "is_current": bool(current) and start == current[0],
            "txn_url": (f"/transactions?date_from={start.isoformat()}"
                        f"&date_to={(end or today).isoformat()}"),
        })
    typical = _typical_cycle_length(ledger)
    day = (today - current[0]).days + 1 if current else None
    return {
        "enabled": settings.BUDGET_CYCLE,
        "rows": list(reversed(rows)),  # newest first
        "current": ({"start": current[0], "label": current[1], "day": day}
                    if current else None),
        "typical_length": typical,
        "progress_pct": (min(100, round(day / typical * 100))
                         if current and typical else None),
    }


@router.get("/cycles", response_class=HTMLResponse,
            dependencies=[Depends(require_session)])
async def cycles_view(request: Request, msg: str = "", level: str = "info"):
    today = datetime.now(settings.TIMEZONE).date()
    ctx = _cycles_ctx(today)
    ctx["msg"] = msg
    ctx["level"] = level
    return request.app.state.templates.TemplateResponse(request, "cycles.html", ctx)


@router.post("/cycles/add", dependencies=[Depends(require_session)])
async def cycles_add(
    request: Request,
    start_date: str = Form(""),
    label: str = Form(""),
):
    start_date = start_date.strip()
    label = label.strip()

    if not start_date:
        return _redirect("Start date is required.")
    try:
        d = date.fromisoformat(start_date)
    except ValueError:
        return _redirect(f"Invalid date: '{start_date}'. Use YYYY-MM-DD format.")

    if len(label) > _MAX_LABEL:
        return _redirect(f"Label too long (max {_MAX_LABEL} characters).")

    if not label:
        existing = load_cycles()
        existing_dates = [c[0] for c in existing]
        label = _dedup_cycle_label(d, existing_dates)

    added = save_cycle_boundary(d, label)
    if not added:
        return _redirect(f"A cycle boundary already exists for {start_date}.")

    return _redirect(f"Cycle '{label}' added.", level="ok")


@router.post("/cycles/{start_date}/rename", dependencies=[Depends(require_session)])
async def cycles_rename(
    request: Request,
    start_date: str,
    label: str = Form(""),
):
    label = label.strip()
    if not label:
        return _redirect("Label cannot be empty.")
    if len(label) > _MAX_LABEL:
        return _redirect(f"Label too long (max {_MAX_LABEL} characters).")

    try:
        date.fromisoformat(start_date)
    except ValueError:
        return _redirect(f"Invalid date: '{start_date}'.")

    updated = rename_cycle_boundary(start_date, label)
    if not updated:
        return _redirect(f"No cycle boundary found for {start_date}.")

    return _redirect(f"Cycle renamed to '{label}'.", level="ok")


@router.post("/cycles/{start_date}/delete", dependencies=[Depends(require_session)])
async def cycles_delete(
    request: Request,
    start_date: str,
):
    try:
        date.fromisoformat(start_date)
    except ValueError:
        return _redirect(f"Invalid date: '{start_date}'.")

    deleted = delete_cycle_boundary(start_date)
    if not deleted:
        return _redirect(f"No cycle boundary found for {start_date}.")

    return _redirect(f"Cycle boundary for {start_date} deleted.", level="ok")


@router.post("/cycles/detect", response_class=HTMLResponse,
             dependencies=[Depends(require_session)])
async def cycles_detect(
    request: Request,
    extra_keywords: str = Form(""),
):
    """
    Scan transaction history for unrecorded salary arrivals and render
    a detect-results page. If keyword detection finds nothing, falls back
    to the largest income rows near each uncovered month boundary.
    """
    today = datetime.now(settings.TIMEZONE).date()
    extra = [kw.strip() for kw in extra_keywords.replace(",", " ").split() if kw.strip()]

    candidates: list[dict] = []
    error: str | None = None
    try:
        df = load_transactions()
        existing = load_cycles()
        candidates = detect_cycle_candidates(df, existing, extra or None)
        if not candidates:
            # Fallback: largest income rows near the start of each uncovered month
            anchor = date(today.year, today.month, 1)
            candidates = fallback_income_candidates(df, anchor, existing)
    except Exception as exc:
        log.exception("Cycle detect failed")
        error = f"Detection failed: {exc}"

    # Enrich candidates with auto-generated labels
    existing_after = load_cycles()
    existing_dates_after = [c[0] for c in existing_after]
    for cand in candidates:
        d = cand["date"]
        cand["label"] = _dedup_cycle_label(d, existing_dates_after)
        cand["amounts_str"] = ", ".join(str(a) for a in cand.get("amounts", []))

    ctx = _cycles_ctx(today)
    ctx.update({
        "detect_candidates": candidates,
        "detect_error": error,
        "detect_extra": extra_keywords,
        "msg": "",
        "level": "info",
    })
    return request.app.state.templates.TemplateResponse(
        request, "cycles_detect.html", ctx)
