"""Newest in the thread first: a reply never goes out over a newer message in its own thread.

Built by the nightly feature run, night 18, 21 October 2026 (task 94, idea I-109), after Pally
shipped on 20 October 2026 "draft approval now displays any replies received after drafting"
(https://pally.com/whats-new/2026-10).

Rouh answers in a thread of its own inbox (`send_mail` with `reply_to_message_id`, and the Send
button on a draft card, `rouh/composing.py`). The reply is written against one message. Between
that message being read, or the draft being made, and the reply going, somebody in the thread
may have written again: "ignore that, Thursday is off", a new question, the file it asked for.
A reply that goes regardless answers a conversation that has moved on, and its writer finds out
only when the other side points it out.

So, every time a reply in a thread is about to go, the thread is looked at first:

- **Nothing newer** from anybody but this mailbox: it goes, and nothing is said. That is
  almost always.
- **A newer message**, after the one being answered, that this mailbox did not send and that
  is not a draft: it is held back. Rouh, sending it itself, is told who wrote, when, the first
  words and the message's id, so it reads that message and answers it instead. A person who
  pressed Send on a card is shown the same on the card, and pressing Send again sends it as
  it stands: a newer message is said once, never held twice.

No model is asked; the thread's ids and labels, and the headers of any newer message, are two
or three reads of Gmail. A look that fails sends the reply as it would have gone before, so
this never stops mail on its own account.

Its switch is `newest_first` (`rouh/switches.py`): off, replies go without the look.
"""
from __future__ import annotations

import logging
import threading
import time

log = logging.getLogger("rouh.newest_first")

SWITCH = "newest_first"
#: Labels that are never somebody writing again: what this mailbox sent, and its drafts.
NOT_NEWER = frozenset({"SENT", "DRAFT"})
#: How long a newer message once said is remembered as said, so the second press sends.
REMEMBER = 24 * 3600

_lock = threading.Lock()
#: (org, user, the message being answered and who sends) -> {newer id: when it was said}.
_said: dict[tuple[str, str, str], dict[str, float]] = {}


def on() -> bool:
    from . import switches

    return switches.on(SWITCH)


async def newer(gmail, reply_to: str) -> list[dict]:
    """The messages in `reply_to`'s thread after it that somebody else wrote, oldest first.

    Each is `Gmail.headers` of it: id, from, subject, date, at and snippet. Empty when there are
    none, when the message is not in this mailbox, or when the thread cannot be read.
    """
    if not reply_to:
        return []
    try:
        thread = await gmail.thread_of(reply_to)
        if not thread:
            return []
        whole = await gmail.thread_minimal(thread)
    except Exception as exc:  # noqa: BLE001 - a look that fails never holds a reply
        log.info("could not look at the thread of %s before replying: %s", reply_to, exc)
        return []
    ids = [str(m.get("id") or "") for m in whole]
    if reply_to not in ids:
        return []
    after = [m for m in whole[ids.index(reply_to) + 1:]
             if m.get("id") and not set(m.get("labelIds") or []) & NOT_NEWER]
    out = []
    for one in after:
        try:
            out.append(await gmail.headers(str(one["id"])))
        except Exception as exc:  # noqa: BLE001 - one unreadable message is left out
            log.info("could not read the newer message %s: %s", one.get("id"), exc)
    return out


def unsaid(who, reply_to: str, found: list[dict], by: str = "") -> list[dict]:
    """Of `found`, the newer messages not yet said to `by` for this reply; remember them as said.

    `by` is who is sending: a card (its number) or Rouh itself, so a message shown on a card
    is still said to Rouh when Rouh sends in the same thread, and the other way round.
    """
    key = (str(getattr(who, "org_id", "") or ""), str(getattr(who, "user_id", "") or ""),
           f"{reply_to}|{by}")
    now = time.time()
    with _lock:
        for k in [k for k, v in _said.items() if all(now - t > REMEMBER for t in v.values())]:
            _said.pop(k, None)
        told = _said.setdefault(key, {})
        fresh = [m for m in found if str(m.get("id")) not in told]
        for m in fresh:
            told[str(m.get("id"))] = now
    return fresh


def _who_wrote(raw: str) -> str:
    from email.utils import parseaddr

    name, address = parseaddr(raw or "")
    return name or address or "Somebody"


def _when(at: float) -> str:
    from . import clock

    dt = clock.moment(at) if at else None
    return dt.strftime("%a %d %b, %H:%M") if dt else ""


def line(m: dict) -> str:
    """One newer message as a person reads it: who, when, and the first words."""
    when = _when(float(m.get("at") or 0))
    words = " ".join(str(m.get("snippet") or "").split())
    if len(words) > 160:
        words = words[:157].rstrip() + "..."
    said = _who_wrote(str(m.get("from") or ""))
    if when:
        said += f" wrote again on {when}"
    else:
        said += " wrote again"
    return said + (f": “{words}”" if words else "")


def _ended(said: str) -> str:
    return said if said.endswith(("\u201d", ".", "?", "!")) else said + "."


def for_rouh(fresh: list[dict], reply_to: str) -> str:
    """What `send_mail` answers when its reply is held: read the newer message, answer that."""
    lines = "; ".join(f"{line(m)} (message id {m.get('id')})" for m in fresh)
    newest = fresh[-1].get("id")
    return (f"Not sent: since the message you are answering ({reply_to}), {lines}. Read it with "
            f"read_mail first, then write your reply to what the thread now says and send it with "
            f"reply_to_message_id {newest}. If it changes nothing, sending the same reply again "
            "sends it.")


def for_card(fresh: list[dict]) -> str:
    """What the card says when its Send was held."""
    lines = " ".join(_ended(line(m)) for m in fresh)
    return f"Not sent yet: {lines} Press Send again to send it as it is."


async def held(gmail, who, reply_to: str, *, pressed: bool, card: str = "") -> str:
    """Why this reply should wait, or "" to send it. Every reply in a thread asks this first.

    `pressed` is a Send on draft card `card`; otherwise Rouh is sending it itself.
    """
    if not reply_to or not on():
        return ""
    fresh = unsaid(who, reply_to, await newer(gmail, reply_to),
                   by=f"card {card}" if pressed else "rouh")
    if not fresh:
        return ""
    from . import evolution

    evolution.used(SWITCH, "held_back", who=who,
                   detail=f"{len(fresh)} newer in the thread, "
                          f"{'a Send on a card' if pressed else 'a reply Rouh wrote'}")
    return for_card(fresh) if pressed else for_rouh(fresh, reply_to)


__all__ = ["SWITCH", "for_card", "for_rouh", "held", "line", "newer", "on", "unsaid"]
