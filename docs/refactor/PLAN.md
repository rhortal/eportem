# Refactor plan: ePortem as a multi-user service

Branch: `refactor/multiuser-service` (from `main` at `54477fa`, 2026-11-18).
Status: **plan only, no code changed yet.** Decisions with their reasons are
in [`DECISIONS.md`](DECISIONS.md). Update both as work lands, in the same
commit as the code.

## 1. Goals

1. **Own scheduler.** The service decides when to clock each user, including
   the random offset and the ±15 min window. No crontab, no `at`.
2. **Multi-user.** Each user has their own ePortem credentials, schedule,
   home/office days, time off, notification channels and session cookies.
3. **Web UI and API.** Users sign in to the web UI with a username and
   password. The API uses personal access tokens. Both do the same things.
4. **Docker.** One image, one port for the UI, the API, admin pages, status
   and metrics. It runs on any Debian homelab host or NAS, and in the cloud.
5. **Ready to sell later.** Accounts can be checked and suspended, features can
   be limited per plan, and crashes and failed clocks get reported somewhere
   other than a cron mail.
6. **Easy schedules.** Pick a working-day template (European 9–18, Spanish
   split day, summer hours, ...), mark which days are home or office, and change
   a single day in one click. See section 5.
7. **Portable open source.** No hostnames, IPs, email addresses, domains,
   company-specific IDs or personal settings in the code or the image.
   Everything that differs between installs is a setting. See section 6.

Not goals for this refactor: payments, a mobile app, any way of getting past
reCAPTCHA other than the real browser login used today (ruled out in
`docs/http-api-investigation.md`).

## 2. Constraints

- **The live system must not break.** `main` runs from cron on the owner's
  host, with the owner's only ePortem account. Until cutover (phase 8), `main`
  and the cron path stay deployable, and nothing on this branch touches the
  real account.
- **There is only one ePortem account.** Development and tests use a fake
  ePortem server (section 7). The real account is only used in phase 8, and only
  after the old cron lines are off, so the old and new systems never both clock.
- **Keep what was learnt.** The HTTP clock flow (`utility/http_clock.py`): the
  `NotRecorded` / `OutcomeUnknown` split, re-reading the dashboard after a
  failed send, exact button IDs, the login budget, the browser that looks like
  a desktop one. Plus the never-raise follow-ups and secret scrubbing. This code
  gets moved and given its settings as arguments. It doesn't get rewritten.
- **Small hosts.** The reference homelab host is an Intel N95 (4 cores, 15 GB
  RAM) already running around 30 containers. Chromium is only started for
  logins, and only a limited number at a time.
