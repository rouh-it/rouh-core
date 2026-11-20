"""A greeting to somebody who is not on the email: "Hi Maria," to Anna is caught before it goes.

Built by the nightly feature run, night 49 of the ledger (20 November 2026, task 94).
Rouh writes many emails from an earlier one: the same introduction to a second investor, the same
follow-up to the next company. The commonest mistake of that way of writing is the name in the
greeting, left from the first one: "Hi Maria," in an email that goes to Anna. She reads at once
that it was written for somebody else.

So, while its switch is on, before send_mail sends an email or draft_mail drafts one (the person's
own turns and Rouh's jobs alike), the greeting at the top of its own words ("Hi Maria,", "Dear Mr
Reed,", "Здравей, Иване,") is read in plain rules, no model, for the names in it, and each is looked
for among the people it goes to (To and Cc): their names as the addresses give them ("Anna Smith"
<anna.smith@...>) and the words of the address itself (anna.smith, asmith), Latin and Cyrillic alike,
a name and its short form or its Bulgarian calling form counting as one (Alex and Alexander, Иване
and Ivan). When a name in the greeting is nobody's, nothing is sent or drafted: Rouh is told who it
goes to, and writes it again with the right name, or asks the person. `greeting_checked` sends it
as written, when the person says it is right (a name they go by that their address does not say).

It never holds an email when somebody it goes to has no name to read (office@, info@): the greeting
may be theirs. "Hi all", "Hi team", "Dear Sir or Madam" have no name in them. Nothing is kept and
nothing is changed.

**Whose.** Nothing of anybody's is read but the email being written and its addresses.

**Its switch** is `greeting_name` (`rouh/switches.py`): off, an email goes as written.
"""
from __future__ import annotations

import email.utils
import re

SWITCH = "greeting_name"
TITLE = "A greeting to somebody not on the email: \"Hi Maria,\" to Anna is caught before it goes"

FIELD = {"type": "boolean",
         "description": "Send or draft it although the name in its greeting is nobody's it goes to: only "
                        "when the person says the name is right (a name they go by), after being told."}

_HELLO = (r"(?:hi|hello|hey|hiya|dear|good (?:morning|afternoon|evening)|morning|greetings|"
          r"здравей(?:те)?|здрасти|здрасте|здравейте|скъп(?:а|и|ий)|уважаем(?:а|и|ий)|привет|добро утро|"
          r"добър ден|добър вечер)")
#: The greeting: its first own line, a hello, then the names, up to the comma, the dash or the end.
_GREETING = re.compile(r"^\s*" + _HELLO + r"\b[ ,]*(?P<names>[^\n,!:;.—-]{1,80}?)\s*[,!:;.—-]?\s*$",
                       re.I | re.M)
#: Words in a greeting that are not a name.
_NOT_NAMES = {
    "all", "everyone", "everybody", "team", "there", "folks", "guys", "both", "you", "again", "friends",
    "colleagues", "sir", "madam", "or", "and", "mr", "mrs", "ms", "miss", "dr", "prof", "professor",
    "sirs", "hiring", "manager", "the", "to", "whom", "it", "may", "concern", "customer", "support",
    "y'all", "gents", "ladies", "gentlemen", "partners", "board", "people",
    "г-н", "г-жо", "г-жа", "господин", "госпожо", "всички", "колеги", "приятели", "екип", "и", "д-р",
}
#: Addresses that name nobody.
_NOBODY = {"info", "office", "hello", "contact", "sales", "support", "team", "admin", "accounts", "billing",
           "hr", "jobs", "careers", "mail", "noreply", "no-reply", "help", "press", "media", "finance",
           "invoices", "legal", "marketing", "partners", "service", "enquiries", "inquiries", "booking",
           "bookings", "reception", "management", "ceo", "founders", "hi", "hey", "general", "post"}

_CYR = dict(zip("абвгдежзийклмнопрстуфхцчшщъьюя",
                ["a", "b", "v", "g", "d", "e", "zh", "z", "i", "y", "k", "l", "m", "n", "o", "p", "r", "s",
                 "t", "u", "f", "h", "ts", "ch", "sh", "sht", "a", "", "yu", "ya"]))

#: Short forms that are one name.
_SHORT = {"alex": "alexander", "sasha": "alexander", "bob": "robert", "rob": "robert", "bill": "william",
          "will": "william", "liz": "elizabeth", "beth": "elizabeth", "kate": "katherine", "katie": "katherine",
          "mike": "michael", "dan": "daniel", "dave": "david", "jim": "james", "jimmy": "james",
          "tom": "thomas", "nick": "nicholas", "chris": "christopher", "matt": "matthew", "pete": "peter",
          "joe": "joseph", "tony": "anthony", "andy": "andrew", "ben": "benjamin", "sam": "samuel",
          "steve": "stephen", "jen": "jennifer", "jenny": "jennifer", "max": "maximilian", "pepe": "petar",
          "pesho": "petar", "gosho": "georgi", "vanyo": "ivan", "mitko": "dimitar", "toni": "antoniya",
          "nadya": "nadezhda", "ani": "anna", "dani": "daniela", "niki": "nikolay", "kiro": "kiril"}

