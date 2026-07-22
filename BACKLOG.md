# Backlog

Findings from the whole-team review (Architect, Designer, Developer, PO, fresh-eyes reviewer)
of 2026-07-21 on branch `feat/bulk-import-draft-ordering`. Grouped by planned follow-up PR.
Items marked **[PR #3]** should land in the current bulk-import PR before merge.

## In scope for PR #3 (bulk-import bug fixes)

- [ ] **[PR #3] Draft-limit path discards just-parsed input** — `handlers/bulk_conv.py` `bulk_receive`:
      when `_draft_limit_reached` fires, the freshly parsed rows (already paid for with an AI call)
      are dropped without warning. Keep them in a holding buffer or warn explicitly.
- [ ] **[PR #3] Preview edits not persisted to draft file** — `bulk_confirm` `reason == "edited"`
      updates `ctx.user_data` only; restart/timeout re-merges pre-edit values from disk.
      Call `_save_bulk_draft` after each edit.
- [ ] **[PR #3] Recovery replay writes Date as text string** — `append_to_recovery_queue` JSON-serializes
      dates with `default=str`; `replay_recovery_queue` writes the string verbatim into the Date cell.
      Rehydrate with `date.fromisoformat` (+ coerce value/is_recurring) before `write_transaction_row`.
- [ ] **[PR #3] Cosmetic cleanup** — dead `"resolved"` status filter in `_draft_limit_reached`
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

## Follow-up PR: merchant memory & description quality

- [ ] **Description cleanup** — MasterData gets `4111XXXXXXXX1111 SHOP TERMINAL 12 CITY PL` and
      `/OPT/X///// BPID:EXAMPLE123 Autopay S.A.`. (a) Prompt: output clean 2-4 word merchant labels;
      (b) deterministic regex post-processor (strip masked PANs, `BPID:` codes, `/OPT/` blocks,
      city/country suffixes) applied on all three entry paths — extend `formatters.sanitize_description`
      and actually call it in quick_conv and bulk_conv.
- [ ] **Merchant→category memory** — `MerchantMap` store (sheet or JSON): cleaned merchant →
      category/type/label/person/is_recurring defaults. Lookup before AI; learn from preview edits
      (`2 category=Transport` writes the mapping back); seed from MasterData history.
      Makes categorization deterministic and cuts DeepSeek calls.

## Follow-up PR: infra & performance

- [ ] **.bak leak on remote backends** — `atomic_save` writes `.bak` next to the temp download on
      GCS/S3; nothing cleans it. Skip the backup for temp files, or register in `_temp_files`.
- [ ] **Reference-data TTL cache** — every message triggers 2-4 full workbook reads
      (`load_reference_data` = `load_lists` + `load_rates`, two full parses of the same file).
      60-300s module-level cache in data.py, invalidated by writes in excel_ops.
      On remote backends each read also re-downloads the workbook.
- [ ] **Recovery queue as append-only JSONL journal** — current read-append-write JSON with no lock;
      enqueue batches/deletes/edits as typed operations; periodic replay job in APScheduler
      instead of startup-only.
- [ ] **Lost-update protection for remote backends** — `ExcelFileContext` does blind
      download→modify→upload; use GCS generation / S3 ETag preconditions and retry on conflict.
- [ ] **_load_bulk_drafts reads every user's file** — called 3× per message just to fetch one
      user's draft; read `_user_draft_path(uid)` directly.
- [ ] **Split file_storage god module** — backends / workbook repo / template concerns;
      backend selection should honor `STORAGE_BACKEND` strictly (a stray `GCS_BUCKET_NAME`
      env var currently overrides `STORAGE_BACKEND=local`).
- [ ] **DeepSeek output as typed model** — validate provider output into a Pydantic
      `ParsedTransaction` at the parse boundary so drafts store validated data.

## Follow-up PR: UX

- [ ] **Person attribution per import** — bulk stamps `person=""` on everything; ask once
      "Whose statement is this?" and stamp all rows; per-row `4 person=X` override stays.
      /add: move person out of the mandatory flow (default household, edit from confirm card).
- [ ] **Recurring detection from history** — same cleaned merchant + similar amount (±10%)
      in ≥2 prior months ⇒ propose `is_recurring=True` (🔁 in preview, pre-selected in /add).
      Stop asking on every /add; bulk stops hardcoding False.
- [ ] **/add default-and-confirm** — 9 round-trips today; pre-fill PLN/Expense/today/non-recurring
      after amount+category and jump to the confirm card with "Edit a field…" (reuse edit_conv picker).
- [ ] **Discoverability** — `/bulk`, `/delete`, `/help`, `/setcurrency` absent from menus and /start;
      add 📥 Import + 🗑 Delete buttons; rewrite /start to show the three entry methods;
      register commands with BotFather.
- [ ] **Bulk edit UX** — `skip N` / `delete N` commands to drop a mis-parsed row without cancelling
      everything; on invalid edit, list the editable fields; validate category values against Lists.
- [ ] **Quick-add one-tap recovery** — on validation failure show what WAS parsed with a category
      keyboard instead of ejecting to the 9-step /add.
- [ ] **Report chunking can break Markdown entities** — `cmd_report` raw 4000-char split;
      reuse the paginated-send helper from bulk_conv.
- [ ] **edit_conv currency keyboard hardcodes 3/3 split** — breaks visually with >6 currencies.

## Follow-up PR: code clarity

- [ ] **Unit-less magic numbers sweep** — parameters like `conversation_timeout=1800` don't say
      seconds/minutes. Every duration, size, or count literal must be a named constant with the
      unit in the name (e.g. `BULK_REVIEW_TIMEOUT_SECONDS = 30 * 60`). bot.py timeouts done in
      PR #3; sweep the rest: `_PREVIEW_MSG_LIMIT` (chars), `_CHUNK_TARGET_CHARS`,
      `_BULK_MAX_TOKENS`, `_REQUEST_TIMEOUT_S` → `_SECONDS`, APScheduler cron params,
      `conversation_timeout` on /setcurrency and /add (currently unset = infinite — decide
      deliberately), recovery-queue retry counts, `$100` row bounds in VLOOKUP ranges.

## Follow-up PR: token economy (paid DeepSeek tokens)

- [ ] **Compact AI output format** — replace keyed JSON objects (~120 output tokens/txn) with
      positional arrays `["2026-07-05", 45.98, "PLN", "E", "Groceries", "Żabka", ""]` + letter
      codes for type. ~4-5× cut on output tokens (the expensive kind). Prompt change + decoder.
- [ ] **Split extraction from categorization** — regex extracts date/amount/description from
      structured bank statements locally; AI only categorizes a compact list of unknown merchant
      names (~5 tokens/txn instead of ~120). Shares foundation with merchant memory.
- [ ] **Merchant memory as token saver** — (see merchant-memory PR) deterministic lookup for
      repeat merchants = zero tokens; after a month ~80% of rows skip the AI entirely.
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
- [ ] **Per-operation audit line** — one structured log line per save attempt
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

- [ ] **Recovery-queue corruption bricks startup** — `append_to_recovery_queue` writes non-atomically
      (file_storage.py:118-123) and `flush_recovery_queue` does an unguarded `json.loads`; a crash
      mid-write leaves invalid JSON and `replay_recovery_queue()` at bot.py:83 raises on every start
      until the file is hand-deleted. Also flush unlinks the file BEFORE replay completes — a crash
      during replay loses all queued rows. Fix: atomic queue writes, guarded parse (quarantine a
      corrupt file with .corrupt suffix + log), delete queue only after successful replay.
- [ ] **Partial bulk save loses failed rows** — bulk_conv.py:425-448: rows failing Transaction
      construction go to `errors`, the rest save, then `_delete_bulk_draft` removes EVERYTHING.
      Fix: keep only failed rows in the draft after a partial save and tell the user how to fix/retry.
- [ ] **Stale row-index race in /delete and /edit** — row_idx captured at pick time, applied minutes
      later; interleaved deletes shift rows → wrong transaction silently deleted/edited
      (delete_conv.py:59-62, edit_conv.py:159-168). Fix: re-verify date+value+description under the
      write lock before applying; abort with a message if the row moved.
- [ ] **Repair scripts unsafe next to a live bot** — no _excel_write_lock, plain wb.save (no atomic),
      lost-update if the bot writes concurrently; on gcs/s3 they modify a local file the bot never
      uploads. Fix: scripts refuse to run when backend != local, take the lock file (once one exists),
      use atomic_save.
- [ ] **Dual logging setup** — config.py calls logging.basicConfig at import while logger.init_logging
      installs its own handlers → duplicate console lines, LOG_LEVEL partially overridden.
      One owner: remove the basicConfig from config.py.
- [ ] **Draft limit porous** — already tracked under "draft limit semantics"; reviewers add: no cap on
      a single oversized parse (400-row statement merges fine), no dedupe on merge.

Unique findings (single reviewer, verified plausible):

- [ ] **Date edit leaves Year/Month stale** — /edit writes only the edited column; reports filter on
      Year/Month so a re-dated row counts in the wrong month forever (edit_conv.py:163-168).
      Fix: when field == date, recompute and write Year + Month in the same save.
- [ ] **Formula injection via descriptions** — formatters.sanitize_description (leading '=' guard)
      is called only in add_conv.py:199; bulk (bulk_conv.py:436), quick-add (quick_conv.py:203) and
      /edit write raw untrusted text into cells. Fix: sanitize in write_transaction_row so every
      path is covered once.
- [ ] **Quick-add KeyError when Lists unreadable** — quick_conv.py:103 unconditionally indexes
      category_map; empty lists (file locked/renamed sheet) → unhandled KeyError → no reply at all.
      Fix: guard the lookup; if reference data is empty, reply with a clear "can't read your Excel" message.
- [ ] **Range-text listener crosstalk** — bot.py group=1 handle_range_text fires on every text;
      'awaiting_range' pops on unrelated messages mid-/add, and a valid range string also enters
      the quick-add conversation → duplicate replies. Fix: scope the flag check tighter
      (per-chat state + only when no other conversation active) or use a ConversationHandler.
- [ ] **fix_import_errors.py**: rule-3 (person→description) uses the description read BEFORE rule-2
      rewrote it — same-row combination silently undoes rule 2. Rerun also overwrites .bak with
      already-fixed data (backup should be write-once: skip if .bak exists).
- [ ] **Legacy scripts lack settings/backup** — fix_currency_range.py, fix_dashboard_validations.py,
      wire_budget_from_lists.py hardcode data/Expenses_Improved.xlsx, save without .bak;
      wire_budget_from_lists hardcodes Dashboard rows 11-27. Either upgrade to the settings+backup
      pattern or delete them (they were one-time migration scripts — deletion preferred).
- [ ] **rename_category.py gaps** — doesn't touch category names inside formula string-literals
      (SUMIFS criteria) nor pending bulk drafts in data/bulk_drafts/*.json (old name resurfaces and
      gets silently normalized to 'Other'). Fix: scan Dashboard/Monthly Summary formulas for the
      quoted old name; rename inside all pending drafts.
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

- [ ] **Exception message leak in /export** — handlers/misc.py `cmd_export`'s except branch replies
      with the raw exception text, which could include internal paths/bucket names; send a generic
      user-facing message and keep `log.exception` for server-side detail.
- [ ] **No file-size guard before reply_document** — Telegram bot API caps uploads at 50MB; add a
      size pre-check with a clear message before the workbook grows past the limit (same leak risk
      above if a raw Telegram error surfaces on failure).

## Follow-up PR: recovery-queue hardening (PR #2 review, 2026-07-22)

- [ ] **Quarantine rename failure retries forever** — file_storage.py: if the corrupt-queue-file
      `.replace(corrupt_path)` itself fails (e.g. permissions), the exception is caught and logged
      but the file stays at its original path; every subsequent flush hits the same JSONDecodeError
      and repeats the same failing rename. Not a data-loss risk, just log spam — give up after one
      retry or alert distinctly instead of looping silently.

## Follow-up PR: budget cycles — agreed design (brainstorm 2026-07-22)

Goal: restore the user's pre-bot salary-period tracking. Salary arrives around the 25th
but shifts ±4-5 days, so cycle boundaries are RECORDED EVENTS, never date formulas.
Answers "which salary funds this?" and "what happened to each salary?" (leftover /
unaccounted tracking — the old manual dashboard metric).

- [ ] **`BUDGET_CYCLE=1` env flag** — off by default; calendar behaviour unchanged for
      everyone else. When off, none of the below activates.
- [ ] **Cycle ledger** — one row per cycle: start date + label (e.g. "Aug"). Stored in
      Lists (new columns) so Excel formulas can reference it; bot reads/writes through
      excel_schema. Boundaries are written once and never recomputed — no retroactive
      re-bucketing, late edits cannot silently move history between cycles.
- [ ] **Boundary capture, user-confirmed** — two inputs, same ledger:
      (a) bot saves an Income row with category Salary → prompt: "💰 Salary received.
      Start the new budget cycle from 23 Jul? (yes / no / different date)" — the bot
      proposes, only the user's confirmation records; a mis-categorized refund cannot
      open a cycle. (b) `/cycle started [date]` manual command any time.
      No salary logged + no command = current cycle continues; the bot never guesses.
- [ ] **Bot reports per cycle** — with the flag on, `/summary` and budget bars compute
      over the current cycle (last boundary → today); days-remaining uses no assumption
      about cycle length. Monthly scheduled report fires on cycle close (boundary
      confirmation) instead of the 1st, reporting the cycle that just closed.
- [ ] **Unaccounted metric** — per cycle: salary received − tracked expenses − tracked
      savings = unaccounted ("not reported"); negative = over-reported (untracked income
      or previous cycle's leftover being spent). Shown in bot cycle reports and on the
      Cycle Dashboard.
- [ ] **Cycle Dashboard sheet** — duplicate of the existing Dashboard on a new sheet;
      same layout, same category rows, same budget targets (shared Lists budget column —
      one edit updates both). Filter is a single cycle selector (dropdown fed by the
      ledger) instead of Year+Month; all SUMIFS filter on Date >= cycle start AND
      Date < next start. Adds the salary/expenses/savings/unaccounted block and shows
      the cycle's day count (24-33 days — budgets are not pro-rated, matching the old
      manual system). The calendar Dashboard and Month/Year columns stay untouched —
      cycles are purely additive; disabling the flag corrupts nothing.
- [ ] **Sync check** — repair-script-pattern check that both dashboards carry the same
      category rows (new category must be added to both sheets).
- [ ] **Cycles sheet, not JSON** — the ledger lives in a dedicated `Cycles` sheet in the
      main workbook (start date + label per row) so Dashboard formulas can reference it;
      included in the template (harmless when the flag is off); auto-created on first
      use for existing workbooks; bot access through excel_schema.
- [ ] **Historical backfill: `/cycles detect`** — one-pass scan of the whole history:
      every Income row with category Salary (fallback: largest recurring end-of-month
      income for rows imported before categories were clean) → propose the COMPLETE
      ledger in one message, one `confirm all` for clear cases, per-row fixes for gaps:
      "Jun 2026 — salary 24 May (6 000 PLN) / Aug 2026 — ??? no salary found 20-31 Jul.
       Reply: confirm all · 3 = 2026-07-23 · 3 none".
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
- [ ] **Multiple salary rows in one window (salary + overtime, all category Salary)** —
      backfill: several candidates in a window → proposal lists them, largest amount
      pre-selected as default (main salary beats overtime), user confirms:
      "Jul 2026 — 2 candidates: ① 25 Jun salary 6 000 ② 28 Jun overtime 900 —
      reply `2 = 1` or a date." Never auto-recorded.
      Live: a Salary-row save triggers the new-cycle prompt only if the current cycle
      is older than ~20 days (configurable); younger → income inside the cycle,
      silently counted, no re-prompt.

## Follow-up PR: /summary picker UX — agreed design (brainstorm 2026-07-22)

- [ ] **Free-form argument parsing, order-independent** — `/summary aug 2025`,
      `2025 aug`, `08.2025`, bare `aug` (= most recent occurrence of that month) all
      resolve without a fixed year-then-month order.
- [ ] **Bare `/summary` → button drill-down** — quick row first: This month · Last
      month · This cycle (cycle button only when BUDGET_CYCLE=1); then year buttons
      generated from actual MasterData years (newest first, only years with data);
      tap year → month buttons (only months with data) → report. 90% of calls end on
      the quick row without drilling.
- [ ] **Calendar vs Cycle choice** — with BUDGET_CYCLE=1, first button row is
      📅 Calendar / 💰 Cycle. Cycle path lists ledger labels with date ranges
      ("Aug (23 Jul–24 Aug)") instead of months; a hole in the ledger triggers the
      lazy backfill prompt.
- [ ] **Range support, both forms** — free-form `/summary aug 2025 - jan 2026`
      (reuse the existing /range parsing pattern) and a `Range…` button that walks the
      same year→month picker twice ("From:" then "To:", prompt text shows progress).
      No new UI concepts — the same pickers, used twice.
- [ ] **Year overflow paging** — years beyond ~2 rows of 4 buttons collapse into an
      "Earlier…" page (Telegram inline-keyboard height limits).

## Notes

- Findings about `excel_schema` adoption, atomic saves, phantom-row replay, shared row-writer,
  preview pagination, /save handling, and bulk timeout were already fixed in PR #3
  (commits 4b5fd47 … 8260bd1).
