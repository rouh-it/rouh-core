"""A link they can open: an email is held when somebody it goes to cannot open a Google Drive file it
links to.

Built by the nightly feature run, night 46 of the ledger (17 November 2026, task 94).
Rouh sends mail for ‹owner› through Gmail's API, and Gmail's own warning ("the recipients don't have
access to this file, share it?") belongs to Gmail's compose window, which Rouh never opens. So an
email with a link to a document went to a client who could not open it: they pressed Request access,
wrote back, waited, and the document reached them a day later, after a second email.

So, while its switch is on, before `send_mail` sends a new email, the Google Drive and Docs links in
its words (`ids`: docs.google.com/.../d/<id>, drive.google.com/file/d/<id>, ...?id=<id>, folders) are
read, at most `MOST` files, each file's sharing once (`Drive.permissions`), and for everybody the email
goes to (To, Cc and Bcc, never Rouh's own mailbox):

- a link anyone can open, the person named on the file, or their whole company (a domain on it) is
  enough, and the email goes as before;
- anybody left who cannot open a linked file holds the email: nothing is sent, and the answer names
  who cannot open which file and who can, so the person says "share it with her" (share_drive_file,
  with notify false, as the email itself is the message) or "send it anyway" (`links_checked`).

A file whose sharing Rouh cannot read (not its own, or Drive refused), and one with a group on it
(whose members cannot be read), lets the email through: only a sure "cannot open" holds it.

Nothing is changed or kept, and no model is asked.

**Whose.** The person's Google connection, by `org_id` and `user_id`.

**Its switch** is `link_access` (`rouh/switches.py`): off, emails with links go as before.
"""
from __future__ import annotations

import email.utils
import re

SWITCH = "link_access"
TITLE = "A link they can open: an email is held when somebody cannot open a Drive file it links to"

#: The most linked files read before one email goes.
MOST = 5

FIELD = {"type": "boolean",
         "description": "Send even though somebody it goes to cannot open a Google Drive file it links "
                        "to, after the person said to (A link they can open). Leave out otherwise."}

_LINK = re.compile(
    r"https?://(?:docs|drive)\.google\.com/[^\s<>\"')\]]*?"
    r"(?:/d/|/folders/|[?&]id=)([A-Za-z0-9_-]{8,})")


def on(who) -> bool:
    from . import switches

    if who is None:
        return False
    return switches.on(SWITCH, getattr(who, "org_id", None) or None)


def ids(body: str) -> list[str]:
    """The Drive files an email's words link to, in the order they first appear."""
    out: list[str] = []
    for found in _LINK.finditer(body or ""):
        one = found.group(1)
        if one not in out:
            out.append(one)
    return out[:MOST]


def recipients(to: str, cc: str, bcc: str, *, own: set[str]) -> list[tuple[str, str]]:
    """(name, address) of everybody an email goes to, Rouh's own mailbox left out."""
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    # Each line on its own: an empty one makes getaddresses give back nothing for all of them.
    pairs = [pair for line in (to, cc, bcc) if (line or "").strip() for pair in email.utils.getaddresses([line])]
    for name, address in pairs:
        address = (address or "").strip().lower()
        if not address or "@" not in address or address in own or address in seen:
            continue
        seen.add(address)
        out.append((name or "", address))
    return out


def can_open(held: list[dict], address: str) -> bool | None:
    """Whether this address can open a file with these permissions: True, False, or None when it
    cannot be told (a group is on it)."""
    domain = address.rsplit("@", 1)[-1]
    unsure = False
    for one in held:
        kind = one.get("kind")
        if kind == "anyone":
            return True
        if kind == "domain":
            named = str(one.get("domain") or "") or str(one.get("who") or "").replace("everybody at ", "")
            if named.lower() == domain:
                return True
        elif kind in ("user", "group") and str(one.get("email") or "").lower() == address:
            return True
        elif kind == "group":
            unsure = True
    return None if unsure else False


def _who_can(held: list[dict]) -> str:
    people = [str(p.get("who") or p.get("email") or "") for p in held if p.get("role") != "owner"]
    people = [p for p in people if p]
    if not people:
        return "only its owner"
    return ", ".join(people[:4]) + (f" and {len(people) - 4} more" if len(people) > 4 else "")


def held_back(files: list[tuple[dict, list[dict]]], people: list[tuple[str, str]]) -> tuple[str, int]:
    """Why the email waits, and how many people cannot open something; ("", 0) when it may go."""
    lines: list[str] = []
    shut = set()
    for about, held in files:
        out = [(n, a) for n, a in people if can_open(held, a) is False]
        if not out:
            continue
        shut.update(a for _, a in out)
        names = ", ".join(f"{n} ({a})" if n else a for n, a in out)
        lines.append(f"- {names} cannot open {about.get('name') or about.get('id')!r} "
                     f"(file id {about.get('id')}): it is open to {_who_can(held)}.")
    if not lines:
        return "", 0
    return ("Not sent: somebody it goes to cannot open a file the email links to.\n" + "\n".join(lines)
            + "\nAsk the person: share it with them first (share_drive_file, people with their address, "
              "notify false, since this email is the message), then send it; or, if they say so, send it "
              "anyway with links_checked."), len(shut)


__all__ = ["FIELD", "MOST", "SWITCH", "TITLE", "can_open", "held_back", "ids", "on", "recipients"]
