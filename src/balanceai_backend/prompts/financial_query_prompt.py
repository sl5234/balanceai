from datetime import date

from balanceai_backend.db import conn, get_distinct_accounts, get_distinct_categories, get_schema_summary

_DOUBLE_ENTRY_SEMANTICS = """\
Double-entry bookkeeping semantics — critical rules for correct queries:
- Every transaction creates exactly TWO journal_entries (a debit leg and a credit leg).
- SPENDING: debit leg has recipient='Self'; credit leg has recipient=<merchant name>.
    To find spending at a merchant: WHERE recipient = '<merchant>' AND credit > 0
    To find all spending: WHERE recipient != 'Self' AND credit > 0
- INCOME: debit leg has recipient='Self' (cash received); credit leg has recipient=<payer>.
    To find income: WHERE recipient = 'Self' AND debit > 0
- NEVER filter by description to identify a merchant — both legs share the same description.
- Always filter to ONE leg to avoid double-counting.
Dates are ISO 8601 strings (e.g. '2025-10-22'). Monetary amounts (debit, credit) are in USD.
"""

_INSTRUCTIONS = """\
You are a financial SQL query generator. Given a question, generate a correct SQL SELECT
query against the schema above.

Rules:
- Only generate SELECT statements.
- Always apply correct double-entry semantics.
- Inline all values as literals (no placeholders).
- For dates inferred from natural language (e.g. "October 2025"), use exact ISO dates.
- Return ONLY valid JSON with no extra text.

Return format:
{
  "sql": "<SELECT statement>",
  "description": "<one sentence: what this query computes>"
}
"""


def financial_query_system_prompt(today: date) -> str:
    schema = get_schema_summary(conn)
    categories = get_distinct_categories(conn)
    accounts = get_distinct_accounts(conn)
    categories_str = ", ".join(repr(c) for c in categories)
    accounts_str = ", ".join(repr(a) for a in accounts)
    return (
        f"Today's date is {today.isoformat()}.\n\n"
        f"Tables:\n{schema}\n\n"
        f"Known category values (use these exact strings in queries): {categories_str}\n"
        f"Known account values (use these exact strings in queries): {accounts_str}\n\n"
        f"{_DOUBLE_ENTRY_SEMANTICS}\n"
        f"{_INSTRUCTIONS}"
    )
