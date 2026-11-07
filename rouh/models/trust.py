"""Trusted contacts, and every email from one tracked from triage to the reply.

Petar, 30 September 2026: Rouh may handle routine, in-scope requests from a
contact he has explicitly trusted, by exact address, and must stop and ask him
before anything sensitive, uncertain or out of scope. What he trusts, and what
became of every email from somebody he trusts, is kept here
(`rouh/trusted.py`, `rouh/mail_cases.py`).

Every row carries `user_id` and `org_id` and is always asked for with both
(`AGENTS.md`, "Whose data is it").
"""
from django.db import models


class ContactGroup(models.Model):
    """A named queue approvals are sorted into. It never grants anything.

    A group only says where an email's approval is listed on the approvals
    page. Whether a sender is trusted, and for what, is on the contact alone
    (`TrustedContact`), and nothing reads a group to decide either.
    """

    id = models.BigAutoField(primary_key=True)
    user_id = models.TextField()
    org_id = models.TextField()
    name = models.TextField()
    created_at = models.FloatField(default=0)

    class Meta:
        db_table = "contact_groups"
        constraints = [models.UniqueConstraint(fields=["org_id", "user_id", "name"],
                                               name="contact_groups_one_name")]


class TrustedContact(models.Model):
    """One person Petar has said Rouh may deal with, and for what.

    `trusted` is the switch, pressed by him and by nobody else; turning it off
    keeps the row, its addresses, its levels and its grants, so turning it back on is
    one press. The addresses it covers are `TrustedAddress` rows, each an exact
    address he ticked: a new address that appears on the contact's card later
    is never covered until he ticks it too.
    """

    id = models.BigAutoField(primary_key=True)
    user_id = models.TextField()
    org_id = models.TextField()
    #: The contact this is (`people.Person.id`: c<card> or p<profile>), or "".
    contact_id = models.TextField(blank=True, default="")
    name = models.TextField(blank=True, default="")
    trusted = models.BooleanField(default=False)
    #: What Petar granted them (`trusted.LEVELS` keys): "communicate", then
    #: "tasks", then "use", each including the ones before it.
    levels = models.JSONField(default=list)
    #: The projects and tasks they may read at the "tasks" level, by object id,
    #: so a task that moves stays granted (`trusted.Grants`).
    grants = models.JSONField(default=list)
    #: How far Rouh may read Petar's own inbox for them (`trusted.INBOX_SCOPES`):
    #: "none", the default, "search", "senders", "read" or "write".
    inbox_scope = models.TextField(default="none", db_default="none")
    #: For "senders": the exact addresses, "@domain"s and "label:Name"s it reaches.
    inbox_from = models.JSONField(default=list, db_default=[])
    #: What happens to a request beyond everything set here (`trusted.BEYOND`):
    #: "ask", the default, "decline_tell" or "decline".
    beyond = models.TextField(default="ask", db_default="ask")
    #: Where they live, as an IANA name ("Europe/Lisbon"), or "" for not said (Petar, 11
    #: October 2026). A date or a time they give is read on this clock, and a Clockwork item
    #: made for them fires at a waking hour for whoever it reminds (`reminders.waking`).
    zone = models.TextField(blank=True, default="", db_default="")
    #: The silos of Petar's life Rouh may bring up for them (`rouh/silos.py`, `Silo.key`), or
    #: None for the silos shown to others until he says (`Silo.others`, Work to start with).
    #: Their Synapse questions and every workspace read beyond what he granted them by name keep
    #: to it; a list that holds every silo is no limit at all.
    sees = models.JSONField(null=True, blank=True, default=None)
    #: Where their approvals are listed. Organisation only, never permission.
    group = models.ForeignKey(ContactGroup, null=True, blank=True, on_delete=models.SET_NULL,
                              db_constraint=True, related_name="+")
    note = models.TextField(blank=True, default="")
    created_at = models.FloatField(default=0)
    updated_at = models.FloatField(default=0)
    #: Moves on every change to trust, addresses, levels, grants or topics, so an approval
    #: made under what was true before can tell it no longer is.
    revision = models.IntegerField(default=1)

    class Meta:
        db_table = "trusted_contacts"
        indexes = [models.Index(fields=["org_id", "user_id"], name="trusted_contacts_mine")]


class TrustedAddress(models.Model):
    """One exact address a trusted contact is recognised by, lower case."""

    id = models.BigAutoField(primary_key=True)
    user_id = models.TextField()
    org_id = models.TextField()
    contact = models.ForeignKey(TrustedContact, on_delete=models.CASCADE,
                                related_name="addresses")
    address = models.TextField()

    class Meta:
        db_table = "trusted_addresses"
        constraints = [models.UniqueConstraint(fields=["org_id", "user_id", "address"],
                                               name="trusted_addresses_once")]


class TelegramLink(models.Model):
    """A trusted contact's own Telegram account, linked by them and confirmed by Petar.

    Petar, 5 October 2026: a trusted contact may use Rouh over Telegram, held to exactly
    what she may do by email (`rouh/telegram_guests.py`). The link is made in
    three presses and never guessed: Petar makes a one-time code on her page
    ("waiting"); she sends it to the bot from her own Telegram account, which
    Telegram vouches for ("claimed", with that account's id); Petar confirms
    that account is hers ("linked"). Only a "linked" row lets a Telegram
    account through, and only as the contact it belongs to. The code itself is
    never kept, only its sha256, and it is spent the moment it is used.
    """

    id = models.BigAutoField(primary_key=True)
    user_id = models.TextField()
    org_id = models.TextField()
    contact = models.ForeignKey(TrustedContact, on_delete=models.CASCADE, related_name="+")
    #: "waiting" (a code is out), "claimed" (an account used it), "linked".
    state = models.TextField(default="waiting")
    code_hash = models.TextField(blank=True, default="")
    code_expires_at = models.FloatField(default=0)
    #: The Telegram account, as Telegram gave it with the message that used the code.
    tg_user_id = models.TextField(blank=True, default="")
    tg_name = models.TextField(blank=True, default="")
    tg_username = models.TextField(blank=True, default="")
    made_at = models.FloatField(default=0)
    claimed_at = models.FloatField(default=0)
    linked_at = models.FloatField(default=0)
    updated_at = models.FloatField(default=0)

    class Meta:
        db_table = "telegram_links"
        constraints = [
            models.UniqueConstraint(fields=["org_id", "user_id", "contact"],
                                    name="telegram_links_one_per_contact"),
            models.UniqueConstraint(fields=["org_id", "user_id", "tg_user_id"],
                                    condition=~models.Q(tg_user_id=""),
                                    name="telegram_links_one_per_account"),
        ]


