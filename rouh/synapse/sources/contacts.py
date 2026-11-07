"""Rouh's contacts are Synapse Master's people: one copy, kept two ways with iCloud.

Petar, 4 October 2026, by voice: "I need it to be both ways. If I update a contact on synapse it needs
to go to iCloud and my phone ... Rouh's contacts should not exist. Rouh should be fully utilizing
contacts from the master." Until then Rouh kept its own copy of every iCloud card (`apple_contacts`)
and its own notes on people (`contact_profiles`) beside Synapse's people; both are gone (migration
0080), and this is where the cards are kept instead.

- **A contact is a person of Synapse Master** (`synapse/master.py`) with an `icloud` field on its meta:
  the card's address in iCloud (`href`), its vCard UID, its ETag, the whole vCard, every number and
  address with the label the phone shows beside it, and what a search reads. The person's own fields
  are the card's: name, organisation, birthday, note, addresses and numbers, so Synapse, its debugger
  and Rouh's tools all read the same thing.
- **iCloud to Synapse.** The CardDAV sync (`apple_contacts.ContactDesk`) is unchanged and hands what it
  fetched to `keep`: a card it has seen updates its person, a new one is matched to a person Synapse
  already knows by an address or a number before a new person is made, and a card iCloud says is gone
  takes its `icloud` field off (`gone`): the person stays in Synapse's memory, no longer a contact.
- **Synapse to iCloud.** An edit of a contact in Synapse (`ingest.edit_person`) queues `push`, which
  writes the change to iCloud through the same code Rouh's save_contact uses (merge, conflict and audit
  included), and the card iCloud keeps comes back through `keep`. A contact deleted in Synapse is
  deleted from iCloud the same way. A person who is no contact never reaches the phone.
- **Rouh's notes on people** (who they are to the person, the online research, addresses Rouh knows
  for them that are not on the card) are fields of the same person (`rouh/people.py`).

Every function takes the account's two ids and finds that person's Master, made empty the first time
if there is none.
"""
from __future__ import annotations

import logging
import time

from .. import db
from ..db import Json

log = logging.getLogger("rouh.synapse.contacts")

#: What a contact card is, as `apple_contacts` and its callers have always read one.
CARD_FIELDS = ("id", "uid", "href", "etag", "kind", "name", "phones", "emails", "organisation", "birthday",
               "note", "vcard", "search_text", "digits", "changed_at", "gone_at")


def master_of(user_id: str, org_id: str, *, make: bool = True) -> dict | None:
    from .. import master

    ds = master.of(str(org_id), str(user_id))
    if ds is None and make:
        ds = master.make(str(org_id), str(user_id))["dataset"]
    return ds


def card_of(row: dict | None) -> dict | None:
    """A person row as a contact card, or None when the person is no contact."""
    if not row or row.get("deleted_at") is not None:
        return None
    meta = row.get("meta") or {}
    ic = meta.get("icloud")
    if not isinstance(ic, dict) or not ic.get("href"):
        return None
    return {"id": str(row["id"]), "uid": ic.get("uid") or "", "href": ic["href"], "etag": ic.get("etag") or "",
            "kind": ic.get("kind") or "individual", "name": meta.get("name") or row.get("title") or "",
            "phones": ic.get("phones") or [], "emails": ic.get("emails") or [],
            "organisation": meta.get("organisation") or "", "birthday": meta.get("birthday") or "",
            "note": meta.get("note") or "", "vcard": ic.get("vcard") or "", "search_text": ic.get("search_text") or "",
            "digits": ic.get("digits") or "", "changed_at": float(ic.get("changed_at") or 0), "gone_at": None,
            "user_id": "", "org_id": ""}


def _cards_sql(where: str = "") -> str:
    return ("SELECT * FROM synapse.item WHERE dataset_id = %s AND kind = 'person' AND deleted_at IS NULL "
            "AND meta ? 'icloud' " + where)


