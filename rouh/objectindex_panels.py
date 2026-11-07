"""The panels and rows of the task browser's own pages, as HTML.

What a task's, a subtask's and a goal step's page is drawn out of
(`objectindex._level` and the pages around it): the Slack, decision, Sources,
subtask, files and goal sections, the header's pin, Upload and three dots, the
box for a question a job is waiting on, and the line, Download and menu of every
file, page, chat and folder listed there. Every function here gives back markup
and writes nothing.

`objectindex` imports this module at its bottom and re-exports every name in
it, so callers keep reaching each one as `objectindex.<name>`.
"""
from __future__ import annotations

import html
import json
import os
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

from . import (addressing, answering, clock, docview, filelinks, objects, pages, task_origin,
               waiting)



#: Slack's mark, as its gene draws it (`rouh/genes/manifests/slack.json`).
SLACK_MARK = ('<svg class="oslack-mark" viewBox="0 0 24 24" aria-hidden="true" fill="none" '
              'stroke="currentColor" stroke-width="1.9" stroke-linecap="round">'
              '<path d="M9.5 3.5 7.5 20.5"/><path d="M16.5 3.5l-2 17"/><path d="M4 9h16.5"/>'
              '<path d="M3.5 15H20"/></svg>')


def _slack_section(person, ident: str) -> str:
    """The Slack channels linked to this task (`rouh/slack_tasks.py`): one small line each,
    naming the channel, with Unlink, and under it the decisions written from it into the task's
    notes, closed until pressed, each with a cross that takes it out of the notes. Only for the
    person who linked them; "" when nothing is linked. Unlink and the crosses are drawn hidden,
    and `taskpage.js` shows them where Rouh is around the page to hand a press to."""
    if person is None or not ident:
        return ""
    from . import slack_tasks

    try:
        linked = slack_tasks.for_page(person, ident)
    except Exception:
        log.exception("the Slack channels linked to %s could not be read", ident)
        return ""
    if not linked:
        return ""
    return (f'<section class="oslack" id="tkSlack" aria-label="Linked Slack channels">'
            f'{"".join(slack_line(one) for one in linked)}</section>')


def slack_line(one: dict) -> str:
    """One linked channel on a task's page (`_slack_section`); `taskpage.js` draws the same
    from what Rouh answers after a press."""
    name = html.escape(one["name"])
    channel = (f'<a href="{html.escape(one["url"], quote=True)}" target="_blank" rel="noopener">{name}</a>'
               if one.get("url") else name)
    rows = []
    for d in one.get("decisions") or []:
        said = (f'<a href="{html.escape(d["link"], quote=True)}" target="_blank" rel="noopener">'
                f'In Slack</a>' if d.get("link") else "")
        rows.append(f'<li class="osd" data-decision="{int(d["id"])}"><span class="osd-w">'
                    f'<span class="osd-day">{html.escape(d["day"])}</span>, {html.escape(d["who"])}: '
                    f'{html.escape(d["decision"])} {said}</span>'
                    f'<button type="button" class="fdrop osd-x" hidden aria-label="Take it out of the notes" '
                    f'title="Take it out of the notes">&times;</button></li>')
    many = len(rows)
    made = (f'<details class="osmade"><summary>{many} decision{"" if many == 1 else "s"} written '
            f'into the notes</summary><ul>{"".join(rows)}</ul></details>' if rows else "")
    return (f'<div class="oslink" data-link="{int(one["id"])}"><p class="oslink-line">{SLACK_MARK}'
            f'<span class="oslink-w">Decisions in {channel} go into the notes</span>'
            f'<button type="button" class="obtn oslink-x" hidden>Unlink</button></p>{made}</div>')


def _decision_of(person, source: str, source_id: str) -> dict | None:
    """This task's or goal step's newest decision (`rouh/decisions.py`), read level with what
    it asks first, or None: for anybody but the workspace's owner, and for a page with nobody
    signed in. A goal step has one only while it is, or was, a decision of the person's."""
    if person is None or not source_id:
        return None
    from . import decision_sources, decisions

    try:
        if not decision_sources._owner(person):
            return None
        decisions.sync(person, kinds={source})
        got = decisions.for_source(person, source, source_id)
    except Exception:
        log.exception("the decision of %s %s could not be read", source, source_id)
        return None
    if got is None:
        return None
    got.pop("events", None)
    return got


def _decision_mount(decided: dict) -> str:
    """Where `decision.js` draws the decision, with the decision on it."""
    blob = json.dumps(decided, ensure_ascii=False, default=str)
    return (f'<div id="dqMount" class="dq-mount" '
            f'data-decision="{html.escape(blob, quote=True)}"></div>')


def _sent_up(task_id: str) -> list[dict]:
    """What this task's subtasks sent up to it, newest first, or nothing."""
    if not task_id:
        return []
    from . import subtasknotes

    try:
        return subtasknotes.notes_for(task_id, limit=MOST_LISTED + 50)
    except Exception:
        log.exception("what the subtasks of %s sent up could not be read", task_id)
        return []


def _sent_up_row(one: dict, now: datetime) -> str:
    """One note a subtask sent up: which subtask, when, and what it said,
    as a line that opens the chat it was sent from."""
    from . import subtasknotes

    where = addressing.url_for("chat", one["chat"]) if one.get("chat") else ""
    step = subtasknotes.step_of_folder(one.get("folder"))
    name = one.get("from") or "A subtask that is no longer there"
    if step and name.startswith(step + " · "):
        name = name[len(step) + 3:]
    when = f'{stamp(one["at"], now)} {clock.clock(one["at"])}'.strip()
    return (f'<a class="orow onote" href="{html.escape(where, quote=True)}" data-kind="note">'
            f'<span class="omark" aria-hidden="true">\u2191</span>'
            f'<span class="snum">{html.escape(step)}</span>'
            f'<span class="oname">{html.escape(name)}</span>'
            f'<span class="ochip"></span>'
            f'<span class="ometa-cell">{html.escape(when)}</span>'
            f'<span class="otext">{html.escape(one["text"])}</span></a>')


#: The pill beside the name of a task or a subtask that is archived.
ARCHIVED_PILL = '<span class="task-status" data-status="archived">Archived</span>'