class MailCase(models.Model):
    """One email from somebody other than Petar, and every stage of what became of it.

    Since 30 September 2026 not only a trusted contact's: anybody not on the
    Trusted contacts page is a case too, with no `contact` (an implicit
    contact, `trusted.implicit`). Junk caught on arrival is never a case; a
    case its reading finds junk is closed and kept, its email moved to Gmail's
    Spam (`CaseDesk._junk`), never deleted.

    Keyed by the email's Gmail message id, once per person, so a second look,
    a restart or a retry finds the same case and carries it on from the stage
    it reached rather than starting it again (`rouh/mail_cases.py`). Each stage
    that reaches the outside world - the reply, the note to Petar - is claimed
    here before it is done and recorded the moment it is, so it happens once.
    """

    id = models.BigAutoField(primary_key=True)
    user_id = models.TextField()
    org_id = models.TextField()
    message_id = models.TextField()
    #: The address of this case's page (`/mail/case/<key>`), random. The page
    #: is behind the sign-in and answers only the case's own person.
    key = models.TextField(unique=True)
    thread_id = models.TextField(blank=True, default="")
    chat_id = models.TextField(blank=True, default="")
    contact = models.ForeignKey(TrustedContact, null=True, blank=True,
                                on_delete=models.SET_NULL, related_name="+")
    sender = models.TextField(blank=True, default="")
    sender_name = models.TextField(blank=True, default="")
    subject = models.TextField(blank=True, default="")
    #: The email as it was triaged: headers and body, for the decision page.
    email = models.JSONField(default=dict)
    #: A hash of what the email says, to tell when it is no longer the same.
    digest = models.TextField(blank=True, default="")
    #: Gmail confirmed the From address, and how.
    identity_ok = models.BooleanField(default=False)
    identity_said = models.TextField(blank=True, default="")
    stage = models.TextField(default="new")
    #: What Rouh reported from each turn (`case_report`), by mode.
    assessment = models.JSONField(default=dict)
    #: Why Petar has to decide, one reason per line, and what was checked.
    reasons = models.JSONField(default=list)
    checks = models.JSONField(default=list)
    #: "direct", "granted", "approval", "nothing", "blocked", "refused" or "".
    route = models.TextField(blank=True, default="")
    proposed_action = models.TextField(blank=True, default="")
    proposed_reply = models.TextField(blank=True, default="")
    #: What Petar approved, exactly: the action and the reply that goes.
    approved_action = models.TextField(blank=True, default="")
    approved_reply = models.TextField(blank=True, default="")
    instruction = models.TextField(blank=True, default="")
    attempts = models.IntegerField(default=0)
    turn_started_at = models.FloatField(default=0)
    work_report = models.JSONField(default=dict)
    job_id = models.TextField(blank=True, default="")
    verified_at = models.FloatField(default=0)
    verified_said = models.TextField(blank=True, default="")
    #: The reply: claimed, then sent, then seen in the mailbox.
    reply_claimed_at = models.FloatField(default=0)
    #: The thread's sent messages when the reply was claimed, so a reply that
    #: went just before a crash is found rather than sent again.
    reply_before = models.JSONField(default=list)
    replied_at = models.FloatField(default=0)
    reply_message_id = models.TextField(blank=True, default="")
    #: The note to Petar about the outcome.
    notify_claimed_at = models.FloatField(default=0)
    notified_at = models.FloatField(default=0)
    notified_text = models.TextField(blank=True, default="")
    outcome = models.TextField(blank=True, default="")
    blocker = models.TextField(blank=True, default="")
    #: A step the work left that the contact's levels cannot do, handed on
    #: (`mail_cases.CaseDesk._hand_off`): the steps and why, whether a server
    #: job or Petar has it, the job's id, its state and what it reported.
    follow_up = models.JSONField(default=dict)
    #: What the work of its started asks sent back for the contact and has not gone yet
    #: (`mail_cases.CaseDesk.work_result`, MAIL.md D18): [{"asks", "label", "text", "files",
    #: "job", "at"}]. Results that come in within a few minutes of each other go in one message.
    results = models.JSONField(default=list, blank=True, db_default=[])
    #: The reply rewritten to say only what was verified, which goes when the
    #: rest cannot be finished (`mail_cases.CaseDesk._honest`), and what is
    #: still not done, for Petar.
    partial_reply = models.TextField(blank=True, default="")
    still_open = models.TextField(blank=True, default="")
    #: Which reply goes, or went: "full" (the approved one) or "partial".
    reply_kind = models.TextField(blank=True, default="")
    #: The reply exactly as it was sent.
    sent_reply = models.TextField(blank=True, default="")
    #: Petar's note for the next turn of a step he re-ran from the case page
    #: (`CaseDesk.rerun`): read by that turn's brief, cleared by a fresh read.
    step_note = models.TextField(blank=True, default="")
    #: Which attempt at the whole email this row is now: 1, and one more each
    #: time Petar pressed Redo (`CaseDesk.redo`). Not `attempts`, which counts
    #: the tries of one stage's turn. Every earlier attempt is a frozen
    #: `MailCaseAttempt`.
    attempt_no = models.IntegerField(default=1, db_default=1)
    #: Petar's own inbox for this email (`rouh/inbox_grants.py`): "once", what
    #: he allowed for this one email when he was asked; "asked", the narrowest
    #: reach the question to him offered; "used", the one search a "This search
    #: only" or "This thread" reach is bound to, what it found, and the thread.
    inbox_grant = models.JSONField(default=dict, db_default={})
    #: The files the work made for the reply (`rouh/case_files.py`): each one's
    #: path, name, type, size and sha256, as the work named it. One Petar took
    #: off the reply is kept, marked "removed".
    reply_files = models.JSONField(default=list, db_default=[])
    #: The files the reply goes with: those Petar approved, or that the reply
    #: check cleared where nobody had to approve, each with the hash it was
    #: cleared at. A file that no longer hashes the same does not go on it.
    approved_files = models.JSONField(default=list, db_default=[])
    #: The work done before Petar is asked, because all it does is make what
    #: the reply sends (`CaseDesk._prepare`): {"state": "preparing", "asked" or
    #: "failed", "at", "why"}. Empty when the case was never prepared first.
    prepared = models.JSONField(default=dict, db_default={})
    #: What Rouh's own code told the sender outside the reply, each once
    #: (`mail_cases.CaseDesk._acknowledge`, `CaseDesk._tell_waiting`):
    #: {"ack_at", "ack", "wait_at", "wait", "waiting"}. Older cases may also hold
    #: "status_at", "status" and "status_sig" from the quiet-spell updates removed
    #: on 11 October 2026. {"before": true} on a case already open when these
    #: began (6 October 2026), which is told nothing.
    told = models.JSONField(default=dict, db_default={})
    #: Newer messages in the same conversation that did not change what this
    #: case asks, kept on it as more context (`CaseDesk._newer_in_thread`):
    #: [{"key", "at", "summary", "words"}].
    later = models.JSONField(default=list, db_default=[])
    #: The same request that came again, attached to this case instead of becoming one of its
    #: own (Petar, 11 October 2026, `mail_cases.CaseDesk.attach`): [{"key", "message_id",
    #: "channel", "telegram_id", "at", "words"}]. The reply goes on each channel they came on.
    arrivals = models.JSONField(default=list, blank=True, db_default=[])
    #: The case this one was attached to as the same request, when it was (its stage is
    #: then "merged" and nothing of it is done on its own).
    merged_into = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL,
                                    related_name="+")
    created_at = models.FloatField(default=0)
    updated_at = models.FloatField(default=0)

    class Meta:
        db_table = "mail_cases"
        constraints = [models.UniqueConstraint(fields=["org_id", "user_id", "message_id"],
                                               name="mail_cases_once_per_message")]
        indexes = [models.Index(fields=["org_id", "user_id", "stage"], name="mail_cases_stage")]


