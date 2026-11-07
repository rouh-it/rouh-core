"""Files the person hands to Rouh: on disk, in the message, in front of the model.

Three separate problems live here, and keeping them in one file is deliberate
because getting any one of them wrong silently breaks the other two.

**On disk.** A browser can say anything it likes about a file. The name it sends
is never used as a path: the bytes go to
``{data_dir}/attachments/{session}/{id}/{safe name}`` where the id is ours and
the name has been stripped down to characters that cannot escape a directory.
The type is decided from the extension and then checked against the first few
bytes of the file, so a shell script called ``photo.png`` is refused rather than
stored and handed to something later.

**What is taken.** Everything, apart from programs. A list of allowed formats
is wrong the first time the person has a .heic or a .tar.gz in front of them,
so the rule is the other way round: ``BLOCKED`` is the short list of formats an
operating system runs when you open them, ``EXECUTABLE_MAGIC`` catches one that
has been renamed, and anything else is stored with the best media type that can
be worked out for it. What comes back out is never rendered on Rouh's own
address unless it is on the equally short ``INLINE_SAFE`` list, because an
uploaded .html or .svg is a document full of script and this origin holds the
person's session.

**In the message.** What is stored in the transcript is a small marker,
``{"type": "attachment", ...}``, not the file. A twenty megabyte screenshot
turned into base64 is twenty-seven megabytes of text, and putting that in the
messages table means every later turn replays it. So the database keeps a
pointer and the file stays the one copy of itself.

**In front of the model.** The marker is expanded just before the request goes
out, into whatever the model can actually read: an image block for a screenshot,
at its full size, with a line naming it, giving its size in pixels and saying
where it is saved - a .heic is kept as a JPEG from the moment it arrives, the
original beside it (`Attachments.save`), and a picture too big for one image
block is written again as one the API takes, never smaller than it has to be
(`Attachments.for_model`) - a document block for a PDF,
the text itself for anything that reads as text - markdown, html, csv, json,
source - and for a .docx, a spreadsheet or a deck the words read out of it as
Markdown, which is kept beside the file (`WORDS`, written by `rouh/uploads.py`).
For a .zip or a recording, and for anything whose words could not be read, it
is the name, the type, the size and the path on disk, because nothing here can
open those and a worker can.
Expansion is capped by total bytes, newest first, so a long conversation full of
screenshots cannot grow into a request that is refused for its size.
"""
from __future__ import annotations

import base64
import grp
import hashlib
import io
import json
import logging
import mimetypes
import os
import pwd
import re
import shutil
import time
import uuid

from . import filestore

#: The most one file may be. Half a gigabyte, since 23 October 2026, when
#: Petar's "call details.mov" came back 413 (fr_b9d6a78fa5d3): a few minutes of
#: a phone's video or a screen recording of a call, which is the biggest thing
#: a person hands over in a conversation without thinking. It was sixty-four
#: megabytes until then, set for a zipped folder of screenshots or a design
#: file. A file past IN_MEMORY is never held in memory whole
#: (`Attachments.save_upload`), so this is a limit of disk and patience, not of
#: this machine's memory.
#:
#: Whatever sits in front of this app has its own limit and it wins. On the
#: server that is nginx: `client_max_body_size` in the rouh site must be at
#: least this, or the upload is refused by the proxy with a page that never
#: mentions Rouh. verify.py checks that against the live site.
#:
#: The page is handed this number (`ATTACH_MAX` in index.html) and refuses a
#: bigger file before a byte of it goes up.
#:
#: This is not the same number as INLINE_BUDGET below, and it is bigger on
#: purpose. A file too big to put in front of the model is still stored, still
#: in the transcript, and still named to the model with its path, so a worker
#: can open it.
MAX_BYTES = 512 * 1024 * 1024

#: The biggest upload read into memory whole, which is what a picture needs to
#: be checked and written again. One bigger is judged by its first HEAD_BYTES
#: and copied to disk as it is.
IN_MEMORY = 64 * 1024 * 1024
HEAD_BYTES = 64 * 1024

#: How the attachment tree is written. These are the person's own screenshots
#: and documents, behind the person's sign-in, on a machine that several other Linux
#: users and several other sites share. Left to the umask they land 0664 and
#: 0775, which means every one of those users can read them: `os.makedirs` and
#: `open` take their permissions from the umask, and the umask here is 002.
#: So both are set outright rather than inherited.
#:
#: The group bit is not slack. A .docx is handed to a job by its path, because
#: nothing in this process can open one, and a screenshot is handed to a run
#: of the one program the same way, and both run as other users (`runuser -u
#: rouh`, `sudo -u assistant`). Closing the group out would make a file Rouh
#: had just promised to pass on unreadable to the only thing that could read
#: it. World access is what is being taken away, not the worker's. The group is
#: `config.attachments_group`, which holds exactly those users and opens
#: nothing but this tree.
#:
#: A directory is also set-group-id, so whatever lands in one keeps its group
#: even if it got there some other way than `_write`: a file copied in by
#: hand, or restored from a backup, is still readable by the runs.
#:
#: Neither mode has an execute bit on a file, and that is the reason a shell
#: script is an ordinary text file here: what is stored cannot be run, by
#: anyone.
DIR_MODE = 0o2750
FILE_MODE = 0o640

#: What every run and every worker is told about a file it is handed, as one
#: line of its brief's rules (`one/agents.py`, FILES_RULE, and `rouh/crew.py`,
#: FILES_INSTRUCTION). Written on 1 October 2026, after run 5fff87dd could not
#: open Petar's screenshot of "a bug with the filters", said so in a
#: parenthesis, and fixed the filter it guessed he meant. A picture is the
#: question itself; a run that has not seen it has not been asked yet.
WORKER_RULE = (
    "- A file the person attached - a screenshot, a photo, a document - is part of what "
    "they asked. Open every one you are given a path to, and look at each picture with "
    "your file reader before you decide anything. If one will not open (Permission "
    "denied, not found, unreadable), do not guess what it shows and do not carry on as if "
    "you had seen it: stop, say plainly which file you could not open and the error it "
    "gave, and ask the person to send it again or say what it shows. Work that does not "
    "depend on the file can go on meanwhile. The path you are given is where the file "
    "lives, the same for Rouh and for every job, and yours to change: open, fix, unzip or "
    "rename it there, never a copy elsewhere. `rouh-files list <task>` lists a task's "
    "files and `rouh-files add <file> <task>` puts one you made with them.")

#: What is kept in an attachment's folder besides the file itself: the record
#: that describes it, and the words read out of it as Markdown, which are what
#: a search reads (`rouh/uploads.py`) and never what anybody is shown.
#:
#: Neither can ever be the name of an upload. `safe_name` strips a leading dot,
#: so no upload is called `.extracted.md`; and an upload called `meta.json` is
#: stored as `_meta.json`, which `safe_name` could not have made either, while
#: keeping the name it came with. Until 24 September 2026 it was stored as
#: itself, and the record written after it took its place.
META = "meta.json"
WORDS = ".extracted.md"

#: The picture the model is shown, when it cannot be shown the file itself: a
#: .heic written again as a PNG or a JPEG, at its full size, kept beside the
#: file so it is made once rather than on every turn. Like WORDS it starts
#: with a dot, so no upload can ever be called it.
SEEN = ".seen"

#: The formats the Messages API takes as a picture. Anything else a picture
#: can be is written again as one of these before it is sent.
MODEL_PICTURES = frozenset({"image/png", "image/jpeg", "image/gif", "image/webp"})

#: Pictures the API does not take and Pillow can open: a screenshot or photo
#: from an iPhone or a Mac is a .heic. Each is shown to the model written
#: again as a PNG or a JPEG at its full size (`Attachments.for_model`). Petar,
#: 27 September 2026: "I want to make sure you have the full image not a
#: blurry thumbnail". Until then a .heic reached the model as a sentence
#: saying nothing here could open it, and it saw no picture at all.
CONVERTIBLE = frozenset({"image/heic", "image/heif", "image/avif", "image/bmp",
                         "image/tiff"})

