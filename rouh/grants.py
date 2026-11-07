"""What the owner can give a trusted contact, as rows per organisation, and the hard limits no grant covers.

Petar, 11 October 2026, after a trusted contact's email forwarding their travel
plans (decision x452) was held whole: the reading put their asks for
Clockwork items for him, notes in his memory and a task they both add to under
"outside_grant", a catch-all no grant could ever cover, so nothing of it went,
not even the parts their grants did cover. So:

- **Grants are data.** Each is a `models.Grant` row of the organisation: an id
  the assessment names it by (`key`), four sets of words, and an optional
  parent. The words, Petar, 11 October 2026: its canonical name (`name`), a
  title, one line in plain words on what it lets Rouh do for the contact,
  which the case page shows under the name; a description, the detailed
  explanation of the grant and what it gives, behind the case page's
  information icon; and the prompt the assessment is given about what it
  covers. Every change to them or to the parent is a `models.GrantVersion`,
  kept forever, so a change is undone by putting the version before it back
  (`undo`). The ones there were before are seeded
  (`SEED`): the three levels, which nest because each always held the ones
  below it (`trusted.with_lower`), the owner's inbox, and three new ones, Clockwork,
  Memory and Shared task, so such asks have somewhere to land. Edit rights
  joined them on 14 October 2026, given with Shared task, and went on 16
  October 2026: changing a task is the task's own permission, never a grant
  (`rouh/task_access.py`, MAIL.md D28).
- **Sub grants.** A grant may have a parent. Giving a contact the parent gives
  them every sub grant under it, at any depth; a sub grant can also be given on
  its own, without its parent (`Tree.held`). A sub grant with no tools of its own
  uses its parent's (`Tree.tools_of`): it is a narrower piece of what the parent
  does, so it needs nothing new. A grant with no parent and no tools - a new
  independent one - only lets an ask be answered and judged covered; nothing new
  can be done without code that does it.
- **Where holding is kept.** A level's in `TrustedContact.levels`, the inbox's in
  `TrustedContact.inbox_scope` (set on the contact's page, with how far), and
  every other grant's as a `models.ContactGrant`. A grant merged into another
  (`merge`) is kept with `merged_into`, and whoever held it holds the other.
  Somebody not on the Trusted contacts holds Communication alone, never a grant
  under it (`trusted.BASELINE`).
- **Hard limits are not grants** (`HARD_LIMITS`): money, his accounts and
  passwords, sending as him, deleting his mail, forwarding it outside, sending
  or sharing with somebody other than the contact, committing his time,
  publishing, anything that cannot be undone, and doubt about who wrote. An ask
  that names one waits for Petar on its own (`mail_ledger.judge`), and what a
  turn can do is held where it acts: a tool with a hard-limit effect is used
  only for an ask he approved with that limit (`mail_turn.EFFECTS`, Petar, 11
  October 2026, D3). No word of a grant's text is read for hard limits.
- **A grant that lifts one** (`LIFTS`, Petar, 15 October 2026, fr_0cefb1d3ed8a,
  after a contact's "block [his] calendar for the dates" was shown as "Never a
  grant": "The correct behavior was that I get another grant creation that I can
  grant the person"). Some hard limits can be lifted for one contact by a grant
  whose tools are the very tools with that effect, and only by the code's own
  words and tools here, never by a model's: committing his time is lifted by
  Your calendar. An ask that touches it is proposed that grant - since 21 October
  2026 as a grant of its own, as data, on the calendars he picks (CAPABILITIES.md),
  or the one already on their page (`Tree.lifting`); until he gives it, it waits,
  and Allow once still lets it go once.
  The rest stay hard: no grant ever lifts money, his accounts, sending as him or
  doubt about who wrote.

**Since 21 October 2026 words allow nothing** (CAPABILITIES.md, MAIL.md D35). What a grant lets
Rouh do is the capabilities the code declares for it (`rouh/capabilities.py`, a capability's
`legacy_grant`), never its prompt: no reading is given grants' prompts, no grant is made or
widened from words (`create`, `append_prompt` and `merge` are gone), and one made from words with
nothing in code behind it is kept, for review, and allows nothing. A grant's words are how it is
said; its versions are kept as they always were.

Every query names the organisation, and a contact's holding the person too
(`AGENTS.md`, "Whose data is it").
"""
from __future__ import annotations

import re
import secrets
import time
from dataclasses import dataclass, field

from . import owner
from . import trusted as trust

#: What no grant ever covers, each as the code and the owner's page say it. Petar, 11 October
#: 2026: "Hard limits stay hard and are not grants".
HARD_LIMITS: dict[str, str] = {
    "money": "‹owner›'s money: paying, buying, booking, transferring, or ‹his› bank or card "
             "details.",
    "accounts": "‹His› accounts and passwords: a login, a password, a code, or who may reach an "
                "account of ‹his›.",
    "as_owner": "Sending as ‹owner›, in ‹his› name.",
    "delete_mail": "Deleting ‹his› mail.",
    "forward_outside": "Forwarding ‹his› mail to anybody outside.",
    "third_party": "Sending or sharing anything with somebody other than the contact who "
                   "asked.",
    "time": "Committing ‹his› time, or changing ‹his› calendar: a meeting, a call, a date or a "
            "slot in ‹his› name.",
    "publish": "Publishing anything, or making it public.",
    "irreversible": "Anything that cannot be undone.",
    "identity_doubt": "Acting when it is not certain who really wrote.",
}

