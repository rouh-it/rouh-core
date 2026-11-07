"""A night of the nightly feature run keeps what Parameters asked of it as a target to finish.

Petar, 20 October 2026, after night 17 built one gene of the four Parameters asked for: "can you please
make sure I get the right number of genes? if ideas get dropped at the idea stage, that is fine, pick
another one on loop." So the night's row keeps its target, what it finished, why it ended short when
it did, and each time Rouh sent its run back to work (`nightly_feature.progress`, `watch`).
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [("rouh", "0193_gene_uses_are_events")]

    operations = [
        migrations.AddField("nightlyfeaturenight", "target",
                            models.JSONField(blank=True, default=dict)),
        migrations.AddField("nightlyfeaturenight", "filled",
                            models.JSONField(blank=True, default=dict)),
        migrations.AddField("nightlyfeaturenight", "short_why",
                            models.TextField(blank=True, default="")),
        migrations.AddField("nightlyfeaturenight", "nudges",
                            models.JSONField(blank=True, default=list)),
    ]
