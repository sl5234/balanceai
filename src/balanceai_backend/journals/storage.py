# DEPRECATED: This module is no longer used by any production code.
# All persistence has been migrated to journal_db.py, which uses SQLite
# via the connection in db.py.  This file used a JSON Lines flat file
# (data/journals.jsonl) as its backing store.
#
# Do not add new callers.  This file is kept for reference only and will
# be removed in a future cleanup.

# import datetime
# import json
# import logging
# from pathlib import Path
#
# from typing import Optional
#
# from balanceai_backend.models import Journal
# from balanceai_backend.models.journal import JournalEntry
#
# logger = logging.getLogger(__name__)
#
# DATA_DIR = Path(__file__).parent.parent / "data"
#
#
# def _ensure_data_dir():
#     DATA_DIR.mkdir(parents=True, exist_ok=True)
#
#
# def load_journals() -> list[Journal]:
#     """Load all journals from storage."""
#     _ensure_data_dir()
#     path = DATA_DIR / "journals.jsonl"
#
#     if not path.exists():
#         return []
#
#     journals = []
#     with open(path) as f:
#         for line in f:
#             line = line.strip()
#             if line:
#                 journals.append(Journal.from_dict(json.loads(line)))
#     return journals
#
#
# def save_journal(journal: Journal) -> None:
#     """Append a journal to storage, keeping journals sorted by start_date."""
#     _ensure_data_dir()
#     journals = load_journals()
#     journals.append(journal)
#     journals.sort(key=lambda j: j.start_date)
#     _save_all_journals(journals)
#
#
# def _save_all_journals(journals: list[Journal]) -> None:
#     """Overwrite storage with the given list of journals."""
#     _ensure_data_dir()
#     path = DATA_DIR / "journals.jsonl"
#
#     with open(path, "w") as f:
#         for journal in journals:
#             f.write(json.dumps(journal.to_dict()) + "\n")
#
#
# def find_journal_by_id(journal_id: str) -> Journal | None:
#     """Find a journal by its journal_id."""
#     for journal in load_journals():
#         if journal.journal_id == journal_id:
#             return journal
#     return None
#
#
# def load_journal_entries(journal_id: str, date: Optional[datetime.date] = None) -> list[JournalEntry]:
#     """Load entries for a journal, optionally filtered by date."""
#     journal = find_journal_by_id(journal_id)
#     if journal is None:
#         raise ValueError(f"Journal {journal_id} not found")
#     entries = journal.entries
#     if date is not None:
#         entries = [e for e in entries if e.date == date]
#     return entries
#
#
# def update_journal(updated: Journal) -> None:
#     """Replace a journal in storage by matching journal_id, keeping journals sorted by start_date."""
#     journals = load_journals()
#     for i, journal in enumerate(journals):
#         if journal.journal_id == updated.journal_id:
#             journals[i] = updated
#             journals.sort(key=lambda j: j.start_date)
#             _save_all_journals(journals)
#             return
#     raise ValueError(f"Journal {updated.journal_id} not found")
