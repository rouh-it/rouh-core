"""Passages a reader highlighted on a page (`rouh/highlights.py`).

Petar, 1 October 2026 (fr_69625bf0c1a8): a highlighter beside comments and
Ask AI, in colours, the way Apple Books and Kindle have one. Each reader's
highlights are their own, kept under the page as its owner has it.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('rouh', '0054_case_traces_and_notes'),
    ]

    operations = [
        migrations.CreateModel(
            name='PageHighlight',
            fields=[
                ('id', models.BigAutoField(primary_key=True, serialize=False)),
                ('owner_id', models.TextField()),
                ('org_id', models.TextField()),
                ('rel', models.TextField()),
                ('user_id', models.TextField()),
                ('colour', models.TextField()),
                ('anchor', models.JSONField(default=dict)),
                ('created_at', models.FloatField()),
            ],
            options={
                'db_table': 'page_highlights',
                'indexes': [models.Index(fields=['owner_id', 'org_id', 'rel', 'user_id', 'id'], name='page_highlights_page')],
            },
        ),
    ]
