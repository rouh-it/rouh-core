"""Settings for My contact card: the iCloud card whose emails are the person's own.

    GET  /api/settings/my-card               what the card draws
    POST /api/settings/my-card               pick a card: {"contact_id": "<person id>"};
                                             or {"forget": true} for none
    GET  /api/settings/my-card/search?q=     iCloud contacts a few words find
    POST /api/settings/my-card/emails        change the picked card's emails in iCloud:
                                             {"add": [{"address", "label"}], "remove": [...]}

The choice and what it means are `rouh/my_card.py`; this file is only the
route. The emails are written to the real iCloud card the same way
`save_contact` writes them (`apple_contacts.ContactDesk.save`), with the person
as the speaker, so a change here is a change on the phone. Rouh's own
mailbox is refused before anything is sent: it is never the person's.
"""
from __future__ import annotations

import re

from asgiref.sync import sync_to_async
from django.http import HttpRequest

from rouh import my_card

from .apple import TOO_MANY, meter
from .common import answer, body_of, only, refuse, who

#: How many cards a search hands back.
FOUND = 10


def _desk():
    from rouh import runtime

    return runtime.contacts


def _shown(row: dict | None) -> dict | None:
    if row is None:
        return None
    return {"id": row["id"], "name": row.get("name") or "",
            "organisation": row.get("organisation") or "",
            "emails": [{"address": str(one.get("address") or ""),
                        "label": str(one.get("label") or ""),
                        "never": my_card.never_mine(one.get("address"))}
                       for one in (row.get("emails") or ()) if isinstance(one, dict)]}


def _state_now(desk, me) -> dict:
    summary = desk.store.summary(me.user_id, me.org_id) if desk is not None else {
        "connected": False, "needs_new_password": False, "last_sync_at": 0}
    found = my_card.card(me.user_id, me.org_id)
    return {
        "apple": {"on": desk is not None, "connected": summary["connected"],
                  "needs_new_password": summary["needs_new_password"],
                  "synced": bool(summary["last_sync_at"])},
        "account": my_card.account_address(me.user_id),
        "chosen": _shown(found),
        # Picked once, and gone from iCloud since: said, never quietly replaced.
        "missing": found is None and bool(my_card.chosen_uid(me.user_id, me.org_id)),
        "own": my_card.own_addresses(me.user_id, me.org_id),
        # Every address of the person's as one list, the same rows their contact card draws
        # (`rouh/person_addresses.py`): label, where it comes from, silo, and whether it is a
        # connected mailbox.
        "addresses": _addresses(me),
    }


def _addresses(me) -> dict | None:
    import logging

    from rouh import person_addresses
    from rouh.people import People

    try:
        # The card picked here when there is one, so its labels are the ones shown; else their own person.
        found = my_card.card(me.user_id, me.org_id)
        person = (People().person(str(me.user_id), str(me.org_id), found["id"]) if found else None) \
            or People().person(str(me.user_id), str(me.org_id), "me")
        return person_addresses.view(str(me.user_id), str(me.org_id), person) if person is not None else None
    except Exception:  # noqa: BLE001 - the rest of the card still draws
        logging.getLogger("rouh.mycard").exception("the person's addresses could not be listed")
        return None


async def _state(desk, me) -> dict:
    return await sync_to_async(_state_now)(desk, me)


@only("GET", "POST")
async def settings_my_card(request: HttpRequest):
    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("sign in", 401)
    desk = _desk()
    if request.method == "GET":
        return answer(await _state(desk, me))
    body = body_of(request)
    if body.get("forget"):
        await sync_to_async(my_card.forget)(me.user_id, me.org_id)
        return answer({"ok": True, "said": "No card is yours now: only your account's "
                                           "address counts as yours.",
                       **(await _state(desk, me))})
    try:
        row = await sync_to_async(my_card.choose)(me.user_id, me.org_id,
                                                  body.get("contact_id"))
    except ValueError as exc:
        return refuse(str(exc), 400, **(await _state(desk, me)))
    return answer({"ok": True, "said": f"{row.get('name') or 'That card'} is your card now.",
                   **(await _state(desk, me))})


def _search_now(desk, me, query: str) -> list[dict]:
    rows = desk.store.search(me.user_id, me.org_id, query, FOUND)
    return [_shown(row) for row in rows]


@only("GET")
async def search(request: HttpRequest):
    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("sign in", 401)
    desk = _desk()
    if desk is None:
        return refuse("Apple Contacts are switched off on this server.", 503)
    query = str(request.GET.get("q") or "").strip()[:200]
    if not query:
        return answer({"found": []})
    return answer({"found": await sync_to_async(_search_now)(desk, me, query)})


def _cleaned(body: dict) -> tuple[list[dict], list[str]]:
    add: list[dict] = []
    for one in body.get("add") or ():
        if isinstance(one, str):
            one = {"address": one}
        if not isinstance(one, dict):
            continue
        address = str(one.get("address") or "").strip()[:320]
        if address:
            add.append({"address": address, "label": str(one.get("label") or "").strip()[:40]})
    remove = [str(one).strip()[:320] for one in body.get("remove") or ()
              if isinstance(one, str) and one.strip()]
    return add, remove


@only("POST")
async def emails(request: HttpRequest):
    from rouh.apple_contacts import SHOWN_SAVED
    from rouh.tenancy import speaking

    me = await sync_to_async(who)(request)
    if me is None:
        return refuse("sign in", 401)
    desk = _desk()
    if desk is None:
        return refuse("Apple Contacts are switched off on this server.", 503)
    if meter.too_many("my-card:" + me.user_id):
        return refuse(TOO_MANY, 429)
    found = await sync_to_async(my_card.card)(me.user_id, me.org_id)
    if found is None:
        return refuse("Pick your card first.", 409, **(await _state(desk, me)))
    add, remove = _cleaned(body_of(request))
    if not add and not remove:
        return refuse("Nothing to change was given.", 400, **(await _state(desk, me)))
    for one in add:
        why = my_card.refused_because(one["address"])
        if why:
            return refuse(why, 400, **(await _state(desk, me)))
    with speaking(me):
        said = await desk.save({"contact_id": f"c{found['id']}", "add_emails": add,
                                "remove_emails": remove})
    # The words save_contact hands the model, less what only the model needs:
    # the card on its screen, and the id it calls the contact by.
    text = re.sub(r"\s*Id c?[0-9a-f-]+\.", "", str(said.text).replace(SHOWN_SAVED, ""))
    text = " ".join(text.split())
    if said.card is None:
        return refuse(text or "Nothing was changed.", 400, **(await _state(desk, me)))
    return answer({"ok": True, "said": text, **(await _state(desk, me))})
