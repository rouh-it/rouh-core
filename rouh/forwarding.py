"""A forward that is the original email, passed on as Gmail's own Forward passes it.

Petar, 27 September 2026, having asked Rouh to forward an airline's flight receipt
to a contact: "when I ask rouh to forward an email, it seems to retransform the
content ... it should forward the exact mail as if forwarded by gmail. Don't
try to recreate the design, just forward the original. html". Until then there
was no forward at all: the model read the email as text and typed a new one
with `send_mail`, so what the contact got was the model's retelling of the receipt,
flattened to plain lines, with its layout, its logo and its links gone.

So a forward is built here out of the original message's own parts and never
out of anything the model wrote about it:

- **The original's HTML goes out as it came**, byte for byte inside its body,
  with the `<style>` from its head kept and its body's own background carried
  on a wrapper. Nothing is cleaned, summarised or redrawn. Its plain text half
  goes out as the plain text half, so a reader of text sees the sender's own
  words too.
- **Its pictures go with it.** A picture drawn inside the message (`cid:`) is
  carried as a part of the new one under the same Content-ID, so the logo is
  where it was rather than a broken box.
- **Its files go with it**, as Gmail's Forward carries them.
- **What the person asked to add goes on top**, then Gmail's own
  "---------- Forwarded message ---------" header - From, Date, Subject, To and
  Cc - then the original. The header is written in the markup Gmail uses
  (`gmail_quote`, `gmail_attr`), so Gmail at the far end folds it the way it
  folds a forward of its own.

`google_api.GmailClient.forward` reads the message and sends what `build`
makes of it; `ToolRegistry._forward_mail` and the inbox card's Forward both go
through that one path.

A whole conversation goes the same way, as Gmail's Forward all sends one
(`build_thread`, 4 October 2026): every message in it, oldest first, each
under its own header and each exactly as it came (`Gmail.forward_thread`).
"""
from __future__ import annotations

import html as html_mod
import re
from dataclasses import dataclass, field
import hashlib
from email import policy as email_policy
from email.parser import BytesParser
from email.utils import getaddresses

from . import clock

#: The line Gmail writes above a forwarded message, in both halves.
RULE = "---------- Forwarded message ---------"

_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct",
           "Nov", "Dec")
_DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


@dataclass
class Original:
    """What a forward is made of, read out of the message exactly as it was sent."""

    headers: dict
    at: float
    text: str
    html: str
    #: Pictures drawn inside the HTML: each part, its Content-ID, its type and
    #: its bytes. Always carried; they are part of how the message looks.
    inline: list[dict] = field(default_factory=list)
    #: The files hanging off it, each by its part number, name, type, size
    #: and bytes.
    files: list[dict] = field(default_factory=list)
    #: The message as it arrived, every byte, for when it has to go whole.
    raw: bytes = b""
    #: False when some text in it could not be read exactly as its sender
    #: wrote it - a charset nobody knows, bytes that are not what the charset
    #: says - and so it goes along as an attached message, untouched, rather
    #: than as a guess at its words (`attached_whole`).
    exact: bool = True


def read(raw: bytes, at: float = 0.0) -> Original:
    """The parts of a message a forward needs, from the message itself.

    `raw` is the message as it was sent, which is what Gmail's `format=raw`
    hands back. Not Gmail's `format=full`: that gives a part's words already
    turned into UTF-8 while still saying they are in the charset the sender
    labelled them with, so Outlook's Bulgarian, labelled koi8-r, was read as
    koi8-r a second time and "Здравей" went out as "п≈п╢я─п╟п╡п╣п╧" (a
    forward of a supplier's GDPR thread to a contact, 4 October 2026). Here every part
    is undone by its own transfer encoding and read in its own charset, once.

    Part numbers are counted as Gmail counts them ("0.1", "3"), so a file
    named by the number the inbox card listed it under is the same file here.
    """
    message = BytesParser(policy=email_policy.default).parsebytes(raw)
    headers: dict = {}
    for name, value in message.items():
        headers.setdefault(name.lower(), " ".join(str(value).split()))
    plain: list[str] = []
    markup: list[str] = []
    parts: list[dict] = []
    exact = True

    def walk(part, number: str) -> None:
        nonlocal exact
        kind = part.get_content_type()
        disposition = (part.get_content_disposition() or "").lower()
        name = part.get_filename() or ""
        if kind == "message/rfc822" or not part.is_multipart():
            if kind in ("text/plain", "text/html") and not name and disposition != "attachment":
                words, sure = _words(part)
                exact = exact and sure
                (plain if kind == "text/plain" else markup).append(words)
                return
            cid = str(part.get("content-id") or "").strip().strip("<>")
            if name or cid or kind == "message/rfc822":
                data = _bytes_of(part)
                if kind == "message/rfc822" and not name:
                    inner = part.get_payload(0) if part.is_multipart() else None
                    name = f"{(inner or {}).get('subject') or 'message'}.eml"
                parts.append({"part": number, "name": name, "type": kind, "cid": cid,
                              "size": len(data), "data": data})
            return
        for index, child in enumerate(part.iter_parts()):
            walk(child, f"{number}.{index}" if number else str(index))

    walk(message, "")
    html = _CHARSET_META.sub("", "\n".join(markup).strip())
    drawn = {c.lower() for c in re.findall(r"""cid:([^"'\s)>]+)""", html, re.I)}
    inline = [p for p in parts if p["cid"] and p["cid"].lower() in drawn]
    pictured = {_mark(p) for p in inline}
    # A picture the message draws goes once, as a picture: Outlook also hangs
    # the same image off the message as a file, and that copy stays behind.
    files = [p for p in parts if p not in inline and p["name"] and _mark(p) not in pictured]
    return Original(headers=headers, at=at, text="\n".join(plain).strip(), html=html,
                    inline=inline, files=files, raw=raw, exact=exact)