- **A previous attempt existed.** The archive tag
  `archive/web-ui-docker-mock-server` had a web UI, Docker files and a mock
  server. They were dropped because of debug mode on `0.0.0.0`, unauthenticated
  endpoints that returned credentials, and a mock whose login fields didn't
  match the real site. A deleted branch, `feature/user-auth-and-multiuser`
  (bundle kept on the owner's host), had JWTs with default secrets. Look at
  both for ideas, but don't copy either.

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
            │   └─ resolves each user's calendar → planned_runs rows (with jitter)   │
            │   └─ due runs → worker pool                                            │
            │  Workers                                                               │
            │   └─ HTTP clock (cheap, concurrent)                                    │
            │   └─ browser login (Chromium, semaphore = 1–2)                         │
            │   └─ notifications / Slack status / alerts / email                     │
            └──────────────┬──────────────────────────────────────┬──────────────────┘
                           │                                      │
                 SQLite (volume) or Postgres         EPORTEM_TARGET_URL (eportem.es or the fake)
```

### Package layout

```
eportem/                  # new importable package (pyproject.toml)
  settings.py             # every instance setting, one place (section 6)
  core/                   # no globals, no os.getenv, no files: pure logic + I/O clients
    clock_http.py         # from utility/http_clock.py; target URL, credentials, cookie store injected
    browser.py            # from utility/login_and_navigate.py + Selenium click path
    actions.py            # from eportem_action.py: perform(), HTTP→browser fallback rules
    calendar.py           # resolves a user's day: template, location, time off, holidays (section 5)
    templates.py          # built-in schedule templates, validation
    notify/               # Telegram, Slack (webhook/bot/user), email, scrubbing
    errors.py
  db/                     # SQLAlchemy models, Alembic migrations, encryption helpers
  scheduler/              # planner, dispatcher, leader lock, verify-day job
  web/                    # FastAPI app: auth, UI routes, API routes, admin, templates, i18n
  ops/                    # metrics, Sentry, structured logging, heartbeat
  cli.py                  # `eportem serve|migrate|create-admin|import-legacy|config|check-contract`
fake_eportem/             # the test double for eportem.es (section 7)
legacy/                   # today's scripts, kept working until cutover, then removed
```

The scripts at the top of the repo (`main.py`, `eportem_action.py`, ...) become
thin shims over `eportem.core` in phase 1, so cron on the owner's host keeps
working from the same code until cutover.

### Data model (first cut)

| Table | Key fields | Notes |
|---|---|---|
| `users` | id, email, username, password_hash (argon2id), role (`admin`/`user`), status (`pending`/`active`/`suspended`), email_verified_at, plan, timezone, locale, paused, created_at | Status and plan are the hooks for monetising later. Timezone and locale default to the instance settings |
| `api_tokens` | id, user_id, name, prefix, token_hash (sha256), scopes, last_used_at, expires_at, revoked_at | Shown once. Format `ept_<prefix>_<secret>` |
| `web_sessions` | id, user_id, created_at, expires_at, ip, user_agent | Server-side sessions; cookie holds only the id |
| `eportem_accounts` | user_id, username, password_enc, office_activity_id, home_activity_id, lunch_pause_id, verified_at, last_login_at | Activity IDs are found from the dashboard when the account is verified; no hard-coded defaults |
| `eportem_sessions` | user_id, cookies_enc, user_agent, logged_in_at, last_used_at | Replaces `config/.session_cookies.json` |
| `schedule_templates` | id, owner_user_id (null = built-in), key, name, description, days (JSON: weekday → start/lunch/back/stop or `off`), jitter_before, jitter_after | Built-ins are read-only; users copy and edit (section 5) |
| `user_schedule` | user_id, default_template_id, location_pattern (JSON: weekday → `home`/`office`, or an A/B fortnight), holiday_region | One per user |
| `schedule_periods` | id, user_id, template_id, start_date, end_date, recurring_yearly, label | e.g. summer hours every 1 Jul–31 Aug |
| `day_overrides` | id, user_id, start_date, end_date, kind (`time_off`/`location`/`business_trip`/`times`/`work_on_holiday`), location, times (JSON), note | Replaces the three `*_override.txt` files; one row can cover a range |
| `local_holidays` | id, user_id, date, name | Local public holidays not in the regional calendar |
| `notification_channels` | id, user_id, kind (`telegram`/`slack_webhook`/`slack_bot`/`slack_user`/`email`), config_enc, notify, alerts, slack_status, status_texts (JSON) | Per user; Slack status texts and emoji can be changed |
| `planned_runs` | id, user_id, date, action, target_time, planned_at (with jitter), location, status (`planned`/`running`/`recorded`/`not_recorded`/`unknown`/`skipped`/`failed`), via (`http`/`browser`), attempt, started_at, finished_at, error | **Unique (user_id, date, action)**: the guard against double clocking. Replaces `logs/actions.log` |
| `run_logs` | run_id, text | The per-run output block that `logs/http_clock.log` holds today, scrubbed |
| `audit_events` | id, user_id, actor, kind, detail, at | Logins, token changes, config changes, admin actions |
| `scheduler_lock` | name, holder, heartbeat_at | Only one scheduler runs (matters with Postgres and more than one replica) |

Secrets (`password_enc`, `cookies_enc`, `config_enc`) are encrypted with
Fernet using the instance secret key (section 6). Losing the key means every
user has to enter their credentials again. That is documented, and so is
rotating it (`MultiFernet`).

## 4. Behaviour that must carry over

These are what today's code does on purpose. Each one gets a test in the new
code that is named after it.

- An action fires only inside ±window (default 15 min) of its target. The
  planner picks a random time between target − 5 min and target + 4 min by
  default, the same spread as today's cron lines (base = target − 5,
  `RANDOM % 10` minutes). Both can be changed per instance, and the jitter per
  template too. Validation keeps the jitter inside the window.
- Time off: skip clocking and set the "On holiday" Slack status. If the
  calendar can't be resolved, refuse to clock.
- Location override for a day. Business trip: clock as usual, and the Slack
  status stays "On a business trip".
- HTTP first. Fall back to the browser only on `NotRecorded`. `OutcomeUnknown`
  and unexpected errors fail without a retry and send an alert.
- Login budget: at most 4 form submissions per run. Selenium retries for up to
  10 minutes when the button isn't there. Never click when the state shows the
  action doesn't apply.
- Follow-ups (notifications, Slack status) never fail a recorded run. Secrets
  are scrubbed from every message and log.
- Verify-day after the last action of the day (default: 40 min after the
  user's stop time). Missing or doubled actions send an alert.
- `EPORTEM_ENABLED` becomes a per-user "paused" switch plus a global one.

## 5. Schedules: templates, home/office days, time off

### Ideas taken from other tools

| Tool | What it does well | What we take |
|---|---|---|
| Calendly / Google Calendar availability | A weekly hours grid with "copy to all days", plus changes for specific dates on top | Weekly template, and one-day changes made on a calendar |
| Google Calendar / Outlook "working location" | Home / office / elsewhere for each weekday, changed for one date with one click | Location pattern per weekday, and a one-click toggle for a single date |
| Spanish HR tools (Factorial, Sesame, Personio, ...) | Named work schedules picked from a list, summer hours (*jornada intensiva*) applied to a date range, regional public holidays loaded for you | Built-in templates, periods that repeat every year, and a holiday region |
| Cron-free schedulers (e.g. Healthchecks, GitHub Actions UI) | Always show "next run at ..." | A preview of the next 14 days, so it's clear what will happen and when |

### Templates

A template is a named working week: for each weekday, the four times (start,
lunch out, lunch back, stop), or a day with no lunch break (just start and
stop), or `off`. Built-ins are shipped as data (`eportem/core/templates.py`) and
are read-only. A user picks one and, if needed, clicks "customise", which saves
an editable copy.

| Key | Name | Mon–Thu | Fri |
|---|---|---|---|
| `european-9-18` | European day, 9–18 | 9:00, lunch 13:30–14:30, 18:00 | same |
| `spanish-9-18` | Spanish day, 9–18 | 9:00, lunch 14:30–15:30, 18:00 | same |
| `spanish-friday-short` | Spanish day, short Friday | 9:00, lunch 14:30–15:30, 18:00 | 8:00–15:00, no lunch |
| `summer-8-15` | Summer hours (*jornada intensiva*) | 8:00–15:00, no lunch | same |
| `continuous-8-16` | Continuous day | 8:00–16:00, no lunch | same |
| `part-time-morning` | Part-time mornings | 9:00–14:00, no lunch | same |

The owner's current `config/config.json` (9:00, 13:30, 14:30, 18:00) is the
`european-9-18` template. Days with no lunch break skip `lunch_break` and
`after_lunch`. That is already possible today by leaving the keys out.

### How a day is resolved

`core.calendar.resolve(user, date)` returns either a plan (times + location) or
a reason why nothing is clocked. The order, first match wins:

1. User paused, or account suspended → nothing.
2. `day_overrides` `time_off` covering the date → nothing ("On holiday" status).
3. A public holiday in the user's region (Python `holidays` package, country +
   region, e.g. `ES` + `MD`) or in `local_holidays` → nothing, unless a
   `work_on_holiday` override covers the date.
4. Times: a `times` override for the date, else the template of a
   `schedule_period` covering the date, else the default template.
5. Location: a `location` or `business_trip` override for the date, else the
   location pattern for that weekday (and A/B week), else `office`.

It is a pure function, tested on tables of dates. The UI preview, the API's
`GET /api/v1/calendar`, the planner and verify-day all use it, so they can't
disagree.

### Making it easy in the UI

- **First-run wizard:** ePortem account (with a test login that doesn't clock)
  → pick a template → tick home days on a Mon–Fri row → region for public
  holidays → notifications → a preview of the next two weeks → done.
- **"This week / next week" strip** on the home page: five day chips, each
  showing times and a home/office icon. Click a chip to switch home/office
  for that date only. Long-press or the menu for: day off, other times, business
  trip.
- **Month calendar** for time off and business trips: drag across days to make
  a range. Public holidays are shown and can be overridden.
- **Periods:** "Use *Summer hours* from 1 Jul to 31 Aug, every year".
- **Next runs:** each run planned for today, with its window and the exact
  time drawn once planned, and the status of each run as the day goes on.
- **iCal feed (optional):** a private, revocable URL with the planned clocks
  and time off, to subscribe to in any calendar app.
- UI in English and Spanish from the start, chosen per user, with the instance
  default from settings.

### Migration of today's files

`eportem import-legacy` maps `config.json` to a custom template (or to the
built-in one it matches exactly) plus a location pattern. It also maps
`holiday_override.txt` to `time_off`, `location_override.txt` to `location`
and `business_trip_override.txt` to `business_trip`.

## 6. Configuration and portability

The rule is: **the code and the image contain no install-specific values.**
Every hostname, URL, IP, email address, domain, company-specific ID, timezone
and credential comes from settings. Owner-specific values live only in the
owner's own, untracked `.env` / config file.

### How settings are given

- One settings module (`eportem/settings.py`, pydantic-settings) is the only
  place that reads the environment.
- Priority: environment variables (`EPORTEM_*`) > a mounted config file
  (`EPORTEM_CONFIG_FILE`, TOML) > defaults that are safe and neutral.
- Every secret also accepts `*_FILE` (e.g. `EPORTEM_SECRET_KEY_FILE`), so
  Docker and Kubernetes secrets work without putting values in the
  environment.
- Settings are checked on start-up. A missing required value or a bad one stops
  the container with one clear message per problem, as `main.py` does today for
  `config.json`.
- `eportem config show` prints the effective settings and where each value came
  from, with secrets hidden. `/admin/settings` shows the same, read-only.
- `.env.example` lists every setting with a comment. The README has a table
  generated from the settings module, and a test fails if they don't match.

### Settings (first list)

| Group | Settings |
|---|---|
| Server | `EPORTEM_PUBLIC_URL` (used in links and emails), `EPORTEM_HOST` (default `0.0.0.0` inside the container), `EPORTEM_PORT` (default `8080`), `EPORTEM_TRUSTED_PROXIES`, `EPORTEM_SECURE_COOKIES` (auto from the public URL), `EPORTEM_ROOT_PATH` (serve under a sub-path) |
| Storage | `EPORTEM_DATA_DIR` (default `/data`), `EPORTEM_DATABASE_URL` (default SQLite in the data dir), `EPORTEM_SECRET_KEY` (required, plus a list of old keys for rotation) |
| Target site | `EPORTEM_TARGET_URL` (default `https://eportem.es`; the fake in development), `EPORTEM_BROWSER_USER_AGENT` (optional override), `EPORTEM_CHROMIUM_PATH`, `EPORTEM_CHROMEDRIVER_PATH`, `EPORTEM_BROWSER_CONCURRENCY`, `EPORTEM_HEADLESS` |
| Defaults for new users | `EPORTEM_DEFAULT_TIMEZONE` (default `Europe/Madrid`), `EPORTEM_DEFAULT_LOCALE`, `EPORTEM_DEFAULT_HOLIDAY_REGION`, `EPORTEM_DEFAULT_TEMPLATE` |
| Scheduling | `EPORTEM_WINDOW_MINUTES` (15), `EPORTEM_JITTER_BEFORE_MINUTES` (5), `EPORTEM_JITTER_AFTER_MINUTES` (4), `EPORTEM_VERIFY_AFTER_MINUTES` (40), `EPORTEM_DRY_RUN` (log, never send) |
| Accounts | `EPORTEM_REGISTRATION` (`closed`/`invite`/`open`), `EPORTEM_REQUIRE_EMAIL_VERIFICATION`, `EPORTEM_ADMIN_USERNAME` / `_EMAIL` / `_PASSWORD(_FILE)` (first start only) |
| Email | `EPORTEM_SMTP_HOST`, `_PORT`, `_SECURITY` (`starttls`/`tls`/`none`), `_USERNAME`, `_PASSWORD(_FILE)`, `_FROM` |
| Observability | `EPORTEM_LOG_LEVEL`, `EPORTEM_LOG_FORMAT` (`json`/`text`), `EPORTEM_METRICS_TOKEN`, `EPORTEM_SENTRY_DSN`, `EPORTEM_SENTRY_ENVIRONMENT`, `EPORTEM_HEARTBEAT_URL`, `EPORTEM_ADMIN_ALERT_CHANNEL` |

Per-user things (ePortem credentials, activity IDs, Slack/Telegram tokens,
status texts, timezone, schedule) are user settings in the database, not
instance settings.

### Keeping the repository portable

- **Portability test:** a test scans tracked files (except `docs/` history
  and `CLAUDE.md`) for email addresses outside `example.com`/`example.org`,
  private IP addresses and hostnames outside an allow-list (`eportem.es`,
  `localhost`, `example.*`, library and CDN hosts). It fails CI when one shows
  up.
- Today's hard-coded values move to settings or user data: `BASE_URL`/`LOGIN_URL`
  (target URL), `USER_AGENT` (derived from the browser, with an optional
  override), `SESSION_ID_HOME`/`SESSION_ID_OFFICE_DEFAULT`/`LUNCH_PAUSE_ID`
  (per account), the Slack status texts and emoji (per user, with defaults), and
  the timezone (per user).
- Docs: README and `docs/` are written for any install. Deployment examples are
  generic: plain `docker compose` with a port mapping, and behind a reverse
  proxy (Caddy, Traefik and nginx-proxy-manager examples) with placeholder
  domains. The owner's host notes stay in `CLAUDE.md` (operations), and the
  owner's real values stay in their untracked `.env`.
- The image has no config baked in. `docker-compose.yml` reads `.env` and
  works as it is for a local try-out (`EPORTEM_TARGET_URL` pointing at the
  fake through the `dev` profile).

## 7. Working without a second ePortem account

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
  Each fake account keeps its own clock state. Different fake accounts can use
  different activity IDs, so the code can't come to rely on `1293`.
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
   `reghorario.cshtml`.** It runs at a time no cron line is due, and reuses the
   saved session.
3. **The target URL is an instance setting** (`EPORTEM_TARGET_URL`), never a
   per-user one, so a user can't point the server at an arbitrary host.

Other ways to cover the gap:

- **Time is injected** (a `Clock` interface). Scheduler tests run a simulated
  week for 50 users, with mixed templates, periods, holiday regions and
  timezones, in seconds.
- **`docker compose --profile dev`** starts `eportem` with `fake-eportem`. The
  full browser login path then runs against the fake end to end.
- **Shadow mode before cutover** (phase 8). The new service runs with the
  owner's real schedule but with `EPORTEM_DRY_RUN=true` and the fake as the
  target, so it never opens a second session on the real account. It plans,
  and at each due time it logs what it *would* send. Afterwards, the live
  cron's `logs/actions.log` is compared with the planned runs.

A friendly second ePortem user (a colleague) would be the best test of
multi-user behaviour against the real site. It's optional and only after
cutover.

## 8. Phases

Every phase ends with: all tests passing (old and new), README and these docs
updated, and a commit. The branch merges back into `main` only at phase 8, or
earlier in pieces if phase 1 turns out cleanly separable.

### Phase 0: groundwork
- [x] Branch, baseline: 352 tests pass (`./run_tests.sh`, 2026-11-18).
- [x] `pyproject.toml` with tool settings (the `[project]` table comes with
      the package in phase 1), `requirements-dev.txt`, `pytest` running
      today's unittest suite unchanged, `ruff` (rules in D-013, existing code
      fixed to pass) and coverage (88% overall at the start).
