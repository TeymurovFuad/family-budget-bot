"""
test_models.py — tests for Transaction and AddTransactionState (models.py).
"""

import datetime
from datetime import timezone

import pytest
from pydantic import ValidationError

from models import Transaction, AddTransactionState, MONTH_NAMES


# ── Transaction validation ────────────────────────────────────────────────────


class TestTransactionValidation:

    def test_valid_transaction_constructs_successfully(self):
        t = Transaction(
            date=datetime.date(2024, 6, 15),
            value=100.0,
            currency="PLN",
            transaction_type="Expense",
        )
        assert t.value == 100.0

    def test_zero_value_raises_validation_error(self):
        with pytest.raises(ValidationError) as exc_info:
            Transaction(
                date=datetime.date(2024, 6, 15),
                value=0,
                currency="PLN",
                transaction_type="Expense",
            )
        assert "positive" in str(exc_info.value).lower()

    def test_negative_value_raises_validation_error(self):
        with pytest.raises(ValidationError):
            Transaction(
                date=datetime.date(2024, 6, 15),
                value=-50.0,
                currency="PLN",
                transaction_type="Expense",
            )

    def test_currency_is_uppercased(self):
        t = Transaction(
            date=datetime.date(2024, 6, 15),
            value=10.0,
            currency="pln",
            transaction_type="Income",
        )
        assert t.currency == "PLN"

    def test_currency_strips_whitespace_and_uppercases(self):
        t = Transaction(
            date=datetime.date(2024, 6, 15),
            value=10.0,
            currency="  eur  ",
            transaction_type="Income",
        )
        assert t.currency == "EUR"

    def test_year_derived_from_date(self):
        t = Transaction(
            date=datetime.date(2024, 6, 15),
            value=10.0,
            currency="PLN",
            transaction_type="Expense",
        )
        assert t.year == 2024

    def test_month_derived_from_date(self):
        t = Transaction(
            date=datetime.date(2024, 6, 15),
            value=10.0,
            currency="PLN",
            transaction_type="Expense",
        )
        assert t.month == "Jun"

    def test_month_derived_for_january(self):
        t = Transaction(
            date=datetime.date(2024, 1, 1),
            value=10.0,
            currency="PLN",
            transaction_type="Expense",
        )
        assert t.month == "Jan"

    def test_month_derived_for_december(self):
        t = Transaction(
            date=datetime.date(2024, 12, 31),
            value=10.0,
            currency="PLN",
            transaction_type="Expense",
        )
        assert t.month == "Dec"

    def test_description_stripped_of_leading_trailing_whitespace(self):
        t = Transaction(
            date=datetime.date(2024, 6, 15),
            value=10.0,
            currency="PLN",
            transaction_type="Expense",
            description="  weekly shop  ",
        )
        assert t.description == "weekly shop"

    def test_description_truncated_to_100_chars(self):
        long_desc = "x" * 200
        t = Transaction(
            date=datetime.date(2024, 6, 15),
            value=10.0,
            currency="PLN",
            transaction_type="Expense",
            description=long_desc,
        )
        assert len(t.description) == 100

    def test_description_exactly_100_chars_is_not_truncated(self):
        exact_desc = "a" * 100
        t = Transaction(
            date=datetime.date(2024, 6, 15),
            value=10.0,
            currency="PLN",
            transaction_type="Expense",
            description=exact_desc,
        )
        assert len(t.description) == 100

    def test_is_done_defaults_to_true(self):
        t = Transaction(
            date=datetime.date(2024, 6, 15),
            value=10.0,
            currency="PLN",
            transaction_type="Expense",
        )
        assert t.is_done is True

    def test_is_recurring_defaults_to_false(self):
        t = Transaction(
            date=datetime.date(2024, 6, 15),
            value=10.0,
            currency="PLN",
            transaction_type="Expense",
        )
        assert t.is_recurring is False


# ── Transaction.to_row() ─────────────────────────────────────────────────────


