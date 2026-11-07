"""Console registration for the Google stand-in."""
from __future__ import annotations

from . import (
    ACCOUNT_EMAIL,
    ALL_SCOPES,
    CALENDAR_ZONE,
    JSONResponse,
    Request,
    _raw_delivered,
    _thread_of,
    _without_bytes,
    base64,
    httpx,
    json,
    time,
)


def _console_routes(app, world, seen, reset, note, made_up):
    # --- what a test reads and sets -----------------------------------------

    @app.get("/_seen")
    async def what_arrived():
        """Everything this has been asked, for a test to read."""
        return JSONResponse({**seen, "sent": world["sent"], "drafts": world["drafts"],
                             "files": world["files"],
                             "messages": [_without_bytes(m) for m in world["messages"]],
                             "documents": world["documents"], "drives": world["drives"],
                             "calendars": world["calendars"], "events": world["events"],
                             "token_scopes": world["token_scopes"],
                             "history_id": world["history_id"], "watch": world["watch"],
                             "topics": world["topics"], "pushes": world["pushes"]})

    @app.post("/_slow")
    async def slow_down(request: Request):
        """`{"threads": 15}`: every minimal read of a thread waits that long; 0 for none."""
        body = await request.json()
        world["slow_threads"] = float(body.get("threads") or 0)
        return JSONResponse({"slow_threads": world["slow_threads"]})

    @app.post("/_reset")
    async def start_again():
        seen["writes"] = []
        reset()
        return JSONResponse({"ok": True})

    @app.post("/_pubsub")
    async def pubsub_console(request: Request):
        """What an administrator does in the Cloud console, as one call.

        `{"topic": "projects/rouh-stand-in/topics/gmail-alerts", "publisher":
        true, "push": "http://127.0.0.1:<rouh>/hooks/gmail/<token>"}` makes the
        topic, grants gmail-api-push@system.gserviceaccount.com the Publisher
        role on it or not, and gives it a push subscription to that address.
        """
        body = await request.json()
        name = str(body.get("topic") or "")
        world["topics"][name] = {"publisher": bool(body.get("publisher", True)),
                                 "push": str(body.get("push") or "")}
        return JSONResponse({"topics": world["topics"]})

    @app.post("/_deliver")
    async def deliver(request: Request):
        """New mail arrives in the inbox, and Gmail tells the watch's topic.

        `{"from": ..., "subject": ..., "text": ..., "labels": [...]}`, where
        the labels are any beside INBOX and UNREAD - `CATEGORY_PROMOTIONS`,
        `IMPORTANT`. `"quiet": true` loses the note on the way, which is what
        a push subscription pointed at the wrong address looks like from
        Rouh's side. `"cc"` copies people in. `"thread"` puts it in the thread
        of an earlier message, by that message's id, the way a reply lands.
        `"headers"` is any other headers it carries, `{"List-Unsubscribe": ...}`.
        `"authentication"` is the Authentication-Results header Gmail writes
        on top of mail from outside - "mx.google.com; dmarc=pass
        header.from=example.com" - and `"forged"` one further down, the way a
        sender can put one in what they send. `"unchangeable": true` makes
        Google refuse every label change on it with the 403 a `gmail.readonly`
        grant gets, which is how a write to a read-only inbox ends. Answers
        with the message's id,
        the history id it is at, and what the push address answered.

        `"sent": true` is the other way round: an email the mailbox's owner
        sent, labelled SENT and nothing else, from them, to `"to"`, and
        `"days_ago"` puts it that far back - what the ghost list looks for.
        It is not pushed to the watch, as Gmail does not push the sent mail.
        `"days_ago"` dates a received one back the same way.
        """
        body = await request.json()
        raw = _raw_delivered(body)
        world["next_id"] += 1
        message_id = f"new-{world['next_id']}"
        # `"read": true` has it opened already; `"date"` is its own Date line, such as one written on
        # another clock ("Tue, 03 Nov 2026 09:12:00 -0500"), when the sender's clock matters.
        labels = ["INBOX"] + ([] if body.get("read") else ["UNREAD"]) + [str(one) for one in body.get("labels") or []]
        if body.get("sent"):
            earlier = next((m for m in world["messages"] if m["id"] == body.get("thread")), None)
            at = time.time() - float(body.get("days_ago") or 0) * 86400
            world["messages"].insert(0, {
                "id": message_id, "from": f"Alex Morgan <{ACCOUNT_EMAIL}>",
                "to": str(body.get("to") or "Somebody <somebody@example.test>"),
                "cc": str(body.get("cc") or ""), "subject": str(body.get("subject") or ""),
                "date": time.strftime("%a, %d %b %Y %H:%M:%S +0000", time.gmtime(at)),
                "at": at, "unread": False, "message_id": f"<{message_id}@stand-in.test>",
                "text": str(body.get("text") or ""), "labels": ["SENT"],
                "thread_id": _thread_of(earlier) if earlier else "thread-" + message_id})
            return JSONResponse({"id": message_id, "history_id": world["history_id"],
                                 "pushed": None})
        earlier = next((m for m in world["messages"] if m["id"] == body.get("thread")), None)
        # `"days_ago"` dates it back, as an email that came in then.
        at = time.time() - float(body.get("days_ago") or 0) * 86400
        world["messages"].insert(0, {
            "id": message_id, "from": str(body.get("from") or "Somebody <somebody@example.test>"),
            "to": str(body.get("to") or f"<{ACCOUNT_EMAIL}>"),
            "cc": str(body.get("cc") or ""),
            "subject": str(body.get("subject") or ""),
            "date": str(body.get("date") or "") or time.strftime("%a, %d %b %Y %H:%M:%S +0000", time.gmtime(at)),
            # To the millisecond, as Gmail's internalDate is, so two emails
            # delivered within one second still come back in the order they came.
            "at": at,
            "unread": not body.get("read"), "message_id": f"<{message_id}@example.test>",
            "text": str(body.get("text") or ""), "labels": labels,
            # Markup beside the text, pictures drawn inside it, files on it:
            # each file as {"name", "type", "data": base64}, and a picture
            # with its "cid" as well.
            "html": str(body.get("html") or ""),
            "inline": [dict(one, data=base64.b64decode(one["data"]))
                       for one in body.get("inline") or []],
            "files": [dict(one, data=base64.b64decode(one["data"]))
                      for one in body.get("files") or []],
            "thread_id": _thread_of(earlier) if earlier else "thread-" + message_id,
            "authentication": str(body.get("authentication") or ""),
            "forged": str(body.get("forged") or ""),
            "unchangeable": bool(body.get("unchangeable")),
            # Any other headers it carries, by name: List-Unsubscribe,
            # Precedence, Auto-Submitted - what bulk mail writes.
            "headers": {str(k): str(v) for k, v in (body.get("headers") or {}).items()},
            **({"raw": raw} if raw else {})})
        world["history_id"] += 7
        world["history"].append({"id": world["history_id"], "message_id": message_id,
                                 "labels": labels})
        pushed = None
        if not body.get("quiet"):
            pushed = await publish()
        return JSONResponse({"id": message_id, "history_id": world["history_id"],
                             "pushed": pushed})

    async def publish():
        """Gmail's note to the watched topic, and Pub/Sub's push of it."""
        watch = world["watch"]
        if not watch or watch["expires"] < time.time() or "INBOX" not in watch["labels"]:
            return None
        topic = world["topics"].get(watch["topic"]) or {}
        if not topic.get("push") or not topic.get("publisher"):
            return None
        data = json.dumps({"emailAddress": ACCOUNT_EMAIL,
                           "historyId": world["history_id"]}).encode()
        envelope = {
            "message": {"data": base64.b64encode(data).decode(),
                        "messageId": str(world["history_id"]),
                        "message_id": str(world["history_id"]),
                        "publishTime": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())},
            "subscription": watch["topic"].replace("/topics/", "/subscriptions/") + "-push",
        }
        try:
            async with httpx.AsyncClient(timeout=10.0) as http:
                answer = await http.post(topic["push"], json=envelope)
            status = answer.status_code
        except httpx.HTTPError as exc:
            status = type(exc).__name__
        world["pushes"].append({"at": time.time(), "history_id": world["history_id"],
                                "status": status})
        return status

    def changed(found: dict, added: list, removed: list) -> None:
        """A message's labels changed: Gmail writes it in the mailbox's history.

        One record each for what was added and what was taken off, as Gmail's
        `labelsAdded` and `labelsRemoved`, carrying the message's labels after."""
        added = [one for one in added if one]
        removed = [one for one in removed if one]
        for kind, which in (("labelsAdded", added), ("labelsRemoved", removed)):
            if which:
                world["history_id"] += 7
                world["history"].append({"id": world["history_id"], "message_id": found["id"],
                                         "labels": list(found["labels"]), "kind": kind,
                                         "changed": list(which)})

    @app.post("/_purge")
    async def purge(request: Request):
        """A message deleted forever, as the person deleting it from the Bin does, or
        Gmail emptying the Bin after thirty days. Gone from every listing, and a
        `messagesDeleted` record in the history. `{"id": ...}`."""
        body = await request.json()
        found = next((m for m in world["messages"] if m["id"] == body.get("id")), None)
        if found is None:
            return JSONResponse({"error": "no such message"}, status_code=404)
        world["messages"] = [m for m in world["messages"] if m is not found]
        world["history_id"] += 7
        world["history"].append({"id": world["history_id"], "message_id": found["id"],
                                 "labels": list(found["labels"]), "kind": "messagesDeleted"})
        note("message deleted forever", {"id": found["id"]})
        return JSONResponse({"id": found["id"], "history_id": world["history_id"]})

    @app.post("/_forget_history")
    async def forget_history():
        """Gmail stops answering for history older than now, as after a long gap."""
        world["history_floor"] = world["history_id"]
        return JSONResponse({"history_floor": world["history_floor"]})

    @app.post("/_grant")
    async def grant(request: Request):
        """What the next Allow hands back. A shorter list is an older consent."""
        body = await request.json()
        world["grant"] = list(body.get("scopes") or ALL_SCOPES)
        return JSONResponse({"grant": world["grant"]})

    @app.post("/_calendar_expire")
    async def calendar_expire():
        """The next sync token is refused with Google's 410, as Google does when it has forgotten one."""
        world["expire_sync_tokens"] = True
        return JSONResponse({"ok": True})

    @app.post("/_calendar")
    async def calendar_on_the_list(request: Request):
        """Put a calendar of the account's own on its list, such as a "Bdays"
        one of birthdays (`rouh/birthdays.py`): {"id", "summary"}. Events go on
        it with the usual POST."""
        body = await request.json()
        made = {"id": str(body.get("id") or made_up("cal") + "@group.calendar.google.com"),
                "summary": str(body.get("summary") or "Calendar"),
                "accessRole": str(body.get("accessRole") or "owner"),
                "timeZone": CALENDAR_ZONE}
        if body.get("dataOwner"):
            # Who made it, as Google says of a secondary calendar: somebody
            # else's, shared with this account as owner, is the case
            # share_calendar must refuse.
            made["dataOwner"] = str(body["dataOwner"])
        world["calendars"] = [one for one in world["calendars"] if one["id"] != made["id"]]
        world["calendars"].append(made)
        return JSONResponse(made)

    @app.post("/_calendar_event")
    async def calendar_event_as_given(request: Request):
        """Put one event on a calendar exactly as given, status and all:
        {"calendar", "event"}. A deleted event on its organiser's calendar is
        `"status": "cancelled"` with every detail kept, which is how Google
        holds one that can be restored, and what `restore_calendar_event` is
        proved against. An event with that id already there is replaced."""
        body = await request.json()
        calendar_id = str(body.get("calendar") or ACCOUNT_EMAIL)
        event = dict(body.get("event") or {})
        event.setdefault("id", made_up("ev"))
        event.setdefault("status", "confirmed")
        event.setdefault("htmlLink", f"https://www.google.com/calendar/event?eid={event['id']}")
        on = world["events"].setdefault(calendar_id, [])
        on[:] = [one for one in on if one["id"] != event["id"]] + [event]
        return JSONResponse(event)

    return changed
