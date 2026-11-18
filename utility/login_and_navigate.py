#!/usr/bin/env python
"""Legacy adapter: browser login with the credentials and flags from config/.env.

The browser set-up and the login form handling live in eportem.core.browser.
This module reads EPORTEM_USERNAME / EPORTEM_PASSWORD / HEADLESS_BROWSING and
passes its own WebDriverWait, so tests that patch names here still apply.
"""
import contextlib
import os
import time  # noqa: F401  (tests patch utility.login_and_navigate.time.sleep)

from selenium import webdriver  # noqa: F401  (tests patch utility.login_and_navigate.webdriver.Chrome)
from selenium.webdriver.support.ui import WebDriverWait

from eportem.core import browser as _core
from eportem.core.browser import (  # noqa: F401  (re-exported)
    CAPTCHA_ERROR,
    PAGE_LOAD_TIMEOUT_SECONDS,
    USER_AGENT,
    USER_AGENT_TEMPLATE,
    LoginRejected,
    user_agent_for,
    uses_recaptcha,
)
from eportem.core.target import Target

TARGET = Target()
LOGIN_URL = TARGET.login_url
STALE_UA_HINT = "(update USER_AGENT in eportem/core/browser.py to avoid the restart)"


def _start_browser(user_agent):
    return _core.start_browser(user_agent, os.getenv('HEADLESS_BROWSING') == "YES")


def create_driver():
    """Start the browser; restarts it once if USER_AGENT's Chrome version is stale."""
    return _core.create_driver(headless=os.getenv('HEADLESS_BROWSING') == "YES",
                               user_agent=USER_AGENT, stale_hint=STALE_UA_HINT)


def _wait_for_login_result(driver):
    _core.wait_for_login_result(driver, wait=WebDriverWait)


def login_and_navigate(driver=None):
    # Fail before a browser is opened; names only, never values.
    uname = os.getenv('EPORTEM_USERNAME')
    pwd = os.getenv('EPORTEM_PASSWORD')
    for name, value in (("EPORTEM_USERNAME", uname), ("EPORTEM_PASSWORD", pwd)):
        if not value:
            raise RuntimeError(f"{name} is not set; add it to config/.env")

    # create a new Chrome browser instance if one isn't passed in; one created here is
    # quit if the login fails, one passed in is left to its owner
    created = driver is None
    if created:
        driver = create_driver()
    try:
        if created:
            driver.get(LOGIN_URL)
        _login(driver, uname, pwd)
    except BaseException:
        if created:
            with contextlib.suppress(Exception):  # the original error matters more
                driver.quit()
        raise
    return driver


def _login(driver, uname, pwd):
    _core.login(driver, uname, pwd, wait=WebDriverWait)


if __name__ == '__main__':
    # Log in and report where the browser ended up. Clicks nothing: the old example
    # clicked the main dashboard button, which on a not-started office day records
    # a clock-in.
    from utility.env_loader import load_environment
    load_environment()
    driver = login_and_navigate()
    try:
        print(f"Logged in: {driver.current_url}")
    finally:
        driver.quit()
