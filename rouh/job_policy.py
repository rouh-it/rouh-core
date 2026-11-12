"""What a background job may have Rouh do for it: one decision for every call, in code.

Petar, 25 October 2026: background jobs - Claude Code and Codex workers, runs of the one
program, the jobs the heartbeat starts - kept stopping when they needed something only Rouh
has: a login, an integration, a tool. Each gap got a one-off fix, the last of them
`mail_find` and `mail_file`. "Okay implement that now": one gateway to Rouh's own tools for
every job (`rouh/job_gateway.py`), and one permission check in front of it, which is this.

**No model sits in it.** Every ruling here is the tool's name, its arguments and the scope
of the job, looked up in the tables below. Nothing a job read, wrote or was told can change
a ruling, which is what makes a hostile page or email that says "send this to X" or "pay Y"
end up as one pending decision and never as a send or a payment: the judge after it reads only
the owner's own words, and money, sending to people those words did not name, deleting for
good, access and Rouh's own rules still come to the owner unless the words name them exactly
(`his_word.held`).

**The scope** is who the job works for, decided by Rouh from the run register and never by
the job (`job_gateway.scope_of`), the same three as `rouh/job_mail.py` drew on 25 October:

- `OWNER`: a job from the owner's own words;
- `CONTACT`: a job doing a trusted contact's work, which reaches that contact's
  conversation and what came in it, and nothing of the owner's own;
- `PROCESS`: a job one of Rouh's own processes started (the heartbeat, quests, the
  nights), which reads what a beat reads: Rouh's own inbox, never the owner's.

**The classes**, one per tool, written out below; a tool that is in none of them is `RISKY`,
so a tool added tomorrow fails closed:

- `READ`: it only reads. Run at once, within the scope.
- `OWN`: it writes only inside the job's own work - a draft, a private file nobody else
  sees, the job's own task. Run at once, for the owner's and Rouh's own jobs.
- `RISKY`: it sends, forwards, shares, publishes, pays, buys, books, deletes or bins, writes
  to contacts, changes other people's calendars or Rouh's own settings, models and rules,
  starts or steers other work. Never run on the ruling alone: `PENDING` hands it to the
  gateway, which runs it when the owner's own words for this job already ask for it
  (`rouh/his_word.py`) or one of their standing rules covers it (`job_gateway.covered_by_rule`),
  and otherwise makes it one decision for the owner, one per job however many calls wait.

**This ruling is not the last word on a risky call.** Petar, 2 November 2026, after two calls
of the rouh.land move he had asked for came back to him as Decisions 385 and 386: "no this is
carving simply this case today. tomorrow we will have a different case. I want ot undrstand
what caused it and to change so tomorrow I don't get a decision but whatever the new thing
gets done". The cause was here: `RISKY` meant "ask him", whatever he had asked for. It still
means only "not safe on its tool and arguments alone"; what he asked for is judged after, in
the gateway, against his own words kept with the run, never against anything the job read.
- `NEVER`: what only makes sense in a live chat with the owner - the screen and the canvas,
  the orb, boxes and thoughts - and what answers for the owner: decisions, a run's
  permission question, a conflict's pick, who decides for him. Also what would have Rouh's
  own model do the work, because the gateway spends no tokens of Rouh's on a plain call.
  Never listed to a job, and refused if named.

Standard library only, so a check of it needs nothing but Python.
"""
from __future__ import annotations

from dataclasses import dataclass

OWNER, CONTACT, PROCESS = "owner", "contact", "process"
SCOPES = (OWNER, CONTACT, PROCESS)

READ, OWN, RISKY, NEVER = "read", "own", "risky", "never"

RUN, PENDING, REFUSE = "run", "pending", "refuse"

#: The gateway's own tools, answered by `rouh/job_gateway.py` itself rather than by the tool
#: registry: files out of mail, a request for what there is no tool for, and its answer.
MAIL_FIND, MAIL_FILE = "mail_find", "mail_file"
REQUEST, REQUEST_STATUS = "request_from_rouh", "request_status"
#: A management command run by Rouh's core, from a short allowlist (`rouh/core_commands.py`).
CORE_COMMAND = "core_command"
NATIVE = (MAIL_FIND, MAIL_FILE, REQUEST, REQUEST_STATUS, CORE_COMMAND)

