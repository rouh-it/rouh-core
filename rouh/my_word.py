"""Your word, by mail: what the person promised somebody by email, in the brief when its day comes.

Built by the nightly feature run, night 32 of this Rouh (the ledger's night 36), 7 November 2026
(task 94). "I'll send you the signed contract by Friday", "ще ти изпратя офертата утре": ‹owner›
promises things by email many times a week, on a phone between two meetings, and nothing keeps them.
A promise made in Slack has been a Clockwork reminder since 16 October 2026 (`rouh/slack_promises.py`);
one made by email was kept only in ‹his› head, and the first sign of one forgotten was the other
side asking for it.

So, while its switch is on, the morning brief has a section **Your word, by mail**, read afresh when
the page opens (kept for `FRESH` seconds) and with no model:

- **Which.** Each sentence of ‹his› own sent mail of the last `DAYS` days, in every mailbox ‹he› gave
  Rouh (its own connection and each read-only one, `ghosts.sources`), that promises something by a
  day (`rouh/mail_promises.py`), to people (not to ‹him›self, a machine or a crowd), whose day is
  today or tomorrow, or passed in the last `PAST_DAYS` days.
- **Not when ‹he› wrote to them again.** A later email from ‹him› to the same person, in any
  conversation, takes it off: what ‹he› promised may well be in it.
- **Each line.** To whom, what ‹he› said ‹he› would do, and the day, how near or how late; **What
  you wrote**, closed at first: the email's subject, when it went, and the sentence in its words;
  **Open the email**, which opens the conversation in Gmail in that account, to send it from there;
  and **Mark as done**, which takes the line off the list, telling nobody, with Undo.

**Whose.** ‹His› own mailboxes, read with GET alone, and ‹his› own setting (`user_settings`,
`my_word`), by `org_id` and `user_id`. Nothing is sent, and nothing in a mailbox changes.

**Its switch** is `my_word` (`rouh/switches.py`): off, the section is not there.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import date, datetime

log = logging.getLogger("rouh.my_word")

SWITCH = "my_word"
TITLE = ("Your word, by mail: what you promised somebody by email, by a day, in the morning brief when "
         "the day comes, unless you have written to them since")
KEPT = "my_word"
DAYS = 21
PAST_DAYS = 7
AHEAD_DAYS = 1
MOST = 6
#: How long one reading of the mailboxes is used again, in seconds, and the longest it may take.
FRESH = 15 * 60
SECONDS = 12.0
ACTS = ("open", "context", "done", "undo")

_seen: dict[tuple[str, str], tuple[float, list[dict]]] = {}


class Refused(ValueError):
    """What cannot be done with a line, in a sentence."""


def on(who) -> bool:
    from . import switches

    if who is None:
        return False
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

    # Only the last two months are worth keeping: older promises are never read again.
    cut = time.time() - 60 * 86400
    held = {k: v for k, v in held.items() if (v.get("at") or 0) >= cut}
    UserSetting.objects.bulk_create(
        [UserSetting(user_id=str(who.user_id), org_id=who.org_id or "", name=KEPT,
                     value=json.dumps(held), updated_at=time.time())],
        update_conflicts=True, unique_fields=["user_id", "name"],
        update_fields=["org_id", "value", "updated_at"])


async def read_all(who, zone) -> list[dict]:
    """Every promise with a day in the person's sent mail, every mailbox, each with its mailbox."""
    from asgiref.sync import sync_to_async

    from . import ghosts, mail_promises, runtime

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
            for one in await mail_promises.scan_sent(reader, zone, days=DAYS, mailbox=source.email):
                out.append(dict(one, mailbox=source.email, read_only=source.read_only))
        except Exception as exc:  # noqa: BLE001 - one mailbox's trouble never stops the rest
            log.info("your word: %s could not be read: %s", source.email, exc)
    return out


def lines(found: list[dict], put_away: dict, zone, today: date) -> list[dict]:
    """The section's lines: late first (the latest first), then today's, then tomorrow's."""
    from . import ghosts, mail_promises

    out = []
    for one in found:
        if one.get("wrote_since") or one["key"] in put_away:
            continue
        days = (one["due"] - today).days
        if days < -PAST_DAYS or days > AHEAD_DAYS:
            continue
        person = one["to"][0]
        sent = datetime.fromtimestamp(one["at"], zone)
        out.append({
            "key": one["key"], "to": person["name"] or person["email"], "email": person["email"],
            "others": max(0, len(one["to"]) - 1), "sentence": one["sentence"], "said_when": one["when"],
            "due": one["due"].isoformat(), "days": days, "when": mail_promises.day_words(one["due"], today),
            "subject": one["subject"], "sent": f"{sent:%A} {sent.day} {sent:%B}, {sent:%H:%M}",
            "mailbox": one["mailbox"], "read_only": bool(one.get("read_only")),
            "link": ghosts.link_to(one["mailbox"], one["thread_id"])})
    out.sort(key=lambda i: i["days"])
    return out


async def found_for(who, zone, *, fresh: bool = False) -> list[dict]:
    """The promises read from the mailboxes, read again when older than `FRESH`."""
    mark = (str(who.org_id or ""), str(who.user_id))
    held = _seen.get(mark)
    if held and not fresh and time.time() - held[0] < FRESH:
        return held[1]
    got = await asyncio.wait_for(read_all(who, zone), SECONDS)
    _seen[mark] = (time.time(), got)
    return got


async def again(who, brief: dict) -> None:
    """The section as the page opens, put on the brief it is sent with; gone when off or empty."""
    from asgiref.sync import sync_to_async

    from . import clock

    brief.pop("my_word", None)
    try:
        if who is None or not await sync_to_async(on)(who):
            return
        zone = clock.zone_of(who)
        today = datetime.now(zone).date()
        got = lines(await found_for(who, zone), await sync_to_async(kept)(who), zone, today)
    except Exception:  # noqa: BLE001 - the rest of the brief is drawn without it
        log.exception("your word, by mail, could not be read")
        return
    if got:
        from . import evolution

        brief["my_word"] = {"ok": True, "source": "Your sent mail", "items": got[:MOST], "count": len(got),
                            "late": len([1 for one in got if one["days"] < 0])}
        await sync_to_async(evolution.used)(SWITCH, "shown", who=who,
                                          detail=f"{len(got)} promises by mail due or late")


def act(who, key: str, what: str) -> dict:
    """Open the email, What you wrote (each kept as a use), Done, or Undo it."""
    from . import evolution

    if what not in ACTS or not key:
        raise Refused("Open the email, Done, or Undo.")
    if what == "open":
        evolution.used(SWITCH, "opened", who=who, detail="opened an email he promised something in")
        return {"ok": True}
    if what == "context":
        evolution.used(SWITCH, "context", who=who, detail="read what he wrote in a promise by mail")
        return {"ok": True}
    held = kept(who)
    if what == "done":
        held[key] = {"at": time.time()}
        _keep(who, held)
        evolution.used(SWITCH, "done", who=who, detail="put away a promise he made by mail")
        return {"ok": True}
    held.pop(key, None)
    _keep(who, held)
    return {"ok": True}


__all__ = ["ACTS", "DAYS", "KEPT", "SWITCH", "TITLE", "Refused", "act", "again", "found_for", "lines", "on",
           "read_all"]
