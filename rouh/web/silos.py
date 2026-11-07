"""Settings, Silos, at /settings/silos (`rouh/silos.py`).

    GET  /api/settings/silos           the account's silos, what each holds, its source rules, and every
                                       project, calendar, inbox and shared drive a rule can be set on
    POST /api/settings/silos/add       {name, colour?}: a new silo, at the end of the list
    POST /api/settings/silos/change    {key, name?, colour?, words?, runs?, others?}: rename, recolour, or
                                       change its words or who sees it by default; the key never changes
    POST /api/settings/silos/move      {key, by}: up (-1) or down (+1) the list
    POST /api/settings/silos/remove    {key, to?}: delete it; what it holds moves to `to`, which is asked
                                       for whenever it holds anything
    POST /api/settings/silos/rule      {kind, match, silo, label?}: where something comes from decides its
                                       silo; silo "" takes the rule away

Petar, 12 October 2026: "Make a silo setting in settings. This will control how many silos you have and
what they are called." Every query names the signed-in person and their organisation: silos are an
account's own. A change that moves labels (a rule, a deletion) labels Synapse again from its sources, on
a thread of its own (`silos.refill`).
"""
from __future__ import annotations

import asyncio
import logging

from django.http import HttpRequest

from .clock import _signed_in, their_clock
from .common import answer, body_of, only, refuse

log = logging.getLogger("rouh.web.silos")
NO_STORE = {"Cache-Control": "no-store"}
#: How long the page waits on Google for the calendars and shared drives before drawing without them.
GOOGLE_WAIT = 6.0


async def _me(request):
    return await asyncio.to_thread(_signed_in, request)


def _local(me) -> dict:
    """Everything the page draws that Rouh keeps itself."""
    from rouh import silos
    from rouh.synapse import db

    uid, oid = str(me.user_id), str(me.org_id)
    have = silos.of(uid, oid)
    rules = silos.rules(uid, oid)
    projects = []
    if db.value("SELECT to_regclass('public.object') IS NOT NULL"):
        rows = db.rows("SELECT folder, title FROM object WHERE type = 'project' AND folder <> '' "
                       "AND array_length(string_to_array(folder, '/'), 1) <= 2 ORDER BY folder")
        for r in rows:
            folder = str(r["folder"]).strip("/")
            own = next((x["silo"] for x in rules if x["kind"] == "project" and x["match"] == folder.lower()), "")
            key, at = silos.of_project(uid, oid, folder)
            projects.append({"folder": folder, "title": r["title"] or folder, "depth": folder.count("/"),
                             "silo": own, "follows": "" if own else key,
                             "follows_from": "" if own or not at else
                             next((p["title"] for p in rows if str(p["folder"]).strip("/").lower() == at), at)})
    calendars = []
    if db.value("SELECT to_regclass('synapse.calendar_sync') IS NOT NULL"):
        for r in db.rows("SELECT DISTINCT c.calendar_id, c.name FROM synapse.calendar_sync c JOIN synapse.dataset d "
                         "ON d.id = c.dataset_id WHERE d.user_id = %s AND d.org_id = %s ORDER BY c.name",
                         (uid, oid)):
            calendars.append({"id": str(r["calendar_id"]), "name": str(r["name"] or r["calendar_id"])})
    inboxes = []
    if db.value("SELECT to_regclass('synapse.mail_sync') IS NOT NULL"):
        inboxes = [str(r["inbox"]) for r in db.rows(
            "SELECT DISTINCT m.inbox FROM synapse.mail_sync m JOIN synapse.dataset d ON d.id = m.dataset_id "
            "WHERE d.user_id = %s AND d.org_id = %s ORDER BY m.inbox", (uid, oid))]
    return {
        "silos": [dict(s.public(), held=silos.holding(uid, oid, s.key)) for s in have],
        "colours": [{"name": k, "hex": v} for k, v in silos.COLOURS.items()],
        "kinds": silos.RULE_KINDS,
        "every": silos.EVERY,
        "rules": rules,
        "projects": projects,
        "calendars": calendars,
        "inboxes": inboxes,
    }


async def _google(me) -> dict:
    """The calendars and shared drives the account can see, asked of Google as the page is drawn (a copy
    here would be wrong the moment one is shared); nothing, and why, when it cannot be asked."""
    from rouh import runtime
    from rouh.config import config

    if runtime.google_auth is None:
        return {"google": "Google is not connected on this server."}
    try:
        from rouh.google_api import GoogleClients

        services = GoogleClients(runtime.google_auth, config).for_user(me)
    except Exception:  # noqa: BLE001 - drawn without them
        return {"google": "Google is not connected."}

    async def calendars():
        return [{"id": c["id"], "name": c.get("name") or c["id"]} for c in await services.calendar.calendars()]

    async def drives():
        return await services.drive.shared_drives()

    out: dict = {}
    for name, fn in (("google_calendars", calendars), ("drives", drives)):
        try:
            out[name] = await asyncio.wait_for(fn(), GOOGLE_WAIT)
        except Exception as exc:  # noqa: BLE001 - said on the page; the rest is drawn
            out[name + "_said"] = _why(exc)
    return out


