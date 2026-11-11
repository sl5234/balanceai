"""Schemas for the MCP consent prompts (ctx.elicit). Each is empty: the prompt
is a plain accept/decline."""

from pydantic import BaseModel


class ShareTransactionsConsent(BaseModel):
    """Empty schema: the prompt is a plain accept/decline."""


class ShareJournalEntriesConsent(BaseModel):
    """Empty schema: the prompt is a plain accept/decline."""


class ShareQueryRowsConsent(BaseModel):
    """Empty schema: the prompt is a plain accept/decline."""


class BookReceiptConsent(BaseModel):
    """Empty schema: the prompt is a plain accept/decline."""
