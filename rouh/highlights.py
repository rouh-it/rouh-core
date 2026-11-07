"""Passages of a page highlighted in colour, the way Apple Books and Kindle have them.

Petar, 1 October 2026 (fr_69625bf0c1a8):

    "on my html pages, I would love to get one more feature besides comments
    and ask ai - highlighter. I would love to turn on maker and be able to
    highlight in colors like apple books or kindle."

The page draws all of it (`rouh/static/askai/highlights.js`): the marker in
the floating control beside comments and Ask AI, the five colours, the
passages painted, and the little bar over a passage that changes its colour or
takes it off. This module is what is kept and who may touch it.

Whose highlights they are
-------------------------

A highlight is made by one reader and seen by everybody on the page.
Petar, 2 October 2026 (fr_0f05e13f03a8):

    "I feel like highlighting should be visible by all users seeing that html
    document. also the name of the person that highlighted it should not
    appear unless you hover on desktop (or tap on mobile/tablet)."

It is kept under the page as its owner has it (``owner_id``, ``org_id`` and
``rel``, the three a share and a comment are kept under, so it follows the
page when its folder moves) and under the reader who made it (``user_id``).
Every reader of the page is sent every highlight on it, each with the name of
whoever made it and whether that was them (`listing`); the page keeps the name
out of sight until a mouse rests on the passage or a finger taps it. Only the
one who made a highlight may change its colour or take it off, so every
change names all four.

Who may highlight, and so who sees them, is everybody who can open the page
as themselves, the same people who may comment (`rouh/comments.py`): its
owner on Rouh's canvas, and every person it is shared with by email. A
visitor to a public link is nobody, with nowhere to keep what they marked and
no business with anybody's name, so a link has no marker and no highlights.

Where a passage is
------------------

A passage is kept as its words, a few words either side of them, and where it
starts in the page's text (``anchor``). The page finds it again by its words,
and where the same words are on the page more than once, by the words around
them and then by where it was. A passage whose words are no longer on the
page is not drawn, and is kept, so it comes back if they do.

Two passages of one reader never overlap; two readers' passages may, and
are drawn one inside the other. Painting over part of one makes one
passage of both, in the colour just used, as Apple Books does: the page sends
which of the reader's highlights the new one takes the place of
(``replaces``), and they go in the same step as it is made.
"""
from __future__ import annotations

import logging
import math
import time

from .comments import Person, Place, Refused

log = logging.getLogger("rouh.highlights")

#: The colours there are, in the order the page offers them: Apple Books' and
#: Kindle's. The page draws each one; only its name is kept.
COLOURS = ("yellow", "green", "blue", "pink", "purple")

#: The longest passage kept, in characters. A highlight is a sentence or a
#: paragraph, and a whole page painted at once is still well under this.
TEXT_MAX = 20_000

#: The words either side of a passage, kept to tell apart the same words in
#: two places.
AROUND_MAX = 64

#: The most highlights one reader may have on one page.
HIGHLIGHTS_MAX = 1000

#: The most highlights sent for one page, everybody's together.
PAGE_MAX = 5000

#: The largest id taken from a page. One past what the column holds is "no
#: such highlight", not a database error.
_ID_MAX = 2 ** 63 - 1


def _on_page(place: Place):
    """Every reader's highlights on this page."""
    from .models import PageHighlight

    return PageHighlight.objects.filter(owner_id=place.owner_id, org_id=place.org_id,
                                        rel=place.rel)


def _scoped(place: Place, me: Person):
    """This reader's own highlights on this page: the only ones they may change."""
    return _on_page(place).filter(user_id=me.user_id)


def _id(raw) -> int:
    try:
        wanted = int(raw)
    except (TypeError, ValueError):
        raise Refused("There is no such highlight.", 404) from None
    if not 0 < wanted <= _ID_MAX:
        raise Refused("There is no such highlight.", 404)
    return wanted


def clean_colour(raw) -> str:
    colour = str(raw or "").strip().lower()
    if colour not in COLOURS:
        raise Refused("That is not one of the highlighter's colours.")
    return colour


