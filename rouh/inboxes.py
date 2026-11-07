"""Which inbox a mail tool acts on: Rouh's own, the person's own, or both.

Petar, 30 September 2026 (fr_b65028b03b05): "when I ask rouh to check if
anything in my mail is present, Rouh should know which is my mail. the one I
signed up with read-only permissions. Rouh has her own email [its own mailbox].
But rouh should have the tools to check and manipulate my mail too, just the
same. same tools, just check either or both inboxes."

So there are two kinds of inbox, and every mail tool takes which (`INBOX_ARG`):

- **Rouh's own** is the Google connection (`google_oauth.py`): `ROUH_OWN_MAILBOXES`
  on the live server, with every grant an assistant acts with.
- **The person's own** are the mailboxes they connected in Settings to be read
  (`mailboxes.py`), each granted `gmail.readonly` and nothing more. The one
  whose address is the account's own, the address they signed up with, is
  named first; any other they connected is theirs too. One of the same Google
  account as Rouh's connection is not a second inbox and is left out.

The person's inboxes are read through the very same `google_api.Gmail` the
tools read Rouh's with, over a stand-in for its clients that can only make the
GET requests a read-only mailbox makes (`ReadOnlyClients`), so a search, a
message and its files come back in the same shape from either. Anything that
writes - send, draft, forward, mark, label, archive, bin - is refused for the
person's inbox with a sentence that says why (`cannot_write`), before Google
is asked: `gmail.readonly` would refuse every one of them anyway, and the
grant is not widened here.

The one exception is forwarding, and only from a mailbox the person allowed
to forward from, in Settings (`mailboxes.can_forward`, 4 October 2026):
`forward_mail` and `forward_thread` open it with `open_to_forward`, over
`ForwardClients`, which reads and makes one `POST /messages/send` and refuses
everything else exactly as `ReadOnlyClients` does. Sending, drafting,
replying, marking and the rest stay refused for every inbox of theirs.

A turn about somebody else's email (`mail_turn`) never reads the person's own
inbox: a stranger's email is not a reason to look through the owner's mail. The one
exception is a trusted contact the owner opened it to, on their page or for one
email, and then only as far as they did (`rouh/inbox_grants.py`).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from . import owner

log = logging.getLogger("rouh.inboxes")

#: What a tool is told to act on.
ROUH, PERSON, BOTH = "rouh", "person", "both"

#: The argument every mail tool takes, as its schema says it.
INBOX_ARG = {
    "type": "string",
    "enum": [ROUH, PERSON, BOTH],
    "description": (
        "Whose inbox, from the person's own words. They say 'your inbox' or 'your "
        "mail' about yours, Rouh's own: \"rouh\". They say 'my inbox' or 'my mail' "
        "about their own, connected read-only: \"person\". 'My' and 'your' each name "
        "exactly one inbox, and that one alone is looked in. Only a question that "
        "names neither, such as 'did anything come in about the invoice', is "
        "\"both\", the default."),
}

#: The same for a tool that writes, where only Rouh's inbox can be written to.
INBOX_WRITE_ARG = {
    "type": "string",
    "description": (
        "Which inbox the message is in, when it came from read_recent_mail with an "
        "inbox: \"rouh\" (your own, the default) or \"person\" or one of the person's "
        "addresses. The person's inboxes are read-only: acting on one of their "
        "messages is refused, and you say so. The one exception is forward_mail and "
        "forward_thread from one of theirs they allowed forwarding from in Settings."),
}


def _own_mailboxes() -> tuple[str, ...]:
    from .inbox import own

    return own()


def which(value, *, default: str = BOTH) -> str:
    """The inbox asked for, as one of ROUH, PERSON, BOTH, or an address in lower case."""
    said = str(value or "").strip().lower()
    if not said:
        return default
    if said in (ROUH, "rou", "yours", "your", "own", "assistant", "rouh's") or \
            said in _own_mailboxes():
        return ROUH
    if said in (PERSON, "mine", "my", "user", "theirs", "owner", "person's") or \
            owner.word(said) == "owner":
        return PERSON
    if said in (BOTH, "all", "every", "either"):
        return BOTH
    if "@" in said:
        return said
    return default


# ---------------------------------------------------------------------------
# Wired in at start-up
# ---------------------------------------------------------------------------

#: `mailboxes.MailboxAuth` and the configuration, once runtime has made them.
_AUTH = None
_CFG = None


def use(auth, cfg) -> None:
    """Say what reads the person's mailboxes. Once, at start-up (`runtime.py`)."""
    global _AUTH, _CFG
    _AUTH, _CFG = auth, cfg


# ---------------------------------------------------------------------------
# Whose inbox is whose
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Theirs:
    """One of the person's own inboxes, as a tool names it. Never a token."""

    id: int
    email: str
    #: The address they signed up with, which is what "my mail" means first.
    account: bool
    needs_reconnect: bool = False
    #: The person allowed Rouh to forward from it (`mailboxes.can_forward`).
    can_forward: bool = False

    def said(self) -> str:
        return self.email or f"mailbox {self.id}"


