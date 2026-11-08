"""The five objects: project, task, chat, run, artifact (`rouh/objects.py`).

Two children - a chat's messages and an artifact's versions - and one link
table that says who owns what and what refers to what. The vocabulary each
column may hold is here, beside the column, and `rouh/objects.py` takes it
from here, so the CHECK constraint in the database and the check in the code
are one rule written once.

Unlike the transcript's tables, these always had their foreign keys enforced
(`objects.py` switched ``foreign_keys`` on), with the database doing the
cascade: deleting a chat takes its messages with it, and a run that goes leaves
the versions it made pointing at nothing rather than going with it. The same is
true here: the constraints are made by the migration with ``ON DELETE`` on
them, so a raw DELETE and an ORM one behave the same, and the fields below say
``DO_NOTHING`` because the database has already done it.
"""
from __future__ import annotations

from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVector, SearchVectorField
from django.db import models
from django.db.models import F, Func, Q, Value

#: The ranking an ownership has to point down. A project may own a task, a task
#: a chat, and so on; the two that nest may also own one of their own kind.
RANK: dict[str, int] = {
    "project": 0,
    "task": 1,
    "chat": 2,
    "run": 3,
    "artifact": 4,
}

#: The two types that nest inside themselves, and are folders in the workspace.
NESTS: tuple[str, ...] = ("project", "task")

#: What may appear as `src_type` or `dst_type` in a link.
KINDS: tuple[str, ...] = tuple(RANK)

#: The one relationship that is ownership, and the three that are references.
OWNS = "owns"
RELS: tuple[str, ...] = (OWNS, "made", "from", "about")

TASK_STATES: tuple[str, ...] = ("open", "waiting", "done")

#: How far along a task is, in the five words the workspace has always used.
#: `task.status` holds one of them and `task.state` is the three-way summary of
#: it the rest of Rouh asks about, kept in step by the store and by a CHECK
#: (`rouh/taskrecord.py`).
TASK_STATUSES: tuple[str, ...] = ("not-started", "in-progress", "waiting", "stopped", "done")
#: What each of the five comes to in three.
STATUS_STATE: dict[str, str] = {"not-started": "open", "in-progress": "open", "stopped": "open",
                                "waiting": "waiting", "done": "done"}
#: And the word a state is given when only the state is said: a task opened
#: again from waiting or done is being worked on, and one made open has not
#: been started.
STATE_STATUS: dict[str, str] = {"open": "in-progress", "waiting": "waiting", "done": "done"}
CHAT_STATES: tuple[str, ...] = ("live", "idle", "archived")
RUN_STATES: tuple[str, ...] = ("running", "waiting", "done", "failed", "conflict")
AGENTS: tuple[str, ...] = ("claude", "codex")
#: Under what rules a run works. The first six are the words `crew.py` offers
#: for a delegated job; the seventh is the one program's.
POLICIES: tuple[str, ...] = ("yolo", "auto", "safe", "self", "local-only",
                             "direct-pr", "one")
#: Which of the two halves of Metabolism, the page of runs, a run is on (Petar, 14
#: October 2026): a mutation changes Rouh itself, everyday work is everything else.
#: Empty is a run nothing has been able to say yet, which is drawn as everyday work
#: (`runs.kind_of`).
RUN_KINDS: tuple[str, ...] = ("", "mutation", "everyday")
ARTIFACT_KINDS: tuple[str, ...] = ("card", "page", "doc", "diff", "file", "image")

#: What separates two words in the content index: any run of characters that
#: are not letters or digits. A POSIX class, so PostgreSQL's regular
#: expressions and the query side in `rouh/objects.py` agree on it.
WORD_BREAKS = "[^[:alnum:]]+"


def _rank_sql(column: str) -> str:
    whens = " ".join(f"WHEN '{kind}' THEN {rank}" for kind, rank in RANK.items())
    return f"CASE {column} {whens} ELSE 99 END"


