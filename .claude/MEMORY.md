# Memory Index — budget-bot

Merged from `~/.ai-memory` template on 2026-06-16. Project-specific additions in `devops-memory.md` and `developer-memory.md`.

## Project context (read first — all roles)
- [project-memory.md](memories/project-memory.md) — who <YOUR_NAME> is, project overview, Excel structure, hosting decisions

## Universal (all roles)
- [conduct.md](memories/conduct.md) — position integrity, RCA format, no sycophantic openers
- [writing-style.md](memories/writing-style.md) — formatting and language rules
- [tooling.md](memories/tooling.md) — search-first, read-before-write, pagination
- [web-search-sources.md](memories/web-search-sources.md) — per-role search sources
- [memory-memory.md](memories/memory-memory.md) — rules for writing and storing memory entries

## Role memories
- [developer-memory.md](memories/developer-memory.md) — budget-bot code rules: column detection, storage patterns, Pydantic models, formula injection, ADD_DATE, duplicate detection
- [devops-memory.md](memories/devops-memory.md) — Oracle VM + Cloudflare R2 hosting, systemd deploy, GitHub Actions scope
- [orchestrator-memory.md](memories/orchestrator-memory.md) — role handoff flow, branch management, blocker handling
- [tester-memory.md](memories/tester-memory.md) — test strategy rules
- [architect-memory.md](memories/architect-memory.md) — architecture decision rules
- [reviewer-memory.md](memories/reviewer-memory.md) — PR review conduct
- [product-owner-memory.md](memories/product-owner-memory.md) — story and acceptance criteria rules
- [engineering-manager-memory.md](memories/engineering-manager-memory.md) — delivery and process rules
- [designer-memory.md](memories/designer-memory.md) — UI/UX rules
- [technical-writer-memory.md](memories/technical-writer-memory.md) — documentation rules

## Agents
- [agents/](agents/) — role agent definitions (developer, devops, tester, architect, reviewer, product-owner, designer, technical-writer, engineering-manager)

## Templates
- [templates/CLAUDE.md](templates/CLAUDE.md) — project-level CLAUDE.md template
- [templates/src.CLAUDE.md](templates/src.CLAUDE.md) — src directory CLAUDE.md template
- [templates/tests.CLAUDE.md](templates/tests.CLAUDE.md) — tests directory CLAUDE.md template

## Deployer
- [deployer/](deployer/) — Deploy-ClaudeUpdate.ps1, server.py, requirements.txt

## Project corrections log
- [corrections.md](corrections.md) — real-time corrections journal (append-only)

---

# Legacy corrections (pre-merge — kept for reference)

## Directory structure (enforced by user)

### ❌ Never create subdirectories unless there is a real reason
**What was done:** Created `src/` and `data/` automatically — `src/` for Python files,
`data/` as a placeholder for the Excel file.

**Why it's wrong:** This is a small single-purpose project. Nesting files in `src/`
adds path complexity everywhere (imports, Dockerfile, workflows, docs) with no benefit.
`data/` as a committed placeholder directory is meaningless — the file path is configured
via env var and can point anywhere.

**Correct approach:** Put files at the project root unless there is a concrete reason
to separate them (e.g. a genuinely separate package, generated output that should not
be committed). Ask before creating any subdirectory.

**Rule:** Flat is better than nested for small projects. No `src/`, no `data/`,
no `utils/`, no `helpers/` unless explicitly asked.

This file records mistakes made during development of this system and how they
were corrected. Any AI working on this project must read this file first and
must update it when new mistakes are made.

---

## How to Use This File

- Read it before making any changes to the workbook or bot
- When you make a mistake and it gets corrected, add it here immediately
- Keep entries short and specific — one lesson per entry
- Never remove entries — the history matters

---

## Naming Rules (enforced by user)

### ❌ Never use abbreviations in code that aren't universally known
**What was done:** Variables named `name_bg`, `row_bg`, `C_BG_ACCENT`, `hfont`,
`bfont`, `al()`, `thin()`, `hex_c`, `gborder()`, `shade`.

**Why it's wrong:** Anyone reading the code has to guess what `bg`, `al`, `thin`,
`hex_c` mean. Code should be self-explanatory.

