"""A task's status is kept in the database, in five words, with every change to it and its summary.

Petar, 6 October 2026, by voice, straight after `_tasks.md` became a view of this database:
"well we want the database to be the source. and we don't want 2 copies of the same thing.
so if we have status and summary in db, don't have that in the files." So the status each
task's folder held, and the summary beside it, are kept here and nowhere else from now
on (`rouh/taskrecord.py`).

The row already had `state`, three words. The file had five - not-started, in-progress,
waiting, stopped, done - and the five are what the workspace's index, the control room and a
goal's steps tell apart, so `task.status` holds the five and `state` stays what they come to
in three, with a CHECK that the two never disagree.

This is the one moment the files are read for a status. The deploy that runs it is the one
that stops anything reading them, and the files still carry their statuses at this commit:
each row takes the word its own folder gives, where that word means what the row's
state already says. A row the file disagrees with keeps its state, which is the database's.

A step whose only status was its line in its task's `steps` list (nineteen on the live server
on 6 October 2026, the rows all left at the "open" they were taken in with, because nothing
ever read that list for a status) takes the status that line gives, state and all, and the
change is written down in `task_change` as made by this migration.

`task_change` is the history git used to give, and `task_token` the key the laptop uses to
reach `/api/task`.
"""
import os
import re
import time
from pathlib import Path

from django.db import migrations, models
from django.db.models import Q

STATUSES = ("not-started", "in-progress", "waiting", "stopped", "done")
STATE_OF = {"not-started": "open", "in-progress": "open", "stopped": "open",
            "waiting": "waiting", "done": "done"}
#: The other words the workspace's index understood (`pages._STATUS_WORDS`, 6 October 2026).
WORDS = {"new": "not-started", "to-do": "not-started", "todo": "not-started",
         "not-started": "not-started", "started": "in-progress", "working": "in-progress",
         "waiting-on-you": "waiting", "blocked": "waiting", "paused": "stopped",
         "finished": "done", "complete": "done", "completed": "done"}
BY = "migration 0097, from the files"


def _word(raw) -> str:
    if not isinstance(raw, str):
        return ""
    key = re.sub(r"[\s_]+", "-", raw.strip().lower())
    key = WORDS.get(key, key)
    return key if key in STATUSES else ""


def _record(root: Path, folder: str) -> dict:
    """What the task's folder said of its status when this ran on the first installation.
    No folder says it any more, so a database made now keeps each row's state as it is."""
    return {}


def _root() -> Path | None:
    try:
        from rouh.config import config
    except Exception:
        return None
    root = config.assistant_repo or ""
    return Path(root) if root and os.path.isdir(root) else None


def fill(apps, schema_editor):
    Task = apps.get_model("rouh", "Task")
    TaskChange = apps.get_model("rouh", "TaskChange")
    root = _root()
    rows = list(Task.objects.all())
    listed: dict[str, str] = {}
    if root is not None:
        for row in rows:
            if not row.folder:
                continue
            steps = _record(root, row.folder).get("steps")
            if not isinstance(steps, dict):
                continue
            for name, entry in steps.items():
                if isinstance(entry, dict) and _word(entry.get("status")):
                    listed[f"{row.folder}/{name}"] = _word(entry.get("status"))
    now = time.time()
    for row in rows:
        own = _word(_record(root, row.folder).get("status")) if root and row.folder else ""
        if row.state == "done":
            word = "done"
        elif row.state == "waiting":
            word = "waiting"
        elif own and STATE_OF[own] == "open":
            word = own
        else:
            word = "not-started"
        was = row.state
        line = listed.get(row.folder or "")
        if not own and line and was == "open" and line != word:
            # The step's line in its task's list is the only status it was ever given.
            TaskChange.objects.create(task_id=row.id, field="status", old=word, new=line,
                                      at=now, by=f"{BY}: its line in its task's steps list")
            word = line
            row.state = STATE_OF[line]
            if row.state != "open" and row.closed_at is None:
                # Stopped then, not now: a stop dated today would light every one of
                # them as news the person has not seen (`owning._ready_at`).
                row.closed_at = row.seen_at or row.updated_at or row.created_at
        row.status = word
        row.save(update_fields=["status", "state", "closed_at"])


class Migration(migrations.Migration):

    dependencies = [
        ("rouh", "0096_task_summary"),
    ]

    operations = [
        migrations.AddField(
            model_name="task",
            name="status",
            field=models.TextField(default="not-started"),
        ),
        migrations.CreateModel(
            name="TaskChange",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("task_id", models.TextField()),
                ("field", models.TextField()),
                ("old", models.TextField(blank=True, default="")),
                ("new", models.TextField(blank=True, default="")),
                ("at", models.FloatField()),
                ("by", models.TextField(blank=True, default="")),
                ("run", models.TextField(blank=True, default="")),
                ("pending", models.BooleanField(default=False)),
            ],
            options={
                "db_table": "task_change",
                "indexes": [models.Index(fields=["task_id", "at"], name="task_change_task")],
                "constraints": [models.CheckConstraint(
                    condition=Q(field__in=("status", "summary")),
                    name="task_change_field_known")],
            },
        ),
        migrations.CreateModel(
            name="TaskToken",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("user_id", models.TextField()),
                ("org_id", models.TextField()),
                ("name", models.TextField()),
                ("token_hash", models.TextField(unique=True)),
                ("created_at", models.FloatField()),
                ("last_used_at", models.FloatField(blank=True, null=True)),
                ("revoked_at", models.FloatField(blank=True, null=True)),
            ],
            options={"db_table": "task_token"},
        ),
        migrations.RunPython(fill, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="task",
            constraint=models.CheckConstraint(condition=Q(status__in=STATUSES),
                                              name="task_status_known"),
        ),
        migrations.AddConstraint(
            model_name="task",
            constraint=models.CheckConstraint(
                condition=(Q(status="done", state="done") | Q(status="waiting", state="waiting")
                           | Q(status__in=("not-started", "in-progress", "stopped"),
                               state="open")),
                name="task_status_is_its_state"),
        ),
    ]
