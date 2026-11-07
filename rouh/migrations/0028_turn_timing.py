"""How long each turn took to start answering, and which tools it loaded.

Petar, 26 September 2026, asking for every tool to be deferred and found
through a search: "Measure it ... input tokens per turn, cache read and write
tokens, time to first token and time to the first spoken word ... Log these
per turn so they can be compared later."

The tokens were already on every `spend` row, and since 0027 each request's
own tokens are in `calls`. These are the rest, written by `brain.py` beside
them (`_timed`):

- `first_token_ms`: from the first request going out to the first thing
  streaming back, thinking included;
- `first_text_ms` and `first_word_ms`: from the start of the turn to the
  first words on the screen and the first sentence handed to the voice;
- `tool_search`: how the turn's tools were declared (`rouh/toolsearch.py`);
- `tools_loaded`: the tools a search loaded, comma-separated.

Every row already there is from before, and says so by having none of them.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("rouh", "0027_spend_per_request"),
    ]

    operations = [
        migrations.AddField(
            model_name="spend",
            name="first_token_ms",
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="spend",
            name="first_text_ms",
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="spend",
            name="first_word_ms",
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="spend",
            name="tool_search",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="spend",
            name="tools_loaded",
            field=models.TextField(blank=True, default=""),
        ),
    ]
