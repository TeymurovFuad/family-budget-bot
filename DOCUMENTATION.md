# Budget Tracker — System Documentation

This document explains how the entire personal finance system works:
the Excel workbook, the Telegram bot, and how they connect.

---

## Overview

Two connected parts:

| Part | Purpose |
|---|---|
| `Expenses.xlsx` | Source of truth — stores every transaction |
| `bot.py` (Telegram) | Reads and writes the Excel file, sends summaries |

All amounts are stored internally in your **base currency** (set via DISPLAY_CURRENCY). You can change how they are displayed
(EUR, AZN, etc.) without touching any data.

---

## Excel Workbook

### Sheets

| Sheet | What it contains |
|---|---|
| 📖 Guide | Explanation of every column and section with examples |
| Lists | Reference values that power all dropdowns |
| MasterData | Every transaction, one row per entry |
| Monthly Summary | One row per month, calculated from MasterData |
| Dashboard | Interactive view — change Year, Month, Display Currency to filter |
| Cycle Dashboard | Cycle-scoped mirror of Dashboard — filter spending by budget cycle (B2 dropdown). Created automatically when the first cycle boundary is recorded. Only present when BUDGET_CYCLE=1. |

---

### MasterData Columns

Every transaction is one row. There are 13 columns:

| Column | Name | Fill this? | What it holds |
|---|---|---|---|
| A | Date | ✅ You fill | The date of the transaction (YYYY-MM-DD) |
| B | Year | ❌ Formula | Extracted from Date automatically |
| C | Month | ❌ Formula | Extracted from Date automatically (e.g. "May") |
| D | Value | ✅ You fill | The amount in the transaction's own currency |
| E | Type | ✅ Dropdown | Expense / Income / Savings |
| F | Category | ✅ Dropdown | One of 17 categories |
| G | Person | ❌ Retired | Legacy column — the household budgets as one unit. The bot always leaves it blank; mention people in Description if needed |
| H | Description | ✅ Free text | A short note — 3 to 6 words is enough |
| I | IsRecurring | ✅ You fill | TRUE if paid every month (rent, loan, internet) |
| J | IsDone | ✅ You fill | TRUE = paid. FALSE = planned but not yet paid (excluded from totals) |
| K | Currency | ✅ Dropdown | Your configured base currency. Change to EUR, AZN etc. for foreign transactions |
| L | Value (base) | ❌ Formula | Auto-converts Value to the base currency using the rate from Lists sheet |
| M | Date Modified (UTC) | ❌ Formula | Audit timestamp — when the row was entered. Set once by formula when Value is first typed in Excel; rows written by the bot get the write time directly |

**The only column you must fill manually is Date (col A).** Year and Month
derive from it automatically. All other columns have dropdowns or are formulas.

**Date Modified** requires one Excel setting to work:
File → Options → Formulas → Enable Iterative Calculation → Max Iterations = 1.
Without this it shows 0.

---

### Adding a Transaction

1. Enter the **Date** (col A). Year and Month fill automatically.
2. Enter the **Value** — the amount in whatever currency you paid in.
3. Set **Currency** if different from your base currency. The base-currency equivalent calculates automatically.
4. Choose **Type** from the dropdown: Expense, Income, or Savings.
5. Choose **Category** from the dropdown.
6. Write a short **Description**.
7. Set **IsRecurring** = TRUE for anything that repeats every month.
8. Leave **IsDone** = TRUE for transactions already made.

---

### Categories

17 categories covering actual spending patterns:

| Category | Typical entries |
|---|---|
| Groceries | Weekly food shopping |
| Housing | Rent |
| Transport | Petrol, parking, car repairs |
| Utilities | Internet, phone, electricity |
| Healthcare | Doctor, pharmacy, vaccines |
| Entertainment | Restaurants, cinema, fun |
| Travel | Hotels, flights, trips |
| Children | Nursery fees, toys, clothing, medical |
| Personal | Pocket money, personal spending |
| Gifts & Shopping | Presents, clothing, home items |
| Insurance | Car insurance, health insurance |
| Loan | Monthly loan repayment |
| Investment | XTB, stocks, savings products |
| Government | Fines, fees, official documents |
| Education | Courses, books, driving school |
| Subscriptions | Google Drive, Proton VPN, streaming |
| Other | Anything that doesn't fit |

