"""Asked in a comment: a Google Docs comment that names Rouh's account, or gives it an action item, is
told at once, with the comment's words and one press that answers it.

Built by the nightly feature run, night 47 of the ledger (18 November 2026, task 94).
Colleagues work with Rouh inside the documents ‹he› shares: since night 22 Rouh reads a doc's
comments and answers one when asked. When somebody writes "+rouh@... can you update the figures?" in a
comment, or assigns Rouh an action item, Google emails Rouh's account, and only Rouh's: ‹he› is not
told unless ‹he› was named too. Mail alerts passed that email over as machine mail (a no-reply sender,
`mail_alerts.junk_because`), so the person who asked waited on an answer nobody knew was owed.

So, while its switch is on, when an email reaches Rouh's inbox from Google Docs (`docs.google.com`,
`google.com`) saying that somebody mentioned Rouh in a comment or assigned it an action item
(`request`, in plain rules, no model), Rouh reads which file (the Docs link in it, `link_access.ids`)
and which comment (the link's `disco=`), then the comment itself from Drive. When the comment is
there, open, and not already answered by Rouh's account, a notice says it at once: who asked, in which
document, on which words, and what they wrote. Its buttons:

- **Open the comment** goes to the comment in the document (through `/mail/comment-asks/<key>?open=1`,
  so the press is counted);
- **Say Rouh has seen it** writes, under the comment, from Rouh's own account, that Rouh has seen it
  and passed it on to ‹owner›, so the person who asked knows it reached somebody.

A notice left alone writes nothing. The same comment is told once. A comment Rouh cannot read, already
resolved, or already answered by Rouh says nothing; the email is passed over as before.

No model is asked.

**Whose.** Rouh's connected inbox and Drive and the person it belongs to, by `org_id` and `user_id`;
what was told is kept in `user_settings` (`comment_asks`), at most the last `KEPT`.

**Its switch** is `comment_asks` (`rouh/switches.py`): off, nothing is read and the button's address
says it is switched off.
"""
from __future__ import annotations

import email.utils
import hashlib
import json
import logging
import re
import time

log = logging.getLogger("rouh.comment_asks")

SWITCH = "comment_asks"
TITLE = "Asked in a comment: a Google Docs comment naming Rouh, told at once"

HELD = "comment_asks"
KEPT = 200

#: What Rouh writes under the comment when Say Rouh has seen it is pressed.
SEEN = "Seen, thank you: I have passed this on to ‹owner›."

_ASKS = re.compile(r"mentioned you|assigned (?:you|to you)|action item|added you to (?:a|the) comment|"
                   r"tagged you", re.I)
_COMMENT_ID = re.compile(r"[?&#]disco=([A-Za-z0-9_-]{4,})")


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


def key_of(file_id: str, comment_id: str) -> str:
    return "ca-" + hashlib.sha256(f"{file_id}|{comment_id}".encode()).hexdigest()[:16]


def _google(address: str) -> bool:
    domain = address.rsplit("@", 1)[-1].lower()
    return domain == "google.com" or domain.endswith(".google.com")


def request(message: dict) -> dict | None:
    """What a Google Docs email asks of Rouh, or None when it is not a comment naming it:
    {"file_id", "comment_id", "name", "action"}."""
    from . import link_access

    sender = email.utils.parseaddr(message.get("from", ""))[1].lower()
    if not sender or not _google(sender):
        return None
    subject = str(message.get("subject") or "")
    body = str(message.get("body") or "")
    words = subject + "\n" + body[:4000]
    if not _ASKS.search(words):
        return None
    files = link_access.ids(body)
    found = _COMMENT_ID.search(body)
    if not files or not found:
        return None
    said = email.utils.parseaddr(message.get("from", ""))[0]
    name = re.sub(r"\s*\((?:via )?Google [^)]*\)\s*$", "", said or "").strip()
    if name.lower() in ("", "google drive", "google docs", "google sheets", "google slides"):
        name = ""
    return {"file_id": files[0], "comment_id": found.group(1), "name": name,
            "action": bool(re.search(r"assigned|action item", words, re.I))}


def _link(about: dict, file_id: str, comment_id: str) -> str:
    base = str(about.get("link") or f"https://docs.google.com/document/d/{file_id}/edit")
    return base + ("&" if "?" in base else "?") + "disco=" + comment_id


