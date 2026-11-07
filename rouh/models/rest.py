"""Everything else Rouh keeps: background workers, feedback, Google, Apple
Contacts, public pages, Ask AI threads and the settings each person has chosen.

Each block names the module that owns it; the history of every table is in
that module's own docstring. Organisation and person are text columns, as they
were, and every store queries them scoped (`AGENTS.md`, "Whose data is it").
"""
from __future__ import annotations

from django.db import models
from django.db.models import Q

# `rouh/gene_therapy.py` imports nothing of Django's, so this cannot go round in a
# circle: it owns the words its columns may hold (see the feedback block).
from rouh.gene_therapy import (FEEDBACK, FEEDBACK_STATUSES, REQUEST, REQUEST_KINDS,
                           REQUEST_STATUSES)

# --- background workers (`rouh/crew.py`) -----------------------------------


class Crewmate(models.Model):
    """One background worker: Claude Code in a tmux window of its own.

    The times are ISO strings, as the crew has always written them.
    """

    id = models.TextField(primary_key=True)
    title = models.TextField()
    task = models.TextField()
    mode = models.TextField()
    status = models.TextField(db_index=False)
    session = models.TextField()
    window_name = models.TextField()
    workdir = models.TextField()
    repo = models.TextField(null=True, blank=True)
    branch = models.TextField(null=True, blank=True)
    is_worktree = models.BooleanField(default=False)
    window_id = models.TextField(null=True, blank=True)
    pane_id = models.TextField(null=True, blank=True)
    created_at = models.TextField()
    updated_at = models.TextField()
    started_at = models.TextField(null=True, blank=True)
    finished_at = models.TextField(null=True, blank=True)
    exit_code = models.IntegerField(null=True, blank=True)
    last_event = models.TextField(null=True, blank=True)
    archived = models.BooleanField(default=False)
    #: JSON: whatever else the crew keeps about a job.
    meta = models.TextField(default="{}")

    class Meta:
        db_table = "crewmates"
        indexes = [models.Index(fields=["status"], name="crewmates_by_status")]


#: What became of a note a job queued for the person: still waiting to be
#: sent, sent, or not wanted (`rouh/outbox.py`).
WORKER_NOTE_STATUSES = ("pending", "sent", "dismissed")


class WorkerNote(models.Model):
    """A note a background job asked Rouh to email the person, and what became of it.

    There is no recipient column, and that is the point of the table: where a
    note goes is not the job's to say. Rouh works out the person's own address
    at the moment it sends (`outbox.recipient`). A note belongs to the job that
    queued it, the way a row of the run register does.
    """

    id = models.BigAutoField(primary_key=True)
    job_id = models.TextField()
    created_at = models.FloatField()
    subject = models.TextField()
    body = models.TextField()
    status = models.TextField(default="pending")
    sent_at = models.FloatField(null=True, blank=True)
    #: The id Gmail gave the message, once Rouh has sent it.
    message_id = models.TextField(blank=True, default="")

    class Meta:
        db_table = "worker_outbox"
        indexes = [models.Index(fields=["job_id", "status"], name="worker_outbox_job")]
        constraints = [
            models.CheckConstraint(condition=Q(status__in=WORKER_NOTE_STATUSES),
                                   name="worker_outbox_status_known"),
        ]


class JobRequest(models.Model):
    """What a background job asked Rouh's gateway for that did not simply run, and what became of
    it (`rouh/job_gateway.py`): a call that needs the owner's yes (`kind` "tool"), or something it
    had no tool for, asked with request_from_rouh (`kind` "need"). One row per ask, so the gaps that
    keep coming back can be counted by `gap`.

    `outcome` is "asking", "tool" (an existing tool does it), "owner" (one decision for the owner),
    "cannot", "pending", "rule" (a standing rule of the owner's covered it), "word" (the owner's
    own words for this job covered it, `rouh/his_word.py`), "yes", "no",
    "answered" (the owner's own words to a question), "failed" or "error". `approval_id` is the heartbeat approval it waits on, shared by every job that asked
    the same. `cost_usd` is what the model Rouh asked cost, and None when none was asked.
    """

    id = models.BigAutoField(primary_key=True)
    user_id = models.TextField()
    org_id = models.TextField()
    job_id = models.TextField()
    job_title = models.TextField(blank=True, default="")
    #: "owner", "contact" or "process" (`rouh/job_policy.py`).
    scope = models.TextField()
    kind = models.TextField()
    tool = models.TextField(blank=True, default="")
    need = models.TextField(blank=True, default="")
    why = models.TextField(blank=True, default="")
    meanwhile = models.TextField(blank=True, default="")
    #: A short key for the gap, the same for the same thing asked again by any job.
    gap = models.TextField(blank=True, default="")
    outcome = models.TextField(default="asking")
    #: What the job was told.
    answer = models.TextField(blank=True, default="")
    approval_id = models.BigIntegerField(null=True, blank=True)
    model = models.TextField(blank=True, default="")
    cost_usd = models.FloatField(null=True, blank=True)
    #: For a call that ran on the owner's word (`outcome` "word", `rouh/his_word.py`): the words
    #: of theirs that covered it, the judge's one-line reason, and how to undo it where there is a
    #: way. For a call the judge did not find covered, its reason is kept here too.
    words = models.TextField(blank=True, default="", db_default="")
    judged = models.TextField(blank=True, default="", db_default="")
    undo = models.TextField(blank=True, default="", db_default="")
    created_at = models.FloatField()
    settled_at = models.FloatField(null=True, blank=True)

    class Meta:
        db_table = "job_requests"
        indexes = [models.Index(fields=["org_id", "user_id", "-created_at"], name="job_requests_whose"),
                   models.Index(fields=["job_id"], name="job_requests_job"),
                   models.Index(fields=["approval_id"], name="job_requests_approval")]


class RunWords(models.Model):
    """The owner's own words behind one run, exactly as they said them (`rouh/his_word.py`).

    Petar, 2 November 2026: "I want ot undrstand what caused it and to change so tomorrow I don't
    get a decision but whatever the new thing gets done". A run started from a turn of the owner's
    own (typed, spoken or from their own Telegram), or from a scheduled item's stored words, keeps
    them here; so does each thing they say to it later through one_say or reply_to_task, and a run
    a job starts gets its starter's words, marked as carried (`from_run`). What a job's call is
    judged against before it would be queued for the owner's yes (`his_word.judge`). Never words
    from an email, a page, a file or a tool's result: only what a turn the person started heard.
    """

    id = models.BigAutoField(primary_key=True)
    user_id = models.TextField()
    org_id = models.TextField()
    run_id = models.TextField()
    #: "started" (what started it), "said" (said to it later) or "scheduled" (stored with a
    #: scheduled item that started it).
    how = models.TextField(default="started")
    words = models.TextField()
    #: The run these words were first said to, when they were carried on to this one.
    from_run = models.TextField(blank=True, default="")
    at = models.FloatField()

    class Meta:
        db_table = "run_words"
        indexes = [models.Index(fields=["run_id", "at"], name="run_words_run")]


class CrewEvent(models.Model):
    """What became of a job: it stopped, it wants a person, it ended."""

    seq = models.BigAutoField(primary_key=True)
    crew_id = models.TextField()
    kind = models.TextField()
    at = models.TextField()
    status = models.TextField(null=True, blank=True)
    payload = models.TextField(default="{}")

    class Meta:
        db_table = "crew_events"
        indexes = [models.Index(fields=["crew_id", "seq"], name="crew_events_by_crew")]


class CrewTreeEvent(models.Model):
    """Every telemetry hook, raw, exactly as Claude Code sent it.

    The work tree is derived from this on every read. ``at`` is unix seconds
    as a float, because tool calls last milliseconds.
    """

    seq = models.BigAutoField(primary_key=True)
    crew_id = models.TextField()
    kind = models.TextField()
    at = models.FloatField()
    payload = models.TextField(default="{}")

    class Meta:
        db_table = "crew_tree_events"
        indexes = [models.Index(fields=["at"], name="crew_tree_events_by_time")]


# --- feedback and feature requests (`rouh/gene_therapy.py`) ---------------------

# The words each column may hold are `rouh/gene_therapy.py`'s, and are taken from
# there (at the top of this file) so the CHECK constraints below and the store's
# own checks are one list.
FILE_OWNERS: tuple[str, ...] = (FEEDBACK, REQUEST)


class Feedback(models.Model):
    """What somebody said about Rouh, in their own words."""

    id = models.TextField(primary_key=True)
    org_id = models.TextField()
    user_id = models.TextField()
    author = models.TextField(blank=True, default="")
    body = models.TextField(blank=True, default="")
    #: Where they were when they said it.
    page = models.TextField(blank=True, default="")
    status = models.TextField(default="new")
    created_at = models.FloatField()
    updated_at = models.FloatField(null=True, blank=True)

    class Meta:
        db_table = "feedback"
        indexes = [models.Index(fields=["org_id", "-created_at"], name="feedback_org")]
        constraints = [
            models.CheckConstraint(condition=Q(status__in=FEEDBACK_STATUSES),
                                   name="feedback_status_known"),
        ]


class FeatureRequest(models.Model):
    """What is going to be done about some feedback, and the run doing it."""

    id = models.TextField(primary_key=True)
    org_id = models.TextField()
    user_id = models.TextField()
    author = models.TextField(blank=True, default="")
    from_feedback = models.TextField(blank=True, default="")
    kind = models.TextField(default="feature")
    title = models.TextField()
    #: How the solution should work: the field the run is briefed from.
    body = models.TextField(blank=True, default="")
    status = models.TextField(default="proposed")
    run_id = models.TextField(blank=True, default="")
    run_started_at = models.FloatField(null=True, blank=True)
    #: Whether a machine wrote this rather than a person.
    automatic = models.BooleanField(default=False)
    run_note = models.TextField(blank=True, default="")
    run_tries = models.IntegerField(default=0)
    created_at = models.FloatField()
    updated_at = models.FloatField(null=True, blank=True)

    class Meta:
        db_table = "feature_request"
        indexes = [
            models.Index(fields=["org_id", "-created_at"], name="request_org"),
            models.Index(fields=["from_feedback"], name="request_source"),
        ]
        constraints = [
            models.CheckConstraint(condition=Q(kind__in=REQUEST_KINDS),
                                   name="request_kind_known"),
            models.CheckConstraint(condition=Q(status__in=REQUEST_STATUSES),
                                   name="request_status_known"),
        ]


class FeedbackBoard(models.Model):
    """One organisation's own settings for its board. No row is the defaults."""

    org_id = models.TextField(primary_key=True)
    #: Whether a feature request written out of a feedback is given a run by
    #: itself (`rouh/triage.py`). Converting goes on either way.
    autobuild = models.BooleanField(default=True)
    #: Who moved it last, and when, so a board that has stopped building says
    #: who stopped it.
    changed_by = models.TextField(blank=True, default="")
    changed_at = models.FloatField(null=True, blank=True)

    class Meta:
        db_table = "feedback_board"


class ModelDefaults(models.Model):
    """One organisation's models (`rouh/modeldefaults.py`): whether each box of the
    Models page is on Auto, its own manual set, and what it locked.

    No row, or an empty field, is the standard's, so a new organisation answers
    the way the standard says until somebody changes something on the Models page.
    """

    org_id = models.TextField(primary_key=True)
    #: Auto for the three tiers, and for every use, each on its own. On: that box follows
    #: the Rouh model service on rouh.land. While either is on, the day's anonymous counts
    #: are sent and double calls run. Petar, the evening of 18 October 2026: "Auto is a
    #: toggle. Sync is a one time button press." One `auto` for the page until 0186.
    auto_tiers = models.BooleanField(default=True)
    auto_uses = models.BooleanField(default=True)
    #: The manual set, `{"tiers": {...}, "uses": {...}}`: a tier's two models and its
    #: main one, and a use's choice (a tier, "off" or a model's id), kept while Auto is
    #: on and used for what is locked; empty until it is first written.
    manual = models.JSONField(blank=True, default=dict)
    #: The tiers and uses, by id, that Auto, Sync, Reset and a new standard leave alone.
    locked = models.JSONField(blank=True, default=list)
    #: What the last Sync or Reset replaced, `{"tiers": {...}, "uses": {...}}`, for its
    #: Undo; emptied by the next change.
    undo = models.JSONField(blank=True, default=dict)
    #: The mode, Best, Balanced or Saver (Petar, 23 October 2026), or "" for the service's
    #: default, Balanced. The manual set may also hold `bar`, the router's bar set by hand.
    mode = models.TextField(blank=True, default="")
    #: Petar, 24 October 2026: "a plain toggle 'Share anonymous totals with rouh.land'", apart
    #: from Auto, which it was part of until then (0213 carries each row's Auto over).
    share_totals = models.BooleanField(default=True)
    #: The blind comparisons, a second opt-in apart from the totals, off until somebody turns
    #: it on: it sends the person's own request to a second provider (`rouh/modelvotes.py`).
    compare = models.BooleanField(default=False)
    #: At most this many comparisons a person a day.
    compare_per_day = models.IntegerField(default=1)
    #: Who changed them last, and when.
    changed_by = models.TextField(blank=True, default="")
    changed_at = models.FloatField(null=True, blank=True)

    class Meta:
        db_table = "model_defaults"


class ModelProviderKey(models.Model):
    """An organisation's own key for a model provider, typed into Anatomy, Behaviour, Models
    (`rouh/providerkeys.py`): Google's Gemini API key or xAI's. Sealed with this instance's
    key (`rouh/encryption.py`) and never given back: the page is told only its last four."""

    pk = models.CompositePrimaryKey("org_id", "provider")
    org_id = models.TextField()
    provider = models.TextField()
    key_sealed = models.TextField()
    last4 = models.TextField(blank=True, default="")
    saved_by = models.TextField(blank=True, default="")
    saved_at = models.FloatField(default=0)

    class Meta:
        db_table = "model_provider_key"


class ModelVote(models.Model):
    """One blind comparison's vote (`rouh/modelvotes.py`): the use, the two models, which
    side each was on, and the vote. Never the request or either answer, and nothing that
    says whose: `org_id` is only which organisation's daily totals it goes into, as every
    row here is keyed (AGENTS.md, "Whose data is it")."""

    id = models.BigAutoField(primary_key=True)
    org_id = models.TextField()
    use = models.TextField()
    #: The models on the left (A) and on the right (B), and which of them was the answer
    #: the person was given first: "a" or "b".
    model_a = models.TextField()
    model_b = models.TextField()
    first = models.TextField()
    #: a, b, tie or neither; "" while it waits, and skip once it was put away or ignored.
    vote = models.TextField(blank=True, default="")
    #: The day (UTC, YYYY-MM-DD) it was asked on, and whose daily totals it went into.
    day = models.TextField()
    counted_on = models.TextField(blank=True, default="")
    #: The one-time word the page votes with: it says nothing and is emptied once used.
    token = models.TextField(blank=True, default="")

    class Meta:
        db_table = "model_vote"
        indexes = [models.Index(fields=["org_id", "day"], name="model_vote_org_day")]


