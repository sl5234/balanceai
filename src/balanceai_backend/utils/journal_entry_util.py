import json
import logging

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
_fh = logging.FileHandler("/Users/sl5234/Workspace/BalanceAI/logs/journal_entry_util.log", mode="a")
_fh.setLevel(logging.DEBUG)
_fh.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))
logger.addHandler(_fh)

from balanceai_backend.journals.merchant_cache import (
    load_merchant_context_cache,
    save_merchant_context_cache,
)
from balanceai_backend.models.journal import GeneratedJournalEntrySet, GeneratedJournalLine
from balanceai_backend.models.transaction import Transaction
from balanceai_backend.prompts.extract_journal_entry_prompt import (
    categorize_journal_entry_prompt,
    extract_journal_entries_prompt,
)
from balanceai_backend.services import anthropic as anthropic_service
from balanceai_backend.services import tavily as tavily_service
from balanceai_backend.utils.ocr_util import _extract_json

DEFAULT_MODEL_ID = "claude-sonnet-4-6"


def generate_transaction_category(entry: GeneratedJournalLine) -> GeneratedJournalLine:
    """
    For a journal entry with null category, look up cached categorization or fall back to
    Tavily + LLM. Caches counterparty → category for future lookups.
    Returns the entry unchanged if no context can be found.
    """
    key = entry.counterparty.lower()
    cache = load_merchant_context_cache()

    if key in cache:
        return entry.model_copy(update={"category": cache[key]})

    context = tavily_service.search(f"What type of business is: {entry.counterparty}")
    if not context:
        logger.warning("Tavily returned no context for counterparty: %s", entry.counterparty)
        return entry

    schema = json.dumps(GeneratedJournalLine.model_json_schema(), indent=2)
    response = anthropic_service.messages(
        model_id=DEFAULT_MODEL_ID,
        content=entry.model_dump_json(),
        system_instruction=categorize_journal_entry_prompt(schema, context),
    )
    logger.info("generate_transaction_category LLM raw response: %s", response)
    result = GeneratedJournalLine.model_validate_json(_extract_json(response))

    if result.category:
        cache[key] = result.category
        save_merchant_context_cache(cache)

    return result


def extract_journal_lines_from_bank_statement_transaction(transaction: Transaction) -> list:
    """
    Extract journal entries from a single parsed bank statement transaction using Claude.

    Args:
        transaction: A Transaction parsed from a bank statement

    Returns:
        List of GeneratedJournalLine objects
    """
    schema = json.dumps(GeneratedJournalEntrySet.model_json_schema(), indent=2)
    merchant_context = load_merchant_context_cache()
    response = anthropic_service.messages(
        model_id=DEFAULT_MODEL_ID,
        content=json.dumps(transaction.to_dict()),
        system_instruction=extract_journal_entries_prompt(
            schema, json.dumps(merchant_context) if merchant_context else None
        ),
    )
    logger.info(
        "extract_journal_lines_from_bank_statement_transaction LLM raw response: %s", response
    )
    result = GeneratedJournalEntrySet.model_validate_json(_extract_json(response))
    return result.lines


def extract_journal_lines_from_plaid_transaction(transaction: dict) -> list:
    """
    Extract journal entries from a single Plaid transaction using Claude.

    Uses double-entry bookkeeping to generate the appropriate debit/credit
    journal entries for the given transaction.

    Args:
        transaction: A single Plaid transaction dict

    Returns:
        List of GeneratedJournalLine objects

    # TODO: Model the input transaction type.
    # TODO: Model the return type instead of returning raw GeneratedJournalLine list.
    """
    schema = json.dumps(GeneratedJournalEntrySet.model_json_schema(), indent=2)
    response = anthropic_service.messages(
        model_id=DEFAULT_MODEL_ID,
        content=json.dumps(transaction),
        system_instruction=extract_journal_entries_prompt(schema),
    )
    result = GeneratedJournalEntrySet.model_validate_json(_extract_json(response))
    return result.lines
