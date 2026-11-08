"""Waiting on your answer, in the brief: emails from people that asked ‹him› something, still unanswered.

Built by the nightly feature run, night 33 of this Rouh (the ledger's night 37), 8 November 2026
(task 94), from the Incubator's INC-135. Night 34's Waiting on your answer (`rouh/to_answer.py`)
finds them when ‹owner› asks "what haven't I answered?", and ‹he› has to remember to ask. The
morning brief has had Needs you in Slack since 16 October 2026, and for mail only how much came in.
An email that asked ‹him› something, read on a phone between two meetings and never answered, sat
there until its sender wrote again.

So, while its switch is on, the morning brief has a section **Waiting on your answer**, read afresh
when the page opens (kept for `FRESH` seconds), with no model:

- **Which.** Every conversation `to_answer.scan` finds in the inboxes ‹he› gave Rouh (its own
  connection and each read-only one), of the last `DAYS` days: the last word is a person's, written
  to ‹him›, not a list, a machine or an invitation; of those only the ones that **asked ‹him›
  something** (`ghosts.the_ask`), and that have waited at least `LEAST_HOURS` hours, oldest first.
- **Each line.** Who, how long it has waited, the subject, and what they asked in their own words;
  **Open the email**, which opens the conversation in Gmail in that account, to answer it from
  there (Open in Gmail); and **No answer needed**, which takes the line off this list only, the email staying in the inbox, telling nobody, with Undo. A line
  ‹he› answered goes by itself the next time the page opens, because the last word is then ‹his›.

**Whose.** ‹His› own mailboxes, read with GET alone, and ‹his› own setting (`user_settings`,
`answer_waiting`), by `org_id` and `user_id`. Nothing is sent, and nothing in a mailbox changes.

**Its switch** is `answer_waiting` (`rouh/switches.py`): off, the section is not there and the route
refuses.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime

log = logging.getLogger("rouh.answer_waiting")

SWITCH = "answer_waiting"
TITLE = ("Waiting on your answer, in the brief: emails from people that asked you something and are still "
         "unanswered, in the morning brief")
KEPT = "answer_waiting"
DAYS = 14
#: An email younger than this, in hours, is not said yet: it may be answered today.
LEAST_HOURS = 20
MOST = 6
#: How long one reading of the mailboxes is used again, in seconds, and the longest it may take.
FRESH = 15 * 60
SECONDS = 12.0
ACTS = ("open", "put_away", "undo")

_seen: dict[tuple[str, str], tuple[float, list[dict]]] = {}


class Refused(ValueError):
    """What cannot be done with a line, in a sentence."""


def on(who) -> bool:
    from . import switches

    if who is None:
        return False
    return switches.on(SWITCH, getattr(who, "org_id", None) or None)


def key_of(one: dict) -> str:
    """One line's key: the conversation and its last email, so a new email from them brings it back."""
    return f"{one.get('mailbox') or ''}:{one.get('thread_id') or ''}:{int(one.get('at') or 0)}"[:100]


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

    # Only what could still be shown is worth keeping.
    cut = time.time() - (DAYS + 7) * 86400
    held = {k: v for k, v in held.items() if (v.get("at") or 0) >= cut}
    UserSetting.objects.bulk_create(
        [UserSetting(user_id=str(who.user_id), org_id=who.org_id or "", name=KEPT,
                     value=json.dumps(held), updated_at=time.time())],
        update_conflicts=True, unique_fields=["user_id", "name"],
        update_fields=["org_id", "value", "updated_at"])


async def read_all(who) -> list[dict]:
    """Every conversation waiting on the person's answer, every mailbox, each with its mailbox."""
    from asgiref.sync import sync_to_async

    from . import ghosts, runtime, to_answer

    auth, cfg = runtime.mailbox_auth, runtime.config
    if auth is None:
        return []
    out: list[dict] = []
    for source in await sync_to_async(ghosts.sources)(who, auth):
        if source.needs_reconnect:
            continue
        try:
            reader = await sync_to_async(ghosts._reader)(who, auth, cfg, source)
            if reader is None:
                continue
            for one in await to_answer.scan(reader, days=DAYS):
                out.append(dict(one, mailbox=source.email, read_only=source.read_only))
        except Exception as exc:  # noqa: BLE001 - one mailbox's trouble never stops the rest
            log.info("waiting on your answer: %s could not be read: %s", source.email, exc)
    return out


