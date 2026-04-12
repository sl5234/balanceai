from balanceai_backend.db import (
    conn,
    get_distinct_accounts,
    get_distinct_categories,
    get_schema_summary,
)
from balanceai_backend.prompts.financial_query_prompt import _DOUBLE_ENTRY_SEMANTICS

_REPORT_DEFINITION_INSTRUCTIONS = """\
You are a SQL parameterization assistant. Given a verified SQL query and a report's
name/description, your ONLY job is to replace hardcoded literal values with SQLite
named parameters where doing so aligns with the report's stated intent.

Rules:
- Do NOT restructure, rewrite, or optimize the SQL in any way.
- Do NOT add, remove, or reorder clauses, joins, columns, or conditions.
- ONLY replace hardcoded literal values with :param_name placeholders.
- Always replace hardcoded date literals with :start_date and :end_date.
  A BETWEEN date range becomes: BETWEEN :start_date AND :end_date
  A >= / <= date pair becomes: >= :start_date ... <= :end_date (preserve the original form)
- Beyond dates, use the report name and description to decide which other scalar
  literals represent user-varying criteria worth parameterizing (e.g. :category,
  :recipient, :min_amount). Only parameterize scalars — do NOT attempt to parameterize
  IN-clause lists (SQLite named parameters cannot expand lists).
- Leave structural literals hardcoded (e.g. account = 'cash' if it is not the
  subject of the report).
- Return ONLY valid JSON with no extra text.

Return format:
{
  "sql": "<original SQL with only literal → :param_name substitutions applied>",
  "parameters": [
    {"name": "start_date", "description": "start of reporting period (inclusive)", "example_value": "2025-10-01"},
    {"name": "end_date", "description": "end of reporting period (inclusive)", "example_value": "2025-10-31"}
  ]
}
Note: include one entry in "parameters" for every :param_name that appears in the SQL,
including :start_date and :end_date. The example_value should be the original hardcoded
literal that was replaced.
"""


def report_definition_system_prompt() -> str:
    schema = get_schema_summary(conn)
    categories = get_distinct_categories(conn)
    accounts = get_distinct_accounts(conn)
    categories_str = ", ".join(repr(c) for c in categories)
    accounts_str = ", ".join(repr(a) for a in accounts)

    return (
        f"Tables:\n{schema}\n\n"
        f"Known category values: {categories_str}\n"
        f"Known account values: {accounts_str}\n\n"
        f"{_DOUBLE_ENTRY_SEMANTICS}\n"
        f"{_REPORT_DEFINITION_INSTRUCTIONS}"
    )


def report_definition_user_message(
    sample_sql: str, name: str, prompt: str, description: str
) -> str:
    return (
        f"Report name: {name}\n"
        f"User intent: {prompt}\n"
        f"Report description: {description}\n\n"
        f"Sample SQL to parameterize:\n```sql\n{sample_sql.strip()}\n```"
    )
