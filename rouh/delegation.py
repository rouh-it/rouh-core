"""May decide for: a trusted contact's authority over a goal, a quest or a task (`DELEGATION.md`).

Petar, 9 October 2026, by voice: "You do the research, she asks for more research if needed,
she makes the decisions, approves goal steps and modifies plan and quest. If needed plan
modification to yourself with extra permissions that can be assigned to trusted contacts,
assign to [her]." So any trusted contact can be given, by the owner alone, the authority to
decide for them over named pieces of work, and nothing else.

Four rules hold everything here:

- **A grant is explicit, by object, and the owner's.** `grant` and `revoke` are his press in
  Settings or his own words to Rouh (`tools.ToolRegistry._delegate`). The one thing Rouh
  does by itself is keep a promise he approved (`extend`): a grant's `pending` words name
  work not made yet, and once it is, Rouh extends the grant to it, and only to goals and
  quests made after the promise was.
- **Every check is made at the moment of acting.** `Scope.of` reads the rows as they are,
  so a revoke, a contact switched off or an address taken off stops the next action.
- **Some things are never theirs** (`NEVER`): money, deleting, publishing and sharing,
  sending or committing the owner to anybody, and Rouh's own code, rules and permissions.
  What falls there becomes the owner's, with their recommendation and their words on it
  (`hold_for_owner`).
- **Everything is written down, with their exact words** (`models.DelegateAct`), and the
  owner can undo it (`undo`).

They act by email through their case (`rouh/mail_cases.py`), with the case tool
`delegate_act` (`act`), which checks who sent it and that the words are theirs every time.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass, field

from . import owner as owners

log = logging.getLogger("rouh.delegation")

KINDS = ("goal", "quest", "task", "step")
KIND_WORDS = {"goal": "goal", "quest": "quest", "task": "task", "step": "step"}
POWERS = ("decide", "edit", "read")
ACTIVE, REVOKED = "active", "revoked"

#: The decisions a delegate may answer, by source: a goal step's, a task's, and a quest's
#: approvals. Every other source is the owner's alone (`covers_decision`).
DECISION_SOURCES = ("goal", "task", "approval")

#: What stays the owner's, even inside a grant, in the words the delegate is told.
NEVER: dict[str, str] = {
    "money": "anything that spends money: a quest's budget or spend cap, its ledger, the card "
             "vault, Stripe, paying a fee",
    "delete": "resetting or deleting a quest, deleting a task or a goal",
    "publish": "publishing anything, sharing a page with anybody further, or a public link",
    "send": "sending mail or messages to anybody else on ‹owner›'s behalf, or anything in "
            "‹owner›'s name",
    "commit": "committing ‹owner› or ‹company› to anybody: signing, filing, registering, "
              "applying, engaging a provider, agreeing terms",
    "rouh": "changing Rouh's code, rules or permissions, or anybody's grants",
    "outside": "anything outside what was granted: ‹owner›'s other tasks, ‹his› mail, calendar "
               "and private data",
}
#: Act names the tool refuses outright, and which part of `NEVER` each is.
NEVER_ACTS = {"budget": "money", "spend_cap": "money", "ledger": "money", "pay": "money",
              "buy": "money", "reset": "delete", "delete": "delete", "remove_goal": "delete",
              "publish": "publish", "share": "publish", "public": "publish", "send": "send",
              "email": "send", "mail": "send", "sign": "commit", "file": "commit",
              "register": "commit", "apply": "commit", "grant": "rouh", "permissions": "rouh",
              "rules": "rouh", "code": "rouh"}

#: The parts of a quest's brief a delegate may write.
QUEST_PARTS = ("goal", "rules", "plan", "notebook")
#: What a delegate may change on a step, as `goals.change_step` takes it.
STEP_FIELDS = ("title", "who", "how", "challenge", "solution", "outcome", "kind", "ask",
               "options", "where")

#: The most of their words kept on one action.
WORDS_MOST = 4000


class Refused(ValueError):
    """A sentence to say back: nothing was done."""


class _Who:
    def __init__(self, user_id, org_id):
        self.user_id, self.org_id = str(user_id), str(org_id)


def _models():
    from . import models

    return models


def _store():
    from . import owning

    return owning.store()


def _tree():
    from . import trusted

    st = _store()
    return trusted.Tree(st) if st is not None else None


def _now() -> float:
    return time.time()


def _norm(text) -> str:
    """Words as compared: lower case, quotes and dashes made plain, spaces folded."""
    text = str(text or "").lower()
    for a, b in (("’", "'"), ("‘", "'"), ("“", '"'), ("”", '"'),
                 ("–", "-"), ("—", "-"), (" ", " ")):
        text = text.replace(a, b)
    return " ".join(text.split())


def words_are_theirs(words: str, written: str) -> bool:
    """Whether `words` were written by them: found, whole, in what they wrote themselves.

    Spaces, case, curly quotes and a full stop at either end do not matter; anything else
    does. Too few words to mean anything (under two characters) is never theirs."""
    want = _norm(words).strip(" .,;:!?\"'")
    return len(want) >= 2 and want in _norm(written)


# --- the grants ---------------------------------------------------------------------------


def _task_of(ref):
    """The task or step a reference names: its number ("98"), a step's as it is said
    ("98-03", "98 03"), or its object id. None when there is none."""
    from . import pinning
    from .models import Task

    if ref.isdigit():
        return Task.objects.filter(number=int(ref)).first()
    if re.fullmatch(r"\d+(?:\s*[-.\s]\s*\d+)+", ref):
        found = pinning.find(ref)
        return Task.objects.filter(id=found["id"]).first() if found.get("ok") else None
    return Task.objects.filter(id=ref).first()


def _is_step(task) -> bool:
    """Whether a task row is a step: a task inside another task."""
    st = _store()
    owner = st.owner_of("task", task.id) if st is not None else None
    return bool(owner) and owner[0] == "task"


def step_code(task_id) -> str:
    """What a step is called by, "98-03", out of its folder; "" when it has none."""
    from . import searching
    from .models import Task

    folder = Task.objects.filter(id=str(task_id or "")).values_list("folder", flat=True).first()
    return searching.number_of_folder(folder or "")


def _target_of(kind: str, ref, who) -> tuple[str, int, str]:
    """(target, number, title) for a goal, quest, task or step named by number, id or
    record id. A step's number is the task it is in, and what it is called by is in its
    folder (`step_code`)."""
    from . import goals, quests

    ref = str(ref or "").strip().lstrip("#")
    if not ref:
        raise Refused(f"Which {kind}? Give its number.")
    if kind == "quest":
        if ref.startswith("record:"):
            row = quests.get(who, ref.split(":", 1)[1])
        else:
            row = quests.by_number(who, ref) if ref.isdigit() else None
            if row is None:
                row = quests.get(who, ref) if ref.isdigit() else None
        if row is None:
            raise Refused(f"There is no quest {ref}.")
        return str(row.id), int(row.task_number or 0), row.title
    task = _task_of(ref)
    if task is None:
        raise Refused(f"There is no {'step' if kind == 'step' else 'task'} {ref}.")
    if kind == "goal":
        folder = goals._folder(task)
        if folder is None or not goals.is_goal(goals._meta(folder)):
            raise Refused(f"Task {task.number} is not a goal.")
    if kind == "step":
        if not _is_step(task):
            raise Refused(f"{task.number or ref} “{task.title}” is a task, not a step.")
        number = _top_number(task.id)
        return task.id, number, task.title
    if kind == "task" and _is_step(task):
        raise Refused(f"{step_code(task.id) or ref} “{task.title}” is a step: grant it as a step.")
    return task.id, int(task.number or 0), task.title


def _top_number(task_id) -> int:
    """The number of the task a step is in, however deep."""
    st = _store()
    if st is None:
        return 0
    seen, at = set(), str(task_id)
    while at and at not in seen:
        seen.add(at)
        row = st.get_task(at)
        if row is not None and row.number is not None:
            return int(row.number)
        owner = st.owner_of("task", at)
        at = owner[1] if owner and owner[0] == "task" else ""
    return 0


@dataclass
class Grant:
    """One record of the one permission (`rouh/task_access.py`) held by a trusted contact on a
    quest, a goal, a task or a step, as this module names it: `id` is the record's token."""

    id: str
    contact_id: int
    kind: str
    #: The goal's, task's or step's id, or the quest's record id.
    target: str
    #: The task the record is on (a quest's own task).
    task_id: str
    number: int
    title: str
    #: "decide", "edit" or "read".
    power: str
    pending: str = ""
    granted_by: str = ""
    created_at: float = 0.0
    rel: str = ""
    email: str = ""
    state: str = ACTIVE
    revoked_at: float = 0.0


#: A level as a grant says it, and back.
POWER_OF = {"view": "read", "edit": "edit", "decide": "decide"}
LEVEL_OF = {"read": "view", "edit": "edit", "decide": "decide"}


def _kind_of(tree, root, ident: str, who) -> tuple[str, str]:
    """(kind, target) of the task a record is on: a quest by its record id, a step, a goal, or
    a task."""
    from . import goals, quests
    from . import trusted as trust

    q = next((q for q in quests.all_of(who) if getattr(q, "task_id", "") == ident), None)
    if q is not None:
        return "quest", str(q.id)
    if tree.rows.get(tree.owner.get(ident, ""), {}).get("type") == "task":
        return "step", ident
    folder = (tree.rows.get(ident) or {}).get("folder") or ""
    if folder and goals.is_goal(trust.task_meta(root, folder)):
        return "goal", ident
    return "task", ident


