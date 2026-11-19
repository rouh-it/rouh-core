"""Trust levels, and what each lets another Rouh do here. Checked in code, never by a model.

    stranger   may ask: introduce itself, hand over a brief or a quote in a fixed form, and in a
               shared space only watch or comment. Off by a setting until rouh.land's terms cover
               the relay and Rouhs talking (task 131, step 131-10).
    known      also free and busy times, meeting proposals, invitations to a space, hand-offs.
    colleague  also Work-side live spaces as an editor, and presence.
    family     also Personal-side live spaces as an editor, and presence.
    delegate   also decides for this Rouh's person inside a written grant (`grants.py`).

The order matters: each level has everything the one before it has, except that colleague and
family are each for one side only (`silo_ok`). A person lowers or cuts a connection in one press
(`peers.set_trust`, `peers.cut`).
"""
from __future__ import annotations

LEVELS = ("stranger", "known", "colleague", "family", "delegate")
WORDS = {
    "stranger": "Stranger",
    "known": "Known",
    "colleague": "Colleague",
    "family": "Family",
    "delegate": "Delegate",
}
SAYS = {
    "stranger": "May introduce itself and hand over a brief; in a space only watches or comments.",
    "known": "Also sees free and busy times, proposes meetings, invites you into a space.",
    "colleague": "Also works with you live on Work-side spaces.",
    "family": "Also works with you live on Personal-side spaces.",
    "delegate": "Also decides for you inside a written grant you can withdraw at once.",
}

#: Message kinds each level may send here. A kind not listed for a level is refused before it is read.
_BASE = {"hello", "ping", "card", "bye", "log.ask", "log.share", "cut", "trust.told"}
_STRANGER = _BASE | {"handoff.brief", "handoff.quote", "money.proposal", "space.join", "room.poll",
                     "room.ops", "space.left", "a2a.note", "space.keep_ask"}
_KNOWN = _STRANGER | {"meeting.ask", "meeting.busy", "meeting.yes", "space.invite", "space.ended",
                      "room.presence", "grant.shown", "grant.withdrawn", "group.welcome", "standin.hold",
                      "standin.handback"}
ALLOWED = {
    "stranger": _STRANGER,
    "known": _KNOWN,
    "colleague": _KNOWN,
    "family": _KNOWN,
    "delegate": _KNOWN | {"grant.decide"},
}

#: Roles in a live space, weakest first.
ROLES = ("viewer", "commenter", "editor", "owner")


def rank(level: str) -> int:
    return LEVELS.index(level) if level in LEVELS else 0


def valid(level: str) -> str:
    return level if level in LEVELS else "known"


def may_send(level: str, kind: str) -> bool:
    return kind in ALLOWED.get(valid(level), _BASE)


def most_role(level: str, space_silo: str, peer_silo: str) -> str:
    """The most a Rouh at this level may be in a space of this side; "" for not at all."""
    level = valid(level)
    if not silo_ok(space_silo, peer_silo):
        return ""
    if level == "stranger":
        return "commenter"
    if level == "known":
        return "editor"
    if level == "colleague" and space_silo == "personal":
        return ""
    if level == "family" and space_silo == "work":
        return ""
    return "editor"


def silo_ok(space_silo: str, peer_silo: str) -> bool:
    """Work and Personal stay apart: a connection on one side never sees a space of the other."""
    if not space_silo or not peer_silo:
        return True
    return space_silo == peer_silo


def role_at_most(role: str, cap: str) -> str:
    """The weaker of the two; "" when the cap is none at all."""
    if cap not in ROLES:
        return ""
    r = ROLES.index(role) if role in ROLES else 0
    c = ROLES.index(cap) if cap in ROLES else 0
    return ROLES[min(r, c)]