**Correct approach:** Name things by what they are and what they do:
- `name_bg` → `field_name_background_color`
- `C_BG_ACCENT` → `ACCENT_TEAL_LIGHT` (what it looks like)
- `hfont()` → `white_header_font()`
- `bfont()` → `body_font()`
- `al()` → `left_aligned()` or `center_aligned()`
- `thin()` → `thin_border()`
- `hex_c` → `hex_color`
- `shade` → `alternating_row_color`

**Rule:** If you cannot understand a name without reading its definition,
rename it.

---

## Documentation Rules (enforced by user)

### ❌ Never add large inline comments to Python/script files
**What was done:** Added a 120-line module docstring to `bot.py`, docstrings
on most functions, inline comments throughout.

**Why it's wrong:** The user asked for clean, self-descriptive code — not
documentation embedded in the code. Documentation belongs in a separate
`DOCUMENTATION.md` file.

**Correct approach:**
- Keep Python files clean with no comments unless a line is genuinely surprising
- All explanations go in `DOCUMENTATION.md`
- All AI context goes in `.claude/SKILL.md`
- Functions must be named so their purpose is obvious — no docstring needed

**Rule:** If you need a comment to explain what a function does, the function
is probably named wrong.

---

## Excel Formula Rules

### ❌ Never hardcode column letters in formulas — detect from headers
**What was done:** Bot's `append_transaction()` used hardcoded column positions
(e.g. `ws.cell(r, 11, ...)` for Currency). When a new column was added earlier
in the sheet, everything shifted and broke.

**Correct approach:**
```python
headers = {ws.cell(1, c).value: c for c in range(1, ws.max_column + 2)}
def col(name, fallback):
    return headers.get(name, fallback)
ws.cell(r, col("Currency", 11), value)
```

**Rule:** Always detect column positions from header names, never hardcode them.

---

### ❌ Never add a new column without checking all formula ranges
**What was done:** Added a `Date` column at the front of MasterData. This shifted
all existing columns right by one. Dashboard formulas still referenced the old
column letters, so `$D` (was Type) now pointed to `$D` (now Value). All SUMIFS
returned zero and the dashboard showed nothing.

**Two bugs in one shift:**
1. The criteria range for Type (`$D`) now pointed to Value (numbers) — matching
   "Income" against numbers always fails
2. The sum range (`$C`) now pointed to Month (text) — summing text gives zero

**Correct approach:** After adding any column, grep every formula in every sheet
for column references and update them all. Run a manual verification:
calculate expected totals in Python and compare to formula results.

**Rule:** Adding a column to MasterData requires updating every Dashboard
and Monthly Summary formula that references MasterData by column letter.

---

### ❌ The Date Modified circular formula requires iterative calculation
**What was done:** The formula `=IF(D2<>"", IF(M2="", NOW(), M2), "")` was
written and the workbook saved. Users saw `0` in the column and thought it
was broken.

**Why:** Excel treats self-referencing formulas as circular errors by default
and returns 0. This formula is intentionally circular — it's a "set once"
pattern that only works with iterative calculation enabled.

**Correct approach:** Always include a visible warning wherever this column
is explained. The Guide sheet, the DOCUMENTATION.md, and the Dashboard all
show this note:
> File → Options → Formulas → Enable Iterative Calculation → Max Iterations = 1

**Rule:** Every time Date Modified is mentioned, include the iterative
calculation requirement.

---

### ❌ VLOOKUP range must be updated when new currencies are added
**What was done:** The initial VLOOKUP used `Lists!$G$2:$H$5` (4 currencies).
When AZN and CHF were added, the range was not updated in MasterData rows,
so those currencies returned `#N/A`.

**Correct approach:** Use a named range, or set the range to cover more rows
than currently needed (e.g. `$G$2:$H$20`), so adding currencies never
requires a formula update.

**Rule:** VLOOKUP ranges for extensible lists should always have headroom.

---

## Workbook Structure Rules

### ❌ Never separate Year and Month into manually-entered columns
**What was done:** Year and Month were originally separate text/number columns
that users filled in manually. This allowed mismatches between Date and Year/Month.

**Correct approach:** Year and Month are formula columns derived from Date:
- Year: `=IF(A2<>"", YEAR(A2), "")`
- Month: `=IF(A2<>"", CHOOSE(MONTH(A2), "Jan", "Feb", ...), "")`

**Rule:** Year and Month must always be formulas, never manually entered.
The only date column a user fills in is Date (col A).

---

