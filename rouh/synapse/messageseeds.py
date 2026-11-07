"""The cheap seed step on every message Petar sends, in Rouh's chats wired to Synapse Master (D84).

On every message from the person, in a chat that is not one of Synapse's own, the
message is looked up in Master the way a question's seeds are found (`recall.run`):
its words and its meaning, each a ranked list, fused by rank (RRF). Nothing more:
no walk along links, no pack, no model call. Only the matches strong enough to be
worth the tokens come into the turn's context, as the compact lines the model reads
everywhere else (`text.compact`, D11), and only when they are back in time
(`brain.Brain._turn` waits at most `message_seed_wait_ms` for them, after its own
work, and never more). The full walk and pack, `synapse_query`, stays for when the
message names a person, a task or something past, or Rouh is unsure.

What is strong enough is a cosine between the message's vector and the item's best
passage, `message_seed_cosine`, measured on real past messages (5 October 2026,
`85-02.synapse-lab-first-version/85-02.areas-seeds-and-the-map.md`). The words list
still decides, through RRF, which items are looked at.

A task or a step the message names by its number ("what's up with 58", "where are we
with seventy") comes in whatever its cosine, found by that number in plain code
(`taskrefs`, as the search query has read them since attempt 21), and first: it needs
no vector, so it is ready in a few milliseconds, and a turn that cannot wait for the
vector still has it in its first request (`Pending`, attempt 22, 7 October 2026). In
the live log the whole lookup was not back for the first request in any of 235 turns.
"""
from __future__ import annotations

import logging
import time

from . import datasets, db, numbers, people, search, taskrefs, text as tx, vectors

log = logging.getLogger(__name__)

#: The longest message looked up, in characters: a pasted page is still searched by its start.
MOST_CHARS = 2000
#: How much of an item's own words a line shows when no model has read it yet (`text.compact`): a match's
#: start, and more of a task the message names, whose summary says what it is waiting on.
RAW_CHARS = 400
NAMED_RAW_CHARS = 1200


def _own_chat(ds: dict, chat_id: str) -> list[str]:
    """Master's items of the chat the message is in (`master._chat_parts`): never a seed for itself."""
    if not chat_id:
        return []
    return [r["id"] for r in db.rows(
        "SELECT id FROM synapse.item WHERE dataset_id = %s AND deleted_at IS NULL AND "
        "(source_key = %s OR source_key LIKE %s)", (ds["id"], f"chat:{chat_id}", f"chat:{chat_id}:%"))]


def _lines(ds: dict, ids: list[str], asker: str, refs: dict, budget: int, used: int = 0,
           raw_chars: int = RAW_CHARS) -> tuple:
    """Compact lines (`text.compact`) for these items, numbered by `refs`, while they fit `budget` tokens
    (the first always does). Returns the lines, the ids they are for, the tokens used so far, and the items."""
    from . import dreaming

    facts = search.items_by_id(ds["id"], ids)
    # A night of dreaming's notes, as the asker may see them (D86): a closed ask reads closed, a replaced
    # claim says so and names the seed that replaced it when it is one of these.
    dreaming.annotate(ds["id"], facts, search.readers_for(asker))
    lines, shown = [], []
    for item_id in ids:
        f = facts.get(item_id)
        if not f:
            continue
        line = tx.compact(refs[item_id], f, raw_chars=raw_chars, refs=refs)
        cost = tx.tokens(line)
        if (lines or used) and used + cost > budget:
            break
        lines.append(line)
        shown.append(item_id)
        used += cost
    return lines, shown, used, facts


