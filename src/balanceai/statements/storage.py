import json
from pathlib import Path

from balanceai.models import Account, Transaction

DATA_DIR = Path(__file__).parent.parent / "data"


def _ensure_data_dir():
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def load_accounts() -> dict[str, Account]:
    """Load all accounts from storage."""
    _ensure_data_dir()
    path = DATA_DIR / "accounts.json"

    if not path.exists():
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


def load_transactions() -> list[Transaction]:
    """Load all transactions from storage."""
    _ensure_data_dir()
    path = DATA_DIR / "transactions.json"

    if not path.exists():
        return []

    with open(path) as f:
        data = json.load(f)

    return [Transaction.from_dict(t) for t in data]


def save_transactions(transactions: list[Transaction]) -> int:
    """
    Save transactions, skipping duplicates.

    Returns:
        Number of new transactions added
    """
    existing = load_transactions()
    existing_ids = {t.id for t in existing}

    new_transactions = [t for t in transactions if t.id not in existing_ids]
    all_transactions = existing + new_transactions

    _ensure_data_dir()
    path = DATA_DIR / "transactions.json"

    with open(path, "w") as f:
        json.dump([t.to_dict() for t in all_transactions], f, indent=2)

    return len(new_transactions)


def update_transaction(transaction_id: str, **updates) -> bool:
    """
    Update a transaction by ID.

    Returns:
        True if transaction was found and updated
    """
    transactions = load_transactions()

    for txn in transactions:
        if txn.id == transaction_id:
            for key, value in updates.items():
                if hasattr(txn, key):
                    setattr(txn, key, value)

            path = DATA_DIR / "transactions.json"
            with open(path, "w") as f:
                json.dump([t.to_dict() for t in transactions], f, indent=2)
            return True

    return False
