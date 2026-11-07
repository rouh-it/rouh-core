"""What a waiting task is waiting on the person for, in the task's own words.

Petar, 22 September 2026: "some tasks are marked as "Waiting on you" after
completion of research or whatever. I am not sure what this is, how it is
triggered, what is the exact action I need to do and how do I get through it
so I am not needed."

A task is `waiting` when its row says the next move is the person's - its
status, kept in Rouh's database and set with `rouh-task status`
(`rouh/taskrecord.py`) - and the job that said so wrote the question into the
task's `AGENTS.md`, near the top, under Where this stands. The pill on the task
said Waiting and nothing else, so what was being asked was two presses and a
page of notes away, on eleven tasks at once.

This finds that passage and hands it back in two shapes: the passage itself,
as the Markdown it was written in, for the task's own page, and one plain line
for the task's row in the task browser. It reads and never writes, and it never
makes anything up: every word it returns is the notes' own, and a task whose
notes say nothing about what it waits on gets None, which the page says out
loud rather than drawing an empty box.

The notes are prose written by many runs over weeks, so there is no one shape
to parse. There are six that account for all of them, tried in this order,
and the first that finds anything wins:

1. A paragraph that opens with the mark - "**Waiting on Petar, two things.**",
   "**Waiting on the person:** whether ...", "**Status:** waiting on Petar,
   ...". The rule written into the workspace's own AGENTS.md on 24 September
   2026 asks every run to write it this way from now on.
2. A heading that is about it: "## Open questions for the user", "## Waiting
   on Petar". Its whole section.
3. A line that says it in the middle: "... and it is waiting on one line from
   Petar."
4. A line that opens "It asks": what a delivered step asks of him.
5. A line that opens "Open:": what is left open.
6. A heading that is only "Open": the same, as a section. Last, because it is
   the loosest of the six: task 44's notes list what they need from Petar
   under "## Open", and nothing before it finds them.

A paragraph that only introduces a list ("two things.") brings the list after
it, because the list is the question.

Whose name the notes use is the account's, not this file's. A workspace's
notes call its person by their name - "Waiting on Petar" in Petar's, "Waiting
on Mira" in Mira's - and until 24 September 2026 the name here was Petar's and
nobody else's, so Mira's Kvadrat task, whose notes open "**Waiting on Mira:**
whether the reception desk is oak or walnut veneer", was reported as saying
nothing about what it waits on, one press away from the notes that said it.
The caller says what the signed-in person is called (`names`), and "the
person", "the user", "you" and "him" are recognised for everybody.

The question, with its answers
------------------------------

Petar, 24 September 2026, looking at task 61's yellow box: "it is very
unstructured. ... easy options for answers predefined for me and option to
give my own. but right there. and it has to be clear what happens
afterwards." Prose cannot give him the options without guessing at them, so
whatever raises the question may also write it down with its shape, in the
task's meta (`question_of`):

    "question": {
      "ask": "Which way should the whole document be reviewed?",
      "options": [{"label": "Walk it as each buyer",
                   "detail": "About an hour: where a buyer gets stuck"}, ...],
      "several": true,
      "then": "A job starts the review you pick, as step 4."
    }

`ask` is the question in one sentence, `options` the answers he can pick with
one press (a plain string is a label with nothing under it), `several` whether
he may pick more than one, and `then` what answering will do. Every field may
be missing: a task with no `question` still gets its prose passage above and a
box to write his own answer in, and nothing here makes an option up.
"""
from __future__ import annotations

import functools
import re
from dataclasses import dataclass
from pathlib import Path

from . import instructions

#: The task's own notes, at the root of its folder: its AGENTS.md, or the
#: CLAUDE.md of a folder that has only that (`rouh/instructions.py`).
NOTES = instructions.NAME

#: How much of a question's shape is carried to the page. A question is one
#: sentence and an option a few words with a line under them; longer than this
#: is notes, and the notes are one press away.
ASK_MOST = 500
OPTIONS_MOST = 8
LABEL_MOST = 140
DETAIL_MOST = 400
THEN_MOST = 400

