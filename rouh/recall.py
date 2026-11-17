"""`recall_result`: an earlier tool result, or an earlier picture, given back whole.

Since 17 November 2026 every chat is sent the tool results of its earlier turns as stubs, and the pictures
and PDFs the person attached before their last message as lines (`context_editing.lean`). Each stub names an
id: a tool result's is the `tool_use_id` of the call it answered, a file's is `file:` and the attachment's id.
This is what the model calls with that id when it needs the thing itself again. It only reads.

What it may read is the chat being answered and the chats that chat carries, up to where each was forked
(`chain`), which is exactly where a stub it was shown can have come from: never another chat of the person's,
and a chat that has Parent chat history turned off carries nothing, so it recalls nothing of its parent. A
reader a page was shared with is never answered here: their chat is Ask AI's own sealed path, with no tool of
Rouh's (`rouh/page_in_chat.py`).
"""
from __future__ import annotations

import json
import logging
import re

log = logging.getLogger("rouh.recall")

#: The most of one result given back in one call, in characters; the rest is had with `offset`.
PART = 100_000
#: The most messages read for one id.
MOST_ROWS = 200
#: What an id may look like: a tool call's id from either provider, or `file:` and an attachment's.
_ID = re.compile(r"^[A-Za-z0-9_.:\-]{4,160}$")


def chain(chat_id: str) -> list[tuple[str, int | None]]:
    """(chat, the last message of it carried, or None for all of it): this chat, then each it carries."""
    from . import forks, reading

    out: list[tuple[str, int | None]] = [(chat_id, None)]
    if not chat_id or not reading.carries_parent(chat_id):
        return out
    here = chat_id
    seen = {chat_id}
    for _ in range(forks.DEEP):
        got = forks.carried(here)
        if got is None or got[0] in seen:
            break
        parent, at = got
        out.append((parent, at))
        seen.add(parent)
        here = parent
    return out


def _rows(chat: str, upto: int | None, needle: str) -> list[str]:
    """The stored content of this chat's live messages holding `needle`, newest first, as far as it is
    carried: up to the exchange of message `upto`, the way `memory.Memory._window` carries it."""
    from .memory import _exchange
    from .models.memory import TranscriptMessage

    rows = TranscriptMessage.objects.filter(session_id=chat, live=True, content__contains=needle)
    if upto is not None:
        edge = (TranscriptMessage.objects.filter(id=upto).annotate(ex=_exchange())
                .values_list("ex", flat=True).first())
        rows = (rows.annotate(exchange=_exchange()).filter(exchange__lte=edge) if edge is not None
                else rows.filter(id__lte=upto))
    # Newest first, and enough of them: a recalled id is quoted again by the turn that recalled it, which must
    # not push the call that made it out of reach.
    return list(rows.order_by("-id").values_list("content", flat=True)[:MOST_ROWS])


def _blocks(raw: str) -> list:
    try:
        got = json.loads(raw)
    except (TypeError, ValueError):
        return []
    return got if isinstance(got, list) else []


def find_result(chat_id: str, call_id: str) -> tuple[str, object, bool] | None:
    """(the tool's name, the result's content as stored, whether it failed), or None when no chat in reach
    holds it."""
    for chat, upto in chain(chat_id):
        name = ""
        result = None
        for raw in _rows(chat, upto, call_id):
            for b in _blocks(raw):
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "tool_result" and b.get("tool_use_id") == call_id and result is None:
                    result = b
                elif b.get("type") in ("tool_use", "server_tool_use") and b.get("id") == call_id:
                    name = str(b.get("name") or "")
        if result is not None:
            return name, result.get("content"), bool(result.get("is_error"))
    return None


def find_file(chat_id: str, att_id: str) -> dict | None:
    """The marker of a file the person attached, in a chat in reach, or None."""
    for chat, upto in chain(chat_id):
        for raw in _rows(chat, upto, att_id):
            for b in _blocks(raw):
                if isinstance(b, dict) and b.get("type") == "attachment" and b.get("id") == att_id:
                    return b
    return None


def answer(chat_id: str, which: str, offset: int = 0, store=None):
    """What `recall_result` answers: the result's words (a part of them, past `offset`, when long), its
    blocks with any file in them (`untrusted.Blocks`), or a sentence saying why there is nothing."""
    from . import attachments, untrusted

    which = (which or "").strip().strip('"')
    if not _ID.match(which):
        return "Give the id exactly as the stub names it, such as toolu_01AbC or file:a1b2c3."
    if which.startswith("file:"):
        marker = find_file(chat_id, which[len("file:"):])
        if marker is None:
            return f"No file {which} was attached in this chat or in the conversation it carries."
        record = store.get(str(marker.get("session_id") or ""), str(marker.get("id") or "")) if store else None
        said = (f"The {'PDF' if marker.get('kind') == 'pdf' else 'picture'} {marker.get('name') or ''} the person "
                f"attached earlier, shown again below.")
        return untrusted.Blocks([{"type": "text", "text": said},
                                 attachments.marker(record) if record else dict(marker)], said=said)
    got = find_result(chat_id, which)
    if got is None:
        return (f"No tool result {which} is in this chat or in the conversation it carries. Use the id the stub "
                "names; a result from another chat cannot be recalled here.")
    name, content, failed = got
    head = f"The {'failed ' if failed else ''}result of {name or 'a tool'} ({which}), as it came back:"
    if isinstance(content, list):
        return untrusted.Blocks([{"type": "text", "text": head}, *content], said=head)
    text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
    offset = max(0, int(offset or 0))
    raw = text[offset:offset + PART]
    if offset == 0 and len(text) <= PART:
        return f"{head}\n{text}"
    end = offset + len(raw)
    # A part of somebody else's words is boxed again: its box's opening or closing is in another part.
    if "<untrusted-content-" in text or untrusted.source_for(name):
        raw = untrusted.wrap(raw, untrusted.source_for(name) or "an earlier tool result quoting somebody else")
    more = (f"\n[Characters {offset:,} to {end:,} of {len(text):,}. Call recall_result again with offset "
            f"{end} for the rest.]" if end < len(text) else f"\n[The last part, to character {len(text):,}.]")
    return f"{head} part from character {offset:,}\n{raw}{more}"
