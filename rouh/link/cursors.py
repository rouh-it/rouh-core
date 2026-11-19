"""Live cursors: each person's pointer, caret and selection in a live space, shared live, like Figma.

Petar, 19 November 2026 (task 189, step 189-09): "can human's cursors be shared with other humans and
rouhs like figma?", then "build it".

A cursor is where a person is pointing, as a part of the space and a place inside it (``item:<id>``
at 0.3 across and 0.5 down, never screen pixels), and their caret or selection in a live text, by the
ids of the text CRDT's characters, so it follows everyone's edits (`forms.CURSOR`).

How it travels, and that it is never kept:

- **A person's page** tells its own Rouh only (`from_page`, ``POST /api/link/spaces/<id>/cursor``), at
  most 15 times a second while it moves, and listens with one long request for the others'.
- **A member's Rouh** sends its own person's cursor to the room (``room.cursor``, sealed through the
  relay like every message, never queued, never the mailbox), at most 15 a second, the newest only,
  and listens at the room with one long request while its person's page is open (`_listen`).
- **The room's Rouh** keeps each cursor in memory for 30 seconds and hands everyone the others'. It
  keeps a sender's only for that sender's own person, and only from a member whose trust level sees
  presence (Known and up); a Stranger's Rouh listens and sends nothing that is kept.
- **Nothing is stored**: not in the history, the signed log, the mailbox, the database or a log line.
  A Rouh's own person's last point and selection stay in this process's memory for two minutes, so
  "this one" can mean what they point at (`pointing`); another person's cursor is never read by a
  Rouh, never reaches a prompt, and never steers anything.
- **"Show my cursor to others"** off: the page still tells its own Rouh (for "this one"), which sends
  it to nobody and takes it away from the others at once.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import deque

from . import forms

log_ = logging.getLogger("rouh.link")

#: A cursor not heard from for this long is dropped.
FRESH = 30.0
#: A Rouh's own person's last point and selection stay this long, for "this one".
OWN_KEEP = 120.0
#: The most a second a cursor is sent on, each way.
MOST_A_SECOND = 15
#: How long one listening request waits at most.
WAIT = 20.0
#: The most cursors one answer carries.
MOST = 40

S = forms.S
POS = ("obj", {"b?": S(120), "n?": S(120), "i": ("int", 0, 2_000_000)})
SEL = ("obj", {"t": S(120), "a": POS, "f": POS})
#: One person's cursor, as it crosses between Rouhs.
CURSOR = ("obj", {"actor": ("actor",), "name?": S(80), "part": S(120), "x": ("num", 0, 1), "y": ("num", 0, 1),
                  "sel?": SEL, "tap?": ("bool",), "n": ("int", 0, 10**12), "gone?": ("bool",)})
#: What a page may say of its own person's cursor: no actor or name (the Rouh puts those), and the
#: selected words, which its own Rouh keeps for itself and never sends on.
FROM_PAGE = {"part": S(120), "x": ("num", 0, 1), "y": ("num", 0, 1), "sel?": SEL, "tap?": ("bool",),
             "n": ("int", 0, 10**12), "gone?": ("bool",), "q?": ("text", 300)}
REPLY = {"cv": ("int", 0, 10**12), "cursors": ("list", MOST, CURSOR)}


def _now() -> float:
    return time.time()


def _part_ok(part: str) -> bool:
    import re

    return part == "" or bool(re.match(r"^(item|list|text|field|el):[A-Za-z0-9_.-]{1,80}$", part))


def _clean(c: dict) -> dict | None:
    """A cursor as it may cross: known parts only, the selection's place a known kind of place."""
    if not _part_ok(c.get("part", "")) or not str(c.get("actor", "person:")).startswith("person:"):
        return None   # only people have cursors; a Rouh has its marker
    sel = c.get("sel")
    if sel is not None and not (sel["t"] == "src" or _part_ok(sel["t"]) and sel["t"]):
        c = {k: v for k, v in c.items() if k != "sel"}
    return c


