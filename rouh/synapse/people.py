"""People in Synapse: items of kind 'person', matched by their identifiers (3 October 2026).

Petar's decisions that day, each kept here:

- **One model.** A person is a `synapse.item` of kind `person`, with what a
  person needs in `meta`, checked against `kinds.REGISTRY`. No table of people.
- **Matched by identifiers, never by name alone.** `synapse.identity` maps
  every address, phone number, name and handle to one person. Addresses are
  kept lower case; phone numbers in E.164 where that can be worked out (a
  number written nationally, starting with one 0, is read in the installation's
  country, `ROUH_PHONE_COUNTRY`); names lower case with the accents off. Two cards that share
  an address or a phone number are one person; two people who share only a
  name are kept apart and flagged as likely the same (`meta.likely_same`).
- **Readers are people.** A reader, an owner, an asker or a map's viewer is a
  person item's id, or `everyone`. A name typed into the lab is turned into one
  here (`reader_id`).
- **Where people come from** (`meta.origin`): `icloud` for people with a card
  in iCloud, the card itself in `meta.icloud` (`contacts.py`), which an edit
  writes back to iCloud and the phone; `synapse` for people met in an item who
  matched nobody, who never reach the phone.
- **Scope.** Every dataset keeps its own people, in itself (`home_id` is where
  a dataset's people live). Synapse Master's are Rouh's contacts. A dataset made
  before 4 October 2026 could resolve against a separate people set
  (`people_id`); none does now.
- **How much a person matters** (`meta.value`), from their links, by code
  (`value`), and used as the walk's prior for a person (`walk.prior`).
- **No model call for a person** until there is something to read: importing
  or making a person writes words only; its passage is embedded once something
  links to it (`linked`).

Rouh's contacts are the people of Synapse Master since 4 October 2026, kept two
ways with iCloud (`contacts.py`); the old copy of the cards, and the one people
set they were imported into, are gone.
"""
from __future__ import annotations

import logging
import math
import re
import unicodedata
from datetime import datetime, timezone

from django.db import IntegrityError

from ..config import _env
from . import db, kinds, text as tx
from .db import Json

log = logging.getLogger("rouh.synapse.people")

UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
EVERYONE = "everyone"
#: The installation's country calling code, for a phone number written nationally (`ROUH_PHONE_COUNTRY`, digits
#: only, such as "44"). Blank, a national number is kept as its digits, never read as anybody's country: it was
#: Bulgaria's, written here, until 20 October 2026.
HOME_COUNTRY = re.sub(r"\D", "", _env("ROUH_PHONE_COUNTRY"))


# ---------------------------------------------------------------------------------------
# normalising what identifies somebody
# ---------------------------------------------------------------------------------------

def norm_email(value) -> str:
    v = str(value or "").strip().strip("<>").strip()
    if v.lower().startswith("mailto:"):
        v = v[7:]
    v = v.lower()
    return v if re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", v) else ""


def norm_phone(value) -> str:
    """E.164 (+447700900123) where it can be worked out, otherwise the digits alone."""
    s = str(value or "").strip()
    if not s:
        return ""
    s = re.split(r"(?i)\b(?:ext|x)\b\.?", s)[0]
    plus = s.lstrip().startswith("+")
    digits = re.sub(r"\D", "", s)
    if len(digits) < 6:
        return ""
    if plus:
        return "+" + digits
    if digits.startswith("00"):
        return "+" + digits[2:]
    if not HOME_COUNTRY:
        return digits
    if digits.startswith("0"):
        return "+" + HOME_COUNTRY + digits[1:]
    if digits.startswith(HOME_COUNTRY) and len(digits) >= 11:
        return "+" + digits
    return digits


def norm_name(name) -> str:
    """Accents off, lower case, punctuation as spaces (as migration 0066 wrote them)."""
    text = unicodedata.normalize("NFKD", str(name or ""))
    text = "".join(c for c in text if not unicodedata.combining(c)).lower()
    return " ".join(re.sub(r"[^\w\s]", " ", text).split())


#: A first name's short forms, as people write them in Slack and in meetings (Tomek is Tomasz). Each
#: line is one name and its short forms; written accent-free and lower case, as `norm_name` gives them.
NICKNAMES = """
maciej maciek
jakub kuba
bartosz bartek
tomasz tomek
wojciech wojtek
krzysztof krzys
lukasz lukas
pawel pawelek
michal michalek
malgorzata gosia
katarzyna kasia
aleksandra ola
joanna asia
agnieszka aga
aleksander olek alex alek
alexander alex alek sasha
aleksandar sasho alex
robert bob rob bobby
william bill will
michael mike mick
thomas tom tommy
daniel dan danny
david dave
james jim jimmy
joseph joe
richard rick dick
christopher chris
nicholas nick
samuel sam sammy
nikola niki nik
katherine kate kathy
elizabeth liz beth
georgi gosho
dimitar mitko
ivaylo ivo
petar pepi pesho
kiril kiro
konstantin kosta kostadin
"""


def _nicknames() -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for line in NICKNAMES.strip().splitlines():
        words = line.split()
        for w in words:
            out.setdefault(w, set()).update(words)
    return out


_NICK = _nicknames()


def name_forms(name) -> set[str]:
    """A name as it is written with accents off (`norm_name`), and with its first name in each of its
    short or long forms: "Tomek Wisniewski" for "Tomasz Wiśniewski". One word gives itself alone."""
    n = norm_name(name)
    words = n.split()
    if len(words) < 2:
        return {n} if n else set()
    return {" ".join([first] + words[1:]) for first in (_NICK.get(words[0]) or {words[0]})} | {n}


def owner_name_of(ds: dict) -> str:
    """What a dataset calls its own person: the name it was made with, else its owner's account's name,
    else "" (nobody is known; the caller says "the owner"). Never a name written in the code."""
    name = " ".join(str(ds.get("owner_name") or "").split())
    if name:
        return name
    try:
        from .. import owner

        found = owner.of(ds.get("user_id"))
    except Exception:  # noqa: BLE001 - a name is only how the owner is shown
        found = None
    return (found.name if found else "") or ""


