"""Also known as: which Slack member, address and name is which person, set by the owner (22 October 2026).

Petar, 22 October 2026, of matching the people in Slack to the people in his contacts, his mail and his
meetings' notes as one person: "give me interface to do that. I am guessing I should be doing this from
contacts card of the person?! also from typing a message like you suggest? please set this up."

Code already ties a Slack member to a contact by the address Slack gives, and surely by name
(`slack.tie`, `people.sure_by_name`), and flags what it is less sure of as likely the same. This is the
owner's own hand on it, in three places that all call the functions here:

- **The contact card** (`show_contact`, `apple_contacts.profile_card`) and **the Synapse person card**
  (`web/synapse.py`, `_person`) each draw one section, "Also known as" (`static/personlinks.js`): every
  identifier the person holds beyond their iCloud card, each with Unlink; one search box that finds Slack
  members, other people and addresses, to Link one into this person; the people flagged as likely the same,
  with Same person and Not the same; and every change made so, each with Undo.
- **Rouh's tool `link_person`** (`tools.py`), for "@Bartek is Bartosz Zielinski", on the owner's own words only.

What each change does:

- **Link a person** folds them into this one (`people.fold`, the survivor chosen as `people.survivor`
  chooses: the one with the iCloud card, else the one with an address).
- **Link a Slack member** puts the member on this person as their identifier (`people.carry_slack`), moving
  it off anybody else who carried it, ties the member to them in Rouh's own list (`SlackPerson.contact_id`)
  and links their Slack days again, so the days are this person's at once.
- **Link an address or a name** adds it to this person; nobody else holds it.
- **Unlink** takes one identifier off and makes it a person of its own, with the items that were linked
  through it, and marks it as taken off (`meta.unlinked`), so no code puts it back.
- **Not the same** takes the flag off two people for good (`people.not_same`).

Every change is a row of `synapse.person_change` (migration 0208), with what was moved, and Undo puts it
back exactly. Nothing here writes to iCloud: a Slack member and a name are Rouh's own fields, and an address
on the iCloud card is never unlinked here (it is the phone's to change).
"""
from __future__ import annotations

import logging
import re

from . import db, people
from .db import Json

log = logging.getLogger("rouh.synapse.aka")

#: The link types code makes to a person from an item, which linking again remakes.
CODE_TYPES = ("from", "to", "cc", "attended", "invited", "spoke")

#: Where an address came from when it came with a Slack member linked by hand.
SLACK_ADDRESS = "their address in Slack"

#: How many changes a card lists.
HISTORY = 12


class Refused(Exception):
    """A change that cannot be made, with the sentence that says why."""


# ---------------------------------------------------------------------------------------
# reading: what a person is also known as
# ---------------------------------------------------------------------------------------

def _scope(ds: dict) -> str:
    return people.home_id(ds)


def _person(ds: dict, pid: str) -> dict:
    p = people.get(_scope(ds), pid)
    if not p:
        raise Refused("That person is not there.")
    if p.get("deleted_at") is not None:
        kept = str(p.get("alias_of") or "")
        if kept and people.get(_scope(ds), kept):
            raise Refused("That person was linked into another one: open them instead.")
        raise Refused("That person is not there any more.")
    return p


def live_id(ds: dict, pid: str) -> str:
    """The person an id is now: itself, or the one it was linked into, followed to the end. "" when gone."""
    scope, seen = _scope(ds), set()
    while pid and pid not in seen:
        seen.add(pid)
        p = people.get(scope, pid)
        if not p:
            return ""
        if p.get("deleted_at") is None:
            return str(p["id"])
        pid = str(p.get("alias_of") or "")
    return ""


def _card_values(p: dict) -> set[tuple[str, str]]:
    """The addresses and numbers on the person's iCloud card, as identifiers: the phone's, never unlinked here."""
    ic = (p.get("meta") or {}).get("icloud") or {}
    if not isinstance(ic, dict):
        return set()
    out = {("email", people.norm_email(e.get("address") if isinstance(e, dict) else e))
           for e in ic.get("emails") or []}
    out |= {("phone", people.norm_phone(n.get("number") if isinstance(n, dict) else n))
            for n in ic.get("phones") or []}
    return {x for x in out if x[1]}


def _slack_rows(ds: dict) -> tuple[object, dict]:
    """The organisation's Slack app and every member Rouh keeps, by "<team>:<member>"."""
    try:
        from .. import slack
        from ..models import SlackPerson

        conn = slack.connection(str(ds["org_id"]))
        if conn is None or not conn.team_id:
            return None, {}
        rows = SlackPerson.objects.filter(org_id=conn.org_id, team_id=conn.team_id)
        return conn, {people.slack_value(r.team_id, r.slack_id): r for r in rows}
    except Exception:  # noqa: BLE001 - no Slack here
        return None, {}


def _member_href(conn, slack_id: str) -> str:
    url = str(getattr(conn, "team_url", "") or "").rstrip("/")
    return f"{url}/team/{slack_id}" if url.startswith("https://") and slack_id else ""


def _source_words(source: str) -> str:
    s = str(source or "")
    if s.startswith("written so in an item"):
        return "as written in mail or notes"
    if s.startswith("merged from "):
        return "from " + s[len("merged from "):]
    if s in ("met in an item", "met in an item, matching nobody"):
        return "met in mail, Slack or notes"
    return s


def _ident(ds: dict, p: dict, x: dict, card: set, conn, members: dict) -> dict:
    t, v = x["type"], x["value"]
    one = {"type": t, "value": v, "shown": x["shown"] or v, "from": _source_words(x["source"]),
           "label": {"email": "Email", "phone": "Phone", "slack": "Slack", "name": "Name",
                     "handle": "Handle"}.get(t, t), "unlink": True}
    if (t, v) in card:
        one["unlink"], one["from"] = False, "on their iCloud card"
    if t == "name" and v == people.norm_name(p.get("title") or ""):
        one["unlink"] = False
    if t == "slack":
        m = members.get(v)
        team, _, member = v.partition(":")
        if m is not None:
            one["detail"] = " · ".join(x for x in (m.real_name if m.real_name != m.name else "",
                                                   getattr(conn, "team_name", "") or "") if x)
        one["href"] = _member_href(conn, member) if conn is not None and team == conn.team_id else ""
    return one


