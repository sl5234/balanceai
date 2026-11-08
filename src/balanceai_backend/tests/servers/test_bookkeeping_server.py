import asyncio
import datetime
import re
import sqlite3
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from balanceai_backend.db.bank_account_db import upsert_bank_account
from balanceai_backend.db.connection import conn, create_schema
from balanceai_backend.db.journal_db import find_booked_raw_transactions
from balanceai_backend.db.readonly_journal_connection import open_readonly_journal_connection
from balanceai_backend.models.bank_account import BankAccount, BankAccountType
from balanceai_backend.models.financial_query import (
    REJECTION_MESSAGES,
    UNANSWERABLE_MESSAGE,
    FinancialQuery,
    QueryRejection,
)
from balanceai_backend.models.journal import (
    GeneratedJournalEntrySet,
    GeneratedJournalLine,
    Journal,
    JournalAccount,
    JournalLine,
)
from balanceai_backend.models.raw_transaction import Classification, ClassifiedBy, RawTransaction
from balanceai_backend.raw_transactions.raw_transaction_db import upsert_raw_transaction
from balanceai_backend.servers.bookkeeping_server import (
    ShareJournalEntriesConsent,
    ShareQueryRowsConsent,
    _hide_descriptions,
    analyze_financial_question,
    create_journal,
    delete_journal,
    list_journal_entries,
    list_journals,
    sync_journal_entries_from_receipt,
    update_journal,
)
from mcp.server.elicitation import (
    AcceptedElicitation,
    CancelledElicitation,
    DeclinedElicitation,
)


@pytest.fixture
def sample_entry():
    return JournalLine(
        journal_line_id="entry-1",
        date=datetime.date(2026, 1, 27),
        account=JournalAccount.CASH,
        description="Trader Joe's purchase",
        debit=Decimal("32.02"),
        credit=Decimal("0.00"),
    )


@pytest.fixture
def sample_entry_2():
    return JournalLine(
        journal_line_id="entry-2",
        date=datetime.date(2026, 1, 28),
        account=JournalAccount.CASH,
        description="Whole Foods purchase",
        debit=Decimal("54.10"),
        credit=Decimal("0.00"),
    )


@pytest.fixture
def journal_with_no_entries():
    return Journal(
        journal_id="journal-1",
        name="January journal",
        lines=[],
    )


@pytest.fixture
def journal_with_entries(sample_entry, sample_entry_2):
    return Journal(
        journal_id="journal-1",
        name="January journal",
        lines=[sample_entry, sample_entry_2],
    )


def _make_ctx(elicit_result) -> MagicMock:
    ctx = MagicMock()
    ctx.elicit = AsyncMock(return_value=elicit_result)
    return ctx


def _list(journal_id: str, ctx: MagicMock | None = None, **kwargs) -> list[dict]:
    """Call list_journal_entries; the user approves sharing unless ctx says otherwise."""
    ctx = ctx or _make_ctx(AcceptedElicitation(data=ShareJournalEntriesConsent()))
    return asyncio.run(list_journal_entries(ctx, journal_id, **kwargs))


class TestListJournalEntriesConsent:
    def test_asks_before_returning_entries(self, sample_entry, sample_entry_2):
        ctx = _make_ctx(AcceptedElicitation(data=ShareJournalEntriesConsent()))
        with patch(
            "balanceai_backend.servers.bookkeeping_server.db_find_journal_lines",
            return_value=[sample_entry, sample_entry_2],
        ):
            result = _list("journal-1", ctx=ctx)

        ctx.elicit.assert_awaited_once()
        message = ctx.elicit.await_args.kwargs["message"]
        assert "2 journal entries" in message
        assert "2026-01-27 to 2026-01-28" in message
        assert len(result) == 2

    @pytest.mark.parametrize(
        "elicit_result",
        [DeclinedElicitation(), CancelledElicitation()],
        ids=["declined", "cancelled"],
    )
    def test_raises_and_returns_nothing_when_user_does_not_approve(
        self, sample_entry, elicit_result
    ):
        with (
            patch(
                "balanceai_backend.servers.bookkeeping_server.db_find_journal_lines",
                return_value=[sample_entry],
            ),
            pytest.raises(PermissionError, match="declined"),
        ):
            _list("journal-1", ctx=_make_ctx(elicit_result))

    def test_propagates_error_when_client_does_not_support_elicitation(self, sample_entry):
        ctx = MagicMock()
        ctx.elicit = AsyncMock(side_effect=RuntimeError("elicitation not supported"))
        with (
            patch(
                "balanceai_backend.servers.bookkeeping_server.db_find_journal_lines",
                return_value=[sample_entry],
            ),
            pytest.raises(RuntimeError),
        ):
            _list("journal-1", ctx=ctx)

    def test_returns_empty_list_without_asking_when_no_entries(self):
        ctx = _make_ctx(DeclinedElicitation())
        with patch(
            "balanceai_backend.servers.bookkeeping_server.db_find_journal_lines", return_value=[]
        ):
            assert _list("journal-1", ctx=ctx) == []

        ctx.elicit.assert_not_called()


