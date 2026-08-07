"""
test_reports_golden_master.py — golden-master proof for Cycle S1 Phase 2,
Unit R1 (rewire handlers/reports.py from data.load_data to
storage_facade.load_transactions).

The golden strings in tests/fixtures/reports_golden_master.json were captured
by running /summary, /report, /top and /savings against the ORIGINAL
Excel-backed handlers/reports.py (commit before the facade rewrite) with a
fixed transaction fixture and frozen time. The tests assert that the
facade-backed handlers produce byte-identical reply text for the same
underlying data, seeded into SQLite via
scripts/import_excel_to_sqlite.run_import from the very same workbook.

Fixture design:
- three-plus months of data (Apr–Jul 2025), all persons/descriptions set;
- one foreign-currency row (80 EUR) so value_base math is exercised;
- two recorded cycle boundaries, both MID-month (2025-05-28, 2025-06-27),
  so the current cycle spans a calendar-month boundary — the cycle-edge case;
- frozen "today" = 2025-07-20, inside the open Jun 2025 cycle.

A supporting parity test also asserts data.load_data() and
storage_facade.load_transactions() agree cell-for-cell on this fixture.

To re-capture (only if report wording deliberately changes): set
GOLDEN_RECAPTURE=1 in the environment and run this file's tests once —
the fixture JSON is rewritten from the live handler output.
"""

import json
import os
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pandas as pd
import pytest

import data
import settings
import storage_facade
import handlers.reports as reports
from file_storage import append_transactions_batch
import sqlite_ops as _sqlite_ops
from cycles import _dedup_cycle_label as _dedup_label


def _seed_cycles_to_sqlite(db_path, starts):
    """Insert cycle boundaries directly into a SQLite DB (bypasses async facade)."""
    conn = _sqlite_ops.connect(db_path)
    try:
        for d in sorted(starts):
            existing = _sqlite_ops.list_cycles(conn)
            existing_dates = [date.fromisoformat(r["start_date"]) for r in existing]
            label = _dedup_label(d, existing_dates)
            _sqlite_ops.upsert_cycle(conn, d.isoformat(), label)
        conn.commit()
    finally:
        conn.close()
from models import Transaction
from scripts.import_excel_to_sqlite import run_import

UID = 123  # allowed id from conftest

FROZEN_NOW = datetime(2025, 7, 20, 12, 0, tzinfo=timezone.utc)

GOLDEN_PATH = Path(__file__).parent / "fixtures" / "reports_golden_master.json"
RECAPTURE = os.getenv("GOLDEN_RECAPTURE") == "1"
EXPECTED: dict = (
    json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    if GOLDEN_PATH.exists() else {}
)
_captured: dict = {}


def _check(key: str, actual: str) -> None:
    """Assert against the golden string, or record it in recapture mode."""
    if RECAPTURE:
        _captured[key] = actual
        GOLDEN_PATH.parent.mkdir(parents=True, exist_ok=True)
        merged = {**EXPECTED, **_captured}
        GOLDEN_PATH.write_text(
            json.dumps(merged, ensure_ascii=False, indent=1) + "\n",
            encoding="utf-8")
        return
    assert actual == EXPECTED[key]


class _FrozenDatetime(datetime):
    """Stand-in for handlers.reports.datetime with a pinned now()."""

    @classmethod
    def now(cls, tz=None):
        if tz is not None:
            return FROZEN_NOW.astimezone(tz)
        return FROZEN_NOW.replace(tzinfo=None)


def _t(d, value, ttype, category, description, currency="PLN", recurring=False):
    return Transaction(
        date=d, value=value, currency=currency, transaction_type=ttype,
        category=category, person="Alice", description=description,
        is_recurring=recurring,
    )


FIXTURE_TXNS = [
    _t(date(2025, 4, 5),  6000.0, "Income",  "Salary",        "April salary"),
    _t(date(2025, 4, 10),  400.0, "Expense", "Groceries",     "monthly groceries"),
    _t(date(2025, 4, 12),  150.0, "Expense", "Transport",     "transit pass", recurring=True),
    _t(date(2025, 4, 20), 1000.0, "Savings", "Investment",    "index fund"),
    _t(date(2025, 5, 28), 6200.0, "Income",  "Salary",        "May salary"),
    _t(date(2025, 5, 30),  350.0, "Expense", "Groceries",     "groceries"),
    _t(date(2025, 6, 5),    80.0, "Expense", "Entertainment", "concert tickets", currency="EUR"),
    _t(date(2025, 6, 10),  900.0, "Savings", "Investment",    "index fund"),
    _t(date(2025, 6, 27), 6400.0, "Income",  "Salary",        "June salary"),
    _t(date(2025, 6, 30),  310.0, "Expense", "Groceries",     "groceries"),
    _t(date(2025, 7, 3),   160.0, "Expense", "Transport",     "transit pass", recurring=True),
    _t(date(2025, 7, 10),  120.0, "Expense", "Entertainment", "cinema"),
    _t(date(2025, 7, 15), 1000.0, "Savings", "Investment",    "index fund"),
]

# Both boundaries fall mid-month; the open cycle spans Jun 27 → Jul 20.
CYCLE_STARTS = [date(2025, 5, 28), date(2025, 6, 27)]


@pytest.fixture()
def golden_env(excel_path, tmp_path, monkeypatch):
    """Excel workbook + cycle ledger + SQLite DB seeded from that workbook."""
    append_transactions_batch(FIXTURE_TXNS)
    db_path = tmp_path / "golden.db"
    monkeypatch.setattr(settings, "SQLITE_DB_PATH", db_path)
    stats = run_import(db_path=db_path)
    assert stats["inserted"] == len(FIXTURE_TXNS)
    _seed_cycles_to_sqlite(db_path, CYCLE_STARTS)
    data.invalidate_reference_cache()
    return excel_path


