# Backend decisions

## #1 — 2026-08-20 — External SDK clients use lazy, memoized construction via `functools.lru_cache`, co-located with their service

**Category:** system (technical)
**Status:** accepted
**One-way door:** no
**Related:** #1 (docs/PLAID_INTEGRATION_DECISIONS.md)

**Short description:** Going forward, external SDK clients (Plaid, and any future provider) are constructed lazily and memoized with `functools.lru_cache()` (or `functools.cache`) on a zero-arg factory function — first call builds and caches the client, later calls reuse it — rather than a hand-rolled `global`/`None`-check singleton. The factory stays co-located with the service module that uses it (e.g. `get_plaid_client()` inside `services/plaid.py`), not centralized in a shared client registry — the number of single-purpose external APIs in this codebase doesn't yet justify that extra layer of indirection.

**Short example:** `get_plaid_client()` in `services/plaid.py`, decorated with `@lru_cache`, replacing the "rebuild every call" style used by the existing Tavily/Gemini/OpenAI/Anthropic services.

**Grounded facts:**
- [verified] Existing codebase already has two inconsistent client-construction patterns: `AWSClients` (`dagger/aws.py`) is eager-initialized at server import and cached via explicit `initialize()`/getter methods; the Gemini/OpenAI/Anthropic/Tavily services each build a brand-new SDK client on every call, with no caching.
- [verified] `AWSClients` lives in its own module separate from any one service because it's a shared bootstrap dependency `config.py` itself needs (to KMS-decrypt the other providers' API keys) before those providers' clients can even be built — not because "separate client module" is the general house style.
- [verified] Gemini/OpenAI/Anthropic/Tavily each construct their client inline inside their own `services/<provider>.py` file (`services/gemini.py:19`, `services/openai.py:37`, `services/anthropic.py:33`, `services/tavily.py:6`), not in a separate client module.
- [unverified] User's stated preference: the ideal pattern is "call whenever the client is needed; first call initializes, subsequent calls skip initialization and reuse" — i.e. lazy + memoized, not eager-at-import like AWS and not rebuild-per-call like the other four services.
- [unverified] Agreed in conversation: `functools.lru_cache()` on a zero-arg factory function is the idiomatic mechanism for this, preferred over hand-rolling a module-level `global`/`None`-check singleton.
- [unverified] Agreed in conversation: with only a handful of single-purpose external APIs in this codebase, per-service co-location (client-getter next to the service that uses it) beats a central client registry — the registry's main benefit (one seam for testing/mocking, one consistent pattern) doesn't yet outweigh the added indirection for what's often a few lines of setup per provider.
