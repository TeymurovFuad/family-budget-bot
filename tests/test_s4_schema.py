"""
tests/test_s4_schema.py — S4 Sub-goal A: cycles, salary_keywords schema + facade reads.
"""
import asyncio
import sqlite3
import tempfile
from datetime import date
from pathlib import Path

import pytest

import sqlite_ops


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_db(tmp_path: Path) -> sqlite3.Connection:
    db_file = tmp_path / "test.db"
    return sqlite_ops.init_db(str(db_file))


# ── Cycle tests ───────────────────────────────────────────────────────────────

def test_upsert_cycle_dedup(tmp_path):
    conn = _make_db(tmp_path)
    first = sqlite_ops.upsert_cycle(conn, "2026-01-01", "Jan 2026")
    second = sqlite_ops.upsert_cycle(conn, "2026-01-01", "Jan 2026 dup")
    assert first is True
    assert second is False
    conn.close()


def test_delete_cycle(tmp_path):
    conn = _make_db(tmp_path)
    sqlite_ops.upsert_cycle(conn, "2026-02-01", "Feb 2026")
    deleted = sqlite_ops.delete_cycle(conn, "2026-02-01")
    second_delete = sqlite_ops.delete_cycle(conn, "2026-02-01")
    assert deleted is True
    assert second_delete is False
    conn.close()


def test_list_cycles_ordered(tmp_path):
    conn = _make_db(tmp_path)
    sqlite_ops.upsert_cycle(conn, "2026-03-01", "Mar 2026")
    sqlite_ops.upsert_cycle(conn, "2026-01-01", "Jan 2026")
    sqlite_ops.upsert_cycle(conn, "2026-02-01", "Feb 2026")
    cycles = sqlite_ops.list_cycles(conn)
    dates = [c["start_date"] for c in cycles]
    assert dates == ["2026-01-01", "2026-02-01", "2026-03-01"]
    conn.close()


# ── Salary keyword tests ──────────────────────────────────────────────────────

def test_insert_salary_keyword_normalizes(tmp_path):
    conn = _make_db(tmp_path)
    first = sqlite_ops.insert_salary_keyword(conn, "SALARY ")
    keywords = sqlite_ops.list_salary_keywords(conn)
    assert first is True
    assert "salary" in keywords
    dupe = sqlite_ops.insert_salary_keyword(conn, "salary")
    assert dupe is False
    conn.close()


def test_list_salary_keywords_insertion_order(tmp_path):
    conn = _make_db(tmp_path)
    sqlite_ops.insert_salary_keyword(conn, "bonus")
    sqlite_ops.insert_salary_keyword(conn, "allowance")
    sqlite_ops.insert_salary_keyword(conn, "salary")
    kws = sqlite_ops.list_salary_keywords(conn)
    assert kws == ["bonus", "allowance", "salary"]
    conn.close()


# ── Migration test ────────────────────────────────────────────────────────────

def test_category_type_column_migration(tmp_path):
    """init_db on an existing DB without category_type column adds it safely."""
    db_file = tmp_path / "migrate_test.db"
    # Create the DB without category_type by using raw sqlite3
    raw_conn = sqlite3.connect(str(db_file))
    raw_conn.execute("CREATE TABLE IF NOT EXISTS categories (name TEXT PRIMARY KEY, budget_base REAL, active INTEGER)")
    raw_conn.commit()
    raw_conn.close()

    # Now call init_db — should add column without error
    conn = sqlite_ops.init_db(str(db_file))
    cols = {r[1] for r in conn.execute("PRAGMA table_info(categories)")}
    assert "category_type" in cols
    conn.close()


# ── Facade tests ──────────────────────────────────────────────────────────────

@pytest.fixture()
def patched_db(tmp_path, monkeypatch):
    """Point storage_facade at a fresh temp DB."""
    import settings
    db_file = str(tmp_path / "facade_test.db")
    monkeypatch.setattr(settings, "SQLITE_DB_PATH", db_file)
    # Ensure DB is initialized
    conn = sqlite_ops.init_db(db_file)
    conn.close()
    return db_file


def test_load_rates_facade(patched_db):
    import storage_facade
    conn = sqlite_ops.init_db(patched_db)
    sqlite_ops.upsert_rate(conn, "USD", 0.85)
    conn.close()
    rates = storage_facade.load_rates()
    assert "USD" in rates
    assert abs(rates["USD"] - 0.85) < 1e-9


def test_load_budgets_facade(patched_db):
    import storage_facade
    conn = sqlite_ops.init_db(patched_db)
    sqlite_ops.upsert_category(conn, "Food", budget_base=500.0)
    conn.close()
    budgets = storage_facade.load_budgets()
    assert "Food" in budgets
    assert budgets["Food"] == 500.0


def test_load_cycles_facade(patched_db):
    import storage_facade
    conn = sqlite_ops.init_db(patched_db)
    sqlite_ops.upsert_cycle(conn, "2026-05-01", "May 2026")
    conn.close()
    cycles = storage_facade.load_cycles()
    assert len(cycles) == 1
    start, label = cycles[0]
    assert start == date(2026, 5, 1)
    assert label == "May 2026"


def test_load_salary_keywords_facade(patched_db):
    import storage_facade
    conn = sqlite_ops.init_db(patched_db)
    sqlite_ops.insert_salary_keyword(conn, "salary")
    conn.close()
    kws = storage_facade.load_salary_keywords()
    assert "salary" in kws