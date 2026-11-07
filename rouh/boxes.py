"""The box: somewhere to put words the model never sees.

Petar, 13 October 2026 (fr_e7f2ebe1c141): "When I am doing stuff I want to be able to say give me
a box and save something there so LLM doesn't see it. So I summon a [text field] that saves the
content automatically to the database without LLM. This can be used for passwords that need to go
to env file or ideas that need to be revealed to LLM at a later point so there is no influence on
its answers."

So:

- **Saying "give me a box"** opens the Box page with an empty box ready to type or paste into. A
  message that is only that (`summoned`), typed or said aloud, is caught by code before the model
  reads it, and the model's own `open_box` does the same for any other way of asking. Either way the
  model knows a box was opened and nothing more.
- **What goes in goes straight to the database** from the page, over HTTP (`rouh/web/boxes.py`),
  never over the conversation's socket and never into a turn, a transcript, a log or an event. It is
  sealed with the instance's key before it reaches its row (`rouh/encryption.py`), the way every
  credential Rouh holds is, whichever kind of box it is.
- **Two kinds.** A *secret* - a password, a key on its way to an env file - is offered as a line to
  copy, `NAME=value` when its name looks like one. An *idea* is held back until the person chooses to
  give it to Rouh: Give to Rouh puts it in the message box, where they send it when they choose.
- **Each box has a number**, 1 for the person's first (Petar, the same day: "they should have
  identification, maybe numbers so that I can tell the LLM which box to open when needed").
- **The model reads a box only when the person names it.** `open_box` with a number gives Rouh
  what is in that box, and only in a turn the person started whose own words, said in this chat in
  the last few minutes, name that box by its number (`named`): never on its own initiative, and
  never because an email, a page or a job's report asked. From then on what is in it is part of that
  conversation, and the page says when and where it was given. Otherwise the model knows each box
  by its number, kind and size, and never by its name, which is the person's own words and could
  say as much as what is inside.

Only the person's own boxes, always asked for by their organisation and account together.

Handing a box to a job
----------------------

Petar, 2 November 2026: "things don't need to go in chat, you can simply use that info and pass it
around in files as you do work". So a job can be handed a box without what is in it ever passing
through a model, a brief or a log:

- **`assistant_job`, `one_start` and `delegate_task` take `boxes`**, a list of box numbers or names
  ("rouh-land-server", matched without regard to case). Each counts only when the person's own recent
  words in this chat name that box, by its number or by its name: the same check, and the same window,
  `open_box` uses (`for_job`). A name that matches no box, or more than one, hands nothing over.
- **Code, not the model, puts each box in the job's own folder**, at `.secrets/box-<number>`, mode 0600
  and owned by the job's user, in a folder of mode 0700 with a `.gitignore` of `*`. A run of the one
  program collects its boxes from Rouh once, over this machine only, with a one-time key the brief never
  sees (`collect`, `/internal/boxes/collect`, `one/runs.py`); a worker of the crew is written them by
  Rouh itself (`crew.spawn`). The brief says only the path and the box's name (`brief_lines`).
- **When the job ends**, done, failed or stopped, the files are overwritten and deleted (`shred_folder`
  here, `one/sealed.py` there), and the job's transcript and log are scrubbed of anything the files held
  first. A restart sweeps any left behind, and a key nobody collected within a day is dropped (`sweep`).
- **What leaks anyway is redacted** (`redact`): Rouh's own log lines, through a filter on its handlers
  (`_Redactor`), a job's report as it comes back (`redact_run`), and a run's transcript as the one program
  reads it.
- **Every hand-over is a row** (`models.BoxHandover`): the box, the job and when, never what was in it.
  The Boxes page says when each box was last used.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import os
import re
import secrets as _random
import threading
import time

from .encryption import box as _sealer

log = logging.getLogger("rouh.boxes")

#: The two kinds of box, and what the page calls each.
KINDS = {"secret": "Secret", "idea": "Idea"}
#: The most characters one box may hold, and its name.
MOST = 100_000
LABEL_MOST = 120

#: A message that is only a request for a box: "give me a box", "Rouh, a new box please", "open a box",
#: "box". Said aloud it arrives with a full stop or a question mark, and sometimes as "text box".
_SUMMON = re.compile(
    r"^\s*(?:(?:hey\s+|ok(?:ay)?\s+)?rouh[\s,.:!-]+)?(?:please\s+)?"
    r"(?:(?:can|could|may)\s+(?:i|you)\s+(?:have|get|give\s+me|open)\s+|"
    r"(?:give|get|bring|open|show|summon|make|create|start)\s+(?:me\s+|up\s+)?|i\s+(?:need|want)\s+)?"
    r"(?:a\s+new|a|an|the|another|one|new|my)?\s*(?:secret\s+|text\s+|private\s+)?box"
    r"(?:[\s,]+please)?[\s.!?]*$",
    re.IGNORECASE)


class NotFound(LookupError):
    pass


class NotNamed(PermissionError):
    """The model asked to open a box the person did not name."""

#: How recent the person's words naming a box must be, and how many of their messages are read.
NAMED_SECONDS = 10 * 60
NAMED_MOST = 3

_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
          "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13, "fourteen": 14,
          "fifteen": 15, "sixteen": 16, "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20,
          "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5}
_NUM = r"(?:\d+|" + "|".join(sorted(_WORDS, key=len, reverse=True)) + r")"
#: "box 3", "box number three", "box #3", "boxes 2 and 3", "box no. 4", "boxes 1, 2, 5".
_NAMED = re.compile(r"\bbox(?:es)?\s*(?:number|num\.?|no\.?|#)?\s*(" + _NUM +
                    r"(?:\s*(?:,|and|&|\+|or)\s*(?:number\s+|#\s*)?" + _NUM + r")*)\b", re.IGNORECASE)
_ONE = re.compile(_NUM, re.IGNORECASE)


def named(text: str) -> set[int]:
    """Every box number the words name: "open box 3", "box number three", "boxes 2 and 4"."""
    out: set[int] = set()
    for got in _NAMED.finditer(str(text or "")):
        for n in _ONE.findall(got.group(1)):
            n = n.lower()
            out.add(int(n) if n.isdigit() else _WORDS[n])
    return out


def summoned(text: str) -> bool:
    """Whether a whole message is only asking for a box."""
    words = str(text or "").strip()
    return bool(words) and len(words) <= 60 and bool(_SUMMON.match(words))


# --- whose ---------------------------------------------------------------------------------------


def _mine(who):
    from .models import Box

    return Box.objects.filter(org_id=str(who.org_id), user_id=str(who.user_id))


def _by_number(who, number):
    try:
        number = int(str(number).strip().lstrip("#"))
    except (TypeError, ValueError):
        raise NotFound("Which box? Give its number.") from None
    b = _mine(who).filter(number=number).first()
    if b is None:
        raise NotFound(f"There is no box {number}.")
    return b


def _get(who, ident):
    try:
        ident = int(str(ident).strip().lstrip("#"))
    except (TypeError, ValueError):
        raise NotFound("There is no such box.") from None
    b = _mine(who).filter(id=ident).first()
    if b is None:
        raise NotFound(f"There is no box {ident}.")
    return b


def _view(b, used: dict | None = None) -> dict:
    """A box as the page lists it: everything but what is in it.

    `used` is its last hand-over to a job (`_last_uses`), when it has had one.
    """
    used = used or {}
    return {"id": b.id, "number": b.number, "label": b.label, "kind": b.kind,
            "kind_said": KINDS.get(b.kind, b.kind), "size": b.size, "made_at": b.made_at,
            "updated_at": b.updated_at, "given_at": b.given_at, "given_chat": b.given_chat,
            "used_at": used.get("made_at"), "used_run": used.get("run_id") or "",
            "used_via": used.get("via") or "", "used_ended": used.get("ended") or ""}


def _last_uses(who) -> dict[int, dict]:
    """Each box's last hand-over to a job, by the box's id."""
    from .models import BoxHandover

    out: dict[int, dict] = {}
    rows = (BoxHandover.objects.filter(org_id=str(who.org_id), user_id=str(who.user_id))
            .exclude(ended="not started").order_by("-made_at")
            .values("box_id", "made_at", "run_id", "via", "ended"))
    for row in rows[:2000]:
        out.setdefault(row["box_id"], row)
    return out


# --- reading -------------------------------------------------------------------------------------


def listing(who) -> dict:
    """Every box of theirs, newest first, none of them opened."""
    used = _last_uses(who)
    every = [_view(b, used.get(b.id)) for b in _mine(who).order_by("-number", "-id")]
    return {"boxes": every, "count": len(every)}


def count(who) -> int:
    return _mine(who).count()


def opened(who, ident) -> dict:
    """One box with what is in it, for the person's own page and nothing else."""
    b = _get(who, ident)
    return dict(_view(b), content=_sealer().open_(b.sealed))


