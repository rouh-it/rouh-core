"""The worker outbox: what a background job asks Rouh to email the person.

A background job - `assistant_job`, `delegate_task`, `improve_myself`, whether
the one program ran it or the crew did - is Claude Code working unattended, and
it cannot send mail. That is on purpose, and every reason for it stays exactly
as it is:

- it has no Google token: `google_store` seals the access and refresh tokens
  with `encryption.SecretBox` and hands them to nothing but Rouh's own calls
  to Google;
- it may not read the server's .env, which holds the database login and the
  encryption key;
- this machine has no mail transfer agent;
- `send_mail` exists only in Rouh's own turn loop.

So until 24 September 2026 a job told "email the owner the summary" dead-ended,
and said in its last message that it could not. Now it queues the text here,
and delivering it stays Rouh's obligation.

How a note goes
---------------

1. The job calls ``notify_owner(subject, body)``, the one tool of the ``rouh``
   MCP server every worker on this machine is given (`rouh/worker_mcp.py`,
   listed in `mcp-servers.json`). That posts to ``/internal/outbox`` here, and
   `queue` writes one pending row tagged with the job's own id. The id comes
   from the worker's environment, which the program that started it set, never
   from anything the model wrote.
2. When the job's report reaches Rouh's conversation - "A job has finished:
   ..." - its pending notes go with it, with their subject, their body and
   their ids (`with_notes`), so Rouh has the text in hand in the same turn.
3. Rouh says who it would go to and what it says, and on the person's yes sends
   it with its own `send_mail`, then marks the row sent with the id Gmail gave
   (`worker_outbox` in `rouh/tools.py`). A note they do not want is dismissed.

What a note can never do
------------------------

- **Choose where it goes.** There is no recipient anywhere in this path: not a
  column, not an argument of the tool, not a field the endpoint reads. It goes
  to the person's own address, which Rouh works out when it sends
  (`recipient`). A job that has read a hostile web page or a poisoned file can
  put words in a note; it cannot make Rouh mail a stranger.
- **Send itself.** A queued note is a request to send, never a send. Nothing in
  this module talks to Gmail, and a row is marked sent only by Rouh's own tool,
  after `send_mail` has sent it to that address in a turn the person is in.
- **Mark anything.** The one door a worker can reach writes pending rows and
  nothing else.

That door is held to `from_this_machine`, the same as the hooks every worker
already posts to, and no stricter. A worker set on it could post with another
job's id rather than its own, as it could post another job's hook. The worst
that buys is a pending note, for the person, beside the wrong job's report:
still read out, still asked about, still only ever sent to them.
"""
from __future__ import annotations

import contextlib
import logging
import re
import time
from contextvars import ContextVar
from typing import Iterable

from django.db import transaction

from . import untrusted

log = logging.getLogger("rouh.outbox")

#: The longest subject kept. A subject is a line, not a paragraph.
MAX_SUBJECT = 200
#: The longest body taken. A note longer than this is refused with a sentence
#: rather than cut, because a cut email says something its writer did not.
MAX_BODY = 20_000
#: How many notes one job may have waiting at once. A job that means to send
#: an email queues one; a job queueing its sixth is going round in a loop, and
#: the person should not have six of them read out to them.
MAX_PENDING = 5

#: Whose words a note's body is, for the box it is quoted in (`untrusted.wrap`).
#: A job may have read anything at all before it wrote them.
SOURCE = untrusted.SOURCES["worker_outbox"]

#: What Rouh is told to do with a note, wherever it reads one. The same
#: standing rule `send_mail` carries: say who and what, and ask.
ASK_FIRST = (
    "Tell them the job has an email ready for them, say that address and the gist, "
    "and ask whether to send it. Only on their yes, send it with send_mail to that "
    "address and nobody else, as the job wrote it, then call worker_outbox with "
    "action sent, the note's id and the message id send_mail gave. If they do not "
    "want it, mark it dismissed.")

#: And on a job's report, where the address is not in front of Rouh yet.
HOW_TO_SEND = (
    "A job cannot send mail and cannot choose where it goes: a note only ever goes "
    "to the person themselves. worker_outbox with action list says their address. "
    + ASK_FIRST)

