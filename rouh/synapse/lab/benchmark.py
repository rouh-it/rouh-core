"""Synapse's benchmark, inside the throwaway database: fictional data, planted cases, every number.

`python manage.py synapse_bench` makes the database and runs this in a process pointed at it
(`rouh/management/commands/synapse_bench.py`), so it times whatever code is in the checkout.

Petar, 4 October 2026 (card 1125): six scaling changes, one at a time, each measured by the same
benchmark straight after it, adopted only when it helps and breaks nothing. So beside the timings
of 3 October this measures whether the answers are right, on cases planted in the bulk data:

- **Ranking**: a rare name buried under common words; four moderately common words that meet
  only in one old item (the case the words cap of 4 October gives up on: when even the rarest
  question word is commoner than the cap, only its most recent passages are ranked); the same
  with the item recent; how often a word is used against how long the item is; meaning alone,
  for the owner and for a reader who sees a small share; a name in Cyrillic asked in Latin; the
  latest of a subject's items; an old item that is the only one holding both words asked.
- **Permissions**: items of the owner's dataset that only another person reads, special and
  unlabelled items of another owner, deleted items, and another person's dataset holding the very
  same words, each asked by the owner, by a reader who sees little, by the other person in the
  owner's dataset and by the other person in their own. Every result of every search is checked
  again by the rule itself (`search.readable_rule_sql`, `synapse.reaches`, deleted, scope), every
  pack's text and every trace written is read for the forbidden items' secret words.
- **Links**: the partner each link candidate should find: thread, reply, sender, recipient, a
  file on an email, the same file stored twice under its hash, a person the text names, meaning
  alone, rare words alone, a partner outside a thread too big for the structure cap, and an item
  sharing everything with it that its owner may not read, which must never be a candidate.
- **Traversal**: an item found by the question, the item it links to and the one after that,
  and an item linked to it that the asker may not read, which must never be gathered or packed.

Two people's data: the owner's dataset with its people set (Vera reads about 12% of it), and
Mallory's own dataset, a tenth the size, in the same tables. Nothing is sent and nothing paid: the
vectors are made by code near one of 64 made-up subjects, and the question's vector is handed in.

Resources: CPU seconds of the database's processes and of this one per phase, the peak resident
memory of both, the lowest memory the machine had free, and the size on disk of every table and
index. A size is skipped, not tried, when the disk or the memory it would need is not there.
"""
from __future__ import annotations

import json
import math
import os
import random
import resource
import statistics
import threading
import time
from contextlib import contextmanager

DIMS = 1024
TOPICS = 64
LIMITS = {"link_candidates_p95_ms": 50, "search_p95_ms": 300}
#: Ranking, link and traversal cases planted once, at the first size.
CASE_SEED = 1125


# ---------------------------------------------------------------------------------------------
# what code does not get to see: the database's own processes, and the machine
# ---------------------------------------------------------------------------------------------

def _proc_cpu(pid: int) -> tuple[float, float]:
    """(own, reaped children's) CPU seconds of a process."""
    try:
        with open(f"/proc/{pid}/stat") as f:
            parts = f.read().rsplit(")", 1)[1].split()
        tick = os.sysconf("SC_CLK_TCK")
        return (int(parts[11]) + int(parts[12])) / tick, (int(parts[13]) + int(parts[14])) / tick
    except (OSError, IndexError, ValueError):
        return 0.0, 0.0


def _status(pid: int, field: str) -> int:
    """A kB field of /proc/<pid>/status, 0 when the process is gone."""
    try:
        with open(f"/proc/{pid}/status") as f:
            for line in f:
                if line.startswith(field + ":"):
                    return int(line.split()[1])
    except OSError:
        pass
    return 0


def _children(ppid: int) -> list[int]:
    out = []
    for name in os.listdir("/proc"):
        if not name.isdigit():
            continue
        try:
            with open(f"/proc/{name}/stat") as f:
                if int(f.read().rsplit(")", 1)[1].split()[1]) == ppid:
                    out.append(int(name))
        except (OSError, IndexError, ValueError):
            continue
    return out


def mem_available_kb() -> int:
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1])
    except OSError:
        pass
    return 0


class Meter:
    """CPU, memory and the machine's free memory, over one phase.

    The database's CPU is every live process of the cluster plus what the postmaster has reaped
    (parallel workers that came and went). Its memory is the sum of each process's own pages
    (RssAnon), so shared buffers are counted once, in `shared_buffers`, not once per process.
    """

    def __init__(self, postmaster: int | None):
        self.pm = postmaster
        self.low_avail = mem_available_kb()
        self.pg_anon_peak = 0
        self._stop = threading.Event()

    def _pg(self) -> list[int]:
        return [self.pm] + _children(self.pm) if self.pm else []

    def cpu(self) -> dict:
        own = resource.getrusage(resource.RUSAGE_SELF)
        pg = 0.0
        for pid in self._pg():
            a, b = _proc_cpu(pid)
            pg += a + (b if pid == self.pm else 0.0)
        return {"pg": pg, "py": own.ru_utime + own.ru_stime}

    def _sample(self):
        while not self._stop.wait(0.5):
            self.low_avail = min(self.low_avail, mem_available_kb())
            self.pg_anon_peak = max(self.pg_anon_peak, sum(_status(p, "RssAnon") for p in self._pg()))

    @contextmanager
    def phase(self, into: dict, name: str, runs: int = 0):
        before, t = self.cpu(), time.time()
        self._stop.clear()
        sampler = threading.Thread(target=self._sample, daemon=True)
        sampler.start()
        try:
            yield
        finally:
            self._stop.set()
            sampler.join()
            after = self.cpu()
            wall = time.time() - t
            got = {"wall_s": round(wall, 2), "pg_cpu_s": round(after["pg"] - before["pg"], 2),
                   "py_cpu_s": round(after["py"] - before["py"], 2)}
            if runs:
                got["pg_cpu_ms_per_run"] = round((after["pg"] - before["pg"]) * 1000 / runs, 2)
                got["py_cpu_ms_per_run"] = round((after["py"] - before["py"]) * 1000 / runs, 2)
            into[name] = got

    def memory(self) -> dict:
        return {"pg_anon_peak_mb": round(self.pg_anon_peak / 1024, 1),
                "py_peak_rss_mb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 1),
                "machine_lowest_available_mb": round(self.low_avail / 1024, 1)}


def machine(db) -> dict:
    """The machine and the database's settings, as this run found them."""
    import platform
    import socket

    total = 0
    try:
        with open("/proc/meminfo") as f:
            total = int(f.readline().split()[1])
    except OSError:
        pass
    cpu = ""
    try:
        with open("/proc/cpuinfo") as f:
            cpu = next((ln.split(":", 1)[1].strip() for ln in f if ln.startswith("model name")), "")
    except OSError:
        pass
    names = ("server_version", "shared_buffers", "work_mem", "effective_cache_size", "maintenance_work_mem",
             "max_parallel_workers_per_gather", "random_page_cost", "jit", "shared_preload_libraries")
    pg = {r["name"]: (r["setting"] + (r["unit"] or "")) for r in db.rows(
        "SELECT name, setting, unit FROM pg_settings WHERE name = ANY(%s)", (list(names),))}
    ext = {r["extname"]: r["extversion"] for r in db.rows("SELECT extname, extversion FROM pg_extension")}
    return {"host": socket.gethostname(), "cpus": os.cpu_count(), "cpu": cpu, "memory_gb": round(total / 1048576, 1),
            "kernel": platform.release(), "python": platform.python_version(), "postgres": pg, "extensions": ext}


def disk(db) -> dict:
    """Every Synapse table and its indexes, on disk."""
    tables = db.rows(
        "SELECT c.relname AS name, pg_table_size(c.oid) AS table_bytes, pg_indexes_size(c.oid) AS index_bytes "
        "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace WHERE n.nspname = 'synapse' "
        "AND c.relkind IN ('r', 'p') ORDER BY pg_total_relation_size(c.oid) DESC")
    indexes = db.rows(
        "SELECT c.relname AS name, t.relname AS on_table, pg_relation_size(c.oid) AS bytes FROM pg_index x "
        "JOIN pg_class c ON c.oid = x.indexrelid JOIN pg_class t ON t.oid = x.indrelid "
        "JOIN pg_namespace n ON n.oid = t.relnamespace WHERE n.nspname = 'synapse' "
        "AND pg_relation_size(c.oid) > 8 * 1024 * 1024 ORDER BY 3 DESC")
    mb = lambda b: round(int(b) / 1048576, 1)  # noqa: E731
    return {"database_mb": mb(db.value("SELECT pg_database_size(current_database())")),
            "tables": [{"name": t["name"], "table_mb": mb(t["table_bytes"]), "index_mb": mb(t["index_bytes"])}
                       for t in tables if int(t["table_bytes"]) + int(t["index_bytes"]) > 1048576],
            "indexes_over_8mb": [{"name": i["name"], "on": i["on_table"], "mb": mb(i["bytes"])} for i in indexes]}


# ---------------------------------------------------------------------------------------------
# the bulk: fictional mail, notes and documents (as on 3 October 2026, so sizes compare)
# ---------------------------------------------------------------------------------------------

class NoTrace:
    """What `link_candidates` writes its call to: nothing, here."""

    id = None
    dataset_id = None
    cost = 0.0

    def call(self, **kw):
        return None

    @contextmanager
    def step(self, *a, **kw):
        class S:
            data: dict = {}
        yield S()


def words() -> tuple[list[str], list[list[str]], list[str], list[str]]:
    """A vocabulary in English and Bulgarian, the subjects' own words, and names."""
    rng = random.Random(7)
    common = ("the and to of a in for is on that with you it this be are from at as your have we will can "
              "please thanks meeting call project invoice price offer client team report draft send attached "
              "today tomorrow week friday monday deadline plan design logo budget contract review notes update "
              "question answer office trip flight hotel order payment account delivery schedule").split()
    bg = ("и в на за да се от с по че това като но е ще са има много среща проект оферта фактура цена клиент "
          "екип доклад чернова изпрати прикачен днес утре седмица петък понеделник срок план дизайн лого бюджет "
          "договор преглед бележки въпрос отговор офис пътуване полет хотел поръчка плащане сметка доставка").split()
    lat = "b c d f g h k l m n p r s t v z".split()
    cyr = "б в г д ж з к л м н п р с т ф х ц ч ш".split()
    vow, cvow = "a e i o u".split(), "а е и о у ъ".split()
    seen, rare = set(common) | set(bg), []
    while len(rare) < 40000:
        if rng.random() < 0.7:
            w = "".join(rng.choice(lat) + rng.choice(vow) for _ in range(rng.randint(2, 4)))
        else:
            w = "".join(rng.choice(cyr) + rng.choice(cvow) for _ in range(rng.randint(2, 4)))
        if w not in seen:
            seen.add(w)
            rare.append(w)
    vocab = common + bg + rare
    topic_words = [rare[30000 + t * 40: 30000 + (t + 1) * 40] for t in range(TOPICS)]
    firsts = ("Maria Ivan Petko Elena Nedko Georgi Teresa Anna Dimitar Stefan Vera Boris Lili Martin Rosa Yana "
              "Kalin Mila Todor Diana Simeon Nadia Pavel Irina Viktor Zara Emil Galina Hristo Olga").split()
    lasts = ("Ivanova Petkov Stoyanov Georgieva Dimitrov Nikolova Popov Hristova Todorov Angelova Kolev Marinova "
             "Iliev Yordanova Stefanov Vasileva Atanasov Petkova Mihaylov Ruseva").split()
    return vocab, topic_words, firsts, lasts


