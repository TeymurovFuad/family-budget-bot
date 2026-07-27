import logging
import os
import time
import tempfile
from pathlib import Path

from logger import SafeStreamHandler, _cleanup_old_logs, _LOG_RETENTION_DAYS


class Cp1252Stream:
    def __init__(self):
        self.chunks = []
        self.encoding = "cp1252"

    def write(self, msg):
        msg.encode("cp1252", errors="strict")
        self.chunks.append(msg)
        return len(msg)

    def flush(self):
        return None


def test_safe_stream_handler_replaces_unsupported_chars():
    stream = Cp1252Stream()
    handler = SafeStreamHandler(stream=stream)
    handler.setFormatter(logging.Formatter("%(message)s"))

    record = logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="Żółć",
        args=(),
        exc_info=None,
    )

    handler.emit(record)

    written = "".join(stream.chunks)
    # The cp1252 stream cannot encode 'Żółć' — the handler must degrade the
    # unsupported characters (backslashreplace/replace) instead of crashing,
    # while still emitting the record.
    assert written, "handler emitted nothing"
    assert "Żółć" not in written           # raw unicode couldn't pass through
    assert ("\\u" in written or "?" in written), "unsupported chars not replaced"


def test_cleanup_old_logs_removes_rotated_files():
    """Rotated log files older than 180 days must be deleted by _cleanup_old_logs."""
    with tempfile.TemporaryDirectory() as tmp:
        log_dir = Path(tmp)

        # Create a rotated log file with a name matching the rotation pattern
        old_log = log_dir / "budget-bot.log.2025-01-01"
        old_log.write_text("old log content")

        # Set mtime to 200 days ago (well beyond 180-day retention)
        old_mtime = time.time() - (200 * 24 * 3600)
        os.utime(old_log, (old_mtime, old_mtime))

        _cleanup_old_logs(log_dir)

        assert not old_log.exists(), "Old rotated log file should have been deleted"


def test_config_does_not_call_basic_config():
    """
    Regression: config.py used to call logging.basicConfig() at import time,
    installing a second console handler alongside logger.init_logging()'s
    handlers — duplicate console lines and a partially overridden LOG_LEVEL.
    logger.init_logging() must be the single owner of root logger setup.
    """
    source = Path(__file__).parent.parent.joinpath("config.py").read_text(encoding="utf-8")
    assert "logging.basicConfig(" not in source