# --- keeping and changing -----------------------------------------------------------------------


def _label(label) -> str:
    return " ".join(str(label or "").split())[:LABEL_MOST]


def _kind(kind) -> str:
    kind = str(kind or "secret").strip().lower()
    if kind not in KINDS:
        raise ValueError("A box is a secret or an idea.")
    return kind


def _content(content) -> str:
    content = str(content or "").replace("\x00", "")
    if not content.strip():
        raise ValueError("The box is empty. Type or paste what goes in it.")
    if len(content) > MOST:
        raise ValueError(f"A box holds at most {MOST:,} characters.")
    return content


def add(who, content, *, label="", kind="secret") -> dict:
    """Keep what was put in a box, sealed, under the next number. Returns it as the page lists it."""
    from django.db import IntegrityError, transaction
    from django.db.models import Max

    from .models import Box

    content = _content(content)
    label, kind, sealed = _label(label), _kind(kind), _sealer().seal(content)
    for _try in range(5):
        now = time.time()
        number = (_mine(who).aggregate(n=Max("number"))["n"] or 0) + 1
        try:
            with transaction.atomic():
                b = Box.objects.create(org_id=str(who.org_id), user_id=str(who.user_id), number=number,
                                       label=label, kind=kind, sealed=sealed, size=len(content),
                                       made_at=now, updated_at=now)
            return _view(b)
        except IntegrityError:
            # Two boxes saved at the same moment took the same number: the next one is free.
            continue
    raise ValueError("The box could not be numbered. Try again in a moment.")


