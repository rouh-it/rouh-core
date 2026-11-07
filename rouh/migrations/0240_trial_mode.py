"""Trials have two modes (Petar, 4 November 2026): an automatic test while a feature is built, fixed by its
builder for at most two rounds and then shipped, and a review he asked for in his own words, which is a
report to read and discuss, where nothing is fixed until he chooses what. Every try before this was one
of the first kind, or a hand-started one treated the same."""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('rouh', '0239_trial_jobs_testers'),
    ]

    operations = [
        migrations.AddField(model_name='trial', name='mode', field=models.TextField(default='auto')),
    ]
