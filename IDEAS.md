# Ideas

## Questions Customers Might Ask

### Spending & Income
- How much did I spend in the last X days/weeks/months? ✅
- How much did I spend on [category]? ✅
- How much did I spend at [merchant]? ✅
- What are my biggest expenses this month? ✅
- How has my spending changed over time?
- How much income did I receive in the last X period?
- What are my recurring expenses?

### Behavioral & Patterns
- Am I spending more or less than usual?
- What categories are increasing the fastest?
- What transactions are unusual or anomalous?
- What new types of spending appeared recently?
- What subscriptions am I not using?
- What habits are driving my spending?

### Cash Flow & Liquidity
- How much cash do I have right now?
- What is my current burn rate?
- How long will my cash last?
- What is my net cash flow over time?
- When do I typically run low on cash?
- What upcoming payments or obligations do I have?

### Profitability (Business)
- What is my profit this month?
- What are my total revenues and expenses?
- What is my gross margin / net margin?
- What are my highest-cost areas?
- Which products or customers are most profitable?
- How much am I spending to generate revenue?

### Balance Sheet & Accounts
- What are my current account balances?
- What is my net worth?
- What changed in my balance sheet over time?
- How much do I owe right now?
- Where is my money allocated (cash vs investments vs liabilities)?

### Transaction Explainability
- Why did my balance drop last week?
- What transactions contributed to this number?
- What caused this spike in spending?
- Show me all transactions for [category/merchant/time]
- Break down this category into individual transactions

### Forecasting & What-If
- If I continue this spending, where will I be in X months?
- Can I afford this purchase?
- What will my balance be after upcoming bills?
- What happens if I reduce spending on [category]?
- How will my cash position change over time?

### Tax & Compliance
- How much did I spend on tax-deductible expenses?
- What are my business vs personal expenses?
- How much do I owe in estimated taxes?
- What transactions need categorization for taxes?

### Data Quality & Reconciliation
- Are all transactions accounted for?
- Are there duplicates?
- What transactions are uncategorized?
- Do my books reconcile with my bank?
- What entries look incorrect?

### Advanced / Power Queries
- Show transactions where amount > X
- Show transactions between date A and B
- Group spending by [category/merchant/account]
- Compare two time periods
- Aggregate by [dimension] over time

---

## Schema & Layers Summary

### Layer 1: Raw Source Data
- **`raw_financial_events`**
- Stores original bank/receipt/API payloads (JSON)
- Purpose: auditability, replay, deduplication

### Layer 2: Normalized Transactions
- **`financial_transactions`**
- Cleaned, standardized representation of external transactions
- Includes amount, date, merchant, account, status
- Purpose: ingestion, categorization, user-facing transaction list

### Layer 3: Ledger (Core Accounting)
- **`journals`**, **`journal_lines`** (postings)
- Represents true double-entry records
- Enforces: total debits = total credits
- Purpose: canonical financial truth

### Layer 4: Chart of Accounts
- **`accounts`**
- Defines asset, liability, equity, revenue, expense structure
- Supports hierarchy (parent/child accounts)
- Purpose: categorization and financial structure

### Layer 5: Dimensions & Metadata
- **`merchants`**, **`entities`**, **`tags`**, **`projects`**
- Optional enrichment tables
- Purpose: flexible grouping, filtering, attribution

### Layer 6: Derived / Analytics Layer
- SQL views (e.g., `posting_facts`)
- Materialized summaries (daily, monthly aggregates)
- Purpose: fast querying, dashboards, reporting

### Query Flow
- Natural language → structured query spec → SQL over ledger (`journal_lines` + `accounts`)
- Source of truth: ledger layer
- Supporting context: transactions + dimensions

---

## Lending & Borrowing (Loan Ledger)

Users manually tag transactions as **lending** (money out, expect repayment) or **borrowing** (money in, owe repayment), with a named counterparty (e.g. "Alice"). These are stored in a loan ledger separate from journal entries. When processing new transactions, open loan records are passed as LLM context so it can automatically detect and match repayments — presenting the user with candidates (by counterparty and remaining balance) to confirm rather than blindly auto-settling. Partial repayments should be supported, keeping the loan open with an updated remaining balance.
