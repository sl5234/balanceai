# Roadmap

Planned order of work. Update the status as items finish; backlog ids point to
`docs/BACKLOGS.md` (BL-*) and `docs/security/SECURITY_BACKLOGS.md` (SBL-*).

1. **Security backlog for `analyze_financial_question`, one by one**
   (`SECURITY_BACKLOGS.md`): done. SBL-1 fixed 2026-11-05; SBL-6 fixed and SBL-5
   partly fixed 2026-11-08; SBL-4 (redact all logs) moved to before launch.
2. **Test the `analyze_financial_question` flow** on real synced data: done
   2026-11-08.
3. **Report and report definition flow:** `create_report_definition` and
   `generate_report` on the new booking, locked down (SBL-2, BL-9). Skipped
   2026-11-08 until we know we want to maintain these tools (an agent can save a
   question and re-run it through analyze); TODO above the tools.
4. **Receipt flow:** receipts become raw transactions (decision #18).
   `upload_receipt` built 2026-11-09. Next: match receipts with Plaid
   transactions (receipt wins), so a card purchase isn't counted twice.
5. **Try Ollama for classification:** a local model on the Mac instead of
   Haiku, so transaction descriptions don't leave the machine. Log it as a new
   decision (`MODEL_PROVIDER_SECURITY_DECISIONS.md` #2 rejected self-hosting
   by BalanceAI, not a model on the user's own Mac). Fold in BL-13.
6. **Backlog items, together:**
   - BL-10: user corrections, free-form override rules, review of flagged
     transactions (incl. `unclassified` person-to-person payments).
   - BL-11: link refunds to their purchases.
7. **Deprecate legacy flows:** retire or rewire the old tools on the legacy
   models (BL-9, SBL-3).
8. **Statement flow:** bank statements on the new booking.

Waiting on: Plaid production access ("Get full access" approval and a
production secret).
