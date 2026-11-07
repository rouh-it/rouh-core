"""A task or a subtask, shared the way a page is.

Petar, 12 October 2026 (fr_80eaca4ddcbf): "Besides sharing an HTML page I
would like to be able to share any task or sub task."

So a task is shared by the very same rows, links and panel a page is
(`rouh/sharing.py`): one `public_pages` row per task per person, its one link
`/p/<token>`, public or not, and the same people invited by email
(`page_guests`, `/shared/<token>`). What tells the two apart is the row's
path: a page's is the page (`.../index.html`), a task's is the task's own
address under the workspace, `_task/<its folder>`, which is what follows
`/workspace/` in the address of a task's own page on the canvas
(`objectindex.TASK_PREFIX`).

What a shared task shows
------------------------

Page sharing settles how far a link reaches: one thing, read only unless the
owner says otherwise, and nothing the reader could climb to from it. A task is
shared on the same terms, and the choices the request left open are made the
simplest way, as it asked:

- **The task and what sits under it, read only.** Its name, number and state;
  the pages it and its subtasks built; its notes (its `.md` files, but never
  its instructions, `AGENTS.md`); and its subtasks, each opening the same view
  one level down. Sharing a task shares its subtasks; sharing a subtask shares
  that subtask and what is under it, and nothing of the task above it.
- **Never its conversations, runs, cards, decisions, files or folders.** Those
  are the owner's working life, held in Rouh's database or beside the pages,
  and a reader has nothing to open them with. The view says so in one line.
- **Read only, unless the owner shared it with a person to change.** A link
  anybody can open is always "Read it" (`sharing.VIEW`), whatever is sent.
  Shared with one person, a task takes the role the owner gave it, as a page
  does. Petar, 13 October 2026, after asking to share task 107 "editable with
  a friend": "Change your instruction that sharing can mean read or edit
  depending on my ask." With `sharing.EDIT`, every page of the task and of its
  subtasks opens for that person in the reader's own page with Ask AI on it,
  able to change the page, exactly as one page shared to change does
  (`rouh/web/guests.py`, `page_at` below). Its notes are read, and ground what
  Ask AI answers; nothing in Rouh changes a note with Ask AI, so neither can
  they. A person given "Read it" sees the task as a link does.
- **Revoked like a page.** Taking it down, or stopping sharing it with a
  person, works exactly as it does for a page, because it is the same row.

A quest shared with a person reaches the goals it names, as the one permission
does (`rouh/task_access.py`): its level lists them, and `?at=~129/...` is a
place inside goal 129, walked the same way from that goal's folder down. A link
anybody can open never reaches past its own folder.

Every address under the link is the link with `?at=` naming a place inside
the shared folder. It is walked from the shared folder down, one step folder
at a time, and ends at the level itself or at one page or one note listed on
that level. Nothing else is ever served, so no `?at=` reaches a folder above
it, a working folder, a source file or another task.
"""
from __future__ import annotations

import html
import logging
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from . import docview, objectindex, pages

log = logging.getLogger("rouh.taskshare")

#: What every shared task's path starts with: its own page's address under
#: the workspace, less `/workspace/`.
PREFIX = objectindex.TASK_PREFIX

#: The longest place inside a shared task that is looked at.
AT_MAX = 600


def is_task(rel) -> bool:
    """Whether a share's path is a task's rather than a page's."""
    return str(rel or "").startswith(PREFIX)


def _parts(path: str) -> list[str] | None:
    """A path's parts, or None when one of them could go somewhere else."""
    parts = [p for p in str(path or "").replace("\\", "/").split("/") if p]
    if any(p in (".", "..") or p.startswith(".") or "\x00" in p for p in parts):
        return None
    return parts


def folder_of(rel) -> str:
    """The task's folder a share names, or "" when it names none."""
    if not is_task(rel):
        return ""
    parts = _parts(str(rel)[len(PREFIX):])
    return "/".join(parts) if parts else ""


def _is_dir(root, folder: str) -> bool:
    base = Path(str(root or ""))
    path = base / folder
    try:
        return (bool(root) and bool(folder) and not path.is_symlink() and path.is_dir()
                and base.resolve() in path.resolve().parents)
    except OSError:
        return False


