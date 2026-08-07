"""
ai_parser.py
============
AI-powered transaction parsing. Supports multiple providers — swap by
setting AI_PROVIDER in .env. Adding a new provider: subclass AIProvider,
implement the three methods, register in _PROVIDER_MAP.

Currently available:
  deepseek  — DeepSeek via OpenAI-compatible API (default)
"""

import base64
import json
import logging
import re
from abc import ABC, abstractmethod
from datetime import datetime, time

from pydantic import BaseModel, ValidationError

import settings
from validators import resolve_fallback_category

log = logging.getLogger(__name__)


def _parse_time_hhmm(raw: str) -> time:
    text = str(raw or "").strip()
    hh, mm = text.split(":", 1)
    return time(int(hh), int(mm))


def _parse_peak_windows_utc(raw: str) -> list[tuple[time, time]]:
    windows: list[tuple[time, time]] = []
    for chunk in str(raw or "").split(","):
        piece = chunk.strip()
        if not piece:
            continue
        if "-" not in piece:
            continue
        start_raw, end_raw = piece.split("-", 1)
        try:
            windows.append((_parse_time_hhmm(start_raw), _parse_time_hhmm(end_raw)))
        except Exception:
            continue
    return windows


def _in_window(now_utc: time, start: time, end: time) -> bool:
    if start < end:
        return start <= now_utc < end
    # Cross-midnight window.
    return now_utc >= start or now_utc < end


_DEEPSEEK_DEFAULT_PEAK_WINDOWS = "01:00-04:00,06:00-10:00"


def get_peak_hours_status(provider_name: str | None = None) -> dict:
    """Return provider peak-hour status and user-facing message."""
    provider = str(provider_name or settings.AI_PROVIDER or "").strip().lower()
    now_utc = datetime.utcnow().time()

    if provider not in ("deepseek", ""):
        return {
            "provider": provider,
            "known": False,
            "is_peak": None,
            "message": (
                f"Peak-hour detection is not available for provider '{provider}'; "
                "please check usage manually."
            ),
        }

    # Accept "deepseek" or empty/unset (falls back to deepseek as the only provider).
    raw_windows = str(settings.DEEPSEEK_PEAK_WINDOWS_UTC or "").strip()
    using_default = not raw_windows
    if using_default:
        # DEEPSEEK_PEAK_WINDOWS_UTC is empty or unset — use hardcoded defaults.
        raw_windows = _DEEPSEEK_DEFAULT_PEAK_WINDOWS

    windows = _parse_peak_windows_utc(raw_windows)
    now_utc = datetime.utcnow().time()
    is_peak = any(_in_window(now_utc, start, end) for start, end in windows)
    label = f"{raw_windows} (default)" if using_default else raw_windows
    return {
        "provider": "deepseek",
        "known": True,
        "is_peak": is_peak,
        "message": (
            f"DeepSeek peak hours active (UTC: {label}). AI may be slower."
            if is_peak else
            f"DeepSeek off-peak (UTC: {label}). Good time to re-analyze."
        ),
    }


def is_off_peak() -> bool:
    """Compatibility helper: True when provider is currently outside known peak windows."""
    status = get_peak_hours_status()
    if not status.get("known"):
        return True
    return not bool(status.get("is_peak"))


