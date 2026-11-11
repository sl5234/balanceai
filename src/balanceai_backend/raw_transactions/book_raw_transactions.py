"""Book a journal's classified raw transactions as journal entries; see
docs/BACKEND_IMPLEMENTATION_DECISIONS.md #7, #9, #13 and #15."""

import logging
import sqlite3
from collections import Counter

from balanceai_backend.db.bank_account_db import find_bank_accounts
from balanceai_backend.db.connection import conn as _default_conn
from balanceai_backend.db.journal_db import (
    add_journal_entries,
    delete_journal_entries,
    find_booked_raw_transactions,
    find_journals,
)
from balanceai_backend.models.bank_account import BankAccountType
from balanceai_backend.models.journal import JournalLine
from balanceai_backend.models.raw_transaction import RawTransaction
from balanceai_backend.raw_transactions.generate_journal_entry import (
    generate_journal_entry,
    generate_matched_transfer_entry,
)
from balanceai_backend.raw_transactions.match_transfers import Match, find_matched_transfers
from balanceai_backend.raw_transactions.raw_transaction_db import find_raw_transactions

logger = logging.getLogger(__name__)


def book_raw_transactions(journal_id: str, conn: sqlite3.Connection = _default_conn) -> dict:
    """
    Book the classified raw transactions in a journal's bank accounts that
    aren't booked yet.

    Transfers are matched among the unbooked and the booked-but-unmatched
    transactions (decision #15); a match replaces any unmatched entry either
    side already had. Every other unbooked transaction gets its own entry. A
    change to a transaction deletes its entry when it's written, so whatever
    isn't booked is exactly what needs booking.

    Safe to call repeatedly.

    Returns:
        dict with "booked" (every transaction booked, including both sides of
        each transfer) and "transfers_paired" (transfers between the user's own
        accounts, each booked as one entry from its two transactions).

    Raises:
        ValueError: if the journal doesn't exist.
    """
    account_types = _find_bank_account_types(journal_id, conn)
    txns = _find_classified_transactions(account_types, conn)
    booked = find_booked_raw_transactions(journal_id, conn)

    # TODO: also re-match booked matched transfers in the window, so a
    # late-classified transaction that would have tied undoes the match
    # (decision #16).
    matches = find_matched_transfers(_find_matchable(txns, booked), account_types)
    matched_ids = {t.id for match in matches for t in match}

    skip = booked.keys() | matched_ids
    unmatched = _build_unmatched_entries([t for t in txns if t.id not in skip], account_types)
    replaced = [booked[i] for i in matched_ids if i in booked]
    _save(journal_id, replaced, _build_matched_entries(matches, account_types) + unmatched, conn)

    if matches:
        logger.info("Matched transfers %s", [(o.id, i.id) for o, i in matches])
    if unmatched:
        logger.info("Booked transactions %s", [lines[0].raw_transaction_id for lines in unmatched])
    return {"booked": len(unmatched) + 2 * len(matches), "transfers_paired": len(matches)}


def _find_bank_account_types(
    journal_id: str, conn: sqlite3.Connection
) -> dict[str, BankAccountType]:
    """The journal's bank accounts, each mapped to its account type.

    Raises:
        ValueError: if the journal doesn't exist.
    """
    journals = find_journals(journal_id=journal_id, conn=conn)
    if not journals:
        raise ValueError(f"Journal {journal_id} not found")
    in_journal = set(journals[0].bank_account_ids)
    return {a.id: a.account_type for a in find_bank_accounts(conn=conn) if a.id in in_journal}


def _find_classified_transactions(
    account_types: dict[str, BankAccountType], conn: sqlite3.Connection
) -> list[RawTransaction]:
    """The classified raw transactions in these bank accounts."""
    return [
        t
        for bank_account_id in account_types
        for t in find_raw_transactions(account_id=bank_account_id, conn=conn)
        if t.classification is not None
    ]


def _find_matchable(txns: list[RawTransaction], booked: dict[str, str]) -> list[RawTransaction]:
    """The transactions that can still match: unbooked, or booked unmatched.
    A booked entry with two transactions is already a matched transfer."""
    txns_per_entry = Counter(booked.values())
    return [t for t in txns if t.id not in booked or txns_per_entry[booked[t.id]] == 1]


def _build_matched_entries(
    matches: list[Match], account_types: dict[str, BankAccountType]
) -> list[list[JournalLine]]:
    """One entry per matched transfer."""
    return [
        generate_matched_transfer_entry(
            o, account_types[o.account_id], i, account_types[i.account_id]
        )
        for o, i in matches
    ]


def _build_unmatched_entries(
    txns: list[RawTransaction], account_types: dict[str, BankAccountType]
) -> list[list[JournalLine]]:
    """One entry per transaction; a zero amount has none."""
    entries = []
    for t in txns:
        lines = generate_journal_entry(t, account_types[t.account_id])
        if lines:
            entries.append(lines)
    return entries


def _save(
    journal_id: str,
    replaced_entry_ids: list[str],
    new_entries: list[list[JournalLine]],
    conn: sqlite3.Connection,
) -> None:
    """Delete the unmatched entries the matches replace and add the new
    entries, in one transaction."""
    with conn:
        delete_journal_entries(replaced_entry_ids, conn)
        add_journal_entries(journal_id, new_entries, conn)
