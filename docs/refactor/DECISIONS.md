# Refactor decisions

One entry per decision. Newest at the bottom. Proposed decisions become
Accepted once the owner agrees, or once code depends on them. When a decision
is reversed, mark the old entry Superseded and link the new one. Don't delete
entries.

Format: **D-NNN: title** (status, date): context → decision → consequences.

---

**D-001: Keep Python and reuse the existing clock code** (Proposed, 2026-11-18)
The HTTP clock and login code contains hard-won behaviour: the
`OutcomeUnknown` handling, exact button IDs and a browser that passes
reCAPTCHA. Rewriting it in another language would throw that away.
→ The service is Python 3.13. Today's modules move into `checkin.core` and get
their settings as arguments instead of reading globals.
→ The old test suite keeps guarding that behaviour throughout.

**D-002: FastAPI + Jinja2/htmx, a single process** (Proposed, 2026-11-18)
One container should serve the UI, the API, admin pages and metrics, and run
the scheduler. A separate SPA would need a JS build step for little gain.
→ FastAPI (it generates OpenAPI from the code) serves server-rendered Jinja2
pages, with htmx for the interactive parts. The scheduler is an asyncio task
in the same process.
→ There's only one thing to deploy. The API is a first-class part of the app,
and the UI uses the same service layer.

**D-003: Own scheduler on top of a `planned_runs` table, not APScheduler or cron** (Proposed, 2026-11-18)
The hard requirements are: never clock twice, never clock late after an
outage, survive restarts, and be easy to check afterwards. APScheduler's job
store doesn't model "this user's lunch_break for this date ran once".
→ Each day's runs are rows, with a unique key on user, date and action. A run
is claimed with a conditional update. A crash leaves the run `unknown`, which
sends an alert and is never retried. A missed window becomes `skipped`.
→ Verify-day and the history UI read the same table. `logs/actions.log` is
retired.

**D-004: SQLite by default, Postgres optional** (Proposed, 2026-11-18)
A homelab install should be one container and one volume. A cloud install may
need more than one replica.
→ SQLAlchemy 2 + Alembic. SQLite (WAL) at `/data/checkin.db` (`eportem.db` before D-025), or Postgres
through `DATABASE_URL`. A leader lock means only one replica schedules.

**D-005: Secrets encrypted at rest with an instance key** (Proposed, 2026-11-18)
The service stores users' ePortem passwords, ePortem session cookies and
Slack/Telegram tokens.
→ Fernet/MultiFernet with `CHECKIN_SECRET_KEY` (env or Docker secret).
User passwords are hashed with argon2id. API tokens are stored as sha256
hashes, with a visible prefix so they can be identified.
→ Losing the key means re-entering secrets. Key rotation is documented. Secrets
can be written through the UI or API but are never returned.

**D-006: Sessions for the UI, personal access tokens for the API, no JWT** (Proposed, 2026-11-18)
The deleted `feature/user-auth-and-multiuser` branch used JWTs with default
secrets. JWTs can't be revoked without extra machinery.
→ Server-side web sessions (cookie holds an opaque id) with CSRF on forms.
Opaque personal access tokens with scopes, expiry and revocation.

**D-007: A fake ePortem built from real pages, plus a read-only contract check** (Proposed, 2026-11-18)
There's only one ePortem account, and it's in live use. The old mock server
drifted from the real login form and was deleted (2026-08-10).
→ `fake_eportem/` serves the real field names and the captured dashboard markup
from shared fixtures. It keeps clock state per account and can inject faults.
`checkin check-contract` compares the real site with the fixtures and never
calls the clock endpoint. The base URL is a global setting, never a per-user
one.
→ Every test except the contract check runs offline, including multi-user
tests and browser end-to-end tests.

**D-008: Cutover by shadow mode, then switching cron off** (Proposed, 2026-11-18)
The live system must keep clocking, and the old and new systems must never
both clock the same account.
→ The legacy scripts stay working on this branch (phase 1 makes them adapters
over core). The new service first runs in dry-run mode against the fake next to
cron. Then cron is switched off and the service is pointed at the real site in
one step. Rollback means restoring the crontab.

**D-009: Observability: Prometheus metrics, Sentry-compatible errors, heartbeat** (Proposed, 2026-11-18)
To sell this later, the owner needs to know about crashes without relying on
cron mail.
→ `/metrics` (token-protected), the Sentry SDK when `SENTRY_DSN` is set (works
with sentry.io or GlitchTip), structured JSON logs, and an outbound heartbeat
URL as a dead-man switch.

