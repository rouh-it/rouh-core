"""Every place a notice leads, each a button of its own (`Notice.links`).

Petar, 13 October 2026 (fr_677001efaa72): "When a run is complete, let's think bigger. If it is in
any way connected to the task system ... it should give me all the buttons: Run, Chat, Task, Visual
explainer." A finished run's notice led to one place, its chat or its page. It now carries every
place it leads (`run_report.destinations`), and the page draws them as a row of buttons; `link`
stays the one place a swipe right goes.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("rouh", "0134_silos"),
    ]

    operations = [
        migrations.AddField(
            model_name="notice",
            name="links",
            field=models.JSONField(blank=True, default=list),
        ),
    ]
