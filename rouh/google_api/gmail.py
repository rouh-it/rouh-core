"""Gmail: reading, searching, labelling, drafting and sending mail.

The signature put under what is written is `signature.py`.
"""
from __future__ import annotations

import asyncio
import base64
import html as html_module
import logging
import re
import urllib.parse
import uuid
from email.message import EmailMessage, MIMEPart
from typing import TYPE_CHECKING

from ..tenancy import Identity
from .common import (CannotDoThat, GoogleSaidNo, LEFT_OUT_OF_A_THREAD, MAIL_LIMIT, MAX_MESSAGES,
                     UPLOAD_SECONDS, _text_of_html)
from .signature import with_signature

if TYPE_CHECKING:
    from .clients import GoogleClients

log = logging.getLogger("rouh.google")


#: Gmail's own names for the states a person talks about, so "mark it read"
#: does not need a lookup. Anything else a person names is a label they made,
#: and `Gmail.label_ids` finds or creates it.
SYSTEM_LABELS = {
    "unread": "UNREAD", "read": "UNREAD", "starred": "STARRED", "important": "IMPORTANT",
    "inbox": "INBOX", "spam": "SPAM", "trash": "TRASH",
}


class Gmail:
    """The connected mailbox: reading it, and writing to it."""

    def __init__(self, clients: GoogleClients, who: Identity) -> None:
        self._clients = clients
        self._who = who

    def _url(self, path: str) -> str:
        return self._clients.base("gmail") + "/gmail/v1/users/me" + path

    # --- reading -------------------------------------------------------------

    async def recent(self, limit: int = 10, query: str = "", *,
                     most: int = MAX_MESSAGES) -> list[dict]:
        """The newest messages, each with who it is from, its subject and when.

        Two steps, because Gmail's list only returns ids: the list, then the
        headers of each one. The second step runs the lookups together rather
        than one after another, so ten messages cost one round trip's wait and
        not ten. `most` is the ceiling: a spoken turn's, unless the caller is
        the inbox card, which is a list read off a screen (`rouh/inbox.py`).
        """
        want = max(1, min(int(limit or 10), int(most or MAX_MESSAGES)))
        params = {"maxResults": want}
        if query:
            params["q"] = query
        listing = await self._clients.call(self._who, "GET", self._url("/messages"),
                                           params=params)
        ids = [m.get("id") for m in (listing.get("messages") or []) if m.get("id")]
        if not ids:
            return []
        headers = await asyncio.gather(
            *(self.headers(one) for one in ids), return_exceptions=True
        )
        out = []
        for one, found in zip(ids, headers):
            if isinstance(found, Exception):
                log.warning("gmail message %s could not be read: %s", one, found)
                continue
            out.append(found)
        return out

    async def headers(self, message_id: str) -> dict:
        """One message as a line of a list: who from, the subject, when, the first words."""
        body = await self._clients.call(
            self._who, "GET", self._url(f"/messages/{urllib.parse.quote(message_id)}"),
            params={"format": "metadata",
                    "metadataHeaders": ["From", "Subject", "Date"]},
        )
        named = {}
        for header in (body.get("payload") or {}).get("headers") or []:
            named[(header.get("name") or "").lower()] = header.get("value") or ""
        return {
            "id": message_id,
            "thread_id": body.get("threadId") or "",
            "from": named.get("from", ""),
            "subject": named.get("subject", "(no subject)"),
            "date": named.get("date", ""),
            "at": _arrived(body, named),
            "snippet": html_module.unescape(body.get("snippet") or ""),
            "unread": "UNREAD" in (body.get("labelIds") or []),
        }

    async def message(self, message_id: str) -> dict:
        """One whole message: its headers, its labels and its body as text.

        Plain text wins over HTML wherever Gmail sends both, because what comes
        back is read out loud or handed to the model, and neither wants markup.
        """
        body = await self._clients.call(
            self._who, "GET", self._url(f"/messages/{urllib.parse.quote(message_id)}"),
            params={"format": "full"})
        named = _named_headers(body.get("payload") or {})
        plain, html = _message_bodies(body.get("payload") or {})
        return {
            "id": body.get("id") or message_id,
            "thread_id": body.get("threadId") or "",
            "from": named.get("from", ""),
            "to": named.get("to", ""),
            "cc": named.get("cc", ""),
            "reply_to": named.get("reply-to", ""),
            "subject": named.get("subject", "(no subject)"),
            "date": named.get("date", ""),
            "at": _arrived(body, named),
            "labels": list(body.get("labelIds") or []),
            "unread": "UNREAD" in (body.get("labelIds") or []),
            "body": plain or (_text_of_html(html) if html else "") or (body.get("snippet") or ""),
            # The markup as sent, only where there is no plain text beside it:
            # the inbox card reads what was quoted out of it, which the text
            # above has already flattened away (`inbox.html_text`).
            "html": "" if plain else html,
            "attachments": _attachments(body.get("payload") or {}),
            # The calendar invitations it carries, as iCalendar text where Gmail sent it inline,
            # read by Invitations read on your clock (`rouh/mail_invites.py`).
            "calendar": _calendar_parts(body.get("payload") or {}),
            # Gmail's own check of the sender, the one it wrote on top as the
            # message arrived. The first, never the last: anybody can put a
            # header of that name further down in what they send
            # (`mail_alerts.gmail_confirmed`).
            "authentication": _first_header(body.get("payload") or {},
                                            "authentication-results"),
            # What bulk mail and machines write about themselves: a message
            # carrying any of these is junk, and never a case
            # (`mail_alerts.junk_because`).
            "list_unsubscribe": named.get("list-unsubscribe", ""),
            "list_id": named.get("list-id", ""),
            "precedence": named.get("precedence", ""),
            "auto_submitted": named.get("auto-submitted", ""),
            # A bounce names the address that failed here (Did not arrive, `rouh/not_arrived.py`),
            # and a list says whether one press unsubscribes (Unsubscribe in the inbox card,
            # `rouh/inbox_unsubscribe.py`, RFC 8058).
            "failed_recipients": named.get("x-failed-recipients", ""),
            "list_unsubscribe_post": named.get("list-unsubscribe-post", ""),
        }

    async def calendar_text(self, message_id: str, one: dict) -> str:
        """The iCalendar text of one of `message()`'s calendar parts: inline as it came, or
        fetched by its attachment id or, for a named file, its part (`rouh/mail_invites.py`)."""
        if one.get("data"):
            return str(one["data"])
        if one.get("attachment_id"):
            got = await self._clients.call(
                self._who, "GET", self._url(f"/messages/{urllib.parse.quote(message_id)}/attachments/"
                                            + urllib.parse.quote(str(one["attachment_id"]))))
            return _b64(got.get("data") or "")
        if one.get("name"):
            file = await self.attachment(message_id, str(one.get("part") or ""))
            return bytes(file.get("data") or b"").decode("utf-8", "replace")
        return ""

    async def attachment(self, message_id: str, part: str) -> dict:
        """One file hanging off a message, as bytes, found by its part.

        By the part's number and not by the attachment id Gmail hands out,
        because Gmail hands out a different attachment id for the same file
        each time the message is read: an id kept from one read is not
        promised to work on the next. So the message is read again here and
        the part looked up in it, which is also what makes sure the file
        really belongs to this message.
        """
        body = await self._clients.call(
            self._who, "GET", self._url(f"/messages/{urllib.parse.quote(message_id)}"),
            params={"format": "full"})
        found = _part_numbered(body.get("payload") or {}, str(part))
        if found is None:
            raise GoogleSaidNo(f"That message has no attachment {part}.")
        return await self._part_file(message_id, found)

    async def draft_files(self, draft_id: str) -> list[dict]:
        """The files already on a draft, as bytes, in the order they hang off it."""
        return (await self.read_draft(draft_id))["files"]

    async def read_draft(self, draft_id: str) -> dict:
        """Who a draft goes to, its subject, and the files already on it.

        Sending a draft writes it over first (`send_draft`), and a message
        written over is only what it is given. So when there is no card on the
        screen to say what a draft carries - Rouh has started again since it
        was drawn, or it was drawn in another conversation - it is read off the
        draft itself, and it goes to everybody it was written to and with the
        files it was written with, rather than quietly without them. On 29
        September 2026 a draft copied to two addresses was sent from General
        by its id with only its first recipient, and to nobody who could
        receive it.

        ``{"to", "cc", "bcc", "subject", "files", "reply_to_message_id"}``,
        each "" or [] when the draft has none. The last is the newest message
        in the draft's thread that is not the draft, which is what a reply is
        written as an answer to, so it goes out in its thread.
        """
        body = await self._clients.call(
            self._who, "GET", self._url(f"/drafts/{urllib.parse.quote(draft_id)}"),
            params={"format": "full"})
        message = body.get("message") or {}
        payload = message.get("payload") or {}
        named = _named_headers(payload)
        out = []
        for one in _attachments(payload):
            found = _part_numbered(payload, one["part"])
            if found is not None:
                out.append(await self._part_file(message.get("id") or "", found))
        answering = ""
        thread = message.get("threadId") or ""
        if thread and named.get("in-reply-to"):
            whole = await self._clients.call(
                self._who, "GET", self._url(f"/threads/{urllib.parse.quote(thread)}"),
                params={"format": "minimal"})
            answering = next((str(m.get("id") or "") for m in reversed(whole.get("messages") or [])
                              if m.get("id") != message.get("id")
                              and "DRAFT" not in (m.get("labelIds") or [])), "")
        return {"to": named.get("to", ""), "cc": named.get("cc", ""),
                "bcc": named.get("bcc", ""), "subject": named.get("subject", ""),
                "files": out, "reply_to_message_id": answering}

    async def send_draft_as_it_is(self, draft_id: str) -> dict:
        """Send a draft exactly as it is in Gmail: its words, everybody on it,
        its files and its thread, the way pressing Send on it in Gmail does.

        For "send it" about a draft that has no card here to say what it now
        reads, and no words given to write over it with: a draft written in
        another conversation, which is the one Petar answered from his phone on
        29 September 2026. Gmail takes it out of Drafts as it sends it.
        """
        draft = await self.read_draft(draft_id)
        answer = await self._clients.call(
            self._who, "POST", self._url("/drafts/send"), json_body={"id": draft_id})
        return {"to": draft["to"], "cc": draft["cc"], "bcc": draft["bcc"],
                "subject": draft["subject"],
                "thread_id": answer.get("threadId") or "",
                "replied_to": draft["reply_to_message_id"],
                "id": answer.get("id") or (answer.get("message") or {}).get("id") or "",
                "draft_id": "", "files": draft["files"]}

    async def draft_named(self, named: str) -> str:
        """The draft `named` means: itself when it is a draft's id, and the
        draft whose message it is when it is a message's.

        A search of the mailbox (`recent`, with in:drafts) hands back a
        draft's message id, which is not its draft id, and Gmail answers a
        message id sent as a draft's with "Requested entity was not found".
        `named` unchanged when no draft answers to it either way, so the
        caller is told the draft is not there.
        """
        page = ""
        for _ in range(5):
            params = {"maxResults": 500}
            if page:
                params["pageToken"] = page
            body = await self._clients.call(self._who, "GET", self._url("/drafts"),
                                            params=params)
            for one in body.get("drafts") or []:
                if named in (one.get("id"), (one.get("message") or {}).get("id")):
                    return str(one.get("id") or named)
            page = body.get("nextPageToken") or ""
            if not page:
                break
        return named

    async def drafts_like(self, query: str = "", most: int = 10) -> list[dict]:
        """The drafts Gmail's search finds, each read whole: its draft id, the message's id, who it goes
        to, its subject and its words. For Not drafted twice (`rouh/draft_twice.py`), GET only."""
        params: dict = {"maxResults": max(1, min(int(most or 10), 50))}
        if query:
            params["q"] = query
        listing = await self._clients.call(self._who, "GET", self._url("/drafts"), params=params)
        ids = [str(d.get("id")) for d in (listing.get("drafts") or []) if d.get("id")][:params["maxResults"]]

        async def one(draft_id: str) -> dict:
            body = await self._clients.call(
                self._who, "GET", self._url(f"/drafts/{urllib.parse.quote(draft_id)}"),
                params={"format": "full"})
            message = body.get("message") or {}
            payload = message.get("payload") or {}
            named = _named_headers(payload)
            plain, html = _message_bodies(payload)
            return {"draft_id": draft_id, "id": message.get("id") or "",
                    "to": named.get("to", ""), "cc": named.get("cc", ""), "bcc": named.get("bcc", ""),
                    "subject": named.get("subject", ""), "at": _arrived(message, named),
                    "body": plain or (_text_of_html(html) if html else "")}

        found = await asyncio.gather(*(one(d) for d in ids), return_exceptions=True)
        return [f for f in found if isinstance(f, dict)]

    async def _part_file(self, message_id: str, found: dict) -> dict:
        """One part of a message that is a file, as its name, its type and its bytes."""
        held = found.get("body") or {}
        data = held.get("data") or ""
        if not data and held.get("attachmentId"):
            got = await self._clients.call(
                self._who, "GET",
                self._url(f"/messages/{urllib.parse.quote(message_id)}/attachments/"
                          f"{urllib.parse.quote(held['attachmentId'])}"))
            data = got.get("data") or ""
        try:
            raw = base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))
        except Exception:
            raise GoogleSaidNo(f"{found.get('filename') or 'That file'} could not be read "
                               "from the message.") from None
        return {"name": found.get("filename") or "attachment",
                "type": found.get("mimeType") or "application/octet-stream",
                "data": raw}

    async def inbox_counts(self) -> dict:
        """How many messages the inbox holds, and how many of them are unread.

        Gmail's own count off the INBOX label, which is exact, rather than the
        estimate a search gives: "143 in the inbox" has to be a number the
        person can check against Gmail and find the same.
        """
        body = await self._clients.call(self._who, "GET", self._url("/labels/INBOX"))
        return {"total": int(body.get("messagesTotal") or 0),
                "unread": int(body.get("messagesUnread") or 0)}

    async def send_as(self) -> list[str]:
        """Every address this mailbox sends as: its own, and any alias set up in Gmail."""
        body = await self._clients.call(self._who, "GET", self._url("/settings/sendAs"))
        return [str(one.get("sendAsEmail") or "").strip().lower()
                for one in (body.get("sendAs") or []) if one.get("sendAsEmail")]

    # --- writing -------------------------------------------------------------

    async def send(self, to: str, subject: str, body: str, *, cc: str = "",
                   bcc: str = "", reply_to_message_id: str = "", html: str = "",
                   attachments: list[dict] | None = None, signed: bool = True) -> dict:
        """Send a message, or reply to one in its own thread.

        Given a message id, the reply really is a reply: it goes into that
        thread, carries `In-Reply-To` and `References` pointing at the message
        it answers, and takes that message's subject with `Re:` in front unless
        one was given. Without those headers Gmail shows a reply as a new
        conversation, which is the difference between answering somebody and
        starting a second thread beside theirs.

        `signed=False` is for Rouh's own letters - a password reset, a sign-in
        handed over - which are not the person writing, so carry no signature.

        No message leaves with a link that opens only on this computer (task 140, step 140-14):
        Rouh's own letters lose every loopback, private-network and `.local` link, moved onto this
        Rouh's outside address when it has one; mail the person writes loses only links to this
        Rouh on this computer (127.0.0.1:8420 and the like), which never open for whoever gets it
        (`outside_links.clean`).
        """
        from rouh import outside_links

        body = outside_links.guard(body, strict=not signed)
        html = outside_links.guard(html, strict=not signed, html=True) if html else html
        raw, wrote = await self._compose(to, subject, body, cc, bcc, reply_to_message_id,
                                         html=html, attachments=attachments, signed=signed)
        payload = {"raw": raw}
        if wrote["thread_id"]:
            payload["threadId"] = wrote["thread_id"]
        answer = await self._clients.call(
            self._who, "POST", self._url("/messages/send"), json_body=payload,
            seconds=_carrying(attachments))
        wrote["id"] = answer.get("id") or ""
        wrote["thread_id"] = answer.get("threadId") or wrote["thread_id"]
        return wrote

    async def draft(self, to: str, subject: str, body: str, *, cc: str = "",
                    bcc: str = "", reply_to_message_id: str = "", html: str = "",
                    attachments: list[dict] | None = None) -> dict:
        """Write the same message into Drafts and send nothing."""
        raw, wrote = await self._compose(to, subject, body, cc, bcc, reply_to_message_id,
                                         html=html, attachments=attachments)
        message = {"raw": raw}
        if wrote["thread_id"]:
            message["threadId"] = wrote["thread_id"]
        answer = await self._clients.call(
            self._who, "POST", self._url("/drafts"), json_body={"message": message},
            seconds=_carrying(attachments))
        wrote["draft_id"] = answer.get("id") or ""
        wrote["id"] = (answer.get("message") or {}).get("id") or ""
        return wrote

    async def send_draft(self, draft_id: str, to: str, subject: str, body: str, *,
                         cc: str = "", bcc: str = "", reply_to_message_id: str = "",
                         html: str = "", attachments: list[dict] | None = None) -> dict:
        """Send a draft that already exists, as it now reads, and leave nothing behind.

        This is the whole answer to the thing Petar found on 24 September 2026:
        Rouh drafted a reply, he said send it, and afterwards the draft was
        still sitting in his Gmail drafts next to the sent message, because
        sending had composed a second message rather than sending the one he
        had been shown.

        So the draft is written over with what the card now says and then that
        very draft is sent. Gmail takes the draft out of Drafts as it sends it,
        which is exactly what a person pressing Send in Gmail sees, and there
        is one message afterwards rather than two.

        A draft that is no longer there - sent from the phone, deleted in
        Gmail - is not quietly composed afresh: the caller is told, because a
        second copy of an email that already went is the mistake worth
        refusing.
        """
        raw, wrote = await self._compose(to, subject, body, cc, bcc, reply_to_message_id,
                                         html=html, attachments=attachments)
        message = {"raw": raw}
        if wrote["thread_id"]:
            message["threadId"] = wrote["thread_id"]
        where = f"/drafts/{urllib.parse.quote(draft_id)}"
        await self._clients.call(self._who, "PUT", self._url(where),
                                 json_body={"id": draft_id, "message": message},
                                 seconds=_carrying(attachments))
        answer = await self._clients.call(
            self._who, "POST", self._url("/drafts/send"), json_body={"id": draft_id})
        wrote["draft_id"] = ""
        wrote["id"] = answer.get("id") or (answer.get("message") or {}).get("id") or ""
        wrote["thread_id"] = answer.get("threadId") or wrote["thread_id"]
        return wrote

    async def forward(self, message_id: str, to: str, *, note: str = "",
                      note_html: str = "", subject: str = "", cc: str = "", bcc: str = "",
                      keep: list[str] | None = None, most: int = 0) -> dict:
        """Forward a message as Gmail's own Forward does: the original, unchanged.

        Its HTML, its pictures and its files go out exactly as they came, under
        Gmail's "Forwarded message" header, with `note` - the words the person
        asked to add - above it (`rouh/forwarding.py`). Nothing of the original
        passes through anything that could rewrite it: it is read from the
        message as it was sent (`format=raw`), each part in its own charset.
        With no note, the forward starts with the forwarded message, and is
        not signed: there is nothing of the person's above it to sign.

        `keep` names, by part number, which of its files go with it; None is
        every one of them, as Gmail forwards. `most` refuses files that
        together come to more than that. The answer is the same as `send`'s,
        with `forwarded` the message it passed on and `files` the names of the
        files that went.
        """
        from .. import forwarding

        whole, original = await self._forwardable(message_id)
        wanted = original.files if keep is None else \
            [one for one in original.files if one["part"] in {str(k) for k in keep}]
        files = [_file_of(one) for one in wanted]
        inline = [dict(_file_of(one), cid=one["cid"]) for one in original.inline]
        if not original.exact:
            files.append(forwarding.attached_whole(original))
        if most and sum(len(one["data"]) for one in files + inline) > most:
            raise CannotDoThat(
                "The files on that message come to more than Gmail takes on one message "
                "(25 MB). Forward it without some of them.")
        from rouh import outside_links
        # The note is Rouh's or the person's words: no link to this Rouh on this computer (step 140-14).
        note = outside_links.guard(note, strict=False)
        note_html = outside_links.guard(note_html, strict=False, html=True) if note_html else note_html
        text, html = forwarding.build(original, note, note_html or _note_markup(note))
        line = (subject or "").strip()
        if not line:
            said = original.headers.get("subject", "").strip()
            line = said if re.match(r"(?i)\s*(fwd?|fw)\s*:", said) else f"Fwd: {said}".strip()
        raw, wrote = await self._compose(to, line, text, cc, bcc, "", html=html,
                                         attachments=files, inline=inline, forwarding=True,
                                         signed=bool(note.strip()))
        answer = await self._clients.call(
            self._who, "POST", self._url("/messages/send"), json_body={"raw": raw},
            seconds=_carrying(files + inline), forward=True)
        wrote["id"] = answer.get("id") or ""
        wrote["thread_id"] = answer.get("threadId") or ""
        wrote["forwarded"] = message_id
        wrote["forwarded_thread"] = whole.get("threadId") or ""
        wrote["files"] = [one["name"] for one in files]
        return wrote

    async def forward_thread(self, message_id: str, to: str, *, note: str = "",
                             note_html: str = "", subject: str = "", cc: str = "",
                             bcc: str = "", with_files: bool = True, most: int = 0) -> dict:
        """Forward a whole conversation as one email, as Gmail's own Forward all does.

        Petar, 4 October 2026: "I have an email thread from [a supplier] about
        questions for regulations, data etc. forward that entire thread to
        [a contact]". `forward` passes on one message; this passes on every message
        in the conversation `message_id` is in - any one of them will do, or
        the conversation's own id - oldest first, each under its own
        "Forwarded message" header and each exactly as it came
        (`forwarding.build_thread`). Drafts, and anything in the bin or in
        spam, are not part of the conversation anybody sent, and stay out.

        Each message is read as it was sent (`format=raw`) and every part of
        it in its own charset: the first forward of that thread read Gmail's
        `format=full`, which had already turned the supplier's koi8-r Outlook mail
        into UTF-8, and read it as koi8-r again, so the contact got "п≈п╢я─п╟п╡п╣п╧"
        for "Здравей". A message whose words cannot be read for certain goes
        as an attached message instead, untouched (`forwarding.attached_whole`).

        Every message's files go with it, as Gmail's Forward all carries them,
        unless `with_files` is false; a file attached again further down the
        conversation, the same name and the same bytes, goes once. Pictures
        drawn inside a message always go, renamed apart from every other
        message's so each is drawn where it was, and the same picture drawn
        again further down (an Outlook signature's logos, in every reply)
        goes once and is drawn from that one. `most` refuses a conversation
        whose files together come to more than that, naming the biggest,
        rather than quietly leaving some behind.

        The answer is `send`'s, with `forwarded_thread`, `messages` (how many
        went) and `files` (the names of the files that went).
        """
        import hashlib

        from .. import forwarding

        wanted = (message_id or "").strip()
        if not wanted:
            raise GoogleSaidNo("Say which conversation, by any one of its emails.")
        try:
            thread_id = await self.thread_of(wanted)
        except GoogleSaidNo as exc:
            if exc.status != 404:
                raise
            thread_id = wanted
        whole = await self._clients.call(
            self._who, "GET", self._url(f"/threads/{urllib.parse.quote(thread_id or wanted)}"),
            params={"format": "minimal"})
        held = [one for one in whole.get("messages") or []
                if one.get("id") and not set(one.get("labelIds") or []) & LEFT_OUT_OF_A_THREAD]
        if not held:
            raise GoogleSaidNo("That conversation has no email in it to forward.")
        read = [await self._forwardable(one["id"]) for one in held]
        read.sort(key=lambda pair: int(pair[0].get("internalDate") or 0))
        files, inline, originals = [], [], []
        sent_once: set = set()
        pictures: dict = {}
        for number, (_, original) in enumerate(read, start=1):
            for part in original.files if with_files else []:
                mark = (part["name"], hashlib.sha256(part["data"]).hexdigest())
                if mark not in sent_once:
                    sent_once.add(mark)
                    files.append(_file_of(part))
            if not original.exact:
                files.append(forwarding.attached_whole(original))
            markup = original.html
            for part in original.inline:
                mark = hashlib.sha256(part["data"]).hexdigest()
                cid = pictures.get(mark)
                if cid is None:
                    cid = pictures[mark] = f"m{number}.{part['cid']}"
                    inline.append(dict(_file_of(part), cid=cid))
                markup = re.sub(r"(?i)cid:" + re.escape(part["cid"]) + r"(?=[\"'\s)>])",
                                "cid:" + cid, markup)
            originals.append(forwarding.Original(
                headers=original.headers, at=original.at, text=original.text, html=markup,
                raw=original.raw, exact=original.exact))
        carried = files + inline
        size = sum(len(one["data"]) for one in carried)
        if most and size > most:
            biggest = sorted(carried, key=lambda one: -len(one["data"]))[:3]
            raise CannotDoThat(
                f"The files in that conversation come to {_megabytes(size)}, and Gmail takes "
                f"{MAIL_LIMIT // (1024 * 1024)} MB at most on one message. The biggest are "
                + ", ".join(f"{one['name'] or 'a picture'} ({_megabytes(len(one['data']))})"
                            for one in biggest)
                + ". Forward it without its files, or the emails one at a time.")
        from rouh import outside_links
        # The note is Rouh's or the person's words: no link to this Rouh on this computer (step 140-14).
        note = outside_links.guard(note, strict=False)
        note_html = outside_links.guard(note_html, strict=False, html=True) if note_html else note_html
        text, html = forwarding.build_thread(originals, note, note_html or _note_markup(note))
        line = (subject or "").strip()
        if not line:
            said = originals[0].headers.get("subject", "").strip()
            said = re.sub(r"(?i)^\s*((re|aw|fwd?|fw)\s*:\s*)+", "", said)
            line = f"Fwd: {said}".strip()
        raw, wrote = await self._compose(to, line, text, cc, bcc, "", html=html,
                                         attachments=files, inline=inline, forwarding=True,
                                         signed=bool(note.strip()))
        answer = await self._clients.call(
            self._who, "POST", self._url("/messages/send"), json_body={"raw": raw},
            seconds=_carrying(files + inline), forward=True)
        wrote["id"] = answer.get("id") or ""
        wrote["thread_id"] = answer.get("threadId") or ""
        wrote["forwarded"] = wanted
        wrote["forwarded_thread"] = whole.get("id") or thread_id
        wrote["messages"] = len(originals)
        wrote["files"] = [one["name"] for one in files]
        return wrote

    async def drawn_inside(self, message_id: str, original) -> str:
        """A forward's original HTML with its `cid:` pictures as data, to be looked at.

        Only for showing it on the inbox card, where a `cid:` address points
        nowhere; what is sent carries the pictures as parts (`forward`).
        """
        markup = original.html
        for one in original.inline:
            url = f"data:{one['type']};base64," + base64.b64encode(one["data"]).decode()
            markup = re.sub(r"(?i)cid:" + re.escape(one["cid"]) + r"(?=[\"'\s)>])",
                            url, markup)
        return markup

    async def forwardable(self, message_id: str):
        """A message as a forward would carry it (`forwarding.Original`)."""
        return (await self._forwardable(message_id))[1]

    async def _forwardable(self, message_id: str):
        """A message as it was sent, every byte (`format=raw`), and what a forward makes of it."""
        from .. import forwarding

        whole = await self._clients.call(
            self._who, "GET", self._url(f"/messages/{urllib.parse.quote(message_id)}"),
            params={"format": "raw"})
        data = whole.get("raw") or ""
        try:
            raw = base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))
        except Exception:
            raise GoogleSaidNo("That email could not be read to forward it.") from None
        original = forwarding.read(raw)
        original.at = _arrived(whole, original.headers)
        return whole, original

    async def delete_draft(self, draft_id: str) -> None:
        """Take a draft out of Drafts. Used when a message went another way."""
        await self._clients.call(
            self._who, "DELETE",
            self._url(f"/drafts/{urllib.parse.quote(draft_id)}"))

    async def _compose(self, to: str, subject: str, body: str, cc: str, bcc: str,
                       reply_to_message_id: str, *, html: str = "",
                       attachments: list[dict] | None = None,
                       inline: list[dict] | None = None, forwarding: bool = False,
                       signed: bool = True) -> tuple[str, dict]:
        """The RFC 2822 message itself, base64url encoded the way Gmail takes it.

        Built with Python's own `email` package rather than by joining strings.
        A subject with a comma in it, an address with a name in front of it and
        a body with a non-ASCII character are each a way a hand-rolled message
        becomes one Gmail rejects or one that arrives as mojibake.

        It is signed here, with the signature the person set in Settings for
        a new email or for a reply or forward (`rouh/signatures.py`), because
        Gmail only signs what is written in its own compose window: what the
        API is handed goes out exactly as it is (`with_signature`). A reply
        is anything with `reply_to_message_id`, and a forward is `forwarding`.
        """
        thread_id, in_reply_to, references, reply_subject, reply_to = "", "", "", "", ""
        if reply_to_message_id:
            original = await self._clients.call(
                self._who, "GET",
                self._url(f"/messages/{urllib.parse.quote(reply_to_message_id)}"),
                params={"format": "metadata",
                        "metadataHeaders": ["Message-ID", "References", "Subject",
                                            "From", "Reply-To"]})
            named = _named_headers(original.get("payload") or {})
            thread_id = original.get("threadId") or ""
            in_reply_to = named.get("message-id", "")
            references = " ".join(x for x in (named.get("references", ""), in_reply_to) if x)
            reply_subject = named.get("subject", "")
            reply_to = named.get("reply-to") or named.get("from", "")

        recipients = (to or "").strip() or reply_to
        if not recipients:
            raise GoogleSaidNo("There is nobody to send that to.")
        line = (subject or "").strip()
        if not line and reply_subject:
            line = reply_subject if reply_subject.lower().startswith("re:") else "Re: " + reply_subject

        note = EmailMessage()
        note["To"] = recipients
        note["Subject"] = line or "(no subject)"
        if cc:
            note["Cc"] = cc
        if bcc:
            note["Bcc"] = bcc
        if in_reply_to:
            note["In-Reply-To"] = in_reply_to
            note["References"] = references
        signature = ""
        if signed:
            from asgiref.sync import sync_to_async

            from .. import signatures

            signature = await sync_to_async(signatures.for_mail)(
                self._who, answering=bool(reply_to_message_id) or forwarding)
        body, html, signed_as = with_signature(body, html, signature)
        note.set_content(body or "")
        # Both halves, whenever there is markup: plenty of people read mail as
        # text, and a reader handed only HTML is handed tags. The text part is
        # the one set above, which is why it goes first.
        if html:
            note.add_alternative(html, subtype="html")
            # Pictures the markup draws by `cid:`, beside it in one
            # multipart/related, under the Content-ID it names them by: a
            # forward's logo, where it was in the original (`forwarding.py`).
            drawn = note.get_payload()[1] if inline else None
            for one in inline or []:
                if not one.get("data"):
                    continue
                main, _, sub = str(one.get("type") or "application/octet-stream").partition("/")
                drawn.add_related(one["data"], maintype=main or "application",
                                  subtype=sub or "octet-stream",
                                  cid=f"<{one.get('cid') or uuid.uuid4().hex}>",
                                  filename=one.get("name") or None,
                                  disposition="inline")
        whole_messages: dict[bytes, bytes] = {}
        for one in attachments or []:
            data = one.get("data")
            if not data:
                continue
            main, _, sub = str(one.get("type") or "application/octet-stream").partition("/")
            if (main, sub) == ("message", "rfc822"):
                # A message attached whole goes byte for byte, as it came
                # (`forwarding.attached_whole`). Python's `email` would only
                # carry it base64, which a message/rfc822 part may not be, or
                # write it out again; so a mark stands in for it here and the
                # bytes are put in its place below.
                mark = f"rouh-whole-message-{uuid.uuid4().hex}"
                held = MIMEPart()
                held["Content-Type"] = "message/rfc822"
                held["Content-Disposition"] = "attachment"
                held.set_param("filename", str(one.get("name") or "message.eml"),
                               header="Content-Disposition")
                held["Content-Transfer-Encoding"] = "7bit" if data.isascii() else "8bit"
                held.set_payload(mark)
                if not note.is_multipart() or note.get_content_type() != "multipart/mixed":
                    note.make_mixed()
                note.attach(held)
                whole_messages[mark.encode()] = re.sub(rb"\r?\n", b"\n", data).rstrip(b"\n")
                continue
            note.add_attachment(data, maintype=main or "application",
                                subtype=sub or "octet-stream",
                                filename=str(one.get("name") or "attachment"))
        whole = note.as_bytes()
        for mark, data in whole_messages.items():
            whole = whole.replace(mark, data, 1)
        if len(whole) > MAIL_LIMIT:
            raise CannotDoThat(
                f"With its files that email comes to {_megabytes(len(whole))}, and Gmail "
                f"takes {MAIL_LIMIT // (1024 * 1024)} MB at most on one message; a file is "
                "about a third bigger inside an email than on disk. Take a file off, or "
                "send a smaller one.")
        raw = base64.urlsafe_b64encode(whole).decode()
        return raw, {"to": recipients, "cc": cc, "bcc": bcc,
                     "subject": note["Subject"], "thread_id": thread_id,
                     "replied_to": reply_to_message_id, "id": "", "signature": signed_as,
                     "html": html}

    async def labels(self) -> list[dict]:
        """Every label in the mailbox: its id and the name a person sees."""
        body = await self._clients.call(self._who, "GET", self._url("/labels"))
        return [{"id": one.get("id") or "", "name": one.get("name") or ""}
                for one in (body.get("labels") or [])]

    async def label_ids(self, names, *, make_missing: bool = False) -> tuple[dict, list[str]]:
        """Turn what a person called a label into what Gmail calls it.

        Returns `{the name they said: the id Gmail uses}` for the ones that
        resolved, and the list of names that did not. A person says "mark it
        important" and "file it under Travel" in the same breath, and only one
        of those is a label Gmail ships with, so both routes are here; keeping
        the name beside the id is what lets the confirmation say the word they
        used rather than `Label_7`.
        """
        wanted = [str(n).strip() for n in (names or ()) if str(n).strip()]
        if not wanted:
            return {}, []
        known = await self.labels()
        by_name = {one["name"].lower(): one["id"] for one in known}
        by_id = {one["id"] for one in known}
        found: dict = {}
        missing: list[str] = []
        for name in wanted:
            if name in by_id:
                found[name] = name
            elif name.lower() in SYSTEM_LABELS and SYSTEM_LABELS[name.lower()] in by_id:
                found[name] = SYSTEM_LABELS[name.lower()]
            elif name.lower() in by_name:
                found[name] = by_name[name.lower()]
            elif name.upper() in by_id:
                found[name] = name.upper()
            elif make_missing:
                made = await self._clients.call(
                    self._who, "POST", self._url("/labels"),
                    json_body={"name": name, "labelListVisibility": "labelShow",
                               "messageListVisibility": "show"})
                if made.get("id"):
                    found[name] = made["id"]
                else:
                    missing.append(name)
            else:
                missing.append(name)
        return found, missing

    async def modify(self, message_id: str, *, add=(), remove=()) -> dict:
        """Add and remove labels on one message. Reading and archiving are both this.

        Read is the absence of `UNREAD`, and archived is the absence of
        `INBOX`, which is why one method covers marking, labelling and
        archiving rather than three.
        """
        body = await self._clients.call(
            self._who, "POST",
            self._url(f"/messages/{urllib.parse.quote(message_id)}/modify"),
            json_body={"addLabelIds": list(add), "removeLabelIds": list(remove)})
        return {"id": body.get("id") or message_id,
                "labels": list(body.get("labelIds") or [])}

    async def modify_thread(self, thread_id: str, *, add=(), remove=()) -> dict:
        """Add and remove labels on every message of a thread, the way Gmail's
        own Archive does to a conversation."""
        body = await self._clients.call(
            self._who, "POST",
            self._url(f"/threads/{urllib.parse.quote(thread_id)}/modify"),
            json_body={"addLabelIds": list(add), "removeLabelIds": list(remove)})
        return {"id": body.get("id") or thread_id}

    async def thread_sent(self, thread_id: str) -> list[str]:
        """The ids of the messages in a thread that this mailbox sent, oldest first.

        What a reply that must go once is checked against: a sent message that
        is in the thread now and was not when the reply was claimed is that
        reply, gone already (`rouh/mail_cases.py`).
        """
        if not thread_id:
            return []
        whole = await self._clients.call(
            self._who, "GET", self._url(f"/threads/{urllib.parse.quote(thread_id)}"),
            params={"format": "minimal"})
        return [str(m.get("id") or "") for m in whole.get("messages") or []
                if m.get("id") and "SENT" in (m.get("labelIds") or [])]

    async def thread_minimal(self, thread_id: str) -> list[dict]:
        """A thread's messages as ids and labels, oldest first, with nothing of them read."""
        whole = await self._clients.call(
            self._who, "GET", self._url(f"/threads/{urllib.parse.quote(thread_id)}"),
            params={"format": "minimal"})
        return [m for m in whole.get("messages") or [] if m.get("id")]

    async def thread_of(self, message_id: str) -> str:
        """Which thread a message is in, with nothing of the message read."""
        body = await self._clients.call(
            self._who, "GET", self._url(f"/messages/{urllib.parse.quote(message_id)}"),
            params={"format": "minimal"})
        return str(body.get("threadId") or "")

    async def trash(self, message_id: str) -> dict:
        """Into the bin, where Gmail keeps it for thirty days. Never deleted outright."""
        body = await self._clients.call(
            self._who, "POST",
            self._url(f"/messages/{urllib.parse.quote(message_id)}/trash"))
        return {"id": body.get("id") or message_id,
                "labels": list(body.get("labelIds") or [])}

    # --- being told about new mail (`rouh/mail_alerts.py`) --------------------

    async def watch(self, topic: str, labels=("INBOX",)) -> dict:
        """Ask Gmail to tell a Pub/Sub topic whenever these labels change.

        Gmail keeps a watch for seven days and asks for it to be made again
        once a day; making it again replaces the one before, so renewing is
        this same call. Nothing is read or changed in the mailbox. What comes
        back is the history id the mailbox is at now, which is where reading
        new mail starts, and when the watch runs out, in seconds.
        """
        body = await self._clients.call(
            self._who, "POST", self._url("/watch"),
            json_body={"topicName": topic, "labelIds": list(labels),
                       "labelFilterBehavior": "include"})
        try:
            expires = int(body.get("expiration") or 0) / 1000.0
        except (TypeError, ValueError):
            expires = 0.0
        return {"history_id": str(body.get("historyId") or ""), "expires_at": expires}

    async def stop(self) -> None:
        """Stop every watch on this mailbox, so Gmail tells nobody any more."""
        await self._clients.call(self._who, "POST", self._url("/stop"))

    async def profile(self) -> dict:
        """The mailbox's own address, and the history id it is at now."""
        body = await self._clients.call(self._who, "GET", self._url("/profile"))
        return {"email": body.get("emailAddress") or "",
                "history_id": str(body.get("historyId") or "")}

    async def added_since(self, history_id: str, *, label: str = "INBOX",
                          pages: int = 10) -> tuple[list[str], str]:
        """The messages added to a label since a history id, and where the mailbox is now.

        Oldest first, each once. A notification from Gmail says only that
        something changed and the history id it changed to; this is how the
        change is read. Raises `HistoryGone` when Gmail no longer keeps history
        that far back, which it answers with a 404: a watch that stopped for a
        week, or a history id from another mailbox.
        """
        params = {"startHistoryId": history_id, "historyTypes": "messageAdded",
                  "labelId": label, "maxResults": 500}
        ids: list[str] = []
        latest = history_id
        for _ in range(max(1, pages)):
            try:
                body = await self._clients.call(self._who, "GET", self._url("/history"),
                                                params=params)
            except GoogleSaidNo as exc:
                if exc.status == 404:
                    raise HistoryGone(str(exc)) from None
                raise
            latest = str(body.get("historyId") or latest)
            for record in body.get("history") or []:
                for added in record.get("messagesAdded") or []:
                    found = (added.get("message") or {}).get("id")
                    if found and found not in ids:
                        ids.append(found)
            following = body.get("nextPageToken")
            if not following:
                break
            params["pageToken"] = following
        return ids, latest


    # --- the whole mailbox, as Synapse keeps a copy of it (`synapse/gmailsync.py`) ----------
    #
    # GET requests only, so a mailbox connected read-only (`inboxes.ReadOnlyClients`)
    # answers every one of them exactly as Rouh's own does.

    async def listing(self, *, page_token: str = "", query: str = "",
                      spam_and_trash: bool = True, size: int = 500) -> tuple[list[str], str]:
        """One page of the mailbox's message ids, newest first, and the next page's token
        ("" after the last). Spam and the Bin are in it unless asked not to be, which
        with no query is everything Gmail's `in:anywhere` finds, drafts included."""
        params: dict = {"maxResults": max(1, min(500, int(size)))}
        if spam_and_trash:
            params["includeSpamTrash"] = "true"
        if query:
            params["q"] = query
        if page_token:
            params["pageToken"] = page_token
        body = await self._clients.call(self._who, "GET", self._url("/messages"), params=params)
        return ([m["id"] for m in body.get("messages") or [] if m.get("id")],
                str(body.get("nextPageToken") or ""))

    async def draft_message_ids(self) -> set[str]:
        """The message id of every draft, which is not mail anybody sent or received yet."""
        out: set[str] = set()
        params: dict = {"maxResults": 500}
        while True:
            body = await self._clients.call(self._who, "GET", self._url("/drafts"), params=params)
            for one in body.get("drafts") or []:
                found = (one.get("message") or {}).get("id")
                if found:
                    out.add(found)
            following = body.get("nextPageToken")
            if not following:
                return out
            params["pageToken"] = following

    async def changes(self, history_id: str, *, page_token: str = "") -> dict:
        """One page of everything that changed since a history id: messages added and
        deleted, labels added and taken off, as Gmail's own records, with the history id
        the mailbox is at and the next page's token. `HistoryGone` on Gmail's 404."""
        params: dict = {"startHistoryId": history_id, "maxResults": 500}
        if page_token:
            params["pageToken"] = page_token
        try:
            body = await self._clients.call(self._who, "GET", self._url("/history"), params=params)
        except GoogleSaidNo as exc:
            if exc.status == 404:
                raise HistoryGone(str(exc)) from None
            raise
        return {"history": body.get("history") or [], "history_id": str(body.get("historyId") or ""),
                "next": str(body.get("nextPageToken") or "")}

    async def raw(self, message_id: str) -> dict:
        """One message whole, as the bytes it arrived as, with its labels, thread and
        Gmail's own time of arrival in milliseconds. `GoogleSaidNo` 404 when it is gone."""
        import base64

        body = await self._clients.call(
            self._who, "GET", self._url("/messages/" + urllib.parse.quote(message_id)),
            params={"format": "raw"}, seconds=90.0)
        try:
            internal = int(body.get("internalDate") or 0)
        except (TypeError, ValueError):
            internal = 0
        data = str(body.get("raw") or "")
        return {"id": str(body.get("id") or message_id), "thread_id": str(body.get("threadId") or ""),
                "labels": list(body.get("labelIds") or []), "internal_ms": internal,
                "raw": base64.urlsafe_b64decode(data + "=" * (-len(data) % 4)) if data else b""}

    async def labels_now(self, message_id: str) -> list[str]:
        """A message's labels as they are now. `GoogleSaidNo` 404 when it is gone."""
        body = await self._clients.call(
            self._who, "GET", self._url("/messages/" + urllib.parse.quote(message_id)),
            params={"format": "minimal"})
        return list(body.get("labelIds") or [])


