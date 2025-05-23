import os
import threading
import time
from datetime import datetime
from flask import Flask, render_template, request, jsonify, send_from_directory
from dotenv import load_dotenv
import json

# Load environment variables from config/.env if present
load_dotenv(os.path.join(os.path.dirname(__file__), '..', 'config', '.env'))

app = Flask(
    __name__,
    template_folder=os.path.join(os.path.dirname(__file__), 'templates'),
    static_folder=os.path.join(os.path.dirname(__file__), 'static')
)

# Configurable port
PORT = int(os.getenv("WEB_UI_PORT", 8010))

WEB_UI_CONFIG_PATH = os.path.join(os.path.dirname(__file__), 'web_ui_config.json')

def save_state():
    try:
        with open(WEB_UI_CONFIG_PATH, 'w') as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        print(f"Could not save web UI config: {e}")

def load_state():
    print(f"Checking for persistent web UI config at: {WEB_UI_CONFIG_PATH}")
    if os.path.exists(WEB_UI_CONFIG_PATH):
        try:
            with open(WEB_UI_CONFIG_PATH, 'r') as f:
                loaded = json.load(f)
            print(f"Loaded state from web_ui_config.json: {loaded}")
            return loaded
        except Exception as e:
            print(f"Could not load web UI config: {e}")
    else:
        print("No web_ui_config.json found, will try to load from config/config.json")
    return None

def load_schedule_from_config():
    config_path = os.path.join(os.path.dirname(__file__), '..', 'config', 'config.json')
    print(f"Attempting to load schedule from config: {config_path}")
    try:
        with open(config_path, 'r') as f:
            config = json.load(f)
        schedule_cfg = config.get("schedule", {})
        schedule = []
        id_counter = 1
        for day_idx, day_info in schedule_cfg.items():
            day = day_info.get("day", "")
            location = day_info.get("location", "office")
            for action_key, action_time in day_info.items():
                if action_key in ["start_the_day", "lunch_break", "after_lunch_break", "stop_the_day"]:
                    action_map = {
                        "start_the_day": "start_day",
                        "lunch_break": "lunch_break",
                        "after_lunch_break": "after_lunch",
                        "stop_the_day": "stop_day"
                    }
                    schedule.append({
                        "id": id_counter,
                        "time": action_time,
                        "action": action_map[action_key],
                        "enabled": True,
                        "day": day,
                        "location": location
                    })
                    id_counter += 1
        print(f"Loaded schedule from config.json: {schedule}")
        return schedule, id_counter
    except Exception as e:
        print(f"Could not load schedule from config: {e}")
        return [], 1

# Load persistent state if present, otherwise initialize
loaded_state = load_state()
if loaded_state:
    print("Initializing state from web_ui_config.json")
    state = loaded_state
    _next_id = max([row["id"] for row in state.get("schedule", [])], default=0) + 1
else:
    print("Initializing state from config/config.json or default schedule")
    schedule_init, _next_id = load_schedule_from_config()
    state = {
        "updates_enabled": True,
        "location": "home",  # or "office"
        "telegram_enabled": True,
        "slack_enabled": True,
        "slack_status_enabled": True,
        "schedule": schedule_init if schedule_init else [
            {"id": 1, "time": "09:00", "action": "start_day", "enabled": True},
            {"id": 2, "time": "12:00", "action": "lunch_break", "enabled": True},
            {"id": 3, "time": "13:00", "action": "after_lunch", "enabled": True},
            {"id": 4, "time": "18:00", "action": "stop_day", "enabled": True},
        ]
    }
    print(f"Initialized state: {state}")

@app.route("/")
def index():
    # Pass config error status and year to template
    return render_template("index.html", config_error=CONFIG_ERROR, page_title="ePortem Web UI", year=datetime.datetime.now().year)

@app.route("/settings")
def settings():
   # Render a dedicated settings page, reusing schema/config error
   return render_template("settings.html", config_error=CONFIG_ERROR, page_title="Settings", year=datetime.datetime.now().year)

@app.route("/api/state", methods=["GET"])
def get_state():
    print(f"API /api/state returning schedule: {state.get('schedule')}")
    # Also return config error status to UI
    return jsonify({**state, "config_error": CONFIG_ERROR})

@app.route("/api/toggle", methods=["POST"])
def toggle():
    data = request.json
    key = data.get("key")
    value = data.get("value")
    if key in state:
        state[key] = value
        save_state()
        return jsonify({"success": True, "state": state})
    return jsonify({"success": False, "error": "Invalid key"}), 400

