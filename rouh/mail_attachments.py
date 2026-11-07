"""The files an email brought in: named where the email is, read when asked.

Petar, 2 October 2026 (fr_bb4c40c00fa9): when trusted contacts asked Rouh for
something and attached the documents, the case reached him with a reply
asking whether they forgot to attach them. Gmail had said what was attached
(`google_api._attachments`) from the start; the case kept only the email's
addresses, subject and words (`mail_cases.kept_email`), its brief said nothing
of files, `read_mail` said nothing of them either, and there was no tool to
open one. So the model was told an email with no files, and said so.

Now every place an email is put in front of the model names its files - each
one's name, kind, size and part number - and nothing more (`listed`): a
hundred-page contract in every brief would crowd out the email it came with.
The model opens one when it needs it with `read_mail_attachment`, which reads
the words out of it here (`uploads.words_in`, the same reader every upload
goes through, in a process of its own and on a clock), a page at a time
(`PAGE`). What cannot be read is said plainly, with what it is, and never as
if nothing were there (`unread_said`).

What is read: PDF, Word, Excel, PowerPoint, OpenDocument, RTF, HTML and every
kind of plain text (`rouh/extracting.py`), and a forwarded email and a zip
archive while Files inside files read is on (`rouh/inside_files.py`). A picture,
a scan with no words in it, a recording and the old binary Office formats are
named and not read, and the model is told to say that rather than guess.
"""
from __future__ import annotations

import os
import tempfile
from collections import OrderedDict

from . import attachments, extracting

#: How much of a file's words one call hands back, in characters: about eight
#: thousand tokens, enough for most letters and contracts whole, and a page at
#: a time for the rest.
PAGE = 30_000

#: Files already read in this process, by (inbox, message id, part), so reading
#: on through a long one does not fetch and read it again for every page.
_READ: OrderedDict[tuple[str, str, str], tuple[dict, str | None]] = OrderedDict()
_KEEP = 8

#: Plain names for the kinds people attach, for a line the model and the owner read.
_KINDS = {
    "application/pdf": "PDF",
    "application/msword": "Word document (old .doc)",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "Word document",
    "application/vnd.ms-excel": "Excel spreadsheet (old .xls)",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "Excel spreadsheet",
    "application/vnd.ms-powerpoint": "PowerPoint (old .ppt)",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "PowerPoint",
    "application/vnd.oasis.opendocument.text": "OpenDocument text",
    "application/vnd.oasis.opendocument.spreadsheet": "OpenDocument spreadsheet",
    "application/zip": "zip archive",
    "text/csv": "CSV",
    "text/plain": "text",
    "text/html": "web page",
    "application/rtf": "RTF document",
}


def kind_said(media: str, name: str = "") -> str:
    """What sort of file this is, in a word or two."""
    media = (media or "").lower().split(";")[0].strip()
    if media in _KINDS:
        return _KINDS[media]
    if media.startswith("image/"):
        return "picture (" + media.split("/", 1)[1].upper() + ")"
    ext = os.path.splitext(name or "")[1].lstrip(".").upper()
    return f"{ext} file" if ext else (media or "file")


def size_said(size) -> str:
    return attachments.human_size(int(size or 0))


def kept(files) -> list[dict]:
    """The files of an email as a case keeps them: part, name, type and size."""
    return [{"part": str(one.get("part") or ""), "name": str(one.get("name") or "attachment"),
             "type": str(one.get("type") or "application/octet-stream"),
             "size": int(one.get("size") or 0)}
            for one in files or [] if isinstance(one, dict)]


def _name(one: dict) -> str:
    """The file's name, with .eml on an email that came without it while Files inside files read
    is on (`rouh/inside_files.py`)."""
    from . import inside_files

    name = str(one.get("name") or "")
    if inside_files.allowed():
        name = inside_files.named(name, str(one.get("type") or ""))
    return name


def readable(one: dict) -> bool:
    """Whether the words in this file can be read here at all."""
    return extracting.can_read(_name(one), _kind(one))


def line(one: dict) -> str:
    """One file, as one line: its name, what it is, its size and its part."""
    return (f"{one.get('name') or 'attachment'} ({kind_said(one.get('type'), one.get('name'))}, "
            f"{size_said(one.get('size'))}), part {one.get('part')}")


