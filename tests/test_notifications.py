import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import contextlib
import io
import unittest
from unittest.mock import MagicMock, patch

import requests

from utility import env_check
from utility.notification_send import (
    REQUEST_TIMEOUT, NotificationManager, SlackChannel, TelegramChannel, _scrub,
)
from utility.slack_status import SlackStatusUpdater

TOKEN = "123456:ABC-secret-token"
WEBHOOK = "https://hooks.slack.com/services/T000/B000/webhooksecret"
SLACK_TOKEN = "xoxp-1111-2222-slacksecret"
BOT_TOKEN = "xoxb-3333-4444-botsecret"


def _capture():
    return contextlib.redirect_stdout(io.StringIO())


def _response(status=200, text="ok", json_body=None):
    r = MagicMock(status_code=status, text=text, ok=status == 200)
    r.json.return_value = json_body if json_body is not None else {}
    return r


def _connection_error(url):
    # The shape requests really produces: the full URL is in the message.
    return requests.ConnectionError(
        f"HTTPSConnectionPool(host='api.telegram.org', port=443): Max retries exceeded "
        f"with url: {url} (Caused by NewConnectionError('Failed to resolve'))")


class TestScrub(unittest.TestCase):

    def test_removes_given_secrets(self):
        self.assertEqual(_scrub("a SECRET b", "SECRET"), "a <redacted> b")

    def test_ignores_empty_secrets(self):
        self.assertEqual(_scrub("abc", "", None), "abc")

    def test_requests_message_loses_the_bot_token(self):
        err = _connection_error(f"/bot{TOKEN}/sendMessage")
        self.assertNotIn(TOKEN, _scrub(err, TOKEN))
        # ...even when we were not told the token:
        self.assertNotIn(TOKEN, _scrub(err))
        self.assertIn("Max retries exceeded", _scrub(err, TOKEN))

    def test_webhook_and_slack_token_patterns(self):
        text = f"POST {WEBHOOK} failed, token {SLACK_TOKEN}"
        out = _scrub(text)
        self.assertNotIn("webhooksecret", out)
        self.assertNotIn("slacksecret", out)


class TestTelegram(unittest.TestCase):

    def test_success_passes_timeout(self):
        with patch("requests.post", return_value=_response()) as post, _capture():
            self.assertTrue(TelegramChannel(TOKEN, "42").send("hi"))
        self.assertEqual(post.call_args.kwargs["timeout"], REQUEST_TIMEOUT)
        self.assertEqual(REQUEST_TIMEOUT, 15)

    def test_network_error_returns_false_and_prints_no_token(self):
        err = _connection_error(f"/bot{TOKEN}/sendMessage")
        with patch("requests.post", side_effect=err), _capture() as out:
            self.assertFalse(TelegramChannel(TOKEN, "42").send("hi"))
        printed = out.getvalue()
        self.assertIn("ConnectionError", printed)
        self.assertNotIn(TOKEN, printed)
        self.assertNotIn("api.telegram.org/bot", printed)

    def test_timeout_is_a_request_exception(self):
        with patch("requests.post", side_effect=requests.Timeout("slow")), _capture():
            self.assertFalse(TelegramChannel(TOKEN, "42").send("hi"))

    def test_http_error_status_returns_false_without_url(self):
        with patch("requests.post", return_value=_response(401, "Unauthorized")), _capture() as out:
            self.assertFalse(TelegramChannel(TOKEN, "42").send("hi"))
        self.assertIn("401", out.getvalue())
        self.assertIn("Unauthorized", out.getvalue())
        self.assertNotIn(TOKEN, out.getvalue())

    def test_missing_credentials_skip_without_a_request(self):
        for token, chat in (("", "42"), (TOKEN, ""), ("", "")):
            with self.subTest(token=token, chat=chat):
                with patch.dict(os.environ, {"TELEGRAM_BOT_TOKEN": "", "TELEGRAM_CHAT_ID": ""}), \
                        patch("requests.post") as post, _capture() as out:
                    self.assertIsNone(TelegramChannel(token, chat).send("hi"))
                post.assert_not_called()
                self.assertIn("skipped", out.getvalue())


