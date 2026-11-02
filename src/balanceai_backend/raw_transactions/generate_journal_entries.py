"""Turn a classified raw transaction into a journal entry, by rule.

One line is the bank account the transaction happened in, from its account
type; the other is the classification's counter account. The amount's sign
decides which is debited; see docs/BACKEND_IMPLEMENTATION_DECISIONS.md #2.
"""

from decimal import Decimal

from appdevcommons.unique_id import UniqueIdGenerator

from balanceai_backend.models.bank_account import BankAccountType
from balanceai_backend.models.journal import JournalAccount, JournalEntry
from balanceai_backend.models.raw_transaction import RawTransaction

_BANK_SIDE_ACCOUNT = {
    # depository
    BankAccountType.CHECKING: JournalAccount.CASH,
    BankAccountType.SAVINGS: JournalAccount.CASH,
    BankAccountType.MONEY_MARKET: JournalAccount.CASH,
    BankAccountType.CD: JournalAccount.CASH,
    BankAccountType.OTHER_DEPOSITORY: JournalAccount.CASH,
    # credit
    BankAccountType.CREDIT_CARD: JournalAccount.CREDIT_CARD_PAYABLE,
    BankAccountType.OTHER_CREDIT: JournalAccount.CREDIT_CARD_PAYABLE,
    # loan
    BankAccountType.MORTGAGE: JournalAccount.LOANS_PAYABLE,
    BankAccountType.HOME_EQUITY: JournalAccount.LOANS_PAYABLE,
    BankAccountType.AUTO_LOAN: JournalAccount.LOANS_PAYABLE,
    BankAccountType.STUDENT_LOAN: JournalAccount.LOANS_PAYABLE,
    BankAccountType.PERSONAL_LOAN: JournalAccount.LOANS_PAYABLE,
    BankAccountType.LINE_OF_CREDIT: JournalAccount.LOANS_PAYABLE,
    BankAccountType.OTHER_LOAN: JournalAccount.LOANS_PAYABLE,
    # investment
    BankAccountType.BROKERAGE: JournalAccount.INVESTMENTS,
    BankAccountType.IRA: JournalAccount.INVESTMENTS,
    BankAccountType.ROTH_IRA: JournalAccount.INVESTMENTS,
    BankAccountType.RETIREMENT_401K: JournalAccount.INVESTMENTS,
    BankAccountType.ROTH_401K: JournalAccount.INVESTMENTS,
    BankAccountType.HSA: JournalAccount.INVESTMENTS,
    BankAccountType.COLLEGE_529: JournalAccount.INVESTMENTS,
    BankAccountType.OTHER_INVESTMENT: JournalAccount.INVESTMENTS,
}


def bank_side_account(account_type: BankAccountType) -> JournalAccount:
    """The journal account a bank account's own side of an entry posts to."""
    return _BANK_SIDE_ACCOUNT[account_type]


def generate_journal_entries(
    txn: RawTransaction, account_type: BankAccountType
) -> list[JournalEntry]:
    """
    The two lines of the journal entry for a classified raw transaction: the
    bank side (from account_type) and the counter account (from the
    classification). Money out credits the bank side and debits the counter
    account; money in does the opposite. Both lines carry the transaction's
    date, description, category, counterparty, raw transaction id, and one
    shared entry id. Only the bank side names the bank account — the counter
    side's account, if it's a bank account at all, isn't known from one
    transaction (decision #9).

    Returns:
        The two lines, bank side first; empty for a zero amount.

    Raises:
        ValueError: if the transaction isn't classified.
    """
    if txn.classification is None:
        raise ValueError(f"Raw transaction {txn.id} isn't classified")
    amount = abs(txn.amount)
    if amount == 0:
        return []

    money_out = txn.amount < 0
    journal_entry_id = UniqueIdGenerator.generate_id()
    sides = [
        # (account, is_debit, bank_account_id)
        (bank_side_account(account_type), not money_out, txn.account_id),
        (txn.classification.counter_account, money_out, None),
    ]
    return [
        _line(txn, account, amount, is_debit, journal_entry_id, bank_account_id)
        for account, is_debit, bank_account_id in sides
    ]


def generate_matched_transfer_entries(
    out_side: RawTransaction,
    out_type: BankAccountType,
    in_side: RawTransaction,
    in_type: BankAccountType,
) -> list[JournalEntry]:
    """
    The journal entry for a matched transfer, whose two sides were found: just the two
    bank-side lines (decision #7). The money-out side's account is credited and
    the money-in side's is debited; each line keeps its own transaction's date,
    description, category, counterparty, and ids, and both share an entry id.

    Raises:
        ValueError: if either side isn't classified.
    """
    for txn in (out_side, in_side):
        if txn.classification is None:
            raise ValueError(f"Raw transaction {txn.id} isn't classified")
    amount = abs(out_side.amount)
    journal_entry_id = UniqueIdGenerator.generate_id()
    return [
        _line(
            out_side,
            bank_side_account(out_type),
            amount,
            False,
            journal_entry_id,
            out_side.account_id,
        ),
        _line(
            in_side, bank_side_account(in_type), amount, True, journal_entry_id, in_side.account_id
        ),
    ]


def _line(
    txn: RawTransaction,
    account: JournalAccount,
    amount: Decimal,
    is_debit: bool,
    journal_entry_id: str,
    bank_account_id: str | None,
) -> JournalEntry:
    """One line of an entry, with the transaction's details."""
    assert txn.classification is not None
    return JournalEntry(
        journal_line_id=UniqueIdGenerator.generate_id(),
        date=txn.posting_date,
        account=account,
        description=txn.description,
        debit=amount if is_debit else Decimal(0),
        credit=Decimal(0) if is_debit else amount,
        category=txn.classification.category,
        recipient=txn.classification.counterparty or txn.description,
        journal_entry_id=journal_entry_id,
        raw_transaction_id=txn.id,
        bank_account_id=bank_account_id,
    )