**D-010: Defer billing; build account status and entitlements now** (Proposed, 2026-11-18)
Monetisation is a "maybe later", and it carries legal questions (PLAN.md R3).
→ `users.status`, `users.plan`, and one `can_clock()` check used by both the
scheduler and the API. Email verification and invites come in phase 5. Stripe
and licence keys wait until there's a buyer.

**D-011: Schedules are templates + a location pattern + dated changes, resolved by one function** (Proposed, 2026-11-18)
People think in patterns, like "European 9–18, home on Wednesdays", "summer
hours in July and August" or "home tomorrow". They don't think in
per-weekday JSON. Calendly, Google Calendar's working location and Spanish
HR tools (named schedules, *jornada intensiva*, regional holidays) all
handle this well.
→ Built-in read-only templates (`european-9-18`, `spanish-9-18`,
`spanish-friday-short`, `summer-8-15`, ...) that users copy to customise.
Plus a home/office pattern per weekday (with an optional A/B fortnight),
yearly or one-off periods, one-day changes (location, times, time off,
business trip, work on a holiday), and regional public holidays through the
`holidays` package. `core.calendar.resolve(user, date)` is a pure function
with a fixed order. The UI preview, the API, the planner and verify-day all
use it.
→ "What will happen on day X" has a single answer, and that answer can be
tested.

**D-012: No install-specific values in code or image; everything is a setting** (Proposed, 2026-11-18)
This is open source, so other people must be able to run it without editing
code. Today the code hard-codes the target URL, activity IDs, the
User-Agent, the timezone and the Slack status texts, and the docs mention
the owner's host.
→ One pydantic-settings module, the only reader of the environment.
`CHECKIN_*` env vars > a TOML config file > neutral defaults, with `*_FILE`
for secrets. It is checked on start-up, and `checkin config show` prints it.
`.env.example` and the README settings table are checked against the
module by a test. A portability test fails CI on personal emails, private IPs
or unknown hostnames in tracked files. Per-user values (credentials, activity
IDs, status texts, timezone) live in the database.
→ The owner's production values (hostname, port, proxy, SMTP, Sentry,
heartbeat) are chosen at cutover in an untracked `.env`. Host-specific
operations notes stay in `CLAUDE.md`. README and `docs/` stay generic.
(Superseded 2026-11-18: host notes moved to `docs/OPERATIONS.md`, session
state to `docs/HANDOFF.md`; `CLAUDE.md` holds only general guidance and is
checked by the portability test. See D-023.)

**D-013: Tooling: pytest, ruff, coverage, one CI workflow for both forges** (Accepted, 2026-11-18)
Phase 0 needed a check that is the same locally and in CI. The repository
lives on Gitea (Actions off, no runner) and is mirrored to GitHub.
→ pytest runs the existing unittest suite unchanged. ruff checks `E, W, F, B,
I, UP, S` at line length 120, with asserts, fake secrets, permissive chmods
and subprocess allowed in `tests/`. Coverage is reported with branches.
Nothing is formatted automatically yet (`ruff format` would rewrite most
lines; decide when the code moves in phase 1). `make check` is the single
command. `.github/workflows/check.yml` runs it on GitHub Actions and, once
enabled, on Gitea Actions, which reads the same directory.
→ Lint fixes to existing code were mechanical (import order, `open()` modes,
`raise ... from e`, one `contextlib.suppress`), and the suite proves they
change no behaviour.

**D-014: Core reports through `say`, and takes its collaborators as arguments or overridable methods** (Accepted, 2026-11-18)
The legacy run log copies stdout (`contextlib.redirect_stdout`). That works
for one run per process. The service will run several users at once, and a
redirect of the process-wide stdout would mix their logs. The legacy tests also
patch module-level names (`eportem_action.RETRY_PAUSE_SECONDS`,
`utility.login_and_navigate.WebDriverWait`, `utility.http_clock.COOKIE_FILE`,
...), and the gate for phase 1 was to keep them unchanged.
→ Every core class takes `say` (default: `print`, looked up per call). A run
captures its log by wrapping its own `say` (`SayCapture`). A test runs two
actions in threads and checks the logs stay apart.
→ Each collaborator (browser start, login, HTTP clock, channels, status
updater, recorder, run log, timings, diagnostics dir, label text) is a
constructor argument and also a method or attribute. The legacy adapters
subclass the core classes and override those methods to call their own
module-level names when used. That keeps the old patches working. The
adapters, and that indirection, go away at cutover (phase 8).
→ Settings named in messages come from `labels`. The legacy scripts pass
their environment variable names, so their output is unchanged.

