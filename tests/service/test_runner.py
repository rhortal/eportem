"""checkin.scheduler.runner: the browser gate, channels from rows, alerts, and
the scheduler's background thread."""
import threading
from unittest.mock import MagicMock, patch

from checkin.db.models import NotificationChannelRow
from checkin.scheduler.runner import BrowserGate, channels_for, secrets_for, send_alert, status_updater_for
from tests.service.test_scheduler import DAY, SchedulerCase, utc


class TestBrowserGate(SchedulerCase):

    def test_second_browser_waits_until_the_first_quits(self):
        gate = BrowserGate(1)
        make = gate.wrap(MagicMock)
        first = make()
        got = []
        t = threading.Thread(target=lambda: got.append(make()))
        t.start()
        threading.Event().wait(0.1)  # time.sleep is patched out in these tests
        self.assertEqual(got, [])            # still waiting for the slot
        first.quit()
        t.join(timeout=2)
        self.assertEqual(len(got), 1)
        first.quit()                          # a second quit doesn't free a second slot
        got[0].quit()

    def test_a_failed_start_gives_the_slot_back(self):
        gate = BrowserGate(1)
        failing = gate.wrap(MagicMock(side_effect=RuntimeError("no chrome")))
        with self.assertRaises(RuntimeError):
            failing()
        gate.wrap(MagicMock)().quit()         # would block forever if the slot leaked


class TestChannels(SchedulerCase):

    def setUp(self):
        super().setUp()
        self.uid = self.person(0)
        with self.Session.begin() as db:
            db.add(NotificationChannelRow(user_id=self.uid, kind="telegram", notify=True, alerts=False,
                                          config_enc=self.box.encrypt_json({"token": "tg-token-1", "chat_id": "5"})))
            slack = self.box.encrypt_json({"bot_token": "xoxb-b", "user_token": "xoxp-u"})
            db.add(NotificationChannelRow(user_id=self.uid, kind="slack", notify=False, alerts=True,
                                          slack_status=True, config_enc=slack))

    def test_purpose_picks_the_channels(self):
        with self.Session() as db:
            self.assertEqual([c.name for c in channels_for(db, self.box, self.uid, "notify", print)], ["telegram"])
            self.assertEqual([c.name for c in channels_for(db, self.box, self.uid, "alerts", print)], ["slack"])
            self.assertEqual(status_updater_for(db, self.box, self.uid, print).token, "xoxp-u")
            self.assertIn("tg-token-1", secrets_for(db, self.box, self.uid))
            self.assertIn("pw0", secrets_for(db, self.box, self.uid))

    def test_send_alert_uses_the_alert_channels_and_never_raises(self):
        response = MagicMock(ok=True, status_code=200)
        response.json.return_value = {"ok": True, "user_id": "U1"}
        with self.Session() as db, patch("requests.post", return_value=response) as post:
            self.assertEqual(send_alert(db, self.box, self.uid, "hello"), [])
        self.assertTrue(all("slack.com" in c.args[0] for c in post.call_args_list))
        with self.Session() as db, patch("checkin.scheduler.runner.channels_for", side_effect=RuntimeError):
            self.assertEqual(send_alert(db, self.box, self.uid, "x"), ["alerts"])

    def test_notifications_reach_the_run_log_and_secrets_are_scrubbed(self):
        from checkin.db.models import RunLog
        response = MagicMock(status_code=500, text="bad tg-token-1")
        with patch("requests.post", return_value=response):
            self.run_day(self.scheduler(), end="09:30")
        run = self.runs(self.uid)["start_day"]
        self.assertEqual(run.status, "recorded")
        with self.Session() as db:
            text = db.get(RunLog, run.id).text
        self.assertIn("Telegram notification failed", text)
        self.assertNotIn("tg-token-1", text)


class TestBackground(SchedulerCase):

    def test_run_forever_ticks_until_stopped(self):
        self.person(0)
        sched = self.scheduler()
        ticks = []
        sched.tick = lambda now=None: ticks.append(now)
        t = threading.Thread(target=sched.run_forever, kwargs={"interval_seconds": 0.01})
        t.start()
        threading.Event().wait(0.1)  # time.sleep is patched out in these tests
        sched.stop()
        t.join(timeout=2)
        self.assertFalse(t.is_alive())
        self.assertGreater(len(ticks), 1)

    def test_a_failing_tick_does_not_stop_the_loop(self):
        sched = self.scheduler()
        calls = []

        def tick(now=None):
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("database away")
            sched.stop()
        sched.tick = tick
        with self.assertLogs("checkin.scheduler", "ERROR"):
            sched.run_forever(interval_seconds=0.01)
        self.assertEqual(len(calls), 2)

    def test_executor_runs_claimed_actions(self):
        from concurrent.futures import ThreadPoolExecutor
        uid = self.person(0)
        with ThreadPoolExecutor(2) as pool:
            sched = self.scheduler(executor=pool)
            sched.tick(utc(DAY, "06:00"))
            sched.tick(utc(DAY, "09:10"))
        self.assertEqual(self.runs(uid)["start_day"].status, "recorded")
