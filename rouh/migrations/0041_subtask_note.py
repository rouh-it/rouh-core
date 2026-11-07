"""Notes sent up from a subtask's chat to its parent task.

Petar, 29 September 2026 (fr_3113364c29fa): a subtask's New chat opened its
parent task's chat. A subtask's chat is its own now, and what is worth the
parent knowing is sent up from it (`rouh/subtasknotes.py`). This is where that
is kept: one row per note, under the parent, naming the subtask and the chat it
came from.

Deleting the parent takes its notes with it, the way `task_answer` goes with
its task (`0016_task_answer`). The table starts empty, so a Rouh rolled back
past this migration loses nothing it had before.
"""
import django.db.models.deletion
from django.db import migrations, models

FOREIGN_KEY = ("subtask_note_task_fk", "task_id")


class Migration(migrations.Migration):

    dependencies = [
        ("rouh", "0040_project_color"),
    ]

    operations = [
        migrations.CreateModel(
            name="SubtaskNote",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("subtask_id", models.TextField()),
                ("chat_id", models.TextField(blank=True, default="")),
                ("text", models.TextField()),
                ("created_at", models.FloatField()),
                ("task", models.ForeignKey(db_column="task_id", db_constraint=False,
                                           on_delete=django.db.models.deletion.DO_NOTHING,
                                           related_name="+", to="rouh.task")),
            ],
            options={
                "db_table": "subtask_note",
                "indexes": [models.Index(fields=["task", "created_at"],
                                         name="subtask_note_task")],
            },
        ),
        migrations.RunSQL(
            f'ALTER TABLE "subtask_note" ADD CONSTRAINT "{FOREIGN_KEY[0]}" FOREIGN KEY '
            f'("{FOREIGN_KEY[1]}") REFERENCES "task" ("id") ON DELETE CASCADE '
            'DEFERRABLE INITIALLY DEFERRED',
            reverse_sql=f'ALTER TABLE "subtask_note" DROP CONSTRAINT "{FOREIGN_KEY[0]}"'),
    ]
