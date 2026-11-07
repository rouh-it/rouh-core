"""A thought's enriched version (`rouh/thought_enrich.py`).

Petar, 14 October 2026 (fr_f2b63641423a): "that thoughts feature - I would love it if when you
receive a new one, you go out and research and think about it and expand it and make a new task
with visual explainer that I can click from the thought list page and detail page and see the
enriched version". So each new thought gets a task of its own and a run that researches it and
writes its page, and the thought remembers which task, which run, which page, and how it went.
A thought kept before this has no enriched version, and its state is empty.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('rouh', '0150_mutations'),
    ]

    operations = [
        migrations.AddField(model_name='thought', name='enrich_state',
                            field=models.TextField(blank=True, default='')),
        migrations.AddField(model_name='thought', name='enrich_task',
                            field=models.TextField(blank=True, default='')),
        migrations.AddField(model_name='thought', name='enrich_run',
                            field=models.TextField(blank=True, default='')),
        migrations.AddField(model_name='thought', name='enrich_page',
                            field=models.TextField(blank=True, default='')),
        migrations.AddField(model_name='thought', name='enrich_why',
                            field=models.TextField(blank=True, default='')),
        migrations.AddField(model_name='thought', name='enrich_at',
                            field=models.FloatField(blank=True, null=True)),
        migrations.AddField(model_name='thought', name='enrich_done_at',
                            field=models.FloatField(blank=True, null=True)),
        migrations.AddIndex(model_name='thought',
                            index=models.Index(fields=['enrich_run'], name='thoughts_enrich_run')),
    ]
