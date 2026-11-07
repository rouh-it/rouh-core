"""Synapse's people: real items of kind 'person', matched by their identifiers.

Petar, 3 October 2026 (asked by voice, task 85): everything Synapse knows is a
`synapse.item` with a kind, and a person is one of them. What this changes:

- The kind `contact` is called `person` everywhere, and the rows are renamed.
- `synapse.identity` maps every address, phone number, name and handle to one
  person item, so people are matched by what identifies them, never by name
  alone. An email, a phone or a handle belongs to one person per scope.
- People belong to their owner, not to one dataset: each owner has one people
  set (`synapse.dataset.role = 'people'`) that every one of their real datasets
  resolves against (`people_id`), and links may cross into it, so a link's far
  end is any item (`link.dst` points at `item.id`, still deleted with it).
  The fictional example datasets keep their own people, in themselves.
- Readers, an item's owner, a question's asker and a map's viewer were a
  lower-case first name; they are a person item's id now, or `everyone`.
  `synapse.dataset.me_id` is the dataset's own person.

`synapse.scope(ds)` is the datasets an item of `ds` may be read from (itself,
and its owner's people set), and `synapse.reaches(ds, item_ds, item)` says
whether one item in that scope is in play for `ds`: its own items, and the
people its own items link to.

The data step below turns every existing contact into a person (origin
'synapse', with its address, name and old first name as identifiers) and every
reader name into the person it meant, and is written out here rather than
imported, so it reads the same whatever the code does later.
"""
import json
import re
import unicodedata

from django.db import migrations

SCHEMA = r"""
ALTER TABLE synapse.dataset ADD COLUMN IF NOT EXISTS role text NOT NULL DEFAULT 'data';
ALTER TABLE synapse.dataset ADD COLUMN IF NOT EXISTS people_id uuid REFERENCES synapse.dataset(id);
ALTER TABLE synapse.dataset ADD COLUMN IF NOT EXISTS me_id uuid;
CREATE UNIQUE INDEX IF NOT EXISTS dataset_people_one ON synapse.dataset (org_id, user_id) WHERE role = 'people';

CREATE TABLE IF NOT EXISTS synapse.identity (
  id        bigserial PRIMARY KEY,
  scope_id  uuid NOT NULL REFERENCES synapse.dataset(id) ON DELETE CASCADE,
  item_id   uuid NOT NULL,
  type      text NOT NULL CHECK (type IN ('email', 'phone', 'name', 'handle')),
  value     text NOT NULL,
  shown     text NOT NULL DEFAULT '',
  source    text NOT NULL DEFAULT '',
  made_at   timestamptz NOT NULL DEFAULT now(),
  UNIQUE (scope_id, item_id, type, value),
  FOREIGN KEY (scope_id, item_id) REFERENCES synapse.item(dataset_id, id) ON DELETE CASCADE
);
CREATE UNIQUE INDEX IF NOT EXISTS identity_one ON synapse.identity (scope_id, type, value)
  WHERE type IN ('email', 'phone', 'handle');
CREATE INDEX IF NOT EXISTS identity_find ON synapse.identity (scope_id, type, value);
CREATE INDEX IF NOT EXISTS identity_of ON synapse.identity (scope_id, item_id);

ALTER TABLE synapse.link DROP CONSTRAINT IF EXISTS link_dataset_id_dst_fkey;
ALTER TABLE synapse.link DROP CONSTRAINT IF EXISTS link_dst_item;
ALTER TABLE synapse.link ADD CONSTRAINT link_dst_item FOREIGN KEY (dst) REFERENCES synapse.item(id) ON DELETE CASCADE;
CREATE INDEX IF NOT EXISTS link_dst_any ON synapse.link (dst);

CREATE OR REPLACE FUNCTION synapse.scope(ds uuid) RETURNS uuid[] LANGUAGE sql STABLE AS $$
  SELECT ARRAY[ds] || coalesce((SELECT ARRAY[d.people_id] FROM synapse.dataset d
                                WHERE d.id = ds AND d.people_id IS NOT NULL), '{}'::uuid[])
$$;
CREATE OR REPLACE FUNCTION synapse.reaches(ds uuid, item_ds uuid, item uuid) RETURNS boolean LANGUAGE sql STABLE AS $$
  SELECT item_ds = ds OR EXISTS (SELECT 1 FROM synapse.link l WHERE l.dataset_id = ds AND l.dst = item)
$$;

UPDATE synapse.item SET kind = 'person' WHERE kind = 'contact';
"""

