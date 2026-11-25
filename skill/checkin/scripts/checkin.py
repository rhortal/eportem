#!/usr/bin/env python3
"""CheckIn from an AI agent: sign in without a password, call the API, update
this skill. Standard library only (Python 3.9+).

    checkin.py login [--url URL] [--name NAME] [--read-only]   # prints a link and a code
    checkin.py login --wait                                     # waits for the person to approve
    checkin.py status | whoami | logout
    checkin.py state                                            # what ePortem shows right now
    checkin.py clock start_day --location home --yes            # a real clock event, now
    checkin.py get /calendar from=2026-12-01 days=14
    checkin.py post /days '{"kind": "time_off", "start_date": "2026-12-24"}'
    checkin.py put|patch|delete PATH [JSON]
    checkin.py version | update [--check]                       # updates come from the app

Output is JSON on stdout; problems go to stderr. Exit codes: 0 fine, 1 the
request failed, 2 bad usage, 3 not signed in (run `login`), 4 still waiting
for approval (run `login --wait` again).

The token is kept in ~/.config/checkin/agent.json (mode 600) and never printed.
CHECKIN_URL and CHECKIN_TOKEN override the saved ones (for scripts and CI).
"""
import argparse
import datetime
import hashlib
import io
import json
import os
import shutil
import socket
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

VERSION = "1.0.1"
SKILL_DIR = Path(__file__).resolve().parent.parent
UPDATE_CHECK_EVERY = datetime.timedelta(days=1)
# One `login --wait` or `clock` stays under the usual two-minute tool timeout.
WAIT_SECONDS = 100
CLOCK_WAIT_SECONDS = 100
ACTIONS = ("start_day", "lunch_break", "after_lunch", "stop_day")

EXIT_FAILED, EXIT_USAGE, EXIT_SIGNED_OUT, EXIT_WAITING = 1, 2, 3, 4


class Problem(Exception):
    def __init__(self, message, code=EXIT_FAILED):
        super().__init__(message)
        self.code = code


# --- files ------------------------------------------------------------------------------
def config_path():
    if os.environ.get("CHECKIN_CONFIG"):
        return Path(os.environ["CHECKIN_CONFIG"])
    base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "checkin" / "agent.json"


def load_config():
    try:
        return json.loads(config_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_config(cfg):
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)
    os.replace(tmp, path)