class Board:
    """One space's cursors in this process: the others', and this Rouh's own person's."""

    def __init__(self, org: str, sid: str):
        self.org, self.sid = org, sid
        self.cursors: dict[str, dict] = {}      # actor -> cursor, with "at"
        self.cv = 0
        self.cond = asyncio.Condition()
        self.own: dict = {}                     # "point" and "sel" of this Rouh's own person, with "at"
        self.shared = False                     # whether this Rouh's person's cursor is out with the others
        self.page_at = 0.0                      # when this Rouh's person's page last listened
        self.room_cv = -1                       # a member's: the room's version it saw last
        self.outgoing: dict | None = None
        self.sender: asyncio.Task | None = None
        self.listener: asyncio.Task | None = None
        self.last_out = 0.0
        self.traffic: deque = deque()           # (time, bytes): every cursor message this Rouh sent or took
        self.cache: dict = {}

    async def bump(self) -> None:
        async with self.cond:
            self.cv += 1
            self.cond.notify_all()

    async def wait(self, cv: int, wait: float) -> None:
        if self.cv != cv or wait <= 0:
            return
        async with self.cond:
            try:
                await asyncio.wait_for(self.cond.wait_for(lambda: self.cv != cv), timeout=wait)
            except asyncio.TimeoutError:
                pass

    def others(self, but_label: str, members: set[str] | None = None) -> list[dict]:
        t = _now()
        out = []
        for actor, c in list(self.cursors.items()):
            if c["at"] < t - FRESH:
                self.cursors.pop(actor, None)
                continue
            label = actor.split(":", 1)[1]
            if label == but_label or (members is not None and label not in members):
                continue
            out.append({k: v for k, v in c.items() if k not in ("at", "from")} | {"age": round(t - c["at"], 2)})
        return out[:MOST]

    def count(self, size: int) -> None:
        t = _now()
        self.traffic.append((t, size))
        while self.traffic and self.traffic[0][0] < t - 10:
            self.traffic.popleft()

    def stats(self) -> dict:
        t = _now()
        recent = [b for at, b in self.traffic if at > t - 10]
        return {"messages_a_second": round(len(recent) / 10, 2), "bytes_a_second": int(sum(recent) / 10)}


_BOARDS: dict[tuple[str, str], Board] = {}


def board(org: str, sid: str) -> Board:
    b = _BOARDS.get((org, sid))
    if b is None:
        b = _BOARDS[(org, sid)] = Board(org, sid)
    return b


def forget(org: str, sid: str) -> None:
    """A space that ended or was left here: its cursors go."""
    b = _BOARDS.pop((org, sid), None)
    if b is not None:
        for t in (b.sender, b.listener):
            if t is not None and not t.done():
                # `spaces.end` may run in a thread: cancel on the task's own loop.
                t.get_loop().call_soon_threadsafe(t.cancel)


async def _cached(b: Board, key: str, fn, keep: float = 10.0):
    """A value worth reading once in a while, not 15 times a second (who this Rouh is, the row)."""
    got = b.cache.get(key)
    if got is not None and got[0] > _now() - keep:
        return got[1]
    value = await asyncio.to_thread(fn)
    b.cache[key] = (_now(), value)
    return value


async def _members(b: Board) -> set[str]:
    from . import spaces

    def go():
        row = spaces._row(b.org, b.sid)
        if row is None:
            return set()
        out = {m["label"] for m in spaces.members_of(row) if m.get("state", "joined") == "joined"}
        out.add(row.holder_label)
        return out
    return await _cached(b, "members", go, 5.0)


# --- the person's page --------------------------------------------------------------------------------


