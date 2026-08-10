# ePortem

Scripts for ePortem. Automates start (office and home working versions), lunch, return and end of day.

Optionally, it notifies the user on Telegram and Slack.

ePortem is a SaaS solution used in Spain for HR-related tasks. These scripts automate the functionality that enables people to track the time they spend at work every day, as required by Spanish law.

## Features

- Automated time tracking for office and remote work
- Support for start of day, lunch break, and end of day actions
- Telegram and Slack notifications
- Location override system
- Mock server for testing without accessing the real ePortem service

## Deployment

To deploy this project, clone this repo and make sure you have the python3 binary in your PATH.

Make sure you have chromium-driver installed
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
Install requirements by running `./run.sh` in the root

The software takes configuration including ePortem and Telegram credentials from a .env file. To set this up:
- Copy config/.env.template to config/.env
- Open .env with your favourite editor (`nano config/.env` or `code config/.env`)
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

You can also override the location for a specific day using the `override_location.py` script:

```bash
python3 override_location.py home
```

This will set the location to `home` for the current day. To set it back to the default, simply delete the `location_override.txt` file.

### Marking Holidays and Business Trips

If you're on holiday, on a business trip, or otherwise out, use the `holiday_override.py` script so `main.py` skips ePortem check-ins entirely for those days:

```bash
# Single day, holiday (the default type)
python3 holiday_override.py 2026-08-17

# Date range (inclusive)
python3 holiday_override.py 2026-08-17 2026-08-21

# Business trip instead of a holiday
python3 holiday_override.py 2026-08-17 2026-08-21 --type business_trip
```

While the override is active, `main.py` skips every ePortem check-in and the
normal start/lunch/stop Telegram and Slack notifications. If `SLACK_STATUS=YES`
in your `.env`, it instead sets your Slack status to match, on every run:

| `--type`        | status text        | emoji         |
|------------------|---------------------|---------------|
| `holiday` (default) | On holiday       | `:palm_tree:` |
| `business_trip`  | On a business trip  | `:airplane:`  |

The status is set with an expiration of end-of-day on the range's last date,
so Slack clears it automatically once you're back - no separate cleanup
needed. Setting it repeatedly (once per cron run for the whole range) is
harmless, since it's just overwriting the same status each time.

To cancel early, delete the `holiday_override.txt` file.

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

You can also use the mock driver or mock server for testing:
```bash
python3 eportem_action.py start_day --location office --mock
python3 eportem_action.py lunch_break --use-mock-server
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

## Testing

To run the tests, use the `run_tests.sh` script in the root directory:

```bash
./run_tests.sh
```

### Mock Server for Testing

You can use the mock server for development and testing without needing to access the real ePortem service:

```bash
# Start the mock server
python3 utility/server.py

# Run all tests using the mock server
pytest tests/test_with_mock.py

# Test a specific action using the mock server
pytest tests/test_with_mock.py --action=start_day --location=office
```

The mock server runs on http://localhost:8000 and provides simulated ePortem interfaces for testing.

> **Important Security Note**: When using the mock server, your real ePortem credentials are never used. The system automatically uses test credentials (`test_user`/`test_password`) for all mock server interactions.

> **Status**: the mock server and mock driver are currently not maintained and known to be broken (wrong template path in `utility/server.py`, and the mock login form fields no longer match the real ePortem login form). `run_tests.sh` does not run anything that depends on them. Production use (`run.sh` / `main.py` / `eportem_action.py` against the real site) is unaffected.

## Configuration

The schedule for each day is configured in the `config/config.json` file, located in the `config` directory. The location (home or office) can also be configured in this file.

## Development

The codebase follows DRY (Don't Repeat Yourself) principles with unified components:

- `eportem_action.py` - Core action handler for all operations
- `start_day.py`, `lunch_break_unified.py`, `after_lunch.py`, `stop_day.py` - thin CLI wrappers, each pinning one action and delegating to `eportem_action.run_fixed_action()`
- `utility/server.py` - Testing environment that simulates ePortem (currently unmaintained, see Testing section)

To switch between real ePortem and the mock server, set the environment variable:

```bash
# Use the mock server
export USE_MOCK_SERVER=YES

# Specify a different port if 8000 is already in use
python3 utility/server.py --port 8888

# To pass additional options to the mock server
python3 utility/server.py --debug

# Use the real ePortem service (default)
export USE_MOCK_SERVER=NO
```

## Acknowledgements

- ChatGPT, Claude, Qwen, Gemma and Gemini
- XPath Helper Chrome extension
- The Selenium docs
- Flask
- Lots and lots of patience

## About Me
I'm learning Python and exploring ways to automate daily tasks at work as a way to improve my Python skills.