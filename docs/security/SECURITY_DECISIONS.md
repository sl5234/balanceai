# Security decisions

<!-- INSTRUCTIONS: Keep entries concise, but with enough detail to understand the decision on its own later. Prefer a concrete example over explanation. Keep grounded facts to the few that drove the decision; leave out supporting detail. -->

General security decisions. Decisions about model providers are in
`MODEL_PROVIDER_SECURITY_DECISIONS.md`.

## #1 — 2026-11-08 — Full redaction of analyze's rows deprioritized

**Category:** system (technical)
**Status:** deprioritized
**One-way door:** no
**Related:** #2; SBL-5

**Short description:** After consent, analyze returns rows without a pass that
replaces all text (keeping only numbers, dates, accounts and categories). That
pass would need a `redact=False` opt-out for questions that need names.
**Short example:** "My 5 biggest expenses" →
`{"merchant": "[redacted]", "amount": 412.00, "date": "2025-10-03"}`: safe, but
you can't tell what the expense was, so most merchant questions would need the
opt-out.

**Grounded facts:**
- [verified] The AI names the result columns, so redaction would have to go by
  value, not column name.
- [verified] User: good idea, too complicated for now.

## #2 — 2026-11-08 — Hide raw bank descriptions in analyze's rows, outside the AI

**Category:** system (technical)
**Status:** accepted
**One-way door:** no
**Related:** #1, #3; SBL-5

**Short description:** After consent, the server replaces any value that
exactly matches a journal line's description with "[hidden description]",
whatever the column is called. A description that's also a counterparty is
kept, since it's the merchant's name, which is shared anyway
(`_hide_descriptions` in `servers/bookkeeping_server.py`).
**Short example:**
`{"d": "SQ *BLUE BOTTLE 0423 OAKLAND", "counterparty": "Blue Bottle Coffee"}` →
`{"d": "[hidden description]", "counterparty": "Blue Bottle Coffee"}`.
`"Shell"` is both a description and a counterparty, so it's kept.

**Grounded facts:**
- [verified] Descriptions are the bank's raw text (card digits, city, reference
  numbers), and for Plaid often equal the counterparty.
- [verified] Exact matches only: `lower(description)` or `substr(...)` get
  through. Consent (SBL-6) is the guard against unusual queries.

## #3 — 2026-11-08 — Prompt rule against selecting description rejected

**Category:** system (technical)
**Status:** rejected
**One-way door:** no
**Related:** #2

**Short description:** The SQL model's prompt doesn't forbid selecting or
filtering on description; hiding happens after the query instead (#2).
**Short example:** "Which purchases mention OAKLAND?" can still filter on
description; the description itself comes back hidden.

**Grounded facts:**
- [verified] A prompt rule is a request to the AI, not a guarantee.
- [unverified] Queries may need description for uses not known yet; user
  prefers flexible SQL (not a strong preference).
