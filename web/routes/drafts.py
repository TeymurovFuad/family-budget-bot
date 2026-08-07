"""web/routes/drafts.py - manage pending /bulk drafts in the web UI.

Shows all saved user draft files and allows bulk fixes before the user
returns to Telegram to save/cancel the draft.
"""

import asyncio
import logging
import time as _time
from collections import Counter
from collections.abc import Sequence
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from ai_parser import get_peak_hours_status, parse_quick
from bulk_drafts import archive_user_draft, list_user_drafts, load_user_draft, save_user_draft
from storage_facade import load_category_types, load_reference_data
from validators import resolve_fallback_category, validate_parsed_row
from web.auth import require_session

router = APIRouter()
log = logging.getLogger(__name__)

_BULK_FIELDS = ("category", "person", "type", "currency")
_BULK_ACTIONS = (
    "set_field", "drop", "restore", "preview_ai", "apply_ai_preview", "clear_ai_preview"
)
_REANALYZE_MAX_ROWS = 20
_REANALYZE_MAX_PARALLEL = 4
_REANALYZE_TIMEOUT_S = 90.0  # DeepSeek can be slow during peak hours


def _build_categories_by_type(ref: dict, category_types: dict[str, str]) -> dict[str, list[str]]:
    txn_types = [str(t).strip() for t in ref.get("txn_types") or [] if str(t).strip()]
    categories = [str(c).strip() for c in ref.get("categories") or [] if str(c).strip()]
    typed: dict[str, list[str]] = {txn_type: [] for txn_type in txn_types}

    for category in categories:
        mapped_type = str(category_types.get(category) or "").strip()
        if mapped_type in typed:
            typed[mapped_type].append(category)
            continue
        # Unscoped categories (missing/unknown type) remain selectable for all
        # transaction types to avoid false blocks until metadata is curated.
        for txn_type in typed:
            typed[txn_type].append(category)
    return typed


def _allowed_categories_for_type(txn_type: str, categories_by_type: dict[str, list[str]]) -> set[str]:
    return set(categories_by_type.get(str(txn_type or "").strip()) or [])


def _build_reanalyze_text(row: dict, instruction: str) -> str:
    # Exclude current type/category from the primary text so AI can
    # reconsider classification instead of mirroring existing labels.
    parts = [
        str(row.get("date") or "").strip(),
        str(row.get("value") or "").strip(),
        str(row.get("currency") or "").strip(),
        str(row.get("description") or "").strip(),
    ]
    base = " ".join([p for p in parts if p])
    if not base:
        # Keep a final fallback for severely incomplete rows.
        base = " ".join(
            [
                str(row.get("category") or "").strip(),
                str(row.get("type") or "").strip(),
            ]
        ).strip()
    if instruction:
        return f"{base}\n\nInstruction: {instruction}"
    return base


def _clone_row(row: dict) -> dict:
    clone = {}
    for k, v in row.items():
        if k == "_ai_preview":
            continue
        clone[k] = v
    return clone


def _compute_preview_for_row(
    row: dict,
    ref: dict,
    categories_by_type: dict[str, list[str]],
    instruction: str,
    parsed: dict | None = None,
) -> dict:
    if row.get("dropped"):
        return {
            "status": "skipped",
            "reason": "Row is dropped.",
            "changed_fields": [],
            "proposed": {},
            "is_invalid": False,
        }

    if parsed is None:
        text = _build_reanalyze_text(row, instruction)
        parsed = parse_quick(text, ref)
    if not parsed:
        return {
            "status": "unchanged",
            "reason": "AI could not parse this row.",
            "changed_fields": [],
            "proposed": {},
            "is_invalid": False,
        }

    candidate = _clone_row(row)
    for key in ("date", "value", "currency", "type", "category", "description"):
        if key in parsed and parsed.get(key) not in (None, ""):
            candidate[key] = parsed.get(key)

    _revalidate_draft_row(candidate, ref)
    strict_allowed = _allowed_categories_for_type(
        str(candidate.get("type") or "").strip(), categories_by_type
    )
    if strict_allowed and candidate.get("category") not in strict_allowed:
        candidate["invalid"] = (
            f"Category '{candidate.get('category')}' does not match type '{candidate.get('type')}'."
        )

    changed_fields = []
    for key in ("date", "value", "currency", "type", "category", "description"):
        if row.get(key) != candidate.get(key):
            changed_fields.append(key)

    # NOTE: person is not included — AI parser does not return it.
    proposed = {k: candidate.get(k) for k in ("date", "value", "currency", "type", "category", "description")}
    if changed_fields:
        return {
            "status": "changed",
            "reason": candidate.get("invalid") or "",
            "changed_fields": changed_fields,
            "proposed": proposed,
            "is_invalid": bool(candidate.get("invalid")),
        }
    return {
        "status": "unchanged",
        "reason": candidate.get("invalid") or "No changes proposed.",
        "changed_fields": [],
        "proposed": proposed,
        "is_invalid": bool(candidate.get("invalid")),
    }


