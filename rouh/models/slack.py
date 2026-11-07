"""Slack: the workspace Rouh's own Slack app is installed in, and what it reads there (`rouh/slack.py`).

Petar, 16 October 2026: "I need you to evesdrop on my slack. Full integration. You should be able to
talk to people and be added to channels. Ideally we also want personal messages directly to me to be
readable by you." So an organisation keeps one Slack app, created from Rouh's manifest and installed
in its workspace, with three tokens sealed here; and every message the app can see is kept, by
conversation, with who wrote it.

The app is the organisation's, and so are its bot token and app-level token. The user token is the
one person's who installed it, and reads only that person's own direct messages: every row names
the organisation, and every row that holds somebody's messages names the person whose they are
(`AGENTS.md`, "Whose data is it").
"""
from django.db import models


class SlackConnection(models.Model):
    """One organisation's Slack app: its workspace, its three tokens, sealed, and how listening goes.

    The tokens are typed into Settings, Connections, Slack, checked with Slack and sealed with
    `encryption.SecretBox`; only their last four characters are ever shown or said.
    """

    id = models.BigAutoField(primary_key=True)
    org_id = models.TextField()
    #: The person who connected it: whose user token it is, whose messages to Rouh are theirs, and
    #: under whose account a message to Rouh becomes a case or a turn.
    user_id = models.TextField(blank=True, default="")
    #: The workspace, as Slack's `auth.test` names it.
    team_id = models.TextField(blank=True, default="")
    team_name = models.TextField(blank=True, default="")
    team_url = models.TextField(blank=True, default="")
    #: The bot user, Rouh, in that workspace.
    bot_user_id = models.TextField(blank=True, default="")
    bot_name = models.TextField(blank=True, default="")
    #: The person's own Slack account, from the user token.
    slack_user_id = models.TextField(blank=True, default="")
    slack_user_name = models.TextField(blank=True, default="")
    bot_sealed = models.TextField(blank=True, default="")
    bot_last4 = models.TextField(blank=True, default="")
    user_sealed = models.TextField(blank=True, default="")
    user_last4 = models.TextField(blank=True, default="")
    app_sealed = models.TextField(blank=True, default="")
    app_last4 = models.TextField(blank=True, default="")
    saved_at = models.FloatField(default=0)
    checked_at = models.FloatField(default=0)
    #: What listening is doing: "", "connecting", "listening", "waiting" (to try again), "off".
    listening = models.TextField(blank=True, default="")
    #: Why, in a sentence, when it is not listening.
    listening_said = models.TextField(blank=True, default="")
    #: When the socket last opened, and when Slack last sent anything over it.
    connected_at = models.FloatField(default=0)
    heard_at = models.FloatField(default=0)
    #: The first look back over the last `slack.BACKFILL_DAYS` (90) days: {started_at, finished_at,
    #: days (how far back it read), conversations, messages, said}.
    backfill = models.JSONField(default=dict, blank=True)
    made_at = models.FloatField(default=0)
    updated_at = models.FloatField(default=0)

    class Meta:
        db_table = "slack_connections"
        constraints = [models.UniqueConstraint(fields=["org_id"], name="slack_connections_one")]


class SlackConversation(models.Model):
    """A channel, private channel, direct message or group direct message the app can see."""

    id = models.BigAutoField(primary_key=True)
    org_id = models.TextField()
    #: The person whose connection it is seen through.
    user_id = models.TextField()
    team_id = models.TextField()
    channel_id = models.TextField()
    #: "channel", "group" (a private channel), "im" or "mpim".
    kind = models.TextField(default="channel")
    #: The channel's name, or for a direct message the other person's.
    name = models.TextField(blank=True, default="")
    #: Rouh's bot is a member: it is read, and Rouh may post there.
    is_member = models.BooleanField(default=False)
    #: Read with the person's own user token: one of their own direct messages, theirs only.
    private = models.BooleanField(default=False)
    is_archived = models.BooleanField(default=False)
    topic = models.TextField(blank=True, default="")
    #: For a direct message, the other person's Slack id.
    other_id = models.TextField(blank=True, default="")
    #: When the last 90 days of it were read back, or 0.
    backfilled_at = models.FloatField(default=0)
    updated_at = models.FloatField(default=0)

    class Meta:
        db_table = "slack_conversations"
        constraints = [models.UniqueConstraint(fields=["org_id", "team_id", "channel_id"],
                                               name="slack_conversations_one")]