def account_address(who) -> str:
    """The address on the person's account: the one they signed up with, or ""."""
    if who is None:
        return ""
    held = str(getattr(who, "email", "") or "").strip()
    if held:
        return held.lower()
    try:
        from .models import User

        found = (User.objects.filter(id=int(who.user_id)).values_list("email", flat=True)
                 .first())
    except Exception:  # noqa: BLE001 - an address is context, never worth a failure
        return ""
    return str(found or "").strip().lower()


def rouh_address(who) -> str:
    """The address of Rouh's own inbox, the Google connection, or ""."""
    if who is None:
        return ""
    try:
        from .models import GoogleConnection

        found = (GoogleConnection.objects.filter(user_id=who.user_id, org_id=who.org_id)
                 .values_list("google_email", flat=True).first())
    except Exception:  # noqa: BLE001
        return ""
    return str(found or "").strip().lower()


def theirs(who) -> list[Theirs]:
    """The person's own inboxes, the account's own address first.

    Asked for by owner, as every mailbox is (`mailboxes.MailboxStore.rows`).
    One of the same Google account as Rouh's connection is Rouh's inbox, not
    theirs, and is left out, as the brief's list leaves it out
    (`ghosts.sources`).
    """
    from .mailboxes import MailboxStore, can_forward
    from .models import GoogleConnection

    if who is None or not getattr(who, "user_id", "") or not getattr(who, "org_id", ""):
        return []
    rouhs = set(GoogleConnection.objects.filter(user_id=who.user_id, org_id=who.org_id)
                .values_list("google_account", flat=True))
    mine = account_address(who)
    out = [Theirs(row.id, row.email or "", bool(mine) and (row.email or "").lower() == mine,
                  bool(row.needs_reconnect), can_forward(row.scopes or ""))
           for row in MailboxStore.rows(who) if row.google_account not in rouhs]
    return sorted(out, key=lambda one: not one.account)


def picked(who, asked: str) -> tuple[list[Theirs], str]:
    """The person's inboxes a tool is to read, and a sentence when there are none.

    `asked` is PERSON (all of theirs) or one address, from `which`. Rouh's own
    address asked for as an address is not theirs, and is said so.
    """
    held = theirs(who)
    mine = account_address(who)
    if not held:
        where = f" ({mine})" if mine else ""
        return [], (f"The person's own inbox{where} is not connected, so it cannot be read. "
                    "They connect it in Settings, under Read-only mailboxes.")
    if asked in (PERSON, BOTH):
        return held, ""
    found = [one for one in held if one.email.lower() == asked]
    if found:
        return found, ""
    return [], (f"{asked} is not one of the person's connected inboxes. Theirs are "
                + ", ".join(one.said() for one in held) + ".")


def prompt_line(who=None) -> str:
    """Which inbox is whose, for the system prompt: the addresses, and what each allows.

    For whoever the turn is for (`tenancy.speaker`), and on an install with one
    person on it, that person, as the tools themselves decide (`GoogleDesk.person`).
    """
    if who is None:
        try:
            from .tenancy import Tenancy, speaker

            who = speaker() or Tenancy().only_person()
        except Exception:  # noqa: BLE001
            who = None
    if who is None:
        return ""
    try:
        rouhs = rouh_address(who)
        held = theirs(who)
        mine = account_address(who)
    except Exception:  # noqa: BLE001 - a line of context is never worth a turn
        log.exception("the inboxes could not be read for the prompt")
        return ""
    lines = ["Inboxes: there are two, and every mail tool takes inbox for which. Yours, "
             "Rouh's own" + (f", {rouhs}" if rouhs else "") + ", is inbox \"rouh\": when "
             "the person says 'your inbox' or 'your mail' they mean this one, and you can "
             "read, send, draft, forward, mark, label, archive and bin in it."]
    if held:
        named = ", ".join(one.said() + (" (the address on their account)" if one.account
                                         else "") for one in held)
        lines.append(f"The person's own is {named}, inbox \"person\": when they say 'my "
                     "inbox' or 'my mail' they mean this one. It is connected read-only: "
                     "you can search and read it, and nothing that changes it is possible, "
                     "so say so if asked.")
        forwards = [one.said() for one in held if one.can_forward]
        if forwards:
            lines.append("They also allowed forwarding from " + ", ".join(forwards)
                         + ": forward_mail and forward_thread with that inbox send the "
                         "forward from it, as them. Nothing else can be sent from it.")
        else:
            lines.append("Forwarding from theirs is not allowed yet: forwarding one of "
                         "their emails needs Allow forwarding beside it in Settings, under "
                         "Read-only mailboxes.")
    else:
        lines.append("The person's own inbox" + (f", {mine}," if mine else "")
                     + " is not connected, so 'my mail' can only be answered from yours: "
                     "say so, and that it is connected under Settings > Read-only "
                     "mailboxes.")
    lines.append("'My' and 'your' each name exactly one inbox: look in that one alone, "
                 "never both. Only when they name neither, as in 'did anything come in "
                 "about the invoice', use inbox \"both\". Whenever you answer from mail, say which inbox each "
                 "email is in, aloud and on the screen.")
    return " ".join(lines)


