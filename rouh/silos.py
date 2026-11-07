"""Silos: the parts of a person's life everything Rouh keeps is labelled with (12 October 2026).

Petar: "Make a silo setting in settings. This will control how many silos you have and what they are
called. Maybe a person has more than two. And then everything will get labeled - data, emails,
calendars etc". It grows out of card 1499's fixed work and personal label (`git show 64dea4b5`): one
memory and one Rouh, nothing split, and a label on things - now a set of the account's own silos.

**The silos** are the account's (`Silo`, Settings, Silos at /settings/silos): as many as it wants, each
with a name, a colour and a place in the list, added, renamed, recoloured, moved and deleted there.
Each has a stable key, which is what every label holds, so a rename changes nothing underneath. Every
account starts with two, Work and Personal, which took over the fixed labels with their keys (`work`,
`personal`), and with the source rules that the fixed labels used to be worked out by (`_seed`, the one
place that names either). Deleting a silo that still holds anything asks which silo it all moves to
(`remove`): nothing is left orphaned and nothing is deleted.

**The label** is a set of silo keys, on every item of Synapse (`synapse.item.silos`) and so on every
contact, who is a person of Synapse Master, and on every Clockwork item (`Reminder.silos`). A thing can
be in one silo, several or none, and none is not known. Where it comes from, strongest first
(`silos_by` on an item):

- `person`: Petar said so ("that's family"), on the lab's item page, a contact's card, the Clockwork
  page, or to Rouh (`synapse_edit`, `update_contact_profile`). Nothing else changes it after that.
- `source`: where the thing comes from decides it, by code and the account's source rules (`SiloRule`,
  set in Settings, Silos): a task takes its project's silo (a rule on the project, or on a project or
  column above it) and everything inside a task takes the task's label; a project's chat its
  project's; an event its calendar's; a meeting its event's, or the meetings' rule; an email its
  sender's, its sender's domain's, its contact's (when the contact is in one silo), the silo of an address
  it was sent to (each address's own silo, set on a contact card, `person_addresses`), or its inbox's; an
  email's file its email's; a contact the rules on their addresses and what Petar said they are to him
  (each silo's `words`); a layer made only from one silo that silo (`fill`, run by the ten-minute sync,
  after the calendar and meeting syncs, and after any change on the Silos page).
- `model`: the X-ray call reads the rest, choosing from the account's silos, in the one call it already
  makes (`ingest.silos_step`), and leaves it not known when the item does not tell.

General's chat is about everything and stays unlabelled.

**Who may see what.** Somebody who uses Rouh on Petar's behalf - a trusted contact by email or
Telegram, a delegate, and an unattended run on Rouh itself - may see a set of silos (`limited`): a
trusted contact's own `sees`, or the silos shown to others (`Silo.others`) until he sets theirs, and
the silos unattended runs see (`Silo.runs`). Work, to start with, except a contact given Work and
Personal. A set that holds every silo is no limit at all, which is how such a contact keeps everything;
any other set sees a thing only when it shares a silo with it, and never anything not known:

- **Synapse filters in code, at the readers check.** A limited reader asks with sided principals,
  `<silo>:<owner id>` and `<silo>:everyone` for each silo of theirs (`principals`), and an item carries
  sided readers only for its own silos (`synapse.can_read_for`, migrations 0133 and 0134), so the one
  column every search, walk, link and look-up by id already filters on keeps the rest out.
- **The workspace**: what Petar granted them by name stays theirs; the jobs Rouh has running and a job
  started for them keep to their silos (`run_silos`, `job_rule`), and an unattended run's brief says
  which folders it may not open (`run_rule`).
- **Contacts**: a contact in none of their silos is not looked up for them (`apple_contacts`).
"""
from __future__ import annotations

import contextvars
import logging
import re
import secrets
import threading
import time
from dataclasses import dataclass

log = logging.getLogger("rouh.silos")

#: Who set an item's label, strongest first.
BY_PERSON, BY_SOURCE, BY_MODEL = "person", "source", "model"

#: The page's colours by name, as `taskbrowser.js` names them; any "#rrggbb" is one too.
COLOURS = {"blue": "#72a6f7", "amber": "#e2b04d", "teal": "#4cc4b0", "rose": "#f07ea2",
           "violet": "#ab8ff3", "green": "#7ec86c", "slate": "#a3adbb"}
#: A key every new silo gets: "s" and eight hex digits. Never one of `RESERVED`, which mean something
#: else where keys are written into principals and askers.
KEY = re.compile(r"^[a-z][a-z0-9]{1,30}$")
RESERVED = {"in", "nobody", "everyone", "none", "unknown", "all", "me"}
MOST = 12
NAME_MOST = 40

#: What a source rule can match (`SiloRule.kind`), as the Silos page names each.
RULE_KINDS = {
    "project": "Project or column",
    "calendar": "Calendar",
    "domain": "Email domain",
    "sender": "Email address",
    "inbox": "Inbox",
    "drive": "Shared drive or folder",
    "meetings": "Meetings with no calendar event",
    "slack": "Slack",
}

#: A rule's silo that is every silo the account has: a holiday calendar is everybody's.
EVERY = "*"

#: Words that say a thing is in no silo, said to Rouh or typed.
NONE_WORDS = {"", "none", "unknown", "not known", "nothing", "no silo", "unlabelled", "unlabeled"}


@dataclass(frozen=True)
class SiloInfo:
    key: str
    name: str
    colour: str
    position: int
    words: tuple = ()
    runs: bool = False
    others: bool = False

    @property
    def hex(self) -> str:
        return hex_of(self.colour)

    def chip(self) -> dict:
        return {"key": self.key, "name": self.name, "colour": self.hex}

    def public(self) -> dict:
        return {"key": self.key, "name": self.name, "colour": self.colour, "hex": self.hex,
                "position": self.position, "words": ", ".join(self.words), "runs": self.runs,
                "others": self.others}


def hex_of(colour: str) -> str:
    """A silo's colour as "#rrggbb", whether it was kept by name or as hex."""
    c = str(colour or "").strip().lower()
    if re.fullmatch(r"#[0-9a-f]{6}", c):
        return c
    return COLOURS.get(c, COLOURS["slate"])


def clean_colour(value) -> str:
    """A colour as typed or picked: one of `COLOURS` by name, or "#rrggbb"; ValueError otherwise."""
    c = str(value or "").strip().lower()
    if c in COLOURS:
        return c
    if re.fullmatch(r"#?[0-9a-f]{3}", c):
        c = "#" + "".join(ch * 2 for ch in c.lstrip("#"))
    if re.fullmatch(r"#?[0-9a-f]{6}", c):
        return "#" + c.lstrip("#")
    raise ValueError("A colour is one of " + ", ".join(COLOURS) + ", or #rrggbb.")


def _words(text) -> tuple:
    out = []
    for w in re.split(r"[,;\n]+", str(text or "")):
        w = " ".join(w.lower().split())
        if w and w not in out:
            out.append(w[:60])
    return tuple(out[:80])


# ---------------------------------------------------------------------------------------------------------
# the account's silos, read through one helper
# ---------------------------------------------------------------------------------------------------------

_cache: dict[tuple[str, str], tuple[float, list, dict]] = {}
_lock = threading.Lock()
#: How long a read of the silos and their rules is kept in this process. A change made here clears it
#: at once; one made by another process is seen this much later.
TTL = 3.0


def forget(user_id=None, org_id=None) -> None:
    """Drop what this process has read, after a change."""
    with _lock:
        if user_id is None:
            _cache.clear()
        else:
            _cache.pop((str(user_id), str(org_id)), None)


