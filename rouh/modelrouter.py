"""Balanced: the router reads each chat message and says whether Cheaper can answer it.

Petar, 18 October 2026: "I would love it if we have dynamic swapping. An ai looks at
the request and decides which model should be employed." And then: "No quick rules.
Just look at the complexity and try to decide on that as a whole."

Petar, 23 October 2026 (card 1842), the plan that replaced the router of 18 October:

- **Only in Balanced** (`modeldefaults.Now.routed`), the default of the three modes,
  for the chats the Rouh model service routes (Rouh and every other chat). Best
  answers them on Smart and Saver on Cheaper, with no router at all.
- **OpenAI's Decisions API on GPT-6 Luna** (`llm.decide_model`, the use "Choosing the
  model in Balanced", `router_decisions`), through the LLM service and written down
  with its cost like every call. One question, easy or hard (`QUESTION`), answered with
  how likely each is. No reasoning step: a decision model answers without one, and
  better context takes its place.
- **Smart unless it is very sure.** Cheaper answers only when the probability that the
  message is easy is at least the bar (`Now.bar`: 0.9 from the model service, editable
  under Customise). Below it, unsure, slower than `config.router_seconds` (8 s since
  21 October 2026), refused, failed or with no key to ask, the message stays on Smart
  (`modeldefaults.AUTO_FALLBACK`). Until 23 October 2026 the limit was also held to 3 s
  here, which undid that raise: about one message in five that Petar sent in Balanced
  that evening went to Smart only because the Decisions API took longer than 3 s.
- **It reads the last few turns and the chat's title** (`BEFORE_MESSAGES`), the title
  being the one-line summary every chat already has, not only the latest message. The
  prompt cache a switch of model loses is not weighed: the cheap model is about a
  hundred times cheaper.
- **Beside the memory look-ups.** Petar, 22 October 2026 (fr_ce5ec6d1e11b): "both
  memory and mode decision calls should fire simultaneously." It is started first thing
  in the turn (`runtime.Turn._run`), its reads go through a pool of its own (`off`), and
  the brain waits for it only once the look-ups are under way (`brain.Brain.run_turn`).
  The moment it starts and the moment it decides are said on the turn's timeline
  (`rouh/turntrace.py`), never only once the answer is written.
- **Once a turn.** The turn keeps its model through every tool loop.
- **Written down** with the turn's call (`modeloutcomes.note_route`) and shown as the
  "Model decision" line with the person's message (`timeline`, kept in
  `RouteTimeline`): the tier, the model, and how sure the router was.

The router of 18 October 2026, a text model asked for a tier in words (the use
"router"), and the third tier it could pick, Best, went the same day (principle A3).

Petar, 24 October 2026: "Without OpenAI, the Balanced router becomes a plain 'easy or
hard?' question to the cheapest available model." So on an install with no OpenAI key
the Decisions API is not asked at all, and the use "Choosing the model without OpenAI"
(`router_question`, on Cheaper's list cheapest first) is asked one word instead
(`PLAIN`): Cheaper answers only when it says easy, and everything else - hard, anything
it cannot read, slow, failed or off - stays on Smart, the same rule as the Decisions API's.
A plain answer has no probability, so the bar does not apply to it.
"""
from __future__ import annotations

import asyncio
import contextvars
import functools
import logging
import time
from dataclasses import dataclass

from . import dbwork
from .config import config as _config, is_decisions_model, model_name

log = logging.getLogger("rouh.modelrouter")

USE = DECISIONS_USE = "router_decisions"
PURPOSE = DECISIONS_PURPOSE = "router_decisions"
#: How long the Decisions API may take before the message is answered on Smart, when the
#: config has no `router_seconds` (it has, 8 s). It answers in about a second, but often in
#: 2 to 3.5 s, and the memory look-ups beside it take about as long, so the wait is mostly hidden.
DECISIONS_SECONDS = 8.0
#: How much of the new message and of each turn before it it reads, and how many turns.
NEW_CHARS = 6000
BEFORE_CHARS = 700
BEFORE_MESSAGES = 6

#: The one question asked of the Decisions API: easy or hard, with how likely each is.
QUESTION = "difficulty"
EASY, HARD = "easy", "hard"
DECIDE = ("Rouh, a personal assistant, is about to answer the new message in this conversation. "
          "Is it easy enough for a quick, inexpensive model to answer it just as well as the most "
          "capable one? Judge it as a whole, with what came before it: how complex it is, how much "
          "it matters that the answer is right, and whether it needs careful work with tools, code "
          "or long reasoning.")
