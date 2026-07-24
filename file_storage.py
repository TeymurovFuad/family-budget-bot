"""
file_storage.py
===================
All access to the Excel file goes through this module.

Supports three storage backends, selected by environment variable:

  STORAGE_BACKEND=local  →  read/write from local disk  (default if nothing set)
  STORAGE_BACKEND=gcs    →  Google Cloud Storage
  STORAGE_BACKEND=s3     →  Any S3-compatible storage:
                             AWS S3, Oracle Object Storage, Cloudflare R2,
                             Backblaze B2, MinIO, DigitalOcean Spaces

bot.py and scheduled_report.py import only two things from here:
  - get_excel_path_for_reading()   returns a local Path ready for pandas/openpyxl
  - ExcelFileContext               context manager for read-write operations

Neither of those callers knows or cares which backend is active.

─────────────────────────────────────────────────────────────────────────────
Environment variables by backend
─────────────────────────────────────────────────────────────────────────────

Local (default — development, phone hosting, Oracle VM with local disk):
  XLSX_PATH          Path to the Excel file. Default: data/Expenses_Improved.xlsx

GCS (Google Cloud Storage — free tier, recommended for reports + phone setup):
  STORAGE_BACKEND    gcs
  GCS_BUCKET_NAME    Bucket name, e.g. your-bucket-name
  GCS_OBJECT_NAME    Object name inside bucket. Default: Expenses_Improved.xlsx
  GCS_KEY_JSON       Full contents of service account JSON key (for GitHub Actions
                     or any host where you can't write a file to disk)
                     Leave empty if GOOGLE_APPLICATION_CREDENTIALS is set instead.

S3-compatible (Oracle Object Storage, Cloudflare R2, Backblaze B2, AWS S3):
  STORAGE_BACKEND    s3
  S3_BUCKET_NAME     Bucket name
  S3_OBJECT_NAME     Object name. Default: Expenses_Improved.xlsx
  S3_ENDPOINT_URL    Full endpoint URL. Examples:
                       Oracle:     https://<namespace>.compat.objectstorage.<region>.oraclecloud.com
                       Cloudflare: https://<account-id>.r2.cloudflarestorage.com
                       Backblaze:  https://s3.<region>.backblazeb2.com
                       AWS:        leave empty (boto3 uses default)
  S3_ACCESS_KEY      Access key ID (AWS_ACCESS_KEY_ID equivalent)
  S3_SECRET_KEY      Secret access key (AWS_SECRET_ACCESS_KEY equivalent)
  S3_REGION          Region name. Default: us-east-1
                     Oracle uses: us-ashburn-1, eu-frankfurt-1, etc.
"""

import asyncio
import json
import tempfile
import time
from pathlib import Path

import settings
from logger import get_logger

log = get_logger(__name__)

from excel_schema import CyclesSchema, ListsSchema, MasterDataSchema, find_col, col_indices, header_of

_excel_write_lock = asyncio.Lock()


class RowMovedError(Exception):
    """
    Raised when a row picked in /delete or /edit no longer matches what the
    user saw at pick time — another write shifted rows in between, so the
    row index is stale. Callers should abort instead of silently mutating
    the wrong transaction.
    """


def _row_matches_snapshot(ws, headers: dict, row_idx: int, expected: dict) -> bool:
    """
    Best-effort check that MasterData row `row_idx` still holds the same
    date/value/description the user saw when they picked it. Used to guard
    against the row having shifted due to a concurrent delete/edit.
    """
    if row_idx < 2 or row_idx > ws.max_row:
        return False

    for col_name in ("Date", "Value", "Description"):
        if col_name not in expected:
            continue
        col_idx = headers.get(col_name)
        if col_idx is None:
            continue
        current = ws.cell(row_idx, col_idx).value
        target = expected[col_name]

        if col_name == "Date":
            current_cmp = current.date() if hasattr(current, "date") else current
            target_cmp = target.date() if hasattr(target, "date") else target
        elif col_name == "Value":
            try:
                current_cmp = round(float(current), 2)
                target_cmp = round(float(target), 2)
            except (TypeError, ValueError):
                current_cmp, target_cmp = current, target
        else:
            current_cmp = str(current or "")
            target_cmp = str(target or "")

        if current_cmp != target_cmp:
            return False
    return True