def change(who, ident, *, label=None, kind=None, content=None) -> dict:
    """Rename a box, change its kind, or put something else in it."""
    b = _get(who, ident)
    if label is not None:
        b.label = _label(label)
    if kind is not None:
        b.kind = _kind(kind)
    if content is not None:
        content = _content(content)
        b.sealed = _sealer().seal(content)
        b.size = len(content)
    b.updated_at = time.time()
    b.save()
    return _view(b)


def delete(who, ident) -> None:
    _get(who, ident).delete()


# --- Rouh, when the person names a box ------------------------------------------------------------


def for_model(who) -> str:
    """Their boxes as Rouh may know them: number, kind, size and whether it was given. Never a name."""
    lines = []
    for b in _mine(who).order_by("number"):
        given = " (given to you once already)" if b.given_at else ""
        lines.append(f"box {b.number}: {KINDS.get(b.kind, b.kind).lower()}, {b.size} characters{given}")
    return "\n".join(lines)


def _recent(said: list[tuple[float, str]]) -> list[str]:
    """The person's own words that may name a box: their last few messages of the last few minutes."""
    lately = time.time() - NAMED_SECONDS
    return [text for at, text in said if at >= lately][-NAMED_MOST:]


def open_for_rouh(who, number, said: list[tuple[float, str]], chat: str) -> dict:
    """What is in box `number`, for the model, when the person's own recent words name it.

    `said` is what the person said in this chat, oldest first, with when (`signups.said_in`):
    only their last few messages of the last few minutes count. Marks the box as given, in `chat`.
    """
    b = _by_number(who, number)
    recent = _recent(said)
    if not any(b.number in named(text) for text in recent):
        raise NotNamed(
            f"The person has not named box {b.number} in their own words just now, so it stays shut. "
            f"A box is opened only when they say its number themselves, such as \"open box {b.number}\".")
    b.given_at = time.time()
    b.given_chat = str(chat or "")
    b.save(update_fields=["given_at", "given_chat"])
    return dict(_view(b), content=_sealer().open_(b.sealed))