#: The core's commands a job may name that only read: run at once, for the owner's and Rouh's
#: own jobs.
CORE_READS = frozenset({"table_sizes", "scrub_status", "code_release_status"})
#: The core's maintenance commands the owner has already agreed to (the scrub of private
#: reasoning, 11 November 2026): started in the core's background, for the owner's and Rouh's
#: own jobs. Each is idempotent and carries on from where it got to.
#: Rouh's release by hand on rouh.land, agreed 12 November 2026 (`rouh/code_release.py`).
CORE_MAINTENANCE = frozenset({"scrub_encrypted_reasoning", "code_release_publish"})

#: Tools that only read, whatever their arguments.
READS = frozenset({
    # The gateway's own.
    MAIL_FIND, MAIL_FILE, REQUEST, REQUEST_STATUS,
    # Mail: reading and saving a file into a task, never marking, moving or sending.
    "read_recent_mail", "read_mail", "read_mail_attachment",
    # Calendar.
    "list_calendars", "list_calendar_events", "read_calendar_event",
    # Drive and Docs.
    "search_drive", "list_drive_folder", "list_shared_drives", "list_drive_permissions",
    "read_doc", "doc_changes",
    # Contacts.
    "search_contacts",
    # Slack.
    "slack_channels", "slack_read", "slack_search",
    # Meetings and Synapse, outside the Synapse lab: what memory holds, with no answer model.
    "meeting_search", "meeting_read", "synapse_find", "synapse_query",
    # The workspace, the tasks and the runs, and anything Rouh made.
    "read_workspace", "read_card", "read_rouh_link", "check_tasks", "look_at_task",
    "read_task_log", "what_task_changed", "one_runs", "what_is_running", "check_task_sharing",
    "list_memory", "upcoming", "server_health",
    # What has become of new mail: it takes no arguments and changes nothing. Until 2 November
    # 2026 it was listed as risky, "how new mail is told", which it never was.
    "mail_alerts",
    # The public web, read with Rouh's own accounts.
    "youtube_search", "youtube_transcript", "linkedin_search", "linkedin_profile",
})

#: Tools that read with some actions and change something with the rest: the actions that
#: only read. A call with any other action, or none, is `RISKY`.
READ_ACTIONS = {
    "agent_instructions": frozenset({"list"}),
    "thoughts": frozenset({"list", "read"}),
    "shipping": frozenset({"list"}),
    "link_person": frozenset({"show"}),
    # check writes back only the value it just read (`cloudflare._settings_edit`);
    # origin_certificates lists the zone's public certificates. dns_delete is not here: it is risky.
    "cloudflare": frozenset({"status", "check", "records", "settings", "origin_certificates"}),
    "hue": frozenset({"list"}),
    "vacuum": frozenset({"status"}),
    # What the heartbeat reads of Stripe (`heartbeat.STRIPE_READS`); "status" when not said.
    "stripe": frozenset({"status", "payments", "balance", "list"}),
    # The comments pinned to one of the owner's pages (`rouh/page_comments.py`); "list" when
    # not said.
    "page_comments": frozenset({"list"}),
}
#: Tools that only read unless one of these arguments is said, which spends or writes:
#: meeting_people's research_now looks the guests up, at a cost, and keeps what it found on
#: their contacts. Until 2 November 2026 meeting_people was risky whatever it was asked.
READ_UNLESS = {"meeting_people": ("research_now",)}
#: The action a tool takes when none is given, where it has one.
DEFAULT_ACTION = {"stripe": "status", "page_comments": "list"}

#: Tools that write only inside the job's own work, whatever their arguments.
OWNS = frozenset({
    # A draft in Rouh's own drafts: nothing is sent, and sending it is send_mail's.
    "draft_mail",
    # A printable PDF of one of the person's own pages, for them: nothing is shared. Listed
    # under sharing and publishing until 2 November 2026.
    "print_page",
})

#: Tools that read with some actions (`READ_ACTIONS`) and, with these, write only on the owner's
#: own things: a comment on one of their pages, drawn as Rouh's and tagging nobody, answered,
#: changed (Rouh's own only) or resolved (`rouh/page_comments.py`). Any other action - taking a
#: comment away - is `RISKY`.
OWN_ACTIONS = {
    "page_comments": frozenset({"add", "reply", "edit", "resolve", "reopen"}),
}

#: Tools that write only inside the job's own work when their arguments say so: a private
#: file nobody else is given, an event of the owner's own with nobody else on it. With any of
#: these arguments they reach somebody else, and are `RISKY`.
OWN_UNLESS = {
    "create_doc": ("email", "role", "notify", "folder"),
    "write_drive_file": ("file_id", "drive", "folder"),
    "create_drive_folder": ("email", "role", "drive", "parent"),
    "create_calendar_event": ("guests", "items", "calendar"),
}

