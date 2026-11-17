"""Live shared spaces: the room held by the owner's Rouh, and each member's own copy.

**The room** (one per space, in the process of the Rouh that made the space, never on the relay):
every change from anyone, the people and Rouhs here and the members' Rouhs, comes to `submit`,
which checks it in code (`limits.may_change`: role, claims, who may decide what), gives it the
next number in the one order, keeps it, and wakes everyone waiting. A member's Rouh waits on the
room with a long poll (``room.poll``), so a change reaches every member in well under a second.

**A member's copy**: a member keeps every change the room confirmed, in its own database, and the
space as they add up (`doc.replay`). Its own changes show at once (pending, on top) and go to the
room; the room's answer confirms or refuses each. If the room cannot be reached they wait (the
outbox, then the mailbox) and the copy keeps working; on its return they are put on top of what the
room has, which the text CRDT and last-writer-wins make the same on every copy.

**A person's page** asks its own Rouh only (`live_state`, a long poll on this process), whether this
Rouh holds the room or is a member: the page never talks to another Rouh.

Presence (who is in now, people and Rouhs, each Rouh's marker and what it is doing) lives in memory
only and is never saved.
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid

from . import doc as _doc
from . import forms, kinds, limits, log, trust, wire

log_ = logging.getLogger("rouh.link")

#: A person whose page asked within this many seconds is "in".
FRESH = 30
#: How long a member's long poll waits at the room.
POLL_WAIT = 20.0
MOST_BACK = 600

POLL_REPLY = {"seq": ("int", 0, 10**9), "ops": ("list", MOST_BACK, ("op",)),
              "presence?": ("list", 12, forms.PRESENCE), "members?": ("list", 200, forms.MEMBER),
              "title?": ("text", 200), "state?": ("enum", ("live", "ended")), "more?": ("bool",),
              "standin?": ("str", 80), "epoch?": ("int", 0, 10**6)}
OPS_REPLY = {"seq": ("int", 0, 10**9), "accepted": ("list", 600, ("id",)),
             "refused": ("list", 600, ("obj", {"id": ("id",), "why": ("text", 300)})),
             "confirmed?": ("list", 600, ("op",))}
JOIN_REPLY = {"space_id": ("id",), "kind": forms.KIND, "title": ("text", 200), "role": forms.ROLE,
              "members": ("list", 200, forms.MEMBER), "standin?": ("str", 80), "silo?": ("str", 40)}


def _now() -> float:
    return time.time()


class Live:
    """A space in memory: its changes, what they add up to, who is in, and a way to wait."""

    def __init__(self, org: str, row):
        self.org = org
        self.sid = row.space_id
        self.mine = row.mine
        self.holder = row.holder_label
        self.ops: list[dict] = []
        self.pending: list[dict] = []
        self.doc = _doc.empty()
        self.seq = 0
        self.version = 0
        self.presence: dict[str, dict] = {}
        self.cond = asyncio.Condition()
        self.lock = asyncio.Lock()
        self.holder_off = False
        self.follower: asyncio.Task | None = None
        self.standin_room = False
        self.standin_base = 0
        self.holder_seq = 0

    def recompute(self) -> None:
        d = _doc.replay(self.ops)
        for op in self.pending:
            try:
                _doc.apply(d, op)
            except Exception:  # noqa: BLE001 - a pending change that no longer fits waits for the room
                pass
        self.doc = d

    async def changed(self) -> None:
        async with self.cond:
            self.version += 1
            self.cond.notify_all()

    def fresh_presence(self) -> list[dict]:
        t = _now()
        return [dict(v, actor=k) for k, v in self.presence.items() if v.get("at", 0) > t - FRESH]


_LIVE: dict[tuple[str, str], Live] = {}
_LOOP: list = []


def _loop():
    if _LOOP:
        return _LOOP[0]
    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        return None


def remember_loop() -> None:
    try:
        lp = asyncio.get_running_loop()
    except RuntimeError:
        return
    if not _LOOP:
        _LOOP.append(lp)


def _row(org: str, sid: str):
    from rouh.models import LinkSpace

    return LinkSpace.objects.filter(org_id=org, space_id=sid).first()


def _load_ops(org: str, sid: str) -> tuple[list[dict], list[dict]]:
    from rouh.models import LinkOp

    done, pend = [], []
    for r in LinkOp.objects.filter(org_id=org, space_id=sid).order_by("seq", "id"):
        op = dict(r.data or {}, id=r.op_id, kind=r.kind, actor=r.actor, at=r.at, seq=r.seq)
        if r.undone:
            op["undone"] = True
        (pend if r.pending else done).append(op)
    return done, pend


async def get(org: str, sid: str) -> Live:
    remember_loop()
    key = (org, sid)
    live = _LIVE.get(key)
    if live is not None:
        return live
    row = await asyncio.to_thread(_row, org, sid)
    if row is None:
        raise LookupError("There is no such shared space here.")
    live = Live(org, row)
    live.ops, live.pending = await asyncio.to_thread(_load_ops, org, sid)
    live.seq = (row.seq or 0) if not row.mine else max([o["seq"] for o in live.ops] or [row.seq or 0])
    live.holder_seq = live.seq
    live.recompute()
    _LIVE[key] = _LIVE.get(key) or live
    return _LIVE[key]


def _op_fields(op: dict) -> dict:
    return {k: v for k, v in op.items() if k not in ("id", "kind", "actor", "at", "seq", "undone")}


def _store(org: str, sid: str, op: dict, *, pending: bool = False) -> None:
    from django.db import IntegrityError

    from rouh.models import LinkOp

    try:
        LinkOp.objects.update_or_create(org_id=org, space_id=sid, op_id=op["id"], defaults=dict(
            seq=op.get("seq", 0), actor=op["actor"], kind=op["kind"], data=_op_fields(op),
            at=op.get("at", 0), pending=pending))
    except IntegrityError:
        pass


def _save_row(org: str, sid: str, live: Live) -> None:
    from rouh.models import LinkSpace

    title = live.doc["fields"].get("title", {}).get("v") or ""
    LinkSpace.objects.filter(org_id=org, space_id=sid).update(
        seq=live.seq, doc=live.doc, title=str(title)[:200], updated_at=_now())


def members_of(row) -> list[dict]:
    return list((row.meta or {}).get("members") or [])


def role_of(row, label: str) -> str:
    for m in members_of(row):
        if m.get("label") == label and m.get("state", "joined") in ("joined", "invited"):
            return m.get("role") or "viewer"
    return ""


# --- the room: changes in one order -----------------------------------------------------------------


def _plain_change(ops: list[dict], names: dict, people: dict | None = None) -> str:
    who = {o["actor"] for o in ops}
    parts = []
    for o in ops:
        for p in _doc.parts_of(o):
            n = p.split(":", 1)[1]
            parts.append(names.get(n, n))
    kinds_ = {o["kind"] for o in ops}
    words = {"comment": "commented", "claim": "claimed a part", "release": "let a part go", "intent": "said what it is about to do",
             "intent.end": "finished or stopped", "propose": "proposed", "yes": "said yes", "settle": "settled a proposal",
             "undo": "undid edits", "restore": "brought back an earlier version", "doing": "worked"}
    said = ", ".join(sorted({words[k] for k in kinds_ if k in words}))
    what = ", ".join(sorted(set(parts)))[:120]
    people = people or {}

    def said_who(a: str) -> str:
        label = a.split(":", 1)[1]
        name = str(people.get(label) or label).split(" ·")[0]
        return name + ("'s person" if a.startswith("person:") else "'s Rouh")

    actors = ", ".join(sorted(said_who(a) for a in who))
    if what:
        return f"{actors} changed {what}" + (f"; {said}" if said else "") + f" ({len(ops)} change{'s' if len(ops) != 1 else ''})."
    return f"{actors} {said or 'changed the space'}."


async def submit(org: str, sid: str, sender: str, ops: list[dict], *, holder_code: bool = False) -> dict:
    """The room takes changes from one sender: {"seq", "accepted": [ids], "refused": [{id, why}]}."""
    live = await get(org, sid)
    if not live.mine and not live.standin_room:
        raise limits.No("This Rouh does not hold that room.")
    row = await asyncio.to_thread(_row, org, sid)
    if row is None or row.state != "live":
        raise limits.No("That space has ended.")
    role = "owner" if sender == row.holder_label else role_of(row, sender)
    if not role:
        raise limits.No("You are not in that space.")
    accepted, refused, fresh, numbered = [], [], [], []
    rebuild = False
    known = {o["id"] for o in live.ops}
    async with live.lock:
        for op in ops:
            if op["id"] in known:
                accepted.append(op["id"])
                numbered.extend(o for o in live.ops if o["id"] == op["id"])
                continue
            try:
                limits.may_change(space_meta=row.meta or {}, doc=live.doc, op=op, sender_label=sender,
                                  holder_label=row.holder_label, role=role, from_holder_code=holder_code)
            except limits.No as exc:
                refused.append({"id": op["id"], "why": str(exc)})
                continue
            live.seq += 1
            op = dict(op, seq=live.seq, at=round(_now(), 3))
            op.pop("undone", None)
            await asyncio.to_thread(_store, org, sid, op)
            live.ops.append(op)
            known.add(op["id"])
            if op["kind"] in ("undo", "restore"):
                rebuild = True
            else:
                _doc.apply(live.doc, op)
            accepted.append(op["id"])
            fresh.append(op)
            numbered.append(op)
        if rebuild:
            live.recompute()
        if fresh:
            await asyncio.to_thread(_save_row, org, sid, live)
    if fresh:
        names = kinds.of(row.kind)["names"]
        if any(o["kind"] != "doing" for o in fresh):
            people = {m["label"]: m.get("name", "") for m in members_of(row)}
            await asyncio.to_thread(log.write, org, "change", _plain_change(fresh, names, people), peer="" if sender == row.holder_label else sender, space=sid)
        await live.changed()
        await _after(org, sid, live, row, fresh)
    return {"seq": live.seq, "accepted": accepted, "refused": refused,
            "confirmed": [_wire_op(o) | {"seq": o["seq"]} for o in numbered]}


async def _after(org: str, sid: str, live: Live, row, fresh: list[dict]) -> None:
    """What the room's own code does after changes: settle a proposal every needed person said yes to."""
    from . import meeting

    for op in fresh:
        if op["kind"] == "yes":
            prop = live.doc["proposals"].get(op["pid"])
            if prop and prop["state"] == "open":
                chosen = {v["option"] for v in prop["yes"].values()}
                if set(prop["needed"]) <= set(prop["yes"]) and len(chosen) == 1:
                    me_label = row.holder_label
                    await submit(org, sid, me_label, [{
                        "id": f"settle-{op['pid']}", "kind": "settle", "actor": f"rouh:{me_label}",
                        "at": _now(), "pid": op["pid"], "state": "agreed", "chosen": chosen.pop(),
                        "said": "Each person said yes to the same time."}], holder_code=True)
    await meeting.after_changes(org, sid, live)


