"""The Incubator: one list of ideas for Rouh's new genes and mutations, until they hatch.

Petar, 3 November 2026, on task 166's Gene Nursery, a Markdown file in his workspace: "I don't
think this task 166 is the right format. I think it needs to be a feature separately put in
navigation with its own page and database + tooling for LLM to manage." And: "list has to have
all kinds of filters. make it a table ... chat for that feature only", "lets put it in the
navigation. obviously this will be in evolution. maybe right under mutations?" He rejected the
name Gene Nursery; Incubator is where ideas are kept warm until they hatch into a gene or a
mutation, and clashes with nothing else in Evolution. What he does for himself is every Rouh's
default, so this is a feature of every Rouh, not a setup of his.

**What an idea is.** A row of `incubator_ideas` (`rouh/models/incubator.py`): its number, shown
as INC-<n> (the nightly run's own list already uses I-<nnn>, so this prefix cannot be read as one
of those); a title; whether it is a new gene or a mutation of a gene there is, naming that gene
when it is known; one main category and any tags; a status; where it came from; the full
original text **exactly as written**, never shortened or reworded, with the same text in its
parts for reading; links to where it lives (its task, step, chat, pages and files); and the
history of every change (`incubator_events`). Triage words go in `notes`; the original is never
edited.

**Statuses** are plain words (task 159 found invented names the first cause of Petar asking what
Rouh meant): New, Triaged, Go, In build, Built, Parked, Rejected, and Merged into another idea.

**One way of building.** Setting an idea to Go hands it to Gene therapy as a feedback, in its
own words, and the same converter every feedback goes through reads it, writes the feature
request and starts its run when the board builds by itself (`rouh/triage.py`). There is no
second pipeline. The idea remembers the feedback, then the request once there is one, and moves
to In build; when the request ships it is Built (`follow`).

**Whose.** Every row carries `org_id` and `user_id` and every query names both; an idea of
anybody else's is "not found".

**Its own chat.** Each person has one chat for the Incubator (`chat_id_for`), opened from the
page, in which the model is told that it is the Incubator's chat and what the list holds
(`prompt_block`), and acts on it with the incubator tools (`rouh/tools.py`).
"""
from __future__ import annotations

import logging
import re
import threading
import time
from typing import Any, Iterable

log = logging.getLogger("rouh.incubator")

#: What an idea's number is shown with. Task 94's nightly list numbers its own I-001 to I-179.
PREFIX = "INC"

STATUSES: tuple[tuple[str, str, str], ...] = (
    ("new", "New", "caught, not looked at yet"),
    ("triaged", "Triaged", "looked at: sized, researched or answered, not decided yet"),
    ("go", "Go", "decided to build: handed to Gene therapy, waiting for its feature request"),
    ("in_build", "In build", "its feature request is being built, or waits to be"),
    ("built", "Built", "it became a gene or a mutation, or Rouh already does it"),
    ("parked", "Parked", "not now; the notes say why"),
    ("rejected", "Rejected", "not to be built; the notes say why, so it is not proposed again"),
    ("merged", "Merged", "the same idea as another one, which holds both"),
)
STATUS_IDS = tuple(s for s, _, _ in STATUSES)
STATUS_NAMES = {s: n for s, n, _ in STATUSES}

#: The categories, short enough to read at a glance: the id, the name, and what it holds in one line.
CATEGORIES: tuple[tuple[str, str, str], ...] = (
    ("ux", "UX and UI", "what the person sees and touches, and how clear it is"),
    ("communication", "Communication", "mail, Slack, Telegram, voice, and how Rouh talks and writes"),
    ("memory", "Memory and knowledge", "Synapse, and what Rouh remembers, finds and connects"),
    ("autonomy", "Autonomy and agents", "jobs, runs, the heartbeat, and Rouh acting in the world by itself"),
    ("integrations", "Integrations", "other services, accounts and devices Rouh connects to"),
    ("security", "Security and privacy", "keys, permissions, approvals, and data that must not leak"),
    ("stability", "Stability and refactoring", "fewer breakages, cleaner code, safer changes"),
    ("speed", "Speed", "answers, pages and runs that come back sooner"),
    ("cost", "Cost and models", "which model answers, and what Rouh spends"),
    ("platform", "Platform and setup", "installing and onboarding, the Mac app, the Gene Pool, open source"),
)
CATEGORY_IDS = tuple(c for c, _, _ in CATEGORIES)
CATEGORY_NAMES = {c: n for c, n, _ in CATEGORIES}

KINDS: tuple[tuple[str, str], ...] = (("gene", "New gene"), ("mutation", "Mutation"), ("", "Not known yet"))
KIND_NAMES = dict(KINDS)

#: Where an idea came from.
SOURCES: tuple[tuple[str, str], ...] = (
    ("ideas_project", "Ideas project"),
    ("nightly", "Nightly feature run"),
    ("nursery", "Gene Nursery"),
    ("chat", "Chat"),
    ("person", "You, directly"),
)
SOURCE_IDS = tuple(s for s, _ in SOURCES)
SOURCE_NAMES = dict(SOURCES)

