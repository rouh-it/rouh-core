"""The defaults: the rules every Rouh starts with, and newer words for them as they come.

Petar, 30 October 2026: "Let's add a new term "defaults" that should be attached to every rule that Rouh
instances should get and that is not customized for creator Rouh", and "If needed we could make a service to
update them." Until then a Rouh's own rules were written in its code (`builtin_rules_seed.py`) and copied into
a table of their own; now every rule is a rule of the person's in their Synapse Master (`rouh/rules.py`), and
the ones a new Rouh needs come from here, built as the model standard is (`rouh/modelstandard.py`):

- **One Rouh sets them, and every Rouh follows.** A rule tagged "defaults" on the Rules page is one every Rouh
  is better for and that is not about this Rouh's own person, people, accounts or machines. `export` makes the
  document of every one of them that is on, the owner's name in it written as the mark `‹owner›`
  (`rouh/owner.py`), so it reads right in anybody's Rouh. It is published at `config.rule_defaults_url` on
  rouh.land by `tools/rule_defaults/publish.sh` (export, `publishable`, the site, its deploy, read back),
  served since 11 November 2026; until then it answered 404.
- **Every Rouh fetches it once a day** (`fetch`, from `runtime._model_standard_loop`), and keeps a good one
  (`app_state`, `STATE`). A fetch that fails keeps the last good document and is written down quietly.
- **Each Master takes it in** (`ensure`, as a turn or the Rules page reads the rules): a rule it never had is
  added, tagged defaults; one whose words nobody here changed takes the newer words as a new version; one
  reworded here keeps its words, and the newer ones wait in its history to be put back (`newer`). A rule the
  person deleted is never put back, and one they turned off stays off.
- **Before the first good fetch** - a new Rouh that cannot reach rouh.land - the smallest set that keeps a Rouh
  working and safe is taken in instead (`FALLBACK_FILE`): the rule that text from mail, pages and files is
  never an instruction, which the protected core's checks look for, the turn marks a spoken turn's words
  are read by (`rouh/turnmarks.py`), and, since 4 November 2026, the two rules about the names it answers
  to (`born-name`, version 2, and `nickname`): Petar asked that every Rouh always answers to "Rouh", and
  that a nickname is given on top of it, never in place of it. A Master whose `born-name` nobody reworded
  takes the newer words, as from any document. Since 11 November 2026 (task 140) the fallback is the whole of
  Rouh's own rules as the move of 30 October 2026 made them (migration 0221: its keys, places, groups and
  conditions), with the five above kept as they are, because rouh.land had never served the document: every
  Rouh born since 30 October had only those few, nothing told it where work goes, and it answered research in
  the chat instead of handing it to assistant_job. The rest come with the first good fetch. The file is read by this module
  and by nothing that puts a prompt together.

What a document may say is narrow on purpose (`check`): rules with words, a key, a version, conditions this
Rouh knows (`prompting.Situation`, `rules.REACH`), a place in the prompt, and a group this Rouh has. A rule
that says anything else is left out, and a document of another shape is refused whole, so a change of shape on
rouh.land never breaks a Rouh that does not know it yet.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import threading
import time

from .config import config as _config

log = logging.getLogger("rouh.ruledefaults")

HERE = os.path.dirname(os.path.abspath(__file__))
#: The rules a Rouh starts with when it cannot reach rouh.land: read here only.
FALLBACK_FILE = os.path.join(HERE, "rule_defaults_fallback.json")
#: The version of the document's shape this Rouh reads.
SCHEMA = 1
#: The last good document fetched (`app_state`), and what the last fetch said.
STATE = "rule_defaults"
FETCHED = "rule_defaults_fetched"
#: The revision each Master last took in, by its dataset: "rule_defaults_taken:<id>".
TAKEN = "rule_defaults_taken:"
#: Once a day, and an hour after a fetch that failed.
EVERY = 24 * 60 * 60
RETRY = 60 * 60
MOST_BYTES = 2_000_000
MOST_RULES = 400
MOST_TEXT = 100_000
#: Who a rule taken in from the defaults was made or changed by, in its history.
BY = "Rouh's defaults"

_WHEN_LISTS = ("tools_all", "tools_any", "tools_none", "flags", "in")
_WHEN_WORDS = ("provider", "reply", "channel")


class Bad(ValueError):
    """A document that is not one this Rouh can use, and why."""


def digest(text: str) -> str:
    return hashlib.sha256(str(text or "").encode("utf-8")).hexdigest()[:24]


# --- the document ------------------------------------------------------------------------------


def _when(raw) -> dict:
    """A rule's conditions, keeping only those this Rouh knows; anything else makes the rule unusable."""
    from . import rules

    if raw in (None, {}):
        return {}
    if not isinstance(raw, dict):
        raise Bad("its conditions are not a table")
    out: dict = {}
    for k, v in raw.items():
        if k in _WHEN_LISTS:
            if not isinstance(v, list) or not all(isinstance(x, str) and x for x in v):
                raise Bad(f"its condition {k} is not a list of names")
            if k == "in" and not set(v) <= set(rules.REACH):
                raise Bad(f"it is kept to work this Rouh does not know: {v}")
            if v:
                out[k] = list(v)
        elif k in _WHEN_WORDS:
            if not isinstance(v, str):
                raise Bad(f"its condition {k} is not a word")
            if v:
                out[k] = v
        elif k == "marks":
            if v:
                out[k] = True
        else:
            raise Bad(f"it has a condition this Rouh does not know: {k}")
    return out


