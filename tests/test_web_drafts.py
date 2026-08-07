"""test_web_drafts.py - route tests for Drafts web UI flows."""

from unittest.mock import patch

import settings
import sqlite_ops

from bulk_drafts import load_user_draft, save_user_draft

PASSWORD = "hunter2"


def _draft_row(**overrides) -> dict:
    row = {
        "date": "2024-06-15",
        "value": "10",
        "currency": "PLN",
        "type": "Expense",
        "category": "Groceries",
        "person": "",
        "description": "test row",
    }
    row.update(overrides)
    return row


def _seed_reference_db(path):
    conn = sqlite_ops.init_db(path)
    sqlite_ops.upsert_person(conn, "Alice")
    sqlite_ops.upsert_person(conn, "Bob")
    sqlite_ops.upsert_category(conn, "Groceries")
    sqlite_ops.upsert_category(conn, "Transport")
    sqlite_ops.upsert_rate(conn, "PLN", 1.0)
    sqlite_ops.upsert_rate(conn, "USD", 4.0)
    conn.close()


def _client(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "WEB_PASSWORD", PASSWORD)
    monkeypatch.setattr(settings, "WEB_SESSION_SECRET", "s3cret")
    monkeypatch.setattr(settings, "SQLITE_DB_PATH", tmp_path / "web-drafts.db")
    _seed_reference_db(settings.SQLITE_DB_PATH)

    from fastapi.testclient import TestClient
    from web.app import create_app

    client = TestClient(create_app())
    client.post("/login", data={"password": PASSWORD}, follow_redirects=False)
    return client


def test_drafts_page_renders_pending_rows(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    save_user_draft(1001, [_draft_row()])

    resp = client.get("/drafts")
    assert resp.status_code == 200
    assert "Drafts" in resp.text
    assert "User 1001" in resp.text


def test_bulk_set_field_revalidates_and_clears_invalid(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    uid = 1002
    save_user_draft(uid, [_draft_row(category="WrongCat", invalid="Unknown category 'WrongCat'.")])

    resp = client.post(f"/drafts/{uid}/bulk-update", data={
        "action": "set_field",
        "row_idx": ["0"],
        "bulk_field": "category",
        "bulk_value": "Transport",
    }, follow_redirects=False)
    assert resp.status_code == 303

    rows = load_user_draft(uid)
    assert rows[0]["category"] == "Transport"
    assert "invalid" not in rows[0]


def test_single_row_update_revalidates(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    uid = 1003
    save_user_draft(uid, [_draft_row(value="oops", invalid="Transaction value must be a positive number.")])

    resp = client.post(f"/drafts/{uid}/row/0/update", data={
        "date": "2024-06-15",
        "value": "22.40",
        "currency": "PLN",
        "type": "Expense",
        "category": "Groceries",
        "person": "",
        "description": "fixed",
    }, follow_redirects=False)
    assert resp.status_code == 303

    rows = load_user_draft(uid)
    assert rows[0]["value"] == 22.4
    assert rows[0]["description"] == "fixed"
    assert "invalid" not in rows[0]


def test_single_row_toggle_drop(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    uid = 1004
    save_user_draft(uid, [_draft_row()])

    resp = client.post(f"/drafts/{uid}/row/0/toggle-drop", follow_redirects=False)
    assert resp.status_code == 303
    assert load_user_draft(uid)[0].get("dropped") is True

    resp2 = client.post(f"/drafts/{uid}/row/0/toggle-drop", follow_redirects=False)
    assert resp2.status_code == 303
    assert "dropped" not in load_user_draft(uid)[0]


def test_archive_moves_draft(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    uid = 1005
    save_user_draft(uid, [_draft_row()])

    resp = client.post(f"/drafts/{uid}/archive", follow_redirects=False)
    assert resp.status_code == 303
    assert load_user_draft(uid) == []


def test_bulk_reanalyze_preview_and_apply(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    uid = 1006
    save_user_draft(uid, [_draft_row(description="lidl"), _draft_row(description="fuel")])

    ai_row = {
        "date": "2024-06-15",
        "value": 10.0,
        "currency": "PLN",
        "type": "Expense",
        "category": "Transport",
        "description": "fuel",
    }
    with patch("web.routes.drafts.parse_quick", return_value=ai_row):
        preview_resp = client.post(
            f"/drafts/{uid}/bulk-update",
            data={
                "action": "preview_ai",
                "row_idx": ["0"],
                "ai_instruction": "Map unknown categories to nearest",
            },
            follow_redirects=False,
        )
    assert preview_resp.status_code == 303

    rows = load_user_draft(uid)
    assert "_ai_preview" in rows[0]
    assert rows[0]["_ai_preview"]["status"] == "changed"

    apply_resp = client.post(
        f"/drafts/{uid}/bulk-update",
        data={
            "action": "apply_ai_preview",
            "row_idx": ["0"],
        },
        follow_redirects=False,
    )
    assert apply_resp.status_code == 303
    rows_after = load_user_draft(uid)
    assert rows_after[0]["category"] == "Transport"
    assert "_ai_preview" not in rows_after[0]


def test_bulk_reanalyze_preview_enforces_selection_cap(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    uid = 1007
    save_user_draft(uid, [_draft_row(description=f"row {i}") for i in range(21)])

    idxs = [str(i) for i in range(21)]
    resp = client.post(
        f"/drafts/{uid}/bulk-update",
        data={
            "action": "preview_ai",
            "row_idx": idxs,
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "Select at most 20 rows" in resp.headers.get("location", "")
