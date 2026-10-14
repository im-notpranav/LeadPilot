# LeadPilot upgrade: progress

Last updated: 14 Oct 2026

The upgrade turns LeadPilot from a demo into a real product: Supabase for the database and login, Gemini for AI
features, and ideas borrowed from Fizzy (https://github.com/KenshinCommits/Fizzy). It has 12 phases.

**Where the code is:** `main` contains Phases 0–5 (first part) and the dashboard redesign. The finishing steps
of Phase 5 and all of Phase 6 are on the branch `claude/epic-bell-nq6hx0`, ready to merge into `main`. The phase branches
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
| 6 | What-if testing: replay history against a draft config | ✅ Done | see branch `claude/epic-bell-nq6hx0` |
| 7 | Notifications: in-app, email, Slack, SMS | ⬜ To do | |
| 8 | Call intelligence with Gemini (summaries, outcomes) | ⬜ To do | |
| 9 | Quotes | ⬜ To do | |
| 10 | Playbooks and recovery sequences | ⬜ To do | |
| 11 | Agent context API (and the AI assistant idea, below) | ⬜ To do | |
| 12 | Hardening, faster restarts, docs | ⬜ To do | |

**Tests right now:** 236 backend tests pass (`make test`). 15 browser tests pass (`make e2e`, including
`settings.spec.ts`). The 5 Postgres tests (`make test-pg`) pass with the Phase 5 migration (run against a local
Postgres 16; worth one run against Supabase too).

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

## What should be done next

### Next phases
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
- [ ] Add `GEMINI_API_KEY` to `backend/.env` before Phase 8.

## How to run and test
```bash
make dev        # backend + dashboard (or: python scripts/dev.py)
make test       # backend tests
make test-pg    # Supabase tests (in a throwaway schema)
make e2e        # browser tests
```