def _read(user_id, org_id) -> tuple[list, dict]:
    who = (str(user_id), str(org_id))
    now = time.monotonic()
    with _lock:
        got = _cache.get(who)
        if got and now - got[0] < TTL:
            return got[1], got[2]
    from .models import Silo, SiloRule

    rows = list(Silo.objects.filter(user_id=who[0], org_id=who[1]).order_by("position", "id"))
    if not rows:
        _seed(*who)
        rows = list(Silo.objects.filter(user_id=who[0], org_id=who[1]).order_by("position", "id"))
    silos = [SiloInfo(key=r.key, name=r.name, colour=r.colour, position=r.position, words=_words(r.words),
                      runs=bool(r.runs), others=bool(r.others)) for r in rows]
    have = {s.key for s in silos}
    rules: dict[str, dict[str, str]] = {k: {} for k in RULE_KINDS}
    for r in SiloRule.objects.filter(user_id=who[0], org_id=who[1]).values("kind", "match", "silo"):
        if r["kind"] in rules and (r["silo"] in have or r["silo"] == EVERY):
            rules[r["kind"]][r["match"]] = r["silo"]
    with _lock:
        _cache[who] = (now, silos, rules)
    return silos, rules


def of(user_id, org_id) -> list[SiloInfo]:
    """The account's silos, in their order. Every account has at least one: the first read of one that
    has none gives it the two everybody starts with (`_seed`)."""
    return list(_read(user_id, org_id)[0])


def of_ds(ds: dict) -> list[SiloInfo]:
    return of(ds["user_id"], ds["org_id"])


def keys(user_id, org_id) -> list[str]:
    return [s.key for s in of(user_id, org_id)]


def rule_map(user_id, org_id) -> dict[str, dict[str, str]]:
    """kind -> match -> silo key, for every rule whose silo is still there."""
    return _read(user_id, org_id)[1]


def by_key(user_id, org_id) -> dict[str, SiloInfo]:
    return {s.key: s for s in of(user_id, org_id)}


def expand(user_id, org_id, silo: str) -> list[str]:
    """A rule's silo as a label: [its key], every key for `EVERY`, [] for none."""
    if silo == EVERY:
        return keys(user_id, org_id)
    return [silo] if silo in by_key(user_id, org_id) else []


def ordered(user_id, org_id, given) -> list[str]:
    """The silo keys of `given` that are still silos, in the account's order."""
    want = {str(k) for k in given or ()}
    return [s.key for s in of(user_id, org_id) if s.key in want]


def chips(user_id, org_id, given) -> list[dict]:
    """A label as the page draws it: each silo's key, name and colour, in the account's order."""
    have = by_key(user_id, org_id)
    return [have[k].chip() for k in ordered(user_id, org_id, given)]


def said(user_id, org_id, given) -> str:
    """A label in words: "Work", "Work and Family", or "not known"."""
    names = [s["name"] for s in chips(user_id, org_id, given)]
    if not names:
        return "not known"
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def listing(user_id, org_id) -> str:
    """The silos by name, for a sentence: "Work, Personal and Family"."""
    return said(user_id, org_id, keys(user_id, org_id)) if of(user_id, org_id) else "none"


def _norm(text) -> str:
    t = " ".join(str(text or "").lower().replace("_", " ").split())
    t = re.sub(r"^(that'?s|it'?s|it is|that is|they'?re|they are|he'?s|she'?s|mark it|make it|put it in|"
               r"move it to|in)\s+", "", t)
    t = re.sub(r"^(the|my)\s+", "", t)
    return re.sub(r"\s+(silo|side)$", "", t).strip(" .!\"'“”")


def find(user_id, org_id, value) -> SiloInfo | None:
    """The silo a word names, by its name or its key, however it was said ("that's family", "Work",
    "s3fa29c1d"), or None when no silo is called that. Never makes one up."""
    t = _norm(value)
    if not t:
        return None
    silos = of(user_id, org_id)
    for s in silos:
        if t == s.key or t == s.name.lower():
            return s
    for s in silos:
        if _norm(s.name) == t:
            return s
    return None


def parse(user_id, org_id, value) -> tuple[list[str] | None, list[str]]:
    """A label as given - a list of names or keys, or one string ("work and family", "both", "none") -
    as (silo keys, the words that named no silo). None for the keys means it said nothing at all."""
    if value is None:
        return None, []
    items = value if isinstance(value, (list, tuple, set)) else [value]
    out: list[str] = []
    missing: list[str] = []
    for one in items:
        text = _norm(one)
        if text in NONE_WORDS:
            continue
        got = find(user_id, org_id, text)
        if got is not None:
            out.append(got.key)
            continue
        if text in ("both", "all", "every silo", "all of them", "everything"):
            silos = keys(user_id, org_id)
            if text != "both" or len(silos) == 2:
                out += silos
                continue
        parts = [p for p in re.split(r"\s*(?:,|\band\b|&|\+)\s*", text) if p]
        if len(parts) > 1:
            sub, miss = parse(user_id, org_id, parts)
            out += sub or []
            missing += miss
            continue
        missing.append(text)
    return ordered(user_id, org_id, out), missing


def unknown_said(user_id, org_id, missing) -> str:
    """Why a label naming no silo was not kept, with the silos there are."""
    names = ", ".join(f"“{m}”" for m in missing)
    return (f"No silo is called {names}. The silos are {listing(user_id, org_id)}; add or rename one in "
            "Settings, Silos. Nothing was changed.")


# ---------------------------------------------------------------------------------------------------------
# the two every account starts with: the one place that names work or personal
# ---------------------------------------------------------------------------------------------------------

#: What placed a contact on a side when the label was fixed (card 1499), as each default silo's words.
WORK_WORDS = ("colleague, co-founder, cofounder, coo, ceo, cto, cfo, cmo, assistant, employee, staff, team, "
              "client, customer, investor, supplier, vendor, lawyer, accountant, contractor, consultant, "
              "manager, recruiter, candidate, board, business")
PERSONAL_WORDS = ("mother, father, mum, mom, mama, dad, papa, parent, parents, brother, sister, sibling, son, "
                  "daughter, child, children, kid, kids, wife, husband, girlfriend, boyfriend, fiance, "
                  "fiancee, ex-partner, ex-wife, ex-husband, family, cousin, aunt, uncle, grandmother, "
                  "grandfather, grandma, grandpa, grandson, granddaughter, niece, nephew, in-law, godfather, "
                  "godmother, friend")
#: The top of the workspace and the side each column was on. Rouh is Petar's work.
COLUMNS = {"work": "work", "rouh": "work", "private": "personal", "personal": "personal"}


def _seed(user_id: str, org_id: str) -> None:
    """Work and Personal, with the keys the fixed labels had, and the rules those labels were worked out
    by, so nothing anybody sees or may see changes the day silos arrive: the columns, the owner's work
    domains, every calendar Synapse keeps with the side it was on, and meetings as work."""
    from django.db import IntegrityError, transaction

    from .models import Silo, SiloRule

    now = time.time()
    try:
        with transaction.atomic():
            Silo.objects.create(user_id=user_id, org_id=org_id, key="work", name="Work", colour="blue", position=0,
                                words=WORK_WORDS, runs=True, others=True, created_at=now, updated_at=now)
            Silo.objects.create(user_id=user_id, org_id=org_id, key="personal", name="Personal", colour="rose",
                                position=1, words=PERSONAL_WORDS, created_at=now, updated_at=now)
    except IntegrityError:
        return      # another thread gave it them first
    rules = [("project", folder, "", side) for folder, side in COLUMNS.items()]
    rules.append(("meetings", "", "", "work"))
    try:
        rules += [("domain", d, "", "work") for d in sorted(_own_work_domains(user_id, org_id))]
        rules += _seed_calendars(user_id, org_id)
    except Exception:  # noqa: BLE001 - fewer rules is only fewer things labelled until they are set
        log.exception("the starting silo rules of %s could not all be worked out", user_id)
    for kind, match, label, silo in rules:
        try:
            with transaction.atomic():
                SiloRule.objects.get_or_create(user_id=user_id, org_id=org_id, kind=kind, match=match,
                                               defaults={"silo": silo, "label": label, "created_at": now})
        except IntegrityError:
            pass
    log.info("silos: %s/%s starts with Work and Personal and %d rules", user_id, org_id, len(rules))


