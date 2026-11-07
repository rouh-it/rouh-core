"""Putting a conversation's system prompt together from the rules, and what a request was told.

Petar, 21 October 2026: "I imagined 1 place should rule the behavior and this is rules." And 30 October 2026,
of the Rules page's built-in rules and the lock on twenty of them: "Fully remove that lock", "Every rule should
be in a database and editable. Nothing should be hardcoded", and "all rules should be equal". So every
instruction a conversation is told is a rule of the person's, a row of their Synapse Master (`rouh/rules.py`),
written, reworded, turned off and deleted on the Rules page like any other. Nothing here holds a rule's words.

A rule says, in its own row, when it is told (`when`, `applies`): in which kinds of work (`rules.reach`), and in
a conversation under which conditions - the tools the turn has, which model answers, a written or spoken reply,
a turn from Telegram, a fact the code worked out. A rule with a `place` is told at that place in the prompt, in
the part that stays the same from turn to turn ("cached") or the part told with the clock ("turn"); every other
rule is told in the person's sections (`rules.prompt_parts`). What a rule's row says is also what its
"Conditions:" lines on the page say (`rules.condition_lines`), so the two cannot disagree.

What is here is the code that assembles: the `Prompt` a turn is put together in, stretch by stretch, the live
values a rule may hold (`VALUES`), and the live context only the code knows - the time, which mailboxes are
whose, the goals, what Synapse found, the tool catalogue made from the tool registry. Each of those is named
in what a request was told (`told`) with the code it comes from, so it is never mistaken for a rule.

Not here, and never claimed to be: the tools' own schemas, which are the code's contract with the model and
come from the registry that runs them; the model provider's own rules; and every check of a permission,
which is code and stays code, whatever any rule says or whether it is on at all.

**What a request was told** (`told`). Every system prompt put together here is described, stretch by
stretch, in `prompt_part`, found by the digest of its exact text. A request in the log of requests
(`rouh/llmlog.py`) keeps the system prompt it really sent, so the Rules page can take any request of the
person's, find its parts, and say for each stretch which rule at which version and why, or which live
value - and check, character for character, that it is what went to the model.
"""
from __future__ import annotations

import hashlib
import logging
import string
import time
from dataclasses import dataclass, field

log = logging.getLogger("rouh.prompting")

PARTS = ("cached", "turn")


def _parts():
    from .models import PromptPart

    return PromptPart


def placeholders(text: str) -> list[str]:
    """The `{value}` names in a rule's words, in order, each once. `{{` and `}}` are a brace."""
    out: list[str] = []
    for _, name, _, _ in string.Formatter().parse(str(text or "")):
        if name is not None and name not in out:
            out.append(name)
    return out


def fill(text: str, values: dict) -> str:
    """A rule's words with its live values in. A value the code did not give is left as it is written,
    never an error: a turn is never lost to a rule's wording."""
    if "{" not in text and "}" not in text:
        return text

    class _Keep(dict):
        def __missing__(self, key):
            return "{" + key + "}"

    try:
        return string.Formatter().vformat(text, (), _Keep({k: ("" if v is None else v) for k, v in values.items()}))
    except (ValueError, IndexError, KeyError):
        log.warning("a rule's words could not be filled in, so they are told as written")
        return text


# --- when one applies -------------------------------------------------------------------------


@dataclass(frozen=True)
class Situation:
    """What the code knows about the request a prompt is for, and nothing a rule could change."""

    #: The names of the tools the request declares.
    tools: frozenset = frozenset()
    #: "claude", "luna" (OpenAI's, `rouh/luna.py`) or "other" (Google's or xAI's,
    #: `rouh/compat.py`): which kind of model answers.
    provider: str = "claude"
    #: How the reply is made, "text" or "voice", and how the words came (`rouh/replymode.py`).
    reply: str = "text"
    heard: str = "typed"
    #: Whether the model is told to start with a turn mark (`rouh/turnmarks.py`).
    marks: bool = False
    #: Where the turn came from beyond the screen: "telegram" for the phone, "" otherwise.
    channel: str = ""
    #: Switches and facts the code worked out: "autorecall", "untrusted", "own_mail", "born",
    #: "nicknamed", "new_rouh".
    flags: frozenset = frozenset()


