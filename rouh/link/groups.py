"""Group keys for a live space of three or more (phase 2), in the manner of MLS.

MLS (the Messaging Layer Security standard, RFC 9420) gives a group one secret per **epoch**, and a
new epoch whenever someone joins or leaves, so a member who left cannot read what comes after.
This is that idea, built on what Rouh Link already has, and not RFC 9420 itself (there is no
maintained Python implementation of it; a real MLS library can take this module's place later):

- The Rouh holding the room makes a random 32-byte key for the space's current members, epoch by
  epoch, and hands it to each member locked to that member alone (``group.welcome``, inside the
  usual pairwise envelope, so only that member can read it).
- A new epoch, with a new key, the moment the set of members changes (joined, left, removed, a
  connection cut or lowered), so a member who left holds no key to what follows.
- What the room sends a member of a group (each long poll's changes) is then locked once more under
  the epoch's key and signed by the room (`seal.group_lock`), on top of the pairwise lock; a member
  says which epoch it holds when it polls, and until its welcome arrives it is answered pairwise.

Spaces of two keep the pairwise lock alone: a group key adds nothing between two.
"""
from __future__ import annotations

import base64
import logging
import os
import time

from . import limits, log, wire

log_ = logging.getLogger("rouh.link")
KEEP_EPOCHS = 3


def _box():
    from rouh.encryption import box

    return box()


def _joined(row) -> list[str]:
    from . import spaces

    return sorted(m["label"] for m in spaces.members_of(row)
                  if m.get("state") == "joined" and m["label"] != row.holder_label)


def is_group(row) -> bool:
    return len(_joined(row)) >= 2


def current(org: str, sid: str) -> tuple[int, bytes] | None:
    """(epoch, key) this Rouh holds for the space now, or None."""
    from . import spaces

    row = spaces._row(org, sid)
    if row is None:
        return None
    meta = row.meta or {}
    epoch = int(meta.get("epoch") or 0)
    sealed = (meta.get("epochs") or {}).get(str(epoch))
    if not epoch or not sealed:
        return None
    return epoch, base64.b64decode(_box().open_(sealed))


def key_of(org: str, sid: str, epoch: int) -> bytes | None:
    from . import spaces

    row = spaces._row(org, sid)
    sealed = ((row.meta or {}).get("epochs") or {}).get(str(epoch)) if row is not None else None
    return base64.b64decode(_box().open_(sealed)) if sealed else None


def _keep(org: str, sid: str, epoch: int, key: bytes, members: list[str]) -> None:
    from rouh.models import LinkSpace

    from . import spaces

    row = spaces._row(org, sid)
    meta = dict(row.meta or {})
    epochs = dict(meta.get("epochs") or {})
    epochs[str(epoch)] = _box().seal(base64.b64encode(key).decode())
    for old in sorted(epochs, key=int)[:-KEEP_EPOCHS]:
        epochs.pop(old, None)
    meta.update(epoch=epoch, epochs=epochs, group_members=members)
    LinkSpace.objects.filter(id=row.id).update(meta=meta)


def ensure(org: str, sid: str) -> int:
    """On the room's Rouh: a key for the members there are now; a new epoch if they changed. The
    epoch, or 0 for a space of two."""
    from . import peers, spaces

    row = spaces._row(org, sid)
    if row is None or not row.mine:
        return 0
    members = _joined(row)
    meta = row.meta or {}
    if len(members) < 2:
        return 0
    if meta.get("group_members") == members and current(org, sid):
        return int(meta["epoch"])
    epoch = int(meta.get("epoch") or 0) + 1
    key = os.urandom(32)
    _keep(org, sid, epoch, key, members)
    secret = base64.b64encode(key).decode()
    view = spaces._member_view(spaces._row(org, sid))
    for label in members:
        p = peers.peer_row(org, label)
        if p is not None and p.state == "connected":
            wire.queue(org, p, "group.welcome", {"space_id": sid, "epoch": epoch, "secret": secret, "members": view})
    log.write(org, "group", f"A new group key (epoch {epoch}) for “{row.title[:60]}”, for its {len(members) + 1} Rouhs.",
              space=sid)
    return epoch


def rekey_soon(org: str, sid: str) -> None:
    try:
        ensure(org, sid)
    except Exception:  # noqa: BLE001 - the pairwise lock still holds meanwhile
        log_.exception("a group key could not be made")


@wire.handles("group.welcome")
def _welcome(ctx, form) -> dict:
    """A member's Rouh takes the space's key for an epoch, from the Rouh holding the room only."""
    from . import spaces

    row = spaces._row(ctx.org, form["space_id"])
    if row is None or row.mine or row.holder_label != ctx.peer.label:
        raise limits.No("Only the Rouh holding a space hands out its key.")
    key = base64.b64decode(form["secret"])
    if len(key) != 32:
        raise limits.No("That is not a group key.")
    _keep(ctx.org, row.space_id, int(form["epoch"]), key, sorted(m["label"] for m in form["members"]))
    log.write(ctx.org, "group", f"Took the group key (epoch {form['epoch']}) for “{row.title[:60]}”.",
              peer=ctx.peer.label, space=row.space_id)
    return {}


def lock_reply(org: str, sid: str, member_epoch: int, me, reply: dict) -> dict:
    """The room's answer to a member, locked under the group key too when the member holds it."""
    from . import seal

    got = current(org, sid)
    if got is None or not member_epoch or member_epoch != got[0]:
        return reply
    return {"group": seal.group_lock(got[1], got[0], sid, me.label, me.seed, me.daily_public, reply),
            "at": time.time()}


def open_reply(org: str, sid: str, holder_key: str, got: dict) -> dict:
    from . import forms, seal

    box = got.get("group")
    if not isinstance(box, dict):
        return got
    if box.get("from_key") != holder_key or box.get("group") != sid:
        raise forms.Refused("the group box is not from the room's Rouh")
    key = key_of(org, sid, int(box.get("epoch") or 0))
    if key is None:
        raise forms.Refused("no key for that epoch here")
    return seal.group_unlock(box, key)