@app.route("/api/schedule", methods=["GET"])
def get_schedule():
    print(f"API /api/schedule returning: {state.get('schedule')}")
    return jsonify(state["schedule"])

@app.route("/api/schedule/toggle", methods=["POST"])
def toggle_schedule_row():
    row_id = request.json.get("id")
    for row in state["schedule"]:
        if row["id"] == row_id:
            row["enabled"] = not row["enabled"]
            save_state()
            return jsonify({"success": True, "row": row})
    return jsonify({"success": False, "error": "Row not found"}), 404

@app.route("/api/schedule/add", methods=["POST"])
def add_schedule_row():
    global _next_id
    time_val = request.json.get("time")
    action = request.json.get("action")
    days = request.json.get("days")
    location = request.json.get("location", "office")
    if not time_val or not action or not days or not isinstance(days, list) or not days:
        return jsonify({"success": False, "error": "Missing time, action, or days"}), 400
    rows = []
    for day in days:
        row = {"id": _next_id, "time": time_val, "action": action, "enabled": True, "day": day, "location": location}
        state["schedule"].append(row)
        rows.append(row)
        _next_id += 1
    save_state()
    return jsonify({"success": True, "rows": rows})

@app.route("/api/schedule/remove", methods=["POST"])
def remove_schedule_row():
    row_id = request.json.get("id")
    before = len(state["schedule"])
    state["schedule"] = [row for row in state["schedule"] if row["id"] != row_id]
    after = len(state["schedule"])
    save_state()
    return jsonify({"success": before != after})

@app.route("/api/schedule/update_location", methods=["POST"])
def update_location():
    row_id = request.json.get("id")
    location = request.json.get("location")
    updated = False
    for row in state["schedule"]:
        if row["id"] == row_id:
            row["location"] = location
            updated = True
            break
    if updated:
        save_state()
        return jsonify({"success": True, "id": row_id, "location": location})
    return jsonify({"success": False, "error": "Row not found"}), 404

@app.route("/api/schedule/update_time", methods=["POST"])
def update_time():
    row_id = request.json.get("id")
    time_val = request.json.get("time")
    updated = False
    for row in state["schedule"]:
        if row["id"] == row_id:
            row["time"] = time_val
            updated = True
            break
    if updated:
        save_state()
        return jsonify({"success": True, "id": row_id, "time": time_val})
    return jsonify({"success": False, "error": "Row not found"}), 404

import subprocess
from flask import request, jsonify

import pathlib

# Track status for UI
state["_scheduler_status"] = {
    "upcoming_action": None,
    "last_action_result": None
}

def update_upcoming_action():
    # Find next enabled action after current time on any day (wrapping)
    from datetime import datetime, timedelta, time as dt_time

    def day_to_num(d):
        days = ["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday","Sunday"]
        try:
            return days.index(d)
        except Exception:
            return -1

    def to_time(tstr):
        # Normalize and parse times like "9:00" and "09:00"
        parts = tstr.strip().split(':')
        hour = int(parts[0])
        minute = int(parts[1]) if len(parts) > 1 else 0
        return dt_time(hour, minute)

    now = datetime.now()
    today_str = now.strftime("%A")
    now_time = now.time()
    schedule = state["schedule"]

    # Prepare all schedule entries by weekday number and time
    items = []
    for row in schedule:
        if not row.get("enabled"):
            continue
        row_day = row.get("day", today_str)
        day_num = day_to_num(row_day)
        norm_time = to_time(row.get("time", "00:00"))
        items.append({
            "day": row_day,
            "day_num": day_num,
            "time": norm_time,
            "action": row.get("action", ""),
            "row": row
        })

    result = None
    # Find earliest action for today, and for today after now
    todays = [it for it in items if it["day"] == today_str]
    if todays:
        todays_sorted = sorted(todays, key=lambda x: x["time"])
        # 1. If current time is before earliest scheduled action, pick the earliest
        if now_time < todays_sorted[0]["time"]:
            result = todays_sorted[0]
        else:
            # 2. Otherwise, pick first after now
            after = [x for x in todays_sorted if x["time"] > now_time]
            if after:
                result = after[0]
    # 3. If not today or no more today, look to future
    if not result:
        for i in range(1, 8):  # next 7 days
            check_date = now + timedelta(days=i)
            check_day_str = check_date.strftime("%A")
            future = [it for it in items if it["day"] == check_day_str]
            if future:
                result = sorted(future, key=lambda x: x["time"])[0]
                break

    # Debug output
    print(f"[SchedulerStatus] Now: {now_time} Today: {today_str}")
    actions_times = [f"{x['action']}@{x['time']}" for x in todays]
    print(f"[SchedulerStatus] Todays actions: {actions_times}")
    print(f"[SchedulerStatus] Selected result: {result}")

    if result:
        human_time = result["time"].strftime("%H:%M")
        state["_scheduler_status"]["upcoming_action"] = (
            f'{result["action"].replace("_"," ").capitalize()} at {human_time} ({result["day"]})'
        )
    else:
        state["_scheduler_status"]["upcoming_action"] = None

