"""Start Chromium so it looks like a desktop browser, and log in to ePortem.

ePortem added reCAPTCHA v3 to the login form (2026-10-29). Its score rejects
plain headless Chrome, so the browser is made to look like a normal desktop one
(docs/http-api-investigation.md). Login is the only step that needs a browser.
"""
import contextlib
import time

from selenium import webdriver
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.chrome.options import Options as ChromeOptions
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait

from checkin.core.output import default_say
from checkin.core.target import Target

USER_AGENT = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/156.0.0.0 Safari/537.36")
# create_driver() swaps in the real browser's major version when it differs.
USER_AGENT_TEMPLATE = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/{major}.0.0.0 Safari/537.36")
CAPTCHA_ERROR = "No se ha podido verificar que no es un robot"
PAGE_LOAD_TIMEOUT_SECONDS = 90
LOGIN_WAIT_SECONDS = 20


def user_agent_for(browser_version, fallback=USER_AGENT):
    """The desktop-Linux Chrome UA with the major version of browser_version
    ('150.0.7871.181'); `fallback` if it is missing or unparsable."""
    major = str(browser_version or "").split(".")[0]
    return USER_AGENT_TEMPLATE.format(major=major) if major.isdigit() else fallback


class LoginRejected(WebDriverException):
    """The login form was submitted but the site did not log us in. A
    WebDriverException so callers that retry on browser errors retry it too."""


def uses_recaptcha(driver):
    return driver.execute_script(
        "return [...document.scripts].some(s => /recaptcha/i.test(s.src))")


def start_browser(user_agent, headless, binary_location=None, sandbox=True, driver_path=None):
    """One Chromium with the given UA. `webdriver.Chrome` is looked up per call.
    sandbox=False adds --no-sandbox, for containers where Chromium's own sandbox
    can't start as a non-root user (the container is the isolation then)."""
    chrome_options = ChromeOptions()
    if not sandbox:
        chrome_options.add_argument("--no-sandbox")
    if binary_location:
        chrome_options.binary_location = binary_location
    chrome_options.add_argument("--disable-gpu")
    if headless:
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
    if driver_path:
        from selenium.webdriver.chrome.service import Service
        driver = webdriver.Chrome(options=chrome_options, service=Service(driver_path))
    else:
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


def create_driver(headless=True, user_agent=USER_AGENT, binary_location=None,
                  say=default_say, stale_hint="", sandbox=True, driver_path=None):
    """Start the browser. The UA has to be given before start-up, and the real
    version is only known afterwards, so start with `user_agent` and, only if its
    Chrome version turns out to be stale, start again with the right one. A UA that
    disagrees with the browser's own client hints is a bot signal."""
    driver = start_browser(user_agent, headless, binary_location, sandbox, driver_path)
    try:
        wanted = user_agent_for(driver.capabilities.get("browserVersion"), fallback=user_agent)
    except BaseException:
        driver.quit()
        raise
    if wanted == user_agent:
        return driver
    say(f"Browser is not the Chrome version in USER_AGENT; restarting it as: {wanted}"
        + (f" {stale_hint}" if stale_hint else ""))
    driver.quit()
    return start_browser(wanted, headless, binary_location, sandbox, driver_path)


def wait_for_login_result(driver, wait=None):
    """Rejected logins (reCAPTCHA) re-render the form at the same URL, so end the
    wait as soon as that text shows up instead of after the full timeout."""
    wait = wait or WebDriverWait
    wait(driver, LOGIN_WAIT_SECONDS).until(
        lambda d: not Target.is_login_page(d.current_url) or CAPTCHA_ERROR in d.page_source)


def login(driver, username, password, wait=None):
    """Fill in and submit the login form on the page the driver is showing.
    Raises LoginRejected when the site doesn't log us in. Never puts the
    credentials in an error message. `wait` defaults to WebDriverWait."""
    wait = wait or WebDriverWait
    # ePortem has turned reCAPTCHA v3 on (2026-10-29) and off again (2026-10-30). When
    # the page loads its script, wait for it, since the form submit handler needs it
    # for its token; otherwise log in straight away.
    if uses_recaptcha(driver):
        wait(driver, LOGIN_WAIT_SECONDS).until(
            lambda d: d.execute_script("return typeof grecaptcha !== 'undefined' && !!grecaptcha.execute"))
    time.sleep(3)

    username_field = driver.find_element(By.NAME, "usuario")
    password_field = driver.find_element(By.NAME, "password")

    username_field.click()
    username_field.send_keys(username)
    time.sleep(0.7)
    password_field.click()
    password_field.send_keys(password)
    time.sleep(0.8)

    driver.find_element(By.ID, "submit").click()

    # wait for the redirect away from the login page, then for the page to load
    try:
        wait_for_login_result(driver, wait)
    except TimeoutException:
        if CAPTCHA_ERROR in driver.page_source:
            raise LoginRejected("Login rejected by reCAPTCHA ('no es un robot')") from None
        raise LoginRejected(f"Login did not leave the login page ({driver.current_url}); "
                            "check the credentials") from None
    if Target.is_login_page(driver.current_url):  # the wait ended on the captcha text
        raise LoginRejected("Login rejected by reCAPTCHA ('no es un robot')")
    time.sleep(3)


def open_and_login(target, username, password, make_driver, wait=None):
    """Start a browser with make_driver(), open the login page and log in.
    Returns the logged-in driver; quits it if anything fails."""
    driver = make_driver()
    try:
        driver.get(target.login_url)
        login(driver, username, password, wait)
    except BaseException:
        with contextlib.suppress(Exception):  # the original error matters more
            driver.quit()
        raise
    return driver
