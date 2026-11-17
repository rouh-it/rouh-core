"""What the model is sent of earlier turns: their tool calls whole, their results as stubs.

Petar, 17 November 2026, of a fork of General whose history had grown past what anybody reads twice: "let's
make it not include stuff that is pointless in including. maybe tool calls but tool results can be on demand
fetched by ai if it decides it needs to". So since that day, in every chat (General, a fork with what it
carries of its parent, a task's chat and a step's), what goes to the model of an earlier turn is:

- every tool call whole, its name and its arguments, so the model knows what it did;
- every tool result of 400 characters or more as a stub (`stub`): the tool's name, a line of what was there
  (its size, and its first line when it is Rouh's own words), and the id to get it back with, the
  `tool_use_id` of the call. The stub IS the tool_result, so every tool_use still has its tool_result and
  the three rules of `memory.Memory.history` hold as they did;
- a picture or a PDF the person attached before their last message as one line saying what it was and where
  it is saved, with the id to see it again (`file:<id>`).

`recall_result` (`tools.Tools._recall_result`) gives any of them back whole, from the database, and only from
the chat being answered and the chats it carries. The current turn's results are never stubbed: they are not
in the history, they are added to the request as they come, so a turn in progress works as it always did.
Nothing here writes to the database: the full result stays in the messages table, and the transcript on the
screen is untouched.

**The prompt cache.** A stub is made from the stored result alone, so it is the same words every time: a
result becomes a stub once, at the start of the turn after the one it came in, and every later request reads
it back out of the prompt cache the same (`rouh/promptcache.py`). Nothing is stubbed between two requests of
one turn, with one exception below.

**General's budget.** Until 17 November 2026 this module trimmed General alone, by age and by size, with a
placeholder of its own. The age pass is the stub now, in every chat (`lean`); what is left of the old module
is the size pass for General (`trim`, `how_many_to_trim`), which takes even the newest results of the history
down when the last request went past `context_budget_tokens`, and the ceiling (`ceiling`), the one time a
turn's own results are stubbed between two of its requests, when the window is about to be more than the
model can read at all. Both write the same stub, so there is one kind of stub and one tool to undo it.

The token numbers are the API's own, off `usage` on each response, not an estimate. :func:`window_tokens` is
what turns one of those into the size of the window that produced it: cached input is in the window and is
deliberately not in `input_tokens`.
"""
from __future__ import annotations

import json

#: The words every stub has, and only stubs: how a body already stubbed is known, so it is never stubbed
#: twice. In the text rather than in a field on the block: a tool_result goes to the Messages API as it is,
#: and the API refuses any field it does not know inside one ("tool_result.trimmed: Extra inputs are not
#: permitted").
MARK = "kept out of the context to save room"
#: What the trimming before 17 November 2026 said, never stored, recognised still so nothing is done twice.
OLD_MARK = "has been trimmed out of the context"

#: Below this a result is left whole. A stub is a couple of hundred characters, and stubbing a short answer
#: costs more than it saves; the short ones are the ones worth keeping anyway.
MIN_BODY = 400

#: How many messages at the end of the window keep their tool results whole in General's size pass.
KEEP_MESSAGES = 6

#: The tool that gives a stub back whole (`tools.Tools._recall_result`).
RECALL = "recall_result"
#: The id a file attached in an earlier turn is recalled by: this, then the attachment's own id.
FILE_ID = "file:"
#: The most of a first line quoted in a stub.
GIST_CHARS = 120


def _body_size(content) -> int:
    if isinstance(content, str):
        return len(content)
    try:
        return len(json.dumps(content))
    except (TypeError, ValueError):
        return len(str(content))


def _text_of(content) -> tuple[str, int]:
    """The words of a result and how many pictures or documents are in it."""
    if isinstance(content, str):
        return content, 0
    words, shown = [], 0
    for b in content if isinstance(content, list) else []:
        if isinstance(b, dict) and b.get("type") == "text":
            words.append(str(b.get("text") or ""))
        elif isinstance(b, dict) and b.get("type") in ("image", "document", "attachment"):
            shown += 1
    return "\n".join(words), shown


def _size_said(n: int) -> str:
    if n < 1024:
        return f"{n} characters"
    if n < 1024 * 1024:
        return f"{n / 1024:.0f} KB"
    return f"{n / (1024 * 1024):.1f} MB"


def gist(name: str, content) -> str:
    """One line of what a result was, without a model: its lines and size, and its first line when the words
    are Rouh's own. Somebody else's words (an email, a page, an MCP server's answer, `untrusted.source_for`)
    are never quoted here: a first line out of its box would read as Rouh's."""
    from . import untrusted

    text, shown = _text_of(content)
    size = _body_size(content)
    lines = text.count("\n") + 1 if text else 0
    bits = [f"{lines} lines" if lines > 1 else "", _size_said(size)]
    if shown:
        bits.append(f"{shown} picture{'s' if shown != 1 else ''} or file{'s' if shown != 1 else ''}")
    said = ", ".join(b for b in bits if b)
    if untrusted.source_for(name) or "<untrusted-content-" in text:
        return said
    first = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
    if first:
        if len(first) > GIST_CHARS:
            first = first[:GIST_CHARS].rstrip() + "..."
        said += f', beginning "{first}"'
    return said


def stub(name: str, block: dict) -> str:
    """The words a tool result is sent as once it is earlier history. The same for the same stored result,
    always: that is what keeps the prompt cache reading it back (module docstring)."""
    what = "failed result" if block.get("is_error") else "result"
    tool = name or "a tool"
    return (f"[Earlier {what} of {tool}, {MARK}: {gist(name, block.get('content'))}. "
            f'Call {RECALL} with id "{block.get("tool_use_id") or ""}" to read it whole.]')


