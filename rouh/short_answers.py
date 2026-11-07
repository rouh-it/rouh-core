"""Short answers: a quick question in Ask AI is answered in a few plain sentences, and an answer
asked for "shortly" or "in one sentence" keeps to it.

Built by the nightly feature run, night 15, 18 October 2026 (task 94, idea I-102). In the three
weeks to 17 October 2026 Petar asked Ask AI, on his pages, what a word or a passage meant 27
times ("what is daca?", "explain this", "what does that mean"), and every answer ran to 200 to 600
words, with headings, lists and tables. Twice he asked for less himself and did not get it: "what
is wipo and how does it work? shortly" was answered in 335 words and a table (task 97, 14 October
2026), and "what does this sentence mean? shortly" in about 170. Ask AI's prompt says "Be
concise" (`askai.SYSTEM_PROMPT`), and that was not enough for a question that wants one
sentence. Petar's own design for Ask AI, the workspace skill `bb-ask-ai`, says "The AI answers in
one sentence by default"; that rule did not come over when Ask AI moved into Rouh.

**Version 2**, mutation request 3, 18 October 2026. Petar's words: "I want this to be the default
behavior, without me asking for it explicitly." So a short answer is no longer kept for the two
shapes below: every question in Ask AI is answered short unless he asks for more. The shapes
still decide how short, and a question that asks for more is the only one left as it was.

So, while its switch is on, one thing changes, and nothing is drawn on any screen: every question
gets one more line at the end of its turn (`note`), which says how long the answer may be, unless
it asks for more (`wants_more`: "in detail", "tell me more", "step by step", "подробно"). The
line's length is found by code, from the words of the question alone:

- **He said how long** (`asked_length`): "shortly", "briefly", "in short", "in one sentence",
  "in 2 sentences", "in a line", "tl;dr", "накратко", "с едно изречение". The answer keeps to it,
  and "shortly" with no number means two sentences.
- **A quick question about meaning** (`quick`): what a word, a name or a passage is or means,
  "what do you mean", "explain this", "I don't get it", "какво е", "обясни". The answer is three
  short sentences at most (five for "explain"), the meaning first, in plain words, with no
  heading, list or table; anything more waits until he asks for it.

- **It asks for a list, a comparison, a plan or steps** (`listing`): only as long as the question
  needs, each item one line, with no preamble, recap or closing offer.
- **It asks for a change to the page or for something written** (`working`): the work is as long
  as it needs to be, and the words around it are one or two sentences.
- **Any other question** (the default): four short sentences at most, the answer first, in plain
  words, with no heading, list or table unless the question cannot be answered without one.

**No model call of its own.** The shape is found by code; the line is words in the turn Ask AI
was going to send anyway, after the question, so the cached system prompt is never changed.

**Whose.** The line is about the question in hand and keeps nothing; the evidence of use is
written under the person who asked (`evolution.used`, its run `kept_short`).

**Its switch** is `short_answers` (`rouh/switches.py`), off until Petar keeps it in Mutations:
off, every turn is sent exactly as before.
"""
from __future__ import annotations

import logging
import re

log = logging.getLogger("rouh.short_answers")

#: The gene's switch (`rouh/switches.py`).
SWITCH = "short_answers"
TITLE = ("Short answers: every answer in Ask AI is short unless you ask for more, a question about "
         "what something means is a few plain sentences, and \"in one sentence\" is kept to")
#: The longest question that can be a quick one, in characters, once a length word is taken out.
QUICK_MOST = 90

_NUMBERS = {"one": 1, "a": 1, "an": 1, "single": 1, "two": 2, "a couple of": 2, "three": 3,
            "four": 4, "five": 5, "едно": 1, "две": 2, "три": 3}
_NUMBER = r"(?P<n>\d|one|a single|a|an|two|a couple of|three|four|five|едно|две|три)"
_UNIT = r"(?P<u>sentences?|lines?|words?|paragraphs?|изречения|изречение|думи|реда?)"

#: He said how long, with a number: "in 2 sentences", "in one line", "с едно изречение".
_COUNTED = re.compile(rf"(?:\b(?:in|with|using|within|max|at most)|(?<!\w)(?:с|в))\s+{_NUMBER}\s+{_UNIT}"
                      r"(?!\w)", re.I)
