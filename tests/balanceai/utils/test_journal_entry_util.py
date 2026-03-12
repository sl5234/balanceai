import sys
from unittest.mock import MagicMock, patch

sys.modules.setdefault("anthropic", MagicMock())
sys.modules.setdefault("tavily", MagicMock())

from balanceai.utils.journal_entry_util import extract_merchant, get_merchant_context


# ---------------------------------------------------------------------------
# extract_merchant
# ---------------------------------------------------------------------------


class TestExtractMerchant:
    def test_strips_leading_date(self):
        assert extract_merchant("01/28 Uber *One Membership San Francisco CA") == "Uber *One Membership San Francisco CA"

    def test_strips_card_purchase_prefix_and_date(self):
        assert extract_merchant("Card Purchase 01/25 Shell Oil Seattle WA") == "Shell Oil Seattle WA"

    def test_strips_card_purchase_with_pin_prefix_and_date(self):
        assert extract_merchant("Card Purchase With Pin 01/25 Shell Oil Seattle WA") == "Shell Oil Seattle WA"

    def test_strips_recurring_card_purchase_prefix(self):
        assert extract_merchant("Recurring Card Purchase 01/27 Adobe Systems Inc.") == "Adobe Systems Inc."

    def test_strips_leading_date_and_prefix_together(self):
        result = extract_merchant("01/28 Card Purchase With Pin 01/28 Uber *One Membership San Francisco CA -9.99 6,271.43")
        assert result == "Uber *One Membership San Francisco CA"

    def test_strips_trailing_amounts(self):
        assert extract_merchant("Uber *One Membership San Francisco CA -9.99 6,271.43") == "Uber *One Membership San Francisco CA"

    def test_leaves_plain_description_unchanged(self):
        assert extract_merchant("Zelle Payment To John Smith") == "Zelle Payment To John Smith"

    def test_case_insensitive_prefix_matching(self):
        assert extract_merchant("card purchase 01/25 Shell Oil Seattle WA") == "Shell Oil Seattle WA"


# ---------------------------------------------------------------------------
# get_merchant_context
# ---------------------------------------------------------------------------


class TestGetMerchantContext:
    def test_returns_cached_value_without_calling_tavily(self):
        cache = {"shell oil seattle wa": "Shell Oil is a gas station."}
        with patch("balanceai.utils.journal_entry_util.load_merchant_context_cache", return_value=cache):
            with patch("balanceai.utils.journal_entry_util.tavily_service.search") as mock_search:
                result = get_merchant_context("Card Purchase 01/25 Shell Oil Seattle WA")
        assert result == "Shell Oil is a gas station."
        mock_search.assert_not_called()

    def test_calls_tavily_and_writes_to_cache_on_miss(self):
        with patch("balanceai.utils.journal_entry_util.load_merchant_context_cache", return_value={}):
            with patch("balanceai.utils.journal_entry_util.save_merchant_context_cache") as mock_save:
                with patch("balanceai.utils.journal_entry_util.tavily_service.search", return_value="Rudy's is a barbershop."):
                    result = get_merchant_context("Rudy's")
        assert result == "Rudy's is a barbershop."
        mock_save.assert_called_once()

    def test_returns_none_and_does_not_write_cache_when_tavily_returns_none(self):
        with patch("balanceai.utils.journal_entry_util.load_merchant_context_cache", return_value={}):
            with patch("balanceai.utils.journal_entry_util.save_merchant_context_cache") as mock_save:
                with patch("balanceai.utils.journal_entry_util.tavily_service.search", return_value=None):
                    result = get_merchant_context("Some Unknown Merchant")
        assert result is None
        mock_save.assert_not_called()