class TestListJournalEntries:
    def test_returns_empty_list_when_journal_has_no_entries(self):
        with patch(
            "balanceai_backend.servers.bookkeeping_server.db_find_journal_lines", return_value=[]
        ):
            result = _list("journal-1")
        assert result == []

    def test_returns_all_entries(self, sample_entry, sample_entry_2):
        with patch(
            "balanceai_backend.servers.bookkeeping_server.db_find_journal_lines",
            return_value=[sample_entry, sample_entry_2],
        ):
            result = _list("journal-1")
        assert len(result) == 2

    def test_returns_entries_in_order(self, sample_entry, sample_entry_2):
        with patch(
            "balanceai_backend.servers.bookkeeping_server.db_find_journal_lines",
            return_value=[sample_entry, sample_entry_2],
        ):
            result = _list("journal-1")
        assert result[0]["lines"][0]["journal_line_id"] == sample_entry.journal_line_id
        assert result[1]["lines"][0]["journal_line_id"] == sample_entry_2.journal_line_id

    def test_entries_are_returned_as_dicts(self, sample_entry, sample_entry_2):
        with patch(
            "balanceai_backend.servers.bookkeeping_server.db_find_journal_lines",
            return_value=[sample_entry, sample_entry_2],
        ):
            result = _list("journal-1")
        for entry in result:
            assert isinstance(entry, dict)

    def test_entry_dict_contains_expected_fields(self, sample_entry):
        with patch(
            "balanceai_backend.servers.bookkeeping_server.db_find_journal_lines",
            return_value=[sample_entry],
        ):
            result = _list("journal-1")
        assert result[0]["date"] == sample_entry.date.isoformat()
        line = result[0]["lines"][0]
        assert line["journal_line_id"] == sample_entry.journal_line_id
        assert line["date"] == sample_entry.date.isoformat()
        assert line["description"] is None
        assert line["debit"] == str(sample_entry.debit)
        assert line["credit"] == str(sample_entry.credit)

    def test_entry_dict_includes_tax_field(self, sample_entry):
        with patch(
            "balanceai_backend.servers.bookkeeping_server.db_find_journal_lines",
            return_value=[sample_entry],
        ):
            result = _list("journal-1")
        line = result[0]["lines"][0]
        assert line["tax"] == "0"

    def test_raises_value_error_when_journal_not_found(self):
        with (
            patch(
                "balanceai_backend.servers.bookkeeping_server.db_find_journal_lines",
                side_effect=ValueError("journal-999"),
            ),
            pytest.raises(ValueError, match="journal-999"),
        ):
            _list("journal-999")

    def test_filters_entries_by_date(self, sample_entry, sample_entry_2):
        with patch(
            "balanceai_backend.servers.bookkeeping_server.db_find_journal_lines",
            return_value=[sample_entry, sample_entry_2],
        ):
            result = _list("journal-1", date=sample_entry.date)
        assert [e["lines"][0]["journal_line_id"] for e in result] == [sample_entry.journal_line_id]

    def test_returns_empty_list_when_no_entries_match_date(self, sample_entry):
        with patch(
            "balanceai_backend.servers.bookkeeping_server.db_find_journal_lines",
            return_value=[sample_entry],
        ):
            result = _list("journal-1", date=datetime.date(2020, 1, 1))
        assert result == []

    def test_lines_of_one_entry_are_grouped(self, sample_entry, sample_entry_2):
        sample_entry.journal_entry_id = sample_entry_2.journal_entry_id = "e-1"
        with patch(
            "balanceai_backend.servers.bookkeeping_server.db_find_journal_lines",
            return_value=[sample_entry, sample_entry_2],
        ):
            result = _list("journal-1")
        assert len(result) == 1
        assert result[0]["journal_entry_id"] == "e-1"
        assert [line["journal_line_id"] for line in result[0]["lines"]] == ["entry-1", "entry-2"]

    def test_date_filter_returns_a_matched_transfer_whole(self, sample_entry, sample_entry_2):
        """A matched transfer's lines can be days apart; one on the date is enough."""
        sample_entry.journal_entry_id = sample_entry_2.journal_entry_id = "e-1"
        with patch(
            "balanceai_backend.servers.bookkeeping_server.db_find_journal_lines",
            return_value=[sample_entry, sample_entry_2],
        ):
            result = _list("journal-1", date=sample_entry_2.date)
        assert len(result) == 1
        assert len(result[0]["lines"]) == 2

    def test_returns_all_entries_when_date_not_provided(self, sample_entry, sample_entry_2):
        with patch(
            "balanceai_backend.servers.bookkeeping_server.db_find_journal_lines",
            return_value=[sample_entry, sample_entry_2],
        ):
            result = _list("journal-1")
        assert len(result) == 2


