"""The signature put under what the person wrote, in both halves of an email.

`with_signature` is what `Gmail` calls as it sends or drafts, and
`signature_text` reads a signature's markup as text. The signature itself is
kept in Settings (`rouh/signatures.py`).
"""
from __future__ import annotations

import html as html_module
import re


#: Where what the person wrote ends and what they are answering or passing on
#: begins, in the markup: Gmail's own quote, or the forwarded message's header.
_QUOTE_MARKUP = re.compile(r'<div\b[^>]*class="[^"]*gmail_quote|-{5,} ?Forwarded message', re.I)
_BLOCKQUOTE = re.compile(r"<blockquote\b", re.I)
_BLOCK_OPEN = re.compile(r"<(?:p|div)\b", re.I)
_WROTE = re.compile(r"\bwrote:\s*$", re.I)


def with_signature(body: str, html: str, signature: str) -> tuple[str, str, str]:
    """Both halves of an email with the signature under what the person wrote.

    `signature` is text, as it was typed in Settings (`rouh/signatures.py`).
    It goes on the very next line after the last line of the new words - the
    closing the model ends with, such as "Best," - with no blank line between
    them (Petar, 27 September 2026), and before anything quoted or forwarded:
    in the text half as it was typed, and in the HTML half after a single
    `<br>` inside the last paragraph, with a `<br>` for each line break, in
    Gmail's own `gmail_signature` class. Trailing spaces and blank lines under
    the words are trimmed first. An email with no HTML half is given one. A
    half that already ends with the signature is left as it is, so a body the
    model signed itself, or a draft sent from its card, is not signed twice.

    Returns the text, the markup, and what happened: "added", "already there",
    or "" when there is no signature to add.
    """
    said = (signature or "").strip("\n")
    if not said.strip():
        return body, html, ""
    body = body or ""
    mine, quoted = _split_text(body)
    already = _ends_with(mine, said)
    if not already:
        body = ((mine.rstrip() + "\n" if mine.strip() else "") + said
                + ("\n\n" + quoted.strip("\n") if quoted else "") + "\n")
    if not html:
        from .. import composing
        head, tail = composing.from_text(mine), composing.from_text(quoted) if quoted else ""
    else:
        cut = _quote_starts(html)
        head, tail = html[:cut], html[cut:]
    if (already and not html) or _ends_with(signature_text(head), said) or "gmail_signature\"" in head:
        return body, head + tail, "already there" if already else "added"
    if not tail:
        # A whole document ends with its body's closing tags: inside them.
        end = re.search(r"(?is)</body\s*>.*$", head)
        if end:
            head, tail = head[:end.start()], head[end.start():]
    lines = "<br>".join(html_module.escape(line) for line in said.split("\n"))
    head = _trimmed_markup(head)
    if not signature_text(head):
        return body, _SIGNATURE_BLOCK.format(lines) + tail, "added"
    # Into the last paragraph, a line under its last line: a block of its own
    # after it would sit a paragraph's gap below the closing.
    closing = re.search(r"(?:</(?:p|div|span|font|b|i|u|strong|em)>\s*)+$", head, re.I)
    at = closing.start() if closing else len(head)
    return (body, head[:at] + '<br><span class="gmail_signature" data-smartmail="gmail_signature">'
            + lines + "</span>" + head[at:] + tail, "added")


#: A signature with nothing written over it: a block of its own.
_SIGNATURE_BLOCK = ('<div dir="ltr" class="gmail_signature" '
                    'data-smartmail="gmail_signature">{}</div>')

#: What a note's markup may end with that shows as nothing: spaces, line
#: breaks, and empty paragraphs, such as the line the inbox card writes on.
_EMPTY_END = re.compile(
    r"(?:\s|&nbsp;|<br\s*/?>|<(p|div)\b[^>]*>(?:\s|&nbsp;|<br\s*/?>)*</\1>)+$", re.I)
_TRAILING_BREAKS = re.compile(
    r"(?:\s|&nbsp;|<br\s*/?>)+((?:</(?:p|div|span|font|b|i|u|strong|em)>\s*)*)$", re.I)


def _trimmed_markup(markup: str) -> str:
    """A note's markup without the blank lines and spaces it ends with."""
    while True:
        trimmed = _TRAILING_BREAKS.sub(r"\1", _EMPTY_END.sub("", markup))
        if trimmed == markup:
            return trimmed
        markup = trimmed


def signature_text(markup: str) -> str:
    """A signature's markup as the text half of an email writes it: its lines, no tags."""
    # As a browser lays it out: a line break is a new line, and a block - a
    # div, which is what Gmail writes a signature's lines as - starts and ends
    # on a line of its own, so <div><br></div> is the empty line it looks like.
    markup = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", "", markup or "")
    out = ""
    for piece in re.split(r"(<[^>]*>)", markup):
        if re.match(r"(?i)<br\b", piece):
            out += "\n"
        elif re.match(r"(?i)</?(?:div|p|tr|li|ul|ol|table|blockquote|h[1-6])\b", piece):
            out += "" if not out or out.endswith("\n") else "\n"
        elif not piece.startswith("<"):
            out += html_module.unescape(re.sub(r"\s+", " ", piece)).replace("\xa0", " ")
    lines = [line.strip() for line in out.splitlines()]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def _ends_with(text: str, signature: str) -> bool:
    """Whether words end with the signature, whatever the spacing between them."""
    def flat(words: str) -> str:
        return " ".join(words.replace("\xa0", " ").split())
    return bool(flat(signature)) and flat(text).endswith(flat(signature))


def _split_text(body: str) -> tuple[str, str]:
    """A text body as what the person wrote and what it quotes or forwards under it.

    The quote starts at the forwarded message's header, or at the "On ...
    wrote:" line over `> ` lines, which Gmail folds onto two lines when it is
    long, or at the first `> ` line of the quote the body ends with.
    """
    lines = body.split("\n")
    for i, line in enumerate(lines):
        if re.match(r"\s*-{5,} ?Forwarded message", line):
            return "\n".join(lines[:i]), "\n".join(lines[i:])
        if _WROTE.search(line):
            after = next((one for one in lines[i + 1:] if one.strip()), "")
            if after.startswith(">"):
                start = i - 1 if line.strip().lower() == "wrote:" and i else i
                return "\n".join(lines[:start]), "\n".join(lines[start:])
    end = len(lines)
    while end and not lines[end - 1].strip():
        end -= 1
    start = end
    while start and (lines[start - 1].startswith(">") or not lines[start - 1].strip()):
        start -= 1
    while start < end and not lines[start].startswith(">"):
        start += 1
    if start < end:
        return "\n".join(lines[:start]), "\n".join(lines[start:])
    return body, ""


def _quote_starts(markup: str) -> int:
    """Where the quoted or forwarded part of an email's markup starts; its end if none.

    Gmail's own quote, the forwarded message's header, or a blockquote under
    an "On ... wrote:" line - which is how the inbox card writes a reply. A
    blockquote with no such line over it is left alone: it is something the
    person is quoting inside what they wrote.
    """
    found = _QUOTE_MARKUP.search(markup)
    cut = len(markup)
    if found:
        cut = found.start()
        if not markup[cut:].lower().startswith("<div"):
            opened = list(_BLOCK_OPEN.finditer(markup, 0, cut))
            cut = opened[-1].start() if opened else cut
    for quote in _BLOCKQUOTE.finditer(markup, 0, cut):
        opened = list(_BLOCK_OPEN.finditer(markup, 0, quote.start()))
        if opened and _WROTE.search(signature_text(markup[opened[-1].start():quote.start()])):
            return opened[-1].start()
    return cut


