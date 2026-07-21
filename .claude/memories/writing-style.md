# Writing Style — Formatting and Language Rules

Applied to every role, every session. Non-negotiable defaults.
Read this file on every activation alongside `conduct.md`.

---

## Sentence construction

- Write short declarative sentences. One idea per sentence.
- Verb-first for directives: "Use X." "Never Y." "Always Z." — not "It is important to..."
- Present tense throughout: "Tester reads docs" not "The Tester will read..."
- Active voice only: "Developer implements" not "Implementation is performed by..."
- No hedging: never "might", "could consider", "it may be worth noting", "perhaps"
- No padding: if a word does not add meaning, remove it

## Emphasis

- **Bold** for non-negotiables only — not for decoration
- Never italicise for style — only for names of files, paths, or defined terms
- Never underline
- Emoji only in role header lines: 🤖 💻 🧪 🎨 🏛️ 🚀 ✍️ 📋 🔍 ❓ — nowhere else

## Structure

- Tables for any comparison, mapping, or multi-attribute list
- Numbered steps for sequences where order matters
- `[ ]` checkboxes for checklists
- `---` horizontal rules between major sections — not `===` or `***`
- `══════` delimiters for handoff blocks only
- Never nest bullet points more than one level deep

## Code

- Real, runnable examples — never pseudocode unless explicitly illustrating a concept
- No inline comments explaining what the code does — rename instead
- No XML doc comments (`///`) in examples
- C# naming: PascalCase methods, _camelCase private fields, `I` prefix interfaces
- PowerShell: verb-noun cmdlet style, `Set-StrictMode -Version Latest`, `$ErrorActionPreference = 'Stop'`
- Conventional commits in all git examples: 2–5 words, `feat:` `fix:` `refactor:` `test:` `chore:` `mem:` prefixes

## Language choices

- "must" not "should" for requirements
- "never" not "avoid" for prohibitions
- "always" not "remember to" for invariants
- "ask" not "clarify with" or "confirm with"
- "role" not "persona" or "agent"
- "handoff" not "hand-off" or "hand off"
- "skill" not "capability" or "module"

## Things that never appear

- Passive constructions: "it was decided", "changes were made", "errors were found"
- Rhetorical questions in technical content

## Handoff blocks

Use this exact format — no variation:
```
══════════════════════════════════════════
[EMOJI] [ROLE] — HANDOFF TO [NEXT ROLE]
──────────────────────────────────────────
[content]
──────────────────────────────────────────
📤 HANDOFF TO: [Role]  STATUS: [PASS/FAIL/IN PROGRESS]
══════════════════════════════════════════
```

## Queries and tasks (inter-role communication)

```
❓ QUERY TO: [Role]  FROM: [Role]  RE: [topic]
[One specific question]
Context: [Why needed]  Blocking: Yes/No
```

```
📋 TASK FOR: [Role]  FROM: [Role]  PRIORITY: P1/P2/P3
EXPECTED: [spec]
FOUND:    [reality]
ACTION:   [what to do]
DONE WHEN: [criterion]
```
