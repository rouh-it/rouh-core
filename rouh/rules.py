"""Rules: what Rouh always follows, kept in Synapse Master.

Petar, 5 October 2026, on what the memory should become: "some of those things should be notes in the
synapse, some should be kinds of efficiently attached word for word without being fetched from synapse?",
and, asked whether the Memory page should become the Rules page backed by Synapse, "Yes sounds good". So
what was one list of facts, every one of them in every turn (`facts`, `Memory.facts_block`), is three
things, all in the person's Synapse Master (`synapse/master.py`):

- **Rules**: how Rouh must act. An item of kind `rule` (D59). A rule for the whole account is loaded word
  for word into every turn; a rule for a person, a task or a project when that is in play (a person's when
  they are named in the conversation, `involved_people`; a task's or a project's in that task's or project's
  chats). Rules are
  never searched for, ranked or cut, so they are never missed; Synapse's own answers load the same ones
  (`synapse/recall.py`), so there is one list.
- **Vocabulary**: a nickname or a term only they use ("Bo" = Robert Smith), an item of kind `vocabulary`
  (`rouh/vocabulary.py`), told only when a message or a brief uses it. Until 30 October 2026 these were "Your
  words" here, every one told in every turn; they were moved by what each does (`vocabulary.classify`).
- **Notes**: what is true about the world, a decision, a fact. An item of kind `note` in Master, found by
  search when it is needed and never loaded on its own (`NOTE_SOURCE`, which never becomes a rule by itself).

Since 30 October 2026 these are every rule there is (Petar: "all rules should be equal"): what was Rouh's own,
"built-in", in a table of its own and partly locked, is rules here too, each saying when it is told in its own row
(`reach`, `when_of`, `conditions`), and a new Rouh gets its first ones from the defaults (`rouh/ruledefaults.py`).

What was in the old list waits on the Rules page, each fact with the home proposed for it
(`Fact.proposal`, set by `manage.py rules propose`), until the person applies or changes it; until then it
is still told to the model in every turn, under its own heading, so nothing is lost on the way.
"""
from __future__ import annotations

import contextvars
import logging
import re
import time
import uuid

log = logging.getLogger("rouh.rules")

#: Where a rule written on the Rules page or with `remember` comes from.
SOURCE = "rouh-rules"
#: A note kept with `remember`, or moved from the old memory: never made a rule by itself (`ingest.write_rules`).
NOTE_SOURCE = "rouh-memory"
HOMES = ("rule", "vocabulary", "note", "drop")
#: The turns a rule can be kept to (`rouh/replymode.py`): a reply written on a screen, or one spoken aloud. A rule
#: with neither is followed in every turn. Petar, 21 October 2026: "I imagined 1 place should rule the behavior
#: and this is rules."
MODES = ("text", "voice")


# --- whose ------------------------------------------------------------------------------------


def master(user_id: str | None = None, org_id: str | None = None) -> dict | None:
    """The person's Synapse Master: the given person's, or this turn's. Made empty when there is none."""
    from .synapse import chat, contacts

    if user_id and org_id:
        return contacts.master_of(str(user_id), str(org_id))
    got = chat.master_for_turn()
    if got is None:
        who = chat._who()
        if who:
            got = contacts.master_of(who[1], who[0])
    return got


def _me(ds: dict) -> str:
    from .synapse import datasets

    return datasets.me(ds)


# --- what a rule is for -----------------------------------------------------------------------


def target_key(t: dict) -> str:
    """How `rule_for` names what a rule governs: a person by their id, a task by Master's key for it."""
    kind, ident = t.get("type"), str(t.get("id") or "")
    return {"person": ident, "task": f"task:{ident}", "project": f"project:{ident}"}.get(kind, "")


def targets(query: str, *, user_id: str, org_id: str, limit: int = 12) -> list[dict]:
    """What a rule can be for, that a few words find: people, tasks and projects."""
    from . import keeping
    from .synapse import contacts, db

    q = " ".join(str(query or "").split())
    if not q:
        return []
    ds = master(user_id, org_id)
    out = [{"type": "person", "id": c["id"], "name": c["name"], "about": c.get("organisation") or "a contact"}
           for c in contacts.search(user_id, org_id, q, 6)]
    seen = {o["id"] for o in out}
    for r in db.rows("SELECT id, title FROM synapse.item WHERE dataset_id = %s AND kind = 'person' AND deleted_at "
                     "IS NULL AND title ILIKE %s ORDER BY title LIMIT 6", (ds["id"], f"%{q}%")):
        if str(r["id"]) not in seen:
            out.append({"type": "person", "id": str(r["id"]), "name": r["title"], "about": "known to Rouh"})
    for r in db.rows("SELECT id, title FROM task WHERE title ILIKE %s ORDER BY title LIMIT 6", (f"%{q}%",)):
        out.append({"type": "task", "id": str(r["id"]), "name": r["title"], "about": "a task"})
    low = q.lower()
    for pid, p in keeping.projects_now().items():
        if low in (p["name"] or "").lower():
            out.append({"type": "project", "id": pid, "name": p["name"], "about": "a project"})
    return out[:limit]


# --- rules ------------------------------------------------------------------------------------


def _rule(row: dict, ds: dict | None = None) -> dict:
    meta = row.get("meta") or {}
    for_ = [f for f in meta.get("for") or [] if isinstance(f, dict)]
    chips = []
    if ds is not None and row.get("silos"):
        from . import silos

        chips = silos.chips(ds["user_id"], ds["org_id"], row["silos"])
    place = meta.get("place") if isinstance(meta.get("place"), dict) else None
    return {"id": str(row["id"]), "text": row["raw"] or row["title"], "for": for_,
            # Its silos (`rouh/silos.py`): from the chat or task it was made in, or what it is for.
            "silos": [c["key"] for c in chips], "silo_chips": chips,
            "every_turn": not for_ and not meta.get("rule_for"),
            # Kept to written replies ("text") or spoken ones ("voice"); "" is every reply (`MODES`).
            "mode": meta.get("mode") if meta.get("mode") in MODES else "",
            "unattached": bool(meta.get("rule_for")) and not for_, "made_by": meta.get("made_by") or row["source"],
            # Its version: one more with every rewording, the old words kept (D27).
            "version": int(row.get("version") or 1),
            "made_at": row["stored_at"].timestamp() if row.get("stored_at") else 0,
            "changed_at": row["updated_at"].timestamp() if row.get("updated_at") else 0,
            # Turned off on the Rules page: kept, shown greyed, and told to nothing until it is turned on.
            "on": not meta.get("off"),
            # Its group on the page (`rouh/rule_groups.py`), and whether the person put it there ("you") or it
            # was sorted when kept ("rouh"); "" until it has one (`settle`).
            "group": meta.get("group") or "", "group_by": meta.get("group_by") or "",
            # Where it came from (`ORIGINS`): {"from", "said", "at"}, or None until it is worked out (`settle`).
            "origin": _origin(meta),
            # When it is told (`reach`, `prompting.applies`), and where in the prompt a rule with a place goes:
            # {"part": "cached" | "turn", "position"}; None for the person's sections (`prompt_parts`).
            "when": meta.get("when") if isinstance(meta.get("when"), dict) else {}, "place": place,
            # Whether its words hold live values (`prompting.VALUES`) filled in as it is told.
            "fills": bool(meta.get("fills")),
            # A name of its own on the page, or "" for its first line (`_title_of`).
            "title": str(meta.get("title") or ""),
            # Tagged "defaults": useful to every Rouh, and so in what this Rouh gives others (`ruledefaults`).
            "defaults": bool(meta.get("defaults")),
            # Marked useful to others: kept for the person alone now, and good enough to be made standard
            # (`set_useful`, `make_standard`); set by the person, or by Rouh when it keeps the rule.
            "useful": bool(meta.get("useful")),
            # Where it came from in the defaults Rouh gives every Rouh, and newer words for it kept aside
            # because it was reworded here (`ruledefaults.ensure`).
            "upstream": meta.get("upstream") if isinstance(meta.get("upstream"), dict) else None,
            "newer": meta.get("newer") if isinstance(meta.get("newer"), dict) else None,
            # Moved from the Agent instructions page: {"heading", "rank", "statement"}, so every agent is told
            # it under its old heading and in its old place (`agent_instructions.agent_rules`).
            "agent": meta.get("agent") if isinstance(meta.get("agent"), dict) else None,
            "key": row.get("source_key") or ""}


_RULE_COLUMNS = "id, title, raw, source, source_key, meta, silos, version, stored_at, updated_at"


def rules(ds: dict, *, every: bool = False) -> list[dict]:
    """The rules in Master that are on, oldest first; with `every`, those turned off too (the Rules page, and
    `forget`, which finds a rule whether it is on or not). Everything that tells a conversation, a run or
    Synapse's answers what to follow reads it without `every`, so a rule turned off is told to nothing."""
    from .synapse import db

    got = [_rule(r, ds) for r in db.rows(
        f"SELECT {_RULE_COLUMNS} FROM synapse.item WHERE dataset_id = %s "
        "AND kind = 'rule' AND deleted_at IS NULL ORDER BY stored_at, id", (ds["id"],))]
    return got if every else [r for r in got if r["on"]]


# --- where and when a rule is told ---------------------------------------------------------------
#
# Petar, 30 October 2026: "I need to know every rule when it gets included. Every chat call, every agent or
# only when a specific tool is used. And specific conditions. That has to be super clear." So what a rule's row
# says - `when`, `place`, `mode`, who or what it is for - decides where it is told, here and nowhere else
# (`reach`, `in_chat`), and its "Conditions:" line is written from the same (`conditions`).

#: The kinds of work a rule can be told in: "chats", every conversation turn of Rouh's (`brain.Brain._system`:
#: typed and spoken chats and their forks, a message from Telegram, a mail case, Slack, a Clockwork turn and the
#: heartbeat's); "runs", every agent Rouh starts: a rule for everything in the standing instructions every agent
#: begins with (`agent_instructions.block`), and one for a person, task or project in the brief of a run about it
#: (`run_block`); and "synapse", Synapse's own answers (`synapse/recall.py`). Helpers (look_into) and Ask AI are told
#: none. A rule's Chat and Agent switches on the Rules page set which (`SIDES`, `set_switch`).
REACH = ("chats", "runs", "synapse")


def when_of(r: dict) -> dict:
    """A rule's conditions for a conversation turn, with which replies it is kept to as one of them."""
    when = {k: v for k, v in (r.get("when") or {}).items() if k != "in" and v}
    if r.get("mode") and not when.get("reply"):
        when["reply"] = r["mode"]
    return when


