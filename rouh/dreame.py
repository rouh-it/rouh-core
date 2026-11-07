"""A Dreame robot vacuum through the Dreamehome cloud or Mi Home's: the sign-in, the robot's state, and commands.

Petar, 17 October 2026: "I have robot for cleaning, can we connect that too?" The robot it was built
for is a Dreame L10s Pro Ultra Heat (`dreame.vacuum.r2338a`), paired in the Dreamehome app. It vacuums and mops, and its base empties the dust bin, washes the mop pads and
dries them with hot air.

**Where the protocol comes from.** Dreame publishes no API, and its robots take no commands on the
home network, so Rouh talks to the Dreamehome cloud as the app does. The shapes are the ones the
community worked out, in Tasshack/dreame-vacuum (MIT, the reference the others build on), its fork
chriguschneider/dreame-vacuum, and sandraschi/dreame-mcp, which wraps Tasshack's. Rouh speaks the
request format the Dreamehome iOS app 2.1.9 uses, as the chrigu fork does, over ordinary TLS with
the server's certificate checked. Tasshack's version 2.0 imitates the current app's handshake byte
for byte with a TLS client of its own that, as its issue 1918 found on 15 October 2026, does not
check the server at all; that is not copied here. The older format still answers, and if Dreame
retires it the sign-in will start failing with a plain sentence rather than quietly.

**The sign-in.** Only an email and password Dreamehome account can sign in this way; one made with
Apple or Google sign-in has no password, and the page says so in one line when the sign-in is
refused. The password is sent as the app sends it (an MD5 of it with the app's salt), kept sealed
(`encryption.SecretBox`) so a sign-in that lapses is made again without asking, and never said
anywhere. The access token is renewed with the refresh token ten minutes before it ends and once
on a 401; when the refresh token is refused the kept password signs in again; when that is refused
too the connection is marked lapsed (`lapse`), which the page, Anatomy's board and the tool say.
A captcha or a code asked for stops the sign-in with what to do (`NeedsCheck`).

**The region.** A Dreamehome account lives in one of six clouds (`REGIONS`). The page's choice
starts at Automatic, which tries Europe first and then the others until one knows the account.

**The robot.** Its state is MIoT properties (service and property numbers, `P`) read with
`get_properties` through the cloud's `sendCommand`; commands are MIoT actions (`A`). The rooms
come from the map the robot uploads when asked (`read_rooms`): an AES-encrypted, zlib-packed frame
whose JSON tail names each room (`seg_inf`). The map itself is not drawn: it cannot be checked
against this robot from here, and a wrong one is worse than none.

**Whose.** The account, its password, its tokens and the robot are the one person's who typed
them; every query names their organisation and them.

**Mi Home.** A Dreame robot paired in Xiaomi's Mi Home app answers through the Xiaomi cloud
instead, with the same MIoT numbers. That account's sign-in, its two-step code and its signed
calls are `rouh/dreame_mi.py`; `cloud_for` picks the cloud a connection's `account` says.

`ROUH_DREAME_API` points every call at a stand-in (`rouh/testing/fake_dreame.py`), each region a path of it.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import re
import threading
import time
import urllib.parse
import zlib

from .encryption import box as _box

log = logging.getLogger("rouh.dreame")

#: A stand-in for the Dreamehome cloud in a test world, each region a path under it; empty for the real one.
API = os.environ.get("ROUH_DREAME_API", "").rstrip("/")
PAGE = "/anatomy/connections/dreame"
TIMEOUT = 15
#: The clouds a Dreamehome account can live in, in the order Automatic tries them.
REGIONS = (("eu", "Europe"), ("ru", "Russia"), ("us", "United States"), ("sg", "Asia (Singapore)"),
           ("kr", "Korea"), ("cn", "China"))
REGION_NAMES = dict(REGIONS)
#: How long before the access token ends that it is renewed.
RENEW_BEFORE = 600.0
#: Waits after a 429 or a 5xx before trying again, in seconds; then it gives up.
RETRIES = (1.0, 2.0, 4.0)
#: `reached_at` is written at most this often.
REACHED_EVERY = 60.0
#: How old the rooms may be before the map is asked for again.
ROOMS_LIFE = 6 * 3600.0
#: The state is read again at most this often, however many pages and turns ask.
STATE_LIFE = 4.0

# What the Dreamehome iOS app 2.1.9 sends, as Tasshack/dreame-vacuum and its chrigu fork send it.
_PORT = 13267
_UA = "Dreame_Smarthome/2.1.9 (iPhone; iOS 18.4.1; Scale/3.00)"
_BASIC = "Basic ZHJlYW1lX2FwcHYxOkFQXmR2QHpAU1FZVnhOODg="
_TENANT = "000000"
_SALT = "RAylYC%fmSKp7%Tq"
_RLC_CN = "1c80b3787b2266776bcdc481f37d8fa42ba10a30af81a6df-1"

LAPSED = "Dreamehome no longer accepts Rouh's sign-in."
NOT_ACCEPTED = ("Dreamehome did not accept that email and password. Only an email and password "
                "sign-in works here, not Apple or Google sign-in.")
CHECK_ASKED = ("Dreamehome asked for an extra check, such as a code or a picture puzzle. Sign in once "
               "in the Dreamehome app on your phone, then press Connect here again.")


def lapsed_line(why: str = "") -> str:
    """What a turn says about a connection that stopped working: why, and what to press."""
    return (f"The Dreame robot needs connecting again: {why or LAPSED} ‹Owner› presses Connect in "
            f"Settings, Connections, Dreame ({PAGE}).")


class Refused(ValueError):
    """Something typed into the page that cannot be used, said for the person."""


class NotSetUp(LookupError):
    """No Dreame connection for this person."""


class Lapsed(RuntimeError):
    """Neither the refresh token nor the kept password signs in any more."""


class NeedsCheck(RuntimeError):
    """Dreamehome asked for a captcha or a code, which only the person can answer."""


class DreameError(Exception):
    """A call the cloud refused or never answered, with a sentence that can be said."""


# --- the box and the rows ---------------------------------------------------------------------

def _model():
    from .models import DreameConnection

    return DreameConnection


def connection(user_id: str, org_id: str):
    """This person's Dreame connection, or None. Both ids, always."""
    if not (user_id and org_id):
        return None
    return _model().objects.filter(user_id=str(user_id), org_id=str(org_id)).first()


def _set(conn, **fields) -> None:
    fields["updated_at"] = time.time()
    _model().objects.filter(id=conn.id, user_id=conn.user_id, org_id=conn.org_id).update(**fields)
    for k, v in fields.items():
        setattr(conn, k, v)


def lapse(conn, why: str = LAPSED) -> None:
    """Mark the connection as no longer working, saying why. Connecting again clears it."""
    _set(conn, lapsed_at=time.time(), lapsed_said=why)
    log.info("dreame: connection %s for user %s lapsed", conn.id, conn.user_id)


# --- the cloud ----------------------------------------------------------------------------------

def base_url(region: str) -> str:
    """The cloud for one region: `https://eu.iot.dreame.tech:13267`, or the stand-in's region."""
    if API:
        return f"{API}/{region}"
    return f"https://{region}.iot.dreame.tech:{_PORT}"


def _headers(region: str, tenant: str = "", token: str = "", json_body: bool = False) -> dict:
    h = {"Accept": "*/*", "Accept-Language": "en-US;q=0.8", "Accept-Encoding": "gzip, deflate",
         "User-Agent": _UA, "Authorization": _BASIC, "Tenant-Id": tenant or _TENANT,
         "Content-Type": "application/json" if json_body else "application/x-www-form-urlencoded"}
    if region == "cn":
        h["Dreame-Rlc"] = _RLC_CN
    if token:
        h["Dreame-Auth"] = token
    return h


