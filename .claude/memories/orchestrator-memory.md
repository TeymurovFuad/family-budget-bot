# Orchestrator — Memory

Read at session start. Apply silently.

## Role activation and flow
<!-- 2026-05-12 -->
- After each role handoff, execute the next role's work immediately — never pause for user confirmation between roles.
- Completion criteria are defined at the start of the task — apply them automatically; never ask for reconfirmation mid-chain.
- "Are we done?" means check the full completion criteria and continue if anything remains — not pause for clarification.

<!-- 2026-05-13 -->
- When the user identifies pending work, route to the implementing role immediately — never ask "do you want me to start this?"

<!-- 2026-05-14 -->
- After session compaction and resume, immediately scan backlog for open tickets and route to implementing role — no user prompt needed.
- PR chain is fully automated: open PR → trigger /reviewer → merge is one uninterrupted sequence; never stop at any step.

## claude/work branch management
<!-- 2026-05-19 -->
- All roles that touch files MUST work on claude/work, never on the user's branch directly.
- Before syncing claude/work to user's branch: stash any uncommitted changes with a meaningful message.
- Before git reset --hard on claude/work: save committed changes to a claude/save/<topic>-YYYYMMDD branch first.
- Never hard-reset claude/work without stashing/saving — stashes and save branches are the safety net.
- If claude/work cannot sync cleanly (rebase conflict in unrelated files): stop and report to user — never edit user's branch as a workaround.
- claude/work is one branch per repo shared across sessions; stash context carries the per-topic history.
- When a topic is confirmed closed by the user: drop its stash and delete its save branch.

<!-- 2026-05-22 -->
- AI work and user work must never interfere — AI roles must use isolated worktrees or claude/work, never checkout/stash/modify the user's active checkout.
- Violating this is a hard stop: stop all work, undo any branch switches or stashes, report what happened.

## Memory management
<!-- 2026-05-14 -->
- Never commit `.claude/memories/` changes to feature or working branches — memory updates follow dedicated `memory/session-*` branch → draft PR → merge flow only.

<!-- 2026-05-20 -->
- After any deep org/repo analysis completes: immediately run /memory update project with each role's findings — auto-learning does not capture domain knowledge, only behavioral corrections.
- Domain knowledge from analysis (product features, stack, appliance types, coverage gaps) must be explicitly pushed to project memory — it will never be captured by the session-end auto-scan.

## Branch strategy
<!-- 2026-05-26 -->
- When creating a branch for new work: check for open unmerged PRs first. If one exists, base the new branch on that PR's branch — not on master — to avoid conflicts.
- If multiple dependent changes need separate PRs: create a chain (PR B targets PR A's branch as base) so each can be reviewed and merged in order.
- Create a separate PR for every logically distinct change. Never add unrelated improvements to an existing open PR.
- Before deleting any branch, run `git worktree list` and remove associated worktrees first.

## Blocker handling
<!-- 2026-05-20 -->
- When any role hits an environment blocker, instruct it to find a workaround first — never let it surface the blocker as a user task.
- Reporting a state without acting on it is not acceptable output — every role invocation must end with either completed work or a named, owned, time-boxed blocker.
