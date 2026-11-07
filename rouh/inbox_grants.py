"""The owner's own inbox, read for a trusted contact: how far, held to it, and written down.

Petar, 2 October 2026, about a trusted contact who works with him: she
held every level and the topics legal, money and private data, and still every
request of hers that needed his inbox failed twice over - the assessment could
only call it "other", which nothing granted, and the mail tools refused every
read with "A turn about somebody else's email never reads [the owner's] own inbox".
So each trusted contact has "Your inbox - how far" on their page
(`trusted.INBOX_SCOPES`), and a case's turns may read his inbox exactly that
far for them, and no further. He can also allow it for one email when asked
(`mail_cases.CaseDesk.decide`), which is kept on the case (`MailCase.inbox_grant`).

What each reach lets a turn of the case do, held here and not by the model:

- **This search only**: one search. The first one the case runs is the one
  (or the one the owner was shown when they allowed it); it may be run again, and
  only messages it found may be opened.
- **This thread**: the same one search, and then every message of the thread
  of the first message opened from it.
- **A sender or label**: searches are narrowed to those senders and labels in
  Gmail's own words, and a message is opened only if that search found it or
  it is from one of those senders.
- **Full read**, and **Full read and write**: everything. Nothing is held back.
  Write cannot change anything yet: his inbox is connected read-only
  (`writable`), and sending as him, deleting and forwarding outside are never
  done by a case at all (`mail_turn.NEVER_IN_CASE`).

Every search, message and file read this way is a row of `InboxRead` against
the contact (`log`), and their page shows the latest ones (`latest`).

Everybody else - an implicit sender, a contact switched off, a contact with
None - is refused exactly as before (`tools.ToolRegistry._whose`).
"""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field

from . import trusted as trust

log = logging.getLogger("rouh.inbox_grants")

#: How many reads a contact's page shows.
LATEST = 12


