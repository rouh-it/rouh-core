"""A tester can be paused (Petar, 5 November 2026: "Can you please pause vesela and Boris testing. ideally
give me a pause button I can toggle on/off"). A paused tester starts no new try of any kind, and keeps
their place on the list and as the one who tries every change; how many tries were skipped while paused
is kept beside it. The switch that pauses everyone is a setting of the person's (`trials_paused`)."""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('rouh', '0241_files'),
    ]

    operations = [
        migrations.AddField(model_name='trialtester', name='paused_at',
                            field=models.FloatField(blank=True, null=True)),
        migrations.AddField(model_name='trialtester', name='skipped',
                            field=models.IntegerField(default=0)),
        migrations.AddField(model_name='trialtester', name='skipped_at',
                            field=models.FloatField(blank=True, null=True)),
    ]