class TestTransactionToRow:

    def test_to_row_returns_dict(self, sample_transaction):
        row = sample_transaction.to_row()
        assert isinstance(row, dict)

    def test_to_row_contains_required_keys(self, sample_transaction):
        row = sample_transaction.to_row()
        expected_keys = {
            "date", "year", "month", "value", "type",
            "category", "person", "description", "is_recurring", "is_done", "currency",
        }
        assert expected_keys.issubset(row.keys())

    def test_to_row_values_match_transaction(self, sample_transaction):
        row = sample_transaction.to_row()
        assert row["date"] == datetime.date(2024, 6, 15)
        assert row["value"] == 150.50
        assert row["currency"] == "PLN"
        assert row["type"] == "Expense"
        assert row["category"] == "Groceries"
        assert row["person"] == "Alice"
        assert row["description"] == "weekly shop"
        assert row["year"] == 2024
        assert row["month"] == "Jun"

    def test_to_row_is_done_is_true_by_default(self, sample_transaction):
        assert sample_transaction.to_row()["is_done"] is True


# ── MONTH_NAMES constant ──────────────────────────────────────────────────────


class TestMonthNames:

    def test_month_names_has_12_entries(self):
        assert len(MONTH_NAMES) == 12

    def test_month_names_first_is_jan(self):
        assert MONTH_NAMES[0] == "Jan"

    def test_month_names_last_is_dec(self):
        assert MONTH_NAMES[11] == "Dec"


# ── AddTransactionState ───────────────────────────────────────────────────────


class TestAddTransactionState:

    def test_is_ready_to_confirm_false_when_all_none(self):
        state = AddTransactionState()
        assert state.is_ready_to_confirm() is False

    def test_is_ready_to_confirm_false_when_value_missing(self):
        state = AddTransactionState(
            currency="PLN",
            transaction_type="Income",
        )
        assert state.is_ready_to_confirm() is False

    def test_is_ready_to_confirm_false_when_currency_missing(self):
        state = AddTransactionState(
            value=100.0,
            transaction_type="Income",
        )
        assert state.is_ready_to_confirm() is False

    def test_is_ready_to_confirm_true_for_income_without_category(self):
        state = AddTransactionState(
            value=500.0,
            currency="PLN",
            transaction_type="Income",
        )
        assert state.is_ready_to_confirm() is True

    def test_is_ready_to_confirm_true_for_savings_without_category(self):
        state = AddTransactionState(
            value=1000.0,
            currency="PLN",
            transaction_type="Savings",
        )
        assert state.is_ready_to_confirm() is True

    def test_is_ready_to_confirm_false_for_expense_without_category(self):
        state = AddTransactionState(
            value=100.0,
            currency="PLN",
            transaction_type="Expense",
        )
        assert state.is_ready_to_confirm() is False

    def test_is_ready_to_confirm_true_for_expense_with_category(self):
        state = AddTransactionState(
            value=100.0,
            currency="PLN",
            transaction_type="Expense",
            category="Groceries",
        )
        assert state.is_ready_to_confirm() is True

    def test_to_transaction_uses_today_when_date_is_none(self):
        state = AddTransactionState(
            value=100.0,
            currency="PLN",
            transaction_type="Income",
        )
        today = datetime.datetime.now(timezone.utc).date()
        txn = state.to_transaction()
        assert txn.date == today

    def test_to_transaction_uses_provided_date(self):
        specific_date = datetime.date(2024, 3, 20)
        state = AddTransactionState(
            value=200.0,
            currency="EUR",
            transaction_type="Expense",
            category="Dining Out",
            date=specific_date,
        )
        txn = state.to_transaction()
        assert txn.date == specific_date

    def test_to_transaction_builds_valid_transaction(self):
        state = AddTransactionState(
            value=75.0,
            currency="pln",  # lowercase — should be uppercased by Transaction validator
            transaction_type="Expense",
            category="Transport",
            person="Bob",
            description="taxi",
            date=datetime.date(2024, 6, 1),
        )
        txn = state.to_transaction()
        assert isinstance(txn, Transaction)
        assert txn.value == 75.0
        assert txn.currency == "PLN"
        assert txn.category == "Transport"
        assert txn.person == "Bob"

    def test_to_transaction_empty_optionals_become_empty_strings(self):
        state = AddTransactionState(
            value=50.0,
            currency="PLN",
            transaction_type="Income",
        )
        txn = state.to_transaction()
        assert txn.category == ""
        assert txn.person == ""
        assert txn.description == ""
        assert txn.is_recurring is False
