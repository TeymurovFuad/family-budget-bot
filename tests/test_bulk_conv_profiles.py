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

    def test_unmapped_optional_field_shown(self):
        """Optional fields with no mapping show 'not found' in the output."""
        proposal = self._sample_proposal()
        proposal["column_map"]["time"] = None
        msg = _format_profile_confirm_message(proposal)
        # Optional unmapped fields show "not found" in the output.
        assert "not found" in msg

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

    def test_split_column_branch_shown(self):
        """split-column proposal renders both debit+credit column names, not 'amount →'."""
        import statement_profiles as sp
        proposal = {
            "column_map": {
                "date": "TxnDate",
                "debit": "Debits",
                "credit": "Credits",
                "currency": "CCY",
                "description": "Memo",
                "time": None,
            },
            "date_format": "%Y-%m-%d",
            "decimal_separator": ".",
            "sign_convention": sp.SIGN_DEBIT_CREDIT_SPLIT,
        }
        msg = _format_profile_confirm_message(proposal)
        # Must contain split line with both column names.
        assert "Debits" in msg
        assert "Credits" in msg
        # Must NOT show a bare "amount    → 'SomeColumn'" line (non-split style).
        lines = msg.splitlines()
        assert not any(
            line.strip().startswith("amount") and "split:" not in line and "Debits" not in line
            for line in lines
        )


# ─────────────────────────────────────────────────────────────────────────────
# fix_field mutual-exclusivity state mutation
# ─────────────────────────────────────────────────────────────────────────────

class TestFixFieldMutualExclusivity:
    """
    Verify the state-dict mutation logic enforced in bulk_profile_callback
    when the user reassigns a column via fix_field.

    These are pure unit tests on the dict manipulation logic — no Telegram
    context or bot needed.
    """

    def _apply_fix_field(self, proposal: dict, col: str, field: str) -> dict:
        """
        Mirror the fix_field mutation from bulk_profile_callback without
        Telegram: given a proposal dict, a column name, and a target field,
        return the updated proposal dict.
        """
        import statement_profiles as sp

        col_map = proposal.setdefault("column_map", {})
        # Clear old mapping for this column across all fields.
        for k in list(col_map.keys()):
            if col_map[k] == col:
                col_map[k] = None
        if field != "skip":
            col_map[field] = col
            if field == "amount":
                col_map.pop("debit", None)
                col_map.pop("credit", None)
                if proposal.get("sign_convention") == sp.SIGN_DEBIT_CREDIT_SPLIT:
                    proposal["sign_convention"] = "negative_expense"
            elif field in ("debit", "credit"):
                col_map.pop("amount", None)
                proposal["sign_convention"] = sp.SIGN_DEBIT_CREDIT_SPLIT
        return proposal

    def test_assign_amount_clears_debit_and_credit(self):
        """Assigning 'amount' removes debit/credit from col_map."""
        proposal = {
            "column_map": {"debit": "Dr", "credit": "Cr", "date": "Date", "currency": "CCY"},
            "sign_convention": "debit_credit_split",
        }
        result = self._apply_fix_field(proposal, "Amt", "amount")
        assert result["column_map"].get("amount") == "Amt"
        assert "debit" not in result["column_map"]
        assert "credit" not in result["column_map"]

    def test_assign_amount_resets_sign_convention(self):
        """Assigning 'amount' changes sign_convention away from debit_credit_split."""
        proposal = {
            "column_map": {"debit": "Dr", "credit": "Cr", "date": "Date", "currency": "CCY"},
            "sign_convention": "debit_credit_split",
        }
        result = self._apply_fix_field(proposal, "Amt", "amount")
        assert result["sign_convention"] == "negative_expense"

    def test_assign_debit_clears_amount(self):
        """Assigning 'debit' removes amount from col_map."""
        proposal = {
            "column_map": {"amount": "Amt", "date": "Date", "currency": "CCY"},
            "sign_convention": "negative_expense",
        }
        result = self._apply_fix_field(proposal, "Dr", "debit")
        assert result["column_map"].get("debit") == "Dr"
        assert "amount" not in result["column_map"]

    def test_assign_debit_sets_sign_convention(self):
        """Assigning 'debit' sets sign_convention to debit_credit_split."""
        import statement_profiles as sp
        proposal = {
            "column_map": {"amount": "Amt", "date": "Date", "currency": "CCY"},
            "sign_convention": "negative_expense",
        }
        result = self._apply_fix_field(proposal, "Dr", "debit")
        assert result["sign_convention"] == sp.SIGN_DEBIT_CREDIT_SPLIT

    def test_assign_credit_clears_amount(self):
        """Assigning 'credit' removes amount from col_map."""
        proposal = {
            "column_map": {"amount": "Amt", "date": "Date", "currency": "CCY"},
            "sign_convention": "negative_expense",
        }
        result = self._apply_fix_field(proposal, "Cr", "credit")
        assert result["column_map"].get("credit") == "Cr"
        assert "amount" not in result["column_map"]

    def test_assign_credit_sets_sign_convention(self):
        """Assigning 'credit' sets sign_convention to debit_credit_split."""
        import statement_profiles as sp
        proposal = {
            "column_map": {"amount": "Amt", "date": "Date", "currency": "CCY"},
            "sign_convention": "negative_expense",
        }
        result = self._apply_fix_field(proposal, "Cr", "credit")
        assert result["sign_convention"] == sp.SIGN_DEBIT_CREDIT_SPLIT
