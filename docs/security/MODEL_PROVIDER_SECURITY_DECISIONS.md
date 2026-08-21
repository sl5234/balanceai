# Model provider security decisions

## #1 — 2026-08-19 — Redact/minimize customer financial data before sending to model providers

**Category:** system (technical)
**Status:** accepted
**One-way door:** no

**Short description:** Before any customer data reaches a model provider's API, strip it down to the minimum needed for that specific call — never send SSNs, account numbers, Plaid access tokens, or other identifiers the model doesn't need to answer the question.
**Short example:** For "how much did I spend on coffee?", send `Starbucks | $8.72 | Aug 19` — not the full account record it was pulled from.

**Grounded facts:**
- [verified, resolved 2026-08-21] `servers/link_bank_server.py`'s old `list_transactions` tool passed the raw Plaid `access_token` as a direct MCP tool parameter — visible in tool-call arguments to any LLM client invoking it. Replaced with `list_linked_banks` / `sync_bank_transactions` / `get_bank_transactions`, all scoped to `item_id`; the access token is looked up server-side from `bank_link/plaid_item_db.py` and never crosses the tool boundary.
- [verified] `servers/bookkeeping_server.py:410-437` logs the full `user_message`, `system_prompt`, and LLM-generated `sql` for every `analyze_financial_question` call to a local DEBUG-level file handler (`logs/bookkeeping_server.log`) — recipient names, categories, and amounts land in plaintext on disk regardless of the model provider's own data handling.
- [verified] Existing partial redaction already exists in the codebase (`redact` / `redact_entries` flags on `list_journals` / `list_journal_entries` in `models/journal.py`), but it's inconsistently applied — `analyze_financial_question`, `get_transactions`, and `list_transactions` return unredacted data today.

## #2 — 2026-08-19 — Self-hosted/dedicated inference (local vLLM, own-purchased GPUs) rejected

**Category:** system (technical)
**Status:** rejected
**One-way door:** no
**Related:** #3

**Short description:** Explicitly will not stand up a local vLLM server, serverless self-hosted inference, or GPU machines purchased/owned by BalanceAI to run model inference — even though this would be the architecture required for "customer data may never enter another company's infrastructure."
**Short example:** No GPU procurement, no vLLM deployment, no dedicated-inference roadmap item — model calls stay on Anthropic/Google/OpenAI's shared infrastructure.

**Grounded facts:**
- [verified] User's explicit statement rejecting this path, made directly in this conversation, not derived from any technical blocker — self-hosting is feasible in principle, just not the chosen direction.
- [verified] The codebase already calls Anthropic, Gemini, and OpenAI exclusively via their hosted SDKs/APIs (`services/anthropic.py`, `services/gemini.py`, `services/openai.py`) — there is no self-hosted inference code anywhere in the repo today, so this rejection matches existing practice rather than reversing it.

## #3 — 2026-08-19 — Trust model providers' multi-tenant inference isolation as the security boundary, based on their business incentive to secure it

**Category:** system (technical)
**Status:** accepted
**One-way door:** no
**Related:** #2

**Short description:** BalanceAI will treat OpenAI's and Anthropic's (and other model providers') multi-tenant inference isolation (token buffers, KV caches, output buffers, batching state, GPU memory, request routing) as a trusted security boundary, rather than building any BalanceAI-side control for it. The trust isn't in an unverified technical claim about isolation strength — it's that these providers have enough business/reputational interest at stake to make their inference engines secure, and BalanceAI is choosing to trust that incentive alignment.
**Short example:** If Alice and Bob's requests happen to land on the same shared GPU/batch at a model provider, BalanceAI relies on that provider's own isolation guarantees — not because those guarantees have been independently audited, but because a provider like OpenAI or Anthropic has too much to lose (reputationally and commercially) to get multi-tenant isolation wrong.

**Grounded facts:**
- [verified] User's explicit correction of an earlier draft of this entry: the trust isn't "these providers provide sufficiently strong multi-tenant isolation, taken as given" — it's "there is enough interest for model providers to make their inference engine secure, so I trust the system and the interest/business model" behind it.
- [verified] This project currently has no multi-tenant customer data model at all (`models/account.py`, `models/journal.py`, `models/transaction.py` have no `user_id`/tenant field) — so this trust boundary isn't load-bearing yet, but becomes relevant once/if BalanceAI serves more than one customer's data through a shared backend.

## #4 — 2026-08-19 — ChatGPT Custom Plugin path stays accepted, gated on a security re-review before shipping

**Category:** system (technical)
**Status:** accepted
**One-way door:** no
**Related:** #1 (this repo); #7, #10 (docs/DISTRIBUTION_CHANNEL_DECISIONS.md)

**Short description:** The ChatGPT Custom Plugin integration path (accepted in DISTRIBUTION_CHANNEL_DECISIONS.md #7) remains the plan for a future distribution phase, but revisiting it must include an explicit security review — specifically comparing whether a more-secure or less-secure alternative exists at that time — rather than defaulting back to the original #7 decision unexamined.
**Short example:** When this is revisited, the redaction work from #1 and the "backend as security authority, not the LLM" principle both need to be re-checked against whatever ChatGPT's plugin/connector security model looks like at that point, not assumed to still match today's understanding.

**Grounded facts:**
- [verified] User's explicit statement in this conversation: still planning to use the ChatGPT Custom Plugin in the future, but wants extra security scrutiny — including a more-secure-vs-less-secure alternatives comparison — when that decision is revisited.
- [verified] DISTRIBUTION_CHANNEL_DECISIONS.md #7 already flagged two unresolved risks when ChatGPT Custom Plugin was first accepted: customer trust in OpenAI with financial data, and whether OpenAI's usage policies even permit processing financial-sensitive data (e.g. receipt OCR) through GPT models — neither has been resolved since.
