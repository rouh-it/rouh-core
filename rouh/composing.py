"""A card the person writes in, and the button that sends it.

Petar, 24 September 2026, after Rouh drafted a reply, showed it in a card and
he said "send it": "the card still says Draft, and later the draft was still in
my Gmail drafts next to the sent reply [...] when you draft an email and show
it in a card, it needs to be a card that is dynamic. It should be editable, so
I can change the text, have a send button. Once I send it, it should say sent
and not be editable anymore [...] I guess we will have other such template
cards later for other stuff."

So this is the second template card, beside `rouh/asking.py`, and the two are
the same idea one step apart. `asking` shows what is about to happen and asks
for a yes: the person reads and presses, and what is done is exactly what the
card shows. This one lets them **change** it first. The card is a small compose
window - named fields, a body they can format, the files going with it - and
one button that does the thing with what they have written rather than with
what the tool wrote.

A tool that wants one does two things: `register` an action by name once, with
what the button does; and put `block(...)` in the card it draws. Today the one
action is sending an email (`tools.py`, `draft_mail`); tomorrow's is whatever
else the person should be able to correct before it leaves.

The rules are `asking`'s, with one deliberate difference.

- **Only Rouh's own code can make one.** The block carries a token signed with
  the server's own key naming the action, what it is to be done with, whose it
  is and which thread. The model cannot make one: every block it writes has any
  `compose` taken off (`strip`).
- **Only its own person.** A press is honoured for the account the token names
  and nobody else, whichever tab it comes from.
- **Once.** Sending revises the card into its sent state, which carries no
  token, under a lock per card, so two presses send one email. A card brought
  back from an older version still says sent, because the card that is read is
  always the card as it is now.
- **The conversation hears it.** A send is put to the thread as a note from
  Rouh's own software, so the assistant says it has gone and does not send it a
  second time.
- **The difference: what the person typed is carried by the press.** In
  `asking` a press names a card and nothing else, because nothing about it is
  the person's to change. Here the whole point is that it is theirs to change,
  so the edits come up with the press. They are the person's own words typed
  into their own card, and they are still cleaned on the way in: addresses and
  the subject down to one line, the body down to the handful of tags a person
  can actually produce with the buttons on the card (`clean_html`). What is
  never taken from the press is what is *done* - the action, the draft it
  belongs to, whose it is - which is read out of the token the server signed.

Edits are saved as the person types (`SAVE`), so a reload or a second tab finds
the card as they left it, and so that the words are not lost if they wander off
before pressing anything. A save rewrites the card where it stands rather than
adding a version per keystroke (`artifacts.amend`); sending adds the version, so
the history of the card is draft-as-sent and not a reel of typing.
"""
from __future__ import annotations

import asyncio
import html as html_mod
import logging
import re
import secrets
import time
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Awaitable, Callable

from . import artifacts

log = logging.getLogger("rouh.composing")

#: What a block is called, on the card and in `renderBlock`.
KIND = "compose"

#: What the token is signed for, so a token signed for anything else in Rouh
#: can never be read as one of these.
SALT = "rouh.composing"

#: How long a card may wait to be sent. A week: a draft is a thing a person
#: comes back to, which is the whole reason it is a draft, and a fortnight-old
#: card quietly sending today is the thing this stops.
MAX_AGE = 7 * 24 * 3600

#: The two things the page asks of a card: keep what I have written, and do it.
SAVE, SEND = "save", "send"

#: A card is being written in, or is done with: sent, or not sent because
#: another draft of the same email went instead (`drop`).
DRAFT, SENT, NOT_SENT = "draft", "sent", "not_sent"

#: The states a card is done with, and has no button to press.
DONE_WITH = (SENT, NOT_SENT)

#: The most a body may be. Well past any email a person writes by hand, and
#: short enough that a runaway paste cannot fill a row.
MAX_BODY = 200_000

#: The most one field - an address line, a subject - may be.
MAX_FIELD = 2_000

#: The tags the body may carry. Exactly what the buttons on the card can make,
#: plus the ones a paste from a real email brings with it. Everything else is
#: unwrapped rather than dropped: the words inside a tag nobody allowed are
#: still the person's words.
ALLOWED = {"p", "br", "div", "b", "strong", "i", "em", "u", "s", "strike", "del",
           "a", "ul", "ol", "li", "blockquote", "span", "h1", "h2", "h3"}

