"""
sqlite_ops.py — SQLite primary store for budget-bot (Cycle S1 Phase 1).

Foundation module: schema init, value_base computation (materialized
equivalent of the Excel VLOOKUP formula in excel_schema.write_transaction_row),
content hashing for idempotent imports, and transaction/reference CRUD.

Nothing in the running bot uses this yet — Phase 2 wires handlers to
storage_facade.py, which delegates here.

Uses only the stdlib sqlite3 module.
"""

import hashlib
import sqlite3
from datetime import datetime, timezone

import settings

# ── Schema ────────────────────────────────────────────────────────────────────

_SCHEMA = """
CREATE TABLE IF NOT EXISTS transactions (
    id                INTEGER PRIMARY KEY,
    date              TEXT,
    year              INTEGER,
    month             INTEGER,
    value             REAL,
    currency          TEXT,
    value_base        REAL,
    rate_used         REAL,
    type              TEXT,
    category          TEXT,
    person            TEXT,
    description       TEXT,
    is_recurring      INTEGER,
    is_done           INTEGER,
    date_modified_utc TEXT,
    source            TEXT,
    content_hash      TEXT UNIQUE
);
CREATE TABLE IF NOT EXISTS categories (
    name        TEXT PRIMARY KEY,
    budget_base REAL,
    active      INTEGER
);
CREATE TABLE IF NOT EXISTS persons (
    name   TEXT PRIMARY KEY,
    active INTEGER
);
CREATE TABLE IF NOT EXISTS rates (
    currency     TEXT PRIMARY KEY,
    rate_to_base REAL
);
CREATE TABLE IF NOT EXISTS goals (
    name      TEXT PRIMARY KEY,
    alloc_pct REAL,
    goal_base REAL
);
CREATE TABLE IF NOT EXISTS sync_log (
    id        INTEGER PRIMARY KEY,
    ts        TEXT,
    direction TEXT,
    status    TEXT,
    detail    TEXT
);
"""


def connect(db_path) -> sqlite3.Connection:
    """Open a connection with row access by column name."""
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path) -> sqlite3.Connection:
    """
    Create the database (and parent directory) if needed, enable WAL mode,
    and ensure all tables exist. Returns an open connection.
    """
    from pathlib import Path
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(_SCHEMA)
    conn.commit()
    return conn


# ── value_base computation ───────────────────────────────────────────────────
# Materialized equivalent of the Excel formula written by
# excel_schema.write_transaction_row:
#
#   =IF(OR(Ccy="", Ccy="<DISPLAY_CURRENCY>"), Value,
#       Value * VLOOKUP(Ccy, Lists!Currency:Rate, 2, 0))
#
# Semantics preserved:
#   - empty currency or currency == display currency → value as-is, rate 1.0
#   - otherwise multiply by the Lists rate. VLOOKUP text matching is
#     case-insensitive and rates are stored uppercase (see
#     excel_schema.load_currency_rates_from_path), so we upper() the code.
#   - an unknown currency makes the Excel formula error (#N/A); here we fall
#     back to rate 1.0 so a row is never lost, mirroring data.load_data()'s
#     fallback `rates.get(ccy.upper(), 1.0)`.


def compute_value_base(value, currency, rates_dict, display_currency=None) -> tuple[float, float]:
    """Return (value_base, rate_used) for a transaction value in `currency`."""
    if display_currency is None:
        display_currency = settings.DISPLAY_CURRENCY
    value = float(value)
    ccy = str(currency or "").strip().upper()
    if not ccy or ccy == str(display_currency).strip().upper():
        return value, 1.0
    rate = float(rates_dict.get(ccy, 1.0))
    return value * rate, rate


# ── Content hash (idempotent import key) ─────────────────────────────────────

def _norm(v) -> str:
    """Stable string form for hashing: None→'', floats without trailing noise."""
    if v is None:
        return ""
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, float):
        return repr(round(v, 2))
    return str(v).strip()


def content_hash_for_row(date, value, currency, type, category, person,
                         description, date_modified) -> str:
    """
    Deterministic sha256 over identity fields. Used as the UNIQUE key on
    transactions.content_hash so re-imports are idempotent.
    """
    parts = [_norm(x) for x in
             (date, value, currency, type, category, person, description, date_modified)]
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()


# ── Transaction CRUD ─────────────────────────────────────────────────────────

_TXN_COLUMNS = (
    "date", "year", "month", "value", "currency", "value_base", "rate_used",
    "type", "category", "person", "description", "is_recurring", "is_done",
    "date_modified_utc", "source", "content_hash",
)


