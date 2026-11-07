"""Synapse's Bulgarian word forms made again wherever a database came back without them.

Petar, 31 October 2026 (fr_ff415b038226): "It seems synapse query fails". Every Synapse
search, and every write of a passage, runs `to_tsvector('synapse.bg', ...)`, and on the
live database that morning it said: text search configuration "synapse.bg" does not
exist. The database had just been copied back by the creator switch's way back
(the Creator Rouh's switch, rouh-it-site ops/creator), and a restore leaves the configuration out whenever its
dictionary could not be made, which is any PostgreSQL without Hunspell's Bulgarian files.

Migration 0062 made both once; this makes whichever of the two is missing, the same way
0062 does (Hunspell where the files are, plain lower-casing where they are not), and
leaves one that is there alone. It changes nothing on a database that already has them.
"""
from django.db import migrations

ENSURE = r"""
DO $$
BEGIN
  IF to_regnamespace('synapse') IS NULL THEN
    RETURN;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_ts_dict d JOIN pg_namespace n ON n.oid = d.dictnamespace
                 WHERE n.nspname = 'synapse' AND d.dictname = 'bg_hunspell') THEN
    BEGIN
      CREATE TEXT SEARCH DICTIONARY synapse.bg_hunspell
        (TEMPLATE = ispell, DictFile = bulgarian_bg, AffFile = bulgarian_bg);
    EXCEPTION WHEN others THEN
      CREATE TEXT SEARCH DICTIONARY synapse.bg_hunspell (TEMPLATE = pg_catalog.simple);
    END;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_ts_config c JOIN pg_namespace n ON n.oid = c.cfgnamespace
                 WHERE n.nspname = 'synapse' AND c.cfgname = 'bg') THEN
    CREATE TEXT SEARCH CONFIGURATION synapse.bg (COPY = pg_catalog.simple);
    ALTER TEXT SEARCH CONFIGURATION synapse.bg
      ALTER MAPPING FOR word, hword, hword_part WITH synapse.bg_hunspell, simple;
  END IF;
END $$;
"""


class Migration(migrations.Migration):
    dependencies = [("rouh", "0221_every_rule_in_master")]

    operations = [migrations.RunSQL(ENSURE, reverse_sql=migrations.RunSQL.noop)]
