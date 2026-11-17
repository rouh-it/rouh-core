from django.db import migrations, models


class Migration(migrations.Migration):
    """Relationships between contacts, and the types the person made up (`rouh/relationships.py`)."""

    dependencies = [("rouh", "0257_heartbeat_kept_on")]
    operations = [
        migrations.CreateModel(
            name="ContactRelation",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("user_id", models.TextField()),
                ("org_id", models.TextField()),
                ("a", models.TextField()),
                ("b", models.TextField()),
                ("a_is", models.TextField()),
                ("b_is", models.TextField()),
                ("by", models.TextField(blank=True, default="")),
                ("created_at", models.FloatField(default=0)),
                ("updated_at", models.FloatField(default=0)),
            ],
            options={
                "db_table": "contact_relation",
                "indexes": [models.Index(fields=["org_id", "user_id", "a"], name="contact_relation_a"),
                            models.Index(fields=["org_id", "user_id", "b"], name="contact_relation_b")],
            },
        ),
        migrations.CreateModel(
            name="RelationType",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("user_id", models.TextField()),
                ("org_id", models.TextField()),
                ("label", models.TextField()),
                ("inverse", models.TextField(blank=True, default="")),
                ("used_at", models.FloatField(default=0)),
            ],
            options={
                "db_table": "contact_relation_type",
                "constraints": [models.UniqueConstraint(fields=("org_id", "user_id", "label"),
                                                        name="contact_relation_type_one")],
            },
        ),
    ]
