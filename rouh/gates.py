"""Permission gates: the tools that must get the owner's yes before they run.

Petar, 15 November 2026: "setup an interface in anatomy to know there are permission gates and
adjust them but I don't want to deal with them myself as of now. rouh is different and more risky
by default."

The gate itself is `rouh/permissions.py`, and the place it stops a call is `ToolRegistry.call` in
`rouh/tools.py`: a gated tool emits its question, holds the turn until the person answers, and is
refused (never quietly run) when nobody does. This file is where the list of gated tools comes
from, and it is enforced by that code, not by anything Rouh is told:

- **The owner's own choices**, one `PermissionGate` row per tool switched to "ask me first" on
  Anatomy, Behaviour, Permission gates (`rouh/web/gates.py`). None by default.
- **The server's**, `ROUH_CONFIRM_TOOLS` in the environment (`config.confirm_tools`), which the page
  shows as locked on: only the machine's settings can turn those off.

The list is read for every call (`live`): from a copy at most `FRESH` seconds old, read again in a
thread when it is older, and dropped the moment the page saves, so a switch takes effect on the next
call without a restart. Whose list it is: the organisation of the install's owner, the person the
gate's questions go to (`hooks.owner`, `telegram.phone_owner`), as the Decisions list is theirs.

`candidates` marks the tools where a mistake costs money or cannot be taken back: the ones that pay,
order, send, publish, share or delete. They are only marked; nothing is switched on by default.
"""
from __future__ import annotations

import asyncio
import logging
import threading
import time

from . import permissions

log = logging.getLogger("rouh.gates")

#: How old the copy of the list may be before a call reads it again, in seconds.
FRESH = 5.0


class Hooks:
    #: () -> the install's owner (an identity with `org_id`), or None. Set by the runtime.
    owner = None


hooks = Hooks()

_lock = threading.Lock()
#: org id -> (read at, the names)
_copy: dict[str, tuple[float, frozenset[str]]] = {}
#: (read at, the owner's organisation), so a call does not ask whose Rouh this is every time.
_org: list = [0.0, ""]


#: The tools where a mistake is expensive or cannot be undone, by what they do, marked as
#: candidates on the page. Only marked: none is gated unless the person switches it on. A new tool
#: that pays, sends, publishes, shares or deletes is added here.
NAMED = {
    "payments": "money", "place_order": "money", "stripe": "money", "shipping": "money",
    "send_mail": "sending", "forward_mail": "sending", "forward_thread": "sending",
    "send_telegram": "sending", "slack_send": "sending", "reply_to_doc_comment": "sending",
    "publish_task": "publishing", "comment_on_doc": "publishing",
    "share_granted_page": "sharing",
    "share_drive_file": "sharing", "share_calendar": "sharing", "share_with_person": "sharing",
    "add_shared_drive_members": "sharing", "add_shared_calendar": "sharing",
    "delete_contact": "deleting", "delete_calendar_event": "deleting",
    "manage_drive_file": "deleting", "forget": "deleting", "synapse_delete": "deleting",
    "update_rouh": "server", "cloudflare": "server",
}

#: What each kind of candidate is said as, on its row.
KIND_WORDS = {
    "money": "Spends money",
    "sending": "Sends in your name",
    "publishing": "Publishes",
    "sharing": "Shares with others",
    "deleting": "Can delete for good",
    "server": "Changes Rouh or its server",
}


def candidate(name: str) -> str:
    """The kind of mistake that makes a tool a candidate, or "" for one that is not.

    Only the tools named in `NAMED`. A guess from the tool's name alone (the way the approval
    queue judges a call by its name and its arguments) marked read_mail as sending and read_card
    as spending money, so it is not used here: a candidate is a tool somebody named."""
    return NAMED.get(name, "")


def from_server(cfg) -> frozenset[str]:
    """The tools the machine's own settings gate (`ROUH_CONFIRM_TOOLS`)."""
    return permissions.gated(cfg)


def chosen(org_id: str) -> frozenset[str]:
    """The tools the organisation switched to "ask me first" itself, from the database."""
    from .models import PermissionGate

    if not org_id:
        return frozenset()
    return frozenset(PermissionGate.objects.filter(org_id=str(org_id))
                     .values_list("tool", flat=True))


