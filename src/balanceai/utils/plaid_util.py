import json

from balanceai.models.journal import JournalEntryDataSet
from balanceai.services import anthropic_service
from balanceai.utils.ocr_util import _extract_json

DEFAULT_MODEL_ID = "claude-sonnet-4-6"


def extract_journal_entries_from_plaid_transaction(transaction: dict) -> list:
    """
    Extract journal entries from a single Plaid transaction using Claude.

    Uses double-entry bookkeeping to generate the appropriate debit/credit
    journal entries for the given transaction.

    Args:
        transaction: A single Plaid transaction dict

    Returns:
        List of JournalEntryData objects

    # TODO: Model the input transaction type.
    # TODO: Model the return type instead of returning raw JournalEntryData list.
    """
    schema = json.dumps(JournalEntryDataSet.model_json_schema(), indent=2)
    system_prompt = (
        "You are a bookkeeping assistant. Given a bank transaction, "
        "generate journal entries using double-entry bookkeeping. "
        f"Return ONLY valid JSON matching this schema:\n{schema}\n\n"
        "Return ONLY valid JSON. No extra text."
    )

    response = anthropic_service.messages(
        model_id=DEFAULT_MODEL_ID,
        content=json.dumps(transaction),
        system_instruction=system_prompt,
    )

    result = JournalEntryDataSet.model_validate_json(_extract_json(response))
    return result.entries
