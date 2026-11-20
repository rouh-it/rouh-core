"""Anatomy, Behaviour, Permissions, at /anatomy/behaviour/permissions (`rouh/unrestricted.py`).

    GET  /api/permissions        the mode now and when it ends, the flips, What Rouh did, what is
                                 still asked in every mode, and what rouh-open has open
    POST /api/permissions        {mode, how, hours}: the owner's own press of the switch
    POST /api/permissions/undo   {id}: one row of What Rouh did put back, where its service allows

Reading needs a sign-in. The switch is the owner's alone: `unrestricted.OwnerPress.of` takes this
signed-in POST, which Django's CSRF check has let through (this view is never csrf_exempt), and
refuses anyone but the installation's owner. Nothing else in Rouh can make that press.
"""
from __future__ import annotations

import asyncio
import logging

from django.http import HttpRequest

from .clock import _signed_in, their_clock
from .common import answer, body_of, only, refuse

log = logging.getLogger("rouh.web.permissions")
NO_STORE = {"Cache-Control": "no-store"}


def _page(me, most: int = 100) -> dict:
    from rouh import unrestricted

    mode = unrestricted.current(me)
    return {"mode": mode.as_dict(), "flips": unrestricted.flips(me),
            "did": unrestricted.feed(me, most), "did_total": unrestricted.feed_total(me),
            "still_asks": list(unrestricted.STILL_ASKS.values()),
            "grants": unrestricted.grants_open(), "most_hours": unrestricted.MOST_HOURS,
            "can_change": bool(getattr(me, "is_admin", False)) and unrestricted._is_owner(me)}


@only("GET", "POST")
@their_clock
async def page(request: HttpRequest):
    from rouh import unrestricted

    me = await asyncio.to_thread(_signed_in, request)
    if me is None:
        return refuse("Sign in first.", 401)
    if request.method == "GET":
        if request.GET.get("only") == "mode":
            # The top row's chip asks this every minute: the mode alone, nothing else read.
            got = await asyncio.to_thread(lambda: unrestricted.current(me).as_dict())
            return answer({"ok": True, "mode": got}, headers=NO_STORE)
        try:
            most = max(1, min(2000, int(request.GET.get("most") or 100)))
        except ValueError:
            most = 100
        return answer({"ok": True, **await asyncio.to_thread(_page, me, most)}, headers=NO_STORE)
    body = body_of(request)

    def press():
        made = unrestricted.OwnerPress.of(request, me)
        return unrestricted.flip(made, str(body.get("mode") or ""), str(body.get("how") or ""),
                                 body.get("hours"))

    try:
        await asyncio.to_thread(press)
        # The key proxy hears the switch at once, not at its next look (`rouh/run_access.py`).
        from rouh import run_access

        await run_access.now()
    except unrestricted.NotAPress as exc:
        return refuse(str(exc), 403)
    except ValueError as exc:
        return refuse(str(exc), 400)
    except Exception:  # noqa: BLE001 - said plainly, and the log has why
        log.exception("the mode could not be switched")
        return refuse("That could not be saved. Try again.", 500)
    return answer({"ok": True, **await asyncio.to_thread(_page, me)}, headers=NO_STORE)


@only("POST")
@their_clock
async def undo(request: HttpRequest):
    from rouh import unrestricted

    me = await asyncio.to_thread(_signed_in, request)
    if me is None:
        return refuse("Sign in first.", 401)
    if not (getattr(me, "is_admin", False) and await asyncio.to_thread(unrestricted._is_owner, me)):
        return refuse("Only the owner of this Rouh can undo what it did.", 403)
    try:
        ident = int(body_of(request).get("id"))
    except (TypeError, ValueError):
        return refuse("Which one?", 400)
    got = await asyncio.to_thread(unrestricted.undo, me, ident)
    page_now = await asyncio.to_thread(_page, me)
    if not got["ok"]:
        return refuse(got["said"], 400, **page_now)
    return answer({"ok": True, "said": got["said"], **page_now}, headers=NO_STORE)
