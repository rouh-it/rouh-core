"""A gene's trial is optional and its settings are his (`rouh/evolution.py`).

Petar, 18 October 2026: "Sometimes I don't want to evaluate. I want this feature to be ON
immediately. Other times, I may want to change the evaluation parameters. Such as what counts,
how many days is the trial etc." So each gene keeps its own trial's settings and outcome, and
Parameters keeps the three defaults a new trial starts from.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [("rouh", "0187_decision_numbers")]

    operations = [
        migrations.AddField("mutationsgene", "trial", models.JSONField(blank=True, default=dict)),
        migrations.AddField("evolutionsetting", "trial_days", models.IntegerField(default=7)),
        migrations.AddField("evolutionsetting", "trial_needed", models.IntegerField(default=1)),
        migrations.AddField("evolutionsetting", "trial_counts", models.JSONField(blank=True, default=list)),
    ]
