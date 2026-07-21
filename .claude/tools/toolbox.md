# Toolbox

Single source of truth for all tools available to roles.

**Before using any MCP:** run `/mcp` in Claude Code to confirm it is connected.
If an MCP is not connected, use the listed fallback.

**Fallback chain (apply everywhere):**
1. MCP not connected → use CLI equivalent listed below
2. CLI not installed → use REST API via WebFetch with a Bearer token
3. REST API unavailable → stop, raise a named blocker with owner and ETA
4. Never guess or fabricate API responses

---

## Tier 1 — Always available (Claude Code built-ins)

Every role has these. No installation required.

| Tool | What it does | How to invoke |
|---|---|---|
| **Bash** | Terminal commands, scripts, CLI tools | Bash tool |
| **Read / Write / Edit** | File system operations | File tools |
| **Glob / Grep** | File search and content search | Search tools |
| **WebSearch** | General web search | WebSearch tool |
| **WebFetch** | Fetch a specific URL | WebFetch tool |
| **Git CLI** | Branch, commit, push, pull, log | `git` via Bash |

---

## Tier 2 — Standard MCPs (install once, always connected)

Install these on every machine. If not connected, use the fallback.

### GitHub MCP
**Purpose:** Issues, PRs, comments, reviews, labels, releases
**Fallback:** `gh` CLI via Bash — covers 95% of operations
**Install:** Claude Code MCP settings → add GitHub MCP server
**Key operations:**
- Issues: `create_issue`, `get_issue`, `update_issue`, `close_issue`, `add_issue_comment`
- PRs: `create_pull_request`, `get_pull_request`, `merge_pull_request`, `list_pull_requests`
- Reviews: `create_review`, `list_review_comments`, `get_review`
- Labels: `add_labels_to_issue`, `remove_labels_from_issue`

**gh CLI fallbacks:**
```bash
gh issue create --title "..." --body "..."
gh issue close 42 --comment "..."
gh pr create --title "..." --body "..." --base main
gh pr merge 42 --squash
gh pr review 42 --approve
gh api repos/{owner}/{repo}/pulls/{n}/reviews/{id}/comments
```

### Playwright MCP
**Purpose:** Browser automation, E2E testing, UI debugging, competitor research
**Fallback:** Claude in Chrome MCP (live tab), or WebFetch for static pages
**Install:** Claude Code MCP settings → add Playwright MCP server
**Screenshot rule:** Always prefer `browser_snapshot` (accessibility tree, no image) over `browser_screenshot`. Never `fullPage: true`. Viewport capped at 1280×800. Discard screenshots after analysis — run `/compact`.
**Key operations:** `browser_navigate`, `browser_snapshot`, `browser_screenshot`, `browser_click`, `browser_fill`, `browser_evaluate`

### Claude in Chrome MCP
**Purpose:** Live browser inspection on an already-open tab — no browser launch needed
**Fallback:** Playwright MCP
**Install:** Claude in Chrome browser extension
**Key operations:** `find`, `read_page`, `javascript_tool`, `navigate`, `computer`, `tabs_context_mcp`

### Figma MCP
**Purpose:** Read Figma designs, extract component specs, get design tokens
**Fallback:** Figma REST API via WebFetch
```
GET https://api.figma.com/v1/files/{file_key}
Authorization: Bearer {FIGMA_TOKEN}
```
**Install:** Claude Code MCP settings → add Figma MCP server

---

## Tier 3 — On-demand MCPs (configure per project)

Not used by default. When a project needs one:
1. Configure the MCP connection in Claude Code project settings
2. Add setup notes to project CLAUDE.md
3. Store any project-specific config in project memory via `/memory update project`

### Azure DevOps MCP
**Purpose:** Work items, pipelines, repos, test plans, sprints
**Fallback:** `az devops` CLI via Bash, or direct REST API via WebFetch
```
GET https://dev.azure.com/{org}/{project}/_apis/wit/workitems/{id}?api-version=7.1
Authorization: Basic {base64(:{PAT})}
```
**Configure:** Add ADO PAT to environment; connect MCP in Claude Code project settings

### AWS MCP
**Purpose:** AWS resource management, CloudWatch logs, S3, Lambda, EC2, ECS
**Fallback:** `aws` CLI via Bash
**Configure:** Set `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION` in project env or `.env` file