def atomic_save(wb, path) -> None:
    """
    Crash-safe workbook save: write to a sibling temp file, keep a rolling
    .bak of the previous version, then atomically replace the target.
    A crash mid-save can no longer corrupt the only copy of the data.
    """
    import os
    import shutil

    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    try:
        wb.save(tmp)
        if path.exists():
            try:
                shutil.copy2(path, path.with_name(path.name + ".bak"))
            except Exception as e:
                log.warning("Could not write backup for %s: %s", path, e)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)

_temp_files: set[Path] = set()


def cleanup_temp_files() -> None:
    for p in list(_temp_files):
        try:
            p.unlink(missing_ok=True)
            _temp_files.discard(p)
        except Exception as e:
            log.warning("Could not delete temp file %s: %s", p, e)


STORAGE_BACKEND = settings.STORAGE_BACKEND
LOCAL_XLSX_PATH = settings.XLSX_PATH
USER_PREFS_PATH = settings.USER_PREFS_PATH

GCS_BUCKET_NAME = settings.GCS_BUCKET_NAME
GCS_OBJECT_NAME = settings.GCS_OBJECT_NAME
GCS_KEY_JSON    = settings.GCS_KEY_JSON

S3_BUCKET_NAME  = settings.S3_BUCKET_NAME
S3_OBJECT_NAME  = settings.S3_OBJECT_NAME
S3_ENDPOINT_URL = settings.S3_ENDPOINT_URL
S3_ACCESS_KEY   = settings.S3_ACCESS_KEY
S3_SECRET_KEY   = settings.S3_SECRET_KEY
S3_REGION       = settings.S3_REGION

RECOVERY_QUEUE_PATH = settings.RECOVERY_QUEUE_PATH


def append_to_recovery_queue(row: dict) -> None:
    """Append a row to the recovery queue with a crash-safe atomic write."""
    import os

    queue = []
    if RECOVERY_QUEUE_PATH.exists():
        try:
            queue = json.loads(RECOVERY_QUEUE_PATH.read_text())
        except (json.JSONDecodeError, ValueError) as e:
            log.error("Recovery queue file is corrupt, starting a new queue: %s", e)
            queue = []
    queue.append(row)
    tmp = RECOVERY_QUEUE_PATH.with_name(RECOVERY_QUEUE_PATH.name + ".tmp")
    tmp.write_text(json.dumps(queue, default=str))
    os.replace(tmp, RECOVERY_QUEUE_PATH)


def flush_recovery_queue() -> list[dict]:
    """
    Read pending recovery rows WITHOUT deleting the file. The caller must
    call delete_recovery_queue_file() only after the rows have been fully
    replayed, so a crash mid-replay can't lose queued data.

    If the file contains invalid JSON (e.g. from a crash mid-write before
    this module wrote atomically), it is quarantined with a `.corrupt`
    suffix and an empty list is returned instead of raising, so startup
    is never blocked by a corrupted queue file.
    """
    if not RECOVERY_QUEUE_PATH.exists():
        return []
    try:
        return json.loads(RECOVERY_QUEUE_PATH.read_text())
    except (json.JSONDecodeError, ValueError) as e:
        corrupt_path = RECOVERY_QUEUE_PATH.with_name(RECOVERY_QUEUE_PATH.name + ".corrupt")
        log.error("Recovery queue file is corrupt, quarantining to %s: %s", corrupt_path, e)
        try:
            RECOVERY_QUEUE_PATH.replace(corrupt_path)
        except Exception as e2:
            log.error("Failed to quarantine corrupt recovery queue file: %s", e2)
        return []


def delete_recovery_queue_file() -> None:
    """Remove the recovery queue file. Call only after replay has fully completed."""
    RECOVERY_QUEUE_PATH.unlink(missing_ok=True)


def _active_backend() -> str:
    if STORAGE_BACKEND == "gcs" or GCS_BUCKET_NAME:
        return "gcs"
    if STORAGE_BACKEND == "s3" or S3_BUCKET_NAME:
        return "s3"
    return "local"


