"""Rouh for the owner's team in Slack: what somebody who is not the owner may be answered from.

Petar, 16 October 2026, the third of five Slack ideas ("do all of those"): when somebody other than
him writes to Rouh's bot or @mentions it, Rouh answers questions such as "where does task 19
stand", "what was decided in Tuesday's meeting" or "find the pricing doc" - from the workspace, the
meeting library and Synapse Master, within what that person may see under their trusted-contact
grants (`rouh/trusted.py`). Everything else about such a message is a case, exactly as an email
from them is (`mail_cases.CaseDesk`): what would spend money, send, publish, commit him or cannot be
undone stays his.

**Who is answered** (`set_up`). Only somebody the owner set up: a trusted contact, switched on, whose
address Slack confirmed is one he ticked for them (`slack_listen.Listener._trusted`). Anybody else -
nobody matched, or a contact he switched off - gets one polite answer in the thread that Rouh can
only help people he has set up (`STRANGER`), and the owner is told once per person, with a button that
opens Trusted contacts ready to set them up (`tell_owner`, one notice, keyed so it is said once).

**What an answer may hold** (`Reach`). Never anything from the owner's mail, his own Slack direct
messages, his chats with Rouh, his notes, his calendar or his contacts: of Synapse Master only the
meeting library, the tasks and the workspace's files are ever read for them (`SOURCES`), never
anything special (health, money, legal) or not yet read by a model, and the case's turn is not
offered his mail, calendar or contacts at all (`mail_turn.SLACK_WITHHELD`). Of those, an item is
theirs when:

- it is inside a task or project they may read by its one level (`task_access`, `trusted.Grants`):
  the task, its steps and its files; or
- Synapse says they may read it themselves - a meeting they were a reader of in the library, under
  the silos of the owner's life they may see (`silos.asker` on their own contact, `search.readers_for`)
  - and it is no more than normal.

**Everybody who reads the answer** (`audience`). A direct message to Rouh is read by the person
alone. A channel, a private channel or a group direct message is read by everybody in it, so there
an item must be theirs for every person in it, the owner and bots aside; somebody in it who is not set
up may see nothing, so nothing of the owner's work goes into an answer there. The tasks a channel's
answer may read are narrowed the same way (`narrowed`, `Trusted.within`).

**Automatic recall on their words** (`recall_block`). The same look-up the owner's own messages get
(`synapse/autorecall.py`), run on what they wrote, with only what `Reach` allows kept, given to the
case's reading as background it may answer from.

Every query names the person and the organisation (`AGENTS.md`, "Whose data is it").
"""
from __future__ import annotations

import dataclasses
import logging
import time
from dataclasses import dataclass, field

from . import slack

log = logging.getLogger("rouh.slack_team")

#: What somebody the owner has not set up is told, every time they write to Rouh.
STRANGER = ("Hi {first} - I'm Rouh, {owner}'s assistant. I can only help people {owner} has set up "
            "to work with me, and you are not one of them yet. I have let {owner} know you asked.")

#: The only kinds of Synapse Master item ever read for somebody else: the meeting library, the
#: tasks and the workspace's files. An allow list, on purpose: a source added tomorrow is not one
#: they can reach until somebody puts it here.
SOURCES = frozenset({"meeting-library", "rouh-task", "rouh-file"})
#: Of those, what a task or project they may read brings: its own item and its files.
WORKSPACE = frozenset({"rouh-task", "rouh-file"})
#: Never in an answer to somebody else, whoever may read it.
NEVER_SENSITIVITY = frozenset({"special", "unlabelled"})
#: How many items a find hands back, and how many it looks at to find them.
FIND_MOST, LOOKED_AT = 12, 300
#: The most of one item read whole.
READ_CHARS = 6000
#: How long the look-up on their words may take before the reading starts without it.
RECALL_CEILING_S = 15.0


def set_up(contact) -> bool:
    """Whether the owner set this person up: a trusted contact they listed and switched on."""
    return contact is not None and not getattr(contact, "implicit", True) and bool(contact.trusted)


def first_name(name: str) -> str:
    return (str(name or "").split() or ["there"])[0]


# --- who reads an answer --------------------------------------------------------------------