# ---------------------------------------------------------------------------
# Reading the person's inbox with the tools' own Gmail
# ---------------------------------------------------------------------------


class CannotWrite(RuntimeError):
    """A write asked of an inbox that is read-only. Its words are said as they are."""


def cannot_write(address: str, what: str) -> str:
    """Why `what` cannot be done in the person's inbox, in words to say."""
    return (f"{address or 'This inbox'} is the person's own inbox, connected read-only: it "
            f"can be searched and read, but Rouh cannot {what} there, because Google "
            "refuses every change to it. Nothing was done. They can do it in Gmail "
            "themselves, or it can be done from Rouh's own inbox if the email is there too.")


def cannot_forward(address: str) -> str:
    """Why an email cannot be forwarded from the person's inbox yet, in words to say."""
    return (f"{address or 'Their inbox'} is connected read-only, and forwarding from it has "
            "not been allowed, so nothing was sent. To allow it, they open Settings, find "
            f"Read-only mailboxes and press Allow forwarding beside {address or 'it'}: Google "
            "then asks them to let Rouh send email as that account, and nothing else changes. "
            "Then ask again.")


class ReadOnlyClients:
    """What `google_api.Gmail` asks of its clients, answered by a read-only mailbox.

    GET only. Anything else is refused here, before Google is asked.
    """

    MARK = "/gmail/v1/users/me"

    def __init__(self, reader) -> None:
        self._reader = reader

    def base(self, service: str) -> str:
        return ""

    async def call(self, who, method: str, url: str, *, params=None, **_):
        if method.upper() != "GET":
            raise CannotWrite(cannot_write(self._reader.mailbox.email, "change anything"))
        path = url.split(self.MARK, 1)[1] if self.MARK in url else url
        return await self._reader.get(path, params)


class ForwardClients(ReadOnlyClients):
    """The same, for a mailbox the person allowed to forward from.

    Reads as `ReadOnlyClients` does, and makes exactly one other request: the
    `POST /messages/send` a forward ends with, which `google_api.Gmail.forward`
    and `forward_thread` mark as one (`forward=True`). A new email, a reply or
    a draft goes through the very same `Gmail` methods without that mark, and
    is refused here like every other write, before Google is asked.
    """

    SEND = ReadOnlyClients.MARK + "/messages/send"

    async def call(self, who, method: str, url: str, *, params=None, json_body=None,
                   seconds: float = 0.0, forward: bool = False, **more):
        if method.upper() == "POST" and url.endswith(self.SEND) and forward and not params:
            return await self._reader.send(json_body or {}, seconds=seconds)
        return await super().call(who, method, url, params=params, **more)


class Opened:
    """One of the person's inboxes, open to be read with `google_api.Gmail`."""

    def __init__(self, one: Theirs, gmail) -> None:
        self.inbox = one
        self.gmail = gmail


def open_one(who, one: Theirs) -> Opened:
    """`one` as a `google_api.Gmail` that can only read. Sync: it reads the row."""
    from .google_api import Gmail
    from .mailboxes import NotConnected, ReadOnlyGmail

    if _AUTH is None:
        raise NotConnected("The person's own inboxes cannot be read on this machine.")
    mailbox = _AUTH.store.mailbox(who, one.id)
    if mailbox is None:
        raise NotConnected(f"{one.said()} is not connected any more.")
    reader = ReadOnlyGmail(_AUTH, mailbox, _CFG)
    return Opened(one, Gmail(ReadOnlyClients(reader), who))


def open_to_forward(who, one: Theirs) -> Opened:
    """`one` as a `google_api.Gmail` that reads and forwards. Sync: it reads the row.

    Raises `CannotWrite` with `cannot_forward` when the person has not
    allowed forwarding from it, so nothing is asked of Google.
    """
    from .google_api import Gmail
    from .mailboxes import ForwardingGmail, NotConnected, can_forward

    if _AUTH is None:
        raise NotConnected("The person's own inboxes cannot be reached on this machine.")
    mailbox = _AUTH.store.mailbox(who, one.id)
    if mailbox is None:
        raise NotConnected(f"{one.said()} is not connected any more.")
    if not can_forward(mailbox.scopes):
        raise CannotWrite(cannot_forward(mailbox.email))
    reader = ForwardingGmail(_AUTH, mailbox, _CFG)
    return Opened(one, Gmail(ForwardClients(reader), who))


def ready() -> bool:
    return _AUTH is not None


__all__ = ["BOTH", "INBOX_ARG", "INBOX_WRITE_ARG", "PERSON", "ROUH", "CannotWrite",
           "ForwardClients", "Opened", "ReadOnlyClients", "Theirs", "account_address",
           "cannot_forward", "cannot_write", "open_one", "open_to_forward", "picked", "prompt_line", "ready", "rouh_address", "theirs", "use",
           "which"]
