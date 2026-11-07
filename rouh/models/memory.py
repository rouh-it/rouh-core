"""What Rouh remembers between one conversation and the next (`rouh/memory.py`).

The transcript every turn is written into, the short standing facts that go
into the system prompt, what each turn cost, and the turn that was in flight
when the process last went away. The tables keep the names they had in
SQLite, so the history of every one of them in `rouh/memory.py` still reads
true.

Nothing here has a foreign key the database enforces, on purpose. SQLite never
enforced the ones these tables declared (`memory.py` did not switch
``foreign_keys`` on), and the code was written against that: a transcript row
outlives the legacy ``sessions`` row it names. Making PostgreSQL stricter than
the store it replaced would turn a quiet row into a failed turn.
"""
from __future__ import annotations

from django.db import models


class LegacySession(models.Model):
    """What a chat was until 21 September 2026. Nothing reads it now.

    Kept, unwritten, as what the move onto `Chat` was made from, and because
    the transcript rows below still carry its ids.
    """

    id = models.TextField(primary_key=True)
    created_at = models.FloatField()
    updated_at = models.FloatField()
    title = models.TextField(null=True, blank=True)
    folder_id = models.TextField(null=True, blank=True)
    task = models.TextField(blank=True, default="")
    unread = models.BooleanField(default=False)

    class Meta:
        db_table = "sessions"


class ChatFolder(models.Model):
    """A chat's folder as it was before step three. Read once, by the migration."""

    id = models.TextField(primary_key=True)
    name = models.TextField()
    created_at = models.FloatField()

    class Meta:
        db_table = "chat_folders"


class AppState(models.Model):
    """Small standing facts about the page: which chat is active, and the like."""

    key = models.TextField(primary_key=True)
    value = models.TextField()

    class Meta:
        db_table = "app_state"


class TranscriptMessage(models.Model):
    """One turn of one chat, as the Anthropic content blocks it was.

    ``root`` is the exchange it belongs to and ``version`` which try of it;
    at most one version of an exchange is ``live`` (`memory.pick_version`), and none when the
    exchange is on a branch of the conversation that is not the one being read (``follows``).
    """

    id = models.BigAutoField(primary_key=True)
    session_id = models.TextField()
    ts = models.FloatField()
    role = models.TextField()
    #: JSON: the Anthropic content blocks, exactly as they were sent.
    content = models.TextField()
    spoken = models.BooleanField(default=False)
    root = models.BigIntegerField(null=True, blank=True)
    version = models.IntegerField(default=1)
    live = models.BooleanField(default=True)
    #: On the first row of a try: the first row of the try of the exchange before it that this
    #: one was asked after, so answering an exchange again branches the conversation there
    #: (`memory.Memory._relive`). Null is the conversation as one line, as it was before.
    follows = models.BigIntegerField(null=True, blank=True)
    #: The try of its exchange the person last chose. ``live`` is whether it is in the
    #: conversation being read, which also needs the branch it is on to be the one chosen.
    picked = models.BooleanField(default=True)
    #: A `user` row Rouh's own software wrote rather than the person: a
    #: finished job's report, a run's question, a press on a card. The model
    #: reads it as a user turn, because that is the only way to hand it
    #: anything; the page never draws it (`memory.Memory._said`).
    note = models.BooleanField(default=False)
    #: The other way round: an `assistant` row that is a notice's words, kept in
    #: the chat the notice leads to so they can be read again once the notice is
    #: gone (fr_c8fb46a5a132). The page draws it; the model is never sent it.
    notice = models.BooleanField(default=False)

    class Meta:
        db_table = "messages"
        indexes = [
            models.Index(fields=["session_id", "id"], name="messages_session"),
            models.Index(fields=["root"], name="messages_root"),
        ]


