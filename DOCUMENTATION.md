# Budget Tracker — System Documentation

This document explains how the entire personal finance system works:
the Excel workbook, the Telegram bot, and how they connect.

---

## Overview

Two connected parts:

| Part | Purpose |
|---|---|
| `Expenses_Improved.xlsx` | Source of truth — stores every transaction |
| `bot.py` (Telegram) | Reads and writes the Excel file, sends summaries |

All amounts are stored internally in **PLN**. You can change how they are displayed
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
| G | Person | ✅ Dropdown | <YOUR_NAME> / <FAMILY_MEMBER_1> / <FAMILY_MEMBER_2> / <FAMILY_MEMBER_3> — leave blank if it's a household expense |
| H | Description | ✅ Free text | A short note — 3 to 6 words is enough |
| I | IsRecurring | ✅ You fill | TRUE if paid every month (rent, loan, internet) |
| J | IsDone | ✅ You fill | TRUE = paid. FALSE = planned but not yet paid (excluded from totals) |
| K | Currency | ✅ Dropdown | PLN by default. Change to EUR, AZN etc. for foreign transactions |
| L | Value (PLN) | ❌ Formula | Auto-converts Value to PLN using the rate from Lists sheet |
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
3. Set **Currency** if not PLN. The PLN equivalent calculates automatically.
4. Choose **Type** from the dropdown: Expense, Income, or Savings.
5. Choose **Category** from the dropdown.
6. Set **Person** if the expense is clearly for one family member.
7. Write a short **Description**.
8. Set **IsRecurring** = TRUE for anything that repeats every month.
9. Leave **IsDone** = TRUE for transactions already made.

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
| Personal | Pocket money for <YOUR_NAME> or <FAMILY_MEMBER_1> |
| Gifts & Shopping | Presents, clothing, home items |
| Insurance | Car insurance, health insurance |
| Loan | Monthly loan repayment |
| Investment | XTB, stocks, savings products |
| Government | Fines, fees, official documents |
| Education | Courses, books, driving school |
| Subscriptions | Google Drive, Proton VPN, streaming |
| Other | Anything that doesn't fit |

**Person column** works alongside Category. Use it when an expense is clearly for
one person. Example: Category = Healthcare, Person = a family member for a pharmacy purchase.

---

### Monthly Budget Targets

These are set in the Dashboard (column I, the blue input cells) and in the bot.
All amounts in PLN:

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
currency in column K. Column L (Value PLN) automatically converts to PLN using
the rate from the Lists sheet. All totals, all Dashboard figures, and all bot
responses use column L — never column D directly.

**The rate table** is in the Lists sheet, columns G and H:

| Currency | Rate to PLN |
|---|---|
| PLN | 1 (never change) |
| EUR | 4.28 — edit when the rate changes |
| USD | 3.92 |
| GBP | 4.98 |
| AZN | 2.51 |
| CHF | 4.41 |

The blue cells are the ones you edit. Changing EUR from 4.28 to 4.35 instantly
recalculates every EUR transaction in the workbook.

**Display currency** is set on the Dashboard in cell F2. Changing it to EUR makes
every number on the Dashboard show in euros — it divides all PLN values by the
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
The tracker is built on: Income = Expenses + Savings. Every earned PLN must be
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
| D | Family members | Add a new person here |
| E | Years | Add the next year here before January |
| G | Currency codes | Add a new currency here |
| H | Rates to PLN | Edit when an exchange rate changes |

---

## Telegram Bot

### Setup

1. Create a bot via `@BotFather` on Telegram → copy the token
2. Get your Telegram user ID from `@userinfobot`
3. Copy `.env.example` to `.env` and fill in the values
4. Put `Expenses_Improved.xlsx` in the `data/` folder
5. Run `python bot.py`

### Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `TELEGRAM_BOT_TOKEN` | ✅ | — | Token from @BotFather |
| `ALLOWED_TELEGRAM_IDS` | ✅ | — | Comma-separated user IDs. Get from @userinfobot |
| `XLSX_PATH` | — | `data/Expenses_Improved.xlsx` | Path to the Excel file |
| `TIMEZONE` | — | `Europe/Warsaw` | For timestamps and scheduled reports |
| `DISPLAY_CURRENCY` | — | `PLN` | Default display currency. Change to `EUR` or `AZN` when relocating |

### Commands

