"""Plain words: a term the owner would not know is explained where it is first used, and a term they
asked about is explained from then on.

Built by the nightly feature run, night 13, 16 October 2026 (task 94, idea I-098). In two of his
Work chats on 14 and 15 October 2026 he stopped five times to ask what a word in an answer or on a
page meant: "66(a) is what?", "What is cve?", "What does that title mean? What is stewardship",
"still didn't undrrstand", and of a list of names, "90 % of those are words a high school or
college kid will not know what they mean". Each was a question he should not have had to ask.

So, while its switch is on, two things change, and nothing is drawn on any screen:

- **Every reply and every page** is written under one more rule (`RULE`): the first time a term,
  an abbreviation, a legal reference or a title is used that a college student would not know, it
  is explained in a few plain words in the same sentence. Rouh's own turns carry it beside the
  clock (`block`), and every run Rouh starts carries it after the agent instructions
  (`for_runs`, from `agent_instructions.block`), so a run's page is written that way too.
- **A term he asks about is kept** (`notice`): when his own message asks what something means,
  in English or Bulgarian ("what is WIPO?", "66(a) is what?", "what does SOC stand for",
  "какво е EOOD"), the term is kept in his own `user_settings` (`KEPT`, the newest `KEEP`), and
  both places name the kept terms as ones to explain every time they come up, not only the first.
  That is Petar's lesson L5 (task 94, `feedback.md`): what he had to correct once holds.

**No model call of its own.** The term is found by code, from the shape of his question; the
rule is words in the prompt the turn was going to make anyway.

**Whose.** Kept under the speaker of the turn, user and organisation; a run is given the terms
of its own organisation's people.

**Its switch** is `plain_words` (`rouh/switches.py`), off until Petar keeps it in Mutations: off,
nothing is kept and neither prompt changes.
"""
from __future__ import annotations

import json
import logging
import re
import time

log = logging.getLogger("rouh.plain_words")

#: The gene's switch (`rouh/switches.py`).
SWITCH = "plain_words"
TITLE = ("Plain words: a term you would not know is explained where it is first used, and a "
         "term you asked about is explained from then on")
#: The setting the terms he asked about are kept in, and how many are kept.
KEPT = "plain_words_asked"
KEEP = 40
#: The longest term kept, in characters and in words.
MOST_CHARS = 48
MOST_WORDS = 4

RULE = (
    "Plain words. The first time you use a term, an abbreviation, a legal or standards reference, "
    "a job title or a name of a method that a college student would not know, explain it in a few "
    "plain words in the same sentence, for example \"a CVE (a public number for one known security "
    "flaw)\" or \"Section 66(a) (the rule that lets an application filed abroad reach the US)\". "
    "Explain each term once in a reply or a page, not again. When a plain word says the same "
    "thing, use the plain word instead of the term."
)

# What a question about a word looks like. Each pattern's group "t" is the term.
_ASKS = [
    re.compile(r"^\s*(?:and\s+|so\s+|ok(?:ay)?,?\s+)?what\s*(?:is|'s|’s|are|was)\s+"
               r"(?P<t>[^?.!,;:\n]{1,60}?)\s*\??\s*$", re.I),
    re.compile(r"^\s*(?P<t>[^?.!,;:\n]{1,60}?)\s+(?:is|are|means)\s+what\s*\??\s*$", re.I),
    re.compile(r"^\s*what\s+does\s+(?P<t>[^?.!,;:\n]{1,60}?)\s+"
               r"(?:mean|stand\s+for)\s*\??\s*$", re.I),
    re.compile(r"^\s*what\s+do\s+you\s+mean\s+by\s+(?P<t>[^?.!,;:\n]{1,60}?)\s*\??\s*$", re.I),
    re.compile(r"^\s*(?:какво\s+(?:е|значи|означава))\s+"
               r"(?P<t>[^?.!,;:\n]{1,60}?)\s*\??\s*$", re.I),
]
# A "term" that is really a question about the conversation, not about a word.
_NOT_TERMS = {
    "it", "this", "that", "that one", "this one", "they", "them", "these", "those", "next",
    "the next step", "the plan", "the problem", "the point", "the difference", "the time",
    "the date", "the cost", "the price", "the status", "happening", "going on", "wrong",
    "up", "new", "left", "missing", "better", "best", "the best", "your view", "you",
    "your name", "the weather", "the matter", "the catch", "the risk", "the answer",
    "това", "то", "тя", "той",
}
_LEAD = re.compile(r"^(?:the|a|an)\s+(?=\S)", re.I)
# "that title", "this section": a question about something on the screen, not a word.
_POINTING = re.compile(r"^(?:this|that|these|those|това|този|тази|тези)\b", re.I)


def on(org_id=None) -> bool:
    from . import switches

    return switches.on(SWITCH, org_id or None)


