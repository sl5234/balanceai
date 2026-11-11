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

**Update 2026-11-11:** rows now have our own id and Plaid's in
`plaid_transaction_id` (BL-16). What's left is matching a re-link's new Plaid
ids to existing rows, part of BL-5.

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

**Update 2026-11-10 — hit in practice, blocks syncing:** re-linking Chase made
the new connection's checking account clash with the existing
`chase:checking:<last4>` row (still tied to the old Plaid account id), so the
account was skipped and the sync saved no raw transactions. Fixing only the
account would re-save every transaction under new ids (BL-4), so do all three
together. Priority: right after the receipt manual test.

## BL-6 — Skill for the end-to-end Plaid flow

**Added:** 2026-10-06

**Problem:** Going from a bank to journal entries takes several separate tool
calls across two MCP servers, with choices in between (which journal, which
accounts), and nothing ties them together.

**Proposed fix:** a skill that runs the whole flow: link bank → sync bank
transactions → create or pick a journal → sync journal entries.

## BL-7 — Classification runs inside the sync call

**Added:** 2026-10-13
**Related:** docs/DISTRIBUTION_CHANNEL_DECISIONS.md #11

**Problem:** `sync_bank_transactions` classifies every unclassified
transaction before returning. A first sync with a lot of history means one
long tool call that a client may time out, and on a remote server work
shouldn't outlive the request.

**Proposed fix:** event-driven syncing (Plaid webhook → queue → workers) or a
workflow engine running sync → classify → book with built-in retries. The
classify function is already a self-contained, safe-to-repeat unit of work,
so only its trigger changes.

## BL-8 — Plaid's original transaction payload isn't kept

**Added:** 2026-10-13

**Problem:** A raw transaction keeps only the fields we map from Plaid; the rest
of Plaid's response (counterparties, location, payment details, …) is dropped,
so nothing can be re-derived from it later.

**Proposed fix:** store Plaid's full transaction JSON alongside the raw
transaction (and the file path for receipts and statements).

## BL-9 — Old journal logic still uses the old accounts and rules

**Added:** 2026-10-26
**Related:** docs/BACKEND_IMPLEMENTATION_DECISIONS.md #2

**Problem:** Journal entries are now generated by rule from classified raw
transactions (`raw_transactions/generate_journal_entry.py`), against the
personal account list. Older code that reads or writes journal entries still
assumes the earlier accounts and conventions (e.g. spending as cash credits,
`counterparty` (was `recipient`) = "Self" on one side), so it will misread or
mis-write entries booked the new way:

- `prompts/report_definition_prompt.py` (`create_report_definition`), which
  writes SQL over `journal_lines`. (`prompts/financial_query_prompt.py` was
  rewritten for the new booking on 2026-11-03.)
- The LLM entry tools — `sync_journal_entries_from_transactions` and
  `_from_bank_statement` — with `GeneratedJournalLine`'s field descriptions and
  `prompts/extract_journal_entry_prompt.py`. `GeneratedJournalLine.counterparty`'s
  description still teaches "Self" on the expense side and the merchant on the
  other; booking puts the same counterparty on both lines. `db/journal_db.py`'s
  `update_journal` still replaces every entry because they save through it.

