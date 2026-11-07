"""What Rouh knows about a person beyond their contact card.

Petar, 25 September 2026 (fr_b657bd8f6100), in his own words: "we need to
update our contacts. Please add two fields: 1. Online research (MD content)
2. My relationship to them." And, of the mail that had been piling up unread:
"When somebody comes into my email, the first thing you should do is research
them if there isn't any research about them. You should also maybe ask me what
my relationship is to them."

So every contact carries two things of Rouh's own:

- **My relationship to them**, in Petar's words: "a long-standing working
  relationship ... generally trustworthy". Only ever written from what he said
  (typed on the card, or said to Rouh). Mail from anybody else can never set
  it, and `rouh/tools.py` refuses it in a turn about somebody else's email.
- **Online research**, markdown, with what the web says about them and where
  it says it, and whether it was confirmed to be this very person rather than
  somebody with the same name - "Definitely cross-check by domain name of the
  email" - which is `research_confirmed`.

Neither is ever written into iCloud. They are Rouh's. Since 4 October 2026
they are fields of the person in the account's Synapse Master, beside the card
(`rouh/synapse/contacts.py`): Petar asked for one copy of his contacts, in
Synapse, and for Rouh to use it. The person's id is their id in Synapse; the
ids Rouh gave before, c12 for a card and p3 for one of Rouh's own, still find
them.

**Two kinds of person.** Somebody with an iCloud card, and somebody who wrote
in and is in nobody's address book: a contact of Rouh's own, with the name and
the addresses Rouh knows, which never reaches the phone. Adding one to iCloud
is still `save_contact`, on the person's own word.

**The person themselves.** Petar: "I should have a contact, and you should
update it with all my emails so you know that if it comes from any of those
emails, you should be doing it because I asked for it." One profile per
account is `is_me`. Since 1 October 2026 its addresses no longer decide whose
mail is his: that is the account's address and every email on the card he
picked in Settings, My contact card, and nothing else (`rouh/my_card.py`).
"""
from __future__ import annotations

import time
from dataclasses import dataclass

from . import vcard

#: How long either field may be. A page of research, not a book.
MAX_RELATIONSHIP = 2000
MAX_RESEARCH = 20000

#: How much of the research a search result carries. The whole of it is one
#: `show_contact` away.
RESEARCH_GIST = 280


def _addr(value) -> str:
    return str(value or "").strip().lower()


def _addresses(values) -> list[str]:
    """Addresses, lower case, each once, in the order given."""
    out: list[str] = []
    for value in values or ():
        one = _addr(value.get("address") if isinstance(value, dict) else value)
        if one and "@" in one and one not in out:
            out.append(one)
    return out


