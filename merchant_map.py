"""
merchant_map.py — merchant → category memory.

A small JSON store (data/merchant_map.json, same pattern as user prefs and
bulk drafts) mapping a cleaned, case-folded merchant key to the defaults the
household uses for that merchant: category, type, label, is_recurring.
(Old entries may still carry a legacy "person" key — tolerated, never written.)

Why: repeat merchants are ~80% of statement rows. A deterministic lookup
means their categorization never drifts AND costs zero DeepSeek tokens —
quick-add messages like "biedronka 45" skip the AI entirely, and bulk rows
get their category from memory instead of trusting the model.

The map learns from preview edits (`2 category=Transport` in /bulk writes the
mapping back) and is seeded once from transaction history on first use.
"""

import json
import logging
import re
from collections import Counter

import pandas as pd

import settings
import storage_facade
from validators import clean_merchant_description, coerce_bool

log = logging.getLogger(__name__)

MERCHANT_MAP_PATH = settings.MERCHANT_MAP_PATH

# Fields a map entry may carry; everything else is dropped on save.
_ENTRY_FIELDS = ("label", "category", "type", "is_recurring")

# A merchant must appear this many times in the transactions table (with a
# dominant category) before seeding trusts it.
_SEED_MIN_OCCURRENCES = 2


def merchant_key(description) -> str:
    """Stable lookup key: guard-quote stripped, junk cleaned, case-folded."""
    cleaned = clean_merchant_description(str(description or "").lstrip("'"))
    return re.sub(r"\s+", " ", cleaned).strip().lower()


# ── Persistence (same JSON-next-to-the-workbook pattern as user prefs) ────────

