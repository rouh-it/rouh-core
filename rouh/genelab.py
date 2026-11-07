"""Shared genes: Rouh's side of a gene registry, and the lab they arrive in (GENES.md).

Petar, 12 October 2026: genes are ideas written in a contract - what a gene is, where it
appears, what it touches and how to remove it - and "they can really modify Rouh in any
possible way", so they need no particular permissions and are rated instead (narrowed on 24
October 2026 to "in any way except the protected core", GENES.md; the signature checks below are
the protected core's since, guard/rouh_guard/geneverify.py, asked through rouh/guardface.py). What a gene
touches is shown before it is installed, as information, never as a gate. The registry
(task 98, step 98-13; rouh.land, closed for now) publishes an index of genes and a blocklist,
each signed with its Ed25519 key. This is the receiving end.

**Off until a person points it somewhere.** An organisation with no registry address asks
nothing of anybody. Rouh Land Account, Gene Pool takes the address and the registry's public key, which
is pinned there: a list whose signature does not hold against that key is refused, and so
is one older than the list already kept (a replayed blocklist would otherwise lift a block),
and one of the wrong kind (the blocklist passed off as the index, both being signed by the
same key).

**Installing is a person's yes, and nothing else.** No beat, no tool and no model installs a
gene: only an administrator pressing Install on the gene's page, after its contract was
drawn there. The press carries the hash of the contract they were shown, and a contract
that changed in between is refused, so nothing is installed that was not read. The files
are fetched from where the index points, their SHA-256 is checked against the signed
index, and their Sigstore signature against the publisher's build identity wherever the
registry gives one. They arrive in the lab: kept here, never run, behind the gene's own
switch, which starts off. Switched on, the gene is in the navigation and in Search where
its contract says it appears, marked Shared, and opens its page here. A gene's place in
the navigation is all a contract can ask of Rouh's page: it never presses a control, never
takes the dedicated area or the account menu, and its glyph is redrawn from lines and
shapes alone.

**Nothing a gene's text says is an instruction to Rouh.** A contract, a brief and every
file are data, drawn as text for the person to read. None of it is put in front of a model,
and no route here takes an action from it.

**Removing is real, and checked.** Remove deletes the gene's row, its files and its switch,
and then looks for anything still named for it - the row, the files, the switch, a link in
the navigation, a line in Search - and compares what the lab holds with what it held just
before the gene came. The result is said on the page and kept in the lab's history.

**The blocklist is fetched on a beat** (`Watch`, hourly) as well as on the page. A gene it
names that is installed is switched off at once and marked blocked, and the person who
installed it is told (`notices`). A hard block cannot be switched on again; a soft one
(quality) can, with the reason in front of them. A newer version in the index is shown
with what changed in its contract, and told once; it is never installed by itself.

**Whose.** Everything is the organisation's, keyed by `org_id` and asked for by it; only
its administrators change anything (`AGENTS.md`, "Whose data is it").
"""
from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
import os
import re
import time
from dataclasses import dataclass
from html.parser import HTMLParser
from types import SimpleNamespace
from urllib.parse import urljoin, urlsplit

from . import clock, genes, switches

log = logging.getLogger("rouh.genelab")

#: Where in a registry the two signed lists are, from its address.
INDEX = "index.json"
BLOCKLIST = "blocklist.json"
#: What each signed list says it is.
INDEX_KIND = "rouh-gene-index"
BLOCKLIST_KIND = "rouh-gene-blocklist"
#: The organisation's switch for the whole lab: off, no shared gene shows anywhere.
LAB_SWITCH = "gene_lab"
#: How much is fetched at most, and how long it may take.
MOST_LIST = 5 * 1024 * 1024
MOST_ARTIFACT = 20 * 1024 * 1024
MOST_UNPACKED = 40 * 1024 * 1024
MOST_FILES = 400
MOST_READ = 256 * 1024
TIMEOUT = 20.0
#: How often the beat asks the registry, in minutes (ROUH_GENES_EVERY_MINUTES).
EVERY_MINUTES = 60.0
#: A gene id, "<publisher>/<name>", as the registry makes them.
GENE_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}/[a-z][a-z0-9-]{1,62}$")
SEMVER = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-([0-9A-Za-z.-]+))?$")
GITHUB_ISSUER = "https://token.actions.githubusercontent.com"
#: The glyph a shared gene gets when its own has nothing left once it is redrawn: a helix.
SHARED_ICON = ('<path d="M7 3c0 6 10 6 10 12s-10 3-10 6"/><path d="M17 3c0 6-10 6-10 12s10 3 10 6"/>'
               '<path d="M8.5 7h7M8.5 17h7"/>')
WHERE = {"list": "a link in the navigation", "dedicated": "a link in the navigation",
         "account": "a link in the navigation", "none": "found by Search"}


class Refused(ValueError):
    """Something a person asked for that is not done, with the reason as a sentence."""


# ---------------------------------------------------------------------------
# Small things
# ---------------------------------------------------------------------------


def _model(name: str):
    from . import models

    return getattr(models, name)


def _org(who) -> str:
    org = str(getattr(who, "org_id", "") or "")
    if not org:
        raise Refused("Sign in first.")
    return org


def _admin(who) -> None:
    if not getattr(who, "is_admin", False):
        raise Refused("Only an administrator of this organisation changes its genes.")


def _name_of(who) -> str:
    return str(getattr(who, "name", "") or getattr(who, "email", "") or getattr(who, "user_id", "") or "")


