import logging
import json
from pathlib import Path

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    filename="/Users/sl5234/Workspace/BalanceAI/logs/storage.log",
    filemode="a",
)
logger = logging.getLogger(__name__)

from balanceai.models import Account, Transaction

DATA_DIR = Path(__file__).parent.parent / "data"


def _ensure_data_dir():
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def load_accounts() -> dict[str, Account]:
    """Load all accounts from storage."""
    _ensure_data_dir()
    path = DATA_DIR / "accounts.json"

    if not path.exists():
        logger.debug("No accounts found in storage")
        return {}

    with open(path) as f:
        data = json.load(f)

    return {acc_id: Account.from_dict(acc) for acc_id, acc in data.items()}


def save_account(account: Account) -> None:
    """Save or update an account."""
    accounts = load_accounts()
    accounts[account.id] = account

    _ensure_data_dir()
    path = DATA_DIR / "accounts.json"

    with open(path, "w") as f:
        json.dump({acc_id: acc.to_dict() for acc_id, acc in accounts.items()}, f, indent=2)


def _load_all_transactions() -> dict[str, list[Transaction]]:
    """Load all transactions from storage, grouped by account_id."""
    _ensure_data_dir()
    path = DATA_DIR / "transactions.json"

    if not path.exists():
        logger.debug("No transactions found in storage")
        return {}

    with open(path) as f:
        data = json.load(f)

    return {
        account_id: [Transaction.from_dict(t) for t in txns]
        for account_id, txns in data.items()
    }


def _save_all_transactions(all_transactions: dict[str, list[Transaction]]) -> None:
    """Save all transactions to storage."""
    _ensure_data_dir()
    path = DATA_DIR / "transactions.json"

    with open(path, "w") as f:
        json.dump(
            {
                account_id: [t.to_dict() for t in txns]
                for account_id, txns in all_transactions.items()
            },
            f,
            indent=2,
        )


def load_transactions_by_account(account_id: str | None = None) -> list[Transaction]:
    """Load transactions from storage, optionally filtered by account_id."""
    all_transactions = _load_all_transactions()

    if account_id is not None:
        return all_transactions.get(account_id, [])

    # Return all transactions flattened
    return [t for txns in all_transactions.values() for t in txns]


def save_transactions_by_account(account_id: str, transactions: list[Transaction]) -> tuple[list[Transaction], int]:
    """
    Save transactions for an account, skipping duplicates. Transactions are sorted by date.

    Returns:
        Tuple of (all transactions for the account sorted by date, count of new transactions added)
    """
    all_transactions = _load_all_transactions()
    existing = all_transactions.get(account_id, [])
    existing_ids = {t.id for t in existing}

    new_transactions = [t for t in transactions if t.id not in existing_ids]
    account_transactions = sorted(existing + new_transactions)

    all_transactions[account_id] = account_transactions
    _save_all_transactions(all_transactions)

    return account_transactions, len(new_transactions)


def update_transaction(transaction_id: str, **updates) -> bool:
    """
    Update a transaction by ID.

    Returns:
        True if transaction was found and updated
    """
    all_transactions = _load_all_transactions()

    for account_id, transactions in all_transactions.items():
        for txn in transactions:
            if txn.id == transaction_id:
                for key, value in updates.items():
                    if hasattr(txn, key):
                        setattr(txn, key, value)

                _save_all_transactions(all_transactions)
                return True

    return False
