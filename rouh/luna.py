"""Luna, OpenAI's model, answering Rouh's own spoken turn instead of Claude.

Petar, 26 September 2026: "Give me the option to use Luna from OpenAI instead
of the listed three models of Anthropic. I will add an API key if you don't
have one. Consider all code you have written so far, we don't want to break
something. Tool search for example, caching, tool use, etc in that feature."

So a turn asked of `gpt-6-luna`, or of any of OpenAI's models a tier can be
(`rouh/modeldefaults.py`), comes here instead of going through the loop in `brain.py`. It is
a loop of its own rather than a branch inside that one, on purpose: the
Anthropic loop is unchanged by a single line of behaviour, and everything this
file cannot do the same way is said here rather than hidden in an `if`.

It talks to OpenAI's Responses API, streamed, because that is the one OpenAI
says tool calling and its own web search need on the GPT-6 models (Chat
Completions calls a function only with reasoning turned off). Every piece of
Rouh's turn, and what it is on this side:

- **Tools.** Every tool Rouh has, from the same registry (`tools.py`), each
  declared as a function with its own JSON schema, `strict` off so an optional
  field stays optional. They run through the very same `Brain._run_tools`, so
  the untrusted-content boxes, the tools that have to be asked about, a mail
  turn's short list, the orb's twigs and the lines on screen are one code path
  for both models.
- **Tool search.** As for Claude, every tool is declared and none is loaded
  until the model searches for it (`rouh/toolsearch.py`): the functions are
  grouped into one namespace per area and deferred, the catalogue in the
  instructions names every one, and OpenAI's own `tool_search` loads them -
  run on OpenAI's side, or here when `ROUH_TOOL_SEARCH=client`, or not at
  all with `off`, the same three choices Claude has. No area is named after
  one of OpenAI's own namespaces, such as `web` or `browser`: the API refuses
  the whole request for one (`toolsearch.AREAS`).
- **The web.** Anthropic's web_search and web_fetch become OpenAI's own
  `web_search`, which runs on OpenAI's side the way Anthropic's did on
  Anthropic's, and both searches and opens a page. Its calls are drawn on the
  screen and the orb like any other: a search as web_search with its query and
  the pages it found, a page it opened as web_fetch with its address. The
  prompt says there is one web tool rather than two (`brain.WEB_LUNA`).
- **Footnotes.** OpenAI hangs each page on the words written from it as a
  `url_citation`. They become the same `[1]` after the words and the same
  Sources list under them (`citing.py`), live and after a reload, and are kept
  on the stored answer in a shape of their own that is taken off before the
  chat is ever sent to Claude (`citing.for_anthropic`).
- **Its own name.** Claude knows it is Claude; Luna is told, under the name
  Rouh, that it is Luna (`brain.MODEL_LUNA`), because asked which model it
  was it said it could not tell.
- **Turn marks.** The same three marks, the same instructions, read the same
  way off the front of the reply (`turnmarks.Reading`), per message, because
  an OpenAI response can hold more than one.
- **Speech.** The words are cut into sentences and spoken as they arrive, by
  the same splitter.
- **Reasoning.** `reasoning.effort`, the level of the kind of chat it is
  answering in: General's, or the default's (`rouh/modeldefaults.py`). OpenAI's reasoning is carried across the tool
  calls of one turn as its encrypted items, handed back with the tool results
  as OpenAI asks, and like Claude's thinking it is never spoken, never shown
  and never stored: it belongs to the turn it happened in.
- **Caching.** OpenAI caches the front of a prompt by itself, at the end of the
  newest message, with nothing to mark and nothing to ask for. What Claude's
  loop does by hand to keep a prefix the same (`rouh/promptcache.py`) is done
  here the same way: the instructions are the part of the system prompt that
  never changes, the clock goes in a message of its own after the person's
  words rather than in front of everything, and old tool results are trimmed
  only where a turn begins. Each request's reads and writes are counted, and
  the cached share and what it cost are on the line under the answer as for
  Claude (`costs.py`).
- **Context trimming, attachments, stop, retries, the orb's line for the
  turn, the question written down once, the note when a turn is stopped** -
  the same functions as the Anthropic loop, called from here.

What has no match on this side, and what happens instead:

- **Code execution in a sandbox.** Off for Claude too unless ROUH_CODE_EXEC is
  set; on Luna it is simply not offered.
- **Anthropic's `pause_turn` and code-execution containers.** Anthropic's own
  machinery; OpenAI's hosted search finishes inside the response.
- **No fallback model.** A Luna turn that cannot be answered says so, the way
  a Claude one does: since the evening of 18 October 2026 no turn falls back to
  another model at all (`brain.Brain.run_turn`).
- **look_into.** The helper is Anthropic's own loop and asks its own use's
  model, an Anthropic one (`modeldefaults.USES`, subagent); a Luna turn can
  still call it, and gets its answer.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import re
import time
from types import SimpleNamespace

from . import (attachments, chatkinds, citing, context_editing, costs, llmlog, modelstandard, replymode, retrying,
               toolsearch, turnmarks, worklabel)
from .brain import (_first_of, _is_stopped, _let_it_finish, _said_timing, _shallow, _shows_files,
                    _split_sentences, _Stopped, _timed, _without_marks)

log = logging.getLogger("rouh.luna")

#: What OpenAI takes for `reasoning.effort` on GPT-6 Luna.
EFFORTS = ("none", "low", "medium", "high", "xhigh", "max")

#: What each request asks to be given back beside the answer: the reasoning,
#: encrypted, so it can be handed back with the tool results of the same turn
#: (nothing is stored on OpenAI's side, `store` is off), and every page a
#: search went through, for its line on the screen.
INCLUDE = ["reasoning.encrypted_content", "web_search_call.action.sources"]

#: A function's name, as OpenAI takes one.
_NAME = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


#: The key the raw OpenAI items of a response ride on, beside the stored shape
#: of the same response, for as long as the turn lasts. Never in the database.
ITEMS = "_luna_items"

#: The longest a function's description is sent when OpenAI has refused a
#: longer one. It has refused 1,024 characters and more on older APIs; nothing
#: says the Responses API does, so descriptions go whole and are only cut, with
#: the rest moved into the instructions, after a refusal that says so.
DESCRIPTION_MAX = 1024


_client = None
_client_key = ""


def client_for(cfg):
    """OpenAI's client, one per key, made on first use.

    `max_retries=0` for the reason Anthropic's has it (`brain.Brain`): the
    retry policy is `retrying.py`'s, which knows whether a reply has already
    been spoken. The address is the SDK's own, or `OPENAI_BASE_URL`, which is
    how the stand-in in `rouh/testing/fake_openai.py` is put in front of it.
    """
    global _client, _client_key
    key = getattr(cfg, "openai_api_key", "")
    if _client is None or key != _client_key:
        # Every request it sends is written down, as Claude's are (`llmlog.py`).
        _client = llmlog.openai_client(key, max_retries=0)
        _client_key = key
    return _client


def effort_of(level: str, model: str = "") -> str:
    """How deeply an OpenAI model reasons: the level that comes with it
    (`modelstandard.effort`), or medium for a word OpenAI does not take.

    The GPT-6 models take every level; the GPT-5 ones on the list
    (`config.OPENAI_CHOICES`) stop at xhigh, so max is asked of them as xhigh."""
    said = (level or "").strip().lower()
    said = said if said in EFFORTS else "medium"
    if said == "max" and (model or "").startswith("gpt-5"):
        return "xhigh"
    return said


# --- the tools -------------------------------------------------------------

_left_out: set[str] = set()


def _leave_out(name: str, why: str) -> None:
    if name not in _left_out:
        _left_out.add(name)
        log.info("Luna is not offered %s: %s", name or "a tool with no name", why)


def _schema(schema) -> dict:
    """A tool's input schema as OpenAI takes one: an object with properties."""
    out = dict(schema) if isinstance(schema, dict) else {}
    out.pop("$schema", None)
    out["type"] = "object"
    if not isinstance(out.get("properties"), dict):
        out["properties"] = {}
    return out


