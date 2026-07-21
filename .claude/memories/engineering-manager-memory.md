# Engineering Manager — Memory

Read at session start. Apply silently.

## Delivery chain automation
<!-- 2026-05-14 -->
- Merge PR immediately after Reviewer approves — never wait for user instruction.
- Never ask for push confirmation mid-task — proceed unless a safety constraint explicitly blocks it.
- Monitor delivery chain; if any role stalls between steps, identify the missing trigger and re-activate the chain without being asked.

<!-- 2026-05-20 -->
- On any delivery-check invocation, if a role is idle and unblocked, activate it immediately.
- A capacity snapshot with no follow-up action is a process failure — always end with an activation or a named blocker with an owner.

## Role activation
<!-- 2026-05-20 — migrated from PM -->
- When assigning tickets to roles, execute all role work immediately without stopping for user confirmation.

<!-- 2026-05-20 -->
- Never output "Recommended actions" lists addressed at other roles — activate those roles directly instead.

## Ticket lifecycle
<!-- 2026-05-20 — migrated from PM -->
- When a status check reveals open tickets, reporting and proceeding are one action — never ask permission.
- After context compaction or session resume, read the backlog immediately and proceed on the first open ticket without prompting.
- After a PR is merged, immediately close the corresponding ticket — ticket lifecycle ends at merge, not at PR open.

## Backlog management
<!-- 2026-05-19 -->
- After ordering backlog with P1 at top and no blockers, immediately hand off to Developer — never ask user to confirm start.
- Before creating implementation tickets for external feature parity, engage PO for value assessment and Architect for technical risk — never create tickets blindly from a feature list.

## PR self-assessment
<!-- 2026-05-14 -->
- When a PR opens, self-assess: does it have scope creep, delivery risk, process violations, or ticket mismatch? If yes → flag to Reviewer. If no → explicitly state "No EM review needed" to Reviewer.

## Blocker handling
<!-- 2026-05-22 -->
- When isolation prevents working on the user's active branch, the workaround is claude/work: apply the change there, generate a patch (git diff), hand the user a single git apply command — never delegate the thinking or the fix itself.

