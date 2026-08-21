# Plaid integration decisions

## #1 — 2026-08-20 — Bank auth via Plaid Hosted Link + a one-time local CLI command, not custom frontend UI

**Category:** system (technical)
**Status:** accepted
**One-way door:** no
**Related:** #1 (docs/DISTRIBUTION_CHANNEL_DECISIONS.md); #1 (docs/security/MODEL_PROVIDER_SECURITY_DECISIONS.md)

**Short description:** Connecting a bank account uses Plaid's Hosted Link — a Plaid-hosted webpage opened in the user's browser — driven by a one-time local CLI command (e.g. `plaid-link`), rather than any custom frontend UI. The CLI calls `/link/token/create` with Hosted Link enabled and `transactions` as a product, prints/opens the returned URL, and polls `/link/token/get` while the user authenticates with their bank entirely inside Plaid's hosted page. Once that succeeds, the CLI retrieves the `public_token`, exchanges it via `/item/public_token/exchange` for a persistent `access_token` + `item_id`, and stores those in encrypted local storage the MCP server alone can read. From then on, MCP tools call `/transactions/sync` directly using the stored `access_token` — no repeated Link flow unless the bank connection needs re-authentication — and return only filtered/aggregated/minimized results to Claude, never the `access_token` or unrestricted raw transaction dumps.
**Short example:** Running `plaid-link` once opens a Plaid-hosted webpage in the browser where the user logs into their bank; BalanceAI's Expo app is never involved in that step, and never needs to be.

**Grounded facts:**
- [verified] User's explicit technical spec, provided directly in this conversation, modeled on the pattern used by the open-source project t-rhex/plaid-mcp.
- [unverified] Whether t-rhex/plaid-mcp's actual implementation was reviewed directly versus the pattern description being taken as given — not independently checked against that repo in this conversation.
- [verified] `PLAID_CLIENT_ID` / `PLAID_SECRET` / `PLAID_ENV` are already wired into `config.py` as plain, non-KMS-encrypted settings (read from env vars / a local `.env`) earlier in this same session — matches this decision's credential model exactly, no further config.py changes needed for that piece.
- [verified] This resolves the tension raised earlier in this conversation between building Plaid Link UI and `docs/DISTRIBUTION_CHANNEL_DECISIONS.md #1` (Expo frontend work paused for MVP validation) — Hosted Link needs no custom app UI at all, only a browser, so the frontend pause is no longer a blocker for bank connection.
- [verified] Reinforces `docs/security/MODEL_PROVIDER_SECURITY_DECISIONS.md #1` (minimize/redact customer data before it reaches a model provider) — `access_token` is explicitly never passed to Claude as a tool argument or tool result; MCP tools process `/transactions/sync` results locally and return only filtered/aggregated data.
- [unverified] Whether Plaid's Hosted Link product is actually enabled on this account's current Sandbox app configuration has not been confirmed yet — open question carried over from earlier in this conversation about confirming which products are enabled.
- [unverified] Exact local storage mechanism for the encrypted `access_token` (a local SQLite file vs. a protected credentials file) was described as either option in the user's spec — not yet decided which.

## #2 — 2026-08-21 — Expose bank-linking as an MCP tool (`link_bank`), not CLI-only

**Category:** system (technical)
**Status:** accepted
**One-way door:** no
**Related:** #1 (this file, amends the "CLI-only, not an MCP tool" part); #1 (docs/security/MODEL_PROVIDER_SECURITY_DECISIONS.md)

**Short description:** Amends #1: connecting a bank via Plaid Hosted Link is now also exposed as an MCP tool (`link_bank`, in `servers/link_bank_server.py`), not CLI-only. The tool opens a browser and blocks synchronously (up to 5 minutes) while polling `/link/token/get` for completion — the same shape as the CLI's `bank_link/link.py`, which remains available for direct/manual use. The security rationale in #1 for keeping `access_token` out of tool arguments/results is unaffected: the token is written straight to `plaid_item_db` inside the tool and never appears in the tool's return value.
**Short example:** A user chatting with an MCP client can say "connect my Chase account" and the client calls `link_bank()` directly, instead of the user having to leave the chat and run a local CLI command.

**Grounded facts:**
- [verified] User's explicit direction in this conversation to add the MCP tool; when the blocking-tool-call UX concern (a multi-minute call reading as a hang to some MCP clients) was raised, the user said they're not concerned and to proceed as a single blocking call rather than splitting into start/poll tools.
- [verified] `link_bank`'s implementation (`servers/link_bank_server.py`) reuses `bank_link.link.create_hosted_link`/`complete_link` as-is — no change to the underlying Hosted Link handshake logic from #1, only a new caller.
- [verified] The tool's return value (`item_id`, `institution_name`, `accounts_linked`) was checked against #1's and `MODEL_PROVIDER_SECURITY_DECISIONS.md #1`'s constraint that `access_token` must never cross the tool boundary — confirmed via a unit test (`test_omits_access_token_from_result`-style assertion) that the token string doesn't appear anywhere in the result.