def _sources_section(person, root, rel: str) -> str:
    """The Sources section: every page with footnotes in this task or step, or in one of its
    subtasks (`rouh/source_check.py`). A checked page says how many of its sources to look at,
    newest first; a page never checked has **Check sources** at the end of its line, and nothing
    is read until it is pressed. Its line opens Sources for that page's own folder
    (`/sources/<folder>`), which lists it and opens it there.

    Petar, 13 October 2026 (fr_fce8f51c00d6): "Sources should not be in the main navigation, only
    in the sources of each task". So this is the way in, and the only one. And on 17 October 2026
    (fr_563bcb1bdb26): "make the check sources off by default and on demand with click of a
    button. I will be using it only for specific cases that require it". So the button: handed up
    to Rouh, which starts the check and opens its Sources, where it is seen being read
    (`taskPageAct` in app.js). Drawn hidden, and shown by `taskpage.js` when Rouh is around the
    page to hand the press to. Nothing when the switch is off, when nobody is signed in, or when
    no page here cites enough sources to check.
    """
    if person is None or not rel:
        return ""
    try:
        from . import source_check

        got = source_check.listing(person, root, rel)
    except Exception:  # noqa: BLE001 - the page is drawn without it
        log.exception("the checked sources under %s could not be read", rel)
        return ""
    pages = got.get("pages") or []
    if got.get("off") or not pages:
        return ""
    now = datetime.now()
    rows = []
    for one in pages[:MOST_LISTED]:
        c = one.get("counts") or {}
        state = one.get("state")
        if state == "unchecked":
            chip = None
        elif state == source_check.ASKED:
            chip = ("open", f"Checking, {one['sources'] - (c.get('pending') or 0)} of {one['sources']}")
        elif c.get("look"):
            chip = ("waiting", f"{c['look']} to look at")
        elif state == "stopped":
            chip = ("open", f"{one['sources'] - (c.get('pending') or 0)} of {one['sources']} checked")
        else:
            chip = ("done", f"All {one['sources']} checked")
        pill = (f'<span class="task-status" data-status="{chip[0]}">{html.escape(chip[1])}</span>'
                if chip else "")
        folder = one["doc"].rsplit("/", 1)[0]
        step = (one.get("step") or "").split(" · ", 1)[0]
        title = one.get("title") or folder.rsplit("/", 1)[-1]
        line = _object_row("sources", addressing.SOURCES + "/" + quote(folder, safe="/"),
                           title, stamp(one.get("checked_at") or 0, now) if chip else "",
                           pill, number=step)
        # The page's own three dots, as its line has on its own level: Petar, 15 October 2026
        # (fr_e8be3507d4d6), "the page ... don't have dots, and they should".
        inside = one["doc"][len(rel) + 1:] if one["doc"].startswith(rel + "/") else ""
        line = (_item_line(line, rel, inside, person, title) if inside else line)
        again = state == "stopped" or one.get("changed")
        if inside and (state == "unchecked" or (again and state != source_check.ASKED)):
            words = "Check sources" if state == "unchecked" else "Check again"
            check = (f'<button type="button" class="ocheck" data-check="{html.escape(inside, quote=True)}" '
                     f'aria-label="{words} of {html.escape(title, quote=True)}" hidden>{words}</button>')
            if line.startswith('<div class="oline oitem"'):
                # Inside its line beside its dots.
                line = ('<div class="oline oitem ochecks"' + line[len('<div class="oline oitem"'):-len("</div>")]
                        + check + "</div>")
            else:
                line = f'<div class="oline ochecks">{line}{check}</div>'
        rows.append(line)
    look = sum((one.get("counts") or {}).get("look") or 0 for one in pages)
    checked = sum(1 for one in pages if one.get("state") != "unchecked")
    note = (f"{look} source{'' if look == 1 else 's'} here may not say what the page says."
            if look else "Every source checked here says what its page says." if checked else "")
    return _section("Sources", len(pages), "".join(rows), note=note, cls="osources")


def _silo_chips(person, ident) -> str:
    """A task's silos (`rouh/silos.py`) as small chips beside its name: what Petar set on it in Synapse,
    else its project's or column's rule. Nothing when none says, or for nobody signed in."""
    if person is None or not ident:
        return ""
    try:
        from . import silos

        got, _why = silos.of_owner(str(person.user_id), str(person.org_id), "task", ident)
        chips = silos.chips(str(person.user_id), str(person.org_id), got)
    except Exception:  # noqa: BLE001 - the page is drawn without them
        log.exception("the silos of task %s could not be read", ident)
        return ""
    if not chips:
        return ""
    names = ", ".join(c["name"] for c in chips)
    return (f'<span class="silo-chips task-silos" title="Its silos: {html.escape(names, quote=True)}" '
            f'aria-label="Silos: {html.escape(names, quote=True)}">'
            + "".join(f'<span class="silo-chip" style="--silo:{html.escape(c["colour"], quote=True)}">'
                      f'<span class="silo-dot"></span><span class="silo-name">{html.escape(c["name"])}</span></span>'
                      for c in chips) + "</span>")


def _subtask_section(subs: list[dict], whole: bool = False, rel: str = "", person=None) -> str:
    """The Subtasks section: the live ones only, or nothing when every one is archived.

    The archived ones are in the Archive at the very bottom of the page
    (`_archive_section`). On a page that is itself archived (`whole`) its
    subtasks went into the Archive with it, and are listed here as they always were.
    """
    live = [s for s in subs if whole or not s["archived"]]
    if not live:
        return ""
    return _section("Subtasks", len(live),
                    "".join(_subtask_row(s, 0, whole, rel, person) for s in live),
                    cls="osubs", cut=False)


def _archive_section(subs: list[dict], whole: bool = False, rel: str = "", person=None) -> str:
    """The Archive, at the very bottom of a task's page: its archived subtasks, closed until pressed.

    Petar, 30 October 2026 (fr_0a87db94c515): "at the very bottom of every task, there should be
    'Archive' where we can see the archived pages. otherwise when I archive something I don't
    know how to get to it". Until then they were behind an Archived button on the Subtasks rule,
    which he never found. Each row opens its subtask, whose own menu has Unarchive. Not drawn
    when nothing is archived, and not on a page that is itself archived (`whole`).
    """
    gone = [] if whole else [s for s in subs if s["archived"]]
    if not gone:
        return ""
    return (f'<details class="oset osubs oarchived" id="taskArchive">'
            f'<summary class="divider">Archive<span class="c">{len(gone)}</span></summary>'
            f'<div class="rows">{"".join(_subtask_row(s, 0, True, rel, person) for s in gone)}</div>'
            f'</details>')


#: The pin: the same drawing as the pin in Rouh's menus (`menu.js`), with its
#: head closed so a pinned one can be filled in.
PIN_SVG = ('<svg class="ic" viewBox="0 0 24 24" aria-hidden="true" fill="none" '
           'stroke="currentColor" stroke-width="1.8" stroke-linecap="round" '
           'stroke-linejoin="round"><path class="pin-head" '
           'd="M10 3.5V9l-3 3v1.5h10V12l-3-3V3.5z"/><path d="M9 3.5h6"/>'
           '<path d="M12 13.5v7"/></svg>')

#: An arrow up out of a tray: Upload, beside the pin (`_upload_button`).
UPLOAD_SVG = ('<svg class="ic" viewBox="0 0 24 24" aria-hidden="true" fill="none" '
              'stroke="currentColor" stroke-width="1.8" stroke-linecap="round" '
              'stroke-linejoin="round"><path d="M12 15V4.5"/><path d="M7.5 9 12 4.5 16.5 9"/>'
              '<path d="M4.5 14.5v4a1.5 1.5 0 0 0 1.5 1.5h12a1.5 1.5 0 0 0 1.5-1.5v-4"/></svg>')


def _pin_button(called: str, pinned: bool) -> str:
    """The pin in the header of a task's or a subtask's own page: one press
    pins it to the Control Room, and one more unpins it (`rouh/pinning.py`).

    Petar, 29 September 2026: in the header of every task page and every step
    page, and not in the three dots, which are for rarer things. It pins this
    one and nothing above or below it."""
    what = "subtask" if called == "Subtask" else "task"
    says = (f"Pinned to the Control Room. Press to unpin this {what}" if pinned
            else f"Pin this {what} to the Control Room")
    return (f'<button type="button" class="opin" id="tkPin" '
            f'aria-pressed="{"true" if pinned else "false"}" '
            f'aria-label="{"Unpin from the Control Room" if pinned else "Pin to the Control Room"}" '
            f'title="{says}">{PIN_SVG}'
            f'<span class="opin-w">{"Pinned" if pinned else "Pin"}</span></button>')