def canonical(payload) -> bytes:
    """The bytes a registry signs: the payload as JSON, keys sorted, no spaces."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def contract_hash(contract: dict) -> str:
    return sha256(canonical(contract))


def version_key(v: str) -> tuple:
    m = SEMVER.match(str(v or ""))
    if not m:
        return (-1, -1, -1, 0, str(v or ""))
    # A release stands after its own pre-releases.
    return (int(m[1]), int(m[2]), int(m[3]), 0 if m[4] else 1, m[4] or "")


def switch_for(gene: str) -> str:
    """A gene's own switch: its id, made a switch's name, with a few letters of its hash so
    two ids never share one."""
    stem = re.sub(r"[^a-z0-9]+", "_", gene.lower()).strip("_")[:40]
    return f"gene_{stem}_{sha256(gene.encode())[:8]}"


def nav_key(gene: str) -> str:
    """A shared gene's key in the navigation and in Search: never one of Rouh's own ids."""
    return "shared-" + sha256(gene.encode())[:12]


def route_for(gene: str) -> str:
    """A shared gene's own page: under Rouh Land Account, Gene Pool, wherever its manifest puts it
    (Meta, Genes until 4 November 2026)."""
    from . import genes

    return genes.BY_ID["genes"]["route"] + "/" + gene


def _event(org: str, gene: str, what: str, said: str, *, by: str = "", version: str = "",
           detail: dict | None = None) -> None:
    _model("GeneLabEvent").objects.create(org_id=org, gene=gene, version=version, what=what,
                                          said=said[:2000], by=by[:200], detail=detail or {},
                                          at=time.time())


# ---------------------------------------------------------------------------
# The pinned key, and the signed lists
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Key:
    """A registry's Ed25519 public key, checked by the protected core: its PEM and its id."""
    pem: str
    id: str


def _guarded(fn: str, **kw):
    """One of the gene checks, which since 24 October 2026 are the protected core's
    (guard/rouh_guard/geneverify.py, task 98 step 98-23): asked over the guard's socket in a
    container, read from this repository's guard/ elsewhere. Its refusal is this module's."""
    from . import guardface

    try:
        return guardface.gene(fn, **kw)
    except guardface.Refused as exc:
        raise Refused(str(exc)) from None
    except guardface.Unavailable as exc:
        raise Refused(f"the gene checks could not be asked: {exc}") from None


def load_key(pem: str) -> Key:
    """The registry's Ed25519 public key from its PEM, or Refused saying what is wrong."""
    got = _guarded("key_of", pem=pem)
    return Key(pem=got["pem"], id=got["id"])


def key_id(key: Key) -> str:
    """The registry's own name for its key: the first 16 hex of the SHA-256 of its raw bytes."""
    return key.id


def verify(document, key: Key, kind: str) -> dict:
    """A fetched list's payload, if it is signed by the pinned key and is the kind expected.
    Raises Refused saying which of those failed."""
    return _guarded("verify_pem", document=document, pem=key.pem, kind=kind)


# ---------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------


def url_ok(url: str) -> str:
    """An address Rouh may fetch a gene from: https, or http on this machine for a local
    copy of a registry. Anything else is Refused."""
    return _guarded("url_ok", url=url)


#: Rouh's way of fetching, replaceable in a check of one's own.
def fetch(url: str, most: int) -> bytes:
    return _guarded("fetch", url=url, most=most)


def _fetch_list(url: str) -> dict:
    try:
        data = fetch(url, MOST_LIST)
    except Refused:
        raise
    except Exception as exc:
        raise Refused(f"it could not be fetched ({type(exc).__name__})") from None
    try:
        return json.loads(data.decode("utf-8"))
    except ValueError:
        raise Refused("it is not JSON") from None


# ---------------------------------------------------------------------------
# The index, read: one entry per gene version, with its contract
# ---------------------------------------------------------------------------


def _strs(value) -> list[str]:
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, list):
        return [str(v) for v in value if isinstance(v, (str, int, float)) and str(v).strip()][:60]
    return []


def _text(value, most: int = 4000) -> str:
    return str(value).strip()[:most] if isinstance(value, (str, int, float)) else ""


def contract_of(row: dict) -> dict:
    """The contract an index row gives: the whole gene manifest where the registry sends it,
    otherwise what it says of the gene beside what it touches. Exactly as given, so its hash
    is the hash of what the person is shown."""
    for key in ("contract", "manifest"):
        if isinstance(row.get(key), dict):
            return row[key]
    out = {k: row[k] for k in ("name", "title", "summary", "description", "group", "route", "nav",
                               "attaches_to", "touches") if k in row}
    return out


def sections(contract: dict, gene: str = "", summary: str = "") -> dict:
    """A contract as the four things a person reads before installing: what it is, where it
    appears, what it touches and how to remove it. Plain text and lists, nothing else.
    `summary` is what the registry's index says the gene is, beside the contract, for a
    contract that does not say it itself (GENES.md's manifest has a title and no more)."""
    c = contract if isinstance(contract, dict) else {}
    t = c.get("touches") if isinstance(c.get("touches"), dict) else {}
    nav = c.get("nav") if isinstance(c.get("nav"), dict) else {}
    group = c.get("group") if c.get("group") in genes.GROUP_IDS else ""
    place = nav.get("place") if nav.get("place") in genes.PLACES else ("list" if group else "none")
    name = _text(c.get("name"), 80) or gene.split("/")[-1]
    return {
        "name": name,
        "title": _text(c.get("title"), 300),
        "what": _text(c.get("summary") or c.get("description") or c.get("what") or summary, 4000),
        "aliases": _strs(c.get("aliases")),
        "group": group,
        "group_name": dict(genes.GROUPS).get(group, ""),
        "place": place,
        "where": (f"{WHERE[place]} under {dict(genes.GROUPS)[group]}" if group and place != "none"
                  else WHERE.get(place, "found by Search")),
        "route": _text(c.get("route"), 200),
        "attaches_to": [a for a in _strs(c.get("attaches_to")) if a in genes.ATTACHES],
        "maturity": _text(c.get("maturity"), 20),
        "switch": _text(c.get("switch"), 70),
        "permissions": _strs(t.get("permissions")),
        "accounts": _strs(t.get("accounts")),
        "tables": _strs(t.get("tables")),
        "jobs": _strs(t.get("jobs")),
        "remove": _text(t.get("remove"), 4000),
    }


