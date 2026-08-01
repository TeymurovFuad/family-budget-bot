"""
test_web_summary_cycles_v2.py — Ledger redesign: Summary period navigation,
session-currency conversion (the previously dead nav switcher), and Cycles →
Transactions linking.

Fixture mirrors tests/test_web_summary_golden_master.py (same data shape,
frozen "today" = 2025-07-20) but freezes time by patching the routes' clock
instead of the context builder, so the real query-param plumbing is
exercised end to end.
"""

import re
from datetime import date, datetime, time

import pytest

import settings
from cycles import cycle_periods, cycle_totals, record_cycle_starts_batch
from file_storage import append_transactions_batch
from models import Transaction
from scripts.import_excel_to_sqlite import run_import
from web.currency import load_rates
from web.routes.summary import build_summary_context

TODAY = date(2025, 7, 20)
CYCLE_STARTS = [date(2025, 5, 28), date(2025, 6, 27)]


def _t(d, value, ttype, category, description, currency="PLN"):
    return Transaction(date=d, value=value, currency=currency,
                       transaction_type=ttype, category=category,
                       person="Alice", description=description)


FIXTURE_TXNS = [
    _t(date(2025, 4, 5),  6000.0, "Income",  "Salary",     "April salary"),
    _t(date(2025, 4, 10),  400.0, "Expense", "Groceries",  "monthly groceries"),
    _t(date(2025, 4, 20), 1000.0, "Savings", "Investment", "index fund"),
    _t(date(2025, 5, 28), 6200.0, "Income",  "Salary",     "May salary"),
    _t(date(2025, 5, 30),  350.0, "Expense", "Groceries",  "groceries"),
    _t(date(2025, 6, 10),  900.0, "Savings", "Investment", "index fund"),
    _t(date(2025, 6, 27), 6400.0, "Income",  "Salary",     "June salary"),
    _t(date(2025, 6, 30),  310.0, "Expense", "Groceries",  "groceries"),
    _t(date(2025, 7, 15), 1000.0, "Savings", "Investment", "index fund"),
]


class _FrozenDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return datetime.combine(TODAY, time(12, 0), tzinfo=tz)


def _freeze_today(monkeypatch):
    import web.routes.cycles as cycles_mod
    import web.routes.summary as summary_mod
    monkeypatch.setattr(summary_mod, "datetime", _FrozenDatetime)
    monkeypatch.setattr(cycles_mod, "datetime", _FrozenDatetime)


@pytest.fixture()
def web_env(excel_path, tmp_path, monkeypatch):
    """Excel workbook + cycle ledger + SQLite seeded from that workbook."""
    append_transactions_batch(FIXTURE_TXNS)
    record_cycle_starts_batch(CYCLE_STARTS)
    db_path = tmp_path / "web_v2.db"
    monkeypatch.setattr(settings, "SQLITE_DB_PATH", db_path)
    run_import(db_path=db_path)
    monkeypatch.setattr(settings, "BUDGET_CYCLE", True)
    monkeypatch.setattr(settings, "WEB_PASSWORD", "test-pass")
    monkeypatch.setattr(settings, "WEB_SESSION_SECRET", "test-secret")
    _freeze_today(monkeypatch)
    return excel_path


@pytest.fixture()
def client(web_env):
    from fastapi.testclient import TestClient
    from web.app import create_app
    client = TestClient(create_app())
    resp = client.post("/login", data={"password": "test-pass"},
                       follow_redirects=False)
    assert resp.status_code == 303
    return client


def _incomes(html: str) -> list[str]:
    return re.findall(r'data-field="income">([\d.]+)<', html)


def _fields(html: str) -> dict[str, float]:
    """First occurrence of each data-field (the primary card's stats)."""
    return {name: float(val) for name, val in
            re.findall(r'data-field="(\w+)">\$?([-+]?[\d.]+)', html)[::-1]}


# ── Period navigation ────────────────────────────────────────────────────────

def test_period_selection_changes_displayed_data(client):
    """?period=<start> makes that period the primary card."""
    ctx = build_summary_context(today=TODAY)
    latest, older = ctx["cards"][0], ctx["cards"][1]
    assert latest["income"] != older["income"]  # fixture guarantees distinct

    default_page = client.get("/").text
    assert _incomes(default_page)[0] == f"{latest['income']:.2f}"

    older_page = client.get(f"/?period={older['start'].isoformat()}").text
    assert _incomes(older_page)[0] == f"{older['income']:.2f}"
    assert older["label"] in older_page


def test_date_jump_selects_containing_period(client):
    """?date_from inside an older period jumps to that period."""
    ctx = build_summary_context(today=TODAY)
    older = ctx["cards"][1]
    mid = older["start"].isoformat()
    page = client.get(f"/?date_from={mid}").text
    assert _incomes(page)[0] == f"{older['income']:.2f}"


def test_prev_next_disabled_at_boundaries(client):
    """Newer disabled at latest period; Older disabled at oldest."""
    ctx = build_summary_context(today=TODAY)
    latest_page = client.get("/").text
    assert re.search(r'period-next disabled', latest_page)
    assert re.search(r'<a class="btn period-prev"', latest_page)

    oldest = ctx["cards"][-1]
    oldest_page = client.get(f"/?period={oldest['start'].isoformat()}").text
    assert re.search(r'period-prev disabled', oldest_page)
    assert re.search(r'<a class="btn period-next"', oldest_page)