def contact_of(who, conn, slack_id: str):
    """The trusted contact this Slack member is, by the address Slack confirmed, switched on or
    not; None for nobody matched."""
    from . import trusted as trust
    from .models import TrustedAddress

    person = slack.person(conn, slack_id)
    email = (person.email if person is not None else "") or ""
    if not email:
        return None
    found = TrustedAddress.objects.filter(user_id=who.user_id, org_id=who.org_id,
                                          address=email.lower()).values_list("contact_id", flat=True).first()
    if found is None:
        return None
    return trust.TrustStore().get(who.user_id, who.org_id, found)


def audience(who, conn, conv, asker: str) -> dict:
    """Who reads an answer in this conversation besides the asker: {"ids": [Slack ids], "said"}.
    The owner, Rouh and other apps are left out; a direct message to Rouh has nobody else. Slack's own
    word, asked now; when it will not say, everybody is unknown and nothing of the owner's work goes in."""
    if conv.kind == "im":
        return {"ids": [], "said": ""}
    try:
        everyone = slack.members(conn, conv.channel_id)
    except (slack.SlackError, slack.NotSetUp) as exc:
        log.info("slack: who is in %s could not be read: %s", slack.conversation_label(conv), exc)
        return {"ids": [], "unknown": True, "said": "Slack would not say who is in it"}
    out = []
    for sid in everyone:
        if sid in (asker, conn.bot_user_id, conn.slack_user_id):
            continue
        person = slack.person(conn, sid)
        if person is None or person.is_bot or person.deleted:
            continue
        own = _owners_own(who, person.email)
        if own:
            continue
        out.append(sid)
    return {"ids": out, "said": ""}


def _owners_own(who, email: str) -> bool:
    from . import my_card

    if not email:
        return False
    try:
        return email.lower() in {a.lower() for a in my_card.own_addresses(who.user_id, who.org_id) or []}
    except Exception:  # noqa: BLE001 - not known as the owner's: read as somebody else, never wider
        return False


@dataclass
class Reader:
    """One person who reads the answer, and what of the owner's they may see."""
    name: str
    #: Their own asker in Synapse, under their silos (`silos.asker`), or "" for none.
    asker: str = ""
    principals: frozenset = frozenset()
    #: The task and project folders they may read (`trusted.Grants`), whole.
    folders: tuple[str, ...] = ()
    #: The task ids they may read.
    task_ids: frozenset = frozenset()
    #: Set up by the owner: anybody else may see nothing.
    set_up: bool = False


@dataclass
class Reach:
    """Everybody who reads one answer: the asker first. An item may go in only when every one of
    them may see it."""
    readers: list[Reader] = field(default_factory=list)
    #: People in the conversation who may see nothing of the owner's: not set up.
    outsiders: list[str] = field(default_factory=list)
    where: str = ""
    #: Slack would not say who is in the conversation, so nobody reading it is known.
    unknown: bool = False

    @property
    def shared(self) -> bool:
        return len(self.readers) > 1 or bool(self.outsiders) or self.unknown

    @property
    def nothing(self) -> bool:
        return self.unknown or bool(self.outsiders) or not self.readers or \
            not all(r.set_up for r in self.readers)

    def within(self) -> frozenset | None:
        """The tasks every other reader may read too, or None when the asker reads it alone."""
        if not self.shared:
            return None
        if self.nothing:
            return frozenset()
        got = set(self.readers[0].task_ids)
        for r in self.readers[1:]:
            got &= set(r.task_ids)
        return frozenset(got)

    def allows(self, row: dict) -> bool:
        """Whether one Synapse item may go into the answer: every reader may see it."""
        if self.nothing:
            return False
        if str(row.get("source") or "") not in SOURCES:
            return False
        if str(row.get("sensitivity") or "unlabelled") in NEVER_SENSITIVITY:
            return False
        return all(_reader_allows(r, row) for r in self.readers)


def _folder_of(row: dict) -> str:
    """The workspace folder an item is in: a task's own, or a file's."""
    thread = str((row.get("meta") or {}).get("thread") or "")
    if thread.startswith("task:"):
        return thread[5:].strip("/")
    key = str(row.get("source_key") or "")
    if key.startswith("file:"):
        return key[5:].rsplit("/", 1)[0].strip("/")
    return ""


def _inside(folder: str, folders) -> bool:
    return bool(folder) and any(folder == f or folder.startswith(f + "/") for f in folders if f)


def _reader_allows(r: Reader, row: dict) -> bool:
    source = str(row.get("source") or "")
    if source in WORKSPACE and _inside(_folder_of(row), r.folders):
        return True
    return str(row.get("sensitivity") or "") == "normal" and bool(
        set(row.get("can_read") or ()) & r.principals)


