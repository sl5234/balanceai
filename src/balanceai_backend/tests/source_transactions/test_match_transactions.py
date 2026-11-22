import datetime
import sqlite3
from decimal import Decimal

import pytest
from balanceai_backend.db.bank_account_db import upsert_bank_account
from balanceai_backend.db.connection import create_schema
from balanceai_backend.db.journal_db import find_journal_lines, save_journal
from balanceai_backend.db.transaction_db import find_transactions, update_transaction
from balanceai_backend.models.bank_account import BankAccount, BankAccountType
from balanceai_backend.models.journal import Journal, JournalAccount
from balanceai_backend.models.source_transaction import (
    Classification,
    ClassifiedBy,
    SourceTransaction,
)
from balanceai_backend.source_transactions.book_transactions import book_transactions
from balanceai_backend.source_transactions.match_transactions import (
    _clean_name,
    _names_match,
    match_receipts_and_bank_transactions,
)
from balanceai_backend.source_transactions.source_transaction_db import (
    find_source_transactions,
    upsert_source_transaction,
)
from balanceai_backend.source_transactions.transaction_grouping import reject_match

CARD = "test_bank:credit_card:1234"
OTHER_CARD = "test_bank:credit_card:5678"
DAY = datetime.date(2026, 11, 8)


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    create_schema(conn)
    for account_id in (CARD, OTHER_CARD):
        upsert_bank_account(
            BankAccount(
                id=account_id,
                institution_name="Test Bank",
                account_type=BankAccountType.CREDIT_CARD,
                last4=account_id[-4:],
            ),
            conn=conn,
        )
    yield conn
    conn.close()


def _receipt(
    db, sid="receipt-1", amount="-12.50", day=DAY, name="Blue Bottle Coffee Roasters", account=CARD
) -> str:
    upsert_source_transaction(
        SourceTransaction(
            source_transaction_id=sid,
            source="receipt",
            account_id=account,
            transaction_date=day,
            description=name,
            amount=Decimal(amount),
        ),
        conn=db,
    )
    return _txn_of(db, sid)


def _bank(
    db, sid="plaid-1", amount="-12.50", day=DAY, name="SQ *BLUE BOTTLE 1234", account=CARD
) -> str:
    upsert_source_transaction(
        SourceTransaction(
            source_transaction_id=sid,
            source="plaid",
            account_id=account,
            transaction_date=day,
            posting_date=day + datetime.timedelta(days=1),
            description=name,
            amount=Decimal(amount),
            plaid_transaction_id=f"p-{sid}",
        ),
        conn=db,
    )
    return _txn_of(db, sid)


def _txn_of(db, source_transaction_id: str) -> str:
    [s] = find_source_transactions(source_transaction_id=source_transaction_id, conn=db)
    assert s.transaction_id is not None
    return s.transaction_id


def _match(db, **kwargs) -> list[str]:
    return match_receipts_and_bank_transactions(conn=db, **kwargs)


def _merged(db, *source_transaction_ids: str) -> bool:
    return len({_txn_of(db, s) for s in source_transaction_ids}) == 1


