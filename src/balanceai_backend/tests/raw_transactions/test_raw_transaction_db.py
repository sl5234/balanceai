import dataclasses
import datetime
import sqlite3
from decimal import Decimal

import pytest
from balanceai_backend.bank_link.plaid_item_db import delete_plaid_item, save_plaid_item
from balanceai_backend.db.bank_account_db import upsert_bank_account
from balanceai_backend.db.connection import _apply_migrations, create_schema
from balanceai_backend.models.bank_account import BankAccount, BankAccountType
from balanceai_backend.models.journal import JournalAccount
from balanceai_backend.models.plaid_item import PlaidItem
from balanceai_backend.models.raw_transaction import Classification, ClassifiedBy, RawTransaction
from balanceai_backend.raw_transactions.raw_transaction_db import (
    delete_raw_transaction,
    find_raw_transactions,
    update_raw_transaction_classification,
    upsert_raw_transaction,
)


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    create_schema(conn)
    # raw_transactions.account_id references bank_accounts(id)
    for account_id in ("plaid-acc-1", "acc-1", "acc-2", "acct-1"):
        upsert_bank_account(
            BankAccount(
                id=account_id,
                institution_name="Test Bank",
                account_type=BankAccountType.CHECKING,
                last4="0000",
            ),
            conn=conn,
        )
    yield conn
    conn.close()


@pytest.fixture
def linked_item(db):
    item = PlaidItem(item_id="item-1", access_token="access-sandbox-abc")
    save_plaid_item(item, conn=db)
    return item


@pytest.fixture
def sample_txn():
    return RawTransaction(
        id="txn-1",
        source="plaid",
        plaid_item_id="item-1",
        account_id="plaid-acc-1",
        plaid_account_id="plaid-raw-acc-1",
        posting_date=datetime.date(2026, 8, 19),
        description="Starbucks",
        amount=Decimal("-4.50"),
        category="FOOD_AND_DRINK",
        pending=False,
    )


class TestFindRawTransactions:
    def test_returns_empty_list_when_none_saved(self, db, linked_item):
        assert find_raw_transactions(conn=db) == []

    def test_returns_saved_transaction(self, db, linked_item, sample_txn):
        upsert_raw_transaction(sample_txn, conn=db)
        [txn] = find_raw_transactions(conn=db)
        assert txn.id == "txn-1"
        assert txn.description == "Starbucks"
        assert txn.amount == Decimal("-4.50")
        assert txn.plaid_account_id == "plaid-raw-acc-1"

    def test_filters_by_plaid_item_id(self, db):
        save_plaid_item(PlaidItem(item_id="item-1", access_token="a"), conn=db)
        save_plaid_item(PlaidItem(item_id="item-2", access_token="b"), conn=db)
        upsert_raw_transaction(
            RawTransaction(
                id="txn-1",
                source="plaid",
                plaid_item_id="item-1",
                account_id="acc-1",
                posting_date=datetime.date(2026, 8, 19),
                description="A",
                amount=Decimal(1),
            ),
            conn=db,
        )
        upsert_raw_transaction(
            RawTransaction(
                id="txn-2",
                source="plaid",
                plaid_item_id="item-2",
                account_id="acc-2",
                posting_date=datetime.date(2026, 8, 19),
                description="B",
                amount=Decimal(2),
            ),
            conn=db,
        )
        [txn] = find_raw_transactions(plaid_item_id="item-2", conn=db)
        assert txn.id == "txn-2"

    def test_filters_by_account_id(self, db, linked_item, sample_txn):
        upsert_raw_transaction(sample_txn, conn=db)
        assert len(find_raw_transactions(account_id="plaid-acc-1", conn=db)) == 1
        assert find_raw_transactions(account_id="plaid-acc-nonexistent", conn=db) == []

    def test_filters_by_source(self, db, linked_item, sample_txn):
        upsert_raw_transaction(sample_txn, conn=db)
        upsert_raw_transaction(
            RawTransaction(
                id="txn-receipt-1",
                source="receipt",
                plaid_item_id=None,
                account_id="acct-1",
                posting_date=datetime.date(2026, 8, 19),
                description="Grocery receipt",
                amount=Decimal("-30.00"),
            ),
            conn=db,
        )
        [txn] = find_raw_transactions(source="receipt", conn=db)
        assert txn.id == "txn-receipt-1"
        assert txn.plaid_item_id is None


