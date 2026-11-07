"""A stand-in for the Philips Hue cloud, so Rouh's Hue connection can be driven end to end with nothing real.

The same idea as `fake_slack.py`: a real HTTP server in front of the real client (`rouh/hue.py`),
so what a check proves is what went over the wire. It speaks enough of the Remote Hue API, in its
own shapes:

- the sign-in: ``GET /v2/oauth2/authorize`` is a page with Allow and Deny that sends the browser back
  to the ``redirect_uri`` with a code (or ``error=access_denied``) and the state; ``POST
  /v2/oauth2/token`` takes the app's client id and secret as Basic auth and changes a code, or a
  refresh token, for an access token (``expires_in`` 7 days) and a new refresh token. A refresh
  token is used once: the old one is refused after it, as a rotating one is.
- the link: ``PUT /route/api/0/config {"linkbutton": true}`` presses the bridge's button, and
  ``POST /route/api {"devicetype"}`` within 30 seconds of it gives an application key.
- CLIP v2: ``GET /route/clip/v2/resource`` (everything), ``/resource/<type>`` and
  ``/resource/<type>/<id>``, and ``PUT`` of a light, a grouped_light (a room's, a zone's or the
  whole home's: every light in it at once) or a scene (``recall``). Each needs the bearer token
  (401 without a good one) and ``hue-application-key`` (403 "unauthorized user" without a key it
  gave).

The home is `_home()`: a Living room (Ceiling and a Floor lamp), a Bedroom (Bedside lamp and Reading
lamp), a Kitchen (Kitchen ceiling, white only) and an Office whose light is also called Office, a
zone Downstairs over the living room and the kitchen, a light in no room (Porch), and scenes Relax
and Read in the living room, Relax and Nightlight in the bedroom.

The app it knows is `CLIENT_ID` and `CLIENT_SECRET` (app id `APP_ID`); any other is refused.

Knobs, each a POST:

- ``/_expire``: every access token stops working now (the next call is a 401).
- ``/_lapse``: every refresh token is refused from now on, as a sign-in that has lapsed.
- ``/_forget_keys``: the bridge no longer knows any application key.
- ``/_ratelimit {"times", "after"}``: the next ``times`` calls under /route answer 429 with
  ``Retry-After: <after>``.
- ``/_fail {"path", "status", "times"}``: the next ``times`` calls to ``path`` (any method) answer
  ``status`` with a page like the Hue cloud's front gives (521 by default: the bridge out of reach);
  ``times`` -1 is every call until ``/_fail {"times": 0}``.
- ``/_press_button``: the bridge's own round link button is pressed, as by a hand, which a
  ``POST /route/api`` within 30 seconds answers with a key.
- ``/_home {"home": "family"}``: the bridge holds a whole family home instead (`_family_home`: the
  eight rooms and three zones of Maple House, scenes in most rooms, and the Toilet Fan as a plug, on
  and off only); ``"small"`` puts the one above back.

And ``GET /_calls`` (every call, the token's last four only) and ``/_lights`` (each light's state).

Point ``ROUH_HUE_API`` at ``http://127.0.0.1:<port>``.

    python -m rouh.testing.fake_hue --port 8098
"""
from __future__ import annotations

import argparse
import base64
import copy
import html
import secrets
import time
import urllib.parse

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

CLIENT_ID = "rouhhuestandinclient"
CLIENT_SECRET = "stand-in-hue-secret-7f3a"
APP_ID = "rouh-stand-in"
ACCESS_LIFE = 604800
REFRESH_LIFE = 9676800

GAMUT_C = {"red": {"x": 0.6915, "y": 0.3083}, "green": {"x": 0.17, "y": 0.7}, "blue": {"x": 0.1532, "y": 0.0475}}
GAMUT_B = {"red": {"x": 0.675, "y": 0.322}, "green": {"x": 0.409, "y": 0.518}, "blue": {"x": 0.167, "y": 0.04}}
CT = {"mirek": 366, "mirek_valid": True, "mirek_schema": {"mirek_minimum": 153, "mirek_maximum": 454}}