**D-015: The fake ePortem uses only the standard library** (Accepted, 2026-11-18)
The plan said a small FastAPI app. But the fake has five routes, has to be a
real HTTP server (the engine uses `requests`, and the browser tests drive
Chromium against it), and must not add packages to `requirements.txt`, which
`run.sh` installs on the live host.
→ `http.server.ThreadingHTTPServer` in a thread, started per test on a free
port. Faults, sessions and per-account state live in the `FakeEportem`
object. It also runs on its own for local tries and the dev profile.
→ FastAPI arrives with the service itself (phase 5), not before.
→ The fake redirects the login's landing page (`/aplicaciones`) to the
dashboard. That page on the real site must show the clock box, because the
click flow finds its button there straight after login, but no capture shows
it. `checkin.contract` checks it on the real site.

**D-016: The random offset (jitter) belongs to each person's profile** (Accepted, 2026-11-18, owner's request)
How far before or after the set time an action may start is a personal choice,
like the ePortem credentials. One person may want 9:00 ± a few minutes, another
a wider spread.
→ `users.jitter_before_minutes` / `jitter_after_minutes`, editable in the
profile and the API. New users start from `CHECKIN_DEFAULT_JITTER_BEFORE_MINUTES`
(5) and `CHECKIN_DEFAULT_JITTER_AFTER_MINUTES` (4), the spread of the owner's
cron lines. Templates don't carry a jitter.
→ The window (`CHECKIN_WINDOW_MINUTES`, 15) stays instance-wide. It is the
safety rule that an action never runs outside it, and above all never late.
Every person's offset is checked against it by one function,
`checkin.core.schedule.jitter_problems()`, which the settings, the profile form
and the API all use.

**D-017: The service's packages are pinned apart from the cron path's; the legacy import also brings history** (Accepted, 2026-11-18)
`run.sh` installs `requirements.txt` into the live host's venv. Adding
SQLAlchemy, Alembic, pydantic and cryptography there would change the cron
path's environment for nothing it uses.
→ `requirements-service.txt` (includes `requirements.txt`) holds the
service's pins. The Docker image and `make venv` install it. The engine in
`checkin/core` still needs only the cron path's packages. `holidays` is
imported only when a calendar asks for public holidays.
→ `import-legacy` maps the cron set-up onto the new tables. The schedule
becomes a built-in template when the times match exactly, and an `imported`
template otherwise. Current and future overrides become day changes. The
cookie file becomes the stored session. `logs/actions.log` becomes
`planned_runs` rows with status `recorded` and `via = legacy-http`/`legacy-browser`.
That last part matters at cutover: the scheduler sees today's earlier actions
as done and doesn't clock them again. The activity IDs come from the legacy
adapter's constants, not from new code. Notification channels are replaced on
every import. Changes and history are only added.

**D-018: Scheduler details** (Accepted, 2026-11-18)
- Statuses: `planned`, `running`, `recorded`, `not_recorded` (nothing sent,
  or the browser fallback failed safely), `unknown` (may be recorded: never
  retried), `failed` (unexpected error), `skipped` (window missed),
  `cancelled` (the plan changed), `dry_run`.
- Runs whose window already passed when first planned get an alert only on the
  first planning pass after start-up, which means the service was down. Later
  passes come from the person's own edits (hours set to times already gone)
  and are only marked `skipped`.
- The leader lock is a row with a heartbeat. Another replica takes over after
  2 minutes of silence. Claims are conditional updates, so a takeover in the
  middle of a run still can't clock twice.
- Runs execute in an 8-thread pool in production and inline in tests. Each run
  opens its own short database sessions. The engine reports through the run's
  `say`, so concurrent runs keep separate logs (D-014).
- The end-of-day check is stored in `day_checks`, once per person per day,
  `verify_after_minutes` after their last planned action.