# --- a change from here: this Rouh's person or this Rouh ---------------------------------------------


def new_op(kind: str, actor: str, **fields) -> dict:
    return {"id": uuid.uuid4().hex[:20], "kind": kind, "actor": actor, "at": round(_now(), 3), **fields}


async def change(org: str, sid: str, ops: list[dict]) -> dict:
    """Changes made here (by this Rouh's person, or this Rouh), to whichever room holds the space."""
    from . import me as _me

    me = await asyncio.to_thread(_me.me, org)
    for op in ops:
        actor_label = op["actor"].split(":", 1)[1]
        if actor_label != me.label:
            raise limits.No("A change made here speaks for this Rouh or its person only.")
        _doc.read_op(op)
    live = await get(org, sid)
    if live.mine or live.standin_room:
        return await submit(org, sid, me.label, ops)
    row = await asyncio.to_thread(_row, org, sid)
    if row is None or row.state != "live":
        raise limits.No("That space has ended.")
    role = role_of(row, me.label)
    # What the room will check is checked here first, so a refusal shows at once.
    for op in ops:
        limits.may_change(space_meta=row.meta or {}, doc=live.doc, op=op, sender_label=me.label,
                          holder_label=row.holder_label, role=role)
    async with live.lock:
        for op in ops:
            await asyncio.to_thread(_store, org, sid, op, pending=True)
            live.pending.append(op)
        live.recompute()
    await live.changed()
    return await _send_pending(org, sid, live, row)