- [x] `make check` (lint + tests + coverage) from a Python 3.13 `.venv`.
- [x] CI workflow `.github/workflows/check.yml`, read by GitHub Actions and by
      Gitea Actions. The Docker build is added to it in phase 7.
- [x] Portability test (`tests/test_portability.py`), plus the gitignored
      `.portability-denylist` for personal names.
- [x] README's "Where to push" section, which named the maintainer's Git
      server, replaced with a generic one.
- [x] `utility/login_and_navigate.py` run as a script no longer clicks the
      dashboard's main button (which records a clock-in on a not-started
      office day); it only logs in and reports.

### Phase 1: pull out `eportem.core` (no behaviour change)
- Move the HTTP clock, browser login and click path, schedule/window logic,
  overrides and notifications into `eportem/core/`. Settings are passed in as
  arguments (`EportemAccount`, `NotificationConfig`, `CookieStore`,
  `target_url`, `clock`). No `os.getenv` inside core.
- Today's scripts become adapters. They read `.env`, `config.json` and the
  override files, build the objects and call core. Cron output, exit codes and
  log files stay byte-for-byte the same where tests check them.
- **Gate:** the whole old suite passes unchanged. The branch could be deployed
  to the owner's host at this point, but that's optional.

### Phase 2: fake ePortem + contract check
- `fake_eportem/` as in section 7, a `fixtures/` directory shared with the
  tests, and `eportem check-contract`.
