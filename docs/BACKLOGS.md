# Backlogs

Deferred engineering work. Code that's affected carries a `TODO` pointing back
to the entry by its id.

## BL-1 — Bank account id doesn't follow changed last 4 / type / institution

**Added:** 2026-10-04
**Related:** docs/PLAID_INTEGRATION_DECISIONS.md #3

**Problem:** A `BankAccount` id is `<institution>:<account_type>:<last4>`. If any
of those change for an account we've already saved (e.g. a reissued credit
card), the next Plaid link/sync builds a different id for the same
`plaid_account_id`. The `UNIQUE` constraint on `plaid_account_id` rejects it, so
the account is reported under `skipped` and keeps its stale values.

**Proposed fix:** either rename the account to the new id with `ON UPDATE CASCADE`
on every column referencing it, or switch the id to a UUID and match Plaid
accounts by `plaid_account_id` (which avoids id changes altogether).