async def from_page(org: str, sid: str, body: dict, *, who=None) -> dict:
    """The page's own person's cursor, if it sent one; then, after waiting up to ``wait`` for news,
    everyone else's."""
    from . import me as _me
    from . import spaces

    row = await asyncio.to_thread(spaces._row, org, sid)
    if row is None or row.state != "live":
        raise LookupError("There is no such live space here.")
    b = board(org, sid)
    me = await _cached(b, "me", lambda: _me.me(org), 60.0)
    actor = f"person:{me.label}"
    name = await _cached(b, "name", lambda: _person_name(who, me), 60.0)
    share = body.get("share") is not False
    b.page_at = _now()
    if isinstance(body.get("cursor"), dict):
        c = forms.read(body["cursor"], FROM_PAGE, "cursor")
        await _mine(b, row, name, actor, c, share)
    if not row.mine:
        _start_listening(b)
    try:
        cv = int(body.get("cv", -1))
    except (TypeError, ValueError):
        cv = -1
    try:
        wait = max(0.0, min(WAIT, float(body.get("wait") or 0)))
    except (TypeError, ValueError):
        wait = 0.0
    await b.wait(cv, wait)
    members = await _members(b)
    return {"cv": b.cv, "cursors": b.others(me.label, members), "mine": actor, "share": share, "stats": b.stats()}


async def _mine(b: Board, row, name: str, actor: str, c: dict, share: bool) -> None:
    t = _now()
    q = str(c.pop("q", "") or "")
    if c.get("part") and _part_ok(c["part"]) and not c.get("gone"):
        b.own["point"] = {"part": c["part"], "x": c["x"], "y": c["y"], "at": t}
    if c.get("sel") is not None:
        b.own["sel"] = dict(c["sel"], q=q, at=t)
    if c.get("gone"):
        share = False
    public = _clean(dict(c, actor=actor, name=name))
    if public is None:
        return
    if share:
        b.cursors[actor] = dict(public, at=t)
        b.shared = True
    elif b.shared:
        # Turned off, the tab hidden, or gone: taken away from the others at once.
        b.shared = False
        public = {"actor": actor, "name": public.get("name", ""), "part": "", "x": 0, "y": 0, "n": c["n"], "gone": True}
        b.cursors[actor] = dict(public, at=t)
    else:
        return
    await b.bump()
    if not row.mine:
        b.outgoing = public
        if b.sender is None or b.sender.done():
            b.sender = asyncio.ensure_future(_send(b))


def _person_name(who, me) -> str:
    """What a person's cursor is labelled with for the others: their first name, as their own Rouh
    knows it, else "<their Rouh>'s person". Only a first name: the others are already working with them."""
    from rouh import owner

    try:
        found = owner.of(getattr(who, "user_id", None) or getattr(who, "id", None) or "") if who is not None else None
    except Exception:  # noqa: BLE001
        found = None
    first = str(getattr(found, "name", "") or "").strip().split(" ")[0][:40]
    return first or (str(me.tagged or "").split(" ·")[0][:50] + "'s person")


# --- between Rouhs --------------------------------------------------------------------------------------


_CLIENTS: dict[str, object] = {}


async def _post(address: str, env: dict) -> dict:
    """One envelope to the room and its answer, on a connection kept open (15 a second would otherwise
    make a new one each time). Unreachable or Refusal, as `wire.post_envelope`."""
    import httpx

    from . import peers, wire

    address = peers.dialable(address)
    if not address:
        raise wire.Unreachable("this Rouh is reached by the mailbox only")
    c = _CLIENTS.get(address)
    if c is None or c.is_closed:
        c = _CLIENTS[address] = httpx.AsyncClient(timeout=httpx.Timeout(WAIT + 8, connect=6.0), follow_redirects=False,
                                                  headers={"User-Agent": "rouh-link/1"})
    try:
        r = await c.post(address.rstrip("/") + "/link/in", json=env)
    except (httpx.HTTPError, OSError) as exc:
        raise wire.Unreachable(type(exc).__name__) from None
    try:
        got = r.json()
    except ValueError:
        raise wire.Unreachable(f"answered {r.status_code}, not a Rouh") from None
    if r.status_code == 200 and isinstance(got, dict) and got.get("v") == 1:
        return got
    if isinstance(got, dict) and got.get("error"):
        raise wire.Refusal(str(got["error"]), r.status_code)
    raise wire.Unreachable(f"answered {r.status_code}")