- End-to-end tests: core HTTP clock and Selenium login against the fake
  (Selenium tests marked `browser`, skipped when no Chromium is present).

### Phase 3: settings, persistence and the calendar
- `eportem/settings.py` with every setting in section 6, `*_FILE` support, the
  start-up check, `eportem config show`, `.env.example`, and the
  README table test.
- SQLAlchemy 2 models, Alembic migrations, SQLite by default (WAL mode in the
  data dir), Postgres through the database URL. Encryption helpers. The
  `CookieStore` comes from the DB.
- Templates (built-ins as data), `core.calendar.resolve()` with the order in
  section 5, regional holidays through the `holidays` package, and table tests
  that cover every rule and the order between them.
- `eportem import-legacy --user <name>`: reads `config/.env`, `config.json`,
  the override files, `.session_cookies.json` and `logs/actions.log` into the
  database for one user. It is idempotent and has a dry run.

### Phase 4: scheduler and workers
- **Planner.** At local midnight for each user (and on start-up, and whenever
  something that affects the calendar changes) it writes the day's
  `planned_runs` from `calendar.resolve()`, with random jitter.
- **Dispatcher.** It wakes up for the next due run. It sets the row to `running`
  with a conditional update, runs `core.actions.perform`, and stores the
  outcome. The unique row per user, date and action means a restart or a second
  replica can't clock twice.
