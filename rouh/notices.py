"""Notifications: the screen first, and the phone only if the screen was not enough.

Petar, 10 October 2026, from the Gene therapy board (fr_8f09d161935f): "The idea is
that you first give me a notification, and I can look at it and dismiss it. If
not, I also get a Telegram notification. I can push up to get away from it,
meaning I'm going to look at it in a little bit or later."

Until that day everything Rouh had to tell him when it was not answering him
went straight to Telegram: a job that needs him, a reminder, the morning brief,
a note before a meeting, an email's note, a question that cannot wait. He was
often at the screen when it did, and the phone buzzed about something already in
front of him. So each of those is now a notice first:

* **It drops in at the top of every open tab of his** (`notices.js` on the page)
  the moment it is said, the way a notification drops in on an iPhone. More than
  one stack. Swiped left it is dismissed; swiped right it goes where it leads,
  if it leads anywhere, and is dismissed on the way (fr_a7c05457e6a3); pushed up
  it is put away for later and waits under the bell in the sidebar. Opened, it says all of itself, with the decision it asks
  drawn inside it where it asks one.
* **Left alone, it goes to the phone.** If nothing is done with it for `GRACE`
  seconds after it was said, its Telegram copy is sent, with the same link. If
  no screen of his drew it at all within `GLANCE` seconds - no tab open, or none
  in front of him - it goes at once, because there is nobody at the screen to
  wait for. Anything done with it on the screen - dismissed, opened, put away -
  means he saw it, and the phone stays quiet.
* **What cannot wait goes to the phone at once, as well as on the screen** (`at_once`).
  Petar, 17 October 2026, after a payment was told as paid while his bank's 3-D Secure
  still waited: "I should be notified on telegram for timely stuff like that." A step in
  the live browser only he can do (his bank's approval, a code, a login, a captcha), a
  job's hand-off to it, and a payment that failed or was left unpaid are sent to Telegram
  the moment they are said, once, and the notice on the screen is the same one.
* **What never went to the phone still does not.** A finished job is a notice
  and not a message (`config.phone_done_jobs`, off since 6 October 2026), and a
  note with no phone words has none to send.

The waiting is a row, not a timer: a deploy restarts Rouh many times a day, and
a notice said a second before one is sent by the process that comes back
(`Sweeper`). Each copy is claimed before it is sent, so it goes once.

Only the install's owner has a phone here: the bot reaches one chat, theirs
(`telegram.phone_owner`), so a notice for anybody else stays on the screen.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import re
import time
from typing import Any, Awaitable, Callable
from urllib.parse import urlsplit

log = logging.getLogger("rouh.notices")

#: How long a notice is on the screen, untouched, before its phone copy goes. Petar: "If
#: I don't dismiss it in a minute or 30 seconds, or whatever you decide makes sense".
GRACE = 45.0
#: How long a notice waits for any screen to draw it before the phone is told at once.
GLANCE = 8.0
#: How far back the list under the bell goes, and how much of it.
KEEP_DAYS = 7
LISTED = 60
#: How often the phone copies that are due are looked for.
EVERY = 2.0

NEW, LATER, READ, DISMISSED = "new", "later", "read", "dismissed"
DUE, SENDING, SENT, SKIPPED, FAILED = "due", "sending", "sent", "skipped", "failed"

#: What a press or a swipe on the page may do to one: drawn while he was looking (`seen`),
#: put away (`later`), opened in place (`read`), swiped away or gone to (`dismiss`).
ACTS = ("seen", "later", "read", "dismiss")

TITLE = 140
#: Room for every word a job closes with (`assistant_job.answer_from`), which an opened notice
#: shows whole; the card in the stack and an unopened row show the first three lines of it.
BODY = 6000

URL = re.compile(r"https?://[^\s<>\"']+")

#: What following a link is called, by where it goes in Rouh. "at least it should say
#: 'link' or 'go to' something".
LABELS = (
    ("/run/", "Open the run"),
    ("/task/", "Open the task"),
    ("/project/", "Open the project"),
    ("/decisions", "Answer it"),
    ("/chat/", "Open the chat"),
    ("/brief", "Open the brief"),
    ("/mail/", "Open the email"),
    ("/browser", "Open the browser"),
    ("/web", "Open the browser"),
    ("/reminders", "Open Clockwork"),
    ("/clockwork", "Open Clockwork"),
    ("/goals", "Open the goal"),
    ("/goal/", "Open the goal"),
    ("/work", "Open the quest"),
    ("/meeting", "Open the meeting"),
    ("/anatomy/behaviour/beats?beat=", "Open the beat"),
)


class Hooks:
    """What the notices borrow from the running Rouh, set by `runtime`."""

    #: () -> identity: the install's owner, whose phone the bot reaches.
    owner: Callable[[], Any] | None = None
    #: async (who, message): one message to every open tab of that person's.
    push: Callable[[Any, dict], Awaitable] | None = None
    #: The bot (`telegram.Telegram`), or None.
    telegram: Any = None
    #: async (who, decision id) -> bool: a decision's own phone message, with its buttons.
    phone_decision: Callable[[Any, int], Awaitable[bool]] | None = None
    public_url: str = ""


hooks = Hooks()


# --- the words ------------------------------------------------------------------------------


def _cut(text: str, most: int) -> str:
    text = " ".join(str(text or "").split())
    if len(text) <= most:
        return text
    return text[: most - 1].rsplit(" ", 1)[0].rstrip(",;:") + "…"


def local_link(link: str, public_url: str = "") -> str:
    """A link into this Rouh as its own address ("/run/abc"), so it is followed inside the
    page; anything else as it came."""
    link = str(link or "").strip()
    base = str(public_url or hooks.public_url or "").rstrip("/")
    if base and (link == base or link.startswith(base + "/")):
        rest = link[len(base):]
        return rest or "/"
    return link


def label_for(link: str) -> str:
    if not link:
        return ""
    if link.startswith("/"):
        for start, words in LABELS:
            if link.startswith(start):
                return words
        return "Open it"
    host = urlsplit(link).hostname or ""
    host = host[4:] if host.startswith("www.") else host
    return f"Open {host}" if host else "Open the link"


def from_text(text: str, public_url: str = "") -> dict:
    """A phone message's words as a notice: its first line the title, the rest the body, and
    the link it carries - a link into Rouh first, else the last one - as where it leads.

    Every note Rouh sends the phone is written that way already ("⚠️ Needs you: ...", a line
    or two, the link at the foot), so the screen says what the phone would have said.
    """
    text = str(text or "").strip()
    links = URL.findall(text)
    base = str(public_url or hooks.public_url or "").rstrip("/")
    ours = [u for u in links if base and u.startswith(base)]
    link = ours[0] if ours else (links[-1] if links else "")
    link = link.rstrip(".,;)")
    lines = [ln.rstrip() for ln in text.splitlines()]
    # A line that is nothing but the link is the link, and is not said twice.
    kept = [ln for ln in lines if not (ln.strip() and URL.fullmatch(ln.strip().rstrip(".,;)")))]
    first = next((i for i, ln in enumerate(kept) if ln.strip()), None)
    if first is None:
        title, body = "Rouh", ""
    else:
        title = kept[first].strip()
        rest = "\n".join(kept[first + 1:]).strip()
        if len(title) > TITLE:
            body = (title + ("\n" + rest if rest else "")).strip()
            title = _cut(title, TITLE)
        else:
            body = rest
    body = re.sub(r"\n{3,}", "\n\n", body)
    local = local_link(link, base)
    return {"title": title, "body": body[:BODY], "link": local, "link_label": label_for(local)}


# --- the rows -------------------------------------------------------------------------------


def _ids(who) -> tuple[str, str]:
    return str(who.user_id), str(who.org_id)


def _model():
    from .models import Notice

    return Notice


def as_dict(row) -> dict:
    return {
        "id": row.id, "kind": row.kind, "title": row.title, "body": row.body,
        "link": row.link, "link_label": row.link_label, "links": list(row.links or []),
        "decision": row.decision_id,
        "state": row.state, "phone": row.phone, "at": row.created_at,
        "phoned_at": row.phoned_at, "deployed": row.deployed,
    }


def _links(links) -> list[dict]:
    """Every place a notice leads, each as Rouh's own address where it is one, and only the
    ones with somewhere to go."""
    out = []
    for one in links or ():
        if not isinstance(one, dict):
            continue
        href = local_link(str(one.get("href") or ""))[:2000]
        label = _cut(one.get("label") or label_for(href), 40)
        if href and label:
            out.append({"to": str(one.get("to") or "")[:20], "label": label, "href": href,
                        "title": _cut(one.get("title") or label, 160)})
    return out[:8]


def post(who, *, title: str, body: str = "", link: str = "", link_label: str = "",
         links=(), kind: str = "", key: str = "", phone_text: str = "",
         decision_id: int | None = None, deployed: str = "",
         now: float | None = None) -> dict | None:
    """Write one notice. None when its key was said before."""
    from django.db import IntegrityError, transaction

    user_id, org_id = _ids(who)
    link = local_link(link)
    try:
        with transaction.atomic():
            row = _model().objects.create(
                user_id=user_id, org_id=org_id, key=str(key or "")[:500], kind=kind or "rouh",
                title=_cut(title, TITLE) or "Rouh", body=str(body or "").strip()[:BODY],
                link=link[:2000], link_label=(link_label or label_for(link))[:80],
                links=_links(links),
                decision_id=decision_id, deployed=str(deployed or "")[:40], state=NEW,
                phone_text=str(phone_text or "").strip(), phone=DUE if phone_text or decision_id
                else "", created_at=now or time.time())
    except IntegrityError:
        return None
    return as_dict(row)


def _settle_decisions(who, rows) -> list:
    """A notice asking a decision that was answered somewhere else is read: the question it
    carried is not waiting any more."""
    asking = [r for r in rows if r.decision_id and r.state in (NEW, LATER)]
    if not asking:
        return rows
    from .models import Decision

    user_id, org_id = _ids(who)
    still = set(Decision.objects.filter(
        user_id=user_id, org_id=org_id, id__in=[r.decision_id for r in asking],
        status__in=("open", "snoozed", "failed")).values_list("id", flat=True))
    gone = [r.id for r in asking if r.decision_id not in still]
    if gone:
        stamp = time.time()
        _model().objects.filter(id__in=gone, phone=DUE).update(phone=SKIPPED)
        _model().objects.filter(id__in=gone).update(state=READ, handled_at=stamp)
        rows = list(_model().objects.filter(id__in=[r.id for r in rows]).order_by("-created_at",
                                                                                   "-id"))
    return rows


def settle_link(who, *, kind: str, link: str) -> int:
    """Every notice of this kind that leads to `link`, new or put away, read, with its phone
    copy kept quiet: what it said waits for him is not waiting any more (N1, "Remove the
    notice when ..."). How many it changed."""
    user_id, org_id = _ids(who)
    links = {str(link or "").strip(), local_link(link)} - {""}
    if not links:
        return 0
    rows = _model().objects.filter(user_id=user_id, org_id=org_id, kind=kind, link__in=links,
                                   state__in=(NEW, LATER))
    rows.filter(phone=DUE).update(phone=SKIPPED)
    return rows.update(state=READ, handled_at=time.time())


async def settled(who, *, kind: str, link: str) -> int:
    """`settle_link`, and every open tab of his told, so the notice goes from the screen."""
    try:
        n = await asyncio.to_thread(settle_link, who, kind=kind, link=link)
    except Exception:  # noqa: BLE001 - a notice left up is shown as read on the next look
        log.exception("notices for %s could not be settled", link)
        return 0
    if n:
        await tell(who)
    return n


def listing(who) -> dict:
    """Everything under the bell: the last week's, newest first, without the dismissed, and
    how many of the week's are still to read.

    The count is a COUNT of its own, never the unread among the `LISTED` rows sent. Until 4
    November 2026 it was those, so the bell could never pass the share of the newest 60 still
    unread, and as each new notice pushed an old one out of the 60 it stayed where it was:
    Petar, that day, of the bell "stuck" at 55 and 56, with more than that to read."""
    user_id, org_id = _ids(who)
    since = time.time() - KEEP_DAYS * 86400
    week = _model().objects.filter(user_id=user_id, org_id=org_id, created_at__gte=since)
    # A notice asking a decision answered elsewhere is not counted, listed or not.
    _settle_decisions(who, list(week.filter(state__in=(NEW, LATER)).exclude(decision_id=None)))
    rows = list(week.exclude(state=DISMISSED).order_by("-created_at", "-id")[:LISTED])
    items = [as_dict(r) for r in rows]
    return {"type": "notices", "items": items,
            "unread": week.filter(state__in=(NEW, LATER)).count(),
            "grace": GRACE}


def act(who, ids, what: str) -> int:
    """One press or swipe on the page, on one notice or several. How many it changed."""
    if what not in ACTS:
        return 0
    user_id, org_id = _ids(who)
    try:
        ids = [int(i) for i in (ids or [])][:LISTED * 2]
    except (TypeError, ValueError):
        return 0
    if not ids:
        return 0
    rows = _model().objects.filter(user_id=user_id, org_id=org_id, id__in=ids)
    stamp = time.time()
    if what == "seen":
        return rows.filter(seen_at__isnull=True).update(seen_at=stamp)
    # Anything done with it means he saw it: the phone stays quiet.
    rows.filter(phone=DUE).update(phone=SKIPPED)
    rows.filter(seen_at__isnull=True).update(seen_at=stamp)
    if what == "later":
        return rows.filter(state=NEW).update(state=LATER, handled_at=stamp)
    if what == "read":
        return rows.filter(state__in=(NEW, LATER)).update(state=READ, handled_at=stamp)
    return rows.exclude(state=DISMISSED).update(state=DISMISSED, handled_at=stamp)


def due(now: float | None = None) -> list:
    """The notices whose phone copy is to go now: still on the screen untouched past `GRACE`,
    or never drawn by any screen past `GLANCE`."""
    from django.db.models import Q

    now = now or time.time()
    return list(_model().objects.filter(phone=DUE, state=NEW).filter(
        Q(created_at__lte=now - GRACE) | Q(seen_at__isnull=True, created_at__lte=now - GLANCE))
        .order_by("created_at")[:20])


def claim(row_id: int) -> bool:
    """Take one phone copy to send. True once only, whoever asks."""
    return _model().objects.filter(id=row_id, phone=DUE, state=NEW).update(phone=SENDING) == 1


def phoned(row_id: int, outcome: str) -> None:
    _model().objects.filter(id=row_id).update(
        phone=outcome, phoned_at=time.time() if outcome == SENT else None)


# --- saying one -----------------------------------------------------------------------------


async def tell(who) -> None:
    """Every open tab of this person's, the list as it is now."""
    if hooks.push is None or who is None:
        return
    with contextlib.suppress(Exception):
        await hooks.push(who, await asyncio.to_thread(listing, who))


async def _owner():
    if hooks.owner is None:
        return None
    try:
        return await asyncio.to_thread(hooks.owner)
    except Exception:
        log.exception("whose notices these are could not be read")
        return None


def _same(a, b) -> bool:
    return a is not None and b is not None and _ids(a) == _ids(b)


async def notify(*, title: str, body: str = "", link: str = "", link_label: str = "",
                 links=(), kind: str = "", key: str = "", phone_text: str = "",
                 decision_id: int | None = None, deployed: str = "", who=None,
                 at_once: bool = False) -> dict | None:
    """Say one notice: on the screen now, on the phone later if it is left there.

    `who` is the install's owner when it is not given. `phone_text` is what the phone is sent
    if it comes to that, and "" for a notice that stays on the screen. Never raises; where
    the notice cannot be written at all, its phone copy is sent at once, so nothing that used
    to reach the phone is lost to a fault here. `deployed` is the commit a finished run put
    live, so a page from before that deploy offers its Reload on this notice. `links` is every
    place it leads, each a button of its own (`_links`); `link` stays the one a swipe goes to.
    `at_once` sends the phone copy now rather than after `GRACE`, for what cannot wait.
    """
    who = who if who is not None else await _owner()
    if who is None:
        log.info("a notice with nobody to give it to: %s", _cut(title, 80))
        return None
    try:
        said = await asyncio.to_thread(
            post, who, title=title, body=body, link=link, link_label=link_label, links=links,
            kind=kind,
            key=key, phone_text=phone_text, decision_id=decision_id, deployed=deployed)
    except Exception:
        log.exception("a notice could not be written; its phone copy goes now")
        if phone_text:
            await _send(phone_text)
        return None
    if said is None:
        return None
    log.info("notice %s (%s): %s", said["id"], kind or "rouh", _cut(title, 80))
    if at_once and phone_text:
        await _phone_now(who, said["id"], phone_text)
    await tell(who)
    return said


#: The last job's hand-off each person was sent at once, by site, so Rouh's own hand_over
#: of that step a moment later is not a second message for the same event (Petar's N1: one
#: notice for one event). The bank's step is covered by its purchase instead
#: (`browsing.Desk._phone_step`).
_STEPS: dict[tuple[str, str], tuple[str, float]] = {}
#: How long a job's hand-off covers the same site's hand_over.
STEP_COVERS = 300.0


def step_told(who, site: str, now: float | None = None) -> None:
    if who is not None and site:
        _STEPS[_ids(who)] = (site, now or time.time())


def step_told_lately(who, site: str, now: float | None = None) -> bool:
    if who is None or not site:
        return False
    told = _STEPS.get(_ids(who))
    return bool(told and told[0] == site and (now or time.time()) - told[1] < STEP_COVERS)


async def _phone_now(who, row_id: int, text: str) -> str:
    """A notice's phone copy sent now, claimed first so the sweeper never sends it again.
    Only the owner's: the bot reaches their phone and nobody else's."""
    owner = await _owner()
    if not _same(who, owner) or not await asyncio.to_thread(claim, row_id):
        return SKIPPED
    outcome = await _send(text)
    await asyncio.to_thread(phoned, row_id, outcome)
    if outcome == SENT:
        log.info("notice %s went to the phone at once", row_id)
    return outcome


async def phone(text: str, *, kind: str = "", key: str = "", who=None,
                title: str = "", link: str = "", phone_too: bool = True,
                whole: str = "", deployed: str = "", links=(),
                at_once: bool = False) -> dict | None:
    """A note that was a Telegram message until 10 October 2026, as a notice first.

    The phone's own words are its title, body and link (`from_text`), and are what the phone
    is sent if the notice is left on the screen, or at once with `at_once`; with `phone_too`
    false it stays on the screen.
    `whole` is the same message with nothing cut out of it, when the phone's is a short form
    of something longer: its body is the notice's, so opening it shows every word.
    """
    shaped = from_text(text)
    if whole:
        shaped["body"] = from_text(whole)["body"] or shaped["body"]
    if title:
        shaped["title"] = title
    if link:
        shaped["link"] = local_link(link)
        shaped["link_label"] = label_for(shaped["link"])
    return await notify(kind=kind, key=key, who=who, phone_text=text if phone_too else "",
                        deployed=deployed, links=links, at_once=at_once, **shaped)


async def _send(text: str) -> str:
    tg = hooks.telegram
    try:
        if tg is None or not tg.configured():
            return SKIPPED
    except Exception:
        return SKIPPED
    from .telegram import NotSent, NotSetUp

    try:
        await tg.send(text)
    except NotSetUp:
        return SKIPPED
    except NotSent as exc:
        log.warning("a notice's phone copy did not go: %s", exc)
        return FAILED
    except Exception as exc:  # noqa: BLE001 - the notice is on the screen either way
        log.warning("a notice's phone copy did not go: %s: %s", type(exc).__name__, exc)
        return FAILED
    return SENT


class Sweeper:
    """Sends the phone copies that are due, once each, across restarts."""

    def __init__(self) -> None:
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="notices")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._task
            self._task = None

    async def _run(self) -> None:
        while True:
            await asyncio.sleep(EVERY)
            try:
                await self.once()
            except Exception:
                log.exception("notices: the phone copies could not be looked at this pass")

    async def once(self, now: float | None = None) -> int:
        rows = await asyncio.to_thread(due, now)
        if not rows:
            return 0
        owner = await _owner()
        sent = 0
        told: dict[tuple[str, str], Any] = {}
        for row in rows:
            if not await asyncio.to_thread(claim, row.id):
                continue
            who = type("Who", (), {"user_id": row.user_id, "org_id": row.org_id})()
            if not _same(who, owner):
                # The bot reaches the owner's phone and nobody else's.
                outcome = SKIPPED
            elif row.decision_id and hooks.phone_decision is not None:
                try:
                    outcome = SENT if await hooks.phone_decision(owner, row.decision_id) \
                        else SKIPPED
                except Exception:
                    log.exception("notice %s: its decision could not go to the phone", row.id)
                    outcome = FAILED
            elif row.phone_text:
                outcome = await _send(row.phone_text)
            else:
                outcome = SKIPPED
            await asyncio.to_thread(phoned, row.id, outcome)
            if outcome == SENT:
                sent += 1
                log.info("notice %s was left on the screen, so it went to the phone", row.id)
            told[_ids(who)] = owner if _same(who, owner) else who
        for who in told.values():
            await tell(who)
        return sent


__all__ = ["GRACE", "GLANCE", "Sweeper", "act", "from_text", "hooks", "listing", "notify",
           "phone", "post", "step_told", "step_told_lately"]
