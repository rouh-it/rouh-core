"""Waiting on others: emails the person sent that asked for something, and nobody answered.

Task 71, 30 September 2026, the "ghost list" in the morning brief. Read from
every mailbox the person has given Rouh: its own Google connection, with full
access (`google_oauth.py`), and each of their mailboxes connected read-only
(`rouh/mailboxes.py`), one at a time and never mixed: every email on the list
is shown under the mailbox it was sent from, and everything done to one is
keyed on that mailbox. "The ghost list should be for all mails you have access
to, including the read only" (Petar, fr_1007ecea9327): so the connection is on
it as well, first, and each read-only mailbox says that it is one. Nothing on
the list writes to any mailbox, so a read-only one loses nothing: the
connection is read the same way, with GET alone (`ConnectionGmail`).

**Finding them.** For each mailbox, in plain rules and no model:

1. **Sent mail**, from `WAIT_DAYS` to `LOOK_BACK_DAYS` days ago
   (`in:sent newer_than:30d older_than:2d`), each conversation once.
2. **The last word in the conversation is still the person's.** A reply
   anywhere in it, from anybody but the person, including someone on Cc,
   clears it. A draft is not a word; an automatic reply (out of office,
   `Auto-Submitted`, "Automatic reply:") does not count as an answer.
3. **It went to somebody.** Not only to the person's own addresses (the
   mailbox's own and its send-as aliases), not only to machines (no-reply,
   notifications, mailer-daemon), not to a mailing list or a crowd of more
   than `MOST_PEOPLE`, and not a calendar invitation or an answer to one.
4. **It asked for something.** What the person wrote themselves - quotes,
   forwarded mail and the signature cut off - has a question in it, or a
   request ("could you", "please send", "let me know", "any update", and the
   same in Bulgarian: "може ли", "моля", "кажи ми"...). A courtesy is not an
   ask: "let me know if you have any questions", "feel free to", "hope you are
   well?". "Thanks", "sounds good", "FYI" and "here is the file" are not asks.
5. **They have not written since.** A later email from any of the people it
   went to, in any conversation, clears it: they are in touch, and the answer
   may be there. Automatic replies do not count here either.

The ask itself, the sentence that asked, is shown with it, so the person can
see at a glance why it is on the list and dismiss it if it is not a real one.

**What the person does with one**, all kept in Rouh and nothing written to any
mailbox: Read it whole on the brief (`message`), Open (the conversation in
Gmail, in that account), Defer (three days, or a week), Dismiss (until a new
ask goes in the same conversation), and Draft a nudge. From Rouh's own
connection, which it controls and may send from, the nudge has a Send button:
it goes as a reply in that conversation to the people it asked, and the email
is marked nudged (`send_nudge`, fr_e052e3e4d875, 29 September 2026: "For the
account that you control, you should just give me a send button. Not copy").
From a read-only mailbox it is text to copy into a reply of their own, since
Rouh can send nothing from one. Neither is ever written into a mailbox as a
draft.

**Incoming.** Each mailbox's look also takes the unread mail in the Primary
tab of its inbox from the last day (`unread`), and nothing from Updates,
Social, Promotions or Forums (fr_1da7cddc045b, 30 September 2026: "we should
be seeing the latest ones from my inbox only. It seems that I'm getting emails
from the other categories, like updates or social media"). The brief has one section per
mailbox, headed by its address, with what came in and what is waiting on
others both under it (fr_dfce915c2c6d, 30 September 2026: "I don't know which
mail inbox that is and now we have multiple"). Each can be read whole, deferred
or marked Handled, kept in the same `GhostMark` rows and never in the mailbox,
so nothing is marked read there, and a read-only mailbox has all of it too.

**When it is read.** Each mailbox's last look is kept on its row
(`ReadMailbox.scan`, and `GoogleConnection.ghost_scan` for the connection) and is looked at again once it is `FRESH_SECONDS` old, or
when the brief is made again; the morning loop looks first thing, so the page
has it straight away (`morning_brief.Mornings.beat`).
"""
from __future__ import annotations

import asyncio
import email.utils
import html as html_module
import json
import logging
import re
import time
import urllib.parse
from dataclasses import dataclass
from datetime import datetime
from types import SimpleNamespace

import httpx

from .mailboxes import GmailReads

log = logging.getLogger("rouh.ghosts")

WAIT_DAYS = 2
LOOK_BACK_DAYS = 30
#: How much sent mail is read in one look, and how many conversations.
MOST_SENT = 100
MOST_THREADS = 40
#: More people than this on one email is an announcement, not an ask of anyone.
MOST_PEOPLE = 10
#: How many emails one mailbox puts on the list at most.
MOST_LISTED = 25
FRESH_SECONDS = 60 * 60
#: A look that has just been made is not made again, even when asked for.
JUST_LOOKED = 60
#: How long each Defer holds, by the name the page sends.
DEFER_DAYS = {"days": 3, "week": 7}
#: How much unread mail from the last day one mailbox puts on the brief.
MOST_UNREAD = 10
UNREAD_DAYS = 1
#: The unread mail in the Primary tab of the inbox, and nothing from its other tabs.
PRIMARY_UNREAD = "in:inbox category:primary is:unread -in:chats"
#: How far the unread in Primary is counted; past it the brief says "500 or more".
MOST_COUNTED = 500
#: The longest body the page is handed to read.
MOST_BODY = 200_000
SCAN_SECONDS = 90.0

#: The mailbox id Rouh's own Google connection is given on the list and in
#: `GhostMark.mailbox_id`. A read-only mailbox's is its row's, from 1 up.
CONNECTION = 0