#: The hard limits a grant can lift for the contacts who hold it, each with the grant Rouh
#: proposes for it: its words, and the tools it brings, each a tool whose effect is that limit
#: (`mail_turn.EFFECTS`). Petar, 15 October 2026 (fr_0cefb1d3ed8a): an ask that touches a hard
#: limit comes with "another grant creation that I can grant the person". A limit not here stays
#: hard: allowed once, or not.
LIFTS: dict[str, dict] = {
    "time": {
        "name": "Your calendar",
        "title": "Rouh puts what they ask into your calendar: blocks dates, adds and moves "
                 "events.",
        "description": ("Committing your time, or changing your calendar, for them: Rouh blocks "
                        "the dates they give, adds an event they ask for, or moves one it made "
                        "for them, in your own calendar. It lifts that hard limit for whoever "
                        "holds it, and only that one: nothing is paid, booked, deleted or sent "
                        "to anybody else, and invitations go to nobody."),
        "prompt": ("Putting into ‹owner›'s own calendar what this contact asks: blocking dates "
                   "they give (a trip, a holiday, a stay), adding an event or a hold, or moving "
                   "one made for them, with create_calendar_event or update_calendar_event. "
                   "Never inviting anybody, never deleting an event, never accepting or "
                   "declining for ‹him›, and never paying or booking anything."),
        "tools": ["create_calendar_event", "update_calendar_event"],
    },
}

#: The catch-all the reading named until 11 October 2026, read back on old cases only.
OLD_CATCH_ALL = "outside_grant"
OLD_CATCH_ALL_SAID = "Old catch-all"

LEVEL, INBOX, GRANT = "level", "inbox", "grant"

#: Clockwork is a time modifier, not a list of its own (Petar, 12 October 2026: "clockwork is
#: about scheduling tasks not just reminders. It should follow everything [they] can do in general
#: without time scheduling"). What an item may do comes from the contact's other grants, checked
#: when it runs (`rouh/clockwork_grants.py`); telling the owner about what they told them is Clockwork
#: alone. Migration 0125 put these words on every organisation's grant.
CLOCKWORK_TITLE = ("Rouh does, at a time or on a repeat, anything they may already have done, and "
                   "tells you of what they told you.")
CLOCKWORK_DESCRIPTION = (
    "A time modifier, not a list of its own: Rouh does at a time, or on a repeat, what their "
    "other grants already let it do for them - a message or a reminder to them on their own "
    "email or Telegram (Communication), a note in your memory (Memory), work for them (Rouh for "
    "themselves), an addition to a task shared with them (Shared task). On its own it tells you, "
    "at a time, about what they told you. Each item is theirs, shows them as its owner and who "
    "it goes to, and is checked against the grants they hold when it runs: take one away and "
    "their items that need it stop, saying why. Hard limits never come with it.")
CLOCKWORK_PROMPT = (
    "Doing at a set time or on a repeat what this contact's other grants already allow, with "
    "clockwork_for_contact: a reminder or a message to them on their own email or their linked "
    "Telegram (Communication: to them, or both), a note in ‹owner›'s memory (Memory), work for them "
    "(Rouh for themselves), an addition to a task shared with them (Shared task); and telling "
    "‹owner› at a time about what they told ‹him›, which is Clockwork alone. Name in also every "
    "other grant the item's work needs: \"remind both of us\" is clockwork with also "
    "communicate. Every item is owned by the contact; only items they own are made, listed or "
    "changed, never ‹owner›'s own and never another contact's. A hard limit is never part of it.")

#: What the Shared task grant is, since 16 October 2026 (MAIL.md D28): making a task they and
#: the owner both add to. Adding to a task, this one or any other, is that task's own permission,
#: never this grant (`rouh/task_access.py`).
SHARED_TASK_TITLE = "Rouh makes a task that you and they both add to."
SHARED_TASK_DESCRIPTION = ("Rouh may make a new task in your Personal column for them, which is "
                           "theirs to edit as well as yours. Adding to a task they may edit needs "
                           "no grant: that is the task's own permission, set beside it on their "
                           "page.")
SHARED_TASK_PROMPT = ("Making a new task of ‹owner›'s that both ‹he› and this contact add to, with "
                      "shared_task create. Adding to a task that is already there is not this: "
                      "it is that task's own permission, and the ask names the task's number in "
                      "task. Making a task for them with what they supplied, done as work for "
                      "them, is Rouh for themselves.")

