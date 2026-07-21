# Developer context — src/

Default role in this directory: **Developer**
Preferred model: `claude-opus-4-7`

When writing any code here, apply the Developer role rules from the root CLAUDE.md
without being asked. After completing any implementation, produce a Developer → Tester
handoff block automatically.

## Screenshot rules (Playwright MCP debugging)
When using Playwright MCP to inspect the running app while debugging:
- **Use `browser_snapshot` first** — returns page structure as text, no image, no dimension risk
- **Only take a screenshot if the snapshot is insufficient**
- **Discard immediately after use** — run `/compact` right after analysing to remove it from context
- **Never `fullPage: true`** — viewport only (capped at 1280×800 by `claude.json`)

## Structure reminder
- `Domain/` — no external dependencies, no Infrastructure references
- `Application/Abstractions/` — every external provider interface lives here
- `Infrastructure/` — all vendor SDKs, adapters, EF Core DbContext
- `Api/` — the only layer that registers concrete types in DI
