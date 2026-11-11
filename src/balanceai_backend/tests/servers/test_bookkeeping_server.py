import asyncio
import datetime
import re
import sqlite3
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from balanceai_backend.db.bank_account_db import upsert_bank_account
from balanceai_backend.db.connection import create_schema
from balanceai_backend.db.journal_db import find_booked_raw_transactions
from balanceai_backend.db.readonly_journal_connection import open_readonly_journal_connection
from balanceai_backend.models.bank_account import BankAccount, BankAccountType
from balanceai_backend.models.consent import (
    BookReceiptConsent,
    ShareJournalEntriesConsent,
    ShareQueryRowsConsent,
)
from balanceai_backend.models.financial_query import (
    REJECTION_MESSAGES,
    UNANSWERABLE_MESSAGE,
    FinancialQuery,
    QueryRejection,
)
from balanceai_backend.models.journal import (
    Journal,
    JournalAccount,
    JournalLine,
)
from balanceai_backend.models.raw_transaction import Classification, ClassifiedBy, RawTransaction
from balanceai_backend.models.receipt import PaymentMethod, ReceiptExtraction, ReceiptKind
from balanceai_backend.raw_transactions.raw_transaction_db import (
    find_raw_transactions,
    update_raw_transaction_classification,
    upsert_raw_transaction,
)
from balanceai_backend.servers.bookkeeping_server import (
    analyze_financial_question,
    create_journal,
    delete_journal,
    list_journal_entries,
    list_journals,
    update_journal,
    upload_receipt,
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


class TestUploadReceipt:
    """upload_receipt against an in-memory database; reading the image and
    classifying are mocked (no AI calls)."""

    CHECKING = "test_bank:checking:0000"

    @pytest.fixture
    def db(self):
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        create_schema(connection)
        upsert_bank_account(
            BankAccount(
                id=self.CHECKING,
                institution_name="Test Bank",
                account_type=BankAccountType.CHECKING,
                last4="1234",
            ),
            conn=connection,
        )
        with patch("balanceai_backend.servers.bookkeeping_server.conn", connection):
            yield connection
        connection.close()

    @pytest.fixture
    def journal_id(self, db):
        return create_journal(name="Personal", bank_account_ids=[self.CHECKING])["journal_id"]

    def _receipt(self, card_last4="1234"):
        return ReceiptExtraction(
            date=datetime.date(2026, 11, 8),
            counterparty="Blue Bottle Coffee",
            kind=ReceiptKind.PURCHASE,
            total=Decimal("12.50"),
            payment_method=PaymentMethod.CARD,
            card_last4=card_last4,
            category="dining",
        )

    def _upload(self, db, ctx, receipt=None, **kwargs):
        def classify(conn):
            for txn in find_raw_transactions(unclassified=True, conn=conn):
                update_raw_transaction_classification(
                    txn.raw_transaction_id,
                    Classification(
                        counter_account=JournalAccount.NON_ESSENTIALS_EXPENSE,
                        category="dining",
                        counterparty="Blue Bottle Coffee",
                        classified_by=ClassifiedBy.AI,
                    ),
                    conn=conn,
                )

        server = "balanceai_backend.servers.bookkeeping_server"
        with (
            patch(f"{server}.resolve_receipt_path"),
            patch(f"{server}.read_receipt", return_value=receipt or self._receipt()),
            patch(f"{server}.classify_raw_transactions", side_effect=classify),
        ):
            return asyncio.run(upload_receipt(ctx, "receipt.jpg", **kwargs))

    def test_books_the_receipt_when_the_user_accepts(self, db, journal_id):
        ctx = _make_ctx(AcceptedElicitation(data=BookReceiptConsent()))
        result = self._upload(db, ctx)
        assert result == {"booked": True, "journal_id": journal_id}  # no receipt details
        message = ctx.elicit.await_args.kwargs["message"]
        assert "Blue Bottle Coffee" in message and "matched the account's last 4" in message
        assert len(find_booked_raw_transactions(journal_id, conn=db)) == 1

    @pytest.mark.parametrize("elicit_result", [DeclinedElicitation(), CancelledElicitation()])
    def test_saves_nothing_when_declined(self, db, journal_id, elicit_result):
        with pytest.raises(PermissionError):
            self._upload(db, _make_ctx(elicit_result))
        assert find_raw_transactions(source="receipt", conn=db) == []

    def test_account_given_by_the_user(self, db, journal_id):
        ctx = _make_ctx(AcceptedElicitation(data=BookReceiptConsent()))
        self._upload(db, ctx, receipt=self._receipt(card_last4="9999"), account_id=self.CHECKING)
        assert "chosen by you" in ctx.elicit.await_args.kwargs["message"]

    def test_unknown_account_raises_before_asking(self, db, journal_id):
        ctx = _make_ctx(AcceptedElicitation(data=BookReceiptConsent()))
        with pytest.raises(ValueError, match="No bank account"):
            self._upload(db, ctx, account_id="nope")
        ctx.elicit.assert_not_awaited()

    def test_unknown_card_asks_for_the_account(self, db, journal_id):
        ctx = _make_ctx(AcceptedElicitation(data=BookReceiptConsent()))
        with pytest.raises(ValueError, match="Couldn't tell which account") as error:
            self._upload(db, ctx, receipt=self._receipt(card_last4="9999"))
        assert "9999" not in str(error.value)
        ctx.elicit.assert_not_awaited()

    def test_account_in_no_journal_is_saved_not_booked(self, db):
        ctx = _make_ctx(AcceptedElicitation(data=BookReceiptConsent()))
        result = self._upload(db, ctx)
        assert result["booked"] is False and result["journal_id"] is None
        assert "won't be booked" in ctx.elicit.await_args.kwargs["message"]
        assert len(find_raw_transactions(source="receipt", conn=db)) == 1


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

    def test_create_journal_creates_its_cash_account(self, db):
        result = create_journal(name="Personal")
        cash_id = f"cash:cash:{result['journal_id']}"
        assert result["bank_account_ids"] == [cash_id]
        [row] = db.execute(
            "SELECT bank_account_id FROM journal_bank_accounts WHERE journal_id = ?",
            (result["journal_id"],),
        ).fetchall()
        assert row["bank_account_id"] == cash_id

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

        cash = f"cash:cash:{result['journal_id']}"
        assert result["bank_account_ids"] == [checking, savings, cash]
        [listed] = list_journals()
        assert sorted(listed["bank_account_ids"]) == sorted([checking, savings, cash])

    def test_update_journal_without_bank_accounts_keeps_them(self, db, bank_accounts):
        checking, _, _ = bank_accounts
        journal_id = create_journal(name="Personal", bank_account_ids=[checking])["journal_id"]

        update_journal(journal_id, name="Home")

        [listed] = list_journals()
        assert sorted(listed["bank_account_ids"]) == sorted([checking, f"cash:cash:{journal_id}"])

    @pytest.mark.parametrize("keep", [["checking"], []])
    def test_update_journal_keeps_the_cash_account(self, db, bank_accounts, keep):
        checking, savings, _ = bank_accounts
        journal_id = create_journal(name="Personal", bank_account_ids=[checking, savings])[
            "journal_id"
        ]
        ids = [checking] if keep else []

        update_journal(journal_id, bank_account_ids=ids)

        [listed] = list_journals()
        assert sorted(listed["bank_account_ids"]) == sorted(ids + [f"cash:cash:{journal_id}"])

    def test_update_journal_replaces_bank_accounts(self, db, bank_accounts):
        checking, savings, card = bank_accounts
        journal_id = create_journal(name="Personal", bank_account_ids=[checking, savings])[
            "journal_id"
        ]

        update_journal(journal_id, bank_account_ids=[card])

        [listed] = list_journals()
        assert sorted(listed["bank_account_ids"]) == sorted([card, f"cash:cash:{journal_id}"])

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
                raw_transaction_id=txn_id,
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

        assert result["booking"] == {"booked": 1, "transfers_paired": 0}
        assert self._booked_txns(db, result["journal_id"]) == {"on-checking"}

    def test_update_journal_books_an_added_account(self, db, bank_accounts):
        checking, savings, _ = bank_accounts
        self._add_purchase(db, "on-checking", checking)
        self._add_purchase(db, "on-savings", savings)
        journal_id = create_journal(name="Personal", bank_account_ids=[checking])["journal_id"]

        result = update_journal(journal_id, bank_account_ids=[checking, savings])

        assert result["booking"] == {"booked": 1, "transfers_paired": 0}
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
        assert result["bank_account_ids"] == [savings, f"cash:cash:{journal_id}"]


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

    def test_rounds_floats_to_cents(self):
        ctx = _make_ctx(AcceptedElicitation(data=ShareQueryRowsConsent()))
        result = _analyze("SELECT 0.1 + 0.2 AS x, 3 AS n, 'a' AS s", ctx)
        assert result["rows"] == [{"x": 0.3, "n": 3, "s": "a"}]

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


class TestAnalyzeFilters:
    """journal_id, account_id and dates are checked before any AI call."""

    @pytest.fixture
    def db(self):
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        create_schema(connection)
        with patch("balanceai_backend.servers.bookkeeping_server.conn", connection):
            yield connection
        connection.close()

    @pytest.fixture
    def journal_id(self, db):
        upsert_bank_account(
            BankAccount(
                id="test_bank:checking:0000",
                institution_name="Test Bank",
                account_type=BankAccountType.CHECKING,
                last4="0000",
            ),
            conn=db,
        )
        upsert_bank_account(
            BankAccount(
                id="test_bank:savings:1111",
                institution_name="Test Bank",
                account_type=BankAccountType.SAVINGS,
                last4="1111",
            ),
            conn=db,
        )
        return create_journal(name="Personal", bank_account_ids=["test_bank:checking:0000"])[
            "journal_id"
        ]

    def _run(self, **kwargs):
        ctx = _make_ctx(AcceptedElicitation(data=ShareQueryRowsConsent()))
        query = FinancialQuery(sql="SELECT 42 AS total", description="d", rejection=None)
        with patch(_PARSE, return_value=query) as parse:
            asyncio.run(analyze_financial_question(ctx, "How much did I spend?", **kwargs))
        return parse

    def test_passes_journal_and_account_to_the_ai(self, journal_id):
        parse = self._run(journal_id=journal_id, account_id="test_bank:checking:0000")
        content = parse.call_args.kwargs["content"]
        assert f"Journal ID filter: {journal_id}" in content
        assert "Bank account ID filter: test_bank:checking:0000" in content

    @pytest.mark.parametrize(
        ("kwargs", "message"),
        [
            ({"journal_id": "nope"}, "No journal with id nope"),
            ({"account_id": "nope"}, "No bank account with id nope"),
            ({"account_id": "test_bank:savings:1111", "journal_id": None}, "isn't in journal"),
            (
                {"start_date": datetime.date(2025, 11, 1), "end_date": datetime.date(2025, 10, 1)},
                "is after the end date",
            ),
        ],
    )
    def test_rejects_bad_filters_before_the_ai_call(self, journal_id, kwargs, message):
        if "journal_id" in kwargs and kwargs["journal_id"] is None:
            kwargs["journal_id"] = journal_id  # an account outside this journal
        with patch(_PARSE) as parse, pytest.raises(ValueError, match=message):
            asyncio.run(
                analyze_financial_question(
                    _make_ctx(AcceptedElicitation(data=ShareQueryRowsConsent())), "q", **kwargs
                )
            )
        parse.assert_not_called()


class TestHideDescriptionsInAnalyze:
    @pytest.fixture(autouse=True)
    def journal(self, tmp_path):
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

    def test_analyze_returns_rows_with_descriptions_hidden(self):
        ctx = _make_ctx(AcceptedElicitation(data=ShareQueryRowsConsent()))
        result = _analyze("SELECT description, counterparty FROM journal_lines ORDER BY 2", ctx)
        assert result["rows"] == [
            {"description": "[hidden description]", "counterparty": "Blue Bottle Coffee"},
            {"description": "Shell", "counterparty": "Shell"},
        ]
