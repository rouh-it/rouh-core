"""The event log: everything done in Rouh and by it, one append-only row each
(`rouh/events.py`, `EVENTS.md`).

Petar, 10 October 2026: "For now track everything in the way we should to be able to
take full advantage of it. This will be big as we will be recording everything. Think
scalability."

In a schema of its own, `analytics`, so it is never mistaken for Rouh's working tables:

* `analytics.event` is range-partitioned by month on `occurred_at`. A month is a table
  of its own (`analytics.event_2026_10`), made ahead by `analytics.ensure_partitions`,
  so old months can later be detached, archived or dropped whole, and a read of last
  week never touches last year. There is deliberately no default partition: a row
  outside every month would make the next month impossible to create. `events.py`
  keeps `occurred_at` within a day of when the row arrives, and makes the months
  around now before it writes.
* `analytics.event_hourly` and `analytics.object_daily` are the rollups Settings,
  Stats reads, so no page ever scans raw events. `analytics.rollup_state` is how far
  they have been filled in.

Every row carries `org_id` and `user_id`, and every read names both.
"""
from django.db import migrations

SCHEMA = r"""
CREATE SCHEMA IF NOT EXISTS analytics;

CREATE TABLE analytics.event (
  id           uuid        NOT NULL DEFAULT uuidv7(),
  occurred_at  timestamptz NOT NULL,
  received_at  timestamptz NOT NULL DEFAULT now(),
  org_id       text        NOT NULL DEFAULT '',
  user_id      text        NOT NULL DEFAULT '',
  session_id   text        NOT NULL DEFAULT '',
  chat_id      text        NOT NULL DEFAULT '',
  actor        text        NOT NULL,
  source       text        NOT NULL,
  name         text        NOT NULL,
  object_type  text        NOT NULL DEFAULT '',
  object_id    text        NOT NULL DEFAULT '',
  duration_ms  bigint,
  count        bigint,
  props        jsonb       NOT NULL DEFAULT '{}'::jsonb,
  v            smallint    NOT NULL DEFAULT 1,
  PRIMARY KEY (id, occurred_at)
) PARTITION BY RANGE (occurred_at);

CREATE INDEX event_whose   ON analytics.event (org_id, user_id, occurred_at);
CREATE INDEX event_named   ON analytics.event (name, occurred_at);
CREATE INDEX event_object  ON analytics.event (object_type, object_id) WHERE object_id <> '';
CREATE INDEX event_when    ON analytics.event USING brin (occurred_at);
CREATE INDEX event_landed  ON analytics.event USING brin (received_at);

-- The months around now, made ahead. Safe to call from anywhere at any time:
-- it takes a lock so two callers never race to make the same month.
CREATE FUNCTION analytics.ensure_partitions(behind int DEFAULT 1, ahead int DEFAULT 3)
RETURNS int LANGUAGE plpgsql AS $fn$
DECLARE
  first date := (date_trunc('month', now() AT TIME ZONE 'UTC')
                 - make_interval(months => behind))::date;
  m date;
  part text;
  made int := 0;
BEGIN
  PERFORM pg_advisory_xact_lock(hashtext('analytics.ensure_partitions'));
  FOR i IN 0 .. behind + ahead LOOP
    m := (first + make_interval(months => i))::date;
    part := 'event_' || to_char(m, 'YYYY_MM');
    IF to_regclass('analytics.' || part) IS NULL THEN
      EXECUTE format('CREATE TABLE analytics.%I PARTITION OF analytics.event FOR VALUES FROM (%L) TO (%L)',
                     part, m::timestamp AT TIME ZONE 'UTC',
                     (m + interval '1 month')::timestamp AT TIME ZONE 'UTC');
      made := made + 1;
    END IF;
  END LOOP;
  RETURN made;
END
$fn$;

SELECT analytics.ensure_partitions(1, 3);

-- Per person, per hour (UTC), per kind of event, who did it and from where. An hour
-- rather than a day so a person's own days can be added up on their own clock.
CREATE TABLE analytics.event_hourly (
  org_id           text        NOT NULL,
  user_id          text        NOT NULL,
  hour             timestamptz NOT NULL,
  name             text        NOT NULL,
  actor            text        NOT NULL,
  source           text        NOT NULL,
  n                bigint      NOT NULL DEFAULT 0,
  count_sum        bigint      NOT NULL DEFAULT 0,
  duration_ms_sum  bigint      NOT NULL DEFAULT 0,
  last_at          timestamptz NOT NULL,
  PRIMARY KEY (org_id, user_id, hour, name, actor, source)
);

-- Per person, per day (UTC), per kind of event and the object it was about: what
-- was opened most, which tools were called.
CREATE TABLE analytics.object_daily (
  org_id       text        NOT NULL,
  user_id      text        NOT NULL,
  day          date        NOT NULL,
  name         text        NOT NULL,
  object_type  text        NOT NULL,
  object_id    text        NOT NULL,
  n            bigint      NOT NULL DEFAULT 0,
  last_at      timestamptz NOT NULL,
  PRIMARY KEY (org_id, user_id, day, name, object_type, object_id)
);

-- How far each rollup has been filled in, by when rows arrived.
CREATE TABLE analytics.rollup_state (
  name     text        PRIMARY KEY,
  through  timestamptz NOT NULL
);
"""

UNDO = r"""
DROP SCHEMA IF EXISTS analytics CASCADE;
"""


class Migration(migrations.Migration):

    dependencies = [
        ('rouh', '0114_nav_taps'),
    ]

    operations = [migrations.RunSQL(SCHEMA, UNDO)]
