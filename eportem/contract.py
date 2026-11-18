"""Check that ePortem's pages still have the structure the clock engine relies on.

The same checks run against the fake ePortem in the tests, and against the real
site by hand (docs/refactor/PLAN.md, section 7):

    venv/bin/python -m eportem.contract --activity-ids 1,1293,2

The real run is read-only. It reuses the saved session (logging in with the
browser only if it has expired), fetches the login page and the dashboard, and
**never requests the clock URL**. It does refresh the session's "last used"
time, so don't run it just before a scheduled clock run you want to measure.
It prints check names and results only: no cookies, no page content, no
account data. `--save DIR` keeps the two pages for study (they contain
account data: delete them once read).
"""
import argparse
import os
import sys
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path

from eportem.core.clock_http import CLOCK_IDS, parse_buttons

LOGIN_FIELDS = ("cc", "recaptchaToken", "usuario", "password", "recordar")
_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}


# --- a small HTML tree, enough for the paths the Selenium flow uses ------------
class Node:
    def __init__(self, tag, attrs, parent=None):
        self.tag, self.attrs, self.parent, self.children = tag, attrs, parent, []

    def iter(self):
        yield self
        for c in self.children:
            yield from c.iter()

    def by_id(self, id_):
        return next((n for n in self.iter() if n.attrs.get("id") == id_), None)


class _TreeBuilder(HTMLParser):
    def __init__(self):
        super().__init__()
        self.root = self.current = Node("#root", {})

    def handle_starttag(self, tag, attrs):
        node = Node(tag, {k: (v or "") for k, v in attrs}, self.current)
        self.current.children.append(node)
        if tag not in _VOID:
            self.current = node

    def handle_startendtag(self, tag, attrs):
        self.current.children.append(Node(tag, {k: (v or "") for k, v in attrs}, self.current))

    def handle_endtag(self, tag):
        node = self.current
        while node is not self.root and node.tag != tag:
            node = node.parent
        if node is not self.root:  # close it (and anything left open inside it)
            self.current = node.parent


def parse_html(html):
    builder = _TreeBuilder()
    builder.feed(html)
    return builder.root


def path_exists(node, steps):
    """XPath-like child steps from `node`: "div" (any div child), "div[2]" (the
    second div child), "button[@data-toggle]" (a button child with that
    attribute). True if any branch matches every step."""
    if not steps:
        return True
    step, rest = steps[0], steps[1:]
    tag, index, attr = step, None, None
    if "[" in step:
        tag, cond = step[:-1].split("[", 1)
        if cond.startswith("@"):
            attr = cond[1:]
        else:
            index = int(cond)
    same = [c for c in node.children if c.tag == tag]
    if index is not None:
        same = same[index - 1:index]
    if attr is not None:
        same = [c for c in same if attr in c.attrs]
    return any(path_exists(c, rest) for c in same)


# --- checks -------------------------------------------------------------------
@dataclass
class Result:
    name: str
    ok: bool
    detail: str = ""


# The paths in eportem/core/actions.py selectors_for(), below #buttonsRegBox.
MAIN_BUTTON = ["div", "div", "button"]
MAIN_LABEL = ["div", "div", "button", "div", "div[2]", "h2"]
DROPDOWN = ["div", "button[@data-toggle]"]


def check_login_page(html):
    root = parse_html(html)
    form = root.by_id("login-form")
    results = [Result("login form #login-form", form is not None)]
    names = {n.attrs.get("name") for n in (form.iter() if form else [])}
    for field in LOGIN_FIELDS:
        results.append(Result(f"login field {field}", field in names))
    results.append(Result("login button #submit", root.by_id("submit") is not None))
    return results


def dashboard_state(buttons):
    """'not started', 'working', 'paused' or 'unknown', from the buttons on offer
    (the 2026-11-16 captures): not started offers _ststart for every activity;
    working offers resuming (_stini) only at the other place; paused offers it
    at both."""
    ids = {b.get("id") for b in buttons}
    if "_ststart" in ids:
        return "not started"
    if "_ststop" in ids:
        resume = [b for b in buttons if b.get("id") == "_stini"]
        return "paused" if len(resume) >= 2 else "working"
    return "unknown"