class RecallTimeline(models.Model):
    """What Synapse Master's look-ups did for one of the person's messages, as its timeline draws it.

    Petar, 10 October 2026: "I want you to visualize the background calls and the parallel calls, and see in
    2.5 seconds whether they returned results or timed out." One row per message the look-ups ran for, written
    as they go and kept, so a chat read back draws the line under each message as it was
    (`rouh/recalling.py`, `memory.Memory.note_recall`). ``data`` is `recalling.MessageMemory.timeline`.
    """

    message_id = models.BigIntegerField(primary_key=True)
    session_id = models.TextField()
    ts = models.FloatField()
    data = models.JSONField(default=dict)

    class Meta:
        db_table = "recall_timelines"
        indexes = [models.Index(fields=["session_id", "message_id"], name="recall_timelines_chat")]


class RouteTimeline(models.Model):
    """How the model that answered one turn was decided, as the line at the top of the answer draws it.

    Petar, 21 October 2026: the line under each answer, built like the memory line, that says which tier
    answered and which model that is, and on Auto the router's own timeline - when the turn started, when
    the router was asked, when it answered or ran out of time, and what it decided (`rouh/modelrouter.py`,
    app/turnline.js). One row per turn, under the turn's name in the log of requests, given its exchange once
    the question is written (`root`). ``data`` is `modelrouter.timeline`.
    """

    call = models.TextField(primary_key=True)
    session_id = models.TextField()
    root = models.BigIntegerField(null=True, blank=True)
    ts = models.FloatField()
    data = models.JSONField(default=dict)

    class Meta:
        db_table = "route_timelines"
        indexes = [models.Index(fields=["session_id", "root"], name="route_timelines_chat")]


class TurnRecord(models.Model):
    """Everything one turn took, kept for good, so speed can be weighed against quality later (`rouh/turnrecords.py`).

    Petar, 23 October 2026: every timing and result the timeline under each reply shows, saved permanently
    for every chat message. One row per turn, under the turn's name (`turn_id`), which is also its call in
    `route_timelines` and `model_outcomes` and its `turn_id` in `llm_requests`: the requests themselves - their
    tokens, cost and first word - stay there and are linked by that name, never copied. ``trace`` is the turn's
    whole timeline as it ended (`turntrace.Trace.snapshot`), which the reply's timeline is drawn from after a
    reload; ``synapse`` is every look-up of Synapse the turn made, the automatic recall's and its own tools',
    each with its trace in Synapse's Activity. Not deleted with its chat. ``labels`` is for what is learned of
    the answer's quality later: the person's correction, a thumb up or down, a judge's score from a double call.
    """

    turn_id = models.TextField(primary_key=True)
    session_id = models.TextField()
    org_id = models.TextField(blank=True, default="")
    user_id = models.TextField(blank=True, default="")
    #: The person's message it answers, its exchange and which try of it this is.
    message_id = models.BigIntegerField(null=True, blank=True)
    root = models.BigIntegerField(null=True, blank=True)
    version = models.IntegerField(default=1)
    note = models.BooleanField(default=False)
    #: How the words came: typed, voice, telegram, note.
    heard = models.TextField(blank=True, default="")
    #: When the message reached the server and when the turn was over, as epoch seconds.
    started_at = models.FloatField()
    ended_at = models.FloatField(null=True, blank=True)
    #: Milliseconds from the message reaching the server: to the end, to the answer's first token, to its first
    #: written word on the screen, and to its first word spoken.
    total_ms = models.IntegerField(null=True, blank=True)
    first_token_ms = models.IntegerField(null=True, blank=True)
    first_word_ms = models.IntegerField(null=True, blank=True)
    first_spoken_ms = models.IntegerField(null=True, blank=True)
    #: finished, stopped (Stop, or talked over), failed, unfinished (not a whole question yet) or replaced.
    status = models.TextField(default="running")
    error = models.TextField(blank=True, default="")
    #: Which tier and model wrote the answer, and the mode that chose it.
    tier = models.TextField(blank=True, default="")
    model = models.TextField(blank=True, default="")
    mode = models.TextField(blank=True, default="")
    #: The answer's rows in the chat (`messages`), and its words as they were when the turn ended.
    reply_ids = models.JSONField(default=list)
    reply_text = models.TextField(blank=True, default="")
    #: What the whole turn cost, router, recall and every request of the answer and its tools, in dollars,
    #: and by part (`turnrecords.costs`).
    cost_usd = models.DecimalField(max_digits=12, decimal_places=6, null=True, blank=True)
    costs = models.JSONField(default=dict)
    trace = models.JSONField(default=dict)
    synapse = models.JSONField(default=list)
    labels = models.JSONField(default=dict)

    class Meta:
        db_table = "turn_records"
        indexes = [
            models.Index(fields=["session_id", "root"], name="turn_records_chat"),
            models.Index(fields=["user_id", "org_id", "-started_at"], name="turn_records_mine"),
            models.Index(fields=["message_id"], name="turn_records_message"),
        ]


