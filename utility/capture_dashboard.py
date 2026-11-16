#!/usr/bin/env python3
"""Read-only capture of the ePortem dashboard, to find the clock endpoints.

Logs in with Selenium (exactly like the cron scripts), then saves what is
needed to work out which HTTP requests the clock buttons send. It NEVER
clicks a clock button and never sends a POST of its own, so it does not
register a clock event. Logging in does not change your clock status.

Saved under capture/<timestamp>/ (gitignored, chmod 700):
  dashboard.html          full page source, anti-forgery token values redacted
  buttons.html            outerHTML of #buttonsRegBox (dropdown items included)
  scripts/                every same-origin external script + inline scripts
  hits.txt                lines in those scripts mentioning ajax/post/url/_st*
  cookies.json            cookie names, domains and expiry - never values
  network.json            requests the browser made (URL, method; bodies redacted)
  session_check.txt       whether a requests.Session with copied cookies
                          can GET /aplicaciones (proves the hybrid approach)

Usage (on the host with config/.env):
  python3 -m utility.capture_dashboard
"""
import datetime
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from selenium import webdriver
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.common.by import By

from utility.env_loader import load_environment
from utility.login_and_navigate import login_and_navigate

BASE_URL = "https://eportem.es"
LOGIN_URL = f"{BASE_URL}/Usuario/Login?ReturnUrl=%2faplicaciones"
CAPTCHA_ERROR = "no es un robot"

# Lines in the dashboard scripts worth reading.
HIT_PATTERN = re.compile(
    r"\$\.(ajax|post|get|getJSON)|fetch\(|XMLHttpRequest|url\s*:|_st(start|pause|ini|stop)|"
    r"RequestVerificationToken|buttonsRegBox",
    re.IGNORECASE,
)
TOKEN_VALUE = re.compile(
    r'(name="__RequestVerificationToken"[^>]*value=")[^"]*(")', re.IGNORECASE
)


def _redact_html(html):
    return TOKEN_VALUE.sub(r"\1<redacted>\2", html)


def _redact_body(body):
    """Keep parameter names, drop values (the login POST carries the password)."""
    if not body:
        return body
    return re.sub(r"=([^&]*)", "=<redacted>", body)


def _make_driver():
    options = ChromeOptions()
    options.add_argument("--disable-gpu")
    if os.getenv("HEADLESS_BROWSING") == "YES":
        options.add_argument("--headless")
    options.set_capability("goog:loggingPrefs", {"performance": "ALL"})
    return webdriver.Chrome(options=options)


def _network_events(driver):
    events = []
    for entry in driver.get_log("performance"):
        msg = json.loads(entry["message"])["message"]
        if msg.get("method") != "Network.requestWillBeSent":
            continue
        req = msg["params"]["request"]
        events.append({
            "url": req["url"],
            "method": req["method"],
            "type": msg["params"].get("type"),
            "postData": _redact_body(req.get("postData")),
            "headers": sorted(req.get("headers", {}).keys()),
        })
    return events


def main():
    load_environment()
    out = Path("capture") / datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    (out / "scripts").mkdir(parents=True)
    os.chmod("capture", 0o700)

    driver = _make_driver()
    try:
        driver.get(LOGIN_URL)
        login_and_navigate(driver)  # fills the form and submits; no clicks after this

        page = driver.page_source
        if CAPTCHA_ERROR in page:
            print("Login rejected by reCAPTCHA ('no es un robot'). Nothing captured.")
            return 2
        if "/Usuario/Login" in driver.current_url:
            print(f"Still on the login page ({driver.current_url}); check credentials.")
            return 2
        print(f"Logged in, now at {driver.current_url}")

        (out / "dashboard.html").write_text(_redact_html(page))
        boxes = driver.find_elements(By.ID, "buttonsRegBox")
        (out / "buttons.html").write_text(
            _redact_html(boxes[0].get_attribute("outerHTML")) if boxes else "#buttonsRegBox not found\n"
        )

        cookies = driver.get_cookies()
        (out / "cookies.json").write_text(json.dumps(
            [{k: c.get(k) for k in ("name", "domain", "path", "expiry", "httpOnly", "secure")}
             for c in cookies], indent=2))

        session = requests.Session()
        session.headers["User-Agent"] = driver.execute_script("return navigator.userAgent")
        for c in cookies:
            session.cookies.set(c["name"], c["value"], domain=c.get("domain"), path=c.get("path", "/"))

        # Scripts: inline ones from the DOM, same-origin external ones via GET.
        hits = []
        inline = driver.execute_script(
            "return Array.from(document.scripts).filter(s => !s.src).map(s => s.text)")
        srcs = driver.execute_script(
            "return Array.from(document.scripts).filter(s => s.src).map(s => s.src)")
        sources = {f"inline-{i}.js": text for i, text in enumerate(inline)}
        for src in srcs:
            if urlparse(src).netloc not in ("eportem.es", "www.eportem.es"):
                continue
            resp = session.get(src, timeout=30)
            name = urlparse(src).path.strip("/").replace("/", "__")
            sources[name] = resp.text
        for name, text in sources.items():
            (out / "scripts" / name).write_text(text)
            for n, line in enumerate(text.splitlines(), 1):
                if HIT_PATTERN.search(line):
                    hits.append(f"{name}:{n}: {line.strip()[:300]}")
        (out / "hits.txt").write_text("\n".join(hits) + "\n")

        (out / "network.json").write_text(json.dumps(_network_events(driver), indent=2))

        # Prove the cookies work without the browser (read-only GET).
        resp = session.get(urljoin(BASE_URL, "/aplicaciones"), timeout=30, allow_redirects=False)
        ok = resp.status_code == 200 and "buttonsRegBox" in resp.text
        (out / "session_check.txt").write_text(
            f"GET /aplicaciones with copied cookies -> {resp.status_code}, "
            f"buttonsRegBox present: {ok}, Location: {resp.headers.get('Location')}\n")
        print(f"requests.Session reuse works: {ok}")
    finally:
        driver.quit()

    print(f"Saved to {out}/ ({len(hits)} script hits)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