def attached_whole(original: Original) -> dict:
    """The message itself as a file, message/rfc822, for one that cannot go inline exactly."""
    subject = re.sub(r'[\\/:*?"<>|\r\n]+', " ", original.headers.get("subject", "")).strip()
    return {"name": f"{subject or 'message'}.eml", "type": "message/rfc822",
            "data": original.raw}


def gmail_date(at: float, fallback: str = "") -> str:
    """When it was sent, as Gmail's forward header says it: "Fri, Sep 25, 2026 at 3:05 PM"."""
    moment = clock.moment(at) if at else None
    if moment is None:
        return fallback
    hour = moment.hour % 12 or 12
    half = "AM" if moment.hour < 12 else "PM"
    return (f"{_DAYS[moment.weekday()]}, {_MONTHS[moment.month - 1]} {moment.day}, "
            f"{moment.year} at {hour}:{moment.minute:02d} {half}")


def header_lines(original: Original) -> list[tuple[str, str]]:
    """The forwarded message's own header, as Gmail lists it: From, Date, Subject, To, Cc."""
    named = original.headers
    lines = [("From", named.get("from", "")),
             ("Date", gmail_date(original.at, named.get("date", ""))),
             ("Subject", named.get("subject", "")),
             ("To", named.get("to", ""))]
    if named.get("cc"):
        lines.append(("Cc", named["cc"]))
    return lines


def build(original: Original, note_text: str, note_html: str) -> tuple[str, str]:
    """The forward's two halves, text and HTML: the note, the header, the original.

    The original's markup is put in exactly as it came. Only what cannot live
    inside another message's body is moved: the `<style>` blocks of its head go
    into the new head, and its `<body>`'s own look goes onto a wrapper round
    it, so a coloured background stays coloured.
    """
    return build_thread([original], note_text, note_html)


def build_thread(originals: list[Original], note_text: str,
                 note_html: str) -> tuple[str, str]:
    """A forward of a whole conversation, as Gmail's own Forward all writes one.

    The note on top, then every message in the order it was sent, each under
    its own "Forwarded message" header with its own From, Date, Subject, To
    and Cc, and each exactly as it came (`build` is this with one message).
    A message's `cid:` pictures are named apart from another's by the caller
    before they get here (`google_api.Gmail.forward_thread`), so two messages
    that both draw a logo called image001 each keep their own.
    """
    texts, styles, markups = [], [], []
    for original in originals:
        lines = header_lines(original)
        if not original.exact:
            # Its words could not be read for certain, so they are not
            # written out again at all: the message itself is attached, as
            # it came (`attached_whole`), and this says where it is.
            said = f"The message is attached as it came: {attached_whole(original)['name']}"
            original = Original(headers=original.headers, at=original.at, text=said, html="")
        body_text = original.text or _text_of(original.html)
        texts.append("\n".join([RULE] + [f"{name}: {value}" for name, value in lines]
                               + ["", "", body_text]))
        attr = "".join(f"{name}: {_header_markup(name, value)}<br>" for name, value in lines)
        head_styles, inner, look = _split(original.html) if original.html else \
            ("", _text_markup(original.text), "")
        styles.append(head_styles)
        wrapped = f'<div style="{html_mod.escape(look)}">{inner}</div>' if look else inner
        markups.append(
            '<div class="gmail_quote gmail_quote_container">'
            f'<div dir="ltr" class="gmail_attr">{RULE}<br>{attr}</div><br><br>'
            f"{wrapped}</div>")
    text = "\n".join(
        ([note_text.rstrip(), ""] if note_text.strip() else [])
        + ["\n\n".join(texts)])
    html = (
        '<html><head><meta http-equiv="Content-Type" content="text/html; charset=utf-8">'
        f"{''.join(styles)}</head><body>"
        + (f'<div dir="ltr">{note_html}</div><br>' if note_text.strip() else "")
        + "<br><br>".join(markups) + "</body></html>")
    return text, html