class TestSlackChannel(unittest.TestCase):

    def test_success_passes_timeout(self):
        with patch("requests.post", return_value=_response()) as post, _capture():
            self.assertTrue(SlackChannel(WEBHOOK).send("hi"))
        self.assertEqual(post.call_args.kwargs["timeout"], REQUEST_TIMEOUT)

    def test_network_error_returns_false_and_prints_no_webhook(self):
        err = requests.ConnectionError(f"Max retries exceeded with url: {WEBHOOK}")
        with patch("requests.post", side_effect=err), _capture() as out:
            self.assertFalse(SlackChannel(WEBHOOK).send("hi"))
        self.assertIn("ConnectionError", out.getvalue())
        self.assertNotIn("webhooksecret", out.getvalue())

    def test_error_status_returns_false(self):
        with patch("requests.post", return_value=_response(404, "no_service")), _capture() as out:
            self.assertFalse(SlackChannel(WEBHOOK).send("hi"))
        self.assertIn("404", out.getvalue())

    def test_missing_webhook_and_token_skips(self):
        with patch.dict(os.environ, {"SLACK_WEBHOOK_URL": "", "SLACK_TOKEN": "", "SLACK_BOT_TOKEN": "", "SLACK_NOTIFY_CHANNEL": ""}), \
                patch("requests.post") as post, _capture() as out:
            self.assertIsNone(SlackChannel().send("hi"))
        post.assert_not_called()
        self.assertIn("none of SLACK_BOT_TOKEN, SLACK_TOKEN or SLACK_WEBHOOK_URL is configured", out.getvalue())


def _api(**by_method):
    """requests.post fake answering by Slack API method (last URL segment)."""
    def fake(url, **kwargs):
        return by_method[url.rsplit("/", 1)[1]]
    return fake


AUTH_OK = _response(json_body={"ok": True, "user_id": "U123"})
POST_OK = _response(json_body={"ok": True})


