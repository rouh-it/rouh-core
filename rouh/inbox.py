"""The inbox on the screen, as a card the person reads their mail in and acts on.

Asked for on 25 September 2026: "a real inbox widget on the screen with working
mail actions: Archive, Reply, Reply all and Forward." Until then the inbox could
only be drawn as an `html` block, and an html block is drawn in a sandbox with
no way back to the server, so a button on one did nothing at all.

So this is a card kind of its own, the third beside `rouh/asking.py` and
`rouh/composing.py`, and it keeps their rules.

- **Only Rouh's own code can draw one.** The block carries a token signed with
  the server's own key, naming whose mailbox it is, which thread it was drawn
  in and what it lists. The model cannot make one: every block it writes has
  any `inbox` taken off (`strip`), and the one way to draw it is `show_inbox`.
- **Only its own person.** Everything the card asks is honoured for the account
  the token names and nobody else, whichever tab it comes from. What it acts on
  is then that person's own mailbox, with the same reach as Gmail's own page.
- **Live, never a snapshot.** The card holds no mail. It asks the server for the
  inbox when it is drawn and whenever Refresh is pressed, so an archived message
  is gone from it rather than frozen in it.
- **The conversation hears it, and only a send is answered.** Everything done
  in the mailbox is put in the thread as a note from Rouh's own software, so
  the assistant knows what was done and does not do it a second time. An
  archive or a mark is written down in silence, with no turn and nothing said,
  because the card already shows it (Petar, 25 September 2026); several quick
  presses make one note. A reply, a reply to all or a forward is told as a
  turn, the way the draft card's Send is, and Rouh says in a sentence what
  went (`runtime.InboxNotes`).

What is sent from it goes out exactly as `send_mail` sends: from the connected
account, which is Rouh's own mailbox, replying in the original thread for Reply
and Reply all, and signed with the person's own signature for replies and
forwards, set in Settings, which Rouh's sender puts under what was written and
over the quote (`rouh/signatures.py`, `google_api.with_signature`).

Opening a message on the card **marks it read in Gmail**, as opening it in
Gmail does, and as `read_mail` does when Rouh reads one: Petar, 26 September
2026, "if you read the contents of an email you immediately mark it as read".
Until then the card left it unread, and a thread he had read, answered and
finished with was still bold in Gmail. Mark unread is on the card for the one
he wants to come back to.

A reply, a reply to all or a forward sent from the card **archives the
conversation and marks it read**, as Gmail's own Send & Archive does, and a
reply takes any other draft of it Rouh wrote in the same chat out of Drafts
(`tools.ToolRegistry._after_sent`, which the draft card's Send uses too).
"""
from __future__ import annotations

import asyncio
import html as html_mod
import logging
import re
import secrets
import time
from dataclasses import dataclass, field
from datetime import timedelta
from email.utils import getaddresses, parseaddr
from html.parser import HTMLParser

from . import clock, composing, untrusted

log = logging.getLogger("rouh.inbox")

#: What the block is called, on the card and in `renderBlock`.
KIND = "inbox"

#: What the token is signed for, so a token signed for anything else in Rouh
#: can never be read as one of these.
SALT = "rouh.inbox"

#: How long a card may go on being used. A month: it is a view of the person's
#: own mailbox and does nothing they could not do in Gmail, so it is allowed to
#: live as long as the conversation it was drawn in is likely to be read.
MAX_AGE = 30 * 24 * 3600

#: The search every card starts from: received mail still in the inbox. Sent
#: mail never carries the INBOX label, so it is never listed.
INBOX = "in:inbox"

#: How many messages the card lists, unless told otherwise, and the most.
DEFAULT_LIMIT = 25
MOST = 50

def own() -> tuple[str, ...]:
    """Rouh's own mailbox on this installation, and its other names, lower case, the first the one it writes from.

    The addresses that are this mailbox's own and are never written to by
    Reply all, beside the connected account's address and whatever Gmail
    lists as its send-as aliases; never the owner's (`my_card.never_mine`);
    and what the system prompt tells the model its address is
    (the built-in rule "own-mail"). The installation's own setting (`ROUH_OWN_MAILBOXES`,
    SETUP.md), never an address written here: empty when this installation
    gave Rouh no mailbox of its own.
    """
    from .config import config

    out: list[str] = []
    for one in str(config.own_mailboxes or "").split(","):
        one = one.strip().lower()
        if one and "@" in one and one not in out:
            out.append(one)
    return tuple(out)


def own_words() -> str:
    """Rouh's own addresses in words, for a prompt: "rouh@example.com (also rou@example.com)", or ""."""
    mine = own()
    if not mine:
        return ""
    return mine[0] + (f" (also {', '.join(mine[1:])})" if mine[1:] else "")

#: What the card can write.
REPLY, REPLY_ALL, FORWARD = "reply", "replyall", "forward"
MODES = (REPLY, REPLY_ALL, FORWARD)

#: The lines at the top of the form, in the order the draft card has them.
FIELDS = (("to", "To"), ("cc", "Cc"), ("bcc", "Bcc"), ("subject", "Subject"))

#: The most of a message's own files that go with a forward, as bytes, so a
#: forward Gmail would refuse is refused before its files are fetched. Gmail's
#: 25 MB is of the message once encoded, where a file is a third bigger, and
#: the message as built is held to that again (`google_api.MAIL_LIMIT`).
FORWARD_BYTES = 18 * 1024 * 1024

#: What names a sender and a subject to the model, which are somebody else's
#: words and are boxed as such inside Rouh's own note.
SOURCE = "the sender and subject of an email, written by whoever sent it"

#: How long the aliases Gmail lists for a mailbox are kept before asking again.
ALIASES_FOR = 600.0

_DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct",
           "Nov", "Dec")


def _signer():
    from django.core import signing

    return signing


# ---------------------------------------------------------------------------
# The block
# ---------------------------------------------------------------------------


def block(who, chat: str, *, query: str = "", limit: int = DEFAULT_LIMIT,
          mailbox: int = 0, address: str = "") -> dict:
    """The block an inbox card is drawn around, for this person, in this thread.

    `query` narrows the inbox with Gmail's own search language and never
    widens it: the card lists the inbox and nothing else (`search_for`).

    `mailbox` is one of the person's own inboxes, connected read-only
    (`rouh/inboxes.py`), by its id, and `address` is what it is called; left
    out, the card is Rouh's own inbox. A read-only card lists and opens and
    does nothing else, and says so on its face.
    """
    query = composing.one_line(query)[:300]
    limit = _limit(limit)
    sealed = {"u": getattr(who, "user_id", ""), "o": getattr(who, "org_id", ""),
              "c": chat or "", "q": query, "l": limit, "n": secrets.token_hex(4)}
    if mailbox:
        sealed["m"] = int(mailbox)
    drawn = {
        "block": KIND,
        "query": query,
        "limit": limit,
        "token": _signer().dumps(sealed, salt=SALT, compress=True),
    }
    if mailbox:
        drawn["read_only"] = True
        drawn["address"] = composing.one_line(address)[:200]
    return drawn


def strip(blocks) -> list:
    """Blocks the model wrote, with any inbox taken off: only `show_inbox` draws one."""
    return [b for b in (blocks or [])
            if not (isinstance(b, dict) and str(b.get("block") or "").lower() == KIND)]


def _limit(value) -> int:
    try:
        return max(1, min(int(value or DEFAULT_LIMIT), MOST))
    except (TypeError, ValueError):
        return DEFAULT_LIMIT