def put(org_id: str, tool: str, on: bool, by: str = "") -> frozenset[str]:
    """Switch one tool's gate on or off for the organisation. The organisation's list after it."""
    from .models import PermissionGate

    org_id, tool = str(org_id or ""), str(tool or "").strip()
    if not org_id or not tool:
        raise ValueError("Which tool, for which organisation.")
    if on:
        PermissionGate.objects.bulk_create(
            [PermissionGate(org_id=org_id, tool=tool, by=by[:200], updated_at=time.time())],
            update_conflicts=True, unique_fields=["org_id", "tool"],
            update_fields=["by", "updated_at"])
    else:
        PermissionGate.objects.filter(org_id=org_id, tool=tool).delete()
    log.info("permission gate for %s %s by %s", tool, "on" if on else "off", by or "?")
    forget(org_id)
    return chosen(org_id)


def forget(org_id: str = "") -> None:
    """Drop the copy, so the next call reads the list again."""
    with _lock:
        if org_id:
            _copy.pop(str(org_id), None)
        else:
            _copy.clear()
        _org[:] = [0.0, ""]


def _owner_org() -> str:
    if hooks.owner is None:
        return ""
    try:
        who = hooks.owner()
    except Exception:  # noqa: BLE001 - no owner read is no list of the owner's
        log.exception("gates: whose Rouh this is could not be read")
        return ""
    return str(getattr(who, "org_id", "") or "") if who is not None else ""


def _read(org_id: str) -> frozenset[str]:
    from django.db import close_old_connections

    try:
        return chosen(org_id)
    finally:
        close_old_connections()


async def live(server: frozenset[str]) -> frozenset[str]:
    """Every tool gated for this call: the server's and the owner's own.

    Never raises. When the owner's list cannot be read, the copy last read stands, and with none
    the server's alone, which is what the gate was before the page existed."""
    with _lock:
        at, org = _org
    if not org or time.time() - at >= FRESH:
        org = await asyncio.to_thread(_owner_org)
        with _lock:
            _org[:] = [time.time(), org]
    if not org:
        return server
    with _lock:
        got = _copy.get(org)
    if got is not None and time.time() - got[0] < FRESH:
        return server | got[1]
    try:
        names = await asyncio.to_thread(_read, org)
    except Exception:  # noqa: BLE001 - see above
        log.exception("gates: the gated tools could not be read")
        return server | (got[1] if got else frozenset())
    with _lock:
        _copy[org] = (time.time(), names)
    return server | names


def page(org_id: str, cfg, entries) -> dict:
    """What Anatomy, Behaviour, Permission gates shows.

    `entries` are the registry's tools as `toolsearch.Tool`s (`ToolRegistry.all_entries`). Every
    tool is listed under its area, with whether it is gated, whether the server locks it on, and
    whether it is a candidate. Counts are worked out here, once, so every line on the page agrees."""
    from . import toolsearch

    server = from_server(cfg)
    own = chosen(org_id)
    areas = {key: {"id": key, "name": name, "tools": []} for key, name, _ in toolsearch.AREAS}
    seen: set[str] = set()
    for tool in entries:
        name = getattr(tool, "name", "") or ""
        if not name or name in seen or name in toolsearch.SEARCH_NAMES:
            continue
        seen.add(name)
        kind = candidate(name)
        area = getattr(tool, "area", "") or "other"
        areas.setdefault(area, {"id": area, "name": area.title(), "tools": []})
        areas[area]["tools"].append({
            "name": name, "brief": getattr(tool, "brief", "") or "",
            "on": name in own or name in server, "locked": name in server,
            "candidate": bool(kind), "kind": kind, "kind_words": KIND_WORDS.get(kind, ""),
        })
    # A gate named for a tool this Rouh does not have (a typo, a tool since removed) is still
    # shown, so it can be seen and turned off rather than sitting there unseen.
    for name in sorted((own | server) - seen):
        areas.setdefault("other", {"id": "other", "name": "Other", "tools": []})
        areas["other"]["tools"].append({
            "name": name, "brief": "Not a tool this Rouh has now.", "on": True,
            "locked": name in server, "candidate": False, "kind": "", "kind_words": "",
            "missing": True})
    groups = []
    for g in areas.values():
        if not g["tools"]:
            continue
        g["tools"].sort(key=lambda t: (not t["candidate"], t["name"]))
        g["candidates"] = sum(1 for t in g["tools"] if t["candidate"])
        g["gated"] = sum(1 for t in g["tools"] if t["on"])
        groups.append(g)
    tools = [t for g in groups for t in g["tools"]]
    return {
        "groups": groups,
        "total": len(tools),
        "gated": sum(1 for t in tools if t["on"]),
        "locked": sum(1 for t in tools if t["locked"]),
        "candidates": sum(1 for t in tools if t["candidate"]),
        "candidates_gated": sum(1 for t in tools if t["candidate"] and t["on"]),
        "timeout": float(getattr(cfg, "confirm_timeout", permissions.TIMEOUT)),
        "kinds": KIND_WORDS,
    }