@dataclass
class Person:
    """A contact as Rouh knows them: their iCloud card, Rouh's profile, or both."""

    card: dict | None = None
    profile: dict | None = None

    @property
    def id(self) -> str:
        """Their id in Synapse Master, the same for the card and the notes."""
        if self.card is not None:
            return str(self.card["id"])
        return str(self.profile["id"]) if self.profile is not None else ""

    def _p(self, key: str, default=""):
        return (self.profile or {}).get(key, default) or default

    @property
    def name(self) -> str:
        return str((self.card or {}).get("name") or self._p("name") or "")

    @property
    def organisation(self) -> str:
        """Their company: the card's, else the one Rouh keeps for somebody with no card (`write`)."""
        return str((self.card or {}).get("organisation") or self._p("organisation") or "")

    @property
    def card_emails(self) -> list[str]:
        return _addresses((self.card or {}).get("emails") or [])

    @property
    def own_emails(self) -> list[str]:
        """The addresses Rouh knows for them that are not on the card."""
        mine = self.card_emails
        return [one for one in _addresses(self._p("emails", [])) if one not in mine]

    @property
    def emails(self) -> list[str]:
        return self.card_emails + self.own_emails

    @property
    def relationship(self) -> str:
        return str(self._p("relationship")).strip()

    @property
    def research(self) -> str:
        return str(self._p("research")).strip()

    @property
    def researched_at(self) -> float:
        return float(self._p("researched_at", 0) or 0)

    @property
    def research_confirmed(self) -> bool:
        return bool(self._p("research_confirmed", False))

    @property
    def is_me(self) -> bool:
        return bool(self._p("is_me", False))

    @property
    def silos(self) -> list[str]:
        """The person's silos they belong to, as keys (`rouh/silos.py`): one, several or none, which is
        not known. Rouh's own, beside the relationship, and never written to iCloud."""
        return [str(k) for k in self._p("silos", []) or []]

    @property
    def silos_by(self) -> str:
        """Who said so: person (the person themselves), source (their own words on the contact, or the
        rules on their addresses), or ""."""
        return str(self._p("silos_by"))

    def account(self) -> tuple[str, str]:
        """(user id, organisation id) of the person whose contact this is, from their Synapse dataset."""
        from .synapse import db

        got = db.row("SELECT user_id, org_id FROM synapse.dataset WHERE id = %s::uuid",
                     (self._p("dataset_id"),)) if self._p("dataset_id") else None
        return (str(got["user_id"]), str(got["org_id"])) if got else ("", "")

    def silos_said(self) -> str:
        """Their silos in words, with where they came from."""
        from . import silos

        uid, oid = self.account()
        if not self.silos or not uid:
            return "Silos: none yet."
        why = (" (you said so)" if self.silos_by == silos.BY_PERSON else
               f" (from {self._p('silos_why')})" if self._p("silos_why") else "")
        return f"Silos: {silos.said(uid, oid, self.silos)}{why}."

    @property
    def photo(self) -> str:
        """Where their face is drawn from: their iCloud card's picture, else the LinkedIn photo
        Rouh kept for them (`meeting_people.photo_url`), or "" for neither."""
        return str(self._p("photo"))

    @property
    def linkedin(self) -> dict:
        """Where they stand with LinkedIn (`meeting_people`): matched, or unresolved with the
        candidates numbered, and when."""
        return dict(self._p("linkedin", {}) or {})

    def gist(self) -> str:
        """The start of the research, on one line, for a list."""
        text = " ".join(self.research.split())
        return text if len(text) <= RESEARCH_GIST else text[:RESEARCH_GIST - 1] + "…"

    def research_said(self) -> str:
        """When it was researched and whether it is sure to be them, in words."""
        from . import clock

        if not self.research:
            return "Not researched yet."
        when = clock.moment(self.researched_at) if self.researched_at else None
        said = f"Researched {when.day} {when:%B %Y}." if when else "Researched."
        return said + (" Confirmed to be this person." if self.research_confirmed else
                       " Not confirmed to be this person: it may be somebody with the "
                       "same name.")


#: The fields of a person that are Rouh's notes, not the card's.
NOTES = ("relationship", "relationship_at", "research", "researched_at", "research_confirmed", "own_emails",
         "is_me")


def _profile(row: dict, me_id: str = "") -> dict:
    """A Synapse person as the notes Rouh keeps on them."""
    meta = row.get("meta") or {}
    return {"id": str(row["id"]), "name": meta.get("name") or row.get("title") or "",
            "emails": list(meta.get("emails") or []), "is_me": bool(meta.get("is_me")),
            "relationship": meta.get("relationship") or "", "relationship_at": float(meta.get("relationship_at") or 0),
            "research": meta.get("research") or "", "researched_at": float(meta.get("researched_at") or 0),
            "research_confirmed": bool(meta.get("research_confirmed")),
            "organisation": meta.get("organisation") or "",
            "apple_uid": ((meta.get("icloud") or {}).get("uid") or ""),
            "linkedin": dict(meta.get("linkedin") or {}), "photo": _photo_url(row),
            "silos": list(row.get("silos") or []), "silos_by": row.get("silos_by") or "",
            "silos_why": row.get("silos_why") or "", "dataset_id": str(row.get("dataset_id") or "")}


