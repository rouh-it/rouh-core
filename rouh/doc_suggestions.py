"""Suggested edits read as suggestions: a Google Doc's suggested edits are told apart from its words.

Built by the nightly feature run, night 30, 2 November 2026 (task 94, idea I-173). A person
reviewing a Google Doc in Suggesting mode leaves suggested edits: words they would add, shown
in colour, and words they would take out, struck through, none of it in the document until
somebody accepts it. The Docs API sends both inside the document's own words, each run marked
only by `suggestedInsertionIds` or `suggestedDeletionIds`, and `read_doc` read every run the
same: a suggested insertion read as if it were already in, and the words a suggestion would
delete as if nobody had touched them, side by side ("the price is €49 €39 a seat"). Rouh then
quoted the document wrongly, could not say what a reviewer had suggested, and a job asked to
"apply Nikola's suggestions" (task 148, 28 October 2026) had to be told what they were.

So, while its switch is on, `read_doc` on a Google Doc (to a chat, a job and Ask AI alike):

- marks each suggested edit where it stands, `[suggested insertion: «€39»]` and
  `[suggested deletion: «€49»]`, the rest of the words as they were;
- says on the line under the title how many there are and what the marks mean, that an
  insertion is not in the document until accepted and a deletion still is.

The Docs API has no way to accept or reject a suggestion, so this gene only reads them; Rouh
says so when asked to accept one. No extra call to Google and no model: the marks are already
in what the Docs API sends.

**Whose.** The documents the connected Google account can open (`org_id` and `user_id`);
nothing is written.

**Its switch** is `doc_suggestions` (`rouh/switches.py`): off, suggested edits read as words,
as before.
"""
from __future__ import annotations

import asyncio
import logging

log = logging.getLogger("rouh.doc_suggestions")

SWITCH = "doc_suggestions"
TITLE = ("Suggested edits read as suggestions: a Google Doc's suggested insertions and deletions "
         "are marked where they stand, not read as its words")


def on(who) -> bool:
    from . import switches

    if who is None:
        return False
    return switches.on(SWITCH, getattr(who, "org_id", None) or None)


async def wanted(google) -> bool:
    """Whether read_doc should mark suggested edits for this person now."""
    who = google.person() if hasattr(google, "person") else None
    if who is None:
        return False
    return await asyncio.to_thread(on, who)


def line(found: dict) -> str:
    """The line under the title, or "" when the document has no suggested edits marked."""
    got = found.get("suggestions") or {}
    added, taken = int(got.get("insertions") or 0), int(got.get("deletions") or 0)
    if not added and not taken:
        return ""
    parts = []
    if added:
        parts.append(f"{added} suggested insertion{'s' if added != 1 else ''}")
    if taken:
        parts.append(f"{taken} suggested deletion{'s' if taken != 1 else ''}")
    return ("Suggested edits nobody has accepted or rejected yet: " + " and ".join(parts)
            + ", marked where they stand. A [suggested insertion: «...»] is not in the document "
              "until somebody accepts it; a [suggested deletion: «...»] is still in it until then. "
              "Rouh can read suggestions but cannot accept or reject them: that is done in Google "
              "Docs.")


async def noted(google, found: dict) -> str:
    """The line for read_doc, with the use reported when there is one."""
    said = line(found)
    if not said:
        return ""
    who = google.person() if hasattr(google, "person") else None
    if who is not None:
        from . import evolution

        got = found.get("suggestions") or {}
        await asyncio.to_thread(
            evolution.used, SWITCH, "read", who=who,
            detail=(f"{found.get('title') or 'a document'}: {got.get('insertions', 0)} insertions, "
                    f"{got.get('deletions', 0)} deletions suggested"))
    return said


__all__ = ["SWITCH", "TITLE", "line", "noted", "on", "wanted"]
