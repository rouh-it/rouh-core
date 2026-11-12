"""Everything Synapse asks of a model, all of it written down.

Three kinds of call, as the spec has them (D64):

- **embeddings**, for search by meaning (D37): Voyage AI's `voyage-4` at
  1,024 dimensions since 3 October 2026, with the query asked as a `query` and
  everything stored as a `document`. Datasets made before then keep OpenAI's
  `text-embedding-3-large` until their vectors are moved (`vectors.py`): a
  dataset's vectors are all one model's, and a question is embedded with that
  model, because two models' numbers mean nothing to each other;
- **generative** calls, all of them OpenAI's, for the X-ray and judgement links (D9), layers (D54),
  the map's words (D16), the checkpoint and the answer (D50) and the judge (D77);
- **decisions** (D66): one interface, `decide`, in the spec's Choice, Score and
  Noul shape, with the backend a setting per purpose.

The decision backends:

- `openai_decisions`: OpenAI's Decisions API, announced at DevDay on 29 September
  2026, on GPT-6 Luna. Asked of this key on 3 October 2026 it answered `403
  Decision API is not enabled for this user.`; on 23 October 2026 it answered.
  It is asked through the one Decisions client (`llm.decide_model`), in the shape
  OpenAI's reference gives. The status is checked again every hour and on
  request, and while it refuses, the generative backend answers and every
  answer says so.
- `generative`: a normal OpenAI model asked the same questions with its answer
  forced to the allowed labels by structured output, with the probability of
  each label read off the log probabilities of the answer's token. gpt-4.1-mini
  by default, because it returns the other labels' log probabilities; GPT-6
  Luna and GPT-5.4 were measured returning only the chosen token's.
- `off`: the point takes its fallback (D69).

Every request goes through `llmlog.openai_client`, so it is a row of
`llm_requests` like every other model request in Rouh, and every call is also
a `synapse.call` row on the operation it was part of, with its backend, model,
version, tokens, time and the items it held.

All of it runs on one event loop of its own, in a thread, so the rest of
Synapse can be plain synchronous code on a thread and still make many calls at
once (`run`).
"""
from __future__ import annotations

import asyncio
import json
import logging
import math
import threading
import time
from concurrent.futures import TimeoutError as FutureTimeout

from .. import costs, llmlog
from ..config import config, takes_effort as config_takes_effort
from . import db

log = logging.getLogger("rouh.synapse.ai")

EMBED_DIMS = 1024
#: The embedding models, by who answers them.
VOYAGE_MODELS = ("voyage-4",)
OPENAI_EMBED_MODELS = ("text-embedding-3-large", "text-embedding-3-small")
PROBE_EVERY = 3600

_loop: asyncio.AbstractEventLoop | None = None
_loop_lock = threading.Lock()
_client = None
_client_key = ""
_claude = None
_claude_key = ""
_voyage = None


class NoKey(RuntimeError):
    """This machine has no key for the provider asked."""


class VoyageError(RuntimeError):
    """Voyage AI said no, or could not be reached; `status` is its HTTP status."""

    def __init__(self, message: str, status: int | None = None, retry_after: float = 0.0):
        super().__init__(message)
        self.status = status
        self.retry_after = retry_after


def have_key() -> bool:
    return bool(getattr(config, "openai_api_key", ""))


def have_voyage() -> bool:
    return bool(getattr(config, "voyage_api_key", ""))


def is_voyage(model: str) -> bool:
    return str(model or "").startswith("voyage-")


def can_embed(model: str) -> bool:
    """Whether this machine has the key that model is asked with."""
    return have_voyage() if is_voyage(model) else have_key()


def _ensure_loop() -> asyncio.AbstractEventLoop:
    global _loop
    with _loop_lock:
        if _loop is None or _loop.is_closed():
            loop = asyncio.new_event_loop()
            thread = threading.Thread(target=loop.run_forever, name="synapse-ai", daemon=True)
            thread.start()
            _loop = loop
        return _loop


def run(coro, timeout: float = 300.0):
    """Run a coroutine on Synapse's own event loop and wait for it, from a thread."""
    future = asyncio.run_coroutine_threadsafe(coro, _ensure_loop())
    try:
        return future.result(timeout)
    except FutureTimeout:
        future.cancel()
        raise TimeoutError("the model did not answer in time")


def _openai():
    global _client, _client_key
    key = getattr(config, "openai_api_key", "")
    if not key:
        raise NoKey("This machine has no OPENAI_API_KEY, so Synapse cannot ask OpenAI anything.")
    if _client is None or key != _client_key:
        _client = llmlog.openai_client(key, max_retries=1, timeout=120.0)
        _client_key = key
    return _client