def _why(exc) -> str:
    text = str(exc) or type(exc).__name__
    if isinstance(exc, asyncio.TimeoutError):
        return "Google did not answer in time."
    return text[:200]


async def _page(me) -> dict:
    local, google = await asyncio.gather(asyncio.to_thread(_local, me), _google(me))
    # Every calendar there is: the ones Synapse keeps, and the ones Google lists that it does not keep yet.
    seen = {c["id"] for c in local["calendars"]}
    for c in google.pop("google_calendars", []) or []:
        if c["id"] not in seen:
            local["calendars"].append(c)
            seen.add(c["id"])
    local.update(google)
    return local


async def _do(request, work, *, relabel: bool = False):
    from rouh import silos

    me = await _me(request)
    if me is None:
        return refuse("Sign in first.", 401)
    body = body_of(request)
    try:
        said = await asyncio.to_thread(work, str(me.user_id), str(me.org_id), body)
    except silos.Refused as exc:
        return refuse(str(exc), 400, **(await _page(me)))
    except Exception:  # noqa: BLE001 - said, and nothing half made
        log.exception("a silos change failed")
        return refuse("That could not be saved. Try again.", 500, **(await _page(me)))
    if relabel:
        await asyncio.to_thread(silos.refill, str(me.user_id), str(me.org_id))
    return answer({"ok": True, "said": said, **(await _page(me))}, headers=NO_STORE)


@only("GET")
@their_clock
async def page(request: HttpRequest):
    me = await _me(request)
    if me is None:
        return refuse("Sign in first.", 401)
    return answer(await _page(me), headers=NO_STORE)


@only("POST")
@their_clock
async def add(request: HttpRequest):
    from rouh import silos

    def go(uid, oid, body):
        made = silos.add(uid, oid, body.get("name"), str(body.get("colour") or ""))
        return f"Added {made.name}. Nothing is in it until a rule or you put it there."
    return await _do(request, go)


@only("POST")
@their_clock
async def change(request: HttpRequest):
    from rouh import silos

    def go(uid, oid, body):
        was = silos.by_key(uid, oid).get(str(body.get("key") or ""))
        now = silos.change(uid, oid, body.get("key"), name=body.get("name"), colour=body.get("colour"),
                           words=body.get("words"),
                           runs=body.get("runs") if isinstance(body.get("runs"), bool) else None,
                           others=body.get("others") if isinstance(body.get("others"), bool) else None)
        if was is not None and was.name != now.name:
            return f"{was.name} is called {now.name} now; everything in it stays in it."
        return f"Saved {now.name}."
    return await _do(request, go, relabel=True)


@only("POST")
@their_clock
async def move(request: HttpRequest):
    from rouh import silos

    def go(uid, oid, body):
        silos.move(uid, oid, str(body.get("key") or ""), -1 if int(body.get("by") or 0) < 0 else 1)
        return ""
    return await _do(request, go)


@only("POST")
@their_clock
async def remove(request: HttpRequest):
    from rouh import silos

    def go(uid, oid, body):
        key, to = str(body.get("key") or ""), str(body.get("to") or "")
        have = silos.by_key(uid, oid)
        name = have[key].name if key in have else "It"
        got = silos.remove(uid, oid, key, to)
        if got["held"]["total"]:
            return f"Deleted {name}. Everything in it is in {have[to].name} now."
        return f"Deleted {name}. Nothing was in it."
    return await _do(request, go, relabel=True)


@only("POST")
@their_clock
async def rule(request: HttpRequest):
    from rouh import silos

    def go(uid, oid, body):
        got = silos.set_rule(uid, oid, str(body.get("kind") or ""), body.get("match"), str(body.get("silo") or ""),
                             str(body.get("label") or ""))
        what = silos.RULE_KINDS[got["kind"]].lower()
        if not got["silo"]:
            return f"The rule on that {what} is gone; what it labelled is labelled again from the rest."
        target = ("every silo" if got["silo"] == silos.EVERY else silos.said(uid, oid, [got["silo"]]))
        return f"Everything from that {what} is in {target} now."
    return await _do(request, go, relabel=True)
