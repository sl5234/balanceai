"""
BalanceAI MCP Server

Provides tools for journal management.
"""

import calendar
import logging
from datetime import date
from typing import Optional

from mcp.server.fastmcp import FastMCP

from balanceai.models import Account, Journal
from balanceai.journals.storage import (
    find_journal_by_id,
    load_journals,
    save_journal,
    update_journal as storage_update_journal,
)
from balanceai.models.journal import JournalEntry, JournalEntryData, JournalEntryInputConfig
from balanceai.utils.general_util import get_mime_type
from balanceai.utils.ocr_util import OcrUtil

logger = logging.getLogger(__name__)

mcp = FastMCP(
    "balanceai_bookkeeping",
    instructions="""
    BalanceAI is a personal finance MCP server for managing journals.

    General behavioral guidelines for the MCP client:
    - Monetary amounts are in USD unless otherwise noted.
    """,
)


@mcp.tool()
def create_journal(
    account: dict,
    description: str,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
) -> dict:
    """
    Create a new journal for a bank account.

    Args:
        account: The bank account object (with id, bank, account_type, balance, categories)
        description: Description of the journal
        start_date: Start date for the journal. Defaults to today.
        end_date: End date for the journal. Defaults to end of current month.

    Returns:
        dict with the created journal
    """
    acct = Account.from_dict(account)

    today = date.today()
    if start_date is None:
        start_date = today
    if end_date is None:
        last_day = calendar.monthrange(today.year, today.month)[1]
        end_date = date(today.year, today.month, last_day)

    journal = Journal(account=acct, description=description, start_date=start_date, end_date=end_date)
    save_journal(journal)
    return journal.to_dict()


@mcp.tool()
def update_journal(
    journal_id: str,
    description: Optional[str] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    entries: Optional[list[dict]] = None,
) -> dict:
    """
    Update a journal's properties by journal ID. Only provided fields are updated.

    Args:
        journal_id: The journal ID of the journal to update
        description: New description for the journal
        start_date: New start date for the journal
        end_date: New end date for the journal
        entries: New list of journal entry objects

    Returns:
        dict with the updated journal
    """
    journal = find_journal_by_id(journal_id)
    if journal is None:
        raise ValueError(f"Journal {journal_id} not found")

    if description is not None:
        journal.description = description
    if start_date is not None:
        journal.start_date = start_date
    if end_date is not None:
        journal.end_date = end_date
    if entries is not None:
        journal.entries = [JournalEntry.from_dict(e) for e in entries]

    storage_update_journal(journal)

    return journal.to_dict()


@mcp.tool()
def list_journals(account_id: Optional[str] = None) -> list[dict]:
    """
    List all journals.

    Args:
        account_id: Optional bank account ID to filter by.

    Returns:
        List of journals with account, description, start_date, end_date, and entries.
    """
    journals = load_journals()
    if account_id is not None:
        journals = [j for j in journals if j.account.id == account_id]
    return [j.to_dict() for j in journals]


@mcp.tool()
def create_journal_entry(
    journal_id: str,
    input_config: JournalEntryInputConfig,
) -> dict:
    """
    Create a journal entry from an input configuration.

    Performs OCR on the provided image to extract transaction details,
    creates a JournalEntry, and adds it to the specified journal.

    Args:
        journal_id: The journal ID to add the entry to
        input_config: Input configuration with input_local_path pointing to an image file

    Returns:
        dict with the updated journal
    """
    journal = find_journal_by_id(journal_id)
    if journal is None:
        raise ValueError(f"Journal {journal_id} not found")

    ocr_result = OcrUtil.executeWithOpenAi(
        content=input_config.input_local_path.read_bytes(),
        output_format=JournalEntryData,
        mime_type=get_mime_type(input_config.input_local_path.suffix),
    )
    entry = ocr_result.to_journal_entry()

    journal.add_entry(entry)
    storage_update_journal(journal)

    return journal.to_dict()


# TODO: Add a tool that identifies recurring transactions over months.  And notifies.
# TODO: Add a tool that identifies a payment that needs to be made.  And proactively check debit account for sufficient funds.  And notifies.


if __name__ == "__main__":
    mcp.run()
