"""Sending to another Rouh and taking in what it sends: the inbox, the outbox and the mailbox.

Every message is an envelope (`seal.py`), POSTed to the other Rouh's inbox, ``<its address>/link/in``.
Its address is ``https://<label>.rouh.page``, so it goes through the relay, which routes it by the
name in the TLS hello and never holds a key that opens it; and the envelope inside is locked again,
to the other Rouh's link key, so even the TLS ending on the other side's own machine is not what
keeps it private. The answer is an envelope locked back to the sender.

A Rouh that is off does not answer. Then a message that can wait goes into the mailbox beside the
relay (`mailbox.py`), filed under the receiver's daily key, for up to 30 days, and the receiver takes
it out when it is back. Every message has an id, and the inbox remembers each id it took in with
its answer, so delivering one twice does no harm: the second time gets the first answer.

Order of work on the way in, for every message, before any handler sees it:
the envelope's form; for this Rouh; its signature by the key it names, and that key the sender's
(its card, chained from its birth key, for one not met yet); the limits (`limits.gate`); seen
before? (answer as before); its fixed form (`forms.read_message`); only then the handler.
"""
from __future__ import annotations

import asyncio
import inspect
import logging
import os
import time
import uuid
from dataclasses import dataclass

from . import forms, limits, seal

log = logging.getLogger("rouh.link")

#: How long a straight delivery may take before a message that can wait goes to the mailbox.
TIMEOUT = 12.0
#: Kinds that may wait in the mailbox when the other Rouh is off.
MAY_WAIT = {"meeting.ask", "meeting.busy", "space.invite", "space.ended", "space.left", "room.ops",
            "grant.shown", "grant.withdrawn", "group.welcome", "cut", "bye", "trust.told",
            "standin.handback", "handoff.brief", "handoff.quote", "money.proposal", "hello"}
#: What a handler's answer is sent as, when its message came by the mailbox (no one waits for it).
REPLY_AS = {"meeting.ask": "meeting.busy"}


def _now() -> float:
    return time.time()


def mailbox_url() -> str:
    url = os.environ.get("ROUH_LINK_MAILBOX", "").strip() or "https://mailbox.rouh.page/"
    return url if url.endswith("/") else url + "/"


@dataclass
class Ctx:
    org: str
    me: object
    peer: object
    level: str
    head: dict
    kind: str
    by_mailbox: bool = False


_HANDLERS: dict[str, object] = {}


def handles(kind: str):
    def put(fn):
        _HANDLERS[kind] = fn
        return fn
    return put


def _load_handlers() -> None:
    from . import cursors, grants, groups, handoff, meeting, pageout, peers, spaces, standin  # noqa: F401 - each registers its kinds


# --- the network -----------------------------------------------------------------------------------


def _client(timeout: float = TIMEOUT):
    import httpx

    return httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=min(6.0, timeout)),
                             follow_redirects=False, headers={"User-Agent": "rouh-link/1"})


async def get_json(url: str, timeout: float = 10.0) -> dict:
    async with _client(timeout) as c:
        r = await c.get(url)
    if r.status_code != 200:
        raise Unreachable(f"{url} answered {r.status_code}")
    try:
        got = r.json()
    except ValueError:
        raise Unreachable(f"{url} did not answer JSON") from None
    if not isinstance(got, dict):
        raise Unreachable("not a JSON object")
    return got


class Unreachable(Exception):
    """The other Rouh did not answer (it is off, or the network is down)."""


class Refusal(Exception):
    """The other Rouh answered, and said no; its words are outside words."""

    def __init__(self, said: str, status: int = 400):
        super().__init__(said)
        self.said = forms.Outside(str(said)[:300])
        self.status = status


async def post_envelope(address: str, env: dict, timeout: float = TIMEOUT) -> dict:
    """The envelope the other Rouh answered with, Refusal, or Unreachable. An address this Rouh may
    not dial (`peers.dialable`) is unreachable: the mailbox carries it."""
    import httpx

    from . import peers

    address = peers.dialable(address)
    if not address:
        raise Unreachable("this Rouh is reached by the mailbox only")

    try:
        async with _client(timeout) as c:
            r = await c.post(address.rstrip("/") + "/link/in", json=env)
    except (httpx.HTTPError, OSError) as exc:
        raise Unreachable(f"{type(exc).__name__}") from None
    try:
        got = r.json()
    except ValueError:
        # The relay's own page for a name with no Rouh on the line: the Rouh is off.
        raise Unreachable(f"answered {r.status_code}, not a Rouh") from None
    if r.status_code == 200 and isinstance(got, dict) and got.get("v") == 1:
        return got
    if isinstance(got, dict) and got.get("error"):
        raise Refusal(str(got["error"]), r.status_code)
    raise Unreachable(f"answered {r.status_code}")


