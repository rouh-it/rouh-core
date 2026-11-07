"""A chat's turn answered by Google's Gemini or xAI's Grok, through their Chat Completions APIs.

Petar, 24 October 2026: Google and xAI as providers beside OpenAI and Anthropic, and "an
install with only one provider's key must work end to end". So a chat whose model is one
of Google's or xAI's (`config.GOOGLE_CHOICES`, `config.XAI_CHOICES`) is answered here, as a
turn asked of OpenAI's model is answered in `rouh/luna.py`: a loop of its own, leaving the
Anthropic loop in `brain.py` untouched. Both providers speak OpenAI's Chat Completions
(ai.google.dev/gemini-api/docs/openai, docs.x.ai), streamed, with function calling, so one
loop serves both, through the client that writes every request down with its cost
(`llmlog.compat_client`, `llm._client`), with the key the organisation has for that provider
(`rouh/providerkeys.py`).

Every piece of Rouh's turn, and what it is on this side:

- **Tools.** Every tool of Rouh's own, declared as a function with its schema cut down to
  what both providers take (`_schema`), run through the very same `Brain._run_tools`, so
  the untrusted-content boxes, the tools that have to be asked about and the lines on
  screen are one code path for every model.
- **Tool search.** As for Claude in its "client" mode: none of the tools is declared until
  the model asks for it with `find_tools`, which this process answers from the catalogue in
  the instructions (`toolsearch.find`); what it loads is declared from the next request on.
- **The web.** Anthropic's web_search and web_fetch run on Anthropic's side and OpenAI's on
  OpenAI's; neither provider here is given one, so neither the tools nor the rules about
  them are told (`brain._system`, provider "other").
- **Its own name.** The model is told, under the name Rouh, which model it is (the built-in
  rule `model-other`).
- **Gemini's thought signatures.** Gemini 3 and later hand back a signature with each tool
  call that must come back with it in the same turn; the turn's own messages keep each call
  exactly as it came (`extra_content`), and only Anthropic's shape is stored.
- **Turn marks, speech, stop, retries, context trimming, attachments, the orb's line and
  the question written down once** are the same functions as Luna's and Claude's.

What is stored is Anthropic's shape - text, tool calls and their results - so the
conversation reads the same whichever model answers next. A search for tools is not stored:
it is how a request reaches its tools, not part of the conversation.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
from types import SimpleNamespace

from . import (attachments, chatkinds, context_editing, costs, llm, llmlog, modelstandard, replymode,
               retrying, toolsearch, turnmarks)
from .brain import (_first_of, _is_stopped, _let_it_finish, _said_timing, _split_sentences, _Stopped,
                    _timed, _without_marks)
from .config import PROVIDER_NAMES, model_name, provider_of
from .luna import should_retry, too_long

log = logging.getLogger("rouh.compat")

#: The schema keywords both providers take; anything else in a tool's schema is left out,
#: because Gemini refuses a whole request for one it does not know.
SCHEMA_KEYS = {"type", "description", "properties", "items", "required", "enum", "anyOf",
               "minimum", "maximum", "minItems", "maxItems", "nullable", "format"}

#: The most a turn's answer may be, in tokens.
MAX_TOKENS = 32000


def _schema(schema) -> dict:
    """A tool's schema as both providers take it: only the keywords they know, an object
    at the top, `required` naming only properties there are."""
    def clean(node):
        if isinstance(node, dict):
            out = {}
            for k, v in node.items():
                if k == "properties" and isinstance(v, dict):
                    out[k] = {name: clean(sub) for name, sub in v.items()}
                elif k in SCHEMA_KEYS:
                    out[k] = clean(v) if isinstance(v, (dict, list)) and k != "enum" else v
            if out.get("type") == "array" and "items" not in out:
                out["items"] = {"type": "string"}
            if isinstance(out.get("required"), list) and isinstance(out.get("properties"), dict):
                out["required"] = [r for r in out["required"] if r in out["properties"]]
                if not out["required"]:
                    out.pop("required")
            if isinstance(out.get("type"), list):
                kinds = [t for t in out["type"] if t != "null"]
                out["type"] = kinds[0] if kinds else "string"
            return out
        if isinstance(node, list):
            return [clean(x) for x in node]
        return node

    out = clean(schema if isinstance(schema, dict) else {})
    out["type"] = "object"
    if not isinstance(out.get("properties"), dict):
        out["properties"] = {}
    return out


def function(definition: dict) -> dict:
    """One of Rouh's tools as a Chat Completions function."""
    return {"type": "function", "function": {
        "name": str(definition.get("name") or ""),
        "description": str(definition.get("description") or "")[:4000],
        "parameters": _schema(definition.get("input_schema"))}}