def _post(url: str, headers: dict, content: str, sleep=time.sleep):
    """One POST, a 429 or a 5xx waited out and made again. The httpx response."""
    import httpx

    tries = 0
    while True:
        try:
            r = httpx.post(url, headers=headers, content=content.encode("utf-8"), timeout=TIMEOUT)
        except httpx.HTTPError as exc:
            if tries < len(RETRIES):
                sleep(RETRIES[tries])
                tries += 1
                continue
            raise DreameError(f"The Dreamehome cloud could not be reached ({type(exc).__name__}).") from None
        if r.status_code not in (429, 500, 502, 503, 504) or tries >= len(RETRIES):
            return r
        log.info("dreame: %s answered %s; waiting", url.split("?")[0], r.status_code)
        sleep(RETRIES[tries])
        tries += 1


def _said_by(r) -> str:
    """The error a refusal carried, in its own words, for the log and the matching below."""
    try:
        got = r.json()
    except ValueError:
        return r.text[:200]
    if isinstance(got, dict):
        return str(got.get("error_description") or got.get("msg") or got.get("message")
                   or got.get("error") or "")[:300]
    return ""


_CHECK_WORDS = re.compile(r"captcha|verif|slider|sms|two.?factor|2fa|security code|验证", re.I)


def token_call(region: str, form: str, tenant: str = "", sleep=time.sleep) -> dict:
    """POST to Dreamehome's token endpoint. The answer, or Refused, NeedsCheck or DreameError."""
    r = _post(base_url(region) + "/dreame-auth/oauth/token", _headers(region, tenant), form, sleep)
    if r.status_code == 200:
        try:
            got = r.json()
        except ValueError:
            raise DreameError("Dreamehome's sign-in answered with something that is not JSON.") from None
        if isinstance(got, dict) and got.get("access_token"):
            return got
        said = _said_by(r)
        if _CHECK_WORDS.search(said):
            raise NeedsCheck(CHECK_ASKED)
        raise DreameError("Dreamehome's sign-in answered without a token.")
    said = _said_by(r)
    if _CHECK_WORDS.search(said):
        raise NeedsCheck(CHECK_ASKED)
    if r.status_code in (400, 401, 403):
        raise Refused(said or str(r.status_code))
    raise DreameError(f"Dreamehome's sign-in answered HTTP {r.status_code}.")


def password_form(email: str, password: str) -> str:
    hashed = hashlib.md5((password + _SALT).encode("utf-8")).hexdigest()
    return ("platform=IOS&scope=all&grant_type=password&username=" + urllib.parse.quote(email, safe="")
            + "&password=" + hashed + "&type=account")


def refresh_form(token: str) -> str:
    return "platform=IOS&scope=all&grant_type=refresh_token&refresh_token=" + urllib.parse.quote(token, safe="")


def _token_fields(got: dict, now: float) -> dict:
    try:
        life = float(got.get("expires_in") or 0)
    except (TypeError, ValueError):
        life = 0.0
    out = {"access_sealed": _box().seal(str(got["access_token"])),
           "access_expires_at": now + life if life else now + 3600.0}
    if got.get("refresh_token"):
        out["refresh_sealed"] = _box().seal(str(got["refresh_token"]))
    if got.get("tenant_id"):
        out["tenant_id"] = str(got["tenant_id"])
    return out


def sign_in(email: str, password: str, region: str, sleep=time.sleep) -> tuple[str, dict]:
    """(the region that knew the account, the token answer). Automatic tries each region in turn.

    A refusal from every region raises Refused with NOT_ACCEPTED; a captcha asked for stops at once."""
    regions = [r for r, _ in REGIONS] if region in ("", "auto") else [region]
    form = password_form(email, password)
    password = ""
    refused = ""
    for r in regions:
        try:
            return r, token_call(r, form, sleep=sleep)
        except Refused as exc:
            refused = str(exc)
            log.info("dreame: the %s cloud refused the sign-in (%s)", r, refused[:120])
            continue
        except DreameError:
            if len(regions) == 1:
                raise
            log.info("dreame: the %s cloud did not answer the sign-in", r)
            continue
    raise Refused(NOT_ACCEPTED)


_LOCKS: dict[int, threading.Lock] = {}
_LOCKS_LOCK = threading.Lock()


def _lock(conn_id: int) -> threading.Lock:
    with _LOCKS_LOCK:
        return _LOCKS.setdefault(conn_id, threading.Lock())


def refresh(conn, *, force: bool = False, sleep=time.sleep):
    """Renew the access token, once even when several calls want it at the same moment.

    The refresh token first; when it is refused, the kept password; when that is refused too, the
    connection lapses. Inside the lock the row is read again, so a token another call has just
    renewed is used rather than renewed twice."""
    with _lock(conn.id):
        fresh = connection(conn.user_id, conn.org_id)
        if fresh is None or not fresh.access_sealed:
            raise NotSetUp("The Dreame robot is not connected.")
        if fresh.lapsed_at:
            raise Lapsed(lapsed_line(fresh.lapsed_said))
        if fresh.access_sealed != conn.access_sealed or (
                not force and fresh.access_expires_at - time.time() > RENEW_BEFORE):
            return fresh
        if fresh.account == "mi":
            from . import dreame_mi

            return dreame_mi.renew(fresh)
        got = None
        if fresh.refresh_sealed:
            try:
                got = token_call(fresh.region, refresh_form(_box().open_(fresh.refresh_sealed)),
                                 fresh.tenant_id, sleep=sleep)
            except Refused as exc:
                log.info("dreame: refresh refused for user %s (%s)", fresh.user_id, str(exc)[:120])
        if got is None and fresh.password_sealed:
            try:
                got = token_call(fresh.region, password_form(fresh.email, _box().open_(fresh.password_sealed)),
                                 fresh.tenant_id, sleep=sleep)
            except Refused:
                lapse(fresh, "Dreamehome no longer accepts the kept password: it may have been changed.")
                raise Lapsed(lapsed_line(fresh.lapsed_said)) from None
            except NeedsCheck:
                lapse(fresh, CHECK_ASKED)
                raise Lapsed(lapsed_line(fresh.lapsed_said)) from None
        if got is None:
            lapse(fresh)
            raise Lapsed(lapsed_line())
        _set(fresh, **_token_fields(got, time.time()))
        log.info("dreame: access token renewed for user %s", fresh.user_id)
        return fresh


