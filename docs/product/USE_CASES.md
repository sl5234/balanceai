# Use cases

What a user does, step by step, and what to expect. Examples are made up.
Each section names the PR that built it and what's still open (BLs in
docs/BACKLOGS.md).

New use cases go under "Not reviewed". Once the user has reviewed one, it
moves to "Reviewed" (BL-24: a test for each).

## Reviewed

None yet.

## Not reviewed

### Receipts and bank transactions for the same purchase (PR #15)

One purchase seen by a receipt and by the bank becomes one transaction,
booked once (BL-15).

- **R1.** *Status: Implemented.*
  User syncs transactions (a $12.50 Blue Bottle charge comes in).
  User uploads the $12.50 Blue Bottle receipt. Expect: they're merged into
  one transaction on upload (`matched_bank_transaction: true`), booked once.
- **R2.** *Status: Implemented.*
  User uploads the $12.50 Blue Bottle receipt. User syncs
  transactions (the charge comes in). Expect: they're merged during the sync
  (counted in `matched`), without asking; booked once.
- **R3.** *Status: Implemented.*
  User syncs transactions (a $48.00 restaurant charge). User uploads
  the $40.00 receipt (before the tip). Expect: merged, since the bank may be
  up to 30% above the receipt. Amount $48.00 from the bank; date paid, tax and
  tip from the receipt.
- **R4.** *Status: Implemented.*
  User uploads a receipt dated Nov 8. User syncs transactions (the
  charge is dated Nov 6 to Nov 15). Expect: merged. Dated Nov 5 or earlier, or
  Nov 16 or later: not merged.
- **R5.** *Status: Implemented.*
  User syncs transactions. User uploads a receipt from another
  merchant, on another card, or a purchase where the bank shows a refund.
  Expect: not merged; both stay as they are.
- **R6.** *Status: Implemented.*
  User uploads two $5.00 coffee receipts. User syncs transactions
  (one $5.00 charge). Expect: nothing merged (ambiguous), logged. Same for one
  receipt and two charges.
- **R7.** *Status: Implemented.*
  User syncs transactions (a $12.50 refund credit). User uploads the
  refund receipt. Expect: merged, like a purchase.
- **R8.** *Status: Implemented (the merge keeps your classification), but a user can't classify by hand yet (BL-10).*
  User syncs transactions. User classifies the charge themselves.
  User uploads its receipt. Expect: merged; their classification is kept and
  flagged for review. With an AI classification instead: it's redone with
  both sources.
- **R9.** *Status: Implemented (a rejected pair isn't merged again), but nothing lets a user reject a pair yet (BL-20).*
  A receipt and a charge were rejected as a pair. User syncs
  transactions. Expect: that pair is never merged again. (No user action
  rejects a pair yet: BL-20.)

Not covered yet (*Status: Not implemented*):
- Choosing or rejecting the match on upload (BL-20).
- Undoing a wrong automatic merge from a sync (BL-20 note: a possible split BL).
- User uploads the same receipt twice: counted twice (BL-19).
- User uploads a statement for an account linked through Plaid: booked twice (BL-23).

### A pending charge posts (PR #15)

- **P1.** *Status: Implemented.*
  User syncs transactions (a pending $12.50 charge). User syncs
  again after it posts as $14.00 with a tip. Expect: the same transaction now
  shows $14.00; its classification and receipt match are kept; booked once.

### Linking a bank that's already linked (PR #15)

Re-linking reuses the existing connection (Plaid update mode) instead of
making a second one. Accounts, transactions and the sync position stay the
same, so nothing is synced twice.

- **L1.** *Status: Implemented.*
  User links Acme Bank. The bank's login expires (or the password
  changes). User syncs transactions. Expect: "Your bank needs you to log in
  again before it can sync." User runs `update_bank_link` and logs in. User
  syncs again. Expect: syncing continues where it left off.
- **L2.** *Status: Implemented.*
  User links Acme Bank. User opens a new account there. User runs
  `update_bank_link(add_accounts=True)` and picks it. User syncs. Expect: the
  new account's transactions come in. (Unpicking an account stops syncing it.)
- **L3.** *Status: Implemented.*
  User links Acme Bank. Months later its consent is close to
  expiring. User runs `update_bank_link` and logs in. Expect: consent renewed.
- **L4.** *Status: Implemented.*
  User links Acme Bank. User asks to link Acme Bank again (it's
  working). Expect: nothing opens; the assistant offers to sync, add or remove
  accounts, or log in again.
- **L5.** *Status: Implemented.*
  User links Acme Bank. Its login breaks. User asks to link Acme Bank.
  Expect: Plaid opens straight away to log in again on the same connection.
- **L6.** *Status: Implemented.*
  User links Acme Bank. The bank is down. User asks to link Acme Bank.
  Expect: nothing opens; told to try again later.
- **L7.** *Status: Implemented.*
  User links Acme Bank. User links again without naming it and picks
  Acme Bank in Plaid. Expect: the new connection is removed at Plaid (not
  saved, not billed); told it was already connected, and to log in again with
  `update_bank_link` if the old one needs it.
- **L8.** *Status: Implemented.*
  User links Acme Bank. User links again with a partner's login at
  Acme Bank (a joint account). Expect: kept as a second connection; its
  accounts differ, so it isn't a duplicate.
- **L9.** *Status: Implemented.*
  User links Acme Bank. The connection is removed at Plaid (e.g. in
  Plaid's portal). User links Acme Bank again. Expect: the new connection
  isn't kept; told reconnecting isn't supported yet. (BL-5 cases 1–2, next.)
- **L10.** *Status: Implemented.*
  User starts linking a bank. User closes the Plaid page, or doesn't
  finish within 5 minutes. Expect: nothing saved; told it was exited or timed
  out.

Not covered yet (*Status: Not implemented*):
- Moving a bank onto a new connection when the old one can't be fixed (BL-5 cases 1–2).
- Unlinking a bank (BL-3), or deleting or archiving an account (BL-21).
- Naming the bank instead of its id in `update_bank_link` and other tools (BL-22).