def listed(files, message_id: str) -> list[str]:
    """What a brief says of an email's files: each one named, and how to open it.

    Empty when there are none, so a brief without files is as it was.
    """
    files = kept(files)
    if not files:
        return []
    out = [f"Attached to email {message_id}: {len(files)} file{'s' if len(files) != 1 else ''}. "
           "They are there: never say that nothing was attached or ask whether they "
           "forgot to attach it."]
    for one in files:
        out.append("- " + line(one) + ("" if readable(one) else
                                       ": its words cannot be read here"))
    out.append(f"Their contents are not given here. When what they want depends on a "
               f"file, open it with read_mail_attachment (message_id {message_id} and the "
               "file's part) and answer from what is in it. If a file cannot be read - a "
               "picture, a scan, a format nothing here opens - say so plainly in what you "
               "report and in the reply, naming the file, rather than guessing what is in it.")
    return out


def _kind(one: dict, data: bytes = b"") -> str:
    """"pdf" or "text" when the file is one of those whatever it is called, else ""."""
    media = str(one.get("type") or "").lower()
    try:
        kind = attachments.classify(str(one.get("name") or ""), data, media)[2]
    except attachments.AttachmentError:
        return ""
    if kind in ("pdf", "text"):
        return kind
    if media == "application/pdf":
        return "pdf"
    return "text" if media.startswith("text/") else ""


def unread_said(one: dict, why: str) -> str:
    """The plain sentence for a file whose words could not be read."""
    return (f"{line(one)} is attached to the email, but {why} Say so plainly, naming the "
            "file, and never that nothing was attached; if what they want depends on it, "
            "ask them for it in a form that can be read (a PDF with text, a Word document, "
            "or the words in the email).")


def words_of(file: dict) -> str | None:
    """The words in one file Gmail handed over, as Markdown.

    "" when it has none, None when it could not be read. The file is written
    to a private folder for the reader and gone again the moment it is read.
    """
    from . import uploads

    from . import inside_files

    data = file.get("data") or b""
    name = attachments.safe_name(str(file.get("name") or "attachment")) or "attachment"
    if inside_files.allowed():
        # An email forwarded as an attachment may come with no .eml on its name.
        name = inside_files.named(name, str(file.get("type") or ""))
    kind = _kind(file, data)
    if not extracting.can_read(name, kind):
        return None
    with tempfile.TemporaryDirectory(prefix="rouh-mailfile-") as folder:
        path = os.path.join(folder, name)
        with open(path, "wb") as out:
            out.write(data)
        return uploads.words_in(path, kind, name)


def described(file: dict, part: str) -> dict:
    """A file Gmail handed over, as `kept` keeps one, and whether it can be read."""
    data = file.get("data") or b""
    return {"part": str(part), "name": str(file.get("name") or "attachment"),
            "type": str(file.get("type") or "application/octet-stream"), "size": len(data),
            "readable": extracting.can_read(_name(file), _kind(file, data))}


def remember(key: tuple[str, str, str], file: dict, words: str | None) -> None:
    _READ[key] = (file, words)
    _READ.move_to_end(key)
    while len(_READ) > _KEEP:
        _READ.popitem(last=False)


def recalled(key: tuple[str, str, str]) -> tuple[dict, str | None] | None:
    found = _READ.get(key)
    if found is not None:
        _READ.move_to_end(key)
    return found


def page(one: dict, words: str | None, start: int = 0) -> tuple[str, str]:
    """(Rouh's own line about the file, the words of it from `start`).

    The words are "" when there are none to give, and then the line says why.
    """
    if words is None:
        if str(one.get("type") or "").lower().startswith("image/"):
            return unread_said(one, "it is a picture, and only the words in documents can "
                                    "be read here, not pictures."), ""
        if not one.get("readable", readable(one)):
            return unread_said(one, "nothing here can read the words out of a "
                                    f"{kind_said(one.get('type'), one.get('name'))}."), ""
        return unread_said(one, "reading it failed: it may be damaged, protected with a "
                                "password, or not what its name says."), ""
    if not words.strip():
        return unread_said(one, "there are no words in it to read: it is most likely a "
                                "scan or made only of pictures, and there is no OCR here."), ""
    total = len(words)
    start = max(0, min(int(start or 0), total))
    if start >= total:
        return (f"{line(one)}: that is past its end. It has {total:,} characters of words.",
                "")
    end = min(total, start + PAGE)
    head = (f"{line(one)}, attached to the email. The words read out of it, as Markdown; "
            "its pictures and layout are not here. ")
    if start == 0 and end == total:
        head += f"This is all of it, {total:,} characters."
    else:
        head += f"Characters {start + 1:,} to {end:,} of {total:,}."
        if end < total:
            head += f" Read on with start {end}, only if you need more of it."
    return head, words[start:end]


__all__ = ["PAGE", "described", "kept", "kind_said", "line", "listed", "page", "readable", "recalled",
           "remember", "size_said", "unread_said", "words_of"]
