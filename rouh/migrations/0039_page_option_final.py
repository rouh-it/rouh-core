"""An option on a page marked final: decided, and shown as decided.

Petar, 29 September 2026 (fr_a383dc8329c0): "How do you close open items?
That was asked by one of the people working on the website. I think he might
mean coding an option as final between all those other options. If we don't
have a means of finalizing an option - we should." Who made it final and
when is the mark (`rouh/pagehistory.py`, `decide`); every option before this
one is still open, which is what NULL says.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("rouh", "0038_task_archived"),
    ]

    operations = [
        migrations.AddField(
            model_name="pageoption",
            name="final_by",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="pageoption",
            name="final_at",
            field=models.FloatField(blank=True, null=True),
        ),
    ]