def _records(user_id, org_id, contact) -> list[dict]:
    """Every record of a contact's on the owner's tasks, goals, quests and steps, switched on or
    not: the ones a person chose, never a tick's."""
    from . import sharing, taskshare, task_access

    if contact is None or not getattr(contact, "addresses", None):
        return []
    return [p for p in sharing.Guests().with_addresses(_Who(user_id, org_id), contact.addresses)
            if taskshare.is_task(p["rel"]) and p.get("via") != task_access.TICK]


def _grants_of(user_id, org_id, contact, tree=None) -> list[Grant]:
    from . import taskshare, task_access

    found = _records(user_id, org_id, contact)
    if not found:
        return []
    tree = tree if tree is not None else _tree()
    root = task_access._root()
    if tree is None or not root:
        return []
    who = _Who(user_id, org_id)
    folders = {(r.get("folder") or "").strip("/"): i for i, r in tree.rows.items()
               if r.get("type") == "task" and r.get("folder")}
    out = []
    for p in found:
        ident = folders.get(taskshare.folder_of(p["rel"]).strip("/"), "")
        if not ident:
            continue
        kind, target = _kind_of(tree, root, ident, who)
        number = 0
        if kind == "step":
            number = _top_number(ident)
        else:
            raw = tree.rows[ident].get("number")
            number = int(raw) if raw is not None else 0
        out.append(Grant(id=p["token"], contact_id=contact.id, kind=kind, target=target,
                         task_id=ident, number=number,
                         title=tree.rows[ident].get("title") or p.get("title") or "",
                         power=POWER_OF.get(p["role"], "read"), pending=p.get("pending") or "",
                         granted_by=p.get("granted_by") or "", created_at=p.get("created_at") or 0,
                         rel=p["rel"], email=p["email"]))
    return out


def _row_dict(d) -> dict:
    from . import quests

    href = ""
    if d.kind == "quest" and d.number:
        href = quests.address(_QuestRef(d.number))
    else:
        from .models import Task

        folder = Task.objects.filter(id=d.target).values_list("folder", flat=True).first()
        if folder:
            from . import goals

            href = "/task/" + folder + ("/" + goals.PAGE if d.kind == "goal" else "")
    return {"id": d.id, "contact": d.contact_id, "kind": d.kind, "target": d.target,
            "number": d.number, "code": code_of_row(d), "title": d.title, "power": d.power,
            "pending": d.pending, "state": d.state,
            "granted_by": owners.word(d.granted_by) if d.granted_by else "",
            "created_at": d.created_at, "revoked_at": d.revoked_at, "href": href,
            "name": name_of_row(d)}


class _QuestRef:
    def __init__(self, number):
        self.task_number = number


def code_of_row(d) -> str:
    """What a grant's work is called by: "101" for a goal, "98-03" for a step, or "" when
    it has no number. A step gone since says the task it was in: "in 98"."""
    kind = d["kind"] if isinstance(d, dict) else d.kind
    number = d["number"] if isinstance(d, dict) else d.number
    if kind == "step":
        if isinstance(d, dict) and d.get("code"):
            return d["code"]
        target = d["target"] if isinstance(d, dict) else d.target
        return step_code(target) or (f"in {number}" if number else "")
    return str(number) if number else ""


def name_of_row(d) -> str:
    """"goal 101 “Legal side of open-sourcing Rouh”", or "step 98-03 “Draft the
    licence”", as it is said everywhere."""
    kind = d["kind"] if isinstance(d, dict) else d.kind
    title = d["title"] if isinstance(d, dict) else d.title
    code = code_of_row(d)
    return f"{KIND_WORDS.get(kind, kind)} {code} “{title}”" if code else \
        f"{KIND_WORDS.get(kind, kind)} “{title}”"


def rows(user_id, org_id, contact_id=None, *, active: bool = True) -> list[Grant]:
    """The records trusted contacts hold on the owner's quests, goals, tasks and steps: one
    contact's, or everybody's. `active` is kept for its callers; a record taken away is gone,
    and what it was is in the record of acts."""
    from . import trusted

    store = trusted.TrustStore()
    contacts = ([store.get(str(user_id), str(org_id), contact_id)] if contact_id is not None
                else store.all(str(user_id), str(org_id)))
    tree = _tree()
    out: list[Grant] = []
    for c in contacts:
        out += _grants_of(user_id, org_id, c, tree=tree)
    return sorted(out, key=lambda d: (d.kind, d.number, d.id))


def listing(user_id, org_id, contact_id) -> list[dict]:
    return [_row_dict(d) for d in rows(user_id, org_id, contact_id)]


def _contact(user_id, org_id, contact_id):
    from . import trusted

    return trusted.TrustStore().get(str(user_id), str(org_id), contact_id)


def find_contact(user_id, org_id, said):
    """A trusted contact by their id, name or one of their addresses."""
    from . import trusted

    said = str(said or "").strip()
    if not said:
        return None
    every = trusted.TrustStore().all(str(user_id), str(org_id))
    if said.isdigit():
        hit = next((c for c in every if str(c.id) == said), None)
        if hit is not None:
            return hit
    low = said.lower()
    hit = next((c for c in every if low in [a.lower() for a in c.addresses]), None)
    if hit is not None:
        return hit
    named = [c for c in every if low == c.name.lower()] or \
        [c for c in every if low in c.name.lower()] or \
        [c for c in every if any(w and w in c.name.lower().split() for w in low.split())]
    return named[0] if len(named) == 1 else None


def log_act(user_id, org_id, contact, act: str, *, grant=None, target_kind: str = "",
            target: str = "", number: int = 0, title: str = "", words: str = "",
            said: str = "", asked: dict | None = None, outcome: str = "done", why: str = "",
            decision=None, case_id=None, channel: str = "", undo: dict | None = None,
            key: str = ""):
    m = _models()
    return m.DelegateAct.objects.create(
        user_id=str(user_id), org_id=str(org_id),
        contact_id=getattr(contact, "id", None) or None,
        contact_name=getattr(contact, "name", "") or "",
        grant=str(getattr(grant, "id", grant) or ""), act=act, target_kind=target_kind,
        target=str(target or ""), number=int(number or 0), title=str(title or "")[:300],
        words=str(words or "")[:WORDS_MOST], said=str(owners.say(said or "", user_id))[:2000],
        asked=asked or {}, outcome=outcome, why=str(owners.say(why or "", user_id))[:2000],
        decision_id=(decision.get("id") if isinstance(decision, dict)
                     else getattr(decision, "id", None)),
        handle=str((decision.get("number") if isinstance(decision, dict)
                    else getattr(decision, "number", None)) or ""),
        case_id=case_id, channel=channel, undo=undo or {}, key=key, at=_now())


#: Said after a grant or revoke something scheduled made on the person's stored words, so its
#: line on the contact's page and in the record says it was not a press of theirs just then.
_BY_CLOCKWORK = {"clockwork": " Done by Clockwork, on your own words stored with it."}

#: What each level lets them do, as a grant says it.
_POWER_SAID = {"decide": "authority to decide for", "edit": "editing of", "read": "reading of"}


def grant(who, contact_id, kind: str, ref, *, power: str = "decide", pending: str | None = "",
          by: str = "owner", channel: str = "settings", words: str = ""):
    """Give a trusted contact a level on one goal, quest, task or step: decide (the default),
    edit or read. It is a record of the one permission (`rouh/task_access.py`), the same one the
    Share panel and the contact's page write, and it reaches what is under it and, for a quest,
    the goals it names. The owner's alone (`extend` is the promise Rouh keeps). Answers the
    `Grant`. `words` are his own that asked for it, when it came through Rouh's `delegate` tool,
    kept on the act; `channel` "clockwork" is something scheduled doing it on his stored words.

    A step is granted on its own, with what is under it, and not the task it is in: they
    decide its decisions and read its folder, its notes and pages, and nothing else of the
    task."""
    from . import quests, task_access

    kind = str(kind or "").strip().lower()
    if kind not in KINDS:
        raise Refused("A grant is over a goal, a quest, a task or a step.")
    power = power if power in POWERS else "decide"
    contact = _contact(who.user_id, who.org_id, contact_id)
    if contact is None:
        raise Refused("That trusted contact is not one of yours.")
    if not contact.trusted:
        raise Refused(f"{contact.name} is switched off. Trust them first.")
    if kind == "task":
        # A step named as a task is granted as the step it is. Never the other way: a task
        # named as a step is refused, because granting it would reach more than was asked.
        found = _task_of(str(ref or "").strip().lstrip("#"))
        if found is not None and _is_step(found):
            kind = "step"
    target, number, title = _target_of(kind, ref, who)
    ident = target
    if kind == "quest":
        q = quests.get(who, target)
        ident = getattr(q, "task_id", "") if q is not None else ""
        if not ident:
            raise Refused(f"Quest {number} has no task to give anybody.")
    try:
        task_access.set_level(who, contact, ident, LEVEL_OF[power],
                              pending=None if pending is None else
                              " ".join(str(pending or "").split())[:600],
                              granted_by="rouh" if by == "rouh" else "owner")
    except ValueError as exc:
        raise Refused(str(exc)) from None
    row = next((g for g in _grants_of(who.user_id, who.org_id, contact) if g.task_id == ident),
               None)
    if row is None:
        raise Refused("It could not be given: the record was not there afterwards.")
    log_act(who.user_id, who.org_id, contact, "extend" if by == "rouh" else "grant",
            grant=row, target_kind=row.kind, target=row.target, number=row.number,
            title=row.title,
            said=(f"{'Rouh extended' if by == 'rouh' else 'You gave'} {contact.name} "
                  f"{_POWER_SAID[power]} {name_of_row(row)}." + _BY_CLOCKWORK.get(channel, "")),
            channel=channel, words=words)
    return row