def lookup(ds: dict, text: str, *, chat_id: str = "", asker: str | None = None, s=None, trace=None,
           early: dict | None = None) -> dict:
    """The strong seeds for one message, and everything measured on the way.

    Returns `{"strong": [...], "seeds": [...], "named": [...], "block": str, "ms": ..., "embed_ms": ...,
    "search_ms": ...}`. `seeds` are the top fused items with their scores, for measuring; `strong` the ones
    over the bar, each with `n`, its number in `block`; `named` the tasks and steps the message names by their
    number (`taskrefs`, attempt 22), which come in whatever their cosine; `block` what goes into the turn
    ("" when nothing came in), which is `named_block` and `match_block` together.

    A named task needs no vector, only one indexed query, so it is found first and, when `early` is given,
    its block is put there at once: a turn that cannot wait for the vector (about 200 ms, longer than the turn
    waits) still has the task the person named in its first request (`Pending`).

    `trace`, when given, is where the vector's cost is written down."""
    began = time.time()
    s = s or datasets.settings(ds)
    out = {"strong": [], "seeds": [], "named": [], "block": "", "named_block": "", "match_block": "",
           "ms": 0, "embed_ms": 0, "search_ms": 0, "named_ms": 0, "why": ""}
    words = " ".join(str(text or "").split())[:MOST_CHARS]
    if not words:
        out["why"] = "nothing to look up"
        return out
    asker = people.asker_id(ds, asker)
    budget, used, refs = int(s.message_seed_tokens), 0, {}
    if s.message_seed_tasks:
        named = taskrefs.resolve(ds, words, search.readers_for(asker))
        refs = {x["id"]: n for n, x in enumerate(named, start=1)}
        lines, shown, used, _ = _lines(ds, list(refs), asker, refs, budget, raw_chars=NAMED_RAW_CHARS) if named else ([], [], 0, {})
        refs = {k: v for k, v in refs.items() if k in shown}
        out["named"] = [{**x, "n": refs[x["id"]]} for x in named if x["id"] in refs]
        if lines:
            said = "; ".join(f"{x['words']} is {taskrefs.label(x)}" for x in out["named"])
            out["named_block"] = (
                f"From Synapse Master, the {'task' if len(lines) == 1 else 'tasks'} the person's last message "
                f"names by number, found by that number and not searched ({said}). Use "
                f"{'it' if len(lines) == 1 else 'them'} for what was asked, and call synapse_query for more:\n"
                + "\n".join(lines))
        out["named_ms"] = int((time.time() - began) * 1000)
        if early is not None:
            early.update({"block": out["named_block"], "named": out["named"]})
    got = vectors.query(ds, words, purpose="message_seeds", trace=trace)
    out["embed_ms"] = int((time.time() - began) * 1000) - out["named_ms"]
    if got["vec"] is None:
        # No meaning, no cosine to hold a match to: nothing more comes in, rather than a guess by words.
        out.update({"why": got["why"], "ms": int((time.time() - began) * 1000), "block": out["named_block"]})
        return out
    searched = time.time()
    found = search.hybrid(ds["id"], words, got["vec"], asker=asker, settings=s, depth=int(s.message_seed_depth),
                          exclude_ids=_own_chat(ds, chat_id), model=got["model"])
    out["search_ms"] = int((time.time() - searched) * 1000)
    bar = float(s.message_seed_cosine)
    top = found["items"][:int(s.message_seed_depth)]
    out["seeds"] = [{"id": f["item_id"], "rrf": round(f["rrf"], 5), "ranks": f["ranks"],
                     "cosine": f["scores"].get("meaning"), "words": f["scores"].get("words")} for f in top]
    strong = [x for x in out["seeds"] if x["cosine"] is not None and x["cosine"] >= bar
              and x["id"] not in refs][:int(s.message_seeds_max)]
    if strong:
        refs = {**refs, **{x["id"]: n for n, x in enumerate(strong, start=len(refs) + 1)}}
        lines, shown, used, facts = _lines(ds, [x["id"] for x in strong], asker, refs, budget, used)
        for x in strong:
            if x["id"] in shown:
                x.update({"title": facts[x["id"]].get("title"), "n": refs[x["id"]]})
        out["strong"] = [x for x in strong if x["id"] in shown]
        if lines:
            out["match_block"] = (
                f"From Synapse Master, looked up on the person's last message and matched closely (cosine at least "
                f"{bar:g}; no walk, nothing else read): {len(lines)} item{'s' if len(lines) != 1 else ''}. "
                "Use them when they bear on what was asked, ignore them when they do not, and call synapse_query "
                "for more:\n" + "\n".join(lines))
    out["block"] = "\n\n".join(b for b in (out["named_block"], out["match_block"]) if b)
    out["ms"] = int((time.time() - began) * 1000)
    return out


class Pending:
    """A turn's lookup under way (`brain.start_seeds`): the future of the whole lookup, and `early`, which the
    lookup fills, before it asks for the vector, with the block of the tasks the message names by number.

    `sent` is what the turns have carried so far: "all" (everything the lookup found), "named" (only the named
    tasks went, because the rest was not back), or "" (nothing went), so a later request brings only what an
    earlier one did not (`brain.late_seeds`). What is not back for the turn's last request goes with the next
    message in the same chat (Petar, 10 October 2026: nothing looked up is thrown away; `rouh/recalling.py`).

    `began` and `ended` (`time.monotonic()`) are its bar on the message's timeline."""

    def __init__(self, future, early: dict) -> None:
        self.future, self.early, self.sent = future, early, ""
        self.began, self.ended = time.monotonic(), None
        future.add_done_callback(self._ended)

    def _ended(self, _done) -> None:
        self.ended = time.monotonic()

    def done(self) -> bool:
        return self.future.done()

    def result(self):
        return self.future.result()