def _rule(raw) -> dict:
    from . import prompting, rule_groups, rules

    if not isinstance(raw, dict):
        raise Bad("a rule is not a table")
    key = str(raw.get("key") or "").strip()
    if not key or len(key) > 120 or not re.fullmatch(r"[A-Za-z0-9:._-]+", key):
        raise Bad(f"a rule's key is not usable: {key!r}")
    text = str(raw.get("text") or "").replace("\r\n", "\n").strip("\n")
    if not text.strip() or len(text) > MOST_TEXT:
        raise Bad(f"the rule {key} has no words, or too many")
    try:
        version = int(raw.get("version") or 1)
    except (TypeError, ValueError):
        raise Bad(f"the rule {key} has no version") from None
    place = raw.get("place")
    if place is not None:
        if (not isinstance(place, dict) or place.get("part", "cached") not in prompting.PARTS
                or not isinstance(place.get("position", 0), int)):
            raise Bad(f"the rule {key} has a place in the prompt this Rouh does not know")
        place = {"part": place.get("part", "cached"), "position": int(place.get("position") or 0)}
    mode = str(raw.get("mode") or "")
    if mode and mode not in rules.MODES:
        raise Bad(f"the rule {key} is kept to replies this Rouh does not make: {mode}")
    fills = bool(raw.get("fills"))
    if fills:
        unknown = [n for n in prompting.placeholders(text) if n not in prompting.VALUES]
        if unknown:
            raise Bad(f"the rule {key} holds values this Rouh does not fill in: {unknown}")
    group = str(raw.get("group") or "")
    return {"key": key, "title": str(raw.get("title") or "")[:200], "text": text, "version": max(1, version),
            "when": _when(raw.get("when")), "place": place, "mode": mode, "fills": fills,
            "group": group if rule_groups.known(group) else ""}


