"""A stand-in Rouh holding the room while the owner's Rouh is off (phase 2).

Filled in by phase 2; until then a member whose room holder is off keeps working on its own copy,
and its changes wait in the outbox and the mailbox for the holder's return.
"""
from __future__ import annotations


async def maybe_hold(org, sid, live, row, me) -> bool:
    return False


async def hand_back(org, sid, live, row, me) -> None:
    return None


def choose(org: str, sid: str, label: str) -> dict:
    from .peers import Problem

    raise Problem("A stand-in comes with phase 2.")