def _task_files_section(ident: str) -> str:
    """The files uploaded to a task or a subtask from its own page.

    Petar, 15 October 2026 (fr_f79f49b86538): "when I open a task, please put
    an upload button so I can upload files directly there". They are kept the
    way a project's are, in the attachment store under the task's id
    (`task_files_key`), never in the workspace, and are found by search and
    told to its chats (`files_block`). Drawn hidden while there are none, so
    `taskpage.js` has somewhere to put the first one the moment it lands; the
    cross that takes one off is drawn by it too, only when Rouh frames the
    page.
    """
    held = task_files(ident)
    rows = "".join(_file_row(one) for one in held)
    return (f'<section class="oset ofiles" id="tkFilesSet"{"" if held else " hidden"}>'
            f'<h2 class="divider">Files<span class="c" id="tkFileCount">{len(held)}</span></h2>'
            f'<div class="rows" id="tkFileRows">{rows}</div></section>')


def _upload_button(called: str) -> str:
    """Upload, in the header of a task's or a subtask's own page, before the pin.

    A button of its own rather than an item in the three dots, which are for
    rarer things: it is the one way a file gets onto the task, and Petar asked
    for it to be there when the task is open (fr_f79f49b86538). It opens the
    browser's own picker, which takes several files at once (`taskpage.js`).
    """
    what = "subtask" if called == "Subtask" else "task"
    return (f'<button type="button" class="opin oup" id="tkUpload" '
            f'aria-label="Upload files to this {what}" '
            f'title="Upload files to this {what}">{UPLOAD_SVG}'
            f'<span class="opin-w">Upload</span></button>')


def _for_pill(made_for) -> str:
    """"For Sam Rivera" beside the name of a task made for somebody else, with the
    channel in its title, or "By Thoughts" beside one a process of Rouh's made
    (`rouh/task_origin.py`), or "" for one of his own."""
    said = html.escape(task_origin.words(made_for), quote=True)
    if task_origin.others(made_for):
        return (f'<span class="forchip" title="{said}">'
                f'<span>For {html.escape(str(made_for["for"]))}</span></span>')
    if task_origin.by_process(made_for):
        name = task_origin.process_words(task_origin.process_of(made_for))
        return (f'<span class="forchip bychip" title="{said}">'
                f'<span>By {html.escape(name)}</span></span>')
    return ""


def _task_dots(called: str, shelved: bool = False, pinned: bool = False,
               uploads: bool = False, made_for=None) -> str:
    """The three dots at the right of a task's or a subtask's name, and their
    menu: Rename, Move, Archive (or Unarchive, when it is archived), whose task
    it is, and Delete.

    Whose task it is since 15 October 2026 (`rouh/task_origin.py`): the two of
    "This is my task", which brings it back among his own, "Made for someone
    else", which puts it with Others' tasks, and "Made by Rouh", which puts it
    with the tasks Rouh's processes made, that it is not already. What he
    picks is kept, and nothing marks it again.

    Move is second since 29 September 2026 (fr_2c31bc88941c): "We want to be
    able to move any subtask or task to any other task or project." It is
    handed up, and Rouh opens its picker over the page (`moveOpen` in app.js,
    `rouh/moving.py`).

    Archive is between the two since 29 September 2026 (fr_08e097dbe815):
    "From inside it can be a button or in the... options, where rename and
    delete is." It is handed up like Delete, and Rouh archives the task and
    everything under it (`taskPageAct` in app.js, `rouh/archiving.py`).

    Petar, 27 September 2026 (fr_3273da8d3be9), on a task's page: "I see no
    option to delete task. just like a chat, I should have ... and then a menu
    that allows me to rename and delete this task." So it is the chat's menu
    (`menu.js`): Rename first, and Delete last, under a rule, in red. Rename
    edits the name where it is on this page; Delete opens Rouh's one delete
    dialog, which names the task and says what goes with it before anything
    does (`owning.plan`).

    The pin sits before the dots, one press, never in the menu
    (`_pin_button`), and Upload before the pin, for a task or a subtask that
    has a row to keep its files under (`_upload_button`).

    Drawn hidden, and shown by `taskpage.js` when Rouh is around the page to
    hand the press to: at the page's own address nothing can be changed.
    """
    what = "subtask" if called == "Subtask" else "task"
    up = _upload_button(called) if uploads else ""
    return (f'<div class="obar" id="tkBar" hidden>{up}{_pin_button(called, pinned)}'
            f'<button type="button" class="odots" id="tkMore" aria-haspopup="menu" '
            f'aria-expanded="false" aria-controls="tkMenu" '
            f'aria-label="What to do with this {what}" '
            f'title="What to do with this {what}">⋯</button>'
            f'<div class="menu tkmenu" id="tkMenu" role="menu" hidden>'
            f'<button type="button" class="menu-item" id="tkRename" role="menuitem" '
            f'data-icon="rename">Rename</button>'
            f'<button type="button" class="menu-item" id="tkMove" role="menuitem" '
            f'data-icon="move">Move</button>'
            f'{_move_out_items(called, "tk")}'
            f'<button type="button" class="menu-item" id="tkArchive" role="menuitem" '
            f'data-icon="{"unarchive" if shelved else "archive"}" '
            f'data-on="{"false" if shelved else "true"}">'
            f'{"Unarchive" if shelved else "Archive"}</button>'
            f'{_whose_items(made_for)}'
            f'<hr class="menu-rule">'
            f'<button type="button" class="menu-item danger" id="tkDelete" role="menuitem" '
            f'data-icon="delete">Delete</button>'
            f'</div></div>')


def _move_out_items(called: str, ids: str = "") -> str:
    """A subtask's two ways out of its task, under Move (`rouh/moving.py`): "Move to new task",
    the first subtask of a task made for it, and "Promote to task", a task of its own. Petar,
    22 October 2026 (fr_676c7ad596fd): "If we are creating it as a subtask of a brand-new task,
    that can be done from the ". . ." context menu ... If it needs to be promoted to its own
    main task, that can also be done from the ". . ." menu." A task has neither."""
    if called != "Subtask":
        return ""
    own = (lambda name: f' id="{ids}{name}"') if ids else (lambda name: "")
    return (f'<button type="button" class="menu-item"{own("NewTask")} role="menuitem" '
            f'data-icon="newtask" data-act="new_task">Move to new task</button>'
            f'<button type="button" class="menu-item"{own("Promote")} role="menuitem" '
            f'data-icon="promote" data-act="promote">Promote to task</button>')


#: Whose a task can be said to be, from its menu: the act handed up, the words, the icon.
WHOSE_ITEMS = (("person", "mine", "This is my task", "people"),
               ("other", "not_mine", "Made for someone else", "people"),
               ("process", "rouhs", "Made by Rouh", "rouh"))


def _whose_items(made_for) -> str:
    """The menu's two items saying whose a task is, of the three it is not already."""
    now = task_origin.made(made_for)
    now = "process" if now.startswith(task_origin.PROCESS) else now
    return "".join(
        f'<button type="button" class="menu-item tkwhose" id="tkWhose-{kind}" role="menuitem" '
        f'data-icon="{icon}" data-act="{act}">{words}</button>'
        for kind, act, words, icon in WHOSE_ITEMS if kind != now)


def _goal_row(store: objects.ObjectStore, ident: str, rel: str) -> str:
    """The goal, as one line on its task's page that opens its own page, or ""
    for a task that is not a goal. It says where the goal stands, and first of
    all whether anything in it is waiting on the person."""
    from . import goals

    task = store.get_task(ident) if ident else None
    folder = goals._folder(task) if task is not None else None
    if folder is None or not goals.is_goal(goals._meta(folder)):
        return ""
    try:
        v = goals.view(task)
    except Exception:
        log.exception("goal %s could not be read for its task's page", ident)
        return ""
    lanes = v["streams"]
    bits = [v["progress_words"]]
    if len(lanes) > 1:
        bits.append(f"{len(lanes)} streams side by side")
    if v["deadline"]:
        bits.append(f'due {v["deadline_words"]}')
    waiting = v["waiting_streams"]
    flag = (f'<span class="task-status" data-status="waiting">'
            f'{waiting} waiting on you</span>' if waiting else "")
    href = doc_url(rel, GOAL_DOC)
    return (f'<a class="prow" href="{html.escape(href, quote=True)}" data-kind="goal">'
            f'<span class="omark" aria-hidden="true">🎯</span>'
            f'<span class="ptext"><span class="phead"><span class="oname">The goal and its '
            f'streams</span>{flag}</span>'
            f'<span class="pabout">{html.escape(", ".join(bits))}</span></span>'
            f'<span class="pgo">Open the goal<span aria-hidden="true"> →</span></span></a>')


