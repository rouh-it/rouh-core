"""Every rule is a rule of the person's: Rouh's built-in rules moved into Synapse Master, and their tables gone.

Petar, 30 October 2026: "Fully remove that lock", "Every rule should be in a database and editable. Nothing
should be hardcoded", "Built in concept should disappear ... all rules should be equal", and a "defaults" tag
on every rule that every Rouh should get. Until then Rouh's own rules were rows of `builtin_rule`, an
organisation's own, made from a seed in the code, twenty of them locked on (`rouh/builtin_rules.py`).

So, once, for each person's Master in an organisation that had them, every row is made a rule of that
Master's, with its words exactly as they were, its version and its earlier versions (`builtin_rule_change`),
whether it was on, its group, and what the code needed of it beside its words: when it is told (`when`), its
place in the prompt (`place`), and whether its words hold live values (`fills`) - all kept in the rule's own
meta now (`rouh/rules.py`, `rouh/prompting.py`). Each is tagged defaults, but for the one sentence about the
name this Rouh had before, which is about this one Rouh alone. Three pieces of what the code said become
something else:

- "own-mail", which only said Rouh's own address, and the first sentence of "clock", which only said the date
  and the time, are live values, put in the prompt by the code (`brain.Brain._system`), and are not rules;
- the run's own two lines - never the em dash, and how what a run writes must sound - were text in
  `rules.run_block`, and are rules kept to jobs and runs.

The rules for written and spoken replies, put into every Master on its first turn until now, are tagged
defaults too, and follow the defaults where nobody reworded them. Every "builtin" origin is "rouh".
"""
import hashlib
import json
import time

from django.db import migrations

#: The groups the Rules page had for each built-in rule (`rule_groups.BUILTIN`), with "About Rouh" new.
GROUPS = {
    "identity": "about", "born-name": "about", "no-own-mail": "about", "model-luna": "about",
    "model-other": "about", "yourself": "about", "new-rouh": "about",
    "asking": "asking", "asking-permission": "asking", "screen": "product", "stopping": "rouh", "orb": "rouh",
    "web": "web", "web-luna": "web", "web-look-up": "web", "web-their-words": "asking", "youtube": "web",
    "linkedin": "web", "pictures": "web", "browser": "web", "shipping": "web", "rouh-links": "web",
    "browser-handoff": "web", "browser-errands": "web",
    "where-work-goes": "work", "research": "work", "no-workspace": "work", "together": "work",
    "job-mail": "mail", "helper": "work", "background-jobs": "work", "one-program": "work",
    "this-machine": "machines", "workspace": "work", "threads": "work", "waiting": "work",
    "decisions": "asking", "publishing": "asking",
    "contacts": "people", "meeting-people": "people", "telegram": "mail", "slack": "mail",
    "from-telegram": "mail",
    "remember": "rouh", "thoughts": "rouh", "boxes": "asking", "background-memory": "asking",
    "time-and-goals": "calendar",
    "untrusted": "asking", "order": "asking", "turn-marks": "rouh",
    "clock": "calendar", "this-turn-written": "voice", "this-turn-spoken": "voice",
}
#: Live values, not rules: said by the code from now on.
NOT_RULES = {"own-mail"}
#: Where "clock" stops saying the date and the time and starts saying what to do with them.
CLOCK_SPLIT = "Every time you give or are given is on that clock."
#: Where "identity" starts saying the name this one Rouh had before, which is its alone.
OLD_NAME_SPLIT = " You were called Jarvis until"
#: The two rules for replies as they were first put into every Master, by the digest of their words: one
#: still word for word that follows the defaults; one reworded is the person's.
HOUSE = {"house:written-replies": "f9d2823b25f1ba75a3904d74", "house:spoken-replies": "53c036c3c9e69ca95e637aee"}
#: What `rules.run_block` said itself until now, every run started for the person's own work.
RUN_RULES = (
    ("runs:no-em-dash", "Never the em dash in a run's work",
     "The house writing rule: never use the em dash in anything you write or make. Use a plain dash (-) instead."),
    ("runs:how-it-sounds", "How a run's writing sounds",
     "A rule about how Rouh itself talks in direct conversation with the person, its voice or its character, is "
     "not about this work: it only says how what you write or send must not sound. Whatever this run writes or "
     "sends is warm and professional, and never flirts."),
)
BY = "Rouh, moving its own rules into yours (30 October 2026)"


def _digest(text):
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()[:24]


def _fills(text):
    import string

    try:
        return any(name for _, name, _, _ in string.Formatter().parse(text) if name)
    except ValueError:
        return False


def _day():
    import datetime

    d = datetime.date.today()
    return f"{d.day} {d.strftime('%B %Y')}"


def _put(cur, ds, me, *, key, text, title, meta, version=1, versions=None, at=None):
    """One rule into Master, with its readers, unless Master has one under that key already."""
    cur.execute("SELECT 1 FROM synapse.item WHERE dataset_id = %s AND kind = 'rule' AND source_key = %s",
                [ds, key])
    if cur.fetchone():
        return False
    cur.execute(
        "INSERT INTO synapse.item (dataset_id, kind, source, source_key, title, raw, body, tier, tier_why, "
        "sensitivity, owner, meta, status, said_at, version) VALUES (%s, 'rule', 'rouh-rules', %s, %s, %s, %s, 2, "
        "'a rule', 'normal', %s, %s::jsonb, 'ready', now(), %s) RETURNING id",
        [ds, key, " ".join(text.split())[:200], text, text, me, json.dumps(meta, ensure_ascii=False), version])
    item = cur.fetchone()[0]
    cur.execute("INSERT INTO synapse.reader (dataset_id, item_id, principal) VALUES (%s, %s, %s) "
                "ON CONFLICT DO NOTHING", [ds, item, me])
    for v, words in sorted((versions or {}).items()):
        cur.execute("INSERT INTO synapse.item_version (dataset_id, item_id, version, title, raw, meta, keep_until, "
                    "why) VALUES (%s, %s, %s, %s, %s, '{}'::jsonb, now() + interval '3650 days', %s)",
                    [ds, item, v, " ".join(words.split())[:200], words, f"{BY}: an earlier version"])
    return True


