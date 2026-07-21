#Requires -Version 7.0
<#
.SYNOPSIS
    One-command Claude Code setup for new team members.
    Clones the config template and installs the deployer dependency.

.EXAMPLE
    # Option A — run directly from GitHub (no clone needed first)
    irm https://raw.githubusercontent.com/YOUR_USERNAME/ai-memory/master/claude-setup.ps1 | iex

    # Option B — run from a local clone
    powershell -ExecutionPolicy Bypass -File .\claude-setup.ps1
#>

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$RepoUrl      = "https://github.com/YOUR_USERNAME/ai-memory.git"
$TemplatePath = Join-Path $env:USERPROFILE ".ai-memory"

function Write-Step($msg) { Write-Host "`n  → $msg" -ForegroundColor Cyan }
function Write-Ok($msg)   { Write-Host "    ✅ $msg" -ForegroundColor Green }
function Write-Warn($msg) { Write-Host "    ⚠️  $msg" -ForegroundColor Yellow }
function Write-Info($msg) { Write-Host "    $msg" }

Write-Host "`n══════════════════════════════════════" -ForegroundColor Cyan
Write-Host "  Claude Code — Team Setup" -ForegroundColor White
Write-Host "══════════════════════════════════════" -ForegroundColor Cyan

# ── 1. Clone or update the config template ────────────────────────────────
Write-Step "Config template"

if (Test-Path (Join-Path $TemplatePath ".git")) {
    Write-Info "Already cloned — pulling latest"
    git -C $TemplatePath pull --quiet
    Write-Ok "Up to date at $TemplatePath"
} else {
    if (Test-Path $TemplatePath) {
        Write-Warn "$TemplatePath exists but is not a git repo — removing and re-cloning"
        Remove-Item $TemplatePath -Recurse -Force
    }
    git clone $RepoUrl $TemplatePath --quiet
    Write-Ok "Cloned to $TemplatePath"
}

# ── 2. Deployer dependency ─────────────────────────────────────────────────
Write-Step "Deployer (fastmcp)"

$deployer = Join-Path $TemplatePath "deployer" "server.py"
if (Test-Path $deployer) {
    try {
        pip install fastmcp --quiet --break-system-packages 2>$null
        Write-Ok "fastmcp installed"
        Write-Info "Deployer path: $deployer"
        Write-Info "Add to .claude/claude.json:"
        Write-Info '  "claude-deployer": { "type": "stdio", "command": "python", "args": ["' + $deployer + '"] }'
    } catch {
        Write-Warn "pip install failed — install manually: pip install fastmcp"
    }
} else {
    Write-Warn "deployer/server.py not found — skipping"
}

# ── 3. Per-project setup ───────────────────────────────────────────────────
Write-Step "Per-project setup"
Write-Info "For each new project, run this inside the project repo:"
Write-Info ""
Write-Info "  /memory init"
Write-Info ""
Write-Info "This copies all config (commands, agents, memories) into .claude/"
Write-Info "The project then owns its config — no ongoing dependency on the template."

# ── 4. Done ───────────────────────────────────────────────────────────────
Write-Host "`n══════════════════════════════════════" -ForegroundColor Cyan
Write-Host "  Setup complete. Open Claude Code: claude" -ForegroundColor Green
Write-Host "══════════════════════════════════════`n" -ForegroundColor Cyan
