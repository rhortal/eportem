# Refactor plan: CheckIn as a multi-user service

Branch: `refactor/multiuser-service` (from `main` at `54477fa`, 2026-11-18),
merged into `main` (fast-forward) on 2026-11-24 after the first clean live day.
Status: **phase 8 under way**: the service clocks for real since 2026-11-24;
steps 5-6 (rollback window, then removing the cron path) remain. The status
lines below each phase are the record. Decisions with their reasons are
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
            ┌───────────────────────── container: checkin ──────────────────────────┐
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
                 SQLite (volume) or Postgres         CHECKIN_TARGET_URL (eportem.es or the fake)
```

### Package layout

```
checkin/                  # new importable package (pyproject.toml)
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
  cli.py                  # `checkin serve|migrate|create-admin|import-legacy|config|check-contract`
fake_eportem/             # the test double for eportem.es (section 7)
legacy/                   # today's scripts, kept working until cutover, then removed
```

The scripts at the top of the repo (`main.py`, `eportem_action.py`, ...) become
thin shims over `checkin.core` in phase 1, so cron on the owner's host keeps
working from the same code until cutover.

### Data model (first cut)

| Table | Key fields | Notes |
|---|---|---|
| `users` | id, email, username, password_hash (argon2id), role (`admin`/`user`), status (`pending`/`active`/`suspended`), email_verified_at, plan, timezone, locale, jitter_before_minutes, jitter_after_minutes, paused, created_at | Status and plan are the hooks for monetising later. Timezone, locale and the random offset are the person's own, starting from the instance defaults (D-016) |
| `api_tokens` | id, user_id, name, prefix, token_hash (sha256), scopes, last_used_at, expires_at, revoked_at | Shown once. Format `ept_<prefix>_<secret>` |
| `web_sessions` | id, user_id, created_at, expires_at, ip, user_agent | Server-side sessions; cookie holds only the id |
| `eportem_accounts` | user_id, username, password_enc, office_activity_id, home_activity_id, lunch_pause_id, use_http, verified_at, last_login_at | Activity IDs are found from the dashboard when the account is verified; no hard-coded defaults |
| `eportem_sessions` | user_id, data_enc (the whole session record, encrypted), updated_at | Replaces `config/.session_cookies.json` |
| `schedule_templates` | id, user_id, key, name, description, days (JSON: weekday → start/stop/lunch_out/lunch_back) | A person's own templates. The built-ins live in code (`checkin/core/templates.py`), read-only; people copy and edit (section 5) |
| `user_schedules` | user_id, template_key, location_weeks (JSON: one week, or two for an A/B fortnight), pattern_anchor, holiday_country, holiday_region | One per user |
| `schedule_periods` | id, user_id, template_key, start_date, end_date, yearly, label | e.g. summer hours every 1 Jul–31 Aug |
| `day_overrides` | id, user_id, start_date, end_date, kind (`time_off`/`location`/`business_trip`/`times`/`work_on_holiday`), location, times (JSON), note | Replaces the three `*_override.txt` files; one row can cover a range |
| `local_holidays` | id, user_id, date, name | Local public holidays not in the regional calendar |
| `notification_channels` | id, user_id, kind (`telegram`, `slack`; `email` later), config_enc, notify, alerts, slack_status, status_texts (JSON) | Per user. One Slack channel holds its webhook, bot token, user token and destination, as the scripts do; status texts and emoji can be changed |
| `planned_runs` | id, user_id, date, action, target_minute, planned_at (UTC, with jitter), location, status (`planned`/`running`/`recorded`/`not_recorded`/`unknown`/`skipped`/`failed`/`cancelled`), via (`http`/`browser`/`legacy-*`), attempt, started_at, finished_at, error | **Unique (user_id, date, action)**: the guard against double clocking. Replaces `logs/actions.log` |
| `run_logs` | run_id, outcome, text | The per-run output block that `logs/http_clock.log` holds today, scrubbed |
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
  `RANDOM % 10` minutes). The random offset (jitter) is part of each
  person's profile, like their ePortem credentials; new users start from the
  instance defaults. The window is instance-wide: it is the safety rule, and
  every person's offset must fit inside it (`jitter_problems()`), so an
  action can never run late (D-016).
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
stop), or `off`. Built-ins are shipped as data (`checkin/core/templates.py`) and
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

`checkin import-legacy` maps `config.json` to a custom template (or to the
built-in one it matches exactly) plus a location pattern. It also maps
`holiday_override.txt` to `time_off`, `location_override.txt` to `location`
and `business_trip_override.txt` to `business_trip`.

## 6. Configuration and portability

The rule is: **the code and the image contain no install-specific values.**
Every hostname, URL, IP, email address, domain, company-specific ID, timezone
and credential comes from settings. Owner-specific values live only in the
owner's own, untracked `.env` / config file.

### How settings are given

- One settings module (`checkin/settings.py`, pydantic-settings) is the only
  place that reads the environment.
- Priority: environment variables (`CHECKIN_*`) > a mounted config file
  (`CHECKIN_CONFIG_FILE`, TOML) > defaults that are safe and neutral.
- Every secret also accepts `*_FILE` (e.g. `CHECKIN_SECRET_KEY_FILE`), so
  Docker and Kubernetes secrets work without putting values in the
  environment.
- Settings are checked on start-up. A missing required value or a bad one stops
  the container with one clear message per problem, as `main.py` does today for
  `config.json`.
- `checkin config show` prints the effective settings and where each value came
  from, with secrets hidden. `/admin/settings` shows the same, read-only.
- `.env.example` lists every setting with a comment. The README has a table
  generated from the settings module, and a test fails if they don't match.

### Settings (first list)

| Group | Settings |
|---|---|
| Server | `CHECKIN_PUBLIC_URL` (used in links and emails), `CHECKIN_HOST` (default `0.0.0.0` inside the container), `CHECKIN_PORT` (default `8080`), `CHECKIN_TRUSTED_PROXIES`, `CHECKIN_SECURE_COOKIES` (auto from the public URL), `CHECKIN_ROOT_PATH` (serve under a sub-path) |
| Storage | `CHECKIN_DATA_DIR` (default `/data`), `CHECKIN_DATABASE_URL` (default SQLite in the data dir), `CHECKIN_SECRET_KEY` (required, plus a list of old keys for rotation) |
| Target site | `CHECKIN_TARGET_URL` (default `https://eportem.es`; the fake in development), `CHECKIN_BROWSER_USER_AGENT` (optional override), `CHECKIN_CHROMIUM_PATH`, `CHECKIN_CHROMEDRIVER_PATH`, `CHECKIN_BROWSER_CONCURRENCY`, `CHECKIN_HEADLESS` |
| Defaults for new users | `CHECKIN_DEFAULT_TIMEZONE` (default `Europe/Madrid`), `CHECKIN_DEFAULT_LOCALE`, `CHECKIN_DEFAULT_HOLIDAY_REGION`, `CHECKIN_DEFAULT_TEMPLATE` |
| Scheduling | `CHECKIN_WINDOW_MINUTES` (15), `CHECKIN_VERIFY_AFTER_MINUTES` (40), `CHECKIN_DRY_RUN` (log, never send). Starting values for each person's random offset are under "Defaults for new users": `CHECKIN_DEFAULT_JITTER_BEFORE_MINUTES` (5), `CHECKIN_DEFAULT_JITTER_AFTER_MINUTES` (4) |
| Accounts | `CHECKIN_REGISTRATION` (`closed`/`invite`/`open`), `CHECKIN_REQUIRE_EMAIL_VERIFICATION`, `CHECKIN_ADMIN_USERNAME` / `_EMAIL` / `_PASSWORD(_FILE)` (first start only) |
| Email | `CHECKIN_SMTP_HOST`, `_PORT`, `_SECURITY` (`starttls`/`tls`/`none`), `_USERNAME`, `_PASSWORD(_FILE)`, `_FROM` |
| Observability | `CHECKIN_LOG_LEVEL`, `CHECKIN_LOG_FORMAT` (`json`/`text`), `CHECKIN_METRICS_TOKEN`, `CHECKIN_SENTRY_DSN`, `CHECKIN_SENTRY_ENVIRONMENT`, `CHECKIN_HEARTBEAT_URL`, `CHECKIN_ADMIN_ALERT_CHANNEL` |