def _grant_row(who, token):
    """The record a grant id names, with the contact it is for, or (None, None)."""
    from .models import PageGuest
    from . import trusted

    p = PageGuest.objects.filter(user_id=str(who.user_id), org_id=str(who.org_id),
                                 token=str(token or "")).first()
    if p is None or not p.rel.startswith("_task/"):
        return None, None
    for c in trusted.TrustStore().all(str(who.user_id), str(who.org_id)):
        if p.email in [a.lower() for a in c.addresses]:
            got = next((g for g in _grants_of(who.user_id, who.org_id, c) if g.id == p.token),
                       None)
            return got, c
    return None, None


def revoke(who, delegation_id, *, channel: str = "settings", words: str = "") -> str:
    """Take a grant back, at once: its record goes. What a record above it gives still holds,
    and the sentence says so."""
    from . import task_access

    row, contact = _grant_row(who, delegation_id)
    if row is None:
        raise Refused("That grant is not there any more.")
    try:
        left = task_access.set_level(who, contact, row.task_id, task_access.NONE)
    except ValueError:
        from . import sharing

        sharing.Guests().remove(who, row.id)
        left = ""
    said = (f"{contact.name if contact else 'They'} no longer "
            f"{'decides for' if row.power == 'decide' else 'edits' if row.power == 'edit' else 'reads'}"
            f" {name_of_row(row)} by this grant."
            + (" " + left.split(", and ", 1)[1][:1].upper() + left.split(", and ", 1)[1][1:]
               if ", and they still" in left else "")
            + _BY_CLOCKWORK.get(channel, ""))
    log_act(who.user_id, who.org_id, contact, "revoke", grant=row, target_kind=row.kind,
            target=row.target, number=row.number, title=row.title, said=said, channel=channel,
            words=words)
    return said


def set_on(who, contact_id, ident: str, level: str, *, channel: str = "settings") -> str:
    """One row of a contact's page set to a level - "view", "edit" or "decide" - or to none
    (""), as the one control there says it: a record of the one permission made, turned or taken
    away, through `grant` and `revoke`, so the record of acts keeps it. A promise on the record
    stays. The sentence of what it is now; Refused says why it could not be."""
    from . import task_access

    contact = _contact(who.user_id, who.org_id, contact_id)
    if contact is None:
        raise Refused("That trusted contact is not one of yours.")
    level = str(level or "").strip().lower()
    if level in ("none", "read"):
        level = {"none": "", "read": "view"}[level]
    if level not in ("", "view", "edit", "decide"):
        raise Refused("A level is none, read, edit or decide.")
    if not level:
        row = next((g for g in _grants_of(who.user_id, who.org_id, contact)
                    if g.task_id == ident), None)
        if row is not None:
            return revoke(who, row.id, channel=channel)
        # Nothing of its own: a task they asked for is theirs by that, and is taken back.
        try:
            return task_access.set_level(who, contact, ident, task_access.NONE)
        except ValueError as exc:
            raise Refused(str(exc)) from None
    tree = _tree()
    if tree is None or ident not in tree.rows:
        raise Refused("That is not one of your tasks.")
    kind, target = _kind_of(tree, task_access._root(), ident, who)
    row = grant(who, contact_id, kind, f"record:{target}" if kind == "quest" else ident,
                power=POWER_OF[level], pending=None, channel=channel)
    return (f"{contact.name} " + {"decide": "decides for", "edit": "may edit",
                                  "read": "may read"}[row.power] + f" {name_of_row(row)}.")


def set_pending(who, delegation_id, words: str) -> None:
    from .models import PageGuest

    PageGuest.objects.filter(user_id=str(who.user_id), org_id=str(who.org_id),
                             token=str(delegation_id or ""), rel__startswith="_task/").update(
        pending=" ".join(str(words or "").split())[:600])


def promises(user_id, org_id, contact_id=None) -> list:
    return [d for d in rows(user_id, org_id, contact_id) if d.pending]


def extend(who, contact_said, *, goals=(), quests=()) -> list[str]:
    """Keep a promise the owner approved: authority over the goals and quests named, for a
    contact who holds one (`PageGuest.pending`). Only goals and quests, only ones made after
    the promise was. Answers one sentence for each."""
    from . import quests as quest_mod
    from .models import Task

    contact = find_contact(who.user_id, who.org_id, contact_said)
    if contact is None:
        raise Refused("Which trusted contact? Give their name as on Trusted contacts.")
    held = promises(who.user_id, who.org_id, contact.id)
    if not held:
        raise Refused(f"{contact.name} holds no promise of authority to extend. Only ‹owner› "
                      "grants new authority.")
    since = min(d.created_at for d in held)
    out = []
    for kind, refs in (("goal", goals or ()), ("quest", quests or ())):
        for ref in refs:
            try:
                target, number, _title = _target_of(kind, ref, who)
                if kind == "goal":
                    made = Task.objects.filter(id=target).values_list("created_at", flat=True)
                    made_at = float(made[0] or 0) if made else 0.0
                else:
                    q = quest_mod.get(who, target)
                    made_at = float(getattr(q, "created_at", 0) or 0)
                if made_at and made_at < since:
                    raise Refused(f"{kind} {number} was made before the promise, so it is not "
                                  "what it promised; only ‹owner› can grant it.")
                grant(who, contact.id, kind, f"record:{target}" if kind == "quest"
                      else number or target, by="rouh", channel="rouh")
                out.append(f"{contact.name} now decides for {kind} {number}.")
            except Refused as exc:
                out.append(f"Not {kind} {ref}: {exc}")
    return out


# --- what a grant reaches -----------------------------------------------------------------


@dataclass
class Scope:
    """What one contact may decide, and read, worked out from the one record as it is now
    (`rouh/task_access.py`): decide on a task is decide on everything that inherits it."""

    contact: object = None
    grants: list = field(default_factory=list)
    #: Every task they may decide for, the goal or task granted and all under it.
    task_ids: set = field(default_factory=set)
    #: The goals among them (their tasks' ids) and the quests (record ids).
    goal_ids: set = field(default_factory=set)
    quest_ids: set = field(default_factory=set)
    #: Every task they may read, at any level.
    read_ids: set = field(default_factory=set)
    access: object = None

    @classmethod
    def of(cls, user_id, org_id, contact, tree=None) -> "Scope":
        """Their scope now. Nothing for a contact switched off, or with no address left."""
        from . import quests, task_access

        scope = cls(contact=contact)
        if contact is None or getattr(contact, "implicit", False) or \
                not getattr(contact, "trusted", False) or not contact.addresses:
            return scope
        store, root = task_access._store(), task_access._root()
        if store is None or not root:
            return scope
        who = _Who(user_id, org_id)
        tree = tree if tree is not None else _tree()
        access = task_access.Access(store, root, contact, who, tree=tree)
        scope.access = access
        scope.grants = _grants_of(user_id, org_id, contact, tree=access.tree)
        levels = access.levels()
        scope.read_ids = set(levels)
        scope.task_ids = {i for i, lvl in levels.items() if lvl == task_access.DECIDE}
        if scope.task_ids:
            for q in quests.all_of(who):
                if getattr(q, "task_id", "") in scope.task_ids:
                    scope.quest_ids.add(str(q.id))
                    scope.goal_ids.add(q.task_id)
            down, _up = access.links()
            scope.goal_ids |= {g for q, gs in down.items() if q in scope.task_ids for g in gs
                               if g in scope.task_ids}
            scope.goal_ids |= {g.task_id for g in scope.grants
                               if g.kind == "goal" and g.task_id in scope.task_ids}
        return scope

    def decides(self) -> bool:
        return bool(self.task_ids or self.quest_ids)

    def covers_task(self, task_id) -> bool:
        return str(task_id or "") in self.task_ids

    def covers_quest(self, record_id) -> bool:
        return str(record_id or "") in self.quest_ids

    def grant_for(self, task_id="", quest_id=""):
        """The record that reaches this, for the record of acts."""
        if quest_id and not task_id:
            task_id = next((g.task_id for g in self.grants
                            if g.kind == "quest" and g.target == str(quest_id)), "")
        if task_id and self.access is not None:
            _lvl, _came, where = self.access.why_from(str(task_id))
            hit = next((g for g in self.grants if g.task_id == where), None)
            if hit is not None:
                return hit
        return next((d for d in self.grants if d.power == "decide"), None)

    def words(self) -> str:
        out = []
        down = self.access.links()[0] if self.access is not None else {}
        for d in self.grants:
            if d.power != "decide":
                continue
            said = name_of_row(d)
            goals = [g for g in down.get(d.task_id, ()) if g in self.task_ids]
            if goals and self.access is not None:
                said += " with its goals " + ", ".join(
                    self.access.number_of(g) or g for g in goals)
            out.append(said)
        return "; ".join(out)


def decision_task(row) -> str:
    """The task a decision belongs to, by id, for the sources a delegate can answer. A goal
    step's is its step, found by its folder, or, when the step has moved since it was asked,
    the goal its batch names ("goal:<id>")."""
    from .models import Task

    if row.source == "task":
        return str(row.source_id or "")
    if row.source == "goal" and row.source_id:
        found = Task.objects.filter(folder=row.source_id).values_list("id", flat=True).first()
        if not found:
            # Moved since: its own folder name is the same wherever it went.
            tail = "/".join(str(row.source_id).strip("/").split("/")[-2:])
            found = Task.objects.filter(folder__endswith="/" + tail).values_list(
                "id", flat=True).first() if tail.count("/") == 1 else None
        if not found:
            batch = str(getattr(row, "batch", "") or "")
            found = batch.split(":", 1)[1] if batch.startswith("goal:") else ""
        return str(found or "")
    return ""


def decision_quest(row) -> str:
    batch = str(getattr(row, "batch", "") or "")
    return batch.split(":", 1)[1] if row.source == "approval" and batch.startswith("quest:") \
        else ""


