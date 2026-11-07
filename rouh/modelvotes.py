"""Blind comparisons: the person's own vote between two answers, the main signal that ranks models.

Petar, 24 October 2026, the design agreed in chat that day, and what it decided here:

- **A separate opt-in, off by default** (`modeldefaults.compares`), apart from sharing the
  totals, and worded plainly on its toggle: it sends the person's own request to a second
  model provider.
- **Occasionally, never in the way.** At most `compare_per_day` comparisons a person a day
  (1 to start, adjustable on the Models page), and only for some of the answers that could
  be one (`CHANCE`). The normal answer is shown at once and is never held back or
  interrupted: the second model is asked only once the turn is over, in the background
  (`after_turn`), and the comparison appears under the answer afterwards (`model_compare` on
  the socket). It is easy to ignore: two answers labelled A and B, the models' names hidden,
  left and right shuffled, and five choices, A, B, Tie, Neither and Skip. Ignoring it is
  Skip, with no reminder and no notice (principle N1): a comparison nobody voted on by the
  end of its day is counted as skipped (`totals`).
- **Only where a second answer is harmless.** The chats (`ELIGIBLE`), and only an answer
  that was words alone: one request, no tool of any kind called (`_plain`), so nothing was
  sent, booked, bought or written. The second model is asked with no tools at all, the
  same instructions and the same conversation as text, so it cannot do anything either.
- **The second model** is the first model on the same list from another provider this
  install has a key for (`modeldefaults.second_opinion`, the double calls' own pick): the
  use's own selection on the Models page decides it, and with one provider's key there is
  no comparison.
- **What is kept and sent is only** the use, the two model ids, which side was which, and
  the vote (`ModelVote`); never the request or either answer, and no ids or names. The two
  answers exist only in the message to the page. Votes go in the same daily anonymous
  payload as the totals (`rouh/modeloutcomes.py`, `votes`), under the same rule on rouh.land
  that a model or use from fewer than 20 installs is left out, and rouh.land ranks the
  models of each use from them (its `rouhit/rankings.py`).
- **The double calls' model judge is replaced by the person** where a person is there to
  vote: a chat's answer is compared here and voted on, never judged by a model. Double
  calls (`llm.double`) stay for the answers nobody is there to judge, and run only with
  this opt-in on, since they too send the request to a second provider.

The second answer is asked through the LLM service with its cost written down (`llm.ask_model`,
purpose `model_vote`), like every call (principle D3).
"""
from __future__ import annotations

import asyncio
import json
import logging
import random
import secrets
import time
from datetime import datetime, timezone

log = logging.getLogger("rouh.modelvotes")

#: The uses a comparison can be of: the chats, where a person reads the answer.
ELIGIBLE = ("general", "chats")
#: The share of the answers that could be compared that are, within the daily limit, when the
#: installation says none (`config.compare_chance`).
CHANCE = 0.25
#: The votes there are, and what each means.
VOTES = ("a", "b", "tie", "neither", "skip")
#: How long the second model may take before the comparison is dropped.
SECOND_SECONDS = 90.0
#: The most of the conversation the second model is given, in messages before the question.
HISTORY = 12
PURPOSE = "model_vote"
#: Said to the second model, so its answer does not give away whose it is: the comparison is blind.
BLIND = ("\n\nIn this answer do not say which model you are or which company made you, even if "
         "asked: this answer is compared blind with another.")
#: Who was asked today, and how often: {user id: [day, count]}, kept here only, for the limit.
ASKED = "model_votes_asked"

_running: set = set()


class Refused(ValueError):
    """A vote that was not taken, with why."""


def _day(at: float | None = None) -> str:
    return datetime.fromtimestamp(time.time() if at is None else at, timezone.utc).strftime("%Y-%m-%d")


def _v():
    from .models import ModelVote

    return ModelVote


# --- whether to compare -------------------------------------------------------------------

def _asked_state() -> dict:
    from .models.memory import AppState

    raw = AppState.objects.filter(key=ASKED).values_list("value", flat=True).first()
    try:
        got = json.loads(raw) if raw else {}
    except ValueError:
        got = {}
    return got if isinstance(got, dict) else {}


