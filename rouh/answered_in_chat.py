"""Answered in a chat: a question waiting in Decisions that the owner already answered somewhere else.

Built by the nightly feature run, night 9, 12 October 2026 (task 94, idea I-085). Rouh asks the owner
things in Decisions - a goal step's approval, a task's choice, the work after a meeting - and he
answers a good many of them without going there, in the chat he happens to be in. On 11 October
2026 at 22:13 his time he told the chat of step 89-10 "I love the way you have structured the
lessons ... There are two things I want to change", which is the answer to goal 89's "Agree the
framework the quest drafted, or say what to change" (decision 176); on 12 October the question
was still open in Decisions, six days old, and the goal still waited on it. Thirty-three
questions waited on him that morning, the oldest from 24 September, and he had answered two of
them on the Decisions page all week.

So every question still waiting on him is read against what he said in his chats since it was
asked. Code picks the few of his own messages that are about it (the chats of its task and the
steps under it, and any message that shares its rarer words); when there are any, one model call
says whether one of them answers it, with his exact words, the answer they amount to, and why.
The decision then shows it above its answers - "You may have answered this already", where and
when he said it, his words, and what they answer - with **Answer with that** and **Not this**:

- **Answer with that** is his own press through the usual way back (`decisions.answer`, with its
  undo and, where a yes spends, sends or publishes, its second press). Where his words are one of
  the offered answers it gives that answer; where they are his own, it opens "Something else"
  with them written in, for him to read and send. Nothing is ever answered without his press.
- **Not this** is kept (Petar's lesson L5, task 94's `feedback.md`): the message it quoted is
  never offered for that question again.

**Made ahead and kept** (lesson L6): read in the background, kept by the question and the
messages it read in his own `user_settings`, and read again only when a new message about it
arrives, at most once an hour. A question nothing he said is about costs no call at all.

**Whose words.** The messages are the install's own chats, which are its owner's: only the
owner's questions are read (`telegram.phone_owner`, as `rouh/meeting_next.py` does), every
question is read by its own user and organisation, and what is kept is kept under them. A
message's text never reaches anybody else.

**What it costs.** One small call per question that something he said is about, its own pick on
the Models page (`modeldefaults.USES`, "Questions you already answered in a chat"), written down
under the purpose `answered_in_chat` (`rouh/llmlog.py`).

**Its switch** is `answered_in_chat` (`rouh/switches.py`): off, nothing is read, nothing is shown
and Not this cannot be pressed; the questions themselves are as they always were.
"""
from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
import math
import os
import re
import time

log = logging.getLogger("rouh.answered_in_chat")

#: The feature's switch (`rouh/switches.py`).
SWITCH = "answered_in_chat"
TITLE = ("Answered in a chat: a question waiting in Decisions that you already answered in a "
         "chat shows your words, to answer it with them in one press")
#: Its model pick (`modeldefaults.USES`) and what its requests are written down under.
USE = "answered_in_chat"
PURPOSE = "answered_in_chat"

#: How often the loop looks for a question to read, in seconds.
BEAT = float(os.environ.get("ANSWERED_BEAT_SECONDS") or 60)
MODEL_SECONDS = 120.0
#: A question is read again, when a new message about it arrives, at most this often.
READ_AGAIN = float(os.environ.get("ANSWERED_READ_AGAIN_SECONDS") or 3600)
#: A question that could not be read is tried again after this long, at most this often.
RETRY_SECONDS = 10 * 60
MOST_TRIES = 3
#: The most questions read in one beat, so the first beat after a deploy is not a burst.
MOST_PER_BEAT = 4
#: The most of his messages one reading reads, and how much of each.
MOST_MESSAGES = 8
MESSAGE_CHARS = 1800
ROUH_CHARS = 500
#: A word is rare among his messages when it is in at most this share of them, or in two.
RARE = 0.02
#: A message counts as about a question when it shares two of its rare words, weighing this
#: much, a long message's weight cut by the square root of its length in minutes of reading.
LEAST_SCORE = 8.0
FEW = 200
LEAST_SHARED = 2
#: A message in a chat of the question's own task, or a step under it, counts when it shares
#: any word with it, and weighs this much more.
OWN_TASK = 3.0
#: How much of a long question is read for its words: its title, where it is from and its
#: answers say what it is about, and a long question's tail mostly says how it works.
QUESTION_CHARS = 240
#: The setting the readings are kept in, by decision id, and how many are kept.
MADE = "answered_in_chat_made"
KEEP = 300
#: Questions this does not read: a message from somebody else is decided in its own case, in
#: minutes, and a yes there sends; an answer given offline is already his.
SKIP = frozenset({"mail", "offline"})

