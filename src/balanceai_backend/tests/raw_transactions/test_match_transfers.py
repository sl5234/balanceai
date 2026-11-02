"""Tests for find_matched_transfers and generate_matched_transfer_entries."""

import datetime
from decimal import Decimal

import pytest
from balanceai_backend.models.bank_account import BankAccountType
from balanceai_backend.models.journal import JournalAccount
from balanceai_backend.models.raw_transaction import Classification, ClassifiedBy, RawTransaction
from balanceai_backend.raw_transactions.generate_journal_entries import (
    generate_matched_transfer_entries,
)
from balanceai_backend.raw_transactions.match_transfers import find_matched_transfers

CHECKING = "chase:checking:0000"
SAVINGS = "chase:savings:1111"
ALLY = "ally:savings:2222"
CARD = "chase:credit_card:3333"

ACCOUNT_TYPES = {
    CHECKING: BankAccountType.CHECKING,
    SAVINGS: BankAccountType.SAVINGS,
    ALLY: BankAccountType.SAVINGS,
    CARD: BankAccountType.CREDIT_CARD,
}


def _txn(
    txn_id: str,
    account_id: str,
    amount: str,
    day: int,
    counter_account: JournalAccount | None = JournalAccount.CASH,
) -> RawTransaction:
    return RawTransaction(
        id=txn_id,
        source="plaid",
        account_id=account_id,
        posting_date=datetime.date(2026, 10, day),
        description=f"Transfer {txn_id}",
        amount=Decimal(amount),
        classification=(
            None
            if counter_account is None
            else Classification(
                counter_account=counter_account,
                category="transfer",
                counterparty="Self",
                classified_by=ClassifiedBy.AI,
            )
        ),
    )


def _match_ids(txns: list[RawTransaction]) -> list[tuple[str, str]]:
    return [(o.id, i.id) for o, i in find_matched_transfers(txns, ACCOUNT_TYPES)]


class TestFindMatchedTransfers:
    def test_card_payment_matches(self):
        from_checking = _txn("out", CHECKING, "-900", 20, JournalAccount.CREDIT_CARD_PAYABLE)
        on_the_card = _txn("in", CARD, "900", 21, JournalAccount.CASH)

        assert _match_ids([from_checking, on_the_card]) == [("out", "in")]

    def test_checking_to_savings_matches(self):
        txns = [_txn("out", CHECKING, "-1000", 1), _txn("in", SAVINGS, "1000", 2)]

        assert _match_ids(txns) == [("out", "in")]

    @pytest.mark.parametrize(
        "in_side",
        [
            _txn("in", SAVINGS, "999.99", 2),  # different amount
            _txn("in", SAVINGS, "1000", 7),  # 6 days apart
            _txn("in", CHECKING, "1000", 2),  # same bank account
            _txn("in", SAVINGS, "-1000", 2),  # same direction
        ],
        ids=["different_amount", "6_days_apart", "same_account", "same_direction"],
    )
    def test_not_a_match(self, in_side):
        assert _match_ids([_txn("out", CHECKING, "-1000", 1), in_side]) == []

    def test_five_days_apart_still_matches(self):
        txns = [_txn("out", CHECKING, "-1000", 1), _txn("in", SAVINGS, "1000", 6)]

        assert _match_ids(txns) == [("out", "in")]

    def test_counters_must_point_at_each_other(self):
        purchase = _txn("out", CARD, "-900", 1, JournalAccount.NON_ESSENTIALS_EXPENSE)
        paycheck = _txn("in", CHECKING, "900", 1, JournalAccount.SALARY_INCOME)

        assert _match_ids([purchase, paycheck]) == []

    def test_one_wrongly_classified_side_doesnt_match(self):
        from_checking = _txn("out", CHECKING, "-900", 20, JournalAccount.CREDIT_CARD_PAYABLE)
        on_the_card = _txn("in", CARD, "900", 21, JournalAccount.CREDIT_CARD_PAYABLE)

        assert _match_ids([from_checking, on_the_card]) == []

    def test_closest_date_wins(self):
        txns = [
            _txn("a1", CHECKING, "-1000", 1),
            _txn("a2", CHECKING, "-1000", 3),
            _txn("b1", SAVINGS, "1000", 2),
            _txn("b2", SAVINGS, "1000", 4),
        ]

        assert sorted(_match_ids(txns)) == [("a1", "b1"), ("a2", "b2")]

    def test_true_tie_matches_none(self):
        txns = [
            _txn("a", CHECKING, "-1000", 1),
            _txn("b", SAVINGS, "1000", 2),
            _txn("c", ALLY, "1000", 2),
        ]

        assert _match_ids(txns) == []

    def test_tie_on_one_account_still_matches_once(self):
        txns = [
            _txn("a", CHECKING, "-1000", 1),
            _txn("b", SAVINGS, "1000", 2),
            _txn("c", SAVINGS, "1000", 2),
        ]

        assert _match_ids(txns) == [("a", "b")]

    def test_a_tie_doesnt_stop_other_matches(self):
        txns = [
            _txn("a", CHECKING, "-1000", 1),
            _txn("b", SAVINGS, "1000", 2),
            _txn("c", ALLY, "1000", 2),
            _txn("d", CHECKING, "-500", 20),
            _txn("e", SAVINGS, "500", 21),
        ]

        assert _match_ids(txns) == [("d", "e")]

    def test_closer_candidate_breaks_what_would_be_a_tie(self):
        txns = [
            _txn("a", CHECKING, "-1000", 1),
            _txn("b", SAVINGS, "1000", 2),
            _txn("c", ALLY, "1000", 4),
        ]

        assert _match_ids(txns) == [("a", "b")]

    def test_same_result_whatever_the_input_order(self):
        txns = [
            _txn("a1", CHECKING, "-1000", 1),
            _txn("a2", CHECKING, "-1000", 3),
            _txn("b1", SAVINGS, "1000", 2),
            _txn("b2", SAVINGS, "1000", 4),
        ]

        assert _match_ids(txns) == _match_ids(list(reversed(txns)))

    def test_unclassified_and_unknown_accounts_are_skipped(self):
        txns = [
            _txn("out", CHECKING, "-1000", 1),
            _txn("unclassified", SAVINGS, "1000", 2, counter_account=None),
            _txn("unknown", "other_bank:savings:9999", "1000", 2),
        ]

        assert _match_ids(txns) == []