class Cloud:
    """One person's Dreamehome account. Every call has the access token, renewed when it is near
    its end or refused once."""

    #: The app the account is in, as a sentence names it.
    name = "Dreamehome"

    def __init__(self, conn, *, sleep=time.sleep) -> None:
        self.conn = conn
        self._sleep = sleep
        self._id = int(time.time()) % 100000

    def _fresh(self) -> None:
        if self.conn.lapsed_at:
            raise Lapsed(lapsed_line(self.conn.lapsed_said))
        if self.conn.access_expires_at - time.time() <= RENEW_BEFORE:
            self.conn = refresh(self.conn, sleep=self._sleep)

    def _call(self, path: str, body) -> dict:
        h = _headers(self.conn.region, self.conn.tenant_id, _box().open_(self.conn.access_sealed), True)
        r = _post(f"{base_url(self.conn.region)}/{path}", h,
                  json.dumps(body, separators=(",", ":")) if body is not None else "", self._sleep)
        return r

    def api(self, path: str, body=None) -> dict:
        """One call to the cloud's API: its JSON, renewing the token once on a 401."""
        self._fresh()
        r = self._call(path, body)
        if r.status_code == 401:
            self.conn = refresh(self.conn, force=True, sleep=self._sleep)
            r = self._call(path, body)
            if r.status_code == 401:
                lapse(self.conn)
                raise Lapsed(lapsed_line())
        if r.status_code != 200:
            raise DreameError(f"The Dreamehome cloud answered HTTP {r.status_code}.")
        try:
            got = r.json()
        except ValueError:
            raise DreameError("The Dreamehome cloud answered with something that is not JSON.") from None
        if time.time() - (self.conn.reached_at or 0) > REACHED_EVERY:
            _set(self.conn, reached_at=time.time())
        return got if isinstance(got, dict) else {}

    def devices(self) -> list[dict]:
        """Every device on the account, as the cloud lists them."""
        got = self.api("dreame-user-iot/iotuserbind/device/listV2", {})
        if got.get("code") not in (0, None):
            raise DreameError(f"The Dreamehome cloud would not list the devices ({_cloud_said(got)}).")
        page = (got.get("data") or {}).get("page") or {}
        return [d for d in page.get("records") or [] if isinstance(d, dict)]

    def send(self, method: str, params) -> object:
        """One MIoT call to the robot through the cloud: its result, or DreameError."""
        did = str(self.conn.did)
        if not did:
            raise NotSetUp("Rouh has no Dreame robot to talk to yet. Press Connect again.")
        self._id += 1
        host = (self.conn.bind_domain or "").split(".")[0]
        path = f"dreame-iot-com{'-' + host if host else ''}/device/sendCommand"
        got = self.api(path, {"did": did, "id": self._id,
                              "data": {"did": did, "id": self._id, "method": method, "params": params}})
        data = got.get("data")
        if not isinstance(data, dict) or "result" not in data:
            if got.get("code") == 80001:
                raise DreameError("The robot is not answering the cloud just now: it may be offline or "
                                  "asleep. Try again in a minute.")
            raise DreameError(f"The robot did not answer ({_cloud_said(got)}).")
        return data["result"]

    def _pdid(self, siid: int, piid: int) -> str:
        """What a MIoT call names as its "did": the robot's id here, the property itself in Mi Home."""
        return str(self.conn.did)

    def get(self, keys: list[tuple[int, int]]) -> dict[tuple[int, int], object]:
        """MIoT properties by (service, property): the values the robot gave, 15 to a call."""
        out: dict[tuple[int, int], object] = {}
        for i in range(0, len(keys), 15):
            batch = [{"did": self._pdid(s, p), "siid": s, "piid": p} for s, p in keys[i:i + 15]]
            for one in self.send("get_properties", batch) or []:
                if isinstance(one, dict) and one.get("code", 0) == 0 and "value" in one:
                    out[(int(one["siid"]), int(one["piid"]))] = one["value"]
        return out

    def put(self, siid: int, piid: int, value) -> None:
        got = self.send("set_properties", [{"did": self._pdid(siid, piid), "siid": siid, "piid": piid, "value": value}])
        code = (got[0] or {}).get("code", 0) if isinstance(got, list) and got else 0
        if code != 0:
            raise DreameError(f"The robot refused that setting (code {code}).")

    def action(self, siid: int, aiid: int, ins: list | None = None) -> dict:
        got = self.send("action", {"did": self._pdid(siid, aiid), "siid": siid, "aiid": aiid, "in": ins or []})
        got = got if isinstance(got, dict) else {}
        if got.get("code", 0) != 0:
            raise DreameError(f"The robot refused that (code {got.get('code')}).")
        return got

    def file_url(self, object_name: str) -> str:
        got = self.api("dreame-user-iot/iotfile/getDownloadUrl",
                       {"did": str(self.conn.did), "model": self.conn.model, "filename": object_name,
                        "region": self.conn.region})
        url = got.get("data")
        return url if isinstance(url, str) else ""


def _cloud_said(got: dict) -> str:
    return str(got.get("msg") or got.get("message") or f"code {got.get('code')}")[:160]


def cloud_for(conn, *, sleep=time.sleep) -> Cloud:
    """The cloud this connection's robot answers through: Dreamehome's, or Mi Home's."""
    if getattr(conn, "account", "") == "mi":
        from .dreame_mi import MiCloud

        return MiCloud(conn, sleep=sleep)
    return Cloud(conn, sleep=sleep)


#: The apps a Dreame robot can be paired in.
ACCOUNTS = (("dreamehome", "Dreamehome"), ("mi", "Mi Home"))
ACCOUNT_NAMES = dict(ACCOUNTS)


# --- connecting -------------------------------------------------------------------------------

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _robot_name(d: dict) -> str:
    return str(d.get("customName") or (d.get("deviceInfo") or {}).get("displayName") or d.get("model") or "")


def _pick_robot(devices: list[dict], did: str = "") -> dict | None:
    vacuums = [d for d in devices if ".vacuum." in str(d.get("model") or "")]
    for d in vacuums:
        if did and str(d.get("did")) == did:
            return d
    return vacuums[0] if vacuums else None


def connect(who, *, email: str, password: str, region: str = "auto", account: str = "dreamehome",
            sleep=time.sleep):
    """Sign in to Dreamehome or Mi Home, keep what stays signed in sealed, and find the robot. The row.

    A Mi Home sign-in that Xiaomi stops for a code or a picture raises `dreame_mi.NeedsCode` or
    `NeedsCaptcha`, and waits for the person's answer (`dreame_mi.answer`)."""
    if account == "mi":
        from . import dreame_mi

        try:
            return dreame_mi.connect(who, user=email, password=password, region=region)
        finally:
            password = ""
    if account != "dreamehome":
        password = ""
        raise Refused("Choose the app the robot is in.")
    email = str(email or "").strip()
    region = str(region or "auto").strip().lower()
    if not _EMAIL.match(email):
        password = ""
        raise Refused("Type the email address of your Dreamehome account.")
    if not password:
        raise Refused("Type the password of your Dreamehome account.")
    if region != "auto" and region not in REGION_NAMES:
        password = ""
        raise Refused("Choose a region.")
    found, got = sign_in(email, password, region, sleep=sleep)
    now = time.time()
    fields = {"account": "dreamehome", "session_sealed": "",
              "email": email, "password_sealed": _box().seal(password), "region": found,
              "refresh_sealed": "", "tenant_id": "", **_token_fields(got, now),
              "lapsed_at": 0.0, "lapsed_said": "", "connected_at": now, "reached_at": now}
    password = ""
    row = connection(who.user_id, who.org_id)
    if row is None:
        row = _model().objects.create(org_id=str(who.org_id), user_id=str(who.user_id), made_at=now,
                                      updated_at=now, **fields)
    else:
        _set(row, **fields)
    cloud = Cloud(row, sleep=sleep)
    robot = _pick_robot(cloud.devices(), str(row.did or ""))
    if robot is None:
        _set(cloud.conn, did="", model="", robot_name="", bind_domain="", master_uid="", rooms_json="", rooms_at=0.0)
        log.info("dreame: user %s signed in to %s with no robot on the account", who.user_id, found)
        return cloud.conn
    _set(cloud.conn, did=str(robot.get("did") or ""), model=str(robot.get("model") or ""),
         robot_name=_robot_name(robot), bind_domain=str(robot.get("bindDomain") or ""),
         master_uid=str(robot.get("masterUid") or ""))
    log.info("dreame: user %s in org %s connected to %s (%s) in %s", who.user_id, who.org_id,
             cloud.conn.did, cloud.conn.model, found)
    try:
        read_rooms(cloud)
    except (DreameError, MapError) as exc:
        log.info("dreame: the rooms could not be read on connecting (%s)", exc)
    return cloud.conn


