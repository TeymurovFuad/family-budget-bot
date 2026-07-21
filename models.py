from __future__ import annotations

import datetime
from datetime import timezone
from typing import Optional

from pydantic import BaseModel, field_validator, model_validator

MONTH_NAMES = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


class Transaction(BaseModel):
    """
    A single financial transaction row, ready to write to MasterData.

    Equivalent to a DTO in C# — validated on construction.
    Pass an instance of this to append_transaction() instead of a raw dict.
    """

    date:         datetime.date
    value:        float
    currency:     str
    transaction_type: str       # "Expense" | "Income" | "Savings"
    category:     str = ""
    person:       str = ""      # optional — blank means household expense
    description:  str = ""
    is_recurring: bool = False
    is_done:      bool = True

    # Derived — always computed from date, never supplied by caller
    year:  int = 0
    month: str = ""

    @field_validator("value")
    @classmethod
    def value_must_be_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError(f"value must be positive, got {v}")
        return round(v, 2)

    @field_validator("transaction_type")
    @classmethod
    def transaction_type_must_be_non_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("transaction_type must not be empty")
        return v.strip()

    @field_validator("currency")
    @classmethod
    def currency_must_be_uppercase(cls, v: str) -> str:
        return v.strip().upper()

    @field_validator("description")
    @classmethod
    def description_strip_whitespace(cls, v: str) -> str:
        return v.strip()[:100]

    @model_validator(mode="after")
    def fill_derived_date_fields(self) -> Transaction:
        """Year and Month are always derived from date — never set manually."""
        self.year  = self.date.year
        self.month = MONTH_NAMES[self.date.month - 1]
        return self

    def to_row(self) -> dict:
        """
        Convert to the dict format expected by append_transaction().
        Named to_row() rather than to_dict() to be explicit about its purpose.
        """
        return {
            "date":         self.date,
            "year":         self.year,
            "month":        self.month,
            "value":        self.value,
            "type":         self.transaction_type,
            "category":     self.category,
            "person":       self.person,
            "description":  self.description,
            "is_recurring": self.is_recurring,
            "is_done":      self.is_done,
            "currency":     self.currency,
        }


class AddTransactionState(BaseModel):
    """
    Holds partial state during the multi-step /add conversation.

    Fields are Optional because they are filled one step at a time.
    Call to_transaction() once all required fields are collected.
    """

    value:            Optional[float]          = None
    currency:         Optional[str]            = None
    transaction_type: Optional[str]            = None
    category:         Optional[str]            = None
    person:           Optional[str]            = None
    description:      Optional[str]            = None
    is_recurring:     Optional[bool]           = None
    date:             Optional[datetime.date]  = None  # None = use today at save time

    # Cached during the conversation — not part of the transaction itself
    display_currency: str   = "PLN"
    rates:            dict  = {}

    def is_ready_to_confirm(self) -> bool:
        """True when enough fields are filled to show the confirmation step."""
        required = [self.value, self.currency, self.transaction_type]
        if self.transaction_type == "Expense":
            required.append(self.category)
        return all(f is not None for f in required)

    def to_transaction(self) -> Transaction:
        """
        Build a validated Transaction from the collected state.
        Raises ValidationError (Pydantic) if required fields are missing.
        """
        return Transaction(
            date             = self.date or datetime.datetime.now(timezone.utc).date(),
            value            = self.value,
            currency         = self.currency or "PLN",
            transaction_type = self.transaction_type,
            category         = self.category or "",
            person           = self.person or "",
            description      = self.description or "",
            is_recurring     = self.is_recurring or False,
        )