Per-user things (ePortem credentials, activity IDs, the random offset, Slack/Telegram tokens,
status texts, timezone, schedule) are user settings in the database, not
instance settings.

### Keeping the repository portable

- **Portability test:** a test scans tracked files (except the host notes:
  `docs/OPERATIONS.md`, `docs/HANDOFF.md`, `TODO.md`, `docs/http-api-investigation.md`) for email addresses outside `example.com`/`example.org`,
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
  domains. The owner's host notes stay in `docs/OPERATIONS.md`, and the
  owner's real values stay in their untracked `.env`.
- The image has no config baked in. `docker-compose.yml` reads `.env` and
  works as it is for a local try-out (`CHECKIN_TARGET_URL` pointing at the
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
   check, `checkin check-contract`, uses the owner's account. It logs in (only
   when the saved session is gone), fetches the login page and the dashboard,
   and compares field names, `buttonsRegBox` structure and button
   `id`/`name` attributes with the fixtures. **It never calls
   `reghorario.cshtml`.** It runs at a time no cron line is due, and reuses the
   saved session.
3. **The target URL is an instance setting** (`CHECKIN_TARGET_URL`), never a
   per-user one, so a user can't point the server at an arbitrary host.

Other ways to cover the gap:

- **Time is injected** (a `Clock` interface). Scheduler tests run a simulated
  week for 50 users, with mixed templates, periods, holiday regions and
  timezones, in seconds.