class MailApproval(models.Model):
    """One question to Petar about a case, bound to exactly what he was shown.

    `fingerprint` is a hash of the email, the proposed action, the proposed
    reply and the contact's trust as they stood when it was asked. A decision
    is taken only while all of those still hash the same; otherwise it is
    refused and the approval is superseded, and a new one has to be asked.
    It never runs out of time (Petar, 8 October 2026).
    """

    id = models.BigAutoField(primary_key=True)
    user_id = models.TextField()
    org_id = models.TextField()
    case = models.ForeignKey(MailCase, on_delete=models.CASCADE, related_name="approvals")
    fingerprint = models.TextField()
    proposed_action = models.TextField(blank=True, default="")
    proposed_reply = models.TextField(blank=True, default="")
    #: "pending", "approved", "declined", "instructed", "superseded", "dismissed"
    #: (closed without a decision, nothing done), or "expired", which is history
    #: only: the 48-hour limit before 8 October 2026; those were all dismissed.
    status = models.TextField(default="pending")
    decided_reply = models.TextField(blank=True, default="")
    edited = models.BooleanField(default=False)
    instruction = models.TextField(blank=True, default="")
    why_invalid = models.TextField(blank=True, default="")
    asked_at = models.FloatField(default=0)
    #: History only: the 48-hour limit approvals carried before 8 October 2026.
    #: Nothing reads it to decide anything, and new approvals leave it at 0.
    expires_at = models.FloatField(default=0)
    decided_at = models.FloatField(default=0)
    decided_by = models.TextField(blank=True, default="")
    notified_at = models.FloatField(default=0)
    #: The attempt at the email it was asked in (`MailCase.attempt_no`).
    attempt_no = models.IntegerField(default=1, db_default=1)
    #: The files the reply was shown with, each with its sha256: the approval
    #: covers exactly these (`rouh/case_files.py`).
    files = models.JSONField(default=list, db_default=[])
    #: When Petar was reminded of it, once (`mail_cases.CaseDesk._remind`).
    reminded_at = models.FloatField(default=0, db_default=0)
    #: What the sender was told at once when he said yes, on decisions made before the
    #: ledger (11 October 2026); kept so their history reads as it was. Nothing new sets it.
    immediate_reply = models.TextField(blank=True, default="", db_default="")
    #: "asks", the one decision of a case: the asks of its ledger that need Petar
    #: (`mail_cases.CaseDesk.sync_decision`, D8). "reply" is a decision made before the
    #: ledger, kept as history.
    kind = models.TextField(blank=True, default="reply", db_default="reply")
    #: The asks waiting on him when it was made, each as the ledger had it
    #: (`mail_ledger.Ask.as_dict`); a newer ledger supersedes it with a new decision.
    asks = models.JSONField(default=list, blank=True, db_default=[])
    #: What he chose for each, with the grant edits he made on the case page, kept
    #: as it was applied: {ask id: {"choice", "target", "name", "description",
    #: "prompt", "prompt_addition", "parent", "give", "said"}}.
    answers = models.JSONField(default=dict, blank=True, db_default={})

    class Meta:
        db_table = "mail_approvals"
        indexes = [models.Index(fields=["org_id", "user_id", "status"],
                                name="mail_approvals_status")]


