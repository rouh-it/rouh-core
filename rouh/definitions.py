"""Passages of a page explained in place, in the light of the page around them.

Petar, 20 October 2026 (fr_a06689f582ba):

    "my html visual explainers have comments, hight and other functionality.
    when I select text, I get ASK option to start chatting with that text.
    However next to ASK option add a Define option that exlains inline in a
    tooltip this term/text with relation to the context. also keep it
    underlined for future hovers that will display tooltip"

The page draws all of it (`rouh/static/askai/definitions.js`): Define beside
Ask on the bar over a selection, the tooltip with its explanation, and the
dotted underline the passage keeps afterwards. This module is what is kept,
who may touch it, and the one question asked of a model to write it.

Whose definitions they are
--------------------------

The same people as a page's highlights (`rouh/highlights.py`), and for the
same reason: everybody who can open the page as themselves, its owner on
Rouh's canvas and every person it is shared with by email. Every reader sees
every passage defined on the page, underlined, and its explanation on hover;
a passage already explained is not explained a second time for the next
reader. Only the reader who pressed Define may have it explained again or
take it off.

What is asked
-------------

The passage, the paragraph it sits in, and the page's own words as the
reader's browser drew them, cut to `CONTEXT_MAX`, go to the model the Models
page has for ``page_define`` (`rouh/modeldefaults.py`), with the instruction
to say what the passage means *here*, in a few sentences, rather than what a
dictionary says.
"""
from __future__ import annotations

import asyncio
import logging
import time
from types import SimpleNamespace

from .comments import Person, Place, Refused
from .highlights import _names, clean_anchor

log = logging.getLogger("rouh.definitions")

#: The use on the Models page this asks through (`rouh/modeldefaults.py`).
USE = "page_define"

#: The longest passage that may be defined. A term, a phrase, a sentence or
#: two; past this it is a summary that is wanted, which is Ask's.
PASSAGE_MAX = 1200

#: The paragraph around the passage, and the page's words, as sent with it.
PARAGRAPH_MAX = 4000
CONTEXT_MAX = 60_000

#: The most definitions one page holds, everybody's together.
PAGE_MAX = 2000

#: How long an explanation may be, in tokens. A tooltip holds a few sentences.
ANSWER_TOKENS = 400

_ID_MAX = 2 ** 63 - 1

SYSTEM = """A reader selected a passage on a page and pressed Define. Explain what the passage means on this page, in the light of the page around it, in a tooltip beside it.

- Two to four short sentences, at most 80 words.
- Say what it means here: what it refers to in this document, why it matters to the point being made, and what the abbreviation stands for if it is one. Not a general dictionary meaning, unless the page uses it in exactly that sense.
- Plain, common words a school student understands. Explain any harder word you have to use.
- Begin with the explanation itself. Do not repeat the passage, do not start with "In this context", "This refers to" or "Here", and do not ask a question back.
- Plain text only: no headings, no lists, no bold, no links. Never use the em dash; use a plain dash.
- If the page does not say enough to be sure, say what it most likely means here and say that it is not certain."""


def _on_page(place: Place):
    from .models import PageDefinition

    return PageDefinition.objects.filter(owner_id=place.owner_id, org_id=place.org_id,
                                         rel=place.rel)


def _id(raw) -> int:
    try:
        wanted = int(raw)
    except (TypeError, ValueError):
        raise Refused("There is no such definition.", 404) from None
    if not 0 < wanted <= _ID_MAX:
        raise Refused("There is no such definition.", 404)
    return wanted


def _shown(row, me: Person, names: dict[str, str]) -> dict:
    mine = row.user_id == me.user_id
    return {"id": int(row.id), "anchor": row.anchor or {}, "text": row.text,
            "mine": mine, "by": me.name if mine else names.get(row.user_id, "Somebody")}


def listing(place: Place, me: Person) -> dict:
    """Every passage defined on this page, everybody's, oldest first."""
    rows = list(_on_page(place).order_by("id")[:PAGE_MAX])
    names = _names(r.user_id for r in rows if r.user_id != me.user_id)
    return {"definitions": [_shown(r, me, names) for r in rows]}


def remove(place: Place, me: Person, definition_id) -> dict:
    """One of the reader's definitions taken off the page."""
    wanted = _id(definition_id)
    _on_page(place).filter(user_id=me.user_id, id=wanted).delete()
    return {"removed": [wanted]}


