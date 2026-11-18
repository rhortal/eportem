#!/usr/bin/env python
import contextlib
import os
import time

from selenium import webdriver
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

# ePortem added reCAPTCHA v3 to the login form (2026-10-29). Its score rejects
# plain headless Chrome, so the browser is made to look like a normal desktop one.
USER_AGENT = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/156.0.0.0 Safari/537.36")
# create_driver() swaps in the real browser's major version when it differs.
USER_AGENT_TEMPLATE = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/{major}.0.0.0 Safari/537.36")
CAPTCHA_ERROR = "No se ha podido verificar que no es un robot"
LOGIN_URL = "https://eportem.es/Usuario/Login?ReturnUrl=%2faplicaciones"
PAGE_LOAD_TIMEOUT_SECONDS = 90


def user_agent_for(browser_version):
    """The desktop-Linux Chrome UA with the major version of browser_version
    ('150.0.7871.181'); USER_AGENT if it is missing or unparsable."""
    major = str(browser_version or "").split(".")[0]
    return USER_AGENT_TEMPLATE.format(major=major) if major.isdigit() else USER_AGENT


class LoginRejected(WebDriverException):
    """The login form was submitted but the site did not log us in. A
    WebDriverException so eportem_action._login's retry still catches it."""


def uses_recaptcha(driver):
    return driver.execute_script(
        "return [...document.scripts].some(s => /recaptcha/i.test(s.src))")


def _start_browser(user_agent):
    headless = os.getenv('HEADLESS_BROWSING')
    chrome_options = ChromeOptions()
    chrome_options.add_argument("--disable-gpu")
    if headless == "YES":
        chrome_options.add_argument("--headless=new")
    chrome_options.add_argument("--window-size=1366,900")
    chrome_options.add_argument("--lang=es-ES")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    # Set on the command line, not through CDP: this way it applies to the whole
    # browser, including the cross-site reCAPTCHA frames, which a per-page CDP
    # override would leave announcing "HeadlessChrome".
    chrome_options.add_argument(f"user-agent={user_agent}")
    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option("useAutomationExtension", False)
    driver = webdriver.Chrome(options=chrome_options)
    try:
        driver.set_page_load_timeout(PAGE_LOAD_TIMEOUT_SECONDS)
        driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
            "source": "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        })
    except BaseException:
        driver.quit()
        raise
    return driver


def create_driver():
    """Start the browser. The UA has to be given before start-up, and the real
    version is only known afterwards, so start with USER_AGENT and, only if its
    Chrome version turns out to be stale, start again with the right one. A UA that
    disagrees with the browser's own client hints is a bot signal."""
    driver = _start_browser(USER_AGENT)
    try:
        wanted = user_agent_for(driver.capabilities.get("browserVersion"))
    except BaseException:
        driver.quit()
        raise
    if wanted == USER_AGENT:
        return driver
    print(f"Browser is not the Chrome version in USER_AGENT; restarting it as: {wanted} "
          "(update USER_AGENT in utility/login_and_navigate.py to avoid the restart)")
    driver.quit()
    return _start_browser(wanted)


def _wait_for_login_result(driver):
    # Rejected logins (reCAPTCHA) re-render the form at the same URL, so end the wait
    # as soon as that text shows up instead of after the full timeout.
    WebDriverWait(driver, 20).until(
        lambda d: "/Usuario/Login" not in d.current_url or CAPTCHA_ERROR in d.page_source)


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
    # ePortem has turned reCAPTCHA v3 on (2026-10-29) and off again (2026-10-30). When
    # the page loads its script, wait for it, since the form submit handler needs it
    # for its token; otherwise log in straight away.
    if uses_recaptcha(driver):
        WebDriverWait(driver, 20).until(
            lambda d: d.execute_script("return typeof grecaptcha !== 'undefined' && !!grecaptcha.execute"))
    time.sleep(3)

    # find the username and password fields within the login form
    username = driver.find_element(By.NAME, "usuario")
    password = driver.find_element(By.NAME, "password")

    username.click()
    username.send_keys(uname)
    time.sleep(0.7)
    password.click()
    password.send_keys(pwd)
    time.sleep(0.8)

    # submit the login form
    driver.find_element(By.ID, "submit").click()

    # wait for the redirect away from the login page, then for the page to load
    try:
        _wait_for_login_result(driver)
    except TimeoutException:
        if CAPTCHA_ERROR in driver.page_source:
            raise LoginRejected("Login rejected by reCAPTCHA ('no es un robot')") from None
        raise LoginRejected(f"Login did not leave the login page ({driver.current_url}); "
                            "check the credentials") from None
    if "/Usuario/Login" in driver.current_url:  # the wait ended on the captcha text
        raise LoginRejected("Login rejected by reCAPTCHA ('no es un robot')")
    time.sleep(3)

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