class ToolLine(models.Model):
    """One line a tool call drew in the chat, as the page last drew it.

    Petar, 30 September 2026 (fr_3f1814427840): "I would like in chat when I
    see the tool usage to also be saved in chat history. Currently after
    refresh we no longer see old tool usage." Until then a line lived only on
    the screen that watched the turn, made from `tool_start`, `tool_update`
    and `tool_end` as they went past (`runtime.Turn.emit`). This row is those
    three messages kept: exactly what the line was drawn from, no more, so a
    chat read back draws each line as it looked live (`memory.Memory.transcript`).

    ``call_id`` is the call's own id, which is also the id of its block in the
    answer's row, and that is how a line is put back among the words it was
    written between. ``after_message_id`` is the newest row of the chat when
    the call started, for the lines no block names: a helper's calls, which
    run inside one of Rouh's own calls.
    """

    id = models.BigAutoField(primary_key=True)
    session_id = models.TextField()
    call_id = models.TextField()
    after_message_id = models.BigIntegerField(null=True, blank=True)
    ts = models.FloatField()
    name = models.TextField(blank=True, default="")
    #: What the call was sent, as the text `tool_start` or `tool_update` carried.
    input = models.TextField(blank=True, default="")
    done = models.BooleanField(default=False)
    ok = models.BooleanField(default=True)
    summary = models.TextField(blank=True, default="")
    #: The pages a web call found or read, as `tool_end` listed them.
    results = models.JSONField(blank=True, default=list)
    #: What a command printed, as its line showed it; null for any other call.
    output = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "tool_lines"
        indexes = [
            models.Index(fields=["session_id", "call_id"], name="tool_lines_call"),
            models.Index(fields=["session_id", "after_message_id"], name="tool_lines_after"),
        ]


class Fact(models.Model):
    """A short standing statement the assistant chose to keep.

    ``project_id`` is the project it belongs to, and "" is the general memory
    everything used to go into. Petar, 24 September 2026, after Rouh said
    "Kept" and the note was nowhere in the project he was working in: "I know
    there is a universal db memory, but that should be either different than
    projects memory or the setup should be such that a column in the database
    says for which project that is." This is that column.

    It is a plain text column and not a foreign key, like everything else in
    this module: a note whose project is deleted is given back to the general
    memory by the deletion itself (`rouh/keeping.py`), and a note pointing at
    a project that is not there reads as a general one rather than as a failed
    turn.

    The key was this table's primary key until then, which made a note's label
    unique across the whole install: keeping "deposit" in one project would
    have quietly overwritten "deposit" in another. A row of its own now, with
    the label unique **within** a project, which is the only place a person
    ever compares two of them.
    """

    id = models.BigAutoField(primary_key=True)
    key = models.TextField()
    project_id = models.TextField(blank=True, default="")
    value = models.TextField()
    created_at = models.FloatField()
    updated_at = models.FloatField()
    hits = models.IntegerField(default=0)
    #: Where this fact is proposed to go now that the memory is rules, words and notes in Synapse Master
    #: (`rouh/rules.py`, 5 October 2026): {"home": "rule" | "vocabulary" | "note" | "drop", "text", "for", "term",
    #: "meaning", "why"} ("word", until 30 October 2026, is Vocabulary). The person applies or changes it on the
    #: Rules page, and the fact then goes.
    proposal = models.JSONField(null=True, blank=True, default=None)

    class Meta:
        db_table = "facts"
        indexes = [models.Index(fields=["project_id"], name="facts_project")]
        constraints = [
            models.UniqueConstraint(fields=["project_id", "key"],
                                    name="fact_one_key_per_project"),
        ]


