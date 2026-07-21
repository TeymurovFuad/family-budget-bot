---
name: budget-analyst
description: >
  Personal finance analyst and coding assistant for <YOUR_NAME>'s household budget tracker.
  Activate on any mention of: budget, expenses, spending, savings, income, transactions,
  categories, Excel tracker, Telegram bot, scheduled reports, file_storage, models.py,
  bot.py, scheduled_report.py, deploy, Docker, GCS, S3, Oracle, Termux, or any question
  about the system architecture or code.
  Also activate for vague financial questions: "how are we doing", "did we overspend",
  "how much did we save", "what's our burn rate".
---

# Budget System — AI Skill

## Read before doing anything

1. **`.claude/MEMORY.md`** — every mistake made and corrected. Do not repeat them.
   Update it immediately when a new mistake is corrected.

2. This file — complete system reference.

---

## Agents

Four agents in `.claude/agents/`. Always use them for their job rather than doing it inline.

| Agent | File | When |
|---|---|---|
| Input Sanitizer | `agents/input-sanitizer.md` | Any data from outside — API, user text, CSV. Always before Transaction Writer. |
| Transaction Writer | `agents/transaction-writer.md` | Writing to MasterData. Only after Input Sanitizer returns clean/fixed. |
| Financial Analyst | `agents/financial-analyst.md` | Any analytical question — summaries, trends, budget vs actual. |
| Report Generator | `agents/report-generator.md` | Formatting for Telegram, GitHub Actions, or API. Always after Financial Analyst. |

**Transaction pipeline:** `raw input → Input Sanitizer → Transaction Writer → confirm`
**Report pipeline:** `Financial Analyst → Report Generator → deliver`

---

## Source files

```
budget_bot/
├── bot.py                      # Always-on Telegram bot — interactive commands
├── scheduled_report.py         # One-shot script — run by GitHub Actions on schedule
├── file_storage.py             # ALL file access goes through here — GCS / S3 / local
├── models.py                   # Pydantic DTOs — Transaction and AddTransactionState
├── .claude/
│   ├── SKILL.md                # This file
│   ├── MEMORY.md               # Mistakes log
│   └── agents/                 # Agent instruction files
├── .github/workflows/
│   ├── build-and-push.yml      # Builds Docker image on push → pushes to Docker Hub
│   ├── deploy.yml              # SSHes into server → pulls new image → restarts bot
│   ├── weekly-report.yml       # Cron: every Sunday 17:00 UTC
│   └── monthly-summary.yml     # Cron: 1st of month 07:00 UTC
├── Dockerfile
├── .dockerignore               # Blocks .env and data/*.xlsx from image
├── DOCUMENTATION.md            # Human-facing docs
└── README.md                   # Setup guide
```

---

## Architecture

```
Expenses_Improved.xlsx (in GCS / S3 / local disk)
        ↑ writes via ExcelFileContext
    bot.py (always-on, Telegram polling — phone or server)
        ↑ reads
    scheduled_report.py (GitHub Actions cron — reports only)
```

`file_storage.py` is the only place that knows where the file is.
`bot.py` and `scheduled_report.py` call `get_excel_path_for_reading()` and
`ExcelFileContext` — they don't know whether the file is local or remote.

---

## Pydantic models (models.py)

Two DTOs:

**`Transaction`** — a complete, validated transaction row ready to write.
- `value` must be positive — validated on construction
- `currency` normalised to uppercase on construction
- `year` and `month` are always derived from `date` — cannot be set manually
- `to_row()` → returns dict for `append_transaction()`

**`AddTransactionState`** — partial state during the /add conversation.
- All fields Optional — filled one step at a time
- `to_transaction()` → builds and validates a `Transaction` at confirmation step
- `is_ready_to_confirm()` → checks all required fields are present

Never pass raw dicts between bot steps. Always use these models.

---

## Storage backends (file_storage.py)

Selected by `STORAGE_BACKEND` env var. All three expose the same interface.