def _light(lid: str, device: str, name: str, archetype: str, *, colour=GAMUT_C, white=True, on=False,
           dims=True, brightness=60.0):
    out = {"id": lid, "type": "light", "owner": {"rid": device, "rtype": "device"},
           "metadata": {"name": name, "archetype": archetype}, "on": {"on": on}}
    if dims:
        out["dimming"] = {"brightness": brightness, "min_dim_level": 0.2}
    if white:
        out["color_temperature"] = copy.deepcopy(CT)
    if colour:
        out["color"] = {"xy": {"x": 0.4573, "y": 0.41}, "gamut": colour,
                        "gamut_type": "C" if colour is GAMUT_C else "B"}
    return out


def _home() -> dict:
    lights = [
        _light("l-ceiling", "d-ceiling", "Ceiling", "ceiling_round", on=True),
        _light("l-floor", "d-floor", "Floor lamp", "floor_shade"),
        _light("l-bedside", "d-bedside", "Bedside lamp", "table_shade", colour=GAMUT_B),
        _light("l-reading", "d-reading", "Reading lamp", "desk_lamp"),
        _light("l-kitchen", "d-kitchen", "Kitchen ceiling", "ceiling_square", colour=None),
        _light("l-office", "d-office", "Office", "classic_bulb"),
        _light("l-porch", "d-porch", "Porch", "wall_lantern"),
    ]
    devices = [{"id": l["owner"]["rid"], "type": "device", "metadata": {"name": l["metadata"]["name"]},
                "services": [{"rid": l["id"], "rtype": "light"}]} for l in lights]
    devices.append({"id": "d-bridge", "type": "device", "metadata": {"name": "Stand-in Bridge"},
                    "services": [{"rid": "b-1", "rtype": "bridge"}]})

    def group(gid: str, kind: str, name: str, children: list, gl: str):
        return {"id": gid, "type": kind, "metadata": {"name": name, "archetype": "other"},
                "children": children, "services": [{"rid": gl, "rtype": "grouped_light"}]}

    dev = lambda d: {"rid": d, "rtype": "device"}  # noqa: E731
    lit = lambda l: {"rid": l, "rtype": "light"}  # noqa: E731
    rooms = [
        group("r-living", "room", "Living room", [dev("d-ceiling"), dev("d-floor")], "g-living"),
        group("r-bedroom", "room", "Bedroom", [dev("d-bedside"), dev("d-reading")], "g-bedroom"),
        group("r-kitchen", "room", "Kitchen", [dev("d-kitchen")], "g-kitchen"),
        group("r-office", "room", "Office", [dev("d-office")], "g-office"),
    ]
    zones = [group("z-down", "zone", "Downstairs", [lit("l-ceiling"), lit("l-floor"), lit("l-kitchen")], "g-down")]
    grouped = [{"id": g["services"][0]["rid"], "type": "grouped_light",
                "owner": {"rid": g["id"], "rtype": g["type"]}, "on": {"on": False},
                "dimming": {"brightness": 0.0}} for g in rooms + zones]
    grouped.append({"id": "g-all", "type": "grouped_light", "owner": {"rid": "home-1", "rtype": "bridge_home"},
                    "on": {"on": True}})

    def scene(sid, name, group_id, kind, sets):
        return {"id": sid, "type": "scene", "metadata": {"name": name}, "group": {"rid": group_id, "rtype": kind},
                "status": {"active": "inactive"},
                "actions": [{"target": {"rid": l, "rtype": "light"}, "action": a} for l, a in sets]}

    scenes = [
        scene("s-living-relax", "Relax", "r-living", "room",
              [("l-ceiling", {"on": {"on": True}, "dimming": {"brightness": 40.0},
                              "color_temperature": {"mirek": 447}}),
               ("l-floor", {"on": {"on": True}, "dimming": {"brightness": 40.0},
                            "color_temperature": {"mirek": 447}})]),
        scene("s-living-read", "Read", "r-living", "room",
              [("l-ceiling", {"on": {"on": True}, "dimming": {"brightness": 100.0},
                              "color_temperature": {"mirek": 346}})]),
        scene("s-bed-relax", "Relax", "r-bedroom", "room",
              [("l-bedside", {"on": {"on": True}, "dimming": {"brightness": 30.0}})]),
        scene("s-bed-night", "Nightlight", "r-bedroom", "room",
              [("l-bedside", {"on": {"on": True}, "dimming": {"brightness": 2.0},
                              "color": {"xy": {"x": 0.56, "y": 0.4}}})]),
    ]
    bridge = [{"id": "b-1", "type": "bridge", "bridge_id": "001788fffe0standin",
               "owner": {"rid": "d-bridge", "rtype": "device"}}]
    home = [{"id": "home-1", "type": "bridge_home", "children": [dev("d-bridge")],
             "services": [{"rid": "g-all", "rtype": "grouped_light"}]}]
    all_ = lights + devices + rooms + zones + grouped + scenes + bridge + home
    return {r["id"]: r for r in all_}


