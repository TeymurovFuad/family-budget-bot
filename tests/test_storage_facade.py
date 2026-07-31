"""Tests for storage_facade.py — round-trips and load_data() shape parity."""

import datetime

import pytest

import settings
import sqlite_ops
import storage_facade
from models import Transaction


@pytest.fixture()
def sqlite_db(tmp_path, monkeypatch):
    """Point the facade at a fresh temp DB seeded with a USD rate."""
    db_path = tmp_path / "facade.db"
    monkeypatch.setattr(settings, "SQLITE_DB_PATH", db_path)
    conn = sqlite_ops.init_db(db_path)
    sqlite_ops.upsert_rate(conn, "USD", 4.0)
    sqlite_ops.upsert_rate(conn, settings.DISPLAY_CURRENCY, 1.0)
    conn.close()
    return db_path


def _txn(**overrides) -> Transaction:
    kwargs = dict(
        date=datetime.date(2024, 6, 15), value=150.50,
        currency=settings.DISPLAY_CURRENCY, transaction_type="Expense",
        category="Groceries", person="Alice", description="weekly shop",
        year=2024, month="Jun",
    )
    kwargs.update(overrides)
    return Transaction(**kwargs)


def test_append_load_roundtrip(sqlite_db):
    storage_facade.append_transaction(_txn())
    df = storage_facade.load_transactions()
    assert len(df) == 1
    row = df.iloc[0]
    assert row["Value"] == 150.50
    assert row["_base"] == 150.50
    assert row["Category"] == "Groceries"
    assert bool(row["IsDone"]) is True


def test_append_computes_value_base_for_foreign_currency(sqlite_db):
    storage_facade.append_transaction(_txn(value=100.0, currency="USD"))
    df = storage_facade.load_transactions()
    assert df.iloc[0]["Value (base)"] == 400.0
    assert df.iloc[0]["_base"] == 400.0


def test_dataframe_shape_matches_load_data(sqlite_db):
    """Column names must match what data.load_data() produces today."""
    storage_facade.append_transaction(_txn())
    df = storage_facade.load_transactions()
    expected = ["Date", "Year", "Month", "Value", "Type", "Category", "Person",
                "Description", "IsRecurring", "IsDone", "Currency",
                "Value (base)", "Date Modified (UTC)", "_base"]
    assert list(df.columns) == expected
    assert str(df["Year"].dtype) == "Int64"
    assert df["IsDone"].dtype == bool


def test_load_transactions_filters(sqlite_db):
    storage_facade.append_transaction(_txn())
    storage_facade.append_transaction(
        _txn(date=datetime.date(2025, 1, 5), year=2025, month="Jan",
             description="new year"))
    assert len(storage_facade.load_transactions({"year": 2025})) == 1
    assert len(storage_facade.load_transactions({"year": 2024, "month": "Jun"})) == 1


def test_delete_and_update(sqlite_db):
    storage_facade.append_transaction(_txn())
    conn = sqlite_ops.init_db(sqlite_db)
    rid = sqlite_ops.list_transactions(conn)[0]["id"]
    conn.close()

    storage_facade.update_transaction_field(rid, "Category", "Dining")
    df = storage_facade.load_transactions()
    assert df.iloc[0]["Category"] == "Dining"

    storage_facade.delete_transaction_row(rid)
    assert storage_facade.load_transactions().empty


def test_update_recomputes_value_base(sqlite_db):
    storage_facade.append_transaction(_txn(value=100.0, currency="USD"))
    conn = sqlite_ops.init_db(sqlite_db)
    rid = sqlite_ops.list_transactions(conn)[0]["id"]
    conn.close()
    storage_facade.update_transaction_field(rid, "Value", 200.0)
    row = storage_facade.load_transactions().iloc[0]
    assert row["Value (base)"] == 800.0


def test_expected_snapshot_guard(sqlite_db):
    storage_facade.append_transaction(_txn())
    conn = sqlite_ops.init_db(sqlite_db)
    rid = sqlite_ops.list_transactions(conn)[0]["id"]
    conn.close()
    with pytest.raises(storage_facade.RowMismatchError):
        storage_facade.delete_transaction_row(rid, expected={"Value": 999.99})
    # Matching snapshot passes
    storage_facade.delete_transaction_row(
        rid, expected={"Value": 150.50, "Description": "weekly shop"})


def test_load_reference_data_shape(sqlite_db):
    conn = sqlite_ops.init_db(sqlite_db)
    sqlite_ops.upsert_category(conn, "Groceries", 1200.0)
    sqlite_ops.upsert_category(conn, "Housing", None)
    sqlite_ops.upsert_person(conn, "Alice")
    conn.close()
    storage_facade.append_transaction(_txn())

    ref = storage_facade.load_reference_data()
    assert set(ref) == {"months", "txn_types", "categories", "persons",
                        "years", "budgets", "currencies"}
    assert ref["categories"] == ["Groceries", "Housing"]
    assert ref["persons"] == ["Alice"]
    assert ref["budgets"] == {"Groceries": 1200.0}
    assert ref["years"] == [2024]
    assert "USD" in ref["currencies"]
    assert len(ref["months"]) == 12


def test_read_paths_raise_when_db_missing(tmp_path, monkeypatch):
    """Reads against a never-seeded DB must fail loudly, not return empty data."""
    missing = tmp_path / "does_not_exist.db"
    monkeypatch.setattr(settings, "SQLITE_DB_PATH", missing)
    with pytest.raises(FileNotFoundError, match="import_excel_to_sqlite"):
        storage_facade.load_transactions()
    with pytest.raises(FileNotFoundError, match="import_excel_to_sqlite"):
        storage_facade.load_reference_data()
    # The guard itself must not have created the DB as a side effect.
    assert not missing.exists()


def test_write_path_still_creates_db_on_first_write(tmp_path, monkeypatch):
    """append_transaction keeps auto-creating the DB (write-path behavior)."""
    db_path = tmp_path / "fresh.db"
    monkeypatch.setattr(settings, "SQLITE_DB_PATH", db_path)
    storage_facade.append_transaction(_txn())
    assert db_path.exists()
    assert len(storage_facade.load_transactions()) == 1
