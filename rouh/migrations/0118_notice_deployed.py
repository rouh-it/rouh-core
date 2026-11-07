"""The commit a finished run put live, on its notice (`Notice.deployed`).

Petar, 11 October 2026 (fr_c09961ff435d): "These are two notifications for the same thing.
Please find a way to combine them. Basically if the run was a feature that need restart,
just add the button reload to it." A run's "Done" notice now names the commit it deployed,
so a page served before that deploy puts its Reload on that notice rather than dropping in
a "Rouh has been updated" of its own (`noteBuild` in `app/notices.js`).
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("rouh", "0117_grants"),
    ]

    operations = [
        migrations.AddField(
            model_name="notice",
            name="deployed",
            field=models.TextField(blank=True, default=""),
        ),
    ]
