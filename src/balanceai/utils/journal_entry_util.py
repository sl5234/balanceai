import json

from balanceai.models.journal import JournalEntryDataSet
from balanceai.models.transaction import Transaction
from balanceai.prompts.extract_journal_entry_prompt import extract_journal_entries_prompt
from balanceai.services import anthropic as anthropic_service
from balanceai.utils.ocr_util import _extract_json

DEFAULT_MODEL_ID = "claude-sonnet-4-6"


def extract_journal_entries_from_bank_statement_transaction(transaction: Transaction) -> list:
    """
    Extract journal entries from a single parsed bank statement transaction using Claude.

    Args:
        transaction: A Transaction parsed from a bank statement

    Returns:
        List of JournalEntryData objects
    """
    schema = json.dumps(JournalEntryDataSet.model_json_schema(), indent=2)
    response = anthropic_service.messages(
        model_id=DEFAULT_MODEL_ID,
        content=json.dumps(transaction.to_dict()),
        system_instruction=extract_journal_entries_prompt(schema),
    )
    result = JournalEntryDataSet.model_validate_json(_extract_json(response))
    return result.entries


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
    response = anthropic_service.messages(
        model_id=DEFAULT_MODEL_ID,
        content=json.dumps(transaction),
        system_instruction=extract_journal_entries_prompt(schema),
    )
    result = JournalEntryDataSet.model_validate_json(_extract_json(response))
    return result.entries