class TestSlackToken(unittest.TestCase):

    def _send(self, side_effect, **kwargs):
        with patch.dict(os.environ, {"SLACK_WEBHOOK_URL": "", "SLACK_BOT_TOKEN": "", "SLACK_NOTIFY_CHANNEL": ""}), \
                patch("requests.post", side_effect=side_effect) as post, _capture() as out:
            result = SlackChannel(token=SLACK_TOKEN, **kwargs).send("hi")
        return result, post, out.getvalue()

    def _failure(self, side_effect, **kwargs):
        result, post, out = self._send(side_effect, **kwargs)
        self.assertIs(result, False)
        self.assertNotIn("slacksecret", out)
        self.assertNotIn("Bearer", out)
        return out

    def test_webhook_preferred_when_both_set(self):
        with patch("requests.post", return_value=_response()) as post, _capture():
            self.assertTrue(SlackChannel(WEBHOOK, token=SLACK_TOKEN).send("hi"))
        post.assert_called_once()
        self.assertEqual(post.call_args.args[0], WEBHOOK)

    def test_token_from_env(self):
        with patch.dict(os.environ, {"SLACK_WEBHOOK_URL": "", "SLACK_BOT_TOKEN": "", "SLACK_TOKEN": SLACK_TOKEN}), \
                patch("requests.post", side_effect=_api(**{"auth.test": AUTH_OK, "chat.postMessage": POST_OK})), \
                _capture():
            self.assertTrue(SlackChannel().send("hi"))

    def test_posts_to_own_dm_from_auth_test(self):
        result, post, out = self._send(_api(**{"auth.test": AUTH_OK, "chat.postMessage": POST_OK}))
        self.assertIs(result, True)
        self.assertIn("Slack notification sent successfully.", out)
        self.assertEqual([c.args[0] for c in post.call_args_list],
                         ["https://slack.com/api/auth.test", "https://slack.com/api/chat.postMessage"])
        last = post.call_args_list[-1]
        self.assertEqual(last.kwargs["json"], {"channel": "U123", "text": "hi"})
        for call in post.call_args_list:
            self.assertEqual(call.kwargs["headers"]["Authorization"], f"Bearer {SLACK_TOKEN}")
            self.assertEqual(call.kwargs["timeout"], REQUEST_TIMEOUT)
        self.assertNotIn("slacksecret", out)

    def test_channel_argument_skips_auth_test(self):
        result, post, _ = self._send(_api(**{"chat.postMessage": POST_OK}), channel="C999")
        self.assertIs(result, True)
        post.assert_called_once()
        self.assertEqual(post.call_args.kwargs["json"]["channel"], "C999")

    def test_channel_from_env_skips_auth_test(self):
        with patch.dict(os.environ, {"SLACK_WEBHOOK_URL": "", "SLACK_BOT_TOKEN": "", "SLACK_NOTIFY_CHANNEL": "C777"}), \
                patch("requests.post", side_effect=_api(**{"chat.postMessage": POST_OK})) as post, _capture():
            self.assertTrue(SlackChannel(token=SLACK_TOKEN).send("hi"))
        self.assertEqual(post.call_args.kwargs["json"]["channel"], "C777")

    def test_empty_channel_env_means_own_dm(self):
        result, post, _ = self._send(_api(**{"auth.test": AUTH_OK, "chat.postMessage": POST_OK}))
        self.assertEqual(post.call_count, 2)

    def test_missing_scope_explains_the_fix(self):
        missing = _response(json_body={"ok": False, "error": "missing_scope",
                                       "needed": "chat:write", "provided": "identify,users:write"})
        out = self._failure(_api(**{"auth.test": AUTH_OK, "chat.postMessage": missing}))
        self.assertIn("Slack notification failed: the token lacks the chat:write scope "
                      "(Slack says it needs: chat:write). Add it under User Token Scopes in the "
                      "Slack app, reinstall the app, and put the new token in SLACK_TOKEN.", out)

    def test_plain_messages_for_known_errors(self):
        for error, fragment in (("invalid_auth", "SLACK_TOKEN"), ("not_authed", "SLACK_TOKEN"),
                                ("token_revoked", "revoked"), ("channel_not_found", "SLACK_NOTIFY_CHANNEL")):
            with self.subTest(error=error):
                bad = _response(json_body={"ok": False, "error": error})
                out = self._failure(_api(**{"auth.test": AUTH_OK, "chat.postMessage": bad}))
                self.assertIn(fragment, out)

    def test_other_error_prints_the_code(self):
        bad = _response(json_body={"ok": False, "error": "is_archived"})
        out = self._failure(_api(**{"auth.test": AUTH_OK, "chat.postMessage": bad}))
        self.assertIn("is_archived", out)

    def test_auth_test_ok_false_fails_without_posting(self):
        bad = _response(json_body={"ok": False, "error": "invalid_auth"})
        result, post, out = self._send(_api(**{"auth.test": bad}))
        self.assertIs(result, False)
        post.assert_called_once()
        self.assertIn("SLACK_TOKEN", out)

    def test_non_json_body_is_a_failure(self):
        html = _response(200, "<html>oops</html>")
        html.json.side_effect = ValueError("no json")
        out = self._failure(_api(**{"auth.test": AUTH_OK, "chat.postMessage": html}))
        self.assertIn("non-JSON", out)

    def test_http_500_is_a_failure(self):
        out = self._failure(_api(**{"auth.test": AUTH_OK,
                                    "chat.postMessage": _response(500, "boom", json_body={"ok": True})}))
        self.assertIn("500", out)

    def test_connection_error_on_auth_test(self):
        err = requests.ConnectionError(f"Max retries exceeded, token {SLACK_TOKEN}")
        out = self._failure(err)
        self.assertIn("ConnectionError", out)

    def test_connection_error_on_post_message(self):
        err = requests.ConnectionError(f"Max retries exceeded, token {SLACK_TOKEN}")

        def fake(url, **kwargs):
            if url.endswith("auth.test"):
                return AUTH_OK
            raise err
        out = self._failure(fake)
        self.assertIn("ConnectionError", out)

    def test_token_echoed_by_slack_is_scrubbed(self):
        bad = _response(json_body={"ok": False, "error": f"weird_{SLACK_TOKEN}"})
        self._failure(_api(**{"auth.test": AUTH_OK, "chat.postMessage": bad}))


