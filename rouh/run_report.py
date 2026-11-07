"""What a finished run says in the chat it was started from, and how to get there.

Petar, 12 October 2026: "A run that was started through a chat should pass the
chat id. So that when the run completes the chat receives the report and the
notification has a link to the chat too."

The chat id is written on the run as it starts (`runs.came_from`, from the turn
that called the tool), and read back when it ends (`runs.report_chat`). What
goes into that chat is the report card the landers already draw - an answer, the
files it changed, a change to Rouh, why it stopped - with the same four facts at
its foot on every one of them, so a report reads the same however the run went:

* **Asked** - what it was asked to do, in the words of its brief.
* **Ended** - done, failed or stopped, and why when it did not simply finish.
* **Changed** - what it made: a page, a commit, files.
* **The run** - a link to the run's own page, where everything it said is.

The card is kept in the chat like any other (`artifacts.keep`), so it is there
whether or not anybody had Rouh open when the run finished; what Rouh says
about it is said there too when somebody does.

The notice for it, and the phone message when one is sent, lead to that chat
(`chat_link`): "/chat/<id>" inside the page, and the public address, the
form every other note to the phone uses, on the phone.

**And to everything else it is connected to.** Petar, 13 October 2026, from the
Gene therapy board (fr_677001efaa72): "When a run is complete, let's think
bigger. If it is in any way connected to the task system ... it should give me
all the buttons: Run, Chat, Task, Visual explainer ... I often want to see the
results (the HTML explainer) or open the task in general." So a run that
worked on a task, a subtask or a page in one carries every place it leads to
(`destinations`), in his order, each only where it is there: its notice draws
them as a row of buttons, one press each, and its report card links the task
beside the page and the run. A run that touched no task keeps its one link.

The last of those buttons says Page. Petar, 13 October 2026 (fr_fab4f066ea28): "For the
notifications, now there is a button visual explainer. Can you name it Page".
"""
from __future__ import annotations

import logging
import posixpath
from urllib.parse import quote

log = logging.getLogger("rouh.run_report")

#: How the run ended, in the word the card says it with.
DONE, FAILED, STOPPED = "done", "failed", "stopped"
ENDED_WORDS = {DONE: "Done", FAILED: "Failed", STOPPED: "Stopped"}

#: How much of the brief the card quotes. The brief is what the model handed
#: over, and can run to pages; the run's own page has all of it.
ASKED_MOST = 600
#: How many files are named before the rest are counted.
FILES_NAMED = 4


def chat_address(chat: str) -> str:
    """A conversation's address inside Rouh (`addressing`), or ""."""
    return f"/chat/{quote(str(chat), safe='')}" if chat else ""


def chat_link(public_url: str, chat: str) -> str:
    """A conversation's address from outside this machine, or "" without one."""
    base = str(public_url or "").rstrip("/")
    return f"{base}{chat_address(chat)}" if base and chat else ""


def run_address(run_id: str) -> str:
    """A run's own page inside Rouh (`addressing.KINDS`)."""
    return f"/run/{quote(str(run_id), safe='')}" if run_id else ""


def task_address(folder: str) -> str:
    """A task's, a subtask's or a workspace page's address inside Rouh, by its folder."""
    folder = str(folder or "").strip("/")
    return "/task/" + quote(folder, safe="/") if folder else ""


#: The four places a finished run can lead, in the order Petar listed them, each with the
#: word its button says. The page it made was "Visual explainer" until fr_fab4f066ea28.
RUN, CHAT, TASK, VISUAL = "run", "chat", "task", "visual"
LABELS = {RUN: "Run", CHAT: "Chat", TASK: "Task", VISUAL: "Page"}


def _in_workspace(rel: str) -> str:
    """A changed file as a path inside the workspace, or "" for one outside it.

    A run of the workspace names its files from the workspace's top already; a run of
    Rouh's own code names them from the repository's, where the workspace is `workspace/`.
    """
    from . import pages

    parts = [p for p in str(rel or "").strip().split("/") if p]
    if len(parts) > 1 and parts[0] == "workspace" and parts[1] in pages.TOPS:
        parts = parts[1:]
    if not parts or parts[0] not in pages.TOPS or ".." in parts:
        return ""
    return "/".join(parts)


