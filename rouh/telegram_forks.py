"""Forks from the owner's phone, and a group of its own for each.

Petar, 27 September 2026: the fork he uses on the screen, on Telegram too,
starting the way he likes a fork to start - with his own first message saying
what the side conversation is about. `rouh/forks.py` is the fork, unchanged;
`rouh/telegram_chat.py` is the conversation on the phone; this is what joins
the two, and everything it keeps.

**/fork, and only /fork.** Written as a reply to one of Rouh's answers it forks
from exactly there: every message of every answer is written down with the
chat and the exchange it finished (`TelegramReply`), so the fork comes off
just below that exchange however much has been said since (`forks.make`,
`through`). Not a reply, it forks the chat it is written in as it stands.
/fork followed by words makes the fork with those words as its first message;
/fork alone holds it (`ARMED`, in `app_state`) and Rouh asks what it is to be
about, and the next thing written in the same place is its first message,
whole. /cancel puts a held fork down, and so does moving to another chat. It
is in the menu of the chat, with the rest (`menus`): "fork is not appearing as
a command in the menu of the chat and it should". There was a Fork button
under every answer for a day; Petar: "No, remove the button. We should only
use /fork." A press on one left on his phone says so and takes it off.

**A group of its own for every fork.** "After I fork, I expect you to setup
and start a new group chat in telegram with that specific fork", and, of his
other project on the server, which does exactly that for an idea: "check on the server
how my other project does that". A bot cannot make a group, so, as that project does, the
group is made as him, with his own Telegram account connected to Rouh in
Settings (`rouh/telegram_account.py`): named after the fork's first message,
with Rouh's bot in it as its admin, opened by the bot with where the fork came
off, and then his first message, posted as his own, which the bot answers
there like anything he writes. What is written in that group is written in
that fork (`TelegramFork.tg_chat`); /fork there forks the fork, into a group
of its own. The private chat is told the group's name and given a link to it.
Until an account is connected, a fork is on the screen only: its first message
is answered there and the answer comes back to the private chat, which says
how to connect one and stays in General.

**The private chat is General, always.** Petar, 27 September 2026: "any
messages i type to Rouh on telegram do not come to the general chat. But they
should, I should have a unified chat on all media ... anything I type on
telegram should be stored in db and shown on Rouh as if I typed it there".
For a day the private chat could move into a fork - when one was made there
without a group, or picked with /chats - and stayed there, so what he wrote to
the bot went into a fork he had left behind, and never reached General on the
screen. So there is no pointer any more: everything he writes to the bot
directly is a turn in General, and a fork is written in its own group, or on
the screen. A fork made without a group (no account connected yet, or a group
Telegram would not make) has its first message answered in the fork, and the
answer comes back to the private chat once, saying so, with its link.

A fork waiting for its first message and each fork's group are rows in the
database, so a deploy or a restart in the middle of any of this leaves him
exactly where he was.
"""
from __future__ import annotations

import json
import logging
import re
import time

from django.db import transaction

from . import conversations, events, forks

log = logging.getLogger("rouh.telegram_forks")

#: Where the private chat used to point, in `app_state`, when it could move
#: into a fork. Only ever taken away now (`settle`).
WHERE = "telegram_chat"
#: The fork waiting for its first message, in `app_state`, as JSON: the chat
#: it comes off, the exchange it comes off below (or none, for the chat as it
#: stands), where it was asked for (`tg_chat`, `thread`), the answer it was
#: asked for under, and the question Rouh asked.
ARMED = "telegram_fork_armed"

#: How much of what a fork asks names it on the phone, in characters.
NAME_ASKED = 48
#: How much of a fork's first message names its group, in characters.
NAME_CHARS = 60

#: What the buttons of the first day carried back when they were pressed: Fork
#: and Cancel under an answer, and a chat of /chats. Only answered now.
FORK = "fork"
CANCEL = "fork:cancel"
CHAT = "chat:"

ASK = "What should this fork be about? Send its first message, or /cancel."
NOTHING_TO_FORK = ("There is nothing in this chat to fork from yet. Write to me, and "
                   "fork from my answer.")
GONE = "That conversation is not there any more, so it cannot be forked from."
NO_BUTTON = "Fork is /fork now: reply to an answer with /fork."
SET_UP = ("To open every fork in a group of its own, connect your Telegram account to "
          "Rouh in Settings, under Telegram account. Rouh then makes the group for each "
          "fork as you, with me in it.")

