"""A copy made when asked: a document, sheet or deck in Drive copied, renamed, filed and filled in.

Built by the nightly feature run, night 31, 3 November 2026 (task 94, idea I-177). Work that
starts from something already made (last client's proposal, the statement-of-work template, the
deck of the last talk) starts with a copy of it, and Rouh could not make one: it could make a
new Google Doc of plain text (`create_doc`), so "make a copy of the Northwind proposal for Acme"
came back as a document with none of the original's headings, tables, pictures, comments' places
or layout, and a deck or a sheet could not be copied at all. Making the copy, naming it, moving it
into the client's folder and changing the old client's name in it was his to do in Drive.

So, while its switch is on, the tool **copy_drive_file** makes Drive's own copy of a file the
connected Google account can open (`files.copy`, so everything in it comes with it: styles,
tables, pictures, a deck's slides and speaker notes, a sheet's tabs and formulas):

- **named** as asked, or "Copy of ..." when no name is given;
- **filed** in the folder asked for (by name or id, on a shared drive too), or beside the original;
- **filled in**: for a Google Doc or a Slides deck, `fill` is a list of {find, put}, each replaced
  everywhere it stands in the copy, matched exactly with case (`replaceAllText`, one batch), so
  "Northwind" becomes "Acme" or "{{client}}" becomes a name. A sheet's copy is made as it is, and
  the answer says that its words were not changed. Words found nowhere in the copy are named.

The original is never changed. The copy is the person's own file and shared with nobody beyond
what its folder already gives; its answer gives its link, its id and what was filled in where.

**Whose.** The files and folders the connected Google account can open (`org_id` and `user_id`).
It copies only what ‹he› asked for in words, in a chat or a job of ‹his›; a document's own words
never ask for a copy.

**Its switch** is `drive_copy` (`rouh/switches.py`): off, the tool says so and makes nothing.
"""
from __future__ import annotations

import asyncio
import logging

log = logging.getLogger("rouh.drive_copy")

SWITCH = "drive_copy"
TITLE = ("A copy made when asked: a document, sheet or deck in Drive copied, renamed, filed and "
         "filled in")
TOOL_NAME = "copy_drive_file"
#: The most fill-ins one call makes.
MOST = 40
DOC = "application/vnd.google-apps.document"
DECK = "application/vnd.google-apps.presentation"
SHEET = "application/vnd.google-apps.spreadsheet"
FOLDER = "application/vnd.google-apps.folder"

DESCRIPTION = (
    "Make a copy of a file in the person's Google Drive: a Google Doc, Sheet or Slides deck, a PDF "
    "or any other file, with everything in it (styles, tables, pictures, slides, notes, tabs). Use "
    "it when the person asks for a copy ('make a copy of the Northwind proposal for Acme', 'copy "
    "last month's report into the December folder', 'start the SOW for Acme from the template'). "
    "`file` is the file's link, id or name; `name` what the copy is called (else 'Copy of ...'); "
    "`folder` where it goes, by name or id (else beside the original), with `drive` for a shared "
    "drive. `fill` is a list of {find, put}: words replaced everywhere in the copy, matched "
    "exactly with case, for a Google Doc or a Slides deck only - read the original with read_doc "
    "first so `find` is the words exactly as they stand. The original is never changed. Say back "
    "the copy's name and link and what was filled in.")
SCHEMA = {
    "type": "object",
    "properties": {
        "file": {"type": "string", "description": "The file to copy: its link, its id or its name."},
        "name": {"type": "string", "description": "What the copy is called."},
        "folder": {"type": "string", "description": "The folder the copy goes into, by name or id."},
        "drive": {"type": "string", "description": "The shared drive that folder is on, by name or id."},
        "fill": {"type": "array", "description": "Words to replace in the copy (Docs and decks).",
                 "items": {"type": "object",
                           "properties": {"find": {"type": "string"}, "put": {"type": "string"}},
                           "required": ["find", "put"]}},
    },
    "required": ["file"],
}


def on(who) -> bool:
    from . import switches

    if who is None:
        return False
    return switches.on(SWITCH, getattr(who, "org_id", None) or None)


def fills(args: dict) -> tuple[list[dict], str]:
    """The fill-ins asked for, cleaned, or the reason they cannot be made."""
    out = []
    for one in (args or {}).get("fill") or []:
        if not isinstance(one, dict):
            continue
        find, put = str(one.get("find") or ""), str(one.get("put") or "")
        if not find.strip():
            return [], "Each fill-in needs the words to find, exactly as they stand in the file."
        if find == put:
            continue
        out.append({"find": find, "put": put})
    if len(out) > MOST:
        return [], f"At most {MOST} fill-ins at once."
    return out, ""