- **`docker compose --profile dev`** starts `checkin` with `fake-eportem`. The
  full browser login path then runs against the fake end to end.
- **Shadow mode before cutover** (phase 8). The new service runs with the
  owner's real schedule but with `CHECKIN_DRY_RUN=true` and the fake as the
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
- [x] CI workflow, now `.gitea/workflows/check.yml` (D-024; it was
      `.github/workflows/check.yml`). The Docker build is added to it in phase 7.
- [x] Portability test (`tests/test_portability.py`), plus the gitignored
      `.portability-denylist` for personal names.
- [x] README's "Where to push" section, which named the maintainer's Git
      server, replaced with a generic one.
- [x] `utility/login_and_navigate.py` run as a script no longer clicks the
      dashboard's main button (which records a clock-in on a not-started
      office day); it only logs in and reports.

### Phase 1: pull out `checkin.core` (no behaviour change)
Done 2026-11-18 (commits `a2046d5`..`de40deb` plus the closing commit).
- [x] `checkin/core/`: `notify`, `schedule`, `overrides`, `target`, `browser`,
      `activities`, `cookies`, `clock_http`, `actions`. No `os.getenv`, no
      file paths. Progress goes through a `say` callable (D-014).
- [x] Today's scripts are adapters: `utility/notification_send.py`,
      `utility/slack_status.py`, `utility/login_and_navigate.py`,
      `utility/http_clock.py`, `eportem_action.py` and `main.py` fill core in
      from `config/.env` and the repository's files.
- [x] **Gate met:** the old suite passes with no test file changed (only
      `tests/test_portability.py` skips its own sample values). `main.py
      --check` and every script's `--help` were run by hand.
- [x] Direct tests of core (`tests/core/`): another site URL, another
      company's activity IDs, memory and file cookie stores, the fallback rules,
      and two runs at once keeping separate logs. Coverage of `checkin/` is 96%,
      with a floor of 85% in `make check` and CI.
- [x] `[project]` metadata in `pyproject.toml` (package `checkin`; `eportem` until D-025).
- [x] Found and fixed on the way: a saved cookie without a `domain` crashed
      `requests` while loading the session (outside the corrupt-file handling).
      Real cookie files always have one, so the cron path never hit it.
- Not deployed to the owner's host. It can be (the cron path is unchanged and
  tested), which would run the core engine in production before the service
  uses it. That is the owner's call.

### Phase 2: fake ePortem + contract check
Done 2026-11-18.
- [x] `fake_eportem/` (standard library only, D-015): login form with an
      optional stub reCAPTCHA, the dashboard in every state, the clock
      endpoint, several accounts with their own activity IDs and state,
      faults (`error_500`, `maintenance`, `drop`, `slow`, `captcha`, before or
      after recording, per account, skipping the first N requests), session
      expiry, a record of events and requested paths, control endpoints and a
      CLI (`python -m fake_eportem`).
- [x] `checkin.contract`: read-only structure checks (login fields, the clock
      box on the login's landing page, the dashboard layout the Selenium flow
      clicks, button attributes, this account's buttons for the current state)
      and a list of the activities found. Same checks on the fake in tests.
- [x] Tests: the fake follows the captures in `tests/test_http_clock.py`;
      `tests/fake/` (engine over HTTP: full days, two accounts at once, every
      fault, sessions, reCAPTCHA blocking a plain-HTTP login, the contract run
      never requesting the clock URL); `tests/browser/` (real headless Chromium:
      login, both full days by clicking, the already-started guard, browser
      login then HTTP, fallback to clicking).
- [x] `make test-fast` leaves out `tests/browser/` (~35 s).
- [ ] **Run `python -m checkin.contract --activity-ids 1,1293,2` on the
      owner's host once**, at a time no cron line is due (it refreshes the
      saved session). Needs the owner's go-ahead. It confirms the fake's
      structure against the real site, including one assumption the captures
      don't show directly: that the page a login lands on has the clock box.
