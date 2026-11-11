"""Tests for book_raw_transactions: a journal's classified transactions -> entries."""

import dataclasses
import datetime
import sqlite3
from decimal import Decimal

import pytest
from balanceai_backend.db.bank_account_db import upsert_bank_account
from balanceai_backend.db.connection import create_schema
from balanceai_backend.db.journal_db import (
    find_booked_raw_transactions,
    find_journal_lines,
    save_journal,
)
from balanceai_backend.models.bank_account import BankAccount, BankAccountType
from balanceai_backend.models.journal import Journal, JournalAccount
from balanceai_backend.models.raw_transaction import Classification, ClassifiedBy, RawTransaction
from balanceai_backend.raw_transactions.book_raw_transactions import book_raw_transactions
from balanceai_backend.raw_transactions.raw_transaction_db import (
    delete_raw_transaction,
    upsert_raw_transaction,
)

CHECKING = "chase:checking:0000"
SAVINGS = "chase:savings:1111"
ALLY = "ally:savings:2222"
OTHER_JOURNALS = "chase:checking:3333"
NO_JOURNAL = "chase:checking:4444"


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    create_schema(conn)
    for account_id, account_type in (
        (CHECKING, BankAccountType.CHECKING),
        (SAVINGS, BankAccountType.SAVINGS),
        (ALLY, BankAccountType.SAVINGS),
        (OTHER_JOURNALS, BankAccountType.CHECKING),
        (NO_JOURNAL, BankAccountType.CHECKING),
    ):
        upsert_bank_account(
            BankAccount(
                id=account_id,
                institution_name="Test Bank",
                account_type=account_type,
                last4=account_id[-4:],
            ),
            conn=conn,
        )
    yield conn
    conn.close()


@pytest.fixture
def journal_id(db) -> str:
    personal = Journal(name="Personal", bank_account_ids=[CHECKING, SAVINGS, ALLY])
    save_journal(personal, db)
    save_journal(Journal(name="My LLC", bank_account_ids=[OTHER_JOURNALS]), db)
    return personal.journal_id


def _txn(
    txn_id: str,
    account_id: str,
    amount: str,
    day: int = 1,
    counter_account: JournalAccount | None = JournalAccount.CASH,
) -> RawTransaction:
    return RawTransaction(
        raw_transaction_id=txn_id,
        source="plaid",
        account_id=account_id,
        posting_date=datetime.date(2026, 10, day),
        description=f"Transaction {txn_id}",
        amount=Decimal(amount),
        classification=(
            None
            if counter_account is None
            else Classification(
                counter_account=counter_account,
                category="test",
                counterparty="Self",
                classified_by=ClassifiedBy.AI,
            )
        ),
    )


def _add(db, *txns: RawTransaction) -> None:
    for txn in txns:
        upsert_raw_transaction(txn, conn=db)


def _purchase(txn_id: str = "coffee", account_id: str = CHECKING) -> RawTransaction:
    return _txn(txn_id, account_id, "-4.33", counter_account=JournalAccount.NON_ESSENTIALS_EXPENSE)


def _entries(db, journal_id: str) -> dict[str, set[str]]:
    """Each entry's id mapped to the raw transactions on its lines."""
    entries: dict[str, set[str]] = {}
    for line in find_journal_lines(journal_id, conn=db):
        entries.setdefault(line.journal_entry_id, set()).add(line.raw_transaction_id)
    return entries


def _entry_txns(db, journal_id: str) -> list[set[str]]:
    return sorted(_entries(db, journal_id).values(), key=sorted)


