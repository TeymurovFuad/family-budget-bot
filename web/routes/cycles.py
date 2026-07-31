"""
web/routes/cycles.py — GET /cycles — read-only cycle-ledger view.

Mirrors what `/cycle` and `/cycle list` show in the bot: current cycle
(start, label, day count) via cycles.current_cycle_start, plus every
recorded boundary with its span, via cycles.load_cycles.
"""

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

import settings
from cycles import current_cycle_start, load_cycles
from web.auth import require_session

router = APIRouter()


@router.get("/cycles", response_class=HTMLResponse,
            dependencies=[Depends(require_session)])
async def cycles_view(request: Request):
    today = datetime.now(settings.TIMEZONE).date()
    ledger = load_cycles()
    current = current_cycle_start(today, ledger)
    rows = []
    for i, (start, label) in enumerate(ledger):
        end = ledger[i + 1][0] - timedelta(days=1) if i + 1 < len(ledger) else None
        rows.append({"start": start, "end": end, "label": label})
    ctx = {
        "enabled": settings.BUDGET_CYCLE,
        "rows": list(reversed(rows)),  # newest first
        "current": ({"start": current[0], "label": current[1],
                     "day": (today - current[0]).days + 1}
                    if current else None),
    }
    return request.app.state.templates.TemplateResponse(request, "cycles.html", ctx)
