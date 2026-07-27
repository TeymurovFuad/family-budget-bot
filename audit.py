"""
audit.py — one structured log line per workbook save attempt.

Every write to the Excel file (single add, batch, delete, edit, rate update,
recovery replay) emits exactly one AUDIT line with who did it, where it came
from, how many rows, the outcome, and how long the save took:

    AUDIT save user=123 source=append rows=1 outcome=ok duration_ms=41.7

Lines go through the standard logging tree, so they land in the same daily
rotating budget-bot.log as everything else (see logger.init_logging) and can
be grepped with `grep "AUDIT save"`.
"""

import time
from contextlib import contextmanager

from logger import get_logger

_audit_log = get_logger("audit")


def audit_save(*, source: str, rows: int, outcome: str, duration_ms: float,
               user=None) -> None:
    """Emit one structured audit line for a save attempt."""
    _audit_log.info(
        "AUDIT save user=%s source=%s rows=%d outcome=%s duration_ms=%.1f",
        user if user is not None else "-", source, rows, outcome, duration_ms,
    )


@contextmanager
def audit_span(source: str, *, rows: int = 0, user=None):
    """
    Time a save operation and emit exactly one audit line on the way out —
    outcome=ok on success, outcome=error (then re-raise) on failure.
    """
    start = time.perf_counter()
    try:
        yield
    except BaseException:
        audit_save(source=source, rows=rows, outcome="error",
                   duration_ms=(time.perf_counter() - start) * 1000, user=user)
        raise
    audit_save(source=source, rows=rows, outcome="ok",
               duration_ms=(time.perf_counter() - start) * 1000, user=user)
