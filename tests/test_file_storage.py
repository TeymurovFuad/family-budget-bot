"""
test_file_storage.py — tests for file_storage.py helper functions.

All tests use the `excel_path` fixture which provides a fresh blank Excel
in a temp directory with file_storage.LOCAL_XLSX_PATH already monkeypatched.
"""

import json

import openpyxl
import pytest

import file_storage
from file_storage import (
    create_blank_excel,
    get_excel_path_for_reading,
    load_lists,
    load_budgets_from_excel,
    get_recent_transactions,
    load_user_prefs,
    save_user_prefs,
)


# ── create_blank_excel ────────────────────────────────────────────────────────


class TestCreateBlankExcel:

    def test_file_is_created(self, excel_path):
        assert excel_path.exists()

    def test_has_masterdata_sheet(self, excel_path):
        wb = openpyxl.load_workbook(excel_path)
        assert "MasterData" in wb.sheetnames

    def test_has_lists_sheet(self, excel_path):
        wb = openpyxl.load_workbook(excel_path)
        assert "Lists" in wb.sheetnames

    def test_has_dashboard_sheet(self, excel_path):
        wb = openpyxl.load_workbook(excel_path)
        assert "Dashboard" in wb.sheetnames

    def test_masterdata_has_13_headers(self, excel_path):
        wb = openpyxl.load_workbook(excel_path)
        ws = wb["MasterData"]
        headers = [ws.cell(1, c).value for c in range(1, 14)]
        assert len([h for h in headers if h is not None]) == 13

    def test_masterdata_header_names(self, excel_path):
        wb = openpyxl.load_workbook(excel_path)
        ws = wb["MasterData"]
        expected = [
            "Date", "Year", "Month", "Value", "Type", "Category",
            "Person", "Description", "IsRecurring", "IsDone",
            "Currency", "Value (base)", "Date Modified (UTC)",
        ]
        actual = [ws.cell(1, c).value for c in range(1, 14)]
        assert actual == expected

    def test_lists_sheet_has_month_header_in_col_a(self, excel_path):
        wb = openpyxl.load_workbook(excel_path)
        ws = wb["Lists"]
        assert ws.cell(1, 1).value == "Months"

    def test_lists_sheet_has_category_header_in_col_c(self, excel_path):
        wb = openpyxl.load_workbook(excel_path)
        ws = wb["Lists"]
        assert ws.cell(1, 3).value == "Categories"

    def test_lists_sheet_has_currency_header_in_col_h(self, excel_path):
        wb = openpyxl.load_workbook(excel_path)
        ws = wb["Lists"]
        assert ws.cell(1, 8).value == "Currency"

    def test_lists_sheet_has_rate_header_in_col_i(self, excel_path):
        wb = openpyxl.load_workbook(excel_path)
        ws = wb["Lists"]
        assert ws.cell(1, 9).value == "Rate to base"

    def test_lists_sheet_has_budget_header_in_col_d(self, excel_path):
        wb = openpyxl.load_workbook(excel_path)
        ws = wb["Lists"]
        assert ws.cell(1, 4).value == "Budget (base)"

    def test_lists_sheet_col_g_is_empty(self, excel_path):
        wb = openpyxl.load_workbook(excel_path)
        ws = wb["Lists"]
        assert ws.cell(1, 7).value is None

    def test_lists_sheet_months_start_with_jan(self, excel_path):
        wb = openpyxl.load_workbook(excel_path)
        ws = wb["Lists"]
        assert ws.cell(2, 1).value == "Jan"

    def test_lists_sheet_months_end_with_dec(self, excel_path):
        wb = openpyxl.load_workbook(excel_path)
        ws = wb["Lists"]
        assert ws.cell(13, 1).value == "Dec"

    def test_lists_sheet_budget_column_is_blank_by_default(self, excel_path):
        # Budget (base) col is present but unpopulated — user fills in limits
        wb = openpyxl.load_workbook(excel_path)
        ws = wb["Lists"]
        for c in range(1, ws.max_column + 1):
            if "budget" in str(ws.cell(1, c).value or "").lower():
                for row in range(2, ws.max_row + 1):
                    assert ws.cell(row, c).value is None, f"Budget col row {row} should be blank"
                break

    def test_pln_rate_is_1(self, excel_path):
        wb = openpyxl.load_workbook(excel_path)
        ws = wb["Lists"]
        found = False
        for row in range(2, ws.max_row + 1):
            if ws.cell(row, 8).value == "PLN":
                assert ws.cell(row, 9).value == 1.0
                found = True
                break
        assert found, "PLN not found in Lists currencies"