def is_claude(model: str) -> bool:
    return str(model or "").startswith("claude-")


def _anthropic():
    """Anthropic's client, for whichever of Synapse's model jobs the Models page has on a Claude model."""
    global _claude, _claude_key
    key = getattr(config, "anthropic_api_key", "")
    if not key:
        raise NoKey("This machine has no ANTHROPIC_API_KEY, so Synapse cannot ask Claude anything.")
    if _claude is None or key != _claude_key:
        _claude = llmlog.client(key, max_retries=2, timeout=300.0)
        _claude_key = key
    return _claude


def _usage_of(usage) -> dict:
    """OpenAI's usage, in the names `costs` reads."""
    if usage is None:
        return {}
    if not isinstance(usage, dict):
        usage = usage.model_dump() if hasattr(usage, "model_dump") else dict(usage)
    details = usage.get("input_tokens_details") or {}
    sent = int(usage.get("input_tokens", usage.get("prompt_tokens", 0)) or 0)
    read = int((details or {}).get("cached_tokens") or 0)
    return {"input_tokens": max(0, sent - read), "output_tokens": int(usage.get("output_tokens") or 0),
            "cache_read_input_tokens": read, "cache_creation_input_tokens": 0}


def price(usage: dict, model: str) -> float:
    got = costs.request_cost(usage, model) if usage else None
    return float(got or 0.0)


def _about(trace, purpose: str, owner: dict | None):
    owner = owner or {}
    return llmlog.about(purpose=f"synapse_{purpose}",
                        subject=f"synapse/{trace.dataset_id}/{trace.id}" if trace else "synapse",
                        user_id=owner.get("user_id") or None, org_id=owner.get("org_id") or None)


# --- embeddings ------------------------------------------------------------------------

async def _embed(texts: list[str], model: str, about, input_type: str) -> tuple[list[list[float]], dict, str]:
    if is_voyage(model):
        return await _embed_voyage(texts, model, about, input_type)
    client = _openai()
    with about:
        got = await client.embeddings.create(model=model, input=texts, dimensions=EMBED_DIMS)
    vectors = [d.embedding for d in got.data]
    usage = {"input_tokens": int(getattr(got.usage, "prompt_tokens", 0) or 0), "output_tokens": 0}
    return vectors, usage, str(getattr(got, "model", model) or model)


def voyage_url(endpoint: str | None = None) -> str:
    """Voyage's embeddings address, from `VOYAGE_ENDPOINT` however it was
    written: a host (MongoDB's, for an Atlas key), a base ending in `/v1`, or
    the whole address. Nothing said is Voyage's own address. `endpoint` is one
    being checked in Settings before it is kept (`rouh/service_keys.py`)."""
    said = (getattr(config, "voyage_endpoint", "") if endpoint is None else endpoint) or ""
    said = said.strip().strip('"').strip("'").rstrip("/")
    base = said or llmlog.VOYAGE_DEFAULT
    if "://" not in base:
        base = "https://" + base
    if base.endswith("/embeddings"):
        return base
    if not base.endswith("/v1"):
        base += "/v1"
    return base + "/embeddings"


def _voyage_client():
    global _voyage
    if _voyage is None:
        import httpx
        _voyage = llmlog.voyage_client(timeout=httpx.Timeout(120.0, connect=15.0))
    return _voyage


async def _embed_voyage(texts: list[str], model: str, about, input_type: str):
    """One request to Voyage AI's embeddings API (docs.voyageai.com, "Text
    embeddings"; MongoDB's own address for an Atlas key): bearer key, the
    texts as `input`, `input_type` query or document, 1,024 numbers each."""
    key = getattr(config, "voyage_api_key", "") or ""
    if not key:
        raise NoKey("There is no Voyage AI key, so Synapse cannot make voyage-4 vectors: the owner adds "
                    "one in Anatomy, Connections, Keys, never in a chat.")
    body = {"input": texts, "model": model, "input_type": input_type, "output_dimension": EMBED_DIMS}
    with about:
        try:
            r = await _voyage_client().post(voyage_url(), json=body,
                                            headers={"Authorization": "Bearer " + key})
        except Exception as exc:  # noqa: BLE001 - said as Voyage's, never with the key
            raise VoyageError(f"Voyage AI could not be reached ({type(exc).__name__})") from None
    if r.status_code >= 400:
        try:
            said = r.json().get("detail") or r.json().get("error") or r.text
        except ValueError:
            said = r.text
        said = str(said).replace(key, "[key]")[:300]
        try:
            after = float(r.headers.get("retry-after") or 0)
        except ValueError:
            after = 0.0
        raise VoyageError(f"Voyage AI answered {r.status_code}: {said}", r.status_code, after)
    got = r.json()
    data = sorted(got.get("data") or [], key=lambda d: d.get("index", 0))
    vectors = [d["embedding"] for d in data]
    if len(vectors) != len(texts) or any(len(v) != EMBED_DIMS for v in vectors):
        raise VoyageError(f"Voyage AI sent {len(vectors)} vectors of {len(vectors[0]) if vectors else 0} numbers "
                          f"for {len(texts)} texts at {EMBED_DIMS}")
    usage = {"input_tokens": int((got.get("usage") or {}).get("total_tokens") or 0), "output_tokens": 0}
    return vectors, usage, str(got.get("model") or model)


