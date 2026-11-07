"""Silos: the account's own parts of life, in place of the fixed work and personal label (12 October 2026).

Petar: "Make a silo setting in settings. This will control how many silos you have and what they are
called. Maybe a person has more than two." So (`rouh/silos.py`):

- **`silo`** and **`silo_rule`**: each account's silos (a stable key, a name, a colour, a place) and the
  source rules that label things by where they come from. An account's first read of its silos gives
  it Work and Personal, with the keys the fixed labels had (`work`, `personal`), and the rules they were
  worked out by (`silos._seed`), so nothing anybody sees or may see moves today.
- **`synapse.item.silos`**, a set of silo keys, in place of `scope`: work is {work}, personal
  {personal}, both {personal, work} and unknown empty. `scope_by` and `scope_why` are `silos_by` and
  `silos_why`. The sided readers stay as they were (`<key>:<reader>`, one for each silo the item is in),
  so `can_read` is the same value it was and only the functions that make it change.
- **`trusted_contacts.sees`**, a list of silo keys or nothing (the silos shown to others): work is
  [work], personal [personal] and both [work, personal], which is every silo, so no limit, as it was.
- **`reminders.silos`**: a Clockwork item's silos, empty until it is made in a chat or task of one.
"""
from django.db import migrations, models

SCHEMA = r"""
ALTER TABLE synapse.item ADD COLUMN IF NOT EXISTS silos text[] NOT NULL DEFAULT '{}';
UPDATE synapse.item SET silos = CASE scope WHEN 'work' THEN '{work}'::text[] WHEN 'personal' THEN '{personal}'::text[]
                                           WHEN 'both' THEN '{personal,work}'::text[] ELSE '{}'::text[] END
 WHERE scope <> 'unknown';
ALTER TABLE synapse.item RENAME COLUMN scope_by TO silos_by;
ALTER TABLE synapse.item RENAME COLUMN scope_why TO silos_why;

-- Each reader again under every silo the item is in: `<key>:<reader>`.
CREATE OR REPLACE FUNCTION synapse.can_read_for(ds uuid, it uuid, sens text, own text, sl text[])
RETURNS text[] LANGUAGE sql STABLE AS $$
  WITH base AS (SELECT synapse.can_read_for(ds, it, sens, own) AS b)
  SELECT CASE WHEN sens IN ('special', 'unlabelled') OR coalesce(cardinality(sl), 0) = 0 THEN b
              ELSE b || coalesce((SELECT array_agg(k || ':' || p ORDER BY k, p) FROM unnest(b) p,
                                  (SELECT DISTINCT unnest(sl) AS k) s), '{}'::text[]) END
  FROM base
$$;

CREATE OR REPLACE FUNCTION synapse.item_can_read() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
  NEW.can_read := synapse.can_read_for(NEW.dataset_id, NEW.id, NEW.sensitivity, NEW.owner, NEW.silos);
  RETURN NEW;
END $$;
DROP TRIGGER IF EXISTS item_can_read ON synapse.item;
CREATE TRIGGER item_can_read BEFORE INSERT OR UPDATE OF sensitivity, owner, silos ON synapse.item
  FOR EACH ROW EXECUTE FUNCTION synapse.item_can_read();

CREATE OR REPLACE FUNCTION synapse.reader_changed() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE r record;
BEGIN
  IF TG_OP = 'DELETE' THEN r := OLD; ELSE r := NEW; END IF;
  UPDATE synapse.item i SET can_read = synapse.can_read_for(i.dataset_id, i.id, i.sensitivity, i.owner, i.silos)
   WHERE i.dataset_id = r.dataset_id AND i.id = r.item_id;
  RETURN NULL;
END $$;

-- An asker's principals as `synapse.reader` holds them, for an item in silos `sl`: a plain one as it is
-- (an id, everyone, nobody:<name>), a sided one without its silo when the item is in that silo, and
-- dropped when it is not.
DROP FUNCTION IF EXISTS synapse.unscoped(text[], text);
CREATE OR REPLACE FUNCTION synapse.unscoped(p text[], sl text[]) RETURNS text[] LANGUAGE sql IMMUTABLE AS $$
  SELECT coalesce(array_agg(y), '{}'::text[]) FROM (
    SELECT CASE WHEN position(':' in x) = 0 OR split_part(x, ':', 1) = 'nobody' THEN x
                WHEN split_part(x, ':', 1) = ANY(coalesce(sl, '{}'::text[]))
                  THEN substr(x, length(split_part(x, ':', 1)) + 2) END AS y
    FROM unnest(p) x) z WHERE y IS NOT NULL
$$;

DROP FUNCTION IF EXISTS synapse.can_read_for(uuid, uuid, text, text, text);
DROP INDEX IF EXISTS synapse.item_scope;
ALTER TABLE synapse.item DROP CONSTRAINT IF EXISTS item_scope_known;
ALTER TABLE synapse.item DROP COLUMN IF EXISTS scope;
CREATE INDEX IF NOT EXISTS item_silos ON synapse.item USING gin (silos) WHERE deleted_at IS NULL;

-- The same value it was, made by the new function: nothing anybody may read moves.
UPDATE synapse.item i SET can_read = synapse.can_read_for(i.dataset_id, i.id, i.sensitivity, i.owner, i.silos)
 WHERE cardinality(i.silos) > 0;
"""

