"""Shared until: a page or a task shared with somebody by hand can be given an end in the Share
panel, and the share is taken away by itself when it comes.

Built by the nightly feature run, night 29, 1 November 2026 (task 94, idea I-144). ‹He› shares
Work pages and tasks with people outside the company before a meeting or a decision: a
client, a writer, a partner. A share is for that moment, and nothing ever ended one: the
person kept reading, and Ask AI kept answering them on ‹his› account, until somebody
remembered to press Remove, which nobody does. Other assistants' shared links take an end
date now (Pally, 23 October 2026).

So, while its switch is on, each person in the Share panel shared with by hand has
**Until**: no end, a day, a week, two weeks or a month from now. When the end comes the share
is taken away exactly as setting the person to None takes it away (`sharing.Guests.remove`
and `task_access.taken_away`): their link stops and the page or task is no longer under
Shared for them. The end is checked every minute (`Sweeper`), and again the moment they open
the share, so a share is never read past its end. A share a trusted contact's tick keeps has
no end: it is the tick's.

**Whose.** The owner's own shares (`org_id` and `user_id` on every row and every query). It
writes its own table, `share_ends`, and takes away only shares the owner gave an end to.

**Its switch** is `share_ends` (`rouh/switches.py`): off, the panel has no Until and nothing is
taken away; the ends already set wait, and are kept, until it is on again.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from types import SimpleNamespace

log = logging.getLogger("rouh.share_ends")

SWITCH = "share_ends"
TITLE = ("Shared until: give a share an end in the Share panel, and it is taken away by itself "
         "when the end comes")
#: The ends the panel offers, in days.
CHOICES = (1, 7, 14, 30)
#: How often ended shares are looked for, in seconds.
BEAT = 60.0


def on(org_id) -> bool:
    from . import switches

    return switches.on(SWITCH, str(org_id) if org_id else None)


def _model():
    from .models import ShareEnd

    return ShareEnd


def with_ends(who, people: list[dict], rel: str) -> list[dict]:
    """The panel's people, each shared by hand with `ends` (a time, or 0 for no end)."""
    try:
        if who is None or not people or not on(getattr(who, "org_id", None)):
            return people
        tokens = [p.get("token") for p in people if p.get("token")]
        ends = dict(_model().objects.filter(org_id=who.org_id, user_id=who.user_id,
                                            token__in=tokens).values_list("token", "ends_at"))
        out = []
        for p in people:
            if p.get("token") and p.get("via") != "tick":
                p = dict(p, ends=float(ends.get(p["token"]) or 0))
            out.append(p)
        return out
    except Exception:  # noqa: BLE001 - the panel is drawn as it was
        log.warning("Shared until could not be read for the Share panel", exc_info=True)
        return people


def set_end(who, rel: str, token: str, days: int) -> tuple[float, str]:
    """(the end set, or 0 for none; "" or why it could not be set) for one of `who`'s shares."""
    from . import evolution
    from .web import guests

    if not on(getattr(who, "org_id", None)):
        return 0.0, "Shared until is switched off."
    share = next((p for p in guests._store().people(who, rel) if p.get("token") == token), None)
    if share is None:
        return 0.0, "That is not somebody this is shared with."
    if share.get("via") == "tick":
        return 0.0, "This share is kept by a tick in Trusted contacts, so it ends there."
    model = _model()
    if not days:
        model.objects.filter(token=token, org_id=who.org_id, user_id=who.user_id).delete()
        evolution.used(SWITCH, "set", who=who, detail="a share's end taken off")
        return 0.0, ""
    if int(days) not in CHOICES:
        return 0.0, "An end is a day, a week, two weeks or a month from now."
    now = time.time()
    ends = now + int(days) * 86400
    model.objects.update_or_create(
        token=token, org_id=who.org_id, user_id=who.user_id,
        defaults={"rel": str(rel or ""), "email": str(share.get("email") or ""),
                  "ends_at": ends, "set_at": now})
    evolution.used(SWITCH, "set", who=who, detail=f"a share given an end {int(days)} days away")
    return ends, ""


def _owner(row) -> SimpleNamespace:
    return SimpleNamespace(org_id=row.org_id, user_id=row.user_id)


def end_one(row) -> bool:
    """Take one ended share away, as Remove does. True when a share was there to take away."""
    from . import evolution, task_access
    from .web import guests

    owner = _owner(row)
    gone = guests._store().remove(owner, row.token)
    if gone:
        with contextlib.suppress(Exception):
            task_access.taken_away(owner, row.rel, row.email)
        log.info("shared until: a share of %s ended by itself", row.rel)
        with contextlib.suppress(Exception):
            evolution.used(SWITCH, "ended", who=owner,
                           detail="a share taken away by itself at the end it was given")
    _model().objects.filter(token=row.token, org_id=row.org_id, user_id=row.user_id).delete()
    return gone


def sweep(now: float | None = None, token: str = "") -> int:
    """Every share whose end has passed, of an organisation with the switch on, taken away."""
    now = time.time() if now is None else now
    rows = _model().objects.filter(ends_at__lte=now)
    if token:
        rows = rows.filter(token=token)
    done = 0
    for row in list(rows[:200]):
        if not on(row.org_id):
            continue
        try:
            if end_one(row):
                done += 1
        except Exception:  # noqa: BLE001 - the next beat tries again
            log.exception("shared until: a share could not be taken away")
    return done


def before_open(token: str) -> None:
    """Called as a share is opened: if its end has passed, it is taken away first."""
    try:
        if token and _model().objects.filter(token=token, ends_at__lte=time.time()).exists():
            sweep(token=token)
    except Exception:  # noqa: BLE001 - the beat takes it away
        log.warning("shared until: the end of a share could not be checked as it opened", exc_info=True)


class Sweeper:
    """Every minute, every share whose end has passed is taken away."""

    def __init__(self) -> None:
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.get_running_loop().create_task(self._run())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._task
            self._task = None

    async def _run(self) -> None:
        from asgiref.sync import sync_to_async

        await asyncio.sleep(5.0)
        while True:
            try:
                await sync_to_async(sweep, thread_sensitive=False)()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("shared until: the look for ended shares failed")
            await asyncio.sleep(BEAT)


__all__ = ["BEAT", "CHOICES", "SWITCH", "Sweeper", "TITLE", "before_open", "end_one", "on",
           "set_end", "sweep", "with_ends"]
