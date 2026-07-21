"""
excel_ops.py — async write operations on the Excel file.
All writes go through asyncio.get_running_loop().run_in_executor so they
don't block the Telegram event loop.
"""

import asyncio

from config import log
from log_decorators import log_call
from excel_schema import find_next_data_row, lists_currency_range, write_transaction_row
from file_storage import (
    ExcelFileContext,
    append_transactions_batch,
    atomic_save,
    delete_transaction_row,
    update_currency_rates_in_excel,
    append_to_recovery_queue,
    flush_recovery_queue,
    _excel_write_lock,
)
from models import Transaction


@log_call()
def _do_append_transaction(transaction: Transaction) -> None:
    from openpyxl import load_workbook

    row = transaction.to_row()
    with ExcelFileContext() as excel_path:
        wb = load_workbook(excel_path)
        ws = wb["MasterData"]
        r = find_next_data_row(ws)
        write_transaction_row(ws, r, row, lists_currency_range(wb))
        atomic_save(wb, excel_path)
        log.info("Appended transaction row %d: %s", r, row)


@log_call()
async def append_transaction(transaction: Transaction) -> None:
    loop = asyncio.get_running_loop()
    async with _excel_write_lock:
        try:
            await loop.run_in_executor(None, _do_append_transaction, transaction)
        except Exception as e:
            log.error("Upload failed — saving to recovery queue: %s", e)
            append_to_recovery_queue(transaction.to_row())
            raise


async def async_delete_transaction_row(row_idx: int) -> None:
    loop = asyncio.get_running_loop()
    async with _excel_write_lock:
        await loop.run_in_executor(None, delete_transaction_row, row_idx)


async def async_update_currency_rates(new_rates: dict) -> None:
    loop = asyncio.get_running_loop()
    async with _excel_write_lock:
        await loop.run_in_executor(None, update_currency_rates_in_excel, new_rates)


async def async_append_batch(transactions: list) -> None:
    loop = asyncio.get_running_loop()
    async with _excel_write_lock:
        await loop.run_in_executor(None, append_transactions_batch, transactions)


def replay_recovery_queue() -> None:
    """
    Re-apply transactions persisted after a failed write. One open/save cycle
    for the whole batch; rows that fail are re-queued instead of dropped.
    """
    from openpyxl import load_workbook

    pending = flush_recovery_queue()
    if not pending:
        return
    log.warning("Re-applying %d transactions from recovery queue", len(pending))

    # Queue rows were JSON-roundtripped (json.dumps default=str): dates became
    # strings, numbers may be strings. Rehydrate so replayed rows are typed
    # identically to normally appended ones.
    from datetime import date as _date
    for row in pending:
        if isinstance(row.get("date"), str):
            try:
                row["date"] = _date.fromisoformat(row["date"][:10])
            except ValueError:
                pass
        for numeric_field in ("value", "year"):
            if isinstance(row.get(numeric_field), str):
                try:
                    row[numeric_field] = float(row[numeric_field]) if numeric_field == "value" else int(row[numeric_field])
                except ValueError:
                    pass
        if isinstance(row.get("is_recurring"), str):
            row["is_recurring"] = row["is_recurring"].lower() in {"true", "1", "yes"}
    failed: list[dict] = []
    try:
        with ExcelFileContext() as excel_path:
            wb = load_workbook(excel_path)
            ws = wb["MasterData"]
            lu_range = lists_currency_range(wb)
            r = find_next_data_row(ws)
            for row in pending:
                try:
                    write_transaction_row(ws, r, row, lu_range)
                    log.info("Recovery queue: re-applied row %d: %s", r, row)
                    r += 1
                except Exception as e:
                    log.error("Recovery queue: failed to re-apply row %s: %s", row, e)
                    failed.append(row)
            atomic_save(wb, excel_path)
    except Exception as e:
        log.error("Recovery queue: replay aborted, re-queueing all rows: %s", e)
        failed = pending
    for row in failed:
        append_to_recovery_queue(row)
