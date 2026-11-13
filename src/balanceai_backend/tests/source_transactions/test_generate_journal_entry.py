"""Tests for generate_journal_entry: a classified source transaction -> two lines."""

import datetime
from decimal import Decimal

import pytest
from balanceai_backend.models.bank_account import BankAccountType
from balanceai_backend.models.journal import JournalAccount
from balanceai_backend.models.source_transaction import (
    Classification,
    ClassifiedBy,
)
from balanceai_backend.models.transaction import Transaction
from balanceai_backend.source_transactions.generate_journal_entry import (
    bank_side_account,
    generate_journal_entry,
)


def _txn(
    amount: str,
    counter_account: JournalAccount,
    counterparty: str | None = "Starbucks",
    account_id: str = "test_bank:checking:0000",
) -> Transaction:
    return Transaction(
        transaction_id="txn-1",
        account_id=account_id,
        transaction_date=datetime.date(2026, 9, 8),
        description="STARBUCKS #123",
        amount=Decimal(amount),
        classification=Classification(
            counter_account=counter_account,
            category="dining",
            counterparty=counterparty,
            classified_by=ClassifiedBy.AI,
        ),
    )


def _lines(entries) -> list[tuple[JournalAccount, Decimal, Decimal]]:
    return [(e.account, e.debit, e.credit) for e in entries]


class TestBankSideAccount:
    def test_every_account_type_is_mapped(self):
        for account_type in BankAccountType:
            assert isinstance(bank_side_account(account_type), JournalAccount)

    @pytest.mark.parametrize(
        "account_type, expected",
        [
            (BankAccountType.CHECKING, JournalAccount.CASH),
            (BankAccountType.MONEY_MARKET, JournalAccount.CASH),
            (BankAccountType.CREDIT_CARD, JournalAccount.CREDIT_CARD_PAYABLE),
            (BankAccountType.MORTGAGE, JournalAccount.LOANS_PAYABLE),
            (BankAccountType.RETIREMENT_401K, JournalAccount.INVESTMENTS),
            (BankAccountType.CASH, JournalAccount.CASH),
        ],
    )
    def test_one_of_each_kind(self, account_type, expected):
        assert bank_side_account(account_type) == expected


