"""
storage_backends.py — physical storage layer for the Excel workbook.

Split out of file_storage.py (which remains the public facade). This module
owns everything about WHERE the workbook lives and how bytes move:

  - backend selection (local / GCS / S3) with explicit-override semantics
  - crash-safe local saves (atomic_save)
  - temp-file lifecycle for remote downloads
  - download / upload with retry
  - lost-update protection for remote backends (GCS generation preconditions)
  - ExcelFileContext, the read-write context manager used by all writers

Configuration is read lazily through the file_storage module attributes
(LOCAL_XLSX_PATH, STORAGE_BACKEND, GCS_*, S3_*) so that existing tests and
callers that monkeypatch `file_storage.<NAME>` keep working unchanged.
"""

import json
import tempfile
import time
from pathlib import Path

import settings
from logger import get_logger

log = get_logger(__name__)


def _config():
    """Late-bound config source — file_storage re-exports settings values and
    tests monkeypatch them there, so read them at call time, not import time."""
    import file_storage
    return file_storage


class ConcurrentModificationError(Exception):
    """
    Raised when a remote upload hits a precondition failure: the object
    changed between our download and upload (another writer won the race).
    The local modification was NOT uploaded — callers should re-queue or
    retry their whole read-modify-write cycle.
    """


# On Windows, antivirus / search indexers can hold a just-written file open
# for a few milliseconds, making os.replace fail with a transient
# PermissionError (WinError 5). Retry briefly before giving up.
_REPLACE_RETRIES = 5
_REPLACE_RETRY_DELAY_SECONDS = 0.1


def _replace_with_retry(src, dst) -> None:
    import os

    for attempt in range(1, _REPLACE_RETRIES + 1):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if attempt == _REPLACE_RETRIES:
                raise
            log.warning("os.replace %s -> %s locked (attempt %d/%d), retrying",
                        src, dst, attempt, _REPLACE_RETRIES)
            time.sleep(_REPLACE_RETRY_DELAY_SECONDS * attempt)


_temp_files: set[Path] = set()


def atomic_save(wb, path) -> None:
    """
    Crash-safe workbook save: write to a sibling temp file, keep a rolling
    .bak of the previous version, then atomically replace the target.
    A crash mid-save can no longer corrupt the only copy of the data.
    """
    import shutil

    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    try:
        wb.save(tmp)
        # Skip the rolling .bak for temp downloads (GCS/S3 backends) — the
        # remote object is the durable copy, and a .bak next to a
        # NamedTemporaryFile would never be cleaned up.
        if path.exists() and path not in _temp_files:
            try:
                shutil.copy2(path, path.with_name(path.name + ".bak"))
            except Exception as e:
                log.warning("Could not write backup for %s: %s", path, e)
        _replace_with_retry(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def cleanup_temp_files() -> None:
    for p in list(_temp_files):
        try:
            p.unlink(missing_ok=True)
            _temp_files.discard(p)
        except Exception as e:
            log.warning("Could not delete temp file %s: %s", p, e)


def _active_backend() -> str:
    cfg = _config()
    backend = (cfg.STORAGE_BACKEND or "local").lower()
    if getattr(settings, "STORAGE_BACKEND_EXPLICIT", False):
        # An explicitly set STORAGE_BACKEND always wins — a stray
        # GCS_BUCKET_NAME/S3_BUCKET_NAME left in the environment must not
        # silently flip the bot onto a remote backend.
        return backend if backend in ("local", "gcs", "s3") else "local"
    if backend == "gcs" or cfg.GCS_BUCKET_NAME:
        return "gcs"
    if backend == "s3" or cfg.S3_BUCKET_NAME:
        return "s3"
    return "local"


def _gcs_client():
    from google.cloud import storage as gcs
    from google.oauth2 import service_account
    cfg = _config()
    if cfg.GCS_KEY_JSON:
        key_data    = json.loads(cfg.GCS_KEY_JSON)
        credentials = service_account.Credentials.from_service_account_info(key_data)
        return gcs.Client(credentials=credentials, project=key_data.get("project_id"))
    return gcs.Client()


def _s3_client():
    import boto3
    cfg = _config()
    kwargs = dict(
        region_name          = cfg.S3_REGION,
        aws_access_key_id    = cfg.S3_ACCESS_KEY or None,
        aws_secret_access_key= cfg.S3_SECRET_KEY or None,
    )
    if cfg.S3_ENDPOINT_URL:
        kwargs["endpoint_url"] = cfg.S3_ENDPOINT_URL
    return boto3.client("s3", **kwargs)


def _download_to_temp_file() -> tuple[Path, int | None]:
    """
    Download the remote workbook to a local temp file.

    Returns (path, generation): `generation` is the GCS object generation at
    download time — used later as an upload precondition so a concurrent
    write can't be blindly overwritten (lost-update protection). It is None
    for S3 and for anything we could not determine.
    """
    cfg        = _config()
    backend    = _active_backend()
    temp_file  = tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False)
    temp_path  = Path(temp_file.name)
    temp_file.close()
    _temp_files.add(temp_path)
    generation: int | None = None

    log.info("Downloading Excel from backend=%s", backend)
    if backend == "gcs":
        client = _gcs_client()
        blob = client.bucket(cfg.GCS_BUCKET_NAME).blob(cfg.GCS_OBJECT_NAME)
        blob.download_to_filename(str(temp_path))
        generation = getattr(blob, "generation", None)
        if generation is None:
            try:
                blob.reload()
                generation = blob.generation
            except Exception as e:
                log.warning("Could not read GCS generation (lost-update guard disabled): %s", e)
        log.info("Downloaded from GCS: gs://%s/%s (generation=%s)",
                 cfg.GCS_BUCKET_NAME, cfg.GCS_OBJECT_NAME, generation)

    elif backend == "s3":
        _s3_client().download_file(cfg.S3_BUCKET_NAME, cfg.S3_OBJECT_NAME, str(temp_path))
        # TODO(lost-update/S3): capture the ETag from head_object here and
        # upload via put_object with an If-Match precondition. Plain S3 only
        # honours If-Match on newer API versions and some S3-compatible
        # stores ignore it entirely, so this is intentionally left as a
        # documented gap — GCS (the recommended remote backend) is protected.
        log.info("Downloaded from S3: s3://%s/%s", cfg.S3_BUCKET_NAME, cfg.S3_OBJECT_NAME)

    return temp_path, generation