LINK_KINDS = ("task", "step", "chat", "page", "file", "idea", "request", "gene", "link")

MAX_TITLE = 300
#: Long enough for any page of notes; an idea is its words whole, never cut to fit a column.
MAX_TEXT = 2_000_000
#: How much of an idea the table's hover shows.
PREVIEW = 900
#: The person's own setting for the page: columns, their order and widths, saved views.
PREFS = "incubator_page"

_LOCK = threading.Lock()


class NotFound(LookupError):
    """There is no such idea, or it is somebody else's."""


class Refused(ValueError):
    """A sentence the person can read, for a change that cannot be made."""


def _models():
    from .models import IncubatorEvent, IncubatorIdea

    return IncubatorIdea, IncubatorEvent


def _whose(who) -> dict:
    return {"org_id": str(who.org_id), "user_id": str(who.user_id)}


def code(number) -> str:
    return f"{PREFIX}-{int(number)}"


_CODE = re.compile(r"^\s*(?:inc|in)?[\s-]*0*(\d{1,6})\s*$", re.I)


def number_of(ident) -> int | None:
    """INC-12, inc 12, 12 -> 12; anything else None."""
    if isinstance(ident, int):
        return ident
    got = _CODE.match(str(ident or ""))
    return int(got.group(1)) if got else None


def _rows(who):
    Idea, _ = _models()
    return Idea.objects.filter(**_whose(who))


def find(who, ident):
    """The person's idea by its INC number, its number, or its name in its source (I-028, N-019, 70-01)."""
    rows = _rows(who)
    n = number_of(ident)
    row = rows.filter(number=n).first() if n is not None else None
    if row is None and str(ident or "").strip():
        row = rows.filter(ref__iexact=str(ident).strip()).order_by("number").first()
    if row is None:
        raise NotFound(f"There is no idea {ident} in the Incubator.")
    return row


def _event(who, idea_id: int, what: str, *, by: str = "", before=None, after=None, note: str = "") -> None:
    _, Event = _models()
    Event.objects.create(**_whose(who), idea_id=int(idea_id), at=time.time(), by=str(by or "")[:200],
                         what=what, before=before or {}, after=after or {}, note=str(note or "")[:2000])


def _clean_links(links) -> list[dict]:
    out, seen = [], set()
    for link in links or []:
        if not isinstance(link, dict):
            continue
        kind = str(link.get("kind") or "link")
        kind = kind if kind in LINK_KINDS else "link"
        href = str(link.get("href") or "").strip()
        path = str(link.get("path") or "").strip()
        label = " ".join(str(link.get("label") or href or path).split())[:300]
        key = (kind, href or path or label)
        if not (href or path or label) or key in seen:
            continue
        seen.add(key)
        item = {"kind": kind, "label": label}
        if href:
            item["href"] = href
        if path:
            item["path"] = path
        out.append(item)
    return out


def _clean_tags(tags) -> list[str]:
    if isinstance(tags, str):
        tags = re.split(r"[,;]", tags)
    out = []
    for t in tags or []:
        t = " ".join(str(t).lower().split())[:40]
        if t and t not in out:
            out.append(t)
    return out[:12]


def _kind(kind) -> str:
    k = str(kind or "").strip().lower().replace(" ", "_")
    k = {"new_gene": "gene", "gene": "gene", "mutation": "mutation", "mutate": "mutation",
         "unknown": "", "not_known": "", "": ""}.get(k, None)
    if k is None:
        raise Refused("kind is gene (a new gene), mutation, or empty when it is not known yet.")
    return k


def _status(status) -> str:
    s = str(status or "").strip().lower().replace(" ", "_").replace("-", "_")
    s = {"merged_into": "merged", "inbuild": "in_build", "building": "in_build"}.get(s, s)
    if s not in STATUS_IDS:
        raise Refused("status is one of: " + ", ".join(STATUS_IDS) + ".")
    return s


def _category(category, *, empty_ok: bool = True) -> str:
    c = str(category or "").strip().lower()
    if not c and empty_ok:
        return ""
    for cid, name, _ in CATEGORIES:
        if c in (cid, name.lower()):
            return cid
    raise Refused("category is one of: " + ", ".join(CATEGORY_IDS) + ".")


# --- guessing a category, for an import or an idea given none --------------------------------------