def run_eportem_action(action, location, telegram=None, slack=None, slack_status=None):
    # Call eportem_action.py as a subprocess for isolation
    import copy, os

    # Prepare environment overrides for notification toggles
    env = copy.deepcopy(os.environ)
    if telegram is not None:
        env["TELEGRAM_NOTIFY"] = "YES" if telegram else "NO"
    if slack is not None:
        env["SLACK_NOTIFY"] = "YES" if slack else "NO"
    if slack_status is not None:
        env["SLACK_STATUS"] = "YES" if slack_status else "NO"

    script_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'eportem_action.py'))
    try:
        result = subprocess.run(
            ["python3", script_path, action, "--location", location],
            capture_output=True, text=True, check=True, env=env
        )
        print(f"eportem_action output: {result.stdout}")
        state["_scheduler_status"]["last_action_result"] = (
            f'OK: {action} at {location} &mdash; '
            + (result.stdout.strip() or "No output")
        )
        return {"success": True, "result": result.stdout.strip()}
    except subprocess.CalledProcessError as e:
        print(f"Error running eportem_action: {e.stderr}")
        state["_scheduler_status"]["last_action_result"] = (
            f'FAILED: {action} at {location} &mdash; '
            + (e.stderr.strip() or "No error details")
        )
        return {"success": False, "error": e.stderr.strip()}

def scheduler_loop():
    while True:
        now = time.strftime("%H:%M")
        today_str = time.strftime("%A")
        update_upcoming_action()
        for row in state["schedule"]:
            if (
                row.get("enabled")
                and row.get("time", "") == now
                and state.get("updates_enabled")
                and ("day" not in row or row["day"] == today_str)
            ):
                run_eportem_action(row["action"], row.get("location", state.get("location", "office")))
        time.sleep(60)

@app.route("/api/trigger_now", methods=["POST"])
def trigger_now():
    data = request.json if request.is_json else request.form
    action = data.get("action")
    location = data.get("location")
    telegram = data.get("telegram")
    slack = data.get("slack")
    slack_status = data.get("slack_status")
    # Convert to bool if sent as string
    if isinstance(telegram, str):
        telegram = telegram.lower() in ("yes", "true", "1", "on")
    if isinstance(slack, str):
        slack = slack.lower() in ("yes", "true", "1", "on")
    if isinstance(slack_status, str):
        slack_status = slack_status.lower() in ("yes", "true", "1", "on")

    print(f"[Manual Trigger] Action={action} Location={location} Flags: telegram={telegram}, slack={slack}, slack_status={slack_status}")
    if not action or not location:
        return {"success": False, "error": "Missing parameters"}, 400
    return run_eportem_action(action, location, telegram=telegram, slack=slack, slack_status=slack_status)

@app.route("/api/scheduler_status", methods=["GET"])
def get_scheduler_status():
    # Always update before sending status to UI
    update_upcoming_action()
    out = state.get("_scheduler_status", {})
    return jsonify({
        "upcoming_action": out.get("upcoming_action") or None,
        "last_action_result": out.get("last_action_result") or None
    })

def start_scheduler():
    t = threading.Thread(target=scheduler_loop, daemon=True)
    t.start()

############################
# Settings (.env) Endpoints
############################

ENV_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'config', '.env'))

