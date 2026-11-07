"""Files inside files read: a forwarded email (.eml) and a zip archive are read like any document.

Built by the nightly feature run, night 32, 4 November 2026 (task 94). Two of the commonest things
people attach are themselves wrappers of other things: an email forwarded "as attachment" (a .eml,
`message/rfc822`, which is how Outlook and Apple Mail forward by default, and how Gmail forwards
several at once) and a .zip of documents (a tender pack, a data room export, a month of invoices).
Rouh read neither. A .zip was named and refused ("nothing here can read the words out of a zip
archive"); a .eml was read as its raw MIME source, headers and base64 and all, so the email inside
was lost in noise and the files attached to it were not read at all. Asked about one, Rouh could
only say it could not see what was in it.

So, while its switch is on, the reader every upload, every mail attachment and every Drive file
goes through (`rouh/extracting.py`, in a process of its own, on a clock and a memory ceiling) also
reads these two:

- **A forwarded email**: its sender, recipients, date and subject, its words (the plain part, or
  the HTML part's words when there is no plain one), and then each file attached to it, named
  and, where it is a kind the reader knows, read, as its own section.
- **A zip archive**: the list of every file in it with its size, and then each file the reader
  knows, read, as its own section, at most `MOST_FILES` of them and `MOST_BYTES` unpacked in all.
  A file locked with a password is named, not read. Nothing is unpacked onto disk under the name
  it has in the archive: each file is written to a private folder under a safe name, read, and
  gone again.

One inside the other is read too (a .zip inside a forwarded email), `MOST_DEPTH` levels down.

No model is asked. Nothing is kept or sent anywhere.

**Whose.** Only what the person already has in front of Rouh: a file an email to them or to Rouh
brought, or one they uploaded. The reading happens on the machine.

**Its switch** is `inside_files` (`rouh/switches.py`): off, a .zip is refused and a .eml read as its
raw source, as before. The extracting process imports nothing from Django, so the switch is read in
Rouh and handed to it as `ENV` (`uploads.words_in`).
"""
from __future__ import annotations

import email
import email.policy
import os
import posixpath
import re
import tempfile
import zipfile

SWITCH = "inside_files"
TITLE = "Files inside files read: a forwarded email (.eml) and a zip archive read like any document"

#: The environment variable the extracting process is told the switch by: "1" or "0".
ENV = "ROUH_READ_INSIDE"

#: The endings this gene reads.
ENDINGS = (".eml", ".zip")

#: The most files of one archive read, in its order; the rest are only listed.
MOST_FILES = 25

#: The most bytes unpacked out of one archive in all, and out of any one file of it. An archive
#: that says a small file is gigabytes inside is a trap, not a document.
MOST_BYTES = 60 * 1024 * 1024
MOST_ONE = 25 * 1024 * 1024

#: How deep one wrapper inside another is read.
MOST_DEPTH = 3

_depth = 0


def on(org_id=None) -> bool:
    """Whether the switch is on, asked in Rouh (never in the extracting process)."""
    try:
        from django.apps import apps

        if not apps.ready:
            return False
        from . import switches

        return switches.on(SWITCH, org_id)
    except Exception:  # noqa: BLE001 - a reader without Django never reads these
        return False


def allowed() -> bool:
    """Whether these files may be read here: the extracting process is told; Rouh asks."""
    told = os.environ.get(ENV)
    if told in ("0", "1"):
        return told == "1"
    return on()


def named(name: str, media: str = "") -> str:
    """A file's name with .eml on it when it is an email that came without the ending."""
    name = name or "attachment"
    if (media or "").lower().split(";")[0].strip() == "message/rfc822" \
            and not name.lower().endswith(".eml"):
        return name + ".eml"
    return name


def is_one(name: str) -> bool:
    return os.path.splitext(name or "")[1].lower() in ENDINGS


def read_one(one: dict) -> bool:
    """Whether a mail attachment just read was one only this gene reads, with its switch on."""
    return allowed() and is_one(named(str(one.get("name") or ""), str(one.get("type") or "")))


def kind_of(name: str) -> str:
    ending = os.path.splitext(name or "")[1].lower()
    return {".eml": "forwarded email", ".zip": "zip archive"}.get(ending, "file")


def _size(n: int) -> str:
    for unit, step in (("GB", 1 << 30), ("MB", 1 << 20), ("KB", 1 << 10)):
        if n >= step:
            return f"{n / step:.1f} {unit}"
    return f"{n} bytes"


def _safe(name: str) -> str:
    base = posixpath.basename(str(name or "").replace("\\", "/"))
    base = re.sub(r"[^\w.\- ]+", "_", base).strip(" .") or "file"
    return base[:120]