async def tell(who) -> None:
    """Every open tab of this person's: their boxes changed, so an open Boxes page reads them again."""
    import asyncio

    from . import runtime

    try:
        n = await asyncio.to_thread(count, who)
        await runtime.push_person(who, {"type": "boxes", "count": n})
    except Exception:  # noqa: BLE001 - a page that missed it reads them when opened
        log.exception("the boxes could not be told to the person's tabs")


# --- handing a box to a job ------------------------------------------------------------------------

#: Where a job finds its boxes, inside the folder it starts in, and what each file is called.
SECRETS_DIR = ".secrets"
#: The most boxes one job may be handed.
JOB_MOST = 10
#: How long a job has to collect what it was handed before the key is dropped. A run of the one
#: program can wait in its queue behind another working on the same files.
COLLECT_SECONDS = 24 * 60 * 60
#: What a box's contents become wherever they turn up anyway.
REDACTED = "[box {n}, redacted]"
#: Contents shorter than this are not looked for: a box holding "1" would blank every 1 in a log.
REDACT_LEAST = 4


def file_name(number: int) -> str:
    return f"box-{int(number)}"


def file_path(number: int) -> str:
    """The path a job is told, relative to the folder it starts in."""
    return f"{SECRETS_DIR}/{file_name(number)}"


def _hash(key: str) -> str:
    return hashlib.sha256(str(key or "").encode("utf-8")).hexdigest()


def _said_name(b) -> str:
    return " ".join(str(b.label or "").split())


def _names_it(b, text: str) -> bool:
    """Whether the person's words name box `b`: by its number, or by its name as words of their own."""
    if b.number in named(text):
        return True
    name = _said_name(b)
    if not name:
        return False
    pattern = r"(?<![\w-])" + r"\s+".join(re.escape(w) for w in name.split()) + r"(?![\w-])"
    return bool(re.search(pattern, str(text or ""), re.IGNORECASE))


def _one_asked(who, asked) -> object:
    """One box, by a number or by its name, case-insensitive. Raises `NotFound` saying why."""
    if isinstance(asked, bool):
        raise NotFound("A box is asked for by its number or its name.")
    if isinstance(asked, int):
        return _by_number(who, asked)
    text = " ".join(str(asked or "").split())
    if not text:
        raise NotFound("A box is asked for by its number or its name.")
    bare = text.lstrip("#").strip()
    if re.fullmatch(r"(?:box\s*)?\d+", bare, re.IGNORECASE):
        return _by_number(who, re.sub(r"\D", "", bare))
    want = text.casefold()
    hits = [b for b in _mine(who).order_by("number") if _said_name(b).casefold() == want]
    if not hits:
        raise NotFound(f'No box is called "{text}".')
    if len(hits) > 1:
        numbers = ", ".join(str(b.number) for b in hits)
        raise NotFound(f'{len(hits)} boxes are called "{text}" (boxes {numbers}), so it is not '
                       "clear which one is meant. Name it by its number.")
    return hits[0]