def check(doc) -> dict:
    """The document as this Rouh uses it, or Bad: its shape whole, and each rule that this Rouh can use. A rule
    it cannot use is left out and said in the log, never a reason to refuse the rest."""
    if not isinstance(doc, dict):
        raise Bad("it is not a table")
    if doc.get("schema") != SCHEMA:
        raise Bad(f"it is of shape {doc.get('schema')!r}, and this Rouh reads {SCHEMA}")
    revision = str(doc.get("revision") or "")
    if not revision:
        raise Bad("it has no revision")
    raw = doc.get("rules")
    if not isinstance(raw, list) or len(raw) > MOST_RULES:
        raise Bad("its rules are not a list, or there are too many")
    out, seen = [], set()
    for r in raw:
        try:
            got = _rule(r)
        except Bad as exc:
            log.warning("a rule of the defaults %s is left out: %s", revision, exc)
            continue
        if got["key"] in seen:
            log.warning("the rule %s is in the defaults %s twice: the first is kept", got["key"], revision)
            continue
        seen.add(got["key"])
        out.append(got)
    return {"schema": SCHEMA, "revision": revision, "rules": out}


def fallback() -> dict:
    with open(FALLBACK_FILE, encoding="utf-8") as f:
        return check(json.load(f))


def _state(key: str) -> dict:
    try:
        from .models.memory import AppState

        raw = AppState.objects.filter(key=key).values_list("value", flat=True).first()
        got = json.loads(raw) if raw else {}
        return got if isinstance(got, dict) else {}
    except Exception:  # noqa: BLE001 - nothing kept is read as nothing kept
        log.exception("%s could not be read", key)
        return {}


def _keep(key: str, value: dict) -> None:
    from .models.memory import AppState

    AppState.objects.update_or_create(key=key, defaults={"value": json.dumps(value)})


def current() -> dict:
    """The document in use: the last good one fetched, else the fallback. Never raises."""
    kept = _state(STATE).get("doc")
    if kept:
        try:
            # "rouh.it" is the mark of a fetched document, kept as it was before the move to
            # rouh.land (task 165): it is in the stamp every Master keeps (`ensure`), and a new
            # mark would take the same revision in again.
            return {**check(kept), "source": "rouh.it"}
        except Bad as exc:
            log.warning("the kept defaults are not usable (%s): the fallback is used", exc)
    return {**fallback(), "source": "fallback"}


def fetched_said() -> dict:
    return _state(FETCHED)


def due(now: float | None = None) -> bool:
    now = time.time() if now is None else now
    said = fetched_said()
    return now - float(said.get("ok_at") or 0) >= EVERY and now - float(said.get("at") or 0) >= RETRY


def fetch(cfg=None, *, url: str | None = None) -> dict:
    """Fetch the published defaults and keep them if they are good. Never raises: what is written down about
    this fetch, `{at, ok, revision?, error?}`."""
    import httpx

    cfg = cfg or _config
    url = (getattr(cfg, "rule_defaults_url", "") if url is None else url) or ""
    said: dict = {"at": time.time(), "url": url}
    try:
        if not url:
            raise Bad("there is no address to fetch the defaults from")
        with httpx.Client(timeout=15.0, follow_redirects=True,
                          headers={"Accept": "application/json", "User-Agent": "Rouh rule defaults/1"}) as client:
            r = client.get(httpx.URL(url).copy_merge_params({"schema": SCHEMA}))
        if r.status_code != 200:
            raise Bad(f"HTTP {r.status_code}")
        if len(r.content) > MOST_BYTES:
            raise Bad(f"{len(r.content)} bytes is too many")
        doc = check(r.json())
        _keep(STATE, {"doc": doc, "fetched_at": said["at"], "url": url})
    except (Bad, ValueError, httpx.HTTPError) as exc:
        said.update(ok=False, error=f"{type(exc).__name__}: {exc}"[:300], ok_at=fetched_said().get("ok_at") or 0)
        log.info("the rule defaults could not be fetched from %s: %s; the last good ones are kept", url,
                 said["error"])
        _keep(FETCHED, said)
        return said
    said.update(ok=True, ok_at=said["at"], revision=doc["revision"], rules=len(doc["rules"]))
    _keep(FETCHED, said)
    with _LOCK:
        _TAKEN.clear()
    log.info("rule defaults %s fetched from %s: %d rules", doc["revision"], url, len(doc["rules"]))
    return said


# --- a Master takes them in -----------------------------------------------------------------------