# ---------------------------------------------------------------------------
# create_or_update_journal_entries
# ---------------------------------------------------------------------------


@pytest.fixture
def journal():
    return Journal(
        journal_id="journal-1",
        name="January journal",
        lines=[],
    )


@pytest.fixture
def receipt_path(tmp_path):
    # File must exist so read_bytes() succeeds; contents are irrelevant because
    # OcrUtil.executeWithAnthropic is mocked in every test.
    img = tmp_path / "receipt.jpg"
    img.write_bytes(b"fake-image-data")
    return str(img)


@pytest.fixture
def ocr_entry_data():
    return GeneratedJournalLine(
        date=datetime.date(2026, 1, 27),
        account=JournalAccount.NON_ESSENTIALS_EXPENSE,
        description="Grocery purchase at Trader Joe's",
        debit=Decimal("32.02"),
        credit=Decimal("0.00"),
    )


@pytest.fixture
def ocr_result(ocr_entry_data):
    return GeneratedJournalEntrySet(
        lines=[
            ocr_entry_data,
            GeneratedJournalLine(
                date=datetime.date(2026, 1, 27),
                account=JournalAccount.CASH,
                description="Grocery purchase at Trader Joe's",
                debit=Decimal("0.00"),
                credit=Decimal("32.02"),
            ),
        ]
    )


