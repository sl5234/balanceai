from enum import StrEnum

from pydantic import BaseModel


class QueryRejection(StrEnum):
    """Why the AI wouldn't write a query; the server maps each to its own message."""

    TECHNICAL_QUERY = "technical_query"  # SQL, table or column names, or raw-value tricks
    NOT_A_FINANCIAL_QUESTION = "not_a_financial_question"


_EXAMPLE_QUESTION = "'How much did I spend on dining in October?'"

# Shown to the assistant when no answer comes back; plain words, nothing technical.
REJECTION_MESSAGES = {
    QueryRejection.TECHNICAL_QUERY: (
        "This answers questions about your spending and income in everyday terms, "
        f"e.g. {_EXAMPLE_QUESTION}. Ask it that way."
    ),
    QueryRejection.NOT_A_FINANCIAL_QUESTION: (
        "This only answers questions about your spending, income and transactions, "
        f"e.g. {_EXAMPLE_QUESTION}."
    ),
}
UNANSWERABLE_MESSAGE = (
    f"Couldn't answer this question. Try asking it a different way, e.g. {_EXAMPLE_QUESTION}"
)


class FinancialQuery(BaseModel):
    """The SQL the AI writes to answer a financial question, or why it won't."""

    sql: str | None  # None when rejected
    description: str
    rejection: QueryRejection | None  # None when answered