def check(who) -> str:
    """Reach the cloud and the robot now: what to say about it."""
    conn = connection(who.user_id, who.org_id)
    if conn is None:
        raise Refused("The Dreame robot is not connected.")
    cloud = cloud_for(conn)
    robot = _pick_robot(cloud.devices(), conn.did)
    if robot is None:
        return f"{cloud.name} answered, but there is no robot vacuum on the account."
    _set(cloud.conn, did=str(robot.get("did") or ""), model=str(robot.get("model") or ""),
         robot_name=_robot_name(robot) or cloud.conn.robot_name,
         bind_domain=str(robot.get("bindDomain") or cloud.conn.bind_domain), reached_at=time.time())
    s = read_state(cloud, fresh=True)
    battery = f", battery {s['battery']}%" if s.get("battery") is not None else ""
    return f"{cloud.conn.robot_name or 'The robot'} answered just now: {s['words'].lower()}{battery}."


def disconnect(who) -> bool:
    """Forget this person's Dreamehome or Mi Home account, its password and its tokens."""
    from . import dreame_mi

    dreame_mi.forget_waiting(who)
    gone, _ = _model().objects.filter(user_id=str(who.user_id), org_id=str(who.org_id)).delete()
    _STATE.pop((str(who.org_id), str(who.user_id)), None)
    log.info("dreame: user %s in org %s disconnected", who.user_id, who.org_id)
    return bool(gone)


def _when(ts) -> str:
    from . import clock

    return clock.moment(ts).strftime("%-d %b %Y, %H:%M") if ts else ""


def public(who) -> dict:
    """Everything the Settings card shows. Never the password or a token."""
    from . import dreame_mi

    auto = [{"id": "auto", "name": "Automatic"}]
    conn = connection(who.user_id, who.org_id)
    out = {"connected": False, "accounts": [{"id": a, "name": n} for a, n in ACCOUNTS],
           "regions": {"dreamehome": auto + [{"id": r, "name": n} for r, n in REGIONS],
                       "mi": auto + [{"id": r, "name": n} for r, n in dreame_mi.REGIONS]}}
    waiting = dreame_mi.waiting_view(who)
    if waiting:
        out["waiting"] = waiting
    if conn is not None:
        names = dreame_mi.REGION_NAMES if conn.account == "mi" else REGION_NAMES
        out.update(connected=bool(conn.access_sealed and not conn.lapsed_at), lapsed=bool(conn.lapsed_at),
                   lapsed_said=conn.lapsed_said, email=conn.email, region=conn.region,
                   account=conn.account or "dreamehome",
                   account_name=ACCOUNT_NAMES.get(conn.account or "dreamehome", "Dreamehome"),
                   region_name=names.get(conn.region, conn.region), robot=conn.robot_name,
                   model=conn.model, has_robot=bool(conn.did), since=_when(conn.connected_at),
                   reached=_when(conn.reached_at))
    return out


# --- the robot's properties ---------------------------------------------------------------------

#: MIoT (service, property) numbers, from Tasshack's DreameVacuumPropertyMapping.
P = {
    "state": (2, 1), "error": (2, 2), "battery": (3, 1), "charging": (3, 2),
    "status": (4, 1), "time": (4, 2), "area": (4, 3), "suction": (4, 4), "water": (4, 5),
    "tank": (4, 6), "task": (4, 7), "mode": (4, 23), "base": (4, 25), "customized": (4, 26),
    "main_brush": (9, 2), "side_brush": (10, 2), "filter": (11, 1), "auto_empty": (15, 5),
    "sensor": (16, 1), "mop_pad": (18, 1), "clean_tank": (27, 1), "dirty_tank": (27, 2),
    "dust_bag": (27, 3), "wetness": (28, 1),
}
#: MIoT (service, action) numbers, from Tasshack's DreameVacuumActionMapping.
A = {"start": (2, 1), "pause": (2, 2), "dock": (3, 1), "custom": (4, 1), "wash": (4, 4),
     "locate": (7, 1), "empty": (15, 1), "map": (6, 1)}

SUCTION = {0: "Quiet", 1: "Standard", 2: "Strong", 3: "Turbo"}
MODES = {"vacuum": "Vacuum only", "mop": "Mop only", "both": "Vacuum and mop", "mop_after": "Vacuum, then mop"}
WETNESS = {1: "Slightly dry", 2: "Moist", 3: "Wet"}
#: The three wetness steps as the 1 to 32 scale of robots that have one (Tasshack's _update_water_level).
WETNESS_SCALE = {1: 5, 2: 16, 3: 27}
CONSUMABLES = (("main_brush", "Main brush"), ("side_brush", "Side brush"), ("filter", "Filter"),
               ("mop_pad", "Mop pads"), ("sensor", "Sensors"))

# The robot's own states (siid 2, piid 1), as Tasshack's DreameVacuumState names them.
_STATES = {
    1: "Vacuuming", 2: "Idle", 3: "Paused", 4: "Error", 5: "Returning to the dock", 6: "Charging",
    7: "Mopping", 8: "Drying the mop pads", 9: "Washing the mop pads", 10: "Returning to wash the mop pads",
    11: "Making a map", 12: "Vacuuming and mopping", 13: "Charged", 14: "Updating", 15: "Cleaning a spot",
    16: "Resetting the base", 17: "Returning to fit the mop pads", 18: "Returning to take off the mop pads",
    19: "Checking water", 20: "Adding water", 21: "Washing paused", 22: "Emptying the dust bin",
    23: "Remote control", 24: "Smart charging", 25: "Cleaning again", 27: "Cleaning a spot",
    28: "Returning to empty", 29: "Waiting for a task", 30: "Cleaning the base", 31: "Returning to drain",
    32: "Draining", 33: "Draining water", 34: "Emptying", 35: "Drying the dust bag",
    37: "Going to clean more", 38: "Cleaning more", 101: "Deep cleaning", 103: "Sanitising",
    104: "Sanitising", 105: "Changing the mop pads", 107: "Maintaining the floor", 118: "Returning to charge",
    121: "Entering the dock", 122: "Leaving the dock",
}
_CLEANING = {1, 7, 11, 12, 15, 25, 27, 37, 38, 101, 107}
_RETURNING = {5, 10, 17, 18, 28, 31, 118, 121}
_PAUSED = {3, 21}
_BASE_WORK = {8, 9, 16, 19, 20, 22, 30, 32, 33, 34, 35, 103, 104, 105}

# The base (siid 4, piid 25), its tanks (siid 27) and its bin (siid 15, piid 5), in words.
_BASE = {1: "Washing the mop pads", 2: "Drying the mop pads", 3: "Returning to wash", 4: "Washing paused",
         5: "Adding water", 6: "Adding water", 7: "Returning to dry the mop pads"}
_CLEAN_TANK = {0: "Fine", 1: "Not in place", 2: "Low on water", 3: "Being checked"}
_DIRTY_TANK = {0: "Fine", 1: "Full or not in place"}
_DUST_BAG = {0: "Fine", 1: "Not in place", 2: "Needs checking"}

