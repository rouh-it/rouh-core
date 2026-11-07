"""Not opened yet: a page or a task ‹he› shared for somebody to read, not opened after two days, in the
morning brief, with Write to them.

Built by the nightly feature run, night 25, 28 October 2026 (task 94, idea I-154). Since night 18
(Who opened it, `rouh/share_opens.py`, kept by ‹him› on 27 October 2026) the Share panel says beside
each person when they last opened what was shared with them, or "Not opened yet". But the panel
says it only when ‹he› opens it, on that one page, and a page shared for a meeting or a decision
waits on the other person: of the fifteen Work pages and tasks ‹he› shared by hand from 24 September
to 27 October 2026, three went to a person outside the company before a meeting. Whether they read
it is the question before the meeting, and one nobody answers by itself.

So, while its switch is on, the morning brief has a section **Not opened yet**, read as the page
opens, with no model: each page or task ‹he› shared with somebody by hand (not a share a trusted
contact's tick keeps), whose invitation went out, between `AFTER_DAYS` and `DAYS` days ago, that
they have not opened since. Each line says what it is, whom it was shared with, when and with what
level, and opens the page. **Write to them** opens Gmail's own new-message window in ‹his› own
mailbox, to them, with the page's name as the subject and a short note with their own link, so
the reminder is one press there and in ‹his› own words if ‹he› changes it; **Let it be** puts it
away, with Undo. A line goes by itself once they open it.

Only shares made after opens began to be kept (`KEPT_SINCE`) are read, because before then
nothing says whether a share was opened.

**Whose.** ‹His› own shares (`page_guests`, by `user_id` and `org_id`) and ‹his› own opens
(`share_opens.last_opens`), read only; what ‹he› put away is ‹his› own setting (`user_settings`,
`not_opened`). Nothing is sent: the note is written in ‹his› own Gmail, by ‹him›.

**Its switch** is `not_opened` (`rouh/switches.py`), and it needs `share_opens` on too, since
without it no open is kept: off, the section is not there.
"""
from __future__ import annotations

import json
import logging
import time
from urllib.parse import quote, urlencode

log = logging.getLogger("rouh.not_opened")

SWITCH = "not_opened"
TITLE = ("Not opened yet: a page you shared for somebody to read, not opened after two days, in "
         "the morning brief, with Write to them")
#: A share is said once it is this many days old, and not after this many.
AFTER_DAYS, DAYS = 2, 14
#: The most lines shown.
SHOWN = 8
#: Opens are kept since Who opened it was built (21 October 2026, 00:00 UTC).
KEPT_SINCE = 1792540800.0
#: The person's own setting: {token key: {"at"}}.
KEPT = "not_opened"


def on(who) -> bool:
    from . import share_opens, switches

    org = getattr(who, "org_id", None) or None
    return switches.on(SWITCH, org) and share_opens.on(org)


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

    UserSetting.objects.bulk_create(
        [UserSetting(user_id=str(who.user_id), org_id=who.org_id or "", name=KEPT,
                     value=json.dumps(held), updated_at=time.time())],
        update_conflicts=True, unique_fields=["user_id", "name"],
        update_fields=["org_id", "value", "updated_at"])


def _day(at: float) -> str:
    from datetime import datetime

    from . import clock

    here = datetime.fromtimestamp(at, clock.zone())
    return f"{here:%A} {here.day} {here:%B}"


def _title(row) -> str:
    rel = str(row.rel or "")
    if row.title:
        return row.title
    folder = rel[len("_task/"):] if rel.startswith("_task/") else rel.rsplit("/", 1)[0]
    return folder.rsplit("/", 1)[-1].split(".", 1)[-1].replace("-", " ").strip() or rel


def _base() -> str:
    from .config import config

    return str(getattr(config, "public_url", "") or "").rstrip("/")


def compose_link(inbox: str, to: str, title: str, link: str) -> str:
    """Gmail's own new-message window in ‹his› mailbox, to them, about the page, filled in."""
    body = (f"Hi,\n\nI shared \"{title}\" with you a few days ago. "
            "Did you get a chance to look at it?\n\n" + link + "\n")
    asked = {"view": "cm", "fs": "1", "to": to, "su": title, "body": body}
    if inbox:
        asked = {"authuser": inbox, **asked}
    return "https://mail.google.com/mail/?" + urlencode(asked, quote_via=quote)


