"""Readonly registration for the Google stand-in."""
from __future__ import annotations

from typing import TYPE_CHECKING

from . import (
    READ_ONLY_ACCOUNTS,
    JSONResponse,
    Request,
    _raw_answer,
    _raw_attachment,
    _raw_delivered,
    _read_only_account,
    _read_only_full,
    _read_only_matches,
    _read_rfc2822,
    base64,
    time,
    urllib,
)

if TYPE_CHECKING:
    from fastapi import FastAPI


def _read_only_routes(app: FastAPI, world: dict, seen: dict) -> None:
    """Gmail for a read-only token: its own mailbox, read, and every write refused.

    In front of every other route, so a read-only token can never reach the
    connected account's mailbox, and a write made with one is refused with
    Google's own reason and written down in `/_seen` as `read_only_refused`.
    """

    @app.post("/_read_only_grant")
    async def read_only_grant(request: Request):
        """`{"extra": [scopes]}` widens what the next read-only Allow hands back;
        `{"withdraw": "work"}` withdraws an account's grant, as Google does when a
        person removes Rouh from their account."""
        body = await request.json()
        if "extra" in body:
            world["ro_extra"] = list(body.get("extra") or [])
        if body.get("withdraw"):
            world["ro_withdrawn"].add(str(body["withdraw"]))
        return JSONResponse({"extra": world["ro_extra"],
                             "withdrawn": sorted(world["ro_withdrawn"])})

    @app.post("/_read_only_deliver")
    async def read_only_deliver(request: Request):
        """`{"account": "work", "thread": "work-t1", "from": ..., "text": ...}`: a reply lands,
        unread in the inbox, as new mail does; `"html"` gives it only an HTML body,
        `"days_ago"` dates it back, and `"labels"` adds any beside INBOX and UNREAD,
        such as `CATEGORY_UPDATES` for one that lands in the Updates tab."""
        body = await request.json()
        raw = _raw_delivered(body)
        account = str(body.get("account") or "work")
        world["next_id"] += 1
        ident = f"{account}-new-{world['next_id']}"
        world["ro_mail"][account].append({
            "id": ident, "thread_id": str(body.get("thread") or "thread-" + ident),
            "from": str(body.get("from") or "Somebody <somebody@example.test>"),
            "to": READ_ONLY_ACCOUNTS[account]["email"], "cc": "",
            "subject": str(body.get("subject") or "Re:"), "text": str(body.get("text") or ""),
            "at": time.time() - float(body.get("days_ago") or 0) * 86400,
            "labels": ["INBOX", "UNREAD"] + [str(one) for one in body.get("labels") or []],
            "message_id": f"<{ident}@mail.test>",
            **({"html": str(body["html"])} if body.get("html") else {}),
            # Files and pictures drawn inside, as `/_deliver` takes them:
            # {"name", "type", "data": base64}, a picture with its "cid".
            "files": [dict(one, data=base64.b64decode(one["data"]))
                      for one in body.get("files") or []],
            "inline": [dict(one, data=base64.b64decode(one["data"]))
                       for one in body.get("inline") or []],
            **({"raw": raw} if raw else {})})
        if body.get("cc"):
            world["ro_mail"][account][-1]["cc"] = str(body["cc"])
        if body.get("to"):
            world["ro_mail"][account][-1]["to"] = str(body["to"])
        # Written in the mailbox's history, which a read-only grant can read as well.
        world["history_id"] += 7
        world["ro_history"].setdefault(account, []).append(
            {"id": world["history_id"], "message_id": ident,
             "labels": list(world["ro_mail"][account][-1]["labels"])})
        return JSONResponse({"id": ident})

    @app.middleware("http")
    async def read_only_gmail(request: Request, call_next):
        account = _read_only_account(request)
        if not account or not request.url.path.startswith("/gmail/"):
            return await call_next(request)
        seen["read_only_api"].append({"account": account, "method": request.method,
                                      "url": str(request.url)})
        if account in world["ro_withdrawn"]:
            return JSONResponse({"error": {"code": 401, "message": "Invalid Credentials"}},
                                status_code=401)
        sends = "https://www.googleapis.com/auth/gmail.send" in world["ro_scopes"].get(
            account, [])
        if (request.method == "POST" and sends
                and request.url.path == "/gmail/v1/users/me/messages/send"):
            # A mailbox the person allowed to forward from: it sends, as them,
            # and keeps what it sent in its own Sent, as Gmail does.
            body = await request.json()
            wrote = _read_rfc2822(body.get("raw") or "")
            world["next_id"] += 1
            wrote["id"] = f"{account}-sent-{world['next_id']}"
            wrote["threadId"] = body.get("threadId") or ""
            wrote["sent_as"] = READ_ONLY_ACCOUNTS[account]["email"]
            world["sent"].append(wrote)
            seen.setdefault("read_only_sent", []).append(
                {"account": account, "to": wrote["to"], "subject": wrote["subject"],
                 "id": wrote["id"]})
            world["ro_mail"][account].append({
                "id": wrote["id"], "thread_id": "thread-" + wrote["id"],
                "from": READ_ONLY_ACCOUNTS[account]["email"], "to": wrote["to"],
                "cc": wrote.get("cc") or "", "subject": wrote["subject"],
                "text": wrote.get("body") or "", "at": time.time(), "labels": ["SENT"],
                "message_id": f"<{wrote['id']}@mail.test>"})
            return JSONResponse({"id": wrote["id"], "threadId": "thread-" + wrote["id"],
                                 "labelIds": ["SENT"]})
        if request.method != "GET":
            seen["read_only_refused"].append({"account": account, "method": request.method,
                                              "path": request.url.path})
            return JSONResponse({"error": {
                "code": 403, "message": "Request had insufficient authentication scopes.",
                "details": [{"reason": "ACCESS_TOKEN_SCOPE_INSUFFICIENT"}]}}, status_code=403)
        mail = world["ro_mail"][account]
        who = READ_ONLY_ACCOUNTS[account]
        path = request.url.path.removeprefix("/gmail/v1/users/me")
        if path == "/profile":
            return JSONResponse({"emailAddress": who["email"], "messagesTotal": len(mail),
                                 "historyId": str(world["history_id"])})
        if path == "/drafts":
            return JSONResponse({"drafts": []})
        if path == "/labels":
            return JSONResponse({"labels": [{"id": x, "name": x} for x in
                                            ("INBOX", "SENT", "UNREAD", "SPAM", "TRASH")]})
        if path == "/history":
            try:
                start = int(request.query_params.get("startHistoryId") or "")
            except ValueError:
                return JSONResponse({"error": {"code": 400, "message": "Invalid startHistoryId"}},
                                    status_code=400)
            return JSONResponse({"history": [
                {"id": str(one["id"]), "messagesAdded": [{"message": {
                    "id": one["message_id"], "labelIds": one["labels"]}}]}
                for one in world["ro_history"].get(account, []) if one["id"] > start],
                "historyId": str(world["history_id"])})
        if path == "/settings/sendAs":
            return JSONResponse({"sendAs": [{"sendAsEmail": who["email"], "isPrimary": True}]
                                 + [{"sendAsEmail": one} for one in who["aliases"]]})
        if path == "/labels/INBOX":
            return JSONResponse({"id": "INBOX", "messagesUnread": sum(
                1 for m in mail if "INBOX" in m["labels"] and "UNREAD" in m["labels"]),
                "messagesTotal": sum(1 for m in mail if "INBOX" in m["labels"])})
        if path == "/messages":
            query = request.query_params.get("q", "")
            most = int(request.query_params.get("maxResults") or 100)
            found = sorted((m for m in mail if _read_only_matches(m, query)),
                           key=lambda m: -m["at"])[:most]
            return JSONResponse({"messages": [{"id": m["id"], "threadId": m["thread_id"]}
                                              for m in found]})
        if path.startswith("/messages/"):
            found = next((m for m in mail if m["id"] == path.split("/")[2]), None)
            if found is None:
                return JSONResponse({"error": {"code": 404, "message": "Not Found"}},
                                    status_code=404)
            if "/attachments/" in path:
                wanted = path.rsplit("/", 1)[1]
                held = _raw_attachment(found, wanted)
                if held is not None:
                    return held
                for kind, prefix in (("inline", "inl"), ("files", "att")):
                    for n, one in enumerate(found.get(kind) or []):
                        if f"{prefix}-{found['id']}-{n}" == wanted:
                            data = base64.urlsafe_b64encode(one["data"]).decode().rstrip("=")
                            return JSONResponse({"size": len(one["data"]), "data": data})
                return JSONResponse({"error": {"code": 404, "message": "Not Found"}},
                                    status_code=404)
            if request.query_params.get("format") == "raw":
                return _raw_answer(found, found["thread_id"])
            if request.query_params.get("format") == "minimal":
                return JSONResponse({"id": found["id"], "threadId": found["thread_id"],
                                     "labelIds": found["labels"]})
            return JSONResponse(_read_only_full(found))
        if path.startswith("/threads/"):
            thread = urllib.parse.unquote(path.split("/")[2])
            held = sorted((m for m in mail if m["thread_id"] == thread), key=lambda m: m["at"])
            if not held:
                return JSONResponse({"error": {"code": 404, "message": "Not Found"}},
                                    status_code=404)
            return JSONResponse({"id": thread, "messages": [_read_only_full(m) for m in held]})
        return JSONResponse({"error": {"code": 404, "message": "Not Found"}}, status_code=404)