class HistoryGone(GoogleSaidNo):
    """Gmail no longer keeps the mailbox's history as far back as was asked."""


def _first_header(payload: dict, name: str) -> str:
    """The first header of that name, which for one Gmail adds is Gmail's own."""
    for header in payload.get("headers") or []:
        if (header.get("name") or "").lower() == name:
            return header.get("value") or ""
    return ""


def _named_headers(payload: dict) -> dict:
    named = {}
    for header in payload.get("headers") or []:
        named[(header.get("name") or "").lower()] = header.get("value") or ""
    return named


def _arrived(body: dict, named: dict) -> float:
    """When a message arrived, in seconds since 1970, or 0 when nothing says.

    Gmail's own `internalDate` first, which is when the message reached the
    mailbox and is what Gmail sorts by; the Date header only when that is
    missing, because a Date header is whatever the sender's machine thought
    the time was.
    """
    try:
        at = int(body.get("internalDate") or 0) / 1000.0
    except (TypeError, ValueError):
        at = 0.0
    if at:
        return at
    try:
        from email.utils import parsedate_to_datetime

        return parsedate_to_datetime(named.get("date", "")).timestamp()
    except (TypeError, ValueError, IndexError):
        return 0.0


def _carrying(attachments) -> float:
    """How long a write may take: a message with files on it is an upload."""
    return UPLOAD_SECONDS if any(one.get("data") for one in attachments or []) else 0.0


