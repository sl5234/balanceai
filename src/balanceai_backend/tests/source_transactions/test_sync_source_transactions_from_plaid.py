"""Tests for the /transactions/sync loop.

Fake Plaid response objects use SimpleNamespace rather than MagicMock — same
reasoning as test_link.py: Plaid's real generated SDK models raise
ApiAttributeError on unset optional fields instead of returning None, and
SimpleNamespace matches that "attribute genuinely absent" behavior.

Every sync_source_transactions_from_plaid() call below passes conn=db explicitly — its default
argument is bound once at function-definition time, so patching the storage
modules' module-level _default_conn after the fact would silently do nothing
and these tests would otherwise hit the real data/balanceai.db.
"""

import dataclasses
import sqlite3
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from balanceai_backend.bank_link.plaid_item_db import save_plaid_item
from balanceai_backend.bank_link.plaid_sync_cursor_db import get_plaid_sync_cursor
from balanceai_backend.db.bank_account_db import upsert_bank_account
from balanceai_backend.db.connection import create_schema
from balanceai_backend.db.transaction_db import find_transactions, update_transaction
from balanceai_backend.models.bank_account import BankAccount, BankAccountType
from balanceai_backend.models.journal import JournalAccount
from balanceai_backend.models.plaid_item import PlaidItem
from balanceai_backend.models.source_transaction import (
    Classification,
    ClassifiedBy,
    MatchedBy,
    SourceTransaction,
)
from balanceai_backend.source_transactions.source_transaction_db import (
    find_source_transactions,
    upsert_source_transaction,
)
from balanceai_backend.source_transactions.sync_source_transactions_from_plaid import (
    sync_source_transactions_from_plaid,
)
from balanceai_backend.source_transactions.transaction_grouping import merge_transactions

BANK_ACCOUNT_ID = "tartan_bank:checking:0000"


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    create_schema(conn)
    yield conn
    conn.close()


@pytest.fixture(autouse=True)
def mock_sync_bank_accounts():
    """Bank-account creation has its own tests (tests/helpers/test_plaid_helper.py);
    stub it here so these tests only exercise the transaction loop."""
    with patch(
        "balanceai_backend.source_transactions.sync_source_transactions_from_plaid.sync_bank_accounts_from_plaid",
        return_value={"saved": [], "skipped": []},
    ) as mock:
        yield mock


@pytest.fixture
def linked_item(db):
    item = PlaidItem(item_id="item-1", access_token="access-sandbox-abc")
    save_plaid_item(item, conn=db)
    upsert_bank_account(
        BankAccount(
            id=BANK_ACCOUNT_ID,
            institution_name="Tartan Bank",
            account_type=BankAccountType.CHECKING,
            last4="0000",
            plaid_item_id="item-1",
            plaid_account_id="plaid-acc-1",
        ),
        conn=db,
    )
    return item


def _plaid_txn(
    transaction_id="txn-1",
    account_id="plaid-acc-1",
    amount=4.50,
    name="STARBUCKS #123",
    merchant_name="Starbucks",
    pending=False,
    personal_finance_category=None,
    authorized_date=None,
    pending_transaction_id=None,
):
    if personal_finance_category is None:
        personal_finance_category = SimpleNamespace(primary="FOOD_AND_DRINK")
    return SimpleNamespace(
        transaction_id=transaction_id,
        account_id=account_id,
        date=date(2026, 8, 19),
        authorized_date=authorized_date,
        amount=amount,
        name=name,
        merchant_name=merchant_name,
        pending=pending,
        personal_finance_category=personal_finance_category,
        pending_transaction_id=pending_transaction_id,
    )


