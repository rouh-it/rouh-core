"""Trimming old tool results out of General's window, and keeping everything else.

General's alone, since 26 September 2026. General is the one conversation
that never ends, sent a window of its newest messages, and it is the one this
was written for. Every other chat is sent whole, every tool result as it came
back, and nothing here touches it (`rouh/chatkinds.py`).

The window used to be managed by one number: the last `history_turns` messages
were sent whole and everything before them was gone. That throws away the wrong
thing. What fills a window is tool output, and tool output is the part nobody
needs twice: a page that was read four turns ago, a directory listing, the
whole of a file. What is worth keeping is the cheap part, the assistant's own
words and reasoning, which is what says why the conversation went the way it
did.

So this replaces the body of an old tool result with one line saying what was
there, and leaves every other block exactly as it was. The result is a window
that holds far more conversation in far fewer tokens, and a model that can
still see what it decided and why, four turns later, instead of a hole.

Two things make a result old enough to trim:

- age: it is further back than `keep_messages` from the end of the window;
- size: the window itself has gone past a token budget, and then the recent
  ones are trimmed too, newest last, until it fits.

Both are decided where a turn begins, and never between two requests of the
same turn. Every request of a turn is read out of the prompt cache up to the
point where it differs from the one before (`rouh/promptcache.py`), so a result
trimmed in the middle of a turn changes a message every later request has
already had cached, and everything after it is written to the cache again at
more than the full price. Trimming a turn's window mid-turn to save money is
the most expensive thing that can be done to it. The one exception is a window
about to be more than the model can read at all (:func:`ceiling`), where a
cache written again is the price of an answer.

A trimmed body is always the same words for the same result, so a result
trimmed at the start of one turn reads exactly the same at the start of the
next.

The token numbers are the API's own, off `usage` on each response, not an
estimate. :func:`window_tokens` is what turns one of those into the size of the
window that produced it, and the only subtlety there is prompt caching: cached
input is in the window and is deliberately not in `input_tokens`.

Nothing here writes to the database. The full result is still in `messages`
table, so a trimmed turn is trimmed only on its way to the model, and the
transcript and the history on disk are untouched.
"""
from __future__ import annotations

import json

#: The words that say a body has already been trimmed. The mark lives in the
#: text rather than in a field on the block: a tool_result goes to the Messages
#: API exactly as it is, and the API refuses any field it does not recognise
#: inside one ("tool_result.trimmed: Extra inputs are not permitted").
MARK = "has been trimmed out of the context"

#: What replaces a body. It says the size, so the model can tell a trimmed
#: listing from a trimmed book, and it says how to get it back, because the
#: only wrong answer here is the model inventing what the result said.
PLACEHOLDER = ("[{what} of about {size} characters was here and " + MARK + " "
               "to save room. It is not lost: call the same "
               "tool again if you need it.]")

#: Below this a result is left alone. Trimming a forty character answer costs
#: more in placeholder than it saves, and the small ones are the ones worth
#: keeping anyway.
MIN_BODY = 400

#: How many messages at the end of the window keep their tool results whole,
#: whatever else happens. The answer being written right now depends on them.
KEEP_MESSAGES = 6


def _describe(block: dict) -> str:
    """What kind of thing is being trimmed, in words, for the placeholder."""
    if block.get("is_error"):
        return "A failed tool result"
    return "A tool result"


def _body_size(content) -> int:
    if isinstance(content, str):
        return len(content)
    try:
        return len(json.dumps(content))
    except (TypeError, ValueError):
        return len(str(content))


def _trim_block(block: dict) -> tuple[dict, int]:
    """One tool_result with its body replaced. Returns it and what that saved."""
    size = _body_size(block.get("content"))
    trimmed = dict(block)
    trimmed["content"] = PLACEHOLDER.format(what=_describe(block), size=size)
    # A trimmed error is no longer an error the model has to act on, and
    # leaving the flag set makes every later turn treat the placeholder as a
    # live failure. The words still say it failed.
    trimmed.pop("is_error", None)
    return trimmed, max(0, size - len(trimmed["content"]))


def _blocks_of(message) -> list | None:
    """The content of a message, if it is a list of plain dictionaries.

    Assistant turns come back from the SDK as model objects and are never
    touched: there is nothing in them worth trimming, and rebuilding one is how
    a `tool_use` block loses the field that pairs it with its result.
    """
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, list):
        return None
    return content


def _already_trimmed(content) -> bool:
    """Whether this body is one of ours, so it is not shortened a second time."""
    return isinstance(content, str) and MARK in content