def _family_home() -> dict:
    """A family home the way a real bridge names one (modelled on one seen on 17 October 2026): eight
    rooms, three zones and scenes in most rooms, with made-up lights in them. The Toilet Fan is a
    plug: on and off only."""
    def L(lid, name, arche, **kw):
        return _light(lid, "d" + lid[1:], name, arche, **kw)
    lights = [
        L("l-lr-ceil", "Living room ceiling", "ceiling_round", on=True, brightness=72.0),
        L("l-lr-floor", "Floor lamp by the sofa", "floor_shade", on=True, brightness=45.0),
        L("l-lr-tv", "TV gradient lightstrip", "hue_lightstrip_tv", on=False),
        L("l-bed-l", "Bedside left", "table_shade", colour=GAMUT_B),
        L("l-bed-r", "Bedside right", "table_shade", colour=GAMUT_B),
        L("l-kids-night", "Kids night light", "hue_go", on=True, brightness=8.0),
        L("l-kids-ceil", "Kids bedroom ceiling", "ceiling_round", colour=None),
        L("l-din-1", "Dining pendant 1", "pendant_round", colour=None),
        L("l-din-2", "Dining pendant 2", "pendant_round", colour=None),
        L("l-kit-ceil", "Kitchen ceiling", "ceiling_square", colour=None, on=True, brightness=100.0),
        L("l-kit-under", "Under the cabinets", "hue_lightstrip", colour=None),
        L("l-hall", "Hallway", "ceiling_round", colour=None, white=False),
        L("l-wc", "Toilet light", "classic_bulb", colour=None),
        L("l-fan", "Toilet Fan", "plug", colour=None, white=False, dims=False),
    ]
    devices = [{"id": l["owner"]["rid"], "type": "device", "metadata": {"name": l["metadata"]["name"]},
                "services": [{"rid": l["id"], "rtype": "light"}]} for l in lights]
    devices.append({"id": "d-bridge", "type": "device", "metadata": {"name": "Maple House"},
                    "services": [{"rid": "b-1", "rtype": "bridge"}]})

    def group(gid, kind, name, children, gl):
        return {"id": gid, "type": kind, "metadata": {"name": name, "archetype": "other"},
                "children": children, "services": [{"rid": gl, "rtype": "grouped_light"}]}

    dev = lambda l: {"rid": "d" + l[1:], "rtype": "device"}  # noqa: E731
    lit = lambda l: {"rid": l, "rtype": "light"}  # noqa: E731
    rooms_of = {
        "Living room": ["l-lr-ceil", "l-lr-floor", "l-lr-tv"], "Bedroom": ["l-bed-l", "l-bed-r"],
        "Kids bedroom": ["l-kids-night", "l-kids-ceil"], "Dining": ["l-din-1", "l-din-2"],
        "Kitchen": ["l-kit-ceil", "l-kit-under"], "Hallway": ["l-hall"], "Toilet": ["l-wc"],
        "Toilet Fan": ["l-fan"],
    }
    rooms = [group(f"r-{i}", "room", name, [dev(l) for l in ls], f"g-r{i}")
             for i, (name, ls) in enumerate(rooms_of.items())]
    every = [l["id"] for l in lights if l["id"] != "l-fan"]
    zones = [group("z-home", "zone", "Home", [lit(l) for l in every], "g-zhome"),
             group("z-nokids", "zone", "Home W/out Kids",
                   [lit(l) for l in every if not l.startswith("l-kids")], "g-znokids"),
             group("z-welcome", "zone", "Welcome Home", [lit("l-hall"), lit("l-lr-ceil"), lit("l-kit-ceil")],
                   "g-zwelcome")]
    grouped = [{"id": g["services"][0]["rid"], "type": "grouped_light",
                "owner": {"rid": g["id"], "rtype": g["type"]}, "on": {"on": False},
                "dimming": {"brightness": 0.0}} for g in rooms + zones]
    grouped.append({"id": "g-all", "type": "grouped_light", "owner": {"rid": "home-1", "rtype": "bridge_home"},
                    "on": {"on": True}})
    warm = {"color_temperature": {"mirek": 447}}
    cool = {"color_temperature": {"mirek": 233}}
    looks = {
        "Relax": lambda ls: [(l, {"on": {"on": True}, "dimming": {"brightness": 45.0}, **warm}) for l in ls],
        "Read": lambda ls: [(l, {"on": {"on": True}, "dimming": {"brightness": 100.0},
                                 "color_temperature": {"mirek": 346}}) for l in ls],
        "Concentrate": lambda ls: [(l, {"on": {"on": True}, "dimming": {"brightness": 100.0}, **cool}) for l in ls],
        "Nightlight": lambda ls: [(l, {"on": {"on": True}, "dimming": {"brightness": 2.0}, **warm}) for l in ls],
        "Savanna sunset": lambda ls: [(l, {"on": {"on": True}, "dimming": {"brightness": 70.0},
                                           "color": {"xy": {"x": 0.58, "y": 0.38}}}) for l in ls],
        "Dimmed": lambda ls: [(l, {"on": {"on": True}, "dimming": {"brightness": 20.0}}) for l in ls],
    }
    plan = {"Living room": ["Relax", "Read", "Concentrate", "Savanna sunset"], "Bedroom": ["Relax", "Nightlight",
            "Savanna sunset"], "Kids bedroom": ["Nightlight", "Relax"], "Dining": ["Relax", "Dimmed"],
            "Kitchen": ["Concentrate", "Relax"], "Hallway": ["Dimmed"], "Toilet": ["Nightlight"],
            "Home": ["Relax", "Dimmed"], "Welcome Home": ["Relax"]}
    scenes = []
    for g in rooms + zones:
        name = g["metadata"]["name"]
        members = [c["rid"] if c["rtype"] == "light" else "l" + c["rid"][1:] for c in g["children"]]
        for n in plan.get(name, []):
            scenes.append({"id": f"s-{g['id']}-{n.lower().replace(' ', '-')}", "type": "scene",
                           "metadata": {"name": n}, "group": {"rid": g["id"], "rtype": g["type"]},
                           "status": {"active": "inactive"},
                           "actions": [{"target": {"rid": l, "rtype": "light"}, "action": a}
                                       for l, a in looks[n](members)]})
    bridge = [{"id": "b-1", "type": "bridge", "bridge_id": "001788fffe0maplehou",
               "owner": {"rid": "d-bridge", "rtype": "device"}}]
    home = [{"id": "home-1", "type": "bridge_home", "children": [dev("l-bridge")],
             "services": [{"rid": "g-all", "rtype": "grouped_light"}]}]
    return {r["id"]: r for r in lights + devices + rooms + zones + grouped + scenes + bridge + home}