def clean_anchor(raw) -> dict:
    """A passage as the page described it, kept to what the page reads back."""
    if not isinstance(raw, dict):
        raise Refused("There is no passage to highlight.")
    text = " ".join(str(raw.get("text") or "").split())
    if not text:
        raise Refused("There is no passage to highlight.")
    if len(text) > TEXT_MAX:
        raise Refused(f"That passage is longer than {TEXT_MAX} characters.")
    try:
        start = float(raw.get("start") or 0)
    except (TypeError, ValueError):
        start = 0.0
    if math.isnan(start) or math.isinf(start):
        start = 0.0
    return {
        "text": text,
        "prefix": str(raw.get("prefix") or "")[-AROUND_MAX:],
        "suffix": str(raw.get("suffix") or "")[:AROUND_MAX],
        "start": int(min(max(start, 0), 100_000_000)),
    }


def _names(user_ids) -> dict[str, str]:
    """What each of these readers is called, as their account has it now."""
    from django.contrib.auth import get_user_model

    from .comments import name_of

    pks = sorted({int(u) for u in user_ids if str(u).isdigit()})
    if not pks:
        return {}
    return {str(u.pk): name_of(u) for u in get_user_model().objects.filter(pk__in=pks)}


def _shown(row, me: Person, names: dict[str, str]) -> dict:
    mine = row.user_id == me.user_id
    return {"id": int(row.id), "colour": row.colour, "anchor": row.anchor or {},
            "created_at": row.created_at, "mine": mine,
            "by": me.name if mine else names.get(row.user_id, "Somebody")}


def listing(place: Place, me: Person) -> dict:
    """Every highlight on this page, everybody's, oldest first, each with who
    made it."""
    rows = list(_on_page(place).order_by("id")[:PAGE_MAX])
    names = _names(r.user_id for r in rows if r.user_id != me.user_id)
    return {"highlights": [_shown(r, me, names) for r in rows], "colours": list(COLOURS)}


def add(place: Place, me: Person, colour, anchor, replaces=None) -> dict:
    """A passage painted, in place of the reader's own highlights it covers."""
    from django.db import transaction

    from . import pageplaces
    from .models import PageHighlight

    colour = clean_colour(colour)
    where = clean_anchor(anchor)
    gone = [_id(r) for r in (replaces if isinstance(replaces, list) else [])[:HIGHLIGHTS_MAX]]
    with transaction.atomic():
        removed = list(_scoped(place, me).filter(id__in=gone).values_list("id", flat=True))
        _scoped(place, me).filter(id__in=removed).delete()
        if _scoped(place, me).count() >= HIGHLIGHTS_MAX:
            raise Refused(f"You already have {HIGHLIGHTS_MAX} highlights on this page.")
        row = PageHighlight.objects.create(
            owner_id=place.owner_id, org_id=place.org_id, rel=place.rel, user_id=me.user_id,
            colour=colour, anchor=where, created_at=time.time())
    # Which page this is, so the highlight follows it when its folder moves.
    pageplaces.remember(place.rel)
    return {"highlight": _shown(row, me, {}), "removed": [int(r) for r in removed]}


def recolour(place: Place, me: Person, highlight_id, colour) -> dict:
    """One of the reader's highlights, in another colour."""
    colour = clean_colour(colour)
    wanted = _id(highlight_id)
    if not _scoped(place, me).filter(id=wanted).update(colour=colour):
        raise Refused("That highlight is not there any more.", 404)
    return {"highlight": _shown(_scoped(place, me).get(id=wanted), me, {})}


def remove(place: Place, me: Person, highlight_id) -> dict:
    """One of the reader's highlights taken off the page."""
    wanted = _id(highlight_id)
    _scoped(place, me).filter(id=wanted).delete()
    return {"removed": [wanted]}


def do(place: Place, me: Person, asked: dict) -> dict:
    """One thing done to the reader's highlights, as the page asked for it."""
    what = str(asked.get("do") or "")
    if what == "add":
        return add(place, me, asked.get("colour"), asked.get("anchor"), asked.get("replaces"))
    if what == "colour":
        return recolour(place, me, asked.get("id"), asked.get("colour"))
    if what == "remove":
        return remove(place, me, asked.get("id"))
    raise Refused("That is not something a highlight can have done to it.")


__all__ = ["COLOURS", "PAGE_MAX", "add", "clean_anchor", "clean_colour", "do", "listing", "recolour",
           "remove"]
