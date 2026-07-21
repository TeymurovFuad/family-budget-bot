"""
test_ai_parser.py — exhaustive unit tests for ai_parser module.
Covers _strip_fences, DeepSeekProvider.parse_quick/parse_text/parse_image,
and the prompt-building helpers.
"""

import json
import pytest
from unittest.mock import patch

from ai_parser import _strip_fences, DeepSeekProvider, _build_quick_prompt, _build_parse_prompt


# ── _strip_fences ──────────────────────────────────────────────────────────────

def test_plain_json_returned_as_is():
    assert _strip_fences('[{"a":1}]') == '[{"a":1}]'


def test_json_fence_extracted():
    assert _strip_fences('```json\n[{"a":1}]\n```') == '[{"a":1}]'


def test_plain_fence_no_language_tag():
    assert _strip_fences('```\n[{"a":1}]\n```') == '[{"a":1}]'


def test_uppercase_JSON_fence_not_stripped():
    # split on "```" → index[1] = 'JSON\n[{"a":1}]\n'
    # does NOT start with lowercase "json" so the 4-char strip is skipped;
    # only outer whitespace is stripped.
    result = _strip_fences('```JSON\n[{"a":1}]\n```')
    assert result == 'JSON\n[{"a":1}]'


def test_empty_string_returns_empty():
    assert _strip_fences('') == ''


def test_whitespace_only_returns_empty():
    assert _strip_fences('   ') == ''


# ── DeepSeekProvider.parse_quick ───────────────────────────────────────────────

def test_parse_quick_valid_transaction():
    provider = DeepSeekProvider()
    mock_resp = '{"value":89,"currency":"PLN","type":"Expense","category":"Groceries","description":"test","person":""}'
    with patch.object(DeepSeekProvider, "_chat", return_value=mock_resp):
        result = provider.parse_quick("groceries 89", {})
    assert result is not None
    assert isinstance(result, dict)


def test_parse_quick_not_transaction_returns_none():
    provider = DeepSeekProvider()
    with patch.object(DeepSeekProvider, "_chat", return_value='{"not_transaction":true}'):
        result = provider.parse_quick("hello", {})
    assert result is None


def test_parse_quick_malformed_json_raises():
    provider = DeepSeekProvider()
    with patch.object(DeepSeekProvider, "_chat", return_value="not json at all"):
        with pytest.raises(ValueError):
            provider.parse_quick("groceries 89", {})


def test_parse_quick_list_response_returns_first_transaction():
    provider = DeepSeekProvider()
    mock_resp = '[{"value":89,"currency":"PLN","type":"Expense","category":"Groceries","description":"test","person":""}]'
    with patch.object(DeepSeekProvider, "_chat", return_value=mock_resp):
        result = provider.parse_quick("groceries 89", {})
    assert result is not None
    assert result["value"] == 89


def test_parse_quick_extra_keys_preserved():
    provider = DeepSeekProvider()
    mock_resp = '{"value":50,"currency":"PLN","type":"Income","category":"Salary","description":"pay","person":"","extra_field":"keep_me"}'
    with patch.object(DeepSeekProvider, "_chat", return_value=mock_resp):
        result = provider.parse_quick("salary 50", {})
    assert result["extra_field"] == "keep_me"


def test_parse_quick_empty_string_response_raises():
    provider = DeepSeekProvider()
    with patch.object(DeepSeekProvider, "_chat", return_value=""):
        with pytest.raises(ValueError):
            provider.parse_quick("anything", {})


# ── DeepSeekProvider.parse_text ───────────────────────────────────────────────

def test_parse_text_returns_list():
    provider = DeepSeekProvider()
    mock_resp = '[{"value":100,"currency":"PLN","type":"Expense","category":"Groceries","description":"shop","person":""}]'
    with patch.object(DeepSeekProvider, "_chat", return_value=mock_resp):
        result = provider.parse_text("shop 100", {})
    assert isinstance(result, list)
    assert len(result) == 1


def test_parse_text_empty_array():
    provider = DeepSeekProvider()
    with patch.object(DeepSeekProvider, "_chat", return_value="[]"):
        result = provider.parse_text("nothing", {})
    assert result == []


def test_parse_text_malformed_raises():
    provider = DeepSeekProvider()
    with patch.object(DeepSeekProvider, "_chat", return_value="BROKEN{"):
        with pytest.raises(ValueError):
            provider.parse_text("anything", {})


def test_parse_text_single_transaction():
    provider = DeepSeekProvider()
    mock_resp = '[{"value":200,"currency":"EUR","type":"Income","category":"Salary","description":"pay","person":""}]'
    with patch.object(DeepSeekProvider, "_chat", return_value=mock_resp):
        result = provider.parse_text("salary 200 EUR", {})
    assert len(result) == 1
    assert result[0]["value"] == 200

