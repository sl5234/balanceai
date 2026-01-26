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
from balanceai.statements.storage import load_accounts, load_transactions_by_account, save_account, save_transactions_by_account

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

    account_transactions, added = save_transactions_by_account(account.id, transactions)

    # Update account balance from latest transaction
    if account_transactions:
        latest = account_transactions[-1]  # already sorted by date
        account.balance = latest.new_balance

    save_account(account)

    return {"account_id": account.id, "transactions_added": added}


@mcp.tool()
def list_accounts() -> list[dict]:
    """
    List all linked bank accounts.

    Returns:
        List of accounts with id, name, type, and institution
    """
    accounts = load_accounts()
    return [account.to_dict() for account in accounts.values()]


@mcp.tool()
def get_balance(account_id: Optional[str] = None) -> list[dict]:
    """
    Get account balances.

    Args:
        account_id: Optional account ID to filter by

    Returns:
        List of balances with account_id, current, and available amounts
    """
    accounts = load_accounts()

    if account_id is not None:
        accounts = {k: v for k, v in accounts.items() if k == account_id}

    return [
        {
            "account_id": acc.id,
            "current": str(acc.balance) if acc.balance is not None else None,
        }
        for acc in accounts.values()
    ]


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
    transactions = load_transactions_by_account(account_id)

    if start_date is not None:
        transactions = [t for t in transactions if t.date >= start_date]

    if end_date is not None:
        transactions = [t for t in transactions if t.date <= end_date]

    return [t.to_dict() for t in transactions]


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
