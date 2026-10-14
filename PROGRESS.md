# LeadPilot upgrade: progress

Last updated: 15 Oct 2026

The upgrade turns LeadPilot from a demo into a real product: Supabase for the database and login, Gemini for AI
features, and ideas borrowed from Fizzy (https://github.com/KenshinCommits/Fizzy). It has 12 phases. Each phase is
on its own git branch, stacked on the previous one: `phase-0-foundations` → `phase-1-supabase` → `phase-2-auth` →
`phase-3-connectors` → `phase-4-accounts`. None are merged into `main` yet.

## Status at a glance

| # | Phase | Status | Branch / commit |
|---|---|---|---|
| 0 | Foundations: live mode, durable event log, browser tests | ✅ Done | `phase-0-foundations` · e22c171 |
| 1 | Supabase Postgres database | ✅ Done | `phase-1-supabase` · aea514a |
| 2 | Sign-in, roles (admin / manager / rep) and API keys | ✅ Done | `phase-2-auth` · 842d5c3 |
| 3 | Connectors: forms, CRM, email, website tracker, CSV import | ✅ Done | `phase-3-connectors` · 26cc0e9 |
| 4 | Accounts (companies) and deals (opportunities) | ✅ Done | `phase-4-accounts` |
| 5 | Settings console: edit scoring / SLA / rules with versions | ⬜ To do | |
| 6 | What-if testing: replay history against a draft config | ⬜ To do | |
| 7 | Notifications: in-app, email, Slack, SMS | ⬜ To do | |
| 8 | Call intelligence with Gemini (summaries, outcomes) | ⬜ To do | |
| 9 | Quotes | ⬜ To do | |
| 10 | Playbooks and recovery sequences | ⬜ To do | |
| 11 | Agent context API (and the AI assistant idea, below) | ⬜ To do | |
| 12 | Hardening, faster restarts, docs | ⬜ To do | |

**Tests right now:** 220 backend tests pass (plus 5 Supabase tests, run with `make test-pg`), and 13 browser tests pass.

**Dashboard redesign:** the `claude/charming-noether-8ziqwn` branch (new brand, sign-in layout, Leads explorer,
clickable drill-downs, self-installing `python scripts/dev.py`) is merged into `phase-4-accounts`. It keeps the real
Supabase sign-in, roles and page guards from Phase 2; the placeholder browser-only accounts from that branch were not used.

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
    A **Deals | Leads** switch brings back the per-lead board.
  - **Accounts** (`/accounts`): companies with contacts, buying roles, open deals, pipeline, won revenue; search and sort.
  - **Account** (`/accounts/:id`): company details, deals, people with their roles, and the buying committee with who is missing.
  - **Deal** (`/deals/:id`): stage path, stage history with rules and evidence, people, value and chance breakdown,
    and an edit form (name, amount, expected close, stage, won / lost with a reason).
  - **Lead page:** an "Account & deals" card with a **New deal** button.
- **Code (frontend):** `pages/Accounts.tsx`, `pages/Account.tsx`, `pages/Deal.tsx`, `pages/Pipeline.tsx`,
  `components/deals.tsx`, `e2e/deals.spec.ts`.

## What should be done next

### Next phases
- **Phase 5: Settings console.**
  - Store scoring, SLA, pipeline and next-action rules as versioned configs in the database (the YAML files stay as defaults).
  - Editor page with history, diff and rollback.
  - Each event records which config version scored it.
- **Phase 6: What-if testing.** Replay history with a draft config and compare grades, stages and assignments before switching.
- **Phase 7: Notifications.**
  - In-app, then email (Resend), Slack and SMS (Twilio).
  - Each channel does nothing until its key is set.
- **Phase 8: Call intelligence.**
  - A call-provider webhook (Retell adapter).
  - Gemini writes call summaries and outcomes, saved as events so replays stay repeatable.
  - Recordings go to Supabase Storage.
- **Phase 9: Quotes.** Quotes attached to deals.
- **Phase 10: Playbooks.** Follow-up sequences and recovery plays for stalled deals.
- **Phase 11: Agent context.** One API that gives an AI agent everything about a lead or deal.
- **Phase 12: Hardening.**
  - Projection snapshots so restarts don't replay the whole log. A rebuild currently takes about 2–3 minutes for 10,000 events in demo mode.
  - Security review, docs.

### Idea parked for later: AI assistant
A chat panel where a rep asks "what should I do next with this lead, and why?":
- Gemini answers using LeadPilot's own data, looked up through tool calls.
- The rules engine stays the source of truth.
- It fits best alongside Phase 8 or Phase 11.

## What you (the owner) need to do
- [ ] Add `SUPABASE_ANON_KEY` and `LEADPILOT_ADMIN_EMAILS` (your email) to `backend/.env`. Real sign-in needs both.
- [ ] In Supabase: Authentication → URL Configuration → set **Site URL** to `http://localhost:5173`.
- [ ] Add `GEMINI_API_KEY` to `backend/.env` before Phase 8.
- [ ] Review the phase branches and merge them into `main` when you're happy (in order: 0, then 1, 2, 3, 4).
      `phase-4-accounts` already contains the dashboard redesign branch.

## How to run and test
```bash
make dev        # backend + dashboard
make test       # backend tests
make test-pg    # Supabase tests (in a throwaway schema)
make e2e        # browser tests
```