async def _send_pending(org: str, sid: str, live: Live, row) -> dict:
    from . import peers

    if not live.pending:
        return {"seq": live.seq, "accepted": [], "refused": []}
    target = row.holder_label
    standin = (row.meta or {}).get("standin_active") or ""
    if live.holder_off and standin and standin != row.holder_label:
        target = standin
    holder = await asyncio.to_thread(peers.peer_row, org, target)
    if holder is None or holder.state != "connected":
        return {"seq": live.seq, "accepted": [], "refused": [], "waiting": True}
    batch = list(live.pending)
    try:
        got = await wire.ask(org, holder, "room.ops", {"space_id": sid, "ops": [_wire_op(o) for o in batch]})
        reply = forms.read(got, OPS_REPLY, "room.ops reply")
    except wire.Unreachable:
        live.holder_off = True
        await asyncio.to_thread(wire.queue, org, holder, "room.ops",
                                {"space_id": sid, "ops": [_wire_op(o) for o in batch]})
        await live.changed()
        return {"seq": live.seq, "accepted": [], "refused": [], "waiting": True}
    except (wire.Refusal, forms.Refused) as exc:
        reply = {"seq": live.seq, "accepted": [], "refused": [{"id": o["id"], "why": str(getattr(exc, "said", exc))} for o in batch]}
    # The changes the room took, with their numbers: filed now, so none stays "waiting" if a poll
    # passes it by. The copy's own number is not moved on: the next poll still brings what came between.
    if reply.get("confirmed"):
        async with live.lock:
            known = {o["id"] for o in live.ops}
            for op in reply["confirmed"]:
                if op["id"] not in known:
                    await asyncio.to_thread(_store, org, sid, op)
                    live.ops.append(op)
                    known.add(op["id"])
            live.ops.sort(key=lambda o: o.get("seq", 0))
            live.pending = [o for o in live.pending if o["id"] not in known]
            live.recompute()
        await live.changed()
    gone = {r["id"] for r in reply["refused"]}
    if gone:
        async with live.lock:
            live.pending = [o for o in live.pending if o["id"] not in gone]
            await asyncio.to_thread(_drop_pending, org, sid, gone)
            live.recompute()
        await live.changed()
    if target == row.holder_label:
        live.holder_off = False
    return reply


def _drop_pending(org: str, sid: str, ids: set) -> None:
    from rouh.models import LinkOp

    LinkOp.objects.filter(org_id=org, space_id=sid, op_id__in=list(ids), pending=True).delete()


def _wire_op(op: dict) -> dict:
    return {k: v for k, v in op.items() if k not in ("seq", "undone")}


# --- a member following the room ---------------------------------------------------------------------


async def _take_confirmed(org: str, sid: str, live: Live, ops: list[dict], seq: int) -> None:
    if not ops and seq <= live.seq:
        return
    async with live.lock:
        known = {o["id"] for o in live.ops}
        mine = {o["id"] for o in live.pending}
        for op in ops:
            if op["id"] in known:
                continue
            await asyncio.to_thread(_store, org, sid, op)
            live.ops.append(op)
            known.add(op["id"])
        live.ops.sort(key=lambda o: o.get("seq", 0))
        live.pending = [o for o in live.pending if o["id"] not in known]
        # Only what a poll covered moves the copy's number on (`seq` is the room's at that poll).
        live.seq = max(live.seq, seq)
        if mine - {o["id"] for o in live.pending}:
            pass
        live.recompute()
        await asyncio.to_thread(_save_row, org, sid, live)


def _my_presence(org: str, live: Live, my_label: str) -> list[dict]:
    t = _now()
    out = []
    for actor, v in live.presence.items():
        if actor.split(":", 1)[1] == my_label and v.get("at", 0) > t - FRESH:
            out.append({k: v[k] for k in ("kind", "name", "part", "doing", "follow", "busy") if k in v} | {"actor": actor})
    return out[:6]


