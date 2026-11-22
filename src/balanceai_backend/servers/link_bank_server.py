"""
BalanceAI Link Bank MCP Server

Provides tools for managing bank accounts, transactions, and categories —
whether sourced from uploaded statement PDFs or synced from Plaid.
"""

import json
import logging
from datetime import date
from pathlib import Path

import plaid
from appdevcommons.hash_generator import HashGenerator
from botocore.exceptions import BotoCoreError, ClientError  # type: ignore[import-untyped]
from mcp.server.fastmcp import Context, FastMCP

import balanceai_backend.parsers.chase  # noqa: F401 - register parser
from balanceai_backend.bank_link.link import run_plaid_link_flow
from balanceai_backend.bank_link.linked_banks import (
    find_linked_bank,
    handle_already_linked_bank,
    resolve_duplicate_link,
    update_link,
)
from balanceai_backend.bank_link.plaid_item_db import find_plaid_items as db_find_plaid_items
from balanceai_backend.config import settings
from balanceai_backend.constants import DEFAULT_CATEGORIES
from balanceai_backend.dagger.aws import AWSClients
from balanceai_backend.db.bank_account_db import find_bank_accounts as db_find_bank_accounts
from balanceai_backend.helpers.plaid_helper import save_linked_plaid_item
from balanceai_backend.models import Account, AccountType, Bank, Category, LegacyTransaction
from balanceai_backend.models.consent import ShareTransactionsConsent
from balanceai_backend.parsers import get_parser
from balanceai_backend.prompts.categorizer import build_categorization_prompt
from balanceai_backend.services.plaid import plaid_error_code
from balanceai_backend.source_transactions.process_source_transactions import (
    classify_and_book_transactions,
)
from balanceai_backend.source_transactions.source_transaction_db import (
    find_source_transactions as db_find_source_transactions,
)
from balanceai_backend.source_transactions.sync_source_transactions_from_plaid import (
    sync_source_transactions_from_plaid,
)
from balanceai_backend.statements.storage import (
    load_accounts,
    load_transactions_by_account,
    save_account,
    save_transactions_by_account,
    update_transaction,
)

logger = logging.getLogger(__name__)


def _log_to_file() -> None:
    """Log every balanceai_backend module the server uses (not just this file)
    to a file next to the bookkeeping server's, so sync and classification
    problems can be read afterwards. Called on startup only, so tests that
    import this module don't write to the real log."""
    log_path = Path(__file__).resolve().parents[3] / "logs" / "link_bank_server.log"
    log_path.parent.mkdir(exist_ok=True)
    package_logger = logging.getLogger("balanceai_backend")
    package_logger.setLevel(logging.INFO)
    handler = logging.FileHandler(log_path, mode="a")
    handler.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))
    package_logger.addHandler(handler)


# TODO: the "after sync_bank_transactions" guideline below is a stopgap for a skill
# that runs link bank -> sync transactions -> journal -> journal entries end to
# end (docs/BACKLOGS.md BL-6). Extend it to ask which accounts to include.
mcp = FastMCP(
    "balanceai_link_bank",
    instructions="""
    BalanceAI Link Bank is an MCP server for managing bank accounts and transactions,
    from either uploaded statement PDFs or banks linked via Plaid.

    General behavioral guidelines for the MCP client:
    - When a user asks to categorize a transaction, ALWAYS ask the user for a category object
      before calling categorize_transaction. Only proceed without one if the user explicitly
      says they don't have a category to provide.
    - Monetary amounts are in USD unless otherwise noted.
    - link_bank opens a browser window and blocks for up to 5 minutes while the user
      logs into their bank on Plaid's hosted page — tell the user to check their
      browser after calling it. The Plaid access token is never returned by any tool.
    - Never link a bank that's already linked: pass the bank's name to link_bank,
      which checks. To get new transactions use sync_bank_transactions; to log in
      again or add/remove accounts use update_bank_link.
    - get_bank_transactions asks the user to approve sharing transaction data before
      returning it. If the user declines, do not retry unless they ask you to.
    - After sync_bank_transactions, check whether the synced bank's accounts are in a
      journal (set of books): call the bookkeeping server's list_journals and look at
      each journal's bank_account_ids. For accounts in no journal, ask the user which
      journal they belong in, or whether to leave any out. Offer the existing
      journals, or creating a new one — suggest the name "Personal" if there are
      none. Create a journal (create_journal) only once the user has confirmed its
      name, and add accounts with create_journal or update_journal's
      bank_account_ids — update_journal replaces the whole list, so include the
      accounts already there. Transactions in a journal's accounts are booked
      automatically, on every sync and when accounts are added with create_journal
      or update_journal.
    """,
)

