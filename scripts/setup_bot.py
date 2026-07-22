"""
setup_bot.py — one-shot interactive bootstrap for a fresh budget-bot fork.

Runs with the Python standard library only (no third-party imports), so it
works on a bare clone BEFORE any requirements are installed. It then creates
the virtualenv, installs requirements into it, and walks you through the
missing configuration.

Usage:
  Linux / macOS:   ./setup.sh          (thin wrapper at the repo root)
  Windows:         python scripts\\setup_bot.py

Safe to re-run at any time — it acts as a config doctor: values already set
in .env are kept (and never echoed back in full), only the gaps are prompted
for. Steps already done (venv, requirements, data dir) are skipped.
"""

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENV_DIR = ROOT / ".venv"
ENV_PATH = ROOT / ".env"
ENV_EXAMPLE_PATH = ROOT / ".env.example"
DATA_DIR = ROOT / "data"
TEMPLATE_PATH = DATA_DIR / "Expenses_Template.xlsx"

MIN_PYTHON = (3, 12)

IS_WINDOWS = platform.system() == "Windows"


# ── Pure helpers (unit-tested in tests/test_setup_bot.py) ─────────────────────

def parse_env_file(text: str) -> dict[str, str]:
    """Parse KEY=VALUE lines from .env content. Ignores comments and blanks.

    Values keep everything after the first '=' with surrounding whitespace and
    matching single/double quotes stripped — mirroring what python-dotenv does
    for the simple values this project uses.
    """
    result: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if not key:
            continue
        value = value.strip()
        # strip inline comments only when the value is unquoted
        if value and value[0] in "\"'" and len(value) >= 2 and value[-1] == value[0]:
            value = value[1:-1]
        elif " #" in value:
            value = value.split(" #", 1)[0].strip()
        result[key] = value
    return result


def merge_env(existing: dict[str, str], new_values: dict[str, str]) -> dict[str, str]:
    """Merge freshly collected values into existing ones.

    Existing real values always win — re-running setup never clobbers what
    the user already configured. New keys, empty values and .env.example
    placeholders are filled from new_values.
    """
    merged = dict(existing)
    for key, value in new_values.items():
        if is_placeholder(merged.get(key, "")):
            merged[key] = value
    return merged


def mask_secret(value: str) -> str:
    """Mask the middle of a secret so it can be shown without leaking it."""
    value = value.strip()
    if not value:
        return "(empty)"
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}{'*' * 6}{value[-4:]}"


def render_env(values: dict[str, str]) -> str:
    """Render values as a simple .env file (one KEY=VALUE per line)."""
    lines = [f"{key}={value}" for key, value in values.items()]
    return "\n".join(lines) + "\n"


def is_placeholder(value: str) -> bool:
    """True when the value is empty or an obvious .env.example placeholder."""
    v = value.strip().lower()
    return not v or v.startswith("your_") or v.startswith("<") or v == "changeme"


# ── Console helpers ───────────────────────────────────────────────────────────

def say(msg: str = "") -> None:
    print(msg, flush=True)


def header(msg: str) -> None:
    # ASCII only — Windows consoles often default to cp1252.
    say()
    say(f"-- {msg} " + "-" * max(0, 66 - len(msg)))