async def follow(org: str, sid: str) -> None:
    """Follow the room for as long as this space is live here (a member's Rouh): the owner's room,
    or the stand-in's while the owner's Rouh is off (`standin.py`)."""
    from . import groups, peers, standin
    from . import me as _me

    live = await get(org, sid)
    me = await asyncio.to_thread(_me.me, org)
    back = 1.0
    last_check = 0.0
    while True:
        row = await asyncio.to_thread(_row, org, sid)
        if row is None or row.state != "live" or row.mine:
            return
        if role_of(row, me.label) == "" and not (row.meta or {}).get("joined"):
            return
        holder = await asyncio.to_thread(peers.peer_row, org, row.holder_label)
        if holder is None or holder.state != "connected":
            await asyncio.sleep(10)
            continue
        # This Rouh holds the room as the stand-in: hand it back as soon as the owner's Rouh answers.
        if live.standin_room:
            if await standin.reachable(org, holder):
                await standin.hand_back(org, sid, live, row, me)
            else:
                await asyncio.sleep(10)
            continue
        target = holder
        active = (row.meta or {}).get("standin_active") or ""
        if live.holder_off and active and active != me.label:
            other = await asyncio.to_thread(peers.peer_row, org, active)
            if other is not None and other.state == "connected":
                target = other
                if time.time() - last_check > 15:
                    last_check = time.time()
                    if await standin.reachable(org, holder):
                        await standin.drop_interim(org, sid, live)
                        continue
        if live.pending:
            await _send_pending(org, sid, live, row)
        try:
            held = await asyncio.to_thread(groups.current, org, sid)
            got = await wire.ask(org, target, "room.poll", {
                "space_id": sid, "since": live.seq, "wait": POLL_WAIT, "epoch": held[0] if held else 0,
                "presence": _my_presence(org, live, me.label)}, timeout=POLL_WAIT + 10)
            if target is holder:
                got = await asyncio.to_thread(groups.open_reply, org, sid, holder.daily_key, got)
            reply = forms.read(got, POLL_REPLY, "room.poll reply")
        except wire.Unreachable:
            if target is not holder:
                # The stand-in is gone too: back to waiting for the owner's Rouh.
                await asyncio.to_thread(standin._set, org, sid, standin_active="")
                await asyncio.sleep(min(30.0, back))
                back = min(30.0, back * 2)
                continue
            if not live.holder_off:
                live.holder_off = True
                await live.changed()
            if await standin.maybe_hold(org, sid, live, row, me):
                continue
            await asyncio.sleep(min(30.0, back))
            back = min(30.0, back * 2)
            continue
        except (wire.Refusal, forms.Refused) as exc:
            log_.info("the room refused a poll: %s", exc)
            if isinstance(exc, wire.Refusal) and exc.status in (403, 404, 410) and target is holder:
                await asyncio.to_thread(_set_state, org, sid, "left")
                await live.changed()
                return
            await asyncio.sleep(10)
            continue
        back = 1.0
        if target is holder and live.holder_off:
            # The owner's Rouh is back: the stand-in's numbering is dropped, the owner's room renumbers.
            if active:
                await standin.drop_interim(org, sid, live)
                continue
            live.holder_off = False
        await _take_confirmed(org, sid, live, reply["ops"], reply["seq"])
        if target is holder:
            live.holder_seq = live.seq
        live.presence = {k: v for k, v in live.presence.items() if k.split(":", 1)[1] == me.label}
        for p in reply.get("presence") or []:
            if p["actor"].split(":", 1)[1] != me.label:
                live.presence[p["actor"]] = dict(p, at=_now())
        if reply.get("members") is not None and target is holder:
            await asyncio.to_thread(_set_members, org, sid, reply["members"], reply.get("standin", ""))
        if reply.get("state") == "ended":
            await asyncio.to_thread(_set_state, org, sid, "ended")
        await live.changed()
        _orb(org)
        if reply.get("more"):
            continue


def _set_state(org: str, sid: str, state: str) -> None:
    from rouh.models import LinkSpace

    LinkSpace.objects.filter(org_id=org, space_id=sid).update(state=state, updated_at=_now())


def _set_members(org: str, sid: str, members: list[dict], standin: str) -> None:
    from rouh.models import LinkSpace

    row = _row(org, sid)
    if row is None:
        return
    meta = dict(row.meta or {})
    meta["members"] = members
    if standin:
        meta["standin"] = standin
    LinkSpace.objects.filter(id=row.id).update(meta=meta)


def _start_following(org: str, sid: str) -> None:
    live = _LIVE.get((org, sid))
    if live is not None and live.follower is not None and not live.follower.done():
        return

    async def go():
        lv = await get(org, sid)
        if lv.follower is not None and not lv.follower.done():
            return
        lv.follower = asyncio.current_task()
        try:
            await follow(org, sid)
        except Exception:  # noqa: BLE001
            log_.exception("following a shared space stopped")

    lp = _loop()
    if lp is None:
        return
    try:
        running = asyncio.get_running_loop()
    except RuntimeError:
        running = None
    if running is lp:
        asyncio.ensure_future(go())
    else:
        asyncio.run_coroutine_threadsafe(go(), lp)


async def keep_up(org: str) -> None:
    """Every space this Rouh is a member of has a follower (the link loop calls this)."""
    from rouh.models import LinkSpace

    remember_loop()
    rows = await asyncio.to_thread(lambda: list(LinkSpace.objects.filter(org_id=org, state="live", mine=False)
                                                .values_list("space_id", "meta")))
    for sid, meta in rows:
        if (meta or {}).get("joined"):
            _start_following(org, sid)


# --- the room's side of the wire ----------------------------------------------------------------------