#: The homes `/_home` can put on the bridge.
HOMES = {"small": _home, "family": _family_home}


STATE = {"home": {}, "codes": {}, "access": {}, "refresh": {}, "keys": set(), "link_at": 0.0,
         "ratelimit": {"times": 0, "after": "1"}, "fail": {"path": "", "status": 521, "times": 0},
         "calls": []}

app = FastAPI()


def _settled_home(which: str = "small") -> dict:
    STATE["home"] = HOMES[which]()
    _settle_groups()
    return STATE["home"]


def _log(request: Request, status: int, note: str = "") -> None:
    auth = request.headers.get("authorization") or ""
    STATE["calls"].append({"at": time.time(), "method": request.method, "path": request.url.path,
                           "status": status, "token": auth[-4:] if auth else "",
                           "key": (request.headers.get("hue-application-key") or "")[-4:], "note": note})


def _client_ok(request: Request) -> bool:
    auth = request.headers.get("authorization") or ""
    if not auth.lower().startswith("basic "):
        return False
    try:
        pair = base64.b64decode(auth[6:]).decode()
    except ValueError:
        return False
    return pair == f"{CLIENT_ID}:{CLIENT_SECRET}"


@app.get("/v2/oauth2/authorize")
async def authorize(request: Request):
    q = request.query_params
    if q.get("client_id") != CLIENT_ID or q.get("response_type") != "code" or not q.get("redirect_uri"):
        _log(request, 400, "bad authorize")
        return HTMLResponse("<h1>Unknown app</h1><p>That client id is not a Hue app.</p>", status_code=400)
    _log(request, 200)
    back = html.escape(q.get("redirect_uri") or "")
    state = html.escape(q.get("state") or "")
    return HTMLResponse(f"""<!doctype html><html><head><title>Philips Hue sign-in (stand-in)</title>
<meta name=viewport content="width=device-width,initial-scale=1"></head>
<body style="font-family:sans-serif;max-width:28rem;margin:3rem auto;padding:0 1rem">
<h1>Philips Hue (stand-in)</h1><p>Rouh would like to control your Hue lights.</p>
<form method="get" action="/_consent">
<input type="hidden" name="redirect_uri" value="{back}"><input type="hidden" name="state" value="{state}">
<button name="answer" value="allow">Allow</button> <button name="answer" value="deny">Deny</button>
</form></body></html>""")