def _repair_template_workbook(path: Path) -> None:
    """
    Minimal template repair for freshly copied workbooks.

    The template is canonical — headers and layout are already correct and
    resolved by excel_schema at runtime. Only ensure the Date Modified column
    exists, and clear any leftover data/placeholder rows.
    """
    from openpyxl import load_workbook

    wb = load_workbook(path)
    changed = False

    if "MasterData" in wb.sheetnames:
        ws = wb["MasterData"]
        if find_col(ws, header_of(MasterDataSchema, "date_modified")) is None:
            ws.cell(1, ws.max_column + 1).value = header_of(MasterDataSchema, "date_modified")
            changed = True
        if ws.max_row > 1:
            ws.delete_rows(2, ws.max_row - 1)
            # delete_rows shrinks dropdown validation ranges along with the
            # rows — restore them so a fresh workbook has working dropdowns.
            from excel_schema import extend_validation_ranges
            extend_validation_ranges(ws, 1)
            changed = True

    if "Lists" in wb.sheetnames:
        ws = wb["Lists"]
        persons_col = find_col(ws, header_of(ListsSchema, "persons"))
        if persons_col:
            for row in range(2, ws.max_row + 1):
                if ws.cell(row, persons_col).value is not None:
                    ws.cell(row, persons_col).value = None
                    changed = True

    from cycles import CYCLES_SHEET_NAME, ensure_cycles_sheet
    if CYCLES_SHEET_NAME not in wb.sheetnames:
        ensure_cycles_sheet(wb)
        changed = True

    if changed:
        wb.save(path)

def _gcs_client():
    from google.cloud import storage as gcs
    from google.oauth2 import service_account
    if GCS_KEY_JSON:
        key_data    = json.loads(GCS_KEY_JSON)
        credentials = service_account.Credentials.from_service_account_info(key_data)
        return gcs.Client(credentials=credentials, project=key_data.get("project_id"))
    return gcs.Client()


def _s3_client():
    import boto3
    kwargs = dict(
        region_name          = S3_REGION,
        aws_access_key_id    = S3_ACCESS_KEY or None,
        aws_secret_access_key= S3_SECRET_KEY or None,
    )
    if S3_ENDPOINT_URL:
        kwargs["endpoint_url"] = S3_ENDPOINT_URL
    return boto3.client("s3", **kwargs)


def _download_to_temp_file() -> Path:
    backend   = _active_backend()
    temp_file = tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False)
    temp_path = Path(temp_file.name)
    temp_file.close()
    _temp_files.add(temp_path)

    log.info("Downloading Excel from backend=%s", backend)
    if backend == "gcs":
        client = _gcs_client()
        client.bucket(GCS_BUCKET_NAME).blob(GCS_OBJECT_NAME).download_to_filename(str(temp_path))
        log.info("Downloaded from GCS: gs://%s/%s", GCS_BUCKET_NAME, GCS_OBJECT_NAME)

    elif backend == "s3":
        _s3_client().download_file(S3_BUCKET_NAME, S3_OBJECT_NAME, str(temp_path))
        log.info("Downloaded from S3: s3://%s/%s", S3_BUCKET_NAME, S3_OBJECT_NAME)

    return temp_path


def _upload_from_local_file(local_path: Path) -> None:
    """Upload to remote storage with exponential backoff retry (3 attempts)."""
    backend     = _active_backend()
    max_attempts = 3

    for attempt in range(1, max_attempts + 1):
        try:
            if backend == "gcs":
                client = _gcs_client()
                client.bucket(GCS_BUCKET_NAME).blob(GCS_OBJECT_NAME).upload_from_filename(str(local_path))
                log.info("Uploaded to GCS: gs://%s/%s", GCS_BUCKET_NAME, GCS_OBJECT_NAME)
            elif backend == "s3":
                _s3_client().upload_file(str(local_path), S3_BUCKET_NAME, S3_OBJECT_NAME)
                log.info("Uploaded to S3: s3://%s/%s", S3_BUCKET_NAME, S3_OBJECT_NAME)
            return
        except Exception as e:
            if attempt == max_attempts:
                log.error("Upload failed after %d attempts — transaction may be lost: %s", max_attempts, e)
                raise
            wait = 2 ** attempt
            log.warning("Upload attempt %d/%d failed, retrying in %ds: %s", attempt, max_attempts, wait, e)
            time.sleep(wait)


