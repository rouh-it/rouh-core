"""A stand-in Rouh that holds the room while the owner's Rouh is off (phase 2).

The owner's person names one member's Rouh as the space's stand-in (``choose``). When the room's
Rouh stops answering:

- **the stand-in** starts a room of its own for the space (`maybe_hold`), from its copy as it was,
  and takes everyone's changes in its own order, checked by the same code (`spaces.submit`);
- **the other members** that are connected to the stand-in poll it instead, and their changes go
  to it;
- **when the owner's Rouh is back**, the stand-in hands it every change it took (``standin.handback``),
  and the owner's room takes each as from the one who made it, checked again in code; then every
  copy drops the stand-in's numbering and follows the owner's room again, which numbers them anew.

Nothing is lost: a change the stand-in took is in the owner's room after the handback, and one
nobody could deliver waits in the outbox and the mailbox as before.
"""
from __future__ import annotations

import asyncio
import logging
import time

from . import limits, log, wire

log_ = logging.getLogger("rouh.link")


def choose(org: str, sid: str, label: str) -> dict:
    """The owner's person names the stand-in (or none, with "")."""
    from rouh.models import LinkSpace

    from . import peers, spaces

    row = spaces._row(org, sid)
    if row is None or not row.mine:
        raise peers.Problem("Only the Rouh holding a space names its stand-in.")
    if label:
        role = spaces.role_of(row, label)
        p = peers.peer_row(org, label)
        if role not in ("editor", "owner") or p is None or p.state != "connected":
            raise peers.Problem("The stand-in must be a connected Rouh in the space, as an editor.")
    LinkSpace.objects.filter(id=row.id).update(meta=dict(row.meta or {}, standin=label))
    log.write(org, "standin", f"{('Named ' + label + ' the stand-in') if label else 'No stand-in now'} for “{row.title[:60]}”.",
              peer=label, space=sid)
    spaces._wake(org, sid)
    return {"standin": label}


def _set(org: str, sid: str, **changes) -> None:
    from rouh.models import LinkSpace

    from . import spaces

    row = spaces._row(org, sid)
    if row is not None:
        LinkSpace.objects.filter(id=row.id).update(meta=dict(row.meta or {}, **changes))


async def reachable(org: str, peer, timeout: float = 5.0) -> bool:
    try:
        await wire.ask(org, peer, "ping", {}, timeout=timeout)
        return True
    except Exception:  # noqa: BLE001
        return False


async def maybe_hold(org: str, sid: str, live, row, me) -> bool:
    """The room's Rouh did not answer. The stand-in starts holding; another member turns to it. True
    when something changed and the follower should go round again at once."""
    standin = (row.meta or {}).get("standin") or ""
    if not standin:
        return False
    if standin == me.label:
        if not live.standin_room:
            live.standin_room = True
            live.standin_base = live.holder_seq
            await asyncio.to_thread(_set, org, sid, standin_active=me.label)
            await asyncio.to_thread(log.write, org, "standin",
                                    f"Holding the room of “{row.title[:60]}” while {row.holder_label} is off.",
                                    peer=row.holder_label, space=sid)
            await live.changed()
        return True
    if (row.meta or {}).get("standin_active") != standin:
        from . import peers

        p = await asyncio.to_thread(peers.peer_row, org, standin)
        if p is None or p.state != "connected":
            return False
        await asyncio.to_thread(_set, org, sid, standin_active=standin)
        await live.changed()
        return True
    return False


async def drop_interim(org: str, sid: str, live) -> None:
    """Forget the stand-in's numbering: the owner's room numbers those changes anew."""
    from rouh.models import LinkOp

    base = live.holder_seq
    async with live.lock:
        interim = [o for o in live.ops if o.get("seq", 0) > base]
        live.ops = [o for o in live.ops if o.get("seq", 0) <= base]
        live.seq = base
        await asyncio.to_thread(lambda: LinkOp.objects.filter(org_id=org, space_id=sid, seq__gt=base).delete())
        live.recompute()
    await asyncio.to_thread(_set, org, sid, standin_active="")
    live.standin_room = False
    live.holder_off = False
    await live.changed()
    return interim


async def hand_back(org: str, sid: str, live, row, me) -> None:
    """The owner's Rouh answers again. The stand-in hands it what it took; every copy then follows
    the owner's room again."""
    from . import peers, spaces

    if live.standin_room:
        interim = [spaces._wire_op(o) for o in live.ops if o.get("seq", 0) > live.standin_base]
        holder = await asyncio.to_thread(peers.peer_row, org, row.holder_label)
        if interim and holder is not None:
            try:
                await wire.ask(org, holder, "standin.handback", {"space_id": sid, "ops": interim[:2000]}, timeout=30)
            except (wire.Unreachable, wire.Refusal) as exc:
                log_.info("the handback did not go: %s", exc)
                return
        await asyncio.to_thread(log.write, org, "standin",
                                f"Handed {len(interim)} change(s) back to {row.holder_label}, which holds the room again.",
                                peer=row.holder_label, space=sid)
    await drop_interim(org, sid, live)


@wire.handles("standin.handback")
async def _handback(ctx, form) -> dict:
    """On the owner's Rouh: the stand-in's changes, each taken as from the one who made it."""
    from . import spaces

    sid = form["space_id"]
    row = await asyncio.to_thread(spaces._row, ctx.org, sid)
    if row is None or not row.mine:
        raise limits.No("This Rouh does not hold that room.")
    if (row.meta or {}).get("standin") != ctx.peer.label:
        raise limits.No("You are not this space's stand-in.")
    taken, refused = 0, 0
    for op in form["ops"]:
        sender = op["actor"].split(":", 1)[1]
        clean = {k: v for k, v in op.items() if k != "seq"}
        try:
            got = await spaces.submit(ctx.org, sid, sender, [clean])
            taken += len(got["accepted"])
            refused += len(got["refused"])
        except limits.No:
            refused += 1
    await asyncio.to_thread(log.write, ctx.org, "standin",
                            f"{ctx.peer.name} held the room while this Rouh was off and handed back {taken} change(s)"
                            + (f"; {refused} refused" if refused else "") + ".", peer=ctx.peer.label, space=sid)
    return {"taken": taken, "refused": refused, "at": time.time()}