def asked_terms(text: str) -> list[str]:
    """The terms a message asks the meaning of, in order, or none. Only a short question about a
    word counts, sentence by sentence, so a long instruction that happens to hold "what is" never
    keeps anything; and "what is the plan" or "what does that title mean" is a question about the
    conversation, not about a word."""
    out: list[str] = []
    pieces = [piece for line in str(text or "").splitlines()
              for piece in re.split(r"(?<=\?)\s+", line)]
    for line in pieces:
        line = " ".join(line.split())
        if not line or len(line) > 90:
            continue
        for pattern in _ASKS:
            m = pattern.match(line)
            if not m:
                continue
            term = m.group("t").strip(" \"'“”‘’`")
            if not term or term.lower() in _NOT_TERMS or _POINTING.match(term):
                break
            led = _LEAD.match(term)
            if led:
                term = term[led.end():]
                # "the plan", "a difference": an everyday word about the conversation.
                if re.fullmatch(r"[a-zа-я]+", term):
                    break
            if (term and len(term) <= MOST_CHARS and len(term.split()) <= MOST_WORDS
                    and term.lower() not in _NOT_TERMS and re.search(r"\w", term)
                    and term.lower() not in (t.lower() for t in out)):
                out.append(term)
            break
    return out


def asked_term(text: str) -> str:
    """The first term a message asks the meaning of, or ""."""
    found = asked_terms(text)
    return found[0] if found else ""


def _held(user_id: str, org_id: str) -> list[dict]:
    from .models import UserSetting

    value = (UserSetting.objects.filter(user_id=str(user_id), org_id=org_id or "", name=KEPT)
             .values_list("value", flat=True).first())
    try:
        held = json.loads(value) if value else []
    except (TypeError, ValueError):
        held = []
    return [h for h in held if isinstance(h, dict) and h.get("term")] if isinstance(held, list) else []


def _put(user_id: str, org_id: str, held: list[dict]) -> None:
    from .models import UserSetting

    UserSetting.objects.bulk_create(
        [UserSetting(user_id=str(user_id), org_id=org_id or "", name=KEPT,
                     value=json.dumps(held[:KEEP], ensure_ascii=False), updated_at=time.time())],
        update_conflicts=True, unique_fields=["user_id", "name"],
        update_fields=["org_id", "value", "updated_at"])


def notice(who, text: str) -> list[str]:
    """Keep the terms the speaker's message asks about. The terms kept, or none (off, nobody, not
    a question about a word). Never raises."""
    try:
        if who is None or not on(getattr(who, "org_id", None)):
            return []
        terms = asked_terms(text)
        user_id, org_id = str(getattr(who, "user_id", "")), str(getattr(who, "org_id", "") or "")
        if not terms or not user_id:
            return []
        lower = {t.lower() for t in terms}
        held = [h for h in _held(user_id, org_id) if h["term"].lower() not in lower]
        now = time.time()
        _put(user_id, org_id, [{"term": t, "at": now} for t in terms] + held)
        from . import evolution

        evolution.used(SWITCH, "term_kept", who=who,
                       detail="kept " + ", ".join(f"\"{t}\"" for t in terms) + " as terms asked about")
        log.info("plain words: kept %s as terms asked about", terms)
        return terms
    except Exception:  # noqa: BLE001 - keeping a word is never worth a turn
        log.exception("a term asked about could not be kept")
        return []


def _terms_line(terms: list[str]) -> str:
    if not terms:
        return ""
    return ("Terms ‹owner› has asked the meaning of, newest first. Explain each of them in plain "
            "words every time it comes up, not only the first time: " + "; ".join(terms) + ".")


def block(who) -> str:
    """What a turn's prompt is told, or "" (off, nobody)."""
    try:
        if who is None or not on(getattr(who, "org_id", None)):
            return ""
        terms = [h["term"] for h in _held(str(getattr(who, "user_id", "")),
                                         str(getattr(who, "org_id", "") or ""))]
        return "\n".join(x for x in (RULE, _terms_line(terms)) if x)
    except Exception:  # noqa: BLE001 - a line of context is never worth a turn
        log.exception("plain words could not be put in the prompt")
        return ""


def for_runs(org: str) -> str:
    """The section every run of this organisation is given after its agent instructions, or ""
    (off). The terms are the organisation's people's, newest first."""
    try:
        if not org or not on(org):
            return ""
        from .models import UserSetting

        terms: list[str] = []
        seen: set[str] = set()
        rows = UserSetting.objects.filter(org_id=org, name=KEPT).values_list("value", flat=True)
        held: list[dict] = []
        for value in rows:
            try:
                got = json.loads(value) if value else []
            except (TypeError, ValueError):
                continue
            held.extend(h for h in got if isinstance(h, dict) and h.get("term"))
        for h in sorted(held, key=lambda h: -(h.get("at") or 0)):
            if h["term"].lower() not in seen:
                seen.add(h["term"].lower())
                terms.append(h["term"])
        text = "## Plain words\n\n" + RULE
        line = _terms_line(terms[:KEEP])
        return text + ("\n\n" + line if line else "")
    except Exception:  # noqa: BLE001 - a run starts whatever this says
        log.exception("plain words could not be put in a run's instructions")
        return ""


__all__ = ["KEPT", "RULE", "SWITCH", "TITLE", "asked_term", "asked_terms", "block", "for_runs", "notice", "on"]
