"""
data.py — read-only Excel helpers: load_data, load_rates, load_budgets,
          now_utc, current_year_and_month, month_name.
"""

import calendar
from datetime import datetime, timezone

import pandas as pd

from config import log
from excel_schema import MasterDataSchema, header_of, load_currency_rates_from_path
from file_storage import get_excel_path_for_reading, load_budgets_from_excel, load_lists
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

def load_reference_data() -> dict:
    lists = load_lists(get_excel_path_for_reading())
    rates = load_rates()
    lists["currencies"] = list(rates.keys()) if rates else ["PLN"]
    return lists


def load_budgets() -> dict[str, float]:
    return load_budgets_from_excel(get_excel_path_for_reading())


# ── rates ─────────────────────────────────────────────────────────────────────

def load_rates() -> dict[str, float]:
    """
    Read currency rate table from the Lists sheet.
    Column positions are resolved via ListsSchema — no hardcoded positions.
    Returns {currency_code: pln_per_unit}. Falls back to {"PLN": 1.0}.
    """
    try:
        return load_currency_rates_from_path(get_excel_path_for_reading())
    except Exception as e:
        log.warning("Could not load currency rates: %s", e)
        return {"PLN": 1.0}


def get_rate(ccy: str, rates: dict[str, float]) -> float:
    """1 unit of ccy in PLN. Returns 1.0 if unknown."""
    return rates.get(ccy.upper(), 1.0)


# ── master data ───────────────────────────────────────────────────────────────

def load_data() -> pd.DataFrame:
    """
    Load MasterData sheet. All aggregations use the '_pln' column.
    Value (PLN) contains Excel formulas — pandas reads cached results, which may
    be NaN for rows never opened in Excel. Falls back to computing from Value *
    exchange rate so reports never show 0 due to stale formula cache.
    """
    excel_path = get_excel_path_for_reading()
    df = pd.read_excel(excel_path, sheet_name="MasterData")

    df["Value"] = pd.to_numeric(df["Value"], errors="coerce")

    if "Value (PLN)" in df.columns:
        df["_pln"] = pd.to_numeric(df["Value (PLN)"], errors="coerce")
    else:
        df["_pln"] = pd.to_numeric(df["Value"], errors="coerce")

    if "Currency" not in df.columns:
        df["Currency"] = "PLN"
    df["Currency"] = df["Currency"].fillna("PLN")

    # Recompute _pln for any row where the formula cache is missing
    missing = df["_pln"].isna() & df["Value"].notna()
    if missing.any():
        rates = load_rates()
        df.loc[missing, "_pln"] = df.loc[missing].apply(
            lambda r: r["Value"] * rates.get(str(r["Currency"]).upper(), 1.0),
            axis=1,
        )

    df["Year"]  = pd.to_numeric(df["Year"],  errors="coerce").astype("Int64")
    df = df.dropna(subset=["_pln", "Type", "Year", "Month"])
    df["IsDone"] = df["IsDone"].fillna(True).astype(bool)

    return df


def load_dedup_evidence(start=None, end=None) -> dict:
    """
    Multiset evidence of MasterData rows for dedup-v2's count-aware, two-pass
    scan. Reads MasterData ONCE (the loose pass reuses this same read — no
    extra workbook access, no AI calls) and returns:

        {
          "strict": {strict_key: [(date_iso, description), ...]},
          "loose":  {loose_key:  [(date_iso, description), ...]},
        }

    strict_key = date|value|currency|cleaned-description (validators.make_dedup_key)
    loose_key  = date|value|currency, no description (validators.make_loose_dedup_key)

    len(evidence["strict"][key]) / len(evidence["loose"][key]) is that key's
    multiset count in MasterData — the basis for count-aware matching ("3
    identical rows found, 2 already in your sheet -> saving 1, skipping 2").
    Only rows whose Date falls in [start, end] (date objects, both
    optional/inclusive) are counted. Returns empty dicts on any read
    failure — dedup never blocks an import, it just stops flagging anything.
    """
    empty = {"strict": {}, "loose": {}}
    try:
        df = pd.read_excel(get_excel_path_for_reading(), sheet_name="MasterData")
        date_h  = header_of(MasterDataSchema, "date")
        value_h = header_of(MasterDataSchema, "value")
        ccy_h   = header_of(MasterDataSchema, "currency")
        desc_h  = header_of(MasterDataSchema, "description")
        if date_h not in df.columns or value_h not in df.columns:
            return empty
        dates = pd.to_datetime(df[date_h], errors="coerce")
        mask = dates.notna() & df[value_h].notna()
        if start is not None:
            mask &= dates >= pd.Timestamp(start)
        if end is not None:
            mask &= dates <= pd.Timestamp(end)
        strict: dict[str, list[tuple[str, str]]] = {}
        loose: dict[str, list[tuple[str, str]]] = {}
        for i in df.index[mask]:
            date_iso = dates.loc[i].date().isoformat()
            value = df.at[i, value_h]
            ccy = df.at[i, ccy_h] if ccy_h in df.columns and pd.notna(df.at[i, ccy_h]) else "PLN"
            desc = df.at[i, desc_h] if desc_h in df.columns and pd.notna(df.at[i, desc_h]) else ""
            strict_key = make_dedup_key(date_iso, value, ccy, desc)
            loose_key = make_loose_dedup_key(date_iso, value, ccy)
            strict.setdefault(strict_key, []).append((date_iso, str(desc)))
            loose.setdefault(loose_key, []).append((date_iso, str(desc)))
        return {"strict": strict, "loose": loose}
    except Exception as e:
        log.warning("Could not load dedup evidence from MasterData: %s", e)
        return empty


def load_dedup_keys(start=None, end=None) -> set[str]:
    """
    Backward-compatible view of load_dedup_evidence: the set of strict dedup
    keys (see validators.make_dedup_key) present in MasterData in [start, end].
    Prefer load_dedup_evidence for count-aware / loose-match callers.
    """
    return set(load_dedup_evidence(start, end)["strict"].keys())