def _member_view(row) -> list[dict]:
    return [{"label": m["label"], "name": m.get("name", ""), "role": m.get("role", "viewer"),
             **({"address": m["address"]} if m.get("address") else {}),
             **({"key": m["key"]} if m.get("key") else {}),
             **({"link_key": m["link_key"]} if m.get("link_key") else {})}
            for m in members_of(row) if m.get("state", "joined") in ("joined", "invited")]


@wire.handles("room.poll")
async def _room_poll(ctx, form) -> dict:
    sid = form["space_id"]
    row = await asyncio.to_thread(_row, ctx.org, sid)
    if row is None or not (row.mine or (await get(ctx.org, sid)).standin_room):
        raise limits.No("This Rouh does not hold that room.")
    if not role_of(row, ctx.peer.label):
        raise limits.No("You are not in that space.")
    live = await get(ctx.org, sid)
    t = _now()
    for p in form.get("presence") or []:
        if p["actor"].split(":", 1)[1] == ctx.peer.label:
            live.presence[p["actor"]] = dict(p, at=t)
    _orb(ctx.org)
    since = int(form["since"])
    wait = float(form.get("wait") or 0)
    if live.seq <= since and wait > 0:
        v0 = live.version
        async with live.cond:
            try:
                await asyncio.wait_for(live.cond.wait_for(lambda: live.seq > since or live.version != v0), timeout=wait)
            except asyncio.TimeoutError:
                pass
    ops = [_wire_op(o) | {"seq": o["seq"]} for o in live.ops if o["seq"] > since]
    more = len(ops) > MOST_BACK
    from . import groups

    return groups.lock_reply(ctx.org, sid, int(form.get("epoch") or 0), ctx.me, {"seq": live.seq if not more else ops[MOST_BACK - 1]["seq"], "ops": ops[:MOST_BACK],
            "presence": [{k: v[k] for k in ("actor", "kind", "name", "part", "doing", "follow", "busy") if k in v}
                         for v in live.fresh_presence()][:12],
            "members": _member_view(row), "title": str(row.title or "")[:200], "state": row.state,
            "more": more, "standin": (row.meta or {}).get("standin", "")})


@wire.handles("room.ops")
async def _room_ops(ctx, form) -> dict:
    return await submit(ctx.org, form["space_id"], ctx.peer.label, form["ops"])


@wire.handles("room.presence")
async def _room_presence(ctx, form) -> dict:
    sid = form["space_id"]
    row = await asyncio.to_thread(_row, ctx.org, sid)
    if row is None or not role_of(row, ctx.peer.label) and row.holder_label != ctx.peer.label:
        raise limits.No("You are not in that space.")
    live = await get(ctx.org, sid)
    for p in form["presence"]:
        if p["actor"].split(":", 1)[1] == ctx.peer.label:
            live.presence[p["actor"]] = dict(p, at=_now())
    await live.changed()
    _orb(ctx.org)
    return {}


# --- making a space, inviting, joining, leaving ------------------------------------------------------


def create(org: str, *, kind: str = "task", title: str, source: str = "", silo: str = "",
           steps: list[str] | None = None, notes: str = "") -> str:
    """A new space held here, its first changes this Rouh's person's. Its id."""
    from rouh.models import LinkSpace

    from . import me as _me

    me = _me.me(org)
    sid = uuid.uuid4().hex[:20]
    now = _now()
    LinkSpace.objects.create(org_id=org, space_id=sid, kind=kind if kind in kinds.KINDS else "task",
                             title=title[:200], holder_label=me.label, holder_address=me.address,
                             holder_key=me.daily_public, mine=True, silo=silo[:40], source=source[:300],
                             meta={"members": [{"label": me.label, "name": me.tagged, "role": "owner",
                                                "state": "joined", "joined_at": now}]},
                             state="live", created_at=now, updated_at=now)
    actor = f"person:{me.label}"
    first = [new_op("set", actor, path=["fields", "title"], v=title[:200])]
    for k, v in kinds.of(kind)["fields"].items():
        first.append(new_op("set", actor, path=["fields", k], v=v))
    for i, s in enumerate((steps or [])[:60]):
        first.append(new_op("add", actor, list=kinds.of(kind)["lists"][0] if kinds.of(kind)["lists"] else "items",
                            item=uuid.uuid4().hex[:12], pos=float(i + 1), fields={"text": str(s)[:300], "done": False}))
    texts = kinds.of(kind)["texts"]
    if notes and texts:
        first.append(new_op("ins", actor, t=texts[0], after="", id0=f"1~{actor}", text=notes[:_doc.TEXT_MOST]))
    seq = 0
    from rouh.models import LinkOp

    d = _doc.empty()
    for op in first:
        seq += 1
        op["seq"] = seq
        LinkOp.objects.create(org_id=org, space_id=sid, seq=seq, op_id=op["id"], actor=op["actor"], kind=op["kind"],
                              data=_op_fields(op), at=op["at"])
        _doc.apply(d, op)
    LinkSpace.objects.filter(org_id=org, space_id=sid).update(seq=seq, doc=d)
    log.write(org, "space", f"Made a live {kinds.word(kind).lower()}: {title[:120]}.", space=sid)
    return sid


