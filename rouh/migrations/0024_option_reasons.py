"""Why each version of a page exists.

Petar, 24 September 2026 (fr_662a64715b9f): "each option for how something
should look or what we should choose needs to have reasoning somewhere around
it so that we know why somebody picked that specific option to exist."

- `askai_edits.reason`: why the page should be the way a change made it, in
  one sentence, written by Ask AI from what the reader asked. It goes with the
  change into the options when the change is kept as one
  (`pagehistory.keep`), where every version shows its reason. The versions
  themselves are JSON in `page_options.alts`, so the reason there needs no
  column of its own.

Every row already there has no reason, and the page offers to write one.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("rouh", "0023_page_history_and_options"),
    ]

    operations = [
        migrations.AddField(
            model_name="askedit",
            name="reason",
            field=models.TextField(blank=True, default=""),
        ),
    ]