def handle_of(name) -> str:
    """The short word the lab addresses somebody by: a name's first word, lower case."""
    word = (str(name or "")).strip().split(" ")[0].split("@")[0].lower()
    return "".join(ch for ch in word if ch.isalnum() or ch in "-_")


def looks_like_phone(text) -> bool:
    t = str(text or "").strip()
    return bool(t) and "@" not in t and bool(re.match(r"^\+?[\d\s().\-/]{6,}$", t))


# ---------------------------------------------------------------------------------------
# where a dataset's people live
# ---------------------------------------------------------------------------------------

def home_id(ds: dict) -> str:
    return str(ds.get("people_id") or ds["id"])


def home(ds: dict) -> dict:
    if not ds.get("people_id"):
        return ds
    return db.row("SELECT * FROM synapse.dataset WHERE id = %s", (str(ds["people_id"]),)) or ds


def me(ds: dict) -> str:
    """The dataset's own person, made the first time it is asked for."""
    if ds.get("me_id"):
        return str(ds["me_id"])
    h = home(ds)
    pid = str(h["me_id"]) if h.get("me_id") and h["id"] != ds["id"] else None
    if not pid:
        key = handle_of(owner_name_of(ds)) or "me"
        pid = find(home_id(ds), "handle", key)
        if not pid:
            person = create(h, name=owner_name_of(ds) or "the owner", origin="synapse", handle=key, readers=[EVERYONE],
                            why="the dataset's own person", owner="")
            pid = person["id"]
            db.run("UPDATE synapse.item SET owner = %s WHERE id = %s", (pid, pid))
        db.run("UPDATE synapse.dataset SET me_id = %s WHERE id = %s AND me_id IS NULL", (pid, h["id"]))
    db.run("UPDATE synapse.dataset SET me_id = %s WHERE id = %s", (pid, ds["id"]))
    ds["me_id"] = pid
    return pid


# ---------------------------------------------------------------------------------------
# identities
# ---------------------------------------------------------------------------------------

def find(scope: str, type_: str, value: str) -> str | None:
    """The live person an identifier belongs to in this scope, by its id."""
    if not value:
        return None
    got = db.row("SELECT x.item_id FROM synapse.identity x JOIN synapse.item i ON i.dataset_id = x.scope_id "
                 "AND i.id = x.item_id WHERE x.scope_id = %s AND x.type = %s AND x.value = %s AND i.deleted_at IS NULL "
                 "ORDER BY i.stored_at LIMIT 1", (str(scope), type_, value))
    return got["item_id"] if got else None


def find_all(scope: str, type_: str, value: str) -> list[str]:
    return [r["item_id"] for r in db.rows(
        "SELECT DISTINCT x.item_id, i.stored_at FROM synapse.identity x JOIN synapse.item i ON i.dataset_id = x.scope_id "
        "AND i.id = x.item_id WHERE x.scope_id = %s AND x.type = %s AND x.value = %s AND i.deleted_at IS NULL "
        "AND i.kind = 'person' ORDER BY i.stored_at", (str(scope), type_, value))] if value else []


def add_identity(scope: str, pid: str, type_: str, value: str, shown: str = "", source: str = "") -> str:
    """'added', 'had', or the id of the other person the identifier already belongs to."""
    if not value:
        return "had"
    other = find(scope, type_, value) if type_ in ("email", "phone", "handle", "slack") else None
    if other and other != pid:
        return other
    got = db.value("INSERT INTO synapse.identity (scope_id, item_id, type, value, shown, source) VALUES "
                   "(%s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING RETURNING id",
                   (str(scope), pid, type_, value, (shown or value)[:300], source[:300]))
    return "added" if got else "had"


def kept_off(scope: str, pid: str, type_: str, value: str) -> bool:
    """Whether the owner took this identifier off this person (`aka.unlink`, `meta.unlinked`), so nothing
    done by code puts it back: a Slack member tied again, a name met again with their address."""
    if not value or not pid:
        return False
    return bool(db.value("SELECT 1 FROM synapse.item WHERE dataset_id = %s AND id = %s::uuid AND "
                         "meta->'unlinked' @> %s::jsonb", (str(scope), str(pid), Json([{"type": type_, "value": value}]))))


def identities(scope: str, pid: str) -> list[dict]:
    return db.rows("SELECT type, value, shown, source, made_at FROM synapse.identity WHERE scope_id = %s AND item_id = %s "
                   "ORDER BY CASE type WHEN 'email' THEN 0 WHEN 'phone' THEN 1 WHEN 'slack' THEN 2 WHEN 'handle' THEN 3 "
                   "ELSE 4 END, value",
                   (str(scope), pid))


# ---------------------------------------------------------------------------------------
# a person item
# ---------------------------------------------------------------------------------------

def person_text(meta: dict, owner_name: str = "the owner") -> str:
    """The person's searchable text, made by code from what is known about them."""
    lines = [meta.get("name") or ""]
    if meta.get("organisation"):
        lines.append(f"Organisation: {meta['organisation']}")
    if meta.get("emails"):
        lines.append("Email: " + ", ".join(meta["emails"]))
    if meta.get("phones"):
        lines.append("Phone: " + ", ".join(meta["phones"]))
    if meta.get("birthday"):
        lines.append(f"Birthday: {meta['birthday']}")
    if meta.get("relationship"):
        lines.append(f"Who they are to {owner_name}: {meta['relationship']}")
    if meta.get("research"):
        lines.append("Online research:\n" + meta["research"])
    return "\n".join(x for x in lines if x).strip()


def write_words(scope: str, pid: str, title: str, body: str) -> int:
    """The person's passages and their words, with no vector: words cost nothing (D24)."""
    from . import datasets, ingest

    s = datasets.settings(db.row("SELECT * FROM synapse.dataset WHERE id = %s", (str(scope),)) or {})
    db.run("DELETE FROM synapse.passage WHERE dataset_id = %s AND item_id = %s", (str(scope), pid))
    return ingest.write_passages(str(scope), pid, title, body, s)