#: What a picture in one of those formats is kept as from the moment it
#: arrives (`Attachments.save`): the same picture as a JPEG or a PNG, at its
#: full size, which the page draws in any browser and the model is shown like
#: any other picture. The file as it came is kept beside it under this name
#: and its own extension, because a .heic carries more than the JPEG does and
#: nothing the person hands over is thrown away. Petar, 29 September 2026,
#: "iPhone photos the model can see": until then a .heic was stored as a file,
#: drawn in the chat as the word HEIC, and task 55's receipts were converted
#: by hand before anything could read them.
ORIGINAL = ".original"

#: The most pixels a picture written on arrival is tried as a PNG first. A
#: phone's screenshot is under four megapixels and is text, which a PNG keeps
#: exactly; a photo is twelve or more, and its PNG is always over what one
#: picture may be, so trying it is seconds of work thrown away.
PNG_PIXELS = 4_500_000

#: Said on the file's chip, and to the model, when a picture in one of those
#: formats could not be opened. It is still kept, as a file, so a job can
#: have it; what the person must not be left thinking is that it was seen.
NOT_SEEN = ("{name} could not be opened as a picture, so I cannot see it. It is "
            "attached as a file. Send it again as a JPEG or a PNG: on an iPhone, "
            "a screenshot of it, or Settings > Camera > Formats > Most Compatible.")

#: The most one picture may be, as the API counts it. It refuses an image
#: over 5 MB, and the refusal fails the whole turn, so a picture is held to
#: this in base64, which is four bytes for every three.
PICTURE_BYTES = 5 * 1024 * 1024 * 3 // 4 - 4096

#: The longest side the API takes, in pixels. A picture longer than this is
#: the only one that is ever made smaller before it is sent.
PICTURE_SIDE = 8000

#: How much of a text file is put in the message before it is cut. Forty
#: thousand characters is roughly ten thousand tokens: enough for a long README
#: or a spreadsheet exported as CSV, and not enough to push a conversation out
#: of its context on one paste.
TEXT_LIMIT = 40_000

#: How many raw bytes of attachments one request may carry. The Messages API
#: refuses a request over 32 MB, and base64 is four bytes for every three, so
#: 20 MB of files is about 27 MB on the wire and leaves room for the rest of
#: the conversation. Everything is expanded newest first and anything past this
#: becomes a line of text saying where the file is, so an old screenshot - or a
#: file bigger than one request can hold at all - degrades into a note instead
#: of making the whole turn fail.
INLINE_BUDGET = 20 * 1024 * 1024

#: The only files that are refused for what they are, and the reason the rest
#: are not.
#:
#: A list of what is allowed is a list that is wrong the first time the person
#: has a .heic, a .pptx or a .tar.gz in front of them, and being told "images
#: and documents only" about their own working file is the kind of small
#: refusal that makes a tool not worth opening. So everything is taken, and
#: this is what is not.
#:
#: These are the formats an operating system runs when you open them. Rouh
#: never runs anything it is given and nothing written here has an execute bit
#: (FILE_MODE above), so the danger is not to this machine: it is that a file
#: which came in through a chat and went out through a download is a program
#: somebody double-clicks. A shell script is deliberately not on this list -
#: it is source, it is text, people paste them all day - and it is stored
#: without the bit that would let it run.
BLOCKED: frozenset[str] = frozenset({
    # Windows
    ".exe", ".com", ".scr", ".pif", ".msi", ".msp", ".cpl", ".msc", ".sys",
    ".drv", ".dll", ".ocx", ".bat", ".cmd", ".vbs", ".vbe", ".jse", ".wsf",
    ".wsh", ".hta", ".lnk",
    # Linux and macOS
    ".so", ".dylib", ".app", ".appimage", ".deb", ".rpm", ".dmg", ".pkg",
    # run by a runtime rather than by the kernel, and run all the same
    ".jar", ".apk", ".ipa",
})

#: What a program looks like from the first few bytes, whatever it is called.
#: The extension came from the browser; these did not. This is what stops
#: `notes.txt` that is really a Windows binary.
EXECUTABLE_MAGIC: tuple[bytes, ...] = (
    b"MZ",                                       # Windows .exe and .dll
    b"\x7fELF",                                  # Linux
    b"\xfe\xed\xfa\xce", b"\xfe\xed\xfa\xcf",  # macOS, big endian
    b"\xce\xfa\xed\xfe", b"\xcf\xfa\xed\xfe",  # macOS, little endian
    b"\xca\xfe\xba\xbe",                       # several architectures in one file
)

#: extension -> (media type, kind). The kind is what decides how the file
#: reaches the model, and it is the only thing the rest of this file branches
#: on: "image", "pdf", "text", "file".
#:
#: This table is not the list of what may be attached - anything not in it is
#: taken too, and worked out from its bytes and its extension by `classify`.
#: It is here so that the common formats get the right media type and the
#: right treatment rather than a guess.
TYPES: dict[str, tuple[str, str]] = {
    # Pictures the model can look at and the page can show.
    ".png": ("image/png", "image"),
    ".jpg": ("image/jpeg", "image"),
    ".jpeg": ("image/jpeg", "image"),
    ".gif": ("image/gif", "image"),
    ".webp": ("image/webp", "image"),
    # Pictures a browser cannot draw and the Messages API does not take: it
    # takes png, jpeg, gif and webp and nothing else. Each is kept as a JPEG
    # or a PNG from the moment it arrives (ORIGINAL, `Attachments.save`). Only
    # one that could not be opened keeps this kind, "file", so the page never
    # puts it in an <img>; and one kept before 29 September 2026 is still
    # shown to the model written again (`Attachments.for_model`).
    ".heic": ("image/heic", "file"),
    ".heif": ("image/heif", "file"),
    ".avif": ("image/avif", "file"),
    ".bmp": ("image/bmp", "file"),
    ".tif": ("image/tiff", "file"),
    ".tiff": ("image/tiff", "file"),
    ".ico": ("image/x-icon", "file"),
    # An SVG is a picture that is really a document full of script. It is read
    # as text, which is useful, and it is never rendered on Rouh's own origin
    # - see INLINE_SAFE below.
    ".svg": ("image/svg+xml", "text"),

    ".pdf": ("application/pdf", "pdf"),

    # Words, markup and data: read and put in the message as themselves.
    ".txt": ("text/plain", "text"),
    ".text": ("text/plain", "text"),
    ".md": ("text/markdown", "text"),
    ".markdown": ("text/markdown", "text"),
    ".rst": ("text/x-rst", "text"),
    ".csv": ("text/csv", "text"),
    ".tsv": ("text/tab-separated-values", "text"),
    ".json": ("application/json", "text"),
    ".jsonl": ("application/json", "text"),
    ".xml": ("application/xml", "text"),
    ".html": ("text/html", "text"),
    ".htm": ("text/html", "text"),
    ".rtf": ("application/rtf", "text"),

    # Office and the rest of the document formats. Nothing in this process can
    # open one, so they arrive as a path a worker can be pointed at.
    ".doc": ("application/msword", "file"),
    ".docx": ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", "file"),
    ".xls": ("application/vnd.ms-excel", "file"),
    ".xlsx": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "file"),
    ".ppt": ("application/vnd.ms-powerpoint", "file"),
    ".pptx": ("application/vnd.openxmlformats-officedocument.presentationml.presentation", "file"),
    ".odt": ("application/vnd.oasis.opendocument.text", "file"),
    ".ods": ("application/vnd.oasis.opendocument.spreadsheet", "file"),
    ".odp": ("application/vnd.oasis.opendocument.presentation", "file"),
    ".pages": ("application/x-iwork-pages-sffpages", "file"),
    ".numbers": ("application/x-iwork-numbers-sffnumbers", "file"),
    ".key": ("application/x-iwork-keynote-sffkey", "file"),
    ".epub": ("application/epub+zip", "file"),

    # Archives.
    ".zip": ("application/zip", "file"),
    ".tar": ("application/x-tar", "file"),
    ".gz": ("application/gzip", "file"),
    ".tgz": ("application/gzip", "file"),
    ".bz2": ("application/x-bzip2", "file"),
    ".xz": ("application/x-xz", "file"),
    ".7z": ("application/x-7z-compressed", "file"),
    ".rar": ("application/vnd.rar", "file"),

    # Sound.
    ".mp3": ("audio/mpeg", "file"),
    ".m4a": ("audio/mp4", "file"),
    ".wav": ("audio/wav", "file"),
    ".ogg": ("audio/ogg", "file"),
    ".oga": ("audio/ogg", "file"),
    ".opus": ("audio/opus", "file"),
    ".flac": ("audio/flac", "file"),
    ".aac": ("audio/aac", "file"),
    ".aiff": ("audio/aiff", "file"),
    ".wma": ("audio/x-ms-wma", "file"),

    # Moving pictures.
    ".mp4": ("video/mp4", "file"),
    ".m4v": ("video/mp4", "file"),
    ".mov": ("video/quicktime", "file"),
    ".webm": ("video/webm", "file"),
    ".mkv": ("video/x-matroska", "file"),
    ".avi": ("video/x-msvideo", "file"),
}