#: The first words of what the model is told, which is also how the stand-in for the model
#: knows it (`rouh/testing/fake_model.py`).
ASK = "You check whether ‹owner› already answered a question that is waiting for ‹him› in Rouh's Decisions."

SYSTEM = ASK + """

Rouh is ‹owner›'s assistant. It asks ‹him› questions in one list, Decisions: a choice in a task, a
goal step to approve, work to start after a meeting. ‹He› often answers in a chat instead, without
opening the list, and the question goes on waiting. You are given one waiting question, with
the answers it offers, and the messages ‹owner› wrote in ‹his› chats since it was asked, each with
what Rouh had just said before it.

Say whether one of ‹his› messages answers this question:

- Only when a message clearly gives an answer or a decision on this very question: the same
  matter, and an answer, not only talk about it, a new question, or a wish to think more. A
  message that answers a similar but different question does not count. When unsure, it is
  not answered.
- "answered": true or false.
- "message": the number of the message that answers it, in brackets in the list; 0 when none.
- "quote": ‹his› exact words from that message that give the answer, copied character for
  character, at most 300 characters; "" when none.
- "option": the id of the offered answer ‹his› words amount to, only when they plainly do; ""
  when they amount to something else, or to ‹his› own answer.
- "answer": ‹his› answer to this question as ‹he› gave it, in ‹his› voice (first person), at most
  three sentences, using ‹his› own words wherever you can; it may be sent as ‹his› answer, so add
  nothing ‹he› did not say. "" when not answered.
- "why": one sentence on how that message answers the question, or why none does.

Write plainly. Answer with one JSON object and nothing else:
{"answered": false, "message": 0, "quote": "", "option": "", "answer": "", "why": ""}"""

_WORD = re.compile(r"[^\W_][\w'-]*", re.UNICODE)
_STOP = frozenset("""
a about above after again against all also am an and any are aren't as at be because been
before being below between both but by can can't cannot could couldn't did didn't do does
doesn't doing don't down during each few for from further had hadn't has hasn't have haven't
having he her here hers herself him himself his how i if in into is isn't it it's its itself
just let's me more most my myself no nor not now of off on once only or other ought our ours
ourselves out over own same she should shouldn't so some such than that that's the their
theirs them themselves then there there's these they this those through to too under until
up very was wasn't we were weren't what when where which while who whom why will with won't
would wouldn't you your yours yourself yourselves
rouh owner task step steps tasks please okay ok yes yeah thing things something want like
make need know think see get got go going one two first new also say said says ask asked
answer answers question questions decide decision decisions choose pick option options way
should could would might will can let us use using used page pages chat chats run runs
today tomorrow yesterday week day days time now still just really very much many more less
good great nice well right sure maybe else other another every each some any all none
""".split())


def on(org_id) -> bool:
    from . import switches

    return switches.on(SWITCH, org_id or None)


def _text(value, most: int) -> str:
    return " ".join(str(value or "").split())[:most]


def _stem(w: str) -> str:
    """A word without its plural or its -ing and -ed, roughly: trucks and truck are one."""
    for end in ("ings", "ing", "ies", "es", "ed", "s"):
        if len(w) > len(end) + 3 and w.endswith(end):
            return w[:-len(end)] + ("y" if end == "ies" else "")
    return w


def _own_names(who) -> frozenset:
    """The owner's own names, in lower case: words too common in their chats to say what a
    message is about, like the rest of `_STOP`."""
    from . import owner

    try:
        found = owner.resolve(who)
    except Exception:                               # noqa: BLE001 - only fewer words skipped
        return frozenset()
    if found is None:
        return frozenset()
    return frozenset(w for n in (found.name, found.full_name)
                     for w in _WORD.findall(str(n or "").lower()))


