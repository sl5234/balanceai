from pydantic import BaseModel


class FinancialQuery(BaseModel):
    """The SQL the AI writes to answer a financial question."""

    sql: str
    description: str
