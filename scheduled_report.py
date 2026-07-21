"""
scheduled_report.py
===================
Runs as a one-shot script inside GitHub Actions.
Reads the Excel file, builds a report, sends it to Telegram, then exits.

No persistent process, no bot framework, no server.
Triggered by GitHub Actions cron schedule or manual workflow dispatch.

Environment variables (set as GitHub Secrets / Variables):
  TELEGRAM_BOT_TOKEN    Required. From @BotFather.
  ALLOWED_TELEGRAM_IDS  Required. Comma-separated Telegram user IDs.
  XLSX_PATH             Path to Excel file. Default: data/Expenses_Improved.xlsx
  DISPLAY_CURRENCY      Currency for display. Default: PLN
  REPORT_TYPE           weekly | monthly | yearly. Default: weekly
  TIMEZONE              Default: Europe/Warsaw
"""

import calendar
import io
import json
import sys
import asyncio
import logging
from datetime import datetime, timedelta, timezone

import pandas as pd
import httpx

import settings

from file_storage import get_excel_path_for_reading, load_budgets_from_excel, load_lists

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN   = settings.BOT_TOKEN
ALLOWED_TELEGRAM_IDS = settings.ALLOWED_TELEGRAM_IDS
DISPLAY_CURRENCY = settings.DISPLAY_CURRENCY
REPORT_TYPE      = settings.REPORT_TYPE
USER_PREFS_PATH  = settings.USER_PREFS_PATH


def load_user_prefs() -> dict:
    try:
        if USER_PREFS_PATH.exists():
            return json.loads(USER_PREFS_PATH.read_text())
    except Exception as e:
        log.warning("Could not load user prefs: %s — using defaults", e)
    return {}



def _month_names() -> list[str]:
    """Read month abbreviations from Lists sheet."""
    return load_lists(get_excel_path_for_reading())["months"]


def load_budget_amounts() -> dict[str, float]:
    """Read monthly PLN budget targets from the Dashboard sheet."""
    return load_budgets_from_excel(get_excel_path_for_reading())


def load_transaction_data() -> pd.DataFrame:
    excel_path = get_excel_path_for_reading()
    df = pd.read_excel(excel_path, sheet_name="MasterData")
    pln_column = "Value (PLN)" if "Value (PLN)" in df.columns else "Value"
    df["amount_pln"] = pd.to_numeric(df[pln_column], errors="coerce")
    df["Value"]      = pd.to_numeric(df["Value"], errors="coerce")
    df["Year"]       = pd.to_numeric(df["Year"], errors="coerce").astype("Int64")
    df["IsDone"]     = df["IsDone"].fillna(True).astype(bool)
    df["Currency"]   = df["Currency"].fillna("PLN")
    missing = df["amount_pln"].isna() & df["Value"].notna()
    if missing.any():
        rates = load_currency_rates()
        df.loc[missing, "amount_pln"] = df.loc[missing].apply(
            lambda r: r["Value"] * rates.get(str(r.get("Currency", "PLN")).upper(), 1.0),
            axis=1,
        )
    return df.dropna(subset=["amount_pln", "Type", "Year", "Month"])


def load_currency_rates() -> dict[str, float]:
    try:
        excel_path = get_excel_path_for_reading()
        rates_df = pd.read_excel(excel_path, sheet_name="Lists", header=0)
        currency_cols = [c for c in rates_df.columns if "currency" in str(c).lower()]
        rate_cols     = [c for c in rates_df.columns if "rate" in str(c).lower() and "pln" in str(c).lower()]
        if not currency_cols or not rate_cols:
            log.warning("Currency/Rate columns not found in Lists sheet")
            return {"PLN": 1.0}
        rates_df = rates_df[[currency_cols[0], rate_cols[0]]].copy()
        rates_df.columns = ["currency_code", "rate_to_pln"]
        rates_df = rates_df.dropna(subset=["currency_code", "rate_to_pln"])
        rates_df = rates_df[rates_df["currency_code"].astype(str).str.match(r"^[A-Z]{3}$")]
        return dict(zip(rates_df["currency_code"], rates_df["rate_to_pln"].astype(float)))
    except Exception as error:
        log.warning("Could not load currency rates: %s — using PLN only", error)
        return {"PLN": 1.0}


def convert_pln_to_display_currency(pln_amount: float, currency: str, rates: dict) -> float:
    rate = rates.get(currency.upper(), 1.0)
    return pln_amount / rate if rate else pln_amount


