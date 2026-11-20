"""One check for "the person's own words": whole words, and never after a "don't".

191-01 weak spot 11 (task 191, 20 November 2026): Rouh had three checks for whether words
quoted as the person's were really theirs, and they disagreed. Purchases took any three
characters found anywhere in what was said, so "buy it" was found inside "don't buy it" and
inside "rebuy items"; scheduled work took three words found anywhere; decisions took one.

So this is the one check every place that acts on quoted words uses (`purchases.words_refused`,
`protected.own_words`, the decisions, actions and delegate tools in `tools.py`):

- **Whole words.** The quote is found as a run of whole words in what was said, ignoring
  case, spacing and punctuation: "buy it" is in "OK, buy it." and not in "rebuy items".
- **Never after a negation.** A place it is found counts only when none of the few words just
  before it says no: "don't buy it", "do not send it", "never delete them", "не купувай".
  Nor does a quote that carries its own negation before the words that ask (`negated`), so
  "don't buy it" quoted whole is no go-ahead to buy either.
- **At least so many words**, where the caller asks for it: a lone "yes" or "Rouh" quoted
  from anything they said is no go-ahead for something scheduled.

It needs nothing but the standard library, so it is checked on its own
(`rouh/selfcheck/protections_191.py`).
"""
from __future__ import annotations

import re

#: How many words before a quote are read for a negation.
WINDOW = 3

#: Words that turn what follows into its opposite, in the languages the person writes in.
#: Only negations: "stop" and "cancel" are things a person asks for ("stop the run").
NEGATIONS = frozenset({
    "not", "no", "never", "nor", "don't", "dont", "doesn't", "doesnt", "didn't", "didnt",
    "won't", "wont", "shouldn't", "shouldnt", "mustn't", "mustnt", "can't", "cant", "cannot",
    "without", "neither",
    # Bulgarian, German, French, Spanish.
    "не", "недей", "нито", "без", "nicht", "kein", "keine", "nie", "niemals", "pas", "jamais",
    "ne", "nunca",
})

_WORD = re.compile(r"[\w']+")


def tokens(text) -> list[str]:
    """The words of a text, lower case, with punctuation and spacing gone; a curly
    apostrophe is read as a plain one."""
    return _WORD.findall(str(text or "").lower().replace("’", "'"))


def plain(text) -> str:
    return " ".join(tokens(text))


def _at(needle: list[str], hay: list[str]) -> list[int]:
    n = len(needle)
    return [i for i in range(len(hay) - n + 1) if hay[i:i + n] == needle] if n else []


def negated_before(hay: list[str], i: int, window: int = WINDOW) -> bool:
    """Whether one of the `window` words before position `i` says no."""
    return any(w in NEGATIONS for w in hay[max(0, i - window):i])


def found(words, said) -> bool:
    """Whether `words` stand in `said` as whole words, somewhere no negation comes just
    before them."""
    needle, hay = tokens(words), tokens(said)
    return any(not negated_before(hay, i) for i in _at(needle, hay))


def negated(words, pattern: re.Pattern | None = None) -> bool:
    """Whether a quote says no itself: a negation among its first words, or, with `pattern`,
    just before the first word the pattern finds in it ("don't buy it", "please do not send").
    Without a pattern, a "no" counts only as the very first word."""
    toks = tokens(words)
    if pattern is None:
        # Its first words; a "no" only as the very first, so "buy it, no rush" still asks.
        return toks[:1] == ["no"] or any(w in NEGATIONS - {"no"} for w in toks[:WINDOW])
    for i, w in enumerate(toks):
        if pattern.fullmatch(w) or pattern.search(w):
            return negated_before(toks, i)
    return False


def theirs(words, said_list, *, at_least: int = 1) -> bool:
    """Whether `words` are the person's own: at least `at_least` words, found whole in one of
    the things they said (`found`), and not a "no" themselves (`negated`)."""
    if len(tokens(words)) < at_least or negated(words):
        return False
    said_list = [said_list] if isinstance(said_list, str) else list(said_list or ())
    return any(found(words, one) for one in said_list)


__all__ = ["NEGATIONS", "WINDOW", "found", "negated", "negated_before", "plain", "theirs",
           "tokens"]
