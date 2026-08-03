"""
tests/test_value_search.py — Feature B: value/amount search.

Covers _build_where logic and end-to-end list_transactions /
count_transactions with value_search.
"""

import sqlite_ops


# ── _build_where unit tests ───────────────────────────────────────────────────

def test_build_where_integer_value_uses_between():
    where, params = sqlite_ops._build_where(None, None, None, None,
                                            value_search=46.0)
    assert len(where) == 1
    clause = where[0]
    assert "BETWEEN" in clause
    assert params == [45.51, 46.49]


def test_build_where_decimal_value_uses_abs():
    where, params = sqlite_ops._build_where(None, None, None, None,
                                            value_search=45.99)
    assert len(where) == 1
    clause = where[0]
    assert "ABS" in clause
    assert params == [45.99]


def test_build_where_both_desc_and_value_uses_or():
    where, params = sqlite_ops._build_where(None, None, None, "coffee",
                                            value_search=5.0)
    assert len(where) == 1
    clause = where[0]
    # Must be an OR clause wrapping both conditions
    assert "OR" in clause
    assert "description LIKE ?" in clause
    assert "BETWEEN" in clause
    # First param is the LIKE pattern, then the BETWEEN bounds
    assert params[0] == "%coffee%"
    assert params[1] == 4.51
    assert params[2] == 5.49


def test_build_where_desc_only_no_value():
    where, params = sqlite_ops._build_where(None, None, None, "coffee",
                                            value_search=None)
    assert len(where) == 1
    assert "description LIKE ?" in where[0]
    assert params == ["%coffee%"]


def test_build_where_no_search_terms():
    where, params = sqlite_ops._build_where(None, None, None, None,
                                            value_search=None)
    assert where == []
    assert params == []


# ── Integration tests ─────────────────────────────────────────────────────────

import pytest


@pytest.fixture()
def db(tmp_path):
    conn = sqlite_ops.init_db(tmp_path / "test_vs.db")
    yield conn
    conn.close()


def _insert(conn, **overrides):
    row = {
        "date": "2024-06-15", "year": 2024, "month": "Jun",
        "value": 100.0, "currency": "PLN", "value_base": 100.0,
        "rate_used": 1.0, "type": "Expense", "category": "Food",
        "person": "Alice", "description": "test row",
        "is_recurring": False, "is_done": True, "source": "test",
    }
    row.update(overrides)
    sqlite_ops.insert_transaction(conn, row)


def test_list_transactions_integer_value_search(db):
    _insert(db, value_base=46.0, description="bus ticket")
    _insert(db, value_base=46.3, description="another bus")   # within ±0.49
    _insert(db, value_base=47.0, description="too high")      # outside band
    _insert(db, value_base=50.0, description="unrelated")

    rows = sqlite_ops.list_transactions(db, value_search=46.0)
    descs = {r["description"] for r in rows}
    assert "bus ticket" in descs
    assert "another bus" in descs
    assert "too high" not in descs
    assert "unrelated" not in descs


def test_list_transactions_decimal_value_search(db):
    _insert(db, value_base=45.99, description="exact match")
    _insert(db, value_base=45.991, description="within tolerance")  # < 0.001 diff
    _insert(db, value_base=46.0, description="outside tolerance")

    rows = sqlite_ops.list_transactions(db, value_search=45.99)
    descs = {r["description"] for r in rows}
    assert "exact match" in descs
    assert "within tolerance" in descs
    assert "outside tolerance" not in descs


def test_count_transactions_decimal_value_search(db):
    _insert(db, value_base=45.99, description="one")
    _insert(db, value_base=45.99, description="two")
    _insert(db, value_base=10.0, description="other")

    count = sqlite_ops.count_transactions(db, value_search=45.99)
    assert count == 2


def test_list_transactions_or_logic_desc_or_value(db):
    _insert(db, value_base=5.0, description="coffee")       # matches both
    _insert(db, value_base=5.0, description="bus")          # matches value only
    _insert(db, value_base=99.0, description="coffee shop") # matches desc only
    _insert(db, value_base=99.0, description="lunch")       # matches neither

    rows = sqlite_ops.list_transactions(db, description_contains="coffee",
                                        value_search=5.0)
    descs = {r["description"] for r in rows}
    assert "coffee" in descs
    assert "bus" in descs
    assert "coffee shop" in descs
    assert "lunch" not in descs
