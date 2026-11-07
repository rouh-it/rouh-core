"""Synapse at 10,000 items now and 100,000 later: every step costs what the answer costs.

Petar, by voice on 3 October 2026: make the lab ready for real use at that size,
by one rule, that every step costs in proportion to the size of the answer (top
k) and never to the size of the dataset. What that needs in the database:

- **Who may read an item, stored** (`can_read`). The principals whose questions
  may reach it, worked out by the same rule `search.readable_sql` always used
  (its readers, and only its owner while it is special or unlabelled), kept on
  the item and copied onto each of its passages, by triggers on `reader` and
  `item`, so nothing in Python can forget to. Search filters on it inside the
  indexed scan instead of asking `reader` once per candidate row.
- **The passage carries its item's kind and date** (`kind`, `said_at`), for the
  same reason, and so a search can start with recent items (time-led index).
- **How many passages hold each word** (`term_count`), per dataset, with
  lexeme '' holding the count of passages. Search reads it to rank by rarity
  (BM25's idf) and to take its candidates from the rarest words' short lists in
  the GIN index; a new item's link candidates are searched with its 5 to 10
  rarest words, never its text. Statement triggers on `passage` only ever
  append to `term_delta` (+1 a passage written, -1 one removed), so sixteen
  items stored at once never wait on each other or deadlock over a common word;
  `synapse.term_fold()`, run by one worker at a time, folds the deltas into
  `term_df`, and `term_count` is the two added up. Passage words are only ever
  written by INSERT (an edit replaces the passages), so there is no UPDATE
  trigger.
- **Indexes for the structure lookups** of link candidates (same thread, files
  attached), and for today's spend of a dataset (the import's daily cap).
- **Two lanes on the queue** (`job.lane`): live work and backfill, so a big
  import never takes a slot live mail needs, and `started_at`, so Activity can
  say when a queued step ran.
"""
from django.db import migrations