def view(ds: dict, pid: str) -> dict:
    """Everything the "Also known as" section draws for one person."""
    scope = _scope(ds)
    p = _person(ds, pid)
    card = _card_values(p)
    conn, members = _slack_rows(ds)
    ids = [_ident(ds, p, x, card, conn, members) for x in people.identities(scope, pid)]
    meta = p.get("meta") or {}
    same = [x for x in meta.get("likely_same") or [] if isinstance(x, dict) and x.get("id")]
    names = people.names([x["id"] for x in same])
    likely = []
    for x in same:
        other = people.get(scope, str(x["id"]))
        if not other or other.get("deleted_at") is not None:
            continue
        likely.append({"id": str(x["id"]), "name": names.get(str(x["id"]), "(no name)"), "why": x.get("why") or "",
                       "detail": _detail(scope, str(x["id"])), "record": record(ds, other)})
    return {"ok": True, "person": {"id": str(p["id"]), "name": p.get("title") or "(no name)",
                                   "card": bool(card) or bool((meta.get("icloud") or {}).get("href")),
                                   "me": str(p["id"]) == str(ds.get("me_id") or "")},
            "this": record(ds, p) if likely else None,
            "ids": ids, "likely_same": likely, "history": history(ds, pid)}


#: Where a person is known from, by the source of what is linked to them, as a person says it.
_FROM = {"gmail": "mail", "slack": "Slack", "gcal": "calendar", "meetings": "meeting notes",
         "meeting": "meeting notes", "icloud": "iCloud", "rouh-chat": "Rouh's chats", "rouh-file": "files"}


def record(ds: dict, p: dict) -> dict:
    """The whole of one person, for deciding whether two are the same (Petar, 27 October 2026: "show the
    whole record side by side"): every address and number with its label, organisation, note, who they
    are to the owner, the research, the face, silos, where they are known from, and when last seen."""
    from .. import meeting_people, silos

    scope = _scope(ds)
    pid = str(p["id"])
    meta = p.get("meta") or {}
    ic = meta.get("icloud") or {}
    xs = people.identities(scope, pid)
    emails, phones = [], []
    seen_e, seen_p = set(), set()
    for e in ic.get("emails") or []:
        if isinstance(e, dict) and e.get("address"):
            emails.append({"value": str(e["address"]), "label": str(e.get("label") or ""), "from": "iCloud card"})
            seen_e.add(people.norm_email(e["address"]))
    for n in ic.get("phones") or []:
        if isinstance(n, dict) and n.get("number"):
            phones.append({"value": str(n["number"]), "label": str(n.get("label") or ""), "from": "iCloud card"})
            seen_p.add(people.norm_phone(n["number"]))
    for x in xs:
        if x["type"] == "email" and x["value"] not in seen_e:
            emails.append({"value": x["shown"] or x["value"], "label": "", "from": _source_words(x["source"])})
            seen_e.add(x["value"])
        elif x["type"] == "phone" and x["value"] not in seen_p:
            phones.append({"value": x["shown"] or x["value"], "label": "", "from": _source_words(x["source"])})
            seen_p.add(x["value"])
    slack = [x["shown"] or x["value"] for x in xs if x["type"] == "slack"]
    seen = db.rows("SELECT s.source, count(*) AS n, max(s.said_at) AS last FROM synapse.link l JOIN synapse.item s "
                   "ON s.id = l.src WHERE l.dst = %s AND s.deleted_at IS NULL GROUP BY s.source", (pid,))
    known = []
    if ic.get("href"):
        known.append("iCloud")
    for r in sorted(seen, key=lambda r: -int(r["n"] or 0)):
        word = _FROM.get(str(r["source"] or ""), str(r["source"] or "") or "Synapse")
        if word not in known:
            known.append(word)
    if slack and "Slack" not in known:
        known.append("Slack")
    if not known:
        known.append({"icloud": "iCloud", "slack": "Slack", "meeting": "meeting notes"}.get(
            str(meta.get("origin") or ""), "Synapse"))
    lasts = [r["last"] for r in seen if r["last"] is not None]
    last = max(lasts) if lasts else None
    uid, oid = str(ds.get("user_id") or ""), str(ds.get("org_id") or "")
    try:
        photo = meeting_people.photo_url(pid, meta)
    except Exception:  # noqa: BLE001 - a face is never worth failing a record over
        photo = ""
    return {"id": pid, "name": p.get("title") or "(no name)", "photo": photo,
            "emails": emails, "phones": phones, "slack": slack,
            "organisation": str(meta.get("organisation") or ""), "note": str(meta.get("note") or ""),
            "relationship": str(meta.get("relationship") or ""), "research": str(meta.get("research") or ""),
            "silos": silos.chips(uid, oid, p.get("silos") or []) if uid else [],
            "known_from": known, "items": sum(int(r["n"] or 0) for r in seen),
            "last_seen": last.isoformat() if hasattr(last, "isoformat") else (str(last) if last else ""),
            "card": bool(ic.get("href")), "dataset": str(p.get("dataset_id") or "")}


def _detail(scope: str, pid: str) -> str:
    """What tells one person from another in a list: their first address, else their Slack member, else
    how many items are linked to them."""
    xs = people.identities(scope, pid)
    first = next((x["shown"] or x["value"] for x in xs if x["type"] == "email"), "") or \
        next((x["shown"] for x in xs if x["type"] == "slack"), "") or \
        next((x["shown"] or x["value"] for x in xs if x["type"] == "phone"), "")
    if first:
        return first
    n = db.value("SELECT count(*) FROM synapse.link WHERE dst = %s", (pid,)) or 0
    return f"{n} item{'s' if n != 1 else ''} linked" if n else "nothing linked yet"


#: A later change, not undone, on either of a change's people: it is undone first, as an undo stack is.
_LATER = ("EXISTS (SELECT 1 FROM synapse.person_change n WHERE n.scope_id = c.scope_id AND n.id > c.id AND "
          "n.undone_at IS NULL AND (n.person IN (c.person, c.other) OR n.other IN (c.person, c.other)))")


def history(ds: dict, pid: str) -> list[dict]:
    rows = db.rows("SELECT c.id, c.person, c.other, c.action, c.what, c.by, c.made_at, c.undone_at, c.undone_by, "
                   "(c.undo->>'can')::boolean AND NOT " + _LATER + " AS can FROM synapse.person_change c "
                   "WHERE c.scope_id = %s AND "
                   "(c.person = %s::uuid OR c.other = %s::uuid) ORDER BY coalesce(c.undone_at, c.made_at) DESC, c.id DESC LIMIT %s",
                   (_scope(ds), pid, pid, HISTORY))
    return [{"id": r["id"], "action": r["action"], "what": r["what"], "by": r["by"],
             "at": r["made_at"].isoformat() if r["made_at"] else "",
             "undone": r["undone_at"] is not None, "undone_by": r["undone_by"],
             "can_undo": r["undone_at"] is None and r["can"] is not False} for r in rows]


# ---------------------------------------------------------------------------------------
# finding what to link
# ---------------------------------------------------------------------------------------

EMAIL = re.compile(r"^[^@\s<>]+@[^@\s<>]+\.[^@\s<>]+$")


