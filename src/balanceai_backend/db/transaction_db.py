import json
import sqlite3

from balanceai_backend.db.connection import conn as _default_conn
from balanceai_backend.db.journal_db import delete_journal_entries_for_transaction
from balanceai_backend.models.source_transaction import Classification
from balanceai_backend.models.transaction import Transaction
from balanceai_backend.utils.general_util import IdPrefix, generate_id, utc_now_iso

# Sources that are the bank's own record, so their date is the posted date.
_BANK_SOURCES = {"plaid", "bank_statement"}

# The merged fields, in table order.
_FIELDS = (
    "account_id",
    "transaction_date",
    "posted_date",
    "amount",
    "description",
    "category",
    "card_last4",
    "tax",
    "tip",
)


# Fields a caller may set with update_transaction; the rest come from the
# source transactions (refresh_transaction).
_SETTABLE = {"classification"}


def _build_transaction_row(row) -> Transaction:
    d = dict(row)
    d["classification"] = json.loads(d["classification"]) if d["classification"] else None
    return Transaction.from_dict(d)


def _serialize_classification(classification: Classification | None) -> str | None:
    return json.dumps(classification.to_dict()) if classification is not None else None


def create_transaction(conn: sqlite3.Connection = _default_conn) -> str:
    """Save a new, empty transaction and return its id ('txn-<uuid>'); its
    fields are filled by refresh_transaction. Doesn't commit; call inside the
    caller's transaction."""
    transaction_id = generate_id(IdPrefix.TRANSACTION)
    now = utc_now_iso()
    conn.execute(
        "INSERT INTO transactions (transaction_id, created_at, updated_at) VALUES (?, ?, ?)",
        (transaction_id, now, now),
    )
    return transaction_id


def find_transactions(
    transaction_id: str | None = None,
    account_ids: list[str] | None = None,
    plaid_item_id: str | None = None,
    unclassified: bool = False,
    conn: sqlite3.Connection = _default_conn,
) -> list[Transaction]:
    """Find transactions, optionally by id, by account (any of account_ids), by
    Plaid item (transactions with a source transaction from it), or only the
    unclassified ones. Ordered by transaction date."""
    query = "SELECT * FROM transactions WHERE 1=1"
    params: list = []
    if transaction_id is not None:
        query += " AND transaction_id = ?"
        params.append(transaction_id)
    if account_ids is not None:
        query += f" AND account_id IN ({', '.join('?' * len(account_ids))})"
        params.extend(account_ids)
    if plaid_item_id is not None:
        query += (
            " AND transaction_id IN"
            " (SELECT transaction_id FROM source_transactions WHERE plaid_item_id = ?)"
        )
        params.append(plaid_item_id)
    if unclassified:
        query += " AND classification IS NULL"
    rows = conn.execute(query + " ORDER BY transaction_date, created_at", params).fetchall()
    return [_build_transaction_row(row) for row in rows]


def update_transaction(
    transaction_id: str, conn: sqlite3.Connection = _default_conn, **changes
) -> None:
    """Set some of a transaction's own fields: classification now; later the
    user's corrections (BL-10). Sets updated_at and unbooks the transaction
    (the next booking run books it again). Doesn't commit.

    Raises:
        ValueError: for a field that can't be set, or a transaction that
            doesn't exist.
    """
    if not changes:
        return
    unknown = set(changes) - _SETTABLE
    if unknown:
        raise ValueError(f"Can't set {sorted(unknown)} on a transaction")
    values = {
        field: _serialize_classification(value) if field == "classification" else value
        for field, value in changes.items()
    }
    cursor = conn.execute(
        f"UPDATE transactions SET {', '.join(f'{f} = ?' for f in values)}, updated_at = ?"
        " WHERE transaction_id = ?",
        (*values.values(), utc_now_iso(), transaction_id),
    )
    if cursor.rowcount == 0:
        raise ValueError(f"Transaction {transaction_id} not found")
    delete_journal_entries_for_transaction(transaction_id, conn)


def refresh_transaction(transaction_id: str, conn: sqlite3.Connection = _default_conn) -> None:
    """Recompute the transaction's fields from its source transactions, or
    delete it when none are left. For now each transaction has one source
    transaction, so each field is copied from it; matching will add per-field
    rules. Sets updated_at only when a value changed. Doesn't commit."""
    source = conn.execute(
        "SELECT source, account_id, posting_date, amount, description, category,"
        " card_last4, tax, tip FROM source_transactions WHERE transaction_id = ?"
        " ORDER BY created_at LIMIT 1",
        (transaction_id,),
    ).fetchone()
    if source is None:
        conn.execute("DELETE FROM transactions WHERE transaction_id = ?", (transaction_id,))
        return

    merged = {
        "account_id": source["account_id"],
        "transaction_date": source["posting_date"],
        "posted_date": source["posting_date"] if source["source"] in _BANK_SOURCES else None,
        "amount": source["amount"],
        "description": source["description"],
        "category": source["category"],
        "card_last4": source["card_last4"],
        "tax": source["tax"],
        "tip": source["tip"],
    }
    current = conn.execute(
        f"SELECT {', '.join(_FIELDS)} FROM transactions WHERE transaction_id = ?",
        (transaction_id,),
    ).fetchone()
    if current is not None and dict(current) == merged:
        return
    conn.execute(
        f"UPDATE transactions SET {', '.join(f'{f} = ?' for f in _FIELDS)}, updated_at = ?"
        " WHERE transaction_id = ?",
        (*(merged[f] for f in _FIELDS), utc_now_iso(), transaction_id),
    )
