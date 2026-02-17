import json
import logging
from pathlib import Path

from typing import Optional

from balanceai.models import Journal

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent.parent / "data"


def _ensure_data_dir():
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def load_journals() -> list[Journal]:
    """Load all journals from storage."""
    _ensure_data_dir()
    path = DATA_DIR / "journals.jsonl"

    if not path.exists():
        return []

    journals = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                journals.append(Journal.from_dict(json.loads(line)))
    return journals


def save_journal(journal: Journal) -> None:
    """Append a journal to storage."""
    _ensure_data_dir()
    path = DATA_DIR / "journals.jsonl"

    with open(path, "a") as f:
        f.write(json.dumps(journal.to_dict()) + "\n")


def _save_all_journals(journals: list[Journal]) -> None:
    """Overwrite storage with the given list of journals."""
    _ensure_data_dir()
    path = DATA_DIR / "journals.jsonl"

    with open(path, "w") as f:
        for journal in journals:
            f.write(json.dumps(journal.to_dict()) + "\n")


def find_journal_by_id(journal_id: str) -> Journal | None:
    """Find a journal by its journal_id."""
    for journal in load_journals():
        if journal.journal_id == journal_id:
            return journal
    return None


def update_journal(updated: Journal) -> None:
    """Replace a journal in storage by matching journal_id."""
    journals = load_journals()
    for i, journal in enumerate(journals):
        if journal.journal_id == updated.journal_id:
            journals[i] = updated
            _save_all_journals(journals)
            return
    raise ValueError(f"Journal {updated.journal_id} not found")
