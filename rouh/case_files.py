"""The files a case's reply carries out: made by its work, seen by the owner, sent once.

Petar, 2 October 2026, from a contact's case: the plan was a one to two
page PDF guide, and "Reply to [the contact] in the Intro thread with the PDF
attached". The proposed reply said "A first version of the guide is attached",
the approval card asked him to approve that reply before any document
existed, and the reply path could not attach anything at all: approved, the
contact would have had a reply that said a guide was attached, and no guide.

So a case can carry the files its work made for the reply, and this is where
each one is checked, fingerprinted, shown and read for sending:

- **Named by the work, never guessed.** The carry-out turn, its check, or the
  job it started names each file (`reply_files` in `case_report`, or a
  `Reply file: <path>` line in a job's report, `from_report`). A file is taken
  only if it is a regular file inside the workspace (`config.assistant_repo`)
  or the case's own folder (`folder`), judged where it really is, links
  followed, not hidden, not a program, and not past what Gmail carries.
  Nothing else on the machine can be attached by a case, whatever an email
  talks a turn into naming.
- **Fingerprinted.** Each file is kept with its sha256 and size. An approval is
  bound to those hashes (`mail_cases.CaseDesk.fingerprint`), and the bytes that
  go are hashed again as they are read for sending (`read_for_send`): a file
  that changed after the owner saw it does not go on their approval.
- **Shown.** The case page previews each one (`preview`): a PDF's pages drawn
  as pictures (`pages`, with `pdftoppm`), a picture as itself, text and
  Markdown as their words, and anything else as its words where they can be
  read, always with a link to open or download the file itself.
- **Never claimed when not there.** A reply that says something is attached
  (`claims`) goes only with a file; one that carries files without saying so
  goes, and the card says they will.
"""
from __future__ import annotations

import hashlib
import logging
import mimetypes
import os
import re
import subprocess

from . import attachments, mail_attachments

log = logging.getLogger("rouh.case_files")

#: The most files one reply carries.
MOST_FILES = 10

#: The most of a document's words the reply check reads with the reply.
WORDS_FOR_CHECK = 40_000

#: The most of a text file the case page shows.
TEXT_SHOWN = 20_000

#: How many pages of a PDF are drawn on the case page.
PAGES_SHOWN = 6


class Refused(ValueError):
    """Why a file cannot go with a case's reply, in a sentence."""


class Changed(ValueError):
    """A file is not, byte for byte, the one that was approved."""


def _config():
    from .config import config

    return config


def mail_limit() -> int:
    from .google_api import MAIL_LIMIT

    return MAIL_LIMIT


def folder(key: str) -> str:
    """The case's own folder, where its work may leave what the reply sends."""
    safe = re.sub(r"[^A-Za-z0-9_-]", "", str(key or ""))[:64] or "unknown"
    return os.path.join(_config().data_dir, "mail-cases", safe)


def roots(key: str) -> list[tuple[str, str]]:
    """(where it really is, what it is called) for each place a reply file may come from."""
    out = []
    workspace = getattr(_config(), "assistant_repo", "") or ""
    if workspace and os.path.isdir(workspace):
        out.append((os.path.realpath(workspace), "workspace"))
    own = folder(key)
    out.append((os.path.realpath(own), "case folder"))
    return out


def where(key: str) -> str:
    return " or ".join(f"the {name} ({path})" for path, name in roots(key))


def _root_of(real: str, key: str) -> tuple[str, str] | None:
    for root, name in roots(key):
        if real == root or real.startswith(root.rstrip(os.sep) + os.sep):
            return root, name
    return None


