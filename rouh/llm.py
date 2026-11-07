"""The LLM service: one way to ask a model, whichever company's it is.

Petar, the evening of 18 October 2026: "Every call that we make now has to route
through our new model selection. Whatever we select here should be the one
called. No exceptions." And, asked why filing could only use Anthropic: it
could not because it was handed Anthropic's own client and read Anthropic's own
stream events, so an OpenAI model failed on it, and the Models page hid that by
giving it the tier's Anthropic stand-in.

So everything that asks a model one question and reads one answer asks it here,
by its use (`modeldefaults.USES`):

    got = await llm.ask("filing", system=SYSTEM, messages=[...], max_tokens=300, who=who)
    got.text, got.model, got.effort

- **The model is the use's, read at the moment of asking**: its tier's model or
  its own (Custom), at the level that comes with it (`modeldefaults.use_pair`).
  Nothing here names a model and nothing swaps one: a model that cannot be asked
  here (no key for its company) is `Cannot`, said in plain words, and the
  Models page says the same thing beside the use (`modeldefaults.blocked`).
- **Any of four providers** (since 24 October 2026): Anthropic's Messages API,
  OpenAI's Responses API, and Google's and xAI's OpenAI-compatible Chat Completions
  endpoints, all through the clients that write every request down (`llmlog.client`,
  `llmlog.openai_client`, `llmlog.compat_client`), under the purpose the caller says
  (`llmlog.about`), with the cost of every call priced from its usage (`costs.py`).
  Each is asked with the key this organisation has for it (`rouh/providerkeys.py`).
- **Or a decision** (`decide`, `decide_model`): OpenAI's Decisions API, the third kind
  of call, which answers typed questions about an input rather than writing words: the
  label it picks from a fixed list, with every label's probability. Only the models it
  takes (`config.DECISIONS_MODELS`), through the same recording client, priced on input
  alone (`costs.decision_cost`). Synapse's hosted decisions and the router's choice of
  tier both ask it here, so there is one Decisions client.
- **Double calls** (`double`): only with the blind comparisons turned on in Settings,
  Models (`modeldefaults.compares`: it sends the request to a second provider, which is
  why it is a choice of its own since 24 October 2026, and no longer part of Auto), a
  small share of the read-only asks, which the caller marks `read_only`, is asked of a
  second model as well, after the answer has been handed back, and a judge on the
  Cheaper tier says which answer was better. Only that conclusion is kept and counted
  (`modeloutcomes.note_double`), never the question or the answers. Where a person is
  there to say which was better, a chat's answer, the person's own vote takes the
  judge's place (`rouh/modelvotes.py`).

The loops that are more than one question - a turn of a chat (`brain.py`,
`luna.py`), Ask AI and its comment pass (`askai.py`, `commentpass.py`), look_into
(`subagent.py`) - ask through the same clients with their use's model, and are
the only other places a model is asked (`llmlog.strays`, which `land.sh` and
the deploy run).
"""
from __future__ import annotations

import asyncio
import logging
import random
import time
import weakref
from dataclasses import dataclass, field

from . import llmlog

log = logging.getLogger("rouh.llm")

ANTHROPIC = "anthropic"
OPENAI = "openai"
GOOGLE = "google"
XAI = "xai"
#: The two asked through Chat Completions.
COMPAT = (GOOGLE, XAI)


#: Room for a model's thinking on top of the words a caller asked for: both companies count
#: reasoning inside the output limit, so a 64-word title on a model that thinks at high would
#: otherwise come back empty, every word spent thinking.
THINKING_ROOM = 8000


class Cannot(RuntimeError):
    """The use's model cannot be asked here, in words a person can read."""


@dataclass
class Answer:
    """What came back: the words, the model and level that said them, and what it took."""

    text: str
    model: str
    effort: str
    ms: int = 0
    usage: dict = field(default_factory=dict)


