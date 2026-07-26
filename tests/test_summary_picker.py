"""
tests/test_summary_picker.py — /summary picker UX.

Covers the five agreed items:
  1. free-form argument parsing, order-independent
  2. bare /summary → one message, three zones (flag on and off)
  3. bare month name resolves ledger-first when cycles are enabled
  4. range support — free-form and the From/To button walk
  5. year overflow paging (Earlier…)

No AI calls anywhere — everything is mocked.
"""

import os
import sys
from datetime import date
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pandas as pd
import pytest

os.environ.setdefault("STORAGE_BACKEND", "local")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "dummy")
os.environ.setdefault("ALLOWED_TELEGRAM_IDS", "123")

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import settings
from handlers.summary_picker import (
    build_cycle_keyboard,
    build_month_keyboard,
    build_summary_keyboard,
    build_year_keyboard,
    cycle_bounds,
    parse_summary_args,
)

TODAY = date(2026, 7, 26)

CYCLES = [
    (date(2026, 5, 24), "May 2026"),
    (date(2026, 6, 25), "Jun 2026"),
    (date(2026, 7, 23), "Jul 2026"),
]


# ── helpers ────────────────────────────────────────────────────────────────────

def make_update(user_id=123):
    upd = MagicMock()
    upd.effective_user.id = user_id
    upd.message.text = ""
    upd.message.reply_text = AsyncMock()
    return upd


def make_callback_update(data, user_id=123):
    upd = MagicMock()
    upd.effective_user.id = user_id
    upd.message = None
    upd.callback_query.data = data
    upd.callback_query.from_user.id = user_id
    upd.callback_query.answer = AsyncMock()
    upd.callback_query.message.reply_text = AsyncMock()
    upd.callback_query.message.edit_text = AsyncMock()
    return upd


def make_ctx(args=None):
    ctx = MagicMock()
    ctx.args = args or []
    ctx.user_data = {}
    return ctx


def _labels(keyboard):
    return [b.text for row in keyboard.inline_keyboard for b in row]


def _callbacks(keyboard):
    return [b.callback_data for row in keyboard.inline_keyboard for b in row]


def _sample_df():
    rows = []
    for year, month in [(2024, "Mar"), (2024, "Nov"), (2025, "Aug"), (2026, "Jun"), (2026, "Jul")]:
        rows.append({
            "Date": pd.Timestamp(year, {"Mar": 3, "Nov": 11, "Aug": 8, "Jun": 6, "Jul": 7}[month], 5),
            "Year": year, "Month": month, "Type": "Expense", "Category": "Groceries",
            "Value": 100.0, "_base": 100.0, "IsDone": True, "Currency": "PLN",
            "Description": "row",
        })
    return pd.DataFrame(rows)


def _patch_report_data(monkeypatch, df):
    import handlers.reports as reports
    monkeypatch.setattr(reports, "load_data", lambda: df)
    monkeypatch.setattr(reports, "load_rates", lambda: {"PLN": 1.0})
    monkeypatch.setattr(reports, "load_budgets", lambda: {})


# ── 1. free-form argument parsing, order-independent ──────────────────────────

class TestParseArgs:

    def test_month_then_year(self):
        assert parse_summary_args(["aug", "2025"], TODAY) == {"kind": "month", "year": 2025, "month": 8}

    def test_year_then_month(self):
        assert parse_summary_args(["2025", "aug"], TODAY) == {"kind": "month", "year": 2025, "month": 8}

    def test_dotted_numeric(self):
        assert parse_summary_args(["08.2025"], TODAY) == {"kind": "month", "year": 2025, "month": 8}

    def test_dotted_numeric_reversed(self):
        assert parse_summary_args(["2025.08"], TODAY) == {"kind": "month", "year": 2025, "month": 8}

    def test_full_month_name(self):
        assert parse_summary_args(["august", "2025"], TODAY) == {"kind": "month", "year": 2025, "month": 8}

    def test_bare_month_most_recent_occurrence(self):
        # today is Jul 2026 → bare 'aug' means Aug 2025
        assert parse_summary_args(["aug"], TODAY) == {"kind": "month", "year": 2025, "month": 8}

    def test_bare_month_earlier_in_year(self):
        assert parse_summary_args(["mar"], TODAY) == {"kind": "month", "year": 2026, "month": 3}

    def test_year_only_becomes_year_range(self):
        got = parse_summary_args(["2025"], TODAY)
        assert got["kind"] == "range"
        assert got["start"] == date(2025, 1, 1)
        assert got["end"] == date(2025, 12, 31)

    def test_current_year_range_capped_at_today(self):
        got = parse_summary_args(["2026"], TODAY)
        assert got["end"] == TODAY

    def test_garbage_returns_none(self):
        assert parse_summary_args(["banana"], TODAY) is None

    def test_two_months_returns_none(self):
        assert parse_summary_args(["aug", "sep"], TODAY) is None

    def test_empty_returns_none(self):
        assert parse_summary_args([], TODAY) is None