def sha256_of(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def kind_of(name: str, media: str) -> str:
    """"pdf", "image", "text" or "other": how the page previews it."""
    media = (media or "").lower()
    ext = os.path.splitext(name or "")[1].lower()
    if media == "application/pdf" or ext == ".pdf":
        return "pdf"
    if media.startswith("image/") and ext in (".png", ".jpg", ".jpeg", ".gif", ".webp"):
        return "image"
    if media.startswith("text/") or ext in (".md", ".markdown", ".txt", ".csv"):
        return "text"
    return "other"


def checked(raw, key: str) -> dict:
    """One file the work named for the reply, checked and fingerprinted. Refused says why.

    `raw` is a path, absolute or relative to the workspace, or {"path",
    "name"} where name is what the file is called in the email.
    """
    if isinstance(raw, dict):
        path, name = str(raw.get("path") or "").strip(), str(raw.get("name") or "").strip()
    else:
        path, name = str(raw or "").strip(), ""
    if not path:
        raise Refused("A file was named with no path.")
    workspace = getattr(_config(), "assistant_repo", "") or ""
    full = path if os.path.isabs(path) else os.path.join(workspace or folder(key), path)
    real = os.path.realpath(full)
    found = _root_of(real, key)
    if found is None:
        raise Refused(f"{path} is not in the workspace or the case's own folder, and only "
                      f"a file there can go with a reply: {where(key)}.")
    root, place = found
    inside = os.path.relpath(real, root)
    if inside == "." or any(part.startswith(".") for part in inside.split(os.sep)):
        raise Refused(f"{path} is hidden, or in a hidden folder, and that never goes with a "
                      "reply.")
    if not os.path.isfile(real):
        raise Refused(f"There is no file at {path}.")
    size = os.path.getsize(real)
    if size == 0:
        raise Refused(f"{path} is empty.")
    if size > mail_limit():
        raise Refused(f"{path} is {attachments.human_size(size)}, more than one email "
                      "carries.")
    name = attachments.safe_name(name or os.path.basename(real)) or os.path.basename(real)
    if os.path.splitext(name)[1].lower() in attachments.BLOCKED:
        raise Refused(f"{name} is a program, and Gmail will not send one.")
    with open(real, "rb") as fh:
        head = fh.read(8)
    if head.startswith(attachments.EXECUTABLE_MAGIC):
        raise Refused(f"{name} is a program, and Gmail will not send one.")
    media = mimetypes.guess_type(name)[0] or "application/octet-stream"
    return {"path": real, "rel": f"{place}: {inside}", "place": place, "name": name,
            "type": media, "size": size, "sha256": sha256_of(real),
            "kind": kind_of(name, media)}


def named(raw, key: str) -> tuple[list[dict], list[str]]:
    """Every file a report named, checked: (the files, why each other one was refused)."""
    if raw in (None, "", []):
        return [], []
    if isinstance(raw, (str, dict)):
        raw = [raw]
    if not isinstance(raw, (list, tuple)):
        return [], ["reply_files has to be a list of paths."]
    files, refused, seen = [], [], set()
    for one in list(raw)[:MOST_FILES + 5]:
        try:
            got = checked(one, key)
        except Refused as exc:
            refused.append(str(exc))
            continue
        except OSError as exc:
            refused.append(f"{one} could not be read ({exc.strerror or exc}).")
            continue
        if got["path"] in seen:
            continue
        seen.add(got["path"])
        files.append(got)
    if len(files) > MOST_FILES:
        refused.append(f"A reply carries at most {MOST_FILES} files.")
        files = files[:MOST_FILES]
    total = sum(f["size"] for f in files)
    if total > mail_limit():
        refused.append(f"Together they come to {attachments.human_size(total)}, more than "
                       "one email carries.")
    return files, refused


#: A line a job ends its report with for each file it made for the reply.
REPORT_LINE = re.compile(r"^\s*[-*]?\s*Reply file:\s*(?P<path>\S.*?)\s*$", re.I | re.M)


def from_report(report: str) -> list[str]:
    """The paths a job's report names with `Reply file: <path>` lines."""
    return [m.group("path").strip("`'\" ") for m in REPORT_LINE.finditer(report or "")][
        :MOST_FILES]


def now(files) -> list[dict]:
    """The files as they are on disk now: each with its present hash, or missing."""
    out = []
    for one in files or []:
        if not isinstance(one, dict):
            continue
        got = dict(one)
        try:
            got["now_sha256"] = sha256_of(one["path"]) if os.path.isfile(one["path"]) else ""
            got["now_size"] = os.path.getsize(one["path"]) if got["now_sha256"] else 0
        except OSError:
            got["now_sha256"], got["now_size"] = "", 0
        got["missing"] = not got["now_sha256"]
        got["changed"] = bool(got["now_sha256"]) and got["now_sha256"] != one.get("sha256")
        out.append(got)
    return out


def refreshed(files) -> list[dict]:
    """The files fingerprinted afresh, as they are now; a missing one is left out."""
    out = []
    for one in now(files):
        if one["missing"]:
            continue
        fresh = {k: v for k, v in one.items() if k not in ("now_sha256", "now_size",
                                                            "missing", "changed")}
        fresh.update(sha256=one["now_sha256"], size=one["now_size"])
        out.append(fresh)
    return out


def prints(files) -> list[str]:
    """What an approval is bound to of the files: each one's name and hash."""
    return [f"{one.get('name')}:{one.get('sha256')}" for one in files or []
            if isinstance(one, dict)]


def same(a, b) -> bool:
    return sorted(prints(a)) == sorted(prints(b))


def read_for_send(files, key: str) -> list[dict]:
    """The files' bytes as `google_api.Gmail.send` takes them, each the very one approved.

    Read without following a link at the last step, checked again for where
    the opened file really is, and hashed as read: a file changed since it was
    approved raises Changed, one gone or moved raises Refused.
    """
    out = []
    for one in files or []:
        try:
            fd = os.open(one["path"], os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        except OSError:
            raise Refused(f"{one.get('name')} is not there any more.") from None
        try:
            if os.path.isdir("/proc/self/fd") and \
                    _root_of(os.path.realpath(f"/proc/self/fd/{fd}"), key) is None:
                raise Refused(f"{one.get('name')} is no longer in the workspace or the case's "
                              "folder.")
            with os.fdopen(fd, "rb", closefd=False) as fh:
                data = fh.read(mail_limit() + 1)
        finally:
            os.close(fd)
        if len(data) > mail_limit():
            raise Refused(f"{one.get('name')} is now more than one email carries.")
        if hashlib.sha256(data).hexdigest() != one.get("sha256"):
            raise Changed(f"{one.get('name')} changed after it was approved.")
        out.append({"name": one.get("name") or "attachment",
                    "type": one.get("type") or "application/octet-stream", "data": data})
    return out


def words(one: dict) -> str | None:
    """The words in one reply file, as the reply check reads them; None when unreadable."""
    try:
        with open(one["path"], "rb") as fh:
            data = fh.read(mail_limit() + 1)
    except OSError:
        return None
    if one.get("kind") == "text" or kind_of(one.get("name", ""), one.get("type", "")) == "text":
        return data.decode("utf-8", "replace")
    return mail_attachments.words_of({"name": one.get("name"), "type": one.get("type"),
                                      "data": data})


def with_documents(reply: str, files) -> str:
    """The reply as the reply check reads it: its words, then each file's words after it.

    Petar, 2 October 2026: a PDF must not carry out what the reply's own words
    would have been stopped for, so the check reads the document as part of
    the reply.
    """
    parts = [reply or ""]
    room = WORDS_FOR_CHECK
    for one in files or []:
        said = words(one)
        head = f"\n\n[Attached to this reply: {one.get('name')}]\n"
        if said is None:
            parts.append(head + "(Its words could not be read here: it is a picture, a scan "
                                "or a format nothing here reads.)")
            continue
        said = said.strip()[:max(0, room)]
        room -= len(said)
        parts.append(head + (said or "(There are no words in it.)"))
    return "".join(parts)


# --- what a reply claims ---------------------------------------------------------------

#: Words a reply says a file is attached with, in English and Bulgarian.
_CLAIMS = re.compile(
    r"\b(?:attached|attaching|enclosed|enclosing|i\s+attach|we\s+attach|please\s+find\s+"
    r"attached|in\s+the\s+attachment|see\s+(?:the\s+)?attachment|attachment\s+(?:is|has|with)"
    r"|the\s+attachment\b)"
    r"|(?:^|[^\w])(?:прилагам|прилагаме|приложен(?:а|о|и|ия|ият|ата|ото|ите)?|прикач(?:ен"
    r"|ена|ено|ени|еня|еният|ената|еното|ените|вам|ваме|их|ихме|ам|аме)|в\s+прикачения)"
    r"(?=[^\w]|$)",
    re.I)

#: A claim about the sender's own file is not a claim about ours.
_THEIRS = re.compile(r"\b(?:you|your|you've|they|their)\b|(?:^|[^\w])(?:вие|ти|вашия|вашата|"
                     r"твоя|твоята|си)(?=[^\w]|$)", re.I)


#: A bare participle - "both offers attached", "офертите прикачени" - that can be what the
#: recipient is asked to send rather than what goes with ours. "I attach", "the attached
#: guide", "прилагам", "приложения файл" are always ours.
_PARTICIPLE = re.compile(r"^(?:attached|enclosed|приложен[аои]?|прикачен[аои]?)$", re.I)

#: The participle said of our own file: "the attached guide", "attached is the plan".
_OURS_BEFORE = re.compile(r"\b(?:the|this|these|that|those|my|our)\s*$", re.I)
_OURS_AFTER = re.compile(r"^\s*(?:is|are|was|were|herewith|please|you'll|you\s+will|"
                         r"е|са|ще\s+намерите)\b", re.I)

#: The recipient asked to send, reply with or attach something: "please reply here with the
#: research attached", "could you send me the offers attached", "моля, изпратете ни ги
#: прикачени". "Please find attached" and "see attached" are not asks: they are claims.
_VERB = (r"(?:reply|respond|send|resend|re-send|forward|share|upload|e-?mail|mail|attach|"
         r"include|provide|return|submit|bring|write\s+back|get\s+back)")
_ASKS = re.compile(
    r"\b(?:please|kindly|could\s+you|can\s+you|would\s+you|will\s+you|you\s+could|"
    r"you\s+can|feel\s+free\s+to|be\s+sure\s+to|remember\s+to|don'?t\s+forget\s+to)"
    r"(?:\s+(?:please|also|just|then|kindly))*\s+" + _VERB + r"\b"
    r"|(?:^|,)\s*(?:(?:and|also|just|then|so)\s+)*" + _VERB + r"\b"
    r"|\bsend\s+(?:me|us)\b"
    r"|(?:^|[^\w])(?:изпрат|прат|отговор|препрат|сподел|прикач|кач|добав|включ|върн|"
    r"предостав)(?:ете|и)(?=[^\w]|$)"
    r"|(?:^|[^\w])да\s+(?:ми\s+|ни\s+)?(?:изпрат|прат|отговор|препрат|сподел|прикач|кач|"
    r"добав|включ|върн)(?:ите|иш)(?=[^\w]|$)"
    r"|(?:^|[^\w])бихте\s+ли\s+(?:ми\s+|ни\s+)?\w+ли(?=[^\w]|$)",
    re.I)

#: Ourselves, between the ask and the participle: "please reply, I've attached the plan".
_WE = re.compile(r"\b(?:i|we|i'?ve|we'?ve|i'?m|we'?re|i'?ll|we'?ll)\b"
                 r"|(?:^|[^\w])(?:аз|ние|ето|прилагам|прилагаме|изпращам|изпращаме)(?=[^\w]|$)",
                 re.I)

#: Said not to be attached: "no documents were attached", "it went without the attachment".
_DENIED = re.compile(r"\b(?:no|not|without|never|wasn't|weren't|isn't|aren't|didn't|"
                     r"forgot|missing|omitted)\b|(?:^|[^\w])(?:не|без|няма|нямаше)(?=[^\w]|$)",
                     re.I)

#: Where a clause ends, so an ask in one does not excuse a claim in the next.
_CLAUSE = re.compile(r"[;:()\u2014\u2013]|\s-\s")


def _asked_of_them(sentence: str, found) -> bool:
    """Whether the participle `found` is what the recipient is asked to send, not ours."""
    if not _PARTICIPLE.match(re.sub(r"^\W+|\W+$", "", found.group(0))):
        return False
    before = sentence[:found.start()]
    if _OURS_BEFORE.search(before) or _OURS_AFTER.match(sentence[found.end():]):
        return False
    ends = list(_CLAUSE.finditer(before))
    clause = before[ends[-1].end():] if ends else before
    asks = list(_ASKS.finditer(clause))
    return bool(asks) and not _WE.search(clause[asks[-1].end():])


def claims(text: str) -> str:
    """The sentence of a reply that says something is attached to it, or "".

    A request that the recipient send something attached is not a claim (Petar, 9 October
    2026: "Please reply here with the Claude research and both offers attached." held a
    reply to a contact on an approval that could never go).
    """
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", text or ""):
        for found in _CLAIMS.finditer(sentence):
            before = _CLAUSE.split(sentence[max(0, found.start() - 40):found.start()])[-1]
            if _THEIRS.search(" ".join(before.split()[-3:])):
                continue
            if _DENIED.search(" ".join(before.split()[-4:])):
                continue
            if _asked_of_them(sentence, found):
                continue
            return " ".join(sentence.split())[:400]
    return ""


# --- for the pages ----------------------------------------------------------------------


def said(files) -> str:
    """"guide.pdf (PDF, 120 kB)", and so on, for a line of words."""
    parts = [f"{one.get('name')} ({mail_attachments.kind_said(one.get('type'), one.get('name'))}"
             f", {attachments.human_size(int(one.get('size') or 0))})"
             for one in files or [] if isinstance(one, dict)]
    if len(parts) < 2:
        return "".join(parts)
    return ", ".join(parts[:-1]) + " and " + parts[-1]


def count_said(files) -> str:
    n = len([f for f in files or [] if isinstance(f, dict)])
    return f"{n} attachment{'s' if n != 1 else ''}"


def link(key: str, one: dict, *, download: bool = False) -> str:
    from .mail_cases import case_path

    return (f"{case_path(key)}/file/{str(one.get('sha256') or '')[:16]}"
            + ("?download=1" if download else ""))


def pages(one: dict, key: str) -> list[str]:
    """A PDF's first pages drawn as pictures, kept in the case's folder by its hash.

    The paths of the PNGs, in order; [] when they cannot be drawn here (no
    `pdftoppm`, a damaged file), and then the page embeds the PDF instead.
    """
    sha = str(one.get("sha256") or "")
    if not sha or one.get("kind") != "pdf":
        return []
    out_dir = os.path.join(folder(key), "pages", sha[:16])
    done = os.path.join(out_dir, ".done")
    if not os.path.exists(done):
        try:
            os.makedirs(out_dir, exist_ok=True)
            if sha256_of(one["path"]) != sha:
                return []
            subprocess.run(["pdftoppm", "-png", "-r", "110", "-f", "1", "-l", str(PAGES_SHOWN),
                            one["path"], os.path.join(out_dir, "p")],
                           check=True, timeout=60, capture_output=True)
            open(done, "w").close()
        except (OSError, subprocess.SubprocessError) as exc:
            log.warning("the pages of %s could not be drawn: %s", one.get("name"), exc)
            return []
    return [os.path.join(out_dir, name) for name in sorted(os.listdir(out_dir),
                                                          key=_page_order)
            if name.startswith("p-") and name.endswith(".png")]


def _page_order(name: str) -> int:
    found = re.search(r"(\d+)", name)
    return int(found.group(1)) if found else 0


def preview(one: dict, key: str) -> dict:
    """What the page shows of one file: its line, its links, and a look inside it."""
    state = now([one])[0]
    out = {**one, "kind_said": mail_attachments.kind_said(one.get("type"), one.get("name")),
           "size_said": attachments.human_size(int(one.get("size") or 0)),
           "url": link(key, one), "download": link(key, one, download=True),
           "id": str(one.get("sha256") or "")[:16], "missing": state["missing"],
           "changed": state["changed"], "pages": [], "text": "", "unreadable": False}
    if state["missing"] or state["changed"]:
        return out
    if one.get("kind") == "pdf":
        drawn = pages(one, key)
        out["pages"] = [f"{out['url']}/page/{i + 1}" for i in range(len(drawn))]
    elif one.get("kind") == "text":
        try:
            with open(one["path"], "rb") as fh:
                out["text"] = fh.read(TEXT_SHOWN).decode("utf-8", "replace")
        except OSError:
            out["unreadable"] = True
    elif one.get("kind") == "other":
        got = words(one)
        out["text"] = (got or "")[:TEXT_SHOWN]
        out["unreadable"] = got is None
    return out


def page_file(one: dict, key: str, number: int) -> str | None:
    drawn = pages(one, key)
    return drawn[number - 1] if 0 < number <= len(drawn) else None


__all__ = ["Changed", "Refused", "checked", "claims", "count_said", "folder", "from_report",
           "link", "named", "now", "page_file", "preview", "prints", "read_for_send",
           "refreshed", "roots", "said", "same", "with_documents", "words"]
