"""The risky topics allowed to one trusted contact (`trusted.TOPICS`).

Petar, 2 October 2026: an allowlist per trusted contact for the risky-topic
alert, opt-in and default-deny. Every contact starts with none.

On the installation it was written for, two contacts the owner named were
given one topic each, found by exactly their names. Who may talk about what is
that owner's own choice and lives only in that installation's database; a
fresh install starts every contact with none, so the seed does nothing.
"""
from django.db import migrations, models


def seed(apps, schema_editor):
    """Nothing to do: a contact's topics are the owner's to tick, in Settings."""


class Migration(migrations.Migration):

    dependencies = [
        ('rouh', '0055_page_highlights'),
    ]

    operations = [
        migrations.AddField(
            model_name='trustedcontact',
            name='topics',
            field=models.JSONField(default=list),
        ),
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
