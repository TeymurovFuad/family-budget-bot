"""
test_web_transactions_v2.py — route-level tests for the v2 "Ledger"
Transactions page: date-range filtering, description search, sort options,
pagination, session-currency display conversion (the "dead control" fix),
HTMX fragment swaps, and graceful no-param / no-JS degradation.
"""

import re
from datetime import date

import pytest

import settings
import sqlite_ops

PASSWORD = "hunter2"


def _txn(**overrides) -> dict:
    row = {
        "date": "2024-06-15", "year": 2024, "month": "Jun", "value": 150.5,
        "currency": "PLN", "value_base": 150.5, "rate_used": 1.0,
        "type": "Expense", "category": "Groceries", "person": "Alice",
        "description": "weekly shop", "is_recurring": False, "is_done": True,
        "source": "test",
    }
    row.update(overrides)
    return row


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "WEB_PASSWORD", PASSWORD)
    monkeypatch.setattr(settings, "WEB_SESSION_SECRET", "s3cret")
    monkeypatch.setattr(settings, "SQLITE_DB_PATH", tmp_path / "web.db")
    conn = sqlite_ops.init_db(settings.SQLITE_DB_PATH)
    sqlite_ops.upsert_person(conn, "Alice")
    sqlite_ops.upsert_person(conn, "Bob")
    sqlite_ops.upsert_category(conn, "Groceries")
    sqlite_ops.upsert_category(conn, "Fun")
    sqlite_ops.upsert_rate(conn, "USD", 4.0)
    # Ten expenses on distinct June days + one income + one savings row.
    for i in range(10):
        sqlite_ops.insert_transaction(conn, _txn(
            date=f"2024-06-{10 + i:02d}", value=100.0 + i, value_base=100.0 + i,
            description=f"item {i}",
            category="Groceries" if i % 2 == 0 else "Fun",
            person="Alice" if i % 2 == 0 else "Bob"))
    sqlite_ops.insert_transaction(conn, _txn(
        date="2024-06-25", type="Income", value=4000.0, value_base=4000.0,
        category="Salary income", description="salary payment"))
    sqlite_ops.insert_transaction(conn, _txn(
        date="2024-06-26", type="Savings", value=400.0, value_base=400.0,
        category="Emergency fund", description="monthly stash"))
    conn.close()

    from fastapi.testclient import TestClient
    from web.app import create_app
    c = TestClient(create_app())
    c.post("/login", data={"password": PASSWORD}, follow_redirects=False)
    return c


def _descriptions(html: str) -> list[str]:
    return re.findall(r'class="txn-desc">([^<]*)<', html)


# ── graceful defaults ─────────────────────────────────────────────────────────

def test_no_query_params_renders_defaults(client):
    resp = client.get("/transactions")
    assert resp.status_code == 200
    today = date.today()
    # Default calendar-month range pre-filled into visible date inputs.
    assert f'name="date_from" value="{today.replace(day=1).isoformat()}"' in resp.text
    assert 'name="date_to" value="' in resp.text
    assert "<html" in resp.text  # full page, not a fragment


def test_explicitly_cleared_dates_mean_all_time(client):
    resp = client.get("/transactions?date_from=&date_to=")
    assert resp.status_code == 200
    assert "12 transactions" in resp.text
    assert "all time" in resp.text


def test_noscript_form_degrades_to_plain_get(client):
    # The toolbar is a plain GET form; a JS-less submit is just this URL.
    resp = client.get("/transactions", params={
        "q": "", "date_from": "2024-06-10", "date_to": "2024-06-12",
        "person": "", "category": "", "sort": "date_desc"})
    assert resp.status_code == 200
    assert _descriptions(resp.text) == ["item 2", "item 1", "item 0"]


# ── date range ────────────────────────────────────────────────────────────────

def test_date_range_filters_results(client):
    all_time = client.get("/transactions?date_from=&date_to=").text
    ranged = client.get("/transactions?date_from=2024-06-11&date_to=2024-06-13").text
    assert "12 transactions" in all_time
    assert "3 transactions" in ranged
    assert _descriptions(ranged) == ["item 3", "item 2", "item 1"]


def test_invalid_dates_treated_as_open(client):
    resp = client.get("/transactions?date_from=nonsense&date_to=2024-13-99")
    assert resp.status_code == 200
    assert "12 transactions" in resp.text


# ── search ────────────────────────────────────────────────────────────────────

def test_search_filters_by_description_substring(client):
    resp = client.get("/transactions?date_from=&date_to=&q=salary")
    assert "1 transaction " in resp.text
    assert _descriptions(resp.text) == ["salary payment"]


