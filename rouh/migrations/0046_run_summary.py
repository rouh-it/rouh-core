"""A run's plain sentence: what it was for.

Petar, 29 September 2026 (fr_0b6dec937436): "I lose a lot of time trying to
figure out what those runs were. When they are green can we show a sentence
that describes what we were trying to achieve instead of terminal lines?"

So a run carries one sentence, written by a small model from its brief as it
starts (`rouh/runsummary.py`) and shown on its card once it has finished well.
Every run already here starts with none and is given one from its brief; a
Rouh rolled back past this migration loses nothing it had before.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("rouh", "0045_tool_lines"),
    ]

    operations = [
        migrations.AddField(
            model_name="run",
            name="summary",
            field=models.TextField(blank=True, default=""),
        ),
    ]