def _own_work_domains(user_id: str, org_id: str) -> set[str]:
    from .meeting_people import PUBLIC_MAIL

    try:
        from . import my_card

        own = my_card.own_addresses(str(user_id), str(org_id))
    except Exception:  # noqa: BLE001 - no work domain known
        own = []
    return {a.rsplit("@", 1)[1].lower() for a in own if "@" in a} - set(PUBLIC_MAIL)


def _seed_calendars(user_id: str, org_id: str) -> list[tuple]:
    """Each calendar Synapse keeps, on the side the fixed label put it: holidays both, birthdays and
    anything called personal personal, an address on a company's domain work, on a public service
    personal. A calendar none of that decides is left for the person to place."""
    from .meeting_people import PUBLIC_MAIL
    from .synapse import db

    if not db.value("SELECT to_regclass('synapse.calendar_sync') IS NOT NULL"):
        return []
    out = []
    for r in db.rows("SELECT DISTINCT c.calendar_id, c.name FROM synapse.calendar_sync c JOIN synapse.dataset d "
                     "ON d.id = c.dataset_id WHERE d.user_id = %s AND d.org_id = %s", (str(user_id), str(org_id))):
        cid, name = str(r["calendar_id"]), " ".join(str(r["name"] or "").split())
        low, lname = cid.lower(), name.lower()
        if "#holiday@" in low or "holiday" in lname:
            side = EVERY
        elif re.search(r"\b(b-?days?|birthdays?|personal|family|private|home)\b", lname):
            side = "personal"
        elif re.fullmatch(r"[^@\s]+@[^@\s]+\.[a-z]{2,}", low) and not low.endswith("calendar.google.com"):
            side = "personal" if low.rsplit("@", 1)[1] in PUBLIC_MAIL else "work"
        else:
            continue
        out.append(("calendar", cid, name, side))
    return out


# ---------------------------------------------------------------------------------------------------------
# changing them, from the Silos page
# ---------------------------------------------------------------------------------------------------------

class Refused(ValueError):
    """A change that was not made, and why, in words for the page."""


def _row(user_id, org_id, key):
    from .models import Silo

    row = Silo.objects.filter(user_id=str(user_id), org_id=str(org_id), key=str(key or "")).first()
    if row is None:
        raise Refused("There is no such silo.")
    return row


def _clean_name(user_id, org_id, name, but: str = "") -> str:
    name = " ".join(str(name or "").split())[:NAME_MOST]
    if not name:
        raise Refused("A silo needs a name.")
    if _norm(name) in NONE_WORDS or _norm(name) in ("both", "all"):
        raise Refused(f"“{name}” already means something else; pick another name.")
    for s in of(user_id, org_id):
        if s.key != but and (s.name.lower() == name.lower() or _norm(s.name) == _norm(name)):
            raise Refused(f"There is already a silo called {s.name}.")
    return name


def add(user_id, org_id, name, colour: str = "") -> SiloInfo:
    from .models import Silo

    have = of(user_id, org_id)
    if len(have) >= MOST:
        raise Refused(f"An account has at most {MOST} silos.")
    name = _clean_name(user_id, org_id, name)
    used = {s.colour for s in have}
    colour = clean_colour(colour) if colour else next((c for c in COLOURS if c not in used), "slate")
    key = "s" + secrets.token_hex(4)
    now = time.time()
    Silo.objects.create(user_id=str(user_id), org_id=str(org_id), key=key, name=name, colour=colour,
                        position=max([s.position for s in have] or [0]) + 1, created_at=now, updated_at=now)
    forget(user_id, org_id)
    return by_key(user_id, org_id)[key]


def change(user_id, org_id, key, *, name=None, colour=None, words=None, runs=None, others=None) -> SiloInfo:
    """Rename, recolour, or change a silo's words or who sees it by default. The key never changes."""
    row = _row(user_id, org_id, key)
    if name is not None:
        row.name = _clean_name(user_id, org_id, name, but=row.key)
    if colour is not None:
        try:
            row.colour = clean_colour(colour)
        except ValueError as exc:
            raise Refused(str(exc)) from None
    if words is not None:
        row.words = ", ".join(_words(words))
    if runs is not None:
        row.runs = bool(runs)
    if others is not None:
        row.others = bool(others)
    row.updated_at = time.time()
    row.save()
    forget(user_id, org_id)
    return by_key(user_id, org_id)[row.key]


def reorder(user_id, org_id, order) -> list[SiloInfo]:
    """The silos in this order, by key; any not named keep their order after the ones that are."""
    from django.db import transaction

    from .models import Silo

    want = [str(k) for k in order or ()]
    rows = list(Silo.objects.filter(user_id=str(user_id), org_id=str(org_id)).order_by("position", "id"))
    rows.sort(key=lambda r: (want.index(r.key) if r.key in want else len(want), r.position, r.id))
    with transaction.atomic():
        for i, r in enumerate(rows):
            if r.position != i:
                r.position = i
                r.save(update_fields=["position"])
    forget(user_id, org_id)
    return of(user_id, org_id)


def move(user_id, org_id, key, by: int) -> list[SiloInfo]:
    """One silo up (-1) or down (+1) the list."""
    order = keys(user_id, org_id)
    if key not in order:
        raise Refused("There is no such silo.")
    i = order.index(key)
    j = max(0, min(len(order) - 1, i + int(by)))
    order.insert(j, order.pop(i))
    return reorder(user_id, org_id, order)


def _datasets(user_id, org_id) -> list[str]:
    from .synapse import db

    if not db.value("SELECT to_regclass('synapse.dataset') IS NOT NULL"):
        return []
    return [str(r["id"]) for r in db.rows("SELECT id FROM synapse.dataset WHERE user_id = %s AND org_id = %s",
                                          (str(user_id), str(org_id)))]


def holding(user_id, org_id, key) -> dict:
    """What is in a silo, counted: Synapse items, Clockwork items, rules, trusted contacts who see it, the
    vault's cards that are for it (`rouh/payments.py`) and the shipping options labelled with it
    (`rouh/shipping.py`), whose situations go wherever they go."""
    from .models import PaymentCard, Reminder, ShippingOption, SiloRule, TrustedContact
    from .synapse import db

    key = str(key)
    ds = _datasets(user_id, org_id)
    items = int(db.value("SELECT count(*) FROM synapse.item WHERE dataset_id = ANY(%s::uuid[]) AND deleted_at IS NULL "
                         "AND %s = ANY(silos)", (ds, key)) or 0) if ds else 0
    clock = sum(1 for s in Reminder.objects.filter(user_id=str(user_id), org_id=str(org_id))
                .exclude(silos=[]).values_list("silos", flat=True) if key in (s or []))
    rules = SiloRule.objects.filter(user_id=str(user_id), org_id=str(org_id), silo=key).count()
    people = sum(1 for s in TrustedContact.objects.filter(user_id=str(user_id), org_id=str(org_id))
                 .exclude(sees=None).values_list("sees", flat=True) if key in (s or []))
    cards = PaymentCard.objects.filter(user_id=str(user_id), org_id=str(org_id), silo=key).count()
    shipping = ShippingOption.objects.filter(user_id=str(user_id), org_id=str(org_id), silo=key).count()
    return {"items": items, "clockwork": clock, "rules": rules, "people": people, "cards": cards,
            "shipping": shipping, "total": items + clock + rules + people + cards + shipping}


