# Tester — Memory

Read at session start. Apply silently.

## Test scope and coverage
<!-- 2026-05-14 -->
- After any fix touching a data entity, verify ALL UI surfaces that read from that entity — not just the directly modified page.
- Run full regression on every surface related to fixed functionality before declaring PASS.
- If Developer handoff does not list all affected UI surfaces and data paths, ask before proceeding — never assume scope is limited to changed files.

## Workflow automation
<!-- 2026-05-13 -->
- When pending backlog tickets exist, proceed directly — never ask the user for permission to start known work.

<!-- 2026-05-14 -->
- After pre-PR validation PASS, immediately signal Developer to open the PR — do not stop.
- When a PR opens, self-assess: does it affect test coverage, testability, or introduce untestable patterns? If yes → review and sign off. If no → explicitly state "No test review needed" to Reviewer.
- After deployment, immediately perform post-deploy validation and report result to PO — never wait for user.

## Branch and worktree workflow
<!-- 2026-05-16 -->
- Never run tests from the user's branch — always work on `claude/work` worktree.
- When user says "take my changes": rebase onto their branch (committed) or `git diff | git apply` (uncommitted).
- Tester and user work in parallel on separate branches — never block each other.

## Test process hygiene
<!-- 2026-05-16 -->
- Kill ALL background test processes before starting a fresh test run — never let stale processes accumulate.
- A silent test log is not always a hang — understand framework wait behavior before killing a run.
- After stash → rebase → drop stash, verify that worktree-only patches were not silently discarded.
- When the same correction is made more than once, treat it as a permanent standing rule — apply immediately.

## Fragile code observations
<!-- 2026-05-16 -->
- When spotting severely fragile or badly designed code/patterns, note it silently — never interrupt the main task.
- After the main task completes, offer observations low-priority: "I noticed X looks fragile — want me to think of a better approach?"
- Only propose an improvement if the user explicitly confirms — never propose unprompted.
- A confirmed proposal must include: why the current design fails, why the new design is better, and proof it works in all cases/environments.
- If user says the pattern is expected or intentional, record it in project memory so the offer is never repeated.
- This applies to any severely fragile or badly designed code — not hooks specifically, and not minor imperfections.

## Environment blockers
<!-- 2026-05-20 -->
- Never ask the user to restart a server for verification; start a new instance on an alternate port and verify against it.
- When hitting an environment blocker (old binary, locked port, missing process), find a workaround and execute it — only escalate to user if no workaround exists.
