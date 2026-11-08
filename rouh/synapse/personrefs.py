"""People named in a question bring their own mails into the search (attempt 30, 15 October 2026).

"Who is Sam?", "What does Robin do for a living?", "What has Rouh emailed Jordan about?": the answer is in
mail that person sent or was sent, and the person's own item is usually among the search's first results
already. But a person has 50 to 130 links, the walk keeps six neighbours of an item, picked by how close
each one's words are to a short question like "who is Sam", so the mails never came in, and the seeds
filled with other people of the same first name instead (nine Ivans of twenty seeds for "Who is Ivan
Varbanov").

So, after the search and before the seeds are chosen (`recall.run`):

- **who is named**: the persons among the search's results whose name has a word of the question in it,
  keeping only those with the most such words ("Ivan Varbanov" is two words; "Ivan Dimitrov" is one). Never
  the owner, and never a mailbox Master reads (Rouh's own address is on every mail, and "Rouh" is in many
  questions about what Rouh did), so a question about Rouh is not flooded with Rouh's inbox;
- **their mails**: the mails each of them sent, was sent or was copied on, that the asker may read, closest
  to the question first, `person_mails` of them (3), become seeds of the walk besides the search's own twenty.

Measured on the benchmark the same night: as seeds besides the search's they found four questions' gold mails
and cost none; fused into the search's own list instead, or five or more of them, they took seed places from
it and lost task files in "is Sam around next week to send Jordan the DPA?". Dropping the persons who match
less of a whole name, also measured, found nothing more, so it is not done.

**Mails that name them** (attempt 37, 22 October 2026): an introduction or a hand-over about somebody is
written by somebody else, to somebody else, so it is not linked to them at all: "Who is Ivan Varbanov, and
what has gone between us and him?" missed the two "Re: Intro" mails Rouh wrote to two other people about him,
and "Who is Sam?" missed the support mail Sam signed, from a mailbox whose person item is not his. So the
mails whose own text or subject holds every word of a named person's name that the question used, whole words,
closest to the question first, `person_named_mails` of them (3), become seeds too, besides the linked ones,
when the question calls them by their first name or two words of their name or more (one other word is too
often an organisation that got into a contact card: "Robin Northwind", for the Northwind flights). A name is far sharper than a question's meaning: only three mails of the benchmark's dataset held the surname
asked about, and two of the three were the ones the question was about.

Plain code and five indexed queries: no model and no vector.
"""
from __future__ import annotations

import re
import time

from . import db, search

#: A name's word must be this long to count, so "Al" or "Jo" in a question match nobody by accident.
MIN_WORD = 3
#: The mails of a person looked at, newest first, before the closest to the question are taken.
LOOK_AT = 300
#: How long the mailboxes Master reads are remembered, per dataset.
MAILBOX_TTL_S = 300.0

_mailboxes: dict[str, tuple[float, set]] = {}


def _words(text: str) -> list[str]:
    return [w for w in re.findall(r"[^\W\d_]+", (text or "").lower()) if len(w) >= MIN_WORD]


def mailboxes(ds_id: str) -> set[str]:
    """The addresses whose inboxes this dataset's mail came from: on every mail, so never 'named'."""
    now = time.time()
    got = _mailboxes.get(ds_id)
    if got and now - got[0] < MAILBOX_TTL_S:
        return got[1]
    rows = db.rows("SELECT DISTINCT lower(meta->'gmail'->>'inbox') AS inbox FROM synapse.item "
                   "WHERE dataset_id = ANY(synapse.scope(%s)) AND kind = 'mail' AND meta->'gmail' ? 'inbox'",
                   (ds_id,))
    found = {r["inbox"] for r in rows if r.get("inbox")}
    _mailboxes[ds_id] = (now, found)
    return found