#: Words drawn per row: a quarter from the item's subject, the rest from the whole vocabulary,
#: log-uniformly, so a few words are very common and most are rare, as in real mail. Each word
#: is its own correlated lookup, so PostgreSQL draws a new one every time.
TEXT = """(SELECT string_agg(CASE WHEN k.r < 0.25 THEN t.words[1 + floor(k.r * 160)::int] ELSE v.w END, ' ')
       FROM generate_series(1, {count}) gs
       CROSS JOIN LATERAL (SELECT random() AS r, least(%(nv)s, floor(exp(random() * ln(%(nv)s)))::int) + 0 * gs AS n) k
       JOIN bench_vocab v ON v.n = k.n)"""

WORDS_SQL = "to_tsvector('english', {w}) || to_tsvector('synapse.bg', {w}) || to_tsvector('simple', {w})"


def q(sql: str, params: dict) -> None:
    """One statement with named parameters, on Django's connection."""
    from django.db import connection

    with connection.cursor() as cur:
        cur.execute(sql, params)


def tenant(db, org: str, user: str, name: str, owner: str) -> dict:
    """A people set, a dataset pointing at it, and its owner as a person readable by everyone."""
    people_ds = db.value("INSERT INTO synapse.dataset (org_id, user_id, name, role, vec_model, owner_name) VALUES "
                         "(%s, %s, %s, 'people', 'bench-stub', %s) RETURNING id", (org, user, f"People ({name})", owner))
    ds = db.value("INSERT INTO synapse.dataset (org_id, user_id, name, people_id, vec_model, owner_name) VALUES "
                  "(%s, %s, %s, %s, 'bench-stub', %s) RETURNING id", (org, user, name, people_ds, owner))
    me = put_person(db, {"people": people_ds}, owner, f"{owner.split()[0].lower()}@{user}.example", key="me",
                    vec=None)
    db.run("UPDATE synapse.item SET owner = %s WHERE id = %s", (me, me))
    db.run("UPDATE synapse.dataset SET me_id = %s WHERE id IN (%s, %s)", (me, people_ds, ds))
    return {"ds": str(ds), "people": str(people_ds), "me": str(me), "persons": 0}


def put_person(db, t: dict, name: str, email: str, *, key: str, vec) -> str:
    pid = db.value("INSERT INTO synapse.item (dataset_id, kind, source, source_key, title, raw, body, said_at, "
                   "sensitivity, status, meta) VALUES (%s, 'person', 'case', %s, %s, %s, %s, now() - interval "
                   "'3 years', 'normal', 'ready', %s::jsonb) RETURNING id",
                   (t["people"], key, name, name, f"{name} <{email}>", json.dumps({"name": name, "origin": "bench"})))
    db.run("INSERT INTO synapse.identity (scope_id, item_id, type, value, shown, source) VALUES "
           "(%s, %s, 'email', %s, %s, 'bench')", (t["people"], pid, email.lower(), email))
    db.run("INSERT INTO synapse.reader VALUES (%s, %s, 'everyone')", (t["people"], pid))
    body = f"{name} <{email}>"
    db.run(f"INSERT INTO synapse.passage (dataset_id, item_id, seq, text, words, vec, embed_model) VALUES "
           f"(%s, %s, 1, %s, {WORDS_SQL.format(w='%s')}, %s::halfvec, 'bench-stub')",
           (t["people"], pid, body, body, body, body, db.vec(vec) if vec else None))
    return str(pid)


def setup(db, vocab, topic_words, firsts, lasts) -> dict:
    """The two people's datasets, the readers, the vocabulary and the subjects' vectors."""
    db.run("SELECT setseed(0.42)")
    me = tenant(db, "bench", "bench", "Bench", "Owner Bench")
    other = tenant(db, "bench", "mallory", "Mallory bench", "Mallory Other")
    # Two more people in the owner's set: Vera reads a small share of the owner's items, and Mallory
    # (the other dataset's owner, known here by the same address) reads only what is shared with her.
    vera = put_person(db, me, "Vera Reader", "vera@bench.example", key="vera", vec=None)
    mallory_p = put_person(db, me, "Mallory Other", "mallory@mallory.example", key="mallory", vec=None)
    db.run("CREATE TABLE bench_ids (k text PRIMARY KEY, v jsonb)")
    ids = {"me_t": me, "other_t": other, "vera": vera, "mallory_p": mallory_p}
    db.run("INSERT INTO bench_ids VALUES ('ids', %s::jsonb)", (json.dumps(ids),))
    db.run("CREATE TABLE bench_vocab (n int PRIMARY KEY, w text)")
    db.run("INSERT INTO bench_vocab SELECT n, w FROM unnest(%s::text[]) WITH ORDINALITY AS x(w, n)", (vocab,))
    db.run("CREATE TABLE bench_topic (t int PRIMARY KEY, words text[], c vector(1024))")
    rng = random.Random(3)
    centroids = []
    for t in range(TOPICS):
        c = [rng.gauss(0, 1) for _ in range(DIMS)]
        centroids.append(c)
        db.run("INSERT INTO bench_topic VALUES (%s, %s, %s::vector)", (t, topic_words[t], db.vec(c)))
    # Noise to add to a subject's vector: two of 1,024 each, so few passages share a vector.
    db.run("CREATE TABLE bench_noise (n int PRIMARY KEY, v vector(1024))")
    for n in range(2048):
        db.run("INSERT INTO bench_noise VALUES (%s, %s::vector)", (n, db.vec([rng.gauss(0, 0.55) for _ in range(DIMS)])))
    db.run("CREATE TABLE bench_name (n int PRIMARY KEY, first text, last text)")
    db.run("INSERT INTO bench_name SELECT row_number() OVER (), f, l FROM unnest(%s::text[]) f, unnest(%s::text[]) l",
           (firsts, lasts))
    db.run("CREATE TABLE bench_case (id serial PRIMARY KEY, family text, kind text, tenant text, asker text, "
           "question text, qvec vector(1024), src uuid, gold uuid[], forbidden uuid[], secret text[], k int, "
           "meta jsonb DEFAULT '{}')")
    ids["centroids"] = centroids
    return ids


def again(db) -> dict | None:
    """What `setup` made, when this database was kept from an earlier run."""
    if not db.value("SELECT to_regclass('public.bench_ids') IS NOT NULL"):
        return None
    ids = db.value("SELECT v FROM bench_ids WHERE k = 'ids'")
    ids = json.loads(ids) if isinstance(ids, str) else ids
    cents = {r["t"]: [float(x) for x in r["c"].strip("[]").split(",")]
             for r in db.rows("SELECT t, c::text AS c FROM bench_topic ORDER BY t")}
    ids["centroids"] = [cents[t] for t in range(TOPICS)]
    for name in ("me_t", "other_t"):
        t = ids[name]
        t["persons"] = int(db.value("SELECT count(*) FROM synapse.item WHERE dataset_id = %s AND source = 'bench' "
                                    "AND source_key LIKE 'person-%%'", (t["people"],)))
    return ids


def load(db, t: dict, have: int, size: int, people_now: int, say, *, vera: str | None, nv: int) -> None:
    """Items `have + 1` to `size` of one dataset, and its people up to `people_now`, straight into the tables."""
    have_people = t["persons"]
    if people_now > have_people:
        q("""
        INSERT INTO synapse.item (dataset_id, kind, source, source_key, title, raw, body, said_at, sensitivity,
                                  owner, status, meta)
        SELECT %(p)s, 'person', 'bench', 'person-' || g, f.first || ' ' || f.last || ' ' || g,
               f.first || ' ' || f.last, f.first || ' ' || f.last || ' <' || lower(f.first) || '.' || g || '@example.org>',
               now() - interval '3 years', 'normal', %(me)s, 'ready',
               jsonb_build_object('name', f.first || ' ' || f.last, 'origin', 'bench')
        FROM generate_series(%(a)s, %(b)s) g JOIN bench_name f ON f.n = 1 + g %% 600
        """, {"p": t["people"], "me": t["me"], "a": have_people + 1, "b": people_now})
        rng_sql = "split_part(source_key, '-', 2)::int BETWEEN %s AND %s"
        db.run("INSERT INTO synapse.identity (scope_id, item_id, type, value, shown, source) "
               "SELECT dataset_id, id, 'email', lower(split_part(title, ' ', 1)) || '.' || split_part(source_key, '-', 2) "
               "|| '@example.org', '', 'bench' FROM synapse.item WHERE dataset_id = %s AND kind = 'person' "
               f"AND source = 'bench' AND source_key LIKE 'person-%%' AND {rng_sql}",
               (t["people"], have_people + 1, people_now))
        db.run("INSERT INTO synapse.reader SELECT dataset_id, id, 'everyone' FROM synapse.item WHERE dataset_id = %s "
               f"AND kind = 'person' AND source = 'bench' AND source_key LIKE 'person-%%' AND {rng_sql}",
               (t["people"], have_people + 1, people_now))
        db.run("INSERT INTO synapse.passage (dataset_id, item_id, seq, text, words, vec, embed_model) "
               "SELECT dataset_id, id, 1, body, to_tsvector('english', body) || to_tsvector('synapse.bg', body) || "
               "to_tsvector('simple', body), (t.c + n.v)::halfvec, 'bench-stub' FROM synapse.item i "
               "JOIN bench_topic t ON t.t = abs(hashtext(i.id::text)) %% 64 "
               "JOIN bench_noise n ON n.n = abs(hashtext(i.source_key)) %% 2048 "
               "WHERE dataset_id = %s AND kind = 'person' AND source = 'bench' AND source_key LIKE 'person-%%' "
               f"AND {rng_sql}", (t["people"], have_people + 1, people_now))
        t["persons"] = people_now
    step = 10000
    for a in range(have + 1, size + 1, step):
        b = min(size, a + step - 1)
        if (a - have - 1) % 100000 == 0:
            say(f"  {t['name']}: items {a:,} to {min(size, a + 99999):,}")
        load_items(db, t, a, b, people_now, nv, vera)


