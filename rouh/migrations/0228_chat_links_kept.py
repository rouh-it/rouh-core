"""An empty step, kept so the numbering of the migrations has no gap.

It once re-linked one installation's chats by hand. That repair was that
installation's own data, done once, and is not code every Rouh needs, so this
step now does nothing.
"""
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("rouh", "0227_incubator"),
    ]

    operations = []
