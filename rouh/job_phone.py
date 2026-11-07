"""What a finished job ended with, sent to the owner's phone with a link to open it.

Petar, 29 September 2026, from the Gene therapy board (fr_17965f7d38c7): "I would
love it if a finished job sends me the link to view in telegram message." He
was reading a finished step's page when he wrote it.

The first cut, 4d3ac43, sent only for a job that made a page, and on 30
September he said "this is still not working": every job that finished after
it was a change to Rouh, or files with no page, so nothing ever went. So every
job Rouh reports now sends one message, and each has a link:

* **A page** links to the page itself, ``/task/<its path>``, the address he
  had open.
* **Anything else that finished** - files with no page, an answer, a change to
  Rouh's own code, with whether it is live - links to the job's own screen,
  ``/run/<id>``, where its result and everything it said are.
* **A job that stopped and needs him** - its work could not be put on main, or
  it ended with work never saved - says so, and links to its run too.

Not sent, because each already reaches him another way or is not a result: a
goal step's run (its goal says it), a step handed to the live browser (Rouh
takes it up in General), a collision for him to decide (`ConflictFeed` in
`rouh/runtime.py` sends that to the phone already), and a job being written
again. Only jobs Rouh reports at all come here, which is jobs Rouh started.
A report that stays on its run rather than being said in General is still
sent, because the phone is where he is when he is away from the screen.

**A job that simply finished is no longer sent, unless the setting says so.**
Petar, 6 October 2026: "I think it is time to stop notifying me on telegram
when a run is completed/done." So the "Done" message - a page, files, an
answer, a change to Rouh that is live - goes only where ``ROUH_PHONE_DONE_JOBS``
is set (`config.phone_done_jobs`, off by default), and the Metabolism page is where a
finished job is seen. "Needs you" is unchanged and always sent: a job that
stopped on him, ended unfinished, or landed a change that is not live.

**And the chat it was asked in.** Petar, 12 October 2026: "when the run
completes the chat receives the report and the notification has a link to the
chat too." A run started from a conversation, General included
(`runs.report_chat`), ends every message with that chat's address, last, so a
reply to it on the phone goes on in that chat (`telegram_chat._CHAT_LINK`), and
its notice on the screen opens that chat (`Lander._phone`).

**Once per result, whatever happens.** The claim is a row in ``app_state``
written before anything is sent, keyed on the job and its result (the page,
the commit, or its words), so a second report of the same stop or a restart of
Rouh part way cannot send it twice. A follow-up that ends with something new
is a new result and sends again.

**The screen first.** Since 10 October 2026 (fr_8f09d161935f) each of these is a
notice on his screen before it is a message (`rouh/notices.py`), and goes to the
phone only if he leaves it there; a finished job is a notice even with the
setting off, and then never reaches the phone (`Lander._phone`).

**A message that does not go never undoes the job.** It is logged, as a
warning with the reason Telegram gave, and the report carries on. Nothing here
raises. The bot, its token and the chat are `rouh/telegram.py`'s, set on the
server in its secrets file, and nothing here reads them; a machine with no bot
logs one line and sends nothing.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import time
from urllib.parse import quote

log = logging.getLogger("rouh.job_phone")

#: The start of the ``app_state`` key that says a message went (or was tried)
#: for one result of one job.
CLAIM = "phone_told:"

#: How much of the job's own words go in the message: a line or two, for a
#: phone's notification and the top of the chat.
SUMMARY = 280


def page_link(public_url: str, page: str) -> str:
    """Rouh's address for a workspace page, from outside this machine.

    ``/task/<path>`` opens the page inside Rouh, in the task browser, which is
    the address Petar had open when he asked for this. Behind the sign-in like
    every address Rouh serves, which a phone that has used Rouh is already past.
    """
    base = str(public_url or "").rstrip("/")
    return f"{base}/task/{quote(str(page).strip('/'), safe='/')}" if base and page else ""


def run_link(public_url: str, run_id: str) -> str:
    """Rouh's address for a run's own screen (`addressing.KINDS`)."""
    base = str(public_url or "").rstrip("/")
    return f"{base}/run/{quote(str(run_id), safe='')}" if base and run_id else ""


def _short(text: str, limit: int | None = SUMMARY) -> str:
    """`text` on one line, cut at `limit`; with no limit, all of it, line breaks and all."""
    if limit is None:
        return re.sub(r"\n{3,}", "\n\n", str(text or "")).strip()
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(text) > limit:
        text = text[: limit - 1].rsplit(" ", 1)[0].rstrip(",;:") + "..."
    return text


def chat_link(public_url: str, chat: str) -> str:
    """Rouh's address for a conversation, the chat a run was started from (`run_report`)."""
    base = str(public_url or "").rstrip("/")
    return f"{base}/chat/{quote(str(chat), safe='')}" if base and chat else ""


def _links(link: str, chat: str) -> list[str]:
    """The foot of a message: where its result is, and then the chat it was asked in.

    The chat last, on a line of its own, because a reply on the phone to a message
    ending in a chat's address goes on in that chat (`telegram_chat._CHAT_LINK`).
    """
    lines = [x for x in (link, chat) if x]
    if len(lines) == 2:
        lines[1] = f"Its chat: {lines[1]}"
    return ["", *lines] if lines else []