#: Source and configuration, all of it read as plain text. Kept apart from the
#: table above only because writing ("text/plain", "text") ninety times would
#: bury the formats that need a media type of their own.
CODE: tuple[str, ...] = (
    ".py", ".pyi", ".ipynb", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx",
    ".css", ".scss", ".sass", ".less", ".vue", ".svelte", ".astro",
    ".c", ".h", ".cc", ".cpp", ".cxx", ".hpp", ".cs", ".java", ".kt", ".kts",
    ".swift", ".go", ".rs", ".rb", ".php", ".pl", ".pm", ".lua", ".r", ".jl",
    ".m", ".mm", ".scala", ".clj", ".ex", ".exs", ".erl", ".hs", ".dart",
    ".sh", ".bash", ".zsh", ".fish", ".ps1", ".psm1", ".bashrc", ".profile",
    ".sql", ".graphql", ".proto", ".thrift",
    ".yaml", ".yml", ".toml", ".ini", ".cfg", ".conf", ".env", ".properties",
    ".gradle", ".mk", ".make", ".cmake", ".dockerfile", ".gitignore",
    ".editorconfig", ".diff", ".patch", ".log", ".tex", ".bib",
    ".tf", ".tfvars", ".hcl", ".srt", ".vtt", ".ics", ".vcf",
)
for _ext in CODE:
    TYPES.setdefault(_ext, ("text/plain", "text"))
del _ext

#: What the file picker offers: everything. What is refused is the short list
#: above, and a picker that offered only what is allowed would have to name
#: every format in the world. A person who cannot see their own file in the
#: picker has no way to find out why, which is worse than being told on the
#: chip a second later.
ACCEPT = "*/*"

#: The media types Rouh will let a browser render in place, on its own
#: address. Everything else is handed over as a download with a type that
#: makes the browser save it rather than open it.
#:
#: This is the whole of the HTML and SVG answer. Both are documents full of
#: script, and a script that runs on Rouh's own origin is inside the
#: person's signed-in session: it can read the conversation and act as them.
#: Neither is on this list, so neither is ever a page the browser runs. They
#: are still stored whole, still read as text in front of the model, and still
#: downloadable - what they cannot be is executed by the browser here.
INLINE_SAFE: frozenset[str] = frozenset({
    "image/png", "image/jpeg", "image/gif", "image/webp",
    "application/pdf", "text/plain",
})

#: The first bytes each format starts with. A file whose name says one thing and
#: whose content says another is refused: the name came from the browser and the
#: bytes did not. The one exception is a picture called by another picture's
#: name, which is renamed instead (`picture_named_truly`).
MAGIC: dict[str, tuple[bytes, ...]] = {
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/gif": (b"GIF87a", b"GIF89a"),
    "application/pdf": (b"%PDF",),
    # .docx and .xlsx are zip files, and so is every other Office format; this
    # only proves it is not a script that has been renamed.
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": (b"PK\x03\x04",),
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": (b"PK\x03\x04",),
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": (b"PK\x03\x04",),
}

#: What the first bytes say a file is when its name says nothing useful. Only
#: the formats it is worth knowing about: a picture the model can look at, and
#: a PDF it can read.
SNIFF: tuple[tuple[bytes, str, str], ...] = (
    (b"\x89PNG\r\n\x1a\n", "image/png", "image"),
    (b"\xff\xd8\xff", "image/jpeg", "image"),
    (b"GIF87a", "image/gif", "image"),
    (b"GIF89a", "image/gif", "image"),
    (b"%PDF", "application/pdf", "pdf"),
)

log = logging.getLogger("rouh.attachments")

#: Said once per message rather than once per file. A data directory whose
#: owner is wrong is one fact about the machine, and it would otherwise be
#: repeated on every screenshot for as long as the process runs.
_said: set[str] = set()


def log_once(message: str, *args) -> None:
    if message in _said:
        return
    _said.add(message)
    log.warning(message, *args)


def _gid_of(user: str | None, group: str | None = None) -> int | None:
    """The group the attachment tree is given to, or None to leave it alone.

    `group` is asked first: the group made for this tree alone, whose members
    are every user a file is handed to. A machine without it falls back to the
    primary group of `user`, the crew's, which is how it was until 1 October
    2026. None is the ordinary case on a laptop, where jobs run as whoever
    runs the app and there is no second user to let in.
    """
    if group:
        try:
            return grp.getgrnam(group).gr_gid
        except KeyError:
            log_once("no group called %r on this machine, so the one program's runs "
                     "cannot open attachments; `python manage.py attachments_access` "
                     "makes it", group)
    if not user:
        return None
    try:
        return pwd.getpwnam(user).pw_gid
    except KeyError:
        pass
    try:
        return grp.getgrnam(user).gr_gid
    except KeyError:
        log_once("no user or group called %r on this machine, so attachments "
                 "are readable only by the app itself", user)
        return None


class AttachmentError(ValueError):
    """Something the person needs to read, not a stack trace.

    Every message raised here is shown on the chip for the file that failed, so
    it says what was wrong with that file and what would work instead.
    """


def human_size(n: int) -> str:
    if n < 1024:
        return f"{n} bytes"
    if n < 1024 * 1024:
        return f"{n / 1024:.0f} kB"
    mb = n / (1024 * 1024)
    return f"{mb:.0f} MB" if mb == int(mb) else f"{mb:.1f} MB"


def safe_name(raw: str) -> str:
    """The client's name, reduced to something that can only ever be a filename.

    The path is thrown away before anything else, because "../../etc/passwd" and
    "C:\\Windows\\x.png" are both names a browser will send. What is left keeps
    letters, digits, space, dot, dash and underscore, and nothing else survives:
    that rules out separators, null bytes and the shell characters that would
    matter later when this path is handed to a job.
    """
    raw = (raw or "").replace("\\", "/")
    raw = raw.rsplit("/", 1)[-1].strip()
    raw = re.sub(r"[^A-Za-z0-9 ._-]+", "_", raw)
    raw = re.sub(r"\.{2,}", ".", raw).strip(" ._")
    if not raw:
        raw = "file"
    stem, dot, ext = raw.rpartition(".")
    if not dot:
        stem, ext = raw, ""
    return (stem[:80] or "file") + (("." + ext[:12]) if ext else "")


def safe_id(raw: str) -> str:
    """A session or attachment id as a single path segment, or "" if it is not one."""
    raw = (raw or "").strip()
    if not raw or len(raw) > 64 or not re.fullmatch(r"[A-Za-z0-9_-]+", raw):
        return ""
    return raw