#: The plain question asked without OpenAI: one word back.
PLAIN = ("You decide which model answers a message to Rouh, a personal assistant. "
         "Read the conversation and the new message. Answer with one word: easy, only when you "
         "are very sure a quick, inexpensive model answers it just as well as the most capable "
         "one; otherwise hard. Judge it as a whole: how complex it is, how much it matters that "
         "the answer is right, and whether it needs careful work with tools, code or long reasoning.")
QUESTION_USE = QUESTION_PURPOSE = "router_question"
MEANS = {EASY: "A quick, inexpensive model answers it as well as the most capable one would.",
         HARD: "It needs the most capable model: it is complex, it matters, or it needs careful "
               "work with tools, code or long reasoning."}

#: The router's own threads for its reads and notes, so it never waits in line behind memory's look-ups or
#: anything else on the shared pool. A few: two reads at once for each turn starting at the same moment.
_POOL = dbwork.Executor(max_workers=4, thread_name_prefix="router")


def off(fn, *args, **kwargs):
    """`asyncio.to_thread` on the router's own pool, with the caller's context (whose turn it is)."""
    run = functools.partial(contextvars.copy_context().run, fn, *args, **kwargs)
    return asyncio.get_running_loop().run_in_executor(_POOL, run)


@dataclass
class Decision:
    """What the router decided for one turn."""

    tier: str
    reason: str
    model: str
    effort: str
    #: Whether the router answered; False is the fallback, Smart.
    ok: bool
    ms: int
    #: The tier the conversation was last answered on, or "".
    before: str = ""
    #: How it went, for the "Model decision" line (`timeline`): picked, timeout, error,
    #: unreadable or no_router; the router's model; when it was asked and when it
    #: answered, in wall-clock seconds; what went wrong; and the limit.
    outcome: str = ""
    router: str = ""
    began_at: float = 0.0
    sent_at: float | None = None
    back_at: float | None = None
    error: str = ""
    limit_s: float = 0.0
    #: "decisions" when OpenAI's Decisions API answered.
    via: str = ""
    #: How likely it said the message is easy, and the bar that had to be cleared.
    easy: float | None = None
    bar: float = 0.0
    #: What the call read and cost, from its answer.
    tokens_in: int = 0
    cost: float | None = None

    def shown(self) -> dict:
        """What the (i) under the answer says."""
        from .modeldefaults import TIER_NAMES

        return {"tier": self.tier, "tier_name": TIER_NAMES.get(self.tier, self.tier),
                "model": self.model, "model_name": model_name(self.model),
                "reason": self.reason, "auto": True}


def timeline(d: "Decision | None", turn_started: float, *, tier: str = "", model: str = "",
             chosen: bool = False, mode: str = "", chat: str = "") -> dict:
    """How an exchange's model was decided (app/turnline.js `routeDraw`), kept with
    the turn (`RouteTimeline`). With a decision, the router's steps in milliseconds
    from the turn's start (`turn_at`, in wall-clock seconds, which lines them up with
    the message's memory timeline, `recalling.MessageMemory.timeline`'s `began`); without one, a chat on a fixed tier, a
    mode that answers without a router (`mode`), or with `chosen` a tier the person
    pressed for this answer (outcome `chosen`). `chat` is Cheap, Smart or Auto when the chat
    is set to one beside the composer (`chatkinds.own_choice`): without a decision that is
    the outcome `chat`, a fixed tier the chat was set to, and with one it is said beside it."""
    from .modeldefaults import CHOICE_NAMES

    def at(t):
        return None if t is None else max(0, int(round((t - turn_started) * 1000)))

    from .chatkinds import CHOICE_NAMES as CHAT_NAMES

    said = {"chat_choice": chat, "chat_choice_name": CHAT_NAMES.get(chat, "")} if chat else {}
    if d is None:
        return {"auto": False, "outcome": "chosen" if chosen else ("chat" if chat else "fixed"),
                "tier": tier, "tier_name": CHOICE_NAMES.get(tier, tier.title()), "model": model,
                "model_name": model_name(model) if model else "", "mode": mode,
                "turn_at": turn_started, **said}
    end = d.began_at + d.ms / 1000 if d.began_at else None
    return {"auto": True, "outcome": d.outcome or ("picked" if d.ok else "error"),
            "tier": d.tier, "tier_name": CHOICE_NAMES.get(d.tier, d.tier), "model": d.model,
            "model_name": model_name(d.model), "reason": d.reason, "before": d.before,
            "router": d.router, "router_name": model_name(d.router) if d.router else "",
            "limit_ms": int(d.limit_s * 1000), "began_ms": at(d.began_at or None),
            "sent_ms": at(d.sent_at), "back_ms": at(d.back_at), "decided_ms": at(end),
            "took_ms": (int(round((d.back_at - d.sent_at) * 1000))
                        if d.back_at is not None and d.sent_at is not None else None),
            "error": d.error, "turn_at": turn_started, "via": d.via, "mode": mode or "balanced",
            "easy": d.easy, "bar": d.bar, "tokens_in": d.tokens_in, "cost": d.cost, **said}