def format_with_currency(pln_amount: float, currency: str, rates: dict) -> str:
    converted = convert_pln_to_display_currency(pln_amount, currency, rates)
    return f"{converted:,.0f} {currency}"


def savings_rate_emoji(rate: float) -> str:
    if rate >= 0.20: return "🚀"
    if rate >= 0.15: return "💚"
    if rate >= 0.08: return "🟡"
    if rate >= 0:    return "🔴"
    return "🚨"


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def previous_month_year_and_name() -> tuple[int, str]:
    today = now_utc()
    first_of_this_month = today.replace(day=1)
    last_day_of_previous = first_of_this_month - timedelta(days=1)
    return last_day_of_previous.year, _month_names()[last_day_of_previous.month - 1]


def build_weekly_report(df: pd.DataFrame, rates: dict, currency: str = DISPLAY_CURRENCY) -> str:
    today    = now_utc()
    year     = today.year
    month    = _month_names()[today.month - 1]

    this_month = df[(df["Year"] == year) & (df["Month"] == month) & df["IsDone"]]
    income   = this_month[this_month["Type"] == "Income"]["amount_pln"].sum()
    expenses = this_month[this_month["Type"] == "Expense"]["amount_pln"].sum()
    savings  = this_month[this_month["Type"] == "Savings"]["amount_pln"].sum()

    by_category    = this_month[this_month["Type"] == "Expense"].groupby("Category")["amount_pln"].sum()
    top_categories = by_category.sort_values(ascending=False).head(3)

    days_elapsed      = today.day
    daily_spend_rate  = expenses / days_elapsed if days_elapsed > 0 else 0
    projected_monthly = daily_spend_rate * calendar.monthrange(today.year, today.month)[1]

    budgets = load_budget_amounts()
    over_budget_categories = [
        f"{cat} ({format_with_currency(actual, currency, rates)})"
        for cat, actual in by_category.items()
        if budgets.get(cat, 0) and actual > budgets[cat]
    ]

    lines = [
        f"📅 *Weekly check-in — {month} {year}* ({currency})\n",
        f"Logged so far this month:",
        f"  Income:   `{format_with_currency(income, currency, rates)}`",
        f"  Expenses: `{format_with_currency(expenses, currency, rates)}`",
        f"  Savings:  `{format_with_currency(savings, currency, rates)}`\n",
        f"Top categories:",
    ]
    for category, amount in top_categories.items():
        lines.append(f"  {category}: `{format_with_currency(amount, currency, rates)}`")

    lines.append(f"\nProjected month-end spend: `{format_with_currency(projected_monthly, currency, rates)}`")

    if over_budget_categories:
        lines.append(f"\n⚠ Over budget: {', '.join(over_budget_categories)}")
    else:
        lines.append("\n🟢 All categories within budget so far")

    lines.append("\n_Don't forget to log this week's transactions_ 📝")

    return "\n".join(lines)


def build_monthly_summary(df: pd.DataFrame, rates: dict, currency: str = DISPLAY_CURRENCY) -> str:
    year, month = previous_month_year_and_name()

    closed_month = df[(df["Year"] == year) & (df["Month"] == month) & df["IsDone"]]
    income   = closed_month[closed_month["Type"] == "Income"]["amount_pln"].sum()
    expenses = closed_month[closed_month["Type"] == "Expense"]["amount_pln"].sum()
    savings  = closed_month[closed_month["Type"] == "Savings"]["amount_pln"].sum()
    net      = income - expenses - savings
    rate     = savings / income if income > 0 else 0

    recurring_expenses  = closed_month[
        (closed_month["Type"] == "Expense") & closed_month["IsRecurring"].fillna(False).astype(bool)
    ]["amount_pln"].sum()
    variable_expenses = expenses - recurring_expenses

    by_category = closed_month[closed_month["Type"] == "Expense"].groupby("Category")["amount_pln"].sum()
    budgets    = load_budget_amounts()
    over_budget = [
        f"{cat}"
        for cat, actual in by_category.items()
        if budgets.get(cat, 0) and actual > budgets[cat]
    ]

    lines = [
        f"🗓 *{month} {year} — Closed* ({currency})\n",
        f"*Income:*    `{format_with_currency(income, currency, rates)}`",
        f"*Expenses:*  `{format_with_currency(expenses, currency, rates)}`",
        f"  Fixed:     `{format_with_currency(recurring_expenses, currency, rates)}`",
        f"  Variable:  `{format_with_currency(variable_expenses, currency, rates)}`",
        f"*Savings:*   `{format_with_currency(savings, currency, rates)}`",
        f"*Net:*       `{format_with_currency(net, currency, rates)}`",
        f"*Rate:* {rate:.0%} {savings_rate_emoji(rate)}\n",
        f"Over budget: {', '.join(over_budget) if over_budget else 'None 🟢'}",
        "\nUse /report for the full breakdown.",
    ]
    return "\n".join(lines)