class TestGenerateMatchedTransferEntries:
    def test_the_two_bank_side_lines(self):
        out_side = _txn("out", CHECKING, "-900", 20, JournalAccount.CREDIT_CARD_PAYABLE)
        in_side = _txn("in", CARD, "900", 21, JournalAccount.CASH)

        credit, debit = generate_matched_transfer_entries(
            out_side, BankAccountType.CHECKING, in_side, BankAccountType.CREDIT_CARD
        )

        assert (credit.account, credit.debit, credit.credit) == (
            JournalAccount.CASH,
            Decimal(0),
            Decimal(900),
        )
        assert (debit.account, debit.debit, debit.credit) == (
            JournalAccount.CREDIT_CARD_PAYABLE,
            Decimal(900),
            Decimal(0),
        )

    def test_each_line_keeps_its_own_transaction(self):
        out_side = _txn("out", CHECKING, "-1000", 1)
        in_side = _txn("in", SAVINGS, "1000", 2)

        credit, debit = generate_matched_transfer_entries(
            out_side, BankAccountType.CHECKING, in_side, BankAccountType.SAVINGS
        )

        assert (credit.date, credit.raw_transaction_id, credit.bank_account_id) == (
            datetime.date(2026, 10, 1),
            "out",
            CHECKING,
        )
        assert (debit.date, debit.raw_transaction_id, debit.bank_account_id) == (
            datetime.date(2026, 10, 2),
            "in",
            SAVINGS,
        )
        assert credit.description == "Transfer out" and debit.description == "Transfer in"

    def test_lines_balance_and_share_one_entry(self):
        lines = generate_matched_transfer_entries(
            _txn("out", CHECKING, "-1000", 1),
            BankAccountType.CHECKING,
            _txn("in", SAVINGS, "1000", 2),
            BankAccountType.SAVINGS,
        )

        assert sum(e.debit for e in lines) == sum(e.credit for e in lines)
        assert (
            lines[0].journal_entry_id is not None
            and lines[0].journal_entry_id == lines[1].journal_entry_id
        )

    def test_unclassified_side_raises(self):
        with pytest.raises(ValueError, match="in isn't classified"):
            generate_matched_transfer_entries(
                _txn("out", CHECKING, "-1000", 1),
                BankAccountType.CHECKING,
                _txn("in", SAVINGS, "1000", 2, counter_account=None),
                BankAccountType.SAVINGS,
            )
