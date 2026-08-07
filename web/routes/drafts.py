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
from validators import resolve_fallback_category, validate_parsed_row
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


def _revalidate_draft_row(row: dict, lists: dict) -> None:
    """Recompute one row's invalid state after web-side edits."""
    if not isinstance(row, dict):
        return

    categories = lists.get("categories") or []
    if not str(row.get("type") or "").strip():
        row["type"] = "Expense"
    if categories and not str(row.get("category") or "").strip():
        row["category"] = resolve_fallback_category(categories)

    ok, reason, normalized, _ = validate_parsed_row(row, lists)
    if ok:
        row.pop("invalid", None)
        for field in ("value", "type", "category", "currency"):
            row[field] = normalized[field]
        return
    row["invalid"] = reason


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
    ref = load_reference_data()
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
                _revalidate_draft_row(rows[idx], ref)
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
        if isinstance(rows[idx], dict):
            if rows[idx].pop("dropped", None):
                restored += 1
            _revalidate_draft_row(rows[idx], ref)
    save_user_draft(user_id, rows)
    return _redirect(user_id, f"Restored {restored} row(s).")


@router.post("/drafts/{user_id}/row/{row_idx}/update", dependencies=[Depends(require_session)])
async def drafts_row_update(request: Request, user_id: int, row_idx: int):
    """Single-row edit path for Drafts UI."""
    rows = load_user_draft(user_id)
    if not rows:
        return _redirect(user_id, "Draft not found.", "error")
    if row_idx < 0 or row_idx >= len(rows) or not isinstance(rows[row_idx], dict):
        return _redirect(user_id, "Row not found.", "error")

    form = await request.form()
    row = rows[row_idx]
    ref = load_reference_data()

    updated = {
        "date": str(form.get("date", row.get("date", ""))).strip(),
        "value": str(form.get("value", row.get("value", ""))).strip(),
        "currency": str(form.get("currency", row.get("currency", ""))).strip(),
        "type": str(form.get("type", row.get("type", ""))).strip(),
        "category": str(form.get("category", row.get("category", ""))).strip(),
        "person": str(form.get("person", row.get("person", ""))).strip(),
        "description": str(form.get("description", row.get("description", ""))).strip(),
    }
    row.update(updated)
    _revalidate_draft_row(row, ref)
    save_user_draft(user_id, rows)
    return _redirect(user_id, f"Updated row {row_idx + 1}.")


@router.post("/drafts/{user_id}/row/{row_idx}/toggle-drop", dependencies=[Depends(require_session)])
async def drafts_row_toggle_drop(user_id: int, row_idx: int):
    """Single-row drop/restore toggle."""
    rows = load_user_draft(user_id)
    if not rows:
        return _redirect(user_id, "Draft not found.", "error")
    if row_idx < 0 or row_idx >= len(rows) or not isinstance(rows[row_idx], dict):
        return _redirect(user_id, "Row not found.", "error")

    row = rows[row_idx]
    if row.get("dropped"):
        row.pop("dropped", None)
        action = "restored"
    else:
        row["dropped"] = True
        action = "dropped"
    save_user_draft(user_id, rows)
    return _redirect(user_id, f"Row {row_idx + 1} {action}.")


@router.post("/drafts/{user_id}/archive", dependencies=[Depends(require_session)])
async def drafts_archive(user_id: int):
    archived = archive_user_draft(user_id)
    if archived is None:
        return _redirect(user_id, "Draft not found.", "error")
    return _redirect(None, f"Archived draft for user {user_id}.")
