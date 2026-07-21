#!/usr/bin/env bash
# auto-update.sh — pull-and-restart the bot only when the remote branch moved.
# Runs from a systemd timer (see budget-bot-update.timer). Safe to run manually.
set -euo pipefail

REPO_DIR="${REPO_DIR:-/home/ubuntu/budget-bot}"
SERVICE="${SERVICE:-budget-bot}"

cd "$REPO_DIR"

BRANCH=$(git rev-parse --abbrev-ref HEAD)
git fetch origin "$BRANCH" --quiet

LOCAL=$(git rev-parse HEAD)
REMOTE=$(git rev-parse "origin/$BRANCH")

if [ "$LOCAL" = "$REMOTE" ]; then
    exit 0  # nothing new
fi

echo "Updating $BRANCH: $LOCAL -> $REMOTE"
git pull --ff-only origin "$BRANCH"
venv/bin/pip install -r requirements.txt --quiet
sudo systemctl restart "$SERVICE"
echo "Deployed $(git rev-parse --short HEAD) and restarted $SERVICE"
