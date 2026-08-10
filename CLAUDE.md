# ePortem — operational notes

See README.md for what this project does and how to run it. This file covers
host-specific state that isn't visible from the repo itself but matters when
debugging why automated runs fail.

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

## Web UI, Docker, and mock server are unused experiments

`web_ui/`, `Dockerfile`/`docker-compose.yml`, and the mock server
(`utility/server.py`, `mock_server/`, `run_mock_server.py`) were experiments
that never got adopted — the user only runs the plain scripts (`run.sh` →
`main.py` → `eportem_action.py`) via cron, as described above and in
README.md. A 2026-08-10 full-codebase review found real problems in the web
UI (Werkzeug debug mode bound to `0.0.0.0`, unauthenticated endpoints that
return plaintext credentials) and the mock server (wrong template path,
mock login form fields don't match the real ePortem login form since the
`usuario` field rename). None of this was fixed — it's explicitly out of
scope until/unless the user decides to actually use one of them. Don't
assume it's safe to run `web_ui/server.py` or the Docker image as-is if
asked to; flag the known issues first.

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
