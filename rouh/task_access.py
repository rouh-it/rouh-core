"""The one permission: what a person may do with each thing of the owner's - read, edit or decide.

Petar, 21 October 2026, after a trusted contact who decides for a quest was told by email that
her asks to edit its tasks waited for him: "Combine delegate grants and task/page shares into ONE
permission record that every check reads. Do not keep two flags in sync." Until then her
authority to decide was a table of its own (`delegations`) that the mail gate never read, while
her shares said she might only read.

The record is a share row (`models.PageGuest`): one person, by their email address, one thing -
a page, or a quest, a goal, a task or a step (`rel` "_task/<folder>") - and a level, lowest
first:

- **read** ("view"): open it, its notes, its pages and its steps;
- **edit**: change it too, its pages with Ask AI, and talk to Rouh in it;
- **decide**: decide for the owner there too - its decisions, its steps, its plan, its quest's
  brief (`rouh/delegation.py`). Only ever a trusted contact's, switched on.

Each includes the ones before it. Money, deleting, publishing, sending, signing or committing the
owner to anybody, and changes to Rouh itself are never part of any level (`delegation.NEVER`).

**Inherited down the tree.** A record on a quest reaches the goals the quest names
(`quest_goals`, its meta's quest block) as well as its own task; a record on a goal or a
task reaches its steps; a record on any of them reaches their pages. The most specific record
wins: one on a step says what that step is whatever is above it, so a lower record may narrow
what it inherits as well as widen it (`Access.why`).

Two other things say something, and each gives way to a record:

1. **Started by them** - a task done at their request (tagged Guest with their address or their
   Telegram account) or made shared with them under Shared task - is theirs to edit, until the
   owner takes it back (`requester_share` wrote it down and its share is gone). Rouh shares it
   with them to edit the moment it sees it (`rouh/requester_share.py`); until then, and for
   somebody with no email address, this is what says so.
2. **Ticked** on a trusted contact's page with Your tasks: a column, a project or a task, and
   everything under it, now and made later. At least read, and never less than that: a tick is a
   floor, never a record that narrows. Every task under it is shared with them to read, quietly
   and kept by the tick (`keep_ticks`, `TICK`), so Rouh's own pages agree, and those rows count as
   the tick, not as a record.

Everything reads the level here and nowhere else: Rouh's pages (`level_of_share`, the Share panel
and the guest pages), a trusted contact's email and Telegram through `trusted.Grants`, the judge
of a case's asks (`for_judge`), the decisions list and the delegate's tools
(`delegation.Scope`), Ask AI on a shared page, and the contact's page, which draws it and
changes it (`set_level`). Every query names the owner's user and organisation (`AGENTS.md`,
"Whose data is it").
"""
from __future__ import annotations

import logging

from . import sharing
from . import trusted as trust

log = logging.getLogger("rouh.task_access")

#: How many tasks' metas are read one at a time before every one is read at once (`Access.meta`).
ONE_BY_ONE = 8

#: The levels, lowest first. "" is none.
NONE, READ, EDIT, DECIDE = "", sharing.VIEW, sharing.EDIT, sharing.DECIDE
RANK = {NONE: 0, READ: 1, EDIT: 2, DECIDE: 3}
#: How each level is said.
WORDS = {READ: "read", EDIT: "edit", DECIDE: "decide"}

#: `PageGuest.via` for a share a ticked column or project on the contact's page keeps.
TICK = "tick"

#: Where a level came from: a record on it, one inherited from above, their own request, a tick.
SHARED, INHERITED, STARTED, TICKED = "shared", "inherited", "started", "ticked"

#: `RequesterShare.outcome` for a task the owner took away from whoever asked for it, so it is not
#: theirs to edit by being theirs any more, and is never shared with them again by itself.
STOPPED = "stopped"


def higher(a: str, b: str) -> str:
    return a if RANK.get(a, 0) >= RANK.get(b, 0) else b


def at_least(level: str, wanted: str) -> bool:
    """Whether `level` covers `wanted`: decide covers edit, and edit covers read."""
    return RANK.get(level or NONE, 0) >= RANK.get(wanted or NONE, 0)


def _root() -> str:
    from .config import config

    return getattr(config, "assistant_repo", "") or ""


def _store():
    from . import objects

    return objects.shared_store(even_when_off=True)


def _emails(contact) -> set[str]:
    return {sharing.clean_email(a) for a in getattr(contact, "addresses", ()) or ()} - {""}


def _stopped(owner, contact) -> set[str]:
    """The tasks Rouh shared with them because they asked for them, or that the owner took away
    from them, by task id: if no share of one is there now, it was taken away."""
    from .models import RequesterShare

    if owner is None or contact is None:
        return set()
    marks = _emails(contact) | {str(t) for t in getattr(contact, "telegram", ()) or ()}
    if not marks:
        return set()
    return set(RequesterShare.objects.filter(user_id=owner.user_id, org_id=owner.org_id,
                                             email__in=sorted(marks))
               .values_list("task_id", flat=True))


# --- a quest's goals ------------------------------------------------------------------------


