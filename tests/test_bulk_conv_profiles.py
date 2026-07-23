"""
tests/test_bulk_conv_profiles.py — unit tests for the pure utility functions
in handlers/bulk_conv.py that support the bank-statement profile feature.

All tests are offline: no Telegram, no network, no live AI calls.
No bank names appear in this file — fixtures use generic column labels.
"""

import io
import json

import pytest

from handlers.bulk_conv import (
    _is_statement_file,
    _read_statement_headers_and_sniff,
    _get_sample_rows,
    _format_profile_confirm_message,
)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _csv_bytes(rows: list[str], delimiter: str = ";") -> bytes:
    return ("\n".join(rows)).encode("utf-8")


def _make_xlsx_bytes(headers: list[str], rows: list[list]) -> bytes:
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(headers)
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ─────────────────────────────────────────────────────────────────────────────
# _is_statement_file
# ─────────────────────────────────────────────────────────────────────────────

class TestIsStatementFile:
    def test_csv(self):
        assert _is_statement_file("export.csv") is True

    def test_xlsx(self):
        assert _is_statement_file("bank_statement.xlsx") is True

    def test_xls(self):
        assert _is_statement_file("old_format.xls") is True

    def test_txt(self):
        assert _is_statement_file("statement.txt") is True

    def test_photo_jpg(self):
        assert _is_statement_file("receipt.jpg") is False

    def test_photo_png(self):
        assert _is_statement_file("scan.png") is False

    def test_pdf(self):
        assert _is_statement_file("report.pdf") is False

    def test_case_insensitive(self):
        assert _is_statement_file("EXPORT.CSV") is True

    def test_no_extension(self):
        assert _is_statement_file("noextension") is False


# ─────────────────────────────────────────────────────────────────────────────
# _read_statement_headers_and_sniff
# ─────────────────────────────────────────────────────────────────────────────

class TestReadStatementHeadersAndSniff:
    def test_read_headers_csv_semicolon(self):
        """Semicolon-delimited CSV — headers extracted, no provisional profile."""
        content = "TransDate;Amount;CCY;Info\n12.03.2026;-45,99;PLN;Coffee\n13.03.2026;10,00;EUR;Salary"
        headers, provisional = _read_statement_headers_and_sniff(content.encode("utf-8"), "export.csv")
        assert headers == ["TransDate", "Amount", "CCY", "Info"]
        # CSV returns None for provisional — profile matching is done by caller.
        assert provisional is None

    def test_read_headers_csv_comma(self):
        """Comma-delimited CSV."""
        content = "Date,Value,Currency\n2026-01-01,10.00,PLN\n2026-01-02,20.00,EUR"
        headers, provisional = _read_statement_headers_and_sniff(content.encode("utf-8"), "export.csv")
        assert headers == ["Date", "Value", "Currency"]
        assert provisional is None

    def test_read_headers_xlsx(self):
        """XLSX — reads first row as headers, no provisional profile."""
        xlsx_bytes = _make_xlsx_bytes(
            ["TransDate", "Amount", "CCY", "Info"],
            [["15.06.2026", -50.0, "PLN", "Transport"]],
        )
        headers, provisional = _read_statement_headers_and_sniff(xlsx_bytes, "export.xlsx")
        assert headers == ["TransDate", "Amount", "CCY", "Info"]
        assert provisional is None

    def test_read_headers_txt_sniffed(self):
        """Tab-delimited .txt — sniffed as CSV, provisional profile returned."""
        content = "Date\tAmount\tCCY\n2026-01-01\t10.00\tPLN\n2026-01-02\t20.00\tEUR"
        headers, provisional = _read_statement_headers_and_sniff(content.encode("utf-8"), "statement.txt")
        assert headers == ["Date", "Amount", "CCY"]
        # provisional profile is returned for .txt with a detected delimiter.
        assert provisional is not None
        assert provisional["delimiter"] == "\t"
        assert "column_map" in provisional

    def test_read_headers_txt_no_sniff(self):
        """Plain-text receipt with no consistent delimiter — returns ([], None)."""
        content = (
            "RECEIPT\n"
            "Coffee 4.50\n"
            "Tax incl.\n"
            "Thank you for your visit\n"
        )
        headers, provisional = _read_statement_headers_and_sniff(content.encode("utf-8"), "receipt.txt")
        assert headers == []
        assert provisional is None


# ─────────────────────────────────────────────────────────────────────────────
# _get_sample_rows
# ─────────────────────────────────────────────────────────────────────────────

