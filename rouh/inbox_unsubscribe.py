"""Unsubscribe in the inbox card: a newsletter opened on the inbox card stops in one press.

Built by the nightly feature run, night 30 (the ledger's night 34), 5 November 2026 (task 94).
Going through the inbox on Rouh's inbox card, a newsletter or a shop's mail could be read and
archived, and nothing more: stopping it meant opening it in Gmail, scrolling to the small link at its
foot, and pressing through the sender's page. On the person's own inbox, which Rouh reads read-only,
the card could not even archive it.

Mail sent to a list says how to leave it, in its headers: `List-Unsubscribe` (RFC 2369) names an
address, and `List-Unsubscribe-Post: List-Unsubscribe=One-Click` (RFC 8058, which Gmail and Yahoo
have asked of every bulk sender since 2024) says one POST to that address is enough, with no page
and no login. That POST is made to the sender, not to the mailbox, so it changes nothing in the
inbox, and works from a read-only one too.

So, while its switch is on, a message opened on the inbox card that carries those headers has an
Unsubscribe button under its own buttons, with the list's sender:

- **one press** (`one-click`): Rouh makes the POST itself, from the server, to a public https address
  only (never this machine or its network, and no redirect followed), and says "Unsubscribed";
- **a page** (only a link, no one-click): the sender's own page opens in a new tab, as it would from
  the email's foot;
- an address only (`mailto:`) is said to be one, as Rouh cannot write from the person's inbox.

Each unsubscribe is kept in the person's own setting (`inbox_unsubscribed`), so the card says
"You unsubscribed from this list on 5 November" when the next one from it is opened.

No model is asked.

**Whose.** The mailbox the card names, by its token, and the person it belongs to.

**Its switch** is `inbox_unsubscribe` (`rouh/switches.py`): off, the button is not offered and the
card refuses the press.
"""
from __future__ import annotations

import ipaddress
import json
import logging
import os
import re
import socket
import time
from urllib.parse import urlsplit

log = logging.getLogger("rouh.inbox_unsubscribe")

SWITCH = "inbox_unsubscribe"
TITLE = ("Unsubscribe in the inbox card: a newsletter opened on the inbox card has an Unsubscribe "
         "button that stops it in one press")
KEPT = "inbox_unsubscribed"
SECONDS = 15.0

_LINKS = re.compile(r"<\s*([^>\s]+)\s*>")


def on(who) -> bool:
    from . import switches

    if who is None:
        return False
    return switches.on(SWITCH, getattr(who, "org_id", None) or None)


def links(header: str) -> tuple[str, str]:
    """(the first web address, the first mailto address) the List-Unsubscribe header names. An https
    address goes before a plain http one; the POST itself is only ever made to https (`public_https`)."""
    web, mail, plain = "", "", ""
    for one in _LINKS.findall(header or ""):
        low = one.lower()
        if low.startswith("https://") and not web:
            web = one
        elif low.startswith("http://") and not plain:
            plain = one
        elif low.startswith("mailto:") and not mail:
            mail = one
    return web or plain, mail


def offer(found: dict) -> dict | None:
    """What the card offers for this message, or None when it is not mail from a list."""
    from email.utils import parseaddr

    web, mail = links(found.get("list_unsubscribe") or "")
    if not web and not mail:
        return None
    one_click = bool(web) and "one-click" in (found.get("list_unsubscribe_post") or "").lower()
    name, address = parseaddr(str(found.get("from") or ""))
    name, address = name.strip().strip('"'), address.strip().lower()
    return {"how": "one-click" if one_click else ("link" if web else "mail"),
            "list": name or address, "address": address}


def _allowed() -> set[str]:
    """Hosts a test world may reach although they are on this machine (never set on a real Rouh)."""
    return {one.strip().lower() for one in os.environ.get("ROUH_UNSUBSCRIBE_ALLOW", "").split(",")
            if one.strip()}


def public_https(url: str) -> str:
    """"" when Rouh may POST to this address, or why not."""
    parts = urlsplit(url or "")
    host = (parts.hostname or "").lower()
    allowed = _allowed()
    if host and (host in allowed or f"{host}:{parts.port}" in allowed):
        return ""
    if parts.scheme != "https" or not host:
        return "it is not an https address"
    try:
        found = socket.getaddrinfo(host, parts.port or 443, proto=socket.IPPROTO_TCP)
    except OSError:
        return f"{host} could not be looked up"
    for _f, _t, _p, _c, sockaddr in found:
        try:
            ip = ipaddress.ip_address(str(sockaddr[0]).split("%", 1)[0])
        except ValueError:
            return f"{host} resolves to something unrecognisable"
        if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
            ip = ip.ipv4_mapped
        if not ip.is_global or ip.is_multicast:
            return f"{host} is not on the public internet"
    return ""