TEMPLATE_PATH = settings.DEFAULT_TEMPLATE_PATH


def create_blank_excel(path: Path) -> None:
    """
    Copy the repo template to path.

    The template (data/Expenses_Template.xlsx) preserves the full sheet
    structure, formulas, styling, and data validations of the production
    workbook — but contains no personal data.  Using it as the base means
    the Dashboard SUMIFS, Monthly Summary layout, and all conditional
    formatting are available immediately without needing to be rebuilt
    from scratch in Python.

    Falls back to a minimal hand-built workbook if the template is missing
    (e.g. fresh clone before the template has been committed).
    """
    import shutil
    from datetime import datetime, timezone

    log.info("Creating blank Excel workbook at %s (template: %s)", path, TEMPLATE_PATH)
    if TEMPLATE_PATH.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(TEMPLATE_PATH, path)
        _repair_template_workbook(path)
        log.info("Created Excel workbook from template at %s", path)
        return

    # ── Fallback: minimal workbook (no formulas / styling) ────────────────────
    log.warning(
        "Template not found at %s — creating minimal fallback workbook. "
        "Run scripts/make_template.py to generate the template.",
        TEMPLATE_PATH,
    )
    from openpyxl import Workbook

    wb = Workbook()

    ws_md = wb.active
    ws_md.title = "MasterData"
    ws_md.append([
        "Date", "Year", "Month", "Value", "Type", "Category",
        "Person", "Description", "IsRecurring", "IsDone",
        "Currency", "Value (PLN)", "Date Modified (UTC)",
    ])

    ws_li = wb.create_sheet("Lists")
    _li_headers = [
        (1, header_of(ListsSchema, "months")),
        (2, header_of(ListsSchema, "txn_types")),
        (3, header_of(ListsSchema, "categories")),
        (4, header_of(ListsSchema, "budget_pln")),
        (5, header_of(ListsSchema, "persons")),
        (6, header_of(ListsSchema, "years")),
        (8, header_of(ListsSchema, "currency")),
        (9, header_of(ListsSchema, "rate_to_pln")),
    ]
    for _c, _h in _li_headers:
        ws_li.cell(1, _c, _h)

    months     = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
    txn_types  = ["Expense","Income","Savings"]
    categories = [
        "Groceries", "Transport", "Housing", "Utilities", "Healthcare",
        "Entertainment", "Travel", "Insurance", "Education", "Salary",
        "Freelance", "Rental", "Bonus", "Bank Deposit", "Investment",
        "Emergency Fund", "Other",
    ]
    cur_year   = datetime.now(timezone.utc).year
    years      = [cur_year - 1, cur_year, cur_year + 1, cur_year + 2]
    currencies = [("PLN", 1.0), ("EUR", 4.28), ("USD", 3.95), ("GBP", 5.05), ("CHF", 4.45)]

    for i, v in enumerate(months,     2): ws_li.cell(i, 1, v)
    for i, v in enumerate(txn_types,  2): ws_li.cell(i, 2, v)
    for i, v in enumerate(categories, 2): ws_li.cell(i, 3, v)
    # col 4 = Budget (PLN) — left blank; user fills in per-category limits
    for i, v in enumerate(years,      2): ws_li.cell(i, 6, v)
    for i, (code, rate) in enumerate(currencies, 2):
        ws_li.cell(i, 8, code)   # Currency
        ws_li.cell(i, 9, rate)   # Rate to PLN

    ws_db = wb.create_sheet("Dashboard")

    from cycles import ensure_cycles_sheet
    ensure_cycles_sheet(wb)

    try:
        from openpyxl.worksheet.datavalidation import DataValidation as _DV
        dv = _DV(type="list", formula1=f"Lists!$C$2:$C${1+len(categories)}", allow_blank=True)
        dv.sqref = "F2:F10000"
        ws_md.add_data_validation(dv)
    except Exception as _e:
        log.warning("Could not add category dropdown: %s", _e)

    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)
    log.info("Created fallback Excel workbook at %s", path)