#: What each organisation starts with, in the order the page lists it. The levels and the
#: inbox keep the ids the code and every old case already name them by.
SEED: list[dict] = [
    {"key": "use", "parent": "", "holding": LEVEL, "position": 10,
     "tools": ["assistant_job", "check_tasks", "look_at_task", "make_picture", "change_picture"],
     "name": "Rouh for themselves",
     "title": ("Rouh does work for them in your workspace, as if you had asked, and sends them the "
               "result."),
     "description": trust.LEVELS["use"][1],
     "prompt": "Work done for them in ‹owner›'s workspace, as if ‹owner› had asked, filed as a task "
               "of ‹his› labelled Guest, and the result sent to them: research, comparisons, "
               "plans, costings, drafts, summaries, pages and presentations, reviewing their "
               "documents, their own legal or personal questions, background jobs included. "
               "Keeping what they supply in such a task, for them, is this too. It never "
               "changes Rouh itself, and never acts in ‹owner›'s mail, calendar, contacts, "
               "memory or Clockwork."},
    {"key": "tasks", "parent": "use", "holding": LEVEL, "position": 20,
     "tools": ["read_granted_tasks", "share_granted_page"],
     "name": "Your tasks",
     "title": ("Rouh answers them from the tasks you picked for them, and shares those tasks' "
               "pages with them."),
     "description": trust.LEVELS["tasks"][1],
     "prompt": "Reading the tasks ‹owner› ticked for them (read_granted_tasks) and answering from "
               "them, read only, and sharing those tasks' pages, or a page of a task done for "
               "them, with them (share_granted_page)."},
    {"key": "communicate", "parent": "tasks", "holding": LEVEL, "position": 30, "tools": [],
     "name": "Communication",
     "title": "Rouh writes back to them: answers, acknowledgements and messages to and from you.",
     "description": trust.LEVELS["communicate"][1],
     "prompt": "Writing back to them: answers, acknowledgements, saying what Rouh can and cannot "
               "do for them, messages to and from ‹owner›, logistics ‹he› already agreed. Nothing "
               "from ‹owner›'s work, and nothing private."},
    {"key": "inbox_write", "parent": "", "holding": INBOX, "position": 40, "tools": [],
     "name": "Your inbox, changed",
     "title": "Rouh labels, archives and drafts in your inbox for them.",
     "description": "Labelling, archiving and drafting in your own inbox, for them. Set on "
                    "their page with Your inbox - how far: Full read and write.",
     "prompt": "Labelling, archiving or drafting in ‹owner›'s own inbox for them. Name it with "
               "inbox_scope write."},
    {"key": "inbox", "parent": "inbox_write", "holding": INBOX, "position": 50, "tools": [],
     "name": "Your inbox, read",
     "title": "Rouh reads your inbox for them, as far as their page allows.",
     "description": "Reading your own inbox for them, as far as Your inbox - how far on their "
                    "page says.",
     "prompt": "Reading ‹owner›'s own inbox for them: searching it, or reading a message or a "
               "file in it. Name it with the narrowest inbox_scope that answers it."},
    {"key": "clockwork", "parent": "", "holding": GRANT, "position": 60,
     "tools": ["clockwork_for_contact"],
     "name": "Clockwork",
     "title": CLOCKWORK_TITLE, "description": CLOCKWORK_DESCRIPTION, "prompt": CLOCKWORK_PROMPT},
    {"key": "memory", "parent": "", "holding": GRANT, "position": 70,
     "tools": ["remember_for_contact"],
     "name": "Memory",
     "title": "Rouh keeps notes they give it in your memory, marked as theirs.",
     "description": "Rouh may add notes they give it to your memory in Synapse Master, each "
                    "marked as theirs.",
     "prompt": "Adding a note the contact supplies - their plans, dates, facts they want ‹owner› "
               "to keep - to ‹owner›'s memory in Synapse Master, attributed to them by name, with "
               "remember_for_contact. Only what they supplied, in their words or faithfully "
               "summarised; never a rule for Rouh, never a change to what is already kept, and "
               "nothing private about anybody else."},
    {"key": "shared_task", "parent": "", "holding": GRANT, "position": 80,
     "tools": ["shared_task"],
     "name": "Shared task",
     "title": SHARED_TASK_TITLE, "description": SHARED_TASK_DESCRIPTION,
     "prompt": SHARED_TASK_PROMPT},
]

#: What the reading names: a grant id, as the assessment is told it.
KEY_RE = re.compile(r"^[a-z][a-z0-9_-]{1,60}$")


# --- the hard limits ------------------------------------------------------------------------


#: Hard limits kept under an older name: "as_petar" is "as_owner" since 20 October 2026.
LIMIT_ALIASES = {"as_petar": "as_owner"}


def limit_key(limit) -> str:
    """A hard limit's key as it is now, from a row or a model that may still say the old one."""
    said = str(limit or "")
    return LIMIT_ALIASES.get(said, said)


