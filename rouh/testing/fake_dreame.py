"""A stand-in for the Dreamehome cloud and one robot on it, so Rouh's Dreame connection can be driven end to end.

The same idea as `fake_hue.py`: a real HTTP server in front of the real client (`rouh/dreame.py`),
so what a check proves is what went over the wire. Every region is a path of its own,
``/<region>/...`` (`dreame.base_url`), and the account lives in `HOME_REGION` only, so Automatic
really has to look for it. It speaks enough of the cloud, in its own shapes:

- the sign-in: ``POST /<region>/dreame-auth/oauth/token``, a form with the app's Basic auth. The
  password grant takes `EMAIL` and the MD5 of `PASSWORD` with the app's salt; the refresh grant
  takes the last refresh token given, once (a used one is refused, as a rotating one is). Both
  give an access token for `ACCESS_LIFE` seconds.
- the devices: ``POST /<region>/dreame-user-iot/iotuserbind/device/listV2``: one robot, an L10s
  Pro Ultra Heat called Golden Retriever.
- the robot: ``POST /<region>/dreame-iot-com-10000/device/sendCommand`` with ``get_properties``,
  ``set_properties`` and ``action``, against a robot that cleans, pauses, docks, charges, washes
  and dries its mop pads and empties its bin, with time and area that grow while it cleans.
- the map: action 6.1 answers with a map file's name and key; ``getDownloadUrl`` gives an address
  under ``/files/`` with the map, encrypted as a real one is, naming five rooms.

Every call needs ``Dreame-Auth`` with a live access token (401 without one).

And the same robot as a Mi Home account sees it (`rouh/dreame_mi.py`), under ``/mi``:

- the Xiaomi sign-in under ``/mi/account`` (account.xiaomi.com): ``serviceLogin``,
  ``serviceLoginAuth2`` taking `MI_USER` and the upper-case MD5 of `MI_PASSWORD`, and ``/mi/sts``,
  which gives the ``serviceToken``. A ``passToken`` cookie signs in again with no password.
- the two-step code when ``/_mi {"two_step": true}``: ``identity/list`` (email only),
  ``verifyEmail``, ``sendEmailTicket``, and ``verifyEmail`` with the ticket `MI_CODE`.
- the picture when ``/_mi {"captcha": true}``: an SVG reading `MI_CAPTCHA`, and an ``ick`` cookie.
- the API under ``/mi/<country>/app/...``, the account's devices in `MI_REGION` only, every
  call's fields RC4-encrypted and signed as the app does (checked here), its answer encrypted back:
  ``home/device_list``, ``v2/homeroom/gethome``, ``v2/home/rpc/<did>`` (the same robot) and
  ``v2/home/get_interim_file_url``. An unknown serviceToken is a 401.
- ``/_mi {"expire": true}``: every serviceToken stops working; ``{"lapse": true}``: passTokens are
  refused too. ``GET /_mi`` says what it has seen.

Knobs, each a POST:

- ``/_expire``: every access token stops working now (the next call is a 401, a refresh follows).
- ``/_lapse``: refresh tokens are refused from now on.
- ``/_password {"password"}``: the account's password is changed, so the kept one is refused.
- ``/_captcha``: the next password sign-in asks for a captcha.
- ``/_offline {"on"}``: the robot stops answering (cloud code 80001).
- ``/_error {"code"}``: the robot stops with that error (0 clears it).
- ``/_norooms {"on"}``: the map has no rooms.

And ``GET /_calls`` (every call: path, method, the token's last four), ``/_robot`` (the robot's
properties and what it was asked to do) and ``/_reset``.

Point ``ROUH_DREAME_API`` at ``http://127.0.0.1:<port>``.

    python -m rouh.testing.fake_dreame --port 8099
"""
from __future__ import annotations

import argparse
import base64
import copy
import hashlib
import json
import secrets
import time
import urllib.parse
import zlib

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse

EMAIL = "alex@example.com"
PASSWORD = "stand-in-dreame-password-41"
HOME_REGION = "eu"
ACCESS_LIFE = 7200
BASIC = "Basic ZHJlYW1lX2FwcHYxOkFQXmR2QHpAU1FZVnhOODg="
SALT = "RAylYC%fmSKp7%Tq"
DID = "-112233445"
MODEL = "dreame.vacuum.r2338a"
MAP_IV = "NRwnBj5FsNPgBNbT"
MAP_KEY = "standinmapkey"

MI_USER = "alex.mi@example.com"
MI_PASSWORD = "stand-in-mi-password-73"
MI_REGION = "de"
MI_CODE = "424242"
MI_CAPTCHA = "W7KQ"
MI_SSECURITY = base64.b64encode(b"stand-in-ssecurity!").decode()
MI_USER_ID = "6611223344"
MI_DID = "386400111"

ROOMS = [
    {"id": 1, "name": "Living room"}, {"id": 2, "type": 4}, {"id": 3, "name": "Kids' room"},
    {"id": 4, "type": 6}, {"id": 5, "type": 12},
]


def _robot() -> dict:
    return {
        "2.1": 13, "2.2": 0, "3.1": 100, "3.2": 3, "4.1": 6, "4.2": 0, "4.3": 0, "4.4": 1, "4.5": 2,
        "4.6": 0, "4.7": 0, "4.23": (2 << 16) | (20 << 8) | 0, "4.25": 0, "4.26": 0,
        "9.2": 87, "10.2": 64, "11.1": 52, "15.5": 0, "16.1": 30, "18.1": 41,
        "27.1": 0, "27.2": 0, "27.3": 0, "28.1": 16,
    }


STATE: dict = {}


def reset() -> None:
    STATE.clear()
    STATE.update({
        "password": PASSWORD, "access": {}, "refresh": "", "lapse": False, "captcha": False,
        "offline": False, "norooms": False, "robot": _robot(), "asked": [], "calls": [],
        "started_at": 0.0, "until": {},
        "mi": {"two_step": False, "captcha": False, "service": {}, "pass": {}, "contexts": {}, "icks": {},
               "lapse": False, "sent": 0, "signins": 0, "renewals": 0, "codes_tried": 0},
    })


reset()
app = FastAPI()


def _log(request: Request, status: int, note: str = "") -> None:
    token = request.headers.get("dreame-auth") or ""
    STATE["calls"].append({"at": time.time(), "method": request.method, "path": request.url.path,
                           "status": status, "token": token[-4:], "note": note})


def _refuse(request: Request, status: int, body: dict, note: str = "") -> JSONResponse:
    _log(request, status, note)
    return JSONResponse(body, status_code=status)


def _tokens() -> dict:
    access = "AT-" + secrets.token_urlsafe(18)
    refresh = "RT-" + secrets.token_urlsafe(18)
    STATE["access"][access] = time.time() + ACCESS_LIFE
    STATE["refresh"] = refresh
    return {"access_token": access, "refresh_token": refresh, "expires_in": ACCESS_LIFE, "token_type": "bearer",
            "uid": "EU100001", "tenant_id": "000000", "country": "BG", "region": HOME_REGION, "lang": "en",
            "domain": f"{HOME_REGION}.iot.dreame.tech:13267"}


@app.post("/{region}/dreame-auth/oauth/token")
async def token(region: str, request: Request):
    if request.headers.get("authorization") != BASIC:
        return _refuse(request, 401, {"error": "unauthorized", "error_description": "Bad client credentials"})
    form = dict(urllib.parse.parse_qsl((await request.body()).decode()))
    grant = form.get("grant_type")
    if grant == "password":
        if STATE["captcha"]:
            STATE["captcha"] = False
            return _refuse(request, 400, {"error": "invalid_grant",
                                          "error_description": "Captcha verification required"}, "captcha")
        good = hashlib.md5((STATE["password"] + SALT).encode()).hexdigest()
        if region != HOME_REGION or form.get("username") != EMAIL or form.get("password") != good:
            return _refuse(request, 400, {"error": "invalid_grant", "error_description": "Bad credentials"},
                           "password refused")
        _log(request, 200, "password")
        return _tokens()
    if grant == "refresh_token":
        if STATE["lapse"] or not STATE["refresh"] or form.get("refresh_token") != STATE["refresh"]:
            return _refuse(request, 401, {"error": "invalid_grant",
                                          "error_description": "Invalid refresh token"}, "refresh refused")
        _log(request, 200, "refresh")
        return _tokens()
    return _refuse(request, 400, {"error": "unsupported_grant_type"})