def for_job(who, asked, said: list[tuple[float, str]], *, chat: str = "", via: str = "") -> dict:
    """Hand the boxes `asked` (numbers or names) to a job about to start.

    Every box must be one the person's own recent words in this chat name (`_names_it`, in the window
    `open_box` reads, `_recent`), or nothing at all is handed over and `NotNamed` says which. Each box
    becomes one `BoxHandover` row under one new grant. Returns the one-time key the job's files are
    collected with (`collect`), its hash, and each box's number, name and path, never what is in it.
    """
    from .models import BoxHandover

    sweep()
    if not isinstance(asked, (list, tuple)):
        asked = [asked]
    asked = [a for a in asked if a not in (None, "")]
    if not asked:
        raise NotFound("No box was named.")
    if len(asked) > JOB_MOST:
        raise NotFound(f"A job may be handed at most {JOB_MOST} boxes.")
    picked, seen = [], set()
    for one in asked:
        b = _one_asked(who, one)
        if b.id not in seen:
            seen.add(b.id)
            picked.append(b)
    recent = _recent(said)
    unnamed = [b for b in picked if not any(_names_it(b, text) for text in recent)]
    if unnamed:
        which = ", ".join(f"box {b.number}" for b in unnamed)
        raise NotNamed(
            f"The person has not named {which} in their own words just now, so nothing was handed "
            "over. A box goes to a job only when they name it themselves, by its number or its name, "
            "such as \"use box " + str(unnamed[0].number) + "\".")
    key = _random.token_urlsafe(32)
    grant, now = _hash(key), time.time()
    for b in picked:
        BoxHandover.objects.create(org_id=str(who.org_id), user_id=str(who.user_id), box_id=b.id,
                                   number=b.number, label=_said_name(b), grant=grant,
                                   via=str(via or "")[:60], chat=str(chat or "")[:200], made_at=now)
    log.info("boxes: %s handed to a job by %s (grant %s), not yet collected",
             ", ".join(str(b.number) for b in picked), via or "a tool", grant[:12])
    return {"key": key, "grant": grant,
            "boxes": [{"number": b.number, "name": _said_name(b), "path": file_path(b.number)}
                      for b in picked]}


def brief_lines(handed: dict) -> str:
    """What the job's brief says about its boxes: each one's name and path, and nothing else."""
    lines = []
    for one in handed.get("boxes") or []:
        name = f' ("{one["name"]}")' if one.get("name") else ""
        lines.append(f"- Box {one['number']}{name}: the file {one['path']}")
    if not lines:
        return ""
    return ("Boxes handed to you. The person named these boxes for this job. Each is a file in the "
            "folder you start in, readable only by you, and it is shredded when you finish. Use them "
            "as your agent instructions say for a box handed to a job: never print or log what is in "
            "one, and feed it in only through stdin or a file.\n" + "\n".join(lines))


def started(grant: str, run_id: str) -> None:
    """The job a grant went to, once it has an id."""
    from .models import BoxHandover

    BoxHandover.objects.filter(grant=str(grant or ""), run_id="").update(run_id=str(run_id or "")[:80])


def not_started(grant: str) -> None:
    """Nothing took the job: its grant can never be collected."""
    from .models import BoxHandover

    BoxHandover.objects.filter(grant=str(grant or ""), ended_at=None).update(
        ended_at=time.time(), ended="not started")


class NotCollected(LookupError):
    """A key that collects nothing: unknown, spent, or older than `COLLECT_SECONDS`."""


def collect(key: str, run_id: str = "") -> list[dict]:
    """What a grant's boxes hold, once, for the code writing them into the job's folder.

    The one place a box's contents leave Rouh for a job, and it is code asking: the one program
    for its run (`/internal/boxes/collect`), or Rouh's crew in its own process. A key is spent the
    first time, so a model that saw it later could collect nothing. Each box's contents are added
    to what Rouh's log redacts (`_Redactor`).
    """
    from django.db import transaction

    from .models import Box, BoxHandover

    grant, now = _hash(key), time.time()
    if not key:
        raise NotCollected("No key was given.")
    with transaction.atomic():
        rows = list(BoxHandover.objects.select_for_update().filter(
            grant=grant, handed_at=None, ended_at=None))
        if not rows:
            raise NotCollected("That key collects nothing: it is unknown or already spent.")
        if any(now - r.made_at > COLLECT_SECONDS for r in rows):
            BoxHandover.objects.filter(grant=grant, ended_at=None).update(ended_at=now, ended="expired")
            raise NotCollected("That key was not collected within a day, so it was dropped.")
        out = []
        for r in rows:
            b = Box.objects.filter(id=r.box_id, org_id=r.org_id, user_id=r.user_id).first()
            if b is None:
                raise NotCollected(f"Box {r.number} is not there any more.")
            content = _sealer().open_(b.sealed)
            remember(r.number, content)
            out.append({"number": r.number, "name": r.label, "content": content})
        fields = {"handed_at": now}
        BoxHandover.objects.filter(grant=grant, handed_at=None).update(**fields)
        if run_id:
            BoxHandover.objects.filter(grant=grant, run_id="").update(run_id=str(run_id)[:80])
    log.info("boxes: %s collected for job %s (grant %s)", ", ".join(str(o["number"]) for o in out),
             run_id or "?", grant[:12])
    return sorted(out, key=lambda o: o["number"])


