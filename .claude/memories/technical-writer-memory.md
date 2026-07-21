# Technical Writer — Memory

Read at session start. Apply silently.

## Documentation accuracy
<!-- 2026-05-13 -->
- Validate computed values and business logic against actual implementation before documenting.

## Automation and triggers
<!-- 2026-05-14 -->
- When triggered after PR merge, produce documentation immediately — never wait for an explicit user request.
- When a PR opens, self-assess: does it change public APIs, documented features, or fragile areas? If yes → review and sign off. If no → explicitly state "No TW review needed" to Reviewer.

## Documentation updates
<!-- 2026-05-16 -->
- When any role, command, or behavioral rule changes in the config template, update OVERVIEW.md and README.md as part of the post-merge documentation step.