def quest_goals(meta: dict) -> list[str]:
    """The goals a quest's task names as its own (its meta's "quest": {"goals": [...]}), by
    their task ids: what a permission on the quest reaches besides its own task."""
    block = meta.get("quest") if isinstance(meta, dict) else None
    goals = block.get("goals") if isinstance(block, dict) else None
    return [str(g) for g in goals if str(g or "").strip()] if isinstance(goals, list) else []


def _quest_links(tree, root) -> tuple[dict[str, list[str]], dict[str, str]]:
    """({quest task id: [its goals' task ids]}, {goal task id: its quest's task id}), read from
    the quests' own meta. A goal one quest names is that quest's; a quest is a task
    tagged quest (`rouh/quests.py`)."""
    down: dict[str, list[str]] = {}
    up: dict[str, str] = {}
    for ident, row in tree.rows.items():
        if row.get("type") != "task" or not row.get("folder"):
            continue
        folder = row["folder"]
        # Only a quest's folder is read: its task holds the quest files.
        if not _looks_like_quest(root, folder):
            continue
        meta = trust.task_meta(root, folder)
        goals = [g for g in quest_goals(meta) if g in tree.rows and g != ident]
        if goals:
            down[ident] = goals
            for g in goals:
                up.setdefault(g, ident)
    return down, up


def _looks_like_quest(root, folder: str) -> bool:
    from pathlib import Path

    try:
        return (Path(root) / folder / "quest-goal.md").is_file()
    except OSError:
        return False


