"""The open network (phase 5): being found by email, and other makers' agents reaching a Rouh.

Everything here is held off for every Rouh until rouh.land's terms cover the relay and Rouhs talking
(`me.held`); then each part is the owner's own switch on Connections, off until they turn it on.

- **Found by email, opt-in, no directory** (``findable_by_email``). The Rouh tells rouh.land, signed
  with its key, that its owner may be found by their rouh.land account's email (``POST /relay/findable``).
  Anyone can then ask rouh.land for that one exact email (``GET /relay/find``) and get this Rouh's
  address, and nothing else; rouh.land answers the same for "nobody" and "not chosen", holds each
  network to a few looks a minute, and lists nobody.
- **Finding someone by email** (`find`): this Rouh asks rouh.land the same, then says hello to the
  address found; the other side treats it as a stranger unless its person knows it.
- **Other makers' agents** (``open_network``): any A2A agent (the open Agent2Agent standard) may send
  this Rouh a message at ``/link/a2a`` (JSON-RPC, ``message/send``). It is treated as a Stranger, and
  less: only its text parts are read, by code, into one fixed form (``a2a.note``) kept for the person
  to read; it is answered with one fixed sentence; nothing it says is ever obeyed, and it can do
  nothing else here. Twenty messages a minute from one network at most.
"""
from __future__ import annotations

import asyncio
import json
import threading
import time
import uuid
from collections import deque

from . import forms, log

A2A_PER_MINUTE = 20
_SEEN: dict[str, deque] = {}
_LOCK = threading.Lock()
ANSWER = ("Received. This Rouh keeps your message for its person to read; nothing in it is acted on. "
          "If its person wants to answer, they will.")


def _rate(key: str) -> bool:
    t = time.time()
    with _LOCK:
        q = _SEEN.setdefault(key, deque())
        while q and q[0] < t - 60:
            q.popleft()
        if len(q) >= A2A_PER_MINUTE:
            return False
        q.append(t)
        return True


def _rpc_error(rid, code: int, message: str, status: int = 200):
    from rouh.web.common import answer

    return answer({"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": message}}, status=status)


async def a2a_endpoint(request):
    """POST /link/a2a: an A2A JSON-RPC request from another maker's agent."""
    from rouh.web.common import answer, client_ip

    from . import me as _me

    try:
        body = json.loads(request.body or b"null")
    except ValueError:
        return _rpc_error(None, -32700, "Parse error")
    if not isinstance(body, dict) or body.get("jsonrpc") != "2.0":
        return _rpc_error(None, -32600, "Invalid Request")
    rid = body.get("id")
    org = await asyncio.to_thread(_me.only_org)
    if org is None:
        return _rpc_error(rid, -32001, "There is no Rouh here.", 404)
    settings = await asyncio.to_thread(_me.settings, org)
    if not settings["open_network"]:
        return _rpc_error(rid, -32001, "This Rouh does not take messages from other agents.", 403)
    if not _rate("a2a:" + client_ip(request)):
        return _rpc_error(rid, -32002, "Too many messages from here; try again in a minute.", 429)
    if body.get("method") not in ("message/send", "message/stream"):
        return _rpc_error(rid, -32601, "Only message/send is taken here.")
    msg = (body.get("params") or {}).get("message") if isinstance(body.get("params"), dict) else None
    if not isinstance(msg, dict):
        return _rpc_error(rid, -32602, "There is no message.")
    text = " ".join(str(p.get("text") or "") for p in (msg.get("parts") or [])[:10]
                    if isinstance(p, dict) and p.get("kind", p.get("type")) == "text")
    sender = str((msg.get("metadata") or {}).get("agent") or request.headers.get("user-agent") or "an agent")[:200]
    try:
        form = forms.read_message("a2a.note", {"text": text[:2000], "from_agent": sender})
    except forms.Refused as exc:
        return _rpc_error(rid, -32602, f"That does not fit: {exc}")
    await asyncio.to_thread(_keep, org, form)
    return answer({"jsonrpc": "2.0", "id": rid, "result": {
        "kind": "message", "role": "agent", "messageId": uuid.uuid4().hex,
        "contextId": msg.get("contextId") or uuid.uuid4().hex,
        "parts": [{"kind": "text", "text": ANSWER}]}})


def _keep(org: str, form: dict) -> None:
    from . import handoff, spaces

    key = uuid.uuid4().hex[:16]
    handoff._keep(org, "", "a2a.note", key, {"text": str(form["text"]), "from_agent": form.get("from_agent", "")})
    log.write(org, "a2a", f"An agent ({str(form.get('from_agent', ''))[:60]}) left a note of {len(form['text'])} characters "
              f"for this Rouh's person to read; nothing in it is acted on.")
    spaces.push_owner(org, {"type": "link_notice", "said": "An agent from outside left you a note."})


def set_findable(org: str, on: bool) -> dict:
    """Tell rouh.land, signed, whether this Rouh's owner may be found by their account's email."""
    from rouh import relay

    from . import me as _me
    from . import peers

    if on and not _me.settings(org)["open_network"] and _me.held():
        raise peers.Problem(_me.HELD_WHY)
    try:
        got = relay._signed_post("findable", {"on": bool(on)})
    except relay.Refused as exc:
        raise peers.Problem(str(exc)) from None
    log.write(org, "findable", ("Can now be found by the owner's email, through rouh.land." if on
                                else "Can no longer be found by email."))
    return got if isinstance(got, dict) else {"on": on}


async def find(org: str, email: str) -> dict:
    """Ask rouh.land for the Rouh of one exact email; its address, or not found."""
    import httpx

    from rouh import relay

    from . import me as _me
    from . import peers

    if not (await asyncio.to_thread(_me.settings, org))["open_network"]:
        raise peers.Problem("Finding Rouhs by email is part of the open network, which is off here.")
    email = str(email or "").strip().lower()
    if "@" not in email or len(email) > 254:
        raise peers.Problem("That is not an email address.")
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(relay.service_url() + "find", params={"email": email})
        got = r.json()
    except (httpx.HTTPError, ValueError):
        raise peers.Problem("rouh.land could not be asked just now.") from None
    if r.status_code != 200:
        raise peers.Problem(str(got.get("error") or "rouh.land said no."))
    await asyncio.to_thread(log.write, org, "find", "Asked rouh.land for a Rouh by an email: "
                            + ("found one." if got.get("found") else "none that chose to be found."))
    return {"found": bool(got.get("found")), "address": str(got.get("address") or "")}