#: The grants any one of which lets the connection read mail. Without one it
#: is Calendar or Drive only, and is not a mailbox at all.
MAIL_READS = ("https://www.googleapis.com/auth/gmail.modify",
              "https://www.googleapis.com/auth/gmail.readonly",
              "https://mail.google.com/")

#: The grants any one of which lets the connection send mail, which is what
#: gives a nudge in it a Send button rather than Copy.
MAIL_SENDS = ("https://www.googleapis.com/auth/gmail.send",
              "https://www.googleapis.com/auth/gmail.compose",
              "https://www.googleapis.com/auth/gmail.modify",
              "https://mail.google.com/")

# --- what the person wrote, and whether it asked -------------------------------------

_CUT = re.compile(
    r"^\s*(?:"
    r"On\b.{0,300}\bwrote:\s*$"
    r"|-{2,}\s*Original Message\s*-{2,}"
    r"|-{5,}\s*Forwarded message"
    r"|Begin forwarded message:"
    r"|From:\s.+"
    r"|На\b.{0,300}\bнаписа:\s*$"
    r"|Le\b.{0,200}\ba écrit\s*:?\s*$"
    r"|Am\b.{0,200}\bschrieb\b.{0,100}:\s*$"
    r"|_{10,}\s*$"
    r"|Sent from my \w+"
    r"|Изпратено от"
    r")", re.I)

_PLEASANTRY = re.compile(
    r"\b(how are you|how(?:'s| is| are) (?:it going|things|you doing|the family)"
    r"|hope (?:you(?:'re| are)|all is|everything is|this finds)"
    r"|как си|как сте|как върви|как е)", re.I)

_COURTESY = re.compile(
    r"(?:(?:let me know|tell me|ping me|reach out) if (?:you )?(?:have|need|there(?:'s| is| are)|anything|any)"
    r"|if you (?:have|need) any(?:thing| questions)|feel free to|(?:don't|do not) hesitate"
    r"|please (?:find|see) (?:the )?(?:attached|below|enclosed)"
    r"|ако (?:имаш|имате) (?:въпроси|нужда)|ако има (?:нещо|въпроси)|не се колебай)", re.I)

_REQUEST = re.compile(
    r"(?:\b(?:could|can|would|will) you\b|\bplease\b|\bkindly\b|\blet me know\b"
    r"|\bget back to (?:me|us)\b|\bwaiting (?:for|on) (?:your|you|the|an?)\b"
    r"|\bany (?:update|news|progress|word)\b|\blooking forward to (?:hearing|your)\b"
    r"|\bneed (?:you|your|it from you)\b|\bsend (?:me|us|over)\b|\bconfirm\b"
    r"|\bwhen (?:can|will|could) (?:you|we|i)\b"
    r"|може ли|можеш ли|можете ли|бихте ли|би ли|\bмоля\b|кажи ми|кажете ми|чакам|очаквам"
    r"|прати ми|пратете|изпрати ми|изпратете|потвърди|обади ми се|обадете ми се|дай ми знак)",
    re.I)

_SENTENCES = re.compile(r"(?<=[.!?])\s+|\n+")


def own_words(text: str) -> str:
    """What the person wrote themselves: no quoted mail, no forward, no signature."""
    kept = []
    for line in (text or "").replace("\r\n", "\n").split("\n")[:400]:
        if line.rstrip() in ("--", "-- ") or _CUT.match(line):
            break
        if line.lstrip().startswith(">"):
            continue
        kept.append(line)
    return "\n".join(kept).strip()


def the_ask(text: str) -> str:
    """The sentence that asks for something, or "" when nothing does."""
    for piece in _SENTENCES.split(own_words(text)[:4000])[:60]:
        sentence = " ".join(piece.split())
        if len(sentence) < 4 or _PLEASANTRY.search(sentence) or _COURTESY.search(sentence):
            continue
        if "?" in sentence or _REQUEST.search(sentence):
            return sentence[:240]
    return ""


def _text_of(markup: str) -> str:
    markup = re.sub(r"(?is)<(style|script|head)[^>]*>.*?</\1>", " ", markup or "")
    markup = re.sub(r"(?is)<blockquote.*?</blockquote>", "\n", markup)
    markup = re.sub(r"(?is)<div class=\"?gmail_quote.*$", "\n", markup)
    markup = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</li>", "\n", markup)
    return html_module.unescape(re.sub(r"<[^>]+>", " ", markup))


# --- reading a message -------------------------------------------------------------------

_MACHINE = re.compile(
    r"^(?:no-?reply|do-?not-?reply|donotreply|notifications?|notify|mailer-daemon|postmaster"
    r"|bounces?|alerts?|calendar-notification|automated|auto-?confirm|news(?:letter)?)"
    r"(?:[+._-].*)?@", re.I)

_CALENDAR_SUBJECT = re.compile(
    r"^\s*(?:invitation|updated invitation|accepted|declined|tentatively accepted"
    r"|canceled event|cancelled event|new event|покана|приета|отхвърлена)\b.*?:", re.I)

_AUTO_SUBJECT = re.compile(
    r"^\s*(?:automatic reply|auto(?:-| )?reply|out of (?:the )?office|autoreply"
    r"|автоматичен отговор|извън офиса)\b", re.I)


def _named(message: dict) -> dict:
    return {(h.get("name") or "").lower(): h.get("value") or ""
            for h in (message.get("payload") or {}).get("headers") or []}