async def post_to_peer(peer, env: dict, timeout: float = TIMEOUT) -> dict:
    """`post_envelope` to a connection: its address, and when that does not answer, its born address.
    A name a Rouh's owner chose stops working when they change it, and the other side only learns the
    new one from the card; the born name keeps answering for good. When the born address answers,
    the connection's address is brought up to the one its card shows now."""
    from . import peers

    try:
        return await post_envelope(peer.address, env, timeout)
    except Unreachable:
        born = peers.born_address(peer.address, peer.label)
        if not born or born == peer.address.rstrip("/"):
            raise
    got = await post_envelope(born, env, timeout)
    await _follow_address(peer, born)
    return got


async def _follow_address(peer, reached: str) -> None:
    """The connection's address, as the card at the address that answered gives it now."""
    from rouh.models import LinkPeer

    from . import card as _card
    from . import peers

    try:
        _got, part = await _card.fetch(reached, label=peer.label)
        now_at = peers.dialable(part.get("address") or "") or reached
    except Exception:  # noqa: BLE001 - the born address answered: keep that
        now_at = reached
    if now_at and now_at != peer.address:
        await asyncio.to_thread(lambda: LinkPeer.objects.filter(id=peer.id).update(address=now_at, updated_at=_now()))
        log.info("link: %s moved from %s to %s", peer.label, peer.address, now_at)
        peer.address = now_at


# --- sending ---------------------------------------------------------------------------------------


def _target(peer) -> tuple[str, str, str, str]:
    return peer.label, peer.address, peer.link_key, peer.daily_key


def lock_for(me, peer, kind: str, body: dict, mid: str = "") -> dict:
    label, _address, link_key, daily = _target(peer)
    return seal.lock(sender=me.label, sender_seed=me.seed, sender_key=me.daily_public, to=label,
                     to_link_key=link_key, to_key=daily, mid=mid,
                     inner={"kind": kind, "body": body})


def open_reply(me, peer, env: dict) -> dict:
    head, inner = seal.unlock(env, me=me.label, link_private=me.link_private)
    if head["from"] != peer.label or head["from_key"] != peer.daily_key:
        raise Refusal("the answer was not from the Rouh asked")
    if inner.get("error"):
        raise Refusal(str(inner["error"]))
    body = inner.get("body")
    return body if isinstance(body, dict) else {}


async def ask(org: str, peer, kind: str, body: dict, *, timeout: float = TIMEOUT, mid: str = "") -> dict:
    """Send now and wait for the answer: its body, Refusal or Unreachable. Nothing is queued."""
    from . import me as _me

    me = await asyncio.to_thread(_me.me, org)
    env = await asyncio.to_thread(lock_for, me, peer, kind, body, mid)
    got = await post_to_peer(peer, env, timeout)
    reply = await asyncio.to_thread(open_reply, me, peer, got)
    await asyncio.to_thread(_seen, org, peer.label)
    return reply


def _seen(org: str, label: str) -> None:
    from rouh.models import LinkPeer

    LinkPeer.objects.filter(org_id=org, label=label).update(last_seen_at=_now())


def queue(org: str, peer, kind: str, body: dict, *, mid: str = "") -> str:
    """Send when it can be sent: now if the other Rouh answers, else by the mailbox. Its id."""
    from rouh.models import LinkMessage

    from . import me as _me

    me = _me.me(org)
    mid = mid or str(uuid.uuid4())
    env = lock_for(me, peer, kind, body, mid)
    LinkMessage.objects.get_or_create(org_id=org, msg_id=mid, direction="out", defaults=dict(
        peer_label=peer.label, kind=kind, envelope=env, state="queued", next_at=0, created_at=_now()))
    _kick()
    return mid


_WAKE: asyncio.Event | None = None


def _kick() -> None:
    w = _WAKE
    if w is None:
        return
    try:
        loop = asyncio.get_running_loop()
        loop.call_soon(w.set)
    except RuntimeError:
        from rouh import runtime

        loop = getattr(runtime, "LOOP", None)
        if loop is not None:
            loop.call_soon_threadsafe(w.set)
        else:
            w.set()


