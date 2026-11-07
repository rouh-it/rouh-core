"""Long-running work becomes quests: each record is joined to a numbered task.

Petar, 5 October 2026: long-running work becomes "Quests", and a quest is part of the task
model, the way a goal is a task tagged Goal. The record keeps what must not live in git
(its money, dates, state, events and what is its own) and gains its task's id and number.

The money experiment, record 1, is joined to task 89 here, which its research runs made
for it, if this install has that task: Petar renamed the experiment "AI with Rouh" the same
evening, so its title no longer matches the task's. Writing its goal, rules, plan and
notebook into the task's folder needs the workspace, which a migration does not have: Rouh
does it at start (`quests.adopt`), and there any other record takes the task with exactly
its title, or a new one. Nothing in the record is changed or lost here, and its four texts
stay in it as the copy.
"""
from django.db import migrations, models


def first_is_89(apps, schema_editor):
    with schema_editor.connection.cursor() as cur:
        cur.execute("SELECT to_regclass('task') IS NOT NULL")
        if not cur.fetchone()[0]:
            return
        cur.execute("SELECT 1 FROM task WHERE id = 'task-89' AND number = 89")
        if cur.fetchone() is None:
            return
        cur.execute("UPDATE long_work SET task_id = 'task-89', task_number = 89 "
                    "WHERE id = 1 AND task_id = '' "
                    "AND NOT EXISTS (SELECT 1 FROM long_work WHERE task_number = 89)")


class Migration(migrations.Migration):

    dependencies = [
        ("rouh", "0093_model_uses"),
    ]

    operations = [
        migrations.AddField(
            model_name="longwork",
            name="task_id",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="longwork",
            name="task_number",
            field=models.IntegerField(default=0),
        ),
        migrations.RunPython(first_is_89, migrations.RunPython.noop),
    ]