async def _ask_room(b: Board, cursors: list[dict], wait: float) -> dict:
    from . import me as _me
    from . import peers, spaces, wire

    row = await _cached(b, "row", lambda: spaces._row(b.org, b.sid), 5.0)
    if row is None or row.mine or row.state != "live":
        raise wire.Unreachable("no room to tell")
    holder = await _cached(b, "holder", lambda: peers.peer_row(b.org, row.holder_label), 10.0)
    if holder is None or holder.state != "connected":
        raise wire.Unreachable("the room's Rouh is not connected")
    me = await _cached(b, "me", lambda: _me.me(b.org), 60.0)
    body = {"space_id": b.sid, "cursors": cursors, "cv": max(0, b.room_cv), "wait": wait}
    env = await asyncio.to_thread(wire.lock_for, me, holder, "room.cursor", body)
    got = await _post(holder.address, env)
    b.count(len(json.dumps(env)) + len(json.dumps(got)))
    reply = await asyncio.to_thread(wire.open_reply, me, holder, got)
    return forms.read(reply, REPLY, "room.cursor reply")


async def _take(b: Board, reply: dict, my_label: str) -> None:
    """The room's answer: the others' cursors, newest of each kept."""
    changed = reply["cv"] != b.room_cv
    b.room_cv = reply["cv"]
    t = _now()
    for c in reply["cursors"]:
        label = c["actor"].split(":", 1)[1]
        if label == my_label:
            continue
        c = _clean(c)
        if c is None:
            continue
        old = b.cursors.get(c["actor"])
        if old is not None and old.get("n", 0) >= c["n"] and old.get("gone") == c.get("gone"):
            continue
        b.cursors[c["actor"]] = dict(c, at=t)
        changed = True
    if changed:
        await b.bump()


async def _send(b: Board) -> None:
    """This Rouh's person's cursor to the room: the newest only, at most 15 a second, one at a time."""
    from . import me as _me

    me = await _cached(b, "me", lambda: _me.me(b.org), 60.0)
    while b.outgoing is not None:
        gap = 1.0 / MOST_A_SECOND - (_now() - b.last_out)
        if gap > 0:
            await asyncio.sleep(gap)
        c, b.outgoing = b.outgoing, None
        b.last_out = _now()
        try:
            await _take(b, await _ask_room(b, [c], 0), me.label)
        except Exception as exc:  # noqa: BLE001 - a cursor is never kept to send later
            log_.debug("a cursor did not reach the room: %s", type(exc).__name__)


def _start_listening(b: Board) -> None:
    if b.listener is None or b.listener.done():
        b.listener = asyncio.ensure_future(_listen(b))


async def _listen(b: Board) -> None:
    """A member's Rouh listens at the room for as long as its person's page is open."""
    from . import me as _me

    back = 1.0
    me = await _cached(b, "me", lambda: _me.me(b.org), 60.0)
    while _now() - b.page_at < WAIT + 10:
        began = _now()
        try:
            await _take(b, await _ask_room(b, [], WAIT), me.label)
            back = 1.0
            # At most 15 a second from the room too: what moved in between comes together in the next.
            gap = 1.0 / MOST_A_SECOND - (_now() - began)
            if gap > 0:
                await asyncio.sleep(gap)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            log_.debug("listening for cursors: %s", type(exc).__name__)
            await asyncio.sleep(back)
            back = min(15.0, back * 2)


# --- the room's side ---------------------------------------------------------------------------------


def _wire_handler():
    from . import limits, spaces, trust, wire

    @wire.handles("room.cursor")
    async def _room_cursor(ctx, form) -> dict:
        if ctx.by_mailbox:
            return {}
        sid = form["space_id"]
        row = await asyncio.to_thread(spaces._row, ctx.org, sid)
        if row is None or not (row.mine or (await spaces.get(ctx.org, sid)).standin_room):
            raise limits.No("This Rouh does not hold that room.")
        if not spaces.role_of(row, ctx.peer.label):
            raise limits.No("You are not in that space.")
        b = board(ctx.org, sid)
        size = len(json.dumps(form))
        b.count(size)
        mine = f"person:{ctx.peer.label}"
        # Only a member that sees presence shares a cursor here, and only its own person's.
        if trust.may_send(ctx.level, "room.presence"):
            names = {m["label"]: str(m.get("name") or "").split(" ·")[0][:50] + "'s person" for m in spaces.members_of(row)}
            t = _now()
            took = False
            for c in form["cursors"]:
                if c["actor"] != mine:
                    continue
                c = _clean(c)
                if c is None:
                    continue
                old = b.cursors.get(mine)
                if old is not None and old.get("n", 0) > c["n"]:
                    continue
                b.cursors[mine] = dict(c, name=c.get("name") or names.get(ctx.peer.label, ""), at=t)
                took = True
            if took:
                await b.bump()
        await b.wait(int(form.get("cv") or 0), float(form.get("wait") or 0))
        members = await _members(b)
        return {"cv": b.cv, "cursors": b.others(ctx.peer.label, members)}


