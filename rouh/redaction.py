"""Keeping credentials out of logs and error messages.

Two habits, because one is not enough.

1. Nothing in this repository passes a secret to a log call. That is the real
   rule and it is enforced by review and by the tests in
   `test_google_secrets.py`.
2. This module is the net under it. Google's credentials all have shapes that
   nothing else has - an access token starts ``ya29.``, a refresh token
   ``1//``, a client secret ``GOCSPX-`` - so a line that carries one can be
   recognised and masked wherever it came from, including from inside a
   library that knows nothing about any of this.

`scrub` is also used on anything Google itself says back, because an error body
from an OAuth endpoint frequently quotes the request that caused it.
"""
from __future__ import annotations

import logging
import re

#: What a masked secret looks like. Short, and obviously deliberate, so nobody
#: reading a log wonders whether the value really was "[redacted]".
MASK = "[redacted]"

#: The shapes Google's own credentials come in, plus the two field names used
#: when one is being carried as JSON or as a form.
PATTERNS: tuple[re.Pattern[str], ...] = (
    # Google client secrets, current form and the older one.
    re.compile(r"GOCSPX-[A-Za-z0-9_\-]{6,}"),
    # Access tokens.
    re.compile(r"ya29\.[A-Za-z0-9_\-\.]{10,}"),
    # Refresh tokens.
    re.compile(r"1//[A-Za-z0-9_\-]{10,}"),
    # A Telegram bot token, which is the bot's number, a colon and 35 random
    # characters. It is here because Telegram puts the key in the address
    # rather than in a header, and httpx logs every address it calls at INFO:
    # on 14 September 2026 the one program's first phone message wrote its
    # key straight into its own log that way (see `one/program.py`). Nothing
    # in `rouh/telegram.py` logs a URL, and this is the net under that.
    re.compile(r"(?<![0-9])\d{6,12}:AA[A-Za-z0-9_\-]{30,}"),
    # An Apify token, which is what reaches HarvestAPI's LinkedIn scrapers
    # (`rouh/linkedin.py`). It goes in a header there and never in an address;
    # this is the net under that.
    re.compile(r"apify_api_[A-Za-z0-9]{8,}"),
    # A key carried in an address, as Google's APIs take one (`?key=AIza...`): httpx logs every
    # address it calls at INFO, and YouTube's search sends its key that way (`rouh/youtube.py`).
    re.compile(r"([?&](?:key|api_key|token|access_token)=)(?!\[redacted\])([^&\s\"']{6,})"),
    # An Apple app-specific password: sixteen lower-case letters in four
    # groups of four (`rouh/apple_contacts.py`). And the Basic authorisation
    # header CardDAV carries it in, which is the same password in base64.
    re.compile(r"(?<![A-Za-z-])[a-z]{4}-[a-z]{4}-[a-z]{4}-[a-z]{4}(?![A-Za-z-])"),
    re.compile(r"(?i)(?<=basic )[A-Za-z0-9+/]{12,}={0,2}"),
    # A named field carrying one, however it is quoted: JSON, a form body, a
    # Python dict printed by an exception. The look-behind is what keeps
    # "status_code=200" and "error_code: 5" readable: only the field itself
    # counts, not a longer word that happens to end in it.
    re.compile(
        r"((?<![A-Za-z0-9_-])(?:client_secret|refresh_token|access_token|id_token|code"
        r"|app_password|password)"
        r"['\"]?\s*[=:]\s*['\"]?)(?!\[redacted\])([^\s,&'\"}\]]{6,})"
    ),
)


#: Every secret this Rouh keeps for a service in Settings, Keys, by its exact text, whatever its
#: shape (`rouh/service_keys.py` gives them here each time they change): the net under the rule
#: that no value is ever passed to a log call.
_HELD: frozenset = frozenset()


def hold(values) -> None:
    """These exact values are masked wherever they appear from now on (and only these)."""
    global _HELD
    _HELD = frozenset(v for v in values if v and len(v) >= 8)


def scrub(text: str) -> str:
    """The same text with anything credential-shaped masked."""
    if not text:
        return text
    out = str(text)
    for held in _HELD:
        if held in out:
            out = out.replace(held, MASK)
    for pattern in PATTERNS:
        if pattern.groups == 2:
            out = pattern.sub(lambda m: m.group(1) + MASK, out)
        else:
            out = pattern.sub(MASK, out)
    return out


class Scrubbing(logging.Filter):
    """A filter that masks credentials in every line that passes through it."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            record.msg = scrub(record.getMessage())
            record.args = ()
        except Exception:      # a record that cannot be formatted is not ours to fix
            pass
        return True


def guard_logging() -> None:
    """Put the filter on every handler the root logger writes through.

    Called once from `runtime.py`, after logging is configured. A filter on a
    handler sees every record that reaches it, wherever it was logged from,
    which is what is wanted here: a line from inside httpx is exactly the kind
    this is meant to catch. A filter on the logger itself would only see what
    was logged through that logger, so both are set.
    """
    scrubbing = Scrubbing()
    root = logging.getLogger()
    if not any(isinstance(f, Scrubbing) for f in root.filters):
        root.addFilter(scrubbing)
    for handler in root.handlers:
        if not any(isinstance(f, Scrubbing) for f in handler.filters):
            handler.addFilter(scrubbing)