# ── 3. bare month name resolves ledger-first ──────────────────────────────────

class TestLedgerFirstResolution:

    def test_bare_month_hits_cycle_label(self):
        got = parse_summary_args(["jul"], TODAY, CYCLES)
        assert got == {"kind": "cycle", "start": date(2026, 7, 23), "end": TODAY, "label": "Jul 2026"}

    def test_closed_cycle_ends_day_before_next(self):
        got = parse_summary_args(["jun"], TODAY, CYCLES)
        assert got == {"kind": "cycle", "start": date(2026, 6, 25),
                       "end": date(2026, 7, 22), "label": "Jun 2026"}

    def test_no_matching_label_falls_back_to_calendar(self):
        got = parse_summary_args(["mar"], TODAY, CYCLES)
        assert got == {"kind": "month", "year": 2026, "month": 3}

    def test_explicit_year_bypasses_ledger(self):
        got = parse_summary_args(["jul", "2026"], TODAY, CYCLES)
        assert got == {"kind": "month", "year": 2026, "month": 7}

    def test_cycle_bounds_open_ended_for_newest(self):
        assert cycle_bounds(CYCLES, 2, TODAY) == (date(2026, 7, 23), TODAY)
        assert cycle_bounds(CYCLES, 0, TODAY) == (date(2026, 5, 24), date(2026, 6, 24))


# ── 4. range support, free-form ───────────────────────────────────────────────

class TestRangeParsing:

    def test_free_form_range(self):
        got = parse_summary_args(["aug", "2025", "-", "jan", "2026"], TODAY)
        assert got["kind"] == "range"
        assert got["start"] == date(2025, 8, 1)
        assert got["end"] == date(2026, 1, 31)

    def test_range_with_to_separator(self):
        got = parse_summary_args(["aug", "2025", "to", "jan", "2026"], TODAY)
        assert got["start"] == date(2025, 8, 1)
        assert got["end"] == date(2026, 1, 31)

    def test_range_bare_months(self):
        got = parse_summary_args(["mar", "-", "jun"], TODAY)
        assert got["start"] == date(2026, 3, 1)
        assert got["end"] == date(2026, 6, 30)

    def test_inverted_range_returns_none(self):
        assert parse_summary_args(["jan", "2026", "-", "aug", "2025"], TODAY) is None


# ── 2. three-zone keyboard structure ──────────────────────────────────────────

class TestSummaryKeyboard:

    def test_flag_off_quick_row_and_years(self):
        kb = build_summary_keyboard(False, [2026, 2025, 2024])
        labels = _labels(kb)
        assert labels[:2] == ["This month", "Last month"]
        assert "This cycle" not in labels and "💰 Cycle" not in labels
        assert {"2026", "2025", "2024"} <= set(labels)
        assert labels[-1] == "Range…"

    def test_flag_on_quick_row_and_choice(self):
        kb = build_summary_keyboard(True, [2026, 2025])
        labels = _labels(kb)
        assert labels[:4] == ["This cycle", "Last cycle", "This month", "Last month"]
        assert "📅 Calendar" in labels and "💰 Cycle" in labels
        assert "2026" not in labels  # years live behind Calendar when the flag is on
        assert labels[-1] == "Range…"

    def test_callback_data_scheme(self):
        kb = build_summary_keyboard(True, [2026])
        cbs = _callbacks(kb)
        assert {"sum:tc", "sum:lc", "sum:tm", "sum:lm", "sum:cal", "sum:cyc:0", "sum:rng"} <= set(cbs)

    def test_month_keyboard_only_months_with_data(self):
        kb = build_month_keyboard(2025, [3, 8])
        assert _callbacks(kb)[:2] == ["sum:m:2025:3", "sum:m:2025:8"]