SCHEMA = r"""
ALTER TABLE synapse.item ADD COLUMN IF NOT EXISTS can_read text[] NOT NULL DEFAULT '{}';
ALTER TABLE synapse.passage ADD COLUMN IF NOT EXISTS can_read text[] NOT NULL DEFAULT '{}';
ALTER TABLE synapse.passage ADD COLUMN IF NOT EXISTS kind text NOT NULL DEFAULT '';
ALTER TABLE synapse.passage ADD COLUMN IF NOT EXISTS said_at timestamptz;

-- The rule of search.readable_sql, as a value: its readers, and while it is special or
-- unlabelled only its owner, and only when the owner (or everyone) is one of its readers.
CREATE OR REPLACE FUNCTION synapse.can_read_for(ds uuid, it uuid, sens text, own text)
RETURNS text[] LANGUAGE sql STABLE AS $$
  SELECT CASE WHEN sens IN ('special', 'unlabelled') THEN
           CASE WHEN own <> '' AND EXISTS (SELECT 1 FROM synapse.reader r WHERE r.dataset_id = ds
                                           AND r.item_id = it AND r.principal IN (own, 'everyone'))
                THEN ARRAY[own] ELSE '{}'::text[] END
         ELSE coalesce((SELECT array_agg(r.principal ORDER BY r.principal) FROM synapse.reader r
                        WHERE r.dataset_id = ds AND r.item_id = it), '{}'::text[]) END
$$;

CREATE OR REPLACE FUNCTION synapse.item_can_read() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  NEW.can_read := synapse.can_read_for(NEW.dataset_id, NEW.id, NEW.sensitivity, NEW.owner);
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS item_can_read ON synapse.item;
CREATE TRIGGER item_can_read BEFORE INSERT OR UPDATE OF sensitivity, owner ON synapse.item
  FOR EACH ROW EXECUTE FUNCTION synapse.item_can_read();

CREATE OR REPLACE FUNCTION synapse.reader_changed() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE r record;
BEGIN
  IF TG_OP = 'DELETE' THEN r := OLD; ELSE r := NEW; END IF;
  UPDATE synapse.item i SET can_read = synapse.can_read_for(i.dataset_id, i.id, i.sensitivity, i.owner)
   WHERE i.dataset_id = r.dataset_id AND i.id = r.item_id;
  RETURN NULL;
END $$;
DROP TRIGGER IF EXISTS reader_changed ON synapse.reader;
CREATE TRIGGER reader_changed AFTER INSERT OR DELETE ON synapse.reader
  FOR EACH ROW EXECUTE FUNCTION synapse.reader_changed();

CREATE OR REPLACE FUNCTION synapse.item_to_passages() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  UPDATE synapse.passage p SET can_read = NEW.can_read, kind = NEW.kind, said_at = NEW.said_at
   WHERE p.dataset_id = NEW.dataset_id AND p.item_id = NEW.id;
  RETURN NULL;
END $$;
DROP TRIGGER IF EXISTS item_to_passages ON synapse.item;
CREATE TRIGGER item_to_passages AFTER UPDATE ON synapse.item FOR EACH ROW
  WHEN (OLD.can_read IS DISTINCT FROM NEW.can_read OR OLD.kind IS DISTINCT FROM NEW.kind
        OR OLD.said_at IS DISTINCT FROM NEW.said_at)
  EXECUTE FUNCTION synapse.item_to_passages();

CREATE OR REPLACE FUNCTION synapse.passage_from_item() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE i record;
BEGIN
  SELECT it.can_read, it.kind, it.said_at INTO i FROM synapse.item it
   WHERE it.dataset_id = NEW.dataset_id AND it.id = NEW.item_id;
  NEW.can_read := coalesce(i.can_read, '{}'::text[]);
  NEW.kind := coalesce(i.kind, '');
  NEW.said_at := i.said_at;
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS passage_from_item ON synapse.passage;
CREATE TRIGGER passage_from_item BEFORE INSERT ON synapse.passage
  FOR EACH ROW EXECUTE FUNCTION synapse.passage_from_item();

-- How many passages of a dataset hold each lexeme; lexeme '' is the number of passages.
CREATE TABLE IF NOT EXISTS synapse.term_df (
  scope_id  uuid NOT NULL REFERENCES synapse.dataset(id) ON DELETE CASCADE,
  lexeme    text NOT NULL,
  df        integer NOT NULL,
  PRIMARY KEY (scope_id, lexeme)
);
-- What changed since the last fold: appended to, never updated, so writers never wait on each other.
CREATE TABLE IF NOT EXISTS synapse.term_delta (
  scope_id  uuid NOT NULL REFERENCES synapse.dataset(id) ON DELETE CASCADE,
  lexeme    text NOT NULL,
  n         integer NOT NULL
);
CREATE INDEX IF NOT EXISTS term_delta_of ON synapse.term_delta (scope_id, lexeme);
CREATE OR REPLACE VIEW synapse.term_count AS
  SELECT scope_id, lexeme, sum(df)::int AS df FROM (
    SELECT scope_id, lexeme, df FROM synapse.term_df
    UNION ALL SELECT scope_id, lexeme, n FROM synapse.term_delta) x
  GROUP BY scope_id, lexeme;

-- One word's count in some datasets: two index lookups, whatever the size. Searches call this per
-- word; a join on the view would add up every word of the dataset first.
CREATE OR REPLACE FUNCTION synapse.df(scopes uuid[], lex text) RETURNS integer LANGUAGE sql STABLE AS $$
  SELECT (coalesce((SELECT sum(df) FROM synapse.term_df WHERE scope_id = ANY(scopes) AND lexeme = lex), 0)
        + coalesce((SELECT sum(n) FROM synapse.term_delta WHERE scope_id = ANY(scopes) AND lexeme = lex), 0))::int
$$;

CREATE OR REPLACE FUNCTION synapse.term_df_added() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  INSERT INTO synapse.term_delta (scope_id, lexeme, n)
  SELECT dataset_id, lexeme, count(*) FROM (
    SELECT a.dataset_id, u.lexeme FROM added a, unnest(a.words) u
    UNION ALL SELECT a.dataset_id, '' FROM added a) x
  GROUP BY 1, 2;
  RETURN NULL;
END $$;
DROP TRIGGER IF EXISTS term_df_added ON synapse.passage;
CREATE TRIGGER term_df_added AFTER INSERT ON synapse.passage REFERENCING NEW TABLE AS added
  FOR EACH STATEMENT EXECUTE FUNCTION synapse.term_df_added();

CREATE OR REPLACE FUNCTION synapse.term_df_gone() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  INSERT INTO synapse.term_delta (scope_id, lexeme, n)
  SELECT dataset_id, lexeme, -count(*) FROM (
    SELECT o.dataset_id, u.lexeme FROM gone o, unnest(o.words) u
    UNION ALL SELECT o.dataset_id, '' FROM gone o) x
  WHERE EXISTS (SELECT 1 FROM synapse.dataset d WHERE d.id = x.dataset_id)
  GROUP BY 1, 2;
  RETURN NULL;
END $$;
DROP TRIGGER IF EXISTS term_df_gone ON synapse.passage;
CREATE TRIGGER term_df_gone AFTER DELETE ON synapse.passage REFERENCING OLD TABLE AS gone
  FOR EACH STATEMENT EXECUTE FUNCTION synapse.term_df_gone();

-- The deltas folded into term_df, by one caller at a time (the others return at once). Sorted, so
-- the fold never deadlocks with itself; returns how many delta rows it folded.
CREATE OR REPLACE FUNCTION synapse.term_fold() RETURNS integer LANGUAGE plpgsql AS $$
DECLARE moved integer;
BEGIN
  IF NOT pg_try_advisory_xact_lock(hashtext('synapse.term_fold')) THEN
    RETURN 0;
  END IF;
  WITH gone AS (DELETE FROM synapse.term_delta RETURNING scope_id, lexeme, n),
  summed AS (SELECT scope_id, lexeme, sum(n)::int AS n, count(*) AS rows FROM gone GROUP BY 1, 2),
  put AS (INSERT INTO synapse.term_df AS t (scope_id, lexeme, df)
          SELECT s.scope_id, s.lexeme, s.n FROM summed s
          WHERE EXISTS (SELECT 1 FROM synapse.dataset d WHERE d.id = s.scope_id) ORDER BY 1, 2
          ON CONFLICT (scope_id, lexeme) DO UPDATE SET df = t.df + excluded.df RETURNING 1)
  SELECT coalesce(sum(rows), 0) INTO moved FROM summed;
  DELETE FROM synapse.term_df WHERE df <= 0 AND lexeme <> '';
  RETURN moved;
END $$;

-- What is there already.
UPDATE synapse.item i SET can_read = synapse.can_read_for(i.dataset_id, i.id, i.sensitivity, i.owner);
UPDATE synapse.passage p SET can_read = i.can_read, kind = i.kind, said_at = i.said_at
  FROM synapse.item i WHERE i.dataset_id = p.dataset_id AND i.id = p.item_id;
DELETE FROM synapse.term_df;
DELETE FROM synapse.term_delta;
INSERT INTO synapse.term_df (scope_id, lexeme, df)
SELECT dataset_id, lexeme, count(*) FROM (
  SELECT p.dataset_id, u.lexeme FROM synapse.passage p, unnest(p.words) u
  UNION ALL SELECT p.dataset_id, '' FROM synapse.passage p) x
GROUP BY 1, 2;

CREATE INDEX IF NOT EXISTS item_can_read ON synapse.item USING gin (can_read);
CREATE INDEX IF NOT EXISTS passage_said ON synapse.passage (dataset_id, said_at DESC);
CREATE INDEX IF NOT EXISTS item_thread ON synapse.item (dataset_id, (meta->>'thread'));
CREATE INDEX IF NOT EXISTS item_attached_to ON synapse.item USING gin ((meta->'attached_to'));
CREATE INDEX IF NOT EXISTS call_day ON synapse.call (dataset_id, at);

ALTER TABLE synapse.job ADD COLUMN IF NOT EXISTS lane text NOT NULL DEFAULT 'live';
ALTER TABLE synapse.job ADD COLUMN IF NOT EXISTS started_at timestamptz;
CREATE INDEX IF NOT EXISTS job_lane ON synapse.job (lane, priority, not_before) WHERE done_at IS NULL;
CREATE INDEX IF NOT EXISTS job_trace ON synapse.job (trace_id);
"""