class TestSyncTransactions:
    def test_raises_when_item_not_found(self, db):
        with pytest.raises(ValueError, match="item-missing"):
            sync_source_transactions_from_plaid("item-missing", conn=db)

    def test_first_sync_omits_cursor(self, db, linked_item):
        mock_client = MagicMock()
        mock_client.transactions_sync.return_value = SimpleNamespace(
            added=[], modified=[], removed=[], next_cursor="cursor-A", has_more=False
        )

        with patch(
            "balanceai_backend.source_transactions.sync_source_transactions_from_plaid.get_client",
            return_value=mock_client,
        ):
            sync_source_transactions_from_plaid("item-1", conn=db)

        request = mock_client.transactions_sync.call_args[0][0]
        assert not hasattr(request, "cursor")
        assert request.access_token == "access-sandbox-abc"

    def test_added_transaction_saved_with_flipped_sign(self, db, linked_item):
        mock_client = MagicMock()
        mock_client.transactions_sync.return_value = SimpleNamespace(
            added=[_plaid_txn(amount=4.50)],
            modified=[],
            removed=[],
            next_cursor="cursor-A",
            has_more=False,
        )

        with patch(
            "balanceai_backend.source_transactions.sync_source_transactions_from_plaid.get_client",
            return_value=mock_client,
        ):
            counts = sync_source_transactions_from_plaid("item-1", conn=db)

        assert counts == {
            "added": 1,
            "modified": 0,
            "removed": 0,
            "bank_accounts": {"saved": 0, "skipped": 0},
        }
        [txn] = find_source_transactions(conn=db)
        assert txn.plaid_transaction_id == "txn-1"
        assert txn.account_id == BANK_ACCOUNT_ID  # our id, not Plaid's "plaid-acc-1"
        assert txn.plaid_account_id == "plaid-acc-1"
        assert txn.amount == Decimal("-4.5")  # Plaid positive (spend) -> our negative (debit)
        assert txn.description == "Starbucks"
        assert txn.category == "FOOD_AND_DRINK"

    def test_income_transaction_flips_to_positive(self, db, linked_item):
        mock_client = MagicMock()
        mock_client.transactions_sync.return_value = SimpleNamespace(
            added=[_plaid_txn(amount=-1000.0, name="PAYROLL", merchant_name=None)],
            modified=[],
            removed=[],
            next_cursor="cursor-A",
            has_more=False,
        )

        with patch(
            "balanceai_backend.source_transactions.sync_source_transactions_from_plaid.get_client",
            return_value=mock_client,
        ):
            sync_source_transactions_from_plaid("item-1", conn=db)

        [txn] = find_source_transactions(conn=db)
        assert txn.amount == Decimal("1000.0")  # Plaid negative (deposit) -> our positive (credit)
        assert txn.description == "PAYROLL"  # falls back to name when merchant_name is None

    def test_modified_transaction_replaces_existing_row(self, db, linked_item):
        mock_client = MagicMock()
        mock_client.transactions_sync.side_effect = [
            SimpleNamespace(
                added=[_plaid_txn(amount=4.50)],
                modified=[],
                removed=[],
                next_cursor="cursor-A",
                has_more=False,
            ),
        ]
        with patch(
            "balanceai_backend.source_transactions.sync_source_transactions_from_plaid.get_client",
            return_value=mock_client,
        ):
            sync_source_transactions_from_plaid("item-1", conn=db)

        mock_client.transactions_sync.side_effect = [
            SimpleNamespace(
                added=[],
                modified=[_plaid_txn(amount=4.75)],
                removed=[],
                next_cursor="cursor-B",
                has_more=False,
            ),
        ]
        with patch(
            "balanceai_backend.source_transactions.sync_source_transactions_from_plaid.get_client",
            return_value=mock_client,
        ):
            counts = sync_source_transactions_from_plaid("item-1", conn=db)

        assert counts == {
            "added": 0,
            "modified": 1,
            "removed": 0,
            "bank_accounts": {"saved": 0, "skipped": 0},
        }
        transactions = find_source_transactions(conn=db)
        assert len(transactions) == 1
        assert transactions[0].amount == Decimal("-4.75")

    def test_removed_transaction_deletes_existing_row(self, db, linked_item):
        mock_client = MagicMock()
        mock_client.transactions_sync.return_value = SimpleNamespace(
            added=[_plaid_txn()], modified=[], removed=[], next_cursor="cursor-A", has_more=False
        )
        with patch(
            "balanceai_backend.source_transactions.sync_source_transactions_from_plaid.get_client",
            return_value=mock_client,
        ):
            sync_source_transactions_from_plaid("item-1", conn=db)

        mock_client.transactions_sync.return_value = SimpleNamespace(
            added=[],
            modified=[],
            removed=[SimpleNamespace(transaction_id="txn-1", account_id="plaid-acc-1")],
            next_cursor="cursor-B",
            has_more=False,
        )
        with patch(
            "balanceai_backend.source_transactions.sync_source_transactions_from_plaid.get_client",
            return_value=mock_client,
        ):
            counts = sync_source_transactions_from_plaid("item-1", conn=db)

        assert counts == {
            "added": 0,
            "modified": 0,
            "removed": 1,
            "bank_accounts": {"saved": 0, "skipped": 0},
        }
        assert find_source_transactions(conn=db) == []

    def test_loops_while_has_more_and_persists_cursor_each_page(self, db, linked_item):
        mock_client = MagicMock()
        mock_client.transactions_sync.side_effect = [
            SimpleNamespace(
                added=[_plaid_txn(transaction_id="txn-1")],
                modified=[],
                removed=[],
                next_cursor="cursor-page-1",
                has_more=True,
            ),
            SimpleNamespace(
                added=[_plaid_txn(transaction_id="txn-2")],
                modified=[],
                removed=[],
                next_cursor="cursor-page-2",
                has_more=False,
            ),
        ]

        with patch(
            "balanceai_backend.source_transactions.sync_source_transactions_from_plaid.get_client",
            return_value=mock_client,
        ):
            counts = sync_source_transactions_from_plaid("item-1", conn=db)

        assert counts == {
            "added": 2,
            "modified": 0,
            "removed": 0,
            "bank_accounts": {"saved": 0, "skipped": 0},
        }
        assert mock_client.transactions_sync.call_count == 2
        second_call_request = mock_client.transactions_sync.call_args_list[1][0][0]
        assert second_call_request.cursor == "cursor-page-1"
        assert get_plaid_sync_cursor("item-1", conn=db) == "cursor-page-2"

    def test_uses_saved_cursor_on_subsequent_sync(self, db, linked_item):
        mock_client = MagicMock()
        mock_client.transactions_sync.return_value = SimpleNamespace(
            added=[], modified=[], removed=[], next_cursor="cursor-A", has_more=False
        )
        with patch(
            "balanceai_backend.source_transactions.sync_source_transactions_from_plaid.get_client",
            return_value=mock_client,
        ):
            sync_source_transactions_from_plaid("item-1", conn=db)

        mock_client.transactions_sync.return_value = SimpleNamespace(
            added=[], modified=[], removed=[], next_cursor="cursor-B", has_more=False
        )
        with patch(
            "balanceai_backend.source_transactions.sync_source_transactions_from_plaid.get_client",
            return_value=mock_client,
        ):
            sync_source_transactions_from_plaid("item-1", conn=db)

        second_call_request = mock_client.transactions_sync.call_args_list[1][0][0]
        assert second_call_request.cursor == "cursor-A"


