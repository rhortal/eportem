"""The language catalogues in checkin/locales: every language has every
message, with the same {placeholders}, and every text the UI asks for exists."""
import re
import string
import unittest
from pathlib import Path

from checkin import i18n
from checkin.core.schedule import ACTIONS, LOCATIONS
from checkin.core.templates import BUILTIN_TEMPLATES, WEEKDAYS

ROOT = Path(__file__).resolve().parent.parent
LITERAL = re.compile(r"""\bt\(\s*(["'])((?:\\.|(?!\1).)*)\1""")
RUN_STATUSES = ("planned", "running", "recorded", "not_recorded", "unknown", "skipped", "failed", "cancelled",
                "dry_run")
USER_STATUSES = ("pending", "active", "suspended")
MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
          "November", "December")


def fields(text):
    return sorted(name for _, name, _, _ in string.Formatter().parse(text) if name is not None)


class TestCatalogues(unittest.TestCase):

    def test_there_are_english_spanish_and_catalan(self):
        self.assertLessEqual({"en", "es", "ca"}, set(i18n.LANGUAGES))
        self.assertEqual(i18n.LANGUAGES["ca"], "Català")

    def test_every_language_has_every_message_and_no_others(self):
        source = i18n.messages(i18n.SOURCE)
        for code in i18n.LANGUAGES:
            with self.subTest(language=code):
                table = i18n.messages(code)
                self.assertEqual(sorted(set(source) - set(table)), [], "missing")
                self.assertEqual(sorted(set(table) - set(source)), [], "not in en.json")
                for key, text in table.items():
                    self.assertTrue(text.strip(), key)
                    self.assertEqual(fields(text), fields(source[key]), key)

    def test_everything_the_ui_asks_for_is_in_the_catalogue(self):
        source = i18n.messages(i18n.SOURCE)
        files = [*(ROOT / "checkin" / "web" / "templates").glob("*.html"), ROOT / "checkin" / "web" / "ui.py"]
        asked = {m.group(2) for f in files for m in LITERAL.finditer(f.read_text(encoding="utf-8"))}
        asked |= set(ACTIONS) | set(LOCATIONS) | set(RUN_STATUSES) | set(USER_STATUSES) | set(MONTHS)
        asked |= set(WEEKDAYS) | {d[:3] for d in WEEKDAYS}
        asked |= {x for tpl in BUILTIN_TEMPLATES.values() for x in (tpl.name, tpl.description) if x}
        self.assertEqual(sorted(asked - set(source)), [])

    def test_codes_never_show_as_codes(self):
        t = i18n.translator("en")
        self.assertEqual([t(a) for a in ACTIONS], ["Start of day", "Lunch break", "Back from lunch", "End of day"])
        self.assertEqual(t("not_recorded"), "not recorded")
        self.assertEqual(i18n.translator("ca")("start_day"), "Inici de jornada")

    def test_picking_a_language(self):
        class User:
            locale = "ca"
        self.assertEqual(i18n.pick_locale(User(), "es", "en"), "ca")
        self.assertEqual(i18n.pick_locale(None, "ca-ES,ca;q=0.9,es;q=0.8", "en"), "ca")
        self.assertEqual(i18n.pick_locale(None, "fr-FR", "es"), "es")
        self.assertEqual(i18n.pick_locale(None, None, "xx"), "en")

    def test_a_missing_entry_falls_back_to_english_then_to_the_id(self):
        self.assertEqual(i18n.translator("xx")("stop_day"), "End of day")
        self.assertEqual(i18n.translator("es")("no such text"), "no such text")
        self.assertEqual(i18n.translator("en")("used {when}", when="today"), "used today")