@app.get("/_consent")
async def consent(request: Request):
    q = request.query_params
    back = q.get("redirect_uri") or "/"
    sep = "&" if "?" in back else "?"
    if q.get("answer") != "allow":
        return RedirectResponse(back + sep + urllib.parse.urlencode({"error": "access_denied",
                                                                     "state": q.get("state") or ""}), 302)
    code = "code-" + secrets.token_urlsafe(8)
    STATE["codes"][code] = back
    return RedirectResponse(back + sep + urllib.parse.urlencode({"code": code, "state": q.get("state") or ""}), 302)


def _tokens() -> dict:
    access, refresh = "acc-" + secrets.token_urlsafe(12), "ref-" + secrets.token_urlsafe(12)
    STATE["access"][access] = time.time() + ACCESS_LIFE
    STATE["refresh"][refresh] = True
    return {"access_token": access, "expires_in": ACCESS_LIFE, "refresh_token": refresh,
            "token_type": "bearer"}


@app.post("/v2/oauth2/token")
async def token(request: Request):
    form = await request.form()
    if not _client_ok(request):
        _log(request, 401, "bad client")
        return JSONResponse({"error": "invalid_client"}, 401)
    grant = form.get("grant_type")
    if grant == "authorization_code":
        back = STATE["codes"].pop(str(form.get("code") or ""), None)
        if back is None or back != form.get("redirect_uri"):
            _log(request, 400, "bad code")
            return JSONResponse({"error": "invalid_grant"}, 400)
    elif grant == "refresh_token":
        old = str(form.get("refresh_token") or "")
        if not STATE["refresh"].get(old):
            _log(request, 400, "bad refresh")
            return JSONResponse({"error": "invalid_grant"}, 400)
        STATE["refresh"][old] = False
    else:
        _log(request, 400, "bad grant")
        return JSONResponse({"error": "unsupported_grant_type"}, 400)
    _log(request, 200, grant)
    return JSONResponse(_tokens())


def _bearer(request: Request):
    """None when the bearer token is good, or the 401 to answer."""
    auth = request.headers.get("authorization") or ""
    tok = auth[7:] if auth.lower().startswith("bearer ") else ""
    if STATE["access"].get(tok, 0) < time.time():
        return JSONResponse({"fault": {"faultstring": "Invalid Access Token",
                                       "detail": {"errorcode": "keymanagement.service.invalid_access_token"}}}, 401)
    return None


