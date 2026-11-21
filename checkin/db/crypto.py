"""Encryption of stored secrets (ePortem passwords, session cookies, Slack and
Telegram tokens) with the instance's secret key (D-005).

Old keys are still accepted for reading, so a key can be rotated:
add the new key as CHECKIN_SECRET_KEY, move the old one to
CHECKIN_OLD_SECRET_KEYS, run `python -m checkin rotate-key`, then drop it.
"""
import json

from cryptography.fernet import Fernet, InvalidToken, MultiFernet


class SecretBox:
    def __init__(self, key, old_keys=()):
        self._fernet = MultiFernet([Fernet(k) for k in (key, *old_keys)])

    @classmethod
    def from_settings(cls, settings):
        return cls(settings.secret_key.get_secret_value(),
                   [k.get_secret_value() for k in settings.old_secret_keys])

    def encrypt(self, text):
        return self._fernet.encrypt(text.encode("utf-8")).decode("ascii")

    def decrypt(self, token):
        try:
            return self._fernet.decrypt(token.encode("ascii")).decode("utf-8")
        except InvalidToken as e:
            raise ValueError("cannot decrypt a stored secret: wrong CHECKIN_SECRET_KEY?") from e

    def encrypt_json(self, value):
        return self.encrypt(json.dumps(value))

    def decrypt_json(self, token):
        return json.loads(self.decrypt(token))

    def rotate(self, token):
        """Re-encrypt with the current key."""
        return self._fernet.rotate(token.encode("ascii")).decode("ascii")