def _room_today(user_id: str, per_day: int) -> bool:
    if per_day <= 0 or not user_id:
        return False
    held = _asked_state().get(user_id) or []
    return not (len(held) == 2 and held[0] == _day() and int(held[1]) >= per_day)


def _count_asked(user_id: str) -> None:
    from .models.memory import AppState

    state = _asked_state()
    held = state.get(user_id) or []
    today = _day()
    state = {k: v for k, v in state.items() if isinstance(v, list) and v and v[0] == today}
    state[user_id] = [today, (int(held[1]) if len(held) == 2 and held[0] == today else 0) + 1]
    AppState.objects.update_or_create(key=ASKED, defaults={"value": json.dumps(state)})


def _text(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(str(b.get("text") or "") for b in content
                         if isinstance(b, dict) and b.get("type") in ("text", "input_text", "output_text"))
    return ""


#: What in an answer means a tool was called, in each provider's words.
TOOL_KINDS = ("tool_use", "server_tool_use", "function_call", "tool_search_call", "web_search_call",
              "code_interpreter_call", "mcp_call")


def _plain(rows) -> bool:
    """Whether a turn's answer was words alone: one request, answered with no tool called."""
    if len(rows) != 1:
        return False
    row = rows[0]
    if row.status != "ok" or not (row.text or "").strip():
        return False
    content = (row.response or {}).get("content") if isinstance(row.response, dict) else None
    return not any(isinstance(b, dict) and b.get("type") in TOOL_KINDS for b in content or [])


def _system_of(row) -> str:
    from . import llmlog

    try:
        asked = llmlog.request_of(row)
    except Exception:
        return ""
    system = asked.get("system")
    if isinstance(system, list):
        return "\n\n".join(str(b.get("text") or "") for b in system if isinstance(b, dict))
    return str(system or "")


def _wait_for_rows(turn_id: str, seconds: float = 5.0) -> list:
    """The turn's requests, once the log has finished writing them."""
    from .models import LLMRequest

    end = time.monotonic() + seconds
    while True:
        rows = list(LLMRequest.objects.filter(turn_id=turn_id, purpose="turn").order_by("id"))
        if rows and all(r.status != "sent" for r in rows):
            return rows
        if time.monotonic() > end:
            return rows
        time.sleep(0.25)


def _prepare(chat: str, turn_id: str, root, who, use: str, asked: str, history):
    """Everything a comparison needs, read on a thread, or None for no comparison now.
    `asked` is what the person said, and `history()` the conversation before it."""
    from . import modeldefaults

    org = str(getattr(who, "org_id", "") or "") or modeldefaults.org_now(who)
    if use not in ELIGIBLE or not modeldefaults.compares(org):
        return None
    user = str(getattr(who, "user_id", "") or "")
    if not _room_today(user, modeldefaults.compare_per_day(org)):
        return None
    from .config import config

    if random.random() >= float(getattr(config, "compare_chance", CHANCE)):
        return None
    rows = _wait_for_rows(turn_id)
    if not _plain(rows):
        return None
    first = rows[0]
    model = str(first.served_model or first.model or "")
    second = modeldefaults.second_opinion(use, model, org)
    if second is None:
        return None
    if not str(asked or "").strip():
        return None
    try:
        before = history() or []
    except Exception:
        before = []
    talk = [{"role": m.get("role"), "content": _text(m.get("content"))}
            for m in before[-HISTORY:] if m.get("role") in ("user", "assistant") and _text(m.get("content")).strip()]
    talk.append({"role": "user", "content": str(asked)})
    while talk and talk[0]["role"] != "user":
        talk.pop(0)
    # Two messages of the same role in a row are one, as every provider takes them.
    merged: list[dict] = []
    for m in talk:
        if merged and merged[-1]["role"] == m["role"]:
            merged[-1] = {"role": m["role"], "content": merged[-1]["content"] + "\n\n" + m["content"]}
        else:
            merged.append(m)
    _count_asked(user)
    return {"org": org, "use": use, "first": model, "first_text": str(first.text or ""),
            "second": second, "system": _system_of(first), "messages": merged, "user": user}


async def _compare(chat: str, turn_id: str, root, who, use: str, asked: str, history, send) -> None:
    from . import llm, llmlog

    try:
        ready = await asyncio.to_thread(_prepare, chat, turn_id, root, who, use, asked, history)
        if ready is None:
            return
        second = ready["second"]
        with llmlog.about(who, purpose=PURPOSE, session_id=chat, subject=use):
            other = await asyncio.wait_for(llm.ask_model(
                second.model, second.effort, system=ready["system"] + BLIND, messages=ready["messages"],
                max_tokens=4000, org_id=ready["org"]), SECOND_SECONDS)
        if not other.text.strip():
            return
        # Which side the answer already given is on is a coin toss, so a person who favours
        # the left favours neither model.
        first_on = random.choice(("a", "b"))
        a, b = ((ready["first"], ready["first_text"]), (other.model, other.text))
        if first_on == "b":
            a, b = b, a
        token = secrets.token_urlsafe(18)
        await asyncio.to_thread(lambda: _v().objects.create(
            org_id=ready["org"], use=use, model_a=a[0], model_b=b[0], first=first_on,
            day=_day(), token=token))
        await send({"type": "model_compare", "token": token, "root": root,
                    "a": a[1], "b": b[1]})
    except Exception as exc:                 # a comparison is never anybody's problem
        log.info("a comparison in %s did not finish: %s", chat, exc)


def after_turn(chat: str, turn_id: str, root, who, use: str, asked: str, history, send) -> bool:
    """A turn of a chat ended with its answer shown: maybe compare it, in the background.
    `asked` is what the person said, `history()` the conversation before it, and `send` how a
    message reaches the chat's tabs. Never raises, never waits."""
    try:
        if use not in ELIGIBLE or who is None:
            return False
        task = asyncio.get_running_loop().create_task(
            _compare(chat, turn_id, root, who, use, asked, history, send))
        _running.add(task)
        task.add_done_callback(_running.discard)
        return True
    except Exception:
        log.exception("a comparison could not be started")
        return False


# --- the vote ------------------------------------------------------------------------------

def vote(who, token: str, said: str) -> None:
    """The person's vote, by the comparison's one-time word, from their own organisation."""
    said = str(said or "").strip().lower()
    if said not in VOTES:
        raise Refused("A vote is A, B, Tie, Neither or Skip.")
    token = str(token or "").strip()
    if not token:
        raise Refused("That comparison is not here.")
    done = _v().objects.filter(token=token, org_id=str(getattr(who, "org_id", "") or ""),
                               vote="").update(vote=said, token="")
    if not done:
        raise Refused("That comparison was already answered, or is not here.")
    log.info("a comparison was answered: %s", said)


# --- what leaves ---------------------------------------------------------------------------

def totals(org_id: str, since: float) -> list[dict]:
    """The votes not yet sent, as counts per day, use, pair of models (left and right),
    which side the answer already given was on, and the vote. One left unanswered past its
    day is a skip."""
    today = _day()
    groups: dict[tuple, int] = {}
    for r in (_v().objects.filter(org_id=org_id, counted_on="", day__gte=_day(since))
              .values("day", "use", "model_a", "model_b", "first", "vote")):
        said = r["vote"] or ("skip" if r["day"] < today else "")
        if not said:
            continue                 # still on the screen today
        key = (r["day"], r["use"], r["model_a"], r["model_b"], r["first"], said)
        groups[key] = groups.get(key, 0) + 1
    return [{"day": d, "use": u, "model_a": a, "model_b": b, "first": f, "vote": v, "count": n}
            for (d, u, a, b, f, v), n in sorted(groups.items())]


def counted(org_id: str, since: float, day: str) -> None:
    """The votes just sent are marked, so none is sent twice; one still waiting today stays."""
    today = _day()
    _v().objects.filter(org_id=org_id, counted_on="", day__gte=_day(since)).exclude(
        vote="", day=today).update(counted_on=day, token="")