def forwards(apps, schema_editor):
    from django.db import connection

    with connection.cursor() as cur:
        cur.execute("SELECT to_regclass('public.builtin_rule') IS NOT NULL")
        had = cur.fetchone()[0]
        rows_by_org, changes = {}, {}
        if had:
            cur.execute("SELECT org_id, key, title, text, \"when\", part, position, enabled, version, \"group\" "
                        "FROM builtin_rule ORDER BY org_id, part, position, id")
            for org, key, title, text, when, part, position, enabled, version, group in cur.fetchall():
                when = when if isinstance(when, dict) else json.loads(when or "{}")
                rows_by_org.setdefault(org, []).append(
                    {"key": key, "title": title, "text": text, "when": when, "part": part, "position": position,
                     "enabled": enabled, "version": version, "group": group})
            cur.execute("SELECT org_id, key, after FROM builtin_rule_change WHERE action <> 'held' ORDER BY at, id")
            for org, key, after in cur.fetchall():
                after = after if isinstance(after, dict) else json.loads(after or "null") if after else None
                if after and "text" in after and after.get("version"):
                    changes.setdefault((org, key), {})[int(after["version"])] = after["text"]
        cur.execute("SELECT id, org_id, me_id FROM synapse.dataset WHERE master")
        masters = cur.fetchall()
        now = time.time()
        for ds, org, me in masters:
            ds, me = str(ds), str(me) if me else None
            if not me:
                cur.execute("SELECT owner FROM synapse.item WHERE dataset_id = %s AND kind = 'rule' AND owner <> '' "
                            "LIMIT 1", [ds])
                got = cur.fetchone()
                me = got[0] if got else ""
            origin = {"from": "rouh", "said": f"Came with Rouh: one of its own rules until {_day()}, when every "
                                              "rule became yours.", "at": now}
            for r in rows_by_org.get(org, []):
                if r["key"] in NOT_RULES:
                    continue
                text, key = r["text"], r["key"]
                pieces = [(key, r["title"], text, True)]
                if key == "clock" and CLOCK_SPLIT in text:
                    pieces = [(key, "What the date and time mean", text[text.index(CLOCK_SPLIT):], True)]
                elif key == "identity" and OLD_NAME_SPLIT in text:
                    at = text.index(OLD_NAME_SPLIT)
                    pieces = [(key, r["title"], text[:at], True),
                              ("identity-old-name", "The name it had before", text[at + 1:], False)]
                for k, title, words, defaults in pieces:
                    kept_whole = words == text
                    versions = {v: t for v, t in changes.get((org, key), {}).items()
                                if v < r["version"] and t != words} if kept_whole else {}
                    meta = {"title": title, "when": {**r["when"], "in": ["chats"]},
                            "place": {"part": r["part"], "position": r["position"]},
                            "fills": _fills(words), "defaults": defaults, "off": not r["enabled"],
                            "group": r["group"] or GROUPS.get(key, "rouh"), "group_by": "you" if r["group"] else "rouh",
                            "made_by": BY, "origin": origin, "for": [], "scope": "account",
                            "history": [{"at": now, "did": "made", "by": BY}]}
                    if defaults:
                        meta["upstream"] = {"key": k, "version": r["version"] if kept_whole else 1,
                                            "digest": _digest(words)}
                    _put(cur, ds, me, key=k, text=words, title=title, meta=meta,
                         version=r["version"] if kept_whole else 1, versions=versions)
            if rows_by_org.get(org):
                for key, title, words in RUN_RULES:
                    meta = {"title": title, "when": {"in": ["runs"]}, "defaults": True, "group": "voice",
                            "group_by": "rouh", "made_by": BY, "origin": origin, "for": [], "scope": "account",
                            "upstream": {"key": key, "version": 1, "digest": _digest(words)},
                            "history": [{"at": now, "did": "made", "by": BY}]}
                    _put(cur, ds, me, key=key, text=words, title=title, meta=meta)
            # The rules for replies: defaults, and following the defaults where they are still word for word.
            for key, first in HOUSE.items():
                cur.execute("SELECT id, raw, version FROM synapse.item WHERE dataset_id = %s AND source_key = %s "
                            "AND kind = 'rule' AND deleted_at IS NULL", [ds, key])
                for item, raw, version in cur.fetchall():
                    change = {"defaults": True}
                    if _digest(raw) == first:
                        change["upstream"] = {"key": key, "version": int(version or 1), "digest": first}
                    cur.execute("UPDATE synapse.item SET meta = meta || %s::jsonb WHERE id = %s",
                                [json.dumps(change), item])
        cur.execute("UPDATE synapse.item SET meta = jsonb_set(meta, '{origin,from}', '\"rouh\"') "
                    "WHERE kind = 'rule' AND meta->'origin'->>'from' = 'builtin'")
        cur.execute("UPDATE synapse.map_line SET meta = jsonb_set(meta, '{origin,from}', '\"rouh\"') "
                    "WHERE meta->'origin'->>'from' = 'builtin'")


class Migration(migrations.Migration):

    dependencies = [
        ('rouh', '0220_rule_groups_and_switches'),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
        migrations.DeleteModel(name='BuiltinRuleChange'),
        migrations.DeleteModel(name='BuiltinRule'),
    ]
