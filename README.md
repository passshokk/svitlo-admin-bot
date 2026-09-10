# Svitlo School Administration Bot (`svitlo-admin-bot`)

A Telegram bot that runs the day-to-day operations of **Svitlo School** — an educational organization focused on youth integration, leadership development, and European policy. It handles student registration, identity/document verification, role-based access, an in-Telegram helpdesk, and keeps the school's external systems in sync.

Maintained by the Svitlo School IT Department.

---

# Part 1 — Overview (for anyone)

## What this bot actually does

Think of it as the school's front desk, ID check, and internal helpdesk, all running inside Telegram:

- **Registers new students.** A prospective student messages the bot, fills out a step-by-step form (name, contact info, parent/guardian details, etc.), passes a short rules quiz, and scans an ID document with their phone camera. A staff member gives the final approval.
- **Checks documents automatically.** The scanned ID is checked by an AI vision model to confirm it's a genuine Ukrainian document, plus an automatic location check — this keeps the school's community consistent with its mission.
- **Controls who can do what.** Students, teachers, IT team members, prefects, and other roles each see a different set of bot features.
- **Runs a helpdesk.** Anyone can open a support ticket from the bot; it lands in a dedicated thread in the staff chat, gets escalated if it sits too long unanswered, and can be rated afterwards.
- **Keeps records in sync.** Student records live in the bot's own database, but the school also uses a separate system ("SchoolToday") for administration — the bot pushes updates there automatically and flags anything a staff member edited by hand, so nothing gets silently overwritten.
- **Automates chores.** Reminding leads who didn't finish signing up, promoting students to the next age group on their 14th birthday, notifying staff of pending reviews — all on autopilot.

## How it's built, in plain terms

```
                    ┌──────────────┐
   Student's phone  │   Telegram   │  Staff chat / helpdesk threads
        ─────────▶  │              │  ◀─────────
                    └──────┬───────┘
                           │  every tap/message
                           ▼
                ┌─────────────────────┐
                │   The bot (this     │   Google Cloud, always-on
                │   repo), running    │   web server — no server to
                │   in the cloud      │   maintain, scales itself
                └──────────┬──────────┘
                           │
              ┌────────────┼─────────────┐
              ▼            ▼             ▼
        ┌──────────┐ ┌──────────┐ ┌──────────────┐
        │ Database │ │ AI photo │ │ SchoolToday & │
        │ (student │ │  check   │ │ Notion (other │
        │ records) │ │          │ │ school tools) │
        └──────────┘ └──────────┘ └──────────────┘
```

- The bot doesn't run on a physical or rented server that someone has to keep running — it lives on **Google Cloud Run**, a "serverless" hosting service that starts it up on demand and shuts it down when idle.
- All student data lives in **Firestore**, Google's cloud database. There is no local file storage — everything the bot "remembers" is a database read or write away.
- New code is deployed automatically: pushing to the `main` branch on GitHub redeploys the live bot within a couple of minutes.

## Key features

- **Guided registration funnel** — a linear, resumable form with validation at every step.
- **AI-assisted document verification** — Gemini Vision checks scanned IDs; automatic location screening backs it up.
- **Role-Based Access Control (RBAC)** — admins, teachers, students, IT team, prefects, and buddies each get a tailored experience.
- **In-Telegram Support Centre** — per-ticket discussion threads, SLA escalation, satisfaction ratings.
- **One-way sync to SchoolToday** — the school's other management system stays current, with drift detection to catch manual edits before they get overwritten.
- **Operational automation** — reminders, age-group promotion, admin digests, error alerts — all without a human needing to trigger them.

## Where to go from here