class SlackPerson(models.Model):
    """Somebody in the workspace, as Slack's `users.info` says, and the contact they are, by email."""

    id = models.BigAutoField(primary_key=True)
    org_id = models.TextField()
    team_id = models.TextField()
    slack_id = models.TextField()
    name = models.TextField(blank=True, default="")
    real_name = models.TextField(blank=True, default="")
    #: The address on their Slack profile, which Slack confirmed when they joined.
    email = models.TextField(blank=True, default="")
    is_bot = models.BooleanField(default=False)
    deleted = models.BooleanField(default=False)
    #: The contact in Synapse Master this address belongs to, by its id and name, or "".
    contact_id = models.TextField(blank=True, default="")
    contact_name = models.TextField(blank=True, default="")
    updated_at = models.FloatField(default=0)

    class Meta:
        db_table = "slack_people"
        constraints = [models.UniqueConstraint(fields=["org_id", "team_id", "slack_id"],
                                               name="slack_people_one")]


class SlackMessage(models.Model):
    """One message, kept as Slack has it now: an edit changes it, a deletion removes it."""

    id = models.BigAutoField(primary_key=True)
    org_id = models.TextField()
    #: The person whose connection read it.
    user_id = models.TextField()
    team_id = models.TextField()
    channel_id = models.TextField()
    #: Slack's own id for the message, its timestamp: "1760600000.000100".
    ts = models.TextField()
    #: The thread it is in (the first message's ts), or "".
    thread_ts = models.TextField(blank=True, default="")
    #: How many replies it has, when it starts a thread.
    reply_count = models.IntegerField(default=0)
    author_id = models.TextField(blank=True, default="")
    author_name = models.TextField(blank=True, default="")
    contact_id = models.TextField(blank=True, default="")
    contact_name = models.TextField(blank=True, default="")
    text = models.TextField(blank=True, default="")
    #: The names of the files it carried, never their contents.
    files = models.JSONField(default=list, blank=True)
    subtype = models.TextField(blank=True, default="")
    #: When it was said, as seconds (its ts as a number), and when it was last edited.
    at = models.FloatField(default=0)
    edited_at = models.FloatField(default=0)
    #: Read with the person's own user token: one of their own direct messages, theirs only.
    private = models.BooleanField(default=False)
    #: Rouh's own bot wrote it.
    by_rouh = models.BooleanField(default=False)
    #: A message to Rouh, handed over as a case or a turn: the case's or the chat's id.
    handed = models.TextField(blank=True, default="")
    #: When it was read for promises (`rouh/slack_promises.py`), or 0 while it waits to be.
    promises_read = models.FloatField(default=0)
    made_at = models.FloatField(default=0)
    updated_at = models.FloatField(default=0)

    class Meta:
        db_table = "slack_messages"
        constraints = [models.UniqueConstraint(fields=["org_id", "team_id", "channel_id", "ts"],
                                               name="slack_messages_one")]
        indexes = [models.Index(fields=["org_id", "channel_id", "at"], name="slack_messages_when"),
                   models.Index(fields=["org_id", "author_id"], name="slack_messages_who"),
                   models.Index(fields=["org_id", "promises_read"], name="slack_messages_promises")]


class SlackPromise(models.Model):
    """A promise made in a Slack message Rouh keeps (`rouh/slack_promises.py`): by the person
    ("I'll send the deck Friday"), or to them by somebody else ("I'll have the numbers to you by
    Monday"). Who promised, to whom, what, by when, and the message it was made in.

    Never a task. Since 17 October 2026 one of the person's own is a Clockwork reminder a day before
    it is due (`clockwork_id`), and one made to them waits unseen until it is late, when it is one
    decision (`decision_sources.PromiseSource`). It closes when it is kept - by the person's answer,
    or by itself when a later message shows it kept.
    """

    id = models.BigAutoField(primary_key=True)
    org_id = models.TextField()
    #: The person whose connection read the message, and whose promise list it is in.
    user_id = models.TextField()
    team_id = models.TextField()
    channel_id = models.TextField()
    #: The message it was made in, and its thread ("" for none).
    ts = models.TextField()
    thread_ts = models.TextField(blank=True, default="")
    #: The same promise read twice is kept once: its message and its words, hashed.
    key = models.TextField()
    #: The person made it; otherwise it was made to them.
    by_petar = models.BooleanField(default=False)
    #: Who promised (the message's author), and to whom, as the model read it.
    by_id = models.TextField(blank=True, default="")
    by_name = models.TextField(blank=True, default="")
    to_name = models.TextField(blank=True, default="")
    #: What was promised, as words after "promised to", written to the person: "send you the deck".
    what = models.TextField()
    #: The message's own words, cut short.
    quote = models.TextField(blank=True, default="")
    #: When it is due, as seconds (the end of the day when no time was said), or 0 for no date;
    #: the day, and how it was said ("by Monday").
    due_at = models.FloatField(default=0)
    due_day = models.TextField(blank=True, default="")
    due_said = models.TextField(blank=True, default="")
    #: For a promise to the person: the short nudge Rouh's bot would post, drafted when it was read.
    nudge = models.TextField(blank=True, default="")
    #: "open", "kept" or "dropped".
    status = models.TextField(default="open")
    #: Who closed it: "itself" (a later message showed it kept) or "person".
    closed_by = models.TextField(blank=True, default="")
    closed_at = models.FloatField(default=0)
    #: The message that showed it kept, its words and its author, and why the model read it so.
    kept_ts = models.TextField(blank=True, default="")
    kept_said = models.TextField(blank=True, default="")
    kept_by = models.TextField(blank=True, default="")
    kept_why = models.TextField(blank=True, default="")
    #: Messages that closed it by itself and were undone: never read as kept again.
    not_kept = models.JSONField(default=list, blank=True)
    #: How many times it was opened again after closing by itself (Undo).
    reopened = models.IntegerField(default=0)
    #: Nudges posted, the last one's time, message and words.
    reminders = models.IntegerField(default=0)
    reminded_at = models.FloatField(default=0)
    reminder_ts = models.TextField(blank=True, default="")
    reminder_text = models.TextField(blank=True, default="")
    #: One of the person's own: the Clockwork reminder made for it (`slack_promises.clockwork`), and
    #: when it was made. Made once, never again, even when the person deletes it on Clockwork.
    clockwork_id = models.BigIntegerField(null=True, blank=True)
    clockwork_at = models.FloatField(default=0)
    #: One made to the person and late: how many times they answered Wait, and until when it waits.
    waits = models.IntegerField(default=0)
    wait_until = models.FloatField(default=0)
    #: The person's own words when they answered it.
    note = models.TextField(blank=True, default="")
    #: Made in one of the person's own direct messages, read with their own token: theirs only.
    private = models.BooleanField(default=False)
    #: Found reading back, not as it was said.
    read_back = models.BooleanField(default=False)
    made_at = models.FloatField(default=0)
    updated_at = models.FloatField(default=0)

    class Meta:
        db_table = "slack_promises"
        constraints = [models.UniqueConstraint(fields=["org_id", "key"], name="slack_promises_one")]
        indexes = [models.Index(fields=["org_id", "user_id", "status"], name="slack_promises_open"),
                   models.Index(fields=["org_id", "channel_id", "status"], name="slack_promises_where")]


