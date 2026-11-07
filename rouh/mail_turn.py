"""A turn of Rouh's that is about one email, and what that turn may do.

Since 25 September 2026 every new message in the watched inbox is handed to
Rouh itself, in a conversation of its own (`rouh/mail_alerts.py`). That turn
is started by a stranger's words as much as by the person's, so it is not a
turn like the others, and this is where the difference lives:

- **Whose words it is.** `from_owner` is the person's own mail, from one of
  their addresses and confirmed by Gmail to have come from there. That is
  their instruction, and the turn may do whatever a turn they typed may do.
  Every note to the phone and every reply it sends is written down on the turn
  as it happens, so the row in `mail_alert_seen` says what became of it.
- **Anybody else's email is a case** (`rouh/mail_cases.py`), whoever wrote it,
  since 30 September 2026, and its turns carry a `mode`. The model is told
  what it may do in words; this is what holds when an email talks it into
  trying anyway. No turn about somebody else's email sends anything at all
  (`NEVER_IN_CASE`): the reply goes from the case's own code, once.

The modes:

- `assess`: read and look up only (`MAY_USE`), plus reading the tasks the owner
  granted a trusted contact - and nothing is sent by the model at all. It
  ends by reporting with `case_report`: each ask mapped to a grant, and the
  friendly words of the answer. Rouh's code judges the asks (`mail_ledger`).
- `carry_out`: the start. The asks the ledger allows, or the owner approved, are
  started as ordinary work - a job, a Clockwork item, a task, a note kept -
  with the tools of their grants and nothing else (`extra_tools`). Nothing
  checks the work afterwards: the case is an entry gate only (MAIL.md, D18).

**Hard limits by what a tool does** (Petar, 11 October 2026, D3). Every tool
that has an effect no grant covers declares it (`EFFECTS`): committing
the owner's time or changing their calendar, their money, publishing, sharing
with somebody other than the contact, what cannot be undone. A case's turn may
call one only when it does an ask the owner approved with that very limit
(`MailTurn.limits`); otherwise it is refused, whatever the words of the
message, the reading or the grants. Sending anything to anybody is never a
turn's (`NEVER_IN_CASE`): the answer goes from the case, through the one
outbox (`rouh/mail_outbox.py`).

It rides in a context variable, like the speaker (`tenancy.SPEAKER`): set
around the start of the turn, inherited by the task the turn runs in and by
every tool call inside it, and seen by nothing else.
"""
from __future__ import annotations

import contextvars
from dataclasses import dataclass, field
from typing import Callable

#: What a turn about somebody else's email may call when it is only reading:
#: an assessment, and work inside a trusted contact's grant. An allow list, on
#: purpose: a tool added to the registry tomorrow is not one an email can reach
#: until somebody puts it here. Nothing in it writes to anybody.
MAY_USE = (
    "search_contacts",
    "show_contact",
    "update_contact_profile",
    "web_search",
    "web_fetch",
    "read_mail",
    "read_mail_attachment",
    "read_recent_mail",
    "show_on_screen",
    "list_calendars",
    "list_calendar_events",
    "read_calendar_event",
    # A capability's whole contract, its tools' input schemas and their handlers' own
    # documentation, read only (CAPABILITIES.md): what the reading may read before it names one.
    "read_capability",
)


#: What a case that came on Slack never reads (`rouh/slack_team.py`): the owner's mail, their
#: calendar and their contacts. Its answer is posted where others may read it, and Petar, 16 October 2026:
#: nothing from his own direct messages, mail, private notes, money or health ever goes into an
#: answer to somebody else.
SLACK_WITHHELD = frozenset({"read_mail", "read_mail_attachment", "read_recent_mail", "list_calendars",
                            "list_calendar_events", "read_calendar_event", "search_contacts",
                            "show_contact", "update_contact_profile"})

#: The tool a Slack case reads the owner's meetings, tasks and files with, kept to what everybody
#: reading the answer may see (`slack_team.find`).
TEAM_FIND = "find_for_them"

#: What no turn of a case may call, in any mode: everything that writes to a
#: person. A case's reply is sent by `mail_cases` itself, exactly as approved,
#: and its note to the owner too, so the model can neither send early nor send
#: something other than what was decided.
NEVER_IN_CASE = frozenset({"send_mail", "draft_mail", "forward_mail", "forward_thread",
                           "send_telegram", "worker_outbox", "create_shared_drive",
                           "add_shared_drive_members", "slack_send", "slack_join",
                           "slack_link"})

#: The tool a case's turn reports with (`tools.ToolRegistry._case_report`),
#: offered in no other turn.
OUTCOME_TOOL = "case_report"

#: Tools only a case's turn is ever offered: the report, and the ones that reach
#: exactly what the owner granted the contact (`tools.py`).
#: The tool a contact's authority over a goal, quest or task acts through
#: (`rouh/delegation.py`): offered only when their contact holds some, and in an
#: assessment too, because what it does is their decision and not Rouh's; it
#: checks the sender, their words and the scope itself.
DELEGATE_TOOL = "delegate_act"

