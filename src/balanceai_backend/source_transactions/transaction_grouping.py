"""Group source transactions that are the same transaction under one
transaction (docs/BACKEND_IMPLEMENTATION_DECISIONS.md #19). Each new source
transaction starts its own transaction; matching decides which are the same,
and merge_transactions combines them."""

import dataclasses
import itertools
import sqlite3

from balanceai_backend.db.connection import conn as _default_conn
from balanceai_backend.db.journal_db import delete_journal_entries_for_transaction
from balanceai_backend.db.transaction_db import (
    find_transactions,
    refresh_transaction,
    update_transaction,
)
from balanceai_backend.models.source_transaction import (
    Classification,
    ClassifiedBy,
    MatchedBy,
    SourceTransaction,
)
from balanceai_backend.models.transaction import Transaction
from balanceai_backend.source_transactions.source_transaction_db import (
    find_source_transactions,
)
from balanceai_backend.utils.general_util import utc_now_iso


def merge_transactions(
    transaction_id_a: str,
    transaction_id_b: str,
    matched_by: MatchedBy,
    conn: sqlite3.Connection = _default_conn,
) -> str:
    """Merge two transactions that are the same transaction. The older one
    (created_at) is kept; the newer one's source transactions move to it, and
    the newer one, now empty, is deleted. Both are unbooked (the next booking
    run books the result once); the kept one's fields are recomputed from its
    sources, and its classification follows _user_classification_or_none.

    Returns:
        The kept transaction's id.

    Raises:
        ValueError: if either doesn't exist, they're the same transaction, or
            the merged transaction would have two source transactions from the
            same source or sources on different accounts.
    """
    if transaction_id_a == transaction_id_b:
        raise ValueError(f"Can't merge transaction {transaction_id_a} with itself")
    with conn:
        kept, newer = sorted(
            (_find_transaction(transaction_id_a, conn), _find_transaction(transaction_id_b, conn)),
            key=lambda t: t.created_at or "",
        )
        kept_sources = find_source_transactions(transaction_id=kept.transaction_id, conn=conn)
        moving = find_source_transactions(transaction_id=newer.transaction_id, conn=conn)
        _check_can_merge(kept_sources, moving)

        delete_journal_entries_for_transaction(kept.transaction_id, conn)
        delete_journal_entries_for_transaction(newer.transaction_id, conn)
        now = utc_now_iso()
        conn.executemany(
            "UPDATE source_transactions SET transaction_id = ?,"
            " matched_to_transaction_by = ?, matched_to_transaction_at = ?, updated_at = ?"
            " WHERE source_transaction_id = ?",
            [
                (kept.transaction_id, matched_by.value, now, now, s.source_transaction_id)
                for s in moving
            ],
        )
        refresh_transaction(newer.transaction_id, conn)  # now empty: deleted
        refresh_transaction(kept.transaction_id, conn)
        update_transaction(
            kept.transaction_id,
            classification=_user_classification_or_none(kept.classification, newer.classification),
            conn=conn,
        )
    return kept.transaction_id


def reject_match(
    transaction_id_a: str,
    transaction_id_b: str,
    conn: sqlite3.Connection = _default_conn,
) -> None:
    """Remember that these two transactions aren't the same, so matching never
    merges them. Stored as pairs of their source transactions, since
    transaction ids change when transactions merge. Safe to call again."""
    now = utc_now_iso()
    with conn:
        conn.executemany(
            "INSERT OR IGNORE INTO rejected_matches"
            " (source_transaction_id_a, source_transaction_id_b, created_at, updated_at)"
            " VALUES (?, ?, ?, ?)",
            [(a, b, now, now) for a, b in _source_pairs(transaction_id_a, transaction_id_b, conn)],
        )


def is_rejected_match(
    transaction_id_a: str,
    transaction_id_b: str,
    conn: sqlite3.Connection = _default_conn,
) -> bool:
    """True if the user said any source transaction of one isn't the same as
    any of the other's."""
    return any(
        conn.execute(
            "SELECT 1 FROM rejected_matches"
            " WHERE source_transaction_id_a = ? AND source_transaction_id_b = ?",
            (a, b),
        ).fetchone()
        for a, b in _source_pairs(transaction_id_a, transaction_id_b, conn)
    )


def _find_transaction(transaction_id: str, conn: sqlite3.Connection) -> Transaction:
    """Raises ValueError if it doesn't exist."""
    found = find_transactions(transaction_id=transaction_id, conn=conn)
    if not found:
        raise ValueError(f"Transaction {transaction_id} not found")
    return found[0]


def _check_can_merge(kept: list[SourceTransaction], moving: list[SourceTransaction]) -> None:
    """Raises ValueError if the merged transaction would have two source
    transactions from the same source (e.g. two Plaid rows), or sources on
    different accounts."""
    merged = kept + moving
    sources = [s.source for s in merged]
    if len(sources) != len(set(sources)):
        raise ValueError(f"Merging would give one transaction two {sources} source transactions")
    if len({s.account_id for s in merged}) > 1:
        raise ValueError("Can't merge source transactions on different accounts")


def _user_classification_or_none(
    kept: Classification | None, newer: Classification | None
) -> Classification | None:
    """The user's classification survives a merge (the kept transaction's
    first, else the newer one's), flagged for review since the transaction
    changed. Otherwise None, so it's redone later, in the classify run, with
    all the sources."""
    for classification in (kept, newer):
        if classification is not None and classification.classified_by == ClassifiedBy.USER:
            return dataclasses.replace(classification, needs_user_review=True)
    return None


def _source_pairs(
    transaction_id_a: str, transaction_id_b: str, conn: sqlite3.Connection
) -> list[tuple[str, str]]:
    """Every (a, b) pair across the two transactions' source transactions,
    each ordered so a < b."""
    a_ids = [
        s.source_transaction_id
        for s in find_source_transactions(transaction_id=transaction_id_a, conn=conn)
    ]
    b_ids = [
        s.source_transaction_id
        for s in find_source_transactions(transaction_id=transaction_id_b, conn=conn)
    ]
    return [(min(a, b), max(a, b)) for a, b in itertools.product(a_ids, b_ids)]
