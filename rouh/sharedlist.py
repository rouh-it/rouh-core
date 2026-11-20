"""One list on a workspace page, shared by everybody who may change the page.

Built 20 November 2026 for task 149's Our shortlist (step 149-04). Petar: "my
brother sees his words, I see mine. this needs to share a common db". The
page's settings (`pagestate.py`) are one person's, and a guest the page is
shared with had none at all, so each of them kept a list of their own, and the
guest's was gone when his page reloaded.

**Which pages.** Only a page that asks in its head, naming its lists:
``<meta name="rouh-shared-list" content="shortlist">`` (several names with
commas). Any other page, and any other name, is refused.

**Who.** The owner's organisation, signed in, for any page they may open
(`askai.resolve`), at ``/api/page-list`` (``askRelay`` in cards.js, the page's
``/api/list``). A person the page or its task is shared with, at
``/shared/<token>/list`` (`web/guests.py`, ``reader.js``): they may read it,
and change it only when the share lets them change the page. A link opened by
anybody (``/p/``) has no list. The list is kept under the page owner's
organisation, never the guest's, so it is one list for all of them.

**Changes, one entry at a time.** Nobody hands the whole list back. ``add``
puts one entry on (or, when it is there already, adds what it brings to it:
new spellings, a meaning it lacked), ``remove`` takes one off, ``edit`` changes
named fields of one. Each runs in a transaction holding the row
(``select_for_update``), so two people adding at the same moment both land;
``version`` goes up by one with each change, and a page asks with ``since`` to
hear whether anything changed. An entry taken off is kept in ``removed`` with
who took it off and when, and every change is in ``log``.

**What was found out** (``answers``) is written only by Rouh's own checks,
never by a page: a domain's .ai and .com (`name_checks.domains`), recorded by
`record_domains` for each list of the page.

**Where it started.** The first time a list is opened it is made from every
person's own copy on the page (`PageState` rows of the organisation, under the
same name), merged by the same rule as ``add``, earliest saved first, and their
kept answers. Those rows are left exactly as they were.

**Beside the page.** Each change is also written beside the page as
``shared-lists.json``, so a job can read the list (`pagestate.beside` is the
same idea for one person's settings).
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger("rouh.sharedlist")

#: The most entries one list may hold, one entry's size, and the whole row's.
ITEMS_MOST = 500
ITEM_BYTES = 4 * 1024
ROW_BYTES = 512 * 1024
#: How much history is kept: entries taken off, and changes.
REMOVED_MOST = 1000
LOG_MOST = 2000
#: The file written beside the page.
BESIDE = "shared-lists.json"
#: Fields of an entry that are Rouh's, never the page's.
OURS = ("id", "by", "at", "seeded_from", "merged")
_ASKS = re.compile(r"""<meta\s[^>]*name\s*=\s*["']rouh-shared-list["'][^>]*>""", re.I)
_CONTENT = re.compile(r"""content\s*=\s*["']([^"']*)["']""", re.I)
HEAD = 16 * 1024
KEY = re.compile(r"^[a-z][a-z0-9_-]{0,39}$")


class Refused(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def lists_of(page: Path) -> list[str]:
    """The names of the lists the page asks to share, from its head."""
    try:
        with open(page, "rb") as fh:
            head = fh.read(HEAD).decode("utf-8", "replace")
    except OSError:
        return []
    found = _ASKS.search(head)
    if not found:
        return []
    content = _CONTENT.search(found.group(0))
    names = [n.strip() for n in (content.group(1) if content else "").split(",")]
    return [n for n in dict.fromkeys(names) if KEY.fullmatch(n)]


def ident(raw) -> str:
    """Which entry it is: its name as written, without case, spacing or a different Unicode form."""
    text = unicodedata.normalize("NFC", str(raw or ""))
    return " ".join(text.split()).casefold()[:200]


def _size(value) -> int:
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode())


def _clean(item) -> dict:
    if not isinstance(item, dict):
        raise Refused("An entry is an object.")
    out = {k: v for k, v in item.items() if isinstance(k, str) and k not in OURS and len(k) <= 40}
    name = out.get("w")
    if not isinstance(name, str) or not ident(name):
        raise Refused("An entry needs its name, as w.")
    if _size(out) > ITEM_BYTES:
        raise Refused("One entry may take %d KB at most." % (ITEM_BYTES // 1024), 413)
    return out


def _merge_into(have: dict, new: dict) -> list[str]:
    """What `new` brings to the entry already there: list fields joined, empty fields filled.
    Nothing already there is changed or lost. The names of the fields it added to."""
    added = []
    for k, v in new.items():
        old = have.get(k)
        if isinstance(old, list) and isinstance(v, list):
            more = [x for x in v if x not in old]
            if more:
                have[k] = old + more
                added.append(k)
        elif old in (None, "", [], {}) and v not in (None, "", [], {}):
            have[k] = v
            added.append(k)
    return added


def _who(person) -> dict:
    return {"user": str(getattr(person, "user_id", "") or ""),
            "name": str(getattr(person, "name", "") or getattr(person, "email", "") or "")[:80]}


def _public(row, since=None) -> dict:
    if row is None:
        return {"version": 0, "items": [], "answers": {}, "updated_at": None}
    if since is not None and since == row.version:
        return {"version": row.version, "same": True}
    return {"version": row.version, "items": row.items, "answers": row.answers,
            "updated_at": row.updated_at,
            "removed": [{"w": r.get("item", {}).get("w"), "by": r.get("by"), "at": r.get("at")}
                        for r in row.removed[-20:]]}


def _seed(org_id: str, rel: str, key: str, now: float) -> tuple[list, dict, list]:
    """The list as each person kept it on the page so far, merged (see the module's words)."""
    from .models import PageState

    items: list[dict] = []
    answers: dict = {}
    notes: list[dict] = []
    for st in PageState.objects.filter(org_id=org_id, rel=rel).order_by("updated_at", "id"):
        settings = st.settings if isinstance(st.settings, dict) else {}
        kept = settings.get(key)
        by = {"user": str(st.user_id), "name": "", "from": f"page_states #{st.id}"}
        for raw in kept if isinstance(kept, list) else []:
            try:
                entry = _clean(raw)
            except Refused:
                notes.append({"op": "seed-skipped", "why": "not an entry", "from": by["from"]})
                continue
            i = ident(entry["w"])
            have = next((x for x in items if x["id"] == i), None)
            if have is None:
                entry.update(id=i, by=by, at=st.updated_at, seeded_from=by["from"])
                items.append(entry)
            else:
                fields = _merge_into(have, entry)
                have.setdefault("merged", []).append({"from": by["from"], "fields": fields,
                                                     "original": entry})
        # Domain answers the page kept for this person, which came from Rouh's own check.
        checks = settings.get("checks")
        if isinstance(checks, dict):
            dom = answers.setdefault("domains", {})
            for name, a in checks.items():
                if isinstance(a, dict) and name not in dom:
                    dom[str(name)[:80]] = {t: a[t] for t in ("ai", "com") if t in a}
        notes.append({"op": "seeded", "from": by["from"], "count": len(kept) if isinstance(kept, list) else 0,
                      "at": now})
    return items[:ITEMS_MOST], answers, notes


def _row(org_id: str, rel: str, key: str):
    """The list's row, held for this transaction, made (and seeded) when it is not there yet."""
    from django.db import IntegrityError, transaction

    from .models import PageSharedList

    row = PageSharedList.objects.select_for_update().filter(org_id=org_id, rel=rel, key=key).first()
    if row is not None:
        return row
    now = time.time()
    items, answers, notes = _seed(org_id, rel, key, now)
    try:
        with transaction.atomic():
            PageSharedList.objects.create(org_id=org_id, rel=rel, key=key, items=items,
                                          answers=answers, removed=[], log=notes,
                                          version=1, updated_at=now)
    except IntegrityError:
        pass  # somebody else made it a moment ago: theirs is the one
    return PageSharedList.objects.select_for_update().get(org_id=org_id, rel=rel, key=key)


def read(org_id: str, rel: str, key: str, since=None) -> dict:
    from django.db import transaction

    with transaction.atomic():
        return _public(_row(org_id, rel, key), since)


def change(org_id: str, rel: str, key: str, body: dict, person) -> dict:
    """One change to the list: ``add`` an entry, ``remove`` or ``edit`` one."""
    from django.db import transaction

    op = body.get("op")
    if op not in ("add", "remove", "edit"):
        raise Refused("Say add, remove or edit.")
    now = time.time()
    by = _who(person)
    with transaction.atomic():
        row = _row(org_id, rel, key)
        items = list(row.items)
        said: dict = {"op": op}
        if op == "add":
            entry = _clean(body.get("item"))
            i = ident(entry["w"])
            have = next((x for x in items if x.get("id") == i), None)
            if have is None:
                if len(items) >= ITEMS_MOST:
                    raise Refused("The list holds %d entries at most." % ITEMS_MOST, 413)
                entry.update(id=i, by=by, at=now)
                items.append(entry)
                said["added"] = i
            else:
                fields = _merge_into(have, entry)
                if fields:
                    have.setdefault("merged", []).append({"by": by, "at": now, "fields": fields})
                said["already"] = i
                said["fields"] = fields
        else:
            i = ident(body.get("id") or body.get("w"))
            have = next((x for x in items if x.get("id") == i), None)
            if have is None:
                # Taken off by somebody else already: nothing to do, and said so.
                said["gone"] = i
                return {**_public(row), **said}
            if op == "remove":
                items = [x for x in items if x.get("id") != i]
                row.removed = (list(row.removed) + [{"item": have, "by": by, "at": now}])[-REMOVED_MOST:]
                said["removed"] = i
            else:
                fields = body.get("fields")
                if not isinstance(fields, dict) or not fields:
                    raise Refused("Say which fields to change.")
                fields = {k: v for k, v in fields.items() if isinstance(k, str) and k not in OURS and k != "w"}
                before = {k: have.get(k) for k in fields}
                have.update(fields)
                if _size(have) > ITEM_BYTES:
                    raise Refused("One entry may take %d KB at most." % (ITEM_BYTES // 1024), 413)
                have.setdefault("edits", []).append({"by": by, "at": now, "before": before})
                have["edits"] = have["edits"][-20:]
                said["edited"] = i
        row.items = items
        row.version += 1
        row.updated_at = now
        row.log = (list(row.log) + [{"v": row.version, **said, "by": by, "at": now}])[-LOG_MOST:]
        if _size({"i": row.items, "a": row.answers, "r": row.removed, "l": row.log}) > ROW_BYTES:
            # History goes first, so the list itself is never refused for it.
            row.log = row.log[-200:]
            row.removed = row.removed[-200:]
        row.save(update_fields=["items", "removed", "log", "version", "updated_at"])
        return {**_public(row), **said}


def record_domains(org_id: str, rel: str, page: Path, found: dict) -> None:
    """Rouh's own domain answers (`name_checks.domains`), kept for every list the page shares."""
    from django.db import transaction

    doms = found.get("domains") if isinstance(found, dict) else None
    if not isinstance(doms, dict) or not doms:
        return
    checked = str(found.get("checked") or "")
    for key in lists_of(page):
        with transaction.atomic():
            row = _row(org_id, rel, key)
            answers = dict(row.answers)
            kept = dict(answers.get("domains") or {})
            changed = False
            for name, d in doms.items():
                one = dict(kept.get(name) or {})
                for t in ("ai", "com"):
                    a = d.get(t) if isinstance(d, dict) else None
                    # An answer that is not one keeps what was known before.
                    if not isinstance(a, dict) or a.get("status") not in ("free", "taken"):
                        continue
                    one[t] = [a["status"], a.get("created") or "", a.get("checked") or checked]
                    changed = True
                kept[name] = one
            if not changed:
                continue
            answers["domains"] = kept
            row.answers = answers
            row.version += 1
            row.updated_at = time.time()
            row.save(update_fields=["answers", "version", "updated_at"])


def beside(page: Path, org_id: str, rel: str) -> str:
    """Every list of the page, written as `BESIDE` in its folder for jobs to read."""
    from . import saving
    from .models import PageSharedList

    try:
        root = page.parent
        target = root / BESIDE
        if target.is_symlink():
            log.warning("sharedlist: %s is a link, not written", target)
            return ""
        keys = lists_of(page)
        out: dict = {}
        for row in PageSharedList.objects.filter(org_id=org_id, rel=rel, key__in=keys):
            out[row.key] = {"version": row.version, "items": row.items, "answers": row.answers,
                            "removed": row.removed[-100:],
                            "saved_at": datetime.fromtimestamp(row.updated_at, timezone.utc)
                            .isoformat(timespec="seconds")}
        if not out:
            return ""
        text = json.dumps(out, ensure_ascii=False, indent=2) + "\n"
        spare = target.with_name(f".{BESIDE}.{os.getpid()}.rouh-edit")
        was = page.stat()
        with open(spare, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.chmod(spare, 0o644)
        try:
            os.chown(spare, was.st_uid, was.st_gid)
        except OSError:
            pass
        os.replace(spare, target)
    except OSError as exc:
        log.warning("sharedlist: not written beside %s: %s", page, exc)
        return ""
    saving.poke()
    return str(target)


__all__ = ["BESIDE", "Refused", "beside", "change", "ident", "lists_of", "read", "record_domains"]
