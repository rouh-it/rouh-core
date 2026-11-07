"""A stand-in for Slack, so Rouh's Slack app can be driven end to end with nothing real.

The same idea as `fake_cloudflare.py` and `fake_telegram.py`: a real HTTP server in front of the
real client (`rouh/slack.py`, `rouh/slack_listen.py`), so what a check proves is what went over the
wire. It speaks enough of Slack, in Slack's own shapes:

- the Web API, ``POST /api/<method>`` with ``Authorization: Bearer <token>``: ``auth.test`` (with
  the ``x-oauth-scopes`` header), ``apps.connections.open``, ``conversations.list``, ``.info``,
  ``.history``, ``.replies``, ``.members``, ``.join`` and ``.open``, ``chat.postMessage`` and ``users.info``;
  each answers ``{"ok": false, "error": ...}`` exactly where Slack does - ``not_in_channel`` for
  the bot outside a channel, ``missing_scope`` for the person's own token anywhere but their own
  direct messages, ``channel_not_found`` for a conversation the token cannot see at all;
- Socket Mode, a websocket at the address ``apps.connections.open`` gives: ``hello`` first, then
  an ``events_api`` envelope for each event, each waiting for its ``{"envelope_id"}``
  acknowledgement; and ``disconnect`` when asked.

The workspace is `TEAM`, with Alex, Sam, Jordan and Bob (`PEOPLE`), the bot Rouh, a public
#general Rouh is in, a public #pricing it is in too, a public #random it is not, a private #board it is in, Rouh's direct messages
with Alex and Sam, Alex's own with Sam and with Jordan, and Sam's with Jordan, which nobody
connected can see. Some of #general is between 30 and 90 days old (read back over 90 days, never over
30), one message is older than 90 days and is never read back, and two messages start a thread, one
of them 50 days ago.

The tokens it knows are `TOKENS`; any other is ``invalid_auth``.

Knobs, each a POST with JSON:

- ``/_say {"user", "channel", "text", "thread_ts"?, "files"?}``: somebody writes; the event goes to
  every socket that may see it (the bot's events, or the owner's own, Alex's, for their direct messages).
- ``/_edit {"channel", "ts", "text"}`` and ``/_delete {"channel", "ts"}``.
- ``/_react {"user", "channel", "ts", "name"?}``: somebody reacts to a message, which
  ``conversations.history`` and ``.replies`` then give in its ``reactions``, as Slack does. No event:
  Rouh's app is not subscribed to reactions.
- ``/_invite {"channel"}``: Rouh is added to a channel (``member_joined_channel``).
- ``/_create {"name"}``: a new public channel (``channel_created``).
- ``/_disconnect``: Slack asks every socket for a new one.
- ``/_ratelimit {"method", "times", "after"}``: the next ``times`` calls of a method answer 429
  with ``Retry-After: <after>``.

And ``GET /_calls`` (every call, with the token's last four only), ``/_posted`` (what was posted
with ``chat.postMessage``), ``/_acks`` (acknowledged envelope ids), ``/_sockets``.

Point ``ROUH_SLACK_API`` at ``http://127.0.0.1:<port>/api``.

    python -m rouh.testing.fake_slack --port 8099
"""
from __future__ import annotations

import argparse
import json
import time
import uuid

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

TEAM = {"id": "T0ROUHTEST", "name": "Rouh Test", "url": "https://rouh-test.slack.com/"}
BOT = {"user_id": "U0ROUHBOT", "bot_id": "B0ROUHBOT", "name": "rouh"}
OWNER = "U0ALEX"
PEOPLE = {
    OWNER: {"name": "alex", "real_name": "Alex Morgan", "email": "alex@example.com"},
    "U0SAM": {"name": "sam", "real_name": "Sam Rivera", "email": "sam@example.org"},
    "U0JORDAN": {"name": "jordan", "real_name": "Jordan Lee", "email": "jordan@example.net"},
    "U0BOB": {"name": "bob", "real_name": "Bob Stranger", "email": "bob@example.net"},
    BOT["user_id"]: {"name": "rouh", "real_name": "Rouh", "email": "", "is_bot": True},
}