- The plan's "fixtures shared in `fake_eportem/fixtures/`" became a test
  instead: the fake must offer every button in the captures the unit tests
  use, so the old test files stay as they are.

### Phase 3: settings, persistence and the calendar
Done 2026-11-18.
- [x] `checkin/settings.py`: every setting in section 6, environment over a
      TOML file over defaults, `*_FILE` for secrets, every problem named by
      its variable. `python -m checkin config check|show|docs|new-key`.
      `.env.example` and README's table are generated and tested.
- [x] The random offset is per person (D-016); the instance gives the
      starting values and the window.
- [x] Templates (`checkin/core/templates.py`, six built-ins) and
      `checkin/core/calendar.py` `resolve()`, with table tests for every rule
      and the order between them (holidays from the `holidays` package,
      loaded only when used).
- [x] `checkin/db/`: SQLAlchemy models, Alembic migration `0001` (tested up
      and down), SQLite in WAL mode with foreign keys, `SecretBox`
      (Fernet/MultiFernet, rotation), `DbCookieStore` (the HTTP clock keeps its
      session encrypted in the database; tested against the fake),
      `load_calendar()` from rows.
- [x] `python -m checkin migrate` and `import-legacy --user NAME [--dry-run]`
      (D-017): idempotent, nothing saved on any problem, secrets never
      printed. `logs/actions.log` becomes run history so the cutover day's
      earlier actions aren't clocked again.
- [x] Service packages pinned in `requirements-service.txt`, apart from the
      cron path's `requirements.txt` (D-017).

### Phase 4: scheduler and workers
Done 2026-11-18 (D-018).
- [x] **Planner** (`checkin/scheduler/planner.py`): each person's day from
      `calendar.resolve()`, with their own random offset. Idempotent: adds
      missing runs, moves runs not yet started when the plan changed, cancels
      runs the plan no longer has, never touches a run that started.
- [x] **Dispatcher** (`checkin/scheduler/scheduler.py`): claims a run with a
      conditional `planned → running` update; runs it through the engine
      built from the person's rows (`runner.py`: account, activity IDs,
      encrypted session store, channels, Slack status, business trip);
      stores status, how it was sent and the run log; alerts on
      `unknown` / `not_recorded` / `failed`.
- [x] **Never late, never twice:** past its window a run becomes `skipped`
      (alerted); a run left `running` at start-up becomes `unknown`
      (alerted, never retried); runs the legacy import recorded are not
      redone.
- [x] Mid-day changes re-plan only what hasn't run (`Scheduler.replan()`).
- [x] Browser gate (`CHECKIN_BROWSER_CONCURRENCY`), worker pool, leader lock
      (stale after 2 minutes), end-of-day check per person (`day_checks`,
      migration `0002`).
- [x] `CHECKIN_DRY_RUN`: runs are planned and logged as `dry_run`, nothing is
      sent (shadow mode).
- [x] `python -m checkin scheduler` runs it in the foreground, before the web
      app exists.
- [x] Tests in simulated time against the fake: full days, offsets, weekends
      and pauses, the lock, claiming, late start-up, crash recovery,
      OutcomeUnknown, re-planning, time off added mid-day, missing activity
      IDs, dry run, 30 people with mixed templates for a week (4 s), the
      browser gate, channels and alerts, the background thread.
- Still to do with phase 5: start the scheduler inside the web app's
  process, and replan when the API changes a calendar.

### Phase 5: auth and API
Done 2026-11-18, except the parts that come with the web UI (below).
- [x] `checkin/auth.py`: argon2id passwords (same timing for unknown users,
      rehash on login), personal access tokens `ept_<prefix>_<secret>` (only
      sha256 stored, scopes read < write < admin, expiry, revocation,
      last used), a rate limiter, the audit log.
- [x] `checkin/service.py`: every operation, shared with the UI. It checks
      input and reports every problem, writes audit events, and returns
      secrets only as `(set)`. Verifying an ePortem account logs in (a browser
      only if the saved session expired), reads the dashboard, never clocks,
      and fills in the activity IDs it can work out.
