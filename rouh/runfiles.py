"""The files a message to a run of the one program carries.

Petar, 29 September 2026 (fr_40ca307722f1): "After adding an image and
forking directly from General, the image is not landed". He dropped a
screenshot into a fork of General and asked Rouh to add it to a bug run. The
fork had it, and so did the model, which sent the run a sentence with the
picture's path in it (`one_say`). That path is in Rouh's own attachments
folder, which only Rouh's own group may open, so the run, which works as
another user, could not read the picture it was told about.

So `one_say` takes `attachments`, and this is where each one is found and
read. The bytes go to the one program with the message, which writes them
into the run's own `drops` folder (`one/drops.py`, the same place a file
dropped on a run's terminal goes) and ends the message with their paths.

**Which files.** Only ones dropped into a conversation: everything else a run
may read is in its own checkout already. Named by the name they were dropped
with, by the id the model is told, or by the whole path it is told; looked for
in this chat and then up the chats it was forked from, because the question
that opens a fork keeps its files under the chat it was typed in
(`forks.py`, `Session.fork_and_ask`).

**In what shape.** A run takes png, jpg, gif and webp pictures and a handful
of documents (`one/drops.py`). A .heic, or a picture too big to carry, goes
as the copy the model is shown (`Attachments.for_model`), which is a PNG or a
JPEG of the same picture.

**How big.** The program's socket reads one line of at most 8 MB, and the
files travel inside it in base64, a third bigger: so 5 MB in all.
"""
from __future__ import annotations

import base64
import os

from . import attachments, mailfiles

#: The most the files of one message may come to, in bytes, before base64.
MOST_BYTES = 5 * 1024 * 1024

#: The most files one message carries: what one drop on a terminal takes.
MOST_FILES = 10

#: The pictures a run takes as they are.
PICTURES = frozenset({"image/png", "image/jpeg", "image/gif", "image/webp"})


class Refused(ValueError):
    """Why these files cannot go to the run, in a sentence the person can be told."""


def find(names, chat: str, store) -> list[dict]:
    """Each file named, as {"name", "type", "data"} ready for the program."""
    try:
        wanted = mailfiles.names_of(names)
    except mailfiles.Refused as exc:
        raise Refused(str(exc)) from None
    if len(wanted) > MOST_FILES:
        raise Refused(f"That is {len(wanted)} files, and one message to a run carries "
                      f"{MOST_FILES} at most.")
    records: list[dict] = []
    for one in wanted:
        record = _record(one, chat, store)
        if all(record["path"] != was["path"] for was in records):
            records.append(record)
    out = [_carried(record, store) for record in records]
    total = sum(len(one["data"]) for one in out)
    if total > MOST_BYTES:
        raise Refused(f"Those files come to {attachments.human_size(total)}, and a message to "
                      f"a run carries {attachments.human_size(MOST_BYTES)} at most. Send "
                      "fewer of them at a time.")
    return out


def one(named, chat: str, store, *, kind: str = "file") -> dict:
    """The record of one file dropped into a conversation, by its name, its id or its path, the
    way `one_say` finds its attachments: for any tool of Rouh's that takes such a file (a contact's
    picture, `contact_picture`), so a picture the person dropped into the chat is never one Rouh can
    see and its tools cannot use. `kind` is what the file is to the tool, for what is said when the
    name finds nothing."""
    try:
        wanted = mailfiles.names_of([named] if isinstance(named, str) else named)
    except mailfiles.Refused as exc:
        raise Refused(str(exc)) from None
    if len(wanted) != 1:
        raise Refused(f"Name one {kind}, by the name it was dropped with, its id or its path.")
    if os.path.isabs(wanted[0]) or wanted[0].startswith("~"):
        record = mailfiles._record_at(os.path.realpath(os.path.expanduser(wanted[0])), store) \
            if store is not None else None
        if record is None:
            raise Refused(f"{wanted[0]} is not a file dropped into a conversation, so it cannot be "
                          f"used as the {kind}.")
        return record
    return _record(wanted[0], chat, store)


def picture(record: dict, store) -> bytes:
    """A file dropped into a conversation as a picture's bytes Pillow opens: itself, or the copy the
    model is shown for a .heic and the like (`Attachments.for_model`). Refused when it is no picture."""
    media = str(record.get("media_type") or "")
    name = str(record.get("name") or "That file")
    if media in PICTURES or media in attachments.MODEL_PICTURES:
        return store.read(record)
    seen = (media in attachments.CONVERTIBLE or record.get("kind") == "image") \
        and store.for_model(record)
    if seen:
        return seen["data"] if isinstance(seen["data"], bytes) else base64.b64decode(seen["data"])
    raise Refused(f"{name} is not a picture.")


def wire(files: list[dict]) -> list[dict]:
    """The files as the program's `say` takes them: the data in base64."""
    return [{"name": f["name"], "type": f["type"],
             "data": base64.b64encode(f["data"]).decode("ascii")} for f in files]


def _record(named: str, chat: str, store) -> dict:
    """The record of one file dropped into this conversation, or a refusal."""
    if store is None:
        raise Refused("Files dropped into a conversation cannot be read here.")
    if os.path.isabs(named) or named.startswith("~"):
        record = mailfiles._record_at(os.path.realpath(os.path.expanduser(named)), store)
        if record is None:
            raise Refused(f"{named} is not a file dropped into a conversation. A run reads "
                          "its own checkout and the workspace itself, so give it the path "
                          "in the words instead.")
        return record
    if "/" in named or os.sep in named:
        raise Refused(f"{named} is a path, and a run reads its own checkout and the "
                      "workspace itself: give it the path in the words instead.")
    for here in mailfiles.chats_of(chat):
        record = store.get(here, named)
        if record is not None:
            return record
    try:
        return mailfiles._in_conversation(named, chat, store).record
    except mailfiles.Refused as exc:
        raise Refused(str(exc)) from None


def _carried(record: dict, store) -> dict:
    """One file as it goes to the run: itself, or the picture the model is shown."""
    name = str(record.get("name") or "attachment")
    media = str(record.get("media_type") or "")
    size = int(record.get("size") or 0)
    if media in PICTURES and size <= MOST_BYTES:
        return {"name": name, "type": media, "data": store.read(record)}
    picture = (media in attachments.CONVERTIBLE or record.get("kind") == "image") \
        and store.for_model(record)
    if picture:
        ext = ".png" if picture["media_type"] == "image/png" else ".jpg"
        return {"name": os.path.splitext(name)[0] + ext, "type": picture["media_type"],
                "data": picture["data"]}
    if size > MOST_BYTES:
        raise Refused(f"{name} is {attachments.human_size(size)}, and a message to a run "
                      f"carries {attachments.human_size(MOST_BYTES)} at most.")
    return {"name": name, "type": media, "data": store.read(record)}
