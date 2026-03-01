from pathlib import Path

from balanceai.helpers.plaid_helper import extract_journal_entries_from_transactions
from balanceai.journals.finder import find_journal_entry as finder_find_journal_entry
from balanceai.journals.storage import find_journal_by_id
from balanceai.journals.storage import update_journal as storage_update_journal
from balanceai.models.journal import JournalEntryDataSet
from balanceai.utils.general_util import get_mime_type
from balanceai.utils.ocr_util import OcrUtil


def handle_create_or_update_journal_entries_for_receipt(journal_id: str, input_local_path: Path) -> dict:
    journal = find_journal_by_id(journal_id)
    if journal is None:
        raise ValueError(f"Journal {journal_id} not found")

    ocr_result = OcrUtil.executeWithAnthropic(
        content=input_local_path.read_bytes(),
        output_format=JournalEntryDataSet,
        mime_type=get_mime_type(input_local_path.suffix),
    )

    for entry_data in ocr_result.entries:
        entry = entry_data.to_journal_entry()
        existing = finder_find_journal_entry(journal_id, entry)
        if existing is not None:
            entry.journal_entry_id = existing.journal_entry_id
            journal.remove_entry(existing.journal_entry_id)
        journal.add_entry(entry)

    storage_update_journal(journal)
    return journal.to_dict()


def handle_create_or_update_journal_entries_for_transactions(journal_id: str, transactions: dict) -> dict:
    journal = find_journal_by_id(journal_id)
    if journal is None:
        raise ValueError(f"Journal {journal_id} not found")

    grouped = extract_journal_entries_from_transactions(transactions)
    upsert_entries = grouped["upsert"]
    remove_entries = grouped["remove"]

    for entry_data in upsert_entries:
        entry = entry_data.to_journal_entry()
        existing = finder_find_journal_entry(journal_id, entry)
        if existing is not None:
            entry.journal_entry_id = existing.journal_entry_id
            journal.remove_entry(existing.journal_entry_id)
        journal.add_entry(entry)

    for entry_data in remove_entries:
        existing = finder_find_journal_entry(journal_id, entry_data.to_journal_entry())
        if existing is not None:
            journal.remove_entry(existing.journal_entry_id)

    storage_update_journal(journal)
    return journal.to_dict()