class Access:
    """What one person may do with each of the owner's tasks and pages, worked out now.

    `owner` is whose they are (`tenancy.Identity`), `store` the object store, `root` the
    workspace. The person is a trusted contact (`contact`), or anybody by their email addresses
    (`emails`) - somebody a page or a task was shared with who is not on the Trusted contacts.
    Only a trusted contact, switched on, may decide; anybody else holding a record of decide has
    edit, which it includes. A contact switched off has nothing.
    """

    def __init__(self, store, root, contact, owner, *, tree=None, emails=()) -> None:
        self.root = root
        self.contact = contact
        self.owner = owner
        self.tree = tree or trust.Tree(store)
        listed = contact is not None and not getattr(contact, "implicit", True)
        self.decides = bool(listed and getattr(contact, "trusted", False))
        mails = _emails(contact) if listed else \
            {sharing.clean_email(e) for e in emails or ()} - {""}
        self.on = self.decides or (not listed and bool(mails))
        # The records: by task folder, and by page path, explicit only. A share a tick keeps is
        # the tick's, and counts as the tick below.
        self.shares: dict[str, str] = {}
        self.pages: dict[str, str] = {}
        self.records: list[dict] = []
        if self.on and owner is not None:
            from . import taskshare

            for person in sharing.Guests().with_addresses(owner, mails):
                if person.get("via") == TICK:
                    continue
                role = person["role"]
                if role == DECIDE and not self.decides:
                    role = EDIT
                self.records.append({**person, "role": role})
                folder = taskshare.folder_of(person["rel"])
                if folder:
                    self.shares[folder] = higher(self.shares.get(folder, ""), role)
                elif not taskshare.is_task(person["rel"]):
                    self.pages[person["rel"]] = higher(self.pages.get(person["rel"], ""), role)
        self.stopped = _stopped(owner, contact) if self.decides else set()
        self.ticked: set[str] = set()
        if self.decides and "tasks" in (contact.levels or ()):
            for one in contact.grants or ():
                if one in self.tree.rows and self.tree.column_of(one) in trust.COLUMNS:
                    self.ticked |= self.tree.under(one)
        self._meta: dict[str, dict] = {}
        self._all_meta: tuple[dict[str, dict], set[str]] | None = None
        self._asked = 0
        self._seen: dict[str, tuple[str, str, str]] = {}
        self._links: tuple[dict, dict] | None = None
        self._folders: dict[str, str] | None = None

    def meta(self, folder: str) -> dict:
        if folder not in self._meta:
            whole = self._every_meta()
            if whole is not None and folder in whole[1]:
                self._meta[folder] = whole[0].get(folder) or {}
            else:
                self._meta[folder] = trust.task_meta(self.root, folder)
        return self._meta[folder]

    def _every_meta(self) -> tuple[dict[str, dict], set[str]] | None:
        """Every task's meta by its row's folder, and every folder a row has, read in two
        queries once more than a few have been asked for one at a time. Reading a whole
        tree's worth one by one was two queries a task: 2,709 of them, and 5.8 seconds, for
        the four goals the Goals page lists on the first Rouh (23 October 2026). A folder no row
        names is still read on its own, by its `.object.json` (`taskmeta.task_id`)."""
        if self._all_meta is None:
            self._asked += 1
            if self._asked <= ONE_BY_ONE or not self.root:
                return None
            from . import taskmeta
            from .models import Task

            try:
                self._all_meta = (taskmeta.by_folder(),
                                  set(Task.objects.exclude(folder="").values_list("folder", flat=True)))
            except Exception:  # noqa: BLE001 - one at a time still answers
                log.exception("every task's meta could not be read at once")
                self._all_meta = ({}, set())
        return self._all_meta

    def links(self) -> tuple[dict[str, list[str]], dict[str, str]]:
        """The quests' goals both ways (`_quest_links`), read once."""
        if self._links is None:
            self._links = _quest_links(self.tree, self.root) if self.root else ({}, {})
        return self._links

    def _is_task(self, ident: str) -> bool:
        return self.tree.rows.get(ident, {}).get("type") == "task"

    def line(self, ident: str) -> list[str]:
        """This task and everything a permission on it is inherited from, nearest first: the
        tasks above it, a step going with its task, and then the quest a goal among them
        belongs to, and what is above that."""
        out, seen = [], set()
        _down, up = self.links()
        while ident and ident not in seen and self._is_task(ident):
            seen.add(ident)
            out.append(ident)
            above = self.tree.owner.get(ident, "")
            if not self._is_task(above):
                above = up.get(ident, "")
            ident = above
        return out

    def under(self, ident: str) -> set[str]:
        """This task and every task a permission on it reaches: what is under it, and, for a
        quest, the goals it names and what is under each."""
        down, _up = self.links()
        out, todo = set(), [ident]
        while todo:
            one = todo.pop()
            if one in out:
                continue
            got = self.tree.under(one)
            out |= got
            todo += [g for q in got for g in down.get(q, ())]
        return out

    def why(self, ident: str) -> tuple[str, str]:
        """(level, where it came from: `SHARED`, `INHERITED`, `STARTED` or `TICKED`), or
        ("", "")."""
        got = self.why_from(ident)
        return got[0], got[1]

    def why_from(self, ident: str) -> tuple[str, str, str]:
        """(level, where it came from, the task whose record it is), or ("", "", "")."""
        if ident in self._seen:
            return self._seen[ident]
        got = ("", "", "")
        within = getattr(self.contact, "within", None)
        if within is not None and ident not in within:
            # An answer others read too: only what every one of them may read (`slack_team`).
            self._seen[ident] = got
            return got
        if self.on and self._is_task(ident):
            line = self.line(ident)
            # The most specific record wins, and a request of theirs is as specific as its task.
            for at, one in enumerate(line):
                folder = self.tree.rows[one].get("folder") or ""
                level = self.shares.get(folder, "") if folder else ""
                if level:
                    got = (level, SHARED if at == 0 else INHERITED, one)
                    break
                if folder and self.decides and one not in self.stopped and \
                        trust.started_by(self.meta(folder), self.contact):
                    got = (EDIT, STARTED, one)
                    break
            if RANK[got[0]] < RANK[READ] and any(one in self.ticked for one in line):
                got = (READ, TICKED, "")
        self._seen[ident] = got
        return got

    def why_above(self, ident: str) -> tuple[str, str, str]:
        """What `why_from` would say with no record on this task itself: what it inherits."""
        got = ("", "", "")
        if not self.on or not self._is_task(ident):
            return got
        line = self.line(ident)
        for one in line[1:]:
            folder = self.tree.rows[one].get("folder") or ""
            level = self.shares.get(folder, "") if folder else ""
            if level:
                return level, INHERITED, one
            if folder and self.decides and one not in self.stopped and \
                    trust.started_by(self.meta(folder), self.contact):
                return EDIT, STARTED, one
        if any(one in self.ticked for one in line):
            return READ, TICKED, ""
        return got

    def level(self, ident: str) -> str:
        return self.why(ident)[0]

    def levels(self) -> dict[str, str]:
        """Every task and step they may read, by id, with its level."""
        return {ident: lvl for ident in self.tree.rows if (lvl := self.level(ident))}

    def by_folder(self, folder: str) -> str:
        """The task whose folder this is, or ""."""
        if self._folders is None:
            self._folders = {(r.get("folder") or "").strip("/"): i
                             for i, r in self.tree.rows.items()
                             if r.get("type") == "task" and r.get("folder")}
        return self._folders.get(str(folder or "").strip("/"), "")

    def task_of_path(self, rel: str) -> str:
        """The innermost task a workspace path is in, or ""."""
        parts = str(rel or "").strip("/").split("/")
        for n in range(len(parts), 0, -1):
            found = self.by_folder("/".join(parts[:n]))
            if found:
                return found
        return ""

    def of_rel(self, rel: str) -> str:
        """The level on a thing as a share names it: a page's path, or "_task/<folder>". A page
        takes its own record when it has one, and otherwise its task's level."""
        from . import taskshare

        rel = str(rel or "")
        if taskshare.is_task(rel):
            ident = self.by_folder(taskshare.folder_of(rel))
            return self.level(ident) if ident else self.shares.get(taskshare.folder_of(rel), "")
        if not self.on:
            return NONE
        if rel in self.pages:
            return self.pages[rel]
        ident = self.task_of_path(rel)
        return self.level(ident) if ident else NONE

    def number_of(self, ident: str) -> str:
        from . import searching

        row = self.tree.rows.get(ident) or {}
        number = row.get("number")
        return str(number) if number is not None else \
            searching.number_of_folder(row.get("folder") or "")

    def find(self, wanted) -> str:
        """The task a number ("90", "90-03"), an id or a folder names, or ""."""
        wanted = str(wanted or "").strip().lstrip("#")
        if not wanted:
            return ""
        if wanted in self.tree.rows:
            return wanted if self._is_task(wanted) else ""
        for ident, row in self.tree.rows.items():
            if row.get("type") != "task":
                continue
            if wanted == (row.get("folder") or "") or wanted == self.number_of(ident):
                return ident
        return ""

    def by_number(self) -> dict[str, dict]:
        """What the judge of a case's asks reads (`mail_ledger.judge`): every task by its number,
        {"level", "title", "id", "from"}, the ones they may not open included, so an ask about one
        of them says which it is. "from" is the number of the task whose record a level comes
        through when it is inherited (a quest's, for its goals), so a case's reading is told "129
        (through 128)" and matches an ask to what they hold (MAIL.md D34)."""
        out = {}
        for ident, row in self.tree.rows.items():
            if row.get("type") != "task":
                continue
            number = self.number_of(ident)
            if number:
                level, came, where = self.why_from(ident)
                out[number] = {"level": level, "id": ident,
                               "title": row.get("title") or row.get("slug") or number,
                               "from": self.number_of(where) if came == INHERITED and where
                               else ""}
        return out


