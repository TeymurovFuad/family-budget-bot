"""
test_s3_web_write_path.py — tests for S3 web write path.

Covers:
  - validate_web_transaction_form: valid input, future date, bad amount
  - update_web_transaction: correct token succeeds, wrong token raises ConflictError
  - delete_web_transaction: correct token deletes, wrong token raises ConflictError
  - POST /transactions/new: valid → 200 + HX-Trigger; invalid → 422
  - POST /transactions/{id}/edit: success → 200; conflict → 409
  - POST /transactions/{id}/delete: success → 200 empty div
"""

import asyncio
import re
from datetime import date, datetime, timezone

import pytest

import settings
import sqlite_ops
from storage_facade import ConflictError, add_web_transaction, delete_web_transaction, update_web_transaction
from validators import validate_web_transaction_form

PASSWORD = "hunter2"

# ── validate_web_transaction_form ─────────────────────────────────────────────


def test_validate_valid_input():
    data = {
        "date": "2024-06-15",
        "amount": "150.50",
        "type": "Expense",
        "category": "Groceries",
        "person": "Alice",
        "description": "weekly shop",
    }
    cleaned, errors = validate_web_transaction_form(data)
    assert errors == {}
    assert cleaned["value"] == 150.50
    assert cleaned["date"] == "2024-06-15"
    assert cleaned["type"] == "Expense"
    assert cleaned["category"] == "Groceries"


def test_validate_future_date_rejected():
    future = (datetime.now(timezone.utc).date().replace(year=date.today().year + 1)).isoformat()
    data = {"date": future, "amount": "10", "type": "Expense"}
    cleaned, errors = validate_web_transaction_form(data)
    assert "date" in errors
    assert "future" in errors["date"].lower()


def test_validate_bad_amount():
    data = {"date": "2024-06-15", "amount": "not_a_number", "type": "Expense"}
    cleaned, errors = validate_web_transaction_form(data)
    assert "amount" in errors


def test_validate_missing_date():
    data = {"date": "", "amount": "10", "type": "Expense"}
    cleaned, errors = validate_web_transaction_form(data)
    assert "date" in errors


def test_validate_missing_type():
    data = {"date": "2024-06-15", "amount": "10", "type": ""}
    cleaned, errors = validate_web_transaction_form(data)
    assert "type" in errors


def test_validate_invalid_type():
    data = {"date": "2024-06-15", "amount": "10", "type": "Wrong"}
    cleaned, errors = validate_web_transaction_form(data)
    assert "type" in errors


def test_validate_optional_fields_empty():
    data = {"date": "2024-06-15", "amount": "10", "type": "Income"}
    cleaned, errors = validate_web_transaction_form(data)
    assert errors == {}
    assert cleaned["category"] is None
    assert cleaned["person"] is None
    assert cleaned["description"] is None


# ── update_web_transaction ────────────────────────────────────────────────────


def _insert_row(conn, date_str="2024-06-15"):
    from sqlite_types import TransactionRow
    row = TransactionRow(
        date=date_str, year=2024, month="Jun", value=100.0,
        currency="PLN", value_base=100.0, rate_used=1.0,
        type="Expense", category="Groceries", person="Alice",
        description="test row", is_recurring=False, is_done=True,
        source="web",
        date_modified_utc="2024-06-15T10:00:00+00:00",
    )
    return sqlite_ops.insert_transaction(conn, row)


def _get_token(conn, row_id: int) -> str:
    row = conn.execute(
        f"SELECT date_modified_utc FROM {sqlite_ops.TABLE_TRANSACTIONS} WHERE id = ?",
        (row_id,)).fetchone()
    return row["date_modified_utc"] or ""


def test_update_correct_token_succeeds(tmp_path, monkeypatch):
    db = tmp_path / "u.db"
    monkeypatch.setattr(settings, "SQLITE_DB_PATH", db)
    conn = sqlite_ops.init_db(db)
    sqlite_ops.upsert_rate(conn, "PLN", 1.0)
    row_id = _insert_row(conn)
    token = _get_token(conn, row_id)
    conn.close()

    asyncio.run(
        update_web_transaction(row_id, token, {"description": "updated"}))

    conn2 = sqlite_ops.init_db(db)
    row = conn2.execute(
        f"SELECT description FROM {sqlite_ops.TABLE_TRANSACTIONS} WHERE id = ?",
        (row_id,)).fetchone()
    conn2.close()
    assert row["description"] == "updated"