def _redirect(
    user_id: int | None,
    msg: str,
    level: str = "success",
    row_error: int | None = None,
) -> RedirectResponse:
    params = {}
    if user_id is not None:
        params["user_id"] = int(user_id)
    if msg:
        params["msg"] = msg
        params["level"] = level
    if row_error is not None:
        params["row_error"] = int(row_error)
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


def _preview_error_reason(exc: Exception) -> str:
    """Return a short, user-visible error reason for AI preview failures.

    Auth/connection exception types are returned by class name only — their
    message bodies can embed API keys or internal URLs from the SDK.
    """
    kind = exc.__class__.__name__
    _OPAQUE_KINDS = {
        "AuthenticationError", "PermissionDeniedError",
        "APIConnectionError", "APIStatusError", "RateLimitError",
    }
    if kind in _OPAQUE_KINDS:
        return kind  # no message body — could contain API key or internal URL
    raw = str(exc or "").strip()
    if not raw:
        return kind
    compact = " ".join(raw.split())
    if len(compact) > 180:
        compact = f"{compact[:177]}..."
    return f"{kind}: {compact}"


@router.get("/drafts/test-ai", dependencies=[Depends(require_session)])
async def drafts_test_ai():
    """Health-check: make a real parse_quick call and report provider/model/timing."""
    import settings as _settings

    provider_name = str(_settings.AI_PROVIDER or "unknown")
    # Best-effort model name — providers expose it differently; fall back gracefully.
    try:
        model = str(_settings.DEEPSEEK_MODEL) if provider_name == "deepseek" else provider_name
    except AttributeError:
        model = provider_name

    t0 = _time.monotonic()
    try:
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, lambda: parse_quick("coffee 5", {}))
        elapsed_ms = round((_time.monotonic() - t0) * 1000)
        return JSONResponse({
            "ok": True,
            "provider": provider_name,
            "model": model,
            "elapsed_ms": elapsed_ms,
            "result": result,
        })
    except Exception as exc:
        elapsed_ms = round((_time.monotonic() - t0) * 1000)
        log.warning("AI connection test failed: %s", exc, exc_info=True)
        return JSONResponse({
            "ok": False,
            "provider": provider_name,
            "model": model,
            "elapsed_ms": elapsed_ms,
            "error": _preview_error_reason(exc),
        }, status_code=200)  # always 200 so JS can read the body


@router.get("/drafts", response_class=HTMLResponse,
            dependencies=[Depends(require_session)])
async def drafts_page(request: Request):
    ref = load_reference_data()
    category_types = load_category_types()
    categories_by_type = _build_categories_by_type(ref, category_types)
    draft_infos = list_user_drafts()
    user_ids = [d.user_id for d in draft_infos]
    selected_user_id = _selected_user_id(request, user_ids)
    rows = load_user_draft(selected_user_id) if selected_user_id is not None else []
    selected_info = next((d for d in draft_infos if d.user_id == selected_user_id), None)
    peak_status = get_peak_hours_status()

    ctx = {
        "draft_infos": draft_infos,
        "selected_user_id": selected_user_id,
        "selected_info": selected_info,
        "rows": rows,
        "categories": ref["categories"],
        "persons": ref["persons"],
        "txn_types": ref["txn_types"],
        "currencies": ref.get("currencies") or [],
        "category_by_type": categories_by_type,
        "peak_status": peak_status,
        "msg": request.query_params.get("msg", ""),
        "level": request.query_params.get("level", "success"),
        "row_error": request.query_params.get("row_error", ""),
    }
    return request.app.state.templates.TemplateResponse(request, "drafts.html", ctx)