def create(scope_ds: dict, *, name: str, origin: str, emails=(), phones=(), handle: str = "", readers=None,
           extra: dict | None = None, source: str = "synapse", source_key: str = "", owner: str | None = None,
           why: str = "", made_from: str = "", said_at=None, written: dict | None = None) -> dict:
    """A new person item in a scope, with its identifiers. No model call (decision 10)."""
    scope = str(scope_ds["id"])
    name = " ".join(str(name or "").split())[:200] or (list(emails) + list(phones) + ["Someone"])[0]
    emails = [e for e in dict.fromkeys(norm_email(e) for e in emails) if e]
    phones = [p for p in dict.fromkeys(norm_phone(p) for p in phones) if p]
    meta = {"origin": origin, "name": name, "emails": emails, "phones": phones, "made_by": "code",
            "made_why": why or ("met in an item, matching nobody" if origin == "synapse" else "imported")}
    if handle:
        meta["handle"] = handle
    if made_from:
        meta["made_from"] = str(made_from)
    meta.update(extra or {})
    problems = kinds.check("person", meta)
    if problems:
        raise ValueError(" ".join(problems))
    key = source_key or ("email:" + emails[0] if emails else "phone:" + phones[0] if phones else "name:" + norm_name(name))
    owner = owner if owner is not None else str(scope_ds.get("me_id") or "")
    body = person_text(meta, scope_ds.get("owner_name") or "the owner")
    # One transaction: the person and their identifiers appear together, so an item stored at the same
    # moment (an import) that waits on the person's key finds them by address once it is let through.
    with db.atomic():
        return _create(scope, scope_ds, name=name, emails=emails, phones=phones, handle=handle, readers=readers,
                       source=source, key=key, owner=owner, body=body, meta=meta, why=why, origin=origin,
                       said_at=said_at, written=written)


def _create(scope, scope_ds, *, name, emails, phones, handle, readers, source, key, owner, body, meta, why, origin,
            said_at, written) -> dict:
    item = db.row(
        "INSERT INTO synapse.item (dataset_id, kind, source, source_key, title, raw, body, said_at, tier, tier_why, "
        "sensitivity, owner, meta, status) VALUES (%s, 'person', %s, %s, %s, %s, %s, %s, 1, 'a person', %s, %s, "
        "%s::jsonb, 'ready') RETURNING *",
        (scope, source, key[:300], name, body, body, said_at, "private" if origin == "icloud" else "normal",
         owner, Json(meta)))
    pid = item["id"]
    from . import ingest
    ingest.set_readers(scope, pid, readers or [EVERYONE])
    write_words(scope, pid, name, body + " " + tx.other_alphabet(name))
    src = why or ("met in an item" if origin == "synapse" else "imported")
    for e in emails:
        add_identity(scope, pid, "email", e, e, src)
    for p in phones:
        add_identity(scope, pid, "phone", p, (written or {}).get(p, p), src)
    add_identity(scope, pid, "name", norm_name(name), name, src)
    if handle and add_identity(scope, pid, "handle", handle, handle, src) != "added":
        meta.pop("handle", None)
        db.run("UPDATE synapse.item SET meta = meta - 'handle' WHERE id = %s", (pid,))
    return item


def get(scope: str, pid: str) -> dict | None:
    if not pid or not UUID.match(str(pid)):
        return None
    return db.row("SELECT * FROM synapse.item WHERE dataset_id = %s AND id = %s::uuid AND kind = 'person'",
                  (str(scope), str(pid)))


def set_meta(pid: str, changes: dict, drop: tuple = ()) -> None:
    sql = "UPDATE synapse.item SET meta = (meta || %s::jsonb)"
    for key in drop:
        sql += f" - '{key}'"
    db.run(sql + ", updated_at = now() WHERE id = %s", (Json(changes), pid))


def flag_same_name(scope: str, pid: str) -> list[str]:
    """Others in the scope with this person's name, accents off and a first name's short form the same as its
    long one (`name_forms`: Tomek is Tomasz): likely the same, never merged on it. A pair he said are two
    people (`not_same`) is never flagged again."""
    names = [r["value"] for r in db.rows("SELECT value FROM synapse.identity WHERE scope_id = %s AND item_id = %s "
                                         "AND type = 'name'", (str(scope), pid))]
    held = db.value("SELECT meta->'not_same' FROM synapse.item WHERE id = %s", (pid,)) or []
    apart = {str(x) for x in held} if isinstance(held, list) else set()
    others: dict[str, str] = {}
    for n in names:
        if len(n.split()) < 2:
            continue  # a first name alone says too little even to flag
        for form in name_forms(n):
            for other in set(find_all(scope, "name", form)) - {pid} - apart:
                others.setdefault(other, "the same name, and no address or phone number in common" if form == n else
                                  f"the same name with {form.split()[0].title()} for {n.split()[0].title()}, "
                                  "and no address or phone number in common")
    for other, why in sorted(others.items()):
        _note_same(pid, other, why)
    return sorted(others)


def _note_same(a: str, b: str, why: str) -> bool:
    """Both people flagged as likely the same; true when that is new."""
    new = False
    for x, y in ((a, b), (b, a)):
        got = db.value("SELECT meta->'likely_same' FROM synapse.item WHERE id = %s", (x,)) or []
        if isinstance(got, str):
            import json
            got = json.loads(got)
        if any(str(e.get("id")) == str(y) for e in got if isinstance(e, dict)):
            continue
        set_meta(x, {"likely_same": got + [{"id": str(y), "why": why}]})
        new = True
    return new


# ---------------------------------------------------------------------------------------
# his pick: the same person, or two (22 October 2026)
# ---------------------------------------------------------------------------------------
#
# Petar: "Never merge two people on a name alone when it is uncertain: queue those for Petar's pick." Two
# people flagged as likely the same (`likely_same`) wait on each other's card in Synapse for his answer:
# the same person, which merges the second into the first (`merge`), or two people (`not_same`), which
# takes the flag off and keeps it off.

