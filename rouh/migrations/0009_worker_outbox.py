"""The worker outbox: notes a background job asked Rouh to email the person.

Petar, 24 September 2026: a job told "email me the summary" could not, because
a worker has no Google token, may not read the server's .env, and this machine
has no mail. So the job queues the text in this table, and Rouh sends it from
the person's own Gmail after saying who it goes to and getting a yes.
`rouh/outbox.py` owns what the rows mean.

There is no recipient column, on purpose: the address is never the job's to
choose. Nothing is in the table until a job queues a note, so a Rouh rolled
back past this migration loses nothing it had before.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("rouh", "0008_apple_contacts"),
    ]

    operations = [
        migrations.CreateModel(
            name="WorkerNote",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("job_id", models.TextField()),
                ("created_at", models.FloatField()),
                ("subject", models.TextField()),
                ("body", models.TextField()),
                ("status", models.TextField(default="pending")),
                ("sent_at", models.FloatField(blank=True, null=True)),
                ("message_id", models.TextField(blank=True, default="")),
            ],
            options={
                "db_table": "worker_outbox",
                "indexes": [models.Index(fields=["job_id", "status"], name="worker_outbox_job")],
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(("status__in", ("pending", "sent", "dismissed"))),
                        name="worker_outbox_status_known"),
                ],
            },
        ),
    ]