def _is_goal_folder(root, rel: str) -> bool:
    """Whether the task in this folder is tagged a goal (`goals.is_goal`)."""
    from . import goals

    if not root or not rel:
        return False
    return goals.is_goal(goals._meta(Path(str(root)) / rel))


#: A step's status as a goal's own page says it (`STATUS` in goalpage.js).
_GOAL_STATUS = {"not-started": "To do", "in-progress": "Doing", "waiting": "Waiting",
                "done": "Complete", "hollow": "Marked done, but nothing was made"}


def _goal_step_panel(store: objects.ObjectStore, under: _Under, ident: str) -> str:
    """What a step of a goal is, on the step's own page: the goal it is part
    of, who does it and what that asks of the person, how, the hard part and
    what to do about it, and the buttons to act on it.

    Petar, 27 September 2026 (fr_89eebb50bd23), from the page of step 67-03:
    "I dint understand what together means. Whatever it is, I have no way to
    follow through. Open link takes me to a dead end". The Goals page's Open
    brought him here, and all this page said was "Nothing in this yet": the
    step's words are in its meta (`goals.of_step`), which nothing on
    this page read. Now they are here, and so is the way to act on them.

    The buttons are drawn hidden, and `taskpage.js` shows them when there is
    a Rouh around the page to hand the press to, exactly as it does Start
    chat. "" for a task that is not a step of a goal.
    """
    from . import goals

    if not ident:
        return ""
    try:
        found = goals.of_step(store.get_task(ident))
    except Exception:
        log.exception("the goal above task %s could not be read", ident)
        return ""
    if found is None:
        return ""
    v, s = found
    who = s["who"] if s["who"] in goals.WHO else "other"
    goal_href = doc_url(v["folder"], GOAL_DOC) if v["folder"] else ""
    goal_name = html.escape(f'Task {v["number"]} · {v["title"]}')
    goal_line = (f'<a href="{html.escape(goal_href, quote=True)}">{goal_name}</a>'
                 if goal_href else goal_name)
    status = "hollow" if s.get("hollow") else s["status"]
    words = _GOAL_STATUS.get(status, status)
    if s.get("done_by") == "rouh":
        # Rouh did it and said so: complete, with nothing asked of him (fr_5404edbbea30).
        words = "Complete · Rouh did it"
    elif s.get("rouh_done"):
        # Rouh did its part; a decision or action of his is left (`goals.ROUH_DONE`).
        words = ("Rouh’s part done · waiting on you" if who in ("rouh", "together")
                 else "Waiting on you to mark it complete")
    parts = [f'<p class="ogs-goal">Step {html.escape(s["n"])} of the goal {goal_line}</p>',
             f'<p class="ogs-who"><span class="ogs-chip w-{who}">{html.escape(s["who_words"])}'
             f'</span><span class="ogs-status" data-status="{html.escape(status)}">'
             f'{html.escape(words)}</span></p>',
             f'<p class="ogs-means">{html.escape(s["who_means"])}</p>']
    if s["how"]:
        parts.append(f'<p class="ogs-how">{html.escape(s["how"])}</p>')
    if s.get("prep"):
        parts.append(f'<p class="ogs-left"><strong>Rouh gets ready</strong> '
                     f'{html.escape(s["prep"])}</p>')
    if s["challenge"] or s["solution"]:
        hard = ""
        if s["challenge"]:
            hard += f'<dt class="h-hard">Hard part</dt><dd>{html.escape(s["challenge"])}</dd>'
        if s["solution"]:
            hard += f'<dt class="h-fix">What to do</dt><dd>{html.escape(s["solution"])}</dd>'
        parts.append(f'<dl class="ogs-hard">{hard}</dl>')
    if s.get("rouh_done") and s.get("left"):
        parts.append(f'<p class="ogs-left"><strong>Left for you</strong> '
                     f'{html.escape(s["left"])}</p>')
    elif s.get("outcome") and status != "done":
        parts.append(f'<p class="ogs-left"><strong>Complete when</strong> '
                     f'{html.escape(s["outcome"])}</p>')
    if s.get("options") and status != "done":
        parts.append('<ul class="gp-options" aria-label="The options">' + "".join(
            f"<li>{html.escape(o)}</li>" for o in s["options"]) + "</ul>")
    run = s.get("run") or {}
    if run.get("words"):
        parts.append(f'<p class="ogs-run">{html.escape(run["words"])}</p>')
    acts = []
    if (status != "done" and not s.get("rouh_done") and run.get("mode") != "now"
            and who in ("rouh", "together")):
        acts.append('<button type="button" class="ogs-btn primary" data-goal-act="now">'
                    + ("Do it again" if status == "hollow" else "Do it now" if who == "rouh"
                       else "Start with Rouh") + '</button>')
    acts.append('<button type="button" class="ogs-btn" data-goal-act="undone">Reopen</button>'
                if status in ("done", "hollow") else
                '<button type="button" class="ogs-btn'
                + (' primary' if s.get("rouh_done") else '')
                + '" data-goal-act="done">Mark complete</button>')
    if s.get("rouh_done"):
        acts.append('<button type="button" class="ogs-btn" data-goal-act="undone">Reopen</button>')
    # The goal's own chat, its only one: a step is worked by a background run,
    # never in a chat of its own (`goals.brief_for_step`).
    chat = v.get("chat") or ""
    if chat and under.row("chat", chat) is not None:
        where = html.escape(addressing.url_for("chat", chat), quote=True)
        acts.append(f'<a class="ogs-btn" href="{where}">Open the goal&rsquo;s chat</a>')
    parts.append(f'<div class="ogs-acts" id="ogsActs" hidden>{"".join(acts)}</div>')
    return (f'<section class="oset ogoal"><h2 class="divider">Step of a goal</h2>'
            f'<div class="ogs w-{who}">{"".join(parts)}</div></section>')


#: The Send arrow, the same glyph as Rouh's own Send beside its box.
_SEND_ARROW = ('<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" '
               'stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">'
               '<path d="M12 20V6M6 11l6-6 6 6"/></svg>')

#: A job's state, read as what it means for an answer it was given.
_RUN_GOING = ("running", "starting")
_RUN_ASKING = ("waiting", "conflict")

#: How long an answer may sit in its chat with no job started from it before
#: the box stops saying one is on its way. Rouh hands it over in the turn the
#: answer starts, which is seconds.
_HANDING_OVER = 180.0


def _asking(root, rel: str, names, task_id: str):
    """What a task asks, and the answer to it if there is one: the question's
    shape, the notes' passage, the line an answer is kept against
    (`answering.asked_of`), and the answer (`answering.answer_to`) or None.
    `names` is what the signed-in person is called, because that is what the
    notes call them: "**Waiting on Mira:**" (`waiting.ask_in`)."""
    question, notes, line = answering.asked_of(root, rel, names)
    return question, notes, line, answering.answer_to(task_id, line) if task_id else None


def _answered_in(task_id: str):
    """The chat an answer from this task's box goes into, or None when the
    task holds no chat yet and the answer starts its first
    (`conversations.answering_chat`)."""
    from . import conversations

    return conversations.answering_chat(task_id) if task_id else None