def covers_decision(scope: Scope, row) -> bool:
    """Whether a decision is inside what this contact may decide: a goal step's or a task's
    in a task they decide for, or a quest's approval for a quest they decide for."""
    if row.source not in DECISION_SOURCES:
        return False
    if row.source == "approval":
        return scope.covers_quest(decision_quest(row))
    return scope.covers_task(decision_task(row))


def never_for_decision(row) -> str:
    """Why a decision in scope is still the owner's, or "": what its answer would do."""
    from . import decisions

    if row.risk in decisions.GATED:
        return {"money": NEVER["money"], "sending": NEVER["send"],
                "publishing": NEVER["publish"],
                "irreversible": "anything that cannot be undone"}.get(row.risk, row.risk) + \
            " stays ‹owner›'s"
    return ""


def deciders(user_id, org_id) -> list[Scope]:
    """Every contact who decides something now, with their scope: for the desk and the pages."""
    from . import trusted

    from .models import PageGuest

    emails = set(PageGuest.objects.filter(user_id=str(user_id), org_id=str(org_id),
                                          role="decide", rel__startswith="_task/")
                 .values_list("email", flat=True))
    if not emails:
        return []
    store = trusted.TrustStore()
    contacts = {}
    for e in sorted(emails):
        c = store.trusted_for(str(user_id), str(org_id), e)
        if c is not None:
            contacts[c.id] = c
    tree = _tree()
    out = []
    for cid in sorted(contacts):
        scope = Scope.of(user_id, org_id, contacts[cid], tree=tree)
        if scope.decides():
            out.append(scope)
    return out


def decider_of(row, scopes: list[Scope] | None = None):
    """The contact who decides this decision, when one does and it is not gated, else None."""
    if row.source not in DECISION_SOURCES or never_for_decision(row):
        return None
    for scope in scopes if scopes is not None else deciders(row.user_id, row.org_id):
        if covers_decision(scope, row):
            return scope.contact
    return None


def briefed_decisions(user_id, org_id, ids) -> set[int]:
    """Which of these decisions were emailed to the person who decides them."""
    m = _models()
    ids = [int(i) for i in ids or [] if i is not None]
    return set(m.DelegateAct.objects.filter(user_id=str(user_id), org_id=str(org_id),
                                            act="briefed", decision_id__in=ids)
               .values_list("decision_id", flat=True)) if ids else set()


def notes_on_decisions(user_id, org_id, ids) -> dict[int, list[dict]]:
    """What delegates said about decisions they could not make: their recommendation and
    words, drawn on the card."""
    m = _models()
    out: dict[int, list[dict]] = {}
    ids = [int(i) for i in ids or [] if i is not None]
    if not ids:
        return out
    for a in m.DelegateAct.objects.filter(user_id=str(user_id), org_id=str(org_id),
                                          decision_id__in=ids,
                                          outcome__in=("for_owner", "for_petar")) \
            .order_by("at"):
        out.setdefault(int(a.decision_id), []).append(
            {"name": a.contact_name, "words": a.words, "said": a.said, "at": a.at,
             "why": a.why})
    return out


# --- what they do -------------------------------------------------------------------------


@dataclass
class Turn:
    """Who is acting, checked: the case their message is, and the contact it is from."""

    who: object
    contact: object
    case: object
    written: str
    channel: str


def check_sender(who, case_id: int, trusted_id: int) -> Turn:
    """The case's sender is this contact, exactly, and confirmed; or Refused with why, which
    becomes a question back to them, never an action."""
    from . import mail_cases, trusted
    from .models import MailCase

    case = MailCase.objects.filter(user_id=str(who.user_id), org_id=str(who.org_id),
                                   id=int(case_id or 0)).first()
    if case is None:
        raise Refused("This is not a message from a trusted contact.")
    contact = trusted.TrustStore().get(str(who.user_id), str(who.org_id), case.contact_id) \
        if case.contact_id else None
    if contact is None or contact.id != int(trusted_id or 0):
        raise Refused("The message is not from the contact who was given authority.")
    if not contact.trusted:
        raise Refused(f"{contact.name} is switched off, so they decide nothing now.")
    if not contact.recognises(case.sender):
        raise Refused(f"It did not come from one of {contact.name}'s own addresses.")
    if not case.identity_ok:
        raise Refused("Gmail could not confirm it really came from that address "
                      f"({case.identity_said or 'no DKIM or SPF alignment'}), so nothing was "
                      "done: ask them to send it again from their own address.")
    written = mail_cases.unquoted((case.email or {}).get("body") or "")
    return Turn(who=who, contact=contact, case=case, written=written,
                channel=mail_cases.channel_of(case))


def _key(turn: Turn, act: str, target: str, words: str, asked: dict) -> str:
    raw = json.dumps([turn.case.id, act, target, _norm(words), asked], sort_keys=True,
                     default=str)
    return hashlib.sha256(raw.encode()).hexdigest()[:40]


def _before(turn: Turn, key: str):
    m = _models()
    return m.DelegateAct.objects.filter(user_id=str(turn.who.user_id),
                                        org_id=str(turn.who.org_id), key=key,
                                        outcome__in=("done", "for_owner", "for_petar")).first()


def done_in_case(user_id, org_id, case_id, asks) -> dict:
    """The asks of a case that its sender, deciding for the work, already had done in the same
    message through their own authority (`act`): {ask ident: what was done}. The mail gate
    reads it (`mail_ledger.judge`, `done_by`), so the same request by email and by this path is
    one thing, done once, and never waits for the owner after it was done (Petar, 21 October
    2026: one ask, one decision)."""
    m = _models()
    if not case_id or not asks:
        return {}
    done = list(m.DelegateAct.objects.filter(
        user_id=str(user_id), org_id=str(org_id), case_id=int(case_id), outcome="done")
        .exclude(act__in=(*BOOKKEEPING, "grant", "extend", "revoke", "undo"))
        .exclude(words="").order_by("at"))
    out = {}
    for a in asks:
        hit = next((d for d in done if words_are_theirs(d.words, getattr(a, "quote", ""))), None)
        if hit is not None:
            out[a.ident] = hit.said
    return out


def hold_for_owner(turn: Turn, act: str, *, why: str, words: str, said: str, asked: dict,
                   target_kind: str = "", target: str = "", number: int = 0, title: str = "",
                   decision=None, grant=None, key: str = "") -> str:
    """What they decided that is the owner's: kept as their recommendation, attributed, for
    their decision. On a decision that exists, drawn on its card; otherwise a decision of its own
    (`decision_sources.DelegateSource`)."""
    log_act(turn.who.user_id, turn.who.org_id, turn.contact, act, grant=grant,
            target_kind=target_kind, target=target, number=number, title=title, words=words,
            said=said, asked=asked, outcome="for_owner", why=why, decision=decision,
            case_id=turn.case.id, channel=turn.channel, key=key)
    from . import decision_desk

    if decision_desk.LIVE is not None:
        decision_desk.LIVE.poke()
    return (f"Held for ‹owner›: {why}. Their recommendation and their words are on it, "
            f"attributed to {turn.contact.name}. Tell them it is ‹owner›'s to decide and that ‹he› "
            "has their recommendation.")


def _done(turn: Turn, act: str, *, said: str, words: str, asked: dict, target_kind: str,
          target: str, number: int, title: str, grant=None, undo=None, decision=None,
          key: str = "") -> str:
    log_act(turn.who.user_id, turn.who.org_id, turn.contact, act, grant=grant,
            target_kind=target_kind, target=target, number=number, title=title, words=words,
            said=said, asked=asked, outcome="done", decision=decision, case_id=turn.case.id,
            channel=turn.channel, undo=undo or {}, key=key)
    return f"Done, as {turn.contact.name}'s decision, written down with their words: {said}"


def _refused(turn: Turn, act: str, why: str, words: str, asked: dict) -> str:
    log_act(turn.who.user_id, turn.who.org_id, turn.contact, act, words=words, asked=asked,
            outcome="refused", why=why, case_id=turn.case.id, channel=turn.channel)
    return f"Not done: {why}"


def _commits(text: str, contact, who=None) -> str:
    """What a step's own work would commit the owner to, in words, or "": a step Rouh would do
    that signs, files or engages somebody. Never money: whether something moves money is what
    the action does - a payment, a charge, Stripe (`NEVER_ACTS`) - and never words in a text
    (Petar, 21 October 2026, after a request for a timeline that mentioned his steps of paying
    and filing was held as moving money)."""
    from . import commitments

    held = [c for c in commitments.commitments(text or "", contact, who) if c["kind"] != "money"]
    if held:
        return "it would commit ‹owner›: " + commitments.commitments_said(held)
    return ""


def _goal_in(scope: Scope, said, *, reading: bool = False):
    """The goal they named, when they decide for it, or with `reading` may read it."""
    from . import goals

    goal, why = goals.find(said)
    if goal is None:
        raise Refused(why)
    if not (scope.covers_task(goal.id) or reading and goal.id in scope.read_ids):
        raise Refused(f"Goal {goal.number} is not one they "
                      + ("may read." if reading else "decide for."))
    return goal


def _quest_in(scope: Scope, who, said, *, reading: bool = False):
    """The quest they named, when they decide for it, or with `reading` may read it."""
    from . import quests

    row = quests.find(who, said)
    if row is None:
        raise Refused(f"There is no quest {said}.")
    if not (scope.covers_quest(row.id) or reading and row.task_id in scope.read_ids):
        raise Refused(f"Quest {row.task_number} is not one they "
                      + ("may read." if reading else "decide for."))
    return row


def _named_work(scope: Scope, who, args) -> dict:
    """The goal or quest a request names, when it is one of theirs, to file what is held
    under it; {} otherwise."""
    try:
        if args.get("quest") not in (None, ""):
            row = _quest_in(scope, who, args.get("quest"))
            return {"target_kind": "quest", "target": str(row.id),
                    "number": row.task_number or 0, "title": row.title}
        if args.get("goal") not in (None, ""):
            goal = _goal_in(scope, args.get("goal"))
            return {"target_kind": "goal", "target": goal.id, "number": goal.number or 0,
                    "title": goal.title}
    except Refused:
        pass
    return {}