def invite(org: str, sid: str, label: str, role: str = "editor") -> dict:
    """Ask a connected Rouh into a space held here, at most what its trust allows."""
    from rouh.models import LinkSpace

    from . import me as _me
    from . import peers

    row = _row(org, sid)
    if row is None or not row.mine:
        raise peers.Problem("Only the Rouh holding a space invites into it.")
    peer = peers.peer_row(org, label)
    if peer is None or peer.state != "connected":
        raise peers.Problem("Connect to that Rouh first.")
    cap = trust.most_role(peer.trust, row.silo, peer.silo)
    if not cap:
        raise peers.Problem(f"{peer.name} is on the other side (Work and Personal stay apart), so it cannot be in this space.")
    role = trust.role_at_most(role, cap)
    members = members_of(row)
    most = _me.settings(org)["most_members"]
    live_members = [m for m in members if m.get("state", "joined") in ("joined", "invited")]
    if not any(m["label"] == label for m in live_members) and len(live_members) >= most:
        raise peers.Problem(f"A space holds at most {most} Rouhs for now.")
    members = [m for m in members if m["label"] != label] + [{
        "label": label, "name": peer.name, "role": role, "state": "invited", "address": peer.address,
        "key": peer.daily_key, "link_key": peer.link_key, "invited_at": _now()}]
    meta = dict(row.meta or {}, members=members)
    LinkSpace.objects.filter(id=row.id).update(meta=meta, updated_at=_now())
    me = _me.me(org)
    wire.queue(org, peer, "space.invite", {
        "space_id": sid, "kind": row.kind, "title": row.title or "", "role": role, "holder": me.label,
        "address": me.address, "holder_key": me.daily_public, "silo": row.silo or "",
        "members": _member_view(_row(org, sid)), "standin": meta.get("standin", "")})
    log.write(org, "invite", f"Asked {peer.name} into “{row.title[:80]}” as {role}.", peer=label, space=sid)
    from . import groups

    groups.rekey_soon(org, sid)
    return {"label": label, "role": role}


@wire.handles("space.invite")
def _space_invite(ctx, form) -> dict:
    from rouh.models import LinkSpace

    if form["holder"] != ctx.peer.label:
        raise limits.No("A space is offered only by the Rouh that holds it.")
    cap = trust.most_role(ctx.peer.trust, form.get("silo") or "", ctx.peer.silo)
    if not cap:
        raise limits.No("That space is on the other side here (Work and Personal stay apart).")
    now = _now()
    row = _row(ctx.org, form["space_id"])
    if row is not None and row.mine:
        raise limits.No("That space is this Rouh's own.")
    meta = {"members": form.get("members") or [], "invited_role": form["role"], "joined": False,
            "standin": form.get("standin") or ""}
    if row is None:
        LinkSpace.objects.create(org_id=ctx.org, space_id=form["space_id"], kind=form["kind"],
                                 title=str(form["title"])[:200], holder_label=ctx.peer.label,
                                 holder_address=ctx.peer.address, holder_key=ctx.peer.daily_key, mine=False,
                                 silo=form.get("silo") or ctx.peer.silo or "", meta=meta, state="invited",
                                 created_at=now, updated_at=now)
    else:
        LinkSpace.objects.filter(id=row.id).update(title=str(form["title"])[:200], meta=dict(row.meta or {}, **meta),
                                                   state="invited" if row.state != "live" else row.state, updated_at=now)
    log.write(ctx.org, "invited", f"{ctx.peer.name} asked this Rouh into a live {kinds.word(form['kind']).lower()}: "
              f"“{str(form['title'])[:80]}”.", peer=ctx.peer.label, space=form["space_id"])
    push_owner(ctx.org, {"type": "link_notice", "said": f"{ctx.peer.name} asks you into “{str(form['title'])[:60]}”."})
    return {}


async def join(org: str, sid: str) -> dict:
    """This Rouh's person says yes to a space they were asked into."""
    from rouh.models import LinkSpace

    from . import peers

    row = await asyncio.to_thread(_row, org, sid)
    if row is None or row.mine:
        raise peers.Problem("There is no invitation to that space.")
    holder = await asyncio.to_thread(peers.peer_row, org, row.holder_label)
    if holder is None or holder.state != "connected":
        raise peers.Problem("The Rouh holding that space is not connected.")
    got = await wire.ask(org, holder, "space.join", {"space_id": sid})
    reply = forms.read(got, JOIN_REPLY, "space.join reply")

    def keep():
        meta = dict(row.meta or {}, members=reply["members"], joined=True, standin=reply.get("standin", ""))
        LinkSpace.objects.filter(id=row.id).update(state="live", title=str(reply["title"])[:200], meta=meta,
                                                   kind=reply["kind"], updated_at=_now())

    await asyncio.to_thread(keep)
    await asyncio.to_thread(log.write, org, "join", f"Joined “{reply['title'][:80]}” as {reply['role']}.",
                            peer=row.holder_label, space=sid)
    live = _LIVE.get((org, sid))
    if live is not None:
        await live.changed()
    _start_following(org, sid)
    return {"space_id": sid}


@wire.handles("space.join")
def _space_join(ctx, form) -> dict:
    from rouh.models import LinkSpace

    row = _row(ctx.org, form["space_id"])
    if row is None or not row.mine or row.state != "live":
        raise limits.No("There is no such live space here.")
    members = members_of(row)
    me = [m for m in members if m["label"] == ctx.peer.label]
    if not me:
        raise limits.No("You were not asked into that space.")
    cap = trust.most_role(ctx.peer.trust, row.silo, ctx.peer.silo)
    if not cap:
        raise limits.No("That space is on the other side.")
    for m in members:
        if m["label"] == ctx.peer.label:
            m["state"] = "joined"
            m["role"] = trust.role_at_most(m.get("role", "viewer"), cap)
            m["joined_at"] = _now()
            role = m["role"]
    LinkSpace.objects.filter(id=row.id).update(meta=dict(row.meta or {}, members=members), updated_at=_now())
    log.write(ctx.org, "join", f"{ctx.peer.name} joined “{row.title[:80]}”.", peer=ctx.peer.label, space=row.space_id)
    _wake(ctx.org, row.space_id)
    from . import groups

    groups.rekey_soon(ctx.org, row.space_id)
    row = _row(ctx.org, form["space_id"])
    return {"space_id": row.space_id, "kind": row.kind, "title": row.title or "", "role": role,
            "members": _member_view(row), "standin": (row.meta or {}).get("standin", ""), "silo": row.silo or ""}