BOT_SCOPES = ["channels:read", "channels:history", "channels:join", "groups:read", "groups:history",
              "im:read", "im:history", "im:write", "mpim:read", "mpim:history", "chat:write", "users:read",
              "users:read.email", "reactions:read", "files:read", "app_mentions:read"]
USER_SCOPES = ["im:read", "im:history", "mpim:read", "mpim:history", "users:read"]
#: What Slack adds to every user token by itself, and says in its x-oauth-scopes.
IMPLICIT_USER_SCOPES = ["identify"]
#: Every token the stand-in accepts.
TOKENS = {
    "xoxb-1000-stand-in-bot-token-aaaa": {"kind": "bot", "scopes": BOT_SCOPES},
    "xoxb-1000-stand-in-bot-no-email-bbbb": {"kind": "bot",
                                             "scopes": [s for s in BOT_SCOPES if s != "users:read.email"]},
    "xoxp-1000-stand-in-owner-reads-cccc": {"kind": "user", "user": OWNER, "scopes": USER_SCOPES + IMPLICIT_USER_SCOPES},
    "xoxp-1000-stand-in-owner-writes-dddd": {"kind": "user", "user": OWNER,
                                             "scopes": USER_SCOPES + IMPLICIT_USER_SCOPES + ["chat:write"]},
    "xapp-1-A0ROUH-1000-stand-in-app-eeee": {"kind": "app"},
}

DAY = 86400.0


def _conversations(now: float) -> dict:
    return {
        "C0GENERAL": {"id": "C0GENERAL", "name": "general", "kind": "channel", "members": {OWNER, "U0SAM", "U0JORDAN",
                                                                                           BOT["user_id"]},
                      "topic": "Everything", "created": now - 400 * DAY},
        "C0PRICING": {"id": "C0PRICING", "name": "pricing", "kind": "channel",
                      "members": {OWNER, "U0SAM", "U0JORDAN", BOT["user_id"]},
                      "topic": "What we charge", "created": now - 60 * DAY},
        "C0RANDOM": {"id": "C0RANDOM", "name": "random", "kind": "channel", "members": {OWNER, "U0BOB"},
                     "topic": "", "created": now - 400 * DAY},
        "G0BOARD": {"id": "G0BOARD", "name": "board", "kind": "group", "members": {OWNER, "U0JORDAN", BOT["user_id"]},
                    "topic": "Board only", "created": now - 300 * DAY},
        "D0ROUHALEX": {"id": "D0ROUHALEX", "kind": "im", "members": {OWNER, BOT["user_id"]}},
        "D0ROUHSAM": {"id": "D0ROUHSAM", "kind": "im", "members": {"U0SAM", BOT["user_id"]}},
        "D0ALEXSAM": {"id": "D0ALEXSAM", "kind": "im", "members": {OWNER, "U0SAM"}},
        "D0ALEXJORDAN": {"id": "D0ALEXJORDAN", "kind": "im", "members": {OWNER, "U0JORDAN"}},
        "D0SAMJORDAN": {"id": "D0SAMJORDAN", "kind": "im", "members": {"U0SAM", "U0JORDAN"}},
        "G0MPIM": {"id": "G0MPIM", "name": "mpdm-alex--sam--jordan-1", "kind": "mpim",
                   "members": {OWNER, "U0SAM", "U0JORDAN"}},
    }


def _ts(at: float, n: int = 0) -> str:
    return f"{at:.0f}.{n:06d}"


