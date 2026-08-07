"""bulk_drafts.py - shared persistence helpers for /bulk draft rows."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import settings

DRAFT_FILE_SUFFIX = ".json"
DRAFT_ARCHIVE_DIR_NAME = "archive"


@dataclass(frozen=True)
class DraftInfo:
    user_id: int
    path: Path
    row_count: int
    invalid_count: int
    dropped_count: int
    display_name: str = ""  # Human-readable label (username or user ID string)


def draft_directory() -> Path:
    return settings.BULK_DRAFTS_DIR


def user_draft_path(user_id: int) -> Path:
    return draft_directory() / f"{int(user_id)}{DRAFT_FILE_SUFFIX}"


def load_user_draft(user_id: int) -> list[dict]:
    path = user_draft_path(user_id)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    return data if isinstance(data, list) else []


def save_user_draft(user_id: int, rows: list[dict]) -> None:
    path = user_draft_path(user_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")


def archive_user_draft(user_id: int) -> Path | None:
    path = user_draft_path(user_id)
    if not path.exists():
        return None
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    archive_dir = draft_directory() / DRAFT_ARCHIVE_DIR_NAME
    archive_dir.mkdir(parents=True, exist_ok=True)
    target = archive_dir / f"{int(user_id)}-{stamp}{DRAFT_FILE_SUFFIX}"
    path.rename(target)
    return target


def list_user_drafts() -> list[DraftInfo]:
    base = draft_directory()
    if not base.exists():
        return []
    items: list[DraftInfo] = []
    for path in sorted(base.glob(f"*{DRAFT_FILE_SUFFIX}")):
        try:
            user_id = int(path.stem)
        except ValueError:
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(data, list):
            continue
        invalid_count = sum(1 for row in data if isinstance(row, dict) and row.get("invalid"))
        dropped_count = sum(1 for row in data if isinstance(row, dict) and row.get("dropped"))
        items.append(DraftInfo(
            user_id=user_id,
            path=path,
            row_count=len(data),
            invalid_count=invalid_count,
            dropped_count=dropped_count,
            display_name=str(user_id),
        ))
    return items