(Receipts moved to the new flow on 2026-11-09: `upload_receipt` makes a raw
transaction and books it; BACKEND_IMPLEMENTATION_DECISIONS.md #18.)

**Proposed fix:** rewire each onto the new accounts and rules, or retire it —
the Plaid tool is replaced by booking classified raw transactions; receipts and
statements could become raw transactions too.

## BL-10 — Users can't correct classifications or set override rules

**Added:** 2026-11-04
**Related:** BL-9; docs/BACKEND_IMPLEMENTATION_DECISIONS.md #17

**Problem:** Users fix bookkeeping by correcting a raw transaction's
classification, not by editing entries (decision #17), but none of that path
exists:

- No tool sets a user classification. `ClassifiedBy.USER` exists and is kept
  across syncs (flagged `needs_user_review` if the source changes) and reused
  for matching transactions, but nothing creates one.
  (`categorize_transaction` is an old tool on the legacy `Transaction` model.)
- `needs_user_review` is set but nothing lists or resolves it.
- No way to say "always classify transactions like this as …".

**Direction so far:**

1. Correct one raw transaction → rewrite its own journal lines (found by
   `raw_transaction_id`); journals pick it up since they're read from
   `journal_lines`. Later similar transactions follow the correction.
2. Override rules as natural-language context from the user, e.g. "whenever
   ~$13.50 goes out to Foo Store, it's my lunch — classify it as dining".
   Rules are passed to the classification AI call with the transactions.
   When a rule clearly matches a recurring transaction (same description,
   amount, direction), apply it without an AI call. Rules apply to new
   transactions only; booked entries aren't rewritten.

**To decide (deep dive):** which wins when a correction and a rule disagree;
matched transfers (reclassifying one side splits the pair); how review of
`needs_user_review` works. For natural-language rules: the AI no longer gets
amounts (only direction), so rules that mention an amount need the amount
sent again for matching transactions, or matched locally first; which rules
go into each call (all, or only ones relevant to the batch); how users list
and edit rules across sessions (stored in the DB, listing asks before sharing).

**Update 2026-11-04 — rules are free-form text, applied by the backend:**

- A rule is any free-form text from the user, e.g. "$13.50 at Foo Store on
  Tuesdays is lunch — classify as dining" or "Zelle to Jane is rent". It can
  mention merchant, amount or range, day or date, account, direction, and set
  the account, category or counterparty.
- Rejected: a Claude Code skill or MD file that the assistant reads and applies
  before calling an MCP tool. The assistant would have to see every
  transaction's description, amount and date on every sync (raw data through
  the assistant), and a skill only works in Claude Code, not other MCP clients.
- Chosen direction: rules are stored server-side (DB, or a file in the secrets
  folder) and included in the backend's classification AI call with the
  transactions. Data goes only where classification already sends it, and
  every sync applies the rules.
- Contradictions are checked when a rule is added: `add_classification_rule`
  makes one AI call comparing the new rule with existing ones and returns
  conflicts or overlaps for the user to resolve (replace, keep both, reword).
  Listing rules asks before sharing.
- Open: rules about amounts, dates or weekdays need the AI to see the amount
  and date again (removed on 2026-11-04). Options: send them only when rules
  exist, or send day of week and a rounded amount instead.

**Update 2026-11-05 — person-to-person payments need the user's intent:**

- Zelle, Venmo, Cash App and PayPal payments to or from a person go to
  `unclassified`, always flagged for review. One payment can be a loan, a loan
  repaid, a refund, rent, or a purchase from a person (e.g. used furniture),
  and nothing in the data tells them apart.
- Only the user knows the intent, so review is how these get resolved: list the
  flagged transactions, the user says what each was (e.g. "loan repaid" ->
  `loans_receivable`), and the correction rewrites its journal lines.
  Recurring ones become rules ("Zelle to Jane is rent").
- A loan repaid only balances if the loan itself was booked to
  `loans_receivable`, so both legs may need correcting.
- Zelle memos ("for couch") would help, but Plaid usually doesn't return them;
  the user supplies that context.
- Transactions classified before `unclassified` existed (e.g. a repayment
  booked as `other_income`) aren't reclassified by a sync; they need a
  correction or a one-off reclassify.

**Priority:** do this right after the current pass of fixing classifications
on real transactions, before the next sync.

## BL-11 — Refunds aren't linked to their purchases

**Added:** 2026-11-05
**Related:** BL-10; docs/BACKEND_IMPLEMENTATION_DECISIONS.md #5, #12

**Problem:** A refund is classified on its own, so the AI guesses its account
and category from the description and direction alone (and can get it wrong,
e.g. `other_income`). Nothing links it to the purchase it reverses, so there's
no way to see a purchase's cost after refunds. Plaid gives no such link.

**Proposed fix:** link a refund to its purchase, like transfer matching
(`raw_transactions/match_transfers.py`), but without merging entries: a refund
is its own event and stays its own entry, booked as a credit to the purchase's
expense account. Store the link on the refund (e.g. `refund_of` on
`raw_transactions`) and copy the purchase's counter account and category.

- Candidates: same bank account, same normalized counterparty, money in dated
  after the purchase and within N days (e.g. 90), amount equal to or less than
  the purchase (partial refunds).
- Several candidates: link the one exact amount match if there's exactly one;
  otherwise don't link (like transfer ties, decision #12).
- Limits: one refund for several items, or several partial refunds, won't
  match by amount.
- Later: list purchases still waiting on a refund; let a user correction
  (BL-10) set or clear the link.

## BL-12 — analyze's failures don't say what's missing from the question

**Added:** 2026-11-05
**Related:** SBL-1

**Problem:** When analyze can't answer, the assistant gets one of a few fixed
messages (a rejection, or "Couldn't answer this question"). They don't say
what to change, e.g. which period, or which merchant was meant.

**Proposed fix:**
- A `needs_clarification` rejection with a question back to the user (e.g.
  "Which period: October, or the last 30 days?"), written by the SQL model.
  It runs before any SQL, so nothing can leak.
- Plain messages per error type (e.g. no matching transactions vs. a broken
  query), chosen from the error's type, never its text.
- One automatic retry that gives the SQL model the error type, not the text:
  the text can contain journal data, and the SQL model's calls go to Anthropic.
- Narrow the `technical_query` rule if everyday words that are also column
  names (category, account, description) cause false rejections.

## BL-13 — Some spending lines get no category

**Added:** 2026-11-08
**Related:** BL-10; ROADMAP #3 (Ollama for classification)

**Problem:** Booking sometimes puts a transaction on an expense account but
leaves its category empty, so analyze's category answers show it as null
("Uncategorized"). Example: a restaurant charge booked to
non_essential_expense with category null. Cause not checked yet.

**Proposed fix:** require a category on every expense line when classifying
(fall back to the closest default category, or book to 'unclassified' for
review). Handle it in the Ollama classification work.


## BL-14 — No tools to manage bank accounts outside Plaid

**Added:** 2026-11-10
**Related:** BL-1, BL-9; BACKEND_IMPLEMENTATION_DECISIONS.md #18

**Problem:** `create_account` and `list_accounts` use the legacy `Account`
store, not the `bank_accounts` table that journals, booking and receipts use.
An account not linked through Plaid (e.g. a debit card used only on receipts)
can't be added, so `upload_receipt` can't book to it.

**Proposed fix:**
- `create_bank_account(institution_name, account_type, last4, display_name?)`
- `list_bank_accounts()`: lists all accounts (drop the "Plaid only" wording).
- `update_bank_account(id, display_name)`: rename only; changing institution,
  type or last 4 changes the id (BL-1).
- `delete_bank_account(id)`: only if no transactions use it and it's in no
  journal; otherwise raise and say why.
- Legacy `create_account` / `list_accounts` stay until roadmap step 7.

**Priority:** right after BL-5.

## BL-15 — Receipts and Plaid transactions for the same purchase aren't matched

**Added:** 2026-11-10
**Related:** BACKEND_IMPLEMENTATION_DECISIONS.md #18; BL-4, BL-5

**Problem:** A card receipt and the Plaid charge for the same purchase are both
booked, so the purchase counts twice. Example (made up): a receipt "Blue Bottle
Coffee Roasters", 2026-10-24, −12.50 on a card, and Plaid's "Blue Bottle
Coffee", 2026-10-25, −12.50 on the same card.

**Proposed fix:** match both ways — on receipt upload (against Plaid rows) and
on every Plaid sync (against receipts) — so arrival order doesn't matter. The
receipt wins (#18): the Plaid row is linked to it (e.g. a `receipt_id` column)
and not booked; if already booked, its entry is removed. v1 rules (no AI):
- same account;
- amount: exact; for dining, the charge may be up to 30% above the receipt (tip);
- date: Plaid date from 2 days before to 7 days after the receipt date;
- merchant: normalized names where one contains the other, or the first word
  matches (e.g. "blue bottle coffee roasters" / "blue bottle coffee");
- exactly one candidate, else leave unmatched and log it.

Uses the separate ids from BL-16.

- Also catch a receipt uploaded twice (raw transaction ids are random now, so
  re-uploading makes a second row).
- Open: pending → posted. Plaid removes the pending transaction and adds the
  posted one under a new id, so a receipt matched to the pending row would lose
  its link and the posted row would be booked again. Likely fix: when an added
  transaction's `pending_transaction_id` matches a stored row, update that row
  (new `plaid_transaction_id`, amount, date) and keep our id, classification
  and receipt link; the later "removed" then finds nothing. To check: whether
  every institution sets `pending_transaction_id`, and posted rows whose
  pending one we never saw.

**Priority:** right after the first round of receipt testing.

## BL-16 — Raw transactions use Plaid's id as their own id (and its column is `id`)

**Added:** 2026-11-10
**Related:** BL-4, BL-5, BL-15, BL-17 (merged in)
**Status:** fixed 2026-11-11 (DB wiped and re-synced, no migration)

**Problem:** A Plaid row's `raw_transactions.id` is Plaid's `transaction_id`;
a receipt's is our own hash. So ids have two formats, and a re-link (new Plaid
ids for the same purchases) can't keep the same row.

**Proposed fix:** every raw transaction gets our own generated id; Plaid's id
moves to a `plaid_transaction_id` column (unique, null for other sources).
Plaid sync finds rows by `plaid_transaction_id` for added / modified / removed.
`journal_lines.raw_transaction_id` keeps pointing at our id. A re-link then
updates `plaid_transaction_id` on the matched row instead of adding a new one
(BL-4, BL-5). Existing data: `journal_lines.raw_transaction_id` (plain text,
no foreign key) still holds the old Plaid ids, so a migration must rewrite it
to the new ids along with `raw_transactions.id`; or wipe the DB and rebook,
since booking rebuilds every line from raw transactions.

Also rename `raw_transactions.id` → `raw_transaction_id` (and `RawTransaction.id`),
so the name matches `journal_lines.raw_transaction_id` (was BL-17).

**Fix (2026-11-11):** `raw_transaction_id` is ours (UniqueIdGenerator) for every
source; Plaid's id is in `plaid_transaction_id`, and Plaid sync finds rows by
it (`upsert_raw_transaction` keeps the stored id; `removed` deletes by Plaid
id). The server stops on a database from before this change and asks to wipe
it.

## BL-17 — Rename raw_transactions.id to raw_transaction_id

Merged into BL-16 (2026-11-11).

## BL-18 — Tables don't record when rows were created or last changed

**Added:** 2026-11-10
**Related:** BL-16, BL-17
**Status:** fixed 2026-11-11 (DB columns and models)

**Problem:** Only `journals`, `plaid_items` and `report_definitions` have
`created_at`, and no table has `updated_at`. `raw_transactions`,
`journal_lines`, `bank_accounts`, `journal_bank_accounts` and
`plaid_sync_cursors` have neither, so there's no way to tell when a
transaction arrived, was reclassified, or when an entry was booked.

**Proposed fix:** `created_at` and `updated_at` (UTC ISO 8601 text) on every
table. Set both on insert; on update, change only `updated_at` (upserts must
keep the original `created_at` on conflict). SQLite can't add a column with a
`CURRENT_TIMESTAMP` default to an existing table, so set them in code (or with
triggers). Existing rows: null, or do it in the same migration / DB wipe as
BL-16.
