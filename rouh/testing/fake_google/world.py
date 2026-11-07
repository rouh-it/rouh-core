"""Shared world registration for the Google stand-in."""
from __future__ import annotations

from . import (
    ACCOUNT_EMAIL,
    ACCOUNT_ID,
    ALL_SCOPES,
    CALENDAR_ZONE,
    DOCUMENTS,
    DRIVES,
    FILES,
    FIRST_HISTORY_ID,
    FIRST_MADE_ID,
    INBOX_MESSAGES,
    LABELS,
    MESSAGES,
    _calendars_at_start,
    _dated,
    _events_at_start,
    _owner_permission,
    _read_only_mail,
    _read_only_routes,
    _renumber,
    json,
    time,
)


from dataclasses import dataclass
from typing import Callable


@dataclass
class Context:
    world: dict
    seen: dict
    codes: dict
    reset: Callable
    made_up: Callable
    note: Callable
    drive_named: Callable
    holding_permissions: Callable
    file_named: Callable


def create_context(app):
    seen: dict = {"consent": [], "token": [], "revoke": 0, "api": [], "writes": [],
                  "revoked": [], "read_only_api": [], "read_only_refused": []}
    codes: dict[str, str] = {}
    # Everything a test may have changed, rebuilt on demand so one module's
    # worth of tests do not inherit each other's sends.
    world: dict = {"messages": [], "files": [], "labels": [], "documents": {},
                   "sent": [], "drafts": [], "grant": list(ALL_SCOPES), "next_id": FIRST_MADE_ID,
                   "sessions": {}, "drives": [], "grant_sees_shared_drives": True,
                   "calendars": [], "shared_calendars": {}, "events": {}, "today": None,
                   "token_scopes": [], "history_id": FIRST_HISTORY_ID,
                   "history_floor": FIRST_HISTORY_ID, "history": [], "watch": None,
                   "topics": {}, "pushes": [], "ro_extra": [], "ro_withdrawn": set(),
                   "ro_mail": {}, "ro_scopes": {}, "drive_rules": {}, "ro_history": {},
                   "signed_in_as": {}}

    def reset() -> None:
        world["messages"] = [dict(m) for m in MESSAGES] + _dated(INBOX_MESSAGES)
        world["files"] = [dict(f, permissions=[_owner_permission()]) for f in FILES]
        world["labels"] = [dict(one) for one in LABELS]
        world["documents"] = json.loads(json.dumps(DOCUMENTS))
        # Positions counted the way Docs counts them, as every edit below
        # counts them again. Written by hand they were wrong, and text put at
        # the end of the plan landed after a blank line.
        for one in world["documents"].values():
            _renumber(one)
        world["sent"] = []
        world["drafts"] = []
        world["grant"] = list(ALL_SCOPES)
        world["next_id"] = FIRST_MADE_ID
        world["sessions"] = {}
        world["drives"] = [dict(one) for one in DRIVES]
        world["grant_sees_shared_drives"] = True
        # The calendars count from today on the person's clock, so "what do I
        # have tomorrow" has an answer whichever day this runs.
        from datetime import datetime
        from zoneinfo import ZoneInfo

        world["today"] = datetime.now(ZoneInfo(CALENDAR_ZONE)).date()
        world["calendars"], world["shared_calendars"] = _calendars_at_start()
        world["events"] = _events_at_start(world["today"])
        for one in world["messages"]:
            one["labels"] = (list(one["labels"]) if "labels" in one else ["INBOX"]) + \
                (["UNREAD"] if one["unread"] else [])
        world["history_id"] = FIRST_HISTORY_ID
        world["history_floor"] = FIRST_HISTORY_ID
        world["history"] = []
        world["watch"] = None
        world["topics"] = {}
        world["pushes"] = []
        world["ro_extra"] = []
        world["ro_withdrawn"] = set()
        world["ro_mail"] = _read_only_mail()
        world["ro_history"] = {}
        world["ro_scopes"] = {}
        world["signed_in_as"] = {}
        # What the organisation's Workspace lets this account do with shared
        # drives (`POST /_drive_rules`): make one, and let people from outside
        # example.com into one. Both allowed until a test says otherwise.
        world["drive_rules"] = {"create": True, "outside": True}

    reset()
    _read_only_routes(app, world, seen)

    def made_up(prefix: str) -> str:
        world["next_id"] += 1
        return f"{prefix}-{world['next_id']}"

    def note(what: str, detail: dict) -> None:
        seen["writes"].append({"what": what, "at": time.time(), **detail})

    def drive_named(drive_id: str) -> dict | None:
        """A shared drive by its id, with its members as permissions, as Drive keeps them."""
        found = next((one for one in world["drives"] if one["id"] == drive_id), None)
        if found is not None and "permissions" not in found:
            found["permissions"] = [{"id": "organizer-" + ACCOUNT_ID, "type": "user",
                                     "role": "organizer", "emailAddress": ACCOUNT_EMAIL,
                                     "displayName": "Alex Morgan"}]
        return found

    def holding_permissions(file_id: str) -> dict | None:
        """A file, or a shared drive: both hold their permissions the same way."""
        return file_named(file_id) or drive_named(file_id)

    def file_named(file_id: str) -> dict | None:
        return next((f for f in world["files"] if f["id"] == file_id), None)

    return Context(world, seen, codes, reset, made_up, note, drive_named, holding_permissions, file_named)
