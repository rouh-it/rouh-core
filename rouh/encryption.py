"""Encrypting the credentials Rouh holds on someone else's behalf.

Two kinds of secret end up in Rouh's database and neither may sit there in
plain text:

- an organisation's Google OAuth **client secret**, typed in once by that
  organisation's administrator,
- every user's Google **refresh token** and access token.

Both are sealed with Fernet, which is AES-128 in CBC with an HMAC-SHA256 over
the ciphertext: authenticated, so a row edited by hand fails to open rather
than decrypting to something else, and timestamped, so a token can be aged out
later if that is ever wanted.

Where the key comes from
------------------------

``ROUH_ENCRYPTION_KEY`` in the environment, which on the server is
``/var/www/rouh/.env`` and is never in this repository. If it is not set,
this makes one on first use and writes it beside the database as ``secret.key``
with mode 0600, so a single-machine install works without anyone doing
operations work first. That is weaker - a key next to the file it protects is
only as safe as the file permissions around it - so which of the two is in use
is reported by ``key_source`` and said out loud in the logs once.

The key never leaves this module, is never logged, and is never in an API
response. Neither is anything it opens.
"""
from __future__ import annotations

import base64
import logging
import os
import threading

log = logging.getLogger("rouh.encryption")

#: What a key file is called, inside the data directory.
KEY_FILE = "secret.key"


class NotEncryptable(RuntimeError):
    """The cryptography library is missing, so nothing may be stored."""


class CannotOpen(ValueError):
    """The sealed text did not open: a wrong key, or a row that was edited."""


def new_key() -> str:
    """A fresh key, as the text that goes in the environment."""
    return base64.urlsafe_b64encode(os.urandom(32)).decode()


class SecretBox:
    """Seals and opens one instance's secrets.

    Built once and shared. `seal` and `open_` are both safe from several
    threads, which is what Fernet itself guarantees.
    """

    def __init__(self, key: str = "", *, data_dir: str = "") -> None:
        try:
            from cryptography.fernet import Fernet, InvalidToken
        except Exception as exc:  # pragma: no cover - only without the dependency
            raise NotEncryptable(
                "the cryptography package is not installed, so credentials "
                "cannot be stored safely"
            ) from exc
        self._invalid = InvalidToken
        self._lock = threading.Lock()
        key = (key or "").strip()
        if key:
            self.key_source = "environment"
        else:
            key = _key_from_file(data_dir)
            self.key_source = "data directory"
        try:
            self._fernet = Fernet(_as_fernet_key(key))
        except Exception as exc:
            raise NotEncryptable(
                "ROUH_ENCRYPTION_KEY is not a usable key: it must be 32 bytes, "
                "url-safe base64 encoded. Generate one with "
                "`python -c \"import rouh.encryption as e; print(e.new_key())\"`."
            ) from exc

    def seal(self, plain: str) -> str:
        """Plain text in, one line of sealed text out."""
        return self._fernet.encrypt((plain or "").encode()).decode()

    def open_(self, sealed: str) -> str:
        """Sealed text back to plain, or `CannotOpen` if it was not ours."""
        try:
            return self._fernet.decrypt((sealed or "").encode()).decode()
        except self._invalid as exc:
            raise CannotOpen("this was not sealed with this instance's key") from exc


_BOX: SecretBox | None = None
_BOX_LOCK = threading.Lock()


def box() -> SecretBox:
    """This instance's own box, built from its configuration on first use and shared.

    Every part of Rouh that seals with the instance's key asks for this one
    rather than building its own. A test or a world that needs another key
    still builds a `SecretBox` of its own.
    """
    global _BOX
    if _BOX is None:
        with _BOX_LOCK:
            if _BOX is None:
                from .config import config

                _BOX = SecretBox(config.encryption_key, data_dir=config.data_dir)
    return _BOX


def _as_fernet_key(key: str) -> bytes:
    """Accept either a Fernet key or 32 raw bytes written any usual way.

    A person setting this by hand is as likely to paste hex or plain base64 as
    the exact url-safe form Fernet wants, and failing on that is a support call
    rather than a security property.
    """
    raw = key.strip()
    for decode in (base64.urlsafe_b64decode, base64.b64decode):
        try:
            candidate = decode(raw + "=" * (-len(raw) % 4))
        except Exception:
            continue
        if len(candidate) == 32:
            return base64.urlsafe_b64encode(candidate)
    try:
        candidate = bytes.fromhex(raw)
        if len(candidate) == 32:
            return base64.urlsafe_b64encode(candidate)
    except ValueError:
        pass
    raise ValueError("not a 32 byte key")


def _key_from_file(data_dir: str) -> str:
    """The key kept beside the database, made on first use.

    Written with mode 0600 before anything is put in it, so it is never
    readable by anyone else even for an instant.
    """
    if not data_dir:
        raise NotEncryptable(
            "ROUH_ENCRYPTION_KEY is not set and there is nowhere to keep a key"
        )
    os.makedirs(data_dir, exist_ok=True)
    path = os.path.join(data_dir, KEY_FILE)
    try:
        with open(path, encoding="utf-8") as fh:
            existing = fh.read().strip()
        if existing:
            return existing
    except FileNotFoundError:
        pass
    key = new_key()
    handle = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(handle, "w", encoding="utf-8") as fh:
        fh.write(key + "\n")
    log.warning(
        "ROUH_ENCRYPTION_KEY is not set, so a key was made at %s. Move it into "
        "the environment to keep it apart from the database it protects.", path
    )
    return key
