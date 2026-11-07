"""Anthropic's own tool calls and their results, kept together the way the API wants them.

Web search, web fetch, the tool search and code execution run on Anthropic's
side. Each is a `server_tool_use` block in the model's reply and a result
block that names it (`web_fetch_tool_result`, `tool_search_tool_result`, ...),
and the API refuses any request in which a call has lost its result:

    messages.23: `web_fetch` tool use with id `srvtoolu_...` was found without
    a corresponding `web_fetch_tool_result` block

A call usually has its result beside it, in the same reply. Not always. When
the model asks for one of Anthropic's tools and one of Rouh's in the same
reply, the API stops for Rouh's (`stop_reason` "tool_use") with its own call
not yet run, and runs it once Rouh's results come back: the next reply opens
with its result. So a call may also be answered by the reply after the one it
is in, and while a turn is still going it may be waiting, in the newest reply,
for the results Rouh is about to send. That waiting is only taken up when the
message after it is nothing but tool results. On 5 and 6 October 2026 the
Synapse seeds that came back too late for a turn's first request were added
after those results as a line of text (`late_seeds` in `rouh/brain.py`), and
the API refused the request, four turns in four chats; the reply holding the
waiting call had been stored, so the next turn of that chat was refused too.

`repair` is what makes any of that answerable again: a call with no result
where the API will look for one is taken out, and so is a result whose call is
gone, with a warning in the log. It never adds or removes a message, only
blocks inside one, so an index into the list (the cache anchor) still points at
the same message. `pending` says which calls of a reply are still waiting, so
nothing is put after its tool results.
"""
from __future__ import annotations

import logging

log = logging.getLogger("rouh.servercalls")

#: A call made on Anthropic's side.
CALL = "server_tool_use"

#: Result blocks whose names end like Anthropic's but that answer something
#: else: Rouh's own tools, and an MCP server's, which has its own call block.
_NOT_SERVER = ("tool_result", "mcp_tool_result")

#: Blocks that are the model thinking, which on their own are not a reply.
_THINKING = ("thinking", "redacted_thinking")


def _get(block, key: str):
    """A field of a block, whether it is a dict or one of the SDK's objects."""
    if isinstance(block, dict):
        return block.get(key)
    return getattr(block, key, None)


def is_result(block) -> bool:
    """Whether a block is what one of Anthropic's own calls gave back."""
    kind = _get(block, "type")
    return (isinstance(kind, str) and kind.endswith("_tool_result")
            and kind not in _NOT_SERVER)


def _calls(content) -> list:
    return [b for b in _blocks(content) if _get(b, "type") == CALL]


def _answered(content) -> set:
    return {_get(b, "tool_use_id") for b in _blocks(content) if is_result(b)}


def _blocks(content) -> list:
    return content if isinstance(content, list) else []


def pending(content) -> list[str]:
    """The ids of the calls of Anthropic's in this reply with no result in it yet."""
    done = _answered(content)
    return [_get(b, "id") for b in _calls(content) if _get(b, "id") not in done]


def _only_results(message) -> bool:
    """A user message that is tool results and nothing else, so a call waiting
    in the reply before it is run when it is sent."""
    if not isinstance(message, dict) or message.get("role") != "user":
        return False
    blocks = _blocks(message.get("content"))
    return bool(blocks) and all(_get(b, "type") == "tool_result" for b in blocks)


def _answer_after(messages: list, i: int) -> int | None:
    """The index of the reply that answers a call left waiting in reply `i`:
    the next message, if it is only tool results, then the reply after it."""
    if (i + 2 < len(messages) and _only_results(messages[i + 1])
            and messages[i + 2].get("role") == "assistant"):
        return i + 2
    return None


def orphans(messages: list, *, in_flight: bool = False) -> list[tuple[int, str, str]]:
    """Every call the API would refuse, as (message index, call id, tool name).

    `in_flight` is a turn's own list between two of its requests, where the
    newest reply may still be waiting on its calls: they are run when the
    request goes out, if nothing but tool results follows them, and after a
    `pause_turn`, when the reply is itself the last message.
    """
    found = []
    last = len(messages) - 1
    for i, message in enumerate(messages):
        if not isinstance(message, dict) or message.get("role") != "assistant":
            continue
        waiting = pending(message.get("content"))
        if not waiting:
            continue
        nxt = _answer_after(messages, i)
        later = _answered(messages[nxt].get("content")) if nxt is not None else set()
        on_its_way = in_flight and (i == last or (i == last - 1 and _only_results(messages[last])))
        names = {_get(b, "id"): _get(b, "name") for b in _calls(message.get("content"))}
        for call_id in waiting:
            if call_id in later or on_its_way:
                continue
            found.append((i, call_id, names.get(call_id) or "?"))
    return found


def repair(messages: list, *, in_flight: bool = False, where: str = "") -> list:
    """`messages` with every call that lost its result taken out, and every
    result whose call is not there for it. The same list when nothing was
    wrong, and never the caller's own messages changed in place.

    `where` names the chat in the warning.
    """
    lost = orphans(messages, in_flight=in_flight)
    dropping: dict[int, set] = {}
    for i, call_id, name in lost:
        dropping.setdefault(i, set()).add(call_id)
        log.warning("%s: the %s call %s in message %d has no result where the API "
                    "looks for one; sent without it", where or "a request", name, call_id, i)
    # Which calls each result may answer once those are gone: one in its own
    # reply, or one left waiting in the reply before the tool results it follows.
    out = list(messages)
    changed = bool(dropping)
    for i, message in enumerate(messages):
        if not isinstance(message, dict) or message.get("role") != "assistant":
            continue
        blocks = _blocks(message.get("content"))
        gone = dropping.get(i, set())
        kept = [b for b in blocks
                if not (_get(b, "type") == CALL and _get(b, "id") in gone)]
        asked = {_get(b, "id") for b in kept if _get(b, "type") == CALL}
        if i >= 2 and _answer_after(messages, i - 2) == i:
            asked |= {_get(b, "id") for b in _calls(messages[i - 2].get("content"))
                      if _get(b, "id") not in dropping.get(i - 2, set())}
        stray = [b for b in kept if is_result(b) and _get(b, "tool_use_id") not in asked]
        for b in stray:
            log.warning("%s: %s for %s answers no call in front of it; sent without it",
                        where or "a request", _get(b, "type"), _get(b, "tool_use_id"))
        if stray:
            kept = [b for b in kept if not any(b is s for s in stray)]
        if len(kept) == len(blocks):
            continue
        # Thinking with nothing after it is not a reply either.
        if all(_get(b, "type") in _THINKING for b in kept):
            kept = []
        out[i] = dict(message, content=kept)
        changed = True
    return out if changed else messages
