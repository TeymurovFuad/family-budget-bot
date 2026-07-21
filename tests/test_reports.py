"""
test_reports.py — tests for helpers extracted from handlers/reports.py.

Tests cover:
  1. /report pagination chunking logic
  2. _build_savings_chart returns a BytesIO PNG buffer
  3. _bar_color color-assignment logic
"""

import io
import sys
import os

import pytest

# Ensure the project root is on the path so we can import handlers.reports
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from handlers.reports import _bar_color, _build_savings_chart


# ── Pagination logic (duplicated here to test standalone) ────────────────────

def _chunk_text(report_text: str, max_size: int = 4000) -> list[str]:
    """Pure function version of the pagination logic in cmd_report."""
    if len(report_text) <= max_size:
        return [report_text]
    chunks = []
    current = ""
    for line in report_text.split("\n"):
        if len(current) + len(line) + 1 > max_size:
            chunks.append(current)
            current = line
        else:
            current += ("\n" if current else "") + line
    if current:
        chunks.append(current)
    return chunks


class TestReportPagination:

    def test_short_report_returns_single_chunk(self):
        text = "line\n" * 10
        chunks = _chunk_text(text)
        assert len(chunks) == 1

    def test_report_pagination_splits_at_4000(self):
        # Build a text clearly over 4000 chars using short lines
        line = "x" * 99  # 99 chars + newline = 100 per line
        report_text = "\n".join([line] * 50)  # 50 * 100 - 1 = 4,999 chars
        assert len(report_text) > 4000

        chunks = _chunk_text(report_text)

        assert len(chunks) > 1, "Expected more than one chunk for a >4000 char report"
        for chunk in chunks:
            assert len(chunk) <= 4000, f"Chunk too long: {len(chunk)}"

    def test_no_line_split_mid_way(self):
        # Each line is unique — verify every line appears intact in exactly one chunk
        lines = [f"Line number {i:04d} content here" for i in range(200)]
        report_text = "\n".join(lines)
        chunks = _chunk_text(report_text)

        all_lines_in_chunks = []
        for chunk in chunks:
            all_lines_in_chunks.extend(chunk.split("\n"))

        for line in lines:
            assert line in all_lines_in_chunks, f"Line missing or split: {line!r}"

    def test_empty_string_returns_single_empty_chunk(self):
        chunks = _chunk_text("")
        assert chunks == [""]

    def test_exactly_4000_chars_is_single_chunk(self):
        # 4000 chars with no newlines
        text = "a" * 4000
        chunks = _chunk_text(text)
        assert len(chunks) == 1


# ── _build_savings_chart ─────────────────────────────────────────────────────

class TestBuildSavingsChart:

    def test_savings_chart_returns_bytesio(self):
        months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun"]
        rates  = [15.0, 18.0, 12.0, 22.0, 20.0, 25.0]
        buf = _build_savings_chart(months, rates)
        assert isinstance(buf, io.BytesIO)

    def test_savings_chart_buffer_has_data(self):
        months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun"]
        rates  = [15.0, 18.0, 12.0, 22.0, 20.0, 25.0]
        buf = _build_savings_chart(months, rates)
        # Buffer position should be at 0 (seeked back) but tell() is also 0 after seek(0)
        # Check size by seeking to end
        buf.seek(0, 2)
        size = buf.tell()
        assert size > 0, "Expected non-empty PNG buffer"

    def test_savings_chart_all_zeros(self):
        months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun"]
        rates  = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
        buf = _build_savings_chart(months, rates)
        assert isinstance(buf, io.BytesIO)
        buf.seek(0, 2)
        assert buf.tell() > 0

    def test_savings_chart_starts_at_position_zero(self):
        """Buffer must be seeked to 0 so Telegram can read it from the start."""
        months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun"]
        rates  = [10.0] * 6
        buf = _build_savings_chart(months, rates)
        assert buf.tell() == 0


# ── _bar_color ────────────────────────────────────────────────────────────────

class TestBarColor:

    def test_zero_spend_green(self):
        assert _bar_color(0, 100) == "#4CAF50"

    def test_exactly_80_percent_green(self):
        assert _bar_color(80, 100) == "#4CAF50"

    def test_just_over_80_percent_orange(self):
        assert _bar_color(81, 100) == "#FF9800"

    def test_exactly_100_percent_orange(self):
        assert _bar_color(100, 100) == "#FF9800"

    def test_over_100_percent_red(self):
        assert _bar_color(101, 100) == "#F44336"

    def test_no_budget_grey(self):
        assert _bar_color(50, 0) == "#9E9E9E"

    def test_large_overspend_red(self):
        assert _bar_color(500, 100) == "#F44336"

    def test_no_budget_zero_spend_grey(self):
        assert _bar_color(0, 0) == "#9E9E9E"