class TestCreateOrUpdateJournalEntriesForReceipt:
    def test_raises_when_journal_not_found(self, receipt_path):
        with (
            patch("balanceai_backend.helpers.journal_entry_helper.find_journals", return_value=[]),
            pytest.raises(ValueError, match="journal-999"),
        ):
            sync_journal_entries_from_receipt("journal-999", receipt_path)

    def test_creates_new_entry_when_no_match(self, journal, receipt_path, ocr_result):
        with (
            patch(
                "balanceai_backend.helpers.journal_entry_helper.find_journals",
                return_value=[journal],
            ),
            patch(
                "balanceai_backend.utils.ocr_util.OcrUtil.executeWithAnthropic",
                return_value=ocr_result,
            ),
            patch(
                "balanceai_backend.helpers.journal_entry_helper.finder_find_journal_line",
                return_value=None,
            ),
            patch("balanceai_backend.helpers.journal_entry_helper.db_update_journal"),
        ):
            result = sync_journal_entries_from_receipt("journal-1", receipt_path)

        assert len(result["lines"]) == 2
        descriptions = {e["description"] for e in result["lines"]}
        assert "Grocery purchase at Trader Joe's" in descriptions

    def test_new_entry_gets_fresh_id(self, journal, receipt_path, ocr_result):
        with (
            patch(
                "balanceai_backend.helpers.journal_entry_helper.find_journals",
                return_value=[journal],
            ),
            patch(
                "balanceai_backend.utils.ocr_util.OcrUtil.executeWithAnthropic",
                return_value=ocr_result,
            ),
            patch(
                "balanceai_backend.helpers.journal_entry_helper.finder_find_journal_line",
                return_value=None,
            ),
            patch("balanceai_backend.helpers.journal_entry_helper.db_update_journal"),
        ):
            result = sync_journal_entries_from_receipt("journal-1", receipt_path)

        line_id = result["lines"][0]["journal_line_id"]
        assert line_id is not None
        assert line_id != ""

    def test_updates_existing_entry_preserving_id(self, receipt_path, ocr_result):
        existing_entry = JournalLine(
            journal_line_id="original-id",
            date=datetime.date(2026, 1, 27),
            account=JournalAccount.NON_ESSENTIALS_EXPENSE,
            description="Old description",
            debit=Decimal("30.00"),
            credit=Decimal("0.00"),
        )
        journal = Journal(
            journal_id="journal-1",
            name="January journal",
            lines=[existing_entry],
        )

        with (
            patch(
                "balanceai_backend.helpers.journal_entry_helper.find_journals",
                return_value=[journal],
            ),
            patch(
                "balanceai_backend.utils.ocr_util.OcrUtil.executeWithAnthropic",
                return_value=ocr_result,
            ),
            patch(
                "balanceai_backend.helpers.journal_entry_helper.finder_find_journal_line",
                side_effect=[existing_entry, None],
            ),
            patch("balanceai_backend.helpers.journal_entry_helper.db_update_journal"),
        ):
            result = sync_journal_entries_from_receipt("journal-1", receipt_path)

        assert len(result["lines"]) == 2
        expense = next(
            e
            for e in result["lines"]
            if e["account"] == JournalAccount.NON_ESSENTIALS_EXPENSE.value
        )
        assert expense["journal_line_id"] == "original-id"
        assert expense["description"] == "Grocery purchase at Trader Joe's"
        assert expense["debit"] == "32.02"

    def test_adds_multiple_entries_from_ocr(self, journal, receipt_path):
        # Double-entry: one debit line and one credit line from the same receipt
        double_entry_result = GeneratedJournalEntrySet(
            lines=[
                GeneratedJournalLine(
                    date=datetime.date(2026, 1, 27),
                    account=JournalAccount.NON_ESSENTIALS_EXPENSE,
                    description="Grocery purchase at Trader Joe's",
                    debit=Decimal("32.02"),
                    credit=Decimal("0.00"),
                ),
                GeneratedJournalLine(
                    date=datetime.date(2026, 1, 27),
                    account=JournalAccount.CASH,
                    description="Payment via Visa",
                    debit=Decimal("0.00"),
                    credit=Decimal("32.02"),
                ),
            ]
        )

        with (
            patch(
                "balanceai_backend.helpers.journal_entry_helper.find_journals",
                return_value=[journal],
            ),
            patch(
                "balanceai_backend.utils.ocr_util.OcrUtil.executeWithAnthropic",
                return_value=double_entry_result,
            ),
            patch(
                "balanceai_backend.helpers.journal_entry_helper.finder_find_journal_line",
                return_value=None,
            ),
            patch("balanceai_backend.helpers.journal_entry_helper.db_update_journal"),
        ):
            result = sync_journal_entries_from_receipt("journal-1", receipt_path)

        assert len(result["lines"]) == 2

    def test_no_entries_from_ocr_leaves_journal_unchanged(self, journal, receipt_path):
        empty_ocr_result = GeneratedJournalEntrySet(lines=[])

        with (
            patch(
                "balanceai_backend.helpers.journal_entry_helper.find_journals",
                return_value=[journal],
            ),
            patch(
                "balanceai_backend.utils.ocr_util.OcrUtil.executeWithAnthropic",
                return_value=empty_ocr_result,
            ),
            patch("balanceai_backend.helpers.journal_entry_helper.db_update_journal"),
        ):
            result = sync_journal_entries_from_receipt("journal-1", receipt_path)

        assert result["lines"] == []

    def test_storage_update_called_once(self, journal, receipt_path, ocr_result):
        with (
            patch(
                "balanceai_backend.helpers.journal_entry_helper.find_journals",
                return_value=[journal],
            ),
            patch(
                "balanceai_backend.utils.ocr_util.OcrUtil.executeWithAnthropic",
                return_value=ocr_result,
            ),
            patch(
                "balanceai_backend.helpers.journal_entry_helper.finder_find_journal_line",
                return_value=None,
            ),
            patch("balanceai_backend.helpers.journal_entry_helper.db_update_journal") as mock_save,
        ):
            sync_journal_entries_from_receipt("journal-1", receipt_path)

        mock_save.assert_called_once_with(journal, conn)

    def test_returns_journal_as_dict(self, journal, receipt_path, ocr_result):
        with (
            patch(
                "balanceai_backend.helpers.journal_entry_helper.find_journals",
                return_value=[journal],
            ),
            patch(
                "balanceai_backend.utils.ocr_util.OcrUtil.executeWithAnthropic",
                return_value=ocr_result,
            ),
            patch(
                "balanceai_backend.helpers.journal_entry_helper.finder_find_journal_line",
                return_value=None,
            ),
            patch("balanceai_backend.helpers.journal_entry_helper.db_update_journal"),
        ):
            result = sync_journal_entries_from_receipt("journal-1", receipt_path)

        assert isinstance(result, dict)
        assert "journal_id" in result
        assert "lines" in result

    def test_mixed_new_and_updated_entries(self, receipt_path):
        # The journal already has a GENERAL entry. OCR returns two entries:
        # one GENERAL (matches the existing entry → update, preserve ID) and
        # one CASH (no match → create, gets a new ID).
        existing_entry = JournalLine(
            journal_line_id="existing-id",
            date=datetime.date(2026, 1, 27),
            account=JournalAccount.NON_ESSENTIALS_EXPENSE,
            description="Old grocery description",
            debit=Decimal("30.00"),
            credit=Decimal("0.00"),
        )
        journal = Journal(
            journal_id="journal-1",
            name="January journal",
            lines=[existing_entry],
        )
        ocr_result = GeneratedJournalEntrySet(
            lines=[
                GeneratedJournalLine(
                    date=datetime.date(2026, 1, 27),
                    account=JournalAccount.NON_ESSENTIALS_EXPENSE,
                    description="Grocery purchase at Trader Joe's",
                    debit=Decimal("32.02"),
                    credit=Decimal("0.00"),
                ),
                GeneratedJournalLine(
                    date=datetime.date(2026, 1, 27),
                    account=JournalAccount.CASH,
                    description="Payment via Visa",
                    debit=Decimal("0.00"),
                    credit=Decimal("32.02"),
                ),
            ]
        )

        def fake_finder(journal_id, entry):
            # Only the GENERAL entry matches the pre-existing journal entry
            return (
                existing_entry if entry.account == JournalAccount.NON_ESSENTIALS_EXPENSE else None
            )

        with (
            patch(
                "balanceai_backend.helpers.journal_entry_helper.find_journals",
                return_value=[journal],
            ),
            patch(
                "balanceai_backend.utils.ocr_util.OcrUtil.executeWithAnthropic",
                return_value=ocr_result,
            ),
            patch(
                "balanceai_backend.helpers.journal_entry_helper.finder_find_journal_line",
                side_effect=fake_finder,
            ),
            patch("balanceai_backend.helpers.journal_entry_helper.db_update_journal"),
        ):
            result = sync_journal_entries_from_receipt("journal-1", receipt_path)

        assert len(result["lines"]) == 2
        ids = {e["journal_line_id"] for e in result["lines"]}
        assert "existing-id" in ids


