"""The code in an email: an opened email that carries a sign-in or confirmation code shows it, with Copy.

Built by the nightly feature run, night 48 of the ledger (19 November 2026, task 94).
Sign-in codes, confirmation codes and one-time passwords come by email several times a week, and
the one thing wanted from such an email is the code: on the inbox card it had to be found among the
service's words and selected by hand, on a phone too, while the page that asked for it waited.

So, while its switch is on, a message opened on the inbox card (Rouh's own inbox or the person's
read-only one) that says it carries a code ("your verification code", "one-time password", "sign-in
code", "код за потвърждение", ...) and was sent in the last `FRESH_HOURS` hours has one more row
at the top: the service, the code in large figures, how long it is good for when the email says
("expires in 10 minutes", and "probably expired" once that has passed), and **Copy the code**. The
code is read in plain rules, no model: the figures after the words that name it, or a line that is
the code alone. Nothing is kept: the code is read from the message each time it is opened, the press
only puts it on the person's own clipboard and is counted, and the code is never sent anywhere.

**Whose.** The opened message, in the person's own inbox card, by `org_id` and `user_id`.

**Its switch** is `mail_code` (`rouh/switches.py`): off, the card has no such row.
"""
from __future__ import annotations

import logging
import re
import time

log = logging.getLogger("rouh.mail_code")

SWITCH = "mail_code"
TITLE = "The code in an email: an opened email carrying a sign-in or confirmation code shows it with Copy the code"
#: An email older than this carries a code nobody can use any more.
FRESH_HOURS = 24

#: The email says it carries a code.
CUE = re.compile(
    r"\b(?:verification|confirmation|security|sign[- ]?in|log[- ]?in|login|one[- ]time|access|authentication"
    r"|auth|2fa|two[- ]factor|single[- ]use|temporary|magic)\s+(?:code|pin|passcode|password)\b"
    r"|\b(?:your|the|enter (?:this|the)?)\s+code\b|\bpasscode\b|\bOTP\b|\bcode (?:is|:)"
    r"|код(?:ът)? за (?:потвърждение|вход|достъп|верификация)|еднократ\w+ (?:код|парола)|вашият код",
    re.I)
#: The figures after the words that name it: "code is 482913", "code: 482 913", "PIN 4821".
_NAMED = re.compile(
    r"(?:code|pin|passcode|password|OTP|код|парола)(?:ът)?\b[^\n\d]{0,30}?"
    r"(?P<code>(?<![\w-])(?:\d{3}[ -]\d{3}|\d{4,8}|[A-Z]{1,3}-\d{4,8}|(?=[A-Z0-9]*\d)(?=[A-Z0-9]*[A-Z])[A-Z0-9]{6,8})(?![\w-]))",
    re.I)
#: A line that is the code alone, as most services set it in large figures.
_ALONE = re.compile(r"^[ \t>*_]*(?P<code>\d{4,8}|\d{3}[ -]\d{3}|(?=[A-Z0-9]*\d)(?=[A-Z0-9]*[A-Z])[A-Z0-9]{6,8})"
                    r"[ \t*_]*$", re.M)
_LASTS = re.compile(
    r"\b(?:expires?|valid|good|active|works?)\s+(?:in|for)\s+(?:the next\s+)?(?P<n>\d{1,3})\s*"
    r"(?P<unit>min(?:ute)?s?|hours?|hrs?)\b|валиден (?:за|в рамките на) (?P<bn>\d{1,3}) (?P<bunit>мин|час)", re.I)


def on(who) -> bool:
    from . import switches

    if who is None:
        return False
    return switches.on(SWITCH, getattr(who, "org_id", None) or None)


def _plausible(code: str) -> bool:
    digits = re.sub(r"\D", "", code)
    if code.isdigit() and len(code) == 4 and 1900 <= int(code) <= 2100:
        return False  # a year, not a code
    return bool(digits) and len(set(digits)) > 1 or len(code) > 6


def code_of(subject: str, body: str) -> str:
    """The code the email carries, or "" when it names none."""
    text = f"{subject or ''}\n{body or ''}"
    if not CUE.search(text):
        return ""
    for hit in _NAMED.finditer(text):
        code = hit.group("code")
        if _plausible(code):
            return code
    for hit in _ALONE.finditer(body or ""):
        code = hit.group("code")
        if _plausible(code):
            return code
    return ""


def minutes_of(text: str) -> int:
    """How long the email says the code is good for, in minutes, or 0."""
    hit = _LASTS.search(text or "")
    if not hit:
        return 0
    n = int(hit.group("n") or hit.group("bn") or 0)
    unit = (hit.group("unit") or hit.group("bunit") or "").lower()
    return n * 60 if unit.startswith(("h", "ч")) else n


def shown(who, found: dict, now: float | None = None) -> dict | None:
    """What the opened message's row says, or None."""
    from . import renewal_notice

    if not on(who):
        return None
    sent = float(found.get("at") or 0)
    now = time.time() if now is None else now
    if sent and now - sent > FRESH_HOURS * 3600:
        return None
    code = code_of(str(found.get("subject") or ""), str(found.get("body") or ""))
    if not code:
        return None
    service = renewal_notice.service_of(str(found.get("from") or ""))
    lasts = minutes_of(str(found.get("body") or ""))
    said = f"Your {service} code"
    gone = bool(lasts and sent and now - sent > lasts * 60)
    if lasts:
        said += (f", good for {lasts} minutes from when it came: it has probably expired" if gone
                 else f", good for {lasts} minutes from when it came")
    return {"said": said, "code": code, "copy": re.sub(r"[ -]", "", code) if re.fullmatch(r"\d{3}[ -]\d{3}", code)
            else code, "service": service, "expired": gone}


def copied(who, service: str = "") -> None:
    """Copy the code pressed: counted, nothing else."""
    from . import evolution

    log.info("the code in an email: copied")
    evolution.used(SWITCH, "copied", who=who, detail=str(service or "")[:60])


__all__ = ["CUE", "FRESH_HOURS", "SWITCH", "TITLE", "code_of", "copied", "minutes_of", "on", "shown"]
