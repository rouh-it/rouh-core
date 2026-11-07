"""Files in Drive read: a PDF, Word, Excel or PowerPoint file kept in Google Drive is read like a document.

Built by the nightly feature run, night 31, 3 November 2026 (task 94, idea I-176). A client's
contract, a signed proposal, a report somebody sent as a PDF, a price list in Excel: most of what
arrives from outside a company is a file, not a Google Doc, and in Drive it stays one. `read_doc`
read Google Docs, Sheets and Slides, and anything that is text; a PDF or an Office file it refused
outright ("is a PDF and there is no way to read it as text"), so a chat, a job or Ask AI asked
about one could only say it could not open it, though the very same file attached to an email is
read in full (`rouh/mail_attachments.py`).

So, while its switch is on, `read_doc` on a file in Drive that is a PDF, a Word, Excel or
PowerPoint file (and their OpenDocument twins, RTF and HTML) downloads its bytes and reads the
words out of it with the reader every upload and every mail attachment already goes through
(`rouh/extracting.py`, in a process of its own, held to `uploads.EXTRACT_SECONDS`): page by page
for a PDF, headings, lists and tables kept for the rest. The line under the title says what kind
of file it was and that pictures in it are not read. A scan with no words in it, a file locked
with a password and one larger than `MOST_BYTES` are said plainly, never guessed at.

No model is asked. Nothing is written: the file is downloaded into a private folder for the
reader and is gone again the moment it is read.

**Whose.** The files the connected Google account can open (`org_id` and `user_id`), read with
that account's own token.

**Its switch** is `drive_files` (`rouh/switches.py`): off, such a file is refused as before.
"""
from __future__ import annotations

import asyncio
import logging
import os
import tempfile

log = logging.getLogger("rouh.drive_files")

SWITCH = "drive_files"
TITLE = ("Files in Drive read: a PDF, Word, Excel or PowerPoint file in Google Drive read like a "
         "document")

#: The largest file downloaded to be read, in bytes. A scanned book is not something a turn reads.
MOST_BYTES = 40 * 1024 * 1024

#: The file name's ending Drive's own type stands for, when the name has none.
ENDINGS = {
    "application/pdf": ".pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
    "application/vnd.oasis.opendocument.text": ".odt",
    "application/vnd.oasis.opendocument.spreadsheet": ".ods",
    "application/vnd.oasis.opendocument.presentation": ".odp",
    "application/rtf": ".rtf",
    "text/rtf": ".rtf",
}

#: How each kind of file is named to the person and the model.
KINDS = {".pdf": "PDF", ".docx": "Word document", ".docm": "Word document",
         ".xlsx": "Excel workbook", ".xlsm": "Excel workbook",
         ".pptx": "PowerPoint deck", ".pptm": "PowerPoint deck",
         ".odt": "OpenDocument text", ".ods": "OpenDocument spreadsheet",
         ".odp": "OpenDocument presentation", ".rtf": "RTF document",
         ".html": "web page", ".htm": "web page"}


def on(who) -> bool:
    from . import switches

    if who is None:
        return False
    return switches.on(SWITCH, getattr(who, "org_id", None) or None)


async def wanted(google) -> bool:
    """Whether read_doc should read such files for this person now."""
    who = google.person() if hasattr(google, "person") else None
    if who is None:
        return False
    return await asyncio.to_thread(on, who)


def file_name(about: dict) -> str:
    """The file's name with the ending its type stands for, so the reader knows what it is."""
    name = os.path.basename(str(about.get("name") or "")) or "file"
    ending = os.path.splitext(name)[1].lower()
    wanted_ending = ENDINGS.get(str(about.get("mime_type") or "").lower(), "")
    if wanted_ending and ending != wanted_ending and ending not in KINDS:
        name += wanted_ending
    return name


def readable(about: dict) -> bool:
    """Whether this file is one only this gene reads: a PDF, an Office file and their like."""
    from . import extracting

    name = file_name(about)
    if os.path.splitext(name)[1].lower() not in KINDS:
        return False
    return extracting.can_read(name, "pdf" if name.lower().endswith(".pdf") else "")


def kind_of(about: dict) -> str:
    return KINDS.get(os.path.splitext(file_name(about))[1].lower(), "file")


def _words(data: bytes, name: str) -> str | None:
    from . import uploads

    with tempfile.TemporaryDirectory(prefix="rouh-drivefile-") as folder:
        path = os.path.join(folder, name)
        with open(path, "wb") as out:
            out.write(data)
        return uploads.words_in(path, "pdf" if name.lower().endswith(".pdf") else "", name)


async def text_of(download, about: dict) -> str:
    """The words in one such file, given `download()` for its bytes. Raises `CannotDoThat`
    with the reason in plain words when there are none to give."""
    from .google_api import CannotDoThat

    name, kind = file_name(about), kind_of(about)
    size = int(about.get("size") or 0)
    if size > MOST_BYTES:
        raise CannotDoThat(f"{about.get('name')!r} is a {kind} of {size // (1024 * 1024)} MB, larger "
                           f"than the {MOST_BYTES // (1024 * 1024)} MB Rouh reads at once.")
    data = await download()
    if len(data) > MOST_BYTES:
        raise CannotDoThat(f"{about.get('name')!r} is a {kind} larger than the "
                           f"{MOST_BYTES // (1024 * 1024)} MB Rouh reads at once.")
    words = await asyncio.to_thread(_words, data, name)
    if words is None:
        raise CannotDoThat(f"{about.get('name')!r} is a {kind}, and reading it failed: it may be "
                           f"damaged, locked with a password, or not what its name says.")
    if not words.strip():
        raise CannotDoThat(f"{about.get('name')!r} is a {kind} with no words in it to read: it is "
                           f"most likely a scan or made only of pictures, and there is no OCR here.")
    return words


def line(found: dict) -> str:
    """The line under the title for a file this gene read, or ""."""
    kind = found.get("extracted") or ""
    if not kind:
        return ""
    return (f"A {kind} in Drive, its words read out of the file (pages divided by ---); pictures "
            f"and charts in it are not read.")


async def noted(google, found: dict) -> str:
    """The line for read_doc, with the use reported when there is one."""
    said = line(found)
    if not said:
        return ""
    who = google.person() if hasattr(google, "person") else None
    if who is not None:
        from . import evolution

        await asyncio.to_thread(evolution.used, SWITCH, "read", who=who,
                                detail=f"{found['extracted']}: {str(found.get('title') or '')[:80]}")
    return said


__all__ = ["SWITCH", "TITLE", "kind_of", "line", "noted", "on", "readable", "text_of", "wanted"]
