# Claude Code Config Template

A template repository for team AI configuration. Clone once, then copy into each project with `/memory init`.

## How it works

```
~/.ai-memory/          ← template (clone once, update to get latest)
    ↓
/memory init           ← copies everything into your project
    ↓
{project}/.claude/     ← project owns its own config from here on
  memories/            ← role memory files
  agents/              ← specialist agents
  commands/            ← skill commands
  corrections.md       ← corrections log
```

After `/memory init`, the project is self-contained. No ongoing dependency on the template.

## Setup (new machine / new team member)

**Windows:**
```powershell
irm https://raw.githubusercontent.com/YOUR_USERNAME/ai-memory/master/claude-setup.ps1 | iex
```

**Mac / Linux:**
```bash
git clone https://github.com/YOUR_USERNAME/ai-memory.git ~/.ai-memory
```

## Per-project setup

Inside any project repo:
```
/memory init
```

This copies the full config into `.claude/` and commits it. The project team can then use all roles, update memory, and log corrections — entirely within the project repo.

## How to use

Start with `/orchestrator`. Describe what you want to build or change. The Orchestrator routes to the right agent and the full delivery chain runs automatically:

```
Orchestrator → Developer → Tester (pre-PR) → PR Review Fan-out → Merge
→ Technical Writer + DevOps → Tester (post-deploy) → Product Owner
```

For hands-on editing alongside Claude (without the full SDLC flow), use `/buddy` instead.

## Roles

| Command | Role | What it does |
|---|---|---|
| `/orchestrator` | Orchestrator | Routes tasks, runs the full delivery chain |
| `/buddy` | Buddy | Pair-programming on a local branch |
| `/memory init` | Memory | Initialise a new project — copies full config template into `.claude/` |
| `/memory migrate` | Memory | Move an existing `.ai-memory/` project to the `.claude/` layout |
| `/memory merge` | Memory | Pull latest template improvements into an already-initialised project |
| `/memory update` | Memory | Store a rule or scan conversation for findings |
| `/pe` | Prompt Engineer | Rephrases rough input before routing |
| `/permissions` | Permissions | Toggle Claude Code approval prompts |

**Specialist agents** (spawned by Orchestrator, not called directly):
`developer` · `reviewer` · `tester` · `architect` · `devops` · `designer` · `product-owner` · `engineering-manager` · `technical-writer`

## Memory

All memory lives in `.claude/memories/` within the project.

```
{project}/.claude/memories/
  developer-memory.md
  reviewer-memory.md
  tester-memory.md
  ... (one file per role)
```

Update memory with `/memory update [text]` — creates a draft PR in the project repo for review before merging.

Corrections are logged automatically in `.claude/corrections.md` during sessions.

## Keeping the template up to date

```bash
git -C ~/.ai-memory pull
```

- **New project** → `/memory init`
- **Existing project on old `.ai-memory/` layout** → `/memory migrate`
- **Already on `.claude/`** → `/memory merge` — pulls template improvements without overwriting project content
