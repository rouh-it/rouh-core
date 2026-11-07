"""What each request of a turn cost, beside what the turn cost.

Petar, 26 September 2026, asking for the conversation to be read out of the
prompt cache by every round trip of a turn: record the cache reads and writes
"on every call, next to input_tokens ... so the savings can be seen".

- `spend.calls`: the requests of the turn, in the order they were made, each
  `{"input", "output", "cache_read", "cache_write"}` off that response's own
  usage (`rouh/costs.py`). The turn's own four columns stay the sums of them.

Every row already there has no requests listed, which is what was known about
it: only its sums were kept.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("rouh", "0026_relationships_onto_contacts"),
    ]

    operations = [
        migrations.AddField(
            model_name="spend",
            name="calls",
            field=models.JSONField(blank=True, default=list),
        ),
    ]