#: How long to wait before asking Voyage again after a 429 or a 5xx: a key with
#: no payment method behind it is held to 3 requests and 10,000 tokens a
#: minute (MongoDB's rate limit page), which a busy minute meets. A question
#: waits once, briefly, and then goes on with words alone; stored work waits
#: the minute out.
WAITS = {"query": (2.0,), "document": (5.0, 15.0, 30.0, 60.0)}
#: A request carries at most this many characters, so one request stays
#: inside the free tier's 10,000 tokens a minute (Bulgarian runs near three
#: characters a token).
VOYAGE_CHARS = 24000


def _chunks(texts: list[str], model: str) -> list[list[str]]:
    texts = [t[:24000] or " " for t in texts]
    if not is_voyage(model):
        return [texts[i:i + 64] for i in range(0, len(texts), 64)]
    out, now, size = [], [], 0
    for t in texts:
        if now and (len(now) >= 64 or size + len(t) > VOYAGE_CHARS):
            out.append(now)
            now, size = [], 0
        now.append(t)
        size += len(t)
    if now:
        out.append(now)
    return out


def _sleep(seconds: float) -> None:
    time.sleep(seconds)


def embed(texts: list[str], *, model: str, trace=None, purpose: str = "embed", items=(),
          owner: dict | None = None, input_type: str = "document") -> list[list[float]]:
    """Vectors for these texts, written down on the trace.

    `input_type` is `query` for a question and `document` for anything
    stored: Voyage makes the two differently, so that a question lands near
    what answers it. OpenAI's models make no difference between them.
    """
    if input_type not in WAITS:
        raise ValueError("input_type is query or document")
    backend = "voyage" if is_voyage(model) else "openai"
    out: list[list[float]] = []
    for chunk in _chunks(texts, model):
        waits = list(WAITS[input_type])
        began = time.time()
        while True:
            try:
                vectors, usage, served = run(_embed(chunk, model, _about(trace, purpose, owner), input_type), 130)
                break
            except VoyageError as exc:
                if exc.status in (429, 500, 502, 503, 504) and waits:
                    _sleep(min(exc.retry_after or waits[0], 60.0))
                    waits.pop(0)
                    continue
                _failed(trace, purpose, backend, model, began, items, exc)
                raise
            except Exception as exc:
                _failed(trace, purpose, backend, model, began, items, exc)
                raise
        if trace is not None:
            trace.call(kind="embed", purpose=purpose, backend=backend, model=model, version=served,
                       ms=int((time.time() - began) * 1000), tokens_in=usage["input_tokens"],
                       cost=price(usage, model), items=items)
        out.extend(vectors)
    return out


def _failed(trace, purpose, backend, model, began, items, exc) -> None:
    if trace is not None:
        trace.call(kind="embed", purpose=purpose, backend=backend, model=model,
                   ms=int((time.time() - began) * 1000), items=items, ok=False,
                   error=f"{type(exc).__name__}: {exc}")


# --- generative ------------------------------------------------------------------------