def _limited(request: Request):
    fail = STATE["fail"]
    if fail["times"] and request.url.path == fail["path"]:
        if fail["times"] > 0:
            fail["times"] -= 1
        return HTMLResponse(f"<!DOCTYPE html><html><head><title>api.meethue.com | {fail['status']}: Web server is "
                            "down</title></head><body><h1>Web server is down</h1></body></html>",
                            fail["status"])
    rl = STATE["ratelimit"]
    if rl["times"] > 0:
        rl["times"] -= 1
        return JSONResponse({"errors": [{"description": "Too many requests"}]}, 429,
                            headers={"Retry-After": str(rl["after"])})
    return None


@app.put("/route/api/0/config")
async def linkbutton(request: Request):
    stop = _limited(request) or _bearer(request)
    if stop is not None:
        _log(request, stop.status_code)
        return stop
    body = await request.json()
    if body.get("linkbutton") is True:
        STATE["link_at"] = time.time()
    _log(request, 200)
    return JSONResponse([{"success": {"/config/linkbutton": True}}])


@app.post("/route/api")
async def new_key(request: Request):
    stop = _limited(request) or _bearer(request)
    if stop is not None:
        _log(request, stop.status_code)
        return stop
    body = await request.json()
    if time.time() - STATE["link_at"] > 30:
        _log(request, 200, "link button not pressed")
        return JSONResponse([{"error": {"type": 101, "address": "", "description": "link button not pressed"}}])
    key = "key-" + secrets.token_urlsafe(16)
    STATE["keys"].add(key)
    _log(request, 200, str(body.get("devicetype") or ""))
    return JSONResponse([{"success": {"username": key}}])


def _guard(request: Request):
    stop = _limited(request) or _bearer(request)
    if stop is not None:
        return stop
    if request.headers.get("hue-application-key") not in STATE["keys"]:
        return JSONResponse({"errors": [{"description": "unauthorized user"}], "data": []}, 403)
    return None


def _of_type(kind: str) -> list:
    return [r for r in STATE["home"].values() if r["type"] == kind]


@app.get("/route/clip/v2/resource")
async def everything(request: Request):
    stop = _guard(request)
    _log(request, stop.status_code if stop else 200)
    return stop or JSONResponse({"errors": [], "data": list(STATE["home"].values())})


@app.get("/route/clip/v2/resource/{kind}")
async def of_kind(kind: str, request: Request):
    stop = _guard(request)
    _log(request, stop.status_code if stop else 200)
    return stop or JSONResponse({"errors": [], "data": _of_type(kind)})


@app.get("/route/clip/v2/resource/{kind}/{rid}")
async def one(kind: str, rid: str, request: Request):
    stop = _guard(request)
    _log(request, stop.status_code if stop else 200)
    if stop:
        return stop
    r = STATE["home"].get(rid)
    if r is None or r["type"] != kind:
        return JSONResponse({"errors": [{"description": f"Not found: /{kind}/{rid}"}], "data": []}, 404)
    return JSONResponse({"errors": [], "data": [r]})


def _apply(light: dict, change: dict) -> None:
    if "on" in change:
        light["on"] = {"on": bool(change["on"].get("on"))}
    if "dimming" in change and "dimming" in light:
        light["dimming"]["brightness"] = float(change["dimming"]["brightness"])
    if "color" in change and "color" in light:
        light["color"]["xy"] = dict(change["color"]["xy"])
        if "color_temperature" in light:
            light["color_temperature"]["mirek_valid"] = False
    if "color_temperature" in change and "color_temperature" in light:
        light["color_temperature"]["mirek"] = int(change["color_temperature"]["mirek"])
        light["color_temperature"]["mirek_valid"] = True