- Deploying, secrets, and hosting are managed by the IT team — see [CI/CD Pipeline](#cicd-pipeline--deployment) below for how it works.
- If you're going to work on the code itself, the rest of this document (Part 2) walks through the actual architecture.

---

# Part 2 — Technical deep dive

## Tech stack

| Layer | Choice |
|---|---|
| Language / runtime | Python 3.13 (`asyncio`), see [`runtime.txt`](runtime.txt) |
| Telegram framework | [`aiogram`](https://docs.aiogram.dev/) v3.x, **webhook mode only** (no long polling in production) |
| Web server | FastAPI + Uvicorn (`main.py`), wraps the aiogram dispatcher behind an HTTP endpoint |
| Database | Google Cloud Firestore (native mode), accessed via `firebase-admin` / `google-cloud-firestore` (async client) |
| AI document check | Vertex AI — Gemini Vision (`gemini-3.5-flash-lite`) |
| Background jobs | Google Cloud Tasks (async queue) + Google Cloud Scheduler (cron) |
| Hosting | Google Cloud Run (source-based deploy via Buildpacks — no `Dockerfile`; run command comes from the [`Procfile`](Procfile)) |
| Region | `europe-west3` (Frankfurt) |
| Scaling | `min-instances=1`, `max-instances=5`, 512Mi memory, dynamic CPU |
| CI/CD | GitHub Actions, deploys on every push to `main` |
| External integrations | SchoolToday (Open API v1), Notion |

> The live Cloud Run service is named `svitlo-auth-bot` (see [`.github/workflows/deploy.yml`](.github/workflows/deploy.yml)) — the name predates some of the bot's current responsibilities and hasn't been renamed since.

## Request lifecycle

Every Telegram update (a message, button tap, etc.) arrives as a single HTTP `POST /` to the FastAPI app in [`main.py`](main.py):

1. **Webhook secret check** — the request must carry the `X-Telegram-Bot-Api-Secret-Token` header matching `WEBHOOK_SECRET`, or it's rejected with `401`. This is what stops anyone but Telegram from injecting fake updates.
2. **Parse & dispatch** — the JSON body is parsed into an aiogram `Update` and handed to `dp.feed_update(bot, update)`, which the app `await`s to completion before responding. Cloud Run freezes a container's CPU once it responds, so the handler must fully finish first — anything slower is pushed onto Cloud Tasks instead (see [Background work](#background-work-cloud-tasks-vs-cloud-scheduler)).
3. **Middleware chain** (in registration order, `main.py`):
   - `LoadDataMiddleware` — looks the sender up in Firestore by Telegram ID, blocks them outright if `stage == "blocked"`, keeps their `@username` fresh, and exposes the loaded student record + roles to the rest of the request via `contextvars` (`core/context.py`).
   - `TicketConflictNoticeMiddleware` — warns a user if they have an open support ticket but are currently mid-flow somewhere else in the bot (their message would otherwise silently miss the curator).
4. **Routing** — routers registered in [`bot/handlers.py`](bot/handlers.py) (`tester_router`, registration, age-group, `private_router`, `public_router`, `support_router`, `fallback_router`) handle the update. `RequireAuthMiddleware` (`bot/middleware.py`) additionally gates the private router: only active students/alumni or staff roles (`boss`, `teacher`) get through; anyone else is redirected into the sync/registration flow.
5. **Always return `200`** — even on an unhandled exception, the webhook handler responds `200` and reports the error separately (see [Error reporting](#error-reporting)). Returning anything else would make Telegram retry-storm the same failing update.

A global `@dp.errors()` handler (`main.py`) catches anything a specific handler didn't: transient Telegram API hiccups (timeouts, flood limits, stale callbacks) are logged and swallowed silently, while genuine bugs get reported to the admin chat and the user gets a generic "please retry" message instead of a hang.

## Statelessness: why FSM state lives in Firestore

Cloud Run can spin a request up on any container instance, and idle instances get recycled — so **nothing about a user's in-progress conversation can live in memory**. aiogram's Finite State Machine (used to track a user's current step in a multi-message flow like registration) normally defaults to an in-memory store, which would silently break here: a user progressing through a form could get routed to a fresh container with no memory of where they left off.

`bot/fsm_storage.py` replaces that default with `FirestoreStorage`, a custom implementation of aiogram's `BaseStorage` backed by the `FSM_Sessions` Firestore collection (keyed by Telegram user ID). Every `state.set_state()` / `state.update_data()` call is a Firestore write; every state check is a Firestore read. It also actively cleans up: a session document with no state and no data left deletes itself rather than accumulating garbage.

This statelessness requirement runs through the whole codebase — no global variables, no local caches of per-user data, no long-lived in-process locks across requests.

## Data model (Firestore collections)

| Collection | Purpose |
|---|---|
| `Svitlo` | The core table: one flat document per lead/student, doc ID format `SV-YYMMDD-XXXXXXXX`. Holds personal info, parent/guardian info, stage, roles, SchoolToday linkage IDs, AI verification results, everything. |
| `StageEvents` | Append-only log of every stage transition (`lead` → `personal_data` → … → `student`/`blocked`). `Svitlo.stage` only holds the *current* stage, so this is the only place funnel-conversion history exists. |
| `SupportCentreTickets` | Helpdesk tickets — category, linked forum thread ID, message history, status, curator, NPS rating. |
| `FSM_Sessions` | aiogram conversation state, described above. |
| `Config/bot_settings` | A single settings document: current semester, term start date, the tester allow-list, and whether registration is currently open. |
| `SyncState` | Per-student snapshot of exactly what was last pushed to SchoolToday — the baseline the drift detector compares against. |
| `FailedEnrollments` | Log of SchoolToday enrollment attempts that failed, for staff follow-up. |

## Registration funnel & access control

The registration flow (`bot/reg_funnel.py`, states defined in `bot/states.py`) is a **linear, resumable** form: personal details → location/displacement status → parent/guardian details → lead source → health disclosures → a short school-rules quiz → document scan → staff review. Every answer is written straight to the `Svitlo` document (flat schema, not nested) as soon as it's collected, so a user can close Telegram mid-form and pick back up exactly where they left off — state comes from Firestore, not from memory.

Access control is stage- and role-driven, not command-based:
- `stage` moves a user through `lead` → `personal_data` → `admin_review` → `student` (or `blocked`, `alumni`).
- `roles` is a free-form list (`itt`, `scl`, `buddy`, `prefect`, `student`, plus staff-only roles like `boss`/`teacher`) read straight from Firestore on every request via `LoadDataMiddleware`.
- `RequireAuthMiddleware` is the actual gate on the private router: active students/alumni or staff roles pass; anyone else gets bounced into an email-sync prompt or a "finish registering first" message.

## Document verification pipeline

Document scanning happens through a **Telegram Mini App** (`api/webapp_routes.py` + `api/scanner.html`), not a regular chat message — this gives access to the phone camera. The flow:

1. **Authenticate the Mini App request.** Telegram signs the WebApp's `initData` payload; the backend recomputes the HMAC-SHA256 signature using the bot token and rejects anything that doesn't match, plus anything older than one hour (`MAX_INITDATA_AGE`) to prevent replay.
2. **GeoIP check.** The client's IP is looked up (`ip-api.com`); a Russian result blocks the account immediately, with the full GeoIP response (ISP, ASN, proxy/hosting flags) recorded as the block reason.
3. **Device timezone check.** The Mini App reports the phone's timezone; anything in `BLOCKED_TIMEZONES` (Russian timezones) blocks the account the same way, independently of the GeoIP result.
4. **AI document check.** The uploaded image goes to Gemini Vision (Vertex AI) with a strict-JSON prompt asking whether it's a genuine Ukrainian identity document, whether it carries any Russian state markers, a confidence score, and the name/date of birth as printed. The full model response is saved to the student's record regardless of outcome — so a later appeal or manual override has something to look at.
5. **Routing the result:**
   - Russian markers detected → blocked, with the model's full reasoning as the block reason.
   - Not recognized as a Ukrainian document → rejected, user asked to rescan.
   - Confidence ≤ 60% → rejected, user asked to improve lighting/rescan.
   - Otherwise → moved to `admin_review`; a staff member gives the final sign-off in the external admin panel (see below).

## Background work: Cloud Tasks vs. Cloud Scheduler

Telegram (and Cloud Run) expect a webhook to respond immediately — a slow handler risks a `504`/`408` and Telegram re-delivering the same update, causing duplicate processing. Anything that talks to a slow external API or needs to happen later is pushed onto **Cloud Tasks** instead of run inline. The queue workers live in [`api/task_routes.py`](api/task_routes.py) (`/tasks/*`):

| Endpoint | Job |
|---|---|
| `/tasks/schooltoday_enroll` | Enrolls an approved student into SchoolToday (idempotent via `externalID`; permanent 4xx failures don't retry, 5xx/network errors do) |
| `/tasks/send_reminder` | 24h/48h nudges to leads who started but didn't finish registering |
| `/tasks/sla_check` | Escalates a support ticket to the main curator if it's gone 30 minutes unanswered |
| `/tasks/export_notion` | Pushes data to Notion |
| `/tasks/delete_messages` | Background bulk message cleanup |
| `/tasks/delete_ticket_thread` | Deletes a closed ticket's forum thread after a grace period, so staff get a last look before it disappears |
| `/tasks/admin_review_digest` | Twice-daily (Cloud **Scheduler**, not Cloud Tasks — cron `0 9,21 * * *` Europe/Kyiv) summary to staff: how many applications are waiting, and how many students have aged into the next group |

The Cloud Scheduler job itself is provisioned by the deploy pipeline (see below) rather than by hand.

## External integrations

### SchoolToday (student records system)

`core/schooltoday.py` is a thin REST client for SchoolToday's Open API v1. A few load-bearing conventions:
- **Idempotency key**: every student/parent record's `externalID` is derived from our own Firestore doc ID (or a normalized phone number for parents) — so retried enrollment requests never create duplicates.
- **Create vs. update**: `PUT` creates, `PATCH` merges. `PUT` is never used against an existing record, because it would wipe fields not present in the payload.
- **Custom fields are matched by numeric ID, not name** — the school has renamed its custom fields multiple times, so the client resolves the current name from a cached registry rather than hardcoding it.

Sync is intentionally **one-way**: Firestore is the source of truth, and changes only flow *to* SchoolToday, never back. This is a deliberate design choice, not a limitation — it means the bot never has to resolve a conflicting write.

Two related tools build on that client:
- `core/sync_ops.py` — computes and (with `--apply`) pushes the diff between Firestore and SchoolToday, then records exactly what it pushed into the `SyncState` collection.
- `core/drift_ops.py` — three-way comparison (`SchoolToday now` vs. `what we last pushed` vs. `Firestore now`) that separates "someone edited it by hand in SchoolToday" from "we have an unpushed change" from genuine conflicts needing a human decision. Run this before a sync to avoid silently overwriting manual corrections.

Both live in `core/` rather than `scripts/` specifically because the running bot needs them too (see [Operational scripts](#operational-scripts-scripts) below) — `scripts/` is excluded from the deployed container.

### The external admin panel ("Solar Panel")

Staff review and trigger sync operations through a separate admin panel application (not in this repo). It talks to this service's `/admin/*` endpoints (`api/admin_routes.py`), authenticated with a shared `X-Admin-Secret` header:

- `POST /admin/sync/drift`, `/admin/sync/preview`, `/admin/sync/apply`
- `POST /admin/age-promotion/preview`, `/admin/age-promotion/apply`

These endpoints run the exact same `core/sync_ops.py` / `core/drift_ops.py` / `core/age_promotion.py` logic the console scripts use, capture their stdout, and return it as text — one source of truth for "what does a sync actually do," whether it's triggered from a terminal or a button in the panel.

### Age promotion

`core/age_promotion.py` automatically identifies students in the "younger" age group who've turned 14 and (on `--apply`) moves them to "older," notifies them, and triggers a SchoolToday sync. The twice-daily admin digest flags how many students are currently eligible, since the actual promotion run is a deliberate, staff-triggered action rather than a silent cron job.

### Notion

Application/ticket data can be exported to Notion via `core/utils.py::export_to_notion`, invoked asynchronously through the `/tasks/export_notion` queue worker so a slow Notion API call never blocks a webhook response.

## Support Centre (helpdesk)

Every ticket (`SupportCentreTickets`) gets its **own Telegram forum topic** (a dedicated thread) inside the curator group, color-coded by category (technical, educational, organizational, registration). This replaced an earlier design where all tickets of one category shared a single thread — per-ticket threads mean nothing gets lost in a crowded conversation. A ticket can be assigned to a curator, accumulates the back-and-forth as message arrays, escalates automatically after 30 minutes unanswered, and — once closed — collects an NPS rating before its thread is cleaned up.

## Error reporting

`core/error_reporting.py` is the bot's only error-observability mechanism: any unhandled exception, wherever it occurs, gets formatted (with the tail of the traceback, since Telegram caps messages at 4096 characters) and sent to `ADMIN_GROUP_ID`. To keep that chat usable during an incident it self-limits: the same exception won't repeat within a 5-minute window, and no more than 20 distinct error messages get sent per hour (with a running "N more suppressed" count).

## CI/CD pipeline & deployment

[`deploy.yml`](.github/workflows/deploy.yml) triggers on every push to `main`:

1. Authenticates to GCP with a dedicated service account (`GCP_SA_KEY` secret).
2. `gcloud run deploy svitlo-auth-bot --source . --region europe-west3 …` — a **source-based Cloud Run deploy**: there's no `Dockerfile`, so Google Cloud's Buildpacks detect the Python app and use the [`Procfile`](Procfile)'s `web: uvicorn main:app` line as the run command.
3. Secrets (`BOT_TOKEN`, `SERVICE_URL`, `NOTION_TOKEN`, `WEBHOOK_SECRET`, `WEBAPP_URL`, `SCHOOL_TODAY_API_KEY`) are injected via `--update-env-vars` — deliberately *not* `--set-env-vars`, which would wipe any variable set by hand between deploys (like `ADMIN_PANEL_SECRET`, which isn't managed by this pipeline).
4. Idempotently ensures the `admin-review-digest` Cloud Scheduler job exists (creates it, or updates it if it's already there) so the twice-daily staff digest keeps running without manual setup.

No separate staging environment exists — every merge to `main` is live.

## Operational scripts (`scripts/`)

A toolbox of one-off/maintenance scripts, documented in detail in [`scripts/README.md`](scripts/README.md). They're deliberately excluded from the deployed container (`.gcloudignore`) even though they stay in git — production never calls them directly, and keeping them out of the container shrinks both the deploy and the attack surface. Anything a script needs that the *running bot* also needs (SchoolToday sync/drift logic, age promotion) lives in `core/` instead, and the scripts just call into it.

Every script is labeled by how dangerous it is:

| | What it does | Safety |
|---|---|---|
| 🟢 | Read-only (`audit_firestore`, `audit_data_quality`, `test_schooltoday_*`, `verify_backfill`, `drift_report`) | Safe to run anytime |
| 🟡 | Writes to Firestore (`backfill_firestore`, `fix_data_quality`, `enrich_from_leads`, `promote_by_age`, …) | Dry-run by default; needs an explicit `--apply` |
| 🔴 | Writes to SchoolToday, the school's live production database | No undo — requires deliberate confirmation |

## Local development

**1. Clone and enter the repo**

```bash
git clone https://github.com/passshokk/svitlo-admin-bot.git
cd svitlo-admin-bot
```

**2. Create a virtual environment and install dependencies**

```bash
python3 -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

**3. Configure environment variables**

Copy [`.env.example`](.env.example) to `.env` and fill in the values (get real ones from the IT team — never commit this file):

```
TEST_BOT_TOKEN=...          # a separate bot for local testing, so you don't touch prod
BOT_TOKEN=...
NOTION_TOKEN=...
SERVICE_URL=...
WEBHOOK_SECRET=...
WEBAPP_URL=...
SCHOOL_TODAY_API_BASE_URL=...
SCHOOL_TODAY_API_KEY=...
ADMIN_PANEL_SECRET=...
```

You'll also need Google Cloud credentials available locally for Firestore/Vertex AI access — either run `gcloud auth application-default login`, or point `GOOGLE_APPLICATION_CREDENTIALS` at a service account key with Firestore + Vertex AI access for the `svitlo-auth-bot` project.

**4. Run the bot locally**

Production runs on webhooks, but locally it's simplest to run in long-polling mode with the test bot token:

```bash
python run_local.py
```

This starts the bot directly against Telegram with no HTTP server or public URL needed.

To instead run the full FastAPI app (e.g. to test the webhook, task, or admin routes) and receive real Telegram webhooks locally, you'll need a tunnel (e.g. `ngrok`) pointed at `uvicorn main:app --reload`, with `SERVICE_URL` set to the tunnel URL and `webhook_setup.py` run once to register it with Telegram.

**5. Known dependency quirk**

`google-api-core` is pinned below `2.35.0` in `requirements.txt` — that version broke default-database access for Firestore (`InvalidArgument: 400 Invalid database id %28default%29`), which silently breaks *everything* touching FSM state (i.e. the entire bot). See the comment in [`requirements.txt`](requirements.txt) for the full story before "helpfully" bumping it.