def _number(here: dict) -> str:
    return (str(here["number"]) if here.get("number") is not None
            else objectindex._step_number(here))


def _here(root, folder: str):
    """The task or subtask filed at this folder, and the tree it was read from."""
    store = objectindex._ready(root)
    tree = objectindex._Tree(store)
    here = objectindex._object_at(tree, root, folder)
    return store, tree, here


def shareable(root, rel: str) -> tuple[str, str]:
    """The task `rel` names and what it is called, or `pages.Refused` saying why not.

    A task or a subtask, and not a project: a project is a column of the
    person's whole working life rather than one piece of work to hand somebody.
    """
    folder = folder_of(rel)
    if not folder or not _is_dir(root, folder):
        raise pages.Refused("There is no task there to share.")
    store, tree, here = _here(root, folder)
    if here is None:
        raise pages.Refused("There is no task there to share.")
    if str(here.get("type") or "task") == "project":
        raise pages.Refused("A task or a subtask can be shared, and a project cannot.")
    called = objectindex._called(tree, here)
    shown = _number(here)
    name = here.get("title") or here.get("slug") or folder.rsplit("/", 1)[-1]
    return PREFIX + folder, (f"{called} {shown}: {name}" if shown else name)[:200]


# --- a task whose folder moved -------------------------------------------------------------
#
# A task's folder is renamed and renumbered and moved between projects, and its
# link must not stop working when it is: the row keeps naming where the task
# was. The number is what does not change (`objectindex.moved_to`), so a
# folder that is gone is looked for under it, and every row naming the old
# place is pointed at the new one, keeping its token, its people and its role.

def _repoint(old: str, new: str) -> None:
    from django.db import transaction

    from .models import PageGuest, PublicPage

    with transaction.atomic():
        for row in PublicPage.objects.select_for_update().filter(rel=old):
            if not PublicPage.objects.filter(user_id=row.user_id, rel=new).exists():
                PublicPage.objects.filter(token=row.token).update(rel=new)
        for row in PageGuest.objects.select_for_update().filter(rel=old):
            if not PageGuest.objects.filter(user_id=row.user_id, rel=new,
                                            email=row.email).exists():
                PageGuest.objects.filter(token=row.token).update(rel=new)
    log.info("a shared task moved from %s to %s, and its links went with it", old, new)


def reading(rel: str, root) -> str:
    """Where the task a share names is now: the same path, or its new one."""
    folder = folder_of(rel)
    if not folder or _is_dir(root, folder):
        return rel
    try:
        now = objectindex.moved_to(folder)
    except Exception:  # noqa: BLE001 - the answer is still "not there any more"
        log.exception("could not tell where the shared task %s went", folder)
        return rel
    if not now or not _is_dir(root, now):
        return rel
    new = PREFIX + now
    try:
        _repoint(rel, new)
    except Exception:  # noqa: BLE001 - served from where it is either way
        log.exception("could not move the shares of %s over to %s", rel, new)
    return new


def follow(root) -> None:
    """Every shared task that has moved, followed. Cheap: a look at each folder."""
    from .models import PageGuest, PublicPage

    try:
        rels = (set(PublicPage.objects.filter(rel__startswith=PREFIX)
                    .values_list("rel", flat=True))
                | set(PageGuest.objects.filter(rel__startswith=PREFIX)
                      .values_list("rel", flat=True)))
        for rel in sorted(rels):
            reading(rel, root)
    except Exception:  # noqa: BLE001 - a task that cannot be followed is only a 404
        log.exception("following moved tasks stumbled")


# --- what the reader sees ----------------------------------------------------------------


#: What starts a place inside one of a shared quest's goals: "~129/129-02.x".
GOAL_MARK = "~"


class _Base(str):
    """A share's own address, with the goal of its quest a place is inside, when it is one:
    every link on the view is made under both (`_link`)."""

    goal = ""
    person = False


def _under(base: str, goal: str) -> "_Base":
    out = _Base(base)
    out.goal = goal
    return out