def tidied(tools: list[dict]) -> list[dict]:
    """The tool list with what OpenAI would refuse put right or left out.

    Each function's schema is an object with properties and no `$schema`
    (an MCP server's often has one), and a function whose name OpenAI will
    not take is left out, said once in the log, rather than costing every
    turn a 400.
    """
    out = []
    for tool in tools:
        if tool.get("type") == "function":
            if not _NAME.match(str(tool.get("name") or "")):
                _leave_out(str(tool.get("name") or ""), "OpenAI will not take that as a function's name")
                continue
            out.append(dict(tool, parameters=_schema(tool.get("parameters"))))
        elif tool.get("type") == "namespace":
            inner = tidied(list(tool.get("tools") or []))
            if inner:
                out.append(dict(tool, tools=inner))
        else:
            out.append(tool)
    return out


def shortened_tools(tools: list[dict]) -> tuple[list[dict], str]:
    """The tools with every long description cut, and the rest as instructions.

    Only ever used after OpenAI has refused a description as too long. Nothing
    a description says is lost: the whole of it goes into the instructions
    under the tool's name, and the cut one says where.
    """
    notes = []

    def cut(tool):
        said = tool.get("description") or ""
        if tool.get("type") == "function" and len(said) > DESCRIPTION_MAX:
            tail = " (The whole of what it is for is under Tool notes in the instructions.)"
            room = DESCRIPTION_MAX - len(tail)
            notes.append(f"{tool['name']}:\n{said}")
            return dict(tool, description=said[:room].rsplit(" ", 1)[0] + tail)
        if tool.get("type") == "namespace":
            return dict(tool, tools=[cut(t) for t in tool.get("tools") or []])
        return tool

    out = [cut(tool) for tool in tools]
    if not notes:
        return tools, ""
    return out, ("\n\nTool notes, the whole of what these tools are for:\n\n"
                 + "\n\n".join(notes))


# --- the conversation, as OpenAI's input -----------------------------------

def _get(thing, name: str, default=None):
    if isinstance(thing, dict):
        return thing.get(name, default)
    return getattr(thing, name, default)


def _as_data(value):
    """An SDK object as plain JSON data, with OpenAI's own field names."""
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json", exclude_none=True, by_alias=True)
    return value


_PDF_NAME = re.compile(r"^That is the PDF (.+?) \(")


def _user_parts(blocks: list) -> list[dict]:
    """A user message's own blocks, as the parts of one OpenAI message.

    Pictures go as pictures and PDFs as files, whole, the way
    `attachments.anthropic_blocks` made them for Claude; everything else that
    carries words goes as words.
    """
    parts: list[dict] = []
    for i, block in enumerate(blocks):
        kind = _get(block, "type")
        if kind == "text":
            words = str(_get(block, "text") or "")
            if words:
                parts.append({"type": "input_text", "text": words})
        elif kind == "image":
            source = _get(block, "source") or {}
            if _get(source, "type") == "base64":
                parts.append({"type": "input_image", "detail": "auto",
                              "image_url": f"data:{_get(source, 'media_type')};base64,"
                                           f"{_get(source, 'data')}"})
            elif _get(source, "url"):
                parts.append({"type": "input_image", "detail": "auto",
                              "image_url": str(_get(source, "url"))})
        elif kind == "document":
            source = _get(block, "source") or {}
            if _get(source, "type") == "base64":
                # Named by the sentence `attachments` writes after it, so the
                # model can say which file it is reading.
                after = blocks[i + 1] if i + 1 < len(blocks) else None
                found = _PDF_NAME.match(str(_get(after, "text") or ""))
                name = found.group(1) if found else "attachment.pdf"
                parts.append({"type": "input_file", "filename": name,
                              "file_data": f"data:{_get(source, 'media_type') or 'application/pdf'};"
                                           f"base64,{_get(source, 'data')}"})
            elif _get(source, "type") == "text" and _get(source, "data"):
                parts.append({"type": "input_text", "text": str(_get(source, "data"))})
            elif _get(source, "url"):
                parts.append({"type": "input_file", "file_url": str(_get(source, "url"))})
        elif kind == "attachment":
            parts.append({"type": "input_text",
                          "text": f"Attached file {_get(block, 'name') or ''}, not sent here."})
    return parts


