"""Gmail registration for the Google stand-in."""
from __future__ import annotations

from . import (
    ACCOUNT_EMAIL,
    JSONResponse,
    PUBSUB_PROJECT,
    Request,
    Response,
    _arrived_at,
    _full_of_raw,
    _matches,
    _payload,
    _raw_answer,
    _raw_attachment,
    _read_rfc2822,
    _thread_of,
    asyncio,
    base64,
    email,
    html,
    re,
    time,
)


def _gmail_routes(app, world, seen, note, made_up, changed):
    # --- Gmail ----------------------------------------------------------------

    @app.get("/gmail/v1/users/me/messages")
    async def messages(request: Request, q: str = "", maxResults: int = 100,
                       includeSpamTrash: str = "", pageToken: str = ""):
        """Gmail's list, newest first, narrowed by as much of its search as Rouh uses.

        `in:inbox`, `in:sent` and `label:` look at the labels, `is:unread` and
        `is:read` at whether it has been read, `from:`, `to:` and `subject:`
        at those lines, and any other word at the sender, the subject and the
        text. The bin and spam are left out unless asked for (`in:anywhere`,
        `in:trash`, `includeSpamTrash=true`), as Gmail leaves them out. At most
        500 a page, as Gmail's, the rest behind `nextPageToken`.
        """
        seen["api"].append(str(request.url))
        anywhere = str(includeSpamTrash).lower() == "true"
        found = [m for m in world["messages"] if _matches(m, q, world["labels"], anywhere=anywhere)]
        found.sort(key=_arrived_at, reverse=True)
        size = max(1, min(500, int(maxResults or 100)))
        start = int(pageToken[1:]) if pageToken.startswith("p") and pageToken[1:].isdigit() else 0
        page = found[start:start + size]
        out = {"messages": [{"id": m["id"], "threadId": _thread_of(m)} for m in page],
               "resultSizeEstimate": len(found)}
        if start + size < len(found):
            out["nextPageToken"] = f"p{start + size}"
        return JSONResponse(out)

    @app.get("/gmail/v1/users/me/messages/{message_id}")
    async def message(message_id: str, request: Request, format: str = "full"):
        seen["api"].append(str(request.url))
        found = next((m for m in world["messages"] if m["id"] == message_id), None)
        if found is None:
            return JSONResponse({"error": {"message": "Not Found"}}, status_code=404)
        if format == "raw":
            return _raw_answer(found, _thread_of(found))
        if format == "minimal":
            return JSONResponse({"id": found["id"], "threadId": _thread_of(found),
                                 "labelIds": found["labels"],
                                 "internalDate": str(int(_arrived_at(found) * 1000))})
        return JSONResponse(whole(found))

    def whole(found: dict) -> dict:
        """One message as Gmail's `format=full` has it, on its own or in its thread."""
        # Gmail's own check goes on top, as it does on arrival; anything a
        # sender wrote in goes further down.
        headers = ([{"name": "Authentication-Results", "value": found["authentication"]}]
                   if found.get("authentication") else [])
        headers += [
            {"name": "From", "value": found["from"]},
            {"name": "To", "value": found["to"]},
            {"name": "Subject", "value": found["subject"]},
            {"name": "Date", "value": found["date"]},
            {"name": "Message-ID", "value": found["message_id"]},
        ]
        for name, key in (("Cc", "cc"), ("Reply-To", "reply_to"),
                          ("References", "references"), ("In-Reply-To", "in_reply_to")):
            if found.get(key):
                headers.append({"name": name, "value": found[key]})
        for name, value in (found.get("headers") or {}).items():
            headers.append({"name": name, "value": value})
        # Anything a sender planted further down, under Gmail's own on top.
        if found.get("forged"):
            headers.append({"name": "Authentication-Results", "value": found["forged"]})
        if found.get("raw"):
            payload = _full_of_raw(found)
        else:
            payload = _payload(found)
            payload["headers"] = headers
        words = found.get("text") or re.sub(
            r"<[^>]+>", " ", re.sub(r"(?is)<(style|script|head)[^>]*>.*?</\1>", " ",
                                    found.get("html") or ""))
        return {
            "id": found["id"], "threadId": _thread_of(found),
            "labelIds": found["labels"],
            "snippet": html.escape(" ".join(words.split())[:100], quote=True),
            "internalDate": str(int(_arrived_at(found) * 1000)),
            "payload": payload,
        }

    @app.get("/gmail/v1/users/me/messages/{message_id}/attachments/{attachment_id}")
    async def attachment(message_id: str, attachment_id: str, request: Request):
        seen["api"].append(str(request.url))
        found = next((m for m in world["messages"] if m["id"] == message_id), None)
        held = _raw_attachment(found or {}, attachment_id)
        if held is not None:
            return held
        for n, one in enumerate((found or {}).get("inline") or []):
            if f"inl-{message_id}-{n}" == attachment_id:
                data = base64.urlsafe_b64encode(one["data"]).decode().rstrip("=")
                return JSONResponse({"size": len(one["data"]), "data": data})
        for n, one in enumerate((found or {}).get("files") or []):
            if f"att-{message_id}-{n}" == attachment_id:
                data = base64.urlsafe_b64encode(one["data"]).decode().rstrip("=")
                return JSONResponse({"size": len(one["data"]), "data": data})
        return JSONResponse({"error": {"code": 404, "message": "Not Found"}},
                            status_code=404)

    @app.get("/gmail/v1/users/me/labels/{label_id}")
    async def label(label_id: str, request: Request):
        """One label, with Gmail's own count of what carries it."""
        seen["api"].append(str(request.url))
        known = next((one for one in world["labels"] if one["id"] == label_id), None)
        if known is None:
            return JSONResponse({"error": {"code": 404, "message": "Not Found"}},
                                status_code=404)
        holding = [m for m in world["messages"] if label_id in m["labels"]]
        return JSONResponse(dict(known, messagesTotal=len(holding),
                                 messagesUnread=sum(1 for m in holding
                                                    if "UNREAD" in m["labels"]),
                                 threadsTotal=len({_thread_of(m) for m in holding})))

    @app.get("/gmail/v1/users/me/settings/sendAs")
    async def send_as(request: Request):
        """The addresses the mailbox sends as: its own, and one alias."""
        seen["api"].append(str(request.url))
        return JSONResponse({"sendAs": [
            {"sendAsEmail": ACCOUNT_EMAIL, "isPrimary": True, "isDefault": True},
            {"sendAsEmail": "rou@example.com", "displayName": "Rouh"},
        ]})

    @app.get("/gmail/v1/users/me/profile")
    async def profile(request: Request):
        seen["api"].append(str(request.url))
        return JSONResponse({"emailAddress": ACCOUNT_EMAIL,
                             "messagesTotal": len(world["messages"]),
                             "historyId": str(world["history_id"])})

    @app.post("/gmail/v1/users/me/watch")
    async def watch(request: Request):
        """Refused where Gmail refuses: another project, no topic, no Publisher role."""
        seen["api"].append(str(request.url))
        body = await request.json()
        topic = str(body.get("topicName") or "")
        shape = re.match(r"^projects/([^/]+)/topics/([^/]+)$", topic)
        if not shape or shape.group(1) != PUBSUB_PROJECT:
            return JSONResponse({"error": {
                "code": 400, "status": "INVALID_ARGUMENT",
                "message": f"Invalid topicName does not match projects/{PUBSUB_PROJECT}/topics/*"}},
                status_code=400)
        found = world["topics"].get(topic)
        if found is None:
            return JSONResponse({"error": {
                "code": 404, "status": "NOT_FOUND",
                "message": f"Resource not found (resource={shape.group(2)})."}},
                status_code=404)
        if not found["publisher"]:
            return JSONResponse({"error": {
                "code": 403, "status": "PERMISSION_DENIED",
                "message": (f"Error sending test message to Cloud PubSub {topic} : User not "
                            "authorized to perform this action.")}}, status_code=403)
        expires = time.time() + 7 * 86400
        world["watch"] = {"topic": topic, "labels": list(body.get("labelIds") or []),
                          "behaviour": body.get("labelFilterBehavior") or "",
                          "expires": expires, "made": time.time()}
        note("watch made", {"topic": topic, "labels": world["watch"]["labels"]})
        return JSONResponse({"historyId": str(world["history_id"]),
                             "expiration": str(int(expires * 1000))})

    @app.post("/gmail/v1/users/me/stop")
    async def stop_watching(request: Request):
        seen["api"].append(str(request.url))
        world["watch"] = None
        note("watch stopped", {})
        return Response(status_code=204)

    @app.get("/gmail/v1/users/me/history")
    async def history(request: Request, startHistoryId: str = "", labelId: str = "",
                      historyTypes: str = "", maxResults: int = 100, pageToken: str = ""):
        """What changed since a history id: messages added and deleted, labels added
        and taken off, each as Gmail writes it, narrowed by `historyTypes` and
        `labelId` as Gmail narrows it, 100 a page unless asked for more."""
        seen["api"].append(str(request.url))
        try:
            start = int(startHistoryId)
        except ValueError:
            return JSONResponse({"error": {"code": 400, "message": "Invalid startHistoryId"}},
                                status_code=400)
        if start < world["history_floor"]:
            return JSONResponse({"error": {"code": 404, "status": "NOT_FOUND",
                                           "message": "Requested entity was not found."}},
                                status_code=404)
        # Gmail's own names in historyTypes, and the field each record puts it under.
        types = {"messageAdded": "messagesAdded", "messageDeleted": "messagesDeleted",
                 "labelAdded": "labelsAdded", "labelRemoved": "labelsRemoved"}
        wanted = {types[t] for t in historyTypes.split(",") if t in types} or set(types.values())
        records = [one for one in world["history"]
                   if one["id"] > start and one.get("kind", "messagesAdded") in wanted
                   and (not labelId or labelId in one["labels"] or labelId in one.get("changed", []))]
        size = max(1, min(500, int(maxResults or 100)))
        at = int(pageToken[1:]) if pageToken.startswith("h") and pageToken[1:].isdigit() else 0
        page = records[at:at + size]

        def record(one: dict) -> dict:
            kind = one.get("kind", "messagesAdded")
            message = {"id": one["message_id"], "threadId": "thread-" + one["message_id"],
                       "labelIds": one["labels"]}
            entry = {"message": message}
            if kind in ("labelsAdded", "labelsRemoved"):
                entry["labelIds"] = one["changed"]
            return {"id": str(one["id"]), "messages": [{"id": one["message_id"]}], kind: [entry]}

        out = {"history": [record(one) for one in page], "historyId": str(world["history_id"])}
        if at + size < len(records):
            out["nextPageToken"] = f"h{at + size}"
        return JSONResponse(out)

    @app.get("/gmail/v1/users/me/labels")
    async def labels(request: Request):
        seen["api"].append(str(request.url))
        return JSONResponse({"labels": world["labels"]})

    @app.post("/gmail/v1/users/me/labels")
    async def make_label(request: Request):
        body = await request.json()
        made = {"id": made_up("Label"), "name": body.get("name") or ""}
        world["labels"].append(made)
        note("label made", {"name": made["name"], "id": made["id"]})
        return JSONResponse(made)

    @app.post("/gmail/v1/users/me/messages/send")
    async def send(request: Request):
        """The one that really matters: what arrived is the RFC 2822 message.

        It is parsed here rather than kept as base64, so a test asserts on the
        headers and the body Gmail would have seen - the To, the Subject, the
        In-Reply-To - instead of on a blob it has to decode itself.
        """
        body = await request.json()
        wrote = _read_rfc2822(body.get("raw") or "")
        wrote["threadId"] = body.get("threadId") or ""
        wrote["id"] = made_up("sent")
        world["sent"].append(wrote)
        into_the_mailbox(wrote, body.get("raw") or "")
        note("message sent", {"to": wrote["to"], "subject": wrote["subject"],
                              "id": wrote["id"]})
        return JSONResponse({"id": wrote["id"],
                             "threadId": wrote["threadId"] or "thread-" + wrote["id"],
                             "labelIds": ["SENT"]})

    def into_the_mailbox(wrote: dict, raw: str = "") -> None:
        """A sent message in the mailbox as well, labelled SENT and nothing else,
        as Gmail keeps it: in its thread, and never in the inbox. Every byte of
        it, so `format=raw` reads back exactly what went."""
        world["messages"].insert(0, {
            "id": wrote["id"], "thread_id": wrote["threadId"] or "thread-" + wrote["id"],
            "from": f"<{ACCOUNT_EMAIL}>", "to": wrote["to"], "cc": wrote["cc"],
            "subject": wrote["subject"], "unread": False, "labels": ["SENT"],
            "date": time.strftime("%a, %d %b %Y %H:%M:%S +0000", time.gmtime()),
            "message_id": f"<{wrote['id']}@stand-in.test>", "text": wrote["body"],
            **({"raw": base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))} if raw else {})})

    @app.post("/gmail/v1/users/me/drafts")
    async def draft(request: Request):
        body = await request.json()
        message = body.get("message") or {}
        wrote = _read_rfc2822(message.get("raw") or "")
        wrote["threadId"] = message.get("threadId") or ""
        wrote["id"] = made_up("draft")
        world["drafts"].append(wrote)
        note("draft written", {"to": wrote["to"], "subject": wrote["subject"],
                               "id": wrote["id"]})
        return JSONResponse({"id": wrote["id"],
                             "message": {"id": "msg-" + wrote["id"],
                                         "threadId": wrote["threadId"] or "thread-" + wrote["id"],
                                         "labelIds": ["DRAFT"]}})

    @app.get("/gmail/v1/users/me/drafts/{draft_id}")
    async def one_draft(draft_id: str, request: Request, format: str = "full"):
        """A draft as Gmail hands one back: its message, files and all.

        What Rouh reads when it sends a draft it has no card for any more, so
        the files written into it go with it (`Gmail.draft_files`). Each file
        comes back inline rather than by attachment id, which Gmail does too
        for a small one: the draft's message is not in the mailbox here.
        """
        seen["api"].append(str(request.url))
        found = next((d for d in world["drafts"] if d["id"] == draft_id), None)
        if found is None:
            return JSONResponse({"error": {"code": 404, "message": "Not Found"}},
                                status_code=404)
        text = base64.urlsafe_b64encode(found.get("body", "").encode()).decode().rstrip("=")
        parts = [{"partId": "0", "mimeType": "text/plain", "filename": "",
                  "body": {"data": text}}]
        held = email.message_from_string(found.get("raw_text") or "")
        for part in (p for p in held.walk() if p.get_filename()):
            data = part.get_payload(decode=True) or b""
            parts.append({"partId": str(len(parts)), "mimeType": part.get_content_type(),
                          "filename": part.get_filename(),
                          "body": {"size": len(data),
                                   "data": base64.urlsafe_b64encode(data).decode().rstrip("=")}})
        headers = [{"name": name, "value": found[key]}
                   for name, key in (("To", "to"), ("Cc", "cc"), ("Bcc", "bcc"),
                                     ("Subject", "subject"), ("In-Reply-To", "in_reply_to"),
                                     ("References", "references")) if found.get(key)]
        return JSONResponse({"id": draft_id, "message": {
            "id": "msg-" + draft_id, "threadId": found.get("threadId") or "",
            "labelIds": ["DRAFT"],
            "payload": {"mimeType": "multipart/mixed", "partId": "", "headers": headers,
                        "parts": parts}}})

    @app.get("/gmail/v1/users/me/drafts")
    async def drafts(request: Request):
        """Gmail's list of drafts: each draft's id and its message's."""
        seen["api"].append(str(request.url))
        return JSONResponse({"drafts": [
            {"id": d["id"], "message": {"id": "msg-" + d["id"],
                                        "threadId": d.get("threadId") or ""}}
            for d in world["drafts"]]})

    @app.get("/gmail/v1/users/me/threads/{thread_id}")
    async def thread(thread_id: str, request: Request, format: str = "full"):
        """A thread's messages, oldest first, with its drafts in it as Gmail keeps them.

        Whole, as Gmail hands them back for `format=full`, which is what the
        ghost list reads a conversation with (`rouh/ghosts.py`); only ids and
        labels for `minimal`, after the wait `/_slow` set, if any, so a test
        can change something between a case's reply being cleared to go and
        its bytes being read (`mail_cases.CaseDesk._reply`).
        """
        if format == "minimal" and world.get("slow_threads"):
            await asyncio.sleep(float(world["slow_threads"]))
        seen["api"].append(str(request.url))
        held = [m for m in world["messages"] if _thread_of(m) == thread_id]
        held.sort(key=_arrived_at)
        out = [whole(m) if format == "full" else
               {"id": m["id"], "threadId": thread_id, "labelIds": m["labels"]} for m in held]
        out += [{"id": "msg-" + d["id"], "threadId": thread_id, "labelIds": ["DRAFT"]}
                for d in world["drafts"] if d.get("threadId") == thread_id]
        if not out:
            return JSONResponse({"error": {"code": 404, "message": "Not Found"}},
                                status_code=404)
        return JSONResponse({"id": thread_id, "messages": out})

    @app.put("/gmail/v1/users/me/drafts/{draft_id}")
    async def update_draft(draft_id: str, request: Request):
        """A draft written over with what the card now says."""
        body = await request.json()
        message = body.get("message") or {}
        found = next((d for d in world["drafts"] if d["id"] == draft_id), None)
        if found is None:
            return JSONResponse({"error": {"code": 404, "message": "Not Found"}},
                                status_code=404)
        found.update(_read_rfc2822(message.get("raw") or ""))
        found["id"] = draft_id
        found["threadId"] = message.get("threadId") or found.get("threadId") or ""
        note("draft rewritten", {"to": found["to"], "subject": found["subject"],
                                 "id": draft_id})
        return JSONResponse({"id": draft_id,
                             "message": {"id": "msg-" + draft_id, "labelIds": ["DRAFT"]}})

    @app.post("/gmail/v1/users/me/drafts/send")
    async def send_draft(request: Request):
        """The draft itself goes, and Gmail takes it out of Drafts as it does.

        Which is the point of the whole road: afterwards there is one sent
        message and no draft beside it.
        """
        body = await request.json()
        draft_id = body.get("id") or ""
        found = next((d for d in world["drafts"] if d["id"] == draft_id), None)
        if found is None:
            return JSONResponse({"error": {"code": 404, "message": "Not Found"}},
                                status_code=404)
        world["drafts"] = [d for d in world["drafts"] if d["id"] != draft_id]
        wrote = dict(found)
        wrote["id"] = made_up("sent")
        world["sent"].append(wrote)
        into_the_mailbox(wrote)
        note("draft sent", {"to": wrote["to"], "subject": wrote["subject"],
                            "id": wrote["id"], "was_draft": draft_id})
        return JSONResponse({"id": wrote["id"],
                             "threadId": wrote.get("threadId") or "thread-" + wrote["id"],
                             "labelIds": ["SENT"]})

    @app.delete("/gmail/v1/users/me/drafts/{draft_id}")
    async def drop_draft(draft_id: str):
        """Gone for good, as Gmail's own delete is; a draft that is not there is a 404."""
        if not any(d["id"] == draft_id for d in world["drafts"]):
            return JSONResponse({"error": {"code": 404, "message": "Not Found"}},
                                status_code=404)
        world["drafts"] = [d for d in world["drafts"] if d["id"] != draft_id]
        note("draft deleted", {"id": draft_id})
        return Response(status_code=204)

    @app.post("/gmail/v1/users/me/messages/{message_id}/modify")
    async def modify(message_id: str, request: Request):
        body = await request.json()
        found = next((m for m in world["messages"] if m["id"] == message_id), None)
        if found is None:
            return JSONResponse({"error": {"message": "Not Found"}}, status_code=404)
        if found.get("unchangeable"):
            note("message change refused", {"id": message_id})
            return JSONResponse({"error": {"code": 403, "message": "Request had insufficient "
                                           "authentication scopes."}}, status_code=403)
        before = list(found["labels"])
        labels = [one for one in found["labels"]
                  if one not in (body.get("removeLabelIds") or [])]
        for one in body.get("addLabelIds") or []:
            if one not in labels:
                labels.append(one)
        found["labels"] = labels
        found["unread"] = "UNREAD" in labels
        changed(found, [x for x in labels if x not in before], [x for x in before if x not in labels])
        note("message changed", {"id": message_id, "labels": labels,
                                 "added": body.get("addLabelIds") or [],
                                 "removed": body.get("removeLabelIds") or []})
        return JSONResponse({"id": message_id, "labelIds": labels})

    @app.post("/gmail/v1/users/me/threads/{thread_id}/modify")
    async def modify_thread(thread_id: str, request: Request):
        """Every message in a thread at once, the way Gmail's Archive works on a conversation."""
        body = await request.json()
        found = [m for m in world["messages"] if _thread_of(m) == thread_id]
        if not found:
            return JSONResponse({"error": {"message": "Not Found"}}, status_code=404)
        if any(one.get("unchangeable") for one in found):
            # As for one message: a read-only grant changes no label of the thread.
            note("thread change refused", {"id": thread_id})
            return JSONResponse({"error": {"code": 403, "message": "Request had insufficient "
                                           "authentication scopes."}}, status_code=403)
        for one in found:
            before = list(one["labels"])
            labels = [x for x in one["labels"] if x not in (body.get("removeLabelIds") or [])]
            for x in body.get("addLabelIds") or []:
                if x not in labels:
                    labels.append(x)
            one["labels"] = labels
            one["unread"] = "UNREAD" in labels
            changed(one, [x for x in labels if x not in before], [x for x in before if x not in labels])
        note("thread changed", {"id": thread_id, "messages": [m["id"] for m in found],
                                "added": body.get("addLabelIds") or [],
                                "removed": body.get("removeLabelIds") or []})
        return JSONResponse({"id": thread_id})

    @app.post("/gmail/v1/users/me/messages/{message_id}/trash")
    async def trash_message(message_id: str):
        found = next((m for m in world["messages"] if m["id"] == message_id), None)
        if found is None:
            return JSONResponse({"error": {"message": "Not Found"}}, status_code=404)
        before = list(found["labels"])
        found["labels"] = [one for one in found["labels"] if one != "INBOX"] + ["TRASH"]
        changed(found, ["TRASH"], ["INBOX"] if "INBOX" in before else [])
        note("message binned", {"id": message_id})
        return JSONResponse({"id": message_id, "labelIds": found["labels"]})
