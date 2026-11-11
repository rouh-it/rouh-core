"""Every request Rouh makes of a model, written down.

Petar, 26 September 2026 (fr_c2ebaf6fa3e0): "Could you build me a new
database model - full log of every single LLM request we do, including cost,
reasoning etc. We have it build in [another project] ... feel free to copy the
model/implementation if you like it. Any improvements you see on the fly are
welcome."

So every request any part of Rouh sends to a model is a row of
`llm_requests` (`rouh/models/llmlog.py`): what was asked, what came back, the
reasoning the model returned, the four token counts and the web searches, the
cost at list price, how long it took to the first word and to the end, what it
was for, and whose it was - the person, their organisation, the chat and the
turn.

What the earlier one does, and what this does differently
---------------------------------------------------------

The earlier project's `LLMInteraction` (`automation/models.py`), written through
`usage.api.record_event`, is where this started, and everything it keeps is
kept here: the provider and model, the prompt and the response, the settings
sent and the metadata that came back, the token counts with both cache
figures, the estimated cost, the purpose and the object it was for, the
status and error, the duration, the user and the organisation. Four things are
done differently, each because it is a way the original loses a request or a
cost:

- **It is written where the bytes go out, not where the code asks.** The earlier
  project records from each wrapper that remembers to, and a call retried to success
  leaves only its success. Here every Anthropic client in Rouh is made by
  `client()`, whose HTTP client writes a row for every request it sends: each
  retry, the SDK's own included (`attempt`), a request stopped half way
  because the person interrupted or the answer turned out not to be wanted, a
  request that failed before a byte came back, and one the process went away
  in the middle of, whose row still says "sent". A client made any other way
  is the one way past this, so there is no other way in this repository.
- **What was asked is kept once.** A turn sends the whole conversation again
  with every request, and every turn sends the same system prompt and tools:
  in a week in September that was about twelve million tokens a day, most of
  it sent before. Kept whole in every row that is gigabytes a month; kept as
  pieces (`llm_pieces`), each system prompt, tool list and message once, it is
  about what the transcripts take. `request_of` puts one back together.
- **The reasoning and the answer have columns of their own** (`reasoning`,
  `text`), rather than being dug out of a metadata blob. Readable reasoning
  summaries are kept there; encrypted reasoning credentials and provider
  signatures are removed from the request and response copies in the log.
- **Nothing waits for the database.** Rows are written by one thread of their
  own, in the order things happened, so a spoken turn is never slower for being
  written down, and a database that is down costs a warning in the log and
  never a turn.

What is said about a request
----------------------------

The code making a request says what it is for with `about(...)`, which holds
for every request made inside it and every task started inside it:
`about(purpose="chat_title", session_id=chat_id)`. The person comes from the
context the socket already sets for a turn (`tenancy.speaker`); a request made
with nobody speaking - a background job - belongs to the install's one person
when it has exactly one, as everything else in Rouh does, and to nobody named
when it has more. A request nobody said anything about is still written down,
under the name of the code that sent it (`caller`).

Prompts and answers are kept as the transcripts in `messages` are, in plain
text: they are the same words, and a log nobody can read is not the log that
was asked for. Credentials never reach it: the API key travels in a header,
and no header is written down but Anthropic's request id.

A request that is stopped before it finishes has the output tokens the API
had reported by then, which is fewer than it was billed for: the true count
only arrives at the end, and nobody was reading any more.
"""
from __future__ import annotations

import asyncio
import atexit
import contextlib
import contextvars
import hashlib
import json
import logging
import os
import queue
import sys
import threading
import time
from decimal import Decimal

from django.db import connection, transaction

import anthropic
import httpx

log = logging.getLogger("rouh.llmlog")

#: What this names every row's provider: Anthropic's Messages API, and since
#: 26 September 2026 OpenAI's Responses API as well, for Luna (`rouh/luna.py`).
PROVIDER = "anthropic"
OPENAI = "openai"
#: And since 3 October 2026 Voyage AI's embeddings, which Synapse searches by
#: meaning with (`rouh/synapse/ai.py`, spec D37).
VOYAGE = "voyage"
#: Google's Gemini API and xAI's, asked through their OpenAI-compatible Chat Completions
#: endpoints with OpenAI's SDK (`compat_client`) since 24 October 2026.
GOOGLE = "google"
XAI = "xai"
COMPAT = (GOOGLE, XAI)
#: Their OpenAI-compatible endpoints (ai.google.dev/gemini-api/docs/openai, docs.x.ai), kept
#: here as every provider's address is (`rouh/llmguard.py`). `config.google_base_url` and
#: `config.xai_base_url` put a stand-in in front of them.
COMPAT_URLS = {GOOGLE: "https://generativelanguage.googleapis.com/v1beta/openai/",
               XAI: "https://api.x.ai/v1"}

#: Where Voyage AI answers when nothing says otherwise. A key made in MongoDB
#: Atlas, where Voyage's keys are made since MongoDB bought it, answers only
#: at `ai.mongodb.com` and refuses this address with a 403; the server says
#: which in `VOYAGE_ENDPOINT` (`Config.voyage_endpoint`).
VOYAGE_DEFAULT = "https://api.voyageai.com"

#: What the requests made in this context are for, and whose they are.
_ABOUT: contextvars.ContextVar[dict | None] = contextvars.ContextVar(
    "rouh_llm_about", default=None)

#: What `about` may say.
FIELDS = ("purpose", "subject", "session_id", "turn_id", "user_id", "org_id", "attempt")

#: This package's folder, for naming the code that sent a request.
_HERE = os.path.dirname(os.path.abspath(__file__))


@contextlib.contextmanager
def about(who=None, **said):
    """Say what the requests made inside this block are for, and whose they are.

    `who` is an `Identity`, for a request made on somebody's behalf with no
    socket in between (Ask AI, from a page). Everything else is one of
    `FIELDS`. A block inside another adds to what the outer one said, and a
    task started inside it keeps what it said after the block has ended, which
    is how a turn's own tasks carry its name.
    """
    unknown = set(said) - set(FIELDS)
    if unknown:
        raise TypeError(f"llmlog.about does not take {', '.join(sorted(unknown))}")
    now = dict(_ABOUT.get() or {})
    if who is not None:
        now["user_id"] = str(getattr(who, "user_id", "") or "")
        now["org_id"] = str(getattr(who, "org_id", "") or "")
    now.update({k: v for k, v in said.items() if v not in (None, "")})
    token = _ABOUT.set(now)
    try:
        yield now
    finally:
        _ABOUT.reset(token)


def current() -> dict:
    """What `about` says for requests made here: the purpose, the chat, the turn."""
    return dict(_ABOUT.get() or {})