class TestMatching:
    def test_receipt_then_bank_transaction_merges_on_sync(self, db):
        _receipt(db)
        _bank(db)
        assert len(_match(db, account_ids=[CARD])) == 1
        assert _merged(db, "receipt-1", "plaid-1")

    def test_bank_transaction_then_receipt_merges_on_upload(self, db):
        _bank(db)
        receipt_txn = _receipt(db)
        assert len(_match(db, receipt_transaction_ids=[receipt_txn])) == 1
        assert _merged(db, "receipt-1", "plaid-1")

    def test_merged_transaction_is_booked_once(self, db):
        journal = Journal(name="Personal", bank_account_ids=[CARD])
        save_journal(journal, db)
        _receipt(db)
        _bank(db)
        [kept] = _match(db)
        with db:
            update_transaction(
                kept,
                classification=Classification(
                    counter_account=JournalAccount.NON_ESSENTIALS_EXPENSE,
                    category="dining",
                    counterparty="Blue Bottle Coffee",
                    classified_by=ClassifiedBy.AI,
                ),
                conn=db,
            )
        book_transactions(journal.journal_id, db)
        lines = find_journal_lines(journal.journal_id, conn=db)
        assert len(lines) == 2 and len({line.journal_entry_id for line in lines}) == 1

    def test_a_tip_up_to_30_percent_merges_and_the_bank_amount_wins(self, db):
        _receipt(db, amount="-40.00")
        _bank(db, amount="-48.00")
        [kept] = _match(db)
        [txn] = find_transactions(transaction_id=kept, conn=db)
        assert txn.amount == Decimal("-48.00")

    @pytest.mark.parametrize("bank_amount", ["-53.00", "-38.00"], ids=["over_30pct", "below"])
    def test_amounts_outside_the_range_dont_merge(self, db, bank_amount):
        _receipt(db, amount="-40.00")
        _bank(db, amount=bank_amount)
        assert _match(db) == []

    @pytest.mark.parametrize(("days", "merges"), [(-3, False), (-2, True), (7, True), (8, False)])
    def test_the_date_window(self, db, days, merges):
        _receipt(db)
        _bank(db, day=DAY + datetime.timedelta(days=days))
        assert bool(_match(db)) is merges

    def test_different_merchants_dont_merge(self, db):
        _receipt(db, name="Blue Bottle Coffee")
        _bank(db, name="PHILZ COFFEE")
        assert _match(db) == []

    def test_different_accounts_dont_merge(self, db):
        _receipt(db)
        _bank(db, account=OTHER_CARD)
        assert _match(db) == []

    def test_two_receipts_and_one_bank_transaction_is_ambiguous(self, db):
        _receipt(db, "receipt-1", amount="-5.00")
        _receipt(db, "receipt-2", amount="-5.00")
        _bank(db, amount="-5.00")
        assert _match(db) == []

    def test_one_receipt_and_two_bank_transactions_is_ambiguous(self, db):
        _receipt(db, amount="-5.00")
        _bank(db, "plaid-1", amount="-5.00")
        _bank(db, "plaid-2", amount="-5.00")
        assert _match(db) == []

    def test_unambiguous_pairs_merge_next_to_each_other(self, db):
        _receipt(db, "receipt-a", amount="-12.50")
        _receipt(db, "receipt-b", amount="-6.00", name="Philz Coffee")
        _bank(db, "plaid-x", amount="-12.50")
        _bank(db, "plaid-y", amount="-6.00", name="PHILZ COFFEE 0042")
        assert len(_match(db)) == 2
        assert _merged(db, "receipt-a", "plaid-x") and _merged(db, "receipt-b", "plaid-y")

    def test_a_rejected_pair_isnt_merged(self, db):
        receipt_txn = _receipt(db)
        bank_txn = _bank(db)
        reject_match(receipt_txn, bank_txn, conn=db)
        assert _match(db) == []

    def test_a_refund_receipt_matches_a_refund_credit(self, db):
        _receipt(db, amount="12.50")
        _bank(db, amount="12.50")
        assert len(_match(db)) == 1

    def test_a_purchase_doesnt_match_a_refund(self, db):
        _receipt(db, amount="-12.50")
        _bank(db, amount="12.50")
        assert _match(db) == []

    def test_already_merged_transactions_are_left_alone(self, db):
        _receipt(db)
        _bank(db)
        _match(db)
        assert _match(db) == []
        assert len(find_transactions(conn=db)) == 1


@pytest.mark.parametrize(
    ("receipt_name", "bank_name", "match"),
    [
        ("Blue Bottle Coffee Roasters", "SQ *BLUE BOTTLE 1234", True),
        ("Whole Foods Market", "Whole Foods", True),
        ("Trader Joe's", "TRADER JOE S #552", True),
        ("Blue Bottle Coffee", "Philz Coffee", False),
        ("", "Blue Bottle", False),
    ],
)
def test_names_match(receipt_name, bank_name, match):
    assert _names_match(receipt_name, bank_name) is match


def test_clean_name_drops_prefix_digits_and_punctuation():
    assert _clean_name("TST* Blue-Bottle #42") == "blue bottle"
