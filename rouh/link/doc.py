"""A live shared space as data: what its changes are, and what they add up to.

The room (`room.py`) puts every change in one order (``seq``), and the space as it stands is that
list of changes replayed (`replay`). Replaying is the whole truth, which is what makes history,
restore and undo per Rouh simple and exact: a version is the changes up to a seq; undoing one
Rouh's edits is replaying without them.

What merges how, as Figma does it and where text needs more:

- **Fields** (a title, a status, a step's done box): last writer wins. The last change the room
  receives is kept, so two people never get a mix.
- **Long text** (notes, a section of a document): a text CRDT (data that merges without clashing,
  here RGA, a replicated growable array). Every character has an id, ``<counter>~<actor>``; an
  insert says which character it follows. Both writers' words stay, in the same order on every
  copy, whatever order the changes arrived in, which is what lets a member that was offline put
  its changes on top on its return.
- **Lists** (steps, places, sources): items by id, each with its own last-writer-wins fields and a
  position number; removing an item hides it.
- **Claims**: a part claimed by a Rouh is changed only by it; first claim to reach the room wins; a
  person can take any part back.
- **Proposals** (a meeting time): never merged. Each person's yes is their own, and only the code
  of the Rouh holding the room settles one.

An op is ``{"id", "kind", "actor", "at", ...}``; `read_op` is its fixed form.
"""
from __future__ import annotations

import copy
import re

from . import forms

TEXT_MOST = 4000
VALUE_MOST = 4000
ACTIVITY_KEEP = 40

KINDS = ("set", "ins", "del", "add", "remove", "move", "claim", "release", "comment", "resolve",
         "intent", "intent.end", "propose", "yes", "settle", "doing", "undo", "restore", "pace")
#: Changes to what the space says; the rest is talk about it (comments, claims, intents, ...).
CONTENT = {"set", "ins", "del", "add", "remove", "move"}
KEY = re.compile(r"^[A-Za-z0-9_.:-]{1,80}$")
CHAR_ID = re.compile(r"^\d{1,12}~(person|rouh):[a-z0-9-]{1,80}$")

_OPT = ("obj", {"id": ("id",), "label": ("text", 200), "start?": ("iso",), "end?": ("iso",)})
OP_FORMS = {
    "set": {"path": ("list", 4, ("str", 80)), "v": ("json", VALUE_MOST)},
    "ins": {"t": ("str", 80), "after": ("str", 120), "id0": ("str", 120), "text": ("text", TEXT_MOST)},
    "del": {"t": ("str", 80), "ids": ("list", 4000, ("str", 120))},
    "add": {"list": ("str", 80), "item": ("id",), "pos": ("num", -1e12, 1e12), "fields": ("json", VALUE_MOST)},
    "remove": {"list": ("str", 80), "item": ("id",)},
    "move": {"list": ("str", 80), "item": ("id",), "pos": ("num", -1e12, 1e12)},
    "claim": {"part": ("str", 120)},
    "release": {"part": ("str", 120)},
    "comment": {"cid": ("id",), "part": ("str", 120), "text": ("text", 2000)},
    "resolve": {"cid": ("id",)},
    "intent": {"iid": ("id",), "part": ("str", 120), "words": ("text", 300)},
    "intent.end": {"iid": ("id",), "state": ("enum", ("stopped", "done"))},
    "propose": {"pid": ("id",), "what": ("enum", ("meeting", "money", "choice")), "title": ("text", 200),
                "options": ("list", 6, _OPT), "needed": ("list", 50, ("label",)), "minutes?": ("int", 0, 480)},
    "yes": {"pid": ("id",), "option": ("id",), "by_grant?": ("id",)},
    "settle": {"pid": ("id",), "state": ("enum", ("agreed", "booked", "withdrawn", "lapsed")),
               "chosen?": ("id",), "said?": ("text", 300)},
    "doing": {"words": ("text", 200), "part?": ("str", 120), "step?": ("int", 0, 10000), "of?": ("int", 0, 10000)},
    "undo": {"target": ("actor",), "from": ("int", 0, 10**9)},
    "restore": {"to": ("int", 0, 10**9)},
    # A person asks a Rouh at work to skip to the end of its run (it then sends the rest at once).
    "pace": {"target": ("actor",), "how": ("enum", ("skip",))},
}


