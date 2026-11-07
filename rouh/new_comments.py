"""New comments on your documents: comments left in the last days on the Google documents ‹his›
tasks link to, by somebody else and not answered yet, in the morning brief.

Built by the nightly feature run, night 26, 29 October 2026 (task 94). ‹His› work is reviewed in
comments on Google Docs: the copy of ‹his› company's site is written in a colleague's docs, and
its readers leave their feedback there. Google tells a document's owner about a new comment, and
whoever it mentions; it does not tell ‹him› about a comment on a document somebody else owns. On
22 October 2026 a reviewer left three comments on a colleague's doc that one of ‹his› tasks links
to; nobody told ‹him›, and they were found six days later only because ‹he› asked a job to apply
"all of" that reviewer's comments and it went looking.

So, while its switch is on, the morning brief has a section **New comments on your documents**,
read as the page opens, with no model: each comment made in the last `DAYS` days on a Google Doc,
Sheet or Slides deck linked in any task's notes (the most recently mentioned `MOST_DOCS`), that is
not resolved, was not written by ‹him› or by Rouh's own Google account, and has no answer from
either since. Each line says the document, the task that links it, who wrote it, the words it is
on and what it says. **Open the comment** opens that comment in its document; **Open the task**
the task's page; **Let it be** puts it away, with Undo. A comment goes by itself once it is
answered or resolved.

**Whose.** The workspace's task notes and the documents the connected Google account can open
(`org_id` and `user_id`), read only; what ‹he› put away is ‹his› own setting (`user_settings`,
`new_comments`). Nothing is written in any document.

**Its switch** is `new_comments` (`rouh/switches.py`): off, the section is not there.
"""
from __future__ import annotations

import json
import logging
import time

log = logging.getLogger("rouh.new_comments")

SWITCH = "new_comments"
TITLE = ("New comments on your documents: comments left in the last days on the Google documents "
         "your tasks link to, not yet answered, in the morning brief")
#: A comment is new for this many days.
DAYS = 3
#: The most documents read, the most lines shown, and how long a reading is kept.
MOST_DOCS = 40
SHOWN = 8
FRESH = 900.0
#: The person's own setting: {"<doc>:<comment>": {"at"}}.
KEPT = "new_comments"
_held: dict[str, tuple[float, list[dict]]] = {}


def on(who) -> bool:
    from . import switches

    return switches.on(SWITCH, getattr(who, "org_id", None) or None)


def kept(who) -> dict[str, dict]:
    from .models import UserSetting

    value = (UserSetting.objects.filter(user_id=str(who.user_id), org_id=who.org_id or "", name=KEPT)
             .values_list("value", flat=True).first())
    try:
        held = json.loads(value) if value else {}
    except (TypeError, ValueError):
        held = {}
    return {str(k): v for k, v in held.items() if isinstance(v, dict)} if isinstance(held, dict) else {}


def _keep(who, held: dict) -> None:
    from .models import UserSetting

    # Only the last month's are worth keeping: older comments are never new again.
    month = time.time() - 31 * 86400
    held = {k: v for k, v in held.items() if float(v.get("at") or 0) > month}
    UserSetting.objects.bulk_create(
        [UserSetting(user_id=str(who.user_id), org_id=who.org_id or "", name=KEPT,
                     value=json.dumps(held), updated_at=time.time())],
        update_conflicts=True, unique_fields=["user_id", "name"],
        update_fields=["org_id", "value", "updated_at"])


def is_new(comment: dict, who, since: float) -> bool:
    """Open, made since `since`, not by the owner or Rouh, and nobody of theirs answered it."""
    from . import comments_in_docs as cid

    if comment.get("resolved") or comment.get("me") or cid.by_owner(comment.get("who") or "", who):
        return False
    if cid.moment(comment.get("at")) < since:
        return False
    for r in comment.get("replies") or []:
        if r.get("me") or cid.by_owner(r.get("who") or "", who):
            return False
    return True