async def _generate_claude(model: str, instructions: str, text: str, schema: dict,
                           effort: str, max_tokens: int, about, cache: bool = False) -> tuple[dict, dict, str]:
    """The same structured answer from Claude: JSON held to the schema by `output_config.format`.
    Thinking is adaptive on the 5 generation, so the output allowance covers it too; Haiku 4.5 takes no
    effort at all, and is not sent one. `cache` marks the instructions for the prompt cache, for a call
    whose instructions are the same many times over (automatic recall's reading)."""
    output = {"format": {"type": "json_schema", "schema": schema}}
    if effort and config_takes_effort(model):
        output["effort"] = effort
    system = [{"type": "text", "text": instructions, "cache_control": {"type": "ephemeral"}}] if cache else instructions
    with about:
        got = await _anthropic().messages.create(
            model=model, max_tokens=max(int(max_tokens), 16000), system=system,
            messages=[{"role": "user", "content": text}], output_config=output)
    if got.stop_reason == "refusal":
        raise RuntimeError(f"{model} declined to answer")
    words = next((b.text for b in got.content if b.type == "text"), "")
    try:
        parsed = json.loads(words) if words else {}
    except ValueError:
        parsed = {}
    u = got.usage
    usage = {"input_tokens": int(u.input_tokens or 0), "output_tokens": int(u.output_tokens or 0),
             "cache_read_input_tokens": int(getattr(u, "cache_read_input_tokens", 0) or 0),
             "cache_creation_input_tokens": int(getattr(u, "cache_creation_input_tokens", 0) or 0)}
    return parsed, usage, str(got.model or model)


async def _generate_compat(model: str, instructions: str, text: str, schema: dict, name: str,
                           effort: str, max_tokens: int, about) -> tuple[dict, dict, str]:
    """The same structured answer from Google's Gemini or xAI's Grok (24 October 2026), through
    their Chat Completions APIs, with the JSON held to the schema by `response_format`, asked
    through the LLM service's recording client with the organisation's key."""
    from .. import llm
    from ..config import config as _cfg, provider_of

    provider = provider_of(model)
    body = dict(model=model, messages=[{"role": "system", "content": instructions},
                                       {"role": "user", "content": text}],
                response_format={"type": "json_schema",
                                 "json_schema": {"name": name, "schema": schema, "strict": True}},
                max_completion_tokens=max(int(max_tokens), 4000) + 8000)
    level = llm.compat_effort(provider, model, effort)
    if level:
        body["reasoning_effort"] = level
    with about:
        got = await llm._client(provider, _cfg).chat.completions.create(**body)
    words = (got.choices[0].message.content or "") if got.choices else ""
    try:
        parsed = json.loads(words) if words else {}
    except ValueError:
        parsed = {}
    u = getattr(got, "usage", None)
    details = getattr(u, "prompt_tokens_details", None)
    cached = int(getattr(details, "cached_tokens", 0) or 0) if details is not None else 0
    usage = {"input_tokens": max(0, int(getattr(u, "prompt_tokens", 0) or 0) - cached),
             "output_tokens": int(getattr(u, "completion_tokens", 0) or 0),
             "cache_read_input_tokens": cached, "cache_creation_input_tokens": 0}
    return parsed, usage, str(getattr(got, "model", model) or model)


async def _generate(model: str, instructions: str, text: str, schema: dict, name: str,
                    effort: str, max_tokens: int, about, cache_key: str = "") -> tuple[dict, dict, str]:
    if is_claude(model):
        return await _generate_claude(model, instructions, text, schema, effort, max_tokens, about,
                                      cache=bool(cache_key))
    if str(model or "").startswith(("gemini-", "grok-")):
        return await _generate_compat(model, instructions, text, schema, name, effort, max_tokens, about)
    client = _openai()
    body = dict(model=model, instructions=instructions, input=text,
                text={"format": {"type": "json_schema", "name": name, "schema": schema, "strict": True}},
                max_output_tokens=max_tokens)
    if effort and not model.startswith("gpt-4"):
        body["reasoning"] = {"effort": effort}
        if effort != "none":
            body["reasoning"]["summary"] = "auto"
    if cache_key:
        # Requests with the same long start sent to the same cache, so it is read rather than paid again.
        body["prompt_cache_key"] = cache_key
    with about:
        got = await client.responses.create(**body)
    words = getattr(got, "output_text", "") or ""
    try:
        parsed = json.loads(words) if words else {}
    except ValueError:
        parsed = {}
    return parsed, _usage_of(getattr(got, "usage", None)), str(getattr(got, "model", model) or model)


def backend_of(model: str) -> str:
    from ..config import provider_of

    return provider_of(model)


