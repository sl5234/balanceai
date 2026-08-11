# Mobile App UX — Chat-First Direction

Summary of a product/UX brainstorm on what the BalanceAI mobile app (Expo/React Native)
should be, resuming after the initial dashboard-style scaffold. Supersedes the KPI-grid
"command center" home screen as the primary direction — that scaffold's components and
screens (`JournalScreen`, `ReportsScreen`, `ReportBuilderScreen`, the `BAI*` component
library) still apply, this changes what's *home* and how you get to everything else.

## Audience

Built for personal use first. Should stay reasonable to extend to other users later
(auth, per-user data isolation), but no multi-tenant onboarding work needed yet.

## Navigation shell

Bottom tab bar with three destinations: **Chat | Ledger | Reports** (evolves the existing
`BAIBottomNav` component — drop the KPI-dashboard "Home" tab in favor of Chat, drop the
standalone "Sync" tab since bank sync is deferred, see below).

- The bar auto-hides when the chat composer/keyboard is focused (actively typing), and
  reappears once focus is released — same resolution X/Twitter uses for the composer vs.
  tab bar conflict. Keeps navigation reachable at rest without permanently eating vertical
  space while composing.
- A floating top-left avatar (opening a profile/account drawer, à la X) was considered and
  **shelved** — worth revisiting later, not a blocker.

## Chat (home screen)

Chat is the landing page, replacing the KPI 2×2 grid dashboard. Structure:

- Header: app identity + avatar (fixed in header, not floating).
- Chat thread: assistant greeting, suggested-prompt chips for cold start
  (e.g. "How much did I spend on dining this week?", "What's my biggest expense this
  month?", "Am I spending more than usual?"), tappable to drop straight into the composer.
- Answers to financial questions render as an "answer card" in the thread — headline
  number, comparison delta, link into the underlying transactions — backed by the existing
  `analyze_financial_question` tool.
- Composer/input bar with a **"+" attach button** (ChatGPT/Gemini-style attach menu).
  - For now, "+" opens **Camera only**. Bank account sync / statement upload was
    considered for the same menu but is **deferred** — revisit once the receipt flow is
    solid.

## Receipt capture flow

1. Tap "+" → **Camera** opens full-screen, with a back button to return to chat.
2. Snap a photo → back in chat, the photo sits **staged in the composer** (not sent yet) —
   standard iMessage/WhatsApp attach pattern. User can discard or send.
3. On send, the photo appears as a message in the thread.
4. The backend parses it (`sync_journal_entries_from_receipt`) and the assistant replies
   with an **editable journal entry card** — asking to confirm and post, or correct
   details first.
5. The card uses **simplified fields** (date, merchant, amount, category, memo) rather
   than exposing raw double-entry debit/credit lines — friendlier for a non-accountant
   user. The backend still creates proper double-entry `journal_lines` underneath; the
   simplified form just doesn't surface them yet. An "advanced" toggle to show the real
   lines is a plausible future addition, not needed for v1.
6. Confirming posts the journal entry.

## Ledger tab

A scrollable list of journal entry cards — the general ledger view. Close to the existing
`JournalScreen`; mainly a home for entries once they're posted (including ones created via
the receipt flow above).

## Reports tab

List of default reports (e.g. income statement) plus a list of user-created custom
reports, with a "+ new report" action reusing the existing report-builder flow
(`create_report_definition`, `list_report_definitions`). Tapping a report opens its detail
view (e.g. the income statement itself), generated via `generate_report`.

## Explicitly deferred (not forgotten)

- **Bank account sync / statement upload** entry point — not in the "+" menu for now.
  The backend capability already exists (manual PDF statement upload via
  `upload_statement`, Chase-only parser); this is purely a "where does it live in the
  new nav" question to answer later. Live account linking via Plaid remains unbuilt
  (service stub exists, no tool wired to it).
- **Floating top-left avatar** for a profile/account drawer — shelved, may revisit.
- **Double-entry line-level editing** in the journal entry card — simplified fields only
  for now.
