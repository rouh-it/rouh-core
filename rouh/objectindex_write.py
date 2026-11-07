"""What the task browser and a project's page write back: `change`, and a
file arriving on a project or a task (`attach_to_project`, `attach_to_task`),
and the list of a task's files told to its chats (`files_block`).

`objectindex` imports this module at its bottom and re-exports every name in
it, so callers keep reaching each one as `objectindex.<name>`.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

from . import keeping, objects, objecttree, task_origin, uploads


# --------------------------------------------------------------------------
# What the page writes back
# --------------------------------------------------------------------------
#
# Eight actions and no others, each named rather than addressed: the page hands
# up an action and ids, never a path and never SQL. A task's category is the
# project that owns it, so filing one is `objecttree.move`, which writes the
# `owns` link and then moves the folder with `git mv` - and puts the link back
# if the folder will not move, so the row and the disk can never disagree.
#
# Two of the eight are a project's own page rather than the browser, and they
# keep the same rule: `instructions` names a project and the words to write,
# and the folder its AGENTS.md goes in is read off the row here; `drop_file`
# names a project and one file in it, and the directory is written here out of
# the id. A file arriving is the one thing that cannot come this way, because
# it is bytes and not JSON: that is `POST /api/workspace/file`.


#: The longest name a project may be given here.
NAME_MAX = 60

#: And the longest description. A description is a sentence or two saying what
#: belongs in a project, for the person reading the list and for the model that
#: files a new task into one (`rouh/filing.py`). Long enough for a paragraph,
#: short enough that the field is never mistaken for the project's notes: those
#: are its AGENTS.md, which is a file and not a column.
DESCRIPTION_MAX = 1000


def _named(body: dict, key: str) -> str:
    return " ".join(str(body.get(key) or "").split())[:NAME_MAX]


def _described(body: dict) -> str:
    """The description out of one change, tidied of nothing but its edges.

    The line breaks are the person's and are kept: a description is often a
    list of what belongs in the project, and flattening it to one line would
    take that away from them and from the model that reads it back.
    """
    said = str(body.get("description") or "").replace("\r\n", "\n").replace("\r", "\n")
    return said.strip()[:DESCRIPTION_MAX]


def _describe(store: objects.ObjectStore, ident: str, said: str) -> dict:
    """Say what belongs in a project. An empty description is a real answer."""
    row = store.get_project(ident) if ident else None
    if row is None:
        return {"ok": False, "why": "There is no project here with that id."}
    store.update_project(ident, description=said, updated_at=time.time())
    return {"ok": True, "did": f"what belongs in {row.title} is written down"}


def _coloured(body: dict) -> str | None:
    """The colour out of one change: a name from `PALETTE`, `#rrggbb` in
    lower case, or empty for the one its place gives it. None is neither."""
    said = str(body.get("color") or "").strip().lower()
    if len(said) == 4 and said.startswith("#"):
        said = "#" + "".join(ch * 2 for ch in said[1:])
    return said if not said or said in PALETTE or _HEX.fullmatch(said) else None


def _colour(store: objects.ObjectStore, ident: str, said: str | None) -> dict:
    """Give a project a colour, or give it back the one its place gives it."""
    row = store.get_project(ident) if ident else None
    if row is None:
        return {"ok": False, "why": "There is no project here with that id."}
    if said is None:
        return {"ok": False, "why": "That is not a colour. Type one like #3a7bd5."}
    store.update_project(ident, color=said, updated_at=time.time())
    return {"ok": True}


def change(root, body: dict, names=(), person=None) -> dict:
    """One change from one of the two pages, and what it is afterwards.

    Always with the state the page draws from, refusal or not, because a page
    draws what the server says is on disk rather than what it hoped it had
    done. A refusal is a sentence, not a status: the page puts it in front of
    the person.

    Which state depends on which page asked. The task browser gets the whole
    index, because a move changes two columns at once. A project's own page
    names itself in ``rel`` and gets that project - its name, what it is for,
    its instructions and its files - and **not** the index: it does not draw
    the index, and walking every object in the workspace to answer a rename on
    one project is a walk for nothing.
    """
    from . import owning

    store = _ready(root)
    action = str(body.get("action") or "")
    ident = str(body.get("id") or "")
    if action == "icon":
        return icon_change(store, body)
    try:
        if action == "move":
            done = owning.move(str(body.get("task") or ""), str(body.get("owner") or ""))
            if done.get("ok"):
                # A drag is the person saying where it goes, Miscellaneous
                # included, so the filing model never moves it after them.
                from . import filing

                filing.placed_by_person(str(body.get("task") or ""))
        elif action == "rename":
            name = _named(body, "name")
            done = ({"ok": False, "why": "A project needs a name."} if not name
                    else owning.rename("project", ident, name))
        elif action == "rename_task":
            # A task renamed from Rename in the three dots at the end of its
            # line in the task browser: its title, and its `.object.json` with
            # it; the folder keeps its name (`owning.rename`).
            done = owning.rename("task", str(body.get("task") or ""), str(body.get("name") or ""))
        elif action == "save_view":
            # Save view, beside the search box: what the browser opens on from
            # now on, for this person (`saved_view`).
            done = (save_view(person, body.get("view")) if person is not None
                    else {"ok": False, "why": "Rouh could not tell who you are. Reload and try again."})
        elif action == "side":
            done = owning.move(ident, str(body.get("side") or ""))
        elif action == "add":
            name = _named(body, "name")
            done = ({"ok": False, "why": "A project needs a name."} if not name
                    else owning.make("project", name, str(body.get("side") or "")))
            # What belongs in it is written on the project that was just made,
            # rather than being a second thing the person has to do to it. The
            # project is the answer either way: a description that could not be
            # written is not a project that was not added.
            said = _described(body)
            if done.get("ok") and said:
                _describe(store, str((done.get("made") or {}).get("id") or ""), said)
        elif action == "describe":
            done = _describe(store, ident, _described(body))
        elif action == "color":
            done = _colour(store, ident, _coloured(body))
        elif action == "instructions":
            # What the project is for, in the project's own AGENTS.md. The id
            # is asked for rather than the folder, so this route is still one
            # where the page names an object and never a path.
            row = store.get_project(ident) if ident else None
            done = ({"ok": False, "why": "There is no project here with that id."}
                    if row is None
                    else write_instructions(root, row.folder,
                                            str(body.get("instructions") or "")))
        elif action == "archive":
            # A task or a subtask archived, or brought back with `on` false
            # (`rouh/archiving.py`). The task browser names it by id; a task's
            # own page by the folder Rouh framed (`taskPageAct` in app.js).
            from . import archiving

            task = str(body.get("task") or "")
            if not task and body.get("folder"):
                task = owning.task_at(str(body.get("folder") or ""))
            done = archiving.archive(task, body.get("on") is not False)
        elif action == "pin":
            # Pinned, or unpinned with `on` false: what the Control Room shows
            # (`rouh/pinning.py`). The task browser names a task or a step by
            # id; a task's own page by the folder Rouh framed.
            from . import pinning

            task = str(body.get("task") or "")
            if not task and body.get("folder"):
                task = owning.task_at(str(body.get("folder") or ""))
            done = pinning.pin(task, body.get("on") is not False)
        elif action == "show_others":
            # "Others' tasks" switched on or off: kept for the person, so the
            # browser, the Control Room and every device show the same
            # (`rouh/task_origin.py`).
            if person is None:
                done = {"ok": False, "why": "Rouh could not tell who you are. Reload and try again."}
            else:
                on = task_origin.show(person.user_id, person.org_id, body.get("on") is not False)
                done = {"ok": True, "did": "Showing others' tasks" if on else
                        "Others' tasks are hidden"}
        elif action == "mine":
            # The person saying whose a task is, from the three dots on its own
            # page: `to` "person", "other" or "process" (`on` true or false, before
            # Made by Rouh, said the first two).
            task = str(body.get("task") or "")
            if not task and body.get("folder"):
                task = owning.task_at(str(body.get("folder") or ""))
            to = str(body.get("to") or "") or ("person" if body.get("on") is not False else "other")
            done = task_origin.set_by_person(task, to, root=root)
        elif action == "relocate":
            # Move, from the three dots on a task's or a subtask's own page:
            # the folder Rouh framed, to a project or a task picked in Rouh's
            # picker, renumbered to fit where it lands (`rouh/moving.py`).
            from . import moving

            done = moving.move(str(body.get("folder") or ""), str(body.get("where") or ""),
                               str(body.get("name") or ""))
        elif action == "move_step":
            # A subtask dragged onto another task in the task browser, or moved
            # out of its task from the three dots on its line: `where` is the
            # task's id, `+task` (Promote to task) or `+new` (Move to new task,
            # `rouh/moving.py`). Named by its id; the folder is its row's.
            from . import moving

            row = store.get_task(str(body.get("task") or ""))
            done = (moving.move(row.folder, str(body.get("where") or ""),
                                str(body.get("name") or ""))
                    if row is not None and row.folder
                    else {"ok": False, "why": "That subtask is not in the workspace any more."})
            if done.get("ok") and done.get("did"):
                done["did"] = ""
        elif action == "drop_file":
            done = _drop_file(store, ident, str(body.get("file") or ""))
        elif action == "drop_task_file":
            # A file taken off a task from the cross on its line on the task's
            # own page, named by the folder Rouh framed and the file's id.
            task = owning.task_at(str(body.get("folder") or ""))
            done = _drop_task_file(store, task, str(body.get("file") or ""))
            if done.get("ok"):
                return {"ok": True, "did": done["did"], "files": task_files(task)}
            return {"ok": False, "error": done.get("why") or "That file was not taken off."}
        elif action == "retitle_page":
            # Rename, from the three dots on a page on a task's own page: the page's own name,
            # named by the folder Rouh framed and the page's place in it (`pagehistory.retitle`).
            return _retitle_page(root, person, str(body.get("folder") or ""),
                                 str(body.get("item") or ""), str(body.get("title") or ""))
        elif action in ("slack_unlink", "slack_remove"):
            # Unlink a Slack channel, or take a decision written from it out of the notes, from
            # the task's own page, named by the folder Rouh framed (`rouh/slack_tasks.py`).
            from . import slack_tasks

            done = slack_tasks.from_page(person, str(body.get("folder") or ""), action[6:],
                                         body.get("slack"))
            if done.get("ok"):
                return {"ok": True, "did": done["did"], "slack": done["slack"]}
            return {"ok": False, "error": done.get("why") or "That could not be changed.",
                    "slack": done.get("slack")}
        elif action == "delete":
            done = _delete_project(root, store, ident)
        else:
            done = {"ok": False, "why": f"The task browser cannot do {action or 'that'}."}
    except Exception:                                    # pragma: no cover - reported
        log.exception("the task browser could not %s", action or "act")
        done = {"ok": False, "why": "That could not be written down."}
    answer = {"ok": bool(done.get("ok"))}
    if action == "relocate":
        # Asked from a task's page, which draws neither the index nor a
        # project: where it is now, and what was done, in words.
        if answer["ok"]:
            answer.update(rel=str(done.get("rel") or ""), did=str(done.get("did") or ""))
            if done.get("task"):
                # Moved to a new task: the new task's folder, whose page is shown.
                answer["task"] = str(done["task"])
        else:
            answer["error"] = done.get("why") or "It was not moved."
        return answer
    # A project's own page names itself and gets itself back; the task browser
    # names nothing and gets the index.
    rel = "/".join(part for part in str(body.get("rel") or "").split("/") if part)
    said = project_data(store, root, rel, True) if rel else None
    if said is not None:
        answer["project"] = said
    else:
        answer["index"] = index_data(store, root, names, person)
    if not answer["ok"]:
        answer["error"] = done.get("why") or "The change was not saved."
    elif done.get("did"):
        # What was really done, when it is more than the page asked for and
        # only this side knows it: deleting a project gives its kept notes
        # back to the general memory rather than deleting them, and the toast
        # says so (`deleteCat` in taskbrowser.js).
        answer["did"] = str(done["did"])
    return answer


def icon_change(store: objects.ObjectStore, body: dict) -> dict:
    """A task's or a step's icon, picked from the icon picker (`taskicon.js`): an emoji, named
    by the task's id. Answers with the icon as the pages draw it, and not the index: the page
    that asked puts it in place itself (`rouh/taskicons.py`)."""
    from . import taskicons

    task = str(body.get("task") or "")
    try:
        done = taskicons.set_emoji(task, str(body.get("icon") or ""))
    except Exception:                                    # pragma: no cover - reported
        log.exception("a task's icon could not be changed")
        done = {"ok": False, "why": "That could not be written down."}
    if not done.get("ok"):
        return {"ok": False, "error": done.get("why") or "The icon was not changed."}
    row = store.get_task(task)
    return {"ok": True, "shown": taskicons.shown(row.icon if row else "", row.title if row else "")}


def icon_upload(task: str, data: bytes) -> dict:
    """A picture uploaded as a task's icon (`taskicons.save_picture`), and the icon as the pages
    draw it."""
    from . import taskicons

    done = taskicons.save_picture(task, data)
    if not done.get("ok"):
        return {"ok": False, "error": done.get("why") or "The picture was not kept."}
    return {"ok": True, "shown": taskicons.shown(done["icon"], "")}


#: The person's setting holding the view the task browser opens on.
SAVED_VIEW = "tasks_view"

#: The longest view kept: Rouh keeps no longer a one for the tab (`TASKS_VIEW` in app.js).
VIEW_MAX = 2000


def saved_view(person) -> str:
    """The view the task browser opens on for this person, as the page writes its views
    (`viewOf` in taskbrowser.js), or "" when they have saved none.

    Petar, 22 October 2026 (fr_d2222b1e45af): "I would love to have a button called "save
    view" that saves the default settings for next time I come here." So a view is the
    labels whose eye is crossed and the filters pressed, kept for him rather than for one
    browser, and every device opens on it."""
    from .models import UserSetting

    if person is None or not getattr(person, "user_id", None):
        return ""
    value = (UserSetting.objects.filter(user_id=str(person.user_id),
                                        org_id=str(person.org_id or ""), name=SAVED_VIEW)
             .values_list("value", flat=True).first())
    try:
        said = json.loads(value) if value else ""
    except (TypeError, ValueError):
        return ""
    return said if isinstance(said, str) and len(said) <= VIEW_MAX else ""


def save_view(person, view) -> dict:
    """Keep `view` as the one the task browser opens on for this person."""
    from .models import UserSetting

    if not isinstance(view, str) or not view or len(view) > VIEW_MAX or "\n" in view:
        return {"ok": False, "why": "That is not a view the task browser can open on."}
    UserSetting.objects.bulk_create(
        [UserSetting(user_id=str(person.user_id), org_id=str(person.org_id or ""), name=SAVED_VIEW,
                     value=json.dumps(view), updated_at=time.time())],
        update_conflicts=True, unique_fields=["user_id", "name"],
        update_fields=["org_id", "value", "updated_at"])
    return {"ok": True, "did": "Saved: the task browser opens on this view from now on"}


def attach_to_project(root, ident: str, filename: str, data: bytes,
                      content_type: str = "") -> dict:
    """One file onto one project, and the project as it stands afterwards.

    The whole of the Add files button's server side. The caller has the bytes
    and the ceiling already (`server.workspace_file`); what is decided here is
    that the id really is a project's, and where under the attachment store its
    files live. What may be attached at all is `attachments.save`'s answer and
    nothing is added to it.
    """
    from . import attachments

    store = _ready(root)
    row = store.get_project(str(ident or ""))
    if row is None:
        return {"ok": False, "error": "There is no project with that id."}
    try:
        record = _held().save(files_key(row.id), filename, data, content_type=content_type)
    except attachments.AttachmentError as exc:
        return {"ok": False, "error": str(exc)}
    except OSError as exc:
        log.exception("a project file could not be written")
        return {"ok": False, "error": f"It could not be saved here: {exc}"}
    log.info("attached %s (%s) to the project %s", record["name"],
             attachments.human_size(record["size"]), row.title)
    # Given, the moment it is added: its words are read and it is searchable
    # from then on, found under its own name (`rouh/uploads.py`).
    uploads.take_in([record], ("project", row.id))
    return {"ok": True, "project": project_data(store, root, row.folder, True)}


def attach_to_task(root, folder: str, filename: str, data: bytes,
                   content_type: str = "") -> dict:
    """One file onto one task or subtask, and the task's files afterwards.

    The server side of Upload on a task's own page. Which task is the folder
    Rouh framed, read off its own canvas and never off anything the page said
    (`taskUpload` in app.js), and where its files live is worked out here from
    the task's id (`task_files_key`). What may be uploaded and how big it may
    be are `attachments.save`'s answer, as they are for a project and a chat.
    """
    from . import attachments, owning

    _ready(root)
    task = owning.task_at(folder)
    if not task:
        return {"ok": False, "error": "There is no task here to upload to."}
    try:
        record = _held().save(task_files_key(task), filename, data, content_type=content_type)
    except attachments.AttachmentError as exc:
        return {"ok": False, "error": str(exc)}
    except OSError as exc:
        log.exception("a task's file could not be written")
        return {"ok": False, "error": f"It could not be saved here: {exc}"}
    log.info("uploaded %s (%s) to the task at %s", record["name"],
             attachments.human_size(record["size"]), folder)
    # Searchable from now on, under its own name and its words, as every file
    # the person gives Rouh is (`rouh/uploads.py`).
    uploads.take_in([record], ("task", task))
    return {"ok": True, "file": {"id": record["id"], "name": record["name"]},
            "files": task_files(task)}


#: How many of a task's uploaded files a turn in its chat is told about by name.
FILES_TOLD = 40


def files_block(chat_id: str) -> str:
    """For the part of the system prompt that changes every turn, or "".

    In a chat of a task, or of a subtask, the files uploaded to it from its
    page (and to the task above a subtask), by name, with where each is on
    disk and where its words are, read out as Markdown when it was uploaded
    (`rouh/uploads.py`). The files are not put into the turn whole, which on
    every turn would be paid for every turn; a job handed the path reads the
    file itself, and the words are there to read with a command.
    """
    if not chat_id:
        return ""
    try:
        return _files_block(chat_id)
    except Exception:  # noqa: BLE001 - a line of context is never worth a turn
        log.exception("the files of the task of %s could not be read", chat_id)
        return ""


def _files_block(chat_id: str) -> str:
    from . import attachments, conversations, subtasknotes

    task = conversations.task_of(chat_id)
    if task is None:
        return ""
    held = [(task, _held().listing(task_files_key(task.id)))]
    parent = subtasknotes.parent_of(task.id)
    if parent is not None:
        held.append((parent, _held().listing(task_files_key(parent.id))))
    parts = []
    for whose, records in held:
        if not records:
            continue
        lines = []
        for record in records[-FILES_TOLD:]:
            words = os.path.join(os.path.dirname(record["path"]), attachments.WORDS)
            lines.append(f"- {record['name']} ({attachments.human_size(record['size'])}),"
                         f" at {record['path']}"
                         + (f"; its words as Markdown at {words}" if os.path.isfile(words) else ""))
        more = len(records) - len(lines)
        which = ("this task" if whose is task
                 else f"the parent task {subtasknotes.label(whose)}")
        parts.append(f"Files the person uploaded to {which} from its page, oldest first"
                     + (f" (the newest {len(lines)} of {len(records)})" if more > 0 else "")
                     + ":\n" + "\n".join(lines))
    if not parts:
        return ""
    return ("\n\n".join(parts) + "\n\nThey are the task's own and are not in this "
            "conversation. When the person refers to one, read it: hand its path to a job "
            "that needs it, or read its words with a command.")


def _retitle_page(root, person, folder: str, item: str, title: str) -> dict:
    """A page of a task given another name (`pagehistory.retitle`): only a page in the folder
    Rouh framed, and never anything that climbs out of it."""
    from . import pagehistory

    parts = [p for p in folder.split("/") if p] + [p for p in item.split("/") if p]
    if (person is None or not folder or not item or any(p in (".", "..") for p in parts)
            or not item.lower().endswith(".html")):
        return {"ok": False, "error": "That page cannot be renamed from here."}
    try:
        done = pagehistory.retitle(root, person, "/".join(parts), title)
    except pagehistory.Refused as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "title": done["title"]}


def _drop_task_file(store: objects.ObjectStore, task: str, att_id: str) -> dict:
    """Take one uploaded file off a task, by the task's id and the file's."""
    row = store.get_task(task) if task else None
    if row is None:
        return {"ok": False, "why": "There is no task here."}
    gone = _held().drop(task_files_key(task), att_id)
    if gone is None:
        return {"ok": False, "why": "That file is not on this task."}
    uploads.forget(task_files_key(task), att_id)
    log.info("took %s off the task %s", gone["name"], row.title)
    return {"ok": True, "did": f"{gone['name']} is off this task"}


def _drop_file(store: objects.ObjectStore, ident: str, att_id: str) -> dict:
    """Take one file off a project.

    The project is looked up first and the key is written here out of its id,
    so the page never names a directory: the worst it can say is the id of a
    project it is already looking at and the id of a file in it.
    """
    row = store.get_project(ident) if ident else None
    if row is None:
        return {"ok": False, "why": "There is no project here with that id."}
    gone = _held().drop(files_key(ident), att_id)
    if gone is None:
        return {"ok": False, "why": "That file is not on this project."}
    uploads.forget(files_key(ident), att_id)
    log.info("took %s off the project %s", gone["name"], row.title)
    return {"ok": True, "did": f"{gone['name']} is off {row.title}"}


def _delete_project(root, store: objects.ObjectStore, ident: str) -> dict:
    """Delete a project that holds nothing, and its folder with it.

    Only when it holds nothing, which is the rule the retired page had and is
    the only rule that makes this safe to offer from a page: `store.delete`
    takes the whole subtree with it, and a folder with work in it is not
    something a misdirected drop should be able to take away. A project whose
    folder holds anything but its own sidecar is refused for the same reason,
    because the rows are not the only thing in there.
    """
    tree = _Tree(store)
    row = tree.rows.get(ident)
    if row is None or row["type"] != "project":
        return {"ok": False, "why": "There is no project here with that id."}
    if tree.under.get(ident):
        held = len(tree.under[ident])
        return {"ok": False, "why": f"{row['title']} still holds {held} thing"
                                    f"{'' if held == 1 else 's'}. Move them first."}
    folder = row.get("folder") or ""
    here = Path(str(root)) / folder if folder else None
    sidecar = objecttree.sidecar_path(here, root) if here is not None else None
    if here is not None and here.is_dir():
        left = [p.name for p in here.iterdir() if p != sidecar]
        if left:
            return {"ok": False, "why": f"{here.name} still has files in it "
                                        f"({', '.join(sorted(left)[:3])}). It is left alone."}
    if not store.delete_project(ident):
        return {"ok": False, "why": "It is not there any more."}
    if here is not None:
        _remove_folder(here, root)
    # Its notes are not objects and do not go with it. Nothing Rouh was told
    # is thrown away because a project went: they go back to the general
    # memory, where the person still reads them (`rouh/keeping.py`).
    moved = keeping.unfile(ident, row["title"] or row["slug"] or "")
    said = f"{row['title']} is gone"
    if moved:
        said += (f", and its {moved} kept note{'' if moved == 1 else 's'} went "
                 "back to the general memory")
    return {"ok": True, "did": said}


def _remove_folder(here: Path, root) -> None:
    """Take an emptied folder off the disk, through git where git knows it."""
    try:
        done = subprocess.run(["git", "rm", "-r", "-q", "--", str(here)], check=False,
                              cwd=str(root), capture_output=True, text=True, timeout=30)
        if done.returncode == 0:
            return
        log.info("git rm %s said: %s", here, (done.stderr or "").strip())
    except (OSError, subprocess.SubprocessError) as exc:
        log.info("git rm %s could not run: %s", here, exc)
    try:
        shutil.rmtree(here, ignore_errors=True)
    except OSError:
        log.warning("%s could not be removed", here)


# What this module reads from `objectindex`, imported last: every function above
# reads these only when it is called, so this module and `objectindex` load in
# either order, and `objectindex` imports this one at its own bottom.
from .objectindex import (  # noqa: E402
    PALETTE, _HEX, _Tree, _held, _ready, files_key, index_data, log, project_data, task_files,
    task_files_key, write_instructions)