async def seen(who, message: dict, services) -> str:
    """A comment asking Rouh, told: the sentence for the mail log, or "" when it is not one, there is
    nothing to tell, or the switch is off."""
    import asyncio

    from asgiref.sync import sync_to_async

    from . import evolution, notices

    asked = request(message)
    if asked is None or services is None:
        return ""
    if not await asyncio.to_thread(on, who):
        return ""
    key = key_of(asked["file_id"], asked["comment_id"])
    held = await sync_to_async(_held)(who)
    if key in held:
        return "A comment asking Rouh already told."
    drive = services.drive
    try:
        about = await drive.metadata(asked["file_id"])
        comments = await drive.comments(asked["file_id"])
    except Exception as exc:  # noqa: BLE001 - not a file Rouh can read: nothing to tell
        log.info("asked in a comment: %s could not be read: %s", asked["file_id"], exc)
        return ""
    comment = next((c for c in comments if c.get("id") == asked["comment_id"]), None)
    if comment is None or comment.get("resolved"):
        return ""
    if any(r.get("me") for r in comment.get("replies") or []):
        return ""
    title = about.get("name") or "a document"
    whom = comment.get("who") or asked["name"] or "Somebody"
    # The newest words are the ask: a reply that names Rouh is newer than the comment it is under.
    replies = [r for r in comment.get("replies") or [] if r.get("words")]
    words = (replies[-1]["words"] if replies else comment.get("words") or "").strip()
    if replies:
        whom = replies[-1].get("who") or whom
    on_words = (comment.get("on") or "").strip()
    what = "gave Rouh an action item" if asked["action"] else "asked Rouh"
    text = (f"{whom} {what} in a comment on “{title[:120]}”"
            + (f", on the words “{on_words[:160]}”" if on_words else "")
            + f": “{words[:600]}”. Google told only Rouh's inbox, so nobody else knows it is waiting.")
    link = _link(about, asked["file_id"], asked["comment_id"])
    held[key] = {"file_id": asked["file_id"], "comment_id": asked["comment_id"], "who": whom,
                 "title": title[:200], "link": link, "at": time.time(), "answered": ""}
    await sync_to_async(_put)(who, held)
    links = [{"label": "Open the comment", "href": f"/mail/comment-asks/{key}?open=1"},
             {"label": "Say Rouh has seen it", "href": f"/mail/comment-asks/{key}"}]
    said = await notices.notify(title=f"{whom} {what} in “{title[:60]}”", body=text,
                                link=links[0]["href"], link_label="Open the comment", links=links,
                                kind="mail", key=key, who=who)
    if said is None:
        return ""
    await sync_to_async(evolution.used)(SWITCH, "told", who=who, detail="a comment asking Rouh, told")
    return f"{whom} {what} in a comment on {title[:80]!r}: told in a notice."


async def opened(who, key: str) -> str:
    """Open the comment, pressed: where it is, or "" when it is not one Rouh told."""
    from asgiref.sync import sync_to_async

    from . import evolution

    told = await sync_to_async(one)(who, key)
    if told is None or not told.get("link"):
        return ""
    await sync_to_async(evolution.used)(SWITCH, "opened", who=who, detail="opened a comment asking Rouh")
    return str(told["link"])


async def answer(who, key: str, services) -> tuple[bool, str]:
    """Say Rouh has seen it, pressed: (done, what to say)."""
    from asgiref.sync import sync_to_async

    from . import evolution, notices, owner

    told = await sync_to_async(one)(who, key)
    if told is None:
        return False, "That is not a comment Rouh told you about."
    title = told.get("title") or "the document"
    whom = told.get("who") or "them"
    if told.get("answered"):
        return True, f"Rouh already told {whom} it has seen their comment on “{title}”."
    if services is None:
        return False, "Google is not connected, so nothing was written under the comment."
    words = await sync_to_async(owner.say)(SEEN, who)
    await services.drive.reply_to_comment(told["file_id"], told["comment_id"], words)
    held = await sync_to_async(_held)(who)
    if key in held:
        held[key] = dict(held[key], answered=time.time())
        await sync_to_async(_put)(who, held)
    await sync_to_async(evolution.used)(SWITCH, "answered", who=who, detail="said Rouh has seen a comment")
    said = f"Under {whom}'s comment on “{title}”, Rouh wrote: “{words}”"
    links = [{"label": "Open the comment", "href": told["link"]}] if told.get("link") else []
    await notices.notify(title="Answered under the comment", body=said, kind="mail", key=key + "-answered",
                         links=links, link=told.get("link") or "",
                         link_label="Open the comment" if links else "", who=who)
    return True, said


__all__ = ["HELD", "KEPT", "SEEN", "SWITCH", "TITLE", "answer", "key_of", "on", "one", "opened", "request", "seen"]