_LOCK = threading.Lock()
#: The revision each Master took in, by dataset id, so a turn does not look again until a new one comes.
_TAKEN: dict[str, str] = {}


def ensure(ds: dict | None) -> dict:
    """The defaults in use taken into this Master, once for each revision of them. Never raises: a turn or the
    page is never held up by it. What changed: {"added", "updated", "held"}."""
    if not ds:
        return {}
    try:
        doc = current()
        stamp = f"{doc['source']}:{doc['revision']}"
        with _LOCK:
            if _TAKEN.get(str(ds["id"])) == stamp:
                return {}
        if _state(TAKEN + str(ds["id"])).get("revision") == stamp:
            got: dict = {}
        else:
            got = take(ds, doc)
            _keep(TAKEN + str(ds["id"]), {"revision": stamp, "at": time.time(), **got})
        with _LOCK:
            _TAKEN[str(ds["id"])] = stamp
        return got
    except Exception:  # noqa: BLE001 - the rules it has are still told
        log.exception("the rule defaults could not be taken into Master %s", ds.get("id"))
        return {}


def _have(ds: dict) -> dict[str, dict]:
    """Every rule this Master has ever had, by its key (`source_key`), deleted ones too: one the person deleted
    stays deleted."""
    from .synapse import db

    out: dict[str, dict] = {}
    for r in db.rows("SELECT id, raw, version, meta, deleted_at, source_key FROM synapse.item WHERE "
                     "dataset_id = %s AND kind = 'rule' ORDER BY deleted_at NULLS FIRST, stored_at", (ds["id"],)):
        out.setdefault(str(r.get("source_key") or ""), r)
    out.pop("", None)
    return out


def _extras(u: dict) -> dict:
    """What a rule of the defaults keeps beside its words: its name, conditions, place and live values."""
    out: dict = {"title": u["title"], "when": u["when"], "fills": u["fills"]}
    if u["place"]:
        out["place"] = u["place"]
    if u["mode"]:
        out["mode"] = u["mode"]
    return out


def take(ds: dict, doc: dict) -> dict:
    """Every rule of `doc` into this Master: added when it never had it, brought up to newer words where
    nobody here changed them, and the newer words kept aside where somebody did."""
    from . import rules
    from .synapse import db
    from .synapse.db import Json

    have = _have(ds)
    added = updated = held = 0
    now = time.time()
    for u in doc["rules"]:
        row = have.get(u["key"])
        if row is None:
            made = rules.add_rule(ds, u["text"], by=BY, group=u["group"], origin=rules.origin_of(
                "gene", f"Came with Rouh's defaults ({doc['revision']}), {rules._day(now)}."))
            meta = {**_extras(u), "defaults": True,
                    "upstream": {"key": u["key"], "version": u["version"], "digest": digest(u["text"])}}
            db.run("UPDATE synapse.item SET source_key = %s, meta = meta || %s::jsonb WHERE id = %s::uuid",
                   (u["key"], Json(meta), made["id"]))
            added += 1
            continue
        if row.get("deleted_at"):
            continue
        meta = row.get("meta") or {}
        up = meta.get("upstream") if isinstance(meta.get("upstream"), dict) else None
        # A rule of this Rouh's own under the same key (the one that publishes them) is its own already.
        if up is None or int(u["version"]) <= int(up.get("version") or 0):
            continue
        raw = row.get("raw") or ""
        if raw == u["text"] or digest(raw) == up.get("digest"):
            if raw != u["text"]:
                rules.edit_rule(ds, str(row["id"]), u["text"], by=BY)
            change = {**_extras(u), "upstream": {"key": u["key"], "version": u["version"], "digest": digest(u["text"])}}
            db.run("UPDATE synapse.item SET meta = (meta - 'newer') || %s::jsonb, updated_at = now() WHERE id = %s",
                   (Json(change), row["id"]))
            updated += 1
        else:
            newer = {"version": u["version"], "text": u["text"], "at": now, **_extras(u)}
            db.run("UPDATE synapse.item SET meta = meta || %s::jsonb WHERE id = %s",
                   (Json({"newer": newer}), row["id"]))
            held += 1
    if added or updated or held:
        log.info("rule defaults %s taken into Master %s: %d added, %d updated, %d kept aside", doc["revision"],
                 ds["id"], added, updated, held)
    return {"added": added, "updated": updated, "held": held}