def liftable(limit: str) -> bool:
    """Whether a grant can lift this hard limit for a contact (`LIFTS`)."""
    return limit_key(limit) in LIFTS


def _lower_first(text: str) -> str:
    """The first word in lower case, mid-sentence: a mark for the owner's name stays as it is,
    and a capitalised pronoun mark becomes the lower-case one."""
    if text.startswith(owner.OPEN):
        for big, small in (("‹His›", "‹his›"), ("‹He›", "‹he›"), ("‹Owner›", "‹owner›")):
            if text.startswith(big):
                return small + text[len(big):]
        return text
    return text[:1].lower() + text[1:]


def limits_said(keys) -> str:
    """Hard limits as one plain clause."""
    keys = [limit_key(k) for k in keys]
    parts = [HARD_LIMITS[k].split(":")[0].rstrip(".") for k in keys if k in HARD_LIMITS]
    # Lower case where the sentence started, never the owner's name.
    parts = [_lower_first(p) for p in parts]
    if not parts:
        return ""
    return parts[0] if len(parts) == 1 else ", ".join(parts[:-1]) + " and " + parts[-1]


# --- the tree -------------------------------------------------------------------------------


@dataclass
class Node:
    key: str
    name: str
    description: str = ""
    title: str = ""
    prompt: str = ""
    parent: str = ""
    holding: str = GRANT
    tools: tuple[str, ...] = ()
    merged_into: str = ""
    revision: int = 1
    position: int = 0
    id: int = 0
    created_at: float = 0.0
    updated_at: float = 0.0

    def as_dict(self) -> dict:
        return {"key": self.key, "name": self.name, "title": self.title_said,
                "description": self.description, "prompt": self.prompt, "parent": self.parent, "holding": self.holding,
                "tools": list(self.tools), "merged_into": self.merged_into,
                "revision": self.revision, "position": self.position, "id": self.id}

    @property
    def title_said(self) -> str:
        """Its title, or, for one made before grants had titles, its description's first
        sentence."""
        return self.title or title_from(self.description)


