"""Test helpers for driving the fake ePortem without a browser."""
import requests

from checkin.core.browser import CAPTCHA_ERROR, LoginRejected
from checkin.core.target import Target


class RequestsLoginDriver:
    """Just enough of a Selenium driver for HttpClock.browser_login(): it logs in
    to the fake with a plain form POST. Only works while the fake's reCAPTCHA is
    off - like the real site, the fake rejects a login without a token."""
    user_agent = "Mozilla/5.0 (fake-eportem test driver)"

    def __init__(self):
        self.session = requests.Session()
        self.current_url = None
        self.quit_called = False

    def get(self, url):
        self.current_url = self.session.get(url, timeout=10).url

    def login(self, username, password):
        resp = self.session.post(self.current_url, data={"usuario": username, "password": password,
                                                         "cc": "false", "recaptchaToken": ""}, timeout=10)
        self.current_url = resp.url
        if Target.is_login_page(resp.url):
            if CAPTCHA_ERROR in resp.text:
                raise LoginRejected("Login rejected by reCAPTCHA ('no es un robot')")
            raise LoginRejected(f"Login did not leave the login page ({resp.url}); check the credentials")
        return self

    def execute_script(self, script):
        return self.user_agent

    def get_cookies(self):
        return [{"name": c.name, "value": c.value, "domain": c.domain, "path": c.path}
                for c in self.session.cookies]

    def quit(self):
        self.quit_called = True


def login_with(username, password):
    """A login_driver for HttpClock: logs the RequestsLoginDriver in."""
    return lambda driver: driver.login(username, password)
