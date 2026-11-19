"""A live page's source as shared data: one text, a line CRDT, with stable element ids.

A Live page (kind ``html``, task 189 step 189-08) is one fully custom, self-contained HTML page that
several Rouhs and their people change at once. Its whole source is one shared text, kept as RGA (the
text CRDT of `doc.py`) with a *unit* in place of a character: a run of the source that ends just after
a newline, or at `UNIT` characters. Every unit has an id ``<counter>~<actor>`` and an insert names the
unit it follows, so both writers' units stay, in the same order on every copy, whatever order the
changes arrived in. A page of 2 MB is some tens of thousands of units, not two million characters,
which keeps replaying, history and undo quick.

Elements get stable ids (`ATTR`, ``data-rouh-id``) when a page enters a space and whenever a change
adds one (`stamp`), so a Rouh's marker, a claim and a pinned comment each sit on one element, by
its id, whatever else moves around it. `touched` says which elements a change reaches, worked out
from the source and never from what the sender said, which is what claims are checked against.
"""
from __future__ import annotations

import re
import secrets

from . import forms

#: The most a live page holds, in characters.
MOST = 2_000_000
#: The longest unit.
UNIT = 4000
#: The most one insert carries, in characters and in units, and the most ids one delete names.
INS_CHARS = 256_000
INS_UNITS = 2000
DEL_IDS = 20000
ATTR = "data-rouh-id"
TOO_BIG = "A live page holds at most 2 MB; this change would make it bigger."
RID = re.compile(r"^[A-Za-z0-9_-]{1,40}$")

#: Elements never stamped, and those whose insides are not HTML or are never stamped.
_SKIP = {"html", "head", "body", "script", "style", "meta", "link", "title", "base", "template", "noscript"}
_RAW = {"script", "style", "textarea", "title", "xmp", "template", "noscript", "iframe", "noembed", "noframes"}
_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source",
         "track", "wbr"}
_TAG = re.compile(r"<([A-Za-z][A-Za-z0-9:-]*)")
_ID_IN = re.compile(r"\sdata-rouh-id\s*=\s*(\"([^\"]*)\"|'([^']*)'|([^\s>]+))", re.I)
_ID_ANY = re.compile(r"data-rouh-id\s*=\s*[\"']?([A-Za-z0-9_-]{1,40})")


def clean(text: str) -> str:
    """The text as the keyless reader leaves it (`forms._clean_text`), so every copy holds the same."""
    return "".join(c for c in str(text or "") if c in "\n\t" or (ord(c) >= 32 and ord(c) != 127))


_END_TAG = re.compile(r"</[A-Za-z][A-Za-z0-9:-]{0,40}\s*>")


def split_units(text: str) -> list[str]:
    """A unit ends just after a newline or an end tag, or at `UNIT` characters: so a page written on
    one long line is still changed an element at a time, not as one piece."""
    out, start, n = [], 0, len(text)
    while start < n:
        limit = min(n, start + UNIT)
        nl = text.find("\n", start, limit)
        end = nl + 1 if nl != -1 else limit
        m = _END_TAG.search(text, start, end)
        if m:
            end = m.end()
        out.append(text[start:end])
        start = end
    return out


# --- the data -------------------------------------------------------------------------------------


def _h(doc: dict) -> dict:
    return doc.setdefault("html", {"units": [], "top": 0, "v": 0})


def units(doc: dict) -> list[tuple[str, str]]:
    """[(id, text)] of the units showing, in order."""
    return [(u[0], u[1]) for u in (doc.get("html") or {}).get("units", []) if not u[2]]


def text(doc: dict) -> str:
    return "".join(u[1] for u in (doc.get("html") or {}).get("units", []) if not u[2])


def size(doc: dict) -> int:
    return sum(len(u[1]) for u in (doc.get("html") or {}).get("units", []) if not u[2])


def top(doc: dict) -> int:
    return int((doc.get("html") or {}).get("top") or 0)


def _cid(uid: str) -> tuple[int, str]:
    n, actor = uid.split("~", 1)
    return int(n), actor


def apply_ins(doc: dict, op: dict, *, gone: bool = False) -> None:
    """An insert, in place: its units after the one it names, by the RGA rule. Each insert's ids run on
    from ``id0`` by one writer, so after the first unit the rest follow it directly."""
    h = _h(doc)
    us = h["units"]
    n, actor = _cid(op["id0"])
    if not op["units"]:
        return
    index = {u[0]: i for i, u in enumerate(us)}
    if op["id0"] in index:
        return
    after = op["after"]
    pos = index[after] + 1 if after and after in index else (0 if not after else len(us))
    mine = (n, actor)
    while pos < len(us) and _cid(us[pos][0]) > mine:
        pos += 1
    fresh = [[f"{n + i}~{actor}", t, 1 if gone else 0, op["actor"]] for i, t in enumerate(op["units"])]
    us[pos:pos] = fresh
    h["top"] = max(int(h.get("top") or 0), n + len(fresh) - 1)
    if not gone:
        h["v"] = max(int(h.get("v") or 0), int(op.get("seq") or 0))