def _looks_like_text(data: bytes | bytearray) -> bool:
    """Whether these bytes read as text, decided from the first 8 kB.

    A null byte anywhere in that window means no: no text file has one and
    every binary format has plenty. Otherwise it has to decode as UTF-8. The
    last four bytes of the window are dropped when there is more file after it,
    because a character cut in half at the edge of the window is not a reason
    to call a file binary, and no UTF-8 character is longer than four bytes.
    """
    head = data[:8192]
    if not head or b"\x00" in head:
        return False
    if len(data) > len(head):
        head = head[:-4]
    try:
        head.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


def _guessed_type(ext: str, declared: str) -> str:
    """A media type for a file TYPES has never heard of.

    Python's own table first, because it knows hundreds of formats this file
    has no reason to list. Then what the browser said, cleaned up, because for
    something exotic the browser is often right and is the only one who knows.
    Then the type that means "bytes", which is honest.

    The browser's word decides only what the file is *called*; it never decides
    how it is treated. That is `classify` below, from the bytes.
    """
    guess = mimetypes.guess_type("x" + ext)[0] if ext else None
    if guess:
        return guess
    said = re.sub(r";.*", "", declared or "").strip().lower()
    if (said and said != "application/octet-stream"
            and re.fullmatch(r"[a-z0-9.+-]+/[a-z0-9.+-]+", said)):
        return said
    return "application/octet-stream"


def classify(name: str, data: bytes | bytearray = b"",
             declared: str = "") -> tuple[str, str, str]:
    """(extension, media type, kind) for a file, refusing only what is a program.

    Everything else is taken. A format this file has never seen is still
    stored, still in the transcript and still named to the model with its path
    and its size, which is more use than a refusal.
    """
    ext = os.path.splitext(safe_name(name))[1].lower()
    if ext in BLOCKED:
        raise AttachmentError(
            f"{ext.lstrip('.')} files cannot be attached, because that is a program "
            "rather than a document. Everything else can: pictures, text, code, "
            "archives, sound, video. Put it in a .zip if the program itself is what "
            "you need me to have."
        )
    if data.startswith(EXECUTABLE_MAGIC):
        raise AttachmentError(
            f"{safe_name(name)} is a program inside, whatever it is called, so it "
            "was not attached. Put it in a .zip if that is what you need me to have."
        )
    if ext in TYPES:
        media, kind = TYPES[ext]
        return ext, media, kind
    for start, media, kind in SNIFF:
        if data.startswith(start):
            return ext, media, kind
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ext, "image/webp", "image"
    if _heif_type(data):
        return ext, _heif_type(data), "file"
    media = _guessed_type(ext, declared)
    # That type is a guess from a name or from the browser, and a guess that
    # the bytes disagree with is simply wrong. Being wrong about what a file is
    # called must never turn into refusing it, so the guess is dropped and the
    # file is taken as bytes.
    if not _magic_ok(media, data):
        media = "application/octet-stream"
    kind = "text" if (media.startswith("text/") or _looks_like_text(data)) else "file"
    return ext, media, kind


def serving(record: dict, download: bool = False) -> tuple[str, str]:
    """(media type, disposition) for handing one stored file back to a browser.

    The list of what may be rendered in place is INLINE_SAFE, and it is short.
    Anything else goes back as `application/octet-stream` with
    `Content-Disposition: attachment`, which no browser renders: an uploaded
    .html or .svg is a document full of script, and a script that ran here
    would be running inside the person's signed-in session, able to read the
    conversation and act as them.

    Saying `attachment` alone would not be enough on its own - a browser that
    sniffed the bytes could still decide it had HTML - so the type is neutered
    too, and the route adds `X-Content-Type-Options: nosniff` on top.
    """
    media = record.get("media_type") or "application/octet-stream"
    if download or media not in INLINE_SAFE:
        return "application/octet-stream", "attachment"
    return media, "inline"


def picture_named_truly(name: str, data: bytes | bytearray) -> str:
    """`name` with the extension its bytes say, when it is a picture called another picture.

    A phone names a picture before it has decided what to hand over: a
    screenshot dragged off an iPhone's thumbnail can say .png over JPEG bytes
    (Petar, 27 September 2026, "it understands I am trying to attach something
    but it gives me error"). A picture called by the wrong picture's name is
    still that picture, so it is renamed rather than refused. Anything else
    whose name and bytes disagree is still refused by `_check_magic`, because
    that is a program dressed as a document.
    """
    stem, ext = os.path.splitext(name)
    claimed = TYPES.get(ext.lower())
    if not claimed or not claimed[0].startswith("image/"):
        return name
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        truly = "image/webp"
    elif _heif_type(data):
        truly = _heif_type(data)
    else:
        truly = next((media for start, media, _ in SNIFF
                      if data.startswith(start) and media.startswith("image/")), "")
    if not truly or truly == claimed[0]:
        return name
    # A .heif, or an .avif whose box names the generic brand, is right as it is.
    if claimed[0] in CONVERTIBLE and truly in ("image/heic", "image/avif"):
        return name
    return stem + {"image/png": ".png", "image/jpeg": ".jpg", "image/gif": ".gif",
                   "image/webp": ".webp", "image/heic": ".heic",
                   "image/avif": ".avif"}[truly]


#: The brands an ISO media file names in its `ftyp` box when it is a picture
#: from a phone: HEIC is what an iPhone writes, AVIF what a browser saves.
_HEIF_BRANDS = {b"heic": "image/heic", b"heix": "image/heic", b"heim": "image/heic",
                b"heis": "image/heic", b"hevc": "image/heic", b"hevx": "image/heic",
                b"mif1": "image/heic", b"msf1": "image/heic",
                b"avif": "image/avif", b"avis": "image/avif"}


def _heif_type(data: bytes | bytearray) -> str:
    """image/heic or image/avif when these bytes are one, else "".

    Both start with an `ftyp` box at the fourth byte, and so does a video,
    which is why the brand is read too. An iPhone photo arrives as
    `IMG_1234.HEIC`, but one saved under another name, or with none, is still
    a photo.
    """
    if len(data) < 12 or data[4:8] != b"ftyp":
        return ""
    return _HEIF_BRANDS.get(bytes(data[8:12]), "")


def _magic_ok(media: str, data: bytes | bytearray) -> bool:
    """Whether the first bytes agree with the type this file claims to be.

    True for everything with no signature to check, because text formats have
    none and inventing one would be wrong.
    """
    if media == "image/webp":
        return len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP"
    starts = MAGIC.get(media)
    return any(data.startswith(s) for s in starts) if starts else True


def _check_magic(media: str, data: bytes | bytearray, name: str) -> None:
    if not _magic_ok(media, data):
        raise AttachmentError(
            f"{name} does not look like a {media.split('/')[-1]} file inside, "
            "so it was not attached."
        )


class _Streamed:
    """An upload too big to hold in memory: where it is, its first bytes, its size."""

    def __init__(self, source, head: bytes, size: int):
        self.source, self.head, self.size = source, head, size

    def __len__(self) -> int:
        return self.size