def test_search_no_match_shows_empty_state(client):
    resp = client.get("/transactions?date_from=&date_to=&q=zzz-no-such-thing")
    assert "No transactions match" in resp.text
    assert "Reset filters" in resp.text


# ── sorting ───────────────────────────────────────────────────────────────────

def test_sort_newest_first_is_default_and_grouped(client):
    resp = client.get("/transactions?date_from=&date_to=").text
    descs = _descriptions(resp)
    assert descs[0] == "monthly stash"
    assert descs[-1] == "item 0"
    assert 'class="txn-date"' in resp  # grouped day headers


@pytest.mark.parametrize("sort_key,expected_first,expected_last", [
    ("date_asc", "item 0", "monthly stash"),
    ("value_desc", "salary payment", "item 0"),
    ("value_asc", "item 0", "salary payment"),
])
def test_sort_orderings(client, sort_key, expected_first, expected_last):
    resp = client.get(f"/transactions?date_from=&date_to=&sort={sort_key}").text
    descs = _descriptions(resp)
    assert descs[0] == expected_first
    assert descs[-1] == expected_last


def test_sort_description_a_to_z(client):
    resp = client.get("/transactions?date_from=&date_to=&sort=description_asc").text
    descs = _descriptions(resp)
    assert descs == sorted(descs)


@pytest.mark.parametrize("sort_key", ["category_asc", "person_asc"])
def test_remaining_sort_options_render(client, sort_key):
    resp = client.get(f"/transactions?date_from=&date_to=&sort={sort_key}")
    assert resp.status_code == 200
    assert len(_descriptions(resp.text)) == 12


def test_non_date_sort_renders_flat_with_inline_dates(client):
    resp = client.get("/transactions?date_from=&date_to=&sort=value_desc").text
    assert 'class="txn-date"' not in resp  # no sticky day headers
    assert 'txn-inline-date' in resp


def test_unknown_sort_falls_back_to_default(client):
    resp = client.get("/transactions?date_from=&date_to=&sort=id;DROP")
    assert resp.status_code == 200
    assert _descriptions(resp.text)[0] == "monthly stash"


# ── pagination ────────────────────────────────────────────────────────────────

@pytest.fixture()
def paged_client(client, monkeypatch):
    import web.routes.transactions as t
    monkeypatch.setattr(t, "PER_PAGE_OPTIONS", (5,))
    monkeypatch.setattr(t, "PER_PAGE_DEFAULT", 5)
    return client


def test_pagination_slices_and_page_count(paged_client):
    page1 = paged_client.get("/transactions?date_from=&date_to=&sort=value_asc").text
    page2 = paged_client.get("/transactions?date_from=&date_to=&sort=value_asc&offset=5").text
    page3 = paged_client.get("/transactions?date_from=&date_to=&sort=value_asc&offset=10").text
    assert "Page 1 of 3" in page1
    assert _descriptions(page1) == [f"item {i}" for i in range(5)]
    assert _descriptions(page2) == [f"item {i}" for i in range(5, 10)]
    assert _descriptions(page3) == ["monthly stash", "salary payment"]
    # Next link carries offset and preserves the sort + explicit dates.
    assert "offset=5" in page1
    assert "sort=value_asc" in page1


def test_offset_beyond_total_is_clamped(paged_client):
    resp = paged_client.get("/transactions?date_from=&date_to=&offset=9999")
    assert resp.status_code == 200
    assert "Page 3 of 3" in resp.text
    assert _descriptions(resp.text)  # last page, not empty


def test_negative_offset_clamped_to_first_page(paged_client):
    resp = paged_client.get("/transactions?date_from=&date_to=&offset=-50")
    assert "Page 1 of 3" in resp.text


# ── rows-per-page selector ────────────────────────────────────────────────────

@pytest.fixture()
def big_client(monkeypatch, tmp_path):
    """Client over 120 expense rows — enough to exercise all real page
    sizes (25/50/100) without monkeypatching the whitelist."""
    monkeypatch.setattr(settings, "WEB_PASSWORD", PASSWORD)
    monkeypatch.setattr(settings, "WEB_SESSION_SECRET", "s3cret")
    monkeypatch.setattr(settings, "SQLITE_DB_PATH", tmp_path / "big.db")
    conn = sqlite_ops.init_db(settings.SQLITE_DB_PATH)
    sqlite_ops.upsert_person(conn, "Alice")
    sqlite_ops.upsert_category(conn, "Groceries")
    for i in range(120):
        sqlite_ops.insert_transaction(conn, _txn(
            date=f"2024-06-{1 + i % 30:02d}", value=100.0 + i,
            value_base=100.0 + i, description=f"row {i:03d}"))
    conn.close()

    from fastapi.testclient import TestClient
    from web.app import create_app
    c = TestClient(create_app())
    c.post("/login", data={"password": PASSWORD}, follow_redirects=False)
    return c