def _waiting_panel(rel: str, number: str, asking, state: str = "waiting", *,
                   into=None) -> str:
    """What a task is waiting on the person for: its page's decision.

    Under the task's chats and its page since 24 September 2026, and folded to
    a compact card until it is pressed, when it opens in place into all of
    what follows (`_decision_top`).

    Petar, 24 September 2026 (fr_2050f48023a7), about this box on task 61:
    "it is very unstructured. ... easy options for answers predefined for me
    and option to give my own. but right there. and it has to be clear what
    happens afterwards. would the chat continue? the task will continue? ...
    I feel like the task is done but I have an optional question."

    So it says four things, in this order: what has stopped, what is asked,
    the answers he can give right here, and what answering does.

    - **What has stopped.** A task marked `waiting` is paused until he
      answers. A task marked `done` whose meta still asks something
      is finished, and the question is optional; any other done task draws
      nothing, and this returns "".
    - **What is asked.** The question as its meta puts it
      (`waiting.question_of`), else the passage from the task's own notes, as
      the notes draw it, else the plain fact that the notes do not say.
    - **The answers.** Each option its meta offers is a button that sends
      it with one press, or, where several may be picked, marks it for one
      Send; and under them a field for his own words. All of it is drawn
      hidden and shown by `taskpage.js`, because at the page's own address
      there is no Rouh to send anything to.
    - **What answering does.** It goes to Rouh at once, in the chat the task
      already has, named, which opens beside the page, and Rouh hands it to a
      job (`brain.WAITING`). `into` is that chat
      (`conversations.answering_chat`), or None when the task has none yet
      and the answer starts it. `then` in its meta says what that job
      will do, when whoever asked knew.

    Answered already (`answering.answer_to`), the box says so instead: what
    he answered and when, and which chat and which job have it now, until
    that job has changed the task and the question is gone.

    And either box can be **dismissed**: "i also need the option to dismiss
    it". Nothing is sent and the task is left as it is; the box folds to one
    line that says so, with the way back to it (`_dismissed_line`), and a
    question dismissed without an answer stops counting as waiting on him.
    Both are drawn every time, one of them hidden, so the press is answered
    on the page at once. `asking` is what `_asking` found.
    """
    question, notes, line, answered = asking
    done = state != "waiting"
    if done and question is None:
        return ""
    href = html.escape(doc_url(rel, waiting.NOTES), quote=True)
    # Where an answer goes, for the box to say before and after it is sent.
    named = _chat_named(into)
    keep = (f' data-number="{html.escape(number, quote=True)}"'
            f' data-asked="{html.escape(line, quote=True)}"'
            f' data-state="{"done" if done else "waiting"}"'
            f' data-into="{"task" if into is not None else "new"}"'
            f' data-chat="{html.escape(named, quote=True)}"')
    has_answer = answered is not None and bool(answered.answer)
    dismissed = answered is not None and answered.dismissed
    form = _answer_form(question, notes, line, again=has_answer)
    if has_answer:
        box = _answered_panel(answered, line, form, href, keep, done, hidden=dismissed)
    else:
        box = _asking_panel(question, notes, line, form, href, keep, done,
                            _answer_goes(named, into is not None), hidden=dismissed)
    return _dismissed_line(answered, done, shown=dismissed) + box


def _chat_named(chat) -> str:
    """What the chat an answer goes into is called, for the box to say, or
    "" when there is no chat yet. An untitled one is the task's chat all the
    same, and says so rather than "New chat"."""
    if chat is None:
        return ""
    from . import conversations

    title = (chat.title or "").strip()
    return "" if conversations.is_untitled(title) else title


def _answer_goes(named: str, has_chat: bool) -> str:
    """Where an answer goes, as the box says it: the task's own chat, by
    name, or a new one when it has none."""
    if named:
        return (f'in the task\'s chat, &ldquo;{html.escape(named)}&rdquo;, which opens beside '
                f'this page as you send it')
    if has_chat:
        return "in the task's chat, which opens beside this page as you send it"
    return "in a new chat about this task that opens as you send it"


#: The cross on Dismiss.
_CROSS = ('<svg viewBox="0 0 24 24" aria-hidden="true" fill="none" stroke="currentColor" '
          'stroke-width="2" stroke-linecap="round"><path d="M7 7l10 10M17 7L7 17"/></svg>')

#: The chevron on a decision's compact card, which turns over once it is open.
_CHEVRON = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" '
            'stroke-linecap="round" stroke-linejoin="round"><path d="M6 9l6 6 6-6"/></svg>')


def _decision_top(head: str, pill: str, asked: str, answer: str = "") -> str:
    """A decision as the compact card it is until it is pressed.

    Petar, 24 September 2026: "decisions can be clicked to be expanded to a
    card, as we will not have additional pages. otherwise they are listed as
    compact cards." So the box is a `<details>` and this is its summary: what
    kind of decision it is, its pill, what it asks and, once answered, the
    answer, with a chevron that says it opens. A press opens the whole box in
    place, under this same line, and a second press on it folds it again. It
    works with no script, so the page at its own address opens it too.
    """
    said = []
    if asked:
        said.append(f'<span class="owait-sum">{html.escape(asked)}</span>')
    if answer:
        words = answer if len(answer) <= 160 else answer[:160].rsplit(" ", 1)[0] + "…"
        said.append(f'<span class="owait-sum-said">You answered: '
                    f'&ldquo;{html.escape(words)}&rdquo;</span>')
    sums = f'<span class="owait-sums">{"".join(said)}</span>' if said else ""
    return (f'<summary class="owait-top"><span class="owait-h" id="owaitHead">{head}</span>'
            f'<span class="owait-pill">{pill}</span>'
            f'<span class="owait-chev" aria-hidden="true">{_CHEVRON}</span>{sums}</summary>')


def _dismiss(answered: bool) -> str:
    """Dismiss, at the right of the open box's foot, drawn hidden for
    `taskpage.js` to show. What it does is on it, for the pointer and for a
    screen reader: nothing is sent, and nothing about the task changes. It is
    not on the compact card: that line opens and folds the box, and one line
    that did two things would be a press that could do the wrong one."""
    what = ("Close this box. Your answer stands, and its job goes on." if answered else
            "Close this question without answering it. Nothing is sent, and the task "
            "stays as it is.")
    return (f'<button type="button" class="owait-x" id="owaitX" hidden title="{what}" '
            f'aria-label="Dismiss this {"box" if answered else "question"}. {what}">'
            f'Dismiss{_CROSS}</button>')


def _said_when(at: float) -> str:
    """"today at 17:52", or "23 Sep at 17:52", on the person's clock."""
    said = clock.moment(at) if at else None
    if said is None:
        return ""
    if said.date() == clock.now().date():
        return f"today at {said:%H:%M}"
    return f"{said.day} {said:%b} at {said:%H:%M}"


def _dismissed_line(answered, done: bool, *, shown: bool) -> str:
    """The one line a dismissed box folds to, and the way back to the box.

    Drawn on every page with the box, hidden until the box is dismissed, so
    the press on Dismiss is answered at once; shown in its place when the
    newest word on the question is a dismissal. It says that nothing was
    sent, what the task does now, and, when it had been answered, what the
    answer was and which job has it."""
    if answered is not None and answered.answer:
        words = answered.answer if len(answered.answer) <= 140 else (
            answered.answer[:140].rsplit(" ", 1)[0] + "…")
        said = (f'<strong>Answered</strong> {_said_when(answered.at)}: '
                f'&ldquo;{html.escape(words)}&rdquo;. {_job_said(answered)[2]}')
        back = "Show it"
    else:
        when = (_said_when(answered.dismissed_at) if shown and answered is not None
                else "just now")
        stays = ("the task stays done" if done else
                 "the task stays paused, and is not counted as waiting on you")
        said = f"<strong>Question dismissed</strong> {when}. Nothing was sent, and {stays}."
        back = "Show the question"
    return (f'<section class="owait-gone" id="owaitGone" aria-label="Dismissed"'
            f'{"" if shown else " hidden"}><p>{said}</p>'
            f'<button type="button" class="owait-back" id="owaitBack" hidden>{back}</button>'
            f'</section>')


