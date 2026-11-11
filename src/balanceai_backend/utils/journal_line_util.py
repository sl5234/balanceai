from balanceai_backend.models.journal import JournalLine


def group_into_entries(lines: list[JournalLine]) -> list[list[JournalLine]]:
    """Group lines by journal_entry_id, keeping date order."""
    entries: dict[str, list[JournalLine]] = {}
    for line in lines:
        entries.setdefault(line.journal_entry_id or line.journal_line_id, []).append(line)
    return list(entries.values())


def date_range(entries: list[list[JournalLine]]) -> str:
    """'<first date> to <last date>' across the entries' lines."""
    dates = [line.date for lines in entries for line in lines]
    return f"{min(dates).isoformat()} to {max(dates).isoformat()}"


def entry_to_dict(lines: list[JournalLine]) -> dict:
    """One journal entry with its lines redacted, for sharing with the assistant."""
    return {
        "journal_entry_id": lines[0].journal_entry_id,
        "date": lines[0].date.isoformat(),
        "lines": [line.to_dict(redact=True) for line in lines],
    }
