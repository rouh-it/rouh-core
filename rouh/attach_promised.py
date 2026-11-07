"""A file promised, not attached: an email that says it carries a file, and carries none, is not
sent until Rouh has looked again.

Built by the nightly feature run, night 34, 6 November 2026 (task 94). Most of what Rouh sends is
asked for by voice ("send Dana the proposal, say it is attached"), and the words are written before
the file is found. Gmail's own compose window has warned about exactly this since 2008 ("You wrote
'attached' in your message, but there are no files attached"), but Rouh sends through the Gmail
API, past that window, so nothing ever warned it: the email went with "please find attached" and
nothing attached, and the next email was "sorry, here it is".

Night 31 of the run (the ledger's night 35), the same day, built the same thing as "Said attached,
nothing attached" and was merged into this one: it reads the words with the rules a contact's case
has used since 2 October 2026 (`rouh/case_files.py`, `claims`), so "please send it attached" and
"you attached" are not taken for a promise; it tells Rouh where to look for the file (the
conversation's files, the task's folder, Drive, the email it came with); and a draft whose words
promise a file it does not carry is made, as before, with a line saying so, so Rouh attaches the
file before the draft is sent.

So, while its switch is on, before send_mail sends, the subject and the words of the email are read
for a phrase that promises a file - "attached", "enclosed", "see the attachment", "here is the
file", in English and in Bulgarian ("прикачен", "приложено", "в приложение") - and when the email
carries no file at all:

- nothing goes, and the answer names the words that promised one, so Rouh attaches the file it
  meant, or, when there is truly none, says so and sends it with `files_checked`
  (`attachment_checked`, night 35's name for it, is taken the same);
- an email with any file on it, a reply in a thread whose words only quote an earlier "attached",
  a draft card already on the screen, and a sent draft named by its id (its files are in Gmail)
  all go as before;
- draft_mail makes the draft (the person reads it first) and says that its words promise a file
  that is not on it.

Only the email's own words are read, not what it quotes ("On ... wrote:" and lines starting ">").
No model is asked and nothing is kept.

**Whose.** The person's own turns only (a contact's case has its own check); nothing of anybody's
is read or kept: the check is on the words being sent.

**Its switch** is `attach_promised` (`rouh/switches.py`): off, mail goes as it is given.
"""
from __future__ import annotations

import logging
import re

log = logging.getLogger("rouh.attach_promised")

SWITCH = "attach_promised"
TITLE = "A file promised, not attached: an email that says it has a file and has none is held"

#: Said to the model beside send_mail's other fields.
FIELD = {"type": "boolean",
         "description": ("Send it even though its words say a file is attached and none is. Only "
                         "when there is truly no file to attach, after looking again, or when the "
                         "person says to send it without the file.")}

#: The arguments that say the email may go as written: night 34's name, and night 35's.
CHECKED = ("files_checked", "attachment_checked")

#: Phrases that promise a file. Each is matched on word boundaries, case aside.
PROMISES = (
    r"attached", r"attaching", r"i attach", r"i've attached", r"i have attached",
    r"see the attachment", r"see attachment", r"in the attachment", r"the attachment",
    r"enclosed", r"i enclose", r"please find", r"here is the file", r"here's the file",
    r"here are the files", r"the file is attached",
    # Bulgarian: attached, in the attachment, I attach, I am sending you the file.
    r"прикачен\w*", r"прикачам", r"прилагам", r"приложен\w*", r"в приложение",
    r"в прикачения", r"изпращам ти файла", r"изпращам ви файла",
)
_PROMISE = re.compile(r"(?<![\w-])(" + "|".join(PROMISES) + r")(?![\w-])", re.IGNORECASE)
#: "Please find" promises a file only when something attached-like follows soon.
_PLEASE_FIND = re.compile(r"please find\b(?=[^.\n]{0,40}\b(attach|enclos|the file|the document)\w*)",
                          re.IGNORECASE)
#: A bare participle, which may be what the other side is asked to send ("please reply with
#: both offers attached") or said of their file ("you attached"): read with a case's rules.
_PARTICIPLE = re.compile(r"^(attached|enclosed|прикачен\w*|приложен\w*)$", re.IGNORECASE)
#: Where a reply's quoted earlier message begins.
_QUOTE_HEAD = re.compile(r"^\s*(on .{3,200} wrote:|-{2,} ?(original|forwarded) message ?-{2,}|"
                         r"from: .+|на .{3,200} написа:)\s*$", re.IGNORECASE)