@dataclass
class Tree:
    """An organisation's grants, read once."""

    nodes: dict[str, Node] = field(default_factory=dict)

    @classmethod
    def of(cls, rows) -> "Tree":
        """A tree from dicts or nodes; `SEED` for the one every organisation starts with."""
        out = cls()
        for row in rows:
            node = row if isinstance(row, Node) else Node(
                key=row["key"], name=row["name"], description=row.get("description", ""),
                title=row.get("title", ""), prompt=row.get("prompt", ""), parent=row.get("parent") or "",
                holding=row.get("holding") or GRANT, tools=tuple(row.get("tools") or ()),
                merged_into=row.get("merged_into") or "", revision=int(row.get("revision") or 1),
                position=int(row.get("position") or 0), id=int(row.get("id") or 0))
            out.nodes[node.key] = node
        return out

    def live(self) -> list[Node]:
        """Every grant not merged away, parents before their sub grants, in the page's order."""
        out: list[Node] = []

        def walk(parent: str) -> None:
            for node in sorted((n for n in self.nodes.values()
                                if not n.merged_into and (n.parent or "") == parent
                                and (not n.parent or n.parent in self.nodes)),
                               key=lambda n: (n.position, n.name.lower())):
                if node not in out:
                    out.append(node)
                    walk(node.key)
        walk("")
        # One whose parent was merged away hangs under where that went.
        for node in self.nodes.values():
            if not node.merged_into and node not in out:
                out.append(node)
        return out

    def resolve(self, key: str) -> str:
        """The grant a key names now, following merges; "" when it is not one."""
        key = str(key or "").strip()
        seen: set[str] = set()
        while key in self.nodes and self.nodes[key].merged_into and key not in seen:
            seen.add(key)
            key = self.nodes[key].merged_into
        return key if key in self.nodes and not self.nodes[key].merged_into else ""

    def parent_of(self, key: str) -> str:
        node = self.nodes.get(self.resolve(key))
        return self.resolve(node.parent) if node is not None and node.parent else ""

    def children(self, key: str) -> list[str]:
        key = self.resolve(key)
        return [n.key for n in self.live() if n.parent and self.resolve(n.parent) == key]

    def under(self, key: str) -> set[str]:
        """Every sub grant under this one, at any depth, not the grant itself."""
        out: set[str] = set()
        todo = list(self.children(key))
        while todo:
            one = todo.pop()
            if one not in out:
                out.add(one)
                todo += self.children(one)
        return out

    def above(self, key: str) -> list[str]:
        """Its parent, the parent's parent, and so on."""
        out, key = [], self.parent_of(key)
        while key and key not in out:
            out.append(key)
            key = self.parent_of(key)
        return out

    def depth(self, key: str) -> int:
        return len(self.above(key))

    def given(self, contact) -> set[str]:
        """What was given the contact directly, before what comes with it."""
        if contact is None:
            return set()
        if getattr(contact, "implicit", False):
            return {k for k in trust.BASELINE if k in self.nodes}
        if not getattr(contact, "trusted", False):
            return set()
        out = {self.resolve(k) for k in getattr(contact, "levels", None) or ()}
        scope = getattr(contact, "inbox_scope", trust.INBOX_NONE) or trust.INBOX_NONE
        if scope != trust.INBOX_NONE:
            out.add(self.resolve("inbox"))
        if scope == trust.INBOX_WRITE:
            out.add(self.resolve("inbox_write"))
        out |= {self.resolve(k) for k in getattr(contact, "extra_grants", None) or ()}
        out.discard("")
        return out

    def held(self, contact) -> set[str]:
        """Every grant this contact holds now: what was given them and every sub grant under it.

        Somebody not on the Trusted contacts holds Communication and nothing under
        it, and a contact switched off holds nothing. The inbox is held as its reach
        says, and how far is still the contact page's (`trusted.INBOX_SCOPES`).
        """
        out = self.given(contact)
        if getattr(contact, "implicit", False):
            return out
        for key in list(out):
            if self.nodes.get(key) is not None and self.nodes[key].holding != INBOX:
                out |= {k for k in self.under(key) if self.nodes[k].holding != INBOX}
            elif self.nodes.get(key) is not None:
                out |= self.under(key)
        return out

    def holds(self, contact, key: str) -> bool:
        key = self.resolve(key)
        return bool(key) and key in self.held(contact)

    def tools_of(self, key: str) -> tuple[str, ...]:
        """The case tools a grant adds: its own, or, for a sub grant with none, its parent's."""
        key = self.resolve(key)
        node = self.nodes.get(key)
        seen: set[str] = set()
        while node is not None and not node.tools and node.holding == GRANT and node.parent \
                and node.key not in seen:
            seen.add(node.key)
            node = self.nodes.get(self.resolve(node.parent))
        return tuple(node.tools) if node is not None else ()

    def lifts(self, key: str) -> set[str]:
        """The hard limits this grant lifts for whoever holds it: those of `LIFTS` its tools
        have the effect of (`mail_turn.EFFECTS`)."""
        from .mail_turn import EFFECTS

        return {EFFECTS[t] for t in self.tools_of(key) if EFFECTS.get(t) in LIFTS}

    def lifting(self, limit: str, contact=None) -> str:
        """The grant that lifts this hard limit: one the contact holds first, else the first
        there is, else ""."""
        limit = limit_key(limit)
        if limit not in LIFTS:
            return ""
        found = [n.key for n in self.live() if limit in self.lifts(n.key)]
        held = self.held(contact) if contact is not None else set()
        return next((k for k in found if k in held), found[0] if found else "")

    def tools_for(self, keys) -> tuple[str, ...]:
        out: list[str] = []
        for key in keys:
            for tool in self.tools_of(key):
                if tool not in out:
                    out.append(tool)
        return tuple(out)

    def name(self, key: str) -> str:
        if key == OLD_CATCH_ALL:
            return OLD_CATCH_ALL_SAID
        node = self.nodes.get(self.resolve(key)) or self.nodes.get(key)
        return node.name if node is not None else key

    def path_said(self, key: str) -> str:
        """"Rouh for themselves > Your tasks" for a sub grant, its name for the rest."""
        key = self.resolve(key)
        return " > ".join([self.name(k) for k in reversed(self.above(key))] + [self.name(key)])

    def as_list(self) -> list[dict]:
        return [{**n.as_dict(), "depth": self.depth(n.key), "path": self.path_said(n.key),
                 "tools": list(self.tools_of(n.key))} for n in self.live()]


def title_from(description: str) -> str:
    """One line out of a description: its first sentence, for a grant with no title."""
    text = " ".join(str(description or "").split())
    m = re.match(r"(.+?[.!?])(?:\s|$)", text)
    line = m.group(1) if m else text
    return line if len(line) <= 160 else line[:159].rstrip() + "…"


def seed_title(key: str) -> str:
    """The title a seeded grant starts with, or ""."""
    return next((one["title"] for one in SEED if one["key"] == key), "")


def seed_tree() -> Tree:
    """The tree every organisation starts with, without a database."""
    return Tree.of(SEED)


# --- reading and seeding ------------------------------------------------------------------


def _node(row) -> Node:
    return Node(key=row.key, name=row.name, description=row.description, title=row.title,
                prompt=row.prompt,
                parent=row.parent.key if row.parent_id and row.parent else "",
                holding=row.holding, tools=tuple(row.tools or ()),
                merged_into=row.merged_into.key if row.merged_into_id and row.merged_into else "",
                revision=row.revision, position=row.position, id=row.id,
                created_at=row.created_at, updated_at=row.updated_at)


