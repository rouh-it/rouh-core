"""How a turn came in and how its reply goes out: written or spoken.

Petar, 21 October 2026 (chat-b812766baac4), after a typed question about a step was answered "ninety-eight dash
nineteen": "you obviously don't speak most of the time, we have been typing mostly. so those instructions about
speaking are wrong ... there needs to be a way of figuring out whether our conversation is piping through text or
voice." Until then every turn was told it was speaking out loud.

Two things are known about every turn, and both are decided here and nowhere else:

- **How the person's words came** (`heard`): `voice` said into the microphone on a screen, `voice_note` a
  Telegram voice note, `typed` the box, `telegram` a Telegram text, `note` Rouh's own software (a job's report,
  a reminder, an email). Kept on the message as `spoken` (`memory.Memory.add_message`); unknown is typed.
- **How the reply is made** (`mode`): `voice` when it is said aloud to somebody who spoke, `text` otherwise.
  Typed in is written out, even with spoken replies on, because the person is reading the screen they typed
  into. A voice note is answered in Telegram, in writing. A note of Rouh's own is spoken only when it is said
  aloud. The rules on the Rules page kept to that mode are the ones the turn is told (`rules.prompt_block`).

The turn marks (`rouh/turnmarks.py`) belong to the microphone alone: only words heard there can stop in the
middle of a thought, so only a turn of them is told to start its reply with a mark.
"""
from __future__ import annotations

import contextvars
from dataclasses import dataclass

#: How the person's words came. The first two were said aloud.
SPOKEN_IN = ("voice", "voice_note")
HEARD = ("voice", "voice_note", "typed", "telegram", "note")


@dataclass(frozen=True)
class Mode:
    #: How the person's words came (`HEARD`).
    heard: str = "typed"
    #: How the reply is made: "text" or "voice" (`rules.MODES`).
    reply: str = "text"
    #: Whether the model is told the turn marks.
    marks: bool = False

    @property
    def spoken_in(self) -> bool:
        return self.heard in SPOKEN_IN


#: The turn being answered now (`brain.Brain.run_turn`); outside one, a typed turn written out.
NOW: contextvars.ContextVar[Mode] = contextvars.ContextVar("rouh_reply_mode", default=Mode())


def heard_as(how: str, *, note: bool = False) -> str:
    """One of `HEARD` for what a doorway said about a message: a note is a note, and unknown is typed."""
    if note:
        return "note"
    return how if how in HEARD else "typed"


def of(heard: str, *, spoken_reply: bool, answer_now: bool) -> Mode:
    """The mode of a turn: how it came, whether its reply is said aloud, and whether it was finished when it
    started (`answer_now`), which only words from the microphone may not be."""
    heard = heard_as(heard)
    reply = "voice" if spoken_reply and heard != "typed" and heard != "telegram" else "text"
    return Mode(heard=heard, reply=reply, marks=heard == "voice" or not answer_now)


#: How the person's words came, as the rule for this turn says it (`rules.placed`, "this-turn-written"
#: and "this-turn-spoken", whose words say how the reply reaches them).
CAME = {"voice": "said this aloud, into the microphone", "voice_note": "sent this as a Telegram voice note",
        "typed": "typed this", "telegram": "wrote this on Telegram",
        "note": "did not write this: it is a note of Rouh's own software"}


def came(mode: Mode) -> str:
    """How this turn's words came, for the built-in rule that tells the model how the turn reaches it."""
    return CAME.get(mode.heard, CAME["typed"])


__all__ = ["HEARD", "Mode", "NOW", "CAME", "SPOKEN_IN", "came", "heard_as", "of"]
