"""The files an email carries out of this machine: which may go, and how big.

Petar, 25 September 2026: send_mail and draft_mail could only send a plain
text body, so a photo he dropped into the chat could not go with the email he
asked Rouh to write. Both now take `attachments`, and this is where each file
named there is found, checked and read.

**Which files.** Three places and nowhere else:

- `{data_dir}/attachments`, where every file dropped into a conversation is
  kept (`rouh/attachments.py`);
- the person's workspace (`config.assistant_repo`);
- `/tmp`, where a job or a tool leaves something it made to be sent.

Rouh runs as a service that can read the whole disk, so anything outside those
is refused, with a sentence that says where a file has to be. A path is judged
by where it really is, links followed, and judged again on the file that is
actually opened, so a link left in /tmp that points at the rest of the machine
sends nothing. A hidden file or folder is refused inside them too: `.git`,
`.env` and `.claude` are never what somebody means by "attach it".

**Named how.** A whole path; a path relative to the workspace, the way every
workspace tool names a file; or the bare name of a file attached in this
conversation, such as `IMG_8997.jpeg`, found among that conversation's own
files, the newest first. The model is told the path of every file the person
attaches (`attachments.anthropic_blocks`), so any of the three works.

**How big.** Gmail takes 25 MB on one message (`google_api.MAIL_LIMIT`). The
files are held to that by their size on disk before a byte of them is read,
and the whole message is held to it again once it is built
(`google_api.Gmail._compose`), because a file is a third bigger inside an
email than on disk.
"""
from __future__ import annotations

import mimetypes
import os
from dataclasses import dataclass

from . import attachments, filestore
from .config import config
from .google_api import MAIL_LIMIT

#: The one place outside Rouh's own folders a file may be sent from.
TMP = "/tmp"

#: The most files one email may name. A few photos and a document is what an
#: email carries; twenty is already more than anybody attaches by voice.
MOST_FILES = 20


class Refused(ValueError):
    """Why these files cannot go, in a sentence the person can be told."""


@dataclass
class File:
    """One file an email is to carry, found and checked, not yet read."""

    name: str
    #: Where it really is, every link followed.
    path: str
    size: int
    type: str
    #: Its record, when it is a file somebody attached in a conversation.
    record: dict | None = None


def roots() -> list[str]:
    """Every folder a file may be sent from, each as where it really is."""
    out = []
    for one in (filestore.root(), os.path.join(config.data_dir, "attachments"),
                config.assistant_repo, TMP):
        if one and os.path.realpath(one) not in out:
            out.append(os.path.realpath(one))
    return out


def where() -> str:
    """The folders files may be sent from, as a person reads them."""
    shown = roots()
    return ", ".join(shown[:-1]) + " or " + shown[-1] if len(shown) > 1 else shown[0]


def _root_of(real: str) -> str | None:
    for root in roots():
        if real == root or real.startswith(root.rstrip(os.sep) + os.sep):
            return root
    return None


def _name_and_size(one) -> tuple[str, int]:
    """A found file, a read one or a record, as its name and its size in bytes."""
    if isinstance(one, File):
        return one.name, one.size
    if "data" in one:
        return one.get("name") or "attachment", len(one.get("data") or b"")
    return one.get("name") or "attachment", int(one.get("size") or 0)


def said(files) -> str:
    """"IMG_8997.jpeg (5.6 MB) and plan.pdf (120 kB)", for files or read files."""
    parts = [f"{name} ({attachments.human_size(size)})"
             for name, size in map(_name_and_size, files or [])]
    if len(parts) < 2:
        return "".join(parts)
    return ", ".join(parts[:-1]) + " and " + parts[-1]


def too_big(total: int, files) -> str:
    """Why these files are too big for one email, with the sizes that say so."""
    files = list(files)
    limit = f"Gmail takes {MAIL_LIMIT // (1024 * 1024)} MB at most on one message"
    if len(files) == 1:
        name, size = _name_and_size(files[0])
        return (f"{name} is {attachments.human_size(size)}, and {limit}. Put it in Drive "
                "and send the link instead, or send a smaller one.")
    return (f"Those files come to {attachments.human_size(total)} - {said(files)} - and "
            f"{limit}. Send fewer of them, or put them in Drive and send the link.")


def names_of(raw) -> list[str]:
    """What the model passed as `attachments`, as a list of names.

    A single string is taken as one file rather than refused: it is what a
    model writes when there is only one, and the meaning is not in doubt.
    """
    if raw is None or raw == "":
        return []
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, (list, tuple)):
        raise Refused("attachments has to be a list of files, each a name or a path.")
    return [str(one).strip() for one in raw if str(one or "").strip()]


def find(names, chat: str, store) -> list[File]:
    """Each file named, found and checked, in the order named. Reads nothing.

    Raises `Refused` with the reason for the first one that cannot go; the
    caller says that nothing went, because one file refused is the whole
    email refused.
    """
    wanted = names_of(names)
    if len(wanted) > MOST_FILES:
        raise Refused(f"That is {len(wanted)} files, and one email carries {MOST_FILES} at "
                      "most. Put them in a .zip, or send them in more than one email.")
    out: list[File] = []
    for one in wanted:
        if os.path.isabs(one) or one.startswith("~"):
            found = _at(os.path.expanduser(one), one, store)
        elif "/" in one or os.sep in one:
            found = _at(os.path.join(config.assistant_repo or "", one), one, store)
        else:
            found = _in_conversation(one, chat, store)
        if all(found.path != was.path for was in out):
            out.append(found)
    total = sum(one.size for one in out)
    if total > MAIL_LIMIT:
        raise Refused(too_big(total, out))
    return out


