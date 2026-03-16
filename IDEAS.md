# Ideas

## Lending & Borrowing (Loan Ledger)

Users manually tag transactions as **lending** (money out, expect repayment) or **borrowing** (money in, owe repayment), with a named counterparty (e.g. "Alice"). These are stored in a loan ledger separate from journal entries. When processing new transactions, open loan records are passed as LLM context so it can automatically detect and match repayments — presenting the user with candidates (by counterparty and remaining balance) to confirm rather than blindly auto-settling. Partial repayments should be supported, keeping the loan open with an updated remaining balance.
