"""Recover without rouh.land (advanced), off by default (4 November 2026): the keys and recovery
words are a Rouh's own business, shown to its owner only if they turn this on (`rouh/birth.py`)."""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [("rouh", "0234_sign_in")]

    operations = [
        migrations.AddField(model_name="rouhbirth", name="advanced_recovery",
                            field=models.BooleanField(default=False)),
    ]
