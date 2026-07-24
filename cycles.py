"""
cycles.py — budget-cycle ledger (Cycles sheet) and cycle-scoped aggregation.

A cycle boundary is a RECORDED EVENT (salary confirmation or /cycle started),
never a date formula. Boundaries are written once and never recomputed.
Everything here is inert unless settings.BUDGET_CYCLE is on — callers gate on
the flag; these helpers just read/write the ledger.
"""

import asyncio
from datetime import date

import pandas as pd

import settings
from logger import get_logger
from excel_schema import CyclesSchema, col_indices, header_of
from file_storage import (
    ExcelFileContext,
    _excel_write_lock,
    atomic_save,
    get_excel_path_for_reading,
)

log = get_logger(__name__)

CYCLES_SHEET_NAME = "Cycles"


def cycle_label(start: date) -> str:
    """Ledger label for a cycle — always carries the year, e.g. 'Aug 2026'."""
    return start.strftime("%b %Y")


def _to_date(value) -> date | None:
    if value is None:
        return None
    if hasattr(value, "date"):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value).strip()[:10])
    except ValueError:
        return None


def ensure_cycles_sheet(wb):
    """Return the Cycles worksheet, creating it with headers if missing."""
    if CYCLES_SHEET_NAME in wb.sheetnames:
        return wb[CYCLES_SHEET_NAME]
    ws = wb.create_sheet(CYCLES_SHEET_NAME)
    ws.cell(1, 1, header_of(CyclesSchema, "start_date"))
    ws.cell(1, 2, header_of(CyclesSchema, "label"))
    log.info("Created %s sheet in workbook", CYCLES_SHEET_NAME)
    return ws


def load_cycles() -> list[tuple[date, str]]:
    """
    Read the cycle ledger, sorted by start date ascending.
    Returns [] when the sheet is missing or unreadable — callers fall back to
    calendar behaviour.
    """
    from openpyxl import load_workbook

    try:
        wb = load_workbook(get_excel_path_for_reading(), data_only=True)
        if CYCLES_SHEET_NAME not in wb.sheetnames:
            return []
        ws = wb[CYCLES_SHEET_NAME]
        idx = col_indices(ws, CyclesSchema)
        start_col = idx.get("start_date")
        label_col = idx.get("label")
        if not start_col:
            return []
        cycles: list[tuple[date, str]] = []
        for row in range(2, ws.max_row + 1):
            start = _to_date(ws.cell(row, start_col).value)
            if start is None:
                continue
            raw_label = ws.cell(row, label_col).value if label_col else None
            label = str(raw_label).strip() if raw_label else cycle_label(start)
            cycles.append((start, label))
        cycles.sort(key=lambda c: c[0])
        return cycles
    except Exception as e:
        log.warning("Could not load cycle ledger: %s", e)
        return []


def record_cycle_start(start: date) -> bool:
    """
    Append one boundary row to the Cycles sheet.
    Returns False (no write) if that start date is already recorded —
    boundaries are written once, never recomputed.
    """
    from openpyxl import load_workbook

    with ExcelFileContext() as excel_path:
        wb = load_workbook(excel_path)
        ws = ensure_cycles_sheet(wb)
        idx = col_indices(ws, CyclesSchema)
        start_col = idx["start_date"]
        label_col = idx["label"]
        next_row = 2
        for row in range(2, ws.max_row + 1):
            existing = _to_date(ws.cell(row, start_col).value)
            if existing is None:
                continue
            if existing == start:
                return False
            next_row = row + 1
        ws.cell(next_row, start_col, start)
        ws.cell(next_row, label_col, cycle_label(start))
        atomic_save(wb, excel_path)
        log.info("Recorded cycle boundary %s (%s)", start, cycle_label(start))
        return True


async def async_record_cycle_start(start: date) -> bool:
    loop = asyncio.get_running_loop()
    async with _excel_write_lock:
        return await loop.run_in_executor(None, record_cycle_start, start)


def current_cycle_start(today: date, cycles: list[tuple[date, str]] | None = None) -> tuple[date, str] | None:
    """Latest recorded boundary on or before today, or None (→ calendar fallback)."""
    if cycles is None:
        cycles = load_cycles()
    past = [c for c in cycles if c[0] <= today]
    return past[-1] if past else None