def _text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(str(b.get("text") or "") for b in content
                        if isinstance(b, dict) and b.get("type") == "text")
    return ""


def _attached(content) -> str:
    """What is attached to the message, by kind, never its contents."""
    if not isinstance(content, list):
        return ""
    kinds = [str(b.get("type") or "") for b in content
             if isinstance(b, dict) and b.get("type") not in ("text", None)]
    return f"\n\n(With {len(kinds)} attachment{'s' if len(kinds) != 1 else ''}: {', '.join(kinds)}.)" \
        if kinds else ""


def reading(content, before: list[tuple[str, str]], title: str = "") -> str:
    """What the router reads: the chat's title, the last few turns before the message,
    the new message, and what is attached to it."""
    lines = []
    for role, text in before[-BEFORE_MESSAGES:]:
        text = " ".join(str(text or "").split())
        if text:
            who = "Person" if role == "user" else "Rouh"
            lines.append(f"{who}: {text[:BEFORE_CHARS]}{'...' if len(text) > BEFORE_CHARS else ''}")
    said = _text(content).strip()
    asked = said[:NEW_CHARS] + ("..." if len(said) > NEW_CHARS else "")
    title = " ".join(str(title or "").split())[:200]
    return ((f"The conversation is about: {title}\n\n" if title else "")
            + (("What came before, oldest first:\n" + "\n".join(lines) + "\n\n") if lines else "")
            + "The new message:\n" + (asked or "(no words)") + _attached(content))


def history_of(rows: list[dict]) -> list[tuple[str, str]]:
    """The conversation's last messages as (role, words), from `memory.history`."""
    out = []
    for m in rows or []:
        text = _text(m.get("content"))
        if text.strip() and m.get("role") in ("user", "assistant"):
            out.append((m["role"], text))
    return out


def title_of(chat: str) -> str:
    """The chat's title, its one-line summary, or ""."""
    try:
        from .models.objects import Chat

        return str(Chat.objects.filter(id=chat).values_list("title", flat=True).first() or "")
    except Exception:
        return ""


def _percent(p: float | None) -> str:
    return "?" if p is None else f"{round(100 * p)}%"


