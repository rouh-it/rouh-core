# The event log

Everything done in Rouh and by it, one append-only row each, so it can be studied later.

Petar, 10 October 2026: "For now track everything in the way we should to be able to take full advantage of it.
This will be big as we will be recording everything. Think scalability. Databases, etc."

One foundation, two views later.
The first is **use**: where the person presses, what they open (tasks, steps, projects, chats, runs, cards, pages, settings), how much they write, forks, panels, the orb, the Control Room.
The second is **work**: what work was done, by whom (the person, Rouh, a background job, a run of the one program, a delegate), of what kind, for how long, and how it ended.
Both are rows of one table.
This phase is the collecting, and a first look at it in Settings, Stats, Event log (`/settings/stats/events`).
The analysis comes later and reads the same rows.

## Where things are

| Piece | File |
|---|---|
| The tables, the monthly partitions and the function that makes them | `rouh/migrations/0115_event_log.py` |
| The fixed list of event names, `emit`, `take`, the writer, the rollups, the reads | `rouh/events.py` |
| The page's tracker: presses, opens, typing counts, the tab | `rouh/static/track.js` |
| The endpoints, `POST /api/events` and `GET /api/settings/stats/events` | `rouh/web/stats.py` |
| The Event log tab | `rouh/static/statspage.js`, `statspage.css` |

## A row

`analytics.event`, in a schema of its own so it is never mistaken for Rouh's working tables.

| Column | What it is |
|---|---|
| `id` | A UUIDv7, so ids sort the way rows were made. The page makes its own, so a batch sent twice is kept once (`ON CONFLICT DO NOTHING`). |
| `occurred_at` | When it happened, by the clock of whoever saw it. Not believed if it is more than a day behind or five minutes ahead of the server: then it is when it arrived. The partition key. |
| `received_at` | When the row reached the database. What the rollups follow. |
| `org_id`, `user_id` | Whose it is. Always both, from the sign-in, never from what the page says. Work nobody signed in asked for (a job, a run, the phone, the clock) is the install owner's. |
| `session_id` | One page load of one tab. Empty for the server's own. |
| `chat_id` | The chat it happened in, where there is one. |
| `actor` | `person`, `rouh`, `job`, `run`, `delegate`, `system`. For work that runs a while (`job.*`, `run.*`, `turn.finished`) it is who set it going, on both ends, so they pair up. |
| `source` | `web`, `telegram`, `mail`, `voice`, `scheduler`, `server`. |
| `name` | Dotted, from `events.NAMES` and nowhere else; any other name is refused. |
| `object_type`, `object_id` | What it was about: a task's folder, a step, a project, a chat, a run, a card, a tool, a mail id, a control's key. |
| `duration_ms`, `count` | The two numbers most events have: how long, and how many (characters, mostly). |
| `props` | Everything else, as JSONB, cleaned on the way in. |
| `v` | The shape of the row, 1 for now. Raised when a column's meaning changes. |

The names, with what each field means for each, are `NAMES` in `rouh/events.py`.
A new kind of event is a line there.

## Never what was typed or said

Counts, lengths, durations and ids, nothing else.

- The page never reads what is in a field. It counts characters as a field grows and shrinks (`ui.typed`: typed, deleted, pasted, and the time spent typing), and a password field or a one-time code is not counted at all.
- Of an address only the path and the chat beside it are sent, so a search typed into the address bar never goes.
- A link out of Rouh is its host only.
- A message's event is its length, never its words, whether typed, spoken or from Telegram.
- On the server every `props` goes through `events.clean`: any key that names content (`text`, `body`, `value`, `password`, `subject`, `title`, `prompt` ...) is dropped, and so is any string longer than 200 characters. It is the guard behind the rule, not the rule: nothing that sends an event holds a person's words in the first place.
- Settings, Stats shows the signed-in person their own numbers only, by `org_id` and `user_id`. The one number about everybody is the table's size on disk.

## Getting rows in without slowing anything

- **The page** queues events in memory and sends a batch of up to 100 every five seconds, and at once when the tab is hidden or closed, with `fetch(..., {keepalive: true})` so a closing tab still gets it there. A batch the server could not take (a 5xx, the network) is tried once more with the next and then let go. Nothing in the tracker can throw into the page.
- **`POST /api/events`** checks the batch and queues it, and answers 202 at once. It never touches the database itself.
- **The server's own events** go through `events.emit`, which only queues. It never raises and never waits.
- **One thread per process** (`events.WRITER`) writes what is queued every two seconds, or sooner at 500 rows, in one multi-row `INSERT`. If the database is away the batch is dropped and counted, and the log says so once a minute. At most 50,000 rows wait in memory. What is waiting when the process ends is written first (`atexit`, and `runtime.shutdown`).