def _words(text: str, skip: frozenset = frozenset()) -> set[str]:
    out = set()
    for w in _WORD.findall(str(text or "").lower()):
        w = w.strip("'-")
        if w in _STOP or w in skip:
            continue
        if w.isdigit() and len(w) >= 2 or len(w) >= 4:
            out.add(_stem(w))
    return out


# --- his messages ------------------------------------------------------------------------------


def _rows(sql: str, args=()) -> list[dict]:
    from django.db import connection

    with connection.cursor() as cur:
        cur.execute(sql, args)
        cols = [c[0] for c in cur.description]
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def _plain(content: str) -> str:
    from . import memory

    try:
        return memory._plain(json.loads(content))
    except (TypeError, ValueError):
        return str(content or "")


def his_messages(since: float) -> list[dict]:
    """His own messages since then, oldest first: never a tool's result, a note Rouh's software
    wrote in his place, a notice put into a chat, or Stop. {id, chat, ts, text}."""
    from . import memory

    out = []
    for r in _rows("SELECT id, session_id, ts, content FROM messages WHERE role = 'user' "
                   "AND NOT note AND NOT notice AND live AND ts > %s ORDER BY id", (since,)):
        content = r["content"] or ""
        if not memory._begins_a_question("user", content):
            continue
        text = _plain(content).strip()
        if not text or text.startswith("["):
            continue
        out.append({"id": int(r["id"]), "chat": r["session_id"], "ts": float(r["ts"]), "text": text})
    return out


def task_of(row) -> str:
    """The task a decision belongs to, when it says: its batch is task:<id> or goal:<id>."""
    batch = str(row.batch or "")
    for lead in ("task:", "goal:"):
        if batch.startswith(lead):
            return batch[len(lead):]
    return str(row.source_id) if row.source == "task" else ""


def chats_of_task(task_id: str) -> set[str]:
    """The chats of a task and of every task and step under it."""
    if not task_id:
        return set()
    rows = _rows(
        "WITH RECURSIVE t(id) AS (SELECT %s::text UNION SELECT l.dst_id FROM link l JOIN t "
        "ON l.src_id = t.id WHERE l.rel = 'owns' AND l.src_type = 'task' AND l.dst_type = 'task') "
        "SELECT dst_id FROM link WHERE rel = 'owns' AND src_type = 'task' AND dst_type = 'chat' "
        "AND src_id IN (SELECT id FROM t)", (task_id,))
    return {r["dst_id"] for r in rows}


def words_of(row) -> set[str]:
    """The words a question is about: its title, question, where it is from, and its answers."""
    parts = [row.title, row.context, str(row.question or "")[:QUESTION_CHARS]]
    parts += [o.get("label") for o in row.options or [] if isinstance(o, dict)]
    return _words(" ".join(str(p or "") for p in parts),
                  _own_names(getattr(row, "user_id", None)))


def about(row, messages: list[dict], df: dict[str, int], own: set[str],
          refused: set[int]) -> list[dict]:
    """The few of his messages since the question was asked that are about it, oldest first."""
    terms = words_of(row)
    total = max(len(messages), 1)
    scored = []
    for m in messages:
        if m["ts"] <= (row.created_at or 0) or m["id"] in refused:
            continue
        shared = terms & m["words"]
        if not shared:
            continue
        rare = {w for w in shared if df.get(w, 0) <= 2 or df.get(w, 0) / total <= RARE}
        # A word's weight as if he had written at least `FEW` messages, so a new install's few
        # do not make every word weigh nothing.
        score = (sum(math.log(1 + max(total, FEW) / df.get(w, 1)) for w in rare)
                 / max(1.0, len(m["text"].split()) / 60) ** 0.5)
        if m["chat"] in own:
            scored.append((score + OWN_TASK, m))
        elif len(rare) >= LEAST_SHARED and score >= LEAST_SCORE:
            scored.append((score, m))
    scored.sort(key=lambda s: (-s[0], -s[1]["id"]))
    return sorted((m for _s, m in scored[:MOST_MESSAGES]), key=lambda m: m["id"])