---

### Monthly Budget Targets

These are set in the Dashboard (column I, the blue input cells) and in the bot.
All amounts in base currency:

| Category | Monthly budget |
|---|---|
| Groceries | 2,100 |
| Housing | 3,300 |
| Transport | 500 |
| Utilities | 200 |
| Healthcare | 150 |
| Entertainment | 250 |
| Travel | 300 |
| Children | 500 |
| Personal | 600 |
| Gifts & Shopping | 200 |
| Insurance | 100 |
| Loan | 280 |
| Investment | 400 |
| Government | 50 |
| Education | 100 |
| Subscriptions | 25 |
| Other | 200 |

---

### Currency System

**How storage works:**
Every transaction stores the original amount in column D (Value) and the
currency in column K. Column L (Value base) automatically converts to your base currency using
the rate from the Lists sheet. All totals, all Dashboard figures, and all bot
responses use column L — never column D directly.

**The rate table** is in the Lists sheet, columns G and H:

| Currency | Rate to base |
|---|---|
| <base currency> | 1 (never change) |
| EUR | 4.28 — edit when the rate changes |
| USD | 3.92 |
| GBP | 4.98 |
| AZN | 2.51 |
| CHF | 4.41 |

The blue cells are the ones you edit. Changing EUR from 4.28 to 4.35 instantly
recalculates every EUR transaction in the workbook.

**Display currency** is set on the Dashboard in cell F2. Changing it to EUR makes
every number on the Dashboard show in euros — it divides all base-currency values by the
EUR rate. Historical data stays untouched; it just displays differently.

---

### Dashboard

**Filter controls (row 2):**

| Cell | Controls |
|---|---|
| B2 | Year — change to view a different year |
| D2 | Month — delete the value to see the full year |
| F2 | Display Currency — all numbers convert instantly |

**The sanity check (row 15):**
The tracker is built on: Income = Expenses + Savings. Every amount in your base currency must be
either logged as an expense or logged as savings. If the check shows anything
other than "✓ Balanced", a transaction is missing or duplicated.

**Blue cells** = values you are meant to edit (budget amounts, savings allocations).
**Black cells** = formulas — do not edit.

---

### Lists Sheet

| Column | Contains | When to edit |
|---|---|---|
| A | Month abbreviations | Never |
| B | Transaction types | Never |
| C | Categories | Add a new category here, then add it to the Dashboard budget table |
| D | Family members | Legacy — the Person field is retired; the bot no longer uses this list |
| E | Years | Add the next year here before January |
| G | Currency codes | Add a new currency here |
| H | Rates (base) | Edit when an exchange rate changes |
| Salary Keywords | Extra words that mark a transaction as salary income | Managed via `/keywords` — do not edit directly |

---

## Telegram Bot

### Setup

1. Create a bot via `@BotFather` on Telegram → copy the token
2. Get your Telegram user ID from `@userinfobot`
3. Copy `.env.example` to `.env` and fill in the values
4. Put `Expenses.xlsx` in the `data/` folder
5. Run `python bot.py`

### Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `TELEGRAM_BOT_TOKEN` | ✅ | — | Token from @BotFather |
| `ALLOWED_TELEGRAM_IDS` | ✅ | — | Comma-separated user IDs. Get from @userinfobot |
| `XLSX_PATH` | — | `data/Expenses.xlsx` | Path to the Excel file |
| `TIMEZONE` | — | `Europe/Warsaw` | For timestamps and scheduled reports |
| `DISPLAY_CURRENCY` | — | `PLN` | Base/display currency. Controls currency fallback in data loading, the Value (base) formula written to Excel, and dedup key generation. Baked into Excel formulas at write time — changing it after rows exist requires re-running `scripts/migrate_base_currency_headers.py`. |
| `BUDGET_CYCLE` | — | `0` | Set to `1` to enable salary-to-salary budget cycles (see "Budget Cycles" below) |
| `CYCLE_REPROMPT_MIN_AGE_DAYS` | — | `20` | A saved Salary income only proposes a new cycle if the current one is at least this old, or if no cycle has been recorded yet |
| `SALARY_CATEGORY` | — | `Salary` | Category name that marks salary income for cycle detection and the unaccounted metric |
| `CYCLE_DETECT_KEYWORDS` | — | *(empty)* | Extra comma-separated words that mark a transaction as salary when found in its Description (e.g. `wages,payroll`) — see "How a salary is detected" |