#: The menu of the private chat, and of Petar in the forks group: (command,
#: what it does), in the order the menu lists them.
MENU_PRIVATE = [
    ("fork", "Fork this chat: reply to an answer with /fork and the fork's first message"),
    ("cancel", "Put down a fork still waiting for its first message"),
    ("help", "What I can do here"),
]
MENU_GROUP = [
    ("fork", "Fork this fork: reply to an answer with /fork and the new fork's first message"),
    ("cancel", "Put down a fork still waiting for its first message"),
    ("help", "What I can do here"),
]


def menu_private(own_chat: str) -> tuple[list[tuple[str, str]], dict]:
    """The private chat's menu, and the scope that is his chat alone."""
    return MENU_PRIVATE, {"type": "chat", "chat_id": _number(own_chat)}


def menu_group(group) -> tuple[list[tuple[str, str]], dict]:
    """A fork group's menu. The group is him and the bot, so the chat is the scope."""
    return MENU_GROUP, {"type": "chat", "chat_id": _number(group)}


def _number(value):
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return value


# --- the two pointers -------------------------------------------------------------


def _state(key: str) -> str:
    from .models import AppState

    return AppState.objects.filter(key=key).values_list("value", flat=True).first() or ""


def _set_state(key: str, value: str | None) -> None:
    from .models import AppState

    if value is None:
        AppState.objects.filter(key=key).delete()
        return
    AppState.objects.bulk_create([AppState(key=key, value=value)], update_conflicts=True,
                                 unique_fields=["key"], update_fields=["value"])


def settle() -> None:
    """Take away where the private chat pointed, from when it could move.

    Left behind by the day the private chat could move into a fork, the row
    would say nothing to anybody, so the first start without it clears it.
    """
    _set_state(WHERE, None)


def armed() -> dict | None:
    """The fork waiting for its first message, or None."""
    try:
        got = json.loads(_state(ARMED) or "null")
    except ValueError:
        return None
    if not isinstance(got, dict) or not got.get("chat"):
        return None
    return got


def arm(chat_id: str, root: int | None, *, tg_chat: str = "", thread: int | None = None,
        pressed: int = 0, asked: int = 0, quote: str = "") -> dict:
    """Hold a fork off this chat, below `root`, until its first message comes
    from where it was asked for: the Telegram chat, and the topic in it.

    `quote` is the answer it comes off, as the phone showed it, for the top of
    the fork's topic. `buttons` says the question was asked with no Cancel
    button under it, which only the first day's were.
    """
    point = {"chat": chat_id, "root": root, "tg_chat": str(tg_chat or ""),
             "thread": int(thread) if thread else None, "pressed": int(pressed or 0),
             "asked": int(asked or 0), "quote": str(quote or "")[:300], "buttons": False,
             "at": time.time()}
    _set_state(ARMED, json.dumps(point))
    return point


def disarm() -> dict | None:
    """Put the waiting fork down, and hand back what it was."""
    was = armed()
    _set_state(ARMED, None)
    return was


# --- the answers, and where each came from ------------------------------------------


def remember(tg_chat: str, message_ids: list[int], chat_id: str, root: int | None) -> None:
    """Write down that these messages on the phone answered this exchange."""
    from .models import TelegramReply

    ids = [int(m) for m in message_ids or [] if m]
    if not ids or root is None or not chat_id or not tg_chat:
        return
    now = time.time()
    TelegramReply.objects.bulk_create(
        [TelegramReply(tg_chat=str(tg_chat), message_id=m, chat_id=chat_id, root=int(root),
                       created_at=now) for m in ids],
        update_conflicts=True, unique_fields=["tg_chat", "message_id"],
        update_fields=["chat_id", "root", "created_at"])


def point_of(tg_chat: str, message_id) -> tuple[str, int] | None:
    """(chat, exchange) a message on the phone answered, or None.

    None for a message that was not one of Rouh's answers - a note it sent,
    one of Petar's own - and for one whose chat has been deleted since, which
    takes its rows with it.
    """
    from .models import TelegramReply

    try:
        message_id = int(message_id)
    except (TypeError, ValueError):
        return None
    row = (TelegramReply.objects.filter(tg_chat=str(tg_chat), message_id=message_id)
           .values("chat_id", "root").first())
    if row is None or conversations.chat(row["chat_id"]) is None:
        return None
    return row["chat_id"], int(row["root"])


# --- making one --------------------------------------------------------------------


