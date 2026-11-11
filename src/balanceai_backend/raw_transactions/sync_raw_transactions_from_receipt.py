"""
Receipts become raw transactions, booked by the same rules as Plaid
(docs/BACKEND_IMPLEMENTATION_DECISIONS.md #18). The tool reads the receipt,
finds or checks the paying account, asks the user to confirm, then saves it
here.
"""

import logging
import re
import sqlite3
from pathlib import Path

from balanceai_backend.db.bank_account_db import find_bank_accounts, find_cash_account_for_journal
from balanceai_backend.db.connection import conn as _default_conn
from balanceai_backend.db.journal_db import is_account_in_journal
from balanceai_backend.models.raw_transaction import RawTransaction
from balanceai_backend.models.receipt import (
    AccountMatch,
    PaymentMethod,
    ReceiptAccount,
    ReceiptExtraction,
    ReceiptKind,
)
from balanceai_backend.paths import RECEIPTS_DIR
from balanceai_backend.raw_transactions.raw_transaction_db import (
    find_receipt_account_ids_for_card_last4,
    upsert_raw_transaction,
)
from balanceai_backend.utils.general_util import get_mime_type
from balanceai_backend.utils.ocr_util import OcrUtil

logger = logging.getLogger(__name__)

_UNREADABLE = "Couldn't read this receipt. Try a clearer photo."

_ASK_ACCOUNT = (
    "Ask the user which account paid, then pass its account_id (from list_bank_accounts)."
)


def resolve_receipt_path(file_name: str, receipts_dir: Path | None = None) -> Path:
    """The receipt's path inside the receipts folder. Only files there are ever
    read, so the tool can't be pointed at other files on the machine.

    Raises:
        ValueError: if the name points outside the folder (e.g. '../x.jpg', an
            absolute path, a symlink out) or the file doesn't exist.
    """
    folder = (receipts_dir or RECEIPTS_DIR).resolve()
    path = (folder / file_name).resolve()
    if path.parent != folder or not path.is_file():
        raise ValueError(f"No receipt named {file_name!r} in the receipts folder.")
    return path


def read_receipt(path: Path) -> ReceiptExtraction:
    """Receipt image → ReceiptExtraction.

    Raises:
        ValueError: if the file type isn't supported, or the image couldn't be
            read. The AI's error text can quote the receipt, so it's logged
            locally only.
    """
    mime_type = get_mime_type(path.suffix)
    try:
        return OcrUtil.executeWithAnthropic(
            content=path.read_bytes(),
            output_format=ReceiptExtraction,
            mime_type=mime_type,
        )
    except Exception:
        logger.warning("read_receipt | failed", exc_info=True)
        raise ValueError(_UNREADABLE) from None


def suggest_receipt_account(
    receipt: ReceiptExtraction,
    journal_id: str | None = None,
    conn: sqlite3.Connection = _default_conn,
) -> ReceiptAccount:
    """A guess at the account that paid, for the user to confirm in the consent
    prompt.
    - Cash: the given journal's cash account; with no journal, ask.
    - Card: first, earlier receipts with the same card (always user-confirmed);
      else, the one bank account whose own last 4 matches (mostly from Plaid).
      Must be in journal_id, if given.
    - Anything else (no single guess, no payment info): ask.

    Raises:
        ValueError: asking for the account.
    """
    if receipt.payment_method is PaymentMethod.CASH:
        if journal_id:
            return ReceiptAccount(
                find_cash_account_for_journal(journal_id, conn=conn), AccountMatch.CASH
            )
        raise ValueError(f"Paid in cash. {_ASK_ACCOUNT}")

    card = normalize_last4(receipt.card_last4)
    if not card:
        raise ValueError(f"The receipt doesn't show how it was paid. {_ASK_ACCOUNT}")

    accounts = find_receipt_account_ids_for_card_last4(card, conn=conn)
    match = AccountMatch.HISTORY
    if not accounts:
        accounts = [a.id for a in find_bank_accounts(conn=conn) if a.last4 == card]
        match = AccountMatch.LAST4
    if len(accounts) == 1 and (
        journal_id is None or is_account_in_journal(accounts[0], journal_id, conn=conn)
    ):
        return ReceiptAccount(accounts[0], match)
    raise ValueError(f"Couldn't tell which account paid. {_ASK_ACCOUNT}")


def check_receipt_account(
    account_id: str, journal_id: str | None = None, conn: sqlite3.Connection = _default_conn
) -> None:
    """Check an account the user gave.

    Raises:
        ValueError: if it doesn't exist, or isn't in journal_id.
    """
    if not find_bank_accounts(id=account_id, conn=conn):
        raise ValueError(f"No bank account with id {account_id}. See list_bank_accounts.")
    if journal_id is not None and not is_account_in_journal(account_id, journal_id, conn=conn):
        raise ValueError(f"Bank account {account_id} isn't in journal {journal_id}.")


def sync_raw_transactions_from_receipt(
    receipt: ReceiptExtraction, account_id: str, conn: sqlite3.Connection = _default_conn
) -> RawTransaction:
    """Save the receipt as a raw transaction (source="receipt"). Saving the same
    receipt again adds a second row (catching duplicates is part of BL-15)."""
    amount = -receipt.total if receipt.kind is ReceiptKind.PURCHASE else receipt.total
    txn = RawTransaction(
        source="receipt",
        account_id=account_id,
        posting_date=receipt.date,
        description=receipt.counterparty,
        amount=amount,
        category=receipt.category,
        card_last4=normalize_last4(receipt.card_last4),
        tax=receipt.tax,
        tip=receipt.tip,
    )
    upsert_raw_transaction(txn, conn=conn)
    return txn


def normalize_last4(card: str | None) -> str | None:
    """'•••• 1234 ' → '1234'; None if there aren't 4 digits."""
    digits = re.sub(r"\D", "", card or "")
    return digits[-4:] if len(digits) >= 4 else None
