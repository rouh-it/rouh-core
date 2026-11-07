"""Riding out an overloaded model, without saying the same sentence twice.

Until now a 529 in the middle of a spoken turn ended it: the person heard "the
model call failed (529)" and the answer they had asked for never arrived. Most
of those clear in a second or two, and they should never have been the person's
problem.

So a request that fails for a reason that passes is tried again, with a delay
that doubles and a jitter on top, and after that with the next model in the
chain if there is one. Two things make that safe rather than merely hopeful.

**A failure that arrives after the headers is the same failure.** A streamed
request answers 200 before the model has written a word, so an overload a
moment later cannot be a status: it is an `error` event in the body, and the
exception it raises carries `status_code` 200. Judged by status alone that is
"nothing went wrong", and for a day it was - the turn ended and the person was
told "The model call failed (200)". The reason is read out of the body as well
as out of the status, and `RETRYABLE_TYPES` draws the same line through the
reasons that `RETRYABLE` draws through the statuses.

**A retry re-sends a request. It never re-runs a tool.** By the time a request
goes out, every tool it depends on has already run and its result is in the
message list. Sending that list again is sending the same words again; it does
not send a second email or run a command twice. Nothing in this file ever
touches a tool, and the loop in `brain.py` retries only around the model call.

**A request that has already said something is never re-sent.** The reply is
streamed to the voice and to the screen sentence by sentence, so an attempt
that produced words and then broke has already been half-spoken. Starting it
again would repeat those sentences, in the person's ear. Whether anything has
been said yet is something only the caller knows, which is why `should_retry`
is asked about it rather than deciding by itself.

The delay is full jitter over an exponential: a random wait between zero and
the exponential bound. Sleeping the same number of seconds as everybody else
is how a busy model stays busy, and "everybody else" here includes this
process's own parallel jobs.

The server's own numbers win over ours. `Retry-After` is honoured when it is
there, and so are Anthropic's rate-limit reset headers, which say when a
bucket refills rather than guessing at it.
"""
from __future__ import annotations

import asyncio
import logging
import random
import re
from datetime import datetime, timezone


log = logging.getLogger("rouh.retrying")

#: Statuses worth trying again. 529 is Anthropic's overload, 429 is the rate
#: limit, and the 5xx below are the ones that mean "not now" rather than "not
#: ever". 400, 401, 403 and 404 are deliberately not here: they are the same
#: answer however many times they are asked.
RETRYABLE = frozenset({408, 409, 429, 500, 502, 503, 504, 529})

#: The same judgement, made on Anthropic's own word for what went wrong rather
#: than on a status. It is the only judgement available when the failure
#: arrives **inside** a stream.
#:
#: A streamed request answers 200 and opens the stream before the model has
#: written anything, so a model that becomes overloaded a moment later cannot
#: say so in a status that has already gone: it says so in an `error` event in
#: the body, and the SDK raises `APIStatusError` built from a response whose
#: `status_code` is 200 (`anthropic/_streaming.py`). Deciding by status alone,
#: that is "not a failure at all, so not worth retrying", and the turn died
#: where the identical overload a moment earlier would have been ridden out.
#: On 22 September 2026 Petar was told "The model call failed (200)", which is
#: the one number that means nothing went wrong.
#:
#: The names are Anthropic's `ErrorType`, and this set is the same line drawn
#: through them that `RETRYABLE` draws through the statuses: overloaded, busy,
#: timed out and "something went wrong our end" pass; invalid request,
#: authentication, permission, not found and billing are the same answer
#: however many times they are asked.
RETRYABLE_TYPES = frozenset({"overloaded_error", "api_error",
                             "rate_limit_error", "timeout_error"})

#: How many times a request is sent in all, per model, before giving up on it.
ATTEMPTS = 4

#: The first wait, in seconds, and the ceiling on any of them. A spoken turn is
#: the most latency-sensitive thing this process does, so the ceiling is a
#: number of seconds a person will sit through and not a number they will not.
BASE_DELAY = 0.5
MAX_DELAY = 8.0

#: Past this, a wait the server itself asked for is not worth honouring inside
#: a spoken turn: the person has gone. It is honoured up to here and refused
#: beyond it, which fails the turn with something to say rather than sitting
#: mute for a minute.
MAX_SERVER_WAIT = 20.0


def status_of(exc) -> int | None:
    """The HTTP status an exception carries, however the SDK spelled it."""
    for attr in ("status_code", "status"):
        value = getattr(exc, attr, None)
        if isinstance(value, int):
            return value
    response = getattr(exc, "response", None)
    value = getattr(response, "status_code", None)
    return value if isinstance(value, int) else None


def is_failure_status(status: int | None) -> bool:
    """Whether that status is the request itself failing.

    Anything else - which in practice is 200 - means the request succeeded and
    the failure came later, in the body of a stream that had already started.
    """
    return status is not None and status >= 400


