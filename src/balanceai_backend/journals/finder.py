import json
import logging

from balanceai_backend.journals.storage import load_journal_entries
from balanceai_backend.models.journal import JournalEntry
from balanceai_backend.prompts.journal_entry_finder import SYSTEM_PROMPT
from balanceai_backend.utils.ocr_util import _extract_json

logger = logging.getLogger(__name__)

_MODEL_ID = "claude-haiku-4-5-20251001"


def find_journal_entry(journal_id: str, candidate: JournalEntry) -> JournalEntry | None:
    """
    Find an existing journal entry that matches the candidate.

    Filters by date and account first, then uses an LLM to fuzzy-match
    on description and amounts.

    Args:
        journal_id: The journal to search in.
        candidate: The entry to match against.

    Returns:
        The matching JournalEntry if found, otherwise None.
    """
    entries = load_journal_entries(journal_id, date=candidate.date)
    entries = [e for e in entries if e.account == candidate.account]

    if not entries:
        return None

    prompt = (
        f"Existing entries:\n{json.dumps([e.to_dict() for e in entries], indent=2)}\n\n"
        f"Candidate entry:\n{json.dumps(candidate.to_dict(), indent=2)}"
    )

    from balanceai_backend.services.anthropic import messages
    response = messages(
        model_id=_MODEL_ID,
        content=prompt,
        system_instruction=SYSTEM_PROMPT,
        temperature=0.0,
        max_output_tokens=256,
    )

    print(f"[finder] LLM raw response: {response!r}")
    result = json.loads(_extract_json(response))

    if not result.get("match"):
        return None

    matched_id = result.get("journal_entry_id")
    return next((e for e in entries if e.journal_entry_id == matched_id), None)
