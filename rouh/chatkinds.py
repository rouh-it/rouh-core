"""Two kinds of chat, each with its own rules: General, and every other one.

Petar, 26 September 2026, asked for chats to be "treated as two different
kinds, with different settings, applied automatically by the kind of chat".
Until then there was one set of rules for every chat, and it was General's.

**General** is the one conversation that is always there
(`conversations.GENERAL`): the person's infinite chat for everything, with no
topic, running to thousands of messages going back months, and the channel
any request of the day goes to. It cannot be sent whole, so it keeps what
makes it work at that length: a window of its newest messages
(`history_turns`), the old tool results in that window trimmed
(`rouh/context_editing.py`), and the prompt cache (`rouh/promptcache.py`).

**Every other chat** - a topic, a task's thread, the chat an email is handled
in, a fork - is about one thing, and is sent whole: every message it has, and
every tool result as it came back. Nothing is trimmed and nothing is
summarised. The prompt cache stays, because it changes what a request costs
and never what it says. A fork carries the chat it came off the way that chat
is sent itself, so a fork of General carries General's window up to the fork,
and the whole of its own conversation after it.

**A chat too long for its model is not cut to fit.** The request goes out
whole, the API refuses it, and the person is told so in words that stay on
the screen until they close them (`too_long`, `filled`). Compacting a chat
that long is a later piece of work and is deliberately not here. What is here
is that nothing is ever dropped from a chat without anybody knowing.

**Which model answers is the chat's kind's too**, and nobody picks it chat by
chat: the box beside the composer that did is gone (Petar, 18 October 2026).
General, and every fork of General, is the use "general" on the Models page,
a chat a heartbeat beats in is the heartbeat's decision, a turn about somebody
else's email or message is "case_read", and every other chat is the use
"chats" (`use_for`); each is on a tier, and the tier is a model
(`rouh/modeldefaults.py`). How deeply it thinks comes with the model. An
OpenAI model is asked through `rouh/luna.py`, and only with an OpenAI key in
this service's environment; without one the tier's Anthropic stand-in answers
(`modeldefaults.Now.model_for`).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from . import context_editing, conversations, modeldefaults
from .config import config as _config
from .config import current_model, model_name

log = logging.getLogger("rouh.chatkinds")

#: The chat that is General.
GENERAL = conversations.GENERAL

#: "Every message", to `memory.Memory.history`: a limit below zero is none.
WHOLE = -1

@dataclass(frozen=True)
class Profile:
    """What one kind of chat sends the model with each turn."""

    #: "general" or "topic".
    kind: str
    #: How many of the chat's newest messages go with a turn: WHOLE is all.
    history: int
    #: Whether old tool results are trimmed out of what is sent, and the three
    #: numbers that say which (`rouh/context_editing.py`).
    trims: bool
    keep_messages: int = 0
    budget_tokens: int = 0
    min_body: int = 0


def is_general(chat_id: str | None) -> bool:
    return (chat_id or "") == GENERAL


def of_general(chat_id: str | None) -> bool:
    """Whether this chat is General or a fork that came off it, at any depth.

    A fork of General answers on General's tier, so a question asked on the
    side of General is asked of the same model. Petar, 28 September 2026
    (fr_430486e07b11): "When I said that I want general chat to default to
    Luna, all forks of the general chat should also default to Luna." Only the
    model follows General: a fork is still sent whole, like every chat but
    General (`profile`).
    """
    if is_general(chat_id):
        return True
    if not chat_id:
        return False
    from . import forks
    try:
        return forks.root_of(chat_id) == GENERAL
    except Exception:                      # the default answers instead
        log.exception("where chat %s was forked from could not be read", chat_id)
        return False


def profile(chat_id: str | None, cfg=None) -> Profile:
    """The rules for this chat, by its kind."""
    cfg = cfg or _config
    if is_general(chat_id):
        return Profile(
            kind="general",
            history=int(getattr(cfg, "history_turns", 40)),
            trims=bool(getattr(cfg, "context_editing", True)),
            keep_messages=int(getattr(cfg, "context_keep_messages",
                                      context_editing.KEEP_MESSAGES)),
            budget_tokens=int(getattr(cfg, "context_budget_tokens", 0)),
            min_body=int(getattr(cfg, "context_min_body", context_editing.MIN_BODY)),
        )
    return Profile(kind="topic", history=WHOLE, trims=False)


def use_for(chat_id: str | None) -> str:
    """The use on the Models page whose tier this chat answers on: "case_read"
    for a turn about somebody else's email or message (a case's reading or its
    start), the heartbeat's decision in a chat its beats run in, "general" for
    General and every fork of it, and "chats" for every other chat."""
    if of_case():
        return "case_read"
    if of_heartbeat(chat_id):
        return "heartbeat_decide"
    return "general" if of_general(chat_id) else "chats"


def kind_pair(chat_id: str | None, cfg=None) -> modeldefaults.Pair:
    """The model this chat answers with, and the level it thinks at."""
    return modeldefaults.use_pair(use_for(chat_id), cfg=cfg)


def of_case() -> bool:
    """Whether this turn is one of a case's, about somebody else's email, Telegram or Slack
    message (`mail_turn.CURRENT`, set around the turn and inherited by everything in it). Its
    model is the use "case_read", on a tier and never routed per message (Petar, 21 October
    2026: the reading of somebody else's words is never left to the cheapest model)."""
    from . import mail_turn

    turn = mail_turn.now()
    return turn is not None and bool(turn.mode) and bool(turn.case_id)


def of_heartbeat(chat_id: str | None) -> bool:
    """Whether this is a chat the heartbeat's beats run in (`heartbeat.CHATS`)."""
    from . import heartbeat

    return bool(chat_id) and chat_id in heartbeat.CHATS


def routes(chat_id: str | None, cfg=None) -> bool:
    """Whether this chat is on Auto: each turn's tier is picked by a model that reads
    the message (`rouh/modelrouter.py`)."""
    return modeldefaults.use_tier(use_for(chat_id), cfg=cfg) == modeldefaults.AUTO


def model_for(chat_id: str | None, cfg=None) -> str:
    """The model that answers in this chat: on Auto, the fallback tier's, for what
    asks without a message to read (a turn routes before it asks)."""
    return current_model(kind_pair(chat_id, cfg).model)


def tier_model(chat_id: str | None, tier: str, cfg=None) -> str:
    """The model this chat answers with on `tier`, whatever tier it is on: a tier
    the person picked for one answer (`runtime.Turns.start`)."""
    return current_model(modeldefaults.Now(None, cfg).tier_pair(use_for(chat_id), tier).model)


def _sent_whole(chat_id: str | None) -> str:
    if is_general(chat_id):
        return ("That is General cut down to its newest messages, with its old "
                "tool results trimmed.")
    return ("Nothing in it was cut to make it fit: every chat but General is "
            "always sent whole. It needs compacting, which Rouh does not do yet, "
            "so carry on in a new chat for now.")


def too_long(chat_id: str | None, model: str, sent: int = 0, holds: int = 0) -> str:
    """What the person is told when a chat is more than its model can read.

    `sent` and `holds` are the API's own numbers, when it gave them
    (`retrying.overflowed`).
    """
    name = model_name(model) or "the model"
    what = "General" if is_general(chat_id) else "This chat"
    size = (f" It comes to {sent:,} tokens, and {name} reads {holds:,}."
            if sent and holds else "")
    return (f"{what} is longer than {name} can read at once, so it was not "
            f"answered.{size} {_sent_whole(chat_id)}")


def filled(chat_id: str | None, model: str) -> str:
    """What the person is told when the window filled while the answer was
    being written, and the answer stopped part way."""
    name = model_name(model) or "the model"
    what = "General" if is_general(chat_id) else "this chat"
    return (f"The answer stopped part way: {what} filled all that {name} can read "
            f"while it was being written. {_sent_whole(chat_id)}")