def error_type_of(exc) -> str:
    """Anthropic's own word for what went wrong, or "".

    The SDK reads it off the body and puts it on the exception as `.type`
    (`APIStatusError.__init__`). The body is read here as well, because an
    older SDK does not set that attribute and because the mid-stream error's
    body is the whole SSE event rather than an ordinary error envelope.
    """
    named = getattr(exc, "type", None)
    if isinstance(named, str) and named:
        return named
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        inner = body.get("error")
        if isinstance(inner, dict) and isinstance(inner.get("type"), str):
            return inner["type"]
    return ""


def is_retryable(exc) -> bool:
    """Whether this failure is the kind that passes.

    A connection that never opened counts: nothing was sent, so nothing can
    have happened twice.

    A request that failed says so in its status and is judged on that, which is
    every failure this file was written for. A request that succeeded and then
    broke says so in its body instead, and is judged on that: see
    `RETRYABLE_TYPES` for why the status is no use there.
    """
    status = status_of(exc)
    if is_failure_status(status):
        return status in RETRYABLE
    kind = error_type_of(exc)
    if kind:
        return kind in RETRYABLE_TYPES
    if status is not None:
        return status in RETRYABLE
    name = type(exc).__name__
    return name in ("APIConnectionError", "APITimeoutError", "ConnectionError",
                    "TimeoutError", "ReadTimeout", "ConnectTimeout")


def should_retry(exc, *, attempt: int, attempts: int = ATTEMPTS,
                 said_anything: bool) -> bool:
    """The whole decision, in one place.

    `said_anything` is whether this attempt already put words in front of the
    person. It is the caller's to know and it is the thing that makes a retry
    unsafe: the reply is streamed, so a broken attempt that spoke two sentences
    has already spoken them, and sending it again says them twice.
    """
    if said_anything:
        return False
    if attempt >= attempts:
        return False
    return is_retryable(exc)


def _headers_of(exc):
    for holder in (exc, getattr(exc, "response", None)):
        headers = getattr(holder, "headers", None)
        if headers is not None:
            return headers
    return None


def _get(headers, name: str) -> str:
    if headers is None:
        return ""
    try:
        return str(headers.get(name) or "")
    except Exception:
        return ""


def server_wait(exc, *, now: float | None = None) -> float | None:
    """How long the server itself asked us to wait, in seconds, or nothing.

    ``Retry-After`` first, because it is the direct answer. Failing that,
    Anthropic's own rate-limit reset headers, which say when the bucket that
    was emptied refills. Those are timestamps, so they need this machine's
    clock, which is why `now` is passed in rather than read here.
    """
    headers = _headers_of(exc)
    raw = _get(headers, "retry-after")
    if raw:
        try:
            return max(0.0, float(raw))
        except ValueError:
            pass                                 # an HTTP-date; the resets below cover it

    now = now if now is not None else datetime.now(timezone.utc).timestamp()
    waits = []
    for name in ("anthropic-ratelimit-requests-reset",
                 "anthropic-ratelimit-tokens-reset",
                 "anthropic-ratelimit-input-tokens-reset",
                 "anthropic-ratelimit-output-tokens-reset"):
        stamp = _get(headers, name)
        if not stamp:
            continue
        try:
            when = datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp()
        except ValueError:
            continue
        waits.append(max(0.0, when - now))
    # The soonest of them: the bucket that refills first is the one that
    # unblocks the request.
    return min(waits) if waits else None


def delay_for(attempt: int, exc=None, *, base: float = BASE_DELAY,
              cap: float = MAX_DELAY, now: float | None = None,
              jitter=random.random) -> float:
    """How long to wait before attempt number `attempt` + 1.

    Full jitter over an exponential: a wait drawn uniformly between zero and
    the bound. Everybody waiting exactly the same doubling number of seconds is
    how an overloaded model stays overloaded.
    """
    asked = server_wait(exc, now=now) if exc is not None else None
    if asked is not None and asked <= MAX_SERVER_WAIT:
        # The server knows when its own bucket refills. A little jitter still,
        # so a hundred callers told the same second do not all return in it.
        return asked + jitter() * min(1.0, base)
    bound = min(cap, base * (2 ** max(0, attempt - 1)))
    return jitter() * bound


def is_wrong_model(exc) -> bool:
    """A model this account cannot use, or that does not exist.

    Waiting does not fix that, and it is exactly what a fallback chain is for,
    so it moves on to the next model at once instead of sleeping four times.
    """
    return status_of(exc) in (403, 404)


def is_unbound_thinking(exc) -> bool:
    """Thinking handed back under a window it was not written in.

    Opus 5.5, like Fable 5.1, binds each thinking block to everything in front
    of it - the system prompt, the tools, the messages - and on the accounts it
    enforces that for, a block whose window has changed since is a 400 before
    a word is written: "The block is bound to a different conversation". The
    same request fails the same way however often it is sent, so this is not a
    retry. What does answer is the documented way out: the same window with
    the thinking taken out, once (`brain._unthought`).
    """
    return (status_of(exc) == 400
            and "bound to a different conversation" in str(exc))