def find(ds: dict, pid: str, q: str, limit: int = 8) -> dict:
    """What one search box finds to link into this person: Slack members Rouh knows (with or without a
    contact), other people of the dataset (contacts, and people met in mail, Slack or meetings), and an
    address or a name nobody holds, to add as it was typed. A leading @ finds Slack members only."""
    scope = _scope(ds)
    t = " ".join(str(q or "").split())
    if not t:
        return {"ok": True, "found": []}
    slack_only = t.startswith("@")
    word = t.lstrip("@").strip()
    out: list[dict] = []
    conn, members = _slack_rows(ds)
    for value, m in members.items():
        if m.is_bot or m.deleted or len(out) >= limit:
            continue
        if not _member_matches(m, word):
            continue
        holder = people.find(scope, "slack", value)
        if holder == pid:
            continue
        holder_name = people.name_of(holder) if holder else ""
        out.append({"kind": "slack", "value": value, "name": f"@{m.name or m.real_name or m.slack_id}",
                     "detail": " · ".join(x for x in (
                         m.real_name if m.real_name and m.real_name != m.name else "", m.email,
                         f"now on {holder_name}" if holder else "no contact yet",
                         getattr(conn, "team_name", "") or "") if x)})
    if not slack_only:
        for one in people.search(ds, word, limit=limit + 2):
            if one["id"] == pid or one.get("me"):
                continue
            out.append({"kind": "person", "id": one["id"], "name": one["name"],
                        "detail": one.get("detail") or _detail(scope, one["id"])})
        low = word.lower()
        if EMAIL.match(low) and not people.find(scope, "email", people.norm_email(low)):
            out.append({"kind": "email", "value": low, "name": low, "detail": "an address nobody has yet"})
        elif not out and "@" not in word and len(word) >= 2 and \
                pid not in people.find_all(scope, "name", people.norm_name(word)):
            # A name as it is written in notes or a transcript, when it is nobody's yet.
            out.append({"kind": "name", "value": word, "name": word, "detail": "a name they go by"})
    return {"ok": True, "found": out[:limit + 2]}


def _member_matches(m, word: str) -> bool:
    w = people.norm_name(word)
    if not w:
        return False
    for said in (m.name, m.real_name):
        n = people.norm_name(said)
        if n and (n.startswith(w) or (" " + w) in (" " + n)):
            return True
    return bool(m.email) and str(m.email).lower().startswith(word.lower())


# ---------------------------------------------------------------------------------------
# changing: link, unlink, not the same, and undo
# ---------------------------------------------------------------------------------------

def _record(ds: dict, person: str, other: str | None, action: str, what: str, by: str, undo: dict) -> int:
    return int(db.value("INSERT INTO synapse.person_change (scope_id, person, other, action, what, by, undo) "
                        "VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb) RETURNING id",
                        (_scope(ds), person, other, action, what[:300], by[:100], Json(undo))))


def _done(ds: dict, pid: str, change: int, said: str, **extra) -> dict:
    live = live_id(ds, pid) or pid
    return {"ok": True, "change": change, "said": said, "person": live, **extra}


def _frozen(ds: dict) -> None:
    if ds.get("frozen"):
        from .ingest import FROZEN_WORDS
        raise Refused(FROZEN_WORDS)


def link(ds: dict, pid: str, pick: dict, *, by: str = "card") -> dict:
    """One thing linked into this person: {kind: person, id} | {kind: slack, value} | {kind: email, value} |
    {kind: name, value}. {ok, change, said, person: who it is now} or raises Refused."""
    _frozen(ds)
    p = _person(ds, pid)
    kind = str((pick or {}).get("kind") or "")
    if kind == "person":
        return _link_person(ds, p, str(pick.get("id") or ""), by)
    if kind == "slack":
        return _link_slack(ds, p, str(pick.get("value") or ""), by)
    if kind in ("email", "name"):
        return _link_value(ds, p, kind, str(pick.get("value") or ""), by)
    raise Refused("Say what to link: a person, a Slack member, an address or a name.")


# --- a person folded into this one ---------------------------------------------------

def _snapshot(scope: str, keep: str, gone: str) -> dict:
    """Everything a fold of `gone` into `keep` changes, so Undo can put it back."""
    from ..models import SlackPerson

    g = db.row("SELECT status, deleted_at, alias_of, meta, source_key FROM synapse.item WHERE id = %s", (gone,))
    k = db.row("SELECT meta FROM synapse.item WHERE id = %s", (keep,))
    km = k["meta"] or {}
    return {"kind": "fold", "keep": keep, "gone": gone,
            "gone_row": {"status": g["status"], "deleted": g["deleted_at"] is not None, "source_key": g["source_key"],
                         "alias_of": str(g["alias_of"] or ""), "meta": g["meta"] or {}},
            "keep_meta": {key: km.get(key) for key in ("emails", "phones", "likely_same", "not_same")},
            "keep_ids": [[x["type"], x["value"]] for x in people.identities(scope, keep)],
            "gone_ids": [{k2: x[k2] for k2 in ("type", "value", "shown", "source")}
                         for x in people.identities(scope, gone)],
            "links": [_link_json(r) for r in db.rows("SELECT * FROM synapse.link WHERE src = %s OR dst = %s",
                                                     (gone, gone))],
            "others_same": [{"id": str(r["id"]), "same": r["s"]} for r in db.rows(
                "SELECT id, meta->'likely_same' AS s FROM synapse.item WHERE dataset_id = %s AND kind = 'person' "
                "AND deleted_at IS NULL AND id <> %s AND meta->'likely_same' @> %s::jsonb",
                (scope, keep, Json([{"id": str(gone)}])))],
            "slack": [[r.pk, r.contact_name] for r in SlackPerson.objects.filter(contact_id=str(gone))]}


def _link_json(r: dict) -> dict:
    out = {}
    for k, v in r.items():
        out[k] = v.isoformat() if hasattr(v, "isoformat") else str(v) if k in ("dataset_id", "src", "dst") else v
    return out


def _fold(ds: dict, keep: str, gone: str, by: str) -> dict:
    snap = _snapshot(_scope(ds), keep, gone)
    got = people.fold(ds, keep, gone, by=by)
    if not got.get("ok"):
        raise Refused(got.get("why") or "They could not be made one person.")
    return snap


def _link_person(ds: dict, p: dict, other: str, by: str) -> dict:
    scope = _scope(ds)
    o = people.get(scope, other)
    if not o or o.get("deleted_at") is not None:
        raise Refused("The person to link is not there any more.")
    if str(o["id"]) == str(p["id"]):
        raise Refused("That is this same person.")
    order = people.survivor(ds, str(p["id"]), str(o["id"]))
    if order.get("why"):
        raise Refused(order["why"])
    keep, gone = order["keep"], order["gone"]
    kept_name, gone_name = people.name_of(keep), people.name_of(gone)
    gone_detail = _detail(scope, gone)
    snap = _fold(ds, keep, gone, by)
    _clear_apart(scope, keep, gone)
    said = f"{gone_name} ({gone_detail}) is {kept_name} now: one person."
    change = _record(ds, keep, gone, "link", f"Linked {gone_name} ({gone_detail})", by,
                     {"can": True, "steps": [snap]})
    return _done(ds, keep, change, said, kept=keep)


