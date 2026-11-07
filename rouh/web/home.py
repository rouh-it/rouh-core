"""The Home page's lights, at /home (`homepage.js`, `rouh/hue.py`).

    GET  /api/home/lights   every room, zone and light with its real state, its scenes and its
                            lights; or `connected: false` and why, for the one line with Connect
    POST /api/home/lights   one press: {kind: room|zone|light, id, on?, brightness?, colour?, kelvin?},
                            {scene: id} or {all_off: true}; what changed, in a line

Petar, 17 October 2026: "chat is not going to cut it. Very cumbersome. I need interface and quick
access". Each is the signed-in person's own Hue connection, by their organisation and them; there
is no other. Reads made within `READ_SAME` seconds of each other, from a second tab or a second
device, are answered with the one before, unless something was pressed since, so the Hue cloud is
asked at most once in that time. The robot is `/api/home/vacuum` (`rouh/web/dreame.py`).
"""
from __future__ import annotations

import asyncio
import logging
import time

from django.http import HttpRequest

from .clock import _signed_in, their_clock
from .common import answer, body_of, only, refuse
from .google import Meter

log = logging.getLogger("rouh.web.home")
NO_STORE = {"Cache-Control": "no-store"}
#: Seconds a read is answered again rather than asked of the Hue cloud again.
READ_SAME = 3.0
_READS: dict[str, tuple[float, dict]] = {}
#: Presses in a minute, per person, before they are refused: a slider dragged sends about two a
#: second, and Hue's own limit for a bridge is about ten.
meter = Meter(240, 60.0)


def _key(me) -> str:
    return f"{me.org_id}:{me.user_id}"


def _not_here(me, exc) -> dict:
    """What the page says when there are no lights to show: one line and where to connect."""
    from rouh import hue

    lapsed = isinstance(exc, hue.Lapsed)
    return {"connected": False, "lapsed": lapsed, "connect": hue.PAGE,
            "said": "Philips Hue needs connecting again." if lapsed else str(exc)}


@only("GET", "POST")
@their_clock
async def lights(request: HttpRequest):
    from rouh import hue

    me = await asyncio.to_thread(_signed_in, request)
    if me is None:
        return refuse("Sign in first.", 401)
    if request.method == "POST":
        if meter.too_many("press:" + str(me.user_id)):
            return refuse("That is a lot of presses at once. Wait a moment.", 429)
        body = body_of(request)
        _READS.pop(_key(me), None)
        try:
            said = await asyncio.to_thread(hue.page_change, me, body)
        except (hue.NotSetUp, hue.Lapsed) as exc:
            return refuse(str(exc), 409, **_not_here(me, exc))
        except hue.Refused as exc:
            return refuse(str(exc), 400)
        except hue.HueError as exc:
            return refuse(str(exc), 502)
        except Exception:  # noqa: BLE001
            log.exception("home: a press on the lights failed")
            return refuse("That did not reach the lights. Try again.", 500)
        _READS.pop(_key(me), None)
        return answer({"ok": True, "said": said}, headers=NO_STORE)
    kept = _READS.get(_key(me))
    if kept and time.monotonic() - kept[0] < READ_SAME:
        return answer(kept[1], headers=NO_STORE)
    try:
        got = await asyncio.to_thread(hue.page_home, me)
    except (hue.NotSetUp, hue.Lapsed) as exc:
        return answer(_not_here(me, exc), headers=NO_STORE)
    except hue.Limited as exc:
        return refuse(str(exc), 429)
    except hue.HueError as exc:
        return refuse(str(exc), 502)
    except Exception:  # noqa: BLE001
        log.exception("home: reading the lights failed")
        return refuse("The lights could not be read. Rouh will try again.", 500)
    out = {"connected": True, **got}
    _READS[_key(me)] = (time.monotonic(), out)
    return answer(out, headers=NO_STORE)
