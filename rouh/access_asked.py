"""Asked to open a file: somebody asking Google for access to a file in Rouh's Drive is told at once,
with one press that lets them in.

Built by the nightly feature run, night 46 of the ledger (17 November 2026, task 94).
Rouh makes documents for ‹owner› in the Drive of its own Google connection (create_doc, write_drive_file,
a page sent to Google Docs) and shares them. When a guest opens such a link without access and presses
Request access, Google emails the file's owner, which is Rouh's inbox. Mail alerts passed that email
over as machine mail (`mail_alerts.junk_because`, a no-reply sender): nobody saw it, the guest waited,
and wrote again a day later asking whether the link was right.

So, while its switch is on, when an email reaches Rouh's inbox from Google (`google.com`) that asks for
access to a file (`request`: "Share request for", "is requesting access", "requests access", in plain
rules, no model), Rouh reads who asked (the email's Reply-To, else the address it names), which file
(the Drive or Docs link in it, `link_access.ids`) and what they asked to do (view, comment or edit),
then the file itself, from its own Drive. When the file is there and the person cannot open it yet, a
notice says it at once: who asked, for which file, to do what, and who can open it now. Its buttons:

- **Let them edit** (or comment, or view: what they asked for) shares the file with them at that, and
  Google emails them that it is shared, which is the answer they are waiting for;
- **View only**, when they asked for more, shares it to read.

A notice left alone shares nothing. The same request is told once. A request for a file Rouh cannot
see, or from somebody who can already open it, says nothing; the email is passed over as before.

No model is asked.

**Whose.** Rouh's connected inbox and Drive and the person it belongs to, by `org_id` and `user_id`;
what was told is kept in `user_settings` (`access_asked`), at most the last `KEPT`.

**Its switch** is `access_asked` (`rouh/switches.py`): off, nothing is read and the buttons' address
says it is switched off.
"""
from __future__ import annotations

import email.utils
import hashlib
import json
import logging
import re
import time

log = logging.getLogger("rouh.access_asked")

SWITCH = "access_asked"
TITLE = "Asked to open a file: a request for access to a file in Rouh's Drive, told at once"

HELD = "access_asked"
KEPT = 200

ROLES = ("reader", "commenter", "writer")
VERB = {"reader": "view", "commenter": "comment on", "writer": "edit"}

_ASKS = re.compile(r"share request|requesting (?:\w+ )?access|requests? (?:\w+ )?access|asked for access|"
                   r"asks? for access|wants? access", re.I)
_EDIT = re.compile(r"\b(?:edit(?:or)? access|to edit|requesting edit|edit request|as an editor)\b", re.I)
_COMMENT = re.compile(r"\b(?:comment(?:er)? access|to comment|as a commenter)\b", re.I)
_ADDRESS = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def on(who) -> bool:
    from . import switches

    if who is None:
        return False
    return switches.on(SWITCH, getattr(who, "org_id", None) or None)


def _ids(who) -> tuple[str, str]:
    return str(getattr(who, "user_id", "") or ""), str(getattr(who, "org_id", "") or "")


def _held(who) -> dict:
    from .models import UserSetting

    user_id, org_id = _ids(who)
    value = (UserSetting.objects.filter(user_id=user_id, org_id=org_id, name=HELD)
             .values_list("value", flat=True).first())
    try:
        held = json.loads(value) if value else {}
    except (TypeError, ValueError):
        held = {}
    return held if isinstance(held, dict) else {}


def _put(who, held: dict) -> None:
    from .models import UserSetting

    user_id, org_id = _ids(who)
    if len(held) > KEPT:
        held = dict(sorted(held.items(), key=lambda kv: kv[1].get("at") or 0)[-KEPT:])
    UserSetting.objects.bulk_create(
        [UserSetting(user_id=user_id, org_id=org_id, name=HELD, value=json.dumps(held), updated_at=time.time())],
        update_conflicts=True, unique_fields=["user_id", "name"], update_fields=["org_id", "value", "updated_at"])


def one(who, key: str) -> dict | None:
    got = _held(who).get(key)
    return got if isinstance(got, dict) else None


def key_of(file_id: str, address: str) -> str:
    return "aa-" + hashlib.sha256(f"{file_id}|{address.lower()}".encode()).hexdigest()[:16]


def _google(address: str) -> bool:
    domain = address.rsplit("@", 1)[-1].lower()
    return domain == "google.com" or domain.endswith(".google.com")