#: Words that point to each category, in the order they are tried; the most hits wins, ties to the first.
_HINTS: dict[str, tuple[str, ...]] = {
    "security": ("security", "secret", "password", "permission", "privacy", "private", "leak", "approval",
                 "approve", "vpn", "hardened", "encrypt", "token", "passkey", "trust", "safe", "injection",
                 "guard", "mandate", "consent"),
    "memory": ("synapse", "memory", "remember", "knowledge", "recall", "wiki", "notes", "dream", "vocabulary",
               "embedding", "search", "find"),
    "communication": ("mail", "email", "inbox", "telegram", "slack", "voice", "speak", "message", "reply",
                      "writing", "write", "tone", "words", "communication", "whatsapp", "call"),
    "autonomy": ("job", "run", "heartbeat", "agent", "autonom", "nightly", "background", "always-on",
                 "buy", "book", "purchase", "avatar", "acts", "by itself", "unasked", "quest", "goal"),
    "integrations": ("google", "calendar", "drive", "apple", "health", "hue", "vacuum", "stripe", "github",
                     "linkedin", "youtube", "meet", "integration", "connect", "api", "dots",
                     "robot", "device", "home"),
    "cost": ("cost", "model", "token", "price", "spend", "budget", "cheap", "opus", "sonnet", "codex",
             "gpt", "llm"),
    "speed": ("speed", "fast", "slow", "latency", "benchmark", "quick", "wait", "time to"),
    "stability": ("refactor", "bug", "debug", "merge conflict", "conflict", "crash", "stable", "stability",
                  "test", "server", "deploy", "migration", "backup", "database", "fuse", "restart", "fix"),
    "platform": ("install", "mac", "gene pool", "open source", "open-source", "onboard", "setup", "set up",
                 "new customer", "rouh.land", "distribution", "marketplace", "logo", "brand", "show off",
                 "demo", "character", "legal"),
    "ux": ("page", "screen", "button", "table", "ui", "ux", "view", "canvas", "card", "layout", "design",
           "show", "x-ray", "explainer", "brief", "navigation", "3d"),
}


def guess_category(*texts: str) -> str:
    """The category whose words a title (counted three times) and its text hold most; "ux" when none."""
    title = (texts[0] if texts else "") or ""
    body = " ".join(t for t in texts[1:] if t)[:6000]
    words = (title.lower() + " ") * 3 + body.lower()
    best, score = "ux", 0
    for cat, hints in _HINTS.items():
        got = sum(words.count(h) for h in hints)
        if got > score:
            best, score = cat, got
    return best


# --- what the page and the model are told ----------------------------------------------------------


def _preview(text: str) -> str:
    text = re.sub(r"\n{3,}", "\n\n", str(text or "")).strip()
    return text if len(text) <= PREVIEW else text[:PREVIEW].rstrip() + " …"


def view(row, *, full: bool = False, codes: dict | None = None, back: dict | None = None) -> dict:
    """One idea as the page draws it. `codes` maps a row id to its INC code, for the merged-into link;
    `back` is how often it came back (`incubator_score.came_back`), for its score's breakdown."""
    from . import incubator_gist, incubator_score
    out = {
        "id": row.id, "number": row.number, "code": code(row.number), "title": row.title,
        "kind": row.kind, "kind_name": KIND_NAMES.get(row.kind, row.kind), "gene": row.gene,
        "category": row.category, "category_name": CATEGORY_NAMES.get(row.category, row.category or "None"),
        "tags": list(row.tags or []), "status": row.status, "status_name": STATUS_NAMES.get(row.status, row.status),
        "source": row.source, "source_name": SOURCE_NAMES.get(row.source, row.source),
        "sources": list(row.sources or [row.source]), "ref": row.ref, "source_status": row.source_status,
        "notes": row.notes, "request_id": row.request_id, "feedback_id": row.feedback_id,
        "built_as": row.built_as, "source_at": row.source_at, "created_at": row.created_at,
        "updated_at": row.updated_at, "length": len(row.original or ""),
        # The preview starts with the words themselves, not with the name of the file they came from.
        "links": list(row.links or []),
        "preview": _preview((row.sections or [{}])[0].get("text") if row.sections else row.original),
        "merged_into": None,
        # Its score, worked out from its parts, with the stars (`rouh/incubator_score.py`).
        **incubator_score.view_parts(row),
        "came_back": back if back is not None else {},
        # What Rouh wrote to get a reader up to speed, once (`rouh/incubator_gist.py`), and the ideas it
        # looks like, filled in by `listing` and `one` when they are asked for.
        "gist": incubator_gist.view(row),
        "alike": [],
    }
    if row.merged_into:
        out["merged_into"] = {"id": row.merged_into, "code": (codes or {}).get(row.merged_into, "")}
    if full:
        out["original"] = row.original
        out["sections"] = list(row.sections or [])
    return out


def _codes(who) -> dict:
    return dict((i, code(n)) for i, n in _rows(who).values_list("id", "number"))


def facts() -> dict:
    """The lists the page and the tools choose from, and the score's scale."""
    from . import incubator_score

    return {
        "prefix": PREFIX,
        "statuses": [{"id": s, "name": n, "line": l} for s, n, l in STATUSES],
        "categories": [{"id": c, "name": n, "line": l} for c, n, l in CATEGORIES],
        "kinds": [{"id": k, "name": n} for k, n in KINDS],
        "sources": [{"id": s, "name": n} for s, n in SOURCES],
        "score": incubator_score.facts(),
    }


