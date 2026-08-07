"""
storage_protocol.py — the structural interface every storage backend must
satisfy (Cycle S1 Phase 1).

`storage_facade` (SQLite-backed, module-level functions) satisfies this
Protocol structurally today; a future backend (e.g. a remote API) plugs in
by exposing the same five callables. Protocol over abc.ABC: no inheritance
required, and a module object counts as an implementation.

Conformance is asserted by tests/test_storage_protocol.py via the
runtime_checkable isinstance check.
"""

from typing import Any, Protocol, runtime_checkable

import pandas as pd


@runtime_checkable
class StorageBackend(Protocol):
    def append_transaction(self, transaction: Any) -> None: ...

    def delete_transaction_row(self, id: int, expected: dict | None = None) -> None: ...

    def update_transaction_field(self, id: int, field: Any, value: Any = None,
                                 expected: dict | None = None) -> None: ...

    def load_transactions(self, filters: dict | None = None) -> pd.DataFrame: ...

    def load_reference_data(self) -> dict: ...