def get_excel_path_for_reading() -> Path:
    """
    Return a local path to the Excel file, ready for pandas or openpyxl to open.

    Local backend: creates a blank workbook if the file does not exist, then
    returns LOCAL_XLSX_PATH.
    GCS / S3 backend: downloads to a temp file and returns that path.
    """
    backend = _active_backend()
    log.debug("get_excel_path_for_reading backend=%s", backend)
    if backend == "local":
        if not LOCAL_XLSX_PATH.exists():
            log.info("Local Excel not found at %s — creating blank workbook", LOCAL_XLSX_PATH)
            create_blank_excel(LOCAL_XLSX_PATH)
        log.info("Using local Excel workbook at %s", LOCAL_XLSX_PATH)
        return LOCAL_XLSX_PATH
    cleanup_temp_files()
    path = _download_to_temp_file()
    log.info("Using downloaded Excel workbook at %s", path)
    return path


class ExcelFileContext:
    """
    Context manager for read-write access to the Excel file.

    Use this whenever you need to modify the file (e.g. adding a transaction).
    On exit, the file is automatically uploaded back if using a remote backend.

    Usage:
        with ExcelFileContext() as excel_path:
            wb = load_workbook(excel_path)
            ws = wb["MasterData"]
            # make changes
            atomic_save(wb, excel_path)
        # upload to GCS/S3 happens here automatically

    Local backend: yields LOCAL_XLSX_PATH, does nothing on exit.
    Remote backend: downloads to temp file, yields temp path,
                    uploads on clean exit, deletes temp file.
    """

    def __init__(self):
        self._temp_path  = None
        self._is_remote  = _active_backend() != "local"

    def __enter__(self) -> Path:
        if self._is_remote:
            self._temp_path = _download_to_temp_file()
            return self._temp_path
        if not LOCAL_XLSX_PATH.exists():
            log.info("Excel file missing on local — creating from template: %s", LOCAL_XLSX_PATH)
            create_blank_excel(LOCAL_XLSX_PATH)
        return LOCAL_XLSX_PATH

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            if self._temp_path:
                try:
                    self._temp_path.unlink(missing_ok=True)
                except Exception:
                    log.exception("Failed to remove temp file %s", self._temp_path)
            return False
        if self._is_remote and self._temp_path:
            _upload_from_local_file(self._temp_path)
            try:
                self._temp_path.unlink(missing_ok=True)
            except Exception:
                log.exception("Failed to remove temp file after upload %s", self._temp_path)
        return False


# ── User preferences ──────────────────────────────────────────────────────────