def listing(who, *, q: str = "", status=None, category=None, kind=None, source=None, tag: str = "",
            since: float | None = None, until: float | None = None, sort: str = "number",
            limit: int = 0, merged: bool = True, alike: bool = False) -> list[dict]:
    """The person's ideas, filtered. Each filter may be one value or a list of them. With `alike`, each
    idea says the ideas it looks like and has not been joined to (`incubator_gist.lookalikes`)."""
    rows = _rows(who)

    def many(v):
        return [v] if isinstance(v, str) else list(v or [])

    if status:
        rows = rows.filter(status__in=[_status(s) for s in many(status)])
    elif not merged:
        rows = rows.exclude(status="merged")
    if category:
        rows = rows.filter(category__in=[_category(c) for c in many(category)])
    if kind is not None and kind != []:
        rows = rows.filter(kind__in=[_kind(k) for k in many(kind)])
    if source:
        rows = rows.filter(source__in=[str(s) for s in many(source)])
    if since:
        rows = rows.filter(created_at__gte=float(since))
    if until:
        rows = rows.filter(created_at__lte=float(until))
    if q:
        from django.db.models import Q

        for word in str(q).split()[:8]:
            rows = rows.filter(Q(title__icontains=word) | Q(original__icontains=word) | Q(ref__iexact=word)
                               | Q(notes__icontains=word) | Q(gene__icontains=word))
    from . import incubator_score

    sort = str(sort or "number").strip().lower()
    by_score = sort.lstrip("-") in SCORE_SORTS
    order = {"number": "number", "newest": "-created_at", "updated": "-updated_at", "title": "title",
             "status": "status", "category": "category"}.get(sort, "number")
    rows = rows.order_by(order, "number")
    if limit and not by_score:
        rows = rows[:int(limit)]
    found = list(rows)
    if tag:
        t = str(tag).lower()
        found = [r for r in found if t in (r.tags or [])]
    codes = _codes(who) if any(r.merged_into for r in found) else {}
    back = incubator_score.came_back(who, found)
    out = [view(r, codes=codes, back=back.get(r.id)) for r in found]
    if alike:
        _alike_into(who, out)
    if by_score:
        # Highest first; "-impact" is lowest first. An idea not scored yet goes last either way.
        key, low = sort.lstrip("-"), sort.startswith("-")
        out.sort(key=lambda v: (score_key(v, key) is None, (score_key(v, key) or 0) * (1 if low else -1), v["number"]))
        if limit:
            out = out[:int(limit)]
    return out


#: What a list can be sorted by, beside number, newest, updated, title, status and category: the score
#: and each of its parts, highest first (a leading "-" turns it round).
SCORE_SORTS = ("score", "impact", "stars", "confidence", "frequency", "pain", "clarity", "risk")


def score_key(v: dict, key: str):
    if key == "score":
        return v.get("score")
    if key == "stars":
        return v.get("stars")
    return ((v.get("parts") or {}).get(key) or {}).get("v")


def _alike_into(who, ideas: list[dict]) -> None:
    """Each idea's lookalikes, by number, with what the page needs to name them."""
    from . import incubator_gist

    rows = list(_rows(who))
    near = incubator_gist.lookalikes(who, rows, apart=prefs(who).get("apart") or ())
    by_number = {r.number: r for r in rows}
    for v in ideas:
        v["alike"] = [{"number": h["number"], "code": code(h["number"]), "why": h["why"],
                       "title": by_number[h["number"]].title, "status": by_number[h["number"]].status}
                      for h in near.get(v["id"], []) if h["number"] in by_number]


def counts(who) -> dict:
    from django.db.models import Count

    rows = _rows(who)
    out = {"all": rows.count()}
    for field in ("status", "category", "kind", "source"):
        out[field] = {str(k or ""): n for k, n in rows.values_list(field).annotate(n=Count("id"))}
    return out


def history(who, idea_id: int) -> list[dict]:
    _, Event = _models()
    return [{"at": e.at, "by": e.by, "what": e.what, "before": e.before, "after": e.after, "note": e.note}
            for e in Event.objects.filter(**_whose(who), idea_id=int(idea_id)).order_by("at", "id")]


def one(who, ident) -> dict:
    """One idea whole: its text, its sections, its history, and the ideas merged into it."""
    row = find(who, ident)
    from . import incubator_score

    codes = _codes(who)
    out = view(row, full=True, codes=codes, back=incubator_score.came_back(who, [row]).get(row.id))
    out["history"] = history(who, row.id)
    out["merged_here"] = [{"id": r.id, "code": code(r.number), "title": r.title, "source_name":
                           SOURCE_NAMES.get(r.source, r.source), "ref": r.ref}
                          for r in _rows(who).filter(merged_into=row.id).order_by("number")]
    _alike_into(who, [out])
    # What the person said about it, newest first, kept with the idea (`feedback`), and its own chat.
    out["feedback"] = [h for h in reversed(out["history"]) if h["what"] == "feedback"]
    out["chat"] = chat_id_for_idea(who, row.number)
    return out


# --- changing the list -----------------------------------------------------------------------------


def _next_number(who) -> int:
    from django.db.models import Max

    got = _rows(who).aggregate(m=Max("number"))["m"]
    return int(got or 0) + 1


