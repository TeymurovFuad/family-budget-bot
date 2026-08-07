"""web/routes/drafts.py - manage pending /bulk drafts in the web UI.

Shows all saved user draft files and allows bulk fixes before the user
returns to Telegram to save/cancel the draft.
"""

from collections.abc import Sequence
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from bulk_drafts import archive_user_draft, list_user_drafts, load_user_draft, save_user_draft
from storage_facade import load_reference_data
from web.auth import require_session

router = APIRouter()

_BULK_FIELDS = ("category", "person", "type", "currency")
_BULK_ACTIONS = ("set_field", "drop", "restore")


def _redirect(user_id: int | None, msg: str, level: str = "success") -> RedirectResponse:
    params = {}
    if user_id is not None:
        params["user_id"] = int(user_id)
    if msg:
        params["msg"] = msg
        params["level"] = level
    url = "/drafts"
    if params:
        url = f"/drafts?{urlencode(params)}"
    return RedirectResponse(url, status_code=303)


def _selected_user_id(request: Request, available: list[int]) -> int | None:
    if not available:
        return None
    raw = request.query_params.get("user_id", "").strip()
    if not raw:
        return available[0]
    try:
        picked = int(raw)
    except ValueError:
        return available[0]
    return picked if picked in available else available[0]


def _parse_selected_indices(raw_values: Sequence[object], total_rows: int) -> list[int]:
    idxs: set[int] = set()
    for raw in raw_values:
        try:
            idx = int(str(raw).strip())
        except (TypeError, ValueError):
            continue
        if 0 <= idx < total_rows:
            idxs.add(idx)
    return sorted(idxs)


@router.get("/drafts", response_class=HTMLResponse,
            dependencies=[Depends(require_session)])
async def drafts_page(request: Request):
    ref = load_reference_data()
    draft_infos = list_user_drafts()
    user_ids = [d.user_id for d in draft_infos]
    selected_user_id = _selected_user_id(request, user_ids)
    rows = load_user_draft(selected_user_id) if selected_user_id is not None else []
    selected_info = next((d for d in draft_infos if d.user_id == selected_user_id), None)

    ctx = {
        "draft_infos": draft_infos,
        "selected_user_id": selected_user_id,
        "selected_info": selected_info,
        "rows": rows,
        "categories": ref["categories"],
        "persons": ref["persons"],
        "txn_types": ref["txn_types"],
        "currencies": ref.get("currencies") or [],
        "msg": request.query_params.get("msg", ""),
        "level": request.query_params.get("level", "success"),
    }
    return request.app.state.templates.TemplateResponse(request, "drafts.html", ctx)


@router.post("/drafts/{user_id}/bulk-update", dependencies=[Depends(require_session)])
async def drafts_bulk_update(request: Request, user_id: int):
    rows = load_user_draft(user_id)
    if not rows:
        return _redirect(user_id, "Draft not found.", "error")

    form = await request.form()
    action = str(form.get("action", "")).strip()
    if action not in _BULK_ACTIONS:
        return _redirect(user_id, "Unknown action.", "error")

    idxs = _parse_selected_indices(list(form.getlist("row_idx")), len(rows))
    if not idxs:
        return _redirect(user_id, "Select at least one row first.", "error")

    if action == "set_field":
        field = str(form.get("bulk_field", "")).strip()
        value = str(form.get("bulk_value", "")).strip()
        if field not in _BULK_FIELDS:
            return _redirect(user_id, "Choose a valid field.", "error")
        if not value:
            return _redirect(user_id, "Choose a value.", "error")

        ref = load_reference_data()
        allowed = {
            "category": set(ref["categories"]),
            "person": set(ref["persons"]),
            "type": set(ref["txn_types"]),
            "currency": set(ref.get("currencies") or []),
        }[field]
        if value not in allowed:
            return _redirect(user_id, f"Invalid {field}: {value}", "error")

        for idx in idxs:
            if isinstance(rows[idx], dict):
                rows[idx][field] = value
        save_user_draft(user_id, rows)
        return _redirect(user_id, f"Updated {len(idxs)} row(s): set {field} = {value}.")

    if action == "drop":
        for idx in idxs:
            if isinstance(rows[idx], dict):
                rows[idx]["dropped"] = True
        save_user_draft(user_id, rows)
        return _redirect(user_id, f"Dropped {len(idxs)} row(s).")

    # action == "restore"
    restored = 0
    for idx in idxs:
        if isinstance(rows[idx], dict) and rows[idx].pop("dropped", None):
            restored += 1
    save_user_draft(user_id, rows)
    return _redirect(user_id, f"Restored {restored} row(s).")


@router.post("/drafts/{user_id}/archive", dependencies=[Depends(require_session)])
async def drafts_archive(user_id: int):
    archived = archive_user_draft(user_id)
    if archived is None:
        return _redirect(user_id, "Draft not found.", "error")
    return _redirect(None, f"Archived draft for user {user_id}.")