def read_op(value, where: str = "op") -> dict:
    """The fixed form of one change, or forms.Refused."""
    if not isinstance(value, dict):
        raise forms.Refused(f"{where}: not a change")
    kind = value.get("kind")
    if kind not in OP_FORMS:
        raise forms.Refused(f"{where}: no such change")
    head = forms.read(value, {"id": ("id",), "kind": ("enum", KINDS), "actor": ("actor",),
                              "at": ("num", 0, 10**11), "seq?": ("int", 0, 10**9)}, where)
    body = forms.read(value, OP_FORMS[kind], where)
    for k in ("t", "list", "part"):
        if k in body and not KEY.match(str(body[k])):
            raise forms.Refused(f"{where}.{k}: not a name")
    if kind == "set":
        p = body["path"]
        if not ((len(p) == 2 and p[0] == "fields") or (len(p) == 4 and p[0] == "lists")):
            raise forms.Refused(f"{where}.path: not a field")
        if any(not KEY.match(x) for x in p):
            raise forms.Refused(f"{where}.path: not a name")
    if kind == "ins":
        if not CHAR_ID.match(body["id0"]) or (body["after"] and not CHAR_ID.match(body["after"])):
            raise forms.Refused(f"{where}: not a character id")
        if body["id0"].split("~", 1)[1] != head["actor"]:
            raise forms.Refused(f"{where}: a character id names another writer")
    if kind == "del" and any(not CHAR_ID.match(i) for i in body["ids"]):
        raise forms.Refused(f"{where}: not a character id")
    return {**head, **body}


# --- the space, from nothing -------------------------------------------------------------------


def empty() -> dict:
    return {"fields": {}, "texts": {}, "lists": {}, "claims": {}, "comments": {}, "intents": {},
            "proposals": {}, "activity": [], "runs": {}, "seq": 0}


def _cid(cid: str) -> tuple[int, str]:
    n, actor = cid.split("~", 1)
    return int(n), actor


def text_of(doc: dict, key: str) -> str:
    t = doc["texts"].get(key) or {}
    return "".join(c[1] for c in t.get("chars", []) if not c[2])


def visible(doc: dict, key: str) -> list[list]:
    """[[id, ch, by], ...] of the characters showing, in order."""
    t = doc["texts"].get(key) or {}
    return [[c[0], c[1], c[3]] for c in t.get("chars", []) if not c[2]]


def top(doc: dict, key: str) -> int:
    return int((doc["texts"].get(key) or {}).get("top") or 0)


def _text(doc: dict, key: str) -> dict:
    return doc["texts"].setdefault(key, {"chars": [], "top": 0})


def _integrate(t: dict, after: str, cid: str, ch: str, by: str, gone: bool = False) -> None:
    chars = t["chars"]
    index = {c[0]: i for i, c in enumerate(chars)}
    if cid in index:
        return
    pos = index[after] + 1 if after and after in index else (0 if not after else len(chars))
    mine = _cid(cid)
    while pos < len(chars) and _cid(chars[pos][0]) > mine:
        pos += 1
    chars.insert(pos, [cid, ch, 1 if gone else 0, by])
    t["top"] = max(int(t.get("top") or 0), mine[0])


def _ins(doc: dict, op: dict, gone: bool) -> None:
    t = _text(doc, op["t"])
    n, actor = _cid(op["id0"])
    after = op["after"]
    for i, ch in enumerate(op["text"]):
        cid = f"{n + i}~{actor}"
        _integrate(t, after, cid, ch, op["actor"], gone)
        after = cid


def _del(doc: dict, op: dict) -> None:
    t = _text(doc, op["t"])
    gone = set(op["ids"])
    for c in t["chars"]:
        if c[0] in gone:
            c[2] = 1


def _field(holder: dict, key: str, op: dict) -> None:
    holder[key] = {"v": copy.deepcopy(op["v"]), "by": op["actor"], "seq": op.get("seq", 0)}


def parts_of(op: dict) -> list[str]:
    """The parts of the space a change touches, for claims."""
    k = op["kind"]
    if k == "set":
        p = op["path"]
        return [f"field:{p[1]}"] if p[0] == "fields" else [f"list:{p[1]}", f"item:{p[2]}"]
    if k in ("ins", "del"):
        return [f"text:{op['t']}"]
    if k in ("add", "remove", "move"):
        return [f"list:{op['list']}"] + ([f"item:{op['item']}"] if k != "add" else [])
    return []


