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
→ The service is Python 3.13. Today's modules move into `eportem.core` and get
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
→ SQLAlchemy 2 + Alembic. SQLite (WAL) at `/data/eportem.db`, or Postgres
through `DATABASE_URL`. A leader lock means only one replica schedules.

**D-005: Secrets encrypted at rest with an instance key** (Proposed, 2026-11-18)
The service stores users' ePortem passwords, ePortem session cookies and
Slack/Telegram tokens.
→ Fernet/MultiFernet with `EPORTEM_SECRET_KEY` (env or Docker secret).
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
`eportem check-contract` compares the real site with the fixtures and never
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
`EPORTEM_*` env vars > a TOML config file > neutral defaults, with `*_FILE`
for secrets. It is checked on start-up, and `eportem config show` prints it.
`.env.example` and the README settings table are checked against the
module by a test. A portability test fails CI on personal emails, private IPs
or unknown hostnames in tracked files. Per-user values (credentials, activity
IDs, status texts, timezone) live in the database.
→ The owner's production values (hostname, port, proxy, SMTP, Sentry,
heartbeat) are chosen at cutover in an untracked `.env`. Host-specific
operations notes stay in `CLAUDE.md`. README and `docs/` stay generic.

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
it. `eportem.contract` checks it on the real site.