def _link(base: str, inside: str) -> str:
    """The address of one place inside the shared task, under the share's own link."""
    goal = getattr(base, "goal", "")
    if goal:
        inside = GOAL_MARK + goal + ("/" + inside if inside else "")
    return str(base) + ("?at=" + quote(inside, safe="/~") if inside else "")


def linked_goals(root, top: str) -> dict[str, dict]:
    """The goals a shared quest names (`task_access.quest_goals`), by number: {"folder",
    "title"}. Nothing for a task that is not a quest."""
    from . import task_access, trusted
    from .models import Task

    ids = task_access.quest_goals(trusted.task_meta(root, top))
    if not ids:
        return {}
    return {str(t.number): {"folder": t.folder, "title": t.title or t.folder}
            for t in Task.objects.filter(id__in=ids).exclude(folder="")
            if t.number is not None}


def _inside(top: str, rel: str) -> str | None:
    """`rel` as a place inside the shared folder, or None when it is not inside it."""
    if rel == top:
        return ""
    return rel[len(top) + 1:] if rel.startswith(top + "/") else None


def _notes(held: dict, page: str) -> list[str]:
    """A level's notes a reader may open: its `.md`, less its instructions."""
    return [n for n in held["md"] if not objectindex.instructions_file(n) and n != page]


def _subtask_lines(root, subs: list[dict], top: str, base: str) -> list[dict]:
    """A level's live subtasks, every link pointed into the share.

    Only those whose folder is inside the shared one: a subtask whose row
    names a folder somewhere else is the owner's to show, not this link's.
    What each holds is counted in what a reader can open, never in chats.
    """
    out = []
    for one in subs:
        inside = _inside(top, one.get("folder") or "")
        if not inside or one.get("archived"):
            continue
        held = objectindex._contents(root, one["folder"])
        page = objectindex._page_of(held)
        counts = {"subtask": len(held["subtasks"]), "page": len(held["pages"]),
                  "md": len(_notes(held, page))}
        if page.lower() == docview.STEP_FILE:
            counts["page"] = 1
        out.append({**one, "href": _link(base, inside),
                    "page": _link(base, f"{inside}/{page}") if page else "",
                    "holds": objectindex._holds_words(counts),
                    "kids": _subtask_lines(root, one.get("kids") or [], top, base)})
    return out


def _shell(body: str, title: str, owner: str, back: str = "", can_edit: bool = False,
           home: str = "") -> bytes:
    """The page around a level or a note: the task page's own look, who shared
    it, and what the reader may do with it. `home`, for a person signed in, is
    their list of everything shared with them, which the line links back to."""
    said = (f'<p class="shared-by">Shared by {html.escape(owner or "somebody")} &middot; '
            + ("you can change its pages with Ask AI" if can_edit else "read only")
            + (f' &middot; <a href="{html.escape(home, quote=True)}">Everything shared with '
               'you</a>' if home else "") + "</p>")
    style = ("<style>.shared-by{margin:0 0 14px;font-size:12.5px;color:var(--mut,#8a93a3)}"
             "body{min-height:100vh}</style>")
    return objectindex._shell(said + (back or "") + body + style, title, None)


def _back(root, base: str, top: str, level: str, tree) -> str:
    """The way up one level, while there is a level above inside the share: from a quest's
    goal, back to the quest."""
    if level == top:
        if not getattr(base, "goal", ""):
            return ""
        return (f'<p class="oback"><a href="{html.escape(str(base), quote=True)}">'
                '<span aria-hidden="true">←</span> The quest</a></p>')
    over_rel = level.rsplit("/", 1)[0]
    over = objectindex._object_at(tree, root, over_rel)
    words = over_rel.rsplit("/", 1)[-1]
    if over is not None:
        shown = _number(over)
        words = (f"{objectindex._called(tree, over)} {shown}".strip() + " · "
                 + (over.get("title") or over.get("slug") or words))
    href = _link(base, _inside(top, over_rel) or "")
    return (f'<p class="oback"><a href="{html.escape(href, quote=True)}">'
            f'<span aria-hidden="true">←</span> {html.escape(words)}</a></p>')