#: `message_seed_wait_ms` as the last lookup read it, so the turn knows how long it may wait before the
#: lookup it is waiting for has read anything (the first turn after a start waits the starting value).
_wait = {"ms": int(numbers.BY_KEY["message_seed_wait_ms"].value)}


def wait_seconds() -> float:
    return max(0, _wait["ms"]) / 1000.0


def _named(named: list[dict] | None) -> str:
    return ", ".join(f"task {x['number']}" for x in named or [])


def note(chat_id: str, got, *, ready: bool, waited_ms: int, prep_ms: int, named: list[dict] | None = None) -> None:
    """One line in the log per turn the lookup applied to: how long, how long the turn waited, what came in.
    `named` are the tasks a lookup that was not back had already found by number, and the turn took."""
    if got is None:
        return
    if got == "late":
        log.info("seeds for %s: not back %d ms after the turn's own %d ms, so the turn went on %s", chat_id,
                 waited_ms, prep_ms, f"with the named {_named(named)} alone" if named else "without them")
        return
    strong = got.get("strong") or []
    log.info("seeds for %s: looked up in %d ms (named tasks %d, vector %d, search %d; %d ms waiting for a thread, "
             "%d ms finding Master), the turn's own work %d ms, %s; %s%s",
             chat_id, got.get("ms", 0), got.get("named_ms", 0), got.get("embed_ms", 0), got.get("search_ms", 0),
             got.get("queued_ms", 0), got.get("setup_ms", 0), prep_ms,
             "back before it" if ready else f"waited {waited_ms} ms more",
             f"named {_named(got.get('named'))}; " if got.get("named") else "",
             (f"{len(strong)} came in (" + ", ".join(f"{x.get('cosine', 0):.2f}" for x in strong) + ")")
             if strong else (got.get("why") or "none strong enough"))


def note_after(chat_id: str, done) -> None:
    """When a lookup the turn did not wait for comes back: where its time went."""
    try:
        got = done.result()
    except Exception:  # noqa: BLE001
        return
    if isinstance(got, dict):
        log.info("seeds for %s: came back late, after %d ms waiting for a thread, %d ms finding Master, %d ms "
                 "for the vector and %d ms searching", chat_id, got.get("queued_ms", 0), got.get("setup_ms", 0),
                 got.get("embed_ms", 0), got.get("search_ms", 0))


def note_late(chat_id: str, got: dict) -> None:
    log.info("seeds for %s: back after the first request, so they came in with the next one after its tools: %s",
             chat_id, ", ".join(f"{x.get('cosine', 0):.2f}" for x in got.get("strong") or []))


def for_turn(chat_id: str, text: str, asked: float | None = None, early: dict | None = None) -> dict | None:
    """The lookup for a turn in Rouh's chats, on a thread of its own: None where it does not apply (a chat of
    Synapse's own, no Master, switched off), and the lookup's result otherwise; `early` is filled with the
    tasks the message names by number as soon as they are found (`lookup`). Never raises. The thread's
    database connection is kept open, as for everything else Rouh runs with `asyncio.to_thread`: opening one
    each time was about 30 ms of a lookup that has to be quick."""
    from . import chat as synapse_chat

    began = time.monotonic()
    queued = int((began - asked) * 1000) if asked else 0
    try:
        if not db.ready() or synapse_chat.place_of_chat(chat_id):
            return None
        ds = synapse_chat.master_for_turn()
        if not ds:
            return None
        s = datasets.settings(ds)
        _wait["ms"] = int(s.message_seed_wait_ms)
        if not s.message_seeds:
            return None
        from .. import silos

        limit = silos.limit_now()
        got = lookup(ds, text, chat_id=chat_id, s=s, early=early,
                     asker=silos.asker(limit, people.me(ds)) if limit is not None else None)
        got.update({"queued_ms": queued, "setup_ms": int((time.monotonic() - began) * 1000) - got["ms"]})
        return got
    except Exception:  # noqa: BLE001 - the turn goes on without it
        log.exception("the seed lookup on a message failed")
        return None
