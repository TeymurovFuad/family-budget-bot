# Memory Skill — Memory

Read at session start. Apply silently.

## Single Responsibility Principle — one rule, one file
<!-- 2026-05-27 -->
- Every rule lives in exactly one file — never duplicate across files.
- Before adding an entry: verify the target file owns that category. If the rule belongs elsewhere, route it there instead.
- If a misplaced rule is found during any operation: move it to the correct file in the same PR, note the move.
- File ownership is defined in `conduct.md` under "Single Responsibility Principle — memory files".

## Classification and dedup

<!-- 2026-05-13 -->
- Never store project-specific requirements or business rules in memory files — rules must be general enough to apply across similar work.

<!-- 2026-05-20 -->
- Before writing an entry, check if the same substance is already present in the target file (even in different words). If so, skip — do not duplicate.

## Layer and role sync
<!-- 2026-05-13 -->
- All memory is project-local — no global repo dependency.

<!-- 2026-06-27 -->
- `.claude/agents/` files follow the same isolation as `memories/` — project-local only.

## PR and branch workflow
<!-- 2026-05-13 -->
- Never commit memory changes to an existing branch; always open a dedicated PR.

<!-- 2026-05-21 -->
- Never commit memory entries directly to a feature branch, even if `.claude/` project memory scaffold lives there — always open a dedicated draft PR; warn user if they explicitly request otherwise.
- When `.claude/` project memory scaffold is on an unmerged feature branch, create a draft PR as usual and reference that feature branch/PR in the draft PR body.

## Trigger rules
<!-- 2026-05-21 -->
- Do not treat praise, confirmation, or agreement ("I think this makes sense", "great", "looks good") as a `/memory update` request — only act on explicit instructions.

## Corrections log

<!-- 2026-05-29 -->
- `corrections.md` replaces `## Corrections log` sections in role memory files — remove that section from all role files; corrections go to `corrections.md`, distilled rules go to `## Standing rules`.
- Write corrections to `.claude/corrections.md` in the project repo.
- During `/memory update` (no-args scan) and session-end learning: read `.claude/corrections.md` first, process all unprocessed entries before scanning conversation context.
- All memory rules go to `.claude/memories/{role}-memory.md` — single layer, no routing decision needed.
- Correction entries are processed by distilling into a `## Standing rules` directive in the appropriate role file, then marking the entry `<!-- processed YYYY-MM-DD -->` in `corrections.md`.
- `[USER]` and `[SELF]` tags distinguish the source — process both the same way; the tag is for audit only.

## Entry content rules
<!-- 2026-05-25 -->
- Never include build numbers, issue numbers, or any identifier tied to a transient artifact — they become meaningless when the artifact is deleted.
- After editing memory files, always grep for `#[0-9]+` and similar patterns to verify no transient references remain before committing.
- After completing a memory task, read back the affected files to verify the full result matches the instruction end-to-end before declaring done.

## Deep analysis rules
<!-- 2026-05-20 -->
- Memory files have a `## Product analysis` section for system-state findings — this section is replaced/updated in full on each new deep analysis, never appended.
- Corrections, preferences, and standing rules are append-only; product analysis findings are replace-on-update.
- Never label deep analysis entries with round numbers (e.g. "round 2") — analysis is current state, not history.
