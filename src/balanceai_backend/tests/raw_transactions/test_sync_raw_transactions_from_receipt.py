import datetime
import sqlite3
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import pytest
from balanceai_backend.db.bank_account_db import create_cash_account, upsert_bank_account
from balanceai_backend.db.connection import create_schema
from balanceai_backend.db.journal_db import save_journal
from balanceai_backend.models.bank_account import BankAccount, BankAccountType
from balanceai_backend.models.journal import Journal
from balanceai_backend.models.raw_transaction import RawTransaction
from balanceai_backend.models.receipt import (
    AccountMatch,
    PaymentMethod,
    ReceiptAccount,
    ReceiptExtraction,
    ReceiptKind,
)
from balanceai_backend.raw_transactions.raw_transaction_db import (
    find_raw_transactions,
    upsert_raw_transaction,
)
from balanceai_backend.raw_transactions.sync_raw_transactions_from_receipt import (
    check_receipt_account,
    normalize_last4,
    read_receipt,
    resolve_receipt_path,
    suggest_receipt_account,
    sync_raw_transactions_from_receipt,
)

CHECKING = "test_bank:checking:0000"
CARD = "test_bank:credit_card:5678"
OTHER_CHECKING = "other_bank:checking:9999"


@pytest.fixture
def db():
    """Personal holds checking (••0000) and a credit card (••5678); My LLC holds
    another checking (••9999). Each journal has its cash account."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    create_schema(conn)
    for account_id, account_type in (
        (CHECKING, BankAccountType.CHECKING),
        (CARD, BankAccountType.CREDIT_CARD),
        (OTHER_CHECKING, BankAccountType.CHECKING),
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
    save_journal(
        Journal(journal_id="j1", name="Personal", lines=[], bank_account_ids=[CHECKING, CARD]),
        conn=conn,
    )
    save_journal(
        Journal(journal_id="j2", name="My LLC", lines=[], bank_account_ids=[OTHER_CHECKING]),
        conn=conn,
    )
    create_cash_account("j1", "Personal", conn=conn)
    create_cash_account("j2", "My LLC", conn=conn)
    yield conn
    conn.close()


def _receipt(**overrides) -> ReceiptExtraction:
    fields = {
        "date": datetime.date(2026, 11, 8),
        "counterparty": "Blue Bottle Coffee",
        "kind": ReceiptKind.PURCHASE,
        "total": Decimal("12.50"),
        "payment_method": PaymentMethod.CARD,
        "card_last4": "1234",
    }
    return ReceiptExtraction(**(fields | overrides))


def _earlier_receipt(db, account_id, card="1234", id="earlier"):
    upsert_raw_transaction(
        RawTransaction(
            raw_transaction_id=id,
            source="receipt",
            account_id=account_id,
            posting_date=datetime.date(2026, 10, 1),
            description="Corner Store",
            amount=Decimal("-3.00"),
            card_last4=card,
        ),
        conn=db,
    )


class TestSuggestReceiptAccount:
    def test_cash_uses_the_journals_cash_account(self, db):
        receipt = _receipt(payment_method=PaymentMethod.CASH, card_last4=None)
        assert suggest_receipt_account(receipt, "j1", conn=db) == ReceiptAccount(
            "cash:cash:j1", AccountMatch.CASH
        )

    def test_cash_without_a_journal_asks(self, db):
        receipt = _receipt(payment_method=PaymentMethod.CASH, card_last4=None)
        with pytest.raises(ValueError, match="Paid in cash"):
            suggest_receipt_account(receipt, conn=db)

    def test_cash_in_a_journal_without_a_cash_account_raises(self, db):
        save_journal(Journal(journal_id="j3", name="Old", lines=[]), conn=db)
        receipt = _receipt(payment_method=PaymentMethod.CASH, card_last4=None)
        with pytest.raises(ValueError, match="has no cash account"):
            suggest_receipt_account(receipt, "j3", conn=db)

    def test_card_seen_on_an_earlier_receipt(self, db):
        _earlier_receipt(db, CHECKING)
        assert suggest_receipt_account(_receipt(), conn=db) == ReceiptAccount(
            CHECKING, AccountMatch.HISTORY
        )

    def test_card_matching_an_accounts_own_last4(self, db):
        assert suggest_receipt_account(_receipt(card_last4="5678"), conn=db) == ReceiptAccount(
            CARD, AccountMatch.LAST4
        )

    def test_earlier_receipts_win_over_an_accounts_last4(self, db):
        _earlier_receipt(db, CHECKING, card="5678")
        assert suggest_receipt_account(_receipt(card_last4="5678"), conn=db) == ReceiptAccount(
            CHECKING, AccountMatch.HISTORY
        )

    def test_card_seen_with_two_accounts_asks(self, db):
        _earlier_receipt(db, CHECKING, id="e1")
        _earlier_receipt(db, CARD, id="e2")
        with pytest.raises(ValueError, match="Couldn't tell which account"):
            suggest_receipt_account(_receipt(), conn=db)

    def test_unknown_card_asks(self, db):
        with pytest.raises(ValueError, match="Couldn't tell which account"):
            suggest_receipt_account(_receipt(card_last4="4321"), conn=db)

    def test_account_in_another_journal_asks(self, db):
        _earlier_receipt(db, OTHER_CHECKING)
        with pytest.raises(ValueError, match="Couldn't tell which account"):
            suggest_receipt_account(_receipt(), "j1", conn=db)

    def test_no_payment_info_asks(self, db):
        receipt = _receipt(payment_method=PaymentMethod.UNKNOWN, card_last4=None)
        with pytest.raises(ValueError, match="doesn't show how it was paid"):
            suggest_receipt_account(receipt, conn=db)

    def test_cash_placeholder_never_matches_a_card(self, db):
        """Card numbers are digits only, so no card can come out as the cash
        account's placeholder last 4."""
        assert normalize_last4("placeholder") is None


