"""
summary_picker.py — /summary argument parsing and inline-keyboard picker.

Pure helpers only: free-form argument resolution (order-independent month/year,
ledger-first month names, ranges) and keyboard builders for the three-zone
picker shown on bare /summary. No Telegram I/O and no workbook access here —
handlers/reports.py owns the sending; callers pass data in.

Callback-data scheme (prefix "sum:"):
    sum:tm / sum:lm          — this / last calendar month
    sum:tc / sum:lc          — this / last cycle (flag on)
    sum:cal                  — show year picker
    sum:yrs:<page>           — year picker page (Earlier… / Newer…)
    sum:y:<year>             — show month picker for a year
    sum:m:<year>:<month>     — render month report (or range step)
    sum:cyc:<page>           — cycle ledger list page
    sum:cs:<iso-date>        — render report for cycle starting that date
    sum:rng                  — start the From/To range walk
"""

import calendar
import re
from datetime import date, timedelta

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

MONTHS_BY_NAME: dict[str, int] = {}
for _n in range(1, 13):
    MONTHS_BY_NAME[calendar.month_name[_n].lower()] = _n
    MONTHS_BY_NAME[calendar.month_abbr[_n].lower()] = _n

YEARS_PER_PAGE = 8    # two rows of four buttons
CYCLES_PER_PAGE = 8


# ── date helpers ──────────────────────────────────────────────────────────────

def month_last_day(year: int, month: int) -> date:
    return date(year, month, calendar.monthrange(year, month)[1])


def most_recent_year_for_month(month: int, today: date) -> int:
    """Bare 'aug' means the most recent occurrence of August."""
    return today.year if month <= today.month else today.year - 1


def cycle_bounds(cycles: list[tuple[date, str]], index: int, today: date) -> tuple[date, date]:
    """[start, end] for cycles[index]; the newest cycle is open-ended → today."""
    start = cycles[index][0]
    if index + 1 < len(cycles):
        return start, cycles[index + 1][0] - timedelta(days=1)
    return start, today


def _label_month(label: str) -> int | None:
    """Month number from a ledger label like 'Aug 2026', or None."""
    return MONTHS_BY_NAME.get(label.split()[0].lower()) if label.strip() else None


def find_cycle_by_month(
    cycles: list[tuple[date, str]], month: int, today: date
) -> tuple[date, date, str] | None:
    """Latest cycle whose ledger label carries this month → (start, end, label)."""
    for i in range(len(cycles) - 1, -1, -1):
        if cycles[i][0] <= today and _label_month(cycles[i][1]) == month:
            start, end = cycle_bounds(cycles, i, today)
            return start, end, cycles[i][1]
    return None


# ── free-form argument parsing ────────────────────────────────────────────────

_COMBINED = re.compile(r"^(\d{1,2})[./](\d{4})$")
_COMBINED_REV = re.compile(r"^(\d{4})[./](\d{1,2})$")


def _parse_period(tokens: list[str]) -> tuple[int | None, int | None] | None:
    """
    Order-independent (year, month) from tokens like ['aug','2025'], ['2025','aug'],
    ['08.2025'], ['aug'], ['2025']. Returns (year|None, month|None), or None when
    any token is unrecognised or a slot is given twice.
    """
    year: int | None = None
    month: int | None = None

    def put(kind: str, value: int) -> bool:
        nonlocal year, month
        if kind == "y":
            if year is not None:
                return False
            year = value
        else:
            if month is not None:
                return False
            month = value
        return True

    for tok in tokens:
        tok = tok.strip().lower()
        if not tok:
            continue
        m = _COMBINED.match(tok)
        if m:
            mo, yr = int(m.group(1)), int(m.group(2))
            if not 1 <= mo <= 12 or not (put("m", mo) and put("y", yr)):
                return None
            continue
        m = _COMBINED_REV.match(tok)
        if m:
            yr, mo = int(m.group(1)), int(m.group(2))
            if not 1 <= mo <= 12 or not (put("y", yr) and put("m", mo)):
                return None
            continue
        if tok in MONTHS_BY_NAME:
            if not put("m", MONTHS_BY_NAME[tok]):
                return None
            continue
        if tok.isdigit():
            n = int(tok)
            if len(tok) == 4:
                if not put("y", n):
                    return None
                continue
            if 1 <= n <= 12:
                if not put("m", n):
                    return None
                continue
        return None

    if year is None and month is None:
        return None
    return year, month


def parse_summary_args(
    args: list[str],
    today: date,
    cycles: list[tuple[date, str]] | None = None,
) -> dict | None:
    """
    Resolve free-form /summary arguments. Returns one of:
      {"kind": "month", "year": int, "month": int}
      {"kind": "cycle", "start": date, "end": date, "label": str}
      {"kind": "range", "start": date, "end": date, "label": str}
    or None when the arguments cannot be understood.

    A bare month name resolves against the cycle ledger first (when cycles are
    passed in), calendar month otherwise — most recent occurrence of that month.
    """
    raw = " ".join(args).strip().lower()
    if not raw:
        return None

    # Range: "aug 2025 - jan 2026" (also accepts "to" as separator)
    parts = re.split(r"\s+-\s+|\s+to\s+|(?<=[a-z0-9])-(?=[a-z])", raw)
    if len(parts) == 2 and all(p.strip() for p in parts):
        return _parse_range(parts[0], parts[1], today)
    if len(parts) > 2:
        return None

    period = _parse_period(raw.split())
    if period is None:
        return None
    year, month = period

    if month is None:
        # Year only → whole-year range (capped at today for the current year).
        start = date(year, 1, 1)
        end = min(date(year, 12, 31), today) if year == today.year else date(year, 12, 31)
        if start > end:
            return None
        return {"kind": "range", "start": start, "end": end, "label": f"Year {year}"}

    if year is None:
        # Bare month: ledger label first, calendar only when no such label.
        if cycles:
            hit = find_cycle_by_month(cycles, month, today)
            if hit is not None:
                start, end, label = hit
                return {"kind": "cycle", "start": start, "end": end, "label": label}
        year = most_recent_year_for_month(month, today)

    return {"kind": "month", "year": year, "month": month}