def test_parse_text_recovers_from_structured_input_when_llm_fails():
    provider = DeepSeekProvider()
    structured = '''
    {"date": "2026-05-19", "value": 23.00, "currency": "PLN", "type": "Expense", "category": "Entertainment", "description": "LUCKY LÓD BLIK", "person": ""},
    {"date": "2026-05-19", "value": 6.00, "currency": "PLN", "type": "Expense", "category": "Other", "description": "ALL DAY PIOTR SOSNOWSKI", "person": ""},
    {"date": "2026-05-19", "value":
    '''
    with patch.object(DeepSeekProvider, "_chat", return_value="not json at all"):
        result = provider.parse_text(structured, {})
    assert len(result) == 2
    assert result[0]["description"] == "LUCKY LÓD BLIK"
    assert result[1]["description"] == "ALL DAY PIOTR SOSNOWSKI"


def test_parse_text_recovers_from_key_value_structured_text_without_braces():
    provider = DeepSeekProvider()
    structured = '''
    "date": "2026-05-23",
    "value": 100.00,
    "currency": "PLN",
    "type": "Expense",
    "category": "Groceries",
    "description": "shop",
    "person": ""
    '''
    with patch.object(DeepSeekProvider, "_chat", return_value="not json at all"):
        result = provider.parse_text(structured, {})
    assert len(result) == 1
    assert result[0]["value"] == 100.0
    assert result[0]["description"] == "shop"


def test_parse_text_ignores_metadata_only_structured_text():
    provider = DeepSeekProvider()
    structured = '''
    "Balance": "7,742.61 PLN",
    "status": "pending",
    "https": "//www.doz.pl/"
    '''
    with patch.object(DeepSeekProvider, "_chat", return_value="not json at all"):
        result = provider.parse_text(structured, {})
    assert result == []

# ── DeepSeekProvider.parse_image ──────────────────────────────────────────────

def test_parse_image_encodes_bytes_and_returns_list():
    provider = DeepSeekProvider()
    mock_resp = '[{"value":50,"currency":"PLN","type":"Expense","category":"Groceries","description":"receipt","person":""}]'
    with patch.object(DeepSeekProvider, "_chat", return_value=mock_resp) as mock_chat:
        result = provider.parse_image(b"FAKEIMAGE", lists={})
    assert isinstance(result, list)
    assert len(result) == 1
    mock_chat.assert_called_once()


def test_parse_image_malformed_raises():
    provider = DeepSeekProvider()
    with patch.object(DeepSeekProvider, "_chat", return_value="BAD"):
        with pytest.raises(ValueError):
            provider.parse_image(b"FAKEIMAGE", lists={})


# ── Prompt building ────────────────────────────────────────────────────────────

def test_quick_prompt_includes_categories():
    lists = {"categories": ["Groceries", "Transport"], "currencies": ["PLN"], "txn_types": ["Expense", "Income"]}
    prompt = _build_quick_prompt(lists)
    assert "Groceries" in prompt
    assert "Transport" in prompt


def test_quick_prompt_includes_currencies():
    lists = {"categories": ["Groceries", "Transport"], "currencies": ["PLN"], "txn_types": ["Expense", "Income"]}
    prompt = _build_quick_prompt(lists)
    assert "PLN" in prompt


def test_quick_prompt_includes_persons():
    lists = {"categories": ["Groceries", "Transport"], "currencies": ["PLN"], "txn_types": ["Expense", "Income"], "persons": ["Alice", "Bob"]}
    prompt = _build_quick_prompt(lists)
    assert "Alice" in prompt
    assert "Bob" in prompt
    assert "exact categories, types, and person names" in prompt.lower()


def test_quick_prompt_includes_date_instruction():
    prompt = _build_quick_prompt({"categories": ["Groceries"], "currencies": ["PLN"], "txn_types": ["Expense"]})
    assert "date" in prompt.lower()
    assert "yyyy-mm-dd" in prompt.lower()


def test_parse_prompt_includes_categories():
    lists = {"categories": ["Groceries", "Transport"], "currencies": ["PLN"], "txn_types": ["Expense", "Income"]}
    prompt = _build_parse_prompt(lists)
    assert "Groceries" in prompt


def test_parse_prompt_includes_statement_parsing_rules():
    prompt = _build_parse_prompt({"categories": ["Groceries"], "currencies": ["PLN"], "txn_types": ["Expense", "Income"]})
    assert "statement" in prompt.lower()
    assert "one transaction per block" in prompt.lower()
    assert "ignore balance rows" in prompt.lower()
    assert "negative amounts" in prompt.lower()
    assert "positive amounts" in prompt.lower()


