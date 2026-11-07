"""A reminder's one-line title, written by a model when it has none.

Petar, 8 October 2026 (fr_b6dabdcc28e2): "The reminders are way too long. I
need them to have a short one liner title and description for the rest ...
Keep in mind the one liner should be short but understandable. If I return in
one month and I have completely forgotten about this task the one liner should
not be cryptic, I should be able to read it and understand what it is about".

A reminder made since then usually comes with its title: Rouh writes one when
it calls `schedule`, and Luna writes one when it reads the words typed on the
Reminders page (`reminder_words`). This is for the rest: every reminder made
before that day, whose words stay as they were as its description, and any
saved with long words and no title (Luna not set up, a tool call that left it
out). Words short enough to be a title already are one, with no model
(`reminders.SHORT`).

**Never in the way.** A row with no title reads as `reminders.rough_title` of
its words until this has written one, so nothing waits on it. One at a time,
in the background, like a run's sentence (`runsummary.py`): at start for every
row that has none, and then for each one saved without one. A row the model
could not title is asked about again only after Rouh starts again.

**Which model**: the one the Models page has for Clockwork titles (`modeldefaults`
use `reminder_title`), either company's (`rouh/llm.py`); the standard starts it on
Cheaper: it reads a paragraph and writes a line, and nobody is waiting on it.
"""
from __future__ import annotations

import asyncio
import logging
import re

from . import reminders

log = logging.getLogger("rouh.reminder_titles")

#: How long the model may take over one title.
TIMEOUT = 20.0

#: How much of the words it reads.
MAX_WORDS = 4000

SYSTEM = """You give a reminder a title: one short line, and nothing else.

You are given what a person asked their assistant to remind them of, or to do
for them at a time. It will be listed under that title, with these words under
it as the description. Write the title.

The test of a good title: the person comes back a month later, has completely
forgotten about this, and reads the title alone. They must know at once what it
is about. So:
- Name the real thing: who, what, and the action. "Watch Sam Rivera's
  LinkedIn for a new role at Acme", not "LinkedIn check" or "Sam update".
- Write it as they would on their own list: "my inbox", never "your inbox".
- At most 60 characters, and never more than one line.
- No shorthand, no abbreviations they did not use, no internal names of tools,
  no links, no ids, no dates or times of day (the list shows when).
- Start with a capital letter. No full stop, no quotation marks, no markdown,
  no preamble.
- Write it in the language the words are written in."""

ASK = """{kind}

The words:

{words}

Answer with the title alone."""

KIND_SAID = {"remind": "A reminder: at its time it is handed to the assistant, which reminds them.",
             "do": "A job: at its time the assistant does this and tells them what it found."}


def ask_text(kind: str, words: str) -> str:
    """What the model is asked about one reminder, or "" when there is nothing to ask."""
    words = " ".join(str(words or "").split())
    if not words:
        return ""
    return ASK.format(kind=KIND_SAID.get(kind, KIND_SAID["remind"]), words=words[:MAX_WORDS])


def tidy(raw: str) -> str:
    """The model's answer as one title, or "" when it is not one.

    The first line, out of any quotation marks, markdown or "Title:" it was put
    in, with no full stop, cut at a word if it is longer than a title may be.
    """
    line = next((x.strip() for x in str(raw or "").splitlines() if x.strip()), "")
    quotes = "\"'“”‘’"
    line = line.strip("*_`#>- \t").strip().strip(quotes).strip()
    line = re.sub(r"^title\s*:\s*", "", line, flags=re.I)
    line = line.strip(quotes).strip().rstrip(".").strip()
    if len(line) < 3:
        return ""
    line = line[0].upper() + line[1:]
    if len(line) > reminders.MAX_TITLE:
        line = line[:reminders.MAX_TITLE - 1].rsplit(" ", 1)[0].rstrip(",;:-") + "…"
    return line


async def write(kind: str, words: str, *, who=None, org_id: str | None = None,
                subject: str = "") -> str:
    """Ask the model the Models page has for Clockwork titles, whichever company's
    it is (`rouh/llm.py`). "" when it could not be asked or did not give one. Never raises."""
    from . import llm

    asked = ask_text(kind, words)
    if not asked:
        return ""
    try:
        got = await llm.ask("reminder_title", system=SYSTEM, messages=asked, max_tokens=60,
                            who=who, org_id=org_id, subject=subject, timeout=TIMEOUT,
                            read_only=True)
    except Exception as exc:                      # noqa: BLE001 - a title is never worth an error
        log.warning("no title could be written for a reminder (%s)", exc)
        return ""
    return tidy(got.text)


class Titles:
    """Every reminder with no title given one, in the background, one at a time.

    `start` takes the running loop and the timekeeper,
    whose `tell` lets the person's open tabs draw the new title, and asks about
    every row there is with none. From then on `reminders.add` and
    `reminders.change` hand each row saved without one to `want`.
    """

    asked: set[int] = set()
    loop: asyncio.AbstractEventLoop | None = None
    keeper = None
    _one_at_a_time: asyncio.Semaphore | None = None

    @classmethod
    async def start(cls, keeper) -> None:
        cls.loop = asyncio.get_running_loop()
        cls.keeper = keeper
        cls._one_at_a_time = asyncio.Semaphore(1)
        reminders.on_untitled = cls.want
        wanting = await asyncio.to_thread(reminders.untitled)
        if wanting:
            log.info("%d reminder(s) have no title yet; writing them", len(wanting))
        for row_id in wanting:
            cls.want(row_id)

    @classmethod
    def want(cls, row_id: int) -> None:
        """Give this row a title if it has none. Returns at once, from any thread."""
        loop = cls.loop
        if not row_id or row_id in cls.asked or loop is None or loop.is_closed():
            return
        cls.asked.add(row_id)
        try:
            loop.call_soon_threadsafe(lambda: asyncio.ensure_future(cls._write(row_id)))
        except RuntimeError:                      # the loop is going away
            cls.asked.discard(row_id)

    @classmethod
    async def _write(cls, row_id: int) -> None:
        from .models import Reminder

        try:
            async with cls._one_at_a_time:
                row = await asyncio.to_thread(lambda: Reminder.objects.filter(id=row_id).first())
                if row is None or row.title or row.kind == reminders.SERVER:
                    return
                title, _what = reminders._parts("", row.what)
                if title:
                    # Short enough to be its own title: no model is asked.
                    await asyncio.to_thread(reminders.titled, row_id, title)
                    return
                keeper = cls.keeper
                who = (await asyncio.to_thread(keeper.identity_of, row.user_id)
                       if keeper is not None else None)
                if who is not None and str(getattr(who, "org_id", "")) != str(row.org_id):
                    who = None
                title = await write(row.kind, row.what, who=who, org_id=row.org_id or None,
                                    subject=str(row_id))
                if not title or not await asyncio.to_thread(reminders.titled, row_id, title):
                    return
                log.info("reminder %s is titled: %s", row_id, title)
                # Titled: should it ever be left with none again, it is asked about again.
                cls.asked.discard(row_id)
            if keeper is not None and who is not None:
                await keeper.tell(who)
        except Exception as exc:  # noqa: BLE001 - a title is never worth an error
            log.warning("reminder %s was given no title: %s", row_id, exc)