def _reader(who, contact, *, case_tasks=()) -> Reader:
    """What one set-up person may see, worked out now."""
    from . import silos, task_access
    from . import trusted as trust
    from .synapse import search

    if not set_up(contact):
        return Reader(name=getattr(contact, "name", "") or "")
    folders: list[str] = []
    ids: frozenset = frozenset()
    store, root = task_access._store(), task_access._root()
    if store is not None and root:
        grants = trust.Grants(store, root, contact, case_tasks=case_tasks, owner=who)
        ids = frozenset(grants.reachable(read=True))
        folders = sorted({(grants.tree.rows[i].get("folder") or "").strip("/") for i in ids
                          if grants.tree.rows.get(i)} - {""})
    asker = ""
    if contact.contact_id:
        asker = silos.asker(silos.limited(who.user_id, who.org_id, contact.sees), contact.contact_id)
    return Reader(name=contact.name, asker=asker,
                  principals=frozenset(search.readers_for(asker)) if asker else frozenset(),
                  folders=tuple(folders), task_ids=ids, set_up=True)


def reach_of(who, case, contact=None) -> Reach:
    """Everybody who reads a Slack case's answer, and what each may see, as trust stands now."""
    from . import mail_cases
    from . import trusted as trust

    email = case.email or {}
    store = trust.TrustStore()
    asker = contact if contact is not None else (
        store.get(who.user_id, who.org_id, case.contact_id) if case.contact_id else None)
    outsiders: list[str] = []
    unknown = bool(email.get("slack_audience_unknown"))
    conn = slack.connection(who.org_id)
    others = []
    for sid in email.get("slack_audience") or ():
        one = contact_of(who, conn, sid) if conn is not None else None
        if set_up(one):
            others.append(one)
        else:
            outsiders.append(slack.name_of(conn, sid) if conn is not None else sid)
    where = str(email.get("slack_where") or "")
    if outsiders or unknown:
        # Somebody reading it may see nothing, so nothing goes in: what the others may see is moot.
        return Reach(readers=[Reader(name=getattr(asker, "name", "") or "", set_up=set_up(asker))]
                     + [Reader(name=o.name, set_up=True) for o in others], outsiders=outsiders, where=where,
                     unknown=unknown)
    readers = [_reader(who, asker, case_tasks=mail_cases.own_paths(case))]
    readers += [_reader(who, one) for one in others]
    return Reach(readers=readers, outsiders=outsiders, where=where)


def narrowed(who, case, contact):
    """The contact of a Slack case as its answer may use them: never the owner's inbox, and in a
    conversation others read, only the silos and the tasks every one of them may see too."""
    if contact is None or not slack.on_slack(case):
        return contact
    changes: dict = {"inbox_scope": "none", "inbox_from": []}
    audience_ids = (case.email or {}).get("slack_audience") or []
    if audience_ids or (case.email or {}).get("slack_audience_unknown"):
        try:
            reach = reach_of(who, case, contact)
        except Exception:  # noqa: BLE001 - not worked out: nothing of his goes in, never more
            log.exception("slack: who reads case %s's answer could not be worked out", case.id)
            reach = Reach(readers=[], unknown=True)
        changes["within"] = reach.within()
        changes["sees"] = _common_silos(who, reach)
    return dataclasses.replace(contact, **changes)


def _common_silos(who, reach: Reach) -> list:
    """The silos every reader may see: none when anybody may see nothing."""
    from . import silos

    if reach.nothing:
        return []
    got = set(silos.keys(who.user_id, who.org_id))
    for r in reach.readers:
        limit = silos.split(r.asker)[0] if r.asker else frozenset()
        if limit is not None:
            got &= set(limit)
    return sorted(got)


# --- what they may see, found and read -------------------------------------------------------


def _master(who) -> dict | None:
    from .synapse import db, master

    try:
        return master.of(who.org_id, who.user_id) if db.ready() else None
    except Exception:  # noqa: BLE001 - no Master here: nothing to find, never a failure
        log.exception("slack: Synapse Master could not be opened")
        return None


def _rows(ds: dict, ids: list[str]) -> dict[str, dict]:
    from .synapse import db

    if not ids:
        return {}
    got = db.rows("SELECT id, kind, title, source, source_key, sensitivity, can_read, meta, silos, said_at, tier "
                  "FROM synapse.item WHERE dataset_id = ANY(synapse.scope(%s)) AND id = ANY(%s::uuid[]) "
                  "AND deleted_at IS NULL", (ds["id"], list(ids)))
    return {str(r["id"]): r for r in got}


