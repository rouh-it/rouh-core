"""ParadeDB's BM25 index over the passages, where PostgreSQL loads pg_search (card 1125, change 1).

On 4 October 2026 Petar had Rouh's PostgreSQL restarted with shared_preload_libraries = pg_search
and the extension installed by its superuser (it creates C functions, which Rouh's own user may not).
This adds what the words list's `pg_search` backend reads (`search._words_pg_search`): a column of
each passage's word forms, the same English, Bulgarian and plain forms the GIN index holds, every
form as often as the passage uses it (`synapse.lexeme_text`), and a BM25 index over it with the
dataset, readers and kind as whole values, so every filter is answered inside the index.

Both are derived from `words` and rebuilt by dropping them. Where the extension is not installed (a
test database, a laptop), or is installed and not loaded, nothing is added and the words list ranks
with `bm25`. Whether it is loaded is not asked: only a privileged role may read that setting.
"""
from django.db import migrations

SCHEMA = r"""
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_search') THEN
    BEGIN
      CREATE OR REPLACE FUNCTION synapse.lexeme_text(v tsvector) RETURNS text LANGUAGE sql IMMUTABLE PARALLEL SAFE AS
        $fn$ SELECT coalesce(string_agg(repeat(u.lexeme || ' ', coalesce(array_length(u.positions, 1), 1)), ''), '')
             FROM unnest(v) u $fn$;
      ALTER TABLE synapse.passage ADD COLUMN IF NOT EXISTS lexemes text GENERATED ALWAYS AS (synapse.lexeme_text(words)) STORED;
      IF to_regclass('synapse.passage_bm25') IS NULL THEN
        CREATE INDEX passage_bm25 ON synapse.passage USING bm25 (id, (lexemes::pdb.whitespace), dataset_id,
          (can_read::pdb.literal), (kind::pdb.literal), said_at, item_id);
      END IF;
    EXCEPTION WHEN others THEN
      -- Installed but not loaded (shared_preload_libraries), say: nothing is added, words rank by bm25.
      RAISE NOTICE 'pg_search is installed but could not be used, so no BM25 index: %', SQLERRM;
    END;
  END IF;
END $$;
"""

UNDO = r"""
DROP INDEX IF EXISTS synapse.passage_bm25;
ALTER TABLE synapse.passage DROP COLUMN IF EXISTS lexemes;
DROP FUNCTION IF EXISTS synapse.lexeme_text(tsvector);
"""


class Migration(migrations.Migration):

    dependencies = [("rouh", "0077_chat_fork_cut")]

    operations = [migrations.RunSQL(SCHEMA, UNDO)]