def _sync_one_page(db, **page):
    """Run a sync against a single Plaid page with the given added/modified/removed."""
    mock_client = MagicMock()
    mock_client.transactions_sync.return_value = SimpleNamespace(
        **{"added": [], "modified": [], "removed": [], **page},
        next_cursor="cursor",
        has_more=False,
    )
    with patch(
        "balanceai_backend.source_transactions.sync_source_transactions_from_plaid.get_client",
        return_value=mock_client,
    ):
        sync_source_transactions_from_plaid("item-1", conn=db)


class TestModifiedTransactionClassification:
    @staticmethod
    def _classification(classified_by: ClassifiedBy) -> Classification:
        return Classification(
            counter_account=JournalAccount.NON_ESSENTIALS_EXPENSE,
            category="dining",
            counterparty="Starbucks",
            classified_by=classified_by,
        )

    def test_modified_amount_keeps_and_flags_a_users_classification(self, db, linked_item):
        _sync_one_page(db, added=[_plaid_txn(amount=4.50)])
        [synced] = find_source_transactions(conn=db)
        with db:
            update_transaction(
                synced.transaction_id,
                classification=self._classification(ClassifiedBy.USER),
                conn=db,
            )

        _sync_one_page(db, modified=[_plaid_txn(amount=5.25)])

        [txn] = find_transactions(conn=db)
        assert txn.amount == Decimal("-5.25")
        assert txn.classification == dataclasses.replace(
            self._classification(ClassifiedBy.USER), needs_user_review=True
        )

    def test_modified_amount_clears_the_ais_classification(self, db, linked_item):
        _sync_one_page(db, added=[_plaid_txn(amount=4.50)])
        [synced] = find_source_transactions(conn=db)
        with db:
            update_transaction(
                synced.transaction_id,
                classification=self._classification(ClassifiedBy.AI),
                conn=db,
            )

        _sync_one_page(db, modified=[_plaid_txn(amount=5.25)])

        [txn] = find_transactions(conn=db)
        assert txn.classification is None


