"""Got it: every message the person writes to Rouh on Telegram is marked 👀 the moment it is taken.

Built by the nightly feature run, night 36 (8 November 2026, task 94), from the Gene Nursery's N-004
(INC-465). A message written to Rouh on Telegram showed nothing until the answer began: "typing..."
comes and goes every few seconds and leaves no trace, and a message sent while Rouh was still
answering the one before, or a few sent together, waited with no sign that they had arrived at all.

So, while its switch is on, each round of messages taken from Telegram (`telegram_chat._round`) is
marked first, before any of them is answered: every one of the person's own messages in it, in
their private chat or a fork's group, gets the reaction 👀 (`telegram.react`, the Bot API's
setMessageReaction). A command such as /fork or /cancel is not a message to Rouh and is not marked.
The mark stays on the message in the chat's history, so a glance at the phone later says it was
taken, whatever happened after. Nothing is kept and no model is asked; a reaction Telegram refuses
is passed over, and the answer comes all the same.

Slack is left out: Rouh's Slack app does not have the reactions:write permission, and adding it
would mean every organisation connecting Slack again.

**Whose.** Only the person's own chats with the bot (`PhoneChat.mine`); a guest's message is never
marked.

**Its switch** is `got_it` (`rouh/switches.py`): off, nothing is marked.
"""
from __future__ import annotations

import asyncio
import logging

log = logging.getLogger("rouh.got_it")

SWITCH = "got_it"
TITLE = "Got it on Telegram: Rouh marks each message you send it with 👀 the moment it is taken"
#: The mark. One of the reactions Telegram lets a bot put.
EMOJI = "\U0001F440"


def on(who) -> bool:
    from . import switches

    return switches.on(SWITCH, getattr(who, "org_id", None) or None)


def to_mark(messages: list[dict]) -> list[dict]:
    """The messages a round brings that are worth a mark: words, a photo, a file or a voice
    note, never a command."""
    out = []
    for message in messages:
        if not isinstance(message, dict) or not message.get("message_id"):
            continue
        text = str(message.get("text") or "").lstrip()
        if text.startswith("/"):
            continue
        out.append(message)
    return out


async def mark(telegram, messages: list[dict], who) -> int:
    """Mark each of these messages 👀, while the switch is on. How many were marked."""
    chosen = to_mark(messages)
    if not chosen or not await asyncio.to_thread(on, who):
        return 0
    marked = 0
    for message in chosen:
        chat = (message.get("chat") or {}).get("id")
        if await telegram.react(chat, int(message["message_id"]), EMOJI):
            marked += 1
    if marked:
        from . import evolution

        await asyncio.to_thread(evolution.used, SWITCH, "marked", who=who,
                                detail=f"{marked} Telegram message{'s' if marked != 1 else ''} marked as taken")
    return marked


__all__ = ["EMOJI", "SWITCH", "TITLE", "mark", "on", "to_mark"]