class MailAsk(models.Model):
    """One thing a message asks, and where it stands: the ledger of a case (`rouh/mail_ledger.py`).

    Petar, 11 October 2026, after two weeks of fixes that each patched one gate: one ledger of
    asks per case is the single source of truth. Reading a message produces its asks; each has
    the sender's own words, the grant it needs ("none" for an answer alone), a hard limit it
    touches, and a status that only code sets: allowed (the contact holds what it needs),
    waiting_for_owner (waiting_for_petar on older rows), approved (the owner said yes to it),
    declined (by the owner, the only refusal
    there is), done (with evidence of what was done, by id) or failed (tried, and why not).
    The route, the case page, Decisions, Test grants, the status part of every message to the
    contact and the case's stage all read these rows, and nothing else holds status.
    """

    id = models.BigAutoField(primary_key=True)
    user_id = models.TextField()
    org_id = models.TextField()
    case = models.ForeignKey(MailCase, on_delete=models.CASCADE, related_name="ledger")
    #: Stable across readings: the same words are the same ask (`mail_ledger.ident_of`).
    ident = models.TextField()
    #: Its place in the message, from 1.
    n = models.IntegerField(default=0)
    #: The attempt that last read or acted on it.
    attempt = models.IntegerField(default=1)
    #: The sender's own words, quoted.
    quote = models.TextField(blank=True, default="")
    #: What it is, in a few words to the sender, in their language ("keep your Rome tickets
    #: for Alex"): how the status part of a message names it.
    label = models.TextField(blank=True, default="")
    #: What Rouh does for it, in Rouh's words.
    do = models.TextField(blank=True, default="")
    #: The grant it needs, by key; "none" for an answer alone; "" when no grant covers it yet.
    grant = models.TextField(blank=True, default="")
    #: A grant Rouh's reading proposes when none covers it: {name, title, description,
    #: suggestion, target, prompt, prompt_addition, nearest, why_not}.
    new_grant = models.JSONField(default=dict, blank=True)
    #: The other grants it needs as well, beyond `grant` (Petar, 12 October 2026): a Clockwork
    #: ask does at a time what these allow, so "remind both of us" also needs Communication.
    also = models.JSONField(default=list, blank=True)
    #: A hard limit it touches (`grants.HARD_LIMITS`), or "".
    hard_limit = models.TextField(blank=True, default="")
    #: The number of one of Petar's tasks it adds to or changes ("90"), or "": what it needs
    #: then is to be allowed to edit that task, a permission of the task and never a grant
    #: (`rouh/task_access.py`, MAIL.md D28).
    task = models.TextField(blank=True, default="", db_default="")
    #: What it needs on that task: "read" (research, a timeline, an answer about it), or "" for
    #: adding to or changing it, which needs edit (`rouh/task_access.py`, 21 October 2026).
    task_needs = models.TextField(blank=True, default="", db_default="")
    #: The capability the reading named for it (`rouh/capabilities.py`, MAIL.md D35), the
    #: resources it names - task numbers, calendar ids - and the values it asks within the
    #: capability's limits; "unsupported" when nothing Rouh has does it.
    capability = models.TextField(blank=True, default="", db_default="")
    scope = models.JSONField(default=list, blank=True, db_default=[])
    values = models.JSONField(default=dict, blank=True, db_default={})
    #: allowed, waiting_for_owner (waiting_for_petar on rows from before migration 0195,
    #: which rewrote them), approved, declined, started, done or failed.
    status = models.TextField(default="waiting_for_owner")
    #: Why it stands there, one sentence the code wrote.
    why = models.TextField(blank=True, default="")
    #: Petar's own choice for it: "grant" (give the grant permanently), "once", "decline",
    #: "mine" (he sees to it himself), or "".
    choice = models.TextField(blank=True, default="")
    choice_by = models.TextField(blank=True, default="")
    choice_at = models.FloatField(default=0)
    #: The grant he set up or gave for it from the case, by key.
    choice_grant = models.TextField(blank=True, default="")
    #: What was done for it, each with the ids that show it: [{"at", "attempt", "said", "ids"}].
    evidence = models.JSONField(default=list, blank=True)
    #: The work it was started as, once the gate let it go (MAIL.md D18): [{"kind", "ref",
    #: "title", "at"}] - a job, a Clockwork item, a task, a note kept. Its status is read from
    #: that work wherever it is shown, never kept here.
    work = models.JSONField(default=list, blank=True, db_default=[])
    #: "reading", "work" (raised by started work that needed something new, before 16 October
    #: 2026: now that goes onto the ask it stopped, `blocker`), "follow_up" (a step the check
    #: named), "whole" (a message read before asks were kept, or not read at all) or
    #: "migrated".
    source = models.TextField(blank=True, default="reading")
    #: For an ask the work raised: the id of the ask it serves, the one in the sender's own
    #: words, so the case page names it by what they asked and quotes them (Petar, 15 October
    #: 2026, fr_1dd66d24e1f6). "" when the work did not say.
    serves = models.TextField(blank=True, default="", db_default="")
    #: What stopped its work, in the work's own words, when the work met a need the gate had
    #: not decided: what it waits for is then on this ask - its task, hard limit or grant -
    #: never on a new ask (Petar, 16 October 2026, MAIL.md D29). "" when nothing stopped it.
    blocker = models.TextField(blank=True, default="", db_default="")
    #: Read in an earlier attempt and not in the latest one: kept, and counted for nothing.
    gone = models.BooleanField(default=False)
    created_at = models.FloatField(default=0)
    updated_at = models.FloatField(default=0)

    class Meta:
        db_table = "mail_asks"
        constraints = [models.UniqueConstraint(fields=["case", "ident"], name="mail_asks_once")]
        indexes = [models.Index(fields=["org_id", "user_id", "status"], name="mail_asks_status")]