class TestUpsertRawTransaction:
    def test_replaces_existing_transaction_on_same_id(self, db, linked_item, sample_txn):
        """Simulates Plaid's `modified` bucket: same transaction_id, changed fields —
        e.g. a pending charge posting with a finalized amount."""
        upsert_raw_transaction(sample_txn, conn=db)

        modified = RawTransaction(
            id="txn-1",
            source="plaid",
            plaid_item_id="item-1",
            account_id="plaid-acc-1",
            posting_date=datetime.date(2026, 8, 19),
            description="Starbucks",
            amount=Decimal("-4.75"),
            pending=False,
        )
        upsert_raw_transaction(modified, conn=db)

        transactions = find_raw_transactions(conn=db)
        assert len(transactions) == 1
        assert transactions[0].amount == Decimal("-4.75")

    def test_non_plaid_source_allows_null_plaid_item_id(self, db):
        """Confirms plaid_item_id is genuinely nullable — a receipt/bank-statement
        row shouldn't need a fake Plaid item just to satisfy the schema."""
        txn = RawTransaction(
            id="txn-statement-1",
            source="bank_statement",
            plaid_item_id=None,
            account_id="acct-1",
            posting_date=datetime.date(2026, 8, 19),
            description="Check deposit",
            amount=Decimal("500.00"),
        )
        upsert_raw_transaction(txn, conn=db)
        [saved] = find_raw_transactions(conn=db)
        assert saved.plaid_item_id is None
        assert saved.source == "bank_statement"


class TestDeleteRawTransaction:
    def test_removes_transaction(self, db, linked_item, sample_txn):
        upsert_raw_transaction(sample_txn, conn=db)
        delete_raw_transaction("txn-1", conn=db)
        assert find_raw_transactions(conn=db) == []

    def test_silently_no_ops_when_not_found(self, db, linked_item):
        delete_raw_transaction("txn-missing", conn=db)  # should not raise


class TestPlaidItemDeletion:
    def test_deleting_item_keeps_its_transactions_and_clears_item_id(
        self, db, linked_item, sample_txn
    ):
        upsert_raw_transaction(sample_txn, conn=db)
        delete_plaid_item("item-1", conn=db)

        [txn] = find_raw_transactions(conn=db)
        assert txn.id == "txn-1"
        assert txn.plaid_item_id is None
        assert txn.plaid_account_id == "plaid-raw-acc-1"


class TestBankAccountReference:
    def test_rejects_unknown_account_id(self, db, linked_item, sample_txn):
        sample_txn.account_id = "no-such-account"
        with pytest.raises(sqlite3.IntegrityError):
            upsert_raw_transaction(sample_txn, conn=db)

    def test_renaming_bank_account_updates_its_transactions(self, db, linked_item, sample_txn):
        upsert_raw_transaction(sample_txn, conn=db)

        with db:
            db.execute(
                "UPDATE bank_accounts SET id = ? WHERE id = ?", ("renamed-acc", "plaid-acc-1")
            )

        [txn] = find_raw_transactions(conn=db)
        assert txn.account_id == "renamed-acc"


def _classification(classified_by: ClassifiedBy = ClassifiedBy.AI) -> Classification:
    return Classification(
        counter_account=JournalAccount.NON_ESSENTIALS_EXPENSE,
        category="dining",
        counterparty="Starbucks",
        classified_by=classified_by,
    )


class TestClassification:
    def test_new_transaction_is_unclassified(self, db, linked_item, sample_txn):
        upsert_raw_transaction(sample_txn, conn=db)
        [saved] = find_raw_transactions(conn=db)
        assert saved.classification is None

    def test_update_sets_classification(self, db, linked_item, sample_txn):
        upsert_raw_transaction(sample_txn, conn=db)
        update_raw_transaction_classification("txn-1", _classification(), conn=db)
        [saved] = find_raw_transactions(conn=db)
        assert saved.classification == _classification()

    def test_update_with_none_clears_classification(self, db, linked_item, sample_txn):
        upsert_raw_transaction(sample_txn, conn=db)
        update_raw_transaction_classification("txn-1", _classification(), conn=db)
        update_raw_transaction_classification("txn-1", None, conn=db)
        [saved] = find_raw_transactions(conn=db)
        assert saved.classification is None

    def test_update_raises_when_transaction_not_found(self, db):
        with pytest.raises(ValueError, match="txn-missing"):
            update_raw_transaction_classification("txn-missing", _classification(), conn=db)

    def test_find_by_id(self, db, linked_item, sample_txn):
        upsert_raw_transaction(sample_txn, conn=db)
        assert [t.id for t in find_raw_transactions(id="txn-1", conn=db)] == ["txn-1"]
        assert find_raw_transactions(id="txn-missing", conn=db) == []

    def test_find_unclassified_only(self, db, linked_item, sample_txn):
        upsert_raw_transaction(sample_txn, conn=db)
        upsert_raw_transaction(dataclasses.replace(sample_txn, id="txn-2"), conn=db)
        update_raw_transaction_classification("txn-1", _classification(), conn=db)
        assert [t.id for t in find_raw_transactions(unclassified=True, conn=db)] == ["txn-2"]
        assert len(find_raw_transactions(conn=db)) == 2