def _clear_apart(scope: str, a: str, b: str) -> None:
    """Two people he said were one are no longer marked as two."""
    for x, y in ((a, b), (b, a)):
        got = db.value("SELECT meta->'not_same' FROM synapse.item WHERE id = %s", (x,)) or []
        if isinstance(got, list) and str(y) in [str(v) for v in got]:
            people.set_meta(x, {"not_same": [v for v in got if str(v) != str(y)]})


# --- a Slack member put on this person -----------------------------------------------

def _member(ds: dict, value: str):
    conn, members = _slack_rows(ds)
    m = members.get(value)
    if conn is None or m is None:
        raise Refused("That Slack member is not one Rouh knows.")
    return conn, m


def _names_of_member(m) -> list[str]:
    return [n for n in dict.fromkeys(x for x in (m.real_name, m.name) if x and not x.startswith("@"))
            if people.norm_name(n)]


def _link_slack(ds: dict, p: dict, value: str, by: str) -> dict:
    from ..models import SlackPerson

    scope, pid = _scope(ds), str(p["id"])
    conn, m = _member(ds, value)
    holder = people.find(scope, "slack", value)
    if holder == pid:
        raise Refused(f"@{m.name} is already {p['title']}.")
    names = _names_of_member(m)
    step = {"kind": "ids", "to": pid, "from": holder or "", "moved": [], "added": [],
            "unmarked": [], "slack": [[m.pk, m.contact_id, m.contact_name]], "emails": None}
    with db.atomic():
        # His word now stands over anything he took off before.
        for t, v in [("slack", value)] + [("name", people.norm_name(n)) for n in names]:
            if people.kept_off(scope, pid, t, v):
                _unmark(pid, t, v)
                step["unmarked"].append([t, v])
        if holder:
            # Off the person who carried them, with the names they go by in Slack, onto this one.
            for x in db.rows("SELECT id, type, value, shown, source FROM synapse.identity WHERE scope_id = %s AND "
                             "item_id = %s AND (type = 'slack' AND value = %s OR type = 'name' AND value = ANY(%s) "
                             "AND source = 'their name in Slack')",
                             (scope, holder, value, [people.norm_name(n) for n in names])):
                db.run("DELETE FROM synapse.identity WHERE id = %s", (x["id"],))
                step["moved"].append({k: x[k] for k in ("type", "value", "shown", "source")})
                if people.add_identity(scope, pid, x["type"], x["value"], x["shown"], x["source"]) == "added":
                    step["added"].append([x["type"], x["value"]])
        else:
            before = {(x["type"], x["value"]) for x in people.identities(scope, pid)}
            people.carry_slack(scope, pid, team=conn.team_id, slack_id=m.slack_id, display=m.name, real=m.real_name)
            step["added"] = [[x["type"], x["value"]] for x in people.identities(scope, pid)
                             if (x["type"], x["value"]) not in before]
        addr = people.norm_email(m.email) if m.email else ""
        if addr and not people.find(scope, "email", addr) and not people.kept_off(scope, pid, "email", addr):
            # The address Slack confirmed for them is theirs too, nobody else holding it.
            people.add_identity(scope, pid, "email", addr, addr, SLACK_ADDRESS)
            step["added"].append(["email", addr])
            emails = list((p.get("meta") or {}).get("emails") or [])
            step["emails"] = emails
            people.set_meta(pid, {"emails": list(dict.fromkeys(emails + [addr]))})
        SlackPerson.objects.filter(pk=m.pk).update(contact_id=pid, contact_name=p.get("title") or "")
    step["items"] = relink_member(ds, m)
    steps = [step]
    for orphan in _orphans(ds, pid, names):
        # The person their Slack days were linked to by name alone, nothing linked to them now: one person.
        steps.append(_fold(ds, pid, orphan, by))
        _clear_apart(scope, pid, orphan)
    who = f"@{m.name}" + (f" ({m.real_name})" if m.real_name and m.real_name != m.name else "")
    was = f", taken off {people.name_of(holder)}" if holder else ""
    change = _record(ds, pid, holder or None, "link", f"Linked {who} on Slack{was}", by,
                     {"can": True, "steps": steps})
    days = len(step["items"])
    return _done(ds, pid, change, f"{who} on Slack is {p['title']} now{was}; "
                                  f"{days} Slack day{'s' if days != 1 else ''} linked again.")


def _orphans(ds: dict, pid: str, names) -> list[str]:
    """People made from one of these bare names (met in an item, matching nobody), with no address, phone or
    Slack member of their own and nothing linked to them any more."""
    keys = ["name:" + people.norm_name(n) for n in names if people.norm_name(n)]
    if not keys:
        return []
    return [str(r["id"]) for r in db.rows(
        "SELECT i.id FROM synapse.item i WHERE i.dataset_id = %s AND i.kind = 'person' AND i.deleted_at IS NULL "
        "AND i.source = 'synapse' AND i.source_key = ANY(%s) AND i.id <> %s::uuid "
        "AND NOT EXISTS (SELECT 1 FROM synapse.identity x WHERE x.scope_id = i.dataset_id AND x.item_id = i.id "
        "AND x.type IN ('email', 'phone', 'slack')) AND NOT EXISTS (SELECT 1 FROM synapse.link l WHERE l.dst = i.id)",
        (_scope(ds), keys, pid))]


def relink_member(ds: dict, m) -> list[str]:
    """A member's Slack days in Master given their writers as they are now (`slack.senders_of_days`) and
    linked again by code, so a day is linked to the person the member now is. The ids of the days."""
    from .. import slack

    names = [people.norm_name(n) for n in _names_of_member(m)]
    if not names:
        return []
    rows = db.rows("SELECT id, source_key, meta->'from' AS who FROM synapse.item WHERE dataset_id = %s AND "
                   "source = %s AND deleted_at IS NULL", (str(ds["id"]), slack.SOURCE))
    mine = [r for r in rows if any(n and n in people.norm_name(" ".join(map(str, r["who"] or []))) for n in names)]
    if not mine:
        return []
    try:
        senders = slack.senders_of_days(str(ds["user_id"]), str(ds["org_id"]))
    except Exception:  # noqa: BLE001 - the days stay linked as they were
        log.exception("aka: Slack days could not be read again")
        return []
    return _relink(ds, [r["id"] for r in mine], senders)