async def decide(chat: str, content, before, *, turn_id: str,
                 org_id: str | None = None, cfg=None, on_start=None) -> Decision:
    """The tier this turn answers on. Never raises and never takes much longer than
    `config.router_seconds`: the fallback is Smart. `before` is what came before the message
    (`history_of`), or an awaitable of it still being read. `on_start(model)` is called
    the moment the Decisions API is asked, for the turn's timeline."""
    from . import chatkinds, llm, llmlog, modeldefaults, modeloutcomes

    cfg = cfg or _config
    use = chatkinds.use_for(chat)
    began_at = time.time()
    started = time.monotonic()
    limit = float(getattr(cfg, "router_seconds", DECISIONS_SECONDS))
    # What came before it may still be being read (`runtime.Turn.routed`): all four side by side.
    if not isinstance(before, list):
        before, last, now, title = await asyncio.gather(
            before, off(modeloutcomes.last_tier, chat), off(modeldefaults.Now, org_id, cfg),
            off(title_of, chat))
    else:
        last, now, title = await asyncio.gather(off(modeloutcomes.last_tier, chat),
                                                off(modeldefaults.Now, org_id, cfg), off(title_of, chat))
    tier, reason, ok = modeldefaults.AUTO_FALLBACK, "", False
    outcome, error, sent_at, back_at, easy, tokens, cost = "no_router", "", None, None, None, 0, None
    bar = now.bar
    router = now.pair(USE).model
    smart = modeldefaults.TIER_NAMES[modeldefaults.AUTO_FALLBACK]
    plain = None
    if router != modeldefaults.OFF and not now.keys.get("openai"):
        # No OpenAI key: the plain question, if its use is on and has a model here.
        asked = now.pair(QUESTION_USE)
        plain = asked if asked.model and asked.model != modeldefaults.OFF else None
    if plain is not None:
        router = plain.model
        try:
            if on_start is not None:
                on_start(router)
            with llmlog.about(purpose=QUESTION_PURPOSE, session_id=chat, subject=turn_id):
                sent_at = time.time()
                got = await asyncio.wait_for(llm.ask_model(
                    router, plain.effort, system=PLAIN, messages=reading(content, before, title),
                    max_tokens=16, cfg=cfg, org_id=now.org), limit)
                back_at = time.time()
            word = (got.text or "").strip().lower().strip(".!*\"' ")
            tokens = int((got.usage or {}).get("input_tokens") or 0) + int(
                (got.usage or {}).get("cache_read_input_tokens") or 0)
            if word.startswith(EASY) or word.startswith(HARD):
                ok, outcome, via = True, "picked", "question"
                tier = modeldefaults.CHEAPER if word.startswith(EASY) else modeldefaults.AUTO_FALLBACK
                reason = (f"{model_name(router)} said the message is easy, so Cheaper answers."
                          if tier == modeldefaults.CHEAPER else
                          f"{model_name(router)} said the message is hard, so {smart} answers.")
            else:
                outcome = "unreadable"
                reason = f"{model_name(router)} gave no answer it could read, so {smart} answered."
        except asyncio.TimeoutError:
            outcome, error = "timeout", f"it took longer than {limit:g} s"
            back_at = time.time() if sent_at is not None else None
            reason = f"The router took longer than {limit:g} s, so {smart} answered."
        except Exception as exc:  # noqa: BLE001 - the turn is answered whatever this does
            outcome, error = "error", llm.failure(exc)
            if sent_at is not None and back_at is None:
                back_at = time.time()
            reason = f"The router failed ({error}), so {smart} answered."
            log.warning("the router's plain question for %s failed (%s); %s answers", chat, error, smart)
    elif not router or router == modeldefaults.OFF:
        router, reason = "", f"Choosing the model in Balanced is off, so {smart} answered."
    elif not is_decisions_model(router):
        error = f"{model_name(router)} is not a model OpenAI's Decisions API takes"
        reason = f"{error}, so {smart} answered."
    elif not now.keys.get("openai"):
        reason, error = f"There is no OpenAI key to ask the router with, so {smart} answered.", "no OpenAI key"
    else:
        closed = llm.decisions_closed(cfg)
        try:
            if closed:
                raise llm.Refused(f"OpenAI's Decisions API turned this key away ({closed})")
            if on_start is not None:
                on_start(router)
            with llmlog.about(purpose=PURPOSE, session_id=chat, subject=turn_id):
                sent_at = time.time()
                got = await asyncio.wait_for(llm.decide_model(
                    router, input=reading(content, before, title), cfg=cfg,
                    questions=[llm.choice(QUESTION, DECIDE, [EASY, HARD], MEANS)]), limit)
                back_at = time.time()
            tokens = int((got.usage or {}).get("input_tokens") or 0) + int(
                (got.usage or {}).get("cache_read_input_tokens") or 0)
            cost = got.cost
            answer = got.answer(QUESTION)
            if answer is None or answer.refused or not answer.probabilities:
                outcome = "unreadable"
                reason = f"The Decisions API gave no answer, so {smart} answered."
            else:
                easy = float(answer.probabilities.get(EASY, 0.0))
                ok, outcome, via = True, "picked", "decisions"
                tier = modeldefaults.CHEAPER if easy >= bar else modeldefaults.AUTO_FALLBACK
                reason = (f"The Decisions API is {_percent(easy)} sure it is easy"
                          + (f", at or above the bar of {_percent(bar)}, so Cheaper answers."
                             if tier == modeldefaults.CHEAPER else
                             f", below the bar of {_percent(bar)}, so {smart} answers."))
        except asyncio.TimeoutError:
            outcome, error = "timeout", f"it took longer than {limit:g} s"
            back_at = time.time() if sent_at is not None else None
            reason = f"The router took longer than {limit:g} s, so {smart} answered."
            log.info("the router for %s took longer than %ss; %s answers", chat, limit, smart)
        except Exception as exc:  # noqa: BLE001 - the turn is answered whatever this does
            outcome, error = "error", llm.failure(exc)
            if sent_at is not None and back_at is None:
                back_at = time.time()
            reason = f"The router failed ({error}), so {smart} answered."
            log.warning("the router for %s failed (%s); %s answers", chat, error, smart)
    via = ("question" if plain is not None else "decisions") if ok else ""
    pair = now.tier_pair(use, tier)
    ms = int((time.monotonic() - started) * 1000)
    log.info("balanced in %s: %s (%s) in %d ms%s: %s", chat, tier, pair.model, ms,
             "" if ok else ", fallen back", reason)
    return Decision(tier=tier, reason=reason, model=pair.model, effort=pair.effort, ok=ok, ms=ms,
                    before=last, outcome=outcome, router=router, began_at=began_at, sent_at=sent_at,
                    back_at=back_at, error=error, limit_s=limit, via=via, easy=easy, bar=bar,
                    tokens_in=tokens, cost=cost)
