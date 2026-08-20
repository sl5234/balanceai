# Distribution channel decisions

## #11 — 2026-08-19 — Sequencing: local MCP server + open-source (bring-your-own-keys) first, defer everything else

**Category:** product
**Status:** accepted
**One-way door:** no
**Related:** #1, #7, #10

**Short description:** Immediate focus is building and dogfooding the local MCP server until it's usable, then open-sourcing the GitHub repo with customers supplying their own Plaid and Claude API keys (bring-your-own-keys) — no shared backend, no multi-tenancy problem. ChatGPT Custom Plugin publishing (#7), traditional messaging, and any custom frontend/infra work are all deferred until this proves useful, not abandoned.
**Short example:** Right now: no Expo frontend work, no Lambda/API Gateway/CDK work, no OAuth/multi-tenancy build — just the MCP server itself, run locally by the founder, then handed to open-source users who bring their own API keys.

**Grounded facts:**
- [verified] User's stated sequencing plan: local MCP server → dogfood until usable for the founder → open-source the repo with customer-supplied Plaid/Claude API keys → if that proves useful, revisit publishing as a ChatGPT Custom Plugin (#7).
- [verified] Bring-your-own-keys means each user runs their own instance with their own credentials — this sidesteps the OAuth/multi-tenant-data-isolation work that #6, #7, and #9 all required for a shared hosted backend, since there is no shared backend in this phase.
- [verified] User explicitly reaffirmed this is not a one-way door — the distribution-channel decision (#10: AI-assistant style vs. traditional messaging vs. a custom-owned frontend) is deferred, not closed, and will be revisited once this phase proves out.

## #10 — 2026-08-19 — Bias toward AI-assistant-platform integration over traditional messaging

**Category:** product
**Status:** accepted
**One-way door:** no

**Short description:** Deliberate directional bias toward the AI-assistant-platform integration style (ChatGPT/Gemini/Claude custom connectors) over traditional messaging platforms (WhatsApp, Messenger, iMessage, etc.) for the next phase — a preference call, not one driven by new evidence overturning the factors that favored traditional messaging.
**Short example:** #6 (Gemini) and #7 (ChatGPT) stay open for further discussion; #8 (Messenger) and #9 (WhatsApp) are rejected on this basis alone, even though neither was ruled out on technical or policy grounds.

**Grounded facts:**
- [unverified] User's explicit stated preference to bias toward the AI-assistant-platform integration approach going forward.
- [unverified] User explicitly noted this call is not a one-way door — reversible, traditional messaging can be revisited later if the AI-assistant path doesn't pan out.

## #9 — 2026-08-19 — WhatsApp Business API integration path rejected — biasing toward AI-assistant platforms

**Category:** other
**Status:** rejected
**One-way door:** no
**Related:** #1, #10

**Short description:** Rejected not on technical or policy grounds — the underlying feasibility findings below still stand — but because of the directional bias toward AI-assistant-platform integration (#10).
**Short example:** TechCrunch reporting on Meta's own policy gives the example of "a travel company running a bot for customer service" as explicitly still permitted, and BalanceAI's bot likely qualified as that shape — but this channel is being set aside anyway per #10, not because it was ruled out.

**Grounded facts (from when this was still an open feasibility question):**
- [verified] TechCrunch (Oct 18, 2025), reporting on Meta's actual policy change: the ban targets AI "when such technologies are the primary (rather than incidental or ancillary) functionality," effective January 15, 2026. Named companies facing disruption: OpenAI, Perplexity, Luzia, Poke.
- [verified] Same source: business-specific AI use cases remain permitted — explicit example given is a travel company's customer-service bot. Meta's stated rationale is infrastructure load and a revenue gap (no billing mechanism existed for general-purpose chatbot providers), not a blanket anti-AI stance.
- [correction] Earlier version of this entry claimed WhatsApp Business API "requires going through a Business Solution Provider" as a blanket rule — checked against developers.facebook.com/docs/whatsapp/overview directly, and found no such requirement stated; Meta also offers direct Cloud API access. The BSP path (Twilio/360dialog/etc.) is *a* route, not confirmed as the only one.
- [correction] Earlier version claimed business verification is required for setup — the same primary source instead describes verification as something that unlocks *additional* benefits (higher throughput, Official Business Account status), not a stated hard requirement to use the platform at all.
- [unverified] Whether BalanceAI's specific bot (personal-finance Q&A + bookkeeping, including open-domain-within-finance questions like "what counts as a business expense") would be classified by Meta as "primary AI functionality" (banned) or "business-specific, AI as mechanism" (permitted) — this is the real remaining open question, and it's a judgment call Meta would make, not something resolvable from documentation alone.
- [unverified] The claimed August/October 2026 billing-rate changes were not re-checked against a primary source in this pass.

## #8 — 2026-08-19 — Facebook Messenger rejected again — biasing toward AI-assistant platforms

**Category:** other
**Status:** rejected
**One-way door:** no
**Related:** #1, #10

**Short description:** Rejected again — not on technical grounds (it remained technically viable on reconsideration) but because of the directional bias toward AI-assistant-platform integration (#10).
**Short example:** Messenger still only needs a Facebook Page + Send API, no business verification, no app review for reply-only bots — but this channel is being set aside anyway per #10.

**Grounded facts (from when this was still an open feasibility question):**
- [unverified] Previously ruled out based solely on the user's stated preference ("i dont like facebook messenger"), no technical blocker identified.
- [unverified] Technical viability (Facebook Page setup, Send API, no app review needed for reply-only bots within the 24-hour window) came from a web-search summary, not checked against Meta's own documentation directly.

## #7 — 2026-08-19 — ChatGPT Custom Plugin (Developer Mode / MCP) accepted as the integration path

**Category:** system (technical)
**Status:** accepted
**One-way door:** no
**Related:** #1, #10

**Short description:** Chose Custom Plugin (Developer Mode, MCP-based) over Custom GPT + Actions — Actions is dead for personal accounts anyway, but the deciding reasons are that Custom Plugin supports advanced/technical use cases (not the no-code GPT builder), reuses the existing MCP server (`bookkeeping_server.py`) directly instead of requiring a new REST/OpenAPI layer, and was intended to let other tools (e.g. Gmail, for pulling receipts) work in the same chat. Two real risks are accepted-but-unresolved for now rather than blocking the decision.
**Short example:** Both building and using a custom plugin require ChatGPT Plus or higher — free and the cheaper "Go" tier are excluded.

**Grounded facts:**
- [unverified] Risk, unresolved: customer trust in ChatGPT/OpenAI with financial information is questionable — the user themselves stated they don't trust it and don't plan to use it personally. Needs a real mitigation, not yet identified.
- [unverified] Risk, unresolved: whether OpenAI's usage policies even permit processing/transcribing financial-sensitive data (e.g. receipt OCR via `sync_journal_entries_from_receipt`) through GPT models at all — not yet checked against OpenAI's usage policies.
- [verified] Real, currently-unresolved risk to the "other tools in the same chat" goal specifically: per an OpenAI Developer Community bug report (community.openai.com, reproduced with a built-in Notion app, June 2026, acknowledged by OpenAI staff but still unresolved), invoking a custom MCP connector in a conversation can cause built-in apps (the pattern would include Gmail) to disappear from the tool namespace or the conversation to fail with a "message stream error" for the rest of that conversation.
- [verified] developers.openai.com/api/docs/guides/developer-mode (OpenAI's own docs): Developer Mode — the single toggle covering both creating and using custom MCP plugins — is "available to Pro, Plus, Business, Enterprise, and Education accounts on the web." Free is excluded; "Go" is not mentioned anywhere on the page, implying it's excluded too (if it qualified, it would likely be listed alongside Plus).
- [unverified] Whether this remains a hard gate going forward, or whether OpenAI extends eligibility to Go/free later, was not checked — this is a snapshot as of August 2026.
- [verified] developers.openai.com/plugins/concepts/plugins: a "plugin" is a package containing skills, an MCP server, or both — "start with the smallest shape that supports your use cases." No Apps SDK / custom UI is required for a functional plugin.
- [verified] developers.openai.com/plugins/build/plugins: confirmed minimum requirement is a `.codex-plugin/plugin.json` manifest plus optionally a `skills/` directory and/or an MCP server — a bare MCP server (reusing `bookkeeping_server.py`'s tools as-is) is sufficient; the MCP server itself handles UI/auth, no separate Apps SDK build needed.
- [verified] developers.openai.com/plugins/build/mcp-server: required transport is "MCP streamable HTTP," typically exposed at `/mcp`. Auth options: OAuth 2.1 for user-specific data, OpenAI-managed mTLS to authenticate ChatGPT as the client, or none for public data.
- [verified] developers.openai.com/plugins/deploy/connect-chatgpt: connecting a plugin supports two connection methods — a **public HTTPS endpoint**, or a **"Secure MCP Tunnel"** (selecting a tunnel and providing its `tunnel_id`) — meaning a fully public always-on host may not be required at all for private/personal use, unlike what was assumed for the Claude connector path.
- [verified] developers.openai.com/plugins/deploy/submission: the review/submission portal is explicitly tied to "publish it for public use" — the docs don't explicitly say private plugins skip review, but structurally, submission is only mentioned in the context of public Plugin Directory listing, not private Developer Mode connections.
- [verified] developers.openai.com/plugins/deploy/submission: publishing to the public Plugin Directory is gated by a completely separate system from personal ChatGPT plans — "you need an organization role with plugin submission write access" on the OpenAI Platform (platform.openai.com), not a Plus/Pro/etc. subscription. Since public listing isn't needed for a private test group, this gate is likely irrelevant to actually reaching testers — only the Developer Mode (Plus+) requirement above applies.

## #6 — 2026-08-19 — Gemini consumer app integration path

**Category:** system (technical)
**Status:** open
**One-way door:** no
**Related:** #1

**Short description:** Whether Gemini's consumer app is viable is unresolved, same shape as ChatGPT (#7) and WhatsApp (#9) — a genuine self-serve MCP-based custom-connector mechanism exists, but it's gated behind a paid Google AI Pro/Ultra subscription ("Gemini Spark access") on whoever wants to use it.
**Short example:** You could link BalanceAI's existing MCP server as a custom "Connected App" in Gemini, but the tester would need an eligible Google AI Pro or Ultra subscription to have Gemini Spark access in the first place — same "must already be a paying subscriber" bottleneck as Claude's connector.

**Grounded facts:**
- [verified] support.google.com (Gemini Connected Apps help article): "You can connect personal or third-party apps by linking their Model Context Protocol (MCP) server. This adds a custom app in your Connected Apps settings." — this feature is "only available to users with Gemini Spark access."
- [verified] Same source: most listed Connected Apps (Gmail, Calendar, YouTube Music, Spotify, WhatsApp, Maps, etc.) are Google-curated, but the MCP-linking capability is the genuine self-serve exception.
- [unverified] Gemini Spark's eligibility requires a personal Google Account, age 18+, Keep Activity enabled, and an eligible Google AI Pro or Ultra subscription — from a web-search summary of secondary sources, not checked against Google's own Gemini Spark documentation directly.
- [unverified] Exactly which paid tier (Pro vs. Ultra only) qualifies, and whether a free account can ever get Gemini Spark access, was not confirmed.

## #5 — 2026-08-19 — Google Messages / RCS rejected as a distribution channel

**Category:** other
**Status:** rejected
**One-way door:** no
**Related:** #1, #2

**Short description:** Rejected primarily on market fit, same logic as Telegram (#2) — in the US, the most popular messaging platforms are Apple iMessage, Facebook Messenger, and WhatsApp, not Google Messages/RCS.
**Short example:** Even if a self-serve RCS bot path existed, most US testers aren't defaulting to Google Messages the way they use iMessage/Messenger/WhatsApp.

**Grounded facts:**
- [verified] User's own market knowledge: in the US, the most popular messaging platforms are Apple iMessage, Facebook Messenger, and WhatsApp — not Google Messages/RCS.
- [unverified] Secondary reason: Google's dedicated consumer bot platform (Business Messages) has reportedly been deprecated — from a web-search summary of secondary/blog sources, not checked against Google's own documentation directly.
- [unverified] Secondary reason: RCS Business Messaging reportedly requires routing through carrier/hub partners (e.g. Infobip, MessageBird) rather than a self-serve bot API — same caveat, not checked against a primary source.

## #4 — 2026-08-19 — Snapchat rejected as a distribution channel

**Category:** system (technical)
**Status:** rejected
**One-way door:** no
**Related:** #1

**Short description:** Snapchat has no official conversational bot API to build on.
**Short example:** The only "Snapchat bots" found are browser/device automation scripts built to mimic human behavior and evade detection.

**Grounded facts:**
- [verified] developers.snap.com lists Snapchat's full developer offering as Lens Studio, Camera Kit, Snap Kit (Creative Kit for one-way content sharing, Login Kit for auth), Spectacles, Social Plugins, and a Marketing API — no two-way conversational messaging API among them.
- [verified] One real example (github.com/Emmanuel-Rods/SnapBot) confirms unofficial automation exists via Puppeteer browser automation "without relying on internal APIs or reverse engineering," carries an "educational and research purposes only" disclaimer (implying real ToS risk), and is fragile — it depends on DOM selectors that break whenever Snapchat changes its web UI.
- [correction] Earlier version of this entry claimed such tools are "explicitly designed to avoid detection" / "mimic human behavior" — that specific framing wasn't found in SnapBot's own documentation and appears to have been conflated from a different, unverified repo. Dropped rather than re-asserted without a source.

## #3 — 2026-08-19 — Apple Messages for Business deprioritized as a distribution channel

**Category:** system (technical)
**Status:** deprioritized
**One-way door:** no
**Related:** #1

**Short description:** Apple Messages for Business is technically doable — bots/AI are a supported feature — but carries enough open setup questions (business registration, MSP selection, REST API integration effort) to not be worth pursuing for a quick validation-stage test.
**Short example:** Before sending a single message you'd need to resolve: does this require a legally registered business, which of the Apple-approved MSPs to use, and how to integrate that MSP's REST API into your own backend.

**Grounded facts:**
- [verified] register.apple.com/resources/messages/messaging-documentation/: "To qualify for an Apple Messages for Business account, your company needs to select an Apple-approved Messaging Service Provider (MSP)." — explicitly frames this as a company-level account, not an individual-developer signup.
- [verified] register.apple.com/resources/messages/msp-rest-api/: integration happens through a server-to-server REST API that the chosen MSP implements — this is a real integration path, not a plug-and-play SDK.
- [verified] register.apple.com/resources/messages/messaging-documentation/ explicitly lists "automation support (bots/AI)" as a supported feature, so bot/AI-driven conversation is possible within the platform — the barrier is eligibility/setup overhead, not a ban on bot logic.
- [unverified] Whether "your company" strictly requires a legally registered business entity, or whether a sole proprietor/individual could qualify, was not checked.
- [unverified] Which specific MSP to choose from Apple's approved list, and the relative cost/effort of each, was not evaluated.

## #2 — 2026-08-19 — Telegram rejected as a distribution channel

**Category:** other
**Status:** rejected
**One-way door:** no
**Related:** #1

**Short description:** Telegram was ruled out despite being the cheapest/lowest-friction bot platform to build on, because the target market doesn't use it.
**Short example:** A Telegram bot link is frictionless to build and free to run, but a random US stranger is unlikely to already have Telegram installed.

**Grounded facts:**
- [verified] User's own market knowledge: the US customer base predominantly uses Apple Messages, WhatsApp, and Messenger — not Telegram.

## #1 — 2026-08-19 — Skip custom frontend and AWS Lambda/CDK infra for MVP validation stage

**Category:** system (technical)
**Status:** accepted
**One-way door:** no

**Short description:** For the goal of cheaply testing whether people outside the founder want this product, don't continue building the custom Expo frontend or the AWS API Gateway/Lambda/CDK stack — reach users through an existing chat surface instead, calling the existing backend logic directly.
**Short example:** Instead of finishing Lambda packaging and shipping the Expo app through TestFlight, get a working chat surface in front of a stranger this week.

**Grounded facts:**
- [verified] `ChatScreen.jsx` has no backend/API calls — the frontend isn't wired to anything yet.
- [verified] Lambda deployment is unfinished and, per STATUS.md, already blocked on dependency-packaging issues.
- [verified] The bookkeeping tools (`servers/bookkeeping_server.py`) and `analyze_financial_question` are already built and tested — the backend logic exists; only the delivery surface is missing.
- [verified] User's stated goal: build something cheap to test whether real strangers want this, not to build production-scale infra yet.
