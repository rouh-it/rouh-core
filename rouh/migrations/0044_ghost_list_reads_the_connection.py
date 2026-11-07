"""The ghost list reads Rouh's own Google connection too (`rouh/ghosts.py`).

30 September 2026, fr_1007ecea9327: "The ghost list should be for all mails you
have access to, including the read only". The connection keeps its last look
beside it, as a read-only mailbox does in `read_mailboxes.scan`. Both columns
start empty, so rolling back past this loses only a look that is made again.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("rouh", "0043_read_mailboxes_and_ghosts"),
    ]

    operations = [
        migrations.AddField(
            model_name="googleconnection",
            name="ghost_scan",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="googleconnection",
            name="ghost_scanned_at",
            field=models.FloatField(default=0),
        ),
    ]