def _output_of(content) -> str:
    """What a tool gave back, as the words OpenAI is handed."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        words = [str(_get(b, "text") or "") for b in content if _get(b, "type") == "text"]
        # A search Claude ran here itself, answered with the tools it loaded
        # (`toolsearch.anthropic_search_result`), said as what it did.
        loaded = [str(_get(b, "tool_name")) for b in content
                  if _get(b, "type") == "tool_reference"]
        if loaded:
            words.append("Loaded the tools " + ", ".join(loaded) + ".")
        if any(words):
            return "\n".join(w for w in words if w)
    try:
        return json.dumps(content)
    except (TypeError, ValueError):
        return str(content)


def _assistant_items(blocks, namespaces=None) -> list[dict]:
    """A stored answer, Claude's or Luna's, as the items OpenAI reads it as.

    Its words and its tool calls, in order. Claude's thinking and the calls and
    results of Anthropic's own web tools are left out: they are Anthropic's,
    OpenAI cannot read them, and what they found is in the words written from
    them.
    """
    if isinstance(blocks, str):
        return [{"type": "message", "role": "assistant", "content": blocks}] if blocks else []
    items: list[dict] = []
    words: list[str] = []

    def flush():
        text = "".join(words).strip()
        words.clear()
        if text:
            items.append({"type": "message", "role": "assistant", "content": text})

    for block in blocks or []:
        kind = _get(block, "type")
        if kind == "text":
            words.append(str(_get(block, "text") or ""))
        elif kind == "tool_use":
            flush()
            call = {"type": "function_call", "call_id": str(_get(block, "id")),
                    "name": str(_get(block, "name")),
                    "arguments": json.dumps(_get(block, "input") or {})}
            # In the namespace the function is declared in this time, which
            # is where OpenAI would have put it had it made the call itself.
            space = (namespaces or {}).get(call["name"])
            if space:
                call["namespace"] = space
            items.append(call)
    flush()
    return items


def to_input(messages: list, clock: str = "", after: int | None = None,
             namespaces=None) -> list[dict]:
    """The conversation, in Anthropic's shape as Rouh keeps it, as OpenAI input.

    What this turn's own responses said goes back exactly as OpenAI sent it
    (`ITEMS`), reasoning and all, because OpenAI asks for its reasoning items
    to be handed back with the results of the tools they called.

    `clock` is the line saying what time it is, which goes in as a message of
    Rouh's own straight after message number `after`, the person's words:
    after everything that is the same from one turn to the next, so that all
    of it is read out of the cache (the built-in rule "clock").
    """
    out: list[dict] = []
    for index, message in enumerate(messages):
        if index > 0 and index - 1 == after and clock:
            out.append({"role": "developer", "content": clock})
        role = _get(message, "role")
        content = _get(message, "content")
        if role == "assistant":
            raw = _get(message, ITEMS)
            out.extend(raw if raw is not None else _assistant_items(content, namespaces))
            continue
        if isinstance(content, str):
            if content:
                out.append({"role": "user", "content": content})
            continue
        blocks = list(content or [])
        shown: list = []
        for block in blocks:
            if _get(block, "type") == "tool_result":
                came = _get(block, "content")
                out.append({"type": "function_call_output",
                            "call_id": str(_get(block, "tool_use_id")),
                            "output": _output_of(came)})
                # A picture or a PDF a tool showed (`rouh/mail_pictures.py`): a function's output is
                # words only, so the file itself follows in the user's message, with its line.
                if isinstance(came, list) and any(_get(b, "type") in ("image", "document") for b in came):
                    shown.extend(b for b in came if _get(b, "type") in ("image", "document", "text"))
        parts = _user_parts(shown + [b for b in blocks if _get(b, "type") != "tool_result"])
        if parts:
            out.append({"role": "user", "content": parts})
    if clock and after is not None and after == len(messages) - 1:
        out.append({"role": "developer", "content": clock})
    return out


def _unreasoned(messages: list) -> list:
    """The window with this turn's reasoning items taken out, once.

    For the one case the retry below names: OpenAI refusing reasoning it gave
    back itself. The turn then carries on from the tool results, as a Claude
    turn does when its thinking cannot be handed back (`brain._unthought`).
    """
    out = []
    for message in messages:
        raw = _get(message, ITEMS)
        if raw is not None:
            message = {**message, ITEMS: [i for i in raw if _get(i, "type") != "reasoning"]}
        out.append(message)
    return out


def _for_input(item: dict) -> dict:
    """One of OpenAI's output items, as it is handed back next time.

    A search's full list of sources is for the screen, not for the model, and
    goes; everything else goes back as it came.
    """
    if item.get("type") == "web_search_call" and isinstance(item.get("action"), dict):
        action = {k: v for k, v in item["action"].items() if k != "sources"}
        return {**item, "action": action}
    return item


# --- what was written, as Rouh stores it ----------------------------------

def _segments(text: str, annotations) -> list[dict]:
    """One output text as text blocks, each with the pages it was written from.

    OpenAI marks a cited stretch by where it ends, in characters. The text is
    cut after each such place, and each piece carries the pages cited there,
    which is the shape Anthropic's own answers are stored in and so the shape
    `citing.footnoted` numbers an answer from.
    """
    ends: dict[int, list[dict]] = {}
    for note in annotations or []:
        note = _as_data(note)
        if not isinstance(note, dict) or note.get("type") != citing.LUNA_CITATION:
            continue
        url = str(note.get("url") or "")
        if not url:
            continue
        at = max(0, min(len(text), int(note.get("end_index") or 0)))
        here = ends.setdefault(at, [])
        if all(c["url"] != url for c in here):
            here.append({"type": citing.LUNA_CITATION, "url": url,
                         "title": str(note.get("title") or "")})
    blocks: list[dict] = []
    start = 0
    for at in sorted(ends):
        piece = text[start:at]
        if piece:
            blocks.append({"type": "text", "text": piece, "citations": ends[at]})
        elif blocks and blocks[-1].get("citations") is not None:
            blocks[-1]["citations"] += [c for c in ends[at] if c not in blocks[-1]["citations"]]
        start = at
    if text[start:]:
        blocks.append({"type": "text", "text": text[start:]})
    return blocks


def _unmarked(text: str) -> str:
    """A message's words with the turn mark taken off their front."""
    stripped = text.lstrip()
    if stripped[:1] in turnmarks.MARKS:
        return stripped[1:].lstrip(" ")
    return text


