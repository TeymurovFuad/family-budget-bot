"""
cycles.py — budget-cycle ledger (Cycles sheet) and cycle-scoped aggregation.

A cycle boundary is a RECORDED EVENT (salary confirmation or /cycle started),
never a date formula. Boundaries are written once and never recomputed.
Everything here is inert unless settings.BUDGET_CYCLE is on — callers gate on
the flag; these helpers just read/write the ledger.
"""

import re
from datetime import date, timedelta

import pandas as pd

import settings
from logger import get_logger

log = get_logger(__name__)

# Implicit bucket for transactions older than the first recorded boundary.
# It has no salary anchor, so unaccounted math never applies to it.
BEFORE_CYCLES_LABEL = "Before cycles"


def cycle_label(start: date) -> str:
    """Ledger label for a cycle — always carries the year, e.g. 'Aug 2026'."""
    return start.strftime("%b %Y")


def _dedup_cycle_label(start: date, existing_dates) -> str:
    """
    Ledger label for a boundary, unique within its calendar month: the first
    boundary in a month keeps the plain label ('Jul 2026'); further ones get
    an index suffix ('Jul 2026 #2').
    """
    same_month = sum(
        1 for d in existing_dates
        if d != start and (d.year, d.month) == (start.year, start.month)
    )
    base = cycle_label(start)
    return base if same_month == 0 else f"{base} #{same_month + 1}"


def current_cycle_start(today: date, cycles: list[tuple[date, str]] | None = None) -> tuple[date, str] | None:
    """Latest recorded boundary on or before today, or None (→ calendar fallback)."""
    if cycles is None:
        from storage_facade import load_cycles as _load_cycles
        cycles = _load_cycles()
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


MAX_SALARY_KEYWORD_BYTES = 57  # Telegram callback_data limit is 64 bytes; "kw:del:" takes 7


def cycle_detect_keywords(extra: list[str] | None = None) -> list[str]:
    """SALARY_CATEGORY plus the stored salary keywords (SQLite, falling back to
    .env CYCLE_DETECT_KEYWORDS) plus any ad-hoc extras, lowercased,
    deduplicated, blanks dropped."""
    from storage_facade import load_salary_keywords as _load_salary_keywords
    stored = _load_salary_keywords()
    if not stored:
        log.debug("No salary keywords in DB — falling back to .env CYCLE_DETECT_KEYWORDS")
        stored = settings.CYCLE_DETECT_KEYWORDS
    words = [settings.SALARY_CATEGORY, *stored, *(extra or [])]
    seen: list[str] = []
    for w in words:
        w = str(w or "").strip().lower()
        if w and w not in seen:
            seen.append(w)
    return seen


def salary_mask(df: pd.DataFrame, extra_keywords: list[str] | None = None) -> pd.Series:
    """
    Boolean mask for salary rows: Income type AND a salary keyword in Category
    (word-boundary contains), or in Description when Category is blank.
    Description matters because bulk-imported salary rows carry the bank's
    transfer title (e.g. 'SALARY PAYMENT JULY') with an empty category;
    a categorised row ('Freelance' + 'Salary' description) is not a salary.
    """
    # Defense in depth: cycle_detect_keywords already drops blanks, but an
    # empty alternative in the regex below would match every Income row —
    # keep the guard next to the pattern it protects.
    keywords = [k for k in cycle_detect_keywords(extra_keywords) if str(k).strip()]
    if not keywords:
        return pd.Series(False, index=df.index)
    pattern = r"(?<!\w)(?:" + "|".join(re.escape(k) for k in keywords) + r")(?!\w)"
    category = df["Category"].fillna("").astype(str).str.strip()
    matches = category.str.contains(pattern, case=False, regex=True, flags=re.UNICODE)
    if "Description" in df.columns:
        matches |= (category == "") & df["Description"].astype(str).str.contains(
            pattern, case=False, regex=True, flags=re.UNICODE
        )
    return (df["Type"] == "Income") & matches