class MailOutbox(models.Model):
    """Every message Rouh sends to somebody other than Petar about a case: the one outbox.

    Petar, 11 October 2026, after a contact got the same holding and status notes twice and an
    automatic re-read answered a case of 2 October without him: one function sends every
    such message (`rouh/mail_outbox.py`), keyed by case, attempt, kind and channel, so it
    goes at most once; written down before it goes and when it went. At most one
    acknowledgement per case, and a reply or a status update only when the ledger changed
    since the last one that went (`ledger`). Linking notes to a Telegram account that has no
    case yet have no case.
    """

    id = models.BigAutoField(primary_key=True)
    user_id = models.TextField()
    org_id = models.TextField()
    case = models.ForeignKey(MailCase, null=True, blank=True, on_delete=models.CASCADE,
                             related_name="outbox")
    #: What makes it once: "<case>:ack:<channel>", "<case>:<attempt>:reply:<channel>" ...
    key = models.TextField()
    attempt = models.IntegerField(default=0)
    #: "ack", "reply", "status", "follow_up" or "link".
    kind = models.TextField()
    #: "email" or "telegram", and the address or the Telegram account it went to.
    channel = models.TextField()
    to = models.TextField(blank=True, default="")
    text = models.TextField(blank=True, default="")
    files = models.JSONField(default=list, blank=True)
    #: The ledger as this message said it: [[ident, status], ...] (`mail_ledger.said_state`).
    ledger = models.JSONField(default=list, blank=True)
    #: "claimed", "sent", "failed", "refused" or "unknown" (claimed, and a restart came
    #: before it was known to have gone).
    state = models.TextField(default="claimed")
    message_id = models.TextField(blank=True, default="")
    error = models.TextField(blank=True, default="")
    #: An email thread's sent messages when it was claimed, to find it after a restart.
    thread_before = models.JSONField(default=list, blank=True)
    claimed_at = models.FloatField(default=0)
    sent_at = models.FloatField(default=0)

    class Meta:
        db_table = "mail_outbox"
        constraints = [models.UniqueConstraint(fields=["org_id", "user_id", "key"],
                                               name="mail_outbox_once")]
        indexes = [models.Index(fields=["org_id", "user_id", "case"], name="mail_outbox_case")]


class MailCaseEvent(models.Model):
    """One step a case took, for its timeline on the case page."""

    id = models.BigAutoField(primary_key=True)
    user_id = models.TextField()
    org_id = models.TextField()
    case = models.ForeignKey(MailCase, on_delete=models.CASCADE, related_name="events")
    at = models.FloatField()
    stage = models.TextField(blank=True, default="")
    said = models.TextField(blank=True, default="")

    class Meta:
        db_table = "mail_case_events"


class MailCaseTrace(models.Model):
    """What went into a step of a case and what came out, for debugging it.

    Petar, 1 October 2026: the case page is for understanding each check -
    what was passed to it, what it decided and why - and tuning it, since most
    cases that stop are false alarms. So every turn's brief and the tools and
    levels it had ("turn"), every report it made ("report"), the code's routing
    of it rule by rule ("route"), and a turn's trouble ("trouble") are kept
    here, append only, one row each (`rouh/case_trace.py` draws them). The
    prompts as sent are in `llm_requests`, under the case's chat.
    """

    id = models.BigAutoField(primary_key=True)
    user_id = models.TextField()
    org_id = models.TextField()
    case = models.ForeignKey(MailCase, on_delete=models.CASCADE, related_name="traces")
    at = models.FloatField()
    kind = models.TextField()
    #: assess, carry_out or verify for a turn's rows.
    mode = models.TextField(blank=True, default="")
    attempt = models.IntegerField(default=0)
    data = models.JSONField(default=dict)

    class Meta:
        db_table = "mail_case_traces"
        indexes = [models.Index(fields=["org_id", "user_id", "case", "at"],
                                name="mail_case_traces_case")]


class MailCaseNote(models.Model):
    """What Petar said about a case while tuning it: kept for tuning the pipeline.

    A false alarm and why, a real problem, a step he re-ran and what he told it,
    a question he asked on the page and the answer it got. Read back on the case
    page, in the brief for another run, and by `manage.py case_notes`.
    """

    id = models.BigAutoField(primary_key=True)
    user_id = models.TextField()
    org_id = models.TextField()
    case = models.ForeignKey(MailCase, on_delete=models.CASCADE, related_name="notes")
    at = models.FloatField()
    #: "false_alarm", "real_problem", "rerun" or "question".
    kind = models.TextField()
    #: Which step it is about, as the case page names it ("verify-1").
    step = models.TextField(blank=True, default="")
    text = models.TextField(blank=True, default="")
    answer = models.TextField(blank=True, default="")
    data = models.JSONField(default=dict)

    class Meta:
        db_table = "mail_case_notes"
        indexes = [models.Index(fields=["org_id", "user_id", "kind", "at"],
                                name="mail_case_notes_kind")]


class MailCaseAttempt(models.Model):
    """One earlier attempt at a case's email, frozen when Petar pressed Redo.

    Petar, 2 October 2026: a case that is blocked, or whose decision expired,
    can be started again from the top of its page as a fresh attempt, with his
    own instructions, and the old attempt and its decisions stay as they were,
    marked superseded, never deleted or rewritten (`CaseDesk.redo`). This row
    is written once, in the same transaction that moves the case on to the next
    attempt, and nothing ever updates it. Its approvals are the case's
    `MailApproval` rows with its `attempt_no`; its events are the case's events
    up to `ended_at`.

    One row per (case, number), so two presses of Redo on the same attempt can
    never make two new attempts: the second finds the first's row.
    """

    id = models.BigAutoField(primary_key=True)
    user_id = models.TextField()
    org_id = models.TextField()
    case = models.ForeignKey(MailCase, on_delete=models.CASCADE, related_name="earlier")
    #: Which attempt this was (1 for the first).
    number = models.IntegerField()
    started_at = models.FloatField(default=0)
    #: When it was superseded: the moment Redo was pressed.
    ended_at = models.FloatField(default=0)
    #: Always "superseded": an attempt is only ever frozen by a redo.
    status = models.TextField(default="superseded")
    #: The attempt that replaced it, and who pressed Redo, with what words.
    superseded_by = models.IntegerField(default=0)
    redone_by = models.TextField(blank=True, default="")
    redo_instruction = models.TextField(blank=True, default="")
    #: Where it stood when it was superseded: blocked, or waiting on a lapsed decision.
    end_stage = models.TextField(blank=True, default="")
    #: The case's own fields as they were at that moment, whole.
    snapshot = models.JSONField(default=dict)
    #: What it had done that reached the outside world, on attempts before the ledger;
    #: since 11 October 2026 that is the case's outbox (`mail_outbox`).
    effects = models.JSONField(default=list)

    class Meta:
        db_table = "mail_case_attempts"
        constraints = [models.UniqueConstraint(fields=["case", "number"],
                                               name="mail_case_attempts_once")]