def add(who, *, title: str, text: str = "", kind: str = "", gene: str = "", category: str = "",
        tags=(), source: str = "person", ref: str = "", source_status: str = "", source_key: str = "",
        sections=None, links=(), status: str = "new", source_at: float | None = None, notes: str = "",
        by: str = "you", what: str = "added") -> dict:
    """A new idea, its words kept exactly as given. Returns it as `view` draws it."""
    Idea, _ = _models()
    title = " ".join(str(title or "").split())[:MAX_TITLE]
    if not title:
        raise Refused("An idea needs a title.")
    text = str(text or "")
    if len(text) > MAX_TEXT:
        raise Refused(f"That text is {len(text):,} characters; the most one idea keeps is {MAX_TEXT:,}.")
    source = source if source in SOURCE_IDS else "person"
    cat = _category(category) or guess_category(title, text)
    now = time.time()
    with _LOCK:
        row = Idea.objects.create(
            **_whose(who), number=_next_number(who), title=title, kind=_kind(kind),
            gene=str(gene or "")[:300], category=cat, tags=_clean_tags(tags), status=_status(status),
            source=source, sources=[source], ref=str(ref or "")[:80], source_status=str(source_status or "")[:300],
            source_key=str(source_key or "")[:300], original=text,
            sections=list(sections) if sections is not None else ([{"title": "The idea", "text": text}] if text else []),
            links=_clean_links(links), source_at=source_at, notes=str(notes or "")[:20000],
            created_at=now, updated_at=now)
    _event(who, row.id, what, by=by, after={"status": row.status, "category": row.category})
    # Scored a moment later, in the background, with whatever else came in at the same time.
    from . import incubator_score

    incubator_score.queue(who, row.id)
    return view(row)


EDITABLE = ("title", "kind", "gene", "category", "tags", "notes")


def edit(who, ident, *, by: str = "you", **fields) -> dict:
    """Change an idea's title, kind, gene, category, tags or notes. Its original words never change."""
    row = find(who, ident)
    before, after = {}, {}
    for name, value in fields.items():
        if value is None or name not in EDITABLE:
            continue
        if name == "title":
            value = " ".join(str(value).split())[:MAX_TITLE]
            if not value:
                raise Refused("An idea needs a title.")
        elif name == "kind":
            value = _kind(value)
        elif name == "category":
            value = _category(value, empty_ok=False)
        elif name == "tags":
            value = _clean_tags(value)
        else:
            value = str(value)[:20000]
        if getattr(row, name) != value:
            before[name], after[name] = getattr(row, name), value
            setattr(row, name, value)
    if not after:
        return view(row)
    row.updated_at = time.time()
    row.save()
    _event(who, row.id, "category" if list(after) == ["category"] else "edited", by=by, before=before, after=after)
    return view(row)


def set_status(who, ident, status: str, *, by: str = "you", note: str = "", into=None) -> dict:
    """Move an idea to a status. Go is `go` (it hands the idea to Gene therapy), and Merged is `merge`."""
    s = _status(status)
    if s == "go":
        raise Refused("Go hands the idea to Gene therapy to be built: use go.")
    if s == "merged":
        if into is None:
            raise Refused("Merged needs the idea it is merged into.")
        return merge(who, ident, into, by=by)
    row = find(who, ident)
    if row.status == s:
        return view(row)
    was = row.status
    row.status = s
    if was == "merged":
        row.merged_into = None
    if note:
        row.notes = (row.notes + "\n\n" if row.notes else "") + str(note)[:4000]
    row.updated_at = time.time()
    row.save()
    _event(who, row.id, "status", by=by, before={"status": was}, after={"status": s}, note=note)
    return view(row)


def merge(who, ident, into, *, by: str = "you") -> dict:
    """The idea `ident` is the same as `into`: it is Merged into it, and `into` gains its sources and links.
    Nothing of either is deleted; the merged one keeps its own words and opens from the one it is in."""
    row = find(who, ident)
    target = find(who, into)
    if row.id == target.id:
        raise Refused("An idea cannot be merged into itself.")
    if target.status == "merged":
        raise Refused(f"{code(target.number)} is itself merged into another idea: merge into that one.")
    was = row.status
    now = time.time()
    row.status, row.merged_into, row.updated_at = "merged", target.id, now
    row.save()
    # The ideas already merged into this one go with it, so nothing points at a merged idea.
    _rows(who).filter(merged_into=row.id).update(merged_into=target.id, updated_at=now)
    target.sources = list(dict.fromkeys([*(target.sources or [target.source]), *(row.sources or [row.source])]))
    # Its own links come with it; the idea itself is listed under "Merged into this one" (`one`).
    target.links = _clean_links([*(target.links or []), *(row.links or [])])
    target.updated_at = now
    target.save()
    _event(who, row.id, "merged", by=by, before={"status": was}, after={"status": "merged", "into": code(target.number)})
    _event(who, target.id, "merged", by=by, after={"from": code(row.number)},
           note=f"{code(row.number)} ({row.title}) was merged into this idea.")
    # The one it is in came back once more, which is demand: scored again, hand-set parts kept.
    from . import incubator_score

    incubator_score.queue(who, target.id)
    return view(row, codes={target.id: code(target.number)})