def _at(message: dict) -> float:
    try:
        return int(message.get("internalDate") or 0) / 1000.0
    except (TypeError, ValueError):
        return 0.0


def people(value: str) -> list[tuple[str, str]]:
    """The people on a To or Cc line, as (name, address lower case)."""
    return [(name.strip().strip('"'), addr.strip().lower())
            for name, addr in email.utils.getaddresses([value or ""]) if "@" in addr]


def is_machine(address: str) -> bool:
    return bool(_MACHINE.match(address or ""))


def is_auto_reply(named: dict) -> bool:
    auto = (named.get("auto-submitted") or "").strip().lower()
    if auto and auto != "no":
        return True
    if named.get("x-autoreply") or named.get("x-autorespond"):
        return True
    if (named.get("precedence") or "").strip().lower() in ("auto_reply",):
        return True
    return bool(_AUTO_SUBJECT.match(named.get("subject") or ""))


def _has_calendar(part: dict) -> bool:
    if (part.get("mimeType") or "").lower() == "text/calendar":
        return True
    return any(_has_calendar(child) for child in part.get("parts") or [])


def _body_text(message: dict) -> str:
    from .google_api import _message_bodies

    plain, markup = _message_bodies(message.get("payload") or {})
    return plain or _text_of(markup)


def sender(value: str) -> dict:
    """The one who sent it, {name, email}, from a From line."""
    found = people(value)
    if found:
        return {"name": found[0][0][:80], "email": found[0][1]}
    return {"name": " ".join((value or "").split())[:80], "email": ""}


def link_to(email_address: str, thread_id: str) -> str:
    """The conversation in Gmail, opened in that account and not whichever is signed in first."""
    return ("https://mail.google.com/mail/?authuser=" + urllib.parse.quote(email_address or "")
            + "#all/" + urllib.parse.quote(thread_id or "", safe=""))


def app_link(account: str, rfc822_id: str) -> str:
    """The email in the Gmail app on a phone, in the account that holds it, or "".

    Google's own link, as the Gmail app itself makes it to open an email from
    a chat message (`UrlAnnotationProcessor` in the Android app, 2026.09): a
    gmail.app.goo.gl address, which the Gmail app claims on an iPhone and on
    Android and which a browser is sent on from to Gmail on the web. It finds
    the email by its own Message-ID and the account by Google's own id of it
    (`ogid`, the `sub` Rouh keeps as `google_account`), so nothing in it is a
    number that means "the first account signed in" (fr_3f75a6f114eb). The
    search is encoded the way Java's URLEncoder does it, as Google's is.
    """
    rfc822_id = (rfc822_id or "").strip().strip("<>").strip()
    if not rfc822_id:
        return ""
    search = urllib.parse.quote_plus("rfc822msgid:" + rfc822_id, safe="*").replace("~", "%7E")
    out = ("https://gmail.app.goo.gl/?link=https://mail.google.com/mail/mu/mp/"
           "%3Fauthuser%3D0%23tl%2Fsearch%2F" + search)
    if account:
        out += "&ogid=" + urllib.parse.quote(account, safe="")
    return out + "&hidesearch=true&apn=com.google.android.gm"


# --- the nudge ------------------------------------------------------------------------------

_MONTHS_BG = ("януари", "февруари", "март", "април", "май", "юни", "юли", "август",
              "септември", "октомври", "ноември", "декември")


def _plain_subject(subject: str) -> str:
    return re.sub(r"^\s*((re|fwd?|fw|отг|препр)\s*:\s*)+", "", subject or "", flags=re.I).strip()


def nudge(item: dict, zone) -> str:
    """A short follow-up for a reply: words only, sent only when the person presses Send."""
    first = ""
    if item["to"]:
        name = item["to"][0]["name"]
        first = name.split()[0] if name and "@" not in name else ""
    sent = datetime.fromtimestamp(item["sent_at"], zone)
    subject = _plain_subject(item["subject"]) or "my last email"
    if re.search(r"[а-яА-Я]", item.get("ask") or "") or re.search(r"[а-яА-Я]", subject):
        hello = f"Здравей, {first}," if first else "Здравей,"
        return (f"{hello}\n\nПиша отново за имейла ми от {sent.day} "
                f"{_MONTHS_BG[sent.month - 1]} относно „{subject}“. Можеш ли да ми кажеш "
                f"докъде стигна?\n\nБлагодаря,")
    hello = f"Hi {first}," if first else "Hi,"
    return (f"{hello}\n\nJust following up on my email from {sent.strftime('%A')} "
            f"{sent.day} {sent.strftime('%B')} about \"{subject}\". Could you let me know "
            f"where this stands?\n\nThanks,")


# --- one look at one mailbox -------------------------------------------------------------------


async def _gathered(calls, most: int = 8):
    gate = asyncio.Semaphore(most)

    async def one(call):
        async with gate:
            return await call

    return await asyncio.gather(*(one(call) for call in calls), return_exceptions=True)