- **Restart rules.** A run left `running` from a crash becomes `unknown`
  and sends an alert, never a retry (same idea as `OutcomeUnknown`). A
  `planned` run whose window was missed while the service was down becomes
  `skipped` and sends an alert. It is never clocked late.
- **Mid-day changes.** Changing today's location or times re-plans only the
  runs that haven't started. Marking today as time off after `start_day` was
  recorded only cancels the runs still planned, and the UI says so.
- At most `EPORTEM_BROWSER_CONCURRENCY` (default 1) browser logins at once, and
  HTTP clocks have their own limit. Logins due soon are spread out so ten users
  at 09:00 don't start ten Chromiums together.
- Verify-day is a scheduled job for each user, reading `planned_runs`.
- Leader lock in `scheduler_lock`, so a second replica only serves the web UI
  and API.

### Phase 5: auth and API
- Passwords: argon2id (`argon2-cffi`). Sign-in is rate-limited for each user
  and each IP. The session cookie is `HttpOnly` and `SameSite=Lax`, with
  `Secure` when served over HTTPS, and there is CSRF protection on forms.
  Password reset and email verification by email (SMTP settings).
- Personal access tokens: only their hash is stored. Each has scopes (`read`,
  `write`, `admin`), an optional expiry, can be revoked, and records when it
  was last used.