def chats_of(chat: str) -> list[str]:
    """Where the files of this conversation are kept: it, then what it was forked from.

    The question that opens a fork was typed in the chat it forks from, and
    its files stay kept there (`Session.fork_and_ask`), so a fork's first
    picture is under its parent and not under the fork. Until 29 September
    2026 a file asked for by name in a fork was looked for in the fork alone
    and was not found (fr_40ca307722f1). And through a fork that was cut
    from its parent by becoming a task's chat, whose first question's files
    are still where it was typed (`forks.came_from`).
    """
    if not chat:
        return []
    from . import forks

    try:
        return list(reversed(forks.came_from(chat)))
    except Exception:
        return [chat]


def _in_conversation(name: str, chat: str, store) -> File:
    """A file attached in this conversation, by the name it was attached with."""
    records = []
    if store is not None:
        # The fork's own first, then its parent's before them, so the newest
        # of a name is the fork's (`hits[-1]` below).
        for here in reversed(chats_of(chat)):
            records.extend(store.listing(here))
    wanted = {name.lower(), attachments.safe_name(name).lower()}
    hits = [r for r in records if str(r.get("name") or "").lower() in wanted]
    if not hits:
        raise Refused(_missing(name, [str(r.get("name") or "") for r in records]))
    record = hits[-1]
    return _at(str(record.get("path") or ""), name, store, record=record)


def _missing(name: str, there: list[str]) -> str:
    if there:
        return (f"No file called {name} was attached in this conversation. The ones that "
                f"were: {', '.join(there[-10:])}. Or give the file's whole path.")
    return (f"No file called {name} was attached in this conversation. Give the file's "
            "whole path, or ask the person to drop it into the conversation.")


def _at(path: str, shown: str, store, *, record: dict | None = None) -> File:
    """One file by its path, checked to be somewhere a file may be sent from."""
    real = os.path.realpath(path) if path else ""
    root = _root_of(real) if real else None
    if root is None:
        raise Refused(f"{shown} is not somewhere a file may be emailed from. Only files "
                      f"under {where()} can be attached.")
    inside = os.path.relpath(real, root)
    if inside != "." and any(part.startswith(".") for part in inside.split(os.sep)):
        raise Refused(f"{shown} is a hidden file, or in a hidden folder, and those are "
                      "never emailed.")
    if not os.path.isfile(real):
        raise Refused(f"There is no file at {shown}.")
    size = os.path.getsize(real)
    if size == 0:
        raise Refused(f"{shown} is empty, so there is nothing in it to attach.")
    if record is None:
        record = _record_at(real, store)
    name = str((record or {}).get("name") or "") or os.path.basename(path) or "attachment"
    kind = (mimetypes.guess_type(name)[0] or (record or {}).get("media_type")
            or "application/octet-stream")
    return File(name=name, path=real, size=size, type=kind, record=record)


def _record_at(real: str, store) -> dict | None:
    """The record of an attached file named by its path, when it is one."""
    if store is None:
        return None
    if filestore.inside(real):
        # The one store every file lives in since 4 November 2026: the list says which it is.
        try:
            from .models.files import File

            for got in File.objects.filter(deleted_at__isnull=True,
                                           name=os.path.basename(real)):
                if os.path.realpath(got.path) == real:
                    return filestore.record_of(got)
        except Exception:  # noqa: BLE001
            return None
        return None
    parts = os.path.relpath(real, os.path.realpath(store.root)).split(os.sep)
    if len(parts) != 3 or parts[0] in ("..", "."):
        return None
    record = store.get(parts[0], parts[1])
    if record is None or os.path.realpath(str(record.get("path") or "")) != real:
        return None
    return record


def read(files: list[File]) -> list[dict]:
    """The files' bytes, as `google_api.Gmail` hangs them off a message.

    Opened without following a link at the last step, and the file that was
    opened is checked for where it is, so a file swapped for a link between
    `find` and here is refused rather than read.
    """
    out = []
    for one in files:
        data = _read_one(one)
        if data[:4].startswith(attachments.EXECUTABLE_MAGIC) or \
                os.path.splitext(one.name)[1].lower() in attachments.BLOCKED:
            raise Refused(f"{one.name} is a program, and Gmail will not send one.")
        out.append({"name": one.name, "type": one.type, "data": data})
    return out


def _read_one(one: File) -> bytes:
    try:
        fd = os.open(one.path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    except OSError:
        raise Refused(f"{one.name} could not be read.") from None
    try:
        # Linux says which file a descriptor really is; elsewhere the check in
        # `find` is the one there is.
        if os.path.isdir("/proc/self/fd") and \
                _root_of(os.path.realpath(f"/proc/self/fd/{fd}")) is None:
            raise Refused(f"{one.name} is not somewhere a file may be emailed from.")
        with os.fdopen(fd, "rb", closefd=False) as fh:
            data = fh.read(MAIL_LIMIT + 1)
    finally:
        os.close(fd)
    if len(data) > MAIL_LIMIT:
        raise Refused(too_big(len(data), [one]))
    return data


def together(already: list[dict], more: list[dict]) -> tuple[list[dict], list[dict]]:
    """Every file a draft is sent with, and which of them were added now.

    The files it already carries come first. A file named now is the same file
    as one of them when its name and its size are: "send it, with the photo"
    about a draft the photo is already on sends one photo, not two.
    """
    held = {(one.get("name"), len(one.get("data") or b"")) for one in already}
    added = []
    for one in more:
        key = (one.get("name"), len(one.get("data") or b""))
        if key not in held:
            held.add(key)
            added.append(one)
    return list(already) + added, added


__all__ = ["MOST_FILES", "TMP", "File", "Refused", "find", "names_of", "read", "roots",
           "said", "together", "too_big", "where"]