def _asking_panel(question, notes, line: str, form: str, href: str, keep: str,
                  done: bool, goes: str, *, hidden: bool) -> str:
    """The box while it asks: what has stopped, the question, the answers and
    what answering does (`_waiting_panel`). `line` is the question in one line,
    for the compact card it folds to, and `goes` is where the answer goes,
    already made safe (`_answer_goes`)."""
    if question is not None and question.ask:
        asked = f'<p class="owait-q">{html.escape(question.ask)}</p>'
    elif notes is not None:
        asked = f'<div class="odoc owait-said">{docview.markdown_html(notes.markdown)}</div>'
    else:
        asked = ('<p class="owait-none">This task is marked Waiting, and its AGENTS.md does '
                 'not say what it is waiting for.</p>')
    if done:
        head, pill = "An optional question", "Done"
        now = ("<strong>This task is done.</strong> Nothing is waiting on this question: "
               "leave it and nothing changes. Answer it only if you want more.")
        then = (question.then if question and question.then else
                "Rouh hands it to a job, which opens the task again and does what you asked.")
        lead = "If you answer"
    else:
        head, pill = "Waiting on you", "Paused"
        now = ("<strong>This task is paused until you answer.</strong> What it has done "
               "so far is kept, and nothing more happens on it until you do.")
        then = (question.then if question and question.then else
                "Rouh hands it to a job, which writes your answer into the task's notes "
                "and carries the task on from here.")
        lead = "When you answer"
    read = "Read it in AGENTS.md" if notes else "Read the task's AGENTS.md"
    return (f'<details class="owait{" is-done" if done else ""}" id="owait"'
            f' aria-labelledby="owaitHead"{keep}{" hidden" if hidden else ""}>'
            + _decision_top(head, pill, line or "Its AGENTS.md does not say what it is "
                                                 "waiting for.")
            + f'<p class="owait-now">{now}</p>'
            f'<div class="owait-ask">{asked}</div>'
            f'{form}'
            f'<p class="owait-then"><strong>{lead},</strong> it goes straight to Rouh, '
            f'{goes}. {html.escape(then)} This box then shows the job that has it.</p>'
            f'<p class="owait-foot"><a class="owait-notes" href="{href}">{read}</a>'
            f'{_dismiss(False)}</p>'
            f'</details>')


def _answer_form(question, notes, line: str, *, again: bool) -> str:
    """The answers to pick and the field for his own, drawn hidden.

    One press sends an option. Where `several` may be picked, a press marks
    it and one Send under them sends every one marked, with anything written
    in the field after them. A task whose notes do not say what it waits on
    has one option of its own, which asks Rouh to find out."""
    options = list(question.options) if question else []
    several = bool(question and question.several)
    rows = []
    for at, option in enumerate(options, 1):
        detail = (f'<span class="owait-od">{html.escape(option.detail)}</span>'
                  if option.detail else "")
        pressed = ' aria-pressed="false"' if several else ""
        rows.append(
            f'<button type="button" class="owait-opt" data-answer="'
            f'{html.escape(option.label, quote=True)}"{pressed}>'
            f'<span class="owait-k" aria-hidden="true">{at}</span>'
            f'<span class="owait-ow"><span class="owait-ol">{html.escape(option.label)}</span>'
            f'{detail}</span><span class="owait-mark" aria-hidden="true">'
            f'{"" if several else _SEND_ARROW}</span></button>')
    if not options and notes is None and not line:
        rows.append(
            '<button type="button" class="owait-opt" data-find="1">'
            '<span class="owait-k" aria-hidden="true">?</span>'
            '<span class="owait-ow"><span class="owait-ol">Ask what it needs</span>'
            '<span class="owait-od">Rouh reads the task and tells you what it is '
            'waiting on you for.</span></span>'
            f'<span class="owait-mark" aria-hidden="true">{_SEND_ARROW}</span></button>')
    picked = ('<p class="owait-picked"><button type="button" class="owait-sendpicked"'
              ' id="owaitPicked" disabled>Pick one or more</button></p>' if several else "")
    choose = (f'<div class="owait-opts" role="group" aria-label="Answers to pick from">'
              f'{"".join(rows)}</div>{picked}' if rows else "")
    own = "Or answer in your own words" if rows else "Your answer"
    return (f'<div class="owait-form" id="owaitForm" hidden'
            f'{" data-several" if several else ""}{" data-again" if again else ""}>'
            f'{choose}'
            f'<div class="owait-own" id="owaitOwn">'
            f'<label class="owait-ownh" for="owaitText">{own}</label>'
            f'<div class="owait-field"><textarea id="owaitText" rows="1" maxlength="'
            f'{answering.ANSWER_MOST}" autocomplete="off" placeholder="Type your answer">'
            f'</textarea><button type="button" class="owait-send" id="owaitSend" '
            f'aria-label="Send your answer" title="Send">{_SEND_ARROW}</button></div></div>'
            f'</div>')


def _job_said(answered) -> tuple[str, str, str]:
    """Who has an answer now, three ways: the pill on the answered box, its
    sentence, and the short one the folded line ends with."""
    run = answered.run
    chat = (html.escape(addressing.url_for("chat", answered.chat_id), quote=True)
            if answered.chat_id else "")
    in_chat = (f'<a href="{chat}">a chat about this task</a>' if chat
               else "a chat about this task")
    if run is not None:
        job = (f'<a href="{html.escape(addressing.url_for("run", run.id), quote=True)}">'
               f'{html.escape(run.title or "the job")}</a>')
        word = str(run.state or "")
        if word in _RUN_GOING:
            return ("Going on",
                    (f"<strong>The task is going on.</strong> A job has your answer: {job}, "
                     "running now. This box goes when that job has saved its work."),
                    f"A job has it: {job}, running now.")
        if word in _RUN_ASKING:
            return ("Needs you",
                    (f"<strong>The job that has your answer is asking you something.</strong> "
                     f"Open {job} to see what."),
                    f"The job that has it is asking you something: {job}.")
        if word == "done":
            return ("Job finished",
                    (f"<strong>The job that had your answer has finished:</strong> {job}. "
                     "This box goes once what it saved reaches this page. If it stays, open "
                     "the chat to see what the job said."),
                    f"The job that had it has finished: {job}.")
        return ("Job stopped",
                (f"<strong>The job that had your answer stopped before it finished"
                 f"</strong> ({html.escape(RUN_WORDS.get(word, word).lower() or 'ended')}): "
                 f"{job}. Open the chat to see why, or answer again."),
                f"The job that had it stopped before it finished: {job}.")
    if time.time() - answered.at < _HANDING_OVER:
        return ("Sent",
                (f"<strong>Rouh has your answer.</strong> It is in {in_chat}, where Rouh "
                 "hands it to a job to carry the task on. This box shows that job once it "
                 "has started."),
                f"It is in {in_chat}, and Rouh is handing it to a job.")
    return ("Sent",
            (f"<strong>Rouh has your answer,</strong> in {in_chat}, and no job has been "
             "started from it yet. Open the chat to see what Rouh said, or answer again."),
            f"It is in {in_chat}, and no job has been started from it yet.")


