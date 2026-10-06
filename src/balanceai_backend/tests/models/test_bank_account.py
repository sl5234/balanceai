import pytest
from balanceai_backend.models.bank_account import (
    BankAccount,
    BankAccountType,
    build_bank_account_id,
)


class TestBankAccount:
    def test_round_trips_through_dict(self):
        account = BankAccount(
            id="tartan_bank:checking:0000",
            institution_name="Tartan Bank",
            account_type=BankAccountType.CHECKING,
            last4="0000",
            display_name="Plaid Checking",
            plaid_institution_id="ins_109511",
            plaid_item_id="item-1",
            plaid_account_id="plaid-acc-1",
        )
        d = account.to_dict()
        assert d["account_type"] == "checking"
        assert BankAccount.from_dict(d) == account

    def test_from_dict_defaults_optional_fields_to_none(self):
        account = BankAccount.from_dict(
            {
                "id": "chase:credit_card:1234",
                "institution_name": "Chase",
                "account_type": "credit_card",
                "last4": "1234",
            }
        )
        assert account.display_name is None
        assert account.plaid_account_id is None


class TestBuildBankAccountId:
    @pytest.mark.parametrize(
        ("institution_name", "account_type", "last4", "expected"),
        [
            ("Tartan Bank", BankAccountType.CHECKING, "0000", "tartan_bank:checking:0000"),
            (
                "Capital One, N.A.",
                BankAccountType.CREDIT_CARD,
                "1234",
                "capital_one_na:credit_card:1234",
            ),
            ("  Chase  ", BankAccountType.SAVINGS, "42", "chase:savings:42"),
        ],
    )
    def test_builds_normalized_id(self, institution_name, account_type, last4, expected):
        assert build_bank_account_id(institution_name, account_type, last4) == expected

    def test_raises_when_institution_name_empty_after_normalizing(self):
        with pytest.raises(ValueError, match="institution_name"):
            build_bank_account_id(" .,& ", BankAccountType.CHECKING, "1234")

    def test_raises_when_last4_empty(self):
        with pytest.raises(ValueError, match="last4"):
            build_bank_account_id("Chase", BankAccountType.CHECKING, "")