def _relink(ds: dict, item_ids, senders: dict | None = None) -> list[str]:
    """Items' links to people made again by code, as storing them makes them: a meeting's guests and
    speakers (`meetings.relink`), anything else's sender, recipients and copies (`ingest.relink_senders`),
    a Slack day with its writers as they are now."""
    from . import ingest
    from .. import slack
    from .sources import meetings

    done = []
    for item_id in dict.fromkeys(str(i) for i in item_ids):
        item = ingest.get_item(str(ds["id"]), item_id)
        if not item or item.get("deleted_at") is not None:
            continue
        try:
            if item.get("kind") == "meeting":
                meetings.relink(ds, item_id)
            else:
                meta = item.get("meta") or {}
                if item.get("source") == slack.SOURCE:
                    if senders is None:
                        senders = slack.senders_of_days(str(ds["user_id"]), str(ds["org_id"]))
                    if item.get("source_key") in senders:
                        meta = {**meta, "from": senders[item["source_key"]]}
                        db.run("UPDATE synapse.item SET meta = meta || %s::jsonb WHERE id = %s",
                               (Json({"from": meta["from"]}), item_id))
                ingest.relink_senders(ds, {**item, "meta": meta})
            done.append(item_id)
        except Exception:  # noqa: BLE001 - one item never stops the rest
            log.exception("aka: item %s could not be linked again", item_id)
    return done


# --- an address or a name added ------------------------------------------------------

def _link_value(ds: dict, p: dict, kind: str, value: str, by: str) -> dict:
    scope, pid = _scope(ds), str(p["id"])
    raw = " ".join(value.split())
    if kind == "email":
        v = people.norm_email(raw)
        if not EMAIL.match(v):
            raise Refused(f"{raw} is not an email address.")
        holder = people.find(scope, "email", v)
        if holder and holder != pid:
            return _link_person(ds, p, holder, by)
    else:
        v = people.norm_name(raw)
        if not v:
            raise Refused("Say the name.")
    if (kind, v) in {(x["type"], x["value"]) for x in people.identities(scope, pid)}:
        raise Refused(f"{p['title']} already has {raw}.")
    step = {"kind": "ids", "to": pid, "from": "", "moved": [], "added": [[kind, v]], "unmarked": [], "slack": [],
            "emails": None}
    with db.atomic():
        if people.kept_off(scope, pid, kind, v):
            _unmark(pid, kind, v)
            step["unmarked"].append([kind, v])
        people.add_identity(scope, pid, kind, v, raw, "linked by the owner")
        if kind == "email":
            emails = list((p.get("meta") or {}).get("emails") or [])
            step["emails"] = emails
            people.set_meta(pid, {"emails": list(dict.fromkeys(emails + [v]))})
    change = _record(ds, pid, None, "link", f"Linked {'the address' if kind == 'email' else 'the name'} {raw}", by,
                     {"can": True, "steps": [step]})
    return _done(ds, pid, change, f"{raw} is {p['title']} now.")


def _unmark(pid: str, t: str, v: str) -> None:
    got = db.value("SELECT meta->'unlinked' FROM synapse.item WHERE id = %s", (pid,)) or []
    people.set_meta(pid, {"unlinked": [x for x in got if not (isinstance(x, dict) and x.get("type") == t
                                                               and x.get("value") == v)]})


# --- one identifier taken off --------------------------------------------------------

def unlink(ds: dict, pid: str, type_: str, value: str, *, by: str = "card") -> dict:
    """One identifier taken off this person and made a person of its own, with the items linked through it.
    Marked as taken off, so code never puts it back. {ok, change, said, person, made}."""
    from ..models import SlackPerson

    _frozen(ds)
    scope = _scope(ds)
    p = _person(ds, pid)
    pid = str(p["id"])
    have = {(x["type"], x["value"]): x for x in people.identities(scope, pid)}
    x = have.get((type_, value))
    if x is None:
        raise Refused(f"{p['title']} does not have that any more.")
    if (type_, value) in _card_values(p):
        raise Refused("That is on their iCloud card. Take it off the card on the phone, and it goes here too.")
    if type_ == "name" and value == people.norm_name(p.get("title") or ""):
        raise Refused("That is the name they are known by here. Rename them instead.")
    member = None
    names: list[str] = []
    if type_ == "slack":
        _conn, members = _slack_rows(ds)
        member = members.get(value)
        names = _names_of_member(member) if member is not None else []
        title = (member.real_name or member.name) if member is not None else x["shown"].lstrip("@")
    else:
        title = x["shown"] or value
    # The items linked to this person through it: the ones whose sender, guests or speakers say it.
    # A Slack member's days are found by the member (`relink_member`), below.
    needles = [n for n in dict.fromkeys([value, x["shown"]]) if n] if type_ in ("email", "phone", "name") else []
    items = [r["src"] for r in db.rows(
        "SELECT DISTINCT l.src FROM synapse.link l JOIN synapse.item i ON i.id = l.src WHERE l.dst = %s "
        "AND l.type = ANY(%s) AND i.deleted_at IS NULL AND (" + " OR ".join(["i.meta::text ILIKE %s"] * len(needles))
        + ")", (pid, list(CODE_TYPES), *[f"%{people._like(n)}%" for n in needles]))] if needles else []
    key = "name:" + people.norm_name(title)
    held = db.row("SELECT id, deleted_at FROM synapse.item WHERE dataset_id = %s AND source = 'synapse' AND "
                  "source_key = %s", (scope, key))
    with db.atomic():
        if held is not None and held["deleted_at"] is not None:
            # Folded into somebody once: its key goes, so the bare name finds the person made now.
            db.run("UPDATE synapse.item SET source_key = %s WHERE id = %s", (f"folded:{held['id']}", held["id"]))
            held = None
        if held is not None and str(held["id"]) != pid and type_ in ("slack", "name"):
            # Somebody already goes by that bare name, apart from this person: it goes back to them.
            qid, made = str(held["id"]), False
        else:
            q = people.create(people.home(ds), name=title, origin="synapse", readers=[people.EVERYONE],
                              source_key=key if held is None else f"unlinked:{pid}:{type_}:{value}"[:300],
                              why=f"taken off {p['title']} by the owner",
                              owner=people.me(ds) if people.home(ds)["id"] == ds["id"] else None)
            qid, made = str(q["id"]), True
        moved = [(type_, value)]
        if type_ == "slack":
            moved += [("name", people.norm_name(n)) for n in names
                      if people.norm_name(n) != people.norm_name(p.get("title") or "")
                      and (have.get(("name", people.norm_name(n))) or {}).get("source") == "their name in Slack"]
            addr = people.norm_email(member.email) if member is not None and member.email else ""
            if addr and (have.get(("email", addr)) or {}).get("source") == SLACK_ADDRESS:
                # The address Slack gives for them came with the member, and goes with them.
                moved.append(("email", addr))
        for t, v in moved:
            db.run("DELETE FROM synapse.identity WHERE scope_id = %s AND item_id = %s AND type = %s AND value = %s",
                   (scope, qid, t, v))
            db.run("UPDATE synapse.identity SET item_id = %s, source = %s WHERE scope_id = %s AND item_id = %s "
                   "AND type = %s AND value = %s", (qid, f"taken off {p['title']}"[:300], scope, pid, t, v))
        meta = p.get("meta") or {}
        marks = list(meta.get("unlinked") or []) + [{"type": t, "value": v} for t, v in moved]
        changes = {"unlinked": marks,
                   "not_same": list(dict.fromkeys([str(v) for v in meta.get("not_same") or []] + [qid])),
                   "likely_same": [e for e in meta.get("likely_same") or [] if str((e or {}).get("id")) != qid]}
        gone_emails = [v for t, v in moved if t == "email"]
        qmeta = (people.get(scope, qid) or {}).get("meta") or {}
        if gone_emails:
            changes["emails"] = [e for e in meta.get("emails") or [] if e not in gone_emails]
            people.set_meta(qid, {"emails": list(dict.fromkeys((qmeta.get("emails") or []) + gone_emails))})
        if type_ == "phone":
            changes["phones"] = [e for e in meta.get("phones") or [] if e != value]
            people.set_meta(qid, {"phones": list(dict.fromkeys((qmeta.get("phones") or []) + [value]))})
        people.set_meta(pid, changes)
        people.set_meta(qid, {"not_same": list(dict.fromkeys([str(v) for v in qmeta.get("not_same") or []] + [pid])),
                              "likely_same": [e for e in qmeta.get("likely_same") or []
                                              if str((e or {}).get("id")) != pid]})
        if member is not None:
            SlackPerson.objects.filter(pk=member.pk).update(contact_id=qid, contact_name=title)
    relinked = _relink(ds, items)
    if member is not None:
        relinked += [i for i in relink_member(ds, member) if i not in relinked]
    people.linked(ds, [pid, qid])
    n = len(relinked)
    said = (f"{x['shown']} is a person of its own now, not {p['title']}"
            + (f"; {n} item{'s' if n != 1 else ''} went with it." if n else "."))
    change = _record(ds, pid, qid, "unlink", f"Unlinked {x['shown']}", by,
                     {"can": True, "steps": [{"kind": "split", "from": pid, "made": qid, "new": made,
                                              "items": relinked, "moved": [[t, v] for t, v in moved],
                                              "sources": [[t, v, (have.get((t, v)) or {}).get("source") or ""]
                                                          for t, v in moved],
                                              "meta": {k: meta.get(k) for k in changes},
                                              "slack": [[member.pk, member.contact_id, member.contact_name]]
                                              if member is not None else []}]})
    return _done(ds, pid, change, said, made=qid, made_new=made)