def apply_del(doc: dict, op: dict) -> None:
    h = _h(doc)
    gone = set(op["ids"])
    for u in h["units"]:
        if u[0] in gone:
            u[2] = 1
    h["v"] = max(int(h.get("v") or 0), int(op.get("seq") or 0))


def restore(doc: dict, then: dict) -> None:
    """The source back to what it was in ``then`` (an earlier replay): units shown then show, the rest hide."""
    keep = {u[0] for u in (then.get("html") or {}).get("units", []) if not u[2]}
    for u in _h(doc)["units"]:
        u[2] = 0 if u[0] in keep else 1


def by_runs(doc: dict) -> list[list]:
    """Who wrote which stretch of the source: [[start char, length, actor], ...], runs merged."""
    out: list[list] = []
    at = 0
    for u in (doc.get("html") or {}).get("units", []):
        if u[2]:
            continue
        if out and out[-1][2] == u[3]:
            out[-1][1] += len(u[1])
        else:
            out.append([at, len(u[1]), u[3]])
        at += len(u[1])
    return out


# --- making changes -------------------------------------------------------------------------------


def _ops(dels: list[str], after: str, pieces: list[str], actor: str, start: int, els: list[str]) -> list[dict]:
    from . import spaces

    out = []
    for i in range(0, len(dels), DEL_IDS):
        out.append(spaces.new_op("hdel", actor, ids=dels[i:i + DEL_IDS], els=els[:200]))
    n = start
    batch: list[str] = []
    chars = 0

    def flush():
        nonlocal n, after, batch, chars
        if batch:
            out.append(spaces.new_op("hins", actor, after=after, id0=f"{n}~{actor}", units=batch, els=els[:200]))
            n += len(batch)
            after = f"{n - 1}~{actor}"
            batch, chars = [], 0

    for p in pieces:
        if len(batch) >= INS_UNITS or chars + len(p) > INS_CHARS:
            flush()
        batch.append(p)
        chars += len(p)
    flush()
    return out


def edit_ops(doc: dict, new_text: str, actor: str, *, base_units: list[tuple[str, str]] | None = None) -> list[dict]:
    """The changes (deletes, then inserts) that turn the source into ``new_text``. ``base_units`` are the
    showing units of the version the editor started from; the changes made since then stay, because
    only the units the editor changed are named. New ids run on from the largest counter in ``doc``."""
    new_text = clean(new_text)
    if len(new_text) > MOST:
        raise forms.Refused(TOO_BIG)
    old = list(base_units) if base_units is not None else units(doc)
    i, pos = 0, 0
    while i < len(old) and new_text.startswith(old[i][1], pos):
        pos += len(old[i][1])
        i += 1
    j, end = len(old), len(new_text)
    while j > i and end - len(old[j - 1][1]) >= pos and new_text.startswith(old[j - 1][1], end - len(old[j - 1][1])):
        end -= len(old[j - 1][1])
        j -= 1
    dels = [u[0] for u in old[i:j]]
    middle = new_text[pos:end]
    if not dels and not middle:
        return []
    after = old[i - 1][0] if i > 0 else ""
    gone_text = "".join(u[1] for u in old[i:j])
    els = list(dict.fromkeys(_ID_ANY.findall(gone_text) + _ID_ANY.findall(middle)))
    if not els:
        base = "".join(u[1] for u in old)
        at = sum(len(u[1]) for u in old[:i])
        inner = _innermost(elements(base), at)
        els = [inner] if inner else []
    return _ops(dels, after, split_units(middle), actor, top(doc) + 1, els)


def initial_ops(source: str, actor: str) -> list[dict]:
    """The changes that put a whole page into an empty space."""
    return edit_ops({"html": {"units": [], "top": 0, "v": 0}}, source, actor)


# --- elements ---------------------------------------------------------------------------------------


def _scan(source: str):
    """The tags of a page, in order: (kind, tag, start, end) with kind "open", "close" or "self".
    Comments, doctypes and the insides of script, style and the like are passed over."""
    i, n = 0, len(source)
    low = source.lower()
    while i < n:
        lt = source.find("<", i)
        if lt == -1:
            return
        if source.startswith("<!--", lt):
            e = source.find("-->", lt + 4)
            i = n if e == -1 else e + 3
            continue
        if source.startswith("<!", lt) or source.startswith("<?", lt):
            e = source.find(">", lt)
            i = n if e == -1 else e + 1
            continue
        if source.startswith("</", lt):
            m = re.match(r"</([A-Za-z][A-Za-z0-9:-]*)[^>]*>", source[lt:lt + 200])
            if m:
                yield ("close", m.group(1).lower(), lt, lt + m.end())
                i = lt + m.end()
            else:
                i = lt + 2
            continue
        m = _TAG.match(source, lt)
        if not m:
            i = lt + 1
            continue
        tag = m.group(1).lower()
        j, quote = m.end(), ""
        while j < n:
            c = source[j]
            if quote:
                if c == quote:
                    quote = ""
            elif c in "\"'":
                quote = c
            elif c == ">":
                break
            j += 1
        end = min(n, j + 1)
        selfclose = source[j - 1:j] == "/" or tag in _VOID
        yield ("self" if selfclose else "open", tag, lt, end)
        i = end
        if tag in _RAW and not selfclose:
            close = low.find("</" + tag, end)
            if close == -1:
                return
            i = close