def test_update_wrong_token_raises_conflict(tmp_path, monkeypatch):
    db = tmp_path / "u2.db"
    monkeypatch.setattr(settings, "SQLITE_DB_PATH", db)
    conn = sqlite_ops.init_db(db)
    sqlite_ops.upsert_rate(conn, "PLN", 1.0)
    row_id = _insert_row(conn)
    conn.close()

    with pytest.raises(ConflictError):
        asyncio.run(
            update_web_transaction(row_id, "wrong-token", {"description": "bad"}))


# ── delete_web_transaction ────────────────────────────────────────────────────


def test_delete_correct_token_removes_row(tmp_path, monkeypatch):
    db = tmp_path / "d.db"
    monkeypatch.setattr(settings, "SQLITE_DB_PATH", db)
    conn = sqlite_ops.init_db(db)
    sqlite_ops.upsert_rate(conn, "PLN", 1.0)
    row_id = _insert_row(conn)
    token = _get_token(conn, row_id)
    conn.close()

    asyncio.run(
        delete_web_transaction(row_id, token))

    conn2 = sqlite_ops.init_db(db)
    row = conn2.execute(
        f"SELECT id FROM {sqlite_ops.TABLE_TRANSACTIONS} WHERE id = ?",
        (row_id,)).fetchone()
    conn2.close()
    assert row is None


def test_delete_wrong_token_raises_conflict(tmp_path, monkeypatch):
    db = tmp_path / "d2.db"
    monkeypatch.setattr(settings, "SQLITE_DB_PATH", db)
    conn = sqlite_ops.init_db(db)
    sqlite_ops.upsert_rate(conn, "PLN", 1.0)
    row_id = _insert_row(conn)
    conn.close()

    with pytest.raises(ConflictError):
        asyncio.run(
            delete_web_transaction(row_id, "wrong-token"))


# ── Route tests ───────────────────────────────────────────────────────────────


def _make_client(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "WEB_PASSWORD", PASSWORD)
    monkeypatch.setattr(settings, "WEB_SESSION_SECRET", "s3cret")
    db = tmp_path / "route.db"
    monkeypatch.setattr(settings, "SQLITE_DB_PATH", db)
    conn = sqlite_ops.init_db(db)
    sqlite_ops.upsert_person(conn, "Alice")
    sqlite_ops.upsert_category(conn, "Groceries")
    sqlite_ops.upsert_rate(conn, "PLN", 1.0)
    conn.close()

    from fastapi.testclient import TestClient
    from web.app import create_app
    c = TestClient(create_app())
    c.post("/login", data={"password": PASSWORD}, follow_redirects=False)
    return c, db


def test_post_new_valid_returns_200_hx_trigger(monkeypatch, tmp_path):
    client, db = _make_client(monkeypatch, tmp_path)
    resp = client.post("/transactions/new", data={
        "date": "2024-06-15",
        "amount": "50.00",
        "type": "Expense",
        "category": "Groceries",
        "person": "Alice",
        "description": "test",
    })
    assert resp.status_code == 200
    assert "HX-Trigger" in resp.headers
    assert "txnSaved" in resp.headers["HX-Trigger"]


def test_post_new_invalid_returns_422(monkeypatch, tmp_path):
    client, db = _make_client(monkeypatch, tmp_path)
    resp = client.post("/transactions/new", data={
        "date": "",           # missing
        "amount": "abc",      # bad
        "type": "Expense",
    })
    assert resp.status_code == 422