## Partitions

`analytics.event` is range-partitioned by month on `occurred_at`: `analytics.event_2026_10`, `analytics.event_2026_11`, and so on.
`analytics.ensure_partitions(behind, ahead)` makes the months around now; it runs in the migration (one month back, three ahead), and the writer runs it again once a day and whenever an insert finds no month for its row.
It takes an advisory lock, so two processes never race to make the same month.
There is deliberately no default partition: rows outside every month would make that month impossible to create later, and the one-day clamp on `occurred_at` keeps every row inside the months that exist.

Indexes are declared on the parent and so on every month:
`(org_id, user_id, occurred_at)` for one person's events in a range,
`(name, occurred_at)` for one kind of event,
`(object_type, object_id)` for everything about one thing,
and BRIN on `occurred_at` and `received_at`, which cost almost nothing on an append-only table and are what the rollups scan by.
The primary key is `(id, occurred_at)`, because a partitioned table's unique keys must hold the partition key.

## Rollups

The Stats page never scans raw events.
`events.rollup` adds every row that arrived since it last ran into two small tables, in one transaction with the mark of how far it got (`analytics.rollup_state`), so each row is counted exactly once:

- `analytics.event_hourly`: per person, per hour (UTC), per name, actor and source: how many, the sum of `count`, the sum of `duration_ms`, and the newest. An hour rather than a day so a person's own days can be added up on their own clock.
- `analytics.object_daily`: per person, per day (UTC), per name and object: how many. What was opened most, which tools were called.

It follows `received_at`, ten seconds behind now, so no write still in flight is passed over.
It runs every minute on the writer's thread and once more before Stats is read, under a try-lock, so only one runs at a time anywhere.
Building a new rollup later is a new table and one pass over the raw rows; nothing about the raw rows changes.

## How big it gets

A rough count for one heavy user of Rouh in a day: about 1,500 presses, 400 things opened, 200 spells of typing, 100 tab events, 150 messages, 200 answers, 1,000 tool calls, a few hundred emails, and some tens of jobs, runs, reminders and decisions.
Call it 5,000 events a person a day, and 10,000 a day for the three people using Rouh now: about 3.7 million rows a year.
A row is about 300 bytes on the heap and as much again in its indexes, so a year is two to four GB, and a month is one table of a few hundred MB.
The rollups are a few hundred rows a person a day, small enough never to think about.

PostgreSQL is comfortable here by a wide margin, and with monthly partitions a read of last week never touches last year.
Nothing new was added to the machine for this, and nothing needs to be until the volume is about a hundred times this.

## Retention

Every raw event is kept, indefinitely, for now.
When that changes, it changes a month at a time: `ALTER TABLE analytics.event DETACH PARTITION analytics.event_2026_10`, export it (below), and drop it.
Dropping a whole month is instant and leaves no bloat, which is the reason for the partitions.
The rollups are kept forever; they are what the long views read.

## If it ever outgrows PostgreSQL

The signs: a monthly table past tens of GB, rollups that cannot keep up with a minute, or analysis that scans many months at a time and is slow.
Then, in order:

1. **Parquet, read by DuckDB.** Export each closed month once, `COPY (SELECT * FROM analytics.event_2026_10) TO STDOUT` into a Parquet file per month (or DuckDB's own `postgres` extension), kept beside the backups. DuckDB reads a year of those on a laptop in seconds. The live month stays in PostgreSQL. This is likely the only step ever needed.
2. **ClickHouse**, if many organisations use Rouh and the live month itself is too big. The writer is the one place rows are written, so it sends the same batches to ClickHouse instead (a `MergeTree` table ordered by `(org_id, user_id, occurred_at)` and partitioned by month, with `name`, `actor`, `source` and `object_type` as `LowCardinality(String)`), and the rollups become materialized views. The columns map one to one; `props` goes as a JSON column. The page, the endpoint and `emit` do not change.

Either way the schema version on every row is what lets old rows be read the way they were meant.