def stamp(source: str) -> str:
    """Every element in the page's body without a ``data-rouh-id`` gets a new one, and a repeated one a
    fresh one. The page's head, its scripts and styles, and what is inside them are left alone."""
    source = clean(source)
    out: list[str] = []
    last = 0
    seen: set[str] = set()
    in_head = False
    has_body = "<body" in source.lower()
    in_body = not has_body
    for kind, tag, start, end in _scan(source):
        if kind == "close":
            if tag == "head":
                in_head = False
            continue
        if tag == "head":
            in_head = True
            continue
        if tag == "body":
            in_body, in_head = True, False
            continue
        if tag in _SKIP or in_head or not in_body:
            continue
        piece = source[start:end]
        m = _ID_IN.search(piece)
        if m:
            value = m.group(2) or m.group(3) or m.group(4) or ""
            if RID.match(value) and value not in seen:
                seen.add(value)
                continue
            fresh = _new_id(seen)
            new_piece = piece[:m.start()] + f' {ATTR}="{fresh}"' + piece[m.end():]
        else:
            fresh = _new_id(seen)
            name_end = len(tag) + 1
            new_piece = piece[:name_end] + f' {ATTR}="{fresh}"' + piece[name_end:]
        out.append(source[last:start])
        out.append(new_piece)
        last = end
    out.append(source[last:])
    return "".join(out)


_ID_ATTR = re.compile(r"\s" + ATTR + r"=\"[A-Za-z0-9_-]{1,40}\"")


def unstamp(source: str) -> str:
    """The page without the ids `stamp` gave it: what goes back into a person's own file, which never
    needed them. Only the exact attribute `stamp` writes is taken out."""
    out: list[str] = []
    last = 0
    for kind, _tag, start, end in _scan(source):
        if kind == "close":
            continue
        piece = source[start:end]
        cut = _ID_ATTR.sub("", piece, count=1)
        if cut != piece:
            out.append(source[last:start])
            out.append(cut)
            last = end
    out.append(source[last:])
    return "".join(out)


def _new_id(seen: set) -> str:
    while True:
        rid = "r" + "".join(secrets.choice("abcdefghijklmnopqrstuvwxyz0123456789") for _ in range(7))
        if rid not in seen:
            seen.add(rid)
            return rid


def elements(source: str) -> list[dict]:
    """The stamped elements: [{"id", "tag", "start", "end", "parent"}], ``end`` after the element's end tag."""
    out: list[dict] = []
    stack: list[tuple[str, int]] = []      # (tag, index in out or -1)
    for kind, tag, start, end in _scan(source):
        if kind == "close":
            for k in range(len(stack) - 1, -1, -1):
                if stack[k][0] == tag:
                    for _t, idx in stack[k:]:
                        if idx >= 0:
                            out[idx]["end"] = end if _t == tag else start
                    del stack[k:]
                    break
            continue
        m = _ID_IN.search(source, start, end)
        rid = (m.group(2) or m.group(3) or m.group(4)) if m else ""
        parent = next((out[idx]["id"] for _t, idx in reversed(stack) if idx >= 0), "")
        idx = -1
        if rid and RID.match(rid):
            out.append({"id": rid, "tag": tag, "start": start, "end": end if kind == "self" else len(source),
                        "parent": parent})
            idx = len(out) - 1
        if kind == "open":
            stack.append((tag, idx))
    return out


def _innermost(els: list[dict], at: int) -> str:
    best, width = "", None
    for e in els:
        if e["start"] < at < e["end"] and (width is None or e["end"] - e["start"] < width):
            best, width = e["id"], e["end"] - e["start"]
    return best


def touched(doc: dict, op: dict) -> set[str]:
    """The elements a change to the source reaches: every element it falls inside or overlaps."""
    us = (doc.get("html") or {}).get("units", [])
    ranges: list[tuple[int, int]] = []
    at = 0
    if op["kind"] == "hdel":
        gone = set(op["ids"])
        for u in us:
            if u[2]:
                continue
            if u[0] in gone:
                ranges.append((at, at + len(u[1])))
            at += len(u[1])
    elif op["kind"] == "hins":
        point = 0 if not op["after"] else None
        for u in us:
            if not u[2]:
                at += len(u[1])
            if u[0] == op["after"]:
                point = at
                break
        if point is None:
            point = at
        ranges.append((point, point))
    if not ranges:
        return set()
    src = text(doc)
    out = set()
    for e in elements(src):
        for a, b in ranges:
            if (a == b and e["start"] < a < e["end"]) or (a < b and e["start"] < b and e["end"] > a):
                out.add(e["id"])
                break
    return out


def page_size_after(doc: dict, op: dict) -> int:
    """How big the page would be after this insert."""
    return size(doc) + sum(len(t) for t in op.get("units", []))