def _level(root, top: str, level: str, base: str, owner: str,
           can_edit: bool = False, home: str = "") -> bytes:
    """One level of the shared task: its pages, its notes and its subtasks."""
    store, tree, here = _here(root, level)
    if here is None or str(here.get("type") or "task") == "project":
        raise pages.Missing("There is no task there.")
    under = objectindex._Under(store)
    now = datetime.now()
    called = objectindex._called(tree, here)
    shown = _number(here)
    number = f'<span class="num">{html.escape(shown)}</span>' if shown else ""
    state = str(here.get("status") or "")
    status = (f'<span class="task-status" data-status="{html.escape(state)}">'
              f'{html.escape(objectindex.STATE_WORDS.get(state, state))}</span>'
              if state and state != "open" else "")
    _own, _others, when = objectindex._facts(root, level)
    held = objectindex._contents(root, level)
    page = objectindex._page_of(held)

    # Its own pages, as its own page lists them, each opened through the share.
    built = []
    if held["pages"]:
        step = shown if called == "Subtask" else ""
        built = objectindex.built_pages(root, [(level, step, level)],
                                        {level: here["title"]} if here.get("title") else None)
        for one in built:
            one["step"] = one["step"] or shown
    elif page:
        built = [{"rel": f"{level}/{page}", "step": shown, "about": "",
                  "title": here.get("title") or page}]
    for one in built:
        one["href"] = _link(base, _inside(top, one["rel"]) or "")
    notes = _notes(held, page if page.lower() == docview.STEP_FILE else "")
    subs = _subtask_lines(root, objectindex._subtasks(root, tree, under, here, level),
                          top, base)
    # A quest shared with a person: the goals it names, each opened through the same share.
    goals = []
    if level == top and getattr(base, "person", False) and not getattr(base, "goal", ""):
        for number, one in sorted(linked_goals(root, top).items(),
                                  key=lambda kv: int(kv[0]) if kv[0].isdigit() else 0):
            goals.append({"folder": one["folder"], "title": one["title"], "number": number,
                          "href": str(base) + "?at=" + quote(GOAL_MARK + number, safe="/~"),
                          "page": "", "holds": "", "kids": []})

    body = []
    if built:
        body.append(objectindex._section(
            "Page" if len(built) == 1 else "Pages", len(built), objectindex._page_rows(built),
            cls="opages one" if len(built) == 1 else "opages", cut=False))
    if subs:
        body.append(objectindex._section(
            "Subtasks", len(subs), "".join(objectindex._subtask_row(s) for s in subs),
            cls="osubs", cut=False))
    if goals:
        body.append(objectindex._section(
            "Its goals", len(goals), "".join(objectindex._subtask_row(s) for s in goals),
            cls="osubs", cut=False))
    if notes:
        base_dir = Path(str(root)) / level
        body.append(objectindex._section(
            "Notes", len(notes),
            "".join(objectindex._object_row(
                "md", _link(base, _inside(top, f"{level}/{n}") or ""), n,
                objectindex.stamp(objectindex._changed(base_dir / n), now),
                objectindex._kind_pill(".md")) for n in notes),
            cls="oown", cut=False))
    head = (f'<header class="ohead"><div class="otitle">'
            f'<h1 class="oname-big">{number}'
            f'<span>{html.escape(here.get("title") or here.get("slug") or level)}</span>'
            f'{status}</h1>{objectindex._changed_on(when, now)}</div></header>')
    rest = ('<p class="osaid">Its chats, runs and files are not shared: only its pages, '
            'its notes and its subtasks are.</p>')
    title = here.get("title") or here.get("slug") or level.rsplit("/", 1)[-1]
    return _shell(head + ("".join(body) or '<p class="none">Nothing in this yet.</p>') + rest,
                  title, owner, _back(root, base, top, level, tree), can_edit, home)


