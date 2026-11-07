"""A card that asks: something about to leave Rouh, shown whole, with the button that does it.

Petar, 24 September 2026, looking at a contact Rouh had read back and was
waiting on his yes for: "this is great but also give me a button to save.
maybe that should be a template card too."

So this is the template. Any tool that is about to do something outside Rouh
- save a contact into iCloud today, and whatever goes out next - draws what it
is about to do as a card, and puts one `ask` block at the foot of it. The page
draws that block as two buttons (`askBlock` in static/app.js): the first does
the thing, exactly as the card shows it, and the second says no. Saying yes out
loud still works the way it always did, the tool called again with the person's
yes; whichever comes first is the answer, and the other finds nothing left to
answer.

A tool that wants one does two things: `register` an action by name once, with
what a yes does and, if it likes, what a no does to the card; and put
`block(...)` at the end of the card it draws. Nothing else in Rouh changes.

Four rules, and they are the reason this is a module rather than a button:

- **Only Rouh's own code can make one.** The block carries a token signed with
  the server's own key (`django.core.signing`, the key sessions are signed
  with), naming the action, what it is to be done with, whose it is and which
  thread. The model cannot make one: every block it writes has any `ask` taken
  off (`strip`). And a press names a card and nothing else - what is done is
  read out of the card as the server stored it, never out of the press.
- **Only its own person.** A press is honoured for the account the token names
  and nobody else, whichever tab it comes from.
- **One answer.** Answering revises the card without its buttons, under a lock
  per card, so two presses, or a press and a spoken yes, do it once. The card
  that is read is always the card as it is now: an older version brought back
  with its buttons on it answers "already answered".
- **The conversation hears it.** A press is put to the thread as a note from
  Rouh's own software, so the assistant says it is done and does not go on to
  do it a second time.
"""
from __future__ import annotations

import asyncio
import logging
import secrets
from dataclasses import dataclass, field
from typing import Awaitable, Callable

from . import artifacts

log = logging.getLogger("rouh.asking")

#: What a block is called, on the card and in `renderBlock`.
KIND = "ask"

#: What the token is signed for, so a token signed for anything else in Rouh
#: can never be read as one of these.
SALT = "rouh.asking"

#: How long a card may wait for its press. Long enough to come back to after a
#: meeting, short enough that a card from last week does not quietly do
#: something today.
MAX_AGE = 24 * 3600

#: The two answers a press can carry.
YES, NO = "yes", "no"


@dataclass
class Done:
    """What a yes did.

    `ok` False means it could not be done - iCloud unreachable, the password
    revoked - and the buttons stay, with `text` under them saying why, so the
    press can be made again. `card` is what the card becomes when it worked.
    """

    ok: bool
    text: str
    card: dict | None = None
    #: What the conversation is told instead of "say that it is done", for a
    #: yes whose outcome is not simply done: a location the browser would not
    #: give (`tools._location_pressed`).
    note: str = ""


@dataclass
class Action:
    #: A yes: the args the tool signed, and the press. Run as the person.
    yes: Callable[[dict, "Press"], Awaitable[Done]]
    #: A no: the card as it is, and what it becomes. None keeps the card and
    #: only takes its buttons off.
    no: Callable[[dict], dict] | None = None
    #: How the note to the conversation names what was done, "saved the contact".
    what: str = "did it"
    #: What the conversation is told after a no, if not "it was not done".
    no_note: str = ""


@dataclass
class Press:
    """One press, as the server understands it once the card has been read."""

    card: int
    choice: str
    action: str
    args: dict
    chat: str
    user_id: str
    org_id: str
    #: What the page measured and sent up with a yes, for an action only the
    #: page can do its half of: where the browser is. Never what is done - that
    #: is `args` - only what was found; the action checks every value in it.
    given: dict | None = None


@dataclass
class Answered:
    """What `answer` hands the socket: the card to draw, a note, or why not."""

    ok: bool
    why: str = ""
    again: bool = False
    spec: dict | None = None
    note: str = ""
    chat: str = ""
    #: Other cards drawn again in place because of this one. None today, but
    #: the socket redraws them, as it does for a compose card's.
    others: list = field(default_factory=list)


ACTIONS: dict[str, Action] = {}
_locks: dict[int, asyncio.Lock] = {}


def register(name: str, yes, *, no=None, what: str = "did it", no_note: str = "") -> None:
    """Say what pressing yes on a card for `name` does. Once, at start-up."""
    ACTIONS[name] = Action(yes=yes, no=no, what=what, no_note=no_note)


def _signer():
    from django.core import signing

    return signing


def block(action: str, args: dict, who, chat: str, *, yes: str, no: str,
          hint: str = "") -> dict:
    """The block that asks, for the foot of a card about to be drawn.

    `args` is exactly what a yes will do the action with, and it is sealed in
    here: the card is what the person reads, and this is what their press does,
    so the two are made from the one call.
    """
    token = _signer().dumps(
        {"a": action, "args": dict(args), "u": getattr(who, "user_id", ""),
         "o": getattr(who, "org_id", ""), "c": chat or "", "n": secrets.token_hex(4)},
        salt=SALT, compress=True)
    out = {"block": KIND, "token": token, "yes": yes, "no": no}
    if hint:
        out["hint"] = hint
    return out