### Commands

| Command | What you get |
|---|---|
| `/start` | Welcome message with the three entry methods and the main button menu |
| `/menu` | Show the persistent button menu |
| `/help` | List all commands grouped by purpose |
| `/summary` | Opens a period picker (quick buttons, history drill-down); or pass a period/range directly, e.g. `/summary aug 2025` or `/summary aug 2025 - jan 2026` |
| `/week` | Last 7 days spending by category |
| `/budget` | All 17 categories with budget vs actual and progress bars |
| `/top` | The 5 biggest expenses this month (current cycle when `BUDGET_CYCLE=1`) |
| `/savings` | Savings rate for each of the last 6 months |
| `/report` | Full report: fixed vs variable, by category (cycle-scoped when `BUDGET_CYCLE=1`) |
| `/chart` | Spending by category rendered as a chart image |
| `/range` | Report for a custom date range (preset buttons or typed dates) |
| `/rates` | Exchange rates (`/rates refresh` fetches live rates) |
| `/add` | Log a new transaction step by step |
| `/bulk` | Import many transactions at once from a photo, CSV/XLSX bank statement, .txt file, or pasted text |
| `/edit` | Edit a field on one of the last 10 transactions |
| `/delete` | Remove one of the last 5 transactions |
| `/setcurrency EUR` | Switch display currency for this session |
| `/setcurrency` | Pick display currency from a keyboard |
| `/keywords` | View, add or remove the salary keywords used for cycle detection — owner only |
| `/setbudget` | Set the monthly budget limit for a category — **owner only** (the first ID in `ALLOWED_TELEGRAM_IDS`) |
| `/setup` | First-time onboarding: creates the budget file from the template, then walks through categories, budgets, and currency — **owner only** (see "Onboarding via /setup") |
| `/export` | Download the live Excel workbook as a Telegram document |
| `/cycle` | Show the current budget cycle (any allowed user); `/cycle started [YYYY-MM-DD]` records a boundary; `/cycle detect [word ...]` backfills history; `/cycle list` shows all boundaries; `/cycle remove YYYY-MM-DD` deletes one — **changes are owner only**, needs `BUDGET_CYCLE=1` |

`/add`, `/bulk`, `/edit`, `/delete`, `/setcurrency`, `/keywords`, `/setbudget`, `/setup`,
the `/cycle` write subcommands (`started`, `remove`), and quick-add (typed
transactions) are **owner-only** — only the first ID listed in
`ALLOWED_TELEGRAM_IDS` can use them. Every other allowed user can still use all
read/report commands, including viewing the current cycle with bare `/cycle`.

Every command accepts `help` as a subcommand (e.g. `/add help`, `/bulk help`,
`/summary help`, `/cycle help`) and returns a one-screen usage card.

All of these are also registered in Telegram's command menu (the `/` button) at
startup via `set_my_commands` — no manual BotFather registration needed.

### Onboarding via /setup

`/setup` (owner only) walks a first-time user from an empty deployment to a
working budget. Sending `/start` when no workbook exists routes the owner into
the same flow automatically.

1. **Welcome** — if the workbook is missing, it is created from
   `data/Expenses_Template.xlsx` atomically (temp file + rename), and a default
   set of 14 categories (Salary, Other Income, Housing, Groceries, Transport,
   Utilities, Health, Dining Out, Shopping, Entertainment, Subscriptions,
   Travel, Savings, Other) is loaded for review.
2. **Category review** — inline buttons to rename a category, add a category
   (with an Expense/Income/Savings type picker), confirm, or cancel.
3. **Budgets** — for every Expense category in turn, send a monthly limit
   (`0` = no limit). Skipped silently if there are no Expense categories.
4. **Currency** — pick USD/EUR/RUB/TRY/CNY, or "Other" and type any 3-letter
   code. The choice becomes your display currency and is added to the Lists
   currency table.