_ADDRESS = re.compile(r"[A-Za-z0-9._%+'-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")

#: The words a remembered fact's key may be made of and still be the person's
#: own address: "email", "my email address", "the person's email". A key that
#: names anybody else - "sam's email" - has a word outside this set, and is
#: somebody else's address, which is never where a note goes.
_OWN_WORDS = {"my", "own", "the", "person", "persons", "user", "users", "owner",
              "owners", "primary", "personal", "work", "main", "email", "e", "mail",
              "address", "addr"}


class Refused(ValueError):
    """What could not be done, as the sentence to hand back."""


def _models():
    from .models import Crewmate, Run, WorkerNote

    return Crewmate, Run, WorkerNote


def _known(job_id: str) -> bool:
    """Whether Rouh knows this job: a row in the run register or the crew's own.

    Both are asked of the database directly, whatever the register's switch
    says, so a note is never refused for a job that is really there.
    """
    Crewmate, Run, _ = _models()
    return (Run.objects.filter(id=job_id).exists()
            or Crewmate.objects.filter(id=job_id).exists())


def as_dict(row) -> dict:
    return {"id": row.id, "job": row.job_id, "created_at": row.created_at,
            "subject": row.subject, "body": row.body, "status": row.status,
            "sent_at": row.sent_at, "message_id": row.message_id}


def queue(job_id: str, subject: str, body: str) -> dict:
    """Write one pending note for a job. The only write a worker can cause.

    Raises `Refused` with the sentence to hand back to the job: it has no job
    to belong to, the job is not one Rouh knows, it is empty or too long, or the
    job already has as many notes waiting as it may.
    """
    job_id = str(job_id or "").strip()
    subject = " ".join(str(subject or "").split())
    body = str(body or "").strip()
    if not job_id:
        raise Refused(
            "This is not a background job Rouh started, so there is no report for a "
            "note to go with. Put what you wanted to send in your last message.")
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,80}", job_id):
        raise Refused("That is not a job id.")
    if not subject:
        raise Refused("Give the note a subject: one short line saying what it is about.")
    if not body:
        raise Refused("The note is empty. Write the email the person should read.")
    if len(body) > MAX_BODY:
        raise Refused(
            f"The note is {len(body):,} characters, and a note may be at most "
            f"{MAX_BODY:,}. Shorten it to what the person needs to read.")
    subject = subject[:MAX_SUBJECT]
    _, _, WorkerNote = _models()
    if not _known(job_id):
        raise Refused(f"Rouh has no job {job_id}, so the note has nowhere to go.")
    with transaction.atomic():
        waiting = WorkerNote.objects.filter(job_id=job_id, status="pending").count()
        if waiting >= MAX_PENDING:
            raise Refused(
                f"This job already has {waiting} notes waiting to be sent, which is as "
                "many as one job may have. Say the rest in your last message.")
        row = WorkerNote.objects.create(job_id=job_id, created_at=time.time(),
                                        subject=subject, body=body)
    log.info("job %s queued note %s for the person: %r (%d characters)",
             job_id, row.id, subject[:80], len(body))
    return {"id": row.id, "job": job_id, "status": row.status}


def pending(job_id: str = "") -> list[dict]:
    """The notes still waiting, oldest first: one job's, or everybody's."""
    _, _, WorkerNote = _models()
    rows = WorkerNote.objects.filter(status="pending")
    if job_id:
        rows = rows.filter(job_id=str(job_id))
    return [as_dict(row) for row in rows.order_by("created_at", "id")[:50]]


def get(note_id: int) -> dict | None:
    _, _, WorkerNote = _models()
    row = WorkerNote.objects.filter(id=note_id).first()
    return as_dict(row) if row is not None else None