def etags(user_id: str, org_id: str) -> dict[str, str]:
    ds = master_of(user_id, org_id)
    return {r["href"]: r["etag"] or "" for r in db.rows(
        "SELECT meta->'icloud'->>'href' AS href, meta->'icloud'->>'etag' AS etag FROM synapse.item "
        "WHERE dataset_id = %s AND kind = 'person' AND deleted_at IS NULL AND meta ? 'icloud'", (ds["id"],))}


def one(user_id: str, org_id: str, contact_id) -> dict | None:
    """A contact by its id: the person's id (c and p in front are allowed), or a card's old number."""
    return card_of(person_by_id(user_id, org_id, contact_id))


def person_by_id(user_id: str, org_id: str, contact_id) -> dict | None:
    """The person a contact id names: their id, `c`/`p` and their id, or c12 and p3 as they were before
    Rouh's contacts moved here (kept on the person as `old`)."""
    said = str(contact_id or "").strip()
    if not said:
        return None
    ds = master_of(user_id, org_id)
    low = said.lower()
    if len(low) > 30 and low[:1] in ("c", "p") and low[1:2].isalnum() and "-" in low:
        low = low[1:]
    if len(low) >= 32 and "-" in low:
        try:
            return db.row("SELECT * FROM synapse.item WHERE dataset_id = %s AND id = %s::uuid AND kind = 'person' "
                          "AND deleted_at IS NULL", (ds["id"], low))
        except Exception:  # noqa: BLE001 - not an id
            return None
    kind, number = low[:1], low[1:]
    if kind in ("c", "p") and number.isdigit():
        key = "card_id" if kind == "c" else "profile_id"
        return db.row("SELECT * FROM synapse.item WHERE dataset_id = %s AND kind = 'person' AND deleted_at IS NULL "
                      "AND meta->'old' @> %s::jsonb ORDER BY stored_at LIMIT 1", (ds["id"], Json([{key: int(number)}])))
    return None


def by_href(user_id: str, org_id: str, href: str) -> dict | None:
    ds = master_of(user_id, org_id)
    return card_of(db.row(_cards_sql("AND meta->'icloud'->>'href' = %s LIMIT 1"), (ds["id"], href)))


def count(user_id: str, org_id: str) -> int:
    ds = master_of(user_id, org_id, make=False)
    if ds is None:
        return 0
    return int(db.value("SELECT count(*) FROM synapse.item WHERE dataset_id = %s AND kind = 'person' "
                        "AND deleted_at IS NULL AND meta ? 'icloud'", (ds["id"],)) or 0)


def search(user_id: str, org_id: str, query: str, limit: int = 8, *, most: int = 50) -> list[dict]:
    """The contacts a few words or a number find, best first, as `apple_contacts` has always ranked them."""
    import re

    from ... import vcard

    ds = master_of(user_id, org_id)
    text = (query or "").strip()
    digits = vcard.digits_of(text)
    letters = re.sub(r"[\d\s+().\-/]", "", text)
    words: list[str] = []
    sql, params = _cards_sql(), [ds["id"]]
    if len(digits) >= 3 and not letters:
        tail = digits.lstrip("0")[-9:] or digits
        sql += " AND meta->'icloud'->>'digits' LIKE %s"
        params.append(f"%{tail}%")
    else:
        words = vcard.normalise(text).split()
        for word in words:
            sql += " AND (meta->'icloud'->>'search_text' LIKE %s OR meta->'icloud'->>'search_text' LIKE %s)"
            params += [f"%{word}%", f"%{vcard.latin(word)}%"]
    found = [card_of(r) for r in db.rows(sql + " ORDER BY title LIMIT 200", params)]
    found = [c for c in found if c and c["kind"] == "individual"]

    def rank(row: dict) -> tuple:
        name = vcard.normalise(row["name"])
        also = vcard.latin(row["name"])
        if not words:
            return (0, name)
        if all(any(part.startswith((w, vcard.latin(w))) for part in (name + " " + also).split()) for w in words):
            return (0, name)
        if all(w in name or vcard.latin(w) in also for w in words):
            return (1, name)
        org = vcard.normalise(row["organisation"])
        if all(w in org for w in words):
            return (2, name)
        return (3, name)

    found.sort(key=rank)
    return found[:max(1, min(int(limit or 8), most))]


