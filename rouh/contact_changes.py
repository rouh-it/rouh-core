"""What changed on a contact: a contact's earlier versions read back as what changed and when, and the
contact put back as it was before one of those changes, on the person's word.

Built by the nightly feature run, night 41 of the ledger (12 November 2026, task 94).
A contact changes from several sides now: ‹his› phone, iCloud on another device, and Rouh, where a
notice's one press adds a number from a signature (night 39), an address (night 40) or a company
(night 41). When a contact reads wrong, ‹he› cannot tell when it changed or what it said before, and
Rouh, asked, could not say either: every earlier version of a contact's person is kept in Synapse
Master (`synapse.item_version`, written by `synapse/sources/contacts.write`), and nothing read them back.

So, while its switch is on, the tool `contact_changes` takes a contact (by `contact_id` or `name`),
reads its kept versions and the card as it is now, and says each change, newest first: when, and
what went from what to what (the name, the company, the birthday, each phone number and email address
added or taken off, and that the note changed, never the note's words). Asked to put it back,
`put_back_before` names one of those changes: the tool says what putting it back would change, and
only with `confirmed`, which the model passes after the person said yes, writes it to iCloud through
the contacts desk's own save (`ContactDesk.save`), the same write `save_contact` makes. The note is
never put back.

No model is asked. It reads only Synapse Master and writes only through the desk.

**Whose.** The person's own Synapse Master, by `org_id` and `user_id`.

**Its switch** is `contact_changes` (`rouh/switches.py`): off, the tool says it is switched off.
"""
from __future__ import annotations

import logging
from datetime import datetime

log = logging.getLogger("rouh.contact_changes")

SWITCH = "contact_changes"
TITLE = "What changed on a contact: its earlier versions read back, and put back as it was"

#: How many changes are said at most.
MOST = 12

DESCRIPTION = (
    "Says what changed on one of the person's contacts and when, from the earlier versions Rouh keeps of "
    "every contact: the name, company, birthday, each phone number and email address added or taken off, "
    "newest first, numbered. For 'what changed on Dana's contact', 'when did her number change', 'what "
    "was his company before', 'who put this number on'. Give contact_id (from search_contacts) or name. "
    "To put the contact back as it was before one of the changes, give put_back_before with that "
    "change's number: it first says exactly what that would change and writes nothing; tell the person, "
    "and only after they say yes call it again with the same put_back_before and confirmed true, which "
    "writes it to iCloud. The note is never put back.")

SCHEMA = {"type": "object", "properties": {
    "contact_id": {"type": "string", "description": "The contact's id, as search_contacts gave it."},
    "name": {"type": "string", "description": "Or the contact's name, when there is no id."},
    "put_back_before": {"type": "integer",
                        "description": "Put the contact back as it was before this change, by the number "
                                       "this tool gave it."},
    "confirmed": {"type": "boolean",
                  "description": "Only after the person said yes to putting it back: writes it to iCloud."}}}


def on(who) -> bool:
    from . import switches

    if who is None:
        return False
    return switches.on(SWITCH, getattr(who, "org_id", None) or None)


def state_of(meta: dict, title: str = "") -> dict | None:
    """The fields of one version of a contact, or None when that version was no contact."""
    meta = meta or {}
    ic = meta.get("icloud")
    if not isinstance(ic, dict):
        return None
    phones = {}
    for p in ic.get("phones") or []:
        number = str(p.get("number") if isinstance(p, dict) else p).strip()
        if number:
            phones[number] = str(p.get("label") or "") if isinstance(p, dict) else ""
    emails = {}
    for e in ic.get("emails") or []:
        address = str(e.get("address") if isinstance(e, dict) else e).strip().lower()
        if address:
            emails[address] = str(e.get("label") or "") if isinstance(e, dict) else ""
    return {"name": str(meta.get("name") or title or ""), "organisation": str(meta.get("organisation") or ""),
            "birthday": str(meta.get("birthday") or ""), "note": str(meta.get("note") or ""),
            "phones": phones, "emails": emails}


