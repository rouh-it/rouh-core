"""The model a chat is set to, beside the composer (Petar, 8 November 2026).

"I am doing heavy and difficult work and I don't want cheap model to answer me ... add a new
control - model Cheap, Smart, Auto ... saved in the settings of the chat ... whatever is on rouh,
will be the default for any new chat, unless changed later."

- `chat.model_choice`: "cheap", "smart" or "auto", set by the person with the control beside the
  composer while this chat was open, or "" when nobody has set it, which is the default from the
  Models page (`chatkinds.default_choice`): Best is Smart, Balanced is Auto, Saver is Cheap.

Every chat already there has no choice, so it keeps following the Models page until somebody
sets one. The per-chat model box of September (`0029_chat_model`) held a model's id and went on
18 October 2026 (`0179_model_tiers`); this holds one of three words and nothing else.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("rouh", "0244_decision_kind_action"),
    ]

    operations = [
        migrations.AddField(
            model_name="chat",
            name="model_choice",
            field=models.TextField(blank=True, default="", db_default=""),
        ),
    ]