def remove(user_id, org_id, key, move_to: str = "") -> dict:
    """Delete a silo. Whatever it still holds moves to `move_to`, which must be another silo whenever it
    holds anything: labels, Clockwork items, rules, who sees it and the cards for it all move, and nothing
    is deleted or left labelled with a silo that is not there. The last silo cannot go."""
    from django.db import transaction

    from .models import PaymentCard, Reminder, ShippingOption, ShippingSituation, SiloRule, TrustedContact
    from .synapse import db

    row = _row(user_id, org_id, key)
    have = keys(user_id, org_id)
    if len(have) <= 1:
        raise Refused("An account keeps at least one silo.")
    held = holding(user_id, org_id, row.key)
    move_to = str(move_to or "")
    if move_to == row.key or (move_to and move_to not in have):
        raise Refused("Pick another silo for what is in it to move to.")
    if held["total"] and not move_to:
        raise Refused(f"{row.name} still holds things: say which silo they move to.")
    uid, oid, old = str(user_id), str(org_id), row.key
    with transaction.atomic():
        ds = _datasets(uid, oid)
        moved = 0
        if ds and move_to:
            moved = db.run(
                "UPDATE synapse.item SET silos = (SELECT coalesce(array_agg(DISTINCT x ORDER BY x), '{}') "
                "FROM unnest(array_replace(silos, %s, %s)) x) WHERE dataset_id = ANY(%s::uuid[]) AND %s = ANY(silos)",
                (old, move_to, ds, old))
        elif ds:
            db.run("UPDATE synapse.item SET silos = array_remove(silos, %s) WHERE dataset_id = ANY(%s::uuid[]) "
                   "AND %s = ANY(silos)", (old, ds, old))
        for r in Reminder.objects.filter(user_id=uid, org_id=oid).exclude(silos=[]):
            if old in (r.silos or []):
                r.silos = _moved(r.silos, old, move_to)
                r.save(update_fields=["silos"])
        for t in TrustedContact.objects.filter(user_id=uid, org_id=oid).exclude(sees=None):
            if old in (t.sees or []):
                t.sees = _moved(t.sees, old, move_to)
                t.revision += 1
                t.save(update_fields=["sees", "revision"])
        for r in SiloRule.objects.filter(user_id=uid, org_id=oid, silo=old):
            if move_to:
                r.silo = move_to
                r.save(update_fields=["silo"])
            else:
                r.delete()
        PaymentCard.objects.filter(user_id=uid, org_id=oid, silo=old).update(silo=move_to)
        ShippingOption.objects.filter(user_id=uid, org_id=oid, silo=old).update(silo=move_to)
        ShippingSituation.objects.filter(user_id=uid, org_id=oid, silo=old).update(silo=move_to)
        row.delete()
    forget(uid, oid)
    return {"held": held, "moved": moved, "to": move_to}


def _moved(given, old, new) -> list[str]:
    out = []
    for k in given or []:
        k = new if k == old else k
        if k and k not in out:
            out.append(k)
    return out


# ---------------------------------------------------------------------------------------------------------
# source rules
# ---------------------------------------------------------------------------------------------------------

def clean_match(kind: str, match) -> str:
    m = " ".join(str(match or "").split())
    if kind in ("domain", "sender", "inbox"):
        m = m.lower().strip("<>")
        if kind == "domain":
            m = m.rsplit("@", 1)[-1].lstrip(".")
            if not re.fullmatch(r"[a-z0-9-]+(\.[a-z0-9-]+)+", m):
                raise Refused("A domain looks like example.com.")
        elif not re.fullmatch(r"[^@\s]+@[^@\s]+\.[a-z]{2,}", m):
            raise Refused("That is not an email address.")
    elif kind == "project":
        m = m.strip("/").lower()
        if not m:
            raise Refused("Which project?")
    elif kind in ("meetings", "slack"):
        m = ""
    elif not m:
        raise Refused("Nothing to match.")
    return m[:300]


def set_rule(user_id, org_id, kind: str, match, silo: str | None, label: str = "") -> dict:
    """Where something comes from decides its silo: a rule set, changed, or (silo "" or None) taken away."""
    from .models import SiloRule

    if kind not in RULE_KINDS:
        raise Refused("A rule is about a " + ", ".join(RULE_KINDS) + ".")
    m = clean_match(kind, match)
    if silo and silo != EVERY and silo not in keys(user_id, org_id):
        raise Refused("There is no such silo.")
    q = SiloRule.objects.filter(user_id=str(user_id), org_id=str(org_id), kind=kind, match=m)
    if not silo:
        q.delete()
    else:
        SiloRule.objects.update_or_create(user_id=str(user_id), org_id=str(org_id), kind=kind, match=m,
                                          defaults={"silo": silo, "label": str(label or "")[:200],
                                                    "created_at": time.time()})
    forget(user_id, org_id)
    return {"kind": kind, "match": m, "silo": silo or ""}


def rules(user_id, org_id) -> list[dict]:
    from .models import SiloRule

    have = set(keys(user_id, org_id))
    return [{"kind": r.kind, "match": r.match, "label": r.label, "silo": r.silo}
            for r in SiloRule.objects.filter(user_id=str(user_id), org_id=str(org_id)).order_by("kind", "match")
            if r.silo in have or r.silo == EVERY]


def of_project(user_id, org_id, folder) -> tuple[str, str]:
    """(silo key, the folder whose rule decided it) for a workspace path: the rule on the deepest project
    or column above it, or ("", "")."""
    got = rule_map(user_id, org_id)["project"]
    parts = [p for p in str(folder or "").strip("/").lower().split("/") if p]
    for n in range(len(parts), 0, -1):
        at = "/".join(parts[:n])
        if at in got:
            return got[at], at
    return "", ""


def of_address(user_id, org_id, address) -> tuple[str, str]:
    """(silo key, why) for an email address: a rule on the sender, then on their domain or one above."""
    a = str(address or "").strip().lower()
    m = re.search(r"[^\s<>\"']+@[^\s<>\"']+", a)
    if not m:
        return "", ""
    a = m.group(0).strip(".,;")
    rm = rule_map(user_id, org_id)
    if a in rm["sender"]:
        return rm["sender"][a], f"the sender {a}"
    domain = a.rsplit("@", 1)[1]
    parts = domain.split(".")
    for i in range(len(parts) - 1):
        d = ".".join(parts[i:])
        if d in rm["domain"]:
            return rm["domain"][d], f"the domain {d}"
    return "", ""


def of_calendar(user_id, org_id, calendar_id) -> tuple[str, str]:
    """(silo key, why) for a calendar: its own rule, else (a calendar that is an address) the rules on
    that address."""
    cid = str(calendar_id or "")
    rm = rule_map(user_id, org_id)
    if cid in rm["calendar"]:
        return rm["calendar"][cid], "its calendar"
    if "@" in cid and not cid.lower().endswith("calendar.google.com"):
        return of_address(user_id, org_id, cid)
    return "", ""


def of_inbox(user_id, org_id, inbox) -> str:
    return rule_map(user_id, org_id)["inbox"].get(str(inbox or "").strip().lower(), "")


def of_drive(user_id, org_id, ids) -> str:
    """The silo of a Drive file, by its shared drive or any folder above it, nearest first."""
    rm = rule_map(user_id, org_id)["drive"]
    return next((rm[str(i)] for i in ids or () if str(i) in rm), "")