async def deliver_due() -> int:
    """Try every message that is due once: straight, else the mailbox. How many went."""
    from rouh.models import LinkMessage, LinkPeer

    rows = await asyncio.to_thread(lambda: list(
        LinkMessage.objects.filter(direction="out", state__in=("queued", "retry"), next_at__lte=_now())
        .order_by("created_at")[:50]))
    went = 0
    for row in rows:
        peer = await asyncio.to_thread(lambda: LinkPeer.objects.filter(org_id=row.org_id, label=row.peer_label).first())
        if peer is None:
            await asyncio.to_thread(_mark, row.id, "refused", "no such connection")
            continue
        try:
            await post_to_peer(peer, row.envelope)
            await asyncio.to_thread(_mark, row.id, "done", "delivered")
            await asyncio.to_thread(_seen, row.org_id, peer.label)
            went += 1
        except Refusal as exc:
            await asyncio.to_thread(_mark, row.id, "refused", str(exc.said))
        except Unreachable:
            if row.kind in MAY_WAIT:
                try:
                    await mailbox_put(row.envelope)
                    await asyncio.to_thread(_mark, row.id, "mailbox", "left in the mailbox")
                    went += 1
                    continue
                except Unreachable as exc2:
                    log.info("mailbox put failed: %s", exc2)
            await asyncio.to_thread(_retry, row.id, row.tries)
    return went


def _mark(rid: int, state: str, said: str) -> None:
    from rouh.models import LinkMessage

    LinkMessage.objects.filter(id=rid).update(state=state, said=said[:300], done_at=_now(), envelope={})


def _retry(rid: int, tries: int) -> None:
    from rouh.models import LinkMessage

    wait = min(3600, 5 * (2 ** min(tries, 10)))
    state = "retry" if tries < 40 else "refused"
    LinkMessage.objects.filter(id=rid).update(state=state, tries=tries + 1, next_at=_now() + wait,
                                              said="the other Rouh did not answer")


# --- the mailbox -----------------------------------------------------------------------------------


async def mailbox_put(env: dict) -> None:
    import httpx

    if not env.get("to_key"):
        raise Unreachable("no key to file it under")
    try:
        async with _client(10) as c:
            r = await c.post(mailbox_url() + "v1/put", json={"env": env})
    except (httpx.HTTPError, OSError) as exc:
        raise Unreachable(f"the mailbox: {type(exc).__name__}") from None
    if r.status_code != 200:
        raise Unreachable(f"the mailbox answered {r.status_code}")


def _take_proof(me) -> dict:
    at = int(_now())
    nonce = uuid.uuid4().hex
    body = {"take": me.daily_public, "at": at, "nonce": nonce}
    return {**body, "sig": seal.sign(me.seed, body)}


async def mailbox_take(org: str) -> int:
    """Take this Rouh's messages out of the mailbox, take each in, and tell the mailbox they are
    taken. How many."""
    import httpx

    from . import me as _me

    me = await asyncio.to_thread(_me.me, org)
    try:
        async with _client(15) as c:
            r = await c.post(mailbox_url() + "v1/take", json=_take_proof(me))
            if r.status_code != 200:
                return 0
            got = r.json().get("messages") or []
            done = []
            for item in got[:200]:
                env = item.get("env") if isinstance(item, dict) else None
                if not isinstance(env, dict):
                    continue
                try:
                    await receive(env, by_mailbox=True)
                except Exception as exc:  # noqa: BLE001 - one bad message never stops the rest
                    log.info("a mailbox message was refused: %s", exc)
                done.append(str(item.get("id") or env.get("id")))
            if done:
                await c.post(mailbox_url() + "v1/ack", json={**_take_proof(me), "ids": done})
            return len(done)
    except (httpx.HTTPError, OSError, ValueError):
        return 0


# --- taking in -------------------------------------------------------------------------------------


def _peer_for(org: str, label: str):
    from rouh.models import LinkPeer

    return LinkPeer.objects.filter(org_id=org, label=label).first()


def _seen_before(org: str, mid: str):
    from rouh.models import LinkMessage

    return LinkMessage.objects.filter(org_id=org, msg_id=mid, direction="in").first()


def _remember(org: str, mid: str, label: str, kind: str, reply: dict, state: str = "done", said: str = "") -> None:
    from django.db import IntegrityError

    from rouh.models import LinkMessage

    try:
        LinkMessage.objects.create(org_id=org, msg_id=mid, peer_label=label, direction="in", kind=kind,
                                   envelope={"reply": reply} if kind not in ("room.poll",) else {},
                                   state=state, said=said[:300], created_at=_now(), done_at=_now())
    except IntegrityError:
        pass


async def _key_holds(org: str, peer, head: dict) -> object:
    """The peer row, its daily key brought up to date when the card shows a new one in its chain."""
    if peer is None or head["from_key"] == peer.daily_key:
        return peer
    from . import card as _card

    from . import peers

    try:
        fetched, part = await _card.fetch(peer.address, label=peer.label)
    except Exception:  # noqa: BLE001 - a name its owner changed: its born address
        try:
            fetched, part = await _card.fetch(peers.born_address(peer.address, peer.label), label=peer.label)
        except Exception:  # noqa: BLE001
            raise limits.No("That key is not this Rouh's.") from None
    if part["daily_key"] != head["from_key"] or part["birth_key"] != (peer.card or {}).get("birth_key", part["birth_key"]):
        raise limits.No("That key is not this Rouh's.")
    from rouh.models import LinkPeer

    await asyncio.to_thread(lambda: LinkPeer.objects.filter(id=peer.id).update(
        daily_key=part["daily_key"], link_key=part["link_key"], card=part, updated_at=_now()))
    peer.daily_key, peer.link_key, peer.card = part["daily_key"], part["link_key"], part
    del fetched
    return peer


