"""Rouh's own contacts are gone: every card and every note on a person is on Synapse Master's people.

Petar, 4 October 2026: "Rouh's contacts should not exist. Rouh should be fully utilizing contacts
from the master." Until now `apple_contacts` kept a copy of every iCloud card and `contact_profiles`
Rouh's notes on people (relationship, research, addresses beyond the card, which one is the owner). Here,
for each account that had any:

1. Each note is put on its person in Synapse Master (found by the old profile id the people import
   left on them, then the card's UID, then an address), or a new person is made for it.
2. Each card is put on its person as `meta.icloud` by the same code the iCloud sync uses from now on
   (`synapse/contacts.keep`), so the sync carries on from these ETags without fetching anything again.
   A person the import had made of two duplicate cards keeps the first; the second is a person of its
   own, as it is on the phone.
3. Trusted contacts and the card picked in Settings name the person's id instead of c12 and p3.

Then both tables are dropped. A database that never had a contact (every test world) does nothing but
the drop. Run again after a failure it does the same: every step is keyed on what it has already done.
"""
import json
import re
import time

from django.db import connection, migrations

OLD_ID = re.compile(r"^[cp]\d+$")


def _rows(sql, params=()):
    with connection.cursor() as c:
        c.execute(sql, params)
        cols = [d[0] for d in c.description]
        return [dict(zip(cols, r)) for r in c.fetchall()]


def _list(value) -> list:
    """A JSON column as Django's own connection hands it back: as its text."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return []
    return value if isinstance(value, list) else []


def forward(apps, schema_editor):
    owners = _rows("SELECT DISTINCT user_id, org_id FROM apple_contacts UNION "
                   "SELECT DISTINCT user_id, org_id FROM contact_profiles")
    if not owners:
        return
    from rouh.carddav import Found
    from rouh.synapse import contacts, db, people
    from rouh.synapse.db import Json

    for owner in owners:
        user_id, org_id = owner["user_id"], owner["org_id"]
        ds = contacts.master_of(user_id, org_id)
        # 1. Rouh's notes on people.
        for p in _rows("SELECT * FROM contact_profiles WHERE user_id = %s AND org_id = %s ORDER BY id",
                       (user_id, org_id)):
            row = contacts.person_by_id(user_id, org_id, f"p{p['id']}")
            if row is None and p["apple_uid"]:
                row = db.row("SELECT * FROM synapse.item WHERE dataset_id = %s AND kind = 'person' AND deleted_at "
                             "IS NULL AND meta->'old' @> %s::jsonb ORDER BY stored_at LIMIT 1",
                             (ds["id"], Json([{"uid": p["apple_uid"]}])))
            known = [people.norm_email(e) for e in _list(p["emails"]) if people.norm_email(e)]
            for e in known:
                if row is None:
                    pid = people.find(ds["id"], "email", e)
                    row = people.get(ds["id"], pid) if pid else None
            if row is None:
                row = people.create(ds, name=p["name"] or (known + ["Someone"])[0], origin="synapse",
                                    emails=known, owner=str(ds.get("me_id") or ""),
                                    why="Rouh's notes on a person, moved from contact_profiles")
            # Two notes can be about one person (a card's, and an address's from before it had one): both kept.
            had = (row.get("meta") or {}).get("own_emails") or []
            meta = {"own_emails": list(dict.fromkeys(had + known))}
            if p["relationship"]:
                meta.update(relationship=p["relationship"], relationship_at=float(p["relationship_at"] or 0))
            if p["research"]:
                meta.update(research=p["research"], researched_at=float(p["researched_at"] or 0),
                            research_confirmed=bool(p["research_confirmed"]))
            if p["is_me"]:
                meta["is_me"] = True
                db.run("UPDATE synapse.dataset SET me_id = %s WHERE id = %s", (row["id"], ds["id"]))
            people.set_meta(row["id"], meta)
        # 2. The cards, oldest first, so a person made of duplicates keeps the first.
        found = [Found(href=r["href"], etag=r["etag"], data=r["vcard"]) for r in _rows(
            "SELECT href, etag, vcard FROM apple_contacts WHERE user_id = %s AND org_id = %s AND gone_at IS NULL "
            "AND kind = 'individual' ORDER BY id", (user_id, org_id))]
        contacts.keep(user_id, org_id, found)
        # 3. What named a contact by its old id.
        for t in _rows("SELECT id, contact_id FROM trusted_contacts WHERE user_id = %s AND org_id = %s",
                       (user_id, org_id)):
            if OLD_ID.match(t["contact_id"] or ""):
                row = contacts.person_by_id(user_id, org_id, t["contact_id"])
                if row is not None:
                    with connection.cursor() as c:
                        c.execute("UPDATE trusted_contacts SET contact_id = %s WHERE id = %s", (str(row["id"]), t["id"]))
        for s in _rows("SELECT value FROM user_settings WHERE user_id = %s AND org_id = %s AND name = "
                       "'my_contact_card'", (user_id, org_id)):
            try:
                held = json.loads(s["value"] or "{}")
            except ValueError:
                continue
            card = contacts.by_uid(user_id, org_id, held.get("uid") or "")
            if card is not None:
                with connection.cursor() as c:
                    c.execute("UPDATE user_settings SET value = %s, updated_at = %s WHERE user_id = %s AND "
                              "name = 'my_contact_card'",
                              (json.dumps({"uid": card["uid"], "id": card["id"]}), time.time(), user_id))


class Migration(migrations.Migration):

    dependencies = [("rouh", "0079_synapse_master")]

    operations = [
        migrations.RunPython(forward, migrations.RunPython.noop),
        migrations.DeleteModel(name="AppleContact"),
        migrations.DeleteModel(name="ContactProfile"),
    ]