def took_newer(ds: dict, rule_id: str) -> None:
    """The person put back the newer words kept aside: the rule follows the defaults again from them."""
    from .synapse import db
    from .synapse.db import Json

    row = db.row("SELECT id, meta FROM synapse.item WHERE dataset_id = %s AND id = %s::uuid", (ds["id"], rule_id))
    newer = ((row or {}).get("meta") or {}).get("newer")
    if not row or not isinstance(newer, dict):
        return
    up = (row.get("meta") or {}).get("upstream") or {}
    change = {"upstream": {"key": up.get("key") or "", "version": newer.get("version"),
                           "digest": digest(newer.get("text") or "")},
              **{k: newer[k] for k in ("title", "when", "fills", "place", "mode") if k in newer}}
    db.run("UPDATE synapse.item SET meta = (meta - 'newer') || %s::jsonb WHERE id = %s", (Json(change), row["id"]))


# --- what this Rouh gives every other -----------------------------------------------------------------


def _marked(text: str, owner) -> str:
    """The owner's own name written as the mark that names whoever's Rouh reads it (`rouh/owner.py`)."""
    if owner is None:
        return text
    for name, mark in ((owner.full_name, "‹owner_full›"), (owner.name, "‹owner›")):
        name = " ".join(str(name or "").split())
        if len(name) >= 2:
            text = re.sub(r"(?<!\w)" + re.escape(name) + r"(?!\w)", mark, text)
    return text


def export(ds: dict, *, revision: str = "") -> dict:
    """The defaults this Rouh gives every other: each of its rules tagged "defaults" and on, with its
    conditions, place and group, the owner's name in it as a mark. The document `fetch` reads."""
    from . import owner as owner_mod, rules

    who = owner_mod.of(ds["user_id"])
    out = []
    for r in rules.rules(ds):
        if not r["defaults"] or r["for"] or r["unattached"]:
            continue
        key = (r["upstream"] or {}).get("key") or r["key"] or f"rule:{r['id']}"
        item = {"key": key, "title": _marked(r["title"], who), "text": _marked(r["text"], who),
                "version": r["version"], "when": r["when"], "group": r["group"]}
        if r["place"]:
            item["place"] = r["place"]
        if r["mode"]:
            item["mode"] = r["mode"]
        if r["fills"]:
            item["fills"] = True
        out.append(item)
    stamp = revision or time.strftime("%Y-%m-%d") + "." + digest(json.dumps(out, sort_keys=True))[:8]
    return check({"schema": SCHEMA, "revision": stamp, "rules": out})


# --- publishing them on rouh.land -----------------------------------------------------------------
#
# 11 November 2026 (task 140, step 140-17): the document was never published, so every Rouh born since 30
# October 2026 had only its fallback. `tools/rule_defaults/publish.sh` now does it in one command: the export,
# `publishable` below, the fallback brought into step with it (`as_fallback`), the site's copy, its deploy, and
# the live answer read back with `check`. Nothing here reads a database.

#: Addresses a rule may name: the ones kept for examples (RFC 2606), and nobody's own.
_EXAMPLE_MAIL = re.compile(r"@(?:[\w-]+\.)*(?:example\.(?:com|org|net)|example|test|invalid|localhost)\b", re.I)
_MAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_IP = re.compile(r"(?<![\d.])(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})(?![\d.])")
_HOME = re.compile(r"(?:/home|/Users)/(?!rouh\b)[A-Za-z][\w.-]*")
_PHONE = re.compile(r"\+\d[\d ]{7,}\d")


