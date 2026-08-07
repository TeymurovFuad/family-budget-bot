"""Tests for sqlite_ops.py — schema, compute_value_base, hashing, CRUD."""

import sqlite3

import pytest

import settings
import sqlite_ops


@pytest.fixture()
def db(tmp_path):
    conn = sqlite_ops.init_db(tmp_path / "test.db")
    yield conn
    conn.close()


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


# ── Schema ────────────────────────────────────────────────────────────────────

def test_init_db_creates_all_tables(db):
    tables = {r["name"] for r in db.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"transactions", "categories", "persons", "rates", "goals",
            "sync_log"} <= tables


def test_init_db_enables_wal(tmp_path):
    conn = sqlite_ops.init_db(tmp_path / "wal.db")
    try:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    finally:
        conn.close()


def test_init_db_is_rerunnable(tmp_path):
    path = tmp_path / "twice.db"
    sqlite_ops.init_db(path).close()
    sqlite_ops.init_db(path).close()  # must not raise


# ── compute_value_base (VLOOKUP-formula semantics) ────────────────────────────

def test_value_base_same_currency(db):
    assert sqlite_ops.compute_value_base(100.0, "PLN", {"USD": 4.0}, "PLN") == (100.0, 1.0)


def test_value_base_empty_currency(db):
    assert sqlite_ops.compute_value_base(100.0, "", {"USD": 4.0}, "PLN") == (100.0, 1.0)
    assert sqlite_ops.compute_value_base(100.0, None, {"USD": 4.0}, "PLN") == (100.0, 1.0)


def test_value_base_foreign_currency(db):
    assert sqlite_ops.compute_value_base(100.0, "USD", {"USD": 4.0}, "PLN") == (400.0, 4.0)


def test_value_base_case_insensitive_lookup(db):
    # VLOOKUP text matching is case-insensitive; rates are stored uppercase.
    assert sqlite_ops.compute_value_base(10.0, "usd", {"USD": 4.0}, "PLN") == (40.0, 4.0)
    assert sqlite_ops.compute_value_base(10.0, "pln", {}, "PLN") == (10.0, 1.0)


def test_value_base_unknown_currency_falls_back_to_1(db):
    # Mirrors data.load_data()'s rates.get(ccy, 1.0) fallback.
    assert sqlite_ops.compute_value_base(10.0, "XXX", {"USD": 4.0}, "PLN") == (10.0, 1.0)


def test_value_base_unknown_currency_logs_to_sync_log(db):
    # The rate-1.0 fallback must be visible in sync_log when a conn is given —
    # a typo'd currency during import should never be silently valued 1:1.
    sqlite_ops.compute_value_base(10.0, "XXX", {"USD": 4.0}, "PLN", conn=db)
    row = db.execute("SELECT * FROM sync_log").fetchone()
    assert row["status"] == "error"
    assert "XXX" in row["detail"]
    # Known / display / empty currencies must NOT log anything.
    sqlite_ops.compute_value_base(10.0, "USD", {"USD": 4.0}, "PLN", conn=db)
    sqlite_ops.compute_value_base(10.0, "PLN", {"USD": 4.0}, "PLN", conn=db)
    sqlite_ops.compute_value_base(10.0, "", {"USD": 4.0}, "PLN", conn=db)
    assert db.execute("SELECT COUNT(*) FROM sync_log").fetchone()[0] == 1


# ── golden master: compute_value_base vs the real Excel formula ───────────────
# excel_schema.write_transaction_row writes (for row r):
#   =IF(OR(Ccy{r}="",Ccy{r}="<DISPLAY>"),Value{r},
#       Value{r}*VLOOKUP(Ccy{r},Lists!Currency:Rate,2,0))
# The evaluator below reproduces Excel's semantics for that exact formula:
# text `=` comparison is case-insensitive, VLOOKUP exact match (range_lookup 0)
# is case-insensitive, and an absent currency yields #N/A.

_NA = "#N/A"