def access_for(owner, contact, *, store=None, root: str | None = None) -> Access | None:
    """`Access` for a contact on this machine's workspace, or None when it is not open here."""
    store = store if store is not None else _store()
    root = _root() if root is None else root
    if store is None or not root:
        return None
    return Access(store, root, contact, owner)


def for_email(owner, email: str) -> Access | None:
    """`Access` for whoever signs in with this address: the owner's trusted contact it is
    ticked for, switched on, or else anybody it was shared with. None when the workspace is not
    open here."""
    store, root = _store(), _root()
    if store is None or not root or owner is None:
        return None
    contact = trust.TrustStore().trusted_for(str(owner.user_id), str(owner.org_id),
                                             sharing.clean_email(email))
    if contact is not None and getattr(contact, "trusted", False):
        return Access(store, root, contact, owner)
    return Access(store, root, None, owner, emails=[email])


def level_of_share(share: dict) -> str:
    """What the person a share names may do with what it names now, read through the one
    record (`Access.of_rel`): the share's own level when nothing more specific or nothing at all
    can be read here. For the guest pages, Ask AI and comments."""
    from .tenancy import Identity

    role = sharing.role_of((share or {}).get("role"))
    try:
        owner = Identity(user_id=str(share["owner_id"]), org_id=str(share["org_id"]))
        found = for_email(owner, share.get("email") or "")
    except Exception:  # noqa: BLE001 - the share's own row still says what it is
        log.exception("task access: the level of a share could not be read")
        return role
    if found is None:
        return role
    return found.of_rel(share.get("rel") or "") or role


#: How each kind of row on the contact's page is said: "Quest 128", "Step 19-17".
KIND_WORD = {"task": "Task", "step": "Step", "quest": "Quest", "goal": "Goal"}


def kind_of(found: "Access", ident: str) -> str:
    """What a task row is on the contact's page: a quest, a goal, a step, or a task."""
    from . import goals

    row = found.tree.rows.get(ident) or {}
    if found._is_task(found.tree.owner.get(ident, "")):
        return "step"
    folder = row.get("folder") or ""
    if folder and (_looks_like_quest(found.root, folder) or
                   "quest" in [str(t).strip().lower() for t in found.meta(folder).get("tags") or []
                               if isinstance(t, str)]):
        return "quest"
    if folder and goals.is_goal(found.meta(folder)):
        return "goal"
    return "task"


def code_of(found: "Access", ident: str) -> str:
    """What a task or step is called by: "128", "19-17"."""
    from . import searching

    row = found.tree.rows.get(ident) or {}
    if found._is_task(found.tree.owner.get(ident, "")):
        return searching.number_of_folder(row.get("folder") or "")
    return found.number_of(ident)


def named(found: "Access", ident: str) -> str:
    """"Quest 128", "Step 19-17", or the title when it has no number."""
    code = code_of(found, ident)
    title = (found.tree.rows.get(ident) or {}).get("title") or ""
    return f"{KIND_WORD[kind_of(found, ident)]} {code}" if code else title


