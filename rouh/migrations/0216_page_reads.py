"""Since you last read it, version 2 (`rouh/since_read.py`): the owner's visits to a page, each with
the page's words as they were, so a page opened again can say whether it changed since.

Petar, 27 October 2026: "track if anything has changed since I last saw it, and if yes, then show me
a button that would generate those changes ... that means you save a version each time I visit in
the database".
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('rouh', '0215_gene_pool_incoming'),
    ]

    operations = [
        migrations.CreateModel(
            name='PageRead',
            fields=[
                ('id', models.BigAutoField(primary_key=True, serialize=False)),
                ('org_id', models.TextField()),
                ('user_id', models.TextField()),
                ('rel', models.TextField()),
                ('text', models.TextField(default='')),
                ('fp', models.TextField(default='')),
                ('first_at', models.FloatField()),
                ('seen_at', models.FloatField()),
                ('told_at', models.FloatField(blank=True, null=True)),
            ],
            options={
                'db_table': 'page_reads',
                'indexes': [models.Index(fields=['org_id', 'user_id', 'rel', '-seen_at'],
                                         name='page_reads_whose')],
            },
        ),
    ]