#: The recording clients, by the event loop they are used on: a client's connections belong
#: to one loop, and Synapse asks from a loop of its own, in a thread (`synapse.ai.run`).
_clients: "weakref.WeakKeyDictionary" = weakref.WeakKeyDictionary()


def _client(company: str, cfg, org_id: str | None = None):
    """The recording client for a provider, one per key and event loop, with the key this
    organisation has for it (`providerkeys.key`)."""
    from . import providerkeys
    from .config import PROVIDER_NAMES

    key = providerkeys.key(company, org_id, cfg)
    if not key:
        raise Cannot(f"there is no {PROVIDER_NAMES.get(company, company)} key here")
    mine = _clients.setdefault(asyncio.get_running_loop(), {})
    held = mine.get(company)
    if held is None or held[0] != key:
        if company == OPENAI:
            made = llmlog.openai_client(key, max_retries=1)
        elif company in COMPAT:
            made = llmlog.compat_client(company, key, getattr(cfg, f"{company}_base_url", "") or "",
                                        max_retries=1)
        else:
            made = llmlog.client(key)
        mine[company] = held = (key, made)
    return held[1]


def compat_effort(provider: str, model: str, effort: str) -> str:
    """How deeply a Gemini or Grok model is asked to think, in its provider's words, or ""
    to send none. Gemini takes minimal, low, medium and high (ai.google.dev, "Thinking");
    Grok 4.5 and later take low, high and xhigh, and Grok 4.3 none and low (docs.x.ai,
    "Reasoning"). A deeper level than the model takes is its deepest."""
    level = (effort or "").strip().lower()
    if not level:
        return ""
    if provider == GOOGLE:
        return {"none": "minimal", "low": "low", "medium": "medium"}.get(level, "high")
    from .config import LEVELS_TAKEN

    few = LEVELS_TAKEN.get((model or "").strip())
    if few:
        return level if level in few else few[-1]
    return {"none": "low", "low": "low", "medium": "high", "high": "high"}.get(level, "xhigh")


def chat_messages(system: str, messages: list[dict]) -> list[dict]:
    """Messages in Anthropic's shape (text, images, tool calls and their results) as Chat
    Completions takes them, the system prompt first."""
    out: list[dict] = [{"role": "system", "content": system}] if system else []
    for m in messages:
        role = m.get("role") or "user"
        content = m.get("content")
        if isinstance(content, str):
            out.append({"role": role, "content": content})
            continue
        texts, parts, calls, results = [], [], [], []
        for block in content or []:
            t = block.get("type") if isinstance(block, dict) else None
            if t == "text":
                texts.append(block.get("text") or "")
                parts.append({"type": "text", "text": block.get("text") or ""})
            elif t == "image" and isinstance(block.get("source"), dict) and role == "user":
                src = block["source"]
                url = (src.get("url") if src.get("type") == "url" else
                       f"data:{src.get('media_type') or 'image/png'};base64,{src.get('data') or ''}")
                parts.append({"type": "image_url", "image_url": {"url": url}})
            elif t == "tool_use" and role == "assistant":
                import json as _json

                calls.append({"id": str(block.get("id")), "type": "function",
                              "function": {"name": str(block.get("name")),
                                           "arguments": _json.dumps(block.get("input") or {})}})
            elif t == "tool_result":
                inner = block.get("content")
                said = inner if isinstance(inner, str) else " ".join(
                    str(b.get("text") or "") for b in inner or [] if isinstance(b, dict) and b.get("type") == "text")
                if block.get("is_error"):
                    said = "Error: " + said
                results.append({"role": "tool", "tool_call_id": str(block.get("tool_use_id")),
                                "content": said or "(nothing)"})
        if role == "assistant":
            said = {"role": "assistant", "content": "".join(texts) or None}
            if calls:
                said["tool_calls"] = calls
            if said["content"] or calls:
                out.append(said)
        else:
            out.extend(results)
            if parts:
                out.append({"role": "user", "content": parts if any(p["type"] != "text" for p in parts)
                            else "".join(p["text"] for p in parts)})
    return out