class InboxRead(models.Model):
    """One read of Petar's own inbox done for a trusted contact, kept against them.

    Petar, 2 October 2026: every read of his inbox done for a contact is
    logged against that contact, and their page shows the latest ones
    (`rouh/inbox_grants.py`). A search is one row with what it asked and how
    many it found; a message or a file read is one row with which.
    """

    id = models.BigAutoField(primary_key=True)
    user_id = models.TextField()
    org_id = models.TextField()
    contact = models.ForeignKey(TrustedContact, on_delete=models.CASCADE, related_name="+")
    #: The case it was read for, and its page's key, for the link.
    case_id = models.BigIntegerField(default=0)
    case_key = models.TextField(blank=True, default="")
    at = models.FloatField(default=0)
    #: "search", "read" or "file".
    kind = models.TextField(default="read")
    #: Which of his inboxes, by address.
    inbox = models.TextField(blank=True, default="")
    query = models.TextField(blank=True, default="")
    message_id = models.TextField(blank=True, default="")
    subject = models.TextField(blank=True, default="")
    sender = models.TextField(blank=True, default="")
    found = models.IntegerField(default=0)
    #: The reach it was read under (`trusted.INBOX_SCOPES`), and whether it was
    #: the contact's standing setting or allowed once for this email.
    scope = models.TextField(blank=True, default="")
    source = models.TextField(blank=True, default="")

    class Meta:
        db_table = "trusted_inbox_reads"
        indexes = [models.Index(fields=["org_id", "user_id", "contact", "at"],
                                name="trusted_inbox_reads_latest")]


class MailCaseFix(models.Model):
    """One run that fixes the check behind a step Petar marked a false alarm (`rouh/case_fixes.py`).

    Petar, 8 October 2026, by voice: marking a step of a mail or Telegram case
    a false alarm starts one run of the one program on Rouh's own code, which
    finds why the step stopped the case, fixes the cause in general, proves it
    on this case and on every case he marked before, lands and deploys it, and
    re-runs the case. The case page shows where it is while it runs and what
    it did when it ends. One row is one such run, and at most one is going for
    a case's step at a time (`active`): marking the step again adds the reason
    to the one going.
    """

    id = models.BigAutoField(primary_key=True)
    user_id = models.TextField()
    org_id = models.TextField()
    case = models.ForeignKey(MailCase, on_delete=models.CASCADE, related_name="fixes")
    #: The step, as the case page names it ("route-1", "verify-1").
    step = models.TextField()
    #: Whether its run is still going. At most one per case and step.
    active = models.BooleanField(default=True)
    #: "queued", "running" or "ended".
    state = models.TextField(default="queued")
    #: How it ended: "fixed", "nothing" (no change was needed), "needs_owner" ("needs_petar" on
    #: older rows; only a change to a safety rule would do, and that is the owner's), "failed", "stopped", or "".
    outcome = models.TextField(blank=True, default="")
    #: What it is doing now, as one of `case_fixes.PHASES`, and in its own words.
    phase = models.TextField(blank=True, default="")
    phase_said = models.TextField(blank=True, default="")
    phase_at = models.FloatField(default=0)
    #: How many earlier marked cases it is replaying, when it says.
    replaying = models.IntegerField(default=0)
    run_id = models.TextField(blank=True, default="")
    #: Every reason Petar gave for this step while it ran: [{"at", "text", "note", "handed"}].
    reasons = models.JSONField(default=list)
    #: What the run said when it ended: done, why, different, files, rule, replayed, same,
    #: needs; the plain words of the summary card.
    summary = models.JSONField(default=dict)
    #: The commit it landed, as found on main by its `Case-fix:` line.
    commit = models.TextField(blank=True, default="")
    deployed_at = models.FloatField(default=0)
    #: The case run again after the fix: when, as which attempt, or why not.
    rerun_at = models.FloatField(default=0)
    rerun_attempt = models.IntegerField(default=0)
    rerun_said = models.TextField(blank=True, default="")
    #: Undo: the run reverting the commit, and the revert once it is deployed.
    undo_run_id = models.TextField(blank=True, default="")
    undo_state = models.TextField(blank=True, default="")
    undo_commit = models.TextField(blank=True, default="")
    undo_at = models.FloatField(default=0)
    #: Why it could not start or did not finish, when that is all there is to say.
    why = models.TextField(blank=True, default="")
    #: When Petar's phone was told it landed or failed: once.
    told_at = models.FloatField(default=0)
    #: His answer to a fix that failed or needs him, from Decisions: "again" or "leave",
    #: and his own words with it.
    verdict = models.TextField(blank=True, default="")
    words = models.TextField(blank=True, default="")
    started_at = models.FloatField(default=0)
    ended_at = models.FloatField(default=0)
    created_at = models.FloatField(default=0)

    class Meta:
        db_table = "mail_case_fixes"
        constraints = [models.UniqueConstraint(
            fields=["org_id", "user_id", "case", "step"], condition=models.Q(active=True),
            name="mail_case_fixes_one_going")]
        indexes = [models.Index(fields=["org_id", "user_id", "case"], name="mail_case_fixes_case"),
                   models.Index(fields=["run_id"], name="mail_case_fixes_run")]


