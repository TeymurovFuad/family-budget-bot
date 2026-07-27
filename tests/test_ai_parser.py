"""
test_ai_parser.py — exhaustive unit tests for ai_parser module.
Covers _strip_fences, DeepSeekProvider.parse_quick/parse_text/parse_image,
and the prompt-building helpers.
"""

import json
import pytest
from unittest.mock import patch

from ai_parser import (
    _strip_fences,
    DeepSeekProvider,
    _build_reference_block,
    _decode_positional_array,
    _normalize_ai_rows,
    _salvage_json_arrays,
    _PARSE_SYSTEM_PROMPT,
    _QUICK_SYSTEM_PROMPT,
)


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


# ── Prompt building (prompt-caching restructure) ──────────────────────────────

def test_reference_block_includes_categories():
    lists = {"categories": ["Groceries", "Transport"], "currencies": ["PLN"], "txn_types": ["Expense", "Income"]}
    block = _build_reference_block(lists)
    assert "Groceries" in block
    assert "Transport" in block


def test_reference_block_includes_currencies_and_default():
    lists = {"categories": ["Groceries"], "currencies": ["GEL", "EUR"], "txn_types": ["Expense"]}
    block = _build_reference_block(lists)
    assert "GEL" in block and "EUR" in block
    assert "Default currency: GEL" in block


def test_reference_block_empty_lists_uses_defaults():
    block = _build_reference_block({})
    assert "PLN" in block
    assert "Expense" in block


def test_system_prompts_have_no_dynamic_reference_data():
    # byte-identical for prompt cache — no per-user category/currency lists.
    for prompt in (_PARSE_SYSTEM_PROMPT, _QUICK_SYSTEM_PROMPT):
        assert "Reference data for this request" in prompt


def test_quick_system_prompt_omits_persons():
    # Person field retired — the prompt must not mention household persons.
    assert "person" not in _QUICK_SYSTEM_PROMPT.lower()


def test_quick_system_prompt_includes_date_instruction():
    assert "date" in _QUICK_SYSTEM_PROMPT.lower()
    assert "yyyy-mm-dd" in _QUICK_SYSTEM_PROMPT.lower()


def test_parse_system_prompt_requests_positional_arrays():
    assert "[date, amount, currency, category, description, type, is_recurring]" in _PARSE_SYSTEM_PROMPT


def test_parse_system_prompt_includes_statement_parsing_rules():
    prompt = _PARSE_SYSTEM_PROMPT
    assert "statement" in prompt.lower()
    assert "one transaction per block" in prompt.lower()
    assert "ignore balance rows" in prompt.lower()
    assert "negative amounts" in prompt.lower()
    assert "positive amounts" in prompt.lower()


def test_system_prompt_byte_identical_across_calls():
    """Different reference lists must never change the system prompt bytes."""
    provider = DeepSeekProvider()
    captured = []

    def fake_chat(self, messages, max_tokens=None):
        captured.append(messages[0]["content"])
        return "[]"

    with patch.object(DeepSeekProvider, "_chat", fake_chat):
        provider.parse_text("x 5", {"categories": ["Groceries"]})
        provider.parse_text("y 7", {"categories": ["Zoo", "Rent"], "currencies": ["GEL"]})
    assert captured[0] == captured[1] == _PARSE_SYSTEM_PROMPT


def test_dynamic_reference_data_lands_in_user_message():
    provider = DeepSeekProvider()
    captured = []

    def fake_chat(self, messages, max_tokens=None):
        captured.append(messages[1]["content"])
        return "[]"

    with patch.object(DeepSeekProvider, "_chat", fake_chat):
        provider.parse_text("shop 5", {"categories": ["Groceries"]})
    assert "Groceries" in captured[0]
    assert captured[0].startswith("shop 5")
    assert captured[0].rstrip().endswith("Allowed categories: Groceries")


# ── Positional-array output format (compact AI format) ───────────────────────

def test_decode_positional_array_maps_all_fields():
    row = _decode_positional_array(
        ["2026-05-19", 23.0, "EUR", "Groceries", "Lidl", "Expense", True])
    assert row == {
        "date": "2026-05-19", "value": 23.0, "currency": "EUR",
        "category": "Groceries", "description": "Lidl", "type": "Expense",
        "is_recurring": True,
    }


