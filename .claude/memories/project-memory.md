# Project — Memory

Read at session start. Apply silently.

## Project overview
<!-- 2026-06-16 -->
- Personal household finance Telegram bot — reads/writes Expenses_Improved.xlsx.
- Stack: Python 3.12, python-telegram-bot v21, pandas, openpyxl, Pydantic v2, APScheduler, httpx, Docker.
- Files: bot.py (polling), scheduled_report.py (GitHub Actions one-shot), file_storage.py (storage abstraction), models.py (Pydantic DTOs).
- Storage: local / GCS / S3-compatible via STORAGE_BACKEND env var.
- Hosting: any always-on machine (Oracle Cloud Free Tier, phone via Termux, VPS) + object storage + GitHub Actions. $0/month possible.

## Excel structure
<!-- 2026-07-21 (supersedes 2026-06-16 layout) -->
- Column positions are NEVER hardcoded — excel_schema.py (MasterDataSchema/ListsSchema DTOs,
  header-name lookup) is the single source of truth; write_transaction_row is the one row writer.
- Lists sheet: A Months, B TxnTypes, C Categories, D Budget (PLN), E Persons, F Years,
  H Currency, I Rate to PLN, M/N/O Goal Name/Alloc %/Goal (PLN).
- MasterData: A Date, B Year, C Month, D Value, E Type, F Category, G Person, H Description,
  I IsRecurring, J IsDone, K Currency, L Value (PLN) formula, M Date Modified (UTC).
- Category "Gifts & Shopping" was renamed to "Shopping" (2026-07-21, scripts/rename_category.py).
- Dropdown validations are static ranges — the writer extends them on every append
  (extend_validation_ranges); delete_rows shrinks them, creation path re-extends.
- All PLN aggregations use _pln column — never sum raw Value (mixed currencies).

## Runtime environment
<!-- 2026-07-21 -->
- Bot runs on a separate always-on machine; this repo checkout is the dev machine.
- The live Excel is NOT in the repo: the bot machine's .env sets XLSX_PATH to a local file outside the repo.
- .env via settings.py is the single config source — scripts and bot all resolve paths through settings;
  relative paths anchor to PROJECT_ROOT, never cwd.
- DeepSeek tokens are PAID — minimize API calls in designs and debugging; live-API verification
  budgets are ~20 requests; prefer offline tests with mocked _chat.
- Maintenance scripts (scripts/audit_masterdata.py, fix_import_errors.py, fix_validation_ranges.py,
  rename_category.py) run on the bot machine against the live file; each writes a .bak first.
