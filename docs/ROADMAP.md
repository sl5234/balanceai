# Roadmap

Planned order of work. Update the status as items finish; backlog ids point to
`docs/BACKLOGS.md` (BL-*) and `docs/security/SECURITY_BACKLOGS.md` (SBL-*).

1. **Security backlog for `analyze_financial_question`, one by one**
   (`SECURITY_BACKLOGS.md`): done. SBL-1 fixed 2026-11-05; SBL-6 fixed and SBL-5
   partly fixed 2026-11-08; SBL-4 (redact all logs) moved to before launch.
2. **Test the `analyze_financial_question` flow** on real synced data.
3. **Try Ollama for classification:** a local model on the Mac instead of
   Haiku, so transaction descriptions don't leave the machine. Log it as a new
   decision (`MODEL_PROVIDER_SECURITY_DECISIONS.md` #2 rejected self-hosting
   by BalanceAI, not a model on the user's own Mac).
4. **Receipt flow:** pick how receipts fit with bank transactions (attach to one,
   become raw transactions, or both), then build it.
5. **Backlog items, together:**
   - BL-10: user corrections, free-form override rules, review of flagged
     transactions (incl. `unclassified` person-to-person payments).
   - BL-11: link refunds to their purchases.
6. **Report and report definition flow:** `create_report_definition` and
   `generate_report` on the new booking, locked down (SBL-2, BL-9).
7. **Deprecate legacy flows:** retire or rewire the old tools on the legacy
   models (BL-9, SBL-3).
8. **Statement flow:** bank statements on the new booking.

Waiting on: Plaid production access ("Get full access" approval and a
production secret).