# ── get_excel_path_for_reading ────────────────────────────────────────────────


class TestGetExcelPathForReading:

    def test_returns_existing_path_for_local_backend(self, excel_path):
        result = get_excel_path_for_reading()
        assert result == excel_path

    def test_auto_creates_file_if_missing(self, tmp_path, monkeypatch):
        missing_path = tmp_path / "auto_created.xlsx"
        monkeypatch.setattr(file_storage, "LOCAL_XLSX_PATH", missing_path)
        result = get_excel_path_for_reading()
        assert result.exists()
        wb = openpyxl.load_workbook(result)
        assert "MasterData" in wb.sheetnames


# ── load_lists ────────────────────────────────────────────────────────────────


class TestLoadLists:

    def test_returns_dict_with_required_keys(self, excel_path):
        result = load_lists(excel_path)
        assert {"months", "txn_types", "categories", "persons", "years", "budgets"}.issubset(result.keys())

    def test_months_has_12_entries(self, excel_path):
        result = load_lists(excel_path)
        assert len(result["months"]) == 12

    def test_months_starts_with_jan(self, excel_path):
        result = load_lists(excel_path)
        assert result["months"][0] == "Jan"

    def test_months_ends_with_dec(self, excel_path):
        result = load_lists(excel_path)
        assert result["months"][-1] == "Dec"

    def test_txn_types_contains_expense_income_savings(self, excel_path):
        result = load_lists(excel_path)
        assert "Expense" in result["txn_types"]
        assert "Income" in result["txn_types"]
        assert "Savings" in result["txn_types"]

    def test_categories_is_non_empty_list(self, excel_path):
        result = load_lists(excel_path)
        assert isinstance(result["categories"], list)
        assert len(result["categories"]) > 0

    def test_categories_contains_groceries(self, excel_path):
        result = load_lists(excel_path)
        assert "Groceries" in result["categories"]

    def test_persons_is_a_list(self, excel_path):
        result = load_lists(excel_path)
        assert isinstance(result["persons"], list)

    def test_years_is_non_empty_list(self, excel_path):
        result = load_lists(excel_path)
        assert len(result["years"]) > 0

    def test_years_are_integers(self, excel_path):
        result = load_lists(excel_path)
        for y in result["years"]:
            assert isinstance(y, int)

    def test_categories_contains_income_type_entry(self, excel_path):
        result = load_lists(excel_path)
        assert "Salary" in result["categories"], "Unified categories must include income-type entries"

    def test_categories_contains_expense_type_entry(self, excel_path):
        result = load_lists(excel_path)
        assert "Groceries" in result["categories"], "Unified categories must include expense-type entries"

    def test_categories_contains_savings_type_entry(self, excel_path):
        result = load_lists(excel_path)
        assert "Bank Deposit" in result["categories"], "Unified categories must include savings-type entries"


# ── load_budgets_from_excel ───────────────────────────────────────────────────