_aws_clients = AWSClients(region_name=settings.aws_region)
if not _aws_clients.is_initialized():
    _aws_clients.initialize()
settings.set_aws_clients(_aws_clients)


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
    balance: float | None = None,
    categories: list[Category] | None = None,
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
def get_balance(account_id: str | None = None) -> list[dict]:
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
    account_id: str | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
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
def categorize_transaction(account: dict, transaction: dict, category: str | None = None) -> dict:
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
    txn = LegacyTransaction.from_dict(transaction)
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
        except (ClientError, BotoCoreError, json.JSONDecodeError, KeyError, IndexError) as e:
            logger.error(f"Bedrock categorization failed: {e}")
            return {"error": f"AI categorization failed: {e!s}"}

    updated = update_transaction(txn.id, category=category)
    if not updated:
        return {"error": f"Failed to update transaction {txn.id}"}

    return {"success": True, "transaction_id": txn.id, "category": category}


@mcp.tool()
def link_bank(bank_name: str | None = None) -> dict:
    """
    Connect a bank via Plaid Hosted Link.

    Pass bank_name whenever the user names the bank (e.g. "Acme Bank"). If that
    bank is already linked, it isn't linked again:
    - its login needs fixing: opens Plaid to log in again on the same
      connection (as update_bank_link); the result has "updated": True.
    - otherwise nothing opens; the result has "already_linked": True. With no
      error_code, ask the user what they want: sync new transactions
      (sync_bank_transactions), add or remove accounts (update_bank_link with
      add_accounts=True), or log in again (update_bank_link). With an
      error_code, the bank has a problem logging in again won't fix (e.g. it's
      down): tell the user to try again later.
    To connect a different login at a bank that's already linked (e.g. a
    joint account under someone else's login), call it without bank_name.

    Opens a Plaid-hosted webpage in the browser where the user logs into their
    bank — the MCP client should tell the user to check their browser and log
    in. Blocks for up to 5 minutes while polling for completion. The resulting
    access token is written straight to local storage and never returned here.

    Args:
        bank_name: The bank the user named, if any.

    Returns:
        dict with item_id, institution_name, and bank_accounts: {"saved": [bank
        account ids], "skipped": [{"plaid_account_id", "display_name", "reason"}]} —
        accounts that couldn't be added (unsupported type, no last 4 digits, or an
        id clash) are listed under skipped. Plus "updated": True if an already
        linked bank's login was fixed. Or, if nothing was opened:
        {"already_linked": True, "item_id", "institution_name", "error_code"}.
        Or, if the new link duplicated a bank that's already linked, it isn't
        kept: {"duplicate_removed": True, "item_id", "institution_name",
        "message"}. Pass the message on; with "login_required": True, offer
        to log in again with update_bank_link.

    Raises:
        LinkExitedError: if the user exits Hosted Link, or Plaid reports an error.
        TimeoutError: if the user doesn't complete the connection within 5 minutes.
    """
    # TODO: plaid.ApiException from here reaches the user as is; raise a plain,
    # non-technical error instead (see sync_bank_transactions).
    linked = find_linked_bank(bank_name) if bank_name else None
    if linked is not None:
        response = handle_already_linked_bank(linked)
        if response is not None:
            return response

    item = run_plaid_link_flow()
    duplicate = resolve_duplicate_link(item)
    if duplicate is not None:
        return duplicate
    bank_accounts = save_linked_plaid_item(item)
    return {
        "item_id": item.item_id,
        "institution_name": item.institution_name,
        "bank_accounts": bank_accounts,
    }


@mcp.tool()
def update_bank_link(item_id: str, add_accounts: bool = False) -> dict:
    """
    Fix or change a bank that's already linked, instead of linking it again
    (a new link would create a second connection for the same accounts).
    Opens a Plaid page in the browser like link_bank; tell the user to check
    their browser.

    Use it when:
    - A sync says the bank needs the user to log in again (expired login,
      changed password, or access revoked at the bank): add_accounts=False.
      This also renews the bank's consent when it's close to expiring.
    - The user wants to add accounts (e.g. one opened since, or one not
      picked when linking) or stop syncing some: add_accounts=True, to show
      the account picker. Some banks show the picker either way.

    The connection stays the same, so syncing continues where it left off,
    with nothing synced twice. Afterwards, ask the user whether to sync now
    (sync_bank_transactions); added accounts' transactions come in then.

    Args:
        item_id: The linked bank (see list_linked_banks).
        add_accounts: Show the account picker.

    Returns:
        dict with item_id, institution_name, and bank_accounts {"saved",
        "skipped"}: the accounts after the update.

    Raises:
        ValueError: if no bank with that item_id is linked.
        LinkExitedError: if the user exits, or Plaid reports an error.
        TimeoutError: if the user doesn't finish within 5 minutes.
    """
    items = db_find_plaid_items(item_id=item_id)
    if not items:
        raise ValueError("That bank isn't linked. See list_linked_banks.")
    # TODO: plain error for plaid.ApiException (see sync_bank_transactions).
    return update_link(items[0], add_accounts=add_accounts)