def stored(output: list[dict]) -> tuple[list[dict], list[tuple[dict, object]], str | None]:
    """A finished response as Rouh keeps it: blocks, the calls, and any refusal.

    The blocks are Anthropic's shapes, text with its citations and tool_use,
    so a chat reads the same whichever model answered it, and so either model
    can carry on a chat the other started. Reasoning and OpenAI's own search
    calls are not kept, for the reasons Claude's thinking and Anthropic's own
    search blocks are not: they belong to the turn.
    """
    blocks: list[dict] = []
    calls: list[tuple[dict, object]] = []
    refusal = None
    for item in output:
        kind = item.get("type")
        if kind == "message":
            first = True
            for part in item.get("content") or []:
                if part.get("type") == "refusal":
                    refusal = str(part.get("refusal") or "") or refusal
                    continue
                if part.get("type") != "output_text":
                    continue
                pieces = _segments(str(part.get("text") or ""), part.get("annotations"))
                if first and pieces:
                    pieces[0]["text"] = _unmarked(pieces[0]["text"])
                    # A second message in one response - after a search it ran
                    # itself - is a paragraph of its own, as it was on screen.
                    if blocks and blocks[-1].get("type") == "text" and pieces[0]["text"].strip():
                        pieces[0]["text"] = "\n\n" + pieces[0]["text"].lstrip()
                    first = False
                blocks.extend(p for p in pieces if p["text"].strip() or p.get("citations"))
        elif kind == "function_call":
            raw = str(item.get("arguments") or "")
            try:
                args = json.loads(raw) if raw.strip() else {}
            except ValueError:
                args = None
            blocks.append({"type": "tool_use", "id": str(item.get("call_id")),
                           "name": str(item.get("name")),
                           "input": args if isinstance(args, dict) else {}})
            calls.append((item, args))
    # Never an empty text block: Anthropic refuses one in a replayed chat, on
    # every later turn (`brain._without_marks` says how that was learned).
    blocks = [b for b in blocks if b.get("type") != "text" or b["text"].strip()]
    return blocks, calls, refusal


# --- failures ---------------------------------------------------------------

class LunaFailed(Exception):
    """A response that failed after it had started, said inside the stream.

    Shaped like the mid-stream failures `retrying.py` was written for: status
    200, because the stream had opened, and a `type` naming the reason in
    Anthropic's words where OpenAI's has one, so the same judgement decides
    whether it is tried again.
    """

    _TYPES = {"server_error": "api_error", "rate_limit_exceeded": "rate_limit_error",
              "server_is_overloaded": "overloaded_error", "overloaded": "overloaded_error",
              "timeout": "timeout_error"}

    def __init__(self, code: str, message: str):
        super().__init__(f"{code}: {message}" if code else message)
        self.code = code or ""
        self.message = message or ""
        self.type = self._TYPES.get(self.code, self.code)
        self.status_code = 200


def _failed_from(response) -> LunaFailed:
    error = _get(response, "error") or {}
    return LunaFailed(str(_get(error, "code") or "failed"),
                      str(_get(error, "message") or "the response failed"))


def _said_of(exc) -> str:
    return str(getattr(exc, "message", "") or exc)


def is_too_long_description(exc) -> bool:
    said = _said_of(exc).lower()
    return (retrying.status_of(exc) == 400 and "description" in said
            and ("too long" in said or "maximum length" in said
                 or "string_above_max_length" in said))


def is_bad_reasoning(exc) -> bool:
    said = _said_of(exc).lower()
    return (retrying.status_of(exc) == 400
            and ("reasoning" in said or "encrypted_content" in said))


def is_out_of_credit(exc) -> bool:
    return (getattr(exc, "code", None) == "insufficient_quota"
            or "insufficient_quota" in _said_of(exc))


def should_retry(exc, *, attempt: int, said_anything: bool) -> bool:
    """`retrying.should_retry`, less the one 429 that waiting does not fix."""
    if is_out_of_credit(exc):
        return False
    return retrying.should_retry(exc, attempt=attempt, said_anything=said_anything)


def friendly(exc) -> str:
    """The failure, in one sentence, for the screen and the voice."""
    status = retrying.status_of(exc)
    if is_out_of_credit(exc):
        return "My OpenAI account will not take the request: it has no credit left."
    if status == 401:
        return "My OpenAI API key is not being accepted."
    if status == 403:
        return "My OpenAI API key is not allowed to use Luna."
    if status == 404:
        return "Luna is not available to my OpenAI API key."
    if status == 429:
        return "Luna is rate limiting me. Give me a moment."
    if isinstance(exc, LunaFailed):
        return "Luna stopped part way through: " + (exc.message or exc.code or "no reason given") + "."
    if retrying.is_failure_status(status):
        return f"The call to Luna failed ({status})."
    if type(exc).__name__ in ("APIConnectionError", "APITimeoutError"):
        return "I could not reach OpenAI to ask Luna."
    return "The call to Luna failed part way through, without saying why."


# --- the turn ---------------------------------------------------------------

def loaded_by(item: dict) -> list[str]:
    """The functions one of OpenAI's `tool_search_output` items loaded."""
    names = []
    for tool in item.get("tools") or []:
        if not isinstance(tool, dict):
            continue
        if tool.get("type") == "namespace":
            names += [str(t.get("name")) for t in tool.get("tools") or []
                      if isinstance(t, dict) and t.get("name")]
        elif tool.get("name"):
            names.append(str(tool["name"]))
    return names


def plan_for(entries, cfg) -> toolsearch.Plan:
    """What a Luna request declares: its tools, and the catalogue that lists them.

    The same choice Claude's requests make (`Config.tool_search`), in OpenAI's
    words: "off" sends every function whole; "client" declares OpenAI's
    `tool_search` to be run here; anything else, Claude's regex and BM25
    among them, is OpenAI's own search, run on its side.
    """
    wanted = (getattr(cfg, "tool_search", "regex") or "regex").strip().lower()
    mode = wanted if wanted in ("off", "client") else "hosted"
    always = getattr(cfg, "tools_always_loaded", ())
    tools = tidied(toolsearch.openai_tools(entries, mode=mode, always=always))
    return toolsearch.Plan(
        mode=mode, tools=tools,
        catalogue=toolsearch.catalogue(entries, mode=mode, provider="openai", always=always),
        declared={t.name for t in entries})


