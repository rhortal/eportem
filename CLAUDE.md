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

## Git remotes: commit and push to Gitea only

`origin` is Gitea, over HTTPS:
`https://gitea.tiorob-home.mywire.org/roberto/eportem.git` (SSH on port 22
isn't reachable from outside the LAN). Gitea pushes on to GitHub
(`github.com/rhortal/eportem`) by itself, so never push to GitHub directly or
add it as a remote. Until 2026-11-17 the Mac checkout's `origin` pointed at
GitHub, so `dfb9101` went to GitHub first and Gitea, which `omv` pulls from,
lagged behind; `omv` was deployed by fetching from GitHub that once. Deploy
`omv` with `git pull --ff-only` from its own `origin` (Gitea).

## Host: this runs on `omv` (OMV NAS, Debian 13 trixie, Intel N95, user `pi`)

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
Selenium+chromedriver using the flags ePortem used then (`--headless` only)
all passed. The flags have changed since: see "Browser flags" below. Note: `--single-process` (not
used by ePortem) still SIGTRAPs on `150.0.7871.181`, so the upstream bug
isn't fully fixed — it just doesn't trigger under the flags ePortem uses.
No hold is currently in place; the package is on the normal apt-managed
security-update track again.

If ePortem's automation silently stops firing again, check
`chromium --version` and try
`chromium --headless --disable-gpu --no-sandbox --dump-dom about:blank`
before assuming the ePortem site's HTML/selectors changed. Also check whether
the login page now rejects the headless browser via reCAPTCHA v3 (error
"No se ha podido verificar que no es un robot" in the page after submit) —
see `docs/http-api-investigation.md` — and don't rule
out a fresh regression in whatever version unattended-upgrades has since
pushed, since `--single-process` still crashed on this host as of 150.x.

### Browser flags and version (checked 2026-11-16)

`omv` now runs Chromium `156.0.8078.79`. The flags come from `start_browser()`
in `eportem/core/browser.py` (called through `utility/login_and_navigate.py`
on the refactor branch; on `main` before the merge it is `_start_browser()` in
`utility/login_and_navigate.py` itself), not `eportem_action.py`: `--disable-gpu`,
`--headless=new` (only when `HEADLESS_BROWSING=YES`), `--window-size=1366,900`,
`--lang=es-ES`, `--disable-blink-features=AutomationControlled`, a desktop
`user-agent=`, and the automation switches turned off. They were added on
2026-10-29 for reCAPTCHA, after the 20-launch test above, so that test doesn't
cover them. The `chromium --headless ...` command above only shows whether
Chromium starts at all.

The `USER_AGENT` constant (in `eportem/core/browser.py` on the refactor
branch) says Chrome/156, matching the host. When Chromium's
major version changes, `create_driver()` notices, restarts the browser once
with the right version in the UA and prints a line saying so; update the
constant to avoid that extra start. The UA is set with the launch flag on
purpose: a per-page DevTools override would not reach the reCAPTCHA frames.

## Cron schedule lives outside the repo

`config/config.json` only defines the target times `main.py` checks against
(±15 minute window). The actual trigger timing is in the system crontab
(`crontab -l` as user `pi`), which fires early and sleeps a random amount so
staff-tracking timestamps look less robotic. Each cron line must land its
`base time + max random sleep` inside the ±15 min window of the
corresponding `config.json` entry, e.g. for a 18:00 target, base time should
be ~17:55 with a small random sleep — not 18:10, which can drift outside the
window. When adding/editing schedule entries, keep base time = target − 5min
and a 0-9 minute random sleep, copying an existing line exactly. The live
lines (checked 2026-11-16) have this shape, and need both `bash -c` (cron's
`sh` is dash, which has no `$RANDOM`) and `\%` (cron turns a bare `%` into a
newline):

```
55 17 * * 1-5 bash -c 'sleep $((RANDOM \% 10))m; out=$(/home/pi/Apps/eportem/run.sh 2>&1) || { echo "$out"; exit 1; }'
```

The wrapper prints, and so mails, only when `run.sh` exits non-zero. Since the
2026-11-16 review changes that includes: exit 3 from `main.py` when a run
lands outside every window (no longer a silent no-op), exit 2 for an invalid
`config/config.json` or an unreadable `holiday_override.txt` (it refuses to
clock), and exit 75 from `run.sh` when another run holds the `flock` lock
(`.run.lock`). `./run.sh --check` shows what would run now without clocking.

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

Nothing is truly gone: the full pre-removal tree is the tag
`archive/web-ui-docker-mock-server` (the last commit before the removal; it
was a branch until 2026-11-16, when the archive branches became tags). The
tag `archive/holidays-json-experiment` keeps an unmerged July 2026 experiment
with holidays and business trips in a JSON file, superseded by
`holiday_override.py` / `override_location.py`. `eportem_action.py` and
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
status updates — have never actually worked here; at the time,
`SlackChannel.send` skipped with a log line instead of making a malformed
request when the webhook was empty — see the 2026-11-16 update below for
what it does now).
`config/.env` and `config/.env.bak` are `chmod 600` (the `.bak` file is
owned by `root`, left over from the web UI writing it — needed `sudo` to
fix).

