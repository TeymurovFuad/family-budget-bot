"""
web/routes/cycles.py — GET /cycles — read-only cycle-ledger view.

Mirrors what `/cycle` and `/cycle list` show in the bot: current cycle
(start, label, day count) via cycles.current_cycle_start, plus every
recorded boundary with its span, via cycles.load_cycles.

v2 (Ledger redesign): each history row links into
/transactions?date_from=...&date_to=... for that cycle's range, and the
current-cycle card shows a progress bar when a typical cycle length is
derivable from history (median of completed cycle lengths) — omitted
otherwise rather than fabricated.
"""

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

import settings
from cycles import current_cycle_start, load_cycles
from web.auth import require_session

router = APIRouter()


def _typical_cycle_length(ledger: list) -> int | None:
    """Median length in days of COMPLETED cycles; None with <2 boundaries."""
    lengths = sorted((ledger[i + 1][0] - ledger[i][0]).days
                     for i in range(len(ledger) - 1))
    if not lengths:
        return None
    mid = len(lengths) // 2
    if len(lengths) % 2:
        return lengths[mid]
    return round((lengths[mid - 1] + lengths[mid]) / 2)


@router.get("/cycles", response_class=HTMLResponse,
            dependencies=[Depends(require_session)])
async def cycles_view(request: Request):
    today = datetime.now(settings.TIMEZONE).date()
    ledger = load_cycles()
    current = current_cycle_start(today, ledger)
    rows = []
    for i, (start, label) in enumerate(ledger):
        end = ledger[i + 1][0] - timedelta(days=1) if i + 1 < len(ledger) else None
        rows.append({
            "start": start, "end": end, "label": label,
            "is_current": bool(current) and start == current[0],
            # Link target into the Transactions page for this cycle's range;
            # the open cycle ends "today" for filtering purposes.
            "txn_url": (f"/transactions?date_from={start.isoformat()}"
                        f"&date_to={(end or today).isoformat()}"),
        })
    typical = _typical_cycle_length(ledger)
    day = (today - current[0]).days + 1 if current else None
    ctx = {
        "enabled": settings.BUDGET_CYCLE,
        "rows": list(reversed(rows)),  # newest first
        "current": ({"start": current[0], "label": current[1], "day": day}
                    if current else None),
        "typical_length": typical,
        "progress_pct": (min(100, round(day / typical * 100))
                         if current and typical else None),
    }
    return request.app.state.templates.TemplateResponse(request, "cycles.html", ctx)