def ended(run_id: str = "", *, key: str = "", grant: str = "", how: str = "shredded") -> int:
    """A job's boxes were shredded: its rows say so. By the job, its key or its grant."""
    from .models import BoxHandover

    q = BoxHandover.objects.filter(ended_at=None)
    if key:
        q = q.filter(grant=_hash(key))
    elif grant:
        q = q.filter(grant=str(grant))
    elif run_id:
        q = q.filter(run_id=str(run_id))
    else:
        return 0
    return q.update(ended_at=time.time(), ended=how)


def sweep() -> int:
    """Drop every key nobody collected within `COLLECT_SECONDS`. Run as Rouh starts and now and then."""
    from .models import BoxHandover

    return BoxHandover.objects.filter(handed_at=None, ended_at=None,
                                      made_at__lt=time.time() - COLLECT_SECONDS).update(
        ended_at=time.time(), ended="expired")


def handed_to(run_id: str) -> list[tuple[int, str]]:
    """What was in each box handed to job `run_id`, for redacting what it says. Never shown."""
    from .models import Box, BoxHandover

    if not run_id:
        return []
    out = []
    for r in BoxHandover.objects.filter(run_id=str(run_id)).exclude(handed_at=None):
        b = Box.objects.filter(id=r.box_id, org_id=r.org_id, user_id=r.user_id).first()
        if b is not None:
            with contextlib.suppress(Exception):
                out.append((r.number, _sealer().open_(b.sealed)))
    return out


# --- redacting -------------------------------------------------------------------------------------


def redact(text, pairs) -> str:
    """`text` with every exact contents in `pairs` ((number, contents), ...) replaced, whether it is
    there as it is or as JSON writes it inside a string."""
    if not text or not pairs:
        return text
    out = str(text)
    for number, content in sorted(pairs, key=lambda p: -len(p[1] or "")):
        if not content or len(content) < REDACT_LEAST:
            continue
        mark = REDACTED.format(n=number)
        for form in {content, content.strip(), json.dumps(content)[1:-1],
                     json.dumps(content, ensure_ascii=False)[1:-1]}:
            if form and len(form) >= REDACT_LEAST and form in out:
                out = out.replace(form, mark)
    return out


def redact_run(run_id: str, text: str) -> str:
    """What job `run_id` said, with anything a box handed to it held taken out."""
    if not text or not run_id:
        return text
    try:
        pairs = handed_to(run_id)
    except Exception:  # noqa: BLE001 - a report is never lost to its own redaction
        log.exception("boxes: what was handed to %s could not be read to redact its report", run_id)
        return text
    return redact(text, pairs)


_held: dict[int, set[str]] = {}
_held_lock = threading.Lock()


def remember(number: int, content: str) -> None:
    """Contents Rouh's own log must never carry, from the moment they are collected."""
    if not content or len(content) < REDACT_LEAST:
        return
    with _held_lock:
        _held.setdefault(int(number), set()).add(content)
    _install_redactor()


def _held_pairs() -> list[tuple[int, str]]:
    with _held_lock:
        return [(n, c) for n, cs in _held.items() for c in cs]


class _Redactor(logging.Filter):
    """Every line Rouh logs, with what a box handed to a job held taken out (`remember`)."""

    def filter(self, record: logging.LogRecord) -> bool:
        pairs = _held_pairs()
        if not pairs:
            return True
        try:
            said = record.getMessage()
        except Exception:  # noqa: BLE001 - a line that cannot be formatted is left to its handler
            return True
        clean = redact(said, pairs)
        if clean != said:
            record.msg, record.args = clean, ()
        if record.exc_info and not record.exc_text:
            record.exc_text = logging.Formatter().formatException(record.exc_info)
        if record.exc_text:
            record.exc_text = redact(record.exc_text, pairs)
        return True