def _history(now: float) -> dict:
    def m(user, at, text, n=0, **more):
        return {"type": "message", "user": user, "ts": _ts(at, n), "text": text, "team": TEAM["id"], **more}

    thread = _ts(now - 3 * DAY, 1)
    old_thread = _ts(now - 50 * DAY, 7)
    return {
        "C0GENERAL": [
            m("U0SAM", now - 120 * DAY, "This is older than ninety days and is never read back."),
            m("U0SAM", now - 40 * DAY, "Forty days ago: read back over 90 days, never over 30."),
            {**m("U0JORDAN", now - 50 * DAY, "Fifty days ago: who signs the Porto contract?", 7),
             "thread_ts": old_thread, "reply_count": 1},
            {**m(OWNER, now - 49 * DAY, "I sign it, on Monday.", 8), "thread_ts": old_thread},
            m(OWNER, now - 5 * DAY, "Welcome to <#C0GENERAL|general>, <@U0JORDAN>!"),
            {**m("U0JORDAN", now - 3 * DAY, "Launch plan for the Lisbon office: who owns the lease?", 1),
             "thread_ts": thread, "reply_count": 2},
            {**m("U0SAM", now - 3 * DAY + 60, "I do. Signing on Friday.", 2), "thread_ts": thread},
            {**m(OWNER, now - 3 * DAY + 120, "Good, send me the draft <https://example.com/lease|lease>.", 3),
             "thread_ts": thread},
            {**m("U0JORDAN", now - 2 * DAY, "Deck attached", 4, subtype="file_share"),
             "files": [{"name": "q4-deck.pdf", "title": "Q4 deck"}]},
            m("U0JORDAN", now - 2 * DAY + 30, "", 5, subtype="channel_join"),
        ],
        "C0PRICING": [m("U0SAM", now - 1 * DAY, "Should we drop the monthly plan and sell annual only?")],
        "C0RANDOM": [m("U0BOB", now - 1 * DAY, "Rouh is not in here and never reads this.")],
        "G0BOARD": [m("U0JORDAN", now - 4 * DAY, "Board pack for October is in the drive.")],
        "D0ROUHALEX": [m(OWNER, now - 6 * DAY, "Hello Rouh"),
                        {**m(BOT["user_id"], now - 6 * DAY + 5, "Hello Alex", 1), "bot_id": BOT["bot_id"]}],
        "D0ROUHSAM": [],
        "D0ALEXSAM": [m("U0SAM", now - 2 * DAY, "Alex, private: my salary ask is 5000."),
                         m(OWNER, now - 2 * DAY + 90, "Noted, between us.", 1)],
        "D0ALEXJORDAN": [m("U0JORDAN", now - 1 * DAY, "Can we talk tomorrow?")],
        "D0SAMJORDAN": [m("U0SAM", now - 1 * DAY, "Nobody but Jordan and me can read this.")],
        "G0MPIM": [m("U0JORDAN", now - 1 * DAY, "Dinner on Thursday?")],
    }


app = FastAPI()
NOW = time.time()
CONVS = _conversations(NOW)
MESSAGES = _history(NOW)
CALLS: list[dict] = []
POSTED: list[dict] = []
ACKS: list[str] = []
SOCKETS: list[dict] = []
LIMITS: dict[str, dict] = {}
TICKETS: set[str] = set()
PORT = {"n": 0}
_COUNTER = {"n": 100}


def _next_ts() -> str:
    _COUNTER["n"] += 1
    return _ts(time.time(), _COUNTER["n"])


def _err(error: str, status: int = 200, **more):
    return JSONResponse({"ok": False, "error": error, **more}, status_code=status)


def _ok(scopes=None, **body):
    headers = {"x-oauth-scopes": ",".join(scopes)} if scopes is not None else {}
    return JSONResponse({"ok": True, **body}, headers=headers)


def _info(c: dict, who: dict) -> dict:
    kind = c["kind"]
    out = {"id": c["id"], "created": int(c.get("created") or NOW), "is_archived": False,
           "is_channel": kind == "channel", "is_group": kind == "group", "is_im": kind == "im",
           "is_mpim": kind == "mpim", "is_private": kind in ("group", "im", "mpim")}
    if kind in ("channel", "group", "mpim"):
        out["name"] = c["name"]
        out["topic"] = {"value": c.get("topic", "")}
        out["is_member"] = _me(who) in c["members"]
    if kind == "im":
        others = [u for u in c["members"] if u != _me(who)]
        out["user"] = others[0] if others else _me(who)
    return out