def defaults():
    """Written by the app that served this copy: {"app_url": ...}."""
    try:
        return json.loads((SKILL_DIR / "defaults.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


# --- HTTP ---------------------------------------------------------------------------------
def http(method, url, body=None, token=None, timeout=30):
    """(status, parsed JSON or text, raw bytes). Tests replace this."""
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Accept": "application/json", "User-Agent": f"checkin-skill/{VERSION}"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status, raw = response.status, response.read()
    except urllib.error.HTTPError as e:
        status, raw = e.code, e.read()
    except (urllib.error.URLError, socket.timeout, OSError) as e:
        raise Problem(f"can't reach {url}: {getattr(e, 'reason', e)}") from None
    try:
        parsed = json.loads(raw) if raw else None
    except ValueError:
        parsed = raw.decode("utf-8", "replace")
    return status, parsed, raw


def app_url(cfg, given=None):
    url = given or os.environ.get("CHECKIN_URL") or cfg.get("url") or defaults().get("app_url")
    if not url:
        raise Problem("no CheckIn address: run `login --url https://checkin.example.com`", EXIT_USAGE)
    return url.rstrip("/")


def api(method, path, body=None, cfg=None):
    cfg = load_config() if cfg is None else cfg
    token = os.environ.get("CHECKIN_TOKEN") or cfg.get("token")
    if not token:
        raise Problem("not signed in: run `login`", EXIT_SIGNED_OUT)
    path = path if path.startswith("/") else f"/{path}"
    path = path.removeprefix("/api/v1")
    status, parsed, _ = http(method, f"{app_url(cfg)}/api/v1{path}", body, token)
    if status == 401:
        raise Problem("the token is invalid, expired or revoked: run `login` again", EXIT_SIGNED_OUT)
    if status >= 400:
        detail = parsed.get("detail", parsed) if isinstance(parsed, dict) else parsed
        raise Problem(f"{method} {path} failed ({status}): {json.dumps(detail, ensure_ascii=False)}")
    return parsed


# --- commands ------------------------------------------------------------------------------
def default_client_name():
    agent = "Claude Code" if os.environ.get("CLAUDECODE") else "AI agent"
    return f"{agent} on {socket.gethostname().split('.')[0]}"[:60]


def cmd_login(args):
    cfg = load_config()
    if args.wait:
        return wait_for_approval(cfg, args.timeout)
    url = app_url(cfg, args.url)
    scopes = ["read"] if args.read_only else ["read", "write"]
    status, out, _ = http("POST", f"{url}/api/v1/device/code",
                          {"client_name": args.name or default_client_name(), "scopes": scopes})
    if status != 200 or not isinstance(out, dict) or "device_code" not in out:
        raise Problem(f"could not start signing in ({status}): {out}")
    cfg.update(url=url, pending={"device_code": out["device_code"], "interval": out.get("interval", 5),
                                 "expires": time.time() + out.get("expires_in", 600),
                                 "user_code": out["user_code"]})
    save_config(cfg)
    emit({"open_this_link": out["verification_uri_complete"], "code": out["user_code"],
          "expires_in_minutes": out.get("expires_in", 600) // 60,
          "next": "Ask the person to open the link, check the code and approve; then run `login --wait`."})
    return 0


def wait_for_approval(cfg, timeout):
    pending = cfg.get("pending")
    if not pending:
        raise Problem("no sign-in in progress: run `login` first", EXIT_USAGE)
    url, deadline = app_url(cfg), time.time() + timeout
    interval = pending.get("interval", 5)
    while True:
        if time.time() > pending["expires"]:
            cfg.pop("pending", None)
            save_config(cfg)
            raise Problem("the code expired before it was approved: run `login` again")
        status, out, _ = http("POST", f"{url}/api/v1/device/token", {"device_code": pending["device_code"]})
        error = out.get("error") if isinstance(out, dict) else None
        if status == 200 and isinstance(out, dict) and out.get("access_token"):
            cfg.pop("pending", None)
            cfg.update(token=out["access_token"], username=out.get("username"), scopes=out.get("scopes"),
                       expires_at=out.get("expires_at"), token_prefix=out.get("token_prefix"))
            save_config(cfg)
            emit({"signed_in_as": out.get("username"), "scopes": out.get("scopes"),
                  "token_expires_at": out.get("expires_at")})
            return 0
        if error == "slow_down":
            interval += 5
        elif error != "authorization_pending":
            cfg.pop("pending", None)
            save_config(cfg)
            raise Problem(f"sign-in failed: {error or status}: {out}")
        if time.time() + interval > deadline:
            emit({"waiting": True, "code": pending["user_code"],
                  "next": "Not approved yet. Run `login --wait` again once the person has approved."})
            return EXIT_WAITING
        time.sleep(interval)


def cmd_logout(args):
    cfg = load_config()
    if cfg.get("token"):
        try:
            api("DELETE", "/tokens/current", cfg=cfg)
        except Problem as e:
            print(f"note: {e}", file=sys.stderr)
    for key in ("token", "username", "scopes", "expires_at", "token_prefix", "pending"):
        cfg.pop(key, None)
    save_config(cfg)
    emit({"signed_out": True})
    return 0


def parse_query(pairs):
    for pair in pairs:
        if "=" not in pair:
            raise Problem(f"query values look like key=value, not {pair!r}", EXIT_USAGE)
    return urllib.parse.urlencode([tuple(p.split("=", 1)) for p in pairs])


def cmd_request(args):
    method = args.command.upper()
    path, rest = args.path, list(args.rest)
    body = None
    if method in ("POST", "PUT", "PATCH") and rest and not _looks_like_query(rest[0]):
        text = rest.pop(0)
        text = sys.stdin.read() if text == "-" else text
        try:
            body = json.loads(text)
        except ValueError as e:
            raise Problem(f"the body is not valid JSON: {e}", EXIT_USAGE) from None
    elif method in ("POST", "PUT", "PATCH"):
        body = {}
    if rest:
        path += ("&" if "?" in path else "?") + parse_query(rest)
    emit(api(method, path, body))
    return 0


def _looks_like_query(text):
    return "=" in text and not text.lstrip().startswith(("{", "["))


def cmd_status(args):
    emit(api("GET", "/status"))
    return 0


def cmd_state(args):
    emit(api("GET", "/eportem/state"))
    return 0


def cmd_clock(args):
    """Clock now, outside the schedule, and wait for ePortem's answer."""
    if not args.yes:
        raise Problem(f"`clock {args.action}` records a real clock event in ePortem. Confirm the action and "
                      "location with the person, then run it again with --yes.", EXIT_USAGE)
    body = {"confirm": True}
    if args.location:
        body["location"] = args.location
    started = api("POST", f"/actions/{args.action}", body)
    run_id, deadline = started["run_id"], time.time() + args.timeout
    while True:
        out = api("GET", f"/runs/{run_id}/log")
        if out["run"]["status"] not in ("planned", "running") or time.time() > deadline:
            break
        time.sleep(3)
    run = out["run"]
    done = run["status"] not in ("planned", "running")
    emit({"run_id": run_id, "action": run["action"], "location": run["location"], "status": run["status"],
          "recorded": run["status"] == "recorded", "error": run.get("error"),
          "log": out.get("text", "")[-2000:] if done and run["status"] != "recorded" else None,
          "next": None if done else f"Still {run['status']}: check later with `get /runs/{run_id}/log`."})
    return 0 if run["status"] in ("recorded", "planned", "running") else EXIT_FAILED


def cmd_whoami(args):
    cfg = load_config()
    emit({"url": cfg.get("url") or defaults().get("app_url"), "signed_in": bool(cfg.get("token")),
          "username": cfg.get("username"), "scopes": cfg.get("scopes"), "token_expires_at": cfg.get("expires_at"),
          "skill_version": VERSION})
    return 0


# --- updates --------------------------------------------------------------------------------
# The skill is only for people with an account, so it comes from the app, with
# this agent's token: GET /api/v1/skill (version, sha256), /api/v1/skill/checkin.zip.
def version_tuple(text):
    try:
        return tuple(int(x) for x in str(text).split("."))
    except ValueError:
        return (0,)


def latest(cfg=None):
    out = api("GET", "/skill", cfg=cfg)
    if not isinstance(out, dict) or "version" not in out:
        raise Problem("could not read the latest version")
    return out


def cmd_version(args):
    emit({"version": VERSION, "installed_at": str(SKILL_DIR)})
    return 0


def cmd_update(args):
    cfg = load_config()
    info = latest(cfg)
    newer = version_tuple(info["version"]) > version_tuple(VERSION)
    if args.check or not newer:
        emit({"installed": VERSION, "latest": info["version"], "update_available": newer})
        return 0
    status, _, raw = http("GET", f"{app_url(cfg)}/api/v1/skill/checkin.zip",
                          token=os.environ.get("CHECKIN_TOKEN") or cfg.get("token"), timeout=60)
    if status != 200:
        raise Problem(f"download failed ({status})")
    if hashlib.sha256(raw).hexdigest() != info.get("sha256"):
        raise Problem("the download doesn't match its checksum; nothing was changed")
    install_zip(raw, SKILL_DIR)
    emit({"updated_from": VERSION, "updated_to": info["version"], "installed_at": str(SKILL_DIR)})
    return 0


def install_zip(raw, target):
    """Replace `target` with the zip's `checkin/` folder, keeping the old copy
    until the new one is in place."""
    target = Path(target)
    work = Path(tempfile.mkdtemp(prefix=".checkin-update-", dir=target.parent))
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            for member in z.namelist():
                dest = (work / member).resolve()
                if not str(dest).startswith(str(work.resolve()) + os.sep):
                    raise Problem(f"unsafe path in the download: {member}")
            z.extractall(work)
        new = work / "checkin"
        if not (new / "SKILL.md").is_file():
            raise Problem("the download has no checkin/SKILL.md")
        old = target.with_name(target.name + ".old")
        shutil.rmtree(old, ignore_errors=True)
        if target.exists():
            target.rename(old)
        new.rename(target)
        shutil.rmtree(old, ignore_errors=True)
    finally:
        shutil.rmtree(work, ignore_errors=True)


def maybe_note_update():
    """At most once a day, a note on stderr when a newer skill is out."""
    cfg = load_config()
    if os.environ.get("CHECKIN_NO_UPDATE_CHECK") or not (os.environ.get("CHECKIN_TOKEN") or cfg.get("token")):
        return
    now = datetime.datetime.now(datetime.timezone.utc)
    try:
        last = datetime.datetime.fromisoformat(cfg.get("update_checked_at", ""))
    except ValueError:
        last = None
    if last and now - last < UPDATE_CHECK_EVERY:
        found = cfg.get("update_latest")
    else:
        try:
            found = latest(cfg)["version"]
        except Problem:
            return
        cfg.update(update_checked_at=now.isoformat(), update_latest=found)
        save_config(cfg)
    if found and version_tuple(found) > version_tuple(VERSION):
        print(f"note: CheckIn skill {found} is available (this is {VERSION}); run `update`.", file=sys.stderr)


# --- main -------------------------------------------------------------------------------------
def emit(value):
    print(json.dumps(value, indent=2, ensure_ascii=False))


def parser():
    p = argparse.ArgumentParser(prog="checkin.py", description="CheckIn from an AI agent.")
    sub = p.add_subparsers(dest="command", required=True)
    login = sub.add_parser("login", help="sign in: prints a link and a code for the person to approve")
    login.add_argument("--url", help="the CheckIn app's address (default: the one this skill came with)")
    login.add_argument("--name", help="how the agent is shown on the approval page")
    login.add_argument("--read-only", action="store_true", help="ask only to read")
    login.add_argument("--wait", action="store_true", help="wait for the approval started by `login`")
    login.add_argument("--timeout", type=int, default=WAIT_SECONDS, help=argparse.SUPPRESS)
    login.set_defaults(func=cmd_login)
    for name, func, text in (("logout", cmd_logout, "revoke this agent's token and forget it"),
                             ("status", cmd_status, "today's plan and runs, the next run, setup"),
                             ("state", cmd_state, "what ePortem shows right now (reads, never clocks)"),
                             ("whoami", cmd_whoami, "where and as whom this agent is signed in"),
                             ("version", cmd_version, "this skill's version")):
        sub.add_parser(name, help=text).set_defaults(func=func)
    clock = sub.add_parser("clock", help="clock an action now (a real event in ePortem)")
    clock.add_argument("action", choices=ACTIONS)
    clock.add_argument("--location", choices=("home", "office"), help="default: the day's planned location")
    clock.add_argument("--yes", action="store_true", help="the person has confirmed this clock event")
    clock.add_argument("--timeout", type=int, default=CLOCK_WAIT_SECONDS, help=argparse.SUPPRESS)
    clock.set_defaults(func=cmd_clock)
    update = sub.add_parser("update", help="install the newest skill from the CheckIn app")
    update.add_argument("--check", action="store_true", help="only say whether there is one")
    update.set_defaults(func=cmd_update)
    for method in ("get", "post", "put", "patch", "delete"):
        r = sub.add_parser(method, help=f"{method.upper()} /api/v1PATH")
        r.add_argument("path")
        r.add_argument("rest", nargs="*", help="a JSON body (or - for stdin), then key=value query values")
        r.set_defaults(func=cmd_request)
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        code = args.func(args)
    except Problem as e:
        print(f"error: {e}", file=sys.stderr)
        return e.code
    if args.command not in ("update", "version", "login"):
        maybe_note_update()
    return code


if __name__ == "__main__":
    sys.exit(main())