def requests_for(asked: list[dict]) -> list[dict]:
    """One replaceAllText each, the same shape for the Docs and the Slides API."""
    return [{"replaceAllText": {"containsText": {"text": one["find"], "matchCase": True},
                                "replaceText": one["put"]}} for one in asked]


async def answer(google, args: dict) -> str:
    """What copy_drive_file says, having made the copy asked for."""
    from . import evolution
    from .tools import _find_doc, _google_trouble

    blocked = google.not_ready_because()
    if blocked:
        return blocked
    who = google.person()
    if who is None or not await asyncio.to_thread(on, who):
        return "Copying a file in Drive is switched off (Evolution, Mutations: A copy made when asked)."
    named = str((args or {}).get("file") or "").strip()
    if not named:
        return "Say which file to copy, by its link, its id or its name."
    asked, why_not = fills(args or {})
    if why_not:
        return why_not
    services = google.services()
    drive = services.drive
    try:
        file_id, _kind = await _find_doc(drive, named)
        about = await drive.metadata(file_id)
    except Exception as exc:  # noqa: BLE001 - said in Google's words
        return _google_trouble(exc)
    mime = about.get("mime_type") or ""
    if mime == FOLDER:
        return f"{about.get('name')!r} is a folder: only a file is copied here, not a whole folder."
    if about.get("trashed"):
        return f"{about.get('name')!r} is in the Drive bin; take it out of the bin first to copy it."
    if asked and mime not in (DOC, DECK):
        kind = "Google Sheet" if mime == SHEET else (about.get("type") or "file")
        return (f"{about.get('name')!r} is a {kind}: words are filled in only in a Google Doc or a "
                f"Slides deck. Ask for the copy without fill-ins, or name a Doc or a deck.")
    name = str((args or {}).get("name") or "").strip() or f"Copy of {about.get('name') or 'the file'}"
    folder_said, parent = "", ""
    folder = str((args or {}).get("folder") or "").strip()
    try:
        if folder:
            on_drive = ""
            if str((args or {}).get("drive") or "").strip():
                on_drive = await drive.shared_drive_id(str(args["drive"]).strip())
            parent = await drive.folder_id(folder, drive_id=on_drive)
            folder_said = f" in the folder {folder!r}"
        made = await drive.copy(file_id, name, parent=parent)
    except Exception as exc:  # noqa: BLE001 - nothing was made, said in Google's words
        return _google_trouble(exc) + " No copy was made."
    lines, missing = [], []
    if asked:
        try:
            api = services.docs if mime == DOC else services.slides
            got = await api.batch_update(made["id"], requests_for(asked))
            replies = (got or {}).get("replies") or []
            for one, reply in zip(asked, replies + [{}] * (len(asked) - len(replies))):
                n = int(((reply or {}).get("replaceAllText") or {}).get("occurrencesChanged") or 0)
                if n:
                    lines.append(f"«{one['find']}» became «{one['put']}» in {n} place{'s' if n != 1 else ''}")
                else:
                    missing.append(f"«{one['find']}»")
        except Exception as exc:  # noqa: BLE001 - the copy stands; the fill-ins are said not made
            log.info("the copy %s was made but not filled in: %r", made.get("id"), exc)
            lines.append("the fill-ins could not be made (" + _google_trouble(exc)
                         + "), so the copy says what the original says")
    said = (f"Made {made['name']!r}, a copy of {about.get('name')!r}{folder_said or ' beside the original'}"
            f" - file id {made['id']}" + (f", {made['link']}" if made.get("link") else "") + ".")
    if lines:
        said += " Filled in: " + "; ".join(lines) + "."
    if missing:
        said += (" Not found in it, so not changed: " + ", ".join(missing)
                 + ". Read the copy with read_doc to see the exact words.")
    if mime == SHEET:
        said += " It is a sheet, so its words are as the original's."
    said += " The original was not changed."
    google.wrote(TOOL_NAME, made["id"], said)
    await asyncio.to_thread(evolution.used, SWITCH, "copied", who=who,
                            detail=f"{str(about.get('name') or '')[:60]} -> {name[:60]}"
                                   + (f", {len(lines)} filled in" if lines else ""))
    return said


__all__ = ["DESCRIPTION", "SCHEMA", "SWITCH", "TITLE", "TOOL_NAME", "answer", "fills", "on",
           "requests_for"]