#: What each error code means, in Tasshack's English (translations/en.json), by code.
ERRORS = {
    1: "Wheels are suspended",
    2: "Cliff sensor error",
    3: "Collision sensor is stuck",
    4: "Robot is tilted",
    5: "Collision sensor is stuck",
    6: "Wheels are suspended",
    7: "Optical flow sensor error",
    8: "Dust bin not installed",
    9: "Water tank not installed",
    10: "Water tank is empty",
    11: "The filter not dry or blocked",
    12: "The main brush wrapped",
    13: "The side brush wrapped",
    14: "The filter not dry or blocked",
    15: "The robot is stuck, or its left wheel may be blocked by foreign objects",
    16: "The robot is stuck, or its right wheel may be blocked by foreign objects",
    17: "The robot is stuck, or cannot turn",
    18: "The robot is stuck, or cannot go forward",
    19: "Cannot find base",
    20: "Low battery",
    21: "Charging error",
    22: "Battery level error",
    23: "Internal error",
    24: "Visual positioning sensor error",
    25: "Move sensor error",
    26: "Optical sensor error",
    27: "Infrared shielding error",
    28: "The charging dock is not powered on",
    29: "Battery error",
    30: "Fan speed sensor error",
    31: "Left wheel may be blocked by foreign objects",
    32: "Right wheel may be blocked by foreign objects",
    33: "Accelerometer error",
    34: "Gyro error",
    35: "Gyro error",
    36: "Left magnet sensor error",
    37: "Right magnet sensor error",
    38: "Flow sensor error",
    39: "Infrared error",
    40: "Camera error",
    41: "Strong magnetic field detected",
    42: "Water pump error",
    43: "RTC error",
    44: "Internal error",
    45: "Internal error",
    46: "Internal error",
    47: "Cleanup route is blocked, returning to the dock.",
    48: "Laser distance sensor error",
    49: "Laser distance sensor bumper error",
    50: "Water pump error",
    51: "The filter not dry or blocked",
    54: "Edge sensor error",
    55: "Please start the robot in non-carpet area.",
    56: "The 3D obstacle avoidance sensor is malfunctioning.",
    57: "Edge sensor error",
    58: "The ultrasonic sensor is malfunctioning.",
    59: "No-Go zone or virtual wall detected.",
    61: "Cleanup route is blocked.",
    62: "Cleanup route is blocked.",
    63: "Cleanup route is blocked, returning to the dock.",
    64: "Cleanup route is blocked, returning to the dock.",
    65: "Detected that the vacuum-mop is in a restricted area.",
    66: "Detected that the vacuum-mop is in a restricted area.",
    67: "Detected that the vacuum-mop is in a restricted area.",
    68: "Mopping completed. Please remove and clean the mop in time.",
    69: "The mop pad came off during the cleaning task.",
    70: "The mop pad came off during the cleaning task.",
    71: "The mop pad has stopped rotating.",
    72: "The mop pad has stopped rotating.",
    74: "Mop pad installation failed.",
    75: "Low battery. Robot will shut down soon.",
    76: "The used water tank of robot is not installed.",
    78: "Hidden area. Please move the robot to the appropriate area and retry.",
    79: "Failed to lift LDS module.",
    80: "LDS cannot be raised here for positioning.",
    81: "LDS cannot be raised here for positioning.",
    82: "Slippery floor. Please try again later.",
    85: "Please check if the mop is installed properly.",
    86: "Abnormal water level in the robot's used water tank.",
    88: "Please check if the retractable legs are tangled.",
    89: "Malfunction due to an internal error. Try to restart the robot.",
    90: "LDS cannot be raised here for positioning.",
    91: "Robot stuck among the tables and chairs.",
    92: "Robot stuck in the narrow passage.",
    93: "Robot stuck at the step/threshold.",
    94: "Robot stuck in a low-clearance area.",
    95: "Robot has detected Easy-to-Fall ramps on the path.",
    96: "Robot has detected obstacles on the path.",
    97: "Robot has detected people or pets on the path.",
    98: "Robot is stuck due to slipping.",
    99: "Robot slips on the carpet",
    101: "The dust collection bag is full, or the air duct is blocked.",
    102: "The upper cover of auto-empty base is not closed, or the dust collection bag is not installed.",
    103: "The upper cover of auto-empty base is not closed, or the dust collection bag is not installed.",
    104: "The dust collection bag is full, or the air duct is blocked.",
    105: "The clean water tank is not installed.",
    106: "The dirty water tank is full or not installed.",
    107: "Low water level in the clean water tank, please fill with water timely.",
    108: "The dirty water tank is full or not installed.",
    109: "Dirty water tank blocked.",
    110: "Dirty water tank pump error.",
    111: "The washboard is not installed properly.",
    112: "The water level of the washboard is abnormal, please clean the washboard timely.",
    114: "The cleaning task is complete, please clean the mop pad washboard.",
    116: "Check and fill the clean water tank.",
    117: "Base station not powered on",
    118: "The water level in the used water tank is too high.",
    119: "Water level in the washboard is too high.",
    120: "Mop pad is not in the station.",
    121: "Dust bag is full or vents are blocked.",
    123: "Abnormal water discharge from the clean water tank of the upper and lower water modules.",
    124: "Washboard stops working.",
    125: "Abnormal water drainage from used water tank",
    126: "Mop not detected.",
    127: "Mop holder quantity/placement error in the dock.",
    128: "Dock Error.",
    129: "Failed to wash dirty mop.",
    200: "Robot slips in the curtain area",
    201: "Edge mop stopped rotating.",
    202: "Edge mop detached.",
    203: "Chassis lift malfunction.",
    207: "Malfunction due to an internal error. Try to restart the robot.",
    209: "Check for any debris near the roller mop and mop cover.",
    210: "Check for any debris near the roller mop and mop cover.",
    212: "Robotic arm stopped.",
    213: "Low water level in robot’s clean water box.",
    214: "Robot's used water box is full.",
    215: "Mop Not Installed.",
    217: "Laser distance sensor error",
    218: "Check for any debris near the roller mop and mop cover.",
    222: "Fluffing Roller Error.",
    223: "Check for any debris near the roller mop and mop cover.",
    224: "Check for any debris near the roller mop and mop cover.",
    225: "Check for any debris near the roller mop and mop cover.",
    226: "Robot blocked by obstacle.",
    227: "The wastewater outlet filter of robot is clogged.",
    228: "Main wheels error.",
    229: "Malfunction due to an internal error. Try to restart the robot.",
    230: "Malfunction due to an internal error. Try to restart the robot.",
    1000: "Failed to return to charge.",
}


def _int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def split_mode(value: int, lifting: bool = True) -> list[int]:
    """A self-washing robot's mode word (siid 4, piid 23): [mode, self-clean value, wetness].

    As Tasshack's split_group_value: the mode is the low two bits on a robot that lifts its mop
    pads and the lowest bit on one that does not."""
    return [value & (0x03 if lifting else 0x01), (value >> 8) & 0xFF, value >> 16]


def join_mode(values: list[int]) -> int:
    return ((values[2] & 0xFFFF) << 16) | ((values[1] & 0xFF) << 8) | (values[0] & 0xFF)


def _mode_of(raw, has_base: bool, lifting: bool) -> str:
    """The cleaning mode in Rouh's words: vacuum, mop, both or mop_after."""
    v = _int(raw)
    if v is None:
        return ""
    first = split_mode(v, lifting)[0] if has_base else v
    if first == 3:
        return "mop_after"
    if lifting:
        return {0: "both", 1: "mop", 2: "vacuum"}.get(first, "")
    return {0: "vacuum", 1: "mop", 2: "both"}.get(first, "")