def fingerprint(found: list[dict]) -> str:
    return hashlib.sha1(",".join(str(m["id"]) for m in found).encode()).hexdigest()[:16] if found else ""


# --- what the model reads ----------------------------------------------------------------------


def _day(ts: float) -> str:
    from . import clock

    when = clock.moment(ts)
    if when is None:
        return ""
    return f"{when:%A} {when.day} {when:%B %Y}, {when:%H:%M}"


def rouh_before(chat: str, message_id: int) -> str:
    """What Rouh said last before one of his messages, cut to its end."""
    rows = _rows("SELECT content FROM messages WHERE session_id = %s AND id < %s AND role = "
                 "'assistant' ORDER BY id DESC LIMIT 1", (chat, message_id))
    said = _text(_plain(rows[0]["content"]) if rows else "", 20000)
    return ("..." + said[-ROUH_CHARS:]) if len(said) > ROUH_CHARS else said


def question(row, found: list[dict], titles: dict[str, str]) -> str:
    """Everything one reading reads about one question, as one text."""
    lines = [f"The question, asked on {_day(row.created_at)}:"]
    if row.context:
        lines.append(f"Where it comes from: {_text(row.context, 300)}")
    if row.title and row.title != row.question:
        lines.append(f"Title: {_text(row.title, 300)}")
    lines.append(f"Question: {_text(row.question, 1200)}")
    if row.why:
        lines.append(f"Why it matters: {_text(row.why, 600)}")
    offered = [o for o in row.options or [] if isinstance(o, dict) and o.get("id") and not o.get("href")]
    if offered:
        lines.append("The answers it offers:")
        for o in offered:
            lines.append(f'- id "{o["id"]}": {_text(o.get("label"), 140)}'
                         + (f" - {_text(o.get('detail'), 300)}" if o.get("detail") else ""))
    lines.append("‹He› may also answer in ‹his› own words." if row.allow_other
                 else "‹He› can only pick one of the offered answers.")
    lines += ["", "What ‹owner› said in ‹his› chats since, oldest first:"]
    for n, m in enumerate(found, 1):
        lines.append("")
        lines.append(f"[{n}] {_day(m['ts'])}, in the chat “{_text(titles.get(m['chat']) or 'untitled', 120)}”")
        if m.get("before"):
            lines.append(f"Rouh had just said: “{m['before']}”")
        lines.append(f"‹owner› said: “{_text(m['text'], MESSAGE_CHARS)}”")
    return "\n".join(lines)


def _same(a: str) -> str:
    return " ".join(re.sub(r"[“”\"'‘’]", "", str(a or "")).lower().split())


def read_answer(said: str, row, found: list[dict]) -> dict | None:
    """The model's answer as the decision shows it, or None when it says nothing answers it, or
    its answer does not hold: a message that is not in the list, or words that are not his."""
    hit = re.search(r"\{.*\}", said or "", re.S)
    try:
        got = json.loads(hit.group(0)) if hit else None
    except ValueError:
        got = None
    if not isinstance(got, dict) or got.get("answered") is not True:
        return None
    try:
        n = int(got.get("message") or 0)
    except (TypeError, ValueError):
        return None
    if not 1 <= n <= len(found):
        return None
    m = found[n - 1]
    quote = _text(got.get("quote"), 300).strip(" “”\"")
    if len(_same(quote)) < 3 or _same(quote) not in _same(m["text"]):
        # Words he never wrote are not his answer.
        return None
    option = str(got.get("option") or "").strip()
    offered = {o["id"]: o for o in row.options or []
               if isinstance(o, dict) and o.get("id") and not o.get("href")}
    if option not in offered:
        option = ""
    answer = _text(got.get("answer"), 1200)
    if not option and not answer:
        return None
    return {"message": m["id"], "chat": m["chat"], "at": m["ts"], "quote": quote,
            "option": option, "answer": answer, "why": _text(got.get("why"), 400)}