5. **Summary** — categories, budgets, and currency are written to the workbook
   (Lists sheet, Dashboard, and Cycle Dashboard stay in sync), and live
   exchange rates are fetched from frankfurter.dev (best effort — a warning is
   shown if the fetch fails or the chosen code has no live rate).

Writes happen at two atomic checkpoints (categories when you confirm them;
budgets + currency at the summary), so `/cancel` keeps everything already
confirmed. Running `/setup` again on a configured workbook asks for
confirmation first, then lets you edit the existing categories and budgets.

Sending `/setup` while a setup session is already in progress restarts it
immediately. The bot warns: "Previous setup session was abandoned. Any unsaved
category edits are lost." No `/cancel` is needed first.

When you rename a category during setup, the rename cascades automatically
through all existing data — MasterData rows, Dashboard plain-value cells, and
formula string literals are all updated in one step, equivalent to running
`scripts/rename_category.py`. For normal use the bot handles this; run
`scripts/rename_category.py` only when renaming categories in a workbook the
bot cannot reach directly (offline migration, shared file on a different
machine).

### Scheduled Reports

| When | What |
|---|---|
| Every Sunday at 18:00 | Weekly check-in with projected month-end spend |
| 1st of every month at 08:00 | Final report for the month that just closed |

### Logging a Transaction via /add

The bot walks you through 7 steps:
1. Enter the amount (numbers only)
2. Pick the currency (keyboard shown, your display currency is first)
3. Pick the type: Expense, Income, or Savings
4. Pick the category (skipped for Income and Savings)
5. Write a description — or type `/skip`
6. Confirm whether it's recurring
7. Review the summary and confirm with ✅ Save or ❌ Cancel

The bot writes the transaction directly to MasterData including the Currency
column and a live Value (base) formula identical to manually entered rows.
It also stamps the **Date Modified (UTC)** column with the write time, so you
can always see when a row was entered by the bot.

### Bulk Import via /bulk

Import a whole bank statement or receipt in one go:

1. Send `/bulk`. If you have an unfinished draft, the bot shows it immediately
   for review — no need to re-upload anything.
2. Otherwise send a **photo**, a **CSV/XLSX bank statement**, a **plain-text
   file (.txt)**, or **pasted text**.
3. Large statements are parsed in chunks — the bot tells you up front
   ("I'll parse it in N parts") and merges the results.
4. The AI output is auto-validated against the Lists sheet:
   - Categories not in the list are fuzzy-matched to a real category
     (or fall back to Other).
   - Any person value the AI still emits is moved into the description
     (the Person field is retired).
   - Unknown transaction types default to Expense.
   - "Savings" received as a category is automatically promoted: the row
     becomes type Savings with category Other (Savings is a transaction type,
     never a category).
   Every correction is reported before the preview as a 🛡 auto-correction.
   The same corrections — including the Savings promotion — apply to quick-add
   (typed transactions) too.
5. The bot shows a numbered preview, split across several messages for large
   imports (row numbers stay stable across pages), sorted by date.
6. Review the preview and reply with commands to adjust it:

   | Command | What it does |
   |---|---|
   | `2 category=Transport` | Edit a field on row 2 |
   | `1 description=Lunch` | Edit the description on row 1 |
   | `drop 3` | Remove row 3 from this import |
   | `drop 4 6` | Remove rows 4 and 6 |
   | `drop 4-6 9` | Remove rows 4, 5, 6, and 9 |
   | `keep 3` | Restore a dropped row, or force-save a skipped duplicate |
   | `drop all` | Remove every row |
   | `keep all` | Restore every row |

7. Send `save` (or `/save` — both work) to write all rows to MasterData.
   The confirmation names the exact destination file (local path or cloud
   object). Send `cancel` to discard the draft.

**Duplicate detection.** The bot automatically compares each row against
MasterData before showing the preview:

- **Already imported** (strict match — same date, amount, currency, and
  description): the row is skipped by default and marked `↺` in the preview.
  Reply `keep N` or `keep all flagged` to save it anyway (e.g. a genuine
  second payment of the same amount to the same merchant).