async def _ask_compat(provider: str, model: str, effort: str, system: str, messages: list[dict],
                      max_tokens: int, cfg, org_id: str | None = None,
                      on_text=None) -> tuple[str, dict]:
    level = compat_effort(provider, model, effort)
    request = dict(model=model, messages=chat_messages(system, messages), stream=True,
                   stream_options={"include_usage": True},
                   max_completion_tokens=max_tokens + (THINKING_ROOM if level not in ("", "none", "minimal") else 0))
    if level:
        request["reasoning_effort"] = level
    said: list[str] = []
    usage: dict = {}
    stream = await _client(provider, cfg, org_id).chat.completions.create(**request)
    async for chunk in stream:
        for choice in getattr(chunk, "choices", None) or []:
            delta = getattr(choice, "delta", None)
            if delta is not None and getattr(delta, "content", None):
                said.append(delta.content)
                if on_text:
                    on_text(delta.content)
        u = getattr(chunk, "usage", None)
        if u is not None:
            details = getattr(u, "prompt_tokens_details", None)
            cached = int(getattr(details, "cached_tokens", 0) or 0) if details is not None else 0
            usage = {"input_tokens": max(0, int(getattr(u, "prompt_tokens", 0) or 0) - cached),
                     "output_tokens": int(getattr(u, "completion_tokens", 0) or 0),
                     "cache_read_input_tokens": cached}
    return "".join(said), usage


def _openai_input(messages: list[dict]) -> list[dict]:
    """Messages in Anthropic's shape (text, or text and image blocks) as OpenAI's input."""
    out = []
    for m in messages:
        role = m.get("role") or "user"
        content = m.get("content")
        kind = "output_text" if role == "assistant" else "input_text"
        if isinstance(content, str):
            out.append({"role": role, "content": [{"type": kind, "text": content}]})
            continue
        parts = []
        for block in content or []:
            t = block.get("type") if isinstance(block, dict) else None
            if t == "text":
                parts.append({"type": kind, "text": block.get("text") or ""})
            elif t == "image" and isinstance(block.get("source"), dict):
                src = block["source"]
                url = (src.get("url") if src.get("type") == "url" else
                       f"data:{src.get('media_type') or 'image/png'};base64,{src.get('data') or ''}")
                parts.append({"type": "input_image", "image_url": url})
        out.append({"role": role, "content": parts})
    return out


async def _ask_anthropic(model: str, effort: str, system: str, messages: list[dict],
                         max_tokens: int, cfg, org_id: str | None = None,
                         on_text=None) -> tuple[str, dict]:
    from .config import effort_for, thinking_for

    thinking = thinking_for(model)
    request = dict(model=model, max_tokens=max_tokens + (THINKING_ROOM if thinking else 0),
                   messages=messages)
    if system:
        request["system"] = system
    if thinking:
        request["thinking"] = thinking
    level = effort_for(model, effort if effort != "none" else "low")
    if level:
        request["output_config"] = {"effort": level}
    said: list[str] = []
    usage: dict = {}
    async with _client(ANTHROPIC, cfg, org_id).messages.stream(**request) as stream:
        async for event in stream:
            if (event.type == "content_block_delta"
                    and getattr(event.delta, "type", "") == "text_delta"):
                said.append(event.delta.text or "")
                if on_text and event.delta.text:
                    on_text(event.delta.text)
        try:
            final = await stream.get_final_message()
            u = getattr(final, "usage", None)
            usage = {"input_tokens": getattr(u, "input_tokens", 0) or 0,
                     "output_tokens": getattr(u, "output_tokens", 0) or 0}
            # Why it stopped, when it was not the end of its words: an answer with nothing in it
            # ("refusal") says so instead of being a mystery (Trials, 4 November 2026).
            if getattr(final, "stop_reason", "") not in ("", None, "end_turn"):
                usage["stop_reason"] = str(final.stop_reason)
        except Exception:                         # the words are what matter
            pass
    return "".join(said), usage