def ensure_seeded(org_id: str) -> None:
    """Every seeded grant there for this organisation, made once; nothing already there is changed."""
    from django.db import IntegrityError, transaction

    from .models import Grant, GrantVersion

    if not org_id:
        return
    have = set(Grant.objects.filter(org_id=org_id).values_list("key", flat=True))
    missing = [one for one in SEED if one["key"] not in have]
    if not missing:
        return
    now = time.time()
    try:
        with transaction.atomic():
            made: dict[str, object] = {}
            for one in SEED:
                if one["key"] in have:
                    continue
                row = Grant.objects.create(
                    org_id=org_id, key=one["key"], name=one["name"], title=one["title"],
                    description=one["description"], prompt=one["prompt"],
                    holding=one["holding"], tools=list(one["tools"]), position=one["position"],
                    revision=1, created_at=now, created_by="seed", updated_at=now)
                made[one["key"]] = row
            for one in SEED:
                row = made.get(one["key"])
                if row is None:
                    continue
                if one["parent"]:
                    parent = made.get(one["parent"]) or Grant.objects.filter(
                        org_id=org_id, key=one["parent"]).first()
                    if parent is not None:
                        row.parent = parent
                        row.save(update_fields=["parent"])
                GrantVersion.objects.create(org_id=org_id, grant=row, revision=1, name=row.name,
                                            title=row.title, description=row.description,
                                            prompt=row.prompt,
                                            parent_key=one["parent"], at=now, by="seed",
                                            why="Seeded from what the owner could grant before.")
    except IntegrityError:
        pass                      # made by another process at the same moment


def tree(org_id: str) -> Tree:
    """The organisation's grants as they are now."""
    from .models import Grant

    ensure_seeded(org_id)
    return Tree.of([_node(r) for r in Grant.objects.filter(org_id=org_id)
                    .select_related("parent", "merged_into")])


def keys(org_id: str) -> set[str]:
    """Every id a report may name, merged ones included (read as where they went)."""
    return set(tree(org_id).nodes)


# --- what a contact holds -----------------------------------------------------------------


def extra_of(user_id: str, org_id: str, contact_id) -> list[str]:
    """The grants given one contact as rows (`models.ContactGrant`), by key."""
    from .models import ContactGrant

    return sorted(ContactGrant.objects.filter(user_id=user_id, org_id=org_id,
                                              contact_id=contact_id)
                  .values_list("grant__key", flat=True))


def holders(user_id: str, org_id: str, key: str) -> list[int]:
    """The trusted contacts who hold this grant now, directly or through a parent."""
    from .trusted import TrustStore

    found = tree(org_id)
    return [c.id for c in TrustStore().all(user_id, org_id) if found.holds(c, key)]


def give(user_id: str, org_id: str, contact_id, key: str, *, by: str, case_key: str = "") -> str:
    """Give one trusted contact a grant. Answers what it did, in a sentence; ValueError when it
    cannot be given here. A level is written as their level (with every level below it); the
    inbox is set on their page with how far, so it is never given here."""
    from django.db import transaction

    from .models import ContactGrant, Grant, TrustedContact

    found = tree(org_id)
    key = found.resolve(key)
    node = found.nodes.get(key)
    if node is None:
        raise ValueError("That grant is not there any more.")
    row = TrustedContact.objects.filter(user_id=user_id, org_id=org_id, id=int(contact_id)).first()
    if row is None:
        raise ValueError("That contact is not one of yours.")
    if node.holding == INBOX:
        raise ValueError(f"{node.name} is set on {row.name}'s page, under Your inbox - how far.")
    with transaction.atomic():
        row = TrustedContact.objects.select_for_update().get(id=row.id)
        if node.holding == LEVEL:
            levels = trust.with_lower(list(row.levels or []) + [key])
            if levels == trust.with_lower(row.levels):
                return f"{row.name} already has {node.name}."
            row.levels = levels
        else:
            grant = Grant.objects.get(org_id=org_id, key=key)
            _, made = ContactGrant.objects.get_or_create(
                user_id=user_id, org_id=org_id, contact=row, grant=grant,
                defaults={"given_at": time.time(), "given_by": by, "from_case": case_key})
            if not made:
                return f"{row.name} already has {node.name}."
        row.revision += 1
        row.updated_at = time.time()
        row.save()
    return f"Gave {row.name} {node.name}."


def take(user_id: str, org_id: str, contact_id, key: str, *, by: str) -> str:
    """Take a grant of holding "grant" back from one contact (levels and the inbox are on their
    page)."""
    from django.db import transaction

    from .models import ContactGrant, TrustedContact

    found = tree(org_id)
    key = found.resolve(key)
    node = found.nodes.get(key)
    if node is None or node.holding != GRANT:
        raise ValueError("That is taken back on their page.")
    with transaction.atomic():
        row = TrustedContact.objects.select_for_update().filter(
            user_id=user_id, org_id=org_id, id=int(contact_id)).first()
        if row is None:
            raise ValueError("That contact is not one of yours.")
        gone, _ = ContactGrant.objects.filter(user_id=user_id, org_id=org_id, contact=row,
                                              grant__key=key).delete()
        if not gone:
            return f"{row.name} did not have {node.name}."
        row.revision += 1
        row.updated_at = time.time()
        row.save()
    return f"Took {node.name} back from {row.name}."


