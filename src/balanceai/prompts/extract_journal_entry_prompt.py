def categorize_journal_entry_prompt(schema: str, merchant_context: str) -> str:
    return (
        "You are a bookkeeping assistant. Given a journal entry with unknown category and merchant context "
        "from web search, return the same journal entry with the correct category filled in. "
        f"Merchant context: {merchant_context}\n\n"
        "For the 'category' field, assign a short label when the merchant or transaction type is clear; "
        "use null only when the merchant cannot be identified even with the provided context.\n\n"
        f"Return ONLY valid JSON matching this schema:\n{schema}\n\n"
        "Return ONLY valid JSON. No extra text."
    )


def extract_journal_entries_prompt(schema: str, merchant_context: str | None = None) -> str:
    context_section = (
        f"\nMerchant context from web search: {merchant_context}\n\n" if merchant_context else ""
    )
    return (
        "You are a bookkeeping assistant. Given a bank transaction, "
        "generate journal entries using double-entry bookkeeping. "
        f"{context_section}"
        "For the 'category' field, assign a short label when the merchant or transaction type is clear; "
        "use null only when the merchant cannot be identified from the description alone.\n\n"
        f"Return ONLY valid JSON matching this schema:\n{schema}\n\n"
        "Return ONLY valid JSON. No extra text."
    )