- [x] `checkin/web/app.py` + `api.py`: `/api/v1` with OpenAPI at `/api/docs`:
      me, password, eportem-account (+ verify), templates, schedule, periods,
      days, local-holidays, calendar, channels (+ test), runs (+ log),
      actions (clock now, needs `confirm`), tokens, admin users/runs/stats.
      `/healthz`, `/readyz` (database and scheduler heartbeat). Calendar
      changes re-plan today in the same transaction.
- [x] Commands: `serve` (web app + API + scheduler), `create-admin`,
      `create-token`; `CHECKIN_ADMIN_*` creates the first admin on start-up.
- [x] Tests (20): auth, rate limit, scopes, expiry, suspension, isolation
      (every route that takes an id answers 404 for another person's
      row), validation, audit, verify against the fake, clock now through
      the scheduler, channels, admin, health.
- [ ] With phase 6: web sessions (cookie + CSRF), sign-in rate limit per user
      and address (the limiter exists), registration modes, email
      verification and password reset (SMTP).
- [ ] Starlette warns that its test client's use of `httpx` is deprecated;
      switch the dev dependency when the replacement is stable.

### Phase 6: web UI
Done 2026-11-18 (D-020), with the items below left open.
- [x] Server-rendered Jinja2 with htmx 2.0.4 bundled in `checkin/web/static/`
      (no CDN). English and Spanish, per person, falling back to the
      browser's language and then the instance default.
- [x] Sign-in with server-side sessions (only a hash of the cookie id is
      stored; HttpOnly, SameSite=Lax, Secure on https), CSRF on every form and
      on cookie-authenticated API calls, a sign-in rate limit per user and per
      address, no open redirect, sessions ended on suspension.
- [x] Pages: today (setup checklist, this week and next week, one tap
      switches a day home/office and a second tap undoes it, today's runs,
      clock now), schedule (template cards, customise the week, home days,
      region for public holidays, periods), calendar (month view, time off,
      business trips, location, other times, work on a holiday, local
      holidays), ePortem account (verify), notifications (add, edit
      without retyping secrets, test, delete), history and run logs, profile
      (timezone, language, own random offset, pause, password), API tokens,
      admin (runs that need a look, users, suspend).
- [x] Days with nothing to clock carry a code (`DayPlan.off`) so the UI
      shows short translated labels.
- [x] Tests (15) and screenshots checked at desktop and phone width; the
      one-tap switch checked in real Chrome.
- [ ] A step-by-step wizard. For now, home shows a setup checklist that
      links to each page; enough for the first users, revisit with feedback.
- [ ] Alternating weeks in the UI (the API and the engine support them).
- [ ] Registration (`invite`/`open`), email verification and password
      reset: they need SMTP and email templates. Accounts are created by an
      admin for now (`CHECKIN_REGISTRATION=closed`, the default).
- [ ] The iCal feed.

### Phase 7: packaging and operations
Done 2026-11-18 (D-021).
- [x] `Dockerfile`: `python:3.13-slim-trixie`, Debian's `chromium` and
      `chromium-driver`, `tini`, non-root user 10001, `/data` volume,
      `HEALTHCHECK` on `/healthz`, no configuration baked in; `.dockerignore`
      keeps local secrets and state out. About 1.4 GB.
- [x] `docker-compose.yml`: reads `.env`, publishes on `CHECKIN_PUBLISH`
      (default `127.0.0.1:8080`), 512 MB shared memory for Chromium, 1 GB
      memory limit, and a `dev` profile with the fake ePortem.
- [x] `checkin/ops.py`: JSON logs (secrets scrubbed), Sentry/GlitchTip error
      reports when a DSN is set (no request data, scrubbed), the heartbeat
      (at most once a minute, never blocking), Prometheus `/metrics` with a
      token (users, runs by status, how they were sent, scheduler lag and
      heartbeat age), `python -m checkin backup` (SQLite online backup,
      rotated).
- [x] `CHECKIN_BROWSER_SANDBOX` (off in the image: Chromium's sandbox can't
      start as a non-root user there) and `CHECKIN_CHROMEDRIVER_PATH`.
- [x] Tested end to end in containers on the Mac (arm64) against the fake with
      its stub reCAPTCHA: verify through Chromium in the container, a clock over
      HTTP, a clock through the browser click flow, health, metrics, backup. That
      run found and fixed two bugs: cookies for single-word host names (a
      container name) were never sent back, and people created after a window
      got "service was down" alerts.