class TestPlaidCategoryDetails:
    def test_saves_detailed_category_and_confidence(self, db, linked_item):
        pfc = SimpleNamespace(
            primary="FOOD_AND_DRINK", detailed="FOOD_AND_DRINK_COFFEE", confidence_level="LOW"
        )
        _sync_one_page(db, added=[_plaid_txn(personal_finance_category=pfc)])

        [txn] = find_source_transactions(conn=db)
        assert txn.category == "FOOD_AND_DRINK"
        assert txn.category_detailed == "FOOD_AND_DRINK_COFFEE"
        assert txn.category_confidence == "LOW"

    def test_no_plaid_category_leaves_all_three_empty(self, db, linked_item):
        plaid_txn = _plaid_txn()
        del plaid_txn.personal_finance_category  # unset, as Plaid's SDK model would have it
        _sync_one_page(db, added=[plaid_txn])

        [txn] = find_source_transactions(conn=db)
        assert (txn.category, txn.category_detailed, txn.category_confidence) == (None, None, None)


class TestSyncBankAccounts:
    def test_syncs_bank_accounts_before_transactions_and_reports_counts(
        self, db, linked_item, mock_sync_bank_accounts
    ):
        mock_sync_bank_accounts.return_value = {
            "saved": ["tartan_bank:checking:0000", "tartan_bank:savings:1111"],
            "skipped": [{"plaid_account_id": "plaid-acc-9", "reason": "no mask (last 4 digits)"}],
        }
        mock_client = MagicMock()
        mock_client.transactions_sync.return_value = SimpleNamespace(
            added=[], modified=[], removed=[], next_cursor="cursor-A", has_more=False
        )

        with patch(
            "balanceai_backend.source_transactions.sync_source_transactions_from_plaid.get_client",
            return_value=mock_client,
        ):
            counts = sync_source_transactions_from_plaid("item-1", conn=db)

        [call] = mock_sync_bank_accounts.call_args_list
        assert call.args[0].item_id == "item-1"
        assert call.kwargs["conn"] is db
        assert counts["bank_accounts"] == {"saved": 2, "skipped": 1}


class TestUnknownPlaidAccount:
    def test_raises_and_keeps_cursor_when_transaction_account_has_no_bank_account(
        self, db, linked_item
    ):
        mock_client = MagicMock()
        mock_client.transactions_sync.return_value = SimpleNamespace(
            added=[_plaid_txn(account_id="plaid-acc-skipped")],
            modified=[],
            removed=[],
            next_cursor="cursor-A",
            has_more=False,
        )

        with (
            patch(
                "balanceai_backend.source_transactions.sync_source_transactions_from_plaid.get_client",
                return_value=mock_client,
            ),
            pytest.raises(ValueError, match="plaid-acc-skipped"),
        ):
            sync_source_transactions_from_plaid("item-1", conn=db)

        assert find_source_transactions(conn=db) == []
        assert get_plaid_sync_cursor("item-1", conn=db) is None


class TestOurOwnIds:
    """BL-16: our source_transaction_id never changes; Plaid's id is stored apart."""

    def test_stores_plaids_id_apart_from_ours(self, db, linked_item):
        _sync_one_page(db, added=[_plaid_txn()])
        [txn] = find_source_transactions(conn=db)
        assert txn.plaid_transaction_id == "txn-1"
        assert txn.source_transaction_id.startswith("plaid-")

    def test_modified_keeps_our_id(self, db, linked_item):
        _sync_one_page(db, added=[_plaid_txn(amount=4.50)])
        [first] = find_source_transactions(conn=db)
        _sync_one_page(db, modified=[_plaid_txn(amount=5.25)])
        [txn] = find_source_transactions(conn=db)
        assert txn.source_transaction_id == first.source_transaction_id
        assert txn.amount == Decimal("-5.25")

    def test_removed_deletes_by_plaids_id(self, db, linked_item):
        _sync_one_page(db, added=[_plaid_txn()])
        _sync_one_page(db, removed=[SimpleNamespace(transaction_id="txn-1")])
        assert find_source_transactions(conn=db) == []


class TestDates:
    def test_stores_when_it_was_paid_and_when_it_posted(self, db, linked_item):
        _sync_one_page(db, added=[_plaid_txn(authorized_date=date(2026, 8, 17))])
        [txn] = find_source_transactions(conn=db)
        assert (txn.transaction_date, txn.posting_date) == (date(2026, 8, 17), date(2026, 8, 19))

    def test_no_authorized_date_leaves_the_transaction_date_empty(self, db, linked_item):
        _sync_one_page(db, added=[_plaid_txn()])
        [txn] = find_source_transactions(conn=db)
        assert (txn.transaction_date, txn.posting_date) == (None, date(2026, 8, 19))


