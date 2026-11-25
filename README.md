# CheckIn

CheckIn automates clocking in and out on ePortem: start of day, lunch break, return from lunch, and end of day - for both office and home working.

Optionally, it notifies you on Telegram and Slack, and can keep your Slack status in sync with what you're doing.

ePortem is a SaaS solution used in Spain for HR-related tasks. CheckIn automates the functionality that enables people to track the time they spend at work every day, as required by Spanish law.

CheckIn is an independent project, not made, endorsed or supported by ePortem; "ePortem" is a trademark of its owner and is used here only to say which site CheckIn works with. The project was called ePortem until 2026-11-21: the service still reads its old `EPORTEM_*` settings and `eportem.db` database file (see [Running the service](#running-the-service-with-docker-refactor-branch)).

## Features

- Automated time tracking for office and remote work, triggered by cron
- Can clock with a direct HTTP request (the browser then only logs in when the saved session has expired), falling back to the browser click flow when that fails; off by default, see `EPORTEM_HTTP`
- Start of day, lunch break, return from lunch, and end of day actions
- Telegram and Slack notifications, plus live Slack status updates
- Per-day location override (home/office)
- Business trip mode: check-ins run as normal, but Slack status stays "On a business trip" for the whole trip
- Holiday mode: skips check-ins and notifications entirely for a date range, with a matching Slack status
- Fails loudly: an invalid `config/config.json`, an unreadable holiday file, or a run that matches no scheduled action exits non-zero, so cron mails it, and also sends a short alert on Telegram/Slack
- Day check: `--verify-day` compares what was scheduled today with what was recorded and alerts if an action is missing or was recorded twice
- Every output line of a cron run starts with a `HH:MM:SS` timestamp

## Deployment

To deploy this project, clone this repo and make sure you have the python3 binary in your PATH.

Make sure Chrome or Chromium itself is installed, plus its driver (the driver alone is not enough):
### On Ubuntu:
```shell
sudo apt install chromium-browser chromium-chromedriver
```
### On Debian:
```shell
sudo apt install chromium chromium-driver
```
### On macOS
install Homebrew then do
```shell
brew install --cask google-chrome chromedriver
```
Then create the `.env` file (below) and set up the Python environment with:

```bash
./run.sh --install
```

It creates a `venv` and installs `requirements.txt`, and exits without running `main.py` (a plain `./run.sh` also runs `main.py`, which records a real clock event if it's within 15 minutes of a scheduled time). `run.sh` also rebuilds the `venv` if its packages no longer import (e.g. after a system Python upgrade): the new `venv` is built beside the old one and only swapped in if the install works, and if it fails `run.sh` stops with a non-zero exit instead of running `main.py`. `install-reqs.sh` is a shortcut for `./run.sh --install`.

`run.sh` takes an exclusive lock (`.run.lock`, via `flock`) so two overlapping runs can't both clock; the second one prints a message and exits 75 without doing anything. On macOS, which has no `flock`, it runs without the lock.

The software takes configuration including ePortem, Telegram and Slack credentials from a `.env` file. To set this up:
- Copy `config/.env.template` to `config/.env`
- Open `.env` with your favourite editor (`nano config/.env` or `code config/.env`)
- Enter values for all variables as per comments in the file
- Set permissions so only you can read it: `chmod 600 config/.env`

The `YES`/`NO` flags are exact matches: only the exact text `YES` turns a feature on. `TELEGRAM_NOTIFY`, `SLACK_NOTIFY` and `SLACK_STATUS` ship as `NO`; set each to `YES` only after filling in its credentials. Two general flags matter for cron:
- `EPORTEM_ENABLED` is a quiet off switch: anything other than exactly `YES` makes every run print `ePortem is disabled (EPORTEM_ENABLED is not YES); nothing done.` and exit 0, so there is no cron mail and no alert. It is checked first, before the config is validated and before any holiday Slack status is set. The scripts run directly (`start_day.py`, `eportem_action.py`, ...) stop the same way, with exit status 0. `./run.sh --check` still validates (it clocks nothing) and adds a note that a real run would do nothing.
- `HEADLESS_BROWSING` must be `YES` under cron; anything else opens a visible browser window.

### Slack notification credentials

Slack notifications are sent by the Slack app's bot, so they arrive in your DM
with the app and Slack alerts you (a message you post to your own DM as
yourself arrives silently). The status update uses your user token. Both are
read from `config/.env`:
- `SLACK_BOT_TOKEN`: the Bot User OAuth Token (`xoxb-...`) with the `chat:write`
  bot scope. Used for `SLACK_NOTIFY=YES`.
- `SLACK_TOKEN`: an OAuth user token (`xoxp-...`). `SLACK_STATUS=YES` needs its
  `users.profile:write` scope; it is also used to find your user ID, which is
  where the bot sends the message.
- `SLACK_NOTIFY_CHANNEL` (optional): a channel or user ID (`C...` / `U...`) to
  send to instead. Without it and without `SLACK_TOKEN`, the bot has nobody
  to send to and the notification fails.
- `SLACK_WEBHOOK_URL` (optional): a full Incoming Webhook URL
  (`https://hooks.slack.com/services/...`). If it is set, notifications go
  through it instead of the tokens.

Without `SLACK_BOT_TOKEN`, `SLACK_TOKEN` is used instead if it has the
`chat:write` user scope: it posts as you to your own DM, silently. If none of
the three is set, the notification is skipped.

To set up the bot: in the Slack app go to OAuth & Permissions, Bot Token Scopes,
add `chat:write`, install (or reinstall) the app, and copy the Bot User OAuth
Token into `SLACK_BOT_TOKEN`. Optionally, under App Home, Show Tabs, enable the
Messages tab so you can see the DM with the app.

If a notification fails with "the bot token lacks the chat:write scope", the
scope is missing or the app was not reinstalled after adding it; if the app
is not in the channel you set, invite it or use your user ID instead.

### Failure alerts and the day check

Besides the cron mail, a failed cron run sends a short alert on the same
channels as the clock notifications (`TELEGRAM_NOTIFY` / `SLACK_NOTIFY`; the
same credentials, 15-second timeout):

```
ePortem: lunch_break FAILED at 13:41 - OutcomeUnknown: the request timed out. Check ePortem by hand; details in the cron mail.
```

It is sent when `main.py` ends with an exception, exit 2 (invalid
configuration) or exit 3 (no window matched). The alert names the action
that was running when an exception hit, otherwise `run`. The reason is the exception type and
a short one-line message with tokens, webhook URLs and the ePortem password
removed; there is never a traceback (that is in the cron mail). Sending the
alert can't fail the run or change its exit code. No alert is sent for
`--check`, for a wrong command-line argument, when `EPORTEM_ENABLED` is off, or
when the action was recorded and only a follow-up (notification, Slack status)
failed: that run is still a success (see below).

`--verify-day` (see [Usage](#usage)) uses the same channels to say that a
scheduled action never got recorded.

### When a notification fails

Notifications and the Slack status are sent after the clock action is
recorded, so a problem with them never fails the run. Each one is tried on its
own with a 15-second timeout: a Telegram error doesn't stop Slack or the
status. If any of them fails, the run prints

```
WARNING: the clock action WAS recorded, but these follow-ups failed: telegram, slack status
```

and still exits 0, so cron doesn't mail it as a failed clock-in. The warning is
in that run's block in `logs/http_clock.log`. A notifier that is
switched on without its credentials is skipped with a one-line message and
isn't counted as a failure. Tokens and webhook URLs are removed from any error
text before it is printed.

### Clocking without the browser (`EPORTEM_HTTP`)

`EPORTEM_HTTP` in `config/.env` (default `NO`) chooses which actions are sent as a direct HTTP
request (the same `reghorario.cshtml` call the dashboard's buttons make)
instead of clicking through Chromium:

- `YES` (or `ALL`): every action.
- A comma-separated list, e.g. `lunch_break,after_lunch`: only those actions.
- `NO` or unset: none; the Selenium click flow as before.

Nothing else changes: cron still calls `run.sh`, and `main.py` still applies the
schedule, holidays and location overrides before any action is sent, whichever
way it is sent. Chromium is still used to log in, because the login page has
reCAPTCHA, but only when the saved session in `config/.session_cookies.json`
(gitignored, `chmod 600`) has expired, which in practice means the first
action of each day.

If HTTP recorded nothing (for example the button wasn't on the dashboard, or
the login failed), the same run falls back to the Selenium click flow. If the
request went out and it can't be told whether it was recorded, it fails without
retrying, so nothing is clocked twice, and cron mails the output. Every clock
run is appended to `logs/http_clock.log` as one block: a header line with the
outcome (`recorded over HTTP`, `not recorded, falling back to the browser: ...`,
`OUTCOME UNKNOWN: ...`, `ERROR, no fallback: ...`, or `recorded with the
browser (HTTP not enabled for this action)`), then everything the run printed
in order: the HTTP attempt, the browser fallback if there was one, and the
notification and Slack status lines. Runs that only use the browser are in it
too, so it is the record of every clock run, despite its name. Details:
`docs/http-api-investigation.md`.

How a run decides whether the action was recorded:

- **Recorded**: the server answered with a clock result. An answer that isn't
  one (an error page, an empty or unexpected JSON body) is not trusted.
- **Checked on the dashboard**: if the request failed or the answer wasn't a
  clock result, the dashboard is read up to 3 times, 5 seconds apart. If it no
  longer offers the button, the action is recorded.
- **Not recorded, fall back to the browser**: the dashboard still offers the
  button and the request can't have reached the server (it never connected, or
  the server answered with an error).
- **Unknown, fail without retrying**: the request timed out or the connection
  dropped after it was sent, or the dashboard can't be read (a maintenance
  page, no buttons at all, a lost session). Check ePortem by hand.

`lunch_break` only ever sends the "Comida" pause: if the dashboard doesn't
offer it, nothing is sent over HTTP. `EPORTEM_HTTP` is not case-sensitive
(`yes`, `true` and `1` also mean every action), and a name in the list that
isn't an action is reported with a warning and ignored.

The log file and its folder are readable only by you (`chmod 600` / `700`).
At about 1 MB the log is rotated to `http_clock.log.1`, the older ones shift
up to `.5` and the oldest is dropped (`utility/logfiles.py`).

To see which request an action would send, without sending it (this skips the
schedule, holiday and override checks, so use it for testing by hand only):

```bash
venv/bin/python3 -m utility.http_clock lunch_break --location office          # dry run
venv/bin/python3 -m utility.http_clock lunch_break --location office --send   # real clock event
```

`--send` refuses to run unless `EPORTEM_ENABLED=YES`; the dry run always works.

## Usage

To run the script, use the `run.sh` script in the root directory:

```bash
./run.sh
```

`main.py` checks `config/config.json` for today's schedule and, if the
current time is within 15 minutes of a scheduled action, performs it. This
is what cron calls (see [Automation](#automation)) - it's not meant to be
run continuously. Don't run it by hand near a scheduled time unless you
want that action recorded.

To see what it would do without clocking anything, use `--check`:

```bash
./run.sh --check
```

It validates `config/config.json` and the override files, then prints which
action would run now and with which location. It never clocks, and exits 0
unless something is invalid.

Exit codes of `main.py` (and so of `run.sh`, which passes them through):

| Code | Meaning |
|------|---------|
| 0 | An action ran, or there was nothing to do (holiday, no schedule for today's weekday, `EPORTEM_ENABLED` not `YES`), or `--verify-day` found everything recorded |
| 2 | `config/config.json` or `holiday_override.txt` is invalid; nothing was clocked |
| 3 | Today has a schedule, but the current time is outside every action's window |
| 4 | `--verify-day` only: a scheduled action was not recorded today, or was recorded twice |
| 75 | `run.sh` only: another run holds the lock |

Exit 2, exit 3 and a crash also send a failure alert (see
[Failure alerts and the day check](#failure-alerts-and-the-day-check)).
Every output line starts with the time (`09:01:12 `), so the cron mail and
the logs show when each step happened; this applies to what `main.py` prints
when run, not to the other scripts.

Cron mails the output of any non-zero run. Exit 3 almost always means a
crontab line fires outside its window (see [Automation](#automation)).

To check at the end of the day that everything was clocked, use `--verify-day`:

```bash
./run.sh --verify-day
```

Each action that `main.py` records (over HTTP or the browser) appends a line
to `logs/actions.log` (timestamp, date, action, location, `http` or `browser`;
`chmod 600`, folder `700`; rotated like `http_clock.log`: 1 MB, 5 generations).
`--verify-day` takes today's schedule from
`config/config.json`, the same way a normal run does, and compares the
actions whose window has closed (target + 15 minutes + `VERIFY_GRACE_MINUTES`,
another 15, in `main.py`) with that log (and its rotated generations), so it is safe to run at any time of
day. An action that is still inside its window is not judged. Then:

- Holiday, nothing scheduled today, or `EPORTEM_ENABLED` off: it prints a line
  and exits 0, with no alert.
- Everything recorded once: `Day check OK: ...`, exit 0.
- Something missing, or recorded twice (a possible double clock-in): it prints
  the details, sends an alert such as `ePortem: today's lunch_break and
  after_lunch were not recorded. Check Registro Jornada.` and exits 4, so cron
  mails it too.
- Invalid config or holiday file: exit 2, as for a normal run.

`--verify-day` and `--check` can't be combined.

`main.py` and the action scripts need the `venv` created by `run.sh --install`.
Run them with `venv/bin/python3`. Only `override_location.py` and
`holiday_override.py` work with a plain `python3`.

### Overriding Location

Override the location for a single day using `override_location.py` (works from any directory, and with plain `python3`; it prints the full path of the file it wrote):

```bash
python3 override_location.py home
python3 override_location.py office
```

This sets the location to `home`/`office` for the current day only - it's
read by `main.py` and used for both which ePortem buttons to click and the
Slack status text. The override files live in the repository root, wherever
you run the script from. To cancel, delete the `location_override.txt` file. Once the
day has passed, the next run that reads it deletes it automatically.

The file is `home,YYYY-MM-DD` (or `office,...`); the location is matched
case-insensitively and must be `home` or `office`. If the file is malformed
or has any other location, `main.py` prints the file's path and the reason
to stderr, ignores it and uses the location from `config/config.json`; it
never deletes a malformed file.

### Marking Holidays

If you're on holiday (not working at all), use `holiday_override.py` so
`main.py` skips ePortem check-ins and the normal start/lunch/stop Telegram
and Slack notifications entirely for those days (again, from any directory,
with plain `python3`):

```bash
# Single day
python3 holiday_override.py 2026-08-17

# Date range (inclusive)
python3 holiday_override.py 2026-08-17 2026-08-21
```

If `SLACK_STATUS=YES` in your `.env`, it also sets your Slack status to "On
holiday" `:palm_tree:` on every run while the override is active, with an
expiration of end-of-day on the range's last date so Slack clears it
automatically once you're back. Setting it repeatedly (once per cron run for
the whole range) is harmless - it's just overwriting the same status each
time. To cancel early, delete the `holiday_override.txt` file. Once every date in the file has passed, the next run that reads it deletes it
automatically.

A holiday file that can't be read must not turn into a day of clock-ins, so
`main.py` fails closed. It tolerates harmless variations: whitespace around
the dates, a trailing newline, a UTF-8 BOM, and a single date meaning a
one-day holiday; an empty file means no holiday. Anything else (garbage, a
bad date, more than two dates, an end date before the start date) makes
`main.py` print the file's path and how to fix it (delete the file, or re-run
`holiday_override.py`) and exit 2 without clocking, so cron mails it. It never
deletes an unparseable file itself.

### Marking Business Trips

A business trip isn't a day off - your normal ePortem check-ins, lunch break,
etc. still run exactly as usual (same schedule and location as any other
day; the crontab-based trigger doesn't adjust for the destination's local
time). What changes is your Slack status: instead of the usual "Working at
X" / "Away for lunch" / "Done for the day" per action, it stays "On a
business trip" for the whole trip - including at end of day, so it doesn't
flip back to "Done for the day" or go offline between clock-outs.

```bash
# Single day
python3 override_location.py business-trip 2026-08-20

# Date range (inclusive)
python3 override_location.py business-trip 2026-08-20 2026-08-22
```

Only takes effect if `SLACK_STATUS=YES`; the status uses `:airplane:` and
expires at end-of-day on the range's last date, same as holidays. To cancel
early, delete the `business_trip_override.txt` file. Once every date in the file has passed, the next run that reads it deletes it
automatically.

### Running Actions Directly

You can invoke any action directly using `eportem_action.py` without relying on the config file or the main runner script. This is useful for manual runs, debugging, or scripting. It records a real clock event, over HTTP or the browser as `EPORTEM_HTTP` says, but it skips `main.py`'s schedule, holiday and location-override checks. Run these with `venv/bin/python3`.

```bash
venv/bin/python3 eportem_action.py ACTION --location LOCATION
```

Where `ACTION` is one of:
- `start_day`
- `lunch_break`
- `after_lunch`
- `stop_day`

And `LOCATION` is either `office` or `home` (default is `office`).

**Examples:**
```bash
venv/bin/python3 eportem_action.py start_day --location office
venv/bin/python3 eportem_action.py lunch_break --location home
venv/bin/python3 eportem_action.py stop_day
```

There's also a thin CLI wrapper per action - `start_day.py`, `lunch_break_unified.py`, `after_lunch.py`, `stop_day.py` - each accepting just `--location`:

```bash
venv/bin/python3 start_day.py --location home
```

### macOS launchers

`command/*.command` are double-click launchers for macOS, one per action
(`00-start_the_day`, `01-lunch_break`, `02-after_lunch_break`, `03-stop_the_day`,
plus `04-start_the_day_home` and `05-after_lunch_break_home`). Each changes to
the repository root and runs the matching wrapper script with `venv/bin/python3`
(or `.venv/bin/python3`), or says so if neither exists. Like the scripts above
they record a real clock event and skip `main.py`'s checks.

## Automation

Run `run.sh` from cron. Each line fires a few minutes early and sleeps a random time, so the recorded timestamps don't look robotic. Copy-pasteable example for the schedule in `config/config.json` (all four actions, Monday to Friday):

```
SHELL=/bin/bash
55 08 * * 1-5 sleep $[RANDOM\%10]m ; /full_path/run.sh
25 13 * * 1-5 sleep $[RANDOM\%10]m ; /full_path/run.sh
25 14 * * 1-5 sleep $[RANDOM\%10]m ; /full_path/run.sh
55 17 * * 1-5 sleep $[RANDOM\%10]m ; /full_path/run.sh
```

To get told when an action was missed, add a day check after the last action (no random sleep, so no `\%` here):

```
40 18 * * 1-5 /full_path/run.sh --verify-day
```

It alerts on Telegram/Slack (if enabled) and exits 4, which cron mails. Use the weekdays of your schedule.

Things that have to be right:
- `SHELL=/bin/bash` at the top. `$RANDOM` and `$[ ]` are bash features, and cron runs lines with `/bin/sh` (dash on Debian), where the `sleep` fails and the script runs immediately with no random delay.
- `%` must be written `\%` in a crontab line; an unescaped one is turned into a newline.
- `RANDOM%10` gives 0 to 9 minutes of sleep, so the first line starts between 08:55 and 09:04, the lunch lines at 13:25-13:34 and 14:25-14:34, and the last at 17:55-18:04.
- Each line's `base time + max random sleep` must land inside the ±15 minute window of its `config/config.json` entry. The rule used here: base time = target - 5 minutes, sleep `RANDOM%10`.
- The weekdays on each line must match the days in `config/config.json`.

A run that matches no scheduled action is not silent: if today has a schedule but the current time is outside every window, `main.py` prints the current time and today's targets with their windows, says the crontab entry's time is probably outside the window, and exits 3, so cron mails it. Run `./run.sh --check` at any time to see what would run now.

### When a button is missing

This describes the browser (Selenium) path; the HTTP path has its own handling, see [Clocking without the browser](#clocking-without-the-browser-eportem_http). An action waits up to 30 seconds for its first button. If it doesn't appear, for example during an ePortem 500 outage, the run reopens the registro page every minute for up to 10 minutes, logging in again if the session was lost; a failed login is tried 3 times, and one run never submits the login form more than 4 times in total, so a rejected login can't hammer the account. A login that ePortem rejects is reported as such (`Login rejected by reCAPTCHA`, or `Login did not leave the login page ... check the credentials`). Nothing has been clicked at that point, so this can't record anything twice, but the recorded time can be up to about 10 minutes late. If the button is still missing, the run prints the URL and page title, saves the HTML and a screenshot to `diagnostics/` (git-ignored), and fails, which sends the cron mail. The saved files are readable only by you, anti-forgery tokens are removed from the HTML, and only the newest 20 files are kept.

If the page doesn't offer the action, the run doesn't retry. For example, `after_lunch` finds nothing to resume when `lunch_break` failed. Opening the dropdown records nothing, so the run prints what ePortem shows, saves diagnostics and fails with the cron mail; correct the day in Detalle registro.

`start_day` at the office is a single click on the main button. If that button shows the day is already running (`Pausar` or `Reanudar`), the run doesn't click it: it says the day is already started, records nothing, sends no notification and fails with the cron mail.

## Testing

To run the tests, use the `run_tests.sh` script in the root directory:

```bash
./run_tests.sh
```

It runs from any directory, uses `venv/bin/python3` (or `.venv/bin/python3`), runs every test found by `unittest discover` in `tests/`, and passes extra arguments to unittest (`./run_tests.sh -v`, or a module such as `tests.test_main`).

For development, `make check` runs the linter and the same tests under pytest with coverage, from a Python 3.13 `.venv` (see "Checks" under Development).

Tests cover `main.py`'s scheduling/holiday logic, `--verify-day`, failure alerts, the kill switch and the timestamped output, `eportem_action.py`'s
click flow, HTTP/browser choice and fallback, and Slack status handling,
`utility/http_clock.py`'s button selection, session cookies and outcome
checks, and the `override_location.py` / `holiday_override.py` CLIs - all
against a mocked Selenium driver and HTTP session
(`unittest.mock.MagicMock`; the override-file tests use a temporary state directory, selected with the `EPORTEM_STATE_DIR` environment variable), with no real ePortem, Telegram, or Slack calls
made during a test run. The full run takes under a second: the waits between
clicks are patched out. The tests also switch `EPORTEM_HTTP` off and empty the
notification credentials, so they can't send anything even on a host whose
`config/.env` has them set.

## Configuration

The schedule is in `config/config.json`:

```json
{
  "schedule": {
    "0": {
      "day": "Monday",
      "location": "office",
      "start_the_day": "9:00",
      "lunch_break": "13:30",
      "after_lunch_break": "14:30",
      "stop_the_day": "18:00"
    }
  }
}
```

- The keys under `schedule` are weekdays, `"0"` = Monday to `"6"` = Sunday.
- `day` is an optional label (any string); `location` is optional, `home` or `office`, the default for days without an override (office if left out).
- The only task keys are `start_the_day`, `lunch_break`, `after_lunch_break` and `stop_the_day`, each a time like `9:00` or `13:30`. Leave one out to skip that action.
- An action runs when the current time is within 15 minutes of its time (`WINDOW_MINUTES` in `main.py`); if two windows overlap, the first one in the file wins.
- A weekday with no entry (e.g. the weekend) is a normal quiet run: "No schedule for today.", exit 0.

The whole file is validated on every run, not just today's entry. Every problem found is printed with its location in the file (e.g. `schedule["2"]["lunch_break"]: must be a time like "9:00"...`) and the run exits 2 without clocking, so a typo shows up in the next cron mail instead of waiting for that task's time. A missing file or missing `schedule` key is treated the same way. Check by hand with `./run.sh --check`.

## Running the service with Docker

The multi-user service runs as one container: web UI, API, scheduler, health
checks and metrics on one port, data in one volume. It needs nothing else
(SQLite by default; Postgres through `CHECKIN_DATABASE_URL` for more than one
replica).

```bash
cp .env.example .env
docker compose build
# put the output in CHECKIN_SECRET_KEY in .env, and keep a copy somewhere safe
docker compose run --rm checkin python -m checkin config new-key
docker compose up -d
docker compose exec checkin python -m checkin create-admin YOUR_NAME
```

Then open `http://127.0.0.1:8080`, sign in, and work through the setup
checklist: ePortem account (verify it; it logs in and never clocks), working-day
template, home days, notifications.

- **HTTPS and a hostname:** put any reverse proxy in front (Caddy, Traefik,
  nginx, nginx-proxy-manager...) pointing at port 8080, set `CHECKIN_PUBLIC_URL`
  to its address (e.g. `https://checkin.example.com`) and `CHECKIN_TRUSTED_PROXIES`
  to the proxy's address. `CHECKIN_PUBLISH` controls where Compose publishes the
  port (default: `127.0.0.1:8080`, local only).
- **Monitoring:** `/healthz` (process up), `/readyz` (database and scheduler),
  `/metrics` (Prometheus, with `CHECKIN_METRICS_TOKEN`), error reports to Sentry or
  GlitchTip (`CHECKIN_SENTRY_DSN`), and a dead-man switch (`CHECKIN_HEARTBEAT_URL`,
  pinged every minute while the scheduler is healthy).
- **Backups:** `docker compose exec checkin python -m checkin backup` copies the
  database to `/data/backups/` (newest 7 kept). Back up that folder and your
  `CHECKIN_SECRET_KEY`; without the key the stored ePortem passwords can't be read.
  To restore, stop the service and put a backup back as `/data/checkin.db`. (Installs from before the rename keep
  using `/data/eportem.db` while no `checkin.db` exists; old `EPORTEM_*` settings
  still work and log a warning naming the new one.)
- **Upgrades:** `git pull && docker compose build && docker compose up -d`; the
  database is migrated on start.
- **Sizing:** the image is about 1.4 GB (it includes Chromium). Chromium only
  starts to log in, one at a time by default (`CHECKIN_BROWSER_CONCURRENCY`).
  `docker-compose.yml` gives it 512 MB of shared memory and 1 GB in total.
- **Trying it without a real ePortem account:** `docker compose --profile dev up -d`
  also starts the fake ePortem (account `DEMO` / `demo-password`); set
  `CHECKIN_TARGET_URL=http://fake-eportem:8081` in `.env` and restart.

## AI agents (the CheckIn skill)

People with an account can let an AI agent (Claude Code, or any agent that uses
skills) read and change their CheckIn, and clock in or out now, by asking in their
own words. The skill is in `skill/checkin/` (`SKILL.md` and `scripts/checkin.py`,
standard library only, Python 3.9+); decision D-028 has the reasons.

- **Getting it:** only from the app, never from the public website. The API tokens
  page has a "For AI agents" box with a text to paste into the agent. It holds a
  personal install link (`/skill/<link>/install.sh`, signed, valid 24 hours) that
  installs the skill into `${CLAUDE_CONFIG_DIR:-~/.claude}/skills/checkin`, or
  another folder with `sh -s -- --dir DIR`, and a zip download. The skill updates
  itself from the app (`checkin.py update`, or a note at most once a day).
- **Signing in:** `checkin.py login` asks the app for a code (device flow) and
  prints a link; the person opens `/device`, checks the code, chooses read or
  read and write, and approves; `checkin.py login --wait` then gets the agent its
  own token (90 days, listed and revocable on the tokens page). No password is
  ever typed into the agent, and the token is kept in `~/.config/checkin/agent.json`
  (mode 600), never printed. `checkin.py logout` revokes it.
- **Using it:** `status` (today and the next run), `state` (what ePortem shows right
  now, read-only), `clock start_day|lunch_break|after_lunch|stop_day [--location
  home|office] --yes` (a real clock event, through the same runs as the schedule),
  and `get|post|put|patch|delete PATH [JSON] [key=value...]` for the rest of
  `/api/v1`.
- **API added for it:** `POST /api/v1/device/code`, `POST /api/v1/device/token`,
  `GET /api/v1/status`, `GET /api/v1/eportem/state`, `DELETE /api/v1/tokens/current`,
  `GET /api/v1/skill` and `/api/v1/skill/checkin.zip`.
- **In this repository:** link the skill into the checkout's own Claude Code skills
  to manage your account from here: `mkdir -p .claude/skills && ln -s
  ../../skill/checkin .claude/skills/checkin`, and put `{"app_url":
  "https://checkin.example.com"}` in `skill/checkin/defaults.json`. Both are gitignored.

## Service settings

The multi-user service (`docs/refactor/PLAN.md`) is configured only through these settings; nothing
install-specific is in the code or the image. Set them as environment variables,
or in a TOML file named by `CHECKIN_CONFIG_FILE` (keys in lower case, without the
prefix). Secrets can also be read from a file with `CHECKIN_<NAME>_FILE`.
`.env.example` lists them all. `python -m checkin migrate` creates the database, and `python -m checkin import-legacy --user NAME --dry-run` shows what moving this checkout's cron set-up into it would do (drop `--dry-run` to do it). `python -m checkin scheduler` runs the scheduler in the foreground (set `CHECKIN_DRY_RUN=true` to plan and log without sending anything). `python -m checkin serve` runs the web app, the JSON API (`/api/v1`, documented at `/api/docs`) and the scheduler together; create the first admin with `python -m checkin create-admin NAME` (or `CHECKIN_ADMIN_USERNAME`/`CHECKIN_ADMIN_PASSWORD`) and an API token with `python -m checkin create-token NAME --scopes read,write`. The web UI (English, Spanish and Catalan; see Languages below) shows this week and next, where one tap switches a day between home and office; the schedule (built-in templates such as European 9–18, Spanish 9–18 with lunch 14:30–15:30, short Friday, summer hours; or your own week), home days, public holidays by region and periods; a calendar for time off, business trips and one-off changes; notifications; history; your random offset; API tokens; and admin pages. Check the settings with `python -m checkin config check`,
and see what is in effect with `python -m checkin config show`. The table is
generated from `checkin/settings.py` by `python -m checkin config docs`.

<!-- settings-table:start -->
| Setting | Default | What it does |
|---|---|---|
| **Server** | | |
| `CHECKIN_PUBLIC_URL` |  | The address people use to reach this instance, e.g. https://checkin.example.com. Used in links and emails. Default: http://localhost:<port>. |
| `CHECKIN_HOST` | `0.0.0.0` | Address to listen on inside the container. |
| `CHECKIN_PORT` | `8080` | Port to listen on (web UI, API, admin, health, metrics). |
| `CHECKIN_TRUSTED_PROXIES` |  | Reverse proxies whose X-Forwarded-* headers are believed (comma-separated IPs or CIDRs). |
| `CHECKIN_SECURE_COOKIES` |  | Send cookies only over HTTPS. Default: on when the public URL is https. |
| `CHECKIN_ROOT_PATH` |  | Serve under a sub-path, e.g. /checkin, behind a proxy. |
| **Storage** | | |
| `CHECKIN_DATA_DIR` | `/data` | Where the database, backups and diagnostics live. |
| `CHECKIN_DATABASE_URL` |  | SQLAlchemy URL. Default: SQLite in the data dir. Postgres (postgresql+psycopg://...) is needed for more than one replica. |
| `CHECKIN_SECRET_KEY` |  | Required. Encrypts stored credentials and tokens (a Fernet key: `python -m checkin config new-key`). Losing it means everyone re-enters their credentials. Secret: also `_FILE`. |
| `CHECKIN_OLD_SECRET_KEYS` |  | Previous secret keys, still accepted for reading while rotating (comma-separated). Secret: also `_FILE`. |
| **Target site** | | |
| `CHECKIN_TARGET_URL` | `https://eportem.es` | The ePortem site to automate. Point it at the fake ePortem for trying things out. |
| `CHECKIN_BROWSER_USER_AGENT` |  | Override the browser's User-Agent. Default: a desktop Chrome matching the installed version. |
| `CHECKIN_CHROMIUM_PATH` |  | Chromium binary, if not on the PATH. |
| `CHECKIN_CHROMEDRIVER_PATH` |  | chromedriver binary, if not on the PATH. |
| `CHECKIN_BROWSER_CONCURRENCY` | `1` | Browser logins allowed at the same time. |
| `CHECKIN_HEADLESS` | `true` | Run the browser without a window. |
| `CHECKIN_BROWSER_SANDBOX` | `true` | Use Chromium's own sandbox. The Docker image turns it off (it can't start as a non-root user there; the container isolates it instead). |
| **Defaults for new users** | | |
| `CHECKIN_DEFAULT_TIMEZONE` | `Europe/Madrid` | Time zone for new users. |
| `CHECKIN_DEFAULT_LOCALE` | `es` | Language for new users: a code with a catalogue in checkin/locales (en, es, ca...). |
| `CHECKIN_DEFAULT_HOLIDAY_COUNTRY` | `ES` | Country for public holidays (ISO code); empty for none. |
| `CHECKIN_DEFAULT_HOLIDAY_REGION` |  | Region for public holidays, e.g. MD (Madrid), CT (Catalonia). |
| `CHECKIN_DEFAULT_TEMPLATE` | `european-9-18` | Working-day template for new users (a built-in key). |
| `CHECKIN_DEFAULT_JITTER_BEFORE_MINUTES` | `5` | Random offset for new users: start up to this many minutes before an action's time. The clock-in and clock-out never fall inside the working day: they go only before the start or after the stop, spread over before + after minutes. Each person changes their own in their profile. |
| `CHECKIN_DEFAULT_JITTER_AFTER_MINUTES` | `4` | Random offset for new users: start up to this many minutes after an action's time. |
| **Scheduling** | | |
| `CHECKIN_WINDOW_MINUTES` | `15` | An action may run this many minutes either side of its time, never later. Everyone's random offset must fit inside it. |
| `CHECKIN_VERIFY_AFTER_MINUTES` | `40` | The end-of-day check runs this long after a user's last action. |
| `CHECKIN_DRY_RUN` | `false` | Plan and log, but never send a clock action. |
| **Accounts** | | |
| `CHECKIN_REGISTRATION` | `closed` | Who can create an account: closed (admins only), invite, open. |
| `CHECKIN_REQUIRE_EMAIL_VERIFICATION` | `true` | New accounts must confirm their email. |
| `CHECKIN_ADMIN_USERNAME` |  | Creates this admin on first start, if no admin exists. |
| `CHECKIN_ADMIN_EMAIL` |  | Email of that first admin. |
| `CHECKIN_ADMIN_PASSWORD` |  | Password of that first admin. Secret: also `_FILE`. |
| **Email** | | |
| `CHECKIN_SMTP_HOST` |  | SMTP server for verification, password reset and alerts. Empty: no email. |
| `CHECKIN_SMTP_PORT` | `587` | SMTP port. |
| `CHECKIN_SMTP_SECURITY` | `starttls` | starttls, tls (implicit, usually port 465) or none. |
| `CHECKIN_SMTP_USERNAME` |  | SMTP login. |
| `CHECKIN_SMTP_PASSWORD` |  | SMTP password. Secret: also `_FILE`. |
| `CHECKIN_SMTP_FROM` |  | From address for the emails this instance sends. |
| **Observability** | | |
| `CHECKIN_LOG_LEVEL` | `INFO` | Log level. |
| `CHECKIN_LOG_FORMAT` | `json` | Log lines as JSON or plain text. |
| `CHECKIN_METRICS_TOKEN` |  | Bearer token required on /metrics. Empty: /metrics is off. Secret: also `_FILE`. |
| `CHECKIN_SENTRY_DSN` |  | Report errors to Sentry or GlitchTip. Empty: off. Secret: also `_FILE`. |
| `CHECKIN_SENTRY_ENVIRONMENT` | `production` | Environment name in error reports. |
| `CHECKIN_HEARTBEAT_URL` |  | POSTed to every minute while the scheduler is healthy (a GlitchTip heartbeat monitor, healthchecks.io...), so a dead instance gets noticed. |
| `CHECKIN_ADMIN_ALERT_CHANNEL` |  | Where admin alerts go, e.g. telegram:<chat id> or slack:<channel id>. |
<!-- settings-table:end -->

## Languages

The web UI speaks English, Spanish and Catalan. Each person picks theirs in their
profile (`CHECKIN_DEFAULT_LOCALE` for new users; before signing in, the browser's
language). The texts are one JSON catalogue per language in `checkin/locales/`
(D-029): keys are the English text, or a code such as `start_day` for the values the
service stores. To add a language, copy `en.json` to `<code>.json` (for example
`eu.json`), set `_language` to the language's own name and translate the values; it
then appears in the profile and is accepted everywhere. `make check` fails while any
catalogue misses a key or a `{placeholder}`, and while a page shows text that never
went through `t()`. The public website has the same three languages (see below).
Notifications, alerts, emails, API errors and the CLI are still English only.

## Public website

`website/` is a static site that presents CheckIn, in English, Spanish and Catalan: what it
does, how it works, terms of use, privacy and a legal notice. No public sign-up (early
access by email), no cookies, nothing loaded from other sites in the source. Copy
`website/site.env.example` to `website/site.env` (untracked: your name, contact email,
site address and host), then `python3 website/build.py` writes `website/dist/`, built
for Cloudflare Pages (extensionless links, a 404 page per language; `--example` builds
a preview with made-up values). Its pictures are drawings of
the product, never screenshots; `website/VISUALS.md` lists where each comes from
(the notes in the source are stripped from the built pages). The site presents the
skill for AI agents but never publishes it (D-028). To deploy to Cloudflare Pages
with a Pages-only token kept in the untracked `website/deploy.env`, isolated from any
other Cloudflare credentials on the machine: `website/deploy.sh` (`--check` only
checks the token). Details in `website/README.md`.

## Development

The clock engine is the `checkin.core` package. It reads no environment variables and no files: the site URL, the account's activity IDs, the credentials, where the session cookies are kept and how to start a browser are all arguments, and progress messages go through a `say` callable instead of `print`. The scripts below are adapters that fill it in from `config/.env` and the repository's files, so their behaviour and output are the same as before. The multi-user service (see `docs/refactor/PLAN.md`) uses the same engine; the scripts stay only until the cron path is removed (PLAN.md phase 8, step 6).

- `checkin/core/actions.py` - one clock action: HTTP first, browser click flow as the fallback, follow-ups that never fail a recorded action
- `checkin/core/clock_http.py` - the HTTP clock client; `clock_and_verify()` tells "nothing recorded" (safe to fall back) from "outcome unknown"
- `checkin/core/browser.py` - starts Chromium so it looks like a desktop browser, and fills in the login form
- `checkin/core/notify.py` - Telegram, Slack and the Slack status, with secrets scrubbed
- `checkin/core/schedule.py`, `overrides.py` - schedule validation and windows, holiday/location/business-trip parsing
- `checkin/core/target.py`, `activities.py`, `cookies.py` - the site URLs, the account's activity IDs, and the session stores (file or memory)

The scripts:

- `eportem_action.py` - `EPortemAction`: the core clock action configured from `config/.env` (`EPORTEM_HTTP`, notification and Slack settings, the business-trip file, `logs/`, `diagnostics/`)
- `main.py` - Scheduler entrypoint called by cron; decides which action (if any) to run based on the current time and `config/config.json`
- `start_day.py`, `lunch_break_unified.py`, `after_lunch.py`, `stop_day.py` - thin CLI wrappers, each pinning one action and delegating to `eportem_action.run_fixed_action()`
- `override_location.py` / `holiday_override.py` - write (atomically) the override files that `main.py`/`eportem_action.py` read, in the repository root (or `EPORTEM_STATE_DIR`); stdlib-only, so they run with plain `python3`
- `utility/` - shared helpers: state file locations (`paths.py`), env loading/checking, Selenium login, Telegram/Slack notifications, Slack status, the recorded-actions log (`action_log.py`), failure/day-check alerts (`alerts.py`), and the timestamp wrapper for output (`timestamps.py`)
- `utility/http_clock.py` - the core HTTP clock with this account's activity IDs and `config/.session_cookies.json`, plus a CLI for runs by hand
- `utility/capture_dashboard.py` - read-only diagnostic for the direct-HTTP work (see `docs/http-api-investigation.md`): logs in, saves the dashboard HTML, button markup, scripts, script hits, cookie names and a session check to `capture/` (gitignored) without clicking anything. Run with `venv/bin/python3 -m utility.capture_dashboard`

### The fake ePortem and the contract check

There is only one real ePortem account to test with, and it is in live use, so
development and tests run against a fake: `fake_eportem/` serves the login form,
the clock dashboard and the clock endpoint for several accounts, each with its
own activity IDs and clock state, and can inject faults (server errors, a
maintenance page, dropped connections before or after recording, slow answers,
expired sessions, reCAPTCHA rejections). Its button attributes come from real
captures; its layout is what the Selenium flow clicks. Run it on its own with
`python -m fake_eportem --account ALICE:secret` (local use only).

`tests/fake/` runs the engine against it over HTTP; `tests/browser/` drives a real
headless Chromium through the login form and every click path (it skips itself
when no browser can start).

`python -m checkin.contract --activity-ids 1,1293,2` checks that the real site
still has the structure the engine relies on: the login form's fields, the clock
box on the page a login lands on, the dashboard layout and its buttons. It is
read-only and never requests the clock URL, but it reuses and refreshes the saved
session (logging in with the browser only if it has expired), so don't run it
just before a scheduled clock run.

### Where the code lives

The public repository is <https://github.com/rhortal/eportem>, a mirror of the
maintainer's own Git server. Open issues and pull requests there.

### Checks

`make check` runs the linter (`ruff`), the test suite (`pytest`, with
coverage, and a floor of 85% for `checkin/`) and the portability test, from a `.venv` that `make venv` builds
with Python 3.13 and `requirements-dev.txt`. `make test-fast` skips the real-browser tests. The same checks, plus a build and smoke test of the
Docker image, are defined for Gitea Actions in `.gitea/workflows/check.yml` (they run once Actions are
enabled for the repository and a runner is registered).

The portability test (`tests/test_portability.py`) fails when a tracked file
has an email address outside the example domains, a private IP address, or a
URL whose host isn't on its allow-list. `docs/OPERATIONS.md`, `docs/HANDOFF.md`,
`TODO.md` and `docs/http-api-investigation.md` are skipped: they are the maintainer's notes
about their own host. To also catch names that are only personal to you (a
host name, a domain, your email), list them one per line in
`.portability-denylist` at the top of the repository. That file is
gitignored, so the names never get committed.

## Releases

Releases are annotated Git tags (`git tag -l -n9 'v*'` lists them with their notes; `git checkout v1.0.0` gets one back):

- `v2.0.0` (2026-11-24): the multi-user service (`checkin/`): its own scheduler, web UI and API, Docker. It replaced cron after its first clean live day. The cron scripts are still in the tree as the rollback until they are removed (`docs/refactor/PLAN.md`, phase 8, step 6).
- `v1.0.0` (2026-11-17): the cron scripts (`run.sh` → `main.py` → `eportem_action.py`), clocking over HTTP with the browser as the fallback, the last state before the refactor.

The version in `pyproject.toml` (also reported by the API and in error reports) matches the latest tag; change all three places together.

## Acknowledgements

- ChatGPT, Claude, Qwen, Gemma and Gemini
- XPath Helper Chrome extension
- The Selenium docs
- Lots and lots of patience

## About Me
I'm learning Python and exploring ways to automate daily tasks at work as a way to improve my Python skills.