def apply(doc: dict, op: dict, *, undone: bool = False) -> None:
    """One change, in place. An undone change is skipped, except that an undone insert stays as
    hidden characters, so what others wrote after them still has its place."""
    k = op["kind"]
    seq = op.get("seq", 0)
    doc["seq"] = max(doc.get("seq", 0), seq)
    if undone:
        if k == "ins":
            _ins(doc, op, gone=True)
        return
    if k == "set":
        p = op["path"]
        if p[0] == "fields":
            _field(doc["fields"], p[1], op)
        else:
            item = doc["lists"].setdefault(p[1], {}).get(p[2])
            if item is not None:
                _field(item["fields"], p[3], op)
    elif k == "ins":
        _ins(doc, op, gone=False)
    elif k == "del":
        _del(doc, op)
    elif k == "add":
        lst = doc["lists"].setdefault(op["list"], {})
        if op["item"] not in lst:
            fields = op["fields"] if isinstance(op["fields"], dict) else {}
            lst[op["item"]] = {"pos": op["pos"], "gone": False, "by": op["actor"], "seq": seq,
                               "fields": {str(f)[:80]: {"v": v, "by": op["actor"], "seq": seq}
                                          for f, v in list(fields.items())[:20]}}
    elif k == "remove":
        item = doc["lists"].setdefault(op["list"], {}).get(op["item"])
        if item is not None:
            item["gone"] = True
    elif k == "move":
        item = doc["lists"].setdefault(op["list"], {}).get(op["item"])
        if item is not None:
            item["pos"] = op["pos"]
    elif k == "claim":
        if op["part"] not in doc["claims"]:
            doc["claims"][op["part"]] = {"by": op["actor"], "seq": seq}
    elif k == "release":
        doc["claims"].pop(op["part"], None)
    elif k == "comment":
        doc["comments"][op["cid"]] = {"part": op["part"], "by": op["actor"], "text": str(op["text"]),
                                      "seq": seq, "at": op.get("at", 0), "resolved": False}
    elif k == "resolve":
        if op["cid"] in doc["comments"]:
            doc["comments"][op["cid"]]["resolved"] = True
    elif k == "intent":
        doc["intents"][op["iid"]] = {"by": op["actor"], "part": op["part"], "words": str(op["words"]),
                                     "state": "shown", "seq": seq, "at": op.get("at", 0)}
        doc["runs"][op["actor"]] = seq
    elif k == "intent.end":
        if op["iid"] in doc["intents"]:
            doc["intents"][op["iid"]]["state"] = op["state"]
    elif k == "propose":
        doc["proposals"][op["pid"]] = {
            "kind": op["what"], "by": op["actor"], "title": str(op["title"]),
            "options": [{k2: str(v) for k2, v in o.items()} for o in op["options"]],
            "needed": list(op["needed"]), "yes": {}, "state": "open", "chosen": "", "seq": seq,
            "minutes": op.get("minutes", 0), "said": ""}
    elif k == "yes":
        prop = doc["proposals"].get(op["pid"])
        if prop is not None and prop["state"] == "open":
            label = op["actor"].split(":", 1)[1]
            prop["yes"][label] = {"option": op["option"], "by": op["actor"], "grant": op.get("by_grant", "")}
    elif k == "settle":
        prop = doc["proposals"].get(op["pid"])
        if prop is not None:
            prop["state"] = op["state"]
            prop["chosen"] = op.get("chosen", "")
            prop["said"] = str(op.get("said") or "")
    elif k == "pace":
        doc.setdefault("pace", {})[op["target"]] = seq
    elif k == "doing":
        doc["activity"].append({"by": op["actor"], "words": str(op["words"]), "part": op.get("part", ""),
                                "seq": seq, "at": op.get("at", 0), "step": op.get("step", 0),
                                "of": op.get("of", 0)})
        doc["activity"] = doc["activity"][-ACTIVITY_KEEP:]
        doc["runs"].setdefault(op["actor"], seq)


