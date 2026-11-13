"""Keep local transaction data in sync with Plaid via /transactions/sync.

Run as: python -m balanceai_backend.source_transactions.sync_source_transactions_from_plaid <item_id>
(syncs only; doesn't classify — the sync_bank_transactions tool does both).
"""

import sqlite3
import sys
from decimal import Decimal

from plaid.model.transaction import Transaction as PlaidTransaction
from plaid.model.transactions_sync_request import TransactionsSyncRequest

from balanceai_backend.bank_link.plaid_item_db import find_plaid_items
from balanceai_backend.bank_link.plaid_sync_cursor_db import (
    get_plaid_sync_cursor,
    update_plaid_sync_cursor,
)
from balanceai_backend.db.bank_account_db import find_bank_accounts
from balanceai_backend.db.connection import conn as _default_conn
from balanceai_backend.helpers.plaid_helper import sync_bank_accounts_from_plaid
from balanceai_backend.models.plaid_sync_cursor import PlaidSyncCursor
from balanceai_backend.models.source_transaction import SourceTransaction
from balanceai_backend.services.plaid import get_client
from balanceai_backend.source_transactions.source_transaction_db import (
    delete_source_transaction_by_plaid_id,
    upsert_source_transaction,
)
from balanceai_backend.utils.general_util import IdPrefix, generate_id


def _to_source_transaction(
    txn: PlaidTransaction, item_id: str, bank_account_id_by_plaid_account_id: dict[str, str]
) -> SourceTransaction:
    """
    Convert a Plaid Transaction into our SourceTransaction.

    Amount sign is flipped: Plaid's own convention (verified against the SDK's
    embedded docs, sourced from Plaid's API reference) is positive = money out
    of the account, negative = money in — the exact opposite of ours
    (negative = debit, positive = credit).

    bank_account_id_by_plaid_account_id maps Plaid's account_id to our
    BankAccount id. Both are stored on the SourceTransaction.

    Raises:
        ValueError: if the transaction's Plaid account has no BankAccount (it
            was skipped when bank accounts were synced).
    """
    bank_account_id = bank_account_id_by_plaid_account_id.get(txn.account_id)
    if bank_account_id is None:
        # TODO: no way yet to attach a BankAccount to a skipped Plaid account.
        # See docs/BACKLOGS.md BL-2.
        raise ValueError(
            f"No bank account for Plaid account {txn.account_id} (transaction "
            f"{txn.transaction_id}). It was skipped when bank accounts were synced — "
            "create that bank account first, then sync again."
        )

    category = category_detailed = category_confidence = None
    pfc = getattr(txn, "personal_finance_category", None)
    if pfc is not None:
        category = getattr(pfc, "primary", None)
        category_detailed = getattr(pfc, "detailed", None)
        category_confidence = getattr(pfc, "confidence_level", None)

    # Plaid's merchant_name (e.g. "Starbucks") when it has one; otherwise its raw
    # name (e.g. "SQ *BLUE BOTTLE 1234 SF", "PAYROLL", "ZELLE PAYMENT TO …").
    # The raw name isn't kept when merchant_name exists. This description is
    # what classification sends to the AI and to the web search.
    description = getattr(txn, "merchant_name", None) or txn.name

    return SourceTransaction(
        # A new id each time; upsert_source_transaction keeps the stored one when
        # this Plaid transaction already exists.
        source_transaction_id=generate_id(IdPrefix.PLAID),
        plaid_transaction_id=txn.transaction_id,
        source="plaid",
        plaid_item_id=item_id,
        account_id=bank_account_id,
        plaid_account_id=txn.account_id,
        posting_date=txn.date,
        description=description,
        # Plaid: positive = money out. Ours: negative = money out (see SourceTransaction.amount).
        amount=-Decimal(str(txn.amount)),
        category=category,
        category_detailed=category_detailed,
        category_confidence=category_confidence,
        pending=txn.pending,
    )


def _apply_sync_page(
    response,
    item_id: str,
    bank_account_id_by_plaid_account_id: dict[str, str],
    conn: sqlite3.Connection,
) -> dict[str, int]:
    """
    Apply one /transactions/sync page to source_transactions: upsert added and
    modified transactions, delete removed ones.

    Returns:
        dict with this page's counts: {"added": int, "modified": int, "removed": int}
    """
    added = getattr(response, "added", None) or []
    modified = getattr(response, "modified", None) or []
    removed = getattr(response, "removed", None) or []

    # TODO: source transactions are kept when a Plaid item is unlinked, so re-linking
    # the same bank saves them again under new Plaid transaction ids.
    # See docs/BACKLOGS.md BL-4.
    for txn in added + modified:
        upsert_source_transaction(
            _to_source_transaction(txn, item_id, bank_account_id_by_plaid_account_id), conn=conn
        )
    for removed_txn in removed:
        delete_source_transaction_by_plaid_id(removed_txn.transaction_id, conn=conn)

    return {"added": len(added), "modified": len(modified), "removed": len(removed)}


def sync_source_transactions_from_plaid(
    item_id: str, conn: sqlite3.Connection = _default_conn
) -> dict:
    """
    Pull the latest transaction changes for a linked Plaid item.

    Loops /transactions/sync while has_more, persisting the cursor after each
    page so an interruption mid-batch doesn't lose progress — not just once at
    the end. Added and modified transactions both go through
    source_transaction_db.upsert_source_transaction (one call handles "new" and
    "changed", and keeps, drops, or flags a changed transaction's
    classification); removed transactions are deleted.

    Bank accounts are created/updated first (sync_bank_accounts_from_plaid),
    and each transaction is saved under its BankAccount id. A transaction whose
    Plaid account has no BankAccount fails the sync; pages already processed
    stay saved and the next sync retries from the failing page.

    Returns:
        dict with transaction counts plus the bank account result:
        {"added": int, "modified": int, "removed": int,
         "bank_accounts": {"saved": int, "skipped": int}}
    """
    items = find_plaid_items(item_id=item_id, conn=conn)
    if not items:
        raise ValueError(f"Plaid item {item_id} not found")
    item = items[0]

    bank_accounts = sync_bank_accounts_from_plaid(item, conn=conn)
    bank_account_id_by_plaid_account_id = {
        a.plaid_account_id: a.id
        for a in find_bank_accounts(plaid_item_id=item_id, conn=conn)
        if a.plaid_account_id is not None
    }

    cursor = get_plaid_sync_cursor(item_id, conn=conn)
    client = get_client()

    counts: dict = {"added": 0, "modified": 0, "removed": 0}
    has_more = True

    while has_more:
        request_kwargs: dict = {"access_token": item.access_token}
        if cursor is not None:
            request_kwargs["cursor"] = cursor
        response = client.transactions_sync(TransactionsSyncRequest(**request_kwargs))

        page_counts = _apply_sync_page(response, item_id, bank_account_id_by_plaid_account_id, conn)
        for key, value in page_counts.items():
            counts[key] += value

        cursor = response.next_cursor
        update_plaid_sync_cursor(PlaidSyncCursor(item_id=item_id, cursor=cursor), conn=conn)
        has_more = bool(getattr(response, "has_more", False))

    counts["bank_accounts"] = {
        "saved": len(bank_accounts["saved"]),
        "skipped": len(bank_accounts["skipped"]),
    }
    return counts


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(
            "Usage: python -m balanceai_backend.source_transactions.sync_source_transactions_from_plaid <item_id>"
        )
        raise SystemExit(2)

    result = sync_source_transactions_from_plaid(sys.argv[1])
    print(
        f"Synced: {result['added']} added, {result['modified']} modified, "
        f"{result['removed']} removed"
    )
