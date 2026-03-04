"""
BalanceAI MCP Server

Provides tools for journal management.
"""

import calendar
import csv
import logging
from datetime import date
from pathlib import Path
from typing import Optional

from mcp.server.fastmcp import FastMCP

from balanceai.dagger.aws import AWSClients
from balanceai.config import settings
from balanceai.models import Account, Journal
from balanceai.journals.storage import (
    find_journal_by_id,
    load_journal_entries,
    load_journals,
    save_journal,
    update_journal as storage_update_journal,
)
from balanceai.helpers.journal_entry_helper import (
    handle_sync_journal_entries_from_receipt,
    handle_sync_journal_entries_from_transactions,
    handle_sync_journal_entries_from_bank_statement,
)
from balanceai.models.journal import JournalEntry

logger = logging.getLogger(__name__)

_aws_clients = AWSClients(region_name=settings.aws_region)
if not _aws_clients.is_initialized():
    _aws_clients.initialize()
settings.set_aws_clients(_aws_clients)

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
def sync_journal_entries_from_receipt(
    journal_id: str,
    input_local_path: str,
) -> dict:
    """
    Create or update journal entries from a receipt image.

    Uses an LLM to perform OCR on the image and extract journal entries using
    double-entry bookkeeping.

    If a matching entry already exists (same date, account, and similar description),
    the existing entry is updated with the latest values — preserving its original ID.
    Otherwise, a new entry is created.

    Args:
        journal_id: The journal ID to add or update entries in
        input_local_path: Local path to the receipt image file

    Returns:
        dict with the updated journal
    """
    from pathlib import Path
    return handle_sync_journal_entries_from_receipt(journal_id, Path(input_local_path))


@mcp.tool()
def sync_journal_entries_from_transactions(
    journal_id: str,
    transactions: dict,
) -> dict:
    """
    Create or update journal entries from Plaid transactions.

    Uses an LLM to map structured transaction data to journal entries with appropriate
    debit/credit/account classifications using double-entry bookkeeping.

    If a matching entry already exists (same date, account, and similar description),
    the existing entry is updated with the latest values — preserving its original ID.
    Otherwise, a new entry is created.

    Args:
        journal_id: The journal ID to add or update entries in
        transactions: Plaid transactions response object (with added, modified, removed, etc.)

    Returns:
        dict with the updated journal
    """
    return handle_sync_journal_entries_from_transactions(journal_id, transactions)


@mcp.tool()
def sync_journal_entries_from_bank_statement(
    journal_id: str,
    file_path: str,
) -> dict:
    """
    Create or update journal entries from a bank statement PDF.

    Parses the PDF using the bank's statement parser, then uses an LLM to map
    each transaction to journal entries using double-entry bookkeeping. The bank
    is inferred from the journal's linked account.

    If a matching entry already exists (same date, account, and similar description),
    the existing entry is updated with the latest values — preserving its original ID.
    Otherwise, a new entry is created.

    Args:
        journal_id: The journal ID to add or update entries in
        file_path: Local path to the bank statement PDF

    Returns:
        dict with the updated journal
    """
    return handle_sync_journal_entries_from_bank_statement(journal_id, file_path)


# TODO: Add a tool that identifies recurring transactions over months.  And notifies.
# TODO: Add a tool that identifies a payment that needs to be made.  And proactively check debit account for sufficient funds.  And notifies.


@mcp.tool()
def list_journal_entries(journal_id: str, date: Optional[date] = None) -> list[dict]:
    """
    List entries for a given journal, optionally filtered by date.

    Args:
        journal_id: The journal ID to retrieve entries for
        date: Optional date to filter entries by

    Returns:
        List of journal entries
    """
    return [e.to_dict() for e in load_journal_entries(journal_id, date=date)]


@mcp.tool()
def publish_journal(journal_id: str, output_dir: str) -> dict:
    """
    Export journal entries to a CSV file.

    The filename is derived from the journal's account bank, account type,
    start date, and end date (e.g. chase_debit_2026-01-01_2026-01-31.csv).

    Args:
        journal_id: The journal ID to export
        output_dir: Local directory path where the CSV will be written

    Returns:
        dict with output_path and number of rows written
    """
    import csv

    journal = find_journal_by_id(journal_id)
    if journal is None:
        raise ValueError(f"Journal {journal_id} not found")

    filename = f"{journal.account.bank.value}_{journal.account.account_type.value}_{journal.start_date}_{journal.end_date}_{journal_id}.csv"
    out = Path(output_dir) / filename
    out.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = ["journal_entry_id", "date", "account", "description", "debit", "credit", "tax"]
    with out.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for entry in journal.entries:
            writer.writerow(entry.to_dict())

    return {"output_path": str(out), "rows_written": len(journal.entries)}


if __name__ == "__main__":
    mcp.run()