async def _ask_openai(model: str, effort: str, system: str, messages: list[dict],
                      max_tokens: int, cfg, org_id: str | None = None,
                      on_text=None) -> tuple[str, dict]:
    from .luna import effort_of

    reasons = bool(effort) and effort != "none" and not model.startswith("gpt-4")
    request = dict(model=model, input=_openai_input(messages), store=False, stream=True,
                   max_output_tokens=max_tokens + (THINKING_ROOM if reasons else 0))
    if system:
        request["instructions"] = system
    if effort and not model.startswith("gpt-4"):
        request["reasoning"] = {"effort": "none" if effort == "none" else effort_of(effort, model)}
    said: list[str] = []
    usage: dict = {}
    stream = await _client(OPENAI, cfg, org_id).responses.create(**request)
    async with stream:
        async for event in stream:
            kind = getattr(event, "type", "")
            if kind == "response.output_text.delta":
                said.append(getattr(event, "delta", "") or "")
                if on_text and getattr(event, "delta", ""):
                    on_text(event.delta)
            elif kind == "response.completed":
                u = getattr(getattr(event, "response", None), "usage", None)
                usage = {"input_tokens": getattr(u, "input_tokens", 0) or 0,
                         "output_tokens": getattr(u, "output_tokens", 0) or 0}
    return "".join(said), usage


async def ask_model(model: str, effort: str, *, system: str = "", messages, max_tokens: int,
                    cfg=None, org_id: str | None = None, on_text=None) -> Answer:
    """Ask this model, already picked from the Models page, one question. For the
    callers that pick first and ask later (`ask` below, the router, double calls).
    `on_text` is handed each piece of the answer's words as it arrives."""
    from .config import config as _config, provider_of

    cfg = cfg or _config
    if isinstance(messages, str):
        messages = [{"role": "user", "content": messages}]
    began = time.monotonic()
    provider = provider_of(model)
    if provider == OPENAI:
        text, usage = await _ask_openai(model, effort, system, messages, max_tokens, cfg, org_id,
                                        on_text)
    elif provider in COMPAT:
        text, usage = await _ask_compat(provider, model, effort, system, messages, max_tokens, cfg,
                                        org_id, on_text)
    else:
        text, usage = await _ask_anthropic(model, effort, system, messages, max_tokens, cfg, org_id,
                                           on_text)
    return Answer(text=text, model=model, effort=effort,
                  ms=int((time.monotonic() - began) * 1000), usage=usage)


async def ask(use: str, *, messages, max_tokens: int, system: str = "", who=None,
              org_id: str | None = None, cfg=None, purpose: str | None = None,
              session_id: str = "", subject: str = "", read_only: bool = False,
              timeout: float | None = None, on_text=None) -> Answer:
    """Ask the model the Models page has for `use` one question, and give back its answer.

    `messages` is a string (one question) or messages in Anthropic's shape, text
    and images. Raises `Cannot` when the use is off or its model cannot be asked
    here, and whatever the provider raised when the request failed: nothing is
    asked of another model instead. `read_only` says the answer only says
    something and changes nothing, so it may be one of Auto's double calls.
    `on_text`, when given, is handed each piece of the words as they arrive, for
    a caller that acts on the first of them before the rest are written."""
    from . import modeldefaults
    from .config import config as _config

    cfg = cfg or _config
    org = org_id or (str(getattr(who, "org_id", "") or "") or None)
    pair = await asyncio.to_thread(modeldefaults.use_pair, use, org, cfg)
    if not pair.model or pair.model == modeldefaults.OFF:
        raise Cannot(f"{modeldefaults.BY_ID[use].name} is off")
    if pair.model == modeldefaults.NONE:
        raise Cannot(f"{modeldefaults.BY_ID[use].name} has no model it can ask here: "
                     "no provider on its list has a key")
    said = {"purpose": purpose or use}
    if session_id:
        said["session_id"] = session_id
    if subject:
        said["subject"] = subject
    with llmlog.about(who, **said):
        asking = ask_model(pair.model, pair.effort, system=system, messages=messages,
                           max_tokens=max_tokens, cfg=cfg, org_id=org, on_text=on_text)
        got = await (asyncio.wait_for(asking, timeout) if timeout else asking)
    if read_only:
        double(use, got, system=system, messages=messages, max_tokens=max_tokens, who=who,
               org_id=org, cfg=cfg)
    return got


