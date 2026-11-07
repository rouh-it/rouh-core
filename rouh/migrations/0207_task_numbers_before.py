"""The numbers a task or a subtask was called by before a move renumbered it (`rouh/moving.py`).

Petar, 22 October 2026 (fr_676c7ad596fd): a subtask moved to another task, to a new task or
promoted to a task of its own takes a new number, "maybe that should just be stored in the
subtask somehow as its history: a list of what it was in the past. That way, when I search
for 92-08, if that's what I remember, it would still appear, but it would be with the new
name, 103-01." Every task starts with none.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('rouh', '0206_youtube_transcripts'),
    ]

    operations = [
        migrations.AddField(
            model_name='task',
            name='numbers_before',
            field=models.JSONField(blank=True, default=list, null=True),
        ),
    ]