def load_user_prefs() -> dict:
    """Load persisted per-user settings (display currency etc.) from JSON."""
    try:
        if USER_PREFS_PATH.exists():
            return json.loads(USER_PREFS_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        log.warning("Could not load user prefs: %s", e)
    return {}


def save_user_prefs(prefs: dict) -> None:
    """Persist per-user settings to JSON file alongside the Excel file."""
    try:
        USER_PREFS_PATH.parent.mkdir(parents=True, exist_ok=True)
        USER_PREFS_PATH.write_text(json.dumps(prefs, indent=2), encoding="utf-8")
    except Exception as e:
        log.warning("Could not save user prefs: %s", e)


# ── Budget loading ────────────────────────────────────────────────────────────

def load_budgets_from_excel(excel_path: Path) -> dict[str, float]:
    """
    Read monthly budget limits (in PLN) from the Lists sheet Budget column.

    Only categories that have a non-zero budget value are returned.
    Categories with no limit set are simply absent from the result dict.

    Returns {category_name: pln_amount}.
    Falls back to an empty dict if the sheet cannot be read.
    """
    try:
        lists = load_lists(excel_path)
        budgets = {cat: amt for cat, amt in lists.get("budgets", {}).items() if amt > 0}
        log.info("Loaded %d budget entries from Lists sheet", len(budgets))
        return budgets
    except Exception as error:
        log.warning("Could not load budgets from Lists: %s", error)
        return {}


# ── Reference lists ───────────────────────────────────────────────────────────

def load_lists(excel_path: Path) -> dict[str, list]:
    """
    Read all reference lists from the Lists sheet.

    Returns a dict with keys:
      months      — ['Jan', 'Feb', ..., 'Dec']
      txn_types   — ['Expense', 'Income', 'Savings']
      categories  — ['Groceries', 'Housing', ...]
      persons     — ['<YOUR_NAME>', '<FAMILY_MEMBER_1>', '<FAMILY_MEMBER_2>', '<FAMILY_MEMBER_3>']
      years       — [2024, 2025, 2026, 2027]

    Currency codes and rates are loaded separately by load_rates() since
    they include a rate column and need different handling.
    """
    from openpyxl import load_workbook

    try:
        wb = load_workbook(excel_path, data_only=True)
        ws = wb["Lists"]

        idx = col_indices(ws, ListsSchema)

        def read_col(field_name: str) -> list:
            c = idx.get(field_name)
            if c is None:
                log.warning("Lists sheet: column '%s' not found",
                            header_of(ListsSchema, field_name))
                return []
            values = []
            for row in range(2, ws.max_row + 1):
                val = ws.cell(row, c).value
                if val is None or (isinstance(val, str) and val.startswith("←")):
                    break
                values.append(val)
            return values

        result = {
            "months":     read_col("months"),
            "txn_types":  read_col("txn_types"),
            "categories": read_col("categories"),
            "persons":    read_col("persons"),
            "years":      read_col("years"),
        }

        # Build category→budget mapping
        cat_c = idx.get("categories")
        bud_c = idx.get("budget_pln")
        budgets: dict[str, float] = {}
        if cat_c and bud_c:
            for row in range(2, ws.max_row + 1):
                cat = ws.cell(row, cat_c).value
                bud = ws.cell(row, bud_c).value
                if cat is None:
                    break
                cat_str = str(cat).strip()
                if cat_str and bud is not None:
                    try:
                        budgets[cat_str] = float(bud)
                    except (TypeError, ValueError):
                        pass
        result["budgets"] = budgets

        return result

    except Exception as error:
        log.warning("Could not load Lists sheet: %s — using empty lists", error)
        return {
            "months": [], "txn_types": [], "categories": [],
            "persons": [], "years": [], "budgets": {},
        }


# ── Currency rate management ──────────────────────────────────────────────────

def update_currency_rates_in_excel(new_rates: dict[str, float]) -> None:
    """
    Write updated currency rates back to Lists sheet columns I (code) and J (rate).

    Only updates rows where the currency code already exists in the sheet.
    Does not add new currencies or remove existing ones.
    """
    from openpyxl import load_workbook

    with ExcelFileContext() as excel_path:
        wb = load_workbook(excel_path)
        ws = wb["Lists"]

        idx = col_indices(ws, ListsSchema)
        ccy_col  = idx.get("currency")
        rate_col = idx.get("rate_to_pln")

        if ccy_col is None or rate_col is None:
            log.warning("Currency or Rate column not found in Lists sheet — rates not updated")
            return

        for row in range(2, ws.max_row + 1):
            ccy = ws.cell(row, ccy_col).value
            if ccy and str(ccy).strip().upper() in new_rates:
                ws.cell(row, rate_col).value = round(new_rates[str(ccy).strip().upper()], 4)

        atomic_save(wb, excel_path)
        log.info("Updated %d currency rates in Lists sheet", len(new_rates))


def update_category_budget_in_excel(category: str, new_budget_pln: float) -> None:
    """
    Write a new monthly budget limit (in PLN) for one category into the Lists
    sheet Budget (PLN) column. Only updates the row whose Categories cell
    already matches `category` — never adds or removes a category row.
    """
    from openpyxl import load_workbook

    with ExcelFileContext() as excel_path:
        wb = load_workbook(excel_path)
        ws = wb["Lists"]

        idx      = col_indices(ws, ListsSchema)
        cat_col  = idx.get("categories")
        bud_col  = idx.get("budget_pln")

        if cat_col is None or bud_col is None:
            log.warning("Categories or Budget (PLN) column not found in Lists sheet — budget not updated")
            return

        for row in range(2, ws.max_row + 1):
            cat = ws.cell(row, cat_col).value
            if cat and str(cat).strip() == category:
                ws.cell(row, bud_col).value = round(new_budget_pln, 2)
                break
        else:
            log.warning("Category '%s' not found in Lists sheet — budget not updated", category)
            return

        atomic_save(wb, excel_path)
        log.info("Updated budget for category '%s' to %.2f PLN", category, new_budget_pln)


# ── Transaction management ────────────────────────────────────────────────────

def get_recent_transactions(excel_path: Path, n: int = 5) -> list[dict]:
    """
    Return the last N data rows from MasterData with their Excel row indices.

    Each dict includes all column values plus '_row_idx' (1-based Excel row number).
    Used by the /delete command so it knows which row to remove.
    """
    from openpyxl import load_workbook

    wb      = load_workbook(excel_path, data_only=True)
    ws      = wb["MasterData"]
    headers = [ws.cell(1, c).value for c in range(1, ws.max_column + 1)]
    rows    = []

    for row_idx in range(2, ws.max_row + 1):
        row_data = {headers[c]: ws.cell(row_idx, c + 1).value
                    for c in range(len(headers))}
        if row_data.get("Value") is not None:
            row_data["_row_idx"] = row_idx
            rows.append(row_data)

    return rows[-n:] if len(rows) > n else rows


def append_transactions_batch(transactions: list) -> None:
    """
    Write multiple Transaction rows in a single open/save/upload cycle.

    Use this instead of calling append_transaction_row N times when you have
    multiple rows ready at once (e.g. bulk import from a receipt image).
    """
    from openpyxl import load_workbook
    from datetime import datetime, timezone

    if not transactions:
        return

    from excel_schema import find_next_data_row, lists_currency_range, write_transaction_row

    with ExcelFileContext() as excel_path:
        wb = load_workbook(excel_path)
        ws = wb["MasterData"]

        lu_range = lists_currency_range(wb)
        r = find_next_data_row(ws)
        for transaction in transactions:
            write_transaction_row(ws, r, transaction.to_row(), lu_range)
            r += 1

        atomic_save(wb, excel_path)
        log.info("Batch-appended %d transactions to MasterData", len(transactions))


def delete_transaction_row(row_idx: int, expected: dict | None = None) -> None:
    """
    Delete a single row from MasterData by its 1-based Excel row index.

    Shifts all rows below up by one. Uploads to remote storage on exit.

    If `expected` (a snapshot of Date/Value/Description captured when the
    user picked the row) is given, the row is re-verified under the write
    lock before deleting — protects against a stale row index if another
    delete/edit shifted rows in the meantime. Raises RowMovedError if the
    row no longer matches.
    """
    from openpyxl import load_workbook

    with ExcelFileContext() as excel_path:
        wb = load_workbook(excel_path)
        ws = wb["MasterData"]
        if expected is not None:
            headers = {ws.cell(1, c).value: c for c in range(1, ws.max_column + 1)}
            if not _row_matches_snapshot(ws, headers, row_idx, expected):
                raise RowMovedError(
                    f"Row {row_idx} no longer matches the selected transaction — it may have moved."
                )
        ws.delete_rows(row_idx)
        atomic_save(wb, excel_path)
        log.info("Deleted MasterData row %d", row_idx)


def update_transaction_field(row_idx: int, field: str, value, expected: dict | None = None) -> None:
    """
    Update a single field of a MasterData row.

    If `expected` is given, the row is re-verified under the write lock
    before applying the change (see delete_transaction_row). Raises
    RowMovedError if the row no longer matches.
    """
    from openpyxl import load_workbook

    with ExcelFileContext() as excel_path:
        wb = load_workbook(excel_path)
        ws = wb["MasterData"]
        headers = {ws.cell(1, c).value: c for c in range(1, ws.max_column + 1)}
        if expected is not None and not _row_matches_snapshot(ws, headers, row_idx, expected):
            raise RowMovedError(
                f"Row {row_idx} no longer matches the selected transaction — it may have moved."
            )
        col_idx = headers.get(field)
        if col_idx is None:
            raise ValueError(f"Column '{field}' not found")
        ws.cell(row_idx, col_idx, value)
        atomic_save(wb, excel_path)
        log.info("Updated MasterData row %d column '%s'", row_idx, field)