class TestBookRawTransactions:
    def test_purchase_is_booked_as_two_lines(self, db, journal_id):
        _add(db, _purchase())

        assert book_raw_transactions(journal_id, db) == {"booked": 1, "transfers_paired": 0}

        lines = find_journal_lines(journal_id, conn=db)
        assert [(e.account, e.debit, e.credit) for e in lines] == [
            (JournalAccount.CASH, Decimal(0), Decimal("4.33")),
            (JournalAccount.NON_ESSENTIALS_EXPENSE, Decimal("4.33"), Decimal(0)),
        ]

    def test_running_again_books_nothing(self, db, journal_id):
        _add(db, _purchase())
        book_raw_transactions(journal_id, db)

        assert book_raw_transactions(journal_id, db) == {"booked": 0, "transfers_paired": 0}
        assert len(find_journal_lines(journal_id, conn=db)) == 2

    def test_skips_unclassified_and_other_accounts(self, db, journal_id):
        _add(
            db,
            _txn("unclassified", CHECKING, "-4.33", counter_account=None),
            _purchase("other-journal", OTHER_JOURNALS),
            _purchase("no-journal", NO_JOURNAL),
        )

        assert book_raw_transactions(journal_id, db) == {"booked": 0, "transfers_paired": 0}
        assert find_journal_lines(journal_id, conn=db) == []

    def test_zero_amount_is_not_booked(self, db, journal_id):
        _add(db, _txn("zero", CHECKING, "0.00"))

        assert book_raw_transactions(journal_id, db) == {"booked": 0, "transfers_paired": 0}

    def test_both_sides_of_a_transfer_are_one_matched_entry(self, db, journal_id):
        _add(db, _txn("out", CHECKING, "-1000", 1), _txn("in", SAVINGS, "1000", 2))

        assert book_raw_transactions(journal_id, db) == {"booked": 2, "transfers_paired": 1}
        assert _entry_txns(db, journal_id) == [{"in", "out"}]

    def test_partner_arriving_later_replaces_the_unmatched_entry(self, db, journal_id):
        _add(db, _txn("out", CHECKING, "-1000", 1))
        book_raw_transactions(journal_id, db)
        assert _entry_txns(db, journal_id) == [{"out"}]

        _add(db, _txn("in", SAVINGS, "1000", 2))

        assert book_raw_transactions(journal_id, db) == {"booked": 2, "transfers_paired": 1}
        assert _entry_txns(db, journal_id) == [{"in", "out"}]

    def test_late_classified_tie_leaves_the_match_alone(self, db, journal_id):
        _add(
            db,
            _txn("out", CHECKING, "-1000", 1),
            _txn("in", SAVINGS, "1000", 2),
            _txn("ally", ALLY, "1000", 2, counter_account=None),
        )
        book_raw_transactions(journal_id, db)

        _add(db, _txn("ally-classified", ALLY, "1000", 2))
        delete_raw_transaction("ally", conn=db)

        assert book_raw_transactions(journal_id, db) == {"booked": 1, "transfers_paired": 0}
        assert _entry_txns(db, journal_id) == [{"ally-classified"}, {"in", "out"}]

    def test_a_change_is_booked_again(self, db, journal_id):
        _add(db, _purchase())
        book_raw_transactions(journal_id, db)

        # A date change keeps the classification; an amount change would drop
        # it, and the transaction would wait to be classified again.
        _add(db, dataclasses.replace(_purchase(), posting_date=datetime.date(2026, 10, 2)))
        assert find_booked_raw_transactions(journal_id, db) == {}

        assert book_raw_transactions(journal_id, db) == {"booked": 1, "transfers_paired": 0}
        assert {e.date for e in find_journal_lines(journal_id, conn=db)} == {
            datetime.date(2026, 10, 2)
        }

    def test_removing_one_side_rebooks_the_other_unmatched(self, db, journal_id):
        _add(db, _txn("out", CHECKING, "-1000", 1), _txn("in", SAVINGS, "1000", 2))
        book_raw_transactions(journal_id, db)

        delete_raw_transaction("in", conn=db)

        assert book_raw_transactions(journal_id, db) == {"booked": 1, "transfers_paired": 0}
        assert _entry_txns(db, journal_id) == [{"out"}]

    def test_unknown_journal_raises(self, db):
        with pytest.raises(ValueError, match="Journal nope not found"):
            book_raw_transactions("nope", db)