def page_tree(owner, *, store=None, root: str | None = None) -> list[dict]:
    """The one tree on a trusted contact's page (Petar, 21 October 2026: "I expected one
    interface"): Work, Personal and Rouh, their projects, and every task with its steps, each
    quest with the goals it names under it, where a permission on it reaches them. Each node is
    {id, title, kind (column, project, task, step, quest or goal), code, kids}; archived work is
    left out. The same for every contact: what each may do is `page_levels`."""
    from . import archiving

    store = store if store is not None else _store()
    root = _root() if root is None else root
    if store is None or not root:
        return []
    probe = Access(store, root, None, owner)
    tree = probe.tree
    kept = archiving.archived(store)
    down, up = probe.links()

    def title(row) -> str:
        return row.get("title") or row.get("slug") or row["id"]

    def task_node(ident: str, seen: set) -> dict:
        seen = seen | {ident}
        kids = [k for k in tree.kids.get(ident, []) if probe._is_task(k) and k not in kept
                and k not in seen]
        kids.sort(key=lambda k: (code_of(probe, k).split("-")[-1].zfill(4), title(tree.rows[k])))
        goals = [g for g in down.get(ident, ()) if g not in kept and g not in seen]
        return {"id": ident, "title": title(tree.rows[ident]), "kind": kind_of(probe, ident),
                "code": code_of(probe, ident),
                "kids": [task_node(g, seen) for g in goals] + [task_node(k, seen) for k in kids]}

    def number(ident: str) -> int:
        raw = tree.rows[ident].get("number")
        return int(raw) if str(raw or "").isdigit() else 0

    def node(ident: str) -> dict:
        row = tree.rows[ident]
        kids = [k for k in tree.kids.get(ident, []) if k not in kept and
                tree.rows[k]["type"] in ("project", "task") and k not in up]
        projects = sorted((k for k in kids if tree.rows[k]["type"] == "project"),
                          key=lambda k: title(tree.rows[k]).lower())
        tasks = sorted((k for k in kids if tree.rows[k]["type"] == "task"),
                       key=lambda k: (-number(k), title(tree.rows[k]).lower()))
        return {"id": ident, "title": title(row),
                "kind": "column" if ident not in tree.owner else "project", "code": "",
                "kids": [node(k) for k in projects] + [task_node(k, set()) for k in tasks]}

    tops = [r for r in tree.rows.values() if r["type"] == "project" and r["id"] not in tree.owner
            and (r.get("slug") or r.get("folder") or "").lower() in trust.COLUMNS]
    tops.sort(key=lambda r: trust.COLUMNS.index((r.get("slug") or r.get("folder") or "").lower()))
    return [node(r["id"]) for r in tops]


def page_levels(owner, contact) -> dict[str, dict]:
    """What the contact's page draws on each row of its tree (`page_tree`), for every task,
    step, quest and goal they may do something with: {id: {"level", "from", "own", "via",
    "above", "above_via", "promise", "by_rouh"}}.

    `level` is what they may do there now, and `from` where it came from (`SHARED` a record on
    it, `INHERITED` one above it, `STARTED` their own request, `TICKED` a ticked project). `own`
    is the level of the record on the row itself, "" when there is none. `via` names what it is
    inherited from ("Quest 128", or the ticked project). When a record on the row overrides what
    is above, `above` and `above_via` say what it would be without it, so it can be cleared."""
    found = access_for(owner, contact)
    if found is None:
        return {}
    from . import taskshare

    extra: dict[str, dict] = {}
    for one in found.records:
        folder = taskshare.folder_of(one.get("rel") or "")
        if folder:
            extra[folder] = one
    out = {}
    for ident, row in found.tree.rows.items():
        if row.get("type") != "task":
            continue
        level, came, where = found.why_from(ident)
        folder = row.get("folder") or ""
        own = found.shares.get(folder, "") if folder else ""
        if not level and not own:
            continue
        one = {"level": level, "from": came, "own": own, "via": "", "above": "",
               "above_via": "", "promise": "", "by_rouh": False}
        if came == INHERITED and where:
            one["via"] = named(found, where)
        elif came == TICKED:
            one["via"] = _ticked_by(found, ident)
        if own:
            above, above_from, above_where = found.why_above(ident)
            one["above"] = above
            one["above_via"] = (named(found, above_where) if above_from == INHERITED and
                                above_where else _ticked_by(found, ident)
                                if above_from == TICKED else "")
            record = extra.get(folder) or {}
            one["promise"] = record.get("pending") or ""
            one["by_rouh"] = record.get("granted_by") == "rouh"
        out[ident] = one
    return out


def _ticked_by(found: "Access", ident: str) -> str:
    """The title of the ticked project or column a task is read through."""
    for one in getattr(found.contact, "grants", None) or ():
        if one in found.tree.rows and ident in found.tree.under(one):
            return (found.tree.rows[one].get("title") or "").strip() or "a ticked project"
    return "a ticked project"


def for_judge(owner, contact) -> dict[str, dict] | None:
    """`Access.by_number` for the judge, or None when the workspace is not open here."""
    if contact is None or getattr(contact, "implicit", True):
        return {}
    try:
        found = access_for(owner, contact)
    except Exception:  # noqa: BLE001 - the judge says it cannot tell, and waits
        log.exception("task access: the levels of contact %s could not be read",
                      getattr(contact, "id", "?"))
        return None
    return found.by_number() if found is not None else None


def inherited(owner, rel: str) -> list[dict]:
    """Who may do something with this task or page only by a record above it - a quest's, a
    goal's, the task a step or a page is in - for the Share panel, which lists them under the
    people it is shared with: [{"email", "role", "from"}], "from" the number (or title) of the
    task whose record it is. Somebody with a record of their own here is the panel's own row."""
    from . import taskshare
    from .models import PageGuest

    store, root = _store(), _root()
    if store is None or not root or owner is None:
        return []
    tree = trust.Tree(store)
    probe = Access(store, root, None, owner, tree=tree)
    if taskshare.is_task(rel):
        ident = probe.by_folder(taskshare.folder_of(rel))
    else:
        ident = probe.task_of_path(rel)
    if not ident:
        return []
    line = probe.line(ident)
    above = [taskshare.PREFIX + (tree.rows[i].get("folder") or "") for i in line
             if taskshare.PREFIX + (tree.rows[i].get("folder") or "") != rel]
    here = set(PageGuest.objects.filter(user_id=owner.user_id, org_id=owner.org_id, rel=rel)
               .exclude(via=TICK).values_list("email", flat=True))
    emails = []
    for r in PageGuest.objects.filter(user_id=owner.user_id, org_id=owner.org_id,
                                      rel__in=above).exclude(via=TICK):
        if r.email not in here and r.email not in emails:
            emails.append(r.email)
    out = []
    for email in emails:
        found = for_email(owner, email)
        if found is None:
            continue
        level = found.of_rel(rel)
        where = found.why_from(ident)[2] if ident else ""
        if level and where and where != ident:
            out.append({"email": email, "role": level, "decides": found.decides,
                        "from": named(found, where)})
    return out


