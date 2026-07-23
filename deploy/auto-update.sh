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

notify_update() {
    local env_file="$REPO_DIR/.env"
    [ -f "$env_file" ] || { echo "auto-update: no .env found, skipping update notification"; return 0; }

    local strip_quotes='s/^["'"'"']//; s/["'"'"']$//'

    local token
    token=$(grep -E '^TELEGRAM_BOT_TOKEN=' "$env_file" | head -n1 | cut -d= -f2- | sed -e "$strip_quotes")
    local ids_raw
    ids_raw=$(grep -E '^ALLOWED_TELEGRAM_IDS=' "$env_file" | head -n1 | cut -d= -f2- | sed -e "$strip_quotes")
    local chat_id
    chat_id=$(echo "$ids_raw" | cut -d, -f1 | tr -d '[:space:]')

    if [ -z "$token" ] || [ -z "$chat_id" ]; then
        echo "auto-update: TELEGRAM_BOT_TOKEN or ALLOWED_TELEGRAM_IDS missing in .env, skipping update notification"
        return 0
    fi

    # PR titles: this repo uses squash-merge-only (protected master), so every PR lands
    # as a single-parent commit whose subject GitHub formats as "<PR title> (#<PR number>)".
    # One commit = one subject line = one title, so we just read subjects (no --merges,
    # no multi-line body parsing, no blank-line heuristics needed). We still filter to
    # subjects ending in "(#N)" so any stray non-squash commit in the range is skipped
    # rather than mis-treated as a title.
    local titles
    titles=$(git log "$LOCAL..$REMOTE" --format='%s' | \
        grep -E '\(#[0-9]+\)$' | \
        sed -E 's/ \(#[0-9]+\)$//') || true

    local short_local short_remote header text
    short_local=$(git rev-parse --short "$LOCAL")
    short_remote=$(git rev-parse --short "$REMOTE")
    header="🔄 Bot updated (commit ${short_local} -> ${short_remote})"

    if [ -n "$titles" ]; then
        text=$(printf '%s\n\nNew in this update:\n' "$header")
        while IFS= read -r title; do
            [ -n "$title" ] && text+=$(printf '\n- %s' "$title")
        done <<< "$titles"
    else
        text="$header"
    fi

    curl -s --connect-timeout 5 --max-time 10 -X POST "https://api.telegram.org/bot${token}/sendMessage" \
        --data-urlencode "chat_id=${chat_id}" \
        --data-urlencode "text=${text}" \
        > /dev/null || echo "auto-update: failed to send Telegram update notification"
}

notify_update || echo "auto-update: update notification step failed, continuing (update already applied)"