class ModelDouble(models.Model):
    """One double call's conclusion (`rouh/llm.py`): the same read-only request answered
    by two models and judged on the Cheaper tier. Never the request or the answers."""

    id = models.BigAutoField(primary_key=True)
    org_id = models.TextField()
    use = models.TextField()
    first_model = models.TextField()
    first_effort = models.TextField(blank=True, default="")
    second_model = models.TextField()
    second_effort = models.TextField(blank=True, default="")
    #: first, second or same.
    winner = models.TextField()
    #: What each answer cost, and the judge: the second answer and the judge are what
    #: double calls add.
    first_cost_usd = models.FloatField(null=True, blank=True)
    second_cost_usd = models.FloatField(null=True, blank=True)
    judge_cost_usd = models.FloatField(null=True, blank=True)
    first_ms = models.IntegerField(null=True, blank=True)
    second_ms = models.IntegerField(null=True, blank=True)
    at = models.FloatField()
    #: The day whose counts it went into, once sent.
    counted_on = models.TextField(blank=True, default="")

    class Meta:
        db_table = "model_double"
        indexes = [models.Index(fields=["org_id", "at"], name="model_double_org_at")]


class ModelOutcome(models.Model):
    """How one call to a model turned out, and never what was asked or answered
    (`rouh/modeloutcomes.py`).

    A call is what a person sees as one: a turn, with every request it made, a run
    of the one program, or one request of anything else. Its outcome is read from
    what the person did next - asked again, pressed Redo or Stop, corrected it,
    rejected it with a reason - or from a run's own end, and is only quiet, never a
    success, once nothing of the kind came within the window (24 October 2026). `call` and `session_id` are what
    the signals find it by, here only: what leaves is counts (`modeloutcomes.payload`).
    """

    id = models.BigAutoField(primary_key=True)
    org_id = models.TextField()
    user_id = models.TextField(blank=True, default="")
    call = models.TextField(unique=True)
    session_id = models.TextField(blank=True, default="")
    use = models.TextField()
    tier = models.TextField(blank=True, default="")
    model = models.TextField()
    effort = models.TextField(blank=True, default="")
    #: pending, failure, or quiet once the window passed with nothing said against it;
    #: "success" is what quiet was called until 24 October 2026, and is not one any more.
    outcome = models.TextField(default="pending")
    #: What made it a failure: repeated, redo, stopped, corrected, rejected, run_failed;
    #: "" for a quiet call (one_shot until 24 October 2026).
    signal = models.TextField(blank=True, default="")
    requests = models.IntegerField(default=0)
    cost_usd = models.FloatField(null=True, blank=True)
    latency_ms = models.IntegerField(null=True, blank=True)
    started_at = models.FloatField()
    ended_at = models.FloatField(null=True, blank=True)
    settled_at = models.FloatField(null=True, blank=True)
    #: The day (UTC, YYYY-MM-DD) whose counts it went into, once they were made.
    counted_on = models.TextField(blank=True, default="")
    #: The exchange of the conversation it answered, so the answer's (i) can be read back.
    root = models.BigIntegerField(null=True, blank=True)
    #: On Auto (`rouh/modelrouter.py`): the tier was the router's pick, or its fallback
    #: (`router_ok` false), with its one-line reason, how long it took and what it cost.
    auto = models.BooleanField(default=False)
    router_ok = models.BooleanField(default=False)
    route_reason = models.TextField(blank=True, default="")
    router_ms = models.IntegerField(null=True, blank=True)
    router_cost_usd = models.FloatField(null=True, blank=True)
    #: Requests of the call that failed (an error from the provider), counted for
    #: troubleshooting: since 24 October 2026 none of these numbers ranks a model.
    errors = models.IntegerField(default=0)

    class Meta:
        db_table = "model_outcome"
        indexes = [
            models.Index(fields=["org_id", "outcome"], name="model_outcome_open"),
            models.Index(fields=["session_id", "-started_at"], name="model_outcome_chat"),
        ]


class FeedbackFile(models.Model):
    """A file attached to a piece of feedback or to a feature request."""

    pk = models.CompositePrimaryKey("owner_kind", "owner_id", "att_id")
    att_id = models.TextField()
    session = models.TextField()
    owner_kind = models.TextField()
    owner_id = models.TextField()
    name = models.TextField(blank=True, default="")
    media_type = models.TextField(blank=True, default="")
    kind = models.TextField(default="file")
    size = models.BigIntegerField(default=0)
    path = models.TextField(blank=True, default="")
    created_at = models.FloatField()

    class Meta:
        db_table = "feedback_file"
        indexes = [models.Index(fields=["owner_kind", "owner_id"], name="feedback_file_owner")]
        constraints = [
            models.CheckConstraint(condition=Q(owner_kind__in=FILE_OWNERS),
                                   name="feedback_file_owner_known"),
        ]


# --- Google (`rouh/google_store.py`) ----------------------------------------


class GoogleClient(models.Model):
    """One organisation's Google Cloud OAuth client. The secret is sealed."""

    org_id = models.TextField(primary_key=True)
    client_id = models.TextField()
    secret_sealed = models.TextField()
    updated_at = models.FloatField()
    updated_by = models.TextField(blank=True, default="")

    class Meta:
        db_table = "google_clients"


class GoogleConnection(models.Model):
    """One person's Google account, and their tokens, sealed."""

    user_id = models.TextField(primary_key=True)
    org_id = models.TextField()
    google_email = models.TextField(blank=True, default="")
    google_account = models.TextField(blank=True, default="")
    access_sealed = models.TextField(blank=True, default="")
    refresh_sealed = models.TextField(blank=True, default="")
    expires_at = models.FloatField(default=0)
    scopes = models.TextField(blank=True, default="")
    connected_at = models.FloatField(default=0)
    needs_reconnect = models.BooleanField(default=False)
    trouble = models.TextField(blank=True, default="")
    #: JSON: the ghost list's last look at this mailbox's sent mail (`ghosts.py`),
    #: as `ReadMailbox.scan` is for a read-only one, and when it was made.
    ghost_scan = models.TextField(blank=True, default="")
    ghost_scanned_at = models.FloatField(default=0)

    class Meta:
        db_table = "google_connections"
        indexes = [models.Index(fields=["org_id"], name="google_connections_org")]


class GoogleOAuthState(models.Model):
    """A consent round trip in flight. Deleted as it is read, so it works once.

    ``purpose`` says which round trip it is: connecting a signed-in person's
    Google account, or signing somebody in with Google (`rouh/web/sso.py`).
    A sign-in has nobody to name yet, so its ``user_id`` is empty.
    """

    nonce = models.TextField(primary_key=True)
    user_id = models.TextField()
    org_id = models.TextField()
    session = models.TextField(blank=True, default="")
    purpose = models.TextField(default="connect")
    next_path = models.TextField(blank=True, default="")
    created_at = models.FloatField()

    class Meta:
        db_table = "google_oauth_states"


# --- Apple Contacts (`rouh/apple_contacts.py`) ------------------------------


class TelegramAccount(models.Model):
    """One person's own Telegram account, connected to Rouh (`rouh/telegram_account.py`).

    Not the bot: the person. It is what a bot cannot be - somebody who can
    make a group - and it is used for that and nothing else: a group for each
    fork made on Telegram, with Rouh's bot in it and made its admin, and the
    fork's first message posted there as his. `api_id` and the sealed
    `api_hash` are the app he registered at my.telegram.org; `session_sealed`
    is the signed-in session, sealed like a Google refresh token
    (`encryption.SecretBox`), and empty until the login is finished.

    A login is two or three steps apart - the phone number, the code Telegram
    sends him, and his password when he has two-step verification - so what
    the next step needs is kept, sealed, in `pending_sealed` while `state`
    says which step it is waiting for. The code and the password are never
    kept anywhere.
    """

    user_id = models.TextField(primary_key=True)
    org_id = models.TextField()
    api_id = models.BigIntegerField(default=0)
    api_hash_sealed = models.TextField(blank=True, default="")
    #: "code" or "password" while a login waits for that; "connected"; or "".
    state = models.TextField(blank=True, default="")
    pending_sealed = models.TextField(blank=True, default="")
    session_sealed = models.TextField(blank=True, default="")
    #: Who it is signed in as, for Settings to say: a name and the last digits
    #: of the phone number, never the whole number.
    name = models.TextField(blank=True, default="")
    phone_hint = models.TextField(blank=True, default="")
    connected_at = models.FloatField(default=0)
    updated_at = models.FloatField(default=0)
    last_error = models.TextField(blank=True, default="")

    class Meta:
        db_table = "telegram_accounts"
        indexes = [models.Index(fields=["org_id"], name="telegram_accounts_org")]


class AppleConnection(models.Model):
    """One person's iCloud contacts: their Apple ID and app-specific password.

    The password is sealed (`encryption.SecretBox`), the way a Google refresh
    token is. The addresses are where CardDAV discovery found the person's
    address book, and the sync token is what iCloud said last time, so the
    next sync asks only for what changed since.
    """

    user_id = models.TextField(primary_key=True)
    org_id = models.TextField()
    apple_id = models.TextField()
    password_sealed = models.TextField()
    connected_at = models.FloatField(default=0)
    principal_url = models.TextField(blank=True, default="")
    home_url = models.TextField(blank=True, default="")
    book_url = models.TextField(blank=True, default="")
    sync_token = models.TextField(blank=True, default="")
    #: The last sync that finished, and how many cards it changed.
    last_sync_at = models.FloatField(default=0)
    last_sync_changed = models.IntegerField(default=0)
    #: The last time a sync was tried at all, and why it failed if it did.
    last_attempt_at = models.FloatField(default=0)
    last_error = models.TextField(blank=True, default="")
    #: iCloud stopped accepting the password: revoked, or the Apple ID's own
    #: password was changed, which revokes every app-specific one.
    needs_new_password = models.BooleanField(default=False)

    class Meta:
        db_table = "apple_connections"
        indexes = [models.Index(fields=["org_id"], name="apple_connections_org")]


# The cards themselves and Rouh's notes on people (`apple_contacts`, `contact_profiles`) are gone since
# 4 October 2026: they are Synapse Master's people (`rouh/synapse/contacts.py`, migration 0080).


# --- mail alerts on Telegram (`rouh/mail_alerts.py`) --------------------------


class GmailPush(models.Model):
    """One organisation's Gmail push: its Pub/Sub topic and the address Google posts to.

    The topic is in the organisation's own Google Cloud project, the one its
    OAuth client is in. The push address carries a random token, which is the
    only thing that lets a caller from outside reach it: kept sealed for showing
    to an administrator again, and as a hash for finding the organisation a
    notification belongs to without opening every row.
    """

    org_id = models.TextField(primary_key=True)
    topic = models.TextField(blank=True, default="")
    token_hash = models.TextField(unique=True)
    token_sealed = models.TextField()
    updated_at = models.FloatField(default=0)
    updated_by = models.TextField(blank=True, default="")
    #: When Google last posted a notification here, for anybody in it.
    last_push_at = models.FloatField(default=0)

    class Meta:
        db_table = "gmail_push"


class MailAlert(models.Model):
    """One person's mail alerts: on or off, the Gmail watch, and where reading got to."""

    user_id = models.TextField(primary_key=True)
    org_id = models.TextField()
    enabled = models.BooleanField(default=False)
    #: The mailbox the watch is on, as Gmail named it when it was made.
    mailbox = models.TextField(blank=True, default="")
    #: Gmail's history id Rouh has read up to. Everything after it is new.
    history_id = models.TextField(blank=True, default="")
    watch_topic = models.TextField(blank=True, default="")
    watch_expires_at = models.FloatField(default=0)
    watch_renewed_at = models.FloatField(default=0)
    #: Why the last watch or the last look at the mailbox failed, in words.
    trouble = models.TextField(blank=True, default="")
    last_push_at = models.FloatField(default=0)
    last_checked_at = models.FloatField(default=0)
    # `guidance`, what the person said was worth a note to the small model
    # that judged each message, went with that model on 25 September 2026
    # (0025). The column is left in the database, with a default, so a Rouh
    # rolled back past it can still read and write a row.
    updated_at = models.FloatField(default=0)

    class Meta:
        db_table = "mail_alerts"
        indexes = [models.Index(fields=["org_id", "enabled"], name="mail_alerts_org")]


class MailAlertSeen(models.Model):
    """One new message Rouh read for a person, and what Rouh did about it.

    Until 25 September 2026 a small model judged each message and this row
    said whether it was worth a note. Since then Rouh itself handles every
    message in a conversation of its own (`rouh/mail_alerts.py`), and the row
    is the record of that: where it got to, what was done, and the note that
    went to the phone. The columns kept their names, so rows from before read
    as what they were.
    """

    id = models.BigAutoField(primary_key=True)
    user_id = models.TextField()
    org_id = models.TextField()
    message_id = models.TextField()
    at = models.FloatField()
    sender = models.TextField(blank=True, default="")
    subject = models.TextField(blank=True, default="")
    #: Handed to Rouh, rather than passed over (Spam, the Bin, a draft).
    #: Before 25 September 2026: judged worth a note.
    worth = models.BooleanField(default=False)
    #: What Rouh did about it, in one or two sentences; why it was passed over.
    why = models.TextField(blank=True, default="")
    #: A note about it went to the phone on Telegram.
    sent = models.BooleanField(default=False)
    #: What went wrong, when something did.
    error = models.TextField(blank=True, default="")
    # What the log shows (`MailAlerts.decisions`, 0015). Each with a default in
    # the database as well, so a Rouh rolled back past 0015 can still write a
    # row.
    #: Where it got to: "waiting" for Rouh, "handling", "handled",
    #: "unhandled" (Rouh could not finish, and the plain note went instead),
    #: "gone", "passed". Before 25 September 2026: "judged" or "unjudged".
    stage = models.TextField(blank=True, default="", db_default="")
    #: The sender's address, which `sender` (the name) leaves out.
    address = models.TextField(blank=True, default="", db_default="")
    #: Gmail's labels on it, as Gmail names them.
    labels = models.TextField(blank=True, default="", db_default="")
    #: The start of the message.
    snippet = models.TextField(blank=True, default="", db_default="")
    # `own`, the person's own address as the small model was told it, went
    # with that model (0025). The column stays, with its default.
    #: Which model handled it, and Rouh's own last words about it.
    model = models.TextField(blank=True, default="", db_default="")
    answer = models.TextField(blank=True, default="", db_default="")
    #: The Telegram note, word for word, every one that went about it.
    note = models.TextField(blank=True, default="", db_default="")
    #: Gmail's thread, and the conversation in Rouh it was handled in: the
    #: next message in the same thread is handled in the same conversation.
    thread_id = models.TextField(blank=True, default="", db_default="")
    chat_id = models.TextField(blank=True, default="", db_default="")
    #: It was the person's own mail, from one of their addresses, and Gmail
    #: confirmed it came from there: their instruction, carried out.
    from_petar = models.BooleanField(default=False, db_default=False)
    #: Rouh answered it by email.
    replied = models.BooleanField(default=False, db_default=False)
    # Its stages, written for everybody's mail for a few hours on 30 September
    # 2026 (`rouh/mail_flow.py`) and kept for those rows. Since that evening
    # somebody else's email is a case (`rouh/mail_cases.py`), which keeps its
    # own stages, and this row is its arrival log: seen, the conversation,
    # junk and why (stage "junk": skipped on arrival, or read as junk and moved
    # to Gmail's Spam, never deleted), and where the case got to. Only
    # Petar's own mail still writes `work` here.
    #: The sender is somebody Petar trusts, and how that was checked, in words.
    trusted = models.BooleanField(default=False, db_default=False)
    trust = models.TextField(blank=True, default="", db_default="")
    #: Petar had said who the sender is to him, so an answer may be sent.
    known = models.BooleanField(default=False, db_default=False)
    #: "rouh" (Rouh may see it through) or "petar" (the owner is needed), what
    #: they want or the owner's question, and when it was decided.
    triage = models.TextField(blank=True, default="", db_default="")
    triage_note = models.TextField(blank=True, default="", db_default="")
    triaged_at = models.FloatField(default=0, db_default=0)
    help_needed = models.BooleanField(default=False, db_default=False)
    reply_owed = models.BooleanField(default=False, db_default=False)
    #: The background jobs started for it: {"run", "title", "state", "at",
    #: and once it has finished "said", "ended", "seen"}.
    work = models.JSONField(default=list, db_default=[])
    #: "verified" or "blocked", in words, and when.
    outcome = models.TextField(blank=True, default="", db_default="")
    outcome_note = models.TextField(blank=True, default="", db_default="")
    outcome_at = models.FloatField(default=0, db_default=0)
    #: The answer's Gmail id, once it went, the moment one was claimed, and
    #: when it went: a message was answered once. Not written since every
    #: email became a case; a row carrying them is never answered again.
    reply_id = models.TextField(blank=True, default="", db_default="")
    reply_claimed_at = models.FloatField(default=0, db_default=0)
    replied_at = models.FloatField(default=0, db_default=0)
    drafted = models.BooleanField(default=False, db_default=False)
    #: When the last note about it reached the phone.
    told_at = models.FloatField(default=0, db_default=0)
    #: How many times Petar asked for it to be handled again.
    replays = models.IntegerField(default=0, db_default=0)

    class Meta:
        db_table = "mail_alert_seen"
        indexes = [models.Index(fields=["user_id", "org_id", "at"], name="mail_alert_seen_mine")]
        constraints = [
            models.UniqueConstraint(fields=["user_id", "message_id"],
                                    name="mail_alert_seen_once"),
        ]


