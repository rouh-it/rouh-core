"""The job genes on Rouh Link: each kind of job two Rouhs do together is a gene of its own.

Rouh Link itself (the card, the locks, the mailbox, the room) is core. What two Rouhs can do over it
is a gene each, with its own manifest, its own switch, and its own message forms (`forms.FORMS`).
The Rouh card lists the ones that are on, as A2A skills, so another Rouh knows what it can ask.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Job:
    id: str
    name: str
    description: str
    switch: str
    forms: tuple
    tags: tuple = ()


JOBS = (
    Job("live-space", "A live shared space",
        "Work on a task page, a document, a trip or a list together, live: presence, markers, claims, "
        "comments, history, undo per Rouh.", "", ("space.invite", "space.join", "room.poll", "room.ops"),
        ("live", "co-working")),
    Job("book-a-meeting", "Book a meeting",
        "Agree a meeting time between two or more people: only free and busy times cross; each person "
        "says yes; each Rouh books it in its own person's calendar.", "book_a_meeting",
        ("meeting.ask", "meeting.busy"), ("calendar", "meeting")),
    Job("hand-over-a-brief", "Hand over a brief",
        "A stranger's Rouh hands over a brief, and a quote comes back, in fixed forms; a person reads "
        "each and decides. Off until its person turns strangers on.", "link_handoff",
        ("handoff.brief", "handoff.quote"), ("hand-off", "brief")),
)


def on_for(org: str) -> list[Job]:
    from rouh import switches

    from . import me as _me

    out = []
    for j in JOBS:
        if j.switch and not switches.on(j.switch, org):
            continue
        if j.id == "hand-over-a-brief" and not _me.settings(org)["strangers"]:
            continue
        out.append(j)
    return out
