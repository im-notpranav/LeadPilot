# LeadPilot deploy plan

Last updated: 15 Oct 2026. Covers `main` at ee240e8 (Phases 0–9).

This plan takes LeadPilot from "runs on my laptop" to a live address your team signs in to, with real leads
coming in from forms, CRMs, the website tracker and phone calls.

## 0. Hosted demo now: Vercel (dashboard) + Render (API)

This is a public demo with seeded data, set up before the production plan below. Vercel can't run the API, because
it needs one always-on process with in-memory state, background loops and WebSockets. So the API runs on Render,
and Vercel serves the dashboard and proxies `/api` to Render.

| Piece | Where | Config |
|---|---|---|
| API, simulator and background loops | Render, `leadpilot-api`, Starter plan, Singapore | `render.yaml` |
| Dashboard | Vercel, root directory `frontend` | `frontend/vercel.json` |
| Data | Supabase, schema `demo_web` (its own schema, separate from local `demo`) | migrations run on start |

**Data init.** In demo mode, every start applies the migrations to `demo_web`, wipes it and simulates a 21-day world
(about 4k events, uploaded in the background in about 30 seconds). `LEADPILOT_SIM_SPEED=1` keeps it growing at about
one simulated day per real day. Anyone with access can reset it from the Simulator page.

