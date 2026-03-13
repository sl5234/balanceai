import json
import logging
import re

logger = logging.getLogger(__name__)

from balanceai.journals.merchant_cache import load_merchant_context_cache, save_merchant_context_cache
from balanceai.models.journal import GeneratedJournalEntry, GeneratedJournalEntrySet
from balanceai.models.transaction import Transaction
from balanceai.prompts.extract_journal_entry_prompt import categorize_journal_entry_prompt, extract_journal_entries_prompt
from balanceai.services import anthropic as anthropic_service
from balanceai.services import tavily as tavily_service
from balanceai.utils.ocr_util import _extract_json

DEFAULT_MODEL_ID = "claude-sonnet-4-6"


def extract_merchant(description: str) -> str:
    """Strip dates, card purchase prefixes, and trailing amounts from a raw bank description."""
    # "01/28 Card Purchase With Pin ..." -> "Card Purchase With Pin ..."
    cleaned = re.sub(r"^\d{1,2}/\d{1,2}\s+", "", description.strip())
    # "Card Purchase With Pin 01/28 Uber *One ..." -> "Uber *One ..."
    cleaned = re.sub(
        r"(?:Card Purchase With Pin|Card Purchase Return|Card Purchase|Recurring Card Purchase|Card Transaction)\s+\d{1,2}/\d{1,2}\s+",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    # "Uber *One Membership San Francisco CA -9.99 6,271.43" -> "Uber *One Membership San Francisco CA"
    cleaned = re.sub(r"\s+-?[\d,]+\.\d{2}(\s+[\d,]+\.\d{2})*\s*$", "", cleaned)
    return cleaned.strip()


def generate_transaction_category(entry: GeneratedJournalEntry) -> GeneratedJournalEntry:
    """
    For a journal entry with null category, look up cached categorization or fall back to
    Tavily + LLM. Caches recipient → category for future lookups.
    Returns the entry unchanged if no context can be found.
    """
    key = entry.recipient.lower()
    cache = load_merchant_context_cache()

    if key in cache:
        return entry.model_copy(update={"category": cache[key]})

    context = tavily_service.search(f"What type of business is: {entry.recipient}")
    if not context:
        logger.warning("Tavily returned no context for recipient: %s", entry.recipient)
        return entry

    schema = json.dumps(GeneratedJournalEntry.model_json_schema(), indent=2)
    response = anthropic_service.messages(
        model_id=DEFAULT_MODEL_ID,
        content=entry.model_dump_json(),
        system_instruction=categorize_journal_entry_prompt(schema, context),
    )
    result = GeneratedJournalEntry.model_validate_json(_extract_json(response))

    if result.category:
        cache[key] = result.category
        save_merchant_context_cache(cache)

    return result


def extract_journal_entries_from_bank_statement_transaction(transaction: Transaction) -> list:
    """
    Extract journal entries from a single parsed bank statement transaction using Claude.

    Args:
        transaction: A Transaction parsed from a bank statement

    Returns:
        List of GeneratedJournalEntry objects
    """
    schema = json.dumps(GeneratedJournalEntrySet.model_json_schema(), indent=2)
    merchant_context = load_merchant_context_cache()
    response = anthropic_service.messages(
        model_id=DEFAULT_MODEL_ID,
        content=json.dumps(transaction.to_dict()),
        system_instruction=extract_journal_entries_prompt(schema, merchant_context),
    )
    result = GeneratedJournalEntrySet.model_validate_json(_extract_json(response))
    return result.entries


def extract_journal_entries_from_plaid_transaction(transaction: dict) -> list:
    """
    Extract journal entries from a single Plaid transaction using Claude.

    Uses double-entry bookkeeping to generate the appropriate debit/credit
    journal entries for the given transaction.

    Args:
        transaction: A single Plaid transaction dict

    Returns:
        List of GeneratedJournalEntry objects

    # TODO: Model the input transaction type.
    # TODO: Model the return type instead of returning raw GeneratedJournalEntry list.
    """
    schema = json.dumps(GeneratedJournalEntrySet.model_json_schema(), indent=2)
    response = anthropic_service.messages(
        model_id=DEFAULT_MODEL_ID,
        content=json.dumps(transaction),
        system_instruction=extract_journal_entries_prompt(schema),
    )
    result = GeneratedJournalEntrySet.model_validate_json(_extract_json(response))
    return result.entries