def namespaces_of(entries, plan) -> dict:
    """Which namespace each function is declared in, when they are namespaced."""
    if plan.mode == "off":
        return {}
    return {t.name: (t.area if t.area in toolsearch.AREA_KEYS else "other")
            for t in entries if t.portable}


def _web_name(action) -> str:
    """What one of OpenAI's search calls is on the screen and the orb.

    A page it opened is the same thing Anthropic's web_fetch was, and is drawn
    as that: the orange twig, "Reading" and the address. Everything else it
    does is a search.
    """
    return "web_fetch" if _get(action, "type") == "open_page" else "web_search"


def _web_args(action) -> dict:
    kind = _get(action, "type")
    if kind == "open_page":
        return {"url": str(_get(action, "url") or "")}
    if kind == "find_in_page":
        return {"query": str(_get(action, "pattern") or ""), "url": str(_get(action, "url") or "")}
    query = _get(action, "query") or " / ".join(str(q) for q in (_get(action, "queries") or []))
    return {"query": str(query or "")}


def _web_result(item: dict) -> dict:
    """What a search call came back with, for its line: like `brain._server_result`."""
    action = item.get("action") or {}
    ok = item.get("status") not in ("failed", "incomplete")
    if _web_name(action) == "web_fetch":
        url = str(action.get("url") or "")
        return {"ok": ok, "results": [{"title": citing.where(url), "url": url}] if url else [],
                "summary": citing.where(url) if url else ("done" if ok else "failed")}
    found = [s for s in (action.get("sources") or [])
             if isinstance(s, dict) and s.get("url")]
    results = [{"title": citing.where(str(s["url"])), "url": str(s["url"])[:2000]}
               for s in found[:20]]
    many = len(found)
    summary = ("failed" if not ok else "no results" if not many
               else "1 result" if many == 1 else f"{many} results")
    return {"ok": ok, "results": results, "summary": summary}