def feedback(who, ident, text: str, *, by: str = "you") -> dict:
    """The person's feedback on an idea: kept in its history, and added to its notes with the day, so
    Gene therapy, the scorer and the chats read it with the idea. Its original words never change."""
    row = find(who, ident)
    text = str(text or "").strip()
    if not text:
        raise Refused("Write the feedback first.")
    text = text[:4000]
    day = time.strftime("%d %b %Y", time.localtime()).lstrip("0")
    row.notes = (row.notes + "\n\n" if row.notes else "") + f"Feedback, {day}: {text}"
    row.updated_at = time.time()
    row.save(update_fields=["notes", "updated_at"])
    _event(who, row.id, "feedback", by=by, note=text)
    return view(row)


def link(who, ident, *, kind: str = "link", label: str = "", href: str = "", path: str = "",
         by: str = "you") -> dict:
    """Add a link to an idea: a task, a step, a chat, a page, a file, another idea, a request or a gene."""
    row = find(who, ident)
    if kind == "gene" and (label or href):
        row.built_as = row.built_as or (label or href)
    new = _clean_links([*(row.links or []), {"kind": kind, "label": label, "href": href, "path": path}])
    if len(new) == len(row.links or []):
        return view(row)
    row.links, row.updated_at = new, time.time()
    row.save()
    _event(who, row.id, "linked", by=by, after=new[-1])
    return view(row)


def bulk(who, idents: Iterable, *, status: str = "", category: str = "", by: str = "you") -> dict:
    """The same change to many ideas at once. Go goes through `go`, one by one, never from here."""
    done, failed = [], []
    for ident in list(idents)[:1000]:
        try:
            if status:
                set_status(who, ident, status, by=by)
            if category:
                edit(who, ident, category=category, by=by)
            done.append(str(ident))
        except (NotFound, Refused) as exc:
            failed.append({"id": str(ident), "why": str(exc)})
    return {"done": done, "failed": failed}


# --- Go: one way of building, through Gene therapy -------------------------------------------------


def brief_of(row) -> str:
    """What Gene therapy is given: the idea's own words, whole, under where it came from."""
    head = [f"From the Incubator, {code(row.number)}: {row.title}",
            f"Kind: {KIND_NAMES.get(row.kind, row.kind)}" + (f", of the gene {row.gene}" if row.gene else ""),
            f"Category: {CATEGORY_NAMES.get(row.category, row.category)}",
            f"Source: {SOURCE_NAMES.get(row.source, row.source)}" + (f" ({row.ref})" if row.ref else ""),
            f"The idea whole: /evolution/incubator/{code(row.number)}"]
    if row.notes:
        head += ["", "Notes:", row.notes]
    from .gene_therapy import MAX_BODY

    body = "\n".join(head) + "\n\nThe idea, as it was written:\n\n" + (row.original or row.title)
    if len(body) > MAX_BODY:
        tail = "\n\n[The rest is in the Incubator, at the address above.]"
        body = body[:MAX_BODY - len(tail)] + tail
    return body


async def go(who, ident, *, by: str = "you", author: str = "") -> dict:
    """Hand an idea to Gene therapy to be built: a feedback in its own words, read by the converter
    every feedback goes through, which writes the feature request and starts its run when the board
    builds by itself. The idea is Go now, and In build once its request is there (`follow`)."""
    import asyncio

    from . import runtime

    row = await asyncio.to_thread(find, who, ident)
    if row.status in ("go", "in_build", "built"):
        return {"ok": False, "idea": view(row),
                "said": f"{code(row.number)} is {STATUS_NAMES[row.status]} already; it was not handed on again."}
    if row.status == "merged":
        raise Refused(f"{code(row.number)} is merged into another idea: set that one to Go.")
    store = getattr(runtime, "gene_therapy", None)
    if store is None:
        raise Refused("Gene therapy is not set up here, so nothing can be built from the Incubator.")
    fb = await asyncio.to_thread(lambda: store.add_feedback(
        org_id=str(who.org_id), user_id=str(who.user_id), author=author or by,
        body=brief_of(row), page=f"/evolution/incubator/{code(row.number)}"))
    converter = getattr(runtime, "converter", None)
    taken = converter is not None and converter.enabled
    if taken:
        converter.take_later(str(who.org_id), fb)

    def mark():
        was = row.status
        row.status, row.feedback_id, row.updated_at = "go", fb.id, time.time()
        row.save()
        _event(who, row.id, "go", by=by, before={"status": was}, after={"status": "go", "feedback": fb.id},
               note="Handed to Gene therapy as a feedback, to be read into a feature request and built.")
        return view(row)

    idea = await asyncio.to_thread(mark)
    said = (f"{code(row.number)} is Go: it is in Gene therapy as feedback {fb.id}, which is being read into a "
            "feature request now; it moves to In build once the request is there.") if taken else (
            f"{code(row.number)} is Go: it is in Gene therapy as feedback {fb.id}. Gene therapy reads "
            "feedback by itself on its next sweep, and the idea moves to In build once its request is there.")
    try:
        await runtime.announce_gene_therapy()
    except Exception:  # noqa: BLE001 - the board catches up on its next read
        log.debug("the board could not be told about %s", fb.id, exc_info=True)
    return {"ok": True, "idea": idea, "feedback": fb.id, "said": said}