class said:
    """A stream from the SDK, opened with this said about it.

    For an async generator, which `about` must not span: what a generator sets
    in its context is set in whoever is reading it until the generator ends,
    and a generator closed by a reader who went away is closed in another
    context altogether. The request goes out when the stream is opened, so the
    opening is the only part that needs saying anything.

        async with llmlog.said(client.messages.stream(...), purpose="askai") as stream:
    """

    def __init__(self, stream, who=None, **fields) -> None:
        self.stream = stream
        self.who = who
        self.fields = fields

    async def __aenter__(self):
        with about(self.who, **self.fields):
            return await self.stream.__aenter__()

    async def __aexit__(self, *exc):
        return await self.stream.__aexit__(*exc)


def client(api_key: str, **options) -> anthropic.AsyncAnthropic:
    """The Anthropic client every part of Rouh asks a model with.

    The SDK's own client, with the SDK's own defaults, over an HTTP client
    that writes down every request it sends. `options` go to the SDK, which is
    where `max_retries=0` goes for a caller that retries by itself.
    """
    return anthropic.AsyncAnthropic(api_key=api_key, http_client=Recording(), **options)


def openai_client(api_key: str, **options):
    """The OpenAI client Luna is asked with, written down the same way.

    The one way an OpenAI client is made in Rouh, for the same reason as
    `client`: a request made any other way is a request nobody can see.
    """
    import httpx2
    import openai

    class OpenAIRecording(_Recording, openai.DefaultAsyncHttpxClient):
        provider = OPENAI
        tee = _tee_on(httpx2.AsyncByteStream)

    guard()
    return openai.AsyncOpenAI(api_key=api_key, http_client=OpenAIRecording(), **options)


def compat_client(provider: str, api_key: str, base_url: str = "", **options):
    """OpenAI's SDK pointed at Google's or xAI's OpenAI-compatible endpoint, written down the
    same way as OpenAI's own, under that provider (`GOOGLE`, `XAI`)."""
    import httpx2
    import openai

    class CompatRecording(_Recording, openai.DefaultAsyncHttpxClient):
        tee = _tee_on(httpx2.AsyncByteStream)

    CompatRecording.provider = provider
    guard()
    return openai.AsyncOpenAI(api_key=api_key, base_url=base_url or COMPAT_URLS[provider],
                              http_client=CompatRecording(),
                              **options)


def voyage_client(**options) -> httpx.AsyncClient:
    """The HTTP client Voyage AI's embeddings are asked with, written down the
    same way.

    Voyage has no SDK in Rouh: its API is one POST (`rouh/synapse/ai.py`), so
    this is a plain `httpx` client whose requests to `/embeddings` each become
    a row of `llm_requests`. The key goes in the caller's `Authorization`
    header, which is never written down.
    """
    return VoyageRecording(**options)


# --------------------------------------------------------------------------
# Nothing asks a model past the log
# --------------------------------------------------------------------------
#
# Petar, 3 October 2026 (fr_6b7d307db6eb): "Please make sure no LLM code runs
# outside of our service that tracks usage and pricing for statistics. Of
# course, excluding Claude Code and Codex sessions."
#
# Every request Rouh sends is already written down by the two clients above,
# so what is left is a client made some other way, which is the one request
# nobody would see, and nothing would say so. Two things refuse one:
#
# - **At run time** (`guard`): an SDK client made in this process without the
#   recording HTTP client is refused the moment it is made, with a sentence
#   naming the way in. It is made long before any request it would send, so
#   it is never a request half sent.
# - **Before a deploy** (`strays`, `deploy/rouh.sh`): Rouh's own source is read
#   for a client made anywhere but here, or a provider's address written into
#   it, and new code that has one is not deployed. That catches the code path
#   nobody exercised before it went out.
#
# Claude Code and Codex are programs of their own, started for a run (the one
# program, `rouh/crew.py`): they keep their own accounts and are not this.


class Untracked(RuntimeError):
    """A model client made past `client` or `openai_client`."""


#: The SDK clients that ask a model, by module: each refuses to be made
#: without a recording HTTP client once `guard` has seen its module.
GUARDED = {"anthropic": ("Anthropic", "AsyncAnthropic"),
           "openai": ("OpenAI", "AsyncOpenAI")}


def guard() -> None:
    """Refuse an SDK client made without the log, in every SDK imported so far.

    Called when this module is imported, which is before any client of
    Anthropic's is made, and again when OpenAI's SDK is first imported for
    Luna (`openai_client`), so OpenAI's import is never paid for at start-up.
    """
    for module, names in GUARDED.items():
        sdk = sys.modules.get(module)
        for name in names if sdk is not None else ():
            cls = getattr(sdk, name, None)
            if cls is not None and not getattr(cls.__init__, "_rouh_guarded", False):
                cls.__init__ = _guarded(cls.__init__, f"{module}.{name}")


def _guarded(init, name: str):
    def __init__(self, *args, **kwargs):
        if not isinstance(kwargs.get("http_client"), _Recording):
            raise Untracked(
                f"{name} made directly, so nothing it asks would be counted: make it "
                "with rouh.llmlog.client or rouh.llmlog.openai_client, which write "
                "every request down for the usage and cost screens")
        init(self, *args, **kwargs)

    __init__._rouh_guarded = True
    __init__.__wrapped__ = init
    return __init__


def strays(root: str = _HERE) -> list[str]:
    """Every place in Rouh's source that could ask a model past the log, ask one past
    the LLM service, or name one in code (`rouh/llmguard.py`, which has the rules)."""
    from . import llmguard

    return llmguard.strays(root)


def main() -> int:
    """`python -m rouh.llmlog`: what `deploy/rouh.sh` asks before a deploy."""
    found = strays()
    for one in found:
        print(one, file=sys.stderr)
    if found:
        print(f"{len(found)} place(s) ask a model past rouh/llmlog.py, so what they "
              "ask would not be counted", file=sys.stderr)
        return 1
    print("every model client in Rouh is made by rouh/llmlog.py")
    return 0


class _Recording:
    """An SDK's HTTP client, writing down every request made of a model."""

    provider = PROVIDER
    #: The body wrapper for this SDK's HTTP library (`_tee_on`); `httpx`'s
    #: when this says nothing.
    tee = None

    async def send(self, request: httpx.Request, **kwargs) -> httpx.Response:
        if not _is_model_call(request, self.provider):
            return await super().send(request, **kwargs)
        request = _owner_said(request)
        entry = Entry(request, provider=self.provider)
        try:
            response = await super().send(request, **kwargs)
        except BaseException as exc:
            entry.end(exc)
            raise
        entry.answered(response)
        if kwargs.get("stream"):
            # Read as the caller reads it, and written down when the caller
            # stops reading, however that happens.
            response.stream = (self.tee or _Tee)(response.stream, entry)
        else:
            entry.headers = {}          # read whole, and so already decoded
            entry.took(response.content)
            entry.end()
        return response