def reach(r: dict) -> set[str]:
    """Where a rule is told (`REACH`). A rule with a place in the prompt, kept to a kind of reply, or with a
    condition only a conversation turn has, is told only in chats; one Synapse attached to something, only in
    Synapse's answers; any other everywhere. A rule's own `in` narrows that."""
    from . import prompting

    when = when_of(r)
    if r.get("unattached"):
        got = {"synapse"}
    elif r.get("place") or any(when.get(k) for k in prompting.SITUATIONAL):
        got = {"chats"}
    else:
        got = set(REACH)
    said = (r.get("when") or {}).get("in")
    if isinstance(said, list):
        got &= {str(x) for x in said}
    return got


def in_chat(r: dict, situation=None) -> bool:
    """Whether a rule is told in this conversation turn, by everything it says but who or what it is for,
    which `prompt_parts` decides. Without a situation, only whether it reaches chats at all."""
    from . import prompting

    if not r.get("on", True) or "chats" not in reach(r):
        return False
    return situation is None or prompting.applies(when_of(r), situation)


# --- Chat and Agent ------------------------------------------------------------------------------
#
# Petar, 30 October 2026 (fr_61e683ffbada): "I want you to merge the rules and the agents instructions. We will
# have one interface. and each rule will have 2 toggles: Chat ON/OFF button and Agent ON/OFF button." So every
# row of the Rules page has two switches, read from where it is told (`reach`) and written to its `in`: Chat is
# its chats, and Synapse's answers, which are a conversation's too; Agent is every agent Rouh starts. What were
# the agent instructions are rules here, with Agent on and Chat off (`agent_instructions.move_to_rules`), and
# both off is a rule turned off.

#: What each switch stands for, among `REACH`.
SIDES = {"chat": frozenset({"chats", "synapse"}), "agent": frozenset({"runs"})}
#: Why a rule's Agent switch cannot be turned on: it says something only a conversation turn has.
NO_AGENT = ("It is told only in chats, because it has a condition only a chat has (a place in Rouh's own "
            "prompt, a kind of reply, or a tool in use), so no agent can be told it.")
NO_CHAT = "It is told only to agents, because of how it was kept, so no chat can be told it."


def natural_reach(r: dict) -> set[str]:
    """Where a rule could be told: its `reach` before its own `in` narrows it."""
    return reach({**r, "when": {k: v for k, v in (r.get("when") or {}).items() if k != "in"}})


def switches(r: dict) -> dict:
    """A row's two switches: {"chat", "agent"} on or off, and {"chat_can", "agent_can"}, whether each can be
    turned on at all, with the reason it cannot ("chat_why", "agent_why")."""
    where, can = reach(r) if r.get("on", True) else set(), natural_reach(r)
    out = {side: bool(where & got) for side, got in SIDES.items()}
    out.update({f"{side}_can": bool(can & got) for side, got in SIDES.items()})
    out["chat_why"] = "" if out["chat_can"] else NO_CHAT
    out["agent_why"] = "" if out["agent_can"] else NO_AGENT
    return out


def for_every_agent(r: dict) -> bool:
    """Whether every agent Rouh starts is told this rule in its standing instructions
    (`agent_instructions.block`): on, its Agent switch on, and for no one person, task or project, since those
    are told in a run's brief only when the run is about them (`run_block`)."""
    return (r.get("on", True) and "runs" in reach(r) and not r.get("for") and not r.get("unattached")
            and not r.get("mode"))


def set_switch(ds: dict, ref: str, which: str, on: bool, *, by: str) -> bool:
    """Turn a rule's Chat or Agent switch on or off; the other stays as it is. Both off is the rule
    turned off (`set_on`), and turning one on again turns it on, told only where its switches now say."""
    if which not in SIDES:
        raise ValueError("A rule has two switches, Chat and Agent.")
    _, ident = _ref(ref)
    event = _event(f"{which} {'on' if on else 'off'}", by)
    r = one(ds, ident)
    if r is None:
        return False
    natural, side = natural_reach(r), SIDES[which]
    if on and not natural & side:
        raise ValueError(NO_AGENT if which == "agent" else NO_CHAT)
    where = reach(r) if r["on"] else set()
    want = (where - side) | ((natural & side) if on else set())
    if not want:
        return _merge_rule(ds, ident, {"off": True}, event)
    when = {k: v for k, v in (r.get("when") or {}).items() if k != "in"}
    if want != natural:
        when["in"] = sorted(want)
    return _merge_rule(ds, ident, {"off": False, "when": when}, event)


#: How each kind of work is said on a rule's "Conditions:" line. Plain words: a student reads them.
_CHATS = "every chat (typed, spoken, Telegram, mail, Slack, Clockwork and heartbeat turns)"
_RUNS = "every agent Rouh starts (a job, a run of the one program, a worker)"
_SYNAPSE = "Synapse's answers"


def _join(words: list[str], joint: str = "and") -> str:
    return words[0] if len(words) == 1 else ", ".join(words[:-1]) + f" {joint} " + words[-1]


def condition_lines(r: dict) -> list[str]:
    """When a rule is told, in plain words, one condition to a line, from what its row says: the same data
    `reach`, `in_chat`, `prompt_parts` and `run_block` decide from, so the lines cannot say other than what
    happens. Petar, 30 October 2026: "conditions- make it in bullet points, each condition on new line", so the
    page draws each line as a bullet of its own."""
    from . import prompting

    where = reach(r)
    situ = prompting.situation_words(when_of(r))
    targets = [f for f in r.get("for") or [] if isinstance(f, dict)]
    said = {"chats": _CHATS, "runs": _RUNS, "synapse": _SYNAPSE}
    lines = [] if r.get("on", True) else ["Off: told to nothing until it is turned on. When on:"]
    if r.get("unattached"):
        lines.append("Only in Synapse's answers, and only when a search of your memory finds what it is about")
    elif targets:
        people = [f["name"] for f in targets if f.get("type") == "person"]
        tasks = [f["name"] for f in targets if f.get("type") == "task"]
        projects = [f["name"] for f in targets if f.get("type") == "project"]
        bits = []
        if people:
            bits.append(f"{_join(people)} {'is' if len(people) == 1 else 'are'} named (by whole or first name, "
                        "or by an entry of your vocabulary that means them) in the chat's latest message, its name or its "
                        "last 40 messages, or in a job's or run's instructions")
        if tasks:
            bits.append(f"it is a chat of the task {_join(tasks)}, or a job or run on that task or naming it")
        if projects:
            bits.append(f"it is a chat of the project {_join(projects)}, or a job or run in it or naming it")
        lines += [("Only when " if i == 0 else "Or when ") + b for i, b in enumerate(bits)]
        if "synapse" in where:
            lines.append("And in Synapse's answers that find " + ("them" if people and len(people) > 1 else "it"))
    elif situ:
        lines.append(f"In {_CHATS}")
        lines += [("Only when " if i == 0 else "And when ") + w for i, w in enumerate(situ)]
    elif where == {"runs"}:
        lines.append(f"Only in {_RUNS}")
    else:
        lines += [f"Every turn, in {said[w]}" for w in ("chats", "runs", "synapse") if w in where]
    left = [w for w, place in (("agents", "runs"),) if place not in where]
    if "chats" not in where and not r.get("unattached"):
        left.insert(0, "chats")
    lines.append("Never in " + _join(left + ["helpers", "Ask AI"], "or"))
    return lines


def conditions(r: dict) -> str:
    """The same as `condition_lines`, as one sentence after "Conditions:", for a model reading the list."""
    return "Conditions: " + "; ".join(condition_lines(r)).replace(":;", ":") + "."