class TestGenerateJournalEntry:
    def test_money_out_of_checking(self):
        txn = _txn("-4.33", JournalAccount.NON_ESSENTIALS_EXPENSE)

        entries = generate_journal_entry(txn, BankAccountType.CHECKING)

        assert _lines(entries) == [
            (JournalAccount.CASH, Decimal(0), Decimal("4.33")),
            (JournalAccount.NON_ESSENTIALS_EXPENSE, Decimal("4.33"), Decimal(0)),
        ]

    def test_money_into_checking(self):
        txn = _txn("3200.00", JournalAccount.SALARY_INCOME, counterparty="Globex")

        entries = generate_journal_entry(txn, BankAccountType.CHECKING)

        assert _lines(entries) == [
            (JournalAccount.CASH, Decimal("3200.00"), Decimal(0)),
            (JournalAccount.SALARY_INCOME, Decimal(0), Decimal("3200.00")),
        ]

    def test_refund_reduces_the_expense(self):
        txn = _txn("500.00", JournalAccount.NON_ESSENTIALS_EXPENSE, counterparty="United")

        entries = generate_journal_entry(txn, BankAccountType.CHECKING)

        assert _lines(entries) == [
            (JournalAccount.CASH, Decimal("500.00"), Decimal(0)),
            (JournalAccount.NON_ESSENTIALS_EXPENSE, Decimal(0), Decimal("500.00")),
        ]

    def test_card_purchase_raises_what_you_owe(self):
        txn = _txn("-60.00", JournalAccount.NON_ESSENTIALS_EXPENSE)

        entries = generate_journal_entry(txn, BankAccountType.CREDIT_CARD)

        assert _lines(entries) == [
            (JournalAccount.CREDIT_CARD_PAYABLE, Decimal(0), Decimal("60.00")),
            (JournalAccount.NON_ESSENTIALS_EXPENSE, Decimal("60.00"), Decimal(0)),
        ]

    def test_card_payment_seen_from_each_side_gives_the_same_entry(self):
        from_checking = _txn("-900.00", JournalAccount.CREDIT_CARD_PAYABLE, counterparty="Self")
        on_the_card = _txn("900.00", JournalAccount.CASH, counterparty="Self")

        checking_lines = generate_journal_entry(from_checking, BankAccountType.CHECKING)
        card_lines = generate_journal_entry(on_the_card, BankAccountType.CREDIT_CARD)

        # debit credit_card_payable, credit cash — either way round
        assert sorted(_lines(checking_lines)) == sorted(_lines(card_lines))

    def test_loan_payment(self):
        txn = _txn("-1500.00", JournalAccount.LOANS_PAYABLE, counterparty="Mortgage Co")

        entries = generate_journal_entry(txn, BankAccountType.CHECKING)

        assert _lines(entries) == [
            (JournalAccount.CASH, Decimal(0), Decimal("1500.00")),
            (JournalAccount.LOANS_PAYABLE, Decimal("1500.00"), Decimal(0)),
        ]

    @pytest.mark.parametrize("amount", ["-4.33", "3200.00", "0.01"])
    def test_lines_always_balance(self, amount):
        entries = generate_journal_entry(
            _txn(amount, JournalAccount.OTHER_INCOME), BankAccountType.SAVINGS
        )

        assert sum(e.debit for e in entries) == sum(e.credit for e in entries)

    def test_both_lines_carry_the_transactions_details(self):
        txn = _txn("-4.33", JournalAccount.NON_ESSENTIALS_EXPENSE)

        entries = generate_journal_entry(txn, BankAccountType.CHECKING)

        for e in entries:
            assert e.date == datetime.date(2026, 9, 8)
            assert e.description == "STARBUCKS #123"
            assert e.category == "dining"
            assert e.counterparty == "Starbucks"
            assert e.tax == Decimal(0)
            assert e.transaction_id == "txn-1"
        assert entries[0].journal_line_id != entries[1].journal_line_id

    def test_both_lines_share_one_entry_id(self):
        first = generate_journal_entry(
            _txn("-4.33", JournalAccount.NON_ESSENTIALS_EXPENSE), BankAccountType.CHECKING
        )
        second = generate_journal_entry(
            _txn("-4.33", JournalAccount.NON_ESSENTIALS_EXPENSE), BankAccountType.CHECKING
        )

        assert first[0].journal_entry_id is not None
        assert first[0].journal_entry_id == first[1].journal_entry_id
        assert first[0].journal_entry_id != second[0].journal_entry_id

    def test_only_the_bank_side_names_the_bank_account(self):
        txn = _txn("-2000.00", JournalAccount.CASH, counterparty="Self")

        bank_side, counter = generate_journal_entry(txn, BankAccountType.CHECKING)

        assert bank_side.bank_account_id == "test_bank:checking:0000"
        assert counter.bank_account_id is None

    def test_no_counterparty_uses_the_description(self):
        txn = _txn("-4.33", JournalAccount.NON_ESSENTIALS_EXPENSE, counterparty=None)

        entries = generate_journal_entry(txn, BankAccountType.CHECKING)

        assert {e.counterparty for e in entries} == {"STARBUCKS #123"}

    def test_zero_amount_has_no_lines(self):
        txn = _txn("0.00", JournalAccount.NON_ESSENTIALS_EXPENSE)

        assert generate_journal_entry(txn, BankAccountType.CHECKING) == []

    def test_unclassified_raises(self):
        txn = _txn("-4.33", JournalAccount.NON_ESSENTIALS_EXPENSE)
        txn.classification = None

        with pytest.raises(ValueError, match="txn-1 isn't classified"):
            generate_journal_entry(txn, BankAccountType.CHECKING)
