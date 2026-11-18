"""Files they can open: a contact's card in the chat shows which of ‹his› Drive files that person can
open, and takes them off one file with one press.

Built by the nightly feature run, night 47 of the ledger (18 November 2026, task 94).
When a contractor's work ends, a client moves on or a colleague leaves, the question is "what of mine
can they still open?". Since night 46 Rouh answers it when asked in words (`open_files` with who) and
takes them off when asked (`take_off_files`), but only by an email address said out loud, and only if
‹he› remembers to ask; a contact's card, where ‹he› is already looking at that person, had no way to it.

So, while its switch is on, a contact card that shows a saved contact with an email address marks
itself `files` (`mark`), and the page draws **Files they can open** under it (`contactFiles` in
`cards.js`). Pressing it reads ‹his› own files that anybody besides ‹him› can open (`Drive.owned_and_shared`,
newest first, read only) and lists those whose sharing names one of the contact's addresses: each
file's name (a link to it), what they can do, and when their access ends, if it does. Beside each,
**Take off** takes that person's own access off that file alone (`Drive.remove_permission`), with
nothing sent to anybody; the owner, the link and their company's access are left. Nothing is read
before the press, and nothing is kept.

No model is asked.

**Whose.** The person's own contacts and Google connection, by `org_id` and `user_id`.

**Its switch** is `their_files` (`rouh/switches.py`): off, the card has no Files they can open and both
addresses say it is switched off.
"""
from __future__ import annotations

SWITCH = "their_files"
TITLE = "Files they can open: a contact's card shows which of your files they can open, with Take off"

#: The most of ‹his› shared files read for one press.
MOST = 1000
#: The most listed on the card.
SHOWN = 40

VERB = {"reader": "can view", "commenter": "can comment", "writer": "can edit",
        "fileOrganizer": "can organise", "organizer": "can manage"}


def on(who=None) -> bool:
    from . import switches

    return switches.on(SWITCH, getattr(who, "org_id", None) or None)


def _emails(block: dict) -> bool:
    if block.get("addresses"):
        return True
    return any(str(r.get("kind") or "") == "email" or "@" in str(r.get("value") or "")
               for r in block.get("rows") or [] if isinstance(r, dict))


def mark(block: dict, person=None, who=None) -> dict:
    """The contact block, marked for Files they can open when the switch is on, it is a saved contact
    and it has an email address."""
    if block.get("state") in ("unsaved", "declined") or not block.get("contact"):
        return block
    if getattr(person, "is_me", False):
        return block
    if not _emails(block):
        return block
    if on(who):
        block["files"] = True
    return block


def addresses(who, contact_id: str) -> tuple[str, list[str]] | None:
    """(their name, every address of theirs) for the person's own contact, or None. Synchronous."""
    from .synapse.sources import contacts

    row = contacts.person_by_id(str(who.user_id), str(who.org_id), contact_id)
    if row is None:
        return None
    meta = row.get("meta") or {}
    found: list[str] = []
    card = contacts.card_of(row) or {}
    for one in list(card.get("emails") or []) + list(meta.get("emails") or []):
        value = one.get("address") or one.get("value") if isinstance(one, dict) else one
        value = str(value or "").strip().lower()
        if "@" in value and value not in found:
            found.append(value)
    try:
        from .synapse import db, people

        ds = db.row("SELECT * FROM synapse.dataset WHERE id = %s::uuid", (str(row["dataset_id"]),))
        if ds is not None:
            for x in people.identities(people.home_id(ds), str(row["id"])):
                value = str(x.get("value") or "").strip().lower()
                if x.get("type") == "email" and "@" in value and value not in found:
                    found.append(value)
    except Exception:  # noqa: BLE001 - the card's own addresses still stand
        pass
    return str(meta.get("name") or row.get("title") or ""), found


def theirs(permission: dict, wanted: set[str]) -> bool:
    """One of their own permissions: a person or group by an address of theirs, never the owner."""
    if permission.get("role") == "owner" or permission.get("kind") not in ("user", "group"):
        return False
    return str(permission.get("email") or "").lower() in wanted


def listed(files: list[dict], wanted: set[str], zone) -> list[dict]:
    """Their files, as the card lists them: id, name, link, kind, what they can do and until when."""
    from . import share_until

    out: list[dict] = []
    for one in files:
        held = [p for p in one.get("permissions") or [] if theirs(p, wanted)]
        if not held:
            continue
        best = max(held, key=lambda p: ("reader", "commenter", "writer", "fileOrganizer", "organizer").index(p["role"])
                   if p.get("role") in VERB else -1)
        until = best.get("until") or ""
        out.append({"id": one.get("id") or "", "name": one.get("name") or "(no name)",
                    "link": one.get("link") or "", "type": one.get("type") or "",
                    "can": VERB.get(best.get("role") or "", "can open"),
                    "until": share_until.day_said(until, zone) if until else "",
                    "as": str(best.get("email") or "")})
    return out


async def files_of(who, contact_id: str, services) -> dict:
    """What Files they can open shows: {name, addresses, files, more} or {error}."""
    import asyncio

    from asgiref.sync import sync_to_async

    from . import clock, evolution

    got = await sync_to_async(addresses)(who, contact_id)
    if got is None:
        return {"error": "That is not one of your contacts."}
    name, found = got
    if not found:
        return {"error": f"{name or 'They'} have no email address on their contact, so no file can name them."}
    if services is None:
        return {"error": "Google is not connected, so your files could not be read."}
    shared = await services.drive.owned_and_shared(MOST)
    zone = await asyncio.to_thread(clock.zone_of, who)
    files = listed(shared, set(found), zone)
    await sync_to_async(evolution.used)(SWITCH, "listed", who=who, detail=f"{len(files)} file(s) they can open")
    return {"name": name, "addresses": found, "files": files[:SHOWN], "more": max(0, len(files) - SHOWN)}


async def take_off(who, contact_id: str, file_id: str, services) -> dict:
    """Take off, pressed: their own access to one file taken away. {said} or {error}."""
    from asgiref.sync import sync_to_async

    from . import evolution

    got = await sync_to_async(addresses)(who, contact_id)
    if got is None:
        return {"error": "That is not one of your contacts."}
    name, found = got
    if services is None:
        return {"error": "Google is not connected, so nobody was taken off."}
    drive = services.drive
    about = await drive.metadata(file_id)
    held = [p for p in await drive.permissions(file_id) if theirs(p, set(found))]
    if not held:
        return {"said": f"{name or 'They'} could not open “{about.get('name') or 'it'}” already.", "gone": True}
    for one in held:
        await drive.remove_permission(file_id, one["id"])
    await sync_to_async(evolution.used)(SWITCH, "taken_off", who=who, detail="taken off one file from their card")
    return {"said": f"{name or 'They'} can no longer open “{about.get('name') or 'it'}”. Google told nobody.",
            "gone": True}


__all__ = ["MOST", "SHOWN", "SWITCH", "TITLE", "VERB", "addresses", "files_of", "listed", "mark", "on",
           "take_off", "theirs"]
