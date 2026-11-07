"""A Dreame robot paired in Mi Home, through a Xiaomi account (`rouh/dreame.py`).

Petar, 17 October 2026: the robot may be paired in the Dreamehome app or in Mi Home, so a
connection says which, and a Mi Home one keeps Xiaomi's signing key, sealed.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("rouh", "0171_slack_promise_clockwork"),
    ]

    operations = [
        migrations.AddField(
            model_name="dreameconnection",
            name="account",
            field=models.TextField(blank=True, default="dreamehome"),
        ),
        migrations.AddField(
            model_name="dreameconnection",
            name="session_sealed",
            field=models.TextField(blank=True, default=""),
        ),
    ]