- **Count-aware:** if you upload 3 identical rows and 2 are already saved,
  the bot saves 1 and skips 2 — it shows the math so you can verify.
- **Possible duplicate** (loose match — same date and amount, different
  description): the row is **saved by default** and flagged `⚠️` as an
  advisory. Reply `drop N` or `drop all flagged` if it's the same payment
  with a reformatted merchant name.
- **Identical rows within one batch** (e.g. three 2.00 car-wash payments
  same day): all are kept by default and annotated. Reply `drop N` to remove
  one if it's a scan error.

**Bank-statement profiles (CSV/XLSX).** The first time you upload a statement
export from your bank, the bot makes one AI call to guess which column is the
date, amount, currency, and description (sample rows are masked before they
leave your machine — amounts and account numbers are replaced with `***`).
It shows you the proposed mapping; you can fix any column with the inline
buttons, then give the profile a name and save it. From then on, every
statement with the same columns is recognized instantly — no AI call, no
questions, no re-mapping — the preview opens directly with a
"📄 Parsed with profile ..." line. Re-uploading the same file or a new export
in the same format always matches the saved profile silently.
Profiles are stored per user on the bot's disk (`data/statement_profiles/`),
never in the repository, so no bank names or account details are shared.
A `.txt` upload that looks column-structured (consistent delimiter) enters
the same profile flow; a plain-text receipt falls through to the normal AI
path.

**Split debit/credit columns.** Some banks export two separate amount columns
instead of one signed column — a debit column for money out and a credit
column for money in. Map `debit` (expense) and `credit` (income) instead of a
single `amount` and the bot handles the rest: the transaction type is inferred
automatically from which column holds the value, rows where both columns are
empty are skipped, and if a row somehow has values in both, the debit wins and
a warning is logged.

**Reading the mapping proposal.** The proposal message is split into three
sections so you can see at a glance what still needs attention:

- **Required** — fields the profile cannot work without: ✅ mapped, ❌ still
  missing.
- **Optional** — nice-to-have fields (description, time): ✅ mapped, ➖ not
  mapped (fine to leave).
- **Ignored** — statement columns that map to nothing; they're simply skipped.

A profile is valid once it has a date column, a currency, and an amount —
either a single `amount` column or the `debit` + `credit` pair.

**Managing saved profiles.** `/bulk profile list` shows every saved profile
with an inline delete button next to each; `/bulk profile delete <name>`
deletes one directly. Both are owner-only, like all write commands.

**Drafts survive interruptions.** The draft is stored per user on disk, so if
the review session times out (30 minutes) or the bot restarts, just run
`/bulk` again and it resumes where you left off. A draft holds at most 50
pending rows. If a new upload arrives while the draft is full, the newly
parsed rows are not lost — they are held aside, and as soon as you `save` or
`cancel` the current draft the held rows automatically load as a new draft
for review. A second upload while rows are already held is refused with an
explicit message — finish the current draft first.

**A note on the `.bak` file:** every save writes to a temporary file first and
keeps a rolling `.bak` copy of the previous version next to the workbook, so a
crash mid-save can never corrupt your data. The `.bak` file is normal — it's
your automatic one-step backup.

---

## Budget Cycles

Budget cycles let you track spending relative to your salary period instead of
calendar months. Salary typically arrives around the 25th of the month but can
shift ±4–5 days, so cycle boundaries are recorded events confirmed by you —
never computed from fixed dates.

### Enabling cycles

Set `BUDGET_CYCLE=1` in `.env` and restart the bot. When the variable is
absent or set to `0` the feature is completely off and all behaviour is
identical to the default calendar mode.

### The /cycle command

```
/cycle                        show the current cycle (label, start date, day count)
/cycle started                start a new cycle from today
/cycle started YYYY-MM-DD     start a new cycle from that date
/cycle detect                 scan transaction history and backfill historical cycle boundaries
/cycle detect <word> ...      same scan with extra search words (e.g. /cycle detect wages)
/cycle list                   show every recorded boundary with its date range
/cycle remove YYYY-MM-DD      delete a wrongly recorded boundary
```