def follow(who) -> int:
    """Ideas handed to Gene therapy, moved on as their request is: In build once there is one, Built once
    it shipped, Parked if it was declined. How many moved. Never raises."""
    try:
        from . import runtime

        store = getattr(runtime, "gene_therapy", None)
        if store is None:
            return 0
        moved = 0
        for row in _rows(who).filter(status__in=("go", "in_build")).exclude(feedback_id=""):
            req = None
            if not row.request_id:
                got = store.list_requests(str(who.org_id), from_feedback=row.feedback_id, limit=1)
                req = got[0] if got else None
                if req is None:
                    continue
                row.request_id = req.id
                row.links = _clean_links([*(row.links or []), {
                    "kind": "request", "label": f"Feature request {req.id}: {req.title}", "href": "/gene-therapy"}])
            else:
                req = store.get_request(str(who.org_id), row.request_id)
                if req is None:
                    continue
            was = row.status
            now = {"shipped": "built", "declined": "parked"}.get(req.status, "in_build")
            if now == was and row.request_id == req.id and was != "go":
                continue
            row.status, row.updated_at = now, time.time()
            if now == "built":
                row.built_as = row.built_as or f"Feature request {req.id}: {req.title}" + (
                    f" (run {req.run_id})" if req.run_id else "")
            row.save()
            moved += 1
            _event(who, row.id, "request" if now == "in_build" else now, by="Gene therapy",
                   before={"status": was}, after={"status": now, "request": req.id, "request_status": req.status})
        return moved
    except Exception:  # noqa: BLE001 - the page still draws; the next read tries again
        log.exception("the Incubator could not follow Gene therapy")
        return 0


def follow_everyone() -> int:
    """`follow` for every person with an idea handed on: the beat behind the page."""
    from .tenancy import Tenancy

    Idea, _ = _models()
    moved = 0
    whose = set(Idea.objects.filter(status__in=("go", "in_build")).exclude(feedback_id="")
                .values_list("org_id", "user_id"))
    for org_id, user_id in whose:
        who = Tenancy().identity_of(user_id)
        if who is not None and str(who.org_id) == org_id:
            moved += follow(who)
    return moved


# --- the person's own settings for the page ---------------------------------------------------------


def prefs(who) -> dict:
    import json

    from .models import UserSetting

    row = UserSetting.objects.filter(user_id=str(who.user_id), org_id=str(who.org_id), name=PREFS).first()
    try:
        got = json.loads(row.value) if row is not None else {}
    except ValueError:
        got = {}
    return got if isinstance(got, dict) else {}


def put_prefs(who, value: dict) -> dict:
    import json

    from .models import UserSetting

    if not isinstance(value, dict):
        raise Refused("The page's settings are an object.")
    # The columns, their widths, the sort, the saved views, and the filters as they were left: which
    # labels are chosen and which are hidden by their eye, the dates and the search. Kept whole, never
    # cut short, since a cut one would not read back at all.
    text = json.dumps(value)
    if len(text) > 200_000:
        raise Refused("The page's settings are too big to keep.")
    UserSetting.objects.update_or_create(user_id=str(who.user_id), name=PREFS,
                                         defaults={"org_id": str(who.org_id), "value": text,
                                                   "updated_at": time.time()})
    return value


# --- its own chat ------------------------------------------------------------------------------------

CHAT_TITLE = "\N{EGG} Incubator"


def chat_id_for(who) -> str:
    return f"incubator-{who.user_id}"


def ensure_chat(who) -> str:
    from . import conversations

    cid = chat_id_for(who)
    conversations.ensure_chat(cid, title=CHAT_TITLE)
    return cid


#: One idea's own chat is the Incubator's chat id with this and the idea's number after it.
IDEA_CHAT = "--inc-"


def chat_id_for_idea(who, number) -> str:
    return f"{chat_id_for(who)}{IDEA_CHAT}{int(number)}"


def ensure_idea_chat(who, ident) -> str:
    """One idea's own chat, kept with it by its number, made if it is not there yet."""
    from . import conversations

    row = find(who, ident)
    cid = chat_id_for_idea(who, row.number)
    conversations.ensure_chat(cid, title=f"{CHAT_TITLE} {code(row.number)} {row.title}"[:120])
    return cid


