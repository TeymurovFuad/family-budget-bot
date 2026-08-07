"""
data.py — thin shim over storage_facade.

All reads now delegate to SQLite via storage_facade. The TTL cache is gone —
SQLite reads are local and fast; no remote-download cost.
"""

from datetime import datetime, timezone

import storage_facade
import settings
from config import log
from models import MONTH_NAMES
from validators import make_dedup_key, make_loose_dedup_key


# ── time ──────────────────────────────────────────────────────────────────────

def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def month_name(month_number: int) -> str:
    return MONTH_NAMES[month_number - 1]


def current_year_and_month() -> tuple[int, str]:
    n = now_utc()
    return n.year, month_name(n.month)


# ── reference data ────────────────────────────────────────────────────────────

def invalidate_reference_cache() -> None:
    """No-op — SQLite reads are always fresh; no cache to invalidate."""
    pass


def load_reference_data() -> dict:
    return storage_facade.load_reference_data()


def load_budgets() -> dict[str, float]:
    return storage_facade.load_budgets()


# ── rates ─────────────────────────────────────────────────────────────────────

def load_rates() -> dict[str, float]:
    return storage_facade.load_rates()


def get_rate(ccy: str, rates: dict[str, float]) -> float:
    """1 unit of ccy in base currency. Returns 1.0 if unknown."""
    return rates.get(ccy.upper(), 1.0)


# ── master data ───────────────────────────────────────────────────────────────

def load_data():
    return storage_facade.load_transactions()


def load_dedup_evidence(start=None, end=None) -> dict:
    return storage_facade.load_dedup_evidence(start, end)


def load_dedup_keys(start=None, end=None) -> set[str]:
    """
    Backward-compatible view of load_dedup_evidence: the set of strict dedup
    keys present in the transactions table in [start, end].
    Prefer load_dedup_evidence for count-aware / loose-match callers.
    """
    return set(load_dedup_evidence(start, end)["strict"].keys())