**Steps**
1. Push `main` to GitHub.
2. **Render:** New → Blueprint → pick the repo. Render reads `render.yaml`. Fill in the secrets it asks for:
   `LEADPILOT_DB_URL` (Supabase session pooler, port 5432), `SUPABASE_ANON_KEY`, `LEADPILOT_ADMIN_EMAILS`,
   `LEADPILOT_PUBLIC_URL` (the Vercel address; fill in after step 3 if you don't know it yet), and optionally
   `GEMINI_API_KEY` and `SUPABASE_SERVICE_ROLE_KEY`. Wait for `/api/health` to show `"ready": true`.
   If Render gives the service an address other than `leadpilot-api.onrender.com`, change it in
   `frontend/vercel.json`.
3. **Vercel:** Add New → Project → import the repo. Set **Root Directory** to `frontend` (Vite is detected). Add the
   environment variable `VITE_BACKEND_WS_URL=wss://leadpilot-api.onrender.com`, then deploy.
4. **Supabase → Authentication → URL Configuration:** set the Site URL to the Vercel address and add it to the
   Redirect URLs, so sign-up and password-reset emails link back to it.
5. **Check:** open the Vercel address and sign in with the admin email. The Live Feed should show as connected, the
   clock should tick, and Leads should be full.

**Why the disk in `render.yaml`:** a service with a disk gets no zero-downtime deploys, so Render stops the old copy
before starting the new one. That keeps exactly one writer (section 1) without code changes.

## 1. How it will run (decisions)

**One container serves everything.** The dashboard calls `/api` and `/ws` on its own address
(`frontend/src/lib/live.tsx` builds the WebSocket URL from `location.host`), and it gets the Supabase keys from
`/api/auth/config` when it loads. So the simplest setup that works is FastAPI serving the built dashboard as well as
the API, on one domain such as `app.yourcompany.com`. The dashboard needs no build-time settings.

**Exactly one copy, always on.** This is the most important constraint:
- State lives in memory and is rebuilt from the event log on start (`runtime.py`, `store.py`).
- Background loops run inside the process: the SLA scheduler, notification delivery, call analysis and the
  connector flush (`main.py` lifespan).
- Two copies running at once would both write events and both send every notification. Nothing in the code stops
  this today (step A4 adds a guard).
- Scale-to-zero is not allowed: SLA timers would not fire, and every wake-up would be a full replay.

**Database: a separate Supabase project for production.** Keep your current project for development and demos.
Use the session pooler (port 5432), as in `.env.example`. Migrations in `supabase/migrations/` apply themselves on
start-up under an advisory lock, so there is no separate migration step.

**Host: Fly.io (recommended).**
- It runs a single always-on Machine.
- With one Machine, a deploy stops the old copy before starting the new one, so two copies never overlap.
- It supports WebSockets, gives free TLS for a custom domain, and lets you pick a region next to Supabase.
- Roughly $5–10 a month for 1 GB of memory.

*Alternatives:* Render or Railway also work, but by default their zero-downtime deploys run the old and new copies
side by side for a short time. Only use them once step A4 is done.

## 2. Phase A: code changes before the first deploy (Claude)

| # | Change | Why |
|---|---|---|
| A1 | **Serve the dashboard from FastAPI.** Mount `frontend/dist/assets` with long cache headers, and send `index.html` (no-cache) for every other path that is not `/api/*` or `/ws`. | One address for everything. Deep links and the buyer's `/q/<token>` page load on refresh. |
| A2 | **Dockerfile (multi-stage) and `.dockerignore`.** Stage 1: Node 22 runs `npm ci && npm run build`. Stage 2: `python:3.12-slim` with `backend/` (app, config, data), `supabase/migrations/` and the built `dist/`. Keep the repo layout, because `migrate.py` finds migrations at `parents[2]/supabase/migrations`. Start command: `uvicorn app.main:app --host 0.0.0.0 --port 8080 --workers 1 --proxy-headers --forwarded-allow-ips="*"`. Ignore `node_modules`, `.venv`, `var/`, `.env`, `graphify-out/`, `test-results/`. | A repeatable build. Exactly one worker. Real client IPs for the tracker, which reads `X-Forwarded-For`. |
| A3 | **Move `pytest` to `requirements-dev.txt`.** `httpx` stays: the Gemini, storage and notification code uses it. | A smaller image with nothing unneeded in production. |
| A4 | **Single-writer guard.** On Postgres, hold a session advisory lock (`pg_try_advisory_lock`) on its own connection for as long as the process runs. If another copy holds it, log it clearly and wait (or exit). | Stops two copies from writing events and sending notifications twice, for example after an accidental scale-up or an overlapping deploy. |
| A5 | **A readiness flag in `/api/health`.** Add `ready: status == "ready"`. Keep `ok: true` while the event log rebuilds, so the platform does not kill a copy that is still rebuilding. | You can tell "up" from "fully rebuilt" in monitoring and in the smoke test. |
| A6 | **`fly.toml`.** One Machine, `auto_stop_machines = "off"`, `min_machines_running = 1`, internal port 8080, an HTTP check on `/api/health` with a generous grace period, and non-secret settings under `[env]`. | The always-on, single-copy rule written down in config. |
| A7 | **CI on GitHub Actions.** On pull requests and on `main`: `pytest`, `npm run build` (which type-checks), and `docker build`. Later, deploy automatically on `main` with a `FLY_API_TOKEN` secret. Deploy by hand for the first few releases. | Nothing broken reaches production. |

After Phase A: run `make test`, `make e2e`, then build the image and run it locally against a scratch schema of the
production database (`LEADPILOT_DB_SCHEMA=staging`). Sign in, open every page, then drop the schema.

## 3. Phase B: accounts and services (owner)

1. **Supabase production project.**
   - Use the Pro plan. Free projects are paused after a week without activity and have no daily backups.
   - Pick a region close to your users. Then put Fly in the **same region**: the database writer sends every event
     to Postgres, so the distance between them matters.
   - Copy three things: the session pooler connection string, the anon (publishable) key and the service role
     (secret) key.
   - Authentication → URL Configuration: set **Site URL** to `https://app.yourcompany.com` and add it to the
     **Redirect URLs**.
   - Authentication → SMTP: use your own SMTP server (Resend offers SMTP). Supabase's built-in email only sends to
     your own team's addresses and is heavily rate-limited, so sign-up and password-reset emails would not reach
     real users without it.
2. **Domain.** Choose a subdomain such as `app.yourcompany.com`. You will add a DNS record for Fly in Phase D.
3. **Fly.io.** Create an account, install `flyctl`, run `fly auth login`.
4. **Resend.** Verify your sending domain (it gives you SPF and DKIM DNS records to add) and choose the from address.
5. **Optional channels:** a Slack incoming webhook, a Twilio number, a Gemini API key, a Retell API key.

## 4. Phase C: production settings

Secrets go in with `fly secrets set NAME=value` (never in `fly.toml`, never in git). Plain settings go in `fly.toml`.

| Variable | Value | Secret |
|---|---|---|
| `LEADPILOT_MODE` | `live` | |
| `LEADPILOT_PERSIST` | `1` | |
| `LEADPILOT_AUTH` | `on` (set it explicitly) | |
| `LEADPILOT_DB_URL` | Supabase session pooler URL of the **production** project | yes |
| `LEADPILOT_DB_SCHEMA` | `public` | |
| `SUPABASE_URL` | `https://<ref>.supabase.co` (otherwise worked out from the database URL) | |
| `SUPABASE_ANON_KEY` | anon / publishable key | public by design, but keep it with the secrets |
| `SUPABASE_SERVICE_ROLE_KEY` | service role key (recordings) | yes |
| `LEADPILOT_ADMIN_EMAILS` | your email | |
| `LEADPILOT_PUBLIC_URL` | `https://app.yourcompany.com` | |
| `RESEND_API_KEY`, `LEADPILOT_EMAIL_FROM` | email notifications and emailed quotes | key: yes |
| `SLACK_WEBHOOK_URL` | Slack channel | yes |
| `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM_NUMBER` | SMS | yes |
| `GEMINI_API_KEY`, `GEMINI_MODEL` | call summaries (`gemini-2.5-flash` by default) | key: yes |
| `RETELL_API_KEY` | Retell webhooks | yes |

**Never set in production:** `LEADPILOT_ALLOW_MODE_SWITCH`, `LEADPILOT_NOTIFY_IN_DEMO`, `LEADPILOT_WARMUP_DAYS`,
`LEADPILOT_DB`.

## 5. Phase D: first deploy (runbook)

1. `fly launch --no-deploy`. Pick the region that matches Supabase, then set the secrets from Phase C.
2. `fly deploy`, then `fly logs`. Expect the migrations to be applied, then the runtime to report `ready`.
3. `fly certs add app.yourcompany.com`, add the DNS record it shows you, and wait for the certificate.
4. **Smoke test** (on the real domain, in this order):
   - [ ] `/api/health` shows `mode: live`, `auth: true`, the database as OK, and `ready: true`.
   - [ ] Sign in with the admin email. Sign up a second address: it lands on "waiting for access"; approve it on the
         **Access** page.
   - [ ] The Live Feed shows as connected (the WebSocket over `wss://` works through Fly).
   - [ ] Create a form connector and send a signed test request. The lead appears and the delivery log shows it.
   - [ ] Put the tracker snippet on a test page, visit it, then fill in the form: the visits are linked to the lead.
   - [ ] Import a small CSV.
   - [ ] Quote: create one, open `/q/<token>` in a private window, accept it. The deal is won.
   - [ ] **Send test** on each notification channel you set up.
   - [ ] Phase 8 checks with real keys (from `PROGRESS.md`): a Gemini summary on a logged call, a Retell test call,
         and playing a recording.
5. **Switch the real sources over.** Point Webflow, Typeform, HubSpot, Pipedrive, Salesforce and Retell webhooks at
   `https://app.yourcompany.com/api/hooks/<connector id>`, and install the tracker snippet on the live site.
6. Tell the team the address. They sign up; you approve them and set their roles.

## 6. Running it

- **Deploys.** Merge to `main`, CI passes, then `fly deploy`. Each deploy means a short outage (stop, start,
  rebuild from the log). Today a rebuild takes about 2–3 minutes per 10,000 events, so deploy outside working hours
  until Phase 12 adds snapshots. Most webhook senders retry. Check the delivery log on the Connectors page after
  each deploy.
- **Rollback.** Code: `fly releases`, then `fly deploy --image <previous image>`. Migrations only add things
  (`IF NOT EXISTS`), so the previous release still runs on the newer database. Keep it that way: never drop or rename
  a column in the same release that stops using it. Rule changes: roll back in the Settings console (Phase 5).
- **Backups.** The event log is the source of truth: everything else can be rebuilt from it. Supabase Pro takes daily
  backups. Add point-in-time recovery once real money depends on the data.
- **Monitoring.** Fly's health check restarts a stuck Machine. Add an outside uptime check on `/api/health`, with an
  alert when it fails or when the database is not OK. Watch the Machine's memory as the log grows: start at 1 GB and
  scale up (`fly scale memory`) when needed. Error tracking (Sentry) can come in Phase 12.
- **Rough monthly cost:** Fly about $5–10, Supabase Pro $25, Resend free up to its monthly limit, Gemini Flash a few
  cents per hundred calls, Twilio per SMS. Check current prices before signing up.

## 7. Known risks (for Phase 12: hardening)

- **One copy is a single point of failure, and restarts get slower as the log grows.** Fix: projection snapshots
  (Phase 12).
- **CORS allows every origin.** The tracker and webhooks need that, and sign-in uses bearer tokens rather than
  cookies, so the risk is low. Still, limit it to the public routes.
- **Public routes have no rate limit:** `/api/hooks/*`, `/api/t.js`, tracking, `/api/public/quotes/*`. Add limits.
- **Email scanners can count as quote views:** any GET of the buyer's link counts as a view (known gap from Phase 9).
- **Retell's signature check has only been tested against our own signer.** Verify it with a real call (step D4).

## 8. Order of work

1. Claude: Phase A (A1–A7), one branch, with tests. About one session.
2. Owner: Phase B (accounts, domain, Resend, Supabase settings).
3. Together: Phase C settings, the Phase D deploy and smoke test.
4. Real sources switched over. After that, deploys follow section 6.