def all_cards(user_id: str, org_id: str, *, with_birthday: bool = False) -> list[dict]:
    ds = master_of(user_id, org_id, make=False)
    if ds is None:
        return []
    where = "AND coalesce(meta->>'birthday', '') <> ''" if with_birthday else ""
    return [c for c in (card_of(r) for r in db.rows(_cards_sql(where) + " ORDER BY title", (ds["id"],)))
            if c and c["kind"] == "individual"]


def by_uid(user_id: str, org_id: str, uid: str) -> dict | None:
    if not uid:
        return None
    ds = master_of(user_id, org_id, make=False)
    if ds is None:
        return None
    return card_of(db.row(_cards_sql("AND meta->'icloud'->>'uid' = %s ORDER BY stored_at LIMIT 1"), (ds["id"], uid)))


# ---------------------------------------------------------------------------------------------
# iCloud to Synapse
# ---------------------------------------------------------------------------------------------

def _person_for_card(ds: dict, href: str, card) -> dict | None:
    """The person a card is: by its address in iCloud, its UID, the old contact it was, then a person
    Synapse already knows by an address or a number. None for somebody new."""
    from .. import people

    got = db.row(_cards_sql("AND meta->'icloud'->>'href' = %s LIMIT 1"), (ds["id"], href))
    if got:
        return got
    if card.uid:
        got = db.row("SELECT * FROM synapse.item WHERE dataset_id = %s AND kind = 'person' AND deleted_at IS NULL "
                     "AND (meta->'icloud'->>'uid' = %s OR (meta->'old' @> %s::jsonb AND NOT meta ? 'icloud')) "
                     "ORDER BY stored_at LIMIT 1",
                     (ds["id"], card.uid, Json([{"uid": card.uid}])))
        if got:
            return got
    for t, values in (("email", [e["address"] for e in card.emails]), ("phone", [p["number"] for p in card.phones])):
        for v in values:
            norm = people.norm_email(v) if t == "email" else people.norm_phone(v)
            pid = people.find(ds["id"], t, norm)
            if pid:
                row = db.row("SELECT * FROM synapse.item WHERE id = %s AND kind = 'person'", (pid,))
                # Never two cards on one person: a person who already has another card stays apart.
                if row and not (row.get("meta") or {}).get("icloud"):
                    return row
    return None


def write(ds: dict, item: dict, meta: dict, title: str, *, by: str, why: str) -> None:
    """A person's new meta and words, the old version kept (D27), identities added; never pushed anywhere."""
    from .. import datasets, people, text as tx

    people_ids = []
    for e in meta.get("emails") or []:
        if people.add_identity(ds["id"], item["id"], "email", e, e, why) not in ("added", "had"):
            people_ids.append(e)
    meta["emails"] = [e for e in meta.get("emails") or [] if e not in people_ids]
    for p in meta.get("phones") or []:
        people.add_identity(ds["id"], item["id"], "phone", p, p, why)
    people.add_identity(ds["id"], item["id"], "name", people.norm_name(title), title, why)
    db.run("INSERT INTO synapse.item_version (dataset_id, item_id, version, title, raw, meta, keep_until, why) "
           "VALUES (%s, %s, %s, %s, %s, %s::jsonb, now() + make_interval(days => %s), %s)",
           (ds["id"], item["id"], item["version"], item["title"], item["raw"], Json(item.get("meta") or {}),
            int(datasets.settings(ds).version_days), f"{by}: {why}"[:300]))
    body = people.person_text(meta, ds.get("owner_name") or "the owner")
    db.run("UPDATE synapse.item SET title = %s, raw = %s, body = %s, meta = %s::jsonb, version = version + 1, "
           "updated_at = now() WHERE id = %s", (title, body, body, Json(meta), item["id"]))
    people.write_words(ds["id"], item["id"], title, body + " " + tx.other_alphabet(title))


