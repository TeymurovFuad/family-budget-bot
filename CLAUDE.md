# budget-bot — AI Configuration

## Orchestrator is always active

Every message routes through the Orchestrator. Do not wait for `/orchestrator` — treat every user message as if it arrived via `/orchestrator`.

Read and apply `.claude/commands/orchestrator.md` before responding to anything.

## Memory bootstrap

Read these files silently before every response:
- `.claude/memories/project-memory.md` — who <YOUR_NAME> is, project overview, Excel structure
- `.claude/memories/writing-style.md` — formatting and language rules
- `.claude/memories/conduct.md` — professional judgment rules
- `.claude/memories/orchestrator-memory.md` — routing and branch rules

## Project config

All AI config lives in `.claude/`. See `.claude/MEMORY.md` for the full index.