#: Tags whose contents go with them. A <script> is not text with markup around
#: it, and unwrapping one would paste its source into the email.
DROPPED = {"script", "style", "head", "title", "iframe", "object", "embed", "svg"}

#: Tags that stand alone.
EMPTY = {"br", "img", "hr"}

#: Where a link may point. `javascript:` in an href is the whole reason this is
#: a list rather than a check for a colon.
SCHEMES = ("http://", "https://", "mailto:", "tel:")


class Refused(ValueError):
    """Why this cannot go, in a sentence the person reads under the button.

    Raised by an action rather than returned, for the checks that happen deep
    inside one - a file that is not there, more bytes than the far end takes -
    and caught where the action can turn it into a `Done` that leaves the card
    exactly as they wrote it.
    """


@dataclass
class Done:
    """What the button did.

    `ok` False means it could not be done - Gmail out of reach, an address
    Gmail would not take - and the card stays exactly as the person has it,
    with `text` under the button saying why, so it can be pressed again.
    `card` is what the card becomes when it worked. `others` are other cards
    the press changed on the way, as they now read - another draft of the
    same email turned over to Not sent - for the page to draw where they are.
    """

    ok: bool
    text: str
    card: dict | None = None
    others: list = field(default_factory=list)


@dataclass
class Action:
    #: The button: what the tool sealed in, what the person typed, and the
    #: press. Run as the person.
    do: Callable[[dict, dict, "Press"], Awaitable[Done]]
    #: How the note to the conversation names what happened, "sent the email".
    what: str = "did it"


@dataclass
class Press:
    """One press, as the server understands it once the card has been read."""

    card: int
    action: str
    args: dict
    edits: dict = field(default_factory=dict)
    chat: str = ""
    user_id: str = ""
    org_id: str = ""


@dataclass
class Answered:
    """What a press hands the socket: the card to draw, a note, or why not."""

    ok: bool
    why: str = ""
    again: bool = False
    saved: bool = False
    spec: dict | None = None
    note: str = ""
    chat: str = ""
    others: list = field(default_factory=list)


ACTIONS: dict[str, Action] = {}
_locks: dict[int, asyncio.Lock] = {}


def register(name: str, do, *, what: str = "did it") -> None:
    """Say what the button on a card for `name` does. Once, at start-up."""
    ACTIONS[name] = Action(do=do, what=what)


def _signer():
    from django.core import signing

    return signing


def block(action: str, args: dict, who, chat: str, *, fields: list[dict],
          body: str = "", attachments: list[dict] | None = None,
          send: str = "Send", hint: str = "", can_attach: bool = False,
          state: str = DRAFT, said: str = "") -> dict:
    """The compose block a card is drawn around.

    `args` is what the button will do the action with - the draft it belongs
    to, the message it answers - and it is sealed in here, so what a press does
    is decided by the tool that drew the card and never by the page. What the
    person may change is `fields` and `body`, and those come back up with the
    press.
    """
    out = {
        "block": KIND,
        "state": state if state in DONE_WITH else DRAFT,
        "fields": [dict(f) for f in (fields or [])],
        "body": str(body or ""),
        "attachments": [dict(a) for a in (attachments or [])],
        "send": send,
        "can_attach": bool(can_attach),
    }
    if hint:
        out["hint"] = hint
    if said:
        out["said"] = said
    if out["state"] == DRAFT:
        # The draft as it was first written, before the person typed in it: the card keeps what
        # they write as they go, so this is what tells their changes apart (`rouh/draft_edits.py`).
        out["first"] = {"fields": {str(f.get("name") or ""): str(f.get("value") or "")
                                   for f in out["fields"]}, "body": out["body"]}
        out["token"] = _signer().dumps(
            {"a": action, "args": dict(args), "u": getattr(who, "user_id", ""),
             "o": getattr(who, "org_id", ""), "c": chat or "", "n": secrets.token_hex(4)},
            salt=SALT, compress=True)
    return out