def should_prompt_new_cycle(today: date) -> bool:
    """
    True when a Salary income should trigger the new-cycle prompt: either no
    cycle exists yet, or the current one is at least
    CYCLE_REPROMPT_MIN_AGE_DAYS old. Younger cycle → income inside the cycle,
    silently counted.
    """
    current = current_cycle_start(today)
    if current is None:
        return True
    return (today - current[0]).days >= settings.CYCLE_REPROMPT_MIN_AGE_DAYS


def detect_cycle_candidates(
    df: pd.DataFrame,
    existing_cycles: list[tuple[date, str]] | None = None,
) -> list[dict]:
    """
    Scan transaction history for salary arrivals not yet recorded as cycle
    boundaries. Returns one entry per unique salary date, oldest first.

    Each entry: {date, amounts, unambiguous}
      - date: the transaction date (the cycle boundary if confirmed)
      - amounts: list of salary amounts on that date (usually one)
      - unambiguous: True when exactly one salary row on that date
    """
    if existing_cycles is None:
        existing_cycles = load_cycles()
    existing_starts = {c[0] for c in existing_cycles}

    df = df.copy()
    df["_date"] = pd.to_datetime(df["Date"], errors="coerce").dt.date

    salary_cat = settings.SALARY_CATEGORY.strip().lower()
    salary_rows = df[
        df["_date"].notna()
        & df["IsDone"].astype(bool)
        & (df["Type"] == "Income")
        & (df["Category"].astype(str).str.strip().str.lower() == salary_cat)
        & (df["_date"] <= date.today())
    ].copy()

    if salary_rows.empty:
        return []

    results: list[dict] = []
    for salary_date, group in salary_rows.groupby("_date"):
        if salary_date in existing_starts:
            continue
        amounts = sorted(
            [round(float(r["_base"]), 2) for _, r in group.iterrows()],
            reverse=True,
        )
        results.append(
            {
                "date": salary_date,
                "amounts": amounts,
                "unambiguous": len(amounts) == 1,
            }
        )

    return results


def record_cycle_starts_batch(starts: list[date]) -> int:
    """
    Open the workbook ONCE and write all boundary rows. Returns the count
    actually written (skips dates that are already present).
    """
    from openpyxl import load_workbook

    with ExcelFileContext() as excel_path:
        wb = load_workbook(excel_path)
        ws = ensure_cycles_sheet(wb)
        idx = col_indices(ws, CyclesSchema)
        start_col = idx["start_date"]
        label_col = idx["label"]

        existing: set[date] = set()
        next_row = 2
        for row in range(2, ws.max_row + 1):
            existing_date = _to_date(ws.cell(row, start_col).value)
            if existing_date is None:
                continue
            existing.add(existing_date)
            next_row = row + 1

        count = 0
        for start in starts:
            if start in existing:
                continue
            ws.cell(next_row, start_col, start)
            ws.cell(next_row, label_col, cycle_label(start))
            existing.add(start)
            next_row += 1
            count += 1
            log.info("Batch-recorded cycle boundary %s (%s)", start, cycle_label(start))

        if count:
            atomic_save(wb, excel_path)
        return count


def cycle_totals(df: pd.DataFrame, start: date, end: date) -> dict:
    """
    Aggregate MasterData over [start, end] (inclusive; end is today for the
    open-ended current cycle). All sums use the _base column.

    unaccounted = salary received − tracked expenses − tracked savings;
    negative means over-reported.
    """
    dates = pd.to_datetime(df["Date"], errors="coerce")
    sub = df[
        dates.notna()
        & (dates.dt.date >= start)
        & (dates.dt.date <= end)
        & df["IsDone"]
    ]
    income  = sub[sub["Type"] == "Income"]["_base"].sum()
    expense = sub[sub["Type"] == "Expense"]["_base"].sum()
    savings = sub[sub["Type"] == "Savings"]["_base"].sum()
    salary_mask = (sub["Type"] == "Income") & (
        sub["Category"].astype(str).str.strip().str.lower()
        == settings.SALARY_CATEGORY.strip().lower()
    )
    salary = sub[salary_mask]["_base"].sum()
    return {
        "sub": sub,
        "income": income,
        "expense": expense,
        "savings": savings,
        "salary": salary,
        "unaccounted": salary - expense - savings,
    }