Bare `/cycle`, `/cycle list`, and `/cycle detect` (the scan itself) are
available to every allowed user; `/cycle started` and `/cycle remove` — and
the detect confirmation buttons that actually write boundaries — are
**owner-only** (the first ID in `ALLOWED_TELEGRAM_IDS`). Future dates are
rejected, and recording the same start date twice is a no-op — boundaries are
written once and never recomputed.

**Fixing a wrong boundary:** `/cycle list` shows every recorded date;
`/cycle remove YYYY-MM-DD` deletes the wrong one; `/cycle started` with the
correct date records the replacement. Removing a boundary merges its
transactions into the previous cycle — no transaction data is touched.

### How a salary is detected

A transaction counts as salary when it is type **Income** and its Category or
Description contains a detection keyword as a whole word — so a category of
"Salary Bonus" matches the keyword `salary`, but "Salaries" does not. The
Description is always checked alongside the Category (e.g. a bulk-imported row
with the bank transfer title "WYNAGRODZENIE ZA LIPIEC ACME" and an empty
category matches via Description). The keyword list starts with `SALARY_CATEGORY`
and is extended by keywords stored in the Excel Lists sheet "Salary Keywords"
column — managed via `/keywords`. If no keywords have been saved to Excel yet,
the bot falls back to `CYCLE_DETECT_KEYWORDS` in `.env` as a seed; once the
first keyword is added via `/keywords` the `.env` value is seeded into Excel and
`.env` is no longer the authoritative source. Any words passed to
`/cycle detect <word> ...` are also included for that one scan. The same
matching drives `/cycle detect`, the salary-cycle prompt, and the unaccounted
metric.

The boundary is written immediately to the `Cycles` sheet in the workbook with
a label such as "Jul 2026". Labels always include the year so multi-year
history is unambiguous; a second boundary within the same calendar month gets
an index suffix ("Jul 2026 #2") so every cycle label stays unique. The sheet is part of the template and is auto-created
on first use for existing workbooks.

A **Cycle Dashboard** sheet is created automatically when the first cycle
boundary is recorded. It mirrors the existing Dashboard but filters by a
selected cycle — pick one in the B2 dropdown, which is fed from the Cycles
ledger. It shows a summary block for the selected cycle: Salary, Income,
Expenses, Savings, Unaccounted, and Cycle Days. If the Cycle Dashboard's
category rows fall out of sync with the main Dashboard, run
`scripts/sync_cycle_dashboard.py` to realign them.

### Salary-cycle prompt

When `BUDGET_CYCLE=1` and you save a transaction of type **Income** with
category **Salary** (via `/add`, quick-add, or `/bulk`), the bot automatically
asks whether to open a new budget cycle:

```
💰 Salary received. Start the new budget cycle from 23 Jul? (yes / no / different date)
```

**When it fires:** the prompt only appears when the last recorded boundary is
at least `CYCLE_REPROMPT_MIN_AGE_DAYS` (default 20) days in the past, or when
no cycle has been recorded yet. A salary row saved inside a younger cycle is
silently counted as income for the current cycle without re-prompting.

**How to respond** — the message carries three inline buttons:

| Button | Effect |
|---|---|
| **Yes** | Records a new cycle starting on the salary transaction date |
| **No** | Dismisses the prompt; the current cycle continues |
| **Different date** | Asks you to send `/cycle started YYYY-MM-DD` with the date you want |

Only a button tap records anything — the bot never opens a cycle on its own.

### Backfilling history with /cycle detect

`/cycle detect` scans the full transaction history for Salary income rows and
proposes cycle boundaries for every past month where a salary arrival can be
identified. Requires `BUDGET_CYCLE=1`.

The bot splits months into two groups:

- **Unambiguous months** — exactly one Salary row falls inside the expected
  payday window. All such months are listed together with a **Confirm all**
  button. Tapping it records every boundary in one step.
- **Ambiguous months** — zero or more than one Salary row in the window. The
  bot walks through these one at a time with inline date pickers. A
  **Custom date** option is always available if none of the suggested dates are
  correct.

Boundaries that already exist in the `Cycles` sheet are skipped — running
`/cycle detect` more than once is safe.

### Cycle-scoped /summary and /budget

Bare `/summary` opens a **period picker** instead of computing a report
directly:

- **Quick row** — one-tap buttons for *This cycle*, *Last cycle* (shown when
  `BUDGET_CYCLE=1` and boundaries exist), *This month* and *Last month*.
- **History drill-down** — a 📅 *Calendar* / 💰 *Cycle* choice that pages
  through past years/months or recorded cycles.
- **Free-form arguments** — type the period directly: `/summary aug 2025`,
  `/summary 2025 aug`, `/summary 08.2025`, or a bare month like
  `/summary aug` (resolved to the most recent matching month).
- **Range syntax** — `/summary aug 2025 - jan 2026` reports over a span of
  months.

When `BUDGET_CYCLE=1` and at least one boundary has been recorded, the cycle
buttons compute over the **current cycle** — last recorded boundary through
today, open-ended — and `/budget` still defaults to the current cycle instead
of the calendar month. The cycle summary shows income, expenses, savings, net
and savings rate for the cycle, plus:

| Line | Meaning |
|---|---|
| **Salary received** | Total income in the Salary category since the cycle start date |
| **Unaccounted** | Salary − tracked expenses − tracked savings |
| **Daily average spend** | Expenses ÷ days elapsed — shown instead of a month-end projection, because a cycle's length is never assumed |

If no boundary has been recorded yet, both commands fall back to the calendar
month.

**Unaccounted:** a positive value means money is accounted for — salary
minus what you spent and saved leaves a surplus that is either still in your
account or will appear in a future transaction. A negative value means
you have logged more spending and savings than salary in this cycle, which
usually indicates untracked income from a previous cycle being spent, or a
mis-categorised refund logged as a new income row.

### Cycle-scoped /report, /top, and budget alerts

When `BUDGET_CYCLE=1` and a boundary exists, `/report` and `/top` also cover
the current cycle instead of the calendar month — `/report` compares category
spend against the previous cycle, and the after-save budget alerts use the
same cycle window as `/budget`, so their percentages always agree.

### What does not change

All other calendar-mode commands (`/week`, `/range`, etc.)
and the existing Dashboard sheet continue to work exactly as before.
Cycles are purely additive. Setting `BUDGET_CYCLE=0` at any point leaves
the `Cycles` sheet in the workbook untouched and simply stops the feature
from activating — no data is lost.

---

## Relocating to Another Country

Example: moving to Azerbaijan.

1. Update the AZN rate in the Lists sheet if needed.
2. Set `DISPLAY_CURRENCY=AZN` in `.env` and restart the bot.
3. Set `TIMEZONE=Asia/Baku` in `.env`.
4. Log new transactions with Currency = AZN and the native amount in Value.
   The base-currency equivalent is calculated automatically.
5. Historical base-currency data stays untouched and converts to AZN for display.
6. Update the budget amounts in the Dashboard (blue cells) to reflect
   the new country's cost of living. The bot's `MONTHLY_BUDGETS` dict
   in `bot.py` also needs updating to match.

---

## Hosting the Bot

### Railway (recommended)

Railway gives $5/month free credit — enough to run the bot 24/7.

1. Push the `budget_bot/` folder to a GitHub repository.
   Make sure `.env` is in `.gitignore` — never commit it.
2. Go to [railway.app](https://railway.app) → New Project → Deploy from GitHub.
3. Add environment variables in Railway → Settings → Variables.
4. Add a Volume mounted at `/app/data` for the Excel file.
5. Deploy. Railway detects the Dockerfile automatically.

### Other options

- **Render** — free tier available, same setup as Railway
- **Fly.io** — free tier, more control, needs `flyctl` CLI
- **Your own PC** — simplest, no hosting needed, Excel stays local

---

## What MCPs Would Help

An honest assessment:

**Genuinely useful now:**
- **Filesystem MCP** (already in Claude Desktop) — Claude can read and write
  the Excel file directly. Say "log 250 EUR petrol" and it adds the row.

**Worth adding later:**
- **Excel/spreadsheet MCP** — richer formula execution and cell queries
- **Bank/Revolut MCP** — auto-import transactions, the biggest quality-of-life upgrade possible

**Not needed:**
Databases, cloud storage, complex auth services. The system is intentionally
file-based and simple. That's a design choice, not a limitation.
