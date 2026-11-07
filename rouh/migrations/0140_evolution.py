"""Evolution: Parameters and the Gene library (`rouh/evolution.py`, EVOLUTION.md).

Petar, 13 October 2026, task 94 step 94-08. Five new tables, each keyed by organisation and
account; nothing existing is changed, so reversing it drops exactly these. The genes nights 3 to
10 built are brought in by `evolution.bring_in` when the library is first read, not here, so a
night that ends while this deploys is never missed and bringing them in can run any number of
times.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("rouh", "0139_box_numbers"),
    ]

    operations = [
        migrations.CreateModel(
            name="EvolutionSetting",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("org_id", models.TextField()),
                ("user_id", models.TextField()),
                ("total", models.IntegerField()),
                ("invisible", models.IntegerField()),
                ("shows_up", models.IntegerField()),
                ("ask_for", models.IntegerField()),
                ("changes_work", models.IntegerField()),
                ("updated_at", models.FloatField()),
                ("by", models.TextField(blank=True, default="")),
                ("history", models.JSONField(blank=True, default=list)),
            ],
            options={
                "db_table": "evolution_settings",
                "constraints": [models.UniqueConstraint(fields=("org_id", "user_id"),
                                                        name="evolution_setting_one")],
            },
        ),
        migrations.CreateModel(
            name="LibraryGene",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("org_id", models.TextField()),
                ("user_id", models.TextField()),
                ("key", models.TextField()),
                ("night_id", models.BigIntegerField(blank=True, null=True)),
                ("night", models.IntegerField(blank=True, null=True)),
                ("source", models.TextField(default="registered")),
                ("name", models.TextField()),
                ("kind", models.TextField(blank=True, default="")),
                ("kind_by", models.TextField(blank=True, default="")),
                ("sentence", models.TextField(blank=True, default="")),
                ("moment", models.TextField(blank=True, default="")),
                ("words", models.TextField(blank=True, default="")),
                ("place", models.TextField(blank=True, default="")),
                ("builds_on", models.TextField(blank=True, default="")),
                ("changed", models.TextField(blank=True, default="")),
                ("sensitive", models.BooleanField(default=False)),
                ("rhythm", models.TextField(blank=True, default="weekly")),
                ("switch", models.TextField(blank=True, default="")),
                ("original", models.JSONField(blank=True, default=dict)),
                ("observed", models.JSONField(blank=True, default=dict)),
                ("checked", models.JSONField(blank=True, default=dict)),
                ("try_it", models.JSONField(blank=True, default=dict)),
                ("use", models.JSONField(blank=True, default=dict)),
                ("screenshots", models.JSONField(blank=True, default=list)),
                ("steps", models.JSONField(blank=True, default=list)),
                ("report", models.TextField(blank=True, default="")),
                ("commits", models.JSONField(blank=True, default=list)),
                ("saves", models.TextField(blank=True, default="")),
                ("version", models.IntegerField(default=1)),
                ("parent_id", models.BigIntegerField(blank=True, null=True)),
                ("mutation_id", models.BigIntegerField(blank=True, null=True)),
                ("state", models.TextField(default="candidate")),
                ("before", models.TextField(blank=True, default="")),
                ("verdict", models.TextField(blank=True, default="")),
                ("released_at", models.FloatField(blank=True, null=True)),
                ("trial_started_at", models.FloatField(blank=True, null=True)),
                ("extended_at", models.FloatField(blank=True, null=True)),
                ("booked_at", models.FloatField(blank=True, null=True)),
                ("reminder_id", models.BigIntegerField(blank=True, null=True)),
                ("removal_run", models.TextField(blank=True, default="")),
                ("made_at", models.FloatField()),
                ("updated_at", models.FloatField()),
                ("answered_at", models.FloatField(blank=True, null=True)),
            ],
            options={
                "db_table": "library_genes",
                "constraints": [models.UniqueConstraint(fields=("org_id", "user_id", "key", "version"),
                                                        name="library_gene_one")],
                "indexes": [models.Index(fields=["org_id", "user_id", "state"], name="library_gene_whose")],
            },
        ),
        migrations.CreateModel(
            name="LibraryGeneEvent",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("org_id", models.TextField()),
                ("user_id", models.TextField()),
                ("gene_id", models.BigIntegerField()),
                ("kind", models.TextField()),
                ("by", models.TextField(blank=True, default="")),
                ("detail", models.TextField(blank=True, default="")),
                ("data", models.JSONField(blank=True, default=dict)),
                ("at", models.FloatField()),
            ],
            options={
                "db_table": "library_gene_events",
                "indexes": [models.Index(fields=["org_id", "user_id", "gene_id", "at"],
                                         name="library_gene_event_whose")],
            },
        ),
        migrations.CreateModel(
            name="GeneMutation",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("org_id", models.TextField()),
                ("user_id", models.TextField()),
                ("gene_id", models.BigIntegerField()),
                ("from_version", models.IntegerField(default=1)),
                ("words", models.TextField()),
                ("status", models.TextField(default="requested")),
                ("before", models.TextField(blank=True, default="")),
                ("night", models.IntegerField(blank=True, null=True)),
                ("result_gene_id", models.BigIntegerField(blank=True, null=True)),
                ("commits", models.JSONField(blank=True, default=list)),
                ("outcome", models.TextField(blank=True, default="")),
                ("history", models.JSONField(blank=True, default=list)),
                ("made_at", models.FloatField()),
                ("updated_at", models.FloatField()),
            ],
            options={
                "db_table": "gene_mutations",
                "indexes": [models.Index(fields=["org_id", "user_id", "status"], name="gene_mutation_whose")],
            },
        ),
        migrations.CreateModel(
            name="GeneQuestion",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("org_id", models.TextField()),
                ("user_id", models.TextField()),
                ("gene_id", models.BigIntegerField()),
                ("topic", models.BigIntegerField()),
                ("question", models.TextField()),
                ("answer", models.TextField(blank=True, default="")),
                ("model", models.TextField(blank=True, default="")),
                ("at", models.FloatField()),
            ],
            options={
                "db_table": "gene_questions",
                "indexes": [models.Index(fields=["org_id", "user_id", "gene_id"], name="gene_question_whose")],
            },
        ),
    ]
