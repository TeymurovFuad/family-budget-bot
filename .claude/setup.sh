#!/usr/bin/env bash
# setup.sh — run after cloning the config template repo to ~/.ai-memory
# If the repo is at a different path, it re-clones to the correct location.

set -euo pipefail

REPO_URL="https://github.com/YOUR_USERNAME/ai-memory.git"
CANONICAL="$HOME/.ai-memory"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# If running from outside the canonical location, re-clone there
if [ "$SCRIPT_DIR" != "$CANONICAL" ]; then
  echo "  Repo is at $SCRIPT_DIR — canonical location is $CANONICAL"
  if [ -d "$CANONICAL/.git" ]; then
    echo "  Pulling latest at canonical location..."
    git -C "$CANONICAL" pull --quiet
  else
    echo "  Cloning to $CANONICAL..."
    git clone "$REPO_URL" "$CANONICAL" --quiet
  fi
  exec bash "$CANONICAL/setup.sh"
  exit
fi

echo "Config template ready at $CANONICAL"
echo ""
echo "Per-project setup:"
echo "  cd /path/to/your/project"
echo "  /memory init"
echo ""
echo "This copies all config (agents, commands, memories, corrections.md)"
echo "into .claude/ within your project repo."
echo ""
echo "Done."
