"""
test_web_bulk.py — route-level tests for bulk select/delete/edit on the
Transactions Ledger page: bulk-confirm modal, bulk-delete, bulk-edit, and
merchant-map learning on single-row edit.
"""

import re

import pytest

import settings
import sqlite_ops

PASSWORD = "hunter2"


def _txn(**overrides) -> dict:
    row = {
        "date": "2024-06-15", "year": 2024, "month": "Jun", "value": 50.0,
        "currency": "PLN", "value_base": 50.0, "rate_used": 1.0,
        "type": "Expense", "category": "Groceries", "person": "Alice",
        "description": "test item", "is_recurring": False, "is_done": True,
        "source": "test",
    }
    row.update(overrides)
    return row


def _insert_txn(conn, **overrides) -> int:
    return sqlite_ops.insert_transaction(conn, _txn(**overrides))


@pytest.fixture()
def client(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "WEB_PASSWORD", PASSWORD)
    monkeypatch.setattr(settings, "WEB_SESSION_SECRET", "s3cret")
    monkeypatch.setattr(settings, "SQLITE_DB_PATH", tmp_path / "bulk.db")
    conn = sqlite_ops.init_db(settings.SQLITE_DB_PATH)
    sqlite_ops.upsert_person(conn, "Alice")
    sqlite_ops.upsert_person(conn, "Bob")
    sqlite_ops.upsert_category(conn, "Groceries")
    sqlite_ops.upsert_category(conn, "Fun")
    sqlite_ops.upsert_rate(conn, "USD", 4.0)
    conn.close()

    from fastapi.testclient import TestClient
    from web.app import create_app
    c = TestClient(create_app())
    c.post("/login", data={"password": PASSWORD}, follow_redirects=False)
    return c


def _get_lock(tmp_path, txn_id: int) -> str:
    import sqlite3
    conn = sqlite3.connect(str(tmp_path / "bulk.db"))
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT date_modified_utc FROM transactions WHERE id = ?",
                       (txn_id,)).fetchone()
    conn.close()
    return row["date_modified_utc"] or "" if row else ""


# ── bulk-confirm modal ────────────────────────────────────────────────────────

def test_bulk_confirm_renders_modal_with_count(client, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "SQLITE_DB_PATH", tmp_path / "bulk.db")
    conn = sqlite_ops.init_db(settings.SQLITE_DB_PATH)
    id1 = _insert_txn(conn, description="row A")
    id2 = _insert_txn(conn, description="row B")
    conn.close()
    tok1 = _get_lock(tmp_path, id1)
    tok2 = _get_lock(tmp_path, id2)

    resp = client.get(
        f"/transactions/bulk-confirm?ids[]={id1}&lock_tokens[]={tok1}"
        f"&ids[]={id2}&lock_tokens[]={tok2}")
    assert resp.status_code == 200
    assert "Delete 2 transaction" in resp.text
    assert f'name="ids[]" value="{id1}"' in resp.text
    assert f'name="ids[]" value="{id2}"' in resp.text


def test_bulk_confirm_single_uses_singular(client, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "SQLITE_DB_PATH", tmp_path / "bulk.db")
    conn = sqlite_ops.init_db(settings.SQLITE_DB_PATH)
    id1 = _insert_txn(conn)
    conn.close()
    tok = _get_lock(tmp_path, id1)

    resp = client.get(f"/transactions/bulk-confirm?ids[]={id1}&lock_tokens[]={tok}")
    assert "Delete 1 transaction" in resp.text
    assert "transactions" not in resp.text.split("Delete 1 transaction")[1][:30]


# ── bulk delete ───────────────────────────────────────────────────────────────

def test_bulk_delete_valid_tokens_returns_hidden_divs(client, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "SQLITE_DB_PATH", tmp_path / "bulk.db")
    conn = sqlite_ops.init_db(settings.SQLITE_DB_PATH)
    id1 = _insert_txn(conn, description="delete me")
    conn.close()
    tok = _get_lock(tmp_path, id1)

    resp = client.post("/transactions/bulk-delete",
                       data={"ids[]": [str(id1)], "lock_tokens[]": [tok]})
    assert resp.status_code == 200
    assert f'id="txn-{id1}"' in resp.text
    assert "display:none" in resp.text
    assert "hx-swap-oob" in resp.text