class TestLoadBudgetsFromExcel:

    def _find_budget_col(self, ws):
        for c in range(1, ws.max_column + 1):
            if "budget" in str(ws.cell(1, c).value or "").lower():
                return c
        return None

    def _find_category_col(self, ws):
        for c in range(1, ws.max_column + 1):
            if "categor" in str(ws.cell(1, c).value or "").lower():
                return c
        return None

    def test_returns_dict(self, excel_path):
        result = load_budgets_from_excel(excel_path)
        assert isinstance(result, dict)

    def test_blank_excel_has_no_budgets(self, excel_path):
        # Blank Excel has no budget amounts filled in — all categories have 0 or None
        result = load_budgets_from_excel(excel_path)
        assert isinstance(result, dict)
        assert len(result) == 0

    def test_returns_numeric_budget_written_as_float(self, excel_path):
        wb = openpyxl.load_workbook(excel_path)
        ws = wb["Lists"]
        cat_col = self._find_category_col(ws)
        bud_col = self._find_budget_col(ws)
        assert cat_col and bud_col, "Lists sheet must have Category and Budget columns"
        # Write a category with a limit in the next empty row
        next_row = ws.max_row + 1
        ws.cell(next_row, cat_col).value = "SpecialCat"
        ws.cell(next_row, bud_col).value = 1200.0
        wb.save(excel_path)
        result = load_budgets_from_excel(excel_path)
        assert "SpecialCat" in result
        assert result["SpecialCat"] == pytest.approx(1200.0)

    def test_skips_categories_with_zero_budget(self, excel_path):
        wb = openpyxl.load_workbook(excel_path)
        ws = wb["Lists"]
        cat_col = self._find_category_col(ws)
        bud_col = self._find_budget_col(ws)
        next_row = ws.max_row + 1
        ws.cell(next_row, cat_col).value = "ZeroCat"
        ws.cell(next_row, bud_col).value = 0
        wb.save(excel_path)
        result = load_budgets_from_excel(excel_path)
        assert "ZeroCat" not in result

    def test_skips_categories_with_no_budget(self, excel_path):
        wb = openpyxl.load_workbook(excel_path)
        ws = wb["Lists"]
        cat_col = self._find_category_col(ws)
        next_row = ws.max_row + 1
        ws.cell(next_row, cat_col).value = "NoBudgetCat"
        wb.save(excel_path)
        result = load_budgets_from_excel(excel_path)
        assert "NoBudgetCat" not in result

    def test_returns_empty_dict_on_missing_lists_sheet(self, tmp_path):
        path = tmp_path / "no_lists.xlsx"
        wb = openpyxl.Workbook()
        wb.active.title = "MasterData"
        wb.save(path)
        result = load_budgets_from_excel(path)
        assert result == {}


# ── get_recent_transactions ───────────────────────────────────────────────────


class TestGetRecentTransactions:

    def test_empty_masterdata_returns_empty_list(self, excel_path):
        result = get_recent_transactions(excel_path)
        assert result == []

    def test_returns_list(self, excel_path):
        result = get_recent_transactions(excel_path)
        assert isinstance(result, list)


# ── user preferences ──────────────────────────────────────────────────────────


class TestUserPrefs:

    def test_load_user_prefs_returns_empty_dict_when_no_file(self, excel_path, monkeypatch, tmp_path):
        # USER_PREFS_PATH is patched to tmp_path/user_prefs.json by excel_path fixture
        # which doesn't exist yet — should return {}
        result = load_user_prefs()
        assert result == {}

    def test_save_and_load_user_prefs_roundtrip(self, excel_path, tmp_path):
        prefs = {"display_currency": "EUR", "user_id": 12345}
        save_user_prefs(prefs)
        loaded = load_user_prefs()
        assert loaded == prefs

    def test_save_user_prefs_creates_file(self, excel_path, tmp_path):
        prefs_path = file_storage.USER_PREFS_PATH
        assert not prefs_path.exists()  # Should not exist yet
        save_user_prefs({"key": "value"})
        assert prefs_path.exists()

    def test_save_user_prefs_overwrites_existing(self, excel_path):
        save_user_prefs({"v": 1})
        save_user_prefs({"v": 2})
        loaded = load_user_prefs()
        assert loaded["v"] == 2


def test_repair_template_keeps_validation_ranges(tmp_path, monkeypatch):
    """delete_rows during template cleanup must not collapse dropdown ranges."""
    import openpyxl
    from openpyxl.worksheet.datavalidation import DataValidation
    import file_storage

    # Build a template-like file: header + 500 stale data rows + validation to row 578
    src = tmp_path / "template.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "MasterData"
    for i, h in enumerate(["Date", "Year", "Month", "Value", "Type", "Category",
                           "Person", "Description", "IsRecurring", "IsDone",
                           "Currency", "Value (base)", "Date Modified (UTC)"], 1):
        ws.cell(1, i, h)
    for r in range(2, 500):
        ws.cell(r, 4, 1.0)
    dv = DataValidation(type="list", formula1="Lists!$C$2:$C$18")
    dv.add("F2:F578")
    ws.add_data_validation(dv)
    wb.create_sheet("Lists")
    wb.save(src)

    file_storage._repair_template_workbook(src)

    wb = openpyxl.load_workbook(src)
    ws = wb["MasterData"]
    sqrefs = [str(d.sqref) for d in ws.data_validations.dataValidation]
    assert sqrefs, "validations were dropped entirely"
    end_row = int(sqrefs[0].split(":F")[1])
    assert end_row >= 500, f"validation range collapsed: {sqrefs}"
