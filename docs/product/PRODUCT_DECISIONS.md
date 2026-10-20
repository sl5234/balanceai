# Product decisions

## #1 — 2026-10-11 — Users work with transactions, not journal entries

**Category:** product
**Status:** accepted
**One-way door:** no
**Related:** #2; #2 (docs/BACKEND_IMPLEMENTATION_DECISIONS.md)

**Short description:** Bookkeeping is fully managed. Users bring in transactions (from Plaid, receipts, or bank statements) and can correct how a transaction is classified. They never create, edit, or delete journal entries — the system produces those. Why: the product does the bookkeeping for the user rather than asking them to know double-entry. Cost: a user who does know bookkeeping can't adjust the books directly.
**Short example:** A dinner is booked as groceries. The user changes the transaction's category to dining; the journal entries behind it update on their own.

**Grounded facts:**
- [verified] User's product call in this conversation.

## #2 — 2026-10-11 — Letting users edit journal entries directly

**Category:** product
**Status:** rejected
**One-way door:** no
**Related:** #1; #3 (docs/BACKEND_IMPLEMENTATION_DECISIONS.md)

**Short description:** Rejected in favor of #1: exposing journal entries for users to create and edit. That suits a product that teaches people bookkeeping by having them work with debits and credits, which is not the product we're building.
**Short example:** To fix a dinner booked as groceries, the user would change the account on one line and the category on both, keeping the lines balanced themselves.

**Grounded facts:**
- [verified] User's product call in this conversation.
