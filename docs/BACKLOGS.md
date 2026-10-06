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

## BL-2 — No way to attach a bank account to a skipped Plaid account

**Added:** 2026-10-04
**Related:** BL-1

**Problem:** A Plaid account skipped at link/sync (unsupported type, no last 4,
or an id clash) has no `BankAccount`, so syncing any of its transactions fails.
There's no tool to create a `BankAccount` for it (with its `plaid_account_id`)
so the sync can proceed.

**Proposed fix:** a tool to create a `BankAccount` for a given Plaid account.

## BL-3 — No way for a user to unlink a bank

**Added:** 2026-10-05

**Problem:** There's no MCP tool or CLI command to remove a linked Plaid item.
`delete_plaid_item` exists in `bank_link/plaid_item_db.py` but only tests call
it, so the only way to unlink today is deleting from the database directly.

**Proposed fix:** an `unlink_bank` tool that calls Plaid's `/item/remove` (so
the access token is revoked, not just forgotten locally) and then deletes the
item.

## BL-4 — Re-linking a bank duplicates its raw transactions

**Added:** 2026-10-05
**Related:** BL-3

**Problem:** Raw transactions are kept when a Plaid item is unlinked (only
`plaid_item_id` is cleared), since a closed account can't be re-fetched and
Plaid only returns ~24 months. But `raw_transactions.id` is Plaid's
`transaction_id`, and a new link issues new ids for the same real purchases —
so the next sync saves them again alongside the old rows.

**Proposed fix (options):**
- Replace: on re-link, delete the account's old Plaid rows for the dates the
  new sync covers; keep older ones.
- Match: our own generated id plus a `plaid_transaction_id` column; match
  incoming transactions to existing rows by account + date + amount +
  description (by count) and update instead of inserting.

## BL-5 — Re-linking an already-linked bank isn't handled correctly

**Added:** 2026-10-05
**Related:** BL-1, BL-3, BL-4

**Problem:** A user may link a bank that's already linked (e.g. the connection
broke and needs a fresh login). Today the new item is saved, all its accounts
are skipped as id clashes, and its sync fails. Re-linking should instead
replace the old connection, which means reconciling three things:

- **Accounts:** the new link's accounts match existing rows by id
  (`institution:type:last4`) and take them over (update `plaid_item_id` /
  `plaid_account_id`). Only an id repeated within one Plaid response is a real
  clash.
- **Plaid item:** every link gets a new `item_id`, so the old item can't be
  matched directly — an old item left with no accounts after the takeover has
  been replaced and should be removed (BL-3).
- **Raw transactions:** the new link issues new transaction ids, so existing
  rows must be matched or replaced rather than saved again (BL-4).

**Proposed fix:** do the three above together; Plaid's "update mode"
(re-authenticating the same item, keeping all ids) is the alternative for the
broken-connection case.
