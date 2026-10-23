"""Keep the classifier prompt in step with JournalAccount."""

import re

from balanceai_backend.models.journal import JournalAccount
from balanceai_backend.prompts.classify_transaction_prompt import _COUNTER_ACCOUNTS, _EXAMPLES

_ACCOUNTS = {account.value for account in JournalAccount}


def test_examples_only_use_existing_accounts():
    used = set(re.findall(r"counter_account: (\w+)", _EXAMPLES))
    assert used
    assert used <= _ACCOUNTS


def test_every_account_but_opening_balance_is_described():
    described = set(re.findall(r"^- (\w+):", _COUNTER_ACCOUNTS, re.MULTILINE))
    assert described == _ACCOUNTS - {JournalAccount.OPENING_BALANCE.value}
