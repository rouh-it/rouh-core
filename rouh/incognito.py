"""Incognito: a chat where nothing is kept.

Petar, 15 November 2026 (Chat Change Planning, point 7): "One icon (in the same unified control). Turning it on
visibly changes the whole chat ... On, it opens/shows the panel: the rules that will apply are listed and
readable, with toggles for memory (Synapse), tools, and the person's rules. Permission, privacy and safety rules
are locked on, shown as locked. Not changeable: everything in an incognito chat is deleted when the chat ends
(closed, left, or new chat), never written to Synapse, never indexed, no history kept."

What that is here:

- **Starting one** (`start`) makes a new chat that belongs to General (`forks.belong`), marked
  `Chat.incognito`, on Simple chat to begin with (memory and the person's rules off; Memory can be turned on in
  Custom: Synapse is then read, never written).
  It is in no list of chats and no search (`hidden`), and is never named by the model.
- **Ending one** (`end`) deletes it the way a person's Delete does, with everything it owns (`owning.remove`),
  and its transcript, cards and timelines (`memory.forget_chat`), and any reminder set in it. It ends when the
  tab in it opens another chat or a new one, when the tab is closed (its socket goes), and, for one left
  behind by a restart, when Rouh starts (`sweep`).
- **Never written anywhere else**: Synapse is never written from a turn (the remember, thought and Synapse
  tools refuse in it: `refuses`), General's running summary is General's alone, the requests made of a model
  keep their tokens, cost and time but not their words (`rouh/llmlog.py`, `quiet`), and automatic recall,
  which writes a trace of what it looked up, does not run in it.

What is kept, and for how long (`KEPT`, said in the panel): while the chat is open, its messages are in the
database like any chat's, so the conversation works; when it ends they are deleted. The log of requests made of
a model keeps one row per request with the model, the tokens, the cost and the time, and no words, for as long
as that log is kept (`rouh/lean.py`), so the budgets stay right. The server's own log lines say that a turn
ran in a chat and how long it took, never what was said.
"""
from __future__ import annotations

import logging
import threading

log = logging.getLogger("rouh.incognito")

TITLE = "Incognito"

KEPT = ("While this chat is open its messages are kept so it works; when it ends they are deleted with it. "
        "Nothing is written to your memory, nothing is searchable, and the log of model requests keeps only "
        "the model, tokens, cost and time of each, never the words.")

#: The tools that write to the person's memory or keep their words, refused in an incognito chat.
WRITES = frozenset({"remember", "forget", "capture_thought", "synapse_add", "synapse_edit", "new_box",
                    "make_a_task", "agent_instructions"})

_LOCK = threading.Lock()
_IDS: set[str] = set()
_LOADED = False


def _load() -> None:
    """The incognito chats, read once. Never from the event loop, where Django refuses a query: there the list
    is whatever was read already (at Rouh's start, by `sweep`, and on every `start`)."""
    global _LOADED
    if _LOADED:
        return
    import asyncio

    try:
        asyncio.get_running_loop()
        return
    except RuntimeError:
        pass
    from .models.objects import Chat

    with _LOCK:
        if not _LOADED:
            try:
                _IDS.update(Chat.objects.filter(incognito=True).values_list("id", flat=True))
            except Exception:  # noqa: BLE001 - asked again next time
                log.debug("the incognito chats could not be read", exc_info=True)
                return
            _LOADED = True


def ids() -> set[str]:
    _load()
    return set(_IDS)


def quiet(chat_id: str | None) -> bool:
    """Whether this chat is incognito: nothing of it is kept beyond what it needs while open."""
    if not chat_id:
        return False
    _load()
    return chat_id in _IDS


def hidden(chat_ids) -> set[str]:
    """Those of these chats that are incognito, which no list or search shows."""
    _load()
    return {c for c in chat_ids if c in _IDS}


def refuses(tool: str, chat_id: str | None) -> str:
    """Why a tool may not run in this chat, or "": in an incognito chat, nothing is written to memory."""
    if tool in WRITES and quiet(chat_id):
        return ("This is an incognito chat: nothing in it is kept, so nothing is written to memory, the "
                "person's thoughts or their tasks from here. Say so, and offer to do it in a normal chat.")
    return ""


def start() -> str:
    """A new incognito chat, and its id."""
    from . import conversations
    from .models.objects import Chat

    chat_id = conversations.new_chat(TITLE)
    # Simple chat to begin with: no memory and none of the person's rules, tools on demand (`reading.SIMPLE`).
    Chat.objects.filter(id=chat_id).update(incognito=True, reading={"mode": "simple"})
    _load()
    with _LOCK:
        _IDS.add(chat_id)
    log.info("an incognito chat was started")
    return chat_id


def end(chat_id: str) -> bool:
    """Delete an incognito chat with everything in it. Whether there was one to delete."""
    from . import owning

    if not quiet(chat_id):
        return False
    from .models.objects import Chat

    if not Chat.objects.filter(id=chat_id, incognito=True).exists():
        with _LOCK:
            _IDS.discard(chat_id)
        return False
    plan = owning.plan("chat", chat_id)
    got = owning.remove("chat", chat_id)
    chats = list(dict.fromkeys([chat_id, *(plan.get("chats") or [])]))
    from .models.memory import OpenTurn, RecallTimeline, RouteTimeline, ScreenCard, ToolLine, TranscriptMessage

    # The model's tape and what was drawn on the way, as `Memory.forget_chat` does for a deleted chat.
    for c in chats:
        try:
            for model in (TranscriptMessage, ScreenCard, ToolLine, RecallTimeline, RouteTimeline, OpenTurn):
                model.objects.filter(session_id=c).delete()
        except Exception:  # noqa: BLE001 - the rest still goes
            log.exception("an incognito chat's tape could not be deleted")
    try:
        from .models.memory import AppState

        AppState.objects.filter(key__in=[f"draft:{c}" for c in chats]).delete()
    except Exception:  # noqa: BLE001
        pass
    with _LOCK:
        _IDS.discard(chat_id)
    log.info("an incognito chat ended and was deleted (%s)", "ok" if got.get("ok") else got.get("why"))
    return bool(got.get("ok"))


def sweep() -> int:
    """Every incognito chat, deleted: at start, none of them has a tab in it any more."""
    n = 0
    for chat_id in ids():
        try:
            n += 1 if end(chat_id) else 0
        except Exception:  # noqa: BLE001 - the next start tries again
            log.exception("an incognito chat could not be deleted")
    if n:
        log.info("%d incognito chat(s) left from before were deleted", n)
    return n
