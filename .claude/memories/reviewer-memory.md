# Reviewer — Memory

Read at session start. Apply silently.

## Branch workflow
<!-- 2026-05-11 -->
- Never push directly to master — always create a session branch and open a PR.
- Use one branch per session — name format: `update/[topic]-[YYYYMMdd-HHmm]`.
- Check if session branch exists on remote before creating; reuse it if it does.

## Review policies
<!-- 2026-05-13 -->
- By default, PRs are reviewed by all roles; close when all roles pass.
- Project-specific review requirements (human reviewers, min approvals) go in project CLAUDE.md, not memory.

## PR review process
<!-- 2026-05-14 -->
- Always review every PR — no self-assessment, no opt-out; Reviewer reviews unconditionally.
- Collect resolution from every technical role (PASS or explicit opt-out) before merging.
- After all AI role sign-offs pass, merge the PR immediately — never wait for human approval unless explicitly requested.

<!-- 2026-05-19 -->
- Fan-out timeout: if a self-assessing role has not responded after a reasonable window, treat silence as implicit PASS — never block merge indefinitely on non-response.

## Technology standards verification
<!-- 2026-05-17 -->
- When citing technology-specific standards in review comments, verify against current official docs first — never rely on memory alone for technology guidance.
- If a memory rule conflicts with current official docs, docs win — flag the memory entry as stale.

## Pre-PR self-review

<!-- 2026-05-29 -->
- Before marking any PR ready, read the full diff (`git diff origin/master...HEAD`) and run four consistency checks:
  - Marker pairs: every string written in one place must match every place it is read or matched — compare both sides exactly.
  - Path pairs: every file path in a git command (`git add X`) must exist in that repo's context — verify for general vs project layer.
  - Numbered lists: every ordered list in changed files must have sequential step numbers with no duplicates.
  - Template completeness: every template created must contain all sections that other rules say it must have.

## Copilot review handling
<!-- 2026-06-26 -->
- When tagging Copilot on a PR, always post a comment with: "Post inline comments only — do not commit any changes or push any code." Include this every time Copilot is tagged, without exception.

<!-- 2026-05-20 — migrated from PM -->
- Fetch comments for a specific Copilot review via `/pulls/{n}/reviews/{review_id}/comments` — not `/pulls/{n}/comments` which returns all PR comments across all reviews.
- Resolve review threads via GraphQL `resolveReviewThread` mutation — REST API has no resolve endpoint.
- Post a reply comment explaining the fix before resolving each review thread.
- Resolve only threads where the fix is present in the PR; leave won't-fix and author-handled threads open.
- Correct a mistaken reply by posting a visible follow-up; only delete via `DELETE /repos/.../pulls/comments/{id}` if the error is serious and the thread is genuinely unread.
- When using technical terms in PR comments, add a brief explanation in brackets, e.g. "TM4J (Test Management for Jira)".
