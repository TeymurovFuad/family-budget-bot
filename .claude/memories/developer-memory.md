# Developer — Memory

Read at session start. Apply silently.

## Branch and handoff workflow
<!-- 2026-05-13 -->
- All work goes through a PR; never merge your own PR.

<!-- 2026-05-15 -->
- Hand off work as unstaged changes via `git diff <base> claude/work | git -C "<checkout>" apply` — never commit directly to user's branch.

<!-- 2026-05-22 -->
- Never checkout, stash, or modify the user's active branch or working tree — all commits go on isolated branches (worktrees or claude/work), never directly on user branches.

## PR process
<!-- 2026-05-14 -->
- Handoff must explicitly list ALL UI pages and API surfaces that read from entities modified by the fix — not just changed files.
- After opening a PR, immediately trigger /reviewer — never pause or wait for user confirmation.

## Playwright API
<!-- 2026-05-25 -->
- `Page.ScreenshotAsync(new PageScreenshotOptions { Path = "..." })` returns `byte[]` — path is optional; use the return value, never re-read from disk.

## .NET configuration
<!-- 2026-05-25 -->
- `AddEnvironmentVariables()` binds `Section__Key` (double underscore); flat names like `RP_URL` do not map to nested config sections.

## Code comments policy
<!-- 2026-05-16 -->
- Never add XML doc comments or descriptive block comments to code (e.g. no /// <summary>).
- Code that needs a comment to be understood is poorly designed — redesign it instead.
- Comments are an edge case: only add a brief inline note for genuine workarounds or non-obvious complex logic (e.g. // workaround: X because Y).

## Budget-bot project
<!-- 2026-06-16 -->
- All PLN aggregations use `_pln` column — never sum raw `Value` (mixed currencies).
- Column positions detected from headers dynamically — never hardcode column indices.
- Storage abstraction in file_storage.py: always use ExcelFileContext for writes, get_excel_path_for_reading for reads.
- Upload retry (3 attempts, exponential backoff) built into _upload_from_local_file.
- User currency prefs persist to data/user_prefs.json — load on startup, save on /setcurrency.
- Duplicate detection: _last_saved dict keyed by user_id; check before every append_transaction call.
- Input sanitization: descriptions starting with =, +, -, @ prefixed with ' to prevent Excel formula injection.
- /add conversation has 9 steps including ADD_DATE (state 8) between ADD_PERSON and ADD_DESC.
<!-- 2026-07-21 -->
- AI output is never trusted: _normalize_parsed_rows enforces Lists (category fuzzy-map, person
  whitelist, type whitelist) after every bulk parse and reports each correction to the user.
- Large statements are chunked at date headers (~5KB) before DeepSeek; truncated responses are
  salvaged object-by-object (_salvage_json_objects). max_tokens=8192, client timeout 120s.
- All workbook writes go through atomic_save (tmp + os.replace + rolling .bak) — never wb.save on the live path.
- Every write-path Telegram handler must carry @auth — /bulk /edit /delete were once missed (309df08).
- Named constants with units for all durations/sizes (BULK_REVIEW_TIMEOUT_SECONDS = 30 * 60) — no bare numbers.
- Report every silent decision to the user in one brief line (corrections, skips, merges, timeouts).
- Copilot/AI review findings are suggestions, not obligations — check against design intent and
  documented tests before fixing; defer disputed ones to BACKLOG.md with reasoning.
- BACKLOG.md in repo root is the ticket store — new findings go there first, grouped by planned PR.

## Excel Lists sheet -- column layout
<!-- 2026-06-29 -->
| Column | Content |
|--------|---------|
| A | Month names (Jan ... Dec) |
| B | Transaction Type (Expense, Income, Savings) |
| C | Category -- unified list shared by all transaction types |
| D | Person |
| E | Year |
| F | Empty -- not used |
| G | Empty -- not used |
| I | Currency code (e.g. PLN, EUR, USD) |
| J | Exchange rate to PLN |

## No hardcoded data rule
<!-- 2026-06-29 -->
- Never hardcode categories, persons, months, or years in Python. All lists come from Excel (Lists sheet). Read them dynamically at runtime.

## Test coverage rule
<!-- 2026-06-29 -->
- Every new public function or handler must have at least one test.

## Bot restart policy
<!-- 2026-06-29 -->
- Excel changes (Lists sheet values, categories, currencies, rates) take effect on the next bot interaction -- no restart needed.
- Python code changes require a bot restart.