#: He said how long, in a word: "shortly", "briefly", "tl;dr".
_SHORT = re.compile(r"\b(?:shortly|briefly|in short|in brief|short answer|quick answer|short "
                    r"version|keep it short|one[- ]liner|tl;?dr|eli5)\b|накратко|кратко", re.I)

#: A quick question about meaning, matched against the whole question once a length word is out.
_MEANING = [
    re.compile(r"^(?:and |so |ok(?:ay)?,? |sorry,? )?(?:what|who)\s*(?:is|'s|’s|are|was|were)\s+"
               r"(?:a |an |the )?[^?]{1,60}\??$", re.I),
    re.compile(r"^(?:and |so |ok(?:ay)?,? )?what (?:exactly )?(?:is|are) (?:meant by )?[^?]{1,60}\??$", re.I),
    re.compile(r"^(?:and |so )?what does (?:this|that|it|the [^?]{1,40}|[^?]{1,40}) (?:mean|stand for|"
               r"refer to)(?: here| exactly)?\??$", re.I),
    re.compile(r"^(?:and |so )?what do (?:you|they|we) mean(?: by [^?]{1,60})?(?: here| exactly)?\??$", re.I),
    re.compile(r"^(?:and |so )?when you say [^?]{1,50}, what do you mean(?: exactly)?\??$", re.I),
    re.compile(r"^(?:i )?(?:don'?t|do not|didn'?t|did not) (?:get|understand) (?:it|this|that)\.?$", re.I),
    re.compile(r"^(?:какво (?:е|са|значи|означава)|кой е|коя е|що е)\s+[^?]{1,60}\??$", re.I),
]
#: "Explain this", "explain this problem", "explain what that is", "обясни".
_EXPLAIN = re.compile(r"^(?:please )?(?:explain|обясни)(?: (?:this|that|it|to me|me|here|please|"
                      r"what (?:this|that|it) (?:is|means)|what that is|what this is)){0,3}"
                      r"(?: [a-z]+)?\.?$|^(?:please )?(?:explain|обясни)\s*\??$", re.I)
#: A question that wants more than a meaning, whatever its first words.
_MORE = re.compile(r"\b(?:compare|comparison|vs\.?|versus|difference between|list|steps|plan|"
                   r"pros and cons|how (?:do|would|should|can) (?:we|i|you)|why|change|rewrite|"
                   r"update|add|remove|make|fix|draft|write|calculate|how much|how many|"
                   r"examples?|in detail|detailed|full)\b", re.I)

#: He asked for more than a short answer: the turn is left exactly as it was.
_WANTS_MORE = re.compile(r"\b(?:in (?:full )?detail|detailed|in depth|in-depth|thorough(?:ly)?|"
                         r"at length|long(?:er)? (?:answer|version|explanation)|full (?:answer|"
                         r"explanation|version|picture|story)|tell me (?:more|everything)|more "
                         r"(?:detail|details|about)|expand(?: on)?|elaborate|step[- ]by[- ]step|"
                         r"everything (?:about|you know)|walk me through|deep dive|go deeper|"
                         r"don'?t (?:hold back|be brief|keep it short))\b|подробно|в детайли", re.I)
#: A list, a comparison, a plan or steps.
_LISTING = re.compile(r"\b(?:compare|comparison|vs\.?|versus|difference between|differences|list|"
                      r"steps|plan|options|pros and cons|which (?:of|one)|rank|summari[sz]e|"
                      r"summary|outline|examples?)\b|сравни|списък", re.I)
#: A change to the page, or something to be written.
_WORKING = re.compile(r"\b(?:change|rewrite|reword|update|add|remove|delete|fix|correct|draft|"
                      r"write|translate|rephrase|edit|insert|replace|move|shorten|turn (?:this|it|"
                      r"that) into)\b|напиши|поправи|промени|добави|махни|преведи", re.I)


def on(org_id=None) -> bool:
    from . import switches

    return switches.on(SWITCH, org_id or None)


def _plain(question: str) -> str:
    return " ".join(str(question or "").split())


