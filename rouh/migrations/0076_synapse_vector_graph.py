"""The passages' vector index built with more links per node: m 32, ef_construction 128 (card 1125).

Measured 4 October 2026 by synapse_bench at 1,000,000 fictional items: with pgvector's defaults (m 16,
ef_construction 64) a meaning-only question found its own item 65% of the time even searching 100
deep, a reader who sees 12% 45%, and a link found by meaning alone 1 in 10; built again with these
settings, 100%, 95% and 10 in 10, ranking cases 81.5% to 94.1%, link candidates' recall 89.4% to
100%, search p95 119 ms and link candidates p95 49 ms. The index is the same size (3.6 GB at that
scale) and takes 4.5 times as long to build (81 minutes there, 18 before). It is derived from the
passages and is rebuilt here only when it does not already have these settings.
"""
from django.db import migrations

SCHEMA = r"""
DO $$
BEGIN
  IF to_regclass('synapse.passage_vec') IS NULL
     OR pg_get_indexdef('synapse.passage_vec'::regclass) NOT LIKE '%m=''32''%' THEN
    DROP INDEX IF EXISTS synapse.passage_vec;
    CREATE INDEX passage_vec ON synapse.passage USING hnsw (vec halfvec_cosine_ops) WITH (m = 32, ef_construction = 128);
  END IF;
END $$;
"""

UNDO = r"""
DROP INDEX IF EXISTS synapse.passage_vec;
CREATE INDEX passage_vec ON synapse.passage USING hnsw (vec halfvec_cosine_ops);
"""


class Migration(migrations.Migration):

    dependencies = [("rouh", "0075_synapse_area_counts")]

    operations = [migrations.RunSQL(SCHEMA, UNDO)]