- First admin through `eportem create-admin` (or the admin settings on first
  start). Registration: `closed` (default), `invite`, or `open` plus email
  verification.
- API `/api/v1`: `me`, `eportem-account` (set, verify with a test login that
  doesn't clock, and find the activity IDs), `templates`, `schedule`,
  `periods`, `days/{date}` (override one day), `time-off`, `calendar?from&to`
  (resolved preview), `channels` (with "send test"), `runs` (history, today's
  plan), `runs/{id}/log`, `actions/{action}` (clock now, by hand, with
  confirmation), `tokens`. Admin endpoints: `users`, suspend/activate,
  `stats`.
- Every API change is written to `audit_events`. Secrets are never returned:
  they can be set but not read back.

### Phase 6: web UI
- Server-rendered Jinja2 with htmx, no JS build step. English and Spanish.
- Pages: first-run wizard, home (this week / next week strip and today's
  runs), schedule (template picker, editor, home/office pattern, periods),
  calendar (time off, business trips, public holidays), ePortem account (with
  "verify"), notifications (with "send test"), history and run logs, API
  tokens, profile/password.
- Admin: users, runs that failed or are `unknown` across users, scheduler
  health, browser queue, effective settings (secrets hidden), version, and the
  audit log.
- Accessibility basics (keyboard, labels, contrast) and phone-width layout:
  switching tomorrow to home from a phone should take seconds.

### Phase 7: packaging and operations
- `Dockerfile`: `python:3.13-slim-trixie` plus Debian's `chromium` and
  `chromium-driver`, a non-root user, `tini`, a `HEALTHCHECK` against
  `/healthz`, and a `/data` volume. No config baked in. Multi-arch (amd64 +
  arm64). Published to a container registry (which registry is a setting of
  the CI, not of the code).
- `docker-compose.yml`: the `eportem` service, reading `.env`, with the port
  mapping set from `.env`, the secret key from a file, and `profiles: [dev]`
  for `fake-eportem`. Docs for running it directly on a port or behind
  a reverse proxy.
- Observability:
  - Logs: structured JSON on stdout, with `user_id` and `run_id` and secrets
    scrubbed.
  - Metrics: `/metrics` in Prometheus format, protected by a token. Includes
    runs by outcome, clock latency, browser logins, session age at login,
    scheduler lag and notification failures.
  - Errors: the Sentry SDK, off unless a DSN is set. It works with sentry.io or
    self-hosted GlitchTip, and personal data is removed before sending.
  - Dead-man switch: an optional heartbeat URL (healthchecks.io style) is
    pinged every minute while the scheduler is healthy. That covers "the whole
    container died", which the service can't report itself.
  - Failure alerts to the user's own channels as today, plus an admin alert
    channel.
- Backups: `eportem backup` (SQLite `.backup` into the data dir, rotated),
  documented with the restore steps.

### Phase 8: cutover on the owner's host
The owner picks their production values (public URL, port, proxy, email,
error tracking, heartbeat) at this point, in their own `.env`.
1. Deploy the container in **shadow mode** (dry run, fake target) for at least
   3 working days. Compare its planned runs with the live `logs/actions.log`
   each day.
2. `eportem import-legacy` for the owner. Check the imported template, home
   days, time off and channels in the UI.
3. Switch over at a quiet time (mid-morning or mid-afternoon). Comment out the
   ePortem crontab lines and back up the crontab first. Then turn off the dry
   run and point at the real site. The same session cookies are imported, so
   the first run doesn't need a browser login.
4. Watch the first full day: each run, verify-day, and the alerts.
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

## 9. Risks and open questions

| # | Risk / question | Plan |
|---|---|---|
| R1 | **reCAPTCHA scores from cloud IPs.** Logins from datacenter IPs may be rejected where a home IP passes. | Measure it with the contract check from a cloud VM before advertising cloud hosting. Logins stay rare (session reuse), which helps. |
| R2 | **Many users behind one IP** may look like abuse to ePortem. | Spread logins out, keep the login budget per user, and alert on any reCAPTCHA rejection. |
| R3 | **Selling a tool that automates the official working-time record** (Registro de jornada, RD-ley 8/2019) and logs in to a third-party service on users' behalf could break ePortem's terms or employer policies. | Get legal advice before phase 9. That is the owner's call, not an engineering one. |
| R4 | Activity IDs (`1293`, `1`, `2`) may differ per company. | Per-account fields, found from the dashboard when the account is verified. The fake uses different IDs per account. |
| R5 | SQLite with several replicas. | One replica on SQLite. Postgres is needed for more than one. Documented. |
| R6 | Chromium memory on small hosts. | Browser concurrency 1 by default, Chromium closed after each login, container memory limit. |
| R7 | Regional and local holiday data can be wrong or missing. | The preview shows them ahead, they can be overridden per day (`work_on_holiday`), local holidays are added by hand, and the `holidays` package version is pinned. |
| Q1 | ~~Gitea Actions runner available on the owner's host?~~ | Answered 2026-11-18: Actions are off for the repository and no runner is registered. `make check` before each push; the workflow runs on GitHub through the mirror, and on Gitea once the owner enables Actions and registers a runner. |

Production choices (hostname, port, proxy, email, error tracking, heartbeat)
are no longer open questions: they are settings the owner fills in at phase 8.

## 10. Definition of done (whole refactor)

- No crontab entries for ePortem on the owner's host. The container runs the
  owner's schedule, and two clean weeks have been seen in `planned_runs` and
  verify-day.
- A new user can go from sign-up to a planned week through the wizard in under
  five minutes, verified against the fake. They can switch a day between home
  and office in one click, and their data is separate from everyone else's.
  Tests prove users are kept apart: a user cannot read or change another user's
  data through the UI or the API.
- `docker compose up` on a clean Debian host, with only `.env.example` copied
  to `.env` and a secret key filled in, gives a working instance after
  `eportem create-admin`. The portability test passes.
- Tests: unit, calendar resolution tables, scheduler simulation, API/auth
  (including authorization checks), end to end against the fake (HTTP and
  browser), migration upgrade and downgrade. All pass in CI. Coverage is
  reported, with a floor of 85% for `eportem/core` and `eportem/scheduler`.
- README describes the service for any install. CLAUDE.md describes the
  owner's container operations. DECISIONS.md is up to date.