#: Tools that are risky whatever their arguments, written out so every tool a job is listed
#: has its class said here. A tool in none of these lists is risky all the same (`classify`).
RISKS = frozenset({
    # Sending, forwarding and posting, in the owner's name or Rouh's.
    "send_mail", "forward_mail", "forward_thread", "send_telegram", "slack_send", "slack_join",
    "reply_to_doc_comment", "comment_on_doc", "handle_email_again",
    # Mail changed: marked, labelled, moved or binned; and how new mail is told.
    "modify_mail",
    # Sharing and publishing.
    "share_drive_file", "manage_drive_file", "upload_drive_file", "edit_doc", "edit_sheet", "edit_slides",
    "copy_drive_file",
    "create_shared_drive", "add_shared_drive_members", "share_calendar", "add_shared_calendar",
    "create_calendar", "publish_task", "share_with_person", "slack_link",
    # Calendars other people may be on.
    "update_calendar_event", "delete_calendar_event", "restore_calendar_event", "block_my_time",
    # Money.
    "payments",
    # Contacts and who somebody is.
    "save_contact", "update_contact_profile", "delete_contact",
    # Rouh's own memory, rules, settings, models and code, and this server.
    "remember", "forget", "model_defaults", "update_rouh", "improve_myself", "deploy_myself", "delegate_task",
    "run_command", "synapse_add", "synapse_edit", "synapse_delete",
    # Starting and steering other work, and what is scheduled or planned for the owner.
    "assistant_job", "one_start", "one_say", "one_stop", "stop_task", "reply_to_task",
    "move_task", "rename_task", "move_step", "tidy_tasks", "schedule", "change_scheduled", "set_goal", "plan_goal",
    "goal_step", "goal_control",
})

#: Never a job's, whatever its scope: listed nowhere and refused if named.
NEVERS = frozenset({
    # The screen, the canvas and the orb, which are the owner's live chat.
    "show_on_screen", "what_was_on_screen", "show_again", "revise_on_screen", "set_panels",
    "show_canvas", "show_workspace_page", "show_inbox", "show_contact", "show_the_gaps",
    "ask_for_location", "rename_this_chat", "make_a_task", "pin",
    # Boxes and thoughts, which are the owner's to capture.
    "open_box", "new_box", "capture_thought",
    # What answers for the owner.
    "decisions", "actions", "one_answer", "answer_conflict", "delegate", "delegate_act",
    # Taking over and handing back a run's terminal, and the live browser the owner watches:
    # a job's own browser is headless, and hands a step to the live one by its report.
    "one_take", "one_give", "browser",
    # Rouh's own model doing the work: a job's own model does it, on its own subscription.
    "look_into", "make_picture", "change_picture", "synapse_generate",
    # The heartbeat's own, and the owner's control of it.
    "heartbeat", "quest", "long_work", "heartbeat_end", "heartbeat_ask", "heartbeat_brief",
    "heartbeat_ledger", "heartbeat_next", "heartbeat_thread",
    # What the outbox holds: a job queues with notify_owner, and never reads the others'.
    "worker_outbox",
    # A gene offered or drafted in the chat, with the owner.
    "gene_offer", "gene_draft",
    # The tools of a turn about a trusted contact's own message (`mail_turn.CASE_ONLY`).
    "case_report", "read_granted_tasks", "share_granted_page", "clockwork_for_contact",
    "remember_for_contact", "shared_task", "find_for_them", "read_capability",
    # The Synapse lab's own, in the Synapse chat.
    "synapse_settings", "synapse_eval", "synapse_trace", "synapse_learn", "synapse_dream",
    "synapse_improvements", "synapse_why",
})

#: Of the mail the registry reads, these take an inbox: a job of Rouh's own processes is held
#: to Rouh's own, as a beat is (`heartbeat.READS_MAIL`).
TAKES_INBOX = frozenset({"read_recent_mail", "read_mail", "read_mail_attachment"})

#: What a job doing a trusted contact's work may have run: that contact's conversation and
#: its files (Rouh holds it to that conversation in `rouh/job_mail.py`), asking Rouh, and the
#: public web.
CONTACT_MAY = frozenset({MAIL_FIND, MAIL_FILE, REQUEST, REQUEST_STATUS,
                         "youtube_search", "youtube_transcript"})

#: Arguments only the gateway reads, taken off before a tool is run or queued.
WHY_ARG = "rouh_why"


@dataclass(frozen=True)
class Ruling:
    """What becomes of one call: `RUN`, `PENDING` or `REFUSE`, why, and the tool's class."""

    verdict: str
    klass: str
    why: str = ""

    @property
    def runs(self) -> bool:
        return self.verdict == RUN