def _result_text(content) -> str:
    """A tool's result as the text a `tool` message carries: what a search loaded said in
    words, and a picture or a file named rather than sent."""
    if isinstance(content, str):
        return content
    out = []
    for block in content or []:
        if not isinstance(block, dict):
            continue
        kind = block.get("type")
        if kind == "text":
            out.append(str(block.get("text") or ""))
        elif kind == "tool_reference":
            out.append(f"Loaded {block.get('tool_name')}: you can call it now.")
        elif kind in ("image", "document"):
            out.append(f"(a {'picture' if kind == 'image' else 'file'}, shown on the screen)")
    return "\n".join(x for x in out if x) or "(nothing)"


class _Turn:
    """One turn's state, as `luna._Turn` keeps Luna's."""

    def __init__(self, brain, session_id, emit, on_sentence, model, stop, answer_now, question,
                 timing=None, began=None):
        self.brain = brain
        self.cfg = brain.cfg
        self.session_id = session_id
        self.emit = emit
        self.on_sentence = on_sentence
        self.model = model
        self.provider = provider_of(model)
        self.stop = stop
        self.question = question
        self.spoken_buffer = ""
        self.full_text: list[str] = []
        self.this_call: list[str] = []
        self.usage = {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0,
                      "cache_write_1h": 0, "trimmed": 0, "calls": []}
        self.judging = not answer_now
        self.timing = timing if timing is not None else {
            "first_token": None, "first_text": None, "first_word": None, "requests": 0, "loaded": []}
        self.began = began if began is not None else time.monotonic()
        self.sent_at = time.monotonic()

    async def pump(self, request: dict) -> dict:
        """Stream one response; give back its words, its tool calls exactly as they came, and
        why it ended."""
        reading = turnmarks.Reading()
        words: list[str] = []
        calls: dict[int, dict] = {}
        finish = ""
        client = llm._client(self.provider, self.cfg)
        stream = await client.chat.completions.create(**request)
        async with stream:
            async for chunk in stream:
                usage = getattr(chunk, "usage", None)
                if usage is not None:
                    self.count(usage)
                for choice in getattr(chunk, "choices", None) or []:
                    delta = getattr(choice, "delta", None)
                    if self.timing.get("first_token") is None:
                        self.timing["first_token"] = time.monotonic() - self.sent_at
                    if delta is not None and getattr(delta, "content", None):
                        words.append(await self._words(reading, delta.content))
                    for call in (getattr(delta, "tool_calls", None) or []) if delta is not None else []:
                        index = getattr(call, "index", None)
                        held = calls.setdefault(len(calls) if index is None else index,
                                                {"id": "", "name": "", "arguments": "", "extra": None})
                        held["id"] = getattr(call, "id", None) or held["id"]
                        fn = getattr(call, "function", None)
                        if fn is not None:
                            held["name"] = getattr(fn, "name", None) or held["name"]
                            held["arguments"] += getattr(fn, "arguments", None) or ""
                        extra = (getattr(call, "model_extra", None) or {}).get("extra_content")
                        if extra:
                            held["extra"] = extra
                    if getattr(choice, "finish_reason", None):
                        finish = choice.finish_reason
        return {"text": "".join(words), "calls": [calls[k] for k in sorted(calls)], "finish": finish}

    async def _words(self, reading, delta: str) -> str:
        """Words as they arrive, with the turn mark taken off the front; gives back what is
        the answer's."""
        piece = reading.take(delta)
        if reading.unfinished and self.judging:
            raise turnmarks.Unfinished(reading.mark)
        if not piece:
            return ""
        self.question.write()
        if self.timing.get("first_text") is None:
            self.timing["first_text"] = time.monotonic() - self.began
        self.full_text.append(piece)
        self.this_call.append(piece)
        await self.emit({"type": "assistant_delta", "text": piece})
        if self.on_sentence:
            self.spoken_buffer += piece
            sentences, self.spoken_buffer = _split_sentences(self.spoken_buffer)
            for sentence in sentences:
                await self.on_sentence(sentence)
        return piece

    def count(self, usage) -> None:
        details = getattr(usage, "prompt_tokens_details", None)
        read = int(getattr(details, "cached_tokens", 0) or 0) if details is not None else 0
        took = {"input": max(0, int(getattr(usage, "prompt_tokens", 0) or 0) - read),
                "output": int(getattr(usage, "completion_tokens", 0) or 0),
                "cache_read": read, "cache_write": 0, "cache_write_1h": 0}
        for key in took:
            self.usage[key] += took[key]
        self.usage["calls"].append(took)
        self.usage["model"] = self.model
        self.window = took["input"] + read


