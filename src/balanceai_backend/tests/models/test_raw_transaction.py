import dataclasses

import pytest
from balanceai_backend.models.journal import JournalAccount
from balanceai_backend.models.source_transaction import Classification, ClassifiedBy


@pytest.mark.parametrize("classified_by", [ClassifiedBy.AI, ClassifiedBy.USER])
def test_unclassified_always_needs_review(classified_by):
    c = Classification(counter_account=JournalAccount.UNCLASSIFIED, classified_by=classified_by)
    assert c.needs_user_review


def test_unclassified_needs_review_after_loading_and_copying():
    c = Classification(counter_account=JournalAccount.UNCLASSIFIED, classified_by=ClassifiedBy.AI)
    stored = {**c.to_dict(), "needs_user_review": False}  # e.g. written before this rule
    assert Classification.from_dict(stored).needs_user_review
    assert dataclasses.replace(c, needs_user_review=False).needs_user_review


def test_other_accounts_keep_the_flag_as_given():
    c = Classification(
        counter_account=JournalAccount.NON_ESSENTIALS_EXPENSE, classified_by=ClassifiedBy.AI
    )
    assert not c.needs_user_review
