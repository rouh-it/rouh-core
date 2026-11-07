"""The sets of data Petar experiments with, each kept apart from the others.

A dataset belongs to one person in one organisation (the repository's tenancy
rule: both ids are on the row and in every query that finds it), holds its own
items, links, layers, map, queries and evaluation set, and has its own numbers
(`tuning`, only what differs from the starting values). The chat beside it is
Synapse's one chat, not the dataset's (`rouh/synapse/chat.py`); `chat_id` is
the chat a dataset made before 4 October 2026 had of its own, kept so that
conversation still acts on it.
"""
from __future__ import annotations

from . import db, numbers
from .db import Json

def owner_of(ds: dict) -> dict:
    return {"user_id": ds["user_id"], "org_id": ds["org_id"]}


def me(ds: dict) -> str:
    """The dataset's own person: a person item's id (`people.me`), since 3 October 2026."""
    from . import people

    return people.me(ds)


def me_word(ds: dict) -> str:
    """The dataset's own person as the X-ray writes people in its claims: a first name, lower case."""
    from . import people

    return principal(people.owner_name_of(ds)) or "me"


def principal(name: str) -> str:
    """A name's first word, lower case: how an X-ray names people in its claims (`who`, `to`).
    Readers were these until 3 October 2026; they are person ids now (`people.reader_id`)."""
    word = (name or "").strip().split(" ")[0].split("@")[0].lower()
    return "".join(ch for ch in word if ch.isalnum() or ch in "-_") or "someone"


def mine(dataset_id: str, who) -> dict | None:
    """The dataset, if it is this person's in this organisation; otherwise nothing."""
    try:
        return db.row("SELECT * FROM synapse.dataset WHERE id = %s::uuid AND org_id = %s AND user_id = %s",
                      (str(dataset_id), str(who.org_id), str(who.user_id)))
    except Exception:  # noqa: BLE001 - a malformed id is simply not found
        return None


def by_id(dataset_id: str) -> dict | None:
    return db.row("SELECT * FROM synapse.dataset WHERE id = %s::uuid", (str(dataset_id),))


def by_chat(chat_id: str) -> dict | None:
    if not chat_id:
        return None
    return db.row("SELECT * FROM synapse.dataset WHERE chat_id = %s", (chat_id,))


def listing(who) -> list[dict]:
    return db.rows(
        "SELECT d.id, d.name, d.about, d.example, d.role, d.master, d.chat_id, d.created_at, d.updated_at, d.owner_name, "
        " (SELECT count(*) FROM synapse.item i WHERE i.dataset_id = d.id AND i.deleted_at IS NULL "
        "    AND i.kind NOT IN ('person', 'topic', 'layer')) AS items, "
        " (SELECT count(*) FROM synapse.item i WHERE i.dataset_id = d.id AND i.deleted_at IS NULL "
        "    AND i.kind = 'person') AS people, "
        " (SELECT count(*) FROM synapse.item i WHERE i.dataset_id = d.id AND i.deleted_at IS NULL) AS all_items, "
        " (SELECT count(*) FROM synapse.link l WHERE l.dataset_id = d.id) AS links, "
        " (SELECT count(*) FROM synapse.item i WHERE i.dataset_id = d.id AND i.kind = 'layer' "
        "    AND i.deleted_at IS NULL) AS layers, "
        " (SELECT count(*) FROM synapse.job j WHERE j.dataset_id = d.id AND j.done_at IS NULL) AS waiting, "
        " (SELECT coalesce(sum(cost_usd), 0) FROM synapse.trace t WHERE t.dataset_id = d.id) AS cost "
        "FROM synapse.dataset d WHERE d.org_id = %s AND d.user_id = %s ORDER BY d.role = 'people', d.created_at",
        (str(who.org_id), str(who.user_id)))


def create(who, name: str, about: str = "", *, example: str = "", owner_name: str = "",
           own_people: bool = False) -> dict:
    """A new dataset, keeping its own people in itself. Until 4 October 2026 a real one resolved them
    against a separate people set of its owner's (decision 7); Rouh's contacts are Synapse Master's people
    now, the one copy (`contacts.py`), and a lab dataset never reads or writes them."""
    from . import people

    name = " ".join((name or "").split())[:120] or "Untitled set"
    if not (owner_name or "").strip():
        # The dataset's own person is whoever makes it, by their account's name, never a name written here.
        from .. import owner

        found = owner.resolve(who)
        owner_name = (found.name if found else "") or "the owner"
    ds = db.row("INSERT INTO synapse.dataset (org_id, user_id, name, about, example, owner_name) "
                "VALUES (%s, %s, %s, %s, %s, %s) RETURNING *",
                (str(who.org_id), str(who.user_id), name, (about or "")[:2000], example, owner_name))
    people.me(ds)
    return ds


