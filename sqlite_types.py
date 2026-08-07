"""
sqlite_types.py — enums and row shape for the SQLite store (Cycle S1 Phase 1).

Fixed value sets stored in SQLite columns are StrEnums (str subclasses), so
they bind directly as sqlite3 parameters and compare equal to the plain
strings that come back from a round-trip. TransactionRow is the internal
fixed-shape row passed between the facade / import script and
sqlite_ops.insert_transaction (the pandas DataFrame boundary in
storage_facade.load_transactions stays dict/DataFrame-shaped on purpose).
"""

from dataclasses import asdict, dataclass
from enum import StrEnum


class TransactionType(StrEnum):
    """transactions.type — same value set as the Excel Lists sheet."""
    EXPENSE = "Expense"
    INCOME = "Income"
    SAVINGS = "Savings"


class TransactionSource(StrEnum):
    """transactions.source — where a row entered the store."""
    BOT = "bot"
    EXCEL_IMPORT = "excel_import"
    WEB = "web"


class SyncDirection(StrEnum):
    """sync_log.direction."""
    IMPORT = "import"
    EXPORT = "export"


class SyncStatus(StrEnum):
    """sync_log.status."""
    OK = "ok"
    ERROR = "error"


@dataclass
class TransactionRow:
    """One transactions-table row as produced by the facade/import script."""
    date: str | None = None
    year: int | None = None
    month: str | None = None
    value: float | None = None
    currency: str | None = None
    value_base: float | None = None
    rate_used: float | None = None
    type: str | None = None
    category: str | None = None
    person: str | None = None
    description: str | None = None
    is_recurring: bool | None = None
    is_done: bool | None = None
    date_modified_utc: str | None = None
    source: str = TransactionSource.BOT
    content_hash: str | None = None

    def to_db_dict(self) -> dict:
        return asdict(self)