def _excel_formula_value_base(value, ccy_cell, display, lists_rows):
    """Evaluate the Value (base) formula the way Excel would."""
    ccy = "" if ccy_cell is None else str(ccy_cell)
    if ccy == "" or ccy.casefold() == str(display).casefold():
        return value
    for cur, rate in lists_rows:  # VLOOKUP(..., 2, 0): first exact match
        if str(cur).casefold() == ccy.casefold():
            return value * rate
    return _NA


# Lists sheet as written by excel_schema.load_currency_rates_from_path
# consumers: currency codes stored uppercase.
_GOLDEN_LISTS = [("PLN", 1.0), ("USD", 4.0), ("EUR", 4.3), ("GBP", 5.1)]
_GOLDEN_RATES = dict(_GOLDEN_LISTS)

_GOLDEN_CASES = [
    # (value, currency-cell, display currency)
    (100.0, "PLN", "PLN"),    # display-currency shortcut
    (100.0, "pln", "PLN"),    # case-insensitive display match
    (100.0, "", "PLN"),       # empty currency
    (100.0, None, "PLN"),     # None currency (empty cell)
    (100.0, "USD", "PLN"),    # plain VLOOKUP
    (100.0, "usd", "PLN"),    # case-insensitive VLOOKUP
    (-42.5, "EUR", "PLN"),    # negative value
    (0.0, "GBP", "PLN"),      # zero value
    (7.77, "EUR", "USD"),     # different display currency
    (100.0, "XXX", "PLN"),    # unknown currency → Excel #N/A
]


@pytest.mark.parametrize("value,ccy,display", _GOLDEN_CASES)
def test_value_base_matches_excel_formula_golden_master(value, ccy, display):
    excel = _excel_formula_value_base(value, ccy, display, _GOLDEN_LISTS)
    got_vb, got_rate = sqlite_ops.compute_value_base(value, ccy, _GOLDEN_RATES, display)
    if excel == _NA:
        # Documented divergence: Excel errors, we keep the row at rate 1.0
        # (mirrors data.load_data(); the fallback is logged to sync_log when
        # a connection is provided — see the test above).
        assert (got_vb, got_rate) == (value, 1.0)
    else:
        assert got_vb == pytest.approx(excel)
        assert got_vb == pytest.approx(value * got_rate)


# ── content hash ──────────────────────────────────────────────────────────────

def test_content_hash_deterministic():
    args = ("2024-06-15", 150.5, "PLN", "Expense", "Groceries", "Alice",
            "weekly shop", "2024-06-15T10:00:00")
    assert sqlite_ops.content_hash_for_row(*args) == sqlite_ops.content_hash_for_row(*args)


def test_content_hash_changes_with_fields():
    base = ["2024-06-15", 150.5, "PLN", "Expense", "Groceries", "Alice",
            "weekly shop", "2024-06-15T10:00:00"]
    other = list(base)
    other[1] = 151.5
    assert sqlite_ops.content_hash_for_row(*base) != sqlite_ops.content_hash_for_row(*other)


# ── CRUD ──────────────────────────────────────────────────────────────────────

def test_insert_and_list_roundtrip(db):
    rid = sqlite_ops.insert_transaction(db, _txn())
    rows = sqlite_ops.list_transactions(db)
    assert len(rows) == 1
    assert rows[0]["id"] == rid
    assert rows[0]["value"] == 150.5
    assert rows[0]["category"] == "Groceries"
    assert rows[0]["is_done"] == 1
    assert rows[0]["content_hash"]


def test_duplicate_insert_is_noop(db):
    row = _txn(date_modified_utc="2024-06-15T10:00:00")
    id1 = sqlite_ops.insert_transaction(db, dict(row))
    id2 = sqlite_ops.insert_transaction(db, dict(row))
    assert id1 == id2
    assert len(sqlite_ops.list_transactions(db)) == 1