UNDO = r"""
DROP INDEX IF EXISTS synapse.job_trace;
DROP INDEX IF EXISTS synapse.job_lane;
ALTER TABLE synapse.job DROP COLUMN IF EXISTS started_at;
ALTER TABLE synapse.job DROP COLUMN IF EXISTS lane;
DROP INDEX IF EXISTS synapse.call_day;
DROP INDEX IF EXISTS synapse.item_attached_to;
DROP INDEX IF EXISTS synapse.item_thread;
DROP INDEX IF EXISTS synapse.passage_said;
DROP INDEX IF EXISTS synapse.item_can_read;
DROP TRIGGER IF EXISTS term_df_gone ON synapse.passage;
DROP TRIGGER IF EXISTS term_df_added ON synapse.passage;
DROP FUNCTION IF EXISTS synapse.term_fold();
DROP FUNCTION IF EXISTS synapse.term_df_gone();
DROP FUNCTION IF EXISTS synapse.term_df_added();
DROP VIEW IF EXISTS synapse.term_count;
DROP FUNCTION IF EXISTS synapse.df(uuid[], text);
DROP TABLE IF EXISTS synapse.term_delta;
DROP TABLE IF EXISTS synapse.term_df;
DROP TRIGGER IF EXISTS passage_from_item ON synapse.passage;
DROP TRIGGER IF EXISTS item_to_passages ON synapse.item;
DROP TRIGGER IF EXISTS reader_changed ON synapse.reader;
DROP TRIGGER IF EXISTS item_can_read ON synapse.item;
DROP FUNCTION IF EXISTS synapse.passage_from_item();
DROP FUNCTION IF EXISTS synapse.item_to_passages();
DROP FUNCTION IF EXISTS synapse.reader_changed();
DROP FUNCTION IF EXISTS synapse.item_can_read();
DROP FUNCTION IF EXISTS synapse.can_read_for(uuid, uuid, text, text);
ALTER TABLE synapse.passage DROP COLUMN IF EXISTS said_at;
ALTER TABLE synapse.passage DROP COLUMN IF EXISTS kind;
ALTER TABLE synapse.passage DROP COLUMN IF EXISTS can_read;
ALTER TABLE synapse.item DROP COLUMN IF EXISTS can_read;
"""


class Migration(migrations.Migration):

    dependencies = [("rouh", "0070_synapse_mentions")]

    operations = [migrations.RunSQL(SCHEMA, UNDO)]
