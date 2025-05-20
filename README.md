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
python3 run_mock_server.py

# Run all tests using the mock server
python3 test_with_mock.py

# Test a specific action using the mock server
python3 test_with_mock.py --action start_day --location office
```

The mock server runs on http://localhost:5000 and provides simulated ePortem interfaces for testing.

## Configuration

The schedule for each day is configured in the `config/config.json` file, located in the `config` directory. The location (home or office) can also be configured in this file.

## Development

The codebase follows DRY (Don't Repeat Yourself) principles with unified components:

- `eportem_action.py` - Core action handler for all operations
- `start_day.py`, `lunch_break_unified.py`, etc. - Simplified action scripts
- `mock_server/` - Testing environment that simulates ePortem

To switch between real ePortem and the mock server, set the environment variable:

```bash
# Use the mock server
export USE_MOCK_SERVER=YES

# Use the real ePortem service (default)
export USE_MOCK_SERVER=NO
```

## Acknowledgements

- ChatGPT 3.5 and Gemini 2.0 Flash
- XPath Helper Chrome extension
- The Selenium docs
- Flask for the mock server
- Patience

## About Me
I'm learning Python and exploring ways to automate daily tasks at work as a way to improve my Python skills.