async def _read(who, root, google, now: float) -> list[dict]:
    """Every new comment, newest first: [{key, doc, comment}]. Kept for `FRESH` seconds."""
    import asyncio

    from . import comments_in_docs as cid

    key = f"{who.org_id}:{who.user_id}"
    held = _held.get(key)
    if held and now - held[0] < FRESH:
        return held[1]
    docs = (await asyncio.to_thread(cid.linked_docs, root))[:MOST_DOCS]
    if not docs:
        return []
    read, _failed = await cid.read_all(google(who).drive, docs, most=MOST_DOCS)
    since = now - DAYS * 86400
    out = []
    for doc, comments in read:
        for c in comments:
            if c.get("id") and await asyncio.to_thread(is_new, c, who, since):
                out.append({"key": f"{doc['id']}:{c['id']}", "doc": doc, "comment": c})
    out.sort(key=lambda one: cid.moment(one["comment"].get("at")), reverse=True)
    _held[key] = (now, out)
    return out


def forget() -> None:
    _held.clear()


async def found(who, root, google, now: float | None = None) -> dict | None:
    """{items, count} for the brief, or None when no new comment waits."""
    from asgiref.sync import sync_to_async

    from . import comments_in_docs as cid

    if google is None or not root:
        return None
    now = now or time.time()
    put_away = await sync_to_async(kept)(who)
    fresh = [one for one in await _read(who, root, google, now) if one["key"] not in put_away]
    if not fresh:
        return None
    shown = fresh[:SHOWN]
    names = await cid.names(who, google(who).drive, list({o["doc"]["id"]: o["doc"] for o in shown}.values()))
    items = []
    for one in shown:
        doc, c = one["doc"], one["comment"]
        tasks = doc.get("tasks") or []
        items.append({
            "key": one["key"], "doc": names.get(doc["id"]) or doc.get("title") or doc["kind"],
            "kind": doc["kind"], "who": c.get("who") or "Somebody",
            "on": cid.clip(c.get("on"), 220), "words": cid.clip(c.get("words"), 500),
            "day": cid.day(cid.moment(c.get("at"))),
            "answers": len([r for r in c.get("replies") or [] if (r.get("words") or "").strip()]),
            "link": cid.link_to(doc, c["id"]),
            "task": ({"number": tasks[0]["number"], "title": tasks[0]["title"],
                      "link": "/task/" + tasks[0]["rel"]} if tasks else None)})
    return {"items": items, "count": len(fresh)}


async def again(who, brief: dict, root, google=None) -> None:
    """The section as the page opens, put on the brief it is sent with; gone when off or empty."""
    from asgiref.sync import sync_to_async

    brief.pop("new_comments", None)
    try:
        if who is None or not await sync_to_async(on)(who):
            return
        got = await found(who, root, google)
    except Exception:  # noqa: BLE001 - the rest of the brief is drawn without it
        log.exception("the new comments on the tasks' documents could not be read")
        return
    if got:
        from . import evolution

        brief["new_comments"] = {"ok": True, "source": "Your tasks' documents", **got}
        await sync_to_async(evolution.used)(SWITCH, "shown", who=who,
                                           detail=f"{got['count']} new comments on documents")


class Refused(ValueError):
    """What cannot be done with a line, in a sentence."""


def act(who, key: str, what: str) -> dict:
    """Open the comment or the task (kept as a use), Let it be, or Undo it."""
    from . import evolution

    if what == "opened":
        evolution.used(SWITCH, "opened", who=who, detail="opened a new comment on a document")
        return {"ok": True}
    if what == "task":
        evolution.used(SWITCH, "task", who=who, detail="opened the task of a new comment")
        return {"ok": True}
    held = kept(who)
    if what == "seen":
        held[key] = {"at": time.time()}
        _keep(who, held)
        evolution.used(SWITCH, "let_be", who=who, detail="let a new comment on a document be")
        return {"ok": True}
    if what == "undo":
        held.pop(key, None)
        _keep(who, held)
        return {"ok": True}
    raise Refused("Open the comment, Open the task, Let it be, or Undo.")


__all__ = ["KEPT", "SWITCH", "Refused", "act", "again", "found", "is_new", "on"]
