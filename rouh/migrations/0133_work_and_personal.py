"""Work and personal: a label on every item of Synapse, and what each trusted contact may see (12 October 2026).

Petar approved card 1499, "Splitting work and personal: a proposal", with "Do it". The first step is one
memory and one Rouh, with a work or personal label on things (`rouh/scopes.py`):

- **`synapse.item.scope`**: work, personal, both or unknown, its own field beside sensitivity and area,
  with who set it (`scope_by`: source, model or person) and why (`scope_why`). Every item starts unknown;
  the syncs fill in what their source decides (a task's project column, a calendar, a meeting), and the
  X-ray call fills in the rest as it reads an item, in the call it already makes.
- **Who may read it, by side** (`can_read`). An item that is work, personal or both also carries each of
  its readers once more under that side, `work:<reader>` or `personal:<reader>`, so a reader limited to
  one side asks with sided principals only (`work:<owner>`, `work:everyone`) and the filter is still the
  one column of the row being scanned that every search already uses (`search.readable_sql`). Unknown
  carries no sided readers, so it is out of reach of anybody limited to a side, which is the rule for it;
  so is anything special or unlabelled. `synapse.unscoped` is the same rule for the checks made once per
  result against `synapse.reader` (`search.readable_rule_sql`).
- **`trusted_contacts.sees`**: work, personal or both, what Rouh may bring up for a trusted contact. Work
  for everybody. On the installation it was written for, two contacts the owner had named were given
  both sides, and their people in Synapse were labelled both; those choices were that owner's own, live
  only in that installation's database, and are not made anywhere else, so those two steps do nothing.
"""
from django.db import migrations, models

SCHEMA = r"""
ALTER TABLE synapse.item ADD COLUMN IF NOT EXISTS scope text NOT NULL DEFAULT 'unknown';
ALTER TABLE synapse.item ADD COLUMN IF NOT EXISTS scope_by text NOT NULL DEFAULT '';
ALTER TABLE synapse.item ADD COLUMN IF NOT EXISTS scope_why text NOT NULL DEFAULT '';
DO $$ BEGIN
  ALTER TABLE synapse.item ADD CONSTRAINT item_scope_known
    CHECK (scope IN ('work', 'personal', 'both', 'unknown'));
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
CREATE INDEX IF NOT EXISTS item_scope ON synapse.item (dataset_id, scope) WHERE deleted_at IS NULL;

-- Each reader again under the item's side: `work:<reader>`, `personal:<reader>`, both for both.
CREATE OR REPLACE FUNCTION synapse.can_read_for(ds uuid, it uuid, sens text, own text, sc text)
RETURNS text[] LANGUAGE sql STABLE AS $$
  WITH base AS (SELECT synapse.can_read_for(ds, it, sens, own) AS b)
  SELECT CASE WHEN sens IN ('special', 'unlabelled') OR coalesce(sc, '') NOT IN ('work', 'personal', 'both')
              THEN b
              ELSE b || coalesce((SELECT array_agg(side || ':' || p ORDER BY side, p) FROM unnest(b) p,
                                  unnest(CASE sc WHEN 'both' THEN ARRAY['personal', 'work'] ELSE ARRAY[sc] END) side),
                                 '{}'::text[]) END
  FROM base
$$;

-- An asker's principals as `synapse.reader` holds them, for an item of side `sc`: a plain one as it is,
-- a sided one without its side when the item is on that side, and dropped when it is not.
CREATE OR REPLACE FUNCTION synapse.unscoped(p text[], sc text) RETURNS text[] LANGUAGE sql IMMUTABLE AS $$
  SELECT coalesce(array_agg(y), '{}'::text[]) FROM (
    SELECT CASE WHEN x LIKE 'work:%' THEN CASE WHEN sc IN ('work', 'both') THEN substr(x, 6) END
                WHEN x LIKE 'personal:%' THEN CASE WHEN sc IN ('personal', 'both') THEN substr(x, 10) END
                ELSE x END AS y
    FROM unnest(p) x) z WHERE y IS NOT NULL
$$;

CREATE OR REPLACE FUNCTION synapse.item_can_read() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  NEW.can_read := synapse.can_read_for(NEW.dataset_id, NEW.id, NEW.sensitivity, NEW.owner, NEW.scope);
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS item_can_read ON synapse.item;
CREATE TRIGGER item_can_read BEFORE INSERT OR UPDATE OF sensitivity, owner, scope ON synapse.item
  FOR EACH ROW EXECUTE FUNCTION synapse.item_can_read();

CREATE OR REPLACE FUNCTION synapse.reader_changed() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE r record;
BEGIN
  IF TG_OP = 'DELETE' THEN r := OLD; ELSE r := NEW; END IF;
  UPDATE synapse.item i SET can_read = synapse.can_read_for(i.dataset_id, i.id, i.sensitivity, i.owner, i.scope)
   WHERE i.dataset_id = r.dataset_id AND i.id = r.item_id;
  RETURN NULL;
END $$;
"""

UNDO = r"""
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
UPDATE synapse.item SET can_read = synapse.can_read_for(dataset_id, id, sensitivity, owner)
 WHERE can_read::text LIKE '%work:%' OR can_read::text LIKE '%personal:%';
DROP FUNCTION IF EXISTS synapse.unscoped(text[], text);
DROP FUNCTION IF EXISTS synapse.can_read_for(uuid, uuid, text, text, text);
DROP INDEX IF EXISTS synapse.item_scope;
ALTER TABLE synapse.item DROP CONSTRAINT IF EXISTS item_scope_known;
ALTER TABLE synapse.item DROP COLUMN IF EXISTS scope_why;
ALTER TABLE synapse.item DROP COLUMN IF EXISTS scope_by;
ALTER TABLE synapse.item DROP COLUMN IF EXISTS scope;
"""

class Migration(migrations.Migration):

    dependencies = [("rouh", "0132_shared_genes")]

    operations = [
        migrations.RunSQL(SCHEMA, UNDO),
        migrations.AddField(
            model_name="trustedcontact",
            name="sees",
            field=models.TextField(default="work", db_default="work"),
        ),
        # Once: one named contact given both sides. Now nothing (see above).
        migrations.RunSQL(migrations.RunSQL.noop, migrations.RunSQL.noop),
        # Once: two named people in Synapse labelled both. Now nothing (see above).
        migrations.RunSQL(migrations.RunSQL.noop, migrations.RunSQL.noop),
    ]