def parse(raw: dict[tuple[int, int], object]) -> dict:
    """The properties read, as what the page and the tool show. Only what the robot gave."""
    g = lambda k: raw.get(P[k])  # noqa: E731
    state, status, charging = _int(g("state")), _int(g("status")), _int(g("charging"))
    error = _int(g("error")) or 0
    battery = _int(g("battery"))
    has_base = g("base") is not None
    lifting = has_base and (g("auto_empty") is not None or g("dust_bag") is not None)
    if state == 4 or status == 12:
        kind = "error"
    elif state in _CLEANING:
        kind = "cleaning"
    elif state in _PAUSED or status == 1:
        kind = "paused"
    elif state in _RETURNING or status == 3:
        kind = "returning"
    elif state == 6 or charging == 1:
        kind = "charging"
    elif state in (13,) or charging == 3 or state in _BASE_WORK:
        kind = "docked"
    else:
        kind = "idle"
    words = _STATES.get(state or -1) or {"cleaning": "Cleaning", "paused": "Paused", "returning": "Returning",
                                         "charging": "Charging", "docked": "Docked", "error": "Error",
                                         "idle": "Idle"}[kind]
    if kind == "docked" and state not in _BASE_WORK:
        words = "Docked" + (", charged" if (battery or 0) >= 100 or charging == 3 else "")
    out: dict = {"kind": kind, "words": words, "battery": battery, "charging": charging == 1}
    if error > 0:
        said = ERRORS.get(error) or f"Error {error}"
        if kind == "error":
            out["error"] = said
        else:
            out["notice"] = said
    started = kind in ("cleaning", "paused", "returning") or (_int(g("task")) or 0) not in (0, None)
    minutes, area = _int(g("time")), _int(g("area"))
    if started and (minutes is not None or area is not None):
        out["clean"] = {"minutes": minutes or 0, "area": area or 0}
    s = _int(g("suction"))
    if s in SUCTION:
        out["suction"] = SUCTION[s].lower()
    mode = _mode_of(g("mode"), has_base, lifting)
    if mode:
        out["mode"] = mode
    if has_base and _int(g("mode")) is not None:
        wet = split_mode(_int(g("mode")), lifting)[2]
        scale = _int(g("wetness"))
        if scale is not None and scale > 0:
            out["wetness"] = 1 if scale <= 10 else 2 if scale <= 21 else 3
        elif wet in WETNESS:
            out["wetness"] = wet
    elif _int(g("water")) in WETNESS:
        out["wetness"] = _int(g("water"))
    base = {}
    if has_base:
        b = _int(g("base"))
        base["work"] = _BASE.get(b or 0, "")
        base["washing"] = b == 1
        base["drying"] = b == 2
    for key, words_of in (("clean_tank", _CLEAN_TANK), ("dirty_tank", _DIRTY_TANK), ("dust_bag", _DUST_BAG)):
        v = _int(g(key))
        if v in words_of:
            base[key] = words_of[v]
    if g("auto_empty") is not None:
        base["emptying"] = _int(g("auto_empty")) == 1
    if base:
        out["base"] = base
    cons = []
    for key, name in CONSUMABLES:
        v = _int(g(key))
        if v is not None and 0 <= v <= 100:
            cons.append({"id": key, "name": name, "left": v})
    if cons:
        out["consumables"] = cons
    out["can"] = {"mode": bool(mode), "wetness": "wetness" in out, "suction": "suction" in out,
                  "wash": has_base, "dry": has_base, "empty": g("auto_empty") is not None}
    out["_mode_raw"] = _int(g("mode"))
    out["_scale"] = g("wetness") is not None
    out["_has_base"] = has_base
    out["_lifting"] = lifting
    out["_customized"] = g("customized") is not None
    return out


_STATE: dict[tuple[str, str], tuple[float, dict]] = {}


def read_state(cloud: Cloud, *, fresh: bool = False) -> dict:
    """The robot's state, read at most every STATE_LIFE seconds for one person however many ask."""
    key = (str(cloud.conn.org_id), str(cloud.conn.user_id))
    kept = _STATE.get(key)
    if kept and not fresh and time.time() - kept[0] < STATE_LIFE:
        return kept[1]
    got = parse(cloud.get(list(P.values())))
    _STATE[key] = (time.time(), got)
    return got


# --- the rooms, from the map -------------------------------------------------------------------

#: The key each model's map is encrypted under (its AES IV), from Tasshack's DEVICE_INFO: most
#: models share the default, these are the others.
MAP_IV_DEFAULT = "NRwnBj5FsNPgBNbT"
MAP_IV: dict[str, str] = {}
_MAP_IV_GROUPS = {
    "FmnfaI2pbem0k75t": (
        "r2251a r2251o r2257o r2317 r2345a r2345h r2363 r2363a r2363n r2364 r23646 r2364a r2382a "
        "r2382k r2382r r2383a r2383k r2386 r2471 r2563b r2563v r25642 r2564b r2564s r2564z r2565a "
        "r2565v r2566a r2566h r530jb r530ua r53148 r5314a r5314s r5314z r531ra r531rh r53456 r5345b "
        "r5345e r540ga r540jb r540tb r54125 r5412a r5412v r54136 r5413a r5413v r63013 r63014 r63015 "
        "r63017 r63018 r6301a r6301f r6301h r6301r r6301v r6301x r64015 r64016 r64017 r64018 r6401c "
        "r6401k r6401r r6401v r95265 r95266 r95267 r9526a r9526c r9526h r9526k r9527 r95275 r95276 "
        "r95277 r95278 r95279 r9527a r9527f r9527v r9537a r9537h r95425 r9542a r9542b r9542h r9542t "
    ),
    "3F0ji4ufBMaH1ThM": (
        "r2243 r2312 r2312a r2328 r2380 r2380r r2388 r2422 r2422a r2422b r2422c r2458a r2458h r2459a "
        "r2459h r2459k r2459r r2463r r2478r r2478v r2567a r2567r r2569c r2569r r2570 r95239 r9523a "
        "r9523b r9523c r9523h r9523k r9523t r9523u "
    ),
    "OFULk9To37qRdXY3": (
        "c102cn c102gl d103cn d110ch r2210 "
    ),
    "8qnS9dqgT3CppGe1": (
        "p2140 p2140a p2140o p2140p p2140q "
    ),
    "6PFiLPYMHLylp7RR": (
        "p2114a p2114o "
    ),
    "RNO4p35b2QKaovHC": (
        "p2149o "
    ),
    "qFKhvoAqRFTPfKN6": (
        "r2209 "
    ),
    "dndRQ3z8ACjDdDMo": (
        "r2211o "
    ),
    "4sCv3Q2BtbWVBIB2": (
        "r2216o "
    ),
    "ojxGnogHfVuefVfx": (
        "r2240 "
    ),
    "nf3Zi2Mq8jD5AAOm": (
        "r2250 "
    ),
    "wRy05fYLQJMRH6Mj": (
        "r2254 "
    ),
}
for _iv, _models_of in _MAP_IV_GROUPS.items():
    for _m in _models_of.split():
        MAP_IV[_m] = _iv

#: A room's type, when it has no name of its own (Tasshack's SEGMENT_TYPE_CODE_TO_NAME).
ROOM_TYPES = {1: "Living room", 2: "Primary bedroom", 3: "Study", 4: "Kitchen", 5: "Dining room",
              6: "Bathroom", 7: "Balcony", 8: "Corridor", 9: "Utility room", 10: "Closet",
              11: "Meeting room", 12: "Office", 13: "Fitness area", 14: "Recreation area",
              15: "Secondary bedroom"}
_HEADER = 27


class MapError(Exception):
    """The map could not be fetched or read."""


def decode_frame(text: str, iv: str, key: str | None = None) -> dict:
    """One map frame, as the robot uploads it: its header's size and its JSON tail.

    url-safe base64; AES-256-CBC under the frame's own key (sha256 of it, hex, first 32) and the
    model's IV when it has one; zlib; a 27-byte header, a width x height grid, then JSON."""
    raw = (text or "").strip().replace("_", "/").replace("-", "+")
    if "," in raw and key is None:
        raw, key = raw.split(",", 1)
    try:
        data = base64.b64decode(raw + "=" * (-len(raw) % 4))
    except (ValueError, TypeError) as exc:
        raise MapError(f"the map is not base64 ({exc})") from None
    if key:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

        try:
            cipher = Cipher(algorithms.AES(hashlib.sha256(key.encode()).hexdigest()[:32].encode()),
                            modes.CBC(iv.encode()))
            d = cipher.decryptor()
            data = d.update(data) + d.finalize()
        except ValueError as exc:
            raise MapError(f"the map would not decrypt ({exc})") from None
    try:
        data = zlib.decompress(data)
    except zlib.error as exc:
        raise MapError(f"the map would not unpack ({exc})") from None
    if len(data) < _HEADER:
        raise MapError("the map is too short")
    width = int.from_bytes(data[19:21], "little")
    height = int.from_bytes(data[21:23], "little")
    tail = data[_HEADER + width * height:]
    try:
        info = json.loads(tail.decode("utf-8")) if tail else {}
    except (UnicodeDecodeError, ValueError):
        raise MapError("the map's room list is not JSON") from None
    return {"map_id": int.from_bytes(data[0:2], "little"), "width": width, "height": height,
            "json": info if isinstance(info, dict) else {}}


