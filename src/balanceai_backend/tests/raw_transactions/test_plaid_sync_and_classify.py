"""The Plaid sync and the classifier together, end to end on an in-memory
database. Only Plaid's responses, the AI, and web search are faked.

Every call passes conn=db explicitly — see test_sync_raw_transactions_from_plaid.py
for why patching the default connection wouldn't work.
"""

import datetime
import json
import sqlite3
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import anthropic
import httpx
import pytest
from balanceai_backend.bank_link.plaid_item_db import save_plaid_item
from balanceai_backend.db.bank_account_db import upsert_bank_account
from balanceai_backend.db.connection import create_schema
from balanceai_backend.models.bank_account import BankAccount, BankAccountType
from balanceai_backend.models.journal import JournalAccount
from balanceai_backend.models.plaid_item import PlaidItem
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
from balanceai_backend.raw_transactions.sync_raw_transactions_from_plaid import (
    sync_raw_transactions_from_plaid,
)

CHECKING = "tartan_bank:checking:0000"
CARD = "tartan_bank:credit_card:1111"
_PLAID_ACCOUNT = {CHECKING: "plaid-checking", CARD: "plaid-card"}


@pytest.fixture
def db():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    create_schema(conn)
    yield conn
    conn.close()


@pytest.fixture(autouse=True)
def no_bank_account_sync():
    """Bank-account creation has its own tests; these use the accounts below."""
    with patch(
        "balanceai_backend.raw_transactions.sync_raw_transactions_from_plaid.sync_bank_accounts_from_plaid",
        return_value={"saved": [], "skipped": []},
    ):
        yield


@pytest.fixture
def linked_item(db):
    save_plaid_item(PlaidItem(item_id="item-1", access_token="access-sandbox-abc"), conn=db)
    for account_id, account_type in (
        (CHECKING, BankAccountType.CHECKING),
        (CARD, BankAccountType.CREDIT_CARD),
    ):
        upsert_bank_account(
            BankAccount(
                id=account_id,
                institution_name="Tartan Bank",
                account_type=account_type,
                last4=account_id[-4:],
                plaid_item_id="item-1",
                plaid_account_id=_PLAID_ACCOUNT[account_id],
            ),
            conn=db,
        )


def _answer_all(**call) -> _ClassifierAnswer:
    """A fake AI: every transaction is non-essential, with a category naming it."""
    return _ClassifierAnswer(
        classifications=[
            _ClassifiedTransaction(
                index=t["index"],
                counter_account=JournalAccount.NON_ESSENTIALS_EXPENSE,
                category=f"ai:{t['description'].lower()}",
                counterparty=t["description"],
            )
            for t in json.loads(call["content"])
        ]
    )


@pytest.fixture
def fake_ai():
    with patch.object(classify_module.anthropic_service, "parse", side_effect=_answer_all) as mock:
        yield mock


@pytest.fixture(autouse=True)
def fake_search():
    with patch.object(classify_module.tavily_service, "search", return_value=None) as mock:
        yield mock


@pytest.fixture(autouse=True)
def no_wait():
    with patch.object(classify_module.time, "sleep"):
        yield


def _plaid_txn(
    txn_id: str,
    name: str,
    amount: float = 10.0,  # Plaid's sign: positive = money out
    account: str = CARD,
    category: str | None = "GENERAL_MERCHANDISE",
    confidence: str | None = "HIGH",
    date: datetime.date = datetime.date(2026, 8, 19),
    pending: bool = False,
):
    txn = SimpleNamespace(
        transaction_id=txn_id,
        account_id=_PLAID_ACCOUNT[account],
        date=date,
        amount=amount,
        name=name,
        merchant_name=None,
        pending=pending,
        personal_finance_category=SimpleNamespace(
            primary=category, detailed=None, confidence_level=confidence
        ),
    )
    if category is None:
        del txn.personal_finance_category
    return txn