# --- double calls ------------------------------------------------------------------------------
#
# Petar, 18 October 2026: "You get the benefit of optimized models if you share stats and double
# calls (a task is made by two models and compared)." Only with Auto on, only on a
# read-only answer, only for the share of them the standard says (`double_rate`, 2% to start),
# and never in the way of the answer: it runs after the answer is handed back.

#: The judge's instructions. It sees the question and both answers, here, and says which is
#: better; the question and the answers never leave this Rouh and are not kept beyond the log
#: of requests every call is in.
JUDGE = """You compare two answers to the same request, A and B, and say which serves the request better: more correct, more complete where it matters, and following what was asked. Length is not a merit.

Answer with JSON alone: {"better": "A", "B" or "same"}"""

_running: set = set()


def double(use: str, first: Answer, *, system: str, messages, max_tokens: int, who=None,
           org_id: str | None = None, cfg=None) -> bool:
    """Maybe ask a second model the same question, in the background. Never raises."""
    try:
        from . import modeldefaults

        rate = modeldefaults.double_rate(org_id)
        if rate > 0 and not modeldefaults.compares(org_id):
            return False
        if rate <= 0 or random.random() >= rate:
            return False
        task = asyncio.get_running_loop().create_task(
            _double(use, first, system=system, messages=messages, max_tokens=max_tokens,
                    who=who, org_id=org_id, cfg=cfg))
        _running.add(task)
        task.add_done_callback(_running.discard)
        return True
    except Exception:
        log.exception("a double call for %s could not be started", use)
        return False


async def _double(use: str, first: Answer, *, system, messages, max_tokens, who, org_id, cfg) -> None:
    from . import modeldefaults, modeloutcomes

    try:
        second = await asyncio.to_thread(modeldefaults.second_opinion, use, first.model, org_id, cfg)
        if second is None:
            return
        with llmlog.about(who, purpose="double_call", subject=use):
            other = await ask_model(second.model, second.effort, system=system, messages=messages,
                                    max_tokens=max_tokens, cfg=cfg, org_id=org_id)
            judge = await asyncio.to_thread(modeldefaults.use_pair, "double_judge", org_id, cfg)
            # Which answer is A is a coin toss, so a judge that favours the first it reads
            # favours neither model.
            flip = random.random() < 0.5
            a, b = (other, first) if flip else (first, other)
            question = messages if isinstance(messages, str) else "\n\n".join(
                str(m.get("content")) if isinstance(m.get("content"), str) else
                " ".join(p.get("text", "") for p in m.get("content") or [] if isinstance(p, dict))
                for m in messages)
            if judge.model in ("", modeldefaults.OFF, modeldefaults.NONE):
                return
            said = await ask_model(
                judge.model, judge.effort, system=JUDGE, max_tokens=400, cfg=cfg, org_id=org_id,
                messages=f"The request:\n{system}\n\n{question}\n\nAnswer A:\n{a.text}\n\n"
                         f"Answer B:\n{b.text}")
        better = _better(said.text)
        winner = "same" if better in ("same", "") else (
            ("second" if better == "A" else "first") if flip else ("first" if better == "A" else "second"))
        await asyncio.to_thread(modeloutcomes.note_double, use, first, other, said, winner, org_id)
    except Exception as exc:                       # a double call is never anybody's problem
        log.info("a double call for %s did not finish: %s", use, exc)


def _better(text: str) -> str:
    import json
    import re

    found = re.search(r"\{.*\}", text or "", re.S)
    try:
        got = json.loads(found.group(0)) if found else {}
    except ValueError:
        return ""
    better = str(got.get("better") or "").strip()
    return better if better in ("A", "B", "same") else ""