# --- two people kept apart -----------------------------------------------------------

def apart(ds: dict, pid: str, other: str, *, by: str = "card") -> dict:
    """Not the same person: the flag between them taken off for good (`people.not_same`), kept with Undo."""
    _frozen(ds)
    scope = _scope(ds)
    p = _person(ds, pid)
    o = people.get(scope, other)
    if not o:
        raise Refused("The other person is not there any more.")
    before = {str(x["id"]): {"likely_same": (x.get("meta") or {}).get("likely_same") or [],
                             "not_same": (x.get("meta") or {}).get("not_same") or []} for x in (p, o)}
    got = people.not_same(ds, str(p["id"]), str(o["id"]))
    if not got.get("ok"):
        raise Refused(got.get("why") or "That could not be kept.")
    change = _record(ds, str(p["id"]), str(o["id"]), "apart",
                     f"Kept apart from {o['title']} ({_detail(scope, str(o['id']))})", by,
                     {"can": True, "steps": [{"kind": "apart", "before": before}]})
    return _done(ds, str(p["id"]), change, f"{p['title']} and {o['title']} are two people.")


# --- undo ------------------------------------------------------------------------------

def undo(ds: dict, change_id, *, by: str = "card") -> dict:
    """One change taken back exactly, its steps last first. {ok, said, person}."""
    _frozen(ds)
    scope = _scope(ds)
    try:
        cid = int(change_id)
    except (TypeError, ValueError):
        raise Refused("Say which change to undo.") from None
    row = db.row("SELECT c.*, " + _LATER + " AS later FROM synapse.person_change c WHERE c.scope_id = %s "
                 "AND c.id = %s", (scope, cid))
    if row is None:
        raise Refused("That change is not there.")
    if row["undone_at"] is not None:
        raise Refused("That change was undone already.")
    if row["later"]:
        raise Refused("A later change on the same people is still in place: undo that one first.")
    plan = row["undo"] or {}
    if plan.get("can") is False:
        raise Refused("That change cannot be undone.")
    touched: set[str] = set()
    items: list[str] = []
    with db.atomic():
        for step in reversed(plan.get("steps") or []):
            kind = step.get("kind")
            if kind == "fold":
                touched |= _unfold(scope, step)
                # What code linked to them is linked again from who holds what now, so an older change
                # undone after a newer one still leaves every item with the right person.
                items += [ln["src"] for ln in step.get("links") or []
                          if ln.get("dst") == step["gone"] and ln.get("type") in CODE_TYPES]
            elif kind == "ids":
                t, i = _unids(scope, step)
                touched |= t
                items += i
            elif kind == "split":
                touched |= _unsplit(ds, step, by)
                if not step.get("new", True):
                    items += list(step.get("items") or [])
            elif kind == "apart":
                for pid, was in (step.get("before") or {}).items():
                    people.set_meta(pid, {"likely_same": was.get("likely_same") or [],
                                          "not_same": was.get("not_same") or []})
                    touched.add(pid)
        db.run("UPDATE synapse.person_change SET undone_at = now(), undone_by = %s WHERE id = %s", (by[:100], cid))
    if items:
        _relink(ds, items)
    alive = [t for t in touched if t and live_id(ds, t) == t]
    if alive:
        people.linked(ds, alive)
    person = live_id(ds, str(row["person"])) or str(row["person"])
    return {"ok": True, "said": f"Undone: {row['what']}.", "person": person}