def _sync(db, added=(), modified=(), removed=()):
    client = MagicMock()
    client.transactions_sync.return_value = SimpleNamespace(
        added=list(added),
        modified=list(modified),
        removed=[SimpleNamespace(transaction_id=txn_id) for txn_id in removed],
        next_cursor="cursor",
        has_more=False,
    )
    with patch(
        "balanceai_backend.raw_transactions.sync_raw_transactions_from_plaid.get_client",
        return_value=client,
    ):
        sync_raw_transactions_from_plaid("item-1", conn=db)


def _sent(fake_ai) -> list[str]:
    """Descriptions the AI was asked about, across all calls."""
    return sorted(
        t["description"]
        for call in fake_ai.call_args_list
        for t in json.loads(call.kwargs["content"])
    )


def _classification(db, txn_id: str) -> Classification | None:
    return find_raw_transactions(id=txn_id, conn=db)[0].classification


def _set(db, txn_id: str, category: str, classified_by: ClassifiedBy) -> None:
    update_raw_transaction_classification(
        txn_id,
        Classification(
            counter_account=JournalAccount.NON_ESSENTIALS_EXPENSE,
            category=category,
            counterparty="Uber",
            classified_by=classified_by,
        ),
        conn=db,
    )


_DONE = {"unclassified": 0, "errors": []}


def test_1_first_sync_asks_once_per_kind_of_transaction(db, linked_item, fake_ai):
    _sync(
        db,
        added=[_plaid_txn(f"uber{i}", "Uber", category="TRANSPORTATION") for i in range(6)]
        + [_plaid_txn("kfc", "KFC", account=CHECKING, category="FOOD_AND_DRINK")]
        + [
            _plaid_txn(
                f"zelle{i}", "Zelle to Sam", amount=500, account=CHECKING, category="TRANSFER_OUT"
            )
            for i in range(2)
        ],
    )

    result = classify_raw_transactions(conn=db)

    assert fake_ai.call_count == 1
    assert _sent(fake_ai) == ["KFC", "Uber", "Zelle to Sam", "Zelle to Sam"]
    assert result == {"classified": 9, **_DONE}


def test_2_a_later_sync_copies_instead_of_asking(db, linked_item, fake_ai):
    _sync(db, added=[_plaid_txn(f"uber{i}", "Uber") for i in range(6)])
    classify_raw_transactions(conn=db)
    fake_ai.reset_mock()

    _sync(db, added=[_plaid_txn("uber6", "Uber")])
    result = classify_raw_transactions(conn=db)

    fake_ai.assert_not_called()
    assert result == {"classified": 1, **_DONE}
    assert _classification(db, "uber6").category == "ai:uber"


def test_3_plaid_changing_an_ai_classified_amount_asks_again(db, linked_item, fake_ai):
    _sync(db, added=[_plaid_txn("kfc", "KFC", amount=12.40)])
    classify_raw_transactions(conn=db)
    fake_ai.reset_mock()

    _sync(db, modified=[_plaid_txn("kfc", "KFC", amount=14.90)])
    assert _classification(db, "kfc") is None
    result = classify_raw_transactions(conn=db)

    assert _sent(fake_ai) == ["KFC"]
    assert result == {"classified": 1, **_DONE}


def test_4_plaid_changing_a_user_classified_amount_keeps_it_and_flags_it(db, linked_item, fake_ai):
    _sync(db, added=[_plaid_txn("kfc", "KFC", amount=12.40)])
    _set(db, "kfc", "my pick", ClassifiedBy.USER)

    _sync(db, modified=[_plaid_txn("kfc", "KFC", amount=14.90)])
    result = classify_raw_transactions(conn=db)

    fake_ai.assert_not_called()
    assert result == {"classified": 0, **_DONE}
    kept = _classification(db, "kfc")
    assert (kept.category, kept.classified_by, kept.needs_user_review) == (
        "my pick",
        ClassifiedBy.USER,
        True,
    )