# --- public pages (`rouh/sharing.py`) ----------------------------------------


class PublicPage(models.Model):
    """A workspace page's one link, `/p/<token>`. The token is the key.

    ``public`` is whether anybody with the link can read it. When it is not,
    the row and its token are kept, so the link stays the same and lets in
    only the owner and the people the page is shared with (`PageGuest`).
    ``role`` is what a visitor may do with it: ``view`` reads it and nothing
    more, ``edit`` gets Ask AI on it, which answers and changes the page.
    """

    token = models.TextField(primary_key=True)
    user_id = models.TextField()
    org_id = models.TextField()
    rel = models.TextField()
    title = models.TextField(blank=True, default="")
    created_at = models.FloatField()
    role = models.TextField(default="view", db_default="view")
    public = models.BooleanField(default=True, db_default=True)

    class Meta:
        db_table = "public_pages"
        indexes = [models.Index(fields=["user_id", "-created_at"], name="public_pages_mine")]
        constraints = [
            models.UniqueConstraint(fields=["user_id", "rel"], name="public_pages_one"),
        ]


class PageGuest(models.Model):
    """One permission: one person's level on one thing of the owner's, by their email address.

    The one record every check reads (`rouh/task_access.py`), since 21 October 2026: a page
    shared with them, or a quest, a goal, a task or a step (``rel`` "_task/<folder>"), at a
    level ``role`` - read ("view") < edit < decide, each including the ones before it. A
    record on a quest reaches its goals, a goal or a task its steps and pages; the most
    specific record wins, so one lower down may narrow what it inherits. Decide is only ever a
    trusted contact's, and money, deleting, publishing, sending, signing or committing the
    owner, and changes to Rouh itself are never part of any level (DELEGATION.md). Until then a
    trusted contact's authority to decide was a table of its own (`delegations`), which
    migration 0197 moved here.

    ``user_id`` and ``org_id`` are the owner's, and every query the owner makes
    names both. ``guest_id`` is the account the address belongs to, once there
    is one: blank until the person registers from the invitation, or filled in
    at once when an account with that address already exists.

    ``token`` is the page's address for that one person (``/shared/<token>``)
    and the invitation's (``/join/<token>``). It is a secret like a public
    page's, and it is not enough on its own: the page answers only somebody
    signed in with that address.
    """

    token = models.TextField(primary_key=True)
    user_id = models.TextField()
    org_id = models.TextField()
    rel = models.TextField()
    title = models.TextField(blank=True, default="")
    email = models.TextField()
    #: ``view`` or ``edit``, as on a public page.
    role = models.TextField(default="edit")
    guest_id = models.TextField(blank=True, default="")
    created_at = models.FloatField()
    #: When the invitation or the note went out, and what the mail service
    #: said when it did not.
    mailed_at = models.FloatField(null=True, blank=True)
    mail_error = models.TextField(blank=True, default="")
    #: Who keeps it: "" when a person chose it - the owner on the Share panel or on a trusted
    #: contact's page, or Rouh for whoever asked for the task (`rouh/requester_share.py`) -
    #: and "tick" when it is there because a column or a project above the task is ticked on
    #: the contact's page, which keeps it for as long as the tick stays (`rouh/task_access.py`).
    via = models.TextField(blank=True, default="", db_default="")
    #: A promise the owner approved, in words: work not made yet that Rouh may extend this
    #: record's level to once it is (`delegation.extend`), or "".
    pending = models.TextField(blank=True, default="", db_default="")
    #: Who gave it, when it came through May decide for: "owner", or "rouh" keeping a promise;
    #: "" for a share made on the Share panel or by Rouh for whoever asked for the task.
    granted_by = models.TextField(blank=True, default="", db_default="")

    class Meta:
        db_table = "page_guests"
        indexes = [models.Index(fields=["user_id", "org_id", "rel"], name="page_guests_page"),
                   models.Index(fields=["email"], name="page_guests_email")]
        constraints = [
            models.UniqueConstraint(fields=["user_id", "rel", "email"], name="page_guests_one"),
        ]


class RequesterShare(models.Model):
    """A task made for somebody outside, shared with them to edit, once (`rouh/requester_share.py`).

    One row per task per address, written the first time Rouh sees the task and
    shares it with the person who asked for it. It is what makes it once: a share
    Petar later stops, or turns to read, is never made again, and no second
    letter goes. ``task_id`` is the task's row, which keeps it through a move or
    a rename; ``folder`` is only where it was. ``outcome`` is what was done:
    ``shared`` (a new share, and the letter), ``upgraded`` (a share to read
    turned to edit), ``already`` (shared to edit before) or ``covered`` (a step
    of a task already shared with them to edit).
    """

    id = models.BigAutoField(primary_key=True)
    user_id = models.TextField()
    org_id = models.TextField()
    task_id = models.TextField()
    folder = models.TextField(blank=True, default="")
    email = models.TextField()
    outcome = models.TextField()
    #: The `page_guests` row it made or turned, when it did.
    token = models.TextField(blank=True, default="")
    #: Whether the letter went, and why not when it did not.
    mailed = models.BooleanField(default=False)
    mail_error = models.TextField(blank=True, default="")
    at = models.FloatField()

    class Meta:
        db_table = "requester_shares"
        constraints = [
            models.UniqueConstraint(fields=["user_id", "org_id", "task_id", "email"],
                                    name="requester_shares_one"),
        ]


# --- comments pinned to a shared page (`rouh/comments.py`) ------------------


class PageComment(models.Model):
    """One comment thread, pinned to one element of one page.

    ``owner_id`` and ``org_id`` are the page owner's, the same pair a share
    of the page is kept under, and every query names both with ``rel``: the
    people a page is shared with read and write the owner's threads, never a
    set of their own. ``author_*`` is whoever started it.

    ``anchor`` is where on the page it is pinned: the element's place in the
    page, its tag and words, and the point clicked, as a share of the element
    and as a place on the page (for when the element has gone). ``snapshot``
    is the element as it looked when the comment was made, as plain markup
    with its styles written in, so a comment whose element was later removed
    can still show what it was about.
    """

    id = models.BigAutoField(primary_key=True)
    owner_id = models.TextField()
    org_id = models.TextField()
    rel = models.TextField()
    author_id = models.TextField()
    author_name = models.TextField(blank=True, default="")
    author_email = models.TextField(blank=True, default="")
    anchor = models.JSONField(default=dict)
    snapshot = models.TextField(blank=True, default="")
    created_at = models.FloatField()
    resolved_at = models.FloatField(null=True, blank=True)
    resolved_by = models.TextField(blank=True, default="")

    class Meta:
        db_table = "page_comments"
        indexes = [models.Index(fields=["owner_id", "org_id", "rel", "id"],
                                name="page_comments_page")]


class PageCommentMessage(models.Model):
    """One message in a comment thread: the first one, or a reply.

    ``mentions`` is who it tagged, as ``{"key", "name"}``, and for each
    whether the letter went (``mailed``) or why not (``why``).
    """

    id = models.BigAutoField(primary_key=True)
    thread = models.ForeignKey(PageComment, on_delete=models.CASCADE, db_column="thread_id",
                               related_name="messages")
    owner_id = models.TextField()
    org_id = models.TextField()
    author_id = models.TextField()
    author_name = models.TextField(blank=True, default="")
    author_email = models.TextField(blank=True, default="")
    body = models.TextField()
    mentions = models.JSONField(default=list)
    created_at = models.FloatField()
    edited_at = models.FloatField(null=True, blank=True)

    class Meta:
        db_table = "page_comment_messages"
        indexes = [models.Index(fields=["thread", "id"], name="page_comment_msgs_thread"),
                   models.Index(fields=["author_id", "created_at"],
                                name="page_comment_msgs_author")]


# --- passages highlighted on a page (`rouh/highlights.py`) -------------------


class PageHighlight(models.Model):
    """One passage of one page, painted in one colour by one reader.

    ``owner_id``, ``org_id`` and ``rel`` are the page as its owner has it,
    the three a share and a comment are kept under, so a highlight follows the
    page when its folder moves (`pageplaces._repoint`). ``user_id`` is who
    made it: every reader of the page sees it, and only they may change it.

    ``anchor`` is the passage as the page found it: its words, a few words
    either side of them, and where it starts in the page's text, which is
    enough to find it again after the page around it has changed.
    """

    id = models.BigAutoField(primary_key=True)
    owner_id = models.TextField()
    org_id = models.TextField()
    rel = models.TextField()
    user_id = models.TextField()
    colour = models.TextField()
    anchor = models.JSONField(default=dict)
    created_at = models.FloatField()

    class Meta:
        db_table = "page_highlights"
        indexes = [models.Index(fields=["owner_id", "org_id", "rel", "user_id", "id"],
                                name="page_highlights_page")]


# --- passages explained in place on a page (`rouh/definitions.py`) ----------


class PageDefinition(models.Model):
    """One passage of one page, explained in the light of the page around it.

    Kept under the page as its owner has it, as a highlight is (``owner_id``,
    ``org_id``, ``rel``), so it follows the page when its folder moves.
    ``user_id`` is who pressed Define: every reader of the page sees the
    passage underlined and its explanation, and only they may explain it
    again or take it off. ``anchor`` is the passage as the page found it,
    in the same shape as a highlight's. ``text`` is the explanation and
    ``model`` the model that wrote it.
    """

    id = models.BigAutoField(primary_key=True)
    owner_id = models.TextField()
    org_id = models.TextField()
    rel = models.TextField()
    user_id = models.TextField()
    anchor = models.JSONField(default=dict)
    text = models.TextField(default="")
    model = models.TextField(default="")
    created_at = models.FloatField()

    class Meta:
        db_table = "page_definitions"
        indexes = [models.Index(fields=["owner_id", "org_id", "rel", "id"],
                                name="page_definitions_page")]


# --- a page's sources, checked against what it says (`rouh/source_check.py`) --


class PageSourceCheck(models.Model):
    """Every footnoted source of one page, read against what the page says it says.

    One row a page and owner. ``sources`` is the page's sources in footnote
    order, each ``{n, url, title, claims, key, verdict, quote, why, at, model}``;
    ``key`` is the address and the sentences it is cited for, so a source is
    read again only when one of them changes. ``fp`` is all the keys at once,
    and ``state`` is ``asked`` from his press on Check sources until every
    source has a verdict, then ``done``. A ``checking`` row is from before
    17 October 2026, when pages were checked by themselves, and is never
    carried on unless he asks.
    """

    id = models.BigAutoField(primary_key=True)
    user_id = models.TextField()
    org_id = models.TextField()
    rel = models.TextField()
    title = models.TextField(default="")
    fp = models.TextField(default="")
    state = models.TextField(default="checking")
    total = models.IntegerField(default=0)
    sources = models.JSONField(default=list)
    checked_at = models.FloatField()

    class Meta:
        db_table = "page_source_checks"
        constraints = [models.UniqueConstraint(fields=["org_id", "user_id", "rel"],
                                               name="page_source_checks_page")]


class PageRead(models.Model):
    """One visit of the owner to one page of the workspace, with the page's words as they were
    (`rouh/since_read.py`, Since you last read it, version 2).

    A visit is every open of the page closer together than `since_read.VISIT_GAP`: the row is
    made at the first and kept up to date at each open after it, so ``text`` is the page as
    it was the last time they had it in front of them. ``text`` is the page's words, one block a
    line (`since_read.text_of`), and ``fp`` their digest, so a change to the page's look alone
    is not a change. ``told_at`` is when they pressed What changed during this visit.
    """

    id = models.BigAutoField(primary_key=True)
    org_id = models.TextField()
    user_id = models.TextField()
    rel = models.TextField()
    text = models.TextField(default="")
    fp = models.TextField(default="")
    first_at = models.FloatField()
    seen_at = models.FloatField()
    told_at = models.FloatField(null=True, blank=True)

    class Meta:
        db_table = "page_reads"
        indexes = [models.Index(fields=["org_id", "user_id", "rel", "-seen_at"],
                                name="page_reads_whose")]


# --- a page's own settings (`rouh/pagestate.py`) ----------------------------

class PageState(models.Model):
    """What one person chose on one page of the workspace, kept for the page itself.

    A page is sandboxed and can keep nothing of its own, so it hands its settings
    to Rouh's page around it, which saves them here (`rouh/pagestate.py`). One row
    a person a page: ``settings`` is the page's own keys and their values, and
    ``rel`` follows the page when its folder moves (`pageplaces._repoint`).
    """

    id = models.BigAutoField(primary_key=True)
    org_id = models.TextField()
    user_id = models.TextField()
    rel = models.TextField()
    settings = models.JSONField(default=dict)
    updated_at = models.FloatField()

    class Meta:
        db_table = "page_states"
        constraints = [models.UniqueConstraint(fields=["org_id", "user_id", "rel"],
                                               name="page_states_one")]


# --- A share that ends by itself (`rouh/share_ends.py`) ---------------------

