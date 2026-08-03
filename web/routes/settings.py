"""web/routes/settings.py — GET /settings page and POST /settings/sync."""
import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from web.auth import require_session
from storage_facade import get_last_export_time, trigger_excel_export

log = logging.getLogger(__name__)
router = APIRouter()


@router.get("/settings", response_class=HTMLResponse,
            dependencies=[Depends(require_session)])
async def settings_page(request: Request):
    last_sync = get_last_export_time()
    ctx = {"last_sync": last_sync}
    return request.app.state.templates.TemplateResponse(
        request, "settings.html", ctx)


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