- [x] CI builds the image and smoke-tests `/healthz` and `/readyz`.
- [ ] Multi-arch images published to a registry: a CI and registry choice
      (Gitea's registry, GHCR...) for when there are releases. Building from
      source works on amd64 and arm64.

### Phase 8: cutover on the owner's host
**Progress (2026-11-18, evening).** The host-specific details (paths, names,
hostname, logins) are in `docs/HANDOFF.md`, not here.
- [x] Contract check against the real site from the owner's host (read-only):
      all checks pass, including the login landing on the page with the clock
      box. The activities found match what verify would pick.
- [x] Shadow running on the owner's host from a git worktree of this branch,
      as its own Compose project. The live checkout and crontab are untouched.
      It runs the service in dry run with the fake as its target, GlitchTip with
      Postgres, and the fake, all published on `127.0.0.1` only. Since
      2026-11-21 GlitchTip runs as the host's own stack (on its shared Postgres)
      instead of the `errors` profile; the profile stays for other installs. In dry run it
      sends nothing: no ePortem request, no notification, no alert.
- [x] Owner imported with `import-legacy` (files streamed into the container,
      deleted afterwards), with recorded actions as history.
- [x] Error reports and the heartbeat go to GlitchTip over the Compose
      network, both checked.
- [x] Daily shadow report (command in `docs/HANDOFF.md`). Done 2026-11-23: three
      full working days match (2026-11-19, 2026-11-20, 2026-11-23). The first day with the
      service's own plan is 2026-11-19. 2026-11-19 and 2026-11-20 match cron
      (every action, location and minute within the jitter); the third working
      day is 2026-11-23. The host rebooted on the morning of 2026-11-19 and the
      service came back and planned the day by itself. In dry run the service
      never contacts its target, so the shadow tests the planning, not the send.
- [x] Public hostname: a DNS record and a reverse-proxy host, with HTTPS.
      Checked from outside on 2026-11-21: health, sign-in and authentication
      on `/metrics` and the API; error tracking is not exposed.
- [x] An outside uptime monitor on `/healthz` (a monitor on the same host
      can't notice the host going down), added 2026-11-21.
- [x] A destination for GlitchTip's alerts (Telegram, 2026-11-21; checked end to end).
- [x] Rehearsal with the dry run off against the fake, in a throwaway project on
      the owner's host (2026-11-24): a browser login, a clock over HTTP, and a
      fresh login after the session expired; one event per action.
- [x] Switch (step 3), 2026-11-24 mid-morning: the cron clocking and verify-day
      lines commented out (crontab backed up), `import-legacy` run again for the
      current session cookies and the morning's clock-in, dry run off, target the
      real site. Next: step 4, watching the first full day.
- [x] 2026-11-24: the clock-in is planned only before the start time and the
      clock-out only after the stop time (D-026), at the owner's request.
- [x] First full day (step 4), 2026-11-24: all four actions recorded at home
      (start by cron before the switch; lunch 13:32, back 14:28, stop 18:03 over
      HTTP), the day check ok. `main` fast-forwarded to this branch the same
      evening; the host now runs `main`. Next: two clean weeks, then step 6.

The owner picks their production values (public URL, port, proxy, email,
error tracking, heartbeat) at this point, in their own `.env`.
1. Deploy the container in **shadow mode** (dry run, fake target) for at least
   3 working days. Compare its planned runs with the live `logs/actions.log`
   each day.
2. `checkin import-legacy` for the owner. Check the imported template, home
   days, time off and channels in the UI.
3. Switch over at a quiet time (mid-morning or mid-afternoon). Comment out the
   ePortem crontab lines and back up the crontab first. Then turn off the dry
   run and point at the real site. The same session cookies are imported, so
   the first run doesn't need a browser login.
4. Watch the first full day: each run, verify-day, and the alerts.
5. **Rollback:** stop the container and restore the crontab. The legacy
   scripts are still on disk, and `config/.env` hasn't changed.
6. After two clean weeks, delete `legacy/` and the cron-specific docs, and
   rewrite the operations sections of README and `docs/OPERATIONS.md`.

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
  `checkin create-admin`. The portability test passes.
- Tests: unit, calendar resolution tables, scheduler simulation, API/auth
  (including authorization checks), end to end against the fake (HTTP and
  browser), migration upgrade and downgrade. All pass in CI. Coverage is
  reported, with a floor of 85% for `checkin/core` and `checkin/scheduler`.
- README describes the service for any install. `docs/OPERATIONS.md`
  describes the owner's container operations. DECISIONS.md is up to date.