#: The parts of a contract compared between two versions, with the words for each.
COMPARED = (("what", "What it is"), ("title", "Its title"), ("where", "Where it appears"),
            ("attaches_to", "What it attaches to"), ("permissions", "What it does"),
            ("accounts", "Accounts it uses"), ("tables", "Tables it keeps"),
            ("jobs", "Scheduled jobs"), ("remove", "How to remove it"))


def changes(before: dict, after: dict, was_summary: str = "", now_summary: str = "") -> list[dict]:
    """What changed from one contract to the next, part by part: for a list what was added and
    what is gone, for a sentence what it said and what it says now. Information, never a gate."""
    a, b = sections(before, summary=was_summary), sections(after, summary=now_summary)
    out = []
    for key, label in COMPARED:
        old, new = a.get(key), b.get(key)
        if old == new:
            continue
        if isinstance(new, list):
            out.append({"part": key, "label": label, "added": [x for x in new if x not in old],
                        "gone": [x for x in old if x not in new]})
        else:
            out.append({"part": key, "label": label, "was": old or "", "now": new or ""})
    return out


def _rating(value) -> dict | None:
    if isinstance(value, dict):
        avg, count = value.get("average", value.get("avg")), value.get("count", value.get("n"))
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        avg, count = value, None
    else:
        return None
    try:
        avg = round(float(avg), 1) if avg is not None else None
        count = int(count) if count is not None else None
    except (TypeError, ValueError):
        return None
    return {"average": avg, "count": count}


def entry(row) -> dict | None:
    """One index row as Rouh reads it, or None for a row it cannot use (no valid id, version,
    file or hash), which is left out rather than guessed at."""
    if not isinstance(row, dict):
        return None
    gene = _text(row.get("gene") or row.get("id"), 130)
    version = _text(row.get("version"), 40)
    url = _text(row.get("url") or row.get("artifact_url"), 2000)
    digest = _text(row.get("sha256") or row.get("artifact_sha256"), 64).lower()
    if not (GENE_ID.match(gene) and SEMVER.match(version) and url and re.fullmatch(r"[0-9a-f]{64}", digest)):
        return None
    contract = contract_of(row)
    publisher = gene.split("/")[0]
    pub = row.get("publisher")
    pub_name = (_text(pub.get("name") or pub.get("display_name"), 120) if isinstance(pub, dict) else "") \
        or _text(row.get("publisher_name"), 120) or publisher
    sig = row.get("sigstore") if isinstance(row.get("sigstore"), dict) else {}
    if not sig and isinstance(row.get("signature_bundle"), dict) and row["signature_bundle"]:
        sig = {"bundle": row["signature_bundle"]}
    prov = row.get("provenance") if isinstance(row.get("provenance"), dict) else {}
    return {
        "gene": gene, "publisher": publisher, "publisher_name": pub_name,
        "verified_publisher": bool(row.get("verified_publisher")), "official": bool(row.get("official")),
        "version": version, "kind": _text(row.get("kind"), 20), "core_range": _text(row.get("core_range"), 60),
        "published_at": _text(row.get("published_at"), 40),
        "rating": _rating(row.get("rating")), "version_rating": _rating(row.get("version_rating")),
        "page": _text(row.get("page") or row.get("page_url"), 2000),
        "url": url, "sha256": digest, "provenance": {k: _text(v, 300) for k, v in prov.items()
                                                     if isinstance(v, (str, int))},
        "summary": _text(row.get("summary"), 2000),
        "sigstore": sig, "contract": contract, "contract_sha256": contract_hash(contract),
        "sections": sections(contract, gene, _text(row.get("summary"), 2000)),
    }


def catalogue(index: dict) -> dict[str, list[dict]]:
    """Every gene in an index, with its versions newest first."""
    out: dict[str, list[dict]] = {}
    for row in (index or {}).get("genes") or []:
        e = entry(row)
        if e:
            out.setdefault(e["gene"], []).append(e)
    for versions in out.values():
        versions.sort(key=lambda e: version_key(e["version"]), reverse=True)
    return out


def block_for(blocklist: dict, gene: str, version: str) -> dict | None:
    """The blocklist's entry naming this gene or this version of it, a hard one first."""
    found = []
    for b in (blocklist or {}).get("entries") or []:
        if not isinstance(b, dict):
            continue
        target = _text(b.get("target") or b.get("gene"), 200)
        m = re.match(r"^([^@ ]+)(?:[@ ]+(\S+))?$", target)
        if not m:
            continue
        named, at = m[1], m[2] or _text(b.get("version"), 40)
        if named != gene or (at and at != version):
            continue
        found.append({"target": target, "severity": "hard" if b.get("severity") == "hard" else "soft",
                      "reason": _text(b.get("reason"), 600), "what_to_do": _text(b.get("what_to_do"), 600),
                      "at": _text(b.get("at"), 40)})
    found.sort(key=lambda b: b["severity"] != "hard")
    return found[0] if found else None


def blocked_genes(blocklist: dict) -> list[dict]:
    """Each gene the blocklist names as a whole, with its hardest entry."""
    named = {m[1] for e in (blocklist or {}).get("entries") or [] if isinstance(e, dict)
             for m in [re.match(r"^([^@ ]+)$", _text(e.get("target") or e.get("gene"), 200))] if m}
    return [b for b in (block_for(blocklist, g, "") for g in sorted(named)) if b]


# ---------------------------------------------------------------------------
# Sigstore
# ---------------------------------------------------------------------------


def sigstore_check(artifact: bytes, sig: dict, provenance: dict) -> dict:
    """The artifact's Sigstore signature checked, where the registry gives one: {state, said}.
    state is "verified", "none" (the registry gave none) or Refused is raised."""
    return _guarded("sigstore_check", artifact=artifact, sig=sig, provenance=provenance)