def _paragraphs(text: str) -> str:
    """The text as it was written: every line, blank line and indent kept, so a Markdown list nested by its
    indent stays nested; only Windows line endings, spaces at the ends of lines and blank lines at either end
    go.

    Until 5 October 2026 every rule was squeezed onto one line here, so a long one written as paragraphs and a
    list arrived on the Rules page as one unreadable block, and so did what Rouh was told. Until 16 October
    2026 the spaces at the start of each line were still squeezed out, which flattened a nested list."""
    lines = str(text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    return "\n".join(line.rstrip() for line in lines).strip("\n")


def too_long(what: str, n: int, most: int, split: str) -> str:
    """The refusal of something longer than it may be: how long it is, the limit, and what to do instead."""
    return (f"{what[:1].upper()}{what[1:]} is {n:,} characters long, and the limit is {most:,}, so nothing was "
            f"saved. {split}")


def _clean(text: str) -> str:
    """A rule's words, whole and as written, however long; a ValueError only when there are none.

    Until 16 October 2026 a rule was cut here at 2,000 characters without a word, and `remember` still said
    "Kept as a rule you always follow": Petar's principles (task 117), 6,000 characters, were kept cut off in
    the middle of a sentence, so most of them never reached a conversation. Petar, the same day: "Please make
    sure a rules don't have maximum length, I want those principles in one rule." So a rule has no limit,
    here, on the Rules page or on its way into a prompt."""
    text = _paragraphs(text)
    if not text.strip():
        raise ValueError("A rule cannot be empty.")
    return text


def _check_values(text: str) -> None:
    """The words of a rule that holds live values (`prompting.VALUES`): only those values, and a brace of the
    words themselves doubled, so what is filled in is what was meant."""
    from . import prompting

    try:
        names = prompting.placeholders(text)
    except ValueError:
        raise ValueError("A { or } on its own is not allowed in this rule: write {{ or }} for a brace.") from None
    unknown = [n for n in names if n not in prompting.VALUES]
    if unknown:
        raise ValueError("Rouh fills in only these values: " + ", ".join("{" + n + "}" for n in prompting.VALUES)
                         + ". " + ", ".join("{" + n + "}" for n in unknown) + " is not one of them.")


def add_rule(ds: dict, text: str, for_: list[dict] | None = None, *, by: str = "page", chat_id: str = "",
             origin: dict | None = None, group: str = "", title: str = "", where: set[str] | None = None,
             more: dict | None = None) -> dict:
    """A new rule: for the whole account, or for the people, tasks and projects in `for_`. Its silos come from
    what it is for, or else from the chat it was made in (`_silos_of`); none when neither says. `origin` is
    where it came from (`origin_of`), and every caller says it; `group` the group the person picked, or "" to
    sort it by what it says (`rule_groups.sort`); `title` a name of its own; `where`, when given, where it is told
    (`REACH`, as its Chat and Agent switches set it); `more`, anything else its meta keeps."""
    from . import rule_groups
    from .synapse import db, ingest
    from .synapse.db import Json

    text = _clean(text)
    for_ = [{"type": f["type"], "id": str(f["id"]), "name": str(f.get("name") or "")} for f in for_ or []
            if isinstance(f, dict) and f.get("type") in ("person", "task", "project") and f.get("id")]
    made = ingest.make_rule(ds, text, None, why=by, targets=[target_key(f) for f in for_] or None)
    picked = group if rule_groups.known(group) else ""
    meta = {"for": for_, "made_by": by, "origin": origin or origin_of("unknown", "Not said when it was kept."),
            "group": picked or rule_groups.sort(text, for_), "group_by": "you" if picked else "rouh",
            "history": [_event("made", by)], **(more or {})}
    if title:
        meta["title"] = " ".join(str(title).split())[:120]
    if where is not None:
        meta["when"] = {"in": sorted(set(where) & set(REACH))}
    db.run("UPDATE synapse.item SET source = %s, source_key = %s, meta = meta || %s::jsonb WHERE id = %s",
           (SOURCE, f"rule:{uuid.uuid4().hex[:12]}", Json(meta), made["id"]))
    got, why = _silos_of(ds, for_, chat_id)
    if got:
        from . import silos

        silos.set_item(ds, made["id"], got, by=silos.BY_SOURCE, why=why)
    return one(ds, made["id"])


def _silos_of(ds: dict, for_: list[dict], chat_id: str = "") -> tuple[list[str], str]:
    """A new rule's silos (`rouh/silos.py`): those of the tasks, projects and people it is for, or else of the
    chat it was made in (its task's or project's); ([], "") when nothing says."""
    from . import silos
    from .synapse import db

    uid, oid = ds["user_id"], ds["org_id"]
    got: list[str] = []
    names: list[str] = []
    for f in for_ or []:
        if f["type"] in ("task", "project"):
            keys, name = silos.of_owner(uid, oid, f["type"], f["id"])
        else:
            keys = list(db.value("SELECT silos FROM synapse.item WHERE id = %s::uuid", (f["id"],)) or [])
            name = f.get("name") or "the person"
        if keys:
            got += [k for k in keys if k not in got]
            names.append(name)
    if got:
        return silos.ordered(uid, oid, got), "what it is for: " + ", ".join(names)
    if chat_id:
        keys, name = silos.of_chat(uid, oid, chat_id)
        if keys:
            return keys, f"the chat it was made in, of {name}"
    return [], ""


def one(ds: dict, rule_id: str) -> dict | None:
    from .synapse import db

    row = db.row(f"SELECT {_RULE_COLUMNS} FROM synapse.item WHERE dataset_id = %s "
                 "AND id = %s::uuid AND kind = 'rule' AND deleted_at IS NULL", (ds["id"], str(rule_id)))
    return _rule(row, ds) if row else None


def edit_rule(ds: dict, rule_id: str, text: str, *, by: str = "page", silos=None, mode=None) -> dict | None:
    """What a rule says, changed; its old words kept as a version (D27). Who it is for stays. `silos`, when
    given, are its silos as the person picked them (`rouh/silos.py`), by key. `mode`, when given, is the
    replies it is kept to: "text", "voice", or "" for every one (`MODES`)."""
    from .synapse import datasets, db
    from .synapse.db import Json

    row = db.row("SELECT * FROM synapse.item WHERE dataset_id = %s AND id = %s::uuid AND kind = 'rule' "
                 "AND deleted_at IS NULL", (ds["id"], str(rule_id)))
    if row is None:
        return None
    text = _clean(text)
    if (row.get("meta") or {}).get("fills"):
        _check_values(text)
    if text != (row["raw"] or ""):
        db.run("INSERT INTO synapse.item_version (dataset_id, item_id, version, title, raw, meta, keep_until, why) "
               "VALUES (%s, %s, %s, %s, %s, %s::jsonb, now() + make_interval(days => %s), %s)",
               (ds["id"], row["id"], row["version"], row["title"], row["raw"], Json(row.get("meta") or {}),
                int(datasets.settings(ds).version_days), f"{by}: the rule was reworded"))
        db.run("UPDATE synapse.item SET title = %s, raw = %s, body = %s, version = version + 1, updated_at = now() "
               "WHERE id = %s", (" ".join(text.split())[:200], text, text, row["id"]))
    if silos is not None and sorted(silos) != sorted(row.get("silos") or []):
        from . import silos as silo_store

        got = silo_store.set_item(ds, row["id"], list(silos))
        if not got.get("ok"):
            raise ValueError(got.get("why") or "Its silos could not be kept.")
    if mode is not None:
        mode = str(mode or "")
        if mode and mode not in MODES:
            raise ValueError("A rule is for every reply, written replies or spoken replies.")
        if mode != ((row.get("meta") or {}).get("mode") or ""):
            db.run("UPDATE synapse.item SET meta = CASE WHEN %s = '' THEN meta - 'mode' "
                   "ELSE meta || jsonb_build_object('mode', %s::text) END, updated_at = now() WHERE id = %s",
                   (mode, mode, row["id"]))
    return one(ds, rule_id)


def delete_rule(ds: dict, rule_id: str, *, by: str = "page") -> bool:
    from .synapse import ingest

    return bool(ingest.delete(ds, str(rule_id), by=by).get("ok"))


def _rebuild_map(ds: dict) -> None:
    from .synapse import datasets, mapping

    try:
        mapping.queue(ds, datasets.settings(ds), force=True)
    except Exception:  # noqa: BLE001 - what changed is kept; the map catches up on its next rebuild
        log.exception("the map could not be queued for a rebuild")


# --- on and off, groups, where each came from, and what happened to it --------------------------
#
# Petar, 29 October 2026, of the Rules page: "every rule should be able to be turned of, like the agents. with
# a toggle button", and "are some of those automatically added? if so I need a flag- I want to be able to see
# clearly what was added automatically vs what I added manually." So a rule keeps, beside its words, in its
# item's meta: whether it is off, its group (`rouh/rule_groups.py`), where it came from, and a short history
# of what was done to it.

#: Where a rule came from, one of these on every rule. Petar, 30 October 2026 (fr_0034ebae3ca2): "I need to
#: know where this rule came from": "manual", added by the person by hand on the Rules page (or Synapse's lab);
#: "chat", out of a conversation, because Rouh decided it should be kept or the person asked for it (an email
#: the person handled with Rouh is a conversation too); "agents", work done by Rouh's agents led to it (a job's
#: or run's report, a scheduled turn, Synapse reading a note, a job applying a plan); "gene", a gene or mutation
#: from the pool added or changed it, which is how the defaults every Rouh starts with arrive
#: (`rouh/ruledefaults.py`); "unknown", nothing kept says, rather than a guess.
#: Until that day they were "you", "auto", "rouh" (and "builtin" before it); `origin_kind` reads those still.
ORIGINS = ("manual", "chat", "agents", "gene", "unknown")
#: Who a rule is for, the second label on every rule: "creator", the person who made it, never published; or
#: "instances", tagged defaults, so every Rouh installed from now on gets it (`ruledefaults.export`).
SCOPES = ("creator", "instances")
#: How many things done to one rule are kept with it.
HISTORY_MOST = 60


def origin_kind(origin: dict | None) -> str:
    """Which of `ORIGINS` an origin is, reading the names kept before 30 October 2026 by what their sentence
    says: "you" was the Rules page or the lab (manual) or the person's words in a chat or email (chat); "auto"
    was Rouh in a conversation (chat) or a note of its software, a scheduled turn or Synapse (agents); "rouh"
    and "builtin" came with Rouh's defaults (gene)."""
    if not isinstance(origin, dict):
        return "unknown"
    was, said = str(origin.get("from") or ""), str(origin.get("said") or "")
    if was in ORIGINS:
        return was
    if was in ("rouh", "builtin"):
        return "gene"
    if was == "you":
        return "chat" if said.startswith(("From your words", "From your own email")) else "manual"
    if was == "auto":
        if "a note of its software" in said or "scheduled turn" in said or said.startswith("Synapse made"):
            return "agents"
        return "chat"
    return "unknown"


def origin_of(source: str, said: str, at: float | None = None) -> dict:
    """Where a rule came from: one of `ORIGINS`, and a sentence saying what added it."""
    said = " ".join(str(said or "").split())[:300]
    return {"from": origin_kind({"from": source, "said": said}), "said": said, "at": at or time.time()}


def _origin(meta: dict) -> dict | None:
    """A rule's or word's kept origin, its name read as one of `ORIGINS`; None until `settle` works it out."""
    got = meta.get("origin")
    if not isinstance(got, dict):
        return None
    return {**got, "from": origin_kind(got)}


def scope_of(r: dict) -> str:
    """Who a rule is for (`SCOPES`): every Rouh only when it is tagged defaults and is one `ruledefaults.export`
    gives away, which a rule for a person, task or project, one Synapse attached, or a word never is."""
    if r.get("kind", "rule") != "rule" or not r.get("defaults") or r.get("for") or r.get("unattached"):
        return "creator"
    return "instances"


def can_standard(r: dict) -> str:
    """Why a rule could not be made standard, or "" when it can: a word, and a rule kept to one person, task
    or project or attached by Synapse, are about this Rouh's own person and never go to another Rouh."""
    if r.get("kind", "rule") != "rule":
        return "A word of yours is yours alone, so it never goes to other Rouh instances."
    if r.get("for") or r.get("unattached"):
        return ("A rule for one person, task or project is about your own life, so it never goes to other Rouh "
                "instances.")
    return ""


def _event(did: str, by: str, **more) -> dict:
    return {"at": time.time(), "did": did, "by": str(by or "")[:200], **more}


def _with(history, event: dict) -> list:
    return ([h for h in history or [] if isinstance(h, dict)] + [event])[-HISTORY_MOST:]


def _ref(ref: str) -> tuple[str, str]:
    """A rule as the page names it: "r:<id>". Until 30 October 2026 "w:<key>" was one of the person's words,
    in Vocabulary since (`rouh/vocabulary.py`)."""
    kind, _, ident = str(ref or "").partition(":")
    if kind != "r" or not ident:
        raise ValueError("That is not a rule on this page.")
    return kind, ident


def _rule_meta(ds: dict, rule_id: str) -> dict | None:
    from .synapse import db

    return db.row("SELECT id, meta FROM synapse.item WHERE dataset_id = %s AND id = %s::uuid AND kind = 'rule' "
                  "AND deleted_at IS NULL", (ds["id"], str(rule_id)))


def _merge_rule(ds: dict, rule_id: str, change: dict, event: dict) -> bool:
    from .synapse import db
    from .synapse.db import Json

    row = _rule_meta(ds, rule_id)
    if row is None:
        return False
    change = {**change, "history": _with((row.get("meta") or {}).get("history"), event)}
    db.run("UPDATE synapse.item SET meta = meta || %s::jsonb, updated_at = now() WHERE id = %s",
           (Json(change), row["id"]))
    return True


def set_on(ds: dict, org_id: str, ref: str, on: bool, *, by: str) -> bool:
    """Turn a rule off, or on again. Off, it stays on the page and is told to nothing - no
    conversation, no run, no Synapse answer - until it is turned on. Every rule can be: Petar, 30 October 2026,
    "Fully remove that lock". What a rule says is never what allows or refuses an action; every check of a
    permission is code, and stays whether the rule about it is on or off."""
    _, ident = _ref(ref)
    return _merge_rule(ds, ident, {"off": not on}, _event("on" if on else "off", by))


def set_group(ds: dict, org_id: str, ref: str, group: str, *, by: str) -> bool:
    """Move a rule to another group, by hand: it stays there, and is never sorted again by itself."""
    from . import rule_groups

    if not rule_groups.known(group):
        raise ValueError("Pick one of the groups.")
    _, ident = _ref(ref)
    return _merge_rule(ds, ident, {"group": group, "group_by": "you"}, _event("group", by, group=group))


def _standard_rule(ds: dict, ref: str) -> tuple[str, dict]:
    """A rule that could go to every Rouh, by its ref, or a refusal saying why it cannot (`can_standard`)."""
    kind, ident = _ref(ref)
    if kind != "r":
        raise ValueError(can_standard({"kind": "word"}))
    r = one(ds, ident)
    if r is None:
        raise LookupError("That rule is not there any more.")
    why = can_standard({**r, "kind": "rule"})
    if why:
        raise ValueError(why)
    return ident, r


def set_defaults(ds: dict, ref: str, on: bool, *, by: str) -> bool:
    """Tag a rule "defaults", or take the tag off. A rule tagged is one every Rouh is better for and that is not
    about this Rouh's own person, people, accounts or machines: what this Rouh gives every other one as its first
    rules (`ruledefaults.export`), and on the page its scope is Rouh instances (`scope_of`). Petar, 30 October
    2026: "Every rule that will be beneficial to Rouh instances should be marked defaults". A rule for one
    person, task or project is theirs alone and is never tagged."""
    _, ident = _ref(ref)
    if on:
        ident, _ = _standard_rule(ds, ref)
    change = {"defaults": bool(on)}
    if on:
        change["useful"] = False
    return _merge_rule(ds, ident, change, _event("defaults on" if on else "defaults off", by))


def set_useful(ds: dict, ref: str, on: bool, *, by: str) -> bool:
    """Mark a rule kept for its creator alone as useful to others, or take the mark off. Petar, 30 October 2026
    (fr_0034ebae3ca2): "a label that tells me this rule that is specifically for me could be useful for others
    and made into a template". The person marks it on the Rules page, or Rouh when it keeps the rule
    (`remember`, `useful`); nothing about it leaves this Rouh until it is made standard (`make_standard`)."""
    if on:
        ident, r = _standard_rule(ds, ref)
        if r["defaults"]:
            raise ValueError("It already goes to every Rouh instance.")
    else:
        _, ident = _ref(ref)
    return _merge_rule(ds, ident, {"useful": bool(on)}, _event("useful on" if on else "useful off", by))


def make_standard(ds: dict, ref: str, *, by: str) -> bool:
    """Make Standard: the rule becomes one of the defaults every Rouh installed from now on starts with, its
    scope Rouh instances, and its Useful mark goes, its job done. It is published with the rest of the defaults
    (`ruledefaults.export`, copied to rouh.land), with the person's name in it replaced by a mark."""
    ident, _ = _standard_rule(ds, ref)
    return _merge_rule(ds, ident, {"defaults": True, "useful": False}, _event("standard", by))


_DID = {"made": "Added", "reworded": "Reworded", "on": "Turned on", "off": "Turned off", "group": "Moved",
        "restore": "Put back", "chat on": "Chat on", "chat off": "Chat off", "agent on": "Agent on",
        "agent off": "Agent off", "standard": "Made standard", "useful on": "Marked useful",
        "useful off": "Useful mark taken off"}


def history(ds: dict, org_id: str, ref: str) -> list[dict]:
    """What was done to one rule, newest first, each with the words it had after it where that is
    kept: {"id", "did", "at", "by", "version", "text", "group"}. `id` is what `restore` takes."""
    from . import rule_groups
    from .synapse import db

    _, ident = _ref(ref)
    out: list[dict] = []
    row = db.row("SELECT id, raw, meta, version, stored_at FROM synapse.item WHERE dataset_id = %s AND "
                 "id = %s::uuid AND kind = 'rule' AND deleted_at IS NULL", (ds["id"], ident))
    if row is None:
        raise LookupError("That rule is not there any more.")
    meta = row.get("meta") or {}
    # Its words at each version: the old ones kept when it was reworded (D27), and the words it has now.
    kept = db.rows("SELECT version, raw, why, made_at FROM synapse.item_version WHERE dataset_id = %s AND "
                   "item_id = %s ORDER BY version", (ds["id"], row["id"]))
    texts = {int(v["version"]): v["raw"] for v in kept}
    texts[int(row["version"] or 1)] = row["raw"]
    made = next((h for h in meta.get("history") or [] if isinstance(h, dict) and h.get("did") == "made"), None)
    origin = meta.get("origin") if isinstance(meta.get("origin"), dict) else {}
    out.append({"id": "v1", "did": "made", "at": row["stored_at"].timestamp() if row.get("stored_at") else 0,
                "by": origin.get("said") or (made or {}).get("by") or meta.get("made_by") or "",
                "version": 1, "text": texts.get(1, "")})
    for v in kept:
        n = int(v["version"]) + 1
        out.append({"id": f"v{n}", "did": "reworded", "at": v["made_at"].timestamp(),
                    "by": str(v.get("why") or "").replace(": the rule was reworded", ""), "version": n,
                    "text": texts.get(n, "")})
    events = [h for h in meta.get("history") or [] if isinstance(h, dict) and h.get("did") not in ("made",)]
    newer = meta.get("newer") if isinstance(meta.get("newer"), dict) else None
    if newer and newer.get("text"):
        # Newer words from the defaults every Rouh starts with, kept aside because it was reworded here
        # (`ruledefaults.ensure`): put back like any version, and then it follows the defaults again.
        out.append({"id": "newer", "did": "held", "at": float(newer.get("at") or 0),
                    "by": "Rouh's defaults", "version": newer.get("version"), "text": newer["text"]})
    for i, h in enumerate(events):
        if h.get("did") == "made":
            h = {**h, "by": origin.get("said") or h.get("by")}
        out.append({"id": f"h{i}" if h.get("text") else "", "did": h.get("did"), "at": float(h.get("at") or 0),
                    "by": h.get("by") or "", "version": h.get("version"), "text": h.get("text") or "",
                    "group": rule_groups.NAMES.get(h.get("group") or "", "")})
    out.sort(key=lambda h: h["at"], reverse=True)
    return out


def restore(ds: dict, org_id: str, ref: str, change: str, *, by: str) -> bool:
    """Put back the words a rule had after one entry of its history."""
    _, ident = _ref(ref)
    got = next((h for h in history(ds, org_id, ref) if h["id"] and h["id"] == str(change)), None)
    if got is None or not got.get("text"):
        raise LookupError("That version has nothing to put back.")
    if got["id"] == "newer":
        done = edit_rule(ds, ident, got["text"], by=f"{by}: took the newer words of Rouh's defaults")
        if done is not None:
            from . import ruledefaults

            ruledefaults.took_newer(ds, ident)
        return done is not None
    done = edit_rule(ds, ident, got["text"], by=f"{by}: put back version {got.get('version') or ''}".strip())
    return done is not None


# --- where each rule came from, worked out for those kept before it was written down ----------------------


def _first_line(text: str) -> str:
    return " ".join(str(text or "").split())


def _chat_title(chat_id: str) -> str:
    try:
        from .models.objects import Chat

        return str(Chat.objects.filter(id=str(chat_id)).values_list("title", flat=True).first() or "")
    except Exception:  # noqa: BLE001 - said without the chat's name
        return ""


def _day(at: float) -> str:
    import datetime

    d = datetime.datetime.fromtimestamp(at or time.time())
    return f"{d.day} {d.strftime('%B %Y')}"


def _owner_name() -> str:
    """The whole name of the person this Rouh is for, as their account has it, or ""."""
    from . import tenancy

    from .models import User

    try:
        who = tenancy.speaker() or tenancy.Tenancy().only_person()
        user = User.objects.filter(id=int(who.user_id)).first() if who else None
    except Exception:  # noqa: BLE001 - nobody to compare with
        return ""
    return " ".join(f"{user.first_name or ''} {user.last_name or ''}".split()) if user else ""


def _said_in(content: str) -> str:
    """The words of a message as it is kept (a JSON string, or a list of blocks), without its markup."""
    import json

    try:
        got = json.loads(content)
    except (TypeError, ValueError):
        return str(content or "")
    if isinstance(got, str):
        return got
    if isinstance(got, list):
        return " ".join(str(b.get("text") or "") for b in got if isinstance(b, dict) and b.get("type") == "text")
    return ""


def _judged(session_id: str, before_id: int, at: float, what: str) -> dict:
    """Where something kept by `remember` in a chat came from: the person's own words when the last thing they
    sent before it was theirs, Rouh on its own when it was a note of Rouh's software (an email arriving, a
    job's report). `what` says what was kept, for the sentence."""
    from .models.memory import TranscriptMessage

    said = ""
    for m in (TranscriptMessage.objects.filter(session_id=session_id, role="user", id__lt=before_id)
              .order_by("-id").values("content", "note")[:12]):
        body = m["content"] or ""
        if body.startswith('[{"type": "tool_result"') or '"type": "tool_result"' in body[:200]:
            continue
        title = _chat_title(session_id)
        if m["note"]:
            if title.startswith("✉"):
                # A mail chat is named "✉️ <sender>: <subject>": the person's own email is their own words.
                sender, _, subject = title.lstrip("✉️ ").strip().partition(": ")
                if _owner_name() and sender.strip().lower() == _owner_name().lower():
                    return origin_of("chat", f"From your own email “{subject or sender}”, {_day(at)}.", at)
                return origin_of("chat", f"Rouh kept this {what} on its own, from an email: "
                                         f"{title.lstrip('✉️ ').strip()}, {_day(at)}.", at)
            first = _first_line(_said_in(body).strip("[").split("]")[0])[:90]
            return origin_of("agents", f"Rouh kept this {what} on its own, after a note of its software ({first}), "
                                     f"{_day(at)}.", at)
        said = _first_line(_said_in(body))[:100]
        place = f" in the chat “{title}”" if title and session_id != "conversation" else " in the main chat"
        return origin_of("chat", f"From your words{place}, {_day(at)}: “{said}”.", at)
    return origin_of("unknown", f"Kept by Rouh with remember on {_day(at)}; what led to it is not kept.", at)


def _remembered() -> list[dict]:
    """Every call of `remember` kept in the conversations, oldest first: its input, and where and when."""
    import json

    from .models.memory import TranscriptMessage

    out = []
    for m in (TranscriptMessage.objects.filter(role="assistant", content__contains='"name": "remember"')
              .order_by("id").values("id", "session_id", "ts", "content")):
        try:
            blocks = json.loads(m["content"])
        except (TypeError, ValueError):
            continue
        for b in blocks if isinstance(blocks, list) else []:
            if isinstance(b, dict) and b.get("type") == "tool_use" and b.get("name") == "remember":
                out.append({"id": m["id"], "session": m["session_id"], "at": m["ts"], "input": b.get("input") or {}})
    return out


def _settle_origin(row: dict, calls: list[dict]) -> dict:
    """Where one rule kept before origins were written down came from, from what it kept and the
    conversations."""
    from .synapse import db

    meta = row.get("meta") or {}
    made_by = str(meta.get("made_by") or "")
    made_at = row["stored_at"].timestamp() if row.get("stored_at") else 0
    text = _first_line(row.get("raw") or "")
    if str(row.get("source_key") or "").startswith("house:"):
        return origin_of("gene", "Came with Rouh, as its first words for how a reply is made.", made_at)
    if row.get("source") == "synapse" and meta.get("made_from"):
        src = db.row("SELECT kind, title, meta FROM synapse.item WHERE id = %s::uuid", (str(meta["made_from"]),))
        if src:
            what = "email" if src["kind"] == "mail" else src["kind"]
            return origin_of("agents", f"Synapse made it on its own from your {what} “{_first_line(src['title'])[:80]}”, "
                                     f"{_day(made_at)}.", made_at)
        return origin_of("agents", f"Synapse made it on its own from something it read, {_day(made_at)}.", made_at)
    if made_by.startswith("page: moved from the old memory") or "moved from the old memory" in made_by:
        key = made_by.rsplit("(", 1)[-1].rstrip(")").strip().lower()
        first = [c for c in calls if str(c["input"].get("key") or "").strip().lower() == key and c["at"] <= made_at]
        if first:
            c = first[-1]
            got = _judged(c["session"], c["id"], c["at"], "fact")
            return origin_of(got["from"], got["said"] + f" Moved here from the old memory, {_day(made_at)}.",
                             made_at)
        return origin_of("manual", f"Moved here by you from your old memory on the Rules page, {_day(made_at)}.", made_at)
    if made_by.startswith("the Rules page") or made_by.startswith("page"):
        extra = made_by.split(": ", 1)[1] if ": " in made_by else ""
        return origin_of("manual", f"Added by you on the Rules page, {_day(made_at)}" + (f" ({extra})" if extra else "")
                         + ".", made_at)
    if made_by == "remember":
        found = [c for c in calls if str(c["input"].get("as") or "") == "rule" and c["at"] <= made_at + 5
                 and _first_line(c["input"].get("text") or c["input"].get("value") or "") == text]
        if found:
            c = found[-1]
            return _judged(c["session"], c["id"], c["at"], "rule")
        return origin_of("unknown", f"Kept by Rouh with remember on {_day(made_at)}; the chat it came from is not "
                                    "kept.", made_at)
    if row.get("source") == "lab":
        return origin_of("manual", f"Added in Synapse's lab, {_day(made_at)}.", made_at)
    return origin_of("unknown", f"Kept on {_day(made_at)}; nothing kept says what added it.", made_at)


def settle(ds: dict) -> int:
    """Give every rule that has none its group and where it came from, worked out once and kept, so
    the page never reshuffles. How many were settled."""
    from . import rule_groups
    from .synapse import db

    # An origin kept under a name from before 30 October 2026 ("you", "auto", "rouh") is written again as one
    # of `ORIGINS` (`origin_kind`), its sentence kept, so what is kept reads as the page does.
    raw = db.rows(f"SELECT {_RULE_COLUMNS} FROM synapse.item WHERE dataset_id = %s AND kind = 'rule' AND "
                  "deleted_at IS NULL AND (NOT meta ? 'origin' OR NOT meta ? 'group' OR "
                  "NOT coalesce(meta->'origin'->>'from', '') = ANY(%s))", (ds["id"], list(ORIGINS)))
    if not raw:
        return 0
    calls = _remembered()
    n = 0
    for row in raw:
        meta = row.get("meta") or {}
        change = {}
        if not isinstance(meta.get("origin"), dict):
            change["origin"] = _settle_origin(row, calls)
        elif meta["origin"].get("from") not in ORIGINS:
            change["origin"] = _origin(meta)
        if not rule_groups.known(meta.get("group")):
            change.update({"group": rule_groups.sort(row.get("raw") or "", meta.get("for") or []),
                           "group_by": "rouh"})
        from .synapse.db import Json

        db.run("UPDATE synapse.item SET meta = meta || %s::jsonb WHERE id = %s", (Json(change), row["id"]))
        n += 1
    log.info("settled the group and origin of %d rules", n)
    return n


# --- the page ---------------------------------------------------------------------------------
#
# Petar, 29 October 2026: "every rule needs to have the same UI. up here there are rules that are seen in full,
# and have date + edit /delete button. down I see another design with a chevron toggle with Edit turn off and
# history button. all should have the same deisgn." So the page gets every rule - his own, those for a person,
# task or project, his words and the built-in ones - as rows of one shape, and draws each the same way.

_MARKS = re.compile(r"^\s*(?:#+\s*|[-*]\s+|\d+\.\s+)?")
_TITLE_MOST = 200


def _title_of(text: str) -> str:
    """What a row is called: the first line of the rule as written, without its Markdown marks; its first
    sentence when that line is long. Never cut in the middle: the rest is in its full text."""
    first = next((line for line in str(text or "").split("\n") if line.strip()), "")
    first = _MARKS.sub("", first).replace("**", "").replace("__", "").strip()
    if len(first) > _TITLE_MOST:
        m = re.search(r"^(.{40,}?[.!?:])\s", first)
        if m:
            return m.group(1)
    return first


def _when(made: float, changed: float) -> tuple[float, str]:
    """The date a row shows: when it was added, or when it last changed if that was later."""
    if changed and made and changed - made > 120:
        return changed, "Changed"
    return made or changed, "Added"


def page_rows(ds: dict, org_id: str = "") -> list[dict]:
    """Every rule on the page as rows of one shape, each in its group, in a fixed order: the rules in the order
    they were kept (those with a place in the prompt in that order, after the rest). Every rule is equal: each can be reworded, turned off and deleted, and each says when it is told
    (`conditions`). A row: {"ref", "kind", "title", "text", "long", "group", "group_by", "from", "from_said",
    "on", "at", "at_said", "for", "mode", "silos", "silo_chips", "version", "defaults", "scope", "useful",
    "standard_no", "conditions" (its `condition_lines`), ...}. "from" is one of `ORIGINS`, "scope" of `SCOPES`."""
    from . import prompting, rule_groups

    out: list[dict] = []
    for i, r in enumerate(rules(ds, every=True)):
        origin = r["origin"] or origin_of("unknown", "")
        title = r["title"] or _title_of(r["text"])
        at, said = _when(r["made_at"], r["changed_at"])
        names = prompting.placeholders(r["text"]) if r["fills"] else []
        where = reach(r)
        out.append({"ref": f"r:{r['id']}", "kind": "rule", "title": title, "text": r["text"],
                    "long": _first_line(r["text"]) != _first_line(title),
                    "group": r["group"] if rule_groups.known(r["group"]) else rule_groups.sort(r["text"], r["for"]),
                    "group_by": r["group_by"] or "rouh", "from": origin["from"], "from_said": origin.get("said") or "",
                    "on": r["on"], "at": at, "at_said": said, "for": r["for"],
                    "mode": r["mode"], "silos": r["silos"], "silo_chips": r["silo_chips"], "version": r["version"],
                    "unattached": r["unattached"], "defaults": r["defaults"], "conditions": condition_lines(r),
                    # Who it is for (`scope_of`), whether it is marked useful to others while it is for its
                    # creator alone, and why it could never go to other Rouh instances ("" when it could).
                    "scope": scope_of({**r, "kind": "rule"}), "standard_no": can_standard({**r, "kind": "rule"}),
                    "useful": r["useful"] and scope_of({**r, "kind": "rule"}) == "creator",
                    "reach": sorted(where), "situational": bool(prompting.situation_words(when_of(r))),
                    **switches(r),
                    "values": names, "values_said": prompting.value_words(names),
                    # Its words were wrapped at eighty characters as the prompt's own lines were, so the page
                    # joins a line that only carries the sentence on.
                    "flow": bool(r["place"]), "newer": bool(r["newer"]),
                    "order": (20_000 + int(r["place"].get("position") or 0)) if r["place"] else i})
    return out


# What the (i) beside each group on the Rules page says: when the rules in it are told to a model, in one
# sentence, from what the code does (Petar, 30 October 2026: "For each rules category, can you in an (I) icon
# explain when those instructions are included"). A group holds rules of every kind, sorted by what they are
# about, and when a rule is told depends on what its row says, so the sentence names the kinds the group holds,
# each clause what `reach`, `in_chat`, `prompt_parts` and `run_block` do. Every rule's own "Conditions:" line
# says the same for that rule (`conditions`).
_INCLUDED = (
    ("always", "a rule with no condition is added to every chat Rouh has, typed, spoken, by Telegram, mail, Slack, "
               "Clockwork or the heartbeat, and to every agent it starts, while its Chat and Agent switches are on"),
    ("chats", "a rule kept to chats, its Agent switch off, is added to every chat Rouh has, never to an agent"),
    ("situational", "a rule with a condition, such as a tool, is added only to chats where that condition holds"),
    ("text", "a rule for written replies is added only when Rouh answers in writing"),
    ("voice", "a rule for spoken replies is added only when Rouh answers out loud"),
    ("runs", "a rule kept to agents, its Chat switch off, is added only to the agents Rouh starts, never to a "
             "chat"),
    ("person", "a rule for a person is added only when that person is named in the conversation, the mail or "
               "a job's instructions"),
    ("place", "a rule for a task or project is added only in its own chats and in jobs that work on it or name "
              "it"),
    ("synapse", "a rule Synapse attached is added only when a search of your memory finds what it is about"),
)


def _included_kind(row: dict) -> str:
    kinds = {f.get("type") for f in row.get("for") or []}
    if "person" in kinds:
        return "person"
    if kinds & {"task", "project"}:
        return "place"
    if row.get("unattached"):
        return "synapse"
    if row.get("mode"):
        return row["mode"]
    where = set(row.get("reach") or REACH)
    if where == {"runs"}:
        return "runs"
    if row.get("situational"):
        return "situational"
    if "runs" not in where:
        return "chats"
    return "always"


def included_said(rows: list[dict]) -> str:
    """When the rules of one group are told to a model, as one sentence, from the kinds of rule it holds; a
    group with none says what a rule added to it would be."""
    have = {_included_kind(r) for r in rows} or {"always"}
    clauses = [said for kind, said in _INCLUDED if kind in have]
    text = "; ".join(clauses)
    return text[:1].upper() + text[1:] + "."


# --- notes ------------------------------------------------------------------------------------


def add_note(ds: dict, text: str, *, title: str = "", project: str = "", task: str = "", by: str = "page") -> dict:
    """A note in Master, found by search when it is needed; never loaded on its own, never a rule by itself.

    Kept whole, however long: Synapse keeps every item's whole text (D25), and until 16 October 2026 a note
    was cut here at 8,000 characters without a word."""
    from .synapse import ingest

    text = _paragraphs(text)
    if not text.strip():
        raise ValueError("A note cannot be empty.")
    me = _me(ds)
    payload = {"kind": "note", "title": " ".join((title or text).split())[:120], "text": text, "source": NOTE_SOURCE,
               "source_key": f"memory:{uuid.uuid4().hex[:12]}", "readers": [me], "owner": me}
    if task:
        payload.update({"task": str(task), "attached_to": [f"task:{task}"]})
    elif project:
        payload["project"] = str(project)
    got = ingest.store(ds, payload, by=by)
    if not got.get("ok"):
        raise ValueError(got.get("why") or "The note could not be kept.")
    return {"id": str(got.get("item") or ""), "title": payload["title"]}


# --- the old memory, to review ----------------------------------------------------------------


def old_facts() -> list[dict]:
    """What is still in the old list, with the home proposed for each."""
    from . import keeping
    from .models.memory import Fact

    names = keeping.project_names()
    out = []
    for f in Fact.objects.order_by("created_at", "id").values("id", "key", "value", "project_id", "proposal",
                                                                "created_at"):
        prop = f.get("proposal") if isinstance(f.get("proposal"), dict) else {}
        out.append({"id": f["id"], "key": f["key"], "value": f["value"], "project": names.get(f["project_id"] or "", ""),
                    "project_id": f["project_id"] or "", "created_at": f["created_at"],
                    "proposal": {"home": prop.get("home") or "rule", "text": prop.get("text") or f["value"],
                                 "for": prop.get("for") or [], "term": prop.get("term") or "",
                                 "meaning": prop.get("meaning") or "", "why": prop.get("why") or ""}})
    return out


def apply_fact(fact_id: int, choice: dict, *, user_id: str, org_id: str, by: str = "page") -> dict:
    """One old fact moved where the person chose: a rule, Vocabulary, a note, or nowhere. The fact then goes."""
    from .models.memory import Fact

    fact = Fact.objects.filter(id=fact_id).first()
    if fact is None:
        raise LookupError("That one is not in the old memory any more.")
    home = str(choice.get("home") or "")
    # "word" is what a proposal made before 30 October 2026 says for Vocabulary.
    home = "vocabulary" if home == "word" else home
    if home not in HOMES:
        raise ValueError("Say where it goes: a rule, Vocabulary, a note, or nowhere.")
    ds = master(user_id, org_id)
    made: dict = {"home": home}
    if home == "rule":
        made["rule"] = add_rule(ds, choice.get("text") or fact.value, choice.get("for") or [],
                                by=f"{by}: moved from the old memory ({fact.key})",
                                origin=origin_of("manual", f"Moved here by you from your old memory ({fact.key})."))
    elif home == "vocabulary":
        from . import vocabulary

        made["vocabulary"] = vocabulary.add(
            ds, choice.get("term") or "", choice.get("meaning") or "", by=by,
            origin=origin_of("manual", f"Moved here by you from your old memory ({fact.key})."))
    elif home == "note":
        made["note"] = add_note(ds, choice.get("text") or fact.value, title=fact.key, project=fact.project_id,
                                by=f"{by}: moved from the old memory")
    Fact.objects.filter(id=fact_id).delete()
    log.info("old memory %s (%s) moved: %s", fact_id, fact.key, home)
    return made


def propose(proposals: dict) -> int:
    """The home proposed for each old fact, by its id: {"12": {"home", "text", "for", "term", "meaning", "why"}}."""
    from .models.memory import Fact

    n = 0
    for ident, prop in proposals.items():
        if isinstance(prop, dict) and prop.get("home") in (*HOMES, "word"):
            n += Fact.objects.filter(id=int(ident)).update(proposal=prop)
    return n


# --- what every turn is told ------------------------------------------------------------------


def _task_of_chat(chat_id: str) -> str:
    from .synapse import db

    if not chat_id:
        return ""
    return str(db.value("SELECT src_id FROM link WHERE rel = 'owns' AND dst_type = 'chat' AND dst_id = %s AND "
                        "src_type = 'task' LIMIT 1", (chat_id,)) or "")


def _indent(text: str) -> str:
    """A rule written in paragraphs, each line after its first set in under its bullet, so it stays one rule."""
    return "\n".join(("  " + line) if line and i else line for i, line in enumerate(str(text).split("\n")))


def _told(rows: list[dict], why) -> list[dict]:
    """Which rules a section of the prompt holds, at which version and why, for what a request was told
    (`prompting.told`)."""
    return [{"id": r["id"], "version": r.get("version", 1), "why": why(r) if callable(why) else why} for r in rows]


def _told_sections(everything: list[dict], *, people: list[dict], here: list[dict],
                   about: str) -> list[tuple[str, dict]]:
    """`_sections`, each with what it holds: (its words, {"key", "title", "why", "rules"})."""
    parts: list[tuple[str, dict]] = []
    everything = [r for r in everything if not r.get("mode")]
    account = [r for r in everything if r["every_turn"]]
    if account:
        parts.append(("Rules you always follow, the person's own (the Rules page under their name; kept in "
                      "Synapse Master):\n" + "\n".join(f"- {_indent(r['text'])}" for r in account),
                      {"key": "rules:every-turn", "title": "Your rules for every conversation",
                       "why": "rules for every conversation", "rules": _told(account, "every conversation")}))
    if people:
        parts.append(("Rules for particular people, followed whenever that person is involved:\n" + "\n".join(
            f"- For {', '.join(f['name'] for f in r['for'] if f['type'] == 'person')}: {_indent(r['text'])}"
            for r in people),
            {"key": "rules:people", "title": "Your rules for people", "why": "each person was named in the conversation",
             "rules": _told(people, lambda r: "for " + ", ".join(f["name"] for f in r["for"]))}))
    if here:
        parts.append((f"Rules for what {about} is about:\n" + "\n".join(
            f"- For {', '.join(f['name'] for f in r['for'] if f['type'] != 'person')}: {_indent(r['text'])}"
            for r in here),
            {"key": "rules:here", "title": f"Your rules for what {about} is about",
             "why": f"its task or project is what {about} is about",
             "rules": _told(here, lambda r: "for " + ", ".join(f["name"] for f in r["for"]))}))
    return parts


def _sections(everything: list[dict], *, people: list[dict], here: list[dict], about: str) -> list[str]:
    """The rules, as the prompt says them, for a turn and for a run alike. A rule kept to
    written or spoken replies is not among them: a turn says the one for its own mode (`reply_parts`), and a
    run, which writes no reply in a conversation, says neither."""
    return [text for text, _ in _told_sections(everything, people=people, here=here, about=about)]


def _old_section() -> list[str]:
    return [text for text, _ in _old_told()]


def _old_told() -> list[tuple[str, dict]]:
    old = old_facts()
    if not old:
        return []
    return [("From the old memory, not yet moved to the Rules page or into Synapse (still true, still "
             "followed):\n" + "\n".join(f"- {f['key']}: {f['value']}" for f in old),
             {"key": "rules:old-memory", "title": "Your old memory, not yet reviewed",
              "why": "kept until it is moved on the Rules page"})]


# --- how a reply is written or spoken ---------------------------------------------------------
#
# Petar, 21 October 2026, in a typed chat that had been answered "ninety-eight dash nineteen": "you obviously
# don't speak most of the time, we have been typing mostly ... why are those instructions outside of the rules?"
# So how a reply is written and how it is spoken are rules kept to written or spoken replies (`mode`), and a turn
# is told the ones for how it is answered (`rouh/replymode.py`), last in its prompt. Until 30 October 2026 the
# first words of the two were here (`HOUSE_RULES`), put into every Master on its first turn; a new Rouh gets them
# with the rest of the defaults (`rouh/ruledefaults.py`).


def _mode_told(everything: list[dict], mode: str) -> list[tuple[str, dict]]:
    """The rules for how this turn's reply is made, written or spoken (`rouh/replymode.py`), with which they are."""
    what = "spoken replies" if mode == "voice" else "written replies"
    rows = [r for r in everything if r.get("mode") == mode and r["every_turn"]]
    if not rows:
        return []
    told = {"key": f"rules:{mode}", "title": f"Your rules for {what}", "why": f"this turn's reply is {what[:-8]}",
            "rules": _told(rows, f"kept to {what}")}
    return [(f"How to make this reply, the person's rules for {what} (the Rules page):\n"
             + "\n".join(f"- {_indent(r['text'])}" for r in rows), told)]


# --- who a conversation involves ---------------------------------------------------------------
#
# Petar, 30 October 2026: in a General chat about the model router all four of his rules for people were in
# Rouh's instructions, though none of those people came up. Until then a conversation was told every rule for
# a person in every turn ("while there are few"), under a heading saying they were followed "whenever that
# person is involved", which is the model left to judge what the code should have. So a person's rules are told
# only when that person is in the conversation: named, by their whole or first name, or by an entry of the
# person's vocabulary that means them (`rouh/vocabulary.py`), in what is being answered now, in the chat's name, or in its last messages - the
# mail a case answers and what a tool read included.

#: The words of the message a turn is answering, which are not in the conversation yet (`brain.Question`).
TURN_WORDS: contextvars.ContextVar[str] = contextvars.ContextVar("rouh_rules_turn_words", default="")
#: How many of a chat's newest messages a person must be named in to be in the conversation.
INVOLVED_MESSAGES = 40


def _message_words(content: str) -> str:
    """Every word of one kept message: its text, and what its tool results said."""
    import json

    try:
        blocks = json.loads(content or "")
    except (TypeError, ValueError):
        return str(content or "")
    if isinstance(blocks, str):
        return blocks
    out: list[str] = []

    def walk(b) -> None:
        if isinstance(b, str):
            out.append(b)
        elif isinstance(b, list):
            for x in b:
                walk(x)
        elif isinstance(b, dict):
            if b.get("type") == "text":
                out.append(str(b.get("text") or ""))
            elif b.get("type") == "tool_result":
                walk(b.get("content"))
            elif b.get("type") == "tool_use":
                out.append(json.dumps(b.get("input") or {}, ensure_ascii=False))

    walk(blocks)
    return "\n".join(out)


def conversation_words(chat_id: str) -> str:
    """What a turn in this chat has in front of it to name somebody: the message being answered, the chat's
    name and its newest messages."""
    from .models.memory import TranscriptMessage

    said = [TURN_WORDS.get(), _chat_title(chat_id) if chat_id else ""]
    if chat_id:
        try:
            said += [_message_words(m) for m in (
                TranscriptMessage.objects.filter(session_id=str(chat_id), live=True, notice=False)
                .order_by("-id").values_list("content", flat=True)[:INVOLVED_MESSAGES])]
        except Exception:  # noqa: BLE001 - the message being answered is still read
            log.exception("the conversation could not be read to see who is in it")
    return "\n".join(s for s in said if s)


def involved_people(everything: list[dict], vocab: list[dict], chat_id: str, text: str | None = None) -> list[dict]:
    """The rules for people who are in this conversation (`conversation_words`, or `text`): a person is in it
    when their whole or first name is, or an entry of the person's vocabulary that the conversation uses
    (`vocabulary.holds`) is about them or names them in its meaning."""
    from . import vocabulary

    rows = [r for r in everything if any(f["type"] == "person" for f in r["for"])]
    if not rows:
        return []
    text = conversation_words(chat_id) if text is None else text
    used = vocabulary.matches({}, text, given=vocab)

    def named(target: dict) -> bool:
        name = target.get("name") or ""
        if _person_named(name, text):
            return True
        return any(any(c.get("type") == "person" and str(c.get("id")) == str(target.get("id"))
                       for c in e["context"]) or _person_named(name, e["meaning"]) for e in used)

    return [r for r in rows if any(f["type"] == "person" and named(f) for f in r["for"])]


def placed(ds: dict | None, part: str) -> list[dict]:
    """The rules on with a place in this part of a conversation's prompt (`prompting.Prompt`), in their order."""
    if not ds:
        return []
    got = [r for r in rules(ds) if r["place"] and r["place"].get("part", "cached") == part]
    return sorted(got, key=lambda r: (int(r["place"].get("position") or 0), r["made_at"], r["id"]))


def _chat_rules(ds: dict, situation=None) -> list[dict]:
    """The rules on that a conversation turn is told in the person's sections: no place of their own, and
    everything they say holding for this turn (`in_chat`)."""
    return [r for r in rules(ds) if not r["place"] and in_chat(r, situation)]


def prompt_parts(chat_id: str = "", situation=None) -> list[tuple[str, dict]]:
    """The rules, word for word, for the system prompt, each section with which rules it holds; and anything still waiting in the old memory, so nothing is lost before it is reviewed. The rules kept
    to written or spoken replies are not here but in `reply_parts`, and the rules with a place of their own are
    told there (`placed`). `situation` is the turn's (`prompting.Situation`): a rule with a condition is told
    only when it holds. The person's vocabulary is not here: an entry is told when a message uses it, in the
    background memory block (`rouh/vocabulary.py`, `synapse/autorecall.py`)."""
    from . import keeping, vocabulary

    parts: list[tuple[str, dict]] = []
    try:
        ds = master()
    except Exception:  # noqa: BLE001 - the old memory is still said below
        log.exception("Synapse Master could not be read for the rules")
        ds = None
    if ds:
        # What is left of the person's old words moved first, by what each does, so none is lost on the way.
        vocabulary.settle(ds)
        everything = _chat_rules(ds, situation)
        project = keeping.project_of_chat(chat_id) if chat_id else ""
        task = _task_of_chat(chat_id)
        people = involved_people(everything, vocabulary.entries(ds), chat_id)
        here = [r for r in everything if any((f["type"] == "task" and f["id"] == task and task)
                                             or (f["type"] == "project" and f["id"] == project and project)
                                             for f in r["for"])]
        parts += _told_sections(everything, people=people, here=here, about="this conversation")
    parts += _old_told()
    return parts


def reply_parts(mode: str = "text", situation=None) -> list[tuple[str, dict]]:
    """The person's rules for how this turn's reply is made, "text" written or "voice" spoken (`MODES`), for the
    end of the system prompt; nothing when Master cannot be read."""
    mode = mode if mode in MODES else "text"
    try:
        ds = master()
        if not ds:
            return []
        return _mode_told([r for r in _chat_rules(ds, situation) if r.get("mode") == mode], mode)
    except Exception:  # noqa: BLE001 - the rest of the prompt is still told
        log.exception("the rules for a %s reply could not be read", mode)
        return []


# --- what every run started for the person is told --------------------------------------------
#
# Petar, 14 October 2026: "Make the auto paste." His rules reached Rouh's own conversations and nothing
# else, so a research run, a visual explainer or any job in his workspace never heard "never sign Petar's
# name" or "never create Anthropic artifacts". So every run started for his own work (`starting.start`)
# begins with them, read from Master at the moment it starts, never a copy kept anywhere that can go stale.

#: The heading the work itself is under once the rules are in front of it, which is also where the
#: section is known to end (`unruled`).
WORK_HEADING = "## What you are asked to do"
_SECTION = re.compile(r"^## [^\n]{0,80}'s standing rules\n.*?^" + re.escape(WORK_HEADING) + r"\n+",
                      re.S | re.M)


def _person_name() -> str:
    from . import tenancy

    try:
        who = tenancy.speaker() or tenancy.Tenancy().only_person()
    except Exception:  # noqa: BLE001 - the section says "The person's" instead
        who = None
    name = str(getattr(who, "name", "") or "").strip().split(" ")[0] if who else ""
    # An account with no first name is named by its username, "alex".
    return f"{name[:1].upper()}{name[1:]}'s" if name else "The person's"


def _named(name: str, text: str, *, case: bool = True) -> bool:
    """Whether `name` is in the brief as words of their own: "Sam" is not inside "Samuel"."""
    name = " ".join(str(name or "").split())
    if len(name) < 3:
        return False
    return re.search(r"(?<!\w)" + re.escape(name) + r"(?!\w)", text, 0 if case else re.I) is not None


def _person_named(name: str, text: str) -> bool:
    """A person is named by their whole name or their first name; never by a surname alone, which two people
    can share."""
    whole = " ".join(str(name or "").split())
    return _named(whole, text) or (" " in whole and _named(whole.split(" ")[0], text))


def _project_named(name: str, text: str) -> bool:
    """A project is named as "the Sales project" or "project Sales", or by a name of more than one word: a
    one-word name such as Rouh or Work is in too many briefs to mean the project by itself."""
    name = " ".join(str(name or "").split())
    return bool(name) and (" " in name and _named(name, text, case=False)
                           or _named(f"{name} project", text, case=False)
                           or _named(f"project {name}", text, case=False))


def _task_named(target: dict, text: str) -> bool:
    """A task is named by its title, as "task 115", or by its folder."""
    from .synapse import db

    if _named(target.get("name") or "", text, case=False):
        return True
    row = db.row("SELECT number, folder FROM task WHERE id = %s", (str(target.get("id") or ""),))
    if not row:
        return False
    return ((row.get("number") is not None
             and re.search(rf"\btask\s+{int(row['number'])}\b", text, re.I) is not None)
            or (bool(row.get("folder")) and row["folder"] in text))


def run_block(brief: str, *, chat_id: str = "", task_id: str = "") -> str:
    """The person's standing rules, as the section a run's brief starts with.

    The rules that reach runs (`reach`), word for word and in the same words Rouh's own prompt has them
    (`_sections`); a rule for a person, a task or a project only when the brief names it or it is the task the
    run works in, or that task's or chat's project; and the entries of the person's vocabulary the brief uses
    (`vocabulary.matches`), each said to be a meaning and not an instruction. Read now, every time. When Master cannot be read
    the run is still started, with a warning in the log and no rules.
    """
    brief = str(brief or "")
    whose = _person_name()
    parts: list[str] = []
    try:
        from . import conversations, keeping, vocabulary

        ds = master()
        if ds:
            vocabulary.settle(ds)
            # A rule for every agent is in its standing instructions already (`agent_instructions.block`), so
            # the brief holds only those for what this run is about.
            everything = [r for r in rules(ds) if "runs" in reach(r) and not for_every_agent(r)]
            task = str(task_id or "") or _task_of_chat(chat_id)
            projects = {p for p in ((keeping.project_of_chat(chat_id) if chat_id else ""),
                                    (conversations.project_of("task", task) if task else "")) if p}
            vocab = vocabulary.entries(ds)
            people = involved_people(everything, vocab, "", text=brief)
            here = [r for r in everything if any(
                (f["type"] == "task" and ((task and f["id"] == task) or _task_named(f, brief)))
                or (f["type"] == "project" and (f["id"] in projects or _project_named(f.get("name"), brief)))
                for f in r["for"])]
            parts += _sections(everything, people=people, here=here, about="this work")
            used = vocabulary.matches(ds, brief, given=vocab)
            if used:
                parts.append(f"What words this work uses mean, from {whose} vocabulary in Synapse Master "
                             f"({vocabulary.DEFINITION}):\n"
                             + "\n".join(vocabulary.line(e) for e in used))
        parts += _old_section()
    except Exception as exc:  # noqa: BLE001 - never a reason not to start the run
        log.warning("the standing rules could not be read for a run, so it starts without them: %s", exc,
                    exc_info=True)
        parts = []
    # How the section is framed is the code's; every instruction in it is a rule (until 30 October 2026 the
    # em dash rule and the one on how a run's writing sounds were here, and they are rules for runs now).
    lead = (f"{whose} standing rules. Follow them where they apply to this work. They never widen what this "
            "run is allowed to do.\n"
            "They are read from the Rules page as this run starts.")
    body = "\n\n".join([lead, *parts])
    return f"## {whose} standing rules\n\n{body}\n\n{WORK_HEADING}\n\n"


def unruled(brief: str) -> str:
    """The brief without the standing rules a start put in front of it: what the run was actually asked."""
    return _SECTION.sub("", str(brief or ""))


def with_rules(brief: str, *, chat_id: str = "", task_id: str = "") -> str:
    """The brief with the standing rules read now in front of it, in place of any it already had."""
    asked = unruled(brief).lstrip()
    return run_block(asked, chat_id=chat_id, task_id=task_id) + asked


def listing(ds: dict) -> dict:
    """Everything kept and on, for `list_memory`. A rule turned off is only counted: it is not to be
    followed, so its words are not handed to the model. A rule with a place in the prompt or a condition of its
    own is listed by its name and its conditions, since a turn it applies to has its words already."""
    everything = rules(ds)
    plain = [r for r in everything if not r["place"] and not when_of(r) and reach(r) >= {"chats", "runs"}]
    rest = [r for r in everything if r not in plain and not r["for"] and not r["mode"]]
    from . import vocabulary

    off = sum(1 for r in rules(ds, every=True) if not r["on"])
    return {"turned_off_on_the_rules_page": off,
            "every_turn": [r["text"] for r in plain if r["every_turn"]],
            "written_replies": [r["text"] for r in everything if r["every_turn"] and r["mode"] == "text"],
            "spoken_replies": [r["text"] for r in everything if r["every_turn"] and r["mode"] == "voice"],
            "with_conditions": [{"rule": r["title"] or _title_of(r["text"]), "conditions": conditions(r)}
                                for r in rest],
            "for": [{"for": [f["name"] for f in r["for"]], "rule": r["text"]} for r in everything if r["for"]],
            "vocabulary": {e["term"] + "".join(f' (also "{a}")' for a in e["aliases"]): e["meaning"]
                           for e in vocabulary.entries(ds)},
            "vocabulary_is": "Vocabulary in Synapse Master (/synapse/vocabulary): what the person means by their "
                             f"words, {vocabulary.DEFINITION}; each entry is put beside a message that uses it.",
            "old_memory_not_yet_reviewed": {f["key"]: f["value"] for f in old_facts()},
            "notes": "Notes are in Synapse Master: synapse_find or synapse_query finds them."}


def find(ds: dict, said: str) -> list[dict]:
    """Rules and Vocabulary entries that a few words find, for `forget`."""
    from . import vocabulary

    q = [w for w in str(said or "").lower().split() if w]
    if not q:
        return []
    out = [{"kind": "rule", **r} for r in rules(ds, every=True) if all(w in r["text"].lower() for w in q)]
    out += [{"kind": "vocabulary", **e} for e in vocabulary.entries(ds)
            if all(x in " ".join([*vocabulary.names(e), e["meaning"]]).lower() for x in q)]
    return out


__all__ = ["HOMES", "MODES", "NOTE_SOURCE", "ORIGINS", "REACH", "SCOPES", "SOURCE", "can_standard", "make_standard",
           "origin_kind", "scope_of", "set_useful", "add_note", "add_rule",
           "apply_fact", "condition_lines", "conditions", "delete_rule", "for_every_agent", "natural_reach", "set_switch",
           "switches", "edit_rule", "find", "history",
           "in_chat", "listing", "master", "old_facts", "one", "origin_of", "placed", "propose", "prompt_parts",
           "reach", "reply_parts", "restore", "rules", "set_defaults", "set_group", "set_on", "settle", "targets",
           "when_of"]


# --- the model's tools ------------------------------------------------------------------------


def _target_for(said: str, *, user_id: str, org_id: str) -> tuple[list[dict], str]:
    """The person, task or project a rule was said to be for, or why it could not be told which."""
    said = " ".join(str(said or "").split())
    if not said:
        return [], ""
    found = targets(said, user_id=user_id, org_id=org_id, limit=8)
    exact = [t for t in found if t["name"].lower() == said.lower()]
    if len(exact) == 1 or len(found) == 1:
        return [(exact or found)[0]], ""
    if not found:
        return [], f'Nothing called "{said}" was found among the people, tasks and projects, so nothing was kept.'
    names = "; ".join(f"{t['name']} ({t['type']})" for t in found[:6])
    return [], f'"{said}" could be several: {names}. Ask which one is meant; nothing was kept.'


def _turn_origin(chat_id: str, args: dict, what: str) -> dict:
    """Where a rule or an entry kept with `remember` in this turn comes from: Rouh on its own in a turn nobody
    started (a scheduled one), after a note of its software (an email arriving, a job's report), or when it
    says the person did not ask (`asked` false); otherwise the person's own words."""
    from . import protected

    if protected.UNATTENDED.get():
        return origin_of("agents", f"Rouh kept this {what} on its own in a scheduled turn, {_day(time.time())}.")
    got = _judged(chat_id, 1 << 62, time.time(), what) if chat_id else origin_of(
        "unknown", f"Kept by Rouh with remember on {_day(time.time())}, outside any chat.")
    if got["from"] == "chat" and got["said"].startswith("From your words") and args.get("asked") is False:
        return origin_of("chat", f"Rouh kept this {what} on its own, from what you said: "
                         + got["said"].split(": ", 1)[-1])
    return got


def remember(args: dict, *, chat_id: str = "") -> str:
    """`remember`: keep a rule, a note or an entry of Vocabulary, and say where it went."""
    from .synapse import chat

    who = chat._who()
    if not who:
        return "There is nobody signed in to keep it for."
    org_id, user_id = who
    ds = master(user_id, org_id)
    kind = str(args.get("as") or "").strip().lower()
    text = str(args.get("text") or args.get("value") or "").strip()
    try:
        # "word" is what this was until 30 October 2026, and a conversation may still say it.
        if kind in ("vocabulary", "word"):
            from . import vocabulary

            about, why = _target_for(str(args.get("for") or ""), user_id=user_id, org_id=org_id)
            if why:
                return why
            e = vocabulary.add(ds, args.get("term") or args.get("key") or "", args.get("meaning") or text,
                               aliases=args.get("aliases") or [], context=about, by="remember",
                               origin=_turn_origin(chat_id, args, "vocabulary entry"))
            also = "".join(f' (also "{a}")' for a in e["aliases"])
            return (f'Kept in Vocabulary in Synapse Master: "{e["term"]}"{also} means {e["meaning"]}. It is on the '
                    "Vocabulary page (/synapse/vocabulary), and is put beside any message that uses the word; it "
                    "is not told to every conversation.")
        if kind == "note":
            from . import keeping

            task = _task_of_chat(chat_id)
            project = "" if task else keeping.project_of_chat(chat_id)
            n = add_note(ds, text, title=str(args.get("key") or ""), task=task, project=project, by="remember")
            return (f'Kept as a note in Synapse Master ("{n["title"]}"). It is found when it is needed '
                    "(synapse_find, synapse_query), and is not told to every conversation.")
        if kind != "rule":
            return ('Say how to keep it: as "rule" (something to always do or never do), "note" (something true '
                    'to look up later) or "vocabulary" (what the person means by a word or a nickname). When it is '
                    "not clear which, ask them: a fact to keep, or a rule to always follow?")
        for_, why = _target_for(str(args.get("for") or args.get("project") or ""), user_id=user_id, org_id=org_id)
        if why:
            return why
        r = add_rule(ds, text, for_, by="remember", chat_id=chat_id, origin=_turn_origin(chat_id, args, "rule"))
        # Rouh's own judgement that it would help other people's Rouh too: the Useful label, for the person
        # to make it standard or not.
        if args.get("useful") is True and not can_standard({**r, "kind": "rule"}):
            set_useful(ds, f"r:{r['id']}", True, by="remember")
    except ValueError as exc:
        return str(exc)
    if r["for"]:
        names = ", ".join(f"{f['name']} ({f['type']})" for f in r["for"])
        plain = ", ".join(f["name"] for f in r["for"])
        return f"Kept as a rule for {names}, on the Rules page. It is followed whenever {plain} is involved."
    return "Kept as a rule you always follow, on the Rules page. Every conversation is told it from now on."


def forget(args: dict) -> str:
    """`forget`: a rule or an entry of Vocabulary, found by its words; never a guess between two."""
    ds = master()
    if not ds:
        return "There is no memory to forget anything from."
    said = str(args.get("text") or args.get("key") or "")
    found = find(ds, said)
    old = [f for f in old_facts() if all(w in (f["key"] + " " + f["value"]).lower() for w in said.lower().split())]
    if not found and len(old) == 1:
        from .models.memory import Fact

        Fact.objects.filter(id=old[0]["id"]).delete()
        return f'Forgotten from the old memory: "{old[0]["key"]}".'
    if not found:
        return ("No rule or Vocabulary entry matches that. A note in Synapse is deleted with synapse_delete; old-memory "
                "matches: " + (", ".join(f'"{f["key"]}"' for f in old) or "none") + ".")
    if len(found) > 1:
        return "Several match; ask which one: " + "; ".join(
            f'{f["kind"]} "{f.get("text") or f.get("term")}"' for f in found[:6]) + ". Nothing was deleted."
    f = found[0]
    if f["kind"] == "vocabulary":
        from . import vocabulary

        vocabulary.delete(ds, f["id"], by="forget")
        return f'Forgotten "{f["term"]}" from Vocabulary in Synapse Master. It is gone from the Vocabulary page.'
    delete_rule(ds, f["id"], by="forget")
    return f'Forgotten the rule "{f["text"]}". It is gone from the Rules page.'
