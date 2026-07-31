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