class DelegateAct(models.Model):
    """One thing a delegate did, tried, or had held for Petar, with their exact words.

    The record Petar reads on the contact's page, the goal's and the quest's, the decision's
    and the morning brief, and what Undo puts back (`undo`)."""

    id = models.BigAutoField(primary_key=True)
    user_id = models.TextField()
    org_id = models.TextField()
    contact = models.ForeignKey(TrustedContact, null=True, blank=True,
                                on_delete=models.SET_NULL, related_name="+")
    contact_name = models.TextField(blank=True, default="")
    #: The permission it was done under (`PageGuest.token`, `rouh/task_access.py`), or "".
    grant = models.TextField(blank=True, default="", db_default="")
    #: decide, step, plan, deadline, quest, research, briefed, grant, extend, revoke, undo.
    act = models.TextField()
    #: What it was about: "goal", "quest", "task" or "decision", its id, number and title.
    target_kind = models.TextField(blank=True, default="")
    target = models.TextField(blank=True, default="")
    number = models.IntegerField(default=0)
    title = models.TextField(blank=True, default="")
    #: Their own words, exactly as they wrote them.
    words = models.TextField(blank=True, default="")
    #: What was done, in plain words, and what was asked of the tool.
    said = models.TextField(blank=True, default="")
    asked = models.JSONField(default=dict)
    #: "done", "refused", "for_owner" ("for_petar" on older rows: held for
    #: the owner, with their recommendation), "answered" (the owner answered what was held) or "undone".
    outcome = models.TextField(default="done")
    why = models.TextField(blank=True, default="")
    decision_id = models.BigIntegerField(null=True, blank=True)
    #: The decision's number as the person says it ("42"); its handle (a482) before 18 October
    #: 2026, when decisions were given handles (`decision_numbers`).
    handle = models.TextField(blank=True, default="")
    case_id = models.BigIntegerField(null=True, blank=True)
    #: "email", "telegram", "settings", "voice" or "rouh".
    channel = models.TextField(blank=True, default="")
    #: What it takes to put it back as it was.
    undo = models.JSONField(default=dict)
    #: The same email read twice does the same action once.
    key = models.TextField(blank=True, default="")
    at = models.FloatField(default=0)
    undone_at = models.FloatField(default=0)
    undone_said = models.TextField(blank=True, default="")

    class Meta:
        db_table = "delegate_acts"
        indexes = [models.Index(fields=["org_id", "user_id", "at"], name="delegate_acts_when"),
                   models.Index(fields=["org_id", "user_id", "contact"], name="delegate_acts_contact"),
                   models.Index(fields=["org_id", "user_id", "decision_id"],
                                name="delegate_acts_decision"),
                   models.Index(fields=["org_id", "user_id", "key"], name="delegate_acts_key")]


# --- grants: what Petar can give a trusted contact, as rows (`rouh/grants.py`) -------------


class Grant(models.Model):
    """One thing Petar can give a trusted contact, per organisation.

    Petar, 11 October 2026, after a trusted contact's itinerary was held on a
    catch-all nothing could grant: what a contact may be given is data, not a
    dict in the code. Each grant has a canonical name, a one-line title and a
    description for Petar, the prompt the assessment is given about what it
    covers, and an optional parent:
    giving a contact a parent gives them every sub grant under it, and a sub
    grant can be given on its own (`rouh/grants.py`). Every change to the name,
    title, description, prompt or parent is a `GrantVersion`.

    `holding` says where a contact's holding of it is kept: "level" in
    `TrustedContact.levels`, "inbox" in `TrustedContact.inbox_scope`, "grant" in
    `ContactGrant`. A grant merged into another is kept, with `merged_into`, and
    whoever held it holds the other.
    """

    id = models.BigAutoField(primary_key=True)
    org_id = models.TextField()
    #: The id the assessment names it by, stable across renames: "use", "clockwork",
    #: or one made for a new grant ("g-flight-plans-3f2a").
    key = models.TextField()
    #: Its canonical name ("Clockwork").
    name = models.TextField()
    #: One line in plain words on what it lets Rouh do for the contact, shown under the name
    #: (Petar, 11 October 2026).
    title = models.TextField(blank=True, db_default="", default="")
    #: The detailed explanation of the grant and what it gives.
    description = models.TextField(blank=True, default="")
    prompt = models.TextField(blank=True, default="")
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL,
                               related_name="+")
    holding = models.TextField(default="grant")
    #: The case tools it adds to a turn inside it (`mail_turn`); a sub grant with
    #: none uses its parent's.
    tools = models.JSONField(default=list, blank=True)
    merged_into = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL,
                                    related_name="+")
    position = models.IntegerField(default=0)
    revision = models.IntegerField(default=1)
    created_at = models.FloatField(default=0)
    created_by = models.TextField(blank=True, default="")
    updated_at = models.FloatField(default=0)

    class Meta:
        db_table = "grants"
        constraints = [models.UniqueConstraint(fields=["org_id", "key"], name="grants_one_key")]


class GrantVersion(models.Model):
    """One version of a grant's name, title, description, prompt and parent, kept forever."""

    id = models.BigAutoField(primary_key=True)
    org_id = models.TextField()
    grant = models.ForeignKey(Grant, on_delete=models.CASCADE, related_name="versions")
    revision = models.IntegerField()
    name = models.TextField()
    title = models.TextField(blank=True, db_default="", default="")
    description = models.TextField(blank=True, default="")
    prompt = models.TextField(blank=True, default="")
    parent_key = models.TextField(blank=True, default="")
    at = models.FloatField()
    by = models.TextField(blank=True, default="")
    #: Why it changed, in plain words ("Merged in from Sam Rivera's email").
    why = models.TextField(blank=True, default="")
    #: The case it came from, by its key, when it came from one.
    case_key = models.TextField(blank=True, default="")

    class Meta:
        db_table = "grant_versions"
        constraints = [models.UniqueConstraint(fields=["grant", "revision"],
                                               name="grant_versions_once")]


class ContactGrant(models.Model):
    """A grant of holding "grant" that Petar gave one trusted contact."""

    id = models.BigAutoField(primary_key=True)
    user_id = models.TextField()
    org_id = models.TextField()
    contact = models.ForeignKey(TrustedContact, on_delete=models.CASCADE, related_name="+")
    grant = models.ForeignKey(Grant, on_delete=models.CASCADE, related_name="+")
    given_at = models.FloatField(default=0)
    given_by = models.TextField(blank=True, default="")
    #: The case it was given from, by its key, or "" from the contact's page.
    from_case = models.TextField(blank=True, default="")
    #: For a grant that lifts committing his time (`grants.LIFTS`), the ids of the calendars it
    #: reaches, as ticked on the contact's page; None is every calendar, as before 16 October
    #: 2026 (`grants.calendars_of`).
    calendars = models.JSONField(null=True, blank=True, default=None)

    class Meta:
        db_table = "contact_grants"
        constraints = [models.UniqueConstraint(fields=["org_id", "user_id", "contact", "grant"],
                                               name="contact_grants_once")]


