import dataclasses
import datetime
import sqlite3
from decimal import Decimal
from unittest.mock import patch

import pytest
from balanceai_backend.bank_link.plaid_item_db import delete_plaid_item, save_plaid_item
from balanceai_backend.db.bank_account_db import upsert_bank_account
from balanceai_backend.db.connection import create_schema
from balanceai_backend.db.journal_db import (
    add_journal_entry,
    find_booked_transactions,
    save_journal,
)
from balanceai_backend.db.transaction_db import find_transactions, update_transaction
from balanceai_backend.models.bank_account import BankAccount, BankAccountType
from balanceai_backend.models.journal import Journal, JournalAccount
from balanceai_backend.models.plaid_item import PlaidItem
from balanceai_backend.models.source_transaction import (
    Classification,
    ClassifiedBy,
    SourceTransaction,
)
from balanceai_backend.models.transaction import Transaction
from balanceai_backend.source_transactions.generate_journal_entry import generate_journal_entry
from balanceai_backend.source_transactions.source_transaction_db import (
    delete_source_transaction,
    delete_source_transaction_by_plaid_id,
    find_receipt_account_ids_for_card_last4,
    find_source_transactions,
    upsert_source_transaction,
)
from balanceai_backend.utils.general_util import IdPrefix, generate_id


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    create_schema(conn)
    # source_transactions.account_id references bank_accounts(id)
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
    return SourceTransaction(
        source_transaction_id="txn-1",
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


class TestFindSourceTransactions:
    def test_returns_empty_list_when_none_saved(self, db, linked_item):
        assert find_source_transactions(conn=db) == []

    def test_returns_saved_transaction(self, db, linked_item, sample_txn):
        upsert_source_transaction(sample_txn, conn=db)
        [txn] = find_source_transactions(conn=db)
        assert txn.source_transaction_id == "txn-1"
        assert txn.description == "Starbucks"
        assert txn.amount == Decimal("-4.50")
        assert txn.plaid_account_id == "plaid-raw-acc-1"

    def test_filters_by_plaid_item_id(self, db):
        save_plaid_item(PlaidItem(item_id="item-1", access_token="a"), conn=db)
        save_plaid_item(PlaidItem(item_id="item-2", access_token="b"), conn=db)
        upsert_source_transaction(
            SourceTransaction(
                source_transaction_id="txn-1",
                source="plaid",
                plaid_item_id="item-1",
                account_id="acc-1",
                posting_date=datetime.date(2026, 8, 19),
                description="A",
                amount=Decimal(1),
            ),
            conn=db,
        )
        upsert_source_transaction(
            SourceTransaction(
                source_transaction_id="txn-2",
                source="plaid",
                plaid_item_id="item-2",
                account_id="acc-2",
                posting_date=datetime.date(2026, 8, 19),
                description="B",
                amount=Decimal(2),
            ),
            conn=db,
        )
        [txn] = find_source_transactions(plaid_item_id="item-2", conn=db)
        assert txn.source_transaction_id == "txn-2"

    def test_filters_by_account_id(self, db, linked_item, sample_txn):
        upsert_source_transaction(sample_txn, conn=db)
        assert len(find_source_transactions(account_id="plaid-acc-1", conn=db)) == 1
        assert find_source_transactions(account_id="plaid-acc-nonexistent", conn=db) == []

    def test_filters_by_source(self, db, linked_item, sample_txn):
        upsert_source_transaction(sample_txn, conn=db)
        upsert_source_transaction(
            SourceTransaction(
                source_transaction_id="txn-receipt-1",
                source="receipt",
                plaid_item_id=None,
                account_id="acct-1",
                posting_date=datetime.date(2026, 8, 19),
                description="Grocery receipt",
                amount=Decimal("-30.00"),
            ),
            conn=db,
        )
        [txn] = find_source_transactions(source="receipt", conn=db)
        assert txn.source_transaction_id == "txn-receipt-1"
        assert txn.plaid_item_id is None


class TestUpsertSourceTransaction:
    def test_replaces_existing_transaction_on_same_id(self, db, linked_item, sample_txn):
        """Simulates Plaid's `modified` bucket: same transaction_id, changed fields —
        e.g. a pending charge posting with a finalized amount."""
        upsert_source_transaction(sample_txn, conn=db)

        modified = SourceTransaction(
            source_transaction_id="txn-1",
            source="plaid",
            plaid_item_id="item-1",
            account_id="plaid-acc-1",
            posting_date=datetime.date(2026, 8, 19),
            description="Starbucks",
            amount=Decimal("-4.75"),
            pending=False,
        )
        upsert_source_transaction(modified, conn=db)

        transactions = find_source_transactions(conn=db)
        assert len(transactions) == 1
        assert transactions[0].amount == Decimal("-4.75")

    def test_non_plaid_source_allows_null_plaid_item_id(self, db):
        """Confirms plaid_item_id is genuinely nullable — a receipt/bank-statement
        row shouldn't need a fake Plaid item just to satisfy the schema."""
        txn = SourceTransaction(
            source_transaction_id="txn-statement-1",
            source="bank_statement",
            plaid_item_id=None,
            account_id="acct-1",
            posting_date=datetime.date(2026, 8, 19),
            description="Check deposit",
            amount=Decimal("500.00"),
        )
        upsert_source_transaction(txn, conn=db)
        [saved] = find_source_transactions(conn=db)
        assert saved.plaid_item_id is None
        assert saved.source == "bank_statement"


class TestDeleteSourceTransaction:
    def test_removes_transaction(self, db, linked_item, sample_txn):
        upsert_source_transaction(sample_txn, conn=db)
        delete_source_transaction("txn-1", conn=db)
        assert find_source_transactions(conn=db) == []

    def test_silently_no_ops_when_not_found(self, db, linked_item):
        delete_source_transaction("txn-missing", conn=db)  # should not raise


class TestPlaidItemDeletion:
    def test_deleting_item_keeps_its_transactions_and_clears_item_id(
        self, db, linked_item, sample_txn
    ):
        upsert_source_transaction(sample_txn, conn=db)
        delete_plaid_item("item-1", conn=db)

        [txn] = find_source_transactions(conn=db)
        assert txn.source_transaction_id == "txn-1"
        assert txn.plaid_item_id is None
        assert txn.plaid_account_id == "plaid-raw-acc-1"


class TestBankAccountReference:
    def test_rejects_unknown_account_id(self, db, linked_item, sample_txn):
        sample_txn.account_id = "no-such-account"
        with pytest.raises(sqlite3.IntegrityError):
            upsert_source_transaction(sample_txn, conn=db)

    def test_renaming_bank_account_updates_its_transactions(self, db, linked_item, sample_txn):
        upsert_source_transaction(sample_txn, conn=db)

        with db:
            db.execute(
                "UPDATE bank_accounts SET id = ? WHERE id = ?", ("renamed-acc", "plaid-acc-1")
            )

        [txn] = find_source_transactions(conn=db)
        assert txn.account_id == "renamed-acc"


def _set_classification(db, source_transaction_id: str, classification) -> None:
    """Classify the transaction this source transaction belongs to."""
    [source] = find_source_transactions(source_transaction_id=source_transaction_id, conn=db)
    with db:
        update_transaction(source.transaction_id, classification=classification, conn=db)


def _transaction_of(db, source_transaction_id: str) -> Transaction:
    """The transaction this source transaction belongs to."""
    [source] = find_source_transactions(source_transaction_id=source_transaction_id, conn=db)
    [txn] = find_transactions(transaction_id=source.transaction_id, conn=db)
    return txn


def _classification(classified_by: ClassifiedBy = ClassifiedBy.AI) -> Classification:
    return Classification(
        counter_account=JournalAccount.NON_ESSENTIALS_EXPENSE,
        category="dining",
        counterparty="Starbucks",
        classified_by=classified_by,
    )


class TestClassification:
    """The classification is the transaction's; a source transaction has none."""

    def test_new_transaction_is_unclassified(self, db, linked_item, sample_txn):
        upsert_source_transaction(sample_txn, conn=db)
        assert _transaction_of(db, "txn-1").classification is None

    def test_update_sets_classification(self, db, linked_item, sample_txn):
        upsert_source_transaction(sample_txn, conn=db)
        _set_classification(db, "txn-1", _classification())
        assert _transaction_of(db, "txn-1").classification == _classification()

    def test_update_with_none_clears_classification(self, db, linked_item, sample_txn):
        upsert_source_transaction(sample_txn, conn=db)
        _set_classification(db, "txn-1", _classification())
        _set_classification(db, "txn-1", None)
        assert _transaction_of(db, "txn-1").classification is None

    def test_update_raises_when_transaction_not_found(self, db):
        with pytest.raises(ValueError, match="txn-missing"):
            update_transaction("txn-missing", classification=_classification(), conn=db)

    def test_update_rejects_a_field_that_cant_be_set(self, db, linked_item, sample_txn):
        upsert_source_transaction(sample_txn, conn=db)
        [source] = find_source_transactions(conn=db)
        with pytest.raises(ValueError, match="amount"):
            update_transaction(source.transaction_id, amount=Decimal(1), conn=db)

    def test_source_transaction_has_no_classification(self, sample_txn):
        assert not hasattr(sample_txn, "classification")

    def test_find_by_id(self, db, linked_item, sample_txn):
        upsert_source_transaction(sample_txn, conn=db)
        assert [
            t.source_transaction_id
            for t in find_source_transactions(source_transaction_id="txn-1", conn=db)
        ] == ["txn-1"]
        assert find_source_transactions(source_transaction_id="txn-missing", conn=db) == []

    def test_find_unclassified_only(self, db, linked_item, sample_txn):
        upsert_source_transaction(sample_txn, conn=db)
        upsert_source_transaction(
            dataclasses.replace(sample_txn, source_transaction_id="txn-2"), conn=db
        )
        _set_classification(db, "txn-1", _classification())
        assert [t.transaction_id for t in find_transactions(unclassified=True, conn=db)] == [
            _transaction_of(db, "txn-2").transaction_id
        ]


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
    def _resend(db, sample_txn, **changes) -> SourceTransaction:
        upsert_source_transaction(dataclasses.replace(sample_txn, **changes), conn=db)
        [saved] = find_source_transactions(conn=db)
        return saved

    @pytest.fixture
    def classified_by_ai(self, db, linked_item, sample_txn):
        upsert_source_transaction(sample_txn, conn=db)
        _set_classification(db, "txn-1", _classification())

    @pytest.fixture
    def classified_by_user(self, db, linked_item, sample_txn):
        upsert_source_transaction(sample_txn, conn=db)
        _set_classification(db, "txn-1", _classification(ClassifiedBy.USER))

    def test_unchanged_resend_keeps_ai_classification(self, db, sample_txn, classified_by_ai):
        assert (
            self._resend(db, sample_txn) and _transaction_of(db, "txn-1").classification
        ) == _classification()

    def test_unchanged_resend_does_not_flag_user_classification(
        self, db, sample_txn, classified_by_user
    ):
        self._resend(db, sample_txn)
        assert _transaction_of(db, "txn-1").classification == _classification(ClassifiedBy.USER)
        assert _transaction_of(db, "txn-1").classification.needs_user_review is False

    def test_date_or_pending_change_keeps_ai_classification(self, db, sample_txn, classified_by_ai):
        saved = self._resend(db, sample_txn, posting_date=datetime.date(2026, 8, 20), pending=True)
        assert saved.posting_date == datetime.date(2026, 8, 20)
        assert saved.pending is True
        assert _transaction_of(db, "txn-1").classification == _classification()

    def test_date_or_pending_change_does_not_flag_user_classification(
        self, db, sample_txn, classified_by_user
    ):
        self._resend(db, sample_txn, posting_date=datetime.date(2026, 8, 20), pending=True)
        assert _transaction_of(db, "txn-1").classification.needs_user_review is False

    @pytest.mark.parametrize("changes", _CLASSIFIER_INPUT_CHANGES)
    def test_input_change_clears_ai_classification(self, db, sample_txn, classified_by_ai, changes):
        self._resend(db, sample_txn, **changes)
        assert _transaction_of(db, "txn-1").classification is None
        assert find_transactions(unclassified=True, conn=db) == [_transaction_of(db, "txn-1")]

    @pytest.mark.parametrize("changes", _CLASSIFIER_INPUT_CHANGES)
    def test_input_change_keeps_and_flags_user_classification(
        self, db, sample_txn, classified_by_user, changes
    ):
        self._resend(db, sample_txn, **changes)
        assert _transaction_of(db, "txn-1").classification == dataclasses.replace(
            _classification(ClassifiedBy.USER), needs_user_review=True
        )

    def test_setting_classification_again_clears_the_flag(self, db, sample_txn, classified_by_user):
        self._resend(db, sample_txn, amount=Decimal("-5.25"))
        _set_classification(db, "txn-1", _classification(ClassifiedBy.USER))
        assert _transaction_of(db, "txn-1").classification.needs_user_review is False

    def test_confidence_only_change_keeps_ai_classification(self, db, sample_txn, classified_by_ai):
        saved = self._resend(db, sample_txn, category_confidence="HIGH")
        assert saved.category_confidence == "HIGH"
        assert _transaction_of(db, "txn-1").classification == _classification()

    def test_confidence_only_change_does_not_flag_user_classification(
        self, db, sample_txn, classified_by_user
    ):
        self._resend(db, sample_txn, category_confidence="HIGH")
        assert _transaction_of(db, "txn-1").classification.needs_user_review is False

    def test_same_amount_written_differently_is_not_a_change(
        self, db, sample_txn, classified_by_ai
    ):
        self._resend(db, sample_txn, amount=Decimal("-4.5"))
        assert _transaction_of(db, "txn-1").classification == _classification()


class TestChangesDeleteTheEntry:
    """A change to a booked transaction deletes its entry so it's booked again."""

    @pytest.fixture
    def journal_id(self, db, linked_item, sample_txn):
        journal = Journal(name="Personal", bank_account_ids=["plaid-acc-1"])
        save_journal(journal, db)
        upsert_source_transaction(sample_txn, conn=db)
        _set_classification(db, "txn-1", _classification())
        txn = _transaction_of(db, "txn-1")
        with db:
            add_journal_entry(
                journal.journal_id, generate_journal_entry(txn, BankAccountType.CHECKING), db
            )
        return journal.journal_id

    @staticmethod
    def _booked(db, journal_id: str) -> dict[str, str]:
        """Booked source transaction ids (via their purchases) → entry ids."""
        raw_id = {
            t.transaction_id: t.source_transaction_id for t in find_source_transactions(conn=db)
        }
        return {raw_id[p]: e for p, e in find_booked_transactions(journal_id, db).items()}

    def test_unchanged_resend_keeps_it(self, db, sample_txn, journal_id):
        upsert_source_transaction(sample_txn, conn=db)

        assert "txn-1" in self._booked(db, journal_id)

    def test_resend_with_another_confidence_keeps_it(self, db, sample_txn, journal_id):
        upsert_source_transaction(
            dataclasses.replace(sample_txn, category_confidence="LOW"), conn=db
        )

        assert "txn-1" in self._booked(db, journal_id)

    @pytest.mark.parametrize(
        "changes",
        [
            {"amount": Decimal("-5.00")},
            {"posting_date": datetime.date(2026, 8, 20)},
            {"description": "Starbucks #2"},
            {"account_id": "acc-1"},
            {"category": "GENERAL_MERCHANDISE"},  # drops the AI's classification
        ],
        ids=["amount", "date", "description", "bank_account", "classification_dropped"],
    )
    def test_resend_with_a_change_deletes_it(self, db, sample_txn, journal_id, changes):
        upsert_source_transaction(dataclasses.replace(sample_txn, **changes), conn=db)

        assert self._booked(db, journal_id) == {}

    def test_reclassifying_deletes_it(self, db, journal_id):
        _set_classification(db, "txn-1", _classification(ClassifiedBy.USER))

        assert self._booked(db, journal_id) == {}

    def test_deleting_the_transaction_deletes_it(self, db, journal_id):
        delete_source_transaction("txn-1", conn=db)

        assert self._booked(db, journal_id) == {}


class TestCategoryDetails:
    def test_round_trips_through_database(self, db, linked_item, sample_txn):
        txn = dataclasses.replace(
            sample_txn, category_detailed="FOOD_AND_DRINK_COFFEE", category_confidence="LOW"
        )
        upsert_source_transaction(txn, conn=db)
        [saved] = find_source_transactions(conn=db)
        assert saved.transaction_id.startswith("txn-")
        assert (
            dataclasses.replace(saved, transaction_id=None, created_at=None, updated_at=None) == txn
        )

    def test_round_trips_through_dict(self, sample_txn):
        txn = dataclasses.replace(
            sample_txn, category_detailed="FOOD_AND_DRINK_COFFEE", category_confidence="LOW"
        )
        d = txn.to_dict()
        assert (d["category_detailed"], d["category_confidence"]) == (
            "FOOD_AND_DRINK_COFFEE",
            "LOW",
        )
        assert SourceTransaction.from_dict(d) == txn

    def test_default_to_none(self, db, linked_item, sample_txn):
        upsert_source_transaction(sample_txn, conn=db)
        [saved] = find_source_transactions(conn=db)
        assert (saved.category_detailed, saved.category_confidence) == (None, None)


class TestReceiptFields:
    def test_saves_and_loads_receipt_fields(self, db):
        txn = SourceTransaction(
            source_transaction_id="receipt-1",
            source="receipt",
            account_id="acc-1",
            posting_date=datetime.date(2026, 11, 8),
            description="Blue Bottle Coffee",
            amount=Decimal("-12.50"),
            card_last4="1234",
            tax=Decimal("1.02"),
            tip=Decimal("2.00"),
        )
        upsert_source_transaction(txn, conn=db)
        [saved] = find_source_transactions(source_transaction_id="receipt-1", conn=db)
        assert (saved.card_last4, saved.tax, saved.tip) == (
            "1234",
            Decimal("1.02"),
            Decimal("2.00"),
        )

    def test_receipt_fields_round_trip_through_dict(self):
        txn = SourceTransaction(
            source_transaction_id="receipt-1",
            source="receipt",
            account_id="acc-1",
            posting_date=datetime.date(2026, 11, 8),
            description="Blue Bottle Coffee",
            amount=Decimal("-12.50"),
            card_last4="1234",
            tax=Decimal("1.02"),
        )
        assert SourceTransaction.from_dict(txn.to_dict()) == txn


class TestFindReceiptAccountIdsForCardLast4:
    def _receipt(self, id, account_id, card="1234", source="receipt"):
        return SourceTransaction(
            source_transaction_id=id,
            source=source,
            account_id=account_id,
            posting_date=datetime.date(2026, 11, 8),
            description="Blue Bottle Coffee",
            amount=Decimal("-12.50"),
            card_last4=card,
        )

    def test_returns_each_account_once(self, db):
        upsert_source_transaction(self._receipt("r1", "acc-1"), conn=db)
        upsert_source_transaction(self._receipt("r2", "acc-1"), conn=db)
        upsert_source_transaction(self._receipt("r3", "acc-2", card="5678"), conn=db)
        assert find_receipt_account_ids_for_card_last4("1234", conn=db) == ["acc-1"]

    def test_only_reads_receipts(self, db):
        upsert_source_transaction(self._receipt("p1", "acc-1", source="plaid"), conn=db)
        assert find_receipt_account_ids_for_card_last4("1234", conn=db) == []


class TestOurIdsAndTimestamps:
    """BL-16 / BL-18."""

    def _plaid(self, amount="-4.50"):
        """A fresh object each time, so a fresh source_transaction_id."""
        return SourceTransaction(
            source_transaction_id=generate_id(IdPrefix.PLAID),
            source="plaid",
            account_id="acc-1",
            posting_date=datetime.date(2026, 8, 19),
            description="Starbucks",
            amount=Decimal(amount),
            plaid_transaction_id="plaid-1",
        )

    def test_same_plaid_id_updates_the_row_and_keeps_our_id(self, db):
        times = iter(["2026-01-01T00:00:00+00:00", "2026-01-02T00:00:00+00:00"])
        with patch(
            "balanceai_backend.source_transactions.source_transaction_db.utc_now_iso",
            side_effect=lambda: next(times),
        ):
            first_id = upsert_source_transaction(self._plaid(), conn=db)
            second_id = upsert_source_transaction(self._plaid("-5.25"), conn=db)
        [txn] = find_source_transactions(conn=db)
        assert first_id == second_id == txn.source_transaction_id
        assert txn.amount == Decimal("-5.25")
        assert (txn.created_at, txn.updated_at) == (
            "2026-01-01T00:00:00+00:00",
            "2026-01-02T00:00:00+00:00",
        )

    def test_finds_by_either_id(self, db):
        our_id = upsert_source_transaction(self._plaid(), conn=db)
        assert find_source_transactions(source_transaction_id=our_id, conn=db)[
            0
        ].plaid_transaction_id == ("plaid-1")
        assert find_source_transactions(plaid_transaction_id="plaid-1", conn=db)[
            0
        ].source_transaction_id == (our_id)

    def test_delete_by_plaid_id(self, db):
        upsert_source_transaction(self._plaid(), conn=db)
        delete_source_transaction_by_plaid_id("plaid-1", conn=db)
        assert find_source_transactions(conn=db) == []
        delete_source_transaction_by_plaid_id("unknown", conn=db)  # no-op

    def test_classification_update_sets_updated_at(self, db):
        with patch(
            "balanceai_backend.db.transaction_db.utc_now_iso",
            return_value="2026-01-01T00:00:00+00:00",
        ):
            our_id = upsert_source_transaction(self._plaid(), conn=db)
        _set_classification(
            db,
            our_id,
            Classification(
                counter_account=JournalAccount.NON_ESSENTIALS_EXPENSE,
                category="dining",
                counterparty="Starbucks",
                classified_by=ClassifiedBy.AI,
            ),
        )
        txn = _transaction_of(db, our_id)
        assert txn.created_at == "2026-01-01T00:00:00+00:00"
        assert txn.updated_at > txn.created_at


class TestTransactions:
    """Each new source transaction gets its own purchase, which never changes."""

    def _txn(self, raw_id="t1", plaid_id="plaid-1", amount="-4.50"):
        return SourceTransaction(
            source_transaction_id=raw_id,
            source="plaid",
            account_id="acc-1",
            posting_date=datetime.date(2026, 8, 19),
            description="Starbucks",
            amount=Decimal(amount),
            plaid_transaction_id=plaid_id,
        )

    def test_a_new_transaction_gets_its_own_purchase(self, db):
        upsert_source_transaction(self._txn(), conn=db)
        [txn] = find_source_transactions(conn=db)
        assert [p.transaction_id for p in find_transactions(conn=db)] == [txn.transaction_id]

    def test_an_update_keeps_the_purchase(self, db):
        upsert_source_transaction(self._txn(), conn=db)
        [first] = find_source_transactions(conn=db)
        upsert_source_transaction(self._txn(raw_id="fresh-id", amount="-5.25"), conn=db)
        [txn] = find_source_transactions(conn=db)
        assert txn.transaction_id == first.transaction_id
        assert len(find_transactions(conn=db)) == 1

    def test_two_transactions_get_two_purchases(self, db):
        upsert_source_transaction(self._txn(), conn=db)
        upsert_source_transaction(self._txn(raw_id="t2", plaid_id="plaid-2"), conn=db)
        assert len({t.transaction_id for t in find_source_transactions(conn=db)}) == 2

    def test_deleting_the_transaction_deletes_its_purchase(self, db):
        upsert_source_transaction(self._txn(), conn=db)
        delete_source_transaction("t1", conn=db)
        assert find_transactions(conn=db) == []

    def test_deleting_by_plaid_id_deletes_its_purchase(self, db):
        upsert_source_transaction(self._txn(), conn=db)
        delete_source_transaction_by_plaid_id("plaid-1", conn=db)
        assert find_transactions(conn=db) == []


def test_transaction_round_trips_through_dict():
    txn = Transaction(
        transaction_id="txn-1",
        account_id="acc-1",
        transaction_date=datetime.date(2026, 8, 19),
        amount=Decimal("-4.50"),
        description="Starbucks",
        classification=_classification(),
        created_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-02T00:00:00+00:00",
    )
    assert Transaction.from_dict(txn.to_dict()) == txn


class TestTransactionFields:
    """refresh_transaction copies each field from the transaction's only source
    transaction (step 4a; matching will add per-field rules)."""

    def _plaid(self, amount="-4.50"):
        return SourceTransaction(
            source_transaction_id=generate_id(IdPrefix.PLAID),
            source="plaid",
            account_id="acc-1",
            posting_date=datetime.date(2026, 8, 19),
            description="Starbucks",
            amount=Decimal(amount),
            category="FOOD_AND_DRINK",
            plaid_transaction_id="plaid-1",
        )

    def test_copies_the_fields_of_a_plaid_transaction(self, db):
        upsert_source_transaction(self._plaid(), conn=db)
        [txn] = find_transactions(conn=db)
        assert (txn.account_id, txn.transaction_date, txn.posted_date) == (
            "acc-1",
            datetime.date(2026, 8, 19),
            datetime.date(2026, 8, 19),
        )
        assert (txn.amount, txn.description, txn.category) == (
            Decimal("-4.50"),
            "Starbucks",
            "FOOD_AND_DRINK",
        )

    def test_a_changed_amount_updates_it_and_keeps_created_at(self, db):
        times = iter(f"2026-01-01T00:00:0{n}+00:00" for n in range(1, 9))
        with (
            patch(
                "balanceai_backend.db.transaction_db.utc_now_iso", side_effect=lambda: next(times)
            ),
            patch(
                "balanceai_backend.source_transactions.source_transaction_db.utc_now_iso",
                side_effect=lambda: next(times),
            ),
        ):
            upsert_source_transaction(self._plaid(), conn=db)
            [first] = find_transactions(conn=db)
            upsert_source_transaction(self._plaid("-5.25"), conn=db)
        [txn] = find_transactions(conn=db)
        assert txn.amount == Decimal("-5.25")
        assert txn.created_at == first.created_at
        assert txn.updated_at > first.updated_at

    def test_an_unchanged_resync_leaves_updated_at_alone(self, db):
        upsert_source_transaction(self._plaid(), conn=db)
        [first] = find_transactions(conn=db)
        upsert_source_transaction(self._plaid(), conn=db)
        [txn] = find_transactions(conn=db)
        assert txn.updated_at == first.updated_at

    def test_a_receipt_has_no_posted_date(self, db):
        receipt = SourceTransaction(
            source_transaction_id=generate_id(IdPrefix.RECEIPT),
            source="receipt",
            account_id="acc-1",
            posting_date=datetime.date(2026, 11, 8),
            description="Blue Bottle Coffee",
            amount=Decimal("-12.50"),
            card_last4="1234",
            tax=Decimal("1.02"),
            tip=Decimal("2.00"),
        )
        upsert_source_transaction(receipt, conn=db)
        [txn] = find_transactions(conn=db)
        assert txn.posted_date is None
        assert (txn.card_last4, txn.tax, txn.tip) == ("1234", Decimal("1.02"), Decimal("2.00"))

    def test_deleting_the_source_deletes_the_transaction(self, db):
        upsert_source_transaction(self._plaid(), conn=db)
        delete_source_transaction_by_plaid_id("plaid-1", conn=db)
        assert find_transactions(conn=db) == []


def test_transaction_fields_round_trip_through_dict():
    txn = Transaction(
        transaction_id="txn-1",
        account_id="acc-1",
        transaction_date=datetime.date(2026, 8, 19),
        amount=Decimal("-4.50"),
        description="Blue Bottle Coffee",
        tax=Decimal("0.30"),
    )
    assert Transaction.from_dict(txn.to_dict()) == txn