def meetings_silo(user_id, org_id) -> str:
    return rule_map(user_id, org_id)["meetings"].get("", "")


def of_relationship(user_id, org_id, words) -> list[str]:
    """The silos whose words what the person said somebody is to them names ("my brother, and our CTO")."""
    text = " ".join(str(words or "").lower().split())
    if not text:
        return []
    out = []
    for s in of(user_id, org_id):
        if any(re.search(r"\b" + re.escape(w) + r"s?\b", text) for w in s.words):
            out.append(s.key)
    return out


def of_chat(user_id, org_id, chat_id) -> tuple[list[str], str]:
    """A chat's label: its task's, or its project's; ([], "") for General and any chat in neither."""
    from .synapse import db

    cid = str(chat_id or "")
    if not cid or not db.value("SELECT to_regclass('public.link') IS NOT NULL"):
        return [], ""
    own = db.row("SELECT src_type, src_id FROM link WHERE rel = 'owns' AND dst_type = 'chat' AND dst_id = %s "
                 "AND src_type IN ('task', 'project') LIMIT 1", (cid,))
    if not own:
        return [], ""
    return of_owner(user_id, org_id, own["src_type"], own["src_id"])


def of_owner(user_id, org_id, kind: str, ident) -> tuple[list[str], str]:
    """A task's or a project's label: the task's own in Synapse when the person set it, else its
    project's rule."""
    from .synapse import db

    if kind == "task":
        t = db.row("SELECT id, number, title, folder FROM task WHERE id::text = %s", (str(ident),))
        if not t:
            return [], ""
        mine = db.row("SELECT i.silos, i.silos_by FROM synapse.item i JOIN synapse.dataset d ON d.id = i.dataset_id "
                      "WHERE d.master AND d.user_id = %s AND d.org_id = %s AND i.source = 'rouh-task' "
                      "AND i.source_key = %s AND i.deleted_at IS NULL LIMIT 1",
                      (str(user_id), str(org_id), "task:" + str(t["id"])))
        name = f"task {t['number']}, {t['title']}" if t.get("number") else f"the task {t['title']}"
        if mine and mine["silos_by"] == BY_PERSON:
            return ordered(user_id, org_id, mine["silos"] or []), name
        key, _at = of_project(user_id, org_id, t["folder"])
        got = expand(user_id, org_id, key)
        return (got, name) if got else ([], "")
    if kind == "project":
        p = db.row("SELECT folder, title FROM object WHERE type = 'project' AND id = %s", (str(ident),))
        if not p:
            return [], ""
        key, _at = of_project(user_id, org_id, p["folder"])
        got = expand(user_id, org_id, key)
        return (got, f"the project {p['title']}") if got else ([], "")
    return [], ""


# ---------------------------------------------------------------------------------------------------------
# who may see what
# ---------------------------------------------------------------------------------------------------------

#: The silos this turn's reader may see, set around work done for somebody limited; None for no limit.
LIMIT: contextvars.ContextVar[frozenset | None] = contextvars.ContextVar("rouh_silo_limit", default=None)


def others(user_id, org_id) -> list[str]:
    """The silos somebody sees until the person says what they see (`Silo.others`)."""
    return [s.key for s in of(user_id, org_id) if s.others]


def for_runs(user_id, org_id) -> frozenset | None:
    """What an unattended run on Rouh itself may see (`Silo.runs`), or None for everything."""
    return limited(user_id, org_id, [s.key for s in of(user_id, org_id) if s.runs])


def limited(user_id, org_id, sees) -> frozenset | None:
    """A reader's limit from what they may see (None for the silos shown to others): the silos of it that
    are still there, or None when that is every silo, which is no limit at all."""
    have = keys(user_id, org_id)
    given = others(user_id, org_id) if sees is None else [str(k) for k in sees or ()]
    got = frozenset(k for k in given if k in have)
    return None if have and got >= set(have) else got


def limit_now() -> frozenset | None:
    """The silos the reader of this turn may see, or None for no limit (Petar himself).

    A turn about somebody else's message is theirs: their contact's `sees`, or the silos shown to others
    for anybody not listed (`mail_turn.MailTurn.sees`). An unattended run on Rouh itself is a process of
    its own, in a checkout of the whole repository, so what holds it is the rule in its brief
    (`run_rule`)."""
    got = LIMIT.get()
    if got is not None:
        return got
    from . import mail_turn

    turn = mail_turn.now()
    if turn is not None and not turn.from_owner:
        return limited(turn.user_id, turn.org_id, getattr(turn, "sees", None))
    return None


def fits(given, limit) -> bool:
    """Whether a thing labelled with silos `given` may be seen by a reader limited to `limit` (None for
    nobody's limit): it shares a silo with them. Not known fits no limit."""
    return limit is None or bool(set(given or ()) & set(limit))


def asker(limit, base: str) -> str:
    """An asker limited to silos, as Synapse keeps it: "in:<key>,<key>:<id>"; the id itself with no limit."""
    base = str(base or "")
    had, base = split(base)
    if had is not None:
        limit = had if limit is None else frozenset(limit) & had
    if limit is None or not base:
        return base
    return "in:" + ",".join(sorted(limit)) + ":" + base


def split(asker_: str) -> tuple[frozenset | None, str]:
    """(the silos, the id) of an asker: (None, id) for one with no limit. Reads the fixed labels' askers
    too ("work:<id>"), which earlier questions were kept with."""
    text = str(asker_ or "")
    if text.startswith("in:"):
        rest = text[3:]
        listed, _, base = rest.partition(":")
        return frozenset(k for k in listed.split(",") if k), base
    for side in ("work", "personal"):
        if text.startswith(side + ":"):
            return frozenset({side}), text[len(side) + 1:]
    return None, text


def principals(asker_: str) -> list[str]:
    """What an asker reads as (`search.readers_for`): themselves and everyone, under each of their silos
    when they are limited (`<key>:<id>`), which an item carries only for the silos it is in."""
    limit, base = split(asker_)
    if limit is not None:
        return [f"{k}:{p}" for k in sorted(limit) for p in (base, "everyone")]
    return [base, "everyone"]


def names_of_keys(given) -> str:
    """Silo keys by name for a trace, where the account is not at hand: the keys' own silos, by name."""
    from .models import Silo

    want = sorted({str(k) for k in given or ()})
    got = dict(Silo.objects.filter(key__in=want).values_list("key", "name")) if want else {}
    return ", ".join(got.get(k) or k for k in want)


def name_of(user_id, org_id, asker_) -> str:
    limit, _base = split(asker_)
    if limit is None:
        return ""
    return said(user_id, org_id, limit) + " only"


# ---------------------------------------------------------------------------------------------------------
# filling it in from the source
# ---------------------------------------------------------------------------------------------------------

#: How many items one UPDATE relabels: each moves its passages' readers too.
BATCH = 400

#: What `fill` can be asked to look at alone: a sync of one source labels only what it brought in.
SOURCES = ("tasks", "events", "meetings", "contacts", "mail", "files", "slack", "layers")
#: Which items each source decides, for clearing a label its source no longer gives.
_DECIDES = {
    "tasks": "source IN ('rouh-task', 'rouh-file', 'rouh-chat', 'rouh-card')",
    "events": "source = 'gcal'",
    "meetings": "kind = 'meeting'",
    "contacts": "kind = 'person'",
    "mail": "source = 'gmail' AND kind = 'mail'",
    "files": "source = 'gmail' AND kind <> 'mail'",
    "slack": "source = 'slack'",
    "layers": "kind = 'layer'",
}