def asked_length(question: str) -> str:
    """How long he said the answer should be, in words a model keeps to, or ""."""
    text = _plain(question)
    m = _COUNTED.search(text)
    if m:
        said = m.group("n").lower()
        n = int(said) if said.isdigit() else _NUMBERS.get(said, 1)
        unit = m.group("u").lower()
        unit = ("sentence" if unit.startswith(("sentence", "изречени")) else
                "line" if unit.startswith(("line", "ред")) else
                "paragraph" if unit.startswith("paragraph") else "word")
        return f"{n} {unit}{'' if n == 1 else 's'}"
    if _SHORT.search(text):
        return "2 sentences"
    return ""


def _without_length(text: str) -> str:
    text = _COUNTED.sub("", text)
    text = _SHORT.sub("", text)
    return re.sub(r"\s+([?.!,])", r"\1", " ".join(text.split())).strip(" ,;:-")


def quick(question: str) -> str:
    """"meaning" or "explain" for a quick question about what something means, else "".
    Only a short question of one part counts: two questions, or one that asks for a
    comparison, a list, a plan, a reason or a change to the page, are not quick."""
    text = _without_length(_plain(question))
    if not text or len(text) > QUICK_MOST or text.count("?") > 1:
        return ""
    if _EXPLAIN.match(text):
        return "explain"
    if _MORE.search(text):
        return ""
    if any(p.match(text) for p in _MEANING):
        return "meaning"
    from . import plain_words

    return "meaning" if plain_words.asked_terms(text) else ""


def wants_more(question: str) -> bool:
    """He asked for more than a short answer: "in detail", "tell me more", "step by step"."""
    return bool(_WANTS_MORE.search(_plain(question)))


def shape(question: str) -> tuple[str, str]:
    """(how long he said, or "", and what kind of question it is: "meaning", "explain",
    "listing", "working", "more" when he asked for more, or "plain", the default)."""
    length = asked_length(question)
    if length:
        return length, quick(question) or "plain"
    if wants_more(question):
        return "", "more"
    kind = quick(question)
    if kind:
        return "", kind
    text = _plain(question)
    if _WORKING.search(text):
        return "", "working"
    if _LISTING.search(text):
        return "", "listing"
    return "", "plain"


_TAIL = "No closing offer or question. If more would help, leave it out; they will ask for more."


def _line(length: str, kind: str) -> str:
    if length:
        return (f"<how_to_answer>The reader asked for a short answer: {length} at most. Keep to "
                "that exactly, the answer itself first, in plain words, with no heading, list, "
                "table or closing offer. If one point would not fit, leave it out; they will ask."
                "</how_to_answer>")
    if kind in ("meaning", "explain"):
        most = "five" if kind == "explain" else "three"
        return (f"<how_to_answer>This is a quick question about what something means. Answer in "
                f"{most} short sentences at most: the meaning first, in plain words a newcomer "
                "follows, then only what it means for this page. No heading, list, table or closing "
                "offer. If there is more worth knowing, leave it out; they will ask.</how_to_answer>")
    if kind == "listing":
        return ("<how_to_answer>Answers here are short by default. Give only what the question "
                "needs: a short list or a small table is fine, each item one line, with no "
                f"preamble and no recap. {_TAIL}</how_to_answer>")
    if kind == "working":
        return ("<how_to_answer>Answers here are short by default. Do the work as asked, at the "
                "length it needs; the words around it are one or two sentences, saying what was "
                f"done, with no preamble and no recap. {_TAIL}</how_to_answer>")
    return ("<how_to_answer>Answers here are short by default. Answer in four short sentences at "
            "most, the answer itself first, in plain words, with no heading, list or table unless "
            f"the question cannot be answered without one. {_TAIL}</how_to_answer>")


def note(who, question: str) -> str:
    """The line that goes after a question's turn, or "" (off, nobody, or he asked for more).
    Never raises."""
    try:
        if who is None or not on(getattr(who, "org_id", None)):
            return ""
        length, kind = shape(question)
        if kind == "more":
            return ""
        from . import evolution

        evolution.used(SWITCH, "kept_short", who=who,
                       detail=(f"kept to {length}" if length else f"a {kind} question, kept short")
                       + f": \"{_plain(question)[:80]}\"")
        log.info("short answers: %s", length or kind)
        return _line(length, kind)
    except Exception:  # noqa: BLE001 - a line of guidance is never worth a question
        log.exception("short answers could not shape a question")
        return ""


__all__ = ["SWITCH", "TITLE", "asked_length", "note", "on", "quick", "shape", "wants_more"]
