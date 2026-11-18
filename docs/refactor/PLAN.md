# Refactor plan: ePortem as a multi-user service

Branch: `refactor/multiuser-service` (from `main` at `54477fa`, 2026-11-18).
Status: **plan only, no code changed yet.** Decisions with their reasons are
in [`DECISIONS.md`](DECISIONS.md). Update both as work lands, in the same
commit as the code.

## 1. Goals

1. **Own scheduler.** The service decides when to clock each user, including
   the random offset and the ±15 min window. No crontab, no `at`.
2. **Multi-user.** Each user has their own ePortem credentials, schedule,
   overrides (holiday, location, business trip), notification channels and
   session cookies.
3. **Web UI and API.** Users sign in to the web UI with a username and
   password. The API uses personal access tokens. Both do the same things.
4. **Docker.** One image, one port for the UI, the API, admin pages, status
   and metrics. It runs on `omv` or any Debian homelab host, and in the cloud.
5. **Ready to sell later.** Accounts can be checked and suspended, features can
   be limited per plan, and crashes and failed clocks get reported somewhere
   other than a cron mail.

Not goals for this refactor: payments, a mobile app, any way of getting past
reCAPTCHA other than the real browser login used today (ruled out in
`docs/http-api-investigation.md`).

## 2. Constraints

- **The live system must not break.** `main` runs on `omv` from cron with the
  owner's only ePortem account. Until cutover (phase 8), `main` and the cron
  path stay deployable, and nothing on this branch touches the real account.
- **There is only one ePortem account.** Development and tests use a fake
  ePortem server (section 5). The real account is only used in phase 8, and only
  after the old cron lines are off, so the old and new systems never both clock.
- **Keep what was learnt.** The HTTP clock flow (`utility/http_clock.py`): the
  `NotRecorded` / `OutcomeUnknown` split, re-reading the dashboard after a
  failed send, exact button IDs, the login budget, the browser that looks like
  a desktop one. Plus the never-raise follow-ups and secret scrubbing. This code
  gets moved and given its settings as arguments. It doesn't get rewritten.
- **Small host.** `omv` is an Intel N95 (4 cores, 15 GB RAM) already running
  around 30 containers. Chromium is only started for logins, and only a limited
  number at a time.
- **A previous attempt existed.** The archive tag
  `archive/web-ui-docker-mock-server` had a web UI, Docker files and a mock
  server. They were dropped because of debug mode on `0.0.0.0`, unauthenticated
  endpoints that returned credentials, and a mock whose login fields didn't
  match the real site. A deleted branch, `feature/user-auth-and-multiuser`
  (bundle on `omv` under `/home/pi/backups/`), had JWTs with default secrets.
  Look at both for ideas, but don't copy either.

## 3. Target architecture

```
            ┌───────────────────────── container: eportem ──────────────────────────┐
 browser ──▶│  FastAPI app (uvicorn)                                                │
 API     ──▶│   /            web UI (Jinja2 + htmx, session cookie + CSRF)           │
            │   /api/v1      JSON API (personal access tokens), OpenAPI at /api/docs │
            │   /admin       admin pages (role=admin)                                │
            │   /healthz /readyz /metrics                                            │
            │                                                                        │
            │  Scheduler (asyncio task, single leader via DB lock)                   │
            │   └─ plans each user's day → planned_runs rows (with jitter)           │
            │   └─ due runs → worker pool                                            │
            │  Workers                                                               │
            │   └─ HTTP clock (cheap, concurrent)                                    │
            │   └─ browser login (Chromium, semaphore = 1–2)                         │
            │   └─ notifications / Slack status / alerts                             │
            └──────────────┬──────────────────────────────────────┬──────────────────┘
                           │                                      │
                 SQLite (volume) or Postgres            eportem.es  /  fake-eportem
```

### Package layout

```
eportem/                  # new importable package (pyproject.toml)
  core/                   # no globals, no os.getenv, no files: pure logic + I/O clients
    clock_http.py         # from utility/http_clock.py; base_url, credentials, cookie store injected
    browser.py            # from utility/login_and_navigate.py + Selenium click path
    actions.py            # from eportem_action.py: perform(), HTTP→browser fallback rules
    schedule.py           # from main.py: validation, windows, which action is due
    overrides.py          # holiday / location / business trip as data, not files
    notify/               # Telegram, Slack (webhook/bot/user), scrubbing
    errors.py
  db/                     # SQLAlchemy models, Alembic migrations, encryption helpers
  scheduler/              # planner, dispatcher, leader lock, verify-day job
  web/                    # FastAPI app: auth, UI routes, API routes, admin, templates
  ops/                    # metrics, Sentry, structured logging, heartbeat
  cli.py                  # `eportem serve|migrate|create-admin|import-legacy|check`
fake_eportem/             # the test double for eportem.es (section 5)
legacy/                   # today's scripts, kept working until cutover, then removed
```