UNDO = r"""
UPDATE synapse.item SET kind = 'contact' WHERE kind = 'person';
DROP FUNCTION IF EXISTS synapse.reaches(uuid, uuid, uuid);
DROP FUNCTION IF EXISTS synapse.scope(uuid);
DROP INDEX IF EXISTS synapse.link_dst_any;
ALTER TABLE synapse.link DROP CONSTRAINT IF EXISTS link_dst_item;
DROP TABLE IF EXISTS synapse.identity;
DROP INDEX IF EXISTS synapse.dataset_people_one;
ALTER TABLE synapse.dataset DROP COLUMN IF EXISTS me_id;
ALTER TABLE synapse.dataset DROP COLUMN IF EXISTS people_id;
ALTER TABLE synapse.dataset DROP COLUMN IF EXISTS role;
"""

UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def principal(name: str) -> str:
    """The old reader key: a name's first word, lower case."""
    word = (name or "").strip().split(" ")[0].split("@")[0].lower()
    return "".join(ch for ch in word if ch.isalnum() or ch in "-_") or "someone"


def norm_name(name: str) -> str:
    """As `synapse.people.norm_name`: accents off, lower case, punctuation as spaces."""
    text = unicodedata.normalize("NFKD", str(name or ""))
    text = "".join(c for c in text if not unicodedata.combining(c)).lower()
    return " ".join(re.sub(r"[^\w\s]", " ", text).split())


class Data:
    def __init__(self, cur):
        self.cur = cur

    def rows(self, sql, params=()):
        self.cur.execute(sql, params)
        if self.cur.description is None:
            return []
        names = [c.name for c in self.cur.description]
        return [dict(zip(names, r)) for r in self.cur.fetchall()]

    def row(self, sql, params=()):
        got = self.rows(sql, params)
        return got[0] if got else None

    def identity(self, home, item, type_, value, shown, source):
        if not value:
            return
        self.cur.execute(
            "INSERT INTO synapse.identity (scope_id, item_id, type, value, shown, source) VALUES (%s, %s, %s, %s, %s, %s) "
            "ON CONFLICT DO NOTHING", (home, item, type_, value, shown or value, source))

    def taken(self, home, type_, value):
        got = self.row("SELECT item_id FROM synapse.identity WHERE scope_id = %s AND type = %s AND value = %s",
                       (home, type_, value))
        return str(got["item_id"]) if got else None

    def new_person(self, home, name, handle, owner, why):
        meta = {"origin": "synapse", "name": name, "handle": handle, "made_by": "migration",
                "made_why": why, "emails": [], "phones": []}
        item = self.row(
            "INSERT INTO synapse.item (dataset_id, kind, source, source_key, title, raw, body, tier, tier_why, sensitivity, "
            "owner, meta, status) VALUES (%s, 'person', 'synapse', %s, %s, %s, %s, 1, %s, 'normal', %s, %s::jsonb, 'ready') "
            "RETURNING id", (home, "handle:" + handle, name, name, name, "a person, made by code", owner or "",
                            json.dumps(meta)))
        pid = str(item["id"])
        self.cur.execute("INSERT INTO synapse.reader (dataset_id, item_id, principal) VALUES (%s, %s, 'everyone')",
                         (home, pid))
        self.cur.execute("INSERT INTO synapse.passage (dataset_id, item_id, seq, text, words) VALUES (%s, %s, 0, %s, "
                         "to_tsvector('simple', %s) || to_tsvector('english', %s))", (home, pid, name, name, name))
        self.identity(home, pid, "name", norm_name(name), name, why)
        self.identity(home, pid, "handle", handle, handle, why)
        return pid