def people_here(owner, rel: str, people: list[dict]) -> list[dict]:
    """The Share panel's people, each with whether they may be given decide - one of the
    owner's trusted contacts, switched on - and, for a share a ticked project keeps, what is
    ticked ("from"), so the panel shows it as coming from there."""
    contacts = [c for c in trust.TrustStore().all(owner.user_id, owner.org_id)
                if getattr(c, "trusted", False)]
    on = {a for c in contacts for a in _emails(c)}
    for p in people:
        p["decides"] = p.get("email") in on
        if p.get("via") == TICK:
            p["from"] = _tick_of(owner, rel, p.get("email") or "")[1] or "a ticked project"
    return people


# --- changing a level ----------------------------------------------------------------------


def _rows_of(owner, rel: str, emails) -> list:
    from .models import PageGuest

    return list(PageGuest.objects.filter(user_id=owner.user_id, org_id=owner.org_id, rel=rel,
                                         email__in=sorted(emails)).order_by("created_at"))


def set_level(owner, contact, ident: str, level: str, *, store=None, root: str | None = None,
              pending: str | None = None, granted_by: str | None = None) -> str:
    """One task, goal, quest or step set to a level for a contact, quietly: no letter goes. The
    sentence of what it is now. ValueError says why it could not be.

    Read, edit or decide is a record of it with them, made or turned (`sharing.Guests.invite`),
    which everything reads. None takes every record of it with them away; what is inherited from
    above still holds, and the sentence says so. A task they asked for is then not theirs to edit
    by that any more. A task under a ticked column or project stays readable while the tick does:
    that is the tick's, and it is taken away by unticking it. `pending` and `granted_by` go on
    the record (`PageGuest.pending`, `PageGuest.granted_by`).
    """
    from . import pages, requester_share, taskshare

    store = store if store is not None else _store()
    root = _root() if root is None else root
    found = Access(store, root, contact, owner) if store is not None and root else None
    if found is None or not found.decides:
        raise ValueError("Only somebody on your Trusted contacts, switched on, can be let in "
                         "to a task here.")
    if level not in (NONE, READ, EDIT, DECIDE):
        raise ValueError("A task is read, edit, decide or nothing.")
    row = found.tree.rows.get(ident) or {}
    folder = row.get("folder") or ""
    if row.get("type") != "task" or not folder:
        raise ValueError("That is not one of your tasks.")
    number = found.number_of(ident)
    title = row.get("title") or folder
    named = f"task {number}, {title}," if number else f"{title},"
    rel = taskshare.PREFIX + folder
    mine = _emails(contact)
    guests = sharing.Guests()
    if level == NONE:
        gone = 0
        for one in _rows_of(owner, rel, mine):
            gone += int(guests.remove(owner, one.token))
        if trust.started_by(found.meta(folder), contact) and ident not in found.stopped:
            mark = next(iter(sorted(mine)), "") or next(iter(contact.telegram or ()), "")
            if mark:
                requester_share._write(owner, ident, folder, mark, STOPPED)
        log.info("task access: %s taken away from contact %s (%d record(s))", rel, contact.id,
                 gone)
        left, came, where = Access(store, root, contact, owner).why_from(ident)
        said = f"{named[:1].upper()}{named[1:]} is not shared with {contact.name} on its own any more"
        if came == INHERITED and where:
            above = found.tree.rows.get(where) or {}
            return (said + f", and they still {WORDS[left]} it through "
                    f"{found.number_of(where) or above.get('title') or 'what it is in'}.")
        return said + (", and they still read it through a ticked project." if left else ".")
    address = requester_share.address_for(contact, found.meta(folder))
    if not address:
        raise ValueError(f"{contact.name} has no email address on your Trusted contacts, so a "
                         "task cannot be shared with them.")
    try:
        rel, shown = sharing.shareable(root, rel)
    except (pages.Refused, OSError) as exc:
        raise ValueError(f"{named} cannot be shared: {exc}") from exc
    there = _rows_of(owner, rel, mine)
    guests.invite(owner, rel, there[0].title if there else shown,
                  there[0].email if there else address, level, pending=pending,
                  granted_by=granted_by)
    log.info("task access: %s set to %s for contact %s", rel, level, contact.id)
    return {DECIDE: f"{contact.name} may decide for {named} and edit it, in Rouh, by email "
                    "and on Telegram.",
            EDIT: f"{contact.name} may edit {named} in Rouh, by email and on Telegram.",
            READ: f"{contact.name} may read {named} and not change it."}[level]