def keep(user_id: str, org_id: str, found) -> int:
    """Cards as iCloud holds them, onto their people. How many were new or changed."""
    from ... import vcard
    from .. import people

    if not found:
        return 0
    ds = master_of(user_id, org_id)
    me = str(ds.get("me_id") or "")
    changed = 0
    now = time.time()
    for card in found:
        try:
            person = vcard.read(card.data)
        except Exception:  # noqa: BLE001 - one unreadable card never stops a sync
            log.warning("a card from iCloud could not be read")
            continue
        if person.kind != "individual":
            continue  # iCloud's contact groups are no people
        words, digits = vcard.searchable(person)
        emails = [e for e in dict.fromkeys(people.norm_email(e["address"]) for e in person.emails) if e]
        phones = [p for p in dict.fromkeys(people.norm_phone(p["number"]) for p in person.phones) if p]
        icloud = {"href": card.href, "uid": person.uid, "etag": card.etag, "kind": person.kind, "vcard": card.data,
                  "phones": person.phones, "emails": person.emails, "search_text": words, "digits": digits,
                  "photo": person.photo, "changed_at": now}
        row = _person_for_card(ds, card.href, person)
        name = " ".join((person.name or "").split())[:200] or (emails + phones + ["Someone"])[0]
        if row is None:
            people.create(ds, name=name, origin="icloud", emails=emails, phones=phones, readers=[me] if me else None,
                          extra={"icloud": icloud, "organisation": person.organisation, "birthday": person.birthday,
                                 "note": person.note, "imported_at": _iso(now)},
                          source="icloud", source_key=person.uid or card.href, owner=me,
                          why="a card in iCloud", written={people.norm_phone(p["number"]): p["number"]
                                                           for p in person.phones})
            changed += 1
            continue
        meta = dict(row.get("meta") or {})
        if (meta.get("icloud") or {}).get("etag") == card.etag and (meta.get("icloud") or {}).get("href") == card.href:
            continue
        own = [e for e in meta.get("own_emails") or [] if e not in emails]
        meta.update({"origin": "icloud", "name": name, "icloud": icloud, "organisation": person.organisation,
                     "birthday": person.birthday, "note": person.note, "emails": emails + own, "phones": phones,
                     "imported_at": _iso(now)})
        meta.pop("icloud_gone", None)
        for k in ("organisation", "birthday", "note"):
            if not meta.get(k):
                meta.pop(k, None)
        write(ds, row, meta, name, by="icloud", why="the card changed in iCloud")
        changed += 1
    return changed


def _iso(ts: float) -> str:
    from datetime import datetime, timezone

    return datetime.fromtimestamp(ts, timezone.utc).isoformat()


def gone(user_id: str, org_id: str, hrefs) -> int:
    """Cards iCloud says went: their people stay in Synapse, no longer contacts."""
    hrefs = [h for h in hrefs or [] if h]
    if not hrefs:
        return 0
    ds = master_of(user_id, org_id)
    rows = db.rows(_cards_sql("AND meta->'icloud'->>'href' = ANY(%s)"), (ds["id"], hrefs))
    for row in rows:
        meta = dict(row.get("meta") or {})
        meta["icloud_gone"] = {**(meta.pop("icloud") or {}), "gone_at": time.time()}
        meta["icloud_gone"].pop("vcard", None)
        write(ds, row, meta, row["title"], by="icloud", why="the card went from iCloud")
    return len(rows)


def forget(user_id: str, org_id: str) -> int:
    """Every card of the account's: their people stay, no longer contacts (a disconnect, another Apple ID)."""
    ds = master_of(user_id, org_id, make=False)
    if ds is None:
        return 0
    hrefs = [r["h"] for r in db.rows("SELECT meta->'icloud'->>'href' AS h FROM synapse.item WHERE dataset_id = %s "
                                    "AND kind = 'person' AND meta ? 'icloud'", (ds["id"],))]
    return gone(user_id, org_id, hrefs)


