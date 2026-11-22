import json
import sqlite3

from balanceai_backend.db.connection import conn as _default_conn
from balanceai_backend.db.journal_db import delete_journal_entries_for_transaction
from balanceai_backend.models.source_transaction import Classification
from balanceai_backend.models.transaction import Transaction
from balanceai_backend.utils.general_util import IdPrefix, generate_id, utc_now_iso

# Sources in order of preference: the bank's record first. For each field the
# first source with a value wins, so receipt-only fields (card, tax, tip) come
# from the receipt (docs/BACKEND_IMPLEMENTATION_DECISIONS.md #21).
_PREFERENCE = ("plaid", "bank_statement", "receipt")

# Except: when it was paid, the receipt knows best.
_TRANSACTION_DATE_PREFERENCE = ("receipt", "plaid", "bank_statement")

# Each transaction field, and the source transaction column it comes from.
_FROM_SOURCE = {
    "account_id": "account_id",
    "transaction_date": "transaction_date",
    "posted_date": "posting_date",
    "amount": "amount",
    "description": "description",
    "category": "category",
    "card_last4": "card_last4",
    "tax": "tax",
    "tip": "tip",
}


# Fields a caller may set with update_transaction; the rest come from the
# source transactions (refresh_transaction).
_SETTABLE = {"classification"}


def _build_transaction_row(row) -> Transaction:
    d = dict(row)
    d["classification"] = json.loads(d["classification"]) if d["classification"] else None
    d["field_sources"] = json.loads(d["field_sources"]) if d["field_sources"] else {}
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
    unclassified ones. Ordered by booking date (transaction date, else posted date)."""
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
    rows = conn.execute(
        query + " ORDER BY COALESCE(transaction_date, posted_date), created_at", params
    ).fetchall()
    return [_build_transaction_row(row) for row in rows]


def find_unmatched_transactions(
    source: str,
    account_ids: list[str] | None = None,
    transaction_ids: list[str] | None = None,
    conn: sqlite3.Connection = _default_conn,
) -> list[Transaction]:
    """Transactions whose only source transaction is from this source (e.g. a
    receipt not yet matched to its bank transaction), optionally limited to
    these accounts and these ids."""
    query = (
        "SELECT t.* FROM transactions t"
        " JOIN source_transactions s ON s.transaction_id = t.transaction_id WHERE 1=1"
    )
    params: list = []
    if account_ids is not None:
        query += f" AND t.account_id IN ({', '.join('?' * len(account_ids))})"
        params.extend(account_ids)
    if transaction_ids is not None:
        query += f" AND t.transaction_id IN ({', '.join('?' * len(transaction_ids))})"
        params.extend(transaction_ids)
    query += " GROUP BY t.transaction_id HAVING COUNT(*) = 1 AND MAX(s.source) = ?"
    params.append(source)
    rows = conn.execute(query, params).fetchall()
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
    delete it when none are left. Each field comes from the first source (in
    _PREFERENCE order; _TRANSACTION_DATE_PREFERENCE for the transaction date)
    that has a value, and field_sources records which. Sets updated_at only
    when something changed. Doesn't commit."""
    rows = conn.execute(
        "SELECT * FROM source_transactions WHERE transaction_id = ? ORDER BY created_at",
        (transaction_id,),
    ).fetchall()
    if not rows:
        conn.execute("DELETE FROM transactions WHERE transaction_id = ?", (transaction_id,))
        return

    merged: dict[str, str | None] = {}
    field_sources: dict[str, str] = {}
    for field, column in _FROM_SOURCE.items():
        order = _TRANSACTION_DATE_PREFERENCE if field == "transaction_date" else _PREFERENCE
        ranked = sorted(
            rows, key=lambda r: order.index(r["source"]) if r["source"] in order else len(order)
        )
        winner = next((r for r in ranked if r[column] is not None), None)
        merged[field] = winner[column] if winner is not None else None
        if winner is not None:
            field_sources[field] = winner["source"]
    merged["field_sources"] = json.dumps(field_sources, sort_keys=True)

    fields = list(merged)
    current = conn.execute(
        f"SELECT {', '.join(fields)} FROM transactions WHERE transaction_id = ?",
        (transaction_id,),
    ).fetchone()
    if current is not None and dict(current) == merged:
        return
    conn.execute(
        f"UPDATE transactions SET {', '.join(f'{f} = ?' for f in fields)}, updated_at = ?"
        " WHERE transaction_id = ?",
        (*(merged[f] for f in fields), utc_now_iso(), transaction_id),
    )