def _action(name: str, args: dict) -> str:
    said = args.get("action") if name != "goals" else args.get("act")
    said = str(said or "").strip().lower()
    return said or DEFAULT_ACTION.get(name, "")


def _said(value) -> bool:
    if value is None or value is False:
        return False
    if isinstance(value, (str, list, tuple, dict)):
        return bool(value) and str(value).strip().lower() not in ("", "primary")
    return True


def classify(name: str, args=None) -> str:
    """The class of this call, from the tool and its arguments alone. Unknown is `RISKY`."""
    name = str(name or "").strip()
    args = args if isinstance(args, dict) else {}
    if name in NEVERS:
        return NEVER
    if name in READS:
        return READ
    if name == "goals":
        return RISKY if _action(name, args) else READ
    if name == CORE_COMMAND:
        command = str(args.get("command") or "").strip()
        return READ if command in CORE_READS else OWN if command in CORE_MAINTENANCE else NEVER
    if name in READ_ACTIONS:
        if _action(name, args) in READ_ACTIONS[name]:
            return READ
        return OWN if _action(name, args) in OWN_ACTIONS.get(name, ()) else RISKY
    if name in READ_UNLESS:
        return RISKY if any(_said(args.get(k)) for k in READ_UNLESS[name]) else READ
    if name in OWNS:
        return OWN
    if name in OWN_UNLESS:
        return RISKY if any(_said(args.get(k)) for k in OWN_UNLESS[name]) else OWN
    # `RISKS`, and anything nobody has classified: it fails closed.
    return RISKY


def known(name: str) -> bool:
    """Whether this tool is written into one of the tables above, so what it does is known. A tool
    nobody has classified is risky (`classify`), and its effect cannot be worked out, so it is
    never run on the owner's word either: it always waits for their yes (`his_word.unknown`)."""
    name = str(name or "").strip()
    return (name in READS or name in READ_ACTIONS or name in READ_UNLESS or name in OWNS
            or name in OWN_UNLESS or name in RISKS or name in NEVERS or name == "goals"
            or name == CORE_COMMAND)


def listed(name: str) -> bool:
    """Whether a tool is listed to jobs at all: everything but `NEVERS`."""
    return str(name or "") not in NEVERS


def decide(scope: str, name: str, args=None) -> Ruling:
    """The one ruling on a job's call. Never reads anything but its three arguments."""
    args = args if isinstance(args, dict) else {}
    klass = classify(name, args)
    if scope not in SCOPES:
        return Ruling(REFUSE, klass, "Rouh cannot tell whom this job works for, so it does "
                                     "nothing for it.")
    if name == CORE_COMMAND and klass == NEVER:
        return Ruling(REFUSE, klass, (
            f"{str(args.get('command') or '')!r} is not on the core's list. The commands: "
            + ", ".join(sorted(CORE_READS | CORE_MAINTENANCE)) + "."))
    if klass == NEVER:
        return Ruling(REFUSE, klass, f"{name} is not something a background job may use: it "
                                     "belongs to the owner's own chat with Rouh.")
    if scope == CONTACT:
        if name in CONTACT_MAY:
            return Ruling(RUN, klass)
        if klass == RISKY:
            return Ruling(PENDING, klass)
        return Ruling(REFUSE, klass, (
            f"This job does a trusted contact's work, so it reaches only that contact's "
            f"conversation and the files in it (mail_find, mail_file), not {name}, which "
            "reads or changes the owner's own things. Ask with request_from_rouh if the work "
            "truly needs more."))
    if scope == PROCESS and name in TAKES_INBOX and \
            str(args.get("inbox") or "").strip().lower() != "rouh":
        return Ruling(REFUSE, klass, (
            "This job was started by one of Rouh's own processes, so it reads Rouh's own "
            "inbox only, as a heartbeat does. Call it again with inbox \"rouh\"."))
    if klass in (READ, OWN):
        return Ruling(RUN, klass)
    return Ruling(PENDING, klass)


__all__ = ["CONTACT", "CONTACT_MAY", "CORE_COMMAND", "CORE_MAINTENANCE", "CORE_READS", "NATIVE", "NEVER", "NEVERS", "OWN", "OWNER", "OWNS",
           "PENDING", "PROCESS", "READ", "READS", "READ_UNLESS", "REFUSE", "RISKS", "RISKY", "RUN",
           "Ruling", "SCOPES", "WHY_ARG", "classify", "decide", "known", "listed"]