class TestGetSampleRows:
    def test_get_sample_rows_csv(self):
        """CSV bytes — returns up to 3 data rows, header excluded."""
        content = (
            "Date;Amount;CCY;Info\n"
            "2026-01-01;-10,00;PLN;Coffee\n"
            "2026-01-02;-20,00;PLN;Lunch\n"
            "2026-01-03;-30,00;EUR;Dinner\n"
            "2026-01-04;-40,00;PLN;Taxi\n"
        )
        rows = _get_sample_rows(content.encode("utf-8"), "export.csv", delimiter=";")
        assert len(rows) == 3  # capped at n=3
        assert rows[0][0] == "2026-01-01"
        assert rows[0][1] == "-10,00"
        assert rows[2][0] == "2026-01-03"

    def test_get_sample_rows_csv_fewer_than_n(self):
        """CSV with only 2 data rows — returns all 2."""
        content = "Date;Amount\n2026-01-01;-10,00\n2026-01-02;-20,00\n"
        rows = _get_sample_rows(content.encode("utf-8"), "export.csv", delimiter=";")
        assert len(rows) == 2

    def test_get_sample_rows_xlsx(self):
        """XLSX bytes — returns up to 3 data rows, header excluded."""
        xlsx_bytes = _make_xlsx_bytes(
            ["TransDate", "Amount", "CCY", "Info"],
            [
                ["2026-01-01", -10.0, "PLN", "Coffee"],
                ["2026-01-02", -20.0, "PLN", "Lunch"],
                ["2026-01-03", -30.0, "EUR", "Dinner"],
                ["2026-01-04", -40.0, "PLN", "Taxi"],
            ],
        )
        rows = _get_sample_rows(xlsx_bytes, "export.xlsx")
        assert len(rows) == 3  # capped at n=3
        # Values are coerced to strings; the date and description cells are present.
        assert rows[0][0] == "2026-01-01"
        assert rows[0][3] == "Coffee"
        assert rows[2][3] == "Dinner"

    def test_get_sample_rows_xlsx_empty_returns_empty(self):
        """XLSX with only a header row — returns []."""
        xlsx_bytes = _make_xlsx_bytes(["TransDate", "Amount"], [])
        rows = _get_sample_rows(xlsx_bytes, "export.xlsx")
        assert rows == []


# ─────────────────────────────────────────────────────────────────────────────
# _format_profile_confirm_message
# ─────────────────────────────────────────────────────────────────────────────

class TestFormatProfileConfirmMessage:
    def _sample_proposal(self) -> dict:
        return {
            "column_map": {
                "date": "TransDate",
                "amount": "Amount",
                "currency": "CCY",
                "description": "Info",
                "time": None,
            },
            "date_format": "%d.%m.%Y",
            "decimal_separator": ",",
            "sign_convention": "negative_expense",
        }

    def test_contains_date_field(self):
        msg = _format_profile_confirm_message(self._sample_proposal())
        assert "date" in msg

    def test_contains_amount_field(self):
        msg = _format_profile_confirm_message(self._sample_proposal())
        assert "amount" in msg

    def test_contains_date_format(self):
        msg = _format_profile_confirm_message(self._sample_proposal())
        assert "%d.%m.%Y" in msg

    def test_contains_decimal_separator_word(self):
        msg = _format_profile_confirm_message(self._sample_proposal())
        # decimal_separator "," → rendered as "comma"
        assert "comma" in msg

    def test_contains_sign_convention(self):
        msg = _format_profile_confirm_message(self._sample_proposal())
        assert "negative" in msg.lower()

    def test_unmapped_field_shown(self):
        """Fields with no column mapping show '(not mapped)'."""
        proposal = self._sample_proposal()
        proposal["column_map"]["time"] = None
        msg = _format_profile_confirm_message(proposal)
        assert "not mapped" in msg

    def test_header_line_present(self):
        msg = _format_profile_confirm_message(self._sample_proposal())
        assert "New statement format" in msg

    def test_mapped_column_name_shown(self):
        msg = _format_profile_confirm_message(self._sample_proposal())
        assert "TransDate" in msg
        assert "Amount" in msg

    def test_empty_proposal_does_not_raise(self):
        """Empty/partial proposal must not raise — produces safe fallback text."""
        msg = _format_profile_confirm_message({})
        assert isinstance(msg, str)
        assert len(msg) > 0