# ── 5. year overflow paging ───────────────────────────────────────────────────

class TestYearPaging:

    YEARS = list(range(2026, 2014, -1))  # 12 years

    def test_first_page_has_eight_years_and_earlier(self):
        kb = build_year_keyboard(self.YEARS, page=0)
        labels = _labels(kb)
        assert "2026" in labels and "2019" in labels
        assert "2018" not in labels
        assert "Earlier…" in labels and "Newer…" not in labels

    def test_second_page_has_rest_and_newer(self):
        kb = build_year_keyboard(self.YEARS, page=1)
        labels = _labels(kb)
        assert "2018" in labels and "2015" in labels
        assert "Newer…" in labels and "Earlier…" not in labels

    def test_no_paging_when_years_fit(self):
        labels = _labels(build_year_keyboard([2026, 2025, 2024], page=0))
        assert "Earlier…" not in labels

    def test_cycle_list_pages_and_labels(self):
        many = [(date(2025, m, 1), f"{date(2025, m, 1):%b} 2025") for m in range(1, 11)]
        kb = build_cycle_keyboard(many, TODAY, page=0)
        labels = _labels(kb)
        assert labels[0].startswith("Oct 2025 (1 Oct – today)")
        assert "Earlier…" in labels
        kb2 = build_cycle_keyboard(many, TODAY, page=1)
        assert "Newer…" in _labels(kb2)

    def test_closed_cycle_label_shows_range(self):
        kb = build_cycle_keyboard(CYCLES, TODAY, page=0)
        labels = _labels(kb)
        assert "Jun 2026 (25 Jun – 22 Jul)" in labels


