"""
claude-deployer — local MCP server
Deploys claude-code-config.zip and config-template.zip from Claude sessions.

Transport: stdio (local only)
Install:   pip install fastmcp
Run:       python server.py
"""

from fastmcp import FastMCP
import zipfile, shutil, subprocess, json, os
from pathlib import Path
from datetime import datetime
from typing import Optional

mcp = FastMCP(
    "claude-deployer",
    instructions=(
        "Deploys Claude config and skill updates from zip files produced in Claude sessions. "
        "Use deploy_config for claude-code-config.zip, deploy_memory for config-template.zip, "
        "and deployment_status to see what is currently installed."
    )
)

# ── Paths ──────────────────────────────────────────────────────────────────
HOME           = Path.home()
COMMANDS_DIR   = HOME / ".claude" / "commands"
MEMORY_DIR     = HOME / ".ai-memory" / "memories"
AI_MEMORY_REPO = HOME / ".ai-memory"


# ── Helpers ────────────────────────────────────────────────────────────────

def _git(args: list[str], cwd: Path) -> tuple[int, str]:
    result = subprocess.run(
        ["git"] + args, cwd=str(cwd),
        capture_output=True, text=True
    )
    return result.returncode, (result.stdout + result.stderr).strip()


def _copy_file(src: Path, dst: Path, deployed: list[str]) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    deployed.append(str(dst))


def _ts() -> str:
    return datetime.now().strftime("%Y-%m-%d")


# ── Tools ──────────────────────────────────────────────────────────────────

@mcp.tool(
    annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True}
)
def deploy_config(
    zip_path: str,
    project_path: Optional[str] = None
) -> str:
    """
    Deploy claude-code-config.zip.

    Installs:
    - ~/.claude/commands/*.md             — active slash commands
    - ~/.ai-memory/commands/*.md  — template command files
    - ~/.ai-memory/memories/*.md  — template memory files (skips existing)
    - ~/.ai-memory/templates/             — CLAUDE.md templates (committed + pushed)
    - .claude/claude.json                 — MCP server config (into project or cwd)
    - CLAUDE.md, src/CLAUDE.md, tests/CLAUDE.md — context files (into project or cwd)

    Args:
        zip_path:     Path to claude-code-config.zip
        project_path: Path to your project root. Defaults to current directory.
    """
    zp   = Path(zip_path).expanduser()
    proj = Path(project_path).expanduser() if project_path else Path.cwd()

    if not zp.exists():
        return f"ERROR: {zp} not found."
    if not zipfile.is_zipfile(zp):
        return f"ERROR: {zp} is not a valid zip file."

    deployed: list[str] = []
    skipped:  list[str] = []
    repo_changed = False

    with zipfile.ZipFile(zp) as z:
        names = z.namelist()

    with zipfile.ZipFile(zp) as z:
        for name in names:
            parts = Path(name).parts
            if len(parts) < 2:
                continue
            rel = Path(*parts[1:])

            # Command files → ~/.claude/commands/ (active) AND ~/.ai-memory/commands/ (repo)
            if rel.parts[0:2] == (".claude", "commands") and name.endswith(".md"):
                data = z.read(name)

                # Active location
                dst_active = COMMANDS_DIR / rel.name
                dst_active.parent.mkdir(parents=True, exist_ok=True)
                dst_active.write_bytes(data)
                deployed.append(f"~/.claude/commands/{rel.name}")

                # Repo location
                repo_cmd_dir = AI_MEMORY_REPO / "commands"
                repo_cmd_dir.mkdir(parents=True, exist_ok=True)
                (repo_cmd_dir / rel.name).write_bytes(data)
                repo_changed = True

            # Memory files → ~/.ai-memory/memories/ (skip if exists)
            elif rel.parts[0:2] == (".claude", "memories") and name.endswith(".md"):
                dst = MEMORY_DIR / rel.name
                if dst.exists():
                    skipped.append(f"memories/{rel.name} (exists)")
                else:
                    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
                    dst.write_bytes(z.read(name))
                    deployed.append(f"~/.ai-memory/memories/{rel.name}")
                    repo_changed = True

            # claude.json → project/.claude/claude.json
            elif str(rel) == ".claude/claude.json":
                dst = proj / ".claude" / "claude.json"
                dst.parent.mkdir(parents=True, exist_ok=True)
                dst.write_bytes(z.read(name))
                deployed.append(str(dst))

            # CLAUDE.md files → project AND repo templates/
            elif rel.name == "CLAUDE.md":
                data = z.read(name)

                # Project
                dst = proj / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                dst.write_bytes(data)
                deployed.append(str(dst))

                # Repo templates
                tmpl_dir = AI_MEMORY_REPO / "templates"
                tmpl_dir.mkdir(parents=True, exist_ok=True)
                tmpl_name = "CLAUDE.md" if str(rel) == "CLAUDE.md" else f"{rel.parent.name}.CLAUDE.md"
                (tmpl_dir / tmpl_name).write_bytes(data)
                repo_changed = True

    # Commit and push repo changes
    push_result = ""
    if repo_changed and AI_MEMORY_REPO.exists():
        _git(["add", "commands/", "templates/", "memories/"], AI_MEMORY_REPO)
        code, msg = _git(
            ["commit", "-m", f"chore: deploy config {_ts()}", "--quiet"],
            AI_MEMORY_REPO
        )
        if code == 0:
            push_code, push_msg = _git(["push", "--quiet"], AI_MEMORY_REPO)
            push_result = "Repo updated and pushed to GitHub." if push_code == 0 else f"Push failed: {push_msg}"
        elif "nothing to commit" in msg:
            push_result = "Repo already up to date."

    lines = ["══════════════════════════════════════",
             "🚀 CONFIG DEPLOYED",
             "──────────────────────────────────────"]
    lines += [f"  ✅ {d}" for d in deployed]
    if skipped:
        lines += ["", "Skipped (already exist):"]
        lines += [f"  – {s}" for s in skipped]
    if push_result:
        lines += ["", push_result]
    lines += ["──────────────────────────────────────",
              "Next: reinstall updated .skill files in Claude.ai → Settings → Custom Skills",
              "══════════════════════════════════════"]
    return "\n".join(lines)


