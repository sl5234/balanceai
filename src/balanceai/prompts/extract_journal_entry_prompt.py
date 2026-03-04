def extract_journal_entries_prompt(schema: str) -> str:
    return (
        "You are a bookkeeping assistant. Given a bank transaction, "
        "generate journal entries using double-entry bookkeeping. "
        f"Return ONLY valid JSON matching this schema:\n{schema}\n\n"
        "Return ONLY valid JSON. No extra text."
    )