The scripts at the top of the repo (`main.py`, `eportem_action.py`, ...) become
thin shims over `eportem.core` in phase 1, so cron on `omv` keeps working from
the same code until cutover.

### Data model (first cut)

| Table | Key fields | Notes |
|---|---|---|
| `users` | id, email, username, password_hash (argon2id), role (`admin`/`user`), status (`pending`/`active`/`suspended`), email_verified_at, plan, timezone (default `Europe/Madrid`), created_at | Status and plan are the hooks for monetising later |
| `api_tokens` | id, user_id, name, prefix, token_hash (sha256), scopes, last_used_at, expires_at, revoked_at | Shown once. Format `ept_<prefix>_<secret>` |
| `web_sessions` | id, user_id, created_at, expires_at, ip, user_agent | Server-side sessions; cookie holds only the id |
| `eportem_accounts` | user_id, username, password_enc, home_activity_id (default 1293), office_activity_id (default 1), lunch_pause_id (default 2), verified_at, last_login_at | Activity IDs are per account, not constants |
| `eportem_sessions` | user_id, cookies_enc, user_agent, logged_in_at, last_used_at | Replaces `config/.session_cookies.json` |
| `schedules` | user_id, weekday, location, start_day, lunch_break, after_lunch, stop_day, enabled | Same rules as today's `config.json` |
| `overrides` | id, user_id, kind (`holiday`/`location`/`business_trip`), start_date, end_date, location | Replaces the three `*_override.txt` files |
| `notification_channels` | id, user_id, kind (`telegram`/`slack_webhook`/`slack_bot`/`slack_user`), config_enc, notify, alerts, slack_status | Per user |
| `planned_runs` | id, user_id, date, action, target_time, planned_at (with jitter), status (`planned`/`running`/`recorded`/`not_recorded`/`unknown`/`skipped`/`failed`), via (`http`/`browser`), attempt, started_at, finished_at, error | **Unique (user_id, date, action)**: the guard against double clocking. Replaces `logs/actions.log` |
| `run_logs` | run_id, text | The per-run output block that `logs/http_clock.log` holds today, scrubbed |
| `audit_events` | id, user_id, actor, kind, detail, at | Logins, token changes, config changes, admin actions |
| `scheduler_lock` | name, holder, heartbeat_at | Only one scheduler runs (matters with Postgres and more than one replica) |

Secrets (`password_enc`, `cookies_enc`, `config_enc`) are encrypted with
Fernet using a key from `EPORTEM_SECRET_KEY` (env or Docker secret). Losing the
key means every user has to enter their credentials again. That is
documented, and so is rotating it (`MultiFernet`).

## 4. Behaviour that must carry over

These are what today's code does on purpose. Each one gets a test in the new
code that is named after it.

- An action fires only inside ±`WINDOW_MINUTES` (15) of its target. The planner
  picks a random time between target − 5 min and target + 4 min, the same spread
  as today's cron lines (base = target − 5, `RANDOM % 10` minutes).
- Holiday: skip clocking and set the Slack status "On holiday". If the holiday
  data can't be read, refuse to clock.
- Location override for one day. Business trip: clock as usual, Slack status
  stays "On a business trip".
- HTTP first. Fall back to the browser only on `NotRecorded`. `OutcomeUnknown`
  and unexpected errors fail without a retry and send an alert.
- Login budget: at most 4 form submissions per run. Selenium retries for up to
  10 minutes when the button isn't there. Never click when the state shows the
  action doesn't apply.
- Follow-ups (notifications, Slack status) never fail a recorded run. Secrets
  are scrubbed from every message and log.
- Verify-day at 18:40 local time. Missing or doubled actions send an alert.
- `EPORTEM_ENABLED` becomes a per-user "paused" switch plus a global one.

## 5. Working without a second ePortem account

The answer is a **fake ePortem server** (`fake_eportem/`), built from the real
pages, plus contract tests. It is a small FastAPI app that copies the parts of
`eportem.es` we use:

- `GET/POST /Usuario/Login?ReturnUrl=...`: the same form fields as the real page
  (`login-form`, `usuario`, `password`, `recaptchaToken`, `cc`, `recordar`,
  `#submit`) and a stub `grecaptcha` script. Several accounts are configured in
  the fake. Switches let tests make a login fail on purpose: wrong password,
  the reCAPTCHA error text, slow responses.
- `GET /aplicaciones/e-portem/registro/`: the dashboard. Its `buttonsRegBox`
  markup matches the captured states (not started, working, paused, stopped).
  Each fake account keeps its own clock state.
- `GET .../reghorario.cshtml?action=...`: changes the state and returns the
  JSON (`isActive`, `LastDescAct`, `listActiv`).
- Ways to inject faults: 500 errors, a maintenance page served with status 200,
  read timeouts *after* the event is recorded (to test `OutcomeUnknown`),
  sessions that expire after N minutes, a missing button.
- `GET /_fake/events`: every clock event the fake recorded, so tests can check
  that each user was clocked exactly once.

So the fake can't drift the way the old mock server did:

1. **Its markup comes from real pages.** The HTML fixtures are the ones in
   `tests/test_http_clock.py` (`NOT_STARTED_HTML`, ...), taken from captures
   with personal data removed. Both the unit tests and the fake read them from
   one place, `fake_eportem/fixtures/`.
2. **Contract test against the real site, read-only.** A manually-triggered
   check, `eportem check-contract`, uses the owner's account. It logs in (only
   when the saved session is gone), fetches the login page and the dashboard,
   and compares field names, `buttonsRegBox` structure and button
   `id`/`name` attributes with the fixtures. **It never calls
   `reghorario.cshtml`.** It runs on `omv`, at a time no cron line is due, and
   reuses the saved session.
3. **The URL is configurable** (`EPORTEM_BASE_URL`, default
   `https://eportem.es`). It is a global setting, not a per-user one, so a user
   can't point the server at an arbitrary host.

Other ways to cover the gap:

- **Time is injected** (a `Clock` interface). Scheduler tests run a simulated
  week for 50 users in seconds.
- **`docker compose --profile dev`** starts `eportem` with `fake-eportem` and a
  Selenium-capable image. The full browser login path then runs against the
  fake end to end.
- **Shadow mode before cutover** (phase 8). The new service runs on `omv` with
  the owner's real schedule but with `dry_run=true`. It plans, and at each due
  time it logs what it *would* send. The service runs with the real-account
  connection turned off (`EPORTEM_BASE_URL` points at the fake), so it doesn't
  make a second session. Afterwards, `logs/actions.log` from the live cron is
  compared with the planned runs.

A friendly second ePortem user (a colleague) would be the best test of
multi-user behaviour against the real site. It's optional and only after
cutover. Activity IDs such as 1293 may differ per company, which is why they
are per-account fields that are found from the dashboard when the account is
verified.

## 6. Phases

Every phase ends with: all tests passing (old and new), README and these docs
updated, and a commit. The branch merges back into `main` only at phase 8, or
earlier in pieces if phase 1 turns out cleanly separable.

### Phase 0: groundwork (this commit + next)
- [x] Branch, baseline: 352 tests pass (`./run_tests.sh`, 2026-11-18).
- [ ] `pyproject.toml` (Python 3.13, the version on `omv` and in the image),
      `pytest` alongside today's unittest suite (pytest runs unittest cases),
      `ruff`, and coverage reporting.
- [ ] CI: a Gitea Actions workflow (or a `make check` if Gitea runners aren't
      set up) running lint + tests + the Docker build.

### Phase 1: pull out `eportem.core` (no behaviour change)
- Move the HTTP clock, browser login and click path, schedule/window logic,
  overrides and notifications into `eportem/core/`. Settings are passed in as
  arguments (`EportemAccount`, `NotificationConfig`, `CookieStore`,
  `base_url`, `clock`). No `os.getenv` inside core.
- Today's scripts become adapters. They read `.env`, `config.json` and the
  override files, build the objects and call core. Cron output, exit codes and
  log files stay byte-for-byte the same where tests check them.
- **Gate:** the whole old suite passes unchanged. The branch could be deployed
  to `omv` at this point, but that's optional.

