"""
_repair_guard.py — shared safety guard for one-off repair/maintenance scripts.

These scripts open the Excel workbook directly with openpyxl and are NOT
part of the bot's normal write path (excel_ops.py / file_storage.py), so
they bypass the bot's in-process write lock and its atomic-save convention.
Running one next to a live bot process risks a lost update (bot writes, or
a bot write is in flight, while the script's stale in-memory copy overwrites
it) or, on gcs/s3, silently editing a local file the bot never uploads.

This guard enforces:
  1. Only run against the local backend. On gcs/s3 the "live" file lives in
     the bucket, not on disk — editing the local copy would be a silent
     no-op from the bot's point of view.
  2. Take an exclusive lock file for the duration of the script so two
     repair scripts (or a repair script + a crashed previous run) can't
     race on the same workbook.

Usage:
    from _repair_guard import repair_guard
    from file_storage import atomic_save

    with repair_guard():
        wb = openpyxl.load_workbook(path)
        ...
        atomic_save(wb, path)
"""
import sys
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import settings
from file_storage import _active_backend

LOCK_PATH = Path(settings.XLSX_PATH).with_suffix(".repair.lock")


def _guard_local_backend() -> None:
    backend = _active_backend()
    if backend != "local":
        print(
            f"Refusing to run: STORAGE_BACKEND={backend!r}. Repair scripts only edit "
            "the local file directly — on gcs/s3 that file is not the one the bot "
            "reads/writes, so changes would silently be lost. Run this on a machine "
            "with STORAGE_BACKEND=local (or temporarily unset gcs/s3 settings) for a "
            "one-off maintenance pass, then let the bot re-upload if needed.",
            file=sys.stderr,
        )
        sys.exit(1)


@contextmanager
def repair_guard(lock_path: Path = LOCK_PATH):
    """
    Refuse to run against a non-local backend, then take an exclusive lock
    file for the duration of the `with` block so concurrent repair scripts
    (or the bot) can't race on the same workbook.
    """
    _guard_local_backend()
    if lock_path.exists():
        print(
            f"Refusing to run: lock file {lock_path} already exists — another "
            "repair script may be running (or a previous run crashed before "
            "cleaning up). Make sure nothing else is writing, then delete the "
            "lock file manually and retry.",
            file=sys.stderr,
        )
        sys.exit(1)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock_path.write_text("locked")
    try:
        yield
    finally:
        lock_path.unlink(missing_ok=True)
