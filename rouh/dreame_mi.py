"""A Dreame robot paired in Mi Home: the Xiaomi account's sign-in, its two-step code, and the signed calls.

Petar, 17 October 2026: a Dreame robot is paired either in the Dreamehome app or in Xiaomi's Mi
Home, and which one decides which cloud it answers through. `rouh/dreame.py` is the robot and the
Dreamehome account; this is the Xiaomi account, written from Tasshack/dreame-vacuum's
`DreameVacuumMiHomeCloudProtocol` (MIT), which is how the community reaches a Mi Home robot.

**The sign-in** is Xiaomi's own, in three steps (`SignIn`): ``serviceLogin`` for a sign of the
attempt, ``serviceLoginAuth2`` with the account and the MD5 of its password, and the address that
answers with the session's ``serviceToken``. Xiaomi may stop the second step to ask for:

- a two-step code (``notificationUrl``): Rouh asks Xiaomi to send it by text or email at once,
  and the half-finished sign-in waits in this process (`_PENDING`, ten minutes) until the person
  types the code into Settings themselves (`verify`);
- the letters in a picture (``captchaUrl``): the picture is shown in Settings and the person
  types them; the password waits sealed in memory for that one retry, and nowhere else.

Rouh never types a code, a password or a picture's letters itself.

**What is kept** is only what stays signed in: the ``serviceToken`` (sealed, as the access token),
the ``passToken`` (sealed, as the refresh token: it signs in again with no password and no code),
and, sealed together, the ``ssecurity`` every call is signed with, the Xiaomi user id and the
device id Rouh signs in as. The password is not kept. When the passToken stops working the
connection lapses with the reason, and the owner connects again.

**The calls** go to ``https://<country>.api.io.mi.com/app/...`` (no prefix for mainland China),
each one's fields RC4-encrypted and signed under a nonce made with the ``ssecurity``
(`fields`), the answer RC4-encrypted the same way. The robot is reached through
``v2/home/rpc/<did>`` with the same MIoT methods as Dreamehome, the property's own ``siid.piid``
standing where Dreamehome puts the robot's id. The map's file comes from
``v2/home/get_interim_file_url``.

`ROUH_DREAME_API` points this at the same stand-in as Dreamehome (`rouh/testing/fake_dreame.py`),
``/mi/account`` for account.xiaomi.com and ``/mi/<country>/app`` for each country's API.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import random
import re
import threading
import time
import urllib.parse

from . import dreame
from .dreame import Cloud, DreameError, Lapsed, NotSetUp, Refused

log = logging.getLogger("rouh.dreame.mi")

#: The Xiaomi clouds a Mi Home account's devices can live in, in the order Automatic looks.
REGIONS = (("de", "Europe"), ("us", "United States"), ("ru", "Russia"), ("sg", "Singapore"),
           ("in", "India"), ("tw", "Taiwan"), ("cn", "Mainland China"))
REGION_NAMES = dict(REGIONS)
#: How long a sign-in waiting for a code or a picture's letters is kept.
PENDING_LIFE = 600.0

NOT_ACCEPTED = "Xiaomi did not accept that account and password."
LAPSED = "Xiaomi signed Rouh out of the Mi Home account."
CODE_WRONG = "Xiaomi did not accept that code. Check it and type it again, or press Start again for a new one."
PENDING_GONE = "That sign-in waited too long and was forgotten. Type the password again."

_AUTH_WORDS = re.compile(r"auth err|invalid signature|SERVICETOKEN_EXPIRED", re.I)


class _QuietSignIn(logging.Filter):
    """Keeps Xiaomi's sign-in addresses out of the log: they carry one-time signatures, a nonce,
    and on the way back from a code, what redeems the session. httpx logs every address it asks."""

    _SECRET = re.compile(r"account\.xiaomi\.com|sts\.api\.io\.mi\.com|/mi/account/|/mi/sts")

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            return not self._SECRET.search(record.getMessage())
        except Exception:  # noqa: BLE001 - a record that cannot be read is kept
            return True


logging.getLogger("httpx").addFilter(_QuietSignIn())


def _api_base() -> str:
    return dreame.API


def account_url(path: str) -> str:
    base = _api_base()
    return f"{base}/mi/account{path}" if base else f"https://account.xiaomi.com{path}"


def api_url(country: str) -> str:
    base = _api_base()
    if base:
        return f"{base}/mi/{country}/app"
    return f"https://{'' if country == 'cn' else country + '.'}api.io.mi.com/app"


def _ua(client_id: str) -> str:
    return f"Android-7.1.1-1.0.0-ONEPLUS A3010-136-{client_id} APP/xiaomi.smarthome APPV/62830"


def _json(text: str) -> dict:
    try:
        got = json.loads((text or "").replace("&&&START&&&", ""))
    except ValueError:
        return {}
    return got if isinstance(got, dict) else {}


# --- the signing --------------------------------------------------------------------------------

def rc4(key: bytes, data: bytes) -> bytes:
    """RC4 with the first 1024 bytes of the stream dropped, as Mi Home's calls use it."""
    s = list(range(256))
    j = 0
    for i in range(256):
        j = (j + s[i] + key[i % len(key)]) & 0xFF
        s[i], s[j] = s[j], s[i]
    i = j = 0
    out = bytearray(len(data))
    for n in range(1024 + len(data)):
        i = (i + 1) & 0xFF
        j = (j + s[i]) & 0xFF
        s[i], s[j] = s[j], s[i]
        if n >= 1024:
            out[n - 1024] = data[n - 1024] ^ s[(s[i] + s[j]) & 0xFF]
    return bytes(out)