class TestCheckReceiptAccount:
    def test_passes_for_an_account_in_the_journal(self, db):
        check_receipt_account(CHECKING, "j1", conn=db)
        check_receipt_account(CHECKING, conn=db)

    def test_unknown_account(self, db):
        with pytest.raises(ValueError, match="No bank account"):
            check_receipt_account("nope", conn=db)

    def test_account_in_another_journal(self, db):
        with pytest.raises(ValueError, match="isn't in journal"):
            check_receipt_account(OTHER_CHECKING, "j1", conn=db)


class TestSyncRawTransactionsFromReceipt:
    def test_purchase_is_money_out(self, db):
        txn = sync_raw_transactions_from_receipt(
            _receipt(tax=Decimal("1.02"), tip=Decimal("2.00")), CHECKING, conn=db
        )
        [saved] = find_raw_transactions(raw_transaction_id=txn.raw_transaction_id, conn=db)
        assert len(saved.raw_transaction_id) == 32 and saved.plaid_transaction_id is None
        assert saved.source == "receipt"
        assert saved.amount == Decimal("-12.50")
        assert saved.description == "Blue Bottle Coffee"
        assert (saved.card_last4, saved.tax, saved.tip) == (
            "1234",
            Decimal("1.02"),
            Decimal("2.00"),
        )

    def test_refund_is_money_in(self, db):
        txn = sync_raw_transactions_from_receipt(_receipt(kind=ReceiptKind.REFUND), CARD, conn=db)
        assert txn.amount == Decimal("12.50")

    def test_saving_the_same_receipt_twice_adds_two_rows(self, db):
        """Ids are random, so duplicates aren't caught here (BL-15)."""
        sync_raw_transactions_from_receipt(_receipt(), CHECKING, conn=db)
        sync_raw_transactions_from_receipt(_receipt(), CHECKING, conn=db)
        assert len(find_raw_transactions(source="receipt", conn=db)) == 2

    def test_keeps_the_category_hint(self, db):
        txn = sync_raw_transactions_from_receipt(_receipt(category="dining"), CHECKING, conn=db)
        assert txn.category == "dining"


@pytest.mark.parametrize(
    ("printed", "expected"),
    [("•••• 1234 ", "1234"), ("XXXX-XXXX-XXXX-1234", "1234"), ("12", None), (None, None)],
)
def test_normalize_last4(printed, expected):
    assert normalize_last4(printed) == expected


class TestResolveReceiptPath:
    @pytest.fixture
    def receipts_dir(self, tmp_path):
        folder = tmp_path / "receipts"
        folder.mkdir()
        (folder / "coffee.jpg").write_bytes(b"fake image")
        (tmp_path / "secret.jpg").write_bytes(b"not a receipt")
        return folder

    def test_finds_a_file_in_the_folder(self, receipts_dir):
        assert (
            resolve_receipt_path("coffee.jpg", receipts_dir)
            == (receipts_dir / "coffee.jpg").resolve()
        )

    @pytest.mark.parametrize("name", ["../secret.jpg", "missing.jpg", "sub/coffee.jpg"])
    def test_rejects_names_outside_the_folder_or_missing(self, receipts_dir, name):
        with pytest.raises(ValueError, match="No receipt named"):
            resolve_receipt_path(name, receipts_dir)

    def test_rejects_an_absolute_path(self, receipts_dir, tmp_path):
        with pytest.raises(ValueError, match="No receipt named"):
            resolve_receipt_path(str(tmp_path / "secret.jpg"), receipts_dir)

    def test_rejects_a_symlink_out_of_the_folder(self, receipts_dir, tmp_path):
        (receipts_dir / "link.jpg").symlink_to(tmp_path / "secret.jpg")
        with pytest.raises(ValueError, match="No receipt named"):
            resolve_receipt_path("link.jpg", receipts_dir)


def test_read_receipt_hides_the_ai_error_text(tmp_path):
    """The AI's error can quote the receipt; it must not reach the assistant."""
    image = tmp_path / "receipt.jpg"
    image.write_bytes(b"fake image")
    with patch(
        "balanceai_backend.raw_transactions.sync_raw_transactions_from_receipt.OcrUtil"
    ) as ocr:
        ocr.executeWithAnthropic.side_effect = ValueError("Blue Bottle Coffee 12.50 ...")
        with pytest.raises(ValueError) as error:
            read_receipt(image)
    assert str(error.value) == "Couldn't read this receipt. Try a clearer photo."
    assert error.value.__cause__ is None and error.value.__suppress_context__


def test_read_receipt_sends_the_image_to_ocr(tmp_path):
    image = tmp_path / "receipt.jpg"
    image.write_bytes(b"fake image")
    with patch(
        "balanceai_backend.raw_transactions.sync_raw_transactions_from_receipt.OcrUtil"
    ) as ocr:
        ocr.executeWithAnthropic.return_value = _receipt()
        assert read_receipt(Path(image)) == _receipt()
    kwargs = ocr.executeWithAnthropic.call_args.kwargs
    assert kwargs["content"] == b"fake image"
    assert kwargs["output_format"] is ReceiptExtraction
    assert kwargs["mime_type"] == "image/jpeg"
