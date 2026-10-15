# LeadPilot upgrade: progress

Last updated: 15 Oct 2026

The upgrade turns LeadPilot from a demo into a real product: Supabase for the database and login, Gemini for AI
features, and ideas borrowed from Fizzy (https://github.com/KenshinCommits/Fizzy). It has 12 phases.

**Where the code is:** `main` contains Phases 0–5 (first part) and the dashboard redesign. The finishing steps
of Phase 5 and Phases 6–9 are on the branch `claude/epic-bell-nq6hx0`, ready to merge into `main`. The phase branches
(`phase-0-foundations` … `phase-5-config`) are kept on GitHub for reference; `phase-5-config` is the same as `main`.
Start new work from `main`.

## Status at a glance

| # | Phase | Status | Commit |
|---|---|---|---|
| 0 | Foundations: live mode, durable event log, browser tests | ✅ Done | e22c171 |
| 1 | Supabase Postgres database | ✅ Done | aea514a |
| 2 | Sign-in, roles (admin / manager / rep) and API keys | ✅ Done | 842d5c3 |
| 3 | Connectors: forms, CRM, email, website tracker, CSV import | ✅ Done | 26cc0e9 |
| 4 | Accounts (companies) and deals (opportunities) | ✅ Done | 2bfe39a, 019a6a6 |
| 5 | Settings console: versioned rules with diff and rollback | ✅ Done | 9cdc32a, 0efdfa6 |
| 6 | What-if testing: replay history against a draft config | ✅ Done | 5e948b6 |
| 7 | Notifications: in-app, email, Slack, SMS | ✅ Done | 8afd02e |
| 8 | Call intelligence with Gemini (summaries, outcomes) | 🟡 Built and tested with a mocked Gemini; needs a real-key check | see branch `claude/epic-bell-nq6hx0` |
| 9 | Quotes on deals, with approval and a buyer link | ✅ Done | see branch `claude/epic-bell-nq6hx0` |
| 10 | Playbooks and recovery sequences | ⬜ To do | |
| 11 | Agent context API (and the AI assistant idea, below) | ⬜ To do | |
| 12 | Hardening, faster restarts, docs | ⬜ To do | |

**Tests right now:** 264 backend tests pass (`make test`). 18 browser tests pass (`make e2e`). The 5 Postgres
tests (`make test-pg`) pass with the Phase 9 migration. They were run against a local Postgres 16; worth
one run against Supabase too.

**Dashboard redesign:** the `claude/charming-noether-8ziqwn` branch (brand, sign-in layout, Leads explorer,
drill-down links, self-installing `python scripts/dev.py`, faster motion, lazy-loaded chart pages, live status on the
Live Feed nav item) is merged up to its commit e3985a5. Its placeholder browser-only sign-in was **not** used: the
real Supabase sign-in, roles and page guards from Phase 2 are kept. Merge future commits from that branch the same way.

## What is done

### Phase 0: Foundations
- Two modes: **demo** (simulated clock and fake leads) and **live** (real time, no simulator).
- Every incoming event is stored in a permanent log, and all state is rebuilt from it on restart.
- Playwright browser tests that open every page.

### Phase 1: Supabase database
- Postgres on Supabase, with versioned SQL migrations in `supabase/migrations/`.
- Background writes, so the database never slows event processing.

### Phase 2: Sign-in and roles
- Supabase login (email and password), and a "waiting for access" screen for new sign-ups.
- Roles:
  - **admin**: everything.
  - **manager**: their team's leads.
  - **rep**: only their own leads.
- Scope is enforced on the server, including the live feed.
- API keys (`lp_…`) let other systems send events; only a hash is stored.
- **Access** page to approve people and issue keys.

### Phase 3: Connectors
- **Signed webhooks** (HMAC-SHA256). Fake, old and replayed requests are refused.
- **Website forms** (Webflow, Typeform, WordPress, Zapier) and **CRM** records (HubSpot, Pipedrive, Salesforce).
- **Inbound email:**
  - Replies are attached to the right lead, with quoted text removed.
  - Bounces are recorded.
  - Out-of-office replies are ignored.
- **Website tracker** script: page views, plus form capture. Earlier anonymous visits are linked to the lead once they fill in a form.
- **CSV import** with column matching, preview, duplicate detection and history dates.
- **Connectors** page (admins) and **Import** page (managers).

### Phase 4: Accounts and deals
- **Accounts:**
  - A company, identified by its web domain, groups all its contacts.
  - It shows the **buying committee**: decision makers, managers and users.
- **Deals (opportunities):**
  - A company can have several contacts on one deal, and several deals over time, so the old "one lead = one deal" limit is gone.
- **How deals open:**
  - Automatically, on the first buying signal from a contact: a demo request, sales enquiry or meeting.
  - Or a rep creates one.
  - After a win, a new signal opens an **expansion** deal.
- **How deals move:**
  - Meeting → proposal → negotiation → won or lost, based on evidence.
  - Or by hand.
  - Every move records a rule and its evidence (rules O0–O8, OM).
- **Deal value and win chance** are calculated per deal. Involving more of the buying committee raises the win chance.
- **Stalled deals** are flagged when nothing happens within the stage's time limit.
- **Built from the event log, so existing data becomes deals automatically:**
  - A replay rebuilds identical deals.
  - Event order doesn't matter (tested).
- **API:**
  - `GET /api/accounts`, `GET /api/accounts/{id}`
  - `GET /api/opportunities` (deal board), `GET /api/opportunities/{id}`
  - `POST /api/opportunities`, `PATCH /api/opportunities/{id}` (amount, close date, name, stage, won/lost)
- **Scope:** reps see a company or deal only through their own contacts; other reps' contacts show name and role only.
- **Data:**
  - New `opportunities` table and migration `20261014000000_opportunities.sql`.
  - New config section `opportunities` in `backend/config/pipeline.yaml`.
- **Code:**
  - `backend/app/engine/opportunity.py`
  - `backend/app/api/routes_deals.py`
  - `backend/tests/test_opportunity.py`
  - changes in `processor.py` and `store.py`
- **Screens:**
  - **Pipeline** opens on the **deal board** (one card per deal, won and lost columns, owner and stalled filters).
    A **Deals | Leads** switch brings back the per-lead board (`?view=leads`; `to.pipeline(filters)` links there).
  - **Accounts** (`/accounts`): companies with contacts, buying roles, open deals, pipeline, won revenue; search and sort.
  - **Account** (`/accounts/:id`): company details, deals, people with their roles, and the buying committee with who is missing.
  - **Deal** (`/deals/:id`): stage path, stage history with rules and evidence, people, value and chance breakdown,
    and an edit form (name, amount, expected close, stage, won / lost with a reason).
  - **Lead page:** an "Account & deals" card with a **New deal** button.
- **Code (frontend):** `pages/Accounts.tsx`, `pages/Account.tsx`, `pages/Deal.tsx`, `pages/Pipeline.tsx`,
  `components/deals.tsx`, `e2e/deals.spec.ts`.

### Phase 5: Settings console
- **How it works:**
  - The rules in `backend/config/scoring.yaml`, `pipeline.yaml`, `assignment.yaml`, `quality.yaml` and `nba.yaml`
    stay the defaults. `simulator.yaml` is not editable (demo only).
  - A **settings version** stores only what differs from those files (`overrides`), so new defaults added in code
    still reach every version. Version 1 ("Starting rules from the YAML files") is created on first start.
  - Exactly one version is **active**. Others are **draft** (saved, never used) or **retired** (used before).
  - **Saving** a version checks it first: valid YAML, same shape as the defaults (no unknown or deleted settings,
    numbers stay numbers), the config loads, and a **dry run** processes a built-in sample journey plus the first
    400 real events in a scratch engine. Any failure is returned as a list of plain-English problems.
  - **Activating** swaps the config in every part of the engine and **replays the whole event log** under it, so
    every score, stage, assignment and deal reflects the active rules. If the replay fails, the previous version is
    put back. Requests wait while it runs (about a minute or two on demo data).
  - **Rollback** saves an old version's rules as a **new** version and activates it, so history is never rewritten.
  - Every processed event and every score change records the version that produced it (`config_version`).
    The lead page's score chart shows "scored under rules vN" for a selected point.
- **API** (managers can read, only admins can change):
  - `GET /api/config`: active version, each section as YAML, plus the documented YAML file (with comments).
  - `GET /api/config/versions`, `GET /api/config/versions/{id}` (with changes vs the previous version and vs active).
  - `POST /api/config/check` `{sections: {name: yaml}}`: validate + dry run, returns the list of changes.
  - `POST /api/config/versions` `{sections, note, activate?}`: save a draft (and optionally activate it).
  - `POST /api/config/versions/{id}/activate` (drafts only), `POST /api/config/versions/{id}/restore` (rollback).
- **Data:** new `config_versions` table (survives demo resets, like connectors); `config_version` column added to
  `events` and `score_changes`. Migration `supabase/migrations/20261015000000_config_versions.sql`. Local SQLite
  files made by older versions get new columns added automatically on start.
- **Screen:** **Settings** (`/settings`, in the System menu for admins and managers): the version in force,
  a YAML editor per section with "Show the documented defaults", **Check changes** (shows problems or a
  before/after table), **Save as draft**, **Save and activate**, and a version history with per-version changes,
  **Activate** and **Roll back to this** (each asks for confirmation).
- **Code:** `backend/app/config_versions.py` (versions, validation, diff, dry run), `backend/app/api/routes_config.py`,
  `Runtime.apply_config` in `backend/app/runtime.py`, `backend/tests/test_config_versions.py`,
  `frontend/src/pages/Settings.tsx`.
- **Checked in the browser** (`frontend/e2e/settings.spec.ts`): grade A 80 → 70, **Check changes** shows the one
  change, **Save and activate** makes version 2 active and more leads become grade A; **Roll back to this** on
  version 1 makes version 3 active with the YAML rules and exactly the original grade-A count. `/settings` is in the
  smoke test's page list. The README has a "Settings console" section and the `/api/config` rows.

### Phase 6: What-if testing
- **What it does:** shows exactly what a rule change would do before it is switched on. The whole event log is
  re-run **twice** in scratch engines, as of the same moment: under the rules in force and under the draft. The two
  outcomes are compared lead by lead and deal by deal. Nothing is saved, switched or written.
- **Why two runs:** the live engine re-evaluates a deal's value only when something happens to it, so live deal
  values are slightly older than a fresh replay. Re-running the active rules too makes the comparison exact: the
  same rules give zero differences (tested), and the draft side equals what **Save and activate** would produce
  (tested: what-if result == state after activation).
- **What it compares:** per lead: grade (up / down), score, stage, owner, next action (open leads), quality status
  (quarantined, merged); per deal: opened, gone, stage. Plus the grade mix, stage mix, owner mix, and deal totals
  (open, won, lost, stalled, expected pipeline) before and after. Lists are capped at 200 per kind; counts are complete.
- **How it runs:** in a background thread on a snapshot taken under the API lock, so the dashboard keeps working.
  One run at a time; the latest 10 are kept in memory (not in the database). In memory a replay is fast: about
  3.4 s for 4,000 demo events (the 2–3 minutes for 10,000 events noted under Phase 12 is with database writes).
- **Limitation (same as activation):** SLA checks are events created by the live scheduler, so a draft that changes
  first-touch SLA times is replayed against the SLA checks that were actually scheduled under the old times.
- **API:** `POST /api/config/whatif` `{sections}` or `{version_id}` (admin) returns `202` with the run;
  `GET /api/config/whatif` (list), `GET /api/config/whatif/{id}` (status, progress, result, `stale` when the
  rules in force changed since).
- **Screen:** Settings → **What if?** next to *Check changes* (for unsaved edits) and on every draft or older
  version in the history. The panel shows a progress bar, then a summary sentence, six counts, grade / stage /
  deal tables (in force, what if, change) and the changed leads and deals with links.
- **Code:** `backend/app/whatif.py`, routes in `backend/app/api/routes_config.py`, `backend/tests/test_whatif.py`,
  API tests in `backend/tests/test_config_versions.py`, `frontend/src/components/whatif.tsx`,
  `frontend/src/pages/Settings.tsx`, `frontend/e2e/settings.spec.ts`.

### Phase 7: Notifications
- **What it does:** tells the right people when something needs them: a hot (grade A) lead assigned to them, any
  new lead, a reply, a meeting or demo request, a missed deadline that moved a lead, an escalation to the manager
  queue, a stall, a won or lost deal, a suspicious lead to review, a junk source. Rules (who, which channels,
  severity, on/off) are in `backend/config/notifications.yaml`; they do not affect the config fingerprint.
- **How it hooks in:** the processor now calls `listeners` from `_emit`, i.e. only while it broadcasts. Replays,
  restarts, settings activations, what-if runs and the demo warm-up never broadcast, so they never notify (tested).
  The notification tables are kept by `clear_projections` (replays) and cleared by a demo reset.
- **Who sees what:** rep notifications go to that rep; manager ones to managers whose team includes the lead's owner,
  plus admins. Managers and admins can also view what their reps were sent ("My reps' too"). Read state is per person.
  Over the WebSocket a `notification.created` message only goes to the people it is addressed to.
- **Channels:** in-app; email (Resend), Slack (incoming webhook), SMS (Twilio), each off until its keys are set
  (`.env.example` lists them). Deliveries run in a background loop, never under the processing lock, and each one is
  recorded as sent / failed (with the reason) / skipped. People turn email and SMS on or off for themselves and save
  a mobile number (validated, stored as E.164). Admins can send a test on each channel. In demo mode only in-app
  notifications are made unless `LEADPILOT_NOTIFY_IN_DEMO=1`.
- **API:** `GET /api/notifications`, `POST /api/notifications/read`, `GET/PUT /api/notifications/settings`,
  `POST /api/notifications/test` (admin).
- **Screens:** the bell (unread count, latest 8, mark all read, links to the lead or deal) and **Notifications**
  (`/notifications`): inbox with All / Unread, "Sent to me" / "My reps' too", kind filter and paging; Your settings;
  Channels (admins); Rules (managers). Urgent notifications also pop up as a toast.
- **Data:** tables `notifications`, `notification_deliveries`, `notification_reads`; `phone` and `notify` columns on
  `profiles`. Migration `supabase/migrations/20261016000000_notifications.sql`.
- **Code:** `backend/app/notifications.py`, `backend/app/api/routes_notifications.py`, `backend/config/notifications.yaml`,
  `backend/tests/test_notifications.py`, `frontend/src/components/notices.tsx`, `frontend/src/pages/Notifications.tsx`,
  the bell in `frontend/src/components/Shell.tsx`, `frontend/e2e/notifications.spec.ts`.
- **Small fixes made on the way:** reassignment reasons read "…. Reassigned to X" instead of "…. ReAssigned to X";
  while the demo clock is paused, messages from API events are now pushed to the dashboard straight away instead of
  waiting for the clock to run.
- **Not done (ideas for later):** editing notification rules from the Settings console; per-person choice per rule;
  a daily digest email; retrying failed deliveries.

### Phase 8: Call intelligence (built; check with real keys, see below)
- **Where calls come from:** a new connector kind **Phone calls** (`/api/hooks/{id}`): Retell's webhook, verified with
  `RETELL_API_KEY` (`x-retell-signature: v=<ms>,d=<HMAC-SHA256(api key, body + ms)>`, 5-minute window), or
  LeadPilot's generic call JSON with the connector token / signature. Reps can also **Log a call** on a lead page.
  Calls are matched to a lead by phone number (dialled number for outbound, caller for inbound) or by
  `lead_id` / `lead_email` in the call metadata; unknown numbers wait on the Calls page until linked.
- **Analysis:** `backend/app/calls/gemini.py` calls Gemini's `generateContent` REST endpoint with a JSON response
  schema (enums for outcome, result, sentiment, intent) at temperature 0, and `clean()` checks and clips whatever comes
  back. Default model `gemini-2.5-flash` (`GEMINI_MODEL` to change). The transcript is fenced and the prompt tells
  the model to treat it as data. Without a key, or if Gemini fails: the phone system's summary plus rules
  (hang-up reason → voicemail / no answer; keyword classifier on the prospect's lines → intent). A rep's own
  outcome choice always wins; voicemails and unanswered calls never go to Gemini.
- **Replays stay exact:** the analysis is stored inside the `call_logged` event (plus `meeting_scheduled` when a
  meeting was agreed). Event ids come from the call id, so a re-delivered call changes nothing. Tested: a replay
  gives the same score and stage and makes no Gemini request.
- **Engine:** new intent signal `positive_call_intent` (6 points, `scoring.yaml`) for a connected call with buying
  intent; it shows as "call with buying intent" in explanations and as `positive_call` in active signals. The
  config fingerprint changes, so a live restart rewrites projections once.
- **Recordings:** copied to the private Supabase Storage bucket `call-recordings` (created on first use) when
  `SUPABASE_SERVICE_ROLE_KEY` is set; played through 1-hour signed links. Otherwise the provider's link is used.
- **Data:** `calls` table (kept through replays, cleared by demo resets), migration `20261017000000_calls.sql`.
- **Screens:** Calls card on the lead page; Calls page (`/calls`, managers) with Needs a lead / Failed; connector
  set-up text for Retell and the generic format; a "Call with …" notification to the owner (rule `call_analyzed`).
- **Code:** `backend/app/calls/` (gemini, parse, storage, center), `backend/app/api/routes_calls.py`, the call
  branch in `routes_connectors.py`, `backend/tests/test_calls.py`, `frontend/src/components/calls.tsx`,
  `frontend/src/pages/Calls.tsx`, `frontend/e2e/calls.spec.ts`.
- **To check with real keys (the owner):**
  1. Add `GEMINI_API_KEY`, restart, log a call with a pasted transcript on a lead page: the card should say
     "Summarised by Gemini (gemini-2.5-flash)". If Google renamed or retired that model, set `GEMINI_MODEL`.
  2. Retell: create a Phone calls connector, set the webhook URL in Retell and `RETELL_API_KEY`, make a test call to
     a lead's number. If the signature is refused, check the delivery log on the Connectors page: Retell's signing
     scheme was implemented from their SDK and has only been tested against our own signer.
  3. Recordings: add `SUPABASE_SERVICE_ROLE_KEY`, make a call with a recording, press **Play recording**.
- **Not done (ideas for later):** transcribing audio-only recordings (Gemini can take audio), a call-coaching view
  across reps, editing an analysis by hand.

### Phase 9: Quotes
- **What it does:** a **Quotes** card on the deal page. Reps build a quote from the catalog or their own lines
  (quantity, unit price, line discount, per year or one-time), a discount on the whole quote, the contact it is for and
  a valid-until date. A discount above 15% off list needs a manager's approval first. **Mark as sent** moves the deal
  to proposal and sets its amount to the quote's total; **New version** replaces a sent quote; **Withdraw** voids one.
- **The buyer's link:** `/q/<token>` opens the quote without signing in (works on a phone; print or save as PDF).
  The buyer accepts (typing their name) or declines. Opening it is a `proposal_viewed` (at most every 6 hours; the
  rep's "Open as the buyer" preview does not count). Accepting wins the deal at the quote's total.
- **Event-sourced:** new event types `quote_created`, `quote_revised`, `quote_approved`, `quote_declined`,
  `quote_voided`; sending is `proposal_sent` and accepting is `deal_won`, each with `payload.quote_id` and
  `payload.opportunity_id`, so the lead and deal pipelines move the way they already did. Quotes are folded with
  their deal (`engine/quotes.py`, called from `fold_opportunities`), so replays and settings activations rebuild
  them exactly. Events that do not fit a quote's state (e.g. accepting a draft) are ignored by the fold.
- **Config:** `backend/config/quotes.yaml` (catalog, approval limit, validity, terms, seller name); a new **Quotes**
  section in the Settings console. Changing the approval limit re-runs the events like any rule change.
- **Notifications:** `quote_approval` (managers), `quote_approved` and `quote_viewed` (owner), `quote_declined`
  (owner and managers) in `notifications.yaml`.
- **Email:** **Send by email** uses the notification email channel (Resend) and needs `LEADPILOT_PUBLIC_URL`. Like
  notifications, it is off in demo mode unless `LEADPILOT_NOTIFY_IN_DEMO=1`. Not yet tried with a real Resend key.
- **Data:** `quotes` table (a projection, rebuilt on replay), migration `20261018000000_quotes.sql`.
- **Code:** `backend/app/engine/quotes.py`, `backend/app/api/routes_quotes.py`, `_sync_quotes` in `processor.py`,
  `quote_view` in `store.py`, `backend/tests/test_quotes.py`, `frontend/src/components/quotes.tsx`,
  `frontend/src/pages/PublicQuote.tsx` (rendered straight from `main.tsx`, outside sign-in), `frontend/e2e/quotes.spec.ts`.
- **Not done (ideas for later):** taxes and multiple currencies; a real PDF file and e-signature; monthly billing
  and multi-year terms; a product catalog editor beyond the YAML; an approval queue page (the API has
  `GET /api/quotes?status=needs_approval`).
- **Known gap:** any GET of the buyer's link counts as a view, so an email scanner that pre-opens links can
  trigger "opened the quote" early.

## What should be done next

### Next phases
- **Phase 10: Playbooks.** Follow-up sequences and recovery plays for stalled deals.
- **Phase 11: Agent context.** One API that gives an AI agent everything about a lead or deal.
- **Phase 12: Hardening.**
  - Projection snapshots so restarts and settings activations don't replay the whole log. A rebuild currently takes
    about 2–3 minutes for 10,000 events in demo mode.
  - Security review, docs.

### Idea parked for later: AI assistant
A chat panel where a rep asks "what should I do next with this lead, and why?":
- Gemini answers using LeadPilot's own data, looked up through tool calls.
- The rules engine stays the source of truth.
- It fits best alongside Phase 8 or Phase 11.

## Notes for whoever continues (including a new Claude session)
- **Git rules from the owner:** commits are authored by the owner (im-notpranav) only; no Claude author, co-author
  or "Generated with" lines in commits or PRs. Never commit `backend/.env` (it holds the Supabase database URL and
  password) and never print its contents. Do not commit the `graphify-out/` folder.
- **How the engine fits together:** FastAPI backend (`backend/app`). Every event goes through
  `Processor.handle` (`processor.py`) into an in-memory `Store` (`store.py`), and is written behind to SQLite or
  Postgres (`persistence.py`). All state is a function of the raw event log plus the config, so anything new should
  be derived from events (that is what makes replays, restarts and settings activations exact).
  `Runtime` (`runtime.py`) owns the clock, the simulator and the processor.
- **Config:** `backend/config/*.yaml`, loaded by `app/config.py` into `Cfg` (attribute access). The active settings
  version is applied on top at start-up (`main.py` lifespan). `cfg.fingerprint` changes when rules change; on a live
  restart a different fingerprint makes the stored projections be rewritten.
- **Frontend:** React 18 + TypeScript + Vite + Tailwind v4 + TanStack Query (`frontend/src`). Routes in `App.tsx`,
  menu and role rules in `components/Shell.tsx` (`visibleNav`), shared UI in `components/ui.tsx`, drill-down URLs
  in `lib/links.ts`, API types in `lib/api.ts`, sign-in in `lib/auth.tsx` + `pages/Login.tsx`.
- **Browser tests in a cloud container:** if `npx playwright test` asks to download a browser, point it at the
  pre-installed Chromium with a local config that sets `use.launchOptions.executablePath` (do not commit it).
- **Tests:** backend tests in `backend/tests` (`make test`); API tests run the real app with sign-in on, using
  test-only signed tokens (see `test_opportunity.py` / `test_config_versions.py`). Browser tests in `frontend/e2e`
  start their own throwaway backends on ports 8010 (sign-in off) and 8011 (sign-in on); see `playwright.config.ts`.
- **Local ports:** port 8000 may be taken by Docker on the owner's machine; `.claude/launch.json` has preview setups
  on 8020 / 5174 (in-memory demo backend, nothing written to Supabase).

## What you (the owner) need to do
- [ ] Add `SUPABASE_ANON_KEY` and `LEADPILOT_ADMIN_EMAILS` (your email) to `backend/.env`. Real sign-in needs both.
- [ ] In Supabase: Authentication → URL Configuration → set **Site URL** to `http://localhost:5173`.
- [ ] Add `GEMINI_API_KEY` to `backend/.env` and run the Phase 8 checks above (Gemini, Retell, recordings).
- [ ] Optional: to email quotes to buyers, set up Resend and `LEADPILOT_PUBLIC_URL` (same keys as notifications) and
      try **Send by email** on a quote in live mode.
- [ ] To get notifications outside the app, add the channel keys listed in `backend/.env.example` (Resend, Slack,
      Twilio) and `LEADPILOT_PUBLIC_URL`, restart, then use **Send test** on the Notifications page.

## How to run and test
```bash
make dev        # backend + dashboard (or: python scripts/dev.py)
make test       # backend tests
make test-pg    # Supabase tests (in a throwaway schema)
make e2e        # browser tests
```