# --- decisions ---------------------------------------------------------------------------------
#
# OpenAI's Decisions API, read from its guide and reference on 23 October 2026
# (developers.openai.com/api/docs/guides/decisions, .../reference/resources/decisions/methods/create):
#
#   POST /v1/decisions {"model": "gpt-6-luna", "input": <text or messages>, "questions": [...]}
#
# A question is a predicate ({"type": "predicate", "name", "instructions"}, answered with a
# `probability`), a choice ({"type": "choice", "name", "instructions", "choices": [{"value",
# "description"}]}, 2 to 255 unique values, answered with `choice`, `probabilities` as a list of
# {"value", "probability"} and `confidence`) or a score ({"type": "score", "name",
# "instructions", "levels": [{"label", "description"}]}, 2 to 10 levels lowest first, answered
# with `score`, `probabilities` as a list of {"value": index, "label", "probability"} and
# `confidence`). 1 to 400 questions a request; answers come back in question order, each with
# its question's name, and any of them may be {"type": "refusal", "name"} instead. The usage is
# `input_tokens` (cache reads and writes included in it), `input_tokens_details.cached_tokens`
# and `.cache_write_tokens`, and `output_tokens`, which is not charged.

#: Where it is asked, on OpenAI's API.
DECISIONS_PATH = "/decisions"

#: How long a key the Decisions API turned away (401, 403 or 404) is not asked again, so a
#: router on it does not wait for the same refusal before every turn. Synapse checks again
#: on the same clock (`synapse.ai.PROBE_EVERY`).
REFUSED_FOR = 3600

_refused: dict = {}


@dataclass
class Verdict:
    """One question's answer. `probabilities` is every label's, by label: a choice's values,
    a score's level labels, a predicate's "yes" and "no"."""

    name: str
    type: str
    label: str = ""
    probabilities: dict = field(default_factory=dict)
    confidence: float | None = None
    probability: float | None = None
    score: float | None = None

    @property
    def refused(self) -> bool:
        return self.type == "refusal"


@dataclass
class Decided:
    """What the Decisions API said: an answer for each question, in question order, the model
    that answered, what it took and what it cost."""

    answers: list
    model: str
    ms: int = 0
    usage: dict = field(default_factory=dict)
    cost: float | None = None

    def answer(self, name: str) -> "Verdict | None":
        return next((a for a in self.answers if a.name == name), None)

    @property
    def label(self) -> str:
        """The first answer's label: the chosen one, for `decide`'s one question."""
        return self.answers[0].label if self.answers else ""

    @property
    def probabilities(self) -> dict:
        return self.answers[0].probabilities if self.answers else {}


class Refused(Cannot):
    """The Decisions API would not take this key or model: `status` is its HTTP status."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


def choice(name: str, instructions: str, labels, descriptions: dict | None = None) -> dict:
    """A choice question: one of `labels`, each with a line saying what it means if given."""
    choices = []
    for label in labels:
        one = {"value": label}
        if descriptions and descriptions.get(label):
            one["description"] = descriptions[label]
        choices.append(one)
    return {"type": "choice", "name": name, "instructions": instructions, "choices": choices}


def score(name: str, instructions: str, levels, descriptions: dict | None = None) -> dict:
    """A score question: `levels` from the lowest to the highest."""
    out = []
    for label in levels:
        one = {"label": label}
        if descriptions and descriptions.get(label):
            one["description"] = descriptions[label]
        out.append(one)
    return {"type": "score", "name": name, "instructions": instructions, "levels": out}


def predicate(name: str, instructions: str) -> dict:
    """A predicate: how likely it is that a statement about the input is true."""
    return {"type": "predicate", "name": name, "instructions": instructions}


def decision_request(model: str, input, questions: list[dict]) -> dict:
    """The body of a Decisions API request, as its reference has it. `input` is text, or
    messages in Anthropic's shape (`_openai_input`), which it takes as Responses does."""
    if not questions or len(questions) > 400:
        raise ValueError(f"the Decisions API takes 1 to 400 questions a request, not {len(questions)}")
    names = [q.get("name") for q in questions]
    if len(set(names)) != len(names):
        raise ValueError("every question needs a name of its own, which its answer comes back with")
    for q in questions:
        if q.get("type") == "choice":
            values = [c.get("value") for c in q.get("choices") or []]
            if not 2 <= len(values) <= 255 or len(set(map(repr, values))) != len(values):
                raise ValueError(f"{q.get('name')}: a choice takes 2 to 255 different values")
        elif q.get("type") == "score" and not 2 <= len(q.get("levels") or []) <= 10:
            raise ValueError(f"{q.get('name')}: a score takes 2 to 10 levels")
        elif q.get("type") not in ("choice", "score", "predicate"):
            raise ValueError(f"{q.get('name')}: {q.get('type')!r} is not a question the Decisions API takes")
    if not isinstance(input, str):
        input = _openai_input(input)
    return {"model": model, "input": input, "questions": [dict(q) for q in questions]}