# ---------------------------------------------------------------------------------------------
# Synapse to iCloud
# ---------------------------------------------------------------------------------------------

def push_soon(ds: dict, item_id: str, before: dict, after: dict, *, by: str) -> int | None:
    """An edit of a contact in Synapse, queued to be written to iCloud. None when there is nothing to send:
    the person is no contact, the edit came from iCloud, or no field iCloud holds changed."""
    from .. import ingest

    if by in ("icloud",) or not (before.get("icloud") or after.get("icloud")):
        return None
    args = changes_for_icloud(before, after)
    if not args:
        return None
    return ingest.enqueue(ds["id"], "icloud_push", item_id=item_id, priority=2,
                          payload={"args": args, "why": f"edited in Synapse ({by})"})


def changes_for_icloud(before: dict, after: dict) -> dict:
    """What iCloud has to be told, as save_contact's arguments: only the fields a card holds."""
    from .. import people

    args: dict = {}
    if (after.get("name") or "") != (before.get("name") or "") and after.get("name"):
        args["name"] = after["name"]
    for k in ("organisation", "birthday", "note"):
        if (after.get(k) or "") != (before.get(k) or ""):
            args[k] = after.get(k) or ""
    own = set(after.get("own_emails") or [])
    card_emails = {people.norm_email(e.get("address")) for e in (after.get("icloud") or {}).get("emails") or []}
    add_e = [e for e in after.get("emails") or [] if e not in card_emails and e not in own
             and e not in (before.get("emails") or [])]
    card_phones = {people.norm_phone(p.get("number")) for p in (after.get("icloud") or {}).get("phones") or []}
    add_p = [p for p in after.get("phones") or [] if p not in card_phones and p not in (before.get("phones") or [])]
    if add_e:
        args["add_emails"] = [{"address": e} for e in add_e]
    if add_p:
        args["add_phones"] = [{"number": p} for p in add_p]
    return args


def delete_soon(ds: dict, item: dict, *, by: str) -> int | None:
    """A contact deleted in Synapse, queued to be deleted from iCloud."""
    from .. import ingest

    ic = (item.get("meta") or {}).get("icloud") or {}
    if by == "icloud" or not ic.get("href"):
        return None
    return ingest.enqueue(ds["id"], "icloud_delete", item_id=item["id"], priority=2,
                          payload={"href": ic["href"], "etag": ic.get("etag") or "", "name": item.get("title") or "",
                                   "why": f"deleted in Synapse ({by})"})


def run_job(ds: dict, job: dict) -> None:
    """The worker's side: the change written to iCloud by Rouh's contact desk, on Rouh's own loop."""
    import asyncio

    from ... import runtime
    from ...tenancy import Identity

    desk = getattr(runtime, "contacts", None)
    loop = getattr(desk, "loop", None) if desk else None
    if desk is None or loop is None or loop.is_closed():
        raise RuntimeError("Rouh's contact desk is not running here, so iCloud cannot be written to yet")
    who = Identity(user_id=str(ds["user_id"]), org_id=str(ds["org_id"]))
    payload = job.get("payload") or {}
    if job["kind"] == "icloud_push":
        coro = desk.save({**(payload.get("args") or {}), "contact_id": str(job["item_id"])}, who=who)
    else:
        coro = desk.remove_card(who, href=payload.get("href") or "", etag=payload.get("etag") or "",
                                name=payload.get("name") or "")
    got = asyncio.run_coroutine_threadsafe(coro, loop).result(timeout=120)
    said = getattr(got, "text", got)
    log.info("Synapse %s for %s: %s", job["kind"], job.get("item_id"), str(said)[:300])
    if isinstance(said, str) and ("Nothing was changed" in said or "Nothing was deleted" in said):
        raise RuntimeError(said[:500])


__all__ = ["CARD_FIELDS", "all_cards", "by_href", "by_uid", "card_of", "changes_for_icloud", "count", "delete_soon",
           "etags", "forget", "gone", "keep", "master_of", "one", "person_by_id", "push_soon", "run_job", "search"]