def load_items(db, t: dict, a: int, b: int, people_now: int, nv: int, vera: str | None) -> None:
    p = {"ds": t["ds"], "pp": t["people"], "me": t["me"], "a": a, "b": b, "np": people_now, "nv": nv,
         "vera": vera or "", "tag": t["tag"]}
    db.run("CREATE TABLE IF NOT EXISTS bench_thread (tag text, thread int, item uuid, PRIMARY KEY (tag, thread))")
    db.run("CREATE TEMP TABLE IF NOT EXISTS bench_new (g int PRIMARY KEY, topic int, words int, kind text, "
           "said timestamptz, sender int, rcpt int[], thread int)")
    db.run("TRUNCATE bench_new")
    q("""
    INSERT INTO bench_new
    SELECT g, abs(hashtext('t' || g)) %% 64,
           least(900, 30 + floor(exp(random() * ln(600)))::int),
           CASE WHEN random() < 0.9 THEN 'mail' WHEN random() < 0.5 THEN 'note' ELSE 'doc' END,
           now() - random() * interval '3 years',
           1 + floor(power(random(), 2) * %(np)s)::int,
           ARRAY(SELECT 1 + floor(power(random(), 2) * %(np)s)::int FROM generate_series(1, 1 + (g %% 3))),
           1 + (g / 3) + (g %% 7)
    FROM generate_series(%(a)s, %(b)s) g
    """, p)
    q(f"""
    INSERT INTO synapse.item (dataset_id, kind, source, source_key, title, raw, body, said_at, sensitivity, owner,
                              status, tier, meta)
    SELECT %(ds)s, n.kind, 'bench', 'bench-' || n.g, title, body, body, n.said,
           CASE WHEN r < 0.85 THEN 'normal' WHEN r < 0.9 THEN 'special' ELSE 'unlabelled' END, %(me)s, 'ready', 1,
           jsonb_build_object('from', 'x <' || lower(fn.first) || '.' || n.sender || '@example.org>',
                              'to', (SELECT jsonb_agg('y <' || lower(i.first) || '.' || x || '@example.org>')
                                     FROM unnest(n.rcpt) x JOIN bench_name i ON i.n = 1 + x %% 600),
                              'thread', %(tag)s || 'thr-' || n.thread)
    FROM bench_new n JOIN bench_topic t ON t.t = n.topic JOIN bench_name fn ON fn.n = 1 + n.sender %% 600,
         LATERAL (SELECT {TEXT.format(count='4 + (n.g %% 5)')} AS title, {TEXT.format(count='n.words')} AS body,
                         random() AS r) x
    """, p)
    # Readers: the owner for most, everyone for a tenth; Vera too for one in fifty of the owner's.
    q("INSERT INTO synapse.reader SELECT dataset_id, id, CASE WHEN random() < 0.1 THEN 'everyone' ELSE %(me)s END "
      "FROM synapse.item i JOIN bench_new b ON i.dataset_id = %(ds)s AND i.source = 'bench' "
      "AND i.source_key = 'bench-' || b.g", p)
    if vera:
        q("INSERT INTO synapse.reader SELECT dataset_id, id, %(vera)s FROM synapse.item i JOIN bench_new b "
          "ON i.dataset_id = %(ds)s AND i.source = 'bench' AND i.source_key = 'bench-' || b.g "
          "WHERE abs(hashtext('v' || i.id::text)) %% 50 = 0 ON CONFLICT DO NOTHING", p)
    # Passages of about 300 words, the way write_passages cuts them, and an X-ray passage for most.
    q("""
    INSERT INTO synapse.passage (dataset_id, item_id, seq, text, words, vec, embed_model)
    SELECT i.dataset_id, i.id, k.seq, k.part,
           to_tsvector('english', k.w) || to_tsvector('synapse.bg', k.w) || to_tsvector('simple', k.w),
           (t.c + n1.v + n2.v)::halfvec, 'bench-stub'
    FROM synapse.item i JOIN bench_new b ON i.dataset_id = %(ds)s AND i.source = 'bench' AND i.source_key = 'bench-' || b.g
    JOIN bench_topic t ON t.t = b.topic
    CROSS JOIN LATERAL (
      SELECT s AS seq, array_to_string((regexp_split_to_array(i.body, ' '))[(s - 1) * 300 + 1: s * 300], ' ') AS part,
             CASE WHEN s = 1 THEN i.title || ' ' ELSE '' END ||
             array_to_string((regexp_split_to_array(i.body, ' '))[(s - 1) * 300 + 1: s * 300], ' ') AS w
      FROM generate_series(1, 1 + (b.words - 1) / 300) s) k
    JOIN bench_noise n1 ON n1.n = abs(hashtext(i.id::text || k.seq)) %% 1024
    JOIN bench_noise n2 ON n2.n = 1024 + abs(hashtext(k.seq || i.id::text)) %% 1024
    """, p)
    q("""
    INSERT INTO synapse.passage (dataset_id, item_id, seq, text, words, from_xray, vec, embed_model)
    SELECT i.dataset_id, i.id, NULL, x.t, to_tsvector('english', x.t) || to_tsvector('synapse.bg', x.t)
           || to_tsvector('simple', x.t), true, (t.c + n1.v)::halfvec, 'bench-stub'
    FROM synapse.item i JOIN bench_new b ON i.dataset_id = %(ds)s AND i.source = 'bench' AND i.source_key = 'bench-' || b.g
    JOIN bench_topic t ON t.t = b.topic
    JOIN bench_noise n1 ON n1.n = abs(hashtext('x' || i.id::text)) %% 2048,
    LATERAL (SELECT i.title || ': ' || array_to_string(t.words[1:6], ' ') AS t) x
    WHERE abs(hashtext(i.id::text)) %% 10 < 7
    """, p)
    # Code links: from and to the people, and each item to its thread's first item.
    q("""
    INSERT INTO synapse.link (dataset_id, src, dst, type, strength, base_strength, origin, made_by)
    SELECT %(ds)s, i.id, p.id, 'from', 0.6, 0.6, 'code', 'code'
    FROM synapse.item i JOIN bench_new b ON i.dataset_id = %(ds)s AND i.source = 'bench' AND i.source_key = 'bench-' || b.g
    JOIN synapse.item p ON p.dataset_id = %(pp)s AND p.source = 'bench' AND p.source_key = 'person-' || b.sender
    ON CONFLICT DO NOTHING
    """, p)
    q("""
    INSERT INTO synapse.link (dataset_id, src, dst, type, strength, base_strength, origin, made_by)
    SELECT %(ds)s, i.id, p.id, 'to', 0.5, 0.5, 'code', 'code'
    FROM synapse.item i JOIN bench_new b ON i.dataset_id = %(ds)s AND i.source = 'bench' AND i.source_key = 'bench-' || b.g
    CROSS JOIN unnest(b.rcpt) r JOIN synapse.item p ON p.dataset_id = %(pp)s AND p.source = 'bench' AND p.source_key = 'person-' || r
    ON CONFLICT DO NOTHING
    """, p)
    q("""
    INSERT INTO bench_thread SELECT DISTINCT ON (b.thread) %(tag)s, b.thread, i.id
    FROM bench_new b JOIN synapse.item i ON i.dataset_id = %(ds)s AND i.source = 'bench' AND i.source_key = 'bench-' || b.g
    ORDER BY b.thread, b.g ON CONFLICT DO NOTHING
    """, p)
    q("""
    INSERT INTO synapse.link (dataset_id, src, dst, type, strength, base_strength, origin, made_by)
    SELECT %(ds)s, i.id, th.item, 'in_thread', 0.9, 0.9, 'code', 'code'
    FROM bench_new b JOIN synapse.item i ON i.dataset_id = %(ds)s AND i.source = 'bench' AND i.source_key = 'bench-' || b.g
    JOIN bench_thread th ON th.tag = %(tag)s AND th.thread = b.thread AND th.item <> i.id
    ON CONFLICT DO NOTHING
    """, p)


#: The indexes a bulk load drops and builds again after; what any bulk load does, only in this database.
BULK_INDEXES = {
    "passage_words": "CREATE INDEX IF NOT EXISTS passage_words ON synapse.passage USING gin (words)",
    "passage_trgm": "CREATE INDEX IF NOT EXISTS passage_trgm ON synapse.passage USING gin (text gin_trgm_ops)",
    # As migration 0076 builds it: m 32, ef_construction 128.
    "passage_vec": "CREATE INDEX IF NOT EXISTS passage_vec ON synapse.passage USING hnsw (vec halfvec_cosine_ops) "
                   "WITH (m = 32, ef_construction = 128)",
}


def bulk_off(db) -> None:
    db.run("SET synchronous_commit = off")
    pg_search_column(db)
    for name in [*BULK_INDEXES, "passage_bm25"]:  # pg_search's is built again after, by pg_search_index
        db.run(f"DROP INDEX IF EXISTS synapse.{name}")


def bulk_on(db, say, mwm_mb: int) -> None:
    db.run(f"SET maintenance_work_mem = '{int(mwm_mb)}MB'")
    db.run("SET max_parallel_maintenance_workers = 6")
    for name, sql in BULK_INDEXES.items():
        t = time.time()
        db.run(sql)
        say(f"  index {name} in {time.time() - t:.0f} s")
    for table in ("item", "passage", "link", "identity", "reader"):
        db.run(f"VACUUM ANALYZE synapse.{table}")
    if db.value("SELECT to_regclass('synapse.term_delta') IS NOT NULL"):
        db.run("SELECT synapse.term_fold()")  # as Rouh's worker does every ten seconds
        db.run("VACUUM ANALYZE synapse.term_df")
        db.run("VACUUM ANALYZE synapse.term_delta")


# ---------------------------------------------------------------------------------------------
# the cases: items planted with known answers
# ---------------------------------------------------------------------------------------------

