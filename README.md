# ePortem

Scripts that automate clocking in and out on ePortem: start of day, lunch break, return from lunch, and end of day - for both office and home working.

Optionally, it notifies you on Telegram and Slack, and can keep your Slack status in sync with what you're doing.

ePortem is a SaaS solution used in Spain for HR-related tasks. These scripts automate the functionality that enables people to track the time they spend at work every day, as required by Spanish law.

## Features

- Automated time tracking for office and remote work, triggered by cron
- Start of day, lunch break, return from lunch, and end of day actions
- Telegram and Slack notifications, plus live Slack status updates
- Per-day location override (home/office)
- Business trip mode: check-ins run as normal, but Slack status stays "On a business trip" for the whole trip
- Holiday mode: skips check-ins and notifications entirely for a date range, with a matching Slack status

## Deployment

To deploy this project, clone this repo and make sure you have the python3 binary in your PATH.

Make sure you have chromium-driver installed:
### On Ubuntu:
```shell
sudo apt install chromium-chromedriver
```
### On Debian:
```shell
sudo apt install chromium-driver
```
### On macOS
install Homebrew then do
```shell
brew install --cask chromedriver
```
Install requirements by running `./run.sh` in the root - it creates a `venv` and installs `requirements.txt` on first run.

The software takes configuration including ePortem, Telegram and Slack credentials from a `.env` file. To set this up:
- Copy `config/.env.template` to `config/.env`
- Open `.env` with your favourite editor (`nano config/.env` or `code config/.env`)
- Enter values for all variables as per comments in the file
- Set permissions so only you can read it: `chmod 600 config/.env`

### Slack notification credentials

Slack notifications and Slack status updates use two different Slack
features and need two different credentials, both read from `config/.env`:
- `SLACK_WEBHOOK_URL` — a full Incoming Webhook URL
  (`https://hooks.slack.com/services/...`), used when `SLACK_NOTIFY=YES`.
- `SLACK_TOKEN` — an OAuth user token (`xoxp-...`) with the
  `users.profile:write` scope, used when `SLACK_STATUS=YES`.

If one of them is missing, that feature is skipped (a webhook cannot set
your status, and a token is not a valid webhook URL).

## Usage

To run the script, use the `run.sh` script in the root directory:

```bash
./run.sh
```

`main.py` checks `config/config.json` for today's schedule and, if the
current time is within 15 minutes of a scheduled action, performs it. This
is what cron calls (see [Automation](#automation)) - it's not meant to be
run continuously.

### Overriding Location

Override the location for a single day using `override_location.py`:

```bash
python3 override_location.py home
python3 override_location.py office
```

This sets the location to `home`/`office` for the current day only - it's
read by `main.py` and used for both which ePortem buttons to click and the
Slack status text. To cancel, delete the `location_override.txt` file.

### Marking Holidays

If you're on holiday (not working at all), use `holiday_override.py` so
`main.py` skips ePortem check-ins and the normal start/lunch/stop Telegram
and Slack notifications entirely for those days:

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
time. To cancel early, delete the `holiday_override.txt` file.

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
early, delete the `business_trip_override.txt` file.

### Running Actions Directly

You can invoke any action directly using `eportem_action.py` without relying on the config file or the main runner script. This is useful for manual runs, debugging, or scripting.

```bash
python3 eportem_action.py ACTION --location LOCATION
```

Where `ACTION` is one of:
- `start_day`
- `lunch_break`
- `after_lunch`
- `stop_day`

And `LOCATION` is either `office` or `home` (default is `office`).

**Examples:**
```bash
python3 eportem_action.py start_day --location office
python3 eportem_action.py lunch_break --location home
python3 eportem_action.py stop_day
```

There's also a thin CLI wrapper per action - `start_day.py`, `lunch_break_unified.py`, `after_lunch.py`, `stop_day.py` - each accepting just `--location`:

```bash
python3 start_day.py --location home
```

## Automation

You can set these scripts to run automatically using Unix `cron`. You can also add a `sleep $[RANDOM%nn]m` command preceding the call so the command is called at a random time between 0 and nn minutes.
```
55 08 * * 1-4 sleep $[RANDOM%10]m ; /full_path/run.sh
25 13 * * 1-5 sleep $[RANDOM%10]m ; /full_path/run.sh
25 14 * * 1-4 sleep $[RANDOM%10]m ; /full_path/run.sh
10 18 * * 1-5 sleep $[RANDOM%25]m ; /full_path/run.sh
```

The above example checks in Monday to Thursday between 08:55 and 09:05, notifies of lunch starting 13:25-13:35 and returns 14:25-14:35, and finally calls the script to end the day daily between 18:10 and 18:35.

Each cron line's `base time + max random sleep` needs to land inside the
±15 minute window of the corresponding `config/config.json` entry, or that
action silently won't fire.

## Testing

To run the tests, use the `run_tests.sh` script in the root directory:

```bash
./run_tests.sh
```

Tests cover `main.py`'s scheduling/holiday logic, `eportem_action.py`'s
click flow and Slack status handling, and the `override_location.py` /
`holiday_override.py` CLIs - all against a mocked Selenium driver
(`unittest.mock.MagicMock`), with no real ePortem, Telegram, or Slack calls
made during a test run.

## Configuration

The schedule for each day is configured in the `config/config.json` file, located in the `config` directory. The location (home or office) can also be configured in this file, as a default for days without an override.

## Development

The codebase follows DRY (Don't Repeat Yourself) principles with unified components:

- `eportem_action.py` - Core action handler for all operations (Selenium click flow, notifications, Slack status)
- `main.py` - Scheduler entrypoint called by cron; decides which action (if any) to run based on the current time and `config/config.json`
- `start_day.py`, `lunch_break_unified.py`, `after_lunch.py`, `stop_day.py` - thin CLI wrappers, each pinning one action and delegating to `eportem_action.run_fixed_action()`
- `override_location.py` / `holiday_override.py` - write the override files that `main.py`/`eportem_action.py` read
- `utility/` - shared helpers: env loading/checking, Selenium login, Telegram/Slack notifications, Slack status

## Acknowledgements

- ChatGPT, Claude, Qwen, Gemma and Gemini
- XPath Helper Chrome extension
- The Selenium docs
- Lots and lots of patience

## About Me
I'm learning Python and exploring ways to automate daily tasks at work as a way to improve my Python skills.