def test_period_picker_lists_all_periods(client):
    ctx = build_summary_context(today=TODAY)
    page = client.get("/").text
    for card in ctx["cards"]:
        assert f'value="{card["start"].isoformat()}"' in page


def test_unknown_period_falls_back_to_latest(client):
    ctx = build_summary_context(today=TODAY)
    page = client.get("/?period=1999-01-01").text
    assert _incomes(page)[0] == f"{ctx['cards'][0]['income']:.2f}"


# ── Currency conversion (the previously dead nav switcher) ──────────────────

def test_currency_switch_actually_converts_numbers(client):
    """POST /currency then GET /: displayed numbers change by the EUR rate."""
    rates = load_rates()
    assert rates.get("EUR"), "fixture DB must know an EUR rate"
    base_income = build_summary_context(today=TODAY)["cards"][0]["income"]

    resp = client.post("/currency", data={"currency": "EUR"},
                       follow_redirects=False)
    assert resp.status_code == 303
    page = client.get("/").text
    assert "(EUR)" in page
    shown = float(_incomes(page)[0])
    assert shown == pytest.approx(base_income / rates["EUR"], abs=0.01)
    assert shown != pytest.approx(base_income)  # conversion actually happened


def test_converted_numbers_stay_internally_consistent(client):
    """income − expense − savings == net in the DISPLAYED currency."""
    client.post("/currency", data={"currency": "EUR"}, follow_redirects=False)
    page = client.get("/").text
    f = _fields(page)
    assert f["net"] == pytest.approx(
        f["income"] - f["expense"] - f["savings"], abs=0.02)


def test_default_currency_shows_base_values_unchanged(client):
    """No cookie preference → base currency, numbers identical to context."""
    df_page = client.get("/").text
    expected = build_summary_context(today=TODAY)["cards"][0]["income"]
    assert _incomes(df_page)[0] == f"{expected:.2f}"
    assert f"({settings.DISPLAY_CURRENCY})" in df_page


def test_history_rows_are_converted_too(client):
    """Conversion covers every card, not just the primary one."""
    rates = load_rates()
    ctx = build_summary_context(today=TODAY)
    client.post("/currency", data={"currency": "EUR"}, follow_redirects=False)
    page = client.get("/").text
    shown = [float(v) for v in _incomes(page)]
    expected = [c["income"] / rates["EUR"] for c in ctx["cards"]]
    assert shown == pytest.approx(expected, abs=0.01)


# ── Cycles page ──────────────────────────────────────────────────────────────

def test_cycles_rows_link_to_transactions(client):
    """Each history row links to /transactions with that cycle's range."""
    page = client.get("/cycles").text
    # Completed cycle: May 28 → Jun 26 (day before the next boundary).
    assert "/transactions?date_from=2025-05-28&amp;date_to=2025-06-26" in page
    # Open cycle ends "today" for filtering purposes.
    assert f"/transactions?date_from=2025-06-27&amp;date_to={TODAY.isoformat()}" in page


def test_cycles_current_card_and_progress(client):
    page = client.get("/cycles").text
    assert "Current cycle" in page
    assert ">24<" in page  # day 24 of the Jun 27 cycle on Jul 20
    # Exactly one completed cycle (30 days) → typical length derivable.
    assert "Typical cycle: 30 days" in page
    assert 'class="cycle-progress"' in page
    assert "current-row" in page


def test_cycles_zero_recorded(excel_path, monkeypatch):
    """No ledger at all: no crash, no progress bar, honest empty state."""
    from fastapi.testclient import TestClient
    from web.app import create_app
    monkeypatch.setattr(settings, "BUDGET_CYCLE", True)
    monkeypatch.setattr(settings, "WEB_PASSWORD", "test-pass")
    monkeypatch.setattr(settings, "WEB_SESSION_SECRET", "test-secret")
    _freeze_today(monkeypatch)
    client = TestClient(create_app())
    client.post("/login", data={"password": "test-pass"}, follow_redirects=False)
    page = client.get("/cycles")
    assert page.status_code == 200
    assert "No budget cycle recorded yet" in page.text
    assert "cycle-progress" not in page.text


def test_cycles_single_recorded_no_fabricated_progress(excel_path, monkeypatch):
    """One boundary: current card renders but no typical length is invented."""
    from fastapi.testclient import TestClient
    from web.app import create_app
    record_cycle_starts_batch([date(2025, 6, 27)])
    monkeypatch.setattr(settings, "BUDGET_CYCLE", True)
    monkeypatch.setattr(settings, "WEB_PASSWORD", "test-pass")
    monkeypatch.setattr(settings, "WEB_SESSION_SECRET", "test-secret")
    _freeze_today(monkeypatch)
    client = TestClient(create_app())
    client.post("/login", data={"password": "test-pass"}, follow_redirects=False)
    page = client.get("/cycles").text
    assert "Current cycle" in page
    assert "cycle-progress" not in page
    assert "Typical cycle" not in page
    assert f"/transactions?date_from=2025-06-27&amp;date_to={TODAY.isoformat()}" in page


# ── Context math is untouched by the redesign (spot check) ──────────────────

def test_context_still_matches_cycle_totals(web_env):
    import storage_facade
    ctx = build_summary_context(today=TODAY)
    df = storage_facade.load_transactions()
    periods = [p for p in cycle_periods(df, None, TODAY) if p[0] <= TODAY]
    for card, (start, end, label) in zip(ctx["cards"], reversed(periods)):
        totals = cycle_totals(df, start, end)
        assert card["income"] == pytest.approx(totals["income"])
        assert card["expense"] == pytest.approx(totals["expense"])