def _me(who: dict) -> str:
    return BOT["user_id"] if who["kind"] == "bot" else who.get("user", "")


def _sees(who: dict, c: dict, *, read: bool) -> str:
    """"" when this token may see (or, with read, read) the conversation, else Slack's error."""
    me = _me(who)
    if who["kind"] == "user":
        if c["kind"] not in ("im", "mpim"):
            return "missing_scope"
        return "" if me in c["members"] else "channel_not_found"
    if c["kind"] == "channel":
        return "" if (not read or me in c["members"]) else "not_in_channel"
    return "" if me in c["members"] else "channel_not_found"


async def _form(request: Request) -> dict:
    try:
        form = await request.form()
        got = {k: str(v) for k, v in form.items()}
    except Exception:  # noqa: BLE001
        got = {}
    got.update({k: v for k, v in request.query_params.items()})
    return got


@app.api_route("/api/{method}", methods=["GET", "POST"])
async def api(method: str, request: Request):
    args = await _form(request)
    auth = request.headers.get("authorization", "")
    token = auth[7:] if auth.lower().startswith("bearer ") else args.get("token", "")
    CALLS.append({"at": time.time(), "method": method, "token": token[-4:], "args":
                  {k: v for k, v in args.items() if k != "token"}})
    limit = LIMITS.get(method)
    if limit and limit["times"] > 0:
        limit["times"] -= 1
        CALLS[-1]["answered"] = 429
        return JSONResponse({"ok": False, "error": "ratelimited"}, status_code=429,
                            headers={"Retry-After": str(limit["after"])})
    who = TOKENS.get(token)
    if who is None:
        return _err("invalid_auth" if token else "not_authed")
    scopes = who.get("scopes")
    if method == "auth.test":
        if who["kind"] == "app":
            return _err("not_allowed_token_type")
        body = {"url": TEAM["url"], "team": TEAM["name"], "team_id": TEAM["id"]}
        if who["kind"] == "bot":
            body.update(user="rouh", user_id=BOT["user_id"], bot_id=BOT["bot_id"])
        else:
            body.update(user=PEOPLE[who["user"]]["name"], user_id=who["user"])
        return _ok(scopes, **body)
    if method == "apps.connections.open":
        if who["kind"] != "app":
            return _err("not_allowed_token_type")
        ticket = uuid.uuid4().hex
        TICKETS.add(ticket)
        return _ok(url=f"ws://{PORT.get('host', '127.0.0.1')}:{PORT['n']}/link/?ticket={ticket}")
    if who["kind"] == "app":
        return _err("not_allowed_token_type")
    if method == "users.info":
        uid = args.get("user", "")
        p = PEOPLE.get(uid)
        if p is None:
            return _err("user_not_found")
        profile = {"display_name": p["name"], "real_name": p["real_name"]}
        if "users:read.email" in (scopes or []) and p.get("email"):
            profile["email"] = p["email"]
        return _ok(scopes, user={"id": uid, "name": p["name"], "real_name": p["real_name"],
                                 "is_bot": bool(p.get("is_bot")), "deleted": False, "profile": profile})
    if method == "conversations.list":
        types = set((args.get("types") or "public_channel").split(","))
        kind_of = {"public_channel": "channel", "private_channel": "group", "im": "im", "mpim": "mpim"}
        want = {kind_of[t] for t in types if t in kind_of}
        if who["kind"] == "user" and want - {"im", "mpim"}:
            return _err("missing_scope", needed="channels:read")
        out = [_info(c, who) for c in CONVS.values() if c["kind"] in want and not _sees(who, c, read=False)]
        limit_n = int(args.get("limit") or 100)
        start = int(args.get("cursor") or 0)
        page = out[start:start + limit_n]
        nxt = str(start + limit_n) if start + limit_n < len(out) else ""
        return _ok(scopes, channels=page, response_metadata={"next_cursor": nxt})
    if method in ("conversations.info", "conversations.history", "conversations.replies", "conversations.join"):
        c = CONVS.get(args.get("channel", ""))
        if c is None:
            return _err("channel_not_found")
        if method == "conversations.join":
            if who["kind"] != "bot":
                return _err("missing_scope")
            if c["kind"] != "channel":
                return _err("method_not_supported_for_channel_type")
            c["members"].add(BOT["user_id"])
            return _ok(scopes, channel=_info(c, who))
        why = _sees(who, c, read=method != "conversations.info")
        if why:
            return _err(why)
        if method == "conversations.info":
            return _ok(scopes, channel=_info(c, who))
        oldest = float(args.get("oldest") or 0)
        msgs = MESSAGES.get(c["id"], [])
        if method == "conversations.history":
            top = [m for m in msgs if float(m["ts"]) > oldest and (not m.get("thread_ts") or m["thread_ts"] == m["ts"])]
        else:
            ts = args.get("ts", "")
            top = [m for m in msgs if m["ts"] == ts or m.get("thread_ts") == ts]
            top = [m for m in top if float(m["ts"]) > oldest or m["ts"] == ts]
            top.sort(key=lambda m: float(m["ts"]))
        if method == "conversations.history":
            top = sorted(top, key=lambda m: -float(m["ts"]))
        limit_n = int(args.get("limit") or 100)
        start = int(args.get("cursor") or 0)
        page = top[start:start + limit_n]
        nxt = str(start + limit_n) if start + limit_n < len(top) else ""
        return _ok(scopes, messages=page, has_more=bool(nxt), response_metadata={"next_cursor": nxt})
    if method == "conversations.members":
        c = CONVS.get(args.get("channel", ""))
        if c is None:
            return _err("channel_not_found")
        why = _sees(who, c, read=False)
        if why:
            return _err(why)
        everyone = sorted(c["members"])
        limit_n = int(args.get("limit") or 100)
        start = int(args.get("cursor") or 0)
        nxt = str(start + limit_n) if start + limit_n < len(everyone) else ""
        return _ok(scopes, members=everyone[start:start + limit_n], response_metadata={"next_cursor": nxt})
    if method == "conversations.open":
        if who["kind"] != "bot":
            return _err("missing_scope")
        users = [u for u in args.get("users", "").split(",") if u]
        if len(users) != 1 or users[0] not in PEOPLE:
            return _err("user_not_found")
        for c in CONVS.values():
            if c["kind"] == "im" and c["members"] == {users[0], BOT["user_id"]}:
                return _ok(scopes, channel={"id": c["id"]})
        cid = "D0ROUH" + users[0][2:]
        CONVS[cid] = {"id": cid, "kind": "im", "members": {users[0], BOT["user_id"]}}
        MESSAGES[cid] = []
        return _ok(scopes, channel={"id": cid})
    if method == "chat.postMessage":
        if who["kind"] != "bot" or "chat:write" not in (scopes or []):
            return _err("missing_scope")
        c = CONVS.get(args.get("channel", ""))
        if c is None:
            return _err("channel_not_found")
        if BOT["user_id"] not in c["members"]:
            return _err("not_in_channel")
        ts = _next_ts()
        m = {"type": "message", "user": BOT["user_id"], "bot_id": BOT["bot_id"], "ts": ts,
             "text": args.get("text", ""), "team": TEAM["id"],
             "bot_profile": {"user_id": BOT["user_id"], "name": "Rouh"}}
        if args.get("thread_ts"):
            m["thread_ts"] = args["thread_ts"]
            for parent in MESSAGES.get(c["id"], []):
                if parent["ts"] == args["thread_ts"]:
                    parent["thread_ts"] = parent["ts"]
                    parent["reply_count"] = int(parent.get("reply_count") or 0) + 1
        MESSAGES.setdefault(c["id"], []).append(m)
        POSTED.append({"at": time.time(), "channel": c["id"], "ts": ts, "text": m["text"],
                       "thread_ts": args.get("thread_ts", "")})
        await _deliver(c, {**m, "channel": c["id"], "channel_type": _channel_type(c)})
        return _ok(scopes, channel=c["id"], ts=ts, message=m)
    return _err("unknown_method")


