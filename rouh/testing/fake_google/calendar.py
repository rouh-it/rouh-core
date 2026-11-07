"""Calendar registration for the Google stand-in."""
from __future__ import annotations

from typing import TYPE_CHECKING

from . import (
    ACCOUNT_EMAIL,
    CALENDAR_SCOPE,
    CALENDAR_ZONE,
    JSONResponse,
    Request,
    Response,
    _chris_busy,
    _moment_of,
    _refused,
    json,
)

if TYPE_CHECKING:
    from fastapi import FastAPI


def _calendar_routes(app: FastAPI, world: dict, seen: dict, note, made_up) -> None:
    """Enough of Calendar v3 to answer every calendar tool, reading and writing.

    Strict where it matters: a token whose grant has no calendar scope is
    refused as Google refuses it, a calendar this account may only read will
    not take a write, a calendar shared as free and busy only lists no events,
    and a calendar nobody shared cannot be added. Every write is noted with
    the `sendUpdates` it came with, because whether the guests were emailed is
    a thing a person cares about and a test has to be able to see.
    """
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    def granted() -> JSONResponse | None:
        if CALENDAR_SCOPE not in world["token_scopes"]:
            return _refused("Request had insufficient authentication scopes.", 403,
                            "ACCESS_TOKEN_SCOPE_INSUFFICIENT")
        return None

    def real_id(calendar_id: str) -> str:
        return ACCOUNT_EMAIL if calendar_id == "primary" else calendar_id

    def access(calendar_id: str) -> str:
        for one in world["calendars"]:
            if one["id"] == calendar_id:
                return one["accessRole"]
        shared = world["shared_calendars"].get(calendar_id)
        if shared:
            return shared["accessRole"]
        # Google's public holiday calendars, which anybody may read without adding them: one
        # exists here once a holiday is put on it (`/_calendar_event`, `rouh/public_holidays.py`).
        if calendar_id.endswith("#holiday@group.v.calendar.google.com") and world["events"].get(calendar_id):
            return "reader"
        return ""

    def find(calendar_id: str, event_id: str) -> dict | None:
        return next((one for one in world["events"].get(calendar_id, [])
                     if one["id"] == event_id), None)

    def overlaps(one: dict, begin, end) -> bool:
        return _moment_of(one["start"]) < end and _moment_of(one["end"]) > begin

    def matches(one: dict, text: str) -> bool:
        if not text:
            return True
        words = " ".join([one.get("summary") or "", one.get("description") or "",
                          one.get("location") or ""]
                         + [a.get("email") or "" for a in one.get("attendees") or []]
                         + [a.get("displayName") or "" for a in one.get("attendees") or []])
        return all(word.lower() in words.lower() for word in text.split())

    def unmovable(one: dict) -> dict:
        got = json.loads(json.dumps(one))
        got.setdefault("updated", "2026-01-01T00:00:00.000Z")
        return got

    world.setdefault("sync_tokens", {})

    def stamp(one: dict) -> None:
        """When an event last changed, as Google keeps it (what a sync notices a change by)."""
        world["cal_rev"] = world.get("cal_rev", 0) + 1
        one["updated"] = datetime.now().astimezone().isoformat(timespec="milliseconds") + f"#{world['cal_rev']}"

    def sync_listing(calendar_id: str, q) -> JSONResponse:
        now = {one["id"]: unmovable(one) for one in world["events"].get(calendar_id, [])}
        token = q.get("syncToken") or ""
        if token:
            if world.pop("expire_sync_tokens", False) or token not in world["sync_tokens"]:
                return _refused("Sync token is no longer valid, a full sync is required.", 410, "fullSyncRequired")
            was = world["sync_tokens"][token]
            found = [one for k, one in now.items() if was.get(k) != one]
            found += [{"kind": "calendar#event", "id": k, "status": "cancelled"} for k in was if k not in now]
        else:
            found = [one for one in now.values() if one.get("status") != "cancelled"
                     or q.get("showDeleted") == "true"]
        found.sort(key=lambda one: one["id"])
        limit = int(q.get("maxResults") or 250)
        start = int((q.get("pageToken") or "p0")[1:] or 0)
        page = found[start:start + limit]
        out = {"kind": "calendar#events", "timeZone": CALENDAR_ZONE, "items": page}
        if start + limit < len(found):
            out["nextPageToken"] = f"p{start + limit}"
        else:
            made = f"sync-{made_up('tok')}"
            world["sync_tokens"][made] = now
            out["nextSyncToken"] = made
        return JSONResponse(out)

    @app.get("/calendar/v3/users/me/calendarList")
    async def calendar_list(request: Request):
        seen["api"].append(str(request.url))
        return granted() or JSONResponse(
            {"kind": "calendar#calendarList", "items": world["calendars"]})

    @app.post("/calendar/v3/users/me/calendarList")
    async def calendar_add(request: Request):
        refusal = granted()
        if refusal:
            return refusal
        wanted = str((await request.json()).get("id") or "")
        for one in world["calendars"]:
            if one["id"] == wanted:
                return JSONResponse(one)
        shared = world["shared_calendars"].pop(wanted, None)
        if shared is None:
            return _refused("Not Found", 404, "notFound")
        world["calendars"].append(shared)
        note("calendar added", {"id": wanted})
        return JSONResponse(shared)

    @app.delete("/calendar/v3/users/me/calendarList/{calendar_id}")
    async def calendar_remove(calendar_id: str):
        """Off the list and back to only being shared, so it can be added again."""
        refusal = granted()
        if refusal:
            return refusal
        calendar_id = real_id(calendar_id)
        found = next((one for one in world["calendars"] if one["id"] == calendar_id), None)
        if found is None:
            return _refused("Not Found", 404, "notFound")
        if found.get("primary"):
            return _refused("Cannot remove primary calendar from calendar list", 400, "invalid")
        world["calendars"] = [one for one in world["calendars"] if one["id"] != calendar_id]
        world["shared_calendars"][calendar_id] = found
        note("calendar removed", {"id": calendar_id})
        return Response(status_code=204)

    @app.get("/calendar/v3/calendars/{calendar_id}/events")
    async def list_events(calendar_id: str, request: Request):
        seen["api"].append(str(request.url))
        refusal = granted()
        if refusal:
            return refusal
        calendar_id = real_id(calendar_id)
        role = access(calendar_id)
        if not role:
            return _refused("Not Found", 404, "notFound")
        if role == "freeBusyReader":
            return _refused("Insufficient permissions for this calendar.", 403,
                            "requiredAccessLevel")
        q = request.query_params
        if q.get("syncToken") or (not q.get("timeMin") and not q.get("singleEvents") and not q.get("q")):
            # A sync, as Synapse keeps a calendar (`rouh/synapse/calsync.py`): every event, a page at a
            # time, and a sync token at the end; with that token, what changed since, deleted ones as
            # cancelled. The token is a snapshot of the calendar, so a change is whatever differs from it.
            return sync_listing(calendar_id, q)
        begin = datetime.fromisoformat(q.get("timeMin", "1970-01-01T00:00:00+00:00"))
        end = datetime.fromisoformat(q.get("timeMax", "2999-01-01T00:00:00+00:00"))
        single = q.get("singleEvents") == "true"
        found = [one for one in world["events"].get(calendar_id, [])
                 # Cancelled first: a deleted event may be no more than its id.
                 if one.get("status") != "cancelled"
                 and overlaps(one, begin, end) and matches(one, q.get("q", ""))
                 and (not one.get("recurrence") if single else not one.get("recurringEventId"))]
        found.sort(key=lambda one: _moment_of(one["start"]))
        limit = int(q.get("maxResults") or 250)
        return JSONResponse({"kind": "calendar#events", "timeZone": CALENDAR_ZONE,
                             "items": [unmovable(one) for one in found[:limit]]})

    @app.get("/calendar/v3/calendars/{calendar_id}/events/{event_id}")
    async def one_event(calendar_id: str, event_id: str, request: Request):
        seen["api"].append(str(request.url))
        refusal = granted()
        if refusal:
            return refusal
        found = find(real_id(calendar_id), event_id)
        if found is None or access(real_id(calendar_id)) in ("", "freeBusyReader"):
            return _refused("Not Found", 404, "notFound")
        return JSONResponse(unmovable(found))

    @app.post("/calendar/v3/calendars/{calendar_id}/events")
    async def create_event(calendar_id: str, request: Request):
        refusal = granted()
        if refusal:
            return refusal
        calendar_id = real_id(calendar_id)
        if access(calendar_id) not in ("owner", "writer"):
            return _refused("You need to have writer access to this calendar.", 403,
                            "requiredAccessLevel")
        body = await request.json()
        made = dict(body, id=made_up("ev"), status="confirmed",
                    organizer={"email": calendar_id, "self": True})
        made["htmlLink"] = f"https://www.google.com/calendar/event?eid={made['id']}"
        made.setdefault("iCalUID", f"{made['id']}@google.com")
        if made.get("attendees"):
            made["attendees"] = [dict(one, responseStatus=one.get("responseStatus")
                                      or "needsAction") for one in made["attendees"]]
        conference = (body.get("conferenceData") or {}).get("createRequest")
        if conference and request.query_params.get("conferenceDataVersion") == "1":
            made["hangoutLink"] = f"https://meet.google.com/new-{made['id']}"
            made.pop("conferenceData", None)
        stamp(made)
        world["events"].setdefault(calendar_id, []).append(made)
        note("event made", {"calendar": calendar_id, "id": made["id"],
                            "summary": made.get("summary") or "",
                            "sendUpdates": request.query_params.get("sendUpdates", ""),
                            "body": body})
        return JSONResponse(made)

    @app.post("/calendar/v3/calendars/{calendar_id}/events/import")
    async def import_event(calendar_id: str, request: Request):
        """Google's events.import: a private copy of an invitation, by its iCalUID, which a
        second import of the same UID is refused for (409), as Google refuses it."""
        refusal = granted()
        if refusal:
            return refusal
        calendar_id = real_id(calendar_id)
        if access(calendar_id) not in ("owner", "writer"):
            return _refused("You need to have writer access to this calendar.", 403,
                            "requiredAccessLevel")
        body = await request.json()
        uid = str(body.get("iCalUID") or "")
        if not uid:
            return _refused("Missing iCalUID.", 400, "required")
        if any(one.get("iCalUID") == uid for one in world["events"].get(calendar_id, [])):
            return _refused("The requested identifier already exists.", 409, "duplicate")
        made = dict(body, id=made_up("ev"), status="confirmed")
        made["htmlLink"] = f"https://www.google.com/calendar/event?eid={made['id']}"
        stamp(made)
        world["events"].setdefault(calendar_id, []).append(made)
        note("event imported", {"calendar": calendar_id, "id": made["id"], "iCalUID": uid,
                                "summary": made.get("summary") or "", "body": body})
        return JSONResponse(made)

    @app.patch("/calendar/v3/calendars/{calendar_id}/events/{event_id}")
    async def change_event(calendar_id: str, event_id: str, request: Request):
        refusal = granted()
        if refusal:
            return refusal
        calendar_id = real_id(calendar_id)
        found = find(calendar_id, event_id)
        if found is None:
            return _refused("Not Found", 404, "notFound")
        if access(calendar_id) not in ("owner", "writer"):
            return _refused("You need to have writer access to this calendar.", 403,
                            "requiredAccessLevel")
        body = await request.json()
        was = _moment_of(found["start"])
        conference = (body.get("conferenceData") or {}).get("createRequest")
        if conference and request.query_params.get("conferenceDataVersion") == "1":
            # A Meet link asked for on an event that is already there, as Add Google Meet does.
            body = {k: v for k, v in body.items() if k != "conferenceData"}
            found["hangoutLink"] = f"https://meet.google.com/new-{event_id}"
        for key, value in body.items():
            if key in ("start", "end") and isinstance(value, dict):
                # Objects are merged and a null clears, as Google's PATCH does.
                merged = dict(found.get(key) or {})
                for part, said in value.items():
                    if said is None:
                        merged.pop(part, None)
                    else:
                        merged[part] = said
                found[key] = merged
            elif value is None:
                found.pop(key, None)
            else:
                found[key] = value
        if found.get("recurrence") and "start" in body:
            # The series was moved: every occurrence moves by as much, on the
            # wall clock.
            shift = _moment_of(found["start"]) - was
            zone = ZoneInfo(CALENDAR_ZONE)
            for one in world["events"][calendar_id]:
                if one.get("recurringEventId") == event_id:
                    for key in ("start", "end"):
                        if one[key].get("dateTime"):
                            wall = datetime.fromisoformat(one[key]["dateTime"]).astimezone(zone)
                            moved = (wall.replace(tzinfo=None) + shift).replace(tzinfo=zone)
                            one[key] = {"dateTime": moved.isoformat(timespec="seconds"),
                                        "timeZone": CALENDAR_ZONE}
        stamp(found)
        note("event changed", {"calendar": calendar_id, "id": event_id, "body": body,
                               "sendUpdates": request.query_params.get("sendUpdates", "")})
        return JSONResponse(unmovable(found))

    @app.post("/calendar/v3/calendars/{calendar_id}/events/{event_id}/move")
    async def move_event(calendar_id: str, event_id: str, request: Request):
        refusal = granted()
        if refusal:
            return refusal
        calendar_id = real_id(calendar_id)
        destination = real_id(request.query_params.get("destination", ""))
        found = find(calendar_id, event_id)
        if found is None:
            return _refused("Not Found", 404, "notFound")
        if access(destination) not in ("owner", "writer"):
            return _refused("You need to have writer access to this calendar.", 403,
                            "requiredAccessLevel")
        world["events"][calendar_id].remove(found)
        stamp(found)
        world["events"].setdefault(destination, []).append(found)
        note("event moved", {"from": calendar_id, "to": destination, "id": event_id})
        return JSONResponse(unmovable(found))

    @app.delete("/calendar/v3/calendars/{calendar_id}/events/{event_id}")
    async def delete_event(calendar_id: str, event_id: str, request: Request):
        refusal = granted()
        if refusal:
            return refusal
        calendar_id = real_id(calendar_id)
        found = find(calendar_id, event_id)
        if found is None:
            return _refused("Not Found", 404, "notFound")
        if access(calendar_id) not in ("owner", "writer"):
            return _refused("You need to have writer access to this calendar.", 403,
                            "requiredAccessLevel")
        world["events"][calendar_id] = [
            one for one in world["events"][calendar_id]
            if one["id"] != event_id and one.get("recurringEventId") != event_id]
        note("event deleted", {"calendar": calendar_id, "id": event_id,
                               "summary": found.get("summary") or "",
                               "sendUpdates": request.query_params.get("sendUpdates", "")})
        return Response(status_code=204)

    # --- calendars themselves, and who they are shared with ------------------

    world.setdefault("acl", {})

    def rules_of(calendar_id: str) -> list[dict]:
        """A calendar's sharing, as Google keeps it: the calendar's own entry for
        itself first, then whoever made it, both as owner."""
        if calendar_id not in world["acl"]:
            maker = next((one.get("dataOwner") for one in world["calendars"]
                          if one["id"] == calendar_id), "") or ACCOUNT_EMAIL
            world["acl"][calendar_id] = [
                {"kind": "calendar#aclRule", "id": f"user:{calendar_id}", "role": "owner",
                 "scope": {"type": "user", "value": calendar_id}},
                {"kind": "calendar#aclRule", "id": f"user:{maker}", "role": "owner",
                 "scope": {"type": "user", "value": maker}}]
        return world["acl"][calendar_id]

    def manages(calendar_id: str) -> JSONResponse | None:
        if not access(calendar_id):
            return _refused("Not Found", 404, "notFound")
        if access(calendar_id) != "owner":
            return _refused("You need to have owner access to this calendar.", 403,
                            "requiredAccessLevel")
        return None

    @app.post("/calendar/v3/calendars")
    async def make_calendar(request: Request):
        refusal = granted()
        if refusal:
            return refusal
        body = await request.json()
        if not str(body.get("summary") or "").strip():
            return _refused("Missing title.", 400, "required")
        made = {"kind": "calendar#calendar",
                "id": f"c_{made_up('cal')}@group.calendar.google.com",
                "summary": body["summary"], "description": body.get("description") or "",
                "timeZone": body.get("timeZone") or "UTC", "dataOwner": ACCOUNT_EMAIL}
        world["calendars"].append(dict(made, kind="calendar#calendarListEntry",
                                       accessRole="owner"))
        note("calendar made", {"id": made["id"], "summary": made["summary"],
                               "timeZone": made["timeZone"]})
        return JSONResponse(made)

    @app.get("/calendar/v3/calendars/{calendar_id}")
    async def one_calendar(calendar_id: str, request: Request):
        seen["api"].append(str(request.url))
        refusal = granted()
        if refusal:
            return refusal
        calendar_id = real_id(calendar_id)
        found = next((one for one in world["calendars"] if one["id"] == calendar_id),
                     None) or world["shared_calendars"].get(calendar_id)
        if found is None:
            return _refused("Not Found", 404, "notFound")
        out = {"kind": "calendar#calendar", "id": found["id"],
               "summary": found.get("summary") or "", "timeZone": found.get("timeZone")}
        if found.get("dataOwner"):
            out["dataOwner"] = found["dataOwner"]
        return JSONResponse(out)

    @app.get("/calendar/v3/users/me/calendarList/{calendar_id}")
    async def one_on_the_list(calendar_id: str, request: Request):
        seen["api"].append(str(request.url))
        refusal = granted()
        if refusal:
            return refusal
        found = next((one for one in world["calendars"]
                      if one["id"] == real_id(calendar_id)), None)
        if found is None:
            return _refused("Not Found", 404, "notFound")
        return JSONResponse(found)

    @app.delete("/calendar/v3/calendars/{calendar_id}")
    async def delete_calendar(calendar_id: str):
        refusal = granted() or manages(real_id(calendar_id))
        if refusal:
            return refusal
        world["calendars"] = [one for one in world["calendars"] if one["id"] != calendar_id]
        world["acl"].pop(calendar_id, None)
        world["events"].pop(calendar_id, None)
        note("calendar deleted", {"id": calendar_id})
        return Response(status_code=204)

    @app.get("/calendar/v3/calendars/{calendar_id}/acl")
    async def acl_list(calendar_id: str, request: Request):
        seen["api"].append(str(request.url))
        calendar_id = real_id(calendar_id)
        refusal = granted() or manages(calendar_id)
        if refusal:
            return refusal
        return JSONResponse({"kind": "calendar#acl", "items": rules_of(calendar_id)})

    @app.post("/calendar/v3/calendars/{calendar_id}/acl")
    async def acl_insert(calendar_id: str, request: Request):
        calendar_id = real_id(calendar_id)
        refusal = granted() or manages(calendar_id)
        if refusal:
            return refusal
        body = await request.json()
        scope = body.get("scope") or {}
        kind, value = scope.get("type") or "", str(scope.get("value") or "")
        if body.get("role") not in ("none", "freeBusyReader", "reader", "writer", "owner"):
            return _refused("Invalid role.", 400, "invalid")
        rule_id = "default" if kind == "default" else f"{kind}:{value}"
        rules = [one for one in rules_of(calendar_id) if one["id"] != rule_id]
        made = {"kind": "calendar#aclRule", "id": rule_id, "role": body["role"],
                "scope": {"type": kind, **({"value": value} if value else {})}}
        world["acl"][calendar_id] = rules + [made]
        note("calendar shared", {"calendar": calendar_id, "scope": made["scope"],
                                 "role": made["role"],
                                 "sendNotifications": request.query_params.get(
                                     "sendNotifications", "")})
        return JSONResponse(made)

    @app.patch("/calendar/v3/calendars/{calendar_id}/acl/{rule_id}")
    async def acl_patch(calendar_id: str, rule_id: str, request: Request):
        calendar_id = real_id(calendar_id)
        refusal = granted() or manages(calendar_id)
        if refusal:
            return refusal
        found = next((one for one in rules_of(calendar_id) if one["id"] == rule_id), None)
        if found is None:
            return _refused("Not Found", 404, "notFound")
        found["role"] = (await request.json()).get("role") or found["role"]
        note("calendar sharing changed", {"calendar": calendar_id, "rule": rule_id,
                                          "role": found["role"],
                                          "sendNotifications": request.query_params.get(
                                              "sendNotifications", "")})
        return JSONResponse(found)

    @app.delete("/calendar/v3/calendars/{calendar_id}/acl/{rule_id}")
    async def acl_delete(calendar_id: str, rule_id: str):
        calendar_id = real_id(calendar_id)
        refusal = granted() or manages(calendar_id)
        if refusal:
            return refusal
        rules = rules_of(calendar_id)
        if not any(one["id"] == rule_id for one in rules):
            return _refused("Not Found", 404, "notFound")
        world["acl"][calendar_id] = [one for one in rules if one["id"] != rule_id]
        note("calendar unshared", {"calendar": calendar_id, "rule": rule_id})
        return Response(status_code=204)

    @app.post("/calendar/v3/freeBusy")
    async def free_busy(request: Request):
        refusal = granted()
        if refusal:
            return refusal
        body = await request.json()
        answered = {}
        for item in body.get("items") or []:
            calendar_id = item.get("id") or ""
            known = real_id(calendar_id)
            if calendar_id != "chris@harbor.test" and known in world["events"]:
                # A colleague's calendar the world holds, or the account's own: its busy events,
                # and nothing else about them, as Google's free/busy says.
                begin = datetime.fromisoformat(body.get("timeMin") or "1970-01-01T00:00:00+00:00")
                end = datetime.fromisoformat(body.get("timeMax") or "2999-01-01T00:00:00+00:00")
                busy = [{"start": one["start"].get("dateTime"), "end": one["end"].get("dateTime")}
                        for one in world["events"].get(known, [])
                        if one.get("status") != "cancelled" and one.get("transparency") != "transparent"
                        and (one.get("start") or {}).get("dateTime") and overlaps(one, begin, end)]
                answered[calendar_id] = {"busy": sorted(busy, key=lambda b: b["start"])}
                continue
            if calendar_id != "chris@harbor.test":
                answered[calendar_id] = {"errors": [{"domain": "global", "reason": "notFound"}]}
                continue
            zone = ZoneInfo(CALENDAR_ZONE)
            busy = []
            for days, start, end in _chris_busy(world["today"]):
                day = world["today"] + timedelta(days=days)
                busy.append({
                    "start": datetime(day.year, day.month, day.day, start, tzinfo=zone)
                    .isoformat(timespec="seconds"),
                    "end": datetime(day.year, day.month, day.day, end, tzinfo=zone)
                    .isoformat(timespec="seconds")})
            answered[calendar_id] = {"busy": busy}
        return JSONResponse({"kind": "calendar#freeBusy", "calendars": answered})