class TestPendingPosts:
    """Plaid sends the posted version under a new id ("P2", pending_transaction_id
    "P1") and removes the pending one ("P1") in the same sync."""

    @staticmethod
    def _post(db, amount=4.50):
        _sync_one_page(
            db,
            added=[_plaid_txn("P2", amount=amount, pending_transaction_id="P1")],
            removed=[SimpleNamespace(transaction_id="P1")],
        )

    @staticmethod
    def _classify(db, classified_by: ClassifiedBy) -> Classification:
        [pending] = find_source_transactions(conn=db)
        classification = Classification(
            counter_account=JournalAccount.NON_ESSENTIALS_EXPENSE,
            category="dining",
            counterparty="Starbucks",
            classified_by=classified_by,
        )
        with db:
            update_transaction(pending.transaction_id, classification=classification, conn=db)
        return classification

    def test_the_posted_version_updates_the_pending_row(self, db, linked_item):
        _sync_one_page(db, added=[_plaid_txn("P1", pending=True)])
        [pending] = find_source_transactions(conn=db)

        self._post(db)

        [posted] = find_source_transactions(conn=db)
        assert posted.source_transaction_id == pending.source_transaction_id
        assert posted.transaction_id == pending.transaction_id
        assert (posted.plaid_transaction_id, posted.pending) == ("P2", False)
        assert len(find_transactions(conn=db)) == 1

    def test_a_receipt_merged_while_pending_stays_merged(self, db, linked_item):
        _sync_one_page(db, added=[_plaid_txn("P1", pending=True)])
        [pending] = find_source_transactions(conn=db)
        upsert_source_transaction(
            SourceTransaction(
                source_transaction_id="receipt-1",
                source="receipt",
                account_id=BANK_ACCOUNT_ID,
                transaction_date=date(2026, 8, 18),
                description="Starbucks",
                amount=Decimal("-4.50"),
            ),
            conn=db,
        )
        [receipt] = find_source_transactions(source_transaction_id="receipt-1", conn=db)
        assert pending.transaction_id and receipt.transaction_id
        kept = merge_transactions(
            pending.transaction_id, receipt.transaction_id, MatchedBy.RULE, conn=db
        )

        self._post(db)

        assert {s.transaction_id for s in find_source_transactions(conn=db)} == {kept}

    def test_an_unchanged_posting_keeps_the_users_classification(self, db, linked_item):
        _sync_one_page(db, added=[_plaid_txn("P1", pending=True)])
        classification = self._classify(db, ClassifiedBy.USER)

        self._post(db)

        [txn] = find_transactions(conn=db)
        assert txn.classification == classification

    def test_a_changed_amount_flags_the_users_classification(self, db, linked_item):
        _sync_one_page(db, added=[_plaid_txn("P1", amount=4.50, pending=True)])
        classification = self._classify(db, ClassifiedBy.USER)

        self._post(db, amount=5.40)

        [txn] = find_transactions(conn=db)
        assert txn.amount == Decimal("-5.40")
        assert txn.classification == dataclasses.replace(classification, needs_user_review=True)

    def test_a_changed_amount_clears_the_ais_classification(self, db, linked_item):
        _sync_one_page(db, added=[_plaid_txn("P1", amount=4.50, pending=True)])
        self._classify(db, ClassifiedBy.AI)

        self._post(db, amount=5.40)

        [txn] = find_transactions(conn=db)
        assert txn.classification is None

    def test_a_posted_transaction_without_its_pending_one_is_saved_new(self, db, linked_item):
        self._post(db)

        [posted] = find_source_transactions(conn=db)
        assert posted.plaid_transaction_id == "P2"

    def test_an_already_stored_posted_transaction_adopts_nothing(self, db, linked_item):
        _sync_one_page(db, added=[_plaid_txn("P1", pending=True), _plaid_txn("P2")])

        _sync_one_page(db, modified=[_plaid_txn("P2", pending_transaction_id="P1")])

        assert sorted(s.plaid_transaction_id for s in find_source_transactions(conn=db)) == [
            "P1",
            "P2",
        ]