def _megabytes(size: int) -> str:
    return f"{size / (1024 * 1024):.1f} MB"


def _attachments(payload: dict) -> list[dict]:
    """The files hanging off a message: each one's part, name, kind and size."""
    out: list[dict] = []

    def walk(part: dict) -> None:
        name = part.get("filename") or ""
        if name and part.get("partId") is not None:
            out.append({"part": str(part.get("partId")), "name": name,
                        "type": part.get("mimeType") or "application/octet-stream",
                        "size": int((part.get("body") or {}).get("size") or 0)})
        for child in part.get("parts") or []:
            walk(child)

    walk(payload)
    return out


#: The kinds a calendar invitation travels as, and the endings of a calendar file.
CALENDAR_KINDS = ("text/calendar", "application/ics", "text/x-vcalendar")
CALENDAR_ENDINGS = (".ics", ".vcs")


def _calendar_parts(payload: dict) -> list[dict]:
    """The calendar invitations in a message: [{part, name, data, attachment_id}], at most four.

    `data` is the iCalendar text where Gmail sent the part inline, which it does for a small text
    part with no file name (the usual invitation); otherwise it is fetched by `attachment_id`, or
    by part for a named .ics file (`Gmail.calendar_text`).
    """
    out: list[dict] = []

    def walk(part: dict) -> None:
        kind = (part.get("mimeType") or "").lower()
        name = part.get("filename") or ""
        if kind in CALENDAR_KINDS or name.lower().endswith(CALENDAR_ENDINGS):
            body = part.get("body") or {}
            out.append({"part": str(part.get("partId") or ""), "name": name,
                        "data": _b64(body["data"]) if body.get("data") else "",
                        "attachment_id": "" if body.get("data") else str(body.get("attachmentId") or "")})
        for child in part.get("parts") or []:
            walk(child)

    walk(payload)
    return out[:4]