def insert_transaction(conn: sqlite3.Connection, row_dict: dict) -> int:
    """
    Insert one transaction. On content_hash conflict the insert is ignored
    (idempotent re-import) and the existing row's id is returned.
    Missing content_hash is computed from the row fields.
    Returns the row id.
    """
    row = dict(row_dict)
    if not row.get("content_hash"):
        row["content_hash"] = content_hash_for_row(
            row.get("date"), row.get("value"), row.get("currency"),
            row.get("type"), row.get("category"), row.get("person"),
            row.get("description"), row.get("date_modified_utc"),
        )
    if not row.get("date_modified_utc"):
        row["date_modified_utc"] = datetime.now(timezone.utc).isoformat()
    for flag in ("is_recurring", "is_done"):
        if row.get(flag) is not None:
            row[flag] = int(bool(row[flag]))
    cols = [c for c in _TXN_COLUMNS if c in row]
    sql = (f"INSERT INTO transactions ({', '.join(cols)}) "
           f"VALUES ({', '.join('?' for _ in cols)}) "
           f"ON CONFLICT(content_hash) DO NOTHING")
    cur = conn.execute(sql, [row[c] for c in cols])
    conn.commit()
    if cur.rowcount == 1:
        return cur.lastrowid
    existing = conn.execute(
        "SELECT id FROM transactions WHERE content_hash = ?",
        (row["content_hash"],),
    ).fetchone()
    return existing["id"]


def update_transaction(conn: sqlite3.Connection, id: int, fields: dict) -> None:
    """Update the given columns of one transaction; bumps date_modified_utc."""
    fields = dict(fields)
    fields.setdefault("date_modified_utc", datetime.now(timezone.utc).isoformat())
    bad = [k for k in fields if k not in _TXN_COLUMNS]
    if bad:
        raise ValueError(f"Unknown transaction column(s): {bad}")
    assignments = ", ".join(f"{k} = ?" for k in fields)
    conn.execute(f"UPDATE transactions SET {assignments} WHERE id = ?",
                 [*fields.values(), id])
    conn.commit()


def delete_transaction(conn: sqlite3.Connection, id: int) -> None:
    conn.execute("DELETE FROM transactions WHERE id = ?", (id,))
    conn.commit()


_FILTER_COLUMNS = ("year", "month", "category", "person", "type")


def list_transactions(conn: sqlite3.Connection, filters: dict | None = None) -> list[dict]:
    """
    Return transactions as dicts, optionally filtered by year, month,
    category, person, and/or type. Ordered by date then id.
    """
    where, params = [], []
    for key, val in (filters or {}).items():
        if key not in _FILTER_COLUMNS:
            raise ValueError(f"Unsupported filter: {key}")
        where.append(f"{key} = ?")
        params.append(val)
    sql = "SELECT * FROM transactions"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY date, id"
    return [dict(r) for r in conn.execute(sql, params)]


# ── Reference upserts ────────────────────────────────────────────────────────

def upsert_category(conn: sqlite3.Connection, name: str,
                    budget_base: float | None = None, active: bool = True) -> None:
    conn.execute(
        "INSERT INTO categories (name, budget_base, active) VALUES (?, ?, ?) "
        "ON CONFLICT(name) DO UPDATE SET budget_base = excluded.budget_base, "
        "active = excluded.active",
        (name, budget_base, int(active)),
    )
    conn.commit()


def upsert_person(conn: sqlite3.Connection, name: str, active: bool = True) -> None:
    conn.execute(
        "INSERT INTO persons (name, active) VALUES (?, ?) "
        "ON CONFLICT(name) DO UPDATE SET active = excluded.active",
        (name, int(active)),
    )
    conn.commit()


def upsert_rate(conn: sqlite3.Connection, currency: str, rate_to_base: float) -> None:
    conn.execute(
        "INSERT INTO rates (currency, rate_to_base) VALUES (?, ?) "
        "ON CONFLICT(currency) DO UPDATE SET rate_to_base = excluded.rate_to_base",
        (str(currency).strip().upper(), float(rate_to_base)),
    )
    conn.commit()


def upsert_goal(conn: sqlite3.Connection, name: str,
                alloc_pct: float | None = None, goal_base: float | None = None) -> None:
    conn.execute(
        "INSERT INTO goals (name, alloc_pct, goal_base) VALUES (?, ?, ?) "
        "ON CONFLICT(name) DO UPDATE SET alloc_pct = excluded.alloc_pct, "
        "goal_base = excluded.goal_base",
        (name, alloc_pct, goal_base),
    )
    conn.commit()


def log_sync(conn: sqlite3.Connection, direction: str, status: str, detail: str = "") -> None:
    """Record one import/export event in sync_log."""
    conn.execute(
        "INSERT INTO sync_log (ts, direction, status, detail) VALUES (?, ?, ?, ?)",
        (datetime.now(timezone.utc).isoformat(), direction, status, detail),
    )
    conn.commit()


def load_rates_dict(conn: sqlite3.Connection) -> dict[str, float]:
    """{currency: rate_to_base} from the rates table; DISPLAY_CURRENCY fallback."""
    rates = {r["currency"]: r["rate_to_base"] for r in conn.execute("SELECT * FROM rates")}
    return rates or {settings.DISPLAY_CURRENCY: 1.0}
