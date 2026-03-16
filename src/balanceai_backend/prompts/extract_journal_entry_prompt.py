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


_DOUBLE_ENTRY_RULES = """\
## DOUBLE-ENTRY BOOKKEEPING RULES:
1. Every transaction must produce at least two journal entries where total debits equal total credits.
2. Each journal entry line represents ONE side of the transaction — never put both a debit and a credit amount on the same line (one must always be 0).
3. Assign each line a single account type. Two lines in the same transaction must NOT both use an expense account (essential_expense or non_essential_expense) — one side must reflect the actual account the money moved through (e.g. cash, accounts_payable, accounts_receivable).
5. When the merchant is ambiguous, default to non_essential_expense (not essential_expense).
6. Validate before returning:
   - total debits == total credits
   - every account type is one of the valid enum values
   - no line has both debit > 0 and credit > 0 
"""

_EXAMPLES = """\
## EXAMPLES:

Transaction: Trader Joe's (grocery store) -$45.00
Journal entries:
  - debit: 45.00, credit: 0.00, account: essential_expense, description: "Grocery purchase from Trader Joe's."
  - debit: 0.00, credit: 45.00, account: cash, description: "Grocery purchase from Trader Joe's."

Transaction: Bilt Eqr (rent) -$1,200.00
Journal entries:
  - debit: 1200.00, credit: 0.00, account: rent, description: "Monthly rent payment."
  - debit: 0.00, credit: 1200.00, account: cash, description: "Monthly rent payment."

Transaction: Payroll $2,500.00
Journal entries:
  - debit: 2500.00, credit: 0.00, account: cash, description: "Payroll deposit."
  - debit: 0.00, credit: 2500.00, account: sales, description: "Payroll deposit."

Transaction: Rudy's (unknown merchant) -$30.00
Journal entries:
  - debit: 30.00, credit: 0.00, account: non_essential_expense, description: "Uncategorized transaction from Rudy's."
  - debit: 0.00, credit: 30.00, account: cash, description: "Uncategorized transaction from Rudy's."

Transaction: Amazon.com $15.00
Journal entries:
  - debit: 15.00, credit: 0.00, account: cash, description: "Refund from Amazon.com."
  - debit: 0.00, credit: 15.00, account: non_essential_expense, description: "Purchase from Amazon.com."     
"""

def extract_journal_entries_prompt(schema: str, merchant_context: str | None = None) -> str:
    context_section = (
        f"\nMerchant context from web search: {merchant_context}\n\n" if merchant_context else ""
    )
    return (
        "You are a bookkeeping assistant. Given a bank transaction, "
        "generate journal entries using double-entry bookkeeping.\n\n"
        f"{_DOUBLE_ENTRY_RULES}\n\n"
        f"## CONTEXT\n\n{context_section}\n\n"
        f"{_EXAMPLES}\n\n"
        f"Return ONLY valid JSON matching this schema:\n{schema}\n\n"
        "Return ONLY valid JSON. No extra text."
    )