_CLASSIFIER_INPUT_CHANGES = [
    {"description": "Starbucks Reserve"},
    {"amount": Decimal("-5.25")},
    {"category": "GENERAL_MERCHANDISE"},
    {"category_detailed": "FOOD_AND_DRINK_RESTAURANT"},
]


class TestUpsertKeepsClassification:
    """What happens to a stored classification when the source sends the
    transaction again (Plaid's `modified` bucket)."""

    @staticmethod
    def _resend(db, sample_txn, **changes) -> RawTransaction:
        upsert_raw_transaction(dataclasses.replace(sample_txn, **changes), conn=db)
        [saved] = find_raw_transactions(conn=db)
        return saved

    @pytest.fixture
    def classified_by_ai(self, db, linked_item, sample_txn):
        upsert_raw_transaction(sample_txn, conn=db)
        update_raw_transaction_classification("txn-1", _classification(), conn=db)

    @pytest.fixture
    def classified_by_user(self, db, linked_item, sample_txn):
        upsert_raw_transaction(sample_txn, conn=db)
        update_raw_transaction_classification("txn-1", _classification(ClassifiedBy.USER), conn=db)

    def test_unchanged_resend_keeps_ai_classification(self, db, sample_txn, classified_by_ai):
        assert self._resend(db, sample_txn).classification == _classification()

    def test_unchanged_resend_does_not_flag_user_classification(
        self, db, sample_txn, classified_by_user
    ):
        saved = self._resend(db, sample_txn)
        assert saved.classification == _classification(ClassifiedBy.USER)
        assert saved.classification.needs_user_review is False

    def test_date_or_pending_change_keeps_ai_classification(self, db, sample_txn, classified_by_ai):
        saved = self._resend(db, sample_txn, posting_date=datetime.date(2026, 8, 20), pending=True)
        assert saved.posting_date == datetime.date(2026, 8, 20)
        assert saved.pending is True
        assert saved.classification == _classification()

    def test_date_or_pending_change_does_not_flag_user_classification(
        self, db, sample_txn, classified_by_user
    ):
        saved = self._resend(db, sample_txn, posting_date=datetime.date(2026, 8, 20), pending=True)
        assert saved.classification.needs_user_review is False

    @pytest.mark.parametrize("changes", _CLASSIFIER_INPUT_CHANGES)
    def test_input_change_clears_ai_classification(self, db, sample_txn, classified_by_ai, changes):
        saved = self._resend(db, sample_txn, **changes)
        assert saved.classification is None
        assert find_raw_transactions(unclassified=True, conn=db) == [saved]

    @pytest.mark.parametrize("changes", _CLASSIFIER_INPUT_CHANGES)
    def test_input_change_keeps_and_flags_user_classification(
        self, db, sample_txn, classified_by_user, changes
    ):
        saved = self._resend(db, sample_txn, **changes)
        assert saved.classification == dataclasses.replace(
            _classification(ClassifiedBy.USER), needs_user_review=True
        )

    def test_setting_classification_again_clears_the_flag(self, db, sample_txn, classified_by_user):
        self._resend(db, sample_txn, amount=Decimal("-5.25"))
        update_raw_transaction_classification("txn-1", _classification(ClassifiedBy.USER), conn=db)
        [saved] = find_raw_transactions(conn=db)
        assert saved.classification.needs_user_review is False

    def test_incoming_classification_does_not_replace_stored_one(
        self, db, sample_txn, classified_by_user
    ):
        saved = self._resend(db, sample_txn, classification=_classification(ClassifiedBy.AI))
        assert saved.classification == _classification(ClassifiedBy.USER)

    def test_confidence_only_change_keeps_ai_classification(self, db, sample_txn, classified_by_ai):
        saved = self._resend(db, sample_txn, category_confidence="HIGH")
        assert saved.category_confidence == "HIGH"
        assert saved.classification == _classification()

    def test_confidence_only_change_does_not_flag_user_classification(
        self, db, sample_txn, classified_by_user
    ):
        saved = self._resend(db, sample_txn, category_confidence="HIGH")
        assert saved.classification.needs_user_review is False

    def test_same_amount_written_differently_is_not_a_change(
        self, db, sample_txn, classified_by_ai
    ):
        saved = self._resend(db, sample_txn, amount=Decimal("-4.5"))
        assert saved.classification == _classification()