**D-019: Never hold a database write lock across network I/O** (Accepted, 2026-11-18)
SQLite allows one writer. The API tests deadlocked twice. First a request
saved a change and asked the scheduler to re-plan in a second transaction.
Then checking a token (which records `last_used_at`) held the write lock while
`verify` logged in to ePortem, and the session store's own write waited behind
it.
→ Re-planning after an API change joins the request's transaction
(`Scheduler.replan(user_id, db=db)`), so the change and its plan are saved
together. Token checks commit at once. Any route that talks to ePortem, Slack
or Telegram commits first. Each run's engine uses its own short sessions
(D-018).
→ This also applies on Postgres, where long transactions are just as
unwelcome.

**D-020: Web UI details** (Accepted, 2026-11-18)
- htmx is bundled in the app, not loaded from a CDN, so a self-hosted instance
  makes no third-party requests and works offline on a LAN. Version and sha256
  are in the plan. Update it deliberately.
- Sessions live server-side with only a hash of the id, so a copied database
  can't be replayed as cookies. CSRF tokens are an HMAC of the session id
  with the instance key, so they need no storage. htmx sends the token as a
  header set on `<body>`. Plain forms send it as a hidden field.
- The API accepts the session cookie too, which lets the UI call it, but only
  with the CSRF header for anything that changes data.
- The calendar engine says why a day has nothing to clock with a code
  (`off`: inactive, paused, time_off, holiday, day_off) plus a detail, instead
  of only an English sentence, so every language gets short labels.
- A setup checklist on the home page instead of a wizard for now. It is
  simpler, works with the normal pages, and doesn't trap anyone mid-flow.

**D-021: Packaging details** (Accepted, 2026-11-18)
- Debian's `chromium` + `chromium-driver` in the image, matching the cron host
  and keeping browser and driver in step without Selenium Manager downloads.
- Chromium runs with `--no-sandbox` only in the container
  (`CHECKIN_BROWSER_SANDBOX=false` set by the image). Its sandbox needs user
  namespaces that a non-root container usually lacks, and the container
  isolates it instead. The setting defaults to on everywhere else.
- Compose publishes on `127.0.0.1` by default. Exposing the UI is a deliberate
  choice (`CHECKIN_PUBLISH`), made with a reverse proxy for HTTPS.
- Metrics are computed from the database on each scrape, so there is no
  in-process state to lose on restart and no extra dependency. `/metrics`
  doesn't exist unless a token is set.
- Error reports never include request bodies, headers or cookies, and token-
  shaped strings are scrubbed.
- A cookie whose domain has no dot is stored for any host
  (`core.clock_http.cookie_domain`). Python's cookie jar would otherwise file
  it under `<host>.local` and never send it. Each HTTP session only talks to
  its own target, so this widens nothing.

**D-022: Shadow deployment and monitoring on the owner's host** (Accepted, 2026-11-18, owner's go-ahead)
- The shadow runs from a git worktree beside the live checkout, as its own
  Compose project. Your crontab and the live files are never touched. Dry run
  sends nothing to ePortem, Slack or Telegram, and the target is the fake as a
  second guard.
- Legacy files go into the container through a tar stream, not a bind mount.
  The container's user can't read `pi`'s `chmod 600` files, and loosening their
  permissions, or running the import as root, which would leave root-owned
  files in the data volume, was worse.