class ShareEnd(models.Model):
    """When one share by hand (`PageGuest`, by its ``token``) ends by itself.

    Set in the Share panel, beside the person, by the owner (``org_id``, ``user_id``); at
    ``ends_at`` the share is taken away the way Remove takes it away, and this row with it.
    """

    token = models.TextField(primary_key=True)
    org_id = models.TextField()
    user_id = models.TextField()
    rel = models.TextField()
    email = models.TextField()
    ends_at = models.FloatField()
    set_at = models.FloatField()

    class Meta:
        db_table = "share_ends"
        indexes = [models.Index(fields=["ends_at"], name="share_ends_when")]


# --- Drafts learn your edits (`rouh/draft_edits.py`) -----------------------

class DraftEdit(models.Model):
    """One email Rouh drafted on a card that the person changed before pressing Send.

    ``drafted`` is the draft as Rouh first wrote it and ``sent`` the email as it went, each
    ``{fields: {name: value}, body}``, kept whole; ``changes`` is each place they differ,
    ``{part, was, now}``. Recorded only, for a later analysis of how drafts should be
    written: nothing reads it back into a prompt. ``card`` and ``chat`` say where it was.
    """

    id = models.BigAutoField(primary_key=True)
    user_id = models.TextField()
    org_id = models.TextField()
    at = models.FloatField()
    card = models.TextField(default="")
    chat = models.TextField(default="")
    to = models.TextField(default="")
    subject = models.TextField(default="")
    drafted = models.JSONField(default=dict)
    sent = models.JSONField(default=dict)
    changes = models.JSONField(default=list)

    class Meta:
        db_table = "draft_edits"
        indexes = [models.Index(fields=["org_id", "user_id", "-id"], name="draft_edits_newest")]


# --- Ask AI on a workspace page (`rouh/askai.py`) ---------------------------


class AskThread(models.Model):
    id = models.BigAutoField(primary_key=True)
    user_id = models.TextField()
    org_id = models.TextField()
    doc = models.TextField()
    title = models.TextField(blank=True, default="")
    created_at = models.FloatField()

    class Meta:
        db_table = "askai_threads"
        indexes = [models.Index(fields=["user_id", "doc", "-id"], name="askai_threads_page")]


class AskMessage(models.Model):
    id = models.BigAutoField(primary_key=True)
    thread = models.ForeignKey(AskThread, on_delete=models.CASCADE, db_column="thread_id",
                               related_name="messages")
    user_id = models.TextField()
    role = models.TextField()
    selected_text = models.TextField(blank=True, default="")
    content = models.TextField(blank=True, default="")
    created_at = models.FloatField()

    class Meta:
        db_table = "askai_messages"
        indexes = [models.Index(fields=["thread", "id"], name="askai_messages_thread")]


class AskEdit(models.Model):
    """One change Ask AI made to a page, whole, so it can be put back.

    ``before`` and ``after`` are the page's source either side of it. Undo
    writes ``before`` back only while the page on disk is still ``after``, so
    an undo can never throw away a change somebody made since.
    """

    id = models.BigAutoField(primary_key=True)
    #: Who asked for it: the person, a guest, or ``link:<token>`` for a
    #: visitor to a public page that may be changed.
    user_id = models.TextField()
    org_id = models.TextField()
    doc = models.TextField()
    thread_id = models.BigIntegerField(null=True, blank=True)
    summary = models.TextField(blank=True, default="")
    before = models.TextField()
    after = models.TextField()
    created_at = models.FloatField()
    undone_at = models.FloatField(null=True, blank=True)
    #: The organisation whose page this is, whoever changed it: a guest's own
    #: rows are under `tenancy.GUEST_ORG`, and a page's history is the owner's
    #: to read (`rouh/pagehistory.py`).
    page_org_id = models.TextField(blank=True, default="")
    #: "" for a change Ask AI made; "default" for somebody picking which of a
    #: page's options everybody sees (`pagehistory.choose`).
    kind = models.TextField(blank=True, default="")
    #: Whether the owner kept it as an option: "" not asked yet, "final", or
    #: "option" (`pagehistory.keep`).
    keep = models.TextField(blank=True, default="")
    #: JSON: the elements it changed, whole, before and after
    #: (`pagehistory.parts_of`). Empty for a change too wide to be an option.
    parts = models.TextField(blank=True, default="")
    #: Why the page should be this way, in one sentence, as the model put it
    #: from what the reader asked: shown beside this version when it is kept as
    #: one of several options (fr_662a64715b9f).
    reason = models.TextField(blank=True, default="")

    class Meta:
        db_table = "askai_edits"
        indexes = [models.Index(fields=["user_id", "org_id", "doc", "-id"],
                                name="askai_edits_page"),
                   models.Index(fields=["page_org_id", "doc", "-id"],
                                name="askai_edits_history")]


class PageOption(models.Model):
    """Part of a page that viewers may switch between versions of.

    Petar, 24 September 2026 (fr_b91369ea7ba2): "if I have a red button and
    make a change to make it orange, I decide whether this change should stay
    like this or have an options pop-up so other people can switch between red
    and orange." Kept beside the page rather than written into it: the page on
    disk holds the default and nothing else, and the switch is drawn over it
    (`rouh/static/askai/askai.js`).

    ``parts`` is JSON, one entry per element the change touched, each with the
    element's whole source in every version (``alts``). ``alts`` is JSON too,
    one entry per version: who made it, when, and what it is called.
    ``chosen`` is the version on disk, which is what everybody sees when the
    page opens. Anybody who can read the page may change it; the last one wins.
    """

    id = models.BigAutoField(primary_key=True)
    #: The organisation whose page this is.
    org_id = models.TextField()
    doc = models.TextField()
    #: The change it was kept from.
    edit_id = models.BigIntegerField()
    parts = models.TextField()
    alts = models.TextField()
    chosen = models.IntegerField(default=0)
    chosen_by = models.TextField(blank=True, default="")
    chosen_at = models.FloatField(null=True, blank=True)
    created_by = models.TextField()
    created_at = models.FloatField()
    removed_by = models.TextField(blank=True, default="")
    removed_at = models.FloatField(null=True, blank=True)
    #: Who made the default final, and when: the choice is decided, and the
    #: page says so to everybody who reads it (`pagehistory.decide`). NULL is
    #: still open.
    final_by = models.TextField(blank=True, default="")
    final_at = models.FloatField(null=True, blank=True)

    class Meta:
        db_table = "page_options"
        indexes = [models.Index(fields=["org_id", "doc", "id"], name="page_options_page")]


class PagePlace(models.Model):
    """Which page a path of the workspace is, by the object it sits in (`rouh/pageplaces.py`).

    A share, a person's share, a comment, Ask AI's threads, a page's history
    and its options all name their page by its path. ``object_id`` is the id
    in the ``.object.json`` of the nearest folder above the page, which a move
    carries along, and ``sub`` is where the page is inside that folder, so a
    path whose folder has moved is found again at the object's new place.

    One workspace per install (``config.assistant_repo``), so a path is the
    same page for everybody on it and the row is not anybody's in particular.
    """

    rel = models.TextField(primary_key=True)
    object_id = models.TextField()
    sub = models.TextField()
    seen_at = models.FloatField()
    #: When its owner last opened it on the canvas (`pageplaces.opened`), or
    #: None when nobody has since this was first kept, 1 October 2026.
    opened_at = models.FloatField(null=True, blank=True)

    class Meta:
        db_table = "page_places"
        indexes = [models.Index(fields=["object_id"], name="page_places_object")]


# --- what each person has set for themselves (`rouh/settings.py`) -----------


class UserSetting(models.Model):
    pk = models.CompositePrimaryKey("user_id", "name")
    user_id = models.TextField()
    org_id = models.TextField()
    name = models.TextField()
    #: JSON.
    value = models.TextField()
    updated_at = models.FloatField()

    class Meta:
        db_table = "user_settings"
        indexes = [models.Index(fields=["org_id", "user_id"], name="user_settings_org")]


# --- the Live browser's saved logins (`rouh/browsing.py`) --------------------


class BrowserLogins(models.Model):
    """One person's logins in the browser Rouh drives for them.

    The browser's cookies and local storage (Playwright's storage state),
    sealed with `encryption.SecretBox` like every other credential Rouh holds
    on somebody's behalf. `sites` is how many sites have cookies in it, for
    saying so without opening it.
    """

    id = models.BigAutoField(primary_key=True)
    user_id = models.TextField()
    org_id = models.TextField()
    state_sealed = models.TextField()
    sites = models.IntegerField(default=0)
    saved_at = models.FloatField()

    class Meta:
        db_table = "browser_logins"
        constraints = [models.UniqueConstraint(fields=["org_id", "user_id"],
                                               name="browser_logins_one")]


# --- reminders (`rouh/reminders.py`) ------------------------------------------


class Reminder(models.Model):
    """One thing Rouh does at a time: says it, or does it.

    `kind` is `remind` (say these words to the person) or `do` (do this piece
    of work then, and say what was found; a goal's step Rouh is to do at a
    time is one of these, `timekeeper.schedule_step`), or `server` (one of
    Rouh's own server jobs, named by `job` and started by code, never a chat
    turn: the nightly Synapse run, `rouh/synapse/nightly.py`). `next_at` is the next moment it is due, in seconds since 1970,
    and None once a one-off has been said. The rule it repeats by is the four
    columns after it, read on its person's own clock (`reminders.Rule`, `clock.zone`).
    """

    id = models.BigAutoField(primary_key=True)
    user_id = models.TextField()
    org_id = models.TextField()
    kind = models.TextField(default="remind")
    #: One short line that says on its own what this is about, for the list and
    #: the morning brief (`reminders.title_of`). Empty until it is written: a
    #: row made before 8 October 2026, or without one, is given one by a model
    #: (`rouh/reminder_titles.py`).
    title = models.TextField(blank=True, default="")
    #: Everything else: the detail under the title, which Rouh is handed with
    #: it when it is due. May be empty when the title says it all.
    what = models.TextField()
    #: The conversation it is said in: the one it was asked for in.
    chat_id = models.TextField(blank=True, default="")
    #: "once", "daily", "weekdays", "weekly" or "monthly".
    repeat = models.TextField(default="once")
    #: "HH:MM", on the person's clock, for a rule that repeats.
    at_time = models.TextField(blank=True, default="")
    #: The days of a weekly rule, "mon,thu".
    days = models.TextField(blank=True, default="")
    #: The day of the month of a monthly rule.
    month_day = models.IntegerField(default=0)
    next_at = models.FloatField(null=True, blank=True)
    #: "on", "paused" or "done".
    state = models.TextField(default="on")
    created_at = models.FloatField()
    updated_at = models.FloatField()
    last_at = models.FloatField(null=True, blank=True)
    #: What happened the last time, in a line: what was said, or why not.
    last_said = models.TextField(blank=True, default="")
    fired = models.IntegerField(default=0)
    #: For a row of kind `server`, which of Rouh's own server jobs it starts
    #: (`reminders.SERVER_JOBS`); empty for every other row.
    job = models.TextField(blank=True, default="")
    #: The person's own words that asked for it, as a list of what they said, oldest first:
    #: what they typed on the Clockwork page, or their own messages in the chat a turn of
    #: theirs scheduled it from (`reminders.asked_of`). Never Rouh's words, an email's or a
    #: tool's. A turn it starts with nobody watching may share and give a trusted contact
    #: authority on these words alone (`tools.ToolRegistry._delegate`). Empty for a row
    #: nobody asked for in words: a goal's step, a server job.
    asked = models.JSONField(default=list, blank=True)
    #: The trusted contact it was made for (`TrustedContact.id`), under their Clockwork
    #: grant (Petar, 11 October 2026), or None for Petar's own. An owner other than
    #: Petar is how an item made for somebody else is told apart: no other flag.
    #: Their grant lets Rouh make and change only the items they own (`rouh/grants.py`).
    owner_contact_id = models.BigIntegerField(null=True, blank=True)
    #: Who an item made for a trusted contact goes to (Petar, 12 October 2026: Clockwork is a
    #: time modifier): "owner" ("petar" on older rows), told about what they told the
    #: owner (Clockwork alone); "contact", a message to them; "both". "" for the person's own
    #: items and for "owner".
    goes_to = models.TextField(blank=True, default="")
    #: The contact's other grants its work uses, beyond Clockwork itself ("memory", "use",
    #: "shared_task"): checked against what they hold each time it runs (`clockwork_grants`).
    uses = models.JSONField(default=list, blank=True)
    #: The words the contact gets when it goes to them, in their language.
    message = models.TextField(blank=True, default="")
    #: Where the contact gets it: "email" or "telegram"; "" for the channel of its case.
    channel = models.TextField(blank=True, default="")
    #: The case it was made in (`MailCase.id`): the contact's channels and the outbox's key.
    case_id = models.BigIntegerField(null=True, blank=True)
    #: Why a contact's item stopped when it came due: a grant it needs was taken away, or
    #: they were removed. Cleared when it is resumed.
    stopped_why = models.TextField(blank=True, default="")
    #: The silos it belongs to (`rouh/silos.py`, `Silo.key`): set as it is made from the chat or
    #: task it was made in, changed on its page; empty when nothing says, which is unlabelled.
    silos = models.JSONField(default=list, blank=True, db_default=[])
    #: Whether it is about Rouh itself - its code, its genes, its own upkeep - rather than the
    #: person's life (Petar, 18 October 2026, fr_5db528986cf6). Set as it is made: always for
    #: Rouh's own server jobs, by the model's `schedule` or Luna's reading of typed words for the
    #: rest; changed on Clockwork. One that also repeats is left out of the morning brief.
    about_rouh = models.BooleanField(default=False, db_default=False)

    class Meta:
        db_table = "reminders"
        indexes = [models.Index(fields=["org_id", "user_id"], name="reminders_whose"),
                   models.Index(fields=["state", "next_at"], name="reminders_due")]


# --- the morning brief (`rouh/morning_brief.py`) -----------------------------


class MorningBrief(models.Model):
    """One person's morning brief for one day: what it said, and when it went out.

    One row per person per day, written over when the brief is made again that
    day, so the page always has today's and the days before it stay as they
    were. `data` is the brief as JSON, every section with its items or the
    reason it has none; `sent_at` is when the link went to the phone, which is
    also what stops it going twice.
    """

    id = models.BigAutoField(primary_key=True)
    user_id = models.TextField()
    org_id = models.TextField()
    #: "YYYY-MM-DD", on the person's own clock.
    day = models.TextField()
    made_at = models.FloatField()
    #: JSON.
    data = models.TextField()
    sent_at = models.FloatField(null=True, blank=True)

    class Meta:
        db_table = "morning_briefs"
        constraints = [models.UniqueConstraint(fields=["org_id", "user_id", "day"],
                                               name="morning_briefs_one_a_day")]


class BirthdayLink(models.Model):
    """A birthday on the person's calendar, tied by them to one of their contacts.

    The brief's Birthdays section (`rouh/birthdays.py`) shows a calendar
    birthday with no contact behind it as the event says it ("Sam Bday"), with
    Link contact beside it; what is picked there is kept here, so that event
    reads as the contact's full name and company in every brief after. Keyed by
    the calendar and the event's series, so every year of it is the one link.
    `contact_uid` is the card's own uid in iCloud, which outlives Rouh's copy
    of it being synced again.
    """

    id = models.BigAutoField(primary_key=True)
    user_id = models.TextField()
    org_id = models.TextField()
    calendar_id = models.TextField()
    #: The repeating event's own id, or the event's when it does not repeat.
    event_key = models.TextField()
    contact_uid = models.TextField()
    #: What the event was called when it was linked, to say what was linked.
    title = models.TextField(blank=True, default="")
    linked_at = models.FloatField()

    class Meta:
        db_table = "birthday_links"
        constraints = [models.UniqueConstraint(fields=["org_id", "user_id", "calendar_id",
                                                       "event_key"],
                                               name="birthday_links_one_per_event")]