def sent_block(was: dict, said: str, *, at: float = 0.0, after: str = "",
               state: str = SENT) -> dict:
    """The same block, done with: read-only, no button, and no token to press.

    Built from the block as it stands rather than from scratch, so the card
    says what was actually sent, field for field and word for word. `at` is
    when it went, as a moment for the page to put a clock on rather than a
    time already written out: every other time on a card is the reader's own.
    `after` is what became of the rest once it went, in a sentence under the
    head - the conversation archived, an older draft of it taken out of
    Drafts - so the card says what Gmail now shows.
    """
    out = {k: v for k, v in (was or {}).items()
           if k not in ("token", "hint", "can_attach", "after", "first")}
    out["block"] = KIND
    out["state"] = state if state in DONE_WITH else SENT
    out["said"] = said
    if at:
        out["at"] = float(at)
    if after:
        out["after"] = after
    return out


def sealed(block_: dict | None) -> dict | None:
    """What a draft card's token says it is for, however old, or None.

    For reading which email a card is a draft of, never for acting on it: a
    press is checked by `_read`, which also refuses a token past `MAX_AGE`.
    An old card is still a draft sitting in the person's Gmail, and still
    one to tidy away when another draft of the same email is sent.
    """
    signing = _signer()
    try:
        return signing.loads(str((block_ or {}).get("token") or ""), salt=SALT)
    except signing.BadSignature:
        return None


async def drop(card, said: str, *, after: str = "", description: str | None = None,
               root: str = "", first=None, wait: float = 5.0) -> dict | None:
    """Turn a draft card over to Not sent, because another draft of it went.

    Petar, 26 September 2026: Rouh drafted a reply, drafted it again when he
    asked for a change, and he sent the second from its card. The first was
    left in his Gmail drafts beside the sent reply, and its card still had a
    Send button that would have sent the same answer twice. So when one draft
    of an email is sent, every other one Rouh drew of it is taken out of
    Drafts (`tools.py`) and its card comes here: the words it held, read-only,
    and no button.

    Under the card's own lock, so a save typed a moment earlier is not written
    back over it. `first` is what has to happen before the card may say so -
    the draft taken out of Gmail - and runs under the lock too; if it raises,
    the card is left as it was and the error is the caller's. A card whose
    lock is held past `wait` is being sent or saved this moment and is left
    alone rather than waited on: two drafts of one email sent at once would
    otherwise each wait for the other. None when the card is already done
    with, busy, or not a card.
    """
    try:
        number = int(card)
    except (TypeError, ValueError):
        return None
    lock = _locks.setdefault(number, asyncio.Lock())
    try:
        await asyncio.wait_for(lock.acquire(), wait)
    except asyncio.TimeoutError:
        log.info("card %s is busy, so it is left as it is", number)
        return None
    try:
        spec = await asyncio.to_thread(artifacts.read, number)
        open_ = waiting(spec)
        if spec is None or open_ is None:
            return None
        if first is not None:
            await first()
        done = sent_block(open_, said, at=time.time(), after=after, state=NOT_SENT)
        return await asyncio.to_thread(
            artifacts.revise, number, description=description,
            blocks=_blocks_with(spec, done), root=root)
    finally:
        lock.release()


def strip(blocks) -> list:
    """Blocks the model wrote, with anything that could send taken off."""
    return [b for b in (blocks or [])
            if not (isinstance(b, dict) and str(b.get("block") or "").lower() == KIND)]


def waiting(spec: dict | None) -> dict | None:
    """The compose block on a card, if the card is still one to write in."""
    for b in (spec or {}).get("blocks") or []:
        if isinstance(b, dict) and b.get("block") == KIND and b.get("state") not in DONE_WITH:
            return b
    return None


def not_sent(spec: dict | None) -> bool:
    """Whether a card is a draft that was not sent because another one went."""
    return any(isinstance(b, dict) and b.get("block") == KIND and b.get("state") == NOT_SENT
               for b in (spec or {}).get("blocks") or [])


# ---------------------------------------------------------------------------
# Content conversion and edit normalization
# ---------------------------------------------------------------------------