def replay(ops: list[dict], *, upto: int | None = None, start: dict | None = None) -> dict:
    """The space after these changes, in their order (each with ``seq`` and ``undone``)."""
    undone_from: dict[str, int] = {}
    for op in ops:
        if op["kind"] == "undo" and (upto is None or op.get("seq", 0) <= upto):
            t = op["target"]
            undone_from[t] = min(undone_from.get(t, 10**12), op["from"]) if t in undone_from else op["from"]
    doc = copy.deepcopy(start) if start else empty()
    for op in ops:
        s = op.get("seq", 0)
        if upto is not None and s > upto:
            break
        if op["kind"] == "restore":
            _restore(doc, ops, op["to"], s)
            continue
        if op["kind"] == "undo":
            doc["seq"] = max(doc.get("seq", 0), s)
            continue
        u = op.get("undone") or (op["kind"] in CONTENT and op["actor"] in undone_from
                                 and s >= undone_from[op["actor"]])
        apply(doc, op, undone=bool(u))
    return doc


def _restore(doc: dict, ops: list[dict], to: int, seq: int) -> None:
    """Bring the content back to what it was at ``to``; comments, claims and decisions stay."""
    then = replay([o for o in ops if o.get("seq", 0) <= to])
    doc["fields"] = copy.deepcopy(then["fields"])
    shown = {key: {c[0] for c in t.get("chars", []) if not c[2]} for key, t in then["texts"].items()}
    for key, t in doc["texts"].items():
        keep = shown.get(key, set())
        for c in t["chars"]:
            c[2] = 0 if c[0] in keep else 1
    for name in set(doc["lists"]) | set(then["lists"]):
        lst = doc["lists"].setdefault(name, {})
        old = then["lists"].get(name, {})
        for iid, item in lst.items():
            if iid in old:
                o = old[iid]
                item.update(pos=o["pos"], gone=o["gone"], fields=copy.deepcopy(o["fields"]))
            else:
                item["gone"] = True
        for iid, o in old.items():
            if iid not in lst:
                lst[iid] = copy.deepcopy(o)
    doc["seq"] = max(doc.get("seq", 0), seq)


# --- what a person's page is handed ---------------------------------------------------------------


def shown(doc: dict) -> dict:
    """The space for a page: fields as values, texts as their showing characters, lists in order."""
    lists = {}
    for name, lst in doc["lists"].items():
        items = [{"id": iid, "pos": it["pos"], "by": it["by"],
                  "fields": {k: v["v"] for k, v in it["fields"].items()},
                  "field_by": {k: v["by"] for k, v in it["fields"].items()}}
                 for iid, it in lst.items() if not it["gone"]]
        items.sort(key=lambda x: (x["pos"], x["id"]))
        lists[name] = items
    texts = {}
    for key in doc["texts"]:
        chars = visible(doc, key)
        texts[key] = {"text": "".join(c[1] for c in chars), "ids": [c[0] for c in chars],
                      "by": _runs([c[2] for c in chars]), "top": top(doc, key)}
    return {
        "fields": {k: v["v"] for k, v in doc["fields"].items()},
        "field_by": {k: v["by"] for k, v in doc["fields"].items()},
        "texts": texts, "lists": lists, "claims": doc["claims"],
        "comments": [dict(v, id=k) for k, v in sorted(doc["comments"].items(), key=lambda kv: kv[1]["seq"])],
        "intents": [dict(v, id=k) for k, v in sorted(doc["intents"].items(), key=lambda kv: kv[1]["seq"])],
        "proposals": [dict(v, id=k) for k, v in sorted(doc["proposals"].items(), key=lambda kv: kv[1]["seq"])],
        "activity": doc["activity"][-12:], "runs": doc.get("runs", {}), "seq": doc.get("seq", 0),
    }


def _runs(bys: list[str]) -> list[list]:
    """Who wrote which stretch of a text: [[start, length, actor], ...]."""
    out: list[list] = []
    for i, b in enumerate(bys):
        if out and out[-1][2] == b:
            out[-1][1] += 1
        else:
            out.append([i, 1, b])
    return out


def diff_text(old_ids: list[str], old: str, new: str) -> tuple[list[str], str, str]:
    """(ids deleted, the id the new text goes after, the text inserted) for an edit of a text whose
    showing characters are ``old_ids``/``old``: one stretch changed, found by the common start and end."""
    a = 0
    while a < len(old) and a < len(new) and old[a] == new[a]:
        a += 1
    b = 0
    while b < len(old) - a and b < len(new) - a and old[len(old) - 1 - b] == new[len(new) - 1 - b]:
        b += 1
    gone = old_ids[a:len(old) - b]
    added = new[a:len(new) - b]
    after = old_ids[a - 1] if a > 0 else ""
    return gone, after, added