def build_yearly_summary(df: pd.DataFrame, rates: dict, currency: str = DISPLAY_CURRENCY) -> str:
    year     = now_utc().year - 1

    year_data = df[(df["Year"] == year) & df["IsDone"]]
    income    = year_data[year_data["Type"] == "Income"]["amount_pln"].sum()
    expenses  = year_data[year_data["Type"] == "Expense"]["amount_pln"].sum()
    savings   = year_data[year_data["Type"] == "Savings"]["amount_pln"].sum()

    monthly_rates = []
    for month in _month_names():
        month_data      = year_data[year_data["Month"] == month]
        month_income    = month_data[month_data["Type"] == "Income"]["amount_pln"].sum()
        month_savings   = month_data[month_data["Type"] == "Savings"]["amount_pln"].sum()
        if month_income > 0:
            monthly_rates.append((month, month_savings / month_income))

    best_month  = max(monthly_rates, key=lambda x: x[1]) if monthly_rates else ("—", 0)
    worst_month = min(monthly_rates, key=lambda x: x[1]) if monthly_rates else ("—", 0)
    average_savings_rate = sum(r for _, r in monthly_rates) / len(monthly_rates) if monthly_rates else 0

    by_category     = year_data[year_data["Type"] == "Expense"].groupby("Category")["amount_pln"].sum()
    top_3_categories = by_category.sort_values(ascending=False).head(3)

    lines = [
        f"📊 *{year} — Full Year* ({currency})\n",
        f"*Income:*   `{format_with_currency(income, currency, rates)}`",
        f"*Expenses:* `{format_with_currency(expenses, currency, rates)}`",
        f"*Savings:*  `{format_with_currency(savings, currency, rates)}`",
        f"*Avg savings rate:* {average_savings_rate:.0%} {savings_rate_emoji(average_savings_rate)}\n",
        f"Best month:  {best_month[0]} ({best_month[1]:.0%})",
        f"Worst month: {worst_month[0]} ({worst_month[1]:.0%})\n",
        "Top 3 expense categories:",
    ]
    for category, total in top_3_categories.items():
        monthly_average = total / 12
        lines.append(
            f"  {category}: `{format_with_currency(total, currency, rates)}` "
            f"(avg {format_with_currency(monthly_average, currency, rates)}/month)"
        )

    return "\n".join(lines)


async def send_telegram_message(text: str, user_id: int) -> None:
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": user_id, "text": text, "parse_mode": "Markdown"}
    async with httpx.AsyncClient() as client:
        response = await client.post(url, json=payload, timeout=10)
        response.raise_for_status()
        log.info("Sent %s report to user %d", REPORT_TYPE, user_id)


async def main() -> None:
    if not TELEGRAM_BOT_TOKEN:
        log.error("TELEGRAM_BOT_TOKEN is not set")
        sys.exit(1)

    if not ALLOWED_TELEGRAM_IDS:
        log.error("ALLOWED_TELEGRAM_IDS is not set")
        sys.exit(1)

    df    = load_transaction_data()
    rates = load_currency_rates()

    report_builders = {
        "weekly":  build_weekly_report,
        "monthly": build_monthly_summary,
        "yearly":  build_yearly_summary,
    }

    builder = report_builders.get(REPORT_TYPE)
    if not builder:
        log.error("Unknown REPORT_TYPE: %s — must be weekly, monthly, or yearly", REPORT_TYPE)
        sys.exit(1)

    prefs = load_user_prefs()
    for user_id in ALLOWED_TELEGRAM_IDS:
        ccy = prefs.get("currency", {}).get(str(user_id), DISPLAY_CURRENCY)
        report_text = builder(df, rates, ccy)
        await send_telegram_message(report_text, user_id)


if __name__ == "__main__":
    asyncio.run(main())
