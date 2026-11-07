"""Who the owner trusts Rouh to deal with by email, for what, and what is never routine.

Petar, 30 September 2026: "Let me explicitly mark and unmark individual
contacts as trusted, review the exact email addresses covered, and define
allowed request and action categories per contact. Groups may organise triage
queues, but group membership must not grant trust or permissions." The same
evening the categories became three levels (`LEVELS`), and access to his tasks
a picker over Work, Personal and Rouh, by project and by task (`grant_tree`).

Three rules hold everything here:

- **Trust is per contact, pressed by the owner, and per exact address.** A sender
  is trusted only when the address in the From line, lower case, is one he
  ticked for a contact he switched on (`TrustStore.trusted_for`). A new address
  on the same person's card is not covered until he ticks it; a look-alike
  address, the same name at another domain, is nobody.
- **A group grants nothing.** `ContactGroup` is where a case's approval is
  listed and nothing else. No function here or in `mail_cases.py` reads a
  group to decide whether somebody is trusted or what they may ask for.
- **What they may have done is code, from grants.** Since 11 October 2026 a
  message is split into its asks, each mapped by the reading to a grant, a
  proposed grant or a hard limit, and code decides from what the contact holds
  (`rouh/mail_ledger.py`). No word list, no topic and no model's opinion
  decides whether something waits for the owner (`MAIL.md`, D2). The risk word
  lists, the allowed topics, the reply checks and the status option that
  stood here until then are gone.

- **The owner's own inbox is a setting of its own, per contact.** Petar, 2 October
  2026: "Your inbox - how far" (`INBOX_SCOPES`), None until he sets it, and
  "When a request goes beyond all this" (`BEYOND`): ask him, or decline it,
  which is his standing no (`mail_ledger.judge`). An ask that needs his inbox
  names the grant inbox, and the reach the contact holds covers it or not; the
  mail tools hold every read to the reach and write it down
  (`rouh/inbox_grants.py`).

- **What can be given is data, and an email is judged ask by ask.** Petar, 11
  October 2026: the levels and the inbox are grants among others, rows per
  organisation with a name, a description and the prompt the reading is given,
  in a tree where a parent brings its sub grants (`rouh/grants.py`); Clockwork,
  Memory and Shared task joined them. The reading splits an email into its asks
  and names the grant that covers each, or proposes a new one; asks inside what
  the contact holds go on at once, and only the rest wait for him
  (`mail_ledger.judge`). The old catch-all, "outside_grant", is gone (`OLD_CATCH_ALL`).
  Hard limits are never a grant (`grants.HARD_LIMITS`).

- **A contact may decide for the owner over named work** (`rouh/delegation.py`,
  `DELEGATION.md`). Petar, 9 October 2026: a goal, a quest or a task he gives
  them authority over is theirs to decide - its decisions, steps, plan and
  quest - by email, checked at every action; money, deleting, publishing,
  sending, committing him and Rouh itself stay his. It is the top level of the
  one permission record (`rouh/task_access.py`): deciding includes editing and
  reading, everywhere they are let in.

**Everybody else has the baseline.** Petar, 30 September 2026, when the two
ways of handling other people's email became one (`rouh/mail_cases.py`):
"Rouh should be able to handle the normal communication with vendors, partners
etc. I will approve people only if I want to grant them extra data, Rouh
capabilities etc." So a sender who is not listed here is an implicit contact
with `BASELINE` - communication only (`implicit`). A contact listed here and switched off is not
implicit: everything from them waits for him, as the page says.

Every query names the person and the organisation (`AGENTS.md`, "Whose data is
it").
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass, field

#: What the owner can grant a trusted contact, each level adding to the one before
#: it (`with_lower`). Petar, 30 September 2026: "First of all I need to grant
#: them the basic stuff - communication. Another layer is to grant them access
#: to my tasks data. Another layer is to allow them to use Rouh for themselves
#: without changing it." Inside what is granted, nothing waits for him: "Not if
#: I have granted them the permissions."
LEVELS: dict[str, tuple[str, str]] = {
    "communicate": ("Communication",
                    "Rouh writes back to them freely: answers, acknowledgements, messages to "
                    "and from you, logistics you have already agreed. Nothing from your "
                    "work, and nothing private."),
    "tasks": ("Your tasks",
              "They may open what the tree below gives them, in Rouh, by email and by message, "
              "and Rouh answers from it: everything in a ticked column or project, and each "
              "task, quest or goal at the level beside it."),
    "use": ("Rouh for themselves",
            "They ask, by email or a message, and Rouh does the work in your workspace as if "
            "you had asked, filed as your task with a Guest label, and sends them the result. "
            "A task they start is theirs to edit. "
            "Background jobs included. It never changes Rouh itself, and never sends, "
            "changes or acts as you in your mail, calendar, contacts or memory. Reading your "
            "inbox for them is the separate setting below, Your inbox - how far."),
}
ORDER = tuple(LEVELS)

#: What everybody who is not a trusted contact has: Rouh answers them, and no
#: more. Trusting somebody is how they get the owner's tasks, or Rouh for themselves.
BASELINE = ("communicate",)

#: The tools each level adds to a case's turn beyond what every turn about an
#: email may read (`mail_turn.MAY_USE`). A case's own two tools
#: (`read_granted_tasks`, `share_granted_page`) only ever reach what was
#: granted; the job a guest may start is the workspace's own (`assistant_job`),
#: never Rouh's code.
LEVEL_TOOLS: dict[str, tuple[str, ...]] = {
    "communicate": (),
    "tasks": ("read_granted_tasks", "share_granted_page"),
    "use": ("assistant_job", "check_tasks", "look_at_task", "make_picture",
            "change_picture"),
}

#: The tag a task done for a guest carries in its meta, beside
#: `"guest": "<their address>"`.
GUEST_TAG = "guest"


def with_lower(levels) -> list[str]:
    """Levels as granted: known ones only, and every level below the highest."""
    got = {str(one or "").strip().lower() for one in levels or ()}
    top = max((ORDER.index(one) for one in got if one in ORDER), default=-1)
    return list(ORDER[:top + 1])


#: How far Rouh may read the owner's own inbox for a contact. Petar, 2 October
#: 2026, about a trusted contact who works with him: she held every level
#: and topic, and still every request that needed his inbox failed, because no
#: level opened it and the turn refused to read it. So it is a setting of its
#: own on each contact's page, None until he sets it, each step wider than the
#: one before (`INBOX_RANK`). Full read means full read: nothing in it is held
#: back - he rejected any "left out even at full read" list. Writing is granted
#: by the last step, but sending as him, deleting and forwarding his mail
#: outside are hard limits (`grants.HARD_LIMITS`), and his inbox is
#: connected read-only (`mailboxes.READ_SCOPES`), so nothing in it can change
#: until Gmail is reconnected with write access.
#:
#: "This thread" is only ever an answer to one question about one email
#: (`mail_cases.CaseDesk.decide`), never a standing setting (`INBOX_STANDING`).
INBOX_NONE, INBOX_SEARCH, INBOX_THREAD, INBOX_SENDERS, INBOX_READ, INBOX_WRITE = (
    "none", "search", "thread", "senders", "read", "write")
INBOX_SCOPES: dict[str, tuple[str, str]] = {
    INBOX_NONE: ("None", "Rouh never reads your inbox for them."),
    INBOX_SEARCH: ("This search only", "For each request, Rouh runs the one search it needs in "
                                       "your inbox, and reads only what that search found."),
    INBOX_THREAD: ("This thread", "One conversation in your inbox: the search that finds it, "
                                  "and every message in that thread."),
    INBOX_SENDERS: ("A sender or label", "Only mail from the senders, or under the labels, "
                                         "you name."),
    INBOX_READ: ("Full read", "Rouh searches and reads all of your inbox for them, sent mail "
                              "included. Nothing is held back."),
    INBOX_WRITE: ("Full read and write", "Full read, and labelling, archiving and drafting in "
                                         "your inbox. Sending as you, deleting and forwarding "
                                         "your mail outside still ask you every time."),
}
INBOX_RANK = {key: n for n, key in enumerate(INBOX_SCOPES)}
INBOX_STANDING = (INBOX_NONE, INBOX_SEARCH, INBOX_SENDERS, INBOX_READ, INBOX_WRITE)

#: What happens to a request that goes beyond everything set on the contact's
#: page: their grants and inbox. Petar, 2 October 2026. Declining is his standing no.
BEYOND: dict[str, tuple[str, str]] = {
    "ask": ("Ask me", "What needs a grant they do not hold waits for you, ask by ask."),
    "decline_tell": ("Decline it and tell me", "What needs a grant they do not hold is "
                                               "declined, and their answer says you decided "
                                               "not to; the case shows it."),
    "decline": ("Decline it", "What needs a grant they do not hold is declined, and their "
                              "answer says you decided not to."),
}

#: The catch-all the reading named until 11 October 2026, "outside_grant", which no grant
#: could ever cover, so a whole email waited on it. It is gone; old cases still say it.
OLD_CATCH_ALL = "outside_grant"

def clean_inbox_scope(value, *, standing: bool = True) -> str:
    """An inbox scope as kept, or ValueError. "" and None are None."""
    key = str(value or INBOX_NONE).strip().lower()
    if key not in (INBOX_STANDING if standing else INBOX_SCOPES):
        raise ValueError("That is not one of the choices for your inbox.")
    return key


def clean_inbox_from(values) -> list[str]:
    """The senders and labels a "A sender or label" scope reaches, or ValueError.

    Each is an exact address, "@domain" for everybody at a domain (a bare
    domain is read as that), or "label:Name" for a Gmail label. Lower case
    for addresses, as written for labels.
    """
    if isinstance(values, str):
        values = [values]
    parts = [p for raw in values or () for p in re.split(r"[\n,;]+", str(raw or ""))]
    out: list[str] = []
    for raw in parts:
        one = " ".join(str(raw or "").split())
        if not one:
            continue
        if one.lower().startswith("label:"):
            name = one[6:].strip().strip('"')
            if not name:
                raise ValueError("Name the label after label:, such as label:Investors.")
            one = "label:" + name[:100]
        else:
            low = one.lower()
            if low.startswith("@"):
                low = low[1:]
            if "@" in low:
                if not clean_address(low):
                    raise ValueError(f"{one} is not an email address.")
                one = low
            elif re.fullmatch(r"[a-z0-9-]+(\.[a-z0-9-]+)+", low):
                one = "@" + low
            else:
                raise ValueError(f"{one} is not an address, a domain like @example.com, or a "
                                 "label like label:Investors.")
        if one not in out:
            out.append(one)
    return out[:40]


def clean_beyond(value) -> str:
    key = str(value or "ask").strip().lower()
    if key not in BEYOND:
        raise ValueError("That is not one of the choices for a request beyond all this.")
    return key


def clean_zone(value) -> str:
    """A time zone as kept: an IANA name that is one ("Europe/Lisbon"), or "" for none. ValueError
    for anything else."""
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    name = str(value or "").strip()
    if not name:
        return ""
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError(f"{name} is not a time zone: write it like Europe/Lisbon.") from None
    return name


def inbox_said(scope: str, entries=()) -> str:
    """An inbox scope in a few words, with what it reaches."""
    name = INBOX_SCOPES.get(scope, (scope,))[0]
    if scope == INBOX_SENDERS and entries:
        return f"{name}: " + ", ".join(entries)
    return name


def clean_address(value: str) -> str:
    """An address as trust compares it: lower case, trimmed, or "" when it is not one."""
    one = str(value or "").strip().lower()
    if one.count("@") != 1 or any(c.isspace() for c in one) or len(one) > 254:
        return ""
    local, domain = one.split("@")
    return one if local and "." in domain and not domain.startswith(".") else ""


@dataclass
class Trusted:
    """A trusted contact as the mail pipeline reads it."""

    id: int
    name: str
    contact_id: str
    trusted: bool
    levels: list[str]
    addresses: list[str]
    #: The projects and tasks they may read, by object id (level "tasks").
    grants: list[str] = field(default_factory=list)
    #: How far Rouh may read the owner's own inbox for them (`INBOX_SCOPES`), and
    #: for "A sender or label" which ones (`clean_inbox_from`).
    inbox_scope: str = INBOX_NONE
    inbox_from: list[str] = field(default_factory=list)
    #: What happens to a request beyond all this (`BEYOND`).
    beyond: str = "ask"
    #: Where they live, as an IANA name, or "" (Petar, 11 October 2026): a date they give is
    #: read on this clock (`TrustedContact.zone`).
    zone: str = ""
    #: The silos of the owner's life Rouh may bring up for them (`rouh/silos.py`), as silo keys, or
    #: None for the silos shown to others until they say (Work, to start with).
    sees: list | None = None
    group_id: int | None = None
    group_name: str = ""
    revision: int = 1
    note: str = ""
    updated_at: float = 0.0
    extra: dict = field(default_factory=dict)
    #: Not on the Trusted contacts page at all: somebody with `BASELINE` only.
    implicit: bool = False
    #: Their own Telegram accounts, linked by them and confirmed by the owner
    #: (`rouh/telegram_guests.py`), each as the sender a case names it by:
    #: "telegram:<Telegram's id for the account>".
    telegram: list[str] = field(default_factory=list)
    #: Their Slack accounts in the connected workspace (`rouh/slack.py`): each member whose address,
    #: which Slack confirmed, is one the owner ticked for them, as the sender a case names it by:
    #: "slack:<Slack's id for the member>".
    slack: list[str] = field(default_factory=list)
    #: The grants given them as rows (`grants.give`), by key: Clockwork, Memory, Shared task
    #: and any the owner made. Their levels and inbox are above.
    extra_grants: list[str] = field(default_factory=list)
    #: Their grants as data (`rouh/capability_grants.py`, CAPABILITIES.md): each in force or
    #: suspended, as `capabilities.authorize` reads it.
    cap_grants: list[dict] = field(default_factory=list)
    #: The grants they hold whose words changed since they were seeded, or that were given as
    #: rows, each "key@revision" (`grants.Tree.held`): a grant widened or given re-reads what
    #: of theirs waits, exactly as a change on their page does.
    held_sig: list[str] = field(default_factory=list)
    #: The tasks an answer to them may read, when others read it too: those every one of them may
    #: read (`slack_team.narrowed`, a Slack channel). None is no narrowing.
    within: frozenset | None = None

    def recognises(self, sender: str) -> bool:
        """Whether a case's sender is exactly one of theirs: an address the owner
        ticked, a Telegram account linked to them, or a Slack account with one of
        those addresses."""
        return bool(sender) and (sender in self.addresses or sender in self.telegram
                                 or sender in self.slack)

    def snapshot(self) -> dict:
        """What trust stood at, for a case's trace. The group is left out on purpose:
        moving a contact between queues changes nothing it may do."""
        shot = {"id": self.id, "trusted": self.trusted, "revision": self.revision,
                "implicit": self.implicit,
                "levels": list(self.levels), "grants": sorted(self.grants),
                "addresses": sorted(self.addresses)}
        # The inbox and the beyond setting, only when set.
        if self.inbox_scope != INBOX_NONE:
            shot["inbox"] = [self.inbox_scope, *self.inbox_from]
        if self.beyond != "ask":
            shot["beyond"] = self.beyond
        # And Telegram, which came last: a link made or undone is a change of
        # who they are recognised as, so an approval asked before it lapses.
        if self.telegram:
            shot["telegram"] = sorted(self.telegram)
        # And Slack, the same way, only when there is one, so every snapshot from before matches.
        if self.slack:
            shot["slack"] = sorted(self.slack)
        # And the grants, since 11 October 2026: only when one was given as a row or its
        # words changed, so every snapshot from before still matches.
        if self.held_sig:
            shot["held"] = sorted(self.held_sig)
        return shot

    def tools(self) -> tuple[str, ...]:
        return tuple(t for level in self.levels for t in LEVEL_TOOLS.get(level, ()))


def implicit(address: str, name: str = "", contact_id: str = "") -> Trusted:
    """Somebody the owner has not listed: this one address, with `BASELINE` and nothing else.

    `contact_id` is who Rouh knows them as (`people.Person.id`), for what he
    said about them; it grants nothing.
    """
    address = clean_address(address)
    return Trusted(id=0, name=name or address or "somebody", contact_id=contact_id or "",
                   trusted=False, levels=list(BASELINE), addresses=[address] if address else [],
                   implicit=True)


def fingerprint(*parts) -> str:
    """A stable hash of anything JSON can hold."""
    text = json.dumps(parts, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(text.encode()).hexdigest()


class TrustStore:
    """The trusted contacts, their exact addresses, and the groups, for one person."""

    # --- reading -------------------------------------------------------------

    @staticmethod
    def _as_trusted(row, groups: dict[int, str]) -> Trusted:
        from .models import TrustedAddress

        addresses = list(TrustedAddress.objects
                         .filter(user_id=row.user_id, org_id=row.org_id, contact_id=row.id)
                         .order_by("address").values_list("address", flat=True))
        from .telegram_guests import linked_senders

        telegram = linked_senders(row.user_id, row.org_id, row.id)
        from .slack import linked_senders as slack_senders

        on_slack = slack_senders(row.user_id, row.org_id, addresses)
        from . import grants

        extra = grants.extra_of(row.user_id, row.org_id, row.id)
        found = Trusted(id=row.id, name=row.name, contact_id=row.contact_id,
                       trusted=row.trusted, levels=with_lower(row.levels),
                       grants=[str(g) for g in row.grants or []],
                       inbox_scope=row.inbox_scope if row.inbox_scope in INBOX_STANDING
                       else INBOX_NONE,
                       inbox_from=[str(x) for x in row.inbox_from or []],
                       beyond=row.beyond if row.beyond in BEYOND else "ask",
                       zone=str(getattr(row, "zone", "") or ""),
                       sees=list(row.sees) if isinstance(getattr(row, "sees", None), list) else None,
                       addresses=addresses, group_id=row.group_id,
                       group_name=groups.get(row.group_id or 0, ""), revision=row.revision,
                       note=row.note, updated_at=row.updated_at, telegram=telegram, slack=on_slack,
                       extra_grants=extra)
        tree = grants.tree(row.org_id)
        from . import capability_grants

        found.cap_grants = capability_grants.rows_of(row.user_id, row.org_id, row.id)
        found.held_sig = sorted(f"{k}@{tree.nodes[k].revision}" for k in tree.held(found)
                                if tree.nodes[k].revision > 1 or tree.nodes[k].holding == grants.GRANT)
        # A grant of their own given, taken back, used up or suspended re-reads what of theirs
        # waits, as a change on their page does.
        found.held_sig += sorted(f"cap:{g['id']}@{g['state']}" for g in found.cap_grants)
        return found

    def _groups(self, user_id: str, org_id: str) -> dict[int, str]:
        from .models import ContactGroup

        return dict(ContactGroup.objects.filter(user_id=user_id, org_id=org_id)
                    .values_list("id", "name"))

    def all(self, user_id: str, org_id: str) -> list[Trusted]:
        from .models import TrustedContact

        groups = self._groups(user_id, org_id)
        rows = TrustedContact.objects.filter(user_id=user_id, org_id=org_id).order_by(
            "-trusted", "name", "id")
        return [self._as_trusted(row, groups) for row in rows]

    def get(self, user_id: str, org_id: str, trusted_id) -> Trusted | None:
        from .models import TrustedContact

        try:
            row = TrustedContact.objects.get(user_id=user_id, org_id=org_id, id=int(trusted_id))
        except (TrustedContact.DoesNotExist, TypeError, ValueError):
            return None
        return self._as_trusted(row, self._groups(user_id, org_id))

    def trusted_for(self, user_id: str, org_id: str, address: str) -> Trusted | None:
        """The contact this exact address belongs to, if the owner has switched them on.

        The only question the mail pipeline asks. The address must be one he
        ticked, character for character once lower cased; the contact must be
        switched on. A group is not consulted.
        """
        from .models import TrustedAddress

        address = clean_address(address)
        if not address or not user_id or not org_id:
            return None
        row = (TrustedAddress.objects
               .filter(user_id=user_id, org_id=org_id, address=address,
                       contact__user_id=user_id, contact__org_id=org_id,
                       contact__trusted=True)
               .select_related("contact").first())
        if row is None:
            return None
        return self._as_trusted(row.contact, self._groups(user_id, org_id))

    def listed_for(self, user_id: str, org_id: str, address: str) -> Trusted | None:
        """The contact this exact address is ticked for, switched on or not.

        What decides whether an email is a listed contact's (their levels, or
        everything waiting for the owner while they are switched off) or an
        implicit one's (`implicit`).
        """
        from .models import TrustedAddress

        address = clean_address(address)
        if not address or not user_id or not org_id:
            return None
        row = (TrustedAddress.objects
               .filter(user_id=user_id, org_id=org_id, address=address,
                       contact__user_id=user_id, contact__org_id=org_id)
               .select_related("contact").first())
        if row is None:
            return None
        return self._as_trusted(row.contact, self._groups(user_id, org_id))

    def groups(self, user_id: str, org_id: str) -> list[dict]:
        from django.db.models import Count

        from .models import ContactGroup, TrustedContact

        counts = dict(TrustedContact.objects.filter(user_id=user_id, org_id=org_id)
                      .exclude(group=None).values_list("group_id")
                      .annotate(n=Count("id")).values_list("group_id", "n"))
        return [{"id": gid, "name": name, "members": counts.get(gid, 0)}
                for gid, name in ContactGroup.objects.filter(user_id=user_id, org_id=org_id)
                .order_by("name").values_list("id", "name")]

    # --- writing: every change here is the owner's own press ------------------------------

    def save(self, user_id: str, org_id: str, *, name: str, contact_id: str = "",
             addresses=(), levels=(), grants=(), trusted: bool = False, group_id=None,
             note: str = "", trusted_id=None, inbox_scope=None,
             inbox_from=None, beyond=None, zone=None) -> Trusted:
        """Make or change one trusted contact. ValueError says what is wrong.

        `inbox_scope`, `inbox_from`, `beyond` and `zone` None keep what the contact has
        ("ask" and no zone for a new one). The zone alone does not move the revision: it
        changes nothing they may do.

        Each address has to be a whole address, and no address may belong to
        two contacts: which contact an email is from has to have one answer.
        """
        from django.db import transaction

        from .models import ContactGroup, TrustedAddress, TrustedContact

        if not user_id or not org_id:
            raise ValueError("trust belongs to a person in an organisation")
        name = " ".join(str(name or "").split())[:200]
        wanted: list[str] = []
        for one in addresses or ():
            cleaned = clean_address(one)
            if not cleaned:
                raise ValueError(f"{str(one).strip() or 'An empty line'} is not an email "
                                 "address.")
            if cleaned not in wanted:
                wanted.append(cleaned)
        from . import my_card

        own = my_card.own_addresses(user_id, org_id)
        for one in wanted:
            if one in own:
                raise ValueError(f"{one} is one of your own addresses (your account's, or "
                                 "on your contact card in Settings), so mail from it is "
                                 "already yours. Leave it off.")
        if trusted and not wanted:
            raise ValueError("Tick at least one address before trusting them: trust is "
                             "only ever given to exact addresses.")
        if not name:
            name = wanted[0] if wanted else ""
        if not name:
            raise ValueError("Give them a name.")
        group = None
        if group_id not in (None, "", 0, "0"):
            group = ContactGroup.objects.filter(user_id=user_id, org_id=org_id,
                                                id=int(group_id)).first()
            if group is None:
                raise ValueError("That group is not one of yours.")
        levels = with_lower(levels)
        granted = sorted({str(g).strip()[:80] for g in grants or () if str(g).strip()})
        if "tasks" not in levels:
            granted = []
        now = time.time()
        with transaction.atomic():
            if trusted_id:
                row = (TrustedContact.objects.select_for_update()
                       .filter(user_id=user_id, org_id=org_id, id=int(trusted_id)).first())
                if row is None:
                    raise ValueError("That contact is not one of yours.")
            else:
                row = (TrustedContact.objects.select_for_update()
                       .filter(user_id=user_id, org_id=org_id, contact_id=contact_id).first()
                       if contact_id else None)
            taken = list(TrustedAddress.objects
                         .filter(user_id=user_id, org_id=org_id, address__in=wanted)
                         .exclude(contact_id=row.id if row else 0)
                         .values_list("address", flat=True))
            if taken:
                raise ValueError(f"{', '.join(taken)} already belongs to another trusted "
                                 "contact. Take it off that one first.")
            before = None
            if row is None:
                row = TrustedContact(user_id=user_id, org_id=org_id, contact_id=contact_id,
                                     created_at=now, revision=1,
                                     inbox_scope=INBOX_NONE, inbox_from=[], beyond="ask")
            scope = clean_inbox_scope(row.inbox_scope if inbox_scope is None else inbox_scope)
            reach = clean_inbox_from(row.inbox_from if inbox_from is None else inbox_from) \
                if scope == INBOX_SENDERS else []
            if scope == INBOX_SENDERS and not reach:
                raise ValueError("Name at least one sender or label for A sender or label, "
                                 "such as anna@example.com, @example.com or label:Investors.")
            past = clean_beyond(row.beyond if beyond is None else beyond)
            if row.pk is not None:
                before = (row.trusted, with_lower(row.levels), sorted(row.grants or []),
                          row.inbox_scope or INBOX_NONE,
                          list(row.inbox_from or []), row.beyond or "ask",
                          sorted(TrustedAddress.objects.filter(
                              user_id=user_id, org_id=org_id, contact_id=row.id)
                              .values_list("address", flat=True)))
            row.name, row.trusted = name, bool(trusted)
            row.levels, row.grants = levels, granted
            row.inbox_scope, row.inbox_from, row.beyond = scope, reach, past
            if zone is not None:
                row.zone = clean_zone(zone)
            row.group, row.note, row.updated_at = group, str(note or "")[:1000], now
            if contact_id and not row.contact_id:
                row.contact_id = contact_id
            if before is not None and before != (row.trusted, levels, granted, scope,
                                                 reach, past, sorted(wanted)):
                row.revision += 1
            row.save()
            TrustedAddress.objects.filter(user_id=user_id, org_id=org_id,
                                          contact_id=row.id).exclude(address__in=wanted).delete()
            have = set(TrustedAddress.objects.filter(user_id=user_id, org_id=org_id,
                                                     contact_id=row.id)
                       .values_list("address", flat=True))
            TrustedAddress.objects.bulk_create(
                [TrustedAddress(user_id=user_id, org_id=org_id, contact=row, address=one)
                 for one in wanted if one not in have])
        return self.get(user_id, org_id, row.id)

    def set_trusted(self, user_id: str, org_id: str, trusted_id, on: bool) -> Trusted:
        """The one switch: trusted, or not, keeping everything else as it was."""
        found = self.get(user_id, org_id, trusted_id)
        if found is None:
            raise ValueError("That contact is not one of yours.")
        return self.save(user_id, org_id, name=found.name, contact_id=found.contact_id,
                         addresses=found.addresses, levels=found.levels, grants=found.grants,
                         trusted=on, group_id=found.group_id, note=found.note,
                         trusted_id=found.id,
                         inbox_scope=found.inbox_scope, inbox_from=found.inbox_from,
                         beyond=found.beyond)

    def set_ticks(self, user_id: str, org_id: str, trusted_id, grants) -> Trusted:
        """What is ticked in the tree on their page - columns and projects, each reaching every
        task under it, now and later - keeping everything else as it was. A tick counts only
        with Your tasks, so ticking one turns Your tasks on (and Communication, which it
        includes)."""
        found = self.get(user_id, org_id, trusted_id)
        if found is None:
            raise ValueError("That contact is not one of yours.")
        levels = list(found.levels)
        if grants and "tasks" not in levels:
            levels = [k for k in ORDER if k in levels or k in ("communicate", "tasks")]
        return self.save(user_id, org_id, name=found.name, contact_id=found.contact_id,
                         addresses=found.addresses, levels=levels, grants=list(grants),
                         trusted=found.trusted, group_id=found.group_id, note=found.note,
                         trusted_id=found.id, inbox_scope=found.inbox_scope,
                         inbox_from=found.inbox_from, beyond=found.beyond)

    def set_inbox(self, user_id: str, org_id: str, trusted_id, scope: str,
                  entries=()) -> Trusted:
        """The owner's "Always" answer about their inbox, written onto the contact's page.

        Everything else stays as it was; the revision moves, as any change to
        what they may do moves it.
        """
        found = self.get(user_id, org_id, trusted_id)
        if found is None:
            raise ValueError("That contact is not one of yours.")
        return self.save(user_id, org_id, name=found.name, contact_id=found.contact_id,
                         addresses=found.addresses, levels=found.levels, grants=found.grants,
                         trusted=found.trusted, group_id=found.group_id, note=found.note,
                         trusted_id=found.id, inbox_scope=scope,
                         inbox_from=list(entries or ()), beyond=found.beyond)

    def set_sees(self, user_id: str, org_id: str, trusted_id, sees) -> Trusted:
        """The silos of the owner's life Rouh may bring up for them (`rouh/silos.py`): silo names or keys, or
        None for the silos shown to others. It is what they may do, so the revision moves and anything of
        theirs waiting is read again. ValueError names a silo that is not one."""
        from django.db import transaction

        from . import silos
        from .models import TrustedContact

        got = None
        if sees is not None:
            got, missing = silos.parse(user_id, org_id, sees)
            if missing:
                raise ValueError(silos.unknown_said(user_id, org_id, missing))
            got = got or []
        with transaction.atomic():
            row = (TrustedContact.objects.select_for_update()
                   .filter(user_id=user_id, org_id=org_id, id=int(trusted_id)).first())
            if row is None:
                raise ValueError("That contact is not one of yours.")
            if row.sees != got:
                row.sees, row.revision, row.updated_at = got, row.revision + 1, time.time()
                row.save(update_fields=["sees", "revision", "updated_at"])
        return self.get(user_id, org_id, trusted_id)

    def remove(self, user_id: str, org_id: str, trusted_id) -> bool:
        from .models import TrustedContact

        try:
            gone, _ = TrustedContact.objects.filter(user_id=user_id, org_id=org_id,
                                                    id=int(trusted_id)).delete()
        except (TypeError, ValueError):
            return False
        return bool(gone)

    def add_group(self, user_id: str, org_id: str, name: str) -> dict:
        from .models import ContactGroup

        name = " ".join(str(name or "").split())[:80]
        if not name:
            raise ValueError("Give the group a name.")
        row, _ = ContactGroup.objects.get_or_create(user_id=user_id, org_id=org_id, name=name,
                                                    defaults={"created_at": time.time()})
        return {"id": row.id, "name": row.name}

    def remove_group(self, user_id: str, org_id: str, group_id) -> bool:
        from .models import ContactGroup

        try:
            gone, _ = ContactGroup.objects.filter(user_id=user_id, org_id=org_id,
                                                  id=int(group_id)).delete()
        except (TypeError, ValueError):
            return False
        return bool(gone)


# --- the tasks a contact may read --------------------------------------------------------

#: The columns a grant can reach, in the picker's order. Rouh's own column
#: joined Work and Personal on 30 September 2026, when Petar asked to be able to
#: grant a contact single Rouh tasks (task 69 among them). It is reached under
#: exactly the same rules: only what he ticks, and everything under it, read
#: only. Nothing a grant reaches can change Rouh itself: the "use" level's work
#: is the workspace's own (`LEVEL_TOOLS`), never Rouh's code.
COLUMNS = ("work", "private", "rouh")


class Tree:
    """The workspace's projects and tasks, read once: rows by id and who owns whom."""

    def __init__(self, store) -> None:
        from .models.objects import NESTS

        self.rows = {row["id"]: row for row in store.objects()}
        self.kids: dict[str, list[str]] = {}
        self.owner: dict[str, str] = {}
        for _st, src, dst_type, dst in store.owns_edges():
            if dst_type in NESTS and src in self.rows and dst in self.rows:
                self.kids.setdefault(src, []).append(dst)
                self.owner[dst] = src

    def column_of(self, ident: str) -> str:
        """The top of the tree this object is in: "work", "private", "rouh" or ""."""
        seen = set()
        while ident in self.owner and ident not in seen:
            seen.add(ident)
            ident = self.owner[ident]
        row = self.rows.get(ident) or {}
        return (row.get("slug") or row.get("folder") or "").lower()

    def under(self, ident: str) -> set[str]:
        """This object and everything under it."""
        out, todo = set(), [ident]
        while todo:
            one = todo.pop()
            if one in out or one not in self.rows:
                continue
            out.add(one)
            todo += self.kids.get(one, [])
        return out

    def tasks_holding(self, paths) -> list[str]:
        """The tasks these workspace paths are in, each the task itself and not one of its
        steps, in the order the paths name them.

        A path is a folder or a file, relative to the workspace or starting with
        ``workspace/``; one that is in no task names nothing.
        """
        tasks = [((row.get("folder") or "").strip("/"), ident)
                 for ident, row in self.rows.items()
                 if row.get("type") == "task" and (row.get("folder") or "").strip("/")]
        out: list[str] = []
        for raw in paths or ():
            path = str(raw or "").strip().strip("/")
            path = path.removeprefix("workspace/")
            if not path or ".." in path.split("/"):
                continue
            held = [(folder, ident) for folder, ident in tasks
                    if path == folder or path.startswith(folder + "/")]
            if not held:
                continue
            ident = max(held, key=lambda one: len(one[0]))[1]
            seen: set[str] = set()
            while self.rows.get(self.owner.get(ident, ""), {}).get("type") == "task" \
                    and ident not in seen:
                seen.add(ident)
                ident = self.owner[ident]
            if ident not in out:
                out.append(ident)
        return out