class ScreenCard(models.Model):
    """The screen as it was kept before the object model. Read once, migrated."""

    id = models.BigAutoField(primary_key=True)
    ts = models.FloatField()
    session_id = models.TextField(null=True, blank=True)
    title = models.TextField()
    description = models.TextField(blank=True, default="")
    #: JSON: exactly what was drawn.
    spec = models.TextField()
    after_message_id = models.BigIntegerField(null=True, blank=True)

    class Meta:
        db_table = "screen_cards"
        indexes = [models.Index(fields=["-ts"], name="screen_cards_ts")]


class Event(models.Model):
    """Something worth a line in the record that is not a turn."""

    id = models.BigAutoField(primary_key=True)
    ts = models.FloatField()
    kind = models.TextField()
    detail = models.TextField()

    class Meta:
        db_table = "events"


class Spend(models.Model):
    """What one turn cost, in tokens and in money (`rouh/costs.py`)."""

    id = models.BigAutoField(primary_key=True)
    ts = models.FloatField()
    session_id = models.TextField()
    model = models.TextField(blank=True, default="")
    input_tokens = models.BigIntegerField(default=0)
    output_tokens = models.BigIntegerField(default=0)
    cache_read = models.BigIntegerField(default=0)
    cache_write = models.BigIntegerField(default=0)
    cost = models.FloatField(null=True, blank=True)
    #: Each request of the turn, in order, each with the same four numbers as
    #: the columns above, which are their sums. How the cache did shows here
    #: and not in the sums: the first request of a turn writes it, the rest
    #: should read it back.
    calls = models.JSONField(blank=True, default=list)
    #: From the turn's first request going out to the first thing streaming
    #: back, thinking included, in milliseconds. Null where nothing came.
    first_token_ms = models.IntegerField(null=True, blank=True)
    #: From the start of the turn to its first words on the screen.
    first_text_ms = models.IntegerField(null=True, blank=True)
    #: From the start of the turn to its first sentence handed to the voice.
    first_word_ms = models.IntegerField(null=True, blank=True)
    #: How the turn's tools were declared (`rouh/toolsearch.py`): regex, bm25,
    #: client, or off for every tool sent whole. Blank on turns from before.
    tool_search = models.TextField(blank=True, default="")
    #: The tools a search loaded in this turn, comma-separated.
    tools_loaded = models.TextField(blank=True, default="")

    class Meta:
        db_table = "spend"
        indexes = [
            models.Index(fields=["-ts"], name="spend_ts"),
            models.Index(fields=["session_id", "id"], name="spend_session"),
        ]


class OpenTurn(models.Model):
    """A turn that has started and not finished: one row per chat.

    A row left here after a restart is a turn the restart cut short, and
    `memory.mark_interrupted` turns it into a sentence in the transcript.
    """

    session_id = models.TextField(primary_key=True)
    started_at = models.FloatField()
    said = models.TextField(blank=True, default="")
    #: `said` is a note of Rouh's own and not the person's words
    #: (`TranscriptMessage.note`), so it goes back in as one.
    note = models.BooleanField(default=False)

    class Meta:
        db_table = "open_turns"
