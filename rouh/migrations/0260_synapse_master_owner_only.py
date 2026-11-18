"""Synapse Master is kept for this Rouh's owner only, and the database itself holds to it.

Petar, 18 November 2026 (task 182, step 182-07): "Sharing is now done through the rouh.land accounts. so
other people should not have accounts in my rouh. this feature should be deleted, along with the accounts
and the synapse for them." Since 30 October each login shared with had been given its own Synapse Master,
and every ten minutes a copy of the owner's whole workspace was read into each of them again.

- **The rule, in the database.** `synapse.only_owner_master` refuses a dataset marked master for anybody
  but the owner: the first active account that is not a guest (`rouh/web/firstrun.the_owner`, the same
  order). The code refuses it too (`synapse/master.make`, `NotOwner`); this is what makes it impossible.
- **Masters already made for somebody else** stop being masters here, with nothing waiting to be read,
  so nothing syncs or reads them again. Their data is left as it is, and the owner deletes it by hand
  (`manage.py synapse_master remove --dataset <id> --user <its account>`).
- **What is left of a memory that was deleted** (`synapse.gone_dataset`): its id, name and whose it was,
  so the call log, which keeps every past call as history, still names it on the stats screen
  ("Deleted login (Name)", `rouh/usage_drill.py`).
"""
from django.db import migrations

OWNER = ("SELECT id::text FROM public.users WHERE is_active AND NOT is_guest "
         "ORDER BY date_joined, id LIMIT 1")

FORWARD = f"""
CREATE TABLE IF NOT EXISTS synapse.gone_dataset (
  id          uuid PRIMARY KEY,
  name        text NOT NULL DEFAULT '',
  owner_name  text NOT NULL DEFAULT '',
  user_id     text NOT NULL DEFAULT '',
  org_id      text NOT NULL DEFAULT '',
  why         text NOT NULL DEFAULT '',
  gone_at     timestamptz NOT NULL DEFAULT now()
);

DELETE FROM synapse.job WHERE done_at IS NULL AND dataset_id IN (
  SELECT id FROM synapse.dataset WHERE master AND user_id IS DISTINCT FROM ({OWNER}));
UPDATE synapse.dataset SET master = false
  WHERE master AND user_id IS DISTINCT FROM ({OWNER});

CREATE OR REPLACE FUNCTION synapse.only_owner_master() RETURNS trigger AS $$
DECLARE
  owner text;
BEGIN
  IF NEW.master THEN
    {OWNER.replace("SELECT id::text FROM", "SELECT id::text INTO owner FROM")};
    IF owner IS NULL OR NEW.user_id IS DISTINCT FROM owner THEN
      RAISE EXCEPTION 'Synapse Master is kept for this Rouh''s owner only, not for account %', NEW.user_id;
    END IF;
  END IF;
  RETURN NEW;
END $$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS dataset_only_owner_master ON synapse.dataset;
CREATE TRIGGER dataset_only_owner_master BEFORE INSERT OR UPDATE OF master, user_id ON synapse.dataset
  FOR EACH ROW EXECUTE FUNCTION synapse.only_owner_master();
"""

BACKWARD = """
DROP TRIGGER IF EXISTS dataset_only_owner_master ON synapse.dataset;
DROP FUNCTION IF EXISTS synapse.only_owner_master();
DROP TABLE IF EXISTS synapse.gone_dataset;
"""


class Migration(migrations.Migration):

    dependencies = [
        ('rouh', '0259_rouh_link'),
    ]

    operations = [migrations.RunSQL(FORWARD, BACKWARD)]
