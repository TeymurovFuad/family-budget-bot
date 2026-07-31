# Backlog

Findings from the whole-team review (Architect, Designer, Developer, PO, fresh-eyes reviewer)
of 2026-07-21 on branch `feat/bulk-import-draft-ordering`. Grouped by planned follow-up PR.
Items marked **[PR #3]** should land in the current bulk-import PR before merge.

## Wave 3 — Next work

Open items after Wave 2, regrouped by theme.

### Group 1 — Statement & import pipeline

Statement parsing, bulk preview, dedup UX, and person attribution.

- [x] **Statement profile saved with wrong decimal separator corrupts every amount (79.99 → 7999)** — fixed: (a) profile list shows separator (`bulk_conv.py:75-77`); (b) debit/credit-split message includes separator (`bulk_conv.py:284-287`); (c) "Fix settings" keyboard handles decimal/date/sign (`bulk_conv.py:345-351`); (d) `validate_proposal_against_samples` sanity check (`statement_profiles.py:568-602`, called at `bulk_conv.py:1818`).
- [x] **Statement imports categorize everything as 'Other'** — fixed: `_apply_ai_categorization` wired into `_do_finish_profile_parse` (`bulk_conv.py:485-487`).
- [x] **Bulk preview separator orphan at page break** — fixed: `_format_bulk_preview` strips trailing separators before flushing each page (`bulk_conv.py:1395-1397`).
- [ ] **Report chunking can break Markdown entities** — PARTIAL: `cmd_report` now splits at `━━━` section-break lines instead of raw 4000-char split (`reports.py:793-820`), preventing mid-span splits. Does not yet reuse the paginated-send helper from bulk_conv.
- [ ] **Message wording drifted from BACKLOG acceptance-criteria text** — footer format, skip-message phrasing, and row-range compression differ from the spec. PR #16 also retroactively edited BACKLOG.md to justify the changes, which is a process smell (spec says this wording is "never improvised"). Deliberate re-alignment pass, not urgent.
- [x] **Person attribution per import** — fixed: `_finish_profile_parse` returns `BULK_PERSON` state, `bulk_person_callback` stamps all rows (`bulk_conv.py:410-452`); also stamped in the AI text/image path (`bulk_conv.py:1898-1902`).
- [x] **`bulk_confirm` pre-existing backtick rendering bug** — fixed: removed backtick from "send \`save\` to store them all" message (no parse_mode on that reply). (`bulk_conv.py:2012`)
- [x] **`bulk_person_callback` empty-person path untested** — fixed: `TestBulkPersonCallback` in `test_e2e_flows.py` covers `bperson:` path and verifies confirmation text and `ctx.user_data["bulk_person"] == ""`.
- [x] **`bulk_confirm` invalid-input branch untested** — fixed: `TestBulkConfirmInvalidBranch` in `test_e2e_flows.py` covers unrecognised message, asserts no `parse_mode`.
- [x] **Stale PLN docstrings** — fixed: `scheduled_report.py:60`, `file_storage.py:208` updated.
- [x] **`scripts/rebuild_excel.py` and `scripts/make_template.py` hardcode PLN** — fixed: column header, descriptions, and comments updated to use base-currency terminology.
- [ ] **Bulk draft archival instead of naming change** — drafts (`data/bulk_drafts/{uid}.json`) ARE deleted after successful save and on cancel (verified). Improvement: on save, move to `data/bulk_drafts/archive/{uid}-{YYYYMMDD-HHMMSS}.json` instead of deleting — cheap audit trail of what each import contained; prune archive >6 months on startup.

### Group 2 — Cycles, reports & data quality

Cycle correctness, PLN neutrality, schema cleanup, and reporting gaps.

- [x] **Ad-hoc `/cycle detect <words>` keywords don't reach `cycle_totals`** — fixed in PR #74: `extra_keywords` param added to `cycle_totals` (`cycles.py:447`) and threaded through all call sites in `handlers/reports.py:66,81,647`.
- [x] **`test_detect_contains_match_on_bank_transfer_titles` fails on master** — fixed in PR #86: replaced Polish bank title "WYNAGRODZENIE ZA LIPIEC ACME SP Z OO" (never matched English salary keywords) with "SALARY PAYMENT JUL ACME LTD". (`tests/test_cycles.py:277`)
- [x] **`\b` fails for keywords with non-word edge chars** — fixed: `cycles.py:345` `salary_mask` and `handlers/cycle.py:545,548` `maybe_prompt_new_cycle` now use `(?<!\w)...(?!\w)` lookarounds.
- [x] **Duplicate boundary still re-uploads on remote backends** — fixed: `cycles.py:121-122` returns `None` when start date already exists; `handlers/cycle.py:589-598` sends "already recorded" and skips upload.
- [x] **Callback "yes" date not re-validated against future dates** — fixed: `handlers/cycle.py:583-587` checks `if start > date.today()` before recording.
- [x] **Sync workbook I/O in async handlers** — fixed: `cmd_cycle` no-args branch (`handlers/cycle.py:116`) and list branch (`handlers/cycle.py:137`) now use `run_in_executor`; `maybe_prompt_new_cycle` (`handlers/cycle.py:554`) also wrapped.
- [x] **lists_currency_range caps at row 100** — fixed: `excel_schema.py:119` defines `_EXCEL_MAX_ROW = 1048576`; `lists_currency_range` uses it as the open-ended upper bound (`excel_schema.py:128`).
- [x] **Remaining PLN in runtime messages** — confirmed clean: no PLN literals in `handlers/misc.py`, `handlers/add_conv.py`, or `handlers/reports.py` as of PR #84.
- [x] **Default-currency fallback hardcodes PLN** — fixed in PR #81: `data.py` `fillna`, `excel_schema.py` writer default and Value formula condition, `scheduled_report.py` fallback, and `load_dedup_evidence` null-currency fallback all route through `settings.DISPLAY_CURRENCY`.
- [x] **`goal_pln` field and "Goal (PLN)" column header in ListsSchema** — fixed in PR #81: `excel_schema.py` field renamed to `goal_base`, column header renamed to "Goal"; `scripts/migrate_base_currency_headers.py` updated with the header rename.
- [ ] **Derive Year/Month from Date by formula** — MasterData carries Date + Year + Month as three independent columns; Year/Month should be formulas (`=YEAR(A2)`, `=TEXT(A2,"mmm")`) or removed entirely with Dashboard SUMIFS rewritten against Date ranges. Touches every Dashboard formula, the writers, and the schema — do as its own PR with a migration script for existing rows.
- [ ] **Category rename support (simplify category names)** — PARTIAL: `/setup` rename flow calls `rename_category_in_workbook` covering MasterData + Dashboard; `scripts/rename_category.py` covers Lists + bulk drafts. Missing: merchant map not updated on rename; no standalone bot command (rename only via `/setup` wizard or CLI script).
- [ ] **`_apply_bulk_edit` revalidation path not tested** — lines 1608–1612: when `lists` is provided, `_revalidate_bulk_row` is called after a field edit; no test asserts the returned notes list is populated when a field edit triggers a cross-field validation warning. (`tests/test_wave3_group_b.py`, `handlers/bulk_conv.py`)
- [ ] **`_apply_bulk_edit` empty lists edge case silent** — when `lists={"categories": []}` is passed, category validation is silently skipped (`if categories and ...`); no test covers this branch. (`handlers/bulk_conv.py:1581`)
- [ ] **Enforce the 50-row limit post-merge, not pre-merge** (Copilot PR review) — `_draft_limit_reached` checks the EXISTING draft before merging, so a draft at exactly 50 can still merge a 185-row import and blow past the documented maximum. Decide the rule (cap total? reject overflow rows? paginate drafts?) and enforce it after `_merge_bulk_draft` with a clear message about what was and wasn't added.
- [ ] **Report every silent decision to the user, briefly** — standing principle: whenever the bot skips, corrects, deduplicates, or drops anything, the user gets one short line about it. Already done for validator corrections (🛡 auto-corrected list). Still needed: dedup skips ("↺ 3 rows skipped as already imported: …"), rows dropped at save due to Transaction validation errors (currently only shown as "Saved N of M" + first 5 errors), recovery-queue replays on startup ("re-applied 2 queued transactions"), and draft archival.
- [x] **Cycle Dashboard sheet** — implemented in `cycle_dashboard.py` (`ensure_cycle_dashboard`): cycle-label dropdown in B2, full category SUMIFS block; called from `record_cycle_start` and `record_cycle_starts_batch` (`cycles.py:110-111, 415-416`).

### Group 3 — Infrastructure, schema & quality

Test coverage gaps, module size, AI output contract, and tooling quality.

- [x] **DeepSeek output as typed model** — done: `ParsedTransaction` Pydantic model at `ai_parser.py:234`; `_normalize_ai_rows` validates every row via `ParsedTransaction.model_validate` (`ai_parser.py:266`).
- [ ] **Off-peak batching** — PARTIAL: `is_off_peak()` implemented at `ai_parser.py:26-32`; currently only logs a cost warning inside `DeepSeekProvider._chat` (`ai_parser.py:513`). No actual deferral or scheduling to the off-peak window yet.
- [ ] **Peak-time user prompt + task scheduling** *(discussion topic)* — when a user triggers a command that requires an AI call during peak hours, notify them: "It's currently peak time — AI calls cost more right now. Run now, or schedule for off-peak (after 16:30 UTC)?" If the user chooses to wait, hold the task and execute it automatically when the off-peak window opens. Needs: reliable task queue (likely the SQLite era), a scheduler (APScheduler or PTB's JobQueue), and a way to resume the original conversation context on delivery. `is_off_peak()` helper from PR #71 is the foundation. (`ai_parser.py`, `bot.py`, PTB JobQueue)
- [ ] **Hard cap 300 lines per production module** — current offenders: `handlers/bulk_conv.py` (2132), `handlers/reports.py` (1242), `statement_profiles.py` (641), `handlers/setup_conv.py` (729), `ai_parser.py` (704), `handlers/cycle.py` (607), `cycles.py` (585), `file_storage.py` (485), `handlers/add_conv.py` (453), `storage_backends.py` (311). Split by cohesion, not line count alone. Exempt: test files and generated/schema files.
- [x] **/start hostile-name test doesn't run the balance checks** — done: `test_start_escapes_hostile_first_name` calls `assert_valid_markdown_v2` which runs both `find_unescaped_reserved` and `assert_markup_balanced` (`tests/mdv2_helpers.py:72-76`).
- [x] **No test for empty first_name → "there" fallback** — done: `test_start_empty_first_name_falls_back_to_there` at `tests/test_help_markdown.py:94-104`.
- [x] **Escape-stripping order vs backslashes inside code spans** — done: `test_validator_escaped_backtick_inside_code_span` covers this regression at `tests/test_help_markdown.py:195-205`.
- [x] **Extend the markdown validator to every static MarkdownV2 reply** — done: `cmd_setcurrency` unknown-currency reply covered by `test_setcurrency_unknown_currency_reply_is_valid_markdown_v2`; all 17 `<cmd> help` texts covered by parametrized `test_cmd_help_subcommand_is_valid_markdown_v2` (`tests/test_help_markdown.py:150-167`).
- [x] **`test_cleanup_old_logs_removes_rotated_files` missing negative-path assertions** — done: `tests/test_logger.py:50-85` asserts all four cases: old rotated deleted, recent rotated retained, base log retained, unrelated log retained.
- [x] **`_decode_positional_array` null-amount contract undefined** — done: `ai_parser.py:258-263` explicitly guards `if arr[1] is None: return None`; documented in function docstring.
- [x] **`_salvage_rows` fallback path untested** — done: `test_salvage_rows_falls_back_to_object_salvage_for_legacy_format` at `tests/test_ai_parser.py:527-535`.
- [x] **[PR #3] Preview edits not persisted to draft file** — done in PR #48: `bulk_confirm` calls `_save_bulk_draft` after each edit (`handlers/bulk_conv.py:1979-1984`).
- [x] **`CATEGORY_TYPE_HINTS` dict** — done: defined at `handlers/setup_conv.py:56`; used in `handlers/add_conv.py:15,70` to pre-select transaction type.
- [x] **Monthly Summary sheet never updated by the bot** — done: `file_storage.py:420` calls `ensure_monthly_summary_rows_from_masterdata(wb)` after writing all batch rows, covering multi-month imports.

### Group F — SQLite + web UI (deferred)

Full SQLite shadow store and web UI — phased integration, deferred until bot core is stable.

See "Roadmap: Web UI + SQLite — phased integration" below for the full Cycle W1–W4 design.

---

## Planned runs — grouped 2026-07-25

150 open items grouped into 3 runs. Items belong to the run they are **first meaningfully addressed in**; detail lives in the sections below.

### Run 1 — "Unblock the re-import" (~20 items)
Must ship before the user re-imports 1,400 historical rows.

**Pre-shipped before the run (PRs #39–#42):**
- [x] Statement decimal separator corrupts every amount *(Bugs 2026-07-25)* — PR #39
- [x] Statement imports categorize everything as 'Other' *(Bugs 2026-07-25)* — PR #40

**Shipped in PR #43 (merged 2026-07-26):**
- [x] Quick-add doesn't recognise Savings as transaction type *(Bugs 2026-07-24)*
- [x] Register PTB error handler — failures are currently silent *(markdown-validator review notes PR #37)*
- [x] Salary-mask: Description match is unconditional OR *(salary-mask review notes PR #36)*
- [x] Salary-mask: Exact-match brittle for statement imports *(salary-mask review notes PR #36)*
- [x] Salary-mask: Test durability pin *(salary-mask review notes PR #36)* — verified already present (`tests/test_cycles.py`)
- [x] [PR #3] Draft-limit path discards just-parsed input *(PR #3 bulk-import bugs)*
- [x] Formula injection via descriptions — bulk/quick/edit bypass sanitizer *(parallel-review findings)*

**Still open:**
- [x] Salary-mask: Empty `SALARY_CATEGORY` degenerates *(fixed: `cycles.py:325-326` strips/drops blank entries; `cycles.py:342-344` adds defense-in-depth guard in `salary_mask`)*
- [x] Monthly Summary sheet never updated by the bot *(fixed PR #38 — bot appends SUMIFS rows on every write)*
- [x] Recovery-queue corruption bricks startup *(fixed in prior PRs — atomic write + .corrupt quarantine in file_storage.py)*
- [x] Partial bulk save loses failed rows *(fixed in prior PRs — failed rows kept in draft with retry message)*
- [x] [PR #3] Preview edits not persisted to draft file *(fixed: `handlers/bulk_conv.py:1987` calls `_save_bulk_draft(uid, parsed)` after every edit)*
- [x] [PR #3] Recovery replay writes Date as text string *(fixed: `excel_ops.py:114-120` rehydrates ISO date string → `datetime.date` before writing)*
- [ ] [PR #3] Cosmetic cleanup *(PR #3 bulk-import bugs)*

### Run 2 — "Complete the cycles feature" (~35 items)
Cycles is half-done: /summary and /budget are cycle-scoped, reports aren't, picker is missing.

**Report gaps:**
- [x] `/report` still calendar-based *(fixed PR #47)*
- [x] `/top` still calendar-based *(fixed PR #47)*
- [x] `/savings` still calendar-based *(fixed: `handlers/reports.py:703-720` uses `cycle_periods` + `cycle_totals` when `settings.BUDGET_CYCLE` is set)*
- [x] `check_budget_alert` still calendar-scoped *(fixed PR #47)*

**/summary picker UX (5 items from agreed design):**
- [x] free-form args *(done PR #45)*
- [x] bare /summary three-zone *(done PR #45)*
- [x] /summary jul resolves ledger *(done PR #45)*
- [x] range support *(done PR #45)*
- [x] year overflow paging *(done PR #45)*

**Cycle Dashboard + remaining design (8 items):** Cycle Dashboard sheet, sync check, lazy backfill on report, `none this month`, candidate window when detection finds nothing, past/entire-period walk, before-first-boundary bucket, multiple salary rows picker

**Cycle correctness fixes (~12 items from PR #30/#32 review notes):** stale row-index race in /delete and /edit, date edit leaves Year/Month stale, bare `/cycle` write-gated for non-owners, auth_write spinner on CallbackQueryHandler, timezone inconsistency in cycle bounds, duplicate labels for two cycles in one month, `detect:stop` wrong count, "Two salary payments" hardcoded for 3+, `detect_candidates` not cleared on re-entry, no currency label on detect amounts, ad-hoc keywords don't reach `cycle_totals`, user-editable label interpolated raw into Markdown

**Currency / PLN neutrality sweep (4 items):** remaining PLN in runtime messages, default-currency fallback hardcodes PLN, `goal_pln` field in ListsSchema, AI parser prompt hardcodes Polish zł/zl

### Run 3 — "Quality, infra, and long tail" (~95 items)
No hard deadline — work through these incrementally.

#### Wave 2 — parallel agent grouping (planned 2026-07-27)

Six groups by file domain — agents A–E chain sequentially (each PR targets the previous branch); F is independent and can run alongside any group.

**Chain order: A → B → C → D → E** (merge A first, B targets A's branch, etc.)
**F runs independently** at any time — all new files, zero collision.

| Group | Files owned | Items |
|---|---|---|
| **A — Storage layer** | `file_storage.py`, `excel_schema.py`, `data.py` | Split file_storage, TTL cache, JSONL queue, lost-update protection, typed DeepSeek model, derive Year/Month formula, per-operation audit line |
| **B — Bulk/import pipeline** | `handlers/bulk_conv.py`, `ai_parser.py`, `validators.py`, `statement_profiles.py` | Compact AI output, extraction/categorization split, dedup-before-parse, prompt caching, bulk drop/skip UX, PR#3 cosmetic cleanup, dedup wording drift, lone-separator, profile design |
| **C — Conversation handlers** | `handlers/add_conv.py`, `handlers/quick_conv.py`, `handlers/edit_conv.py`, `handlers/delete_conv.py` | /add default-and-confirm, quick-add one-tap recovery, recurring detection, person attribution, local fast-path quick-add, empty SALARY_CATEGORY fix |
| **D — Reports + cycles** | `handlers/reports.py`, `handlers/cycle.py`, `cycles.py`, `scheduled_report.py` | /savings cycle-aware, lazy backfill, none-this-month, candidate window, past/entire-period walk, before-first-boundary, multi-salary picker, timezone fix, report chunking |
| **E — Infra + scripts** | `scripts/`, `logger.py`, `bot.py` (wiring only) | Log retention, draft archival, magic numbers sweep, 300-line cap, recovery replay Date fix, off-peak batching |
| **F — Web UI** | `web/` (new), `sqlite_ops.py` (shipped in PR #96, with `sqlite_types.py`, `storage_protocol.py`, `storage_facade.py`) | SQLite shadow store → read API + UI → web write path → flip SQLite primary (Cycles W1–W4) |

**Collision rules:**
- `bot.py` — Group E only, wiring/constants changes only
- `file_storage.py`, `excel_schema.py` — Group A exclusively; B/C/D call but never edit during the same run
- Tests mirror their module: `tests/test_bulk_*` → B, `tests/test_handlers_*` → C, etc.

### /setup onboarding — agreed design (brainstorm 2026-07-27)

Goal: user sets XLSX_PATH in .env, runs /setup (or /start with no file present), bot creates the workbook from the bundled template and walks through full configuration. No spreadsheet editing required.

**Entry points:** `/start` detects missing file and hands off to the setup flow. `/setup` also works as a direct command. Both use the same ConversationHandler in `handlers/setup_conv.py`.

**File creation:** `create_workbook_from_template(dest)` in `file_storage.py` — atomic copy from `data/Expenses_Template.xlsx`. Parent directory created if missing. Clear error if path not writable or `XLSX_PATH` not set.

**Workbook state detection (3 cases at handler entry):**
1. File missing → create from template, run onboarding.
2. File exists, Lists!C populated → "already configured" message (no re-run).
3. File exists, Lists!C empty → skip file creation, run onboarding.

**Auth:** only `ALLOWED_TELEGRAM_IDS[0]` (primary user) can run `/setup`.

**Default categories (14, written to Lists!C on first run):**

| # | Name | Type |
|---|------|------|
| 1 | Salary | Income |
| 2 | Other Income | Income |
| 3 | Housing | Expense |
| 4 | Groceries | Expense |
| 5 | Transport | Expense |
| 6 | Utilities | Expense |
| 7 | Health | Expense |
| 8 | Dining Out | Expense |
| 9 | Shopping | Expense |
| 10 | Entertainment | Expense |
| 11 | Subscriptions | Expense |
| 12 | Travel | Expense |
| 13 | Savings | Savings |
| 14 | Other | Expense |

**Conversation flow (7 steps):**
1. Welcome — bot creates file silently, auto-advances.
2. Category review — numbered list displayed; buttons: `Rename a category` · `Add a category` · `Done with categories`.
3. Rename — bot shows all categories as inline buttons (emoji+name, 2 per row); user taps one → sends new name → list refreshes. Loops back to Step 2.
4. Add — user sends name → picks type from `[Expense]` `[Income]` `[Savings]` → appended, list refreshes. Loops back to Step 2.
5. Budget per category — Expense categories only, one at a time; 0 = no limit, default 0; non-numeric input re-prompts.
6. Currency setup — buttons `[USD]` `[EUR]` `[RUB]` `[TRY]` `[CNY]` `[Other]`; user picks main display currency; `[Other]` → free-text 3-letter code.
7. Summary + done — lists final categories, currencies, budgets; triggers rate fetch automatically; button: `Done`.

Cancel button available from Step 2 onward — exits, keeps partial writes, tells user to re-run `/setup`.

**What gets updated on every category add/rename (atomic, one workbook save):**
- `Lists!C` — the category row itself
- Dashboard category SUMIF block — full rebuild from final list (same pattern as `sync_cycle_dashboard_categories`)
- Cycle Dashboard category block — `sync_cycle_dashboard_categories(wb)` called after rebuild
- MasterData dropdown validations — `extend_validation_ranges` (already exists)
- `merchant_map.json` — empty at setup time, no action needed

**Category type hint (not enforcement):** A `CATEGORY_TYPE_HINTS` dict maps default category names to their typical type (e.g. `"Salary" → "Income"`). When a user picks a category in `/add` or quick-add, the bot pre-selects the hinted type. User can override. Enforcement (reject mismatches) is a follow-up item.

**Display currency:** Written to `data/user_prefs.json` (same file `/setcurrency` uses) — not to `.env`. No bot restart needed. Env var `DISPLAY_CURRENCY` remains the server-default fallback.

**Rate fetch:** Triggered automatically at end of setup (Step 7). If it fails, rates stay 1.0 and user is warned.

**Category edits post-setup:** Not supported as a bot command — use `scripts/rename_category.py` on the server. Full in-bot rename/delete support deferred to the SQLite+web UI era (data migration is trivial with SQL; dangerous with Excel mid-use).

**No-file guard for normal commands:** No hard block. `ExcelFileContext` raises `FileNotFoundError` naturally; global error handler in `bot.py` catches it and replies "No workbook found. Run /setup to create one."

**Files to create/modify:**
- `handlers/setup_conv.py` (new) — ConversationHandler + all step callbacks
- `file_storage.py` — add `create_workbook_from_template`
- `bot.py` — register setup ConversationHandler; add FileNotFoundError catch in global error handler
- `states.py` — add SETUP_* state constants
- `tests/test_setup_conv.py` (new)

**Open items (resolve before implementation):**
- [ ] Confirm `data/Expenses_Template.xlsx` is committed and present at runtime (it is — verify before starting)
- [x] Dashboard category SUMIF rebuild function: fixed: `excel_schema.py:252-278` `write_category_sumif_block` is already shared; both Dashboard and Cycle Dashboard call it
- [ ] `CATEGORY_TYPE_HINTS` dict: implement as part of this PR or as a follow-up to the data-validation PR

- **Infra/performance (7):** .bak leak, reference-data TTL cache, JSONL recovery queue, lost-update protection, `_load_bulk_drafts` reads every user, split `file_storage`, DeepSeek output as typed model
- **E2E test coverage (3):** golden-path, edge-case, CI regression guard
- **Token economy (6):** compact AI output, split extraction/categorization, local fast-path quick-add, dedup before parse, prompt byte-identical caching, off-peak batching
- **UX (6):** person attribution per import, recurring detection, /add default-and-confirm, bulk edit drop/skip UX, quick-add one-tap recovery, report chunking markdown split, edit_conv currency keyboard
- **Statement profile design + PR #18 review notes (~25):** profile contents spec, first-upload AI flow, known-format zero-token path, bank-redesign handling, plus all dead-code/test findings from PR #18
- **Dedup review notes (5):** OOB feedback, wording drift, footer redundancy, denominator bug, double file read
- **Data-validation review notes (2):** lone-separator reinterpretation, bulk revalidation skipped
- **Code clarity + module size (4):** magic numbers sweep, 300-line cap, split offenders
- **Draft + log lifecycle (3):** draft archival, log retention, per-operation audit line
- **Schema simplification (2):** derive Year/Month from Date by formula, category rename support
- **Parallel-review remaining (5):** repair scripts unsafe, dual logging, draft limit porous, range-text listener crosstalk, fix_import_errors rule-3 ordering
- **Misc (~10):** /export exception leak, file-size guard, quarantine rename retries forever, legacy script cleanup, rename_category.py gaps, lists_currency_range row 100 cap, markdown-validator extension, /start test gaps, profile review notes PR #27

---

## Session handoff — read this first if resuming in a new session

> **Always verify before acting — this note is a snapshot, not live state.**
> Run `gh pr list --repo TeymurovFuad/family-budget-bot --state open` and
> `git log --oneline -5` first; trust those over anything written here.
> Update this section at the end of every session so the next one starts clean.
> *(Last updated: 2026-07-27 — PRs through #50 merged; Run 3 Wave 1 complete)*

### PR state at last update
- **PRs #1–#50 merged.**
- **PR #50 merged 2026-07-27**: /setup onboarding — 7-step ConversationHandler
  (`handlers/setup_conv.py`): creates workbook from template, category add/rename,
  budget-per-category, currency setup, summary + rate fetch. Category types persisted
  to Lists sheet. `file_storage.create_workbook_from_template` (atomic, _replace_with_retry).
  `excel_schema.py`: shared `write_category_sumif_row/block`, `sync_dashboard_categories`.
  `states.py` SETUP_* range. Error guards: _load_existing_state try/except, ValueError
  on malformed callback, falsy message guard, non-owner /start with missing workbook.
  28 new tests; 1151 total passing.
- **PR #49 merged 2026-07-27**: Tests and code quality — `tests/mdv2_helpers.py`
  (assert_valid_markdown_v2, assert_markup_balanced); `tests/test_e2e_flows.py`
  (60 E2E tests across all major commands); `tests/test_help_markdown.py` rewritten
  with all 17 help subcommands parametrized; `tests/test_repair_scripts.py` (new).
  fix_import_errors.py rule chaining + .bak write-once; rename_category.py formula
  + draft rewrite; one-time migration scripts deleted; magic-number constants renamed.
  1239 total passing.
- **PR #48 merged 2026-07-27**: Bug fixes — bulk/dedup: _save_bulk_draft after edit,
  _parse_row_targets returns (list,list), _bulk_footer fixed, denominator fixed, single
  file read per receive, bulk_confirm guard. validators.parse_amount returns (float,
  list[str]). update_transaction_field accepts dict (Year/Month sync moved to
  edit_conv). Stale row-index re-verify in edit+delete. /export generic error + 50MB
  guard. Empty-categories guard in quick_conv. handle_range_text group=-1 per-chat.
  .bak skip for temp files; quarantine one-retry. +16 tests; 1152 total passing.
- **PR #47 merged 2026-07-27**: Cycle-aware reports — /report, /top, check_budget_alert
  use _current_cycle_bounds() when BUDGET_CYCLE=1. auth_write answers callback before
  returning on denial. _deny_non_owner null-safe. detect:pick ownership check. deferred
  imports hoisted. /help wording fixes. async_record_cycle_start returns str|None.
  detect amounts show display currency. _dedup_cycle_label appends #2/#3 for same-month.
- **PRs #1–#46**: see previous session notes above.
- **PR-title rule is live**: titles become the Telegram changelog verbatim —
  write them as plain-language outcomes, no `feat:`/`fix:` prefixes, and
  always squash-merge. See `.github/pull_request_template.md`.

### Standing mechanics (doesn't change session to session)
- **Push/merge**: `fuadteymurov` is NOT a collaborator on
  `TeymurovFuad/family-budget-bot`. Pushes go to `fork` remote
  (`fuadteymurov/family-budget-bot`), PRs opened
  `--head fuadteymurov:branch --base master`. **Merging requires the repo
  owner** — always ask the user; never assume it can be automated.
- **Worktree isolation**: always give each parallel file-editing agent its own
  `git worktree add` — shared worktrees caused branch entanglement this session.
  See `.claude/memories/orchestrator-memory.md` "Parallel agent isolation".
- **PR chaining not usable in fork workflow**: base branches must exist on upstream
  (`TeymurovFuad/family-budget-bot`); feature branches only exist on the fork. Use
  sequential merge + immediate rebase-per-merge instead.
- **Rebase test strategy**: no conflicts → skip tests; conflicts resolved → run only
  the affected modules, not the full suite.
- **DeepSeek tokens are paid** — budget ~20 live API calls per debug session;
  prefer mocked tests. See `.claude/memories/project-memory.md`.

### Next up (priority order — update when items complete)
  1. ~~Run 3 Wave 1 (PRs #47–#50)~~ — ✅ merged 2026-07-27.
  2. **Run 3 Wave 2 — infra/performance**: reference-data TTL cache, JSONL recovery
     queue, split file_storage, typed DeepSeek model, lost-update protection,
     _load_bulk_drafts read single user. See "Follow-up PR: infra & performance".
  3. **Run 3 Wave 2 — token economy**: compact AI output format, extraction/categorization
     split, local fast-path for quick-add, dedup-before-parse, prompt caching, off-peak
     batching. See "Follow-up PR: token economy".
  4. **Run 3 Wave 2 — UX**: person attribution per import, recurring detection, /add
     default-and-confirm, bulk drop/skip UX, quick-add one-tap recovery, report chunking.
  5. **Run 3 Wave 2 — statement profile design**: profile contents spec, first-upload AI
     flow, known-format zero-token path, bank-redesign handling, PR #18 dead-code findings.
  6. **Remaining open items**: schema simplification (Year/Month formula derive), draft+log
     lifecycle (archival, retention, audit line), code-clarity sweep (300-line cap),
     currency neutrality sweep, cycle follow-ups (lazy backfill on report, none-this-month,
     candidate window, past/entire-period walk, before-first-boundary bucket, multi-salary picker).
  7. **Optional**: rename `Żabka` fixture in `tests/test_merchant_map.py` to match the
     "Old Tbilisi" doc-example rename (PR #14) — tiny, deferred.

### Recent context
- PR #30 (budget cycles core) squash-merged 2026-07-24 after a rebase that
  consolidated it with the parallel PR #23 Phase-1 implementation. 17
  unchecked review findings queued in the two cycles review-notes sections.
- PRs #23, #24, #27 merged 2026-07-23: budget cycles Phase 1, cycles docs,
  and debit/credit split columns + profile deletion.
- Budget cycles Phase 1 (PR #23) merged 2026-07-23. DOCUMENTATION.md, README,
  and BACKLOG updated in the follow-up docs PR. Phase 2 items (Cycle Dashboard,
  `/cycles detect`, `/summary` picker UX) remain pending — see "budget cycles —
  agreed design" section.
- Bank-statement profiles (PR #18) merged 2026-07-23. DOCUMENTATION.md and
  README updated post-merge. Test-suite hardening landed in the same PR:
  handler-test auth bypass is now immune to pytest collection order (reload
  trick mirrored from test_write_gate.py).
- Dedup v2 (PR #16) merged 2026-07-23. Five non-blocking findings queued in
  "dedup review notes (PR #16)" below. DOCUMENTATION.md updated for the new
  `drop`/`keep` grammar (PR #17).
- Security/PII audit 2026-07-22: clean. One low-priority nit: `deploy/budget-bot.service`
  hardcodes `User=ubuntu` — reveals VM OS-user convention, no IP/credentials.

## Bugs (confirmed live, 2026-07-24)

- [x] **Quick-add doesn't recognise Savings as transaction type** *(fixed in PR #43)* — user typed
      "2380 added to savings 23 July 2026"; bot replied: ❌ Unknown category
      'Savings'. Use one of: Groceries, Housing, …
      Root cause: the AI parser maps "savings" / "saved" to the Category field
      instead of the Type field. "Savings" is a valid TxnType (Lists sheet B
      column), not a category.
      Expected: parser sets type="Savings", category="" (let user pick or
      default to "Other"); the shared validator should also catch a
      type=Expense / category=Savings mismatch and promote type.
      Workaround: use /add and manually pick Type=Savings step by step.

- [x] **/cycle detect shows wrong salary candidates for Jul 2024** — window
      was anchored at the 20th, missing salaries paid on day 1. Fixed:
      `window_start` now set to the 1st of the target month.
      (`cycles.py` `detect_cycle_candidates`)

## Bugs (confirmed live, 2026-07-25)

- [x] **/cycle detect finds nothing when 'Salary' is in Description, not
      Category** — real MasterData salary rows carry empty Category and
      "Salary" in Description; the PR #35 detect filtered on Category only and
      reported "nothing to backfill" against 1400+ imported rows. Fixed:
      shared `cycles.salary_mask()` matches the salary keyword in Category OR
      Description; applied in `detect_cycle_candidates`, `cycle_totals`
      (unaccounted math), and the live salary prompt
      (`maybe_prompt_cycle_start`).

- [ ] **Statement profile saved with wrong decimal separator corrupts every
      amount (79.99 → 7999)** — a profile stored `decimal_separator: ","` for
      a dot-decimal bank; `_normalize_amount` strips "." as thousands. 1400
      rows imported with 100× inflated values. Three compounding gaps:
      (a) profile list (`/bulk profile`) doesn't show the separator;
      (b) debit/credit-split proposal message omits the separator entirely;
      (c) "Fix a column" can only remap columns — separator, date format, and
      sign convention cannot be corrected in the confirm flow.
      Also add a sanity check: sample amount values like `79.99` (2 digits
      after ".") contradict comma-decimal — validate proposal against samples
      before saving. (`statement_profiles.py`, `handlers/bulk_conv.py`)

- [ ] **Statement imports categorize everything as 'Other'** — `parse_statement`
      returns no category; `_normalize_parsed_rows` defaults empties to
      "Other"; merchant memory only helps for known merchants (empty on first
      import). The AI-categorization step for unknown merchants (BACKLOG
      "known format" design: "AI only for unknown merchants") was never wired
      into the statement path. 1400 rows imported as Other.
      (`handlers/bulk_conv.py` `_finish_profile_parse`)

- [x] **Deployed bot stops replying to commands (file uploads still work)** —
      root cause found in VM logs: /help replied with MarkdownV2 containing an
      unescaped `=` (`BUDGET_CYCLE=1` — the `_` was escaped, the `=` was not);
      Telegram rejected with BadRequest and the user saw nothing. Second
      occurrence of this bug class (PR #32 fixed one instance and shipped this
      one in the same file). Fixed in the help-markdown PR: offending strings
      moved into code spans; new `tests/test_help_markdown.py` validates the
      full /help text offline so any unescaped reserved char fails CI.
      Follow-up: register a PTB error handler (`Application.add_error_handler`)
      so send-failures reply with a fallback plain-text message instead of
      silence — "No error handlers are registered" appears in the same log.

- [ ] **Monthly Summary sheet is never updated by the bot** — nothing in
      runtime code writes to Monthly Summary; its per-month formula rows are
      created once by `scripts/rebuild_excel.py`. Any transaction saved for a
      month that has no pre-built row (bulk-imported history, or simply a new
      month starting) appears nowhere in the sheet. Confirmed live 2026-07-25:
      1400 imported rows spanning 2024 left Monthly Summary empty.
      Re-confirmed 2026-07-27: workbook created via /setup + bulk AI import had
      only 12 pre-built rows (Jan–Dec 2024); 2025/2026 data invisible in the sheet.
      Options: (a) bot appends a formula row for unseen Year/Month on save;
      (b) rebuild-script-style sync check like the planned Cycle Dashboard
      sync; (c) convert the sheet to dynamic formulas (SUMPRODUCT over open
      ranges) that need no per-month rows. Decide with the schema-simplification
      PR ("Derive Year/Month from Date by formula" — same territory).
      **Priority: P2** — visible blank sheet misleads the user about their data.

- [x] **Cycle new-boundary prompt omits year — ambiguous in December** — fixed: `handlers/cycle.py:82` `_day_month` now returns `f"{d.day} {d.strftime('%b %Y')}"` (year always included).
      (`handlers/cycle.py` `_day_month`, also used in `/cycle list` output)

## Follow-up: salary-mask review notes (PR #36, 2026-07-25)

- [x] **Description match is an unconditional OR** *(fixed in PR #43)* — an Income row with
      Category "Freelance" and Description "Salary" counts as salary,
      inflating unaccounted math. Safer: fall back to Description only when
      Category is empty/blank. Same in `maybe_prompt_cycle_start`.
      (`cycles.py` `salary_mask`)
- [x] **Empty `SALARY_CATEGORY` degenerates** — fixed: `cycles.py:325-326` strips/drops blank entries in `cycle_detect_keywords`; `cycles.py:342-344` adds defense-in-depth guard in `salary_mask`. (`cycles.py` `salary_mask`)
- [x] **Exact-match on Description brittle for statement imports** *(fixed in PR #43 — word-boundary contains match)* — bank
      salary rows often read "SALARY JUL 2024" / "ACME PAYROLL"; the exact
      `== "salary"` match misses them — the same failure mode PR #36 fixed.
      Check what the user's bank statement actually titles the salary transfer
      before the re-import; if longer than the bare word, switch to a
      word-boundary contains match. (`cycles.py` `salary_mask`)
- [x] **Test durability** *(verified during PR #43: pin already present in `tests/test_cycles.py`)* — `test_detect_matches_salary_in_category_without_
      description_column` relies on `_cycle_df()` incidentally lacking a
      Description column; pin with `assert "Description" not in df.columns`.
      (`tests/test_cycles.py`)

## Follow-up: re-review notes (PR #36/#37 second pass, 2026-07-25)

- [x] **Ad-hoc `/cycle detect <words>` keywords don't reach `cycle_totals`** — done in PR #74: `extra_keywords` param added to `cycle_totals` and threaded through all call sites (`handlers/reports.py:66,81,647`).
- [x] **`\b` fails for keywords with non-word edge chars** — fixed in PR #87: `cycles.py:345` and `handlers/cycle.py:548-551` use `(?<!\w)...(?!\w)` lookarounds.
      (`cycles.py` `salary_mask`)
- [ ] **Keyword set widens the Description-OR blast radius** — extends the
      existing "Description match is unconditional OR" note above: with more
      keywords, more non-salary income descriptions can trigger the prompt.
- [x] **/start hostile-name test doesn't run the balance checks** — done: `test_start_escapes_hostile_first_name` calls `assert_valid_markdown_v2` which runs balance checks via `mdv2_helpers.py:72-76`.
- [x] **No test for empty first_name → "there" fallback** — done: `test_start_empty_first_name_falls_back_to_there` at `tests/test_help_markdown.py:94-104`.

## Follow-up: markdown-validator review notes (PR #37, 2026-07-25)

- [x] **Escape-stripping order vs backslashes inside code spans** — done: `test_validator_escaped_backtick_inside_code_span` covers this at `tests/test_help_markdown.py:195-205`.
- [x] **Extend the markdown validator to every static MarkdownV2 reply** — done: `cmd_setcurrency` and all 17 `<cmd> help` texts covered by parametrized tests at `tests/test_help_markdown.py:109-167`.
- [x] **Register a PTB error handler** *(fixed in PR #43)* — "No error handlers are registered"
      in the VM log; a global `Application.add_error_handler` that logs and
      replies with a plain-text fallback would have surfaced the /help
      failure to the user on day one instead of silence. (`bot.py`)

## Roadmap: Web UI + SQLite — phased integration (added 2026-07-26)

Goal: a simple web UI that mirrors the Excel view, backed by SQLite, introduced
incrementally so the bot never breaks and the household can switch gradually.
Excel stays the source of truth until Cycle 4 explicitly flips it.

Each cycle is a self-contained deliverable that ships value on its own.
Cycles must be done in order — each depends on the previous.

> **Progress (PR #96, Cycle S1 Phase 1):** the storage foundation shipped ahead of W1 —
> `sqlite_ops.py` (WAL schema: transactions/categories/persons/rates/goals/sync_log, table-name
> constants, `sqlite_types.py` StrEnums + `TransactionRow` dataclass), `storage_facade.py`
> (satisfies `storage_protocol.StorageBackend`, mirrors `data.load_data()` shape),
> `scripts/import_excel_to_sqlite.py` (idempotent backfill via content_hash),
> `excel_export.py` + `scripts/reconcile_sqlite_export.py`. Nothing is wired into the
> running bot yet; W1's dual-write (or a direct flip per W4) is the next step.

### Cycle W1 — SQLite as a shadow/parallel store
- [x] Design schema: `transactions` (mirrors MasterData), reference tables (categories, persons, rates, goals) — done in `sqlite_ops.py` (PR #96); `cycles` and `merchant_map` tables still pending.
- [x] Add a `sqlite_ops.py` layer — done (PR #96): `init_db`, `insert_transaction`, `update_transaction`, `delete_transaction`, `list_transactions(filters)`, reference upserts, `log_sync`.
- [ ] Wire dual-write: every `write_transaction_row` / `delete_transaction` / edit also writes to SQLite. Reads still come from Excel. Bot behaviour unchanged.
- [x] Backfill script — done (PR #96) as `scripts/import_excel_to_sqlite.py`: re-runnable, `--dry-run`, content_hash skips duplicates.
- [ ] CI: SQLite write failures are logged and non-fatal (Excel is still authoritative — a SQLite bug must never block a save).
- Done when: SQLite stays in sync with Excel through normal bot usage for one week without divergence.

### Cycle W2 — Read API + minimal web UI (view only)
- [ ] FastAPI (or Flask) micro-service (`web/app.py`) reading from SQLite only. Runs on the same VM, different port.
- [ ] Three pages: Transactions list (filterable by month/category/person), Summary (mirrors /summary numbers), Cycles list.
- [ ] Auth: single shared password (env var `WEB_PASSWORD`) — no multi-user, no OAuth.
- [ ] Transactions list matches Excel exactly: same columns, same sort order, paginated.
- [ ] Deploy: systemd unit `budget-web.service`, documented in `deploy/` alongside the bot service.
- Done when: the household can browse transactions in a browser and numbers match the bot's /summary.

### Cycle W3 — Web UI write path (add / edit / delete)
- [ ] Add transaction form in the web UI — same fields as /add, same validation (reuse `validators.py`).
- [ ] Edit and delete in the web UI — same row-lock semantics as the bot (`_excel_write_lock`).
- [ ] Dual-write: web UI writes to SQLite first, then queues an Excel write (same `atomic_save` path as the bot). Recovery queue handles failures.
- [ ] Conflict detection: if the same row was edited in Excel and the web UI between reads, surface a conflict warning.
- Done when: a transaction added via web UI appears in the bot's /summary and in Excel.

### Cycle W4 — SQLite as primary, Excel as export
- [ ] Flip reads: bot reads from SQLite instead of Excel for all queries (`/summary`, `/report`, `/top`, etc.).
- [ ] Excel becomes an export target: "Export to Excel" button in the web UI generates a fresh workbook from SQLite on demand.
- [ ] Remove dual-write: bot writes to SQLite only; Excel is regenerated on export, not kept in sync.
- [ ] Migration: run a final reconciliation to ensure SQLite and Excel match before flipping.
- [ ] Retire `file_storage.py` Excel read paths (keep write path for export only).
- Done when: the bot runs for two weeks reading from SQLite with no regressions; Excel export produces a correct workbook.

### Decisions (resolved 2026-07-26)
- [x] **UI framework**: HTMX + Jinja2 templates served by FastAPI. Server-side rendering, no JS framework — closest Python equivalent to Blazor/Razor Pages.
- [x] **Hosting**: systemd service + Nginx reverse proxy on the same Oracle Cloud VM. No Docker — same pattern as the existing bot service.
- [x] **Access**: WireGuard VPN. No public web surface. Phone and laptop connect via WireGuard app (QR code setup). Web UI only reachable inside the VPN tunnel.
- [ ] **SQLite concurrency**: WAL mode enabled (`sqlite_ops.init_db`, PR #96); still to verify bot + web server don't deadlock under concurrent writes.

---

## Idea: SQLite as a parallel datastore, ahead of a future web UI (2026-07-24)

Superseded by the roadmap above. Keeping for context — the step-by-step
approach described here is exactly Cycles W1–W4.

- **Trigger for this idea**: discussed switching the datastore from Excel to
  SQLite as part of the PLN/base-currency rename work. Conclusion: Excel stays
  the source of truth for now — the household edits the spreadsheet directly,
  and $0-hosting depends on no separate DB process. Excel's exact-header-match
  fragility (the whole reason this rename PR needed a migration script) is a
  real cost, but not enough on its own to justify a full datastore swap today.
- **The user's actual plan**: build a web UI later. When that happens, SQLite
  becomes the natural backing store for the UI (proper schema, migrations,
  no VLOOKUP/exact-header-match fragility, safer concurrent writes than the
  current `atomic_save` + recovery-queue workaround). Excel then becomes an
  export target rather than the primary store — an "Export to Excel" button
  instead of Excel-as-database.
- **Suggested approach — step by step, not a big-bang rewrite**:
  1. Add SQLite as a **parallel** datastore alongside Excel — writes go to
     both, reads still come from Excel (bot behavior unchanged, zero risk).
  2. Build the web UI against SQLite only, once schema/migrations are solid.
  3. Once the web UI is the primary way transactions are entered, flip reads
     to SQLite and add an explicit "Export to Excel" button for anyone who
     still wants the spreadsheet view.
  4. Retire dual-write once SQLite is trusted as the sole source of truth.
- **Open questions to resolve before starting**: schema design for
  MasterData/Lists/Cycles equivalents; how `Value (base)` / rate conversion
  formulas (currently Excel VLOOKUP) get reimplemented in SQL or the app
  layer; whether the recovery-queue mechanism is still needed once SQLite
  has real transactions.

## Follow-up PR: primary-user write gate + /setbudget (2026-07-23)

- [x] **Primary-user write gate** — `ALLOWED_TELEGRAM_IDS` is now an ordered
      `list[int]` (was a `set`), so `ALLOWED_TELEGRAM_IDS[0]` is the
      primary/sudo user. `config.py` gained `auth_write`, a new decorator
      alongside `auth`: non-listed users get the existing not-authorized
      reply (with their ID), listed-but-non-primary users get a new
      owner-only rejection ("You can view reports and data, but not add,
      edit, or delete"), and only the primary user passes through. All write
      entry points were reclassified from `@auth` to `@auth_write`: `/add`,
      `/bulk`, `/edit`, `/delete`, `/setcurrency`, `/setbudget`, and the
      quick-add (bare-text) handler. Internal conversation steps keep their
      existing (or absent) decorator — the gate check happens once at
      conversation entry, not on every step. All read/report commands
      (`/summary`, `/week`, `/budget`, `/top`, `/savings`, `/report`,
      `/rates`, `/chart`, `/range`, `/export`, `/help`, `/menu`, `/start`)
      remain on `@auth` and stay open to every allowed user.
- [x] **`/setbudget` command** — new owner-only conversation
      (`handlers/misc.py`) that shows all categories as an inline keyboard (2
      per row) with their current `Budget (PLN)` value from the Lists sheet,
      lets the owner tap a category, enter a new non-negative monthly budget
      (parsed via the shared `validators.parse_amount`), writes it back
      through a new `file_storage.update_category_budget_in_excel()` (same
      `ListsSchema`/`ExcelFileContext` pattern as `update_currency_rates_in_excel`),
      confirms the change, and loops back to the category picker so several
      categories can be set in one session. Reuses the same `Budget (PLN)`
      column already read by `/budget`/`check_budget_alert` — no schema
      changes. Registered in `bot.py`'s handler list, `BOT_COMMANDS` menu, and
      `/help`; documented in `DOCUMENTATION.md`.
- Tests: `tests/test_write_gate.py` (auth_write unit behavior, all seven write
  entry points reject non-primary/non-listed users correctly, a read command
  stays open to a non-primary allowed user, and the full `/setbudget` flow
  including negative-amount rejection and persisted-value re-render).
  `tests/test_handlers_full.py` now also patches `config.auth_write` to a
  pass-through so its conversation-step tests are unaffected by the new gate.

## In scope for PR #3 (bulk-import bug fixes)

- [x] **[PR #3] Draft-limit path discards just-parsed input** *(fixed in PR #43 — overflow holding buffer)* — `handlers/bulk_conv.py` `bulk_receive`:
      when `_draft_limit_reached` fires, the freshly parsed rows (already paid for with an AI call)
      are dropped without warning. Keep them in a holding buffer or warn explicitly.
- [x] **[PR #3] Preview edits not persisted to draft file** *(fixed PR #48 — _save_bulk_draft called after each edit)*
- [x] **[PR #3] Recovery replay writes Date as text string** *(fixed — `replay_recovery_queue` now rehydrates date/value/is_recurring before `write_transaction_row`)* — `append_to_recovery_queue` JSON-serializes
      dates with `default=str`; `replay_recovery_queue` writes the string verbatim into the Date cell.
      Rehydrate with `date.fromisoformat` (+ coerce value/is_recurring) before `write_transaction_row`.
- [x] **[PR #3] Cosmetic cleanup** *(fixed — resolved filter removed, limit message corrected, unused imports dropped; e2e tests updated for two-tap /add flow)* — dead `"resolved"` status filter in `_draft_limit_reached`
      (nothing ever sets it); limit message says "50" but triggers at 51; unused `io`/`logging`
      imports in `file_storage.py`.

## Follow-up PR: data validation

- [x] **Shared validator for all entry paths** — extract `_validate_quick_parsed` (quick_conv.py)
      into `validate_parsed_row(row, lists)`; run per row after bulk `parse_text`/`parse_image`
      (flag invalid rows in preview) and inside `_apply_bulk_edit` for the edited field.
      Today `2 category=Grocries` (typo) saves fine and breaks Dashboard SUMIFS.
- [x] **Type↔Category coherence** — nothing stops `type=Expense, category=Savings` (observed live:
      2000 PLN transfer-to-self) or `type=Expense, category=Salary`. Two layers:
      (a) rules in the AI prompts ("category Savings ⇒ type Savings; refunds are Income with the
      original purchase's category"), (b) type→category compatibility check in the shared validator.
      Optionally a `TxnType` column next to Categories in Lists (extend `ListsSchema`).
- [x] **Value normalization** — one shared `parse_amount(raw)` for `1 234,56` / `1,234.56` / `-45.00`
      (last separator = decimal); /add currently corrupts `1.234,56`; bulk rejects signed amounts
      instead of mapping negative → Expense. Round to 2 decimals in the `Transaction` validator.
- [x] **Date sanity in quick-add** — quick-add accepts future dates; /add has a future/90-day check.
      Align via the shared validator.
- [x] **write_transaction_row honors is_done** — `excel_schema.py` hardcodes IsDone=True;
      `Transaction.is_done` is a dead field. Write `row.get("is_done", True)`.
- [x] **is_recurring editable in bulk** — bulk hardcodes False and `_apply_bulk_edit` whitelist
      excludes the field; add it with yes/no/true/false coercion.

## Follow-up: data-validation review notes (PR #5, 2026-07-22)

- [ ] **Lone-separator amounts silently reinterpreted** — `parse_amount` treats a single
      comma/dot as decimal, so `1,234` (thousands intent) becomes 1.23 with no warning;
      surface a 🛡 note when a lone separator with exactly 3 trailing digits is reinterpreted.
- [ ] **Bulk edit revalidation skipped when reference data unavailable** — `_apply_bulk_edit`
      revalidates only `if lists:`; after a bot restart mid-draft, lists is absent from
      ctx.user_data and typo'd categories slip through; reload reference data instead of skipping.

## Follow-up PR: dedup

- [x] **Statement dedup against MasterData** — re-uploading an overlapping bank export silently
      doubles rows. Key: `sha1(date|value|currency|cleaned-description)`. At batch save, read
      existing keys for the date range; dedupe within the batch; flag collisions in the preview
      as "↺ likely already imported" (skip by default, `3 keep` to override).
- [x] **Within-draft dedup** — `_merge_bulk_draft` concatenates blindly; uploading the same
      photo twice mid-draft duplicates every row inside one save. Same key.

## Follow-up PR: dedup v2 — agreed design (brainstorm 2026-07-22)

Refines the base dedup (PR #7). All user-facing message templates below are acceptance
criteria — exact wording reviewed at implementation, never improvised. Standing rule:
the bot never blocks an import with a question; it decides a default, shows its
reasoning in the preview, and offers a one-command override.

- [x] **Count-aware matching (multiset, not set)** — keys are compared with occurrence
      counts on both sides. Upload has 3 identical rows, MasterData has 2 in range →
      save 1, skip 2, and say the math: "3 identical rows found, 2 already in your
      sheet → saving 1, skipping 2. Reply `keep all` if these are new payments."
      *(done: `data.load_dedup_evidence` returns MasterData rows as multiset evidence
      lists; `handlers.bulk_conv._flag_master_duplicates` groups draft rows by strict
      key and flags only `min(group_size, master_count)` — the excess is kept. Message
      wording uses `keep all flagged` instead of bare `keep all` so the reply only
      overrides this group, not the whole batch — see "all flagged scopes" below.)*
- [x] **Within-batch identical rows are KEPT by default** (inverts PR #7 behaviour) —
      repetition inside one source is almost always real (e.g. several 2 PLN car-wash
      payments same day). Preview annotates instead of dropping:
      "rows 4, 5, 6 are identical — keeping all 3; reply `drop N` if one is a scan error."
      *(done: `_merge_bulk_draft` no longer hard-skips repeats; `_flag_master_duplicates`
      annotates same-key groups with no MasterData match as `identical_group` on every
      row, rendered in the preview and reported in `_format_dedup_messages`.)*
- [x] **Multi-row `drop` / `keep` grammar with stable numbering** — `drop 4 6`,
      `drop 4-6 9 12`, `keep 3 7-9`; one reply, one re-rendered preview. Row numbers
      never shift mid-draft (no renumbering until save) so batch commands stay safe.
      `N field=value` edit grammar stays single-row.
      *(done: `handlers.bulk_conv._apply_row_command` + `_parse_row_targets`; dropped
      rows stay in the list marked `row["dropped"]`, never removed, so numbering is
      stable across sequential commands.)*
- [x] **Two-pass scan: strict decides, loose advises** — pass 1 (strict key
      date|value|currency|cleaned-description) drives all automatic skip/keep behaviour.
      Pass 2 (loose key date|value|currency, no description) runs only on rows pass 1
      called new; matches get NO automatic action (saved by default) and are surfaced
      as an advisory showing BOTH descriptions side by side.
      Asymmetry is deliberate: wrong advisory costs one line of reading; wrong skip
      loses a transaction. Loose pass reuses the same MasterData read — no extra
      workbook access, no AI calls.
      *(done: `data.load_dedup_evidence` computes strict+loose evidence in ONE read;
      `validators.make_loose_dedup_key` added; `_flag_master_duplicates` pass 2 only
      sets `loose_dup`/`loose_other_date`/`loose_other_desc`, never `dup`.)*
- [x] **Mass loose-match hint** — when most rows of a batch loose-match (bank
      reformatted descriptions between exports), say so explicitly and offer
      `drop all flagged` in one command.
      *(done: `_format_dedup_messages` appends the hint when >=3 loose matches cover
      at least half of the batch's "new" rows.)*
- [x] **Strict-flag evidence in message** — skip lines show date, amount, merchant AND
      what was matched, so a false match is spottable without opening Excel.
      *(done: single-occurrence strict matches (`single_skips`) render "matches an
      entry saved {date}"; preview rows show the same evidence date inline.)*
- [x] **Deleted rows reappear as new on re-import — accepted, no tombstones** —
      decided: the bank file says the transaction happened; preview shows it as new,
      user can drop it. No deleted-key state is kept. *(done: no code change needed —
      dedup only ever compares against what's currently in MasterData; nothing tracks
      deletions, matching the decision as written.)*
- [ ] **Timestamp disambiguates within-batch only (corrected by design review
      2026-07-22)** — MasterData has no time column, so HH:MM must NEVER enter keys
      compared against stored rows (time-bearing draft keys would never match timeless
      stored keys — dedup would silently stop firing for statement imports). When the
      source provides time (statement profiles), use it only to tell identical rows
      apart WITHIN one batch (exact per-day counts for count-aware matching);
      cross-import keys stay timeless. A MasterData Time column is deliberately out of
      scope; revisit only if timeless+count-aware dedup proves insufficient.
      *(deferred: no current source provides time data — nothing to implement now;
      revisit once a statement profile actually supplies a time column.)*
- [x] **Unified row-command grammar** — `drop` and `keep` as verbs; targets `N`, `N M`,
      `N-M`, `all`, `all flagged`; alongside existing `N field=value`, `save`, `cancel`.
      One parser for all preview states (dedup flags, validation flags, manual pruning).
      Supersedes the UX-group "skip N / delete N" item — implement once, here.
      *(done: `_apply_row_command` is tried before the single-row `N field=value`
      regex in `_apply_bulk_edit`; the pre-dedup-v2 `N keep` syntax still works too.)*
- [x] **Contextual command footer — show only what applies** — every preview ends with a
      short hint line, but content adapts to state; a user who has no duplicates never
      reads a word about duplicates.
      *(done: `handlers.bulk_conv._bulk_footer` builds the base edit/save/cancel line
      plus a dup-skip block and/or a loose-match block only when those rows exist.)*
- [x] **`all flagged` scopes to the block it is printed under** — `keep all flagged`
      under the skip list acts on skipped rows only; `drop all flagged` under the
      advisory acts on advisory rows only; plain `drop all` / `keep all` act on the
      whole batch.
      *(done: `_apply_row_command` maps `keep all flagged` -> rows with `dup` set,
      `drop all flagged` -> rows with `loose_dup` set, independent of `all`/`all M-N`.)*

## Follow-up PR: merchant memory & description quality

- [x] **Description cleanup** — MasterData gets `4111XXXXXXXX1111 SHOP TERMINAL 12 CITY PL` and
      `/OPT/X///// BPID:EXAMPLE123 Autopay S.A.`. (a) Prompt: output clean 2-4 word merchant labels;
      (b) deterministic regex post-processor (strip masked PANs, `BPID:` codes, `/OPT/` blocks,
      city/country suffixes) applied on all three entry paths — extend `formatters.sanitize_description`
      and actually call it in quick_conv and bulk_conv.
      *(done: `validators.clean_merchant_description` shared by sanitize_description, bulk
      normalize, quick-add AND `make_dedup_key`, so display/storage/dedup stay consistent)*
- [x] **Merchant→category memory** — `MerchantMap` store (sheet or JSON): cleaned merchant →
      category/type/label/person/is_recurring defaults. Lookup before AI; learn from preview edits
      (`2 category=Transport` writes the mapping back); seed from MasterData history.
      Makes categorization deterministic and cuts DeepSeek calls.
      *(done: `merchant_map.py`, JSON at `data/merchant_map.json` via the user-prefs pattern —
      no workbook change; auto-seeds from MasterData on first use; 🧠 markers in the preview)*

## Follow-up: dedup review notes (PR #16, 2026-07-23)

Four non-blocking findings from the PR #16 adversarial review — safe to merge as-is, queued as follow-up:

- [x] **`_parse_row_targets` inconsistent OOB feedback** *(fixed PR #48 — returns (valid_list, error_list); OOB reported consistently)*
- [ ] **Message wording drifted from BACKLOG acceptance-criteria text** — footer format, skip-message
      phrasing, and row-range compression differ from the spec. PR #16 also retroactively edited
      BACKLOG.md to justify the changes, which is a process smell (spec says this wording is "never
      improvised"). Deliberate re-alignment pass, not urgent.
- [x] **`_bulk_footer` redundant suggestion for single-flagged-row case** *(fixed PR #48)* — when exactly one row
      is dup-flagged the footer renders e.g. `keep 3`, `keep 3`, or `keep all flagged` — the first
      example duplicates the second.
      (`handlers/bulk_conv.py` `_bulk_footer`)
- [x] **`_format_dedup_messages` mass-loose-match-hint denominator is wrong** *(fixed PR #48 — denominator is strict-pass-new rows only)* — it folds
      already-skipped strict-dup counts into `total_new` (the denominator for the "most rows
      loose-matched" ratio), undercounting it in mixed strict+loose batches — exactly the
      bank-reformatted-descriptions scenario the hint exists for. Fix: denominator should be
      rows the strict pass left as new.
      (`handlers/bulk_conv.py` `_format_dedup_messages`)
- [x] **`bulk_receive` reads the draft file twice** *(fixed PR #48 — single file read per receive)* — `pre_merge_len = len(_load_user_draft(uid))`
      is called immediately before `_merge_bulk_draft`, which calls `_load_user_draft` internally
      as its first step. On local backend this is negligible; on GCS/S3 it's two network downloads
      for the same file. Fix: have `_merge_bulk_draft` return the pre-merge count alongside
      the merged list, or cache the read.
      (`handlers/bulk_conv.py` `bulk_receive`, `_merge_bulk_draft`)
- [x] **DOCUMENTATION.md not updated for dedup v2 user-facing grammar** — the `/bulk` section
      only documents `N field=value`, `save`, and `cancel`. The new `drop N`, `keep N`,
      `drop 4-6 9`, `keep all flagged`, `drop all flagged`, `drop all`, `keep all` grammar is
      completely absent, as are the dedup advisory messages and how to respond to them.
      *(done: "Bulk Import via /bulk" section updated in PR #17 — command table + duplicate
      detection block covering strict/count-aware, loose advisory, and within-batch behaviour.)*

## Follow-up: dedup review notes (PR #7, 2026-07-22)

- [x] **Within-batch identical rows have no keep override** — two genuinely identical same-day
      transactions in one statement are dropped by `_merge_bulk_draft`'s `seen` set and
      `bulk_confirm`'s `seen_batch_keys`; `N keep` is rejected because `_apply_bulk_edit`
      requires `parsed[idx].get("dup")`, which only MasterData flags set. Allow `keep` on
      within-batch dups or use count-aware keys.
      *(fixed by dedup v2 above: within-batch identical rows are kept by default via
      count-aware matching, so there's no skip left to override for the pure-repeat case;
      `_merge_bulk_draft`'s `seen` set and `bulk_confirm`'s `seen_batch_keys` were removed.)*
- [x] **Guard-quoted descriptions defeat dedup** — `write_transaction_row` prepends `'` to
      descriptions starting with `=+-@` (excel_schema.py); read-back keys hash `'foo` vs draft
      `foo`, so dedup silently never fires for those rows. Strip the guard quote in
      `load_dedup_keys`/`make_dedup_key` normalization; add a round-trip test with a
      leading-`=` description.
      *(fixed in the merchant-memory PR: `make_dedup_key` now strips a leading `'` and runs
      `clean_merchant_description` before hashing; round-trip test in tests/test_merchant_map.py)*
- [x] **Locale-formatted draft values fall back to raw-string keys** — `make_dedup_key` value
      normalization: `"1,234.56"`-style strings fail float() and fall back to the raw string,
      never matching Excel's float-derived key; route through validators.parse_amount before
      hashing.
      *(done: `validators._normalize_dedup_value` now calls `parse_amount` before hashing,
      shared by both `make_dedup_key` and `make_loose_dedup_key`; tests in test_dedup.py
      cover thousands-comma and European decimal-comma formats.)*

## Follow-up PR: infra & performance

- [x] **.bak leak on remote backends** *(fixed PR #48 — .bak skipped for temp files)*
- [x] **Reference-data TTL cache** — every message triggers 2-4 full workbook reads
      (`load_reference_data` = `load_lists` + `load_rates`, two full parses of the same file).
      60-300s module-level cache in data.py, invalidated by writes in excel_ops.
      On remote backends each read also re-downloads the workbook.
- [x] **Recovery queue as append-only JSONL journal** — current read-append-write JSON with no lock;
      enqueue batches/deletes/edits as typed operations; periodic replay job in APScheduler
      instead of startup-only.
- [x] **Lost-update protection for remote backends** — `ExcelFileContext` does blind
      download→modify→upload; use GCS generation / S3 ETag preconditions and retry on conflict.
- [x] **_load_bulk_drafts reads every user's file** — called 3× per message just to fetch one
      user's draft; read `_user_draft_path(uid)` directly. `_load_user_draft` in `bulk_conv.py:794-804` already reads single file.
- [x] **Split file_storage god module** — backends / workbook repo / template concerns;
      backend selection should honor `STORAGE_BACKEND` strictly (a stray `GCS_BUCKET_NAME`
      env var currently overrides `STORAGE_BACKEND=local`).
- [x] **DeepSeek output as typed model** — done: `ParsedTransaction` at `ai_parser.py:234`; validated via `model_validate` in `_normalize_ai_rows`.

## Follow-up PR: UX

- [x] **Person attribution per import** — done: `_finish_profile_parse` prompts "Whose statement is this?", `bulk_person_callback` stamps all rows (`bulk_conv.py:410-452`). /add: `ADD_PERSON` state retired 2026-07-25 (`states.py:7`); person defaults to "" (household), editable from confirm card.
- [x] **Recurring detection from history** — same cleaned merchant + similar amount (±10%)
      in ≥2 prior months ⇒ propose `is_recurring=True` (🔁 in preview, pre-selected in /add).
      Stop asking on every /add; bulk stops hardcoding False.
- [x] **/add default-and-confirm** — 9 round-trips today; pre-fill PLN/Expense/today/non-recurring
      after amount+category and jump to the confirm card with "Edit a field…" (reuse edit_conv picker).
- [x] **Discoverability** — `/bulk`, `/delete`, `/help`, `/setcurrency` absent from menus and /start;
      add 📥 Import + 🗑 Delete buttons; rewrite /start to show the three entry methods;
      register commands with BotFather. *Done: 📥 Import + 🗑 Delete added to MAIN_MENU;
      /start shows the three entry methods; /help lists every command grouped by purpose;
      BotFather registration replaced by `set_my_commands` at startup (bot.py `register_commands`
      post_init hook) — better, no manual BotFather step, guarded by a drift test.*
- [ ] **Bulk edit UX** — `skip N` / `delete N` commands to drop a mis-parsed row without cancelling
      everything; on invalid edit, list the editable fields; validate category values against Lists.
- [x] **Quick-add one-tap recovery** — on validation failure show what WAS parsed with a category
      keyboard instead of ejecting to the 9-step /add.
- [x] **Bulk preview separator orphan at page break** — done: `_format_bulk_preview` strips trailing separators before page flush (`bulk_conv.py:1395-1397`).
- [ ] **Report chunking can break Markdown entities** — PARTIAL: now splits at `━━━` section-break lines (not raw 4000-char); does not yet reuse bulk_conv paginated-send helper.
- [x] **edit_conv currency keyboard hardcodes 3/3 split** — fixed: `edit_conv.py:105` now uses 2-per-row dynamic split (`ccy_list[i:i+2]`), not hardcoded 3-column rows.

## Follow-up PR: code clarity

- [ ] **Unit-less magic numbers sweep** — parameters like `conversation_timeout=1800` don't say
      seconds/minutes. Every duration, size, or count literal must be a named constant with the
      unit in the name (e.g. `BULK_REVIEW_TIMEOUT_SECONDS = 30 * 60`). bot.py timeouts done in
      PR #3; PR #49 renamed `_PREVIEW_MSG_LIMIT` → `_PREVIEW_MSG_LIMIT_CHARS`, added
      `_REPORT_MSG_LIMIT_CHARS`, and named the APScheduler cron constants. Sweep the rest:
      `_CHUNK_TARGET_CHARS`, `_BULK_MAX_TOKENS`, `_REQUEST_TIMEOUT_S` → `_SECONDS`,
      `conversation_timeout` on /setcurrency and /add (currently unset = infinite — decide
      deliberately), recovery-queue retry counts, `$100` row bounds in VLOOKUP ranges.

## Follow-up PR: module size policy — agreed (brainstorm 2026-07-22)

- [ ] **Hard cap 300 lines per production module** — a file exceeding 300 lines almost
      always contains two concerns; split by cohesion, not by line count alone.
      Exempt: test files (a thorough test suite for one module legitimately runs long)
      and generated/schema files.
- [ ] **Target 150-200 lines** — not enforced immediately, but the trigger to consider
      a split the next time the file is touched for a feature (not mid-feature, not
      forced) — 150 as a hard cap was considered and rejected: it forces the opposite
      failure, fragmenting one coherent handler into files whose functions call across
      each other, trading "too long to scroll" for "too scattered to follow."
- [ ] **Split by concern, name by concern** — e.g. `bulk_conv.py` → conversation states /
      preview rendering / draft persistence, not `bulk_conv_part2.py`.
- [ ] **Known offenders (first pass, measured 2026-07-22):** `file_storage.py` (745
      lines — split already tracked under "infra & performance: Split file_storage god
      module", merge these two items when implementing), `handlers/bulk_conv.py` (733),
      `handlers/reports.py` (670).

## Follow-up PR: token economy (paid DeepSeek tokens)

- [ ] **Compact AI output format** — replace keyed JSON objects (~120 output tokens/txn) with
      positional arrays `["2026-07-05", 45.98, "PLN", "E", "Entertainment", "Old Tbilisi", ""]` + letter
      codes for type. ~4-5× cut on output tokens (the expensive kind). Prompt change + decoder.
- [ ] **Split extraction from categorization** — regex extracts date/amount/description from
      structured bank statements locally; AI only categorizes a compact list of unknown merchant
      names (~5 tokens/txn instead of ~120). Shares foundation with merchant memory.
- [x] **Merchant memory as token saver** — (see merchant-memory PR) deterministic lookup for
      repeat merchants = zero tokens; after a month ~80% of rows skip the AI entirely.
      *(covered by the merchant-memory PR: `merchant_map.try_local_quick_parse` gives known
      merchants a zero-token quick-add path; bulk still parses via AI but categorization of
      known merchants is deterministic)*
- [ ] **Local fast-path for quick-add** — regex + Lists categories handle "groceries 89" /
      "lunch 45 eur" patterns with zero tokens; AI only for ambiguous messages.
- [ ] **Dedup before parse** — skip already-imported statement blocks BEFORE sending to the AI
      (see dedup PR), not just before saving.
- [ ] **Keep system prompts byte-identical across calls** — DeepSeek auto-caches identical prompt
      prefixes at ~10× discount; keep dynamic content (dates, user text) at the END of messages.
- [ ] **Off-peak batching** — DeepSeek is 50-75% cheaper 16:30-00:30 UTC; schedule any
      non-interactive batch work in that window.

## Follow-up PR: draft & log lifecycle

- [ ] **Bulk draft archival instead of naming change** — drafts (`data/bulk_drafts/{uid}.json`)
      ARE deleted after successful save and on cancel (verified). Improvement: on save, move to
      `data/bulk_drafts/archive/{uid}-{YYYYMMDD-HHMMSS}.json` instead of deleting — cheap audit
      trail of what each import contained; prune archive >6 months on startup.
- [ ] **Log retention: 6 months, enforced on startup** — daily rotation already exists
      (TimedRotatingFileHandler → budget-bot.log.YYYY-MM-DD), but backupCount pruning only fires
      on rollover, and the bot is stopped/started irregularly. Add a startup sweep in
      logger.init_logging(): delete `budget-bot.log.*` older than 180 days.
      Decision: keep by-day grouping (one file per transaction would mean thousands of files —
      per-operation detail belongs INSIDE the daily file as structured lines).
- [x] **Per-operation audit line** — one structured log line per save attempt
      (user, source, rows, outcome, duration) so a day's file answers "what was saved today"
      without reading debug noise. Consider a separate `audit.log` with the same daily rotation.

## Follow-up PR: schema simplification

- [ ] **Derive Year/Month from Date by formula** — MasterData carries Date + Year + Month as three
      independent columns; Year/Month should be formulas (`=YEAR(A2)`, `=TEXT(A2,"mmm")`) or removed
      entirely with Dashboard SUMIFS rewritten against Date ranges. Touches every Dashboard formula,
      the writers, and the schema — do as its own PR with a migration script for existing rows.
- [ ] **Category rename support (simplify category names)** — user decision: category + description
      is enough granularity; e.g. rename "Gifts & Shopping" → "Shopping" (description says what kind).
      Needs a rename script that updates: Lists Categories cell, all matching MasterData rows,
      Budget row on Dashboard, and the merchant-map once it exists — otherwise historical rows and
      budget VLOOKUPs silently stop matching. Also update the bulk validator's fuzzy map.

## Follow-up PR: draft limit semantics

- [ ] **Enforce the 50-row limit post-merge, not pre-merge** (Copilot PR review) —
      `_draft_limit_reached` checks the EXISTING draft before merging, so a draft at exactly 50
      can still merge a 185-row import and blow past the documented maximum. Decide the rule
      (cap total? reject overflow rows? paginate drafts?) and enforce it after `_merge_bulk_draft`
      with a clear message about what was and wasn't added.

## Follow-up PR: user-visible reporting

- [ ] **Report every silent decision to the user, briefly** — standing principle: whenever the bot
      skips, corrects, deduplicates, or drops anything, the user gets one short line about it.
      Already done for validator corrections (🛡 auto-corrected list). Still needed:
      dedup skips ("↺ 3 rows skipped as already imported: …"), rows dropped at save due to
      Transaction validation errors (currently only shown as "Saved N of M" + first 5 errors),
      recovery-queue replays on startup ("re-applied 2 queued transactions"), and draft archival.

## Follow-up PR: parallel-review findings (2026-07-21, reviewers A+B)

Found by BOTH reviewers independently — highest confidence:

- [x] **Recovery-queue corruption bricks startup** — `append_to_recovery_queue` writes non-atomically
      (file_storage.py:118-123) and `flush_recovery_queue` does an unguarded `json.loads`; a crash
      mid-write leaves invalid JSON and `replay_recovery_queue()` at bot.py:83 raises on every start
      until the file is hand-deleted. Also flush unlinks the file BEFORE replay completes — a crash
      during replay loses all queued rows. Fix: atomic queue writes, guarded parse (quarantine a
      corrupt file with .corrupt suffix + log), delete queue only after successful replay.
- [ ] **Partial bulk save loses failed rows** — bulk_conv.py:425-448: rows failing Transaction
      construction go to `errors`, the rest save, then `_delete_bulk_draft` removes EVERYTHING.
      Fix: keep only failed rows in the draft after a partial save and tell the user how to fix/retry.
- [x] **Stale row-index race in /delete and /edit** *(fixed PR #48 — re-verify under write lock, abort if row moved)*
- [ ] **Repair scripts unsafe next to a live bot** — no _excel_write_lock, plain wb.save (no atomic),
      lost-update if the bot writes concurrently; on gcs/s3 they modify a local file the bot never
      uploads. Fix: scripts refuse to run when backend != local, take the lock file (once one exists),
      use atomic_save.
- [x] **Dual logging setup** — config.py calls logging.basicConfig at import while logger.init_logging
      installs its own handlers → duplicate console lines, LOG_LEVEL partially overridden.
      One owner: remove the basicConfig from config.py.
- [ ] **Draft limit porous** — already tracked under "draft limit semantics"; reviewers add: no cap on
      a single oversized parse (400-row statement merges fine), no dedupe on merge.

Unique findings (single reviewer, verified plausible):

- [x] **Date edit leaves Year/Month stale** *(fixed PR #48 — edit_conv builds {"Date","Year","Month"} dict, passed atomically to update_transaction_field)*
- [x] **Formula injection via descriptions** *(fixed in PR #43 — bulk/quick/edit paths covered)* — formatters.sanitize_description (leading '=' guard)
      is called only in add_conv.py:199; bulk (bulk_conv.py:436), quick-add (quick_conv.py:203) and
      /edit write raw untrusted text into cells. Fix: sanitize in write_transaction_row so every
      path is covered once.
- [x] **Quick-add KeyError when Lists unreadable** *(fixed PR #48 — empty-categories guard in quick_conv.py)*
- [x] **Range-text listener crosstalk** *(fixed PR #48 — handle_range_text group=-1, per-chat chat.id flag)*
- [x] **fix_import_errors.py**: rule-3 (person→description) uses the description read BEFORE rule-2
      rewrote it — same-row combination silently undoes rule 2. Rerun also overwrites .bak with
      already-fixed data (backup should be write-once: skip if .bak exists).
      *(done in PR #49: rules chain on local row state so rule 3 sees rule 2's rewrite;
      .bak is write-once — kept if it already exists; regression test in
      tests/test_repair_scripts.py.)*
- [x] **Legacy scripts lack settings/backup** — fix_currency_range.py, fix_dashboard_validations.py,
      wire_budget_from_lists.py hardcode data/Expenses_Improved.xlsx, save without .bak;
      wire_budget_from_lists hardcodes Dashboard rows 11-27. Either upgrade to the settings+backup
      pattern or delete them (they were one-time migration scripts — deletion preferred).
      *(done in PR #49: all three one-time migration scripts deleted.)*
- [x] **rename_category.py gaps** — doesn't touch category names inside formula string-literals
      (SUMIFS criteria) nor pending bulk drafts in data/bulk_drafts/*.json (old name resurfaces and
      gets silently normalized to 'Other'). Fix: scan Dashboard/Monthly Summary formulas for the
      quoted old name; rename inside all pending drafts.
      *(done in PR #49: Dashboard/Monthly Summary formula string-literals and pending
      bulk-draft JSON files are renamed; tests in tests/test_repair_scripts.py.)*
- [x] **Bulk manual edits bypass the normalizer** — `2 category=Trnsport` writes verbatim
      (bulk_conv.py:229-260); run _normalize_parsed_rows (or the shared validator) on the edited
      field too. (Covered by the data-validation PR: `_apply_bulk_edit` now runs the shared
      validator on the edited row.)
- [ ] **lists_currency_range caps at row 100** — currencies beyond Lists row 100 silently ignored
      in every written Value (PLN) formula → #N/A. Derive the end row from actual data or use a
      named range. (Overlaps with "unit-less magic numbers" sweep.)

Fixed immediately during this review (not backlog): missing @auth on /bulk, /edit, /delete
write paths — commit 309df08.

## Follow-up PR: security posture (pre-publication audit)

- [x] **Auth fails open** — config.py: empty ALLOWED_TELEGRAM_IDS serves ALL Telegram users with
      only a log warning. Now that the code is public, misconfiguration = strangers get full
      read/write on the finances file. Fail closed unless an explicit ALLOW_ALL_USERS=1 is set.

## Follow-up PR: /export command hardening (PR #1 review, 2026-07-22)

- [x] **Exception message leak in /export** *(fixed PR #48 — generic user-facing error message, log.exception for server detail)*
- [x] **No file-size guard before reply_document** *(fixed PR #48 — 50MB pre-check added)*

## Follow-up PR: recovery-queue hardening (PR #2 review, 2026-07-22)

- [x] **Quarantine rename failure retries forever** *(fixed PR #48 — one-retry then log.critical, stops looping)*

## Follow-up: budget cycles review notes (pre-PR verify, 2026-07-24)

- [x] **Bare `/cycle` (read-only status) is write-gated** — non-owner allowed users
      cannot view the current cycle; consider `@auth` for the no-arg path and
      `auth_write` only for `started`. (handlers/cycle.py)
- [x] **Timezone inconsistency** — reports.`_current_cycle_bounds` uses
      `now_utc().date()` while handlers/cycle.py uses `datetime.now(TIMEZONE)`;
      near midnight the "today" bound and the prompt-day can disagree by one day.
- [ ] **Sync workbook I/O in async handlers** — `load_cycles()` /
      `should_prompt_new_cycle()` block the event loop; matters mainly on remote
      storage backends.
- [ ] **Duplicate boundary still re-uploads on remote backends** —
      `record_cycle_start` returning False inside `ExcelFileContext` triggers an
      unnecessary upload of an unchanged workbook.
- [ ] **Callback "yes" date not re-validated against future dates** — currently
      unreachable but cheap to harden. (handlers/cycle.py)

### PR #30 review notes (2026-07-24)

- [ ] **Ledger row order unspecified** — backfill will append boundaries out of
      chronological order; the Dashboard PR must compute "next start"
      order-independently (MINIFS) or backfill must insert sorted.
      (cycles.py `record_cycle_start`)
- [ ] **Layering inversion between file_storage and cycles** — file_storage.py
      does function-local imports from cycles.py while cycles.py imports
      file_storage; move `ensure_cycles_sheet` down to the schema/storage layer
      before the Dashboard PR adds more scaffolding.
- [ ] **Duplicate labels for two boundaries in one calendar month** —
      `cycle_label` gives "Jul 2026" for both; decide label-uniqueness vs
      keying by start date before the Dashboard dropdown is built.
- [ ] **Unparseable ledger dates mishandled** — `record_cycle_start`'s next_row
      scan can overwrite a trailing row whose date fails to parse, and
      `load_cycles` silently drops such rows; advance past any non-blank row
      and surface unparseable rows. (cycles.py)
- [ ] **Flag-on removes the calendar view entirely** until the /summary picker
      PR ships — the picker PR is the usability completion of cycles, don't
      deprioritize it.
- [ ] **check_budget_alert still calendar-scoped** while /budget is
      cycle-scoped — contradictory percentages after every save when the flag
      is on. (handlers/reports.py)
- [ ] **Backdated Salary save proposes a backdated boundary with no undo
      path** — `should_prompt_new_cycle` gates on today's cycle age, not the
      transaction date; no `/cycle delete` exists and hand-editing the Cycles
      sheet is undocumented. (handlers/cycle.py)
- [ ] **Prompt text "(yes / no / different date)" invites typed replies** that
      fall into the group-0 quick-add AI parser (wasted paid call /
      hallucinated row) — drop the parenthetical or handle the typed text.
      (handlers/cycle.py)
- [ ] **User-editable Label cell interpolated raw into Markdown messages** — a
      label containing markdown chars breaks /summary, /budget and /cycle
      replies entirely; escape or sanitize. (cycles.py, handlers/reports.py)
- [x] **auth_write on CallbackQueryHandler never answers the callback query on denial** *(fixed PR #47 — auth_write answers callback before returning)*
- [ ] **handlers/reports.py now ~730 lines** (rule cap 300 for new modules) —
      move `_current_cycle_bounds` / `_send_cycle_summary` toward cycles.py
      during the module-size sweep.
- [ ] **Static /help and DOCUMENTATION command-table wording for /summary and
      /budget stays calendar-based** when the flag flips them to cycle scope —
      polish the descriptions.

## Follow-up PR: budget cycles — agreed design (brainstorm 2026-07-22)

Goal: restore the user's pre-bot salary-period tracking. Salary arrives around the 25th
but shifts ±4-5 days, so cycle boundaries are RECORDED EVENTS, never date formulas.
Answers "which salary funds this?" and "what happened to each salary?" (leftover /
unaccounted tracking — the old manual dashboard metric).

> **Phase 1 merged in PR #23; PR #30 consolidates the implementation** (dedicated
> `cycles.py` module, inline-button prompt, cycle-scoped `/budget`, template Cycles
> sheet). Items marked [x] shipped; items marked [ ] are follow-up PRs.

- [x] **`BUDGET_CYCLE=1` env flag** — off by default; calendar behaviour unchanged for
      everyone else. When off, none of the below activates.
      *(done: `settings.BUDGET_CYCLE` plus `settings.CYCLE_REPROMPT_MIN_AGE_DAYS` and
      `settings.SALARY_CATEGORY`; every cycle code path is gated on the flag.)*
- [x] **Cycle ledger** — one row per cycle: start date + label. Labels always carry the
      year ("Aug 2026", never bare "Aug") so multi-year resolution is unambiguous.
      Lives in the dedicated `Cycles` sheet (see below — NOT Lists columns).
      Boundaries are written once and never recomputed — no retroactive
      re-bucketing, late edits cannot silently move history between cycles.
      *(done: `cycles.py` — `load_cycles`/`record_cycle_start` via `CyclesSchema`
      header lookup; duplicate start dates are a no-op, rows are never rewritten.)*
- [x] **Boundary capture, user-confirmed** — two inputs, same ledger:
      (a) bot saves an Income row with category Salary → prompt: "💰 Salary received.
      Start the new budget cycle from 23 Jul? (yes / no / different date)" — the bot
      proposes, only the user's confirmation records; a mis-categorized refund cannot
      open a cycle. (b) `/cycle started [date]` manual command any time.
      No salary logged + no command = current cycle continues; the bot never guesses.
      *(done: `handlers/cycle.py` — `maybe_prompt_cycle_start` fires from /add and
      quick-add saves with inline Yes / No / Different date buttons; "Different date"
      points at `/cycle started YYYY-MM-DD`; prompt only when the current cycle is
      ≥ `CYCLE_REPROMPT_MIN_AGE_DAYS` old.)*
- [x] **Bot reports per cycle** — with the flag on, `/summary` and budget bars compute
      over the current cycle (last boundary → today); days-remaining uses no assumption
      about cycle length. Monthly scheduled report fires on cycle close (boundary
      confirmation) instead of the 1st, reporting the cycle that just closed.
      *(done for /summary and /budget: cycle-scoped via `cycles.cycle_totals`, upper
      bound open-ended at today, daily-average instead of month-end projection.
      Scheduled report on cycle close is NOT yet moved — still fires on the 1st;
      follow-up with the Cycle Dashboard PR.)*
- [x] **Unaccounted metric** — per cycle: salary received − tracked expenses − tracked
      savings = unaccounted ("not reported"); negative = over-reported (untracked income
      or previous cycle's leftover being spent). Shown in bot cycle reports and on the
      Cycle Dashboard.
      *(done for bot reports: shown in the cycle /summary with an "over-reported" note
      when negative. Cycle Dashboard sheet is a later PR.)*
- [ ] **Cycle Dashboard sheet** — duplicate of the existing Dashboard on a new sheet;
      same layout, same category rows, same budget targets (shared Lists budget column —
      one edit updates both). Filter is a single cycle selector (dropdown fed by the
      ledger) instead of Year+Month; all SUMIFS filter on Date >= cycle start AND
      Date < next start — for the LAST ledger row (no next start) the upper bound is
      open-ended: TODAY()+1 in formulas, today in bot queries.
      Adds the salary/expenses/savings/unaccounted block and shows
      the cycle's day count (24-33 days — budgets are not pro-rated, matching the old
      manual system). The calendar Dashboard and Month/Year columns stay untouched —
      cycles are purely additive; disabling the flag corrupts nothing.
- [ ] **Sync check** — repair-script-pattern check that both dashboards carry the same
      category rows (new category must be added to both sheets).
- [x] **Cycles sheet, not JSON** — the ledger lives in a dedicated `Cycles` sheet in the
      main workbook (start date + label per row) so Dashboard formulas can reference it;
      included in the template (harmless when the flag is off); auto-created on first
      use for existing workbooks; bot access through excel_schema.
      *(done: `excel_schema.CyclesSchema` + `cycles.ensure_cycles_sheet`; sheet added
      to `data/Expenses_Template.xlsx`, to the fallback workbook builder, to
      `_repair_template_workbook`, and auto-created on first `record_cycle_start`.)*
- [x] **Historical backfill: `/cycle detect`** — one-pass scan of the whole history:
      every Income row with category Salary. Unambiguous months listed with a single
      "Confirm all" button; ambiguous months walked one at a time with inline pickers
      and a "Custom date" fallback. *(done PR #32: `detect_cycle_candidates()` +
      `record_cycle_starts_batch()` in `cycles.py`; full UX in `handlers/cycle.py`.)*
- [ ] **Lazy backfill on report** — cycle report requested for a period with missing
      boundaries → run the same detection scoped to that period and ask before
      rendering. Same engine, two triggers (explicit command + lazy on demand).
- [ ] **`none this month` is a valid answer** — a gap can be legitimate (no salary that
      month: job gap, delayed payment). "none" extends the previous cycle (a 60-day
      cycle is valid data, not an error) instead of fabricating a boundary; unaccounted
      math stays honest over long cycles.
- [ ] **Candidate window when detection finds nothing** — show Income rows (any
      category) from the 20th of the previous month through the 5th of the target
      month; if none, the largest 3 credits in that window; user picks one or types a
      date. Catches the ±4-5-day payday drift without dumping a month of noise.
- [ ] **Past/entire-period reports walk the ledger** — `/summary aug 2025` or "entire
      period" iterates ledger rows: each cycle ends where the next begins, the last
      ends today. A hole in the walk triggers the lazy backfill prompt before
      rendering. No special-case logic for historical queries.
- [ ] **Before the first boundary** — transactions older than the first recorded cycle
      form an implicit "Before cycles" bucket: included in entire-period reports under
      that label (never silently omitted), listed in the cycle picker as
      "Before cycles (… – first start)", and excluded from unaccounted math (no salary
      anchor exists there). Backfill can shrink this bucket by recording earlier
      boundaries; "none this month" for the very first gap simply leaves rows in the
      bucket instead of extending a nonexistent previous cycle.
- [ ] **Multiple salary rows in one window (salary + overtime, all category Salary)** —
      backfill: each ambiguous month gets its own inline-button prompt, one candidate
      per button (largest amount listed first — main salary beats overtime), plus
      `Custom date` and `No cycle this month`:
      "Jul 2026 — which payment starts the cycle?
       [ ① 25 Jun · salary · 6 000 PLN ] [ ② 28 Jun · overtime · 900 PLN ]
       [ Custom date ] [ No cycle this month ]"
      One tap per gap; typing only for Custom date (e.g. 2026-07-23). Never
      auto-recorded. Buttons, not reply grammar — same interaction language as the
      /summary picker.
      Live: a Salary-row save triggers the new-cycle prompt only if the current cycle
      is older than ~20 days (configurable); younger → income inside the cycle,
      silently counted, no re-prompt.

## Follow-up PR: currency and timezone neutrality sweep (found 2026-07-24)

Help text examples updated to EUR in PR #32 (groceries example, setbudget limit prompt,
rates help). Remaining PLN references in business logic strings and any timezone-specific
wording need a second pass — deferred to avoid scope creep in PR #32.

- [ ] **Remaining PLN in runtime messages** — `handlers/misc.py`: setcurrency confirmation
      note (`1 {ccy} = {rates[ccy]} PLN`), setcurrency pick confirmation (`Rate: 1 {ccy} = X PLN`),
      setbudget category picker label (`Budget (PLN)`), setbudget amount prompts and confirm
      messages. `handlers/add_conv.py`: PLN equivalent note shown during /add.
      `handlers/reports.py`: rates display lines (`PLN per 1 unit`, `{r:.4f} PLN`).
      Decide per-string: use display currency where possible; keep PLN where it is the
      factually correct base-currency label.
- [ ] **Timezone wording sweep** — `handlers/add_conv.py:183`: "(UTC) aren't allowed"
      is already UTC; verify no other handler surfaces a timezone name to the user. If
      any Poland/Warsaw-specific timezone text exists in user-facing strings, replace with
      UTC or a generic "your local time" phrase.

- [ ] **Default-currency fallback hardcodes PLN** — `data.py` (`fillna("PLN")`),
      `models.py` / `states.py` transaction defaults, `scheduled_report.py` fallback,
      `excel_schema.py` writer default (`row.get("currency", "PLN")`). For a public repo
      the fallback must come from the `DISPLAY_CURRENCY` setting (already prompted in
      `setup_bot.py`), not a hardcoded currency — swapping PLN for EUR/USD would repeat
      the same mistake. One source of truth: `settings.DISPLAY_CURRENCY`.

### Additional PLN hardcodings found in scan (2026-07-24)

### IMPROVEMENT — `goal_pln` field and "Goal (PLN)" column header in ListsSchema
- `excel_schema.py:236`: `goal_pln: Any = col("Goal (PLN)")` — the Pydantic field name
  and the Excel column header both embed "PLN". Any non-PLN user sees a "Goal (PLN)" column
  header in their spreadsheet and the schema attribute name is misleading.
- Expected: rename column header to "Goal" (or "Goal (base)") and field to `goal_base`;
  migration script or `ensure_lists_sheet` rename on first open so existing workbooks
  are upgraded transparently.

### IMPROVEMENT — `/cycle detect` inline-button labels hardcode PLN
- `handlers/cycle.py:144`: unambiguous-month summary line renders
  `{amount:,.0f} PLN` verbatim.
- `handlers/cycle.py:178`: per-candidate inline-button label renders
  `{date} — {amount:,.0f} PLN` verbatim.
- Expected: replace the bare "PLN" with the configured display currency
  (`get_display_currency()`) so detect labels match all other bot amount strings.

### IMPROVEMENT — AI parser prompt hardcodes Polish "zł/zl = PLN" shorthand
- `ai_parser.py:280`: the bulk-parse system prompt includes `"zł/zl = PLN"` as a
  currency alias hint. This is Poland-specific; a non-PLN user will never type "zł"
  and the hint adds noise that could mislead the model into defaulting to PLN.
- Expected: omit the alias entirely, or make it conditional on PLN appearing in
  `lists["currencies"]`.

### IMPROVEMENT — Template script resets Dashboard Currency filter to PLN
- `scripts/make_template.py:95`: `ws.cell(2, c + 1, "PLN")` hard-resets the
  Dashboard Currency dropdown cell to "PLN" when generating or resetting the template.
  A non-PLN user who regenerates the template loses their currency filter setting.
- Expected: read the first entry from the Lists currencies range and use that as the
  reset value, or leave the cell blank (showing all currencies).

## Follow-up PR: cycle-aware report gaps (found 2026-07-24)

When `BUDGET_CYCLE=1`, the following commands are still calendar-scoped while `/summary`
and `/budget` are already cycle-scoped — giving contradictory numbers in the same session.
All three need the same `_current_cycle_bounds()` branch that `/summary` and `/budget` use.

- [ ] **`/report` still calendar-based** — `cmd_report` (handlers/reports.py:~325) uses
      `current_year_and_month()` with no cycle branch. Month-over-month delta block also
      uses calendar arithmetic. Accidental omission.
- [ ] **`/top` still calendar-based** — `cmd_top` (handlers/reports.py:~235) filters on
      `df["Year"] == year` and `df["Month"] == month`. Accidental omission.
- [ ] **`/savings` 6-month trend is calendar-based** — `cmd_savings` (handlers/reports.py:~277)
      iterates over calendar months. A full cycle-aware redesign (last N cycles instead of
      last N calendar months) is non-trivial and lower priority than report/top, but the
      current-month bar mismatches the cycle-scoped `/summary` rate.
- [ ] **`check_budget_alert` still calendar-scoped** — already tracked in "PR #30 review
      notes" above (line starting "check_budget_alert still calendar-scoped"). Contradictory
      percentages after every save when the flag is on.

## Follow-up PR: E2E test coverage (gap found 2026-07-24)

No end-to-end flow tests exist. Unit tests cover individual functions; no test exercises
a full command from Telegram update → Excel write → reply. Confirmed gap 2026-07-24.

- [x] **Golden-path E2E tests** *(done PR #49 — 60 E2E tests across /add, /bulk text+file, /edit, /delete, /summary, /report, /cycle, /help)*
- [x] **Edge-case E2E** *(done PR #49 — cycle detect, bulk file, hostile name, empty first_name covered)*
- [ ] **Regression guard** — run E2E suite in CI on every PR (currently only unit tests run).

## Follow-up PR: /summary picker UX — agreed design (brainstorm 2026-07-22)

- [x] **Free-form argument parsing, order-independent** *(done PR #45)* — `/summary aug 2025`,
      `2025 aug`, `08.2025`, bare `aug` (= most recent occurrence of that month) all
      resolve without a fixed year-then-month order.
- [x] **Bare `/summary` → one message, three zones** *(done PR #45)* — buttons appear ONLY on bare
      /summary (no arguments); any typed argument renders the report directly.
      Zone 1 (quick row, top): flag off → This month · Last month;
      flag on → This cycle · Last cycle · This month · Last month.
      "This cycle" = last recorded boundary → today (how am I doing on this salary);
      "Last cycle" = between the two most recent boundaries (what happened to the
      previous salary — the leftover metric's home). Most calls end here.
      Zone 2 (history drill-down, beneath): flag off → year buttons directly;
      flag on → 📅 Calendar / 💰 Cycle choice first. Calendar → year buttons
      (actual MasterData years, newest first, only years with data) → month buttons
      (only months with data) → report. Cycle → ledger list, newest first, labeled
      with ranges: "Aug (23 Jul – today)", "Jul (25 Jun – 22 Jul)", "Earlier…" paging;
      a hole in the ledger triggers the lazy backfill prompt.
      Calendar/Cycle is never a gate — the quick row sits above it on the same screen.
- [x] **`/summary jul` with cycles enabled** *(done PR #45)* — a bare month name resolves against the
      ledger label first (cycle "Jul"), calendar month only when no such label exists.
- [x] **Range support, both forms** *(done PR #45)* — free-form `/summary aug 2025 - jan 2026`
      (reuse the existing /range parsing pattern) and a `Range…` button that walks the
      same year→month picker twice ("From:" then "To:", prompt text shows progress).
      No new UI concepts — the same pickers, used twice.
- [x] **Year overflow paging** *(done PR #45)* — years beyond ~2 rows of 4 buttons collapse into an
      "Earlier…" page (Telegram inline-keyboard height limits).

## Follow-up PR: bank-statement profiles — agreed design (brainstorm 2026-07-22)

Goal: import any bank's CSV/XLSX export without hardcoding any bank in the public repo.
Profiles are per-user local JSON — `data/statement_profiles/<name>.json`, gitignored like
the live Excel and merchant map. No bank name ever enters the repo; only an
`example.json` with fake columns ships.

- [ ] **Profile contents** — delimiter, encoding, header row index, column→field mapping
      (date, amount, currency, description, optional time), date format, decimal
      convention, sign convention (negative = expense). Header fingerprint stored inside
      the profile (set/order of header names) — matching is by fingerprint, never by
      filename or profile name.
- [ ] **First upload of unknown format (via /bulk attachment)** — read locally; no
      fingerprint match → ONE small AI call with header row + 2-3 masked sample rows
      (amounts/account numbers masked) proposes the mapping. User reviews a ready
      answer, never assembles from scratch:
      "New statement format detected. My reading: column 2 → date (DD.MM.YYYY) ·
       column 7 → amount (comma decimal, negative = expense) · …
       [ Looks right ] [ Fix a column ] [ Cancel ]"
      Fix a column = button walk (pick column → pick field). Nothing saved until
      confirmed. Then: "Name this format?" with suggested default; saved locally.
- [ ] **Known format** — fingerprint match → zero questions, zero tokens, deterministic
      extraction; preview opens with one status line: "📄 Parsed with profile 'MyBankA' —
      42 rows." Categorization runs the normal pipeline (merchant map 🧠 first, AI only
      for unknown merchants) — this IS the token-economy "split extraction from
      categorization" item for statement imports.
- [ ] **Bank redesigns the export** — fingerprint stops matching (all-or-nothing; a
      changed format can never half-match/misparse) → new-format flow reruns. Before
      proposing from scratch, compare the new header against saved profiles: ~80%
      similar → "This looks like an updated MyBankA format (2 columns changed). Update
      MyBankA or save as new?" Old profile is KEPT either way (matching is by
      fingerprint, so profiles coexist under one bank) — re-downloaded historical
      statements arrive in the format of their era and still parse silently.
- [ ] **Feeds dedup v2 — within-batch only (design correction, review 2026-07-22)** —
      MasterData has NO time column, so HH:MM can never appear in keys compared against
      stored rows (time-bearing draft keys would never match timeless stored keys and
      dedup would silently stop firing — the opposite of the goal). Corrected rule:
      the profile's time column disambiguates identical rows WITHIN one statement
      (count-aware logic gets exact per-day counts); cross-import keys stay timeless.
      Persisting time cross-import would require a MasterData Time column — a schema
      change deliberately NOT part of this design; revisit only if timeless+count-aware
      dedup proves insufficient in practice.
- [ ] **`.txt` that is secretly a CSV** — some banks export column-structured files named
      .txt (tab/semicolon separated). On .txt upload, sniff: if the content splits into
      consistent columns, offer the profile flow; otherwise AI free-form parsing as
      today. Plain receipts/pasted text keep the current path unchanged.

## Follow-up: bank-statement profiles review notes (PR #18, 2026-07-23)

- [ ] **Dead `BULK_STATEMENT = 402` constant** — `states.py` defines `BULK_STATEMENT = 402` and it is imported in `handlers/bulk_conv.py` but never returned from any handler and never registered in `bot.py`'s ConversationHandler. The CSV/XLSX detection happens synchronously inside `BULK_RECEIVE`; no intermediate state is needed. Either remove the constant or add an explicit comment marking it as a reserved placeholder.
- [ ] **`_stmt_*` keys not cleaned up on cancel/timeout** — `ctx.user_data` keys `_stmt_file_bytes`, `_stmt_proposal`, `_stmt_filename`, `_stmt_headers`, `_stmt_fix_col` are never cleaned up by the existing `bulk_confirm` or `bulk_timeout` handlers. On a restart with `PicklePersistence`, stale file bytes from a prior abandoned session persist in `user_data`. Add cleanup of all `_stmt_*` keys in the cancel and timeout paths.
- [ ] **`time` field survivability through normalization** — `parse_statement` returns rows with a `time` key reserved for dedup v2's within-batch count-aware matching. Verify that `time` survives through `_normalize_parsed_rows` and `_validate_bulk_rows` into the draft dict. If `Transaction` has no `time` field and drops it silently, dedup v2 will need to re-add it to the model and write path before relying on it.
- [ ] **Header-reading duplicated across module boundary** — `bulk_conv._read_statement_headers_and_sniff` and `_get_sample_rows` each open the file bytes independently (and XLSX bytes are opened twice via openpyxl), while `statement_profiles.parse_statement` opens them a third time. `statement_profiles.py` should own all file-reading; `bulk_conv.py` should call a `read_headers(file_bytes, filename) -> list[str]` function from the module instead of duplicating the logic.
- [ ] **Profile registry reloads from disk on every upload** — `_load_profiles()` in `bulk_conv.py` globs and reads all `.json` profile files on each document upload. Profiles are immutable at runtime (only written when the user completes the naming step). A module-level cache invalidated only after `save_profile` would be cleaner and explicit.
- [ ] **No file-size guard before storing in `user_data`** — `ctx.user_data["_stmt_file_bytes"] = file_bytes` stores raw file bytes for the lifetime of the profile-confirmation sub-flow with no size check. Add a size guard (e.g., reject files over a configurable MB threshold before entering the profile path) to prevent unbounded memory use.
- [ ] **`.txt` plain-receipt UX regression risk** — some plain receipts with aligned price columns (e.g., itemized printouts) could trip `sniff_txt_delimiter`'s 80% consistency threshold and enter the profile confirmation dialog unexpectedly, breaking the existing AI free-form parse path. Monitor after first real `.txt` upload that previously worked; tighten the sniff threshold or add a user-facing "this looks like a structured file — treat as statement?" prompt if false-positives occur.
- [ ] **`mask_sample_rows` amount-column masking is a no-op** — the stated invariant "amount column is always masked" is broken: the cell-value-to-column-name comparison can never match (a cell value like `45.99` is compared to the column name string `"Amount"`), and the call site passes `{}` so `amount_col` is `""`. In practice `_AMOUNT_RE` catches most numeric values, but amounts like `"1234.56"` with 4+ integer digits and no separator fall through unmasked. Fix: mask by column index position rather than by value comparison.
- [ ] **Dead code — unused variables in `bulk_profile_callback`** — in the `profile_ok` branch: `file_bytes` and `filename` are retrieved from `ctx.user_data` but never used (they are retrieved again in `bulk_profile_name`). In the `fix_field:` branch: `headers` is assigned but never referenced. Remove both.
- [ ] **Dead `try/except` around `bytes.decode("utf-8", errors="replace")`** — in `bulk_conv._read_statement_headers_and_sniff` and `_get_sample_rows`, the `except` branch is unreachable because `bytes.decode` with `errors="replace"` never raises. Remove the try/except wrapper.
- [ ] **`save_profile` not defensive against whitespace-only name** — `"   " or "unnamed"` evaluates to `"   "` (truthy), then `.strip()` yields `""`, producing `profiles_dir / ".json"` — a hidden file that silently overwrites any previous empty-name profile. The UI handler blocks this at the Telegram layer, but add a guard in `save_profile` itself: if `safe_name` is empty after stripping, default to `"unnamed"`.
- [ ] **`_column_pick_keyboard` one button per row** — each column gets its own `InlineKeyboardButton` row; banks with 25+ columns produce a 26-row keyboard which may hit Telegram's button limits or be visually unusable. Chunk 3–4 buttons per row.
- [ ] **Test: `sniff_txt_delimiter` tie scenario** — when two delimiters score identically the first candidate wins silently. A file with an equal number of semicolons and commas (e.g., description fields containing commas in a semicolon-delimited file) could trigger this; document and test the tie-breaking behavior.
- [ ] **Test: profile name collision / overwrite** — `save_profile` silently overwrites an existing `<name>.json`. Test and document this behavior; consider a warning if a profile with the same name already exists.
- [ ] **Test: `load_profiles` with valid non-dict JSON** — the code guards `if not isinstance(profile, dict)` and skips; there is a test for malformed JSON but not for valid JSON that is an array or string. Add a test.
- [ ] **Test: `parse_statement` with headers-only, no data rows** — should return `[]` gracefully; the user-facing "no transactions found" path is untested.
- [ ] **Test: unknown encoding in profile → `LookupError` fallback** — `parse_statement` catches `LookupError` when `profile["encoding"]` specifies an unknown codec and falls back to `utf-8, errors="replace"`. The fallback is untested and silent; add a test and consider surfacing a warning to the user.
- [ ] **Test: zero-amount row classification** — `"0.00"` passes the empty-check and under `negative_expense` becomes Income type with value 0 (possibly a fee-waiver or balance row). Test and document the intended behavior.
- [ ] **Test fixture: shallow copy of `BANKA_PROFILE` fixture** — `test_multiple_profiles_loaded` does `{**BANKA_PROFILE, ...}` which is a shallow copy; `column_map` is the same object as `BANKA_PROFILE["column_map"]`. Any future test mutating `p2["column_map"]` in-place would corrupt the shared fixture. Use `copy.deepcopy(BANKA_PROFILE)` in the fixture or a factory function.

## Follow-up: /cycle detect review notes (PR #32, 2026-07-24)

- [x] **`awaiting_detect_date` leaks / `handle_detect_text` has no `@auth_write`** —
      both issues eliminated: custom-date text input removed entirely in the detect
      redesign. The detect flow is now fully inline-button driven; no group-2 text
      handler exists. (`handlers/cycle.py`)
- [ ] **Empty-fingerprint fallback in bulk_conv is silent** — the `or []` guard on
      `profile["fingerprint"]` is unreachable in the normal path, but if it fires the
      profile saves with an empty fingerprint and will never match on re-upload. Add a
      `log.warning` at that branch. (`handlers/bulk_conv.py` near `bulk_profile_name`)

## Follow-up: /cycle detect review notes (cycle-detect redesign, 2026-07-24)

- [ ] **`detect:stop` reports "recorded" but counts reviewed** — the stop message
      says "Recorded N boundaries so far" but N is computed as
      `detect_total - len(detect_queue)`, which counts both confirmed and skipped
      entries. If the user skipped any, the count overstates actual boundaries written.
      Track confirmed count separately in `ctx.user_data["detect_confirmed"]` and
      increment only on `detect:pick`. (`handlers/cycle.py` `handle_detect_callback`)
- [ ] **"Two salary payments" hardcoded — breaks for 3+ salaries on same date** —
      `_send_detect_prompt` renders `"Two salary payments: …"` unconditionally when
      `not entry["unambiguous"]`. If three salary rows share a date the label is wrong.
      Fix: `f"{len(entry['amounts'])} salary payments"`. (`handlers/cycle.py`)
- [ ] **`detect_candidates` not cleared when entering review mode** — `detect:review`
      sets `detect_queue = list(candidates)` but leaves `detect_candidates` in
      `user_data`. A second `/cycle detect` mid-review overwrites `detect_candidates`
      while `detect_queue` is still active, leaving inconsistent state. Pop
      `detect_candidates` inside the `detect:review` branch. (`handlers/cycle.py`)
- [ ] **No currency label on amounts in the detect summary list** — amounts render as
      bare numbers (`12,027`) with no currency symbol. Append `get_display_currency()`
      (or `settings.DISPLAY_CURRENCY`) alongside each amount line.
      Part of the broader PLN/currency sweep. (`handlers/cycle.py` `_cmd_cycle_detect`)

## Follow-up: profile review notes (PR #27, 2026-07-23)

Non-blocking findings from the PR #27 review (debit/credit split columns + profile deletion):

- [ ] **`validate_profile_mapping` `amount+credit` conflict case untested** — the
      symmetric `amount+debit` conflict is covered by a test; add the `amount+credit`
      counterpart. (`statement_profiles.py`)
- [ ] **Parser behaviour untested for debit-only split mapping** — when
      `sign_convention` is `debit_credit_split` but `column_map` contains only
      `debit` (no `credit`), the parser's behaviour is untested; add coverage and
      document the intended result. (`statement_profiles.py`)
- [ ] **Possible test-isolation flake** —
      `tests/test_cycles.py::TestAppendCycleBoundary::test_creates_sheet_and_appends`
      failed once in a full-suite run but passes in isolation and on rerun;
      investigate test ordering / shared state.

## Follow-up: PR #43 review notes (2026-07-25)

Non-blocking findings from the PR #43 fan-out review (Architect, EM, Tester, TW):

### Architect

- [ ] **Bulk formula-injection guard duplicates `sanitize_description`** —
      `_revalidate_bulk_row` (`handlers/bulk_conv.py` ~1158) re-implements
      `formatters.sanitize_description` inline instead of calling it. Call
      `sanitize_description` or extract the guard into a shared helper; as-is,
      bulk skips the merchant-junk cleanup and truncation every other path gets.
- [ ] **Salary detection rule lives in two places** — `cycles.py::salary_mask`
      (pandas) and `handlers/cycle.py::maybe_prompt_cycle_start`
      (per-transaction) both encode the rule. Extract a shared
      `is_salary_row(category, description)` predicate in `cycles.py` so the
      handler stays thin.
- [ ] **Overflow buffer `_pending_overflow` is in-memory only** — a restart
      between the overflow warning and save/cancel silently loses it. Persist
      alongside the draft or as a second draft slot. (`handlers/bulk_conv.py`)
- [ ] **"Fallback to Other" policy embedded twice** —
      `validators.validate_parsed_row` and `_revalidate_bulk_row` both embed
      the policy; consolidate. (`validators.py`, `handlers/bulk_conv.py`)

### EM

- [ ] **Category matching silently broadened in `cycles.py`** — exact `isin`
      became word-boundary `contains` (e.g. "Salary Bonus" now matches). The
      behaviour is intentional but undisclosed; the PR description should note
      it explicitly.
- [ ] **Overflow `cancel` returns `BULK_CONFIRM` instead of `END`** — when
      overflow exists; verify this doesn't leave the user stuck in
      conversation state after cancelling. (`handlers/bulk_conv.py`)

### Tester

- [ ] **`maybe_prompt_cycle_start` description-match path has zero test
      coverage** — the test factory `make_transaction` has no `description`
      param. (`handlers/cycle.py`, tests)
- [ ] **Overflow buffer transitions untested** — `bulk_receive` populating
      `_pending_overflow`, release on save success, and NOT releasing on
      save-with-failed-items are all untested. (`handlers/bulk_conv.py`, tests)
- [ ] **Error handler send-failure path untested.**
- [ ] **Formula guard tests only cover `=`** — the `-` prefix mutating
      legitimate descriptions (e.g. "-5% discount") is worth pinning with a
      test.
- [ ] **`/edit` sanitization side effects unasserted** — merchant cleaner +
      truncation on edited descriptions have no assertions.
- [ ] **Validator promotion untested without an "Other" category entry** —
      behaviour when Lists lacks "Other" is unpinned. (`validators.py`, tests)

### TW

- [ ] **DOCUMENTATION.md "How a salary is detected" (~line 422) is stale** —
      needs the new blank-Category gate and word-boundary Category matching.
- [ ] **Bulk draft-limit doc (~line 376) describes old behaviour** — still
      says "save or cancel"; the overflow-holding behaviour is undocumented.
- [ ] **Savings-category promotion undocumented** — category "Savings" →
      type Savings + category Other is not covered in the quick-add/bulk docs.
- [ ] **Formula-injection apostrophe prefix worth a doc note** — `=+-@`
      descriptions get a leading apostrophe, which affects "-5% discount"
      style entries.

## Follow-up: PR #44 review notes (2026-07-26)

Non-blocking findings from the PR #44 review (/keywords feature):

- [ ] **`load_salary_keywords` duplicates strip/lowercase/dedup loop** —
      `cycles.py::load_salary_keywords` re-implements the same strip/lowercase/dedup
      loop that `_keyword_column_words` already provides. `load_salary_keywords` should
      call `_keyword_column_words` instead of duplicating the logic. (`cycles.py`)
- [ ] **`save_salary_keyword` re-seeds from `.env` on empty list** —
      `save_salary_keyword` re-seeds from `.env` whenever the stored keyword list is
      empty, not just on first use. If the user removes all keywords, the next `/keywords
      add` silently re-seeds from the env defaults before appending. Either guard by
      checking whether the header row already exists (meaning the sheet was intentionally
      emptied), or update the docstring to document the actual behaviour explicitly.
      (`cycles.py`)
- [ ] **`keywords_add_word` handler path for empty/whitespace input untested** —
      the storage-layer rejection of empty/whitespace input is tested, but the handler's
      re-prompt path (the Telegram reply asking the user to try again) is not covered.
      (`handlers/keywords_conv.py`, tests)
- [ ] **`save_salary_keyword("payroll")` when env already contains "payroll"** —
      returns `False` but the Excel write still happened; the False-return contract is
      surprising for callers who expect "False means nothing was written". Add a test
      that asserts the exact return value and Excel state for this case. (`cycles.py`,
      tests)
- [ ] **`test_detect_keywords_prefer_excel_over_env` tests seeded content, not pure
      Excel content** — the test exercises env-seeded-then-persisted keywords rather
      than keywords written directly to Excel bypassing `save_salary_keyword`. The test
      name and intent are misleading. Add a companion test that writes keywords directly
      to the Excel sheet to verify the Excel-over-env preference on genuinely
      non-seeded data. (`tests/test_cycles.py`)
- [ ] **`delete_salary_keyword("")` untested** — deleting an empty string is a benign
      named path (returns False, no-op) but has no test. Add a minimal test.
      (`tests/test_cycles.py`)
- [ ] **`_keywords_view()` source label misleading when both env and Excel are empty**
      — currently shows ".env fallback" even when both env and Excel are empty. Consider
      changing the label to "Not configured — use ➕ to add the first keyword" for this
      state. (`handlers/keywords_conv.py`)
- [ ] **Pre-existing flaky test `test_seed_from_master`** — `tests/test_merchant_map.py`
      has a Windows file-lock race on `os.replace` during atomic save; fails
      intermittently under parallel test runs. Unrelated to /keywords — needs its own
      investigation and fix. (`tests/test_merchant_map.py`)

## Follow-up: PR #45 review notes (2026-07-26)

Non-blocking findings from the PR #45 fan-out review (/summary picker UX). Safe to merge as-is.

**Correctness / robustness:**

- [ ] **`sum_range` user_data state never cleared when the range walk is abandoned** —
      a user who starts the `sum:rng` From/To walk and then taps a month button later
      silently re-enters the From/To flow instead of getting a month report. Clear the
      state in the `cmd_summary` bare path and on quick-button actions
      (`tm`/`lm`/`tc`/`lc`/`cs`). (`handlers/reports.py:260`, also flagged at :186)
- [ ] **`handle_summary_callback` has no `@auth` guard** — mirrors the pre-existing
      `handle_range_callback` pattern; queue an auth-for-callback-handlers pass across
      all read callbacks. (`handlers/reports.py:189`)
- [ ] **Forged/stale callback data can raise unhandled exceptions** — `parts[1]`
      IndexError on bare `sum:`; `date.fromisoformat(parts[2])` ValueError in the `cs`
      branch on malformed dates. Add a defensive length check or try/except.
      (`handlers/reports.py:222`)
- [ ] **`/summary 2027` (future year) returns a full-year range over empty data**
      instead of a "no data" message — the `min(..., today)` capping only applies when
      `year == today.year`. (`handlers/summary_picker.py:172`)
- [ ] **Dead import: `most_recent_year_for_month`** — imported inside
      `handle_summary_callback` but never used there. (`handlers/reports.py:193`)

**Architecture:**

- [ ] **Cycle-boundary derivation exists in three places** —
      `cycles.current_cycle_start`, `reports._current_cycle_bounds`, and
      `summary_picker.cycle_bounds`; consolidate into `cycles.py` as the single owner.
      (`handlers/summary_picker.py:57`)
- [ ] **Two parallel range-report UIs** — `range:` presets + free-text vs `sum:rng`
      two-step walk + free-form args, with disjoint callback namespaces and separate
      user_data keys (`awaiting_range`, `sum_range`). Consider retiring `/range` or
      re-routing it through the picker. (`handlers/reports.py:582-768`)

**Test gaps (`tests/test_summary_picker.py`):**

- [ ] **Empty-state handler branches untested** — `sum:cyc` with empty ledger,
      `sum:tc`/`sum:lc` with too few cycles, `sum:cal`/`sum:rng` with empty DataFrame,
      `sum:y` for a year with no months, `sum:cs` for a stale cycle start.
- [ ] **Inverted range via button walk untested** — the handler auto-swaps From/To
      while free-form inverted input returns None; the behavioral divergence has
      coverage only on the free-form side.
- [ ] **`sum:tm`/`sum:lm` handler branches untested** — especially Last month across
      the year boundary (January → December of the prior year).
- [ ] **Unknown-callback-action fallback and the FileNotFoundError branch of
      `handle_summary_callback` untested.**
- [ ] **Parser duplicate-slot inputs untested** — e.g. `aug 2025 2026`,
      `08.2025 sep`; both should return None per the put() guard.
- [ ] **Stray `excel_path=None` parameter in `test_cycle_button_lists_ledger`
      signature** — cosmetic dead artifact. (~line 330)

**Docs / wording:**

- [ ] **`BotCommand("summary", …)` description stale** — still "This month at a
      glance"; update after the docs PR lands. (`bot.py:96`)
- [ ] **/start text "Try /summary to start" is now a stronger onboarding hook** —
      optional wording refresh. (`handlers/misc.py:30`)
- [ ] **/cycle help card says "with cycles enabled, /summary covers the current
      cycle"** — still true via the "This cycle" button, but worth clarifying when
      touching docs. (`handlers/cycle.py:42`)

## Follow-up: Cycle Dashboard review notes (PR #46, 2026-07-26)

Non-blocking findings from the PR #46 fan-out review (Cycle Dashboard feature).

### Architect

- [ ] **Deferred imports masking a structural cycle** — `cycles.py` still uses deferred inline imports (`from cycle_dashboard import ensure_cycle_dashboard` inside function bodies) as a workaround for the previous circular dependency. Now that `_to_date` is in `excel_schema`, investigate whether the top-level import can be promoted; deferred imports make the dependency graph harder to read. (`cycles.py` `record_cycle_start`, `record_cycle_starts_batch`)
- [ ] **Local copy of Dashboard sheet name constant** — `cycle_dashboard.py` defines its own `DASHBOARD_SHEET_NAME = "Dashboard"` instead of importing a shared constant from `excel_schema.py`. If the sheet is ever renamed this copy silently diverges. Move to `excel_schema.py`. (`cycle_dashboard.py`)

### Reviewer

- [ ] **Escape or validate `salary_category` before embedding in Excel formula string** — `_sumifs_salary` interpolates `salary_category` directly into the formula string; a value containing a double-quote would emit a syntactically broken formula. Escape or validate the value before interpolation. (`cycle_dashboard.py` `_sumifs_salary`)
- [ ] **`sync_cycle_dashboard_categories` over-clearing risk when `current_cats is None`** — when the Cycle Dashboard exists but has no TOTAL row, `old_total_row` falls back to 11 and the clear loop upper bound is `max(11, ws.max_row) + 1`, which could wipe legitimate content in columns H–L below the category block. Tighten the bound or document the assumption. (`cycle_dashboard.py` `sync_cycle_dashboard_categories`)
- [ ] **Missing comment on intentional Var % omission in `_write_total_row`** — the TOTAL row skips the Var % (column L) because summing percentages is meaningless, but this is not documented; a reader may mistake it for a bug. Add a one-line comment. (`cycle_dashboard.py` `_write_total_row`)

### TW

- [ ] **Scripts inventory missing from DOCUMENTATION.md** — `sync_cycle_dashboard.py` (and the pre-existing scripts `fix_formula_bounds.py`, `fix_import_errors.py`, etc.) are undocumented at the doc level. Create a "Maintenance Scripts" table in DOCUMENTATION.md covering all scripts in `scripts/` (purpose, when to run, flags). (`DOCUMENTATION.md`)

## Follow-up: Wave 2 Group B (PR #64, 2026-07-27)

- [ ] **Hardcoded PLN fallbacks sweep** — `row.get("currency", "PLN")`-style
  defaults are hardcoded across the codebase (`handlers/bulk_conv.py`,
  `validators.py` `_dedup_key_parts`, `models.py`, formatters, etc.) even
  though `DISPLAY_CURRENCY` already exists in settings/.env. Sweep every
  hardcoded `"PLN"` fallback and route it through `settings.DISPLAY_CURRENCY`
  (or a new `DEFAULT_CURRENCY` setting if display and entry defaults should
  diverge). PR #64 already did this for the AI prompt reference block; the
  rest of the code still assumes PLN. Locale-neutrality follow-up to the
  earlier PLN-hardcoding sweep.

## Notes

- Findings about `excel_schema` adoption, atomic saves, phantom-row replay, shared row-writer,
  preview pagination, /save handling, and bulk timeout were already fixed in PR #3
  (commits 4b5fd47 … 8260bd1).
