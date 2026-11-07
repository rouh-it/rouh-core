"""Synapse's lab: the first version of Rouh's new memory, in a schema of its own.

Task 85, step 85-02 (3 October 2026, asked by voice): build Synapse from the
design spec in step 85-01 as a standalone lab inside Rouh, which nothing else in
Rouh reads from yet. The spec's D20 asks for "a `memory` schema in Rouh's
database"; D63 leaves the name to whoever builds it, and it is `synapse` here,
so it can never be mistaken for today's facts list (`rouh/memory.py`).

Every table carries `dataset_id`, and every link, passage, reader and version
points at its item through `(dataset_id, item_id)`, so a row of one dataset can
never point into another: the isolation Petar asked for is in the keys, not
only in the queries. Deleting a dataset deletes everything in it.

The two extensions, `vector` (pgvector, D37) and `pg_trgm` (letter groups for
misspellings, D36), need a superuser on the live server, so `manage.py
predeploy` makes them as PostgreSQL's own user before this runs; in a test
world the database's owner is a superuser and this makes them itself.
"""
from django.db import migrations

SCHEMA = r"""
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
CREATE SCHEMA IF NOT EXISTS synapse;

-- Bulgarian word forms (D36), the meeting library's way: Hunspell's
-- dictionary for words in Cyrillic, plain lower-casing for everything else.
-- A machine without the dictionary files gets plain lower-casing only.
DO $$
BEGIN
  BEGIN
    CREATE TEXT SEARCH DICTIONARY synapse.bg_hunspell
      (TEMPLATE = ispell, DictFile = bulgarian_bg, AffFile = bulgarian_bg);
  EXCEPTION WHEN others THEN
    CREATE TEXT SEARCH DICTIONARY synapse.bg_hunspell (TEMPLATE = pg_catalog.simple);
  END;
END $$;
CREATE TEXT SEARCH CONFIGURATION synapse.bg (COPY = pg_catalog.simple);
ALTER TEXT SEARCH CONFIGURATION synapse.bg
  ALTER MAPPING FOR word, hword, hword_part WITH synapse.bg_hunspell, simple;

CREATE TABLE synapse.dataset (
  id          uuid PRIMARY KEY DEFAULT uuidv7(),
  org_id      text NOT NULL,
  user_id     text NOT NULL,
  name        text NOT NULL,
  about       text NOT NULL DEFAULT '',
  example     text NOT NULL DEFAULT '',
  owner_name  text NOT NULL DEFAULT 'Petar',
  chat_id     text NOT NULL DEFAULT '',
  tuning      jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at  timestamptz NOT NULL DEFAULT now(),
  updated_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX dataset_owner ON synapse.dataset (org_id, user_id);

CREATE TABLE synapse.item (
  id            uuid NOT NULL DEFAULT uuidv7(),
  dataset_id    uuid NOT NULL REFERENCES synapse.dataset(id) ON DELETE CASCADE,
  kind          text NOT NULL,
  source        text NOT NULL DEFAULT 'lab',
  source_key    text NOT NULL,
  title         text NOT NULL DEFAULT '',
  raw           text NOT NULL DEFAULT '',
  body          text NOT NULL DEFAULT '',
  said_at       timestamptz,
  stored_at     timestamptz NOT NULL DEFAULT now(),
  updated_at    timestamptz NOT NULL DEFAULT now(),
  tier          smallint NOT NULL DEFAULT 1,
  tier_why      text NOT NULL DEFAULT '',
  sensitivity   text NOT NULL DEFAULT 'unlabelled',
  sensitivity_why jsonb NOT NULL DEFAULT '{}'::jsonb,
  owner         text NOT NULL DEFAULT '',
  meta          jsonb NOT NULL DEFAULT '{}'::jsonb,
  xray          jsonb,
  xray_by       jsonb,
  xray_dropped  integer NOT NULL DEFAULT 0,
  status        text NOT NULL DEFAULT 'stored',
  version       integer NOT NULL DEFAULT 1,
  deleted_at    timestamptz,
  PRIMARY KEY (id),
  UNIQUE (dataset_id, id),
  UNIQUE (dataset_id, source, source_key)
);
CREATE INDEX item_kind ON synapse.item (dataset_id, kind) WHERE deleted_at IS NULL;
CREATE INDEX item_said ON synapse.item (dataset_id, said_at);
CREATE INDEX item_title_trgm ON synapse.item USING gin (title gin_trgm_ops);

CREATE TABLE synapse.item_version (
  id          bigserial PRIMARY KEY,
  dataset_id  uuid NOT NULL,
  item_id     uuid NOT NULL,
  version     integer NOT NULL,
  title       text NOT NULL DEFAULT '',
  raw         text NOT NULL DEFAULT '',
  meta        jsonb NOT NULL DEFAULT '{}'::jsonb,
  xray        jsonb,
  xray_by     jsonb,
  made_at     timestamptz NOT NULL DEFAULT now(),
  keep_until  timestamptz,
  why         text NOT NULL DEFAULT '',
  FOREIGN KEY (dataset_id, item_id) REFERENCES synapse.item(dataset_id, id) ON DELETE CASCADE
);
CREATE INDEX item_version_of ON synapse.item_version (dataset_id, item_id, version);

CREATE TABLE synapse.passage (
  id          bigserial PRIMARY KEY,
  dataset_id  uuid NOT NULL,
  item_id     uuid NOT NULL,
  seq         integer NOT NULL,
  text        text NOT NULL,
  words       tsvector NOT NULL,
  vec         halfvec(1024),
  from_xray   boolean NOT NULL DEFAULT false,
  embed_model text NOT NULL DEFAULT '',
  FOREIGN KEY (dataset_id, item_id) REFERENCES synapse.item(dataset_id, id) ON DELETE CASCADE
);
CREATE INDEX passage_item ON synapse.passage (dataset_id, item_id);
CREATE INDEX passage_words ON synapse.passage USING gin (words);
CREATE INDEX passage_trgm ON synapse.passage USING gin (text gin_trgm_ops);
CREATE INDEX passage_vec ON synapse.passage USING hnsw (vec halfvec_cosine_ops);

CREATE TABLE synapse.link (
  id            bigserial PRIMARY KEY,
  dataset_id    uuid NOT NULL,
  src           uuid NOT NULL,
  dst           uuid NOT NULL,
  type          text NOT NULL,
  strength      real NOT NULL,
  base_strength real NOT NULL,
  origin        text NOT NULL,
  made_by       text NOT NULL DEFAULT '',
  claim_idx     integer,
  why           text NOT NULL DEFAULT '',
  evidence      jsonb NOT NULL DEFAULT '{}'::jsonb,
  made_at       timestamptz NOT NULL DEFAULT now(),
  checked_at    timestamptz NOT NULL DEFAULT now(),
  UNIQUE (dataset_id, src, dst, type),
  FOREIGN KEY (dataset_id, src) REFERENCES synapse.item(dataset_id, id) ON DELETE CASCADE,
  FOREIGN KEY (dataset_id, dst) REFERENCES synapse.item(dataset_id, id) ON DELETE CASCADE
);
CREATE INDEX link_src ON synapse.link (dataset_id, src);
CREATE INDEX link_dst ON synapse.link (dataset_id, dst);

CREATE TABLE synapse.reader (
  dataset_id  uuid NOT NULL,
  item_id     uuid NOT NULL,
  principal   text NOT NULL,
  PRIMARY KEY (dataset_id, item_id, principal),
  FOREIGN KEY (dataset_id, item_id) REFERENCES synapse.item(dataset_id, id) ON DELETE CASCADE
);
CREATE INDEX reader_principal ON synapse.reader (dataset_id, principal);

CREATE TABLE synapse.derived (
  id           bigserial PRIMARY KEY,
  dataset_id   uuid NOT NULL REFERENCES synapse.dataset(id) ON DELETE CASCADE,
  child_table  text NOT NULL,
  child_id     text NOT NULL,
  item_id      uuid NOT NULL
);
CREATE INDEX derived_item ON synapse.derived (dataset_id, item_id);

CREATE TABLE synapse.use (
  id          bigserial PRIMARY KEY,
  dataset_id  uuid NOT NULL REFERENCES synapse.dataset(id) ON DELETE CASCADE,
  query_id    uuid NOT NULL,
  item_id     uuid NOT NULL,
  shown       boolean NOT NULL DEFAULT true,
  cited       boolean NOT NULL DEFAULT false,
  rank        integer,
  path        jsonb NOT NULL DEFAULT '[]'::jsonb,
  engaged     boolean NOT NULL DEFAULT false,
  learned     boolean NOT NULL DEFAULT false,
  at          timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX use_item ON synapse.use (dataset_id, item_id);

CREATE TABLE synapse.job (
  id          bigserial PRIMARY KEY,
  dataset_id  uuid NOT NULL REFERENCES synapse.dataset(id) ON DELETE CASCADE,
  kind        text NOT NULL,
  item_id     uuid,
  trace_id    uuid,
  payload     jsonb NOT NULL DEFAULT '{}'::jsonb,
  priority    integer NOT NULL DEFAULT 5,
  not_before  timestamptz NOT NULL DEFAULT now(),
  tries       integer NOT NULL DEFAULT 0,
  locked_by   text,
  locked_at   timestamptz,
  done_at     timestamptz,
  error       text NOT NULL DEFAULT '',
  made_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX job_waiting ON synapse.job (priority, not_before) WHERE done_at IS NULL;

CREATE TABLE synapse.trace (
  id           uuid PRIMARY KEY DEFAULT uuidv7(),
  dataset_id   uuid NOT NULL REFERENCES synapse.dataset(id) ON DELETE CASCADE,
  kind         text NOT NULL,
  item_id      uuid,
  title        text NOT NULL DEFAULT '',
  by           text NOT NULL DEFAULT 'page',
  status       text NOT NULL DEFAULT 'running',
  started_at   timestamptz NOT NULL DEFAULT now(),
  finished_at  timestamptz,
  ms           integer,
  cost_usd     numeric(12, 6) NOT NULL DEFAULT 0,
  summary      jsonb NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX trace_of ON synapse.trace (dataset_id, started_at DESC);
CREATE INDEX trace_item ON synapse.trace (dataset_id, item_id);

CREATE TABLE synapse.trace_step (
  id          bigserial PRIMARY KEY,
  trace_id    uuid NOT NULL REFERENCES synapse.trace(id) ON DELETE CASCADE,
  dataset_id  uuid NOT NULL,
  seq         integer NOT NULL,
  name        text NOT NULL,
  title       text NOT NULL DEFAULT '',
  status      text NOT NULL DEFAULT 'done',
  started_at  timestamptz NOT NULL DEFAULT now(),
  ms          integer,
  cost_usd    numeric(12, 6) NOT NULL DEFAULT 0,
  data        jsonb NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX trace_step_of ON synapse.trace_step (trace_id, seq);

CREATE TABLE synapse.call (
  id          bigserial PRIMARY KEY,
  dataset_id  uuid NOT NULL REFERENCES synapse.dataset(id) ON DELETE CASCADE,
  trace_id    uuid,
  kind        text NOT NULL,
  purpose     text NOT NULL DEFAULT '',
  backend     text NOT NULL DEFAULT '',
  model       text NOT NULL DEFAULT '',
  version     text NOT NULL DEFAULT '',
  ms          integer,
  tokens_in   integer NOT NULL DEFAULT 0,
  tokens_out  integer NOT NULL DEFAULT 0,
  cost_usd    numeric(12, 6) NOT NULL DEFAULT 0,
  items       uuid[] NOT NULL DEFAULT '{}',
  ok          boolean NOT NULL DEFAULT true,
  error       text NOT NULL DEFAULT '',
  at          timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX call_trace ON synapse.call (trace_id);
CREATE INDEX call_items ON synapse.call USING gin (items);

CREATE TABLE synapse.topic_proposal (
  id          bigserial PRIMARY KEY,
  dataset_id  uuid NOT NULL REFERENCES synapse.dataset(id) ON DELETE CASCADE,
  name        text NOT NULL,
  norm        text NOT NULL,
  item_id     uuid NOT NULL,
  strength    real NOT NULL DEFAULT 0.6,
  at          timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX topic_proposal_norm ON synapse.topic_proposal (dataset_id, norm);

CREATE TABLE synapse.word_proposal (
  id          bigserial PRIMARY KEY,
  dataset_id  uuid NOT NULL REFERENCES synapse.dataset(id) ON DELETE CASCADE,
  term        text NOT NULL,
  norm        text NOT NULL,
  meaning     text NOT NULL DEFAULT '',
  area        text NOT NULL DEFAULT '',
  item_id     uuid NOT NULL,
  at          timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX word_proposal_norm ON synapse.word_proposal (dataset_id, norm);

CREATE TABLE synapse.map (
  id          bigserial PRIMARY KEY,
  dataset_id  uuid NOT NULL REFERENCES synapse.dataset(id) ON DELETE CASCADE,
  viewer      text NOT NULL,
  version     integer NOT NULL,
  text        text NOT NULL,
  lines       jsonb NOT NULL DEFAULT '{}'::jsonb,
  tokens      integer NOT NULL DEFAULT 0,
  why         text NOT NULL DEFAULT '',
  made_at     timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX map_of ON synapse.map (dataset_id, viewer, version DESC);

CREATE TABLE synapse.map_line (
  id          bigserial PRIMARY KEY,
  dataset_id  uuid NOT NULL REFERENCES synapse.dataset(id) ON DELETE CASCADE,
  section     text NOT NULL,
  key         text NOT NULL,
  text        text NOT NULL,
  pinned      boolean NOT NULL DEFAULT false,
  by          text NOT NULL DEFAULT 'model',
  made_at     timestamptz NOT NULL DEFAULT now(),
  UNIQUE (dataset_id, section, key)
);

CREATE TABLE synapse.query (
  id           uuid PRIMARY KEY DEFAULT uuidv7(),
  dataset_id   uuid NOT NULL REFERENCES synapse.dataset(id) ON DELETE CASCADE,
  question     text NOT NULL,
  context_item uuid,
  asker        text NOT NULL,
  mode         text NOT NULL DEFAULT 'live',
  by           text NOT NULL DEFAULT 'page',
  label        text NOT NULL DEFAULT '',
  settings     jsonb NOT NULL DEFAULT '{}'::jsonb,
  trace_id     uuid,
  status       text NOT NULL DEFAULT 'running',
  walk         jsonb NOT NULL DEFAULT '{}'::jsonb,
  pack         jsonb NOT NULL DEFAULT '{}'::jsonb,
  answer       jsonb NOT NULL DEFAULT '{}'::jsonb,
  ms_pack      integer,
  ms_total     integer,
  cost_usd     numeric(12, 6) NOT NULL DEFAULT 0,
  engaged      boolean NOT NULL DEFAULT true,
  expires_at   timestamptz,
  created_at   timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX query_of ON synapse.query (dataset_id, created_at DESC);

CREATE TABLE synapse.eval_question (
  id           bigserial PRIMARY KEY,
  dataset_id   uuid NOT NULL REFERENCES synapse.dataset(id) ON DELETE CASCADE,
  question     text NOT NULL,
  context_item uuid,
  asker        text NOT NULL DEFAULT '',
  gold         uuid[] NOT NULL DEFAULT '{}',
  facts        jsonb NOT NULL DEFAULT '[]'::jsonb,
  forbidden    boolean NOT NULL DEFAULT false,
  grp          text NOT NULL DEFAULT '',
  made_at      timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE synapse.eval_run (
  id           uuid PRIMARY KEY DEFAULT uuidv7(),
  dataset_id   uuid NOT NULL REFERENCES synapse.dataset(id) ON DELETE CASCADE,
  label        text NOT NULL DEFAULT '',
  configs      jsonb NOT NULL DEFAULT '[]'::jsonb,
  status       text NOT NULL DEFAULT 'running',
  by           text NOT NULL DEFAULT 'page',
  results      jsonb NOT NULL DEFAULT '[]'::jsonb,
  summary      jsonb NOT NULL DEFAULT '{}'::jsonb,
  trace_id     uuid,
  started_at   timestamptz NOT NULL DEFAULT now(),
  finished_at  timestamptz
);

CREATE TABLE synapse.backend_status (
  org_id      text NOT NULL,
  name        text NOT NULL,
  status      text NOT NULL,
  said        text NOT NULL DEFAULT '',
  checked_at  timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (org_id, name)
);

CREATE TABLE synapse.spend (
  org_id   text NOT NULL,
  day      date NOT NULL,
  backend  text NOT NULL,
  usd      numeric(12, 6) NOT NULL DEFAULT 0,
  PRIMARY KEY (org_id, day, backend)
);
"""

UNDO = "DROP SCHEMA IF EXISTS synapse CASCADE;"


class Migration(migrations.Migration):

    dependencies = [("rouh", "0061_guest_requests_to_page_org")]

    operations = [migrations.RunSQL(SCHEMA, UNDO)]