@router.post("/drafts/{user_id}/bulk-update", dependencies=[Depends(require_session)])
async def drafts_bulk_update(request: Request, user_id: int):
    rows = load_user_draft(user_id)
    if not rows:
        return _redirect(user_id, "Draft not found.", "error")

    form = await request.form()
    ref = load_reference_data()
    category_types = load_category_types()
    categories_by_type = _build_categories_by_type(ref, category_types)
    action = str(form.get("action", "")).strip()
    if action not in _BULK_ACTIONS:
        return _redirect(user_id, "Unknown action.", "error")

    idxs = _parse_selected_indices(list(form.getlist("row_idx")), len(rows))
    if not idxs:
        return _redirect(user_id, "Select at least one row first.", "error")

    if action == "preview_ai":
        if len(idxs) > _REANALYZE_MAX_ROWS:
            return _redirect(
                user_id,
                f"Select at most {_REANALYZE_MAX_ROWS} rows for AI preview.",
                "error",
            )
        instruction = str(form.get("ai_instruction", "")).strip()
        loop = asyncio.get_running_loop()
        semaphore = asyncio.Semaphore(_REANALYZE_MAX_PARALLEL)

        async def _preview_one(idx: int) -> tuple[int, dict]:
            row = rows[idx]
            if not isinstance(row, dict):
                return idx, {
                    "status": "unchanged",
                    "reason": "Row is not editable.",
                    "changed_fields": [],
                    "proposed": {},
                    "is_invalid": False,
                }
            if row.get("dropped"):
                return idx, {
                    "status": "skipped",
                    "reason": "Row is dropped.",
                    "changed_fields": [],
                    "proposed": {},
                    "is_invalid": False,
                }
            try:
                async with semaphore:
                    text = _build_reanalyze_text(row, instruction)
                    parsed = await asyncio.wait_for(
                        loop.run_in_executor(None, lambda: parse_quick(text, ref)),
                        timeout=_REANALYZE_TIMEOUT_S,
                    )
                preview = _compute_preview_for_row(
                    row, ref, categories_by_type, instruction, parsed=parsed
                )
                return idx, preview
            except asyncio.TimeoutError:
                return idx, {
                    "status": "timeout",
                    "reason": "AI preview timed out for this row.",
                    "changed_fields": [],
                    "proposed": {},
                    "is_invalid": False,
                }
            except Exception as exc:
                err = _preview_error_reason(exc)
                log.warning(
                    "Draft AI preview failed for user=%s row=%s: %s",
                    user_id,
                    idx,
                    err,
                    exc_info=True,
                )
                return idx, {
                    "status": "error",
                    "reason": f"AI preview failed: {err}",
                    "changed_fields": [],
                    "proposed": {},
                    "is_invalid": False,
                }

        work = [idx for idx in idxs if isinstance(rows[idx], dict)]
        previews = await asyncio.gather(*[_preview_one(idx) for idx in work])

        changed = 0
        unchanged = 0
        invalid = 0
        failed = 0
        timed_out = 0
        skipped = 0
        error_reasons: list[str] = []
        for idx, preview in previews:
            row = rows[idx]
            row["_ai_preview"] = preview
            status = str(preview.get("status") or "")
            if status == "changed":
                changed += 1
            elif status == "error":
                failed += 1
                reason = str(preview.get("reason") or "").strip()
                if reason:
                    error_reasons.append(reason)
            elif status == "timeout":
                timed_out += 1
            elif status == "skipped":
                skipped += 1
            else:
                unchanged += 1
            if preview.get("is_invalid"):
                invalid += 1
        save_user_draft(user_id, rows)
        log.info(
            "Draft AI preview: user=%s rows=%s instruction=%r changed=%s unchanged=%s invalid=%s failed=%s timed_out=%s skipped=%s",
            user_id, len(idxs), instruction, changed, unchanged, invalid, failed, timed_out, skipped,
        )
        level = "error" if failed or timed_out else "success"
        reason_suffix = ""
        if error_reasons:
            top = Counter(error_reasons).most_common(2)
            summary = "; ".join([f"{reason} ({count}x)" for reason, count in top])
            if summary:
                reason_suffix = f" Top failures: {summary}."
        return _redirect(
            user_id,
            (
                "AI preview ready: "
                f"{changed} changed, {unchanged} unchanged, {invalid} invalid, "
                f"{failed} failed, {timed_out} timed out, {skipped} skipped."
                f"{reason_suffix}"
            ),
            level,
        )

    if action == "apply_ai_preview":
        applied = 0
        for idx in idxs:
            row = rows[idx]
            if not isinstance(row, dict):
                continue
            preview = row.get("_ai_preview") if isinstance(row.get("_ai_preview"), dict) else None
            if not preview or preview.get("status") != "changed":
                continue
            proposed = preview.get("proposed") if isinstance(preview.get("proposed"), dict) else {}
            for key in ("date", "value", "currency", "type", "category", "description"):
                if key in proposed:
                    row[key] = proposed[key]
            _revalidate_draft_row(row, ref)
            strict_allowed = _allowed_categories_for_type(
                str(row.get("type") or "").strip(), categories_by_type
            )
            if strict_allowed and row.get("category") not in strict_allowed:
                row["invalid"] = (
                    f"Category '{row.get('category')}' does not match type '{row.get('type')}'."
                )
            row.pop("_ai_preview", None)
            applied += 1
        save_user_draft(user_id, rows)
        return _redirect(user_id, f"Applied AI preview to {applied} row(s).")

    if action == "clear_ai_preview":
        cleared = 0
        for idx in idxs:
            row = rows[idx]
            if not isinstance(row, dict):
                continue
            if row.pop("_ai_preview", None) is not None:
                cleared += 1
        save_user_draft(user_id, rows)
        return _redirect(user_id, f"Cleared AI preview on {cleared} row(s).")

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

        if field == "category":
            mismatched_rows = 0
            for idx in idxs:
                row = rows[idx]
                if not isinstance(row, dict):
                    continue
                row_type = str(row.get("type") or "Expense").strip()
                allowed_for_type = _allowed_categories_for_type(row_type, categories_by_type)
                if allowed_for_type and value not in allowed_for_type:
                    mismatched_rows += 1
            if mismatched_rows:
                return _redirect(
                    user_id,
                    f"Category '{value}' does not match transaction type for {mismatched_rows} selected row(s).",
                    "error",
                )

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

    categories_by_type = _build_categories_by_type(ref, load_category_types())
    allowed_for_type = _allowed_categories_for_type(updated["type"], categories_by_type)
    if allowed_for_type and updated["category"] and updated["category"] not in allowed_for_type:
        return _redirect(
            user_id,
            f"Category '{updated['category']}' does not match type '{updated['type']}'.",
            "error",
            row_error=row_idx,
        )

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