#: Kinds that are live only (`cursors.py`): nothing of them is written down on the way in.
LIVE_ONLY = {"room.cursor"}


async def receive(env: dict, *, by_mailbox: bool = False) -> dict:
    """Take in one envelope; the envelope to answer with. Raises limits.No or seal.Refused, whose
    words are safe to send back."""
    from . import me as _me

    # Every kind's handler, whichever modules this process happened to import first (one importing
    # the room alone left `hello` unanswered on a live Rouh, 17 November 2026).
    _load_handlers()
    head = seal.outside(env)
    org = await asyncio.to_thread(_me.org_for_label, head["to"])
    if org is None:
        raise seal.Refused("There is no such Rouh here.")
    me = await asyncio.to_thread(_me.me, org)
    head, inner = await asyncio.to_thread(seal.unlock, env, me=me.label, link_private=me.link_private)
    kind = str(inner.get("kind") or "")
    peer = await asyncio.to_thread(_peer_for, org, head["from"])
    peer = await _key_holds(org, peer, head)
    level = await asyncio.to_thread(limits.gate, org, peer, kind)
    # A cursor (`cursors.py`) is live only: never looked up, kept or remembered, 15 times a second.
    live_only = kind in LIVE_ONLY
    before = None if live_only else await asyncio.to_thread(_seen_before, org, head["id"])
    if before is not None and kind != "room.poll":
        reply = (before.envelope or {}).get("reply") or {}
        return _answer(me, head, reply)
    form = forms.read_message(kind, inner.get("body"))
    fn = _HANDLERS.get(kind)
    if fn is None:
        raise limits.No(f"This Rouh does not take {kind}.")
    ctx = Ctx(org=org, me=me, peer=peer, level=level, head=head, kind=kind, by_mailbox=by_mailbox)
    if inspect.iscoroutinefunction(fn):
        reply = await fn(ctx, form)
    else:
        reply = await asyncio.to_thread(fn, ctx, form)
    reply = reply or {}
    if kind not in ("room.poll", "room.presence", "ping") and not live_only:
        await asyncio.to_thread(_remember, org, head["id"], head["from"], kind, reply)
    if peer is not None and not live_only:
        await asyncio.to_thread(_seen, org, peer.label)
    if by_mailbox and kind in REPLY_AS and reply and ctx.peer is not None:
        await asyncio.to_thread(queue, org, ctx.peer, REPLY_AS[kind], reply)
    return _answer(me, head, reply)


def _answer(me, head: dict, reply: dict) -> dict:
    """The answer, locked to the sender: its link key is in its card, which `hello` brought or the
    connection keeps."""
    from rouh.models import LinkPeer

    peer = LinkPeer.objects.filter(org_id=me.org_id, label=head["from"]).first()
    link_key = peer.link_key if peer is not None else (reply.pop("_link_key", "") if isinstance(reply, dict) else "")
    if not link_key:
        return {"v": 1, "plain": True}
    return seal.lock(sender=me.label, sender_seed=me.seed, sender_key=me.daily_public, to=head["from"],
                     to_link_key=link_key, to_key=head["from_key"], inner={"kind": "reply", "body": reply})


# --- the loop --------------------------------------------------------------------------------------

_TASK: list = []


def start() -> None:
    """The outbox and the mailbox, on Rouh's loop. Once."""
    global _WAKE
    if _TASK:
        return
    _WAKE = asyncio.Event()
    _TASK.append(asyncio.ensure_future(_loop()))


async def _loop() -> None:
    last_take = 0.0
    await asyncio.sleep(3)
    while True:
        try:
            if _now() - last_take > 30:
                last_take = _now()
                orgs = await asyncio.to_thread(_born_orgs)
                for org in orgs:
                    await mailbox_take(org)
                    from . import spaces

                    await spaces.keep_up(org)
            await deliver_due()
        except Exception:  # noqa: BLE001 - the loop goes on
            log.exception("the link loop")
        try:
            await asyncio.wait_for(_WAKE.wait(), timeout=2.0)
        except asyncio.TimeoutError:
            pass
        _WAKE.clear()


def _born_orgs() -> list[str]:
    from rouh.models import RouhBirth

    return [str(o) for o in RouhBirth.objects.filter(state="born").values_list("org_id", flat=True)]
