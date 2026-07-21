# Tester context — tests/

Default role in this directory: **Tester**
Preferred model: `claude-sonnet-4-6`

When reviewing or writing anything in this directory, apply the Tester role rules.
Any test file opened or modified triggers the verification checklist automatically.

## Screenshot rules (Playwright MCP debugging)
When using Playwright MCP to debug a failing test or inspect the running app:
- **Use `browser_snapshot` first** — returns the accessibility tree as text, no image, no dimension risk
- **Only take a `browser_screenshot` if you cannot diagnose from the snapshot**
- **Discard immediately after use** — run `/compact` right after analysing a screenshot to remove it from context
- **Never `fullPage: true`** — viewport only (already capped at 1280×800 by `claude.json`)

```
// Preferred for debugging
"Snapshot the current page and identify the failing element"
"Get an accessibility snapshot of localhost:5000/[route]"

// Only if snapshot is not enough
"Take a viewport screenshot of localhost:5000/[route] — not full page"
```

## Test quality rules (enforced here)
- AAA pattern — every test has Arrange / Act / Assert
- No logic in tests — no if/else, no loops, no try/catch
- One concept per test
- Names follow `Method_Scenario_Expected`
- Async tests use `await`, never `.Result`
- No `Thread.Sleep` — use async waits
- Unit tests use `Fake[Provider]` from `Tests/Fakes/`, never real vendor SDK
- No vendor types in test arrange/act — only your interfaces

## Fake provider location
All test fakes live in `tests/Fakes/`. One fake per provider interface:
```
tests/Fakes/
├── FakeEmailService.cs      : IEmailService
├── FakeFileStorage.cs       : IFileStorage
├── FakeAppLogger.cs         : IAppLogger<T>
└── FakeCacheService.cs      : ICacheService
```
