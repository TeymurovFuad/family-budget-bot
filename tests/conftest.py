"""
conftest.py — shared pytest fixtures for budget-bot tests.

IMPORTANT: environment variables are set at MODULE LEVEL (before any project
import) because file_storage.py reads them at import time to set its globals.
"""

import os
import sys
from pathlib import Path

# ── Set env vars BEFORE any project-module import ────────────────────────────
os.environ.setdefault("STORAGE_BACKEND", "local")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "dummy")
os.environ.setdefault("ALLOWED_TELEGRAM_IDS", "123")

# Make sure the project root is on sys.path so all project modules are importable.
PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# ── Now safe to import project modules ───────────────────────────────────────
import datetime

import pytest

import file_storage
from file_storage import create_blank_excel
from models import Transaction


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def _sqlite_seed_template(tmp_path_factory):
    """
    Build ONE seeded SQLite DB per session (schema + the same default lists a
    blank workbook has, per workbook_template.py's fallback). Per-test copies
    are made by _isolate_sqlite_db — a file copy is far cheaper than the ~20
    fsync'ing commits seeding takes on Windows.
    """
    import settings
    import sqlite_ops

    template = tmp_path_factory.mktemp("sqlite_seed") / "seed_budget.db"
    conn = sqlite_ops.init_db(template)
    for cat in ("Groceries", "Transport", "Housing", "Utilities", "Healthcare",
                "Entertainment", "Travel", "Insurance", "Education", "Salary",
                "Freelance", "Rental", "Bonus", "Bank Deposit", "Investment",
                "Emergency Fund", "Other"):
        sqlite_ops.upsert_category(conn, cat)
    for code, rate in ((settings.DISPLAY_CURRENCY, 1.0), ("EUR", 4.28),
                       ("USD", 3.95), ("GBP", 5.05), ("CHF", 4.45)):
        sqlite_ops.upsert_rate(conn, code, rate)
    conn.close()
    return template


@pytest.fixture(autouse=True)
def _isolate_sqlite_db(tmp_path, monkeypatch, _sqlite_seed_template):
    """
    Point storage_facade/sqlite at a fresh temp DB for every test, seeded
    with the same default lists a blank workbook has, so unpatched
    storage_facade.load_reference_data() calls behave like
    data.load_reference_data() on a blank Excel did before S1 Phase 2.
    Also guarantees no test ever touches a real data/budget.db.
    """
    import shutil

    import settings

    db_path = tmp_path / "test_budget.db"
    shutil.copy2(_sqlite_seed_template, db_path)
    monkeypatch.setattr(settings, "SQLITE_DB_PATH", db_path)


@pytest.fixture(autouse=True)
def _isolate_merchant_map(tmp_path, monkeypatch):
    """Point the merchant map at a temp file so no test touches data/."""
    import merchant_map
    map_path = tmp_path / "merchant_map.json"
    # Pre-create an empty map so load_merchant_map() never auto-seeds from
    # (and thereby never touches) a real workbook during unrelated tests.
    map_path.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(merchant_map, "MERCHANT_MAP_PATH", map_path)


@pytest.fixture()
def excel_path(tmp_path, monkeypatch):
    """
    Provide a fresh blank Excel workbook in a temp directory.

    Also monkeypatches file_storage.LOCAL_XLSX_PATH so that ExcelFileContext
    and get_excel_path_for_reading() operate on the temp file, not any real
    data file on disk.
    """
    path = tmp_path / "test_budget.xlsx"
    # Force fallback builder — tests must not depend on the real template's structure
    monkeypatch.setattr(file_storage, "TEMPLATE_PATH", tmp_path / "nonexistent_template.xlsx")
    create_blank_excel(path)

    monkeypatch.setattr(file_storage, "LOCAL_XLSX_PATH", path)
    # Also patch USER_PREFS_PATH to a temp location so pref tests don't touch disk
    monkeypatch.setattr(file_storage, "USER_PREFS_PATH", tmp_path / "user_prefs.json")

    yield path
    # tmp_path is cleaned up automatically by pytest — no explicit cleanup needed


@pytest.fixture()
def sample_transaction():
    """Return a fully-populated Transaction with known values."""
    return Transaction(
        date=datetime.date(2024, 6, 15),
        value=150.50,
        currency="PLN",
        transaction_type="Expense",
        category="Groceries",
        person="Alice",
        description="weekly shop",
    )


@pytest.fixture()
def sample_expense_row():
    """Return a plain dict matching what the AI parser returns for a single expense."""
    return {
        "date": "2024-06-15",
        "value": 150.50,
        "currency": "PLN",
        "type": "Expense",
        "category": "Groceries",
        "description": "weekly shop",
        "person": "<YOUR_NAME>",
    }


@pytest.fixture(autouse=True)
def isolated_bulk_drafts(tmp_path, monkeypatch):
    """Every test gets its own bulk-drafts dir — no cross-test or repo pollution."""
    import settings as _settings
    draft_dir = tmp_path / "bulk_drafts"
    draft_dir.mkdir()
    monkeypatch.setattr(_settings, "BULK_DRAFTS_DIR", draft_dir)
    return draft_dir
