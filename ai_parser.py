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

import settings

log = logging.getLogger(__name__)


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


def _build_parse_prompt(lists: dict) -> str:
    all_cats  = ", ".join(lists.get("categories", []))
    txn_types = " | ".join(lists.get("txn_types", ["Expense", "Income", "Savings"]))
    persons   = ", ".join(lists.get("persons", []))
    person_note = f" (known persons: {persons})" if persons else ""
    return f"""You are a financial transaction parser. Extract ALL transactions from the input.

Return ONLY a JSON array. Each element must have these exact keys:
- "date": "YYYY-MM-DD" (use today's date if unknown)
- "value": number (positive amount)
- "currency": {" | ".join(lists.get("currencies", ["PLN"]))} (default PLN)
- "type": {txn_types}
- "category": one of: {all_cats}
- "description": clean 2-4 word merchant label (max 60 chars)
- "person": ""{person_note}

CRITICAL field rules:
- "description" must be a clean, human-readable merchant or purpose label
  (e.g. "Biedronka", "Shell fuel", "Autopay S.A."). NEVER include masked card
  numbers (4111XXXXXXXX1111), terminal ids, BPID:/reference codes, /OPT/
  routing blocks, or trailing city/country codes from the raw statement line.
- "category" MUST be copied EXACTLY, character for character, from the list above.
  Never invent, shorten, translate, or paraphrase a category name.
  If unsure, use "Other".
- "person" identifies WHO IN THE HOUSEHOLD made the transaction. It must be one of
  the known persons above or "". NEVER put the transfer recipient, counterparty,
  merchant, or landlord here — mention them in "description" instead.
- "type" must be coherent with "category": category Savings ⇒ type Savings
  (transfers to your own savings account are Savings, never Expense);
  category Salary ⇒ type Income. Refunds/returns are Income with the
  category of the ORIGINAL purchase (e.g. a returned jacket is Income/Shopping).

Rules:
- This may be a bank statement, transaction export, receipt, or mixed transaction text.
- Parse it as a list of individual financial transactions, not as one long narrative.
- For statement-style text, identify one transaction per block and extract the transaction date, amount, description, and direction.
- Negative amounts = Expense; positive amounts = Income.
- If the amount is written with a sign or appears after words like refund/zwrot/return, infer the direction from that context.
- Ignore balance rows, repeated headers, summary lines, account metadata, and obvious fees unless they are real transactions.
- Do not merge multiple separate transactions into one row.
- Do not invent dates; use the date nearest to the transaction block when present.
- If a transaction is ambiguous, still return the best possible structured entry rather than skipping it.
- Receipt: all items = Expense, category = Groceries unless clearly otherwise.
- Round amounts to 2 decimal places.
- Use the exact categories, types, and person names provided above when possible; otherwise fall back to "Other".

Return ONLY the JSON array, no other text."""


def _build_quick_prompt(lists: dict) -> str:
    all_cats  = ", ".join(lists.get("categories", []))
    txn_types = " | ".join(lists.get("txn_types", ["Expense", "Income", "Savings"]))
    persons   = ", ".join(lists.get("persons", []))
    person_note = f" (known persons: {persons})" if persons else ""
    return f"""You are a transaction parser for a Polish household finance bot.

Parse the user message as a single financial transaction.
Return ONLY a JSON object with these keys:
- "date": "YYYY-MM-DD" (use today's date if unknown)
- "value": positive number
- "currency": {" | ".join(lists.get("currencies", ["PLN"]))} (default PLN; zł/zl = PLN)
- "type": {txn_types}
- "category": one of: {all_cats}
- "description": clean 2-4 word merchant label (max 40 chars) — never card numbers, BPID:/reference codes, or city/country suffixes
- "person": ""{person_note}

Use only the exact categories, types, and person names provided above. Do not invent new categories, transaction types, or persons.
Keep "type" coherent with "category": category Savings ⇒ type Savings (moving money to your own savings is Savings, never Expense); category Salary ⇒ type Income. Refunds/returns are Income with the category of the original purchase.
If you cannot map the message to an exact known category, type, or person, return: {{"not_transaction": true}}

Examples:
"groceries 89" → {{"value": 89, "currency": "PLN", "type": "Expense", "category": "Groceries", "description": "groceries", "person": ""}}
"lunch 45 EUR" → {{"value": 45, "currency": "EUR", "type": "Expense", "category": "Dining Out", "description": "lunch", "person": ""}}
"salary 5000" → {{"value": 5000, "currency": "PLN", "type": "Income", "category": "Salary", "description": "salary", "person": ""}}
"hello" → {{"not_transaction": true}}
"2026-05-24 groceries 89" → {{"date": "2026-05-24", "value": 89, "currency": "PLN", "type": "Expense", "category": "Groceries", "description": "groceries", "person": ""}}
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
                {"role": "system", "content": _build_parse_prompt(lists)},
                {"role": "user",   "content": text},
            ],
            max_tokens=self._BULK_MAX_TOKENS,
        )
        parsed = _try_parse_json(raw)
        if isinstance(parsed, list):
            return parsed
        if isinstance(parsed, dict):
            return [parsed]

        salvaged = _salvage_json_objects(raw)
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
            {"role": "system", "content": _build_quick_prompt(lists)},
            {"role": "user",   "content": text},
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
                {"role": "system", "content": _build_parse_prompt(lists)},
                {"role": "user",   "content": [
                    {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{b64}"}},
                    {"type": "text",      "text": "Parse all transactions from this image."},
                ]},
            ],
            max_tokens=self._BULK_MAX_TOKENS,
        )
        parsed = _try_parse_json(raw)
        if isinstance(parsed, list):
            return parsed
        if parsed is None:
            salvaged = _salvage_json_objects(raw)
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