| Backend | Env var | Use case |
|---|---|---|
| `local` | `STORAGE_BACKEND=local` | Phone (Termux), Oracle VM, any server with local disk |
| `gcs` | `STORAGE_BACKEND=gcs` | Google Cloud Storage — free tier, recommended |
| `s3` | `STORAGE_BACKEND=s3` | Oracle Object Storage, Cloudflare R2, AWS S3 |

Key functions:
- `get_excel_path_for_reading()` — returns local Path (downloads from remote if needed)
- `ExcelFileContext` — context manager: download → modify → upload atomically
- `load_lists(path)` — reads all reference lists from Lists sheet (months, types, categories, persons, years)
- `load_budgets_from_excel(path)` — reads budget amounts from Dashboard col I (parses `=2100/$N$2` formulas)

**Critical:** `ExcelFileContext` must wrap the entire read-modify-save block. If you
save the file inside the `with` block, it uploads on exit. If you save outside, GCS
never gets the update.

---

## Data rules — nothing hardcoded

All domain values come from the Excel file at runtime. Nothing is hardcoded:

| Data | Source in Excel | How loaded |
|---|---|---|
| Month names | Lists col A | `load_lists()["months"]` |
| Transaction types | Lists col B | `load_lists()["txn_types"]` |
| Categories | Lists col C | `load_lists()["categories"]` |
| Family members | Lists col D | `load_lists()["persons"]` |
| Years | Lists col E | `load_lists()["years"]` |
| Currency codes + rates | Lists col G + H | `load_rates()` |
| Budget amounts | Dashboard col I | `load_budgets_from_excel()` |

If you add a category to the Lists sheet, the bot keyboard shows it automatically.
If you change a budget in the Dashboard, the bot uses the new amount on the next command.

---

## Excel workbook

### Sheets
| Sheet | Purpose |
|---|---|
| 📖 Guide | Documents every column with examples |
| Lists | Reference data for all dropdowns |
| MasterData | Every transaction, one row per entry |
| Monthly Summary | Auto-calculated monthly rollup |
| Dashboard | Interactive — Year / Month / Display Currency filters |

### MasterData columns (A–M)
| Col | Name | Who fills it |
|---|---|---|
| A | Date | User — only manual column |
| B | Year | Formula `=YEAR(A)` |
| C | Month | Formula `=CHOOSE(MONTH(A),"Jan",...)` |
| D | Value | User — amount in transaction's own currency |
| E | Type | Dropdown from Lists col B |
| F | Category | Dropdown from Lists col C |
| G | Person | Dropdown from Lists col D — blank = household |
| H | Description | Free text |
| I | IsRecurring | TRUE for fixed monthly costs |
| J | IsDone | TRUE = confirmed, FALSE = planned (excluded from totals) |
| K | Currency | Dropdown from Lists col G |
| L | Value (PLN) | Formula: `=IF(OR(K="",K="PLN"),D,D*VLOOKUP(K,Lists!$G$2:$H$20,2,0))` |
| M | Date Modified (UTC) | Circular formula — requires iterative calculation enabled |

### Date Modified formula
Requires: File → Options → Formulas → Enable Iterative Calculation → Max Iterations = 1.
Without this it shows 0. Mention this every time Date Modified is referenced.

### Column positions
Always detect from header names — never hardcode column numbers:
```python
headers = {ws.cell(1, c).value: c for c in range(1, ws.max_column + 2)}
col_index = headers.get("Currency", 11)
```

### Adding a column
After adding any column to MasterData, audit every Dashboard and Monthly Summary
formula for column letter references and update them all.

---

## Bot commands
| Command | What |
|---|---|
| `/summary` | This month: income / expenses / savings / net / savings rate |
| `/week` | Last 7 days by category |
| `/budget` | Budget vs actual all categories with progress bars |
| `/top` | Top 5 biggest expenses this month |
| `/savings` | Savings rate trend — last 6 months |
| `/report` | Full report: fixed vs variable, by category, by person |
| `/add` | 8-step transaction logger |
| `/setcurrency` | Switch display currency |