def _unfold(scope: str, step: dict) -> set[str]:
    from ..models import SlackPerson

    keep, gone = step["keep"], step["gone"]
    g = step.get("gone_row") or {}
    db.run("UPDATE synapse.item SET status = %s, deleted_at = CASE WHEN %s THEN deleted_at ELSE NULL END, "
           "alias_of = NULLIF(%s, '')::uuid, meta = %s::jsonb, updated_at = now() WHERE id = %s",
           (g.get("status") or "ready", bool(g.get("deleted")), g.get("alias_of") or "", Json(g.get("meta") or {}), gone))
    key = str(g.get("source_key") or "")
    now = db.row("SELECT dataset_id, source, source_key FROM synapse.item WHERE id = %s", (gone,))
    if key and now and now["source_key"] != key:
        # Its key back (an unlink may have moved it on), so a bare name finds it again; a person folded
        # away since gives it up.
        held = db.row("SELECT id, deleted_at FROM synapse.item WHERE dataset_id = %s AND source = %s AND "
                      "source_key = %s", (now["dataset_id"], now["source"], key))
        if held is not None and held["deleted_at"] is not None:
            db.run("UPDATE synapse.item SET source_key = %s WHERE id = %s", (f"folded:{held['id']}", held["id"]))
            held = None
        if held is None:
            db.run("UPDATE synapse.item SET source_key = %s WHERE id = %s", (key, gone))
    had = {tuple(x) for x in step.get("keep_ids") or []}
    for x in step.get("gone_ids") or []:
        if (x["type"], x["value"]) not in had:
            db.run("DELETE FROM synapse.identity WHERE scope_id = %s AND item_id = %s AND type = %s AND value = %s",
                   (scope, keep, x["type"], x["value"]))
        db.run("INSERT INTO synapse.identity (scope_id, item_id, type, value, shown, source) VALUES "
               "(%s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
               (scope, gone, x["type"], x["value"], x["shown"], x["source"]))
    cols = ("id", "dataset_id", "src", "dst", "type", "strength", "base_strength", "origin", "made_by", "claim_idx",
            "why", "evidence", "made_at", "checked_at")
    for ln in step.get("links") or []:
        if db.run("UPDATE synapse.link SET src = %s, dst = %s WHERE id = %s", (ln["src"], ln["dst"], ln["id"])):
            continue
        present = [c for c in cols if c in ln]
        db.run(f"INSERT INTO synapse.link ({', '.join(present)}) VALUES ({', '.join(['%s'] * len(present))}) "
               "ON CONFLICT DO NOTHING",
               tuple(Json(ln[c]) if isinstance(ln[c], (dict, list)) else ln[c] for c in present))
    km = step.get("keep_meta") or {}
    people.set_meta(keep, {k: v for k, v in km.items() if v is not None},
                    drop=tuple(k for k, v in km.items() if v is None))
    for o in step.get("others_same") or []:
        people.set_meta(o["id"], {"likely_same": o.get("same") or []})
    for pk, name in step.get("slack") or []:
        SlackPerson.objects.filter(pk=pk).update(contact_id=gone, contact_name=name)
    return {keep, gone}


def _unids(scope: str, step: dict) -> tuple[set[str], list[str]]:
    from ..models import SlackPerson

    to, frm = step["to"], step.get("from") or ""
    for t, v in step.get("added") or []:
        db.run("DELETE FROM synapse.identity WHERE scope_id = %s AND item_id = %s AND type = %s AND value = %s",
               (scope, to, t, v))
    if frm and people.get(scope, frm):
        # What it had before stays; only what this change added went above.
        for x in step.get("moved") or []:
            db.run("INSERT INTO synapse.identity (scope_id, item_id, type, value, shown, source) VALUES "
                   "(%s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
                   (scope, frm, x["type"], x["value"], x["shown"], x["source"]))
    if step.get("unmarked"):
        got = db.value("SELECT meta->'unlinked' FROM synapse.item WHERE id = %s", (to,)) or []
        people.set_meta(to, {"unlinked": list(got) + [{"type": t, "value": v} for t, v in step["unmarked"]]})
    if step.get("emails") is not None:
        people.set_meta(to, {"emails": step["emails"]})
    for pk, contact, name in step.get("slack") or []:
        SlackPerson.objects.filter(pk=pk).update(contact_id=contact or "", contact_name=name or "")
    return {to, frm}, list(step.get("items") or [])


def _unsplit(ds: dict, step: dict, by: str) -> set[str]:
    """An unlink taken back: the person it made folded back into the one it came from, exactly that way,
    with whatever was linked to them meanwhile, and the marks it set taken off."""
    from ..models import SlackPerson

    scope = _scope(ds)
    pid, qid = step["from"], step["made"]
    q = people.get(scope, qid)
    if step.get("new", True):
        if q and q.get("deleted_at") is None:
            got = people.fold(ds, pid, qid, by=f"undo by {by}")
            if not got.get("ok"):
                raise Refused(got.get("why") or "The unlink could not be undone.")
    else:
        # It went back to somebody who was there before: only what it moved comes back.
        for t, v in step.get("moved") or []:
            db.run("UPDATE synapse.identity SET item_id = %s WHERE scope_id = %s AND item_id = %s AND type = %s "
                   "AND value = %s AND NOT EXISTS (SELECT 1 FROM synapse.identity y WHERE y.scope_id = %s AND "
                   "y.item_id = %s AND y.type = %s AND y.value = %s)", (pid, scope, qid, t, v, scope, pid, t, v))
        for pk, _contact, _name in step.get("slack") or []:
            SlackPerson.objects.filter(pk=pk).update(contact_id=pid, contact_name=people.name_of(pid))
        if q:
            qm = q.get("meta") or {}
            people.set_meta(qid, {"not_same": [v for v in qm.get("not_same") or [] if str(v) != str(pid)]})
    for t, v, source in step.get("sources") or []:
        # Where each came from, as it said before it was taken off.
        db.run("UPDATE synapse.identity SET source = %s WHERE scope_id = %s AND item_id = %s AND type = %s AND "
               "value = %s", (source, scope, pid, t, v))
    meta = step.get("meta") or {}
    now = (people.get(scope, pid) or {}).get("meta") or {}
    gone = {(t, v) for t, v in step.get("moved") or []}
    changes = {"unlinked": [x for x in now.get("unlinked") or []
                            if not (isinstance(x, dict) and (x.get("type"), x.get("value")) in gone)],
               "not_same": [v for v in now.get("not_same") or [] if str(v) != str(qid)]}
    if "emails" in meta:
        changes["emails"] = list(dict.fromkeys((now.get("emails") or []) + (meta.get("emails") or [])))
    people.set_meta(pid, changes)
    return {pid}


# ---------------------------------------------------------------------------------------
# words: the two sides of "@Bartek is Bartosz Zielinski", for Rouh's tool
# ---------------------------------------------------------------------------------------

