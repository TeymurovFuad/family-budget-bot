# Backlog

Findings from the whole-team review (Architect, Designer, Developer, PO, fresh-eyes reviewer)
of 2026-07-21 on branch `feat/bulk-import-draft-ordering`. Grouped by planned follow-up PR.
Items marked **[PR #3]** should land in the current bulk-import PR before merge.

## Session handoff — read this first if resuming in a new session

> **Always verify before acting — this note is a snapshot, not live state.**
> Run `gh pr list --repo TeymurovFuad/family-budget-bot --state open` and
> `git log --oneline -5` first; trust those over anything written here.
> Update this section at the end of every session so the next one starts clean.
> *(Last updated: 2026-07-24 — PRs through #32 merged)*

### PR state at last update
- **All PRs #1–#32 merged.** PR #32 shipped:
  - Bug fix: re-upload of a mapped bank statement no longer triggers re-mapping (fingerprint was missing from saved profile JSON); profiles saved before the fix need one re-map to pick up the fingerprint, then work silently forever after
  - Bug fix: `/help` MarkdownV2 fix (was silently failing due to unescaped special chars)
  - Feature: `/cycle detect` — historical backfill scan (`detect_cycle_candidates` + `record_cycle_starts_batch` in `cycles.py`; full inline-button UX in `handlers/cycle.py`); reviewed and blocking bug fixed (duplicate prompt in mixed unambiguous+ambiguous flow)
  - Feature: all 16 commands accept `<cmd> help` subcommand
  - Polish: help text examples changed from PLN to EUR (remaining PLN in runtime messages deferred — see backlog)
  - Docs: README + DOCUMENTATION updated for all of the above
- **Next open work**: `/summary` picker UX PR first (see "Next up"), then
  Cycle Dashboard sheet + sync check. Designs in "budget cycles — agreed design"
  and "/summary picker UX — agreed design" sections below.
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
- **DeepSeek tokens are paid** — budget ~20 live API calls per debug session;
  prefer mocked tests. See `.claude/memories/project-memory.md`.

### Next up (priority order — update when items complete)
  1. **`/summary` picker UX PR** — now HIGHER priority: with `BUDGET_CYCLE=1`
     the calendar view is currently unreachable from bare `/summary` (flag-on
     removes it entirely until the picker ships). Design in "/summary picker
     UX — agreed design" below.
  3. **Cycle Dashboard sheet + sync check** — see "budget cycles — agreed
     design"; must handle ledger rows that may be out of chronological order
     (see PR #30 review notes).
  4. **E2E test coverage PR** — no end-to-end flow tests exist for any command.
     Gap confirmed 2026-07-24. Separate PR after #32 merges. Cover golden path
     + key edge cases for: /add, /bulk (file + text), /edit, /delete, /summary,
     /report, /cycle, /cycle detect, and all help subcommands.
  5. **Cycle-aware `/report` and `/top`** — both are still calendar-scoped when
     `BUDGET_CYCLE=1`; they should use `_current_cycle_bounds()` like `/summary`
     and `/budget` do. Found 2026-07-24. See "cycle-aware report gaps" below.
  6. **Cleanup note**: file_storage.py carries two dead imports
     (`CyclesSchema`, `header_of` usage from the removed #23 cycle helpers)
     left over from the PR #30 consolidation — fold into the next cleanup.
  7. **Smaller items**: code-clarity sweep (300-line hard cap — `file_storage.py`
     and `bulk_conv.py` are known offenders); dedup v2 follow-up findings (5
     items in "dedup review notes (PR #16, 2026-07-23)"); PR #18 review
     backlog items ("bank-statement profiles review notes (PR #18)" below);
     UX group (person attribution — check overlap with dedup v2 grammar
     before implementing); token-economy and infra/performance groups.
  8. **Optional**: rename `Żabka` fixture in `tests/test_merchant_map.py` to
     match the "Old Tbilisi" doc-example rename (PR #14) — tiny, deferred.

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

- [ ] **Quick-add doesn't recognise Savings as transaction type** — user typed
      "2380 added to savings 23 July 2026"; bot replied: ❌ Unknown category
      'Savings'. Use one of: Groceries, Housing, …
      Root cause: the AI parser maps "savings" / "saved" to the Category field
      instead of the Type field. "Savings" is a valid TxnType (Lists sheet B
      column), not a category.
      Expected: parser sets type="Savings", category="" (let user pick or
      default to "Other"); the shared validator should also catch a
      type=Expense / category=Savings mismatch and promote type.
      Workaround: use /add and manually pick Type=Savings step by step.

- [ ] **/add date step rejects natural language ("yesterday")** — user typed
      "Yesterday" in the /add date step; bot replied: ❌ Use YYYY-MM-DD format
      or 'today'. The keyword "today" is accepted but "yesterday", "last
      Monday", etc. are not.
      Expected: at minimum accept "yesterday" as a valid relative-date
      shorthand (maps to `date.today() - timedelta(days=1)`); consider
      "last Monday" etc. as a follow-up stretch goal.
      (`handlers/add_conv.py` date-parsing step)

- [ ] **/cycle detect shows wrong salary candidates for Jul 2024** — bot
      prompted "📅 Jul 2024 — Which income was your salary?" and offered:
        2024-08-01 - 11,871 PLN
        2024-08-01 - 11,856 PLN
      with payday window 2024-07-20 → 2024-08-05.
      Actual Jul 2024 salary: 12,027 PLN on 2024-07-01 — falls BEFORE the
      window start (2024-07-20) and was therefore missed. The two candidates
      shown are the August salaries (2024-08-01), both inside the Jul window
      because the window extends to 2024-08-05; there are two because Aug has
      two salary entries (11,871 + 11,856 PLN).
      Root cause: the payday window for the first detected cycle is anchored
      too late, excluding salaries paid at the very start of the month (day 1).
      Fix: widen the window backward (e.g. anchor at the 1st of the target
      month instead of the 20th) for the first cycle, or let the first-cycle
      search use a broader range.
      (`cycles.py` `detect_cycle_candidates` window logic)

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

- [ ] **`_parse_row_targets` inconsistent OOB feedback** — `keep 1 5` on a 1-row draft silently
      drops the out-of-range `5` rather than reporting it; a lone out-of-range token does error.
      Unified: any target list with at least one valid index silently ignores OOB extras, but
      a list with zero valid indices should error consistently.
      (`handlers/bulk_conv.py` `_parse_row_targets`)
- [ ] **Message wording drifted from BACKLOG acceptance-criteria text** — footer format, skip-message
      phrasing, and row-range compression differ from the spec. PR #16 also retroactively edited
      BACKLOG.md to justify the changes, which is a process smell (spec says this wording is "never
      improvised"). Deliberate re-alignment pass, not urgent.
- [ ] **`_bulk_footer` redundant suggestion for single-flagged-row case** — when exactly one row
      is dup-flagged the footer renders e.g. `keep 3`, `keep 3`, or `keep all flagged` — the first
      example duplicates the second.
      (`handlers/bulk_conv.py` `_bulk_footer`)
- [ ] **`_format_dedup_messages` mass-loose-match-hint denominator is wrong** — it folds
      already-skipped strict-dup counts into `total_new` (the denominator for the "most rows
      loose-matched" ratio), undercounting it in mixed strict+loose batches — exactly the
      bank-reformatted-descriptions scenario the hint exists for. Fix: denominator should be
      rows the strict pass left as new.
      (`handlers/bulk_conv.py` `_format_dedup_messages`)
- [ ] **`bulk_receive` reads the draft file twice** — `pre_merge_len = len(_load_user_draft(uid))`
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
- [x] **Discoverability** — `/bulk`, `/delete`, `/help`, `/setcurrency` absent from menus and /start;
      add 📥 Import + 🗑 Delete buttons; rewrite /start to show the three entry methods;
      register commands with BotFather. *Done: 📥 Import + 🗑 Delete added to MAIN_MENU;
      /start shows the three entry methods; /help lists every command grouped by purpose;
      BotFather registration replaced by `set_my_commands` at startup (bot.py `register_commands`
      post_init hook) — better, no manual BotFather step, guarded by a drift test.*
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

## Follow-up: budget cycles review notes (pre-PR verify, 2026-07-24)

- [ ] **Bare `/cycle` (read-only status) is write-gated** — non-owner allowed users
      cannot view the current cycle; consider `@auth` for the no-arg path and
      `auth_write` only for `started`. (handlers/cycle.py)
- [ ] **Timezone inconsistency** — reports.`_current_cycle_bounds` uses
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
- [ ] **auth_write on CallbackQueryHandler never answers the callback query on
      denial** — a non-owner tapping Yes/No sees a hanging spinner.
      Pre-existing decorator gap, newly exposed. (config.py)
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

- [ ] **Golden-path E2E tests** — one test per major command exercising the real handler
      and asserting the bot reply and Excel mutation. Priority commands: `/add`,
      `/bulk` (file attachment + text paste), `/edit`, `/delete`, `/summary`,
      `/report`, `/cycle`, `/cycle detect`, and at least one `<cmd> help` subcommand.
- [ ] **Edge-case E2E** — `/bulk` with an unrecognised statement format triggers the
      profile flow; re-upload of a mapped statement matches silently; `/cycle detect`
      with a mix of unambiguous and ambiguous months walks the full confirm+pick flow.
- [ ] **Regression guard** — run E2E suite in CI on every PR (currently only unit tests run).

## Follow-up PR: /summary picker UX — agreed design (brainstorm 2026-07-22)

- [ ] **Free-form argument parsing, order-independent** — `/summary aug 2025`,
      `2025 aug`, `08.2025`, bare `aug` (= most recent occurrence of that month) all
      resolve without a fixed year-then-month order.
- [ ] **Bare `/summary` → one message, three zones** — buttons appear ONLY on bare
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
- [ ] **`/summary jul` with cycles enabled** — a bare month name resolves against the
      ledger label first (cycle "Jul"), calendar month only when no such label exists.
- [ ] **Range support, both forms** — free-form `/summary aug 2025 - jan 2026`
      (reuse the existing /range parsing pattern) and a `Range…` button that walks the
      same year→month picker twice ("From:" then "To:", prompt text shows progress).
      No new UI concepts — the same pickers, used twice.
- [ ] **Year overflow paging** — years beyond ~2 rows of 4 buttons collapse into an
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

- [ ] **`awaiting_detect_date` leaks across unrelated messages** — clicking "Custom date"
      sets `ctx.user_data["awaiting_detect_date"]`; if the user ignores the prompt and
      types anything else, `handle_detect_text` (group=2) fires and returns
      "❌ Use YYYY-MM-DD." with no escape path. Fix: add a "Cancel" inline button to the
      custom-date edit message and/or clear `awaiting_detect_date` inside the
      `detect:pick`, `detect:none`, and `detect:confirm_all` callback branches.
      (`handlers/cycle.py`)
- [ ] **`handle_detect_text` has no `@auth_write`** — write path (`async_record_cycle_start`)
      runs without re-checking auth. Low practical risk (flow can only start via `/cycle detect`
      which is auth-gated), but inconsistent with all other write handlers.
      (`handlers/cycle.py:263`)
- [ ] **Empty-fingerprint fallback in bulk_conv is silent** — the `or []` guard on
      `profile["fingerprint"]` is unreachable in the normal path, but if it fires the
      profile saves with an empty fingerprint and will never match on re-upload. Add a
      `log.warning` at that branch. (`handlers/bulk_conv.py` near `bulk_profile_name`)

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

## Notes

- Findings about `excel_schema` adoption, atomic saves, phantom-row replay, shared row-writer,
  preview pagination, /save handling, and bulk timeout were already fixed in PR #3
  (commits 4b5fd47 … 8260bd1).
