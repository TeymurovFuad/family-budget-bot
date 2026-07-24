# Corrections Log

Real-time journal of role corrections. Append-only.
Written by roles mid-session (user feedback or self-reflection).

## Entry format

```
<!-- YYYY-MM-DD HH:MM [ROLE] [USER|SELF] -->
Action:     [what was attempted that was wrong — one sentence]
Correction: [paraphrased summary of what worked — never verbatim user text]
---
```

`[USER]` = user feedback. `[SELF]` = agent self-detected during task.

<!-- 2026-06-29 00:00 [DEVELOPER] [USER] -->
Action:     Split categories into three separate Excel columns (Expense/Income/Savings) with INDIRECT($E2) dropdown.
Correction: User confirmed this broke things and wanted simplicity — one unified category list in col C for all transaction types. INDIRECT approach removed entirely.
---

<!-- 2026-06-29 00:00 [DEVELOPER] [SELF] -->
Action:     Updated column positions in file_storage.py but missed scheduled_report.py which has its own load_currency_rates reading from old cols G:H.
Correction: Any file with its own column-reading logic must be audited when Excel structure changes. Four files must always be updated together: create_blank_excel, migrate_excel.py, load_lists, and scheduled_report.py.
---

<!-- 2026-06-29 00:00 [DEVELOPER] [SELF] -->
Action:     Agents reported "tests pass" without writing new tests for changed behavior.
Correction: Tests passing is not sufficient — every change requires new tests for the changed behavior, not just verification that old tests still pass.
---

<!-- 2026-06-29 00:00 [ORCHESTRATOR] [USER] -->
Action:     Answered a question about Excel dropdown behavior as if the user was asking about the bot.
Correction: When user says "if I select X will it show Y" — clarify whether they mean the bot flow or the Excel file before answering. The context was Excel, not the bot.
---

<!-- 2026-06-29 00:00 [DEVELOPER] [SELF] -->
Action:     Hardcoded rates API URL without follow_redirects — broke on 301 when frankfurter.app moved to frankfurter.dev.
Correction: External API calls must use follow_redirects=True and should prefer the canonical current URL with a fallback. Never assume a URL is stable.
---

<!-- 2026-06-29 00:00 [DEVELOPER] [SELF] -->
Action:     Memory branch creation attempted while claude/work had uncommitted changes, causing stash/merge conflicts.
Correction: Before switching to a memory branch, always commit or stash claude/work changes first. Memory files should be edited on the memory branch directly, not on claude/work then moved.
---

<!-- 2026-07-21 02:30 [REVIEWER] [USER] -->
Action:     Treated all Copilot PR review comments as items that must be fixed.
Correction: Copilot findings are suggestions, not obligations. Evaluate each against design intent and documented tests; if a fix could break functionality or contradicts a deliberate design decision, defer it to backlog with reasoning instead of applying it.
---


<!-- 2026-07-25 ORCHESTRATOR [USER] -->
Action:     Started work on shared `claude/work` branch instead of creating an isolated per-session worktree.
Correction: Each session must create a task-named worktree (`git worktree add ../budget-bot-<task> -b fix/<task> origin/master`) before touching any file. `claude/work` is retired.
---

<!-- 2026-07-25 ORCHESTRATOR [USER] -->
Action:     After code review, reported findings in conversation only — did not add them to BACKLOG.md. User had to ask explicitly.
Correction: After every review, non-blocking findings must be written to BACKLOG.md immediately in the same worktree, then committed, without waiting for the user to ask.
---
