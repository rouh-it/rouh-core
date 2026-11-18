"""Book a meeting: the first job gene on Rouh Link (`rouh/genes/manifests/book-a-meeting.json`).

Inside a live shared space, one press ("Find a time") and the Rouhs agree a meeting between their
people without a single message between the people:

1. The Rouh whose person pressed asks each other member's Rouh it is connected to for its person's
   busy times over the window (``meeting.ask``). **Only free and busy times cross**: never what a
   meeting is, where, or with whom; each Rouh reads its own calendar.
2. With everyone's busy times, it finds the three first times all are free, in working hours, and
   puts them in the space as a **proposal**, with every person needed named.
3. **Each person taps yes** on their own screen. A proposal is never merged: each yes is that
   person's, and a Rouh can never say yes (`limits.may_change`). When every person needed said yes
   to the same time, the room's own code marks it agreed.
4. Each Rouh then puts it in **its own person's calendar** only, with "added by Rouh" in its notes,
   because its own person said yes to that very time. No Rouh writes into another's calendar.

A Rouh that is off gets the ask from the mailbox when it is back, and answers then.
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from datetime import datetime, timedelta, timezone

from . import limits, log, wire

log_ = logging.getLogger("rouh.link")
GENE = "book-a-meeting"
SWITCH = "book_a_meeting"
MOST_DAYS = 21


def on(org: str) -> bool:
    from rouh import switches

    return switches.on(SWITCH, org)


def _owner(org: str):
    from rouh import runtime

    people = runtime.tenancy.members(org)
    admins = [p for p in people if getattr(p, "is_admin", False)]
    return (admins or people or [None])[0]


def _google_for(org: str):
    from rouh import runtime

    who = _owner(org)
    factory = getattr(runtime, "brief_google", None)
    if who is None or factory is None:
        return who, None
    try:
        return who, factory(who)
    except Exception:  # noqa: BLE001
        return who, None


def _iso(d: datetime) -> str:
    return d.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _when(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


async def my_busy(org: str, begin: datetime, finish: datetime, *, silo: str = "") -> tuple[list, str]:
    """This Rouh's person's busy times: [(start, end)] and any trouble in words.

    A space with a side reads only the calendars the silo rules put on that side (Work and Personal
    stay apart), always with the calendar a meeting of that side is booked in (`book_calendar`); a
    space with no side reads the usual calendar, the person's own (which, when Rouh has a Google
    account of its own, is not the account's `primary`). Only free and busy times are asked for
    (Google's free/busy query), never what is on any calendar."""
    from rouh import free_busy

    who, services = await asyncio.to_thread(_google_for, org)
    if who is None or services is None or getattr(services, "calendar", None) is None:
        return [], "no calendar is connected on that side"
    if not await asyncio.to_thread(free_busy.on, who):
        return [], "reading free and busy times is switched off there"
    cal = services.calendar
    ids = list(await asyncio.to_thread(_calendars_of_side, who, services, silo)) if silo else []
    try:
        booked_in, _why = await book_calendar(org, who, cal, silo)
    except Exception:  # noqa: BLE001 - the calendar list could not be read; free/busy says the rest
        booked_in = "" if silo else "primary"
    if booked_in and booked_in not in ids:
        ids.append(booked_in)
    if not ids:
        return [], f"no calendar on the {_side_words(silo)} side is known there"
    try:
        got = await cal.free_busy(ids, begin, finish)
    except Exception as exc:  # noqa: BLE001
        return [], f"the calendar could not be read ({type(exc).__name__})"
    busy = []
    for one in got.values():
        busy.extend(one.get("busy") or [])
    unread = [cid for cid, one in got.items() if one.get("trouble")]
    if got and len(unread) == len(got):
        return [], "the calendar could not be read (" + ", ".join(sorted({got[c]["trouble"] for c in unread}))[:80] + ")"
    return busy, ""


def _calendars_of_side(who, services, silo: str) -> list[str]:
    """The person's calendars on one side, by the silo rules (the person's own word for which of
    their calendars are which side); [] when none says."""
    from rouh import silos

    try:
        rm = silos.rule_map(who.user_id, who.org_id)["calendar"]
    except Exception:  # noqa: BLE001
        return []
    return [cid for cid, key in rm.items() if key == silo][:10]


#: Said in the space when a Personal-side meeting is agreed and there is no calendar to put it in.
CHOOSE_PERSONAL = "Agreed; choose the calendar for Personal-side meetings on Connections to have it put in"


def _side_words(silo: str) -> str:
    return {"work": "Work", "personal": "Personal"}.get(silo, silo.capitalize())


async def book_calendar(org: str, who, cal, silo: str) -> tuple[str, str]:
    """(calendar id, "") the agreed meeting of a space on this side goes in, or ("", why not).

    The owner chooses one calendar per side on Connections (`book_calendar_work`,
    `book_calendar_personal`). With no choice, a Work-side meeting goes in the usual calendar and a
    space with no side does as it always did; any other side (Personal) is not booked at all until the
    owner chooses its calendar: never the work calendar, and never a guess (on a real account the one
    writable Personal calendar the silo rules name can be the birthdays calendar). A chosen calendar the silo rules put on another side,
    or that can no longer be written to, is refused the same way."""
    from rouh import silos

    from . import me as _me

    if not silo:
        return await cal.calendar_id(""), ""
    chosen = str((await asyncio.to_thread(_me.settings, org)).get(f"book_calendar_{silo}") or "").strip()
    listed = await cal.calendars()
    writable = {one["id"]: one for one in listed if one["writable"]}
    side = _side_words(silo)
    if chosen:
        if chosen not in writable:
            return "", (f"Agreed; the calendar chosen for {side}-side meetings cannot be written to here any more: "
                        f"choose another on Connections")
        try:
            its = (await asyncio.to_thread(silos.rule_map, who.user_id, who.org_id))["calendar"].get(chosen, "")
        except Exception:  # noqa: BLE001
            its = ""
        if its and its not in (silo, silos.EVERY):
            return "", (f"Agreed; the calendar chosen for {side}-side meetings is on the {_side_words(its)} side: "
                        f"choose another on Connections")
        return chosen, ""
    if silo == "work":
        return await cal.calendar_id(""), ""
    if silo == "personal":
        return "", CHOOSE_PERSONAL
    return "", f"Agreed; choose the calendar for {side}-side meetings on Connections to have it put in"


async def writable_calendars(org: str) -> dict:
    """What Connections shows to choose from: the owner's calendars this Rouh may write to, each with
    its side by the silo rules, and the calendar each side falls back to with no choice."""
    who, services = await asyncio.to_thread(_google_for, org)
    if who is None or services is None or getattr(services, "calendar", None) is None:
        return {"connected": False, "calendars": [], "fallback": {}}
    from rouh import silos

    cal = services.calendar
    try:
        listed = await cal.calendars()
    except Exception as exc:  # noqa: BLE001
        if type(exc).__name__ == "NotConnected":   # no Google account on this Rouh yet: said as such
            return {"connected": False, "calendars": [], "fallback": {}}
        return {"connected": True, "calendars": [], "fallback": {}, "trouble": f"the calendar list could not be read ({type(exc).__name__})"}
    try:
        rm = (await asyncio.to_thread(silos.rule_map, who.user_id, who.org_id))["calendar"]
    except Exception:  # noqa: BLE001
        rm = {}
    out = [{"id": one["id"], "name": one["name"], "access": one["access"], "primary": one["primary"],
            "side": rm.get(one["id"], "")} for one in listed if one["writable"]]
    fallback = {}
    for side in ("work", "personal"):
        try:
            fallback[side] = (await _fallback_of(org, who, cal, side))
        except Exception:  # noqa: BLE001
            fallback[side] = ""
    return {"connected": True, "calendars": out, "fallback": fallback}


async def _fallback_of(org: str, who, cal, silo: str) -> str:
    """The calendar a side's meeting goes in when nothing is chosen, or ""."""
    if silo == "work":
        got = await cal.calendar_id("")
        if got == "primary":
            got = next((one["id"] for one in await cal.calendars() if one["primary"]), got)
        return got
    return ""


def effective_side(org: str, row, my_label: str = "") -> str:
    """The side a meeting in this space is on: the space's own, else the one side every other
    member's connection here is on (a side-less task space worked on with a Family connection is a
    Personal meeting, read and booked on that side, never the work calendar), else none."""
    from . import me as _me
    from . import peers, spaces

    if row is None:
        return ""
    if row.silo:
        return row.silo
    if not my_label:
        try:
            my_label = _me.me(org).label
        except Exception:  # noqa: BLE001
            my_label = ""
    labels = {m["label"] for m in spaces.members_of(row) if m.get("label") and m["label"] != my_label}
    if not row.mine and row.holder_label and row.holder_label != my_label:
        labels.add(row.holder_label)
    sides = set()
    for label in labels:
        peer = peers.peer_row(org, label)
        sides.add((peer.silo if peer is not None else "") or "")
    return sides.pop() if len(sides) == 1 else ""


def _meta_meetings(row) -> dict:
    return dict((row.meta or {}).get("meetings") or {})


def _save_meeting(org: str, sid: str, ask_id: str, entry: dict) -> None:
    from rouh.models import LinkSpace

    from . import spaces

    row = spaces._row(org, sid)
    if row is None:
        return
    meets = _meta_meetings(row)
    meets[ask_id] = entry
    LinkSpace.objects.filter(id=row.id).update(meta=dict(row.meta or {}, meetings=meets))


async def start(org: str, sid: str, *, minutes: int = 30, days: int = 7) -> dict:
    """The person pressed Find a time: ask the others' Rouhs, then propose three times."""
    from rouh import clock

    from . import me as _me
    from . import peers, spaces

    if not await asyncio.to_thread(on, org):
        raise limits.No("Book a meeting is switched off on this Rouh.")
    from rouh import evolution

    evolution.used(SWITCH, "found_time", who=_owner(org), detail=f"{int(minutes or 30)} minutes")
    minutes = max(15, min(240, int(minutes or 30)))
    days = max(1, min(MOST_DAYS, int(days or 7)))
    me = await asyncio.to_thread(_me.me, org)
    row = await asyncio.to_thread(spaces._row, org, sid)
    if row is None or row.state != "live":
        raise limits.No("That space is not live.")
    now = clock.now()
    begin = (now + timedelta(minutes=60)).replace(second=0, microsecond=0)
    finish = begin + timedelta(days=days)
    others = [m for m in spaces.members_of(row) if m["label"] != me.label and m.get("state") == "joined"]
    if not row.mine and row.holder_label not in [m["label"] for m in others]:
        others.append({"label": row.holder_label})
    ask_id = uuid.uuid4().hex[:16]
    mine, trouble = await my_busy(org, begin, finish, silo=await asyncio.to_thread(effective_side, org, row, me.label))
    entry = {"minutes": minutes, "from": _iso(begin), "until": _iso(finish), "busy": {me.label: [[_iso(a), _iso(b)] for a, b in mine]},
             "trouble": {me.label: trouble} if trouble else {}, "waiting": [], "at": time.time(), "by": me.label,
             "zone": str(getattr(now.tzinfo, "key", "") or "")}
    actor = f"rouh:{me.label}"
    await spaces.change(org, sid, [spaces.new_op("doing", actor, words=f"Finding a {minutes}-minute time: asking for free and busy times only")])
    for m in others:
        peer = await asyncio.to_thread(peers.peer_row, org, m["label"])
        if peer is None or peer.state != "connected":
            entry["trouble"][m["label"]] = "not connected to this Rouh"
            continue
        body = {"ask_id": ask_id, "space_id": sid, "minutes": minutes, "from": entry["from"], "until": entry["until"]}
        try:
            got = await wire.ask(org, peer, "meeting.ask", body, timeout=20)
            from . import forms

            form = forms.read_message("meeting.busy", got)
            entry["busy"][peer.label] = form["busy"]
            if form.get("trouble"):
                entry["trouble"][peer.label] = str(form["trouble"])
        except wire.Unreachable:
            await asyncio.to_thread(wire.queue, org, peer, "meeting.ask", body)
            entry["waiting"].append(peer.label)
        except (wire.Refusal, Exception) as exc:  # noqa: BLE001
            entry["trouble"][peer.label] = str(getattr(exc, "said", exc))[:200]
    await asyncio.to_thread(_save_meeting, org, sid, ask_id, entry)
    if entry["waiting"]:
        names = ", ".join(entry["waiting"])
        await spaces.change(org, sid, [spaces.new_op("doing", actor, words=f"Waiting for {names}'s Rouh, which is off; the times come when it is back")])
        return {"ask_id": ask_id, "waiting": entry["waiting"]}
    return await _propose(org, sid, ask_id)


async def _propose(org: str, sid: str, ask_id: str) -> dict:
    from rouh import clock, free_busy

    from . import me as _me
    from . import spaces

    me = await asyncio.to_thread(_me.me, org)
    row = await asyncio.to_thread(spaces._row, org, sid)
    entry = _meta_meetings(row).get(ask_id)
    if entry is None or entry.get("proposed"):
        return {}
    zone = clock.now().tzinfo
    begin, finish = _when(entry["from"]), _when(entry["until"])
    lists = [[(_when(a), _when(b)) for a, b in busy] for busy in entry["busy"].values()]
    found = free_busy.common_free(lists, begin, finish, entry["minutes"], zone, most=12)
    options = []
    length = timedelta(minutes=entry["minutes"])
    for a, _b in found:
        if len(options) >= 3:
            break
        if options and abs((a - _when(options[-1]["start"])).total_seconds()) < 3 * 3600:
            continue
        options.append({"id": uuid.uuid4().hex[:8], "label": f"{a:%A %-d %B, %H:%M}-{(a + length):%H:%M}",
                        "start": _iso(a), "end": _iso(a + length)})
    for a, _b in found:
        if len(options) >= 3:
            break
        if all(o["start"] != _iso(a) for o in options):
            options.append({"id": uuid.uuid4().hex[:8], "label": f"{a:%A %-d %B, %H:%M}-{(a + length):%H:%M}",
                            "start": _iso(a), "end": _iso(a + length)})
    needed = sorted(entry["busy"].keys())
    actor = f"rouh:{me.label}"
    entry["proposed"] = True
    await asyncio.to_thread(_save_meeting, org, sid, ask_id, entry)
    if not options:
        await spaces.change(org, sid, [spaces.new_op("doing", actor, words="No time when everyone is free in that window; try a longer window")])
        return {"options": []}
    title = str((row.doc or {}).get("fields", {}).get("title", {}).get("v") or row.title or "Meeting")[:120]
    pid = uuid.uuid4().hex[:12]
    trouble = entry.get("trouble") or {}
    await spaces.change(org, sid, [spaces.new_op(
        "propose", actor, pid=pid, what="meeting", title=f"Meeting: {title}", options=options[:3],
        needed=needed, minutes=entry["minutes"])] + ([spaces.new_op(
            "doing", actor, words="Could not read: " + "; ".join(f"{k}: {v}" for k, v in trouble.items())[:180])] if trouble else []))
    log.write(org, "meeting", f"Proposed three times for “{title}”, from free and busy times only.", space=sid)
    return {"pid": pid, "options": options[:3]}


@wire.handles("meeting.ask")
async def _ask(ctx, form) -> dict:
    """Another Rouh asks this one's person's busy times, for a meeting in a space both are in."""
    from . import spaces

    if not await asyncio.to_thread(on, ctx.org):
        raise limits.No("Book a meeting is switched off on this Rouh.")
    sid = form.get("space_id") or ""
    silo = ctx.peer.silo or ""
    if sid:
        row = await asyncio.to_thread(spaces._row, ctx.org, sid)
        if row is None or row.state != "live":
            raise limits.No("That space is not live here.")
        if not (row.holder_label == ctx.peer.label or spaces.role_of(row, ctx.peer.label)):
            raise limits.No("You are not in that space.")
        silo = await asyncio.to_thread(effective_side, ctx.org, row) or silo
    begin, finish = _when(form["from"]), _when(form["until"])
    if finish <= begin or finish - begin > timedelta(days=MOST_DAYS + 1):
        raise limits.No("That window is too long.")
    busy, trouble = await my_busy(ctx.org, begin, finish, silo=silo)
    await asyncio.to_thread(log.write, ctx.org, "meeting",
                            f"Told {ctx.peer.name} when this Rouh's person is busy ({len(busy)} busy times), "
                            f"nothing else.", peer=ctx.peer.label, space=sid)
    return {"ask_id": form["ask_id"], "busy": [[_iso(a), _iso(b)] for a, b in busy],
            **({"trouble": trouble} if trouble else {})}


@wire.handles("meeting.busy")
async def _busy(ctx, form) -> dict:
    """The busy times of a Rouh that was off when asked, arriving by the mailbox."""
    from rouh.models import LinkSpace

    def find():
        for row in LinkSpace.objects.filter(org_id=ctx.org, state="live"):
            if form["ask_id"] in _meta_meetings(row):
                return row
        return None

    row = await asyncio.to_thread(find)
    if row is None:
        return {}
    entry = _meta_meetings(row)[form["ask_id"]]
    entry["busy"][ctx.peer.label] = form["busy"]
    entry["waiting"] = [w for w in entry.get("waiting", []) if w != ctx.peer.label]
    await asyncio.to_thread(_save_meeting, ctx.org, row.space_id, form["ask_id"], entry)
    if not entry["waiting"]:
        await _propose(ctx.org, row.space_id, form["ask_id"])
    return {}


async def after_changes(org: str, sid: str, live) -> None:
    """Book an agreed time in this Rouh's own person's calendar, once, when that person said yes to it."""
    from . import me as _me

    if not live.doc.get("proposals"):
        return
    try:
        me = await asyncio.to_thread(_me.me, org)
    except Exception:  # noqa: BLE001
        return
    for pid, prop in list(live.doc["proposals"].items()):
        if _ours_to_book(me.label, prop):
            asyncio.ensure_future(_book(org, sid, pid, prop))


def _ours_to_book(label: str, prop: dict) -> bool:
    """An agreed meeting this Rouh's own person said yes to, at the very time chosen."""
    if prop.get("kind") != "meeting" or prop.get("state") != "agreed" or not prop.get("chosen"):
        return False
    mine = (prop.get("yes") or {}).get(label)
    return bool(mine) and mine["option"] == prop["chosen"] and (mine["by"] == f"person:{label}" or bool(mine.get("grant")))


_BOOKING: set = set()


#: What `booked` holds for an agreed meeting that waits for its side's calendar to be chosen.
WAITING = "waiting-calendar"


async def book_waiting(org: str) -> int:
    """After a calendar is chosen on Connections: put in every agreed meeting that waited for one."""
    from rouh.models import LinkSpace

    from . import me as _me
    from . import spaces

    me = await asyncio.to_thread(_me.me, org)
    rows = await asyncio.to_thread(lambda: [r.space_id for r in LinkSpace.objects.filter(org_id=org, state="live")
                                            if WAITING in ((r.meta or {}).get("booked") or {}).values()])
    tried = 0
    for sid in rows:
        try:
            live = await spaces.get(org, sid)
        except Exception:  # noqa: BLE001
            continue
        row = await asyncio.to_thread(spaces._row, org, sid)
        booked = (row.meta or {}).get("booked") or {}
        for pid, prop in list((live.doc.get("proposals") or {}).items()):
            if booked.get(pid) == WAITING and _ours_to_book(me.label, prop):
                tried += 1
                await _book(org, sid, pid, prop, retry=True)
    return tried


async def _book(org: str, sid: str, pid: str, prop: dict, *, retry: bool = False) -> None:
    from rouh.models import LinkSpace

    from . import me as _me
    from . import spaces

    key = (org, sid, pid)
    if key in _BOOKING:
        return
    _BOOKING.add(key)
    try:
        row = await asyncio.to_thread(spaces._row, org, sid)
        booked = dict((row.meta or {}).get("booked") or {})
        if pid in booked and not (retry and booked[pid] == WAITING):
            return
        opt = next((o for o in prop["options"] if o["id"] == prop["chosen"]), None)
        if opt is None or not opt.get("start"):
            return
        me = await asyncio.to_thread(_me.me, org)
        who, services = await asyncio.to_thread(_google_for, org)
        actor = f"rouh:{me.label}"
        if services is None or getattr(services, "calendar", None) is None:
            await spaces.change(org, sid, [spaces.new_op("doing", actor, words="Agreed; no calendar is connected here to put it in")])
            booked[pid] = "no-calendar"
        else:
            others = [m.get("name") or m["label"] for m in spaces.members_of(row) if m["label"] != me.label]
            notes = (f"Agreed in the live shared space “{row.title[:100]}” with {', '.join(others)[:200]}, "
                     f"each person saying yes to this time (Rouh Link).\n\nadded by Rouh")
            cal = services.calendar
            try:
                side = await asyncio.to_thread(effective_side, org, row, me.label)
                into, why_not = await book_calendar(org, who, cal, side)
            except Exception as exc:  # noqa: BLE001 - said in the space, never left silent
                into, why_not = "", f"Agreed; could not read the calendar list here ({type(exc).__name__})"
            if not into:
                if not retry:
                    await spaces.change(org, sid, [spaces.new_op("doing", actor, words=why_not)])
                booked[pid] = WAITING
                await asyncio.to_thread(lambda: LinkSpace.objects.filter(id=row.id).update(
                    meta=dict(spaces._row(org, sid).meta or {}, booked=booked)))
                return
            try:
                made = await cal.create(into, title=prop["title"][:200], start=_when(opt["start"]),
                                        end=_when(opt["end"]), description=notes, notify=False)
            except Exception as exc:  # noqa: BLE001 - said in the space, never left silent
                await spaces.change(org, sid, [spaces.new_op(
                    "doing", actor, words=f"Agreed; could not put it in the calendar here ({type(exc).__name__})")])
                booked[pid] = "failed"
                made = None
            if made is None:
                await asyncio.to_thread(lambda: LinkSpace.objects.filter(id=row.id).update(
                    meta=dict(spaces._row(org, sid).meta or {}, booked=booked)))
                return
            booked[pid] = str((made or {}).get("id") or "booked")
            from rouh import evolution

            evolution.used(SWITCH, "booked", who=who, detail=opt["label"])
            await spaces.change(org, sid, [spaces.new_op("doing", actor, words=f"Put it in {me.tagged}'s person's calendar: {opt['label']}")])
            await asyncio.to_thread(log.write, org, "booked", f"Booked “{prop['title'][:80]}” for {opt['label']} in this "
                                    f"Rouh's person's own calendar, after their yes.", space=sid)
        await asyncio.to_thread(lambda: LinkSpace.objects.filter(id=row.id).update(
            meta=dict(spaces._row(org, sid).meta or {}, booked=booked)))
    except Exception:  # noqa: BLE001
        log_.exception("booking an agreed meeting failed")
    finally:
        _BOOKING.discard(key)