def grant_tree(store) -> list[dict]:
    """Work, Personal and Rouh, their projects and their tasks, for the picker.

    Each node is {id, title, kind, number, kids}. Projects nest in projects;
    a task's own steps are not listed, because a task is granted whole.
    """
    from . import archiving

    tree = Tree(store)
    # The `object` view has no archived_at, so what is archived is asked of the tasks.
    kept = archiving.archived(store)

    def key(row) -> tuple:
        return (row["type"] != "project", (row.get("title") or row.get("slug") or "").lower())

    def node(ident: str) -> dict:
        row = tree.rows[ident]
        kids = [] if row["type"] == "task" else [
            node(k) for k in sorted(tree.kids.get(ident, []), key=lambda k: key(tree.rows[k]))
            if tree.rows[k]["type"] in ("project", "task")
            and k not in kept]
        return {"id": ident, "title": row.get("title") or row.get("slug") or ident,
                "kind": row["type"], "number": row.get("number"), "kids": kids}

    tops = [r for r in tree.rows.values() if r["type"] == "project" and r["id"] not in tree.owner
            and (r.get("slug") or r.get("folder") or "").lower() in COLUMNS]
    tops.sort(key=lambda r: COLUMNS.index((r.get("slug") or r.get("folder") or "").lower()))
    return [node(r["id"]) for r in tops]