def _verdict(thread: dict, own: set[str], now: float) -> dict | None:
    """One conversation: the email waiting on somebody, or None and why not (for the log)."""
    messages = sorted(thread.get("messages") or [], key=_at)
    waiting = None
    auto = False
    for message in reversed(messages):
        labels = set(message.get("labelIds") or [])
        if labels & {"DRAFT", "CHAT", "SPAM", "TRASH"}:
            continue
        named = _named(message)
        sender = (people(named.get("from", "")) or [("", "")])[0][1]
        if "SENT" in labels or sender in own:
            waiting = message
            break
        if is_auto_reply(named):
            auto = True
            continue
        return None                          # somebody answered
    if waiting is None:
        return None
    sent_at = _at(waiting)
    if now - sent_at < WAIT_DAYS * 86400:
        return None                          # asked again lately: not waiting long yet
    named = _named(waiting)
    subject = named.get("subject") or ""
    if (named.get("list-id") or named.get("list-unsubscribe")
            or (named.get("precedence") or "").lower() in ("bulk", "list", "junk")):
        return None
    if _CALENDAR_SUBJECT.match(subject) or _has_calendar(waiting.get("payload") or {}):
        return None
    to, cc = people(named.get("to", "")), people(named.get("cc", ""))
    if len(to) + len(cc) > MOST_PEOPLE:
        return None
    asked = [(n, a) for n, a in to if a not in own and not is_machine(a)]
    if not asked and not to:
        asked = [(n, a) for n, a in cc if a not in own and not is_machine(a)]
    if not asked:
        return None                          # to themselves, or to machines
    ask = the_ask(_body_text(waiting))
    if not ask:
        return None
    return {"thread_id": waiting.get("threadId") or thread.get("id") or "",
            "message_id": waiting.get("id") or "", "subject": subject[:200] or "(no subject)",
            "rfc822_id": named.get("message-id", "")[:500],
            "to": [{"name": n[:80], "email": a} for n, a in asked[:5]],
            "cc": len([1 for _n, a in cc if a not in own]),
            "sent_at": sent_at, "ask": ask, "auto_reply": auto}


async def _written_since(gmail, item: dict) -> bool:
    """Whether any of the people it went to has written to this mailbox since, by a person."""
    who = " OR ".join(one["email"] for one in item["to"])
    try:
        found = await gmail.search(f"from:({who}) after:{int(item['sent_at'])} -in:sent -in:chats", 5)
    except Exception as exc:
        log.info("mailbox %s: could not look for later mail: %s", gmail.mailbox.id, exc)
        return False
    others = [one for one in found if one.get("threadId") != item["thread_id"]][:3]
    for got in await _gathered([gmail.headers(one["id"]) for one in others]):
        if isinstance(got, BaseException):
            continue
        if not is_auto_reply(_named(got)) and _at(got) > item["sent_at"]:
            return True
    return False


async def unread(gmail, deferred: tuple[str, ...] = ()) -> dict:
    """The unread mail in the Primary tab of this inbox from the last day, newest first.

    {unread: [...], unread_total, unread_more} - the total is every unread
    email in Primary, counted up to `MOST_COUNTED`, and `unread_more` says it
    reached that. Read with GET alone, so nothing is marked
    read. `deferred` are the emails deferred from here: each is read again by
    its id, however old, and handed back as `returned`, so one deferred for a
    week is there to come back when the week is up, long after it stopped
    being new.
    """
    found = await gmail.search(f"{PRIMARY_UNREAD} newer_than:{UNREAD_DAYS}d", MOST_UNREAD)
    ids = [one["id"] for one in found]
    again = [one for one in deferred if one not in ids][:MOST_UNREAD]
    got = await _gathered([gmail.summary(one) for one in ids + again])
    since = time.time() - UNREAD_DAYS * 86400
    items = []
    for ident, one in zip(ids + again, got):
        if isinstance(one, BaseException):
            log.info("mailbox %s: an unread email could not be read: %s", gmail.mailbox.id, one)
            continue
        returned = ident in again
        if not returned and _at(one) and _at(one) < since:
            continue                         # older than the search promised
        named = _named(one)
        items.append({"returned": returned,
            "kind": "unread", "message_id": one.get("id") or "",
            "thread_id": one.get("threadId") or one.get("id") or "",
            "from": sender(named.get("from", "")),
            "subject": (named.get("subject") or "(no subject)")[:200],
            "at": _at(one),
            "snippet": html_module.unescape(one.get("snippet") or "")[:200],
            "rfc822_id": named.get("message-id", "")[:500],
            "link": link_to(gmail.mailbox.email, one.get("threadId") or one.get("id") or "")})
    items.sort(key=lambda one: -one["at"])
    total = len(items)
    try:
        # Primary's own unread, counted, not the INBOX label's, which counts
        # every tab: that is the number Gmail shows beside Primary.
        every = await gmail.search(PRIMARY_UNREAD, MOST_COUNTED)
        total = max(total, len(every))
    except Exception as exc:
        log.info("mailbox %s: the inbox count could not be read: %s", gmail.mailbox.id, exc)
    return {"unread": items, "unread_total": total,
            "unread_more": total >= MOST_COUNTED}