def merge(ds: dict, keep: str, gone: str, *, by: str = "page") -> dict:
    """`gone` is `keep`: every identifier and link of `gone` moved to `keep`, and `gone` kept as `keep`'s
    alias (`alias_of`) and out of every search. {ok, moved: {identities, links}, kept} or {ok: False, why}.
    Which of the two is kept is `survivor`'s, so `kept` may be `gone`."""
    order = survivor(ds, keep, gone)
    if order.get("why"):
        return {"ok": False, "why": order["why"]}
    return fold(ds, order["keep"], order["gone"], by=by)


def survivor(ds: dict, keep: str, gone: str) -> dict:
    """Which of two people a merge keeps: {keep, gone}, or {why} when they cannot be merged. The dataset's own
    person is always kept; else the one with a card in iCloud, so the card stays theirs; else the one with an
    address or a phone number, which is the contact, a name met in an item being what joins it."""
    scope = home_id(ds)
    a, b = get(scope, keep), get(scope, gone)
    if not a or not b or a.get("deleted_at") is not None or b.get("deleted_at") is not None or keep == gone:
        return {"why": "Both people must be there, and two of them."}
    if str(gone) == str(ds.get("me_id") or ""):
        keep, gone, a, b = gone, keep, b, a
    def addressed(p) -> bool:
        return bool(db.value("SELECT 1 FROM synapse.identity WHERE scope_id = %s AND item_id = %s AND type IN "
                             "('email', 'phone')", (scope, p["id"])))
    if addressed(b) and not addressed(a) and not (a.get("meta") or {}).get("icloud") \
            and str(keep) != str(ds.get("me_id") or ""):
        # The one with an address is the contact; a name met in an item is what joins it.
        keep, gone, a, b = gone, keep, b, a
    if (b.get("meta") or {}).get("icloud"):
        if (a.get("meta") or {}).get("icloud"):
            return {"why": "Both have a card in iCloud: merge the two cards on the phone, and they "
                           "are one person here too."}
        # The one with a card in iCloud is the one kept, so the card stays theirs.
        keep, gone, a, b = gone, keep, b, a
    return {"keep": str(keep), "gone": str(gone)}


def fold(ds: dict, keep: str, gone: str, *, by: str = "page") -> dict:
    """`gone` folded into `keep`, exactly that way round (`merge` picks which with `survivor`)."""
    scope = home_id(ds)
    a, b = get(scope, keep), get(scope, gone)
    if not a or not b or a.get("deleted_at") is not None or b.get("deleted_at") is not None or keep == gone:
        return {"ok": False, "why": "Both people must be there, and two of them."}
    with db.atomic():
        ids = db.rows("SELECT id, type, value, shown FROM synapse.identity WHERE scope_id = %s AND item_id = %s",
                      (scope, gone))
        moved_ids = 0
        for x in ids:
            db.run("DELETE FROM synapse.identity WHERE id = %s", (x["id"],))
            if add_identity(scope, keep, x["type"], x["value"], x["shown"], f"merged from {b['title']}"[:300]) == "added":
                moved_ids += 1
        # A link of `gone` that `keep` already has goes with it; every other one is now `keep`'s.
        links = db.value("WITH moved AS (UPDATE synapse.link l SET dst = %s WHERE l.dst = %s AND NOT EXISTS ("
                         "SELECT 1 FROM synapse.link k WHERE k.dataset_id = l.dataset_id AND k.src = l.src AND k.dst = %s "
                         "AND k.type = l.type) RETURNING 1) SELECT count(*) FROM moved", (keep, gone, keep)) or 0
        links += db.value("WITH moved AS (UPDATE synapse.link l SET src = %s WHERE l.src = %s AND NOT EXISTS ("
                          "SELECT 1 FROM synapse.link k WHERE k.dataset_id = l.dataset_id AND k.dst = l.dst AND k.src = %s "
                          "AND k.type = l.type) RETURNING 1) SELECT count(*) FROM moved", (keep, gone, keep)) or 0
        db.run("DELETE FROM synapse.link WHERE dst = %s OR src = %s", (gone, gone))
        am, bm = a.get("meta") or {}, b.get("meta") or {}
        emails = list(dict.fromkeys((am.get("emails") or []) + (bm.get("emails") or [])))
        phones = list(dict.fromkeys((am.get("phones") or []) + (bm.get("phones") or [])))
        same = [x for x in am.get("likely_same") or [] if isinstance(x, dict) and str(x.get("id")) != str(gone)]
        set_meta(keep, {"emails": emails, "phones": phones, "likely_same": same})
        db.run("UPDATE synapse.item SET alias_of = %s, deleted_at = now(), status = 'deleted', "
               "meta = meta || %s::jsonb WHERE id = %s",
               (keep, Json({"merged_into": str(keep), "merged_by": by, "likely_same": []}), gone))
        # Nobody else is flagged as likely the same as somebody who is not there any more.
        for r in db.rows("SELECT id, meta->'likely_same' AS s FROM synapse.item WHERE dataset_id = %s AND kind = 'person' "
                         "AND deleted_at IS NULL AND meta->'likely_same' @> %s::jsonb", (scope, Json([{"id": str(gone)}]))):
            set_meta(r["id"], {"likely_same": [x for x in r["s"] or [] if str(x.get("id")) != str(gone)]})
    linked(ds, [keep])
    _repoint_slack(scope, keep, gone)
    return {"ok": True, "moved": {"identities": moved_ids, "links": int(links)}, "kept": str(keep)}


def not_same(ds: dict, a: str, b: str) -> dict:
    """`a` and `b` are two people: the flag between them taken off, and never put back."""
    scope = home_id(ds)
    for x, y in ((a, b), (b, a)):
        person = get(scope, x)
        if not person:
            return {"ok": False, "why": "Both people must be there."}
        meta = person.get("meta") or {}
        same = [e for e in meta.get("likely_same") or [] if isinstance(e, dict) and str(e.get("id")) != str(y)]
        apart = list(dict.fromkeys([str(v) for v in meta.get("not_same") or []] + [str(y)]))
        set_meta(x, {"likely_same": same, "not_same": apart})
    return {"ok": True}


