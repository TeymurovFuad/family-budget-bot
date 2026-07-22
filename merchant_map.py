"""
merchant_map.py — merchant → category memory.

A small JSON store (data/merchant_map.json, same pattern as user prefs and
bulk drafts) mapping a cleaned, case-folded merchant key to the defaults the
household uses for that merchant: category, type, label, person, is_recurring.

Why: repeat merchants are ~80% of statement rows. A deterministic lookup
means their categorization never drifts AND costs zero DeepSeek tokens —
quick-add messages like "biedronka 45" skip the AI entirely, and bulk rows
get their category from memory instead of trusting the model.

The map learns from preview edits (`2 category=Transport` in /bulk writes the
mapping back) and is seeded once from MasterData history on first use.
"""

import json
import logging
import re
from collections import Counter

import pandas as pd

import settings
from excel_schema import MasterDataSchema, header_of
from file_storage import get_excel_path_for_reading
from validators import clean_merchant_description, coerce_bool

log = logging.getLogger(__name__)

MERCHANT_MAP_PATH = settings.MERCHANT_MAP_PATH

# Fields a map entry may carry; everything else is dropped on save.
_ENTRY_FIELDS = ("label", "category", "type", "person", "is_recurring")

# A merchant must appear this many times in MasterData (with a dominant
# category) before seeding trusts it.
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
    """Persist the merchant map to JSON alongside the Excel file."""
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
    MasterData history and persist the result, so past imports immediately
    make future categorization deterministic.
    """
    existing = _read_map_file()
    if existing is not None:
        return existing
    seeded = seed_from_master()
    save_merchant_map(seeded)
    if seeded:
        log.info("Merchant map seeded from MasterData: %d merchants", len(seeded))
    return seeded


# ── Lookup / learn ────────────────────────────────────────────────────────────

def lookup(mapping: dict, description) -> dict | None:
    """Return the stored defaults for a description's merchant, or None."""
    key = merchant_key(description)
    entry = mapping.get(key) if key else None
    return dict(entry) if isinstance(entry, dict) else None


def learn_from_row(row: dict) -> str | None:
    """
    Persist one row's category/type/person/is_recurring as the defaults for
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
        "person": str(row.get("person") or "").strip(),
        "is_recurring": is_recurring,
    }
    save_merchant_map(mapping)
    return mapping[key]["label"]


# ── Seeding from MasterData history ───────────────────────────────────────────

def seed_from_master() -> dict:
    """
    Build an initial map from MasterData: merchants seen >= 2 times whose most
    common category covers more than half of their rows. Column positions come
    from excel_schema — never hardcoded.
    """
    try:
        df = pd.read_excel(get_excel_path_for_reading(), sheet_name="MasterData")
    except Exception as e:
        log.warning("Merchant-map seeding skipped — could not read MasterData: %s", e)
        return {}

    desc_h = header_of(MasterDataSchema, "description")
    cat_h = header_of(MasterDataSchema, "category")
    type_h = header_of(MasterDataSchema, "type")
    person_h = header_of(MasterDataSchema, "person")
    rec_h = header_of(MasterDataSchema, "is_recurring")
    if desc_h not in df.columns or cat_h not in df.columns:
        return {}

    groups: dict[str, list[dict]] = {}
    for i in df.index:
        desc = df.at[i, desc_h]
        cat = df.at[i, cat_h]
        if pd.isna(desc) or pd.isna(cat) or not str(desc).strip() or not str(cat).strip():
            continue
        key = merchant_key(desc)
        if not key:
            continue
        groups.setdefault(key, []).append({
            "label": clean_merchant_description(str(desc).lstrip("'")),
            "category": str(cat).strip(),
            "type": str(df.at[i, type_h]).strip() if type_h in df.columns and pd.notna(df.at[i, type_h]) else "Expense",
            "person": str(df.at[i, person_h]).strip() if person_h in df.columns and pd.notna(df.at[i, person_h]) else "",
            "is_recurring": bool(df.at[i, rec_h]) if rec_h in df.columns and pd.notna(df.at[i, rec_h]) else False,
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
            "person": Counter(r["person"] for r in matching).most_common(1)[0][0],
            "is_recurring": sum(r["is_recurring"] for r in matching) * 2 > len(matching),
        }
    return result


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
        "currency": (ccy or "PLN").upper(),
        "type": entry.get("type") or "Expense",
        "category": entry.get("category") or "Other",
        "description": entry.get("label") or clean_merchant_description(desc),
        "person": entry.get("person") or "",
        "is_recurring": bool(entry.get("is_recurring", False)),
    }