#: The most of the notes that is read. The passage is always near the top, and
#: a task's notes run to a few hundred lines at most.
MOST_READ = 256 * 1024

#: The longest the one line may be. The row clamps it to two lines on the
#: screen; this only keeps a runaway list from being carried to the page.
LINE_MOST = 280

#: The passage on the task's page. Longer than this is not the question any
#: more, it is the notes, and the notes are one press away under it.
BLOCK_MOST_LINES = 40

#: Who the notes say a task is waiting on, whoever the person is: the
#: workspace's template calls them "the person" and "the user", and the agent
#: instructions "the owner" when nobody's name is known (`rouh/owner.py`). Their own
#: name is added to these on every call, from their account (`names`).
_ANYONE = ("the person", "the user", "the owner", "you", "him")
#: What the start of a line may carry before its words: a list mark, bold, and
#: a "Status:" label.
_LEADING = r"^\s*(?:[-*+]\s+|\d{1,3}[.)]\s+)?(?:\*\*|__)?\s*(?:status:?\s*(?:\*\*|__)?\s*)?"
_ASKS_AT_START = re.compile(_LEADING + r"it asks\b", re.IGNORECASE)
_OPEN_AT_START = re.compile(_LEADING + r"open:", re.IGNORECASE)
_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_ABOUT_IT = re.compile(r"^(?:waiting on\b|open questions\b|questions for\b|what is open\b"
                       r"|what we need from\b|what is needed from\b)", re.IGNORECASE)
#: A heading that says only that what is under it is open (`_section`).
_OPEN_HEADING = re.compile(r"^(?:still )?open:?$", re.IGNORECASE)
_FENCE = re.compile(r"^\s*(```+|~~~+)")
_LIST_ITEM = re.compile(r"^\s*(?:[-*+]|\d{1,3}[.)])\s+(.*)$")

#: A lead that counts what follows, "two things.": then every sentence after
#: it is one of them, and the line says them all.
_COUNTED = re.compile(r"\b(?:two|three|four|five|six|several|\d+) (?:things|questions|decisions)\b", re.IGNORECASE)
#: A sentence that is the question rather than the setting around it.
_ASKING = re.compile(r"\b(?:whether|which|should|who|what|how|when)\b|\?", re.IGNORECASE)
_SENTENCE_END = re.compile(r"(?<=[.?!])\s+(?=[A-Z0-9\"'(])")


@dataclass(frozen=True)
class Ask:
    """What a task is waiting on, in two shapes."""

    #: The passage as it is written in the notes, for the task's page.
    markdown: str
    #: One plain line of it, for the task's row in the browser.
    line: str


@dataclass(frozen=True)
class Option:
    """One answer the person can pick with one press."""

    label: str
    #: A line under it: what picking it means, what it takes.
    detail: str = ""


@dataclass(frozen=True)
class Question:
    """What its meta says about the question, with its answers."""

    #: The question in one sentence, or "" when only the notes ask it.
    ask: str
    options: tuple[Option, ...]
    #: Whether more than one option may be picked together.
    several: bool
    #: What answering will do, in the words of whoever asked.
    then: str


def _words(value, most: int) -> str:
    """A string field, with its spaces tidied and cut to `most`, or ""."""
    if not isinstance(value, str):
        return ""
    return _cut(" ".join(value.split()), most)