_wire_handler()


# --- what this Rouh may read: its own person's, only ---------------------------------------------------


def pointing(org: str, sid: str) -> dict | None:
    """Where this Rouh's own person is pointing and what they selected, each within two minutes:
    ``{"point": {"part", "x", "y", "age"}, "sel": {"t", "a", "f", "q", "age"}}``, or None.
    Never anyone else's: the others' cursors are for drawing only."""
    b = _BOARDS.get((org, sid))
    if b is None:
        return None
    t = _now()
    out = {}
    for k in ("point", "sel"):
        v = b.own.get(k)
        if v and v["at"] > t - OWN_KEEP:
            out[k] = {kk: vv for kk, vv in v.items() if kk != "at"} | {"age": round(t - v["at"], 1)}
    return out or None


def _place(ids: list[str], pos: dict) -> int:
    """A place in a live text, as it stands now: after the character before it, else before the one
    after it, else where it was, clamped (`forms.CURSOR`'s POS)."""
    if pos.get("b") and pos["b"] in ids:
        return ids.index(pos["b"]) + 1
    if pos.get("n") and pos["n"] in ids:
        return ids.index(pos["n"])
    return max(0, min(len(ids), int(pos.get("i") or 0)))


#: The heading of the block a Rouh's reader is handed, the line before its person's words.
HEAD = ('Where your own person is pointing (from their own screen, only theirs; for words like "this", '
        '"this one", "these" or "here"):')


def said_for(org: str, sid: str, sd: dict | None = None) -> str:
    """The block a Rouh's reader is handed about its own person's pointer and selection, or "".

    It says which part (by its id) and, for a selection, which words: those words are the space's,
    written by anyone, so they are boxed as untrusted like the rest of the space. Nothing of anyone
    else's cursor is ever in it."""
    from rouh import untrusted

    got = pointing(org, sid)
    if not got:
        return ""
    lines = [HEAD]
    p = got.get("point")
    if p:
        part = p["part"]
        kind, _, name = part.partition(":")
        what = {"item": "an item of list {list}", "list": "the list {name}", "text": "the text {name}",
                "field": "the field {name}", "el": 'the element with data-rouh-id "{name}"'}.get(kind, "{name}")
        lst = ""
        if kind == "item" and sd:
            lst = next((ln for ln, items in (sd.get("lists") or {}).items() if any(it["id"] == name for it in items)), "")
            if not lst:
                what = "an item no longer there"
        lines.append(f"Pointer on: {part} ({what.format(list=lst, name=name)}), {int(p['age'])} s ago.")
    s = got.get("sel")
    if s:
        t = s["t"]
        words = ""
        if t.startswith("text:") and sd:
            text = (sd.get("texts") or {}).get(t[5:]) or {}
            ids = list(text.get("ids") or [])
            a, f = sorted((_place(ids, s["a"]), _place(ids, s["f"])))
            body = str(text.get("text") or "")
            if a == f:
                lines.append(f"Caret in {t}, at character {a}, just after:")
                words = body[max(0, a - 80):a]
            else:
                lines.append(f"Selected in {t}, characters {a} to {f}:")
                words = body[a:f]
        elif s.get("q"):
            lines.append(f"Selected in {t if t != 'src' else 'the source'}:")
            words = s["q"]
        if words:
            lines.append(untrusted.wrap(words[:600], "what your person selected in the shared space"))
        elif lines[-1].endswith(":") and lines[-1] != HEAD:
            lines.pop()
    return "\n".join(lines) if len(lines) > 1 else ""