def rename(ds: dict, name: str, about: str | None = None) -> dict:
    name = " ".join((name or "").split())[:120] or ds["name"]
    db.run("UPDATE synapse.dataset SET name = %s, about = coalesce(%s, about), updated_at = now() "
           "WHERE id = %s", (name, about, ds["id"]))
    return by_id(ds["id"])


def remove(ds: dict) -> dict:
    """Delete a dataset and everything in it, the logged prompts included (D60)."""
    from . import ingest

    if ds.get("frozen"):
        return {"refused": "This is a frozen benchmark snapshot: the nightly runs measure against it, so it is not "
                           "deleted from the lab (manage.py synapse_benchmark freeze makes a new one)."}
    if ds.get("master"):
        return {"refused": "This is Synapse Master, the memory Rouh reads and writes in every chat, so it is not "
                           "deleted from the lab. Delete single items instead."}
    if ds.get("role") == "people":
        using = db.value("SELECT count(*) FROM synapse.dataset WHERE people_id = %s", (ds["id"],))
        if using:
            return {"refused": f"{using} dataset" + ("" if using == 1 else "s") + " resolve their people here, so the "
                               "people set stays while they do. Delete them first."}

    counts = db.row(
        "SELECT (SELECT count(*) FROM synapse.item WHERE dataset_id = %s) AS items, "
        "(SELECT count(*) FROM synapse.link WHERE dataset_id = %s) AS links, "
        "(SELECT count(*) FROM synapse.passage WHERE dataset_id = %s) AS passages, "
        "(SELECT count(*) FROM synapse.trace WHERE dataset_id = %s) AS traces",
        (ds["id"],) * 4) or {}
    redacted = ingest.redact_logs_for_dataset(ds)
    db.run("DELETE FROM synapse.dataset WHERE id = %s", (ds["id"],))
    counts["logged_requests_redacted"] = redacted
    return counts


def settings(ds: dict, override: dict | None = None) -> numbers.Settings:
    """The numbers this dataset works by; its models are its organisation's Models page's
    (`numbers.MODEL_USES`)."""
    return numbers.settings_for(ds.get("tuning") or {}, override, str(ds.get("org_id") or ""))


def tune(ds: dict, changes: dict) -> tuple[dict, list[str]]:
    """Set some numbers on a dataset; `None` puts one back to its starting value."""
    tuning = dict(ds.get("tuning") or {})
    problems = []
    for key, value in (changes or {}).items():
        if value is None:
            tuning.pop(key, None)
            continue
        try:
            cleaned = numbers.clean(key, value)
        except (ValueError, TypeError) as exc:
            problems.append(str(exc))
            continue
        start = numbers.defaults().get(key)
        if cleaned == start:
            tuning.pop(key, None)
        else:
            tuning[key] = cleaned
    db.run("UPDATE synapse.dataset SET tuning = %s::jsonb, updated_at = now() WHERE id = %s",
           (Json(tuning), ds["id"]))
    ds["tuning"] = tuning
    return ds, problems


def people(ds: dict) -> list[dict]:
    """Who may ask in this dataset: its own person, and every person who reads one of its items.
    `key` is the person's id; `name` is for the screen."""
    from . import people as ppl

    got = db.rows("SELECT principal, count(*) AS items FROM synapse.reader WHERE dataset_id = %s "
                  "GROUP BY principal ORDER BY count(*) DESC", (ds["id"],))
    counts = {r["principal"]: r["items"] for r in got if r["principal"] != "everyone"}
    owner = me(ds)
    counts.setdefault(owner, 0)
    names = ppl.names(list(counts))
    return [{"key": k, "name": names.get(k, k), "items": v, "me": k == owner}
            for k, v in sorted(counts.items(), key=lambda kv: (kv[0] != owner, -kv[1], names.get(kv[0], "")))]