def scope_text(turn: Turn) -> str:
    """Their grants and the open decisions inside them, for the case's turn."""
    from . import decisions as dmod
    from .models import Decision

    scope = Scope.of(turn.who.user_id, turn.who.org_id, turn.contact)
    if not scope.decides():
        return f"{turn.contact.name} decides nothing now (no grant, or it was revoked)."
    lines = [f"{turn.contact.name} may decide for: {scope.words()}.",
             "Never theirs, even there: " + "; ".join(NEVER.values()) + "."]
    open_rows = Decision.objects.filter(user_id=str(turn.who.user_id),
                                        org_id=str(turn.who.org_id),
                                        status__in=dmod.ANSWERABLE,
                                        source__in=DECISION_SOURCES)
    mine = [r for r in open_rows if covers_decision(scope, r)]
    if mine:
        lines.append("Open decisions in it:")
        for r in mine:
            gate = never_for_decision(r)
            opts = "; ".join(f'{o["id"]} "{o["label"]}"' for o in r.options or [])
            lines.append(f"- {dmod.name_of(r)} [{r.context}] {r.question}"
                         + (f" Options: {opts}." if opts else "")
                         + (" Their own words are accepted." if r.allow_other else "")
                         + (f" ‹owner›'S: {gate}; only their recommendation is kept." if gate
                            else ""))
    else:
        lines.append("No decision in it is open now.")
    return "\n".join(lines)


async def act(who, case_id: int, trusted_id: int, args: dict) -> str:
    """The case tool `delegate_act`: one thing a delegate decided in their message, checked
    and done, or held for the owner, or refused, and always written down."""
    try:
        turn = await asyncio.to_thread(check_sender, who, case_id, trusted_id)
    except Refused as exc:
        return f"Not done: {exc}"
    action = str(args.get("action") or "").strip().lower()
    if action == "list":
        return await asyncio.to_thread(scope_text, turn)
    words = str(args.get("words") or "").strip()[:WORDS_MOST]
    asked = {k: v for k, v in args.items() if k not in ("words",)}
    if not words_are_theirs(words, turn.written):
        return await asyncio.to_thread(
            _refused, turn, action or "unknown",
            "words must be the sender's own, copied exactly from their message (not from what "
            "it quotes). Give the sentence they wrote that decides it.", words, asked)
    scope = await asyncio.to_thread(Scope.of, who.user_id, who.org_id, turn.contact)
    if not scope.decides():
        return await asyncio.to_thread(
            _refused, turn, action, f"{turn.contact.name} decides nothing now: no grant, or it "
            "was revoked.", words, asked)
    never = NEVER_ACTS.get(action) or NEVER_ACTS.get(str(args.get("do") or "").lower())
    if never:
        return await asyncio.to_thread(
            hold_for_owner, turn, action, why=NEVER[never] + " stays ‹owner›'s", words=words,
            said=(f"{turn.contact.name} asks for this, which stays ‹owner›'s ("
                  + " ".join(x for x in (action, str(args.get("do") or "")) if x) + "): "
                  + str(args.get("what") or args.get("text") or words))[:600], asked=asked,
            **await asyncio.to_thread(_named_work, scope, who, args))
    try:
        if action == "decide":
            return await _decide(turn, scope, args, words, asked)
        if action == "step":
            return await _step(turn, scope, args, words, asked)
        if action == "plan":
            return await _plan(turn, scope, args, words, asked)
        if action == "quest":
            return await _quest(turn, scope, args, words, asked)
        if action == "research":
            return await _research(turn, scope, args, words, asked)
    except Refused as exc:
        return await asyncio.to_thread(_refused, turn, action, str(exc), words, asked)
    except ValueError as exc:
        return await asyncio.to_thread(_refused, turn, action, str(exc), words, asked)
    return ("action is list, decide, step, plan, quest or research. Nothing was done.")


async def _decide(turn: Turn, scope: Scope, args, words, asked) -> str:
    from . import decision_desk, decisions

    # What the model passes is the decision's number as said, never a row's own id.
    ident = str(args.get("decision") or "")
    row = await asyncio.to_thread(decisions._row, turn.who, ident)
    if row is None:
        raise Refused("There is no such decision. Give its number, such as Decision 42.")
    if not covers_decision(scope, row):
        raise Refused(f"{decisions.name_of(row)} is not inside what {turn.contact.name} decides "
                      "for: " + NEVER["outside"] + " stays ‹owner›'s.")
    key = _key(turn, "decide", str(row.id), words, {"c": args.get("choice"),
                                                     "t": args.get("text")})
    if await asyncio.to_thread(_before, turn, key):
        return "Already done for this same message; nothing more was done."
    target_task = decision_task(row)
    grant_row = scope.grant_for(task_id=target_task, quest_id=decision_quest(row))
    gate = never_for_decision(row)
    d = decisions.as_dict(row)
    if gate:
        return await asyncio.to_thread(
            hold_for_owner, turn, "decide", why=gate, words=words,
            said=f"{turn.contact.name} recommends: "
                 + (", ".join(o["label"] for o in row.options or []
                              if o["id"] in _ids(args.get("choice"))) or
                    str(args.get("text") or words))[:600],
            asked=asked, target_kind="decision", target=str(row.id), title=row.question[:200],
            decision=d, grant=grant_row, key=key)
    choice = _ids(args.get("choice"))
    text = str(args.get("text") or "").strip()
    desk = decision_desk.LIVE
    kw = dict(choice=choice, text=text, channel=turn.channel, by=f"delegate:{turn.contact.id}",
              by_name=turn.contact.name, their_words=words)
    got = (await desk.answer(turn.who, row.id, **kw) if desk is not None else
           await asyncio.to_thread(lambda: decisions.answer(turn.who, row.id, **kw)))
    said = (got.get("decision") or {}).get("answer", {}).get("said") or text
    return await asyncio.to_thread(
        _done, turn, "decide", said=f"{decisions.name_of(row)} answered: {said}", words=words,
        asked=asked, target_kind="decision", target=str(row.id), number=0,
        title=row.question[:200], grant=grant_row, decision=d, key=key,
        undo={"decision": row.id})


def _ids(choice) -> list[str]:
    if isinstance(choice, str):
        choice = [choice]
    return [str(c).strip() for c in choice or [] if str(c).strip()]


async def _step(turn: Turn, scope: Scope, args, words, asked) -> str:
    from . import goals
    from .decision_sources import hooks

    goal = await asyncio.to_thread(_goal_in, scope, args.get("goal"))
    step, why = await asyncio.to_thread(goals.find_step, goal, args.get("step"))
    if step is None:
        raise Refused(why)
    do = str(args.get("do") or "").strip().lower()
    key = _key(turn, "step", step.id, words, {"do": do, "c": args.get("choice")})
    if await asyncio.to_thread(_before, turn, key):
        return "Already done for this same message; nothing more was done."
    keeper = hooks.keeper
    if keeper is None:
        raise Refused("Goals are not running on this machine just now.")
    was = await asyncio.to_thread(goals.step_state, step)
    grant_row = scope.grant_for(task_id=step.id)
    name = turn.contact.name
    choice = str(args.get("choice") or "").strip()
    note = str(args.get("note") or "").strip() or None
    if do in ("complete", "approve", "answer", "done"):
        if choice or note:
            await asyncio.to_thread(goals.change_step, step, choice=choice or None, note=note)
        started = await keeper.step_status(turn.who, goal, step.id, "done", by_person=True)
        said = (f"step “{step.title}” of goal {goal.number} "
                + ("answered “" + choice + "” and " if choice else "")
                + ("approved and marked complete" if do == "approve" else "marked complete")
                + (f"; {len(started)} step(s) waiting on it started" if started else ""))
    elif do in ("reject", "again"):
        await asyncio.to_thread(goals.change_step, step, note=words)
        await keeper.step_status(turn.who, goal, step.id, "not-started")
        await keeper.do_step(turn.who, goal, step.id, unattended=True,
                             why=f"{name}, who decides for this goal, rejected what was done "
                                 f"and asked for it again. Their words: {words}")
        said = f"step “{step.title}” of goal {goal.number} rejected; Rouh is doing it again"
    elif do == "reopen":
        await keeper.step_status(turn.who, goal, step.id, "not-started")
        said = f"step “{step.title}” of goal {goal.number} reopened"
    elif do == "note":
        await asyncio.to_thread(goals.change_step, step, note=note or words)
        said = f"a note kept on step “{step.title}” of goal {goal.number}"
    else:
        raise Refused("do is complete, approve, answer, reject, reopen or note.")
    await keeper.tell(turn.who)
    return await asyncio.to_thread(
        _done, turn, "step", said=said, words=words, asked=asked, target_kind="goal",
        target=goal.id, number=goal.number or 0, title=goal.title, grant=grant_row,
        key=key, undo={"step": step.id, "goal": goal.id, "was": list(was)})


