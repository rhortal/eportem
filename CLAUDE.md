# ePortem — operational notes

See README.md for what this project does and how to run it. This file covers
host-specific state that isn't visible from the repo itself but matters when
debugging why automated runs fail.

## Keep README.md current

README.md is the actual project documentation (features, usage, CLI
commands, testing, dev notes) — CLAUDE.md is only for host/operational
context that doesn't belong there. When a change alters user-visible
behavior — a new script or CLI flag, a changed file format, a renamed env
var, a feature added/removed/relocated (e.g. the business-trip move from
`holiday_override.py` to `override_location.py`, or the 2026-08-10 removal
of the web UI/Docker/mock server below) — update README.md in the same
commit, not as a follow-up.

Separately, check README.md for drift at the start of a session if it's
been a while: run `git log -1 --format=%cd -- README.md` and compare
against `git log -10 --oneline` (or `git log --format=%cd -1` for the
latest commit overall). If meaningful commits have landed since the last
README touch — roughly a couple of weeks, or several feature-shaped
commits, whichever comes first — read through README.md against the
current state of the scripts/CLI and fix what's gone stale, even if the
user didn't ask.

## Host: this runs on `omv` (Raspberry Pi / OMV NAS, Debian 13 trixie, Intel N95)

## Chromium hold history — was pinned at 149.x, unheld 2026-07-27

`chromium`, `chromium-common`, `chromium-driver` were held at `149.0.7827.196`
via `apt-mark hold` from 2026-07-06 to 2026-07-27. Chromium 150.0.7871.46
(the version Debian's unattended-upgrades pushed on 2026-07-06) crashed with
`SIGTRAP` on essentially every headless launch on this host — confirmed
~100% reproducible across `--no-sandbox`, `--single-process`, `--jitless`,
and multiple GL backends, so it was a genuine upstream regression for this
platform, not a flag/config issue.

On 2026-07-27 the hold was removed and the packages upgraded to
`150.0.7871.181` after verifying: 20 consecutive headless launches via
Selenium+chromedriver using ePortem's actual production flags (`--headless`
only, per `eportem_action.py`) all passed. Note: `--single-process` (not
used by ePortem) still SIGTRAPs on `150.0.7871.181`, so the upstream bug
isn't fully fixed — it just doesn't trigger under the flags ePortem uses.
No hold is currently in place; the package is on the normal apt-managed
security-update track again.

If ePortem's automation silently stops firing again, check
`chromium --version` and try
`chromium --headless --disable-gpu --no-sandbox --dump-dom about:blank`
before assuming the ePortem site's HTML/selectors changed — and don't rule
out a fresh regression in whatever version unattended-upgrades has since
pushed, since `--single-process` still crashes on this host as of 150.x.

## Cron schedule lives outside the repo

`config/config.json` only defines the target times `main.py` checks against
(±15 minute window). The actual trigger timing is in the system crontab
(`crontab -l` as user `pi`), which fires early and sleeps a random amount so
staff-tracking timestamps look less robotic. Each cron line must land its
`base time + max random sleep` inside the ±15 min window of the
corresponding `config.json` entry, e.g. for a 18:00 target, base time should
be ~17:55 with a small random sleep — not 18:10, which can drift outside the
window and silently no-op. When adding/editing schedule entries, keep base
time = target − 5min and `sleep $[RANDOM%10]m`, matching the existing lines.

## Web UI, Docker, and mock server were removed (2026-08-10)

`web_ui/`, `Dockerfile`/`docker-compose.yml`, and the mock server
(`utility/server.py`, `mock_server/`, `run_mock_server.py`, plus the tests
that only existed to cover them: `tests/test_api.py`, `tests/test_ui_live.py`,
`tests/conftest.py`, `tests/test_with_mock.py`) were experiments that never
got adopted — the user only ever ran the plain scripts (`run.sh` → `main.py`
→ `eportem_action.py`) via cron. A full-codebase review earlier the same day
found real problems in the web UI (Werkzeug debug mode bound to `0.0.0.0`,
unauthenticated endpoints returning plaintext credentials) and the mock
server (wrong template path, mock login fields that didn't match the real
ePortem login form since the `usuario` rename) — rather than fix unused,
broken code, the user asked to delete it.

Nothing is truly gone: the full pre-removal tree is preserved on the remote
branch `archive/web-ui-docker-mock-server` (branched off the last commit
before the removal). `eportem_action.py` and
`utility/login_and_navigate.py` also got a cleanup pass to drop the
`USE_MOCK_SERVER`/`--mock`/`--use-mock-server` branches that existed only to
support the mock server — the real automation path's behavior is unchanged
(those branches only ever swallowed errors or diverged when mocking).

If asked to add a web UI, dashboard, or Docker packaging back: this isn't
starting from scratch, there's a whole prior implementation on that archive
branch worth looking at first (with known issues to fix, not copy as-is).

## Slack credentials: SLACK_WEBHOOK split into SLACK_TOKEN / SLACK_WEBHOOK_URL (2026-08-10)

`config/.env` used to have a single `SLACK_WEBHOOK` var doing double duty as
both a webhook URL suffix (for `SLACK_NOTIFY`) and an OAuth bearer token
(for `SLACK_STATUS`) — since only a token-shaped value actually worked for
status updates, `SLACK_NOTIFY=YES` was silently sending that token in a URL
to `hooks.slack.com` instead of delivering a notification. This host's real
`config/.env` was migrated: the existing token value now lives under
`SLACK_TOKEN`, and `SLACK_WEBHOOK_URL` was added empty (there was never a
real Incoming Webhook configured, so Slack *notifications* — as opposed to
status updates — have never actually worked here; `SlackChannel.send` now
skips cleanly with a log line instead of making a malformed request). If
Slack notifications should actually start working, `SLACK_WEBHOOK_URL`
needs a real Incoming Webhook URL from Slack, not just a truthy value.
`config/.env` and `config/.env.bak` are `chmod 600` (the `.bak` file is
owned by `root`, left over from the web UI writing it — needed `sudo` to
fix).

## Mail (cron failure notifications)

Postfix relays outbound mail via `mail.hortal.me:465` (implicit TLS) as
`eportem@hortal.me` (previously Gmail, which had failing SASL auth and was
silently dropping all cron failure emails for days before this was caught).
Key files: `/etc/postfix/sasl_passwd` (relay credentials),
`/etc/postfix/sender_canonical` (rewrites outgoing sender to
`eportem@hortal.me` — sender only, never recipient; don't use
`smtp_generic_maps` for this, it also rewrites matching recipients and will
misdeliver mail). `/etc/postfix/recipient_canonical` (pre-existing) maps
local system users (root/pi/admin/@omv.local) to `rhortal@gmail.com` for
local cron/system mail — unrelated to ePortem specifically, don't remove it.