async def leave(org: str, sid: str) -> None:
    from . import peers

    row = await asyncio.to_thread(_row, org, sid)
    if row is None:
        return
    if row.mine:
        await asyncio.to_thread(end, org, sid)
        return
    await asyncio.to_thread(_set_state, org, sid, "left")
    holder = await asyncio.to_thread(peers.peer_row, org, row.holder_label)
    if holder is not None and holder.state == "connected":
        await asyncio.to_thread(wire.queue, org, holder, "space.left", {"space_id": sid})
    await asyncio.to_thread(log.write, org, "leave", f"Left “{row.title[:80]}”.", peer=row.holder_label, space=sid)
    live = _LIVE.pop((org, sid), None)
    if live is not None and live.follower is not None:
        live.follower.cancel()


def end(org: str, sid: str) -> None:
    from . import peers

    row = _row(org, sid)
    if row is None or not row.mine:
        return
    _set_state(org, sid, "ended")
    for m in members_of(row):
        if m["label"] == row.holder_label or m.get("state") not in ("joined", "invited"):
            continue
        p = peers.peer_row(org, m["label"])
        if p is not None and p.state == "connected":
            wire.queue(org, p, "space.ended", {"space_id": sid})
    log.write(org, "end", f"Ended the live space “{row.title[:80]}”.", space=sid)
    _wake(org, sid)


@wire.handles("space.left")
def _space_left(ctx, form) -> dict:
    from rouh.models import LinkSpace

    row = _row(ctx.org, form["space_id"])
    if row is None or not row.mine:
        return {}
    members = [dict(m, state="left") if m["label"] == ctx.peer.label else m for m in members_of(row)]
    LinkSpace.objects.filter(id=row.id).update(meta=dict(row.meta or {}, members=members), updated_at=_now())
    log.write(ctx.org, "leave", f"{ctx.peer.name} left “{row.title[:80]}”.", peer=ctx.peer.label, space=row.space_id)
    _wake(ctx.org, row.space_id)
    from . import groups

    groups.rekey_soon(ctx.org, row.space_id)
    return {}


@wire.handles("space.ended")
def _space_ended(ctx, form) -> dict:
    row = _row(ctx.org, form["space_id"])
    if row is None or row.mine or row.holder_label != ctx.peer.label:
        return {}
    _set_state(ctx.org, row.space_id, "ended")
    log.write(ctx.org, "end", f"{ctx.peer.name} ended “{row.title[:80]}”.", peer=ctx.peer.label, space=row.space_id)
    _wake(ctx.org, row.space_id)
    return {}


def connection_changed(org: str, label: str) -> None:
    """A connection's level, side or state changed: every space here held to it again at once."""
    from rouh.models import LinkSpace

    from . import peers

    peer = peers.peer_row(org, label)
    for row in LinkSpace.objects.filter(org_id=org, state__in=("live", "invited")):
        if row.mine:
            members = members_of(row)
            touched = False
            for m in members:
                if m["label"] != label or m.get("state") not in ("joined", "invited"):
                    continue
                cap = "" if peer is None or peer.state != "connected" else trust.most_role(peer.trust, row.silo, peer.silo)
                new = trust.role_at_most(m.get("role", "viewer"), cap) if cap else ""
                if not new:
                    m["state"] = "removed"
                elif new != m.get("role"):
                    m["role"] = new
                else:
                    continue
                touched = True
            if touched:
                LinkSpace.objects.filter(id=row.id).update(meta=dict(row.meta or {}, members=members), updated_at=_now())
                from . import groups

                groups.rekey_soon(org, row.space_id)
                log.write(org, "role", f"{label}'s place in “{row.title[:60]}” changed with its connection.", peer=label,
                          space=row.space_id)
                _wake(org, row.space_id)
        elif row.holder_label == label and (peer is None or peer.state != "connected"):
            _set_state(org, row.space_id, "left")
            _wake(org, row.space_id)


def _wake(org: str, sid: str) -> None:
    live = _LIVE.get((org, sid))
    lp = _loop()
    if live is None or lp is None:
        return

    async def go():
        await live.changed()
    try:
        running = asyncio.get_running_loop()
    except RuntimeError:
        running = None
    if running is lp:
        asyncio.ensure_future(go())
    else:
        asyncio.run_coroutine_threadsafe(go(), lp)


# --- a person's page ----------------------------------------------------------------------------------


def listing(org: str) -> list[dict]:
    from rouh.models import LinkSpace

    out = []
    for r in LinkSpace.objects.filter(org_id=org).exclude(state="left").order_by("-updated_at")[:100]:
        out.append({"space_id": r.space_id, "kind": r.kind, "kind_word": kinds.word(r.kind), "title": r.title,
                    "mine": r.mine, "holder": r.holder_label, "state": r.state, "silo": r.silo,
                    "members": [{"label": m["label"], "name": m.get("name", ""), "role": m.get("role", "")}
                                for m in members_of(r) if m.get("state", "joined") in ("joined", "invited")],
                    "updated_at": r.updated_at, "source": r.source})
    return out


