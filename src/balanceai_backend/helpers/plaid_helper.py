from balanceai_backend.utils.journal_entry_util import (
    extract_journal_entries_from_plaid_transaction,
)


def extract_journal_entries_from_transactions(transactions: dict) -> dict:
    """
    Extract journal entries from a Plaid transactions response dict.

    Iterates through added, modified, and removed transactions, running each
    through the LLM to generate journal entries. Results are grouped by whether
    the entries should be upserted or removed from the journal.

    Args:
        transactions: Plaid transactions response dict (with added, modified, removed, etc.)

    Returns:
        dict with:
            - "upsert": list of journal entry dicts for added and modified transactions
            - "remove": list of journal entry dicts for removed transactions

    # TODO: Model the input and output types.
    """
    upsert_entries = []
    remove_entries = []

    for txn in transactions.get("added", []) + transactions.get("modified", []):
        entries = extract_journal_entries_from_plaid_transaction(txn)
        upsert_entries.extend(entries)

    for txn in transactions.get("removed", []):
        entries = extract_journal_entries_from_plaid_transaction(txn)
        remove_entries.extend(entries)

    return {"upsert": upsert_entries, "remove": remove_entries}