class MailCaseDryRun(models.Model):
    """One Test of a case: run again with nothing sent and nothing lasting changed.

    Petar, 11 October 2026: after setting the grants a held email needs, he
    presses Test and sees the whole case go again - the reading, the route per
    ask, the work, the check, the reply check - as a step-by-step timeline, with
    every tool that would send, write or schedule replaced by a recorder
    (`rouh/case_dry_run.py`). It never marks the case done or answers a decision.
    """

    id = models.BigAutoField(primary_key=True)
    user_id = models.TextField()
    org_id = models.TextField()
    case = models.ForeignKey(MailCase, on_delete=models.CASCADE, related_name="dry_runs")
    #: "running", "done" or "failed".
    state = models.TextField(default="running")
    started_at = models.FloatField(default=0)
    ended_at = models.FloatField(default=0)
    #: The throwaway conversation its turns ran in, so its requests and cost are its own.
    chat_id = models.TextField(blank=True, default="")
    #: What it was run with: the grants as they stood, the one-time passes.
    setup = models.JSONField(default=dict)
    #: [{"at", "who", "step", "given", "decided", "raw"}], the timeline.
    steps = models.JSONField(default=list)
    #: Where it ended, in a sentence, and what it would have sent or done.
    said = models.TextField(blank=True, default="")
    cost = models.FloatField(default=0)

    class Meta:
        db_table = "mail_case_dry_runs"
        indexes = [models.Index(fields=["org_id", "user_id", "case"], name="mail_case_dry_runs_case")]


class CapabilityGrant(models.Model):
    """One grant as data (CAPABILITIES.md, `rouh/capability_grants.py`): one trusted contact, one
    capability at one contract version, an exact scope, typed limits and a lifetime, worded by
    code from exactly those fields and approved by their digest. A proposal is a row too, and
    every row is kept: declined, taken back, used up, suspended or replaced, never deleted."""

    id = models.BigAutoField(primary_key=True)
    user_id = models.TextField()
    org_id = models.TextField()
    contact = models.ForeignKey(TrustedContact, on_delete=models.CASCADE, related_name="+")
    #: The capability's id (`capabilities.Capability.id`) and the contract version it was made for.
    capability = models.TextField()
    version = models.IntegerField()
    #: The resources it reaches, by id (task numbers, calendar ids); [] for none or their own.
    scope = models.JSONField(default=list)
    #: {limit: value}, every limit the capability declares.
    limits = models.JSONField(default=dict)
    #: "once", "until" (with `until`, a day, and `expires_at`, its end) or "standing".
    lifetime = models.TextField()
    until = models.TextField(blank=True, default="")
    expires_at = models.FloatField(null=True, blank=True, default=None)
    max_uses = models.IntegerField(null=True, blank=True, default=None)
    used = models.IntegerField(default=0)
    #: proposed, active, rejected, revoked, spent, suspended or replaced (`capabilities`).
    state = models.TextField()
    #: The hash of the fields the owner was shown and approved (`capabilities.digest`), and the
    #: sentence they were shown, made by code from those fields.
    digest = models.TextField()
    wording = models.TextField(blank=True, default="")
    #: What it came from: the reading's own report of the ask, kept as it was, and who proposed
    #: it ("code, from case_read on <model>", or "owner").
    proposal = models.JSONField(default=dict)
    proposed_by = models.TextField(blank=True, default="")
    case_key = models.TextField(blank=True, default="")
    ask_ident = models.TextField(blank=True, default="")
    approved_by = models.TextField(blank=True, default="")
    approved_at = models.FloatField(null=True, blank=True, default=None)
    ended_by = models.TextField(blank=True, default="")
    ended_at = models.FloatField(null=True, blank=True, default=None)
    #: The owner's own words when they declined or took it back, and why it was suspended.
    reason = models.TextField(blank=True, default="")
    suspended_reason = models.TextField(blank=True, default="")
    replaces = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL,
                                 related_name="+")
    created_at = models.FloatField(default=0)
    updated_at = models.FloatField(default=0)

    class Meta:
        db_table = "capability_grants"
        indexes = [models.Index(fields=["org_id", "user_id", "contact", "state"],
                                name="capability_grants_held"),
                   models.Index(fields=["org_id", "user_id", "case_key"],
                                name="capability_grants_case")]


class CapabilityGrantEvent(models.Model):
    """What happened to a grant, kept forever: proposed, narrowed, approved, declined, taken back,
    suspended, resumed, used, refused, migrated."""

    id = models.BigAutoField(primary_key=True)
    user_id = models.TextField()
    org_id = models.TextField()
    grant = models.ForeignKey(CapabilityGrant, on_delete=models.CASCADE, related_name="events")
    at = models.FloatField()
    by = models.TextField(blank=True, default="")
    kind = models.TextField()
    digest = models.TextField(blank=True, default="")
    detail = models.JSONField(default=dict)

    class Meta:
        db_table = "capability_grant_events"
        indexes = [models.Index(fields=["org_id", "user_id", "grant"],
                                name="capability_grant_events_of")]


class CapabilityUse(models.Model):
    """One call a grant covered, claimed before it runs: the same call of the same case is one
    row, so a retry finds it done and never does it twice, and a grant allowed once is claimed by
    one ask alone, under a row lock (`capability_grants.claim`). `grant_ref` names the authority:
    "row:<id>" for a grant of its own, "held:<key>:<contact>" or "level:<tasks>:<contact>"."""

    id = models.BigAutoField(primary_key=True)
    user_id = models.TextField()
    org_id = models.TextField()
    grant = models.ForeignKey(CapabilityGrant, null=True, blank=True, on_delete=models.CASCADE,
                              related_name="uses")
    grant_ref = models.TextField()
    call_key = models.TextField()
    use_key = models.TextField(blank=True, default="")
    case_key = models.TextField(blank=True, default="")
    ask_ident = models.TextField(blank=True, default="")
    tool = models.TextField(blank=True, default="")
    capability = models.TextField(blank=True, default="")
    #: claimed, done or failed.
    state = models.TextField()
    result = models.TextField(blank=True, default="")
    at = models.FloatField()
    done_at = models.FloatField(null=True, blank=True, default=None)

    class Meta:
        db_table = "capability_uses"
        constraints = [models.UniqueConstraint(fields=["org_id", "grant_ref", "call_key"],
                                               name="capability_uses_once")]
        indexes = [models.Index(fields=["org_id", "grant", "at"], name="capability_uses_day")]