def test_bulk_delete_stale_token_returns_conflict_div(client, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "SQLITE_DB_PATH", tmp_path / "bulk.db")
    conn = sqlite_ops.init_db(settings.SQLITE_DB_PATH)
    id1 = _insert_txn(conn)
    conn.close()

    resp = client.post("/transactions/bulk-delete",
                       data={"ids[]": [str(id1)], "lock_tokens[]": ["stale-token"]})
    assert resp.status_code == 200
    assert f'id="txn-{id1}"' in resp.text
    assert "txn--error" in resp.text
    assert "modified by another writer" in resp.text


def test_bulk_delete_missing_row_returns_not_found_div(client, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "SQLITE_DB_PATH", tmp_path / "bulk.db")
    sqlite_ops.init_db(settings.SQLITE_DB_PATH).close()

    resp = client.post("/transactions/bulk-delete",
                       data={"ids[]": ["99999"], "lock_tokens[]": ["tok"]})
    assert resp.status_code == 200
    assert 'id="txn-99999"' in resp.text
    assert "txn--error" in resp.text


# ── bulk edit ─────────────────────────────────────────────────────────────────

def test_bulk_edit_valid_updates_row_and_returns_oob(client, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "SQLITE_DB_PATH", tmp_path / "bulk.db")
    conn = sqlite_ops.init_db(settings.SQLITE_DB_PATH)
    id1 = _insert_txn(conn, category="Groceries")
    conn.close()
    tok = _get_lock(tmp_path, id1)

    resp = client.post("/transactions/bulk-edit", data={
        "ids[]": [str(id1)], "lock_tokens[]": [tok],
        "bulk_field": "category", "bulk_value": "Fun",
    })
    assert resp.status_code == 200
    assert f'id="txn-{id1}"' in resp.text
    assert "hx-swap-oob" in resp.text
    # Confirm the DB was actually updated.
    import sqlite3
    conn2 = sqlite3.connect(str(tmp_path / "bulk.db"))
    conn2.row_factory = sqlite3.Row
    row = conn2.execute("SELECT category FROM transactions WHERE id = ?", (id1,)).fetchone()
    conn2.close()
    assert row["category"] == "Fun"


def test_bulk_edit_invalid_field_returns_400(client, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "SQLITE_DB_PATH", tmp_path / "bulk.db")
    sqlite_ops.init_db(settings.SQLITE_DB_PATH).close()

    resp = client.post("/transactions/bulk-edit", data={
        "ids[]": ["1"], "lock_tokens[]": ["tok"],
        "bulk_field": "value", "bulk_value": "9999",
    })
    assert resp.status_code == 400


def test_bulk_edit_invalid_value_returns_422(client, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "SQLITE_DB_PATH", tmp_path / "bulk.db")
    sqlite_ops.init_db(settings.SQLITE_DB_PATH).close()

    resp = client.post("/transactions/bulk-edit", data={
        "ids[]": ["1"], "lock_tokens[]": ["tok"],
        "bulk_field": "category", "bulk_value": "NonExistentCategory",
    })
    assert resp.status_code == 422


# ── merchant map learning on single-row edit ──────────────────────────────────

def test_txn_edit_calls_merchant_map_learn(client, monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "SQLITE_DB_PATH", tmp_path / "bulk.db")
    conn = sqlite_ops.init_db(settings.SQLITE_DB_PATH)
    txn_id = _insert_txn(conn, description="supermarket visit", category="Groceries",
                         type="Expense")
    conn.close()
    tok = _get_lock(tmp_path, txn_id)

    learned = []

    import merchant_map as _mm
    monkeypatch.setattr(_mm, "learn_from_row", lambda row: learned.append(row))

    resp = client.post(f"/transactions/{txn_id}/edit", data={
        "lock_token": tok,
        "date": "2024-06-15",
        "amount": "50.00",
        "type": "Expense",
        "category": "Fun",
        "person": "Alice",
        "description": "supermarket visit",
        "currency": "",
    })
    assert resp.status_code == 200
    assert len(learned) == 1
    assert learned[0]["category"] == "Fun"
    assert learned[0]["description"] == "supermarket visit"