def rooms_of(frame_json: dict, iv: str) -> list[dict]:
    """The rooms a map frame names: [{id, name}], by id. A saved map inside it when it has none."""
    seg = frame_json.get("seg_inf")
    if not isinstance(seg, dict) or not seg:
        saved = frame_json.get("rism")
        if isinstance(saved, str) and saved:
            return rooms_of(decode_frame(saved, iv)["json"], iv)
        return []
    out = []
    for k in sorted(seg, key=lambda x: int(x) if str(x).isdigit() else 0):
        if not str(k).isdigit():
            continue
        v = seg[k] if isinstance(seg[k], dict) else {}
        name = ""
        if v.get("name"):
            try:
                name = base64.b64decode(str(v["name"])).decode("utf-8").strip()
            except (ValueError, UnicodeDecodeError):
                name = ""
        if not name:
            t = _int(v.get("type")) or 0
            index = _int(v.get("index")) or 0
            name = ROOM_TYPES.get(t, "")
            name = f"{name} {index + 1}" if name and index > 0 else name or f"Room {k}"
        out.append({"id": int(k), "name": name})
    return out


def _object_name(out: list) -> str:
    """The map file's name from what the map request answered (siid 6, piid 3)."""
    for prop in out or []:
        if isinstance(prop, dict) and _int(prop.get("piid")) == 3 and prop.get("value"):
            v = prop["value"]
            if isinstance(v, list) and v:
                v = v[0]
            if isinstance(v, str) and v.startswith("["):
                try:
                    v = json.loads(v)[0]
                except (ValueError, IndexError, KeyError):
                    pass
            return str(v)
    return ""


def _map_data(out: list) -> str:
    for prop in out or []:
        if isinstance(prop, dict) and _int(prop.get("piid")) == 1 and prop.get("value"):
            return str(prop["value"])
    return ""


def read_rooms(cloud: Cloud) -> list[dict]:
    """Ask the robot for its map, read the rooms out of it, and keep them on the row."""
    import httpx

    got = cloud.action(*A["map"], [{"piid": 2, "value": json.dumps(
        {"req_type": 1, "frame_type": "I", "force_type": 1}, separators=(",", ":"))}])
    out = got.get("out") or []
    iv = MAP_IV.get(str(cloud.conn.model).rsplit(".", 1)[-1], MAP_IV_DEFAULT)
    text, key = _map_data(out), None
    if not text:
        name = _object_name(out)
        if not name:
            raise MapError("the robot sent no map")
        if "," in name:
            name, key = name.split(",", 1)
        url = cloud.file_url(name)
        if not url:
            raise MapError("the cloud gave no address for the map")
        try:
            r = httpx.get(url, timeout=TIMEOUT)
        except httpx.HTTPError as exc:
            raise MapError(f"the map could not be fetched ({type(exc).__name__})") from None
        if r.status_code != 200:
            raise MapError(f"the map could not be fetched (HTTP {r.status_code})")
        text = r.text
    rooms = rooms_of(decode_frame(text, iv, key)["json"], iv)
    _set(cloud.conn, rooms_json=json.dumps(rooms), rooms_at=time.time())
    log.info("dreame: %d rooms read from the map for user %s", len(rooms), cloud.conn.user_id)
    return rooms


def rooms(cloud: Cloud, *, again: bool = False) -> list[dict]:
    """The rooms kept on the row, read from the map again when they are old or asked for."""
    kept = []
    if cloud.conn.rooms_json:
        try:
            kept = json.loads(cloud.conn.rooms_json) or []
        except ValueError:
            kept = []
    if again or not cloud.conn.rooms_at or time.time() - cloud.conn.rooms_at > ROOMS_LIFE:
        try:
            return read_rooms(cloud)
        except (DreameError, MapError) as exc:
            log.info("dreame: the rooms could not be read again (%s); keeping %d", exc, len(kept))
    return kept


# --- commands ----------------------------------------------------------------------------------

def _rooms_meant(said: list[str] | str, known: list[dict]) -> tuple[list[dict], str]:
    """(the rooms meant, "") or ([], what to say): names matched loosely, never guessed between."""
    from .hue import Thing, match

    things = [Thing("room", str(r["id"]), r["name"]) for r in known]
    if isinstance(said, str):
        said = [s for s in re.split(r",|\band\b|&", said) if s.strip()]
    picked: list[dict] = []
    for one in said:
        one = str(one).strip()
        if not one:
            continue
        by_id = [r for r in known if str(r["id"]) == one]
        if by_id:
            picked += by_id
            continue
        thing, candidates = match(one, things)
        if thing is None:
            names = ", ".join(r["name"] for r in known)
            if candidates:
                return [], f"More than one room fits {one!r}: " + ", ".join(c.name for c in candidates) + ". Say which."
            return [], f"No room is called anything like {one!r}." + (f" The rooms are: {names}." if names else "")
        picked += [r for r in known if str(r["id"]) == thing.id]
    seen, out = set(), []
    for r in picked:
        if r["id"] not in seen:
            seen.add(r["id"])
            out.append(r)
    return out, ""


def _names(rs: list[dict]) -> str:
    n = [r["name"] for r in rs]
    return n[0] if len(n) == 1 else ", ".join(n[:-1]) + " and " + n[-1]


def start(cloud: Cloud, state: dict, room_ids: list[int] | None = None) -> str:
    name = cloud.conn.robot_name or "The robot"
    if room_ids:
        known = {r["id"]: r for r in rooms(cloud)}
        picked = [known[i] for i in room_ids if i in known] or [{"id": i, "name": f"Room {i}"} for i in room_ids]
        suction = {v.lower(): k for k, v in SUCTION.items()}.get(state.get("suction") or "", 1)
        water = state.get("wetness") or 2
        selects = [[r["id"], 1, suction, water, 1 if state.get("_customized") else i + 1]
                   for i, r in enumerate(picked)]
        cloud.action(*A["custom"], [{"piid": 1, "value": 18},
                                    {"piid": 10, "value": json.dumps({"selects": selects}, separators=(",", ":"))}])
        return f"{name} is cleaning {_names(picked)}."
    cloud.action(*A["start"])
    return f"{name} is {'carrying on' if state.get('kind') == 'paused' else 'cleaning'}."


def set_suction(cloud: Cloud, level: str) -> str:
    want = {v.lower(): k for k, v in SUCTION.items()}.get(str(level or "").strip().lower())
    if want is None:
        return "Suction is quiet, standard, strong or turbo."
    cloud.put(*P["suction"], want)
    return f"Suction: {SUCTION[want].lower()}."


def set_mode(cloud: Cloud, state: dict, mode: str) -> str:
    m = str(mode or "").strip().lower().replace(" ", "_").replace("-", "_")
    m = {"vacuum_only": "vacuum", "sweep": "vacuum", "sweeping": "vacuum", "vacuuming": "vacuum",
         "mop_only": "mop", "mopping": "mop", "vacuum_and_mop": "both", "sweep_and_mop": "both"}.get(m, m)
    if m not in ("vacuum", "mop", "both"):
        return "The mode is vacuum, mop or both."
    if not state["can"]["mode"]:
        return "This robot does not say its cleaning mode, so Rouh cannot change it."
    lifting, has_base = state["_lifting"], state["_has_base"]
    first = ({"both": 0, "mop": 1, "vacuum": 2} if lifting else {"vacuum": 0, "mop": 1, "both": 2})[m]
    if has_base and state["_mode_raw"] is not None:
        values = split_mode(state["_mode_raw"], lifting)
        values[0] = first
        cloud.put(*P["mode"], join_mode(values))
    else:
        cloud.put(*P["mode"], first)
    return f"Mode: {MODES[m].lower()}."