def _ids(who) -> tuple[str, str]:
    return str(getattr(who, "user_id", "") or ""), str(getattr(who, "org_id", "") or "")


def kept(who) -> dict[str, dict]:
    from .models import UserSetting

    user_id, org_id = _ids(who)
    value = (UserSetting.objects.filter(user_id=user_id, org_id=org_id, name=KEPT)
             .values_list("value", flat=True).first())
    try:
        held = json.loads(value) if value else {}
    except (TypeError, ValueError):
        held = {}
    return {str(k): v for k, v in held.items() if isinstance(v, dict)} if isinstance(held, dict) else {}


def keep(who, address: str, how: str, name: str) -> None:
    from .models import UserSetting

    held = kept(who)
    held[address.lower()] = {"at": time.time(), "how": how, "list": name}
    if len(held) > 500:
        held = dict(sorted(held.items(), key=lambda kv: kv[1].get("at") or 0)[-500:])
    user_id, org_id = _ids(who)
    UserSetting.objects.bulk_create(
        [UserSetting(user_id=user_id, org_id=org_id, name=KEPT, value=json.dumps(held),
                     updated_at=time.time())],
        update_conflicts=True, unique_fields=["user_id", "name"],
        update_fields=["org_id", "value", "updated_at"])


def shown(who, found: dict, zone=None) -> dict | None:
    """The card's offer for one opened message, with when it was unsubscribed before, if it was."""
    if not on(who):
        return None
    got = offer(found)
    if got is None:
        return None
    before = kept(who).get((got.get("address") or "").lower())
    if before and before.get("at"):
        from datetime import datetime

        from . import clock

        zone = zone or clock.zone_of(who)
        got["before"] = datetime.fromtimestamp(before["at"], zone).strftime("%-d %B")
    return got


async def press(who, found: dict, *, by: str = "") -> dict:
    """Unsubscribe from the list this message came from: {"ok", "said", "open"?} or {"ok": False, "why"}.

    `by` is another gene's switch that has already checked itself and says its own use (Newsletters
    you never open, `rouh/unread_lists.py`): this one's switch is then not asked, nor its use said."""
    import asyncio

    import httpx
    from asgiref.sync import sync_to_async

    from . import evolution

    if not by and not await asyncio.to_thread(on, who):
        return {"ok": False, "why": "Unsubscribe in the inbox card is switched off."}
    got = offer(found)
    if got is None:
        return {"ok": False, "why": "This message says no way to unsubscribe from it."}
    web, mail = links(found.get("list_unsubscribe") or "")
    name = got["list"] or "this list"
    if got["how"] == "mail":
        return {"ok": False, "why": f"{name} unsubscribes only by an email to {mail[7:].split('?')[0]}, "
                                    "from your own address: write it from Gmail."}
    if got["how"] == "link":
        await asyncio.to_thread(keep, who, got["address"], "link", name)
        if not by:
            await sync_to_async(evolution.used)(SWITCH, "unsubscribed", who=who, detail=f"page: {got['address']}"[:200])
        return {"ok": True, "open": web, "said": f"{name}'s own page to unsubscribe is open in a new tab."}
    why = await asyncio.to_thread(public_https, web)
    if why:
        return {"ok": False, "why": f"Rouh will not send the unsubscribe there: {why}."}
    try:
        async with httpx.AsyncClient(timeout=SECONDS, follow_redirects=False) as http:
            answer = await http.post(web, content=b"List-Unsubscribe=One-Click",
                                     headers={"Content-Type": "application/x-www-form-urlencoded",
                                              "User-Agent": "Rouh (one-click unsubscribe, RFC 8058)"})
    except httpx.HTTPError as exc:
        return {"ok": False, "why": f"{name}'s server did not answer ({type(exc).__name__}). Try again later."}
    if answer.status_code >= 400:
        return {"ok": False, "why": f"{name}'s server refused it (it answered {answer.status_code})."}
    await asyncio.to_thread(keep, who, got["address"], "one-click", name)
    if not by:
        await sync_to_async(evolution.used)(SWITCH, "unsubscribed", who=who, detail=f"one press: {got['address']}"[:200])
    return {"ok": True, "said": f"Unsubscribed from {name}. Senders may take up to two days to stop."}


__all__ = ["KEPT", "SWITCH", "TITLE", "keep", "kept", "links", "offer", "on", "press", "public_https", "shown"]