class TestSlackBot(unittest.TestCase):

    def _send(self, side_effect, token=SLACK_TOKEN, **kwargs):
        with patch.dict(os.environ, {"SLACK_WEBHOOK_URL": "", "SLACK_NOTIFY_CHANNEL": ""}), \
                patch("requests.post", side_effect=side_effect) as post, _capture() as out:
            result = SlackChannel(token=token, bot_token=BOT_TOKEN, **kwargs).send("hi")
        return result, post, out.getvalue()

    def _failure(self, side_effect, **kwargs):
        result, post, out = self._send(side_effect, **kwargs)
        self.assertIs(result, False)
        for secret in ("slacksecret", "botsecret", "Bearer"):
            self.assertNotIn(secret, out)
        return out

    def test_bot_preferred_over_user_token(self):
        result, post, out = self._send(_api(**{"auth.test": AUTH_OK, "chat.postMessage": POST_OK}))
        self.assertIs(result, True)
        self.assertIn("Slack notification sent successfully.", out)

    def test_auth_test_uses_user_token_and_post_uses_bot_token(self):
        _, post, _ = self._send(_api(**{"auth.test": AUTH_OK, "chat.postMessage": POST_OK}))
        self.assertEqual([c.args[0] for c in post.call_args_list],
                         ["https://slack.com/api/auth.test", "https://slack.com/api/chat.postMessage"])
        auth, posted = post.call_args_list
        self.assertEqual(auth.kwargs["headers"]["Authorization"], f"Bearer {SLACK_TOKEN}")
        self.assertEqual(posted.kwargs["headers"]["Authorization"], f"Bearer {BOT_TOKEN}")
        self.assertEqual(posted.kwargs["json"], {"channel": "U123", "text": "hi"})
        for call in post.call_args_list:
            self.assertEqual(call.kwargs["timeout"], REQUEST_TIMEOUT)

    def test_bot_token_from_env(self):
        with patch.dict(os.environ, {"SLACK_WEBHOOK_URL": "", "SLACK_NOTIFY_CHANNEL": "C1",
                                     "SLACK_BOT_TOKEN": BOT_TOKEN, "SLACK_TOKEN": ""}), \
                patch("requests.post", side_effect=_api(**{"chat.postMessage": POST_OK})) as post, _capture():
            self.assertTrue(SlackChannel().send("hi"))
        self.assertEqual(post.call_args.kwargs["headers"]["Authorization"], f"Bearer {BOT_TOKEN}")

    def test_notify_channel_skips_auth_test(self):
        result, post, _ = self._send(_api(**{"chat.postMessage": POST_OK}), channel="C999")
        self.assertIs(result, True)
        post.assert_called_once()
        self.assertEqual(post.call_args.kwargs["json"]["channel"], "C999")
        self.assertEqual(post.call_args.kwargs["headers"]["Authorization"], f"Bearer {BOT_TOKEN}")

    def test_notify_channel_alone_needs_no_user_token(self):
        result, post, _ = self._send(_api(**{"chat.postMessage": POST_OK}), token="", channel="U55")
        # token="" falls back to the env, so make sure the env has none:
        self.assertIs(result, True)

    def test_nobody_to_send_to_fails_without_a_request(self):
        with patch.dict(os.environ, {"SLACK_WEBHOOK_URL": "", "SLACK_NOTIFY_CHANNEL": "", "SLACK_TOKEN": ""}), \
                patch("requests.post") as post, _capture() as out:
            result = SlackChannel(bot_token=BOT_TOKEN).send("hi")
        self.assertIs(result, False)
        post.assert_not_called()
        self.assertIn("Slack notification failed: SLACK_BOT_TOKEN is set but there is nobody to send to; "
                      "set SLACK_NOTIFY_CHANNEL to your Slack user ID (or a channel ID), "
                      "or set SLACK_TOKEN.", out.getvalue())
        self.assertNotIn("botsecret", out.getvalue())

    def test_webhook_wins_over_both_tokens(self):
        with patch("requests.post", return_value=_response()) as post, _capture():
            self.assertTrue(SlackChannel(WEBHOOK, token=SLACK_TOKEN, bot_token=BOT_TOKEN).send("hi"))
        post.assert_called_once()
        self.assertEqual(post.call_args.args[0], WEBHOOK)

    def test_bot_missing_scope_names_bot_token_scopes(self):
        missing = _response(json_body={"ok": False, "error": "missing_scope", "needed": "chat:write"})
        out = self._failure(_api(**{"auth.test": AUTH_OK, "chat.postMessage": missing}))
        self.assertIn("Slack notification failed: the bot token lacks the chat:write scope "
                      "(Slack says it needs: chat:write). Add chat:write under Bot Token Scopes in the "
                      "Slack app, reinstall the app, and put the new Bot User OAuth Token (xoxb-...) "
                      "in SLACK_BOT_TOKEN.", out)

    def test_auth_test_missing_scope_is_generic_and_names_slack_token(self):
        missing = _response(json_body={"ok": False, "error": "missing_scope", "needed": "identify"})
        result, post, out = self._send(_api(**{"auth.test": missing}))
        self.assertIs(result, False)
        post.assert_called_once()
        self.assertIn("SLACK_TOKEN lacks a scope needed to find your user ID "
                      "(Slack says it needs: identify)", out)
        self.assertNotIn("Bot Token Scopes", out)

    def test_not_in_channel_hint(self):
        bad = _response(json_body={"ok": False, "error": "not_in_channel"})
        out = self._failure(_api(**{"chat.postMessage": bad}), channel="C1")
        self.assertIn("the app is not in that channel; invite it, or use your user ID in "
                      "SLACK_NOTIFY_CHANNEL", out)

    def test_invalid_bot_token_names_bot_variable(self):
        bad = _response(json_body={"ok": False, "error": "invalid_auth"})
        out = self._failure(_api(**{"auth.test": AUTH_OK, "chat.postMessage": bad}))
        self.assertIn("Check SLACK_BOT_TOKEN.", out)

    def test_no_token_in_output_for_any_failure(self):
        both = f"Max retries exceeded, tokens {SLACK_TOKEN} {BOT_TOKEN}"
        html = _response(200, f"<html>{SLACK_TOKEN} {BOT_TOKEN}</html>")
        html.json.side_effect = ValueError("no json")

        def net_on(method):
            def fake(url, **kwargs):
                if url.endswith(method):
                    raise requests.ConnectionError(both)
                return {"auth.test": AUTH_OK, "chat.postMessage": POST_OK}[url.rsplit("/", 1)[1]]
            return fake
        cases = {
            "network auth.test": net_on("auth.test"),
            "network postMessage": net_on("chat.postMessage"),
            "non-json": _api(**{"auth.test": AUTH_OK, "chat.postMessage": html}),
            "http 500": _api(**{"auth.test": AUTH_OK,
                                "chat.postMessage": _response(500, f"{BOT_TOKEN}", json_body={"ok": True})}),
            "ok false": _api(**{"auth.test": AUTH_OK, "chat.postMessage": _response(
                json_body={"ok": False, "error": f"weird_{BOT_TOKEN}_{SLACK_TOKEN}"})}),
            "auth ok false": _api(**{"auth.test": _response(
                json_body={"ok": False, "error": f"weird_{SLACK_TOKEN}"})}),
        }
        for name, fake in cases.items():
            with self.subTest(name):
                self._failure(fake)