def mark(note_id: int, status: str, message_id: str = "") -> dict:
    """Say what became of a note: sent, with the id Gmail gave, or dismissed.

    Only a pending note can be marked, and only once. Called by Rouh's own tool
    and by nothing a worker can reach.
    """
    if status not in ("sent", "dismissed"):
        raise Refused("A note is marked sent or dismissed, and nothing else.")
    message_id = str(message_id or "").strip()[:200]
    if status == "sent" and not message_id:
        raise Refused("Say the message id send_mail gave: a note is marked sent only "
                      "once it has really gone.")
    _, _, WorkerNote = _models()
    with transaction.atomic():
        row = WorkerNote.objects.select_for_update().filter(id=note_id).first()
        if row is None:
            raise Refused(f"There is no note {note_id}.")
        if row.status != "pending":
            raise Refused(f"Note {note_id} is already {row.status}.")
        row.status = status
        fields = ["status"]
        if status == "sent":
            row.sent_at = time.time()
            row.message_id = message_id
            fields += ["sent_at", "message_id"]
        row.save(update_fields=fields)
    log.info("note %s from job %s marked %s%s", row.id, row.job_id, status,
             f" (message {message_id})" if message_id else "")
    return as_dict(row)


# ---------------------------------------------------------------------------
# Where a note goes: the person's own address, worked out here and only here
# ---------------------------------------------------------------------------


def _own_key(key: str, names: Iterable[str] = ()) -> bool:
    """Whether a remembered fact's key is about the person's own email address.

    `names` are the person's own names (`owner.resolve`): their name may be in it
    ("alex's email address"); anybody else's may not ("alex's partner's email" is
    theirs)."""
    key = str(key or "").lower().replace("'s", "").replace("’s", "")
    words = [w for w in re.split(r"[^a-z]+", key) if w]
    if "email" not in words and "mail" not in words:
        return False
    own = {w for n in names or () for w in re.split(r"[^a-z]+", str(n or "").lower()) if w}
    return all(w in _OWN_WORDS or w in own for w in words)


def address_in(text: str) -> str:
    """The first email address in some text, or ""."""
    found = _ADDRESS.search(str(text or ""))
    return found.group(0) if found else ""


def addresses_in(text: str) -> list[str]:
    """Every email address in some text: a To line with names and commas in it."""
    return _ADDRESS.findall(str(text or ""))


def recipient(facts: Iterable[tuple[str, str]] = (), *, account_email: str = "",
              google_email: str = "", names: Iterable[str] = ()) -> tuple[str, str]:
    """The person's own address, and where it came from; ("", "") when none is known.

    Three places, in this order, and all three are the person's own:

    1. what they asked Rouh to remember as their email address ("alex's email
       address", "my email", with `names` their own names);
    2. the email on their Rouh account;
    3. the Google account they connected, which is the one it is sent from.

    Never anything a job wrote: a note's words are not read here at all.
    """
    for key, value in facts or ():
        if _own_key(key, names):
            found = address_in(value)
            if found:
                return found, f'what you were asked to remember as "{key}"'
    found = address_in(account_email)
    if found:
        return found, "the email on their Rouh account"
    found = address_in(google_email)
    if found:
        return found, "the Google account they connected, which it is sent from"
    return "", ""


def recipient_for(memory=None, google=None) -> tuple[str, str]:
    """`recipient`, gathered from what this process holds. Never raises.

    `memory` is Rouh's `Memory`, for the remembered facts; `google` is the
    `GoogleDesk`, for whose account this is and the address it is connected to.
    Whose account is answered the way every Google tool answers it: the person
    in this conversation, or the one account this install has.
    """
    facts: list[tuple[str, str]] = []
    who = None
    connected = ""
    with contextlib.suppress(Exception):
        facts = list(memory.facts()) if memory is not None else []
    with contextlib.suppress(Exception):
        if google is not None:
            who = google.person()
            connected = google.address()
        else:
            from .tenancy import Tenancy, speaker

            who = speaker() or Tenancy().only_person()
    account = str(getattr(who, "email", "") or "") if who is not None else ""
    names: tuple[str, ...] = ()
    with contextlib.suppress(Exception):
        from . import owner

        found = owner.resolve(who)
        if found is not None:
            names = (found.name, found.full_name)
    return recipient(facts, account_email=account, google_email=connected, names=names)


# ---------------------------------------------------------------------------
# What Rouh is told
# ---------------------------------------------------------------------------


def _when(ts: float) -> str:
    with contextlib.suppress(Exception):
        return time.strftime("%d %b %H:%M", time.localtime(float(ts)))
    return ""