def strip(blocks) -> list:
    """Blocks the model wrote, with anything that could ask taken off."""
    return [b for b in (blocks or [])
            if not (isinstance(b, dict) and str(b.get("block") or "").lower() == KIND)]


def waiting(spec: dict | None) -> dict | None:
    """The ask block on a card, if the card is still asking."""
    for b in (spec or {}).get("blocks") or []:
        if isinstance(b, dict) and b.get("block") == KIND:
            return b
    return None


def _without(spec: dict) -> dict:
    """The card as it stands, with its buttons taken off."""
    return dict(spec, blocks=strip(spec.get("blocks")))


def _read(block_: dict) -> dict | None:
    signing = _signer()
    try:
        return signing.loads(str(block_.get("token") or ""), salt=SALT, max_age=MAX_AGE)
    except signing.SignatureExpired:
        return {"expired": True}
    except signing.BadSignature:
        return None


async def answer(card, choice: str, who, *, root: str = "", given=None) -> Answered:
    """A press on a card's ask block, by `who`.

    Reads the card as the server has it now, checks that it is still asking,
    that the token in it is one this server signed, and that it is this
    person's; then does the action or declines it, and revises the card.
    `root` is the workspace, so a card already filed as a step is written
    again as it now reads. `given` is what the page measured for the press,
    handed to the action as `Press.given`.
    """
    try:
        number = int(card)
    except (TypeError, ValueError):
        return Answered(False, "That is not a card.")
    choice = YES if str(choice or "").lower() == YES else NO
    if not artifacts.enabled():
        return Answered(False, "Cards cannot be answered from here on this machine. "
                               "Say yes or no to Rouh instead.")
    # Kept, one per card ever pressed: taking one away while a second press
    # waits on it would let a third run beside it.
    async with _locks.setdefault(number, asyncio.Lock()):
        return await _answer(number, choice, who, root,
                             dict(given) if isinstance(given, dict) else None)


async def _answer(number: int, choice: str, who, root: str, given: dict | None) -> Answered:
    """The press itself, under the card's lock."""
    spec = await asyncio.to_thread(artifacts.read, number)
    asking_now = waiting(spec)
    if spec is None or asking_now is None:
        return Answered(False, "This has already been answered.")
    sealed = _read(asking_now)
    if sealed is None:
        log.warning("card %s carries an ask this server did not sign; refused", number)
        return Answered(False, "This card cannot be answered with a button.")
    if sealed.get("expired"):
        return Answered(False, "This waited too long to be answered with a button. "
                               "Ask Rouh again and it will show it afresh.")
    if (getattr(who, "user_id", None), getattr(who, "org_id", None)) != \
            (sealed.get("u"), sealed.get("o")):
        log.warning("card %s was pressed by somebody it does not belong to", number)
        return Answered(False, "This card is not yours to answer.")
    action = ACTIONS.get(str(sealed.get("a") or ""))
    if action is None:
        return Answered(False, "Nothing on this machine knows how to do that any more. "
                               "Ask Rouh again.")
    press = Press(card=number, choice=choice, action=str(sealed["a"]),
                  args=dict(sealed.get("args") or {}), chat=str(sealed.get("c") or ""),
                  user_id=str(sealed.get("u") or ""), org_id=str(sealed.get("o") or ""),
                  given=given)
    if choice == NO:
        after = action.no(_without(spec)) if action.no else _without(spec)
        revised = await _revise(number, after, root)
        return Answered(True, spec=revised, chat=press.chat, note=(
            f"the person pressed \"{asking_now.get('no') or 'No'}\" on card {number}, so "
            + (action.no_note or "nothing was done and nothing left Rouh. Say in a few "
               "words that it was not done. Do not do it.")))
    try:
        done = await action.yes(press.args, press)
    except Exception:  # noqa: BLE001 - a press must always be answered
        log.exception("the %s on card %s failed", press.action, number)
        return Answered(False, "That did not work, and nothing was changed. Try again, "
                               "or ask Rouh.", again=True)
    if not done.ok or done.card is None:
        return Answered(False, done.text, again=True)
    revised = await _revise(number, done.card, root)
    if done.note:
        return Answered(True, spec=revised, chat=press.chat, note=(
            f"the person pressed \"{asking_now.get('yes') or 'Yes'}\" on card {number}: "
            f"{done.note}"))
    return Answered(True, spec=revised, chat=press.chat, note=(
        f"the person pressed \"{asking_now.get('yes') or 'Yes'}\" on card {number} "
        f"rather than answering out loud, and Rouh {action.what}: {done.text} Say in "
        "one short sentence that it is done. Do not do it again."))


async def _revise(number: int, card: dict, root: str) -> dict | None:
    return await asyncio.to_thread(
        artifacts.revise, number, title=card.get("title"),
        description=card.get("description"), blocks=card.get("blocks") or [], root=root)


__all__ = ["KIND", "NO", "YES", "Action", "Answered", "Done", "Press", "answer", "block",
           "register", "strip", "waiting"]