### ❌ Savings rows must not have an Expense Tag / Category
**What was done:** Two early Savings rows had Category = "Other", which caused
them to appear in the category expense breakdown on the Dashboard.

**Correct approach:** Savings rows get Category = "Savings" and Income rows
get Category = "Income". These values are excluded from the expense breakdown.

**Rule:** The Category column for Savings and Income rows should reflect
the type, not a spending category.

---

## User Preferences (enforced repeatedly)

### Communication style
- Direct answers first, explanation after if needed
- No softening language when pointing out problems in data
- Flag overspending plainly: "Transport was 47% over budget in May"

### Code style
- No inline comments unless a line is genuinely surprising
- No docstrings — functions should be self-explanatory by name
- Short functions with clear names are better than long functions with comments
- Self-descriptive naming is the only documentation needed in code

### Documentation style  
- Keep explanations short — 2 to 3 sentences maximum per concept
- Use concrete examples from actual data, not hypothetical data
- Tables over prose for anything structural
- One place for each type of information — no duplication across files

### What goes where
| Content type | Lives in |
|---|---|
| How the system works | `DOCUMENTATION.md` |
| AI context and financial data | `.claude/SKILL.md` |
| Mistakes and corrections | `.claude/MEMORY.md` (this file) |
| How to use each Excel column | Guide sheet in the workbook |
| Code | `bot.py` — clean, no comments |

---

## Hardcoded domain values (enforced by user)

### ❌ Never hardcode any value that lives in the Excel file
**What was done:** `MONTHLY_BUDGET_PLN`, `CATEGORIES`, `MONTH_ORDER`,
`MONTH_ABBREVIATIONS`, `["Expense","Income","Savings"]`, `["<YOUR_NAME>","<FAMILY_MEMBER_1>","<FAMILY_MEMBER_2>","<FAMILY_MEMBER_3>"]`
were all hardcoded as Python constants in `bot.py` and `scheduled_report.py`.

**Why it's wrong:** Excel is the source of truth. If a category is added or a
budget changes in Excel, the bot would silently use stale data.

**Correct approach:** Everything reads from the Excel file at runtime via `file_storage.py`:
- Categories, months, types, persons, years → `load_lists(path)["categories"]` etc.
- Budget amounts → `load_budgets_from_excel(path)` (parses `=2100/$N$2` formulas)
- Currency rates → `load_rates()` (reads Lists col G:H)

**Rule:** If a value exists in the Excel file, it must come from there. No exceptions.

---

## Pydantic models (enforced by user)

### ❌ Never pass raw dicts between functions for structured data
**What was done:** `append_transaction(row: dict)` accepted an untyped dict.
`ctx.user_data["value"]`, `ctx.user_data["type"]` etc. were accessed by string key
with no type safety. Wrong key = silent KeyError at runtime, not at build time.

**Correct approach:** Use Pydantic models from `models.py`:
- `Transaction` — complete validated transaction ready to write
- `AddTransactionState` — partial state during /add conversation, stored as `ctx.user_data["state"]`

C# equivalent: DTOs with validation attributes.

**Rule:** Structured data between functions = Pydantic model. Raw dicts only for
ephemeral one-liners.

---

## Storage module naming

### ❌ gcs_storage.py was too specific — replaced by file_storage.py
**What was done:** `gcs_storage.py` only supported Google Cloud Storage.
Adding Oracle/S3 support would have required renaming and updating all imports.

**Correct approach:** `file_storage.py` supports `local`, `gcs`, and `s3` backends.
Backend selected by `STORAGE_BACKEND` env var. `bot.py` and `scheduled_report.py`
import only `get_excel_path_for_reading`, `ExcelFileContext`, `load_lists`,
`load_budgets_from_excel` — they are unaware of which backend is active.

**Rule:** Storage is an implementation detail. Callers never know where the file lives.

---

## ExcelFileContext usage

### ❌ Writing to Excel outside the context manager does not upload to GCS/S3
**What was done (risk):** `wb.save()` called after `with ExcelFileContext() as path:`
block had already closed — file saved locally but upload never happened.

**Correct pattern:**
```python
with ExcelFileContext() as excel_path:
    wb = load_workbook(excel_path)
    # make all changes
    wb.save(excel_path)
# upload happens here automatically on clean exit
```

**Rule:** `wb.save()` must be the last line inside the `with` block.