| Command | What you get |
|---|---|
| `/start` | Welcome message with the three entry methods and the main button menu |
| `/menu` | Show the persistent button menu |
| `/help` | List all commands grouped by purpose |
| `/summary` | This month: income, expenses, savings, net, savings rate |
| `/week` | Last 7 days spending by category |
| `/budget` | All 17 categories with budget vs actual and progress bars |
| `/top` | The 5 biggest expenses this month |
| `/savings` | Savings rate for each of the last 6 months |
| `/report` | Full report: fixed vs variable, by category, by person |
| `/chart` | Spending by category rendered as a chart image |
| `/range` | Report for a custom date range (preset buttons or typed dates) |
| `/rates` | Exchange rates (`/rates refresh` fetches live rates) |
| `/add` | Log a new transaction step by step |
| `/bulk` | Import many transactions at once from a photo, CSV/XLSX bank statement, .txt file, or pasted text |
| `/edit` | Edit a field on one of the last 10 transactions |
| `/delete` | Remove one of the last 5 transactions |
| `/setcurrency EUR` | Switch display currency for this session |
| `/setcurrency` | Pick display currency from a keyboard |
| `/setbudget` | Set the monthly budget limit for a category — **owner only** (the first ID in `ALLOWED_TELEGRAM_IDS`) |
| `/export` | Download the live Excel workbook as a Telegram document |

`/add`, `/bulk`, `/edit`, `/delete`, `/setcurrency`, `/setbudget`, and quick-add
(typed transactions) are **owner-only** — only the first ID listed in
`ALLOWED_TELEGRAM_IDS` can use them. Every other allowed user can still use all
read/report commands.

All of these are also registered in Telegram's command menu (the `/` button) at
startup via `set_my_commands` — no manual BotFather registration needed.

### Scheduled Reports

| When | What |
|---|---|
| Every Sunday at 18:00 | Weekly check-in with projected month-end spend |
| 1st of every month at 08:00 | Final report for the month that just closed |

### Logging a Transaction via /add

The bot walks you through 8 steps:
1. Enter the amount (numbers only)
2. Pick the currency (keyboard shown, your display currency is first)
3. Pick the type: Expense, Income, or Savings
4. Pick the category (skipped for Income and Savings)
5. Pick the family member (skipped for Income and Savings)
6. Write a description — or type `/skip`
7. Confirm whether it's recurring
8. Review the summary and confirm with ✅ Save or ❌ Cancel

The bot writes the transaction directly to MasterData including the Currency
column and a live Value (PLN) formula identical to manually entered rows.
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
   - Person values that aren't known family members are moved into the
     description instead.
   - Unknown transaction types default to Expense.
   Every correction is reported before the preview.
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
- **Identical rows within one batch** (e.g. three 2 PLN car-wash payments
  same day): all are kept by default and annotated. Reply `drop N` to remove
  one if it's a scan error.

**Bank-statement profiles (CSV/XLSX).** The first time you upload a statement
export from your bank, the bot makes one AI call to guess which column is the
date, amount, currency, and description (sample rows are masked before they
leave your machine — amounts and account numbers are replaced with `***`).
It shows you the proposed mapping; you can fix any column with the inline
buttons, then give the profile a name and save it. From then on, every
statement with the same columns is recognized instantly — no AI call, no
questions, the preview opens directly with a "📄 Parsed with profile ..." line.
Profiles are stored per user on the bot's disk (`data/statement_profiles/`),
never in the repository, so no bank names or account details are shared.
A `.txt` upload that looks column-structured (consistent delimiter) enters
the same profile flow; a plain-text receipt falls through to the normal AI
path.

**Drafts survive interruptions.** The draft is stored per user on disk, so if
the review session times out (30 minutes) or the bot restarts, just run
`/bulk` again and it resumes where you left off. A draft holds at most 50
pending rows — save or cancel before importing more.

**A note on the `.bak` file:** every save writes to a temporary file first and
keeps a rolling `.bak` copy of the previous version next to the workbook, so a
crash mid-save can never corrupt your data. The `.bak` file is normal — it's
your automatic one-step backup.

---

## Relocating to Another Country

Example: moving to Azerbaijan.

1. Update the AZN rate in the Lists sheet if needed.
2. Set `DISPLAY_CURRENCY=AZN` in `.env` and restart the bot.
3. Set `TIMEZONE=Asia/Baku` in `.env`.
4. Log new transactions with Currency = AZN and the native amount in Value.
   The PLN equivalent is calculated automatically.
5. Historical PLN data stays untouched and converts to AZN for display.
6. Update the budget amounts in the Dashboard (blue cells) to reflect
   the new country's cost of living. The bot's `MONTHLY_BUDGETS_PLN` dict
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
