# Architecture & Data Flow

Visual overview of how Budget Bot works — from Telegram message to Excel and back.

---

## System Overview

```mermaid
graph TD
    TG["📱 Telegram\n(user)"]
    BOT["🤖 bot.py\n(Python process)"]
    SCHED["⏰ scheduled_report.py\n(GitHub Actions / cron)"]
    EXCEL["📊 Expenses_Improved.xlsx"]
    GCS["☁️ Cloud Storage\n(GCS / S3 / local disk)"]

    TG -- "message / command" --> BOT
    BOT -- "reply / chart / report" --> TG
    BOT -- "read/write" --> EXCEL
    EXCEL -- "stored in" --> GCS
    SCHED -- "reads" --> GCS
    SCHED -- "weekly/monthly report" --> TG
```

---

## Excel File Structure

```mermaid
erDiagram
    MASTERDATA {
        date     Date
        int      Year
        string   Month
        float    Value
        string   Type
        string   Category
        string   Person
        string   Description
        bool     IsRecurring
        bool     IsDone
        string   Currency
        float    Value_PLN
        datetime DateModified
    }

    LISTS {
        string   Month_A
        string   Type_B
        string   Category_C
        string   Person_D
        int      Year_E
        string   Currency_I
        float    Rate_PLN_J
    }

    DASHBOARD {
        string   Category_H
        float    Budget_PLN_I
    }

    MASTERDATA }o--|| LISTS : "dropdowns validated against"
    DASHBOARD }o--|| LISTS : "budget per category"
```

> **Single source of truth:** The **Lists** sheet drives every dropdown in MasterData and every prompt shown by the bot. Add a category to col C — it appears everywhere instantly, no restart needed.

---

## Bot Message Flow

```mermaid
sequenceDiagram
    actor User
    participant TG as Telegram
    participant Bot as bot.py
    participant AI as ai_parser.py
    participant Excel as Excel (via file_storage)

    User->>TG: sends text / photo
    TG->>Bot: update event

    alt Quick natural language entry
        Bot->>AI: parse_text(text, lists)
        AI-->>Bot: Transaction fields (JSON)
        Bot->>Excel: append_transaction()
        Bot->>TG: "✅ Saved: 250 PLN → Groceries"
    end

    alt /add step-by-step
        Bot->>TG: "Enter amount:"
        TG->>Bot: "250"
        Bot->>TG: currency keyboard
        TG->>Bot: "PLN"
        Bot->>TG: type keyboard (Expense/Income/Savings)
        TG->>Bot: "Expense"
        Bot->>Excel: load_lists() — categories
        Bot->>TG: category keyboard
        TG->>Bot: "Groceries"
        Bot->>TG: "✅ Confirm?" summary
        TG->>Bot: "✅ Save"
        Bot->>Excel: append_transaction()
        Bot->>TG: "✅ Saved"
    end

    alt Report command
        Bot->>Excel: load_data()
        Bot->>Bot: filter + aggregate _pln
        Bot->>TG: formatted report / chart PNG
    end
```

---

## Add Transaction — Step by Step

```mermaid
flowchart TD
    START(["/add or quick text"]) --> VALUE["Enter amount\n(positive number)"]
    VALUE --> CCY["Choose currency\n(from Lists col I)"]
    CCY --> TYPE["Choose type\nExpense · Income · Savings"]
    TYPE --> CAT["Choose category\n(from Lists col C)"]
    CAT --> PERSON["For whom?\n(from Lists col D)"]
    PERSON --> DATE["Enter date\n(YYYY-MM-DD or 'today')"]
    DATE --> DESC["Short description\n(or /skip)"]
    DESC --> RECUR["Recurring?\nYes / No"]
    RECUR --> CONFIRM["📝 Confirm summary"]
    CONFIRM -->|"✅ Save"| WRITE["append_transaction()\nwrite to Excel"]
    CONFIRM -->|"❌ Cancel"| END2([Cancelled])
    WRITE --> DUP{"Duplicate\ncheck"}
    DUP -->|"looks like duplicate"| WARN["⚠️ Possible duplicate\nSave anyway?"]
    WARN -->|"Yes"| SAVED(["✅ Saved"])
    WARN -->|"No"| END2
    DUP -->|"ok"| SAVED
```

---

## Bulk Import Flow (/bulk)

```mermaid
flowchart TD
    START(["/bulk"]) --> DRAFT{"Unfinished\ndraft on disk?"}
    DRAFT -->|yes| PREVIEW
    DRAFT -->|no| INPUT["Send photo / .txt file / pasted text"]
    INPUT --> CHUNK{"Large\nstatement?"}
    CHUNK -->|yes| PARTS["ai_parser: split at date headers,\nparse in chunks, merge results\n(progress notice sent)"]
    CHUNK -->|no| ONE["ai_parser: single parse\n(salvages truncated JSON)"]
    PARTS --> NORM
    ONE --> NORM["Normalize vs Lists sheet:\nfuzzy-map categories, unknown\npersons → description,\ncorrections reported"]
    NORM --> PREVIEW["Paginated preview\n(sorted by date, stable row numbers)"]
    PREVIEW -->|"2 category=Transport"| EDIT["Apply edit,\npersist draft, re-preview"]
    EDIT --> PREVIEW
    PREVIEW -->|"save or /save"| WRITE["async_append_batch()\n→ write_transaction_row per row\n→ atomic_save"]
    PREVIEW -->|"cancel"| DISCARD([Draft deleted])
    PREVIEW -->|"30 min timeout"| KEEP["Draft kept on disk\n— /bulk resumes it"]
    WRITE --> DONE(["✅ Saved — confirmation\nnames destination file"])
```