def _repoint_slack(scope: str, keep: str, gone: str) -> None:
    """A Slack member tied to the person merged away is tied to the one kept (`slack.person`)."""
    try:
        from ..models import SlackPerson

        name = (get(scope, keep) or {}).get("title") or ""
        SlackPerson.objects.filter(contact_id=str(gone)).update(contact_id=str(keep), contact_name=name)
    except Exception:  # noqa: BLE001 - no Slack here
        pass


# ---------------------------------------------------------------------------------------
# a Slack member as one of a person's identifiers (22 October 2026)
# ---------------------------------------------------------------------------------------

def slack_value(team: str, slack_id: str) -> str:
    return f"{team}:{slack_id}" if team and slack_id else ""


def carry_slack(scope: str, pid: str, *, team: str, slack_id: str, display: str = "", real: str = "") -> str:
    """The member's Slack id and the names they go by there (@Tomek, Tomasz Wiśniewski) put on the person
    as their identifiers. 'added', 'had', or the id of another person the member is already on."""
    if kept_off(scope, pid, "slack", slack_value(team, slack_id)):
        # He took this member off this person (`aka.unlink`): never put back by code.
        return ""
    got = add_identity(scope, pid, "slack", slack_value(team, slack_id), f"@{display or real or slack_id}",
                       "their Slack member")
    if got not in ("added", "had"):
        return got
    for name in dict.fromkeys(n for n in (real, display) if n and not n.startswith("@")):
        if norm_name(name) and not kept_off(scope, pid, "name", norm_name(name)):
            add_identity(scope, pid, "name", norm_name(name), name, "their name in Slack")
    return got


def sure_by_name(scope: str, name: str, companies=()) -> tuple[str | None, list[str]]:
    """The one person a full name is surely, when nothing else says who: (their id, []) when exactly one person
    has the name in any of its forms (`name_forms`) and one of their addresses is at a company the name was met
    with (`companies`, the company words of the channels a Slack member writes in, such as "brightfield");
    else (None, everybody it could be), which is for his pick and never merged on."""
    if len(norm_name(name).split()) < 2:
        return None, []
    found: list[str] = []
    for form in name_forms(name):
        found += [p for p in find_all(scope, "name", form) if p not in found]
    found = [p for p in found if (get(scope, p) or {}).get("source") != "synapse" or
             any(x["type"] == "email" for x in identities(scope, p))]
    if len(found) != 1 or not companies:
        return None, found
    words = {str(c).lower() for c in companies if c}
    domains = [x["value"].rsplit("@", 1)[-1] for x in identities(scope, found[0]) if x["type"] == "email"]
    if any(w in d.split(".") for d in domains for w in words):
        return found[0], []
    return None, found


# ---------------------------------------------------------------------------------------
# people made of a list of names (22 October 2026)
# ---------------------------------------------------------------------------------------
#
# Until 22 October 2026 a Slack day in Master said who wrote in it as a list of names, and the code that links
# an item's sender (`ingest.code_links`) took the list for one sender: a person called "['Nadia', 'Tomasz
# Wiśniewski']", met in an item and matching nobody, for every set of people who wrote on one day. The day now
# says each writer with their Slack address (`slack.master_items`) and every sender of a list is linked
# (`code_links`); `repair_list_people` takes away the people made before, linking each of their items to the
# people who really wrote in it.

LIST_TITLE = re.compile(r"^\[\s*'.*'\s*\]$", re.S)


def list_people(ds: dict) -> list[dict]:
    """The people made of a list of names, in this dataset's scope."""
    return [r for r in db.rows("SELECT id, title FROM synapse.item WHERE dataset_id = %s AND kind = 'person' "
                               "AND source = 'synapse' AND deleted_at IS NULL AND title LIKE '[%%'", (home_id(ds),))
            if LIST_TITLE.match(r["title"] or "")]


def repair_list_people(ds: dict, *, by: str = "repair") -> dict:
    """Each person made of a list of names deleted, and every item linked to them linked again, by code, to the
    people who wrote it: for a Slack day, each writer by their Slack address where Slack gives one."""
    from . import ingest
    from .. import slack

    bad = list_people(ds)
    if not bad:
        return {"ok": True, "deleted": 0, "items": 0}
    items = sorted({r["src"] for r in db.rows("SELECT DISTINCT src FROM synapse.link WHERE dst = ANY(%s::uuid[])",
                                              ([b["id"] for b in bad],))})
    senders = slack.senders_of_days(str(ds["user_id"]), str(ds["org_id"]))
    for b in bad:
        # Its key goes with it, so its tombstone never stands in for a real person met later by that name.
        db.run("UPDATE synapse.item SET source_key = %s WHERE id = %s", (f"list-of-names:{b['id']}", b["id"]))
        ingest.delete(ds, b["id"], by=by, scrub=False)
    relinked = 0
    for item_id in items:
        item = ingest.get_item(ds["id"], item_id)
        if not item or item.get("deleted_at") is not None:
            continue
        meta = item.get("meta") or {}
        if item.get("source") == slack.SOURCE and item.get("source_key") in senders:
            meta = {**meta, "from": senders[item["source_key"]]}
            db.run("UPDATE synapse.item SET meta = meta || %s::jsonb WHERE id = %s", (Json({"from": meta["from"]}), item_id))
        ingest.relink_senders(ds, {**item, "meta": meta})
        relinked += 1
    return {"ok": True, "deleted": len(bad), "items": relinked}


# ---------------------------------------------------------------------------------------
# resolving somebody met in an item (decision 8)
# ---------------------------------------------------------------------------------------

