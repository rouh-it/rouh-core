"""The model a chat was given by hand, beside the chat.

Petar, 26 September 2026: chats are of two kinds, General and every other
one, and each kind starts on a model of its own; "if a chat already has a
model chosen explicitly, that choice still wins over the default"
(`rouh/chatkinds.py`).

- `chat.model`: the model picked in the box beside the composer while this
  chat was open, or "" when nobody has picked one, which is the default for
  its kind. The pick used to belong to the browser tab, lasted until the tab
  was reloaded, and went with the tab into whatever chat it opened next.

Every chat already there has no pick, which is what was known about it: the
box's choice was never written down anywhere.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("rouh", "0028_turn_timing"),
    ]

    operations = [
        migrations.AddField(
            model_name="chat",
            name="model",
            field=models.TextField(blank=True, default=""),
        ),
    ]