_NOT_A_PROMISE = re.compile(r"\b(no|not|nothing|without)\b[^.\n]{0,20}$", re.IGNORECASE)


def on(who) -> bool:
    from . import switches

    if who is None:
        return False
    return switches.on(SWITCH, getattr(who, "org_id", None) or None)


def checked(args: dict) -> bool:
    """Whether the model was told to send it as written (`files_checked` or `attachment_checked`)."""
    return any((args or {}).get(name) for name in CHECKED)


def own_words(body: str) -> str:
    """The email's own words: everything above the first quoted message, with no ">" lines,
    and no markup."""
    text = re.sub(r"(?is)<(blockquote|style|script)\b.*?</\1>", " ", str(body or ""))
    text = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</li>", "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    kept = []
    for line in text.splitlines():
        if _QUOTE_HEAD.match(line):
            break
        if line.lstrip().startswith(">"):
            continue
        kept.append(line)
    return "\n".join(kept)


def _a_case_says_ours(line: str) -> bool:
    """Whether a case's rules (`case_files.claims`) read the line as saying our file is on it.
    True when they cannot be read, so the check is never weaker than the phrases alone."""
    try:
        from . import case_files

        return bool(case_files.claims(line))
    except Exception:  # noqa: BLE001 - the phrases alone decide
        log.debug("a case's rules could not be read for the file check", exc_info=True)
        return True


def promised(subject: str, body: str) -> list[str]:
    """The phrases in the subject and the email's own words that promise a file, as written, once
    each; [] when none does."""
    found: list[str] = []
    text = f"{subject or ''}\n{own_words(body)}"
    for m in _PROMISE.finditer(text):
        word = m.group(1)
        if word.lower() == "please find" and not _PLEASE_FIND.match(text, m.start()):
            continue
        if word.lower() == "the attachment" and found:
            continue
        before = text[max(0, m.start() - 30):m.start()]
        if _NOT_A_PROMISE.search(before):
            continue  # "nothing attached", "without the attachment"
        line_start = text.rfind("\n", 0, m.start()) + 1
        line_end = text.find("\n", m.end())
        line = text[line_start:line_end if line_end != -1 else len(text)].strip()
        if _PARTICIPLE.match(word) and not _a_case_says_ours(line):
            continue  # "please send it attached", "the file you attached"
        said = line if len(line) <= 120 else line[:117] + "..."
        if said and said not in found:
            found.append(said)
    return found[:3]


#: Where the file an email means may be found, said to the model.
_WHERE = ("a file the person gave in this conversation (by its name), one in the task's folder (its "
          "path), a Google Doc or Drive file (search_drive, then copy_drive_file or the export it "
          "offers, to a file), or the file of an email it came with (read_mail_attachment)")


def check(subject: str, body: str, *, has_files: bool) -> str:
    """Why the email is held, in words for the model; "" when it may go."""
    if has_files:
        return ""
    lines = promised(subject, body)
    if not lines:
        return ""
    quoted = "; ".join(f'"{one}"' for one in lines)
    return ("Not sent yet, and nobody was emailed: its words say a file is attached (" + quoted + "), "
            "and no file is on it: nothing is attached. Find the file it means and send again with "
            "it in `attachments`: " + _WHERE + ". If no file can be found, ask the person which "
            "one, or change the words; only if there is truly no file, or the person says to send "
            "it without one, send it as written with files_checked true. Nothing was sent.")


def draft_note(subject: str, body: str, *, has_files: bool) -> str:
    """Said after a draft whose words promise a file it does not carry; "" otherwise."""
    if has_files:
        return ""
    lines = promised(subject, body)
    if not lines:
        return ""
    quoted = "; ".join(f'"{one}"' for one in lines)
    return ("\n\nThe draft's words say a file is attached (" + quoted + "), and nothing is attached "
            "to it. Before it is sent, find the file it means (" + _WHERE + ") and draft it again "
            "with the file in `attachments`, or take the words out.")


__all__ = ["CHECKED", "FIELD", "SWITCH", "TITLE", "check", "checked", "draft_note", "on",
           "own_words", "promised"]
