"""A mistyped address caught: an email is not sent to an address a letter or two off one ‹he›
already knows.

Built by the nightly feature run, night 33 (second run), 5 November 2026 (task 94). Most of what
Rouh sends is asked for by voice, and an address heard or typed from memory is easily one letter
wrong: "dana@northwnd.com" for dana@northwind.com, "ownen.marsh@" for owen.marsh@,
"@gmial.com" for @gmail.com. Gmail sends it all the same. The best case is a bounce an hour later
that nobody reads; the worst is a stranger's mailbox, or a domain somebody registered to catch
exactly those letters, holding a client's figures. Nobody notices until the person asks "did
Dana answer?".

So, while its switch is on, before send_mail sends anything, each address it goes to (To, Cc and
Bcc) is compared with the addresses ‹he› already has: everybody in ‹his› Synapse Master (‹his›
contacts and everybody ‹his› mail and meetings met), Rouh's own mailbox, and ‹his› own address.

- An address already known goes, as before; so does a new one that looks like nobody known (a
  new person is not a mistake).
- An address that is not known but is one or two letters off a known one, in the name before the
  @ at the same company or in the company's domain with the same name (a letter missing, added,
  changed or two swapped), or a well-known mail domain misspelt (gmial.com), is not sent: nothing
  goes, and the answer says which address, and which known one it is probably meant to be, so the
  person says "yes, Dana" in a word.
- When the person says the new address is right, `address_checked` sends it as written.

No model is asked; nothing is kept.

**Whose.** The Synapse Master of the person sending (`org_id` and `user_id`).

**Its switch** is `address_check` (`rouh/switches.py`): off, mail goes to whatever address it is
given, as before.
"""
from __future__ import annotations

import logging
import re

log = logging.getLogger("rouh.address_check")

SWITCH = "address_check"
TITLE = "A mistyped address caught: an email is not sent to an address one letter off one you know"

#: Said to the model beside send_mail's other fields.
FIELD = {"type": "boolean",
         "description": ("Send to the addresses exactly as written even though one is a letter or two "
                         "off an address the person already has. Only when the person says the "
                         "address is right, after being asked.")}

#: Mail domains so common that a near miss of one is a typo, whoever it is for.
COMMON = ("gmail.com", "googlemail.com", "outlook.com", "hotmail.com", "live.com", "yahoo.com",
          "icloud.com", "me.com", "mac.com", "proton.me", "protonmail.com", "aol.com", "gmx.com",
          "gmx.de", "web.de", "abv.bg", "mail.bg", "dir.bg", "yandex.ru", "mail.ru")

_ADDRESS = re.compile(r"[A-Za-z0-9._%+'-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def on(who) -> bool:
    from . import switches

    if who is None:
        return False
    return switches.on(SWITCH, getattr(who, "org_id", None) or None)


def addresses(*fields: str) -> list[str]:
    """Every address in To, Cc and Bcc as written, "Name <a@b>" or bare, lower case, once each."""
    out: list[str] = []
    for text in fields:
        for one in _ADDRESS.findall(str(text or "")):
            one = one.lower().strip(".")
            if one not in out:
                out.append(one)
    return out


def distance(a: str, b: str) -> int:
    """Letters added, taken out, changed or two side by side swapped to make one into the other
    (the optimal string alignment distance)."""
    if a == b:
        return 0
    if abs(len(a) - len(b)) > 2:
        return 3
    prev2: list[int] = []
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i] + [0] * len(b)
        for j, cb in enumerate(b, 1):
            cost = 0 if ca == cb else 1
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
            if i > 1 and j > 1 and ca == b[j - 2] and a[i - 2] == cb:
                cur[j] = min(cur[j], prev2[j - 2] + 1)
        prev2, prev = prev, cur
    return prev[-1]


def _near(a: str, b: str) -> bool:
    """One or two letters off: one for a short word, two for a longer one; never for a word of
    two letters or fewer, where every change is a different word."""
    if min(len(a), len(b)) <= 2:
        return False
    if min(len(a), len(b)) <= 5 and len(a) != len(b):
        # dan beside dana is as likely a second person as a typo: a short word is held only for a
        # letter changed or two swapped, never one added or taken out.
        return False
    most = 1 if min(len(a), len(b)) <= 5 else 2
    return 0 < distance(a, b) <= most


def meant(address: str, known: set[str]) -> str:
    """The known address this unknown one is probably a mistyping of, or ""."""
    if address in known or "@" not in address:
        return ""
    local, _, domain = address.rpartition("@")
    best, score = "", 9
    for one in known:
        k_local, _, k_domain = one.rpartition("@")
        if k_domain == domain and _near(local, k_local):
            d = distance(local, k_local)
        elif k_local == local and _near(domain, k_domain):
            d = distance(domain, k_domain)
        else:
            continue
        if d < score or (d == score and one < best):
            best, score = one, d
    if best:
        return best
    if domain not in COMMON:
        for common in COMMON:
            if _near(domain, common) and distance(domain, common) == 1:
                return f"{local}@{common}"
    return ""


def known(who) -> set[str]:
    """Every address the person already has: their Synapse Master's people, Rouh's own mailbox
    and their own address."""
    from . import inbox
    from .synapse import db
    from .synapse.sources.contacts import master_of

    out = {a.lower() for a in inbox.own() if a}
    email = str(getattr(who, "email", "") or "").lower()
    if email:
        out.add(email)
    try:
        ds = master_of(str(who.user_id), str(who.org_id), make=False)
    except Exception:  # noqa: BLE001 - checked against what is known without it
        log.exception("the Synapse Master could not be read for the addresses")
        ds = None
    if ds:
        for row in db.rows("SELECT DISTINCT lower(value) AS value FROM synapse.identity "
                           "WHERE scope_id = %s AND type = 'email'", (str(ds["id"]),)):
            if row.get("value"):
                out.add(str(row["value"]).strip())
    return out


def check(who, to: str = "", cc: str = "", bcc: str = "") -> tuple[str, list[tuple[str, str]]]:
    """(why not, [(address, meant)]): a refusal when an address is probably a mistyping of a known
    one; ("", []) when every address is known or new."""
    said = addresses(to, cc, bcc)
    if not said:
        return "", []
    have = known(who)
    found = [(one, meant(one, have)) for one in said if one not in have]
    found = [(one, m) for one, m in found if m]
    if not found:
        return "", []
    lines = ["Not sent, and nobody was emailed: "
             + "; ".join(f"{one} is not an address the person has, and is a letter or two off {m}"
                         for one, m in found) + "."]
    lines.append("Ask the person in a few words whether they meant "
                 + (found[0][1] if len(found) == 1 else "those") + "; send it to the right address, "
                 "or, if they say the new address is right, send it again with address_checked.")
    return "\n".join(lines), found


__all__ = ["COMMON", "FIELD", "SWITCH", "TITLE", "addresses", "check", "distance", "known", "meant", "on"]
