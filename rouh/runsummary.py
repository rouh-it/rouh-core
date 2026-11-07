"""What a run was for, in one plain sentence, written as it starts.

Petar, 29 September 2026 (fr_0b6dec937436): "I lose a lot of time trying to
figure out what those runs were. Some of those are from a day or two. When
they are green can we show a sentence that describes what we were trying to
achieve instead of terminal lines? We can formulate this sentence in the very
beginning but show it only after it is done?"

So that is what this is, in exactly that order:

    a run is written down with its brief  ->  one sentence about what it is for
    ->  kept on the run (`run.summary`)   ->  shown once it has finished well

**Written at the start, from what was asked.** The brief is the one thing that
says what a run is for, and it is there the moment the run is. What the run
said at the end is its report, and a report says what happened, which is not
the question somebody scrolling back through a day of green runs is asking.

**Shown only once it is green.** While a run is going, its card keeps the line
it has always had, what it is doing this second. Once it has finished well -
done, or finished its turn at its prompt, the two greens - the sentence takes
that line's place (`taskCard` in `static/app.js`). A run that failed, died or
is asking keeps its own line, because that line is the thing to read then.
The last line is still one click away: the run itself, which opens on its
terminal and its transcript.

**Written once.** A run that has a sentence is never asked about again, and a
run nobody could write one for - no model, a model that is down, an answer that
is not a sentence - is asked again only after Rouh starts again, so one broken
request is never a stream of them. A run with no sentence reads the way every
run read before this: its last line.

**Every run already on the list is given one too,** oldest last, one at a time,
because the runs Petar could not read were a day or two old when he said so.
Only runs started in the last `BACKFILL_DAYS`: a run from last month has
already been read or never will be.

Which model: the one the Models page has for run summaries, either company's
(`rouh/llm.py`); the standard starts it on Cheaper, because it reads a few
paragraphs and writes a sentence, and nobody is waiting on it.
"""
from __future__ import annotations

import logging
import re

log = logging.getLogger("rouh.runsummary")

#: How long the model may take over one sentence. Nobody is waiting on it: the
#: run is already started and on the list, and its card reads perfectly well
#: without one until it comes.
TIMEOUT = 20.0

#: How much of the brief it reads. The request comes first in every brief this
#: machine writes - the Gene therapy board's, a chat's, the Start box's - and what
#: follows it is how to work, which says nothing about what the work is for.
MAX_BRIEF = 3000

#: How long a sentence may be, which is about two lines of a run's card.
MAX_SENTENCE = 220

#: How far back the runs already on the list are given a sentence of their own.
BACKFILL_DAYS = 7

SYSTEM = """You say what a piece of work is for, in one plain sentence, and nothing else.

You are given the title of a job and the brief it was handed when it started.
Answer with one sentence saying what the job is trying to achieve, so that the
person who asked for it, scrolling back through a list of finished jobs days
later, knows at once what this one was for.

The rules:
- One sentence, under 25 words, ending with a full stop.
- Say the outcome wanted, in the person's terms: "Show a plain sentence on
  finished runs saying what each was for", not "Implement a summary field".
- No file names, function names, ids, branch names or commit hashes.
- Do not start with "This job", "The job", "This run" or "The task".
- No quotation marks, no markdown, no preamble.
- Write it in the language the brief is written in."""

ASK = """The title: {title}

The brief:

{brief}

Answer with the one sentence."""

#: Openings the model is told not to use, taken off if it uses one anyway, so
#: a card does not read "This run..." forty times down a column.
_OPENINGS = re.compile(
    r"^(?:this|the)\s+(?:job|run|task|work)\s+(?:is\s+)?(?:(?:trying|meant|supposed)\s+to|"
    r"aims\s+to|will|was\s+to|is\s+to)\s+", re.I)


def ask_text(title: str, brief: str) -> str:
    """What the model is asked about one run, or "" when there is nothing to ask."""
    brief = str(brief or "").strip()
    if not brief:
        return ""
    return ASK.format(title=" ".join(str(title or "").split())[:200] or "(none)",
                      brief=brief[:MAX_BRIEF])


def tidy(raw: str) -> str:
    """The model's answer as one sentence for a card, or "" when it is not one.

    The first line only, with any quotation marks or markdown it wrapped it in
    taken off, the opening it was told not to use dropped, and a full stop put
    on. Anything longer than a card holds is cut at a word and ends with an
    ellipsis rather than mid-word.
    """
    line = next((x.strip() for x in str(raw or "").splitlines() if x.strip()), "")
    line = line.strip("*_`#>- \t").strip("\"'“”‘’").strip()
    line = _OPENINGS.sub("", line).strip()
    if len(line) < 8 or " " not in line:
        return ""
    line = line[0].upper() + line[1:]
    if len(line) > MAX_SENTENCE:
        line = line[:MAX_SENTENCE].rsplit(" ", 1)[0].rstrip(",;:-") + "…"
    elif line[-1] not in ".!?…":
        line += "."
    return line


async def write(title: str, brief: str, *, subject: str = "") -> str:
    """Ask the model the Models page has for run summaries, whichever company's it
    is (`rouh/llm.py`), for the sentence. "" when it could not be asked or did not say one.

    Never raises: a run with no sentence is a run whose card reads the way it
    always did.
    """
    from . import llm

    asked = ask_text(title, brief)
    if not asked:
        return ""
    try:
        got = await llm.ask("run_summary", system=SYSTEM, messages=asked, max_tokens=120,
                            subject=subject, timeout=TIMEOUT, read_only=True)
    except Exception as exc:                      # noqa: BLE001 - never worth an error
        log.warning("no sentence could be written for a run (%s)", exc)
        return ""
    return tidy(got.text)
