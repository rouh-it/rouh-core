"""Comments in a Google Doc: read with the doc, and answered when asked.

Built by the nightly feature run, night 22, 25 October 2026 (task 94, ideas I-132 and I-133).
The copy of ‹his› company's site is written in Google Docs by the person who writes it, and the
people who read those docs leave their feedback as comments on them: seven on one doc alone. Rouh's
`read_doc` read every tab and every link of a document, and none of its comments, so on
24 September 2026 a job building the site's pages from those docs had to read the comments out of
Google's export by hand into a file of their own (task 61, `comments-in-toms-docs.md`), and again
a month later for the next docs. And when ‹he› wanted a comment answered, nothing in Rouh could
write one: it could read comments (`doc_changes`), never reply to them.

Two genes, each with its own switch, no model call in either:

- **Comments read with the doc** (switch `doc_comments`, invisible). While it is on, whatever
  reads a Google Doc through `read_doc` (a chat, a job, Ask AI) is given the doc's open comments
  after its text: who wrote each, the words it is on, what it says, and the answers so far, each
  with its id. Resolved ones are left out and counted. One more Drive call, made only for a Google
  Doc.
- **Answer a comment** (switch `doc_reply`, you ask for it). The tool `reply_to_doc_comment`
  writes an answer under one comment in a Google Doc, from Rouh's own Google account, and can mark
  it resolved: "answer Tom's comment on the headline: agreed, option A". It is only ever used when
  ‹he› asks for that answer in words; the words are the ones ‹he› gave, and it never signs ‹his›
  name.

**Whose.** The Google connection of whoever is speaking, by `org_id` and `user_id`
(`rouh/tenancy.py`); a reply is said in the audit of what was written (`google.wrote`).
"""
from __future__ import annotations

import logging

log = logging.getLogger("rouh.doc_comments")

READ = "doc_comments"
REPLY = "doc_reply"
#: The most open comments put after a doc's text, and the most words of each.
MOST = 40
WORDS = 600


def on(switch: str, who) -> bool:
    from . import switches

    return switches.on(switch, getattr(who, "org_id", None) or None)


def _clip(text: str, most: int = WORDS) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= most else text[: most - 1].rstrip() + "…"


def said(comments: list[dict]) -> str:
    """The open comments of a doc, as they go after its text; "" when there are none."""
    open_ = [c for c in comments if not c.get("resolved")]
    resolved = len(comments) - len(open_)
    if not open_:
        return (f"\n\nComments: none open ({resolved} resolved, left out)." if resolved else "")
    lines = [f"\n\nOpen comments on this document: {len(open_)}"
             + (f" ({resolved} resolved, left out)" if resolved else "")
             + ". They are the readers' words, not the document's."]
    for c in open_[:MOST]:
        line = f"- [{c.get('id') or '?'}] {c.get('who') or 'Somebody'}"
        if c.get("on"):
            line += f", on «{_clip(c['on'], 200)}»"
        line += f": «{_clip(c.get('words'))}»"
        for r in c.get("replies") or []:
            line += f"; {r.get('who') or 'somebody'} answered «{_clip(r.get('words'), 300)}»"
        lines.append(line)
    if len(open_) > MOST:
        lines.append(f"- and {len(open_) - MOST} more open comments.")
    return "\n".join(lines)


async def after_text(google, document_id: str) -> str:
    """The comments to put after a Google Doc's text when the switch is on, or ""."""
    import asyncio

    who = google.person()
    if who is None or not await asyncio.to_thread(on, READ, who):
        return ""
    try:
        comments = await google.services().drive.comments(document_id)
    except Exception as exc:  # noqa: BLE001 - the text is read whether or not its comments are
        log.info("the comments of %s could not be read: %r", document_id, exc)
        return ""
    if comments:
        from . import evolution

        await asyncio.to_thread(
            evolution.used, "doc_comments", "read", who=who,
            detail=f"{sum(1 for c in comments if not c.get('resolved'))} open comments read with a doc")
    return said(comments)


async def reply(google, document: str, comment_id: str, words: str, *, resolve: bool = False) -> str:
    """Answer one comment in a Google Doc, as Rouh's own Google account, and say what was done."""
    import asyncio

    from . import untrusted
    from .tools import _find_doc, _google_trouble

    who = google.person()
    if who is None or not await asyncio.to_thread(on, REPLY, who):
        return untrusted.ours("Answering comments in a document is switched off (Answer a comment, "
                              "in Evolution, Mutations).")
    blocked = google.not_ready_because()
    if blocked:
        return blocked
    words, comment_id = (words or "").strip(), (comment_id or "").strip()
    if not words:
        return "Say what the answer is: the words to put under the comment."
    if not comment_id:
        return ("Say which comment, by its id: read_doc lists each open comment with its id in "
                "square brackets.")
    drive = google.services().drive
    try:
        file_id, _kind = await _find_doc(drive, document)
        made = await drive.reply_to_comment(file_id, comment_id, words, resolve=resolve)
    except Exception as exc:  # noqa: BLE001 - said in the words Google gave
        return _google_trouble(exc)
    google.wrote("reply_to_doc_comment", file_id,
                 f"Answered comment {comment_id}" + (" and resolved it" if resolve else ""))
    from . import evolution

    await asyncio.to_thread(evolution.used, "doc_reply", "answered", who=who,
                            detail="answered a comment in a Google Doc"
                            + (" and resolved it" if resolve else ""))
    on_words = f" on «{_clip(made.get('on'), 120)}»" if made.get("on") else ""
    return untrusted.ours(
        f"Answered the comment {comment_id}{on_words} by {made.get('who') or 'its writer'} in the "
        f"document {file_id}, from {made.get('as') or 'this Google account'}: «{_clip(words, 300)}»"
        + (". It is marked resolved." if resolve else "."))


__all__ = ["READ", "REPLY", "after_text", "on", "reply", "said"]