def _note(root, top: str, level: str, name: str, base: str, owner: str,
          can_edit: bool = False, home: str = "") -> bytes:
    """One note of one level, read."""
    path = Path(str(root)) / level / name
    text = objectindex._read_head(path, objectindex.DOC_LONGEST)
    if name.lower() == docview.STEP_FILE:
        drawn, title = docview.step_html(text)
    else:
        drawn, title = docview.markdown_html(text), name
    title = title or name
    drawn = drawn or "<p class=dnote>This file is empty.</p>"
    _store, tree, here = _here(root, level)
    words = level.rsplit("/", 1)[-1]
    if here is not None:
        shown = _number(here)
        words = (f"{objectindex._called(tree, here)} {shown}".strip() + " · "
                 + (here.get("title") or here.get("slug") or words))
    back = (f'<p class="oback"><a href="{html.escape(_link(base, _inside(top, level) or ""), quote=True)}">'
            f'<span aria-hidden="true">←</span> {html.escape(words)}</a></p>')
    head = (f'<header class="ohead"><h1 class="oname-big"><span>{html.escape(title)}</span>'
            f'{objectindex._kind_pill(".md", "md")}</h1></header>')
    return _shell(head + f'<article class="odoc">{drawn}</article>', title, owner, back,
                  can_edit, home)


def goal_of(at: str) -> tuple[str, str]:
    """(the goal number a place names with `GOAL_MARK`, the rest of it), or ("", at)."""
    at = str(at or "")
    if not at.startswith(GOAL_MARK):
        return "", at
    number, _, rest = at[len(GOAL_MARK):].partition("/")
    return number, rest


def _place(root, rel: str, at: str, *, person: bool = False) -> tuple[str, str, str]:
    """The shared folder, the level `at` is on, and what is left of `at` past it. For a
    `person` a quest was shared with, `at` may start inside one of its goals ("~129/..."),
    and the shared folder is then that goal's.

    `pages.Refused` or `pages.Missing` when `at` is not a place in this task.
    """
    top = folder_of(rel)
    goal, at = goal_of(str(at or "")[:AT_MAX])
    if goal:
        found = linked_goals(root, top).get(goal) if person and top else None
        if found is None:
            raise pages.Refused("That is not a place in this task.")
        top = found["folder"]
    parts = _parts(str(at or "")[:AT_MAX])
    if not top or parts is None:
        raise pages.Refused("That is not a place in this task.")
    if not _is_dir(root, top):
        raise pages.Missing("This task is not there any more.")
    level, rest = objectindex.subtask_within(root, top, "/".join(parts))
    if "/" in rest:
        raise pages.Missing("That is not a place in this task.")
    return top, level, rest


def page_at(root, rel: str, at: str, *, person: bool = False) -> str | None:
    """The page of the shared task `at` names, as its path in the workspace, or None.

    The very walk `view` takes, ending only at one of the pages a level lists:
    what a person a task was shared with to change may open in the reader's
    page with Ask AI, and nothing else (`rouh/web/guests.py`).
    """
    try:
        _top, level, rest = _place(root, rel, at, person=person)
    except (pages.Refused, pages.Missing, OSError):
        return None
    if not rest or rest not in objectindex._contents(root, level)["pages"]:
        return None
    return f"{level}/{rest}"


def view(root, rel: str, at: str, base: str, owner: str = "",
         can_edit: bool = False, home: str = "", person: bool = False) -> tuple[bytes, str]:
    """What the share's link shows at `at`: a level, one of its pages, or one of its notes.

    `pages.Missing` or `pages.Refused` for anything else, which the caller
    answers as not found. `base` is the share's own address, `/p/<token>` or
    `/shared/<token>`, which every link on the view is under. `can_edit` is
    only what the view says the reader may do: a page they may change is
    opened in the reader's page (`page_at`), never served from here. `home` is
    the signed-in reader's list of what is shared with them, linked from every
    level (`_shell`); a link anybody can open has none. `person` is one person it
    was shared with, whom a quest's goals are reached for too.
    """
    top, level, rest = _place(root, rel, at, person=person)
    base = _under(base, goal_of(at)[0])
    base.person = person
    if not rest:
        return _level(root, top, level, base, owner, can_edit, home), pages.TYPES[".html"]
    held = objectindex._contents(root, level)
    if rest in held["pages"]:
        # A page, served exactly as a shared page is (`views.public_page`).
        return pages.read(root, f"{level}/{rest}", f"{level}/{rest}")
    if rest in held["md"] and not objectindex.instructions_file(rest):
        return (_note(root, top, level, rest, base, owner, can_edit, home),
                pages.TYPES[".html"])
    raise pages.Missing("That is not a place in this task.")