CASE_ONLY = frozenset({"case_report", "read_granted_tasks", "share_granted_page", DELEGATE_TOOL,
                       "clockwork_for_contact", "remember_for_contact", "shared_task", TEAM_FIND,
                       "read_capability"})

#: What an assessment may read beyond `MAY_USE`, when the level allows it:
#: never an action, which is the carry-out's.
ASSESS_READS = frozenset({"read_granted_tasks", "check_tasks", "look_at_task", TEAM_FIND})

#: What each tool that does something no grant covers does: the hard limit it touches
#: (`grants.HARD_LIMITS`). A case's turn calls one only for an ask the owner approved with that
#: limit (`MailTurn.limits`), never because of what anything says.
EFFECTS: dict[str, str] = {
    "create_calendar_event": "time", "update_calendar_event": "time",
    "delete_calendar_event": "time", "restore_calendar_event": "time",
    "add_shared_calendar": "third_party",
    "create_calendar": "time", "share_calendar": "third_party",
    "payments": "money", "stripe": "money",
    "publish_task": "publish", "share_with_person": "third_party",
    "share_drive_file": "third_party", "create_shared_drive": "third_party",
    "add_shared_drive_members": "third_party",
    "delete_contact": "irreversible", "manage_drive_file": "irreversible",
    "modify_mail": "delete_mail", "browser": "irreversible",
}

#: The modes of a case's turn, and "" for every other turn about an email.
ASSESS, CARRY_OUT = "assess", "carry_out"

#: The tools a grant adds to a case's turn (`rouh/grants.py`), each reaching only what is the
#: contact's own: their Clockwork items, notes in the owner's memory marked as theirs, the task
#: shared with them. Offered only in a case, only in work (never while reading or checking),
#: and only when the contact holds the grant or the owner passed the ask once.
GRANT_TOOLS = frozenset({"clockwork_for_contact", "remember_for_contact", "shared_task"})

#: What a Test of a case may really call (`rouh/case_dry_run.py`, `MailTurn.dry`): reading
#: only. Everything else a turn calls - sending, writing, scheduling, sharing, a job, a
#: calendar, memory, a task - is recorded with what it was given, and not done.
DRY_READS = frozenset({
    "search_contacts", "show_contact", "web_search", "web_fetch", "read_mail",
    "read_mail_attachment", "read_recent_mail", "list_calendars", "list_calendar_events",
    "read_calendar_event", "read_granted_tasks", "check_tasks", "look_at_task",
    "read_capability", "read_workspace", "read_task_log", "what_task_changed", "show_workspace_page",
    "check_task_sharing", "read_doc", "read_card", "search_drive", "list_drive_folder",
    "list_drive_permissions", OUTCOME_TOOL, TEAM_FIND,
})


