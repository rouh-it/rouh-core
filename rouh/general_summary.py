"""General's running summary: what was said before the newest messages, kept short.

Petar, 15 November 2026 (Chat Change Planning, point 3): General "loads everything about the person, as now ...
Older turns are compacted into a running summary so it doesn't grow forever."

General is sent as a window of its newest messages (`chatkinds.profile`, `history_turns`), and until now what
fell out of the window was simply gone from what the model read. Now it is folded into one running summary,
told in every General turn beside the clock (`brain.Brain._system`, "What General said before"):

- **What it covers** is General's own record of words (`objects.message`, the words and nothing else), every
  row but the newest `KEEP`, which the window sends whole. The window counts the model's tape, tool calls
  and all, so it may hold fewer turns than `KEEP`; the two then overlap by a few turns, which says the same
  thing twice rather than leaving a gap.
- **When it moves** is after a turn of General's, once at least `STEP` more rows have fallen out of the
  window, on a thread of its own, never in front of an answer (`after_a_turn`). The newest summary is
  folded with what fell out since, `BATCH` rows at a time, so it never reads the whole history again.
- **Who writes it** is the model of the use "general_summary" on the Models page, through the LLM service.
  If it cannot be asked, the summary stays as it was and the window works as it always did.
- **Where it is kept** is one row of `app_state` (`KEY`), as General is one chat: `through` (the last row's
  `seq` it covers) and `text`. An incognito chat never reaches it: only General has one.
"""
from __future__ import annotations

import asyncio
import json
import logging
import threading
import time

log = logging.getLogger("rouh.general_summary")

KEY = "general_summary"
#: The newest rows of the record never folded in: the window sends them whole.
KEEP = 40
#: How many rows must have fallen out of the window before the summary is written again.
STEP = 12
#: The most rows folded in by one call, so a first summary of months of General is made in steps.
BATCH = 160
#: The most characters of one row handed to the summary, and the longest a summary may get.
ROW_CHARS = 1500
MOST_WORDS = 700
USE = "general_summary"

SYSTEM = (
    "You keep the running summary of a long, never-ending conversation between a person and their assistant, "
    "Rouh. You are given the summary so far and the next stretch of the conversation, oldest first. Write the "
    "new summary: what the person asked for, decided, said about themselves and their people, what Rouh did "
    "or promised, and what is still open, newest last. Keep names, numbers, dates, addresses and ids exactly. "
    "Drop greetings and small talk. Plain sentences, no headings. At most {most} words. Write only the summary.")

_LOCK = threading.Lock()
_WORKING: set[str] = set()


def _state():
    from .models.memory import AppState

    return AppState


def _key() -> str:
    """General is one chat, `conversations.GENERAL`, so its summary is one row."""
    return KEY


def read(key: str | None = None) -> dict:
    """{"through": seq, "text": words, "at": time}, or {} when there is none yet."""
    try:
        row = _state().objects.filter(key=key or _key()).values_list("value", flat=True).first()
    except Exception:  # noqa: BLE001 - no summary is the old behaviour
        log.exception("General's summary could not be read")
        return {}
    if not row:
        return {}
    try:
        got = json.loads(row) if isinstance(row, str) else row
    except ValueError:
        return {}
    return got if isinstance(got, dict) else {}


def _write(key: str, value: dict) -> None:
    _state().objects.update_or_create(key=key, defaults={"value": json.dumps(value)})


def block() -> str:
    """What a General turn is told: the summary, labelled, or ""."""
    got = read()
    text = str(got.get("text") or "").strip()
    if not text:
        return ""
    return ("What was said earlier in this conversation, before the newest messages, as a running summary "
            "(the newest messages follow in full and win where they differ):\n" + text)


def _rows(chat_id: str, after: int, upto: int) -> list[tuple[int, str, str]]:
    from .models.objects import ChatMessage

    return list(ChatMessage.objects.filter(chat_id=chat_id, seq__gt=after, seq__lte=upto)
                .order_by("seq").values_list("seq", "role", "body")[:BATCH])


def _last_seq(chat_id: str) -> int:
    from .models.objects import ChatMessage

    got = ChatMessage.objects.filter(chat_id=chat_id).order_by("-seq").values_list("seq", flat=True).first()
    return int(got or 0)


def due(chat_id: str, key: str | None = None) -> tuple[int, int] | None:
    """(after, upto): the rows to fold in now, or None when fewer than STEP have fallen out of the window."""
    last = _last_seq(chat_id)
    upto = last - KEEP
    after = int(read(key).get("through") or 0)
    if upto - after < STEP:
        return None
    return after, upto


def _stretch(rows) -> str:
    out = []
    for _seq, role, body in rows:
        who = "Person" if role == "user" else "Rouh"
        words = " ".join(str(body or "").split())
        if len(words) > ROW_CHARS:
            words = words[:ROW_CHARS] + "..."
        if words:
            out.append(f"{who}: {words}")
    return "\n".join(out)


async def fold(chat_id: str, key: str) -> bool:
    """Fold what has fallen out of the window into the summary, a batch at a time. Whether it moved."""
    from . import llm

    moved = False
    for _ in range(50):
        span = await asyncio.to_thread(due, chat_id, key)
        if span is None:
            break
        after, upto = span
        rows = await asyncio.to_thread(_rows, chat_id, after, upto)
        if not rows:
            break
        before = str(read(key).get("text") or "")
        ask = (f"The summary so far:\n{before or '(none yet: this is the start of the conversation)'}\n\n"
               f"The next stretch of the conversation:\n{_stretch(rows)}")
        try:
            got = await llm.ask(USE, system=SYSTEM.format(most=MOST_WORDS), messages=ask,
                                max_tokens=1800, session_id=chat_id, read_only=True, timeout=120)
        except llm.Cannot as e:
            log.info("General's summary was not written: %s", e)
            break
        text = (got.text or "").strip()
        if not text:
            break
        await asyncio.to_thread(_write, key, {"through": int(rows[-1][0]), "text": text, "at": time.time()})
        moved = True
    return moved


def after_a_turn(chat_id: str) -> None:
    """After a turn of General's: fold in what fell out of the window, if enough did. Returns at once."""
    from .conversations import GENERAL

    if chat_id != GENERAL:
        return
    key = _key()
    with _LOCK:
        if key in _WORKING:
            return
        _WORKING.add(key)
    try:
        if due(chat_id, key) is None:
            _WORKING.discard(key)
            return
        task = asyncio.ensure_future(fold(chat_id, key))
    except Exception:  # noqa: BLE001 - no loop, or the record could not be read: next turn
        _WORKING.discard(key)
        log.debug("General's summary was not started", exc_info=True)
        return

    def done(t) -> None:
        _WORKING.discard(key)
        if not t.cancelled() and t.exception() is not None:
            log.error("General's summary failed: %s", t.exception())

    task.add_done_callback(done)