def keep(ds: dict, reach: Reach, ids: list[str]) -> list[str]:
    """These items, best first as given, without any one somebody reading the answer may not see."""
    rows = _rows(ds, [str(i) for i in ids])
    return [str(i) for i in ids if str(i) in rows and reach.allows(rows[str(i)])]


def find(who, reach: Reach, words, *, most: int = FIND_MOST) -> str:
    """`find_for_them`: what holds every word, of what everybody reading the answer may see."""
    from .synapse import chat as synapse_chat
    from .synapse import search
    from .synapse import text as tx

    ds = _master(who)
    if ds is None:
        return "There is no memory to look in on this server."
    if reach.nothing:
        return ("Nothing: " + _nothing_said(reach) + " So nothing of ‹owner›'s may go into this answer.")
    words = [w for w in (str(x).strip() for x in words or ()) if w]
    if not words:
        return "Give the words to look for."
    found = search.containing(ds["id"], words, limit=LOOKED_AT,
                              kinds_out=("person", "rule", "topic", "layer", "mail", "event", "note"))
    kept = keep(ds, reach, [str(r["id"]) for r in found])[:max(1, min(int(most or FIND_MOST), 30))]
    if not kept:
        return (f"Nothing that {_whom(reach)} may see holds every one of: {' '.join(words)}. Do not guess "
                "and do not answer from anything else.")
    rows = {str(r["id"]): r for r in found}
    lines = [f"- {synapse_chat._short(rows[i])}, {tx.item_date(rows[i])}" for i in kept]
    return ("What " + _whom(reach) + " may see that holds those words (read one whole with item):\n"
            + "\n".join(lines))


def read(who, reach: Reach, ref: str) -> str:
    """`find_for_them` with an item: that item whole, when everybody reading the answer may see it."""
    from .synapse import chat as synapse_chat
    from .synapse import db

    ds = _master(who)
    if ds is None:
        return "There is no memory to look in on this server."
    ref = str(ref or "").strip()
    row = db.row("SELECT * FROM synapse.item WHERE dataset_id = %s AND deleted_at IS NULL AND "
                 "(id::text = %s OR source_key = %s) LIMIT 1", (ds["id"], ref, ref)) if ref else None
    if row is None or not reach.allows(row):
        return f"There is no item {ref} that {_whom(reach)} may see."
    text = str(row.get("body") or row.get("raw") or "")
    if row.get("kind") == "meeting":
        text = _meeting_text(ds, row, text)
    return (synapse_chat._short(row) + "\n" + (text[:READ_CHARS] + (
        f"\n... ({len(text) - READ_CHARS} more characters)" if len(text) > READ_CHARS else "") or "(no text)"))


def _meeting_text(ds: dict, row: dict, text: str) -> str:
    """A meeting's summary and decisions as the library has them, and its transcript after."""
    from .synapse import db

    got = db.rows("SELECT text FROM synapse.passage WHERE dataset_id = %s AND item_id = %s AND part = 'transcript' "
                  "ORDER BY seq LIMIT 400", (ds["id"], row["id"]))
    said = "\n".join(str(r["text"]) for r in got)
    return text + ("\n\nTranscript:\n" + said if said else "")


def _whom(reach: Reach) -> str:
    names = [first_name(r.name) for r in reach.readers]
    if len(names) == 1:
        return names[0]
    return "everybody reading the answer (" + ", ".join(names) + ")"


def _nothing_said(reach: Reach) -> str:
    if reach.unknown:
        return (f"Slack would not say who is in {reach.where or 'the conversation'}, so who reads the "
                "answer is not known.")
    if reach.outsiders:
        return (f"{', '.join(reach.outsiders)} in {reach.where or 'the conversation'} "
                f"{'is' if len(reach.outsiders) == 1 else 'are'} not set up by ‹owner› and may see "
                "nothing of ‹his›.")
    return "the person asking is not set up by ‹owner›."