class Attachments:
    """The files for every conversation, one directory per conversation.

    `group` owns what is written here so that a path handed to a job or a run
    can still be opened by it; everyone else on the machine is shut out.
    `readable_by` is the Linux user that jobs run as, whose own group is used
    when there is no `group` on this machine. Both left out, the files are the
    app's own and nobody else's.
    """

    def __init__(self, data_dir: str, readable_by: str | None = None,
                 group: str | None = None):
        self.root = os.path.join(data_dir, "attachments")
        self.gid = _gid_of(readable_by, group)

    # --- writing ------------------------------------------------------------

    def _close_up(self, path: str, mode: int) -> None:
        """Set one path's permissions, and its group when there is one to set.

        Failures are swallowed on purpose: the file is written either way, and
        a data directory owned by someone else is a deployment to fix rather
        than a reason to refuse the person's screenshot.
        """
        # The group first: a change of owner may clear a set-group-id bit, so
        # the mode is set after it, and is the last word.
        if self.gid is not None:
            try:
                os.chown(path, -1, self.gid)
            except OSError:
                log_once("could not set the group on %s", path)
        try:
            os.chmod(path, mode)
        except OSError:
            log_once("could not set the permissions on %s", path)

    def _make_dir(self, path: str) -> None:
        """Create a directory and every level above it, each one closed up.

        `os.makedirs` applies its mode to the last directory it makes, and
        masks even that with the umask, so the levels above it would keep
        whatever the umask allowed. Each one this call creates is therefore set
        by hand. A level that was already there is left exactly as it is: its
        permissions are the machine's to decide, not this function's.
        """
        parts = []
        while path and not os.path.isdir(path):
            parts.append(path)
            path = os.path.dirname(path)
        for made in reversed(parts):
            os.makedirs(made, exist_ok=True)
            self._close_up(made, DIR_MODE)

    def _write(self, path: str, data: bytes | bytearray, mode: int = FILE_MODE) -> None:
        """Write one file that is never, even for an instant, world readable.

        Created through os.open with its mode rather than opened and chmod-ed
        afterwards: between those two calls the bytes are on disk and open to
        everyone, and a screenshot is exactly the thing not to leave lying
        there.
        """
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
        with os.fdopen(fd, "wb") as fh:
            if isinstance(data, _Streamed):
                data.source.seek(0)
                shutil.copyfileobj(data.source, fh, 1024 * 1024)
            else:
                fh.write(data)
        self._close_up(path, mode)

    def dir_for(self, session_id: str) -> str:
        sid = safe_id(session_id)
        if not sid:
            raise AttachmentError("That conversation has no id, so nothing could be saved.")
        return os.path.join(self.root, sid)

    def save_upload(self, session_id: str, filename: str, upload,
                    content_type: str = "") -> dict:
        """`save` for a file that came up in a request, read from where it was spooled.

        One of IN_MEMORY or less is read whole and saved as ever. A bigger one -
        a video, as a rule - is never held in memory at once: its first bytes
        are what it is judged by, and the whole of it is copied to disk.
        """
        size = int(getattr(upload, "size", 0) or 0)
        if size <= IN_MEMORY:
            return self.save(session_id, filename, upload.read(), content_type)
        upload.seek(0)
        head = upload.read(HEAD_BYTES)
        return self.save(session_id, filename, _Streamed(upload, head, size), content_type)

    def save(self, session_id: str, filename: str, data: bytes | bytearray,
             content_type: str = "", *, made: dict | None = None, source: str = "",
             source_ref: dict | None = None) -> dict:
        """Store one file and return the record describing it.

        `content_type` is what the browser said the file was. It is used only
        when nothing else knows - an extension neither this file nor Python's
        own table has heard of - and never to decide how the file is treated.

        `made` is how a file Rouh made itself came about - a picture it drew
        (`rouh/imaging.py`) - kept in its record and in every marker of it.

        Since 4 November 2026 the file lives in the one store every job sees at the
        same path (`rouh/filestore.py`): in the folder of the task, chat or project
        it was given to, under its own name, and on the list of files, which says
        where it is from then on. `source` says where it came from ("chat",
        "telegram", "email", ...), worked out from the key when not said.

        Raises AttachmentError with a sentence the person can read.
        """
        if not data:
            raise AttachmentError(
                f"{safe_name(filename)} arrived with nothing in it, so there was "
                "nothing to attach. Attach it again, or pick it from Photos or "
                "Files rather than dragging it."
            )
        if len(data) > MAX_BYTES:
            raise AttachmentError(
                f"{safe_name(filename)} is {human_size(len(data))}, and the limit is "
                f"{human_size(MAX_BYTES)} per file. Attach a smaller one, or ask me "
                "to open it from a path on this machine."
            )
        streamed = isinstance(data, _Streamed)
        head = data.head if streamed else data
        name = picture_named_truly(safe_name(filename), head)
        ext, media, kind = classify(name, head, content_type)
        _check_magic(media, head, name)

        # An iPhone photo, or any other picture no browser draws and the API
        # does not take, is kept as the same picture in a format both do, from
        # the moment it arrives (ORIGINAL). One that cannot be opened is kept
        # as it came, and says so on its chip (NOT_SEEN).
        came = None
        if media in CONVERTIBLE and streamed:
            # A picture this big is not read into memory to be written again.
            came = {"unseen": NOT_SEEN.format(name=name)}
        elif media in CONVERTIBLE:
            try:
                made_now = _rewritten(data, whole=True)
            except Exception as exc:  # noqa: BLE001 - kept as a file, and it says so
                log.info("could not write %s again as a picture: %s", name, exc)
                made_now = None
            if made_now is None:
                came = {"unseen": NOT_SEEN.format(name=name)}
            else:
                came = {"name": name, "media_type": media, "size": len(data)}
                original = data
                data = made_now["data"]
                media, kind = made_now["media_type"], "image"
                name = (os.path.splitext(name)[0] or "picture") + (
                    ".png" if media == "image/png" else ".jpg")

        sid = self.dir_for(session_id) and safe_id(session_id)
        # The same bytes are kept once: a file already on the list gains this owner instead of
        # a second copy (`filestore.same_content`).
        digest = _digest(data)
        twin = filestore.same_content(digest, len(data)) if not made else None
        if twin is not None:
            kind_of, owner = filestore.owner_of_key(sid)
            filestore.add_owner(twin.id, kind_of, owner)
            if not sid.startswith(("task-", "project-")):
                filestore.add_owner(twin.id, "chat", sid)
            log.info("%s is the same as file %s, kept once", name, twin.id)
            return filestore.record_of(twin)
        att_id = uuid.uuid4().hex[:16]
        home = filestore.home_of_key(sid)
        filestore.make_dir(home)
        path = filestore.free_name(home, name)
        name = os.path.basename(path)
        folder = filestore.side_of(att_id)
        filestore.make_dir(folder)
        self._write(path, data, filestore.FILE_MODE)
        record = {
            "id": att_id,
            "session_id": safe_id(session_id),
            "name": name,
            "media_type": media,
            "kind": kind,
            "size": len(data),
            "ts": time.time(),
            "path": path,
        }
        if came and "unseen" in came:
            record["unseen"] = came["unseen"]
        elif came:
            self._write(os.path.join(folder, ORIGINAL + ext), original)
            record["converted_from"] = came
        if made:
            record["made"] = dict(made)
        # The description of the file is as private as the file: it carries the
        # name the person chose and the path it sits at.
        self._write(os.path.join(folder, META),
                    json.dumps(record).encode("utf-8"))
        try:
            filestore.register(record, source=source or _source_of(sid, made),
                               source_ref=source_ref,
                               sha256=digest if not came else "")
        except Exception:  # noqa: BLE001 - the file is kept and found by its record beside it
            log.exception("%s could not be put on the list of files", path)
        return record

    def _own_folder(self, record: dict) -> str | None:
        """The folder of this attachment, or None if the record points elsewhere.

        A record is read off disk, and its path is only trusted this far: the
        folder it names has to be one attachment's own, two levels inside this
        store - `{session}/{id}` - and nowhere else.
        """
        path = str(record.get("path") or "")
        if path and record.get("id") and filestore.inside(path):
            side = filestore.side_of(str(record["id"]))
            if not os.path.isdir(side):
                filestore.make_dir(side)
            return side
        folder = os.path.dirname(path)
        if not folder:
            return None
        real = os.path.realpath(folder)
        if os.path.dirname(os.path.dirname(real)) != os.path.realpath(self.root):
            return None
        return real

    def mark(self, record: dict, made: dict) -> dict | None:
        """Say how a file already kept came about, in its record, and return it.

        For what the picture editor sends up beside a change - the area
        painted, the copy painted on - which arrives by the same door as any
        upload and is only known for what it is once the change names it
        (`imaging.HELPERS`). None when the record is not this store's.
        """
        folder = self._own_folder(record)
        if folder is None:
            return None
        kept = self.get(record.get("session_id", ""), record.get("id", ""))
        if kept is None:
            return None
        kept["made"] = dict(made)
        self._write(os.path.join(folder, META), json.dumps(kept).encode("utf-8"))
        got = filestore.row(kept.get("id", ""))
        if got is not None:
            got.meta = {**(got.meta or {}), "made": dict(made)}
            got.save(update_fields=["meta"])
        return kept

    def keep_words(self, record: dict, words: str) -> bool:
        """Keep the words read out of one file, as Markdown, beside it.

        Written the way the file itself was, closed to everyone but the app
        and the worker's group. False when the folder is not this record's.
        """
        folder = self._own_folder(record)
        if folder is None:
            return False
        self._write(os.path.join(folder, WORDS), words.encode("utf-8"))
        return True

    def words(self, record: dict) -> str | None:
        """The words read out of one file, or None when nobody has read them.

        An empty string is an answer too: the file was read and had no words
        in it, which is what a scanned PDF or a deck of pictures comes back as.
        """
        folder = self._own_folder(record)
        if folder is None:
            return None
        try:
            with open(os.path.join(folder, WORDS), encoding="utf-8", errors="replace") as fh:
                return fh.read()
        except OSError:
            return None

    # --- reading ------------------------------------------------------------

    def get(self, session_id: str, att_id: str) -> dict | None:
        """The record of one file, from the list of files, which says where it is now.

        A file kept before the list (`{data dir}/attachments/{session}/{id}`) is still
        found where it was until it is moved into its home (`manage.py files_migrate`).
        """
        sid, aid = safe_id(session_id), safe_id(att_id)
        if not sid or not aid:
            return None
        found = filestore.find(sid, aid)
        if found is not None:
            return found
        side = os.path.join(filestore.side_of(aid), META)
        try:
            with open(side, encoding="utf-8") as fh:
                record = json.load(fh)
            if (isinstance(record, dict) and record.get("session_id") == sid
                    and filestore.row(aid) is None and not _on_list(aid)
                    and os.path.isfile(record.get("path", ""))
                    and filestore.inside(record["path"])):
                return record
        except (OSError, ValueError):
            pass
        meta = os.path.join(self.root, sid, aid, META)
        try:
            with open(meta, encoding="utf-8") as fh:
                record = json.load(fh)
        except (OSError, ValueError):
            return None
        if not isinstance(record, dict) or not os.path.isfile(record.get("path", "")):
            return None
        return record

    def listing(self, session_id: str) -> list[dict]:
        """Every file kept under one key, oldest first.

        A conversation never asks this - what was attached in a chat is in the
        chat, in the order it was said - and a project does: the files on a
        project's page are the project's own and there is nowhere else they are
        written down. A folder with no readable `meta.json` in it is skipped
        rather than guessed at, which is what a half-written upload looks like.
        """
        sid = safe_id(session_id)
        if not sid:
            return []
        out: list[dict] = list(filestore.listing(sid))
        seen = {r["id"] for r in out}
        here = os.path.join(self.root, sid)
        try:
            names = sorted(os.listdir(here))
        except OSError:
            names = []
        for name in names:
            if name in seen:
                continue
            record = self.get(sid, name)
            if record is not None:
                out.append(record)
        out.sort(key=lambda r: r.get("ts") or 0)
        return out

    def drop(self, session_id: str, att_id: str) -> dict | None:
        """Take one file away, and say which one it was.

        The whole of its own folder goes: the bytes and the `meta.json` beside
        them are one thing and there is never a reason to keep half of it. The
        id is checked by `get` first, so nothing here can be pointed at a
        directory that is not one attachment's.
        """
        record = self.get(session_id, att_id)
        if record is None:
            return None
        if filestore.inside(record["path"]):
            # Kept once for several owners (`filestore.same_content`): only this one lets go.
            if filestore.let_go(record["id"], safe_id(session_id)):
                return record
            # Into the bin, which is emptied on a schedule: nothing is deleted for good at once.
            filestore.to_bin(record["id"], by="the person")
            return record
        folder = os.path.dirname(record["path"])
        want = os.path.join(self.root, safe_id(session_id), safe_id(att_id))
        if os.path.realpath(folder) != os.path.realpath(want):
            return None
        shutil.rmtree(folder, ignore_errors=True)
        return record

    def resolve(self, session_id: str, ids) -> tuple[list[dict], list[str]]:
        """The records for these ids, and the ids that were not found.

        An id that belongs to another conversation is not found either: the
        session is part of the path, so there is nothing to check separately.
        """
        found, missing = [], []
        for raw in ids or []:
            att_id = raw.get("id") if isinstance(raw, dict) else raw
            record = self.get(session_id, str(att_id or ""))
            if record is None:
                missing.append(str(att_id or "")[:40])
            else:
                found.append(record)
        return found, missing

    def read(self, record: dict) -> bytes:
        with open(record["path"], "rb") as fh:
            return fh.read()

    def for_model(self, record: dict) -> dict | None:
        """The picture the model is shown for this file, or None if it is not one.

        {"media_type", "data", "width", "height", "written"}: `data` the bytes
        to send, and `written` true when they are not the file itself but the
        file written again (`_rewritten`). A picture the API takes as it is,
        and small enough for one image block, is the file itself, untouched. A
        .heic, or a PNG too big for one image block, is written again at its
        full size, once, and kept beside the file (SEEN) for every later turn.

        None when the file is not a picture, or is one nothing here can open,
        which the caller turns into a line naming the file and its path.
        """
        media = str(record.get("media_type") or "")
        if not (record.get("kind") == "image" or media in CONVERTIBLE):
            return None
        folder = self._own_folder(record)
        if folder is None:
            return None
        body = self.read(record)
        if media in MODEL_PICTURES and len(body) <= PICTURE_BYTES:
            size = _picture_size(body)
            if size and max(size) <= PICTURE_SIDE:
                return {"media_type": media, "data": body, "width": size[0],
                        "height": size[1], "written": False}
        for name, kind in ((SEEN + ".png", "image/png"), (SEEN + ".jpg", "image/jpeg")):
            kept = os.path.join(folder, name)
            try:
                with open(kept, "rb") as fh:
                    data = fh.read()
            except OSError:
                continue
            size = _picture_size(data)
            if size:
                return {"media_type": kind, "data": data, "width": size[0],
                        "height": size[1], "written": True, "whole": _picture_size(body)}
        made = _rewritten(body)
        if made is None:
            return None
        self._write(os.path.join(folder, SEEN + (".png" if made["media_type"] == "image/png"
                                                 else ".jpg")), made["data"])
        return {**made, "written": True, "whole": _picture_size(body)}