# A request past the model's context window. The API says it in one of three
# ways, and each is read here:
#
# - a 400 before anything is written, "prompt is too long: 1052341 tokens >
#   1000000 maximum", when the request and all it carries is more than the
#   window holds;
# - a 413, when the request is past the size the API takes at all;
# - a reply that stops with `model_context_window_exceeded`, when the window
#   filled while the answer was being written, which is a stop reason and not
#   an error, and is read where the reply is.
#
# The words are the API's own, the ones Claude Code reads for its own "Prompt
# is too long". Not a retry either: the same request is the same length every
# time it is sent. Read by the Ask AI drawer (`rouh/askai.py`) and by the
# conversation (`rouh/chatkinds.py`), which each say it in their own words.

_TOO_LONG = re.compile(r"prompt is too long[^0-9]*(\d+)\s*tokens?\s*>\s*(\d+)", re.I)
_TOO_LONG_WORDS = ("prompt is too long", "input is too long", "context window",
                   "exceed context limit")


def api_words(exc) -> str:
    """What the API said, out of the error it said it in."""
    body = getattr(exc, "body", None)
    if isinstance(body, dict):
        said = body.get("error")
        if isinstance(said, dict) and said.get("message"):
            return str(said["message"])
    return str(getattr(exc, "message", "") or exc)


def overflowed(exc) -> tuple[int, int] | None:
    """How far a refusal went past the model's context window, or None.

    ``(tokens sent, tokens the window holds)`` when the API said both, ``(0,
    0)`` when it said the request was too long without them, and None for a
    refusal that is about something else.
    """
    status = getattr(exc, "status_code", 0)
    words = api_words(exc)
    if status == 400:
        found = _TOO_LONG.search(words)
        if found:
            return int(found.group(1)), int(found.group(2))
        if any(w in words.lower() for w in _TOO_LONG_WORDS):
            return 0, 0
    if status == 413:
        return 0, 0
    return None


# The monthly spending limit on the API account, which Anthropic says as a 400
# "invalid_request_error": "You have reached your specified API usage limits.
# You will regain access on 2026-11-01 at 00:00 UTC." It reached Petar on
# 29 October 2026 as "The model answered 400." in the Ask AI drawer, and on
# 23 October it stopped the chats for an hour, both times read as a bug in the
# page. Not a retry: every request is refused until the limit is raised in the
# Anthropic Console or the month turns. Read by the Ask AI drawer
# (`rouh/askai.py`) and the chat (`rouh/brain.py`), which say `capped_words`.

_CAPPED = re.compile(r"reached your specified API usage limits", re.I)
_REGAIN = re.compile(r"regain access on (\d{4}-\d{2}-\d{2}) at (\d{2}:\d{2}) UTC", re.I)
CAP_PAGE = "console.anthropic.com/settings/limits"


def capped(exc) -> datetime | None | bool:
    """Whether a refusal is the account's spending limit.

    False when it is not. When it is, the moment Anthropic said access comes
    back, or None when it did not say one.
    """
    if status_of(exc) != 400:
        return False
    words = api_words(exc)
    if not _CAPPED.search(words):
        return False
    found = _REGAIN.search(words)
    if not found:
        return None
    try:
        return datetime.fromisoformat(f"{found.group(1)}T{found.group(2)}+00:00")
    except ValueError:
        return None


def capped_words(back: datetime | None) -> str:
    """The spending limit, in one sentence for the screen and the voice."""
    if back is not None:
        from . import clock

        local = back.astimezone(clock.zone())
        when = f" It comes back by itself on {local:%-d %B} at {local:%H:%M}, or"
    else:
        when = " It comes back"
    return ("Anthropic has stopped answering: this month's spending limit on "
            f"Rouh's API account is used up.{when} as soon as the limit is raised "
            f"at {CAP_PAGE}.")


async def wait(seconds: float) -> None:
    if seconds > 0:
        await asyncio.sleep(seconds)


def said(exc, *, model: str, attempt: int, seconds: float) -> str:
    """One line for the log, saying what is being waited for and why.

    Named by what actually says something. A failure inside a stream carries
    status 200, and "answered HTTP 200 and is being tried again" is a line
    nobody could make sense of; its error type is the thing that is true.
    """
    status, kind = status_of(exc), error_type_of(exc)
    if is_failure_status(status):
        what = f"HTTP {status}"
    elif kind:
        what = f"{kind} mid-stream"
    elif status is not None:
        what = f"HTTP {status}"
    else:
        what = type(exc).__name__
    return (f"{model} answered {what} on attempt {attempt}; "
            f"trying again in {seconds:.1f}s")