def _read(token) -> dict | None:
    signing = _signer()
    try:
        return signing.loads(str(token or ""), salt=SALT, max_age=MAX_AGE)
    except signing.SignatureExpired:
        return {"expired": True}
    except signing.BadSignature:
        return None


def search_for(query: str = "") -> str:
    """The Gmail search a card lists: the inbox, narrowed by what was asked."""
    query = composing.one_line(query)
    return f"{INBOX} {query}".strip()


# ---------------------------------------------------------------------------
# What the card shows
# ---------------------------------------------------------------------------


def when(at, now=None) -> str:
    """When a message came, as the list says it, on the person's own clock.

    "Today 15:15", "Yesterday 17:52", "Sun 20 Sep 21:24", and the year as well
    for anything from another year. Worked out here rather than on the page,
    because the person is on their own clock (`clock.zone`) wherever the screen
    they are reading is.
    """
    moment = clock.moment(at) if at else None
    if moment is None:
        return ""
    today = (clock.moment(now) if now is not None else clock.now()).date()
    clock_ = moment.strftime("%H:%M")
    if moment.date() == today:
        return f"Today {clock_}"
    if moment.date() == today - timedelta(days=1):
        return f"Yesterday {clock_}"
    said = f"{_DAYS[moment.weekday()]} {moment.day} {_MONTHS[moment.month - 1]}"
    if moment.year != today.year:
        said += f" {moment.year}"
    return f"{said} {clock_}"


def dated(at, *, joined: str = ", ") -> str:
    """The whole date of a message, on the person's own clock: "Fri 25 Sep 2026, 15:15"."""
    moment = clock.moment(at) if at else None
    if moment is None:
        return ""
    return (f"{_DAYS[moment.weekday()]} {moment.day} {_MONTHS[moment.month - 1]} "
            f"{moment.year}{joined}{moment.strftime('%H:%M')}")


def sender(line: str) -> tuple[str, str]:
    """Who a From line names, as the name and the address, either possibly empty."""
    name, address = parseaddr(str(line or ""))
    return name.strip().strip('"').strip(), address.strip()


def row(found: dict, now=None) -> dict:
    """One line of the list: who, what about, the first words, when, and whether read."""
    name, address = sender(found.get("from"))
    at = float(found.get("at") or 0.0)
    return {
        "id": str(found.get("id") or ""),
        "thread": str(found.get("thread_id") or ""),
        "from": name or address or "Unknown sender",
        "address": address,
        "subject": composing.one_line(found.get("subject")) or "(no subject)",
        "snippet": composing.one_line(found.get("snippet"))[:240],
        "when": when(at, now),
        "at": at,
        "unread": bool(found.get("unread")),
    }


def silo_chips(user_id: str, org_id: str, rows: list[dict]) -> None:
    """Each row's silos, as the chips the card draws (`rouh/silos.py`): its email's label in Synapse Master
    when Synapse has it, else what the rules on its sender say. Nothing when neither says, and nothing at
    all when it cannot be read: a row without chips is only a row without chips."""
    if not user_id or not rows:
        return
    try:
        from . import silos
        from .synapse import db

        ids = [r["id"] for r in rows if r.get("id")]
        kept = {str(x["gid"]): list(x["silos"] or []) for x in db.rows(
            "SELECT i.meta->'gmail'->>'id' AS gid, i.silos FROM synapse.item i JOIN synapse.dataset d "
            "ON d.id = i.dataset_id WHERE d.master AND d.user_id = %s AND d.org_id = %s AND i.source = 'gmail' "
            "AND i.kind = 'mail' AND i.deleted_at IS NULL AND i.meta->'gmail'->>'id' = ANY(%s)",
            (user_id, org_id, ids))} if ids else {}
        for r in rows:
            got = kept.get(r.get("id") or "")
            if not got and r.get("address"):
                got = silos.expand(user_id, org_id, silos.of_address(user_id, org_id, r["address"])[0])
            if got:
                r["silos"] = silos.chips(user_id, org_id, got)
    except Exception:  # noqa: BLE001 - the list is drawn without them
        log.exception("the inbox's silos could not be read")


def faces(user_id: str, org_id: str, rows: list[dict]) -> None:
    """Each row's sender's face, when they are a contact with one (`people.Person.photo`): the picture on
    their iCloud card, else the LinkedIn photo kept for them. Nothing at all when it cannot be read."""
    if not user_id or not rows:
        return
    try:
        from .people import People

        found: dict[str, str] = {}
        for r in rows:
            address = str(r.get("address") or "").strip().lower()
            if not address:
                continue
            if address not in found:
                people = People().by_address(user_id, org_id, address)
                found[address] = next((p.photo for p in people if p.photo), "")
            if found[address]:
                r["photo"] = found[address]
    except Exception:  # noqa: BLE001 - the list is drawn with initials
        log.exception("the inbox's faces could not be read")


def counted(total: int, unread: int, *, query: str = "", shown: int = 0,
            more: bool = False) -> str:
    """The line at the top of the list: "4 in the inbox, 3 unread"."""
    if query:
        if not shown:
            return f"Nothing in the inbox matches {query}"
        many = f"the newest {shown}" if more else str(shown)
        return f"{many} in the inbox matching {query}, {_unread(unread, shown)}"
    if not total:
        return "Nothing in the inbox"
    return f"{total} in the inbox, {_unread(unread, total)}"


def _unread(unread: int, of: int) -> str:
    if not unread:
        return "none unread"
    return "all unread" if unread == of else f"{unread} unread"


def opened(found: dict, now=None) -> dict:
    """One whole message, as the card shows it when it is opened."""
    name, address = sender(found.get("from"))
    body = message_text(found)
    return {
        "id": str(found.get("id") or ""),
        "thread": str(found.get("thread_id") or ""),
        "from": str(found.get("from") or ""),
        "name": name or address or "Unknown sender",
        "to": str(found.get("to") or ""),
        "cc": str(found.get("cc") or ""),
        "subject": composing.one_line(found.get("subject")) or "(no subject)",
        "date": dated(found.get("at")) or str(found.get("date") or ""),
        "when": when(found.get("at"), now),
        "unread": bool(found.get("unread")),
        "in_inbox": "INBOX" in (found.get("labels") or []),
        "parts": parts(body),
        "attachments": [{"part": a.get("part"), "name": a.get("name"),
                         "size": int(a.get("size") or 0)}
                        for a in found.get("attachments") or []],
    }


def message_text(found: dict) -> str:
    """The words of a message, with what it quotes still marked as quoted.

    Plain text as the sender wrote it wherever there is some. A message sent
    as markup alone is read out of the markup here, rather than out of the
    flattened text `google_api` makes of it for the model, because that loses
    which lines were quoted and this is the one place that shows them.
    """
    if found.get("html"):
        return html_text(found["html"])
    return str(found.get("body") or "")


# --- quoted text -------------------------------------------------------------

#: `>` at the start of a line, as many as it is deep, with or without spaces.
_DEPTH = re.compile(r"^[ \t]{0,3}((?:>[ \t]?)+)")

#: The line a mail program writes above what it quotes: "On Wed, 23 Sep 2026
#: at 18:04, Sam <sam@...> wrote:". Gmail folds a long one onto two lines,
#: which is why the start and the end are looked for separately.
_SAID_START = re.compile(r"^\s*On\s.+", re.I)
_SAID_END = re.compile(r"\bwrote:\s*$", re.I)

