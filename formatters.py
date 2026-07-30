"""
formatters.py — display formatting helpers. No I/O, no side effects.
"""

import settings
from data import get_rate
from validators import clean_merchant_description


def format_amount(n: float, ccy: str = "") -> str:
    ccy = ccy or settings.DISPLAY_CURRENCY
    return f"{n:,.0f} {ccy}"


def convert(base_amount: float, ccy: str, rates: dict) -> float:
    rate = get_rate(ccy, rates)
    return base_amount / rate if rate else base_amount


def format_base_as_currency(base_amount: float, ccy: str, rates: dict) -> str:
    return format_amount(convert(base_amount, ccy, rates), ccy)


def budget_progress_bar(actual: float, budget: float, width: int = 10) -> str:
    if budget <= 0:
        return "─" * width
    pct = actual / budget
    filled = round(min(pct, 1.0) * width)
    colour = "🟩" if pct <= 0.8 else ("🟨" if pct <= 1.0 else "🟥")
    return colour * filled + "⬜" * (width - filled)


def savings_emoji(rate: float) -> str:
    if rate >= 0.20: return "🚀"
    if rate >= 0.15: return "💚"
    if rate >= 0.08: return "🟡"
    if rate >= 0:    return "🔴"
    return "🚨"


def sanitize_description(text: str) -> str:
    """Clean bank-statement junk from a description, then prevent Excel formula injection."""
    text = clean_merchant_description(text)[:100]
    if text and text[0] in ('=', '+', '-', '@'):
        text = "'" + text
    return text
