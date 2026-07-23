<!--
PR TITLE RULE — read before typing the title above.

MERGE THIS PR WITH "SQUASH AND MERGE" — never "Create a merge commit" or
"Rebase and merge". GitHub turns your PR title into the squash commit's
subject line, appending " (#<PR number>)" automatically — don't add the
number yourself.

The bot's auto-update script posts a Telegram message to the owner after
every deploy, parsed directly from that squash commit subject (see
deploy/auto-update.sh). Your title becomes user-facing changelog text, not
just a git log entry.

Write it as a plain-language sentence a non-technical family member would
understand — the user-visible outcome, not the internal change.

  Bad:  "refactor: extract validator"
  Bad:  "fix: bug in bulk_conv.py"
  Bad:  "Add /export command (#12)"          (don't add the PR number — GitHub does)
  Good: "Prevent typo'd categories from breaking the Dashboard"
  Good: "Add a command to download your Excel workbook via Telegram"

Conventional-commit prefixes (feat:/fix:/refactor:) are fine in individual
COMMIT messages — this rule is about the PR TITLE specifically.
-->

## Summary

## Test plan
