"""When the person last opened each page (`pageplaces.opened`).

The Control Room says "You haven't opened it yet" about a page Rouh made, and
offers Read for it, only when that is true (Petar, 1 October 2026). Until now
nothing recorded that a page had been opened, so a page row gets the moment
its owner last had it on the canvas. Empty for every page until then.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("rouh", "0051_trust_levels_and_grants"),
    ]

    operations = [
        migrations.AddField(model_name="pageplace", name="opened_at",
                            field=models.FloatField(null=True, blank=True)),
    ]