def _digest(data) -> str:
    """The sha256 of what arrived, read once: from memory, or from where a big upload was spooled."""
    h = hashlib.sha256()
    if isinstance(data, _Streamed):
        data.source.seek(0)
        for block in iter(lambda: data.source.read(1024 * 1024), b""):
            h.update(block)
        data.source.seek(0)
    else:
        h.update(data)
    return h.hexdigest()


def _source_of(session: str, made: dict | None) -> str:
    """Where a file came from, when its caller did not say: read off the key it was given under."""
    if made:
        return "made"
    if session.startswith("task-"):
        return "task_page"
    if session.startswith("project-"):
        return "project_page"
    return "chat"


def _on_list(att_id: str) -> bool:
    """Whether the list has this file at all, live or in the bin."""
    try:
        from .models.files import File

        return File.objects.filter(id=att_id).exists()
    except Exception:  # noqa: BLE001 - no list: the record beside the file is all there is
        return False


# --- a picture the model can be shown -----------------------------------------


def _pillow():
    """Pillow, able to open a .heic, or None where it is not installed.

    Imported here rather than at the top so that a machine without it still
    takes every file and still answers every turn: a picture it cannot write
    again is named to the model with its path, as it was before.
    """
    try:
        from PIL import Image, ImageOps
    except ImportError:
        log_once("Pillow is not installed, so a .heic is named to the model rather than shown")
        return None
    try:
        import pillow_heif
        pillow_heif.register_heif_opener()
    except ImportError:
        log_once("pillow-heif is not installed, so a .heic is named to the model rather than shown")
    return Image, ImageOps