class TestJournalTools:
    """create/update/list/delete journal tools, against an in-memory database."""

    @pytest.fixture
    def db(self):
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        create_schema(connection)
        with patch("balanceai_backend.servers.bookkeeping_server.conn", connection):
            yield connection
        connection.close()

    def test_create_journal_returns_and_saves_journal(self, db):
        result = create_journal(name="Personal", description="Household books")

        assert result["name"] == "Personal"
        assert result["description"] == "Household books"
        assert result["lines"] == []
        [row] = db.execute("SELECT * FROM journals").fetchall()
        assert row["journal_id"] == result["journal_id"]
        assert row["name"] == "Personal"

    def test_create_journal_description_defaults_to_empty(self, db):
        assert create_journal(name="Personal")["description"] == ""

    def test_create_journal_rejects_duplicate_name_case_insensitively(self, db):
        create_journal(name="Personal")

        with pytest.raises(ValueError, match="already exists"):
            create_journal(name="personal")

        assert len(list_journals()) == 1

    def test_update_journal_changes_only_given_fields(self, db):
        journal_id = create_journal(name="Personal", description="Household books")["journal_id"]

        result = update_journal(journal_id, name="Home")

        assert result["name"] == "Home"
        assert result["description"] == "Household books"

    def test_update_journal_rejects_name_used_by_another_journal(self, db):
        create_journal(name="Personal")
        journal_id = create_journal(name="My LLC")["journal_id"]

        with pytest.raises(ValueError, match="already exists"):
            update_journal(journal_id, name="PERSONAL")

    def test_update_journal_allows_keeping_its_own_name(self, db):
        journal_id = create_journal(name="Personal")["journal_id"]

        result = update_journal(journal_id, name="Personal", description="Household")

        assert result["description"] == "Household"

    def test_update_journal_raises_when_not_found(self, db):
        with pytest.raises(ValueError, match="not found"):
            update_journal("missing", name="Home")

    def test_list_journals_returns_all_without_entries(self, db):
        create_journal(name="Personal")
        create_journal(name="My LLC")

        result = list_journals()

        assert {j["name"] for j in result} == {"Personal", "My LLC"}
        assert all(j["lines"] == [] for j in result)

    def test_delete_journal_removes_it(self, db):
        journal_id = create_journal(name="Personal")["journal_id"]

        assert delete_journal(journal_id) == {"journal_id": journal_id}
        assert list_journals() == []

    @pytest.fixture
    def bank_accounts(self, db):
        ids = ["test_bank:checking:0000", "test_bank:savings:1111", "test_bank:credit_card:2222"]
        for account_id in ids:
            upsert_bank_account(
                BankAccount(
                    id=account_id,
                    institution_name="Test Bank",
                    account_type=BankAccountType(account_id.split(":")[1]),
                    last4=account_id[-4:],
                ),
                conn=db,
            )
        return ids

    def test_create_journal_with_bank_accounts(self, db, bank_accounts):
        checking, savings, _ = bank_accounts

        result = create_journal(name="Personal", bank_account_ids=[checking, savings])

        assert result["bank_account_ids"] == [checking, savings]
        [listed] = list_journals()
        assert listed["bank_account_ids"] == [checking, savings]

    def test_update_journal_without_bank_accounts_keeps_them(self, db, bank_accounts):
        checking, _, _ = bank_accounts
        journal_id = create_journal(name="Personal", bank_account_ids=[checking])["journal_id"]

        update_journal(journal_id, name="Home")

        [listed] = list_journals()
        assert listed["bank_account_ids"] == [checking]

    def test_update_journal_replaces_bank_accounts(self, db, bank_accounts):
        checking, savings, card = bank_accounts
        journal_id = create_journal(name="Personal", bank_account_ids=[checking, savings])[
            "journal_id"
        ]

        update_journal(journal_id, bank_account_ids=[card])

        [listed] = list_journals()
        assert listed["bank_account_ids"] == [card]

    def test_create_journal_with_taken_account_raises(self, db, bank_accounts):
        checking, _, _ = bank_accounts
        create_journal(name="Personal", bank_account_ids=[checking])

        with pytest.raises(ValueError, match="already in journal 'Personal'"):
            create_journal(name="My LLC", bank_account_ids=[checking])

        assert [j["name"] for j in list_journals()] == ["Personal"]

    @staticmethod
    def _add_purchase(db, txn_id: str, account_id: str) -> None:
        upsert_raw_transaction(
            RawTransaction(
                id=txn_id,
                source="plaid",
                account_id=account_id,
                posting_date=datetime.date(2026, 10, 1),
                description="STARBUCKS",
                amount=Decimal("-4.33"),
                classification=Classification(
                    counter_account=JournalAccount.NON_ESSENTIALS_EXPENSE,
                    category="dining",
                    counterparty="Starbucks",
                    classified_by=ClassifiedBy.AI,
                ),
            ),
            conn=db,
        )

    @staticmethod
    def _booked_txns(db, journal_id: str) -> set[str]:
        return set(find_booked_raw_transactions(journal_id, db))

    def test_create_journal_books_its_accounts(self, db, bank_accounts):
        checking, _, card = bank_accounts
        self._add_purchase(db, "on-checking", checking)
        self._add_purchase(db, "on-card", card)

        result = create_journal(name="Personal", bank_account_ids=[checking])

        assert result["booking"] == {"booked": 1, "matched": 0}
        assert self._booked_txns(db, result["journal_id"]) == {"on-checking"}

    def test_update_journal_books_an_added_account(self, db, bank_accounts):
        checking, savings, _ = bank_accounts
        self._add_purchase(db, "on-checking", checking)
        self._add_purchase(db, "on-savings", savings)
        journal_id = create_journal(name="Personal", bank_account_ids=[checking])["journal_id"]

        result = update_journal(journal_id, bank_account_ids=[checking, savings])

        assert result["booking"] == {"booked": 1, "matched": 0}
        assert self._booked_txns(db, journal_id) == {"on-checking", "on-savings"}

    def test_update_journal_removing_an_account_deletes_its_entries(self, db, bank_accounts):
        checking, savings, _ = bank_accounts
        self._add_purchase(db, "on-checking", checking)
        self._add_purchase(db, "on-savings", savings)
        journal_id = create_journal(name="Personal", bank_account_ids=[checking, savings])[
            "journal_id"
        ]

        update_journal(journal_id, bank_account_ids=[savings])

        assert self._booked_txns(db, journal_id) == {"on-savings"}

    def test_update_journal_result_omits_entries(self, db, bank_accounts):
        """The journal is loaded before the update, so its entries would be stale."""
        checking, savings, _ = bank_accounts
        self._add_purchase(db, "on-checking", checking)
        journal_id = create_journal(name="Personal", bank_account_ids=[checking, savings])[
            "journal_id"
        ]

        result = update_journal(journal_id, bank_account_ids=[savings])

        assert result["lines"] == []
        assert result["bank_account_ids"] == [savings]


