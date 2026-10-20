"""Tests for classify_raw_transactions, with the AI call mocked."""

import datetime
import json
import sqlite3
import threading
from decimal import Decimal
from unittest.mock import patch

import anthropic
import httpx
import pytest
from balanceai_backend.db.bank_account_db import upsert_bank_account
from balanceai_backend.db.connection import create_schema
from balanceai_backend.models.bank_account import BankAccount, BankAccountType
from balanceai_backend.models.journal import JournalAccount
from balanceai_backend.models.raw_transaction import Classification, ClassifiedBy, RawTransaction
from balanceai_backend.raw_transactions import classify_raw_transactions as classify_module
from balanceai_backend.raw_transactions.classify_raw_transactions import (
    _ClassifiedTransaction,
    _ClassifierAnswer,
    classify_raw_transactions,
)
from balanceai_backend.raw_transactions.raw_transaction_db import (
    find_raw_transactions,
    update_raw_transaction_classification,
    upsert_raw_transaction,
)

CHECKING = "test_bank:checking:0000"
CARD = "test_bank:credit_card:1111"


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    create_schema(conn)
    for account_id, account_type in (
        (CHECKING, BankAccountType.CHECKING),
        (CARD, BankAccountType.CREDIT_CARD),
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


def _txn(txn_id: str, account_id: str = CHECKING, **fields) -> RawTransaction:
    return RawTransaction(
        **{
            "id": txn_id,
            "source": "plaid",
            "account_id": account_id,
            "posting_date": datetime.date(2026, 8, 19),
            "description": f"Merchant {txn_id}",
            "amount": Decimal("-10.00"),
            **fields,
        }
    )


def _answer_all(**call) -> _ClassifierAnswer:
    """A fake AI that classifies every transaction it's sent as dining."""
    return _ClassifierAnswer(
        classifications=[
            _ClassifiedTransaction(
                index=t["index"],
                counter_account=JournalAccount.NON_ESSENTIALS_EXPENSE,
                category="dining",
                counterparty=t["description"],
            )
            for t in json.loads(call["content"])
        ]
    )


@pytest.fixture(autouse=True)
def fake_search():
    """No real web searches in tests; by default a search finds nothing."""
    with patch.object(classify_module.tavily_service, "search", return_value=None) as mock:
        yield mock


@pytest.fixture
def fake_ai():
    with patch.object(classify_module.anthropic_service, "parse", side_effect=_answer_all) as mock:
        yield mock


def _sent(fake_ai, call: int = 0) -> list[dict]:
    return json.loads(fake_ai.call_args_list[call].kwargs["content"])


class TestClassifyRawTransactions:
    def test_saves_the_ais_classification(self, db, fake_ai):
        upsert_raw_transaction(_txn("t1"), conn=db)

        result = classify_raw_transactions(conn=db)

        assert result == {"classified": 1, "unclassified": 0, "errors": []}
        [txn] = find_raw_transactions(conn=db)
        assert txn.classification == Classification(
            counter_account=JournalAccount.NON_ESSENTIALS_EXPENSE,
            category="dining",
            counterparty="Merchant t1",
            classified_by=ClassifiedBy.AI,
        )

    def test_skips_pending_transactions(self, db, fake_ai):
        upsert_raw_transaction(_txn("posted"), conn=db)
        upsert_raw_transaction(_txn("pending", pending=True), conn=db)

        result = classify_raw_transactions(conn=db)

        assert [t["description"] for t in _sent(fake_ai)] == ["Merchant posted"]
        assert result == {"classified": 1, "unclassified": 0, "errors": []}
        pending = find_raw_transactions(id="pending", conn=db)[0]
        assert pending.classification is None

    def test_skips_already_classified_transactions(self, db, fake_ai):
        upsert_raw_transaction(_txn("t1"), conn=db)
        upsert_raw_transaction(_txn("t2"), conn=db)
        mine = Classification(
            counter_account=JournalAccount.ESSENTIALS_EXPENSE, classified_by=ClassifiedBy.USER
        )
        update_raw_transaction_classification("t1", mine, conn=db)

        classify_raw_transactions(conn=db)

        assert [t["description"] for t in _sent(fake_ai)] == ["Merchant t2"]
        assert find_raw_transactions(id="t1", conn=db)[0].classification == mine

    def test_sends_batches_of_twenty(self, db, fake_ai):
        for i in range(45):
            upsert_raw_transaction(_txn(f"t{i:02}"), conn=db)

        result = classify_raw_transactions(conn=db)

        batches = [_sent(fake_ai, call) for call in range(fake_ai.call_count)]
        assert sorted(len(b) for b in batches) == [5, 20, 20]
        for batch in batches:
            assert [t["index"] for t in batch] == list(range(len(batch)))
        assert result == {"classified": 45, "unclassified": 0, "errors": []}

    def test_what_the_ai_sees(self, db, fake_ai):
        upsert_raw_transaction(
            _txn("t1", description="Rudy's", posting_date=datetime.date(2026, 8, 18)), conn=db
        )
        upsert_raw_transaction(
            _txn(
                "t2",
                account_id=CARD,
                plaid_item_id=None,
                plaid_account_id="plaid-secret-id",
                description="Uber",
                amount=Decimal("-6.33"),
                category="TRANSPORTATION",
                category_detailed="TRANSPORTATION_TAXIS_AND_RIDE_SHARES",
                category_confidence="VERY_HIGH",
            ),
            conn=db,
        )

        classify_raw_transactions(conn=db)

        assert _sent(fake_ai) == [
            {
                "index": 0,
                "date": "2026-08-18",
                "description": "Rudy's",
                "amount": "-10.00",
                "bank_account_type": "checking",
            },
            {
                "index": 1,
                "date": "2026-08-19",
                "description": "Uber",
                "amount": "-6.33",
                "bank_account_type": "credit_card",
                "plaid_category": "TRANSPORTATION",
                "plaid_category_detailed": "TRANSPORTATION_TAXIS_AND_RIDE_SHARES",
                "plaid_confidence": "VERY_HIGH",
            },
        ]

    def test_calls_haiku_at_temperature_zero(self, db, fake_ai):
        upsert_raw_transaction(_txn("t1"), conn=db)

        classify_raw_transactions(conn=db)

        call = fake_ai.call_args.kwargs
        assert call["model_id"] == "claude-haiku-4-5"
        assert call["temperature"] == 0.0
        assert call["output_format"] is _ClassifierAnswer

    def test_skipped_index_stays_unclassified(self, db, fake_ai):
        upsert_raw_transaction(_txn("t1"), conn=db)
        upsert_raw_transaction(_txn("t2"), conn=db)
        fake_ai.side_effect = lambda **call: _ClassifierAnswer(
            classifications=_answer_all(**call).classifications[:1]
        )

        result = classify_raw_transactions(conn=db)

        assert result == {
            "classified": 1,
            "unclassified": 1,
            "errors": [{"reason": "The AI skipped some transactions.", "transactions": 1}],
        }

    def test_invented_index_is_ignored(self, db, fake_ai):
        upsert_raw_transaction(_txn("t1"), conn=db)
        invented = _ClassifiedTransaction(
            index=7,
            counter_account=JournalAccount.SALARY_INCOME,
            category="income",
            counterparty="Nobody",
        )
        fake_ai.side_effect = lambda **call: _ClassifierAnswer(
            classifications=[*_answer_all(**call).classifications, invented]
        )

        result = classify_raw_transactions(conn=db)

        assert result == {"classified": 1, "unclassified": 0, "errors": []}
        [txn] = find_raw_transactions(conn=db)
        assert txn.classification.counterparty == "Merchant t1"

    def test_declined_batch_saves_nothing(self, db, fake_ai):
        upsert_raw_transaction(_txn("t1"), conn=db)
        fake_ai.side_effect = None
        fake_ai.return_value = None

        result = classify_raw_transactions(conn=db)

        assert result["classified"] == 0
        assert result["unclassified"] == 1
        assert result["errors"] == [
            {
                "reason": "Classifying a batch failed: The AI declined to classify this batch.",
                "transactions": 1,
            }
        ]

    def test_nothing_to_classify_makes_no_calls(self, db, fake_ai):
        assert classify_raw_transactions(conn=db) == {
            "classified": 0,
            "unclassified": 0,
            "errors": [],
        }
        fake_ai.assert_not_called()


_REQUEST = httpx.Request("POST", "https://api.anthropic.com/v1/messages")


def _status_error(cls, status: int):
    return cls(f"status {status}", response=httpx.Response(status, request=_REQUEST), body=None)


def _rate_limit():
    return _status_error(anthropic.RateLimitError, 429)


def _attempts(*failures: Exception):
    """A fake AI that raises each of failures in turn, then answers normally."""
    remaining = list(failures)

    def side_effect(**call):
        if remaining:
            raise remaining.pop(0)
        return _answer_all(**call)

    return side_effect


@pytest.fixture
def no_wait():
    with patch.object(classify_module.time, "sleep") as sleep:
        yield sleep


class TestRetries:
    def test_rate_limit_is_retried(self, db, fake_ai, no_wait):
        upsert_raw_transaction(_txn("t1"), conn=db)
        fake_ai.side_effect = _attempts(_rate_limit())

        result = classify_raw_transactions(conn=db)

        assert fake_ai.call_count == 2
        assert result == {"classified": 1, "unclassified": 0, "errors": []}

    @pytest.mark.parametrize(
        "error",
        [
            _status_error(anthropic.InternalServerError, 500),
            anthropic.APIConnectionError(request=_REQUEST),
            anthropic.APITimeoutError(request=_REQUEST),
        ],
    )
    def test_server_and_network_errors_are_retried(self, db, fake_ai, no_wait, error):
        upsert_raw_transaction(_txn("t1"), conn=db)
        fake_ai.side_effect = _attempts(error)

        assert classify_raw_transactions(conn=db)["classified"] == 1
        assert fake_ai.call_count == 2

    def test_bad_request_is_not_retried(self, db, fake_ai, no_wait):
        upsert_raw_transaction(_txn("t1"), conn=db)
        fake_ai.side_effect = _status_error(anthropic.BadRequestError, 400)

        result = classify_raw_transactions(conn=db)

        assert fake_ai.call_count == 1
        assert result["unclassified"] == 1
        assert result["errors"] == [
            {"reason": "Classifying a batch failed: status 400", "transactions": 1}
        ]

    def test_gives_up_after_ten_attempts_and_carries_on(self, db, fake_ai, no_wait):
        for i in range(25):  # two batches: 20 + 5
            upsert_raw_transaction(_txn(f"t{i:02}"), conn=db)

        def side_effect(**call):
            if len(json.loads(call["content"])) == 20:  # the big batch fails every attempt
                raise _rate_limit()
            return _answer_all(**call)

        fake_ai.side_effect = side_effect

        result = classify_raw_transactions(conn=db)

        assert fake_ai.call_count == 11
        assert result["classified"] == 5
        assert result["unclassified"] == 20
        assert result["errors"] == [
            {
                "reason": "Classifying a batch failed: Gave up after 10 attempts: status 429",
                "transactions": 20,
            }
        ]

    def test_waits_grow_and_stop_at_thirty_seconds(self, db, fake_ai, no_wait):
        upsert_raw_transaction(_txn("t1"), conn=db)
        fake_ai.side_effect = _rate_limit()

        classify_raw_transactions(conn=db)

        waits = [c.args[0] for c in no_wait.call_args_list]
        assert len(waits) == 9  # between ten attempts
        for wait, base in zip(waits, [2, 4, 8, 16, 30, 30, 30, 30, 30], strict=True):
            assert base <= wait <= base + 1

    @pytest.mark.parametrize(
        "error",
        [
            _status_error(anthropic.AuthenticationError, 401),
            _status_error(anthropic.PermissionDeniedError, 403),
        ],
    )
    def test_rejected_credentials_stop_the_run(self, db, fake_ai, no_wait, error):
        for i in range(100):  # five batches, at most four under way at once
            upsert_raw_transaction(_txn(f"t{i:02}"), conn=db)
        fake_ai.side_effect = error

        result = classify_raw_transactions(conn=db)

        assert 1 <= fake_ai.call_count <= 4  # the fifth batch never calls the AI
        assert result["classified"] == 0
        assert result["errors"] == [
            {
                "reason": f"The AI provider rejected our credentials: {error}",
                "transactions": 100,
            }
        ]

    def test_same_reason_from_two_batches_is_counted_together(self, db, fake_ai, no_wait):
        for i in range(40):  # two batches of 20
            upsert_raw_transaction(_txn(f"t{i:02}"), conn=db)
        fake_ai.side_effect = _status_error(anthropic.BadRequestError, 400)

        result = classify_raw_transactions(conn=db)

        assert result["errors"] == [
            {"reason": "Classifying a batch failed: status 400", "transactions": 40}
        ]


class TestParallelCalls:
    def test_four_calls_run_at_once(self, db, fake_ai):
        for i in range(80):  # four batches of 20
            upsert_raw_transaction(_txn(f"t{i:02}"), conn=db)
        all_four_arrived = threading.Barrier(4, timeout=5)

        def side_effect(**call):
            all_four_arrived.wait()  # raises BrokenBarrierError unless 4 calls overlap
            return _answer_all(**call)

        fake_ai.side_effect = side_effect

        result = classify_raw_transactions(conn=db)

        assert result == {"classified": 80, "unclassified": 0, "errors": []}

    def test_results_are_saved_on_the_calling_thread(self, db, fake_ai):
        for i in range(40):
            upsert_raw_transaction(_txn(f"t{i:02}"), conn=db)
        saving_threads = set()
        real_update = classify_module.update_raw_transaction_classification

        def recording_update(*args, **kwargs):
            saving_threads.add(threading.get_ident())
            return real_update(*args, **kwargs)

        with patch.object(
            classify_module, "update_raw_transaction_classification", recording_update
        ):
            classify_raw_transactions(conn=db)

        assert saving_threads == {threading.get_ident()}


def _classify(txn_id: str, classified_by: ClassifiedBy, db, **fields) -> Classification:
    classification = Classification(
        counter_account=JournalAccount.ESSENTIALS_EXPENSE,
        category=fields.pop("category", "groceries"),
        counterparty=fields.pop("counterparty", "Known"),
        classified_by=classified_by,
    )
    update_raw_transaction_classification(txn_id, classification, conn=db)
    return classification


class TestReuse:
    def test_copies_an_existing_classification_without_asking(self, db, fake_ai):
        upsert_raw_transaction(_txn("old", description="Uber"), conn=db)
        _classify("old", ClassifiedBy.AI, db, category="rideshare", counterparty="Uber")
        upsert_raw_transaction(_txn("new", description="Uber"), conn=db)

        result = classify_raw_transactions(conn=db)

        fake_ai.assert_not_called()
        assert result == {"classified": 1, "unclassified": 0, "errors": []}
        new = find_raw_transactions(id="new", conn=db)[0].classification
        assert (new.category, new.counterparty, new.classified_by) == (
            "rideshare",
            "Uber",
            ClassifiedBy.AI,
        )

    def test_users_classification_wins_over_the_ais(self, db, fake_ai):
        for txn_id in ("by_ai", "by_user", "new"):
            upsert_raw_transaction(_txn(txn_id, description="Uber"), conn=db)
        _classify("by_ai", ClassifiedBy.AI, db, category="ai's pick")
        _classify("by_user", ClassifiedBy.USER, db, category="user's pick")

        classify_raw_transactions(conn=db)

        new = find_raw_transactions(id="new", conn=db)[0].classification
        assert new.category == "user's pick"
        assert new.classified_by == ClassifiedBy.AI

    def test_matching_unclassified_transactions_are_sent_once(self, db, fake_ai):
        for i in range(6):
            upsert_raw_transaction(_txn(f"uber{i}", description="Uber"), conn=db)
        upsert_raw_transaction(_txn("kfc", description="KFC"), conn=db)

        result = classify_raw_transactions(conn=db)

        assert sorted(t["description"] for t in _sent(fake_ai)) == ["KFC", "Uber"]
        assert result == {"classified": 7, "unclassified": 0, "errors": []}
        assert {t.classification.counterparty for t in find_raw_transactions(conn=db)} == {
            "Uber",
            "KFC",
        }

    @pytest.mark.parametrize(
        "other",
        [
            {"amount": Decimal("10.00")},  # a refund, not a purchase
            {"account_id": CARD},  # same merchant, different kind of account
            {"description": "STARBUCKS #456"},  # numbers are kept
        ],
    )
    def test_different_transactions_are_not_grouped(self, db, fake_ai, other):
        upsert_raw_transaction(_txn("a", description="STARBUCKS #123"), conn=db)
        upsert_raw_transaction(_txn("b", **{"description": "STARBUCKS #123", **other}), conn=db)

        classify_raw_transactions(conn=db)

        assert len(_sent(fake_ai)) == 2

    def test_case_and_spacing_still_match(self, db, fake_ai):
        upsert_raw_transaction(_txn("a", description="Trader Joe's"), conn=db)
        upsert_raw_transaction(_txn("b", description="  TRADER   joe's "), conn=db)

        classify_raw_transactions(conn=db)

        assert len(_sent(fake_ai)) == 1

    @pytest.mark.parametrize("category", ["TRANSFER_IN", "TRANSFER_OUT", "LOAN_PAYMENTS", "INCOME"])
    def test_transfers_loans_and_income_never_share(self, db, fake_ai, category):
        upsert_raw_transaction(_txn("old", description="Zelle to Sam", category=category), conn=db)
        _classify("old", ClassifiedBy.USER, db)
        upsert_raw_transaction(_txn("a", description="Zelle to Sam", category=category), conn=db)
        upsert_raw_transaction(_txn("b", description="Zelle to Sam", category=category), conn=db)

        classify_raw_transactions(conn=db)

        assert len(_sent(fake_ai)) == 2

    def test_a_failed_batch_counts_every_transaction_in_its_groups(self, db, fake_ai, no_wait):
        for i in range(3):
            upsert_raw_transaction(_txn(f"uber{i}", description="Uber"), conn=db)
        fake_ai.side_effect = _status_error(anthropic.BadRequestError, 400)

        result = classify_raw_transactions(conn=db)

        assert result["errors"] == [
            {"reason": "Classifying a batch failed: status 400", "transactions": 3}
        ]


class TestLogging:
    _LOGGER = "balanceai_backend.raw_transactions.classify_raw_transactions"

    def test_failed_batch_logs_its_transaction_ids(self, db, fake_ai, no_wait, caplog):
        upsert_raw_transaction(_txn("t1"), conn=db)
        upsert_raw_transaction(_txn("t2"), conn=db)
        fake_ai.side_effect = _status_error(anthropic.BadRequestError, 400)

        with caplog.at_level("ERROR", logger=self._LOGGER):
            classify_raw_transactions(conn=db)

        [record] = caplog.records
        assert "'t1'" in record.getMessage() and "'t2'" in record.getMessage()

    def test_rejected_credentials_log_the_transaction_ids(self, db, fake_ai, no_wait, caplog):
        upsert_raw_transaction(_txn("t1"), conn=db)
        fake_ai.side_effect = _status_error(anthropic.AuthenticationError, 401)

        with caplog.at_level("WARNING", logger=self._LOGGER):
            classify_raw_transactions(conn=db)

        assert any(
            "Not classified" in r.getMessage() and "'t1'" in r.getMessage() for r in caplog.records
        )

    def test_skipped_answers_log_the_skipped_ids(self, db, fake_ai, caplog):
        upsert_raw_transaction(_txn("t1", posting_date=datetime.date(2026, 8, 18)), conn=db)
        upsert_raw_transaction(_txn("t2"), conn=db)
        fake_ai.side_effect = lambda **call: _ClassifierAnswer(
            classifications=_answer_all(**call).classifications[:1]
        )

        with caplog.at_level("WARNING", logger=self._LOGGER):
            classify_raw_transactions(conn=db)

        [record] = caplog.records
        assert record.getMessage() == "The AI skipped transactions ['t2']"

    def test_conflicting_answers_log_both_and_keep_the_last(self, db, fake_ai, caplog):
        for i in range(3):
            upsert_raw_transaction(_txn(f"uber{i}", description="Uber"), conn=db)

        def conflicting(**call):
            first = _answer_all(**call).classifications[0]
            second = first.model_copy(update={"category": "commute"})
            return _ClassifierAnswer(classifications=[first, second])

        fake_ai.side_effect = conflicting

        with caplog.at_level("WARNING", logger=self._LOGGER):
            classify_raw_transactions(conn=db)

        [record] = caplog.records
        message = record.getMessage()
        assert "conflicting answers" in message
        assert all(f"'uber{i}'" in message for i in range(3))
        assert "'dining'" in message and "'commute'" in message
        assert {t.classification.category for t in find_raw_transactions(conn=db)} == {"commute"}

    def test_identical_duplicate_answers_log_nothing(self, db, fake_ai, caplog):
        upsert_raw_transaction(_txn("t1"), conn=db)

        def repeated(**call):
            only = _answer_all(**call).classifications[0]
            return _ClassifierAnswer(classifications=[only, only])

        fake_ai.side_effect = repeated

        with caplog.at_level("WARNING", logger=self._LOGGER):
            result = classify_raw_transactions(conn=db)

        assert caplog.records == []
        assert result["classified"] == 1


class TestWebSearch:
    @pytest.mark.parametrize(
        "plaid",
        [
            {"category": "GENERAL_MERCHANDISE", "category_confidence": "LOW"},
            {"category": "GENERAL_MERCHANDISE", "category_confidence": "UNKNOWN"},
            {},  # no Plaid category at all
        ],
    )
    def test_unsure_merchants_are_searched_and_the_ai_sees_the_result(
        self, db, fake_ai, fake_search, plaid
    ):
        upsert_raw_transaction(_txn("t1", description="Rudy's", **plaid), conn=db)
        fake_search.return_value = "Rudy's is a barbershop chain."

        classify_raw_transactions(conn=db)

        fake_search.assert_called_once_with("What type of business is: Rudy's")
        assert _sent(fake_ai)[0]["web_context"] == "Rudy's is a barbershop chain."

    @pytest.mark.parametrize("confidence", ["VERY_HIGH", "HIGH", "MEDIUM", None])
    def test_merchants_plaid_is_sure_of_are_not_searched(
        self, db, fake_ai, fake_search, confidence
    ):
        upsert_raw_transaction(
            _txn("t1", category="FOOD_AND_DRINK", category_confidence=confidence), conn=db
        )

        classify_raw_transactions(conn=db)

        fake_search.assert_not_called()
        assert "web_context" not in _sent(fake_ai)[0]

    def test_same_description_is_searched_once(self, db, fake_ai, fake_search):
        upsert_raw_transaction(_txn("checking", description="Rudy's"), conn=db)
        upsert_raw_transaction(_txn("card", description="RUDY'S", account_id=CARD), conn=db)
        fake_search.return_value = "A barbershop."

        classify_raw_transactions(conn=db)

        assert fake_search.call_count == 1
        assert [t["web_context"] for t in _sent(fake_ai)] == ["A barbershop.", "A barbershop."]

    def test_merchants_handled_by_reuse_are_not_searched(self, db, fake_ai, fake_search):
        upsert_raw_transaction(_txn("old", description="Rudy's"), conn=db)
        _classify("old", ClassifiedBy.USER, db)
        upsert_raw_transaction(_txn("new", description="Rudy's"), conn=db)

        classify_raw_transactions(conn=db)

        fake_search.assert_not_called()
        fake_ai.assert_not_called()

    def test_failed_search_still_classifies_and_logs_the_id(self, db, fake_ai, fake_search, caplog):
        upsert_raw_transaction(_txn("t1", description="Rudy's"), conn=db)
        fake_search.side_effect = RuntimeError("search is down")

        with caplog.at_level("WARNING", logger=TestLogging._LOGGER):
            result = classify_raw_transactions(conn=db)

        assert result == {"classified": 1, "unclassified": 0, "errors": []}
        assert "web_context" not in _sent(fake_ai)[0]
        assert any("transaction t1" in r.getMessage() for r in caplog.records)
        assert all("Rudy" not in r.getMessage() for r in caplog.records)

    def test_empty_result_adds_no_web_context(self, db, fake_ai, fake_search):
        upsert_raw_transaction(_txn("t1"), conn=db)
        fake_search.return_value = ""

        classify_raw_transactions(conn=db)

        assert "web_context" not in _sent(fake_ai)[0]
