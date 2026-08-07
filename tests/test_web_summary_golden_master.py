"""
test_web_summary_golden_master.py — Cycle S2 parity proof.

Asserts the web Summary route computes the SAME numbers as the bot's
/summary math: build_summary_context() must equal direct
cycles.cycle_totals()/cycle_periods() calls on the same fixture data —
expected values are derived by calling the real functions, never
hand-picked. Fixture mirrors tests/test_reports_golden_master.py:
mid-month cycle boundaries (2025-05-28, 2025-06-27) so the open cycle
spans a calendar-month edge; frozen "today" = 2025-07-20.
"""

import re
from datetime import date

import pytest

import settings
import storage_facade
from cycles import BEFORE_CYCLES_LABEL, cycle_periods, cycle_totals
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
from web.routes.summary import build_summary_context

TODAY = date(2025, 7, 20)
CYCLE_STARTS = [date(2025, 5, 28), date(2025, 6, 27)]


def _t(d, value, ttype, category, description, currency="PLN"):
    return Transaction(date=d, value=value, currency=currency,
                       transaction_type=ttype, category=category,
                       person="Alice", description=description)


FIXTURE_TXNS = [
    _t(date(2025, 4, 5),  6000.0, "Income",  "Salary",        "April salary"),
    _t(date(2025, 4, 10),  400.0, "Expense", "Groceries",     "monthly groceries"),
    _t(date(2025, 4, 20), 1000.0, "Savings", "Investment",    "index fund"),
    _t(date(2025, 5, 28), 6200.0, "Income",  "Salary",        "May salary"),
    _t(date(2025, 5, 30),  350.0, "Expense", "Groceries",     "groceries"),
    _t(date(2025, 6, 5),    80.0, "Expense", "Entertainment", "concert", currency="EUR"),
    _t(date(2025, 6, 10),  900.0, "Savings", "Investment",    "index fund"),
    _t(date(2025, 6, 27), 6400.0, "Income",  "Salary",        "June salary"),
    _t(date(2025, 6, 30),  310.0, "Expense", "Groceries",     "groceries"),
    _t(date(2025, 7, 10),  120.0, "Expense", "Entertainment", "cinema"),
    _t(date(2025, 7, 15), 1000.0, "Savings", "Investment",    "index fund"),
]


@pytest.fixture()
def web_env(excel_path, tmp_path, monkeypatch):
    """Excel workbook + cycle ledger + SQLite seeded from that workbook."""
    append_transactions_batch(FIXTURE_TXNS)
    db_path = tmp_path / "web_golden.db"
    monkeypatch.setattr(settings, "SQLITE_DB_PATH", db_path)
    stats = run_import(db_path=db_path)
    assert stats["inserted"] == len(FIXTURE_TXNS)
    _seed_cycles_to_sqlite(db_path, CYCLE_STARTS)
    monkeypatch.setattr(settings, "BUDGET_CYCLE", True)
    monkeypatch.setattr(settings, "WEB_PASSWORD", "test-pass")
    monkeypatch.setattr(settings, "WEB_SESSION_SECRET", "test-secret")
    return excel_path


def test_summary_context_matches_cycle_totals(web_env):
    """The route's computed dict equals direct cycle_totals/cycle_periods."""
    ctx = build_summary_context(today=TODAY)
    df = storage_facade.load_transactions()

    expected_periods = [p for p in cycle_periods(df, None, TODAY) if p[0] <= TODAY]
    # 3 periods: "Before cycles" bucket + two recorded boundaries.
    assert len(expected_periods) == 3
    assert len(ctx["cards"]) == 3

    for card, (start, end, label) in zip(ctx["cards"], reversed(expected_periods)):
        totals = cycle_totals(df, start, end)
        assert (card["label"], card["start"], card["end"]) == (label, start, end)
        assert card["income"] == pytest.approx(totals["income"])
        assert card["expense"] == pytest.approx(totals["expense"])
        assert card["savings"] == pytest.approx(totals["savings"])
        assert card["net"] == pytest.approx(
            totals["income"] - totals["expense"] - totals["savings"])
        days = (end - start).days + 1
        assert card["daily_avg"] == pytest.approx(totals["expense"] / days)
        if label == BEFORE_CYCLES_LABEL:
            assert card["unaccounted"] is None  # no salary anchor, like the bot
        else:
            assert card["unaccounted"] == pytest.approx(totals["unaccounted"])


def test_open_cycle_spans_month_boundary(web_env):
    """Cycle-edge fixture: newest card covers Jun 27 → Jul 20 across months."""
    ctx = build_summary_context(today=TODAY)
    newest = ctx["cards"][0]
    assert newest["start"] == date(2025, 6, 27)
    assert newest["end"] == TODAY
    df = storage_facade.load_transactions()
    totals = cycle_totals(df, date(2025, 6, 27), TODAY)
    assert newest["income"] == pytest.approx(totals["income"])
    assert newest["expense"] == pytest.approx(totals["expense"])


def test_rendered_html_shows_same_numbers(web_env, monkeypatch):
    """End-to-end: TestClient GET / renders exactly the computed numbers."""
    from fastapi.testclient import TestClient
    import web.routes.summary as summary_mod
    from web.app import create_app

    monkeypatch.setattr(summary_mod, "build_summary_context",
                        lambda today=None: build_summary_context(TODAY))
    client = TestClient(create_app())
    resp = client.post("/login", data={"password": "test-pass"}, follow_redirects=False)
    assert resp.status_code == 303
    page = client.get("/")
    assert page.status_code == 200

    df = storage_facade.load_transactions()
    periods = [p for p in cycle_periods(df, None, TODAY) if p[0] <= TODAY]
    rendered = re.findall(r'data-field="income">([\d.]+)<', page.text)
    expected = [f"{cycle_totals(df, s, e)['income']:.2f}"
                for s, e, _ in reversed(periods)]
    assert rendered == expected