async def _plan(turn: Turn, scope: Scope, args, words, asked) -> str:
    from . import archiving, goals
    from .decision_sources import hooks

    goal = await asyncio.to_thread(_goal_in, scope, args.get("goal"))
    change = str(args.get("change") or "").strip().lower()
    key = _key(turn, "plan", goal.id, words, asked)
    if await asyncio.to_thread(_before, turn, key):
        return "Already done for this same message; nothing more was done."
    keeper = hooks.keeper
    grant_row = scope.grant_for(task_id=goal.id)
    undo: dict = {"goal": goal.id}
    name = turn.contact.name
    if change == "add":
        specs = args.get("steps") or ([args.get("new")] if isinstance(args.get("new"), dict)
                                      else [])
        specs = [s for s in specs if isinstance(s, dict)]
        if not specs:
            raise Refused("Give the new step as steps: [{title, who, how}].")
        for s in specs:
            text = " ".join(str(s.get(k) or "") for k in ("title", "how", "solution"))
            held = _commits(text, turn.contact, turn.who) if str(s.get("who") or "rouh") in (
                "rouh", "together", "quest") else ""
            if held:
                return await asyncio.to_thread(
                    hold_for_owner, turn, "plan", why=held, words=words,
                    said=f"{name} wants a step added to goal {goal.number}: "
                         f"“{s.get('title')}”", asked=asked, target_kind="goal",
                    target=goal.id, number=goal.number or 0, title=goal.title,
                    grant=grant_row, key=key)
        made = await asyncio.to_thread(goals.plan, goal, steps=specs, add=True)
        undo["added"] = [r.id for r in made]
        if keeper is not None:
            await keeper.start_streams(turn.who, goal, why=f"{name}, who decides for this goal, "
                                       "added to the plan.")
        said = f"{len(specs)} step(s) added to goal {goal.number}: " + ", ".join(
            f"“{s.get('title')}”" for s in specs)
    elif change == "deadline":
        block = (await asyncio.to_thread(goals._goal_block, goal))[2]
        undo["deadline"] = block.get("deadline") or ""
        kept = await asyncio.to_thread(goals.set_deadline, goal, args.get("deadline") or "")
        said = (f"goal {goal.number}'s deadline set to {kept}" if kept
                else f"goal {goal.number}'s deadline taken off")
    else:
        step, why = await asyncio.to_thread(goals.find_step, goal, args.get("step"))
        if step is None:
            raise Refused(why)
        undo["step"] = step.id
        undo["was"] = list(await asyncio.to_thread(goals.step_state, step))
        if change == "remove":
            got = await asyncio.to_thread(archiving.archive, step.id, True)
            if not got.get("ok"):
                raise Refused(got.get("why") or "It could not be taken off the plan.")
            undo["archived"] = step.id
            said = f"step “{step.title}” taken off goal {goal.number}'s plan (archived)"
        elif change in ("reword", "who", "change"):
            fields = {k: args.get(k) for k in STEP_FIELDS if args.get(k) is not None}
            if not fields:
                raise Refused("Say what changes: title, who, how, ask, options, outcome.")
            meta_now = goals._meta(goals._folder(step))
            block = meta_now.get("goal_step") if isinstance(meta_now.get("goal_step"), dict) \
                else {}
            who_after = str(fields.get("who") or block.get("who") or "rouh")
            text = " ".join(str(fields.get(k) or "") for k in ("title", "how", "solution"))
            held = _commits(text, turn.contact, turn.who) if who_after in ("rouh", "together") else ""
            if held:
                return await asyncio.to_thread(
                    hold_for_owner, turn, "plan", why=held, words=words,
                    said=f"{name} wants step “{step.title}” of goal {goal.number} changed",
                    asked=asked, target_kind="goal", target=goal.id, number=goal.number or 0,
                    title=goal.title, grant=grant_row, key=key)
            await asyncio.to_thread(lambda: goals.change_step(step, by_person=True, **fields))
            said = f"step “{step.title}” of goal {goal.number} changed: " + ", ".join(fields)
        elif change == "move":
            block = (await asyncio.to_thread(goals._goal_block, goal))[2]
            undo["streams"] = block.get(goals.STREAMS)
            after = None
            if str(args.get("after") or "").strip():
                after, why = await asyncio.to_thread(goals.find_step, goal, args.get("after"))
                if after is None:
                    raise Refused(why)
            into = str(args.get("stream") or "").strip()
            await asyncio.to_thread(goals.put_in_stream, goal, step, into, after=after,
                                    first=bool(args.get("first")))
            said = (f"step “{step.title}” of goal {goal.number} moved"
                    + (f" into “{into}”" if into else "")
                    + (f" after “{after.title}”" if after is not None else ""))
        else:
            raise Refused("change is add, remove, reword, who, move or deadline.")
    if keeper is not None:
        await keeper.tell(turn.who)
    return await asyncio.to_thread(
        _done, turn, "plan", said=said, words=words, asked=asked, target_kind="goal",
        target=goal.id, number=goal.number or 0, title=goal.title, grant=grant_row,
        key=key, undo=undo)


async def _quest(turn: Turn, scope: Scope, args, words, asked) -> str:
    from . import quests
    from .decision_sources import hooks

    row = await asyncio.to_thread(_quest_in, scope, turn.who, args.get("quest"))
    do = str(args.get("do") or "").strip().lower()
    key = _key(turn, "quest", str(row.id), words, asked)
    if await asyncio.to_thread(_before, turn, key):
        return "Already done for this same message; nothing more was done."
    grant_row = scope.grant_for(quest_id=row.id)
    pulse = hooks.heartbeat
    undo: dict = {"quest": row.id}
    if do in QUEST_PARTS:
        text = str(args.get("text") or "").strip()
        if not text:
            raise Refused(f"Give the quest's {do} as text, whole.")
        undo["part"], undo["text"] = do, await asyncio.to_thread(quests.part_of, row, do)
        said = await asyncio.to_thread(quests.write_brief, row, do, text, "replace")
        if not said.startswith("The "):
            raise Refused(said)
    elif do in ("pause", "resume"):
        if pulse is None:
            raise Refused("The heartbeat is not running here.")
        undo["state"] = row.state
        said = await pulse.work_state(turn.who, row.id, paused=do == "pause")
    elif do in ("beat", "now"):
        if pulse is None:
            raise Refused("The heartbeat is not running here.")
        try:
            said = await pulse.work_now(turn.who, row.id, where="quest")
        except Exception as exc:  # noqa: BLE001 - questcheck.Refused says why
            raise Refused(str(exc)) from None
        undo = {}
    else:
        raise Refused("do is goal, rules, plan, notebook, pause, resume or beat.")
    return await asyncio.to_thread(
        _done, turn, "quest", said=said, words=words, asked=asked, target_kind="quest",
        target=str(row.id), number=row.task_number or 0, title=row.title, grant=grant_row,
        key=key, undo=undo)


async def _research(turn: Turn, scope: Scope, args, words, asked) -> str:
    from . import goals
    from .decision_sources import hooks

    # Research only reads and prepares: it is never held for what its words mention (Petar's
    # steps of signing, paying or filing are things it lays out, not things it does), and it
    # only needs reading of the work (`rouh/task_access.py`).
    ask = str(args.get("ask") or words).strip()
    name = turn.contact.name
    if args.get("quest") not in (None, ""):
        row = await asyncio.to_thread(_quest_in, scope, turn.who, args.get("quest"), reading=True)
        key = _key(turn, "research", str(row.id), words, asked)
        if await asyncio.to_thread(_before, turn, key):
            return "Already done for this same message; nothing more was done."
        pulse = hooks.heartbeat
        if pulse is None:
            raise Refused("The heartbeat is not running here.")
        await pulse.event("delegate", f"{name}, who decides for this quest, asks for more "
                                      f"research: {ask}", work_id=row.id)
        with_beat = ""
        try:
            with_beat = " " + await pulse.work_now(turn.who, row.id, where="quest")
        except Exception:  # noqa: BLE001 - the event waits for the next beat anyway
            pass
        return await asyncio.to_thread(
            _done, turn, "research", said=f"research asked on quest {row.task_number}: "
                                          f"{ask[:300]}.{with_beat}", words=words, asked=asked,
            target_kind="quest", target=str(row.id), number=row.task_number or 0,
            title=row.title, grant=scope.grant_for(quest_id=row.id), key=key)
    goal = await asyncio.to_thread(_goal_in, scope, args.get("goal"), reading=True)
    key = _key(turn, "research", goal.id, words, asked)
    if await asyncio.to_thread(_before, turn, key):
        return "Already done for this same message; nothing more was done."
    grant_row = scope.grant_for(task_id=goal.id)
    title = str(args.get("title") or "").strip() or ("Research: " + " ".join(ask.split())[:90])
    made = await asyncio.to_thread(goals.plan, goal, steps=[{
        "title": title, "who": "rouh", "how": f"{name} asked for this research: {ask}",
        "stream": str(args.get("stream") or "") or None}], add=True)
    keeper = hooks.keeper
    if made and keeper is not None:
        await keeper.do_step(turn.who, goal, made[0].id, unattended=True,
                             why=f"{name}, who decides for this goal, asked for this research.")
        await keeper.tell(turn.who)
    return await asyncio.to_thread(
        _done, turn, "research", said=f"a research step “{title}” added to goal {goal.number} "
                                      "and started", words=words, asked=asked,
        target_kind="goal", target=goal.id, number=goal.number or 0, title=goal.title,
        grant=grant_row, key=key, undo={"goal": goal.id, "added": [r.id for r in made]})


# --- undo ---------------------------------------------------------------------------------


