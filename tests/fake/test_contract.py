"""eportem.contract: the structure checks pass on the fake in every state, fail
on broken pages, and a full run never requests the clock URL."""
import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from eportem import contract
from eportem.core.activities import ActivityIds
from eportem.core.clock_http import HttpClock, parse_buttons
from eportem.core.cookies import MemoryCookieStore
from eportem.core.target import Target
from fake_eportem import Account, FakeEportem, pages
from fake_eportem.server import CAPTURED_IDS, CLOCK_PATH
from fake_eportem.testing import RequestsLoginDriver, login_with
from tests.test_http_clock import NOT_STARTED_HTML, PAUSED_HTML, WORKING_HTML

OTHER_IDS = ActivityIds(office="7", home="8", lunch_pause="9")


def attrs(buttons):
    return {(b.get("id"), b.get("name") or "", b.get("name2"), b.get("name3")) for b in buttons}


class TestFakeFollowsTheCaptures(unittest.TestCase):
    """Every button in the real captures is in the fake's page for that state."""

    def test_each_state(self):
        account = Account("OWNER", "x", CAPTURED_IDS)
        for state, captured in (("not_started", NOT_STARTED_HTML), ("working", WORKING_HTML),
                                ("paused", PAUSED_HTML)):
            with self.subTest(state=state):
                account.state = state
                account.working_activity = CAPTURED_IDS.office
                fake = attrs(parse_buttons(pages.dashboard_page(state, account)))
                missing = attrs(parse_buttons(captured)) - fake
                self.assertEqual(missing, set())


class TestChecksOnTheFake(unittest.TestCase):

    def test_login_page_passes_with_and_without_recaptcha(self):
        for recaptcha in (False, True):
            results = contract.check_login_page(pages.login_page(recaptcha))
            self.assertTrue(all(r.ok for r in results), [r for r in results if not r.ok])

    def test_dashboard_passes_and_state_is_detected_for_any_ids(self):
        for ids in (CAPTURED_IDS, OTHER_IDS):
            account = Account("X", "x", ids)
            for state, expected in (("not_started", "not started"), ("working", "working"),
                                    ("paused", "paused"), ("stopped", "not started")):
                with self.subTest(ids=ids, state=state):
                    account.state, account.working_activity = state, ids.office
                    results, found = contract.check_dashboard(pages.dashboard_page(state, account), ids)
                    self.assertEqual(found, expected)
                    self.assertTrue(all(r.ok for r in results), [r for r in results if not r.ok])

    def test_another_accounts_ids_fail_the_account_checks(self):
        account = Account("X", "x", CAPTURED_IDS)
        results, _ = contract.check_dashboard(pages.dashboard_page("not_started", account), OTHER_IDS)
        self.assertTrue(any(not r.ok and "_ststart[7]" in r.name for r in results))


class TestChecksCatchChanges(unittest.TestCase):

    def test_renamed_login_field(self):
        html = pages.login_page(False).replace('name="usuario"', 'name="user"')
        failed = [r.name for r in contract.check_login_page(html) if not r.ok]
        self.assertEqual(failed, ["login field usuario"])

    def test_no_clock_box(self):
        results, state = contract.check_dashboard(pages.maintenance_page())
        self.assertFalse(results[0].ok)
        self.assertEqual(state, "unknown")

    def test_flattened_layout_breaks_the_main_button_path(self):
        account = Account("X", "x")
        html = pages.dashboard_page("working", account).replace(
            '<div class="btn-group">\n      <button class="btn btn-outline', '<button class="btn btn-outline', 1)
        html = html.replace("</button>\n    </div>\n    <button class=\"btn btn-primary dropdown-toggle\"",
                            "</button>\n    <button class=\"btn btn-primary dropdown-toggle\"", 1)
        results, _ = contract.check_dashboard(html)
        self.assertIn("main button (#buttonsRegBox/div/div/button)", [r.name for r in results if not r.ok])

    def test_unknown_button_id_and_handler(self):
        html = ('<div id="buttonsRegBox"><div><div><button>x</button></div></div>'
                '<a id="_ststart" name="1" name2="W" name3="T" onclick="other()">x</a></div>')
        failed = [r.name for r in contract.check_dashboard(html)[0] if not r.ok]
        self.assertIn("clock buttons call _doPostJor", failed)


class TestPathExists(unittest.TestCase):

    def test_steps(self):
        root = contract.parse_html('<div id="b"><div><span></span><button data-x="1"></button></div>'
                                   '<div><p><br></p><h2></h2></div></div>')
        box = root.by_id("b")
        self.assertTrue(contract.path_exists(box, ["div", "button[@data-x]"]))
        self.assertFalse(contract.path_exists(box, ["div", "button[@data-y]"]))
        self.assertTrue(contract.path_exists(box, ["div[2]", "h2"]))
        self.assertFalse(contract.path_exists(box, ["div[1]", "h2"]))
        self.assertTrue(contract.path_exists(box, []))


class TestRunAgainstTheFake(unittest.TestCase):

    def test_run_passes_and_never_requests_the_clock_url(self):
        with FakeEportem([Account("ALICE", "pw", OTHER_IDS)]) as fake:
            target = Target(fake.base_url)
            clock = HttpClock(target=target, activity_ids=OTHER_IDS, cookie_store=MemoryCookieStore(),
                              make_driver=RequestsLoginDriver, login_driver=login_with("ALICE", "pw"),
                              say=lambda *a: None)
            clock.ensure_session()
            import requests
            login_html = requests.get(target.login_url, timeout=10).text
            lines = []
            with patch("builtins.print") as printed:
                ok = contract.run(clock, login_html, OTHER_IDS, out=lines.append)
            printed.assert_not_called()
            self.assertIn("  PASS  this account's _ststart[8] is offered (not started)", lines)
            self.assertTrue(ok)
            self.assertNotIn(CLOCK_PATH, fake.paths)
            self.assertEqual(fake.events, [])

    def test_save_writes_private_files(self):
        import os
        import tempfile
        with FakeEportem([Account("ALICE", "pw")]) as fake, tempfile.TemporaryDirectory() as tmp:
            target = Target(fake.base_url)
            clock = HttpClock(target=target, cookie_store=MemoryCookieStore(), make_driver=RequestsLoginDriver,
                              login_driver=login_with("ALICE", "pw"), say=lambda *a: None)
            clock.ensure_session()
            with redirect_stdout(io.StringIO()):
                contract.run(clock, pages.login_page(False), save_dir=os.path.join(tmp, "s"), out=lambda *a: None)
            self.assertEqual(os.stat(os.path.join(tmp, "s", "dashboard.html")).st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
