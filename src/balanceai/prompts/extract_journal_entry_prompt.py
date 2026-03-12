def extract_journal_entries_prompt(schema: str, merchant_context: str | None = None) -> str:
    context_section = (
        f"\nMerchant context from web search: {merchant_context}\n\n" if merchant_context else ""
    )
    return (
        "You are a bookkeeping assistant. Given a bank transaction, "
        "generate journal entries using double-entry bookkeeping. "
        f"{context_section}"
        f"Return ONLY valid JSON matching this schema:\n{schema}\n\n"
        "Return ONLY valid JSON. No extra text."
    )