#: Each live value a rule can hold, in plain words, for the page and for what a request was told.
VALUES = {"own_mail": "Rouh's own email address", "name": "the model's name", "model": "the model",
          "rouh_name": "the name this Rouh was born with", "born_day": "the day it was born",
          "rouh_nickname": "the nickname the person gave this Rouh",
          "company": "whose model it is",
          "app_dir": "where Rouh's code is", "version": "the build running", "repo": "where the workspace is",
          "reading": "the tools that read the web", "hosts": "Rouh's own web addresses",
          "came": "how the person's words came", "today": "the date", "now": "the time", "place": "the time zone",
          "offset": "its offset from UTC", "finished": "the finished mark", "cut_off": "the cut-off mark",
          "still_thinking": "the still-thinking mark"}


def value_words(names) -> str:
    return ", ".join(VALUES.get(n, n) for n in names)


#: The keys of a rule's `when` that only a conversation turn can answer (`Situation`): a rule with any of them
#: is told only in chats, since a run's brief or a memory answer has no tools, model or reply of its own.
SITUATIONAL = ("tools_all", "tools_any", "tools_none", "provider", "reply", "channel", "marks", "flags")

#: Each tool a rule's condition can name, in plain words, for its "Conditions:" line ("the web search tool").
#: One not here is named as the tool is.
TOOLS_SAID = {
    "web_search": "web search", "web_fetch": "web page", "youtube_transcript": "YouTube transcript",
    "youtube_search": "YouTube search", "linkedin_search": "LinkedIn search", "make_picture": "picture",
    "browser": "live browser", "shipping": "shipping", "read_rouh_link": "Rouh link",
    "assistant_job": "job", "worker_outbox": "job note", "send_mail": "send mail",
    "look_into": "helper (look_into)", "read_workspace": "workspace", "show_canvas": "canvas",
    "decisions": "decisions", "publish_task": "publish task", "one_runs": "one program",
    "reply_to_task": "reply to a job", "update_contact_profile": "contacts",
    "meeting_people": "meeting guests", "send_telegram": "Telegram", "slack_send": "Slack",
}

#: How each other condition is said, as the end of "only when ...".
_SAID = {"reply": {"text": "the reply is written on the screen", "voice": "the reply is spoken aloud"},
         "provider": {"claude": "Claude answers", "luna": "an OpenAI model answers",
                      "other": "a Google or xAI model answers"},
         "channel": {"telegram": "the message came from Telegram"},
         "flag": {"autorecall": "automatic recall is on",
                  "untrusted": "a tool in the turn can bring in words that are not yours (mail, Slack and the like)",
                  "own_mail": "Rouh has an email address of its own",
                  "no_own_mail": "Rouh has no email address of its own",
                  "born": "this Rouh has been born and has a name of its own",
                  "nicknamed": "the person has given this Rouh a nickname",
                  "new_rouh": "setting up was finished less than two weeks ago"}}


def _tools(names, joint: str) -> str:
    """"the browser tool", "the browser and job tools", "the web search or web page tool"."""
    said = [TOOLS_SAID.get(n, n) for n in names]
    words = said[0] if len(said) == 1 else ", ".join(said[:-1]) + f" {joint} " + said[-1]
    return f"the {words} tool" + ("s" if len(said) > 1 and joint == "and" else "")


def situation_words(when: dict) -> list[str]:
    """Each condition of a conversation turn a rule's `when` holds, in plain words, each the end of "only
    when ...": the same keys `applies` checks, in the same order."""
    parts: list[str] = []
    if when.get("tools_all"):
        parts.append(f"the turn has {_tools(when['tools_all'], 'and')}")
    if when.get("tools_any"):
        parts.append(f"the turn has {_tools(when['tools_any'], 'or')}")
    if when.get("tools_none"):
        parts.append(f"the turn does not have {_tools(when['tools_none'], 'or')}")
    for k in ("provider", "reply", "channel"):
        if when.get(k):
            parts.append(_SAID[k].get(when[k], f"{k} is {when[k]}"))
    if when.get("marks"):
        parts.append("your words came from the microphone")
    for f in when.get("flags") or []:
        parts.append(_SAID["flag"].get(f, f))
    return parts