async def ask(who, text: str) -> tuple[str, str]:
    """One question to the model this use is set to: (what it said, the model asked)."""
    from . import llm

    try:
        got = await llm.ask(USE, system=SYSTEM, messages=[{"role": "user", "content": text}],
                            max_tokens=3000, who=who, org_id=str(who.org_id) or None,
                            purpose=PURPOSE, timeout=MODEL_SECONDS, read_only=True)
    except llm.Cannot:
        return "", ""
    return got.text, got.model


# --- what was read, kept -----------------------------------------------------------------------


def _held(user_id: str, org_id: str) -> dict:
    from .models import UserSetting

    value = (UserSetting.objects.filter(user_id=str(user_id), org_id=org_id or "", name=MADE)
             .values_list("value", flat=True).first())
    try:
        held = json.loads(value) if value else {}
    except (TypeError, ValueError):
        held = {}
    return {k: v for k, v in held.items() if isinstance(v, dict)} if isinstance(held, dict) else {}


def _put(user_id: str, org_id: str, held: dict) -> None:
    from .models import UserSetting

    newest = sorted(held, key=lambda k: held[k].get("at") or 0, reverse=True)[:KEEP]
    UserSetting.objects.bulk_create(
        [UserSetting(user_id=str(user_id), org_id=org_id or "", name=MADE,
                     value=json.dumps({k: held[k] for k in newest}, ensure_ascii=False),
                     updated_at=time.time())],
        update_conflicts=True, unique_fields=["user_id", "name"],
        update_fields=["org_id", "value", "updated_at"])


def attach(who, drawn: list[dict]) -> None:
    """Put what he said on each waiting decision it answers, as `said`, for the card to draw and
    Rouh's tool to read. Nothing when the switch is off. Never raises."""
    from . import decisions

    try:
        if not drawn or not on(who.org_id):
            return
        held = _held(who.user_id, who.org_id)
        if not held:
            return
        titles = {}
        for d in drawn:
            one = held.get(str(d.get("id")))
            said = (one or {}).get("said")
            if not said or d.get("status") not in decisions.ANSWERABLE:
                continue
            labels = {o.get("id"): o.get("label") for o in d.get("options") or [] if isinstance(o, dict)}
            if said.get("option") and said["option"] not in labels:
                continue
            titles.setdefault(said["chat"], None)
            d["said"] = {**said, "option_label": labels.get(said.get("option"), "") or "",
                         "link": f"/chat/{said['chat']}", "chat_title": ""}
        wanted = [c for c, t in titles.items() if t is None]
        if wanted:
            from .models import Chat

            names = dict(Chat.objects.filter(id__in=wanted).values_list("id", "title"))
            for d in drawn:
                if d.get("said"):
                    d["said"]["chat_title"] = _bare_title(names.get(d["said"]["chat"]) or "")
    except Exception:
        log.exception("what he already said could not be put on the decisions")


def answered(who, decision_id, picked) -> None:
    """His answer to a waiting question, given with Answer with that: the answer he already gave in
    a chat is the one he picked. Its use (`evolution.used`). Never raises."""
    try:
        if not picked or not on(who.org_id):
            return
        said = (_held(who.user_id, who.org_id).get(str(decision_id)) or {}).get("said") or {}
        if said.get("option") and said["option"] in [str(p) for p in picked]:
            from . import evolution

            evolution.used(SWITCH, "answered_with_that", who=who, detail=f"decision {decision_id}")
    except Exception:  # noqa: BLE001 - the answer stands whatever this says
        log.exception("an answer given with what he said in a chat could not be noted")


def _bare_title(title: str) -> str:
    """A chat's title without the mark a chat's title can start with."""
    return re.sub(r"^[^\w“\"(]+\s*", "", str(title or "")).strip() or "a chat"


def not_this(who, ident) -> dict:
    """He pressed Not this: the message it quoted is never offered for this question again."""
    from . import decisions

    if not on(who.org_id):
        raise decisions.Refused("That is turned off in Evolution, Mutations.")
    row = decisions._row(who, ident)
    if row is None:
        raise decisions.Refused("There is no such question.")
    held = _held(who.user_id, who.org_id)
    one = held.get(str(row.id)) or {}
    said = one.get("said") or {}
    refused = [int(x) for x in one.get("refused") or [] if str(x).isdigit()]
    if said.get("message") and int(said["message"]) not in refused:
        refused.append(int(said["message"]))
    held[str(row.id)] = {**one, "said": None, "refused": refused[-40:], "at": time.time(),
                         "not_at": time.time()}
    _put(who.user_id, who.org_id, held)
    log.info("decision %s: the owner said the chat message %s does not answer it", row.id,
             said.get("message"))
    return decisions.get(who, row.id) or {}