**Update 2026-11-16:** with no webhook set, `SlackChannel` now sends
notifications through `SLACK_TOKEN` using `chat.postMessage`, to the owner's
own DM (user ID from `auth.test`; `SLACK_NOTIFY_CHANNEL` overrides it). When
checked on 2026-11-16 the token on this host had only
`identify,users:write,users.profile:write`, so Slack notifications fail with
`missing_scope` until `chat:write` is added under User Token Scopes and the app
is reinstalled. Reinstalling may issue a new token, which then has to replace
`SLACK_TOKEN` in `config/.env` on `omv` (the status update uses the same
token). `SLACK_WEBHOOK_URL` stays empty there; if it were set it would win.

**Update 2026-11-16 (bot route):** the owner chose to send notifications as the
app's bot, because a message posted to your own DM as yourself arrives silently
while one from the app in your DM with the app alerts you. The app got the
`chat:write` bot scope, and `SLACK_BOT_TOKEN` (Bot User OAuth Token, `xoxb-`)
must be added to `config/.env` on `omv`. Order in `SlackChannel`: webhook, else
bot token, else `SLACK_TOKEN` (the fallback described above), else skip. On the
bot path the destination is `SLACK_NOTIFY_CHANNEL`, or else the owner's user ID
from `auth.test` called with the user token (a bot token's `auth.test` returns
the bot's own ID). The user token (ends `a598`) still has only
`identify,users:write,users.profile:write`; it stays for the status and for
finding the owner's user ID, so the earlier note about adding `chat:write` to it
no longer applies.

## Mail (cron failure notifications)

Postfix relays outbound mail via `<mail relay host>:465` (implicit TLS) as
`<relay sender address>` (previously Gmail, which had failing SASL auth and was
silently dropping all cron failure emails for days before this was caught).
Key files: `/etc/postfix/sasl_passwd` (relay credentials),
`/etc/postfix/sender_canonical` (rewrites outgoing sender to
`<relay sender address>` — sender only, never recipient; don't use
`smtp_generic_maps` for this, it also rewrites matching recipients and will
misdeliver mail). `/etc/postfix/recipient_canonical` (pre-existing) maps
local system users (root/pi/admin/@omv.local) to `<owner's personal email>` for
local cron/system mail — unrelated to ePortem specifically, don't remove it.

## Direct-HTTP (no browser) clocking — all actions, since 2026-11-16

**Picking this up in a new session: read the "Handoff" section at the top of
`docs/http-api-investigation.md` first.** It has the live state, what ran on
2026-11-16 and how to check it, and the next steps. Login can't be done with plain
HTTP (reCAPTCHA v3), so `utility/http_clock.py` logs in with Selenium only when
the saved cookies (`config/.session_cookies.json`) have expired, then sends
the clock action as `GET .../registro/reghorario.cshtml`.

On this host the checkout is on **`main`** (the work was merged from
`http-clock-actions` on 2026-11-16). Which actions go over HTTP is set by `EPORTEM_HTTP` in `config/.env`
(`YES`, `NO` or a list like `lunch_break,after_lunch`); cron calls `run.sh`
for every line, and `main.py` applies holidays and overrides before
`EPortemAction.perform()` tries HTTP and falls back to Selenium only when
nothing was recorded. Since 2026-11-16 14:57 `omv` has `EPORTEM_HTTP=YES`. The earlier
crontab backups were deleted on 2026-11-17. Every
HTTP attempt is logged to `logs/http_clock.log`. A dry run
(`python3 -m utility.http_clock ACTION`) never changes clock status, but it
skips the holiday/override checks.

`at` was installed on 2026-11-16 for one-off jobs (e.g. timed
`utility.capture_dashboard` runs; output in `logs/capture.log`). Use `atq` to
list pending jobs. The first full all-HTTP day (2026-11-17) ran cleanly and
passed `--verify-day`; the rollout leftovers on the host were cleared that
evening.

## Alerts and the daily check (added 2026-11-16)

Every recorded action is appended to `logs/actions.log` (time, date, action,
location, `http`/`browser`). `./run.sh --verify-day`, from cron at 18:40 on
weekdays, compares today's due actions with that file and alerts on Telegram
and Slack (exit 4, so cron mails too) when one is missing or recorded twice.
A cron run that fails (exception, exit 2 invalid config/holiday file, exit 3
outside every window) also sends a short alert on the same channels. Output
lines carry `HH:MM:SS` timestamps. `EPORTEM_ENABLED` other than `YES` is now a
quiet off switch: one line and exit 0, no mail and no alert.

`logs/actions.log` only exists from the deploy on the evening of 2026-11-16,
so the verify line was added to the crontab after that day's 18:40 slot; a
day's check is only meaningful once that day's actions were all run by the
new code.

Open items for the host live in `TODO.md` (tracked).

## Refactor to a multi-user service (branch `refactor/multiuser-service`, from 2026-11-18)

Work to replace cron with a built-in scheduler, add multiple users, a web UI
and API, and Docker packaging. Plan: `docs/refactor/PLAN.md`; decisions:
`docs/refactor/DECISIONS.md`. Update both in the same commit as the code
they describe. Until the phase 8 cutover, `main` and the cron path on `omv`
stay live and must keep working. Nothing on the branch may call the real
clock endpoint: development and tests use the fake ePortem server
(`fake_eportem/`, PLAN.md section 7).

State on 2026-11-18: phases 0-7 done on the branch (engine, fake, calendar,
database, scheduler, API, web UI, Docker), `make check` green. Phase 8 (the
cutover on `omv`) and the read-only contract check against the real site wait
for the owner; see `TODO.md`. Rule from D-019: never hold a database write lock
across network I/O.