@pytest.mark.parametrize("size,pages", [(25, 5), (50, 3), (100, 2)])
def test_per_page_options_slice_and_page_count(big_client, size, pages):
    html = big_client.get(
        f"/transactions?date_from=&date_to=&per_page={size}").text
    assert len(_descriptions(html)) == size
    assert f"Page 1 of {pages}" in html


def test_per_page_out_of_whitelist_falls_back_to_default(big_client):
    for bad in (9999, 0, -25, 33):
        html = big_client.get(
            f"/transactions?date_from=&date_to=&per_page={bad}").text
        assert len(_descriptions(html)) == 50
        assert "Page 1 of 3" in html
        # The fallback value is the default, so no link re-emits it.
        assert "per_page=" not in html


def test_per_page_default_omitted_from_urls_like_sort(big_client):
    html = big_client.get("/transactions?date_from=&date_to=").text
    # Mirrors sort: the default (50) never appears in generated URLs; the
    # only 'per_page' occurrences are the select's name attribute.
    assert "per_page=" not in html
    assert 'name="per_page"' in html


def test_per_page_non_default_propagates_to_links(big_client):
    html = big_client.get(
        "/transactions?date_from=&date_to=&per_page=25&sort=value_asc").text
    # Next link keeps both the page size and the sort.
    m = re.search(r'href="([^"]*offset=25[^"]*)"', html)
    assert m and "per_page=25" in m.group(1) and "sort=value_asc" in m.group(1)
    # Preset range chips keep it too.
    p = re.search(r'class="chip chip--preset[^"]*"\s+href="([^"]*)"', html)
    assert p and "per_page=25" in p.group(1)
    # The selected option is marked.
    assert re.search(r'value="25"\s+selected', html)


def test_changing_per_page_resets_to_page_1(big_client):
    # Deep on page 3 of 25s...
    deep = big_client.get(
        "/transactions?date_from=&date_to=&per_page=25&offset=50").text
    assert "Page 3 of 5" in deep
    # ...the page-size form carries no offset field, so submitting it (htmx
    # or plain GET) lands on page 1 of the new size.
    form = re.search(r'<form method="get"[^>]*class="page-size-form".*?</form>',
                     deep, re.S).group(0)
    assert 'name="offset"' not in form
    resized = big_client.get(
        "/transactions?date_from=&date_to=&per_page=100").text
    assert "Page 1 of 2" in resized


def test_toolbar_keeps_non_default_per_page_across_filter_changes(big_client):
    html = big_client.get("/transactions?date_from=&date_to=&per_page=25").text
    assert re.search(r'<form class="toolbar".*?type="hidden" name="per_page" value="25"',
                     html, re.S)
    default = big_client.get("/transactions?date_from=&date_to=").text
    assert 'type="hidden" name="per_page"' not in default


def test_page_size_form_preserves_active_filters(client):
    html = client.get("/transactions?date_from=&date_to=&q=item"
                      "&person=Alice&sort=value_desc&per_page=25").text
    form = re.search(r'<form method="get"[^>]*class="page-size-form".*?</form>',
                     html, re.S).group(0)
    # Hidden inputs mirror the canonical query-string rules: dates always,
    # q/person when set, sort when non-default — so a no-JS submit keeps
    # every active filter.
    for field in ('name="q" value="item"', 'name="date_from" value=""',
                  'name="date_to" value=""', 'name="person" value="Alice"',
                  'name="sort" value="value_desc"'):
        assert field in form
    assert 'name="category"' not in form  # unset filters not emitted
    assert re.search(r'value="25"\s+selected', form)


# ── currency conversion (the "dead control" regression test) ─────────────────

def test_session_currency_converts_displayed_amounts(client):
    # Base currency amounts first.
    before = client.get("/transactions?date_from=&date_to=&q=salary").text
    assert "+4000.00" in before
    assert f'class="txn-ccy">{settings.DISPLAY_CURRENCY}' in before

    # Switch session currency to USD (rate 4.0 → base / 4).
    client.post("/currency", data={"currency": "USD"}, follow_redirects=False)
    after = client.get("/transactions?date_from=&date_to=&q=salary").text
    assert "+1000.00" in after
    assert "+4000.00" not in after
    assert 'class="txn-ccy">USD' in after


def test_expense_income_savings_kinds_and_signs(client):
    html = client.get("/transactions?date_from=&date_to=").text
    assert re.search(r'amount--neg">-1\d\d\.00', html)   # expenses negative
    assert 'amount--pos">+4000.00' in html               # income positive
    assert 'amount--save">400.00' in html                # savings unsigned