SETTING_SCHEMA = [
    {
        "key": "EPORTEM_USERNAME",
        "type": "text",
        "label": "ePortem Username",
        "description": "Your ePortem username for login.",
        "required": True,
    },
    {
        "key": "EPORTEM_PASSWORD",
        "type": "password",
        "label": "ePortem Password",
        "description": "Your ePortem password for login.",
        "required": True,
    },
    {
        "key": "TELEGRAM_BOT_TOKEN",
        "type": "text",
        "label": "Telegram Bot Token",
        "description": "Format: 000000000:AaAaAaAaAaAaAaAaAaAa... (numbers, colon, then mixed case letters/numbers)",
        "pattern": r"^\d{6,}:[A-Za-z0-9_]{35,}$",
        "required": False,
        "example": "1745486736:AAEAPhpBIlK9oVS1QEQkSyD0WSbHLRcu23M"
    },
    {
        "key": "TELEGRAM_CHAT_ID",
        "type": "text",
        "label": "Telegram Chat ID",
        "description": "Telegram chat ID (should be all digits, copy from your Telegram app).",
        "pattern": r"^\d+$",
        "required": False,
        "example": "123456789"
    },
    {
        "key": "TELEGRAM_NOTIFY",
        "type": "toggle",
        "label": "Enable Telegram Notifications",
        "description": "Send notifications via Telegram.",
        "required": True,
    },
    {
        "key": "SLACK_NOTIFY",
        "type": "toggle",
        "label": "Enable Slack Notifications",
        "description": "Send notifications via Slack webhooks.",
        "required": True,
    },
    {
        "key": "SLACK_WEBHOOK",
        "type": "text",
        "label": "Slack Token",
        "description": "Format: xoxb-... (bot) or xoxp-... (user), e.g. xoxp-000000000000-000000000000-000000000000-abcdefghijklmnopqrstuvwxyz012345",
        "pattern": r"^xox[bpar]-[0-9]+-[0-9]+-[0-9]+-[a-zA-Z0-9]+$",
        "required": False,
        "example": "xoxp-REDACTED-EXAMPLE-TOKEN"
    },
    {
        "key": "SLACK_STATUS",
        "type": "toggle",
        "label": "Update Slack Status",
        "description": "Change Slack status automatically when schedule events occur.",
        "required": True,
    },
    {
        "key": "HEADLESS_BROWSING",
        "type": "toggle",
        "label": "Use Headless Browsing",
        "description": "Run browser actions in headless mode.",
        "required": True,
    },
    {
        "key": "EPORTEM_ENABLED",
        "type": "toggle",
        "label": "Enable ePortem Automation",
        "description": "Main toggle to enable or disable all automation.",
        "required": True,
    },
    {
        "key": "WEB_UI_PORT",
        "type": "number",
        "label": "Web UI Port",
        "description": "Port for the web UI server.",
        "required": True,
        "min": 1025,
        "max": 65535,
        "example": "8010"
    },
    {
        "key": "USE_MOCK_SERVER",
        "type": "toggle",
        "label": "Use Mock Server (Developer Setting)",
        "description": "Send actions to a local mock server for testing.",
        "required": True
    }
]

def parse_env_file(env_path):
    values = {}
    try:
        with open(env_path, "r") as f:
            for line in f:
                s = line.strip()
                if not s or s.startswith("#") or "=" not in s:
                    continue
                k, v = s.split("=", 1)
                values[k.strip()] = v.strip()
    except Exception:
        pass
    return values

def write_env_file(new_values, env_path):
    # Compose new .env file with comments preserved where possible.
    orig_lines = []
    try:
        with open(env_path, "r") as f:
            orig_lines = f.readlines()
    except Exception:
        pass

    result_lines = []
    seen = set()
    # Update existing keys
    for line in orig_lines:
        s = line.strip()
        # Comments/empty lines untouched
        if not s or s.startswith("#") or "=" not in s:
            result_lines.append(line)
            continue
        k = s.split("=", 1)[0].strip()
        if k in new_values:
            result_lines.append(f"{k}={new_values[k]}\n")
            seen.add(k)
        else:
            result_lines.append(line)
    # Add any missing from new_values
    for k,v in new_values.items():
        if k not in seen:
            result_lines.append(f"{k}={v}\n")
    with open(env_path, "w") as f:
        f.writelines(result_lines)

@app.route("/api/env_schema", methods=["GET"])
def env_schema():
    env_vals = parse_env_file(ENV_PATH)
    schema = []
    for entry in SETTING_SCHEMA:
        current_val = env_vals.get(entry["key"])
        typ = entry["type"]
        if typ == "toggle":
            normalized = (current_val or "").upper()
            value = normalized == "YES"
        elif typ == "number":
            try:
                value = int(current_val)
            except Exception:
                value = ""
        else:
            value = current_val or ""
        with_info = entry.copy()
        with_info["value"] = value
        schema.append(with_info)
    return jsonify({"success": True, "schema": schema})

@app.route("/api/env", methods=["GET"])
def get_env_struct():
    # for backward UI-compat, get raw if "?raw=1"
    if request.args.get("raw"):
        try:
            with open(ENV_PATH, "r") as f:
                content = f.read()
            return jsonify({"success": True, "content": content})
        except Exception as e:
            return jsonify({"success": False, "error": str(e)}), 500
    # else JSON schema
    env_vals = parse_env_file(ENV_PATH)
    return jsonify({"success": True, "env": env_vals})