def _lights_under(owner: dict) -> list:
    home = STATE["home"]
    if owner["rtype"] == "bridge_home":
        return _of_type("light")
    group = home.get(owner["rid"]) or {}
    out = []
    for c in group.get("children") or []:
        if c["rtype"] == "light":
            out.append(home[c["rid"]])
        elif c["rtype"] == "device":
            out += [home[s["rid"]] for s in home[c["rid"]]["services"] if s["rtype"] == "light"]
    return out


def _settle_groups() -> None:
    """Each grouped_light says on when any of its lights is, and their mean brightness."""
    for g in _of_type("grouped_light"):
        ls = _lights_under(g["owner"])
        g["on"] = {"on": any(l["on"]["on"] for l in ls)}
        lit = [l["dimming"]["brightness"] for l in ls if l["on"]["on"] and "dimming" in l]
        if "dimming" in g:
            g["dimming"] = {"brightness": round(sum(lit) / len(lit), 1) if lit else 0.0}


@app.put("/route/clip/v2/resource/{kind}/{rid}")
async def change(kind: str, rid: str, request: Request):
    stop = _guard(request)
    body = await request.json()
    _log(request, stop.status_code if stop else 200, str(body))
    if stop:
        return stop
    r = STATE["home"].get(rid)
    if r is None or r["type"] != kind:
        return JSONResponse({"errors": [{"description": f"Not found: /{kind}/{rid}"}], "data": []}, 404)
    if kind == "light":
        _apply(r, body)
    elif kind == "grouped_light":
        for l in _lights_under(r["owner"]):
            _apply(l, body)
    elif kind == "scene":
        if (body.get("recall") or {}).get("action") != "active":
            return JSONResponse({"errors": [{"description": "recall.action must be active"}], "data": []}, 400)
        for s in _of_type("scene"):
            if s["group"]["rid"] == r["group"]["rid"]:
                s["status"]["active"] = "inactive"
        for a in r["actions"]:
            _apply(STATE["home"][a["target"]["rid"]], a["action"])
        r["status"]["active"] = "static"
    else:
        return JSONResponse({"errors": [{"description": f"{kind} cannot be changed here"}], "data": []}, 405)
    _settle_groups()
    return JSONResponse({"errors": [], "data": [{"rid": rid, "rtype": kind}]})


@app.post("/_expire")
async def expire():
    for t in STATE["access"]:
        STATE["access"][t] = 0
    return {"ok": True}


@app.post("/_lapse")
async def lapse():
    for t in STATE["refresh"]:
        STATE["refresh"][t] = False
    STATE["lapsed"] = True
    return {"ok": True}


@app.post("/_forget_keys")
async def forget_keys():
    STATE["keys"].clear()
    return {"ok": True}


@app.post("/_ratelimit")
async def ratelimit(request: Request):
    body = await request.json()
    STATE["ratelimit"] = {"times": int(body.get("times") or 1), "after": str(body.get("after") or "1")}
    return {"ok": True}


@app.post("/_fail")
async def fail(request: Request):
    body = await request.json()
    STATE["fail"] = {"path": str(body.get("path") or "/route/api/0/config"),
                     "status": int(body.get("status") or 521), "times": int(body.get("times", 1))}
    return {"ok": True}


@app.post("/_home")
async def which_home(request: Request):
    body = await request.json()
    which = str(body.get("home") or "small")
    if which not in HOMES:
        return JSONResponse({"error": f"no home {which!r}; there are {', '.join(HOMES)}"}, 400)
    _settled_home(which)
    return {"ok": True}


@app.post("/_press_button")
async def press_button():
    STATE["link_at"] = time.time()
    return {"ok": True}


@app.get("/_calls")
async def calls():
    return STATE["calls"]


@app.get("/_lights")
async def lights():
    return {l["metadata"]["name"]: {"on": l["on"]["on"], "brightness": (l.get("dimming") or {}).get("brightness"),
                                    "xy": (l.get("color") or {}).get("xy"),
                                    "mirek": (l.get("color_temperature") or {}).get("mirek")
                                    if (l.get("color_temperature") or {}).get("mirek_valid") else None}
            for l in _of_type("light")}


_settled_home()


def main() -> None:
    import uvicorn

    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8098)
    args = ap.parse_args()
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