def _photo_url(row: dict) -> str:
    from . import meeting_people

    try:
        return meeting_people.photo_url(str(row["id"]), row.get("meta") or {})
    except Exception:  # noqa: BLE001 - a face is never worth failing a contact over
        return ""


def _person(row: dict | None) -> Person | None:
    from .synapse import contacts

    if not row:
        return None
    return Person(contacts.card_of(row), _profile(row))


class People:
    """What Rouh knows about people, read from and written to Synapse Master. Each method takes both ids."""

    # --- reading ------------------------------------------------------------

    @staticmethod
    def _ds(user_id: str, org_id: str) -> dict:
        from .synapse import contacts

        return contacts.master_of(user_id, org_id)

    @staticmethod
    def _rows(ds: dict, where: str, params=()) -> list[dict]:
        from .synapse import db

        return db.rows("SELECT * FROM synapse.item WHERE dataset_id = %s AND kind = 'person' AND deleted_at IS NULL "
                       + where, (ds["id"], *params))

    def attach(self, user_id: str, org_id: str, cards: list[dict]) -> list[Person]:
        """Cards found some other way, each with what Rouh keeps on them. One query."""
        from .synapse import contacts

        ids = [str(c["id"]) for c in cards if c.get("id")]
        if not ids:
            return [Person(c, None) for c in cards]
        by_id = {str(r["id"]): r for r in self._rows(self._ds(user_id, org_id), "AND id = ANY(%s::uuid[])", (ids,))}
        return [Person(contacts.card_of(by_id[str(c["id"])]) or c, _profile(by_id[str(c["id"])]))
                if str(c.get("id")) in by_id else Person(c, None) for c in cards]

    def person(self, user_id: str, org_id: str, contact_id) -> Person | None:
        """A contact by the id Rouh gives it, or me."""
        from .synapse import contacts

        said = str(contact_id or "").strip().lower()
        if not user_id or not org_id or not said:
            return None
        if said in ("me", "myself", "self"):
            return self.me(user_id, org_id)
        return _person(contacts.person_by_id(user_id, org_id, said))

    def me(self, user_id: str, org_id: str) -> Person | None:
        """The person's own contact: the card they picked on their profile (`my_card`), else the one marked
        as theirs, else Master's own person."""
        from . import my_card

        try:
            picked = my_card.card(user_id, org_id)
        except Exception:  # noqa: BLE001 - no choice readable is no choice
            picked = None
        if picked is not None:
            got = self.person(user_id, org_id, picked["id"])
            if got is not None:
                got.profile = dict(got.profile or {}, is_me=True)
                return got
        ds = self._ds(user_id, org_id)
        rows = self._rows(ds, "AND meta->>'is_me' = 'true' ORDER BY stored_at LIMIT 1")
        if not rows and ds.get("me_id"):
            rows = self._rows(ds, "AND id = %s::uuid", (str(ds["me_id"]),))
        return _person(rows[0]) if rows else None

    def by_address(self, user_id: str, org_id: str, address: str) -> list[Person]:
        """Everybody an address belongs to, the person's own contact first: every person of Synapse Master
        the address is an identity of, one of whose known addresses it is, or whose phone's card has it.

        The card counts on its own: an address Synapse had already given a person it met in an item stays
        that person's identity when the card arrives (`contacts.write`), and the card is still who it is."""
        address = _addr(address)
        if not address or not user_id or not org_id:
            return []
        from .synapse import db, people as synapse_people

        ds = self._ds(user_id, org_id)
        norm = synapse_people.norm_email(address)
        rows = db.rows(
            "SELECT DISTINCT i.* FROM synapse.item i LEFT JOIN synapse.identity x ON x.scope_id = i.dataset_id "
            "AND x.item_id = i.id AND x.type = 'email' AND x.value = %s WHERE i.dataset_id = %s AND i.kind = 'person' "
            "AND i.deleted_at IS NULL AND (x.item_id IS NOT NULL OR i.meta->'emails' ? %s OR EXISTS (SELECT 1 FROM "
            "jsonb_array_elements(CASE WHEN jsonb_typeof(i.meta->'icloud'->'emails') = 'array' "
            "THEN i.meta->'icloud'->'emails' ELSE '[]'::jsonb END) e WHERE lower(e->>'address') = %s))",
            (norm, ds["id"], norm, norm))
        out = [_person(r) for r in rows]
        out = [p for p in out if p is not None]
        out.sort(key=lambda p: (not p.is_me, p.card is None, p.name))
        return out

    def search(self, user_id: str, org_id: str, query: str, *, skip=()) -> list[Person]:
        """People with no card whom a few words find (Rouh's own contacts, by name and address), and anybody
        by what their relationship says ("my mother"). `skip` is the ids a card search already found."""
        words = vcard.normalise(query or "").split()
        if not words or not user_id or not org_id:
            return []
        ds = self._ds(user_id, org_id)
        rows = self._rows(ds, "AND (coalesce(meta->>'relationship', '') <> '' OR meta->>'is_me' = 'true' "
                              "OR (NOT meta ? 'icloud' AND meta->>'origin' = 'icloud') "
                              "OR coalesce(meta->>'research', '') <> '') ORDER BY stored_at")
        out: list[Person] = []
        for row in rows:
            one = _person(row)
            if one is None or not one.id or one.id in skip:
                continue
            said = " ".join([one.name, one.relationship, *one.emails, "me myself" if one.is_me else ""])
            hay = vcard.normalise(said) + " " + vcard.latin(said)
            if all(w in hay or vcard.latin(w) in hay for w in words):
                out.append(one)
        return out

    # --- writing ------------------------------------------------------------

    def ensure_me(self, user_id: str, org_id: str) -> Person:
        """The person's own contact: Master's own person, marked as theirs the first time."""
        found = self.me(user_id, org_id)
        if found is not None:
            return found
        from .synapse import datasets

        ds = self._ds(user_id, org_id)
        datasets.me(ds)  # made if it is not there yet
        return self.me(user_id, org_id)

    def write(self, user_id: str, org_id: str, person: Person | None, *,
              name: str | None = None, address: str = "",
              relationship: str | None = None, research: str | None = None,
              confirmed: bool | None = None, add_emails=(), remove_emails=(), silos=None,
              organisation: str | None = None) -> Person:
        """Change what Rouh knows about a person, and hand them back as they now are.

        `person` None is somebody new to Rouh, known by `address` and `name`: a person of Synapse Master
        and a contact of Rouh's own, which never reaches iCloud. A field left None is left as it is; an
        empty string clears it. `silos` is the person's silos they are in, by name or key, as the person said
        it ("Family", ["work", "family"], "none"; `rouh/silos.py`): a name that is no silo is refused, never
        made up. `organisation` is their company: on a card it is the card's, so it is queued to be
        written to iCloud as an edit in Synapse is (`contacts.push_soon`); with no card it stays here.
        Nothing else here is written to iCloud. ValueError says what is wrong.
        """
        from .synapse import contacts, db, people as synapse_people

        if not user_id or not org_id:
            raise ValueError("A contact belongs to a person in an organisation.")
        if relationship is not None and len(relationship) > MAX_RELATIONSHIP:
            raise ValueError(f"The relationship is longer than {MAX_RELATIONSHIP} "
                             "characters. A few sentences is what is read.")
        if research is not None and len(research) > MAX_RESEARCH:
            raise ValueError(f"The research is longer than {MAX_RESEARCH} characters. Keep "
                             "what matters about them and where it was found.")
        from . import silos as silo_store

        label = None
        if silos is not None:
            label, missing = silo_store.parse(user_id, org_id, silos)
            if missing:
                raise ValueError(silo_store.unknown_said(user_id, org_id, missing))
            label = label or []
        ds = self._ds(user_id, org_id)
        now = time.time()
        with db.atomic():
            if person is None:
                first = _addr(address)
                if "@" not in first:
                    raise ValueError("Somebody new needs an email address to be known by.")
                found = self.by_address(user_id, org_id, first)
                if found:
                    person = found[0]
                else:
                    made = synapse_people.create(ds, name=(name or "").strip()[:200] or first, origin="synapse",
                                                 emails=[first], readers=[str(ds.get("me_id") or "")] or None,
                                                 owner=str(ds.get("me_id") or ""), why="a contact of Rouh's own")
                    person = _person(made)
            row = db.row("SELECT * FROM synapse.item WHERE dataset_id = %s AND id = %s::uuid AND deleted_at IS NULL "
                         "FOR UPDATE", (ds["id"], person.id))
            if row is None:
                raise ValueError("That contact is not there any more.")
            meta = dict(row.get("meta") or {})
            title = row["title"]
            if name is not None and name.strip() and not meta.get("icloud"):
                title = meta["name"] = name.strip()[:200]
            if relationship is not None:
                meta["relationship"] = relationship.strip()
                meta["relationship_at"] = now if meta["relationship"] else 0
            if research is not None:
                meta["research"] = research.strip()
                meta["researched_at"] = now if meta["research"] else 0
                if not meta["research"]:
                    meta["research_confirmed"] = False
            if confirmed is not None:
                meta["research_confirmed"] = bool(confirmed) and bool(meta.get("research"))
            before = dict(row.get("meta") or {})
            if organisation is not None:
                meta["organisation"] = " ".join(organisation.split())[:200]
            card = {synapse_people.norm_email(e.get("address")) for e in (meta.get("icloud") or {}).get("emails") or []}
            own = [e for e in meta.get("own_emails") or [] if e not in card]
            for one in _addresses(add_emails):
                one = synapse_people.norm_email(one)
                if one and one not in card and one not in own:
                    own.append(one)
            gone = {synapse_people.norm_email(e) for e in _addresses(remove_emails)}
            own = [e for e in own if e not in gone]
            meta["own_emails"] = own
            meta["emails"] = [e for e in dict.fromkeys(list(card) + [e for e in meta.get("emails") or []
                                                                      if e not in gone] + own) if e]
            for k in ("relationship", "research"):
                if not meta.get(k):
                    meta.pop(k, None)
            contacts.write(ds, row, meta, title, by="rouh", why="Rouh's own notes on them")
            if organisation is not None and (before.get("organisation") or "") != meta["organisation"]:
                # The company is a field of the card: iCloud is told, as a Synapse edit tells it.
                contacts.push_soon(ds, str(row["id"]), before, meta, by="rouh")
            if label is not None:
                # The label is the person item's own field (`synapse.item.silos`), never the card's.
                if not label:
                    db.run("UPDATE synapse.item SET silos = '{}', silos_by = '', silos_why = '' WHERE id = %s",
                           (row["id"],))
                else:
                    from . import owner

                    db.run("UPDATE synapse.item SET silos = %s::text[], silos_by = 'person', silos_why = %s "
                           "WHERE id = %s", (label, owner.say("‹Owner› said so", user_id), row["id"]))
        if label is None and (relationship is not None or add_emails or remove_emails):
            # What they are to the person, or their addresses, may place them in a silo (`silos.fill`).
            silo_store.fill(ds, ("contacts",))
        return _person(db.row("SELECT * FROM synapse.item WHERE id = %s::uuid", (person.id,)))


__all__ = ["MAX_RELATIONSHIP", "MAX_RESEARCH", "People", "Person"]