def ask(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    try:
        answer = input(f"{prompt}{suffix}: ").strip()
    except EOFError:
        answer = ""
    return answer or default


def ask_yes_no(prompt: str, default: bool = True) -> bool:
    hint = "Y/n" if default else "y/N"
    answer = ask(f"{prompt} ({hint})")
    if not answer:
        return default
    return answer.lower() in ("y", "yes")


# ── Steps ─────────────────────────────────────────────────────────────────────

def check_python() -> None:
    if sys.version_info < MIN_PYTHON:
        say(f"ERROR: Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]}+ is required, "
            f"you are running {platform.python_version()}.")
        say("Install a newer Python from https://www.python.org/downloads/ "
            "and re-run this script with it.")
        sys.exit(1)
    say(f"Python {platform.python_version()} — OK")


def venv_python() -> Path:
    if IS_WINDOWS:
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def setup_venv() -> None:
    header("Virtual environment")
    py = venv_python()
    if py.exists():
        say(f"Reusing existing virtualenv at {VENV_DIR}")
    else:
        say(f"Creating virtualenv at {VENV_DIR} ...")
        subprocess.run([sys.executable, "-m", "venv", str(VENV_DIR)], check=True)
    say("Installing requirements (this can take a few minutes on first run) ...")
    subprocess.run(
        [str(py), "-m", "pip", "install", "-r", str(ROOT / "requirements.txt"),
         "--prefer-binary", "--quiet"],
        check=True,
    )
    say("Requirements installed — OK")


# (key, prompt, help text, secret?) for values the bot cannot run without.
REQUIRED_PROMPTS = [
    (
        "TELEGRAM_BOT_TOKEN",
        "Telegram bot token",
        "Create a bot with @BotFather in Telegram (/newbot) and paste the token here.",
        True,
    ),
    (
        "ALLOWED_TELEGRAM_IDS",
        "Allowed Telegram user IDs",
        "Your numeric Telegram ID — message @userinfobot to get it.\n"
        "  Comma-separate multiple IDs to share the bot with family.\n"
        "  The bot REFUSES to start when this is empty (fail-closed auth).",
        False,
    ),
]

# (key, prompt, help text, default) — Enter accepts the default.
OPTIONAL_PROMPTS = [
    ("TIMEZONE", "Timezone", "IANA name, e.g. Europe/Warsaw, America/New_York.", "Europe/Warsaw"),
    ("DISPLAY_CURRENCY", "Display currency", "Currency code used in reports.", "PLN"),
    ("STORAGE_BACKEND", "Storage backend", "local | gcs | s3. 'local' keeps the Excel file on disk.", "local"),
    ("XLSX_PATH", "Excel file path", "Where the workbook lives (relative to the repo).", "data/Expenses_Improved.xlsx"),
]

DEEPSEEK_HELP = (
    "Optional. Get a key at https://platform.deepseek.com.\n"
    "  Powers /bulk (photo/statement import) and natural-language quick-add.\n"
    "  Without it the bot still runs — guided add, reports, budgets and export\n"
    "  all work; only the AI parsing features will fail."
)


def collect_config(existing: dict[str, str]) -> dict[str, str]:
    header("Configuration (.env)")
    values = dict(existing)

    for key, prompt, help_text, secret in REQUIRED_PROMPTS:
        current = values.get(key, "")
        if not is_placeholder(current):
            shown = mask_secret(current) if secret else current
            say(f"{key} already set ({shown}) — keeping it.")
            continue
        say()
        say(f"{key} is required.")
        say(f"  {help_text}")
        while True:
            answer = ask(prompt)
            if answer:
                values[key] = answer
                break
            say("  This value is required — the bot will not start without it.")

    # DeepSeek key — optional, skippable
    current = values.get("DEEPSEEK_API_KEY", "")
    if not is_placeholder(current):
        say(f"DEEPSEEK_API_KEY already set ({mask_secret(current)}) — keeping it.")
    else:
        say()
        say("DEEPSEEK_API_KEY (optional).")
        say(f"  {DEEPSEEK_HELP}")
        answer = ask("DeepSeek API key (Enter to skip)")
        if answer:
            values["DEEPSEEK_API_KEY"] = answer
        else:
            values.setdefault("DEEPSEEK_API_KEY", "")
            say("  Skipped — AI parsing (/bulk, quick-add) will be unavailable.")

    say()
    say("Optional settings — press Enter to accept the default.")
    for key, prompt, help_text, default in OPTIONAL_PROMPTS:
        current = values.get(key, "")
        if not is_placeholder(current):
            say(f"{key} already set ({current}) — keeping it.")
            continue
        say(f"  {help_text}")
        values[key] = ask(prompt, default)

    return values


def load_env() -> dict[str, str]:
    if ENV_PATH.exists():
        return parse_env_file(ENV_PATH.read_text(encoding="utf-8"))
    if ENV_EXAMPLE_PATH.exists():
        say(f"No .env found — starting from {ENV_EXAMPLE_PATH.name}.")
        return parse_env_file(ENV_EXAMPLE_PATH.read_text(encoding="utf-8"))
    say("No .env or .env.example found — starting from scratch.")
    return {}


def write_env(values: dict[str, str]) -> None:
    ENV_PATH.write_text(render_env(values), encoding="utf-8")
    say(f".env written to {ENV_PATH}")


def validate_config() -> bool:
    header("Validating configuration")
    proc = subprocess.run(
        [str(venv_python()), "-c", "import config; print('config OK')"],
        cwd=str(ROOT), capture_output=True, text=True,
    )
    if proc.returncode == 0:
        say("Configuration parses — OK")
        return True
    say("Configuration failed to load:")
    tail = (proc.stderr or proc.stdout).strip().splitlines()
    for line in tail[-6:]:
        say(f"  {line}")
    say("Fix the value above (edit .env or re-run this script) and try again.")
    return False


def setup_data_dir(values: dict[str, str]) -> None:
    header("Data directory")
    DATA_DIR.mkdir(exist_ok=True)
    say(f"{DATA_DIR} exists — OK")

    xlsx = Path(values.get("XLSX_PATH", "data/Expenses_Improved.xlsx"))
    if not xlsx.is_absolute():
        xlsx = ROOT / xlsx
    if xlsx.exists():
        say(f"Workbook found at {xlsx} — OK")
        return
    if TEMPLATE_PATH.exists():
        if ask_yes_no(f"No workbook at {xlsx}. Create one from the template now?"):
            xlsx.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(TEMPLATE_PATH, xlsx)
            say(f"Created {xlsx} from {TEMPLATE_PATH.name}")
        else:
            say("Skipped — the bot creates it automatically on first run.")
    else:
        say("Template missing — the bot will build a minimal workbook on first run.")


def offer_systemd() -> str | None:
    """Returns the start command to show in the summary."""
    plain_cmd = (
        f"{VENV_DIR}\\Scripts\\python.exe bot.py" if IS_WINDOWS
        else f"{VENV_DIR}/bin/python bot.py"
    )
    if IS_WINDOWS or not shutil.which("systemctl"):
        return plain_cmd

    header("systemd service")
    if not ask_yes_no("Install and enable the systemd service (runs the bot on boot)?",
                      default=False):
        return plain_cmd

    unit_src = (ROOT / "deploy" / "budget-bot.service").read_text(encoding="utf-8")
    user = os.environ.get("SUDO_USER") or os.environ.get("USER", "ubuntu")
    unit = (unit_src
            .replace("User=ubuntu", f"User={user}")
            .replace("/home/ubuntu/budget-bot", str(ROOT))
            .replace(f"{ROOT}/venv/", f"{VENV_DIR}/"))
    unit_path = Path("/etc/systemd/system/budget-bot.service")
    try:
        tmp = ROOT / ".budget-bot.service.tmp"
        tmp.write_text(unit, encoding="utf-8")
        subprocess.run(["sudo", "cp", str(tmp), str(unit_path)], check=True)
        tmp.unlink()
        subprocess.run(["sudo", "systemctl", "daemon-reload"], check=True)
        subprocess.run(["sudo", "systemctl", "enable", "--now", "budget-bot"], check=True)
        say("Service installed and started.")
        return "sudo systemctl start budget-bot   (stop: sudo systemctl stop budget-bot)"
    except (subprocess.CalledProcessError, OSError) as exc:
        say(f"Service install failed ({exc}). You can run the bot manually instead.")
        return plain_cmd


def print_summary(values: dict[str, str], start_cmd: str) -> None:
    header("Setup complete")
    say(f"  Bot token:      {mask_secret(values.get('TELEGRAM_BOT_TOKEN', ''))}")
    say(f"  Allowed IDs:    {values.get('ALLOWED_TELEGRAM_IDS', '')}")
    ds = values.get("DEEPSEEK_API_KEY", "")
    say(f"  DeepSeek key:   {mask_secret(ds) if ds else '(not set — AI parsing disabled)'}")
    say(f"  Storage:        {values.get('STORAGE_BACKEND', 'local')}")
    say(f"  Workbook:       {values.get('XLSX_PATH', 'data/Expenses_Improved.xlsx')}")
    say(f"  Timezone:       {values.get('TIMEZONE', 'Europe/Warsaw')}")
    say(f"  Currency:       {values.get('DISPLAY_CURRENCY', 'PLN')}")
    say()
    say(f"Start the bot:    {start_cmd}")
    say("Stop it:          Ctrl+C (or systemctl stop budget-bot if installed as a service)")
    say(f"Logs:             {ROOT / 'logs'} (daily files, LOG_KEEP_DAYS rotation)")
    say()
    say("Re-run this script any time — it only asks for what is missing.")


def main() -> int:
    say("budget-bot setup")
    say("=" * 68)
    check_python()
    setup_venv()

    existing = load_env()
    values = merge_env(existing, collect_config(existing))
    write_env(values)

    if not validate_config():
        return 1

    setup_data_dir(values)
    start_cmd = offer_systemd()
    print_summary(values, start_cmd)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        say("\nSetup interrupted — re-run scripts/setup_bot.py to continue.")
        sys.exit(130)