### /add conversation state
Uses `AddTransactionState` Pydantic model stored in `ctx.user_data["state"]`.
Steps: value → currency → type → category (Expense only) → person → description → recurring → confirm.
On confirm: `state.to_transaction()` → `append_transaction(transaction)`.

---

## Environment variables

| Variable | Required | What |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | ✅ | From @BotFather |
| `ALLOWED_TELEGRAM_IDS` | ✅ | Comma-separated Telegram user IDs (get from @userinfobot) |
| `STORAGE_BACKEND` | — | `local` / `gcs` / `s3`. Default: local |
| `XLSX_PATH` | local only | Path to Excel file on disk |
| `GCS_BUCKET_NAME` | gcs | Bucket name |
| `GCS_KEY_JSON` | gcs | Full contents of service account JSON key |
| `GCS_OBJECT_NAME` | — | Default: `Expenses_Improved.xlsx` |
| `S3_BUCKET_NAME` | s3 | Bucket name |
| `S3_ENDPOINT_URL` | s3 | Oracle: `https://<ns>.compat.objectstorage.<region>.oraclecloud.com` |
| `S3_ACCESS_KEY` | s3 | Access key |
| `S3_SECRET_KEY` | s3 | Secret key |
| `S3_REGION` | s3 | e.g. `eu-frankfurt-1` |
| `DISPLAY_CURRENCY` | — | Default: `PLN` |
| `TIMEZONE` | — | Default: `Europe/Warsaw` |

---

## Deployment

### GitHub Actions (scheduled reports — free)
- `weekly-report.yml` — every Sunday 17:00 UTC → weekly summary
- `monthly-summary.yml` — 1st of month 07:00 UTC → closed month report
- January 1st auto-detected in weekly workflow → sends yearly summary instead
- All storage secrets passed via GitHub Secrets
- Excel file never committed to repo — always in GCS/S3

### Docker auto-deploy
Push to `main` → `build-and-push.yml` builds image → `deploy.yml` SSHes into server → pulls + restarts.

GitHub Secrets needed for deploy:
- `DOCKER_USERNAME`, `DOCKER_TOKEN` — Docker Hub credentials
- `SERVER_HOST`, `SERVER_USER`, `SERVER_SSH_KEY` — SSH into the server

Env file lives on the server at `~/budget-bot.env` — never baked into image.
Excel file mounted as volume from `~/data/` — never baked into image.
`.dockerignore` blocks `.env` and `data/*.xlsx` from image.

### Phone (Termux) — free, zero config
```bash
pkg install python git tmux
git clone <repo> && cd budget-bot
pip install -r requirements.txt
cp .env.example .env && nano .env
tmux new -s bot
python bot.py
# Ctrl+B D to detach
```
Battery: Settings → Apps → Termux → Battery → Unrestricted.
See dontkillmyapp.com for phone-brand-specific steps.
Auto-start on reboot: install Termux:Boot from F-Droid, create `~/.termux/boot/start-bot.sh`.

### Oracle VM (free forever)
Use `STORAGE_BACKEND=local`. Systemd service for auto-restart.
Auto-deploy: add `deploy.yml` workflow with SSH action.

---

## Financial context (example profile)

- **Income**: single primary salary, paid monthly in PLN
- **Fixed floor**: rent + groceries + loan + utilities + childcare form a stable monthly base
- **Savings rate**: target 15%+; actual varies month to month
- **Family**: household of several members configured in the Lists sheet (never hardcoded)
- **One-offs**: occasional large transactions (vehicle purchases/sales, tax returns) must not
  break trend analysis — treat as outliers
- **Savings goals**: long-term goals with percentage allocations, configured in Lists
- **Currencies in use**: PLN primary, others occasional

---

## Code style rules (enforced)

- No inline comments unless a line is genuinely surprising
- No docstrings — function names must be self-explanatory
- No abbreviations unless universally known (`df` for DataFrame is fine, `bg` for background is not)
- No hardcoded domain values — everything from Excel
- Use Pydantic models for structured data — no raw dicts between functions
- Column positions always detected from headers — never hardcoded numbers
