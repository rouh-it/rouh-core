"""Passages a reader had explained in place on a page (`rouh/definitions.py`).

Petar, 20 October 2026 (fr_a06689f582ba): Define beside Ask over a selected
passage, which explains it in a tooltip in the light of the page around it,
and leaves it underlined so the explanation comes back on hover.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('rouh', '0195_owner_words_not_a_name'),
    ]

    operations = [
        migrations.CreateModel(
            name='PageDefinition',
            fields=[
                ('id', models.BigAutoField(primary_key=True, serialize=False)),
                ('owner_id', models.TextField()),
                ('org_id', models.TextField()),
                ('rel', models.TextField()),
                ('user_id', models.TextField()),
                ('anchor', models.JSONField(default=dict)),
                ('text', models.TextField(default='')),
                ('model', models.TextField(default='')),
                ('created_at', models.FloatField()),
            ],
            options={
                'db_table': 'page_definitions',
                'indexes': [models.Index(fields=['owner_id', 'org_id', 'rel', 'id'], name='page_definitions_page')],
            },
        ),
    ]