def _part_numbered(payload: dict, number: str) -> dict | None:
    """The part of a message with this part number and a file name, or None."""
    if str(payload.get("partId")) == number and payload.get("filename"):
        return payload
    for child in payload.get("parts") or []:
        found = _part_numbered(child, number)
        if found is not None:
            return found
    return None


def _file_of(part: dict) -> dict:
    """A part a forward carries, as `_compose` takes a file: name, type and bytes."""
    return {"name": part.get("name") or "attachment",
            "type": part.get("type") or "application/octet-stream", "data": part["data"]}


def _note_markup(text: str) -> str:
    """The words added above a forward, as markup: paragraphs and lines kept."""
    paragraphs = [p for p in re.split(r"\n[ \t]*\n+", (text or "").strip()) if p.strip()]
    return "".join(f"<p>{html_module.escape(p).replace(chr(10), '<br>')}</p>"
                   for p in paragraphs)


def _message_bodies(payload: dict) -> tuple[str, str]:
    """The plain text and the HTML of a message, each joined up, either empty.

    A Gmail message is a tree: a multipart/alternative with a text part and an
    HTML part, a multipart/mixed with attachments beside it, or one part on its
    own. Both text kinds are gathered from the whole tree, and the plain one is
    used wherever there is one, because that is what the sender wrote rather
    than what their client drew. A part with a file name is an attachment even when it is text - a notes.txt
    sent along with the message - and is not read as the message itself.
    """
    plain: list[str] = []
    html: list[str] = []

    def walk(part: dict) -> None:
        kind = (part.get("mimeType") or "").lower()
        data = (part.get("body") or {}).get("data") or ""
        if data and not part.get("filename"):
            text = _b64(data)
            if kind == "text/plain":
                plain.append(text)
            elif kind == "text/html":
                html.append(text)
        for child in part.get("parts") or []:
            walk(child)

    walk(payload)
    return "\n".join(plain).strip(), "\n".join(html).strip()


def _b64(data: str) -> str:
    """Gmail's base64url, with the padding it leaves off put back."""
    try:
        raw = base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))
    except Exception:
        return ""
    return raw.decode("utf-8", "replace")