def _channel_type(c: dict) -> str:
    return {"channel": "channel", "group": "group", "im": "im", "mpim": "mpim"}[c["kind"]]


def _who_sees(c: dict) -> list[dict]:
    """The authorizations Slack would name for an event in this conversation: the bot's, when it is
    in it; else the owner's own, for their own direct messages."""
    if BOT["user_id"] in c["members"]:
        return [{"team_id": TEAM["id"], "user_id": BOT["user_id"], "is_bot": True}]
    if c["kind"] in ("im", "mpim") and OWNER in c["members"]:
        return [{"team_id": TEAM["id"], "user_id": OWNER, "is_bot": False}]
    return []


async def _deliver(c: dict | None, event: dict, *, to_all: bool = False) -> int:
    """One event to every socket, as an events_api envelope, if anybody connected may see it."""
    auths = _who_sees(c) if c is not None else [{"team_id": TEAM["id"], "user_id": BOT["user_id"], "is_bot": True}]
    if not auths and not to_all:
        return 0
    payload = {"token": "verification", "team_id": TEAM["id"], "api_app_id": "A0ROUH", "event": event,
               "type": "event_callback", "event_id": "Ev" + uuid.uuid4().hex[:10].upper(),
               "event_time": int(time.time()), "authorizations": auths}
    sent = 0
    for s in list(SOCKETS):
        env = {"envelope_id": uuid.uuid4().hex, "type": "events_api", "payload": payload,
               "accepts_response_payload": False, "retry_attempt": 0, "retry_reason": ""}
        try:
            await s["ws"].send_text(json.dumps(env))
            sent += 1
        except Exception:  # noqa: BLE001
            pass
    return sent


