"""
recovery_queue.py — append-only journal for writes that failed to persist.

Split out of file_storage.py (which remains the public facade).

Format
------
The queue file (settings.RECOVERY_QUEUE_PATH) is an append-only JSONL
journal: one typed operation per line, e.g.

    {"op": "append", "ts": "2026-07-27T10:00:00+00:00", "row": {...}}

Appending is a single O(1) file append — no read-modify-write, so two
near-simultaneous failures can no longer clobber each other's queued rows.

Backward compatibility: the previous format was a whole-file JSON array of
raw rows (written as a single line by json.dumps). flush_recovery_queue()
transparently reads both — a line that parses as a list is treated as a
legacy queue and its rows are migrated into the result; a line that parses
as a dict is either an op envelope ({"op", "row"}) or a raw row.

The path is read lazily through file_storage so tests that monkeypatch
`file_storage.RECOVERY_QUEUE_PATH` keep working unchanged.
"""

import json
from datetime import datetime, timezone
from pathlib import Path

from logger import get_logger

log = get_logger(__name__)


def _queue_path() -> Path:
    import file_storage
    return file_storage.RECOVERY_QUEUE_PATH


def append_to_recovery_queue(row: dict, op: str = "append") -> None:
    """Journal one failed operation as a single appended JSONL line."""
    path = _queue_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "op": op,
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "row": row,
    }
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, default=str) + "\n")
        f.flush()


def _unwrap(entry: dict) -> dict | None:
    """Return the transaction row from a journal entry (or a raw legacy row)."""
    if "op" in entry and "row" in entry:
        if entry.get("op") != "append":
            # Typed ops other than "append" are reserved for future
            # delete/edit journaling — never silently apply an unknown op.
            log.warning("Recovery queue: skipping unsupported op %r", entry.get("op"))
            return None
        return entry["row"]
    return entry  # raw legacy row dict


def flush_recovery_queue() -> list[dict]:
    """
    Read pending recovery rows WITHOUT deleting the file. The caller must
    call delete_recovery_queue_file() only after the rows have been fully
    replayed, so a crash mid-replay can't lose queued data.

    Understands both the JSONL journal and the legacy whole-file JSON array.
    If the file cannot be parsed at all, it is quarantined with a `.corrupt`
    suffix and an empty list is returned instead of raising, so startup is
    never blocked by a corrupted queue file.
    """
    path = _queue_path()
    if not path.exists():
        return []

    rows: list[dict] = []
    corrupt = False
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        log.error("Could not read recovery queue file %s: %s", path, e)
        return []

    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
        except (json.JSONDecodeError, ValueError) as e:
            log.error("Recovery queue: corrupt line in %s: %s", path, e)
            corrupt = True
            continue
        if isinstance(parsed, list):
            # Legacy format: the whole old queue serialized on one line.
            rows.extend(r for r in parsed if isinstance(r, dict))
        elif isinstance(parsed, dict):
            row = _unwrap(parsed)
            if row is not None:
                rows.append(row)
        else:
            log.error("Recovery queue: unexpected entry type %s — skipping", type(parsed))
            corrupt = True

    if corrupt and not rows:
        _quarantine_corrupt_queue_file(path)
    return rows


def _quarantine_corrupt_queue_file(path: Path) -> None:
    corrupt_path = path.with_name(path.name + ".corrupt")
    log.error("Recovery queue file is corrupt, quarantining to %s", corrupt_path)
    try:
        path.replace(corrupt_path)
    except Exception as e2:
        # One fallback attempt: delete the corrupt file so the next flush
        # doesn't hit the same JSONDecodeError and repeat the failing
        # rename forever. If even that fails, alert loudly and give up —
        # this needs operator attention (file locked / permissions).
        log.error("Failed to quarantine corrupt recovery queue file: %s", e2)
        try:
            path.unlink()
            log.warning(
                "Deleted corrupt recovery queue file %s after quarantine "
                "rename failed — its contents are lost.",
                path,
            )
        except Exception as e3:
            log.critical(
                "OPERATOR ACTION NEEDED: corrupt recovery queue file %s "
                "could not be quarantined or deleted (%s). Every flush "
                "will keep failing until it is removed manually.",
                path, e3,
            )


def requeue_rows(rows: list[dict]) -> None:
    """
    Atomically persist the given rows as the complete new queue.

    Used after a replay attempt: the old journal has been consumed and only
    the rows that still failed must survive. Written in the legacy list
    format (single atomic write) so a crash mid-requeue can't leave a
    half-written journal.
    """
    import os

    path = _queue_path()
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(rows, default=str), encoding="utf-8")
    os.replace(tmp, path)


def delete_recovery_queue_file() -> None:
    """Remove the recovery queue file. Call only after replay has fully completed."""
    _queue_path().unlink(missing_ok=True)
