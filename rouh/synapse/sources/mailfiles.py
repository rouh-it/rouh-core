"""The files an email brought, as Synapse items of their own, each linked to its email.

Petar, 4 October 2026: the "Rouh inbox" dataset held 104 emails and none of
their files, so a client's provisioning PDF was a subject line with
nothing behind it. An email's files are now items too: a `doc` when its words
can be read, a `file` when they cannot (a picture, a scan, an archive), so a
file is never dropped without a word. Each one carries `attached_to`, the
source keys of the emails it came on, and code links it to each of them with
an `attached` link from the file to the email (`ingest.code_links`).

The words are read by the same reader `read_mail_attachment` uses
(`mail_attachments.words_of`: PDF, Word, Excel, PowerPoint, OpenDocument, RTF,
HTML and plain text). Synapse cannot see pictures, so a picture is stored with
its name, kind and size, and says so.

The same file is one item: its source key is the hash of its bytes, so when it
comes on several emails it is stored once and linked to each
(`ingest.store` sees the key again and only adds the new email).

Not every part with a file name is a file anybody sent. Skipped, and said
why (`skipped_why`): tracking pixels and tiny icons, and a picture the email's
own body shows in its signature or in the quoted mail below it, such as a
company logo under every message.
"""
from __future__ import annotations

import hashlib
import re
from email.message import EmailMessage

#: A picture this small is a tracking pixel or an icon, never a file somebody meant to send.
TINY_PICTURE = 2048

#: A picture the body shows after this share of its words sits in the signature or the quoted mail.
SIGNATURE_FROM = 0.6


def _visible(html: str) -> str:
    html = re.sub(r"(?is)<(style|script)\b.*?</\1>", " ", html or "")
    return " ".join(re.sub(r"<[^>]+>", " ", html).split())


def skipped_why(part: EmailMessage, data: bytes, html: str) -> str:
    """Why this part is not a file anybody sent, or "" when it is one."""
    media = part.get_content_type()
    if not media.startswith("image/"):
        return ""
    if len(data) < TINY_PICTURE:
        return f"a picture of {len(data)} bytes, a tracking pixel or an icon"
    cid = str(part.get("content-id") or "").strip().strip("<>").strip()
    at = (html or "").find("cid:" + cid) if cid else -1
    if at < 0:
        return ""
    before, whole = len(_visible(html[:at])), len(_visible(html))
    if whole and before / whole >= SIGNATURE_FROM:
        return "a picture shown inside the email's signature or the quoted mail below it"
    return ""


def unread_text(name: str, media: str, size: int, why: str, subject: str, sender: str) -> str:
    """What a file whose words were not read says, so it is still found by its name and email."""
    from rouh import mail_attachments

    kind = mail_attachments.kind_said(media, name)
    came = f' attached to the email "{subject}"' + (f" from {sender}" if sender else "")
    return f"{name}: {kind}, {mail_attachments.size_said(size)},{came}. Its contents were not read: {why}"


def files_of(msg: EmailMessage, *, mail_key: str, said_at: str | None, source: str) -> tuple[list[dict], list[dict]]:
    """(one payload for `ingest.store` per file the email brought, the parts skipped and why).

    A part is a file when it has a file name, as Gmail counts them (`google_api._attachments`).
    """
    from rouh import mail_attachments

    body = msg.get_body(preferencelist=("html",))
    try:
        html = body.get_content() if body is not None else ""
    except Exception:  # noqa: BLE001 - a body that will not decode just shows no pictures
        html = ""
    subject = " ".join(str(msg.get("subject") or "").split())
    sender = str(msg.get("from") or "")
    files, skipped, seen = [], [], set()
    for part in msg.walk():
        if part.is_multipart() or not part.get_filename():
            continue
        name = " ".join(str(part.get_filename()).split()) or "attachment"
        media = part.get_content_type()
        try:
            data = part.get_payload(decode=True) or b""
        except Exception:  # noqa: BLE001
            data = b""
        digest = hashlib.sha256(data).hexdigest()
        why = skipped_why(part, data, html)
        if why:
            skipped.append({"name": name, "type": media, "size": len(data), "sha256": digest, "why": why})
            continue
        if digest in seen:
            continue  # the same file twice on one email is one file
        seen.add(digest)
        words = mail_attachments.words_of({"name": name, "type": media, "data": data})
        if words and words.strip():
            text, kind, read = words, "doc", "read"
        else:
            if words is not None:
                why = "there are no words in it: it is most likely a scan or made only of pictures"
            elif media.startswith("image/"):
                why = "it is a picture, and Synapse reads only the words in documents"
            elif not mail_attachments.readable({"name": name, "type": media}):
                why = f"nothing here reads a {mail_attachments.kind_said(media, name)}"
            else:
                why = "reading it failed: it may be damaged, protected with a password, or not what its name says"
            text, kind, read = unread_text(name, media, len(data), why, subject, sender), "file", why
        files.append({"kind": kind, "title": name, "text": text, "said_at": said_at, "source": source,
                      "source_key": f"sha256:{digest}", "attached_to": [mail_key], "file_name": name,
                      "file_type": media, "file_size": len(data), "sha256": digest, "file_read": read})
    return files, skipped


__all__ = ["SIGNATURE_FROM", "TINY_PICTURE", "files_of", "skipped_why", "unread_text"]
