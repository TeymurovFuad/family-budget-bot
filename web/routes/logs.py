"""
web/routes/logs.py — GET /logs

Owner-facing log viewer. Reads from the end of the log file in chunks
(never loads the full file into memory). Supports level filter, date
selector, full-text search, logger filter, and pagination.
"""

import re
from datetime import date as _date
from pathlib import Path
from typing import Optional

import settings
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from web.auth import require_session

router = APIRouter()

_LOG_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d+) \| (\w+) \| ([^\|]+) \| (.+)$"
)
_CHUNK = 32 * 1024  # 32 KB
_MAX_LINES = 10_000
_PAGE_SIZE = 100


def _log_file(selected_date: str) -> Path:
    today = _date.today().isoformat()
    if selected_date == today:
        return settings.LOG_DIR / "budget-bot.log"
    return settings.LOG_DIR / f"budget-bot.log.{selected_date}"


def _available_dates() -> list[str]:
    today = _date.today().isoformat()
    dates = [today]
    log_dir = settings.LOG_DIR
    if log_dir.is_dir():
        for f in sorted(log_dir.glob("budget-bot.log.*"), reverse=True):
            suffix = f.suffix.lstrip(".")
            # suffix is the date portion e.g. 2026-08-07
            if re.match(r"^\d{4}-\d{2}-\d{2}$", suffix):
                dates.append(suffix)
    return dates


def _read_tail(path: Path, max_lines: int = _MAX_LINES) -> list[str]:
    """Read the last max_lines lines from path using backward chunk reads."""
    if not path.is_file():
        return []
    chunks: list[bytes] = []
    with open(path, "rb") as fh:
        fh.seek(0, 2)
        remaining = fh.tell()
        while remaining > 0 and sum(len(c) for c in chunks) < max_lines * 200:
            read_size = min(_CHUNK, remaining)
            remaining -= read_size
            fh.seek(remaining)
            chunks.append(fh.read(read_size))
    raw = b"".join(reversed(chunks))
    lines = raw.decode("utf-8", errors="replace").splitlines()
    return lines[-max_lines:]


def _parse_and_filter(
    lines: list[str],
    level: str,
    q: str,
    logger_filter: str,
) -> list[dict]:
    keep_levels: set[str]
    if level == "ERROR":
        keep_levels = {"ERROR"}
    elif level == "WARNING":
        keep_levels = {"WARNING", "ERROR"}
    else:
        keep_levels = set()  # ALL — no level filter

    q_lower = q.strip().lower()
    logger_lower = logger_filter.strip().lower()

    results: list[dict] = []
    for line in lines:
        m = _LOG_RE.match(line.rstrip())
        if not m:
            # Continuation line (e.g. traceback frame) — append to last entry.
            if results:
                results[-1]["message"] += "\n" + line.rstrip()
            continue
        ts, lvl, logger, message = m.group(1), m.group(2), m.group(3).strip(), m.group(4).strip()
        if keep_levels and lvl not in keep_levels:
            continue
        if q_lower and q_lower not in message.lower() and q_lower not in logger.lower():
            continue
        if logger_lower and logger_lower != logger.lower():
            continue
        results.append({"ts": ts, "level": lvl, "logger": logger, "message": message})

    # Newest first
    results.reverse()
    return results


@router.get("/logs", response_class=HTMLResponse, dependencies=[Depends(require_session)])
async def logs_page(
    request: Request,
    level: str = "WARNING",
    date: Optional[str] = None,
    q: str = "",
    logger_filter: str = "",
    page: int = 1,
):
    today = _date.today().isoformat()
    # Validate date to prevent path traversal — only accept YYYY-MM-DD format.
    if date and re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        selected_date = date
    else:
        selected_date = today
    if level not in ("WARNING", "ERROR", "ALL"):
        level = "WARNING"
    if page < 1:
        page = 1

    available_dates = _available_dates()
    log_path = _log_file(selected_date)

    raw_lines = _read_tail(log_path)
    entries = _parse_and_filter(raw_lines, level, q, logger_filter)

    # Collect unique loggers from ALL level-filtered lines (before q/logger filter)
    level_filtered = _parse_and_filter(raw_lines, level, "", "")
    loggers = sorted({e["logger"] for e in level_filtered})

    total_entries = len(entries)
    total_pages = max(1, (total_entries + _PAGE_SIZE - 1) // _PAGE_SIZE)
    page = min(page, total_pages)

    start = (page - 1) * _PAGE_SIZE
    page_entries = entries[start : start + _PAGE_SIZE]

    file_missing = not log_path.is_file()

    templates = request.app.state.templates
    return templates.TemplateResponse(
        "logs.html",
        {
            request,
            "entries": page_entries,
            "level": level,
            "selected_date": selected_date,
            "available_dates": available_dates,
            "q": q,
            "logger_filter": logger_filter,
            "loggers": loggers,
            "page": page,
            "total_pages": total_pages,
            "total_entries": total_entries,
            "has_prev": page > 1,
            "has_next": page < total_pages,
            "file_missing": file_missing,
        },
    )
