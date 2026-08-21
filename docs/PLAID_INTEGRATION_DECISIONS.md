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