UNDO = r"""
ALTER TABLE synapse.item ADD COLUMN IF NOT EXISTS scope text NOT NULL DEFAULT 'unknown';
UPDATE synapse.item SET scope = CASE WHEN silos @> '{work,personal}' THEN 'both' WHEN silos @> '{work}' THEN 'work'
                                     WHEN silos @> '{personal}' THEN 'personal' ELSE 'unknown' END;
ALTER TABLE synapse.item RENAME COLUMN silos_by TO scope_by;
ALTER TABLE synapse.item RENAME COLUMN silos_why TO scope_why;
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
DROP FUNCTION IF EXISTS synapse.unscoped(text[], text[]);
CREATE OR REPLACE FUNCTION synapse.unscoped(p text[], sc text) RETURNS text[] LANGUAGE sql IMMUTABLE AS $$
  SELECT coalesce(array_agg(y), '{}'::text[]) FROM (
    SELECT CASE WHEN x LIKE 'work:%' THEN CASE WHEN sc IN ('work', 'both') THEN substr(x, 6) END
                WHEN x LIKE 'personal:%' THEN CASE WHEN sc IN ('personal', 'both') THEN substr(x, 10) END
                ELSE x END AS y
    FROM unnest(p) x) z WHERE y IS NOT NULL
$$;
DROP FUNCTION IF EXISTS synapse.can_read_for(uuid, uuid, text, text, text[]);
DROP INDEX IF EXISTS synapse.item_silos;
ALTER TABLE synapse.item DROP COLUMN IF EXISTS silos;
UPDATE synapse.item i SET can_read = synapse.can_read_for(i.dataset_id, i.id, i.sensitivity, i.owner, i.scope);
"""

#: Who a trusted contact sees, as a list of silo keys. Both was every silo, so it stays no limit.
SEES = r"""
ALTER TABLE trusted_contacts ALTER COLUMN sees DROP DEFAULT;
ALTER TABLE trusted_contacts ALTER COLUMN sees DROP NOT NULL;
ALTER TABLE trusted_contacts ALTER COLUMN sees TYPE jsonb USING (CASE sees
    WHEN 'both' THEN '["work", "personal"]' WHEN 'personal' THEN '["personal"]' ELSE '["work"]' END)::jsonb;
"""
SEES_UNDO = r"""
ALTER TABLE trusted_contacts ALTER COLUMN sees TYPE text USING (CASE
    WHEN sees @> '["work", "personal"]'::jsonb THEN 'both' WHEN sees @> '["personal"]'::jsonb THEN 'personal'
    ELSE 'work' END);
UPDATE trusted_contacts SET sees = 'work' WHERE sees IS NULL;
ALTER TABLE trusted_contacts ALTER COLUMN sees SET DEFAULT 'work';
ALTER TABLE trusted_contacts ALTER COLUMN sees SET NOT NULL;
"""


class Migration(migrations.Migration):

    dependencies = [("rouh", "0133_work_and_personal")]

    operations = [
        migrations.CreateModel(
            name="Silo",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("user_id", models.TextField()),
                ("org_id", models.TextField()),
                ("key", models.TextField()),
                ("name", models.TextField()),
                ("colour", models.TextField(default="slate")),
                ("position", models.IntegerField(default=0)),
                ("words", models.TextField(blank=True, default="")),
                ("runs", models.BooleanField(default=False)),
                ("others", models.BooleanField(default=False)),
                ("created_at", models.FloatField(default=0)),
                ("updated_at", models.FloatField(default=0)),
            ],
            options={"db_table": "silo"},
        ),
        migrations.AddConstraint(
            model_name="silo",
            constraint=models.UniqueConstraint(fields=("org_id", "user_id", "key"), name="silo_one_key"),
        ),
        migrations.CreateModel(
            name="SiloRule",
            fields=[
                ("id", models.BigAutoField(primary_key=True, serialize=False)),
                ("user_id", models.TextField()),
                ("org_id", models.TextField()),
                ("kind", models.TextField()),
                ("match", models.TextField()),
                ("label", models.TextField(blank=True, default="")),
                ("silo", models.TextField()),
                ("created_at", models.FloatField(default=0)),
            ],
            options={"db_table": "silo_rule"},
        ),
        migrations.AddConstraint(
            model_name="silorule",
            constraint=models.UniqueConstraint(fields=("org_id", "user_id", "kind", "match"),
                                               name="silo_rule_one_match"),
        ),
        migrations.AddField(
            model_name="reminder",
            name="silos",
            field=models.JSONField(blank=True, default=list, db_default=[]),
        ),
        migrations.SeparateDatabaseAndState(
            database_operations=[migrations.RunSQL(SEES, SEES_UNDO)],
            state_operations=[migrations.AlterField(
                model_name="trustedcontact",
                name="sees",
                field=models.JSONField(blank=True, default=None, null=True),
            )],
        ),
        migrations.RunSQL(SCHEMA, UNDO),
    ]
