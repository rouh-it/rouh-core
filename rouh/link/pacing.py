"""A Rouh's edits in a live space, at a person's speed while a person watches.

A Rouh could write a whole page in a blink; in a space people are watching, that is not working
together. So this Rouh's own edits go through here: a step at a time (a sentence, a row, a field),
a few a second, each step said first ("Writing step 2 of 4"), its marker on the part it is on.
With nobody watching, they go at full speed. "Skip to the end" sends the rest at once.

Before a big change (more than a few steps, or anything removed) the Rouh says in one line what
it is about to do, and waits a moment: anyone in the space can press Stop, and then nothing of it
is done.
"""
from __future__ import annotations

import asyncio
import re
import time
import uuid

#: A big change waits this long after saying what it is about to do.
INTENT_WAIT = 4.0
BIG = 4
#: Characters a second, and the shortest and longest pause between steps.
CHARS_A_SECOND = 45.0
LEAST, MOST = 0.35, 2.2


class _Run:
    def __init__(self, total: int, iid: str):
        self.total, self.done, self.iid = total, 0, iid
        self.skip = False
        self.stopped = False
        self.task: asyncio.Task | None = None


_RUNS: dict[tuple[str, str], _Run] = {}


def status(org: str, sid: str) -> dict:
    r = _RUNS.get((org, sid))
    if r is None or r.task is None or r.task.done():
        return {"busy": False}
    return {"busy": True, "done": r.done, "total": r.total, "intent": r.iid, "skipping": r.skip}


def skip(org: str, sid: str) -> bool:
    r = _RUNS.get((org, sid))
    if r is None:
        return False
    r.skip = True
    return True


def stop(org: str, sid: str) -> bool:
    r = _RUNS.get((org, sid))
    if r is None:
        return False
    r.stopped = True
    return True


def _watched(live, my_label: str) -> bool:
    return any(p.get("kind") == "person" for p in live.fresh_presence())


def sentences(text: str) -> list[str]:
    """Text in pieces a person can follow: sentences, or lines, of at most about 160 characters."""
    parts = re.findall(r"[^.!?\n]+[.!?]*\s*|\n", text)
    out: list[str] = []
    for p in parts:
        while len(p) > 160:
            cut = p.rfind(" ", 0, 160)
            cut = cut if cut > 40 else 160
            out.append(p[:cut + 1])
            p = p[cut + 1:]
        if p:
            out.append(p)
    return out or [text]


def split_insert(op: dict) -> list[dict]:
    """One long insert as several, a sentence each, the same characters with the same ids."""
    from . import doc as _doc

    pieces = sentences(op["text"])
    if len(pieces) <= 1:
        return [op]
    n, actor = _doc._cid(op["id0"])
    after = op["after"]
    out = []
    for p in pieces:
        out.append(dict(op, id=uuid.uuid4().hex[:20], id0=f"{n}~{actor}", after=after, text=p))
        n += len(p)
        after = f"{n - 1}~{actor}"
    return out


async def run(org: str, sid: str, steps: list[tuple[str, list[dict]]], *, intent: str, part: str = "",
              big: bool | None = None) -> dict:
    """Do these steps (each its words and its changes) as this Rouh, paced. Waits for the end."""
    from . import me as _me
    from . import spaces

    me = await asyncio.to_thread(_me.me, org)
    actor = f"rouh:{me.label}"
    key = (org, sid)
    old = _RUNS.get(key)
    if old is not None and old.task is not None and not old.task.done():
        raise RuntimeError("This Rouh is already at work in this space.")
    # Long texts in sentences, so they can be watched being written.
    paced: list[tuple[str, list[dict]]] = []
    for words, ops in steps:
        expanded: list[dict] = []
        for op in ops:
            expanded.extend(split_insert(op) if op["kind"] == "ins" else [op])
        if len(expanded) > 1 and all(o["kind"] == "ins" for o in expanded):
            for i, o in enumerate(expanded):
                paced.append((words if i == 0 else "", [o]))
        else:
            paced.append((words, expanded))
    iid = uuid.uuid4().hex[:16]
    big = (len(steps) >= BIG or any(o["kind"] in ("remove", "del") for _w, os_ in steps for o in os_)) if big is None else big
    r = _RUNS[key] = _Run(len(paced), iid if big else "")
    r.task = asyncio.current_task()
    live = await spaces.get(org, sid)
    name = me.tagged
    began = live.seq
    said = []
    try:
        if big:
            await spaces.change(org, sid, [spaces.new_op("intent", actor, iid=iid, part=part or "space", words=intent[:300])])
            spaces.seen(live, actor, kind="rouh", name=name, part=part, doing=f"About to: {intent[:150]}", busy=True)
            await live.changed()
            if not live.mine:
                asyncio.ensure_future(spaces._tell_presence(org, sid))
            end = time.time() + INTENT_WAIT
            while time.time() < end and not r.skip and not (live.doc.get("pace") or {}).get(actor, 0) > began:
                if r.stopped or (live.doc["intents"].get(iid) or {}).get("state") == "stopped":
                    r.stopped = True
                    break
                await asyncio.sleep(0.2)
        n_words = sum(1 for w, _ in paced if w)
        k = 0
        for words, ops in paced:
            if (live.doc.get("pace") or {}).get(actor, 0) > began:
                r.skip = True
            if r.stopped or (big and (live.doc["intents"].get(iid) or {}).get("state") == "stopped"):
                r.stopped = True
                break
            from . import doc as _doc

            here = next((p for o in ops for p in _doc.parts_of(o)), part)
            batch = []
            if words:
                k += 1
                batch.append(spaces.new_op("doing", actor, words=words[:200], part=here or "", step=k, of=n_words))
            batch.extend(ops)
            spaces.seen(live, actor, kind="rouh", name=name, part=here or "", doing=words or "Writing", busy=True)
            if not live.mine:
                asyncio.ensure_future(spaces._tell_presence(org, sid))
            got = await spaces.change(org, sid, batch)
            for ref in got.get("refused") or []:
                said.append(ref["why"])
            r.done += 1
            if _watched(live, me.label) and not r.skip:
                chars = sum(len(o.get("text", "")) for o in ops) + 20
                await asyncio.sleep(max(LEAST, min(MOST, chars / CHARS_A_SECOND)))
        if big:
            await spaces.change(org, sid, [spaces.new_op("intent.end", actor, iid=iid,
                                                         state="stopped" if r.stopped else "done")])
    finally:
        spaces.seen(live, actor, kind="rouh", name=name, part="", doing="", busy=False)
        await live.changed()
        if not live.mine:
            asyncio.ensure_future(spaces._tell_presence(org, sid))
        spaces._orb(org)
    return {"done": r.done, "total": r.total, "stopped": r.stopped, "refused": said[:5]}