def set_from_page(owner, contact, changes: dict) -> list[str]:
    """What the owner changed beside the tasks on a contact's page, carried out: {task id: "edit",
    "view" or ""}. A sentence for each. One under a ticked column or project is read by the
    tick, so "view" for it takes away a record of its own and leaves the tick's. The page's box
    is read or edit, so a task they decide for that is left at edit there is left as it is."""
    store, root = _store(), _root()
    if store is None or not root or not changes:
        return []
    out = []
    for ident, level in changes.items():
        level = level if level in (NONE, READ, EDIT) else ""
        found = Access(store, root, contact, owner)
        if ident not in found.tree.rows:
            continue
        now = found.level(ident)
        if level == now or (level == EDIT and now == DECIDE):
            continue
        if level == READ and ident in found.ticked:
            if found.why(ident)[1] == TICKED:
                continue
            level = NONE
        try:
            out.append(set_level(owner, contact, ident, level, store=store, root=root))
        except ValueError as exc:
            out.append(str(exc))
    return out


# --- ticks reach Rouh's own pages ----------------------------------------------------------


def _tops(tree, ids) -> set[str]:
    """The tasks among these that are not steps of another."""
    return {i for i in ids if tree.rows.get(i, {}).get("type") == "task"
            and tree.rows.get(tree.owner.get(i, ""), {}).get("type") != "task"
            and tree.rows[i].get("folder")}


def keep_ticks(owner, *, store=None, root: str | None = None) -> tuple[int, int]:
    """Every task under what is ticked on a contact's page shared with them to read, quietly,
    and every share a tick kept that no tick reaches any more taken away. (made, taken away).

    A task that is shared with them already, however, is left as it is: a share a person chose
    is never changed here. Only shares this keeps (`TICK`) are ever taken away here.
    """
    from . import pages, requester_share, taskshare
    from .models import PageGuest

    store = store if store is not None else _store()
    root = _root() if root is None else root
    if store is None or not root or owner is None:
        return 0, 0
    tree = trust.Tree(store)
    want: dict[tuple[str, str], str] = {}
    for contact in trust.TrustStore().all(owner.user_id, owner.org_id):
        found = Access(store, root, contact, owner, tree=tree)
        if not found.ticked:
            continue
        address = requester_share.address_for(contact, {})
        if not address:
            continue
        for ident in _tops(tree, found.ticked):
            folder = tree.rows[ident]["folder"]
            want[(taskshare.PREFIX + folder, address)] = tree.rows[ident].get("title") or ""
    rows = list(PageGuest.objects.filter(user_id=owner.user_id, org_id=owner.org_id,
                                         rel__startswith=taskshare.PREFIX))
    have = {(r.rel, r.email) for r in rows}
    guests = sharing.Guests()
    made = gone = 0
    for (rel, email), title in sorted(want.items()):
        if (rel, email) in have:
            continue
        try:
            rel_ok, shown = sharing.shareable(root, rel)
        except (pages.Refused, OSError):
            continue
        try:
            guests.invite(owner, rel_ok, title or shown, email, READ, via=TICK)
            made += 1
        except ValueError as exc:
            log.warning("task access: %s could not be shared with %s: %s", rel, email, exc)
    for r in rows:
        if r.via == TICK and (r.rel, r.email) not in want:
            gone += int(guests.remove(owner, r.token))
    if made or gone:
        log.info("task access: %d task(s) shared to read by a tick, %d no longer ticked", made,
                 gone)
    return made, gone


def tick_holding(owner, rel: str, email: str) -> str:
    """The name of the contact whose tick keeps this share, and what is ticked, as a sentence for
    the Share panel, or "" when no tick keeps it. A share kept by a tick is taken away by
    unticking it on the contact's page, so it never comes back by itself."""
    from . import taskshare

    if not taskshare.is_task(rel):
        return ""
    store, root = _store(), _root()
    if store is None or not root:
        return ""
    folder = taskshare.folder_of(rel)
    tree = trust.Tree(store)
    ident = next((i for i, r in tree.rows.items()
                  if r.get("type") == "task" and r.get("folder") == folder), "")
    if not ident:
        return ""
    contact, what = _tick_of(owner, rel, email, store=store, root=root, tree=tree, ident=ident)
    if contact is None:
        return ""
    return (f"{contact.name} reads it because {what or 'a project above it'} is ticked on their "
            f"page in Trusted contacts. Untick it there to stop.")


def _tick_of(owner, rel: str, email: str, *, store=None, root=None, tree=None,
             ident: str = "") -> tuple:
    """(the contact whose tick keeps this share, the title of what is ticked), or (None, "")."""
    from . import taskshare

    store = store if store is not None else _store()
    root = _root() if root is None else root
    if store is None or not root or not taskshare.is_task(rel):
        return None, ""
    tree = tree or trust.Tree(store)
    folder = taskshare.folder_of(rel)
    ident = ident or next((i for i, r in tree.rows.items()
                           if r.get("type") == "task" and r.get("folder") == folder), "")
    if not ident:
        return None, ""
    for contact in trust.TrustStore().all(owner.user_id, owner.org_id):
        if email not in _emails(contact):
            continue
        found = Access(store, root, contact, owner, tree=tree)
        if ident not in found.ticked:
            continue
        tick = next((g for g in contact.grants or () if g in tree.rows
                     and ident in tree.under(g)), "")
        return contact, (tree.rows.get(tick) or {}).get("title") or ""
    return None, ""