class _Clean(HTMLParser):
    """The body as markup Rouh is willing to put in an email.

    An allowlist and not a blocklist: a tag nobody named is unwrapped, which
    keeps the words and loses the markup, and the handful whose contents are
    not words at all are dropped whole. Attributes go except `href` on a link,
    and a link may only point somewhere a link points.
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self._open: list[str] = []
        self._dropping = 0

    def handle_starttag(self, tag, attrs):
        if tag in DROPPED:
            self._dropping += 1
            return
        if self._dropping or tag not in ALLOWED:
            return
        if tag in EMPTY:
            self.out.append("<br>")
            return
        if tag == "a":
            href = ""
            for name, value in attrs:
                if name.lower() == "href":
                    href = (value or "").strip()
            if not href.lower().startswith(SCHEMES):
                self.out.append("<span>")
                self._open.append("span")
                return
            self.out.append(f'<a href="{html_mod.escape(href, quote=True)}">')
            self._open.append("a")
            return
        self.out.append(f"<{tag}>")
        self._open.append(tag)

    def handle_startendtag(self, tag, attrs):
        if tag in EMPTY and not self._dropping:
            self.out.append("<br>")

    def handle_endtag(self, tag):
        if tag in DROPPED:
            self._dropping = max(0, self._dropping - 1)
            return
        if self._dropping or tag not in ALLOWED or tag in EMPTY:
            return
        # Close back to it, so markup that closes out of order comes out
        # nested rather than as tags in the wrong places.
        if tag not in self._open:
            return
        while self._open:
            open_ = self._open.pop()
            self.out.append(f"</{open_}>")
            if open_ == tag or (tag == "a" and open_ == "span"):
                break

    def handle_data(self, data):
        if not self._dropping and data:
            self.out.append(html_mod.escape(data, quote=False))

    def markup(self) -> str:
        while self._open:
            self.out.append(f"</{self._open.pop()}>")
        return "".join(self.out)


def clean_html(raw: str) -> str:
    """One body, as markup that is safe to send and is still what they wrote."""
    raw = str(raw or "")[:MAX_BODY]
    parser = _Clean()
    try:
        parser.feed(raw)
        parser.close()
    except Exception:  # noqa: BLE001 - a malformed paste is not an error
        log.warning("a composed body could not be parsed as markup; sent as text")
        return html_mod.escape(raw, quote=False)
    return parser.markup()


#: Where one line ends in the plain-text alternative.
_BREAK = re.compile(r"</?(?:p|div|br|li|ul|ol|blockquote|h[1-3])[^>]*>", re.I)
_TAG = re.compile(r"<[^>]+>")
_BLANKS = re.compile(r"\n{3,}")


#: A quoted block with no other quoted block inside it, so the innermost are
#: turned into text first and each level round them adds its own `> `.
_INNERMOST_QUOTE = re.compile(
    r"<blockquote\b[^>]*>((?:(?!<blockquote\b).)*?)</blockquote\s*>", re.I | re.S)


def as_text(markup: str) -> str:
    """The same body as plain text, for the alternative part of the email.

    Every email goes out as both, because plenty of people read mail as text
    and a reader handed only markup is handed tags. List items keep their
    bullet, because a list read as a run-on paragraph has lost the point of
    being a list, and a quoted block keeps `> ` in front of every line, which
    is how quoting has always been written in a text email: a reply's quote of
    the message it answers used to arrive as more lines of the reply.
    """
    text = str(markup or "")
    while True:
        quoted = _INNERMOST_QUOTE.sub(_quoted_as_markup, text)
        if quoted == text:
            break
        text = quoted
    return _plain(text)


def _quoted_as_markup(found) -> str:
    """One innermost quote, as markup again but already written out as `> ` lines."""
    lines = _plain(found.group(1)).split("\n")
    said = "\n".join(("> " + line) if line else ">" for line in lines)
    return "<div>" + html_mod.escape(said, quote=False).replace("\n", "<br>") + "</div>"


def _plain(markup: str) -> str:
    text = str(markup or "")
    # The bullet comes from the opening tag, so the closing one goes first:
    # otherwise every item is followed by a blank line.
    text = re.sub(r"</li\s*>", "", text, flags=re.I)
    text = re.sub(r"<li[^>]*>", "\n- ", text, flags=re.I)
    text = _BREAK.sub("\n", text)
    text = _TAG.sub("", text)
    text = html_mod.unescape(text)
    text = "\n".join(line.rstrip() for line in text.split("\n"))
    return _BLANKS.sub("\n\n", text).strip()


def from_text(text: str) -> str:
    """Plain text as the markup a compose card starts out holding.

    The model writes an email as words with blank lines in it, and the card
    edits markup, so this is the one conversion between them: a blank line is
    a paragraph, a single newline is a line break, and everything else is
    escaped rather than read as markup.
    """
    text = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    out = []
    for para in re.split(r"\n\s*\n", text):
        lines = [html_mod.escape(line, quote=False) for line in para.split("\n")]
        said = "<br>".join(lines).strip()
        if said:
            out.append(f"<p>{said}</p>")
    return "".join(out)


def one_line(raw: str) -> str:
    """An address line or a subject: one line, nothing enormous, and nothing taken out.

    Plain text, never markup: these come out of a text box and go into an email
    header, and are only ever drawn as text. Reading them as markup used to
    take "<sam@example.org>" off "Sam Rivera <sam@example.org>" as
    though it were a tag, and the email went to "Sam Rivera", which is not
    an address.
    """
    return " ".join(str(raw or "").split())[:MAX_FIELD]


def edits_of(raw, *, fields: list[str] | None = None) -> dict:
    """What the page sent, cleaned: the fields as lines, the body as markup."""
    raw = raw if isinstance(raw, dict) else {}
    out: dict = {"fields": {}, "body": "", "attachments": []}
    out["fields"] = _field_lines(raw.get("fields"), fields)
    out["body"] = clean_html(raw.get("body"))
    out["attachments"] = _attachment_ids(raw.get("attachments"))
    return out


def _field_lines(given, fields: list[str] | None) -> dict:
    """Named editable fields, limited to the card's names when supplied."""
    out = {}
    if isinstance(given, dict):
        for name, value in given.items():
            name = str(name)[:64]
            if fields is not None and name not in fields:
                continue
            out[name] = one_line(value)
    return out