class TestManager(unittest.TestCase):

    def _channel(self, name, result):
        ch = MagicMock()
        ch.name = name
        if isinstance(result, Exception):
            ch.send.side_effect = result
        else:
            ch.send.return_value = result
        return ch

    def test_one_raising_channel_does_not_stop_the_others(self):
        a = self._channel("a", RuntimeError("boom"))
        b = self._channel("b", True)
        manager = NotificationManager()
        manager.register_channel(a)
        manager.register_channel(b)
        with _capture() as out:
            failed = manager.notify("msg")
        b.send.assert_called_once_with("msg")
        self.assertEqual(failed, ["a"])
        self.assertIn("RuntimeError", out.getvalue())

    def test_returns_names_of_channels_that_returned_false(self):
        manager = NotificationManager()
        for ch in (self._channel("a", False), self._channel("b", True), self._channel("c", False)):
            manager.register_channel(ch)
        self.assertEqual(manager.notify("m"), ["a", "c"])

    def test_no_channels_no_failures(self):
        self.assertEqual(NotificationManager().notify("m"), [])

    def test_real_channels_all_failing_never_raise(self):
        manager = NotificationManager()
        manager.register_channel(TelegramChannel(TOKEN, "1"))
        manager.register_channel(SlackChannel(WEBHOOK))
        with patch("requests.post", side_effect=requests.ConnectionError("x")), _capture():
            self.assertEqual(manager.notify("m"), ["telegram", "slack"])


