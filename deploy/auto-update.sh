#!/usr/bin/env bash
# auto-update.sh — pull-and-restart the bot (and the web UI, if installed)
# only when the remote branch moved. Runs from a systemd timer (see
# budget-bot-update.timer). Safe to run manually.
set -euo pipefail

REPO_DIR="${REPO_DIR:-/home/ubuntu/budget-bot}"
SERVICE="${SERVICE:-budget-bot}"
WEB_SERVICE="${WEB_SERVICE:-budget-web}"
SYNC_SERVICE="${SYNC_SERVICE:-budget-excel-sync}"

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

# The web UI is optional — only restart it if it's enabled on this host
# (setups without the web UI never enabled budget-web.service). A restart
# failure here must never abort the script or block notify_update() below —
# git pull already succeeded, and the next timer run would short-circuit at
# the LOCAL=REMOTE check above, so a hard failure here would be permanent.

if systemctl is-enabled --quiet "${WEB_SERVICE}.service" 2>/dev/null; then
    if sudo systemctl restart "$WEB_SERVICE"; then
        echo "Also restarted $WEB_SERVICE"
    else
        echo "auto-update: failed to restart $WEB_SERVICE, continuing"
    fi
fi

# Re-export SQLite → Excel immediately after every pull so the file stays fresh.
# daemon-reload picks up any changes to the .service/.timer unit files from the pull.
# systemctl start on a oneshot runs it once and exits — the scheduled timer continues
# independently. Failure here is non-fatal: the next timer run will cover it.
sudo systemctl daemon-reload
if sudo systemctl start "${SYNC_SERVICE}.service"; then
    echo "Excel export triggered (${SYNC_SERVICE}.service)"
else
    echo "auto-update: Excel export failed, continuing (timer will retry)"
fi

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
