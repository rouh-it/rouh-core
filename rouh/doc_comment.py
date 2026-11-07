"""Leave a comment: asked to comment on a Google Doc, Rouh writes a new comment in it.

Built by the nightly feature run, night 23, 26 October 2026 (task 94, idea I-139). The copy of
‹his› company's site is written in Google Docs, and the people who read those docs give their
feedback as comments on them: twenty-five on the writer's docs by 24 September 2026, and a
colleague's on 22 October on a headline that "doesn't get across the idea". Since night 22 Rouh
reads those comments with the doc and answers one when asked (`rouh/doc_comments.py`), but it
could not start one: feedback ‹he› gave Rouh on a doc ("tell Tom the headline should be shorter")
had to be typed into the doc by ‹him›, or sent as an email beside it.

So, while its switch is on, the tool `comment_on_doc` writes a new comment in a Google Doc from
Rouh's own Google account, in the words ‹he› gave, on the passage ‹he› named: Drive's API cannot
pin a comment to a passage of a Google Doc, so the passage is quoted at the head of the comment,
and it is checked against the document's own words first, so a comment is never left on words
the document does not have. It is only ever used when ‹he› asks for a comment in words, and it
never signs ‹his› name. No model call of its own: it is a tool in the turn already being taken.

**Whose.** The Google connection of whoever is speaking (`google.person()`, by `org_id` and
`user_id`); what was written is said in the audit of what Rouh wrote in Google (`google.wrote`).
A job may ask for one only through the approval queue (`rouh/job_policy.py`, `RISKS`).

**Its switch** is `doc_comment` (`rouh/switches.py`): off, the tool says it is switched off.
"""
from __future__ import annotations

import logging

log = logging.getLogger("rouh.doc_comment")

SWITCH = "doc_comment"
#: The longest passage quoted at the head of a comment, and the longest comment.
ON_MOST = 300
WORDS_MOST = 4000

TOOL_NAME = "comment_on_doc"
DESCRIPTION = (
    "Write a new comment in a Google Doc, from your own Google account, on a passage of it. Use "
    "it only when the person asks you to comment on a document, leave feedback in it or tell its "
    "writer something there (\"comment on Tom's homepage doc that the headline is too long\"), "
    "with the words they gave or plainly asked for; never on your own, and never signed with "
    "their name. Give `on`, the words of the document the comment is about, copied exactly as "
    "read_doc gave them (a sentence or a heading is enough); they are checked against the "
    "document and quoted at the head of the comment. To answer a comment already there, use "
    "reply_to_doc_comment instead. Say back what was written and on which words.")
SCHEMA = {
    "type": "object",
    "properties": {
        "document": {"type": "string", "description": "The document id, its link, or its name in Drive."},
        "words": {"type": "string", "description": "The comment, exactly as it goes."},
        "on": {"type": "string",
               "description": "The words of the document it is about, exactly as written there. "
                              "Left out, the comment is on the whole document."},
    },
    "required": ["document", "words"],
}


def on(who) -> bool:
    from . import switches

    return switches.on(SWITCH, getattr(who, "org_id", None) or None)


def _flat(text: str) -> str:
    text = (str(text or "").replace("\u2019", "'").replace("\u2018", "'")
            .replace("\u201c", '"').replace("\u201d", '"').replace("\u2014", "-").replace("\u2013", "-"))
    return " ".join(text.split()).lower()


def found_in(text: str, passage: str) -> bool:
    """Whether the passage is in the document's words, spaces, quotes and dashes aside."""
    want = _flat(passage).strip(" .,;:")
    return bool(want) and want in _flat(text)


def written(words: str, passage: str) -> str:
    """The comment as it goes into the document: the passage it is about first, quoted."""
    words = str(words or "").strip()
    passage = " ".join(str(passage or "").split())
    if not passage:
        return words
    if len(passage) > ON_MOST:
        passage = passage[:ON_MOST - 1].rstrip() + "…"
    return f"On \u201c{passage}\u201d:\n{words}"


async def comment(google, document: str, words: str, passage: str = "") -> str:
    """Write the comment, and say what was done, or why not."""
    import asyncio

    from . import untrusted
    from .google_api import DOC_TYPE
    from .tools import _find_doc, _google_trouble

    who = google.person()
    if who is None or not await asyncio.to_thread(on, who):
        return untrusted.ours("Leaving comments in a document is switched off (Leave a comment, in "
                              "Evolution, Mutations).")
    blocked = google.not_ready_because()
    if blocked:
        return blocked
    words, passage = (words or "").strip(), (passage or "").strip()
    if not words:
        return "Say what the comment is: the words to write in the document."
    if len(words) > WORDS_MOST:
        return f"That comment is {len(words)} characters long; a comment can take {WORDS_MOST}."
    services = google.services()
    try:
        file_id, kind = await _find_doc(services.drive, document)
        if passage and kind in ("", DOC_TYPE):
            read = await services.docs.read(file_id)
            if not found_in(read.get("text") or "", passage):
                return (f"The words «{passage[:200]}» are not in that document, so no comment was "
                        "written. Read it with read_doc and give the words exactly as they are "
                        "written there.")
        made = await services.drive.add_comment(file_id, written(words, passage))
    except Exception as exc:  # noqa: BLE001 - said in the words Google gave
        return _google_trouble(exc)
    google.wrote(TOOL_NAME, file_id, "Left a comment" + (" on a passage" if passage else ""))
    from . import evolution

    await asyncio.to_thread(evolution.used, SWITCH, "commented", who=who,
                            detail="left a comment in a Google Doc")
    where = f" on «{passage[:120]}»" if passage else " on the whole document"
    return untrusted.ours(
        f"Left a comment{where} in the document {file_id}, from "
        f"{made.get('as') or 'this Google account'}: «{words[:300]}». Its id is "
        f"{made.get('id') or 'not given'}.")


__all__ = ["DESCRIPTION", "SCHEMA", "SWITCH", "TOOL_NAME", "comment", "found_in", "on", "written"]