def generate(*, model: str, instructions: str, text: str, schema: dict, name: str,
             purpose: str, trace=None, items=(), effort: str | None = None, max_tokens: int = 4000,
             owner: dict | None = None, timeout: float = 180.0, cache_key: str = "") -> dict:
    """One structured answer from a generative model, written down on the trace.

    `model` is the one the Models page has for the job asking (`numbers.MODEL_USES`): nothing here
    picks or swaps one. It thinks at the level that comes with it (`modelstandard.effort`) unless
    `effort` says otherwise."""
    if effort is None:
        from .. import modelstandard

        effort = modelstandard.effort(model)
        effort = "" if effort == "none" and is_claude(model) else effort
    began = time.time()
    try:
        parsed, usage, served = run(_generate(model, instructions, text, schema, name, effort, max_tokens,
                                              _about(trace, purpose, owner), cache_key), timeout)
    except Exception as exc:
        if trace is not None:
            trace.call(kind="generate", purpose=purpose, backend=backend_of(model), model=model,
                       ms=int((time.time() - began) * 1000), items=items, ok=False,
                       error=f"{type(exc).__name__}: {exc}")
        raise
    ms, cost = int((time.time() - began) * 1000), price(usage, model)
    if trace is not None:
        trace.call(kind="generate", purpose=purpose, backend=backend_of(model), model=model, version=served,
                   ms=ms, tokens_in=usage.get("input_tokens", 0) + usage.get("cache_read_input_tokens", 0),
                   tokens_out=usage.get("output_tokens", 0), cost=cost, items=items)
    parsed.update({"_model": served, "_ms": ms, "_cost": cost, "_usage": usage})
    return parsed


# --- decisions (D66) ---------------------------------------------------------------------

def Choice(qid: str, prompt: str, options: list[str]) -> dict:
    return {"id": qid, "type": "choice", "prompt": prompt, "options": list(options)[:255]}


def Score(qid: str, prompt: str, levels: list[str]) -> dict:
    return {"id": qid, "type": "score", "prompt": prompt, "levels": list(levels)[:10]}


def Noul(qid: str, prompt: str) -> dict:
    return {"id": qid, "type": "noul", "prompt": prompt}


RANK = {"normal": 0, "unlabelled": 1, "private": 1, "special": 2}

DECIDE_INSTRUCTIONS = (
    "You are a decision model. You are given a STATE and numbered questions. Answer every "
    "question with exactly one of its allowed labels and nothing else. Judge only from the "
    "STATE. For a yes or no question answer Y or N.")


def _labels(q: dict) -> list[str]:
    if q["type"] == "noul":
        return ["Y", "N"]
    count = len(q["options"] if q["type"] == "choice" else q["levels"])
    return [str(i + 1) for i in range(count)]


def _question_text(key: str, q: dict) -> str:
    if q["type"] == "noul":
        return f"{key} (Y or N): {q['prompt']}"
    names = q["options"] if q["type"] == "choice" else q["levels"]
    head = "pick one number" if q["type"] == "choice" else "pick one level, 1 is the lowest"
    return f"{key} ({head}): {q['prompt']}\n" + "\n".join(
        f"   {i + 1} = {name}" for i, name in enumerate(names))


def _read_probabilities(text: str, logprobs: list, keys: list[str], labels: dict) -> dict:
    """Each question's labels with their probabilities, from the answer's tokens."""
    spans, at = [], 0
    for tok in logprobs or []:
        token = tok.get("token", "") if isinstance(tok, dict) else getattr(tok, "token", "")
        spans.append((at, at + len(token), tok))
        at += len(token)
    out = {}
    for key in keys:
        marker = f'"{key}":"'
        pos = text.find(marker)
        if pos < 0:
            marker = f'"{key}": "'
            pos = text.find(marker)
        if pos < 0:
            continue
        start = pos + len(marker)
        found = None
        for begin, end, tok in spans:
            if begin <= start < end or (begin == start and end > begin):
                found = (begin, tok)
                break
        allowed = labels[key]
        probs = {label: 0.0 for label in allowed}
        if found is not None:
            begin, tok = found
            tops = tok.get("top_logprobs") if isinstance(tok, dict) else getattr(tok, "top_logprobs", None)
            tops = tops or [tok]
            for alt in tops:
                alt_token = alt.get("token", "") if isinstance(alt, dict) else getattr(alt, "token", "")
                alt_lp = alt.get("logprob", -100) if isinstance(alt, dict) else getattr(alt, "logprob", -100)
                piece = alt_token[start - begin:] if len(alt_token) > start - begin else ""
                label = piece.strip().strip('",}').strip()
                if label in probs:
                    probs[label] += math.exp(float(alt_lp))
        total = sum(probs.values())
        if total <= 0:
            # No alternatives were readable: the label written is taken as certain.
            chosen = text[start:start + 4].split('"')[0]
            if chosen in probs:
                probs[chosen] = 1.0
                total = 1.0
        if total > 0:
            probs = {k: v / total for k, v in probs.items()}
        out[key] = probs
    return out


