"""The doctor: puts a Rouh's code back when Rouh stops answering right after a change.

Part of the protected core (guard/README.md; task 98, step 98-23). It sits outside anything the
Rouh edits, asks Rouh's health page (``ROUH_GUARD_HEALTH``, http://core:8021/healthz) every few
seconds, and acts on one case only: the code that runs is a change (an undo point the change step
made, not the first one), it went live less than ``WINDOW`` ago, and Rouh has not answered "ok" for
``PATIENCE`` without a break. Then it puts /code back to the undo point that ran before the change
(``Changes.undo``, kind "doctor"), never the data, and the core starts again on it.

``PATIENCE`` is fifteen minutes (Petar, 11 November 2026: five was too low, "sometimes operations
take longer"). Its clock starts only once the core has really started on the code that runs, as the
core's start says by asking ``verify`` (``Changes.started``): a core still busy with the code before,
still in that code's migration, has not run this code at all, so this code is not what failed. On
11 November 2026 undo point 174 held the core in a 14-minute data migration; the doctor put 173
back at five minutes, the core never got to 173, and five minutes later the doctor blamed 173 too.

It never goes back later on its own, never twice for the same change, and never because of a slow
first start: a slow start or a network outage after the window is not its business. It says what
it did once: a notice in the guard's signal, which Rouh shows its person when it is up again, and
the Changes page keeps it with a press to put the change back.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
import urllib.request

log = logging.getLogger("rouh-guard")

EVERY = float(os.environ.get("ROUH_GUARD_DOCTOR_EVERY", "15"))
PATIENCE = float(os.environ.get("ROUH_GUARD_DOCTOR_PATIENCE", "900"))
WINDOW = float(os.environ.get("ROUH_GUARD_DOCTOR_WINDOW", "1800"))


def healthy(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            return b'"ok":true' in r.read().replace(b" ", b"")
    except Exception:  # noqa: BLE001 - not answering is the answer
        return False


class Doctor:
    def __init__(self, changes, url: str | None = None):
        self.changes = changes
        self.url = url or os.environ.get("ROUH_GUARD_HEALTH", "http://core:8021/healthz")
        self.failing_since: float | None = None
        self.last_ok: float | None = None
        self.acted: dict | None = None

    def status(self) -> dict:
        return {"watching": self.url, "patience_minutes": round(PATIENCE / 60, 1),
                "window_minutes": round(WINDOW / 60, 1), "healthy": self.failing_since is None and self.last_ok is not None,
                "failing_since": self.failing_since, "last_ok": self.last_ok, "acted": self.acted}

    async def once(self, now: float | None = None) -> dict | None:
        now = time.time() if now is None else now
        ok = await asyncio.to_thread(healthy, self.url)
        if ok:
            self.failing_since = None
            self.last_ok = now
            return None
        if self.failing_since is None:
            self.failing_since = now
        if self.changes.busy:
            return None
        cur = self.changes.point(self.changes.data.get("current"))
        back = self.changes.doctor_target()
        if cur is None or back is None:
            return None
        # When the core started on this point; None when it has not since the point went live.
        began = self.changes.started("core", cur["n"])
        if began is None:
            return None
        live = max(cur["at"], float(cur.get("live") or 0))
        if now - live > WINDOW:
            return None
        if now - max(self.failing_since, live, began) < PATIENCE:
            return None
        minutes = max(1, int(round(PATIENCE / 60)))
        said = (f"Rouh did not answer for {minutes} minute{'s' if minutes != 1 else ''} after the change “{cur['why'][:120]}” "
                f"(undo point {cur['n']}), so the doctor put its code back to undo point {back['n']}. "
                "Your data was not touched. The change is kept, and Changes can put it back.")
        self.changes.mark_doctored(cur["n"])
        got = await self.changes.undo(back["n"], by="the doctor", kind="doctor", said=said)
        self.acted = {"at": now, "from": cur["n"], "to": back["n"], "said": said, "ok": got.get("ok")}
        self.failing_since = None
        return self.acted

    async def watch(self) -> None:
        while True:
            try:
                await self.once()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - the doctor never stops for one bad look
                log.exception("the doctor's look stumbled; it looks again")
            await asyncio.sleep(EVERY)