class TestCategoryDetails:
    def test_round_trips_through_database(self, db, linked_item, sample_txn):
        txn = dataclasses.replace(
            sample_txn, category_detailed="FOOD_AND_DRINK_COFFEE", category_confidence="LOW"
        )
        upsert_raw_transaction(txn, conn=db)
        assert find_raw_transactions(conn=db) == [txn]

    def test_round_trips_through_dict(self, sample_txn):
        txn = dataclasses.replace(
            sample_txn, category_detailed="FOOD_AND_DRINK_COFFEE", category_confidence="LOW"
        )
        d = txn.to_dict()
        assert (d["category_detailed"], d["category_confidence"]) == (
            "FOOD_AND_DRINK_COFFEE",
            "LOW",
        )
        assert RawTransaction.from_dict(d) == txn

    def test_default_to_none(self, db, linked_item, sample_txn):
        upsert_raw_transaction(sample_txn, conn=db)
        [saved] = find_raw_transactions(conn=db)
        assert (saved.category_detailed, saved.category_confidence) == (None, None)


class TestClassificationDictRoundTrip:
    def test_round_trips_through_dict(self, sample_txn):
        txn = dataclasses.replace(sample_txn, classification=_classification())
        d = txn.to_dict()
        assert d["classification"] == {
            "counter_account": "non_essential_expense",
            "category": "dining",
            "counterparty": "Starbucks",
            "classified_by": "ai",
            "needs_user_review": False,
        }
        assert RawTransaction.from_dict(d) == txn

    def test_unclassified_round_trips_as_none(self, sample_txn):
        d = sample_txn.to_dict()
        assert d["classification"] is None
        assert RawTransaction.from_dict(d).classification is None


class TestClassificationColumnMigration:
    def test_adds_column_to_a_database_from_before_it_existed(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        create_schema(conn)
        conn.execute("ALTER TABLE raw_transactions DROP COLUMN classification")
        conn.execute(
            "INSERT INTO bank_accounts (id, institution_name, account_type, last4)"
            " VALUES ('acc-1', 'Test Bank', 'checking', '0000')"
        )
        conn.execute(
            "INSERT INTO raw_transactions (id, source, account_id, posting_date, description, amount)"
            " VALUES ('txn-old', 'plaid', 'acc-1', '2026-08-19', 'Starbucks', '-4.50')"
        )
        conn.commit()

        _apply_migrations(conn)

        [txn] = find_raw_transactions(conn=conn)
        assert txn.description == "Starbucks"
        assert txn.classification is None
        conn.close()


class TestCategoryDetailsColumnMigration:
    def test_adds_columns_to_a_database_from_before_they_existed(self):
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        create_schema(conn)
        conn.execute("ALTER TABLE raw_transactions DROP COLUMN category_detailed")
        conn.execute("ALTER TABLE raw_transactions DROP COLUMN category_confidence")
        conn.execute(
            "INSERT INTO bank_accounts (id, institution_name, account_type, last4)"
            " VALUES ('acc-1', 'Test Bank', 'checking', '0000')"
        )
        conn.execute(
            "INSERT INTO raw_transactions (id, source, account_id, posting_date, description, amount)"
            " VALUES ('txn-old', 'plaid', 'acc-1', '2026-08-19', 'Starbucks', '-4.50')"
        )
        conn.commit()

        _apply_migrations(conn)

        [txn] = find_raw_transactions(conn=conn)
        assert txn.description == "Starbucks"
        assert (txn.category_detailed, txn.category_confidence) == (None, None)
        conn.close()