### Terraform MCP
**Purpose:** Terraform registry lookup, module discovery, provider documentation
**Fallback:** `terraform` CLI via Bash + WebFetch to `registry.terraform.io`
**Configure:** Set `TF_TOKEN_app_terraform_io` if using Terraform Cloud

### Rovo MCP (Atlassian)
**Purpose:** Jira issues, Confluence pages, Compass service catalog — search, create, update via natural language
**Transport:** HTTP — cloud-hosted, no local binary needed
**Fallback:** Atlassian REST API via WebFetch
```
GET https://{domain}.atlassian.net/rest/api/3/issue/{issueKey}
Authorization: Basic {base64(email:api_token)}
```
**Install (one-time, run in terminal):**
```bash
claude mcp add --transport http rovo https://mcp.atlassian.com/v1/mcp
```
Then authenticate: run `/mcp` in Claude Code and complete the OAuth browser flow.

**⚙️ Auto-detect — every role must run this before any Rovo operation:**
```bash
claude mcp list 2>/dev/null | grep -i rovo
```
- Found → proceed normally
- Not found → stop immediately and show the user:
  > "Rovo MCP is not connected. To install, run in your terminal:
  > `claude mcp add --transport http rovo https://mcp.atlassian.com/v1/mcp`
  > Then open a new Claude Code session and authenticate via `/mcp`.
  > Come back when done."
  Do not attempt any Atlassian operations until the user confirms it's connected.

---

## Tier 4 — CLI tools (installed separately, invoked via Bash)

| Tool | Purpose | Install (Windows) | Install (Mac/Linux) | Fallback |
|---|---|---|---|---|
| `gh` | GitHub CLI — issues, PRs, releases | `winget install GitHub.cli` | `brew install gh` | GitHub MCP or REST API |
| `k6` | Performance / load testing | `winget install k6` | `brew install k6` | Playwright timing APIs |
| `axe-core` | Accessibility testing | `npm install axe-playwright` | `npm install axe-playwright` | Manual WCAG 2.1 AA checklist |
| `docker` | Container build and run | Docker Desktop | Docker Desktop | n/a |
| `az` | Azure CLI — subscriptions, resources | `winget install Microsoft.AzureCLI` | `brew install azure-cli` | Azure DevOps MCP or REST API |
| `aws` | AWS CLI — all AWS services | `winget install Amazon.AWSCLI` | `brew install awscli` | AWS MCP or REST API |
| `terraform` | Terraform plan/apply/state | `winget install Hashicorp.Terraform` | `brew install terraform` | Terraform MCP |

---

## Role permission matrix

Quick reference — see each role's `## Tool permissions` section for details.

| Tool | Orchestrator | Developer | Tester | Architect | Designer | DevOps | TW | Reviewer | EM | PO | Buddy | Memory |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Bash + Git | ✅ | ✅ | ✅ | read | ✅ | ✅ | read | read | ✅ | read | ✅ local | ✅ |
| File system | read | ✅ | ✅ | read | read | ✅ | ✅ | read | read | read | ✅ | ✅ |
| WebSearch + WebFetch | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | — |
| GitHub MCP / gh CLI | read | write | write | read | — | write | read | write | write | write | ❌ | write |
| Playwright MCP | — | debug | ✅ | — | research | — | — | — | — | — | — | — |
| Chrome MCP | — | debug | ✅ | — | research | — | — | — | — | — | — | — |
| Figma MCP | — | — | — | — | ✅ | — | — | — | — | — | — | — |
| k6 (Bash) | — | — | ✅ | — | — | ✅ | — | — | — | — | — | — |
| axe-core (Playwright) | — | — | ✅ | — | — | — | — | — | — | — | — | — |
| Azure DevOps MCP | — | on-demand | on-demand | — | — | on-demand | — | — | on-demand | on-demand | — | — |
| AWS MCP | — | — | — | — | — | on-demand | — | — | — | — | — | — |
| Terraform MCP | — | — | — | on-demand | — | on-demand | — | — | — | — | — | — |
| Rovo MCP | on-demand | on-demand | — | — | — | — | on-demand | — | on-demand | on-demand | — | — |