def question(title: str, passage: str, paragraph: str, context: str) -> str:
    """What the model is asked: the page, then the paragraph, then the passage."""
    parts = []
    if title:
        parts.append(f"The page is called: {title}")
    if context:
        parts.append("The page's text:\n<page>\n" + context + "\n</page>")
    if paragraph and paragraph != passage:
        parts.append("The paragraph the passage is in:\n<paragraph>\n" + paragraph + "\n</paragraph>")
    parts.append("The passage to define:\n<passage>\n" + passage + "\n</passage>")
    return "\n\n".join(parts)


def _clean(text: str) -> str:
    said = " ".join(str(text or "").replace("\u2014", " - ").split())
    return said.strip().strip('"').strip()


async def explain(place: Place, me: Person, asked: dict, cfg=None) -> dict:
    """The passage asked about, explained, kept and handed back.

    A passage somebody has already had explained on this page is handed back
    as it is, unless its maker asked for it again (``id``)."""
    from . import llm, pageplaces
    from .models import PageDefinition

    again = asked.get("id")
    row = None
    if again not in (None, ""):
        wanted = _id(again)
        row = await asyncio.to_thread(
            lambda: _on_page(place).filter(user_id=me.user_id, id=wanted).first())
        if row is None:
            raise Refused("That definition is not there any more.", 404)
        where = row.anchor or {}
    else:
        where = clean_anchor(asked.get("anchor"))
        if len(where["text"]) > PASSAGE_MAX:
            raise Refused("That is too long to define. Select a word, a phrase or a sentence, "
                          "or use Ask for a longer passage.")
        same = await asyncio.to_thread(
            lambda: _on_page(place).filter(anchor__text=where["text"],
                                           anchor__start=where["start"]).order_by("id").first())
        if same is not None:
            names = {} if same.user_id == me.user_id else \
                await asyncio.to_thread(_names, [same.user_id])
            return {"definition": _shown(same, me, names)}
        if await asyncio.to_thread(lambda: _on_page(place).count()) >= PAGE_MAX:
            raise Refused(f"This page already has {PAGE_MAX} definitions.")

    passage = str(where.get("text") or "")
    paragraph = " ".join(str(asked.get("paragraph") or "").split())[:PARAGRAPH_MAX]
    context = str(asked.get("context") or "")[:CONTEXT_MAX]
    # Whose Rouh answers is the page's owner's: their Models page, their organisation's
    # keys, and the request written down under the reader who pressed Define.
    asker = SimpleNamespace(user_id=me.user_id, org_id=place.org_id)
    try:
        got = await llm.ask(USE, system=SYSTEM, max_tokens=ANSWER_TOKENS, who=asker,
                            org_id=place.org_id, cfg=cfg, subject=place.rel[:200],
                            read_only=True,
                            messages=question(place.title, passage, paragraph, context))
    except llm.Cannot as exc:
        raise Refused(f"Rouh cannot define it here: {exc}.", 503) from None
    except Exception:
        log.exception("defining a passage on %s failed", place.rel)
        raise Refused("The model could not be reached. Try again in a moment.", 502) from None
    text = _clean(got.text)
    if not text:
        raise Refused("No explanation came back. Try again.", 502)

    def keep():
        if row is not None:
            row.text, row.model = text, got.model
            row.save(update_fields=["text", "model"])
            return row
        return PageDefinition.objects.create(
            owner_id=place.owner_id, org_id=place.org_id, rel=place.rel, user_id=me.user_id,
            anchor=where, text=text, model=got.model, created_at=time.time())

    kept = await asyncio.to_thread(keep)
    # Which page this is, so the definition follows it when its folder moves.
    await asyncio.to_thread(pageplaces.remember, place.rel)
    return {"definition": _shown(kept, me, {})}


async def do(place: Place, me: Person, asked: dict, cfg=None) -> dict:
    """One thing done, as the page asked for it: ``define``, ``again`` or ``remove``."""
    what = str(asked.get("do") or "")
    if what in ("define", "again"):
        if what == "again" and asked.get("id") in (None, ""):
            raise Refused("There is no such definition.", 404)
        return await explain(place, me, asked if what == "again" else {**asked, "id": None},
                             cfg=cfg)
    if what == "remove":
        return await asyncio.to_thread(remove, place, me, asked.get("id"))
    raise Refused("That is not something a definition can have done to it.")


__all__ = ["CONTEXT_MAX", "PASSAGE_MAX", "SYSTEM", "USE", "do", "explain", "listing", "question",
           "remove"]