def request(message: dict, mailbox: str = "") -> dict | None:
    """What an email from Google asks, or None when it is not a request for access:
    {"email", "name", "file_id", "role"}."""
    from . import link_access

    sender = email.utils.parseaddr(message.get("from", ""))[1].lower()
    if not sender or not _google(sender):
        return None
    subject = str(message.get("subject") or "")
    body = str(message.get("body") or "")
    if not _ASKS.search(subject) and not _ASKS.search(body[:3000]):
        return None
    files = link_access.ids(body)
    if not files:
        return None
    name, address = email.utils.parseaddr(message.get("reply_to", "") or "")
    address = address.lower()
    if not address or _google(address):
        name, address = "", ""
        own = (mailbox or "").lower()
        for found in _ADDRESS.findall(body):
            found = found.lower()
            if not _google(found) and found != own:
                address = found
                break
    if not address:
        return None
    if not name:
        said = email.utils.parseaddr(message.get("from", ""))[0]
        name = re.sub(r"\s*\(via Google [^)]*\)\s*$", "", said or "").strip()
        if name.lower() in ("", "google drive", "google docs", "google sheets", "google slides"):
            name = ""
    words = subject + "\n" + body[:3000]
    role = "writer" if _EDIT.search(words) else "commenter" if _COMMENT.search(words) else "reader"
    return {"email": address, "name": name, "file_id": files[0], "role": role}


def _who_can(held: list[dict]) -> str:
    people = [str(p.get("who") or p.get("email") or "") for p in held if p.get("role") != "owner"]
    people = [p for p in people if p]
    if not people:
        return "nobody but Rouh's account"
    return ", ".join(people[:4]) + (f" and {len(people) - 4} more" if len(people) > 4 else "")


async def seen(who, message: dict, services, *, mailbox: str = "") -> str:
    """A request for access to a file in Rouh's Drive, told: the sentence for the mail log, or ""
    when it is not one, there is nothing to tell, or the switch is off."""
    import asyncio

    from asgiref.sync import sync_to_async

    from . import evolution, link_access, notices

    asked = request(message, mailbox)
    if asked is None or services is None:
        return ""
    if not await asyncio.to_thread(on, who):
        return ""
    key = key_of(asked["file_id"], asked["email"])
    held = await sync_to_async(_held)(who)
    if key in held:
        return "A request for access already told."
    drive = services.drive
    try:
        about = await drive.metadata(asked["file_id"])
        permissions = await drive.permissions(asked["file_id"])
    except Exception as exc:  # noqa: BLE001 - not a file Rouh can share: nothing to tell
        log.info("asked to open a file: %s could not be read: %s", asked["file_id"], exc)
        return ""
    if link_access.can_open(permissions, asked["email"]) is True:
        return ""
    title = about.get("name") or "a file"
    whom = asked["name"] or asked["email"]
    verb = VERB[asked["role"]]
    named = f"{whom} ({asked['email']})" if asked["name"] else whom
    text = (f"{named} asked Google to {verb} "
            f"“{title[:120]}”. The file is in Rouh's Drive, so the request came to Rouh's inbox and "
            f"nobody else saw it. Now it is open to {_who_can(permissions)}.")
    held[key] = {"file_id": asked["file_id"], "email": asked["email"], "name": asked["name"],
                 "role": asked["role"], "title": title[:200], "link": about.get("link") or "",
                 "mailbox": mailbox, "at": time.time(), "given": ""}
    await sync_to_async(_put)(who, held)
    base = f"/mail/access-asked/{key}"
    links = [{"label": f"Let them {VERB[asked['role']].split()[0]}", "href": f"{base}?role={asked['role']}"}]
    if asked["role"] != "reader":
        links.append({"label": "View only", "href": f"{base}?role=reader"})
    said = await notices.notify(title=f"{whom} asks to {verb} “{title[:60]}”", body=text,
                                link=links[0]["href"], link_label=links[0]["label"], links=links,
                                kind="mail", key=key, who=who)
    if said is None:
        return ""
    await sync_to_async(evolution.used)(SWITCH, "told", who=who, detail=f"asked to {verb} a file")
    return f"{whom} asked to {verb} {title[:80]!r}, a file in Rouh's Drive: told in a notice."


async def let_in(who, key: str, role: str, services) -> tuple[bool, str]:
    """Let them in, pressed: (done, what to say)."""
    from asgiref.sync import sync_to_async

    from . import evolution, notices

    told = await sync_to_async(one)(who, key)
    if told is None:
        return False, "That is not a request Rouh told you about."
    role = role if role in ROLES else told.get("role") or "reader"
    title = told.get("title") or "the file"
    whom = told.get("name") or told.get("email")
    if told.get("given") == role:
        return True, f"{whom} can already {VERB[role]} “{title}”."
    if services is None:
        return False, "Google is not connected, so nobody could be let in."
    await services.drive.share_with_person(told["file_id"], told["email"], role, notify=True)
    held = await sync_to_async(_held)(who)
    if key in held:
        held[key] = dict(held[key], given=role, given_at=time.time())
        await sync_to_async(_put)(who, held)
    await sync_to_async(evolution.used)(SWITCH, "let_in", who=who, detail=f"let in to {VERB[role]}")
    said = f"{whom} can {VERB[role]} “{title}” now, and Google emailed them that it is shared."
    links = [{"label": "Open the file", "href": told["link"]}] if told.get("link") else []
    await notices.notify(title=f"{whom} is let in", body=said, kind="mail", key=key + "-given-" + role, links=links,
                         link=told.get("link") or "", link_label="Open the file" if links else "", who=who)
    return True, said


__all__ = ["HELD", "KEPT", "ROLES", "SWITCH", "TITLE", "VERB", "key_of", "let_in", "on", "one", "request", "seen"]