def fill(ds: dict, only=None) -> dict:
    """Every item of a dataset whose source decides its silos, labelled so, unless Petar labelled it: one
    query per kind of source and an UPDATE per change; a label its source gave and no longer gives is
    taken off again. `only` names the sources to look at (`SOURCES`), every one when None. Returns how
    many changed, by why. Never raises."""
    from .synapse import db

    out: dict[str, int] = {}
    looked = [s for s in SOURCES if s in set(only or SOURCES)]
    try:
        wanted = _wanted(ds, set(looked))
        have = {str(r["id"]): r for r in db.rows(
            "SELECT id, silos, silos_by, silos_why FROM synapse.item WHERE dataset_id = %s AND deleted_at IS NULL "
            "AND id = ANY(%s::uuid[])", (ds["id"], list(wanted)))}
        groups: dict[tuple, list[str]] = {}
        for item_id, (got, why, what) in wanted.items():
            row = have.get(item_id)
            if row is None or row["silos_by"] == BY_PERSON:
                continue
            if sorted(row["silos"] or []) == sorted(got) and row["silos_by"] == BY_SOURCE and row["silos_why"] == why:
                continue
            groups.setdefault((tuple(sorted(got)), why), []).append(item_id)
            out[what] = out.get(what, 0) + 1
        for (got, why), ids in groups.items():
            for i in range(0, len(ids), BATCH):
                db.run("UPDATE synapse.item SET silos = %s::text[], silos_by = 'source', silos_why = %s "
                       "WHERE dataset_id = %s AND id = ANY(%s::uuid[]) AND silos_by <> 'person'",
                       (list(got), why[:300], ds["id"], ids[i:i + BATCH]))
        # A rule taken away, or changed so it no longer reaches: what it labelled is not known again.
        decides = " OR ".join(f"({_DECIDES[s]})" for s in looked)
        if decides:
            gone = [str(r["id"]) for r in db.rows(
                "SELECT id FROM synapse.item WHERE dataset_id = %s AND deleted_at IS NULL AND silos_by = 'source' "
                f"AND ({decides}) AND NOT (id = ANY(%s::uuid[]))", (ds["id"], list(wanted)))]
            for i in range(0, len(gone), BATCH):
                db.run("UPDATE synapse.item SET silos = '{}', silos_by = '', silos_why = '' WHERE dataset_id = %s "
                       "AND id = ANY(%s::uuid[]) AND silos_by = 'source'", (ds["id"], gone[i:i + BATCH]))
            if gone:
                out["no longer decided"] = len(gone)
    except Exception:  # noqa: BLE001 - next sync
        log.exception("the silos of %s could not be worked out", ds.get("id"))
        return {"failed": 1}
    if out:
        log.info("silo labels in %s: %s", ds.get("name") or ds.get("id"), out)
    return out


