"""Mutations, called the Gene library until 14 October 2026, keeps no "library" inside either.

Petar, 14 October 2026 (fr_a982710d30c7): "Gene library competes as name so it should be
renamed to mutations", and then: "Do not keep the internal evolution/library. Make it into
evolution/mutations." So:

* its two tables are `mutations_genes` and `mutations_gene_events` (were `library_genes` and
  `library_gene_events`), with their constraint and indexes named the same way, and the gene
  log's column for a nightly gene's key is `mutations_key` (was `library_key`);
* its gene manifest's id is `mutations` (was `gene-library`), so everything kept under that id
  moves with it: its gene in the gene log and every sub-gene of it (`gene-library.2` becomes
  `mutations.2`), its use, marks and evaluations, the presses of its link in Settings, Stats,
  and the event log's presses of it (`nav:gene-library`). A day's count already under the new
  id, from the hours the link was called Mutations, is added to, never lost.

Nothing is thrown away. Going back renames everything to what it was.
"""
from django.db import migrations, models

OLD, NEW = "gene-library", "mutations"


def _keys(old: str, new: str) -> str:
    """Every row kept under one gene id, moved to another. A key already taken is left as it is."""
    return f"""
UPDATE gene_log g SET key = '{new}' || substr(g.key, {len(old) + 1})
 WHERE (g.key = '{old}' OR g.key LIKE '{old}.%')
   AND NOT EXISTS (SELECT 1 FROM gene_log t WHERE t.org_id = g.org_id
                    AND t.key = '{new}' || substr(g.key, {len(old) + 1}));
UPDATE gene_log SET manifest = '{new}' WHERE manifest = '{old}';
UPDATE gene_log SET made_by = 'its gene manifest, {new}.json' WHERE made_by = 'its gene manifest, {old}.json';
UPDATE gene_use_daily u SET gene_key = '{new}' WHERE gene_key = '{old}'
   AND NOT EXISTS (SELECT 1 FROM gene_use_daily t WHERE t.org_id = u.org_id AND t.user_id = u.user_id
                    AND t.gene_key = '{new}' AND t.day = u.day);
UPDATE gene_marks u SET gene_key = '{new}' WHERE gene_key = '{old}'
   AND NOT EXISTS (SELECT 1 FROM gene_marks t WHERE t.org_id = u.org_id AND t.user_id = u.user_id
                    AND t.gene_key = '{new}');
UPDATE gene_evals u SET gene_key = '{new}' WHERE gene_key = '{old}'
   AND NOT EXISTS (SELECT 1 FROM gene_evals t WHERE t.org_id = u.org_id AND t.user_id = u.user_id
                    AND t.gene_key = '{new}' AND t.month = u.month);
UPDATE nav_taps SET item = '{new}' WHERE item = '{old}';
UPDATE analytics.event SET object_id = 'nav:{new}' WHERE object_type = 'control' AND object_id = 'nav:{old}';
INSERT INTO analytics.object_daily (org_id, user_id, day, name, object_type, object_id, n, last_at)
SELECT org_id, user_id, day, name, object_type, 'nav:{new}', n, last_at FROM analytics.object_daily
 WHERE object_type = 'control' AND object_id = 'nav:{old}'
ON CONFLICT (org_id, user_id, day, name, object_type, object_id)
DO UPDATE SET n = analytics.object_daily.n + EXCLUDED.n,
              last_at = greatest(analytics.object_daily.last_at, EXCLUDED.last_at);
DELETE FROM analytics.object_daily WHERE object_type = 'control' AND object_id = 'nav:{old}';
"""


def _names(old: str, new: str) -> str:
    """The primary keys and id sequences of the two tables, under the tables' own names."""
    return "".join(f"ALTER INDEX IF EXISTS {old}_{t}_pkey RENAME TO {new}_{t}_pkey;\n"
                   f"ALTER SEQUENCE IF EXISTS {old}_{t}_id_seq RENAME TO {new}_{t}_id_seq;\n"
                   for t in ("genes", "gene_events"))


class Migration(migrations.Migration):

    dependencies = [
        ('rouh', '0149_shipping_options'),
    ]

    operations = [
        migrations.RenameModel(old_name='LibraryGene', new_name='MutationsGene'),
        migrations.RenameModel(old_name='LibraryGeneEvent', new_name='MutationsGeneEvent'),
        migrations.AlterModelTable(name='mutationsgene', table='mutations_genes'),
        migrations.AlterModelTable(name='mutationsgeneevent', table='mutations_gene_events'),
        migrations.RenameIndex(model_name='mutationsgene', new_name='mutations_gene_whose',
                               old_name='library_gene_whose'),
        migrations.RenameIndex(model_name='mutationsgeneevent', new_name='mutations_gene_event_whose',
                               old_name='library_gene_event_whose'),
        # A unique constraint has no rename of its own in Django: the database's is renamed in
        # place, and Django's record of it follows.
        migrations.SeparateDatabaseAndState(
            database_operations=[migrations.RunSQL(
                "ALTER TABLE mutations_genes RENAME CONSTRAINT library_gene_one TO mutations_gene_one;",
                "ALTER TABLE mutations_genes RENAME CONSTRAINT mutations_gene_one TO library_gene_one;")],
            state_operations=[
                migrations.RemoveConstraint(model_name='mutationsgene', name='library_gene_one'),
                migrations.AddConstraint(model_name='mutationsgene', constraint=models.UniqueConstraint(
                    fields=('org_id', 'user_id', 'key', 'version'), name='mutations_gene_one')),
            ]),
        # And what PostgreSQL named after the tables when they were made: their keys and their ids.
        migrations.RunSQL(_names("library", "mutations"), _names("mutations", "library")),
        migrations.RenameField(model_name='geneloggene',
                               old_name='library_key', new_name='mutations_key'),
        migrations.RunSQL(_keys(OLD, NEW), _keys(NEW, OLD)),
    ]
