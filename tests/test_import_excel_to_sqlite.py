"""Tests for scripts/import_excel_to_sqlite.py — idempotent Excel → SQLite."""

import datetime

import pytest

import sqlite_ops
from file_storage import append_transactions_batch
from models import Transaction

from scripts.import_excel_to_sqlite import run_import


@pytest.fixture()
def populated_excel(excel_path):
    """Blank fixture workbook + two known transactions (one foreign-currency)."""
    append_transactions_batch([
        Transaction(date=datetime.date(2024, 6, 15), value=150.50, currency="PLN",
                    transaction_type="Expense", category="Groceries",
                    person="Alice", description="weekly shop"),
        Transaction(date=datetime.date(2024, 7, 1), value=100.00, currency="USD",
                    transaction_type="Income", category="Salary",
                    person="Bob", description="contract"),
    ])
    return excel_path


def _rates_from_lists(excel_path):
    from excel_schema import load_currency_rates_from_path
    return load_currency_rates_from_path(excel_path)


def test_import_row_count_and_value_base(populated_excel, tmp_path):
    db = tmp_path / "import.db"
    stats = run_import(db_path=db, dry_run=False)
    assert stats == {"total": 2, "inserted": 2, "skipped": 0}

    conn = sqlite_ops.init_db(db)
    try:
        rows = sqlite_ops.list_transactions(conn)
        assert len(rows) == 2
        by_ccy = {r["currency"]: r for r in rows}
        assert by_ccy["PLN"]["value_base"] == pytest.approx(150.50)
        assert by_ccy["PLN"]["rate_used"] == 1.0
        usd_rate = _rates_from_lists(populated_excel).get("USD", 1.0)
        assert by_ccy["USD"]["value_base"] == pytest.approx(100.0 * usd_rate)
        assert by_ccy["USD"]["rate_used"] == pytest.approx(usd_rate)
        # Rates and reference lists were imported too
        assert sqlite_ops.load_rates_dict(conn)
        assert conn.execute("SELECT COUNT(*) FROM sync_log").fetchone()[0] == 1
    finally:
        conn.close()


def test_second_run_skips_duplicates(populated_excel, tmp_path):
    db = tmp_path / "import.db"
    first = run_import(db_path=db, dry_run=False)
    assert first["inserted"] == 2
    second = run_import(db_path=db, dry_run=False)
    assert second["inserted"] == 0
    assert second["skipped"] == 2

    conn = sqlite_ops.init_db(db)
    try:
        assert len(sqlite_ops.list_transactions(conn)) == 2
    finally:
        conn.close()


def test_export_reimport_round_trip_adds_nothing(populated_excel, tmp_path, monkeypatch):
    """Import → export → re-import must be a no-op (idempotent round trip)."""
    import file_storage
    from excel_export import generate_excel_from_sqlite

    # Include a formula-injection description: written to Excel with a leading
    # apostrophe guard, it must still round-trip to the same content_hash.
    append_transactions_batch([
        Transaction(date=datetime.date(2024, 8, 2), value=9.99, currency="PLN",
                    transaction_type="Expense", category="Groceries",
                    person="Alice", description="=SUM(A1:A9) sneaky"),
    ])

    db = tmp_path / "roundtrip.db"
    first = run_import(db_path=db, dry_run=False)
    assert first["inserted"] == 3

    exported = tmp_path / "exported.xlsx"
    generate_excel_from_sqlite(db, populated_excel, exported)

    # Point the importer's reader at the freshly exported workbook.
    monkeypatch.setattr(file_storage, "LOCAL_XLSX_PATH", exported)
    second = run_import(db_path=db, dry_run=False)
    assert second["inserted"] == 0, "re-importing an export must not create duplicates"

    conn = sqlite_ops.init_db(db)
    try:
        rows = sqlite_ops.list_transactions(conn)
        assert len(rows) == 3
        # The stored description carries no injection-guard apostrophe.
        descs = {r["description"] for r in rows}
        assert "=SUM(A1:A9) sneaky" in descs
    finally:
        conn.close()


def test_dry_run_writes_nothing(populated_excel, tmp_path):
    db = tmp_path / "import.db"
    stats = run_import(db_path=db, dry_run=True)
    assert stats == {"total": 2, "inserted": 2, "skipped": 0}
    conn = sqlite_ops.init_db(db)
    try:
        assert sqlite_ops.list_transactions(conn) == []
    finally:
        conn.close()


def test_dry_run_reports_skips_after_real_import(populated_excel, tmp_path):
    db = tmp_path / "import.db"
    run_import(db_path=db, dry_run=False)
    stats = run_import(db_path=db, dry_run=True)
    assert stats["inserted"] == 0
    assert stats["skipped"] == 2
