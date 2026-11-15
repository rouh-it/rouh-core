"""Anatomy, Meta, What Rouh keeps and runs, at /anatomy/meta/keeps (`rouh/lean.py`, task 185).

    GET  /api/anatomy/keeps              the preset, and every job and record with its value, where it comes
                                         from, its options with roughly the disk each holds, and any lowering
                                         that waits for the owner's press with what would go
    POST /api/anatomy/keeps              {item, mode, days?, confirm?}: one item set. A value that would remove
                                         old rows answers {needs_confirm, preview} and is saved only when sent
                                         again with confirm
    POST /api/anatomy/keeps/default      {item, confirm?}: back to the preset's value, the same way
    POST /api/anatomy/keeps/confirm      {item}: remove what a lowered value already in force removes
    POST /api/anatomy/keeps/preset       {preset, confirm?}: another preset; the owner's own rows stay

Reading needs a sign-in; changing needs the organisation's administrator, since it can delete. Every
value is the signed-in person's organisation's. A removal confirmed here starts that record's sweep
at once, in the background; nothing is removed without a press.
"""
from __future__ import annotations

import asyncio
import logging
import threading

from django.http import HttpRequest

from .clock import _signed_in, their_clock
from .common import answer, body_of, only, refuse

log = logging.getLogger("rouh.web.lean")
NO_STORE = {"Cache-Control": "no-store"}


async def _me(request):
    return await asyncio.to_thread(_signed_in, request)


def _sweep_soon(item_ids, org: str) -> None:
    """The confirmed removal, started now in its own thread rather than at the next daily sweep."""
    from rouh import lean

    def go():
        from django.db import close_old_connections

        try:
            for item in item_ids:
                lean.sweep_item(item, org)
        except Exception:  # noqa: BLE001 - the daily sweep tries again
            log.exception("the confirmed removal could not run now")
        finally:
            close_old_connections()

    threading.Thread(target=go, name="rouh-lean-sweep", daemon=True).start()


def _by(me) -> str:
    return "the owner on Anatomy"


async def _change(request, work):
    from rouh import lean

    me = await _me(request)
    if me is None:
        return refuse("Sign in first.", 401)
    if not getattr(me, "is_admin", False):
        return refuse("Only this Rouh's administrator can change what it keeps and runs.", 403)
    org = str(me.org_id)
    try:
        got = await asyncio.to_thread(work, org, _by(me), body_of(request))
    except lean.Refused as exc:
        return refuse(str(exc), 400, **(await asyncio.to_thread(lean.page, org)))
    except Exception:  # noqa: BLE001 - said plainly, and the log has why
        log.exception("a change to what Rouh keeps failed")
        return refuse("That could not be saved. Try again.", 500)
    if got.get("swept"):
        _sweep_soon(got.get("sweep") or ([got["item"]] if got.get("item") else []), org)
    if got.get("needs_confirm"):
        # A question carries only itself: nothing was saved, so the page as it was still holds.
        return answer({"ok": True, **got}, headers=NO_STORE)
    page = await asyncio.to_thread(lean.page, org)
    return answer({"ok": True, **got, **page}, headers=NO_STORE)


@only("GET", "POST")
@their_clock
async def page(request: HttpRequest):
    from rouh import lean

    if request.method == "POST":
        def go(org, by, body):
            return lean.set_choice(str(body.get("item") or ""), str(body.get("mode") or ""), body.get("days"),
                                   by=by, org_id=org, confirm=bool(body.get("confirm")))
        return await _change(request, go)
    me = await _me(request)
    if me is None:
        return refuse("Sign in first.", 401)
    return answer(await asyncio.to_thread(lean.page, str(me.org_id)), headers=NO_STORE)


@only("POST")
@their_clock
async def default(request: HttpRequest):
    from rouh import lean

    def go(org, by, body):
        item = str(body.get("item") or "")
        if item not in lean.BY_ID:
            raise lean.Refused("There is no such item.")
        return lean.back_to_default(item, by=by, org_id=org, confirm=bool(body.get("confirm")))
    return await _change(request, go)


@only("POST")
@their_clock
async def confirm(request: HttpRequest):
    from rouh import lean

    def go(org, by, body):
        item = str(body.get("item") or "")
        if item not in lean.BY_ID:
            raise lean.Refused("There is no such item.")
        return lean.confirm_waiting(item, by=by, org_id=org)
    return await _change(request, go)


@only("POST")
@their_clock
async def preset(request: HttpRequest):
    from rouh import lean

    def go(org, by, body):
        got = lean.set_preset(str(body.get("preset") or ""), by=by, org_id=org, confirm=bool(body.get("confirm")))
        if got.get("swept"):
            got["sweep"] = [i.id for i in lean.ITEMS if i.kind == "record" and i.parts]
        return got
    return await _change(request, go)