def question_of(root, folder: str) -> Question | None:
    """The question's shape, from the task's meta (`rouh/taskmeta.py`), or None.

    None when there is no meta, no `question` in it, or nothing in that worth
    drawing. What is there is taken as far as it is sound: an option with no
    label is dropped rather than the whole question, and every string is cut
    to the most the page shows, because the file is written by a job and read
    into a page."""
    from . import taskmeta

    if not root or not folder:
        return None
    shape = taskmeta.get(folder, root).get("question")
    if not isinstance(shape, dict):
        return None
    options, seen = [], set()
    for one in shape.get("options") or []:
        if isinstance(one, str):
            one = {"label": one}
        if not isinstance(one, dict):
            continue
        label = _words(one.get("label"), LABEL_MOST)
        if not label or label.lower() in seen:
            continue
        seen.add(label.lower())
        options.append(Option(label=label, detail=_words(one.get("detail"), DETAIL_MOST)))
        if len(options) == OPTIONS_MOST:
            break
    question = Question(ask=_words(shape.get("ask"), ASK_MOST), options=tuple(options),
                        several=shape.get("several") is True and len(options) > 1,
                        then=_words(shape.get("then"), THEN_MOST))
    if not (question.ask or question.options or question.then):
        return None
    return question


@dataclass(frozen=True)
class _Marks:
    """The three patterns that name who a task waits on, for one person."""

    #: A line that opens with the mark: "Waiting on Mira", or "The ask", which
    #: is what a run writes when the whole of it is one thing to do.
    at_start: re.Pattern
    #: A line that says it in the middle: "... waiting on one line from Mira."
    inside: re.Pattern
    #: The words that open the passage and say only that it is waiting:
    #: "Waiting on Petar, two things." and "Waiting on the person:" both, up
    #: to the colon or the full stop, and a bare "Open:". What follows them is
    #: the question.
    lead: re.Pattern


def _called(names) -> tuple[str, ...]:
    """The names as the patterns want them: each one once, in lower case, with
    its spaces tidied, and the longest first so "mira koleva" is tried before
    "mira". A name of one letter is not a name anybody's notes wait on."""
    if isinstance(names, str):
        names = (names,)
    said = {" ".join(str(name or "").split()).lower() for name in names or ()}
    return tuple(sorted((n for n in said if len(n) > 1), key=lambda n: (-len(n), n)))


@functools.lru_cache(maxsize=64)
def _marks(names: tuple[str, ...]) -> _Marks:
    """The patterns for one person, made once for each set of names."""
    words =tuple(r"\s+".join(re.escape(part) for part in name.split())
                  for name in (*names, *_ANYONE))
    who = "(?:" + "|".join(words) + ")"
    # Not \b round a name: a name need not start and end with a letter, and
    # "Waiting on O'Brien (Jo):" is still a name followed by a colon.
    mark = r"(?:waiting on " + who + r"|the ask)(?!\w)"
    return _Marks(
        at_start=re.compile(_LEADING + mark, re.IGNORECASE),
        inside=re.compile(r"\bwaiting on\b[^.\n]{0,60}?(?<!\w)" + who + r"(?!\w)",
                          re.IGNORECASE),
        lead=re.compile(r"^(?:status:?\s*)?(?:" + mark + r"[^:.\n]{0,70}[:.]|open:)\s*",
                        re.IGNORECASE),
    )


def names_of(user) -> tuple[str, ...]:
    """What the workspace's notes may call this account's person.

    A waiting task's notes say who it waits on by name - "**Waiting on
    Mira:** whether the reception desk is oak or walnut veneer" - and that is
    how its question is found. The first name and the whole name on the
    account, which signing in with Google fills in, and the username, which
    for an account made with `manage.py account add` is most often the name
    itself in lower case. One helper for every caller, the task browser's
    pages and the rail's task rows alike (`owning.snapshot`), so the two can
    never find different questions in the same notes.
    """
    first = (getattr(user, "first_name", "") or "").strip()
    last = (getattr(user, "last_name", "") or "").strip()
    username = (getattr(user, "username", "") or "").strip()
    return tuple(name for name in (first, f"{first} {last}".strip(), username) if name)


def ask_of(root, folder: str, names=()) -> Ask | None:
    """What the task in this folder is waiting on, or None when its notes do
    not say, or it has no notes, or they cannot be read. `names` is what the
    person reading it is called (`ask_in`)."""
    if not root or not folder:
        return None
    path = instructions.in_folder(Path(str(root)) / folder)
    try:
        with open(path, "rb") as fh:
            text = fh.read(MOST_READ).decode("utf-8", "replace")
    except OSError:
        return None
    return ask_in(text, names)