@dataclass
class Access:
    """How far one case's turns may read the owner's inbox, and what they have used of it."""

    user_id: str
    org_id: str
    contact_id: int
    name: str
    case_id: int
    case_key: str
    scope: str
    entries: list[str] = field(default_factory=list)
    #: "standing" (the contact's page) or "once" (this email, when he was asked).
    source: str = "standing"
    #: The one search a SEARCH or THREAD reach is bound to, what it found, and
    #: the thread a THREAD reach is bound to.
    search: str = ""
    ids: list[str] = field(default_factory=list)
    thread: str = ""

    def said(self) -> str:
        return trust.inbox_said(self.scope, self.entries) + (
            " (allowed once, for this email)" if self.source == "once" else "")

    # --- searching ------------------------------------------------------------------

    def narrowed(self, query: str) -> tuple[str, str]:
        """The search to run for `query`, and a refusal when it may not run at all."""
        query = " ".join(str(query or "").split())
        if self.scope in (trust.INBOX_READ, trust.INBOX_WRITE):
            return query, ""
        if self.scope == trust.INBOX_SENDERS:
            reach = " ".join(_gmail_term(one) for one in self.entries)
            if not reach:
                return "", self._outside("no sender or label is named for it")
            return (f"({query}) {{{reach}}}" if query else f"{{{reach}}}"), ""
        if not self.search or _same(self.search, query):
            return query, ""
        if self.scope == trust.INBOX_THREAD and self.thread:
            return query, ""              # only the bound thread's messages come back
        return "", self._outside(f"it allows one search of the inbox for this email, which "
                                 f"was \"{self.search}\"; only that search runs again")

    def kept(self, found: list[dict]) -> list[dict]:
        """What a search found that this reach may show."""
        if self.scope == trust.INBOX_THREAD and self.thread:
            return [m for m in found if m.get("thread_id") == self.thread]
        if self.scope == trust.INBOX_SENDERS and not any(
                e.startswith("label:") for e in self.entries):
            return [m for m in found if self._from_reached(m.get("from"))]
        return found

    def searched(self, query: str, found: list[dict]) -> None:
        """Bind the one search, and remember what it found. The case's row is written."""
        query = " ".join(str(query or "").split())
        if self.scope in (trust.INBOX_SEARCH, trust.INBOX_THREAD) and not self.search:
            self.search = query
        if self.scope in (trust.INBOX_SEARCH, trust.INBOX_THREAD, trust.INBOX_SENDERS):
            self.ids = list(dict.fromkeys([*self.ids, *(str(m.get("id") or "")
                                                        for m in found if m.get("id"))]))[-200:]
        self._keep()

    # --- opening one message ------------------------------------------------------------

    def may_open(self, message: dict) -> str:
        """"" when this message may be read for them, or why not. A THREAD reach binds here."""
        if self.scope in (trust.INBOX_READ, trust.INBOX_WRITE):
            return ""
        ident = str(message.get("id") or "")
        thread = str(message.get("thread_id") or "")
        if self.scope == trust.INBOX_SENDERS:
            if ident in self.ids or self._from_reached(message.get("from")):
                return ""
            return self._outside("that message is not from a sender, or under a label, "
                                 "it names")
        if self.scope == trust.INBOX_THREAD:
            if self.thread and thread == self.thread:
                return ""
            if ident in self.ids and not self.thread:
                self.thread = thread
                self._keep()
                return ""
            return self._outside("it allows one thread, and that message is not in it"
                                 if self.thread else
                                 "only messages its one search found may be opened")
        if ident in self.ids:
            return ""
        return self._outside("only messages its one search found may be opened"
                             + (f" (\"{self.search}\")" if self.search else
                                ", and no search has been run yet"))

    # --- what it says, and what it keeps -------------------------------------------------

    def _from_reached(self, sender) -> bool:
        from .mail_alerts import address_of

        address = trust.clean_address(address_of(str(sender or "")))
        if not address:
            return False
        domain = "@" + address.split("@", 1)[1]
        return any(e == address or e == domain for e in self.entries)

    def _outside(self, why: str) -> str:
        return (f"‹owner›'s inbox is open to {self.name} only as far as {self.said()}, and {why}. "
                "Nothing was read. If answering needs more of ‹his› inbox, do not work round "
                "it: name inbox in needs and the reach it takes in inbox_scope, say in "
                "proposed_action exactly what you would read, and report with case_report; "
                "Rouh asks ‹owner›, or declines, as ‹he› set.")

    def _keep(self) -> None:
        from .models import MailCase

        try:
            row = MailCase.objects.filter(user_id=self.user_id, org_id=self.org_id,
                                          id=self.case_id).values("inbox_grant").first()
            if row is None:
                return
            grant = dict(row["inbox_grant"] or {})
            grant["used"] = {"search": self.search, "ids": self.ids, "thread": self.thread}
            MailCase.objects.filter(user_id=self.user_id, org_id=self.org_id,
                                    id=self.case_id).update(inbox_grant=grant)
        except Exception:  # noqa: BLE001 - kept again on the next read
            log.exception("could not keep what case %s used of the inbox", self.case_id)


def _same(a: str, b: str) -> bool:
    return " ".join(str(a or "").lower().split()) == " ".join(str(b or "").lower().split())


def _gmail_term(entry: str) -> str:
    """One sender or label in Gmail's search words."""
    if entry.startswith("label:"):
        name = re.sub(r"[\s/]+", "-", entry[6:].strip().lower())
        return f"label:{name}"
    if entry.startswith("@"):
        return f"from:{entry[1:]}"
    return f"from:{entry}"


def for_case(user_id: str, org_id: str, trusted_id, case_id) -> Access | None:
    """How far the case's turns may read the owner's inbox, or None for not at all.

    Only a listed contact who is switched on: the wider of what their page
    says and what the owner allowed for this one email.
    """
    from .models import MailCase

    if not trusted_id or not user_id or not org_id:
        return None
    contact = trust.TrustStore().get(user_id, org_id, trusted_id)
    if contact is None or contact.implicit or not contact.trusted:
        return None
    row = (MailCase.objects.filter(user_id=user_id, org_id=org_id, id=case_id)
           .values("key", "inbox_grant").first()) if case_id else None
    grant = dict((row or {}).get("inbox_grant") or {})
    scope, entries, source = contact.inbox_scope, list(contact.inbox_from), "standing"
    once = grant.get("once") or {}
    wanted = str(once.get("scope") or "")
    if wanted in trust.INBOX_SCOPES and \
            trust.INBOX_RANK[wanted] > trust.INBOX_RANK.get(scope, 0):
        scope, entries, source = wanted, [str(e) for e in once.get("from") or []], "once"
    if scope == trust.INBOX_NONE:
        return None
    used = grant.get("used") or {}
    search = str(used.get("search") or "") or (str(once.get("search") or "")
                                               if source == "once" else "")
    return Access(user_id=user_id, org_id=org_id, contact_id=contact.id, name=contact.name,
                  case_id=int(case_id or 0), case_key=str((row or {}).get("key") or ""),
                  scope=scope, entries=entries, source=source, search=search,
                  ids=[str(i) for i in used.get("ids") or []],
                  thread=str(used.get("thread") or ""))