# --- read-only mailboxes and the ghost list (`rouh/mailboxes.py`, `rouh/ghosts.py`) ---


class ReadMailbox(models.Model):
    """One mailbox a person connected to Rouh to be read and never written to.

    Not the Google connection (`GoogleConnection`), which is Rouh's own mailbox
    with every grant it acts through. This is one of the person's own
    mailboxes, as many as they connect, each granted `gmail.readonly` and
    nothing more, through their organisation's OAuth client. The tokens are
    sealed like every other credential. `scan` is the last look for sent mail
    nobody answered (`ghosts.py`), as JSON, so the brief can draw it at once.
    """

    id = models.BigAutoField(primary_key=True)
    user_id = models.TextField()
    org_id = models.TextField()
    email = models.TextField(blank=True, default="")
    #: Google's own id of the account (`sub`), which stays when an address changes.
    google_account = models.TextField()
    access_sealed = models.TextField(blank=True, default="")
    refresh_sealed = models.TextField(blank=True, default="")
    expires_at = models.FloatField(default=0)
    scopes = models.TextField(blank=True, default="")
    connected_at = models.FloatField(default=0)
    needs_reconnect = models.BooleanField(default=False)
    trouble = models.TextField(blank=True, default="")
    #: JSON: the last look at the sent mail, and when it was made.
    scan = models.TextField(blank=True, default="")
    scanned_at = models.FloatField(default=0)

    class Meta:
        db_table = "read_mailboxes"
        constraints = [models.UniqueConstraint(fields=["org_id", "user_id", "google_account"],
                                               name="read_mailboxes_once_each")]
        indexes = [models.Index(fields=["org_id", "user_id"], name="read_mailboxes_whose")]


class GhostMark(models.Model):
    """What the person did about one email on the brief: deferred, dismissed or handled it.

    An unanswered ask of theirs, or unread mail in the inbox (fr_dfce915c2c6d).
    Kept in Rouh only: nothing about it is written to the mailbox. Keyed on
    the mailbox and the thread, and on the message it was given to, so a
    dismissed ask comes back when a new ask is sent in the same thread, and a
    new email in a handled conversation shows as new.
    """

    id = models.BigAutoField(primary_key=True)
    user_id = models.TextField()
    org_id = models.TextField()
    mailbox_id = models.BigIntegerField()
    thread_id = models.TextField()
    message_id = models.TextField()
    #: "snoozed" (an ask deferred), "deferred" (an email that came in, deferred:
    #: read again by its id when its day comes), "dismissed", "handled", or
    #: "nudged" (a nudge was sent from the brief as a reply, `ghosts.send_nudge`).
    state = models.TextField()
    #: Until when a deferral holds; 0 for the others.
    until = models.FloatField(default=0)
    at = models.FloatField()

    class Meta:
        db_table = "ghost_marks"
        constraints = [models.UniqueConstraint(
            fields=["org_id", "user_id", "mailbox_id", "thread_id"], name="ghost_marks_one")]


# --- the heartbeat (`rouh/heartbeat.py`) -------------------------------------


class HeartbeatState(models.Model):
    """One person's heartbeat: whether it beats, how often, what it may spend, and what wakes it.

    One row per person. The heartbeat is general, part of Rouh's arsenal: its own duties
    and the long-running pieces of work it carries (`LongWork`) are what it does; nothing
    of any one piece of work is kept here. `config` holds every setting the page changes
    (hours, what wakes it, skips, messaging limits and the duties, `heartbeat.config_of`);
    the rest is what the loop needs to decide whether the next beat is worth a model call.
    """

    id = models.BigAutoField(primary_key=True)
    user_id = models.TextField()
    org_id = models.TextField()
    #: "on" or "paused".
    state = models.TextField(default="on")
    interval_minutes = models.IntegerField(default=30)
    #: The most its own model spend may be in a day, across every beat, in dollars.
    daily_cap = models.DecimalField(max_digits=10, decimal_places=2, default=3)
    #: The conversation every duties beat runs in, "Heartbeat"; never General.
    chat_id = models.TextField(blank=True, default="")
    #: Every setting, read with its defaults by `heartbeat.config_of`.
    config = models.JSONField(default=dict)
    #: Events not yet handed to a beat, oldest first: [{"kind", "at", "what", ...}].
    pending = models.JSONField(default=list)
    #: What is the heartbeat's own: {"runs", "threads", "files", "told"}.
    own = models.JSONField(default=dict)
    #: Silent notes for Rouh's next real turn with Petar: [{"at", "text", "seen"}].
    notes = models.JSONField(default=list)
    #: When its own next beat is due, and why (`heartbeat_next`); 0 for none.
    due_at = models.FloatField(default=0)
    due_what = models.TextField(blank=True, default="")
    last_beat_at = models.FloatField(default=0)
    last_full_at = models.FloatField(default=0)
    last_telegram_at = models.FloatField(default=0)
    #: When each of its Telegrams went, for the hourly and daily limits.
    sent = models.JSONField(default=list)
    #: Messages kept back during quiet hours, sent together when they end: [{"at", "text"}].
    held = models.JSONField(default=list)
    #: The day ("2026-10-05", Petar's clock) the daily summary last went.
    summary_day = models.TextField(blank=True, default="")
    #: Event wakes in the flood guard's window.
    wakes = models.JSONField(default=list)
    created_at = models.FloatField(default=0)
    updated_at = models.FloatField(default=0)

    class Meta:
        db_table = "heartbeat_state"
        constraints = [models.UniqueConstraint(fields=["org_id", "user_id"],
                                               name="heartbeat_state_one")]


class HeartbeatBeat(models.Model):
    """One beat: what woke it, and whether it was skipped and why, or what it did and cost.

    A beat is either the heartbeat's own, on its duties, in the Heartbeat chat, or one
    on a long-running piece of work (`work_id`), in that work's own chat.
    """

    id = models.BigAutoField(primary_key=True)
    user_id = models.TextField()
    org_id = models.TextField()
    #: "timer", "event", "due", "now" (asked for), "answer" (Petar answered the queue)
    #: or "summary" (the daily summary's time).
    trigger = models.TextField()
    #: The piece of work it was on, or None for the heartbeat's own duties.
    work_id = models.BigIntegerField(null=True, blank=True)
    #: The duties it said it acted on (`heartbeat.DUTIES` ids).
    duties = models.JSONField(default=list)
    #: The events it was handed, as in `HeartbeatState.pending`.
    events = models.JSONField(default=list)
    #: "skipped", "running", "done" or "failed".
    status = models.TextField(default="running")
    #: Why it was skipped, or what went wrong.
    reason = models.TextField(blank=True, default="")
    #: How it ended: "nothing", "note" or "telegram", and what it said.
    outcome = models.TextField(blank=True, default="")
    said = models.TextField(blank=True, default="")
    #: Every tool it called, in order: [{"name", "held"?}].
    tools = models.JSONField(default=list)
    cost = models.DecimalField(max_digits=12, decimal_places=6, null=True, blank=True)
    started_at = models.FloatField()
    finished_at = models.FloatField(null=True, blank=True)

    class Meta:
        db_table = "heartbeat_beats"
        indexes = [models.Index(fields=["org_id", "user_id", "started_at"],
                                name="heartbeat_beats_whose")]


class HeartbeatApproval(models.Model):
    """One thing a heartbeat may not do by itself, waiting for Petar's yes or no.

    `tool` and `args` are exactly what runs on a yes, and nothing else does; an empty `tool` is a
    decision with nothing to run. `what`, `to_whom`, `why` and `cost` are said to him as they are.
    `duty` or `work_id` says what raised it.
    """

    id = models.BigAutoField(primary_key=True)
    user_id = models.TextField()
    org_id = models.TextField()
    beat_id = models.BigIntegerField(null=True, blank=True)
    #: The piece of work it is for, or None.
    work_id = models.BigIntegerField(null=True, blank=True)
    #: The duty that raised it ("mail", "payments", ...), or "".
    duty = models.TextField(blank=True, default="")
    tool = models.TextField(blank=True, default="")
    args = models.JSONField(default=dict)
    what = models.TextField()
    to_whom = models.TextField(blank=True, default="")
    why = models.TextField(blank=True, default="")
    cost = models.TextField(blank=True, default="")
    #: Whether other work waits on this answer, which lets its Telegram past the hourly limit.
    blocking = models.BooleanField(default=False)
    #: "waiting", "yes", "no" or "failed" (a yes whose action could not run).
    state = models.TextField(default="waiting")
    #: "screen" or "telegram".
    answered_on = models.TextField(blank=True, default="")
    #: What the action answered, on a yes.
    result = models.TextField(blank=True, default="")
    asked_at = models.FloatField()
    answered_at = models.FloatField(null=True, blank=True)

    class Meta:
        db_table = "heartbeat_approvals"
        indexes = [models.Index(fields=["org_id", "user_id", "state"],
                                name="heartbeat_approvals_whose")]


# --- quests: the long-running work the heartbeat carries (`rouh/quests.py`) ------------


class LongWork(models.Model):
    """One quest's record, such as a money experiment the owner runs as a quest.

    A quest is a numbered task tagged Quest (`task_id`, `task_number`), whose goal, rules,
    plan and notebook are files in its folder; this is what must not live in git: its
    dates, its budget, its own spending cap under the Payments caps, its ledger (its own
    table), its chat, whether the heartbeat carries it, its events and what is its own.
    The table keeps its first name, `long_work`.
    """

    id = models.BigAutoField(primary_key=True)
    user_id = models.TextField()
    org_id = models.TextField()
    title = models.TextField()
    #: Its task: the object's id ("task-89") and its number (89), which is the quest's.
    task_id = models.TextField(blank=True, default="")
    task_number = models.IntegerField(default=0)
    #: A copy of the four files in its task, written with them, read only without them.
    goal = models.TextField(blank=True, default="")
    rules = models.TextField(blank=True, default="")
    plan = models.TextField(blank=True, default="")
    notebook = models.TextField(blank=True, default="")
    #: "on" or "paused".
    state = models.TextField(default="on")
    #: Whether the heartbeat works on it at all.
    carried = models.BooleanField(default=True)
    #: Its own chat, where every beat on it runs, made at its first beat.
    chat_id = models.TextField(blank=True, default="")
    #: Where its earlier beats ran, before it was a record of its own (the Heartbeat chat).
    earlier_chat_id = models.TextField(blank=True, default="")
    started_at = models.FloatField(default=0)
    #: When it ends; 0 for no end.
    ends_at = models.FloatField(default=0)
    #: Its hard cap in dollars: its model and tool spend plus its card charges. 0 for none.
    budget = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    #: The most one card purchase for it may be, under the Payments caps.
    spend_cap = models.DecimalField(max_digits=10, decimal_places=2, default=50)
    #: Model spend on it before it had a chat of its own (in the Heartbeat chat).
    spent_before = models.DecimalField(max_digits=12, decimal_places=6, default=0)
    #: Events for it not yet handed to a beat.
    pending = models.JSONField(default=list)
    #: What is its own: {"runs", "threads", "files"}.
    own = models.JSONField(default=dict)
    due_at = models.FloatField(default=0)
    due_what = models.TextField(blank=True, default="")
    last_beat_at = models.FloatField(default=0)
    last_full_at = models.FloatField(default=0)
    created_at = models.FloatField(default=0)
    updated_at = models.FloatField(default=0)

    class Meta:
        db_table = "long_work"
        indexes = [models.Index(fields=["org_id", "user_id"], name="long_work_whose")]


class LongWorkLedger(models.Model):
    """One amount of a piece of work's money, in or out.

    Written by a beat, by Petar, by a card purchase (`payments.fill_card`) or by a Stripe
    payment (`payments.webhook`); `ref` is the charge's or the payment's id, which is
    written once. A Stripe payment that came from no piece of work has no `work_id`.
    """

    id = models.BigAutoField(primary_key=True)
    user_id = models.TextField()
    org_id = models.TextField()
    work_id = models.BigIntegerField(null=True, blank=True)
    #: "in" or "out".
    direction = models.TextField()
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.TextField(default="USD")
    what = models.TextField()
    #: "heartbeat", "owner" ("petar" on older rows), "card" or "stripe".
    by = models.TextField()
    ref = models.TextField(blank=True, default="")
    at = models.FloatField()

    class Meta:
        db_table = "long_work_ledger"
        indexes = [models.Index(fields=["org_id", "user_id", "work_id", "at"],
                                name="long_work_ledger_whose")]
        constraints = [models.UniqueConstraint(
            fields=["org_id", "user_id", "ref"], condition=~Q(ref=""),
            name="long_work_ledger_ref_once")]


# --- payments: the card vault and Stripe (`rouh/payments.py`) ----------------------


class PaymentSettings(models.Model):
    """One person's Stripe key; their cards are `PaymentCard`s, each with its own caps.

    The Stripe key and the webhook's signing secret are sealed with `encryption.SecretBox`
    and opened only where they are used; only a masked key is ever shown or said.
    """

    id = models.BigAutoField(primary_key=True)
    user_id = models.TextField()
    org_id = models.TextField()
    stripe_sealed = models.TextField(blank=True, default="")
    #: The key as it may be shown: "rk_test_…a1b2".
    stripe_hint = models.TextField(blank=True, default="")
    #: "test" or "live", from the key's own prefix.
    stripe_mode = models.TextField(blank=True, default="")
    stripe_saved_at = models.FloatField(default=0)
    #: The webhook: the random part of its address here, Stripe's id for it, the
    #: address, and its signing secret, sealed.
    hook_token = models.TextField(blank=True, default="")
    hook_id = models.TextField(blank=True, default="")
    hook_url = models.TextField(blank=True, default="")
    hook_sealed = models.TextField(blank=True, default="")
    hook_saved_at = models.FloatField(default=0)
    updated_at = models.FloatField(default=0)

    class Meta:
        db_table = "payment_settings"
        constraints = [models.UniqueConstraint(fields=["org_id", "user_id"],
                                               name="payment_settings_one")]