def _parse_range(left: str, right: str, today: date) -> dict | None:
    sides = []
    for part in (left, right):
        period = _parse_period(part.split())
        if period is None:
            return None
        year, month = period
        if month is None:
            month_span = (1, 12)
        else:
            month_span = (month, month)
        if year is None:
            if month is None:
                return None
            year = most_recent_year_for_month(month, today)
        sides.append((year, month_span))

    (y1, (m1, _)), (y2, (_, m2)) = sides
    start = date(y1, m1, 1)
    end = month_last_day(y2, m2)
    if start > end:
        return None
    label = f"{calendar.month_abbr[m1]} {y1} – {calendar.month_abbr[m2]} {y2}"
    return {"kind": "range", "start": start, "end": end, "label": label}


# ── keyboards ─────────────────────────────────────────────────────────────────

def _year_rows(years: list[int], page: int) -> list[list[InlineKeyboardButton]]:
    """Year buttons newest-first, 4 per row, paged behind Earlier…/Newer…"""
    chunk = years[page * YEARS_PER_PAGE:(page + 1) * YEARS_PER_PAGE]
    rows = [
        [InlineKeyboardButton(str(y), callback_data=f"sum:y:{y}") for y in chunk[i:i + 4]]
        for i in range(0, len(chunk), 4)
    ]
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("Newer…", callback_data=f"sum:yrs:{page - 1}"))
    if len(years) > (page + 1) * YEARS_PER_PAGE:
        nav.append(InlineKeyboardButton("Earlier…", callback_data=f"sum:yrs:{page + 1}"))
    if nav:
        rows.append(nav)
    return rows


def build_year_keyboard(years: list[int], page: int = 0) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(_year_rows(years, page))


def build_month_keyboard(year: int, months: list[int]) -> InlineKeyboardMarkup:
    """Month buttons (only months with data), 4 per row, plus back-to-years."""
    rows = [
        [
            InlineKeyboardButton(calendar.month_abbr[m], callback_data=f"sum:m:{year}:{m}")
            for m in months[i:i + 4]
        ]
        for i in range(0, len(months), 4)
    ]
    rows.append([InlineKeyboardButton("« Years", callback_data="sum:cal")])
    return InlineKeyboardMarkup(rows)


def _cycle_button_label(cycles: list[tuple[date, str]], index: int, today: date) -> str:
    """'Aug 2026 (23 Jul – today)' — newest cycle's end reads 'today'."""
    start, end = cycle_bounds(cycles, index, today)
    end_txt = "today" if index == len(cycles) - 1 else end.strftime("%d %b").lstrip("0")
    return f"{cycles[index][1]} ({start.strftime('%d %b').lstrip('0')} – {end_txt})"


def build_cycle_keyboard(
    cycles: list[tuple[date, str]], today: date, page: int = 0
) -> InlineKeyboardMarkup:
    """Ledger list newest-first, one per row, 'Earlier…' paging."""
    newest_first = list(range(len(cycles) - 1, -1, -1))
    chunk = newest_first[page * CYCLES_PER_PAGE:(page + 1) * CYCLES_PER_PAGE]
    rows = [
        [
            InlineKeyboardButton(
                _cycle_button_label(cycles, i, today),
                callback_data=f"sum:cs:{cycles[i][0].isoformat()}",
            )
        ]
        for i in chunk
    ]
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("Newer…", callback_data=f"sum:cyc:{page - 1}"))
    if len(cycles) > (page + 1) * CYCLES_PER_PAGE:
        nav.append(InlineKeyboardButton("Earlier…", callback_data=f"sum:cyc:{page + 1}"))
    if nav:
        rows.append(nav)
    return InlineKeyboardMarkup(rows)


def build_summary_keyboard(cycles_enabled: bool, years: list[int]) -> InlineKeyboardMarkup:
    """
    The one-message, three-zone picker for bare /summary.
    Zone 1: quick row(s). Zone 2: history drill-down — year buttons directly when
    the flag is off, Calendar/Cycle choice when it is on (never a gate: the quick
    row sits above on the same screen). Zone 3: Range….
    """
    rows: list[list[InlineKeyboardButton]] = []
    if cycles_enabled:
        rows.append([
            InlineKeyboardButton("This cycle", callback_data="sum:tc"),
            InlineKeyboardButton("Last cycle", callback_data="sum:lc"),
        ])
    rows.append([
        InlineKeyboardButton("This month", callback_data="sum:tm"),
        InlineKeyboardButton("Last month", callback_data="sum:lm"),
    ])
    if cycles_enabled:
        rows.append([
            InlineKeyboardButton("📅 Calendar", callback_data="sum:cal"),
            InlineKeyboardButton("💰 Cycle", callback_data="sum:cyc:0"),
        ])
    else:
        rows.extend(_year_rows(years, 0))
    rows.append([InlineKeyboardButton("Range…", callback_data="sum:rng")])
    return InlineKeyboardMarkup(rows)