def named(ds: dict, question: str, fused: list[dict], details: dict, *, me: str = "") -> dict:
    """The persons among the search's results that the question names, best match only:
    {"people": [{"id", "title", "words"}]}."""
    asked = set(_words(question))
    if not asked:
        return {"people": []}
    found = []
    for f in fused:
        d = details.get(f["item_id"]) or {}
        if d.get("kind") != "person" or str(f["item_id"]) == str(me):
            continue
        words = sorted({w for w in _words(d.get("title") or "") if w in asked})
        if words:
            found.append({"id": str(f["item_id"]), "title": d.get("title") or "", "words": words})
    if not found:
        return {"people": []}
    # A mailbox Master reads (Rouh's own address) is on every mail: it is never the person asked about.
    boxes = mailboxes(ds["id"])
    if boxes:
        own = {r["item_id"] for r in db.rows(
            "SELECT DISTINCT item_id FROM synapse.identity WHERE type = 'email' AND item_id = ANY(%s::uuid[]) "
            "AND value = ANY(%s)", ([p["id"] for p in found], sorted(boxes)))}
        found = [p for p in found if p["id"] not in own]
    if not found:
        return {"people": []}
    best = max(len(p["words"]) for p in found)
    found = [p for p in found if len(p["words"]) == best]
    # The assistant's own sending address is a person of its own with the mailbox's name ("Rouh"), so it is
    # found on every question that says Rouh. It is not a correspondent: its own mails are its notices, which
    # took the seed places of the person really asked about ("What has Rouh emailed Teresa about?" lost one of
    # Teresa's two mails to them). Its name still finds the mails that name it (attempt 49).
    mine = assistants(ds["id"], [p["id"] for p in found])
    for p in found:
        if p["id"] in mine:
            p["assistant"] = True
    return {"people": found}


def assistants(ds_id: str, ids) -> set[str]:
    """Of these persons, those that share a name with a mailbox Master reads: the assistant's own sending
    addresses ("Rouh"). One query; the mailboxes' names are remembered with the mailboxes."""
    ids = [str(i) for i in ids if i]
    names = mailbox_names(ds_id)
    if not ids or not names:
        return set()
    return {str(r["item_id"]) for r in db.rows(
        "SELECT DISTINCT item_id FROM synapse.identity WHERE item_id = ANY(%s::uuid[]) AND type = 'name' "
        "AND value = ANY(%s)", (ids, sorted(names)))}


_mailbox_names: dict[str, tuple[float, set]] = {}


def mailbox_names(ds_id: str) -> set[str]:
    """The names of the persons whose address is a mailbox Master reads, per dataset."""
    now = time.time()
    got = _mailbox_names.get(ds_id)
    if got and now - got[0] < MAILBOX_TTL_S:
        return got[1]
    boxes = sorted(mailboxes(ds_id))
    found = {r["value"] for r in db.rows(
        "SELECT DISTINCT n.value FROM synapse.identity e JOIN synapse.identity n ON n.item_id = e.item_id "
        "AND n.type = 'name' WHERE e.type = 'email' AND e.value = ANY(%s)", (boxes,))} if boxes else set()
    _mailbox_names[ds_id] = (now, found)
    return found


def _capitalised(question: str) -> list[str]:
    """The question's words written with a capital letter, but for its first, which every sentence capitalises."""
    words = re.findall(r"[^\W\d_]+", question or "")[1:]
    return sorted({w.lower() for w in words if len(w) >= MIN_WORD and w[0].isupper()})


def names_someone(ds: dict, question: str, *, readers: list[str], me: str = "") -> list[str]:
    """The names of persons the asker may read that the question calls by a capitalised word (attempt 46):
    "Who is Sam?", "What has Jordan asked Rouh to do?". Never the owner, a mailbox Master reads, or a
    person sharing a name with one (the assistant's own sending address is a person of its own, "Rouh"),
    so "Does Rouh flag emails?" names nobody. Two small queries, no model."""
    asked = _capitalised(question)
    if not asked:
        return []
    rows = db.rows(
        "SELECT i.id, i.title FROM synapse.item i WHERE i.dataset_id = ANY(synapse.scope(%s)) AND i.kind = 'person' "
        "AND i.deleted_at IS NULL AND i.title ~* %s AND " + search.readable_sql("i"),
        (ds["id"], r"\m(" + "|".join(re.escape(w) for w in asked) + r")\M", readers))
    rows = [r for r in rows if str(r["id"]) != str(me)]
    if not rows:
        return []
    boxes = sorted(mailboxes(ds["id"]))
    own = set()
    if boxes:
        own = {str(r["item_id"]) for r in db.rows(
            "SELECT DISTINCT item_id FROM synapse.identity WHERE item_id = ANY(%s::uuid[]) AND "
            "((type = 'email' AND value = ANY(%s)) OR (type = 'name' AND value = ANY(%s)))",
            ([r["id"] for r in rows], boxes, sorted(mailbox_names(ds["id"]))))}
    return sorted({r["title"] for r in rows if str(r["id"]) not in own})