def test_5_pending_waits_until_it_posts(db, linked_item, fake_ai):
    _sync(db, added=[_plaid_txn("pending-1", "Blue Bottle", pending=True)])
    result = classify_raw_transactions(conn=db)

    fake_ai.assert_not_called()
    assert result == {"classified": 0, **_DONE}

    # Plaid posts it as a new transaction and removes the pending one.
    _sync(db, added=[_plaid_txn("posted-1", "Blue Bottle")], removed=["pending-1"])
    result = classify_raw_transactions(conn=db)

    assert _sent(fake_ai) == ["Blue Bottle"]
    assert result == {"classified": 1, **_DONE}
    assert [t.id for t in find_raw_transactions(conn=db)] == ["posted-1"]


def test_6_after_a_failed_batch_only_whats_left_is_asked(db, linked_item, fake_ai):
    _sync(db, added=[_plaid_txn(f"t{i:02}", f"Merchant {i:02}") for i in range(25)])

    def big_batch_fails(**call):
        if len(json.loads(call["content"])) == 20:
            raise anthropic.BadRequestError(
                "status 400",
                response=httpx.Response(400, request=httpx.Request("POST", "https://x")),
                body=None,
            )
        return _answer_all(**call)

    fake_ai.side_effect = big_batch_fails
    first = classify_raw_transactions(conn=db)
    assert (first["classified"], first["unclassified"]) == (5, 20)

    fake_ai.reset_mock()
    fake_ai.side_effect = _answer_all
    second = classify_raw_transactions(conn=db)

    assert len(_sent(fake_ai)) == 20
    assert second == {"classified": 20, **_DONE}


def test_7_a_new_transaction_copies_the_users_classification_as_ai(db, linked_item, fake_ai):
    _sync(db, added=[_plaid_txn("uber0", "Uber")])
    _set(db, "uber0", "commute", ClassifiedBy.USER)

    _sync(db, added=[_plaid_txn("uber1", "Uber")])
    classify_raw_transactions(conn=db)

    fake_ai.assert_not_called()
    copied = _classification(db, "uber1")
    assert (copied.category, copied.classified_by) == ("commute", ClassifiedBy.AI)


def test_8_transfers_are_asked_about_every_time(db, linked_item, fake_ai):
    zelle = {"name": "Zelle to Sam", "amount": 500, "account": CHECKING, "category": "TRANSFER_OUT"}
    _sync(db, added=[_plaid_txn("zelle0", **zelle)])
    classify_raw_transactions(conn=db)
    fake_ai.reset_mock()

    _sync(db, added=[_plaid_txn("zelle1", **zelle)])
    classify_raw_transactions(conn=db)

    assert _sent(fake_ai) == ["Zelle to Sam"]


def test_9_a_date_change_keeps_the_ais_classification(db, linked_item, fake_ai):
    _sync(db, added=[_plaid_txn("kfc", "KFC")])
    classify_raw_transactions(conn=db)
    fake_ai.reset_mock()

    _sync(db, modified=[_plaid_txn("kfc", "KFC", date=datetime.date(2026, 8, 20))])
    result = classify_raw_transactions(conn=db)

    fake_ai.assert_not_called()
    assert result == {"classified": 0, **_DONE}
    assert _classification(db, "kfc").category == "ai:kfc"


def test_10_a_removed_transaction_is_gone_and_not_counted(db, linked_item, fake_ai):
    _sync(db, added=[_plaid_txn("kfc", "KFC")])
    classify_raw_transactions(conn=db)

    _sync(db, removed=["kfc"])
    result = classify_raw_transactions(conn=db)

    assert find_raw_transactions(conn=db) == []
    assert result == {"classified": 0, **_DONE}


def test_11_a_purchase_and_its_refund_are_asked_about_separately(db, linked_item, fake_ai):
    _sync(
        db,
        added=[
            _plaid_txn("buy", "Amazon.com", amount=15.0),
            _plaid_txn("refund", "Amazon.com", amount=-15.0),
        ],
    )

    classify_raw_transactions(conn=db)

    assert _sent(fake_ai) == ["Amazon.com", "Amazon.com"]