class BillingEntity(models.Model):
    """Who a card's purchases are billed to (`rouh/payments.py`): one of a person's
    companies, or themselves.

    Petar, 14 October 2026 (fr_7c47d56e9a95): "we also need company details for the
    invoices- company, vat, and if anything else is filled. We actually need to have
    multiple entities saved. I have two business entities and one personal set of cards".
    `label` is how the Payments page and every message name it; the company, VAT number,
    registration number and invoice email are each optional, and a checkout is filled
    only with the ones that are set. The billing address is required, as a card's was.
    None of it is a credential, so it is kept in the clear and shown on the page.
    """

    id = models.BigAutoField(primary_key=True)
    user_id = models.TextField()
    org_id = models.TextField()
    label = models.TextField()
    company = models.TextField(blank=True, default="")
    vat = models.TextField(blank=True, default="")
    reg_number = models.TextField(blank=True, default="")
    email = models.TextField(blank=True, default="")
    line1 = models.TextField(blank=True, default="")
    line2 = models.TextField(blank=True, default="")
    city = models.TextField(blank=True, default="")
    postal_code = models.TextField(blank=True, default="")
    state = models.TextField(blank=True, default="")
    country = models.TextField(blank=True, default="")
    created_at = models.FloatField()
    updated_at = models.FloatField(default=0)

    class Meta:
        db_table = "billing_entities"
        indexes = [models.Index(fields=["org_id", "user_id", "created_at"],
                                name="billing_entities_whose")]


class ShippingOption(models.Model):
    """One way a parcel can reach the person, in their favourite order (`rouh/shipping.py`).

    Petar, 14 October 2026: "I need to be able to define logistics company, type of
    place, and specific address." So an option is the courier (`company`, free text, or
    "Any courier"), the kind of place (`kind`: a locker, an office or a door address), and
    the place itself: the courier's own code and name for a locker or an office, and the
    street, city, postcode, country, floor, apartment, entrance and door code. The
    recipient's name and phone are blank when they are the person's own defaults. `position`
    is its place in the main order, which the Default situation uses; `active` off skips it
    without losing it. `silo` is the silo it is labelled with, Personal unless the account has
    none of that name: it is private contact detail.
    """

    id = models.BigAutoField(primary_key=True)
    user_id = models.TextField()
    org_id = models.TextField()
    label = models.TextField()
    company = models.TextField(blank=True, default="")
    kind = models.TextField()
    place_code = models.TextField(blank=True, default="")
    place_name = models.TextField(blank=True, default="")
    line1 = models.TextField(blank=True, default="")
    city = models.TextField(blank=True, default="")
    postal_code = models.TextField(blank=True, default="")
    country = models.TextField(blank=True, default="")
    floor = models.TextField(blank=True, default="")
    apartment = models.TextField(blank=True, default="")
    entrance = models.TextField(blank=True, default="")
    door_code = models.TextField(blank=True, default="")
    recipient_name = models.TextField(blank=True, default="")
    recipient_phone = models.TextField(blank=True, default="")
    notes = models.TextField(blank=True, default="")
    position = models.IntegerField(default=0)
    active = models.BooleanField(default=True)
    silo = models.TextField(blank=True, default="")
    created_at = models.FloatField()
    updated_at = models.FloatField(default=0)

    class Meta:
        db_table = "shipping_options"
        indexes = [models.Index(fields=["org_id", "user_id", "position"],
                                name="shipping_options_whose")]


class ShippingSituation(models.Model):
    """A named situation with its own order of the saved options (`rouh/shipping.py`),
    such as "Big or heavy" or "Abroad". `options` is the ids of `ShippingOption` rows in
    the order they are tried. The Default situation is no row: it is the main order."""

    id = models.BigAutoField(primary_key=True)
    user_id = models.TextField()
    org_id = models.TextField()
    name = models.TextField()
    options = models.JSONField(blank=True, default=list)
    position = models.IntegerField(default=0)
    silo = models.TextField(blank=True, default="")
    created_at = models.FloatField()
    updated_at = models.FloatField(default=0)

    class Meta:
        db_table = "shipping_situations"
        indexes = [models.Index(fields=["org_id", "user_id", "position"],
                                name="shipping_situations_whose")]


class PaymentCard(models.Model):
    """One card in a person's vault (`rouh/payments.py`); a person may keep several.

    The card itself (number, expiry, security code, name and billing address, as one JSON
    text) is sealed with `encryption.SecretBox` and opened only by `payments._open_card`,
    to be filled into a checkout. Beside it, in the clear, only what the Payments page
    shows: the brand, the last four digits, the name on the card and the expiry month and
    year (0 for a card saved before 14 October 2026, when they were only in the seal).

    `silo` is the key of the one silo it is for (`rouh/silos.py`), or "" for none: a
    purchase in that silo fills it before any other card (14 October 2026, fr_3c19cfb75db1).

    `entity_id` is the `BillingEntity` it belongs to, whose company details and address
    a checkout is filled with (14 October 2026, fr_7c47d56e9a95); None for a card saved
    before entities whose sealed billing address has not been carried over yet
    (`payments.carry_over`). A card's billing address is its entity's, not the seal's.

    `per_purchase`, `per_day` and `per_month` are the card's own spending caps in dollars,
    each None for no cap of that kind: the most one purchase may be, and all of the card's
    purchases in a day and in a calendar month (14 October 2026, fr_c29d7ddcee31: "Each card
    needs to have a limit", and then "I have a spending cap but it needs to be per card").
    They took the place of one cap a purchase and a day for the whole vault, which every
    card was given as its own when they did. A purchase that would cross one is refused
    before the fill.
    """

    id = models.BigAutoField(primary_key=True)
    user_id = models.TextField()
    org_id = models.TextField()
    sealed = models.TextField()
    brand = models.TextField(blank=True, default="")
    last4 = models.TextField(blank=True, default="")
    name = models.TextField(blank=True, default="")
    exp_month = models.IntegerField(default=0)
    exp_year = models.IntegerField(default=0)
    saved_at = models.FloatField()
    silo = models.TextField(blank=True, default="")
    entity_id = models.BigIntegerField(null=True, blank=True)
    per_purchase = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    per_day = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    per_month = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    class Meta:
        db_table = "payment_cards"
        indexes = [models.Index(fields=["org_id", "user_id", "saved_at"],
                                name="payment_cards_whose")]


class CloudflareZone(models.Model):
    """One Cloudflare zone an organisation keeps an API token for (`rouh/cloudflare.py`).

    The token is typed into Settings, Cloudflare, checked with Cloudflare and sealed with
    `encryption.SecretBox`; only its last four characters, when it was saved and how its
    last check went are ever shown or said. Keyed and asked for by organisation.
    """

    id = models.BigAutoField(primary_key=True)
    org_id = models.TextField()
    #: The zone's domain name, lower case: "example.com".
    zone = models.TextField()
    #: Cloudflare's ids for the zone and its account, given or found by a check.
    zone_id = models.TextField(blank=True, default="")
    account_id = models.TextField(blank=True, default="")
    #: The zone's status at Cloudflare when last checked: "active", "pending".
    status = models.TextField(blank=True, default="")
    #: One of the zones this install starts with (`cloudflare.STARTING`), which stay listed.
    starting = models.BooleanField(default=False)
    token_sealed = models.TextField(blank=True, default="")
    last4 = models.TextField(blank=True, default="")
    saved_at = models.FloatField(default=0)
    #: Who saved it, or "" for one carried over from the server's settings.
    saved_by = models.TextField(blank=True, default="")
    #: "settings", typed on the page, or "server", carried over (`cloudflare._carry_over`).
    source = models.TextField(blank=True, default="")
    #: The server's token was carried over once, so a token removed here does not come back.
    carried = models.BooleanField(default=False)
    checked_at = models.FloatField(default=0)
    check_ok = models.BooleanField(null=True, blank=True)
    #: Each check as {name, ok, optional, said}, never with the token in it.
    checks = models.JSONField(default=list, blank=True)
    made_at = models.FloatField(default=0)
    updated_at = models.FloatField(default=0)

    class Meta:
        db_table = "cloudflare_zones"
        constraints = [models.UniqueConstraint(fields=["org_id", "zone"], name="cloudflare_zones_one")]


class SignupGrant(models.Model):
    """One sign-up the person authorized the live browser to make for them (`rouh/signups.py`).

    One new account on one service: its site (the registrable domain, which covers every
    page under it), the email it is made with, the person's own words, and the password
    they set for it on the Sign-ups page, sealed with `encryption.SecretBox` and emptied
    when it is withdrawn or runs out. Keyed and asked for by person and organisation.
    """

    id = models.BigAutoField(primary_key=True)
    user_id = models.TextField()
    org_id = models.TextField()
    service = models.TextField()
    site = models.TextField()
    email = models.TextField(blank=True, default="")
    #: What the person said, quoted, or "Allowed on the Sign-ups page.".
    words = models.TextField(blank=True, default="")
    #: "conversation" or "settings".
    source = models.TextField(default="conversation")
    chat = models.TextField(blank=True, default="")
    granted_at = models.FloatField()
    expires_at = models.FloatField()
    withdrawn_at = models.FloatField(null=True, blank=True)
    password_sealed = models.TextField(blank=True, default="")
    password_set_at = models.FloatField(null=True, blank=True)
    filled_at = models.FloatField(null=True, blank=True)
    submitted_at = models.FloatField(null=True, blank=True)

    class Meta:
        db_table = "signup_grants"
        indexes = [models.Index(fields=["org_id", "user_id", "expires_at"],
                                name="signup_grants_whose")]


class CardCharge(models.Model):
    """One purchase made with the vault's card: filled into a checkout page by Rouh.

    Written before the card is filled, so the caps count it whatever the page does next;
    `state` is "filled", or "void" when Petar says it never went through. One Rouh placed
    the order for itself has `placed_at`. An order submitted at a shop before the card, to be
    paid on its payment provider's page, is "submitted" until the card goes in there, and
    "unpaid" when it was left without being paid.

    A press of the Pay or order button is not a payment (17 October 2026, charge 2 at
    an online shop, which was told as paid while the bank's 3-D Secure still waited): from the
    press the charge is "confirming", "bank" while the page asks for Petar's bank approval,
    and "paid" only once the page shows the shop's or the payment provider's confirmation;
    "failed" when the page says it was declined, and "unconfirmed" when nothing was seen
    either way (`payments.settle`).
    """

    id = models.BigAutoField(primary_key=True)
    user_id = models.TextField()
    org_id = models.TextField()
    work_id = models.BigIntegerField(null=True, blank=True)
    merchant = models.TextField()
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.TextField(default="USD")
    reason = models.TextField()
    brand = models.TextField(blank=True, default="")
    last4 = models.TextField(blank=True, default="")
    state = models.TextField(default="filled")
    at = models.FloatField()
    #: The run of the one program that paid, for the nightly feature run's own cap a run
    #: (`rouh/nightly_feature.py`); empty for a purchase Rouh made in its live browser.
    run_id = models.TextField(blank=True, default="")
    #: Who it was billed to, as the card's billing entity was named when it was filled
    #: ("Company A (Company A Ltd)"), so editing the entity later does not rewrite it.
    billed_to = models.TextField(blank=True, default="")
    #: The `PaymentCard` it was filled from, for that card's own caps; None for a purchase
    #: made before 14 October 2026, which the caps count by its brand and last four.
    card_id = models.BigIntegerField(null=True, blank=True)
    #: When Rouh pressed the order button itself, for a purchase Petar asked for in his own
    #: words (`rouh/purchases.py`, `payments.place_order`); None when it did not. Then
    #: `amount` is the total the page showed, `bought` what was ordered and `words` his
    #: words that authorized it.
    placed_at = models.FloatField(null=True, blank=True)
    bought = models.TextField(blank=True, default="")
    words = models.TextField(blank=True, default="")
    #: When Rouh pressed the order button of a shop that takes the card only afterwards, on
    #: its payment provider's page (`payments._submit`); the charge is then "submitted"
    #: until the card is filled there, and "unpaid" if it never was.
    submitted_at = models.FloatField(null=True, blank=True)
    #: The workspace task it was for, "122" or "122-04", when one was named rather than a
    #: quest (`payments.task_ref`); "" when none was.
    task_ref = models.TextField(blank=True, default="")
    #: The address it was billed to, the card's billing entity's as it was then, and where it
    #: was delivered, a shipping option's label and place, for an order Rouh placed: each kept
    #: so the Payments page shows both and Petar can check them (fr_cd4ba48083df). "" for a
    #: purchase made before 17 October 2026, or one whose page showed neither.
    billing_address = models.TextField(blank=True, default="")
    delivered_to = models.TextField(blank=True, default="")
    #: When Rouh pressed the button that pays (`payments.place_order`), and the page's own
    #: words about what became of it: a decline, the bank's request, or the confirmation.
    #: `placed_at` is set only when the payment is confirmed.
    pressed_at = models.FloatField(null=True, blank=True)
    outcome = models.TextField(blank=True, default="")

    class Meta:
        db_table = "card_charges"
        indexes = [models.Index(fields=["org_id", "user_id", "at"], name="card_charges_whose")]


class StripeLink(models.Model):
    """A Stripe product, price or payment link Rouh made, and the piece of work it is for."""

    id = models.BigAutoField(primary_key=True)
    user_id = models.TextField()
    org_id = models.TextField()
    work_id = models.BigIntegerField(null=True, blank=True)
    #: "product", "price" or "payment_link".
    kind = models.TextField()
    stripe_id = models.TextField()
    name = models.TextField(blank=True, default="")
    url = models.TextField(blank=True, default="")
    at = models.FloatField()

    class Meta:
        db_table = "stripe_links"
        indexes = [models.Index(fields=["org_id", "user_id", "stripe_id"],
                                name="stripe_links_whose")]


# --- the nightly feature run (`rouh/nightly_feature.py`) and its switches (`rouh/switches.py`) --


class PaidService(models.Model):
    """One outside service paid for again and again: a subscription, a plan or a trial that
    turns into one (`rouh/services.py`, Anatomy, Money, Services).

    Petar, 15 October 2026: "Services are things we purchase and we need to track and maybe
    unsubscribe." Kept by hand on the Services page, so each renewal, trial's end and way out
    is in one place; it has nothing to do with the nightly feature run, which keeps its own
    sign-ups in its task's services.md. `amount` is what one `period` costs ("month", "year",
    "week" or "once"), None for not known; `state` is "active", "trial" or "cancelled".
    Nothing secret is kept: `account` names the login, never its password.
    """

    id = models.BigAutoField(primary_key=True)
    user_id = models.TextField()
    org_id = models.TextField()
    name = models.TextField()
    what_for = models.TextField(blank=True, default="")
    amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    currency = models.TextField(default="USD")
    period = models.TextField(default="month")
    renews_on = models.DateField(null=True, blank=True)
    trial_ends = models.DateField(null=True, blank=True)
    paid_with = models.TextField(blank=True, default="")
    account = models.TextField(blank=True, default="")
    cancel_how = models.TextField(blank=True, default="")
    state = models.TextField(default="active")
    created_at = models.FloatField()
    updated_at = models.FloatField()
    cancelled_at = models.FloatField(null=True, blank=True)

    class Meta:
        db_table = "paid_services"
        indexes = [models.Index(fields=["org_id", "user_id", "state"], name="paid_services_whose")]