def tidy_grants(store, grants) -> list[str]:
    """Ticked ids as kept: ones in a column of `COLUMNS`, and none under another ticked one."""
    tree = Tree(store)
    wanted = [g for g in dict.fromkeys(str(g) for g in grants or ())
              if g in tree.rows and tree.column_of(g) in COLUMNS]
    covered: set[str] = set()
    for one in wanted:
        covered |= tree.under(one) - {one}
    return [g for g in wanted if g not in covered]


#: The tag a task made shared with a contact carries in its meta, beside
#: `GUEST_TAG`, `"guest": "<their address>"` and `"shared_with": [<their contact id>]`
#: (`tools.ToolRegistry._shared_task`, Petar, 11 October 2026).
SHARED_TAG = "shared"


def task_meta(root, folder: str) -> dict:
    """A task's meta, what was its meta (`rouh/taskmeta.py`), or {} for none."""
    from . import taskmeta

    if not folder or not root:
        return {}
    return taskmeta.get(folder, root)


def shared_with_them(meta: dict, contact) -> bool:
    """Whether a task's meta says it is shared with exactly this contact."""
    tags = [str(t).strip().lower() for t in meta.get("tags") or [] if isinstance(t, str)]
    if SHARED_TAG not in tags or contact is None:
        return False
    ids = {str(x) for x in meta.get("shared_with") or [] if str(x).strip()}
    return str(contact.id) in ids


