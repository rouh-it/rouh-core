"""Which agent a job is: Codex when the person asked for Codex or an OpenAI model by name.

Petar, 9 November 2026 (task 178): he asked for two jobs "with openai astra", and both
started as Claude Code, because the tools started Codex only when the person said
"Codex". Claude then ran `codex exec -m gpt-6-astra` inside the job: eight Codex sessions
that used up the ChatGPT plan's five-hour window, none of them on Metabolism, and the
Claude plan spent as well.

So a request that names Codex, an OpenAI model (Astra, Sol, Luna, Terra, or a model id
such as gpt-6-astra) or OpenAI as the model to use starts as a run of Codex on the
ChatGPT subscription, with that model, unless the agent "claude" was passed on purpose
(`starting.start`). Words count whole and in any case, so "astral" is not Astra.

The short names that are also everyday words or names of Rouh's own parts ("sol",
"luna", "terra", "codex", "openai") count only when they are said as who does the work:
"with Luna", "using Codex", "on OpenAI's Sol", "have Codex". A brief about fixing Luna's
voice, or the Codex sign-in, is not a request to be done by them. Astra and the full model
ids count wherever they are.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from .config import OPENAI_CHOICES

#: The names said as who does the work that are not a model's: Codex itself and OpenAI
#: ("" is the Codex run's own pick on the Models page).
_NOT_A_MODEL = ("codex", "openai")

#: Said anywhere, a family name counts too; the rest only as who does the work.
_ANYWHERE_FAMILIES = ("astra",)


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


def _tables() -> tuple[list[tuple[str, str]], dict[str, str]]:
    anywhere: list[tuple[str, str]] = []
    families: dict[str, str] = {}
    for model, family, label in _models():
        anywhere.append((_spelled(model), model))
        if label.lower() != family:
            anywhere.append((_spelled(label), model))
        families.setdefault(family, model)
    for family in _ANYWHERE_FAMILIES:
        if family in families:
            anywhere.append((re.escape(family), families[family]))
    as_agent = {f: m for f, m in families.items() if f not in _ANYWHERE_FAMILIES}
    as_agent.update({word: "" for word in _NOT_A_MODEL})
    return anywhere, as_agent


_ANYWHERE, _AS_THE_AGENT = _tables()

#: The words that put a name in the place of who does the work.
_LEAD = r"(?:with|using|use|via|through|on|in|by|ask|asks|have|let|get)"
#: What may sit between them: "with OpenAI Astra", "using the GPT-6 Sol", "in OpenAI's Codex".
_BETWEEN = r"(?:(?:openai(?:'s|s)?|the|gpt[-\s]?\d(?:\.\d)?|chatgpt(?:'s)?|codex)\s+){0,2}"

_PATTERNS: tuple[tuple[re.Pattern, str], ...] = tuple(
    (re.compile(rf"(?<![\w.-])(?P<word>{rx})(?![\w-])", re.IGNORECASE), model)
    for rx, model in _ANYWHERE
) + tuple(
    (re.compile(rf"(?<![\w-]){_LEAD}\s+{_BETWEEN}(?P<word>{word})(?![\w-])", re.IGNORECASE),
     model)
    for word, model in _AS_THE_AGENT.items()
)


@dataclass(frozen=True)
class Named:
    """What a request named: the word as it was written, and the model it means ("" for none)."""

    word: str
    model: str

    def line(self) -> str:
        """The sentence the job's record keeps, saying why it is Codex."""
        on = f" on {self.model}" if self.model else ""
        return (f"Started as Codex{on}, on the ChatGPT subscription, because the request "
                f"named \"{self.word}\" (rouh/codex_route.py).")


def named(text: str) -> Named | None:
    """The OpenAI model, or Codex, a request names as who does the work, or None.

    A name that says which model wins over one that only says Codex or OpenAI, and of
    those the first said wins.
    """
    found: list[tuple[int, int, Named]] = []
    for pattern, model in _PATTERNS:
        for m in pattern.finditer(str(text or "")):
            found.append((0 if model else 1, m.start("word"), Named(m.group("word"), model)))
    if not found:
        return None
    return min(found, key=lambda f: (f[0], f[1]))[2]