def _attachment_ids(given) -> list:
    """The bounded attachment selection, in its first-seen order."""
    out = []
    seen = set()
    for one in (given or [])[:20]:
        if isinstance(one, dict):
            ident = str(one.get("id") or "")[:128]
        else:
            ident = str(one or "")[:128]
        if ident and ident not in seen:
            seen.add(ident)
            out.append(ident)
    return out


def _with_edits(was: dict, edits: dict, attachments: list[dict]) -> dict:
    """The block as the person now has it: their lines, their body, their files."""
    fields = []
    for one in was.get("fields") or []:
        name = str(one.get("name") or "")
        fields.append(dict(one, value=edits["fields"].get(name, one.get("value") or "")))
    return dict(was, fields=fields, body=edits["body"],
                attachments=[dict(a) for a in attachments])


def _edited_draft(was: dict, raw, files: list[dict]) -> tuple[dict, dict]:
    """Normalize the editable content and apply it to the draft it belongs to."""
    named = [str(f.get("name") or "") for f in (was.get("fields") or [])]
    kept = edits_of(raw, fields=named)
    now = _with_edits(was, kept, files)
    return kept, now


def _blocks_with(spec: dict, block_: dict) -> list:
    """The card's blocks, with its compose block replaced by this one."""
    out = []
    for b in spec.get("blocks") or []:
        if isinstance(b, dict) and b.get("block") == KIND and b.get("state") not in DONE_WITH:
            out.append(block_)
        else:
            out.append(b)
    return out


# ---------------------------------------------------------------------------
# The press
# ---------------------------------------------------------------------------


def _read(block_: dict) -> dict | None:
    signing = _signer()
    try:
        return signing.loads(str(block_.get("token") or ""), salt=SALT, max_age=MAX_AGE)
    except signing.SignatureExpired:
        return {"expired": True}
    except signing.BadSignature:
        return None