def nonce() -> str:
    b = random.getrandbits(64).to_bytes(8, "big") + (int(time.time() * 1000) // 60000).to_bytes(4, "big")
    return base64.b64encode(b).decode()


def signed_nonce(ssecurity: str, n: str) -> str:
    return base64.b64encode(hashlib.sha256(base64.b64decode(ssecurity) + base64.b64decode(n)).digest()).decode()


def _signature(path: str, params: dict, sn: str) -> str:
    text = "&".join(["POST", path] + [f"{k}={v}" for k, v in params.items()] + [sn])
    return base64.b64encode(hashlib.sha1(text.encode("utf-8")).digest()).decode()


def fields(path: str, params: dict, ssecurity: str) -> tuple[dict, str]:
    """The encrypted, signed form for one call to `path` (after ``/app``), and its signed nonce."""
    n = nonce()
    sn = signed_nonce(ssecurity, n)
    out = dict(params)
    out["rc4_hash__"] = _signature(path, out, sn)
    key = base64.b64decode(sn)
    for k, v in list(out.items()):
        out[k] = base64.b64encode(rc4(key, str(v).encode("utf-8"))).decode()
    out["signature"] = _signature(path, out, sn)
    out["ssecurity"] = ssecurity
    out["_nonce"] = n
    return out, sn


class _AuthFailed(Exception):
    """The serviceToken or the ssecurity is no longer accepted."""


def call(session: dict, service_token: str, country: str, path: str, params) -> dict:
    """One signed call to Mi Home's API: its answer, or _AuthFailed, or DreameError."""
    form, sn = fields("/" + path, {"data": json.dumps(params, separators=(",", ":"))}, session["ssecurity"])
    cookies = {"userId": str(session["user_id"]), "yetAnotherServiceToken": service_token,
               "serviceToken": service_token, "locale": "en_US", "timezone": "GMT+00:00", "is_daylight": "0",
               "dst_offset": "0", "channel": "MI_APP_STORE"}
    headers = {"User-Agent": _ua(session["client_id"]), "Accept-Encoding": "identity",
               "x-xiaomi-protocal-flag-cli": "PROTOCAL-HTTP2", "MIOT-ENCRYPT-ALGORITHM": "ENCRYPT-RC4",
               "Content-Type": "application/x-www-form-urlencoded",
               "Cookie": "; ".join(f"{k}={v}" for k, v in cookies.items())}
    r = dreame._post(f"{api_url(country)}/{path}", headers, urllib.parse.urlencode(form))
    if r.status_code in (401, 403):
        raise _AuthFailed()
    if r.status_code != 200:
        raise DreameError(f"The Xiaomi cloud answered HTTP {r.status_code}.")
    text = r.text.strip()
    try:
        # An answer it would not sign is plain JSON; every other is encrypted under the same nonce.
        got = _json(text) if text.startswith("{") else json.loads(
            rc4(base64.b64decode(sn), base64.b64decode(text)).decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise DreameError("The Xiaomi cloud answered with something Rouh could not read.") from None
    if not isinstance(got, dict):
        return {}
    if got.get("code") in (2, 3) or _AUTH_WORDS.search(str(got.get("message") or "")):
        raise _AuthFailed()
    return got


# --- the sign-in ------------------------------------------------------------------------------

class _Web:
    """An HTTP session that keeps each cookie by name across Xiaomi's hosts and redirects."""

    def __init__(self, client_id: str, cookies: dict | None = None) -> None:
        self.ua = _ua(client_id)
        self.cookies = {"sdkVersion": "3.8.6", "deviceId": client_id, **(cookies or {})}

    def go(self, method: str, url: str, *, params=None, data=None, extra: dict | None = None,
           follow: bool = True):
        import httpx

        for _hop in range(10):
            jar = {**self.cookies, **(extra or {})}
            headers = {"User-Agent": self.ua, "Cookie": "; ".join(f"{k}={v}" for k, v in jar.items() if v)}
            if data is not None:
                headers["Content-Type"] = "application/x-www-form-urlencoded"
            try:
                r = httpx.request(method, url, params=params, headers=headers, timeout=dreame.TIMEOUT,
                                  content=urllib.parse.urlencode(data).encode() if data is not None else None,
                                  follow_redirects=False)
            except httpx.HTTPError as exc:
                raise DreameError(f"Xiaomi's sign-in could not be reached ({type(exc).__name__}).") from None
            for k, v in r.cookies.items():
                if v and v != "EXPIRED":
                    self.cookies[k] = v
            where = r.headers.get("location")
            if not (follow and r.status_code in (301, 302, 303, 307, 308) and where):
                return r
            url, method, params, data = urllib.parse.urljoin(str(r.url), where), "GET", None, None
        raise DreameError("Xiaomi's sign-in sent Rouh round in circles.")


class NeedsCode(Exception):
    """Xiaomi sent a two-step code, which only the person can type."""


class NeedsCaptcha(Exception):
    """Xiaomi wants the letters in a picture, which only the person can read."""


def picture(data: bytes) -> str:
    """The captcha's picture as an address the page can show without fetching anything."""
    head = data[:64].lstrip()
    mime = ("image/png" if head.startswith(b"\x89PNG") else "image/jpeg" if head.startswith(b"\xff\xd8")
            else "image/gif" if head.startswith(b"GIF8") else "image/svg+xml" if head[:5] in (b"<svg ", b"<?xml")
            else "image/png")
    return f"data:{mime};base64," + base64.b64encode(data).decode()


def _client_id() -> str:
    return "".join(chr(random.randint(97, 122)) for _ in range(16))


class SignIn:
    """One sign-in to a Xiaomi account, kept whole while it waits for a code or a picture."""

    def __init__(self, client_id: str = "", pass_token: str = "", user_id: str = "") -> None:
        self.client_id = client_id or _client_id()
        jar = {}
        if pass_token:
            jar["passToken"] = pass_token
        if user_id:
            jar["userId"] = str(user_id)
        self.web = _Web(self.client_id, jar)
        self.user_id = str(user_id or "")
        self.ssecurity = ""
        self.location = ""
        self.sign = ""
        self.service_token = ""
        self.notification = ""
        self.flag = 4
        self.sent_to = ""
        self.ick = ""

    def _take(self, got: dict) -> None:
        self.user_id = str(got.get("userId") or self.user_id or "")
        self.ssecurity = str(got.get("ssecurity") or self.ssecurity or "")
        self.location = str(got.get("location") or "")

    def step1(self) -> bool:
        """True when the kept passToken already signs in (with the address for step 3)."""
        r = self.web.go("GET", account_url("/pass/serviceLogin"), params={"sid": "xiaomiio", "_json": "true"})
        got = _json(r.text)
        self.sign = str(got.get("_sign") or "")
        if r.status_code == 200 and got.get("code") == 0 and got.get("ssecurity") and got.get("location"):
            self._take(got)
            return True
        return False

    def step2(self, user: str, password: str, captcha: str = "") -> None:
        """The account and its password. Raises Refused, NeedsCode or NeedsCaptcha when it does not end."""
        data = {"user": user, "hash": hashlib.md5(password.encode("utf-8")).hexdigest().upper(),
                "callback": "https://sts.api.io.mi.com/sts", "sid": "xiaomiio",
                "qs": "%3Fsid%3Dxiaomiio%26_json%3Dtrue"}
        password = ""
        if self.sign:
            data["_sign"] = self.sign
        params: dict = {"_json": "true"}
        extra = {}
        if captcha and self.ick:
            data["captCode"] = captcha
            params["_dc"] = int(time.time() * 1000)
            extra["ick"] = self.ick
        r = self.web.go("POST", account_url("/pass/serviceLoginAuth2"), params=params, data=data, extra=extra)
        data = {}
        got = _json(r.text)
        if r.status_code == 200 and got.get("ssecurity") and got.get("location"):
            self._take(got)
            return
        if got.get("notificationUrl"):
            url = str(got["notificationUrl"])
            self.notification = url if url.startswith("http") else account_url(url)
            raise NeedsCode()
        if got.get("captchaUrl"):
            url = str(got["captchaUrl"])
            img = self.web.go("GET", url if url.startswith("http") else account_url(url))
            self.ick = self.web.cookies.get("ick", "")
            raise NeedsCaptcha(picture(img.content) if img.status_code == 200 else "")
        if r.status_code != 200 or not got:
            raise DreameError(f"Xiaomi's sign-in answered HTTP {r.status_code}.")
        log.info("dreame: Xiaomi refused the sign-in (code %s)", got.get("code"))
        raise Refused(NOT_ACCEPTED)

    def step3(self) -> None:
        """Follow the address Xiaomi gave to the session's serviceToken."""
        if not self.location:
            raise DreameError("Xiaomi's sign-in gave no address to finish at.")
        self.web.go("GET", self.location)
        token = self.web.cookies.get("serviceToken", "")
        if not token:
            raise DreameError("Xiaomi's sign-in finished without a session.")
        self.service_token = token
        self.user_id = self.user_id or self.web.cookies.get("userId", "")

    # The two-step code, as Tasshack's send_2fa_code and verify_code.

    def _context(self) -> str:
        return urllib.parse.parse_qs(urllib.parse.urlparse(self.notification).query).get("context", [""])[0]

    def _identity(self) -> str:
        context = self._context()
        self.web.go("GET", self.notification)
        r = self.web.go("GET", account_url("/identity/list"),
                        params={"sid": "xiaomiio", "context": context, "_locale": "en_US"})
        got = _json(r.text)
        options = got.get("options") or []
        self.flag = 4 if 4 in options else 8 if 8 in options else int(got.get("flag") or 4)
        if not self.web.cookies.get("identity_session"):
            raise DreameError("Xiaomi did not start the two-step check.")
        return context

    def send_code(self) -> str:
        """Ask Xiaomi to send the code by text or email. Where it went, masked, as Xiaomi says it."""
        context = self._identity()
        key = "Phone" if self.flag == 4 else "Email"
        params = {"_flag": self.flag, "_json": "true", "sid": "xiaomiio", "context": context, "mask": "0",
                  "_locale": "en_US"}
        got = _json(self.web.go("GET", account_url(f"/identity/auth/verify{key}"), params=params).text)
        if got.get("code") not in (0, None):
            raise Refused(_code_said(got))
        self.sent_to = str(got.get("maskedPhone") or got.get("maskedEmail") or "")
        sent = _json(self.web.go("POST", account_url(f"/identity/auth/send{key}Ticket"),
                                 params={"_dc": str(int(time.time() * 1000)), "sid": "xiaomiio",
                                         "context": context, "mask": "0", "_locale": "en_US"},
                                 data={"retry": 0, "icode": "", "_json": "true",
                                       "ick": self.web.cookies.get("ick", "")}).text)
        if sent.get("code") != 0:
            raise Refused(_code_said(sent))
        return self.sent_to

    def verify(self, code: str) -> None:
        """The code the person typed. Signs in to the end, or raises Refused."""
        context = self._context()
        key = "Phone" if self.flag == 4 else "Email"
        r = self.web.go("POST", account_url(f"/identity/auth/verify{key}"),
                        params={"_flag": self.flag, "_json": "true", "sid": "xiaomiio", "context": context,
                                "mask": "0", "_locale": "en_US"},
                        data={"_flag": self.flag, "ticket": code, "trust": "true", "_json": "true",
                              "ick": self.web.cookies.get("ick", "")}, follow=False)
        got = _json(r.text)
        where = got.get("location") or r.headers.get("location") or ""
        if got.get("code") not in (0, None) or not where:
            raise Refused(CODE_WRONG)
        self.web.go("GET", urllib.parse.urljoin(account_url("/"), where))
        self.user_id = self.web.cookies.get("userId") or self.web.cookies.get("cUserId") or self.user_id
        if not self.step1():
            raise DreameError("Xiaomi took the code but did not finish the sign-in. Press Start again.")
        self.step3()

    def session(self) -> dict:
        return {"ssecurity": self.ssecurity, "user_id": self.user_id, "client_id": self.client_id}


def _code_said(got: dict) -> str:
    said = f"{got.get('description') or ''} {got.get('message') or got.get('desc') or ''}".lower()
    if "frequent" in said or "second" in said:
        return "Xiaomi sent a code a moment ago. Wait a minute, then ask for a new one."
    if got.get("code") == 70022 or "limit" in said:
        return "Xiaomi will not send more codes today. Try again tomorrow."
    return "Xiaomi would not send a code just now. Press Start again."


# --- the waiting sign-ins -------------------------------------------------------------------------

_PENDING: dict[tuple[str, str], dict] = {}
_PENDING_LOCK = threading.Lock()


def _key(who) -> tuple[str, str]:
    return (str(who.org_id), str(who.user_id))


def _waiting(who) -> dict | None:
    with _PENDING_LOCK:
        p = _PENDING.get(_key(who))
        if p and time.time() - p["at"] > PENDING_LIFE:
            _PENDING.pop(_key(who), None)
            p = None
        return p


def forget_waiting(who) -> None:
    with _PENDING_LOCK:
        _PENDING.pop(_key(who), None)


def waiting_view(who) -> dict | None:
    """What Settings shows of a sign-in waiting for the person: the code's field, or the picture."""
    p = _waiting(who)
    if not p:
        return None
    out = {"step": p["step"], "user": p["user"], "region": p["region"]}
    if p["step"] == "code":
        out["sent_to"] = p["signin"].sent_to
    else:
        out["image"] = p.get("image", "")
    return out


# --- connecting, renewing ---------------------------------------------------------------------

def _finish(who, signin: SignIn, user: str, region: str):
    """Keep the session sealed, find the robot, and read its rooms. The row."""
    box = dreame._box()
    session = signin.session()
    found = region if region in REGION_NAMES else ""
    robot = None
    for country in ([found] if found else [r for r, _ in REGIONS]):
        try:
            devices = list_devices(session, signin.service_token, country)
        except (DreameError, _AuthFailed) as exc:
            log.info("dreame: Mi Home devices in %s could not be listed (%s)", country, type(exc).__name__)
            continue
        robot = dreame._pick_robot(devices)
        if robot is not None or found:
            found = country
            break
    found = found or REGIONS[0][0]
    now = time.time()
    fields_ = {"account": "mi", "email": user, "password_sealed": "", "region": found, "tenant_id": "",
               "access_sealed": box.seal(signin.service_token), "access_expires_at": 0.0,
               "refresh_sealed": box.seal(signin.web.cookies.get("passToken", "")) if signin.web.cookies.get(
                   "passToken") else "",
               "session_sealed": box.seal(json.dumps(session)),
               "lapsed_at": 0.0, "lapsed_said": "", "connected_at": now, "reached_at": now,
               "did": "", "model": "", "robot_name": "", "bind_domain": "", "master_uid": "",
               "rooms_json": "", "rooms_at": 0.0}
    if robot is not None:
        fields_.update(did=str(robot.get("did") or ""), model=str(robot.get("model") or ""),
                       robot_name=dreame._robot_name(robot))
    row = dreame.connection(who.user_id, who.org_id)
    if row is None:
        row = dreame._model().objects.create(org_id=str(who.org_id), user_id=str(who.user_id), made_at=now,
                                             updated_at=now, **fields_)
    else:
        dreame._set(row, **fields_)
    dreame._STATE.pop(_key(who), None)
    log.info("dreame: user %s in org %s connected through Mi Home in %s (%s)", who.user_id, who.org_id, found,
             row.model or "no robot")
    if row.did:
        try:
            dreame.read_rooms(MiCloud(row))
        except (DreameError, dreame.MapError, Lapsed) as exc:
            log.info("dreame: the rooms could not be read on connecting (%s)", exc)
        row = dreame.connection(who.user_id, who.org_id)
    return row


def connect(who, *, user: str, password: str, region: str = "auto"):
    """Sign in to a Xiaomi account. The row, or NeedsCode / NeedsCaptcha with the sign-in kept waiting."""
    user = str(user or "").strip()
    region = str(region or "auto").strip().lower()
    if not user:
        raise Refused("Type the email, phone number or Xiaomi ID of your Mi Home account.")
    if not password:
        raise Refused("Type the password of your Mi Home account.")
    if region != "auto" and region not in REGION_NAMES:
        raise Refused("Choose a region.")
    forget_waiting(who)
    signin = SignIn()
    signin.step1()
    try:
        signin.step2(user, password)
    except NeedsCode:
        sent_to = signin.send_code()
        with _PENDING_LOCK:
            _PENDING[_key(who)] = {"step": "code", "signin": signin, "user": user, "region": region, "at": time.time()}
        raise NeedsCode(sent_to) from None
    except NeedsCaptcha as exc:
        with _PENDING_LOCK:
            _PENDING[_key(who)] = {"step": "captcha", "signin": signin, "user": user, "region": region,
                                   "at": time.time(), "image": str(exc.args[0] if exc.args else ""),
                                   "password": dreame._box().seal(password)}
        raise NeedsCaptcha() from None
    finally:
        password = ""
    signin.step3()
    return _finish(who, signin, user, region)


def answer(who, *, code: str = "", captcha: str = "", again: bool = False):
    """The person's answer to a waiting sign-in: the code, the picture's letters, or a new code asked for."""
    p = _waiting(who)
    if p is None:
        raise Refused(PENDING_GONE)
    signin: SignIn = p["signin"]
    if again:
        if p["step"] != "code":
            raise Refused("There is no code to send again.")
        p["at"] = time.time()
        signin.send_code()
        raise NeedsCode(signin.sent_to)
    if p["step"] == "code":
        code = re.sub(r"\s+", "", str(code or ""))
        if not code:
            raise Refused("Type the code Xiaomi sent.")
        signin.verify(code)
    else:
        captcha = str(captcha or "").strip()
        if not captcha:
            raise Refused("Type the letters in the picture.")
        password = dreame._box().open_(p["password"])
        try:
            signin.step2(p["user"], password, captcha)
        except NeedsCode:
            sent_to = signin.send_code()
            with _PENDING_LOCK:
                _PENDING[_key(who)] = {"step": "code", "signin": signin, "user": p["user"], "region": p["region"],
                                       "at": time.time()}
            raise NeedsCode(sent_to) from None
        except NeedsCaptcha as exc:
            p.update(image=str(exc.args[0] if exc.args else ""), at=time.time())
            raise Refused("Those letters were not right. Here is a new picture.") from None
        finally:
            password = ""
        signin.step3()
    forget_waiting(who)
    return _finish(who, signin, p["user"], p["region"])


def renew(conn):
    """A new serviceToken from the kept passToken, with no password and no code; Lapsed when refused.

    Called by `dreame.refresh` inside its lock, on the row it has just read again."""
    box = dreame._box()
    try:
        session = json.loads(box.open_(conn.session_sealed)) if conn.session_sealed else {}
    except ValueError:
        session = {}
    pass_token = box.open_(conn.refresh_sealed) if conn.refresh_sealed else ""
    if not (pass_token and session.get("client_id")):
        dreame.lapse(conn, LAPSED)
        raise Lapsed(dreame.lapsed_line(conn.lapsed_said))
    signin = SignIn(session["client_id"], pass_token, session.get("user_id", ""))
    if not signin.step1():
        dreame.lapse(conn, LAPSED)
        raise Lapsed(dreame.lapsed_line(conn.lapsed_said))
    signin.step3()
    fields_ = {"access_sealed": box.seal(signin.service_token), "session_sealed": box.seal(json.dumps(signin.session()))}
    if signin.web.cookies.get("passToken") and signin.web.cookies["passToken"] != pass_token:
        fields_["refresh_sealed"] = box.seal(signin.web.cookies["passToken"])
    dreame._set(conn, **fields_)
    log.info("dreame: Mi Home session renewed for user %s", conn.user_id)
    return conn


# --- the robot through Mi Home ----------------------------------------------------------------

def _device(d: dict) -> dict:
    """A Mi Home device in the shape `dreame._pick_robot` and `_robot_name` read."""
    return {"did": str(d.get("did") or ""), "model": str(d.get("model") or ""), "customName": str(d.get("name") or ""),
            "online": d.get("isOnline")}


def list_devices(session: dict, service_token: str, country: str) -> list[dict]:
    """Every device on the account in one country: the account's own list, then each home's."""
    got = call(session, service_token, country, "home/device_list", {"getVirtualModel": False, "getHuamiDevices": 0})
    out = [_device(d) for d in ((got.get("result") or {}).get("list") or []) if isinstance(d, dict)]
    if any(".vacuum." in d["model"] for d in out):
        return out
    homes = call(session, service_token, country, "v2/homeroom/gethome",
                 {"fg": True, "fetch_share": True, "fetch_share_dev": True, "limit": 100, "app_ver": 7})
    for home in ((homes.get("result") or {}).get("homelist") or []):
        if not isinstance(home, dict) or not home.get("id"):
            continue
        devs = call(session, service_token, country, "v2/home/home_device_list",
                    {"home_id": int(home["id"]), "home_owner": int(session.get("user_id") or 0), "limit": 100,
                     "get_split_device": True, "support_smart_home": True})
        seen = {d["did"] for d in out}
        out += [_device(d) for d in ((devs.get("result") or {}).get("device_info") or [])
                if isinstance(d, dict) and str(d.get("did")) not in seen]
    return out


class MiCloud(Cloud):
    """One person's Mi Home account: every call signed, the session renewed from the passToken once
    when Xiaomi refuses it."""

    name = "Mi Home"

    def _session(self) -> dict:
        try:
            return json.loads(dreame._box().open_(self.conn.session_sealed))
        except (ValueError, TypeError):
            raise NotSetUp("Rouh's Mi Home sign-in is incomplete. Press Connect again.") from None

    def _fresh(self) -> None:
        if self.conn.lapsed_at:
            raise Lapsed(dreame.lapsed_line(self.conn.lapsed_said))

    def _once(self, path: str, body) -> dict:
        return call(self._session(), dreame._box().open_(self.conn.access_sealed), self.conn.region, path,
                    body if body is not None else {})

    def api(self, path: str, body=None) -> dict:
        self._fresh()
        try:
            got = self._once(path, body)
        except _AuthFailed:
            self.conn = dreame.refresh(self.conn, force=True, sleep=self._sleep)
            try:
                got = self._once(path, body)
            except _AuthFailed:
                dreame.lapse(self.conn, LAPSED)
                raise Lapsed(dreame.lapsed_line(LAPSED)) from None
        if time.time() - (self.conn.reached_at or 0) > dreame.REACHED_EVERY:
            dreame._set(self.conn, reached_at=time.time())
        return got

    def devices(self) -> list[dict]:
        self._fresh()
        try:
            return list_devices(self._session(), dreame._box().open_(self.conn.access_sealed), self.conn.region)
        except _AuthFailed:
            self.conn = dreame.refresh(self.conn, force=True, sleep=self._sleep)
            return list_devices(self._session(), dreame._box().open_(self.conn.access_sealed), self.conn.region)

    def _pdid(self, siid: int, piid: int) -> str:
        return f"{siid}.{piid}"

    def send(self, method: str, params) -> object:
        did = str(self.conn.did)
        if not did:
            raise NotSetUp("Rouh has no Dreame robot to talk to yet. Press Connect again.")
        got = self.api(f"v2/home/rpc/{did}", {"method": method, "params": params})
        if "result" not in got:
            if got.get("code") in (-2, -3, -9999) or "offline" in str(got.get("message") or "").lower():
                raise DreameError("The robot is not answering the cloud just now: it may be offline or "
                                  "asleep. Try again in a minute.")
            raise DreameError(f"The robot did not answer ({dreame._cloud_said(got)}).")
        return got["result"]

    def file_url(self, object_name: str) -> str:
        got = self.api("v2/home/get_interim_file_url", {"obj_name": object_name})
        url = (got.get("result") or {}).get("url") if isinstance(got.get("result"), dict) else ""
        return url if isinstance(url, str) else ""

