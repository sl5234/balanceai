"""Tests for book_transactions: a journal's classified transactions -> entries."""

import dataclasses
import datetime
import sqlite3
from decimal import Decimal

import pytest
from balanceai_backend.db.bank_account_db import upsert_bank_account
from balanceai_backend.db.connection import create_schema
from balanceai_backend.db.journal_db import (
    find_booked_transactions,
    find_journal_lines,
    save_journal,
)
from balanceai_backend.db.transaction_db import find_transactions, update_transaction
from balanceai_backend.models.bank_account import BankAccount, BankAccountType
from balanceai_backend.models.journal import Journal, JournalAccount
from balanceai_backend.models.source_transaction import (
    Classification,
    ClassifiedBy,
    SourceTransaction,
)
from balanceai_backend.source_transactions.book_transactions import book_transactions
from balanceai_backend.source_transactions.source_transaction_db import (
    delete_source_transaction,
    find_source_transactions,
    upsert_source_transaction,
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


# Each test transaction's classification, by source transaction id: sources
# don't carry one, so _add sets it on the transaction after saving.
_CLASSIFICATIONS: dict[str, Classification | None] = {}


def _txn(
    txn_id: str,
    account_id: str,
    amount: str,
    day: int = 1,
    counter_account: JournalAccount | None = JournalAccount.CASH,
) -> SourceTransaction:
    _CLASSIFICATIONS[txn_id] = (
        None
        if counter_account is None
        else Classification(
            counter_account=counter_account,
            category="test",
            counterparty="Self",
            classified_by=ClassifiedBy.AI,
        )
    )
    return SourceTransaction(
        source_transaction_id=txn_id,
        source="plaid",
        account_id=account_id,
        posting_date=datetime.date(2026, 10, day),
        description=f"Transaction {txn_id}",
        amount=Decimal(amount),
    )


def _add(db, *txns: SourceTransaction) -> None:
    """Save each one, and classify its transaction if it isn't yet."""
    for txn in txns:
        upsert_source_transaction(txn, conn=db)
        [saved] = find_source_transactions(source_transaction_id=txn.source_transaction_id, conn=db)
        [transaction] = find_transactions(transaction_id=saved.transaction_id, conn=db)
        classification = _CLASSIFICATIONS.get(txn.source_transaction_id)
        if transaction.classification is None and classification is not None:
            with db:
                update_transaction(saved.transaction_id, classification=classification, conn=db)


def _purchase(txn_id: str = "coffee", account_id: str = CHECKING) -> SourceTransaction:
    return _txn(txn_id, account_id, "-4.33", counter_account=JournalAccount.NON_ESSENTIALS_EXPENSE)


def _raw_id_by_transaction(db) -> dict[str, str]:
    """Each transaction's source transaction (one each until matching groups them)."""
    return {t.transaction_id: t.source_transaction_id for t in find_source_transactions(conn=db)}


def _entries(db, journal_id: str) -> dict[str, set[str]]:
    """Each entry's id mapped to the source transactions of the transactions on its lines."""
    raw_id = _raw_id_by_transaction(db)
    entries: dict[str, set[str]] = {}
    for line in find_journal_lines(journal_id, conn=db):
        entries.setdefault(line.journal_entry_id, set()).add(raw_id[line.transaction_id])
    return entries


def _entry_txns(db, journal_id: str) -> list[set[str]]:
    return sorted(_entries(db, journal_id).values(), key=sorted)


class TestBookSourceTransactions:
    def test_purchase_is_booked_as_two_lines(self, db, journal_id):
        _add(db, _purchase())

        assert book_transactions(journal_id, db) == {"booked": 1, "transfers_paired": 0}

        lines = find_journal_lines(journal_id, conn=db)
        assert [(e.account, e.debit, e.credit) for e in lines] == [
            (JournalAccount.CASH, Decimal(0), Decimal("4.33")),
            (JournalAccount.NON_ESSENTIALS_EXPENSE, Decimal("4.33"), Decimal(0)),
        ]

    def test_running_again_books_nothing(self, db, journal_id):
        _add(db, _purchase())
        book_transactions(journal_id, db)

        assert book_transactions(journal_id, db) == {"booked": 0, "transfers_paired": 0}
        assert len(find_journal_lines(journal_id, conn=db)) == 2

    def test_skips_unclassified_and_other_accounts(self, db, journal_id):
        _add(
            db,
            _txn("unclassified", CHECKING, "-4.33", counter_account=None),
            _purchase("other-journal", OTHER_JOURNALS),
            _purchase("no-journal", NO_JOURNAL),
        )

        assert book_transactions(journal_id, db) == {"booked": 0, "transfers_paired": 0}
        assert find_journal_lines(journal_id, conn=db) == []

    def test_zero_amount_is_not_booked(self, db, journal_id):
        _add(db, _txn("zero", CHECKING, "0.00"))

        assert book_transactions(journal_id, db) == {"booked": 0, "transfers_paired": 0}

    def test_both_sides_of_a_transfer_are_one_matched_entry(self, db, journal_id):
        _add(db, _txn("out", CHECKING, "-1000", 1), _txn("in", SAVINGS, "1000", 2))

        assert book_transactions(journal_id, db) == {"booked": 2, "transfers_paired": 1}
        assert _entry_txns(db, journal_id) == [{"in", "out"}]

    def test_partner_arriving_later_replaces_the_unmatched_entry(self, db, journal_id):
        _add(db, _txn("out", CHECKING, "-1000", 1))
        book_transactions(journal_id, db)
        assert _entry_txns(db, journal_id) == [{"out"}]

        _add(db, _txn("in", SAVINGS, "1000", 2))

        assert book_transactions(journal_id, db) == {"booked": 2, "transfers_paired": 1}
        assert _entry_txns(db, journal_id) == [{"in", "out"}]

    def test_late_classified_tie_leaves_the_match_alone(self, db, journal_id):
        _add(
            db,
            _txn("out", CHECKING, "-1000", 1),
            _txn("in", SAVINGS, "1000", 2),
            _txn("ally", ALLY, "1000", 2, counter_account=None),
        )
        book_transactions(journal_id, db)

        _add(db, _txn("ally-classified", ALLY, "1000", 2))
        delete_source_transaction("ally", conn=db)

        assert book_transactions(journal_id, db) == {"booked": 1, "transfers_paired": 0}
        assert _entry_txns(db, journal_id) == [{"ally-classified"}, {"in", "out"}]

    def test_a_change_is_booked_again(self, db, journal_id):
        _add(db, _purchase())
        book_transactions(journal_id, db)

        # A date change keeps the classification; an amount change would drop
        # it, and the transaction would wait to be classified again.
        _add(db, dataclasses.replace(_purchase(), posting_date=datetime.date(2026, 10, 2)))
        assert find_booked_transactions(journal_id, db) == {}

        assert book_transactions(journal_id, db) == {"booked": 1, "transfers_paired": 0}
        assert {e.date for e in find_journal_lines(journal_id, conn=db)} == {
            datetime.date(2026, 10, 2)
        }

    def test_removing_one_side_rebooks_the_other_unmatched(self, db, journal_id):
        _add(db, _txn("out", CHECKING, "-1000", 1), _txn("in", SAVINGS, "1000", 2))
        book_transactions(journal_id, db)

        delete_source_transaction("in", conn=db)

        assert book_transactions(journal_id, db) == {"booked": 1, "transfers_paired": 0}
        assert _entry_txns(db, journal_id) == [{"out"}]

    def test_unknown_journal_raises(self, db):
        with pytest.raises(ValueError, match="Journal nope not found"):
            book_transactions("nope", db)


class TestBookingByTransaction:
    """Journal lines point to transactions (one per source transaction for now)."""

    def test_both_lines_of_a_purchase_carry_its_transaction(self, db, journal_id):
        _add(db, _purchase())
        book_transactions(journal_id, db)
        [txn] = find_source_transactions(conn=db)
        assert {line.transaction_id for line in find_journal_lines(journal_id, conn=db)} == {
            txn.transaction_id
        }

    def test_each_line_of_a_transfer_carries_its_own_sides_transaction(self, db, journal_id):
        _add(db, _txn("out", CHECKING, "-1000", 1), _txn("in", SAVINGS, "1000", 2))
        book_transactions(journal_id, db)
        txn_of = {
            t.source_transaction_id: t.transaction_id for t in find_source_transactions(conn=db)
        }
        lines = find_journal_lines(journal_id, conn=db)
        assert {line.transaction_id for line in lines} == {txn_of["out"], txn_of["in"]}
        assert len({line.journal_entry_id for line in lines}) == 1

    def test_changing_one_side_unbooks_the_whole_transfer(self, db, journal_id):
        _add(db, _txn("out", CHECKING, "-1000", 1), _txn("in", SAVINGS, "1000", 2))
        book_transactions(journal_id, db)
        _add(db, dataclasses.replace(_txn("out", CHECKING, "-1000", 1), description="Renamed"))
        assert find_journal_lines(journal_id, conn=db) == []

    def test_booking_twice_adds_nothing(self, db, journal_id):
        _add(db, _purchase())
        book_transactions(journal_id, db)
        assert book_transactions(journal_id, db) == {"booked": 0, "transfers_paired": 0}
