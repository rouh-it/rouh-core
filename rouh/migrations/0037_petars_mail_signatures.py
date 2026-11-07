"""The owner's two email signatures, as they were given on 27 September 2026.

The signatures are each person's own setting now (`rouh/signatures.py`), in
Settings under Email signatures. On the installation they were given for, this
wrote that owner's in once, leaving a row already saved alone. Those
signatures now live only in that installation's database; anybody else starts
with none, so this does nothing.
"""
from django.db import migrations


def seed(apps, schema_editor):
    """Nothing to do: a signature is a person's own setting, made in Settings."""


class Migration(migrations.Migration):

    dependencies = [
        ("rouh", "0036_telegram_account"),
    ]

    operations = [
        migrations.RunPython(seed, migrations.RunPython.noop),
    ]