def _upload_from_local_file(local_path: Path, generation: int | None = None) -> None:
    """
    Upload to remote storage with exponential backoff retry (3 attempts).

    If `generation` is given (GCS), the upload carries an
    if_generation_match precondition: it fails with
    ConcurrentModificationError instead of overwriting an object that was
    modified by another writer since our download.
    """
    cfg          = _config()
    backend      = _active_backend()
    max_attempts = 3

    for attempt in range(1, max_attempts + 1):
        try:
            if backend == "gcs":
                client = _gcs_client()
                blob = client.bucket(cfg.GCS_BUCKET_NAME).blob(cfg.GCS_OBJECT_NAME)
                if generation is not None:
                    blob.upload_from_filename(str(local_path), if_generation_match=generation)
                else:
                    blob.upload_from_filename(str(local_path))
                log.info("Uploaded to GCS: gs://%s/%s", cfg.GCS_BUCKET_NAME, cfg.GCS_OBJECT_NAME)
            elif backend == "s3":
                _s3_client().upload_file(str(local_path), cfg.S3_BUCKET_NAME, cfg.S3_OBJECT_NAME)
                log.info("Uploaded to S3: s3://%s/%s", cfg.S3_BUCKET_NAME, cfg.S3_OBJECT_NAME)
            return
        except Exception as e:
            if type(e).__name__ == "PreconditionFailed":
                # Retrying the same upload can never succeed — the object
                # generation moved on. Surface it as a conflict so callers
                # (recovery queue) can re-queue the operation.
                log.error(
                    "Remote object changed since download (generation %s) — "
                    "refusing to overwrite: %s", generation, e,
                )
                raise ConcurrentModificationError(
                    f"Remote workbook was modified concurrently (expected generation {generation})"
                ) from e
            if attempt == max_attempts:
                log.error("Upload failed after %d attempts — transaction may be lost: %s", max_attempts, e)
                raise
            wait = 2 ** attempt
            log.warning("Upload attempt %d/%d failed, retrying in %ds: %s", attempt, max_attempts, wait, e)
            time.sleep(wait)


def get_excel_path_for_reading() -> Path:
    """
    Return a local path to the Excel file, ready for pandas or openpyxl to open.

    Local backend: creates a blank workbook if the file does not exist, then
    returns LOCAL_XLSX_PATH.
    GCS / S3 backend: downloads to a temp file and returns that path.
    """
    cfg = _config()
    backend = _active_backend()
    log.debug("get_excel_path_for_reading backend=%s", backend)
    if backend == "local":
        if not cfg.LOCAL_XLSX_PATH.exists():
            log.info("Local Excel not found at %s — creating blank workbook", cfg.LOCAL_XLSX_PATH)
            cfg.create_blank_excel(cfg.LOCAL_XLSX_PATH)
        log.info("Using local Excel workbook at %s", cfg.LOCAL_XLSX_PATH)
        return cfg.LOCAL_XLSX_PATH
    cleanup_temp_files()
    path, _generation = _download_to_temp_file()
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
    Remote backend: downloads to temp file, yields temp path, uploads on
                    clean exit (with a generation precondition on GCS so a
                    concurrent write raises ConcurrentModificationError
                    instead of being silently overwritten), deletes temp file.
    """

    def __init__(self):
        self._temp_path  = None
        self._generation = None
        self._is_remote  = _active_backend() != "local"

    def __enter__(self) -> Path:
        cfg = _config()
        if self._is_remote:
            self._temp_path, self._generation = _download_to_temp_file()
            return self._temp_path
        if not cfg.LOCAL_XLSX_PATH.exists():
            log.info("Excel file missing on local — creating from template: %s", cfg.LOCAL_XLSX_PATH)
            cfg.create_blank_excel(cfg.LOCAL_XLSX_PATH)
        return cfg.LOCAL_XLSX_PATH

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            if self._temp_path:
                try:
                    self._temp_path.unlink(missing_ok=True)
                except Exception:
                    log.exception("Failed to remove temp file %s", self._temp_path)
            return False
        if self._is_remote and self._temp_path:
            try:
                _upload_from_local_file(self._temp_path, generation=self._generation)
            finally:
                try:
                    self._temp_path.unlink(missing_ok=True)
                except Exception:
                    log.exception("Failed to remove temp file after upload %s", self._temp_path)
        return False