def decision_usage(usage) -> dict:
    """The Decisions API's usage in the names `costs` reads: the uncached input on its own,
    beside the tokens read from the cache and written to it, which its `input_tokens`
    includes; and the output tokens, which are kept and never charged."""
    if not isinstance(usage, dict):
        return {}
    details = usage.get("input_tokens_details") if isinstance(usage.get("input_tokens_details"), dict) else {}

    def number(of, key) -> int:
        try:
            return int(of.get(key) or 0)
        except (TypeError, ValueError):
            return 0

    sent, read, wrote = number(usage, "input_tokens"), number(details, "cached_tokens"), number(details, "cache_write_tokens")
    return {"input_tokens": max(0, sent - read - wrote), "output_tokens": number(usage, "output_tokens"),
            "cache_read_input_tokens": read, "cache_creation_input_tokens": wrote}


def read_decision(body, questions: list[dict], model: str = "") -> Decided:
    """A Decisions API answer as a `Decided`, every answer matched to its question by name,
    or by its place when the name is missing. A question with no answer, or a refusal,
    comes back as a refusal."""
    from . import costs

    body = body if isinstance(body, dict) else {}
    given = [a for a in body.get("answers") or [] if isinstance(a, dict)]
    by_name = {a.get("name"): a for a in given if a.get("name") is not None}
    out = []
    for i, q in enumerate(questions):
        a = by_name.get(q.get("name")) or (given[i] if i < len(given) and given[i].get("name") is None else {})
        kind = str(a.get("type") or "refusal")
        v = Verdict(name=q.get("name") or "", type=kind if kind in ("choice", "score", "predicate") else "refusal")
        if v.type == "predicate":
            p = float(a.get("probability") or 0.0)
            v.probability, v.probabilities = p, {"yes": p, "no": 1.0 - p}
            v.label = "yes" if p >= 0.5 else "no"
        elif v.type == "choice":
            v.probabilities = {p.get("value"): float(p.get("probability") or 0.0)
                               for p in a.get("probabilities") or [] if isinstance(p, dict)}
            v.label = a.get("choice")
            v.confidence = float(a["confidence"]) if a.get("confidence") is not None else None
        elif v.type == "score":
            levels = [lv.get("label") for lv in q.get("levels") or []]
            for p in a.get("probabilities") or []:
                if not isinstance(p, dict):
                    continue
                label = p.get("label")
                if label is None and isinstance(p.get("value"), int) and 0 <= p["value"] < len(levels):
                    label = levels[p["value"]]
                v.probabilities[label] = float(p.get("probability") or 0.0)
            v.score = float(a["score"]) if a.get("score") is not None else None
            v.confidence = float(a["confidence"]) if a.get("confidence") is not None else None
            v.label = max(v.probabilities, key=v.probabilities.get) if v.probabilities else ""
        out.append(v)
    served = str(body.get("model") or model)
    usage = decision_usage(body.get("usage"))
    return Decided(answers=out, model=served, usage=usage,
                   cost=costs.decision_cost(usage, served) if usage else None)