def _waiting(who, now: float | None = None) -> list[dict]:
    """‹His› shares made by hand, mailed, two to fourteen days old, never opened, newest first."""
    from . import share_opens
    from .models import PageGuest

    now = now or time.time()
    since = max(KEPT_SINCE, now - DAYS * 86400)
    rows = list(PageGuest.objects
                .filter(user_id=who.user_id, org_id=who.org_id, via="", pending="",
                        mailed_at__isnull=False, created_at__gte=since,
                        created_at__lte=now - AFTER_DAYS * 86400)
                .order_by("-created_at")[:200])
    if not rows:
        return []
    opened = share_opens.last_opens(who, [r.token for r in rows])
    return [{"token": r.token, "rel": r.rel, "title": _title(r), "email": r.email,
             "role": r.role, "at": float(r.created_at)}
            for r in rows if r.token not in opened]


def found(who, now: float | None = None) -> dict | None:
    """{items, count} for the brief, or None when every page shared by hand has been opened."""
    from . import inboxes

    put_away = kept(who)
    waiting = [w for w in _waiting(who, now) if share_opens_key(w["token"]) not in put_away]
    if not waiting:
        return None
    mine = inboxes.theirs(who)
    inbox = mine[0].email if mine else ""
    base = _base()
    items = []
    for w in waiting[:SHOWN]:
        theirs = (base + "/shared/" + w["token"]) if base else ""
        rel = w["rel"]
        own = "/task/" + (rel[len("_task/"):] if rel.startswith("_task/") else rel)
        items.append({"key": share_opens_key(w["token"]), "title": w["title"],
                      "kind": "task" if rel.startswith("_task/") else "page",
                      "email": w["email"], "level": "edit" if w["role"] == "edit" else "read",
                      "day": _day(w["at"]), "days": int((time.time() - w["at"]) // 86400),
                      "link": own,
                      "write": compose_link(inbox, w["email"], w["title"], theirs or own)})
    return {"items": items, "count": len(waiting)}


def share_opens_key(token: str) -> str:
    from . import share_opens

    return share_opens.key(token)


async def again(who, brief: dict) -> None:
    """The section as the page opens, put on the brief it is sent with; gone when off or empty."""
    from asgiref.sync import sync_to_async

    brief.pop("not_opened", None)
    try:
        if who is None or not await sync_to_async(on)(who):
            return
        got = await sync_to_async(found)(who)
    except Exception:  # noqa: BLE001 - the rest of the brief is drawn without it
        log.exception("the pages shared and not opened could not be read")
        return
    if got:
        from . import evolution

        brief["not_opened"] = {"ok": True, "source": "Your shares", **got}
        await sync_to_async(evolution.used)(SWITCH, "shown", who=who,
                                           detail=f"{got['count']} shared pages not opened yet")


class Refused(ValueError):
    """What cannot be done with a line, in a sentence."""


def act(who, key: str, what: str) -> dict:
    """Write to them (the press, kept as a use), Let it be, or Undo it."""
    from . import evolution

    held = kept(who)
    if what == "write":
        evolution.used(SWITCH, "wrote", who=who,
                       detail="opened a reminder to somebody who had not opened a shared page")
        return {"ok": True}
    if what == "opened":
        evolution.used(SWITCH, "opened", who=who, detail="opened a page shared and not opened yet")
        return {"ok": True}
    if what == "seen":
        held[key] = {"at": time.time()}
        _keep(who, held)
        evolution.used(SWITCH, "let_be", who=who, detail="let a shared page that was not opened be")
        return {"ok": True}
    if what == "undo":
        held.pop(key, None)
        _keep(who, held)
        return {"ok": True}
    raise Refused("Write to them, Let it be, or Undo.")


__all__ = ["KEPT", "SWITCH", "Refused", "act", "again", "compose_link", "found", "on"]
