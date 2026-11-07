"""A stand-in for the meeting library (task 67), so Synapse's meeting sync can be driven for
real in a test world with nothing reaching the network (`rouh/synapse/meetings.py`).

A real HTTP server speaking the library's half of the contract the two were built to, in the shapes the
library has as built and installed (task 67-08's "sync contract as built and installed"):

- `GET /api/v1/changes?since=<seq>&limit=<n>`: `{"changes": [{seq, meeting_id, revision, state, changed_at}],
  "next_since", "more"}`, every change in order, one per revision.
- `GET /api/v1/meetings/<id>`: one meeting whole: revision, state, title, started_at, ended_at, language,
  category (`{name, set_by, sure}`), calendar_event_id, ical_uid, meeting_url, participants (`{name, email,
  outside, side, attended: took_part or invited}`), readers (`{"emails": [...], "administrators": true}`),
  summary, summary_long, decisions, action_items, speakers (`[{label, name, email, outside, confirmed}]`) and
  segments (`{segment_id, speaker: the label, start_ms, end_ms, text}`). A withdrawn one keeps its keys and
  loses its content.
- Every one of them wants the library's key, `Authorization: Bearer <KEY>`, and answers 401 without it; the
  list of meetings answers the key 401 too, as the real library answers a service key.
- On every change it posts the signed webhook `meeting.changed` `{event, meeting_id, revision, state, seq,
  sent_at}` to the address it was given, with `X-Library-Signature: sha256=<HMAC-SHA256 of the raw body>`,
  `X-Library-Timestamp: <unix seconds>` and `X-Library-Event`, the way the real library does.

What only a stand-in has, to drive it from outside:

- `POST /_hook {"url", "secret"}` says where the webhooks go.
- `POST /_meeting {...}` makes a meeting, or replaces one with the same id, as one change: a new revision.
- `POST /_meeting/<id>/edit {...}` changes one: fields given replace the meeting's (`readers`, `participants`,
  `summary`, `decisions`, ...), `segments_text: {segment_id: text}` corrects lines of the transcript,
  `speakers: {label: {name, email, confirmed}}` names, renames or un-names a speaker. One change, one revision.
- `POST /_meeting/<id>/withdraw` withdraws it. `/_meeting/<id>/processing` marks it being worked on.
- Any of them with `"webhook": false` makes the change without sending its webhook (a missed webhook).
- `GET /_last_webhook` is the last one sent, body and headers, so a test can send it again (a replay);
  `GET /_state` counts the requests by path and lists every meeting's revision and state.

    python -m rouh.testing.fake_meeting_library --port 8097 --key ml_test
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import threading
import time
from datetime import datetime, timezone

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

KEY = "ml_test-key-not-a-real-one"
SECRET = "whsec-test-not-a-real-one"


def build_app(key: str) -> FastAPI:
    app = FastAPI()
    lock = threading.Lock()
    state = {"meetings": {}, "changes": [], "hook": {"url": "", "secret": ""}, "requests": {}, "last_webhook": None,
             "webhooks": []}

    def counted(path: str) -> None:
        state["requests"][path] = state["requests"].get(path, 0) + 1

    def keyed(request: Request):
        if request.headers.get("authorization") != f"Bearer {key}":
            return JSONResponse(status_code=401, content={"error": "Sign in, or send a key: Authorization: Bearer ml_..."})
        return None

    def now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def change(m: dict) -> dict:
        """One change: the meeting's revision up by one, written to the change list."""
        m["revision"] = int(m.get("revision") or 0) + 1
        seq = len(state["changes"]) + 1
        c = {"seq": seq, "meeting_id": m["id"], "revision": m["revision"], "state": m["state"], "changed_at": now()}
        state["changes"].append(c)
        return c

    async def hook(c: dict) -> None:
        url, secret = state["hook"]["url"], state["hook"]["secret"]
        if not url:
            return
        sent = int(time.time())
        body = json.dumps({"event": "meeting.changed", "meeting_id": c["meeting_id"], "revision": c["revision"],
                           "state": c["state"], "seq": c["seq"], "sent_at": sent}).encode()
        headers = {"Content-Type": "application/json", "X-Library-Timestamp": str(sent),
                   "X-Library-Event": "meeting.changed",
                   "X-Library-Signature": "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()}
        state["last_webhook"] = {"body": body.decode(), "headers": headers}
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                r = await client.post(url, content=body, headers=headers)
            state["webhooks"].append({"seq": c["seq"], "status": r.status_code})
        except httpx.HTTPError as exc:
            state["webhooks"].append({"seq": c["seq"], "error": str(exc)})

    def public(m: dict) -> dict:
        return {k: v for k, v in m.items() if not k.startswith("_")}

    @app.get("/_state")
    async def _state():
        return {"requests": state["requests"], "changes": len(state["changes"]), "webhooks": state["webhooks"][-20:],
                "meetings": {i: {"revision": m["revision"], "state": m["state"], "title": m["title"]}
                             for i, m in state["meetings"].items()}}

    @app.get("/_last_webhook")
    async def _last():
        return state["last_webhook"] or {}

    @app.post("/_hook")
    async def _hook(request: Request):
        got = await request.json()
        state["hook"] = {"url": str(got.get("url") or ""), "secret": str(got.get("secret") or "")}
        return {"ok": True}

    @app.post("/_meeting")
    async def _meeting(request: Request):
        got = await request.json()
        send = got.pop("webhook", True) is not False
        with lock:
            mid = str(got.get("id") or len(state["meetings"]) + 1)
            had = state["meetings"].get(mid) or {}
            m = {"id": mid, "state": "ready", "title": "", "started_at": None, "ended_at": None, "language": None,
                 "category": None, "calendar_event_id": None, "ical_uid": None, "meeting_url": None, "participants": [],
                 "readers": {"emails": [], "administrators": True}, "summary": "", "summary_long": "",
                 "next_meeting": "", "decisions": [], "action_items": [], "speakers": [], "segments": [], **got,
                 "revision": had.get("revision", 0)}
            m["id"] = mid
            state["meetings"][mid] = m
            c = change(m)
        if send:
            await hook(c)
        return {"ok": True, "meeting": public(m), "change": c}

    @app.post("/_meeting/{mid}/{what}")
    async def _edit(mid: str, what: str, request: Request):
        try:
            got = await request.json()
        except ValueError:
            got = {}
        send = got.pop("webhook", True) is not False
        with lock:
            m = state["meetings"].get(mid)
            if m is None:
                return JSONResponse(status_code=404, content={"error": "no such meeting"})
            if what == "withdraw":
                m["state"] = "withdrawn"
            elif what == "processing":
                m["state"] = "processing"
            elif what == "ready":
                m["state"] = "ready"
            elif what == "edit":
                for seg_id, text in (got.pop("segments_text", None) or {}).items():
                    for s in m["segments"]:
                        if str(s["segment_id"]) == str(seg_id):
                            s["text"] = text
                for label, person in (got.pop("speakers", None) or {}).items():
                    m["speakers"] = [s for s in m["speakers"] if s["label"] != label] + [
                        {"label": label, "name": None, "email": None, "outside": False, "confirmed": False,
                         **(person or {})}]
                    m["speakers"].sort(key=lambda s: s["label"])
                m.update(got)
            else:
                return JSONResponse(status_code=404, content={"error": f"no {what}"})
            c = change(m)
        if send:
            await hook(c)
        return {"ok": True, "meeting": public(m), "change": c}

    @app.get("/api/v1/changes")
    async def changes(request: Request, since: int = 0, limit: int = 100):
        counted("/api/v1/changes")
        refused = keyed(request)
        if refused:
            return refused
        limit = max(1, min(1000, limit))
        after = [c for c in state["changes"] if c["seq"] > since]
        got = after[:limit]
        return {"changes": got, "next_since": got[-1]["seq"] if got else since, "more": len(after) > limit}

    @app.get("/api/v1/meetings")
    async def meetings(request: Request, offset: int = 0, limit: int = 50):
        counted("/api/v1/meetings")
        # The library's service key reads only the changes and one meeting at a time.
        return JSONResponse(status_code=401, content={"error": "This key reads only the changes and one meeting."})

    @app.get("/api/v1/meetings/{mid}")
    async def meeting(mid: str, request: Request):
        counted("/api/v1/meetings/<id>")
        refused = keyed(request)
        if refused:
            return refused
        m = state["meetings"].get(mid)
        if m is None:
            return JSONResponse(status_code=404, content={"error": "There is no meeting with that id that you can see."})
        if m["state"] == "withdrawn":
            # Every key kept, the content gone, as the real library answers its service key.
            return {**public(m), "segments": [], "speakers": [], "decisions": [], "action_items": [], "summary": "",
                    "summary_long": "", "readers": {"emails": [], "administrators": True}}
        return public(m)

    return app


def main() -> None:
    import uvicorn

    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--key", default=KEY)
    args = ap.parse_args()
    uvicorn.run(build_app(args.key), host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