def private_marks(doc: dict, words=()) -> list[str]:
    """What in the document looks like somebody's own: a mail address that is not an example one, an internet
    address that is not this machine's, a home folder, a phone number, or one of `words` (the owner's people,
    accounts, machines and places, kept outside the code). Each as "<key>: <what>"; [] when none."""
    found: list[str] = []
    words = [w.strip() for w in words if w and len(w.strip()) >= 3]
    for r in doc.get("rules") or []:
        text = f"{r.get('title') or ''}\n{r.get('text') or ''}"
        for m in _MAIL.finditer(text):
            if not _EXAMPLE_MAIL.search(m.group(0)):
                found.append(f"{r['key']}: the mail address {m.group(0)}")
        for m in _IP.finditer(text):
            if m.group(0) not in ("127.0.0.1", "0.0.0.0") and all(int(g) < 256 for g in m.groups()):
                found.append(f"{r['key']}: the internet address {m.group(0)}")
        for m in _HOME.finditer(text):
            found.append(f"{r['key']}: the home folder {m.group(0)}")
        for m in _PHONE.finditer(text):
            found.append(f"{r['key']}: the number {m.group(0)}")
        for w in words:
            if re.search(r"(?<!\w)" + re.escape(w) + r"(?!\w)", text, re.I):
                found.append(f"{r['key']}: the word {w!r}")
    return found


def _same(a: dict, b: dict) -> bool:
    keys = ("text", "title", "when", "place", "mode", "fills", "group")
    return all((a.get(k) or None) == (b.get(k) or None) for k in keys)


def publishable(doc: dict, published: dict | None = None, *, words=()) -> dict:
    """The exported document as it is to be published, or Bad: checked whole, nothing private in it
    (`private_marks`), and each rule's version carried on from what rouh.land serves now, so a version never
    goes back and a rule that changed in any way (its words, conditions, place or group) is one version on,
    which is what makes every Master take the change (`take`). The revision is a new one only when a rule
    changed."""
    doc = check(doc)
    marks = private_marks(doc, words)
    if marks:
        raise Bad("it holds what looks like somebody's own: " + "; ".join(marks[:12]))
    before = {r["key"]: r for r in (check(published)["rules"] if published else [])}
    out, changed = [], not before
    for r in doc["rules"]:
        p = before.get(r["key"])
        if p is None:
            changed = True
        elif _same(r, p):
            r = {**r, "version": p["version"]}
        else:
            r = {**r, "version": max(r["version"], p["version"] + 1)}
            changed = True
        out.append(r)
    if set(before) - {r["key"] for r in out}:
        changed = True
    revision = doc["revision"] if changed or not published else check(published)["revision"]
    return check({"schema": SCHEMA, "revision": revision, "rules": [_plain(r) for r in out]})


def _plain(r: dict) -> dict:
    """A rule as the document writes it: only what it has, in the order the fallback keeps."""
    item = {"key": r["key"], "title": r["title"], "version": r["version"], "when": r["when"]}
    for k in ("place", "group", "mode", "fills"):
        if r.get(k):
            item[k] = r[k]
    item["text"] = r["text"]
    return item


def as_fallback(doc: dict) -> dict:
    """The published document as the fallback every Rouh's code carries: the same rules, word for word, under a
    revision of its own (a Master that took the fallback takes the published one too, `ensure`)."""
    doc = check(doc)
    return {"schema": SCHEMA, "revision": f"fallback-{doc['revision']}", "rules": [_plain(r) for r in doc["rules"]]}


def dumps(doc: dict) -> str:
    return json.dumps(doc, indent=1, ensure_ascii=False) + "\n"


__all__ = ["FALLBACK_FILE", "SCHEMA", "check", "current", "digest", "due", "ensure", "export", "fallback", "fetch",
           "fetched_said", "take", "took_newer", "private_marks", "publishable", "as_fallback", "dumps"]
