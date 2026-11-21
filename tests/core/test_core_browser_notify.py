"""checkin.core.browser and checkin.core.notify without any environment."""
import unittest
from unittest.mock import MagicMock, patch

from selenium.common.exceptions import TimeoutException

from checkin.core import browser
from checkin.core.notify import SlackChannel, SlackStatusUpdater, TelegramChannel
from checkin.core.schedule import actions_due_for_verify, due_task, validate_week_schedule, window_bounds
from checkin.core.target import Target

TARGET = Target("https://checkin.example.test")


class FakeWait:
    def __init__(self, driver, timeout):
        self.driver = driver

    def until(self, predicate):
        if not predicate(self.driver):
            raise TimeoutException("timed out")


def login_page_driver(url_after):
    d = MagicMock()
    d.current_url = TARGET.login_url
    d.page_source = ""
    d.execute_script.return_value = False  # no reCAPTCHA script on the page
    submit = MagicMock()
    submit.click.side_effect = lambda: setattr(d, "current_url", url_after)
    d.find_element.side_effect = lambda by, value: submit if value == "submit" else MagicMock()
    return d


class TestOpenAndLogin(unittest.TestCase):

    def setUp(self):
        p = patch("time.sleep")
        p.start()
        self.addCleanup(p.stop)

    def test_success_opens_the_targets_login_page(self):
        d = login_page_driver(TARGET.dashboard_url)
        self.assertIs(browser.open_and_login(TARGET, "u", "p", lambda: d, wait=FakeWait), d)
        d.get.assert_called_once_with(TARGET.login_url)
        d.quit.assert_not_called()

    def test_rejected_login_quits_and_never_shows_credentials(self):
        d = login_page_driver(TARGET.login_url)
        with self.assertRaises(browser.LoginRejected) as cm:
            browser.open_and_login(TARGET, "someone", "s3cret", lambda: d, wait=FakeWait)
        self.assertNotIn("s3cret", str(cm.exception))
        self.assertNotIn("someone", str(cm.exception))
        d.quit.assert_called_once()

    def test_start_browser_options(self):
        d = MagicMock()
        with patch.object(browser.webdriver, "Chrome", return_value=d) as chrome:
            browser.start_browser("UA", headless=True, binary_location="/opt/chromium")
        options = chrome.call_args.kwargs["options"]
        self.assertIn("--headless=new", options.arguments)
        self.assertIn("user-agent=UA", options.arguments)
        self.assertEqual(options.binary_location, "/opt/chromium")

    def test_stale_user_agent_restart_is_said_not_printed(self):
        said = []
        d = MagicMock()
        d.capabilities = {"browserVersion": "150.1"}
        with patch.object(browser.webdriver, "Chrome", return_value=d), patch("builtins.print") as printed:
            browser.create_driver(headless=True, say=said.append)
        printed.assert_not_called()
        self.assertIn("Chrome/150.0.0.0", said[0])


class TestNeutralLabels(unittest.TestCase):

    def test_skip_messages_name_settings_not_environment_variables(self):
        said = []
        self.assertIsNone(TelegramChannel(say=said.append).send("x"))
        self.assertIsNone(SlackChannel(say=said.append).send("x"))
        text = " ".join(said)
        self.assertIn("the Telegram bot token", text)
        self.assertIn("the Slack bot token", text)
        self.assertNotIn("TELEGRAM_BOT_TOKEN", text)
        self.assertNotIn("SLACK_TOKEN", text)

    def test_labels_can_be_replaced(self):
        said = []
        TelegramChannel(say=said.append, labels={"telegram_token": "Bot token field"}).send("x")
        self.assertIn("Bot token field", said[0])

    def test_status_updater_needs_a_token(self):
        with self.assertRaises(ValueError):
            SlackStatusUpdater(None)


class TestScheduleRules(unittest.TestCase):
    DAY = {"location": "home", "start_the_day": "9:00", "lunch_break": "13:30", "stop_the_day": "18:00"}

    def test_due_task_inside_the_window_only(self):
        self.assertEqual(due_task(self.DAY, 9 * 60 + 15, 15), ("start_the_day", 540))
        self.assertIsNone(due_task(self.DAY, 9 * 60 + 16, 15))

    def test_verify_waits_for_window_and_grace(self):
        self.assertEqual(actions_due_for_verify(self.DAY, 13 * 60 + 59, 15, 15), ["start_day"])
        self.assertEqual(actions_due_for_verify(self.DAY, 14 * 60, 15, 15), ["start_day", "lunch_break"])

    def test_window_is_clamped_to_the_day(self):
        self.assertEqual(window_bounds(5, 15), (0, 20))
        self.assertEqual(window_bounds(23 * 60 + 55, 15), (23 * 60 + 40, 24 * 60 - 1))

    def test_validation_reports_every_problem(self):
        problems = validate_week_schedule({"schedule": {"7": {"lunch_break": "25:00", "nap": "1"}}})
        self.assertEqual(len(problems), 3)


if __name__ == "__main__":
    unittest.main()