_PARSE = "balanceai_backend.servers.bookkeeping_server.anthropic_service.parse"


def _analyze(sql: str, ctx: MagicMock, question: str = "How much did I spend?") -> dict:
    """Call analyze_financial_question with the AI's reply mocked to the given SQL."""
    query = FinancialQuery(sql=sql, description="Total spend", rejection=None)
    with patch(_PARSE, return_value=query):
        return asyncio.run(analyze_financial_question(ctx, question))


class TestAnalyzeFinancialQuestion:
    def test_returns_rows_when_user_accepts(self):
        ctx = _make_ctx(AcceptedElicitation(data=ShareQueryRowsConsent()))
        result = _analyze("SELECT 42 AS total", ctx)
        assert result["rows"] == [{"total": 42}]
        ctx.elicit.assert_awaited_once()
        message = ctx.elicit.await_args.kwargs["message"]
        assert "Share 1 rows" in message
        assert 'Question asked: "How much did I spend?"' in message
        assert "Total spend" not in message  # the AI's summary isn't shown

    @pytest.mark.parametrize("elicit_result", [DeclinedElicitation(), CancelledElicitation()])
    def test_raises_when_user_declines_or_cancels(self, elicit_result):
        with pytest.raises(PermissionError):
            _analyze("SELECT 42 AS total", _make_ctx(elicit_result))

    def test_returns_without_asking_when_no_rows(self):
        ctx = _make_ctx(AcceptedElicitation(data=ShareQueryRowsConsent()))
        result = _analyze("SELECT debit FROM journal_lines WHERE 0", ctx)
        assert result["rows"] == [] and result["row_count"] == 0
        ctx.elicit.assert_not_awaited()

    def test_blocks_sql_outside_journal_tables(self):
        ctx = _make_ctx(AcceptedElicitation(data=ShareQueryRowsConsent()))
        with pytest.raises(RuntimeError, match=re.escape(UNANSWERABLE_MESSAGE)):
            _analyze("SELECT access_token FROM plaid_items", ctx)
        ctx.elicit.assert_not_awaited()

    def test_raises_when_ai_declines(self):
        ctx = _make_ctx(AcceptedElicitation(data=ShareQueryRowsConsent()))
        with patch(_PARSE, return_value=None), pytest.raises(ValueError):
            asyncio.run(analyze_financial_question(ctx, "q"))

    def test_error_text_with_data_does_not_reach_the_assistant(self):
        """SBL-1: a value that isn't UTF-8 makes sqlite3 quote it in the error,
        which would reach the assistant before the consent prompt."""
        ctx = _make_ctx(AcceptedElicitation(data=ShareQueryRowsConsent()))
        with pytest.raises(RuntimeError) as error:
            _analyze("SELECT 'Acme Corp|5000.0' || x'ff' AS x", ctx)
        assert str(error.value) == UNANSWERABLE_MESSAGE
        assert error.value.__cause__ is None and error.value.__suppress_context__
        ctx.elicit.assert_not_awaited()

    def test_broken_sql_gives_the_plain_message(self):
        ctx = _make_ctx(AcceptedElicitation(data=ShareQueryRowsConsent()))
        with pytest.raises(RuntimeError, match=re.escape(UNANSWERABLE_MESSAGE)):
            _analyze("SELEC nonsense", ctx)

    @pytest.mark.parametrize("rejection", list(QueryRejection))
    def test_rejection_gives_its_message_and_runs_no_sql(self, rejection):
        ctx = _make_ctx(AcceptedElicitation(data=ShareQueryRowsConsent()))
        query = FinancialQuery(sql=None, description="q", rejection=rejection)
        with (
            patch(_PARSE, return_value=query),
            patch("balanceai_backend.servers.bookkeeping_server.readonly_journal_conn") as ro,
            pytest.raises(ValueError) as error,
        ):
            asyncio.run(analyze_financial_question(ctx, "q"))
        assert str(error.value) == REJECTION_MESSAGES[rejection]
        ro.execute.assert_not_called()

    def test_no_sql_and_no_rejection_gives_the_plain_message(self):
        ctx = _make_ctx(AcceptedElicitation(data=ShareQueryRowsConsent()))
        query = FinancialQuery(sql=None, description="q", rejection=None)
        with patch(_PARSE, return_value=query), pytest.raises(ValueError) as error:
            asyncio.run(analyze_financial_question(ctx, "q"))
        assert str(error.value) == UNANSWERABLE_MESSAGE

    def test_every_rejection_has_a_message(self):
        assert set(REJECTION_MESSAGES) == set(QueryRejection)


