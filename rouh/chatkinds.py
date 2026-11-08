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

**Cheap, Smart or Auto, chat by chat** (Petar, 8 November 2026): "I am doing heavy and
difficult work and I don't want cheap model to answer me ... add a new control - model Cheap,
Smart, Auto ... saved in the settings of the chat ... whatever is on rouh, will be the default
for any new chat, unless changed later." So the control beside the composer is back, as three
words rather than a list of models, and kept on the chat (`Chat.model_choice`), never in the
browser: Cheap is the Cheaper tier, Smart the Smart tier, and Auto the router of Balanced
(`rouh/modelrouter.py`: Cheaper only when it is at least the bar sure the message is easy).
A chat with no choice of its own follows the Models page (`default_choice`): Best is Smart,
Balanced is Auto, Saver is Cheap, and a use locked to a tier is that tier. Setting one chat
never moves the Models page, and moving the Models page never rewrites a chat that has its own.
A chat set to Smart is never routed, and one set to Cheap always answers on Cheaper. Only the
person's chats take a choice (`chooses`): a case's turn and a heartbeat's chat keep their own
use's tier, and so does every unattended job, which never asks through a chat.
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


#: The three choices beside the composer, as they are kept and as they are shown.
CHEAP, SMART, AUTO = "cheap", "smart", "auto"
CHOICES = (CHEAP, SMART, AUTO)
CHOICE_NAMES = {CHEAP: "Cheap", SMART: "Smart", AUTO: "Auto"}
#: The tier a fixed choice answers on.
CHOICE_TIER = {CHEAP: modeldefaults.CHEAPER, SMART: modeldefaults.SMART}
#: What each choice means, in a line the control shows.
CHOICE_HINTS = {CHEAP: "Always the cheaper model.",
                SMART: "Always the smart model. The router never runs.",
                AUTO: "Cheap for clearly easy messages; Smart otherwise."}
#: The uses whose chats take a choice of their own: General and its forks, and every other chat.
CHOOSING = ("general", "chats")


def chooses(chat_id: str | None) -> bool:
    """Whether the control beside the composer decides this chat's model: one of the person's
    chats, never a case's turn about somebody else's words or a heartbeat's chat."""
    return bool(chat_id) and use_for(chat_id) in CHOOSING


def stored_choice(chat_id: str | None) -> str:
    """The choice this chat was given by hand, or "": the chat's own, or, for a draft not
    written down yet, the draft's (`conversations.make` carries it over)."""
    if not chat_id:
        return ""
    try:
        from .models.objects import Chat

        got = Chat.objects.filter(id=chat_id).values_list("model_choice", flat=True).first()
        if got is None:
            from . import conversations

            held = conversations.draft(chat_id)
            got = (held or {}).get("model_choice") or ""
    except Exception:                      # the Models page answers instead
        log.exception("the model chat %s is set to could not be read", chat_id)
        return ""
    return got if got in CHOICES else ""


def own_choice(chat_id: str | None) -> str:
    """The choice that decides this chat's model by hand, or "" to follow the Models page."""
    return stored_choice(chat_id) if chooses(chat_id) else ""


def default_choice(chat_id: str | None, cfg=None, now=None) -> str:
    """What a chat with no choice of its own is on, from the Models page: Auto when its use is
    routed (Balanced), else its use's tier (Best is Smart, Saver is Cheap); "" for a use on a
    model of its own or off, which no three words describe."""
    now = now or modeldefaults.Now(None, cfg)
    kind = now.kind(use_for(chat_id))
    return {modeldefaults.AUTO: AUTO, modeldefaults.CHEAPER: CHEAP,
            modeldefaults.SMART: SMART}.get(kind, "")


def choice_of(chat_id: str | None, cfg=None) -> dict:
    """What the control beside the composer shows for this chat: the choice in force, whether
    it is the chat's own or the Models page's, the default it would follow, and the model each
    choice answers with here."""
    now = modeldefaults.Now(None, cfg)
    use = use_for(chat_id)
    default = default_choice(chat_id, now=now)
    own = own_choice(chat_id)
    models = {c: now.tier_pair(use, t).model for c, t in CHOICE_TIER.items()}
    return {"chat": chat_id or "", "choice": own or default, "own": bool(own), "default": default,
            "chooses": chooses(chat_id), "mode": now.mode,
            "options": [{"id": c, "name": CHOICE_NAMES[c], "hint": CHOICE_HINTS[c],
                         "model": models.get(c, ""),
                         "model_name": model_name(models[c]) if models.get(c) else ""}
                        for c in CHOICES]}


def set_choice(chat_id: str, choice: str) -> bool:
    """Keep this chat's choice ("" goes back to the Models page's default). A draft keeps it
    until it is written down. False when there is no such chat or the choice is not one."""
    from . import conversations
    from .models.objects import Chat

    chat_id = (chat_id or "").strip()
    choice = (choice or "").strip().lower()
    if not chat_id or (choice and choice not in CHOICES):
        return False
    if Chat.objects.filter(id=chat_id).update(model_choice=choice):
        return True
    return conversations.draft_choice(chat_id, choice)


def routes(chat_id: str | None, cfg=None) -> bool:
    """Whether this chat is on Auto: each turn's tier is picked by a model that reads
    the message (`rouh/modelrouter.py`). The chat's own choice first: Smart and Cheap
    never route, and Auto always does."""
    own = own_choice(chat_id)
    if own:
        return own == AUTO
    return modeldefaults.use_tier(use_for(chat_id), cfg=cfg) == modeldefaults.AUTO


def model_for(chat_id: str | None, cfg=None) -> str:
    """The model that answers in this chat: its own fixed choice's tier when it has one; on
    Auto, the fallback tier's, for what asks without a message to read (a turn routes before
    it asks)."""
    own = own_choice(chat_id)
    if own in CHOICE_TIER:
        return tier_model(chat_id, CHOICE_TIER[own], cfg)
    if own == AUTO:
        return tier_model(chat_id, modeldefaults.AUTO_FALLBACK, cfg)
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