def seen(live: Live, actor: str, *, kind: str, name: str, part: str = "", follow: str = "", doing: str = "",
         busy: bool = False) -> None:
    live.presence[actor] = {"kind": kind, "name": name, "part": part[:120], "follow": follow[:120],
                            "doing": doing[:200], "busy": busy, "at": _now()}


async def page_state(org: str, sid: str, *, since: int = -1, wait: float = 0.0, part: str = "",
                     follow: str = "", watching: bool = True) -> dict:
    """What a person's page shows, after waiting up to ``wait`` seconds for something new."""
    from . import me as _me

    live = await get(org, sid)
    me = await asyncio.to_thread(_me.me, org)
    actor = f"person:{me.label}"
    old_part = (live.presence.get(actor) or {}).get("part")
    if watching:
        seen(live, actor, kind="person", name=me.tagged + "'s person", part=part, follow=follow)
        if old_part != part:
            await live.changed()
            if not live.mine:
                asyncio.ensure_future(_tell_presence(org, sid))
    if wait > 0 and live.version <= since:
        async with live.cond:
            try:
                await asyncio.wait_for(live.cond.wait_for(lambda: live.version > since), timeout=wait)
            except asyncio.TimeoutError:
                pass
    row = await asyncio.to_thread(_row, org, sid)
    if row is None:
        raise LookupError("There is no such shared space here.")
    role = "owner" if row.mine else role_of(row, me.label) or (row.meta or {}).get("invited_role", "")
    from . import pacing

    return {
        "space": {"space_id": sid, "kind": row.kind, "kind_word": kinds.word(row.kind), "names": kinds.of(row.kind)["names"],
                  "texts": kinds.of(row.kind)["texts"], "lists": kinds.of(row.kind)["lists"],
                  "mine": row.mine, "holder": row.holder_label, "state": row.state, "silo": row.silo,
                  "joined": row.mine or bool((row.meta or {}).get("joined")), "source": row.source,
                  "members": [{"label": m["label"], "name": m.get("name", ""), "role": m.get("role", ""),
                               "state": m.get("state", "joined")} for m in members_of(row)],
                  "standin": (row.meta or {}).get("standin", ""),
                  "standin_active": (row.meta or {}).get("standin_active", ""),
                  "epoch": int((row.meta or {}).get("epoch") or 0)},
        "me": {"label": me.label, "name": me.tagged, "person": actor, "rouh": f"rouh:{me.label}", "role": role},
        "doc": _doc.shown(live.doc), "version": live.version, "seq": live.seq,
        "pending": len(live.pending), "holder_off": live.holder_off,
        "presence": live.fresh_presence(),
        "pacing": pacing.status(org, sid),
        "grants_in": await asyncio.to_thread(_grants_in, org),
    }


def _grants_in(org: str) -> list[dict]:
    """The grants other people wrote to this Rouh, in force: whose, what, in their words."""
    from . import grants

    return [{"from": g["peer"], "what": g["what"], "words": g["words"]} for g in grants.listing(org)
            if g["direction"] == "in" and g["active"]]


async def _tell_presence(org: str, sid: str) -> None:
    from . import me as _me
    from . import peers

    try:
        live = await get(org, sid)
        row = await asyncio.to_thread(_row, org, sid)
        me = await asyncio.to_thread(_me.me, org)
        holder = await asyncio.to_thread(peers.peer_row, org, row.holder_label)
        if holder is not None and holder.state == "connected":
            await wire.ask(org, holder, "room.presence", {"space_id": sid, "presence": _my_presence(org, live, me.label)},
                           timeout=6)
    except Exception:  # noqa: BLE001 - presence is best effort
        pass


async def history(org: str, sid: str, upto: int) -> dict:
    live = await get(org, sid)
    return {"seq": upto, "doc": _doc.shown(_doc.replay(live.ops, upto=upto)),
            "marks": [{"seq": o["seq"], "actor": o["actor"], "kind": o["kind"], "at": o.get("at", 0)}
                      for o in live.ops if o["kind"] in _doc.CONTENT or o["kind"] in ("undo", "restore")][-400:]}


# --- the person's own pages, and the orb ------------------------------------------------------------


def push_owner(org: str, message: dict) -> None:
    """A message to every open tab of this organisation's people (the main page's socket)."""
    lp = _loop()
    if lp is None:
        return

    async def go():
        from rouh import runtime

        for s in list(runtime.Hub.sockets):
            me = getattr(s, "me", None)
            if me is not None and str(getattr(me, "org_id", "")) == str(org):
                try:
                    await s.emit(message)
                except Exception:  # noqa: BLE001
                    pass
    try:
        running = asyncio.get_running_loop()
    except RuntimeError:
        running = None
    if running is lp:
        asyncio.ensure_future(go())
    else:
        asyncio.run_coroutine_threadsafe(go(), lp)


_ORB: dict[str, list] = {}


def _orb(org: str) -> None:
    """The orb's second colour: on while another Rouh is at work in a space with this Rouh."""
    from . import me as _me

    try:
        mine = _me.me(org).label
    except Exception:  # noqa: BLE001
        return
    at_work = []
    for (o, _sid), live in list(_LIVE.items()):
        if o != org:
            continue
        for p in live.fresh_presence():
            if p.get("kind") == "rouh" and p.get("busy") and p["actor"].split(":", 1)[1] != mine:
                at_work.append(p.get("name") or p["actor"].split(":", 1)[1])
    names = sorted(set(at_work))
    if _ORB.get(org) != names:
        _ORB[org] = names
        push_owner(org, {"type": "link_partner_working", "on": bool(names), "who": names[:4]})
