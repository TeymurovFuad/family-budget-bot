#Requires -Version 7.0
<#
.SYNOPSIS
    Deploy Claude config or memory zips produced in Claude sessions.
.EXAMPLE
    .\Deploy-ClaudeUpdate.ps1 -ConfigZip ~/Downloads/claude-code-config.zip
    .\Deploy-ClaudeUpdate.ps1 -MemoryZip ~/Downloads/config-template.zip
    .\Deploy-ClaudeUpdate.ps1 -ConfigZip ~/Downloads/claude-code-config.zip -ProjectPath ~/projects/myapp
    .\Deploy-ClaudeUpdate.ps1 -Status
#>
[CmdletBinding()]
param (
    [string]$ConfigZip,
    [string]$MemoryZip,
    [string]$ProjectPath = (Get-Location).Path,
    [switch]$Status
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$CommandsDir  = Join-Path $HOME ".claude"   "commands"
$MemoryDir    = Join-Path $HOME ".ai-memory" "memories"
$AiMemoryRepo = Join-Path $HOME ".ai-memory"

function Write-Header($text) {
    Write-Host "`n══════════════════════════════════════" -ForegroundColor Cyan
    Write-Host "  $text" -ForegroundColor White
    Write-Host "──────────────────────────────────────" -ForegroundColor Cyan
}

function Deploy-Config {
    param([string]$ZipPath, [string]$Project)

    if (-not (Test-Path $ZipPath)) { throw "Not found: $ZipPath" }

    $tmp = Join-Path $env:TEMP "claude-deploy-$(Get-Random)"
    Expand-Archive -Path $ZipPath -DestinationPath $tmp -Force

    $root = Get-ChildItem $tmp | Select-Object -First 1 -ExpandProperty FullName
    $deployed = @()
    $skipped  = @()

    # Command files
    $cmdSrc = Join-Path $root ".claude" "commands"
    if (Test-Path $cmdSrc) {
        New-Item -ItemType Directory -Force -Path $CommandsDir | Out-Null
        Get-ChildItem "$cmdSrc\*.md" | ForEach-Object {
            Copy-Item $_.FullName (Join-Path $CommandsDir $_.Name) -Force
            $deployed += "~/.claude/commands/$($_.Name)"
        }
    }

    # Memory files (skip existing)
    $memSrc = Join-Path $root ".claude" "memories"
    if (Test-Path $memSrc) {
        New-Item -ItemType Directory -Force -Path $MemoryDir | Out-Null
        Get-ChildItem "$memSrc\*.md" | ForEach-Object {
            $dst = Join-Path $MemoryDir $_.Name
            if (Test-Path $dst) {
                $skipped += "~/.ai-memory/memories/$($_.Name)"
            } else {
                Copy-Item $_.FullName $dst
                $deployed += "~/.ai-memory/memories/$($_.Name)"
            }
        }
    }

    # claude.json
    $jsonSrc = Join-Path $root ".claude" "claude.json"
    if (Test-Path $jsonSrc) {
        $dst = Join-Path $Project ".claude" "claude.json"
        New-Item -ItemType Directory -Force -Path (Split-Path $dst) | Out-Null
        Copy-Item $jsonSrc $dst -Force
        $deployed += $dst
    }

    # CLAUDE.md files
    foreach ($rel in @("CLAUDE.md", "src\CLAUDE.md", "tests\CLAUDE.md")) {
        $src = Join-Path $root $rel
        if (Test-Path $src) {
            $dst = Join-Path $Project $rel
            New-Item -ItemType Directory -Force -Path (Split-Path $dst) | Out-Null
            Copy-Item $src $dst -Force
            $deployed += $dst
        }
    }

    Remove-Item $tmp -Recurse -Force

    Write-Header "CONFIG DEPLOYED"
    $deployed | ForEach-Object { Write-Host "  ✅ $_" -ForegroundColor Green }
    if ($skipped) {
        Write-Host "`nSkipped (already exist):" -ForegroundColor Yellow
        $skipped | ForEach-Object { Write-Host "  – $_" -ForegroundColor Yellow }
    }
    Write-Host "`nNext: reinstall updated .skill files in Claude.ai → Settings → Custom Skills" -ForegroundColor Cyan
}

function Deploy-Memory {
    param([string]$ZipPath)

    if (-not (Test-Path $ZipPath)) { throw "Not found: $ZipPath" }
    if (-not (Test-Path $AiMemoryRepo)) {
        throw "Template not found at ~/.ai-memory — run setup.sh first."
    }

    $tmp = Join-Path $env:TEMP "claude-mem-$(Get-Random)"
    Expand-Archive -Path $ZipPath -DestinationPath $tmp -Force

    $root = Get-ChildItem $tmp | Select-Object -First 1 -ExpandProperty FullName
    $memSrc = Join-Path $root "memories"
    $deployed = @()

    if (Test-Path $memSrc) {
        New-Item -ItemType Directory -Force -Path $MemoryDir | Out-Null
        Get-ChildItem "$memSrc\*.md" | ForEach-Object {
            Copy-Item $_.FullName (Join-Path $MemoryDir $_.Name) -Force
            $deployed += $_.Name
        }
    }

    Remove-Item $tmp -Recurse -Force

    # Commit and push
    Push-Location $AiMemoryRepo
    git add memories/ 2>$null
    $commitResult = git commit -m "mem: deployed $(Get-Date -Format 'yyyy-MM-dd')" --quiet 2>&1
    if ($commitResult -match "nothing to commit") {
        $pushResult = "Nothing new to commit — already up to date."
    } else {
        git push --quiet 2>&1 | Out-Null
        $pushResult = "Pushed to GitHub."
    }
    Pop-Location

    Write-Header "MEMORY DEPLOYED"
    $deployed | ForEach-Object { Write-Host "  ✅ $_" -ForegroundColor Green }
    Write-Host "`n$pushResult" -ForegroundColor Cyan
}

function Show-Status {
    Write-Header "DEPLOYMENT STATUS"

    Write-Host "`nCommands in ~/.claude/commands/:" -ForegroundColor White
    if (Test-Path $CommandsDir) {
        Get-ChildItem "$CommandsDir\*.md" | Sort-Object Name | ForEach-Object {
            Write-Host ("  {0,-35} {1}" -f $_.Name, $_.LastWriteTime.ToString("yyyy-MM-dd HH:mm"))
        }
    } else { Write-Host "  Not found" -ForegroundColor Yellow }

    Write-Host "`nMemory files in ~/.ai-memory/memories/:" -ForegroundColor White
    if (Test-Path $MemoryDir) {
        Get-ChildItem "$MemoryDir\*.md" | Sort-Object Name | ForEach-Object {
            Write-Host ("  {0,-45} {1}" -f $_.Name, $_.LastWriteTime.ToString("yyyy-MM-dd HH:mm"))
        }
    } else { Write-Host "  Not found — run setup-skills-repo.sh" -ForegroundColor Yellow }

    if (Test-Path $AiMemoryRepo) {
        Write-Host "`nLast 5 memory commits:" -ForegroundColor White
        Push-Location $AiMemoryRepo
        git log --oneline -5
        Pop-Location
    }
}

# ── Entry point ────────────────────────────────────────────────────────────
if ($Status) {
    Show-Status
} elseif ($ConfigZip) {
    Deploy-Config -ZipPath (Resolve-Path $ConfigZip) -Project $ProjectPath
} elseif ($MemoryZip) {
    Deploy-Memory -ZipPath (Resolve-Path $MemoryZip)
} else {
    Write-Host "Usage:"
    Write-Host "  Deploy config:  .\Deploy-ClaudeUpdate.ps1 -ConfigZip path/to/claude-code-config.zip"
    Write-Host "  Deploy memory:  .\Deploy-ClaudeUpdate.ps1 -MemoryZip path/to/config-template.zip"
    Write-Host "  Show status:    .\Deploy-ClaudeUpdate.ps1 -Status"
}
