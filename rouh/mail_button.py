"""The button in an email: confirm, verify, reset or accept, pressed from the inbox card.

Built by the nightly feature run, night 49 of the ledger (20 November 2026, task 94).
"Confirm your email address", "Reset your password", "You have been invited to join", "Your
sign-in link": a service's email of that kind wants one press of one link, set among its logo, its
words and its footer. On the inbox card it had to be found and pressed in the drawn email, on a
phone too. And the same shape of email is the one a fake one copies, with a link to somewhere else.

So, while its switch is on, a message opened on the inbox card (Rouh's own inbox or the person's
read-only one) from the last `FRESH_HOURS` hours that asks for one such press has one more row at
the top: what it is ("Confirm your email at Acme"), the address it opens, and the button itself.
The link is read in plain rules, no model: the email's own button or link whose words or address
name that step. It is offered only when it goes to the sender's own domain (a link from
mail.acme.com to acme.com is; one to acme-login.example or through a click counter is not), so a
link elsewhere is never put one press away. Nothing is kept, and the press is only counted.

**Whose.** The opened message, in the person's own inbox card, by `org_id` and `user_id`.

**Its switch** is `mail_button` (`rouh/switches.py`): off, the card has no such row.
"""
from __future__ import annotations

import email.utils
import html
import logging
import re
import time
import urllib.parse

log = logging.getLogger("rouh.mail_button")

SWITCH = "mail_button"
TITLE = "The button in an email: confirm, verify, reset or accept, pressed from the inbox card"
FRESH_HOURS = 48

#: Each step, the words that ask for it, the words a button for it says, and what its address may hold.
STEPS = (
    ("Confirm your email", r"\b(?:confirm|verify|validate) (?:your )?(?:e-?mail|email address|account|registration|sign[- ]?up|subscription)\b"
     r"|потвърд\w+ (?:на )?(?:имейл|акаунт|регистрация)",
     r"confirm|verify|validate|потвърд", r"confirm|verif|validat|activate"),
    ("Activate your account", r"\bactivate (?:your )?account\b|активир\w+ (?:на )?(?:акаунт|профил)",
     r"activate|активир", r"activat"),
    ("Reset your password", r"\breset (?:your )?password\b|\bpassword reset\b|\bchoose a new password\b"
     r"|нова парола|смяна на парола|възстановяване на парола",
     r"reset|new password|change password|парола", r"reset|password|recover"),
    ("Accept the invitation", r"\b(?:invited you to (?:join|collaborate)|you(?:'ve| have) been invited|accept (?:the |your |this )?invit\w*"
     r"|join (?:the |your |our )?(?:team|workspace|organi[sz]ation|project|board))\b|покан\w+ (?:да се присъедините|в)",
     r"accept|join|приеми|присъедин", r"invit|accept|join"),
    ("Sign in", r"\b(?:sign[- ]in|log[- ]?in|magic) link\b|\b(?:click|tap|press) (?:the |this )?(?:button|link) (?:below )?to (?:sign|log) in\b"
     r"|\bsign in to\b.*\bwith (?:this|the) link\b|линк за вход",
     r"sign in|log in|login|вход", r"magic|login|signin|sign-in|auth|session"),
    ("Approve the sign-in", r"\b(?:was this you|approve (?:this |the )?sign[- ]?in|confirm (?:it was|it's) you)\b",
     r"yes|approve|it was me|it's me|this was me|потвърди", r"approve|confirm|verify|device"),
)
_ANCHOR = re.compile(r"<a\b[^>]*?href\s*=\s*[\"'](?P<href>[^\"']+)[\"'][^>]*>(?P<text>.*?)</a>", re.I | re.S)
_URL = re.compile(r"https://[^\s<>\"')\]]+")
_TAGS = re.compile(r"<[^>]+>")
_SECOND = {"co", "com", "org", "net", "ac", "gov", "edu", "ltd", "plc"}


def on(who) -> bool:
    from . import switches

    if who is None:
        return False
    return switches.on(SWITCH, getattr(who, "org_id", None) or None)


def registrable(host: str) -> str:
    """acme.com for mail.acme.com, acme.co.uk for eu.acme.co.uk."""
    parts = [p for p in (host or "").lower().strip(".").split(".") if p]
    if len(parts) >= 3 and len(parts[-1]) == 2 and parts[-2] in _SECOND:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def _links(found: dict) -> list[tuple[str, str]]:
    """(the words on it, the address) for every https link, in the order they come."""
    out: list[tuple[str, str]] = []
    markup = str(found.get("html") or "")
    for hit in _ANCHOR.finditer(markup):
        href = html.unescape(hit.group("href")).strip()
        words = " ".join(html.unescape(_TAGS.sub(" ", hit.group("text"))).split())
        if href.startswith("https://"):
            out.append((words, href))
    body = str(found.get("body") or "")
    lines = body.splitlines()
    for i, line in enumerate(lines):
        for hit in _URL.finditer(line):
            before = line[: hit.start()].strip(" :-<([") or (lines[i - 1].strip(" :-") if i else "")
            out.append((before[-80:], hit.group(0).rstrip(".,;")))
    return out


def shown(who, found: dict, now: float | None = None) -> dict | None:
    """What the opened message's row says, or None."""
    from . import renewal_notice

    if not on(who):
        return None
    sent = float(found.get("at") or 0)
    now = time.time() if now is None else now
    if sent and now - sent > FRESH_HOURS * 3600:
        return None
    subject = str(found.get("subject") or "")
    body = str(found.get("body") or "")
    text = f"{subject}\n{body[:3000]}"
    step = next((s for s in STEPS if re.search(s[1], text, re.I)), None)
    if step is None:
        return None
    label, _asks, says, holds = step
    _name, address = email.utils.parseaddr(str(found.get("from") or ""))
    sender = registrable(address.rsplit("@", 1)[-1]) if "@" in address else ""
    if not sender:
        return None
    for words, href in _links(found):
        low_words, low_href = words.lower(), href.lower()
        if not (re.search(says, low_words, re.I) or re.search(holds, low_href, re.I)):
            continue
        if re.search(r"unsubscribe|preferences|privacy|terms|help|support|not you|didn'?t", low_words + " " + low_href):
            continue
        host = (urllib.parse.urlsplit(href).hostname or "").lower()
        if registrable(host) != sender:
            continue
        service = renewal_notice.service_of(str(found.get("from") or ""))
        return {"label": label, "said": f"{label} at {service}", "href": href, "host": host, "service": service}
    return None


def pressed(who, label: str = "") -> None:
    """The button pressed: counted, nothing else."""
    from . import evolution

    log.info("the button in an email: pressed")
    evolution.used(SWITCH, "pressed", who=who, detail=str(label or "")[:60])


__all__ = ["FRESH_HOURS", "STEPS", "SWITCH", "TITLE", "on", "pressed", "registrable", "shown"]