def _shape_answer(q: dict, probs: dict, backend: str, version: str, ms: int, extra: dict) -> dict:
    labels = _labels(q)
    if q["type"] == "noul":
        p_yes = float(probs.get("Y", 0.0))
        return {"p_yes": p_yes, "probabilities": {"yes": p_yes, "no": 1 - p_yes},
                "confidence": max(p_yes, 1 - p_yes), "backend": backend, "version": version,
                "ms": ms, **extra}
    names = q["options"] if q["type"] == "choice" else q["levels"]
    named = {names[i]: float(probs.get(label, 0.0)) for i, label in enumerate(labels)}
    best = max(named, key=named.get) if named else ""
    answer = {"probabilities": named, "confidence": named.get(best, 0.0), "backend": backend,
              "version": version, "ms": ms, **extra}
    if q["type"] == "choice":
        answer["pick"] = best
    else:
        count = max(1, len(names) - 1)
        answer["score"] = sum(i * named[n] for i, n in enumerate(names)) / count
        answer["level"] = best
    return answer


async def _generative_decide(model: str, state: str, questions: list[dict], about) -> tuple[dict, dict, str]:
    keys = [f"q{i + 1}" for i in range(len(questions))]
    labels = {k: _labels(q) for k, q in zip(keys, questions)}
    schema = {"type": "object", "additionalProperties": False, "required": keys,
              "properties": {k: {"type": "string", "enum": labels[k]} for k in keys}}
    text = ("STATE:\n" + state + "\n\nQUESTIONS:\n" +
            "\n".join(_question_text(k, q) for k, q in zip(keys, questions)))
    client = _openai()
    body = dict(model=model, instructions=DECIDE_INSTRUCTIONS, input=text, temperature=0,
                text={"format": {"type": "json_schema", "name": "decisions", "schema": schema,
                                 "strict": True}},
                include=["message.output_text.logprobs"], top_logprobs=20,
                max_output_tokens=40 + 12 * len(keys))
    with about:
        got = await client.responses.create(**body)
    raw = got.model_dump() if hasattr(got, "model_dump") else dict(got)
    words, logprobs = "", []
    for item in raw.get("output") or []:
        if item.get("type") == "message":
            for part in item.get("content") or []:
                if part.get("type") == "output_text":
                    words += part.get("text") or ""
                    logprobs.extend(part.get("logprobs") or [])
    probs = _read_probabilities(words, logprobs, keys, labels)
    return probs, _usage_of(raw.get("usage")), str(raw.get("model") or model)


def _hosted_questions(questions: list[dict]) -> list[dict]:
    """The spec's questions (D66) as the Decisions API asks them (`llm.choice`, `llm.score`,
    `llm.predicate`): a Noul is a predicate, each named by its own id, which its answer
    comes back with."""
    from .. import llm

    out = []
    for q in questions:
        if q["type"] == "noul":
            out.append(llm.predicate(q["id"], q["prompt"]))
        elif q["type"] == "choice":
            out.append(llm.choice(q["id"], q["prompt"], q["options"]))
        else:
            out.append(llm.score(q["id"], q["prompt"], q["levels"]))
    return out


def _hosted_probabilities(got, questions: list[dict]) -> dict:
    """Each question's probabilities by the labels `_shape_answer` reads ("Y" and "N", or a
    choice's and a level's place from 1), from what the Decisions API said. A question it
    refused is left out, so its point takes its fallback (D69)."""
    probs = {}
    for i, q in enumerate(questions):
        a = got.answer(q["id"])
        if a is None or a.refused:
            continue
        if q["type"] == "noul":
            p = float(a.probability or 0.0)
            probs[f"q{i + 1}"] = {"Y": p, "N": 1 - p}
        else:
            names = q["options"] if q["type"] == "choice" else q["levels"]
            probs[f"q{i + 1}"] = {str(j + 1): float(a.probabilities.get(n, 0.0)) for j, n in enumerate(names)}
    return probs


async def _hosted_decide(model: str, state: str, questions: list[dict], purpose: str,
                         about) -> tuple[dict, dict, str]:
    """OpenAI's Decisions API, with the model the Models page has for it
    (`synapse_decisions_api`), through the one Decisions client (`llm.decide_model`): the
    state is its input, and each question is asked as its own kind. Until 23 October 2026
    this was its own request, written before OpenAI published the API, which sent the
    spec's `purpose`, `state` and `questions` as they were and read answers keyed by id."""
    from .. import llm

    with about:
        got = await llm.decide_model(model, input=state, questions=_hosted_questions(questions))
    return _hosted_probabilities(got, questions), got.usage, got.model


