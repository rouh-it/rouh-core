"""Goals are tasks now: the goal tables and the check-in's column leave the models.

Petar, 27 September 2026: "The goal will essentially become one task with a
label/Tag Goal (not folder) and will have its sub tasks and sub-sub-tasks just
the same as our system is designed" (`rouh/goals.py`). So a goal is no longer a
row of `goals` with `goal_entries` counted toward it and a reminder of kind
`check_in` naming it by `reminders.goal_id`.

Only Django's picture of the database changes here, not the database. The two
tables and the column stay where they are, empty on the live server the day
this was written, so a Rouh rolled back past this still finds everything it
reads; a later migration can drop them once nothing is going back.
"""
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("rouh", "0032_telegram_forks"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.DeleteModel(name="GoalEntry"),
                migrations.DeleteModel(name="Goal"),
                migrations.RemoveField(model_name="reminder", name="goal_id"),
            ],
            database_operations=[],
        ),
    ]
