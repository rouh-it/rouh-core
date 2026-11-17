"""Relationships between contacts, on the contact card (`rouh/relationships.py`, `static/personrelations.js`).

    GET  /api/people/<person id>/relationships            the contact's links and the types to pick from
    POST /api/people/<person id>/relationships            {"action": "add", "other", "type", "other_type"},
                                                          {"action": "change", "id", "type", "other_type"},
                                                          {"action": "remove", "id"}: answers the links as they now read
    GET  /api/people/<person id>/relationships/find?q=    contacts to link to, by name or company

`<person id>` is a contact's id in the person's Synapse Master, or "me" for the person themselves. Only ever
the signed-in person's own contacts, by both their ids.
"""
from __future__ import annotations

import asyncio
import re

from django.http import HttpRequest

from .common import answer, body_of, only, refuse, who

#: A person's id in Synapse, or the person themselves.
_ID = re.compile(r"^(?:me|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$")


def _now(me, person_id: str) -> dict:
    from rouh import relationships

    uid, oid = str(me.user_id), str(me.org_id)
    return relationships.view(uid, oid, relationships.end(uid, oid, person_id))


def _do(me, person_id: str, body: dict) -> dict:
    from rouh import relationships

    uid, oid = str(me.user_id), str(me.org_id)
    action = str(body.get("action") or "")
    if action == "add":
        relationships.add(uid, oid, person_id, body.get("other"), body.get("type"), body.get("other_type"),
                          by="card")
    elif action == "change":
        relationships.change(uid, oid, body.get("id"), person_id, body.get("type"), body.get("other_type"))
    elif action == "remove":
        relationships.remove(uid, oid, body.get("id"))
    else:
        raise ValueError("Say add, change or remove.")
    return _now(me, person_id)


@only("GET", "POST")
async def relations(request: HttpRequest, person_id: str):
    me = await asyncio.to_thread(who, request)
    if me is None:
        return refuse("Sign in first.", 401)
    if not _ID.match(person_id or ""):
        return refuse("not found", 404)
    try:
        if request.method == "POST":
            got = await asyncio.to_thread(_do, me, person_id, body_of(request))
        else:
            got = await asyncio.to_thread(_now, me, person_id)
    except ValueError as exc:
        return refuse(str(exc), 400)
    return answer({"ok": True, **got}, headers={"Cache-Control": "no-store"})


@only("GET")
async def find(request: HttpRequest, person_id: str):
    from rouh import relationships

    me = await asyncio.to_thread(who, request)
    if me is None:
        return refuse("Sign in first.", 401)
    if not _ID.match(person_id or ""):
        return refuse("not found", 404)
    query = str(request.GET.get("q") or "")[:80]
    got = await asyncio.to_thread(relationships.find, str(me.user_id), str(me.org_id), query, skip=person_id)
    return answer({"ok": True, "people": got}, headers={"Cache-Control": "no-store"})