def failure(exc: BaseException) -> str:
    """What went wrong with a request, in a line a person can read: the HTTP status and the
    API's own words, rather than the SDK's dump of the whole error."""
    status = getattr(exc, "status_code", None)
    body = getattr(exc, "body", None)
    said = ""
    if isinstance(body, dict):
        inner = body.get("error") if isinstance(body.get("error"), dict) else body
        said = str(inner.get("message") or "")
    said = " ".join((said or str(exc) or type(exc).__name__).split()).rstrip(".")
    return f"{status}: {said}"[:300] if status else said[:300]


def decisions_closed(cfg=None) -> str:
    """Why the Decisions API is not to be asked with this key just now, or "": it turned
    the key away within the last `REFUSED_FOR` seconds."""
    from .config import config as _config

    key = getattr(cfg or _config, "openai_api_key", "") or ""
    held = _refused.get(key)
    if held and time.monotonic() < held[0]:
        return held[1]
    return ""


async def decide_model(model: str, *, input, questions: list[dict], cfg=None) -> Decided:
    """Ask this model, already picked from the Models page, questions through OpenAI's
    Decisions API. Raises `Cannot` for a model it does not take or a key it turned away
    (`Refused`), and whatever the request raised otherwise."""
    from .config import config as _config, is_decisions_model, model_name

    cfg = cfg or _config
    if not is_decisions_model(model):
        raise Cannot(f"{model_name(model)} is not a model OpenAI's Decisions API takes")
    body = decision_request(model, input, questions)
    key = getattr(cfg, "openai_api_key", "") or ""
    began = time.monotonic()
    try:
        data = await _client(OPENAI, cfg).post(DECISIONS_PATH, cast_to=object, body=body)
    except Exception as exc:
        status = getattr(exc, "status_code", None)
        if status in (401, 403, 404):
            said = failure(exc)
            _refused[key] = (time.monotonic() + REFUSED_FOR, said)
            log.warning("OpenAI's Decisions API turned this key away (%s)", said)
            raise Refused(f"OpenAI's Decisions API turned this key away ({said})", status) from exc
        raise
    _refused.pop(key, None)
    got = read_decision(data, questions, model)
    got.ms = int((time.monotonic() - began) * 1000)
    return got


async def decide(use: str, *, input, labels, instructions: str, descriptions: dict | None = None,
                 who=None, org_id: str | None = None, cfg=None, purpose: str | None = None,
                 session_id: str = "", subject: str = "", timeout: float | None = None) -> Decided:
    """Ask the Decisions API, on the model the Models page has for `use`, which of `labels`
    fits `input`, and give back the chosen label (`.label`) with every label's probability
    (`.probabilities`). Raises `Cannot` when the use is off, or its model is not one the
    Decisions API takes, or the key was turned away; nothing is asked of another model."""
    from . import modeldefaults
    from .config import config as _config

    cfg = cfg or _config
    org = org_id or (str(getattr(who, "org_id", "") or "") or None)
    pair = await asyncio.to_thread(modeldefaults.use_pair, use, org, cfg)
    if not pair.model or pair.model == modeldefaults.OFF:
        raise Cannot(f"{modeldefaults.BY_ID[use].name} is off")
    closed = decisions_closed(cfg)
    if closed:
        raise Refused(f"OpenAI's Decisions API turned this key away ({closed})")
    said = {"purpose": purpose or use}
    if session_id:
        said["session_id"] = session_id
    if subject:
        said["subject"] = subject
    with llmlog.about(who, **said):
        asking = decide_model(pair.model, input=input, cfg=cfg,
                              questions=[choice("answer", instructions, list(labels), descriptions)])
        return await (asyncio.wait_for(asking, timeout) if timeout else asking)
