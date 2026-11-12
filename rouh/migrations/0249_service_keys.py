import django.db.models
from django.db import migrations, models


class Migration(migrations.Migration):
    """The keys and settings of the services a Rouh uses, typed into Anatomy, Connections, Keys
    and sealed (`rouh/service_keys.py`), instead of being written into the settings file."""

    dependencies = [("rouh", "0248_user_land_id")]
    operations = [
        migrations.CreateModel(
            name="ServiceKey",
            fields=[
                ("pk", django.db.models.CompositePrimaryKey("org_id", "name", blank=True, editable=False,
                                                            primary_key=True, serialize=False)),
                ("org_id", models.TextField()),
                ("name", models.TextField()),
                ("value_sealed", models.TextField()),
                ("last4", models.TextField(blank=True, default="")),
                ("saved_by", models.TextField(blank=True, default="")),
                ("saved_at", models.FloatField(default=0)),
            ],
            options={"db_table": "service_key"},
        ),
        migrations.CreateModel(
            name="ServiceCheck",
            fields=[
                ("pk", django.db.models.CompositePrimaryKey("org_id", "service", blank=True, editable=False,
                                                            primary_key=True, serialize=False)),
                ("org_id", models.TextField()),
                ("service", models.TextField()),
                ("checked_at", models.FloatField(default=0)),
                ("ok", models.BooleanField(null=True)),
                ("said", models.TextField(blank=True, default="")),
            ],
            options={"db_table": "service_check"},
        ),
    ]