def _waited(at: float, now: float, zone) -> str:
    """How long, by the days on the person's calendar: written Thursday, read Sunday, is 3 days."""
    days = (datetime.fromtimestamp(now, zone).date() - datetime.fromtimestamp(at, zone).date()).days
    if days <= 1:
        return "since yesterday" if days == 1 else "since this morning"
    return f"for {days} days" if days < 14 else f"for {days // 7} weeks"


def lines(found: list[dict], put_away: dict, zone, now: float | None = None) -> list[dict]:
    """The section's lines: the ones that asked something, waited long enough, oldest first."""
    from . import ghosts

    now = now or time.time()
    out = []
    for one in found:
        if not one.get("ask") or now - (one.get("at") or now) < LEAST_HOURS * 3600:
            continue
        key = key_of(one)
        if key in put_away:
            continue
        at = datetime.fromtimestamp(one["at"], zone)
        out.append({
            "key": key, "name": one.get("name") or one["email"], "email": one["email"],
            "others": one.get("others") or 0, "subject": one.get("subject") or "(no subject)",
            "ask": one["ask"], "waited": _waited(one["at"], now, zone), "days": int((now - one["at"]) // 86400),
            "when": f"{at:%A} {at.day} {at:%B}, {at:%H:%M}",
            "mailbox": one["mailbox"], "read_only": bool(one.get("read_only")),
            "link": ghosts.link_to(one["mailbox"], one["thread_id"])})
    out.sort(key=lambda i: -i["days"])
    return out


async def found_for(who, *, fresh: bool = False) -> list[dict]:
    """The conversations read from the mailboxes, read again when older than `FRESH`."""
    mark = (str(who.org_id or ""), str(who.user_id))
    held = _seen.get(mark)
    if held and not fresh and time.time() - held[0] < FRESH:
        return held[1]
    got = await asyncio.wait_for(read_all(who), SECONDS)
    _seen[mark] = (time.time(), got)
    return got


async def again(who, brief: dict) -> None:
    """The section as the page opens, put on the brief it is sent with; gone when off or empty."""
    from asgiref.sync import sync_to_async

    from . import clock

    brief.pop("answer_waiting", None)
    try:
        if who is None or not await sync_to_async(on)(who):
            return
        zone = clock.zone_of(who)
        got = lines(await found_for(who), await sync_to_async(kept)(who), zone)
    except Exception:  # noqa: BLE001 - the rest of the brief is drawn without it
        log.exception("waiting on your answer, in the brief, could not be read")
        return
    if got:
        from . import evolution

        brief["answer_waiting"] = {"ok": True, "source": "Your inboxes", "items": got[:MOST], "count": len(got)}
        await sync_to_async(evolution.used)(SWITCH, "shown", who=who,
                                         detail=f"{len(got)} emails asking him something, unanswered")


def act(who, key: str, what: str) -> dict:
    """Open in Gmail (a use), No answer needed, or Undo it."""
    from . import evolution

    if what not in ACTS or not key:
        raise Refused("Open in Gmail, No answer needed, or Undo.")
    if what == "open":
        evolution.used(SWITCH, "opened", who=who, detail="opened an email waiting on his answer")
        return {"ok": True}
    held = kept(who)
    if what == "put_away":
        held[key] = {"at": time.time()}
        _keep(who, held)
        evolution.used(SWITCH, "put_away", who=who, detail="put away an email that needs no answer")
        return {"ok": True}
    held.pop(key, None)
    _keep(who, held)
    return {"ok": True}


__all__ = ["ACTS", "DAYS", "KEPT", "SWITCH", "TITLE", "Refused", "act", "again", "found_for", "key_of", "lines",
           "on", "read_all"]