- GlitchTip (owner's choice of a free, bundled error tracker) runs without
  Valkey, using Postgres for queue and cache, to save memory on the NAS.
  The service reaches it over the Compose network, so it doesn't need to be
  public.
- Heartbeat: the owner suggested a path on the service's own hostname. A heartbeat has
  to be received by something other than the thing being watched, so the
  service POSTs to a GlitchTip heartbeat monitor instead. That catches a stuck or
  stopped service container. A dead host needs an outside monitor on
  `/healthz`, which now answers HEAD too.
- Going public: security headers and a strict CSP were added first, sessions are
  `Secure`, the admin password is 24 random URL-safe characters, and metrics,
  GlitchTip and the fake stay on `127.0.0.1`. Follow-up: behind Cloudflare the
  per-address sign-in limit sees Cloudflare's addresses. The per-user limit
  still holds. Trusting `CF-Connecting-IP` from Cloudflare's ranges would fix it.

**D-023: CLAUDE.md is general guidance; host notes and session state live elsewhere** (Accepted, 2026-11-18, owner's request)
CLAUDE.md had grown into the live host's logbook, and then a session handoff.
→ `CLAUDE.md`: only how to work on the repository (where things are written
down, README upkeep, commits and checks, testing against ePortem, the
refactor's rules). It is no longer skipped by the portability test, which now
keeps it free of personal values. `docs/OPERATIONS.md`: the live host (cron,
Chromium, mail, Slack credentials, deploying). `docs/HANDOFF.md`: where ongoing
work stands. Both are skipped by the portability test, with `TODO.md` and
`docs/http-api-investigation.md`.

**D-024: The CI workflow lives in `.gitea/workflows/` for now** (Accepted, 2026-11-18, owner's choice)
Gitea's push mirror to GitHub had been failing since phase 0. GitHub refuses
changes to `.github/workflows/` from a token without the `workflow` scope,
and the mirror's token doesn't have it. So GitHub's copy of the refactor
branch stopped at `ff12faa`. D-013 assumed one file serving both forges.
→ The workflow moved to `.gitea/workflows/check.yml`, which GitHub ignores.
Gitea Actions are still off, so it doesn't run anywhere yet. `make check`
before each commit remains the check. To revisit: give the mirror's token the
`workflow` scope and move the file back (GitHub would then run it), or enable
Gitea Actions with a runner.

**D-025: The project is called CheckIn** (Accepted, 2026-11-21, owner's request)
"ePortem" is the trademark of the site this project automates, so the project
can't use it as its own name. → Everything the project calls itself is now
CheckIn: the Python package and CLI (`checkin`, `python -m checkin`), the
settings (`CHECKIN_*`), metric names, the session cookie, the Docker image,
user, service and volume, the web UI and the docs. "ePortem" stays wherever it
names the site itself (the target URL, "your ePortem account", activity IDs,
the fake ePortem and `fake_eportem/`, the `EportemAccount`/`EportemSession`
models and their tables), which is the nominative use a trademark allows. The
legacy cron path (`main.py`, `eportem_action.py`, `utility/`, `config/.env`
with `EPORTEM_ENABLED`, `EPORTEM_HTTP`, `EPORTEM_USERNAME`...) keeps its
names: it is deleted at the cutover, and `main` isn't renamed. The repository
keeps its name for now. Existing installs keep working: every `EPORTEM_<NAME>`
(and `_FILE`, and `EPORTEM_CONFIG_FILE`) is still read when the `CHECKIN_` name
isn't set, with a warning; the default database stays `eportem.db` while no
`checkin.db` exists. Renaming the Compose service and volume does need a manual
step on an existing install (copy the old volume's data to the new one).

**D-026: The clock-in is never late and the clock-out never early** (Accepted, 2026-11-24, owner's request)
The random offset used to apply the same way to every action, so a 9:00 start
could be clocked at 9:04 and an 18:00 stop at 17:55 (the cron set-up did the
same). The owner wants the working day never cut short. → The planner puts
`start_day` only before the template's start and `stop_day` only after its
stop, at least 30 seconds out, spread over the person's whole offset (before +
after minutes, capped by the window); with the defaults (5 and 4) that is
08:51–08:59:30 and 18:00:30–18:09. Lunch out and back keep the symmetric
offset. Templates keep the real working hours (9:00 and 18:00), so the rule
holds for every template, built-in or custom, with no new setting. A planned run
that breaks the rule (planned before this change) is re-planned on the next
start-up. Catching up after an outage can still clock in late: within the window,
late beats not at all.

**D-027: A static public website, built apart from the service** (Accepted, 2026-11-24, owner's request; built on the branch `website`, merged 2026-11-25)
The owner wants a page that presents CheckIn to the world before sign-ups exist,
with terms that make clear CheckIn isn't responsible for wrong clock events, an
ePortem trademark disclaimer, and a visual style that shows our product and never
ePortem's. → `website/`: plain HTML and CSS in English and Spanish, built by a
standard-library script (`website/build.py`) into `website/dist/`, deployable on
any static host. Personal values (name, contact email, address, tax ID) live in
the untracked `website/site.env`, like every personal value (D-012), and the
build fails while one is missing. The site sets no cookies and loads nothing from
other sites (system fonts, drawn pictures), so its privacy policy stays short; a
test enforces that, the disclaimer on every page, and working links. Pictures are
HTML/CSS drawings of the product's own screens, each catalogued with its source in
`website/VISUALS.md` for when the UI is redesigned; the one picture of a
time-recording site is a generic illustration labelled as such. The legal pages
are a first draft to be reviewed before the service takes users. Not served by
the service itself: the site has to stay up and simple even when the service is
down or being changed. Hosting, agreed the same day: the site on Cloudflare Pages
at the address people already have, the app moved to its own hostname one level
below the zone (Cloudflare's free certificate covers only one level, so not
`app.<site address>`), rather than under a `/app` sub-path (never run in production,
and it would share an origin and cookies with the site).


Amended 2026-11-25 (owner's request): the site counts visits with Cloudflare Web
Analytics. It sets no cookies and Cloudflare injects its script at the edge (the
zone's automatic install, EU visitors included), so the source still loads nothing
from other sites and the test still holds; the privacy page and footer now say so.
The privacy page also names the host (`HOSTING_PROVIDER`) and says we keep no access
logs of our own, which replaces the self-hosted wording (`LOG_RETENTION_DAYS`). The
app's `script-src 'self'` blocks the injected script, so signed-in pages aren't counted. Also on 2026-11-25: links and canonicals became root-absolute and extensionless (Pages
redirected every `.html` link with a 308), and each language got a `404.html` (Pages answered
unknown paths with the home page and a 200).

**D-028: Managing CheckIn from an AI agent: a skill, signed in by device flow, only for account holders** (Accepted, 2026-11-25, owner's request; built on the branch `agent-skill`)
The owner wants to run their CheckIn (and clock in and out, as in ePortem) by
asking an AI agent, and to offer the same to other users. → Four parts:
(1) **Sign-in without a password:** the OAuth device authorization grant (RFC 8628),
cut down (`checkin/device.py`, table `device_grants`, migration 0003). The agent
asks `POST /api/v1/device/code` (no authentication, 10 per address per 10
minutes) and shows the person a link and an 8-letter code (no vowels, 10 minutes);
the person approves on `/device` in a signed-in browser, choosing read and/or write
(never more than asked, admin only for admins, 10 wrong codes per 5 minutes); the
agent polls `POST /api/v1/device/token` (`authorization_pending`, `slow_down`,
`access_denied`, `expired_token`) and gets an ordinary `ept_` token named "Agent:
<name>", valid 90 days, created at that poll so it is never stored in clear. Chosen
over pasting a token (people copy secrets into chats) and over a callback to a
local port (agents often run where no browser can reach them).
(2) **API for agents:** `GET /status` (who, today's plan and runs, next run, setup),
`GET /eportem/state` (reads ePortem's dashboard, never clocks: `working`,
`on_break` or `not_working`, from the buttons offered, and the actions that fit;
a switch between home and office while working is not offered as "back from
lunch"), `DELETE /tokens/current` (sign out), and the existing
`POST /actions/{action}` for clocking now. Clocking stays the four actions through
the run system, so a manual clock shows in history, notifies, and replaces that
day's planned run; ePortem's other pauses (absence, medical...) are not offered.
(3) **The skill:** `skill/checkin/` (`SKILL.md` and a standard-library script for
Python 3.9+, `scripts/checkin.py`: `login`, `login --wait`, `status`, `state`,
`clock ACTION --yes`, `get|post|put|patch|delete`, `update`). The token lives in
`~/.config/checkin/agent.json` (mode 600) and is never printed; clocking refuses
without `--yes`, and SKILL.md has the agent confirm the action and place first.
(4) **Distribution only to account holders:** the public website says the skill
exists and what it does (home section, `/agents`, illustration `agent-chat`) but
publishes no file. The app serves it: the API tokens page shows a text to paste
into an agent with a personal install link, `/skill/<user>.<expiry>.<HMAC>/install.sh`
(signed with the instance key, 24 hours, dead once the account isn't active), and
the skill updates itself from `/api/v1/skill` with its own token, checking the
zip's sha256 and swapping folders only once the new one is complete. The zip is
built in memory with a `defaults.json` naming the instance, and is byte-for-byte
stable. The Docker image now copies `skill/`. In this repository,
`.claude/skills/checkin` is an untracked symlink to `skill/checkin`, with an
untracked `defaults.json`, so the maintainer runs their own account from here.

Amended 2026-11-25 (owner's request), D-027 and D-028: the build strips HTML comments,
so the pictures' notes (which name repository files) stay in the source and never reach
the published pages; a test checks it. The site deploys with `website/deploy.sh`, which
runs wrangler with an empty environment and a throwaway home folder and a Pages-only
token from the untracked `website/deploy.env`, after checking the token reaches the
Pages project, so a machine holding another Cloudflare account's credentials (the work
Mac) can deploy without any risk of using them.