class _Turn:
    """One Luna turn: the state `Brain._turn` keeps in locals, kept here."""

    def __init__(self, brain, session_id, emit, on_sentence, model, stop, answer_now,
                 question, timing=None, began=None, entries=()):
        self.brain = brain
        self.cfg = brain.cfg
        self.session_id = session_id
        self.emit = emit
        self.on_sentence = on_sentence
        self.model = model
        self.stop = stop
        self.question = question
        self.client = client_for(brain.cfg)
        self.spoken_buffer = ""
        self.full_text: list[str] = []
        #: The words of the response streaming now, not yet in the database:
        #: what a stop has to store for itself (`Brain._abandon`).
        self.this_call: list[str] = []
        self.usage = {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0,
                      "cache_write_1h": 0, "trimmed": 0, "calls": []}
        #: Only the first reply of a turn judges the question, as in brain.py.
        self.judging = not answer_now
        #: How long each part of the turn took, in the shape `brain._timed`
        #: reads, filled in as for Claude.
        self.timing = timing if timing is not None else {
            "first_token": None, "first_text": None, "first_word": None,
            "requests": 0, "loaded": []}
        self.began = began if began is not None else time.monotonic()
        self.sent_at = time.monotonic()
        #: The turn's tools, for a search run here (`toolsearch.find`).
        self.entries = list(entries or ())
        #: Searches OpenAI asked this process to run, in the response now in.
        self.client_searches: list[dict] = []

    # -- one response, streamed -------------------------------------------

    async def pump(self, request: dict):
        """Stream one response, and give back the finished one.

        Cancelled by a stop, which leaves the `async with` and closes the
        stream: OpenAI stops being read and stops being paid for.
        """
        self.readings: dict[str, turnmarks.Reading] = {}
        self.first_message: str | None = None
        self.spoken_items: list[str] = []
        self.cited = citing.Numbering()
        self.marked: set[tuple] = set()
        self.searches: dict[str, str] = {}
        #: The tool searches on the screen still waiting for what they loaded.
        self.open_searches: list[str] = []
        self.client_searches = []
        final = None
        stream = await self.client.responses.create(**request)
        async with stream:
            async for event in stream:
                kind = getattr(event, "type", "")
                if self.timing.get("first_token") is None and kind in (
                        "response.output_item.added", "response.output_text.delta"):
                    self.timing["first_token"] = time.monotonic() - self.sent_at
                if kind == "response.output_text.delta":
                    await self._words(event.item_id, event.delta or "")
                elif kind == "response.output_text.annotation.added":
                    await self._footnote(event.item_id, event.content_index,
                                         event.annotation_index, _as_data(event.annotation))
                elif kind == "response.output_item.added":
                    await self._started(_as_data(event.item))
                elif kind == "response.output_item.done":
                    await self._finished(_as_data(event.item))
                elif kind in ("response.completed", "response.incomplete"):
                    final = event.response
                elif kind == "response.failed":
                    raise _failed_from(event.response)
                elif kind == "error":
                    raise LunaFailed(str(getattr(event, "code", "") or "error"),
                                     str(getattr(event, "message", "") or ""))
        if final is None:
            raise LunaFailed("unfinished", "the stream ended before the response did")
        return final

    async def _words(self, item_id: str, delta: str) -> None:
        reading = self.readings.get(item_id)
        if reading is None:
            reading = self.readings[item_id] = turnmarks.Reading()
            if self.first_message is None:
                self.first_message = item_id
        piece = reading.take(delta)
        if reading.unfinished and self.judging and item_id == self.first_message:
            # They had not finished asking: leave unread, say and keep nothing.
            raise turnmarks.Unfinished(reading.mark)
        if not piece:
            return
        # Their words are theirs from here: the mark said to answer.
        self.question.write()
        if self.timing.get("first_text") is None:
            self.timing["first_text"] = time.monotonic() - self.began
        if item_id not in self.spoken_items:
            if self.spoken_items:
                # A second message in the same response, after a search it
                # ran itself: a paragraph of its own, and a pause in the voice.
                piece = "\n\n" + piece.lstrip()
            self.spoken_items.append(item_id)
        self.full_text.append(piece)
        self.this_call.append(piece)
        await self.emit({"type": "assistant_delta", "text": piece})
        if self.on_sentence:
            self.spoken_buffer += piece
            sentences, self.spoken_buffer = _split_sentences(self.spoken_buffer)
            for sentence in sentences:
                await self.on_sentence(sentence)

    async def _footnote(self, item_id: str, part: int, index: int, note) -> None:
        """A page the words just written came from: its number, after them.

        On the screen and in the answer, never to the voice, as for Claude.
        """
        if not isinstance(note, dict) or note.get("type") != citing.LUNA_CITATION:
            return
        if (item_id, part, index) in self.marked or item_id not in self.spoken_items:
            # Numbered once; and never for words nobody was shown, which is
            # a message still holding its mark back.
            return
        self.marked.add((item_id, part, index))
        mark = self.cited.cite({"citations": [note]})
        # The same page twice at the same place is one number there.
        place = (item_id, part, note.get("end_index"), mark)
        if place in self.marked:
            return
        self.marked.add(place)
        if mark:
            self.full_text.append(mark)
            await self.emit({"type": "assistant_delta", "text": mark})

    async def _started(self, item: dict) -> None:
        if item.get("type") in ("tool_search_call", "web_search_call"):
            # Searching is answering, so the question is written before the
            # search's line is drawn and kept, and the line is read back under
            # it rather than above it, with the answer before (fr_f8a1bebc7237).
            self.question.write()
            self.judging = False
        if item.get("type") == "tool_search_call":
            # OpenAI looking for the tools it needs, on the screen and the
            # orb like Claude's search is (`toolsearch`).
            call_id = str(item.get("id"))
            self.open_searches.append(call_id)
            said = worklabel.describe_step("tool_search", None)
            await self.emit({"type": "tool_start", "id": call_id, "name": "tool_search",
                             "input": "", "what": said["what"], "detail": said["detail"],
                             "where": "rouh"})
            return
        if item.get("type") != "web_search_call":
            return
        name = _web_name(item.get("action"))
        self.searches[str(item.get("id"))] = name
        said = worklabel.describe_step(name, None)
        await self.emit({"type": "tool_start", "id": str(item.get("id")), "name": name,
                         "input": "", "what": said["what"], "detail": said["detail"],
                         "where": "rouh"})

    async def _finished(self, item: dict) -> None:
        kind = item.get("type")
        if kind == "tool_search_call":
            if str(item.get("id")) not in self.open_searches:
                await self._started(item)
            asked = item.get("arguments")
            said = worklabel.describe_step("tool_search", asked if isinstance(asked, dict) else None)
            await self.emit({"type": "tool_update", "id": str(item.get("id")),
                             "name": "tool_search", "input": _shallow(asked),
                             "what": said["what"], "detail": said["detail"], "where": "rouh"})
            if item.get("execution") == "client":
                # Ours to run: answered before the next request (`turn`).
                self.client_searches.append(item)
            return
        if kind == "tool_search_output":
            names = loaded_by(item)
            self.timing["loaded"] += names
            if self.open_searches:
                call_id = self.open_searches.pop(0)
                await self.emit({"type": "tool_end", "id": call_id, "name": "tool_search",
                                 "ok": True, "summary": toolsearch.said_loaded(names),
                                 "results": [{"title": n, "url": ""} for n in names],
                                 "where": "rouh"})
            return
        if kind == "message":
            # Footnotes the stream did not announce one by one: numbered now,
            # after the words, so none is lost.
            for part_index, part in enumerate(item.get("content") or []):
                for index, note in enumerate(part.get("annotations") or []):
                    await self._footnote(str(item.get("id")), part_index, index, note)
            return
        if kind != "web_search_call":
            return
        call_id = str(item.get("id"))
        action = item.get("action") or {}
        name = _web_name(action)
        if call_id not in self.searches:
            await self._started(item)
        args = _web_args(action)
        said = worklabel.describe_step(name, args)
        # What the call was really given, which it did not know when it
        # started. It can turn out to have been a page opened rather than a
        # search, and then its name moves with it (PROTOCOL.md, tool_update).
        await self.emit({"type": "tool_update", "id": call_id, "name": name,
                         "input": _shallow(args), "what": said["what"],
                         "detail": said["detail"], "where": "rouh"})
        came = _web_result(item)
        await self.emit({"type": "tool_end", "id": call_id, "name": name, "ok": came["ok"],
                         "summary": came["summary"], "results": came["results"],
                         "where": "rouh"})

    # -- a round of tools --------------------------------------------------

    async def run_calls(self, calls) -> list[dict]:
        """Every function Luna asked for, run the way Claude's calls are."""
        good = [SimpleNamespace(id=str(item.get("call_id")), name=str(item.get("name")),
                                input=args)
                for item, args in calls if isinstance(args, dict)]
        ran = await self.brain._run_tools(good, self.emit) if good else []
        by_id = {r["tool_use_id"]: r for r in ran}
        out = []
        for item, args in calls:
            call_id = str(item.get("call_id"))
            if isinstance(args, dict) and call_id in by_id:
                out.append(by_id[call_id])
            else:
                out.append({"type": "tool_result", "tool_use_id": call_id, "is_error": True,
                            "content": (f"{item.get('name')} was not run: what it was given "
                                        f"was not valid JSON ({str(item.get('arguments'))[:200]!r}).")})
        return out

    # -- the whole turn ----------------------------------------------------

    def count(self, response) -> int:
        """Add one response's tokens to the turn's, and say how big its window was.

        OpenAI's input count is every token sent, cached, written to the cache
        or neither; Rouh's is the ones that were neither, as Anthropic counts
        them, so the two are taken apart here.
        """
        usage = _get(response, "usage")
        if usage is None:
            return 0
        sent = int(_get(usage, "input_tokens") or 0)
        details = _get(usage, "input_tokens_details") or {}
        read = int(_get(details, "cached_tokens") or 0)
        wrote = int(_get(details, "cache_write_tokens") or 0)
        # One lifetime on OpenAI's side, so no hour-long writes to count.
        took = {"input": max(0, sent - read - wrote), "output": int(_get(usage, "output_tokens") or 0),
                "cache_read": read, "cache_write": wrote, "cache_write_1h": 0}
        for key in took:
            self.usage[key] += took[key]
        self.usage["calls"].append(took)
        log.info("request %d of the turn: %s", len(self.usage["calls"]), costs.call_said(took))
        self.usage["model"] = self.model
        return sent


