"""Areas counted as items come and go, so an X-ray reads them in a few rows (card 1125, change 5).

Measured 4 October 2026 by synapse_bench at 1,000,000 fictional items: every X-ray call counted the
dataset's areas and proposed areas by reading all its items (`ingest.area_list`), 0.4 s on a quiet
machine and over a second with four workers, so the queue slowed as the dataset grew, to 3 items a
second. `synapse.area_count` holds each area's count, real or still proposed, kept by a trigger on
`synapse.item` as the old query counted it (not deleted, not a person, topic, layer or rule; real
when it has an area, waiting when it has only a proposal), and the X-ray reads its top rows.
The area step's two lookups by one area's name get indexes of their own.
"""
from django.db import migrations

SCHEMA = r"""
CREATE TABLE IF NOT EXISTS synapse.area_count (
  dataset_id  uuid NOT NULL REFERENCES synapse.dataset(id) ON DELETE CASCADE,
  state       text NOT NULL,            -- 'real' or 'waiting' (proposed, not yet real)
  key         text NOT NULL,            -- the name, lower case
  name        text NOT NULL,            -- as first written
  items       integer NOT NULL,
  PRIMARY KEY (dataset_id, state, key)
);
CREATE INDEX IF NOT EXISTS area_count_top ON synapse.area_count (dataset_id, state, items DESC);

CREATE OR REPLACE FUNCTION synapse.area_counted() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE o_state text; o_name text; n_state text; n_name text; o_key text; n_key text;
BEGIN
  IF TG_OP <> 'INSERT' AND OLD.deleted_at IS NULL AND OLD.kind NOT IN ('person', 'topic', 'layer', 'rule') THEN
    IF coalesce(OLD.meta->>'area', '') <> '' THEN o_state := 'real'; o_name := OLD.meta->>'area';
    ELSIF coalesce(OLD.meta->>'area_proposed', '') <> '' THEN o_state := 'waiting'; o_name := OLD.meta->>'area_proposed';
    END IF;
  END IF;
  IF TG_OP <> 'DELETE' AND NEW.deleted_at IS NULL AND NEW.kind NOT IN ('person', 'topic', 'layer', 'rule') THEN
    IF coalesce(NEW.meta->>'area', '') <> '' THEN n_state := 'real'; n_name := NEW.meta->>'area';
    ELSIF coalesce(NEW.meta->>'area_proposed', '') <> '' THEN n_state := 'waiting'; n_name := NEW.meta->>'area_proposed';
    END IF;
  END IF;
  o_key := lower(o_name); n_key := lower(n_name);
  IF o_state IS NOT DISTINCT FROM n_state AND o_key IS NOT DISTINCT FROM n_key THEN
    RETURN NULL;
  END IF;
  -- Two rows in key order, so two items moving opposite ways never wait on each other.
  IF n_state IS NOT NULL AND (o_state IS NULL OR (n_state, n_key) < (o_state, o_key)) THEN
    INSERT INTO synapse.area_count AS c VALUES (NEW.dataset_id, n_state, n_key, n_name, 1)
      ON CONFLICT (dataset_id, state, key) DO UPDATE SET items = c.items + 1;
    n_state := NULL;
  END IF;
  IF o_state IS NOT NULL THEN
    UPDATE synapse.area_count SET items = items - 1 WHERE dataset_id = OLD.dataset_id AND state = o_state AND key = o_key;
  END IF;
  IF n_state IS NOT NULL THEN
    INSERT INTO synapse.area_count AS c VALUES (NEW.dataset_id, n_state, n_key, n_name, 1)
      ON CONFLICT (dataset_id, state, key) DO UPDATE SET items = c.items + 1;
  END IF;
  RETURN NULL;
END $$;
DROP TRIGGER IF EXISTS area_counted ON synapse.item;
CREATE TRIGGER area_counted AFTER INSERT OR DELETE OR UPDATE OF meta, deleted_at, kind ON synapse.item
  FOR EACH ROW EXECUTE FUNCTION synapse.area_counted();

DELETE FROM synapse.area_count;
INSERT INTO synapse.area_count
SELECT dataset_id, state, key, min(name), count(*) FROM (
  SELECT dataset_id,
         CASE WHEN coalesce(meta->>'area', '') <> '' THEN 'real' ELSE 'waiting' END AS state,
         lower(coalesce(nullif(meta->>'area', ''), meta->>'area_proposed')) AS key,
         coalesce(nullif(meta->>'area', ''), meta->>'area_proposed') AS name
  FROM synapse.item WHERE deleted_at IS NULL AND kind NOT IN ('person', 'topic', 'layer', 'rule')
  AND (coalesce(meta->>'area', '') <> '' OR coalesce(meta->>'area_proposed', '') <> '')) x
GROUP BY 1, 2, 3;

CREATE INDEX IF NOT EXISTS item_area ON synapse.item (dataset_id, lower(meta->>'area'), stored_at)
  WHERE deleted_at IS NULL AND coalesce(meta->>'area', '') <> '';
CREATE INDEX IF NOT EXISTS item_area_proposed ON synapse.item (dataset_id, lower(meta->>'area_proposed'))
  WHERE deleted_at IS NULL AND coalesce(meta->>'area', '') = '' AND coalesce(meta->>'area_proposed', '') <> '';
"""

UNDO = r"""
DROP INDEX IF EXISTS synapse.item_area_proposed;
DROP INDEX IF EXISTS synapse.item_area;
DROP TRIGGER IF EXISTS area_counted ON synapse.item;
DROP FUNCTION IF EXISTS synapse.area_counted();
DROP TABLE IF EXISTS synapse.area_count;
"""


class Migration(migrations.Migration):

    dependencies = [("rouh", "0074_synapse_job_per_item")]

    operations = [migrations.RunSQL(SCHEMA, UNDO)]