def _wants(one: dict | None, fp: str, now: float) -> bool:
    if one is None:
        return True
    if one.get("fp") == fp:
        # The same messages: only a reading that failed is tried again.
        return (not one.get("read") and int(one.get("tries") or 0) < MOST_TRIES
                and now - float(one.get("at") or 0) >= RETRY_SECONDS)
    # New messages about it: read again, though not more than once an hour, and never while
    # an answer found is still on show from messages he has not said no to.
    return now - float(one.get("read_at") or 0) >= READ_AGAIN


def due(who) -> list[tuple]:
    """(decision row, the messages about it) for each of his waiting questions that something
    he said since is about, and that has no reading for those messages yet, oldest first."""
    from . import decisions
    from .models import Decision

    rows = list(Decision.objects.filter(user_id=str(who.user_id), org_id=str(who.org_id or ""),
                                        status__in=decisions.WAITING)
                .exclude(source__in=SKIP).order_by("created_at"))
    if not rows:
        return []
    messages = his_messages(min(r.created_at or 0 for r in rows))
    if not messages:
        return []
    df: dict[str, int] = {}
    skip = _own_names(who)
    for m in messages:
        m["words"] = _words(m["text"], skip)
        for w in m["words"]:
            df[w] = df.get(w, 0) + 1
    held = _held(who.user_id, who.org_id)
    now = time.time()
    out, quiet = [], {}
    for row in rows:
        one = held.get(str(row.id))
        refused = {int(x) for x in (one or {}).get("refused") or [] if str(x).isdigit()}
        found = about(row, messages, df, chats_of_task(task_of(row)), refused)
        fp = fingerprint(found)
        if not found:
            if one is None or one.get("fp") != "":
                # Nothing he said is about it: kept as such, so it costs no call.
                quiet[str(row.id)] = {**(one or {}), "fp": "", "said": None, "at": now,
                                      "read": True}
            continue
        if one is not None and one.get("said") and one.get("fp") != fp:
            # An answer found is kept until he answers or says Not this; newer messages are
            # read when it is gone.
            continue
        if _wants(one, fp, now):
            out.append((row, found))
    if quiet:
        held = _held(who.user_id, who.org_id)
        held.update(quiet)
        _put(who.user_id, who.org_id, held)
    return out


def _context(row, found: list[dict]) -> str:
    from .models import Chat

    for m in found:
        m["before"] = rouh_before(m["chat"], m["id"])
    titles = {k: _bare_title(v or "") for k, v in
              Chat.objects.filter(id__in={m["chat"] for m in found}).values_list("id", "title")}
    return question(row, found, titles)


async def read(who, row, found: list[dict]) -> dict:
    """Read one question against what he said. {ok, said, model}; ok False when it could not be
    read (tried again later, at most `MOST_TRIES` times)."""
    from asgiref.sync import sync_to_async

    text = await sync_to_async(_context)(row, found)
    ok, said, model = True, None, ""
    try:
        words, model = await ask(who, text)
        if not model:
            ok = False
        else:
            said = read_answer(words, row, found)
    except Exception as exc:  # noqa: BLE001 - written down, tried again later
        log.warning("decision %s could not be read against his chats: %s", row.id, exc)
        ok = False
    fp = fingerprint(found)

    def keep():
        held = _held(who.user_id, who.org_id)
        old = held.get(str(row.id)) or {}
        tries = (int(old.get("tries") or 0) if old.get("fp") == fp else 0) + 1
        now = time.time()
        held[str(row.id)] = {**old, "fp": fp, "at": now, "model": model, "tries": tries,
                             "read": ok, "read_at": now if ok else old.get("read_at") or 0,
                             "said": said if ok else None,
                             "found_at": now if said and not (old.get("said") or {}).get(
                                 "message") == said.get("message") else old.get("found_at")}
        _put(who.user_id, who.org_id, held)

    await sync_to_async(keep)()
    return {"ok": ok, "said": said, "model": model}


