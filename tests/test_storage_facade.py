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


# ── append_transactions_batch (S1 Phase 2, Unit R4) ──────────────────────────

def test_batch_append_inserts_all_rows(sqlite_db):
    txns = [
        _txn(description="row one"),
        _txn(value=42.0, currency="USD", description="row two"),
        _txn(value=7.5, description="row three"),
    ]
    storage_facade.append_transactions_batch(txns)
    df = storage_facade.load_transactions()
    assert len(df) == 3
    usd_row = df[df["Description"] == "row two"].iloc[0]
    assert usd_row["Value (base)"] == 168.0  # 42 * 4.0


def test_batch_append_empty_list_is_noop(sqlite_db):
    storage_facade.append_transactions_batch([])
    assert storage_facade.load_transactions().empty


def test_batch_append_is_all_or_nothing(sqlite_db):
    """A failure mid-batch must roll back every row (mirrors the Excel batch
    write, which saves the workbook once at the end — a mid-loop exception
    persists nothing)."""
    txns = [
        _txn(description="good row"),
        {"value": None, "currency": "USD", "date": datetime.date(2024, 6, 15),
         "year": 2024, "month": "Jun", "type": "Expense",
         "category": "Groceries", "person": "Alice",
         "description": "bad row — value None"},
        _txn(description="never reached"),
    ]
    with pytest.raises(TypeError):
        storage_facade.append_transactions_batch(txns)
    assert storage_facade.load_transactions().empty


def test_batch_append_unknown_currency_logged_after_commit(sqlite_db):
    storage_facade.append_transactions_batch(
        [_txn(value=10.0, currency="XXX", description="typo currency")])
    df = storage_facade.load_transactions()
    assert len(df) == 1
    assert df.iloc[0]["Value (base)"] == 10.0  # rate 1.0 fallback
    conn = sqlite_ops.init_db(sqlite_db)
    detail = conn.execute(
        f"SELECT detail FROM {sqlite_ops.TABLE_SYNC_LOG}").fetchone()["detail"]
    conn.close()
    assert "XXX" in detail


def test_bulk_conv_reference_reads_use_facade(sqlite_db):
    """bulk_conv's load_reference_data must be the facade's, and the facade
    must return the same category/person lists the handlers key on."""
    import handlers.bulk_conv as bulk_conv
    assert bulk_conv.load_reference_data is storage_facade.load_reference_data
    conn = sqlite_ops.init_db(sqlite_db)
    sqlite_ops.upsert_category(conn, "Groceries", 1200.0)
    sqlite_ops.upsert_person(conn, "Alice")
    conn.close()
    ref = bulk_conv.load_reference_data()
    assert ref["categories"] == ["Groceries"]
    assert ref["persons"] == ["Alice"]


# ── load_dedup_evidence (SQLite twin of data.load_dedup_evidence) ─────────────

def test_bulk_conv_dedup_evidence_uses_facade(sqlite_db):
    """bulk_conv must read dedup evidence from the facade (SQLite), not data.py
    (Excel) — otherwise its own SQLite saves never feed its own dedup scan."""
    import handlers.bulk_conv as bulk_conv
    assert bulk_conv.load_dedup_evidence is storage_facade.load_dedup_evidence


def test_load_dedup_evidence_shape_and_multiset_counts(sqlite_db):
    from validators import make_dedup_key, make_loose_dedup_key
    # Two rows with the same date|value|ccy|description (different person, so
    # distinct content_hash) + one row differing only in description.
    storage_facade.append_transactions_batch([
        _txn(), _txn(person="Bob"), _txn(description="other shop"),
    ])
    ev = storage_facade.load_dedup_evidence(
        datetime.date(2024, 6, 1), datetime.date(2024, 6, 30))
    strict_key = make_dedup_key(
        "2024-06-15", 150.50, settings.DISPLAY_CURRENCY, "weekly shop")
    loose_key = make_loose_dedup_key("2024-06-15", 150.50, settings.DISPLAY_CURRENCY)
    assert len(ev["strict"][strict_key]) == 2          # multiset, count-aware
    assert len(ev["loose"][loose_key]) == 3            # description ignored
    assert ev["strict"][strict_key][0] == ("2024-06-15", "weekly shop")


def test_load_dedup_evidence_sees_own_batch_writes(sqlite_db):
    """The re-upload scenario: rows saved via append_transactions_batch must
    appear in the very next dedup evidence read."""
    from validators import make_dedup_key
    assert storage_facade.load_dedup_evidence() == {"strict": {}, "loose": {}}
    storage_facade.append_transactions_batch([_txn()])
    ev = storage_facade.load_dedup_evidence()
    key = make_dedup_key("2024-06-15", 150.50, settings.DISPLAY_CURRENCY, "weekly shop")
    assert len(ev["strict"][key]) == 1


def test_load_dedup_evidence_date_range_filter(sqlite_db):
    storage_facade.append_transactions_batch([
        _txn(),
        _txn(date=datetime.date(2024, 7, 1), month="Jul", description="july row"),
    ])
    ev = storage_facade.load_dedup_evidence(
        datetime.date(2024, 6, 1), datetime.date(2024, 6, 30))
    all_descs = [d for entries in ev["strict"].values() for _, d in entries]
    assert all_descs == ["weekly shop"]                # July row filtered out
    # Boundary day is inclusive.
    ev2 = storage_facade.load_dedup_evidence(
        datetime.date(2024, 7, 1), datetime.date(2024, 7, 1))
    assert [d for e in ev2["strict"].values() for _, d in e] == ["july row"]


def test_load_dedup_evidence_read_failure_returns_empty(sqlite_db, monkeypatch):
    """Dedup never blocks an import — any read failure yields empty evidence."""
    monkeypatch.setattr(storage_facade, "_conn",
                        lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    assert storage_facade.load_dedup_evidence() == {"strict": {}, "loose": {}}


# ── within-batch duplicate content_hash: silent skip, never data loss ─────────

def test_duplicate_content_hash_within_batch_skips_only_exact_dup(sqlite_db):
    conn = sqlite_ops.init_db(sqlite_db)
    row = dict(
        date="2024-06-15", year=2024, month="Jun", value=10.0,
        currency=settings.DISPLAY_CURRENCY, value_base=10.0, rate_used=1.0,
        type="Expense", category="Groceries", person="Alice",
        description="coffee", is_recurring=0, is_done=1,
        date_modified_utc="2024-06-15T00:00:00+00:00", content_hash="same-hash",
    )
    id1 = sqlite_ops.insert_transaction(conn, dict(row), commit=False)
    id2 = sqlite_ops.insert_transaction(conn, dict(row), commit=False)  # exact dup
    id3 = sqlite_ops.insert_transaction(
        conn, dict(row, description="tea", content_hash="other-hash"), commit=False)
    conn.commit()
    rows = sqlite_ops.list_transactions(conn)
    conn.close()
    assert id2 == id1                       # dup resolved to the existing row id
    assert id3 != id1
    assert len(rows) == 2                   # only the exact duplicate was skipped
    assert sorted(r["description"] for r in rows) == ["coffee", "tea"]