def _task_folder(st, folder: str):
    """The deepest task or subtask whose folder holds `folder`, as (folder, row or None).

    A row first; a step folder no row has heard of yet is still a subtask with a page of
    its own (`objectindex._step_on_disk`), so one shaped like a step inside a task is taken
    as it is. ("", None) when no folder above it is one.
    """
    from . import steps

    parts = [p for p in str(folder or "").split("/") if p]
    while len(parts) > 1:
        here = "/".join(parts)
        row = st.by_folder("task", here) if st is not None else None
        if row is not None:
            return here, row
        if (steps._STEP_NAME.match(parts[-1]) and len(parts) > 2
                and steps._TASK_NAME.match(parts[-2])):
            return here, None
        parts.pop()
    return "", None


def _task_words(folder: str, row) -> str:
    """What the Task button opens, said in full for its hover and a screen reader."""
    title = str(getattr(row, "title", "") or "").strip()
    number = getattr(row, "number", None)
    name = posixpath.basename(folder)
    step = name.split(".", 1)[0] if "-" in name.split(".", 1)[0] else ""
    if step:
        what = f"step {step}"
    elif number is not None:
        what = f"task {number}"
    else:
        what = "the task"
    return f"Open {what}" + (f": {title}" if title else "")


def destinations(run_id: str, *, chat: str = "", page: str = "", files=()) -> list[dict]:
    """Every place a finished run leads, when it is connected to the task system, or [].

    Run, Chat, Task and Page, in that order, each a `{"to", "label", "href",
    "title"}` and each only where it is there: the chat it reports into (`runs.report_chat`,
    which is "" for a chat since deleted), the most specific task it worked on, and the page
    it made. Which task is the first of: the subtask its page is in, the deepest task its
    changed files are in, the task that owns the run, the task whose chat asked for it.

    [] when there is no task and no page, which leaves the run its one link as before.
    Never raises.
    """
    try:
        return _destinations(run_id, chat=chat, page=page, files=files)
    except Exception:
        log.exception("where run %s leads could not be worked out", run_id)
        return []


def _destinations(run_id: str, *, chat: str, page: str, files) -> list[dict]:
    from . import owning

    st = owning.store()
    page = _in_workspace(page) if page else ""
    made = [f for f in (_in_workspace(f) for f in files or ()) if f]
    if not page:
        # A page it made without saying so: a step's explainer, or a step's own page.
        html = [f for f in made if posixpath.basename(f).lower() in ("explainer.html",
                                                                      "index.html")
                and _task_folder(st, posixpath.dirname(f))[0]]
        html.sort(key=lambda f: (posixpath.basename(f).lower() != "explainer.html", f))
        page = html[0] if html else ""

    folder, row = ("", None)
    if page:
        folder, row = _task_folder(st, posixpath.dirname(page))
    if not folder and made:
        found = [_task_folder(st, posixpath.dirname(f)) for f in made]
        found = [f for f in found if f[0]]
        if found:
            folder, row = max(found, key=lambda f: (f[0].count("/"),
                                                   sum(1 for g in found if g[0] == f[0])))
    if not folder and st is not None and run_id:
        owner = st.owner_of("run", run_id)
        if owner and owner[0] == "task":
            row = st.get_task(owner[1])
            folder = str(getattr(row, "folder", "") or "") if row is not None else ""
    if not folder and chat:
        from . import conversations

        row = conversations.task_of(chat)
        folder = str(getattr(row, "folder", "") or "") if row is not None else ""

    if not folder and not page:
        return []
    out = [{"to": RUN, "label": LABELS[RUN], "href": run_address(run_id),
            "title": "Open the run: what it did and how it ended"}] if run_id else []
    if chat:
        from .conversations import GENERAL

        said = "General" if chat == GENERAL else "the chat it reported into"
        out.append({"to": CHAT, "label": LABELS[CHAT], "href": chat_address(chat),
                    "title": f"Open {said}"})
    if folder:
        out.append({"to": TASK, "label": LABELS[TASK], "href": task_address(folder),
                    "title": _task_words(folder, row)})
    if page:
        out.append({"to": VISUAL, "label": LABELS[VISUAL], "href": task_address(page),
                    "title": "Open the page it made"})
    return out


