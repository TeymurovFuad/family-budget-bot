"""
test_repair_guard.py — tests for scripts/_repair_guard.py.

Regression: one-off maintenance scripts under scripts/ used to open the live
Excel file directly with openpyxl and plain wb.save(), with no coordination
with the bot's in-process write lock, and no atomic save. Worse, on gcs/s3
backends they'd silently edit a local file the bot never uploads. repair_guard()
refuses to run on a non-local backend and takes an exclusive lock file for the
duration of the script.
"""
import os
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import file_storage
import settings
from _repair_guard import repair_guard


def test_repair_guard_runs_on_local_backend(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "STORAGE_BACKEND", "local")
    monkeypatch.setattr(settings, "GCS_BUCKET_NAME", "")
    monkeypatch.setattr(settings, "S3_BUCKET_NAME", "")
    monkeypatch.setattr(file_storage, "STORAGE_BACKEND", "local")
    monkeypatch.setattr(file_storage, "GCS_BUCKET_NAME", "")
    monkeypatch.setattr(file_storage, "S3_BUCKET_NAME", "")

    lock_path = tmp_path / "test.repair.lock"
    ran = False
    with repair_guard(lock_path):
        ran = True
        assert lock_path.exists()  # lock held during the block
    assert ran
    assert not lock_path.exists()  # lock released on clean exit


def test_repair_guard_refuses_on_gcs_backend(tmp_path, monkeypatch):
    monkeypatch.setattr(file_storage, "STORAGE_BACKEND", "gcs")
    monkeypatch.setattr(file_storage, "GCS_BUCKET_NAME", "some-bucket")
    monkeypatch.setattr(file_storage, "S3_BUCKET_NAME", "")

    lock_path = tmp_path / "test.repair.lock"
    with pytest.raises(SystemExit):
        with repair_guard(lock_path):
            pytest.fail("should never enter the block on a non-local backend")
    assert not lock_path.exists()


def test_repair_guard_refuses_on_s3_backend(tmp_path, monkeypatch):
    monkeypatch.setattr(file_storage, "STORAGE_BACKEND", "s3")
    monkeypatch.setattr(file_storage, "GCS_BUCKET_NAME", "")
    monkeypatch.setattr(file_storage, "S3_BUCKET_NAME", "some-bucket")

    lock_path = tmp_path / "test.repair.lock"
    with pytest.raises(SystemExit):
        with repair_guard(lock_path):
            pytest.fail("should never enter the block on a non-local backend")


def test_repair_guard_refuses_when_lock_already_held(tmp_path, monkeypatch):
    monkeypatch.setattr(file_storage, "STORAGE_BACKEND", "local")
    monkeypatch.setattr(file_storage, "GCS_BUCKET_NAME", "")
    monkeypatch.setattr(file_storage, "S3_BUCKET_NAME", "")

    lock_path = tmp_path / "test.repair.lock"
    lock_path.write_text("locked")  # simulate another script already running

    with pytest.raises(SystemExit):
        with repair_guard(lock_path):
            pytest.fail("should never enter the block while the lock file exists")


def test_repair_guard_releases_lock_even_on_exception(tmp_path, monkeypatch):
    monkeypatch.setattr(file_storage, "STORAGE_BACKEND", "local")
    monkeypatch.setattr(file_storage, "GCS_BUCKET_NAME", "")
    monkeypatch.setattr(file_storage, "S3_BUCKET_NAME", "")

    lock_path = tmp_path / "test.repair.lock"
    with pytest.raises(RuntimeError):
        with repair_guard(lock_path):
            raise RuntimeError("boom mid-script")
    assert not lock_path.exists()
