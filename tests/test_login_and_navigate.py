import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import unittest
from unittest.mock import MagicMock, patch

from selenium.common.exceptions import TimeoutException, WebDriverException

from utility import login_and_navigate as lan
from utility.login_and_navigate import LoginRejected, login_and_navigate

ENV = {"EPORTEM_USERNAME": "someone", "EPORTEM_PASSWORD": "s3cret"}


class FakeWait:
    """Stands in for WebDriverWait: runs the predicate once, times out if falsy."""
    def __init__(self, driver, timeout):
        self.driver = driver

    def until(self, predicate):
        if not predicate(self.driver):
            raise TimeoutException("timed out")


def _driver(url_after="https://eportem.es/aplicaciones", page_after="", recaptcha=False):
    d = MagicMock()
    d.current_url = "https://eportem.es/Usuario/Login?ReturnUrl=%2faplicaciones"
    d.page_source = ""
    d.execute_script.return_value = recaptcha
    def submit():
        d.current_url, d.page_source = url_after, page_after
    d.find_element.return_value.click.side_effect = lambda: None
    submit_button = MagicMock()
    submit_button.click.side_effect = submit
    d.find_element.side_effect = lambda by, value: submit_button if value == "submit" else MagicMock()
    return d


class TestLogin(unittest.TestCase):

    def setUp(self):
        for p in (patch.dict(os.environ, ENV), patch.object(lan.time, "sleep"),
                  patch.object(lan, "WebDriverWait", FakeWait), patch("builtins.print")):
            p.start()
            self.addCleanup(p.stop)

    def test_success_returns_the_given_driver_and_does_not_quit_it(self):
        d = _driver()
        self.assertIs(login_and_navigate(d), d)
        d.quit.assert_not_called()

    def test_captcha_rejection_raises_login_rejected(self):
        d = _driver(url_after="https://eportem.es/Usuario/Login",
                    page_after="<p>No se ha podido verificar que no es un robot</p>")
        with self.assertRaises(LoginRejected) as cm:
            login_and_navigate(d)
        self.assertIn("reCAPTCHA", str(cm.exception))
        d.quit.assert_not_called()  # a passed-in driver belongs to the caller

    def test_still_on_login_page_raises_login_rejected_with_url(self):
        d = _driver(url_after="https://eportem.es/Usuario/Login", page_after="<form></form>")
        with self.assertRaises(LoginRejected) as cm:
            login_and_navigate(d)
        self.assertIn("/Usuario/Login", str(cm.exception))
        self.assertIn("credentials", str(cm.exception))
        self.assertNotIn("reCAPTCHA", str(cm.exception))

    def test_messages_never_contain_credentials(self):
        for page in ("", "No se ha podido verificar que no es un robot"):
            d = _driver(url_after="https://eportem.es/Usuario/Login", page_after=page)
            with self.assertRaises(LoginRejected) as cm:
                login_and_navigate(d)
            self.assertNotIn("s3cret", str(cm.exception))
            self.assertNotIn("someone", str(cm.exception))

    def test_login_rejected_is_a_webdriver_exception(self):
        # eportem_action._login retries on WebDriverException
        self.assertTrue(issubclass(LoginRejected, WebDriverException))

    def test_wait_ends_early_on_captcha_text(self):
        d = MagicMock()
        d.current_url = "https://eportem.es/Usuario/Login"
        d.page_source = "No se ha podido verificar que no es un robot"
        with patch.object(lan, "WebDriverWait", FakeWait):
            lan._wait_for_login_result(d)  # FakeWait raises if the predicate is falsy
        d.page_source = "<form>"
        with patch.object(lan, "WebDriverWait", FakeWait), self.assertRaises(TimeoutException):
            lan._wait_for_login_result(d)

    def test_driver_created_here_is_quit_on_failure(self):
        d = _driver(url_after="https://eportem.es/Usuario/Login")
        with patch.object(lan, "create_driver", return_value=d):
            with self.assertRaises(LoginRejected):
                login_and_navigate()
        d.get.assert_called_once_with(lan.LOGIN_URL)
        d.quit.assert_called_once()

    def test_driver_created_here_is_returned_on_success_and_not_quit(self):
        d = _driver()
        with patch.object(lan, "create_driver", return_value=d):
            self.assertIs(login_and_navigate(), d)
        d.quit.assert_not_called()

    def test_driver_created_here_is_quit_on_any_error(self):
        d = _driver()
        d.find_element.side_effect = RuntimeError("no form")
        with patch.object(lan, "create_driver", return_value=d):
            with self.assertRaises(RuntimeError):
                login_and_navigate()
        d.quit.assert_called_once()

    def test_passed_driver_is_not_quit_on_unexpected_error(self):
        d = _driver()
        d.find_element.side_effect = RuntimeError("no form")
        with self.assertRaises(RuntimeError):
            login_and_navigate(d)
        d.quit.assert_not_called()


