"""
tests/test_auth_config.py — Auth fail-closed behavior for config.py / settings.py.

config.py raises RuntimeError at IMPORT time when ALLOWED_TELEGRAM_IDS is empty
and ALLOW_ALL_USERS is not explicitly set to "1". Because that check runs at
module import, each scenario is exercised in a fresh subprocess so we don't
fight Python's module cache or leak state between tests.
"""

import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent

_IMPORT_CONFIG_SNIPPET = "import config"


def _run(env_overrides: dict[str, str]) -> subprocess.CompletedProcess:
    env = {
        "PATH": __import__("os").environ.get("PATH", ""),
        "SYSTEMROOT": __import__("os").environ.get("SYSTEMROOT", ""),
        "TELEGRAM_BOT_TOKEN": "dummy",
        "STORAGE_BACKEND": "local",
    }
    env.update(env_overrides)
    return subprocess.run(
        [sys.executable, "-c", _IMPORT_CONFIG_SNIPPET],
        cwd=str(PROJECT_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_empty_allowed_ids_without_allow_all_fails_closed():
    """No ALLOWED_TELEGRAM_IDS and no ALLOW_ALL_USERS → startup must fail."""
    result = _run({"ALLOWED_TELEGRAM_IDS": ""})
    assert result.returncode != 0
    assert "RuntimeError" in result.stderr
    assert "ALLOWED_TELEGRAM_IDS" in result.stderr
    assert "ALLOW_ALL_USERS" in result.stderr


def test_empty_allowed_ids_with_allow_all_opts_in():
    """ALLOW_ALL_USERS=1 explicitly opts into the open-bot behavior."""
    result = _run({"ALLOWED_TELEGRAM_IDS": "", "ALLOW_ALL_USERS": "1"})
    assert result.returncode == 0, result.stderr
    assert "bot is open to ALL users" in result.stderr


def test_non_empty_allowed_ids_unaffected():
    """Normal configuration (non-empty ALLOWED_TELEGRAM_IDS) starts cleanly,
    regardless of ALLOW_ALL_USERS."""
    result = _run({"ALLOWED_TELEGRAM_IDS": "123,456"})
    assert result.returncode == 0, result.stderr
    assert "bot is open to ALL users" not in result.stderr