@app.websocket("/link/")
async def link(ws: WebSocket):
    ticket = ws.query_params.get("ticket", "")
    if ticket not in TICKETS:
        await ws.close(code=4001)
        return
    TICKETS.discard(ticket)
    await ws.accept()
    me = {"ws": ws, "at": time.time()}
    SOCKETS.append(me)
    await ws.send_text(json.dumps({"type": "hello", "num_connections": len(SOCKETS),
                                   "connection_info": {"app_id": "A0ROUH"}}))
    try:
        while True:
            raw = await ws.receive_text()
            try:
                got = json.loads(raw)
            except ValueError:
                continue
            if got.get("envelope_id"):
                ACKS.append(got["envelope_id"])
    except WebSocketDisconnect:
        pass
    finally:
        if me in SOCKETS:
            SOCKETS.remove(me)


# --- knobs ------------------------------------------------------------------------------------


@app.post("/_say")
async def say(request: Request):
    body = await request.json()
    c = CONVS.get(body.get("channel", ""))
    user = body.get("user", "")
    if c is None or user not in PEOPLE:
        return _err("no such channel or person")
    ts = _next_ts()
    m = {"type": "message", "user": user, "ts": ts, "text": body.get("text", ""), "team": TEAM["id"]}
    if body.get("thread_ts"):
        m["thread_ts"] = body["thread_ts"]
    if body.get("files"):
        m["subtype"] = "file_share"
        m["files"] = [{"name": n} for n in body["files"]]
    MESSAGES.setdefault(c["id"], []).append(m)
    sent = await _deliver(c, {**m, "channel": c["id"], "channel_type": _channel_type(c), "event_ts": ts})
    if "<@" + BOT["user_id"] in m["text"] and BOT["user_id"] in c["members"]:
        await _deliver(c, {"type": "app_mention", "user": user, "text": m["text"], "ts": ts, "channel": c["id"],
                           "event_ts": ts, **({"thread_ts": m["thread_ts"]} if m.get("thread_ts") else {})})
    return {"ok": True, "ts": ts, "delivered": sent}