def asked_by_them(meta: dict, contact) -> bool:
    """Whether a task's meta says it was done at this contact's request: tagged
    `GUEST_TAG`, with an address of theirs, or the Telegram account they asked on, as its guest.
    "telegram:<id>" is no address, and a task done for a Telegram message was refused to the very
    case that made it (card 1315)."""
    if contact is None:
        return False
    tags = [str(t).strip().lower() for t in meta.get("tags") or [] if isinstance(t, str)]
    if GUEST_TAG not in tags:
        return False
    guest = str(meta.get("guest") or "").strip().lower()
    return bool(guest) and (clean_address(guest) in contact.addresses
                            or guest in contact.telegram)


def started_by(meta: dict, contact) -> bool:
    """Whether this contact started the task: asked for it (`asked_by_them`), or had it made
    shared with them (`shared_with_them`). Theirs to edit (`rouh/task_access.py`)."""
    return asked_by_them(meta, contact) or shared_with_them(meta, contact)


class Grants:
    """What one trusted contact may read and be sent, worked out now.

    Against the tree as it stands, not as it was when the owner ticked it: a task
    that moved stays granted (it is granted by id), and a task made inside a
    granted project since is granted too. Only the columns in `COLUMNS` are
    ever reached. Every task they may read or edit by its one level
    (`rouh/task_access.py`) is reached: one ticked, one shared with them, one
    they started - done at their request, from the address it was asked from or
    the linked Telegram account (`Trusted.telegram`), or made shared with them.
    `edit_ids` are the ones they may change (Petar, 16 October 2026,
    fr_5825d8e52d0a: "If she is allowed, she should be allowed from anywhere").

    A task they decide for is one they may edit (`rouh/task_access.py`, the one record): what
    they were given authority over is read and changed the same way as everything else.

    `case_tasks` are the paths of the task or tasks the case being worked on
    made or was approved to work on (`mail_cases.own_paths`): those are
    readable in that case's turns, whatever the levels, and nothing else is
    added. Reading only: what may be shared with them is still `folder_ok`.
    """

    def __init__(self, store, root, contact: Trusted, *, case_tasks=(), owner=None) -> None:
        from . import task_access

        self.root = root
        self.contact = contact
        self.tree = Tree(store)
        self.access = task_access.Access(store, root, contact, owner, tree=self.tree)
        levels = self.access.levels()
        self.ids: set[str] = set(self.access.ticked)
        # Theirs by a share or because they started it, beyond what is ticked.
        self.guest_ids: set[str] = {i for i in levels if i not in self.ids}
        self.edit_ids: set[str] = {i for i, lvl in levels.items()
                                   if task_access.at_least(lvl, task_access.EDIT)}
        self.started_ids: set[str] = {i for i in levels if started_by(
            self.access.meta(self.tree.rows[i].get("folder") or ""), contact)}
        self.case_ids: set[str] = set()
        for ident in self.tree.tasks_holding(case_tasks):
            self.case_ids |= self.tree.under(ident)

    def reachable(self, *, read: bool = False) -> set[str]:
        """What they may reach, and with `read` what this case's turn may also read; in an answer
        others read too, only what every one of them may (`Trusted.within`)."""
        got = self.ids | self.guest_ids | (self.case_ids if read else set())
        within = getattr(self.contact, "within", None)
        return got if within is None else got & set(within)

    def tasks(self) -> list[dict]:
        """Every task that may be read, with its number, title and folder.

        A step is listed only when the task it is in is not: a step granted on its own
        (`rouh/delegation.py`), called by its number as said, "98-03"."""
        from . import searching, workpicker

        reach = self.reachable(read=True)
        out = []
        for ident in reach:
            row = self.tree.rows[ident]
            above = self.tree.owner.get(ident, "")
            if row["type"] != "task" or (
                    self.tree.rows.get(above, {}).get("type") == "task" and above in reach):
                continue
            number = row.get("number")
            if number is None:
                number = searching.number_of_folder(row.get("folder") or "") or None
            out.append({"id": ident, "number": number, "title": row.get("title"),
                        "folder": row.get("folder") or "",
                        "edit": ident in self.edit_ids,
                        "guest": ident in self.started_ids,
                        "case": ident in self.case_ids and ident not in self.ids
                        and ident not in self.guest_ids})
        return sorted(out, key=lambda r: (r["number"] is None,
                                          workpicker.code_parts(r["number"]) or (0,),
                                          r["title"] or ""))

    def folder_ok(self, rel: str, *, read: bool = False) -> bool:
        """Whether a path in the workspace is inside something they may reach, or with
        `read`, something this case's turn may read."""
        rel = str(rel or "").strip().strip("/")
        if not rel or ".." in rel.split("/"):
            return False
        for ident in self.reachable(read=read):
            folder = (self.tree.rows[ident].get("folder") or "").strip("/")
            if folder and (rel == folder or rel.startswith(folder + "/")):
                return True
        return False