def check_dashboard(html, activity_ids=None):
    """Structure checks for the dashboard in whatever state it is. With
    activity_ids, also checks that this account's buttons are where the state
    says they should be."""
    root = parse_html(html)
    box = root.by_id("buttonsRegBox")
    results = [Result("clock box #buttonsRegBox", box is not None)]
    if box is None:
        return results, "unknown"
    buttons = parse_buttons(html)
    state = dashboard_state(buttons)
    results.append(Result("clock buttons present", bool(buttons), f"{len(buttons)} found"))
    bad = [b.get("id") for b in buttons if b.get("id") not in CLOCK_IDS]
    results.append(Result("clock button ids are known", not bad, ", ".join(bad)))
    no_handler = [b.get("id") for b in buttons if "_doPostJor" not in b.get("onclick", "")]
    results.append(Result("clock buttons call _doPostJor", not no_handler, ", ".join(no_handler)))
    odd_kind = [b.get("id") for b in buttons if b.get("name2") not in ("W", "P")]
    results.append(Result("clock buttons have name2 W or P", not odd_kind, ", ".join(odd_kind)))
    results.append(Result("main button (#buttonsRegBox/div/div/button)", path_exists(box, MAIN_BUTTON)))
    if state == "not started":
        results.append(Result("activity list toggle (#buttonsRegBox/div/button[@data-toggle])",
                              path_exists(box, DROPDOWN)))
    if state == "paused":
        results.append(Result("main button label (.../button/div/div[2]/h2)", path_exists(box, MAIN_LABEL)))
    if activity_ids is not None:
        def offered(id_, name=None):
            return any(b.get("id") == id_ and (name is None or b.get("name") == name) for b in buttons)
        expected = {
            "not started": [("_ststart", activity_ids.office), ("_ststart", activity_ids.home)],
            "working": [("_stpause", activity_ids.lunch_pause), ("_ststop", None)],
            "paused": [("_stini", activity_ids.office), ("_stini", activity_ids.home), ("_ststop", None)],
        }.get(state, [])
        for id_, name in expected:
            label = f"{id_}[{name}]" if name else id_
            results.append(Result(f"this account's {label} is offered ({state})", offered(id_, name)))
    return results, state


def activities_found(html):
    """(id, name, name2, name3) of every clock button, to find an account's IDs."""
    return sorted({(b.get("id"), b.get("name") or "", b.get("name2") or "", b.get("name3") or "")
                   for b in parse_buttons(html)})


# --- the real-site run --------------------------------------------------------
def _print_results(title, results, out):
    out(title)
    for r in results:
        out(f"  {'PASS' if r.ok else 'FAIL'}  {r.name}" + (f" ({r.detail})" if r.detail else ""))


def check_landing_page(clock):
    """The page a login lands on (ReturnUrl=/aplicaciones) must show the clock
    box: the Selenium flow looks for its button there before opening the
    registro page."""
    resp = clock.session.get(f"{clock.target.base_url}/aplicaciones", timeout=30)
    return [Result("login landing page shows #buttonsRegBox", "buttonsRegBox" in resp.text,
                   resp.url.replace(clock.target.base_url, ""))]


def run(clock, login_html, activity_ids=None, save_dir=None, out=print):
    """Check a fetched login page, the login's landing page and the dashboard
    behind `clock`'s session. Returns True when every check passed. Never calls
    the clock URL."""
    login_results = check_login_page(login_html) + check_landing_page(clock)
    dashboard_html = clock.fetch_dashboard()
    dashboard_results, state = check_dashboard(dashboard_html, activity_ids)
    if save_dir:
        save_dir = Path(save_dir)
        save_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        for name, text in (("login.html", login_html), ("dashboard.html", dashboard_html)):
            path = save_dir / name
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w") as f:
                f.write(text)
        out(f"Pages saved to {save_dir} (they hold account data: delete them once read)")
    _print_results("Login page:", login_results, out)
    _print_results(f"Dashboard (state: {state}):", dashboard_results, out)
    out("Activities on the dashboard (id, name, kind, label):")
    for a in activities_found(dashboard_html):
        out(f"  {a}")
    return all(r.ok for r in login_results + dashboard_results)


def main(argv=None):
    import requests
    from dotenv import load_dotenv

    from eportem.core import browser
    from eportem.core.activities import ActivityIds
    from eportem.core.clock_http import HttpClock
    from eportem.core.cookies import FileCookieStore
    from eportem.core.target import DEFAULT_BASE_URL, Target

    parser = argparse.ArgumentParser(description="Read-only check of ePortem's page structure.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--env-file", default="config/.env",
                        help="where EPORTEM_USERNAME / EPORTEM_PASSWORD / HEADLESS_BROWSING are")
    parser.add_argument("--cookie-file", default="config/.session_cookies.json",
                        help="the saved session to reuse (and update)")
    parser.add_argument("--activity-ids", help="OFFICE,HOME,LUNCH, to check this account's buttons too")
    parser.add_argument("--save", metavar="DIR", help="keep the fetched pages here")
    args = parser.parse_args(argv)

    load_dotenv(args.env_file)
    username, password = os.getenv("EPORTEM_USERNAME"), os.getenv("EPORTEM_PASSWORD")
    if not username or not password:
        print("EPORTEM_USERNAME and EPORTEM_PASSWORD must be set (see --env-file).", file=sys.stderr)
        return 2
    ids = ActivityIds(*args.activity_ids.split(",")) if args.activity_ids else None
    target = Target(args.base_url)
    headless = os.getenv("HEADLESS_BROWSING", "YES") == "YES"
    clock = HttpClock(target=target, activity_ids=ids, cookie_store=FileCookieStore(args.cookie_file),
                      make_driver=lambda: browser.create_driver(headless=headless),
                      login_driver=lambda d: browser.login(d, username, password))
    clock.ensure_session()
    login_html = requests.get(target.login_url, timeout=30, headers={"User-Agent": browser.USER_AGENT}).text
    ok = run(clock, login_html, ids, args.save)
    print("Contract OK." if ok else "Contract FAILED: the site changed; see the FAIL lines above.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