@router.post("/drafts/{user_id}/row/{row_idx}/apply-ai-preview", dependencies=[Depends(require_session)])
async def drafts_row_apply_ai_preview(request: Request, user_id: int, row_idx: int):
    """Apply the AI suggestion for a single row directly, without the bulk panel."""
    rows = load_user_draft(user_id)
    if not rows:
        return _redirect(user_id, "Draft not found.", "error")
    if row_idx < 0 or row_idx >= len(rows) or not isinstance(rows[row_idx], dict):
        return _redirect(user_id, "Row not found.", "error")
    row = rows[row_idx]
    preview = row.get("_ai_preview") if isinstance(row.get("_ai_preview"), dict) else None
    if not preview or preview.get("status") != "changed":
        return _redirect(user_id, f"No AI suggestion to apply on row {row_idx + 1}.", "error")
    proposed = preview.get("proposed") if isinstance(preview.get("proposed"), dict) else {}
    for key in ("date", "value", "currency", "type", "category", "description"):
        if key in proposed:
            row[key] = proposed[key]
    ref = load_reference_data()
    _revalidate_draft_row(row, ref)
    category_types = load_category_types()
    categories_by_type = _build_categories_by_type(ref, category_types)
    strict_allowed = _allowed_categories_for_type(
        str(row.get("type") or "").strip(), categories_by_type
    )
    if strict_allowed and row.get("category") not in strict_allowed:
        row["invalid"] = f"Category '{row.get('category')}' does not match type '{row.get('type')}'."
    row.pop("_ai_preview", None)
    save_user_draft(user_id, rows)
    return _redirect(user_id, f"Applied AI suggestion to row {row_idx + 1}.")


@router.post("/drafts/{user_id}/archive", dependencies=[Depends(require_session)])
async def drafts_archive(user_id: int):
    archived = archive_user_draft(user_id)
    if archived is None:
        return _redirect(user_id, "Draft not found.", "error")
    return _redirect(None, f"Archived draft for user {user_id}.")