def detect_cycle_candidates(
    df: pd.DataFrame,
    existing_cycles: list[tuple[date, str]] | None = None,
    extra_keywords: list[str] | None = None,
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
        from storage_facade import load_cycles as _load_cycles
        existing_cycles = _load_cycles()
    existing_starts = {c[0] for c in existing_cycles}

    df = df.copy()
    df["_date"] = pd.to_datetime(df["Date"], errors="coerce").dt.date

    salary_rows = df[
        df["_date"].notna()
        & df["IsDone"].astype(bool)
        & salary_mask(df, extra_keywords)
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



def cycle_totals(
    df: pd.DataFrame,
    start: date,
    end: date,
    extra_keywords: list[str] | None = None,
) -> dict:
    """
    Aggregate MasterData over [start, end] (inclusive; end is today for the
    open-ended current cycle). All sums use the _base column.

    extra_keywords — ad-hoc salary search words for this session (e.g. from
    `/cycle detect <words>`); they extend the stored keyword list without being
    persisted to the Excel workbook.

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
    salary = sub[salary_mask(sub, extra_keywords)]["_base"].sum()
    return {
        "sub": sub,
        "income": income,
        "expense": expense,
        "savings": savings,
        "salary": salary,
        "unaccounted": salary - expense - savings,
    }


def cycle_periods(
    df: pd.DataFrame,
    cycles: list[tuple[date, str]] | None = None,
    today: date | None = None,
) -> list[tuple[date, date, str]]:
    """
    Every cycle as (start, end, label), oldest first. Each cycle ends the day
    before the next begins; the newest ends today. When transactions exist
    that are older than the first recorded boundary, an implicit
    "Before cycles" bucket is prepended covering [earliest txn, first-1].
    Returns [] when the ledger is empty.
    """
    if cycles is None:
        from storage_facade import load_cycles as _load_cycles
        cycles = _load_cycles()
    if today is None:
        today = date.today()
    if not cycles:
        return []
    periods: list[tuple[date, date, str]] = []
    first_start = cycles[0][0]
    dates = pd.to_datetime(df["Date"], errors="coerce").dt.date.dropna()
    older = dates[dates < first_start]
    if not older.empty:
        periods.append((older.min(), first_start - timedelta(days=1), BEFORE_CYCLES_LABEL))
    for i, (start, label) in enumerate(cycles):
        end = cycles[i + 1][0] - timedelta(days=1) if i + 1 < len(cycles) else today
        periods.append((start, end, label))
    return periods


def detect_missing_boundaries(
    start: date,
    end: date,
    cycles: list[tuple[date, str]] | None = None,
) -> list[date]:
    """
    First-of-month markers for calendar months inside [start, end] that have
    no recorded cycle boundary. Used by reports to offer a lazy backfill
    before rendering a period with gaps.
    """
    if cycles is None:
        from storage_facade import load_cycles as _load_cycles
        cycles = _load_cycles()
    if not cycles:
        # No ledger at all → no boundaries to compare against, hence no gaps
        # to backfill (an empty ledger means cycles are effectively unused).
        return []
    covered = {(c[0].year, c[0].month) for c in cycles}
    missing: list[date] = []
    y, m = start.year, start.month
    while (y, m) <= (end.year, end.month):
        if (y, m) not in covered:
            missing.append(date(y, m, 1))
        m += 1
        if m > 12:
            y, m = y + 1, 1
    return missing


def fallback_income_candidates(
    df: pd.DataFrame,
    anchor: date,
    existing_cycles: list[tuple[date, str]] | None = None,
    window_days: int = 20,
    limit: int = 3,
) -> list[dict]:
    """
    When keyword detection finds nothing: the largest `limit` Income rows in
    the ±window_days window around `anchor` (usually the 1st of the target
    month), largest first. Catches salaries filed under non-salary categories.
    Each entry: {date, amounts, unambiguous} — same shape as
    detect_cycle_candidates() entries.
    """
    if existing_cycles is None:
        from storage_facade import load_cycles as _load_cycles
        existing_cycles = _load_cycles()
    existing_starts = {c[0] for c in existing_cycles}

    df = df.copy()
    if df.empty or "Date" not in df.columns or "_base" not in df.columns:
        return []
    df["_date"] = pd.to_datetime(df["Date"], errors="coerce").dt.date
    lo, hi = anchor - timedelta(days=window_days), anchor + timedelta(days=window_days)
    rows = df[
        df["_date"].notna()
        & df["IsDone"].astype(bool)
        & (df["Type"] == "Income")
        & (df["_date"] >= lo)
        & (df["_date"] <= hi)
        & (df["_date"] <= date.today())
    ]
    rows = rows[~rows["_date"].isin(existing_starts)]
    if rows.empty:
        return []
    rows = rows.sort_values("_base", ascending=False).head(limit)
    return [
        {
            "date": r["_date"],
            "amounts": [round(float(r["_base"]), 2)],
            "unambiguous": True,
        }
        for _, r in rows.iterrows()
    ]
