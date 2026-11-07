"""Cloudflare zones: an organisation's API token for each, typed into Settings and sealed
(`rouh/cloudflare.py`).

Petar, 12 October 2026: "create an input field where I can save the token in settings, so
it doesn't pass through the LLM. Remember I have one cloudflare token for [the first Rouh's
domain] and now we are doing another one for Rouh.it". The rows themselves are made the first time the zones
are read, and a token already in Rouh's environment is sealed into its row then, so nothing
secret is in a migration.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("rouh", "0128_thoughts"),
    ]

    operations = [
        migrations.CreateModel(
            name="CloudflareZone",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("org_id", models.TextField()),
                ("zone", models.TextField()),
                ("zone_id", models.TextField(blank=True, default="")),
                ("account_id", models.TextField(blank=True, default="")),
                ("status", models.TextField(blank=True, default="")),
                ("starting", models.BooleanField(default=False)),
                ("token_sealed", models.TextField(blank=True, default="")),
                ("last4", models.TextField(blank=True, default="")),
                ("saved_at", models.FloatField(default=0)),
                ("saved_by", models.TextField(blank=True, default="")),
                ("source", models.TextField(blank=True, default="")),
                ("carried", models.BooleanField(default=False)),
                ("checked_at", models.FloatField(default=0)),
                ("check_ok", models.BooleanField(blank=True, null=True)),
                ("checks", models.JSONField(blank=True, default=list)),
                ("made_at", models.FloatField(default=0)),
                ("updated_at", models.FloatField(default=0)),
            ],
            options={"db_table": "cloudflare_zones"},
        ),
        migrations.AddConstraint(
            model_name="cloudflarezone",
            constraint=models.UniqueConstraint(fields=("org_id", "zone"), name="cloudflare_zones_one"),
        ),
    ]