class NightlyFeatureNight(models.Model):
    """One night of the nightly Rouh feature run: its run, what it built, and Petar's answer.

    Written when the night starts, before the run does, so there is always a row. The run
    fills in what it built when it asks its one question (`nightly_feature.ask`), and the
    answer is written here when Petar gives it (`decision_sources.NightlySource`).
    """

    id = models.BigAutoField(primary_key=True)
    user_id = models.TextField()
    org_id = models.TextField()
    #: 1, 2, 3, ... for this person.
    number = models.IntegerField()
    run_id = models.TextField(blank=True, default="")
    #: The port the run's browser opens DevTools on, on loopback, so Rouh can fill the
    #: vault's card into its checkout (`payments.fill_card_in_run`).
    browser_port = models.IntegerField(default=0)
    #: "running", "ended" or "failed" (it never started; `why` says why).
    state = models.TextField(default="running")
    why = models.TextField(blank=True, default="")
    started_at = models.FloatField()
    #: What the run built, as it asked about it.
    feature = models.TextField(blank=True, default="")
    switch = models.TextField(blank=True, default="")
    built = models.TextField(blank=True, default="")
    try_it = models.TextField(blank=True, default="")
    saves = models.TextField(blank=True, default="")
    #: Workspace paths of its screenshots, and of the night's report page.
    screenshots = models.JSONField(default=list, blank=True)
    report = models.TextField(blank=True, default="")
    asked_at = models.FloatField(null=True, blank=True)
    #: Petar's answer: "accepted", "rejected" or "other", with his own words for other.
    verdict = models.TextField(blank=True, default="")
    words = models.TextField(blank=True, default="")
    decided_at = models.FloatField(null=True, blank=True)
    #: The run that reverts and cancels it, on Reject and undo.
    undo_run_id = models.TextField(blank=True, default="")
    #: When a later night's brief carried the answer on, so it is carried once.
    handed_on = models.FloatField(null=True, blank=True)
    #: What Parameters asked of this night when it started, {"total", and each kind}: the number
    #: of genes it has to finish, not a ceiling on the ideas it may try (`nightly_feature.progress`).
    target = models.JSONField(default=dict, blank=True)
    #: How many of each kind it finished, written when the night ends, and why it ended short of
    #: its target when it did: an operational blocker, in words, never "no good idea".
    filled = models.JSONField(default=dict, blank=True)
    short_why = models.TextField(blank=True, default="")
    #: Each time Rouh sent the run back to work short of its target: {"at", "done"}.
    nudges = models.JSONField(default=list, blank=True)

    class Meta:
        db_table = "nightly_feature_nights"
        constraints = [models.UniqueConstraint(fields=["org_id", "user_id", "number"],
                                               name="nightly_feature_night_number")]


class NightlyFeatureService(models.Model):
    """A service a night signed up for: counted against the two a night, its login sealed.

    The service log Petar reads is the task's services.md, which the run writes before
    every sign-up; this row is what Rouh needs to hold itself: the count, the address, and
    the login the run made, sealed with `encryption.SecretBox` and never in a file.
    """

    id = models.BigAutoField(primary_key=True)
    user_id = models.TextField()
    org_id = models.TextField()
    night_id = models.BigIntegerField()
    #: One lowercase word, as the address carries it: rouh+<service>@<Rouh's own mailbox's domain>
    #: (`inbox.own`).
    service = models.TextField()
    address = models.TextField()
    why = models.TextField(blank=True, default="")
    #: The user name the login is under, which may be shown; the password never is.
    login_name = models.TextField(blank=True, default="")
    login_sealed = models.TextField(blank=True, default="")
    at = models.FloatField()

    class Meta:
        db_table = "nightly_feature_services"
        indexes = [models.Index(fields=["org_id", "user_id", "service"],
                                name="nightly_service_whose")]


class NightlyRefactorNight(models.Model):
    """One night of the nightly code refactoring run (`rouh/nightly_refactor.py`): its run,
    what it refactored and the commits it landed, and the run that undid them, if Petar asked.

    Written when the night's time comes, before the run starts, so a night that waits for the
    feature run to land is a row too, and its wait outlives a restart.
    """

    id = models.BigAutoField(primary_key=True)
    user_id = models.TextField()
    org_id = models.TextField()
    #: 1, 2, 3, ... for this person.
    number = models.IntegerField()
    run_id = models.TextField(blank=True, default="")
    #: "waiting" (for the feature run, or the home task), "running", "ended" or "failed"
    #: (it never started; `why` says why).
    state = models.TextField(default="waiting")
    why = models.TextField(blank=True, default="")
    #: When its time came, and when its run started.
    started_at = models.FloatField()
    began_at = models.FloatField(null=True, blank=True)
    #: What the run said it did (`refactor_done`): "refactored", "nothing" or "failed", a summary,
    #: each item ({id, title, commits, files, result}), every commit it landed, and how many
    #: candidates are still on the list.
    outcome = models.TextField(blank=True, default="")
    summary = models.TextField(blank=True, default="")
    items = models.JSONField(default=list, blank=True)
    commits = models.JSONField(default=list, blank=True)
    left = models.IntegerField(default=0)
    reported_at = models.FloatField(null=True, blank=True)
    #: The run that reverts its commits, on Undo in the morning brief.
    undo_run_id = models.TextField(blank=True, default="")
    undone_at = models.FloatField(null=True, blank=True)

    class Meta:
        db_table = "nightly_refactor_nights"
        constraints = [models.UniqueConstraint(fields=["org_id", "user_id", "number"],
                                               name="nightly_refactor_night_number")]


class FeatureSwitch(models.Model):
    """One feature's on/off switch (`rouh/switches.py`), the organisation's.

    A switch nobody has written is on: a row is made when a feature registers its switch or
    when somebody turns it off, which is what Reject and undo does first.
    """

    id = models.BigAutoField(primary_key=True)
    org_id = models.TextField()
    name = models.TextField()
    title = models.TextField(blank=True, default="")
    on = models.BooleanField(default=True)
    #: The nightly feature run's night that made it, when one did.
    night_id = models.BigIntegerField(null=True, blank=True)
    changed_by = models.TextField(blank=True, default="")
    updated_at = models.FloatField()

    class Meta:
        db_table = "feature_switches"
        constraints = [models.UniqueConstraint(fields=["org_id", "name"],
                                               name="feature_switch_one")]


# --- shared genes: the registry an organisation points at, and its lab (`rouh/genelab.py`) --


class GeneRegistry(models.Model):
    """The gene registry an organisation fetches shared genes from, and the key it pins.

    No row, or a row with no address, is the lab switched off: Rouh asks no registry
    anything until a person points it at one in Meta, Gene registry. What was last fetched is
    kept here only after its signature held against the pinned key.
    """

    id = models.BigAutoField(primary_key=True)
    org_id = models.TextField()
    #: The registry's address, such as https://rouh.land/registry/; "" is off.
    url = models.TextField(blank=True, default="")
    #: The registry's Ed25519 public key, PEM, pinned here by a person.
    public_key = models.TextField(blank=True, default="")
    key_id = models.TextField(blank=True, default="")
    set_by = models.TextField(blank=True, default="")
    set_at = models.FloatField(default=0)
    #: The last index and blocklist whose signatures held, as their payloads.
    index = models.JSONField(default=dict, blank=True)
    blocklist = models.JSONField(default=dict, blank=True)
    #: When each was made by the registry (its own made_at), so an older one is refused.
    index_made_at = models.TextField(blank=True, default="")
    blocklist_made_at = models.TextField(blank=True, default="")
    fetched_at = models.FloatField(default=0)
    #: What went wrong the last time, said as a sentence; "" when it went well.
    error = models.TextField(blank=True, default="")
    error_at = models.FloatField(default=0)

    class Meta:
        db_table = "gene_registries"
        constraints = [models.UniqueConstraint(fields=["org_id"], name="gene_registry_one")]


class SharedGene(models.Model):
    """One shared gene in an organisation's lab: its contract, its files, its switch.

    Installed only on a person's yes, after its contract was shown to them, and always
    switched off at first. Its files are kept here and never run. Removing it deletes this
    row and its switch, and checks that nothing named for it is left.
    """

    id = models.BigAutoField(primary_key=True)
    org_id = models.TextField()
    #: The registry's id, "<publisher>/<name>".
    gene = models.TextField()
    publisher = models.TextField()
    name = models.TextField()
    version = models.TextField()
    kind = models.TextField(blank=True, default="")
    #: The contract as the signed index gave it, and its hash, which the person saw.
    contract = models.JSONField(default=dict)
    contract_sha256 = models.TextField()
    #: The rest of the index's row: publisher, rating, provenance, as information.
    listing = models.JSONField(default=dict, blank=True)
    artifact_url = models.TextField()
    artifact_sha256 = models.TextField()
    artifact = models.BinaryField()
    #: Each file in it: {path, size, sha256}.
    files = models.JSONField(default=list, blank=True)
    #: How its Sigstore signature went: {state, said, identity}.
    sigstore = models.JSONField(default=dict, blank=True)
    #: Its own feature switch (`rouh/switches.py`), off when it arrives.
    switch = models.TextField()
    #: "lab", or "blocked" once the registry's blocklist names it.
    state = models.TextField(default="lab")
    blocked = models.JSONField(default=dict, blank=True)
    #: A newer version the index offers, with what changed in its contract; never installed by itself.
    update = models.JSONField(default=dict, blank=True)
    #: What the lab held just before it was installed, for the check after it is removed.
    before = models.JSONField(default=dict, blank=True)
    installed_by = models.TextField(blank=True, default="")
    installed_by_name = models.TextField(blank=True, default="")
    installed_at = models.FloatField(default=0)
    updated_at = models.FloatField(default=0)

    class Meta:
        db_table = "shared_genes"
        constraints = [models.UniqueConstraint(fields=["org_id", "gene"], name="shared_gene_one")]


class GeneLabEvent(models.Model):
    """What was done in an organisation's lab, and by whom: installed, switched on or off,
    updated, removed and checked, blocklisted. The lab's history, kept after a gene is gone."""

    id = models.BigAutoField(primary_key=True)
    org_id = models.TextField()
    gene = models.TextField()
    version = models.TextField(blank=True, default="")
    what = models.TextField()
    said = models.TextField(blank=True, default="")
    by = models.TextField(blank=True, default="")
    detail = models.JSONField(default=dict, blank=True)
    at = models.FloatField()

    class Meta:
        db_table = "gene_lab_events"
        indexes = [models.Index(fields=["org_id", "at"], name="gene_lab_events_when")]


# --- decisions: everything waiting on the person, in one place (`rouh/decisions.py`) ------


class Decision(models.Model):
    """One thing waiting on a person's answer, wherever it came from.

    A task's question, a heartbeat or quest approval, a goal step's decision, a run of the one
    program asking leave, a landing that collided: each source keeps its own record of what it
    asked, and this is the one copy of it that every place draws - the Decisions page, the
    task's page, the run's card, Telegram and Rouh's own `decisions` tool. `source` and
    `source_id` say where it came from, and `key` which question of it: a source that asks
    something new asks it under a new key, so an answer is always to the words it was given.
    The answer goes back through the source (`decision_sources`), once, whoever gave it and
    wherever. See `rouh/decisions.py` for what every column means.
    """

    id = models.BigAutoField(primary_key=True)
    user_id = models.TextField()
    org_id = models.TextField()
    #: What the person says and sees for it, "Decision 42": 1 for their first decision and one
    #: more for each after, never given twice (`decision_numbers`, `decisions._Numbers`). None
    #: only for a row made by code older than numbers, until the next sync gives it one.
    number = models.IntegerField(null=True, blank=True)
    #: The handle (a482) a decision asked between 8 and 18 October 2026 was given. Nothing gives,
    #: shows or reads one any more (29 October 2026: the number is a decision's only name); the
    #: column is kept as the record of what was said then.
    handle = models.TextField(blank=True, default="", db_default="")
    #: "task", "goal", "approval", "run" or "conflict".
    source = models.TextField()
    #: The source's own id for it: a task's id, a step's folder, an approval's number, ...
    source_id = models.TextField()
    #: Which question of that source: its id and the words it asked, hashed.
    key = models.TextField()
    #: Where its context is (an address in Rouh), and what to call it there.
    link = models.TextField(blank=True, default="")
    context = models.TextField(blank=True, default="")
    #: The project it belongs to, for grouping ("Work", "Personal", "Rouh"), or "".
    project = models.TextField(blank=True, default="")
    #: Related questions share it, and are drawn together.
    batch = models.TextField(blank=True, default="")
    title = models.TextField()
    question = models.TextField()
    why = models.TextField(blank=True, default="")
    then = models.TextField(blank=True, default="")
    #: What Rouh already prepared: [{"label", "href"?, "text"?}].
    prepared = models.JSONField(default=list)
    #: [{"id", "label", "detail", "go"}]; `go` is an option that carries out the risk.
    options = models.JSONField(default=list)
    #: The small questions it holds, each answered with its options, all at once or one by
    #: one: [{"id", "label", "text", "href", "detail", "why", "sides"}]. A night of Synapse's
    #: changes of one kind is one decision with its changes here (`decision_sources`).
    items = models.JSONField(default=list, db_default=[])
    #: Its line on the Decisions page and in the tool's list (`decisions.line_of`): {"yes",
    #: "wait", "blocks", "tags", "advice"}, what a yes does and what waiting costs.
    line = models.JSONField(default=dict, db_default={})
    recommended = models.TextField(blank=True, default="")
    recommended_why = models.TextField(blank=True, default="")
    allow_other = models.BooleanField(default=True)
    #: "choice", "multi", "yes_no", "text", "date" or "approval".
    answer_type = models.TextField(default="choice")
    #: "now", "today", "soon" or "whenever".
    urgency = models.TextField(default="soon")
    due_at = models.FloatField(null=True, blank=True)
    #: "reversible", "money", "sending", "publishing" or "irreversible".
    risk = models.TextField(default="reversible")
    #: The risk in plain words, as the person confirms it: "Sends an email to ...".
    risk_note = models.TextField(blank=True, default="")
    #: open, snoozed, answered, applying, applied, failed, expired, withdrawn or dismissed.
    status = models.TextField(default="open")
    snoozed_until = models.FloatField(null=True, blank=True)
    #: {"choice": [option ids], "text": his own words, "said": the answer as a sentence}.
    answer = models.JSONField(default=dict)
    #: The account that answered, or "rouh" when he asked Rouh to decide.
    answered_by = models.TextField(blank=True, default="")
    #: "screen", "telegram", "voice", or where the source itself was answered.
    channel = models.TextField(blank=True, default="")
    #: What the source said when the answer went back to it.
    result = models.TextField(blank=True, default="")
    #: When the answer goes back to its source, so it can be undone until then.
    apply_at = models.FloatField(null=True, blank=True)
    #: The Telegram message it was sent in, so its buttons can be taken off once answered.
    telegram_message = models.BigIntegerField(null=True, blank=True)
    created_at = models.FloatField()
    updated_at = models.FloatField()
    answered_at = models.FloatField(null=True, blank=True)
    resolved_at = models.FloatField(null=True, blank=True)

    class Meta:
        db_table = "decisions"
        constraints = [models.UniqueConstraint(fields=["org_id", "user_id", "source", "key"],
                                               name="decisions_one_per_question"),
                       models.UniqueConstraint(fields=["org_id", "user_id", "handle"],
                                               condition=~models.Q(handle=""),
                                               name="decisions_one_handle"),
                       models.UniqueConstraint(fields=["org_id", "user_id", "number"],
                                               condition=models.Q(number__isnull=False),
                                               name="decisions_one_number")]
        indexes = [models.Index(fields=["org_id", "user_id", "status"], name="decisions_whose"),
                   models.Index(fields=["status", "apply_at"], name="decisions_due")]