def _failure(exc) -> bool:
    try:
        import openai
    except ImportError:                                  # pragma: no cover
        return False
    return isinstance(exc, (openai.APIStatusError, openai.APIConnectionError))


def friendly(exc, model: str) -> str:
    """The failure, in one sentence, for the screen and the voice."""
    who = PROVIDER_NAMES.get(provider_of(model), "The provider")
    status = retrying.status_of(exc)
    if status in (401, 403):
        return f"My {who} API key is not being accepted. Check it in Anatomy, Rouh Land Account, Models."
    if status == 404:
        return f"{model_name(model)} is not available to my {who} API key."
    if status == 429:
        return f"{who} is rate limiting me. Give me a moment."
    return f"{model_name(model)} could not answer just now ({llm.failure(exc)})."


async def turn(brain, session_id: str, user_content, emit, on_sentence, model: str,
               stop, answer_now: bool, question, *, rules=None, timing=None,
               began=None, level: str = "", seeds=None, recall=None, steer=None) -> str:
    """One turn, answered by a Gemini or Grok model. What `Brain._turn` is for Claude."""
    from .brain import late_memory, memory_for_turn

    cfg = brain.cfg
    rules = rules or chatkinds.profile(session_id, cfg)
    history = await asyncio.to_thread(
        brain.memory.history, session_id, rules.history, before=question.slot.root,
        limit_of=lambda chat: chatkinds.profile(chat, cfg).history)
    log.info("a %s turn in %s, with %s of history, on %s", rules.kind, session_id,
             f"all {len(history)} messages" if rules.history < 0
             else f"the newest {len(history)} messages", model)
    messages = history + [{"role": "user", "content": user_content}]
    noted = answer_now and replymode.NOW.get().marks
    if noted:
        messages = messages + [{"role": "user", "content": turnmarks.ANSWER_NOW}]
    messages = attachments.hydrate(messages, brain.files)
    # Only Rouh's own tools: the web tools are Anthropic's and OpenAI's, run on their side.
    entries = [t for t in brain.tools.entries() if t.portable]
    always = {n for n in getattr(cfg, "tools_always_loaded", ()) if n in {t.name for t in entries}}
    catalogue = toolsearch.catalogue(entries, mode="client", always=sorted(always))
    plan = toolsearch.Plan(mode="client", tools=[], catalogue=catalogue,
                           declared={t.name for t in entries})
    found, remembered = await memory_for_turn(session_id, seeds, recall, began or time.monotonic())
    system = await asyncio.to_thread(brain._system, plan, openai=model, seeds=found, recall=remembered)
    instructions = "\n\n".join(block["text"] for block in system)
    now = _Turn(brain, session_id, emit, on_sentence, model, stop, answer_now, question,
                timing=timing, began=began)
    now.window = 0
    windows = getattr(brain, "_windows", {})
    messages = await brain._edit_context(messages, emit, rules, window=windows.get(session_id, 0),
                                         usage=now.usage)
    convo = llm.chat_messages(instructions, messages)
    effort = llm.compat_effort(now.provider, model, level or modelstandard.effort(model))
    loaded: list[str] = sorted(always)
    by_name = {t.name: t for t in entries}
    stopped = False
    first = True
    while True:
        if _is_stopped(stop):
            stopped = True
            break
        if first and answer_now:
            taken = await brain._take_steer(session_id, question, steer, emit)
            for m in llm.chat_messages("", taken):
                convo.append(m)
        first = False
        tools = [function(toolsearch.client_search_definition())] + [
            function(by_name[n].definition) for n in dict.fromkeys(loaded) if n in by_name]
        request = {"model": model, "messages": convo, "stream": True,
                   "stream_options": {"include_usage": True}, "max_completion_tokens": MAX_TOKENS,
                   "tools": tools, "tool_choice": "auto"}
        if effort:
            request["reasoning_effort"] = effort
        attempt = 0
        got = None
        while True:
            attempt += 1
            said_before = len(now.full_text)
            now.this_call.clear()
            now.timing["requests"] = int(now.timing.get("requests") or 0) + 1
            now.sent_at = time.monotonic()
            with llmlog.about(attempt=attempt):
                reading = asyncio.ensure_future(now.pump(request))
            try:
                got = await _first_of(reading, stop)
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
                if not _failure(exc):
                    raise
                spoke = len(now.full_text) > said_before
                if should_retry(exc, attempt=attempt, said_anything=spoke):
                    seconds = retrying.delay_for(attempt, exc)
                    log.warning("%s", retrying.said(exc, model=model, attempt=attempt, seconds=seconds))
                    await retrying.wait(seconds)
                    if _is_stopped(stop):
                        stopped = True
                        break
                    continue
                question.write()
                over = too_long(exc)
                if over is not None:
                    await emit({"type": "error", "fatal": False, "lasting": True,
                                "message": chatkinds.too_long(session_id, model, *over)})
                    return "".join(now.full_text)
                log.exception("the call to %s failed", model)
                await emit({"type": "error", "message": friendly(exc, model), "fatal": False})
                return "".join(now.full_text)
        if stopped:
            break
        question.write()
        now.judging = False
        if isinstance(windows, dict):
            windows[session_id] = now.window
        calls = got["calls"]
        # The response as the conversation keeps it: its words, and every call but the search.
        blocks: list[dict] = []
        if got["text"].strip():
            blocks.append({"type": "text", "text": got["text"]})
        parsed = []
        for c in calls:
            try:
                args = json.loads(c["arguments"] or "{}")
            except ValueError:
                args = None
            call_id = c["id"] or f"call_{len(parsed)}_{int(time.time() * 1000)}"
            c["id"] = call_id
            parsed.append((c, args))
            if c["name"] != toolsearch.CLIENT_SEARCH:
                blocks.append({"type": "tool_use", "id": call_id, "name": c["name"],
                               "input": args if isinstance(args, dict) else {}})
        said = {"role": "assistant", "content": got["text"] or None}
        if calls:
            said["tool_calls"] = [dict({"id": c["id"], "type": "function",
                                        "function": {"name": c["name"], "arguments": c["arguments"] or "{}"}},
                                       **({"extra_content": c["extra"]} if c["extra"] else {}))
                                  for c in calls]
        convo.append(said)
        kept = _without_marks(blocks)
        if kept:
            brain.memory.add_message(session_id, "assistant", kept,
                                     root=question.slot.root, version=question.slot.version)
        now.this_call = []
        if not calls:
            if got["finish"] == "length" and not "".join(now.full_text).strip():
                await emit({"type": "error", "fatal": False,
                            "message": f"{model_name(model)} ran out of room before it answered. "
                                       "Ask me again, or more simply."})
            break
        if _is_stopped(stop):
            stopped = True
            break
        good = [SimpleNamespace(id=c["id"], name=c["name"], input=args)
                for c, args in parsed if isinstance(args, dict)]
        running = asyncio.ensure_future(brain._run_tools(good, emit, entries=entries, loaded=loaded))
        try:
            results = await _first_of(running, stop)
        except _Stopped:
            _let_it_finish(running)
            stopped = True
            break
        by_id = {r["tool_use_id"]: r for r in results}
        answered = []
        for c, args in parsed:
            r = by_id.get(c["id"]) or {"type": "tool_result", "tool_use_id": c["id"], "is_error": True,
                                       "content": f"{c['name']} was not run: what it was given was not "
                                                  f"valid JSON ({str(c['arguments'])[:200]!r})."}
            answered.append((c, r))
            convo.append({"role": "tool", "tool_call_id": c["id"],
                          "content": ("Error: " if r.get("is_error") else "") + _result_text(r.get("content"))})
        stored = [r for c, r in answered if c["name"] != toolsearch.CLIENT_SEARCH]
        if stored:
            brain.memory.add_message(session_id, "user", stored,
                                     root=question.slot.root, version=question.slot.version)
        later = await late_memory(session_id, seeds, recall)
        if later:
            convo.append({"role": "user", "content": later})
        for m in llm.chat_messages("", await brain._take_steer(session_id, question, steer, emit)):
            convo.append(m)
        ceiling = context_editing.ceiling(model)
        if rules.trims and now.window > ceiling:
            log.warning("%s is past %s's window (%d tokens); the next request may be refused",
                        session_id, model, now.window)

    if stopped:
        question.write()
        return await brain._abandon(session_id, now.this_call, now.full_text, emit, question.slot)
    if on_sentence and now.spoken_buffer.strip():
        await on_sentence(now.spoken_buffer.strip())
    text = "".join(now.full_text).strip()
    spent = costs.summarise(now.usage, now.usage.get("model") or model)
    spent["trimmed"] = now.usage.get("trimmed", 0)
    spent.update(_timed(now.timing, "client"))
    with contextlib.suppress(Exception):
        brain.memory.note_spend(session_id, spent)
    log.info("turn cost: %s", costs.said(spent))
    log.info("turn timing: %s", _said_timing(spent))
    await emit({"type": "assistant_done", "text": text, "usage": now.usage, "spent": spent})
    return text