def _answered_panel(answered, line: str, form: str, href: str, keep: str,
                    done: bool, *, hidden: bool = False) -> str:
    """The box once it has been answered: what, when, and who has it now."""
    pill, now, _short = _job_said(answered)
    chat = (html.escape(addressing.url_for("chat", answered.chat_id), quote=True)
            if answered.chat_id else "")
    when = _said_when(answered.at)
    asked = (f'<p class="owait-was"><span class="owait-wk">It asked</span>'
             f'{html.escape(line)}</p>' if line else "")
    links = [('<button type="button" class="owait-again" id="owaitAgain" hidden>'
              'Answer again</button>')]
    if chat:
        links.append(f'<a class="owait-notes" href="{chat}">Open the chat</a>')
    links.append(f'<a class="owait-notes" href="{href}">Read the task\'s AGENTS.md</a>')
    links.append(_dismiss(True))
    return (f'<details class="owait is-answered{" is-done" if done else ""}" id="owait"'
            f' aria-labelledby="owaitHead"{keep}{" hidden" if hidden else ""}>'
            + _decision_top("Answered", pill, line, answered.answer)
            + f'<p class="owait-now">{now}</p>'
            f'{asked}'
            f'<blockquote class="owait-mine"><span class="owait-wk">You answered'
            f'{", " + when if when else ""}</span>{html.escape(answered.answer)}</blockquote>'
            f'{form}'
            f'<p class="owait-foot">{"".join(links)}</p></details>')


#: The arrow on every Download, the one glyph the canvas bar draws it with too.
DOWNLOAD_ICON = ('<svg viewBox="0 0 24 24" width="15" height="15" aria-hidden="true" '
                 'fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" '
                 'stroke-linejoin="round"><path d="M12 4v11M7 10l5 5 5-5M5 20h14"/></svg>')


def _file_word(name: str) -> str:
    """What kind of file a name is, as its pill says it: its extension in
    capitals, PDF, XLSX, CSV, and "File" for a name with none worth reading.

    Petar, 30 September 2026: "it says in a label file or something generic. I
    would prefer the extension of the type of file. PDF for example".
    """
    ext = os.path.splitext(str(name or ""))[1][1:]
    return ext.upper() if ext and len(ext) <= 5 and ext.isalnum() else "File"


def _download(rel: str, name: str, person) -> str:
    """The Download button under a file's name: the file as it is on disk,
    under its own name, saved to the reader's computer.

    Petar, 29 September 2026, reading a bank's PDF under a task: "I have no way
    to download it. Make a download button". A PDF, a spreadsheet or a picture
    is only said not to be text here (`_plain_file`), so without this there was
    nothing to do with one at all. It spent a day in Rouh's top bar, because a
    link in this frame could not download (`rouh/filelinks.py` says why), and
    came back here when he said "I like the old place of the button".

    Nothing for a page drawn for nobody, which has nobody to sign a link for.
    """
    if person is None:
        return ""
    href = filelinks.link(person, rel, name)
    shown = name.rsplit("/", 1)[-1]
    return (f'<p class="oget"><a class="odl" href="{html.escape(href, quote=True)}" '
            f'download="{html.escape(shown, quote=True)}" '
            f'title="Download {html.escape(shown, quote=True)}">'
            f'{DOWNLOAD_ICON}Download</a></p>')


def _file_line(row: str, rel: str, name: str, person) -> str:
    """A file's line in a list, with a Download button at its end.

    Petar, 30 September 2026, on the page of task 18-03 that lists its PDF: "On
    the line there should be a download button." Beside the line rather than
    in it, because the line is a link that opens the file and a link cannot
    hold another. The line keeps its columns: every line of a list that has
    one leaves room at its end (`.oline` in taskbrowser.css).
    """
    if person is None:
        return row
    href = filelinks.link(person, rel, name)
    shown = name.rsplit("/", 1)[-1]
    said = html.escape(f"Download {shown}", quote=True)
    return (f'<div class="oline">{row}'
            f'<a class="orow-dl" href="{html.escape(href, quote=True)}" '
            f'download="{html.escape(shown, quote=True)}" title="{said}" '
            f'aria-label="{said}">{DOWNLOAD_ICON}</a></div>')


def _item_acts(name: str, person) -> list[str]:
    """What an item's own menu on a task's page offers, by the sections it has: "pdf" for a page
    or a Markdown file, while printable PDFs are on (`rouh/page_pdf.py`). Nothing for a page
    drawn for nobody, which has nobody to make anything for."""
    if person is None:
        return []
    from . import page_pdf

    acts = []
    if str(name).lower().endswith(page_pdf.PRINTABLE) and page_pdf.on(getattr(person, "org_id", None)):
        acts.append("pdf")
    return acts


def _item_line(row: str, rel: str, item: str, person, called: str = "", rename: str = "") -> str:
    """An item's line on a task's page, with its own three dots and their menu at its end.

    Petar, 15 October 2026 (fr_4c075039223f), after a PDF of a task gave him its HTML page: "Each
    item in the folder of a task or sub task should have its dotdotdot menu and then inside could
    be the PDF option ... In this menu we might even be putting other useful stuff later. Plenty
    of options for drive-type interactions - move, permissions, extra info, rename delete". So
    the menu is the item's, one section per thing it can do (`_item_acts`), and PDF is the first:
    Letter paper and A4 paper, each making a PDF of this one item and nothing else. A line with
    nothing to offer has no dots, rather than dots that open an empty box.

    ``item`` is its path inside the task's folder, and ``called`` what its line calls it, which
    is what the dots are named after (a page's title, a .md's file name). The press is handed up and Rouh puts the
    folder it framed in front of it (`taskPageAct` in app.js). Drawn hidden, and shown by
    `taskpage.js` when Rouh is around the page to hand the press to.

    ``rename`` puts Rename first, on a page listed under Page: "page" gives the page itself
    another name (`pagehistory.retitle`), and "step" is a step's own page, which is called what
    the step is called, so it renames the step. Petar, 26 October 2026 (fr_0234d21daa0b): "Add
    rename to this context menu". The name changes in place, as a task's own does
    (`taskpage.js`), and the file keeps its name, so no link to it breaks.
    """
    acts = _item_acts(item, person)
    parts = [_PDF_ITEMS.format(what="item")] if "pdf" in acts else []
    attrs = {"data-item": item}
    if person is not None and rename in ("page", "step"):
        parts.insert(0, _menu_item("rename", "rename", "Rename"))
        attrs["data-names"] = rename
    if not parts:
        return row
    shown = called or item.rsplit("/", 1)[-1]
    return _dots_line(row, shown, parts, attrs)


#: The PDF section of an item's menu: one press per paper, each making that one thing alone.
_PDF_ITEMS = ('<div class="menu-head">PDF of this {what}</div>'
              '<button type="button" class="menu-item" role="menuitem" data-icon="pdf" '
              'data-act="pdf" data-paper="letter">Letter paper</button>'
              '<button type="button" class="menu-item" role="menuitem" data-icon="pdf" '
              'data-act="pdf" data-paper="a4">A4 paper</button>')


def _menu_item(act: str, icon: str, words: str, danger: bool = False) -> str:
    return (f'<button type="button" class="menu-item{" danger" if danger else ""}" role="menuitem" '
            f'data-icon="{icon}" data-act="{act}">{html.escape(words)}</button>')


