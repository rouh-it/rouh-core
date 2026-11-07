"""Files as Synapse items: text, Markdown, PDF and email, with their raw text unchanged.

The lab's Add > Upload files reads files with this, and so does the Gmail sync
(`gmailsync.py`), so an email is read one way whichever road it came by. It was
`rouh/web/synapse._parse_file` until 5 October 2026, when the Gmail sync needed
it outside the web layer; nothing in what it reads changed.

An email comes first, then each file it brought (`mailfiles.files_of`), which
must be stored after it so its `attached` link finds the email. An email's key
is its Message-ID unless the caller gives one (`mail_key`): the Gmail sync keys
every email by its inbox and Gmail's own id, `gmail:<inbox>:<id>`, so the same
email in two inboxes, or a Message-ID two senders reused, is never one item.
"""
from __future__ import annotations

import email
import email.policy
import email.utils
import hashlib
import io
import re

_MSG_ID = re.compile(r"<[^<>\s]+>")


def thread_of(msg) -> str:
    """An email's thread, from its headers alone: the first Message-ID in References, else
    In-Reply-To, else its own Message-ID, as one lower-case <id@host>. Nothing is guessed."""
    for header in ("references", "in-reply-to", "message-id"):
        value = str(msg.get(header) or "")
        found = _MSG_ID.findall(value) or value.split()
        token = found[0].strip("<>").strip() if found else ""
        if token:
            return f"<{token.lower()}>"
    return ""


def is_email(name: str, data: bytes) -> bool:
    lower = (name or "").lower()
    return lower.endswith((".eml", ".msg")) or data[:200].lower().find(b"\nsubject:") >= 0 \
        or data[:8].lower().startswith(b"from:")


def parse_file(name: str, data: bytes, *, mail_key: str = "", source: str = "upload") -> list[dict]:
    """Text, Markdown, PDF and email files, as items with their raw text unchanged.

    An email comes first, then each file it brought, which must be stored after it so its
    `attached` link finds the email. `mail_key` keys an email (and its files' `attached_to`)
    by something other than its Message-ID; `source` is the items' source."""
    lower = (name or "").lower()
    # The file's hash, so the same file uploaded and arriving on an email is known as one file
    # (card 1125, change 2: link candidates look it up).
    digest = hashlib.sha256(data).hexdigest()
    if lower.endswith(".pdf"):
        try:
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(data))
            text = "\n\n".join((page.extract_text() or "") for page in reader.pages)
        except Exception as exc:  # noqa: BLE001
            text = f"(The PDF could not be read: {exc})"
        return [{"kind": "doc", "title": name, "text": text, "file_name": name, "source": source,
                 "source_key": f"file:{name}", "sha256": digest}]
    if is_email(name, data):
        msg = email.message_from_bytes(data, policy=email.policy.default)
        body = msg.get_body(preferencelist=("plain", "html"))
        text = body.get_content() if body is not None else ""
        if body is not None and body.get_content_type() == "text/html":
            text = re.sub(r"<[^>]+>", " ", text)
        when = msg.get("date")
        try:
            said = email.utils.parsedate_to_datetime(when).isoformat() if when else None
        except Exception:  # noqa: BLE001
            said = None
        headers = {}
        if msg.get("list-unsubscribe"):
            headers["list_unsubscribe"] = str(msg.get("list-unsubscribe"))
        if msg.get("precedence"):
            headers["precedence"] = str(msg.get("precedence")).lower()
        out = {"kind": "mail", "title": str(msg.get("subject") or name), "text": text, "from": str(msg.get("from") or ""),
               "to": [a.strip() for a in str(msg.get("to") or "").split(",") if a.strip()],
               "cc": [a.strip() for a in str(msg.get("cc") or "").split(",") if a.strip()],
               "said_at": said, "source": source,
               "source_key": mail_key or str(msg.get("message-id") or f"file:{name}"),
               "file_name": name}
        if headers:
            out["headers"] = headers
        if msg.get("in-reply-to"):
            out["reply_to"] = str(msg.get("in-reply-to"))
        thread = thread_of(msg)
        if thread:
            out["thread"] = thread
        # The email's files follow it as items of their own, each linked to it (`mailfiles`).
        from . import mailfiles
        files, skipped = mailfiles.files_of(msg, mail_key=out["source_key"], said_at=said, source=out["source"])
        if skipped:
            out["skipped_files"] = skipped
        return [out, *files]
    text = data.decode("utf-8", errors="replace")
    return [{"kind": "doc" if lower.endswith((".md", ".markdown")) else "note", "title": name, "text": text,
             "file_name": name, "source": source, "source_key": f"file:{name}", "sha256": digest}]


__all__ = ["is_email", "parse_file", "thread_of"]