def _same_phone(a: str, b: str) -> bool:
    from .sig_phones import same

    return same(a, b)


def differences(before: dict, after: dict) -> list[str]:
    """What went from `before` to `after`, in words."""
    out = []
    for key, word in (("name", "name"), ("organisation", "company"), ("birthday", "birthday")):
        a, b = before.get(key) or "", after.get(key) or ""
        if a != b:
            if a and b:
                out.append(f"{word} {a} → {b}")
            elif b:
                out.append(f"{word} {b} added")
            else:
                out.append(f"{word} {a} taken off")
    for number, label in after["phones"].items():
        if not any(_same_phone(number, n) for n in before["phones"]):
            out.append(f"phone {number}{' (' + label + ')' if label else ''} added")
    for number, label in before["phones"].items():
        if not any(_same_phone(number, n) for n in after["phones"]):
            out.append(f"phone {number}{' (' + label + ')' if label else ''} taken off")
    for address in after["emails"]:
        if address not in before["emails"]:
            out.append(f"email {address} added")
    for address in before["emails"]:
        if address not in after["emails"]:
            out.append(f"email {address} taken off")
    if (before.get("note") or "") != (after.get("note") or ""):
        out.append("the note changed")
    return out


def history(who, card: dict) -> list[dict]:
    """Every change of the contact, oldest first: each with `at` (when), `before`, `after` and `said`."""
    from .synapse import db
    from .synapse.sources import contacts

    ds = contacts.master_of(str(who.user_id), str(who.org_id), make=False)
    if ds is None:
        return []
    item = db.row("SELECT id, title, meta, version, updated_at FROM synapse.item WHERE dataset_id = %s "
                  "AND id = %s::uuid", (ds["id"], str(card["id"])))
    if item is None:
        return []
    kept = db.rows("SELECT version, title, meta, made_at FROM synapse.item_version WHERE dataset_id = %s "
                   "AND item_id = %s::uuid ORDER BY version, id", (ds["id"], str(card["id"])))
    # Each kept version is the contact as it was until `made_at`, when the next one replaced it.
    states = [(state_of(v.get("meta") or {}, v.get("title") or ""), v.get("made_at")) for v in kept]
    states.append((state_of(item.get("meta") or {}, item.get("title") or ""), None))
    out = []
    previous = None
    for at, (state, made_at) in enumerate(states):
        if state is None:
            previous = None
            continue
        if previous is not None:
            said = differences(previous[0], state)
            if said:
                out.append({"at": previous[1], "before": previous[0], "after": state, "said": said})
        previous = (state, made_at)
    return out


def _when(at, zone) -> str:
    if at is None:
        return "lately"
    if isinstance(at, datetime):
        return at.astimezone(zone).strftime("%a %-d %b %Y at %H:%M")
    return str(at)


def restoring(card_now: dict, back_to: dict) -> dict:
    """The save that makes the contact read as `back_to` (the note left as it is)."""
    args: dict = {"contact_id": card_now["id"]}
    if back_to["name"] and back_to["name"] != card_now["name"]:
        args["name"] = back_to["name"]
    if back_to["organisation"] != card_now["organisation"]:
        args["organisation"] = back_to["organisation"]
    if back_to["birthday"] != card_now["birthday"] and back_to["birthday"]:
        args["birthday"] = back_to["birthday"]
    add = [{"number": n, "label": label or "work"} for n, label in back_to["phones"].items()
           if not any(_same_phone(n, m) for m in card_now["phones"])]
    gone = [n for n in card_now["phones"] if not any(_same_phone(n, m) for m in back_to["phones"])]
    if add:
        args["add_phones"] = add
    if gone:
        args["remove_phones"] = gone
    add_e = [{"address": a, "label": label or "work"} for a, label in back_to["emails"].items()
             if a not in card_now["emails"]]
    gone_e = [a for a in card_now["emails"] if a not in back_to["emails"]]
    if add_e:
        args["add_emails"] = add_e
    if gone_e:
        args["remove_emails"] = gone_e
    return args