def decisions_status(org_id: str) -> dict:
    got = db.row("SELECT status, said, checked_at FROM synapse.backend_status "
                 "WHERE org_id = %s AND name = 'openai_decisions'", (org_id,))
    return got or {"status": "unknown", "said": "Not asked yet.", "checked_at": None}


def _set_status(org_id: str, status: str, said: str) -> None:
    db.run("INSERT INTO synapse.backend_status (org_id, name, status, said, checked_at) "
           "VALUES (%s, 'openai_decisions', %s, %s, now()) ON CONFLICT (org_id, name) DO UPDATE "
           "SET status = excluded.status, said = excluded.said, checked_at = now()",
           (org_id, status, said[:500]))


def probe_decisions(org_id: str, owner: dict | None = None) -> dict:
    """Ask the Decisions API one tiny question, to learn whether this key may use it, with the
    decision backend's model from the Models page."""
    from .. import modeldefaults

    if not have_key():
        _set_status(org_id, "no_key", "This machine has no OpenAI key.")
        return decisions_status(org_id)
    q = [Noul("q1", "Is this a greeting?")]
    try:
        model = modeldefaults.use_model("synapse_decisions_api", org_id or None)
        run(_hosted_decide(model, "Hello ‹owner›.", q, "probe", _about(None, "decisions_probe", owner)), 30)
        _set_status(org_id, "open", "The Decisions API answered.")
    except Exception as exc:
        status = getattr(exc, "status_code", None)
        said = getattr(exc, "message", "") or str(exc)
        _set_status(org_id, "refused" if status in (401, 403, 404) else "error",
                    f"{status or type(exc).__name__}: {said}"[:500])
    return decisions_status(org_id)


def _hosted_open(org_id: str, owner: dict | None) -> tuple[bool, str]:
    st = decisions_status(org_id)
    checked = st.get("checked_at")
    stale = True
    if checked is not None:
        try:
            stale = (time.time() - checked.timestamp()) > PROBE_EVERY
        except Exception:  # noqa: BLE001
            stale = True
    if st.get("status") in ("unknown", None) or stale:
        st = probe_decisions(org_id, owner)
    return st.get("status") == "open", st.get("said") or ""


def _spent_today(org_id: str, backend: str) -> float:
    return float(db.value("SELECT usd FROM synapse.spend WHERE org_id = %s AND day = current_date "
                          "AND backend = %s", (org_id, backend)) or 0.0)


def _spend(org_id: str, backend: str, usd: float) -> None:
    db.run("INSERT INTO synapse.spend (org_id, day, backend, usd) VALUES (%s, current_date, %s, %s) "
           "ON CONFLICT (org_id, day, backend) DO UPDATE SET usd = synapse.spend.usd + excluded.usd",
           (org_id, backend, round(usd, 6)))


def backend_for(purpose: str, settings) -> str:
    if not settings.get("decision_models", False):
        return "off"
    return str(settings.get("dm_" + purpose, "generative"))


