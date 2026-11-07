"""A question's box dismissed rather than answered.

Petar, 24 September 2026, the day the box on a waiting task's page was made
answerable in place: "i also need the option to dismiss it". A dismissal is a
row of `task_answer` like an answer, with nothing sent and nothing answered,
so the newest word on a question is the one the page and the lists go by
(`rouh/answering.py`). Every row there before this is an answer, which is what
the default says.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("rouh", "0016_task_answer"),
    ]

    operations = [
        migrations.AddField(
            model_name="taskanswer",
            name="dismissed",
            field=models.BooleanField(default=False),
        ),
    ]