# ── HTMX fragment swap ────────────────────────────────────────────────────────

def test_hx_request_returns_fragment_only(client):
    resp = client.get("/transactions?date_from=&date_to=",
                      headers={"HX-Request": "true"})
    assert resp.status_code == 200
    assert "<html" not in resp.text
    assert 'id="txn-list"' not in resp.text  # inner content only
    assert 'class="txn"' in resp.text
    assert 'class="pagination"' in resp.text


def test_person_category_filters_still_work(client):
    resp = client.get("/transactions?date_from=&date_to=&person=Alice&category=Fun")
    assert _descriptions(resp.text) == []  # Alice never buys Fun
    resp = client.get("/transactions?date_from=&date_to=&person=Bob&category=Fun")
    assert len(_descriptions(resp.text)) == 5
    # Active filters render as removable chips.
    assert 'chip--filter' in resp.text


# ── Apply button + preset range chips (date-filter reliability fixes) ────────

def test_apply_button_always_visible_and_dates_not_auto_applied(client):
    html = client.get("/transactions").text
    # Apply is a real, always-visible submit button (not inside <noscript>).
    assert 'class="btn--primary toolbar-apply"' in html
    assert "<noscript><button type=\"submit\">Filter" not in html
    # Date inputs no longer auto-apply via htmx change events (the silent
    # mobile failure); only submit + select changes trigger.
    m = re.search(r'<form class="toolbar"[^>]*hx-trigger="([^"]*)"', html)
    assert m and m.group(1) == "submit, change target:select"
    assert "input[type='date']" not in (m.group(1) or "")


def test_bug_scenario_plain_get_with_dates_filters(client):
    """The exact reported bug: widening/narrowing the date range must apply
    on a plain (non-JS, non-htmx) GET — the Apply button path."""
    default = client.get("/transactions").text
    filtered = client.get("/transactions", params={
        "q": "", "date_from": "2024-06-10", "date_to": "2024-06-12",
        "person": "", "category": "", "sort": "date_desc"}).text
    assert _descriptions(filtered) == ["item 2", "item 1", "item 0"]
    assert _descriptions(filtered) != _descriptions(default)
    # Visible confirmation inside the swapped fragment.
    assert "Showing 3 of 3" in filtered


class _FrozenDatetime(__import__("datetime").datetime):
    @classmethod
    def now(cls, tz=None):
        from datetime import datetime, time
        return datetime.combine(date(2024, 6, 15), time(12, 0), tzinfo=tz)


@pytest.fixture()
def frozen_client(client, monkeypatch):
    import web.routes.transactions as t
    monkeypatch.setattr(t, "datetime", _FrozenDatetime)
    return client


def test_preset_chip_this_month_bounds(frozen_client):
    html = frozen_client.get("/transactions").text
    assert re.search(r'class="chip chip--preset[^"]*"\s+href="/transactions\?'
                     r'[^"]*date_from=2024-06-01&amp;date_to=2024-06-30', html)


def test_preset_chip_last_30_days_bounds(frozen_client):
    html = frozen_client.get("/transactions").text
    assert "date_from=2024-05-17&amp;date_to=2024-06-15" in html


def test_preset_chip_this_year_and_all_time(frozen_client):
    html = frozen_client.get("/transactions").text
    assert "date_from=2024-01-01&amp;date_to=2024-12-31" in html
    # All time = present-but-empty date params.
    assert 'href="/transactions?date_from=&amp;date_to="' in html


def test_active_preset_highlighted(frozen_client):
    html = frozen_client.get(
        "/transactions?date_from=2024-06-01&date_to=2024-06-30").text
    assert 'chip--preset is-active' in html
    assert ">This month</a>" in html.split("is-active", 1)[1][:500]
    # A custom range highlights nothing.
    custom = frozen_client.get(
        "/transactions?date_from=2024-06-02&date_to=2024-06-30").text
    assert "is-active" not in custom


def test_preset_chips_preserve_other_filters(frozen_client):
    html = frozen_client.get(
        "/transactions?date_from=&date_to=&person=Alice&sort=value_desc").text
    m = re.search(r'class="chip chip--preset[^"]*"\s+href="([^"]*)"', html)
    assert m
    assert "person=Alice" in m.group(1)
    assert "sort=value_desc" in m.group(1)


def test_unknown_person_category_ignored(client):
    resp = client.get("/transactions?date_from=&date_to=&person=Mallory&category=%27--")
    assert resp.status_code == 200
    assert "12 transactions" in resp.text