def _wanted(ds: dict, only: set) -> dict[str, tuple[list[str], str, str]]:
    """item id -> (silo keys, why, what kind of source decided it), for every item a source decides."""
    from .synapse import db

    ds_id, uid, oid = ds["id"], str(ds["user_id"]), str(ds["org_id"])
    known = by_key(uid, oid)
    out: dict[str, tuple[list[str], str, str]] = {}
    has_objects = bool(db.value("SELECT to_regclass('public.object') IS NOT NULL"))
    titles = {str(r["folder"]).lower(): str(r["title"]) for r in db.rows(
        "SELECT folder, title FROM object WHERE type = 'project' AND folder <> ''")} if has_objects else {}
    tasks = {str(r["id"]): r for r in db.rows("SELECT id, number, title, folder FROM task")} \
        if db.value("SELECT to_regclass('public.task') IS NOT NULL") else {}

    def project_of(folder) -> tuple[list[str], str]:
        key, at = of_project(uid, oid, folder)
        if not key:
            return [], ""
        return expand(uid, oid, key), f"its project, {titles.get(at) or at.rsplit('/', 1)[-1].capitalize()}"

    # 1. A task or a step: its project's (or column's) rule, unless Petar labelled its item.
    task_items = [] if "tasks" not in only else db.rows(
        "SELECT id, source_key, silos, silos_by FROM synapse.item WHERE dataset_id = %s AND kind = 'task' "
        "AND source = 'rouh-task' AND deleted_at IS NULL", (ds_id,))
    task_silos: dict[str, tuple[list[str], str]] = {}
    for r in task_items:
        tid = str(r["source_key"]).removeprefix("task:")
        t = tasks.get(tid)
        if not t:
            continue
        name = f"task {t['number']}, {t['title']}" if t.get("number") else f"the task {t['title']}"
        if r["silos_by"] == BY_PERSON:
            task_silos[tid] = (list(r["silos"] or []), name)
            continue
        got, why = project_of(t.get("folder"))
        if got:
            out[str(r["id"])] = (got, why, "task")
            task_silos[tid] = (got, name)
    # 2. Everything inside a task takes the task's label; a file in no task, its own project's; a chat or
    #    a card of a project, the project's.
    projects = {str(r["id"]): str(r["folder"]) for r in db.rows(
        "SELECT id, folder FROM object WHERE type = 'project'")} if has_objects and "tasks" in only else {}
    for r in [] if "tasks" not in only else db.rows(
            "SELECT id, source, source_key, meta->>'task' AS task, meta->>'project' AS project FROM synapse.item "
            "WHERE dataset_id = %s AND deleted_at IS NULL AND source IN ('rouh-file', 'rouh-chat', 'rouh-card')",
            (ds_id,)):
        if r["task"] and r["task"] in task_silos:
            got, name = task_silos[r["task"]]
            if got:
                out[str(r["id"])] = (got, f"its task, {name}", "inside a task")
            continue
        if r["source"] == "rouh-file":
            got, why = project_of(str(r["source_key"]).removeprefix("file:"))
        elif r["project"] and r["project"] in projects:
            got, why = project_of(projects[r["project"]])
        else:
            continue
        if got:
            out[str(r["id"])] = (got, why, "file" if r["source"] == "rouh-file" else "project chat")
    # 3. An event: its calendar's.
    names = {str(r["calendar_id"]): str(r["name"] or "") for r in db.rows(
        "SELECT calendar_id, name FROM synapse.calendar_sync WHERE dataset_id = %s", (ds_id,))} \
        if ("events" in only or "meetings" in only) and db.value(
            "SELECT to_regclass('synapse.calendar_sync') IS NOT NULL") else {}
    cal_of: dict[str, tuple[str, str]] = {}
    events: dict[str, list[str]] = {}
    for r in [] if not ({"events", "meetings"} & only) else db.rows(
            "SELECT id, source_key FROM synapse.item WHERE dataset_id = %s AND source = 'gcal' AND deleted_at IS NULL",
            (ds_id,)):
        key = str(r["source_key"])
        cal = key[len("gcal:"):].rsplit(":", 1)[0] if key.startswith("gcal:") else ""
        if cal not in cal_of:
            cal_of[cal] = of_calendar(uid, oid, cal)
        silo, why = cal_of[cal]
        if silo:
            events[str(r["id"])] = expand(uid, oid, silo)
            if "events" in only:
                why = f"its calendar, {names.get(cal) or cal}" if why == "its calendar" else f"its calendar's {why}"
                out[str(r["id"])] = (events[str(r["id"])], why, "event")
    # 4. A meeting: its calendar event's, or the meetings' own rule.
    if "meetings" in only:
        recorded = {str(r["src"]): str(r["dst"]) for r in db.rows(
            "SELECT l.src, l.dst FROM synapse.link l JOIN synapse.item m ON m.id = l.src WHERE l.dataset_id = %s "
            "AND l.type = 'recorded' AND m.kind = 'meeting'", (ds_id,))}
        fallback = meetings_silo(uid, oid)
        for r in db.rows("SELECT id FROM synapse.item WHERE dataset_id = %s AND kind = 'meeting' AND deleted_at IS NULL",
                         (ds_id,)):
            ev = recorded.get(str(r["id"]))
            if ev and events.get(ev):
                out[str(r["id"])] = (events[ev], "its calendar event", "meeting")
            elif fallback:
                out[str(r["id"])] = (expand(uid, oid, fallback), "the rule for meetings", "meeting")
    # 5. A contact: the rules on their addresses, and what Petar said they are to him.
    contacts: dict[str, list[str]] = {}
    if {"contacts", "mail"} & only:
        for r in db.rows("SELECT id, meta->>'relationship' AS rel, meta->'emails' AS emails, silos, silos_by "
                         "FROM synapse.item WHERE dataset_id = %s AND kind = 'person' AND deleted_at IS NULL AND "
                         "(coalesce(meta->>'relationship', '') <> '' OR jsonb_array_length(coalesce(meta->'emails', "
                         "'[]'::jsonb)) > 0 OR silos_by = 'person')", (ds_id,)):
            if r["silos_by"] == BY_PERSON:
                got = list(r["silos"] or [])
                why = ""
            else:
                emails = r["emails"] if isinstance(r["emails"], list) else []
                got, why = _person_silos(uid, oid, r["rel"] or "", emails)
            if got:
                for e in r["emails"] if isinstance(r["emails"], list) else []:
                    contacts.setdefault(str(e).strip().lower(), got)
                if why and "contacts" in only:
                    out[str(r["id"])] = (got, why, "contact")
    # 6. An email: its sender's rule, their domain's, their contact's when they are in one silo, its inbox's.
    if "mail" in only:
        own = {a.lower() for a in _own_addresses(uid, oid)}
        exact = rule_map(uid, oid)["sender"]
        for r in db.rows("SELECT id, meta->>'from' AS sender, meta->'gmail'->>'inbox' AS inbox, meta->'to' AS to_, "
                         "meta->'cc' AS cc FROM synapse.item WHERE dataset_id = %s AND source = 'gmail' AND "
                         "kind = 'mail' AND deleted_at IS NULL", (ds_id,)):
            address = _address(r["sender"])
            got, why = [], ""
            if address and address not in own:
                silo, why = of_address(uid, oid, address)
                if silo:
                    got, why = expand(uid, oid, silo), f"its sender, by the rule on {why}"
                elif len(contacts.get(address, [])) == 1:
                    got, why = contacts[address], f"its sender's contact, {address}"
            elif address and address in exact:
                # One of the owner's own addresses, put in a silo on their card (`person_addresses`):
                # what they send from it is in that silo.
                got, why = expand(uid, oid, exact[address]), f"its sender, by the rule on the address {address}"
            if not got:
                # Mail to an address put in a silo, the owner's own or anybody's, is in that silo.
                for line in _lines(r["to_"]) + _lines(r["cc"]):
                    to = _address(line)
                    if to and to in exact and expand(uid, oid, exact[to]):
                        got, why = expand(uid, oid, exact[to]), f"sent to {to}, by the rule on that address"
                        break
            if not got and r["inbox"]:
                silo = of_inbox(uid, oid, r["inbox"])
                if silo:
                    got, why = expand(uid, oid, silo), f"its inbox, {r['inbox']}"
            if got:
                out[str(r["id"])] = (got, why, "email")
    # 7. An email's file: its email's label, once the email has one.
    for r in [] if "files" not in only else db.rows(
            "SELECT f.id, e.id AS mail, e.silos, e.title FROM synapse.item f JOIN synapse.item e "
            "ON e.dataset_id = f.dataset_id AND e.source_key = f.meta->'attached_to'->>0 AND e.kind = 'mail' "
            "WHERE f.dataset_id = %s AND f.source = 'gmail' AND f.kind <> 'mail' AND f.deleted_at IS NULL", (ds_id,)):
        got = out[str(r["mail"])][0] if str(r["mail"]) in out else list(r["silos"] or [])
        if got:
            out[str(r["id"])] = (got, f"its email, {str(r['title'])[:80]}", "email file")
    # 8. Slack (`rouh/slack.py`): the rule for Slack, and Work when there is none (Petar, 16 October 2026:
    #    his Slack workspace is his company's).
    if "slack" in only:
        rule = rule_map(uid, oid).get("slack", {}).get("", "")
        got, why = (expand(uid, oid, rule), "the rule for Slack") if rule else (
            (["work"], "Slack, which is work unless a rule for Slack says otherwise") if "work" in known else ([], ""))
        if got:
            for r in db.rows("SELECT id FROM synapse.item WHERE dataset_id = %s AND source = 'slack' "
                             "AND deleted_at IS NULL", (ds_id,)):
                out[str(r["id"])] = (got, why, "slack")
    # 9. A layer made only from one silo's things is in that silo: what every one of them shares.
    built: dict[str, list[set]] = {}
    for r in [] if "layers" not in only else db.rows(
            "SELECT l.src AS layer, s.id, s.silos FROM synapse.link l JOIN synapse.item s ON s.id = l.dst "
            "JOIN synapse.item y ON y.id = l.src AND y.dataset_id = l.dataset_id WHERE l.dataset_id = %s "
            "AND l.type = 'built_from' AND y.kind = 'layer' AND y.deleted_at IS NULL", (ds_id,)):
        now = out[str(r["id"])][0] if str(r["id"]) in out else list(r["silos"] or [])
        built.setdefault(str(r["layer"]), []).append(set(now))
    for layer, sets in built.items():
        shared = set.intersection(*sets) if sets else set()
        if shared:
            got = [k for k in known if k in shared]
            out[layer] = (got, f"what it is made from, all {said(uid, oid, got)}", "layer")
    return {k: ([x for x in v[0] if x in known], v[1], v[2]) for k, v in out.items() if any(x in known for x in v[0])}


def _lines(value) -> list[str]:
    """An email's To or Cc as kept in its meta, a list or one line, as the addresses written in it."""
    if isinstance(value, list):
        return [str(v) for v in value]
    return [p for p in str(value or "").split(",") if p.strip()]


def _address(text) -> str:
    m = re.search(r"[^\s<>\"',;]+@[^\s<>\"',;]+", str(text or ""))
    return m.group(0).lower().strip(".") if m else ""


def _own_addresses(user_id, org_id) -> list[str]:
    try:
        from . import my_card

        return my_card.own_addresses(str(user_id), str(org_id))
    except Exception:  # noqa: BLE001 - none known
        return []


def _person_silos(user_id, org_id, relationship: str, emails) -> tuple[list[str], str]:
    """A contact's silos from Petar's own words on them and the rules on their addresses: (keys, why)."""
    words = " ".join(str(relationship or "").split())
    got = of_relationship(user_id, org_id, words)
    because = f"your words on them: “{words[:120]}”" if got else ""
    for e in emails or ():
        silo, why = of_address(user_id, org_id, e)
        more = [k for k in expand(user_id, org_id, silo) if k not in got]
        if more:
            got += more
            because = because or f"the rule on {why}"
    return ordered(user_id, org_id, got), because