def find_contacts(people, user_id: str, org_id: str, query: str, *,
                  limit: int = 12) -> list[dict]:
    """Contacts a few words find, to pick one to trust: name and every address.

    iCloud cards by their search text and address, and Rouh's own contacts
    (`people.People.search`). Never the person's own contact, the card picked
    in Settings (`my_card.is_my_card`): trusting themselves means nothing,
    their own mail is already theirs.
    """
    from . import my_card, vcard
    from .synapse import contacts

    words = vcard.normalise(query or "").split()
    if not words or not user_id or not org_id:
        return []
    out: list[dict] = []
    seen: set[str] = set()
    cards = contacts.search(user_id, org_id, query, limit) + [
        c for c in contacts.all_cards(user_id, org_id) if "@" in query
        and any(query.strip().lower() in str(e.get("address") or "").lower() for e in c["emails"])][:limit]
    for person in people.attach(user_id, org_id, cards[:limit]):
        if (person.id and person.id not in seen
                and not my_card.is_my_card(user_id, org_id, person)):
            seen.add(person.id)
            out.append({"id": person.id, "name": person.name,
                        "organisation": person.organisation, "emails": person.emails})
    for person in people.search(user_id, org_id, query, skip=seen)[:limit]:
        if (person.id and person.id not in seen
                and not my_card.is_my_card(user_id, org_id, person)):
            seen.add(person.id)
            out.append({"id": person.id, "name": person.name,
                        "organisation": person.organisation, "emails": person.emails})
    return out[:limit]


__all__ = ["BASELINE", "BEYOND", "GUEST_TAG", "INBOX_RANK", "INBOX_SCOPES",
           "INBOX_STANDING", "LEVELS", "LEVEL_TOOLS", "OLD_CATCH_ALL",
           "Trusted", "TrustStore", "clean_address", "clean_beyond", "clean_inbox_from",
           "clean_inbox_scope", "clean_zone", "find_contacts", "inbox_said",
           "fingerprint", "grant_tree", "implicit", "with_lower"]
