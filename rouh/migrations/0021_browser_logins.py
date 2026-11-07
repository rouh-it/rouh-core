"""The Live browser's saved logins: one sealed row per person.

Petar, 24 September 2026, answering task 60: "for now I only want 9 - the live
visual browser." The browser Rouh drives for errands keeps the person's logins
between one errand and the next, and a login is a credential, so it is kept
here, sealed (`rouh/browsing.py`, `Logins`), keyed by the person and their
organisation, and never on disk beside the browser.

Nothing is in the table until the browser has been used, so a Rouh rolled back
past this migration loses nothing it had before.

It was written as 0020 and renumbered before it landed: another 0020 reached
main while it was being built, and two leaves in one app is a graph Django
refuses to migrate.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("rouh", "0020_guests_and_page_edits"),
    ]

    operations = [
        migrations.CreateModel(
            name="BrowserLogins",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("user_id", models.TextField()),
                ("org_id", models.TextField()),
                ("state_sealed", models.TextField()),
                ("sites", models.IntegerField(default=0)),
                ("saved_at", models.FloatField()),
            ],
            options={
                "db_table": "browser_logins",
                "constraints": [models.UniqueConstraint(fields=["org_id", "user_id"],
                                                        name="browser_logins_one")],
            },
        ),
    ]