def recall_block(who, case) -> str:
    """Automatic recall on their words, with only what everybody reading the answer may see: the
    background the reading may answer from, or ""."""
    from .synapse import autorecall

    if not autorecall.on(who.org_id):
        return ""
    ds = _master(who)
    text = str((case.email or {}).get("body") or "").strip()
    if ds is None or not text:
        return ""
    reach = reach_of(who, case)
    if reach.nothing:
        return ""
    began = time.monotonic()
    try:
        got = autorecall.run(ds, text[:2000], ceiling=RECALL_CEILING_S, timeout=RECALL_CEILING_S)
    except Exception:  # noqa: BLE001 - more memory is never worth a case
        log.exception("slack: the look-up on a teammate's words failed")
        return ""
    found = list(got.get("items") or [])
    kept = keep(ds, reach, found)
    log.info("slack: recall on case %s's words found %d item(s), %d %s may see, in %d ms", case.id, len(found),
             len(kept), "everybody reading it" if reach.shared else "they", int((time.monotonic() - began) * 1000))
    if not kept:
        return ""
    made = autorecall.block(ds, {**got, "items": kept},
                            label=f"What {_whom(reach)} may see that their message may be about - looked up "
                                  "automatically on their words, before you read it. It may or may not be "
                                  "relevant.")
    return made.get("text") or ""


def brief_lines(who, case, owner: str) -> list[str]:
    """What the reading and the start of a Slack case are told about what the answer may hold."""
    reach = reach_of(who, case)
    out = ["", "What the answer may hold. It goes to "
           + (case.sender_name if not reach.shared else "everybody in " + (reach.where or "the conversation"))
           + f". Never put in it anything from {owner}'s mail, ‹his› own Slack direct messages, ‹his› "
           "conversations with Rouh, ‹his› notes, ‹his› calendar, ‹his› contacts, ‹his› money or ‹his› health: "
           "you have no way to read those here, and nothing you know of them goes in."]
    if reach.nothing:
        out.append(f"Nothing of {owner}'s work may go into this answer: {_nothing_said(reach)} Answer "
                   "only what needs nothing of ‹his›, and if they want more, say you can answer them "
                   "in a direct message to Rouh.")
        return out
    out.append(
        "Answer questions about ‹his› work from what " + _whom(reach) + " may see, and from nothing else: "
        "find_for_them (words, or one item whole) finds their meetings in the meeting library, the "
        "tasks they may read and the files in them; read_granted_tasks reads a task's notes and files. "
        "Answer such a question in the reply: one about ‹his› tasks or their files is grant tasks, "
        "with no task number (task is only for adding to or changing one); one answered from "
        "their meetings alone is grant none. When they cannot see what they ask about, say so "
        "plainly in the reply and never guess.")
    if reach.shared:
        out.append("Everybody in " + (reach.where or "it") + " reads the answer: "
                   + ", ".join(r.name for r in reach.readers)
                   + ". Both tools give only what every one of them may see.")
    return out


# --- somebody not set up --------------------------------------------------------------------


def stranger_text(owner: str, name: str) -> str:
    return STRANGER.format(first=first_name(name), owner=owner)


def tell_owner(who, conn, *, slack_id: str, name: str, email: str, contact=None, where: str = "",
               said: str = "") -> bool:
    """The owner told, once for each person, that somebody they have not set up asked Rouh on Slack,
    with the button that opens Trusted contacts ready to set them up. False when they were told before."""
    from urllib.parse import urlencode

    from . import genes, notices

    route = genes.BY_ID["trusted-contacts"]["route"]
    if contact is not None and not getattr(contact, "implicit", True):
        link, label = f"{route}/{contact.id}", "Set them up"
        why = f"{name} is on your Trusted contacts, switched off."
    else:
        query = {k: v for k, v in (("add", email), ("name", name)) if v}
        link, label = route + ("?" + urlencode(query) if query else ""), "Set them up"
        why = (f"{name} ({email}) is not on your Trusted contacts." if email else
               f"Slack does not give {name}'s address, so they cannot be matched to a contact.")
    body = (f"{why} Rouh told them it can only help people you have set up. "
            f"They asked in {where or 'Slack'}: “{' '.join(str(said or '').split())[:240]}”")
    got = notices.post(who, title=f"{name} asked Rouh on Slack", body=body, link=link, link_label=label,
                       kind="slack", key=f"slack-not-set-up:{conn.team_id}:{slack_id}",
                       phone_text=f"{name} asked Rouh on Slack and is not set up. {why}")
    return got is not None


__all__ = ["Reach", "Reader", "SOURCES", "STRANGER", "audience", "brief_lines", "contact_of", "find", "keep",
           "narrowed", "reach_of", "read", "recall_block", "set_up", "stranger_text", "tell_owner"]