def _stub_block(block: dict, name: str) -> tuple[dict, int]:
    """One tool_result with its body replaced by its stub. Returns it and the characters that saved."""
    size = _body_size(block.get("content"))
    out = dict(block)
    out["content"] = stub(name, block)
    # A stubbed error is no longer an error the model has to act on, and leaving the flag set makes every
    # later turn treat the stub as a live failure. The words still say it failed.
    out.pop("is_error", None)
    return out, max(0, size - len(out["content"]))


def _field(block, name: str):
    return block.get(name) if isinstance(block, dict) else getattr(block, name, None)


def tool_names(messages: list) -> dict[str, str]:
    """Each tool call's id, with the name of the tool it called, in these messages (an assistant turn of
    this request may be the SDK's objects rather than dictionaries)."""
    out: dict[str, str] = {}
    for m in messages:
        if _field(m, "role") != "assistant":
            continue
        content = _field(m, "content")
        for b in content if isinstance(content, list) else []:
            if _field(b, "type") in ("tool_use", "server_tool_use") and _field(b, "id"):
                out[str(_field(b, "id"))] = str(_field(b, "name") or "")
    return out


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
    return isinstance(content, str) and (MARK in content or OLD_MARK in content)


def _loads_tools(content) -> bool:
    """Whether a result is a search's answer, the tools it loaded.

    Never trimmed, however old: its `tool_reference` blocks are what keep
    those tools loaded for the rest of the conversation (`rouh/toolsearch.py`),
    and a placeholder in their place would unload them with nothing said.
    """
    return isinstance(content, list) and any(
        isinstance(b, dict) and b.get("type") == "tool_reference" for b in content)


def _shows_file(content) -> bool:
    """Whether a result carries a file (`untrusted.Blocks`): small as stored, a picture once sent."""
    return isinstance(content, list) and any(
        isinstance(b, dict) and b.get("type") in ("attachment", "image", "document") for b in content)


def _trimmable(block, min_body: int) -> bool:
    return (isinstance(block, dict)
            and block.get("type") == "tool_result"
            and not _already_trimmed(block.get("content"))
            and not _loads_tools(block.get("content"))
            and (_body_size(block.get("content")) >= min_body or _shows_file(block.get("content"))))


#: The files of an earlier turn that go as a line: pictures and PDFs, the heavy ones. A text file the person
#: attached is its words and stays.
def _heavy_file(block) -> bool:
    if not (isinstance(block, dict) and block.get("type") == "attachment"):
        return False
    if isinstance(block.get("made"), dict) and block["made"]:
        return False                     # already a line of words (`attachments._made_block`)
    from . import attachments

    return (block.get("kind") in ("image", "pdf")
            or str(block.get("media_type") or "") in attachments.CONVERTIBLE)


def file_stub(block: dict, store=None) -> dict:
    """A picture or PDF from an earlier turn, as the one line it is sent as: what it was, where it is saved,
    and the id to see it again with."""
    from . import attachments

    record = None
    if store is not None:
        try:
            record = store.get(str(block.get("session_id") or ""), str(block.get("id") or ""))
        except Exception:  # noqa: BLE001 - a line without its place is still a line
            record = None
    where = (record or {}).get("path") or ""
    what = "picture" if block.get("kind") != "pdf" else "PDF"
    size = attachments.human_size(int(block.get("size") or 0))
    text = (f"[Earlier the person attached the {what} {block.get('name') or 'a file'} ({size})"
            f"{', saved at ' + where if where else ''}. It is {MARK}: call {RECALL} with id "
            f'"{FILE_ID}{block.get("id") or ""}" to see it again.]')
    return {"type": "text", "text": text}


def _person_said(m) -> bool:
    """A message of the person's own, not a set of tool results."""
    if not isinstance(m, dict) or m.get("role") != "user":
        return False
    content = m.get("content")
    if not isinstance(content, list):
        return True
    return not any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content)


def lean(history: list, *, store=None, min_body: int = MIN_BODY) -> tuple[list, dict]:
    """The earlier turns of a conversation as the model is sent them: every tool result stubbed, and every
    picture or PDF before the person's last message a line (module docstring). Returns the new list and what
    it did. The caller's list and its messages are never changed: they are the database's."""
    names = tool_names(history)
    last = max((i for i, m in enumerate(history) if _person_said(m)), default=-1)
    out: list = []
    did = {"results": 0, "files": 0, "characters": 0}
    for index, message in enumerate(history):
        blocks = _blocks_of(message)
        if blocks is None or message.get("role") != "user":
            out.append(message)
            continue
        if not any(_trimmable(b, min_body) or (index != last and _heavy_file(b)) for b in blocks):
            out.append(message)
            continue
        fresh = []
        for block in blocks:
            if _trimmable(block, min_body):
                block, freed = _stub_block(block, names.get(str(block.get("tool_use_id") or ""), ""))
                did["results"] += 1
                did["characters"] += freed
            elif index != last and _heavy_file(block):
                block = file_stub(block, store)
                did["files"] += 1
            fresh.append(block)
        out.append(dict(message, content=fresh))
    return out, did


def trim(messages: list, *, keep_messages: int = KEEP_MESSAGES,
         min_body: int = MIN_BODY, at_most: int | None = None) -> tuple[list, dict]:
    """Stub more results, for General's budget and the ceiling (module docstring). Returns the new message
    list and what it did.

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
    names = tool_names(messages)
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
                block, freed = _stub_block(block, names.get(str(block.get("tool_use_id") or ""), ""))
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