def ask_in(text: str, names=()) -> Ask | None:
    """The same, from the notes' text.

    `names` is what the person is called - their first name, their whole
    name, their username - so that the notes' "Waiting on Mira" is found for
    Mira. "The person", "the user", "you" and "him" are found for anybody.
    """
    marks = _marks(_called(names))
    lines = _prose(str(text or "").replace("\r", "").split("\n"))
    block = (_opening_with(lines, marks.at_start, marks.lead) or _section(lines)
             or _opening_with(lines, marks.inside, marks.lead, search=True)
             or _all_opening_with(lines, _ASKS_AT_START)
             or _opening_with(lines, _OPEN_AT_START, marks.lead)
             or _section(lines, _OPEN_HEADING))
    if not block:
        return None
    block = block[:BLOCK_MOST_LINES]
    markdown = "\n".join(block).strip()
    line = one_line(block, names)
    if not markdown or not line:
        return None
    return Ask(markdown=markdown, line=line)


# ---------------------------------------------------------------------------
# Finding the passage
# ---------------------------------------------------------------------------


def _prose(lines: list[str]) -> list[str]:
    """The notes with every fenced block blanked, so a line of code that
    happens to say "waiting on you" is never taken for the question. The
    lines keep their places, so a paragraph still ends where it ended."""
    out, fenced = [], False
    for line in lines:
        if _FENCE.match(line):
            fenced = not fenced
            out.append("")
            continue
        out.append("" if fenced else line.rstrip())
    return out


def _paragraph_from(lines: list[str], at: int) -> tuple[list[str], int]:
    """The line at `at` and the lines after it in the same paragraph, and
    where the paragraph ends. A list item's own paragraph is that item and the
    lines wrapped under it, not the rest of the list."""
    out = [lines[at]]
    item = bool(_LIST_ITEM.match(lines[at]))
    i = at + 1
    while i < len(lines) and lines[i].strip() and not _HEADING.match(lines[i]):
        if _LIST_ITEM.match(lines[i]) or (item and not lines[i].startswith((" ", "\t"))):
            break
        out.append(lines[i])
        i += 1
    return out, i


def _list_after(lines: list[str], at: int) -> list[str]:
    """The list that starts at or just after `at`, with its wrapped lines and
    any list inside it, or nothing when what follows is not a list."""
    i = at
    while i < len(lines) and not lines[i].strip():
        i += 1
    if i >= len(lines) or not _LIST_ITEM.match(lines[i]):
        return []
    out = []
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            # A blank line inside a list keeps it going only when the list
            # carries on after it.
            j = i + 1
            while j < len(lines) and not lines[j].strip():
                j += 1
            if j < len(lines) and (_LIST_ITEM.match(lines[j]) or lines[j].startswith(("  ", "\t"))):
                i = j
                continue
            break
        if _HEADING.match(line):
            break
        if not (_LIST_ITEM.match(line) or line.startswith((" ", "\t"))):
            break
        out.append(line)
        i += 1
    return out


def _introduces(paragraph: list[str], lead: re.Pattern) -> bool:
    """Whether a paragraph only leads into the list after it: "Waiting on
    Petar, two things." rather than the question itself."""
    said = _plain(" ".join(s.strip() for s in paragraph))
    return said.endswith(":") or len(lead.sub("", said, count=1).strip()) < 12 or len(said) <= 60


def _opening_with(lines: list[str], mark: re.Pattern, lead: re.Pattern, *,
                  search: bool = False) -> list[str]:
    """The first paragraph whose line matches `mark`, from that line on, and
    the list after it when the paragraph only introduces one."""
    for at, line in enumerate(lines):
        if _HEADING.match(line):
            continue
        if not (mark.search(line) if search else mark.match(line)):
            continue
        paragraph, end = _paragraph_from(lines, at)
        if _introduces(paragraph, lead):
            listed = _list_after(lines, end)
            if listed:
                return paragraph + [""] + listed
        return paragraph
    return []