def applies(when: dict, s: Situation) -> bool:
    """Whether a rule with this `when` is told in this situation. Every condition must hold."""
    if not when:
        return True
    if when.get("tools_all") and not all(t in s.tools for t in when["tools_all"]):
        return False
    if when.get("tools_any") and not any(t in s.tools for t in when["tools_any"]):
        return False
    if when.get("tools_none") and any(t in s.tools for t in when["tools_none"]):
        return False
    for k in ("provider", "reply", "channel"):
        if when.get(k) and getattr(s, k) != when[k]:
            return False
    if when.get("marks") and not s.marks:
        return False
    if when.get("flags") and not all(f in s.flags for f in when["flags"]):
        return False
    return True


# --- putting a prompt together ----------------------------------------------------------------


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass
class Prompt:
    """One part of a system prompt, put together stretch by stretch, each stretch described.

    `placed` are the rules with a place in this part (`rules.placed`), in their order; `at(position)` adds
    every one of them before a position whose `when` holds, each filled in with the live `values`, so the code
    can put live context and the person's other rules in their place among them; `context` and `add` add
    stretches that are not placed rules. `text` is the part as sent; `segments` says what each stretch of it
    is."""

    situation: Situation
    part: str
    values: dict = field(default_factory=dict)
    placed: list = field(default_factory=list)
    pieces: list[tuple[str, dict]] = field(default_factory=list)
    _next: int = 0

    def at(self, position: int) -> "Prompt":
        """Every rule of this part placed before `position`, not yet added."""
        while self._next < len(self.placed) and self.placed[self._next]["place"]["position"] < position:
            self._rule(self.placed[self._next])
            self._next += 1
        return self

    def rest(self) -> "Prompt":
        return self.at(1 << 30)

    def _rule(self, r: dict) -> None:
        if not r.get("on", True) or not applies(r.get("when") or {}, self.situation):
            return
        text = (fill(r["text"], self.values) if r.get("fills") else r["text"]).strip("\n")
        if not text.strip():
            return
        why = "; ".join(situation_words(r.get("when") or {})) or "every turn"
        names = placeholders(r["text"]) if r.get("fills") else []
        if names:
            why += "; filled in live: " + value_words(names)
        self.add(text, kind="rule", key=r["id"], title=r["title"], version=r.get("version"), why=why)

    def add(self, text: str, *, kind: str, key: str = "", title: str = "", version: int | None = None,
            why: str = "", **more) -> None:
        text = str(text or "").strip("\n")
        if not text.strip():
            return
        self.pieces.append((text, {"kind": kind, "key": str(key), "title": title, "version": version,
                                   "why": why, **more}))

    def context(self, text: str, label: str, source: str) -> None:
        """Live context: a value or a block the code worked out, which is not a rule."""
        self.add(text, kind="context", key=source, title=label, why=f"live, from {source}")

    def finish(self, say=None) -> tuple[str, list[dict]]:
        """The part's words as sent, and what each stretch of it is. `say` fills the owner's marks in
        (`owner.say`) before the words are measured, so the description fits the bytes that go out."""
        self.rest()
        texts: list[str] = []
        segs: list[dict] = []
        for i, (text, meta) in enumerate(self.pieces):
            if say is not None:
                text = say(text)
            sep = "\n\n" if i else ""
            texts.append(sep + text)
            segs.append({**meta, "chars": len(sep) + len(text), "digest": _digest(sep + text)[:16]})
        return "".join(texts), segs