def for_turn(turn) -> Access | None:
    """`for_case` for a case's turn (`mail_turn.MailTurn`); None for any other turn."""
    if turn is None or not getattr(turn, "mode", "") or getattr(turn, "from_owner", False):
        return None
    return for_case(turn.user_id, turn.org_id, turn.trusted_id, turn.case_id)


def scope_of(user_id: str, org_id: str, trusted_id) -> str:
    """The contact's standing reach, for a refusal's words. "" for none."""
    contact = trust.TrustStore().get(user_id, org_id, trusted_id) if trusted_id else None
    return contact.inbox_scope if contact is not None and contact.trusted else ""


def logged(access: Access, kind: str, *, inbox: str, query: str = "", message: dict | None = None,
           found: int = 0) -> None:
    """One read of the owner's inbox, written down against the contact. Never raises."""
    from .models import InboxRead

    message = message or {}
    try:
        InboxRead.objects.create(
            user_id=access.user_id, org_id=access.org_id, contact_id=access.contact_id,
            case_id=access.case_id, case_key=access.case_key, at=time.time(), kind=kind,
            inbox=inbox[:300], query=str(query or "")[:500],
            message_id=str(message.get("id") or "")[:200],
            subject=str(message.get("subject") or "")[:300],
            sender=str(message.get("from") or "")[:300], found=int(found or 0),
            scope=access.scope, source=access.source)
    except Exception:  # noqa: BLE001 - the read is said all the same; the log line says why not
        log.exception("could not log a read of the inbox for contact %s", access.contact_id)


def latest(user_id: str, org_id: str, trusted_id, *, limit: int = LATEST) -> list[dict]:
    """The latest reads done for one contact, newest first, for their page."""
    from . import clock
    from .models import InboxRead

    rows = (InboxRead.objects.filter(user_id=user_id, org_id=org_id, contact_id=trusted_id)
            .order_by("-at", "-id")[:limit])
    out = []
    for row in rows:
        moment = clock.moment(row.at)
        if row.kind == "search":
            what = (f"Searched \"{row.query}\"" if row.query else "Listed the newest mail") \
                + f": {row.found} found"
        else:
            what = ("Read a file of " if row.kind == "file" else "Read ") + \
                (f"\"{row.subject}\"" if row.subject else f"message {row.message_id}") + \
                (f" from {row.sender}" if row.sender else "")
        out.append({"when": f"{moment.day} {moment:%b, %H:%M}", "what": what,
                    "inbox": row.inbox, "scope": trust.INBOX_SCOPES.get(row.scope, ("",))[0],
                    "once": row.source == "once",
                    "case": f"/mail/case/{row.case_key}" if row.case_key else ""})
    return out


def writable(who) -> bool:
    """Whether the owner's own inbox can be changed for anybody. Not yet: always False.

    His inboxes are connected with `gmail.readonly` and nothing wider
    (`mailboxes.READ_SCOPES`), and opened through a stand-in that makes GET
    requests only (`inboxes.ReadOnlyClients`). Until Gmail is reconnected with
    write access and that is widened, "Full read and write" reads like Full
    read, and its page says so (`READ_ONLY_NOTE`) rather than pretending.
    """
    return False


#: What the page says beside "Full read and write" while nothing can be written.
READ_ONLY_NOTE = ("Your inbox is connected read-only, so this cannot change anything in it "
                  "yet: Rouh can read it, as with Full read. Labelling, archiving and drafting "
                  "work once Gmail is reconnected with write access.")


__all__ = ["Access", "READ_ONLY_NOTE", "for_case", "for_turn", "latest", "logged", "scope_of",
           "writable"]