# --- the loop ----------------------------------------------------------------------------------


class Reader:
    """Every minute: each question waiting on the owner that something he said since is about,
    and that has no reading for those words yet, is read; an answer found is put on the
    question, and he is told once, on the screen."""

    def __init__(self, *, owner, poke=None, tell=None) -> None:
        self.owner = owner
        self.poke = poke
        self.tell = tell
        self._registered = False
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.get_running_loop().create_task(self._run())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._task
            self._task = None

    async def _run(self) -> None:
        await asyncio.sleep(min(45.0, BEAT))
        while True:
            try:
                await self.beat()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("the answered-in-a-chat beat failed")
            await asyncio.sleep(BEAT)

    async def beat(self) -> list[int]:
        """One look. The ids of the questions found answered."""
        from asgiref.sync import sync_to_async

        who = await sync_to_async(self.owner)()
        if who is None:
            return []
        if not self._registered:
            # Listed in Mutations from the first beat; never turned on again.
            from . import switches

            await sync_to_async(switches.register)(SWITCH, TITLE, org_id=str(who.org_id))
            self._registered = True
        if not await sync_to_async(on)(who.org_id):
            return []
        found = []
        for row, messages in (await sync_to_async(due)(who))[:MOST_PER_BEAT]:
            got = await read(who, row, messages)
            if got.get("said"):
                found.append(row)
                from . import evolution

                await asyncio.to_thread(evolution.used, SWITCH, "answer_found", who=who,
                                        detail=f"decision {row.id}")
        if found:
            await sync_to_async(_notice)(who, found)
            if self.poke is not None:
                with contextlib.suppress(Exception):
                    self.poke()
            if self.tell is not None:
                with contextlib.suppress(Exception):
                    await self.tell(who)
        return [r.id for r in found]


def _notice(who, rows) -> None:
    """One notice on his screen for what one beat found, never on the phone: it can wait."""
    from . import decisions, notices

    try:
        if len(rows) == 1:
            row = rows[0]
            notices.post(who, kind="decision", key=f"answered:{row.id}:{fingerprint_of(who, row)}",
                         title="You may have answered this already",
                         body=f"{_text(row.title or row.question, 160)}: you answered it in a chat. "
                              "Answer it with that in one press, or say Not this.",
                         link=decisions.page_of(row), link_label="See it")
        else:
            ids = ",".join(str(r.id) for r in rows)
            notices.post(who, kind="decision", key=f"answered:{ids}",
                         title=f"{len(rows)} questions you may have answered already",
                         body="; ".join(_text(r.title or r.question, 80) for r in rows[:4])
                              + ". Each shows what you said, to answer it with that in one press.",
                         link="/decisions", link_label="See them")
    except Exception:
        log.exception("the notice for questions answered in a chat could not be written")


def fingerprint_of(who, row) -> str:
    one = _held(who.user_id, who.org_id).get(str(row.id)) or {}
    return str((one.get("said") or {}).get("message") or "")


def line_for_model(d: dict) -> str:
    """What the decisions tool tells Rouh about one, when he may have answered it already."""
    said = d.get("said")
    if not isinstance(said, dict):
        return ""
    gave = (f'the answer "{said.get("option_label")}"' if said.get("option") else
            f"in his own words: {str(said.get('answer') or '').rstrip('.')}")
    return (f" He may already have answered it in a chat (“{said.get('chat_title') or 'a chat'}”, "
            f"{_day(said.get('at') or 0)}), saying “{said.get('quote')}”, which reads as {gave}. "
            "Ask him whether to answer it with that; never answer it on this alone.")


__all__ = ["ASK", "PURPOSE", "Reader", "SWITCH", "SYSTEM", "TITLE", "USE", "about", "attach",
           "due", "his_messages", "line_for_model", "not_this", "on", "question", "read",
           "read_answer", "words_of"]