def _quoted(note: dict) -> str:
    """One note, its subject and id in Rouh's words and its body in a box."""
    return (f'note {note["id"]}, subject "{note["subject"]}", which says:\n'
            + untrusted.wrap(note["body"], SOURCE))


def for_report(job_id: str) -> str:
    """What a job's report says about the notes it queued, or "" when it queued none."""
    try:
        notes = pending(job_id)
    except Exception:
        log.exception("could not read the notes job %s queued", job_id)
        return ""
    if not notes:
        return ""
    many = len(notes) != 1
    said = "\n".join(_quoted(n) for n in notes)
    return (f"\n\nIt also queued {len(notes)} note{'s' if many else ''} for the person "
            f"to be emailed, and nothing has been sent:\n{said}\n\n{HOW_TO_SEND}")


#: Which job a report being written is about, for the reports that can say
#: several different things about one job (`assistant_job.Lander` and
#: `one_jobs.OneLander`, whose `_say` is where the notes are put in). Set
#: around the report exactly as `memory.answering_in` sets the thread it goes
#: into, so the notes and the words they ride with can never be two jobs'.
REPORTING: ContextVar[str] = ContextVar("rouh_outbox_reporting", default="")


@contextlib.contextmanager
def reporting(job_id: str):
    token = REPORTING.set(str(job_id or ""))
    try:
        yield
    finally:
        REPORTING.reset(token)


def on_its_own(job_id: str) -> str:
    """What is said in General about a finished job: its queued notes alone, or "".

    The report of a job no conversation started stays out of General
    (`runs.report_stays`): what it did is on its run, not in the conversation.
    A note it queued to be emailed is
    not a report. The person asked for that email, only Rouh can send it, and
    only once they have said yes, so it is still asked about, and nothing else
    about the job is said with it.
    """
    try:
        notes = pending(job_id)
    except Exception:
        log.exception("could not read the notes job %s queued", job_id)
        return ""
    if not notes:
        return ""
    title = ""
    with contextlib.suppress(Exception):
        from . import runs

        row = runs.get(job_id)
        title = str(getattr(row, "title", "") or "") if row is not None else ""
    which = f'The job "{title}"' if title else "A job"
    many = len(notes) != 1
    said = "\n".join(_quoted(n) for n in notes)
    return (f"[{which} has finished. What it did stays on its own run, where the person "
            "reads it, so say nothing about that here. It queued "
            f"{len(notes)} note{'s' if many else ''} for the person to be emailed, and "
            f"nothing has been sent:\n{said}\n\n{HOW_TO_SEND} Do not start anything else.]")


def with_notes(job_id: str, note: str) -> str:
    """A job's report, with the notes it queued inside it.

    Put inside the bracket the report is written in, so what the job queued
    reads as part of what Rouh is being told about that job, and the report's
    own last word - "Do not start anything" - still covers it: sending is only
    ever on the person's yes, in a later turn.
    """
    extra = for_report(job_id) if job_id else ""
    if not extra:
        return note
    text = str(note or "").rstrip()
    if text.endswith("]"):
        return text[:-1].rstrip() + extra + "]"
    return text + extra


def describe(notes: list[dict], address: str, where: str, *, titles: dict | None = None) -> str:
    """The waiting notes as Rouh reads them from `worker_outbox`."""
    if address:
        head = f"A note goes to {address}, the person's own address, from {where}."
    else:
        head = ("No address for the person is known yet, so nothing can be sent. Ask "
                "them for theirs and keep it with remember, as \"‹owner›'s email "
                "address\"; then it is the only place a note goes.")
    if not notes:
        return head + "\n\nNo notes are waiting to be sent."
    lines = [head, "", f"{len(notes)} note{'s' if len(notes) != 1 else ''} waiting, "
             "none sent:"]
    for note in notes:
        title = (titles or {}).get(note["job"]) or ""
        job = f'job {note["job"]}' + (f' "{title}"' if title else "")
        lines.append("")
        lines.append(f"From {job}, queued {_when(note['created_at'])}: " + _quoted(note))
    lines += ["", "Nothing here has been sent. " + ASK_FIRST]
    return "\n".join(lines)
