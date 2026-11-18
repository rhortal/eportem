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