def keep(org: str, text: str, segments: list[dict]) -> str:
    """Write down what a part of a prompt was made of, once per exact text, off the turn's way."""
    digest = _digest(text)
    org = str(org or "")
    if not org or (org, digest) in _KEPT:
        return digest
    _KEPT.add((org, digest))
    if len(_KEPT) > 5000:
        _KEPT.clear()

    def write():
        Part = _parts()
        Part.objects.get_or_create(org_id=org, digest=digest,
                                   defaults={"chars": len(text), "segments": segments, "created_at": time.time()})

    try:
        from . import llmlog

        llmlog.WRITER.put(write)
    except Exception:  # noqa: BLE001 - never a turn's problem
        log.warning("what a prompt was made of could not be written down", exc_info=True)
    return digest


_KEPT: set[tuple[str, str]] = set()


# --- what a request was told ------------------------------------------------------------------


def _sent_parts(request: dict) -> list[str]:
    """The texts a request sent as its system prompt, in order: Claude's system blocks; an OpenAI request's
    instructions and the message of Rouh's own that carries the clock."""
    out: list[str] = []
    system = request.get("system")
    if isinstance(system, list):
        return [b.get("text", "") for b in system if isinstance(b, dict) and b.get("type") == "text"]
    # An OpenAI request's instructions are kept as its system piece, and its input as its messages
    # (`llmlog.request_of`).
    if isinstance(system, str):
        out.append(system)
    for item in request.get("messages") or request.get("input") or []:
        if isinstance(item, dict) and item.get("role") == "developer" and isinstance(item.get("content"), str):
            out.append(item["content"])
            break
    return out


def _match(org: str, sent: str):
    """The part recorded for the exact text `sent`, or for the start of it (an OpenAI request adds notes
    after its instructions), with how much of `sent` it covers."""
    Part = _parts()
    row = Part.objects.filter(org_id=org, digest=_digest(sent)).first()
    if row is not None:
        return row, len(sent)
    for row in Part.objects.filter(org_id=org, chars__lt=len(sent)).order_by("-created_at")[:200]:
        if _digest(sent[:row.chars]) == row.digest:
            return row, row.chars
    return None, 0


def told(org: str, user_id: str, request_id) -> dict:
    """What one request of this person's was told, stretch by stretch, checked against what it sent.

    Only a request of this person's, in this organisation: any other is "not found". The words of a rule
    and of the live context come out of the request itself, never out of the rules as they are now, so this
    shows what the model really received; a stretch whose words are not the ones recorded says so."""
    from . import llmlog, redaction, rule_groups
    from .models import LLMRequest

    try:
        ident = int(request_id)
    except (TypeError, ValueError):
        raise LookupError("That is not a request number.") from None
    row = LLMRequest.objects.filter(id=ident, org_id=str(org), user_id=str(user_id)).first()
    if row is None:
        raise LookupError(f"Request {ident} is not one of yours.")
    request = llmlog.request_of(row)
    parts = []
    for n, sent in enumerate(_sent_parts(request)):
        part, covered = _match(str(org), sent)
        stretches = []
        if part is not None:
            at = 0
            for seg in part.segments:
                words = sent[at:at + seg["chars"]]
                at += seg["chars"]
                ok = _digest(words)[:16] == seg.get("digest")
                stretch = {**{k: v for k, v in seg.items() if k != "digest"}, "matches": ok,
                           "text": redaction.scrub(words.lstrip("\n"))}
                # Where a rule told on its own sits on the Rules page, for one deleted since (the page finds
                # the rest by their rows).
                if seg.get("kind") == "rule":
                    stretch["group"] = rule_groups.sort(words)
                stretches.append(stretch)
        else:
            stretches.append({"kind": "unknown", "title": "Not put together from the rules",
                              "why": "No record of how this part was made: a request from before the rules "
                                     "moved, or one made somewhere else.",
                              "chars": len(sent), "matches": None, "text": redaction.scrub(sent)})
        if part is not None and covered < len(sent):
            stretches.append({"kind": "context", "title": "Notes added for this request", "key": "rouh/luna.py",
                              "why": "added after the instructions for this one request",
                              "chars": len(sent) - covered, "matches": None,
                              "text": redaction.scrub(sent[covered:])})
        parts.append({"name": "The part that stays the same" if n == 0 else "This turn's part",
                      "chars": len(sent), "recorded": part is not None, "stretches": stretches})
    tools = request.get("tools") or []
    return {"id": row.id, "at": row.started_at, "model": row.model, "provider": row.provider,
            "purpose": row.purpose, "session_id": row.session_id, "turn_id": row.turn_id,
            "status": row.status, "parts": parts, "asked": _asked(row),
            "tools": {"count": len(tools) if isinstance(tools, list) else 0,
                      "from": "the tool registry that runs them (rouh/tools.py); never a rule"}}