def asked(brief: str) -> str:
    """What a run was asked, from its brief: the request, without what Rouh added.

    Rouh adds sections of its own under the request - which task it belongs to
    (`starting.with_its_task`), the rules of its workspace - each under a
    heading of its own, so the request is what comes before the first of them.
    """
    text = str(brief or "").strip()
    cut = text.find("\n\n## ")
    if cut > 0:
        text = text[:cut].strip()
    text = " ".join(text.split())
    if len(text) > ASKED_MOST:
        text = text[: ASKED_MOST - 1].rsplit(" ", 1)[0].rstrip(",;:") + "…"
    return text


def changed(*, page: str = "", sha: str = "", files=(), branch: str = "",
            where: str = "") -> list[str]:
    """What a run made, as the lines the card lists, or [] for nothing."""
    out: list[str] = []
    if page:
        out.append(f"The page {page}")
    if sha:
        on = f"the branch {branch}" if branch else (f"{where}'s main" if where else "main")
        out.append(f"Commit {str(sha)[:7]} on {on}")
    files = [str(f) for f in files or () if f]
    if files:
        named = ", ".join(files[:FILES_NAMED])
        more = len(files) - FILES_NAMED
        count = f"{len(files)} file" + ("" if len(files) == 1 else "s")
        out.append(f"{count}: {named}" + (f" and {more} more" if more > 0 else ""))
    return out


def footer(run_id: str, *, ended: str, why: str = "", page: str = "", sha: str = "",
           files=(), branch: str = "", where: str = "", touched=()) -> list[dict]:
    """The four facts at the foot of a run's report card.

    `ended` is one of `DONE`, `FAILED` and `STOPPED`; `why` says what stopped
    it or what went wrong. `touched` is every file it changed, which says which
    task it worked on and is not listed. Never raises: a report without its
    foot is still a report.

    The links are the run's places (`destinations`) but its chat, which is the
    chat this card is in: the run, the task it worked on, the page it made.
    """
    blocks: list[dict] = []
    try:
        from . import runs

        row = runs.get(run_id)
        said = asked(getattr(row, "brief", "") if row is not None else "")
        if said:
            blocks.append({"block": "text", "label": "Asked", "text": said})
        how = ENDED_WORDS.get(ended, ended.capitalize() or "Ended")
        why = " ".join(str(why or "").split())
        blocks.append({"block": "text", "label": "Ended",
                       "text": f"{how}: {why}" if why else f"{how}."})
        made = changed(page=page, sha=sha, files=files, branch=branch, where=where)
        if made:
            blocks.append({"block": "list", "label": "Changed", "items": made})
        places = destinations(run_id, chat=runs.report_chat(run_id) if run_id else "",
                              page=page, files=list(touched or ()) or list(files or ()))
        if places:
            words = {RUN: "Open the run", TASK: "Open the task",
                     VISUAL: "Open the page"}
            for to in places:
                if to["to"] in words:
                    blocks.append({"block": "link", "text": words[to["to"]],
                                   "href": to["href"]})
            return blocks
        if page:
            blocks.append({"block": "link", "text": "Open the page",
                           "href": "/task/" + quote(str(page).strip("/"), safe="/")})
        if run_id:
            blocks.append({"block": "link", "text": "Open the run",
                           "href": run_address(run_id)})
    except Exception:
        log.exception("the foot of run %s's report could not be written", run_id)
    return blocks