def test_decode_positional_array_short_row_partial_fields():
    row = _decode_positional_array(["2026-05-19", 23.0, "EUR"])
    assert row == {"date": "2026-05-19", "value": 23.0, "currency": "EUR"}


def test_decode_positional_array_extra_positions_ignored():
    row = _decode_positional_array(
        ["2026-05-19", 1, "EUR", "Other", "x", "Expense", False, "junk", 42])
    assert "junk" not in row.values() or len(row) == 7
    assert set(row) == {"date", "value", "currency", "category", "description",
                        "type", "is_recurring"}


@pytest.mark.parametrize("bad", [None, "string", 42, {}, [], ["only-date"]])
def test_decode_positional_array_rejects_malformed(bad):
    assert _decode_positional_array(bad) is None


def test_normalize_ai_rows_mixed_formats():
    items = [
        {"date": "2026-05-19", "value": 5},            # legacy dict — kept
        ["2026-05-20", 7, "EUR"],                      # array — decoded
        "garbage", 42, None,                            # dropped
    ]
    rows = _normalize_ai_rows(items)
    assert len(rows) == 2
    assert rows[1]["value"] == 7


def test_parse_text_accepts_positional_array_response():
    provider = DeepSeekProvider()
    mock_resp = '[["2026-05-19", 89, "PLN", "Groceries", "shop", "Expense", false]]'
    with patch.object(DeepSeekProvider, "_chat", return_value=mock_resp):
        result = provider.parse_text("shop 89", {})
    assert result == [{
        "date": "2026-05-19", "value": 89, "currency": "PLN",
        "category": "Groceries", "description": "shop", "type": "Expense",
        "is_recurring": False,
    }]


def test_parse_text_still_accepts_dict_response():
    # Backward compat during rollout — dict elements pass through unchanged.
    provider = DeepSeekProvider()
    mock_resp = '[{"date": "2026-05-19", "value": 89, "currency": "PLN", "type": "Expense", "category": "Groceries", "description": "shop"}]'
    with patch.object(DeepSeekProvider, "_chat", return_value=mock_resp):
        result = provider.parse_text("shop 89", {})
    assert len(result) == 1 and result[0]["value"] == 89


def test_parse_image_accepts_positional_array_response():
    provider = DeepSeekProvider()
    mock_resp = '[["2026-05-19", 50, "PLN", "Groceries", "receipt", "Expense", false]]'
    with patch.object(DeepSeekProvider, "_chat", return_value=mock_resp):
        result = provider.parse_image(b"FAKEIMAGE", lists={})
    assert len(result) == 1 and result[0]["description"] == "receipt"


def test_parse_text_malformed_array_elements_dropped_not_fatal():
    provider = DeepSeekProvider()
    mock_resp = '[["2026-05-19", 89, "PLN", "Groceries", "shop", "Expense", false], ["x"], 42]'
    with patch.object(DeepSeekProvider, "_chat", return_value=mock_resp):
        result = provider.parse_text("shop 89", {})
    assert len(result) == 1


def test_salvage_json_arrays_from_truncated_response():
    full = json.dumps([
        ["2026-05-19", 10.0 + i, "PLN", "Groceries", f"txn {i}", "Expense", False]
        for i in range(30)
    ])
    truncated = full[:int(len(full) * 0.9)]  # cut mid-array
    salvaged = _salvage_json_arrays(truncated)
    assert len(salvaged) >= 20
    assert all(r["date"] == "2026-05-19" for r in salvaged)


def test_salvage_json_arrays_ignores_numeric_arrays_in_objects():
    raw = '[{"description": "shop", "amounts": [1, 2, 3]}, {"value": 6'
    assert _salvage_json_arrays(raw) == []


def test_parse_text_salvages_truncated_array_response():
    provider = DeepSeekProvider()
    full = json.dumps([
        ["2026-05-19", 10.0 + i, "PLN", "Groceries", f"txn {i}", "Expense", False]
        for i in range(30)
    ])
    truncated = full[:int(len(full) * 0.9)]
    with patch.object(DeepSeekProvider, "_chat", return_value=truncated):
        result = provider.parse_text("statement text", {})
    assert len(result) >= 20
    assert all("value" in r for r in result)


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
