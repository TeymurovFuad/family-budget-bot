"""Centralized logging setup.

Creates a daily rotating log file and console output. Keeps the last
20 log files (approx 20 days) and deletes older files on startup.

Usage:
    from logger import init_logging, get_logger
    init_logging()
    log = get_logger(__name__)
    log.info("startup")
"""
from __future__ import annotations

import logging
import logging.handlers
from pathlib import Path
from datetime import datetime, timedelta

import settings


class SafeStreamHandler(logging.StreamHandler):
    """Stream handler that safely writes Unicode to non-UTF-8 consoles."""

    def __init__(self, stream=None):
        super().__init__(stream=stream)

    def _sanitize_text(self, text: str) -> str:
        encoding = getattr(self.stream, "encoding", None) or "utf-8"
        try:
            return text.encode(encoding, errors="replace").decode(encoding)
        except LookupError:
            return text.encode("utf-8", errors="replace").decode("utf-8")

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            stream = self.stream
            if stream is None:
                return
            safe_msg = self._sanitize_text(msg)
            stream.write(safe_msg + self.terminator)
            self.flush()
        except Exception:
            self.handleError(record)


def _ensure_log_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def _cleanup_old_logs(path: Path, keep_days: int = 20) -> None:
    """Delete log files older than `keep_days` days in `path`."""
    cutoff = datetime.now() - timedelta(days=keep_days)
    for p in path.glob("*.log"):
        try:
            mtime = datetime.fromtimestamp(p.stat().st_mtime)
            if mtime < cutoff:
                p.unlink()
        except Exception:
            # best-effort cleanup
            pass


def init_logging(level: int | str = None, *, keep_days: int | None = None) -> None:
    """Initialize root logging configuration.

    - Daily rotating file handler (midnight), keeps `keep_days` backups.
    - Console StreamHandler.
    - Simple timestamped formatter.
    """
    log_dir = settings.LOG_DIR
    _ensure_log_dir(log_dir)
    if keep_days is None:
        keep_days = settings.LOG_KEEP_DAYS
    _cleanup_old_logs(log_dir, keep_days=keep_days)

    root = logging.getLogger()
    if level is None:
        level = settings.LOG_LEVEL
    root.setLevel(level)

    # Avoid duplicate handlers on repeated init
    if any(isinstance(h, logging.handlers.TimedRotatingFileHandler) for h in root.handlers):
        return

    log_file = str(log_dir / "budget-bot.log")
    file_handler = logging.handlers.TimedRotatingFileHandler(
        filename=log_file,
        when="midnight",
        interval=1,
        backupCount=keep_days,
        utc=True,
    )
    file_formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s")
    file_handler.setFormatter(file_formatter)
    file_handler.setLevel(level)
    root.addHandler(file_handler)

    console = SafeStreamHandler()
    if hasattr(console.stream, "reconfigure"):
        console.stream.reconfigure(encoding="utf-8")
    console_formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s")
    console.setFormatter(console_formatter)
    console.setLevel(level)
    root.addHandler(console)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