def _loads_tools(content) -> bool:
    """Whether a result is a search's answer, the tools it loaded.

    Never trimmed, however old: its `tool_reference` blocks are what keep
    those tools loaded for the rest of the conversation (`rouh/toolsearch.py`),
    and a placeholder in their place would unload them with nothing said.
    """
    return isinstance(content, list) and any(
        isinstance(b, dict) and b.get("type") == "tool_reference" for b in content)


def _trimmable(block, min_body: int) -> bool:
    return (isinstance(block, dict)
            and block.get("type") == "tool_result"
            and not _already_trimmed(block.get("content"))
            and not _loads_tools(block.get("content"))
            and _body_size(block.get("content")) >= min_body)


def trim(messages: list, *, keep_messages: int = KEEP_MESSAGES,
         min_body: int = MIN_BODY, at_most: int | None = None) -> tuple[list, dict]:
    """Trim old tool results. Returns the new message list and what it did.

    `keep_messages` messages at the end are never touched. `at_most` caps how
    many results are trimmed in one pass, which is what lets the caller take
    the window down gradually rather than emptying it the moment it is one
    token over budget.

    The list is rebuilt rather than edited in place: the caller's copy is the
    one that goes in the database, and a trimmed body must never end up there.
    """
    if keep_messages < 0:
        keep_messages = 0
    cut = len(messages) - keep_messages
    out: list = []
    trimmed_count = 0
    saved = 0
    for index, message in enumerate(messages):
        blocks = _blocks_of(message) if index < cut else None
        if blocks is None:
            out.append(message)
            continue
        if not any(_trimmable(b, min_body) for b in blocks):
            out.append(message)
            continue
        fresh = []
        for block in blocks:
            if _trimmable(block, min_body) and (at_most is None or trimmed_count < at_most):
                block, freed = _trim_block(block)
                trimmed_count += 1
                saved += freed
            fresh.append(block)
        out.append(dict(message, content=fresh))
    return out, {"results": trimmed_count, "characters": saved}


def window_tokens(usage) -> int:
    """How big the window that produced this response actually was.

    `input_tokens` alone is wrong wherever prompt caching is on, which is
    everywhere here: the cached part of the prompt is in the window and is
    deliberately not counted there. Cache reads and cache writes are both real
    input, so all three are added.
    """
    def number(name: str) -> int:
        value = getattr(usage, name, None)
        if value is None and isinstance(usage, dict):
            value = usage.get(name)
        return int(value or 0)

    return (number("input_tokens") + number("cache_read_input_tokens")
            + number("cache_creation_input_tokens"))


#: How many tokens each model can read at once, by the start of its id, like
#: `costs.PRICES`. A model not named here is taken to be the smaller size,
#: because the only cost of guessing low is a cache written again.
WINDOWS = {
    "claude-opus-5-5": 1_000_000,
    "claude-opus-5": 1_000_000,
    "claude-opus-4-8": 1_000_000,
    "claude-opus-4-7": 1_000_000,
    "claude-opus-4-6": 1_000_000,
    "claude-fable-5": 1_000_000,
    "claude-fable-5-1": 1_000_000,
    "claude-sonnet-5": 1_000_000,
    "claude-sonnet-4-6": 1_000_000,
    "claude-haiku-4-5": 200_000,
    # OpenAI's GPT-6 Luna reads 922,000 tokens of input (`rouh/luna.py`).
    "gpt-6-luna": 922_000,
}
SMALLEST_WINDOW = 200_000

#: How full a model's window may get before a turn is trimmed part way through.
CEILING = 0.85


def ceiling(model: str) -> int:
    """The window, in tokens, past which a turn is trimmed between two requests.

    Only against running out of room altogether: well past any budget, and
    something only a long turn on a small model ever reaches. The person can
    pick Haiku 4.5, which reads 200,000 tokens, and a turn that reads a few
    large pages can get there.
    """
    name = str(model or "")
    best = ""
    for known in WINDOWS:
        if name.startswith(known) and len(known) > len(best):
            best = known
    return int(WINDOWS.get(best, SMALLEST_WINDOW) * CEILING)


def how_many_to_trim(window: int, budget: int) -> int:
    """How many results to take out of a window that has gone over budget.

    Gently: a few at a time, more the further over it is. Emptying the window
    the moment it crosses the line throws away context that was about to be
    used, and the next turn would have been under budget anyway.
    """
    if budget <= 0 or window <= budget:
        return 0
    over = window - budget
    return max(2, min(12, 2 + over // max(1, budget // 8)))


def describe(did: dict) -> str:
    """What a pass did, in a line, for the log and for the work tree."""
    if not did.get("results"):
        return ""
    many = "results" if did["results"] != 1 else "result"
    return (f"trimmed {did['results']} old tool {many} out of the context, "
            f"saving about {did['characters']:,} characters")
