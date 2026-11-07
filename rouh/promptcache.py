"""Where the prompt cache's breakpoints go, so a turn's round trips are cheap.

The Messages API keeps no state. A spoken turn that uses tools makes one
request per round of tools, often seven or more, and every one of them sends
the whole conversation again. That cannot be avoided, but paying full price
for it can: a prefix the API has seen in the last few minutes is read out of
its cache for a small fraction of the input price, and only what is new after
it is billed in full.

Caching is a prefix match, and only at the blocks marked with `cache_control`
(a breakpoint). So the whole of this is two rules.

- Mark the right blocks. Three places at most, one fewer than the four the API
  allows: the end of the system prompt (which caches the tools with it), the
  end of the conversation as it stood when the turn began, and the newest
  message of each request. The first is shared by every turn and every chat;
  the second is written once a turn and read by each of its round trips; the
  third moves along with the round trips, so each one reads what the one
  before it sent.
- Never change what is in front of a mark. One byte different anywhere before
  a breakpoint and the cache misses from that byte on, silently: the turn
  still works, it just costs what it did before. That is why the clock is not
  in the cached part of the system prompt, and why old tool results are only
  trimmed where a turn begins (`rouh/context_editing.py`).

Nothing here changes a message the caller holds. The marks are on copies,
made for the one request, because the list they are made from goes on to the
next round, and a mark left behind on an old block is a fifth breakpoint and
a 400.
"""
from __future__ import annotations

#: The mark for a prefix that is read again within minutes: every round trip
#: of a turn is.
BRIEF = {"type": "ephemeral"}

#: The mark for the system prompt and the tools, which are the same for every
#: turn of every chat and are the largest part of every request. Written at
#: twice the input price rather than a quarter more, and kept an hour rather
#: than five minutes. Petar's turns are mostly more than five minutes apart
#: and less than an hour (in the week to 26 September 2026, 197 gaps of 5 to
#: 60 minutes against 26 longer), so on the five-minute mark this block was
#: written again on most turns instead of being read.
#:
#: An hour-long entry has to come before any five-minute one in a request,
#: which the system prompt always does.
LONG = {"type": "ephemeral", "ttl": "1h"}

#: The most breakpoints one request may carry. The API refuses a fifth.
MOST = 4


def marked(messages: list, anchor: int | None = None) -> list:
    """The conversation as one request carries it, with its breakpoints.

    `anchor` is the index of the last message the turn began with: the
    person's words, or the note after them. Its last block is marked, and so
    is the last block of the newest message when that is one of ours. On the
    first request of a turn they are the same block, and that is one mark.

    The newest message is only marked when it is a user message, which is a
    list of plain blocks this process built: the person's words or a round of
    tool results. After a `pause_turn` the newest is the model's own reply,
    and the API puts a breakpoint after a server tool's results by itself.

    Returns a new list. The messages that carry a mark are copies; every
    other message is the very object it was.
    """
    out = list(messages)
    wanted = set()
    if anchor is not None and 0 <= anchor < len(out):
        wanted.add(anchor)
    if out and _role(out[-1]) == "user":
        wanted.add(len(out) - 1)
    for index in wanted:
        out[index] = _with_mark(out[index])
    return out


def _role(message) -> str:
    return message.get("role", "") if isinstance(message, dict) else ""


def _with_mark(message, mark: dict = BRIEF):
    """A copy of `message` whose last block carries `mark`, or the message
    itself when it has no block a mark may go on."""
    if not isinstance(message, dict):
        return message
    content = message.get("content")
    if isinstance(content, str):
        # A plain string is one text block on the wire, so it becomes one
        # here to carry the mark. An empty one is refused by the API with or
        # without a mark, and is left for that to say.
        if not content:
            return message
        return {**message, "content": [{"type": "text", "text": content,
                                        "cache_control": dict(mark)}]}
    if not isinstance(content, list) or not content:
        return message
    last = content[-1]
    # Only a block this process wrote as a dict: the SDK's own objects are the
    # model's reply, and are never rebuilt (`context_editing._blocks_of`).
    if not isinstance(last, dict) or last.get("type") not in MARKABLE:
        return message
    if last.get("type") == "text" and not last.get("text"):
        return message
    return {**message, "content": [*content[:-1], {**last, "cache_control": dict(mark)}]}


#: The kinds of block a breakpoint may go on that a user message carries.
MARKABLE = frozenset({"text", "image", "document", "tool_result"})
