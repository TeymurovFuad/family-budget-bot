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

    local token
    token=$(grep -E '^TELEGRAM_BOT_TOKEN=' "$env_file" | head -n1 | cut -d= -f2-)
    local ids_raw
    ids_raw=$(grep -E '^ALLOWED_TELEGRAM_IDS=' "$env_file" | head -n1 | cut -d= -f2-)
    local chat_id
    chat_id=$(echo "$ids_raw" | cut -d, -f1 | tr -d '[:space:]')

    if [ -z "$token" ] || [ -z "$chat_id" ]; then
        echo "auto-update: TELEGRAM_BOT_TOKEN or ALLOWED_TELEGRAM_IDS missing in .env, skipping update notification"
        return 0
    fi

    # PR titles = first non-empty line of each merge commit's body in the updated range.
    local titles
    titles=$(git log "$LOCAL..$REMOTE" --merges --format='%b' | awk 'BEGIN{p=1} /^$/{p=1;next} p{print;p=0}')

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

    curl -s -X POST "https://api.telegram.org/bot${token}/sendMessage" \
        --data-urlencode "chat_id=${chat_id}" \
        --data-urlencode "text=${text}" \
        > /dev/null || echo "auto-update: failed to send Telegram update notification"
}

notify_update || echo "auto-update: update notification step failed, continuing (update already applied)"