def _strip_fences(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return raw.strip()


def _try_parse_json(raw: str) -> list[dict] | dict | None:
    cleaned = _strip_fences(raw)
    if not cleaned:
        return None
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    match = re.search(r"\[(?:.|\n)*\]", cleaned)
    if match:
        candidate = match.group(0)
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass

    match = re.search(r"\{(?:.|\n)*\}", cleaned)
    if match:
        candidate = match.group(0)
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            pass

    return None


def _salvage_json_objects(raw: str) -> list[dict]:
    """
    Recover complete top-level JSON objects from a malformed or truncated
    response (e.g. the model hit its output token limit mid-array).
    Scans with brace-depth + string awareness and parses each {...} span.
    """
    cleaned = _strip_fences(raw or "")
    results: list[dict] = []
    depth = 0
    start = None
    in_string = False
    escape = False
    for i, ch in enumerate(cleaned):
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = in_string
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            if depth > 0:
                depth -= 1
                if depth == 0 and start is not None:
                    try:
                        obj = json.loads(cleaned[start : i + 1])
                        if isinstance(obj, dict):
                            results.append(obj)
                    except json.JSONDecodeError:
                        pass
                    start = None
    return results


# Statement lines that begin a new dated block, e.g. "05.07.2026, Sunday",
# "2026-07-05", "Today", "Yesterday".
_DATE_HEADER_RE = re.compile(
    r"^\s*(\d{2}\.\d{2}\.\d{4}|\d{4}-\d{2}-\d{2}|Today|Yesterday)\b", re.IGNORECASE
)

_CHUNK_TARGET_CHARS = 5000


def _chunk_statement_text(text: str, target: int = _CHUNK_TARGET_CHARS) -> list[str]:
    """
    Split long statement text into chunks near `target` chars, breaking only
    at date-header lines so a transaction block is never split. The date
    header that opens each chunk is carried over, keeping date context intact.
    """
    lines = text.splitlines()
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    for line in lines:
        # Chunks split only AT date-header lines, so every chunk after the
        # first starts with its own date header — no carry-over needed.
        if _DATE_HEADER_RE.match(line) and current and current_len >= target:
            chunks.append("\n".join(current))
            current = []
            current_len = 0
        current.append(line)
        current_len += len(line) + 1

    if current:
        chunks.append("\n".join(current))
    return [c for c in chunks if c.strip()]


def _try_parse_structured_text(text: str) -> list[dict] | None:
    cleaned = (text or "").strip()
    if not cleaned:
        return None

    candidates = []
    for match in re.finditer(r"\{[^{}]*\}", cleaned):
        candidate = match.group(0)
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            candidate = candidate.replace("'", '"')
            candidate = re.sub(r",\s*([}\]])", r"\1", candidate)
            try:
                parsed = json.loads(candidate)
            except json.JSONDecodeError:
                continue
        if isinstance(parsed, dict):
            candidates.append(parsed)

    if candidates:
        return candidates

    compact = re.sub(r"\s+", " ", cleaned)
    for match in re.finditer(r"\{[^{}]*\}", compact):
        candidate = match.group(0)
        try:
            parsed = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            candidates.append(parsed)

    if candidates:
        return candidates

    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    else:
        if isinstance(parsed, list):
            return [item for item in parsed if isinstance(item, dict)]
        if isinstance(parsed, dict):
            return [parsed]

    key_value_pairs = []
    for line in cleaned.splitlines():
        line = line.strip()
        if not line or line.startswith("//"):
            continue
        if ":" not in line:
            continue
        if line.startswith(("{", "[", "]", "}")):
            continue
        key, value = line.split(":", 1)
        key = key.strip().strip('"\'')
        value = value.strip().rstrip(",")
        if len(value) >= 2 and value[0] in {'"', "'"} and value[-1] == value[0]:
            value = value[1:-1]
        if not key:
            continue
        if value.lower() in {"true", "false", "null"}:
            parsed_value = value.lower() == "true"
        else:
            try:
                parsed_value = float(value)
            except ValueError:
                parsed_value = value
        key_value_pairs.append((key, parsed_value))

    if key_value_pairs:
        known_transaction_fields = {"date", "value", "currency", "type", "category", "description", "person"}
        if not any(key.lower() in known_transaction_fields for key, _ in key_value_pairs):
            return []
        record = {}
        for key, value in key_value_pairs:
            record[key] = value
        return [record]

    return None


# ── Typed parse boundary ────────────────────────────────────────────────────────

class ParsedTransaction(BaseModel):
    date: str
    value: float
    currency: str
    category: str
    description: str
    type: str
    is_recurring: bool = False


# ── Compact positional-array output format ───────────────────────────────────
# The bulk parse prompt asks for positional arrays instead of JSON objects —
# roughly half the output tokens per transaction. Position → field mapping:
_ARRAY_FIELDS = ("date", "value", "currency", "category", "description", "type",
                 "is_recurring")


def _decode_positional_array(arr) -> dict | None:
    """
    Map one positional array [date, amount, currency, category, description,
    type, is_recurring] to a transaction dict. Missing trailing positions are
    simply absent (downstream validators default them); extra positions are
    ignored. Returns None for anything that isn't a plausible row (not a
    list/tuple, or fewer than 2 positions).
    """
    if not isinstance(arr, (list, tuple)) or len(arr) < 2:
        return None
    if arr[1] is None:
        return None
    return {field: value for field, value in zip(_ARRAY_FIELDS, arr)}


def _normalize_ai_rows(items) -> list[dict]:
    """
    Dual-format normalization (backward compat during the array-format
    rollout): positional arrays are decoded, dicts pass through unchanged,
    anything else is dropped. Each candidate row is validated against
    ParsedTransaction; rows that fail validation are logged and excluded.
    """
    rows: list[dict] = []
    for item in items or []:
        if isinstance(item, dict):
            candidate = item
        else:
            candidate = _decode_positional_array(item)
            if candidate is None:
                continue
        try:
            parsed = ParsedTransaction.model_validate(candidate)
        except ValidationError as exc:
            log.debug("Dropping invalid AI row %r: %s", candidate, exc)
            continue
        rows.append(parsed.model_dump())
    return rows


def _salvage_json_arrays(raw: str) -> list[dict]:
    """
    Array-aware salvage: recover complete inner positional arrays from a
    malformed or truncated response (outer array cut mid-element). Scans with
    bracket-depth + string awareness and decodes each depth-1 [...] span.
    """
    cleaned = _strip_fences(raw or "")
    results: list[dict] = []
    depth = 0
    start = None
    in_string = False
    escape = False
    for i, ch in enumerate(cleaned):
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = in_string
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "[":
            depth += 1
            if depth == 2:
                start = i
        elif ch == "]":
            if depth == 2 and start is not None:
                try:
                    arr = json.loads(cleaned[start : i + 1])
                    # First position must be a string date — guards against
                    # decoding stray numeric arrays nested inside objects.
                    if isinstance(arr, list) and arr and isinstance(arr[0], str):
                        decoded = _decode_positional_array(arr)
                        if decoded is not None:
                            results.append(decoded)
                except json.JSONDecodeError:
                    pass
                start = None
            if depth > 0:
                depth -= 1
    return results


def _salvage_rows(raw: str) -> list[dict]:
    """Partial-parse recovery for both output formats: arrays first, then objects."""
    return _salvage_json_arrays(raw) or _salvage_json_objects(raw)


def _build_reference_block(lists: dict) -> str:
    """
    Dynamic reference data (currencies, types, categories) appended to the END
    of the user message — never interpolated into the system prompt, so the
    system prompt stays byte-identical across calls and DeepSeek's
    prompt-prefix cache applies.
    """
    all_cats   = ", ".join(lists.get("categories", []))
    fallback_category = resolve_fallback_category(lists.get("categories", []))
    txn_types  = " | ".join(lists.get("txn_types", ["Expense", "Income", "Savings"]))
    currency_list = lists.get("currencies") or [settings.DISPLAY_CURRENCY]
    currencies = " | ".join(currency_list)
    # The user's configured currency (DISPLAY_CURRENCY in .env) is the default
    # when it is an allowed currency; otherwise fall back to the first allowed.
    default_ccy = (
        settings.DISPLAY_CURRENCY
        if settings.DISPLAY_CURRENCY in currency_list
        else currency_list[0]
    )
    return (
        "Reference data for this request:\n"
        f"Allowed currencies: {currencies}\n"
        f"Default currency: {default_ccy}\n"
        f"Fallback category: {fallback_category}\n"
        f"Allowed transaction types: {txn_types}\n"
        f"Allowed categories: {all_cats}"
    )


# byte-identical for prompt cache
_PARSE_SYSTEM_PROMPT = """You are a financial transaction parser. Extract ALL transactions from the input.

The allowed currencies, transaction types, and categories are listed at the END of the user message under "Reference data for this request".

Return ONLY a JSON array of positional arrays — one inner array per transaction, with the fields in EXACTLY this order:
[date, amount, currency, category, description, type, is_recurring]
- date: "YYYY-MM-DD" string (use today's date if unknown)
- amount: number (positive amount)
- currency: one of the allowed currencies (fall back to the default currency in the reference data)
- category: one of the allowed categories
- description: clean 2-4 word merchant label (max 60 chars)
- type: one of the allowed transaction types
- is_recurring: true or false (false if unknown)

Example output:
[["2026-05-19", 23.00, "EUR", "Groceries", "Lidl", "Expense", false], ["2026-05-20", 5000, "EUR", "Salary", "salary", "Income", true]]

CRITICAL field rules:
- description must be a clean, human-readable merchant or purpose label
  (e.g. "Lidl", "Shell fuel", "City Utilities"). NEVER include masked card
  numbers (4111XXXXXXXX1111), terminal ids, BPID:/reference codes, /OPT/
  routing blocks, or trailing city/country codes from the raw statement line.
- category MUST be copied EXACTLY, character for character, from the allowed list.
  Never invent, shorten, translate, or paraphrase a category name.
    If unsure, use the fallback category named in the reference data.
- Transfer recipients, counterparties, and landlords belong in description —
  there is no separate field for them.
- "Savings" is a transaction TYPE, never a category: transfers to your own
    savings account get type "Savings" and fallback category, never Expense.
- type must be coherent with category:
  category Salary ⇒ type Income. Refunds/returns are Income with the
  category of the ORIGINAL purchase (e.g. a returned jacket is Income/Shopping).

Rules:
- This may be a bank statement, transaction export, receipt, or mixed transaction text.
- Parse it as a list of individual financial transactions, not as one long narrative.
- For statement-style text, identify one transaction per block and extract the transaction date, amount, description, and direction.
- Negative amounts = Expense; positive amounts = Income.
- If the amount is written with a sign or appears after words like refund/return (in any language), infer the direction from that context.
- Ignore balance rows, repeated headers, summary lines, account metadata, and obvious fees unless they are real transactions.
- Do not merge multiple separate transactions into one row.
- Do not invent dates; use the date nearest to the transaction block when present.
- If a transaction is ambiguous, still return the best possible structured entry rather than skipping it.
- Receipt: all items = Expense, category = Groceries unless clearly otherwise.
- Round amounts to 2 decimal places.
- Use the exact categories and types provided in the reference data when possible; otherwise use the fallback category named in the reference data.

Return ONLY the JSON array, no other text."""


# byte-identical for prompt cache
_QUICK_SYSTEM_PROMPT = """You are a transaction parser for a household finance bot.

The allowed currencies, transaction types, categories, and the default currency are listed at the END of the user message under "Reference data for this request".

Parse the user message as a single financial transaction.
Return ONLY a JSON object with these keys:
- "date": "YYYY-MM-DD" (use today's date if unknown)
- "value": positive number
- "currency": one of the allowed currencies (fall back to the default currency; map local currency symbols and abbreviations to their ISO code)
- "type": one of the allowed transaction types
- "category": one of the allowed categories
- "description": clean 2-4 word merchant label (max 40 chars) — never card numbers, BPID:/reference codes, or city/country suffixes

Use only the exact categories and types provided in the reference data. Do not invent new categories or transaction types.
"Savings" is a transaction TYPE, never a category: when the message says "savings", "saved", "put into savings" or similar, set type "Savings" and category equal to the fallback category named in the reference data. Moving money to your own savings is type Savings, never Expense.
Keep "type" coherent with "category": category Salary ⇒ type Income. Refunds/returns are Income with the category of the original purchase.
If you cannot map the message to an exact known category or type, return: {"not_transaction": true}

Examples (assuming default currency EUR):
"groceries 89" → {"value": 89, "currency": "EUR", "type": "Expense", "category": "Groceries", "description": "groceries"}
"lunch 45 GEL" → {"value": 45, "currency": "GEL", "type": "Expense", "category": "Dining Out", "description": "lunch"}
"salary 5000" → {"value": 5000, "currency": "EUR", "type": "Income", "category": "Salary", "description": "salary"}
"2380 added to savings" → {"value": 2380, "currency": "EUR", "type": "Savings", "category": "<fallback category>", "description": "savings"}
"hello" → {"not_transaction": true}
"2026-05-24 groceries 89" → {"date": "2026-05-24", "value": 89, "currency": "EUR", "type": "Expense", "category": "Groceries", "description": "groceries"}
"""

# ── Provider interface ────────────────────────────────────────────────────────

class AIProvider(ABC):
    """
    Base class for AI transaction parsing providers.

    To add a new provider:
      1. Subclass AIProvider
      2. Implement chat, parse_text, parse_quick, parse_image
      3. Add to _PROVIDER_MAP below
      4. Set AI_PROVIDER=<name> in .env
    """

    @abstractmethod
    def chat(self, messages: list[dict]) -> str:
        """
        Send a single chat-completion request and return the raw string response.
        This is the low-level primitive used by propose_mapping and any other caller
        that needs direct message-level control. Declared here so callers never need
        to reach for a private _chat that may not exist on other providers.
        """

    @abstractmethod
    def parse_text(self, text: str, lists: dict) -> list[dict]:
        """Extract all transactions from a text string or document content."""

    @abstractmethod
    def parse_quick(self, text: str, lists: dict) -> dict | None:
        """Parse a single transaction from a short message. Returns None if not a transaction."""

    @abstractmethod
    def parse_image(self, image_bytes: bytes, lists: dict, mime_type: str = "image/jpeg") -> list[dict]:
        """Extract all transactions from an image (receipt, bank statement screenshot)."""


# ── DeepSeek provider ─────────────────────────────────────────────────────────

class DeepSeekProvider(AIProvider):

    def __init__(self):
        self._client = None

    # A hung request would otherwise block an executor thread for the whole
    # 300s conversation timeout. Large chunk parses take ~20s each.
    _REQUEST_TIMEOUT_S = 120

    def _client_(self):
        if self._client is None:
            from openai import OpenAI
            self._client = OpenAI(
                api_key=settings.DEEPSEEK_API_KEY,
                base_url="https://api.deepseek.com",
                timeout=self._REQUEST_TIMEOUT_S,
                max_retries=1,
            )
        return self._client

    # DeepSeek defaults to 4096 output tokens; a large statement produces a
    # JSON array well beyond that and the response gets truncated mid-array.
    _BULK_MAX_TOKENS = 8192

    def _chat(self, messages: list, max_tokens: int | None = None) -> str:
        model = settings.DEEPSEEK_MODEL
        kwargs = {"model": model, "messages": messages, "temperature": 0}
        if max_tokens:
            kwargs["max_tokens"] = max_tokens
        resp = self._client_().chat.completions.create(**kwargs)
        return resp.choices[0].message.content

    def chat(self, messages: list[dict]) -> str:
        """Public AIProvider.chat — delegates to the internal _chat (no token cap)."""
        return self._chat(messages)

    def parse_text(self, text: str, lists: dict) -> list[dict]:
        chunks = _chunk_statement_text(text)
        if len(chunks) <= 1:
            return self._parse_text_single(text, lists)

        log.info("Bulk text split into %d chunks for parsing", len(chunks))
        merged: list[dict] = []
        for i, chunk in enumerate(chunks, 1):
            items = self._parse_text_single(chunk, lists)
            log.info("Chunk %d/%d parsed: %d transactions", i, len(chunks), len(items))
            merged.extend(items)
        return merged

    def _parse_text_single(self, text: str, lists: dict) -> list[dict]:
        raw = self._chat(
            [
                # System prompt is a static constant; dynamic reference data
                # travels at the end of the user message (prompt cache).
                {"role": "system", "content": _PARSE_SYSTEM_PROMPT},
                {"role": "user",   "content": f"{text}\n\n{_build_reference_block(lists)}"},
            ],
            max_tokens=self._BULK_MAX_TOKENS,
        )
        parsed = _try_parse_json(raw)
        if isinstance(parsed, list):
            return _normalize_ai_rows(parsed)
        if isinstance(parsed, dict):
            return [parsed]

        salvaged = _salvage_rows(raw)
        if salvaged:
            log.warning(
                "AI response was malformed/truncated — salvaged %d complete transactions",
                len(salvaged),
            )
            return salvaged

        structured = _try_parse_structured_text(text)
        if structured is not None:
            log.info("Recovered transactions from structured text input.")
            return structured

        log.error("JSON parse failed for bulk text. Raw: %s", raw)
        raise ValueError("Could not parse transactions from the provided text.")

    def parse_quick(self, text: str, lists: dict) -> dict | None:
        raw = self._chat([
            # Static system prompt + dynamic reference data in the user
            # message keeps the system prefix byte-identical (prompt cache).
            {"role": "system", "content": _QUICK_SYSTEM_PROMPT},
            {"role": "user",   "content": f"{text}\n\n{_build_reference_block(lists)}"},
        ])
        parsed = _try_parse_json(raw)
        if isinstance(parsed, list):
            if parsed and isinstance(parsed[0], dict):
                parsed = parsed[0]
            else:
                log.error("JSON parse failed for quick add. Raw: %s", raw)
                raise ValueError("Could not parse the transaction from the provided message.")
        if not isinstance(parsed, dict):
            log.error("JSON parse failed for quick add. Raw: %s", raw)
            raise ValueError("Could not parse the transaction from the provided message.")
        return None if parsed.get("not_transaction") else parsed

    def parse_image(self, image_bytes: bytes, lists: dict, mime_type: str = "image/jpeg") -> list[dict]:
        b64 = base64.standard_b64encode(image_bytes).decode()
        raw = self._chat(
            [
                # Static system prompt; reference data at the end of the user
                # message (prompt cache).
                {"role": "system", "content": _PARSE_SYSTEM_PROMPT},
                {"role": "user",   "content": [
                    {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{b64}"}},
                    {"type": "text",      "text": "Parse all transactions from this image."
                                                  f"\n\n{_build_reference_block(lists)}"},
                ]},
            ],
            max_tokens=self._BULK_MAX_TOKENS,
        )
        parsed = _try_parse_json(raw)
        if isinstance(parsed, list):
            return _normalize_ai_rows(parsed)
        if parsed is None:
            salvaged = _salvage_rows(raw)
            if salvaged:
                log.warning(
                    "AI image response was malformed/truncated — salvaged %d transactions",
                    len(salvaged),
                )
                return salvaged
            log.error("JSON parse failed for image input. Raw: %s", raw)
            raise ValueError("Could not parse transactions from the provided image.")
        raise ValueError("Unexpected parser response format.")


# ── Provider registry ─────────────────────────────────────────────────────────

_PROVIDER_MAP: dict[str, type[AIProvider]] = {
    "deepseek": DeepSeekProvider,
    # "openai":   OpenAIProvider,   ← add future providers here
    # "gemini":   GeminiProvider,
}

_active_provider: AIProvider | None = None


def get_provider() -> AIProvider:
    global _active_provider
    if _active_provider is None:
        name = settings.AI_PROVIDER
        cls = _PROVIDER_MAP.get(name)
        if cls is None:
            raise ValueError(
                f"Unknown AI_PROVIDER '{name}'. "
                f"Available: {list(_PROVIDER_MAP)}"
            )
        _active_provider = cls()
    return _active_provider


# ── Public API (bot.py imports these — provider is an implementation detail) ──

def parse_text(text: str, lists: dict) -> list[dict]:
    return get_provider().parse_text(text, lists)


def parse_quick(text: str, lists: dict) -> dict | None:
    return get_provider().parse_quick(text, lists)


def parse_image(image_bytes: bytes, lists: dict, mime_type: str = "image/jpeg") -> list[dict]:
    return get_provider().parse_image(image_bytes, lists, mime_type)


# ── Merchant categorization (statement imports) ──────────────────────────────
#
# Token economy: statement profiles extract date/amount/description
# deterministically with zero tokens; the only AI work left is assigning a
# category to merchants the merchant map doesn't know yet. Sending a compact
# list of unique merchant names (~5 output tokens each) instead of full
# transaction JSON keeps the cost at a small fraction of a full parse.

# Kept byte-identical across calls so DeepSeek's prompt-prefix cache applies;
# all dynamic content (categories, merchants) goes in the user message.
_CATEGORIZE_SYSTEM_PROMPT = (
    "You assign spending categories to bank-statement merchant names. "
    "Reply with ONLY a JSON object mapping each merchant name (key verbatim, "
    "exactly as given) to the single best category from the provided list. "
    "Use category names exactly as given. "
    "If unsure, use the fallback category named in the user message."
)

_CATEGORIZE_BATCH_SIZE = 80


def categorize_merchants(merchants: list[str], categories: list[str]) -> dict[str, str]:
    """
    One compact AI call (per batch of 80) mapping unique merchant names to
    categories. Returns {merchant: category}; missing/failed merchants are
    simply absent — the caller falls back to its default. Never raises.
    """
    if not merchants or not categories:
        return {}
    provider = get_provider()
    result: dict[str, str] = {}
    for i in range(0, len(merchants), _CATEGORIZE_BATCH_SIZE):
        batch = merchants[i:i + _CATEGORIZE_BATCH_SIZE]
        fallback_category = resolve_fallback_category(categories)
        user = (
            f"Fallback category: {json.dumps(fallback_category, ensure_ascii=False)}\n"
            f"Categories: {json.dumps(categories, ensure_ascii=False)}\n"
            f"Merchants: {json.dumps(batch, ensure_ascii=False)}"
        )
        try:
            raw = provider.chat([
                {"role": "system", "content": _CATEGORIZE_SYSTEM_PROMPT},
                {"role": "user", "content": user},
            ])
            parsed = _try_parse_json(raw)
            if isinstance(parsed, dict):
                result.update({str(k): str(v) for k, v in parsed.items()})
            else:
                log.warning("categorize_merchants: non-object response for batch %d", i)
        except Exception as exc:
            log.warning("categorize_merchants batch %d failed: %s", i, exc)
    return result
