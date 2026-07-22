#!/usr/bin/env bash
# setup.sh — one-command bootstrap for budget-bot (Linux/macOS).
# Windows: run `python scripts\setup_bot.py` instead.
set -euo pipefail

cd "$(dirname "$0")"

if ! command -v python3 >/dev/null 2>&1; then
    echo "ERROR: python3 not found. Install Python 3.12+ first." >&2
    exit 1
fi

exec python3 scripts/setup_bot.py "$@"