def _dots_menu(shown: str, parts: list[str], cls: str = "odots orow-dots") -> str:
    """Three dots named after what they are for, and their menu, one section per part with a rule
    between. Drawn hidden; `taskpage.js` shows them where Rouh is around the page to hand a press
    to, and hands each item's ``data-act`` up with what its line names."""
    said = html.escape(f"What to do with {shown}", quote=True)
    return (f'<button type="button" class="{cls}" hidden aria-haspopup="menu" '
            f'aria-expanded="false" aria-label="{said}" title="{said}">⋯</button>'
            f'<div class="menu imenu" role="menu" aria-label="{said}" hidden>'
            f'{"<hr class=menu-rule>".join(parts)}</div>')


def _dots_line(row: str, shown: str, parts: list[str], attrs: dict) -> str:
    """A line on a task's page with its own three dots at its end (`_dots_menu`). ``attrs`` say
    what the line is to Rouh: ``data-item`` a file in the task, ``data-chat`` a chat."""
    if not parts:
        return row
    marks = "".join(f' {k}="{html.escape(str(v), quote=True)}"' for k, v in attrs.items())
    return f'<div class="oline oitem"{marks}>{row}{_dots_menu(shown, parts)}</div>'


def _chat_line(row: str, chat, person) -> str:
    """A chat's line on a task's page, or a fork's, with its own three dots: a PDF of the whole
    conversation, then what its dots in Rouh's own lists offer that make sense here (Cards, Pin,
    Delete; `rowMenu` in index.html). Renaming stays where its name is, in the chat itself.

    Petar, 15 October 2026 (fr_e8be3507d4d6), on task 108's page: "The chats and the page and
    finals don't have dots, and they should. Chat should be pdf-able as well as pages." The PDF is
    made on the server (`page_pdf.make_chat`), and Rouh's notification says when it is ready."""
    if person is None or chat is None:
        return row
    from . import page_pdf

    shown = _its_emoji(chat.title or "")[1] or "this chat"
    parts = []
    if page_pdf.on(getattr(person, "org_id", None)):
        parts.append(_PDF_ITEMS.format(what="chat"))
    pinned = bool(getattr(chat, "pinned", False))
    parts.append(_menu_item("cards", "cards", "Cards")
                 + _menu_item("unpin" if pinned else "pin", "unpin" if pinned else "pin",
                              "Un-pin" if pinned else "Pin"))
    parts.append(_menu_item("delete", "delete", "Delete", danger=True))
    return _dots_line(row, shown, parts, {"data-chat": chat.id, "data-name": shown})


def _subtask_dots(one: dict, rel: str, person) -> str:
    """A subtask's own three dots on its task's page, before its arrow: a PDF of the page it
    built, and what its dots on its own page offer that make sense from here (Pin, Move, Archive,
    Delete; `_task_dots`). Renaming stays on its own page, where its name is.

    Petar, 15 October 2026 (fr_e8be3507d4d6): "Subtasks can have at least the dots if not pdf".
    Only for a subtask whose folder is inside this level's, which is how Rouh finds it again from
    the folder it framed (`taskPageAct` in app.js)."""
    folder = str(one.get("folder") or "")
    if person is None or not rel or not folder.startswith(rel + "/"):
        return ""
    sub = folder[len(rel) + 1:]
    page = str(one.get("page_file") or "")
    parts = []
    if page and _item_acts(page, person):
        parts.append(_PDF_ITEMS.format(what="subtask's page"))
    pinned, shelved = bool(one.get("pinned")), bool(one.get("archived"))
    parts.append(_menu_item("unpin" if pinned else "pin", "unpin" if pinned else "pin",
                            "Un-pin" if pinned else "Pin")
                 + _menu_item("move", "move", "Move")
                 + _move_out_items("Subtask")
                 + _menu_item("unarchive" if shelved else "archive",
                              "unarchive" if shelved else "archive",
                              "Unarchive" if shelved else "Archive"))
    parts.append(_menu_item("delete", "delete", "Delete", danger=True))
    said = " ".join(part for part in (one.get("num"), one.get("title")) if part)
    marks = (f' data-sub="{html.escape(sub, quote=True)}" data-item="{html.escape(page, quote=True)}"'
             f' data-name="{html.escape(said, quote=True)}"'
             f' data-title="{html.escape(str(one.get("title") or ""), quote=True)}"')
    return f'<span class="sdots"{marks}>{_dots_menu(said, parts, "odots srow-dots")}</span>'


def _folder_listing(root, rel: str, name: str, path: Path, person=None) -> str:
    """What one folder of an object holds, one line each: folders, then files.

    Every line opens what it names the way a line of Documents does: a folder
    or a file here, to read, and a page as the page it is.
    """
    from . import attachments

    try:
        with os.scandir(path) as found:
            entries = [e for e in found if _listed(e)]
    except OSError:
        entries = []

    def is_dir(entry) -> bool:
        try:
            return entry.is_dir(follow_symlinks=False)
        except OSError:
            return False

    entries.sort(key=lambda e: (not is_dir(e), e.name.lower()))
    rows = []
    for entry in entries[:FOLDER_MOST]:
        child, low = f"{name}/{entry.name}", entry.name.lower()
        if is_dir(entry):
            rows.append(_object_row("folder", doc_url(rel, child), entry.name,
                                    _holds(path / entry.name), _kind_pill("Folder")))
        elif low.endswith((".html", ".htm")):
            rows.append(_object_row("page", pages.url_for(f"{rel}/{child}"),
                                    pages.title_of(path / entry.name) or entry.name,
                                    entry.name, _kind_pill("Page")))
        elif low.endswith(".md"):
            rows.append(_object_row("md", doc_url(rel, child),
                                    _md_title(path / entry.name, entry.name)
                                    or entry.name, "", _kind_pill(".md")))
        else:
            try:
                size = attachments.human_size(entry.stat().st_size)
            except OSError:
                size = ""
            rows.append(_file_line(_object_row("file", doc_url(rel, child), entry.name,
                                               size, _kind_pill(_file_word(entry.name))),
                                   rel, child, person))
    if not rows:
        return "<p class=dnote>This folder is empty.</p>"
    more = (f'<p class="omore">and {len(entries) - FOLDER_MOST} more</p>'
            if len(entries) > FOLDER_MOST else "")
    return f'<div class="rows">{"".join(rows)}</div>{more}'


def _plain_file(path: Path) -> str:
    """A file that is neither notes nor a page, as the text it is.

    Escaped and in a block of its own, so code reads as code and nothing in it
    is ever markup. A file that is not text - a spreadsheet, a picture, a PDF -
    is said to be one rather than drawn as noise.
    """
    from . import attachments

    try:
        size = path.stat().st_size
        with open(path, "rb") as fh:
            data = fh.read(FILE_LONGEST)
    except OSError:
        return "<p class=dnote>This file could not be read.</p>"
    if not data:
        return "<p class=dnote>This file is empty.</p>"
    if b"\x00" in data[:8192]:
        return (f"<p class=dnote>This is not a text file ("
                f"{html.escape(attachments.human_size(size))}), so it is not drawn here."
                "</p>")
    cut = (f"<p class=dnote>The first {html.escape(attachments.human_size(FILE_LONGEST))} "
           f"of {html.escape(attachments.human_size(size))}.</p>"
           if size > FILE_LONGEST else "")
    text = data.decode("utf-8", "replace")
    return f'<pre class="otext"><code>{html.escape(text)}</code></pre>{cut}'


# What this module reads from `objectindex`, imported last: every function above
# reads these only when it is called, so this module and `objectindex` load in
# either order, and `objectindex` imports this one at its own bottom.
from .objectindex import (  # noqa: E402
    FILE_LONGEST, FOLDER_MOST, GOAL_DOC, MOST_LISTED, RUN_WORDS, _Under, _file_row, _holds,
    _its_emoji, _kind_pill, _listed, _md_title, _object_row, _section, _subtask_row, doc_url, log,
    stamp, task_files)
