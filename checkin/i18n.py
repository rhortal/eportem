"""The languages CheckIn speaks: one JSON catalogue per language in
checkin/locales/, named by its code (en.json, es.json, ca.json...).

Keys are message ids: the English text for UI copy, or a code such as
`start_day` or `not_recorded` for the values the service stores. en.json holds
every id and is the template for a new language: copy it to `<code>.json`, set
`_language` to the language's own name and translate the values. Nothing else
changes; the language then shows up in the profile, is accepted by the API and
`default_locale`, and is picked from the browser's Accept-Language. The tests
fail while any catalogue lacks an id that en.json has (see README, Languages).

A missing entry falls back to English, so a page never shows a raw id.
"""
import json
from pathlib import Path

LOCALES_DIR = Path(__file__).resolve().parent / "locales"
SOURCE = "en"


def _load(directory=LOCALES_DIR):
    catalogues = {}
    for path in sorted(directory.glob("*.json")):
        catalogues[path.stem] = json.loads(path.read_text(encoding="utf-8"))
    return catalogues


CATALOGUES = _load()
# code -> the language's own name, for the language picker
LANGUAGES = {code: cat["_language"] for code, cat in CATALOGUES.items()}


def messages(locale):
    """The ids and texts of one language, without `_language`."""
    return {k: v for k, v in CATALOGUES.get(locale, {}).items() if not k.startswith("_")}


def pick_locale(user, accept_language, default):
    if user is not None and user.locale in LANGUAGES:
        return user.locale
    for part in (accept_language or "").split(","):
        code = part.split(";")[0].strip()[:2].lower()
        if code in LANGUAGES:
            return code
    return default if default in LANGUAGES else SOURCE


def translator(locale):
    table, english = CATALOGUES.get(locale, {}), CATALOGUES[SOURCE]

    def t(text, **kw):
        out = table.get(text) or english.get(text, text)
        return out.format(**kw) if kw else out
    return t
