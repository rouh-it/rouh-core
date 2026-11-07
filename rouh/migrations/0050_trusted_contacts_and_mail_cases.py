"""Trusted contacts, their groups, and every email from one tracked as a case.

Petar, 30 September 2026: routine in-scope email from a contact he trusted by
exact address may be handled by Rouh; anything sensitive, uncertain or out of
scope waits for his decision on a page of its own (`rouh/trusted.py`,
`rouh/mail_cases.py`, `rouh/models/trust.py`). New tables only, so a Rouh
rolled back past this migration loses only the trust and the cases.
"""
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("rouh", "0049_mail_stages"),
    ]

    operations = [
        migrations.CreateModel(
            name="ContactGroup",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("user_id", models.TextField()),
                ("org_id", models.TextField()),
                ("name", models.TextField()),
                ("created_at", models.FloatField(default=0)),
            ],
            options={"db_table": "contact_groups"},
        ),
        migrations.AddConstraint(
            model_name="contactgroup",
            constraint=models.UniqueConstraint(fields=("org_id", "user_id", "name"),
                                               name="contact_groups_one_name"),
        ),
        migrations.CreateModel(
            name="TrustedContact",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("user_id", models.TextField()),
                ("org_id", models.TextField()),
                ("contact_id", models.TextField(blank=True, default="")),
                ("name", models.TextField(blank=True, default="")),
                ("trusted", models.BooleanField(default=False)),
                ("categories", models.JSONField(default=list)),
                ("group", models.ForeignKey(blank=True, null=True,
                                            on_delete=django.db.models.deletion.SET_NULL,
                                            related_name="+", to="rouh.contactgroup")),
                ("note", models.TextField(blank=True, default="")),
                ("created_at", models.FloatField(default=0)),
                ("updated_at", models.FloatField(default=0)),
                ("revision", models.IntegerField(default=1)),
            ],
            options={"db_table": "trusted_contacts"},
        ),
        migrations.AddIndex(
            model_name="trustedcontact",
            index=models.Index(fields=["org_id", "user_id"], name="trusted_contacts_mine"),
        ),
        migrations.CreateModel(
            name="TrustedAddress",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("user_id", models.TextField()),
                ("org_id", models.TextField()),
                ("contact", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                                              related_name="addresses",
                                              to="rouh.trustedcontact")),
                ("address", models.TextField()),
            ],
            options={"db_table": "trusted_addresses"},
        ),
        migrations.AddConstraint(
            model_name="trustedaddress",
            constraint=models.UniqueConstraint(fields=("org_id", "user_id", "address"),
                                               name="trusted_addresses_once"),
        ),
        migrations.CreateModel(
            name="MailCase",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("user_id", models.TextField()),
                ("org_id", models.TextField()),
                ("message_id", models.TextField()),
                ("key", models.TextField(unique=True)),
                ("thread_id", models.TextField(blank=True, default="")),
                ("chat_id", models.TextField(blank=True, default="")),
                ("contact", models.ForeignKey(blank=True, null=True,
                                              on_delete=django.db.models.deletion.SET_NULL,
                                              related_name="+", to="rouh.trustedcontact")),
                ("sender", models.TextField(blank=True, default="")),
                ("sender_name", models.TextField(blank=True, default="")),
                ("subject", models.TextField(blank=True, default="")),
                ("email", models.JSONField(default=dict)),
                ("digest", models.TextField(blank=True, default="")),
                ("identity_ok", models.BooleanField(default=False)),
                ("identity_said", models.TextField(blank=True, default="")),
                ("stage", models.TextField(default="new")),
                ("assessment", models.JSONField(default=dict)),
                ("reasons", models.JSONField(default=list)),
                ("checks", models.JSONField(default=list)),
                ("route", models.TextField(blank=True, default="")),
                ("proposed_action", models.TextField(blank=True, default="")),
                ("proposed_reply", models.TextField(blank=True, default="")),
                ("approved_action", models.TextField(blank=True, default="")),
                ("approved_reply", models.TextField(blank=True, default="")),
                ("instruction", models.TextField(blank=True, default="")),
                ("attempts", models.IntegerField(default=0)),
                ("turn_started_at", models.FloatField(default=0)),
                ("work_report", models.JSONField(default=dict)),
                ("job_id", models.TextField(blank=True, default="")),
                ("verified_at", models.FloatField(default=0)),
                ("verified_said", models.TextField(blank=True, default="")),
                ("reply_claimed_at", models.FloatField(default=0)),
                ("reply_before", models.JSONField(default=list)),
                ("replied_at", models.FloatField(default=0)),
                ("reply_message_id", models.TextField(blank=True, default="")),
                ("notify_claimed_at", models.FloatField(default=0)),
                ("notified_at", models.FloatField(default=0)),
                ("notified_text", models.TextField(blank=True, default="")),
                ("outcome", models.TextField(blank=True, default="")),
                ("blocker", models.TextField(blank=True, default="")),
                ("created_at", models.FloatField(default=0)),
                ("updated_at", models.FloatField(default=0)),
            ],
            options={"db_table": "mail_cases"},
        ),
        migrations.AddConstraint(
            model_name="mailcase",
            constraint=models.UniqueConstraint(fields=("org_id", "user_id", "message_id"),
                                               name="mail_cases_once_per_message"),
        ),
        migrations.AddIndex(
            model_name="mailcase",
            index=models.Index(fields=["org_id", "user_id", "stage"], name="mail_cases_stage"),
        ),
        migrations.CreateModel(
            name="MailApproval",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("user_id", models.TextField()),
                ("org_id", models.TextField()),
                ("case", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                                           related_name="approvals", to="rouh.mailcase")),
                ("fingerprint", models.TextField()),
                ("proposed_action", models.TextField(blank=True, default="")),
                ("proposed_reply", models.TextField(blank=True, default="")),
                ("status", models.TextField(default="pending")),
                ("decided_reply", models.TextField(blank=True, default="")),
                ("edited", models.BooleanField(default=False)),
                ("instruction", models.TextField(blank=True, default="")),
                ("why_invalid", models.TextField(blank=True, default="")),
                ("asked_at", models.FloatField(default=0)),
                ("expires_at", models.FloatField(default=0)),
                ("decided_at", models.FloatField(default=0)),
                ("decided_by", models.TextField(blank=True, default="")),
                ("notified_at", models.FloatField(default=0)),
            ],
            options={"db_table": "mail_approvals"},
        ),
        migrations.AddIndex(
            model_name="mailapproval",
            index=models.Index(fields=["org_id", "user_id", "status"],
                               name="mail_approvals_status"),
        ),
        migrations.CreateModel(
            name="MailCaseEvent",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("user_id", models.TextField()),
                ("org_id", models.TextField()),
                ("case", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                                           related_name="events", to="rouh.mailcase")),
                ("at", models.FloatField()),
                ("stage", models.TextField(blank=True, default="")),
                ("said", models.TextField(blank=True, default="")),
            ],
            options={"db_table": "mail_case_events"},
        ),
    ]