#: Where a forwarded message or an Outlook reply's copy of the original begins.
_ORIGINAL = re.compile(
    r"^\s*(?:-{2,}\s*Forwarded message\s*-{2,}|Begin forwarded message:|"
    r"-{2,}\s*Original Message\s*-{2,})\s*$", re.I)
_OUTLOOK_FROM = re.compile(r"^\s*\*?From:\*?\s+\S", re.I)
_OUTLOOK_NEXT = re.compile(r"^\s*\*?(?:Sent|Date):\*?\s+\S", re.I)
_RULE = re.compile(r"^\s*_{8,}\s*$")


def parts(text: str) -> list[dict]:
    """A message's words in pieces, each with how deeply it is quoted.

    `q` is 0 for what the sender wrote now and one more for every level of
    quoting; `head` marks the "On ... wrote:" line or the forwarded message's
    header, which belongs with the quote it introduces. Three ways of quoting
    are read, because all three arrive in a real inbox: `>` at the start of
    the line, which is Gmail's plain text and everybody's old habit; a
    forwarded message, from its "Forwarded message" line to the end; and an
    Outlook reply, from the "From: ... Sent:" header it writes above the
    original to the end.
    """
    lines = str(text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    depth: list[int] = []
    words: list[str] = []
    head: list[bool] = [False] * len(lines)
    for line in lines:
        found = _DEPTH.match(line)
        if found:
            depth.append(found.group(1).count(">"))
            words.append(line[found.end():])
        else:
            depth.append(0)
            words.append(line)

    # A forwarded message, or an original copied in under a reply, is quoted
    # from its header to the end.
    for i, line in enumerate(words):
        starts = bool(_ORIGINAL.match(line))
        if not starts and _OUTLOOK_FROM.match(line):
            starts = any(_OUTLOOK_NEXT.match(words[j])
                         for j in range(i + 1, min(i + 4, len(words))))
        if starts:
            # Outlook rules a line of underscores above its header, which is
            # part of the quote and not the last line of the reply.
            if i > 0 and _RULE.match(words[i - 1]) and depth[i - 1] == depth[i]:
                i -= 1
            level = depth[i]
            for j in range(i, len(words)):
                if depth[j] >= level:
                    depth[j] += 1
            # The header is its lines up to the first blank one.
            j = i
            while j < len(words) and words[j].strip():
                head[j] = True
                j += 1
            break

    # "On ... wrote:" goes with the quote under it.
    for i, line in enumerate(words):
        if head[i] or not _SAID_END.search(line):
            continue
        first = i
        if not _SAID_START.match(line) and i > 0 and _SAID_START.match(words[i - 1]) \
                and depth[i - 1] == depth[i]:
            first = i - 1
        below = next((depth[j] for j in range(i + 1, len(words)) if words[j].strip()), 0)
        if below > depth[i]:
            for j in range(first, i + 1):
                depth[j] = below
                head[j] = True

    out: list[dict] = []
    for level, line, is_head in zip(depth, words, head):
        if out and out[-1]["q"] == level and out[-1]["head"] == is_head:
            out[-1]["lines"].append(line)
        else:
            out.append({"q": level, "head": is_head, "lines": [line]})
    said = []
    for piece in out:
        text_ = "\n".join(piece["lines"]).strip("\n")
        if text_.strip():
            said.append({"q": piece["q"], "head": piece["head"], "text": text_.rstrip()})
    return said


class _Text(HTMLParser):
    """A message sent as markup, as the text a reader sees, with its quotes kept.

    Every level of `<blockquote>` becomes a level of `> ` in front of the lines
    inside it, so what is quoted comes out exactly as it would have in a plain
    text email and is read by `parts` the same way.
    """

    BLOCKS = {"p", "div", "br", "li", "tr", "table", "ul", "ol", "h1", "h2", "h3", "h4",
              "h5", "h6", "pre", "hr", "section", "article", "header", "footer"}
    DROPPED = {"script", "style", "head", "title", "template"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.lines: list[tuple[int, str]] = []
        self.line = ""
        self.depth = 0
        self.dropping = 0

    def _end_line(self) -> None:
        self.lines.append((self.depth, " ".join(self.line.split())))
        self.line = ""

    def handle_starttag(self, tag, attrs):
        if tag in self.DROPPED:
            self.dropping += 1
        elif tag == "blockquote":
            if self.line.strip():
                self._end_line()
            self.depth += 1
        elif tag in self.BLOCKS:
            if self.line.strip() or tag in ("br", "p"):
                self._end_line()
            if tag == "li":
                self.line = "- "

    def handle_endtag(self, tag):
        if tag in self.DROPPED:
            self.dropping = max(0, self.dropping - 1)
        elif tag == "blockquote":
            if self.line.strip():
                self._end_line()
            self.depth = max(0, self.depth - 1)
        elif tag in self.BLOCKS and self.line.strip():
            self._end_line()

    def handle_data(self, data):
        if not self.dropping:
            self.line += data

    def text(self) -> str:
        if self.line.strip():
            self._end_line()
        lines = self.lines
        out: list[str] = []
        for n, (depth, said) in enumerate(lines):
            if not said:
                # One blank line between paragraphs, and none at the edge of a
                # quote, where the rule down its side already says where it is.
                before = lines[n - 1] if n else None
                after = lines[n + 1] if n + 1 < len(lines) else None
                if before is None or after is None or not before[1] or \
                        before[0] != depth or after[0] != depth:
                    continue
            out.append(("> " * depth + said).rstrip() if said else ">" * depth)
        return "\n".join(out).strip()


def html_text(markup: str) -> str:
    """A message's markup as text, quoted lines kept as `> ` lines."""
    parser = _Text()
    try:
        parser.feed(str(markup or ""))
        parser.close()
    except Exception:  # noqa: BLE001 - a malformed message is still a message
        log.warning("a message's markup could not be read; shown as it came")
        return html_mod.unescape(re.sub(r"<[^>]+>", " ", str(markup or "")))
    return parser.text()


# ---------------------------------------------------------------------------
# Writing back: who it goes to, what it is called, what it says
# ---------------------------------------------------------------------------


def addresses(line: str) -> list[tuple[str, str]]:
    """Every address on a To, Cc or From line, with the name in front of it."""
    out = []
    for name, address in getaddresses([str(line or "")]):
        address = address.strip()
        if "@" in address:
            out.append((name.strip().strip('"').strip(), address))
    return out


def written(name: str, address: str) -> str:
    """One address as a person writes it on a To line: `Sam Rivera <sam@...>`."""
    if not name or name.lower() == address.lower():
        return address
    if re.search(r'[,;:@<>"()\[\]\\]', name):
        name = '"' + name.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return f"{name} <{address}>"


def _unplussed(address: str) -> str:
    """An address without its plus part: rouh+stripe@example.com is rouh@example.com, which
    Gmail delivers it to (the nightly feature run's sign-up addresses, `nightly_feature.py`)."""
    local, at, domain = str(address or "").lower().partition("@")
    return f"{local.split('+', 1)[0]}{at}{domain}"


def recipients(found: dict, mode: str, own) -> tuple[str, str]:
    """Who a reply goes to and who is copied, as the To and Cc lines.

    Reply answers whoever the message asks answers to go to - its Reply-To, or
    else its sender. Reply all adds everybody else it was sent to: the rest of
    its To beside the sender, and its Cc copied in, as Gmail does it. Nobody is
    written to twice, and never the mailbox's own addresses (`own`). A message
    the mailbox sent itself is answered to whoever it went to, because
    replying to it would be writing to ourselves. A forward goes to nobody
    until the person says who.
    """
    if mode == FORWARD:
        return "", ""
    mine = {str(a).lower() for a in own}
    senders = addresses(found.get("from"))
    ours = bool(senders) and all(_unplussed(a) in mine for _, a in senders)
    to_list = addresses(found.get("to")) if ours else \
        (addresses(found.get("reply_to")) or senders)
    cc_list: list[tuple[str, str]] = []
    if mode == REPLY_ALL:
        to_list = to_list + addresses(found.get("to"))
        cc_list = addresses(found.get("cc"))
    seen: set[str] = set()

    def keep(pairs):
        out = []
        for name, address in pairs:
            key = address.lower()
            if key in mine or _unplussed(key) in mine or key in seen:
                continue
            seen.add(key)
            out.append(written(name, address))
        return ", ".join(out)

    to = keep(to_list)
    return to, keep(cc_list)


def reply_all_with(found: dict, own, to: str = "", cc: str = "") -> tuple[str, str]:
    """A reply to `found` as Reply all, with whatever else was named kept.

    Petar, 1 October 2026: Rouh's answer to an email of his goes to everybody
    on it, not to him alone, so the others he wrote to stay in the loop. The
    To and Cc are `recipients` in REPLY_ALL: its sender (or Reply-To) and the
    rest of its To, its Cc copied in, never the mailbox's own addresses
    (`own`), nobody twice, and nobody who was not on it. Addresses the reply
    was told to go to besides (`to`, `cc`) are the instruction's own and are
    kept, after those, once each and never one of `own`.
    """
    all_to, all_cc = recipients(found, REPLY_ALL, own)
    mine = {str(a).lower() for a in own}
    seen: set[str] = set()

    def keep(*lines: str) -> str:
        out = []
        for line in lines:
            for name, address in addresses(line):
                key = address.lower()
                if key in mine or key in seen:
                    continue
                seen.add(key)
                out.append(written(name, address))
        return ", ".join(out)

    to_line = keep(all_to, to)
    return to_line, keep(all_cc, cc)


_RE = re.compile(r"^\s*re\s*:", re.I)
_FWD = re.compile(r"^\s*(?:fwd?|fw)\s*:", re.I)


def subject_for(subject: str, mode: str) -> str:
    """The subject of a reply or a forward: Re: or Fwd: in front, once."""
    subject = composing.one_line(subject)
    if subject == "(no subject)":
        subject = ""
    if mode == FORWARD:
        return subject if _FWD.match(subject) else f"Fwd: {subject}".strip()
    return subject if _RE.match(subject) else f"Re: {subject}".strip()


def signature_markup() -> str:
    """Where the person writes, over the quote.

    No name is written here: every send is signed on its way out with the
    signature the person set in Settings for replies and forwards, under
    what was written and over any quote, and a name on the form as well
    would sign it twice.
    """
    return "<p><br></p>"


def written_under(found: dict, mode: str) -> str:
    """The body a reply or a forward starts with, as markup for the form.

    A line to write on; the signature is added as it is sent. For a reply the original follows,
    quoted, under "On ... wrote:", which is how Gmail writes one. A forward's
    form holds only the note: the original is not the person's to rewrite,
    and goes out as it came under it (`forwarding.py`, `form`).
    """
    if mode == FORWARD:
        return signature_markup()
    original = quoted_markup(message_text(found))
    when_ = dated(found.get("at")) or str(found.get("date") or "")
    said = (f"On {dated(found.get('at'), joined=' at ') or when_}, "
            f"{found.get('from') or 'they'} wrote:")
    return (signature_markup() + f"<p>{html_mod.escape(said)}</p>"
            f"<blockquote>{original}</blockquote>")


def quoted_markup(text: str) -> str:
    """A message's words as markup, with what it quotes as quotes inside it.

    So a reply's copy of a message that was itself a reply has one quote
    inside the other, rather than lines with `>` typed in front of them, and
    the text half of the email comes out as `> > ` where it should.
    """
    out: list[str] = []
    depth = 0
    for piece in parts(text):
        while depth < piece["q"]:
            out.append("<blockquote>")
            depth += 1
        while depth > piece["q"]:
            out.append("</blockquote>")
            depth -= 1
        out.append(composing.from_text(piece["text"]))
    out.append("</blockquote>" * depth)
    return "".join(out)


def form(found: dict, mode: str, own, original=None) -> dict:
    """The compose form a Reply, Reply all or Forward opens, filled in.

    A forward's form is the note alone, with the original shown under it as
    it will go - its header, and its own HTML or text - and not to be edited
    (`original`, a `forwarding.Original`). Its files are the original's own,
    each of which the person can take off; pictures drawn inside it always go.
    """
    to, cc = recipients(found, mode, own)
    values = {"to": to, "cc": cc, "bcc": "", "subject": subject_for(found.get("subject"), mode)}
    if mode == FORWARD and original is not None:
        from . import forwarding

        return {
            "mode": mode,
            "id": str(found.get("id") or ""),
            "fields": [{"name": name, "label": label, "value": values[name],
                        "kind": "line" if name == "subject" else "addresses"}
                       for name, label in FIELDS],
            "body": written_under(found, mode),
            "attachments": [{"part": a["part"], "name": a["name"], "size": a["size"]}
                            for a in original.files],
            "forwarded": {"rule": forwarding.RULE,
                          "head": [[n, v] for n, v in forwarding.header_lines(original)],
                          "html": original.html, "text": original.text},
            "send": "Send",
        }
    return {
        "mode": mode,
        "id": str(found.get("id") or ""),
        "fields": [{"name": name, "label": label, "value": values[name],
                    "kind": "line" if name == "subject" else "addresses"}
                   for name, label in FIELDS],
        "body": written_under(found, mode),
        # A forward carries the message's own files, as Gmail's does, each of
        # which the person can take off before it goes.
        "attachments": ([{"part": a.get("part"), "name": a.get("name"),
                          "size": int(a.get("size") or 0)}
                         for a in found.get("attachments") or []]
                        if mode == FORWARD else []),
        "send": "Send",
    }


def about(found: dict) -> str:
    """A message named for the model: its sender and subject, boxed, and its id."""
    name, address = sender(found.get("from"))
    said = untrusted.wrap(
        f"from {name or address or 'an unknown sender'}, subject "
        f"\"{composing.one_line(found.get('subject')) or '(no subject)'}\"", SOURCE)
    return f"the message {found.get('id') or ''} ({said})"


# ---------------------------------------------------------------------------
# Doing it, in the person's mailbox
# ---------------------------------------------------------------------------


@dataclass
class Answer:
    """What one ask of the card comes to.

    `said` goes back to the tab that asked. `note` is a line for the thread the
    card is in, when something was done. `turn` says Rouh answers it: the
    thread is told straight away, as a turn, and says what was done. Without
    it the line is written into the thread in silence with whatever else is
    pressed in the next few seconds, which is everything but a send: the card
    already shows an archive or a mark, and the person does not want it said
    back to them.
    `changed` is what every tab of this person should know about a message,
    so the same inbox open on a phone loses an archived message as well.
    """

    ok: bool
    said: dict = field(default_factory=dict)
    why: str = ""
    note: str = ""
    turn: bool = False
    chat: str = ""
    changed: dict | None = None
    #: Other cards in the thread that changed on the way, as they now read: a
    #: draft of the same reply turned over to Not sent once this one went.
    cards: list = field(default_factory=list)


class Mailroom:
    """The card's hands in the mailbox: the same Gmail calls the mail tools make.

    `google` is the `GoogleDesk` the tools use, which opens the mailbox of the
    person on this socket. `sent` hears about every message sent from here, as
    the tools keep one list of those (`tools._sent_mail`). `trouble` turns a
    failure into the sentence the tools would say for it. `after_sent` is what
    happens once a message has gone, the same for the card as for the tools
    (`tools.ToolRegistry._after_sent`): the conversation archived and read, and the
    other drafts of it out of Drafts.
    """

    def __init__(self, google, *, sent=None, trouble=None, after_sent=None) -> None:
        self.google = google
        self._sent = sent
        self._after_sent = after_sent
        self._trouble = trouble or (lambda exc: f"Google could not answer that: {exc}")
        self._aliases: dict[str, tuple[float, set[str]]] = {}

    def _gmail(self):
        return self.google.services().gmail

    async def _theirs(self, sealed: dict):
        """The person's own inbox a read-only card names, opened to read, or None.

        Asked for by its id and its owner, the token's person, so an inbox
        disconnected since the card was drawn is not read.
        """
        import asyncio

        from . import inboxes
        from .mailboxes import NotConnected
        from .tenancy import Identity

        who = Identity(user_id=str(sealed.get("u") or ""), org_id=str(sealed.get("o") or ""))
        held = [one for one in await asyncio.to_thread(inboxes.theirs, who)
                if one.id == sealed.get("m")]
        if not held:
            raise NotConnected("That inbox is not connected any more. Ask Rouh to show it "
                               "again once it is connected in Settings.")
        return (await asyncio.to_thread(inboxes.open_one, who, held[0])).gmail

    async def own(self) -> set[str]:
        """Every address that is this mailbox's own: Reply all never writes to one."""
        mine = set(own())
        address = self.google.address()
        if address:
            mine.add(address.lower())
        who = self.google.person()
        key = f"{getattr(who, 'org_id', '')}:{getattr(who, 'user_id', '')}"
        held = self._aliases.get(key)
        if held is None or time.time() - held[0] > ALIASES_FOR:
            try:
                aliases = set(await self._gmail().send_as())
            except Exception as exc:  # noqa: BLE001 - the known addresses still stand
                log.info("gmail would not list send-as addresses: %s", exc)
                aliases = set()
            held = (time.time(), aliases)
            self._aliases[key] = held
        return mine | held[1]

    async def listing(self, sealed: dict) -> dict:
        query = str(sealed.get("q") or "")
        limit = _limit(sealed.get("l"))
        gmail = await self._theirs(sealed) if sealed.get("m") else self._gmail()
        found = await gmail.recent(limit=limit, query=search_for(query), most=MOST)
        now = clock.now()
        rows = sorted((row(one, now) for one in found), key=lambda r: r["at"], reverse=True)
        unread = sum(1 for r in rows if r["unread"])
        total = len(rows)
        if not query:
            # The inbox as Gmail counts it, which is the number to check
            # against Gmail; what was listed is the fallback.
            try:
                counts = await gmail.inbox_counts()
                total, unread = counts["total"], counts["unread"]
            except Exception as exc:  # noqa: BLE001
                log.info("gmail would not count the inbox: %s", exc)
        more = len(rows) >= limit
        # Each message's silos (`rouh/silos.py`), as small chips on its row.
        await asyncio.to_thread(silo_chips, str(sealed.get("u") or ""), str(sealed.get("o") or ""), rows)
        await asyncio.to_thread(faces, str(sealed.get("u") or ""), str(sealed.get("o") or ""), rows)
        return {"rows": rows, "total": total, "unread": unread, "limit": limit,
                "more": more or total > len(rows), "query": query,
                "count": counted(total, unread, query=query, shown=len(rows),
                                 more=more)}

    async def open(self, message_id: str, sealed: dict | None = None) -> Answer:
        """One message, read, and marked read in Gmail if it was not yet.

        One of the person's own inboxes is read-only, so a message opened
        there stays as it was in Gmail.
        """
        if sealed and sealed.get("m"):
            found = await (await self._theirs(sealed)).message(message_id)
            return Answer(True, said={"message": await self._unsub(opened(found), found, sealed)})
        gmail = self._gmail()
        found = await gmail.message(message_id)
        if not found.get("unread"):
            return Answer(True, said={"message": await self._unsub(opened(found), found, sealed)})
        try:
            await gmail.modify(message_id, remove=["UNREAD"])
        except Exception as exc:  # noqa: BLE001 - it is open all the same
            log.info("gmail would not mark %s read: %s", message_id, exc)
            return Answer(True, said={"message": opened(found)})
        self.google.wrote("modify_mail", message_id,
                          f"Message {message_id}: marked it read, opened on the inbox card.")
        found = dict(found, unread=False,
                     labels=[x for x in found.get("labels") or [] if x != "UNREAD"])
        return Answer(True, said={"message": await self._unsub(opened(found), found, sealed),
                                  "marked_read": True},
                      changed={"id": message_id, "unread": False})

    def _owner(self, sealed: dict | None):
        from .tenancy import Identity

        if sealed and sealed.get("u"):
            return Identity(user_id=str(sealed.get("u") or ""), org_id=str(sealed.get("o") or ""))
        return self.google.person()

    async def _unsub(self, shown: dict, found: dict, sealed: dict | None) -> dict:
        """Unsubscribe in the inbox card (night 34, `rouh/inbox_unsubscribe.py`): what the
        message offers, when it is mail from a list and the switch is on."""
        from . import inbox_unsubscribe

        try:
            got = await asyncio.to_thread(inbox_unsubscribe.shown, self._owner(sealed), found)
        except Exception as exc:  # noqa: BLE001 - the message opens all the same
            log.info("unsubscribe could not be offered: %s", exc)
            got = None
        if got:
            shown = dict(shown, unsubscribe=got)
        # Remind me about this email (night 34, `rouh/inbox_remind.py`): the times it offers.
        from . import inbox_remind

        try:
            remind = await asyncio.to_thread(inbox_remind.shown, self._owner(sealed))
        except Exception as exc:  # noqa: BLE001 - the message opens all the same
            log.info("remind me could not be offered: %s", exc)
            remind = None
        if remind:
            shown = dict(shown, remind=remind)
        # You meet them soon (night 36, `rouh/meeting_soon.py`): a meeting soon with somebody on it.
        from . import inboxes, meeting_soon

        try:
            who = self._owner(sealed)
            own = [self.google.address() or ""] + [one.email for one in
                                                   await asyncio.to_thread(inboxes.theirs, who)]
            soon = await meeting_soon.shown(who, self.google.services().calendar, found, own=own)
        except Exception as exc:  # noqa: BLE001 - the message opens all the same
            log.info("the meetings soon could not be read: %s", exc)
            soon = None
        if soon:
            shown = dict(shown, meeting_soon=soon)
        # If it does not come (night 36, `rouh/promise_watch.py`): an email promising something by a day.
        from . import promise_watch

        try:
            watch = await asyncio.to_thread(promise_watch.shown, self._owner(sealed), found)
        except Exception as exc:  # noqa: BLE001 - the message opens all the same
            log.info("if it does not come could not be offered: %s", exc)
            watch = None
        if watch:
            shown = dict(shown, watch=watch)
        # Also waiting on you (night 36, `rouh/waiting_too.py`): the sender's other emails unanswered.
        from . import waiting_too

        try:
            who = self._owner(sealed)
            own = [self.google.address() or ""] + [one.email for one in
                                                   await asyncio.to_thread(inboxes.theirs, who)]
            too = await waiting_too.shown(who, found, own=own)
        except Exception as exc:  # noqa: BLE001 - the message opens all the same
            log.info("the sender's other emails could not be read: %s", exc)
            too = None
        if too:
            shown = dict(shown, waiting_too=too)
        # How you know them (night 38, `rouh/know_them.py`): a sender back after months.
        from . import know_them

        try:
            who = self._owner(sealed)
            own = await self._own_addresses(who, sealed)
            know = await know_them.shown(who, found, own=own)
        except Exception as exc:  # noqa: BLE001 - the message opens all the same
            log.info("how you know them could not be read: %s", exc)
            know = None
        if know:
            shown = dict(shown, know_them=know)
        # Save them as a contact (night 39, `rouh/save_sender.py`): a sender not in the contacts.
        from . import save_sender

        try:
            who = self._owner(sealed)
            own = await self._own_addresses(who, sealed)
            newcomer = await asyncio.to_thread(save_sender.shown, who, found, own)
        except Exception as exc:  # noqa: BLE001 - the message opens all the same
            log.info("save them as a contact could not be offered: %s", exc)
            newcomer = None
        if newcomer:
            shown = dict(shown, save_sender=newcomer)
        # A contact card in an email (night 40, `rouh/card_in_mail.py`): a .vcf on the email.
        from . import card_in_mail

        if card_in_mail.part_of(found) is not None:
            try:
                who = self._owner(sealed)
                gmail = await self._theirs(sealed) if sealed and sealed.get("m") else self._gmail()
                card = await card_in_mail.shown(who, gmail, found)
            except Exception as exc:  # noqa: BLE001 - the message opens all the same
                log.info("the contact card on the email could not be read: %s", exc)
                card = None
            if card:
                shown = dict(shown, card_in_mail=card)
        # If I have not answered it, remind me (night 37, `rouh/answer_watch.py`): an email asking him something.
        from . import answer_watch

        try:
            who = self._owner(sealed)
            own = await self._own_addresses(who, sealed)
            asks = await asyncio.to_thread(answer_watch.shown, who, found, own)
        except Exception as exc:  # noqa: BLE001 - the message opens all the same
            log.info("if I have not answered it could not be offered: %s", exc)
            asks = None
        if asks:
            shown = dict(shown, answer_watch=asks)
        return shown

    async def waiting_too(self, sealed: dict | None) -> Answer:
        """Open pressed on an email's Also waiting on you line: counted, nothing changed."""
        from . import waiting_too

        who = self._owner(sealed)
        if not await asyncio.to_thread(waiting_too.on, who):
            return Answer(False, why="Also waiting on you is switched off.")
        await asyncio.to_thread(waiting_too.opened, who)
        return Answer(True, said={"counted": True})

    async def know_them(self, which: str, sealed: dict | None) -> Answer:
        """Open the last or the first, pressed on an email's How you know them line: counted, nothing changed."""
        from . import know_them

        who = self._owner(sealed)
        if not await asyncio.to_thread(know_them.on, who):
            return Answer(False, why="How you know them is switched off.")
        await asyncio.to_thread(know_them.opened, who, which)
        return Answer(True, said={"counted": True})

    async def save_sender(self, message_id: str, sealed: dict | None) -> Answer:
        """Save to contacts, pressed on an email's line: the sender written to iCloud as a new contact,
        read from the message again here, never from the page."""
        from . import runtime, save_sender

        who = self._owner(sealed)
        if not await asyncio.to_thread(save_sender.on, who):
            return Answer(False, why="Save them as a contact is switched off.")
        theirs = bool(sealed and sealed.get("m"))
        gmail = await self._theirs(sealed) if theirs else self._gmail()
        found = await gmail.message(message_id)
        own = await self._own_addresses(who, sealed)
        done, said = await save_sender.save(who, found, getattr(runtime, "contacts", None), own)
        if not done:
            return Answer(False, why=said)
        return Answer(True, said={"said": said}, note=f"saved {about(found)} as a contact, pressed on the inbox card")

    async def card_in_mail(self, message_id: str, sealed: dict | None) -> Answer:
        """Save to contacts or Add to their contact, pressed on an email's contact card line: the card read
        from the message again here, never from the page, and written to iCloud."""
        from . import card_in_mail, runtime

        who = self._owner(sealed)
        if not await asyncio.to_thread(card_in_mail.on, who):
            return Answer(False, why="A contact card in an email is switched off.")
        gmail = await self._theirs(sealed) if sealed and sealed.get("m") else self._gmail()
        found = await gmail.message(message_id)
        done, said = await card_in_mail.save(who, gmail, found, getattr(runtime, "contacts", None))
        if not done:
            return Answer(False, why=said)
        return Answer(True, said={"said": said}, note=f"saved the contact card on {about(found)}, pressed on the inbox card")

    async def _own_addresses(self, who, sealed: dict | None) -> list[str]:
        """The person's own addresses: Rouh's connection's and each read-only inbox's."""
        from . import inboxes

        return [self.google.address() or ""] + [one.email for one in await asyncio.to_thread(inboxes.theirs, who)]

    async def meeting_soon(self, sealed: dict | None) -> Answer:
        """Open the meeting pressed on an email's You meet them soon line: counted, nothing changed."""
        from . import meeting_soon

        who = self._owner(sealed)
        if not await asyncio.to_thread(meeting_soon.on, who):
            return Answer(False, why="You meet them soon is switched off.")
        await asyncio.to_thread(meeting_soon.opened, who)
        return Answer(True, said={"counted": True})

    async def watch(self, message_id: str, sealed: dict | None) -> Answer:
        """If it does not come: a look on Clockwork the morning after the promised day."""
        from . import inboxes, promise_watch

        who = self._owner(sealed)
        if not await asyncio.to_thread(promise_watch.on, who):
            return Answer(False, why="If it does not come is switched off.")
        theirs = bool(sealed and sealed.get("m"))
        gmail = await self._theirs(sealed) if theirs else self._gmail()
        found = await gmail.message(message_id)
        found = dict(found, id=found.get("id") or message_id)
        if theirs:
            held = [one for one in await asyncio.to_thread(inboxes.theirs, who)
                    if one.id == sealed.get("m")]
            inbox = held[0].email if held else ""
        else:
            inbox = self.google.address() or ""
        try:
            said = await asyncio.to_thread(promise_watch.make, who, found=found,
                                           chat=str((sealed or {}).get("c") or ""), inbox=inbox,
                                           read_only=theirs)
        except ValueError as exc:
            return Answer(False, why=str(exc))
        return Answer(True, said=said, note=f"asked to be told if what {about(found)} promised has not come, "
                                            "pressed on the inbox card")

    async def answer_watch(self, message_id: str, sealed: dict | None) -> Answer:
        """If I have not answered it, remind me: a look on Clockwork the next working morning."""
        from . import answer_watch, inboxes

        who = self._owner(sealed)
        if not await asyncio.to_thread(answer_watch.on, who):
            return Answer(False, why="If I have not answered it, remind me, is switched off.")
        theirs = bool(sealed and sealed.get("m"))
        gmail = await self._theirs(sealed) if theirs else self._gmail()
        found = await gmail.message(message_id)
        found = dict(found, id=found.get("id") or message_id)
        if theirs:
            held = [one for one in await asyncio.to_thread(inboxes.theirs, who)
                    if one.id == sealed.get("m")]
            inbox = held[0].email if held else ""
        else:
            inbox = self.google.address() or ""
        try:
            said = await asyncio.to_thread(answer_watch.make, who, found=found,
                                           own=await self._own_addresses(who, sealed),
                                           chat=str((sealed or {}).get("c") or ""), inbox=inbox,
                                           read_only=theirs)
        except ValueError as exc:
            return Answer(False, why=str(exc))
        return Answer(True, said=said, note=f"asked to be reminded if {about(found)} is still unanswered "
                                            "tomorrow, pressed on the inbox card")

    async def remind(self, message_id: str, when: str, sealed: dict | None) -> Answer:
        """Remind me about this email: a reminder on Clockwork, nothing in the mailbox."""
        from . import inbox_remind, inboxes

        who = self._owner(sealed)
        if not await asyncio.to_thread(inbox_remind.on, who):
            return Answer(False, why="Remind me about this email is switched off.")
        if when not in inbox_remind.WHENS:
            return Answer(False, why="This evening, Tomorrow morning or Monday morning: say which.")
        theirs = bool(sealed and sealed.get("m"))
        gmail = await self._theirs(sealed) if theirs else self._gmail()
        found = await gmail.headers(message_id)
        found = dict(found, id=found.get("id") or message_id)
        if theirs:
            held = [one for one in await asyncio.to_thread(inboxes.theirs, who)
                    if one.id == sealed.get("m")]
            inbox = held[0].email if held else ""
        else:
            inbox = self.google.address() or ""
        try:
            said = await asyncio.to_thread(inbox_remind.make, who, found=found, when=when,
                                           chat=str((sealed or {}).get("c") or ""), inbox=inbox,
                                           read_only=theirs)
        except ValueError as exc:
            return Answer(False, why=str(exc))
        return Answer(True, said=said, note=f"set a reminder {inbox_remind.WORDS[when].lower()} "
                                            f"about {about(found)}, pressed on the inbox card")

    async def unsubscribe(self, message_id: str, sealed: dict | None) -> Answer:
        """Leave the list the message came from: a POST to the sender, nothing in the mailbox."""
        from . import inbox_unsubscribe

        gmail = await self._theirs(sealed) if sealed and sealed.get("m") else self._gmail()
        found = await gmail.message(message_id)
        done = await inbox_unsubscribe.press(self._owner(sealed), found)
        if not done.get("ok"):
            return Answer(False, why=str(done.get("why") or "It could not be done."))
        said = {"id": message_id, "unsubscribed": True, "said": done.get("said") or ""}
        if done.get("open"):
            said["open"] = done["open"]
        return Answer(True, said=said)

    async def archive(self, message_id: str) -> Answer:
        """Out of the inbox, and nothing else: the same change `modify_mail` makes."""
        gmail = self._gmail()
        found = await gmail.headers(message_id)
        await gmail.modify(message_id, remove=["INBOX"])
        self.google.wrote("modify_mail", message_id,
                          f"Message {message_id}: archived it out of the inbox, "
                          "pressed on the inbox card.")
        return Answer(True, said={"id": message_id, "archived": True},
                      note=f"archived {about(found)} out of the inbox",
                      changed={"id": message_id, "archived": True})

    async def unarchive(self, message_id: str) -> Answer:
        """Back into the inbox: the Undo beside "Archived" on the list."""
        gmail = self._gmail()
        found = await gmail.headers(message_id)
        await gmail.modify(message_id, add=["INBOX"])
        self.google.wrote("modify_mail", message_id,
                          f"Message {message_id}: put it back in the inbox, pressed on "
                          "the inbox card.")
        return Answer(True, said={"id": message_id, "unarchived": True},
                      note=f"put {about(found)} back in the inbox",
                      changed={"id": message_id, "unarchived": True})

    async def mark(self, message_id: str, *, read: bool) -> Answer:
        gmail = self._gmail()
        found = await gmail.headers(message_id)
        if read:
            await gmail.modify(message_id, remove=["UNREAD"])
        else:
            await gmail.modify(message_id, add=["UNREAD"])
        did = "marked it read" if read else "marked it unread"
        self.google.wrote("modify_mail", message_id,
                          f"Message {message_id}: {did}, pressed on the inbox card.")
        return Answer(True, said={"id": message_id, "unread": not read},
                      note=f"marked {about(found)} {'read' if read else 'unread'}",
                      changed={"id": message_id, "unread": not read})

    async def compose(self, message_id: str, mode: str) -> dict:
        gmail = self._gmail()
        found = await gmail.message(message_id)
        original = await gmail.forwardable(message_id) if mode == FORWARD else None
        shown = form(found, mode, await self.own(), original)
        if original is not None and original.inline and original.html:
            # Its own pictures, where the card can draw them.
            shown["forwarded"]["html"] = await gmail.drawn_inside(message_id, original)
        return {"form": shown}

    async def send(self, message_id: str, mode: str, raw_edits, keep,
                   chat: str = "") -> Answer:
        """A reply, a reply to all or a forward, sent as `send_mail` sends one.

        What it says and who it goes to are what the person has on the form,
        cleaned the way the draft card cleans them (`composing.edits_of`).
        Which message it answers is the message the form was opened on, and a
        reply goes into that message's own thread. Once it has gone, that
        message's conversation is archived and read, and a reply takes any
        other draft of itself Rouh wrote in `chat` out of Drafts; a forward is
        not a draft of the reply, so it leaves those alone.
        """
        edits = composing.edits_of(raw_edits, fields=[name for name, _ in FIELDS])
        said = edits["fields"]
        html = edits["body"]
        text = composing.as_text(html)
        to = (said.get("to") or "").strip()
        if not text.strip() and mode != FORWARD:
            return Answer(False, why="There is nothing in the message to send.")
        if not to:
            return Answer(False, why="Say who it goes to before sending it.")
        gmail = self._gmail()
        found = await gmail.headers(message_id)
        files: list[str] = []
        replying = message_id if mode in (REPLY, REPLY_ALL) else ""
        if mode == FORWARD:
            # The note on the form, then the original as it came: its markup,
            # its pictures and the files left on the form (`forwarding.py`).
            try:
                wrote = await gmail.forward(
                    message_id, to, note=text if text.strip() else "",
                    note_html=html if text.strip() else "",
                    subject=said.get("subject") or "", cc=said.get("cc") or "",
                    bcc=said.get("bcc") or "", keep=[str(p) for p in (keep or [])][:20],
                    most=FORWARD_BYTES)
            except ValueError as exc:  # google_api.CannotDoThat: too big to go
                raise composing.Refused(str(exc)) from None
            files = wrote.get("files") or []
        else:
            wrote = await gmail.send(to, said.get("subject") or "", text,
                                     cc=said.get("cc") or "", bcc=said.get("bcc") or "",
                                     reply_to_message_id=replying, html=html)
        if wrote.get("id") and self._sent is not None:
            self._sent(str(wrote["id"]), str(wrote.get("to") or ""))
        what = {REPLY: "replied to", REPLY_ALL: "replied to everyone on",
                FORWARD: "forwarded"}[mode]
        trail = (f"Sent to {wrote['to']}"
                 + (f", copying {wrote['cc']}" if wrote.get("cc") else "")
                 + f" - subject {wrote['subject']!r}"
                 + (f" - a reply in the thread of {message_id}" if replying else
                    f" - forwarding {message_id}")
                 + (f" with {len(files)} of its files" if files else "")
                 + f" - message id {wrote.get('id') or 'unknown'} - pressed on the inbox card")
        self.google.wrote("send_mail", wrote["to"], trail)
        went = f"it went to {wrote['to']}"
        if wrote.get("cc"):
            went += f", copying {wrote['cc']}"
        archived, after, told, cards = "", "", "", []
        if self._after_sent is not None:
            # Told to every tab once this one has its answer (`changed`), so
            # the card that sent it goes back to its list before the others
            # hear that the conversation left the inbox.
            tidied = await self._after_sent(
                chat, wrote, conversation=str(found.get("thread_id") or ""),
                drafts=mode != FORWARD, tell=False)
            archived, after, told, cards = (tidied.archived, tidied.after(),
                                            tidied.told(), tidied.cards)
        return Answer(True, said={"id": message_id, "sent": True, "to": wrote["to"],
                                  "said": f"Sent to {wrote['to']}",
                                  "thread": archived, "archived": bool(archived),
                                  "after": after},
                      note=(f"{what} {about(found)}: {went}, subject "
                            f"{wrote['subject']!r}, sent message id {wrote.get('id')}."
                            + told),
                      turn=True, cards=cards,
                      changed={"thread": archived, "archived": True} if archived else None)


#: The one mailroom this process has, once the tools have wired it in.
ROOM: Mailroom | None = None


def serve(room: Mailroom) -> None:
    """Say what the card's buttons act with. Once, at start-up (`tools.py`)."""
    global ROOM
    ROOM = room


#: What the page may ask of a card.
ASKS = {"list", "open", "archive", "unarchive", "read", "unread", "compose", "send",
        "unsubscribe", "remind", "meeting_soon", "watch", "waiting_too", "answer_watch", "know_them",
        "save_sender", "card_in_mail"}


async def press(msg: dict, who) -> Answer:
    """One ask of an inbox card, by `who`: read it, check it, and do it.

    The token in the card decides whose mailbox it is and which thread hears
    about it; the page only ever says which message and what to do with it.
    """
    what = str(msg.get("do") or "")
    if what not in ASKS:
        return Answer(False, why="The inbox card cannot do that.")
    if ROOM is None:
        return Answer(False, why="Mail is not set up on this machine.")
    sealed = _read(msg.get("token"))
    if sealed is None:
        log.warning("an inbox card carries a token this server did not sign; refused")
        return Answer(False, why="This card cannot reach the mailbox. Ask Rouh to show "
                                 "the inbox again.")
    if sealed.get("expired"):
        return Answer(False, why="This inbox card is too old to use. Ask Rouh to show the "
                                 "inbox again.")
    if (getattr(who, "user_id", None), getattr(who, "org_id", None)) != \
            (sealed.get("u"), sealed.get("o")):
        log.warning("an inbox card was used by somebody it does not belong to")
        return Answer(False, why="This inbox is not yours.")
    theirs = bool(sealed.get("m"))
    if not theirs:
        blocked = ROOM.google.not_ready_because()
        if blocked:
            return Answer(False, why=str(blocked))
    chat = str(sealed.get("c") or "")
    message_id = composing.one_line(msg.get("id"))[:200]
    if what != "list" and not message_id:
        return Answer(False, why="Say which message.")
    if theirs and what not in ("list", "open", "unsubscribe", "remind", "meeting_soon", "watch", "waiting_too", "answer_watch",
                               "know_them", "save_sender", "card_in_mail"):
        # The person's own inbox is connected read-only (`rouh/inboxes.py`):
        # the card has no such button, and a page that asks anyway is told why.
        return Answer(False, why="This inbox is connected read-only, so it can be read "
                                 "here and nothing in it can be changed.")
    mode = str(msg.get("mode") or "")
    if what in ("compose", "send") and mode not in MODES:
        return Answer(False, why="Reply, Reply all or Forward: say which.")
    try:
        if what == "list":
            return Answer(True, said=await ROOM.listing(sealed))
        if what == "open":
            done = await ROOM.open(message_id, sealed)
            done.chat = chat
            return done
        if what == "compose":
            return Answer(True, said=await ROOM.compose(message_id, mode))
        if what == "unsubscribe":
            # A POST to the list's sender, never a change in the mailbox: allowed on a read-only one.
            done = await ROOM.unsubscribe(message_id, sealed)
            done.chat = chat
            return done
        if what == "remind":
            # A reminder on Clockwork, never a change in the mailbox: allowed on a read-only one.
            done = await ROOM.remind(message_id, str(msg.get("when") or ""), sealed)
            done.chat = chat
            return done
        if what == "meeting_soon":
            # Open the meeting, counted: nothing in the mailbox, so a read-only one allows it too.
            done = await ROOM.meeting_soon(sealed)
            done.chat = chat
            return done
        if what == "waiting_too":
            # Open on Also waiting on you, counted: nothing in the mailbox changes.
            done = await ROOM.waiting_too(sealed)
            done.chat = chat
            return done
        if what == "save_sender":
            # Save them as a contact: written to iCloud, nothing in the mailbox changes.
            done = await ROOM.save_sender(message_id, sealed)
            done.chat = chat
            return done
        if what == "card_in_mail":
            # A contact card in an email: written to iCloud, nothing in the mailbox changes.
            done = await ROOM.card_in_mail(message_id, sealed)
            done.chat = chat
            return done
        if what == "know_them":
            # Open on How you know them, counted: nothing in the mailbox changes.
            done = await ROOM.know_them(str(msg.get("when") or ""), sealed)
            done.chat = chat
            return done
        if what == "watch":
            # A look on Clockwork, never a change in the mailbox: allowed on a read-only one.
            done = await ROOM.watch(message_id, sealed)
            done.chat = chat
            return done
        if what == "answer_watch":
            # A look on Clockwork, never a change in the mailbox: allowed on a read-only one.
            done = await ROOM.answer_watch(message_id, sealed)
            done.chat = chat
            return done
        if what == "archive":
            done = await ROOM.archive(message_id)
        elif what == "unarchive":
            done = await ROOM.unarchive(message_id)
        elif what in ("read", "unread"):
            done = await ROOM.mark(message_id, read=what == "read")
        else:
            done = await ROOM.send(message_id, mode, msg.get("edits"), msg.get("keep"),
                                   chat=chat)
    except composing.Refused as exc:
        return Answer(False, why=str(exc))
    except Exception as exc:  # noqa: BLE001 - every ask is answered, with why
        log.warning("the inbox card's %s failed: %s", what, type(exc).__name__)
        return Answer(False, why=str(ROOM._trouble(exc)))
    done.chat = chat
    return done


__all__ = ["DEFAULT_LIMIT", "FORWARD", "KIND", "MODES", "MOST", "REPLY",
           "REPLY_ALL", "Answer", "Mailroom", "addresses", "block",
           "counted", "form", "html_text", "opened", "parts", "press", "recipients",
           "row", "search_for", "serve", "strip", "subject_for", "when", "written"]