class TestHideDescriptions:
    @pytest.fixture(autouse=True)
    def journal(self, tmp_path):
        """Two journal lines: one whose description is raw bank text, and one
        whose description is also its counterparty."""
        path = tmp_path / "journal.db"
        db = sqlite3.connect(path)
        db.execute("CREATE TABLE journal_lines (description TEXT, counterparty TEXT)")
        db.executemany(
            "INSERT INTO journal_lines VALUES (?, ?)",
            [("SQ *BLUE BOTTLE 0423 OAKLAND", "Blue Bottle Coffee"), ("Shell", "Shell")],
        )
        db.commit()
        readonly = open_readonly_journal_connection(path)
        with patch("balanceai_backend.servers.bookkeeping_server.readonly_journal_conn", readonly):
            yield
        readonly.close()
        db.close()

    @pytest.mark.parametrize("column", ["description", "d"])
    def test_hides_a_description_under_any_column_name(self, column):
        rows = _hide_descriptions([{column: "SQ *BLUE BOTTLE 0423 OAKLAND"}])
        assert rows == [{column: "[hidden description]"}]

    def test_keeps_a_description_that_is_also_a_counterparty(self):
        assert _hide_descriptions([{"description": "Shell"}]) == [{"description": "Shell"}]

    def test_keeps_everything_else(self):
        row = {"counterparty": "Blue Bottle Coffee", "debit": 6.5, "date": "2025-10-22"}
        assert _hide_descriptions([row]) == [row]

    def test_analyze_returns_rows_with_descriptions_hidden(self):
        ctx = _make_ctx(AcceptedElicitation(data=ShareQueryRowsConsent()))
        result = _analyze("SELECT description, counterparty FROM journal_lines ORDER BY 2", ctx)
        assert result["rows"] == [
            {"description": "[hidden description]", "counterparty": "Blue Bottle Coffee"},
            {"description": "Shell", "counterparty": "Shell"},
        ]