@mcp.tool(
    annotations={"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True}
)
def deploy_memory(zip_path: str) -> str:
    """
    Deploy config-template.zip.

    Copies memory files into ~/.ai-memory/memories/ and pushes to GitHub.

    Args:
        zip_path: Path to ai-memory-repo.zip
    """
    zp = Path(zip_path).expanduser()

    if not zp.exists():
        return f"ERROR: {zp} not found."
    if not zipfile.is_zipfile(zp):
        return f"ERROR: {zp} is not a valid zip file."

    if not AI_MEMORY_REPO.exists():
        return (
            "ERROR: ~/.ai-memory does not exist. "
            "Run setup-skills-repo.sh first to clone the ai-memory repo."
        )

    deployed: list[str] = []

    with zipfile.ZipFile(zp) as z:
        for name in z.namelist():
            parts = Path(name).parts
            if len(parts) < 2:
                continue
            rel = Path(*parts[1:])

            if str(rel).startswith("memories/") and name.endswith(".md"):
                dst = AI_MEMORY_REPO / rel
                dst.parent.mkdir(parents=True, exist_ok=True)
                dst.write_bytes(z.read(name))
                deployed.append(rel.name)

    if not deployed:
        return "No memory files found in zip."

    # Commit and push
    _git(["add", "memories/"], AI_MEMORY_REPO)
    code, msg = _git(
        ["commit", "-m", f"mem: deployed {_ts()}", "--quiet"],
        AI_MEMORY_REPO
    )
    if code != 0 and "nothing to commit" in msg:
        push_result = "Nothing new to commit — already up to date."
    else:
        push_code, push_msg = _git(["push", "--quiet"], AI_MEMORY_REPO)
        push_result = "Pushed to GitHub." if push_code == 0 else f"Push failed: {push_msg}"

    lines = ["══════════════════════════════════════",
             "💾 MEMORY DEPLOYED",
             "──────────────────────────────────────"]
    lines += [f"  ✅ {f}" for f in deployed]
    lines += ["", push_result,
              "══════════════════════════════════════"]
    return "\n".join(lines)


@mcp.tool(annotations={"readOnlyHint": True})
def deployment_status() -> str:
    """
    Show what is currently deployed:
    - Installed command files in ~/.claude/commands/
    - Memory files in ~/.ai-memory/memories/
    - Last git commit in ai-memory repo
    """
    lines = ["══════════════════════════════════════",
             "📋 DEPLOYMENT STATUS",
             "──────────────────────────────────────"]

    # Commands
    if COMMANDS_DIR.exists():
        cmds = sorted(COMMANDS_DIR.glob("*.md"))
        lines.append(f"\nCommands ({len(cmds)}) in ~/.claude/commands/:")
        for c in cmds:
            mtime = datetime.fromtimestamp(c.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
            lines.append(f"  {c.name:<30} {mtime}")
    else:
        lines.append("\n~/.claude/commands/ not found")

    # Memory files
    if MEMORY_DIR.exists():
        mems = sorted(MEMORY_DIR.glob("*.md"))
        lines.append(f"\nMemory files ({len(mems)}) in ~/.ai-memory/memories/:")
        for m in mems:
            mtime = datetime.fromtimestamp(m.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
            lines.append(f"  {m.name:<40} {mtime}")
    else:
        lines.append("\n~/.ai-memory/memories/ not found — run setup-skills-repo.sh")

    # Git log
    if AI_MEMORY_REPO.exists():
        _, log = _git(["log", "--oneline", "-5"], AI_MEMORY_REPO)
        lines.append(f"\nLast 5 memory commits:\n{log}")

    lines.append("══════════════════════════════════════")
    return "\n".join(lines)


if __name__ == "__main__":
    mcp.run()