_REDACTOR = _Redactor()


def _install_redactor() -> None:
    """On every handler of the root logger, once each: a filter on a logger misses its children."""
    for handler in logging.getLogger().handlers:
        if _REDACTOR not in handler.filters:
            handler.addFilter(_REDACTOR)


# --- the files, for a worker of the crew, which Rouh writes itself --------------------------------


def write_folder(folder: str, given: list[dict], owner: str | None = None) -> list[str]:
    """Put each box in `given` at `<folder>/.secrets/box-<n>`: the folder 0700, each file 0600,
    with a `.gitignore` of `*`, all handed to `owner` when the job runs as another user."""
    import shutil

    where = os.path.join(folder, SECRETS_DIR)
    os.makedirs(where, mode=0o700, exist_ok=True)
    os.chmod(where, 0o700)
    written = []
    with open(os.path.join(where, ".gitignore"), "w") as fh:
        fh.write("*\n")
    for one in given:
        path = os.path.join(where, file_name(one["number"]))
        with contextlib.suppress(OSError):
            os.unlink(path)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(one["content"])
        os.chmod(path, 0o600)
        written.append(path)
    if owner:
        for path in [where, os.path.join(where, ".gitignore"), *written]:
            try:
                shutil.chown(path, user=owner, group=owner)
            except Exception as exc:  # noqa: BLE001 - said, and the job reads what it can
                log.warning("boxes: %s could not be handed to %s: %s", path, owner, exc)
    return written


def read_folder(folder: str) -> list[tuple[int, str]]:
    """What the box files in `<folder>/.secrets` hold, for scrubbing before they are shredded."""
    where = os.path.join(folder, SECRETS_DIR)
    out = []
    try:
        names = os.listdir(where)
    except OSError:
        return []
    for name in names:
        m = re.fullmatch(r"box-(\d+)", name)
        if not m:
            continue
        try:
            with open(os.path.join(where, name), encoding="utf-8", errors="replace") as fh:
                out.append((int(m.group(1)), fh.read()))
        except OSError:
            continue
    return out


def _shred(path: str) -> None:
    """Overwrite a file with random bytes, flush it to disk, then unlink it."""
    try:
        size = os.lstat(path).st_size
        if os.path.islink(path):
            os.unlink(path)
            return
        with open(path, "r+b", buffering=0) as fh:
            for _ in range(2):
                fh.seek(0)
                fh.write(os.urandom(max(size, 1)))
                os.fsync(fh.fileno())
    except OSError:
        pass
    with contextlib.suppress(OSError):
        os.unlink(path)


def scrub_file(path: str, pairs) -> bool:
    """Rewrite a text file with what `pairs` held redacted, in place. True when it changed."""
    try:
        with open(path, encoding="utf-8", errors="surrogateescape") as fh:
            text = fh.read()
    except OSError:
        return False
    clean = redact(text, pairs)
    if clean == text:
        return False
    try:
        mode = os.stat(path).st_mode & 0o777
        tmp = path + ".scrub"
        with open(tmp, "w", encoding="utf-8", errors="surrogateescape") as fh:
            fh.write(clean)
        os.chmod(tmp, mode)
        os.replace(tmp, path)
        return True
    except OSError as exc:
        log.warning("boxes: %s could not be scrubbed: %s", path, exc)
        return False


def shred_folder(folder: str, also: list[str] | tuple = ()) -> int:
    """Scrub the files in `also` of what the box files hold, then shred the box files and their
    folder. Returns how many boxes were shredded. Safe on a folder with none."""
    import shutil

    where = os.path.join(folder, SECRETS_DIR)
    if not os.path.isdir(where) or os.path.islink(where):
        return 0
    pairs = read_folder(folder)
    for path in also:
        if path and os.path.isfile(path):
            scrub_file(path, pairs)
    count = 0
    for name in os.listdir(where):
        _shred(os.path.join(where, name))
        count += name.startswith("box-")
    shutil.rmtree(where, ignore_errors=True)
    return count
