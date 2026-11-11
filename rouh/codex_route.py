"""Which agent a job is: Codex when the person asked, in their own words, for Codex or an OpenAI model to do it.

Petar, 9 November 2026 (task 178): he asked for two jobs "with openai astra", and both
started as Claude Code, because the tools started Codex only when the person said
"Codex". Claude then ran `codex exec -m gpt-6-astra` inside the job: eight Codex sessions
that used up the ChatGPT plan's five-hour window, none of them on Metabolism, and the
Claude plan spent as well.

Petar, 11 November 2026: "fix it immediately". Three jobs started as Codex that he never
asked to be Codex, because the words read were the whole brief Rouh wrote, not his: "update
the docstrings in luna.py" read as "in Luna", a quoted history line "Codex run e32c0ff3
(gpt-6-luna)" read as a model asked for, and "the top GPT on Codex", a bar described, read
as "on Codex".

So two rules, and when unsure the Models page default wins:

1. Only the person's own words for this job are read (`tools._their_words`): what they
   said or typed in the turn that started it. A brief Rouh or a model wrote, a scheduled
   run, a mail case and every internal start have none, and start as their default.
2. Even in their words, a name counts only when it is said as who does the work, after a
   lead word: "do it with Codex", "use Astra", "run it on GPT-6.1 Sol", "with openai astra",
   "have Codex do it". "on" and "in" count only after a verb of doing ("run it on Sol",
   "do it in Codex"), so "the top GPT on Codex" does not. Never counted: a file name or
   path (luna.py, rouh/luna.py), text in quotes or backticks, a name with no lead word
   (a run id, a history line, "Luna's voice", "fix the Codex sign-in"), a name followed by
   what it is the subject of ("with the Codex sign-in", "Luna's"), and a lead that is
   negated ("not with Codex", "don't use Astra").

An agent or model passed to the tool on purpose wins over all of this (`starting.route_to_codex`).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .config import OPENAI_CHOICES

#: The names said as who does the work that are not a model's: Codex itself and OpenAI
#: ("" is the Codex run's own pick on the Models page).
_NOT_A_MODEL = ("codex", "openai")


def _models() -> list[tuple[str, str, str]]:
    """Each OpenAI model on the Models page's list, as (id, family word, label).

    Read from `config.OPENAI_CHOICES`, the one place a model id is written: the family is
    the last word of its label ("GPT-6 Astra" is astra, "Luna" is luna). The list is newest
    first, so a family said alone means its newest model ("Sol" is GPT-6.1 Sol).
    """
    out = []
    for model, label in OPENAI_CHOICES:
        family = str(label).split()[-1].lower() if label else ""
        if family.isalpha() and family not in ("mini", "nano"):
            out.append((model, family, str(label)))
    return out


def _spelled(text: str) -> str:
    """A model id or label as a pattern: a dash, a space or nothing between its parts."""
    parts = [re.escape(p) for p in re.split(r"[-\s]+", text.strip()) if p]
    return r"[-\s]?".join(parts)


def _names() -> list[tuple[str, str]]:
    """Every way of naming who does the work, as (pattern, model), longest first."""
    names: list[tuple[str, str]] = []
    families: dict[str, str] = {}
    for model, family, label in _models():
        names.append((_spelled(model), model))
        if label.lower() != family:
            names.append((_spelled(label), model))
        families.setdefault(family, model)
    names += [(re.escape(f), m) for f, m in families.items()]
    # "Codex" or "OpenAI" just before a model's name only says whose it is: "with OpenAI Astra".
    models = "|".join(rx for rx, _ in names)
    names += [(rf"{re.escape(w)}(?!(?:'s|s)?\s+(?:the\s+)?(?:{models})(?![\w-]))", "")
              for w in _NOT_A_MODEL]
    return sorted(names, key=lambda n: -len(n[0]))


_NAMES = _names()

#: Lead words that put a name in the place of who does the work, anywhere.
_LEAD = r"(?:with|using|use|via|through|by|ask|have|let|get|switch\s+to|hand\s+it\s+to|give\s+it\s+to)"
#: "on" and "in" only after a verb of doing, at most three words before: "run it on Sol".
_DO = (r"(?:do|run|start|redo|rerun|build|make|put|try|launch|fix|write|implement|work|"
       r"it|this|that|them|job|jobs|task|run)")
_ON = rf"(?:\b{_DO}\b(?:\s+[\w'-]+){{0,3}}?\s+(?:on|in))"
#: What may sit between them: "with OpenAI Astra", "using the GPT-6 Sol", "in OpenAI's Codex".
_BETWEEN = r"(?:(?:openai(?:'s|s)?|the|gpt[-\s]?\d(?:\.\d)?|chatgpt(?:'s)?|codex|model)\s+){0,2}?"
#: After the name: not part of a longer word, a file name or a path, and not a possessive.
_AFTER = r"(?![\w-])(?![./\\]\w)(?!['’]s\b)"
#: Nor followed by what the name is the subject of: "with the Codex sign-in".
_SUBJECT = (r"(?!\s+(?:sign[-\s]?in|login|log[-\s]?in|auth\w*|session|sessions|run|runs|usage|"
            r"plan|limit|limits|window|quota|voice|tab|page|button|card|bar|account|"
            r"subscription|key|token|integration|route|routing|cli|config\w*|bug|bugs|"
            r"error|errors|code|file|files|module|docstring\w*|tests?|issue|issues|problem)\b)")
_NAME_ALT = "|".join(f"(?:{rx})" for rx, _ in _NAMES)
_PATTERN = re.compile(
    rf"(?<![\w./\\-])(?P<lead>{_LEAD}|{_ON})\s+{_BETWEEN}(?P<word>{_NAME_ALT}){_AFTER}{_SUBJECT}",
    re.IGNORECASE)
_BY_NAME = [(re.compile(rf"^(?:{rx})$", re.IGNORECASE), model) for rx, model in _NAMES]
#: A lead said as not wanted: "not with Codex", "don't use Astra", "never on Sol".
_NEGATED = re.compile(r"(?:\bnot|n't|\bnever|\bno|\bwithout|\binstead\s+of|\brather\s+than)"
                      r"(?:\s+[\w'-]+){0,2}\s*$", re.IGNORECASE)
#: Quoted text, which is somebody's words or a name, never a request: `x`, "x", “x”, ```x```.
_QUOTED = re.compile(r"```.*?```|`[^`\n]*`|\"[^\"\n]*\"|“[^”\n]*”", re.DOTALL)


@dataclass(frozen=True)
class Named:
    """What a request named: the word as it was written, and the model it means ("" for none)."""

    word: str
    model: str

    def line(self) -> str:
        """The sentence the job's record keeps, saying why it is Codex."""
        on = f" on {self.model}" if self.model else ""
        return (f"Started as Codex{on}, on the ChatGPT subscription, because the person's "
                f"own words named \"{self.word}\" as doing it (rouh/codex_route.py).")


def _model_of(word: str) -> str:
    for rx, model in _BY_NAME:
        if model and rx.match(word):
            return model
    return ""


def named(text: str) -> Named | None:
    """The OpenAI model, or Codex, the person's own words ask to do the work, or None.

    Pass only the person's own words for this job, never a brief. A name that says which
    model wins over one that only says Codex or OpenAI, and of those the first said wins.
    """
    plain = _QUOTED.sub(lambda m: " " * len(m.group(0)), str(text or ""))
    found: list[tuple[int, int, Named]] = []
    for m in _PATTERN.finditer(plain):
        if _NEGATED.search(plain[:m.start("lead")]):
            continue
        model = _model_of(m.group("word"))
        found.append((0 if model else 1, m.start("word"), Named(m.group("word"), model)))
    if not found:
        return None
    return min(found, key=lambda f: (f[0], f[1]))[2]