def _all_opening_with(lines: list[str], mark: re.Pattern) -> list[str]:
    """Every line that opens with `mark`, one paragraph each: a task with two
    delivered steps can have two things it asks."""
    out: list[str] = []
    for at, line in enumerate(lines):
        if _HEADING.match(line) or not mark.match(line):
            continue
        if out:
            out.append("")
        out.extend(_paragraph_from(lines, at)[0] if _LIST_ITEM.match(line) else [line])
    return out


def _section(lines: list[str], about: re.Pattern = _ABOUT_IT) -> list[str]:
    """The body of the first heading that is about what the task waits on,
    down to the next heading at its level or above."""
    for at, line in enumerate(lines):
        found = _HEADING.match(line)
        if not found or not about.match(_plain(found.group(2))):
            continue
        level = len(found.group(1))
        body = []
        for below in lines[at + 1:]:
            deeper = _HEADING.match(below)
            if deeper and len(deeper.group(1)) <= level:
                break
            body.append(below)
        while body and not body[0].strip():
            body.pop(0)
        while body and not body[-1].strip():
            body.pop()
        if body:
            return body
    return []


# ---------------------------------------------------------------------------
# The one line
# ---------------------------------------------------------------------------


def _plain(text: str) -> str:
    """Markdown's marks taken off, so the line reads as words."""
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"(\*\*|__)(.+?)\1", r"\2", text)
    text = re.sub(r"(?<![\w*])\*(?!\s)([^*\n]+?)\*(?!\w)", r"\1", text)
    text = text.replace("`", "")
    return re.sub(r"\s+", " ", text).strip()


def _bold_lead(item: str) -> str:
    """A list item's bold opening, when it has one: "**Which programme, how
    long.** Both steps say ..." is asking "Which programme, how long."."""
    found = re.match(r"^\s*(?:\*\*|__)(.+?)(?:\*\*|__)", item)
    return _plain(found.group(1)) if found else ""


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE_END.split(text) if s.strip()]


def _capital(text: str) -> str:
    return text[:1].upper() + text[1:] if text else text


def _cut(text: str, most: int = LINE_MOST) -> str:
    if len(text) <= most:
        return text
    return text[:most].rsplit(" ", 1)[0].rstrip(",;:") + "…"


def one_line(block: list[str], names=()) -> str:
    """The passage as one plain line: what the task is waiting on, and no
    more. A list says each of its items by its bold opening, or else by its
    first sentence; a paragraph says the sentence in it that asks something.
    `names` is what the person is called, as for `ask_in`, so the lead that
    names them is taken off the line."""
    opening = _marks(_called(names)).lead
    items: list[str] = []
    lead: list[str] = []
    for raw in block:
        found = _LIST_ITEM.match(raw)
        if found and not raw.startswith(("  ", "\t")):
            items.append(found.group(1))
        elif items and raw.strip() and raw.startswith((" ", "\t")):
            items[-1] += " " + raw.strip()
        elif not items and raw.strip():
            lead.append(raw.strip())
    said = _plain(" ".join(lead))
    rest = opening.sub("", said, count=1).strip()
    if items and (not rest or _introduces(lead, opening)):
        heads = []
        for item in items:
            head = _bold_lead(item) or (_sentences(_plain(item)) or [""])[0]
            if head:
                heads.append(_capital(head.rstrip(" :")))
        return _cut(" · ".join(heads))
    if not rest:
        # The mark is the whole of it: "Status: waiting on Petar, for item one
        # and for nothing else." It is still what the notes say.
        return _cut(_capital(re.sub(r"^status:?\s*", "", said, flags=re.IGNORECASE)))
    sentences = _sentences(rest)
    counted = opening.match(said)
    if counted and _COUNTED.search(counted.group(0)) and len(sentences) > 1:
        return _cut(" \u00b7 ".join(_capital(s) for s in sentences))
    asking = next((s for s in sentences if _ASKING.search(s)), sentences[0] if sentences else rest)
    return _cut(_capital(asking))