def set_given(user_id: str, org_id: str, contact_id, wanted, *, by: str,
              calendars: dict | None = None) -> list[str]:
    """The grants of holding "grant" given one contact, from their page: exactly `wanted`.

    `calendars` is, for a grant that lifts committing his time, the calendars ticked under it,
    by key: none ticked is the grant not given, and the ones ticked are all it reaches
    (`calendars_of`). A grant not in it keeps the calendars it had."""
    found = tree(org_id)
    picked = {found.resolve(k): calendar_ids(v) for k, v in (calendars or {}).items()
              if found.resolve(k) and reaches_calendars(found, found.resolve(k))}
    wanted = {found.resolve(k) for k in wanted or ()} - {""}
    wanted = {k for k in wanted if found.nodes[k].holding == GRANT}
    wanted = {k for k in wanted if k not in picked or picked[k]} | {k for k, v in picked.items() if v}
    have = {found.resolve(k) for k in extra_of(user_id, org_id, contact_id)} - {""}
    said = []
    for key in sorted(wanted - have):
        said.append(give(user_id, org_id, contact_id, key, by=by))
    for key in sorted(have - wanted):
        said.append(take(user_id, org_id, contact_id, key, by=by))
    for key in sorted(k for k in picked if k in wanted):
        changed = put_calendars(user_id, org_id, contact_id, key, picked[key])
        if changed:
            said.append(changed)
    return said


# --- which calendars a calendar grant reaches ---------------------------------------------
#
# Petar, 16 October 2026 (fr_6c6d23abe250): "This Grant for calendar needs to be able to work
# with multiple calendars ... you pick which calendar specifically you approve." A grant that
# lifts committing his time is given one calendar at a time on the contact's page, and reaches
# only the calendars ticked there (`models.ContactGrant.calendars`); the calendar tools refuse
# any other in a case's turn (`tools._calendar_in_case`). A calendar connected later starts
# unticked for everybody. A row from before there was a choice, or given from a case, is None
# and reaches every calendar, as it always did, until the page is saved with what is ticked.

#: The hard limit a calendar grant lifts.
CALENDAR_LIMIT = "time"


def reaches_calendars(found: Tree, key: str) -> bool:
    """Whether this grant is given calendar by calendar: it lifts committing his time."""
    return CALENDAR_LIMIT in found.lifts(key)


def calendar_ids(value) -> list[str]:
    out: list[str] = []
    for one in value if isinstance(value, (list, tuple)) else ():
        one = str(one or "").strip()[:300]
        if one and one not in out:
            out.append(one)
    return out[:200]


def calendars_of(user_id: str, org_id: str, contact_id) -> dict[str, list[str] | None]:
    """The calendar grants given one contact as rows, by key, each with the calendar ids it
    reaches, or None for every calendar."""
    from .models import ContactGrant

    found = tree(org_id)
    out: dict[str, list[str] | None] = {}
    for key, ids in (ContactGrant.objects.filter(user_id=user_id, org_id=org_id,
                                                  contact_id=contact_id)
                     .values_list("grant__key", "calendars")):
        key = found.resolve(key)
        if key and reaches_calendars(found, key):
            out[key] = None if ids is None else calendar_ids(ids)
    return out


def calendar_reach(user_id: str, org_id: str, contact_id) -> frozenset | None:
    """Every calendar a contact's calendar grants reach together, or None when nothing narrows
    it: a grant from before there was a choice, or none given as a row at all (Petar's Allow
    once, or one that came with another grant)."""
    given = calendars_of(user_id, org_id, contact_id) if contact_id else {}
    if not given or any(ids is None for ids in given.values()):
        return None
    return frozenset(i for ids in given.values() for i in ids or ())


def put_calendars(user_id: str, org_id: str, contact_id, key: str, ids: list[str]) -> str:
    """Keep which calendars one contact's calendar grant reaches. Answers what changed, or ""."""
    from django.db import transaction

    from .models import ContactGrant, TrustedContact

    with transaction.atomic():
        row = ContactGrant.objects.select_for_update().filter(
            user_id=user_id, org_id=org_id, contact_id=int(contact_id), grant__key=key).first()
        if row is None or (row.calendars is not None and sorted(row.calendars) == sorted(ids)):
            return ""
        row.calendars = list(ids)
        row.save(update_fields=["calendars"])
        person = TrustedContact.objects.select_for_update().get(id=row.contact_id)
        person.revision += 1
        person.updated_at = time.time()
        person.save(update_fields=["revision", "updated_at"])
    n = len(ids)
    return f"{tree(org_id).name(key)} reaches {n} calendar{'' if n == 1 else 's'} for {person.name}."


# --- changing grants: every change a version ------------------------------------------------