def resolve(ds: dict, who: str, *, made_from: str = "", create_new: bool = True, readers=None,
            made_by: str = "") -> tuple[dict | None, str]:
    """The person an address, a phone number or a bare name in an item is, made if nobody matches.

    A person made here is read by everyone, unless `readers` says who (the meeting sync makes the people it
    meets readable only by the meetings' own readers, `meetings.people_readers`); `made_by` says what made them.

    Returns the person and how it was found: 'email', 'phone', 'name seen before', 'made'.
    A bare name only ever finds the person made from that same bare name before; it is never
    matched to somebody with an address, which would be a merge on name alone.
    """
    if isinstance(who, (list, tuple, set)):
        # One person at a time: a list said as one sender made "['Nadia', 'Tomasz Wiśniewski']" until
        # 22 October 2026 (`repair_list_people`). The caller resolves each.
        raise TypeError("resolve takes one person, not a list of them")
    raw = str(who or "").strip()
    if not raw:
        return None, ""
    scope = home_id(ds)
    if looks_like_phone(raw):
        name, email, phone = "", "", norm_phone(raw)
    else:
        name, addr = tx.address_of(raw)
        email, phone = norm_email(addr), ""
    if not (email or phone or name):
        return None, ""
    if email:
        pid, how = find(scope, "email", email), "email"
    elif phone:
        pid, how = find(scope, "phone", phone), "phone"
    else:
        got = db.row("SELECT id FROM synapse.item WHERE dataset_id = %s AND kind = 'person' AND source_key = %s "
                     "AND deleted_at IS NULL", (scope, "name:" + norm_name(name)))
        pid, how = (got or {}).get("id"), "name seen before"
    if pid:
        person = get(scope, pid)
        if person and name and (email or phone) and not kept_off(scope, pid, "name", norm_name(name)):
            # A new way of writing their name is one more identifier for the same person.
            add_identity(scope, pid, "name", norm_name(name), name, f"written so in an item {made_from}".strip())
        return person, how
    if not create_new:
        return None, ""
    h = home(ds)
    try:
        person = create(h, name=name or email or phone, origin="synapse", emails=[email] if email else [],
                        phones=[phone] if phone else [], readers=readers or [EVERYONE], made_from=made_from,
                        why="met in an item, matching nobody", owner=me(ds) if h["id"] == ds["id"] else None,
                        extra={"made_by": made_by} if made_by else None)
    except IntegrityError:
        # Two items from the same new address stored at once (an import): the other made them a moment
        # ago, and the item's key (`create`) refused the second. That one is the person.
        key = "email:" + email if email else "phone:" + phone if phone else "name:" + norm_name(name)
        got = db.row("SELECT id FROM synapse.item WHERE dataset_id = %s AND source = 'synapse' AND source_key = %s",
                     (scope, key[:300]))
        if not got:
            raise
        return get(scope, got["id"]), "made at the same moment by another item"
    flag_same_name(scope, person["id"])
    return person, "made"


def find_address(ds: dict, who: str) -> dict | None:
    """The person an address is, without making anybody."""
    return resolve(ds, who, create_new=False)[0]


def linked(ds: dict, pids) -> dict:
    """After links to people changed: their value again, and a first vector for anyone who now has
    something linked to them and had none (decision 10)."""
    from . import ingest

    pids = sorted({str(p) for p in pids if p})
    if not pids:
        return {}
    scope = home_id(ds)
    values = recompute(ds, pids)
    embedding = []
    for pid in pids:
        row = db.row(
            "SELECT i.dataset_id, (SELECT count(*) FROM synapse.passage p WHERE p.dataset_id = i.dataset_id "
            " AND p.item_id = i.id AND p.vec IS NOT NULL) AS vecs, "
            "(SELECT count(*) FROM synapse.job j WHERE j.dataset_id = i.dataset_id AND j.item_id = i.id AND j.kind = 'embed' "
            " AND j.done_at IS NULL) AS queued, (SELECT count(*) FROM synapse.link l WHERE l.dst = i.id) AS links "
            "FROM synapse.item i WHERE i.id = %s AND i.kind = 'person' AND i.deleted_at IS NULL", (pid,))
        if row and not row["vecs"] and not row["queued"] and row["links"]:
            ingest.enqueue(str(row["dataset_id"]), "embed", item_id=pid, priority=6)
            embedding.append(pid)
    return {"values": values, "embedding": embedding, "scope": scope}


# ---------------------------------------------------------------------------------------
# readers are people (decision 4)
# ---------------------------------------------------------------------------------------

def reader_id(ds: dict, text, *, create_new: bool = True) -> str | None:
    """A person's id for a reader, owner or asker as typed: an id, `everyone`, me, an address,
    a handle, a unique full name, a unique first name; with none of those, a new person."""
    t = " ".join(str(text or "").split())
    if not t:
        return None
    low = t.lower()
    if low == EVERYONE:
        return EVERYONE
    scope = home_id(ds)
    if UUID.match(low):
        return low if get(scope, low) else None
    if low in ("me", "myself", "owner", "the owner"):
        return me(ds)
    if "@" in t or looks_like_phone(t):
        person = resolve(ds, t, create_new=create_new)[0]
        return person["id"] if person else None
    if " " not in t:
        got = find(scope, "handle", low)
        if got:
            return got
    n = norm_name(t)
    same = find_all(scope, "name", n)
    if len(same) == 1:
        return same[0]
    if " " not in t:
        first = [r["item_id"] for r in db.rows(
            "SELECT DISTINCT x.item_id FROM synapse.identity x JOIN synapse.item i ON i.dataset_id = x.scope_id "
            "AND i.id = x.item_id WHERE x.scope_id = %s AND x.type = 'name' AND x.value LIKE %s AND i.deleted_at IS NULL "
            "AND i.kind = 'person' LIMIT 3", (scope, n + " %"))]
        if len(first) == 1:
            return first[0]
    if not create_new:
        return None
    h = home(ds)
    key = handle_of(t)
    person = create(h, name=t if t != low else t[:1].upper() + t[1:], origin="synapse",
                    handle=key if key and not find(scope, "handle", key) else "", readers=[EVERYONE],
                    why="a reader typed by name, matching nobody", source_key="handle:" + key if key and not find(
                        scope, "handle", key) else "", owner=me(ds) if h["id"] == ds["id"] else None)
    flag_same_name(scope, person["id"])
    return person["id"]