def their_mails(ds: dict, people: list[dict], qvec, *, readers: list[str], take: int,
                model: str | None = None) -> list[dict]:
    """The named persons' own mails the asker may read, closest to the question first: [{"item_id", "score"}]."""
    # The assistant's own sending address is no correspondent: its mails are its notices (attempt 49).
    people = [p for p in people or [] if not p.get("assistant")]
    if not people or take <= 0:
        return []
    rows = db.rows(
        "SELECT DISTINCT ON (m.id) m.id, m.said_at FROM synapse.link l JOIN synapse.item m ON m.id = l.src "
        "WHERE l.dataset_id = ANY(synapse.scope(%s)) AND l.dst = ANY(%s::uuid[]) AND l.type IN ('from', 'to', 'cc') "
        "AND m.kind = 'mail' AND m.deleted_at IS NULL AND " + search.readable_sql("m") +
        " ORDER BY m.id", (ds["id"], [p["id"] for p in people], readers))
    rows.sort(key=lambda r: str(r.get("said_at") or ""), reverse=True)
    ids = [r["id"] for r in rows[:LOOK_AT]]
    if not ids:
        return []
    # The rule itself, once each, as every search result is checked (`search.check_results`).
    ok = search.check_results(ds["id"], ids, readers)
    ids = [i for i in ids if i in ok]
    near = search.cosines(ds["id"], ids, qvec, model) if qvec is not None else {}
    # Closest to the question first; without a vector, newest first.
    ranked = sorted(ids, key=lambda i: -near.get(i, -1.0)) if near else ids
    return [{"item_id": i, "score": round(near.get(i, 0.0), 4)} for i in ranked[:take]]


def _calls_by_name(p: dict) -> bool:
    """Whether the question calls this person by name: their first name, or two words of their name or more.
    One word that is not the first name is too often an organisation that got into a contact card ("Robin
    Northwind", for "How much did the Northwind flights cost?")."""
    words = p.get("words") or []
    first = (_words(p.get("title") or "") or [""])[0]
    return len(words) >= 2 or first in words


def naming_mails(ds: dict, people: list[dict], qvec, *, readers: list[str], take: int, model: str | None = None,
                 skip=()) -> list[dict]:
    """The mails whose own text or subject names a named person, the asker may read, closest to the question
    first (attempt 37): [{"item_id", "score"}]. A mail must hold every word of the name that the question
    used, as whole words; `skip` are mails already seeds."""
    names = sorted({tuple(p["words"]) for p in people if _calls_by_name(p)})
    if not names or take <= 0:
        return []
    parts, params = [], []
    for words in names:
        pats = [r"\m" + re.escape(w) + r"\M" for w in words]
        # Whole words through the trigram indexes, every word of the name in the same passage or the subject.
        parts.append("SELECT p.item_id AS id FROM synapse.passage p WHERE p.dataset_id = ANY(synapse.scope(%s)) "
                     "AND NOT p.from_xray AND " + " AND ".join(["p.text ~* %s"] * len(pats)))
        params += [ds["id"], *pats]
        parts.append("SELECT t.id FROM synapse.item t WHERE t.dataset_id = ANY(synapse.scope(%s)) AND "
                     + " AND ".join(["t.title ~* %s"] * len(pats)))
        params += [ds["id"], *pats]
    rows = db.rows(
        "WITH hits AS (" + " UNION ".join(parts) + ") SELECT m.id, m.said_at FROM synapse.item m "
        "JOIN hits h ON h.id = m.id WHERE m.kind = 'mail' AND m.deleted_at IS NULL AND " + search.readable_sql("m")
        + " ORDER BY m.said_at DESC NULLS LAST LIMIT %s", [*params, readers, LOOK_AT])
    have = {str(x) for x in skip}
    ids = [r["id"] for r in rows if str(r["id"]) not in have]
    if not ids:
        return []
    ok = search.check_results(ds["id"], ids, readers)
    ids = [i for i in ids if i in ok]
    near = search.cosines(ds["id"], ids, qvec, model) if qvec is not None else {}
    ranked = sorted(ids, key=lambda i: -near.get(i, -1.0)) if near else ids
    return [{"item_id": i, "score": round(near.get(i, 0.0), 4)} for i in ranked[:take]]