async def scan(gmail, zone, *, now: float | None = None,
               deferred: tuple[str, ...] = ()) -> dict:
    """One look at one mailbox's sent mail. {ok, items, looked_at, at} or {ok: False, note}."""
    now = time.time() if now is None else now
    own = await gmail.addresses()
    sent = await gmail.search(
        f"in:sent newer_than:{LOOK_BACK_DAYS}d older_than:{WAIT_DAYS}d -in:chats", MOST_SENT)
    threads, seen = [], set()
    for one in sent:
        thread = one.get("threadId") or one["id"]
        if thread not in seen:
            seen.add(thread)
            threads.append(thread)
    threads = threads[:MOST_THREADS]
    read = await _gathered([gmail.thread(one) for one in threads])
    items, missed = [], 0
    for got in read:
        if isinstance(got, BaseException):
            missed += 1
            log.info("mailbox %s: a conversation could not be read: %s", gmail.mailbox.id, got)
            continue
        found = _verdict(got, own, now)
        if found:
            items.append(found)
    since = await _gathered([_written_since(gmail, one) for one in items])
    items = [one for one, wrote in zip(items, since) if wrote is not True]
    for one in items:
        one["days"] = int((now - one["sent_at"]) // 86400)
        one["link"] = link_to(gmail.mailbox.email, one["thread_id"])
        one["nudge"] = nudge(one, zone)
    items.sort(key=lambda one: one["sent_at"])
    out = {"ok": True, "items": items[:MOST_LISTED], "more": max(0, len(items) - MOST_LISTED),
           "looked_at": len(threads), "at": now}
    if missed:
        out["unreadable"] = missed
    try:
        out.update(await unread(gmail, deferred))
    except Exception as exc:
        log.info("mailbox %s: the inbox could not be read: %s", gmail.mailbox.id, exc)
        out.update({"unread": [], "unread_total": 0, "unread_more": False,
                    "unread_note": "The unread mail in this inbox could not be read just now."})
    return out


# --- Rouh's own connection, read like a mailbox -------------------------------------------


class ConnectionGmail(GmailReads):
    """Rouh's own Google connection, read for the ghost list with GET alone.

    Through `GoogleClients.call`, so its token, renewal and refusals are the
    connection's own, and a grant that cannot read mail says so.
    """

    def __init__(self, clients, who, email: str) -> None:
        self._clients = clients
        self._who = who
        self.mailbox = SimpleNamespace(id=CONNECTION, email=email)

    async def get(self, path: str, params=None) -> dict:
        return await self._clients.call(
            self._who, "GET", self._clients.base("gmail") + "/gmail/v1/users/me" + path,
            params=params, needs_scope=MAIL_READS,
            without_it=(f"Rouh's Google connection, {self.mailbox.email}, was not allowed to "
                        "read mail. Connect it again in Settings, under Google."))


def _can_read_mail(connection) -> bool:
    # No scopes on file is a grant this build never saw: left to Google to judge.
    return not connection.scopes or any(one in connection.scopes for one in MAIL_READS)


def _can_send_mail(connection) -> bool:
    return not connection.scopes or any(one in connection.scopes for one in MAIL_SENDS)


@dataclass
class Source:
    """One mailbox on the list: the connection, or a read-only mailbox."""

    id: int
    email: str
    read_only: bool
    needs_reconnect: bool = False
    account: str = ""
    #: Whether Rouh may send from it: only its own connection, with a grant to send.
    can_send: bool = False

    @property
    def is_connection(self) -> bool:
        return self.id == CONNECTION


def sources(who, auth) -> list[Source]:
    """Every mailbox this person has given Rouh, the connection first.

    A read-only mailbox of the same Google account as the connection is left
    out, so no mailbox is on the list twice, and it is the connection that
    stays: Rouh can do more with it, and it says so.
    """
    out = []
    held = auth.google_store.connection(who.user_id, who.org_id)
    if held is not None and _can_read_mail(held):
        out.append(Source(CONNECTION, held.google_email, False, held.needs_reconnect,
                          held.google_account, _can_send_mail(held)))
    for row in auth.store.rows(who):
        if out and row.google_account and row.google_account == out[0].account:
            continue
        out.append(Source(row.id, row.email, True, bool(row.needs_reconnect),
                          row.google_account))
    return out


# --- what the page is given ----------------------------------------------------------------

_LOCKS: dict[tuple, asyncio.Lock] = {}


def _say_trouble(exc, email_address: str) -> str:
    from .google_api import GoogleSaidNo
    from .google_oauth import NeedsReconnect as ConnectionNeedsReconnect
    from .google_oauth import NotConnected as ConnectionNotConnected
    from .google_store import NotSetUp
    from .mailboxes import NeedsReconnect, NotConnected, Refused

    if isinstance(exc, NotSetUp):
        return ("Google is not set up for your organisation any more, so "
                f"{email_address} cannot be read. An administrator enters the Google app in Settings.")
    if isinstance(exc, (NeedsReconnect, NotConnected, ConnectionNeedsReconnect,
                        ConnectionNotConnected)):
        return str(exc)
    if isinstance(exc, (GoogleSaidNo, Refused)):
        said = re.sub(r"\s+", " ", str(exc)).strip()[:220]
        return f"{email_address} could not be read just now" + (f": {said}" if said else ".")
    if isinstance(exc, asyncio.TimeoutError):
        return f"{email_address} took too long to read just now. Try again in a moment."
    log.warning("the ghost list could not read mailbox %s: %r", email_address, exc)
    return f"{email_address} could not be read just now."


def _kept(who, mailbox_id) -> dict | None:
    """A mailbox's last look, {} when there is none yet, or None when it is not connected.

    The connection's look is only its own while the same Google account is
    connected: one connected again as another account starts afresh.
    """
    from .models import GoogleConnection, ReadMailbox

    try:
        ident = int(mailbox_id)
    except (TypeError, ValueError):
        return None
    if not who or not who.user_id or not who.org_id:
        return None
    if ident == CONNECTION:
        row = (GoogleConnection.objects.filter(user_id=who.user_id, org_id=who.org_id)
               .values("ghost_scan", "ghost_scanned_at", "google_account").first())
        if row is None:
            return None
        text, at, account = row["ghost_scan"], row["ghost_scanned_at"], row["google_account"]
    else:
        row = (ReadMailbox.objects.filter(id=ident, user_id=who.user_id, org_id=who.org_id)
               .values("scan", "scanned_at").first())
        if row is None:
            return None
        text, at, account = row["scan"], row["scanned_at"], None
    try:
        found = json.loads(text) if text else {}
    except ValueError:
        found = {}
    if account is not None and found.get("account", "") != account:
        return {}
    return {"found": found, "at": at or 0} if found else {}


def _keep_scan(who, source: Source, found: dict) -> None:
    from .models import GoogleConnection, ReadMailbox

    at = found.get("at") or time.time()
    if source.is_connection:
        GoogleConnection.objects.filter(
            user_id=who.user_id, org_id=who.org_id, google_account=source.account).update(
            ghost_scan=json.dumps({**found, "account": source.account}, ensure_ascii=False),
            ghost_scanned_at=at)
        return
    ReadMailbox.objects.filter(id=source.id, user_id=who.user_id, org_id=who.org_id).update(
        scan=json.dumps(found, ensure_ascii=False), scanned_at=at)


#: How long after its day a deferred email is still read again to show it.
DEFERRED_KEPT_DAYS = 14


def _deferred(who, mailbox_id: int) -> tuple[str, ...]:
    """The emails deferred from this mailbox's inbox, lately enough to show again."""
    from .models import GhostMark

    return tuple(GhostMark.objects.filter(
        user_id=who.user_id, org_id=who.org_id, mailbox_id=mailbox_id, state="deferred",
        until__gt=time.time() - DEFERRED_KEPT_DAYS * 86400)
        .order_by("-until").values_list("message_id", flat=True)[:MOST_UNREAD])


def _marks(who) -> dict:
    from .models import GhostMark

    return {(one.mailbox_id, one.thread_id): one for one in
            GhostMark.objects.filter(user_id=who.user_id, org_id=who.org_id)}


def _reader(who, auth, cfg, source: Source):
    if source.is_connection:
        from .google_api import GoogleClients

        return ConnectionGmail(GoogleClients(auth.google_auth, cfg), who, source.email)
    from .mailboxes import ReadOnlyGmail

    mailbox = auth.store.mailbox(who, source.id)
    if mailbox is None:
        return None
    return ReadOnlyGmail(auth, mailbox, cfg)


async def look(who, auth, cfg, source: Source, *, zone, fresh: bool = False) -> dict:
    """This mailbox's last look, made again when it is old or `fresh` is asked for."""
    from asgiref.sync import sync_to_async

    held = await sync_to_async(_kept)(who, source.id)
    if held is None:
        return {"ok": False, "note": "That mailbox is not connected any more."}
    kept, at = held.get("found") or {}, held.get("at") or 0
    age = time.time() - at
    if kept.get("ok") and "unread_more" not in kept:
        # Kept before Incoming was Primary alone: its unread is from every tab.
        age = FRESH_SECONDS
    if kept and (age < JUST_LOOKED or (not fresh and age < FRESH_SECONDS)):
        return kept
    lock = _LOCKS.setdefault((who.org_id, who.user_id, source.id), asyncio.Lock())
    async with lock:
        again = await sync_to_async(_kept)(who, source.id)
        if again and again.get("found") and time.time() - again["at"] < JUST_LOOKED:
            return again["found"]
        try:
            reader = await sync_to_async(_reader)(who, auth, cfg, source)
            if reader is None:
                return {"ok": False, "note": "That mailbox is not connected any more."}
            deferred = await sync_to_async(_deferred)(who, source.id)
            found = await asyncio.wait_for(scan(reader, zone, deferred=deferred), SCAN_SECONDS)
        except Exception as exc:
            said = _say_trouble(exc, source.email or "This mailbox")
            if kept.get("ok"):
                # What was found last time is still worth seeing, said to be old.
                return {**kept, "note": said, "stale": True}
            return {"ok": False, "note": said}
        await sync_to_async(_keep_scan)(who, source, found)
        return found


async def listing(who, auth, cfg, *, fresh: bool = False) -> dict:
    """Every mailbox this person has given Rouh, each with what is waiting on others in it.

    Deferred, dismissed and handled emails, asks and unread alike, are taken
    off the list here and handed back under `hidden`, each with its mark and
    its `kind`, so the page can bring one back.
    """
    from asgiref.sync import sync_to_async

    from . import clock

    opened = await sync_to_async(sources)(who, auth)
    zone = clock.zone_of(who)
    looks = await asyncio.gather(*(
        look(who, auth, cfg, one, zone=zone, fresh=fresh) if not one.needs_reconnect
        else _needs_again(one) for one in opened), return_exceptions=True)
    marks = await sync_to_async(_marks)(who)
    now = time.time()
    out = []
    for one, got in zip(opened, looks):
        if isinstance(got, BaseException):
            got = {"ok": False, "note": _say_trouble(got, one.email)}
        hidden = []

        def sift(items, kind):
            shown = []
            for item in items or []:
                item = {**item, "app_link": app_link(one.account, item.get("rfc822_id", ""))}
                mark = marks.get((one.id, item["thread_id"]))
                if _holds(mark, item, now):
                    hidden.append({**item, "kind": kind, "mark": mark.state, "until": mark.until})
                else:
                    shown.append({**item, "kind": kind})
            return shown

        shown = sift(got.get("items"), "ask")
        fresh_mail = sift(got.get("unread"), "unread")
        out.append({"id": one.id, "email": one.email, "account": one.account,
                    "read_only": one.read_only,
                    "connection": one.is_connection, "can_send": one.can_send,
                    "ok": bool(got.get("ok")),
                    "note": got.get("note") or "", "stale": bool(got.get("stale")),
                    "items": shown, "unread": fresh_mail,
                    "unread_total": got.get("unread_total") or 0,
                    "unread_more": bool(got.get("unread_more")),
                    "unread_note": got.get("unread_note") or "",
                    "hidden": hidden, "more": got.get("more") or 0,
                    "looked_at": got.get("looked_at") or 0, "at": got.get("at") or 0,
                    "wait_days": WAIT_DAYS, "look_back_days": LOOK_BACK_DAYS})
    return {"ok": True, "mailboxes": out}


def _holds(mark, item: dict, now: float) -> bool:
    """Whether a mark still keeps this email off the list.

    Only for the very email it was given to: a new one in the same
    conversation is new, and shows. A deferral holds until its day.
    """
    if mark is None or mark.message_id != item["message_id"]:
        return False
    return mark.state in ("dismissed", "handled", "nudged") or (
        mark.state in ("snoozed", "deferred") and mark.until > now)


async def _needs_again(source: Source) -> dict:
    where = "Google" if source.is_connection else "Read-only mailboxes"
    return {"ok": False, "note": (f"Google no longer accepts {source.email}. Connect it again "
                                  f"in Settings, under {where}.")}


async def refresh_all(who, auth, cfg) -> None:
    """Look at every mailbox now, for the morning loop, so the page has the list at once."""
    await listing(who, auth, cfg, fresh=True)


class Refused(ValueError):
    """A mark that cannot be kept, or a nudge that cannot go, in words the page shows."""


def mark(who, sent: dict) -> dict:
    """Defer, dismiss, mark handled, or bring back one email.

    {mailbox, thread, message, action, until}: action "defer" (or its old name
    "snooze") with until "days" or "week", "dismiss", "handled" or "restore".

    Kept in Rouh alone. The mailbox has to be this person's own - their
    connection, or one of their read-only mailboxes - and the email has to be
    on its last look, so nothing can be marked in a mailbox that is not
    theirs, or for a conversation that is not in it.
    """
    from .models import GhostMark

    held = _kept(who, sent.get("mailbox"))
    if held is None:
        raise Refused("That mailbox is not connected.")
    mailbox_id = int(sent.get("mailbox"))
    thread, message = str(sent.get("thread") or ""), str(sent.get("message") or "")
    found = held.get("found") or {}
    asks, fresh_mail = found.get("items") or [], found.get("unread") or []

    def on(items):
        return any(one["thread_id"] == thread and one["message_id"] == message for one in items)

    if not on(asks) and not on(fresh_mail):
        raise Refused("That email is not on the list any more. Make the brief again.")
    action = sent.get("action")
    where = dict(user_id=who.user_id, org_id=who.org_id, mailbox_id=mailbox_id, thread_id=thread)
    if action == "restore":
        GhostMark.objects.filter(**where).delete()
        return {"state": ""}
    if action == "dismiss":
        state, until = "dismissed", 0.0
    elif action == "handled":
        state, until = "handled", 0.0
    elif action in ("defer", "snooze"):
        days = DEFER_DAYS.get(str(sent.get("until") or "days"))
        if days is None:
            raise Refused("Defer for three days or for a week.")
        # An ask is "snoozed" and an email that came in is "deferred": only
        # the second is read again by its id when its day comes (`unread`).
        state, until = ("snoozed" if on(asks) else "deferred"), time.time() + days * 86400
    else:
        raise Refused("Defer, dismiss, mark handled or bring it back.")
    GhostMark.objects.update_or_create(**where, defaults={
        "message_id": message, "state": state, "until": until, "at": time.time()})
    return {"state": state, "until": until}


#: The longest nudge that is sent.
MOST_NUDGE = 20_000


def _nudge_to(named: dict, own: set[str], asked: list[dict]) -> tuple[str, str]:
    """Who a nudge goes to and who is copied: the email's own people, less the person.

    The people it went to and the people on Cc, as Gmail's Reply all on one's
    own sent email has them. When all it asked were on Cc, they are the To.
    """
    def line(found):
        return [email.utils.formataddr((n, a)) for n, a in found
                if a not in own and not is_machine(a)]

    to, cc = line(people(named.get("to", ""))), line(people(named.get("cc", "")))
    if not to:
        to, cc = cc, []
    if not to:
        to = [email.utils.formataddr((p.get("name") or "", p.get("email") or ""))
              for p in asked if p.get("email")]
    return ", ".join(to), ", ".join(cc)


async def send_nudge(who, auth, cfg, sent: dict) -> dict:
    """Send the nudge on one waiting email as a reply in its conversation, and mark it nudged.

    {mailbox, thread, message, text}. Only from Rouh's own connection, and only
    when its grant can send: a read-only mailbox is copied from, never sent
    from. The email has to be on the connection's last look, so nothing can be
    sent into a conversation that is not on the brief.
    """
    from asgiref.sync import sync_to_async

    from .google_api import Gmail, GoogleClients

    try:
        mailbox_id = int(sent.get("mailbox"))
    except (TypeError, ValueError):
        raise Refused("That mailbox is not connected.")
    thread, message = str(sent.get("thread") or ""), str(sent.get("message") or "")
    text = str(sent.get("text") or "").strip()
    if not text:
        raise Refused("There is nothing in the nudge to send.")
    if len(text) > MOST_NUDGE:
        raise Refused("That nudge is too long to send.")
    source, _listed = await sync_to_async(_source_of)(who, auth, mailbox_id)
    if source is None:
        raise Refused("That mailbox is not connected.")
    if not source.is_connection:
        raise Refused(f"{source.email} is connected read-only, so Rouh cannot send from it. "
                      "Copy the nudge into a reply instead.")
    if not source.can_send:
        raise Refused(f"Rouh's Google connection, {source.email}, was not allowed to send "
                      "mail. Connect it again in Settings, under Google.")
    held = await sync_to_async(_kept)(who, mailbox_id)
    item = next((one for one in ((held or {}).get("found") or {}).get("items") or []
                 if one["thread_id"] == thread and one["message_id"] == message), None)
    if item is None:
        raise Refused("That email is not on the list any more. Make the brief again.")
    clients = GoogleClients(auth.google_auth, cfg)
    gmail = Gmail(clients, who)
    try:
        got = await asyncio.wait_for(clients.call(
            who, "GET", clients.base("gmail") + "/gmail/v1/users/me/messages/"
            + urllib.parse.quote(message),
            params={"format": "metadata", "metadataHeaders": ["To", "Cc"]}), SCAN_SECONDS)
        own = {source.email.lower()}
        try:
            own |= set(await gmail.send_as())
        except Exception:
            pass
        to, cc = _nudge_to(_named(got), own, item.get("to") or [])
        if not to:
            raise Refused("There is nobody to send that nudge to.")
        wrote = await asyncio.wait_for(
            gmail.send(to, "", text, cc=cc, reply_to_message_id=message), SCAN_SECONDS)
    except Refused:
        raise
    except Exception as exc:
        log.info("a nudge from the brief was not sent: %r", exc)
        if isinstance(exc, (httpx.TransportError, asyncio.TimeoutError)):
            raise Refused("Google could not be reached. Try again in a moment.") from exc
        said = re.sub(r"\s+", " ", str(exc)).strip()[:220]
        raise Refused("Google refused it" + (f": {said}" if said else ".")) from exc
    from . import runtime

    audit = getattr(runtime, "google_audit", None)
    if audit is not None:
        audit.wrote("send_mail", wrote["to"],
                    f"Sent to {wrote['to']}" + (f", copying {wrote['cc']}" if wrote.get("cc")
                                                else "")
                    + f" - subject {wrote['subject']!r} - a nudge in the thread of {message}"
                    + f" - message id {wrote.get('id') or 'unknown'} - pressed on the brief",
                    user_id=who.user_id, org_id=who.org_id, account=source.email)

    def keep():
        from .models import GhostMark

        GhostMark.objects.update_or_create(
            user_id=who.user_id, org_id=who.org_id, mailbox_id=mailbox_id, thread_id=thread,
            defaults={"message_id": message, "state": "nudged", "until": 0.0,
                      "at": time.time()})

    await sync_to_async(keep)()
    return {"state": "nudged", "until": 0.0, "to": wrote["to"], "cc": wrote.get("cc") or "",
            "id": wrote.get("id") or ""}


# --- one email, read whole on the brief --------------------------------------------------


def _source_of(who, auth, mailbox_id) -> tuple[Source | None, list[dict]]:
    """This person's mailbox of that id, and the emails on its last look."""
    held = _kept(who, mailbox_id)
    if held is None:
        return None, []
    found = held.get("found") or {}
    source = next((one for one in sources(who, auth) if one.id == int(mailbox_id)), None)
    return source, (found.get("items") or []) + (found.get("unread") or [])


def whole(got: dict) -> dict:
    """A `format=full` message as the brief shows it: headers, the whole body, file names.

    The plain text wherever the sender's mail has one, quotes and all; the
    HTML only when it has nothing else, for the page to show in a frame that
    runs nothing.
    """
    from .google_api import _attachments, _message_bodies

    named = _named(got)
    plain, markup = _message_bodies(got.get("payload") or {})
    files = []
    for one in _attachments(got.get("payload") or {}):
        files.append({"name": str(one.get("name") or "")[:200], "size": one.get("size") or 0})
    return {"message_id": got.get("id") or "", "thread_id": got.get("threadId") or "",
            "from": named.get("from", ""), "to": named.get("to", ""),
            "cc": named.get("cc", ""), "subject": named.get("subject") or "(no subject)",
            "date": named.get("date", ""), "at": _at(got),
            "body": (plain or ("" if markup else html_module.unescape(got.get("snippet") or "")))
            [:MOST_BODY],
            "html": "" if plain else markup[:MOST_BODY],
            "files": [one for one in files if one["name"]]}


async def message(who, auth, cfg, mailbox_id, message_id: str) -> dict:
    """One email on the brief, read whole from its own mailbox with GET alone.

    Only one that is on that mailbox's last look, in a mailbox that is this
    person's own, so nothing else can be read through it. Reading it here does
    not mark it read in the mailbox.
    """
    from asgiref.sync import sync_to_async

    try:
        int(mailbox_id)
    except (TypeError, ValueError):
        raise Refused("That mailbox is not connected.")
    source, listed = await sync_to_async(_source_of)(who, auth, mailbox_id)
    if source is None:
        raise Refused("That mailbox is not connected.")
    if not any(one["message_id"] == message_id for one in listed):
        raise Refused("That email is not on the brief any more. Make the brief again.")
    reader = await sync_to_async(_reader)(who, auth, cfg, source)
    if reader is None:
        raise Refused("That mailbox is not connected.")
    try:
        got = await asyncio.wait_for(reader.message(message_id), SCAN_SECONDS)
    except Exception as exc:
        raise Refused(_say_trouble(exc, source.email or "This mailbox")) from exc
    return {**whole(got), "mailbox": source.id, "email": source.email}