def why_not(point: dict) -> str:
    """Why a fork cannot come off this point, or "" when it can."""
    parent = str(point.get("chat") or "")
    if not parent or conversations.chat(parent) is None:
        return GONE
    root = point.get("root")
    if forks.comes_off(parent, through=int(root) if root is not None else None) is None:
        return NOTHING_TO_FORK
    return ""


def make(point: dict) -> str | None:
    """The fork a point asks for; or None.

    Made with the fork every chat has (`forks.make`), so it is the same fork
    the screen makes: beside its parent, marked in it, carrying it up to the
    point and nothing after. Written down as made on the phone, and the fork
    that was waiting is put down, in the same transaction, so a restart can
    never make it twice. The private chat stays in General. None when there is
    nothing to come off (`why_not`), with the fork left waiting.
    """
    from .models import TelegramFork

    if why_not(point):
        return None
    parent = str(point["chat"])
    root = point.get("root")
    with transaction.atomic():
        made = forks.make(parent, through=int(root) if root is not None else None)
        if made is None:
            return None
        now = time.time()
        TelegramFork.objects.update_or_create(chat_id=made,
                                              defaults={"created_at": now, "used_at": now})
        _set_state(ARMED, None)
    events.emit("chat.forked", actor="person", source="telegram", chat_id=made,
                object_type="chat", object_id=made, props={"from_chat": parent, "way": "fork"})
    log.info("telegram: fork %s made off %s%s from the phone", made, parent,
             f" below exchange {root}" if root is not None else "")
    return made


# --- a group for each fork ---------------------------------------------------------------


def fork_name(first: str) -> str:
    """What a fork is called on Telegram, from its first message: its first line, cut short."""
    line = next((ln.strip() for ln in str(first or "").splitlines() if ln.strip()), "")
    line = re.sub(r"^/fork(@\w+)?\s*", "", " ".join(line.split()), flags=re.IGNORECASE)
    if len(line) > NAME_CHARS:
        cut = line[:NAME_CHARS - 1]
        cut = cut[:cut.rfind(" ")] if " " in cut[NAME_CHARS // 2:] else cut
        line = cut.rstrip(" ,.;:-") + "…"
    return line or "A fork"


def placed(chat_id: str, tg_chat) -> None:
    """This fork's group: what is written there is written in it."""
    from .models import TelegramFork

    TelegramFork.objects.filter(chat_id=chat_id).update(tg_chat=str(tg_chat), thread_id=None)


def fork_in(tg_chat) -> str:
    """The fork a group is, or "": a group whose fork has been deleted, which
    takes its row with it, or one that was never a fork's."""
    from .models import TelegramFork

    chat_id = (TelegramFork.objects.filter(tg_chat=str(tg_chat), thread_id__isnull=True)
               .values_list("chat_id", flat=True).first())
    return chat_id if chat_id and conversations.chat(chat_id) is not None else ""


def groups() -> set[str]:
    """Every fork's group: where, besides the private chat, Petar is read."""
    from .models import TelegramFork

    return set(TelegramFork.objects.filter(thread_id__isnull=True).exclude(tg_chat="")
               .values_list("tg_chat", flat=True))


def group_of(chat_id: str) -> str:
    """The group a fork has, or ""."""
    from .models import TelegramFork

    return (TelegramFork.objects.filter(chat_id=chat_id, thread_id__isnull=True)
            .values_list("tg_chat", flat=True).first() or "")


def unplaced(tg_chat) -> bool:
    """The bot is out of this group: the fork it was is no longer written there."""
    from .models import TelegramFork

    return bool(TelegramFork.objects.filter(tg_chat=str(tg_chat)).update(tg_chat=""))


def moved(old, new) -> bool:
    """A fork's group became a supergroup, which is a new id."""
    from .models import TelegramFork

    return bool(TelegramFork.objects.filter(tg_chat=str(old)).update(tg_chat=str(new)))


# --- what a chat is called ------------------------------------------------------------


def name_of(chat_id: str, general: str) -> str:
    """What a chat is called on the phone: General, its title, or what it asks."""
    if chat_id == general:
        return "General"
    row = conversations.chat(chat_id) or {}
    title = str(row.get("title") or "").strip()
    if title and not conversations.is_untitled(title):
        return title
    asked = " ".join(forks.asked(chat_id).split())
    if asked:
        return asked if len(asked) <= NAME_ASKED else asked[:NAME_ASKED - 1].rstrip() + "…"
    return "A new fork"
