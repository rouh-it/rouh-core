"""Projects for what is kept: their names, the project a chat is in, and a project's rules for its page.

Since 5 October 2026 what is kept is rules and notes in Synapse Master (`rouh/rules.py`), and since 30 October
2026 the person's own words are Vocabulary there (`rouh/vocabulary.py`); the
history below is how a note came to be filed under a project at all.

Petar, 24 September 2026, with a photograph of the screen: Rouh had answered
**"Kept: the Kvadrat joiner wants a thirty percent deposit by Monday."** and
the note was nowhere to be seen when he opened the Kvadrat project.

    Kept where? When I open the Kvadrat project, it is not there. Where is it
    saved? ... I know there is a universal db memory, but that should be
    either different than projects memory or the setup should be such that a
    column in the database says for which project that is.

It had gone into `facts`, which until that day was one flat list with no
project on it at all: the note was really there, under the label `kvadrat
joiner deposit`, and there was no screen anywhere that would have told him so.
"Kept" was the whole of what the model said, because "Remembered kvadrat
joiner deposit." was the whole of what the tool said back.

Three things follow from that, and this module is the first of them.

1. **A note is kept somewhere, and the somewhere is named.** `facts` carries
   `project_id` now, "" being the general memory (`rouh/models/memory.py`), and
   `keep` below answers with the place in words: *Remembered kvadrat joiner
   deposit, in the project Clients.* That sentence is what the model reads and
   is what it says back, so "Kept" on its own cannot happen again.
2. **The project is the one the conversation is in**, walked up from the chat
   through whatever owns it (`conversations._project_over`), or the one the
   person named out loud in the same breath - "note for Kvadrat" - found among
   the projects that really exist.
3. **Nothing is ever dropped for want of a project.** A name that fits no
   project, or two, still keeps the note, in the general memory, and says both
   things in one sentence. Losing what somebody asked to be kept, in order to
   ask them a tidying question, is the worse of the two failures by a long way.

Where a kept note can then be read: the Memory page under the person's own
name, which groups them by project, and the project's own page, which has a
Notes section of its own (`objectindex.build_task`).

Nothing here writes. `rouh/memory.py` is the store and knows nothing about
projects; `rouh/objects.py` is the projects and knows nothing about memory;
this is the one place that holds both, so neither has to import the other.
"""
from __future__ import annotations

import logging

log = logging.getLogger("rouh.keeping")

#: What a note with no project is called, in the one place the words are
#: written down. Said to the model and printed on the page.
GENERAL = "the general memory"


def _store():
    """The one store, or None when the object model is off or it will not open.

    None is not a failure here: with no object model there are no projects, so
    every note belongs to the general memory and every answer says so.
    """
    from . import objects

    return objects.shared_store()


def projects_now() -> dict[str, dict]:
    """Every project's id against its name and the folder its page is at.

    Read once per turn for the system prompt (`Memory.facts_block`) and once
    per page for the Memory page, rather than a lookup per note. The folder is
    "" for one of the person's own projects for chats, which has no page of
    its own to send anybody to.
    """
    st = _store()
    if st is None:
        return {}
    try:
        return {row.id: {"name": row.title or row.slug or row.id,
                         "folder": row.folder or ""}
                for row in st.list_projects(limit=500)}
    except Exception:
        log.exception("the projects could not be read for what is kept in them")
        return {}


def project_names() -> dict[str, str]:
    """Every project's id against what it is called. {} when there are none."""
    return {ident: one["name"] for ident, one in projects_now().items()}


def name_of(project_id: str) -> str:
    """What one project is called, or "" when there is no such project now."""
    project_id = (project_id or "").strip()
    if not project_id:
        return ""
    st = _store()
    if st is None:
        return ""
    row = st.get_project(project_id)
    return (row.title or row.slug or row.id) if row is not None else ""


def project_of_chat(chat_id: str) -> str:
    """The project the conversation is filed under, or "" for none.

    Walked up through whatever owns the chat, because a chat a task owns is in
    that task's project and has no link of its own to it
    (`conversations._project_over`).
    """
    chat_id = (chat_id or "").strip()
    if not chat_id:
        return ""
    try:
        from . import conversations

        return conversations.project_of("chat", chat_id)
    except Exception:
        log.exception("the project over chat %s could not be read", chat_id)
        return ""


def notes_of(project_id: str) -> list[dict]:
    """One project's rules (`rouh/rules.py`), and any of its old notes not yet moved, for its own page."""
    project_id = (project_id or "").strip()
    if not project_id:
        return []
    from .models.memory import Fact

    out: list[dict] = []
    try:
        from . import rules

        ds = rules.master()
        for r in rules.rules(ds) if ds else []:
            if any(f["type"] == "project" and f["id"] == project_id for f in r["for"]):
                out.append({"id": r["id"], "key": "", "value": r["text"], "created_at": r["made_at"],
                            "updated_at": r["changed_at"]})
    except Exception:
        log.exception("the rules of project %s could not be read", project_id)
    out += list(Fact.objects.filter(project_id=project_id)
                .order_by("-updated_at", "key")
                .values("id", "key", "value", "created_at", "updated_at"))
    return out


def unfile(project_id: str, label: str = "") -> int:
    """A deleted project's notes go back to the general memory. How many moved.

    Called where a person deletes a project (`objectindex._delete_project`),
    with what that project was called, because by then there is no row to read
    the name from. A note whose project went some other way is not lost either
    and needs no repair: a project id that names no project reads as the
    general memory everywhere it is read, on the page and in the prompt.
    """
    from . import runtime

    memory = getattr(runtime, "memory", None)
    if memory is None or not project_id:
        return 0
    moved = memory.unfile_facts(project_id, label)
    if moved:
        log.info("%d kept note(s) of project %s went back to the general memory",
                 moved, project_id)
    return moved
