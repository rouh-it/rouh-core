"""Dreaming: a nightly pass that compares Synapse's items over time (5 October 2026, D86 to D92).

Synapse keeps every item and works out what matters when a question is asked, so nothing is promoted
from one tier to another and nothing is rewritten. What a night does is compare items written at
different times and write down what it found, as annotations beside the items, never in them
(`rouh/synapse/dreaming.py`):

- `synapse.dream` is one night (or one press of Dream now): its scope, what it cost, what stopped it,
  its plain-language summary and diary, and the memory's health after it.
- `synapse.dream_change` is one change the night proposed, with the items it depends on, the quotes it
  rests on (each checked against the stored text), its state (applied, waiting, rejected, undone, shown)
  and `before`, the exact previous state of every claim, link and item field it touched, so one change or
  a whole night can be undone exactly. `readers` is the intersection of its items' readers.
- `synapse.claim_note` is what retrieval reads: a claim replaced by a newer one, an ask or promise closed
  by a later item, a claim whose kind was corrected. A note belongs to its change and goes with it, and
  goes with its item when the item is deleted.
- `synapse.item.alias_of` marks a duplicate kept as an alias of its canonical item, and `dreamed_at` when a
  night last read an item, so a night's backfill takes the oldest unread ones.

Every table carries `dataset_id`, and every row that names an item names it through `(dataset_id, item_id)`.
"""
from django.db import migrations

SCHEMA = r"""
ALTER TABLE synapse.item ADD COLUMN IF NOT EXISTS alias_of uuid;
ALTER TABLE synapse.item ADD COLUMN IF NOT EXISTS dreamed_at timestamptz;
CREATE INDEX IF NOT EXISTS item_alias_of ON synapse.item (dataset_id, alias_of) WHERE alias_of IS NOT NULL;
CREATE INDEX IF NOT EXISTS item_dreamed ON synapse.item (dataset_id, dreamed_at NULLS FIRST, stored_at);

CREATE TABLE IF NOT EXISTS synapse.dream (
    id          uuid PRIMARY KEY DEFAULT uuidv7(),
    dataset_id  uuid NOT NULL REFERENCES synapse.dataset(id) ON DELETE CASCADE,
    number      integer NOT NULL,
    by          text NOT NULL DEFAULT 'page',
    status      text NOT NULL DEFAULT 'running',
    stage       text NOT NULL DEFAULT 'gather',
    progress    jsonb NOT NULL DEFAULT '{}'::jsonb,
    trace_id    uuid,
    started_at  timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz,
    ms          integer,
    cost_usd    numeric(12, 6) NOT NULL DEFAULT 0,
    cap_usd     numeric(12, 6) NOT NULL DEFAULT 0,
    since       timestamptz,
    scope       jsonb NOT NULL DEFAULT '{}'::jsonb,
    counts      jsonb NOT NULL DEFAULT '{}'::jsonb,
    health      jsonb NOT NULL DEFAULT '{}'::jsonb,
    guard       jsonb NOT NULL DEFAULT '{}'::jsonb,
    stopped_why text NOT NULL DEFAULT '',
    summary     text NOT NULL DEFAULT '',
    diary       jsonb NOT NULL DEFAULT '[]'::jsonb,
    undone_at   timestamptz,
    CONSTRAINT dream_number_once UNIQUE (dataset_id, number)
);
CREATE INDEX IF NOT EXISTS dream_newest ON synapse.dream (dataset_id, number DESC);

CREATE TABLE IF NOT EXISTS synapse.dream_change (
    id          bigserial PRIMARY KEY,
    dataset_id  uuid NOT NULL REFERENCES synapse.dataset(id) ON DELETE CASCADE,
    dream_id    uuid NOT NULL REFERENCES synapse.dream(id) ON DELETE CASCADE,
    kind        text NOT NULL,
    state       text NOT NULL,
    items       uuid[] NOT NULL DEFAULT '{}',
    readers     text[] NOT NULL DEFAULT '{}',
    area        text NOT NULL DEFAULT '',
    old_item    uuid,
    old_claim   integer,
    new_item    uuid,
    new_claim   integer,
    reason      text NOT NULL DEFAULT '',
    evidence    jsonb NOT NULL DEFAULT '[]'::jsonb,
    payload     jsonb NOT NULL DEFAULT '{}'::jsonb,
    effect      jsonb NOT NULL DEFAULT '{}'::jsonb,
    before      jsonb NOT NULL DEFAULT '{}'::jsonb,
    made_at     timestamptz NOT NULL DEFAULT now(),
    applied_at  timestamptz,
    decided_at  timestamptz,
    decided_by  text NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS dream_change_of ON synapse.dream_change (dream_id, kind);
CREATE INDEX IF NOT EXISTS dream_change_waiting ON synapse.dream_change (dataset_id, state);
CREATE INDEX IF NOT EXISTS dream_change_items ON synapse.dream_change USING gin (items);

CREATE TABLE IF NOT EXISTS synapse.claim_note (
    id          bigserial PRIMARY KEY,
    dataset_id  uuid NOT NULL,
    item_id     uuid NOT NULL,
    claim_idx   integer NOT NULL,
    claim_text  text NOT NULL DEFAULT '',
    note        text NOT NULL,
    by_item     uuid,
    by_claim    integer,
    changed_on  date,
    kind_now    text NOT NULL DEFAULT '',
    readers     text[] NOT NULL DEFAULT '{}',
    change_id   bigint NOT NULL REFERENCES synapse.dream_change(id) ON DELETE CASCADE,
    made_at     timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (dataset_id, item_id) REFERENCES synapse.item(dataset_id, id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS claim_note_of ON synapse.claim_note (dataset_id, item_id);
CREATE INDEX IF NOT EXISTS claim_note_by ON synapse.claim_note (dataset_id, by_item);
"""

UNDO = r"""
DROP TABLE IF EXISTS synapse.claim_note;
DROP TABLE IF EXISTS synapse.dream_change;
DROP TABLE IF EXISTS synapse.dream;
DROP INDEX IF EXISTS synapse.item_dreamed;
DROP INDEX IF EXISTS synapse.item_alias_of;
ALTER TABLE synapse.item DROP COLUMN IF EXISTS dreamed_at;
ALTER TABLE synapse.item DROP COLUMN IF EXISTS alias_of;
"""


class Migration(migrations.Migration):

    dependencies = [("rouh", "0088_synapse_frozen_and_experience")]

    operations = [migrations.RunSQL(SCHEMA, UNDO)]