@app.route("/api/env", methods=["POST"])
def save_env_struct():
    data = request.json
    # Must be dict: {key1: val1, ...}
    incoming = data.get("env") if "env" in data else None
    if not incoming or not isinstance(incoming, dict):
        return jsonify({"success": False, "error": "No env dict provided!"}), 400

    err = []

    # Validate each input per schema
    to_save = {}
    for entry in SETTING_SCHEMA:
        k = entry["key"]
        typ = entry["type"]
        val = incoming.get(k)
        if typ == "toggle":
            real_val = "YES" if bool(val) else "NO"
        elif typ == "number":
            try:
                real_val = str(int(val))
                if "min" in entry and int(val) < entry["min"]:
                    err.append(f"{entry['label']}: must be >= {entry['min']}")
                if "max" in entry and int(val) > entry["max"]:
                    err.append(f"{entry['label']}: must be <= {entry['max']}")
            except Exception:
                err.append(f"{entry['label']}: must be a number")
                real_val = ""
        else:
            real_val = val if val is not None else ""
        # Required check
        if entry.get("required") and (real_val is None or real_val == "" or (typ=="toggle" and real_val not in ["YES","NO"])):
            err.append(f"{entry['label']}: is required")
        # Pattern validation
        pat = entry.get("pattern")
        if pat and real_val:
            if not re.match(pat, real_val):
                err.append(f"{entry['label']}: format invalid")
        to_save[k] = real_val

    if err:
        return jsonify({"success": False, "error": "; ".join(err)}), 400
    # Backup old .env
    backup_path = ENV_PATH + ".bak"
    if pathlib.Path(ENV_PATH).exists():
        with open(ENV_PATH, "r") as oldf:
            with open(backup_path, "w") as bak:
                bak.write(oldf.read())
    # Write new values
    try:
        write_env_file(to_save, ENV_PATH)
        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

import argparse
import sys
import signal
import datetime
import re

@app.route("/api/restart", methods=["POST"])
def restart_server():
    """
    Attempt to restart the web UI process.
    Only works if run in a way where signal or sys.exit will trigger a restart policy,
    for example under Docker or systemd with restart policy.
    """
    # Acknowledge immediately, then restart after short delay (to flush response)
    import threading
    def delayed_exit():
        import time as _t
        _t.sleep(1)
        print("[web_ui] Restart triggered from settings UI.")
        sys.exit(0)
    threading.Thread(target=delayed_exit, daemon=True).start()
    return jsonify({"success": True})

SERVER_START_TIME = datetime.datetime.now()

@app.route("/api/serverinfo", methods=["GET"])
def get_server_info():
    start_time = SERVER_START_TIME
    now = datetime.datetime.now()
    uptime = now - start_time
    days, rem = divmod(uptime.total_seconds(), 86400)
    hours, rem = divmod(rem, 3600)
    minutes, _ = divmod(rem, 60)
    return jsonify({
        "success": True,
        "start_time": start_time.isoformat(),
        "uptime_days": int(days),
        "uptime_hours": int(hours),
        "uptime_minutes": int(minutes)
    })

# Global variable to communicate config validity to UI
CONFIG_ERROR = None
MIN_REQUIRED_KEYS = [
    "EPORTEM_USERNAME",
    "EPORTEM_PASSWORD",
    "EPORTEM_ENABLED",
    "HEADLESS_BROWSING",
    "WEB_UI_PORT"
]

def validate_basic_config():
    # Check if .env file exists, and key fields are present/non-empty
    if not os.path.exists(ENV_PATH):
        return "Configuration file not found (.env missing)."
    vals = parse_env_file(ENV_PATH)
    missing = [k for k in MIN_REQUIRED_KEYS if not vals.get(k)]
    if missing:
        return f"Configuration incomplete. Missing required: {', '.join(missing)}"
    if vals.get("EPORTEM_ENABLED", "").upper() != "YES":
        return "EPORTEM_ENABLED is not set to YES."
    return None

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run ePortem Web UI server")
    parser.add_argument("--mock", action="store_true", help="Use the mock server for ePortem actions (sets USE_MOCK_SERVER=YES) for this session.")
    args = parser.parse_args()
    if args.mock:
        os.environ["USE_MOCK_SERVER"] = "YES"
        print("[web_ui] Running in MOCK SERVER mode: USE_MOCK_SERVER=YES")
    else:
        print("[web_ui] Running in normal (real) mode.")
    # Validate config
    CONFIG_ERROR = validate_basic_config()
    start_scheduler()
    app.run(host="0.0.0.0", port=PORT, debug=True)