Drafts are stored per user as JSON on disk (max 50 pending rows), so they
survive conversation timeouts and bot restarts.

---

## Reports Menu Flow

```mermaid
flowchart LR
    MENU["📊 Reports\nmenu button"]
    MENU --> SUM["📅 Summary\nmonth income/expense/net"]
    MENU --> WEEK["📆 Week\nlast 7 days by category"]
    MENU --> BUD["💰 Budget\nvs actual this month"]
    MENU --> TOP["🏆 Top 5\nexpenses this month"]
    MENU --> SAV["💾 Savings\n6-month line chart"]
    MENU --> REP["📋 Report\nfull monthly list"]
    MENU --> CHART["📊 Chart\nbar chart vs budget"]
    MENU --> RANGE["📅 Range\nchoose date window"]

    RANGE --> R1["This month"]
    RANGE --> R2["Last month"]
    RANGE --> R3["Last 3 months"]
    RANGE --> R4["Last 6 months"]
    RANGE --> R5["This year"]
    RANGE --> R6["Custom…\nYYYY-MM-DD to YYYY-MM-DD"]
```

---

## Currency Rate Pipeline

```mermaid
flowchart LR
    EXT["🌐 frankfurter.dev\nlive exchange rates"]
    CMD["User: 🔄 Rates Refresh"]
    BOT["bot.py\nasync_update_currency_rates()"]
    EXCEL_LI["Excel\nLists col I/J"]
    LOAD["load_rates()\nfinds cols by header name"]
    COMPUTE["load_data()\n_pln = Value × rate"]

    CMD --> BOT
    BOT --> EXT
    EXT --> BOT
    BOT --> EXCEL_LI
    EXCEL_LI --> LOAD
    LOAD --> COMPUTE
```

---

## Storage Backends

```mermaid
flowchart TD
    BOT["bot.py"]
    FS["file_storage.py\nget_excel_path_for_reading()\nExcelFileContext"]

    BOT --> FS

    FS -->|"STORAGE_BACKEND=local"| LOCAL["📁 Local disk\nXLSX_PATH"]
    FS -->|"STORAGE_BACKEND=gcs"| GCS["☁️ Google Cloud Storage"]
    FS -->|"STORAGE_BACKEND=s3"| S3["☁️ S3-compatible\n(Oracle / R2 / AWS)"]

    LOCAL --> EXCEL["📊 Excel file"]
    GCS --> EXCEL
    S3 --> EXCEL
```

---

## Module Map

```mermaid
graph TD
    BOT["bot.py\nregisters handlers\nstarts polling"]

    BOT --> MENU_H["handlers/menu.py\nbottom nav + routing"]
    BOT --> ADD_H["handlers/add_conv.py\n9-step /add flow"]
    BOT --> EDIT_H["handlers/edit_conv.py\nedit last transaction"]
    BOT --> BULK_H["handlers/bulk_conv.py\n/bulk import flow\n+ per-user draft persistence"]
    BOT --> REP_H["handlers/reports.py\nall report commands + charts"]

    ADD_H --> AI["ai_parser.py\nNL + image → Transaction"]
    ADD_H --> DATA["data.py\nload_data, load_rates\nload_reference_data"]
    REP_H --> DATA
    REP_H --> FMT["formatters.py\nnumber formatting\nchart building"]

    DATA --> FS["file_storage.py\nstorage backend abstraction"]
    BULK_H --> AI
    ADD_H --> EXCEL_OPS["excel_ops.py\nappend_transaction\nasync_append_batch\nrecovery queue"]
    EDIT_H --> EXCEL_OPS
    BULK_H --> EXCEL_OPS

    EXCEL_OPS --> SCHEMA["excel_schema.py\ncolumn declarations\nwrite_transaction_row"]
    FS --> SCHEMA

    FS --> EXCEL["📊 Excel file"]
    EXCEL_OPS --> FS

    SCHED["scheduled_report.py\nGitHub Actions cron"] --> DATA
    SCHED --> FMT
```

---

## Scheduled Reports

```mermaid
gantt
    title Automatic reports (UTC)
    dateFormat HH:mm
    axisFormat %H:%M

    section Weekly (every Sunday)
    Weekly budget check : 17:00, 30m

    section Monthly (1st of month)
    Closed month summary : 07:00, 30m

    section Yearly (1st Jan)
    Annual summary : 17:00, 30m
```

---

## Key Design Rules

| Rule | Detail |
|---|---|
| **No hardcoded lists** | Categories, persons, currencies, types all read live from Lists sheet |
| **Single category list** | Lists col C is used for all transaction types (Expense, Income, Savings) |
| **_pln fallback** | If `Value (PLN)` formula cache is empty, recomputed from `Value × rate` |
| **No restart for data changes** | Any Lists sheet edit takes effect on the next bot message |
| **Restart required** | Only `.py` file changes or `.env` changes require a restart |
| **Storage agnostic** | Switch `STORAGE_BACKEND` in `.env` — no code change needed |
| **One column layout** | `excel_schema.py` declares every sheet's columns by header name — no hardcoded positions anywhere |
| **One row writer** | `write_transaction_row` (in `excel_schema.py`) is used by all three write paths: single add, bulk batch, recovery-queue replay |
| **Atomic saves** | Every workbook save goes through `atomic_save`: write to temp file → keep rolling `.bak` → `os.replace` — a crash can't corrupt the data |
| **Bulk drafts persist** | /bulk drafts are per-user JSON files on disk — they survive timeouts and restarts; `save`/`cancel` finalizes |