# ── handler flows ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestSummaryHandler:

    async def test_bare_summary_shows_picker(self, monkeypatch):
        from handlers.reports import cmd_summary
        monkeypatch.setattr(settings, "BUDGET_CYCLE", False)
        _patch_report_data(monkeypatch, _sample_df())
        upd = make_update()
        await cmd_summary(upd, make_ctx())
        kwargs = upd.message.reply_text.call_args.kwargs
        assert kwargs.get("reply_markup") is not None
        labels = _labels(kwargs["reply_markup"])
        assert "This month" in labels and "Range…" in labels

    async def test_typed_arg_renders_directly_no_buttons(self, monkeypatch):
        from handlers.reports import cmd_summary
        monkeypatch.setattr(settings, "BUDGET_CYCLE", False)
        _patch_report_data(monkeypatch, _sample_df())
        upd = make_update()
        await cmd_summary(upd, make_ctx(args=["aug", "2025"]))
        args, kwargs = upd.message.reply_text.call_args
        assert "Aug 2025 — Summary" in args[0]
        assert kwargs.get("reply_markup") is None

    async def test_typed_range_renders_range_report(self, monkeypatch):
        from handlers.reports import cmd_summary
        monkeypatch.setattr(settings, "BUDGET_CYCLE", False)
        _patch_report_data(monkeypatch, _sample_df())
        upd = make_update()
        await cmd_summary(upd, make_ctx(args=["aug", "2025", "-", "jul", "2026"]))
        assert "Range Report" in upd.message.reply_text.call_args[0][0]

    async def test_unparseable_arg_gives_hint(self, monkeypatch):
        from handlers.reports import cmd_summary
        monkeypatch.setattr(settings, "BUDGET_CYCLE", False)
        _patch_report_data(monkeypatch, _sample_df())
        upd = make_update()
        await cmd_summary(upd, make_ctx(args=["banana"]))
        assert "Could not understand" in upd.message.reply_text.call_args[0][0]

    async def test_past_month_report_has_no_projection(self, monkeypatch):
        from handlers.reports import handle_summary_callback
        _patch_report_data(monkeypatch, _sample_df())
        upd = make_callback_update("sum:m:2025:8")
        await handle_summary_callback(upd, make_ctx())
        text = upd.callback_query.message.reply_text.call_args[0][0]
        assert "Aug 2025 — Summary" in text
        assert "Projected" not in text

    async def test_calendar_button_shows_data_years_newest_first(self, monkeypatch):
        from handlers.reports import handle_summary_callback
        _patch_report_data(monkeypatch, _sample_df())
        upd = make_callback_update("sum:cal")
        await handle_summary_callback(upd, make_ctx())
        kb = upd.callback_query.message.edit_text.call_args.kwargs["reply_markup"]
        year_labels = [t for t in _labels(kb) if t.isdigit()]
        assert year_labels == ["2026", "2025", "2024"]

    async def test_year_button_shows_only_months_with_data(self, monkeypatch):
        from handlers.reports import handle_summary_callback
        _patch_report_data(monkeypatch, _sample_df())
        upd = make_callback_update("sum:y:2024")
        await handle_summary_callback(upd, make_ctx())
        kb = upd.callback_query.message.edit_text.call_args.kwargs["reply_markup"]
        cbs = _callbacks(kb)
        assert "sum:m:2024:3" in cbs and "sum:m:2024:11" in cbs
        assert "sum:m:2024:1" not in cbs

    async def test_range_button_walks_from_then_to(self, monkeypatch):
        from handlers.reports import handle_summary_callback
        _patch_report_data(monkeypatch, _sample_df())
        ctx = make_ctx()

        upd = make_callback_update("sum:rng")
        await handle_summary_callback(upd, ctx)
        assert ctx.user_data["sum_range"] == {"stage": "from"}
        assert "From" in upd.callback_query.message.edit_text.call_args[0][0]

        upd2 = make_callback_update("sum:m:2025:8")
        await handle_summary_callback(upd2, ctx)
        assert ctx.user_data["sum_range"] == {"stage": "to", "from": (2025, 8)}
        assert "To" in upd2.callback_query.message.edit_text.call_args[0][0]

        upd3 = make_callback_update("sum:m:2026:7")
        await handle_summary_callback(upd3, ctx)
        assert "sum_range" not in ctx.user_data
        text = upd3.callback_query.message.reply_text.call_args[0][0]
        assert "Range Report" in text
        assert "Aug 2025 – Jul 2026" in text

    async def test_cycle_button_lists_ledger(self, monkeypatch, excel_path=None):
        from handlers.reports import handle_summary_callback
        import handlers.reports as reports
        _patch_report_data(monkeypatch, _sample_df())
        monkeypatch.setattr("handlers.reports.load_cycles", lambda: CYCLES)
        upd = make_callback_update("sum:cyc:0")
        await handle_summary_callback(upd, make_ctx())
        kb = upd.callback_query.message.edit_text.call_args.kwargs["reply_markup"]
        cbs = _callbacks(kb)
        assert cbs[0] == "sum:cs:2026-07-23"  # newest first

    async def test_cycle_pick_renders_cycle_report(self, monkeypatch):
        from handlers.reports import handle_summary_callback
        _patch_report_data(monkeypatch, _sample_df())
        monkeypatch.setattr("handlers.reports.load_cycles", lambda: CYCLES)
        upd = make_callback_update("sum:cs:2026-06-25")
        await handle_summary_callback(upd, make_ctx())
        text = upd.callback_query.message.reply_text.call_args[0][0]
        assert "Cycle Jun 2026" in text

    async def test_last_cycle_button(self, monkeypatch):
        from handlers.reports import handle_summary_callback
        _patch_report_data(monkeypatch, _sample_df())
        monkeypatch.setattr("handlers.reports.load_cycles", lambda: CYCLES)
        upd = make_callback_update("sum:lc")
        await handle_summary_callback(upd, make_ctx())
        text = upd.callback_query.message.reply_text.call_args[0][0]
        assert "Cycle Jun 2026" in text
