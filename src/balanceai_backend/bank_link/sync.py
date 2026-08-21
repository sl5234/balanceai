"""Keep local transaction data in sync with Plaid via /transactions/sync.

Run as: python -m balanceai_backend.bank_link.sync <item_id>
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
from balanceai_backend.db.connection import conn as _default_conn
from balanceai_backend.models.plaid_sync_cursor import PlaidSyncCursor
from balanceai_backend.models.raw_transaction import RawTransaction
from balanceai_backend.raw_transactions.raw_transaction_db import (
    delete_raw_transaction,
    upsert_raw_transaction,
)
from balanceai_backend.services.plaid import get_client


def _to_raw_transaction(txn: PlaidTransaction, item_id: str) -> RawTransaction:
    """
    Convert a Plaid Transaction into our RawTransaction.

    Amount sign is flipped: Plaid's own convention (verified against the SDK's
    embedded docs, sourced from Plaid's API reference) is positive = money out
    of the account, negative = money in — the exact opposite of ours
    (negative = debit, positive = credit).
    """
    category = None
    pfc = getattr(txn, "personal_finance_category", None)
    if pfc is not None:
        category = getattr(pfc, "primary", None)

    description = getattr(txn, "merchant_name", None) or txn.name

    return RawTransaction(
        id=txn.transaction_id,
        source="plaid",
        plaid_item_id=item_id,
        account_id=txn.account_id,
        posting_date=txn.date,
        description=description,
        amount=-Decimal(str(txn.amount)),
        category=category,
        pending=txn.pending,
    )


def sync_transactions(item_id: str, conn: sqlite3.Connection = _default_conn) -> dict:
    """
    Pull the latest transaction changes for a linked Plaid item.

    Loops /transactions/sync while has_more, persisting the cursor after each
    page so an interruption mid-batch doesn't lose progress — not just once at
    the end. Added and modified transactions both go through
    raw_transaction_db.upsert_raw_transaction (SQLite's INSERT OR REPLACE
    handles "new" and "changed" with one call); removed transactions are
    deleted.

    Returns:
        dict with counts: {"added": int, "modified": int, "removed": int}
    """
    items = find_plaid_items(item_id=item_id, conn=conn)
    if not items:
        raise ValueError(f"Plaid item {item_id} not found")
    item = items[0]

    cursor = get_plaid_sync_cursor(item_id, conn=conn)
    client = get_client()

    counts = {"added": 0, "modified": 0, "removed": 0}
    has_more = True

    while has_more:
        request_kwargs: dict = {"access_token": item.access_token}
        if cursor is not None:
            request_kwargs["cursor"] = cursor
        response = client.transactions_sync(TransactionsSyncRequest(**request_kwargs))

        added = getattr(response, "added", None) or []
        modified = getattr(response, "modified", None) or []
        removed = getattr(response, "removed", None) or []

        for txn in added:
            upsert_raw_transaction(_to_raw_transaction(txn, item_id), conn=conn)
        for txn in modified:
            upsert_raw_transaction(_to_raw_transaction(txn, item_id), conn=conn)
        for removed_txn in removed:
            delete_raw_transaction(removed_txn.transaction_id, conn=conn)

        counts["added"] += len(added)
        counts["modified"] += len(modified)
        counts["removed"] += len(removed)

        cursor = response.next_cursor
        update_plaid_sync_cursor(PlaidSyncCursor(item_id=item_id, cursor=cursor), conn=conn)
        has_more = bool(getattr(response, "has_more", False))

    return counts


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python -m balanceai_backend.bank_link.sync <item_id>")
        raise SystemExit(2)

    result = sync_transactions(sys.argv[1])
    print(
        f"Synced: {result['added']} added, {result['modified']} modified, "
        f"{result['removed']} removed"
    )
