from datetime import date

from balanceai_backend.db import conn, get_distinct_accounts, get_distinct_categories, get_schema_summary

_DOUBLE_ENTRY_SEMANTICS = """\
Double-entry bookkeeping semantics — critical rules for correct queries:
- Every transaction creates exactly TWO journal_entries (a debit leg and a credit leg).
- SPENDING: debit leg has recipient='Self'; credit leg has recipient=<merchant name>.
    To find spending at a merchant: WHERE je.account = 'cash' AND je.credit > 0 AND je.recipient = '<merchant>'
    To find all spending: WHERE je.account = 'cash' AND je.credit > 0 AND je.recipient != 'Self'
- INCOME: debit leg has recipient='Self' (cash received); credit leg has recipient=<payer>.
    To find income: WHERE je.account = 'income' AND je.debit > 0 AND je.recipient = 'Self'
- NEVER filter by description to identify a merchant — both legs share the same description.
- Always filter to ONE leg to avoid double-counting.
- Column 'account' (bookkeeping type: 'cash', 'income', etc.) lives in journal_entries ONLY.
  The journals table has 'account_id' (bank account UUID) and 'account_type' — NOT 'account'.
- When filtering by Account ID, JOIN journals j ON j.journal_id = je.journal_id and filter j.account_id = '<id>'.
  Example: SELECT SUM(je.credit) FROM journal_entries je JOIN journals j ON je.journal_id = j.journal_id
           WHERE j.account_id = '<id>' AND je.account = 'cash' AND je.credit > 0 AND je.recipient != 'Self'
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