def _freeze(monkeypatch, budget_cycle: bool):
    monkeypatch.setattr(settings, "BUDGET_CYCLE", budget_cycle)
    monkeypatch.setattr(reports, "now_utc", lambda: FROZEN_NOW)
    monkeypatch.setattr(reports, "current_year_and_month", lambda: (2025, "Jul"))
    monkeypatch.setattr(reports, "datetime", _FrozenDatetime)
    monkeypatch.setattr(reports, "get_display_currency", lambda uid: "PLN")


def _make_update():
    upd = MagicMock()
    upd.message.reply_text = AsyncMock()
    upd.message.reply_photo = AsyncMock()
    upd.effective_message = upd.message
    upd.effective_user.id = UID
    upd.callback_query = None
    return upd


def _make_ctx(args=None):
    ctx = MagicMock()
    ctx.user_data = {}
    ctx.args = args or []
    return ctx


def _texts(upd) -> str:
    return "\n<REPLY-BREAK>\n".join(
        str(c.args[0]) for c in upd.message.reply_text.call_args_list)


def _caption(upd) -> str:
    call = upd.message.reply_photo.call_args
    return str(call.kwargs.get("caption", ""))


async def _run(handler, args=None):
    upd = _make_update()
    await handler(upd, _make_ctx(args))
    return upd


# ── Golden-master assertions ──────────────────────────────────────────────────

class TestGoldenMasterCycleMode:
    async def test_summary_calendar_month(self, golden_env, monkeypatch):
        _freeze(monkeypatch, budget_cycle=True)
        upd = await _run(reports.cmd_summary, ["apr", "2025"])
        _check("summary_apr_calendar", _texts(upd))

    async def test_summary_resolves_to_mid_month_cycle(self, golden_env, monkeypatch):
        """'/summary jun 2025' must hit the Jun 27 → today cycle, not the month."""
        _freeze(monkeypatch, budget_cycle=True)
        upd = await _run(reports.cmd_summary, ["jun", "2025"])
        _check("summary_jun_cycle", _texts(upd))

    async def test_report_cycle(self, golden_env, monkeypatch):
        _freeze(monkeypatch, budget_cycle=True)
        upd = await _run(reports.cmd_report)
        _check("report_cycle", _texts(upd))

    async def test_top_cycle(self, golden_env, monkeypatch):
        _freeze(monkeypatch, budget_cycle=True)
        upd = await _run(reports.cmd_top)
        _check("top_cycle", _texts(upd))

    async def test_savings_cycle_caption(self, golden_env, monkeypatch):
        _freeze(monkeypatch, budget_cycle=True)
        upd = await _run(reports.cmd_savings)
        _check("savings_cycle_caption", _caption(upd))


class TestGoldenMasterCalendarMode:
    async def test_summary_current_month_projection(self, golden_env, monkeypatch):
        _freeze(monkeypatch, budget_cycle=False)
        upd = await _run(reports.cmd_summary, ["jul", "2025"])
        _check("summary_jul_projection", _texts(upd))

    async def test_report_calendar(self, golden_env, monkeypatch):
        _freeze(monkeypatch, budget_cycle=False)
        upd = await _run(reports.cmd_report)
        _check("report_calendar", _texts(upd))

    async def test_top_calendar(self, golden_env, monkeypatch):
        _freeze(monkeypatch, budget_cycle=False)
        upd = await _run(reports.cmd_top)
        _check("top_calendar", _texts(upd))

    async def test_savings_calendar_caption(self, golden_env, monkeypatch):
        _freeze(monkeypatch, budget_cycle=False)
        upd = await _run(reports.cmd_savings)
        _check("savings_calendar_caption", _caption(upd))


def test_all_golden_keys_present():
    """Guard against a silently missing/renamed key in the fixture JSON."""
    if RECAPTURE:
        pytest.skip("recapture mode")
    assert set(EXPECTED) == {
        "summary_apr_calendar", "summary_jun_cycle", "report_cycle",
        "top_cycle", "savings_cycle_caption", "summary_jul_projection",
        "report_calendar", "top_calendar", "savings_calendar_caption",
    }


# ── Supporting parity: DataFrames agree cell-for-cell ─────────────────────────

def test_load_transactions_matches_load_data(golden_env):
    excel_df = data.load_data().reset_index(drop=True)
    sqlite_df = storage_facade.load_transactions().reset_index(drop=True)

    # "_id" is a private SQLite primary-key column for the web write path;
    # it has no Excel equivalent — exclude it from the parity check.
    assert list(excel_df.drop(columns=["_id"], errors="ignore").columns) == list(sqlite_df.drop(columns=["_id"], errors="ignore").columns)
    assert len(excel_df) == len(sqlite_df) == len(FIXTURE_TXNS)

    e_dates = pd.to_datetime(excel_df["Date"]).dt.date.tolist()
    s_dates = pd.to_datetime(sqlite_df["Date"]).dt.date.tolist()
    assert e_dates == s_dates

    for col in ("Year", "Month", "Type", "Category", "Person", "Description",
                "Currency"):
        assert excel_df[col].astype(str).tolist() == \
               sqlite_df[col].astype(str).tolist(), f"column {col} diverges"

    for col in ("Value", "_base"):
        assert excel_df[col].tolist() == pytest.approx(sqlite_df[col].tolist()), \
            f"column {col} diverges"

    assert excel_df["IsDone"].astype(bool).tolist() == \
           sqlite_df["IsDone"].astype(bool).tolist()
    assert excel_df["IsRecurring"].fillna(False).astype(bool).tolist() == \
           sqlite_df["IsRecurring"].fillna(False).astype(bool).tolist()