def decide(purpose: str, state: str, questions: list[dict], *, ceiling: str, settings, trace=None,
           items=(), live: bool = False, owner: dict | None = None) -> dict:
    """Ask a decision model: `{"answers": {id: answer}, "backend", "asked", "why", ...}`.

    `ceiling` is the most sensitive item in the state (D67). An answer that
    cannot be had (the point is off, the call failed or timed out) comes back
    with `answers` empty and `fallback` saying why, and the caller takes its
    fallback (D69).
    """
    owner = owner or {}
    org_id = owner.get("org_id") or ""
    asked = backend_for(purpose, settings)
    meta = {"purpose": purpose, "asked": asked, "backend": asked, "why": "", "answers": {},
            "fallback": "", "questions": questions, "ceiling": ceiling}
    if asked == "off":
        meta["fallback"] = "This decision point is off, so the spec's fallback is used (D69)."
        return meta
    backend = asked
    if backend == "openai_decisions":
        reasons = []
        if RANK.get(ceiling, 1) > 0:
            reasons.append(f"the state holds a {ceiling} item, and only normal items may go to a "
                           "hosted decision model (D67)")
        elif not settings.get("hosted_allowed", True):
            reasons.append("hosted decision calls are not allowed (Q17)")
        elif _spent_today(org_id, "openai_decisions") >= float(settings.get("daily_cap_usd", 1.0)):
            reasons.append("today's hosted spend cap is reached (D69)")
        else:
            is_open, said = _hosted_open(org_id, owner)
            if not is_open:
                reasons.append(f"the Decisions API is not open to this key ({said})")
        if reasons:
            backend = "generative"
            meta["why"] = "Answered by the generative backend because " + "; ".join(reasons) + "."
    meta["backend"] = backend
    # The Models page's model for the decision backend (`numbers.MODEL_USES`), whichever backend asks.
    model = str(settings.decision_model)
    timeout = (float(settings.get("live_timeout_ms", 300)) / 1000.0 if live
               else float(settings.get("background_timeout_s", 10)))
    began = time.time()
    about = _about(trace, "decide_" + purpose, owner)
    try:
        if backend == "openai_decisions":
            model = str(settings.decisions_api_model)
            probs, usage, version = run(_hosted_decide(model, state, questions, purpose, about), timeout + 5)
            used_model = model
        else:
            if not model.startswith("gpt-4.1"):
                # Never another model instead: the point takes its fallback, and says why.
                raise ValueError(f"{model} gives no log probabilities for the other answers, which this "
                                 "backend reads: put Synapse's decision backend on GPT-4.1 Mini or Nano "
                                 "on the Models page")
            coro = _generative_decide(model, state, questions, about)
            probs, usage, version = run(asyncio.wait_for(coro, timeout), timeout + 5)
            used_model = model
    except Exception as exc:
        ms = int((time.time() - began) * 1000)
        timed = isinstance(exc, (asyncio.TimeoutError, TimeoutError))
        meta["fallback"] = (f"The call took longer than its {int(timeout * 1000)} ms limit, so the "
                            "point took its fallback (D69)." if timed else
                            f"The call failed ({type(exc).__name__}: {exc}), so the point took its "
                            "fallback (D69).")
        meta["ms"] = ms
        if trace is not None:
            trace.call(kind="decide", purpose=purpose, backend=backend,
                       model=model,
                       ms=ms, items=items, ok=False, error=meta["fallback"])
        return meta
    ms = int((time.time() - began) * 1000)
    # A decision is priced on its input alone (`costs.decision_cost`); the generative backend
    # as any other answer.
    cost = (float(costs.decision_cost(usage, used_model) or 0.0) if backend == "openai_decisions"
            else price(usage, used_model))
    if backend == "openai_decisions":
        _spend(org_id, backend, cost)
    if trace is not None:
        trace.call(kind="decide", purpose=purpose, backend=backend, model=used_model, version=version,
                   ms=ms, tokens_in=usage.get("input_tokens", 0) + usage.get("cache_read_input_tokens", 0),
                   tokens_out=usage.get("output_tokens", 0), cost=cost, items=items)
    extra = {"model": used_model}
    for i, q in enumerate(questions):
        meta["answers"][q["id"]] = _shape_answer(q, probs.get(f"q{i + 1}", {}), backend, version, ms, extra)
    meta["ms"] = ms
    meta["cost"] = cost
    meta["version"] = version
    meta["model"] = used_model
    return meta


def decide_many(purpose: str, state: str, questions: list[dict], *, per_call: int = 30, **kw) -> dict:
    """The same, in batches of `per_call` questions sent at once (D70: 100 in 4 calls)."""
    if len(questions) <= per_call:
        return decide(purpose, state, questions, **kw)
    chunks = [questions[i:i + per_call] for i in range(0, len(questions), per_call)]
    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=min(6, len(chunks))) as pool:
        parts = list(pool.map(lambda c: _decide_in_thread(purpose, state, c, kw), chunks))
    merged = dict(parts[0])
    merged["answers"] = {}
    merged["calls"] = len(parts)
    merged["cost"] = sum(float(p.get("cost") or 0) for p in parts)
    merged["ms"] = max(int(p.get("ms") or 0) for p in parts)
    merged["questions"] = questions
    fallbacks = [p.get("fallback") for p in parts if p.get("fallback")]
    merged["fallback"] = fallbacks[0] if fallbacks and len(fallbacks) == len(parts) else ""
    merged["partial"] = bool(fallbacks) and len(fallbacks) < len(parts)
    for p in parts:
        merged["answers"].update(p.get("answers") or {})
    return merged


def _decide_in_thread(purpose, state, chunk, kw):
    from django.db import connection

    try:
        return decide(purpose, state, chunk, **kw)
    finally:
        connection.close()