def _asked(row) -> dict:
    """The message of the person's a request was answering, its words and the files they attached, as the chat
    draws them (`memory.Memory._said`): the message its turn was kept against (`turn_records`), or else the
    person's last message in that chat before the request began. Petar, 30 October 2026: "after I click on a
    chat name, I want you to display the message I wrote, and the file I included". {"found": False} when there
    is none, and {"note": True} when the turn answered a note Rouh's own software wrote in their place."""
    from .memory import Memory
    from .models import TranscriptMessage, TurnRecord

    if not row.session_id:
        return {"found": False}
    q = TranscriptMessage.objects.filter(session_id=row.session_id, role="user")
    msg = None
    if row.turn_id:
        mid = (TurnRecord.objects.filter(turn_id=row.turn_id, session_id=row.session_id)
               .values_list("message_id", flat=True).first())
        if mid:
            msg = q.filter(id=mid).first()
    if msg is None:
        msg = q.filter(ts__lte=row.started_at + 1).order_by("-id").first()
    if msg is None:
        return {"found": False}
    if msg.note:
        return {"found": False, "note": True}
    said = Memory._said({"id": msg.id, "ts": msg.ts, "role": msg.role, "content": msg.content,
                         "note": msg.note, "notice": msg.notice, "root": msg.root})
    if said is None:
        return {"found": False}
    return {"found": True, "id": msg.id, "ts": msg.ts, "text": said.get("text") or "",
            "attachments": said.get("attachments") or []}


def recent(org: str, user_id: str, limit: int = 25, chat: str = "") -> list[dict]:
    """This person's latest conversation requests, newest first, without their words."""
    from . import conversations
    from .models import LLMRequest

    q = LLMRequest.objects.filter(org_id=str(org), user_id=str(user_id), purpose="turn").exclude(system_piece="")
    if chat:
        q = q.filter(session_id=str(chat))
    titles = {}
    got = list(q.order_by("-id").values("id", "started_at", "model", "session_id", "turn_id", "status")[:limit])
    try:
        from . import forks
        from .models import Chat

        titles = {k: v for k, v in Chat.objects.filter(id__in={g["session_id"] for g in got})
                  .values_list("id", "title") if not conversations.is_untitled(v)}
        # A chat with no title of its own, such as a fork of General, by what was first asked in it, as the
        # chats' own list names it (`forks.asked_of`). Petar, 30 October 2026: "instead should say the title of
        # the chat", where it had said "A conversation".
        untitled = [g["session_id"] for g in got if g["session_id"] not in titles and g["session_id"] != "conversation"]
        titles.update({k: v for k, v in forks.asked_of(untitled).items() if v})
    except Exception:  # noqa: BLE001 - a request is listed without its chat's title
        log.warning("the titles of the chats could not be read", exc_info=True)
    # The main chat has no title of its own: the page calls it Rouh.
    return [{**g, "chat": titles.get(g["session_id"]) or ("Rouh, the main chat" if g["session_id"] == "conversation"
                                                         else conversations.UNTITLED)} for g in got]


__all__ = ["PARTS", "SITUATIONAL", "TOOLS_SAID", "VALUES", "Prompt", "Situation", "applies", "fill", "keep",
           "placeholders", "recent", "situation_words", "told", "value_words"]