def _owner_said(request):
    """The request with the owner's name and pronouns in place of the marks (`rouh/owner.py`).

    Every prompt, tool description and tool answer that is about the owner
    says `‹owner›` rather than a name written in the code, and this is where
    it becomes the name: every request made of a model passes through here,
    so a prompt reaches the model exactly as it was written before, in the
    owner's own name. A request with no mark in it goes out untouched.
    """
    try:
        from . import owner

        if "json" not in request.headers.get("content-type", ""):
            return request
        body = request.content
        said = owner.say_bytes(body)
        if said is body:
            return request
        headers = {k: v for k, v in request.headers.items() if k.lower() != "content-length"}
        return type(request)(request.method, request.url, headers=headers, content=said,
                             extensions=request.extensions)
    except Exception:                               # noqa: BLE001 - never worth a request
        log.exception("the owner's name could not be put into a request")
        return request


class Recording(_Recording, anthropic.DefaultAsyncHttpxClient):
    """Anthropic's SDK's HTTP client, writing down every request made of a model."""


class VoyageRecording(_Recording, httpx.AsyncClient):
    """A plain HTTP client for Voyage AI, writing down every embedding asked of it."""

    provider = VOYAGE


#: OpenAI's two endpoints that draw a picture (`rouh/imaging_openai.py`).
IMAGE_ENDPOINTS = ("/images/generations", "/images/edits")

#: OpenAI's endpoints that are neither an answer nor a picture, and are still
#: asked of a model and billed: the vectors Synapse's lab searches by meaning
#: with, and the Decisions API it asks typed questions of (`rouh/synapse/ai.py`).
OTHER_ENDPOINTS = ("/embeddings", "/decisions")


def _is_model_call(request: httpx.Request, provider: str = PROVIDER) -> bool:
    """A request for an answer: `POST /v1/messages`, beta or not, or OpenAI's
    `POST /v1/responses`, or one of OpenAI's for a picture."""
    path = request.url.path.rstrip("/")
    if provider == VOYAGE:
        return request.method == "POST" and path.endswith("/embeddings")
    if provider in COMPAT:
        return request.method == "POST" and path.endswith("/chat/completions")
    if provider == OPENAI:
        return request.method == "POST" and (path.endswith("/responses")
                                             or path.endswith(IMAGE_ENDPOINTS)
                                             or path.endswith(OTHER_ENDPOINTS))
    return request.method == "POST" and path.endswith("/v1/messages")


def is_image_endpoint(endpoint: str) -> bool:
    return str(endpoint or "").rstrip("/").endswith(IMAGE_ENDPOINTS)


def _tee_on(stream_type):
    """The body wrapper, on the byte stream of the HTTP library an SDK uses.

    Anthropic's SDK is built on `httpx` and OpenAI's, since its 3.x, on
    `httpx2`, and each will only close a stream of its own library's kind:
    handed the other's, OpenAI's refused with "Attempted to call an async
    close on a sync stream" and the turn ended.
    """

    class Tee(stream_type):
        """A response body, passed on untouched and kept for the record."""

        def __init__(self, inner, entry: "Entry") -> None:
            self.inner = inner
            self.entry = entry

        async def __aiter__(self):
            try:
                async for chunk in self.inner:
                    self.entry.took(chunk)
                    yield chunk
            except (Exception, asyncio.CancelledError) as exc:
                self.entry.end(exc)
                raise
            # A reader that stopped early never gets here: `aclose` says so.
            self.entry.end()

        async def aclose(self) -> None:
            try:
                await self.inner.aclose()
            finally:
                self.entry.end(stopped=True)

    return Tee


_Tee = _tee_on(httpx.AsyncByteStream)