def test_12_an_unsure_merchant_is_searched_once_then_reused(db, linked_item, fake_ai, fake_search):
    fake_search.return_value = "Rudy's is a barbershop chain."
    _sync(db, added=[_plaid_txn("rudys0", "Rudy's", category=None)])
    classify_raw_transactions(conn=db)
    fake_ai.reset_mock()

    _sync(db, added=[_plaid_txn("rudys1", "Rudy's", category=None)])
    classify_raw_transactions(conn=db)

    assert fake_search.call_count == 1
    fake_ai.assert_not_called()
    assert _classification(db, "rudys1").category == "ai:rudy's"


OTHER_BANK_CHECKING = "first_gingham:checking:2222"


def _link_other_bank(db) -> None:
    save_plaid_item(PlaidItem(item_id="item-2", access_token="access-sandbox-xyz"), conn=db)
    upsert_bank_account(
        BankAccount(
            id=OTHER_BANK_CHECKING,
            institution_name="First Gingham",
            account_type=BankAccountType.CHECKING,
            last4="2222",
            plaid_item_id="item-2",
        ),
        conn=db,
    )


def _other_bank_txn(txn_id: str, description: str) -> RawTransaction:
    return RawTransaction(
        id=txn_id,
        source="plaid",
        plaid_item_id="item-2",
        account_id=OTHER_BANK_CHECKING,
        posting_date=datetime.date(2026, 8, 19),
        description=description,
        amount=-30,
    )


def test_13_only_the_synced_banks_transactions_are_classified(db, linked_item, fake_ai):
    _link_other_bank(db)
    upsert_raw_transaction(_other_bank_txn("safeway", "Safeway"), conn=db)

    _sync(db, added=[_plaid_txn("kfc", "KFC", account=CHECKING)])
    result = classify_raw_transactions("item-1", conn=db)

    assert _sent(fake_ai) == ["KFC"]
    assert result == {"classified": 1, **_DONE}
    assert _classification(db, "safeway") is None


@pytest.mark.parametrize(
    "earlier_by, later_by, expected",
    [
        (ClassifiedBy.AI, ClassifiedBy.AI, "later"),  # 14: both by the AI
        (ClassifiedBy.USER, ClassifiedBy.USER, "later"),  # 15: both by the user
        (ClassifiedBy.USER, ClassifiedBy.AI, "earlier"),  # 16: the user's wins, even if older
    ],
    ids=["14-both-ai", "15-both-user", "16-user-over-ai"],
)
def test_14_to_16_which_classification_a_new_match_copies(
    db, linked_item, fake_ai, earlier_by, later_by, expected
):
    _sync(
        db,
        added=[
            _plaid_txn("earlier", "Uber", date=datetime.date(2026, 8, 1)),
            _plaid_txn("later", "Uber", date=datetime.date(2026, 8, 5)),
        ],
    )
    _set(db, "earlier", "earlier", earlier_by)
    _set(db, "later", "later", later_by)

    _sync(db, added=[_plaid_txn("new", "Uber", date=datetime.date(2026, 8, 9))])
    classify_raw_transactions(conn=db)

    fake_ai.assert_not_called()
    assert _classification(db, "new").category == expected


def test_17_reuse_crosses_banks(db, linked_item, fake_ai):
    _sync(db, added=[_plaid_txn("uber-tartan", "Uber", account=CHECKING)])
    classify_raw_transactions("item-1", conn=db)
    fake_ai.reset_mock()
    _link_other_bank(db)
    upsert_raw_transaction(_other_bank_txn("uber-gingham", "Uber"), conn=db)

    result = classify_raw_transactions("item-2", conn=db)

    fake_ai.assert_not_called()
    assert result == {"classified": 1, **_DONE}
    assert _classification(db, "uber-gingham").category == "ai:uber"
