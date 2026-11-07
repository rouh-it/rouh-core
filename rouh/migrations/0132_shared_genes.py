"""Shared genes: the gene registry an organisation points at, the genes in its lab, and the
lab's history (`rouh/genelab.py`).

Task 98, step 98-13: Rouh's receiving side of the gene registry. No row in gene_registries is
the lab off, so nothing here asks anybody anything until a person sets a registry and pins its
key in Settings, Genes.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('rouh', '0131_nav_tap_visit'),
    ]

    operations = [
        migrations.CreateModel(
            name='GeneLabEvent',
            fields=[
                ('id', models.BigAutoField(primary_key=True, serialize=False)),
                ('org_id', models.TextField()),
                ('gene', models.TextField()),
                ('version', models.TextField(blank=True, default='')),
                ('what', models.TextField()),
                ('said', models.TextField(blank=True, default='')),
                ('by', models.TextField(blank=True, default='')),
                ('detail', models.JSONField(blank=True, default=dict)),
                ('at', models.FloatField()),
            ],
            options={
                'db_table': 'gene_lab_events',
                'indexes': [models.Index(fields=['org_id', 'at'], name='gene_lab_events_when')],
            },
        ),
        migrations.CreateModel(
            name='GeneRegistry',
            fields=[
                ('id', models.BigAutoField(primary_key=True, serialize=False)),
                ('org_id', models.TextField()),
                ('url', models.TextField(blank=True, default='')),
                ('public_key', models.TextField(blank=True, default='')),
                ('key_id', models.TextField(blank=True, default='')),
                ('set_by', models.TextField(blank=True, default='')),
                ('set_at', models.FloatField(default=0)),
                ('index', models.JSONField(blank=True, default=dict)),
                ('blocklist', models.JSONField(blank=True, default=dict)),
                ('index_made_at', models.TextField(blank=True, default='')),
                ('blocklist_made_at', models.TextField(blank=True, default='')),
                ('fetched_at', models.FloatField(default=0)),
                ('error', models.TextField(blank=True, default='')),
                ('error_at', models.FloatField(default=0)),
            ],
            options={
                'db_table': 'gene_registries',
                'constraints': [models.UniqueConstraint(fields=('org_id',), name='gene_registry_one')],
            },
        ),
        migrations.CreateModel(
            name='SharedGene',
            fields=[
                ('id', models.BigAutoField(primary_key=True, serialize=False)),
                ('org_id', models.TextField()),
                ('gene', models.TextField()),
                ('publisher', models.TextField()),
                ('name', models.TextField()),
                ('version', models.TextField()),
                ('kind', models.TextField(blank=True, default='')),
                ('contract', models.JSONField(default=dict)),
                ('contract_sha256', models.TextField()),
                ('listing', models.JSONField(blank=True, default=dict)),
                ('artifact_url', models.TextField()),
                ('artifact_sha256', models.TextField()),
                ('artifact', models.BinaryField()),
                ('files', models.JSONField(blank=True, default=list)),
                ('sigstore', models.JSONField(blank=True, default=dict)),
                ('switch', models.TextField()),
                ('state', models.TextField(default='lab')),
                ('blocked', models.JSONField(blank=True, default=dict)),
                ('update', models.JSONField(blank=True, default=dict)),
                ('before', models.JSONField(blank=True, default=dict)),
                ('installed_by', models.TextField(blank=True, default='')),
                ('installed_by_name', models.TextField(blank=True, default='')),
                ('installed_at', models.FloatField(default=0)),
                ('updated_at', models.FloatField(default=0)),
            ],
            options={
                'db_table': 'shared_genes',
                'constraints': [models.UniqueConstraint(fields=('org_id', 'gene'), name='shared_gene_one')],
            },
        ),
    ]