def taken_away(owner, rel: str, email: str) -> None:
    """A share of a task stopped on its Share panel: when a contact with that address started the
    task, it is not theirs to edit by that any more either, so the level everywhere is what the
    panel now says."""
    from . import requester_share, taskshare

    if not taskshare.is_task(rel):
        return
    store, root = _store(), _root()
    if store is None or not root:
        return
    folder = taskshare.folder_of(rel)
    tree = trust.Tree(store)
    ident = next((i for i, r in tree.rows.items()
                  if r.get("type") == "task" and r.get("folder") == folder), "")
    if not ident:
        return
    meta = trust.task_meta(root, folder)
    for contact in trust.TrustStore().all(owner.user_id, owner.org_id):
        if email in _emails(contact) and trust.started_by(meta, contact) \
                and ident not in _stopped(owner, contact):
            requester_share._write(owner, ident, folder, email, STOPPED)


# --- records that say no more than what they inherit --------------------------------------


def redundant(owner, *, store=None, root: str | None = None, levels=(DECIDE,)) -> list[dict]:
    """Records that say exactly what their person would have without them, inherited from a
    record above (a goal's decide that its quest's decide already gives), for `dedupe`. Only
    records at `levels`, and only ones never emailed, so no link anybody was sent goes. Each
    {"token", "rel", "email", "role", "from", "name"}."""
    from . import taskshare
    from .models import PageGuest

    store = store if store is not None else _store()
    root = _root() if root is None else root
    if store is None or not root or owner is None:
        return []
    tree = trust.Tree(store)
    out = []
    rows = list(PageGuest.objects.filter(user_id=owner.user_id, org_id=owner.org_id,
                                         rel__startswith=taskshare.PREFIX, role__in=list(levels),
                                         mailed_at__isnull=True, pending="")
                .exclude(via=TICK))
    for r in rows:
        contact = trust.TrustStore().trusted_for(str(owner.user_id), str(owner.org_id), r.email)
        found = (Access(store, root, contact, owner, tree=tree) if contact is not None
                 else Access(store, root, None, owner, tree=tree, emails=[r.email]))
        ident = found.by_folder(taskshare.folder_of(r.rel))
        if not ident:
            continue
        # What they would have with this record gone.
        folder = taskshare.folder_of(r.rel)
        found.shares.pop(folder, None)
        found._seen.clear()
        without, came, where = found.why_from(ident)
        if without == sharing.role_of(r.role) and came == INHERITED and where:
            out.append({"token": r.token, "rel": r.rel, "email": r.email, "role": r.role,
                        "from": where, "name": found.number_of(where)})
    return out


def dedupe(owner, *, apply: bool = False, store=None, root: str | None = None) -> list[dict]:
    """Every record of decide that its quest or task above already gives, taken away when
    `apply` - or, under a ticked project, left as the tick's read row it was before - after
    checking again that what they have stays exactly the same. The ones found, each with
    "done" when it was taken away."""
    from .models import PageGuest

    store = store if store is not None else _store()
    root = _root() if root is None else root
    found = redundant(owner, store=store, root=root)
    if not apply:
        return found
    for one in found:
        contact = trust.TrustStore().trusted_for(str(owner.user_id), str(owner.org_id),
                                                 one["email"])
        before = Access(store, root, contact, owner) if contact is not None else None
        ident = before.by_folder(one["rel"][len("_task/"):]) if before is not None else ""
        was = before.level(ident) if before is not None else ""
        ticked = before is not None and ident in before.ticked
        if ticked:
            PageGuest.objects.filter(token=one["token"], user_id=owner.user_id,
                                     org_id=owner.org_id).update(role=READ, via=TICK,
                                                                 granted_by="", pending="")
        else:
            sharing.Guests().remove(owner, one["token"])
        after = Access(store, root, contact, owner) if contact is not None else None
        now = after.level(ident) if after is not None else ""
        one["done"] = now == was
        if now != was:
            # Never a loss: put it back exactly as it was.
            log.error("task access: taking %s from %s changed %s to %s; put back", one["rel"],
                      one["email"], was, now)
            if ticked:
                PageGuest.objects.filter(token=one["token"]).update(role=one["role"], via="")
            else:
                sharing.Guests().invite(owner, one["rel"], "", one["email"], one["role"])
    return found


__all__ = ["Access", "DECIDE", "EDIT", "INHERITED", "NONE", "READ", "SHARED", "STARTED",
           "STOPPED", "TICK", "TICKED", "access_for", "at_least", "dedupe", "for_email",
           "for_judge", "higher", "inherited", "keep_ticks", "kind_of", "level_of_share", "named",
           "page_levels", "page_tree", "people_here", "quest_goals",
           "redundant", "set_from_page", "set_level", "taken_away", "tick_holding"]