# ---------------------------------------------------------------------------
# A gene's files: unpacked in memory, never run, never written out
# ---------------------------------------------------------------------------


def unpack(data: bytes, name: str = "") -> dict[str, bytes]:
    """The files in a gene's artifact: a tar (any compression), a zip, or one file as it is.
    Links, devices and paths that climb out are refused, and so is too much."""
    return _guarded("unpack", data=data, name=name)


def file_list(files: dict[str, bytes]) -> list[dict]:
    return [{"path": p, "size": len(b), "sha256": sha256(b)} for p, b in sorted(files.items())]


def readable(body: bytes) -> str | None:
    """A file as text, if it is text: shown to the person as it is, never acted on."""
    if len(body) > MOST_READ or b"\x00" in body[:8192]:
        return None
    try:
        return body.decode("utf-8")
    except UnicodeDecodeError:
        return None


# ---------------------------------------------------------------------------
# A shared gene's glyph, redrawn from lines and shapes alone
# ---------------------------------------------------------------------------

_ICON_ATTRS = {"d", "cx", "cy", "r", "rx", "ry", "x", "y", "x1", "y1", "x2", "y2", "width", "height",
               "points", "fill", "stroke-width"}
_ICON_VALUE = re.compile(r"^[0-9a-zA-Z .,\-]{1,2000}$")


