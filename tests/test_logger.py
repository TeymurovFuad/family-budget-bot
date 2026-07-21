import logging
from pathlib import Path

from logger import SafeStreamHandler


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


def test_config_does_not_call_basic_config():
    """
    Regression: config.py used to call logging.basicConfig() at import time,
    installing a second console handler alongside logger.init_logging()'s
    handlers — duplicate console lines and a partially overridden LOG_LEVEL.
    logger.init_logging() must be the single owner of root logger setup.
    """
    source = Path(__file__).parent.parent.joinpath("config.py").read_text(encoding="utf-8")
    assert "logging.basicConfig(" not in source