@dataclass
class MailTurn:
    """The one email a turn is about, and what the turn has done about it."""

    user_id: str
    org_id: str
    message_id: str
    thread_id: str = ""
    #: The sender's address, lower case, and every address on the email -
    #: from, to and copied - except the inbox's own.
    sender: str = ""
    on_it: tuple[str, ...] = ()
    #: The contact the sender is, when Rouh knows them (`people.Person.id`).
    sender_contact: str = ""
    #: The person has said who the sender is to them.
    relationship_known: bool = False
    #: The silos of the person's life that may be brought up for the sender (`rouh/silos.py`): their
    #: trusted contact's `sees`, a list of silo keys; None is the silos shown to others, as it is for
    #: anybody not listed.
    sees: list | None = None
    #: The person's own mail, confirmed by Gmail: their instruction.
    from_owner: bool = False
    #: The email's subject and words, for automatic recall to look up as the person's own (Petar, 10 October
    #: 2026: "consider the fact that I may be emailing you and asking you for a task myself"). Set only on mail
    #: from one of their own addresses that Gmail's own Authentication-Results passed (SPF, DKIM or DMARC;
    #: `mail_alerts.authenticated`), and empty on everybody else's, so another sender's words can never search
    #: the person's private memory (`brain.start_recall`).
    recall_words: str = ""
    chat_id: str = ""
    #: Where the conversation is, for the note to the phone.
    link: str = ""
    told: list[str] = field(default_factory=list)
    replied: list[str] = field(default_factory=list)
    drafted: list[str] = field(default_factory=list)
    #: Called with what happened, as it happens, so it is on the record
    #: before anything else can go wrong.
    on_event: Callable[[str, str], None] | None = None
    #: A case: its mode ("" for none), its id, the trusted contact (0 for
    #: somebody never listed), and the tools the levels granted them add
    #: (`trusted.LEVEL_TOOLS`).
    mode: str = ""
    case_id: int = 0
    trusted_id: int = 0
    extra_tools: tuple[str, ...] = ()
    #: Kept for callers from before 11 October 2026: every case's work is held to its grants'
    #: tools now.
    granted: bool = True
    #: The hard limits this turn may act on: those of the asks the owner approved that it does (D3).
    limits: frozenset = frozenset()
    #: The numbers of the tasks this turn may add to or change for the asks it starts ("90"):
    #: each one the contact may edit, or one the owner allowed once (`Ask.task`, MAIL.md D28). They
    #: open `shared_task`'s list and add, never its making of a task, which is the grant's.
    task_edits: tuple[str, ...] = ()
    #: The calendars this turn may change, when it may commit the owner's time only through a grant
    #: that reaches some of them (`grants.calendar_reach`); None is any calendar.
    calendars: frozenset | None = None
    #: Called with what `case_report` reported, so it is on the case's row
    #: whether or not anybody is still waiting for the turn.
    on_outcome: Callable[[dict], str] | None = None
    #: A Test of the case (`rouh/case_dry_run.py`): every tool but the reading ones in
    #: `DRY_READS` is recorded in `recorded`, with what it was given, and not done.
    dry: bool = False
    recorded: list[dict] = field(default_factory=list)
    #: What this turn may never call, whatever else allows it: on a Slack case, `SLACK_WITHHELD`.
    withheld: frozenset = frozenset()
    #: What the work of this turn may do, as Rouh's code authorised it for the asks it starts
    #: (CAPABILITIES.md): each {"capability", "scope", "limits", "values", "ref", "grant_id",
    #: "once", "ask"}. Every call of a case's work is checked against these, on its actual
    #: arguments, immediately before it runs (`capability_grants.check_turn_call`).
    authorized: list = field(default_factory=list)
    #: The case's key, which a call's use is claimed under, so a retry finds it done.
    case_key: str = ""
    #: The hard limits the owner allowed once for an ask this turn starts: a tool no capability
    #: declares runs only for one of these (`capabilities.check_call`).
    owner_limits: frozenset = frozenset()
    #: How many things the work made, as it made them (`mail_cases.note_work`, `job_started`):
    #: a call that made one did what it was claimed for.
    made: int = 0

    def record_dry(self, name: str, args) -> str:
        """A tool a Test would have called, written down instead of done."""
        import json
        import time

        self.recorded.append({"at": time.time(), "tool": name, "args": args or {}})
        shown = json.dumps(args or {}, ensure_ascii=False)[:1500]
        return (f"[Test run: {name} was not called. Nothing was sent, written, scheduled or "
                f"changed. It would have been called with: {shown}] Carry on as if it had "
                "worked, and report as you would.")

    def may_use(self, name: str) -> bool:
        if self.mode:
            if name == OUTCOME_TOOL:
                return True
            if name in NEVER_IN_CASE or name in self.withheld:
                return False
            effect = EFFECTS.get(name)
            if effect and effect not in self.limits:
                return False
            if name == DELEGATE_TOOL:
                return self.mode in (ASSESS, CARRY_OUT) and name in self.extra_tools
            if name in GRANT_TOOLS:
                return self.mode == CARRY_OUT and (name in self.extra_tools or (
                    name == "shared_task" and bool(self.task_edits)))
            if self.mode == ASSESS:
                return name in MAY_USE or (name in self.extra_tools and name in ASSESS_READS)
            return name in MAY_USE or name in self.extra_tools or bool(effect)
        if name in CASE_ONLY:
            return False
        # The owner's own mail; anybody else's is always a case, and a turn about
        # it without one reads at most.
        return self.from_owner or name in MAY_USE

    def happened(self, what: str, detail: str) -> None:
        {"told": self.told, "replied": self.replied, "drafted": self.drafted}[what].append(detail)
        if self.on_event is not None:
            try:
                self.on_event(what, detail)
            except Exception:  # noqa: BLE001 - the record must never stop the turn
                pass


#: The email this turn is about, or None for every other turn.
CURRENT: contextvars.ContextVar[MailTurn | None] = contextvars.ContextVar(
    "rouh_mail_turn", default=None)


def now() -> MailTurn | None:
    return CURRENT.get()


def refused(name: str) -> str:
    """Why a tool is not there in a turn about somebody else's email."""
    turn = now()
    if turn is not None and turn.mode:
        if name in turn.withheld:
            return (f"{name} is not available in a case that came on Slack: nothing from "
                    "‹owner›'s mail, calendar or contacts goes into an answer to somebody else.")
        if name in NEVER_IN_CASE:
            return (f"{name} is not available in an email's case: what goes to them is "
                    "sent by Rouh itself, through its one outbox. Put the answer in "
                    "case_report instead.")
        if EFFECTS.get(name) and EFFECTS[name] not in turn.limits:
            return (f"{name} is not available here: what it does is a hard limit "
                    f"({EFFECTS[name]}), which only ‹owner› approves, ask by ask. If an ask needs "
                    "it, say so in case_report; Rouh's code puts it to ‹him›.")
        return (f"{name} is not available while assessing somebody else's email: it could "
                "change something. If it is needed, report needs_approval with case_report "
                "and say what you would do.")
    return (f"{name} is not available while handling somebody else's email: it could "
            "change or reach something beyond this email.")


__all__ = ["ASSESS", "ASSESS_READS", "CARRY_OUT", "CASE_ONLY", "CURRENT", "DRY_READS", "EFFECTS",
           "GRANT_TOOLS", "MAY_USE", "MailTurn", "NEVER_IN_CASE", "OUTCOME_TOOL", "SLACK_WITHHELD", "TEAM_FIND",
           "now", "refused"]