def prompt_block(chat_id: str) -> str:
    """In the Incubator's own chat: that it is, and what the list holds now. "" in any other chat."""
    if not str(chat_id or "").startswith("incubator-"):
        return ""
    from .tenancy import Tenancy

    rest = str(chat_id)[len("incubator-"):]
    number = None
    if IDEA_CHAT in rest:
        rest, _, tail = rest.partition(IDEA_CHAT)
        number = int(tail) if tail.isdigit() else None
    who = Tenancy().identity_of(rest)
    if who is None:
        return ""
    about = ""
    if number is not None:
        try:
            v = one(who, number)
        except NotFound:
            v = None
        if v is not None:
            g = v.get("gist") or {}
            summary = " ".join(f"{name}: {g[k]}" for k, name in (("line", "In a line"), ("problem", "Problem"),
                               ("helps", "Who it helps"), ("in_use", "In use"), ("vision", "Vision")) if g.get(k))
            about = (f" This chat is about one idea, {v['code']}, kept with it: the person opened it from that idea's "
                     "page to talk it through, give feedback or decide it. Say what you think plainly, ask what is "
                     "unclear, and when the person gives feedback worth keeping, add it at the end of the idea's notes with "
                     "incubator_edit, keeping every note already there word for word. " + (summary + " " if summary else "") + "The idea now:\n"
                     + detail_for_model(v, most=8000))
    c = counts(who)
    by_status = ", ".join(f"{STATUS_NAMES[s]} {c['status'].get(s, 0)}" for s in STATUS_IDS if c["status"].get(s))
    return ("This chat is the Incubator's own chat, beside its page in Evolution: the one list of ideas for "
            "Rouh's new genes and mutations. What the person says here is about that list. Read and change it "
            "with the incubator tools (incubator_list, incubator_read, incubator_add, incubator_edit, "
            "incubator_status, incubator_merge, incubator_link). Ideas are numbered "
            f"{PREFIX}-<n>; say the number. Setting an idea to go with incubator_status hands it to Gene therapy "
            "to be built, so do it only when the person asks for it. Every idea has a score, worked out from its "
            "parts: Score = Impact² × Confidence × Frequency × Pain × Stars × Clarity ÷ Risk, with Impact 1-5 "
            "(squared; raised when it unblocks other ideas), Confidence 50-100%, Frequency 1-4 (daily 4, weekly 3, "
            "now and then 2, once 1, raised by demand: how often the idea came back), Pain ×2 broken today, ×1.5 "
            "annoying, ×1 nice to have, Stars 1-3 (×1, ×1.5, ×2; Rouh suggests them, the person's own win), "
            "Clarity ×0.9-1 and Risk ÷1-1.5, and no part for effort. The list sorts highest first. Read a score "
            "with incubator_read, and when the person gives a part or stars, set it with incubator_score; a part "
            "or stars set by hand are never changed by a re-score. "
            f"The list now: {c['all']} ideas ({by_status or 'none yet'})." + about)


# --- the words the model reads ------------------------------------------------------------------------


def line_for_model(v: dict) -> str:
    bits = [f"{v['code']} “{v['title']}”", v["status_name"], v["category_name"]]
    if v.get("kind"):
        bits.append(v["kind_name"] + (f" of {v['gene']}" if v.get("gene") else ""))
    bits.append(v["source_name"] + (f" {v['ref']}" if v.get("ref") else ""))
    if v.get("merged_into"):
        bits.append(f"merged into {v['merged_into'].get('code')}")
    if v.get("score") is not None:
        p = v.get("parts") or {}
        g = {k: (p.get(k) or {}).get("v") for k in ("impact", "confidence", "frequency", "pain", "clarity", "risk")}
        bits.append(f"score {round(v['score'])} (impact {g['impact']}, confidence {round(float(g['confidence']) * 100)}%, "
                    f"frequency {g['frequency']}, pain {g['pain']:g}, stars {v.get('stars')}"
                    + (" yours" if v.get("stars_mine") else "") + f", clarity {g['clarity']:g}, risk {g['risk']:g})")
    else:
        bits.append("not scored yet")
    return " · ".join(bits)


def detail_for_model(v: dict, *, most: int = 30_000) -> str:
    lines = [line_for_model(v)]
    g = v.get("gist") or {}
    if g.get("line"):
        lines.append(f"In a line (Rouh's summary): {g['line']}")
    if v.get("tags"):
        lines.append("Tags: " + ", ".join(v["tags"]))
    if v.get("notes"):
        lines.append("Notes: " + v["notes"])
    if v.get("request_id"):
        lines.append(f"Feature request: {v['request_id']}")
    if v.get("built_as"):
        lines.append(f"Became: {v['built_as']}")
    from . import incubator_score

    lines.append(incubator_score.explain(v))
    for link in v.get("links") or []:
        lines.append(f"Link ({link['kind']}): {link['label']} {link.get('href') or link.get('path') or ''}".rstrip())
    for m in v.get("merged_here") or []:
        lines.append(f"Merged into it: {m['code']} “{m['title']}” ({m['source_name']} {m['ref']})".rstrip())
    text = v.get("original") or ""
    if len(text) > most:
        text = text[:most] + f"\n[{len(v['original']) - most:,} more characters: read it on the page]"
    lines += ["", "The original words:", text]
    return "\n".join(lines)


__all__ = ["CATEGORIES", "PREFIX", "STATUSES", "SOURCES", "NotFound", "Refused", "add", "bulk", "counts",
           "edit", "feedback", "find", "follow", "go", "link", "listing", "merge", "one", "set_status"]