def resolve(ds: dict, text: str, *, want: str = "") -> list[dict]:
    """Everybody a few words could be, for `link_person`: a person by their id, an address, a Slack member by
    @handle or name, a contact by name (with short forms: Bartek for Bartosz). `want` narrows it: person, slack,
    email or name. Each {kind, id|value, name, detail}; one is sure, more are for the owner to pick from,
    and none is nobody (then an address or a name nobody holds comes back as one to add)."""
    scope = _scope(ds)
    t = " ".join(str(text or "").split()).strip().strip('"\'')
    if not t:
        return []
    low = t.lower()
    if people.UUID.match(low):
        pid = live_id(ds, low)
        return [{"kind": "person", "id": pid, "name": people.name_of(pid), "detail": _detail(scope, pid)}] if pid else []
    if want in ("", "email") and EMAIL.match(low):
        pid = people.find(scope, "email", people.norm_email(low))
        if pid:
            return [{"kind": "person", "id": pid, "name": people.name_of(pid), "detail": low}]
        return [{"kind": "email", "value": low, "name": low, "detail": "an address nobody has yet"}]
    out: list[dict] = []
    word = t.lstrip("@")
    if want in ("", "slack"):
        conn, members = _slack_rows(ds)
        exact = [(v, m) for v, m in members.items() if not m.is_bot and not m.deleted and
                 people.norm_name(word) in (people.norm_name(m.name), people.norm_name(m.real_name))]
        found = exact or [(v, m) for v, m in members.items() if not m.is_bot and not m.deleted and
                          _member_matches(m, word)]
        for v, m in found[:8]:
            holder = people.find(scope, "slack", v)
            out.append({"kind": "slack", "value": v, "name": f"@{m.name or m.real_name}",
                        "detail": " · ".join(x for x in (m.real_name if m.real_name != m.name else "", m.email,
                                                         f"now on {people.name_of(holder)}" if holder else "") if x),
                        "holder": holder or ""})
        if t.startswith("@") or want == "slack":
            return out
    if want in ("", "person"):
        # The name as said first; its short and long forms (Bartek for Bartosz) only when nobody has it.
        ids: list[str] = list(people.find_all(scope, "name", people.norm_name(word)))
        for f in people.name_forms(word) if not ids else ():
            ids += [p for p in people.find_all(scope, "name", f) if p not in ids]
        if not ids:
            ids = [p["id"] for p in people.search(ds, word, limit=8) if not p.get("me")]
        for pid in ids[:8]:
            # A person a Slack member already found is that member, not a second candidate.
            if any(o.get("holder") == pid for o in out):
                continue
            out.append({"kind": "person", "id": pid, "name": people.name_of(pid), "detail": _detail(scope, pid)})
    if not out and want in ("", "name") and "@" not in word:
        out.append({"kind": "name", "value": word, "name": word, "detail": "a name they go by"})
    return out


SLACK_VALUE = re.compile(r"^[A-Z0-9]+:[A-Z0-9]+$")


def _listed(found: list[dict]) -> str:
    return "; ".join(f"{f['name']} ({f.get('detail') or f['kind']}) = "
                     + (f"id {f['id']}" if f["kind"] == "person" else f"{f['kind']} {f['value']}") for f in found)


def _one_side(ds: dict, words: str, want: str = "") -> tuple[dict | None, str]:
    """The one thing a few words name, or None and the sentence that says why: nobody, or who it could be."""
    w = " ".join(str(words or "").split())
    if SLACK_VALUE.match(w):
        _conn, members = _slack_rows(ds)
        m = members.get(w)
        return ({"kind": "slack", "value": w, "name": f"@{m.name}"}, "") if m is not None else \
            (None, f"There is no Slack member {w}.")
    found = resolve(ds, w, want=want)
    if not found:
        return None, f"Nobody matches \"{w}\"."
    if len(found) > 1:
        return None, (f"\"{w}\" could be {len(found)} people, so nothing was linked. Ask ‹owner› which, and "
                      f"call again with that one's id or value: {_listed(found)}.")
    return found[0], ""


def told(ds: dict, action: str, person: str, other: str = "", *, other_kind: str = "", change=None) -> tuple[str, str]:
    """`link_person`: the owner's words that two identities are one person, or that one is not this person.
    (what to say, the person to show afterwards or ""). Never guesses: anything that could be more than one
    person comes back as the candidates, for the owner to pick from."""
    action = (action or "link").strip().lower()
    if action not in ("link", "unlink", "show", "undo"):
        return "action is link, unlink, show or undo.", ""
    a, why = _one_side(ds, person)
    if a is None:
        return why, ""
    if action == "link":
        b, why = _one_side(ds, other, other_kind if other_kind in ("person", "slack", "email", "name") else "")
        if b is None:
            return why, ""
        if a["kind"] != "person" and b["kind"] == "person":
            a, b = b, a
        if a["kind"] != "person":
            return (f"Neither \"{person}\" nor \"{other}\" is a person Rouh knows: one of the two has to be a "
                    "contact or a person met in mail, Slack or notes.", "")
        try:
            got = link(ds, a["id"], {"kind": b["kind"], **({"id": b["id"]} if b["kind"] == "person"
                                                            else {"value": b["value"]})}, by="Rouh")
        except Refused as exc:
            return f"Nothing was linked: {exc}", a["id"]
        return got["said"] + " Their contact is on the screen, with Undo under Also known as.", got["person"]
    if a["kind"] != "person":
        return f"\"{person}\" is not a person Rouh knows.", ""
    pid = a["id"]
    if action == "show":
        return f"{a['name']}'s contact is on the screen, with what they are also known as.", pid
    if action == "undo":
        rows = [h for h in history(ds, pid) if h["can_undo"]]
        if change not in (None, ""):
            rows = [h for h in rows if str(h["id"]) == str(change)]
        if not rows:
            return f"There is no change on {a['name']} to undo.", pid
        try:
            got = undo(ds, rows[0]["id"], by="Rouh")
        except Refused as exc:
            return f"Nothing was undone: {exc}", pid
        return got["said"], got["person"]
    # unlink: which of their identifiers the words name.
    w = " ".join(str(other or "").split())
    if not w:
        return "Say what to unlink from them: an @handle, an address or a name.", pid
    ids = view(ds, pid)["ids"]
    low, bare = w.lower(), w.lower().lstrip("@")
    hits = [x for x in ids if x["unlink"] and (x["value"].lower() == low or x["shown"].lower() == low
            or x["shown"].lower().lstrip("@") == bare or people.norm_name(x["shown"]) == people.norm_name(w)
            or people.norm_name(x.get("detail", "").split(" · ")[0]) == people.norm_name(w))]
    if w.startswith("@") and any(x["type"] == "slack" for x in hits):
        # @ is a Slack member, never a name that happens to be spelt the same.
        hits = [x for x in hits if x["type"] == "slack"]
    if not hits:
        return (f"{a['name']} has nothing called \"{w}\" that can be unlinked. They have: "
                + "; ".join(f"{x['label']} {x['shown']}" for x in ids if x["unlink"]) + ".", pid)
    if len(hits) > 1:
        return (f"\"{w}\" is {len(hits)} of {a['name']}'s identifiers, so nothing was unlinked. Ask which: "
                + "; ".join(f"{x['label']} {x['shown']} = {x['value']}" for x in hits) + ".", pid)
    try:
        got = unlink(ds, pid, hits[0]["type"], hits[0]["value"], by="Rouh")
    except Refused as exc:
        return f"Nothing was unlinked: {exc}", pid
    return got["said"] + " Their contact is on the screen, with Undo under Also known as.", pid
