import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import anthropic

from balanceai.helpers.plaid_helper import extract_journal_entries_from_transactions
from balanceai.journals.finder import find_journal_entry as finder_find_journal_entry
from balanceai.journals.storage import find_journal_by_id
from balanceai.journals.storage import update_journal as storage_update_journal
from balanceai.models.journal import JournalEntryDataSet
from balanceai.parsers import get_parser
import balanceai.parsers.chase  # noqa: F401 - register parsers
from balanceai.utils.journal_entry_util import extract_journal_entries_from_bank_statement_transaction
from balanceai.utils.general_util import get_mime_type
from balanceai.utils.ocr_util import OcrUtil

_BATCH_SIZE = 10
_RATE_LIMIT_RETRY_SECONDS = 60


def handle_sync_journal_entries_from_receipt(journal_id: str, input_local_path: Path) -> dict:
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


def handle_sync_journal_entries_from_transactions(journal_id: str, transactions: dict) -> dict:
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


def handle_sync_journal_entries_from_bank_statement(journal_id: str, file_path: str) -> dict:
    journal = find_journal_by_id(journal_id)
    if journal is None:
        raise ValueError(f"Journal {journal_id} not found")

    _, transactions = get_parser(journal.account.bank).parse(file_path)

    batches = [transactions[i:i + _BATCH_SIZE] for i in range(0, len(transactions), _BATCH_SIZE)]

    for batch in batches:
        while True:
            try:
                with ThreadPoolExecutor(max_workers=len(batch)) as executor:
                    futures = {executor.submit(extract_journal_entries_from_bank_statement_transaction, txn): txn for txn in batch}
                    batch_results = []
                    for future in as_completed(futures):
                        batch_results.append(future.result())
            except anthropic.RateLimitError:
                time.sleep(_RATE_LIMIT_RETRY_SECONDS)
                continue

            for entries in batch_results:
                for entry_data in entries:
                    entry = entry_data.to_journal_entry()
                    existing = finder_find_journal_entry(journal_id, entry)
                    if existing is not None:
                        entry.journal_entry_id = existing.journal_entry_id
                        journal.remove_entry(existing.journal_entry_id)
                    journal.add_entry(entry)

            storage_update_journal(journal)
            break

    return journal.to_dict()