### Phase 2: fake ePortem + contract check
- `fake_eportem/` as in section 5, a `fixtures/` directory shared with the
  tests, and `eportem check-contract`.
- End-to-end tests: core HTTP clock and Selenium login against the fake
  (Selenium tests marked `browser`, skipped when no Chromium is present).

### Phase 3: persistence
- SQLAlchemy 2 models, Alembic migrations, SQLite by default
  (`/data/eportem.db`, WAL mode), Postgres through `DATABASE_URL`.
- Encryption helpers. The `CookieStore` and settings come from the DB.
- `eportem import-legacy --user <name>`: reads `config/.env`, `config.json`,
  the override files, `.session_cookies.json` and `logs/actions.log` into the
  database for one user. It is idempotent and has a dry run.

### Phase 4: scheduler and workers
- **Planner.** At midnight (and on start-up, and whenever a user's
  schedule or override changes) it writes today's `planned_runs` for each
  active user, with random jitter. It skips holidays and works out the
  location then.
- **Dispatcher.** It wakes up for the next due run. It sets the row to `running`
  with a conditional update, runs `core.actions.perform`, and stores the
  outcome. The unique row per user, date and action means a restart or a second
  replica can't clock twice.
- **Restart rules.** A run left `running` from a crash becomes `unknown`
  and sends an alert, never a retry (same idea as `OutcomeUnknown`). A
  `planned` run whose window was missed while the service was down becomes
  `skipped` and sends an alert. It is never clocked late.
- At most `BROWSER_CONCURRENCY` (default 1) browser logins at once, and HTTP
  clocks have their own limit. Logins due soon are spread out so ten users at
  09:00 don't start ten Chromiums together.
- Verify-day is a scheduled job for each user, reading `planned_runs`.
- Leader lock in `scheduler_lock`, so a second replica only serves the web UI
  and API.

### Phase 5: auth and API
- Passwords: argon2id (`argon2-cffi`). Sign-in is rate-limited for each user
  and each IP. The session cookie is `HttpOnly` and `SameSite=Lax`, with
  `Secure` when served over HTTPS, and there is CSRF protection on forms.
- Personal access tokens: only their hash is stored. Each has scopes (`read`,
  `write`, `admin`), an optional expiry, can be revoked, and records when it
  was last used.
- First admin through `eportem create-admin` (or `EPORTEM_ADMIN_*` env on first
  start). Registration: `closed` (default), `invite`, or `open` plus email
  verification.
