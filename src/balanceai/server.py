"""
BalanceAI MCP Server

Provides tools for financial data management, mimicking a Plaid-like interface
but backed by manual PDF statement uploads.
"""

from datetime import date
from typing import Optional

from mcp.server.fastmcp import FastMCP

from balanceai.models import Bank
from balanceai.parsers import get_parser
import balanceai.parsers.chase  # noqa: F401 - register parser
from balanceai.statements.storage import save_account, save_transactions

mcp = FastMCP("balanceai")


@mcp.tool()
def upload_statement(file_path: str, bank: Bank) -> dict:
    """
    Parse and store a bank statement PDF.

    Args:
        file_path: Path to the bank statement PDF file
        bank: The bank this statement is from

    Returns:
        dict with account_id and number of transactions added
    """
    parser = get_parser(bank)
    account, transactions = parser.parse(file_path)

    save_account(account)
    added = save_transactions(transactions)

    return {"account_id": account.id, "transactions_added": added}


@mcp.tool()
def list_accounts() -> list[dict]:
    """
    List all linked bank accounts.

    Returns:
        List of accounts with id, name, type, and institution
    """
    # TODO: Load from accounts.json
    return []


@mcp.tool()
def get_balance(account_id: Optional[str] = None) -> list[dict]:
    """
    Get account balances.

    Args:
        account_id: Optional account ID to filter by

    Returns:
        List of balances with account_id, current, and available amounts
    """
    # TODO: Load from accounts.json, filter by account_id
    return []


@mcp.tool()
def get_transactions(
    account_id: Optional[str] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
) -> list[dict]:
    """
    Query transactions with optional filters.

    Args:
        account_id: Filter by account
        start_date: Filter transactions on or after this date
        end_date: Filter transactions on or before this date

    Returns:
        List of transactions with id, date, description, amount, and category
    """
    # TODO: Load from transactions.json
    # TODO: Apply filters
    return []


@mcp.tool()
def categorize_transaction(transaction_id: str, category: str) -> dict:
    """
    Manually set the category for a transaction.

    Args:
        transaction_id: The transaction to update
        category: The category to assign

    Returns:
        dict with success status
    """
    # TODO: Load transactions.json
    # TODO: Find and update transaction
    # TODO: Save back to file
    return {}


if __name__ == "__main__":
    mcp.run()