#: Where somebody else's words start in a reply: they are not read.
_QUOTED = re.compile(r"^\s*(?:On .{4,200}wrote:|На .{4,200}написа:|-{2,}\s*Original Message|"
                     r"-{2,}\s*Forwarded message|From: .+@)", re.M | re.I)


def on(who) -> bool:
    from . import switches

    if who is None:
        return False
    return switches.on(SWITCH, getattr(who, "org_id", None) or None)


def latin(word: str) -> str:
    """A word in plain lower-case Latin letters: Cyrillic spelt out, accents taken off."""
    import unicodedata

    low = (word or "").lower()
    out = "".join(_CYR.get(ch, ch) for ch in low)
    out = unicodedata.normalize("NFKD", out)
    return "".join(ch for ch in out if ch.isalpha() and ord(ch) < 128)


def _same(a: str, b: str) -> bool:
    """One name, or one a calling form or a short form of the other."""
    if not a or not b:
        return False
    a, b = _SHORT.get(a, a), _SHORT.get(b, b)
    if a == b:
        return True
    shorter, longer = sorted((a, b), key=len)
    # Иване is Ivan called; Alex is Alexander; Ani is Anna spoken: four letters in common at the start,
    # or the whole of a short one.
    return len(shorter) >= 3 and (longer.startswith(shorter) or (len(shorter) >= 4 and longer[:4] == shorter[:4]))


def greeting_names(body: str) -> list[str]:
    """The names in the greeting at the top of the email's own words, as written."""
    text = (body or "").lstrip()
    cut = _QUOTED.search(text)
    if cut:
        text = text[: cut.start()]
    lines = [line for line in text.splitlines() if line.strip()][:1]
    for line in lines:
        hit = _GREETING.match(line)
        if not hit:
            continue
        words = re.split(r"[\s&/+]+", hit.group("names").strip())
        names = [w.strip("'\"()") for w in words]
        names = [w for w in names if w and w.lower().rstrip(".") not in _NOT_NAMES and w[0].isupper()
                 and len(latin(w)) >= 2]
        return names
    return []


def people(*fields: str) -> list[dict]:
    """Each address it goes to, with the name words it carries: {"address", "names", "readable"}."""
    out = []
    for name, address in email.utils.getaddresses([f for f in fields if f]):
        address = (address or "").strip().lower()
        if "@" not in address:
            continue
        local = address.split("@", 1)[0].split("+", 1)[0]
        raw = [latin(p) for p in re.split(r"[._\-\d]+", local) if p]
        words = [latin(p) for p in re.split(r"[\s,.'\"()-]+", name or "") if p]
        words = [w for w in words if len(w) >= 2]
        parts = [p for p in raw if len(p) >= 2 and p not in _NOBODY]
        # An address reads as a name only as first.last, with a first name of two letters or more:
        # "asmith", "dreed" and "d.reed" do not say what the person is called.
        spelt = len(raw) >= 2 and len(raw[0]) >= 2 and raw[0] not in _NOBODY
        out.append({"address": address, "names": words + parts, "readable": bool(words) or spelt})
    return out


def _named(name: str, person: dict) -> bool:
    want = latin(name)
    for word in person["names"]:
        if _same(want, word):
            return True
    # annasmith, anna1987: the name at the start of an address run together.
    local = person["address"].split("@", 1)[0]
    return len(want) >= 3 and latin(local).startswith(want)


def wrong(body: str, to: str, cc: str = "") -> tuple[list[str], list[dict]]:
    """The greeting's names that are nobody's it goes to, and who it goes to; ([], ...) when it is right."""
    names = greeting_names(body)
    them = people(to, cc)
    if not names or not them or not all(p["readable"] for p in them):
        return [], them
    return [n for n in names if not any(_named(n, p) for p in them)], them


def check(body: str, to: str, cc: str = "", *, verb: str = "sent") -> str:
    """Why it is held, or "" when every name in the greeting is somebody's it goes to."""
    missing, them = wrong(body, to, cc)
    if not missing:
        return ""
    names = " and ".join(f"“{n}”" for n in missing)
    goes = ", ".join(p["address"] for p in them[:6])
    return (f"Not {verb}: the greeting names {names}, and nobody it goes to is called that: it goes to "
            f"{goes}. It looks written for somebody else. Write it again with the right name (look the "
            "person up in the contacts if their address does not say it), or ask the person. If the name "
            "is right, a name they go by, call it again with greeting_checked true.")


__all__ = ["FIELD", "SWITCH", "TITLE", "check", "greeting_names", "latin", "on", "people", "wrong"]
