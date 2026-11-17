"""Checked identity for a Rouh this one does not know yet (phase 4).

A stranger's Rouh proves who it is with what it already carries, each checked here:

1. its card is signed by its daily key, and that key follows from its birth key (`card.check`);
2. its name and tag are the ones its birth key gives (`card.check`, `names.tag_of`);
3. its keys are not on rouh.land's public list of dead keys (stolen or retired keys), which
   rouh.land signs and every Rouh can read (``/registry/birth/api/revoked``): the "still valid?"
   list of task 123's design;
4. its address is its name on the relay's domain, which only rouh.land hands out.

The result is said to the person in plain words beside the request, and nothing is decided by it:
the person still says yes or no, and a stranger stays a Stranger until they choose otherwise.
"""
from __future__ import annotations

import asyncio
import hashlib
import base64
import time
from urllib.parse import urlsplit

_CACHE: dict = {"at": 0.0, "dead": set(), "ok": False}
EVERY = 600


def key_id(pub_b64: str) -> str:
    try:
        return hashlib.sha256(base64.b64decode(pub_b64)).hexdigest()[:16]
    except ValueError:
        return ""


def _dead_list() -> tuple[set, bool]:
    """The ids of every dead key, from rouh.land, signed; (set(), False) when it cannot be read."""
    import httpx

    from rouh import birth, genelab

    if time.time() - _CACHE["at"] < EVERY:
        return _CACHE["dead"], _CACHE["ok"]
    try:
        url, key_pem = birth.defaults()
        url = url if url.endswith("/") else url + "/"
        r = httpx.get(url + "api/revoked", timeout=10)
        payload = genelab.verify(r.json(), genelab.load_key(key_pem), birth.KIND if hasattr(birth, "KIND") else "rouh-birth")
        dead = {str(k.get("key_id")) for k in payload.get("keys") or []}
        _CACHE.update(at=time.time(), dead=dead, ok=True)
    except Exception:  # noqa: BLE001 - said as not checked, never as checked
        _CACHE.update(at=time.time(), dead=set(), ok=False)
    return _CACHE["dead"], _CACHE["ok"]


def check(part: dict) -> dict:
    """What can be said of a Rouh from its checked card part: {"ok", "said", "points": [...]}."""
    from rouh import relay

    points = ["its card is signed, and its keys follow from its birth key",
              f"its name, {part.get('name')} ·{part.get('tag')}, is the one its birth key gives"]
    dead, read = _dead_list()
    bad = [k for k in (part.get("daily_key"), part.get("birth_key")) if k and key_id(k) in dead]
    if bad:
        return {"ok": False, "said": "Its key is on rouh.land's list of dead keys: do not trust it.", "points": points}
    points.append("its keys are not on rouh.land's list of dead keys" if read
                  else "rouh.land's list of dead keys could not be read just now")
    host = urlsplit(str(part.get("address") or "")).hostname or ""
    on_relay = host == f"{part.get('label')}.{relay.domain()}" or host.endswith("." + relay.domain())
    points.append("its address is its own name on rouh.page" if on_relay else "it has no address on rouh.page")
    ok = read and on_relay
    return {"ok": ok, "said": ("Checked: " if ok else "Partly checked: ") + "; ".join(points) + ".", "points": points}


async def check_async(part: dict) -> dict:
    return await asyncio.to_thread(check, part)