async def undo(who, act_id) -> str:
    """Put one action of a delegate's back, at the owner's press."""
    from . import archiving, decisions, goals, quests
    from .decision_sources import hooks

    m = _models()
    a = await asyncio.to_thread(lambda: m.DelegateAct.objects.filter(
        user_id=str(who.user_id), org_id=str(who.org_id), id=int(act_id)).first())
    if a is None:
        raise Refused("That action is not there.")
    if a.undone_at:
        raise Refused("It was already undone.")
    if a.outcome != "done":
        raise Refused("Only something that was done can be undone.")
    u = a.undo or {}
    said = ""
    if a.act == "decide" and u.get("decision"):
        try:
            await asyncio.to_thread(decisions.undo, who, u["decision"])
            said = "Their answer was taken back before it went; the decision waits on you."
        except decisions.Refused:
            row = await asyncio.to_thread(decisions._row, who, u["decision"])
            task_id = decision_task(row) if row is not None else ""
            if row is not None and row.source == "goal" and task_id:
                step = await asyncio.to_thread(_task_row, task_id)
                goal = await asyncio.to_thread(goals.goal_above, step) if step else None
                if goal is not None and hooks.keeper is not None:
                    await asyncio.to_thread(goals.change_step, step, choice="", note="")
                    await hooks.keeper.step_status(who, goal, step.id, "not-started")
                    said = ("The step was opened again with their choice taken off; it asks "
                            "you now.")
            if not said:
                raise Refused("Their answer has already been carried out and its source "
                              "cannot take it back; answer it again yourself on the work.")
    elif a.act in ("step", "plan", "research") and (u.get("step") or u.get("added")
                                                     or "deadline" in u or u.get("streams")):
        goal = await asyncio.to_thread(_task_row, u.get("goal"))
        if u.get("added"):
            for ident in u["added"]:
                await asyncio.to_thread(archiving.archive, ident, True)
        if u.get("archived"):
            await asyncio.to_thread(archiving.archive, u["archived"], False)
        if u.get("step") and u.get("was"):
            step = await asyncio.to_thread(_task_row, u["step"])
            if step is not None:
                await asyncio.to_thread(goals.put_back, step, tuple(u["was"]))
        if "deadline" in u and goal is not None:
            await asyncio.to_thread(goals.set_deadline, goal, u["deadline"] or "")
        if u.get("streams") is not None and goal is not None:
            await asyncio.to_thread(_put_streams, goal, u["streams"])
        if hooks.keeper is not None:
            await hooks.keeper.tell(who)
        said = "Put back as it was before."
    elif a.act == "quest" and u.get("quest"):
        row = await asyncio.to_thread(quests.get, who, u["quest"])
        if row is None:
            raise Refused("The quest is not there any more.")
        if u.get("part"):
            await asyncio.to_thread(quests.write_brief, row, u["part"], u.get("text") or " ",
                                    "replace")
        if u.get("state") and hooks.heartbeat is not None:
            await hooks.heartbeat.work_state(who, row.id, paused=u["state"] == "paused")
        said = "Put back as it was before."
    else:
        raise Refused("There is nothing to put back for this one: what it started has run.")
    now = _now()
    await asyncio.to_thread(lambda: m.DelegateAct.objects.filter(id=a.id).update(
        outcome="undone", undone_at=now, undone_said=said))
    await asyncio.to_thread(log_act, who.user_id, who.org_id, None, "undo",
                            target_kind=a.target_kind, target=a.target, number=a.number,
                            title=a.title, said=f"‹Owner› undid what {a.contact_name} did: "
                                                f"{a.said} {said}", channel="settings")
    return said


def _task_row(task_id):
    st = _store()
    return st.get_task(task_id) if st is not None and task_id else None


def _put_streams(goal, streams) -> None:
    from . import goals

    folder, meta, block = goals._goal_block(goal)
    block[goals.STREAMS] = streams
    meta["goal"] = block
    goals._write_meta(folder, meta)


# --- the record, read -----------------------------------------------------------------------


def _act_dict(a) -> dict:
    return {"id": a.id, "contact": a.contact_id, "name": a.contact_name, "act": a.act,
            "target_kind": a.target_kind, "target": a.target, "number": a.number,
            "title": a.title, "words": a.words, "said": a.said, "outcome": a.outcome,
            "why": a.why, "handle": a.handle, "decision_id": a.decision_id,
            "channel": a.channel, "at": a.at, "undone_at": a.undone_at,
            "undone_said": a.undone_said, "grant": a.grant,
            "can_undo": a.outcome == "done" and bool(a.undo) and not a.undone_at}


#: The record's own book-keeping, never one of their actions.
BOOKKEEPING = ("briefed",)


def acts(user_id, org_id, *, contact_id=None, target_kind: str = "", target: str = "",
         since: float = 0.0, most: int = 50, theirs: bool = True) -> list[dict]:
    m = _models()
    q = m.DelegateAct.objects.filter(user_id=str(user_id), org_id=str(org_id))
    if contact_id is not None:
        q = q.filter(contact_id=int(contact_id))
    if target_kind:
        q = q.filter(target_kind=target_kind, target=str(target))
    if since:
        q = q.filter(at__gte=since)
    q = q.exclude(act__in=BOOKKEEPING)
    if theirs:
        q = q.exclude(act__in=("grant", "extend", "revoke", "undo"))
    out = [_act_dict(a) for a in q.order_by("-at", "-id")[:most]]
    _with_work(user_id, org_id, out)
    return out


def _with_work(user_id, org_id, rows_: list) -> None:
    """Name the work each act was done in, the grant's goal, quest, task or step, as
    `work_kind`, `work_code` and `work_title`: a decision act's own title is the decision's
    question, and the contact's page lists them under the work they belong to."""
    grants = {}
    if any(r.get("grant") for r in rows_):
        grants = {d.id: d for d in rows(user_id, org_id)}
    codes: dict = {}
    for r in rows_:
        d = grants.get(r.get("grant"))
        if d is not None:
            kind, number, target, title = d.kind, d.number, d.target, d.title
        elif r["target_kind"] in KINDS:
            kind, number, target, title = (r["target_kind"], r["number"], r["target"],
                                           r["title"])
        else:
            r.update(work_kind="", work_code="", work_title="")
            continue
        key = (kind, number, target)
        if key not in codes:
            codes[key] = code_of_row({"kind": kind, "number": number, "target": target})
        r.update(work_kind=kind, work_code=codes[key], work_title=title)


def on_work(user_id, org_id, *, goal_id: str = "", quest_id: str = "") -> dict:
    """Who decides for a goal or quest, and what they did there, for its page."""
    scopes = deciders(user_id, org_id)
    names = [s.contact.name for s in scopes
             if (goal_id and s.covers_task(goal_id)) or (quest_id and s.covers_quest(quest_id))]
    done = []
    if goal_id:
        done += acts(user_id, org_id, target_kind="goal", target=goal_id, most=20)
    if quest_id:
        done += acts(user_id, org_id, target_kind="quest", target=str(quest_id), most=20)
    return {"deciders": names, "acts": sorted(done, key=lambda d: -d["at"])[:20]}


def digest(user_id, org_id, since: float) -> list[dict]:
    """What every delegate did, tried or had held for the owner since `since`: the brief's lines."""
    return list(reversed(acts(user_id, org_id, since=since, most=40)))


# --- the briefs they are sent -------------------------------------------------------------


def _briefed(user_id, org_id, contact_id) -> set[int]:
    m = _models()
    return set(m.DelegateAct.objects.filter(user_id=str(user_id), org_id=str(org_id),
                                            contact_id=int(contact_id), act="briefed")
               .values_list("decision_id", flat=True))


def brief_address(user_id, org_id, contact) -> str:
    """Where a delegate's briefs go: the address they last wrote to Rouh from, else the first
    one the owner ticked for them."""
    from .models import MailCase

    last = (MailCase.objects.filter(user_id=str(user_id), org_id=str(org_id),
                                    contact_id=contact.id, sender__contains="@")
            .order_by("-id").values_list("sender", flat=True).first())
    return last if last and last in contact.addresses else contact.addresses[0]


def brief_text(contact, rows_: list, public_url: str = "") -> tuple[str, str]:
    """The email a delegate is sent for the decisions waiting on them: (subject, body).

    Warm and professional: it is work, written to somebody the owner trusts with it. Its
    marks for the owner are filled in where it is sent (`brief_delegates`)."""
    from . import decisions as dmod

    first = (contact.name or "").split()[0] if contact.name else ""
    many = len(rows_) > 1
    subject = (f"{len(rows_)} decisions for you" if many else
               f"A decision for you: {rows_[0].title or rows_[0].question}"[:160])
    lines = [f"Hello {first}," if first else "Hello,", "",
             ("These are waiting for your decision" if many else
              "This is waiting for your decision")
             + ", as ‹owner› asked you to decide for this work.", ""]
    for r in rows_:
        lines.append(f"{dmod.name_of(r)} - {r.context}".strip(" -"))
        lines.append(r.question)
        if r.why:
            lines.append(f"Why it matters: {r.why}")
        for n, o in enumerate(r.options or [], 1):
            lines.append(f"  {n}. {o['label']}" + (f" - {o['detail']}" if o.get("detail") else ""))
        rec = next((o for o in r.options or [] if o.get("id") == r.recommended), None)
        if rec is not None:
            lines.append(f"Rouh would choose: {rec['label']}"
                         + (f", because {r.recommended_why}" if r.recommended_why else "") + ".")
        if r.then:
            lines.append(f"What happens next: {r.then}")
        lines.append("")
    lines += [f"To decide, reply to this email from your own address with the decision's number and your "
              f"choice in your own words, for example: \"{dmod.name_of(rows_[0])}: option 1\". "
              "You can also ask for more research, or change the plan, the same way.",
              "",
              "Anything that would spend money, send something on ‹owner›'s behalf, publish, or "
              "commit ‹him› or ‹company› to anybody stays ‹his› to decide; I will pass ‹him› your "
              "recommendation for those.",
              "", "Thank you,", "Rouh"]
    return subject, "\n".join(lines)