class Planter:
    """Writes planted items, the way the bulk is written, and the cases that ask about them."""

    def __init__(self, db, ids: dict, vocab: list[str], rng: random.Random):
        self.db, self.ids, self.vocab, self.rng = db, ids, vocab, rng
        self.used: set[str] = set(vocab)
        self.n = 0

    # words -----------------------------------------------------------------------------------
    def code(self, cyrillic: bool = False) -> str:
        """A made-up word no bulk item holds: letters the bulk never draws (q x w y j, or щ ю я й)."""
        while True:
            if cyrillic:
                w = self.rng.choice("щюяй") + "".join(self.rng.choice("бвгдзклмнпрст") + self.rng.choice("аеиоу")
                                                     for _ in range(self.rng.randint(2, 3)))
            else:
                w = self.rng.choice("qxwj") + "".join(self.rng.choice("bdfgklmnprstvz") + self.rng.choice("aeiou")
                                                     for _ in range(self.rng.randint(2, 3)))
            if w not in self.used:
                self.used.add(w)
                return w

    def filler(self, n: int) -> list[str]:
        nv = len(self.vocab)
        return [self.vocab[min(nv, int(math.exp(self.rng.random() * math.log(nv)))) - 1] for _ in range(n)]

    def text(self, keep: list[str], n: int) -> str:
        parts = self.filler(n) + keep
        self.rng.shuffle(parts)
        return " ".join(parts)

    def vec(self, topic: int, sd: float = 0.78) -> list[float]:
        c = self.ids["centroids"][topic]
        return [x + self.rng.gauss(0, sd) for x in c]

    def near(self, v: list[float], sd: float) -> list[float]:
        return [x + self.rng.gauss(0, sd) for x in v]

    def blend(self, v: list[float], cos: float) -> list[float]:
        """A vector at about `cos` to `v`: v mixed with another subject's, the mix found by halving."""
        other = self.vec(self.topic())
        lo, hi = 0.0, 4.0
        for _ in range(30):
            a = (lo + hi) / 2
            w = [a * x + y for x, y in zip(v, other)]
            got = sum(x * y for x, y in zip(w, v)) / math.sqrt(sum(x * x for x in w) * sum(x * x for x in v))
            lo, hi = (a, hi) if got < cos else (lo, a)
        return w

    def topic(self) -> int:
        return self.rng.randrange(TOPICS)

    # rows ------------------------------------------------------------------------------------
    def item(self, t: dict, *, title: str, body: str, days_ago: float, readers: list[str], vec,
             kind: str = "mail", sens: str = "normal", owner: str | None = None, meta: dict | None = None,
             key: str | None = None, mentions: dict | None = None, deleted: bool = False, xray: bool = True,
             people: tuple = ()) -> str:
        db = self.db
        self.n += 1
        key = key or f"case-{self.n}"
        iid = str(db.value(
            "INSERT INTO synapse.item (dataset_id, kind, source, source_key, title, raw, body, said_at, sensitivity, "
            "owner, status, tier, meta, mentions) VALUES (%s, %s, 'case', %s, %s, %s, %s, now() - make_interval("
            "secs => %s), %s, %s, 'ready', 1, %s::jsonb, %s::jsonb) RETURNING id",
            (t["ds"], kind, key, title, body, body, float(days_ago) * 86400, sens, owner or t["me"],
             json.dumps(meta or {}), json.dumps(mentions) if mentions else None)))
        for r in readers:
            db.run("INSERT INTO synapse.reader VALUES (%s, %s, %s) ON CONFLICT DO NOTHING", (t["ds"], iid, r))
        ws = body.split()
        for s in range(1 + max(0, len(ws) - 1) // 300):
            part = " ".join(ws[s * 300:(s + 1) * 300])
            w = (title + " " + part) if s == 0 else part
            db.run(f"INSERT INTO synapse.passage (dataset_id, item_id, seq, text, words, vec, embed_model) VALUES "
                   f"(%s, %s, %s, %s, {WORDS_SQL.format(w='%s')}, %s::halfvec, 'bench-stub')",
                   (t["ds"], iid, s + 1, part, w, w, w, db.vec(self.near(vec, 0.15)) if vec else None))
        if xray:
            x = title + ": " + " ".join(ws[:12])
            db.run(f"INSERT INTO synapse.passage (dataset_id, item_id, seq, text, words, from_xray, vec, embed_model) "
                   f"VALUES (%s, %s, NULL, %s, {WORDS_SQL.format(w='%s')}, true, %s::halfvec, 'bench-stub')",
                   (t["ds"], iid, x, x, x, x, db.vec(vec) if vec else None))
        for pid, typ in people:
            # The links code writes when an item is stored (`ingest.code_links`): from and to its people.
            db.run("INSERT INTO synapse.link (dataset_id, src, dst, type, strength, base_strength, origin, made_by) "
                   "VALUES (%s, %s, %s, %s, 0.6, 0.6, 'code', 'code') ON CONFLICT DO NOTHING", (t["ds"], iid, pid, typ))
        if deleted:
            db.run("UPDATE synapse.item SET deleted_at = now() WHERE id = %s", (iid,))
        return iid

    def link(self, t: dict, src: str, dst: str, typ: str = "about", strength: float = 0.7) -> None:
        self.db.run("INSERT INTO synapse.link (dataset_id, src, dst, type, strength, base_strength, origin, made_by) "
                    "VALUES (%s, %s, %s, %s, %s, %s, 'model', 'bench') ON CONFLICT DO NOTHING",
                    (t["ds"], src, dst, typ, strength, strength))

    def case(self, family: str, kind: str, *, tenant: str = "me_t", asker: str = "me", question: str = "",
             qvec=None, src: str | None = None, gold=(), forbidden=(), secret=(), k: int = 10, meta=None) -> None:
        self.db.run("INSERT INTO bench_case (family, kind, tenant, asker, question, qvec, src, gold, forbidden, "
                    "secret, k, meta) VALUES (%s, %s, %s, %s, %s, %s::vector, %s, %s::uuid[], %s::uuid[], %s, %s, "
                    "%s::jsonb)", (family, kind, tenant, asker, question, self.db.vec(qvec) if qvec else None, src,
                                  list(gold), list(forbidden), list(secret), k, json.dumps(meta or {})))


def plant(db, ids: dict, vocab: list[str], topic_words: list[list[str]], say) -> None:
    """Every case, once. Ask with the case's question and vector; the answers are known by construction."""
    from .. import text as tx

    if db.value("SELECT count(*) FROM bench_case"):
        return
    rng = random.Random(CASE_SEED)
    P = Planter(db, ids, vocab, rng)
    me_t, other_t = ids["me_t"], ids["other_t"]
    me, vera, mp, mal = me_t["me"], ids["vera"], ids["mallory_p"], other_t["me"]
    common = vocab[8:60]

    # --- ranking -----------------------------------------------------------------------------
    for i in range(20):  # a rare name buried under common words
        name = P.code().capitalize()
        cw = rng.sample(common, 3)
        top = P.topic()
        gold = P.item(me_t, title=f"Note from {name}", body=P.text([name, name] + cw, 120), days_ago=rng.uniform(1, 900),
                      readers=[me], vec=P.vec(top))
        for _ in range(5):
            P.item(me_t, title=" ".join(cw), body=P.text(cw * 6, 200), days_ago=rng.uniform(1, 900), readers=[me],
                   vec=P.vec(top))
        P.case("rank_rare_name", "search", question=" ".join([name.lower()] + cw), qvec=ids["centroids"][top],
               gold=[gold], k=10)
    # Four words of the vocabulary's middle (ranks 150 to 400: each in some 5 to 12% of passages),
    # met together in one item only; asked when it is old, and when it is recent.
    mid = vocab[150:400]
    for i in range(30):
        ws = rng.sample(mid, 4)
        old = i < 20
        top = P.topic()
        gold = P.item(me_t, title=" ".join(ws[:2]), body=P.text(ws * 3, 30),
                      days_ago=rng.uniform(700, 1050) if old else rng.uniform(1, 30), readers=[me], vec=P.vec(top))
        P.case("rank_common_words_old" if old else "rank_common_words_recent", "search", question=" ".join(ws),
               qvec=ids["centroids"][top], gold=[gold], k=10)
    for i in range(15):  # how often against how long: the short item about it beats the long one
        w = P.code()
        top = P.topic()
        gold = P.item(me_t, title=P.text([], 4), body=P.text([w] * 4, 60), days_ago=rng.uniform(1, 900),
                      readers=[me], vec=P.vec(top))
        for _ in range(3):
            P.item(me_t, title=P.text([], 4), body=P.text([w], 600), days_ago=rng.uniform(1, 900), readers=[me],
                   vec=P.vec(top))
        P.case("rank_tf_length", "search", question=w + " " + " ".join(rng.sample(common, 2)),
               qvec=ids["centroids"][top], gold=[gold], k=1)
    for i in range(20):  # meaning alone, the owner asking; and a reader who sees a small share
        for who, readers, fam in (("me", [me], "rank_meaning_only"), ("vera", [me, vera], "rank_meaning_minority")):
            v = P.vec(P.topic())
            gold = P.item(me_t, title=P.text([], 4), body=P.text([], 150), days_ago=rng.uniform(1, 900),
                          readers=readers, vec=v)
            P.case(fam, "search", asker=who, question=" ".join(rng.sample(common, 3)), qvec=P.near(v, 0.25),
                   gold=[gold], k=10)
    for i in range(10):  # a Cyrillic name asked in Latin letters
        name = P.code(cyrillic=True)
        latin = tx.other_alphabet(name)
        if tx.other_alphabet(latin) != name:
            continue
        top = P.topic()
        gold = P.item(me_t, title=f"Писмо от {name.capitalize()}", body=P.text([name, name], 100),
                      days_ago=rng.uniform(1, 900), readers=[me], vec=P.vec(top))
        P.case("rank_other_alphabet", "search", question=latin + " " + rng.choice(common),
               qvec=ids["centroids"][top], gold=[gold], k=10)
    for i in range(10):  # the latest of a subject's items
        a, b = P.code(), P.code()
        top = P.topic()
        items = [P.item(me_t, title=f"{a} {b} update", body=P.text([a, b], 120), days_ago=d, readers=[me],
                        vec=P.vec(top)) for d in (rng.uniform(1, 20), 200, 420, 640, 900)]
        P.case("time_latest", "search", question=f"{a} {b} latest", qvec=ids["centroids"][top], gold=[items[0]],
               k=3, meta={"older": items[1:]})
    for i in range(10):  # old but relevant: the only item with both words is two and a half years old
        a, b = P.code(), P.code()
        top = P.topic()
        gold = P.item(me_t, title=f"{a} and {b}", body=P.text([a, b, a], 120), days_ago=rng.uniform(850, 1000),
                      readers=[me], vec=P.vec(top))
        for j in range(6):
            P.item(me_t, title=P.text([], 4), body=P.text([a if j % 2 else b], 150), days_ago=rng.uniform(1, 60),
                   readers=[me], vec=P.vec(top))
        P.case("time_old_relevant", "search", question=f"{a} {b}", qvec=ids["centroids"][top], gold=[gold], k=10)

    # --- permissions -------------------------------------------------------------------------
    # (family, the item's dataset, readers, sensitivity, owner, deleted, who may read it)
    perms = [("perm_reader_other", me_t, [mp], "normal", me, False, {"mallory_p"}),
             ("perm_special_not_owner", me_t, [me, vera], "special", vera, False, {"vera"}),
             ("perm_unlabelled_not_owner", me_t, [me, vera], "unlabelled", vera, False, {"vera"}),
             ("perm_deleted", me_t, [me, vera, mp], "normal", me, True, set()),
             ("perm_other_dataset", other_t, ["everyone"], "normal", mal, False, {"mallory"}),
             ("perm_everyone", me_t, ["everyone"], "normal", me, False, {"me", "vera", "mallory_p"})]
    for fam, t, readers, sens, owner, deleted, allowed in perms:
        for i in range(8 if fam != "perm_everyone" else 5):
            # s1 and s2 are asked; s3 is in its words only, so finding s3 in a pack or a trace means the
            # item's own words got there, not the question's.
            s1, s2, s3 = P.code(), P.code(), P.code()
            v = P.vec(P.topic())
            secret = P.item(t, title=f"{s1} {s2}", body=P.text([s1, s2, s1, s3], 80), days_ago=rng.uniform(1, 400),
                            readers=readers, sens=sens, owner=owner, vec=v, deleted=deleted)
            ask = dict(question=f"{s1} {s2}", qvec=P.near(v, 0.1), k=10)
            if t is me_t:
                for who in ("me", "vera", "mallory_p"):
                    ok = who in allowed
                    P.case(fam, "search", asker=who, gold=[secret] if ok else [], forbidden=[] if ok else [secret],
                           secret=[] if ok else [s3], **ask)
                # Mallory, in her own dataset, never reaches the owner's.
                P.case(fam, "search", tenant="other_t", asker="mallory", forbidden=[secret], secret=[s3], **ask)
                continue
            # The same words in the owner's dataset too, readable there by Mallory alone: a second way in.
            copy = P.item(me_t, title=f"{s1} {s2}", body=P.text([s1, s2, s3], 80), days_ago=rng.uniform(1, 400),
                          readers=[mp], vec=v)
            for who in ("me", "vera"):
                P.case(fam, "search", asker=who, forbidden=[secret, copy], secret=[s3], **ask)
            P.case(fam, "search", asker="mallory_p", gold=[copy], forbidden=[secret], **ask)
            P.case(fam, "search", tenant="other_t", asker="mallory", gold=[secret], **ask)

    # --- links -------------------------------------------------------------------------------
    def person(name):
        P.n += 1
        email = f"{name.lower()}.{P.n}@case.example"
        return put_person(db, me_t, f"{name} Case", email, key=f"case-person-{P.n}", vec=P.vec(P.topic())), email

    def mail(**kw):
        kw.setdefault("readers", [me])
        kw.setdefault("days_ago", rng.uniform(1, 900))
        kw.setdefault("vec", P.vec(P.topic()))
        kw.setdefault("title", P.text([], 5))
        kw.setdefault("body", P.text([], 150))
        return P.item(me_t, **kw)

    for i in range(10):
        thr = f"case-thread-{i}"
        b = mail(meta={"thread": thr})
        a = mail(meta={"thread": thr})
        P.case("link_thread", "link", src=a, gold=[b], k=20)
    for i in range(5):
        b = mail(key=f"case-reply-parent-{i}")
        a = mail(meta={"reply_to": f"case-reply-parent-{i}"})
        P.case("link_reply", "link", src=a, gold=[b], k=20)
    for i in range(10):
        pid, email = person(P.code().capitalize())
        a = mail(meta={"from": f"Someone <{email}>"}, people=((pid, "from"),))
        P.case("link_sender", "link", src=a, gold=[pid], k=20)
    for i in range(10):
        pid, email = person(P.code().capitalize())
        a = mail(meta={"from": "x <nobody@example.org>", "to": [f"Them <{email}>"]}, people=((pid, "to"),))
        P.case("link_recipient", "link", src=a, gold=[pid], k=20)
    for i in range(10):
        a = mail(key=f"case-mail-with-file-{i}")
        f = mail(kind="file", key=f"sha256:{i:064x}", meta={"attached_to": [f"case-mail-with-file-{i}"],
                                                          "sha256": f"{i:064x}"})
        P.case("link_file", "link", src=a, gold=[f], k=20)
    for i in range(5):
        h = f"{1000 + i:064x}"
        e = mail(key=f"case-mail-same-hash-{i}")
        f = mail(kind="file", key=f"sha256:{h}", meta={"attached_to": [f"case-mail-same-hash-{i}"], "sha256": h})
        a = mail(kind="doc", key=f"case-doc-same-hash-{i}", meta={"sha256": h, "file_name": "contract.pdf"})
        P.case("link_same_file_hash", "link", src=a, gold=[f], k=20, meta={"email": e})
    for i in range(10):
        name = P.code().capitalize()
        pid, email = person(name)
        # Named in the text, not on the envelope; known to this dataset from an older email of theirs.
        mail(meta={"from": f"{name} <{email}>"}, people=((pid, "from"),), days_ago=rng.uniform(900, 1000))
        a = mail(mentions={"people_mentioned": [{"full_name_as_written": f"{name} Case", "emails": [email]}]})
        P.case("link_mention", "link", src=a, gold=[pid], k=20)
    for i in range(10):
        v = P.vec(P.topic())
        b = mail(vec=P.near(v, 0.3))
        a = mail(vec=P.near(v, 0.3))
        P.case("link_meaning", "link", src=a, gold=[b], k=20)
    for i in range(10):
        ws = [P.code() for _ in range(3)]
        b = mail(body=P.text(ws, 150))
        a = mail(body=P.text(ws, 150))
        P.case("link_rare_words", "link", src=a, gold=[b], k=20)
    for i in range(5):
        thr = f"case-big-thread-{i}"
        for _ in range(25):
            mail(meta={"thread": thr})
        ws = [P.code() for _ in range(3)]
        b = mail(body=P.text(ws, 150))
        a = mail(body=P.text(ws, 150), meta={"thread": thr})
        P.case("link_beside_big_thread", "link", src=a, gold=[b], k=20)
    for i in range(10):
        ws = [P.code() for _ in range(3)]
        v = P.vec(P.topic())
        c = mail(body=P.text(ws, 150), vec=P.near(v, 0.2), readers=[mp])
        a = mail(body=P.text(ws, 150), vec=P.near(v, 0.2))
        P.case("link_forbidden", "link", src=a, forbidden=[c], secret=[], k=20)

    # --- traversal ---------------------------------------------------------------------------
    for i in range(10):
        q1, q2 = P.code(), P.code()
        v = P.vec(P.topic())
        a = mail(title=f"{q1} {q2}", body=P.text([q1, q2, q1], 120), vec=v)
        # Related to the question but less than the subject's own items (cosine about 0.45, theirs about
        # 0.6), and recent: reached through the links, not found by the search.
        b = mail(vec=P.blend(v, 0.45), days_ago=rng.uniform(1, 10))
        c = mail(vec=P.blend(v, 0.45), days_ago=rng.uniform(1, 10))
        s1 = P.code()
        d = mail(title=f"{s1} {q1}", body=P.text([s1, q1], 120), vec=P.near(v, 0.3), readers=[mp])
        P.link(me_t, a, b, "about", 0.8)
        P.link(me_t, b, c, "about", 0.8)
        P.link(me_t, a, d, "about", 0.9)
        P.case("walk_chain", "walk", question=f"{q1} {q2}", qvec=P.near(v, 0.1), gold=[a, b], forbidden=[d],
               secret=[s1], k=0, meta={"second": c})
    say(f"  planted {P.n} case items and {db.value('SELECT count(*) FROM bench_case')} cases")


# ---------------------------------------------------------------------------------------------
# measuring
# ---------------------------------------------------------------------------------------------

def pct(values: list[float], p: float) -> float | None:
    if not values:
        return None
    v = sorted(values)
    i = min(len(v) - 1, max(0, int(round(p / 100 * (len(v) - 1)))))
    return round(v[i], 1)


def timing(ms: list[float], errors: int = 0) -> dict:
    return {"p50_ms": pct(ms, 50), "p95_ms": pct(ms, 95), "max_ms": pct(ms, 100), "runs": len(ms), "errors": errors}


class Rule:
    """Who may read what, worked out again from the tables for every result: never from `can_read`."""

    def __init__(self, db):
        self.db = db
        from .. import search
        self.sql = search.readable_rule_sql("i")

    def bad(self, ds_id: str, ids, asker: str) -> list[str]:
        ids = list({str(x) for x in ids})
        if not ids:
            return []
        readers = [asker, "everyone"]
        ok = {r["id"] for r in self.db.rows(
            "SELECT i.id FROM synapse.item i WHERE i.id = ANY(%s::uuid[]) AND i.dataset_id = ANY(synapse.scope(%s)) "
            "AND i.deleted_at IS NULL AND synapse.reaches(%s, i.dataset_id, i.id) AND " + self.sql,
            (ids, ds_id, ds_id, readers, readers))}
        return [x for x in ids if x not in ok]


def _reset(db, timeout_s):
    from django.db import connection
    connection.close()
    db.run(f"SET statement_timeout = '{int(timeout_s)}s'")


def bench_question(rng, vocab, topic_words, firsts) -> tuple[str, int]:
    """A made-up question: a subject's words, a few ordinary ones, sometimes a name (3 October 2026)."""
    topic = rng.randrange(TOPICS)
    parts = rng.sample(topic_words[topic], 2) + [vocab[int(rng.paretovariate(0.8)) % 2000] for _ in range(rng.randint(1, 4))]
    if rng.random() < 0.4:
        parts.append(rng.choice(firsts))
    rng.shuffle(parts)
    return " ".join(parts), topic


def _parse(v):
    if v is None:
        return None
    return [float(x) for x in str(v).strip("[]").split(",")]


def measure(db, ids: dict, override: dict, *, samples: int, timeout_s: int, vocab, topic_words, firsts, meter,
            say, size: int) -> dict:
    """One configuration, everything: timings, cases, leaks, resources."""
    from .. import datasets, ingest, recall, search

    me_t, other_t = ids["me_t"], ids["other_t"]
    who = {"me": me_t["me"], "vera": ids["vera"], "mallory_p": ids["mallory_p"], "mallory": other_t["me"]}
    ds = datasets.by_id(me_t["ds"])
    ds_other = datasets.by_id(other_t["ds"])
    s = datasets.settings(ds, override)
    s_other = datasets.settings(ds_other, override)
    rule = Rule(db)
    out: dict = {"override": override, "cpu": {}}
    leaks: dict[str, int] = {"search": 0, "link_candidates": 0, "walk_gathered": 0, "pack_text": 0, "trace_text": 0}
    leak_examples: list[dict] = []

    def search_once(d, sett, query, qvec, asker):
        got = search.hybrid(d["id"], query, qvec, asker=asker, settings=sett, model="bench-stub")
        bad = rule.bad(d["id"], [f["item_id"] for f in got["items"]], asker)
        if bad:
            leaks["search"] += len(bad)
            if len(leak_examples) < 20:
                leak_examples.append({"where": "search", "query": query, "asker": asker, "items": bad[:5]})
        return got

    rng = random.Random(size)
    # Warm the caches the way a server's are warm: a few searches and candidates first, not counted.
    db.run(f"SET statement_timeout = '{int(timeout_s)}s'")

    # --- timings, as on 3 October 2026 ----------------------------------------------------------
    sample = [r["id"] for r in db.rows("SELECT id FROM synapse.item WHERE dataset_id = %s AND kind = 'mail' "
                                       "AND source = 'bench' ORDER BY id LIMIT 20000", (me_t["ds"],))]
    picked = [rng.choice(sample) for _ in range(samples + 10)]
    lc, lc_err, structure, pool = [], 0, [], []
    with meter.phase(out["cpu"], "link_candidates", samples):
        for n, item_id in enumerate(picked):
            item = ingest.get_item(me_t["ds"], item_id)
            began = time.time()
            try:
                chosen, info = ingest.link_candidates(ds, item, s, NoTrace(), None)
                bad = rule.bad(ds["id"], [c["item_id"] for c in chosen], item["owner"])
                leaks["link_candidates"] += len(bad)
            except Exception as exc:  # noqa: BLE001 - counted, and the statement's time is the time
                lc_err += 1
                say(f"  link candidates failed: {type(exc).__name__}: {str(exc)[:200]}")
                _reset(db, timeout_s)
                chosen, info = [], {}
            ms = (time.time() - began) * 1000
            if n >= 10:
                lc.append(ms)
                structure.append(int(info.get("structure") or 0))
                pool.append(len(chosen))
    out["link_candidates"] = {**timing(lc, lc_err),
                              "mean_from_structure": round(statistics.mean(structure), 1) if structure else None,
                              "mean_chosen": round(statistics.mean(pool), 1) if pool else None}
    questions = [bench_question(rng, vocab, topic_words, firsts) for _ in range(samples + 10)]
    for label, asker, share in (("search", who["me"], samples), ("search_minority_reader", who["vera"], samples // 2)):
        times, err, found = [], 0, []
        with meter.phase(out["cpu"], label, share):
            for n, (qtext, topic) in enumerate(questions[:share + 10]):
                began = time.time()
                try:
                    got = search_once(ds, s, qtext, ids["centroids"][topic], asker)
                    found.append({"n": len(got["items"]), "older": bool((got.get("recent") or {}).get("older_searched")),
                                  "capped": bool((got.get("terms") or {}).get("common"))})
                except Exception as exc:  # noqa: BLE001
                    err += 1
                    say(f"  search failed: {type(exc).__name__}: {str(exc)[:200]}")
                    _reset(db, timeout_s)
                ms = (time.time() - began) * 1000
                if n >= 10:
                    times.append(ms)
        out[label] = {**timing(times, err),
                      "mean_results": round(statistics.mean(f["n"] for f in found), 1) if found else None,
                      "older_searched": sum(1 for f in found if f["older"]),
                      "words_capped": sum(1 for f in found if f["capped"])}

    # --- cases ----------------------------------------------------------------------------------
    cases = db.rows("SELECT id, family, kind, tenant, asker, question, qvec::text AS qvec, src, gold, forbidden, secret, "
                    "k, meta FROM bench_case ORDER BY id")
    fam: dict[str, dict] = {}
    case_ms: list[float] = []

    def fam_of(name):
        return fam.setdefault(name, {"cases": 0, "gold_cases": 0, "hits": 0, "rr": 0.0, "words_hits": 0,
                                     "meaning_hits": 0, "forbidden_seen": 0, "ms": []})

    with meter.phase(out["cpu"], "cases_search_and_links"):
        for c in cases:
            if c["kind"] == "walk":
                continue
            f = fam_of(c["family"])
            f["cases"] += 1
            gold, forbidden = [str(x) for x in c["gold"] or []], {str(x) for x in c["forbidden"] or []}
            t = ids[c["tenant"]]
            d = ds if c["tenant"] == "me_t" else ds_other
            sett = s if c["tenant"] == "me_t" else s_other
            began = time.time()
            if c["kind"] == "search":
                got = search_once(d, sett, c["question"], _parse(c["qvec"]), who[c["asker"]])
                ranked = [x["item_id"] for x in got["items"]]
                w_ranked = [x["item_id"] for x in sorted((x for x in got["items"] if "words" in x["ranks"]),
                                                         key=lambda x: x["ranks"]["words"])]
                m_ranked = [x["item_id"] for x in sorted((x for x in got["items"] if "meaning" in x["ranks"]),
                                                         key=lambda x: x["ranks"]["meaning"])]
            else:
                item = ingest.get_item(t["ds"], c["src"])
                chosen, _info = ingest.link_candidates(d, item, sett, NoTrace(), None)
                ranked = [x["item_id"] for x in chosen]
                w_ranked = m_ranked = []
                bad = rule.bad(d["id"], ranked, item["owner"])
                leaks["link_candidates"] += len(bad)
            ms = (time.time() - began) * 1000
            f["ms"].append(ms)
            case_ms.append(ms)
            k = int(c["k"]) or 10
            if gold:
                f["gold_cases"] += 1
                rank = next((i + 1 for i, x in enumerate(ranked) if x in gold), None)
                f["hits"] += 1 if rank and rank <= k else 0
                f["rr"] += 1.0 / rank if rank else 0.0
                f["words_hits"] += 1 if any(x in gold for x in w_ranked[:k]) else 0
                f["meaning_hits"] += 1 if any(x in gold for x in m_ranked[:k]) else 0
            seen = forbidden & set(ranked)
            f["forbidden_seen"] += len(seen)
            if seen and len(leak_examples) < 20:
                leak_examples.append({"where": c["family"], "case": c["id"], "asker": c["asker"], "items": list(seen)})

    # --- traversal and packs: what would reach the model ---------------------------------------
    walk_cases = [c for c in cases if c["kind"] == "walk"]
    perm_cases = [c for c in cases if c["family"].startswith("perm_") and c["secret"]][:24]
    qvecs: dict[str, list[float]] = {}
    real_query, real_map = recall.vectors.query, recall.mapping.text_for
    recall.vectors.query = lambda d, text, trace=None, owner=None: {  # noqa: E731
        "vec": qvecs.get(text), "model": "bench-stub", "why": "" if text in qvecs else "no vector"}
    recall.mapping.text_for = lambda d, viewer: ""  # noqa: E731 - the map is not what is measured here
    walk_ms = []
    try:
        with meter.phase(out["cpu"], "walks", len(walk_cases) + len(perm_cases)):
            for c in walk_cases + perm_cases:
                qvecs[c["question"]] = _parse(c["qvec"])
                d = ds if c["tenant"] == "me_t" else ds_other
                began = time.time()
                got = recall.run(d, c["question"], asker=who[c["asker"]], answer=False, by="bench", engaged=False,
                                 override=override)
                walk_ms.append((time.time() - began) * 1000)
                pack = got.get("pack") or {}
                gathered = {str(x["id"]) for x in pack.get("items") or []}
                forbidden, secret = {str(x) for x in c["forbidden"] or []}, list(c["secret"] or [])
                leaks["walk_gathered"] += len(forbidden & gathered)
                text = (pack.get("text") or "").lower()
                leaks["pack_text"] += sum(1 for w in secret if w.lower() in text)
                logged = db.value("SELECT string_agg(data::text, ' ') FROM synapse.trace_step WHERE trace_id = %s",
                                  (got["trace"],)) or ""
                leaks["trace_text"] += sum(1 for w in secret if w.lower() in logged.lower())
                if c["kind"] == "walk":
                    f = fam_of(c["family"])
                    f["cases"] += 1
                    f["gold_cases"] += 1
                    gold = [str(x) for x in c["gold"]]
                    f["hits"] += 1 if all(g in gathered for g in gold) else 0
                    f.setdefault("second_hop", 0)
                    f["second_hop"] += 1 if str((c["meta"] or {}).get("second")) in gathered else 0
                    # The linked item came by its link, not by the search.
                    f.setdefault("by_link", 0)
                    f["by_link"] += 1 if any(str(x["id"]) == gold[1] and x.get("path")
                                             for x in pack.get("items") or []) else 0
                    f["forbidden_seen"] += len(forbidden & gathered)
    finally:
        recall.vectors.query, recall.mapping.text_for = real_query, real_map

    families = {}
    for name, f in sorted(fam.items()):
        n = f["gold_cases"]
        row = {"cases": f["cases"], "gold_cases": n, "forbidden_seen": f["forbidden_seen"],
               "p50_ms": pct(f["ms"], 50), "p95_ms": pct(f["ms"], 95)}
        if n:
            row.update({"hit_rate": round(f["hits"] / n, 3) if n else None,
                        "mrr": round(f["rr"] / n, 3) if n else None})
            if name.startswith("rank_") or name.startswith("time_"):
                row.update({"words_list_hit_rate": round(f["words_hits"] / n, 3) if n else None,
                            "meaning_list_hit_rate": round(f["meaning_hits"] / n, 3) if n else None})
        if "second_hop" in f:
            row["second_hop_rate"] = round(f["second_hop"] / n, 3) if n else None
            row["by_link_rate"] = round(f["by_link"] / n, 3) if n else None
        families[name] = row
    out["families"] = families
    out["case_latency"] = timing(case_ms)
    out["walk_latency"] = timing(walk_ms)
    ranking = [v for k, v in families.items() if k.startswith(("rank_", "time_"))]
    links = [v for k, v in families.items() if k.startswith("link_") and k != "link_forbidden"]
    out["quality"] = {
        "ranking_hit_rate": round(sum(v["hit_rate"] * v["gold_cases"] for v in ranking)
                                  / max(1, sum(v["gold_cases"] for v in ranking)), 3),
        "link_candidate_recall": round(sum(v["hit_rate"] * v["gold_cases"] for v in links)
                                       / max(1, sum(v["gold_cases"] for v in links)), 3),
        "permitted_found": round(sum(v["hit_rate"] * v["gold_cases"] for k, v in families.items() if k.startswith("perm_")
                                     and v["gold_cases"]) / max(1, sum(v["gold_cases"] for k, v in families.items()
                                                                        if k.startswith("perm_"))), 3),
        "walk_recall": families.get("walk_chain", {}).get("hit_rate")}
    leaks["case_forbidden_seen"] = sum(v["forbidden_seen"] for v in families.values())
    leaks["total"] = sum(v for k, v in leaks.items() if k != "total")
    out["leaks"] = leaks
    out["leak_examples"] = leak_examples
    out["memory"] = meter.memory()
    return out


#: Disk the machine keeps free whatever a run needs, and a guess per item before any is measured.
DISK_RESERVE_GB = 80
GUESS_BYTES_PER_ITEM = 30_000


def too_big(db, have: int, size: int, other_share: float, *, max_disk_gb: float, data_dir: str, mwm_mb: int):
    """Why a size is not to be tried here, or None: the disk it would take, measured per item so far,
    against what is free less a reserve and against the run's own cap; and memory for the index build."""
    import shutil

    used = int(db.value("SELECT pg_database_size(current_database())"))
    per_item = used / max(1, have * (1 + other_share)) if have >= 5000 else GUESS_BYTES_PER_ITEM
    # Indexes are built after the load, beside the tables, and sorting them needs room too: half again.
    need = per_item * (size - have) * (1 + other_share) * 1.5
    free = shutil.disk_usage(data_dir).free if data_dir else 1 << 50
    total_after = (used + need) / 1e9
    room = free / 1e9 - DISK_RESERVE_GB
    estimate = {"estimated_db_gb": round((used + per_item * size * (1 + other_share)) / 1e9, 1),
                "bytes_per_item": int(per_item), "disk_free_gb": round(free / 1e9, 1)}
    # A size already loaded needs no more disk, so the reserve cannot stop it being measured (31 October 2026).
    if need > 0 and need / 1e9 > room:
        return {**estimate, "why": f"it would need about {need / 1e9:.0f} GB more on disk while loading and "
                                    f"building indexes, and {room:.0f} GB is free above the {DISK_RESERVE_GB} GB "
                                    "the machine keeps"}
    if total_after > max_disk_gb:
        return {**estimate, "why": f"the database would grow to about {total_after:.0f} GB, over this run's cap "
                                    f"of {max_disk_gb:g} GB (--max-disk-gb)"}
    avail_mb = mem_available_kb() / 1024
    if avail_mb < mwm_mb + 6000:
        return {**estimate, "why": f"{avail_mb:.0f} MB of memory is free, and building the indexes takes "
                                    f"{mwm_mb} MB with 6,000 MB kept for everything else on the machine"}
    return None


def pg_search_column(db) -> bool:
    """The extension and the column of word forms, as migration 0078 makes them where pg_search is
    loaded; made before a load, so each passage's forms are written with it rather than the table
    rewritten after (over 28 minutes at 1,000,000 items)."""
    if "pg_search" not in str(db.value("SHOW shared_preload_libraries") or ""):
        return False
    db.run("CREATE EXTENSION IF NOT EXISTS pg_search CASCADE")
    db.run("CREATE OR REPLACE FUNCTION synapse.lexeme_text(v tsvector) RETURNS text LANGUAGE sql IMMUTABLE "
           "PARALLEL SAFE AS $$ SELECT coalesce(string_agg(repeat(u.lexeme || ' ', "
           "coalesce(array_length(u.positions, 1), 1)), ''), '') FROM unnest(v) u $$")
    db.run("ALTER TABLE synapse.passage ADD COLUMN IF NOT EXISTS lexemes text "
           "GENERATED ALWAYS AS (synapse.lexeme_text(words)) STORED")
    return True


def pg_search_index(db, say, mwm_mb: int) -> dict | None:
    """ParadeDB's BM25 index over the passages, when this database loads pg_search (--pg-search):
    over the same word forms the GIN index holds, so the two rank the same words. Built once, timed."""
    if "pg_search" not in str(db.value("SHOW shared_preload_libraries") or ""):
        return None
    if db.value("SELECT to_regclass('synapse.passage_bm25') IS NOT NULL") and not db.value(
            "SELECT pg_get_indexdef('synapse.passage_bm25'::regclass) LIKE '%%pdb.literal%%'"):
        db.run("DROP INDEX synapse.passage_bm25")
    if db.value("SELECT to_regclass('synapse.passage_bm25') IS NOT NULL"):
        return {"built_before": True, "mb": round(int(db.value(
            "SELECT pg_relation_size('synapse.passage_bm25')")) / 1048576, 1)}
    t = time.time()
    pg_search_column(db)
    column_s = time.time() - t
    db.run(f"SET maintenance_work_mem = '{int(mwm_mb)}MB'")
    db.run("SET max_parallel_maintenance_workers = 6")
    # Readers and kinds as whole values (the default tokenizer splits an id at its hyphens), so the
    # reader filter is answered in the index: checked against the table instead, it took ten times longer.
    db.run("CREATE INDEX passage_bm25 ON synapse.passage USING bm25 (id, (lexemes::pdb.whitespace), dataset_id, "
           "(can_read::pdb.literal), (kind::pdb.literal), said_at, item_id)")
    db.run("VACUUM ANALYZE synapse.passage")
    got = {"column_s": round(column_s, 1), "index_s": round(time.time() - t - column_s, 1),
           "mb": round(int(db.value("SELECT pg_relation_size('synapse.passage_bm25')")) / 1048576, 1)}
    say(f"  pg_search index: {json.dumps(got)}")
    return got


def hot_indexes(db, say, days: int, mwm_mb: int) -> dict | None:
    """A hot window as the planner would see a hot partition: the words and vector indexes again,
    over the passages of the last `days` days only (card 1125, change 4). Their edge is fixed when
    they are built, so they hold for a run, not for ever; built again when asked for another edge."""
    if not days:
        for name in ("passage_vec_hot", "passage_words_hot"):
            db.run(f"DROP INDEX IF EXISTS synapse.{name}")
        return None
    edge = db.value("SELECT date_trunc('day', now() - make_interval(days => %s))", (int(days) + 1,))
    have = db.value("SELECT pg_get_indexdef('synapse.passage_vec_hot'::regclass)") \
        if db.value("SELECT to_regclass('synapse.passage_vec_hot') IS NOT NULL") else ""
    t = time.time()
    if str(edge.date()) not in (have or ""):
        for name in ("passage_vec_hot", "passage_words_hot"):
            db.run(f"DROP INDEX IF EXISTS synapse.{name}")
        db.run(f"SET maintenance_work_mem = '{int(mwm_mb)}MB'")
        lit = edge.isoformat()
        db.run(f"CREATE INDEX passage_vec_hot ON synapse.passage USING hnsw (vec halfvec_cosine_ops) "
               f"WHERE said_at >= '{lit}'")
        db.run(f"CREATE INDEX passage_words_hot ON synapse.passage USING gin (words) WHERE said_at >= '{lit}'")
        db.run("ANALYZE synapse.passage")
    got = {"days": int(days), "edge": str(edge), "build_s": round(time.time() - t, 1),
           "passages": int(db.value("SELECT count(*) FROM synapse.passage WHERE said_at >= %s", (edge,))),
           "mb": round(int(db.value("SELECT pg_relation_size('synapse.passage_vec_hot') + "
                                    "pg_relation_size('synapse.passage_words_hot')")) / 1048576, 1)}
    say(f"  hot window indexes: {json.dumps(got)}")
    return got


def hnsw_rebuild(db, say, params: str, mwm_mb: int) -> dict | None:
    """The vector index built again with other HNSW settings ('m=32,ef_construction=128'), timed, for
    an experiment: what a better-connected graph does to recall and time. Nothing in Synapse sets these."""
    if not params:
        return None
    want = dict(p.split("=") for p in params.split(","))
    now = (db.value("SELECT pg_get_indexdef('synapse.passage_vec'::regclass)")
           if db.value("SELECT to_regclass('synapse.passage_vec') IS NOT NULL") else "") or ""
    if all(f"{k}='{v}'" in now or f"{k}={v}" in now for k, v in want.items()):
        return {"params": want, "built_before": True}
    db.run("DROP INDEX IF EXISTS synapse.passage_vec")
    db.run(f"SET maintenance_work_mem = '{int(mwm_mb)}MB'")
    db.run("SET max_parallel_maintenance_workers = 6")
    t = time.time()
    db.run("CREATE INDEX passage_vec ON synapse.passage USING hnsw (vec halfvec_cosine_ops) WITH ("
           + ", ".join(f"{k} = {int(v)}" for k, v in want.items()) + ")")
    got = {"params": want, "build_s": round(time.time() - t, 1),
           "mb": round(int(db.value("SELECT pg_relation_size('synapse.passage_vec')")) / 1048576, 1)}
    say(f"  vector index rebuilt: {json.dumps(got)}")
    return got


def inside(sizes: list[int], samples: int, timeout_s: int, say, *, variants: list[dict], postmaster: int | None,
           other_share: float = 0.1, mwm_mb: int = 4096, max_disk_gb: float = 150, data_dir: str = "",
           writes: bool = False, hot_days: int = 0, hnsw: str = "") -> dict:
    from .. import db, datasets, people

    vocab, topic_words, firsts, lasts = words()
    ids = again(db) or setup(db, vocab, topic_words, firsts, lasts)
    meter = Meter(postmaster)
    out = {"samples": samples, "sizes": [], "machine": machine(db), "variants": [v["label"] for v in variants]}
    me_t, other_t = ids["me_t"], ids["other_t"]
    me_t.update(name="Bench", tag="")
    other_t.update(name="Mallory bench", tag="m:")
    count = lambda t: int(db.value("SELECT count(*) FROM synapse.item WHERE dataset_id = %s AND source = 'bench'",  # noqa: E731
                                   (t["ds"],)))
    have, have_o = count(me_t), count(other_t)
    if have:
        say(f"A database kept with --keep, already holding {have:,} items: only what is missing is loaded.")
    nv = int(db.value("SELECT count(*) FROM bench_vocab"))
    for size in sizes:
        if size < have:
            say(f"  {size:,} is fewer than the {have:,} already there: skipped")
            continue
        refused = too_big(db, have, size, other_share, max_disk_gb=max_disk_gb, data_dir=data_dir, mwm_mb=mwm_mb)
        if refused:
            # Every size it cannot take is said, each with its own estimate; a larger one only needs more.
            say(f"  {size:,} items not tried: {refused['why']}")
            out["sizes"].append({"items": size, "measured": False, **refused})
            continue
        t = time.time()
        db.run("SET statement_timeout = 0")
        loaded = {}
        if size > have or not db.value("SELECT count(*) FROM bench_case"):
            with meter.phase(loaded, "load"):
                bulk_off(db)
                load(db, me_t, have, size, 2000 + size // 20, say, vera=ids["vera"], nv=nv)
                o_size = int(size * other_share)
                if o_size > have_o:
                    load(db, other_t, have_o, o_size, 500 + o_size // 20, say, vera=None, nv=nv)
                    have_o = o_size
                plant(db, ids, vocab, topic_words, say)
                say("  indexes")
                bulk_on(db, say, mwm_mb)
                # People's values (D81's walk prior), as the first question would work them out.
                for d in (me_t, other_t):
                    while people.ensure_values(datasets.by_id(d["ds"])):
                        pass
            have = size
        load_s = round(time.time() - t, 1)
        bm25_index = pg_search_index(db, say, mwm_mb)
        hot = hot_indexes(db, say, hot_days, mwm_mb)
        rebuilt = hnsw_rebuild(db, say, hnsw, mwm_mb)
        passages = int(db.value("SELECT count(*) FROM synapse.passage"))
        items = int(db.value("SELECT count(*) FROM synapse.item"))
        say(f"{size:,} of the owner's items ({items:,} in all, {passages:,} passages), loaded in {load_s} s; measuring.")
        row = {"items": size, "items_all_datasets": items, "passages_all_datasets": passages,
               "people": 2000 + size // 20, "other_dataset_items": have_o, "load_s": load_s, "load": loaded.get("load"),
               "disk": disk(db), "pg_search_index": bm25_index, "hot_window_indexes": hot, "hnsw_rebuilt": rebuilt,
               "variants": {}}
        # Warm the caches first, unmeasured, so the first configuration does not pay for a cold start
        # the later ones do not (found 4 October 2026: the first of three equal settings measured 3x slower).
        with meter.phase(row, "warm_up"):
            warm(db, ids, vocab, topic_words, firsts, say, n=max(50, samples // 2))
        for v in variants:
            say(f"  configuration {v['label']}: {json.dumps(v['override'])}")
            got = measure(db, ids, v["override"], samples=samples, timeout_s=timeout_s, vocab=vocab,
                          topic_words=topic_words, firsts=firsts, meter=meter, say=say, size=size)
            row["variants"][v["label"]] = got
            say(summary_line(size, v["label"], got))
        if writes:
            with meter.phase(row, "writes_cpu"):
                row["writes"] = measure_writes(db, ids, say)
        out["sizes"].append(row)
    return out


# ---------------------------------------------------------------------------------------------
# the write path: storing, the queue, the links after it (card 1125, change 5)
# ---------------------------------------------------------------------------------------------

class Stubs:
    """The model's part with no model: the X-ray call answers at once with one judgement link to the
    first candidate, and vectors are made by code near the item's subject. Counts each X-ray asked."""

    def __init__(self, ids: dict):
        self.ids = ids
        self.xrays: dict[str, int] = {}
        self._saved = []

    def __enter__(self):
        from .. import ai, ingest, vectors

        def generate(*, name="", items=None, **kw):
            if name == "xray":
                key = str((items or [""])[0])
                self.xrays[key] = self.xrays.get(key, 0) + 1
                return {"gist": "bench gist", "claims": [], "links": [{"target": 1, "type": "about",
                                                                       "strength": "medium", "why": "bench"}],
                        "topics": [], "tier": "normal", "tier_why": "bench", "title": "", "sensitivity": "normal",
                        "area": "", "_model": "bench-stub", "_cost": 0.0, "_ms": 0}
            return {"_model": "bench-stub", "_cost": 0.0}

        rng = random.Random(5)
        cents = self.ids["centroids"]

        def store(ds, rows, **kw):
            from .. import db
            for r in rows:
                v = [x + rng.gauss(0, 0.78) for x in cents[abs(hash(r.get("text", ""))) % TOPICS]]
                db.run("UPDATE synapse.passage SET vec = %s::halfvec, embed_model = 'bench-stub' WHERE id = %s",
                       (db.vec(v), r["id"]))
            return {"passages": len(rows)}

        for mod, name, new in ((ai, "generate", generate), (vectors, "store", store),
                               (ingest.vectors, "store", store)):
            self._saved.append((mod, name, getattr(mod, name)))
            setattr(mod, name, new)
        return self

    def __exit__(self, *exc):
        for mod, name, old in reversed(self._saved):
            setattr(mod, name, old)


def _drain(ds_id: str, until, *, workers: int, limit_s: float, say) -> dict:
    """Run the queue's live lane for one dataset with `workers` threads of the worker's own code
    (`worker._claim`, `worker._finish`) until `until()` or `limit_s`."""
    from django.db import connection
    from .. import worker

    stop = threading.Event()
    done = {"jobs": 0}
    lock = threading.Lock()

    def loop():
        try:
            while not stop.is_set():
                jobs = worker._claim("live", 1, dataset_id=ds_id)
                if not jobs:
                    time.sleep(0.05)
                    continue
                worker._finish(jobs[0])
                with lock:
                    done["jobs"] += 1
        finally:
            connection.close()

    threads = [threading.Thread(target=loop, daemon=True) for _ in range(workers)]
    began = time.time()
    for t in threads:
        t.start()
    while time.time() - began < limit_s and not until():
        time.sleep(0.1)
    stop.set()
    for t in threads:
        t.join(timeout=60)
    return {"jobs": done["jobs"], "s": round(time.time() - began, 2), "finished": bool(until())}


def measure_writes(db, ids: dict, say, *, n: int = 200, workers: int = 4) -> dict:
    """Storing and linking, as Synapse does it, with the model's calls answered by `Stubs`."""
    import subprocess
    import socket
    from .. import datasets, ingest, search, worker

    ds = datasets.by_id(ids["me_t"]["ds"])
    s = datasets.settings(ds)
    out: dict = {"n": n, "workers": workers}
    rng = random.Random(55)
    run = f"{int(time.time())}"  # a kept database is written to again by every run: new keys each time
    with Stubs(ids) as stubs:
        db.run("DELETE FROM synapse.job WHERE dataset_id = %s AND done_at IS NULL", (ds["id"],))
        # 1. Store: the code's part, then is it found by its words at once?
        stored, write_ms, found = [], [], 0
        for i in range(n):
            word = "zqw" + "".join(rng.choice("bdfgklmnprstvz") + rng.choice("aeiou") for _ in range(3))
            body = f"Bench write {i}: {word} " + " ".join(rng.choice(["invoice", "delivery", "plan", "team", "budget"])
                                                         for _ in range(60))
            t0 = time.time()
            got = ingest.store(ds, {"kind": "mail", "text": body, "title": f"Write {i} {word}",
                                    "source": "bench-write", "source_key": f"w-{run}-{i}-{word}",
                                    "from": "Someone <someone@example.org>"}, by="bench")
            write_ms.append((time.time() - t0) * 1000)
            hit = search.hybrid(ds["id"], word, None, asker=ids["me_t"]["me"], settings=s, meaning=False)
            found += 1 if any(f["item_id"] == got["item"] for f in hit["items"]) else 0
            stored.append((got["item"], t0))
        out["store_code_part"] = timing(write_ms)
        out["searchable_at_once"] = f"{found} of {n}"
        ids_ = [x[0] for x in stored]
        statuses = {r["status"]: r["n"] for r in db.rows(
            "SELECT status, count(*) AS n FROM synapse.item WHERE id = ANY(%s::uuid[]) GROUP BY 1", (ids_,))}
        out["status_before_the_queue"] = statuses
        # 2. The queue: links after the store, how long until each item is ready, how many an hour.
        ready = lambda: int(db.value("SELECT count(*) FROM synapse.item WHERE id = ANY(%s::uuid[]) AND "  # noqa: E731
                                     "status IN ('ready', 'failed')", (ids_,))) >= n
        q0 = time.time()
        drained = _drain(ds["id"], ready, workers=workers, limit_s=600, say=say)
        rows = db.rows("SELECT id, status, updated_at FROM synapse.item WHERE id = ANY(%s::uuid[])", (ids_,))
        at = {r["id"]: r for r in rows}
        lags = [(at[i]["updated_at"].timestamp() - t0) * 1000 for i, t0 in stored
                if at.get(i) and at[i]["status"] == "ready" and at[i]["updated_at"]]
        out["queue"] = {**drained, "items_per_s": round(n / max(0.001, time.time() - q0), 1),
                        "ready": sum(1 for r in rows if r["status"] == "ready"),
                        "failed": sum(1 for r in rows if r["status"] == "failed"),
                        "link_completion_lag": timing(lags),
                        "judgement_links": int(db.value("SELECT count(*) FROM synapse.link WHERE src = ANY(%s::uuid[]) "
                                                        "AND origin = 'model'", (ids_,))),
                        "xray_calls": sum(stubs.xrays.get(i, 0) for i in ids_)}
        # 3. The same item asked for twice before the first is done (two reruns, a retried import).
        twice = ids_[:20]
        before_calls = sum(stubs.xrays.get(i, 0) for i in twice)
        before_links = int(db.value("SELECT count(*) FROM synapse.link WHERE src = ANY(%s::uuid[])", (twice,)))
        jobs = [ingest.enqueue(ds["id"], "ingest", item_id=i, priority=3) for i in twice for _ in range(2)]
        _drain(ds["id"], lambda: not db.value("SELECT count(*) FROM synapse.job WHERE id = ANY(%s) AND done_at IS NULL",
                                               (jobs,)), workers=workers, limit_s=300, say=say)
        out["asked_twice"] = {"items": len(twice), "jobs_queued": len(set(jobs)),
                              "xray_calls": sum(stubs.xrays.get(i, 0) for i in twice) - before_calls,
                              "links_after_minus_before": int(db.value(
                                  "SELECT count(*) FROM synapse.link WHERE src = ANY(%s::uuid[])", (twice,))) - before_links}
        # 4. A worker that dies holding jobs: its process is gone, its locks are not.
        dead = subprocess.Popen(["true"])
        dead.wait()
        dead_id = f"{socket.gethostname()}:{dead.pid}"
        lost = []
        for i in range(20):
            got = ingest.store(ds, {"kind": "note", "text": f"Recovery {i} " + "words " * 40, "source": "bench-write",
                                    "source_key": f"r-{run}-{i}"}, by="bench")
            lost.append(got["item"])
        worker._claim("live", 50, dataset_id=ds["id"], me=dead_id)
        r0 = time.time()
        restarted = getattr(worker, "release_dead", None)
        released = restarted() if restarted else None
        back = _drain(ds["id"], lambda: int(db.value("SELECT count(*) FROM synapse.item WHERE id = ANY(%s::uuid[]) "
                                                     "AND status = 'ready'", (lost,))) >= len(lost),
                      workers=workers, limit_s=60, say=say)
        out["dead_worker"] = {"items": len(lost), "released_at_start": released,
                              "ready_within_60_s": int(db.value("SELECT count(*) FROM synapse.item WHERE id = ANY(%s::uuid[]) "
                                                                "AND status = 'ready'", (lost,))),
                              "s": round(time.time() - r0, 1), "jobs_run": back["jobs"],
                              "still_locked_by_the_dead": int(db.value(
                                  "SELECT count(*) FROM synapse.job WHERE locked_by = %s AND done_at IS NULL", (dead_id,)))}
        db.run("DELETE FROM synapse.job WHERE dataset_id = %s AND done_at IS NULL", (ds["id"],))
    say(f"  writes: {json.dumps(out)[:600]}")
    return out


def warm(db, ids: dict, vocab, topic_words, firsts, say, *, n: int) -> None:
    """Searches and link candidates as the measured runs make them, as tuned, results thrown away."""
    from .. import datasets, ingest, search

    ds = datasets.by_id(ids["me_t"]["ds"])
    s = datasets.settings(ds)
    rng = random.Random(-1)
    sample = [r["id"] for r in db.rows("SELECT id FROM synapse.item WHERE dataset_id = %s AND kind = 'mail' "
                                       "AND source = 'bench' ORDER BY id DESC LIMIT 5000", (ids["me_t"]["ds"],))]
    began = time.time()
    for _ in range(n):
        q, topic = bench_question(rng, vocab, topic_words, firsts)
        search.hybrid(ds["id"], q, ids["centroids"][topic], asker=ids["me_t"]["me"], settings=s, model="bench-stub")
        ingest.link_candidates(ds, ingest.get_item(ds["id"], rng.choice(sample)), s, NoTrace(), None)
    say(f"  warmed up: {n} searches and link candidates in {time.time() - began:.0f} s, not counted")


def summary_line(size: int, label: str, got: dict) -> str:
    qv = got["quality"]
    return (f"  {size:>9,} {label:<14} link p50/p95 {got['link_candidates']['p50_ms']}/{got['link_candidates']['p95_ms']} ms"
            f" | search {got['search']['p50_ms']}/{got['search']['p95_ms']} ms"
            f" | minority {got['search_minority_reader']['p50_ms']}/{got['search_minority_reader']['p95_ms']} ms"
            f" | ranking {qv['ranking_hit_rate']} links {qv['link_candidate_recall']} walk {qv['walk_recall']}"
            f" | leaks {got['leaks']['total']}")