def _read_map_file() -> dict | None:
    try:
        if MERCHANT_MAP_PATH.exists():
            data = json.loads(MERCHANT_MAP_PATH.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
    except Exception as e:
        log.warning("Could not load merchant map: %s", e)
        return {}
    return None


def save_merchant_map(mapping: dict) -> None:
    """Persist the merchant map to JSON."""
    try:
        MERCHANT_MAP_PATH.parent.mkdir(parents=True, exist_ok=True)
        MERCHANT_MAP_PATH.write_text(
            json.dumps(mapping, indent=2, ensure_ascii=False), encoding="utf-8"
        )
    except Exception as e:
        log.warning("Could not save merchant map: %s", e)


def load_merchant_map() -> dict:
    """
    Load the merchant map. On very first use (no file yet) seed it from
    transaction history and persist the result, so past imports immediately
    make future categorization deterministic.
    """
    existing = _read_map_file()
    if existing is not None:
        return existing
    seeded = seed_from_master()
    save_merchant_map(seeded)
    if seeded:
        log.info("Merchant map seeded from transactions: %d merchants", len(seeded))
    return seeded


# ── Lookup / learn ────────────────────────────────────────────────────────────

def lookup(mapping: dict, description) -> dict | None:
    """Return the stored defaults for a description's merchant, or None."""
    key = merchant_key(description)
    entry = mapping.get(key) if key else None
    return dict(entry) if isinstance(entry, dict) else None


def learn_from_row(row: dict) -> str | None:
    """
    Persist one row's category/type/is_recurring as the defaults for
    its merchant. Called when the user edits a row in the /bulk preview —
    a human correction is the strongest signal we get. Returns the cleaned
    merchant label that was learned, or None if the row can't be keyed.
    """
    desc = str(row.get("description") or "")
    key = merchant_key(desc)
    if not key or not str(row.get("category") or "").strip():
        return None
    try:
        is_recurring = coerce_bool(row.get("is_recurring", False))
    except ValueError:
        is_recurring = False
    mapping = load_merchant_map()
    mapping[key] = {
        "label": clean_merchant_description(desc.lstrip("'")),
        "category": str(row.get("category")).strip(),
        "type": str(row.get("type") or "Expense").strip(),
        "is_recurring": is_recurring,
    }
    save_merchant_map(mapping)
    return mapping[key]["label"]


def rename_category(old_name: str, new_name: str) -> int:
    """
    Rename a category across all merchant-map entries so future bulk imports
    stop suggesting the retired name. Returns the number of entries updated.
    Called wherever a workbook-wide category rename happens (/setup,
    scripts/rename_category.py).
    """
    mapping = load_merchant_map()
    updated = 0
    for entry in mapping.values():
        if isinstance(entry, dict) and entry.get("category") == old_name:
            entry["category"] = new_name
            updated += 1
    if updated:
        save_merchant_map(mapping)
        log.info("Renamed category in merchant map: %s → %s (%d entries)",
                 old_name, new_name, updated)
    return updated


# ── Seeding from transaction history ──────────────────────────────────────────

def seed_from_master() -> dict:
    """
    Build an initial map from the transactions table: merchants seen >= 2 times
    whose most common category covers more than half of their rows.
    """
    try:
        df = storage_facade.load_transactions()
    except Exception as e:
        log.warning("Merchant-map seeding skipped — could not read transactions: %s", e)
        return {}

    if "Description" not in df.columns or "Category" not in df.columns:
        return {}

    groups: dict[str, list[dict]] = {}
    for i in df.index:
        desc = df.at[i, "Description"]
        cat = df.at[i, "Category"]
        if pd.isna(desc) or pd.isna(cat) or not str(desc).strip() or not str(cat).strip():
            continue
        key = merchant_key(desc)
        if not key:
            continue
        type_val = df.at[i, "Type"] if "Type" in df.columns and pd.notna(df.at[i, "Type"]) else "Expense"
        rec_val = df.at[i, "IsRecurring"] if "IsRecurring" in df.columns and pd.notna(df.at[i, "IsRecurring"]) else False
        groups.setdefault(key, []).append({
            "label": clean_merchant_description(str(desc).lstrip("'")),
            "category": str(cat).strip(),
            "type": str(type_val).strip(),
            "is_recurring": bool(rec_val),
        })

    result: dict[str, dict] = {}
    for key, rows in groups.items():
        if len(rows) < _SEED_MIN_OCCURRENCES:
            continue
        top_cat, n = Counter(r["category"] for r in rows).most_common(1)[0]
        if n * 2 <= len(rows):  # no dominant category — don't guess
            continue
        matching = [r for r in rows if r["category"] == top_cat]
        result[key] = {
            "label": matching[-1]["label"],
            "category": top_cat,
            "type": Counter(r["type"] for r in matching).most_common(1)[0][0],
            "is_recurring": sum(r["is_recurring"] for r in matching) * 2 > len(matching),
        }
    return result


# ── Recurring detection from history ─────────────────────────────────────────

# Amount tolerance for "same subscription, slightly different bill".
_RECURRING_AMOUNT_TOLERANCE = 0.10
# Distinct months required before a merchant looks recurring.
_RECURRING_MIN_MONTHS = 2


def detect_recurring(description, value) -> bool:
    """
    True when this merchant appears in the transactions table in >= 2 distinct
    months with a similar amount (±10%). Used to PROPOSE is_recurring on
    confirm cards — never to set it silently. Returns False on any read problem.
    """
    key = merchant_key(description)
    try:
        target = abs(float(value))
    except (TypeError, ValueError):
        return False
    if not key or not target:
        return False

    try:
        df = storage_facade.load_transactions()
    except Exception as e:
        log.debug("Recurring detection skipped — could not read transactions: %s", e)
        return False

    if not all(h in df.columns for h in ("Description", "Value", "Date")):
        return False

    months: set[tuple[int, int]] = set()
    for i in df.index:
        if merchant_key(df.at[i, "Description"]) != key:
            continue
        try:
            row_val = abs(float(df.at[i, "Value"]))
        except (TypeError, ValueError):
            continue
        if abs(row_val - target) > target * _RECURRING_AMOUNT_TOLERANCE:
            continue
        d = pd.to_datetime(df.at[i, "Date"], errors="coerce")
        if pd.isna(d):
            continue
        months.add((d.year, d.month))
        if len(months) >= _RECURRING_MIN_MONTHS:
            return True
    return False


# ── Zero-token quick-add fast path ────────────────────────────────────────────

# "[YYYY-MM-DD] <merchant words> <amount> [CCY]"  e.g. "biedronka 45",
# "lunch 45.50 eur", "2026-05-24 uber 23,90".
_QUICK_RE = re.compile(
    r"^(?:(\d{4}-\d{2}-\d{2})\s+)?(.+?)\s+(-?\d+(?:[.,]\d{1,2})?)\s*([A-Za-z]{3})?$"
)


def try_local_quick_parse(text: str) -> dict | None:
    """
    Parse a quick-add message WITHOUT calling the AI, when the merchant is
    already known in the map. Returns a parsed-row dict (same shape the AI
    returns) or None to fall through to the AI. Zero DeepSeek tokens.
    """
    match = _QUICK_RE.match(str(text or "").strip())
    if not match:
        return None
    date_s, desc, amount_s, ccy = match.groups()
    entry = lookup(load_merchant_map(), desc)
    if not entry:
        return None
    return {
        "date": date_s or "",
        "value": float(amount_s.replace(",", ".")),
        "currency": (ccy or settings.DISPLAY_CURRENCY).upper(),
        "type": entry.get("type") or "Expense",
        "category": entry.get("category") or "Other",
        "description": entry.get("label") or clean_merchant_description(desc),
        "person": "",  # field retired — legacy map entries with a person key are ignored
        "is_recurring": bool(entry.get("is_recurring", False)),
    }