async def brief_delegates(who, send) -> int:
    """Email each delegate the decisions newly waiting on them, once each, and say how many
    went. `send(address, subject, body)` is Rouh's own mailbox; nothing goes when it is None."""
    from . import decisions as dmod
    from .models import Decision

    if send is None:
        return 0
    scopes = await asyncio.to_thread(deciders, who.user_id, who.org_id)
    if not scopes:
        return 0
    open_rows = await asyncio.to_thread(lambda: list(Decision.objects.filter(
        user_id=str(who.user_id), org_id=str(who.org_id), status__in=dmod.WAITING,
        source__in=DECISION_SOURCES)))
    went = 0
    for scope in scopes:
        c = scope.contact
        told = await asyncio.to_thread(_briefed, who.user_id, who.org_id, c.id)
        fresh = [r for r in open_rows if r.id not in told and covers_decision(scope, r)
                 and not never_for_decision(r)]
        if not fresh or not c.addresses:
            continue
        address = await asyncio.to_thread(brief_address, who.user_id, who.org_id, c)
        subject, body = brief_text(c, fresh)
        # The letter leaves Rouh here: the owner's marks are filled in for whose decisions
        # these are.
        subject, body = owners.say(subject, who), owners.say(body, who)
        try:
            await send(address, subject, body)
        except Exception as exc:  # noqa: BLE001 - tried again on the next pass
            log.warning("the decision brief to %s could not be sent: %s", c.name, exc)
            continue
        for r in fresh:
            await asyncio.to_thread(
                log_act, who.user_id, who.org_id, c, "briefed", target_kind="decision",
                target=str(r.id), title=r.question[:200], decision=r, channel="email",
                said=f"Rouh emailed {c.name} {dmod.name_of(r)} to decide, at {address}.")
            await asyncio.to_thread(dmod.told, r.id, f"emailed to {c.name}, who decides it")
        went += len(fresh)
    return went


def model_block(user_id, org_id) -> str:
    """Who decides what now, for Rouh's own prompt: empty when nobody does."""
    try:
        scopes = deciders(user_id, org_id)
        held = promises(user_id, org_id)
    except Exception:
        log.exception("who decides what could not be read for the prompt")
        return ""
    lines = [f"- {s.contact.name} decides for {s.words()}." for s in scopes]
    for d in held:
        c = _contact(user_id, org_id, d.contact_id)
        if c is not None:
            lines.append(f"- Promised to {c.name}, once made: {d.pending} When you make it, "
                         f"extend it with delegate {{\"action\": \"extend\", \"contact\": "
                         f"\"{c.name}\", \"goals\": [...], \"quests\": [...]}}.")
    return "\n".join(lines)


def work_line(user_id, org_id, *, task_id: str = "", quest_id: str = "") -> str:
    """One paragraph for a goal step's run or a quest's beat, when somebody decides for it."""
    try:
        scopes = deciders(user_id, org_id)
    except Exception:
        log.exception("who decides for a piece of work could not be read")
        return ""
    names = [s.contact.name for s in scopes
             if (task_id and s.covers_task(task_id)) or (quest_id and s.covers_quest(quest_id))]
    if not names:
        return ""
    who = " and ".join(names)
    return (f"{who} decides for this work, by ‹owner›'s grant: a decision or an approval you "
            f"leave for the person here goes to {who}, by email, and not to ‹owner›. Write it as "
            f"you would for ‹him›, warmly and professionally. Never leave {who} anything that "
            "spends money, sends anything on ‹owner›'s behalf, publishes, or commits ‹owner› or "
            "‹company› to anybody (signing, filing, registering, applying, paying): those stay "
            "‹owner›'s, and you only prepare them.")


# --- whom Rouh writes to about the work ----------------------------------------------------


def people_of_quest(user_id, org_id, quest_id) -> list[tuple[object, list[str]]]:
    """The trusted contacts, switched on, who decide for or edit this quest - its task, or a
    goal it names - each with their ticked addresses: the people Rouh works with on it.

    Petar, 23 October 2026, after a beat on a delegate's quest queued for his yes an email to her
    of the timeline she had asked for herself: "she should have been able to make decisions
    on the stuff she is working on". Sending, in what stays his (`NEVER`), is sending to
    somebody else or in his name. Rouh writing from its own inbox to the person the work was
    given to, about that work, is working with them, and needs nobody's yes
    (`heartbeat._mail_refusal`)."""
    from . import quests, task_access, trusted

    from .models import PageGuest

    work = quests.by_id(str(user_id), str(org_id), quest_id)
    task_id = str(getattr(work, "task_id", "") or "")
    if not task_id:
        return []
    emails = set(PageGuest.objects.filter(
        user_id=str(user_id), org_id=str(org_id), role__in=(task_access.EDIT, task_access.DECIDE),
        rel__startswith="_task/").values_list("email", flat=True))
    store, root = task_access._store(), task_access._root()
    if not emails or store is None or not root:
        return []
    owner, tree, mails = _Who(str(user_id), str(org_id)), _tree(), trusted.TrustStore()
    contacts: dict = {}
    for e in sorted(emails):
        c = mails.trusted_for(str(user_id), str(org_id), e)
        if c is not None and getattr(c, "trusted", False) and c.addresses:
            contacts[c.id] = c
    out = []
    for cid in sorted(contacts):
        c = contacts[cid]
        access = task_access.Access(store, root, c, owner, tree=tree)
        levels = access.levels()
        ids = [task_id, *access.links()[0].get(task_id, ())]
        if any(task_access.at_least(levels.get(i, ""), task_access.EDIT) for i in ids):
            out.append((c, [a.lower() for a in c.addresses]))
    return out


def quest_people_line(user_id, org_id, quest_id) -> str:
    """What a beat on a quest is told about writing to the people it works with on it, or ""."""
    try:
        people = people_of_quest(user_id, org_id, quest_id)
    except Exception:
        log.exception("the people of quest %s could not be read", quest_id)
        return ""
    if not people:
        return ""
    names = "; ".join(f"{c.name} ({', '.join(a)})" for c, a in people)
    return ("PEOPLE YOU WORK WITH ON IT, by ‹owner›'s grant: " + names + ". Write to them "
            "yourself, with send_mail from Rouh's own inbox (inbox \"rouh\"), about this work: "
            "deliver what they asked for, ask for their decisions, remind them as the plan "
            "allows, and answer their mail. That is working with them, not sending in ‹owner›'s "
            "name, and needs nobody's yes, so never queue it with heartbeat_ask. Keep to the "
            "quest's own rules on when and how often. Never write as ‹owner›, never promise or "
            "commit ‹owner› or ‹company› to anything, and mail to anybody else still needs "
            "‹his› yes.")


def _deciding_owners() -> set:
    """Every owner somebody decides for, as (user id, organisation id)."""
    from .models import PageGuest

    return set(PageGuest.objects.filter(role="decide", rel__startswith="_task/")
               .values_list("user_id", "org_id"))


def on_work_any(*, goal_id: str = "", quest_id: str = "") -> dict:
    """`on_work` for whoever's workspace this is: the goal's page has no person to ask."""
    m = _models()
    owners = set(m.DelegateAct.objects.filter(target=str(goal_id or quest_id))
                 .values_list("user_id", "org_id")) | _deciding_owners()
    out = {"deciders": [], "acts": []}
    for u, o in sorted(owners):
        got = on_work(u, o, goal_id=goal_id, quest_id=quest_id)
        out["deciders"] += got["deciders"]
        out["acts"] += got["acts"]
    out["acts"].sort(key=lambda d: -d["at"])
    return out


def case_tools(who, contact) -> tuple[str, ...]:
    """The tools a case's turn adds for a contact with a grant: acting on it, and reading
    what it covers."""
    try:
        scope = Scope.of(who.user_id, who.org_id, contact)
    except Exception:
        log.exception("the grants of %s could not be read", getattr(contact, "name", "?"))
        return ()
    out: tuple[str, ...] = ()
    if scope.decides():
        out += ("delegate_act",)
    if scope.read_ids and "read_granted_tasks" not in contact.tools():
        out += ("read_granted_tasks",)
    return out


def case_paragraph(who, contact, owner: str = "‹owner›") -> str:
    """What a case's reading is told about a contact's authority, or "" for none."""
    try:
        scope = Scope.of(who.user_id, who.org_id, contact)
    except Exception:
        log.exception("the grants of %s could not be read", getattr(contact, "name", "?"))
        return ""
    if not scope.decides():
        # What they may read or edit is said with every task's level (`mail_cases.tasks_said`).
        return ""
    name = contact.name
    return "\n".join([
        f"- may decide for (authority {owner} gave them): {scope.words()}. Inside it {name} "
        f"decides as {owner} would: answers its decisions, completes, approves or rejects its "
        "steps, changes its plan and deadline, edits, pauses and resumes its quest and asks "
        "for a beat, and asks for more research. When this message decides any of that, "
        "carry it out now, in this turn, with delegate_act (action list first, then one call "
        "per thing, each with their own words copied exactly), then report done with a reply "
        f"that confirms exactly what was done, warmly and professionally, as Rouh, {owner}'s "
        "assistant. A request for research is delegate_act research, not needs_work.",
        f"  Never theirs, even there, and held for {owner} with their recommendation by "
        "delegate_act itself: " + "; ".join(NEVER.values()) + ". Say in the reply that "
        f"those are {owner}'s and that ‹he› has their recommendation. If delegate_act says it "
        "could not be sure who sent it, do nothing and ask them to write from their own "
        "address.",
    ])


def work_line_any(*, task_id: str = "", quest_id: str = "") -> str:
    """`work_line` for whoever's workspace this is: every person with a grant out."""
    try:
        owners = _deciding_owners()
    except Exception:
        log.exception("who decides for a piece of work could not be read")
        return ""
    return " ".join(x for x in (work_line(u, o, task_id=task_id, quest_id=quest_id)
                                for u, o in sorted(owners)) if x)


__all__ = ["KINDS", "NEVER", "Refused", "Scope", "act", "acts", "brief_delegates",
           "covers_decision", "decider_of", "deciders", "digest", "extend", "grant",
           "hold_for_owner", "listing", "model_block", "never_for_decision", "on_work",
           "people_of_quest", "quest_people_line", "revoke", "undo", "words_are_theirs",
           "work_line"]
