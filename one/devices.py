"""Who is talking to the program: devices, each paired once and revocable from any other.

Step 07, section 7, asks for three things and only three: one person; several
devices, each paired once at a real keyboard and revocable from any other; and
one field on every entry saying which device. Deliberately absent: a password
per surface, roles, sharing.

**A device** is a name, the surface it is (terminal, browser, voice), and a
token it presents when it connects. The list keeps only the token's SHA-256,
never the token: the list is plain text anyone with the files can read.

**Pairing** happens at a real keyboard:

* A terminal on the server itself, over the program's own socket, is trusted
  because only root and the program's own user can open that socket, and
  reaching it means having logged in to the machine. From there ``one pair``
  makes a device and prints its token once.
* A browser pairs with a six-digit code that a paired terminal asks for. The
  code lasts ten minutes and works once, and it lives only in the program's
  memory, never in the list. Wrong codes are counted, and after ten in ten
  minutes pairing is closed until the ten minutes have passed, so a code
  cannot be found by trying them all.
"""
from __future__ import annotations

import hashlib
import re
import secrets
import time
from dataclasses import dataclass
from typing import Callable

CODE_TTL = 600.0
MAX_WRONG = 10
WRONG_WINDOW = 600.0


def new_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def new_device_id(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (name or "device").lower()).strip("-")[:20] or "device"
    return f"{slug}-{secrets.token_hex(3)}"


@dataclass
class Code:
    code: str
    surface: str
    name: str
    by: str
    expires: float


class Pairing:
    """Six-digit pairing codes, in memory only."""

    def __init__(self, clock: Callable[[], float] = time.time) -> None:
        self._clock = clock
        self._codes: dict[str, Code] = {}
        self._wrong: list[float] = []

    def issue(self, *, surface: str, name: str, by: str) -> Code:
        now = self._clock()
        self._expire(now)
        while True:
            code = f"{secrets.randbelow(10 ** 6):06d}"
            if code not in self._codes:
                break
        issued = Code(code=code, surface=surface, name=name, by=by, expires=now + CODE_TTL)
        self._codes[code] = issued
        return issued

    def closed(self) -> bool:
        now = self._clock()
        self._wrong = [t for t in self._wrong if now - t < WRONG_WINDOW]
        return len(self._wrong) >= MAX_WRONG

    def redeem(self, code: str) -> Code | None:
        """The code's details if it is right and fresh, once. None otherwise."""
        now = self._clock()
        self._expire(now)
        if self.closed():
            return None
        found = self._codes.pop((code or "").strip(), None)
        if found is None:
            self._wrong.append(now)
            return None
        return found

    def _expire(self, now: float) -> None:
        for code in [c for c, v in self._codes.items() if v.expires <= now]:
            del self._codes[code]
