"""settings.py — centralized environment loading and runtime constants."""

import os
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()

PROJECT_ROOT = Path(__file__).resolve().parent
DATA_DIR = PROJECT_ROOT / "data"
DEFAULT_XLSX_PATH = DATA_DIR / "Expenses_Improved.xlsx"
DEFAULT_TEMPLATE_PATH = DATA_DIR / "Expenses_Template.xlsx"
DEFAULT_LOG_DIR = PROJECT_ROOT / "logs"

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
# Ordered list (not a set) — preserves .env comma order so
# ALLOWED_TELEGRAM_IDS[0] can be treated as the primary/sudo user.
ALLOWED_TELEGRAM_IDS = [
    int(x) for x in os.getenv("ALLOWED_TELEGRAM_IDS", "").split(",") if x.strip()
]

xlsx_path = os.getenv("XLSX_PATH", str(DEFAULT_XLSX_PATH)).strip('"\'')
XLSX_PATH = Path(xlsx_path).expanduser()
if not XLSX_PATH.is_absolute():
    XLSX_PATH = PROJECT_ROOT / XLSX_PATH

TIMEZONE = ZoneInfo(os.getenv("TIMEZONE", "Europe/Warsaw"))
DISPLAY_CURRENCY = os.getenv("DISPLAY_CURRENCY", "PLN")
REPORT_TYPE = os.getenv("REPORT_TYPE", "weekly")
AI_PROVIDER = os.getenv("AI_PROVIDER", "deepseek").lower()
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

if "SAVINGS_TARGET_PCT" in os.environ:
    SAVINGS_RATE_TARGET = float(os.getenv("SAVINGS_TARGET_PCT", "20")) / 100
else:
    SAVINGS_RATE_TARGET = float(os.getenv("SAVINGS_RATE_TARGET", "0.20"))

STORAGE_BACKEND = os.getenv("STORAGE_BACKEND", "local").lower()
USER_PREFS_PATH = Path(os.getenv("USER_PREFS_PATH", str(DATA_DIR / "user_prefs.json"))).expanduser()
GCS_BUCKET_NAME = os.getenv("GCS_BUCKET_NAME", "")
GCS_OBJECT_NAME = os.getenv("GCS_OBJECT_NAME", "Expenses_Improved.xlsx")
GCS_KEY_JSON = os.getenv("GCS_KEY_JSON", "")
S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME", "")
S3_OBJECT_NAME = os.getenv("S3_OBJECT_NAME", "Expenses_Improved.xlsx")
S3_ENDPOINT_URL = os.getenv("S3_ENDPOINT_URL", "")
S3_ACCESS_KEY = os.getenv("S3_ACCESS_KEY", "")
S3_SECRET_KEY = os.getenv("S3_SECRET_KEY", "")
S3_REGION = os.getenv("S3_REGION", "us-east-1")
RECOVERY_QUEUE_PATH = Path(os.getenv("RECOVERY_QUEUE_PATH", str(DATA_DIR / "recovery_queue.json"))).expanduser()
BULK_DRAFTS_DIR = Path(os.getenv("BULK_DRAFTS_DIR", str(DATA_DIR / "bulk_drafts"))).expanduser()
if not BULK_DRAFTS_DIR.is_absolute():
    BULK_DRAFTS_DIR = PROJECT_ROOT / BULK_DRAFTS_DIR
MERCHANT_MAP_PATH = Path(os.getenv("MERCHANT_MAP_PATH", str(DATA_DIR / "merchant_map.json"))).expanduser()
if not MERCHANT_MAP_PATH.is_absolute():
    MERCHANT_MAP_PATH = PROJECT_ROOT / MERCHANT_MAP_PATH

STATEMENT_PROFILES_DIR = Path(
    os.getenv("STATEMENT_PROFILES_DIR", str(DATA_DIR / "statement_profiles"))
).expanduser()
if not STATEMENT_PROFILES_DIR.is_absolute():
    STATEMENT_PROFILES_DIR = PROJECT_ROOT / STATEMENT_PROFILES_DIR

# Logging configuration
LOG_DIR = Path(os.getenv("LOG_DIR", str(DEFAULT_LOG_DIR))).expanduser()
if not LOG_DIR.is_absolute():
    LOG_DIR = PROJECT_ROOT / LOG_DIR
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
try:
    LOG_KEEP_DAYS = int(os.getenv("LOG_KEEP_DAYS", "20"))
except ValueError:
    LOG_KEEP_DAYS = 20

BUDGET_CYCLE = bool(int(os.getenv("BUDGET_CYCLE", "0")))
CYCLE_PROMPT_COOLDOWN_DAYS = 20
# Public name for the income category that triggers cycle prompts.
SALARY_CATEGORY = "Salary"