- API `/api/v1`: `me`, `eportem-account` (set, verify with a test login that
  doesn't clock), `schedule`, `overrides`, `channels` (with "send test"),
  `runs` (history, today's plan), `runs/{id}/log`, `actions/{action}` (clock
  now, by hand, with confirmation), `tokens`. Admin endpoints: `users`,
  suspend/activate, `stats`.
- Every API change is written to `audit_events`. Secrets are never returned:
  they can be set but not read back.

### Phase 6: web UI
- Server-rendered Jinja2 with htmx. No JS build step. Pages: sign in, today
  (the plan and status of each run), schedule editor, overrides calendar,
  ePortem account (with "verify"), notifications (with "send test"), history
  and run logs, API tokens, profile/password.
- Admin: users, runs that failed or are `unknown` across users, scheduler
  health, browser queue, version, and the audit log.

### Phase 7: packaging and operations
- `Dockerfile`: `python:3.13-slim-trixie` plus Debian's `chromium` and
  `chromium-driver` (the same packages as on `omv` today), a non-root user,
  `tini`, and a `HEALTHCHECK` against `/healthz`. Multi-arch (amd64 + arm64).
  The image is pushed to the Gitea container registry.
- `docker-compose.yml`: the `eportem` service, a `/data` volume, the secret key
  from a file, and `profiles: [dev]` for `fake-eportem`. On `omv` it sits
  behind the existing nginx-proxy-manager for TLS. Only that proxy is exposed.
- Observability:
  - Logs: structured JSON on stdout, with `user_id` and `run_id` and secrets
    scrubbed.
  - Metrics: `/metrics` in Prometheus format, protected by a token. Includes
    runs by outcome, clock latency, browser logins, session age at login,
    scheduler lag and notification failures.
  - Errors: the Sentry SDK, off unless `SENTRY_DSN` is set. It works with
    sentry.io or self-hosted GlitchTip, and personal data is removed before
    sending.
  - Dead-man switch: an optional `HEARTBEAT_URL` (healthchecks.io style) is
    pinged every minute while the scheduler is healthy. That covers "the whole
    container died", which the service can't report itself.
  - Failure alerts to the user's own channels as today, plus an admin alert
    channel.
- Backups: `eportem backup` (SQLite `.backup` into `/data/backups`, rotated),
  documented with the restore steps.

### Phase 8: cutover on `omv`
1. Deploy the container in **shadow mode** (`dry_run`, fake base URL) for at
   least 3 working days. Compare its planned runs with the live
   `logs/actions.log` each day.
2. `eportem import-legacy` for the owner. Check the imported schedule,
   overrides and channels in the UI.
3. Switch over at a quiet time (mid-morning or mid-afternoon). Comment out the
   ePortem crontab lines and back up the crontab first. Then turn off
   `dry_run` and point at `https://eportem.es`. The same session cookies are
   imported, so the first run doesn't need a browser login.
4. Watch the first full day: each run, verify-day at 18:40, and the alerts.
5. **Rollback:** stop the container and restore the crontab. The legacy
   scripts are still on disk, and `config/.env` hasn't changed.
6. After two clean weeks, delete `legacy/` and the cron-specific docs, and
   rewrite the operations sections of README and CLAUDE.md.

### Phase 9: groundwork for selling it (after cutover, when wanted)
- Entitlements in one place (`can_clock(user)`, users per instance, channels
  per plan) that the scheduler and API both check.
- Account checks: verified email, admin approval or invite codes, and a working
  ePortem login before the account is enabled. Users whose ePortem login keeps
  failing for N days are suspended automatically.
- Billing (Stripe Checkout + webhook → `users.plan`/`status`) only when there
  is a buyer. Self-hosted licence keys (Ed25519-signed, checked offline) only
  if self-hosting is ever sold.
- Data protection: the service stores other people's employer credentials and
  working-time data. It needs a privacy policy, account deletion and export, a
  record of where data is processed, and a decision on whether it can be
  offered at all (see the risks below).

## 7. Risks and open questions

| # | Risk / question | Plan |
|---|---|---|
| R1 | **reCAPTCHA scores from cloud IPs.** Logins from datacenter IPs may be rejected where `omv`'s home IP passes. | Measure it with the contract check from a cloud VM before advertising cloud hosting. Logins stay rare (session reuse), which helps. |
| R2 | **Many users behind one IP** may look like abuse to ePortem. | Spread logins out, keep the login budget per user, and alert on any reCAPTCHA rejection. |
| R3 | **Selling a tool that automates the official working-time record** (Registro de jornada, RD-ley 8/2019) and logs in to a third-party service on users' behalf could break ePortem's terms or employer policies. | Get legal advice before phase 9. That is the owner's call, not an engineering one. |
| R4 | Activity IDs (`1293`, `1`, `2`) may differ per company. | Per-account fields, found from the dashboard when the account is verified. |
| R5 | SQLite with several replicas. | One replica on SQLite. Postgres is needed for more than one. Documented. |
| R6 | Chromium memory on `omv`. | Browser concurrency 1 by default, Chromium closed after each login, container memory limit. |
| Q1 | Gitea Actions runner available on `omv`? | Check in phase 0; fallback is `make check` run before each push. |
| Q2 | Hostname for the UI (e.g. `eportem.<home domain>` through nginx-proxy-manager), and LAN only or public? | Owner decides before phase 7. LAN/VPN only is recommended until auth has been reviewed. |
| Q3 | Error tracking: sentry.io free tier, or self-hosted GlitchTip on `omv`? | Owner decides before phase 7. The code works with either. |

## 8. Definition of done (whole refactor)

- No crontab entries for ePortem on `omv`. The container runs the owner's
  schedule, and two clean weeks have been seen in `planned_runs` and
  verify-day.
- A second user can be added via the UI, verified against the fake, and gets
  their own schedule, overrides and notifications. Tests prove users are kept
  apart: a user cannot read or change another user's data through the UI or
  the API.
- `docker compose up` on a clean Debian host gives a working instance after
  `eportem create-admin`.
- Tests: unit, scheduler simulation, API/auth (including authorization
  checks), end to end against the fake (HTTP and browser), migration upgrade
  and downgrade. All pass in CI. Coverage is reported, with a 85% floor for
  `eportem/core` and `eportem/scheduler`.
- README describes the service. CLAUDE.md describes the container
  operations. DECISIONS.md is up to date.