@mcp.tool()
def list_linked_banks() -> list[dict]:
    """
    List banks linked via Plaid.

    Returns:
        List of linked items with item_id, institution_id, and institution_name.
        Never includes the Plaid access_token — that stays server-side.
    """
    items = db_find_plaid_items()
    return [
        {
            "item_id": item.item_id,
            "institution_id": item.institution_id,
            "institution_name": item.institution_name,
        }
        for item in items
    ]


@mcp.tool()
def list_bank_accounts(item_id: str | None = None) -> list[dict]:
    """
    List bank accounts — currently those created from banks linked via Plaid.

    Args:
        item_id: Optional Plaid item to filter by (see list_linked_banks).

    Returns:
        List of bank accounts with id, institution_name, account_type, last4,
        display_name, plaid_institution_id, plaid_item_id, and plaid_account_id.
    """
    return [a.to_dict() for a in db_find_bank_accounts(plaid_item_id=item_id)]


@mcp.tool()
def sync_bank_transactions(item_id: str | None = None) -> dict:
    """
    Pull the latest transaction changes for a linked bank via Plaid's /transactions/sync,
    classify that bank's transactions that aren't classified yet, then book every
    journal holding one of its accounts.
    The access token never leaves the server — pass the item_id from list_linked_banks.

    Args:
        item_id: The Plaid item to sync. Optional if exactly one bank is linked, in
            which case that item is used automatically. Required once more than one
            bank is linked — look it up via list_linked_banks.

    Returns:
        dict with transaction counts {"added", "modified", "removed"} plus
        "bank_accounts": {"saved", "skipped"} — the bank accounts created/updated
        from the item first — "matched" (receipts merged with their bank
        transaction), "classification": {"classified",
        "unclassified", "errors"}, and "booking": {journal_id: {"booked",
        "transfers_paired"} or {"error"}}. Classification and booking problems are
        reported there rather than raised; the pulled transactions are saved
        either way.

    Raises:
        ValueError: if a transaction belongs to a Plaid account that has no bank
            account (it was skipped at link/sync time).
    """
    if item_id is None:
        items = db_find_plaid_items()
        if not items:
            raise ValueError("No banks are linked yet.")
        if len(items) > 1:
            raise ValueError("Multiple banks are linked — specify item_id (see list_linked_banks).")
        item_id = items[0].item_id
    try:
        result = sync_source_transactions_from_plaid(item_id)
    except plaid.ApiException as e:
        if plaid_error_code(e) == "ITEM_LOGIN_REQUIRED":
            raise ValueError("Your bank needs you to log in again before it can sync.") from e
        # TODO: raise a plain, non-technical error instead of Plaid's (log only its
        # error_code). Same for link_bank and update_bank_link.
        raise
    # TODO: classifying and booking here makes a first sync with a lot of history one long
    # tool call. Move it to event-driven syncing or a workflow engine.
    # See docs/BACKLOGS.md BL-7.
    result.update(classify_and_book_transactions(item_id))
    return result


@mcp.tool()
async def get_bank_transactions(
    ctx: Context,
    item_id: str | None = None,
    account_id: str | None = None,
) -> list[dict]:
    """
    Query Plaid transactions already pulled down by sync_bank_transactions.

    Transactions are private, so the user is asked to approve sharing them before any
    are returned.

    Args:
        item_id: Filter to a specific linked bank
        account_id: Filter to a specific bank account (BankAccount id)

    Returns:
        List of transactions with id, account_id, date, description, amount, and category

    Raises:
        PermissionError: if the user declines or cancels the approval prompt.
    """
    transactions = db_find_source_transactions(
        plaid_item_id=item_id, account_id=account_id, source="plaid"
    )
    if not transactions:
        return []

    dates = [d for t in transactions if (d := t.posting_date or t.transaction_date)]
    result = await ctx.elicit(
        message=(
            f"Share {len(transactions)} bank transactions "
            f"({min(dates).isoformat()} to {max(dates).isoformat()}) with the assistant?"
        ),
        schema=ShareTransactionsConsent,
    )
    if result.action != "accept":
        raise PermissionError("User declined to share bank transactions.")
    return [t.to_dict() for t in transactions]


if __name__ == "__main__":
    _log_to_file()
    mcp.run()
