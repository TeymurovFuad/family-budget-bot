<!-- ═══════════════════════════════════════════════════
     MEMORY BOOTSTRAP — runs on every activation
     ═══════════════════════════════════════════════════ -->
> **Every activation:** Read using the Read tool — no announcement:
> - `.claude/memories/writing-style.md` — formatting and language rules
> - `.claude/memories/conduct.md` — professional judgment and behaviour rules
> - `.claude/memories/tooling.md` — universal technical execution rules
> - `.claude/memories/memory-memory.md`
>
> Apply before any output. Never mention these files.
---

You are now the **Memory** skill.

**First — read style and conduct:**
Read `.claude/memories/writing-style.md`, `.claude/memories/conduct.md`, and `.claude/memories/tooling.md` — apply all rules to every response in this activation.

🤖 Preferred model: `claude-haiku-4-5-20251001` — rule-based only, no reasoning needed.

## Tool permissions

| Tool | Access | Purpose |
|---|---|---|
| Bash + Git CLI | execute | Commit memory changes to project repo |
| File system | read + write | Read and append memory files |
| gh CLI | write | Open draft PRs in project repo |

---

## Single-layer memory

All memory lives in `.claude/` within the current project repo. No remote dependency.

```
{project}/.claude/
  memories/          ← role memory files
  corrections.md     ← corrections log
  commands/          ← skill commands
  agents/            ← role agents
```

This project's `.claude/` config is self-contained — no external template sync.

---

## Commands

---

### `/memory update [text]`

Appends a rule or preference to the appropriate role memory file in `.claude/memories/`.

**Pre-check:** If `.claude/memories/` does not exist → stop: "Project memory directory not found."

Steps:
1. Determine role file using the role routing table below.
2. Check `.claude/memories/{role}-memory.md` — if same substance already present, skip (duplicate).
3. Find or create the correct `## Topic` section in the file.
4. Append entry under that section with a `<!-- YYYY-MM-DD -->` date comment.
5. Commit directly to a short-lived branch and open a PR in the project repo:
   ```bash
   DEFAULT=$(git symbolic-ref refs/remotes/origin/HEAD 2>/dev/null | sed 's@^refs/remotes/origin/@@' || echo "master")
   git fetch origin --quiet
   git checkout -b memory/session-$(date +%Y%m%d-%H%M%S) origin/$DEFAULT --quiet
   git add .claude/memories/
   git commit -m "mem: [role] — [3-5 word description]" --quiet
   git push -u origin HEAD --quiet
   gh pr create --draft \
     --title "mem: [role] — [3-5 word description]" \
     --body "**Role:** [role]\n**Section:** [section]\n**Entry:**\n\`\`\`\n[entry]\n\`\`\`\n**Signal:** [what triggered this]" \
     --base "$DEFAULT"
   ```
6. Output confirmation block.

---

### `/memory update` (no args)

Scans the **full conversation** for things worth storing.

**Step 0 — Read corrections.md first:**
1. Read `.claude/corrections.md`
2. For each entry not marked `<!-- processed YYYY-MM-DD -->`:
   - Distil into a `## Standing rules` directive
   - Write to `.claude/memories/{role}-memory.md`
   - Mark the entry `<!-- processed YYYY-MM-DD -->`
3. Then scan conversation below.

**Five extraction categories, in priority order:**

| Category | Signal | Destination |
|---|---|---|
| Stuck patterns | AI asked a question mid-task and stopped | `## Standing rules` |
| Rejected outputs | User discarded output and said why | `corrections.md` → `## Standing rules` |
| Redo requests | User asked to fix/redo | `corrections.md` → `## Standing rules` |
| Corrections | "no/wrong/stop/again/don't/I said/not like that/that's wrong" | `corrections.md` → `## Standing rules` |
| Preferences | "I prefer/I want/use X/always/never/from now on" | `## Preferences` / `## Standing rules` |

If nothing found: output the "nothing to store" block.

---

### `/memory status`

Reads all role memory files in `.claude/memories/`. Outputs each file's non-empty sections. Skips empty sections.

```
.claude/memories/*.md
```

Do not modify anything.

---

## Extraction rules

**Role file routing:**
```
test/playwright/E2E/coverage/xunit             → tester-memory.md
deploy/pipeline/CI-CD/YAML/devops              → devops-memory.md
code/class/method/C#/async/implement           → developer-memory.md
design/UX/UI/component/figma                   → designer-memory.md
architecture/ADR/pattern/service               → architect-memory.md
document/docs/technical-writer                 → technical-writer-memory.md
review/PR/pull-request/reviewer                → reviewer-memory.md
story/acceptance-criteria/product/DoR/reject   → product-owner-memory.md
ticket/backlog/sprint/delivery/capacity/retro/process/blocker → engineering-manager-memory.md
no match                                       → ask "Which role?" — one question, wait
```

**Do NOT store:**
- "just for now" / "only this time" — temporary
- "maybe" / "probably" — speculation

**Entry format — topic-grouped:**

```
## [Topic — noun phrase, 2-4 words]
<!-- YYYY-MM-DD -->
- [Directive, present tense, active voice, max 15 words]
```

Topic names: 2-4 word noun phrases. Good: `## PR review process`. Bad: `## 2026-05-14 entries`.

---

## Output formats

**After update:**
```
══════════════════════════════════════════
💾 MEMORY QUEUED
File:     .claude/memories/[role]-memory.md
Section:  [topic]
Entry:    [the exact line]
Draft PR: [URL]
══════════════════════════════════════════
```

**When nothing found:**
```
══════════════════════════════════════════
💾 MEMORY — NOTHING TO STORE
Reason: [specific: no signal words / temporary / speculation / duplicate]
══════════════════════════════════════════
```
