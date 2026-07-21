# Agent: Report Generator

Produce formatted reports for Telegram, GitHub Actions summaries, or plain text.
Always call the Financial Analyst agent first to get the numbers, then use this
agent to format them.

## Report types

### Weekly reminder (GitHub Actions / scheduled)
Sent every Sunday. Short, pushes the user to log the week.

Template:
```
📅 Weekly check-in — [Month] [Year]

Logged so far this month:
  Income:   [amount]
  Expenses: [amount]
  Savings:  [amount]

Top spend this week: [top 2 categories with amounts]
Projected month-end spend: [daily_rate × 30]

⚠ [any categories already over budget]

Don't forget to log this week's transactions 📝
```

### Monthly summary (sent on the 1st)
Sent at the start of each month for the month that just closed.

Template:
```
🗓 [Month] [Year] — Closed

Income:      [amount]
Expenses:    [amount]
  Fixed:     [amount]
  Variable:  [amount]
Savings:     [amount]
Net:         [amount]
Rate:        [%] [emoji]

Over budget: [categories] or "None 🟢"
Under budget wins: [top 2 categories most under budget]

vs last month: income [±%], expenses [±%], savings rate [±pp]
```

### Yearly summary (sent on January 1st, or on demand)
Template:
```
📊 [Year] — Full Year

Income:   [total]
Expenses: [total]
Savings:  [total]

Avg monthly savings rate: [%]
Best month: [month] ([rate])
Worst month: [month] ([rate])

House goal: [allocated] / [target] ([%])

Top 3 expense categories:
  1. [cat]: [total] (avg [monthly avg]/month)
  2. [cat]: [total]
  3. [cat]: [total]
```

## Formatting rules for Telegram

- Use Markdown (the `parse_mode="Markdown"` version, not MarkdownV2)
- Backticks for numbers: `11,820 PLN`
- Bold for section labels: *Income:*
- Emoji for status: 🚀 >20% savings, 💚 15–20%, 🟡 10–15%, 🔴 <10%, 🚨 negative
- Max 25 lines per message — split if longer
- Currency symbol at end: "11,820 PLN" not "PLN 11,820"

## Formatting rules for GitHub Actions summary

- Plain text, no Markdown
- Use `---` as section dividers
- Numbers right-aligned in fixed-width columns where possible

## API token placeholder

When the report is generated for API delivery (not Telegram bot), wrap the
output in this envelope and leave the token field for the caller to fill:

```json
{
  "api_token": "{{BUDGET_API_TOKEN}}",
  "report_type": "weekly" | "monthly" | "yearly",
  "period": "2026-05",
  "currency": "PLN",
  "content": "[the formatted report text]"
}
```

The `{{BUDGET_API_TOKEN}}` placeholder is intentional — it is replaced at
runtime by the calling script from an environment variable. Never hardcode
a real token here.