def _inner(data: bytes, name: str, out) -> bool:
    """Read one file found inside another into `out`, under its own heading. True when read."""
    from . import extracting

    global _depth
    safe = _safe(name)
    read = extracting.reader_for(safe, "")
    if read is None:
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            return False
        if "\x00" in text[:4000]:
            return False
        read = extracting._plain
    if _depth >= MOST_DEPTH:
        return False
    _depth += 1
    try:
        with tempfile.TemporaryDirectory(prefix="rouh-inside-") as folder:
            path = os.path.join(folder, safe)
            with open(path, "wb") as fh:
                fh.write(data)
            mark = len(out.parts)
            try:
                read(path, out)
                if out.parts and not out.parts[-1].endswith("\n\n"):
                    out._add("\n\n")
            except extracting._Full:
                raise
            except Exception as exc:  # noqa: BLE001 - one damaged file does not end the rest
                del out.parts[mark:]
                out.size = sum(len(p) for p in out.parts)
                out.block(f"({safe} could not be read: {type(exc).__name__})")
            return True
    finally:
        _depth -= 1


def _body(msg) -> str:
    """The words of an email: its plain part, or the words of its HTML part."""
    plain = msg.get_body(preferencelist=("plain",))
    if plain is not None:
        try:
            return plain.get_content()
        except Exception:  # noqa: BLE001
            pass
    rich = msg.get_body(preferencelist=("html",))
    if rich is not None:
        try:
            from . import extracting

            words = extracting._Out()
            page = extracting._Html(words)
            page.feed(rich.get_content())
            page.close()
            page.flush()
            return words.text()
        except Exception:  # noqa: BLE001
            pass
    return ""


def read_eml(path: str, out) -> None:
    """A forwarded email: who, when, what about, its words, and its own files read."""
    with open(path, "rb") as fh:
        msg = email.message_from_binary_file(fh, policy=email.policy.default)
    out.block("A forwarded email")
    for field in ("From", "To", "Cc", "Date", "Subject"):
        value = msg.get(field)
        if value:
            out.block(f"**{field}:** {' '.join(str(value).split())}")
    out.block(_body(msg))
    files = []
    for part in msg.iter_attachments():
        name = part.get_filename() or ""
        media = part.get_content_type()
        if media == "message/rfc822":
            inner = part.get_payload()
            data = (inner[0] if isinstance(inner, list) and inner else inner)
            data = data.as_bytes() if hasattr(data, "as_bytes") else b""
            name = named(name or "forwarded", media)
        else:
            data = part.get_payload(decode=True) or b""
            name = name or "attachment"
        files.append((name, media, data))
    if not files:
        return
    out.block(f"Attached to it: {len(files)} file{'s' if len(files) != 1 else ''}")
    for name, media, data in files:
        out.block(f"- {name} ({media}, {_size(len(data))})")
    for name, media, data in files:
        if media.startswith("image/"):
            continue
        out.rule()
        out.block(f"## Attached to the forwarded email: {name}")
        if not _inner(data, name, out):
            out.block("(its words cannot be read here)")


def read_zip(path: str, out) -> None:
    """A zip archive: every file in it listed, and those the reader knows read."""
    with zipfile.ZipFile(path) as zf:
        entries = [one for one in zf.infolist() if not one.is_dir()
                   and not posixpath.basename(one.filename).startswith(("._", "."))
                   and "__MACOSX/" not in one.filename]
        out.block(f"A zip archive of {len(entries)} file{'s' if len(entries) != 1 else ''}")
        for one in entries[:500]:
            lock = ", locked with a password" if one.flag_bits & 0x1 else ""
            out.block(f"- {one.filename} ({_size(one.file_size)}{lock})")
        if len(entries) > 500:
            out.block(f"- and {len(entries) - 500} more")
        unpacked, read = 0, 0
        for one in entries:
            if read >= MOST_FILES:
                out.rule()
                out.block(f"(only the first {MOST_FILES} files were read)")
                break
            if one.flag_bits & 0x1 or one.file_size > MOST_ONE:
                continue
            if unpacked + one.file_size > MOST_BYTES:
                out.rule()
                out.block("(the rest is too large to unpack at once, and was not read)")
                break
            from . import extracting

            if extracting.reader_for(_safe(one.filename), "") is None \
                    and os.path.splitext(one.filename)[1].lower() not in (
                        ".txt", ".md", ".csv", ".json", ".xml", ".log", ".tsv", ".yaml", ".yml"):
                continue
            with zf.open(one) as fh:
                data = fh.read(MOST_ONE + 1)
            if len(data) > MOST_ONE:
                continue
            unpacked += len(data)
            out.rule()
            out.block(f"## In the archive: {one.filename}")
            if _inner(data, one.filename, out):
                read += 1
            else:
                out.block("(its words cannot be read here)")


__all__ = ["ENDINGS", "ENV", "SWITCH", "TITLE", "allowed", "is_one", "kind_of", "named", "on", "read_one",
           "read_eml", "read_zip"]
