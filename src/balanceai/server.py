"""
BalanceAI MCP Server

Provides tools for financial data management, mimicking a Plaid-like interface
but backed by manual PDF statement uploads.
"""

import json
import logging
from datetime import date
from typing import Optional

from mcp.server.fastmcp import FastMCP

from balanceai.models import Bank, Category
from balanceai.parsers import get_parser
import balanceai.parsers.chase  # noqa: F401 - register parser
from balanceai.prompts.categorizer import build_categorization_prompt
from balanceai.statements.storage import (
    load_accounts,
    load_transactions_by_account,
    save_account,
    save_transactions_by_account,
    update_transaction,
)

logger = logging.getLogger(__name__)

mcp = FastMCP(
    "balanceai",
    instructions="""
    BalanceAI is a personal finance MCP server for managing bank accounts and transactions.

    General behavioral guidelines for the MCP client:
    - When a user asks to categorize a transaction, ALWAYS ask the user for a category object
      before calling categorize_transaction. Only proceed without one if the user explicitly
      says they don't have a category to provide.
    - Monetary amounts are in USD unless otherwise noted.
    """,
)

_bedrock_client = None


def _get_bedrock_client():
    global _bedrock_client
    if _bedrock_client is None:
        import boto3

        _bedrock_client = boto3.client("bedrock-runtime")
    return _bedrock_client


@mcp.resource("balanceai://supported-banks")
def get_supported_banks() -> str:
    """
    List of supported banks and their statement format requirements.
    Use this resource to check which banks BalanceAI can parse statements from.
    """
    return """
    Supported Banks:
    - chase: Chase Bank (PDF statements from chase.com)
    - marcus: Marcus by Goldman Sachs (PDF statements)
    - coinbase: Coinbase (PDF statements)
    - webull: Webull (PDF statements)

    Notes:
    - All statements must be in PDF format.
    - Statements are parsed locally and data is stored on-device.
    """


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

    return {
        "bank": account.bank,
        "account_type": account.account_type,
        "account_id": account.id,
        "transactions_added": added,
    }


@mcp.tool()
def list_accounts() -> list[dict]:
    """
    List all linked bank accounts.

    Returns:
        List of accounts with id, bank, account_type, and balance.
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
def list_categories(account_id: str) -> list[dict]:
    """
    List categories configured for an account.

    Args:
        account_id: The account to get categories for

    Returns:
        List of categories with name and description
    """
    accounts = load_accounts()
    account = accounts.get(account_id)
    if account is None:
        return {"error": f"Account {account_id} not found"}
    return [c.to_dict() for c in account.categories]


@mcp.tool()
def update_categories(account_id: str, categories: list[dict]) -> dict:
    """
    Replace the category list for an account.

    Args:
        account_id: The account to update categories for
        categories: List of category objects, each with 'name' and 'description' keys

    Returns:
        dict with success status
    """
    accounts = load_accounts()
    account = accounts.get(account_id)
    if account is None:
        return {"error": f"Account {account_id} not found"}

    account.categories = [Category.from_dict(c) for c in categories]
    save_account(account)
    return {"success": True, "categories_count": len(account.categories)}


@mcp.tool()
def categorize_transaction(account_id: str, transaction_id: str, category: str) -> dict:
    """
    Manually set the category for a transaction.

    Args:
        account_id: The account the transaction belongs to
        transaction_id: The transaction to update
        category: The category to assign

    Returns:
        dict with success status
    """
    accounts = load_accounts()
    account = accounts.get(account_id)
    if account is None:
        return {"error": f"Account {account_id} not found"}

    transactions = load_transactions_by_account(account_id)
    transaction = next((t for t in transactions if t.id == transaction_id), None)
    if transaction is None:
        return {"error": f"Transaction {transaction_id} not found"}

    # If account has categories configured and no category provided, use Bedrock
    if account.categories and not category:
        prompt = build_categorization_prompt(account.categories, transaction.description)

        try:
            client = _get_bedrock_client()
            response = client.converse(
                modelId="anthropic.claude-3-haiku-20240307-v1:0",
                messages=[{"role": "user", "content": [{"text": prompt}]}],
            )
            response_text = response["output"]["message"]["content"][0]["text"]
            result = json.loads(response_text)
            ai_category = result.get("category", "")

            valid_names = {c.name for c in account.categories}
            if ai_category not in valid_names:
                return {"error": f"AI returned invalid category '{ai_category}'"}

            category = ai_category
        except Exception as e:
            logger.error(f"Bedrock categorization failed: {e}")
            return {"error": f"AI categorization failed: {str(e)}"}

    updated = update_transaction(transaction_id, category=category)
    if not updated:
        return {"error": f"Failed to update transaction {transaction_id}"}

    return {"success": True, "transaction_id": transaction_id, "category": category}


if __name__ == "__main__":
    mcp.run()