class Entry:
    """One request, from the moment it goes out to the moment its answer ends.

    Everything that has to happen on the event loop happens here and is cheap:
    the time, the bytes as they arrive. Reading them, pricing them and the
    database are the writer's (`_begin`, `_finish`), in its own thread.
    """

    def __init__(self, request: httpx.Request, provider: str = PROVIDER) -> None:
        self.provider = provider
        self.started = time.time()
        self.clock = time.monotonic()
        self.endpoint = request.url.path
        self.content_type = request.headers.get("content-type", "")
        try:
            self.body = bytes(request.content)
        except Exception:                         # a body sent as a stream, in
            self.body = b""                       # either library's words
            if is_image_endpoint(self.endpoint):
                # A picture to be changed goes up as a form with files in
                # it, which neither library reads until it is sent. Read now,
                # it is sent from what was read; the pictures themselves are
                # never written down (`_image_request`).
                with contextlib.suppress(Exception):
                    self.body = bytes(request.read())
        try:
            self.sdk_retry = int(request.headers.get("x-stainless-retry-count") or 0)
        except ValueError:
            self.sdk_retry = 0
        self.about = dict(_ABOUT.get() or {})
        # A turn of a case is the use "case_read", which only the turn's own context says: the
        # record of the call is written later, on the writer's thread (`modeloutcomes`).
        self.use = _case_use()
        self.speaker = _speaker()
        self.caller = _caller()
        self.status: int | None = None
        self.request_id = ""
        self.headers: dict = {}
        self.chunks: list[bytes] = []
        self.first_ms: int | None = None
        self.done = False
        self.outcome = ""
        self.problem = ""
        self.duration_ms: int | None = None
        self.finished = 0.0
        self.row: int | None = None
        self.fields: dict = {}
        self.pieces: dict = {}
        # A request of a turn's answer is a bar on that turn's timeline (`rouh/turntrace.py`),
        # from now, through its first word, to its end and what it cost.
        from . import turntrace

        self.trace = turntrace.current() if self.about.get("purpose") == "turn" else None
        self.trace_lane = self.trace.request_started("turn") if self.trace is not None else ""
        self.phase = ""
        WRITER.put(self._begin)

    # --- on the event loop ------------------------------------------------

    def answered(self, response: httpx.Response) -> None:
        self.status = response.status_code
        self.request_id = response.headers.get("request-id", "")
        encoding = response.headers.get("content-encoding")
        self.headers = {"content-encoding": encoding} if encoding else {}

    def took(self, chunk: bytes) -> None:
        if not chunk:
            return
        if self.first_ms is None and (b"content_block_delta" in chunk
                                      or b"response.output_text.delta" in chunk
                                      or b"partial_image" in chunk
                                      or (self.provider in COMPAT and b'"content":"' in chunk)):
            self.first_ms = self._since()
            if self.trace_lane:
                self.trace.request_first(self.trace_lane)
        if self.trace_lane:
            self._phase_of(chunk)
        self.chunks.append(bytes(chunk))

    #: What a piece of a stream says the model is doing, the last of them winning: thinking,
    #: writing words, or writing a call to a tool. Anthropic's and OpenAI's words for each.
    _PHASES = ((b"thinking_delta", "thinking"), (b'"type":"thinking"', "thinking"),
               (b'"type":"redacted_thinking"', "thinking"), (b"response.reasoning", "thinking"),
               (b"text_delta", "writing"), (b"output_text.delta", "writing"),
               (b"input_json_delta", "calling"), (b'"type":"tool_use"', "calling"),
               (b'"type":"server_tool_use"', "calling"), (b"function_call_arguments", "calling"))

    def _phase_of(self, chunk: bytes) -> None:
        """Tell the turn's timeline when the model moves on to thinking, writing or a tool."""
        found, at = "", -1
        for marker, phase in self._PHASES:
            where = chunk.rfind(marker)
            if where > at:
                found, at = phase, where
        if found and found != self.phase:
            self.phase = found
            self.trace.request_phase(self.trace_lane, found)

    def end(self, exc: BaseException | None = None, *, stopped: bool = False) -> None:
        """The answer is over: read to the end, broken, or no longer read."""
        if self.done:
            return
        self.done = True
        self.finished = time.time()
        self.duration_ms = self._since()
        if isinstance(exc, (asyncio.CancelledError, GeneratorExit)) or (exc is None and stopped):
            self.outcome = "stopped"
        elif exc is not None:
            self.outcome = "broken"
            self.problem = f"{type(exc).__name__}: {exc}"[:2000]
        else:
            self.outcome = "ended"
        if self.trace_lane:
            self.trace.request_ended(self.trace_lane, self.outcome)
        WRITER.put(self._finish)

    def _since(self) -> int:
        return int((time.monotonic() - self.clock) * 1000)

    # --- in the writer's thread -------------------------------------------

    def _begin(self) -> None:
        from .models import LLMRequest

        picture = is_image_endpoint(self.endpoint)
        if picture:
            body = _image_request(self.body, self.content_type)
        else:
            try:
                body = json.loads(self.body) if self.body else {}
            except ValueError:
                body = {}
        if not isinstance(body, dict):
            body = {}
        pieces = self.pieces
        if self.provider in COMPAT:
            # Chat Completions: the system prompt is the conversation's first message, and the
            # level is `reasoning_effort` (`rouh/compat.py`).
            said = body.get("messages") if isinstance(body.get("messages"), list) else []
            system_text = "\n\n".join(str(m.get("content") or "") for m in said
                                       if isinstance(m, dict) and m.get("role") == "system")
            body["messages"] = [m for m in said if not (isinstance(m, dict) and m.get("role") == "system")]
            if system_text:
                body["instructions"] = system_text
            body["input"] = body.pop("messages")
            if body.get("reasoning_effort"):
                body["reasoning"] = {"effort": body.get("reasoning_effort")}
            if body.get("max_completion_tokens") is not None:
                body["max_output_tokens"] = body.pop("max_completion_tokens")
        # Voyage's body is OpenAI's shape: its texts are its `input`.
        openai = self.provider in (OPENAI, VOYAGE) + COMPAT
        # The same three parts under OpenAI's names: its instructions are the
        # system prompt and its input the conversation (`rouh/luna.py`). A
        # picture's words are its one message, and the rest of what it was
        # asked with its settings.
        system = _piece(pieces, "system", _log_safe(
            body.pop("instructions" if openai else "system", None), self.provider))
        tools = _piece(pieces, "tools", _log_safe(body.pop("tools", None), self.provider))
        messages = body.pop("input" if openai else "messages", None)
        if picture and body.get("prompt") is not None:
            messages = str(body.pop("prompt"))
        if isinstance(messages, str):
            messages = [{"role": "user", "content": messages}]
        message_pieces = [_piece(pieces, "message", _log_safe(m, self.provider))
                          for m in (messages if isinstance(messages, list) else [])]

        thinking = body.get("thinking")
        thought = ""
        if isinstance(thinking, dict):
            thought = str(thinking.get("type") or "")
            if thinking.get("display"):
                thought += "/" + str(thinking["display"])
        output = body.get("output_config") if isinstance(body.get("output_config"), dict) else {}
        if openai:
            output = body.get("reasoning") if isinstance(body.get("reasoning"), dict) else {}
            thought = "reasoning" if output.get("effort") not in (None, "none") else ""
        user_id, org_id = self._whose()
        purpose = str(self.about.get("purpose") or "")
        if not purpose and self.caller:
            purpose = os.path.splitext(os.path.basename(self.caller.split(":")[0]))[0]
        most = body.get("max_output_tokens" if openai else "max_tokens")
        try:
            max_tokens = int(most) if most is not None else None
        except (TypeError, ValueError):
            max_tokens = None
        self.fields = dict(
            started_at=self.started,
            org_id=org_id, user_id=user_id,
            session_id=str(self.about.get("session_id") or ""),
            turn_id=str(self.about.get("turn_id") or ""),
            purpose=purpose,
            subject=str(self.about.get("subject") or ""),
            caller=self.caller,
            provider=self.provider,
            endpoint=self.endpoint,
            model=str(body.get("model") or ""),
            stream=bool(body.get("stream")),
            max_tokens=max_tokens,
            effort=str(output.get("effort") or ""),
            thinking=thought,
            settings=_log_safe(body, self.provider),
            system_piece=system,
            tools_piece=tools,
            message_pieces=message_pieces,
            request_hash=hashlib.sha256(self.body).hexdigest(),
            request_bytes=len(self.body),
            attempt=_number(self.about.get("attempt"), 1) + self.sdk_retry,
        )
        _keep(pieces)
        self.row = LLMRequest.objects.create(status="sent", **self.fields).pk

    def _finish(self) -> None:
        from . import costs
        from .models import LLMRequest

        raw = b"".join(self.chunks)
        if self.headers and raw:
            with contextlib.suppress(Exception):
                raw = httpx.Response(self.status or 200, headers=self.headers,
                                     stream=httpx.ByteStream(raw)).read()
        picture = is_image_endpoint(self.endpoint)
        if picture:
            message, error = read_openai_images(raw)
        elif self.provider == VOYAGE or (self.provider == OPENAI
                                         and self.endpoint.rstrip("/").endswith(OTHER_ENDPOINTS)):
            message, error = read_openai_other(raw)
        elif self.provider == OPENAI:
            message, error = read_openai_answer(raw)
        elif self.provider in COMPAT:
            message, error = read_chat_answer(raw)
        else:
            message, error = read_answer(raw)
        blocks = [b for b in message.get("content") or [] if isinstance(b, dict)]
        usage = message.get("usage") if isinstance(message.get("usage"), dict) else {}
        took = costs.tokens_of(usage)
        model = str(message.get("model") or self.fields.get("model") or "")
        if picture:
            cost = costs.image_cost(usage, model) if usage else None
        elif self.provider == OPENAI and self.endpoint.rstrip("/").endswith("/decisions"):
            # OpenAI's Decisions API charges input alone (`costs.DECISION_PRICES`).
            cost = costs.decision_cost(usage, model) if usage else None
        else:
            cost = costs.request_cost(usage, model) if usage else None
        tools = usage.get("server_tool_use")
        tools = tools if isinstance(tools, dict) else {}

        if (self.status is not None and self.status >= 400) or error or self.outcome == "broken":
            status = "error"
        elif self.outcome == "stopped" and not message.get("stop_reason"):
            status = "stopped"
        else:
            status = "ok"
        error = error or {}
        said = str(error.get("message") or "") or self.problem
        if not said and status == "error" and self.status:
            said = f"HTTP {self.status}"

        done = dict(
            finished_at=self.finished,
            status=status,
            http_status=self.status,
            request_id=self.request_id,
            message_id=str(message.get("id") or ""),
            served_model=str(message.get("model") or ""),
            stop_reason=str(message.get("stop_reason") or ""),
            error_type=str(error.get("type") or ""),
            error=said[:4000],
            text=(str(message.get("text") or "") if self.provider in (OPENAI, VOYAGE) + COMPAT else
                  "".join(str(b.get("text") or "") for b in blocks if b.get("type") == "text")),
            reasoning=(str(message.get("reasoning") or "") if self.provider in (OPENAI, VOYAGE) + COMPAT else
                       "\n\n".join(str(b.get("thinking") or "") for b in blocks
                                    if b.get("type") == "thinking" and b.get("thinking"))),
            response=_log_safe(message, self.provider) if message else None,
            input_tokens=took["input"],
            output_tokens=took["output"],
            cache_read_tokens=took["cache_read"],
            cache_write_tokens=took["cache_write"],
            web_searches=(_number(message.get("web_searches"), 0) if self.provider in (OPENAI, VOYAGE) + COMPAT
                          else _number(tools.get("web_search_requests"), 0)),
            usage=usage,
            cost_usd=None if cost is None else Decimal(f"{cost:.6f}"),
            first_token_ms=self.first_ms,
            duration_ms=self.duration_ms,
        )
        if self.trace_lane:
            self.trace.request_counted(self.trace_lane, tokens_in=took["input"] + took["cache_write"],
                                       tokens_out=took["output"], cache_read=took["cache_read"],
                                       cache_write=took["cache_write"], cost=cost, row=self.row)
        if self.row is not None:
            LLMRequest.objects.filter(pk=self.row).update(**done)
        elif self.fields:
            # Its first write failed and this one may not: the request is
            # written down whole, late, rather than not at all.
            _keep(self.pieces)
            self.row = LLMRequest.objects.create(**self.fields, **done).pk
        # And the call it was part of, for which model succeeds: its use, model,
        # level, cost and time, and never its words (`rouh/modeloutcomes.py`).
        from . import modeloutcomes

        modeloutcomes.request_done(self.fields, done, self.row, use=self.use)

    def _whose(self) -> tuple[str, str]:
        user_id = str(self.about.get("user_id") or "")
        org_id = str(self.about.get("org_id") or "")
        if user_id:
            return user_id, org_id
        who = self.speaker
        if who is None:
            with contextlib.suppress(Exception):
                from .tenancy import Tenancy
                who = Tenancy().only_person()
        if who is None:
            return "", org_id
        return str(who.user_id or ""), org_id or str(who.org_id or "")