def test_distinct_bot_rows_without_date_modified_are_both_kept(db):
    # Two legitimate same-looking transactions (e.g. two same-day coffees) —
    # no date_modified_utc supplied, as in the facade's append path. The
    # write timestamp must enter the content hash so neither row is silently
    # dropped by ON CONFLICT DO NOTHING.
    import time
    id1 = sqlite_ops.insert_transaction(db, _txn())
    time.sleep(0.001)  # guarantee a distinct write timestamp
    id2 = sqlite_ops.insert_transaction(db, _txn())
    assert id1 != id2
    rows = sqlite_ops.list_transactions(db)
    assert len(rows) == 2
    assert all(r["date_modified_utc"] for r in rows)


def test_caller_supplied_hash_preserves_null_date_modified(db):
    # The Excel importer hashes over the raw source values (date_modified may
    # be None) and passes content_hash explicitly. insert_transaction must
    # store the row exactly as given — no fresh timestamp — so re-imports
    # keep hitting the same hash.
    h = sqlite_ops.content_hash_for_row(
        "2024-06-15", 150.5, "PLN", "Expense", "Groceries", "Alice",
        "weekly shop", None)
    row = _txn(date_modified_utc=None, content_hash=h)
    id1 = sqlite_ops.insert_transaction(db, dict(row))
    id2 = sqlite_ops.insert_transaction(db, dict(row))
    assert id1 == id2
    rows = sqlite_ops.list_transactions(db)
    assert len(rows) == 1
    assert rows[0]["date_modified_utc"] is None


def test_update_transaction(db):
    rid = sqlite_ops.insert_transaction(db, _txn())
    sqlite_ops.update_transaction(db, rid, {"category": "Dining", "value": 99.0})
    row = sqlite_ops.list_transactions(db)[0]
    assert row["category"] == "Dining"
    assert row["value"] == 99.0
    assert row["date_modified_utc"]


def test_update_rejects_unknown_column(db):
    rid = sqlite_ops.insert_transaction(db, _txn())
    with pytest.raises(ValueError):
        sqlite_ops.update_transaction(db, rid, {"nope; DROP TABLE": 1})


def test_delete_transaction(db):
    rid = sqlite_ops.insert_transaction(db, _txn())
    sqlite_ops.delete_transaction(db, rid)
    assert sqlite_ops.list_transactions(db) == []


def test_list_filters(db):
    sqlite_ops.insert_transaction(db, _txn())
    sqlite_ops.insert_transaction(db, _txn(date="2025-01-05", year=2025, month="Jan",
                                           person="Bob", type="Income", category="Salary"))
    assert len(sqlite_ops.list_transactions(db, {"year": 2024})) == 1
    assert len(sqlite_ops.list_transactions(db, {"person": "Bob"})) == 1
    assert len(sqlite_ops.list_transactions(db, {"type": "Income", "category": "Salary"})) == 1
    assert len(sqlite_ops.list_transactions(db, {"month": "Feb"})) == 0
    with pytest.raises(ValueError):
        sqlite_ops.list_transactions(db, {"description": "x"})


# ── reference upserts + sync log ──────────────────────────────────────────────

def test_upserts(db):
    sqlite_ops.upsert_category(db, "Groceries", 1200.0)
    sqlite_ops.upsert_category(db, "Groceries", 1500.0)
    sqlite_ops.upsert_person(db, "Alice")
    sqlite_ops.upsert_rate(db, "usd", 4.0)
    sqlite_ops.upsert_rate(db, "USD", 4.2)
    sqlite_ops.upsert_goal(db, "Vacation", 0.1, 5000.0)
    assert db.execute("SELECT budget_base FROM categories").fetchone()[0] == 1500.0
    assert db.execute("SELECT COUNT(*) FROM rates").fetchone()[0] == 1
    assert sqlite_ops.load_rates_dict(db) == {"USD": 4.2}
    assert db.execute("SELECT goal_base FROM goals").fetchone()[0] == 5000.0


def test_log_sync(db):
    sqlite_ops.log_sync(db, "import", "ok", "5 rows")
    row = db.execute("SELECT * FROM sync_log").fetchone()
    assert row["direction"] == "import"
    assert row["status"] == "ok"
    assert row["ts"]
