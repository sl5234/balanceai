import datetime
import itertools
import sqlite3
from decimal import Decimal
from unittest.mock import patch

import pytest
from balanceai_backend.db.bank_account_db import upsert_bank_account
from balanceai_backend.db.connection import create_schema
from balanceai_backend.db.journal_db import find_journal_lines, save_journal
from balanceai_backend.db.transaction_db import (
    find_transactions,
    refresh_transaction,
    update_transaction,
)
from balanceai_backend.models.bank_account import BankAccount, BankAccountType
from balanceai_backend.models.journal import Journal, JournalAccount
from balanceai_backend.models.source_transaction import (
    Classification,
    ClassifiedBy,
    MatchedBy,
    SourceTransaction,
)
from balanceai_backend.source_transactions.book_transactions import book_transactions
from balanceai_backend.source_transactions.source_transaction_db import (
    find_source_transactions,
    upsert_source_transaction,
)
from balanceai_backend.source_transactions.transaction_grouping import (
    is_rejected_match,
    merge_transactions,
    reject_match,
)

CARD = "test_bank:credit_card:1234"
CHECKING = "test_bank:checking:0000"


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    create_schema(conn)
    for account_id, account_type in (
        (CARD, BankAccountType.CREDIT_CARD),
        (CHECKING, BankAccountType.CHECKING),
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


@pytest.fixture(autouse=True)
def clock():
    """Each new transaction is created a second after the last, so "older" is
    well defined."""
    ticks = (f"2026-01-01T00:00:{n:02d}+00:00" for n in itertools.count(1))
    with patch("balanceai_backend.db.transaction_db.utc_now_iso", side_effect=lambda: next(ticks)):
        yield


def _save(db, source_transaction_id: str, source: str, **fields) -> str:
    """Save a source transaction (its own new transaction); return that transaction's id."""
    upsert_source_transaction(
        SourceTransaction(
            **{
                "source_transaction_id": source_transaction_id,
                "source": source,
                "account_id": CARD,
                "posting_date": datetime.date(2026, 11, 8),
                "description": "Blue Bottle Coffee",
                "amount": Decimal("-12.50"),
                **fields,
            }
        ),
        conn=db,
    )
    [saved] = find_source_transactions(source_transaction_id=source_transaction_id, conn=db)
    assert saved.transaction_id is not None
    return saved.transaction_id


def _classify(db, transaction_id: str, classified_by: ClassifiedBy) -> Classification:
    classification = Classification(
        counter_account=JournalAccount.NON_ESSENTIALS_EXPENSE,
        category="dining",
        counterparty="Blue Bottle Coffee",
        classified_by=classified_by,
    )
    with db:
        update_transaction(transaction_id, classification=classification, conn=db)
    return classification


def _classification_of(db, transaction_id: str) -> Classification | None:
    [txn] = find_transactions(transaction_id=transaction_id, conn=db)
    return txn.classification


class TestMergeTransactions:
    def test_merge_keeps_the_older_and_deletes_the_newer(self, db):
        plaid_txn = _save(db, "plaid-1", "plaid")
        receipt_txn = _save(db, "receipt-1", "receipt")

        kept = merge_transactions(receipt_txn, plaid_txn, MatchedBy.RULE, conn=db)

        assert kept == plaid_txn
        assert [t.transaction_id for t in find_transactions(conn=db)] == [plaid_txn]
        assert {s.source for s in find_source_transactions(transaction_id=kept, conn=db)} == {
            "plaid",
            "receipt",
        }

    def test_moved_sources_record_how_and_when(self, db):
        plaid_txn = _save(db, "plaid-1", "plaid")
        receipt_txn = _save(db, "receipt-1", "receipt")

        merge_transactions(plaid_txn, receipt_txn, MatchedBy.RULE, conn=db)

        by_id = {s.source_transaction_id: s for s in find_source_transactions(conn=db)}
        assert by_id["receipt-1"].matched_to_transaction_by is MatchedBy.RULE
        assert by_id["receipt-1"].matched_to_transaction_at is not None
        assert by_id["plaid-1"].matched_to_transaction_by is None

    def test_two_sources_of_the_same_kind_are_refused(self, db):
        first = _save(db, "plaid-1", "plaid")
        second = _save(db, "plaid-2", "plaid")

        with pytest.raises(ValueError, match="two"):
            merge_transactions(first, second, MatchedBy.RULE, conn=db)
        assert len(find_transactions(conn=db)) == 2

    def test_different_accounts_are_refused(self, db):
        plaid_txn = _save(db, "plaid-1", "plaid")
        receipt_txn = _save(db, "receipt-1", "receipt", account_id=CHECKING)

        with pytest.raises(ValueError, match="different accounts"):
            merge_transactions(plaid_txn, receipt_txn, MatchedBy.RULE, conn=db)

    def test_a_missing_transaction_is_refused(self, db):
        plaid_txn = _save(db, "plaid-1", "plaid")
        with pytest.raises(ValueError, match="not found"):
            merge_transactions(plaid_txn, "txn-missing", MatchedBy.RULE, conn=db)

    def test_merging_a_transaction_with_itself_is_refused(self, db):
        plaid_txn = _save(db, "plaid-1", "plaid")
        with pytest.raises(ValueError, match="itself"):
            merge_transactions(plaid_txn, plaid_txn, MatchedBy.RULE, conn=db)


class TestClassificationAfterMerge:
    def test_ai_classifications_are_cleared(self, db):
        plaid_txn = _save(db, "plaid-1", "plaid")
        receipt_txn = _save(db, "receipt-1", "receipt")
        _classify(db, plaid_txn, ClassifiedBy.AI)
        _classify(db, receipt_txn, ClassifiedBy.AI)

        kept = merge_transactions(plaid_txn, receipt_txn, MatchedBy.RULE, conn=db)

        assert _classification_of(db, kept) is None

    def test_the_users_classification_is_kept_and_flagged(self, db):
        plaid_txn = _save(db, "plaid-1", "plaid")
        receipt_txn = _save(db, "receipt-1", "receipt")
        mine = _classify(db, plaid_txn, ClassifiedBy.USER)
        _classify(db, receipt_txn, ClassifiedBy.AI)

        kept = merge_transactions(plaid_txn, receipt_txn, MatchedBy.RULE, conn=db)

        assert _classification_of(db, kept) == Classification(
            counter_account=mine.counter_account,
            category=mine.category,
            counterparty=mine.counterparty,
            classified_by=ClassifiedBy.USER,
            needs_user_review=True,
        )

    def test_the_users_classification_on_the_newer_one_survives(self, db):
        plaid_txn = _save(db, "plaid-1", "plaid")
        receipt_txn = _save(db, "receipt-1", "receipt")
        _classify(db, receipt_txn, ClassifiedBy.USER)

        kept = merge_transactions(plaid_txn, receipt_txn, MatchedBy.RULE, conn=db)

        classification = _classification_of(db, kept)
        assert classification is not None
        assert classification.classified_by == ClassifiedBy.USER
        assert classification.needs_user_review is True


class TestBookingAndResync:
    def test_a_merged_transaction_is_booked_once(self, db):
        journal = Journal(name="Personal", bank_account_ids=[CARD])
        save_journal(journal, db)
        plaid_txn = _save(db, "plaid-1", "plaid")
        receipt_txn = _save(db, "receipt-1", "receipt")
        _classify(db, plaid_txn, ClassifiedBy.USER)
        book_transactions(journal.journal_id, db)
        assert len(find_journal_lines(journal.journal_id, conn=db)) == 2

        merge_transactions(plaid_txn, receipt_txn, MatchedBy.RULE, conn=db)
        assert find_journal_lines(journal.journal_id, conn=db) == []
        book_transactions(journal.journal_id, db)

        lines = find_journal_lines(journal.journal_id, conn=db)
        assert len(lines) == 2 and len({line.journal_entry_id for line in lines}) == 1

    def test_a_resync_keeps_the_merge(self, db):
        plaid_txn = _save(db, "plaid-1", "plaid")
        receipt_txn = _save(db, "receipt-1", "receipt")
        kept = merge_transactions(plaid_txn, receipt_txn, MatchedBy.RULE, conn=db)

        _save(db, "receipt-1", "receipt")  # the same source transaction, sent again

        [receipt] = find_source_transactions(source_transaction_id="receipt-1", conn=db)
        assert receipt.transaction_id == kept
        assert receipt.matched_to_transaction_by is MatchedBy.RULE


class TestRejectedMatches:
    def test_a_rejected_pair_is_found_from_either_side(self, db):
        plaid_txn = _save(db, "plaid-1", "plaid")
        receipt_txn = _save(db, "receipt-1", "receipt")

        assert not is_rejected_match(plaid_txn, receipt_txn, conn=db)
        reject_match(plaid_txn, receipt_txn, conn=db)
        assert is_rejected_match(receipt_txn, plaid_txn, conn=db)

    def test_a_rejection_covers_sources_added_later(self, db):
        plaid_txn = _save(db, "plaid-1", "plaid")
        receipt_txn = _save(db, "receipt-1", "receipt")
        reject_match(plaid_txn, receipt_txn, conn=db)
        statement_txn = _save(db, "statement-1", "bank_statement")

        kept = merge_transactions(plaid_txn, statement_txn, MatchedBy.RULE, conn=db)

        assert is_rejected_match(kept, receipt_txn, conn=db)


class TestFieldsAcrossSources:
    """Each field comes from the first source with a value: the bank's record
    first (Plaid, statement, receipt); the transaction date prefers the receipt."""

    def _merged(self, db, **receipt_fields):
        plaid_txn = _save(
            db,
            "plaid-1",
            "plaid",
            description="Blue Bottle Coffee",
            amount=Decimal("-48.00"),
            transaction_date=datetime.date(2026, 11, 7),
            posting_date=datetime.date(2026, 11, 9),
            category="FOOD_AND_DRINK",
        )
        receipt_txn = _save(
            db,
            "receipt-1",
            "receipt",
            **{
                "description": "Blue Bottle Coffee Roasters",
                "amount": Decimal("-40.00"),
                "transaction_date": datetime.date(2026, 11, 8),
                "posting_date": None,
                "category": "dining",
                "card_last4": "1234",
                "tax": Decimal("3.20"),
                "tip": None,
                **receipt_fields,
            },
        )
        kept = merge_transactions(plaid_txn, receipt_txn, MatchedBy.RULE, conn=db)
        [txn] = find_transactions(transaction_id=kept, conn=db)
        return txn

    def test_the_bank_wins_amount_posted_date_description_and_category(self, db):
        txn = self._merged(db)
        assert txn.amount == Decimal("-48.00")  # the tip was added after the receipt
        assert txn.posted_date == datetime.date(2026, 11, 9)
        assert txn.description == "Blue Bottle Coffee"
        assert txn.category == "FOOD_AND_DRINK"

    def test_the_receipt_wins_the_transaction_date_and_its_own_fields(self, db):
        txn = self._merged(db)
        assert txn.transaction_date == datetime.date(2026, 11, 8)
        assert txn.booking_date == datetime.date(2026, 11, 8)
        assert (txn.card_last4, txn.tax) == ("1234", Decimal("3.20"))

    def test_field_sources_say_where_each_field_came_from(self, db):
        txn = self._merged(db)
        assert txn.field_sources["amount"] == "plaid"
        assert txn.field_sources["transaction_date"] == "receipt"
        assert txn.field_sources["tax"] == "receipt"
        assert "tip" not in txn.field_sources  # no source has one

    def test_without_a_receipt_date_plaids_authorized_date_is_used(self, db):
        txn = self._merged(db, transaction_date=None, posting_date=datetime.date(2026, 11, 8))
        # (a receipt row always has a date in practice; this checks the fallback)
        assert txn.transaction_date == datetime.date(2026, 11, 7)
        assert txn.field_sources["transaction_date"] == "plaid"

    def test_removing_the_receipt_falls_back_to_plaids_values(self, db):
        txn = self._merged(db)
        with db:
            db.execute("DELETE FROM source_transactions WHERE source_transaction_id = 'receipt-1'")
            refresh_transaction(txn.transaction_id, db)
        [after] = find_transactions(transaction_id=txn.transaction_id, conn=db)
        assert after.transaction_date == datetime.date(2026, 11, 7)
        assert after.tax is None and "tax" not in after.field_sources