def page_text(title: str, summary: str, link: str, *, whole: bool = False,
              chat: str = "") -> str:
    """The message for a job that finished: a page, files, an answer or a change.

    `whole` keeps every word of `summary`: the notice on the screen says all of it when it
    is opened, and only the phone is held to a line or two. `chat` is the address of the
    conversation it was started from, which its report went into, or "".
    """
    lines = [f"✅ Done: {_short(title, 120) or 'a job'}"]
    said = _short(summary, None if whole else SUMMARY)
    if said:
        lines.append(said)
    return "\n".join(lines + _links(link, chat))


def stuck_text(title: str, why: str, link: str, *, whole: bool = False,
               chat: str = "") -> str:
    """The message for a job that stopped and needs the person. As in `page_text`."""
    lines = [f"⚠️ Needs you: {_short(title, 120) or 'a job'}"]
    said = _short(why, None if whole else SUMMARY)
    if said:
        lines.append(said)
    return "\n".join(lines + _links(link, chat))


def _said(text: str) -> str:
    return hashlib.sha256(str(text or "").strip().encode("utf-8")).hexdigest()[:12]


def message_for(job_id: str, title: str, summary: str, result: dict,
                public_url: str, *, done: bool = False,
                whole: bool = False, chat: str = "") -> tuple[str, str] | None:
    """What goes to the phone for this report: ``(what, text)``, or None.

    ``what`` names the result, for the once-only claim; ``text`` is the
    message. `result` is the report's own, as `Lander` and `OneLander` leave
    it, and its ``kind`` says which of the three messages it is. `done` is
    whether a job that simply finished is sent at all
    (`config.phone_done_jobs`); a job that needs him is sent either way.
    `whole` is the same message with every word of the job's own kept, for the
    notice on the screen. `chat` is the conversation the run was started from
    (`runs.report_chat`), whose address goes at the foot of every message, so
    the report it put there is a press away.
    """
    kind = str(result.get("kind") or "")
    run = run_link(public_url, job_id)
    talk = chat_link(public_url, chat)
    if kind == "page" and result.get("page"):
        if not done:
            return None
        page = str(result["page"])
        return f"page:{page}", page_text(title, summary, page_link(public_url, page) or run, whole=whole,
                                         chat=talk)
    if kind in ("needs_you", "unfinished"):
        why = str(result.get("reason") or "")
        return "stuck", stuck_text(title, why or summary, run, whole=whole, chat=talk)
    if kind == "change":
        sha = str(result.get("sha") or "")[:7]
        if not result.get("live"):
            why = f"On main at {sha} and NOT live: {result.get('deployed') or 'it was not deployed'}."
            return f"change:{sha}", stuck_text(title, why, run, whole=whole, chat=talk)
        if not done:
            return None
        said = " ".join(x for x in (summary, f"Deployed at {sha}.") if x)
        return f"change:{sha}", page_text(title, said, run, whole=whole, chat=talk)
    if kind in ("files", "answer"):
        if not done:
            return None
        which = str(result.get("sha") or "")[:12] or _said(summary)
        return f"{kind}:{which}", page_text(title, summary, run, whole=whole, chat=talk)
    return None


def claim(job_id: str, what: str) -> bool:
    """Take the one message this job has for `what`. True the first time only.

    Written before the message is sent, so two reports racing each other, or a
    Rouh restarted between the two, cannot both send it.
    """
    from django.db import IntegrityError, transaction

    from .models.memory import AppState

    key = f"{CLAIM}{job_id}:{what}"[:500]
    try:
        with transaction.atomic():
            AppState.objects.create(key=key, value=str(int(time.time())))
    except IntegrityError:
        return False
    return True


async def send(telegram, job_id: str, what: str, text: str) -> str:
    """Send `text` for this job's `what` once. Says what became of it, never raises.

    One of "sent", "already" (it went, or was tried, before), "not set up" and
    "failed". The job is finished whichever it is.
    """
    if telegram is None or not job_id:
        return "not set up"
    try:
        if not telegram.configured():
            log.info("job %s finished; no Telegram bot on this machine, so nothing was sent",
                     job_id)
            return "not set up"
        if not await asyncio.to_thread(claim, job_id, what):
            log.info("job %s: its message for %s went already", job_id, what)
            return "already"
    except Exception:
        log.exception("job %s: could not tell whether its message had gone, so it was not "
                      "sent", job_id)
        return "failed"
    from .telegram import NotSent, NotSetUp

    try:
        await telegram.send(text)
    except NotSetUp:
        log.info("job %s finished; Telegram is not set up, so nothing was sent", job_id)
        return "not set up"
    except NotSent as exc:
        # The job is done either way; the message is what did not happen.
        log.warning("job %s finished, but its Telegram message did not go: %s", job_id, exc)
        return "failed"
    except Exception as exc:
        log.warning("job %s finished, but its Telegram message did not go: %s: %s",
                    job_id, type(exc).__name__, exc)
        return "failed"
    log.info("job %s: sent to the owner's phone, about %s", job_id, what)
    return "sent"
