"""Sent by you: a reply the owner sends themself, to mail a task drafted for them, is kept in the task.

Built by the nightly feature run, night 17, 20 October 2026 (task 94, idea I-108). The owner's own
inbox is read-only to Rouh, so when a task prepares a reply for him (three such replies to
contacts in October 2026), he sends it himself from
his Gmail, often in his own words rather than the draft's. The task never hears it. On 19 October
he typed "Here is what I wrote" and pasted his whole email into the task's chat, then "it is sent
already" when Rouh suggested changes; the task's notes still said "Open, for <the owner>: send the
draft" the next morning, which is what every later run and chat in the task reads.

So, while its switch is on, two things happen, and nothing is drawn on any screen:

- **Every run is told** (`RULE`, after its agent instructions, from `agent_instructions.block`):
  when it leaves a reply for the person to send from their own mail, it adds one entry to the
  task's meta (`rouh-task meta <task> append sends_himself`, `rouh/taskmeta.py`): the Gmail thread it answers, whom it goes to, its
  subject, the step that drafted it and the day.
- **Rouh watches his sent mail for it** (`Watcher`, every five minutes, for the person the
  workspace is for): each entry not yet answered is looked for in the read-only mailbox it names,
  by its thread, or by whom it went to and its subject when the run had no thread. The first email
  he sent there after the draft is written, with his own words whole, under "Sent by you" at the
  end of the task's `AGENTS.md`, which every run, chat and Ask AI in the task already reads, and
  the entry is marked sent, so it is written once. An entry nobody answered in thirty days is
  let go.

**No model call.** Matching is by Gmail's own thread, or by address and subject.

**Whose.** Only the owner's own read-only mailboxes, read with GET (`rouh/mailboxes.py`); the
task is in the owner's own workspace, saved to main like every other change Rouh makes there
(`rouh/saving.py`). Nothing is sent, and nothing in the mailbox changes.

**Its switch** is `sent_by_you` (`rouh/switches.py`): off, no run is told and no mail is read.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import threading
import time
from datetime import date, datetime, timedelta
from pathlib import Path

log = logging.getLogger("rouh.sent_by_you")

#: The gene's switch (`rouh/switches.py`).
SWITCH = "sent_by_you"
TITLE = ("Sent by you: a reply you send yourself, to mail a task drafted for you, is kept in the "
         "task's notes in your own words")

#: The key in a task's meta that lists the replies the person is to send himself.
KEY = "sends_himself"
#: The heading the replies go under, at the end of the task's AGENTS.md.
HEADING = "## Sent by you"
#: How often the sent mail is looked at, and how long an entry is watched for.
BEAT = 300.0
WATCH_DAYS = 30
#: The longest of his own words kept, and the most entries looked at in one beat.
WORDS_MOST = 6000
MOST_A_BEAT = 40

RULE = (
    "The person's own inbox is read-only to Rouh, so a reply you prepare for them to send from "
    "their own mail is sent by them, by hand, often changed. When you leave such a draft, add "
    f"one entry to the list `{KEY}` in the task's meta, so Rouh can find the reply in their sent "
    f"mail and keep it in the task: `rouh-task meta <task> append {KEY} '<the entry>'`, the "
    'entry being `{"thread": "<the Gmail thread id of the email it answers>", "to": "<the '
    'address it goes to>", "subject": "<its subject>", "step": "<the step that drafted it, such '
    'as 126-01>", "inbox": "<the mailbox it goes from, such as alex@example.com>", "since": '
    '"<today, YYYY-MM-DD>"}`. Give the thread whenever you read the email; without it, `to` and '
    "`subject` are what is matched. Write the open item in the task's `AGENTS.md` as \"send the "
    "reply from your own mail\", not as a question. Once they have sent it, Rouh writes it, in "
    f"their own words, under \"{HEADING[3:]}\" at the end of the task's `AGENTS.md`: read it "
    "there rather than asking whether it went, and treat what they sent, not the draft, as what "
    "was said."
)

_lock = threading.Lock()


def on(org_id=None) -> bool:
    from . import switches

    return switches.on(SWITCH, org_id or None)


def for_runs(org: str) -> str:
    """The section every run of this organisation is given after its agent instructions, or ""
    (off)."""
    try:
        if not org or not on(org):
            return ""
        return "## Replies the person sends themselves\n\n" + RULE
    except Exception:  # noqa: BLE001 - a run starts whatever this says
        log.exception("sent by you could not be put in a run's instructions")
        return ""


# --- the entries a task's meta holds -------------------------------------------------------


def _day(value) -> date | None:
    try:
        return date.fromisoformat(str(value or "").strip()[:10])
    except ValueError:
        return None


def _entries(data: dict) -> list:
    held = data.get(KEY)
    if isinstance(held, dict):
        return [held]
    return held if isinstance(held, list) else []


def _waiting(entry) -> bool:
    return (isinstance(entry, dict) and not entry.get("sent") and not entry.get("let_go")
            and bool(str(entry.get("thread") or "").strip()
                     or (str(entry.get("to") or "").strip()
                         and str(entry.get("subject") or "").strip())))


def pending(root) -> list[tuple[Path, int, dict]]:
    """Every reply still to be sent, as (the task's folder, its place in the list, the entry).

    Out of every task's meta, in one read (`rouh/taskmeta.py`)."""
    from . import taskmeta

    root = Path(root)
    out = []
    for folder, data in sorted(taskmeta.by_folder().items()):
        for n, entry in enumerate(_entries(data)):
            if _waiting(entry):
                out.append((root / folder, n, entry))
    return out


def _since(entry: dict, folder: Path) -> date:
    held = _day(entry.get("since"))
    if held:
        return held
    from . import taskmeta

    ident = taskmeta.task_id(folder)
    task = taskmeta._store().get_task(ident) if ident else None
    return datetime.fromtimestamp(task.created_at).date() if task else date.today()


# --- finding the reply in his sent mail -----------------------------------------------------


def _plain(subject: str) -> str:
    from .ghosts import _plain_subject

    return " ".join(_plain_subject(subject).lower().split())


def _addresses(value: str) -> set[str]:
    from .ghosts import people

    found = {addr for _name, addr in people(value)}
    if not found and "@" in str(value or ""):
        found = {a.strip().lower() for a in str(value).split(",") if "@" in a}
    return found


def _his(message: dict, own: set[str], after: float) -> bool:
    from .ghosts import _at, _named, sender

    if "DRAFT" in (message.get("labelIds") or []):
        return False
    if _at(message) < after:
        return False
    return sender(_named(message).get("from") or "")["email"] in own


def _answers(message: dict, entry: dict) -> bool:
    """Without a thread: whether a sent email is to the entry's address and on its subject."""
    from .ghosts import _named

    named = _named(message)
    to = _addresses(entry.get("to") or "")
    went = _addresses(named.get("to") or "") | _addresses(named.get("cc") or "")
    if to and not (to & went):
        return False
    want = _plain(entry.get("subject") or "")
    return not want or want in _plain(named.get("subject") or "")


async def find(reader, own: set[str], entry: dict, after: float) -> dict | None:
    """The first email he sent in answer to the entry after `after`, whole, or None."""
    thread = str(entry.get("thread") or "").strip()
    if thread:
        try:
            held = await reader.thread(thread)
        except Exception as exc:  # noqa: BLE001 - a thread gone is looked for by its subject
            log.info("sent by you: thread %s could not be read: %s", thread, exc)
            held = {}
        from .ghosts import _at

        mine = sorted((m for m in held.get("messages") or [] if _his(m, own, after)), key=_at)
        if mine:
            return mine[0]
        if held.get("messages"):
            return None
    if not (str(entry.get("to") or "").strip() and str(entry.get("subject") or "").strip()):
        return None
    query = f"in:sent after:{int(after)}"
    to = sorted(_addresses(entry.get("to") or ""))
    if to:
        query += f" to:{to[0]}"
    from .ghosts import _at

    found = []
    for one in await reader.search(query, 20):
        message = await reader.message(one["id"])
        if _his(message, own, after) and _answers(message, entry):
            found.append(message)
    return min(found, key=_at) if found else None


# --- keeping it in the task -----------------------------------------------------------------


def _quote(text: str) -> str:
    return "\n".join(("> " + line).rstrip() for line in text.split("\n"))


def section(message: dict, entry: dict, inbox: str, when: float | None = None) -> str:
    """The lines one reply is kept as, under the heading."""
    from . import clock
    from .ghosts import _at, _body_text, _named, link_to, own_words, people

    try:
        zone = clock.zone()
    except Exception:  # noqa: BLE001 - the server's own zone is a fair second
        zone = None
    named = _named(message)
    at = datetime.fromtimestamp(when or _at(message) or time.time(), zone)
    to = people(named.get("to") or "")
    first = (to[0][0] or to[0][1]) if to else (named.get("to") or "somebody")
    subject = " ".join((named.get("subject") or "(no subject)").split())
    words = own_words(_body_text(message)) or "(only a quote, no words of their own)"
    words = words if len(words) <= WORDS_MOST else words[:WORDS_MOST - 1].rstrip() + "…"
    lines = [f"### {at.day} {at:%B %Y}, {at:%H:%M}: to {first}, \"{subject}\"", "",
             f"- From {inbox or 'their own mail'} to {' '.join((named.get('to') or '').split())}"
             + (f"; cc {' '.join(named['cc'].split())}" if named.get("cc") else "") + "."]
    step = str(entry.get("step") or "").strip()
    if step:
        lines.append(f"- In answer to the draft of step {step}; this, not the draft, is what was "
                     "sent.")
    thread = str(message.get("threadId") or entry.get("thread") or "")
    if thread and inbox:
        lines.append(f"- [Open it in Gmail]({link_to(inbox, thread)})")
    return "\n".join(lines + ["", _quote(words)]) + "\n"


def keep(folder: Path, n: int, entry: dict, message: dict, inbox: str) -> Path | None:
    """Write the reply into the task's AGENTS.md and mark the entry sent. The notes' path, or
    None when the task has no notes or the entry was already kept."""
    from . import instructions

    notes = instructions.in_folder(folder)
    if not notes.is_file():
        return None
    from . import taskmeta

    with _lock:
        entries = _entries(taskmeta.get(folder))
        if n >= len(entries) or not isinstance(entries[n], dict) or entries[n].get("sent"):
            return None
        text = notes.read_text(encoding="utf-8")
        new = section(message, entry, inbox)
        if HEADING in text:
            text = text.rstrip("\n") + "\n\n" + new
        else:
            text = (text.rstrip("\n") + "\n\n" + HEADING + "\n\n"
                    "Replies the owner sent from their own mail to email this task drafted for "
                    "them, found in their sent mail by Rouh, in their own words. What they sent "
                    "is what was said.\n\n" + new)
        _write(notes, text)
        from . import clock
        from .ghosts import _at

        try:
            zone = clock.zone()
        except Exception:  # noqa: BLE001 - the server's own zone is a fair second
            zone = None
        sent = {
            "at": datetime.fromtimestamp(_at(message) or time.time(), zone).isoformat(
                timespec="minutes"),
            "message": str(message.get("id") or ""), "thread": str(message.get("threadId") or "")}
        taskmeta.change(folder, lambda data: _mark(data, n, sent=sent),
                        by="Rouh, finding a reply in the sent mail")
    return notes


def _mark(data, n: int, **marks):
    """The meta with entry `n` of its list carrying `marks`, a list of one kept as one."""
    entries = _entries(data or {})
    if n < len(entries) and isinstance(entries[n], dict):
        entries[n] = dict(entries[n], **marks)
        data[KEY] = entries[0] if isinstance(data.get(KEY), dict) else entries
    return data


def let_go(folder: Path, n: int) -> None:
    from . import taskmeta

    with _lock:
        taskmeta.change(folder, lambda data: _mark(data, n, let_go=date.today().isoformat()),
                        by="Rouh, letting a reply go")


def _write(path: Path, text: str) -> None:
    was = path.stat()
    spare = path.with_name(f".{path.name}.{os.getpid()}.rouh-sent")
    try:
        with open(spare, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
        os.chmod(spare, was.st_mode & 0o7777)
        with contextlib.suppress(OSError):
            os.chown(spare, was.st_uid, was.st_gid)
        os.replace(spare, path)
    finally:
        if spare.exists():
            spare.unlink()


# --- one look --------------------------------------------------------------------------------


def _mailbox_for(sources, entry: dict, mine: str):
    """The read-only mailbox an entry goes from: the one it names, else the account's own, else
    the only one."""
    held = [s for s in sources if not s.is_connection]
    wanted = str(entry.get("inbox") or "").strip().lower() or mine
    for one in held:
        if (one.email or "").lower() == wanted:
            return one
    return held[0] if len(held) == 1 else None


async def look(who, auth, cfg, root) -> list[str]:
    """Every waiting entry looked for once. The tasks a reply was kept in."""
    from asgiref.sync import sync_to_async

    from . import evolution, ghosts, inboxes, saving

    waiting = (await asyncio.to_thread(pending, root))[:MOST_A_BEAT]
    if not waiting:
        return []
    sources = await sync_to_async(ghosts.sources)(who, auth)
    mine = await sync_to_async(inboxes.account_address)(who)
    readers: dict = {}
    kept = []
    for folder, n, entry in waiting:
        since = _since(entry, folder)
        if date.today() - since > timedelta(days=WATCH_DAYS):
            await asyncio.to_thread(let_go, folder, n)
            continue
        source = _mailbox_for(sources, entry, mine)
        if source is None:
            continue
        if source.id not in readers:
            reader = await sync_to_async(ghosts._reader)(who, auth, cfg, source)
            own = await reader.addresses() if reader is not None else set()
            readers[source.id] = (reader, own)
        reader, own = readers[source.id]
        if reader is None or not own:
            continue
        after = datetime.combine(since, datetime.min.time()).timestamp()
        try:
            message = await find(reader, own, entry, after)
        except Exception as exc:  # noqa: BLE001 - one mailbox's trouble never stops the rest
            log.info("sent by you: %s could not be read: %s", source.email, exc)
            continue
        if message is None:
            continue
        notes = await asyncio.to_thread(keep, folder, n, entry, message, source.email)
        if notes is None:
            continue
        kept.append(folder.name)
        saving.poke()
        await sync_to_async(evolution.used)(
            SWITCH, "reply_kept", who=who,
            detail=f"kept in {folder.name}: {str(entry.get('subject') or entry.get('thread'))[:80]}")
        log.info("sent by you: kept a reply in %s", notes)
    return kept


class Watcher:
    """Every five minutes, for the person the workspace is for with the switch on: each reply a
    task is waiting for them to send is looked for in their sent mail, and kept once found."""

    def __init__(self, *, owner, auth, cfg, root) -> None:
        self.owner = owner
        self.auth = auth
        self.cfg = cfg
        self.root = root
        self._registered = False
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.get_running_loop().create_task(self._run())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._task
            self._task = None

    async def _run(self) -> None:
        await asyncio.sleep(min(60.0, BEAT))
        while True:
            try:
                await self.beat()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("the sent-by-you look failed")
            await asyncio.sleep(BEAT)

    async def beat(self) -> list[str]:
        from asgiref.sync import sync_to_async

        who = await sync_to_async(self.owner)()
        if who is None:
            return []
        if not self._registered:
            from . import switches

            await sync_to_async(switches.register)(SWITCH, TITLE, org_id=str(who.org_id))
            self._registered = True
        if not await sync_to_async(on)(str(who.org_id)):
            return []
        auth, root = self.auth(), self.root()
        if auth is None or not root:
            return []
        return await look(who, auth, self.cfg, root)


__all__ = ["HEADING", "KEY", "RULE", "SWITCH", "TITLE", "Watcher", "find", "for_runs", "keep",
           "look", "on", "pending", "section"]
