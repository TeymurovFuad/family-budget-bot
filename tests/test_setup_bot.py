"""tests/test_setup_bot.py — unit tests for the pure helpers in scripts/setup_bot.py.

The interactive flow is covered by monkeypatching input(); subprocess-heavy
steps (venv creation, pip, systemd) are not exercised here.
"""

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

import setup_bot


# ── parse_env_file ────────────────────────────────────────────────────────────

class TestParseEnvFile:
    def test_basic_pairs(self):
        text = "A=1\nB=hello world\n"
        assert setup_bot.parse_env_file(text) == {"A": "1", "B": "hello world"}

    def test_ignores_comments_and_blanks(self):
        text = "# comment\n\nA=1\n   \n# another\n"
        assert setup_bot.parse_env_file(text) == {"A": "1"}

    def test_strips_quotes(self):
        text = "A=\"quoted\"\nB='single'\n"
        parsed = setup_bot.parse_env_file(text)
        assert parsed == {"A": "quoted", "B": "single"}

    def test_strips_inline_comment_on_unquoted_value(self):
        text = "AI_PROVIDER=deepseek          # currently the only provider\n"
        assert setup_bot.parse_env_file(text) == {"AI_PROVIDER": "deepseek"}

    def test_value_with_equals_sign(self):
        text = "URL=https://x.example/?a=1&b=2\n"
        assert setup_bot.parse_env_file(text)["URL"] == "https://x.example/?a=1&b=2"

    def test_ignores_lines_without_equals(self):
        assert setup_bot.parse_env_file("not a pair\nA=1\n") == {"A": "1"}

    def test_empty_value_kept(self):
        assert setup_bot.parse_env_file("DEEPSEEK_API_KEY=\n") == {"DEEPSEEK_API_KEY": ""}


# ── merge_env ─────────────────────────────────────────────────────────────────

class TestMergeEnv:
    def test_existing_real_value_wins(self):
        merged = setup_bot.merge_env({"A": "real"}, {"A": "new"})
        assert merged["A"] == "real"

    def test_empty_existing_filled(self):
        merged = setup_bot.merge_env({"A": ""}, {"A": "new"})
        assert merged["A"] == "new"

    def test_placeholder_existing_replaced(self):
        merged = setup_bot.merge_env(
            {"TELEGRAM_BOT_TOKEN": "your_bot_token_here"},
            {"TELEGRAM_BOT_TOKEN": "123:abc"},
        )
        assert merged["TELEGRAM_BOT_TOKEN"] == "123:abc"

    def test_new_keys_added(self):
        merged = setup_bot.merge_env({"A": "1"}, {"B": "2"})
        assert merged == {"A": "1", "B": "2"}


# ── mask_secret ───────────────────────────────────────────────────────────────

class TestMaskSecret:
    def test_empty(self):
        assert setup_bot.mask_secret("") == "(empty)"

    def test_short_fully_masked(self):
        assert setup_bot.mask_secret("abcd") == "****"

    def test_long_masks_middle(self):
        masked = setup_bot.mask_secret("1234567890abcdef")
        assert masked == "1234******cdef"
        assert "567890ab" not in masked


# ── render_env ────────────────────────────────────────────────────────────────

class TestRenderEnv:
    def test_round_trip(self):
        values = {"A": "1", "B": "hello", "C": ""}
        assert setup_bot.parse_env_file(setup_bot.render_env(values)) == values

    def test_trailing_newline(self):
        assert setup_bot.render_env({"A": "1"}).endswith("\n")


# ── is_placeholder ────────────────────────────────────────────────────────────

class TestIsPlaceholder:
    @pytest.mark.parametrize("value", ["", "  ", "your_bot_token_here",
                                       "YOUR_TELEGRAM_ID_HERE", "<token>", "changeme"])
    def test_placeholders(self, value):
        assert setup_bot.is_placeholder(value)

    @pytest.mark.parametrize("value", ["123:abc", "local", "Europe/Warsaw", "0.20"])
    def test_real_values(self, value):
        assert not setup_bot.is_placeholder(value)


# ── collect_config (interactive flow, monkeypatched input) ───────────────────

class TestCollectConfig:
    def test_prompts_only_for_gaps(self, monkeypatch):
        answers = iter([
            "123:abc",        # TELEGRAM_BOT_TOKEN
            "",               # ALLOWED_TELEGRAM_IDS — rejected (required)
            "42",             # ALLOWED_TELEGRAM_IDS retry
            "",               # DeepSeek key — skipped
            "",               # TIMEZONE default
            "USD",            # DISPLAY_CURRENCY
            "",               # STORAGE_BACKEND default
            "",               # XLSX_PATH default
        ])
        monkeypatch.setattr("builtins.input", lambda _: next(answers))
        values = setup_bot.collect_config({"TELEGRAM_BOT_TOKEN": "your_bot_token_here"})
        assert values["TELEGRAM_BOT_TOKEN"] == "123:abc"
        assert values["ALLOWED_TELEGRAM_IDS"] == "42"
        assert values["DEEPSEEK_API_KEY"] == ""
        assert values["TIMEZONE"] == "Europe/Warsaw"
        assert values["DISPLAY_CURRENCY"] == "USD"
        assert values["STORAGE_BACKEND"] == "local"
        assert values["XLSX_PATH"] == "data/Expenses_Improved.xlsx"

    def test_existing_values_not_prompted(self, monkeypatch):
        existing = {
            "TELEGRAM_BOT_TOKEN": "123:abc",
            "ALLOWED_TELEGRAM_IDS": "42",
            "DEEPSEEK_API_KEY": "sk-x1234567890",
            "TIMEZONE": "UTC",
            "DISPLAY_CURRENCY": "EUR",
            "STORAGE_BACKEND": "s3",
            "XLSX_PATH": "data/x.xlsx",
        }

        def fail(_):
            raise AssertionError("input() should not be called")

        monkeypatch.setattr("builtins.input", fail)
        assert setup_bot.collect_config(existing) == existing
