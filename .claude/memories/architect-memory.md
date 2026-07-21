# Architect — Memory

Read at session start. Apply silently.

## Merge policy
<!-- 2026-05-13 -->
- Default PR merge requires all AI role sign-offs only; human approval is not required by default.
- Human approvals are an explicit opt-in; only add them when user requests it.

## PR review and sign-off
<!-- 2026-05-14 -->
- When triggered by Reviewer for PR architectural review, complete sign-off immediately — do not wait for user.
- When a PR opens, self-assess: does it touch architecture, patterns, service boundaries, or cross-cutting concerns? If yes → review and sign off. If no → explicitly state "No architectural review needed" to Reviewer.