async def press(card, what: str, edits, who, *, files: list[dict] | None = None,
                root: str = "") -> Answered:
    """A save or a send on a compose card, by `who`.

    Reads the card as the server has it now, checks that it is still one to
    write in, that the token in it is one this server signed and that it is
    this person's; then keeps what they wrote, or does the thing with it.
    `files` are the attachments the press named, already found on disk by
    whoever is holding the socket. `root` is the workspace, so a card already
    filed as a step is written again as it now reads.
    """
    try:
        number = int(card)
    except (TypeError, ValueError):
        return Answered(False, "That is not a card.")
    what = SEND if str(what or "").lower() == SEND else SAVE
    if not artifacts.enabled():
        return Answered(False, "Cards cannot be written in from here on this machine.")
    async with _locks.setdefault(number, asyncio.Lock()):
        return await _press(number, what, edits, who, files or [], root)


async def _press(number: int, what: str, edits, who, files: list[dict],
                 root: str) -> Answered:
    spec = await asyncio.to_thread(artifacts.read, number)
    open_ = waiting(spec)
    if spec is not None and open_ is None and not_sent(spec):
        return Answered(False, "This draft was not sent: another draft of the same email "
                               "went instead, and this one was taken out of Drafts.")
    if spec is None or open_ is None:
        return Answered(False, "This has already been sent.")
    sealed = _read(open_)
    if sealed is None:
        log.warning("card %s carries a compose this server did not sign; refused", number)
        return Answered(False, "This card cannot be sent from a button.")
    if sealed.get("expired"):
        return Answered(False, "This draft waited too long to be sent from its card. "
                               "Ask Rouh to draft it again.")
    if (getattr(who, "user_id", None), getattr(who, "org_id", None)) != \
            (sealed.get("u"), sealed.get("o")):
        log.warning("card %s was written in by somebody it does not belong to", number)
        return Answered(False, "This card is not yours.")
    kept, now = _edited_draft(open_, edits, files)
    if what == SAVE:
        await asyncio.to_thread(artifacts.amend, number, blocks=_blocks_with(spec, now),
                                root=root)
        return Answered(True, saved=True, chat=str(sealed.get("c") or ""))
    action = ACTIONS.get(str(sealed.get("a") or ""))
    if action is None:
        return Answered(False, "Nothing on this machine knows how to send that any "
                               "more. Ask Rouh.")
    press_ = Press(card=number, action=str(sealed["a"]), args=dict(sealed.get("args") or {}),
                   edits=dict(kept, block=now, files=list(files)),
                   chat=str(sealed.get("c") or ""), user_id=str(sealed.get("u") or ""),
                   org_id=str(sealed.get("o") or ""))
    try:
        done = await action.do(press_.args, press_.edits, press_)
    except Exception:  # noqa: BLE001 - a press must always be answered
        log.exception("the %s on card %s failed", press_.action, number)
        return Answered(False, "That did not go, and nothing was sent. Try again, or "
                               "ask Rouh.", again=True)
    if not done.ok or done.card is None:
        # What they wrote is kept even though it did not go, so a failed send
        # never costs the person the words they had just typed.
        await asyncio.to_thread(artifacts.amend, number, blocks=_blocks_with(spec, now),
                                root=root)
        return Answered(False, done.text, again=True)
    # What he changed in the draft before it went, recorded for a later look (`rouh/draft_edits.py`).
    from . import draft_edits

    await asyncio.to_thread(draft_edits.keep, press_.user_id, press_.org_id, press_.action, open_, now,
                            card=str(number), chat=press_.chat)
    revised = await asyncio.to_thread(
        artifacts.revise, number, title=done.card.get("title"),
        description=done.card.get("description"), blocks=done.card.get("blocks") or [],
        root=root)
    return Answered(True, spec=revised, chat=press_.chat, others=list(done.others), note=(
        f"the person pressed \"{open_.get('send') or 'Send'}\" on card {number} rather "
        f"than asking out loud, and Rouh {action.what}: {done.text} Say in one short "
        "sentence that it has gone. Do not do it again."))


__all__ = ["ALLOWED", "DONE_WITH", "DRAFT", "KIND", "MAX_BODY", "NOT_SENT", "SAVE", "SEND",
           "SENT", "Action", "Answered", "Done", "Press", "Refused", "as_text", "block",
           "clean_html", "drop", "edits_of", "from_text", "not_sent", "one_line", "press",
           "register", "sealed", "sent_block", "strip", "waiting"]