def _picture_size(data: bytes) -> tuple[int, int] | None:
    """(width, height) from a picture's header, without decoding it."""
    got = _pillow()
    if got is None:
        return None
    try:
        with got[0].open(io.BytesIO(data)) as im:
            return im.size
    except Exception:
        return None


def _rewritten(body: bytes, whole: bool = False) -> dict | None:
    """A picture as a PNG or a JPEG the API takes, at its full size.

    `whole` is for the copy kept when a picture arrives (`Attachments.save`):
    never made smaller, whatever its size, and not tried as a PNG when it is a
    photo (PNG_PIXELS). What the model is shown of it is decided each turn, as
    for any other picture.

    A PNG first, because a screenshot is text and a PNG keeps every pixel of
    it. If that is over PICTURE_BYTES, a JPEG at a quality where small text
    stays sharp, and lower only as far as it has to go. The picture is made
    smaller only when nothing else fits: a side over PICTURE_SIDE, or a photo
    so large that even the lowest JPEG is over the limit. A 12 megapixel
    photo fits at full size well before that.
    """
    got = _pillow()
    if got is None:
        return None
    Image, ImageOps = got
    try:
        with Image.open(io.BytesIO(body)) as opened:
            im = ImageOps.exif_transpose(opened)
            im.load()
    except Exception as exc:
        log.info("could not open a picture to show it to the model: %s", exc)
        return None
    if im.mode not in ("RGB", "RGBA"):
        im = im.convert("RGBA" if "A" in im.getbands() or im.mode == "P" else "RGB")
    if whole:
        # The profile is kept, so an iPhone's wide colour reads the same.
        icc = im.info.get("icc_profile")
        if im.width * im.height <= PNG_PIXELS:
            out = io.BytesIO()
            im.save(out, "PNG", compress_level=6, icc_profile=icc)
            if len(out.getvalue()) <= PICTURE_BYTES:
                return {"media_type": "image/png", "data": out.getvalue(),
                        "width": im.width, "height": im.height}
        if im.mode == "RGBA":
            flat = Image.new("RGB", im.size, (255, 255, 255))
            flat.paste(im, mask=im.getchannel("A"))
            im = flat
        out = io.BytesIO()
        im.save(out, "JPEG", quality=92, subsampling=0, icc_profile=icc)
        return {"media_type": "image/jpeg", "data": out.getvalue(),
                "width": im.width, "height": im.height}
    if max(im.size) > PICTURE_SIDE:
        im.thumbnail((PICTURE_SIDE, PICTURE_SIDE), Image.LANCZOS)

    def png() -> bytes:
        out = io.BytesIO()
        im.save(out, "PNG", optimize=False, compress_level=6)
        return out.getvalue()

    def jpeg(quality: int) -> bytes:
        out = io.BytesIO()
        flat = im
        if im.mode == "RGBA":
            flat = Image.new("RGB", im.size, (255, 255, 255))
            flat.paste(im, mask=im.getchannel("A"))
        # Not optimize=True: on a large picture it runs out of the encoder's
        # buffer and fails with "Suspension not allowed here".
        flat.save(out, "JPEG", quality=quality, subsampling=0 if quality >= 90 else 2)
        return out.getvalue()

    data = png()
    if len(data) <= PICTURE_BYTES:
        return {"media_type": "image/png", "data": data,
                "width": im.width, "height": im.height}
    for quality in (92, 85, 75):
        data = jpeg(quality)
        if len(data) <= PICTURE_BYTES:
            return {"media_type": "image/jpeg", "data": data,
                    "width": im.width, "height": im.height}
    while max(im.size) > 1000:
        im = im.resize((im.width * 4 // 5, im.height * 4 // 5), Image.LANCZOS)
        data = jpeg(85)
        if len(data) <= PICTURE_BYTES:
            return {"media_type": "image/jpeg", "data": data,
                    "width": im.width, "height": im.height}
    return None


# --- what is kept in the transcript ----------------------------------------


def marker(record: dict, made: dict | None = None) -> dict:
    """The block stored in the messages table in place of the file itself.

    `made` marks a file as one Rouh made or pointed at rather than one the
    person handed over - a picture it drew, the area painted to change one, a
    picture named again as the one being changed - and such a file reaches the
    model as a line of words, never as itself (`_made_block`). Given here, or
    taken from the record.
    """
    out = {
        "type": "attachment",
        "id": record["id"],
        "session_id": record.get("session_id", ""),
        "name": record["name"],
        "media_type": record["media_type"],
        "kind": record["kind"],
        "size": int(record.get("size") or 0),
    }
    made = made if made is not None else record.get("made")
    if isinstance(made, dict) and made:
        out["made"] = dict(made)
    return out


def stored_content(records: list[dict], text: str) -> list[dict]:
    """One user message: the files first, then what was typed.

    Files first because that is the order the model reads best in - a question
    about a picture makes more sense after the picture - and because it keeps
    the person's own words as the last thing in the message.
    """
    blocks = [marker(r) for r in records]
    if text:
        blocks.append({"type": "text", "text": text})
    return blocks


def markers_in(content) -> list[dict]:
    """Every attachment marker in a stored message, for the transcript on screen."""
    if not isinstance(content, list):
        return []
    return [
        {k: v for k, v in b.items() if k != "type"}
        for b in content
        if isinstance(b, dict) and b.get("type") == "attachment"
    ]


# --- what the model is sent -------------------------------------------------


def _text_block(record: dict, body: bytes) -> dict:
    try:
        body_text = body.decode("utf-8")
    except UnicodeDecodeError:
        body_text = body.decode("utf-8", "replace")
    cut = ""
    if len(body_text) > TEXT_LIMIT:
        body_text = body_text[:TEXT_LIMIT]
        cut = (
            f"\n\n[Cut here. This is the first {TEXT_LIMIT:,} characters of "
            f"{human_size(record['size'])}. The whole file is at {record['path']}.]"
        )
    return {
        "type": "text",
        "text": (
            f"Attached file {record['name']} ({record['media_type']}, "
            f"{human_size(record['size'])}), saved at {record['path']}:\n\n"
            f"{body_text}{cut}"
        ),
    }


def _words_block(record: dict, words: str) -> dict:
    """A file nothing here can open, as the words that were read out of it."""
    cut = ""
    if len(words) > TEXT_LIMIT:
        words = words[:TEXT_LIMIT]
        cut = (f"\n\n[Cut here. This is the first {TEXT_LIMIT:,} characters of its "
               f"words. The file itself is at {record['path']}.]")
    return {
        "type": "text",
        "text": (
            f"Attached file {record['name']} ({record['media_type']}, "
            f"{human_size(record['size'])}), saved at {record['path']}. These are "
            "the words read out of it, as Markdown; its pictures and its layout "
            f"are not here:\n\n{words}{cut}"
        ),
    }


def _path_block(record: dict, why: str) -> dict:
    return {
        "type": "text",
        "text": (
            f"Attached file {record['name']} ({record['media_type']}, "
            f"{human_size(record['size'])}) is saved at {record['path']}. "
            f"{why} Read it with a tool or hand the path to a job that can open it."
        ),
    }


def _seen(record: dict, store: Attachments) -> dict | None:
    """`store.for_model`, with a file that cannot be read back taken as None."""
    try:
        return store.for_model(record)
    except OSError:
        return None


def sent_size(record: dict, store: Attachments, seen: dict | None = None) -> int:
    """How many bytes of this file one request would carry.

    For a picture that is what the model is shown, which for a .heic written
    again as a PNG can be several times the file: counting the file would let
    a conversation of phone screenshots grow past what one request may be.
    """
    seen = seen if seen is not None else _seen(record, store)
    return len(seen["data"]) if seen else int(record.get("size") or 0)


def anthropic_blocks(record: dict, store: Attachments, inline: bool = True,
                     seen: dict | None = None) -> list[dict]:
    """One attachment, as the blocks this model can actually read.

    `inline` false means the file is not being sent this time, only named. That
    happens when a conversation already carries more attachment bytes than one
    request should, and it is always better than a request that is refused.

    `seen` is `store.for_model(record)` when the caller already has it.
    """
    kind = record.get("kind")
    if inline and (kind == "image" or record.get("media_type") in CONVERTIBLE):
        seen = seen if seen is not None else _seen(record, store)
        if seen is not None:
            return _picture_blocks(record, seen)
        if kind != "image":
            return [_path_block(record, "It could not be opened as a picture here.")]
        if int(record.get("size") or 0) > PICTURE_BYTES:
            # Sent as it is, it would be refused, and the whole turn with it.
            return [_path_block(record, "It is too big to be shown as one picture, "
                                        "and could not be made to fit.")]
    if not inline:
        why = (
            f"It is too big to put in one request - {human_size(INLINE_BUDGET)} of "
            "files is the most that fits - so only its name and its place are here."
            if int(record.get("size") or 0) > INLINE_BUDGET else
            "It is not sent here because this conversation already carries several files."
        )
        return [_path_block(record, why)]
    if kind not in ("image", "pdf", "text"):
        # A .docx, a spreadsheet, a deck: the model cannot open one, and its
        # words were read out of it when it was uploaded (`rouh/uploads.py`).
        # The file itself is never read here - a recording is sixty megabytes
        # of nothing the model could use.
        words = store.words(record)
        if words and words.strip():
            return [_words_block(record, words)]
        return [_path_block(record, "Nothing here can open that format.")]
    try:
        body = store.read(record)
    except OSError:
        return [{
            "type": "text",
            "text": f"Attached file {record['name']} could not be read back from "
                    f"{record.get('path', 'disk')}.",
        }]

    if kind == "image":
        # A picture Pillow could not open: sent as it is, as it always was.
        return _picture_blocks(record, {"media_type": record["media_type"], "data": body})
    if kind == "pdf":
        # The Messages API reads a PDF itself, pages and all, so it is sent
        # whole rather than flattened to text here. Saying so in the message
        # matters: it is the difference between "I cannot see the diagram on
        # page two" being true and being a guess.
        return [
            {
                "type": "document",
                "source": {
                    "type": "base64",
                    "media_type": "application/pdf",
                    "data": base64.b64encode(body).decode("ascii"),
                },
            },
            {
                "type": "text",
                "text": (
                    f"That is the PDF {record['name']} ({human_size(record['size'])}), "
                    f"sent whole so you can read its pages and see its pictures. "
                    f"It is also on disk at {record['path']}."
                ),
            },
        ]
    return [_text_block(record, body)]


def _picture_blocks(record: dict, seen: dict) -> list[dict]:
    """A picture, and the line that names it.

    Named as well as shown, as every other file is: a picture the model can
    see but not name is a picture it cannot attach to an email or hand to a
    job. Its size in pixels is said too, and whether it is the file itself or
    the file written again, so that "do you have the whole screenshot" has an
    answer that is a fact rather than a guess.
    """
    how = ""
    if seen.get("width") and seen.get("height"):
        how = f", {seen['width']} x {seen['height']} pixels"
    if seen.get("written"):
        was = str(record.get("media_type") or "").split("/")[-1] or "file"
        now = "PNG" if seen["media_type"] == "image/png" else "JPEG"
        why = ("the file itself is not a format you can be sent"
               if record.get("media_type") not in MODEL_PICTURES else
               "the file itself is too big to be sent as one picture")
        whole = seen.get("whole")
        # Compared either way round: a photo turned upright is the same picture.
        if whole and sorted(whole) != sorted((seen.get("width"), seen.get("height"))):
            how += (f", shown to you as a {now} made smaller from its {whole[0]} x "
                    f"{whole[1]}, because {why}")
        else:
            how += f", shown to you whole as a {now} written from the {was}, because {why}"
    else:
        how += ", shown to you whole"
    came = record.get("converted_from")
    if isinstance(came, dict) and came.get("name"):
        how += f", written from the {came['name']} it arrived as"
    return [
        {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": seen["media_type"],
                "data": base64.b64encode(seen["data"]).decode("ascii"),
            },
        },
        {
            "type": "text",
            "text": (
                f"That is the picture {record['name']} ({human_size(int(record.get('size') or 0))}"
                f"{how}), saved at {record['path']}, id {record.get('id', '')} in this chat."
            ),
        },
    ]


def _made_block(record: dict, made: dict, role: str) -> dict:
    """A file Rouh made or pointed at, as the line of words the model reads.

    Never the picture itself. A picture Rouh drew is on the person's screen,
    and the words it was drawn from say what is in it; sending it back with
    every later request would put a thousand tokens or more of picture into
    each of them for nothing. And an assistant message may not carry a picture
    at all: the API refuses one.
    """
    name = record.get("name") or "a file"
    where = record.get("path") or "(no longer on disk)"
    ident = record.get("id") or ""
    kind = made.get("kind") if isinstance(made, dict) else ""
    if kind == "drawn":
        size = (f"{made.get('width')}x{made.get('height')}, "
                if made.get("width") and made.get("height") else "")
        if made.get("variation"):
            how = "a variation of picture " + str(made.get("from") or "")
        elif made.get("from"):
            how = "changed from picture " + str(made["from"])
            if made.get("area"):
                how += " in the area the person painted"
        else:
            how = "drawn"
        if made.get("references"):
            how += " with the person's pictures " + ", ".join(map(str, made["references"]))
        text = (f"[A picture Rouh showed in the chat here: {name} (id {ident}, {size}{how} by "
                f"{made.get('by') or 'a provider'} {made.get('model') or ''}) from the words: "
                f"\"{made.get('prompt') or ''}\". Saved at {where}.]")
    elif kind == "area":
        text = (f"[The person painted an area of picture {made.get('from') or ''} to change, "
                f"shown to them as {name}.]")
    elif kind == "ref":
        text = f"[The picture {name} (id {ident}), shown again here.]"
    else:
        who = "Rouh" if role == "assistant" else "The person"
        text = f"[{who} showed the file {name} (id {ident}) here. Saved at {where}.]"
    return {"type": "text", "text": text}


def expand(content, store: Attachments, budget: int, role: str = "user") -> tuple[list, int]:
    """One message's content with its attachment markers turned into real blocks.

    Only a file the person handed over is ever sent as itself. One Rouh made
    or pointed at, and anything at all in Rouh's own message, is a line of
    words (`_made_block`).
    """
    if not isinstance(content, list):
        return content, budget
    out = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "attachment":
            record = store.get(block.get("session_id", ""), block.get("id", "")) or dict(block)
            record.setdefault("path", "(no longer on disk)")
            record.setdefault("size", 0)
            made = block.get("made")
            if isinstance(made, dict) or role == "assistant":
                out.append(_made_block(record, made if isinstance(made, dict) else {}, role))
                continue
            seen = _seen(record, store)
            cost = sent_size(record, store, seen)
            fits = budget - cost >= 0
            out.extend(anthropic_blocks(record, store, inline=fits, seen=seen))
            if fits:
                budget -= cost
        elif (isinstance(block, dict) and block.get("type") == "tool_result"
              and isinstance(block.get("content"), list)
              and any(isinstance(b, dict) and b.get("type") == "attachment" for b in block["content"])):
            # A tool that showed a file, such as a picture attached to an email (`rouh/mail_pictures.py`):
            # its result keeps the marker, and the file is read here like any other.
            inner, budget = expand(block["content"], store, budget, role="user")
            out.append({**block, "content": inner})
        else:
            out.append(block)
    return out, budget


def hydrate(messages: list[dict], store: Attachments) -> list[dict]:
    """Every attachment marker in a conversation, expanded, newest first.

    Newest first is the whole point of walking backwards: when there is more
    than one request's worth of files in a conversation, the screenshot just
    handed over is the one that has to arrive, and the one from twenty turns ago
    is the one that can become a line of text.
    """
    budget = INLINE_BUDGET
    out: list[dict] = []
    for msg in reversed(messages):
        content, budget = expand(msg.get("content"), store, budget,
                                 role=str(msg.get("role") or "user"))
        out.append({**msg, "content": content})
    out.reverse()
    return out