@app.post("/_edit")
async def edit(request: Request):
    body = await request.json()
    c = CONVS.get(body.get("channel", ""))
    for m in MESSAGES.get(body.get("channel", ""), []):
        if m["ts"] == body.get("ts"):
            before = dict(m)
            m["text"] = body.get("text", "")
            m["edited"] = {"user": m.get("user"), "ts": _next_ts()}
            sent = await _deliver(c, {"type": "message", "subtype": "message_changed", "hidden": True,
                                      "channel": c["id"], "channel_type": _channel_type(c), "message": dict(m),
                                      "previous_message": before, "ts": _next_ts()})
            return {"ok": True, "delivered": sent}
    return _err("message_not_found")


@app.post("/_delete")
async def delete(request: Request):
    body = await request.json()
    c = CONVS.get(body.get("channel", ""))
    msgs = MESSAGES.get(body.get("channel", ""), [])
    for m in list(msgs):
        if m["ts"] == body.get("ts"):
            msgs.remove(m)
            sent = await _deliver(c, {"type": "message", "subtype": "message_deleted", "hidden": True,
                                      "channel": c["id"], "channel_type": _channel_type(c),
                                      "deleted_ts": m["ts"], "previous_message": m, "ts": _next_ts()})
            return {"ok": True, "delivered": sent}
    return _err("message_not_found")


@app.post("/_react")
async def react(request: Request):
    body = await request.json()
    for m in MESSAGES.get(body.get("channel", ""), []):
        if m["ts"] == body.get("ts"):
            name = body.get("name") or "thumbsup"
            reactions = m.setdefault("reactions", [])
            one = next((r for r in reactions if r["name"] == name), None)
            if one is None:
                one = {"name": name, "users": [], "count": 0}
                reactions.append(one)
            if body.get("user") not in one["users"]:
                one["users"].append(body.get("user"))
                one["count"] = len(one["users"])
            return {"ok": True}
    return _err("message_not_found")


@app.post("/_invite")
async def invite(request: Request):
    body = await request.json()
    c = CONVS.get(body.get("channel", ""))
    if c is None:
        return _err("channel_not_found")
    c["members"].add(BOT["user_id"])
    sent = await _deliver(c, {"type": "member_joined_channel", "user": BOT["user_id"], "channel": c["id"],
                              "channel_type": "C" if c["kind"] == "channel" else "G", "team": TEAM["id"],
                              "inviter": OWNER, "event_ts": _next_ts()})
    return {"ok": True, "delivered": sent}


@app.post("/_create")
async def create(request: Request):
    body = await request.json()
    cid = "C0" + body.get("name", "new").upper()[:8]
    CONVS[cid] = {"id": cid, "name": body.get("name", "new"), "kind": "channel", "members": {OWNER},
                  "topic": "", "created": time.time()}
    MESSAGES[cid] = []
    sent = await _deliver(None, {"type": "channel_created", "channel": {"id": cid, "name": CONVS[cid]["name"],
                                                                        "created": int(time.time()),
                                                                        "creator": OWNER}}, to_all=True)
    return {"ok": True, "id": cid, "delivered": sent}


@app.post("/_disconnect")
async def disconnect():
    n = 0
    for s in list(SOCKETS):
        try:
            await s["ws"].send_text(json.dumps({"type": "disconnect", "reason": "refresh_requested"}))
            n += 1
        except Exception:  # noqa: BLE001
            pass
    return {"ok": True, "told": n}


@app.post("/_ratelimit")
async def ratelimit(request: Request):
    body = await request.json()
    LIMITS[body["method"]] = {"times": int(body.get("times") or 1), "after": int(body.get("after") or 2)}
    return {"ok": True}


@app.get("/_calls")
async def calls():
    return CALLS


@app.get("/_posted")
async def posted():
    return POSTED


@app.get("/_acks")
async def acks():
    return ACKS


@app.get("/_sockets")
async def sockets():
    return {"open": len(SOCKETS)}


def main(argv=None) -> None:
    import uvicorn

    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, default=8099)
    a = p.parse_args(argv)
    PORT["n"] = a.port
    uvicorn.run(app, host="127.0.0.1", port=a.port, log_level="warning")


if __name__ == "__main__":
    main()