class _Icon(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag not in genes.ICON_TAGS:
            return
        kept = []
        for k, v in attrs:
            if k not in _ICON_ATTRS or v is None or not _ICON_VALUE.match(v):
                continue
            if k == "fill" and v not in ("none", "currentColor"):
                continue
            kept.append(f'{k}="{v}"')
        if kept:
            self.out.append(f"<{tag} {' '.join(kept)}/>")

    handle_startendtag = handle_starttag


def icon_of(icon) -> str:
    """A gene's own glyph, rebuilt tag by tag from the shapes and numbers in it; the shared
    gene glyph when nothing is left."""
    if not isinstance(icon, str) or not icon.strip() or len(icon) > 6000:
        return SHARED_ICON
    p = _Icon()
    with contextlib.suppress(Exception):
        p.feed(icon)
        p.close()
    drawn = "".join(p.out[:40])
    return drawn if drawn and not genes.icon_problems(drawn) else SHARED_ICON


# ---------------------------------------------------------------------------
# The registry an organisation points at
# ---------------------------------------------------------------------------


def _registry(org: str):
    return _model("GeneRegistry").objects.filter(org_id=org).first()


def base_of(url: str) -> str:
    url = url_ok(url)
    return url if url.endswith("/") else url + "/"


def point(who, url: str, public_key: str) -> dict:
    """Point the organisation at a registry and pin its key. Fetches both lists at once, so a
    wrong address or key is said now rather than an hour from now."""
    _admin(who)
    org = _org(who)
    base = base_of(url)
    key = load_key(public_key)
    pem = public_key.strip()
    Reg = _model("GeneRegistry")
    row = _registry(org)
    changed = row is None or row.url != base or row.key_id != key_id(key)
    fields = {"url": base, "public_key": pem, "key_id": key_id(key), "set_by": _name_of(who)[:200],
              "set_at": time.time()}
    if changed:
        # What was fetched from somewhere else, or under another key, is not kept.
        fields.update(index={}, blocklist={}, index_made_at="", blocklist_made_at="", fetched_at=0,
                      error="", error_at=0)
    Reg.objects.update_or_create(org_id=org, defaults=fields)
    _event(org, "", "registry", f"Pointed at {base}, key {key_id(key)}.", by=_name_of(who))
    return refresh(org)


def forget(who) -> dict:
    """Off again: no address, no key, nothing fetched. Genes already in the lab stay there."""
    _admin(who)
    org = _org(who)
    _model("GeneRegistry").objects.filter(org_id=org).delete()
    _event(org, "", "registry", "No registry any more: Rouh asks none.", by=_name_of(who))
    return {"ok": True}


def refresh(org: str) -> dict:
    """Fetch the blocklist and the index, check them, keep them, and act on them: a gene the
    blocklist names is switched off, a newer version is noted. What happened, for telling."""
    Reg = _model("GeneRegistry")
    row = _registry(org)
    if row is None or not row.url or not row.public_key:
        return {"off": True, "blocked": [], "updates": []}
    key = load_key(row.public_key)
    said: list[str] = []
    fields: dict = {"fetched_at": time.time()}
    lists = {}
    for name, kind, made_field in ((BLOCKLIST, BLOCKLIST_KIND, "blocklist_made_at"),
                                   (INDEX, INDEX_KIND, "index_made_at")):
        try:
            payload = verify(_fetch_list(urljoin(row.url, name)), key, kind)
            made = _text(payload.get("made_at"), 40)
            kept = getattr(row, made_field)
            if kept and made and (clock.epoch(made) or 0.0) < (clock.epoch(kept) or 0.0):
                raise Refused(f"it was made at {made}, before the one Rouh already has ({kept}), so "
                              "it may be an old copy sent again")
            lists[name] = payload
            fields[made_field] = made
        except Refused as exc:
            said.append(f"The registry's {'blocklist' if name == BLOCKLIST else 'index'} was not taken: {exc}.")
    if BLOCKLIST in lists:
        fields["blocklist"] = lists[BLOCKLIST]
    if INDEX in lists:
        fields["index"] = lists[INDEX]
    fields["error"] = " ".join(said)
    fields["error_at"] = time.time() if said else 0
    Reg.objects.filter(id=row.id).update(**fields)
    if said:
        log.warning("genes for %s: %s", org, " ".join(said))
    blocklist = lists.get(BLOCKLIST, row.blocklist)
    index = lists.get(INDEX, row.index)
    return {"off": False, "error": fields["error"], "blocked": _apply_blocks(org, blocklist),
            "updates": _note_updates(org, index)}


def _apply_blocks(org: str, blocklist: dict) -> list[dict]:
    """Every installed gene the blocklist names, switched off and marked; the newly blocked."""
    newly = []
    for g in _model("SharedGene").objects.filter(org_id=org):
        b = block_for(blocklist, g.gene, g.version)
        if b is None:
            if g.state == "blocked":
                # Lifted at the registry: it stays off until a person switches it on.
                g.state, g.blocked, g.updated_at = "lab", {}, time.time()
                g.save(update_fields=["state", "blocked", "updated_at"])
                _event(org, g.gene, "unblocked", "The registry's blocklist no longer names it. It stays "
                                                 "off until it is switched on.", version=g.version)
            continue
        if g.state == "blocked" and g.blocked.get("severity") == b["severity"]:
            # Said before; but a soft block a person switched back on is left as they chose.
            if b["severity"] == "hard" and switches.on(g.switch, org):
                switches.set_on(g.switch, False, by="blocklist", org_id=org)
            continue
        switches.set_on(g.switch, False, by="blocklist", org_id=org)
        g.state, g.blocked, g.updated_at = "blocked", b, time.time()
        g.save(update_fields=["state", "blocked", "updated_at"])
        _event(org, g.gene, "blocked", f"Switched off: the registry's blocklist names it ({b['severity']}): "
               f"{b['reason']}", version=g.version, detail=b)
        newly.append({"gene": g.gene, "name": g.contract and sections(g.contract, g.gene)["name"] or g.name,
                      "version": g.version, "installed_by": g.installed_by, **b})
    return newly


def _note_updates(org: str, index: dict) -> list[dict]:
    """A newer version of an installed gene, with what changed in its contract. Kept on the
    gene, never installed. The ones not noted before."""
    found = catalogue(index)
    newly = []
    for g in _model("SharedGene").objects.filter(org_id=org):
        versions = found.get(g.gene) or []
        newest = versions[0] if versions else None
        if newest is None or version_key(newest["version"]) <= version_key(g.version):
            if g.update:
                g.update = {}
                g.save(update_fields=["update"])
            continue
        if g.update.get("version") == newest["version"] and g.update.get("contract_sha256") == newest["contract_sha256"]:
            continue
        g.update = {"version": newest["version"], "contract_sha256": newest["contract_sha256"],
                    "changes": changes(g.contract, newest["contract"], (g.listing or {}).get("summary", ""),
                                       newest["summary"]),
                    "seen_at": time.time()}
        g.save(update_fields=["update"])
        _event(org, g.gene, "update", f"Version {newest['version']} is in the registry; it is not installed.",
               version=newest["version"])
        newly.append({"gene": g.gene, "name": sections(g.contract, g.gene)["name"], "from": g.version,
                      "to": newest["version"], "changes": g.update["changes"], "installed_by": g.installed_by})
    return newly


# ---------------------------------------------------------------------------
# What the lab holds, and the check after a gene is removed
# ---------------------------------------------------------------------------


def _held(org: str) -> dict:
    """What the lab has made in Rouh, by name: its genes, its genes' switches, and the shared
    links in the navigation."""
    lab = list(_model("SharedGene").objects.filter(org_id=org).values_list("gene", flat=True))
    made = list(_model("FeatureSwitch").objects.filter(org_id=org, name__startswith="gene_")
                .exclude(name=LAB_SWITCH).values_list("name", flat=True))
    return {"genes": sorted(lab), "switches": sorted(made),
            "links": sorted(m["id"] for m in shared_manifests(org, everything=True))}


def traces(org: str, gene: str) -> list[dict]:
    """Every place a gene could still be, each with whether it is gone."""
    sw, key = switch_for(gene), nav_key(gene)
    row = _model("SharedGene").objects.filter(org_id=org, gene=gene).first()
    shared = shared_manifests(org, everything=True)
    words = re.findall(r"[a-z0-9]+", gene.split("/")[-1])
    found = genes.find(words, extra=shared, limit=50) if words else []
    return [
        {"what": "Its place in the lab", "gone": row is None},
        {"what": "Its files", "gone": row is None or not bytes(row.artifact or b"")},
        {"what": f"Its switch, {sw}",
         "gone": not _model("FeatureSwitch").objects.filter(org_id=org, name=sw).exists()},
        {"what": "Its link in the navigation", "gone": all(m["id"] != key for m in shared)},
        {"what": "Its line in Search", "gone": all(m["id"] != key for m in found)},
    ]


def as_it_was(org: str, before: dict, now: dict, gene: str) -> list[str]:
    """What the lab holds now that it did not just before the gene came, or held then and does
    not now, apart from other genes installed or removed since; empty when it is as it was."""
    own = {gene, switch_for(gene), nav_key(gene)}
    out = []
    for part in ("genes", "switches", "links"):
        was, is_ = set(before.get(part) or []), set(now.get(part) or [])
        for item in sorted(is_ - was):
            if item in own or _belongs_to_another(org, item, gene, now, before):
                if item in own:
                    out.append(f"{part}: {item} is still there")
                continue
            out.append(f"{part}: {item} is there and was not before")
        for item in sorted(was - is_):
            if not _belongs_to_another(org, item, gene, now, before):
                out.append(f"{part}: {item} was there before and is gone")
    return out


def _belongs_to_another(org: str, item: str, gene: str, now: dict, before: dict) -> bool:
    others = (set(now.get("genes") or []) | set(before.get("genes") or [])) - {gene}
    others |= {g["gene"] for g in _model("GeneLabEvent").objects.filter(org_id=org, what="installed")
               .values("gene").distinct()} - {gene}
    return any(item in (o, switch_for(o), nav_key(o)) for o in others)


# ---------------------------------------------------------------------------
# What the people of the organisation do: install, switch, update, remove
# ---------------------------------------------------------------------------


def _listed(org: str, gene: str, version: str) -> tuple[dict, dict]:
    row = _registry(org)
    if row is None or not row.url:
        raise Refused("Rouh is not pointed at a gene registry. Set one in Anatomy, Rouh Land Account, Gene Pool, first.")
    if not GENE_ID.match(gene):
        raise Refused(f"{gene[:80]!r} is not a gene's id.")
    versions = catalogue(row.index).get(gene) or []
    e = next((v for v in versions if v["version"] == version), None)
    if e is None:
        raise Refused(f"{gene} {version} is not in the registry's signed index. Check again and read "
                      "its contract there.")
    return e, row.blocklist or {}


def _receive(e: dict) -> tuple[bytes, dict[str, bytes], dict]:
    """A version's files fetched and checked: their hash against the signed index, then their
    Sigstore signature where the registry gives one."""
    try:
        data = fetch(url_ok(e["url"]), MOST_ARTIFACT)
    except Refused as exc:
        raise Refused(f"Its files could not be fetched: {exc}. Nothing was installed.") from None
    except Exception as exc:
        raise Refused(f"Its files could not be fetched ({type(exc).__name__}). Nothing was installed.") from None
    if sha256(data) != e["sha256"]:
        raise Refused("Its files are not the ones the signed index names: their SHA-256 is "
                      f"{sha256(data)[:16]}..., not {e['sha256'][:16]}.... Nothing was installed.")
    try:
        sig = sigstore_check(data, e["sigstore"], e["provenance"])
    except Refused as exc:
        raise Refused(f"Not installed: {exc}.") from None
    try:
        files = unpack(data, urlsplit(e["url"]).path.rsplit("/", 1)[-1])
    except Refused as exc:
        raise Refused(f"Its files were not kept: {exc}. Nothing was installed.") from None
    return data, files, sig


def install(who, gene: str, version: str, seen: str) -> dict:
    """Install a gene in the lab, on an administrator's yes, switched off. `seen` is the hash
    of the contract their page drew, and it has to be the contract installed."""
    _admin(who)
    org = _org(who)
    if _model("SharedGene").objects.filter(org_id=org, gene=gene).exists():
        raise Refused(f"{gene} is already in the lab.")
    e, blocklist = _listed(org, gene, version)
    if seen != e["contract_sha256"]:
        raise Refused("Its contract is not the one you were shown: the registry changed it since. "
                      "Read it again before installing.")
    b = block_for(blocklist, gene, version)
    if b:
        raise Refused(f"The registry's blocklist names {gene} ({b['severity']}): {b['reason']}. Not installed.")
    data, files, sig = _receive(e)
    before = _held(org)
    now = time.time()
    sw = switch_for(gene)
    switches.set_on(sw, False, by=f"installed by {_name_of(who)}", org_id=org,
                    title=f"Shared gene {gene}, in the lab")
    listing = {k: e[k] for k in ("publisher_name", "verified_publisher", "official", "rating", "core_range",
                                 "published_at", "provenance", "page", "version_rating", "summary")}
    _model("SharedGene").objects.create(
        org_id=org, gene=gene, publisher=e["publisher"], name=gene.split("/")[1], version=version,
        kind=e["kind"], contract=e["contract"], contract_sha256=e["contract_sha256"], listing=listing,
        artifact_url=e["url"], artifact_sha256=e["sha256"], artifact=data, files=file_list(files),
        sigstore=sig, switch=sw, state="lab", before=before, installed_by=str(getattr(who, "user_id", "")),
        installed_by_name=_name_of(who)[:200], installed_at=now, updated_at=now)
    _event(org, gene, "installed", f"Installed {version} in the lab, switched off. {sig['said']}",
           by=_name_of(who), version=version, detail={"sha256": e["sha256"], "files": len(files)})
    return {"gene": gene, "said": f"{e['sections']['name']} {version} is in the lab, switched off. "
                                  "Switch it on when you want it."}


def set_switch(who, gene: str, on: bool) -> dict:
    _admin(who)
    org = _org(who)
    g = _model("SharedGene").objects.filter(org_id=org, gene=gene).first()
    if g is None:
        raise Refused(f"{gene} is not in the lab.")
    if on and g.state == "blocked" and g.blocked.get("severity") == "hard":
        raise Refused(f"The registry's blocklist names {gene} as harmful: {g.blocked.get('reason')}. "
                      "It cannot be switched on; remove it.")
    switches.set_on(g.switch, bool(on), by=_name_of(who) or "settings", org_id=org,
                    title=f"Shared gene {gene}, in the lab")
    name = sections(g.contract, gene)["name"]
    _event(org, gene, "switched_on" if on else "switched_off",
           f"Switched {'on' if on else 'off'}.", by=_name_of(who), version=g.version)
    if on:
        where = sections(g.contract, gene)
        return {"said": f"{name} is on: {where['where']}, marked Shared." +
                        (" The registry still marks it for quality." if g.state == "blocked" else "")}
    return {"said": f"{name} is off, and out of the navigation and Search."}


def update(who, gene: str, version: str, seen: str) -> dict:
    """Move an installed gene to a newer version, on a person's yes after they read what
    changed in its contract. Its switch stays as it was."""
    _admin(who)
    org = _org(who)
    g = _model("SharedGene").objects.filter(org_id=org, gene=gene).first()
    if g is None:
        raise Refused(f"{gene} is not in the lab.")
    e, blocklist = _listed(org, gene, version)
    if version_key(version) <= version_key(g.version):
        raise Refused(f"{version} is not newer than {g.version}, which is installed.")
    if seen != e["contract_sha256"]:
        raise Refused("Its new contract is not the one you were shown: the registry changed it since. "
                      "Read it again before updating.")
    b = block_for(blocklist, gene, version)
    if b:
        raise Refused(f"The registry's blocklist names {gene} {version} ({b['severity']}): {b['reason']}.")
    data, files, sig = _receive(e)
    was, said = g.version, changes(g.contract, e["contract"], (g.listing or {}).get("summary", ""), e["summary"])
    g.version, g.kind, g.contract, g.contract_sha256 = version, e["kind"], e["contract"], e["contract_sha256"]
    g.artifact_url, g.artifact_sha256, g.artifact, g.files, g.sigstore = (
        e["url"], e["sha256"], data, file_list(files), sig)
    g.listing = {**g.listing, "rating": e["rating"], "published_at": e["published_at"],
                 "provenance": e["provenance"], "version_rating": e["version_rating"], "summary": e["summary"]}
    g.update, g.updated_at = {}, time.time()
    g.save()
    _event(org, gene, "updated", f"Updated from {was} to {version}. {sig['said']}", by=_name_of(who),
           version=version, detail={"changes": said})
    return {"said": f"{e['sections']['name']} is at {version} now, switched "
                    f"{'on' if switches.on(g.switch, org) else 'off'} as it was."}


def remove(who, gene: str) -> dict:
    """Take a gene out: its row and files, its switch. Then look for anything left."""
    _admin(who)
    org = _org(who)
    g = _model("SharedGene").objects.filter(org_id=org, gene=gene).first()
    if g is None:
        raise Refused(f"{gene} is not in the lab.")
    before, version, name = g.before or {}, g.version, sections(g.contract, gene)["name"]
    _model("SharedGene").objects.filter(org_id=org, gene=gene).delete()
    forget_switch(org, g.switch)
    found = traces(org, gene)
    left = as_it_was(org, before, _held(org), gene)
    ok = all(t["gone"] for t in found) and not left
    said = (f"Removed {name}. Rouh is as it was before it came: nothing named for it is left."
            if ok else f"Removed {name}, and something is left: " +
            "; ".join([t["what"] for t in found if not t["gone"]] + left) + ".")
    _event(org, gene, "removed", said, by=_name_of(who), version=version,
           detail={"checks": found, "differences": left, "ok": ok})
    return {"said": said, "check": {"ok": ok, "checks": found, "differences": left}}


def forget_switch(org: str, name: str) -> None:
    """A gene's switch, gone: not off, gone, as it was before the gene came."""
    _model("FeatureSwitch").objects.filter(org_id=org, name=name).delete()
    with switches._lock:
        switches._seen.pop((org, name), None)


def set_lab(who, on: bool) -> dict:
    _admin(who)
    org = _org(who)
    switches.set_on(LAB_SWITCH, bool(on), by=_name_of(who) or "settings", org_id=org,
                    title="The gene lab: every shared gene, at once")
    _event(org, "", "lab_on" if on else "lab_off", f"The lab switched {'on' if on else 'off'}.",
           by=_name_of(who))
    return {"said": "The lab is on: each shared gene shows when its own switch is on." if on
            else "The lab is off: no shared gene shows anywhere, whatever its own switch says."}


# ---------------------------------------------------------------------------
# Shared genes as Rouh's own gene registry draws them
# ---------------------------------------------------------------------------


def shared_manifests(org: str | None, *, everything: bool = False) -> list[dict]:
    """The lab's genes as manifests the navigation and Search can draw (`rouh/genes`): each
    behind its own switch, a lab, marked shared, opening its page in Rouh Land Account, Gene Pool. With
    the lab switched off there are none. `everything` is every gene in the lab, for the check."""
    if not org:
        return []
    try:
        rows = list(_model("SharedGene").objects.filter(org_id=org).order_by("installed_at", "id"))
        if not everything and not switches.on(LAB_SWITCH, org):
            return []
    except Exception:
        log.exception("the lab's genes could not be read")
        return []
    out = []
    for i, g in enumerate(rows):
        s = sections(g.contract, g.gene)
        group = s["group"] or "machine"
        out.append({
            "id": nav_key(g.gene), "name": s["name"][:60] or g.name,
            "title": f"{s['name']}: {s['title'] or s['what'][:120] or 'a shared gene'}"[:200],
            "aliases": [a[:40] for a in s["aliases"][:12]], "group": group, "route": route_for(g.gene),
            "icon": icon_of((g.contract or {}).get("icon")), "attaches_to": [], "maturity": "lab",
            "switch": g.switch, "shared": True, "gene": g.gene,
            "publisher_name": (g.listing or {}).get("publisher_name") or g.publisher,
            "nav": {"place": "list" if s["place"] in ("list", "dedicated", "account") else "none",
                    "order": 1000 + i, "opens": "address"},
            "touches": {k: s[k] for k in ("permissions", "accounts", "tables", "jobs", "remove")},
        })
    return out


# ---------------------------------------------------------------------------
# The page
# ---------------------------------------------------------------------------


def _installed_view(g, org: str) -> dict:
    s = sections(g.contract, g.gene, (g.listing or {}).get("summary", ""))
    return {
        "gene": g.gene, "name": s["name"], "version": g.version, "kind": g.kind, "state": g.state,
        "on": switches.on(g.switch, org) and switches.on(LAB_SWITCH, org), "switch_on": switches.on(g.switch, org),
        "switch": g.switch, "blocked": g.blocked or None, "update": g.update or None,
        "sigstore": g.sigstore, "sha256": g.artifact_sha256, "files": g.files, "listing": g.listing,
        "contract": s, "contract_sha256": g.contract_sha256, "installed_by": g.installed_by_name,
        "installed_at": g.installed_at, "updated_at": g.updated_at, "route": route_for(g.gene),
    }


def public(who) -> dict:
    """Everything Rouh Land Account, Gene Pool draws, for this organisation."""
    org = _org(who)
    row = _registry(org)
    found = catalogue(row.index) if row else {}
    blocklist = row.blocklist if row else {}
    lab = {g.gene: g for g in _model("SharedGene").objects.filter(org_id=org)}
    available = []
    for gene, versions in sorted(found.items()):
        e = versions[0]
        b = block_for(blocklist, gene, e["version"])
        available.append({k: e[k] for k in ("gene", "publisher", "publisher_name", "verified_publisher",
                                             "official", "version", "kind", "core_range", "published_at",
                                             "rating", "version_rating", "page", "sha256", "contract_sha256",
                                             "sections", "provenance")}
                         | {"sigstore": bool(e["sigstore"]), "blocked": b, "installed": gene in lab,
                            "installed_version": lab[gene].version if gene in lab else "",
                            "versions": [v["version"] for v in versions]})
    history = [{"gene": h.gene, "version": h.version, "what": h.what, "said": h.said, "by": h.by, "at": h.at}
               for h in _model("GeneLabEvent").objects.filter(org_id=org).order_by("-at", "-id")[:40]]
    return {
        "admin": bool(getattr(who, "is_admin", False)),
        "registry": {
            "url": row.url if row else "", "key_id": row.key_id if row else "",
            "public_key": row.public_key if row else "", "set_by": row.set_by if row else "",
            "set_at": row.set_at if row else 0, "fetched_at": row.fetched_at if row else 0,
            "index_made_at": row.index_made_at if row else "",
            "blocklist_made_at": row.blocklist_made_at if row else "",
            "blocked_count": len((blocklist or {}).get("entries") or []),
            "error": row.error if row else "",
        },
        "lab_on": switches.on(LAB_SWITCH, org),
        "available": available,
        # What the blocklist names, so a gene it pulled from the index still says why.
        "blocked": blocked_genes(blocklist),
        "installed": [_installed_view(g, org) for g in sorted(lab.values(), key=lambda g: g.installed_at)],
        "history": history,
        "every_minutes": every_minutes(),
        # The section's own address, which every link inside it is under.
        "route": route_for("").rstrip("/"),
    }


def read_file(who, gene: str, path: str) -> dict:
    """One file of an installed gene, as text to read, or what it is when it is not text."""
    org = _org(who)
    g = _model("SharedGene").objects.filter(org_id=org, gene=gene).first()
    if g is None:
        raise Refused(f"{gene} is not in the lab.")
    files = unpack(bytes(g.artifact), urlsplit(g.artifact_url).path.rsplit("/", 1)[-1])
    if path not in files:
        raise Refused(f"{gene} has no file {path[:120]!r}.")
    text = readable(files[path])
    return {"gene": gene, "path": path, "size": len(files[path]), "text": text,
            "said": "" if text is not None else "Not text, or too long to show here."}


# ---------------------------------------------------------------------------
# The beat: the blocklist, and what is new in the index
# ---------------------------------------------------------------------------


def every_minutes() -> float:
    try:
        return max(0.05, float(os.environ.get("ROUH_GENES_EVERY_MINUTES") or EVERY_MINUTES))
    except ValueError:
        return EVERY_MINUTES


def _pointed() -> list[str]:
    return list(_model("GeneRegistry").objects.exclude(url="").values_list("org_id", flat=True))


async def tell(org: str, found: dict) -> None:
    """The person who installed a gene, told what the registry said about it: a block at
    once, and on the phone if it is left; an update on the screen."""
    from . import notices

    for b in found.get("blocked") or []:
        who = SimpleNamespace(user_id=b["installed_by"], org_id=org)
        hard = b["severity"] == "hard"
        await notices.notify(
            who=who, kind="gene", key=f"gene-block:{org}:{b['gene']}:{b['version']}:{b['severity']}:{b['at']}",
            title=f"Rouh switched off {b['name']}: the registry blocklisted it",
            body=(f"{b['gene']} {b['version']} is on the registry's blocklist "
                  f"({'harmful' if hard else 'for quality'}): {b['reason']}"
                  + (f"\nWhat to do: {b['what_to_do']}" if b['what_to_do'] else "")),
            link=route_for(b["gene"]), link_label="Open the gene",
            phone_text=f"Rouh switched off the gene {b['name']}: the registry blocklisted it. {b['reason']}")
    for u in found.get("updates") or []:
        who = SimpleNamespace(user_id=u["installed_by"], org_id=org)
        parts = ", ".join(c["label"].lower() for c in u["changes"]) or "nothing in its contract"
        await notices.notify(
            who=who, kind="gene", key=f"gene-update:{org}:{u['gene']}:{u['to']}",
            title=f"An update to {u['name']} is waiting: {u['to']}",
            body=f"From {u['from']} to {u['to']}. What changed in its contract: {parts}. "
                 "It is not installed until you say so.",
            link=route_for(u["gene"]), link_label="Read what changed")


class Watch:
    """Asks every pointed registry for its blocklist and index, on a beat."""

    def __init__(self) -> None:
        self.task: asyncio.Task | None = None

    def start(self) -> None:
        if self.task is None or self.task.done():
            self.task = asyncio.create_task(self._loop(), name="genelab")

    async def stop(self) -> None:
        if self.task is not None:
            self.task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self.task
            self.task = None

    async def _loop(self) -> None:
        await asyncio.sleep(min(30.0, every_minutes() * 60))
        while True:
            try:
                await self.once()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("the gene lab's look at its registries stumbled; continuing")
            await asyncio.sleep(every_minutes() * 60)

    async def once(self) -> None:
        for org in await asyncio.to_thread(_pointed):
            try:
                found = await asyncio.to_thread(refresh, org)
            except Exception:
                log.exception("the registry for %s could not be asked", org)
                continue
            await tell(org, found)


__all__ = ["Refused", "Watch", "catalogue", "changes", "contract_hash", "entry", "forget", "install",
           "point", "public", "read_file", "refresh", "remove", "sections", "set_lab", "set_switch",
           "shared_manifests", "update", "verify"]
