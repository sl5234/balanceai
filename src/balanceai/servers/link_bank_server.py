"""
BalanceAI Link Bank MCP Server

Provides tools for managing bank accounts, transactions, and categories.
"""

import json
import logging
from datetime import date
from typing import Optional

from mcp.server.fastmcp import FastMCP

from appdevcommons.hash_generator import HashGenerator

from balanceai.models import Account, AccountType, Bank, Category, Transaction
from balanceai.parsers import get_parser
import balanceai.parsers.chase  # noqa: F401 - register parser
from balanceai.constants import DEFAULT_CATEGORIES
from balanceai.dagger.aws import AWSClients
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
    "balanceai_link_bank",
    instructions="""
    BalanceAI Link Bank is an MCP server for managing bank accounts and transactions.

    General behavioral guidelines for the MCP client:
    - When a user asks to categorize a transaction, ALWAYS ask the user for a category object
      before calling categorize_transaction. Only proceed without one if the user explicitly
      says they don't have a category to provide.
    - Monetary amounts are in USD unless otherwise noted.
    """,
)

_aws_clients = AWSClients()
if not _aws_clients.is_initialized():
    _aws_clients.initialize()


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
def create_account(
    bank: Bank,
    account_type: AccountType,
    balance: Optional[float] = None,
    categories: Optional[list[Category]] = None,
) -> dict:
    """
    Create a new bank account.

    Args:
        bank: The bank for the account
        account_type: The type of account (debit, credit, saving, investment)
        balance: Optional starting balance
        categories: Optional list of category objects, each with 'name' and 'description' keys

    Returns:
        dict with the created account
    """
    from decimal import Decimal

    account_id = HashGenerator.generate_hash(f"{bank.value}:{account_type.value}")
    account = Account(
        id=account_id,
        bank=bank,
        account_type=account_type,
        balance=Decimal(str(balance)) if balance is not None else None,
        categories=categories or [],
    )
    save_account(account)
    return account.to_dict()


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
        transactions = [t for t in transactions if t.posting_date >= start_date]

    if end_date is not None:
        transactions = [t for t in transactions if t.posting_date <= end_date]

    return [t.to_dict() for t in transactions]


@mcp.tool()
def list_categories(account_id: str) -> list[dict] | dict:
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
def categorize_transaction(
    account: dict, transaction: dict, category: Optional[str] = None
) -> dict:
    """
    Categorize a transaction. If category is omitted, uses AI (Bedrock) to
    auto-categorize based on the account's configured categories. If category
    is provided, it must match one of the account's categories.

    Args:
        account: The account object (with id, bank, account_type, balance, categories)
        transaction: The transaction object (with id, account_id, date, description, amount, etc.)
        category: Optional category name to assign. Omit to auto-categorize via AI.

    Returns:
        dict with success status
    """
    acct = Account.from_dict(account)
    txn = Transaction.from_dict(transaction)
    valid_names = {c.name for c in acct.categories}

    if category is not None:
        # Manual category — must be in the account's category list
        if category not in valid_names:
            return {
                "error": f"Category '{category}' not found in account categories",
                "valid_categories": sorted(valid_names),
            }
    else:
        # AI categorization via Bedrock — fall back to defaults if account has none
        categories = acct.categories or DEFAULT_CATEGORIES
        valid_names = {c.name for c in categories}

        prompt = build_categorization_prompt(categories, txn.description)

        try:
            client = _aws_clients.get_bedrock_runtime_client()
            response = client.converse(
                modelId="anthropic.claude-3-haiku-20240307-v1:0",
                messages=[{"role": "user", "content": [{"text": prompt}]}],
            )
            response_text = response["output"]["message"]["content"][0]["text"]
            result = json.loads(response_text)
            category = result.get("category", "")

            if category not in valid_names:
                return {"error": f"AI returned invalid category '{category}'"}
        except Exception as e:
            logger.error(f"Bedrock categorization failed: {e}")
            return {"error": f"AI categorization failed: {str(e)}"}

    updated = update_transaction(txn.id, category=category)
    if not updated:
        return {"error": f"Failed to update transaction {txn.id}"}

    return {"success": True, "transaction_id": txn.id, "category": category}


if __name__ == "__main__":
    mcp.run()