def set_wetness(cloud: Cloud, state: dict, level) -> str:
    t = str(level or "").strip().lower()
    want = {"slightly dry": 1, "dry": 1, "low": 1, "1": 1, "moist": 2, "medium": 2, "2": 2,
            "wet": 3, "high": 3, "3": 3}.get(t)
    if want is None:
        return "Mop wetness is slightly dry, moist or wet."
    if state.get("_scale"):
        cloud.put(*P["wetness"], WETNESS_SCALE[want])
    elif state["_has_base"] and state["_mode_raw"] is not None:
        values = split_mode(state["_mode_raw"], state["_lifting"])
        values[2] = want
        cloud.put(*P["mode"], join_mode(values))
    elif state.get("wetness"):
        cloud.put(*P["water"], want)
    else:
        return "This robot does not say how wet its mop is, so Rouh cannot change it."
    return f"Mop wetness: {WETNESS[want].lower()}."


def do(cloud: Cloud, action: str, *, rooms_said=None, level=None) -> str:
    """One thing the robot is asked to do; what changed, in a line."""
    name = cloud.conn.robot_name or "The robot"
    a = str(action or "").strip().lower().replace(" ", "_")
    state = read_state(cloud, fresh=True)
    if a in ("start", "clean", "resume"):
        ids: list[int] = []
        if rooms_said:
            if isinstance(rooms_said, list) and all(isinstance(x, int) for x in rooms_said):
                ids = list(rooms_said)
            else:
                known = rooms(cloud)
                if not known:
                    return ("Rouh could not read the rooms from the robot's map, so it cannot clean single "
                            "rooms. It can clean everywhere.")
                picked, said = _rooms_meant(rooms_said, known)
                if said:
                    return said
                ids = [r["id"] for r in picked]
        out = start(cloud, state, ids)
    elif a == "pause":
        cloud.action(*A["pause"])
        out = f"{name} is paused."
    elif a in ("dock", "return", "return_to_dock", "home"):
        cloud.action(*A["dock"])
        out = f"{name} is going back to the dock."
    elif a == "locate":
        cloud.action(*A["locate"])
        out = f"{name} is saying where it is."
    elif a == "suction":
        out = set_suction(cloud, level)
    elif a == "mode":
        out = set_mode(cloud, state, level)
    elif a in ("wetness", "water", "mop"):
        out = set_wetness(cloud, state, level)
    elif a == "wash":
        if not state["can"]["wash"]:
            return "This robot has no base that washes the mop pads."
        cloud.action(*A["wash"], [{"piid": 10, "value": "2,1"}])
        out = f"{name} is washing its mop pads."
    elif a == "dry":
        if not state["can"]["dry"]:
            return "This robot has no base that dries the mop pads."
        stop = (state.get("base") or {}).get("drying")
        cloud.action(*A["wash"], [{"piid": 10, "value": "3,0" if stop else "3,1"}])
        out = "Drying stopped." if stop else f"{name}'s base is drying the mop pads."
    elif a == "empty":
        if not state["can"]["empty"]:
            return "This robot has no base that empties the dust bin."
        cloud.action(*A["empty"])
        out = f"{name}'s base is emptying the dust bin."
    else:
        return "The actions are status, start, pause, dock, locate, suction, mode, wetness, wash, dry and empty."
    _STATE.pop((str(cloud.conn.org_id), str(cloud.conn.user_id)), None)
    return out


# --- what the Home page and the tool show ------------------------------------------------------

def view(who) -> dict:
    """The robot for the Home page: connected or why not, its state, and its rooms."""
    conn = connection(who.user_id, who.org_id)
    if conn is None or not conn.access_sealed:
        return {"connected": False, "page": PAGE}
    if conn.lapsed_at:
        return {"connected": False, "lapsed": True, "said": conn.lapsed_said, "page": PAGE}
    cloud = cloud_for(conn)
    if not conn.did:
        return {"connected": True, "robot": None, "page": PAGE,
                "said": f"There is no robot vacuum on this {cloud.name} account."}
    try:
        state = read_state(cloud)
    except Lapsed:
        # The row that was marked lapsed is the one `refresh` read again, not this one.
        now = connection(who.user_id, who.org_id)
        return {"connected": False, "lapsed": True, "said": (now.lapsed_said if now else "") or LAPSED,
                "page": PAGE}
    except (DreameError, NotSetUp) as exc:
        return {"connected": True, "page": PAGE, "robot": {"name": conn.robot_name, "model": conn.model},
                "unreachable": str(exc)}
    shown = {k: v for k, v in state.items() if not k.startswith("_")}
    return {"connected": True, "page": PAGE,
            "robot": {"name": cloud.conn.robot_name, "model": cloud.conn.model, **shown},
            "rooms": rooms(cloud)}


def describe(name: str, s: dict, known: list[dict]) -> str:
    """The robot's state as a few lines for a turn."""
    lines = [f"{name}: {s['words'].lower()}" + (f", battery {s['battery']}%" if s.get("battery") is not None else "")
             + "."]
    if s.get("error"):
        lines.append(f"Error: {s['error']}.")
    if s.get("notice"):
        lines.append(f"It says: {s['notice']}.")
    if s.get("clean"):
        lines.append(f"This clean: {s['clean']['minutes']} min, {s['clean']['area']} m².")
    settings = []
    if s.get("mode"):
        settings.append("mode " + MODES[s["mode"]].lower())
    if s.get("suction"):
        settings.append("suction " + s["suction"])
    if s.get("wetness"):
        settings.append("mop " + WETNESS[s["wetness"]].lower())
    if settings:
        lines.append("Settings: " + ", ".join(settings) + ".")
    base = s.get("base") or {}
    b = [base["work"]] if base.get("work") else []
    b += [f"{label} {base[k].lower()}" for k, label in (("clean_tank", "clean water"), ("dirty_tank", "used water"),
                                                         ("dust_bag", "dust bag")) if base.get(k)]
    if b:
        lines.append("Base: " + ", ".join(b) + ".")
    if known:
        lines.append("Rooms: " + ", ".join(r["name"] for r in known) + ".")
    return "\n".join(lines)


def run(who, args: dict) -> str:
    """The `vacuum` tool for a turn. A sentence, or a few lines for status."""
    conn = connection(who.user_id, who.org_id)
    if conn is None or not conn.access_sealed:
        return f"The Dreame robot is not connected. ‹Owner› connects it in Settings, Connections, Dreame ({PAGE})."
    if conn.lapsed_at:
        return lapsed_line(conn.lapsed_said)
    robot = str(args.get("robot") or "").strip()
    if robot and conn.robot_name:
        from .hue import Thing, match

        if match(robot, [Thing("robot", conn.did, conn.robot_name, more=["robot", "vacuum", "hoover"])])[0] is None:
            return f"The only robot connected is {conn.robot_name}."
    cloud = cloud_for(conn)
    if not conn.did:
        return f"{cloud.name} is connected, but there is no robot vacuum on the account."
    action = str(args.get("action") or "status").strip().lower()
    try:
        if action == "status":
            return describe(cloud.conn.robot_name or "The robot", read_state(cloud, fresh=True), rooms(cloud))
        return do(cloud, action, rooms_said=args.get("rooms"),
                  level=args.get("level") or args.get("suction") or args.get("mode") or args.get("wetness"))
    except Lapsed as exc:
        return str(exc) or lapsed_line()
    except NotSetUp as exc:
        return str(exc)
    except DreameError as exc:
        return str(exc)