def _clean_words(name, title, description, prompt) -> tuple[str, str, str, str]:
    name = " ".join(str(name or "").split())[:120]
    title = " ".join(str(title or "").split())[:240]
    description = str(description or "").strip()[:2000]
    prompt = str(prompt or "").strip()[:4000]
    if not name:
        raise ValueError("Give the grant a name.")
    if not prompt:
        raise ValueError("Say what the grant covers, in the words the reading is given.")
    return name, title or title_from(description), description, prompt


def _new_key(org_id: str, name: str) -> str:
    from .models import Grant

    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:32] or "grant"
    while True:
        key = f"g-{slug}-{secrets.token_hex(2)}"
        if not Grant.objects.filter(org_id=org_id, key=key).exists():
            return key


def _version(row, *, by: str, why: str, case_key: str = "") -> None:
    from .models import GrantVersion

    GrantVersion.objects.create(org_id=row.org_id, grant=row, revision=row.revision,
                                name=row.name, title=row.title, description=row.description,
                                prompt=row.prompt,
                                parent_key=row.parent.key if row.parent_id else "",
                                at=time.time(), by=by, why=why[:500], case_key=case_key)


def _parent_row(org_id: str, parent_key: str, *, child=None):
    from .models import Grant

    if not parent_key:
        return None
    found = tree(org_id)
    key = found.resolve(parent_key)
    if not key:
        raise ValueError("That parent grant is not there any more.")
    if child is not None and (key == child.key or key in found.under(child.key)):
        raise ValueError("A grant cannot sit under itself or under one of its own sub grants.")
    if found.nodes[key].holding == INBOX:
        raise ValueError("Nothing can sit under your inbox: how far it reaches is set on each "
                         "contact's page.")
    return Grant.objects.get(org_id=org_id, key=key)


def edit(org_id: str, key: str, *, name=None, title=None, description=None, prompt=None,
         parent_key: str | None = None, by: str, why: str = "", case_key: str = "") -> Node:
    """Change a grant's name, title, description, prompt or parent: a new version, the old one
    kept."""
    from django.db import transaction

    from .models import Grant

    found = tree(org_id)
    key = found.resolve(key)
    if not key:
        raise ValueError("That grant is not there any more.")
    with transaction.atomic():
        row = Grant.objects.select_for_update(of=("self",)).select_related("parent").get(org_id=org_id,
                                                                              key=key)
        new = _clean_words(row.name if name is None else name,
                           row.title if title is None else title,
                           row.description if description is None else description,
                           row.prompt if prompt is None else prompt)
        parent = row.parent
        if parent_key is not None:
            if row.holding != GRANT and (parent_key or "") != (row.parent.key if row.parent_id
                                                               else ""):
                raise ValueError(f"{row.name} keeps its place: where it sits says what comes "
                                 "with what, and the code relies on it.")
            parent = _parent_row(org_id, parent_key, child=row)
        if new == (row.name, row.title, row.description, row.prompt) and parent == row.parent:
            return found.nodes[key]
        row.name, row.title, row.description, row.prompt = new
        row.parent = parent
        row.revision += 1
        row.updated_at = time.time()
        row.save()
        _version(row, by=by, why=why or "Changed.", case_key=case_key)
    return tree(org_id).nodes[key]


def versions(org_id: str, key: str) -> list[dict]:
    from .models import GrantVersion

    found = tree(org_id)
    key = found.resolve(key) or key
    return [{"revision": v.revision, "name": v.name, "title": v.title,
             "description": v.description,
             "prompt": v.prompt, "parent": v.parent_key, "at": v.at, "by": v.by, "why": v.why,
             "case": v.case_key}
            for v in GrantVersion.objects.filter(org_id=org_id, grant__key=key)
            .order_by("-revision")]


def undo(org_id: str, key: str, *, by: str, to_revision: int | None = None) -> Node:
    """Put a grant's version before the last one back (or `to_revision`), as a new version."""
    from .models import GrantVersion

    found = tree(org_id)
    key = found.resolve(key)
    if not key:
        raise ValueError("That grant is not there any more.")
    node = found.nodes[key]
    want = to_revision if to_revision is not None else node.revision - 1
    old = GrantVersion.objects.filter(org_id=org_id, grant__key=key, revision=want).first()
    if old is None:
        raise ValueError("There is no earlier version to go back to.")
    return edit(org_id, key, name=old.name, title=old.title, description=old.description,
                prompt=old.prompt,
                parent_key=old.parent_key if node.holding == GRANT else None, by=by,
                why=f"Put back as it was at version {want}.")


__all__ = ["HARD_LIMITS", "LIFTS", "LIMIT_ALIASES", "OLD_CATCH_ALL", "OLD_CATCH_ALL_SAID", "SEED", "Node", "Tree",
           "CALENDAR_LIMIT", "calendar_ids", "calendar_reach", "calendars_of", "edit", "ensure_seeded", "extra_of", "give",
           "holders", "liftable", "limit_key", "limits_said", "put_calendars", "seed_tree",
           "reaches_calendars", "seed_title", "set_given", "take", "title_from", "tree", "undo", "versions"]