def _in_sql(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def owns_check_sql() -> str:
    """The whole of what an `owns` edge may be, as SQL, for the migration.

    Down the ranking, or one of the two types that nest inside itself and then
    never onto itself. The same expression the SQLite table was made with.
    """
    return (f"rel <> '{OWNS}' OR ({_rank_sql('src_type')} < {_rank_sql('dst_type')}"
            f" OR (src_type = dst_type AND src_type IN ({_in_sql(NESTS)})"
            " AND src_id <> dst_id))")


class Project(models.Model):
    id = models.TextField(primary_key=True)
    number = models.IntegerField(null=True, blank=True)
    slug = models.TextField(blank=True, default="")
    title = models.TextField()
    description = models.TextField(blank=True, default="")
    #: The colour the person picked for it: one of the task browser's own
    #: names (`objectindex.PALETTE`) or `#rrggbb`. Empty is no pick, and the
    #: project takes the colour at its place in its column.
    color = models.TextField(blank=True, default="")
    status = models.TextField(default="open")
    folder = models.TextField(blank=True, default="")
    pinned = models.BooleanField(default=False)
    created_at = models.FloatField()
    updated_at = models.FloatField(null=True, blank=True)

    class Meta:
        db_table = "project"
        constraints = [
            models.CheckConstraint(condition=Q(status__in=TASK_STATES),
                                   name="project_status_known"),
        ]


class Task(models.Model):
    id = models.TextField(primary_key=True)
    number = models.IntegerField(null=True, blank=True, unique=True)
    slug = models.TextField(blank=True, default="")
    title = models.TextField()
    state = models.TextField(default="open")
    folder = models.TextField(blank=True, default="")
    pinned = models.BooleanField(default=False)
    created_at = models.FloatField()
    updated_at = models.FloatField(null=True, blank=True)
    closed_at = models.FloatField(null=True, blank=True)
    seen_at = models.FloatField(default=0)
    #: When it was archived, or None while it is live. A subtask archived with
    #: the task above it carries the same moment, which is how unarchiving that
    #: task brings back exactly what went with it (`archiving.py`).
    archived_at = models.FloatField(null=True, blank=True)
    #: What it is, where it stands and what is open, in 50 to 90 words. Kept
    #: here and nowhere else since 6 October 2026: changed through
    #: `rouh/taskrecord.py` (`workspace/bin/task summary`), every change in
    #: `task_change`, and `_tasks.md` generated out of it (`rouh/tasklist.py`).
    summary = models.TextField(blank=True, default="")
    #: How far along it is, in the workspace's five words (`TASK_STATUSES`).
    #: The one place it is kept, like the summary; `state` is what it comes to
    #: in three words, and the CHECK below holds the two together.
    status = models.TextField(default="not-started")
    #: Who made it (`rouh/task_origin.py`), its `made` one of three: "person" ({} too, for
    #: nobody said, which is the person's own); "other", {"for": name, "email", "telegram",
    #: "channel", "by", "why", "at"}, made on somebody else's behalf by a mail case, a
    #: Telegram message or a contact's turn; "process:<name>", {"process", "by", "why",
    #: "at"}, made by one of Rouh's processes on its own. "by": "owner" ("petar" on older rows) is
    #: the owner's own word, which nothing marks again. Kept beside the status, and every change is in
    #: `task_change`.
    origin = models.JSONField(default=dict, blank=True, db_default={})
    #: Its meta (Petar, 22 October 2026: "should be in DB"): its steps' titles,
    #: descriptions and groups, the groups and the arrows between steps, its tags, a goal's
    #: and a goal step's blocks, a waiting task's `question` (and `question_cleared`), the
    #: replies the owner sends himself (`sends_himself`). Kept here and nowhere else
    #: (`rouh/taskmeta.py`), every change in `task_change`. None is a task that never had
    #: one, which is not the same as one with nothing in it: a step is only noted in a task
    #: that keeps a list of its steps (`steps.note_step`).
    meta = models.JSONField(null=True, blank=True, default=None)
    #: The picture in front of its title, as a Notion page has one (`rouh/taskicons.py`): one
    #: emoji, or the name of a small picture uploaded for it, kept in Rouh's data folder under
    #: `task-icons/`. Empty is one not picked yet, which the icon picker fills within moments of
    #: the task being made. Every change is in `task_change`.
    icon = models.TextField(blank=True, default="", db_default="")
    #: The numbers it was called by before a move gave it the one it has now, oldest first:
    #: `["98-02", "103-01"]` for a subtask moved twice (`rouh/moving.py`). Petar, 22 October
    #: 2026 (fr_676c7ad596fd): "when I search for 92-08, if that's what I remember, it would
    #: still appear, but it would be with the new name, 103-01." A number typed into search is
    #: looked for here when no task is called it now (`ObjectStore.task_called`).
    numbers_before = models.JSONField(null=True, blank=True, default=list)

    class Meta:
        db_table = "task"
        indexes = [models.Index(fields=["state", "-created_at"], name="task_state")]
        constraints = [
            models.CheckConstraint(condition=Q(state__in=TASK_STATES),
                                   name="task_state_known"),
            models.CheckConstraint(condition=Q(status__in=TASK_STATUSES),
                                   name="task_status_known"),
            models.CheckConstraint(
                condition=(Q(status="done", state="done") | Q(status="waiting", state="waiting")
                           | Q(status__in=("not-started", "in-progress", "stopped"),
                               state="open")),
                name="task_status_is_its_state"),
        ]


class TaskChange(models.Model):
    """One change to a task's status, its summary, who it was made for or its meta
    (`rouh/taskmeta.py`): when, by whom, from what, to what.

    The history git used to give when both were lines in a file in the task's
    folder, kept here since 6 October 2026, when the database became the
    only place they are (`rouh/taskrecord.py`). Written by the store on every
    change, whoever made it: a job through `workspace/bin/task`, Rouh's own
    code, the laptop with a token.

    `pending` is a change sent for a task Rouh has no row for yet, which is a
    task a job made in its own checkout and has not landed: it is kept against
    the id that task's `.object.json` gives, and made the moment a row with
    that id is taken in (`taskrecord.apply_pending`).
    """

    id = models.BigAutoField(primary_key=True)
    #: The task's id; no foreign key, because a pending change has no row yet.
    task_id = models.TextField()
    field = models.TextField()
    old = models.TextField(blank=True, default="")
    new = models.TextField(blank=True, default="")
    at = models.FloatField()
    #: Who made it, in words: "run 3f8d9ce5", "job crew-ab12", "the owner on the laptop".
    by = models.TextField(blank=True, default="")
    #: The run or job it came from, when it came from one.
    run = models.TextField(blank=True, default="")
    pending = models.BooleanField(default=False)

    class Meta:
        db_table = "task_change"
        indexes = [models.Index(fields=["task_id", "at"], name="task_change_task")]
        constraints = [
            models.CheckConstraint(condition=Q(field__in=("status", "summary", "origin", "meta",
                                                     "icon")),
                                   name="task_change_field_known"),
        ]


class TaskToken(models.Model):
    """A key that lets one person change a task's status or summary from elsewhere.

    For `rouh-task` run on another computer, in a copy of the workspace there, which
    reaches Rouh over https. Nothing on the server needs one. It opens
    `/api/task` and nothing else. Only its sha256 is kept; the key itself is
    shown once, when `manage.py task_token add` makes it.
    """

    id = models.BigAutoField(primary_key=True)
    user_id = models.TextField()
    org_id = models.TextField()
    name = models.TextField()
    token_hash = models.TextField(unique=True)
    created_at = models.FloatField()
    last_used_at = models.FloatField(null=True, blank=True)
    revoked_at = models.FloatField(null=True, blank=True)

    class Meta:
        db_table = "task_token"


class Chat(models.Model):
    id = models.TextField(primary_key=True)
    title = models.TextField(null=True, blank=True)
    state = models.TextField(default="live")
    pinned = models.BooleanField(default=False)
    unread = models.BooleanField(default=False)
    last_spoke = models.FloatField()
    last_activity = models.FloatField(default=0)
    created_at = models.FloatField()
    #: Cheap, Smart or Auto, set beside the composer, or "" for the Models page's default
    #: (`chatkinds.choice_of`, `0245_chat_model_choice`).
    model_choice = models.TextField(blank=True, default="", db_default="")

    class Meta:
        db_table = "chat"
        indexes = [
            models.Index(fields=["last_spoke"], name="chat_quiet"),
            models.Index(fields=["-last_activity"], name="chat_recent"),
        ]
        constraints = [
            models.CheckConstraint(condition=Q(state__in=CHAT_STATES),
                                   name="chat_state_known"),
        ]


class ChatFork(models.Model):
    """A chat that hangs off a point in another chat (`rouh/forks.py`).

    The fork is a chat like any other, with its own messages and its own
    turns; this row is the whole of what makes it a fork. `parent` is the chat
    it came off and `at` the id of that chat's last message when it did, which
    is both how much of the parent the model is shown before the fork's own
    words and where the parent's conversation marks it. `open` said whether it
    was laid out beside its parent until 22 October 2026, when which forks
    are laid out became each tab's own (`forks.strip`); it is no longer read
    or written, and is kept only so a deploy can still be rolled back.

    Both ends are the database's to clear (`0014_chat_fork`): a fork that is
    deleted takes its row, and a parent deleted by anything other than Rouh's
    own delete - which takes its forks with it - leaves them as ordinary chats
    rather than as rows hanging off nothing.

    `cut_at` is when a fork stopped being one to look at, because it became a
    task's own chat (`forks.cut`): from then on it is laid out on its own and
    says nothing of the chat it came off, and the row is kept only for what
    the model still reads above its first words and for the mark in the
    parent, which now opens the task.
    """

    chat = models.OneToOneField(Chat, on_delete=models.DO_NOTHING, db_constraint=False,
                                primary_key=True, db_column="chat_id", related_name="+")
    parent = models.ForeignKey(Chat, on_delete=models.DO_NOTHING, db_constraint=False,
                               db_column="parent_id", related_name="+")
    at = models.BigIntegerField(null=True, blank=True)
    open = models.BooleanField(default=True)
    created_at = models.FloatField()
    cut_at = models.FloatField(null=True, blank=True)

    class Meta:
        db_table = "chat_fork"
        indexes = [models.Index(fields=["parent"], name="chat_fork_parent")]


class TelegramReply(models.Model):
    """A message Rouh sent to Petar's phone in answer, and the point it answers.

    The answer to something he wrote on Telegram finished one exchange of one
    chat, and this row says which (`rouh/telegram_forks.py`): Fork under it,
    or /fork written as a reply to it, comes off that chat just below that
    exchange, however much has been said there since. An answer long enough to
    go in parts is a row for each part. `tg_chat` is the Telegram chat it went
    to, because Telegram numbers messages per chat. A chat deleted takes its
    rows with it (`0032_telegram_forks`).
    """

    id = models.BigAutoField(primary_key=True)
    tg_chat = models.TextField()
    message_id = models.BigIntegerField()
    chat = models.ForeignKey(Chat, on_delete=models.DO_NOTHING, db_constraint=False,
                             db_column="chat_id", related_name="+")
    root = models.BigIntegerField()
    created_at = models.FloatField()

    class Meta:
        db_table = "telegram_reply"
        constraints = [models.UniqueConstraint(fields=["tg_chat", "message_id"],
                                               name="telegram_reply_one")]
        indexes = [models.Index(fields=["chat"], name="telegram_reply_chat")]


class TelegramFork(models.Model):
    """A fork made from Petar's phone.

    The fork itself is a `ChatFork` like any made on the screen; this row only
    says it was made on Telegram (`rouh/telegram_forks.py`). `used_at` was the
    order /chats listed them in, the day the private chat could move into a
    fork; nothing reads it now. Deleting the chat takes the row with it
    (`0032_telegram_forks`).

    `tg_chat` is the group of its own the fork was given, made as Petar
    (`rouh/telegram_account.py`): what is written there is written in this
    fork. Empty for a fork with no group, which is on the screen only. `thread_id` was a
    topic of one shared group, the first way of giving a fork a chat of its
    own (`0034`), replaced the same day by a group each; a fork with one is
    no longer read from there.
    """

    chat = models.OneToOneField(Chat, on_delete=models.DO_NOTHING, db_constraint=False,
                                primary_key=True, db_column="chat_id", related_name="+")
    created_at = models.FloatField()
    used_at = models.FloatField()
    tg_chat = models.TextField(blank=True, default="", db_default="")
    thread_id = models.BigIntegerField(null=True, blank=True)

    class Meta:
        db_table = "telegram_fork"
        indexes = [models.Index(fields=["tg_chat", "thread_id"], name="telegram_fork_topic")]


class TaskAnswer(models.Model):
    """The person's answer to what a task was waiting on them for.

    Written the moment it is sent from the box at the top of the task's page
    (`rouh/answering.py`), so that box can say it was answered, and what is
    carrying it on, for as long as the task still says Waiting: the job that
    takes the answer in changes the task itself, and that lands minutes later.
    `asked` is the question as the box showed it, which is how an answer to
    an earlier question is told from one to the question asked now; `chat_id`
    is the chat the answer was sent in, and so the one the job was started
    from. Deleting the task takes its answers with it (`0016_task_answer`).

    `dismissed` is the box closed rather than answered (`0017`): nothing was
    sent and there is no chat, `answer` is empty, and the question stops
    being counted as waiting on the person until they answer it after all.
    """

    id = models.BigAutoField(primary_key=True)
    task = models.ForeignKey(Task, on_delete=models.DO_NOTHING, db_constraint=False,
                             db_column="task_id", related_name="+")
    asked = models.TextField()
    answer = models.TextField()
    chat_id = models.TextField(blank=True, default="")
    dismissed = models.BooleanField(default=False)
    created_at = models.FloatField()

    class Meta:
        db_table = "task_answer"
        indexes = [models.Index(fields=["task", "created_at"], name="task_answer_task")]


class SubtaskNote(models.Model):
    """A decision or a note sent up from a subtask's chat to its parent task.

    A subtask's chat is the subtask's own and stays local to it (Petar, 29
    September 2026, fr_3113364c29fa: "make the new chat belong to the subtask
    ... provide a clear link or action to bring important decisions back to
    the parent"). What is worth the parent knowing is sent up from it with
    Send to the task (`rouh/subtasknotes.py`), and is then listed on the
    parent's page under From its subtasks and put in front of Rouh in every
    chat of the parent and of its subtasks.

    `task` is the parent, `subtask_id` the subtask it came from and `chat_id`
    the chat it was sent from, which the line on the parent's page opens.
    Deleting the parent takes its notes with it (`0041_subtask_note`).
    """

    id = models.BigAutoField(primary_key=True)
    task = models.ForeignKey(Task, on_delete=models.DO_NOTHING, db_constraint=False,
                             db_column="task_id", related_name="+")
    subtask_id = models.TextField()
    chat_id = models.TextField(blank=True, default="")
    text = models.TextField()
    created_at = models.FloatField()

    class Meta:
        db_table = "subtask_note"
        indexes = [models.Index(fields=["task", "created_at"], name="subtask_note_task")]


class Run(models.Model):
    id = models.TextField(primary_key=True)
    parent_run = models.ForeignKey("self", on_delete=models.DO_NOTHING, db_constraint=False,
                                   null=True, blank=True, db_column="parent_run_id",
                                   related_name="children")
    title = models.TextField()
    brief = models.TextField(blank=True, default="")
    #: What the run was for, in one plain sentence written from its brief
    #: when it starts (`rouh/runsummary.py`).
    summary = models.TextField(blank=True, default="")
    #: A mutation, a run that changes Rouh itself, or everyday work (`RUN_KINDS`),
    #: decided when it starts (`runs.kind_of`).
    kind = models.TextField(blank=True, default="")
    #: The process of Rouh's that started it, "process:<name>", or "" for one started from
    #: the person's own words: what the steps it brings in are made by (`rouh/task_origin.py`).
    made_by = models.TextField(blank=True, default="", db_default="")
    agent = models.TextField(default="claude")
    workspace = models.TextField(blank=True, default="")
    policy = models.TextField(default="safe")
    state = models.TextField(default="running")
    phase = models.TextField(blank=True, default="")
    detail = models.TextField(blank=True, default="")
    archived = models.BooleanField(default=False)
    pinned = models.BooleanField(default=False)
    question = models.TextField(null=True, blank=True)
    branch = models.TextField(null=True, blank=True)
    worktree = models.TextField(null=True, blank=True)
    exit_code = models.IntegerField(null=True, blank=True)
    cost_usd = models.FloatField(null=True, blank=True)
    started_at = models.FloatField()
    updated_at = models.FloatField(null=True, blank=True)
    ended_at = models.FloatField(null=True, blank=True)
    seen_at = models.FloatField(default=0)

    class Meta:
        db_table = "run"
        indexes = [
            models.Index(fields=["parent_run"], name="run_parent"),
            models.Index(fields=["state", "-started_at"], name="run_state"),
        ]
        constraints = [
            models.CheckConstraint(condition=Q(agent__in=AGENTS), name="run_agent_known"),
            models.CheckConstraint(condition=Q(policy__in=POLICIES), name="run_policy_known"),
            models.CheckConstraint(condition=Q(state__in=RUN_STATES), name="run_state_known"),
            models.CheckConstraint(condition=Q(kind__in=RUN_KINDS), name="run_kind_known"),
        ]


class Artifact(models.Model):
    id = models.TextField(primary_key=True)
    kind = models.TextField()
    title = models.TextField()
    path = models.TextField(null=True, blank=True)
    mime = models.TextField(null=True, blank=True)
    head_version = models.IntegerField(default=1)
    pinned = models.BooleanField(default=False)
    created_at = models.FloatField()

    class Meta:
        db_table = "artifact"
        indexes = [
            models.Index(fields=["kind", "-created_at"], name="artifact_kind"),
            models.Index(fields=["path"], condition=Q(path__isnull=False),
                         name="artifact_path"),
        ]
        constraints = [
            models.CheckConstraint(condition=Q(kind__in=ARTIFACT_KINDS),
                                   name="artifact_kind_known"),
        ]


class ChatMessage(models.Model):
    """One message of one chat in the object model (`rouh/conversations.py`)."""

    id = models.TextField(primary_key=True)
    chat = models.ForeignKey(Chat, on_delete=models.DO_NOTHING, db_constraint=False,
                             db_column="chat_id", related_name="messages")
    seq = models.IntegerField()
    role = models.TextField()
    body = models.TextField(blank=True, default="")

    class Meta:
        db_table = "message"
        constraints = [
            models.UniqueConstraint(fields=["chat", "seq"], name="message_chat_seq"),
        ]


class ArtifactVersion(models.Model):
    pk = models.CompositePrimaryKey("artifact_id", "version")
    artifact = models.ForeignKey(Artifact, on_delete=models.DO_NOTHING, db_constraint=False,
                                 db_column="artifact_id", related_name="versions")
    version = models.IntegerField()
    body = models.TextField(null=True, blank=True)
    made_by_run = models.ForeignKey(Run, on_delete=models.DO_NOTHING, db_constraint=False,
                                    null=True, blank=True, db_column="made_by_run",
                                    related_name="+")

    class Meta:
        db_table = "artifact_version"
        indexes = [models.Index(fields=["made_by_run"], name="artifact_version_run")]


class Link(models.Model):
    """Who owns what, and what was made from, by or about what."""

    id = models.TextField(primary_key=True)
    rel = models.TextField()
    src_type = models.TextField()
    src_id = models.TextField()
    dst_type = models.TextField()
    dst_id = models.TextField()
    created_at = models.FloatField()

    class Meta:
        db_table = "link"
        indexes = [
            models.Index(fields=["src_type", "src_id", "rel"], name="link_src"),
            models.Index(fields=["dst_type", "dst_id", "rel"], name="link_dst"),
        ]
        constraints = [
            models.UniqueConstraint(fields=["rel", "src_type", "src_id", "dst_type", "dst_id"],
                                    name="link_unique"),
            # Exactly one owner for anything that is owned.
            models.UniqueConstraint(fields=["dst_type", "dst_id"], condition=Q(rel=OWNS),
                                    name="link_one_owner"),
            models.CheckConstraint(condition=Q(rel__in=RELS), name="link_rel_known"),
            models.CheckConstraint(condition=Q(src_type__in=KINDS), name="link_src_known"),
            models.CheckConstraint(condition=Q(dst_type__in=KINDS), name="link_dst_known"),
            # The ownership ranking itself is added by the migration as raw
            # SQL (`owns_check_sql`), because it is a CASE over two columns.
        ]


class ContentFile(models.Model):
    """One file of one object's own words, indexed for search.

    The words stay in the files, where an agent can edit them with the tools
    it already has; this is the derived index over them, rebuilt off the files.
    ``search`` is PostgreSQL's full-text vector of the body, kept by the
    database itself, so it can never disagree with the body it came from.

    **A word is a run of letters and digits, and nothing else.** That is how
    SQLite's FTS5 read the body until 23 September 2026 (its `unicode61`
    tokenizer), and PostgreSQL's own parser reads it differently: it keeps
    `rouh.example.com` as one host name and `app.js` as one file name, so a
    search for "example" or "js" that used to find those files would have found
    nothing. So every run of anything else becomes one space before the body
    is turned into a vector, and a query is cut up the same way
    (`objects.search_content`). "Letters" is whatever the database's
    ``LC_CTYPE`` says a letter is, which is why the database is made with a
    UTF-8 one (``C.UTF-8``): Cyrillic and accented words are words.
    """

    pk = models.CompositePrimaryKey("object_id", "path")
    object_id = models.TextField()
    path = models.TextField()
    sha256 = models.TextField()
    bytes = models.BigIntegerField()
    modified = models.FloatField()
    body = models.TextField(blank=True, default="")
    indexed_at = models.FloatField()
    search = models.GeneratedField(
        expression=SearchVector(
            Func(F("body"), Value(WORD_BREAKS), Value(" "), Value("g"),
                 function="regexp_replace", output_field=models.TextField()),
            config="simple"),
        output_field=SearchVectorField(),
        db_persist=True,
    )

    class Meta:
        db_table = "content_file"
        indexes = [
            models.Index(fields=["object_id"], name="content_file_object"),
            models.Index(fields=["sha256"], name="content_file_sha"),
            GinIndex(fields=["search"], name="content_file_search"),
        ]


#: What a file the person uploaded can have been given to (`rouh/uploads.py`):
#: a chat it was sent in, a project it was added to, or a task or subtask it was
#: uploaded to from the task's own page (since 15 October 2026).
FILE_OWNERS: tuple[str, ...] = ("chat", "project", "task")


class UploadedFile(models.Model):
    """One file the person gave Rouh, indexed for search by the words in it.

    Derived, like ``ContentFile`` above: the truth is the file in the
    attachment store and the Markdown read out of it beside it
    (`attachments.WORDS`), and every row here can be rebuilt from those two
    (`uploads.catch_up`). ``session`` and ``att_id`` are where the file is in
    that store; ``owner_type`` and ``owner_id`` are the chat it was sent in,
    the project it was added to or the task it was uploaded to, and a row whose
    owner has gone is never found.

    ``search`` is the same vector ``content_file`` keeps, made the same way, so
    a word means one thing in both indexes.
    """

    pk = models.CompositePrimaryKey("session", "att_id")
    session = models.TextField()
    att_id = models.TextField()
    owner_type = models.TextField()
    owner_id = models.TextField()
    name = models.TextField()
    media_type = models.TextField(blank=True, default="")
    kind = models.TextField(default="file")
    size = models.BigIntegerField(default=0)
    uploaded_at = models.FloatField()
    body = models.TextField(blank=True, default="")
    indexed_at = models.FloatField()
    search = models.GeneratedField(
        expression=SearchVector(
            Func(F("body"), Value(WORD_BREAKS), Value(" "), Value("g"),
                 function="regexp_replace", output_field=models.TextField()),
            config="simple"),
        output_field=SearchVectorField(),
        db_persist=True,
    )

    class Meta:
        db_table = "uploaded_file"
        indexes = [
            models.Index(fields=["owner_type", "owner_id"], name="uploaded_file_owner"),
            GinIndex(fields=["search"], name="uploaded_file_search"),
        ]
        constraints = [
            models.CheckConstraint(condition=Q(owner_type__in=FILE_OWNERS),
                                   name="uploaded_file_owner_known"),
        ]


class ObjectRow(models.Model):
    """The `object` view: projects and tasks as one list, read-only.

    Made by the migration as the same view it was in SQLite. Unmanaged:
    Django reads it and never tries to create, alter or write it.
    """

    id = models.TextField(primary_key=True)
    type = models.TextField()
    title = models.TextField()
    slug = models.TextField()
    number = models.IntegerField(null=True)
    status = models.TextField()
    folder = models.TextField()
    pinned = models.BooleanField()
    created_at = models.FloatField()
    updated_at = models.FloatField(null=True)

    class Meta:
        managed = False
        db_table = "object"