def reader_ids(ds: dict, texts, *, create_new: bool = True) -> list[str]:
    out = []
    for t in texts or []:
        got = reader_id(ds, t, create_new=create_new)
        if got and got not in out:
            out.append(got)
    return out


def asker_id(ds: dict, text) -> str:
    """Who asks: a known person, or a name that matches nobody and so reads only what everyone may."""
    from .. import silos

    limit, base = silos.split(str(text or ""))
    if limit is not None:
        # Limited to some of the owner's silos (`rouh/silos.py`): the same person, under those silos.
        return silos.asker(limit, asker_id(ds, base))
    if not text:
        return me(ds)
    if str(text).startswith("nobody:"):
        return str(text)
    got = reader_id(ds, text, create_new=False)
    return got or ("nobody:" + handle_of(text))


def search(ds: dict, q: str, limit: int = 12) -> list[dict]:
    """People of the dataset's people set whose name, address, phone or handle has a word starting
    with what was typed, best match first, for a picker: never makes anybody (4 October 2026).

    With nothing typed it is the dataset's own people (`datasets.people`), the owner first."""
    from . import datasets

    scope, owner = home_id(ds), me(ds)
    t = " ".join(str(q or "").split())
    if not t:
        ids = [p["key"] for p in datasets.people(ds)][:limit]
        hits = {i: 0 for i in ids}
    else:
        n, low = norm_name(t), t.lower()
        digits = re.sub(r"\D", "", t)
        start, word = _like(n) + "%", "% " + _like(n) + "%"
        rows = db.rows(
            "SELECT x.item_id, min(CASE WHEN x.value = %s THEN 0 WHEN x.value LIKE %s THEN 1 ELSE 2 END) AS rank "
            "FROM synapse.identity x JOIN synapse.item i ON i.dataset_id = x.scope_id AND i.id = x.item_id "
            "WHERE x.scope_id = %s AND i.kind = 'person' AND i.deleted_at IS NULL AND ("
            " (x.type IN ('name', 'handle') AND %s <> '' AND (x.value LIKE %s OR x.value LIKE %s))"
            " OR (x.type = 'email' AND x.value LIKE %s)"
            " OR (x.type = 'phone' AND length(%s) >= 3 AND x.value LIKE %s)) "
            "GROUP BY x.item_id ORDER BY rank LIMIT 200",
            (n, start, scope, n, start, word, _like(low) + "%", digits, "%" + _like(digits) + "%"))
        hits = {r["item_id"]: r["rank"] for r in rows}
    if not hits:
        return []
    got = db.rows("SELECT id, title, meta FROM synapse.item WHERE dataset_id = %s AND id = ANY(%s::uuid[])",
                  (scope, list(hits)))
    emails = {}
    for r in db.rows("SELECT item_id, shown, value FROM synapse.identity WHERE scope_id = %s AND type = 'email' "
                     "AND item_id = ANY(%s::uuid[]) ORDER BY made_at", (scope, list(hits))):
        emails.setdefault(r["item_id"], r["shown"] or r["value"])
    out = []
    for r in got:
        meta = r["meta"] if isinstance(r["meta"], dict) else {}
        out.append({"id": str(r["id"]), "name": r["title"] or "(no name)", "me": str(r["id"]) == owner,
                    "detail": emails.get(r["id"]) or meta.get("organisation") or "",
                    "rank": hits[r["id"]], "value": float(meta.get("value") or 0)})
    if not t:
        out.sort(key=lambda p: list(hits).index(p["id"]))
    else:
        out.sort(key=lambda p: (p["rank"], not p["me"], -p["value"], p["name"].lower()))
    return [{k: v for k, v in p.items() if k not in ("rank", "value")} for p in out[:limit]]


def _like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def names(ids) -> dict[str, str]:
    """Each id's name, for the screen."""
    ids = sorted({str(i) for i in ids or [] if i and UUID.match(str(i))})
    out = {EVERYONE: EVERYONE}
    if ids:
        for r in db.rows("SELECT id, title FROM synapse.item WHERE id = ANY(%s::uuid[])", (ids,)):
            out[r["id"]] = r["title"] or "(no name)"
    return out


def name_of(pid) -> str:
    p = str(pid or "")
    if not p:
        return ""
    if p.startswith("nobody:"):
        return p[7:] + " (nobody known)"
    from .. import silos

    limit, base = silos.split(p)
    if limit is not None:
        return f"{name_of(base)} (only {silos.names_of_keys(limit) or 'no silo'})"
    return names([p]).get(p, p)


def short(ds: dict, pid) -> str:
    """How a person is written in a prompt or a claim: their first name, lower case, as the X-ray writes them."""
    return handle_of(name_of(pid)) if pid else ""


def seed_people(ds: dict, whos) -> list[dict]:
    """An example set's own fictional people, from its addresses, before its items are stored: each
    with the first name its items' readers and questions use as a handle, and the set's owner's own
    addresses on the dataset's own person (the example says who its owner is)."""
    scope = home_id(ds)
    owner = me(ds)
    owner_key = handle_of(owner_name_of(ds)) or "me"
    out = []
    for who in dict.fromkeys(w for w in whos if w):
        name, addr = tx.address_of(who)
        email = norm_email(addr)
        if not email or find(scope, "email", email):
            continue
        key = handle_of(name)
        if key == owner_key:
            add_identity(scope, owner, "email", email, email, "the example's owner")
            add_identity(scope, owner, "name", norm_name(name), name, "the example's owner")
            row = get(scope, owner) or {}
            set_meta(owner, {"emails": list(dict.fromkeys(((row.get("meta") or {}).get("emails") or []) + [email]))})
            out.append({"person": name, "email": email, "as": "the dataset's own person"})
            continue
        person, _how = resolve(ds, who, made_from="")
        if person and key and add_identity(scope, person["id"], "handle", key, key, "the example's reader name") == "added":
            set_meta(person["id"], {"handle": key})
        out.append({"person": name, "email": email, "handle": key})
    return out


