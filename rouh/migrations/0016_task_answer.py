"""Answers: what the person answered a waiting task, from the box on its page.

Petar, 24 September 2026 (fr_2050f48023a7): "it has to be clear what happens
afterwards. would the chat continue? the task will continue?" An answer sent
from the task's page is written here as it is sent, so the page can say it was
answered, and what is carrying it on, until the job that takes it in has
changed the task itself (`rouh/answering.py`).

Deleting a task takes its answers with it, the way the object model's other
foreign keys do (`0002_database_rules`). The table starts empty, so a Rouh
rolled back past this migration loses nothing it had before.
"""
from django.db import migrations, models

FOREIGN_KEY = ("task_answer_task_fk", "task_id")


class Migration(migrations.Migration):

    dependencies = [
        ("rouh", "0015_mail_alert_log"),
    ]

    operations = [
        migrations.CreateModel(
            name="TaskAnswer",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("task", models.ForeignKey(db_column="task_id", db_constraint=False,
                                           on_delete=models.DO_NOTHING, related_name="+",
                                           to="rouh.task")),
                ("asked", models.TextField()),
                ("answer", models.TextField()),
                ("chat_id", models.TextField(blank=True, default="")),
                ("created_at", models.FloatField()),
            ],
            options={
                "db_table": "task_answer",
                "indexes": [models.Index(fields=["task", "created_at"],
                                         name="task_answer_task")],
            },
        ),
        migrations.RunSQL(
            f'ALTER TABLE "task_answer" ADD CONSTRAINT "{FOREIGN_KEY[0]}" FOREIGN KEY '
            f'("{FOREIGN_KEY[1]}") REFERENCES "task" ("id") ON DELETE CASCADE '
            'DEFERRABLE INITIALLY DEFERRED',
            reverse_sql=f'ALTER TABLE "task_answer" DROP CONSTRAINT "{FOREIGN_KEY[0]}"'),
    ]