def set_item(ds: dict, item_id: str, value, *, by: str = BY_PERSON, why: str = "") -> dict:
    """Label one item, as Petar said: {"ok", "item", "silos", "was", "carried"}; a task carries its
    contents with it (everything inside it takes its label at once, unless he labelled that too). A
    label that names a silo there is none of is refused, with the silos there are: no silo is made up.
    An empty label from Petar is not known again, which hands it back to the sources and the X-ray."""
    from .synapse import db

    uid, oid = str(ds["user_id"]), str(ds["org_id"])
    got, missing = parse(uid, oid, value)
    if missing:
        return {"ok": False, "why": unknown_said(uid, oid, missing)}
    got = got or []
    item = db.row("SELECT id, kind, title, source, source_key, silos FROM synapse.item WHERE dataset_id = %s "
                  "AND id = %s::uuid AND deleted_at IS NULL", (ds["id"], str(item_id)))
    if item is None:
        return {"ok": False, "why": "No item matches that."}
    if not why and by == BY_PERSON:
        from . import owner

        why = owner.say("‹Owner› said so", uid)
    if not got and by == BY_PERSON:
        db.run("UPDATE synapse.item SET silos = '{}', silos_by = '', silos_why = '' WHERE id = %s", (item["id"],))
    else:
        db.run("UPDATE synapse.item SET silos = %s::text[], silos_by = %s, silos_why = %s WHERE id = %s",
               (got, by, why[:300], item["id"]))
    carried = 0
    if item["kind"] == "task" and item["source"] == "rouh-task":
        fill(ds, ("tasks", "layers"))
        carried = int(db.value("SELECT count(*) FROM synapse.item WHERE dataset_id = %s AND deleted_at IS NULL "
                               "AND meta->>'task' = %s AND silos = %s::text[]",
                               (ds["id"], str(item["source_key"])[5:], sorted(got))) or 0) if got else 0
    elif not got and by == BY_PERSON:
        fill(ds)
    return {"ok": True, "item": str(item["id"]), "title": item["title"], "silos": got,
            "was": list(item["silos"] or []), "carried": carried,
            "said": said(uid, oid, got), "was_said": said(uid, oid, item["silos"] or [])}


def refill(user_id, org_id) -> None:
    """Every dataset of the account labelled again from its sources, after a change on the Silos page. On
    a thread of its own: a first fill of a big Master takes a few seconds."""
    def go():
        from django.db import close_old_connections

        from .synapse import db

        try:
            for ds in db.rows("SELECT * FROM synapse.dataset WHERE user_id = %s AND org_id = %s AND master",
                              (str(user_id), str(org_id))):
                fill(ds)
        except Exception:  # noqa: BLE001 - the ten-minute sync does it next
            log.exception("the silos of %s could not be filled again", user_id)
        finally:
            close_old_connections()

    threading.Thread(target=go, name="silos-refill", daemon=True).start()


def item_view(user_id, org_id, row: dict) -> dict:
    """An item's label as the lab draws it: its chips, who set it and why, and every silo to choose from."""
    return {"silos": ordered(user_id, org_id, row.get("silos") or []),
            "silo_chips": chips(user_id, org_id, row.get("silos") or []),
            "silos_by": row.get("silos_by") or "", "silos_why": row.get("silos_why") or "",
            "silos_all": [s.chip() for s in of(user_id, org_id)]}


# ---------------------------------------------------------------------------------------------------------
# the workspace beyond what was granted by name
# ---------------------------------------------------------------------------------------------------------

def run_silos(user_id, org_id, run_ids) -> dict[str, list[str]]:
    """Each job's silos, from the task its chat (or itself) belongs to: run id -> keys ([] when no task or
    project says). Reads Rouh's own links: a run came from a chat, and a task or a project owns a chat."""
    from .synapse import db

    ids = [str(i) for i in run_ids or () if i]
    if not ids:
        return {}
    rows = db.rows(
        "WITH r AS (SELECT unnest(%s::text[]) AS run), "
        "own AS (SELECT r.run, coalesce(t1.folder, t2.folder, p.folder) AS folder FROM r "
        "  LEFT JOIN link d ON d.src_type = 'task' AND d.rel = 'owns' AND d.dst_type = 'run' AND d.dst_id = r.run "
        "  LEFT JOIN task t1 ON t1.id::text = d.src_id "
        "  LEFT JOIN link c ON c.src_type = 'run' AND c.rel = 'from' AND c.dst_type = 'chat' AND c.src_id = r.run "
        "  LEFT JOIN link o ON o.dst_type = 'chat' AND o.rel = 'owns' AND o.dst_id = c.dst_id "
        "       AND o.src_type IN ('task', 'project') "
        "  LEFT JOIN task t2 ON o.src_type = 'task' AND t2.id::text = o.src_id "
        "  LEFT JOIN object p ON o.src_type = 'project' AND p.id = o.src_id) "
        "SELECT run, array_agg(DISTINCT folder) FILTER (WHERE folder IS NOT NULL) AS folders FROM own GROUP BY run",
        (ids,))
    out: dict[str, list[str]] = {i: [] for i in ids}
    for r in rows:
        got = {k for f in r["folders"] or [] for k in expand(user_id, org_id, of_project(user_id, org_id, f)[0])}
        out[str(r["run"])] = ordered(user_id, org_id, got)
    return out


def _off_limits(user_id, org_id, limit) -> list[str]:
    """The workspace folders whose rule puts them in a silo outside `limit`."""
    from . import workspace_repo

    return sorted(f"{workspace_repo.in_run(m)}/" for m, k in rule_map(user_id, org_id)["project"].items()
                  if limit is not None and k not in limit)


def job_rule(user_id, org_id, limit, name: str = "") -> str:
    """The rule a job started for somebody limited to some silos works under, said in its brief."""
    if limit is None:
        return ""
    whom = name or "the person this job is for"
    seen = said(user_id, org_id, limit) if limit else "nothing"
    rest = [s.name for s in of(user_id, org_id) if s.key not in limit]
    where = ", ".join(_off_limits(user_id, org_id, limit)) or "nothing in particular"
    return _owner_say(
        f"\n\nThis job is done for {whom}, who may see only ‹owner›'s {seen}, never anything of ‹his› "
        f"{', '.join(rest) or 'other silos'} (‹his› silos, Settings, Silos). Do not open, read, quote or copy "
        f"anything under {where}, or anything else about the rest of ‹his› life, and leave it out of what you "
        "write and say. If the request needs it, stop and say so in your last message.", user_id)


def run_rule(user_id, org_id) -> str:
    """For an unattended run that works on Rouh itself (the nightly runs): what it may see, in its brief."""
    limit = for_runs(user_id, org_id)
    if limit is None:
        return ""
    seen = said(user_id, org_id, limit) if limit else "nothing of ‹his› life"
    where = ", ".join(f"`{w}`" for w in _off_limits(user_id, org_id, limit))
    return _owner_say(
        f"\n\nYou are limited to ‹owner›'s {seen} (‹his› silos, Settings, Silos): never open, read, quote or "
        f"copy anything under {where or 'a folder of another silo'}, or any Synapse item outside "
        f"{seen} or not known, and keep the rest of ‹his› life out of everything you write, commit and "
        "report. A test world copies the workspace: leave those folders alone there too.", user_id)


def _owner_say(text: str, user_id) -> str:
    """A worker's brief leaves Rouh with the owner's marks filled in (`rouh/owner.py`)."""
    from . import owner

    return owner.say(text, user_id)


__all__ = ["BY_MODEL", "BY_PERSON", "BY_SOURCE", "COLOURS", "LIMIT", "RULE_KINDS", "Refused", "SOURCES",
           "SiloInfo", "add", "asker", "by_key", "change", "chips", "clean_colour", "fill", "find", "fits",
           "for_runs", "forget", "hex_of", "holding", "item_view", "job_rule", "keys", "limit_now", "limited",
           "listing", "meetings_silo", "move", "name_of", "of", "of_address", "of_calendar", "of_chat",
           "of_drive", "of_ds", "of_inbox", "of_owner", "of_project", "of_relationship", "ordered", "others",
           "parse", "principals", "refill", "remove", "reorder", "rule_map", "rules", "run_rule", "run_silos",
           "said", "set_item", "set_rule", "split", "unknown_said"]
