"""The limits, checked by a program outside the AI, before anything another Rouh sent is acted on.

Safety rule 3 of the concept (task 123's design of a signer that checks limits in code): whatever a
model may say, what another Rouh may do here is decided here, by its connection's trust level, its
side (Work or Personal), the owner's switches, the space's roles and claims, and how fast it is
asking. A model is never asked whether something is allowed.

- `gate(org, peer_row, kind)`: may this Rouh send this kind of message at all. A blocked or cut
  connection, a kind its level does not allow, strangers while the owner's switch is off, or too
  many messages a minute are each refused here, before the message is read.
- `may_change(...)`: may this actor make this change in this space (`room.py` asks, for every op).
- `rate`: per sender, a minute's allowance by level.
"""
from __future__ import annotations

import threading
import time
from collections import deque

from . import trust

#: Messages a minute, by level; a live room sends many small ones.
PER_MINUTE = {"stranger": 20, "known": 900, "colleague": 1500, "family": 1500, "delegate": 1500}
#: Changes a person or Rouh outside this one may never make, whoever they are.
ONLY_PERSONS = {"yes", "restore", "pace"}
ONLY_HOLDER = {"settle"}


class No(Exception):
    """Refused, with the reason in plain words."""


_RATE: dict[tuple[str, str], deque] = {}
_RATE_LOCK = threading.Lock()


def rate(org: str, label: str, level: str, now: float | None = None) -> None:
    t = time.time() if now is None else now
    most = PER_MINUTE.get(trust.valid(level), 20)
    with _RATE_LOCK:
        q = _RATE.setdefault((org, label), deque())
        while q and q[0] < t - 60:
            q.popleft()
        if len(q) >= most:
            raise No(f"{label} is sending too fast; try again in a minute.")
        q.append(t)


def gate(org: str, peer, kind: str) -> str:
    """The level to treat this sender at, or No. ``peer`` is its LinkPeer row, or None (unknown)."""
    from . import me as _me

    settings = _me.settings(org)
    if peer is None:
        if kind == "hello":
            return "stranger"
        if not settings["strangers"]:
            raise No("This Rouh does not take messages from Rouhs it does not know yet.")
        level = "stranger"
    else:
        if peer.state == "blocked":
            raise No("This Rouh blocked you.")
        if peer.state == "cut" and kind not in ("hello", "ping"):
            raise No("This connection was cut.")
        if peer.state not in ("connected", "cut") and kind not in ("hello", "ping", "bye", "cut"):
            raise No("This connection is not made yet: its person has not said yes.")
        level = trust.valid(peer.trust)
        if level == "stranger" and not settings["strangers"] and kind not in ("hello", "ping", "bye", "cut"):
            raise No("Strangers are switched off on this Rouh.")
    if not trust.may_send(level, kind):
        raise No(f"A {trust.WORDS[level]} Rouh may not send {kind} here.")
    rate(org, peer.label if peer is not None else "?", level)
    return level


def touched_claims(doc: dict, op: dict) -> list[str]:
    from . import doc as _doc

    return [p for p in _doc.parts_of(op) if p in doc["claims"]]


def may_change(*, space_meta: dict, doc: dict, op: dict, sender_label: str, holder_label: str,
               role: str, from_holder_code: bool = False) -> None:
    """No unless this change may be made: by its role, its claims, and who may decide what."""
    from . import doc as _doc

    kind = op["kind"]
    actor = op["actor"]
    who, label = actor.split(":", 1)
    if label != sender_label:
        raise No("A Rouh may only speak for itself and its own person.")
    if kind in ONLY_HOLDER and not from_holder_code:
        raise No("Only the Rouh holding the room settles a proposal, after each person's yes.")
    if kind in ONLY_PERSONS and who != "person":
        raise No("Only a person says yes or brings back an earlier version; no Rouh does.")
    if kind == "undo" and who == "rouh" and op["target"] != actor:
        raise No("A Rouh may only undo its own edits.")
    if role == "viewer":
        raise No("A viewer only watches.")
    if role == "commenter" and kind not in ("comment", "resolve", "doing"):
        raise No("A commenter only comments.")
    if kind == "resolve" and role == "commenter":
        c = doc["comments"].get(op["cid"])
        if c and c["by"] != actor:
            raise No("A commenter resolves only their own comments.")
    if kind == "yes":
        prop = doc["proposals"].get(op["pid"])
        if prop is None or prop["state"] != "open":
            raise No("That proposal is not open.")
        if label not in prop["needed"]:
            raise No("That proposal is not yours to answer.")
        if not any(o["id"] == op["option"] for o in prop["options"]):
            raise No("That is not one of the options.")
    if kind == "release":
        claim = doc["claims"].get(op["part"])
        if claim and claim["by"] != actor and who != "person":
            raise No("Only the one who claimed it, or a person, releases a part.")
    if kind == "claim" and op["part"] in doc["claims"] and doc["claims"][op["part"]]["by"] != actor:
        raise No("Another got there first: that part is claimed.")
    if kind in _doc.CONTENT and who == "rouh":
        for part in touched_claims(doc, op):
            if doc["claims"][part]["by"] != actor:
                raise No(f"That part is claimed by {doc['claims'][part]['by'].split(':', 1)[1]}.")
    del space_meta, holder_label