class TestMissingCredentials(unittest.TestCase):

    def _run(self, env):
        with patch.dict(os.environ, env, clear=True), \
             patch.object(lan, "create_driver") as create:
            with self.assertRaises(RuntimeError) as cm:
                login_and_navigate()
        create.assert_not_called()  # fails before a browser is opened
        return str(cm.exception)

    def test_missing_username(self):
        self.assertIn("EPORTEM_USERNAME", self._run({"EPORTEM_PASSWORD": "s3cret"}))

    def test_missing_password(self):
        msg = self._run({"EPORTEM_USERNAME": "someone"})
        self.assertIn("EPORTEM_PASSWORD", msg)
        self.assertNotIn("someone", msg)

    def test_empty_values_count_as_missing(self):
        self.assertIn("EPORTEM_USERNAME",
                      self._run({"EPORTEM_USERNAME": "", "EPORTEM_PASSWORD": "x"}))

    def test_passed_driver_untouched_when_credentials_missing(self):
        d = MagicMock()
        with patch.dict(os.environ, {}, clear=True), self.assertRaises(RuntimeError):
            login_and_navigate(d)
        d.find_element.assert_not_called()


class TestCreateDriver(unittest.TestCase):

    def _create(self, capabilities, cdp_side_effect=None):
        d = MagicMock()
        d.capabilities = capabilities
        d.execute_cdp_cmd.side_effect = cdp_side_effect
        with patch.object(lan.webdriver, "Chrome", return_value=d) as chrome:
            try:
                result = lan.create_driver()
            except Exception as e:
                result = e
        return d, chrome, result

    @staticmethod
    def _ua_args(chrome):
        return [a for call in chrome.call_args_list
                for a in call.kwargs["options"].arguments if a.startswith("user-agent=")]

    def test_matching_version_starts_once_with_the_constant(self):
        major = lan.USER_AGENT.split("Chrome/")[1].split(".")[0]
        d, chrome, result = self._create({"browserVersion": f"{major}.0.8078.79"})
        self.assertIs(result, d)
        self.assertEqual(self._ua_args(chrome), [f"user-agent={lan.USER_AGENT}"])
        d.quit.assert_not_called()
        # Never through CDP: that would not reach the reCAPTCHA frames.
        self.assertNotIn("Network.setUserAgentOverride",
                         [c.args[0] for c in d.execute_cdp_cmd.call_args_list])

    def test_stale_version_restarts_with_the_real_one(self):
        d, chrome, result = self._create({"browserVersion": "150.0.7871.181"})
        self.assertIs(result, d)
        uas = self._ua_args(chrome)
        self.assertEqual(len(uas), 2)
        self.assertIn("Chrome/150.0.0.0", uas[1])
        self.assertIn("X11; Linux x86_64", uas[1])
        d.quit.assert_called_once()  # the first browser, before the restart

    def test_keeps_the_constant_when_version_unknown(self):
        for caps in ({}, {"browserVersion": ""}, {"browserVersion": "weird"}):
            d, chrome, _ = self._create(caps)
            self.assertEqual(self._ua_args(chrome), [f"user-agent={lan.USER_AGENT}"])

    def test_user_agent_for(self):
        self.assertIn("Chrome/99.0.0.0", lan.user_agent_for("99.1.2.3"))
        self.assertEqual(lan.user_agent_for(None), lan.USER_AGENT)

    def test_driver_quit_if_setup_fails(self):
        d, _, result = self._create({"browserVersion": "150.0.1"},
                                    cdp_side_effect=RuntimeError("cdp"))
        self.assertIsInstance(result, RuntimeError)
        d.quit.assert_called_once()


if __name__ == "__main__":
    unittest.main()