async def answer(who, args: dict, desk, zone) -> str:
    """Everything the tool does, as `who`."""
    from asgiref.sync import sync_to_async

    from . import evolution
    from .contact_card import find
    from .synapse.sources import contacts

    if not await sync_to_async(on)(who):
        return "What changed on a contact is switched off (Evolution, Mutations)."
    cards = await sync_to_async(contacts.all_cards)(str(who.user_id), str(who.org_id))
    if not cards:
        return "There are no contacts to read: iCloud contacts are not connected, or the address book is empty."
    card, could_be = find(cards, contact_id=str(args.get("contact_id") or ""), name=str(args.get("name") or ""))
    if card is None:
        if could_be:
            listed = "; ".join(f"{c.get('name')} ({c.get('organisation') or 'no company'}, contact id {c['id']})"
                               for c in could_be[:6])
            return (f"Several contacts could be meant: {listed}. Ask which, then call contact_changes with its "
                    "contact_id.")
        return "No contact by that name or id. Search for them with search_contacts first."
    changes = await sync_to_async(history)(who, card)
    name = card.get("name") or "This contact"
    if not changes:
        return (f"{name}'s contact has not changed since Rouh first read it from iCloud, as far back as Rouh "
                "keeps earlier versions. Nothing was changed.")
    numbered = list(reversed(changes))[:MOST]
    back = args.get("put_back_before")
    if back in (None, "", 0):
        await sync_to_async(evolution.used)(SWITCH, "read", who=who, detail=f"{len(changes)} changes")
        lines = [f"{n}. {_when(c['at'], zone)}: {'; '.join(c['said'])}" for n, c in enumerate(numbered, start=1)]
        more = len(changes) - len(numbered)
        return (f"{name}'s contact changed {len(changes)} time{'s' if len(changes) != 1 else ''}, newest first:\n"
                + "\n".join(lines)
                + (f"\n({more} older change{'s' if more != 1 else ''} not listed.)" if more > 0 else "")
                + "\nWho made a change is not kept, only when and what: it may have been the phone, another "
                  "device or Rouh. To put the contact back as it was before one of these, call contact_changes "
                  "with put_back_before and that number. Nothing was changed.")
    try:
        number = int(back)
    except (TypeError, ValueError):
        return "put_back_before is the number of a change, as this tool listed it."
    if not 1 <= number <= len(numbered):
        return f"There is no change {number}: {name}'s contact has {len(numbered)} listed. Nothing was changed."
    target = numbered[number - 1]["before"]
    now = await sync_to_async(history)(who, card)
    current = now[-1]["after"] if now else target
    current = dict(current, id=card["id"])
    save = restoring(current, target)
    would = differences(current, dict(target, note=current.get("note") or ""))
    if len(save) <= 1 or not would:
        return f"{name}'s contact already reads as it did before change {number}. Nothing was changed."
    if not args.get("confirmed"):
        return (f"Putting {name}'s contact back as it was before change {number} "
                f"({_when(numbered[number - 1]['at'], zone)}) would make these changes: {'; '.join(would)}. "
                "Nothing is changed yet. Tell the person, and only if they say yes call contact_changes again "
                f"with put_back_before {number} and confirmed true.")
    if desk is None:
        return "iCloud contacts are not connected, so the contact could not be put back. Nothing was changed."
    done = await desk.save(save, who)
    words = str(getattr(done, "text", "") or done)
    if not (words.startswith("Changed") or "already reads that way" in words):
        return words
    await sync_to_async(evolution.used)(SWITCH, "put_back", who=who, detail=f"{len(would)} fields put back")
    return (f"Put {name}'s contact back as it was before change {number}: {'; '.join(would)}. "
            "It reaches the phone when it next syncs with iCloud.")


__all__ = ["DESCRIPTION", "MOST", "SCHEMA", "SWITCH", "TITLE", "answer", "differences", "history", "on",
           "restoring", "state_of"]