def test_quick_prompt_empty_lists_uses_defaults():
    prompt = _build_quick_prompt({})
    assert "PLN" in prompt
    assert "Expense" in prompt


def test_parse_prompt_empty_lists_uses_defaults():
    prompt = _build_parse_prompt({})
    assert "PLN" in prompt


# ── Truncated-response salvage (root cause of July-08 bulk failures) ──────────

def _make_txn(i):
    return {
        "date": f"2026-07-{(i % 28) + 1:02d}", "value": 10.0 + i, "currency": "PLN",
        "type": "Expense", "category": "Groceries",
        "description": f"txn {i}", "person": "",
    }


def test_salvage_json_objects_from_truncated_array():
    from ai_parser import _salvage_json_objects
    full = json.dumps([_make_txn(i) for i in range(38)], indent=1)
    truncated = full[:int(len(full) * 0.9)]  # cut mid-array like max_tokens did
    salvaged = _salvage_json_objects(truncated)
    assert len(salvaged) >= 30
    assert all(isinstance(t, dict) and "value" in t for t in salvaged)


def test_salvage_ignores_braces_inside_strings():
    from ai_parser import _salvage_json_objects
    raw = '[{"description": "shop {weird} name", "value": 5}, {"value": 6'
    salvaged = _salvage_json_objects(raw)
    assert len(salvaged) == 1
    assert salvaged[0]["description"] == "shop {weird} name"


def test_parse_text_salvages_truncated_llm_response():
    provider = DeepSeekProvider()
    full = json.dumps([_make_txn(i) for i in range(38)])
    truncated = full[:int(len(full) * 0.9)]
    with patch.object(DeepSeekProvider, "_chat", return_value=truncated):
        result = provider.parse_text("statement text", {})
    assert len(result) >= 30


def test_parse_image_salvages_truncated_response():
    provider = DeepSeekProvider()
    full = json.dumps([_make_txn(i) for i in range(20)])
    truncated = full[:int(len(full) * 0.85)]
    with patch.object(DeepSeekProvider, "_chat", return_value=truncated):
        result = provider.parse_image(b"fakeimage", {})
    assert len(result) >= 10


# ── Statement chunking ─────────────────────────────────────────────────────────

def _fake_statement(n_days=20, blocks_per_day=4):
    lines = []
    for d in range(1, n_days + 1):
        lines.append(f"{d:02d}.06.2026, Monday")
        for b in range(blocks_per_day):
            lines += [
                "", "SHOP NAME", "PURCHASE - CARD PRESENT",
                f"4111XXXXXXXX1111 SHOP {d}-{b} CITY PL",
                f"-{10 + b}.99 PLN", f"Balance: {1000 - d}.00 PLN",
            ]
    return "\n".join(lines)


def test_chunker_returns_single_chunk_for_short_text():
    from ai_parser import _chunk_statement_text
    assert len(_chunk_statement_text("short text\n-5.00 PLN")) == 1


def test_chunker_splits_long_statement_at_date_headers():
    from ai_parser import _chunk_statement_text
    text = _fake_statement()
    chunks = _chunk_statement_text(text)
    assert len(chunks) > 1
    # every chunk after the first must start at a date-header line
    for c in chunks[1:]:
        first = c.splitlines()[0]
        assert first[0:2].isdigit(), f"chunk starts mid-block: {first!r}"
    # nothing lost
    assert sum(len(c.splitlines()) for c in chunks) >= len(text.splitlines())


def test_chunker_preserves_all_transaction_lines():
    from ai_parser import _chunk_statement_text
    text = _fake_statement()
    chunks = _chunk_statement_text(text)
    merged = "\n".join(chunks)
    for d in range(1, 21):
        for b in range(4):
            assert f"SHOP {d}-{b} CITY PL" in merged


def test_parse_text_chunks_large_input_and_merges():
    provider = DeepSeekProvider()
    text = _fake_statement()
    calls = []

    def fake_chat(self, messages, max_tokens=None):
        calls.append(messages[1]["content"])
        return json.dumps([_make_txn(len(calls))])

    with patch.object(DeepSeekProvider, "_chat", fake_chat):
        result = provider.parse_text(text, {})
    assert len(calls) > 1            # chunked → multiple API calls
    assert len(result) == len(calls) # merged one txn per chunk


def test_parse_text_small_input_single_call():
    provider = DeepSeekProvider()
    calls = []

    def fake_chat(self, messages, max_tokens=None):
        calls.append(1)
        return '[{"value": 5, "currency": "PLN", "type": "Expense", "category": "Groceries", "description": "x", "person": ""}]'

    with patch.object(DeepSeekProvider, "_chat", fake_chat):
        result = provider.parse_text("zabka 5", {})
    assert len(calls) == 1
    assert len(result) == 1
