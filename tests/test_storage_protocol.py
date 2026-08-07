"""Tests for storage_protocol.StorageBackend conformance and sqlite_types enums."""

import datetime

import pytest

import settings
import sqlite_ops
import storage_facade
from sqlite_types import (
    SyncDirection,
    SyncStatus,
    TransactionRow,
    TransactionSource,
    TransactionType,
)
from storage_protocol import StorageBackend


def test_storage_facade_satisfies_storage_backend_protocol():
    assert isinstance(storage_facade, StorageBackend)


def test_incomplete_backend_fails_protocol_check():
    class Partial:
        def append_transaction(self, transaction):
            pass

    assert not isinstance(Partial(), StorageBackend)


def test_transaction_type_matches_reference_data_value_set():
    assert [t.value for t in TransactionType] == ["Expense", "Income", "Savings"]


def test_enums_compare_equal_to_plain_strings():
    assert TransactionSource.BOT == "bot"
    assert TransactionSource.EXCEL_IMPORT == "excel_import"
    assert SyncDirection.IMPORT == "import"
    assert SyncDirection.EXPORT == "export"
    assert SyncStatus.OK == "ok"
    assert SyncStatus.ERROR == "error"


@pytest.fixture()
def db(tmp_path):
    conn = sqlite_ops.init_db(tmp_path / "types.db")
    yield conn
    conn.close()


def test_transaction_row_insert_roundtrip(db):
    rid = sqlite_ops.insert_transaction(db, TransactionRow(
        date="2024-06-15", year=2024, month="Jun", value=150.5,
        currency=settings.DISPLAY_CURRENCY, value_base=150.5, rate_used=1.0,
        type=TransactionType.EXPENSE, category="Groceries", person="Alice",
        description="weekly shop", is_recurring=False, is_done=True,
    ))
    row = sqlite_ops.list_transactions(db)[0]
    assert row["id"] == rid
    # sqlite3 returns plain str; StrEnum members compare equal to it
    assert row["source"] == TransactionSource.BOT
    assert row["type"] == TransactionType.EXPENSE
    assert isinstance(row["source"], str)


def test_log_sync_accepts_enums(db):
    sqlite_ops.log_sync(db, SyncDirection.EXPORT, SyncStatus.ERROR, "boom")
    row = db.execute(f"SELECT * FROM {sqlite_ops.TABLE_SYNC_LOG}").fetchone()
    assert row["direction"] == SyncDirection.EXPORT
    assert row["status"] == SyncStatus.ERROR


def test_facade_append_defaults_source_to_bot(tmp_path, monkeypatch):
    db_path = tmp_path / "facade_source.db"
    monkeypatch.setattr(settings, "SQLITE_DB_PATH", db_path)
    from models import Transaction
    storage_facade.append_transaction(Transaction(
        date=datetime.date(2024, 6, 15), value=10.0,
        currency=settings.DISPLAY_CURRENCY, transaction_type="Expense",
        category="Groceries", person="Alice", description="x"))
    conn = sqlite_ops.init_db(db_path)
    try:
        assert sqlite_ops.list_transactions(conn)[0]["source"] == TransactionSource.BOT
    finally:
        conn.close()