def people_set(data, ds):
    got = data.row("SELECT id FROM synapse.dataset WHERE org_id = %s AND user_id = %s AND role = 'people'",
                   (ds["org_id"], ds["user_id"]))
    if got:
        return str(got["id"])
    got = data.row("INSERT INTO synapse.dataset (org_id, user_id, name, about, owner_name, role) VALUES "
                   "(%s, %s, 'People', %s, %s, 'people') RETURNING id",
                   (ds["org_id"], ds["user_id"],
                    "Everyone this owner's real datasets know: imported from the contacts, or met in an item. "
                    "Every real dataset resolves people here and links to them.", ds["owner_name"]))
    return str(got["id"])


def forward(apps, schema_editor):
    with schema_editor.connection.cursor() as cur:
        data = Data(cur)
        for ds in data.rows("SELECT * FROM synapse.dataset WHERE role = 'data' ORDER BY created_at"):
            ds_id = str(ds["id"])
            real = not ds["example"]
            home = people_set(data, ds) if real else ds_id
            if real:
                cur.execute("UPDATE synapse.dataset SET people_id = %s WHERE id = %s", (home, ds_id))
            # 1. Every contact becomes a person in its home, with its address, name and old key as identities.
            moved = {}
            for c in data.rows("SELECT * FROM synapse.item WHERE dataset_id = %s AND kind = 'person' "
                               "ORDER BY stored_at", (ds_id,)):
                cid = str(c["id"])
                meta = c["meta"] if isinstance(c["meta"], dict) else json.loads(c["meta"] or "{}")
                email = str(meta.get("email") or (c["source_key"] if "@" in (c["source_key"] or "") else "")).lower()
                handle = str(meta.get("person") or "")
                name = c["title"] or email
                pid = cid
                if real:
                    pid = data.taken(home, "email", email) if email else None
                    if not pid:
                        meta2 = {"origin": "synapse", "name": name, "emails": [email] if email else [], "phones": [],
                                 "made_by": "code"}
                        got = data.row(
                            "INSERT INTO synapse.item (dataset_id, kind, source, source_key, title, raw, body, tier, tier_why, "
                            "sensitivity, owner, meta, status) VALUES (%s, 'person', %s, %s, %s, %s, %s, %s, %s, 'normal', "
                            "%s, %s::jsonb, 'ready') ON CONFLICT (dataset_id, source, source_key) DO UPDATE SET "
                            "title = excluded.title RETURNING id",
                            (home, c["source"], c["source_key"], c["title"], c["raw"], c["body"], c["tier"], c["tier_why"],
                             c["owner"], json.dumps(meta2)))
                        pid = str(got["id"])
                        cur.execute("INSERT INTO synapse.reader (dataset_id, item_id, principal) VALUES (%s, %s, "
                                    "'everyone') ON CONFLICT DO NOTHING", (home, pid))
                        cur.execute("INSERT INTO synapse.passage (dataset_id, item_id, seq, text, words) SELECT %s, %s, seq, "
                                    "text, words FROM synapse.passage WHERE dataset_id = %s AND item_id = %s",
                                    (home, pid, ds_id, cid))
                    # Links that pointed at the old contact point at the person; its own links go with it.
                    cur.execute("UPDATE synapse.link SET dst = %s WHERE dataset_id = %s AND dst = %s "
                                "AND NOT EXISTS (SELECT 1 FROM synapse.link x WHERE x.dataset_id = synapse.link.dataset_id "
                                "AND x.src = synapse.link.src AND x.dst = %s AND x.type = synapse.link.type)",
                                (pid, ds_id, cid, pid))
                    cur.execute("DELETE FROM synapse.item WHERE dataset_id = %s AND id = %s", (ds_id, cid))
                    moved[cid] = pid
                else:
                    meta.update({"origin": "synapse", "name": name, "emails": [email] if email else [], "phones": []})
                    meta.pop("email", None)
                    cur.execute("UPDATE synapse.item SET meta = %s::jsonb WHERE id = %s", (json.dumps(meta), cid))
                data.identity(home, pid, "email", email, email, "its address, before people were items")
                data.identity(home, pid, "name", norm_name(name), name, "its name, before people were items")
                if handle and not data.taken(home, "handle", handle):
                    data.identity(home, pid, "handle", handle, handle, "its reader name before 3 October 2026")
                    cur.execute("UPDATE synapse.item SET meta = jsonb_set(meta, '{handle}', to_jsonb(%s::text)) "
                                "WHERE id = %s", (handle, pid))
            # 2. The dataset's own person.
            me_key = principal(ds["owner_name"] or "Owner")
            me = data.taken(home, "handle", me_key) or data.new_person(
                home, ds["owner_name"] or "Owner", me_key, "", "the dataset's own person")
            cur.execute("UPDATE synapse.dataset SET me_id = %s WHERE id = %s", (me, ds_id))
            if home != ds_id:
                cur.execute("UPDATE synapse.dataset SET me_id = %s WHERE id = %s AND me_id IS NULL", (me, home))
            # 3. Every reader name, owner, asker and viewer becomes the person it meant.
            names = set()
            for sql in ("SELECT DISTINCT principal AS p FROM synapse.reader WHERE dataset_id = %s",
                        "SELECT DISTINCT owner AS p FROM synapse.item WHERE dataset_id = %s",
                        "SELECT DISTINCT asker AS p FROM synapse.query WHERE dataset_id = %s",
                        "SELECT DISTINCT asker AS p FROM synapse.eval_question WHERE dataset_id = %s",
                        "SELECT DISTINCT viewer AS p FROM synapse.map WHERE dataset_id = %s"):
                names |= {r["p"] for r in data.rows(sql, (ds_id,)) if r["p"]}
            names -= {"everyone"}
            for name in sorted(n for n in names if not UUID.match(n)):
                pid = data.taken(home, "handle", name) or data.new_person(
                    home, name[:1].upper() + name[1:], name, me, "a reader name before 3 October 2026")
                cur.execute("INSERT INTO synapse.reader (dataset_id, item_id, principal) SELECT dataset_id, item_id, %s "
                            "FROM synapse.reader WHERE dataset_id = %s AND principal = %s ON CONFLICT DO NOTHING",
                            (pid, ds_id, name))
                cur.execute("DELETE FROM synapse.reader WHERE dataset_id = %s AND principal = %s", (ds_id, name))
                cur.execute("UPDATE synapse.item SET owner = %s WHERE dataset_id = %s AND owner = %s", (pid, ds_id, name))
                cur.execute("UPDATE synapse.query SET asker = %s WHERE dataset_id = %s AND asker = %s", (pid, ds_id, name))
                cur.execute("UPDATE synapse.eval_question SET asker = %s WHERE dataset_id = %s AND asker = %s",
                            (pid, ds_id, name))
                cur.execute("UPDATE synapse.map SET viewer = %s WHERE dataset_id = %s AND viewer = %s", (pid, ds_id, name))
                cur.execute("UPDATE synapse.map_line SET key = %s || substr(key, %s) WHERE dataset_id = %s "
                            "AND key LIKE %s", (pid + ":", len(name) + 2, ds_id, name + ":%"))
            # Items stored with no owner belong to the dataset's own person.
            cur.execute("UPDATE synapse.item SET owner = %s WHERE dataset_id = %s AND owner = ''", (me, ds_id))
        # People sets made above have their own person too, owned by it.
        cur.execute("UPDATE synapse.item i SET owner = d.me_id::text FROM synapse.dataset d WHERE d.role = 'people' "
                    "AND i.dataset_id = d.id AND d.me_id IS NOT NULL AND i.owner = ''")


class Migration(migrations.Migration):

    dependencies = [("rouh", "0065_synapse_vectors")]

    operations = [migrations.RunSQL(SCHEMA, UNDO), migrations.RunPython(forward, migrations.RunPython.noop)]
