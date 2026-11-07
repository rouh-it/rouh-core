"""The morning brief's Birthdays: which calendar birthday is which contact.

Petar, 30 September 2026 (fr_d3ea4a374d50): "if the people having birthdays
are not linked to contacts, give me a button to a modal that picks the right
person so you can link them. Once linked, replace the generic contactless
birthday event with the full name and company of the contact."

One row per link he makes (`rouh/birthdays.py`). A Rouh rolled back past this
migration loses only the links.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("rouh", "0046_run_summary"),
    ]

    operations = [
        migrations.CreateModel(
            name="BirthdayLink",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("user_id", models.TextField()),
                ("org_id", models.TextField()),
                ("calendar_id", models.TextField()),
                ("event_key", models.TextField()),
                ("contact_uid", models.TextField()),
                ("title", models.TextField(blank=True, default="")),
                ("linked_at", models.FloatField()),
            ],
            options={"db_table": "birthday_links"},
        ),
        migrations.AddConstraint(
            model_name="birthdaylink",
            constraint=models.UniqueConstraint(
                fields=("org_id", "user_id", "calendar_id", "event_key"),
                name="birthday_links_one_per_event"),
        ),
    ]