def _authorised(region: str, request: Request):
    tok = request.headers.get("dreame-auth") or ""
    if region != HOME_REGION or STATE["access"].get(tok, 0) < time.time():
        return _refuse(request, 401, {"code": 401, "msg": "token invalid", "success": False})
    return None


@app.post("/{region}/dreame-user-iot/iotuserbind/device/listV2")
async def devices(region: str, request: Request):
    no = _authorised(region, request)
    if no:
        return no
    _log(request, 200)
    record = {"id": 7, "did": DID, "model": MODEL, "customName": "Golden Retriever", "mac": "AA:BB:CC:00:11:22",
              "masterUid": "EU100001", "bindDomain": "10000.mt.eu.iot.dreame.tech:19973", "online": True,
              "deviceInfo": {"displayName": "L10s Pro Ultra Heat"}, "property": "{}"}
    return {"code": 0, "success": True, "msg": "ok", "data": {"page": {"records": [record], "total": 1}}}


def _tick() -> None:
    """The robot's clean moving on: time and area while cleaning, then back to the dock."""
    r = STATE["robot"]
    now = time.time()
    if r["2.1"] in (1, 7, 12) and STATE["started_at"]:
        run = now - STATE["started_at"]
        r["4.2"] = int(run // 20)
        r["4.3"] = int(run // 6)
        r["3.1"] = max(20, 100 - int(run // 30))
    for key, (at, value) in list(STATE["until"].items()):
        if now >= at:
            r[key] = value
            del STATE["until"][key]
            if key == "2.1" and value == 6:
                r["4.1"], r["3.2"], r["4.7"] = 6, 1, 0


def _set_state(state: int, status: int, task: int | None = None) -> None:
    r = STATE["robot"]
    r["2.1"], r["4.1"] = state, status
    if task is not None:
        r["4.7"] = task
    r["3.2"] = 2 if state not in (6, 13) else (3 if state == 13 else 1)


def _clean_state() -> int:
    """What the robot says while cleaning, from its mode: vacuuming, mopping, or both."""
    mode = STATE["robot"]["4.23"] & 0x03
    return {0: 12, 1: 7, 2: 1}.get(mode, 12)


def _action(siid: int, aiid: int, ins: list) -> dict:
    r = STATE["robot"]
    STATE["asked"].append({"siid": siid, "aiid": aiid, "in": ins})
    if (siid, aiid) == (2, 1):
        if r["2.1"] == 3:
            _set_state(_clean_state(), 2)
        else:
            STATE["started_at"] = time.time()
            r["4.2"], r["4.3"] = 0, 0
            _set_state(_clean_state(), 2, 1)
    elif (siid, aiid) == (2, 2):
        _set_state(3, 1)
    elif (siid, aiid) == (3, 1):
        _set_state(5, 3, 0)
        STATE["until"]["2.1"] = (time.time() + 6, 6)
    elif (siid, aiid) == (4, 1):
        values = {p.get("piid"): p.get("value") for p in ins}
        if values.get(1) == 18:
            STATE["started_at"] = time.time()
            r["4.2"], r["4.3"] = 0, 0
            _set_state(_clean_state(), 18, 3)
    elif (siid, aiid) == (4, 4):
        value = next((p.get("value") for p in ins if p.get("piid") == 10), "")
        r["4.25"] = {"2,1": 1, "3,1": 2, "3,0": 0, "1,0": 4}.get(value, r["4.25"])
        if value == "2,1":
            STATE["until"]["4.25"] = (time.time() + 20, 0)
    elif (siid, aiid) == (15, 1):
        r["15.5"] = 1
        STATE["until"]["15.5"] = (time.time() + 8, 0)
    elif (siid, aiid) == (6, 1):
        return {"code": 0, "out": [{"piid": 3, "value": f"ali_dreame/{MODEL}/EU100001/{DID}/0,{MAP_KEY}"},
                                   {"piid": 5, "value": str(int(time.time() * 1000))}]}
    return {"code": 0, "out": []}


@app.post("/{region}/dreame-iot-com-10000/device/sendCommand")
async def command(region: str, request: Request):
    no = _authorised(region, request)
    if no:
        return no
    body = await request.json()
    data = body.get("data") or {}
    method, params = data.get("method"), data.get("params")
    if STATE["offline"]:
        _log(request, 200, f"{method} offline")
        return {"code": 80001, "msg": "设备可能不在线，指令发送超时", "success": False}
    result = _rpc(method, params)
    if result is None:
        _log(request, 200, f"{method} unknown")
        return {"code": -1, "msg": "unknown method", "success": False}
    _log(request, 200, method)
    return {"code": 0, "success": True, "msg": "ok", "data": {"id": data.get("id"), "result": result}}


def _rpc(method, params):
    """One MIoT call on the robot, from either cloud: its result, or None for a method it lacks."""
    _tick()
    r = STATE["robot"]
    if method == "get_properties":
        result = []
        for p in params or []:
            key = f"{p['siid']}.{p['piid']}"
            if key in r:
                result.append({"did": p.get("did"), "siid": p["siid"], "piid": p["piid"], "code": 0, "value": r[key]})
            else:
                result.append({"did": p.get("did"), "siid": p["siid"], "piid": p["piid"], "code": -1})
    elif method == "set_properties":
        result = []
        for p in params or []:
            key = f"{p['siid']}.{p['piid']}"
            r[key] = p.get("value")
            STATE["asked"].append({"set": key, "value": p.get("value")})
            result.append({"did": p.get("did"), "siid": p["siid"], "piid": p["piid"], "code": 0})
    elif method == "action":
        result = _action(int(params["siid"]), int(params["aiid"]), params.get("in") or [])
    else:
        return None
    return result


def _map_text() -> str:
    """A map frame as the robot uploads one: header, an empty grid, JSON naming the rooms; packed,
    encrypted under MAP_KEY with the model's IV, and base64 with the url-safe letters."""
    seg = {}
    for room in ([] if STATE["norooms"] else ROOMS):
        one: dict = {"type": room.get("type", 0), "index": 0, "nei_id": []}
        if room.get("name"):
            one["name"] = base64.b64encode(room["name"].encode()).decode()
        seg[str(room["id"])] = one
    width, height = 4, 3
    header = bytearray(27)
    header[0:2] = (1).to_bytes(2, "little")
    header[17:19] = (50).to_bytes(2, "little")
    header[19:21] = width.to_bytes(2, "little")
    header[21:23] = height.to_bytes(2, "little")
    tail = json.dumps({"seg_inf": seg, "timestamp_ms": int(time.time() * 1000)}).encode()
    raw = zlib.compress(bytes(header) + bytes(width * height) + tail)
    raw += b"\0" * (-len(raw) % 16)
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    enc = Cipher(algorithms.AES(hashlib.sha256(MAP_KEY.encode()).hexdigest()[:32].encode()),
                 modes.CBC(MAP_IV.encode())).encryptor()
    data = enc.update(raw) + enc.finalize()
    return base64.b64encode(data).decode().replace("/", "_").replace("+", "-")


@app.post("/{region}/dreame-user-iot/iotfile/getDownloadUrl")
async def download_url(region: str, request: Request):
    no = _authorised(region, request)
    if no:
        return no
    body = await request.json()
    _log(request, 200, str(body.get("filename") or ""))
    base = str(request.base_url).rstrip("/")
    return {"code": 0, "success": True, "data": f"{base}/files/{urllib.parse.quote(str(body.get('filename')), safe='')}?sig=x"}


@app.get("/files/{name:path}")
async def file(name: str, request: Request):
    _log(request, 200)
    return PlainTextResponse(_map_text())


# --- Mi Home: the Xiaomi account and its API --------------------------------------------------

def _mi_json(body: dict, request: Request, note: str = "", cookies: dict | None = None):
    _log(request, 200, note)
    out = PlainTextResponse("&&&START&&&" + json.dumps(body))
    for k, v in (cookies or {}).items():
        out.set_cookie(k, v, path="/")
    return out


def _mi_cookie(request: Request, name: str) -> str:
    return request.cookies.get(name) or ""


def _mi_signed_in(request: Request, note: str):
    """The answer that ends a sign-in: ssecurity and the address that gives the serviceToken."""
    mi = STATE["mi"]
    pass_token = "PT-" + secrets.token_urlsafe(12)
    mi["pass"][pass_token] = True
    base = str(request.base_url).rstrip("/")
    nonce = secrets.token_urlsafe(8)
    return _mi_json({"code": 0, "ssecurity": MI_SSECURITY, "userId": MI_USER_ID, "cUserId": "c" + MI_USER_ID,
                     "passToken": pass_token, "location": f"{base}/mi/sts?nonce={nonce}&d=x"},
                    request, note, {"passToken": pass_token, "userId": MI_USER_ID})


@app.get("/mi/account/pass/serviceLogin")
async def mi_service_login(request: Request):
    mi = STATE["mi"]
    token = _mi_cookie(request, "passToken")
    if token and token in mi["pass"] and not mi["lapse"]:
        mi["renewals"] += 1
        return _mi_signed_in(request, "passToken")
    return _mi_json({"code": 70016, "_sign": "stand-in-sign", "desc": "login required"}, request, "sign")


@app.post("/mi/account/pass/serviceLoginAuth2")
async def mi_login(request: Request):
    mi = STATE["mi"]
    form = dict(urllib.parse.parse_qsl((await request.body()).decode()))
    if mi["captcha"]:
        ick = _mi_cookie(request, "ick")
        if not (form.get("captCode") and ick in mi["icks"] and form["captCode"].upper() == MI_CAPTCHA):
            return _mi_json({"code": 87001, "captchaUrl": "/pass/getCode?icodeType=login"}, request, "captcha")
        mi["captcha"] = False
    good = hashlib.md5(MI_PASSWORD.encode()).hexdigest().upper()
    if form.get("user") != MI_USER or form.get("hash") != good or form.get("sid") != "xiaomiio":
        return _mi_json({"code": 70016, "desc": "Invalid username or password"}, request, "password refused")
    if mi["two_step"]:
        context = "CTX" + secrets.token_hex(6)
        mi["contexts"][context] = {"sent": False}
        return _mi_json({"code": 0, "notificationUrl": f"/fe/service/identity/authStart?sid=xiaomiio&context={context}"},
                        request, "two-step")
    mi["signins"] += 1
    return _mi_signed_in(request, "password")


@app.get("/mi/account/pass/getCode")
async def mi_captcha(request: Request):
    ick = "ICK" + secrets.token_hex(6)
    STATE["mi"]["icks"][ick] = True
    _log(request, 200, "captcha picture")
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" width="160" height="56"><rect width="160" height="56" '
           'fill="#eef"/><text x="22" y="40" font-family="monospace" font-size="34" fill="#224">'
           f'{MI_CAPTCHA}</text></svg>')
    out = PlainTextResponse(svg, media_type="image/svg+xml")
    out.set_cookie("ick", ick, path="/")
    return out


@app.get("/mi/account/fe/service/identity/authStart")
async def mi_auth_start(request: Request):
    _log(request, 200)
    return PlainTextResponse("<html>Verify your identity</html>", media_type="text/html")


@app.get("/mi/account/identity/list")
async def mi_identity_list(request: Request):
    context = request.query_params.get("context", "")
    if context not in STATE["mi"]["contexts"]:
        return _mi_json({"code": 70002, "desc": "no such check"}, request, "identity refused")
    return _mi_json({"code": 2, "flag": 8, "options": [8]}, request, "identity",
                    {"identity_session": "IS" + secrets.token_hex(6)})


@app.get("/mi/account/identity/auth/verifyEmail")
async def mi_verify_email_start(request: Request):
    if not _mi_cookie(request, "identity_session"):
        return _mi_json({"code": 70002}, request, "no identity session")
    return _mi_json({"code": 0, "maskedEmail": "pe***@example.com"}, request, "verify start")


@app.post("/mi/account/identity/auth/sendEmailTicket")
async def mi_send_ticket(request: Request):
    context = request.query_params.get("context", "")
    if context not in STATE["mi"]["contexts"] or not _mi_cookie(request, "identity_session"):
        return _mi_json({"code": 70002}, request, "send refused")
    STATE["mi"]["sent"] += 1
    return _mi_json({"code": 0}, request, "code sent")


@app.post("/mi/account/identity/auth/verifyEmail")
async def mi_verify_email(request: Request):
    mi = STATE["mi"]
    context = request.query_params.get("context", "")
    form = dict(urllib.parse.parse_qsl((await request.body()).decode()))
    mi["codes_tried"] += 1
    if context not in mi["contexts"] or form.get("ticket") != MI_CODE:
        return _mi_json({"code": 70014, "desc": "Wrong code"}, request, "code refused")
    mi["contexts"].pop(context, None)
    pass_token = "PT-" + secrets.token_urlsafe(12)
    mi["pass"][pass_token] = True
    base = str(request.base_url).rstrip("/")
    return _mi_json({"code": 0, "location": f"{base}/mi/account/identity/result/done?pt={pass_token}"},
                    request, "code taken")


@app.get("/mi/account/identity/result/done")
async def mi_identity_done(request: Request):
    _log(request, 200, "identity done")
    out = PlainTextResponse("ok")
    out.set_cookie("passToken", request.query_params.get("pt", ""), path="/")
    out.set_cookie("userId", MI_USER_ID, path="/")
    return out


@app.get("/mi/sts")
async def mi_sts(request: Request):
    token = "ST-" + secrets.token_urlsafe(16)
    STATE["mi"]["service"][token] = True
    _log(request, 200, "serviceToken")
    out = PlainTextResponse("ok")
    out.set_cookie("serviceToken", token, path="/")
    return out


def _rc4(key: bytes, data: bytes) -> bytes:
    from rouh.dreame_mi import rc4

    return rc4(key, data)


def _mi_sig(path: str, params: list[tuple[str, str]], sn: str) -> str:
    text = "&".join(["POST", path] + [f"{k}={v}" for k, v in params] + [sn])
    return base64.b64encode(hashlib.sha1(text.encode()).digest()).decode()


@app.post("/mi/{country}/app/{path:path}")
async def mi_api(country: str, path: str, request: Request):
    mi = STATE["mi"]
    if not mi["service"].get(_mi_cookie(request, "serviceToken")) or _mi_cookie(request, "userId") != MI_USER_ID:
        _log(request, 401, "serviceToken refused")
        return PlainTextResponse('{"code":401,"message":"auth err"}', status_code=401)
    form = urllib.parse.parse_qsl((await request.body()).decode())
    fields = dict(form)
    if fields.get("ssecurity") != MI_SSECURITY:
        _log(request, 200, "wrong ssecurity")
        return JSONResponse({"code": 3, "message": "invalid signature"})
    sn = base64.b64encode(hashlib.sha256(base64.b64decode(MI_SSECURITY) + base64.b64decode(fields["_nonce"])).digest()).decode()
    key = base64.b64decode(sn)
    encrypted = [(k, v) for k, v in form if k not in ("signature", "ssecurity", "_nonce")]
    if _mi_sig("/" + path, encrypted, sn) != fields.get("signature"):
        _log(request, 200, "bad signature")
        return JSONResponse({"code": 3, "message": "invalid signature"})
    plain = {k: _rc4(key, base64.b64decode(v)).decode() for k, v in encrypted}
    if _mi_sig("/" + path, [(k, v) for k, v in plain.items() if k != "rc4_hash__"], sn) != plain.get("rc4_hash__"):
        _log(request, 200, "bad rc4 hash")
        return JSONResponse({"code": 3, "message": "invalid signature"})
    params = json.loads(plain.get("data") or "{}")
    mine = country == MI_REGION
    if path == "home/device_list":
        devices = [{"did": MI_DID, "name": "Golden Retriever", "model": MODEL, "isOnline": True,
                    "mac": "AA:BB:CC:00:11:22", "uid": int(MI_USER_ID)}] if mine else []
        out = {"code": 0, "message": "ok", "result": {"list": devices}}
    elif path == "v2/homeroom/gethome":
        out = {"code": 0, "message": "ok", "result": {"homelist": []}}
    elif path == f"v2/home/rpc/{MI_DID}" and mine:
        if STATE["offline"]:
            out = {"code": -2, "message": "device offline"}
        else:
            result = _rpc(params.get("method"), params.get("params"))
            out = {"code": -1, "message": "unknown method"} if result is None else \
                {"code": 0, "message": "ok", "result": result}
    elif path == "v2/home/get_interim_file_url" and mine:
        base = str(request.base_url).rstrip("/")
        name = urllib.parse.quote(str(params.get("obj_name") or ""), safe="")
        out = {"code": 0, "message": "ok", "result": {"url": f"{base}/files/{name}?sig=x", "expires_time": 0}}
    else:
        out = {"code": -8, "message": "not found"}
    _log(request, 200, f"mi {path} {params.get('method') or ''}".strip())
    return PlainTextResponse(base64.b64encode(_rc4(key, json.dumps(out).encode())).decode())


@app.post("/_mi")
async def mi_knobs(request: Request):
    mi = STATE["mi"]
    body = await request.json()
    for k in ("two_step", "captcha", "lapse"):
        if k in body:
            mi[k] = bool(body[k])
    if body.get("expire"):
        mi["service"].clear()
    if body.get("lapse"):
        mi["pass"].clear()
        mi["service"].clear()
    return {"ok": True}


@app.get("/_mi")
async def mi_seen():
    mi = STATE["mi"]
    return {k: mi[k] for k in ("two_step", "captcha", "lapse", "sent", "signins", "renewals", "codes_tried")}


@app.post("/_expire")
async def expire():
    STATE["access"].clear()
    return {"ok": True}


@app.post("/_lapse")
async def lapse():
    STATE["lapse"] = True
    STATE["access"].clear()
    return {"ok": True}


@app.post("/_password")
async def password(request: Request):
    STATE["password"] = str((await request.json()).get("password") or "changed")
    return {"ok": True}


@app.post("/_captcha")
async def captcha():
    STATE["captcha"] = True
    return {"ok": True}


@app.post("/_offline")
async def offline(request: Request):
    STATE["offline"] = bool((await request.json()).get("on", True))
    return {"ok": True}


@app.post("/_error")
async def error(request: Request):
    code = int((await request.json()).get("code") or 0)
    r = STATE["robot"]
    r["2.2"] = code
    if code:
        _set_state(4, 12)
    else:
        _set_state(13, 6)
    return {"ok": True}


@app.post("/_norooms")
async def norooms(request: Request):
    STATE["norooms"] = bool((await request.json()).get("on", True))
    return {"ok": True}


@app.post("/_reset")
async def reset_all():
    reset()
    return {"ok": True}


@app.get("/_calls")
async def calls():
    return STATE["calls"]


@app.get("/_robot")
async def robot():
    _tick()
    return {"properties": copy.deepcopy(STATE["robot"]), "asked": STATE["asked"]}


def main() -> None:
    import uvicorn

    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8099)
    args = ap.parse_args()
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