def _case_use() -> str:
    """"case_read" while a case's turn asks (`chatkinds.of_case`), else ""."""
    try:
        from . import chatkinds

        return "case_read" if chatkinds.of_case() else ""
    except Exception:  # noqa: BLE001 - the record never stops a request
        return ""


def _speaker():
    """Who is talking in this context, if anybody is."""
    try:
        from .tenancy import speaker
        return speaker()
    except Exception:                               # noqa: BLE001 - never worth a request
        return None


def _caller() -> str:
    """The function in Rouh that is sending this request: `rouh/brain.py:pump`."""
    frame = sys._getframe(2)
    while frame is not None:
        path = frame.f_code.co_filename
        if path.startswith(_HERE + os.sep) and os.path.abspath(path) != os.path.abspath(__file__):
            where = os.path.relpath(path, os.path.dirname(_HERE))
            return f"{where}:{frame.f_code.co_name}"
        frame = frame.f_back
    return ""


def _number(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


# --------------------------------------------------------------------------
# What was asked, kept once
# --------------------------------------------------------------------------


def _dump(value) -> str:
    """The JSON a piece is kept as, and its digest taken of: compact, every key
    in the order it was sent, and every character as itself."""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _log_safe(value, provider: str, parent_type: str = ""):
    """Copy a model payload without turn-only or provider-private reasoning data.

    This affects only the database copy. The SDK sends and receives the
    original values, so reasoning can still be handed back within a turn.
    """
    if isinstance(value, list):
        return [_log_safe(item, provider, parent_type) for item in value]
    if not isinstance(value, dict):
        return value
    kind = str(value.get("type") or parent_type)
    clean = {}
    for key, item in value.items():
        if provider == OPENAI and key == "encrypted_content":
            continue
        if provider == PROVIDER and ((kind == "thinking" and key == "signature")
                                     or (kind == "redacted_thinking" and key == "data")):
            continue
        clean[key] = _log_safe(item, provider, kind)
    return clean


def _as_json(value):
    """A jsonb value as Python: decoded when the cursor handed it back as text."""
    if isinstance(value, (str, bytes, bytearray)):
        try:
            return json.loads(value)
        except ValueError:
            return value
    return value


def scrub_historical_reasoning(batch_size: int = 2000, pause: float = 0.1,
                               after_request_id: int = 0, after_piece_hash: str = "",
                               progress=None) -> dict[str, int]:
    """Idempotently remove private reasoning fields from stored log batches.

    Each read and its updates share one short transaction. The keyset cursor
    and idempotent rewrite make an interrupted run safe to restart from the
    beginning. New rows already use the safe writer above.
    """
    if not 1 <= batch_size <= 5000:
        raise ValueError("batch_size must be between 1 and 5000")
    if pause < 0 or pause > 60:
        raise ValueError("pause must be between 0 and 60 seconds")
    if after_request_id < 0:
        raise ValueError("after_request_id must not be negative")
    report = {"request_rows": 0, "request_bytes": 0,
              "piece_rows": 0, "piece_bytes": 0}
    scanned = {"requests": 0, "pieces": 0}

    def say(stage: str, cursor_value: str, batch: int):
        if progress:
            progress(stage, cursor_value, batch, dict(scanned), dict(report))

    last_id = after_request_id
    while True:
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("""SELECT id, provider, settings, response FROM llm_requests
                    WHERE id > %s ORDER BY id LIMIT %s""", (last_id, batch_size))
                rows = cursor.fetchall()
                for row_id, provider, settings, response in rows:
                    # Django's PostgreSQL backend hands jsonb back as text to a raw cursor, so
                    # it is read here; left as text, nothing in it was ever scrubbed.
                    settings, response = _as_json(settings), _as_json(response)
                    safe_settings = _log_safe(settings or {}, provider)
                    safe_response = _log_safe(response, provider) if response is not None else None
                    before = len(_dump([settings, response]).encode())
                    after = len(_dump([safe_settings, safe_response]).encode())
                    if before == after:
                        continue
                    cursor.execute("UPDATE llm_requests SET settings = %s::jsonb, "
                                   "response = %s::jsonb WHERE id = %s",
                                   (json.dumps(safe_settings, ensure_ascii=False),
                                    None if safe_response is None else
                                    json.dumps(safe_response, ensure_ascii=False), row_id))
                    report["request_rows"] += 1
                    report["request_bytes"] += before - after
        if not rows:
            break
        scanned["requests"] += len(rows)
        last_id = int(rows[-1][0])
        say("requests", str(last_id), len(rows))
        if pause:
            time.sleep(pause)

    last_hash = after_piece_hash
    while True:
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("""SELECT hash, body FROM llm_pieces
                    WHERE hash > %s ORDER BY hash LIMIT %s""", (last_hash, batch_size))
                rows = cursor.fetchall()
                for digest, body in rows:
                    try:
                        original = json.loads(body)
                    except (TypeError, ValueError):
                        continue
                    safe = _log_safe(_log_safe(original, OPENAI), PROVIDER)
                    new_body = _dump(safe)
                    if new_body == body:
                        continue
                    report["piece_bytes"] += len(body.encode()) - len(new_body.encode())
                    cursor.execute("UPDATE llm_pieces SET body = %s, size = %s WHERE hash = %s",
                                   (new_body, len(new_body.encode()), digest))
                    report["piece_rows"] += 1
        if not rows:
            break
        scanned["pieces"] += len(rows)
        last_hash = rows[-1][0]
        say("pieces", last_hash, len(rows))
        if pause:
            time.sleep(pause)
    return report


def _piece(pieces: dict, kind: str, value) -> str:
    """The digest of one piece, noted to be kept. "" for a piece not sent."""
    if value is None:
        return ""
    text = _dump(value)
    digest = hashlib.sha256(f"{kind}\n{text}".encode()).hexdigest()
    pieces.setdefault(digest, (kind, text))
    return digest


def _keep(pieces: dict) -> None:
    """Write down the pieces nobody has sent before. The rest are there."""
    from .models import LLMPiece

    if not pieces:
        return
    there = set(LLMPiece.objects.filter(hash__in=list(pieces)).values_list("hash", flat=True))
    now = time.time()
    fresh = [LLMPiece(hash=digest, kind=kind, body=text, size=len(text.encode()), created_at=now)
             for digest, (kind, text) in pieces.items() if digest not in there]
    if fresh:
        LLMPiece.objects.bulk_create(fresh, ignore_conflicts=True)


def request_of(row) -> dict:
    """One request as it was sent, put back together from its pieces."""
    from .models import LLMPiece

    wanted = [h for h in (row.system_piece, row.tools_piece, *(row.message_pieces or [])) if h]
    bodies = dict(LLMPiece.objects.filter(hash__in=wanted).values_list("hash", "body"))

    def back(digest):
        return json.loads(bodies[digest]) if digest in bodies else {"missing piece": digest}

    out = dict(row.settings or {})
    if row.system_piece:
        out["system"] = back(row.system_piece)
    out["messages"] = [back(h) for h in row.message_pieces or []]
    if row.tools_piece:
        out["tools"] = back(row.tools_piece)
    return out


# --------------------------------------------------------------------------
# What came back
# --------------------------------------------------------------------------


def read_answer(raw: bytes) -> tuple[dict, dict | None]:
    """The answer as one message, and the error if there was one.

    A streamed answer is put back together from its events the way the SDK
    does it; one that was not streamed, or an error the API sent as a status,
    is one JSON body.
    """
    text = raw.decode("utf-8", errors="replace")
    stripped = text.lstrip()
    if stripped.startswith("{"):
        try:
            body = json.loads(stripped)
        except ValueError:
            return {}, {"type": "unreadable", "message": stripped[:500]}
        if isinstance(body, dict) and body.get("type") == "error":
            return {}, body.get("error") if isinstance(body.get("error"), dict) else body
        return (body if isinstance(body, dict) else {}), None
    return _assemble(_events(text))


def read_openai_answer(raw: bytes) -> tuple[dict, dict | None]:
    """An OpenAI Responses answer as the same one message, and its error.

    The finished response out of the stream's last `response.*` event, with
    what the columns want beside it: its usage in the names `costs` reads (an
    uncached count, cache reads, cache writes, output), its words, what it
    said of its reasoning, and how many searches it ran. A stream stopped
    before it finished keeps the words that had arrived.
    """
    text = raw.decode("utf-8", errors="replace")
    stripped = text.lstrip()
    if stripped.startswith("{"):
        try:
            body = json.loads(stripped)
        except ValueError:
            return {}, {"type": "unreadable", "message": stripped[:500]}
        if isinstance(body, dict) and isinstance(body.get("error"), dict):
            return {}, body["error"]
        return _openai_message(body if isinstance(body, dict) else {}, ""), None
    response: dict = {}
    said: list[str] = []
    error = None
    for event in _events(text):
        kind = str(event.get("type") or "")
        if kind == "response.output_text.delta":
            said.append(str(event.get("delta") or ""))
        elif kind.startswith("response.") and isinstance(event.get("response"), dict):
            response = event["response"]
            if kind == "response.failed" and isinstance(response.get("error"), dict):
                error = dict(response["error"], type=response["error"].get("code") or "failed")
        elif kind == "error":
            error = {"type": str(event.get("code") or "error"),
                     "message": str(event.get("message") or "")}
    return _openai_message(response, "".join(said)), error


def read_chat_answer(raw: bytes) -> tuple[dict, dict | None]:
    """A Chat Completions answer from Google's or xAI's endpoint, streamed or whole, as the same
    one message: its words, its reasoning where the provider sends it, its tool calls, and its
    usage in the names `costs` reads (the uncached prompt, the cached part, the output)."""
    text = raw.decode("utf-8", errors="replace")
    stripped = text.lstrip()
    chunks = []
    if stripped.startswith(("{", "[")):
        try:
            body = json.loads(stripped)
        except ValueError:
            return {}, {"type": "unreadable", "message": stripped[:500]}
        if isinstance(body, list):              # Google sends an error as a list of one
            body = body[0] if body and isinstance(body[0], dict) else {}
        if isinstance(body, dict) and isinstance(body.get("error"), dict):
            return {}, {"type": str(body["error"].get("status") or body["error"].get("code") or "error"),
                        "message": str(body["error"].get("message") or "")}
        chunks = [body] if isinstance(body, dict) else []
    else:
        chunks = list(_events(text))
    words, thought, calls = [], [], {}
    usage, model, rid, finish, error = {}, "", "", "", None
    for chunk in chunks:
        if isinstance(chunk.get("error"), dict):
            error = {"type": str(chunk["error"].get("code") or "error"),
                     "message": str(chunk["error"].get("message") or "")}
        model = str(chunk.get("model") or model)
        rid = str(chunk.get("id") or rid)
        if isinstance(chunk.get("usage"), dict):
            usage = chunk["usage"]
        for choice in chunk.get("choices") or []:
            if not isinstance(choice, dict):
                continue
            part = choice.get("delta") if isinstance(choice.get("delta"), dict) else (
                choice.get("message") if isinstance(choice.get("message"), dict) else {})
            if part.get("content"):
                words.append(str(part["content"]))
            if part.get("reasoning_content"):
                thought.append(str(part["reasoning_content"]))
            for call in part.get("tool_calls") or []:
                if not isinstance(call, dict):
                    continue
                held = calls.setdefault(call.get("index", len(calls)), {"id": "", "name": "", "arguments": ""})
                held["id"] = call.get("id") or held["id"]
                fn = call.get("function") if isinstance(call.get("function"), dict) else {}
                held["name"] = fn.get("name") or held["name"]
                held["arguments"] += str(fn.get("arguments") or "")
            finish = str(choice.get("finish_reason") or finish)
    out = {"id": rid, "model": model, "stop_reason": finish, "text": "".join(words),
           "reasoning": "".join(thought), "web_searches": 0,
           "content": ([{"type": "text", "text": "".join(words)}] if words else [])
           + [{"type": "tool_use", "id": c["id"], "name": c["name"], "input": c["arguments"]}
              for _, c in sorted(calls.items())]}
    if usage:
        details = usage.get("prompt_tokens_details") if isinstance(usage.get("prompt_tokens_details"), dict) else {}
        sent = _number(usage.get("prompt_tokens"), 0)
        read = _number(details.get("cached_tokens"), 0)
        out["usage"] = {"input_tokens": max(0, sent - read),
                        "output_tokens": _number(usage.get("completion_tokens"), 0),
                        "cache_read_input_tokens": read, "cache_creation_input_tokens": 0}
    return out, error


def read_openai_other(raw: bytes) -> tuple[dict, dict | None]:
    """An answer from OpenAI's embeddings or Decisions endpoint, or Voyage AI's
    embeddings, as one message.

    The vectors themselves are not kept: a thousand numbers per passage say
    nothing to anybody reading the log, and the passage they were made from is
    already in the request. How many came back, the model and the tokens are.
    """
    text = raw.decode("utf-8", errors="replace").strip()
    try:
        body = json.loads(text) if text else {}
    except ValueError:
        return {}, {"type": "unreadable", "message": text[:500]}
    if not isinstance(body, dict):
        return {}, {"type": "unreadable", "message": text[:500]}
    if isinstance(body.get("error"), dict):
        return {}, body["error"]
    if "detail" in body and "data" not in body:
        # Voyage's way of saying no: `{"detail": "..."}` with a 4xx status.
        return {}, {"type": "error", "message": str(body["detail"])[:500]}
    usage = body.get("usage") if isinstance(body.get("usage"), dict) else {}
    kept = {k: v for k, v in body.items() if k != "data"}
    if isinstance(body.get("data"), list):
        kept["data"] = f"{len(body['data'])} vectors"
    sent = _number(usage.get("input_tokens", usage.get("prompt_tokens", usage.get("total_tokens"))), 0)
    out = {"id": body.get("id") or "", "model": body.get("model") or "",
           "stop_reason": "", "content": [], "response": kept,
           "text": kept.get("data") if isinstance(kept.get("data"), str)
           else json.dumps(kept.get("answers", kept.get("output", "")), ensure_ascii=False)[:4000],
           "reasoning": "", "web_searches": 0}
    if usage and isinstance(body.get("answers"), list):
        # A decision's `input_tokens` holds its cache reads and writes, which are priced
        # apart; its output is kept and never charged (`costs.decision_cost`).
        from .llm import decision_usage

        out["usage"] = decision_usage(usage)
    elif usage:
        out["usage"] = {"input_tokens": sent,
                        "output_tokens": _number(usage.get("output_tokens"), 0),
                        "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0}
    return out, None


def _image_request(body: bytes, content_type: str) -> dict:
    """What a picture was asked for with, without the pictures handed in.

    A new picture is asked for in JSON. One made from another goes up as a
    form, with the picture and its mask as files: those are kept as their
    names and sizes, because they are the person's own and already on disk,
    and the rest is kept as it was sent.
    """
    if not body:
        return {}
    if body.lstrip()[:1] == b"{":
        try:
            said = json.loads(body)
        except ValueError:
            return {}
        return said if isinstance(said, dict) else {}
    boundary = ""
    for part in str(content_type or "").split(";"):
        name, _, value = part.strip().partition("=")
        if name.lower() == "boundary":
            boundary = value.strip('"')
    if not boundary:
        return {}
    out: dict = {}
    for chunk in body.split(b"--" + boundary.encode()):
        head, _, value = chunk.partition(b"\r\n\r\n")
        if not value:
            continue
        value = value[:-2] if value.endswith(b"\r\n") else value
        heads = head.decode("utf-8", "replace")
        field = ""
        for piece in heads.replace("\r\n", ";").split(";"):
            key, _, said = piece.strip().partition("=")
            if key == "name":
                field = said.strip('"')
                break
        if not field:
            continue
        field = field[:-2] if field.endswith("[]") else field
        if "filename=" in heads:
            out.setdefault(field + "_files", []).append({"bytes": len(value)})
        else:
            out[field] = value.decode("utf-8", "replace")
    for key in ("n", "partial_images", "output_compression"):
        if isinstance(out.get(key), str) and out[key].isdigit():
            out[key] = int(out[key])
    if out.get("stream") in ("true", "false"):
        out["stream"] = out["stream"] == "true"
    return out


def read_openai_images(raw: bytes) -> tuple[dict, dict | None]:
    """OpenAI's answer to a picture, without the picture, and its error.

    The pictures are base64 in the answer, and a few megabytes each, and they
    are kept where every picture is kept, in the chat's own files
    (`rouh/imaging.py`). What is written down is what the columns want: the
    usage as it came, the model, and each picture's size, quality and length;
    the rough previews of a streamed one are counted.
    """
    text = raw.decode("utf-8", errors="replace")
    stripped = text.lstrip()
    pictures: list[dict] = []
    usage: dict = {}
    error = None
    previews = 0
    said: list[str] = []

    def keep(one: dict, whole: dict) -> None:
        data = str(one.get("b64_json") or "")
        pictures.append({"type": "image", "size": whole.get("size") or one.get("size") or "",
                         "quality": whole.get("quality") or one.get("quality") or "",
                         "output_format": whole.get("output_format")
                         or one.get("output_format") or "",
                         "bytes": len(data) * 3 // 4})
        if one.get("revised_prompt"):
            said.append(str(one["revised_prompt"]))

    if stripped.startswith("{"):
        try:
            body = json.loads(stripped)
        except ValueError:
            return {}, {"type": "unreadable", "message": stripped[:500]}
        if isinstance(body, dict) and isinstance(body.get("error"), dict):
            return {}, body["error"]
        body = body if isinstance(body, dict) else {}
        for one in body.get("data") or []:
            if isinstance(one, dict):
                keep(one, body)
        usage = body.get("usage") if isinstance(body.get("usage"), dict) else {}
    else:
        for event in _events(text):
            kind = str(event.get("type") or "")
            if kind.endswith("partial_image"):
                previews += 1
            elif kind.endswith(".completed"):
                keep(event, event)
                if isinstance(event.get("usage"), dict):
                    usage = event["usage"]
            elif kind == "error" or isinstance(event.get("error"), dict):
                inner = event.get("error") if isinstance(event.get("error"), dict) else event
                error = {"type": str(inner.get("code") or inner.get("type") or "error"),
                         "message": str(inner.get("message") or "")}
    out = {"model": "", "stop_reason": "completed" if pictures else "",
           "content": pictures, "text": "\n\n".join(said), "previews": previews}
    if usage:
        out["usage"] = usage
    return out, error


def _openai_message(response: dict, streamed: str) -> dict:
    output = [i for i in response.get("output") or [] if isinstance(i, dict)]
    words = "".join(str(p.get("text") or "") for i in output if i.get("type") == "message"
                    for p in i.get("content") or [] if isinstance(p, dict)
                    and p.get("type") == "output_text")
    thought = "\n\n".join(str(s.get("text") or "") for i in output if i.get("type") == "reasoning"
                           for s in i.get("summary") or [] if isinstance(s, dict))
    usage = response.get("usage") if isinstance(response.get("usage"), dict) else {}
    details = usage.get("input_tokens_details") if isinstance(
        usage.get("input_tokens_details"), dict) else {}
    sent = _number(usage.get("input_tokens"), 0)
    read = _number(details.get("cached_tokens"), 0)
    wrote = _number(details.get("cache_write_tokens"), 0)
    reason = (response.get("incomplete_details") or {}).get("reason") if isinstance(
        response.get("incomplete_details"), dict) else None
    out = {"id": response.get("id") or "", "model": response.get("model") or "",
           "stop_reason": reason or response.get("status") or "",
           "content": output, "text": words or streamed, "reasoning": thought,
           "web_searches": sum(1 for i in output if i.get("type") == "web_search_call")}
    if usage:
        out["usage"] = {"input_tokens": max(0, sent - read - wrote),
                        "output_tokens": _number(usage.get("output_tokens"), 0),
                        "cache_read_input_tokens": read,
                        "cache_creation_input_tokens": wrote}
    return out


def _events(text: str):
    """Each server-sent event's data, parsed."""
    for chunk in text.replace("\r\n", "\n").split("\n\n"):
        data = [line[5:].lstrip() for line in chunk.split("\n") if line.startswith("data:")]
        if not data:
            continue
        try:
            event = json.loads("\n".join(data))
        except ValueError:
            continue
        if isinstance(event, dict):
            yield event


def _assemble(events) -> tuple[dict, dict | None]:
    message: dict = {}
    blocks: dict[int, dict] = {}
    partial: dict[int, str] = {}
    error = None
    for event in events:
        kind = event.get("type")
        if kind == "message_start":
            message = dict(event.get("message") or {})
            message["usage"] = dict(message.get("usage") or {})
        elif kind == "content_block_start":
            at = _number(event.get("index"), len(blocks))
            blocks[at] = dict(event.get("content_block") or {})
        elif kind == "content_block_delta":
            at = _number(event.get("index"), 0)
            block = blocks.setdefault(at, {})
            delta = event.get("delta") or {}
            what = delta.get("type")
            if what == "input_json_delta":
                partial[at] = partial.get(at, "") + str(delta.get("partial_json") or "")
            elif what == "citations_delta":
                if not isinstance(block.get("citations"), list):
                    block["citations"] = []
                block["citations"].append(delta.get("citation"))
            elif what == "signature_delta":
                block["signature"] = delta.get("signature")
            else:
                # text_delta, thinking_delta, and whatever comes next: a
                # string is added to, anything else is replaced.
                for key, value in delta.items():
                    if key == "type":
                        continue
                    if isinstance(value, str):
                        block[key] = str(block.get(key) or "") + value
                    else:
                        block[key] = value
        elif kind == "content_block_stop":
            at = _number(event.get("index"), 0)
            if at in partial:
                blocks.setdefault(at, {})["input"] = _parsed(partial.pop(at))
        elif kind == "message_delta":
            for key, value in (event.get("delta") or {}).items():
                message[key] = value
            usage = message.setdefault("usage", {})
            for key, value in (event.get("usage") or {}).items():
                if value is not None:
                    usage[key] = value
        elif kind == "error":
            error = event.get("error") if isinstance(event.get("error"), dict) else event
    # A block cut off before it closed keeps what had arrived of its input.
    for at, pieces in partial.items():
        blocks.setdefault(at, {})["input"] = _parsed(pieces)
    if message or blocks:
        message["content"] = [blocks[at] for at in sorted(blocks)]
    return message, error


def _parsed(text: str):
    try:
        return json.loads(text) if text else {}
    except ValueError:
        return {"unfinished": text}


# --------------------------------------------------------------------------
# The writer
# --------------------------------------------------------------------------


class _Writer:
    """One thread that writes the log, one job at a time, in order.

    In order matters: a request's row is made before its answer is written
    onto it. One thread is what makes that true without anybody waiting.
    """

    def __init__(self) -> None:
        self._jobs: queue.SimpleQueue = queue.SimpleQueue()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def put(self, job) -> None:
        with self._lock:
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(target=self._run, name="rouh-llmlog",
                                                 daemon=True)
                self._thread.start()
        self._jobs.put(job)

    def _run(self) -> None:
        while True:
            job = self._jobs.get()
            try:
                job()
            except Exception:                        # noqa: BLE001 - never a turn's problem
                log.warning("a request made of the model could not be written down",
                            exc_info=True)

    def flush(self, timeout: float = 10.0) -> bool:
        """Wait until everything asked of the writer so far is written."""
        if self._thread is None:
            return True
        done = threading.Event()
        self.put(done.set)
        return done.wait(timeout)


WRITER = _Writer()

# What is still waiting to be written when the process ends is written first.
atexit.register(WRITER.flush, 5.0)

guard()

if __name__ == "__main__":
    sys.exit(main())
