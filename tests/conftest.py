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