class SlackTaskLink(models.Model):
    """A Slack channel linked to a numbered task (`rouh/slack_tasks.py`): while it is linked, a
    decision made in the channel is written into the task's notes as it happens.

    Petar, 16 October 2026, the fifth of five Slack ideas: "link #pricing to 19". One task a
    channel; a task may have several channels. Only a channel or a private channel Rouh's bot is
    in: never a direct message, and never one of the person's own.
    """

    id = models.BigAutoField(primary_key=True)
    org_id = models.TextField()
    #: The person who linked it, whose connection reads the channel.
    user_id = models.TextField()
    team_id = models.TextField()
    channel_id = models.TextField()
    #: The task's object id (`objects.Task`), so a task that moves or is renumbered stays linked.
    task_id = models.TextField()
    #: When it was linked: nothing said before is read for it.
    linked_at = models.FloatField(default=0)
    #: How far the channel has been read: the newest `SlackMessage.made_at` read for decisions.
    read_to = models.FloatField(default=0)
    made_at = models.FloatField(default=0)
    updated_at = models.FloatField(default=0)

    class Meta:
        db_table = "slack_task_links"
        constraints = [models.UniqueConstraint(fields=["org_id", "team_id", "channel_id"],
                                               name="slack_task_links_one")]
        indexes = [models.Index(fields=["org_id", "task_id"], name="slack_task_links_task")]


class SlackTaskDecision(models.Model):
    """A decision made in a linked channel and written into its task's notes: the line written,
    word for word, so it can be found there again and taken out (`slack_tasks.remove`)."""

    id = models.BigAutoField(primary_key=True)
    org_id = models.TextField()
    user_id = models.TextField()
    team_id = models.TextField()
    channel_id = models.TextField()
    task_id = models.TextField()
    #: The message the decision was made in, and its thread ("" for none).
    ts = models.TextField()
    thread_ts = models.TextField(blank=True, default="")
    #: The same decision read twice is written once: its message and its words, hashed.
    key = models.TextField()
    #: Who decided, as the model read it, and the decision in one sentence.
    who = models.TextField(blank=True, default="")
    decision = models.TextField()
    #: The message's own words, kept whole and linked, never rewritten (D1).
    quote = models.TextField(blank=True, default="")
    link = models.TextField(blank=True, default="")
    #: When it was said, as seconds.
    said_at = models.FloatField(default=0)
    #: The line written into the notes, exactly, and the notes it went into.
    line = models.TextField(blank=True, default="")
    notes = models.TextField(blank=True, default="")
    written_at = models.FloatField(default=0)
    #: Taken out of the notes by the person, and when.
    removed_at = models.FloatField(default=0)

    class Meta:
        db_table = "slack_task_decisions"
        constraints = [models.UniqueConstraint(fields=["org_id", "key"], name="slack_task_decisions_one")]
        indexes = [models.Index(fields=["org_id", "task_id"], name="slack_task_decisions_task")]