def test_post_edit_success_returns_row_fragment(monkeypatch, tmp_path):
    client, db = _make_client(monkeypatch, tmp_path)
    # Insert a row directly
    conn = sqlite_ops.init_db(db)
    from sqlite_types import TransactionRow
    row = TransactionRow(
        date="2024-06-15", year=2024, month="Jun", value=100.0,
        currency="PLN", value_base=100.0, rate_used=1.0,
        type="Expense", category="Groceries", person="Alice",
        description="orig", is_recurring=False, is_done=True,
        source="web", date_modified_utc="2024-06-15T10:00:00+00:00",
    )
    row_id = sqlite_ops.insert_transaction(conn, row)
    token = conn.execute(
        f"SELECT date_modified_utc FROM {sqlite_ops.TABLE_TRANSACTIONS} WHERE id=?",
        (row_id,)).fetchone()["date_modified_utc"]
    conn.close()

    resp = client.post(f"/transactions/{row_id}/edit", data={
        "lock_token": token,
        "date": "2024-06-15",
        "amount": "200.00",
        "type": "Expense",
        "category": "Groceries",
        "person": "Alice",
        "description": "updated",
    })
    assert resp.status_code == 200
    assert f'id="txn-{row_id}"' in resp.text


def test_post_edit_conflict_returns_409(monkeypatch, tmp_path):
    client, db = _make_client(monkeypatch, tmp_path)
    conn = sqlite_ops.init_db(db)
    from sqlite_types import TransactionRow
    row = TransactionRow(
        date="2024-06-15", year=2024, month="Jun", value=100.0,
        currency="PLN", value_base=100.0, rate_used=1.0,
        type="Expense", category="Groceries", person="Alice",
        description="orig", is_recurring=False, is_done=True,
        source="web", date_modified_utc="2024-06-15T10:00:00+00:00",
    )
    row_id = sqlite_ops.insert_transaction(conn, row)
    conn.close()

    resp = client.post(f"/transactions/{row_id}/edit", data={
        "lock_token": "stale-token",
        "date": "2024-06-15",
        "amount": "200.00",
        "type": "Expense",
        "category": "Groceries",
        "person": "Alice",
        "description": "conflict",
    })
    assert resp.status_code == 409


def test_post_delete_success_returns_empty_div(monkeypatch, tmp_path):
    client, db = _make_client(monkeypatch, tmp_path)
    conn = sqlite_ops.init_db(db)
    from sqlite_types import TransactionRow
    row = TransactionRow(
        date="2024-06-15", year=2024, month="Jun", value=100.0,
        currency="PLN", value_base=100.0, rate_used=1.0,
        type="Expense", category="Groceries", person="Alice",
        description="to delete", is_recurring=False, is_done=True,
        source="web", date_modified_utc="2024-06-15T10:00:00+00:00",
    )
    row_id = sqlite_ops.insert_transaction(conn, row)
    token = conn.execute(
        f"SELECT date_modified_utc FROM {sqlite_ops.TABLE_TRANSACTIONS} WHERE id=?",
        (row_id,)).fetchone()["date_modified_utc"]
    conn.close()

    resp = client.post(f"/transactions/{row_id}/delete", data={"lock_token": token})
    assert resp.status_code == 200
    assert f'id="txn-{row_id}"' in resp.text
    assert 'display:none' in resp.text


def test_post_delete_conflict_returns_409(monkeypatch, tmp_path):
    client, db = _make_client(monkeypatch, tmp_path)
    import sqlite3
    conn = sqlite_ops.init_db(db)
    from sqlite_types import TransactionRow
    row = TransactionRow(
        date="2024-06-15", year=2024, month="Jun", value=100.0,
        currency="PLN", value_base=100.0, rate_used=1.0,
        type="Expense", category="Groceries", person="Alice",
        description="orig", is_recurring=False, is_done=True,
        source="web", date_modified_utc="2024-06-15T10:00:00+00:00",
    )
    row_id = sqlite_ops.insert_transaction(conn, row)
    token = conn.execute(
        "SELECT date_modified_utc FROM transactions WHERE id=?",
        (row_id,)).fetchone()["date_modified_utc"]
    conn.close()

    conn2 = sqlite3.connect(str(db))
    conn2.execute(
        "UPDATE transactions SET date_modified_utc = ? WHERE id = ?",
        ("2000-01-01T00:00:00Z", row_id)
    )
    conn2.commit()
    conn2.close()

    resp = client.post(f"/transactions/{row_id}/delete", data={"lock_token": token})
    assert resp.status_code == 409