def copy_people(src: dict, new: dict) -> dict[str, str]:
    """For a copy of a dataset with its own people: each person of the source made again in the copy,
    with the same identifiers, and the source's person ids mapped to the copy's."""
    out = {EVERYONE: EVERYONE}
    if home_id(src) == home_id(new):
        return out
    out[me(src)] = me(new)
    scope = home_id(new)
    for p in db.rows("SELECT * FROM synapse.item WHERE dataset_id = %s AND kind = 'person' AND deleted_at IS NULL "
                     "ORDER BY stored_at", (home_id(src),)):
        if p["id"] in out:
            continue
        ids = identities(home_id(src), p["id"])
        found = next((find(scope, x["type"], x["value"]) for x in ids if x["type"] in ("email", "phone", "handle")
                      and find(scope, x["type"], x["value"])), None)
        if not found:
            meta = p.get("meta") or {}
            extra = {k: v for k, v in meta.items() if k in ("organisation", "birthday", "known", "old")}
            made = create(new, name=p["title"], origin=meta.get("origin") or "synapse",
                          emails=[x["value"] for x in ids if x["type"] == "email"],
                          phones=[x["value"] for x in ids if x["type"] == "phone"], readers=[EVERYONE], extra=extra,
                          why="copied with its dataset", source=p["source"], source_key=p["source_key"])
            found = made["id"]
        for x in ids:
            add_identity(scope, found, x["type"], x["value"], x["shown"], "copied with its dataset")
        out[p["id"]] = found
    return out


# ---------------------------------------------------------------------------------------
# how much a person matters (decision 9)
# ---------------------------------------------------------------------------------------

def value(scope_ds: dict, pid: str, s=None) -> tuple[float, dict]:
    """From their links, by code: the items they are on, the items the owner wrote to them or
    answered, how recent the latest is (the walk's half-life), and whether a relationship is set."""
    from . import datasets

    s = s or datasets.settings(scope_ds)
    me_id = str(scope_ds.get("me_id") or "")
    person = db.row("SELECT meta FROM synapse.item WHERE id = %s", (pid,)) or {}
    meta = person.get("meta") or {}
    got = db.row(
        "WITH mine AS (SELECT l.dataset_id, l.src, l.type FROM synapse.link l JOIN synapse.item i ON i.id = l.src "
        "  WHERE l.dst = %s AND i.deleted_at IS NULL AND i.kind NOT IN ('layer', 'person') "
        "  AND l.type IN ('from', 'to', 'cc', 'about')) "
        "SELECT (SELECT count(DISTINCT src) FROM mine) AS items, "
        " (SELECT count(DISTINCT m.src) FROM mine m WHERE m.type IN ('to', 'cc') AND EXISTS (SELECT 1 FROM synapse.link f "
        "   WHERE f.dataset_id = m.dataset_id AND f.src = m.src AND f.type = 'from' AND f.dst::text = %s)) AS wrote, "
        " (SELECT count(DISTINCT r.src) FROM synapse.link r JOIN mine m ON m.dataset_id = r.dataset_id AND m.src = r.dst "
        "   AND m.type = 'from' WHERE r.type = 'reply_to' AND EXISTS (SELECT 1 FROM synapse.link f WHERE "
        "   f.dataset_id = r.dataset_id AND f.src = r.src AND f.type = 'from' AND f.dst::text = %s)) AS answered, "
        " (SELECT max(i.said_at) FROM mine m JOIN synapse.item i ON i.id = m.src) AS latest",
        (pid, me_id, me_id)) or {}
    items, wrote, answered = int(got.get("items") or 0), int(got.get("wrote") or 0), int(got.get("answered") or 0)
    latest = got.get("latest")
    rec = 0.0
    if latest is not None:
        age = max(0.0, (datetime.now(timezone.utc) - latest).total_seconds() / 86400.0)
        rec = max(float(s.recency_floor), 0.5 ** (age / max(1.0, float(s.half_life_days))))
    activity = 1.0 - math.exp(-(items + 2 * (wrote + answered)) / max(0.5, float(s.person_value_items)))
    rel = bool(str(meta.get("relationship") or "").strip()) or bool(meta.get("known"))
    v = (float(s.person_value_base) + float(s.person_value_activity) * activity * rec
         + (float(s.person_value_relationship) if rel else 0.0))
    v = round(max(0.0, min(1.0, v)), 4)
    parts = {"items": items, "owner_wrote_to_them": wrote, "owner_answered_them": answered,
             "latest": latest.isoformat() if latest else None, "recency": round(rec, 4),
             "activity": round(activity, 4), "relationship": rel, "base": float(s.person_value_base),
             "rule": "base + activity weight × (1 − e^(−(items + 2 × written or answered) / scale)) × recency "
                     "+ relationship weight when a relationship is set or the owner marked them known",
             "at": datetime.now(timezone.utc).isoformat()}
    return v, parts


def recompute(ds: dict, pids) -> dict:
    from . import datasets

    scope_ds = home(ds)
    s = datasets.settings(scope_ds)
    out = {}
    for pid in sorted({str(p) for p in pids if p}):
        v, parts = value(scope_ds, pid, s)
        set_meta(pid, {"value": v, "value_parts": parts})
        out[pid] = v
    return out


def ensure_values(ds: dict) -> int:
    """Values for any person in this dataset's scope who has none yet (after the migration)."""
    pids = [r["id"] for r in db.rows(
        "SELECT id FROM synapse.item WHERE dataset_id = ANY(synapse.scope(%s)) AND kind = 'person' "
        "AND deleted_at IS NULL AND NOT (meta ? 'value') LIMIT 5000", (ds["id"],))]
    if pids:
        recompute(ds, pids)
    return len(pids)