async def turn(brain, session_id: str, user_content, emit, on_sentence, model: str,
               stop, answer_now: bool, question, *, rules=None, timing=None,
               began=None, level: str = "", seeds=None, recall=None, steer=None) -> str:
    """One turn, answered by Luna. What `Brain._turn` is for Claude.

    `rules` is the chat's kind (`chatkinds.profile`), `level` how deeply the
    model thinks (`modelstandard.effort`), and `timing` and `began` are
    the turn's clock, which `Brain._turn` has already started.
    """
    cfg = brain.cfg
    rules = rules or chatkinds.profile(session_id, cfg)
    # What this chat is sent, by its kind, exactly as for Claude.
    # On a thread, as the system prompt below: on the loop they held every tab,
    # and the answers being streamed to them, for as long as they took.
    history = await asyncio.to_thread(
        brain.memory.history, session_id, rules.history, before=question.slot.root,
        limit_of=lambda chat: chatkinds.profile(chat, cfg).history)
    log.info("a %s turn in %s, with %s of history, on %s",
             rules.kind, session_id,
             f"all {len(history)} messages" if rules.history < 0
             else f"the newest {len(history)} messages", model)
    messages = history + [{"role": "user", "content": user_content}]
    noted = answer_now and replymode.NOW.get().marks
    if noted:
        # On the request and never in the database, as for Claude.
        messages = messages + [{"role": "user", "content": turnmarks.ANSWER_NOW}]
    messages = attachments.hydrate(messages, brain.files)
    # Every tool declared, and none loaded until a search asks for it, as
    # for Claude (`plan_for`).
    entries = brain.tools.entries()
    plan = plan_for(entries, cfg)
    tools = plan.tools
    spaces = namespaces_of(entries, plan)
    # Once a turn, as for Claude. The part that never changes, catalogue and
    # all, is the instructions; the clock goes in after the person's words
    # (`to_input`).
    from .brain import late_memory, memory_for_turn
    found, remembered = await memory_for_turn(session_id, seeds, recall, began or time.monotonic())
    system = await asyncio.to_thread(brain._system, plan, openai=model or True, seeds=found,
                                     recall=remembered)
    instructions = system[0]["text"]
    clock = "\n\n".join(block["text"] for block in system[1:])
    notes = ""
    now = _Turn(brain, session_id, emit, on_sentence, model, stop, answer_now, question,
                timing=timing, began=began, entries=entries)
    # Trimmed where the turn begins, as for Claude: only General, by age, and
    # to the budget if its last request went past it (`Brain._edit_context`).
    windows = getattr(brain, "_windows", {})
    messages = await brain._edit_context(messages, emit, rules,
                                         window=windows.get(session_id, 0), usage=now.usage)
    # The person's words: where the clock goes, after everything the last
    # turn already sent.
    asked_at = len(history)
    effort = effort_of(level or modelstandard.effort(model), model)
    stopped = False
    cut_descriptions = False
    unreasoned = False

    def inputs():
        return to_input(messages, clock, asked_at, spaces)

    first = True
    while True:
        if _is_stopped(stop):
            stopped = True
            break
        # What the person sent while the turn was getting ready, under the
        # question and in front of the note asking for an answer now, as for
        # Claude (`Brain._take_steer`).
        if first and answer_now:
            taken = await brain._take_steer(session_id, question, steer, emit)
            if taken:
                if noted:
                    messages[-1:-1] = taken
                else:
                    messages.extend(taken)
        first = False
        request = {
            "model": model,
            "instructions": instructions + notes,
            "input": inputs(),
            "reasoning": {"effort": effort},
            "max_output_tokens": getattr(cfg, "luna_max_tokens", 32000),
            # Nothing kept on OpenAI's side: the conversation is Rouh's, in
            # its own database, and every request carries what it needs.
            "store": False,
            "include": INCLUDE,
            "stream": True,
        }
        if tools:
            request.update(tools=tools, tool_choice="auto", parallel_tool_calls=True)

        attempt = 0
        final = None
        #: Where this response's words start in the answer, for `exact` below.
        began_at = len(now.full_text)
        while True:
            attempt += 1
            said_before = len(now.full_text)
            now.this_call.clear()
            now.timing["requests"] = int(now.timing.get("requests") or 0) + 1
            now.sent_at = time.monotonic()
            # The request goes out inside `pump`, a task of its own, which
            # takes which try this is with it into the log of requests.
            with llmlog.about(attempt=attempt):
                reading = asyncio.ensure_future(now.pump(request))
            try:
                final = await _first_of(reading, stop)
                break
            except _Stopped:
                reading.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await reading
                stopped = True
                break
            except turnmarks.Unfinished:
                raise
            except Exception as exc:
                if not _is_openai_failure(exc):
                    raise
                spoke = len(now.full_text) > said_before
                if not spoke and not cut_descriptions and is_too_long_description(exc):
                    cut_descriptions = True
                    tools, notes = shortened_tools(tools)
                    request.update(tools=tools, instructions=instructions + notes)
                    log.warning("%s refused a tool description as too long; sending them "
                                "cut, with the rest in the instructions", model)
                    continue
                if not spoke and not unreasoned and is_bad_reasoning(exc):
                    unreasoned = True
                    messages = _unreasoned(messages)
                    request["input"] = inputs()
                    log.warning("%s would not take its own reasoning back; asking again "
                                "without it", model)
                    continue
                if should_retry(exc, attempt=attempt, said_anything=spoke):
                    seconds = retrying.delay_for(attempt, exc)
                    log.warning("%s", retrying.said(exc, model=model, attempt=attempt,
                                                    seconds=seconds))
                    await retrying.wait(seconds)
                    if _is_stopped(stop):
                        stopped = True
                        break
                    continue
                question.write()    # they asked; the failure is ours
                over = too_long(exc)
                if over is not None:
                    # More than Luna can read. Never cut to fit: the person is
                    # told, and the words stay on the screen (`chatkinds`).
                    log.warning("%s is more than %s can read, and was not answered: %s",
                                session_id, model, _said_of(exc))
                    await emit({"type": "error", "fatal": False, "lasting": True,
                                "message": chatkinds.too_long(session_id, model, *over)})
                    return "".join(now.full_text)
                log.exception("the call to %s failed", model)
                await emit({"type": "error", "message": friendly(exc), "fatal": False})
                return "".join(now.full_text)

        if stopped:
            break

        # The reply is real, so the question was finished.
        question.write()
        now.judging = False
        sources = now.cited.listing()
        if sources:
            now.full_text.append(sources)
            await emit({"type": "assistant_delta", "text": sources})
        window = now.count(final)
        if isinstance(windows, dict):
            windows[session_id] = window
        output = [_as_data(item) for item in (_get(final, "output") or [])]
        blocks, calls, refusal = stored(output)
        if now.cited.pages:
            # The words as they are kept, footnoted exactly where OpenAI said
            # each page was used, which is how a reload draws them. The stream
            # put each number where its annotation arrived, which is nearly
            # always the same place; the finished answer is the one to trust.
            exact = citing.footnoted([b for b in blocks if b.get("type") == "text"])
            if exact:
                now.full_text[began_at:] = [exact]
        raw = [_for_input(item) for item in output]
        # A search OpenAI asked this process to run is answered here, in
        # the next request, with the tools it loaded (`toolsearch`).
        for item in now.client_searches:
            asked = item.get("arguments") if isinstance(item.get("arguments"), dict) else {}
            names = toolsearch.find(entries, toolsearch.query_of(asked), asked.get("limit"))
            now.timing["loaded"] += names
            raw.append(toolsearch.openai_search_output(str(item.get("call_id")), names, entries))
            await emit({"type": "tool_end", "id": str(item.get("id")), "name": "tool_search",
                        "ok": True, "summary": toolsearch.said_loaded(names),
                        "results": [{"title": n, "url": ""} for n in names], "where": "rouh"})
        searched_here = bool(now.client_searches)
        messages.append({"role": "assistant", "content": blocks, ITEMS: raw})
        kept = _without_marks(blocks)
        if kept:
            brain.memory.add_message(session_id, "assistant", kept,
                                     root=question.slot.root, version=question.slot.version)
        now.this_call = []

        status = _get(final, "status")
        why = _get(_get(final, "incomplete_details"), "reason")
        if refusal is not None or why == "content_filter":
            note = refusal or "I can't help with that one."
            await emit({"type": "assistant_delta", "text": note})
            if on_sentence:
                await on_sentence(note)
            now.full_text.append(note)
            break
        if not calls:
            if searched_here and not _is_stopped(stop):
                continue            # the tools it asked for are loaded: go on
            if status == "incomplete" and not "".join(now.full_text).strip():
                # Out of room before a word: say so rather than say nothing.
                await emit({"type": "error", "fatal": False,
                            "message": "Luna ran out of room before it answered. "
                                       "Ask me again, or more simply."})
            break
        if _is_stopped(stop):
            stopped = True
            break
        running = asyncio.ensure_future(now.run_calls(calls))
        try:
            results = await _first_of(running, stop)
        except _Stopped:
            _let_it_finish(running)
            stopped = True
            break
        as_kept = results
        if _shows_files(as_kept):
            # A file a tool showed is kept as its marker and read in on the request.
            results = attachments.hydrate([{"role": "user", "content": as_kept}],
                                          brain.files)[0]["content"]
        messages.append({"role": "user", "content": results})
        brain.memory.add_message(session_id, "user", as_kept,
                                 root=question.slot.root, version=question.slot.version)
        # What Master's look-ups found since the first request, after the
        # results and on this request only, as for Claude (`late_memory`).
        later = await late_memory(session_id, seeds, recall)
        if later:
            messages[-1] = {"role": "user", "content": list(results) + [{"type": "text", "text": later}]}
        # And what the person sent while the tools ran, as for Claude.
        messages.extend(await brain._take_steer(session_id, question, steer, emit))
        # Not trimmed between two requests of a turn, which would change what
        # the next one has cached, unless the window is about to be more than
        # Luna can read at all (`context_editing.ceiling`), and only in
        # General, as for Claude.
        ceiling = context_editing.ceiling(model)
        if rules.trims and window > ceiling:
            messages = await brain._edit_context(messages, emit, rules, window=window,
                                                 budget=ceiling, by_age=False,
                                                 usage=now.usage)

    if stopped:
        question.write()
        return await brain._abandon(session_id, now.this_call, now.full_text, emit,
                                    question.slot)

    if on_sentence and now.spoken_buffer.strip():
        await on_sentence(now.spoken_buffer.strip())

    text = "".join(now.full_text).strip()
    spent = costs.summarise(now.usage, now.usage.get("model") or model)
    spent["trimmed"] = now.usage.get("trimmed", 0)
    spent.update(_timed(now.timing, plan.mode))
    with contextlib.suppress(Exception):
        brain.memory.note_spend(session_id, spent)
    log.info("turn cost: %s", costs.said(spent))
    log.info("turn timing: %s", _said_timing(spent))
    await emit({"type": "assistant_done", "text": text, "usage": now.usage, "spent": spent})
    return text


def too_long(exc) -> tuple[int, int] | None:
    """More than Luna can read, as `retrying.overflowed` says it for Claude."""
    over = retrying.overflowed(exc)
    if over is not None:
        return over
    if getattr(exc, "code", None) == "context_length_exceeded" or \
            "context_length_exceeded" in _said_of(exc):
        return 0, 0
    return None


def _is_openai_failure(exc) -> bool:
    """A failure of the call itself, which the retry rules are for.

    OpenAI's own errors and a failure said inside the stream. Anything else is
    a bug of Rouh's and goes up to `Brain.run_turn`, which writes the question
    down and lets it be seen.
    """
    if isinstance(exc, LunaFailed):
        return True
    try:
        import openai
    except ImportError:                                  # pragma: no cover
        return False
    return isinstance(exc, (openai.APIStatusError, openai.APIConnectionError))