def _header_markup(name: str, value: str) -> str:
    """One header's value as Gmail writes it: names in bold, addresses as links."""
    if name not in ("From", "To", "Cc"):
        return html_mod.escape(value)
    out = []
    for who, address in getaddresses([value]):
        address = address.strip()
        if not address:
            continue
        link = (f'&lt;<a href="mailto:{html_mod.escape(address)}">'
                f"{html_mod.escape(address)}</a>&gt;")
        who = who.strip().strip('"').strip()
        if name == "From" and who:
            out.append(f'<strong class="gmail_sendername" dir="auto">{html_mod.escape(who)}'
                       f'</strong> <span dir="auto">{link}</span>')
        elif who:
            out.append(f"{html_mod.escape(who)} {link}")
        else:
            out.append(link)
    return ", ".join(out) or html_mod.escape(value)


_HEAD = re.compile(r"<head\b[^>]*>(.*?)</head\s*>", re.I | re.S)
_STYLE = re.compile(r"<style\b[^>]*>.*?</style\s*>", re.I | re.S)
_BODY = re.compile(r"<body\b([^>]*)>(.*?)(?:</body\s*>|$)", re.I | re.S)
_ATTR = re.compile(r"""([\w-]+)\s*=\s*("[^"]*"|'[^']*'|[^\s>]+)""")


def _split(markup: str) -> tuple[str, str, str]:
    """A whole HTML document as its head's styles, its body's inside and its body's look."""
    head = _HEAD.search(markup)
    styles = "".join(_STYLE.findall(head.group(1))) if head else ""
    body = _BODY.search(markup)
    if body is None:
        # A fragment rather than a document: it is the body.
        inner = _HEAD.sub("", markup)
        inner = re.sub(r"</?html\b[^>]*>|<!doctype[^>]*>", "", inner, flags=re.I)
        return styles, inner, ""
    looks = []
    for name, value in _ATTR.findall(body.group(1)):
        value = html_mod.unescape(value.strip("\"'"))
        name = name.lower()
        if name == "style":
            looks.append(value.rstrip("; "))
        elif name == "bgcolor":
            looks.append(f"background-color:{value}")
        elif name == "text":
            looks.append(f"color:{value}")
    # A style inside the body, which many mailers put there, stays where it is.
    return styles, body.group(2), ";".join(x for x in looks if x)


def _text_markup(text: str) -> str:
    """A plain-text original as Gmail puts one in a forward's HTML: escaped, lines kept."""
    return '<div dir="ltr">' + html_mod.escape(text).replace("\n", "<br>") + "</div>"


def _text_of(markup: str) -> str:
    """The words of an HTML-only original, for the forward's text half."""
    text = re.sub(r"(?is)<(script|style|head)[^>]*>.*?</\1>", " ", markup)
    text = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>|</li>|</h\d>", "\n", text)
    text = html_mod.unescape(re.sub(r"<[^>]+>", "", text))
    lines = [" ".join(line.split()) for line in text.splitlines()]
    return "\n".join(line for line in lines if line).strip()


_CHARSET_META = re.compile(
    r"""<meta\b[^>]*(?:\bcharset\s*=|http-equiv\s*=\s*["']?content-type)[^>]*>""", re.I)


def _words(part) -> tuple[str, bool]:
    """A text part's words as its sender wrote them, and whether that is certain.

    Its transfer encoding undone, then read in the charset it names. One that
    names none is ASCII by the standard and UTF-8 in practice. Anything that
    will not read cleanly is read as well as it can be and said to be unsure,
    so the caller sends the whole message along untouched instead.
    """
    words, sure = _decoded(part)
    # Line ends as Python writes them: the forward is written out again with
    # its own, and a CRLF kept inside the words would become a blank line.
    return re.sub(r"\r\n?", "\n", words), sure


def _decoded(part) -> tuple[str, bool]:
    data = part.get_payload(decode=True) or b""
    named = (part.get_content_charset() or "").strip()
    try:
        return data.decode(named or "utf-8"), True
    except LookupError:
        # A charset Python does not know: only plain ASCII reads the same in
        # every one of them.
        if data.isascii():
            return data.decode("ascii"), True
    except UnicodeDecodeError:
        pass
    try:
        return data.decode(named or "utf-8", "replace"), False
    except LookupError:
        return data.decode("utf-8", "replace"), False


def _bytes_of(part) -> bytes:
    """A file's own bytes, its transfer encoding undone; an attached message whole."""
    if part.get_content_type() == "message/rfc822":
        inner = part.get_payload(0) if part.is_multipart() else None
        if inner is not None:
            return inner.as_bytes(policy=email_policy.compat32)
        payload = part.get_payload(decode=True)
        return payload if isinstance(payload, bytes) else b""
    return part.get_payload(decode=True) or b""


def _mark(part: dict) -> str:
    return hashlib.sha256(part.get("data") or b"").hexdigest()


__all__ = ["Original", "RULE", "attached_whole", "build", "build_thread", "gmail_date", "header_lines", "read"]