class DecisionEvent(models.Model):
    """One line of a decision's history: asked, snoozed, answered, undone, applied, withdrawn.

    Kept for good, beside the decision, so what was answered, by whom, where and with what
    result can always be read back."""

    id = models.BigAutoField(primary_key=True)
    decision_id = models.BigIntegerField()
    user_id = models.TextField()
    org_id = models.TextField()
    #: "asked", "changed", "snoozed", "woke", "answered", "undone", "applying", "applied",
    #: "failed", "withdrawn", "dismissed", "expired", "told".
    kind = models.TextField()
    by = models.TextField(blank=True, default="")
    channel = models.TextField(blank=True, default="")
    detail = models.TextField(blank=True, default="")
    at = models.FloatField()

    class Meta:
        db_table = "decision_events"
        indexes = [models.Index(fields=["decision_id", "at"], name="decision_events_of")]


class DecisionGate(models.Model):
    """What the gate in front of the decisions said of one question (`rouh/decision_gate.py`).

    Petar, 18 October 2026: a question is put to him only when work he asked for has truly
    stopped without him and the answer is his to give. Every question a source asks is judged
    once, under its key, and this is that judgement: let through ("ask"), kept from him
    ("clear"), or still to be judged ("pending"). It is the log of what the gate refused, for
    whoever debugs it, and it is never drawn for him. A question he opened again himself is
    "ask" by "person", and is never judged again."""

    id = models.BigAutoField(primary_key=True)
    user_id = models.TextField()
    org_id = models.TextField()
    source = models.TextField()
    source_id = models.TextField(blank=True, default="")
    #: The question's key, as the decision has it (`decisions.key_of`).
    key = models.TextField()
    #: "pending", "ask" or "clear".
    verdict = models.TextField(default="pending")
    #: "code" (the source's own rule), "model" (the judge), "fallback" (the judge could not be
    #: asked) or "person" (he opened it again).
    by = models.TextField(blank=True, default="")
    reason = models.TextField(blank=True, default="")
    #: Rouh's recommendation instead of the question, in words.
    recommendation = models.TextField(blank=True, default="")
    #: The judge's reading of the work: "finished", "stopped" or "going".
    work = models.TextField(blank=True, default="")
    title = models.TextField(blank=True, default="")
    question = models.TextField(blank=True, default="")
    #: What the judge is given, kept so a pending question is judged as it was asked.
    facts = models.JSONField(default=dict)
    model = models.TextField(blank=True, default="")
    tries = models.IntegerField(default=0)
    #: When the judge may be asked again after it could not answer.
    retry_at = models.FloatField(null=True, blank=True)
    created_at = models.FloatField()
    judged_at = models.FloatField(null=True, blank=True)

    class Meta:
        db_table = "decision_gate"
        constraints = [models.UniqueConstraint(fields=["org_id", "user_id", "source", "key"],
                                               name="decision_gate_one_per_question")]
        indexes = [models.Index(fields=["org_id", "user_id", "verdict"], name="decision_gate_whose")]


class Notice(models.Model):
    """One notification for a person: it drops in at the top of their screen first, and goes to
    their phone only if it is left there (`rouh/notices.py`).

    Petar, 10 October 2026 (fr_8f09d161935f): "you first give me a notification, and I can look
    at it and dismiss it. If not, I also get a Telegram notification." So a row is what was
    said, where it leads, where it stands on the screen, and what became of its phone copy.
    """

    id = models.BigAutoField(primary_key=True)
    user_id = models.TextField()
    org_id = models.TextField()
    #: The sender's own name for it, so the same thing is never said twice ("job:<id>:<what>"),
    #: or "" for a note that is never repeated.
    key = models.TextField(blank=True, default="")
    #: What kind of thing said it: "job", "reminder", "decision", "mail", "brief", "meeting",
    #: "conflict", "browser", "rouh". Its icon on the screen, and nothing else.
    kind = models.TextField(blank=True, default="")
    title = models.TextField()
    body = models.TextField(blank=True, default="")
    #: Where swiping it right goes: an address in Rouh ("/run/<id>"), or a whole URL elsewhere.
    link = models.TextField(blank=True, default="")
    #: What that is, in a few words: "Open the run".
    link_label = models.TextField(blank=True, default="")
    #: Every place it leads, each a button of its own beside the rest, as
    #: `[{"to", "label", "href", "title"}]`, or [] for a notice with `link` alone. A finished
    #: run connected to a task has its run, chat, task and page here (`run_report.destinations`).
    links = models.JSONField(blank=True, default=list)
    #: The decision it asks, drawn inside it when it is opened (`decisions`), or None.
    decision_id = models.BigIntegerField(null=True, blank=True)
    #: The commit a finished run put live, seven characters of it, or "". A page served before
    #: that deploy offers its Reload on this notice rather than in one of its own (`notices.js`).
    deployed = models.TextField(blank=True, default="")
    #: new (on the screen), later (put away, still to read), read, or dismissed.
    state = models.TextField(default="new")
    #: The words its Telegram copy is sent in, or "" when it never goes to the phone.
    phone_text = models.TextField(blank=True, default="")
    #: "" (nothing to send), due, sending, sent, skipped (not needed or no bot), or failed.
    phone = models.TextField(blank=True, default="")
    created_at = models.FloatField()
    #: When a screen first drew it with the page in front of the person.
    seen_at = models.FloatField(null=True, blank=True)
    handled_at = models.FloatField(null=True, blank=True)
    phoned_at = models.FloatField(null=True, blank=True)

    class Meta:
        db_table = "notices"
        constraints = [models.UniqueConstraint(fields=["org_id", "user_id", "key"],
                                               condition=~models.Q(key=""),
                                               name="notices_said_once")]
        indexes = [models.Index(fields=["org_id", "user_id", "created_at"], name="notices_whose"),
                   models.Index(fields=["phone", "state"], name="notices_phone_due")]


# --- how often each row of the navigation is pressed (`rouh/navtaps.py`) ---


class NavTap(models.Model):
    """One press of one row of the sidebar's navigation, for Settings, Stats.

    Petar, 10 October 2026 (fr_e82bf294e064): "I see navigation tap counts ... for
    total for 30 days rolling back." A row is who pressed what, and when.
    """

    id = models.BigAutoField(primary_key=True)
    user_id = models.TextField()
    org_id = models.TextField()
    #: The row's key in `navtaps.ITEMS`: "tasks", "runs", "rouh", ..., or a group box's,
    #: "group:work" (since 12 October 2026, fr_0ef0ca151b48).
    item = models.TextField()
    #: The page load it was pressed in, an id the page made, so the flow can follow one
    #: journey at a time; empty for presses from before it was sent.
    visit = models.TextField(blank=True, default="")
    at = models.FloatField()

    class Meta:
        db_table = "nav_taps"
        indexes = [models.Index(fields=["org_id", "user_id", "at"], name="nav_taps_whose")]


# --- what the person did with no connection, carried out once (`rouh/offline.py`) ---


class OfflineAction(models.Model):
    """One thing the person did on a device with no connection, sent when it came back.

    Petar, 12 October 2026 (card 1457, "Rouh offline, on laptop and phone"): act now, have it
    carried out later. Each device keeps an outbox of what was done offline - a decision
    answered, a reply written, a page edited, a note recorded - and sends it when it reconnects.
    This is the one outbox on the server: a row per action, under the id the device gave it, so
    an action is carried out exactly once whichever device sends it and however often.
    `base` is the version of what it acted on, so an action whose subject moved meanwhile is
    turned into a decision instead of being carried out over the newer version.
    """

    id = models.BigAutoField(primary_key=True)
    user_id = models.TextField()
    org_id = models.TextField()
    #: The id the device gave it when it was made, unique for the person.
    action_id = models.TextField()
    #: Which device made it, and what kind of device: "laptop" or "phone".
    device_id = models.TextField(blank=True, default="")
    device_name = models.TextField(blank=True, default="")
    device_kind = models.TextField(blank=True, default="")
    #: "decision", "reply", "draft", "page", "reminder", "task" or "note" (`offline.KINDS`).
    kind = models.TextField()
    payload = models.JSONField(default=dict)
    #: The version of what it acted on, as the device had it.
    base = models.JSONField(default=dict)
    #: When it was done on the device, by the device's clock, and when it reached the server.
    made_at = models.FloatField()
    received_at = models.FloatField()
    #: received, running, done, clash, held, failed or dropped (`offline.STATUSES`).
    status = models.TextField(default="received")
    #: What became of it, in a sentence the device shows.
    result = models.TextField(blank=True, default="")
    #: What it made: a draft's id, a decision's id, a task's number, and for a clash both sides.
    outcome = models.JSONField(default=dict)
    done_at = models.FloatField(null=True, blank=True)
    updated_at = models.FloatField()

    class Meta:
        db_table = "offline_actions"
        constraints = [models.UniqueConstraint(fields=["org_id", "user_id", "action_id"],
                                               name="offline_actions_once")]
        indexes = [models.Index(fields=["org_id", "user_id", "updated_at"], name="offline_actions_whose"),
                   models.Index(fields=["org_id", "user_id", "status"], name="offline_actions_state")]


class Thought(models.Model):
    """One of the person's thoughts, kept in their own words (`rouh/thoughts.py`).

    Petar, 12 October 2026: "If I have random thoughts that come to my mind and I want you to
    remember them reliably what feature would you use to handle that?" - and, told that a note
    in Synapse was only found by search and there was no list of his thoughts, "But that is
    exactly what I was interested in getting solved". So a thought is its own kind of thing,
    kept here, listed on the Thoughts page, and copied into Synapse Master as an item tagged as
    a thought so a question finds it and Synapse can connect it to everything else. This row is
    the thought: nothing done in Synapse ever deletes or changes it.
    """

    id = models.BigAutoField(primary_key=True)
    org_id = models.TextField()
    user_id = models.TextField()
    #: The person's words as they said them, with only obvious dictation slips mended.
    words = models.TextField()
    #: A short title, a few words.
    title = models.TextField(blank=True, default="")
    #: When they said it, epoch seconds.
    said_at = models.FloatField()
    #: How it came: voice, typed, telegram or voice_note (`thoughts.SOURCES`).
    source = models.TextField(default="typed")
    #: The topics Rouh read in it, or the person gave it.
    tags = models.JSONField(default=list)
    #: open, developed or archived (`thoughts.STATUSES`).
    status = models.TextField(default="open")
    #: The earlier thought this one follows up, so a line of thinking can grow over time.
    follows = models.BigIntegerField(null=True, blank=True)
    #: The chat it was said in, when it was said in one.
    chat_id = models.TextField(blank=True, default="")
    #: Its copy in the person's Synapse Master, and when that copy was last made level with it.
    synapse_item = models.TextField(blank=True, default="")
    synapse_at = models.FloatField(null=True, blank=True)
    made_at = models.FloatField()
    updated_at = models.FloatField()
    archived_at = models.FloatField(null=True, blank=True)
    #: Its enriched version (`rouh/thought_enrich.py`): "" for a thought kept before there was
    #: one, then starting, running, done or failed. The words above are never touched by it.
    enrich_state = models.TextField(blank=True, default="")
    #: The numbered task Rouh made for it, by its object id, so a move never loses it.
    enrich_task = models.TextField(blank=True, default="")
    #: The background run doing the research.
    enrich_run = models.TextField(blank=True, default="")
    #: The enriched page, as a path inside the task's folder: `110-01.its-name/index.html`.
    enrich_page = models.TextField(blank=True, default="")
    #: Why it failed, in words to show.
    enrich_why = models.TextField(blank=True, default="")
    enrich_at = models.FloatField(null=True, blank=True)
    enrich_done_at = models.FloatField(null=True, blank=True)

    class Meta:
        db_table = "thoughts"
        indexes = [models.Index(fields=["org_id", "user_id", "said_at"], name="thoughts_whose"),
                   models.Index(fields=["org_id", "user_id", "status"], name="thoughts_state"),
                   models.Index(fields=["enrich_run"], name="thoughts_enrich_run")]


class Box(models.Model):
    """Something the person put in a box, which the model never sees (`rouh/boxes.py`).

    Petar, 13 October 2026 (fr_e7f2ebe1c141): "When I am doing stuff I want to be able to say
    give me a box and save something there so LLM doesn't see it." A password on its way to an
    env file, or an idea held back so it cannot sway an answer. What is in it is sealed with
    the instance's key (`rouh/encryption.py`) before it reaches this row, and only the person's
    own page ever opens it.
    """

    id = models.BigAutoField(primary_key=True)
    org_id = models.TextField()
    user_id = models.TextField()
    #: Its number among this person's boxes, 1 for their first: what they say to Rouh to open it.
    number = models.IntegerField(default=0)
    #: The name the person gave it, or empty. Never shown to the model either.
    label = models.TextField(blank=True, default="")
    #: secret or idea (`boxes.KINDS`).
    kind = models.TextField(default="secret")
    #: What is in it, sealed (`encryption.SecretBox.seal`). Never plain text.
    sealed = models.TextField()
    #: How many characters it holds, so the page can say so without opening it.
    size = models.IntegerField(default=0)
    made_at = models.FloatField()
    updated_at = models.FloatField()
    #: When the person last had Rouh open it, and the chat it was opened in: from then on what
    #: is in it is part of that conversation.
    given_at = models.FloatField(null=True, blank=True)
    given_chat = models.TextField(blank=True, default="")

    class Meta:
        db_table = "boxes"
        indexes = [models.Index(fields=["org_id", "user_id", "made_at"], name="boxes_whose")]
        constraints = [models.UniqueConstraint(fields=["org_id", "user_id", "number"], name="boxes_number")]


class BoxHandover(models.Model):
    """One box handed to a job as a file, never its contents (`rouh/boxes.py`, "Handing a box to a job").

    Petar, 2 November 2026: "things don't need to go in chat, you can simply use that info and pass it
    around in files as you do work". A job started with ``boxes`` gets each box the person named as a file
    in its own folder, written by Rouh's code and the one program's, and shredded when the job ends. This
    row is the record of it: which box, which job, when it was asked for, when the file was written and
    when it was shredded. What was in the box is never here.
    """

    id = models.BigAutoField(primary_key=True)
    org_id = models.TextField()
    user_id = models.TextField()
    #: The box (`Box.id`), its number and its name as they were when it was handed over.
    box_id = models.BigIntegerField()
    number = models.IntegerField(default=0)
    label = models.TextField(blank=True, default="")
    #: The sha256 of the one-time key the program shows to collect the files; never the key itself.
    grant = models.TextField(db_index=True)
    #: The job it went to, once it has an id, and the tool that started it.
    run_id = models.TextField(blank=True, default="", db_index=True)
    via = models.TextField(blank=True, default="")
    chat = models.TextField(blank=True, default="")
    #: Asked for; written into the job's folder; shredded (or never collected, and so dropped).
    made_at = models.FloatField()
    handed_at = models.FloatField(null=True, blank=True)
    ended_at = models.FloatField(null=True, blank=True)
    #: How it ended: "shredded", "expired" or "not started".
    ended = models.TextField(blank=True, default="")

    class Meta:
        db_table = "box_handovers"
        indexes = [models.Index(fields=["org_id", "user_id", "box_id", "made_at"], name="box_handovers_whose")]