class TestSlackStatus(unittest.TestCase):

    def _set(self, **post_kwargs):
        with patch("requests.post", **post_kwargs) as post, _capture() as out:
            result = SlackStatusUpdater(SLACK_TOKEN).set_status("t", ":x:", 5)
        return result, post, out.getvalue()

    def test_ok(self):
        result, post, _ = self._set(return_value=_response(json_body={"ok": True}))
        self.assertIs(result, True)
        self.assertEqual(post.call_args.kwargs["timeout"], REQUEST_TIMEOUT)
        self.assertEqual(post.call_args.kwargs["json"]["profile"]["status_expiration"], 5)

    def test_ok_false_returns_false(self):
        result, _, out = self._set(return_value=_response(text='{"ok":false,"error":"invalid_auth"}',
                                                          json_body={"ok": False}))
        self.assertIs(result, False)
        self.assertIn("invalid_auth", out)

    def test_non_json_response_returns_false(self):
        r = _response(500, "<html>")
        r.json.side_effect = ValueError("no json")
        result, _, _ = self._set(return_value=r)
        self.assertIs(result, False)

    def test_network_error_returns_false_and_never_prints_token(self):
        err = requests.ConnectionError(f"boom {SLACK_TOKEN}")
        result, _, out = self._set(side_effect=err)
        self.assertIs(result, False)
        self.assertNotIn("slacksecret", out)
        self.assertIn("ConnectionError", out)

    def test_authorization_header_is_never_printed(self):
        _, _, out = self._set(return_value=_response(json_body={"ok": True}))
        self.assertNotIn("Bearer", out)
        self.assertNotIn("slacksecret", out)

    def test_missing_token_raises_value_error(self):
        with patch.dict(os.environ, {"SLACK_TOKEN": ""}):
            with self.assertRaises(ValueError):
                SlackStatusUpdater()


class TestEnvCheck(unittest.TestCase):

    def test_enabled_returns(self):
        with patch.dict(os.environ, {"EPORTEM_ENABLED": "YES"}):
            self.assertIsNone(env_check.check_env_variable())

    def test_not_enabled_exits_non_zero(self):
        for value in ("NO", "yes", ""):
            with self.subTest(value=value), patch.dict(os.environ, {"EPORTEM_ENABLED": value}):
                with self.assertRaises(SystemExit) as cm:
                    env_check.check_env_variable()
                self.assertIn("EPORTEM_ENABLED", str(cm.exception.code))

    def test_unset_exits_non_zero(self):
        with patch.dict(os.environ):
            os.environ.pop("EPORTEM_ENABLED", None)
            with self.assertRaises(SystemExit):
                env_check.check_env_variable()


if __name__ == '__main__':
    unittest.main()
