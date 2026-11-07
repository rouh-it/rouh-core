"""Philips Hue through its cloud: the sign-in, the link to the bridge, and the lights themselves.

Petar, 16 October 2026: "can you build the cloud integration", for the lights at home, through the
Philips Hue cloud (the Remote Hue API) rather than the bridge on his own network. He does not use
Hue's streaming (Entertainment, Sync), so there is none here.

**The app.** Hue only lets an app it knows sign in, so the organisation registers a Remote Hue API
app at developers.meethue.com and its administrator types the app's client id, client secret and
app id into Settings, Connections, Philips Hue. The secret is sealed (`encryption.SecretBox`), as
every credential Rouh keeps is; there is no server-wide app and no fallback to one.

**The sign-in.** Connect sends the person to Hue's own sign-in (`consent_url`, OAuth2 with
`/v2/oauth2/authorize`), which comes back to `/auth/hue/callback` with a code; the code is changed
for an access token (7 days) and a refresh token (`exchange`). Both are sealed. The access token is
renewed by itself a few minutes before it ends, and again once if Hue refuses it (`Hue.raw`);
when the refresh token itself is refused the connection is marked lapsed (`lapse`), which the
page, Anatomy's board and the tool all say, and Connect starts again from the top.

**The link.** Once signed in, Rouh presses the bridge's link button through the cloud
(`PUT /route/api/0/config {"linkbutton": true}`) and asks for an application key
(`POST /route/api {"devicetype": "rouh#server"}`), and keeps that key, sealed (`link`).
The cloud's front answers 5xx (521 most of all) when it, or the bridge behind it, cannot be reached
just now, so that press is tried four times over about 20 seconds (`TEMPORARY`, `LINK_WAITS`).
Petar, 17 October 2026, after "The Hue cloud would not press the bridge's link button (HTTP 521)":
when the press still will not go, the sign-in is kept and the page asks for the bridge's own round
button (`ButtonNeeded`, `BUTTON_LINE`); its Try again asks the bridge for a key for up to 30
seconds (`link_button`), which a real press answers through the cloud just as well.
Every call Hue fails is written to rouh.log under `rouh.hue`: the method, the path, the status and
the start of what it said, never a token or a key (`_failed`).

**The lights.** CLIP v2 through the cloud (`/route/clip/v2/resource/...`), with the bearer token
and the `hue-application-key` header. The whole home is read in one call (`read_home`); a room or a
zone is changed through its `grouped_light`, one call for all its lights, never light by light,
and everything off is the home's own `grouped_light` (`bridge_home`). A 429 or a 503 is waited
out, for as long as Retry-After says or 1, 2, 4 and 8 seconds, before giving up (`RETRIES`).

**The Home page** (`/home`, `rouh/web/home.py`, `homepage.js`) reads the whole home every 12
seconds while it is on screen, without waiting out a 429 (`Limited`): it keeps what it showed and
reads again later. Its presses change things by their ids (`page_change`), with the home's shape
kept for `SHAPE_FOR` so a press costs one call.

Names are matched loosely (`match`): "living room", "the lamp in the bedroom" and "bedroom lamp"
each find the one thing they mean, and two things that fit as well as each other are answered
with both, never guessed between. Colours by name or hex become xy inside the light's own gamut
(`colour_xy`), and kelvin becomes mirek inside the light's own range (`kelvin_to_mirek`).

**Whose.** The app is the organisation's; the Hue account, its tokens and the bridge's key are the
one person's who signed in, and every query names their organisation and them.

`ROUH_HUE_API` points every call, the sign-in page included, at a stand-in
(`rouh/testing/fake_hue.py`); `ROUH_HUE_SIGN_IN` is the sign-in page alone, for a stand-in the
browser reaches at another address than Rouh does (the stack test, `tests/stack/settings.env`).
"""
from __future__ import annotations

import base64
import difflib
import logging
import os
import re
import secrets
import threading
import time
import urllib.parse
from dataclasses import dataclass, field

from .encryption import box as _box

log = logging.getLogger("rouh.hue")

#: The Hue cloud, or a stand-in's in a test world.
API = os.environ.get("ROUH_HUE_API", "https://api.meethue.com").rstrip("/")
#: Where the person's browser is sent to sign in to Hue: the cloud's own address, unless set apart.
SIGN_IN = os.environ.get("ROUH_HUE_SIGN_IN", API).rstrip("/")
PAGE = "/anatomy/connections/hue"
CALLBACK = "/auth/hue/callback"
DEVICETYPE = "rouh#server"
TIMEOUT = 20
#: How long before an access token ends that it is renewed.
RENEW_BEFORE = 300.0
#: Waits after a 429 or a 503 when Hue does not say how long, in seconds; then it gives up.
RETRIES = (1.0, 2.0, 4.0, 8.0)
#: The longest Retry-After waited out in a turn somebody is waiting through.
RETRY_MOST = 30.0
#: Answers that mean the Hue cloud, or the bridge behind it, could not be reached just now.
TEMPORARY = frozenset({500, 502, 503, 504, 520, 521, 522, 523, 524})
#: Waits between the tries of the link button's press through the cloud: four tries, about 20 s.
LINK_WAITS = (2.0, 6.0, 10.0)
#: How long one try of the press, or one ask for a key, may take.
LINK_TIMEOUT = 10
#: How long Try again asks the bridge for a key, and how often.
BUTTON_WINDOW = 30.0
BUTTON_EVERY = 2.0
#: What the page says while Rouh has the sign-in and still needs the bridge's own button.
BUTTON_LINE = "Press the round button on top of your Hue bridge, then press Try again within 30 seconds."
#: How much of what Hue said about a failed call goes into the log.
LOGGED = 300
#: How long a consent may take before its state is no longer accepted.
STATE_LIFE = 900.0
#: `reached_at` is written at most this often.
REACHED_EVERY = 60.0
#: Why a connection stopped working, as the page says it beside Connect again.
LAPSED = "Hue would no longer renew Rouh's sign-in."
KEY_GONE = "The Hue bridge no longer accepts Rouh's key."


def lapsed_line(why: str = "") -> str:
    """What a turn says about a connection that stopped working: why, and what to press."""
    return (f"Philips Hue needs connecting again: {why or LAPSED} ‹Owner› presses Connect again in "
            f"Settings, Connections, Philips Hue ({PAGE}).")


class Refused(ValueError):
    """Something typed into the page that cannot be kept, said for the person."""


class NotSetUp(LookupError):
    """No Hue app for this organisation, or no Hue connection for this person."""


class Lapsed(RuntimeError):
    """The sign-in cannot be renewed, or the bridge no longer takes Rouh's key."""


class HueError(Exception):
    """A call Hue refused or never answered, with a sentence that can be said."""


class Unreachable(HueError):
    """No answer from the Hue cloud at all: a timeout or a connection that would not open."""


class Limited(HueError):
    """The Hue cloud answered 429 to a call that was not to wait it out: the Home page's read."""


class ButtonNeeded(HueError):
    """The bridge would not give Rouh a key through the cloud: its own button is needed, and the
    sentence says why."""


# --- the box and the rows ---------------------------------------------------------------------

def _models():
    from .models import HueApp, HueConnection

    return HueApp, HueConnection


def app_of(org_id: str):
    """The organisation's Hue app, or None."""
    return _models()[0].objects.filter(org_id=str(org_id)).first() if org_id else None


def connection(user_id: str, org_id: str):
    """This person's Hue connection, or None. Both ids, always."""
    if not (user_id and org_id):
        return None
    return _models()[1].objects.filter(user_id=str(user_id), org_id=str(org_id)).first()


def _set(conn, **fields) -> None:
    fields["updated_at"] = time.time()
    _models()[1].objects.filter(id=conn.id, user_id=conn.user_id, org_id=conn.org_id).update(**fields)
    for k, v in fields.items():
        setattr(conn, k, v)


def lapse(conn, why: str = LAPSED) -> None:
    """Mark the connection as no longer working, saying why. Connecting again clears it."""
    _set(conn, lapsed_at=time.time(), lapsed_said=why)
    log.info("hue: connection %s for user %s lapsed", conn.id, conn.user_id)


# --- the app, typed into Settings -------------------------------------------------------------

_CLIENT_ID = re.compile(r"^[A-Za-z0-9_.-]{4,200}$")


def _admin(who) -> None:
    if not getattr(who, "is_admin", False):
        raise Refused("Only an administrator of this organisation sets up the Hue app.")


def save_app(who, *, client_id: str = "", client_secret: str = "", app_id: str = "") -> None:
    """Keep the organisation's Hue app: each field given replaces the one kept."""
    _admin(who)
    client_id, app_id = str(client_id or "").strip(), str(app_id or "").strip()
    secret = str(client_secret or "").strip()
    client_secret = ""
    row = app_of(who.org_id)
    if client_id and not _CLIENT_ID.match(client_id):
        raise Refused("That does not look like a Hue client id. Nothing was saved.")
    if app_id and not _CLIENT_ID.match(app_id):
        raise Refused("That does not look like a Hue app id. Nothing was saved.")
    if secret and not (4 <= len(secret) <= 300 and re.match(r"^\S+$", secret)):
        raise Refused("That does not look like a Hue client secret. Nothing was saved.")
    if row is None and not (client_id and secret):
        raise Refused("The client id and the client secret are both needed. Nothing was saved.")
    if not (client_id or secret or app_id):
        raise Refused("Type something to save first.")
    fields: dict = {"saved_by": str(who.user_id), "saved_at": time.time()}
    if client_id:
        fields["client_id"] = client_id
    if app_id:
        fields["app_id"] = app_id
    if secret:
        fields["secret_sealed"] = _box().seal(secret)
        fields["secret_last4"] = secret[-4:]
    secret = ""
    model = _models()[0]
    if row is None:
        model.objects.create(org_id=str(who.org_id), **fields)
    else:
        model.objects.filter(id=row.id, org_id=str(who.org_id)).update(**fields)
    log.info("hue: app saved for org %s by user %s", who.org_id, who.user_id)


def remove_app(who) -> None:
    _admin(who)
    _models()[0].objects.filter(org_id=str(who.org_id)).delete()
    log.info("hue: app removed for org %s by user %s", who.org_id, who.user_id)


# --- the sign-in -------------------------------------------------------------------------------

def callback_url(base: str) -> str:
    """The address Hue sends the person back to: the one registered with the app."""
    return base.rstrip("/") + CALLBACK


def new_state() -> str:
    return secrets.token_urlsafe(24)


def consent_url(app, state: str, base: str) -> str:
    """Hue's own sign-in page for this app, coming back to `callback_url(base)`."""
    q = {"client_id": app.client_id, "response_type": "code", "state": state,
         "redirect_uri": callback_url(base)}
    if app.app_id:
        q["appid"] = app.app_id
    return f"{SIGN_IN}/v2/oauth2/authorize?" + urllib.parse.urlencode(q)


def _basic(app) -> str:
    pair = f"{app.client_id}:{_box().open_(app.secret_sealed)}".encode()
    return "Basic " + base64.b64encode(pair).decode()


def _token_call(app, form: dict) -> dict:
    """POST to Hue's token endpoint, with the app's client id and secret as Basic auth.

    A refusal (400 or 401) raises `Lapsed`; Hue out of reach raises `HueError`."""
    import httpx

    headers = {"Authorization": _basic(app), "Accept": "application/json"}
    try:
        r = httpx.post(f"{API}/v2/oauth2/token", data=form, timeout=TIMEOUT, headers=headers)
    except httpx.HTTPError as exc:
        _failed("POST", "/v2/oauth2/token", type(exc).__name__, "", headers)
        raise HueError(f"Hue's sign-in could not be reached ({type(exc).__name__}).") from None
    if r.status_code >= 300:
        _failed("POST", "/v2/oauth2/token", r.status_code, r.text, headers, form)
    if r.status_code in (400, 401, 403):
        try:
            error = str(r.json().get("error") or r.status_code)
        except ValueError:
            error = str(r.status_code)
        raise Lapsed(error)
    if r.status_code >= 300:
        raise HueError(f"Hue's sign-in answered HTTP {r.status_code}.")
    try:
        got = r.json()
    except ValueError:
        raise HueError("Hue's sign-in answered with something that is not JSON.") from None
    if not isinstance(got, dict) or not got.get("access_token"):
        raise HueError("Hue's sign-in answered without an access token.")
    return got


def _token_fields(got: dict, now: float) -> dict:
    """The sealed tokens and their ends, from what the token endpoint said."""
    def life(*names) -> float:
        for n in names:
            try:
                if got.get(n) is not None:
                    return float(got[n])
            except (TypeError, ValueError):
                pass
        return 0.0
    access_life = life("expires_in", "access_token_expires_in")
    refresh_life = life("refresh_token_expires_in")
    out = {"access_sealed": _box().seal(str(got["access_token"])),
           "access_expires_at": now + access_life if access_life else 0.0,
           "refreshed_at": now}
    if got.get("refresh_token"):
        out["refresh_sealed"] = _box().seal(str(got["refresh_token"]))
        out["refresh_expires_at"] = now + refresh_life if refresh_life else 0.0
    return out


def exchange(app, code: str, base: str) -> dict:
    """The code Hue sent back, changed for tokens: the row's fields, sealed."""
    got = _token_call(app, {"grant_type": "authorization_code", "code": code,
                            "redirect_uri": callback_url(base)})
    return _token_fields(got, time.time())


_LOCKS: dict[int, threading.Lock] = {}
_LOCKS_LOCK = threading.Lock()


def _lock(conn_id: int) -> threading.Lock:
    with _LOCKS_LOCK:
        return _LOCKS.setdefault(conn_id, threading.Lock())


def refresh(conn, *, force: bool = False):
    """Renew the access token, once even when several calls want it at the same moment.

    Inside the lock the row is read again: another call may have renewed it already, and a
    refresh token Hue has replaced must never be used twice."""
    with _lock(conn.id):
        fresh = connection(conn.user_id, conn.org_id)
        if fresh is None or not fresh.refresh_sealed:
            raise NotSetUp("Philips Hue is not connected.")
        if fresh.lapsed_at:
            raise Lapsed(lapsed_line(fresh.lapsed_said))
        if fresh.access_sealed != conn.access_sealed or (
                not force and fresh.access_expires_at and fresh.access_expires_at - time.time() > RENEW_BEFORE):
            return fresh
        app = app_of(fresh.org_id)
        if app is None or not app.secret_sealed:
            raise NotSetUp("The Hue app is not set up in Settings, Connections, Philips Hue.")
        try:
            got = _token_call(app, {"grant_type": "refresh_token",
                                    "refresh_token": _box().open_(fresh.refresh_sealed)})
        except Lapsed as exc:
            log.info("hue: refresh refused for user %s (%s)", fresh.user_id, exc)
            lapse(fresh)
            raise Lapsed(lapsed_line()) from None
        _set(fresh, **_token_fields(got, time.time()))
        log.info("hue: access token renewed for user %s", fresh.user_id)
        return fresh


# --- calls to the bridge through the cloud ----------------------------------------------------

def _retry_after(value, tries: int) -> float:
    try:
        return max(0.5, float(value))
    except (TypeError, ValueError):
        return RETRIES[min(tries, len(RETRIES) - 1)]


def _failed(method: str, path: str, status, said: str, headers: dict | None = None, form=None) -> None:
    """Write one call Hue failed to rouh.log: the method, the path, the status (or the exception's
    name) and the first `LOGGED` characters of what Hue said. Anything secret Rouh sent is masked
    first, should Hue have said it back."""
    said = str(said or "")
    secret = []
    for name, value in (headers or {}).items():
        if name.lower() in ("authorization", "hue-application-key") and value:
            secret += [str(value), str(value).split(" ", 1)[-1]]
    for name in ("code", "refresh_token", "client_secret"):
        if (form or {}).get(name):
            secret.append(str(form[name]))
    for value in secret:
        if len(value) >= 6:
            said = said.replace(value, "[hidden]")
    said = " ".join(said.split())[:LOGGED]
    log.warning("hue: %s %s failed: %s %s", method, path, status, said)


def _request(method: str, url: str, headers: dict, body=None, sleep=time.sleep, *,
             timeout: float = TIMEOUT, wait_out: bool = True):
    """One HTTP call, a 429 or a 503 waited out and made again unless `wait_out` is False.
    Returns the httpx response; no answer at all raises `Unreachable`."""
    import httpx

    path = urllib.parse.urlsplit(url).path
    tries = 0
    while True:
        try:
            r = httpx.request(method, url, headers=headers, json=body, timeout=timeout)
        except httpx.HTTPError as exc:
            _failed(method, path, type(exc).__name__, str(exc), headers)
            raise Unreachable(f"The Hue cloud could not be reached ({type(exc).__name__}).") from None
        if r.status_code >= 400:
            _failed(method, path, r.status_code, r.text, headers)
        if r.status_code not in (429, 503) or not wait_out:
            return r
        if tries >= len(RETRIES):
            raise HueError("The Hue cloud is limiting Rouh's calls just now. Try again in a minute.")
        wait = _retry_after(r.headers.get("Retry-After"), tries)
        if wait > RETRY_MOST:
            raise HueError(f"The Hue cloud asks Rouh to wait {int(wait)} seconds before calling again.")
        log.info("hue: %s %s answered %s; waiting %.1f s", method, path, r.status_code, wait)
        sleep(wait)
        tries += 1


class Hue:
    """One person's bridge through the Hue cloud. Every call has the bearer token, renewed when
    it is near its end or refused once, and the bridge's application key."""

    def __init__(self, conn, *, sleep=time.sleep, wait_out: bool = True) -> None:
        self.conn = conn
        self._sleep = sleep
        #: Whether a 429 or a 503 is waited out (`RETRIES`). The Home page's read is not: it
        #: keeps what it showed and reads again later, slower (`Limited`).
        self.wait_out = wait_out

    def _headers(self, with_key: bool = True) -> dict:
        h = {"Authorization": "Bearer " + _box().open_(self.conn.access_sealed),
             "Accept": "application/json"}
        if with_key:
            if not self.conn.key_sealed:
                raise NotSetUp("Rouh is not linked to the Hue bridge yet. ‹Owner› presses the round button on top "
                               f"of the bridge, then Try again in Settings, Connections, Philips Hue ({PAGE}).")
            h["hue-application-key"] = _box().open_(self.conn.key_sealed)
        return h

    def _fresh(self) -> None:
        if self.conn.lapsed_at:
            raise Lapsed(lapsed_line(self.conn.lapsed_said))
        ends = self.conn.access_expires_at
        if ends and ends - time.time() <= RENEW_BEFORE:
            self.conn = refresh(self.conn)

    def raw(self, method: str, path: str, body=None, *, with_key: bool = True, timeout: float = TIMEOUT,
            wait_out: bool | None = None):
        """The response to one call to `API + path`, renewing the token once on a 401."""
        self._fresh()
        how = {"timeout": timeout, "wait_out": self.wait_out if wait_out is None else wait_out}
        r = _request(method, API + path, self._headers(with_key), body, self._sleep, **how)
        if r.status_code == 401:
            self.conn = refresh(self.conn, force=True)
            r = _request(method, API + path, self._headers(with_key), body, self._sleep, **how)
            if r.status_code == 401:
                lapse(self.conn)
                raise Lapsed(lapsed_line())
        if r.status_code < 500 and time.time() - (self.conn.reached_at or 0) > REACHED_EVERY:
            _set(self.conn, reached_at=time.time())
        return r

    def clip(self, method: str, path: str, body=None) -> list:
        """A CLIP v2 call: `path` under /route/clip/v2/resource. Its `data`, or HueError."""
        r = self.raw(method, "/route/clip/v2/resource" + path, body)
        try:
            got = r.json()
        except ValueError:
            got = {}
        errors = [str((e or {}).get("description") or "")
                  for e in ((got.get("errors") or []) if isinstance(got, dict) else [])]
        if r.status_code == 403 and any("unauthorized" in e.lower() for e in errors):
            lapse(self.conn, KEY_GONE)
            raise Lapsed(lapsed_line(KEY_GONE))
        if r.status_code == 429:
            raise Limited("The Hue cloud is limiting Rouh's calls just now.")
        if r.status_code >= 300:
            said = "; ".join(e for e in errors if e) or f"HTTP {r.status_code}"
            raise HueError(f"The Hue bridge refused that ({said}).")
        return list(got.get("data") or []) if isinstance(got, dict) else []

    # -- the link ---------------------------------------------------------------------------

    def press(self, waits=LINK_WAITS) -> None:
        """Press the bridge's link button through the cloud (`PUT /route/api/0/config`).

        A 429, an answer in `TEMPORARY` or no answer at all is tried again after each of `waits`.
        When it still has not gone, or Hue refused it outright, `ButtonNeeded` says why."""
        tries = 0
        while True:
            status, why = 0, ""
            try:
                r = self.raw("PUT", "/route/api/0/config", {"linkbutton": True}, with_key=False,
                             timeout=LINK_TIMEOUT, wait_out=False)
            except Unreachable as exc:
                why = str(exc)
            else:
                status = r.status_code
                if status < 300:
                    refused = _hue_errors(r)
                    if not refused:
                        return
                    raise ButtonNeeded(f"The Hue bridge would not press its link button for Rouh ({refused[0]}). "
                                       "Press the button on the bridge and Try again.")
            if (status and status != 429 and status not in TEMPORARY) or tries >= len(waits):
                break
            log.info("hue: the link button's press answered %s; trying again in %.0f s",
                     status or "nothing", waits[tries])
            self._sleep(waits[tries])
            tries += 1
        raise ButtonNeeded(_why_no_press(status, why))

    def ask_key(self, window: float, every: float, between=None) -> tuple[str, str]:
        """Ask the bridge for an application key (`POST /route/api`) until it gives one, or for
        `window` seconds, every `every` seconds. `between` is called once, after the first ask
        that got none. (the key, or "" and the last reason it gave none)."""
        ends = time.monotonic() + window
        asks = max(1, int(window // every) + 1) if every > 0 else 1
        last = ""
        for n in range(asks):
            try:
                r = self.raw("POST", "/route/api", {"devicetype": DEVICETYPE}, with_key=False,
                             timeout=LINK_TIMEOUT, wait_out=False)
            except Unreachable as exc:
                last = str(exc)
            else:
                if r.status_code >= 300:
                    last = f"HTTP {r.status_code}"
                    if r.status_code != 429 and r.status_code not in TEMPORARY:
                        return "", last
                else:
                    try:
                        got = r.json()
                    except ValueError:
                        got = None
                    for one in got if isinstance(got, list) else []:
                        key = ((one or {}).get("success") or {}).get("username")
                        if key:
                            return str(key), ""
                        last = str(((one or {}).get("error") or {}).get("description") or last)
            if n == 0 and between is not None:
                between()
            if n + 1 >= asks or time.monotonic() + every > ends:
                break
            self._sleep(every)
        return "", last

    def link(self) -> str:
        """Press the bridge's link button through the cloud and ask for an application key.
        `ButtonNeeded` when either will not come: the bridge's own button is needed."""
        self.press()
        key, last = self.ask_key(4.0, 1.5)
        if key:
            return key
        raise ButtonNeeded(_why_no_key(last))

    def link_by_button(self) -> str:
        """Try again: ask the bridge for a key for up to `BUTTON_WINDOW` seconds, which a press of
        its own button answers. After the first ask the button is pressed once through the cloud
        too, in case the cloud reaches the bridge again."""
        def press_once():
            try:
                self.press(waits=())
            except ButtonNeeded as exc:
                log.info("hue: the link button's press through the cloud still failed (%s)", exc)
        key, last = self.ask_key(BUTTON_WINDOW, BUTTON_EVERY, between=press_once)
        if key:
            return key
        if last == "link button not pressed":
            # The page says `BUTTON_LINE` beside it already.
            raise ButtonNeeded("The bridge's button was not pressed in time.")
        raise ButtonNeeded(_why_no_key(last))


def _hue_errors(r) -> list[str]:
    """What a bridge said went wrong, in its own `[{"error": {...}}]`, in a 200."""
    try:
        got = r.json()
    except ValueError:
        return []
    return [str((one.get("error") or {}).get("description") or "an error")
            for one in (got if isinstance(got, list) else []) if isinstance(one, dict) and one.get("error")]


def _why_no_press(status: int, why: str) -> str:
    """Why the link button could not be pressed through the cloud, in plain words, with the code."""
    if status in TEMPORARY:
        return (f"The Hue cloud could not reach your bridge right now (HTTP {status}). Check in the Hue app "
                "that the bridge is online, then press the button on the bridge and Try again.")
    if status == 429:
        return ("The Hue cloud is limiting Rouh's calls just now (HTTP 429). Press the button on the bridge "
                "and Try again in a minute.")
    if not status:
        return (f"{why or 'The Hue cloud did not answer.'} Check in the Hue app that the bridge is online, "
                "then press the button on the bridge and Try again.")
    return (f"The Hue cloud would not press the bridge's link button for Rouh (HTTP {status}). Press the "
            "button on the bridge and Try again.")


def _why_no_key(last: str) -> str:
    """Why the bridge gave no key, in plain words."""
    code = re.match(r"^HTTP (\d+)$", last or "")
    if code:
        return _why_no_press(int(code.group(1)), "")
    if last.startswith("The Hue cloud"):
        return _why_no_press(0, last)
    return ("The Hue bridge did not give Rouh a key" + (f" ({last})" if last else "") + ". "
            "Press the button on the bridge and Try again.")


def _bridge_name(hue: Hue) -> tuple[str, str]:
    """(bridge id, its name) as the bridge itself says."""
    bridges = hue.clip("GET", "/bridge")
    if not bridges:
        return "", "Hue Bridge"
    b = bridges[0]
    name = ""
    owner = (b.get("owner") or {}).get("rid")
    if owner:
        for d in hue.clip("GET", f"/device/{owner}"):
            name = str((d.get("metadata") or {}).get("name") or "")
    return str(b.get("bridge_id") or ""), name or "Hue Bridge"


def finish(who, code: str, base: str):
    """Back from Hue's sign-in: the tokens kept, the bridge linked, its name read. The row."""
    app = app_of(who.org_id)
    if app is None or not app.secret_sealed:
        raise NotSetUp("The Hue app is not set up yet.")
    fields = exchange(app, code, base)
    code = ""
    model = _models()[1]
    now = time.time()
    row = connection(who.user_id, who.org_id)
    blank = {"key_sealed": "", "bridge_id": "", "bridge_name": "", "lapsed_at": 0.0, "lapsed_said": "",
             "connected_at": now, "reached_at": now, "updated_at": now}
    if row is None:
        row = model.objects.create(org_id=str(who.org_id), user_id=str(who.user_id), made_at=now,
                                   **fields, **blank)
    else:
        _set(row, **fields, **blank)
    hue = Hue(row)
    try:
        key = hue.link()
    except ButtonNeeded as exc:
        # The sign-in stays: the page asks for the bridge's own button, and Try again finishes it.
        log.info("hue: user %s in org %s signed in, and the bridge needs its button (%s)",
                 who.user_id, who.org_id, exc)
        raise
    return _linked(hue, key)


def _linked(hue: Hue, key: str):
    """Keep the bridge's key, sealed, and read the bridge's name. The row."""
    _set(hue.conn, key_sealed=_box().seal(key), lapsed_at=0.0, lapsed_said="")
    key = ""
    try:
        bridge_id, name = _bridge_name(hue)
    except HueError as exc:
        # The key is what matters; Check now reads the name later.
        log.info("hue: linked, and the bridge's name could not be read (%s)", exc)
        bridge_id, name = hue.conn.bridge_id, hue.conn.bridge_name
    _set(hue.conn, bridge_id=bridge_id, bridge_name=name)
    log.info("hue: user %s in org %s linked to bridge %s", hue.conn.user_id, hue.conn.org_id, bridge_id)
    return hue.conn


def link_button(who) -> str:
    """Try again, once the bridge's own button is pressed: ask it for a key for up to 30 seconds."""
    conn = connection(who.user_id, who.org_id)
    if conn is None or not conn.access_sealed:
        raise Refused("Philips Hue is not connected. Press Connect first.")
    if conn.lapsed_at:
        raise Lapsed(lapsed_line(conn.lapsed_said))
    hue = Hue(conn)
    conn = _linked(hue, hue.link_by_button())
    return f"Linked to {conn.bridge_name or 'your Hue Bridge'}."


def check(who) -> str:
    """Reach the bridge now: what to say about it."""
    conn = connection(who.user_id, who.org_id)
    if conn is None:
        raise Refused("Philips Hue is not connected.")
    hue = Hue(conn)
    bridge_id, name = _bridge_name(hue)
    _set(hue.conn, bridge_id=bridge_id or hue.conn.bridge_id, bridge_name=name, reached_at=time.time())
    return f"{name} answered just now."


def disconnect(who) -> bool:
    """Forget this person's tokens and the bridge's key for Rouh."""
    gone, _ = _models()[1].objects.filter(user_id=str(who.user_id), org_id=str(who.org_id)).delete()
    log.info("hue: user %s in org %s disconnected", who.user_id, who.org_id)
    return bool(gone)


def _when(ts) -> str:
    from . import clock

    return clock.moment(ts).strftime("%-d %b %Y, %H:%M") if ts else ""


def public(who, base: str = "") -> dict:
    """Everything the page shows. Never a secret, a token or the key."""
    app = app_of(who.org_id)
    conn = connection(who.user_id, who.org_id)
    out = {"admin": bool(getattr(who, "is_admin", False)), "callback": callback_url(base) if base else "",
           "app": None, "connected": False}
    if app is not None:
        out["app"] = {"client_id": app.client_id, "secret_last4": app.secret_last4 if app.secret_sealed else "",
                      "app_id": app.app_id, "ready": bool(app.client_id and app.secret_sealed)}
    if conn is not None:
        out.update(connected=bool(conn.access_sealed and conn.key_sealed and not conn.lapsed_at),
                   linked=bool(conn.key_sealed),
                   needs_button=bool(conn.access_sealed and not conn.key_sealed and not conn.lapsed_at), lapsed=bool(conn.lapsed_at), lapsed_said=conn.lapsed_said,
                   bridge=conn.bridge_name, since=_when(conn.connected_at), reached=_when(conn.reached_at),
                   reached_at=conn.reached_at)
    return out


# --- colours -----------------------------------------------------------------------------------

#: Hue's three colour gamuts, as (red, green, blue) corners in CIE xy.
GAMUTS = {
    "A": ((0.704, 0.296), (0.2151, 0.7106), (0.138, 0.08)),
    "B": ((0.675, 0.322), (0.409, 0.518), (0.167, 0.04)),
    "C": ((0.6915, 0.3083), (0.17, 0.7), (0.1532, 0.0475)),
}
#: Whites by name are colour temperatures, in kelvin.
WHITES = {"warm white": 2700, "soft white": 2700, "warm": 2700, "candle": 2000, "candlelight": 2000,
          "white": 4000, "neutral white": 4000, "neutral": 4000, "cool white": 5000, "cool": 5000,
          "daylight": 6500, "cold white": 6500, "bright white": 5000}
#: Colours by name, as sRGB hex.
COLOURS = {
    "red": "ff0000", "dark red": "8b0000", "crimson": "dc143c", "orange": "ff8000", "amber": "ffbf00",
    "gold": "ffd700", "yellow": "ffff00", "lime": "bfff00", "green": "00ff00", "dark green": "006400",
    "mint": "98ff98", "teal": "008080", "turquoise": "40e0d0", "cyan": "00ffff", "aqua": "00ffff",
    "sky blue": "87ceeb", "light blue": "add8e6", "blue": "0000ff", "navy": "000080", "indigo": "4b0082",
    "violet": "8f00ff", "purple": "800080", "lavender": "b57edc", "magenta": "ff00ff", "fuchsia": "ff00ff",
    "pink": "ff69b4", "hot pink": "ff1493", "light pink": "ffb6c1", "rose": "ff007f", "salmon": "fa8072",
    "coral": "ff7f50", "peach": "ffcba4", "warm orange": "ff6a00",
}
_HEX = re.compile(r"^#?([0-9a-f]{3}|[0-9a-f]{6})$")


def rgb_to_xy(r: float, g: float, b: float) -> tuple[float, float]:
    """sRGB (0 to 1 each) to CIE 1931 xy, through linear light and XYZ (D65)."""
    def lin(c: float) -> float:
        return ((c + 0.055) / 1.055) ** 2.4 if c > 0.04045 else c / 12.92
    r, g, b = lin(r), lin(g), lin(b)
    x = r * 0.4124 + g * 0.3576 + b * 0.1805
    y = r * 0.2126 + g * 0.7152 + b * 0.0722
    z = r * 0.0193 + g * 0.1192 + b * 0.9505
    total = x + y + z
    if total <= 0:
        return (0.3127, 0.3290)
    return (x / total, y / total)


def _cross(o, a, b) -> float:
    return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])


def in_gamut(xy, gamut) -> bool:
    r, g, b = gamut
    d1, d2, d3 = _cross(r, g, xy), _cross(g, b, xy), _cross(b, r, xy)
    neg = d1 < 0 or d2 < 0 or d3 < 0
    pos = d1 > 0 or d2 > 0 or d3 > 0
    return not (neg and pos)


def _closest_on(p, a, b):
    ax, ay = p[0] - a[0], p[1] - a[1]
    bx, by = b[0] - a[0], b[1] - a[1]
    t = max(0.0, min(1.0, (ax * bx + ay * by) / ((bx * bx + by * by) or 1e-12)))
    return (a[0] + bx * t, a[1] + by * t)


def clamp_to_gamut(xy, gamut) -> tuple[float, float]:
    """The point itself when the light can show it, or the nearest one it can."""
    if gamut is None or in_gamut(xy, gamut):
        return (xy[0], xy[1])
    r, g, b = gamut
    near = [_closest_on(xy, r, g), _closest_on(xy, g, b), _closest_on(xy, b, r)]
    return min(near, key=lambda q: (q[0] - xy[0]) ** 2 + (q[1] - xy[1]) ** 2)


def gamut_of(light: dict):
    """A CLIP v2 light's gamut as three corners, or None when it shows no colour."""
    c = light.get("color") or {}
    g = c.get("gamut")
    if isinstance(g, dict) and all(isinstance(g.get(k), dict) for k in ("red", "green", "blue")):
        return tuple((float(g[k]["x"]), float(g[k]["y"])) for k in ("red", "green", "blue"))
    t = str(c.get("gamut_type") or "")
    return GAMUTS.get(t) if c else None


def parse_colour(text: str):
    """("kelvin", K) for a white, ("xy", (x, y), "name") for a colour, or ValueError saying why."""
    t = re.sub(r"\s+", " ", str(text or "").strip().lower())
    if not t:
        raise ValueError("Say a colour.")
    if t in WHITES:
        return ("kelvin", WHITES[t])
    hexed = _HEX.match(t)
    name = t
    if hexed:
        h = hexed.group(1)
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        name = "#" + h
    elif t in COLOURS or t.replace("grey", "gray") in COLOURS:
        h = COLOURS[t]
    else:
        near = difflib.get_close_matches(t, list(COLOURS) + list(WHITES), n=1, cutoff=0.8)
        if not near:
            raise ValueError(f"Rouh does not know the colour {text!r}. Say a colour such as red, warm white "
                             "or blue, or a hex code such as #ff8800.")
        return parse_colour(near[0])
    rgb = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    return ("xy", rgb_to_xy(*rgb), name)


def colour_xy(text: str, gamut) -> tuple[float, float]:
    """A colour by name or hex as xy inside `gamut`. ValueError for a white or an unknown one."""
    got = parse_colour(text)
    if got[0] != "xy":
        raise ValueError(f"{text} is a white: it is set as a colour temperature.")
    return clamp_to_gamut(got[1], gamut)


def kelvin_to_mirek(kelvin: float, schema: dict | None = None) -> int:
    """Kelvin as mirek (a million over kelvin), inside the light's own range (153 to 500 unless it says)."""
    k = float(kelvin)
    if k <= 0:
        raise ValueError("A colour temperature is a number of kelvin, such as 2700.")
    lo = int((schema or {}).get("mirek_minimum") or 153)
    hi = int((schema or {}).get("mirek_maximum") or 500)
    return max(lo, min(hi, round(1_000_000 / k)))


def nearest_colour_name(xy) -> str:
    """The name of the colour nearest an xy point, to say a light's colour in words."""
    best, far = "", 9.0
    for name, h in COLOURS.items():
        p = rgb_to_xy(*[int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)])
        d = (p[0] - xy[0]) ** 2 + (p[1] - xy[1]) ** 2
        if d < far:
            best, far = name, d
    return best


# --- names -------------------------------------------------------------------------------------

#: Words that say nothing about which thing is meant.
STOP = frozenset("the a an my our in on at of by to for please all whole entire".split())
#: Words that only say "a light", which never find a thing on their own name alone.
GENERIC = frozenset({"light", "lights", "lamp", "lamps", "bulb", "bulbs"})
#: A light's archetype, when it is something a person would call a lamp.
_ARCHETYPE_LAMP = ("shade", "lantern", "lamp", "hue_go", "bloom", "iris", "table", "floor", "desk")


def words(text: str) -> list[str]:
    t = re.sub(r"[^a-z0-9]+", " ", str(text or "").lower().replace("'s", ""))
    return [w for w in t.split() if w not in STOP]


def _stem(w: str) -> str:
    return w[:-1] if len(w) > 3 and w.endswith("s") and not w.endswith("ss") else w


def _same(a: str, b: str) -> bool:
    a, b = _stem(a), _stem(b)
    if a == b:
        return True
    if len(a) >= 4 and len(b) >= 4 and (a.startswith(b) or b.startswith(a)):
        return True
    return len(a) >= 5 and difflib.SequenceMatcher(None, a, b).ratio() >= 0.85


@dataclass
class Thing:
    """A room, a zone, a light or a scene, with the words it can be called by."""

    kind: str
    id: str
    name: str
    #: More words that point at it: for a light its room's name and what it is (a lamp, a
    #: ceiling light), for a room or a zone "lights", for a scene its room's name.
    more: list[str] = field(default_factory=list)
    data: dict = field(default_factory=dict)

    def label(self) -> str:
        where = self.data.get("room") if self.kind in ("light", "scene") else ""
        return f"{self.name} ({self.kind}{', in ' + where if where else ''})"


def score(query: list[str], thing: Thing) -> float:
    """How well the words said fit a thing, 0 to 100: its own name said exactly is 100.

    Mostly how much of what was said the thing explains, by its name or the words beside it,
    and then how much of its own name was said. "The lamp in the bedroom" is explained whole by
    a lamp in the bedroom and only half by the bedroom itself."""
    own = words(thing.name)
    if not query or not own:
        return 0.0
    if [_stem(w) for w in query] == [_stem(w) for w in own]:
        return 100.0
    pool = own + thing.more
    explained = [w for w in query if any(_same(w, n) for n in pool)]
    if not explained:
        return 0.0
    if any(w not in GENERIC for w in query) and all(w in GENERIC for w in explained):
        return 0.0
    named = [n for n in own if any(_same(n, w) for w in query)]
    return 60.0 * len(explained) / len(query) + 30.0 * len(named) / len(own)


KIND_ORDER = {"room": 0, "zone": 1, "light": 2, "scene": 3}
#: The least a fit may score to count at all.
FIT = 45.0


def match(text: str, things: list[Thing]) -> tuple[Thing | None, list[Thing]]:
    """(the one thing meant, []) or (None, the candidates that fit as well as each other).

    (None, []) is nothing at all. Two equal fits of different kinds go to the room before the
    zone before the light, as a room called Office beats a light called Office; two of one kind
    are never guessed between."""
    query = words(text)
    scored = [(score(query, t), t) for t in things]
    scored = [(s, t) for s, t in scored if s >= FIT]
    if not scored:
        return None, []
    top = max(s for s, _ in scored)
    best = sorted((t for s, t in scored if top - s < 1e-6), key=lambda t: KIND_ORDER.get(t.kind, 9))
    first = KIND_ORDER.get(best[0].kind, 9)
    best = [t for t in best if KIND_ORDER.get(t.kind, 9) == first]
    return (best[0], []) if len(best) == 1 else (None, best[:8])


# --- the home ----------------------------------------------------------------------------------

def _name(r: dict) -> str:
    return str((r.get("metadata") or {}).get("name") or "").strip()


@dataclass
class Home:
    """Everything the bridge has, as one read of `/resource` makes it."""

    rooms: list[Thing]
    zones: list[Thing]
    lights: list[Thing]
    scenes: list[Thing]
    #: The grouped_light of the whole home, for everything off at once.
    everything: str = ""
    groups: dict = field(default_factory=dict)

    def targets(self) -> list[Thing]:
        return self.rooms + self.zones + self.lights


def build_home(resources: list[dict]) -> Home:
    by_type: dict[str, list[dict]] = {}
    for r in resources:
        by_type.setdefault(str(r.get("type") or ""), []).append(r)
    lights = {r["id"]: r for r in by_type.get("light", []) if r.get("id")}
    groups = {r["id"]: r for r in by_type.get("grouped_light", []) if r.get("id")}
    device_lights: dict[str, list[str]] = {}
    for d in by_type.get("device", []):
        device_lights[d.get("id")] = [s["rid"] for s in d.get("services") or [] if s.get("rtype") == "light"]

    def lights_of(group: dict) -> list[str]:
        out = []
        for c in group.get("children") or []:
            if c.get("rtype") == "device":
                out += device_lights.get(c.get("rid"), [])
            elif c.get("rtype") == "light":
                out.append(c.get("rid"))
        return [i for i in out if i in lights]

    def grouped(group: dict) -> str:
        return next((s["rid"] for s in group.get("services") or [] if s.get("rtype") == "grouped_light"), "")

    room_of: dict[str, str] = {}
    rooms, zones = [], []
    for kind, out in (("room", rooms), ("zone", zones)):
        for g in sorted(by_type.get(kind, []), key=_name):
            members = lights_of(g)
            if kind == "room":
                for i in members:
                    room_of[i] = _name(g)
            gl = groups.get(grouped(g), {})
            out.append(Thing(kind, g["id"], _name(g), more=["lights"], data={
                "grouped_light": grouped(g), "lights": members,
                "on": bool((gl.get("on") or {}).get("on")),
                "brightness": (gl.get("dimming") or {}).get("brightness")}))
    things = []
    for i, l in sorted(lights.items(), key=lambda p: _name(p[1])):
        arche = str((l.get("metadata") or {}).get("archetype") or "")
        more = words(room_of.get(i, "")) + [w for w in arche.split("_") if w and w not in ("bulb",)]
        if any(a in arche for a in _ARCHETYPE_LAMP):
            more.append("lamp")
        things.append(Thing("light", i, _name(l), more=more, data={"room": room_of.get(i, ""), "raw": l}))
    scenes = []
    for s in sorted(by_type.get("scene", []), key=_name):
        g = (s.get("group") or {}).get("rid", "")
        status = str((s.get("status") or {}).get("active") or "inactive")
        scenes.append(Thing("scene", s["id"], _name(s), data={"group": g, "active": status != "inactive"}))
    names = {t.id: t.name for t in rooms + zones}
    for t in scenes:
        t.data["room"] = names.get(t.data["group"], "")
        t.more = words(t.data["room"])
    everything = next((g for g, r in groups.items() if (r.get("owner") or {}).get("rtype") == "bridge_home"), "")
    return Home(rooms, zones, things, scenes, everything, groups)


def read_home(hue: Hue) -> Home:
    """The whole home in one call; type by type only if the bridge will not answer that one."""
    try:
        return build_home(hue.clip("GET", ""))
    except Limited:
        # Seven more calls are the last thing a cloud that is limiting Rouh needs.
        raise
    except HueError:
        got: list = []
        for t in ("room", "zone", "device", "light", "grouped_light", "scene", "bridge_home"):
            got += [{**r, "type": r.get("type") or t} for r in hue.clip("GET", "/" + t)]
        return build_home(got)


def _pct(v) -> str:
    try:
        return f"{round(float(v))}%"
    except (TypeError, ValueError):
        return ""


def light_state(raw: dict) -> str:
    """One light's state in a few words: off, or on with brightness and colour."""
    if not (raw.get("on") or {}).get("on"):
        return "off"
    out = ["on"]
    b = _pct((raw.get("dimming") or {}).get("brightness"))
    if b:
        out.append(b)
    ct = raw.get("color_temperature") or {}
    xy = ((raw.get("color") or {}).get("xy") or {})
    if ct.get("mirek_valid") and ct.get("mirek"):
        out.append(f"{round(1_000_000 / float(ct['mirek']) / 50) * 50} K")
    elif xy.get("x") is not None and raw.get("color"):
        out.append(nearest_colour_name((float(xy["x"]), float(xy["y"]))))
    return ", ".join(out)


def describe(home: Home, bridge: str = "") -> str:
    """The home as a few lines: rooms and zones with their lights and scenes, and the rest."""
    lights = {t.id: t for t in home.lights}
    scenes_of: dict[str, list[Thing]] = {}
    for s in home.scenes:
        scenes_of.setdefault(s.data["group"], []).append(s)
    lines = [f"Philips Hue{', ' + bridge if bridge else ''}."]
    placed = set()
    for title, groups in (("Rooms", home.rooms), ("Zones", home.zones)):
        if not groups:
            continue
        lines.append(f"{title}:")
        for g in groups:
            state = "on" + (f", {_pct(g.data['brightness'])}" if g.data.get("brightness") is not None else "") \
                if g.data["on"] else "off"
            ls = [f"{lights[i].name} ({light_state(lights[i].data['raw'])})" for i in g.data["lights"] if i in lights]
            if g.kind == "room":
                placed.update(g.data["lights"])
            sc = scenes_of.get(g.id, [])
            line = f"- {g.name}: {state}"
            if ls:
                line += "; lights: " + ", ".join(ls)
            if sc:
                line += "; scenes: " + ", ".join(s.name + (" (active)" if s.data["active"] else "") for s in sc)
            lines.append(line)
    rest = [t for t in home.lights if t.id not in placed]
    if rest:
        lines.append("Lights in no room: " + ", ".join(f"{t.name} ({light_state(t.data['raw'])})" for t in rest))
    if not home.lights:
        lines.append("The bridge has no lights.")
    return "\n".join(lines)


def _ambiguous(what: str, said: str, candidates: list[Thing]) -> str:
    return (f"More than one {what} fits {said!r}: " + "; ".join(t.label() for t in candidates)
            + ". Say which.")


def _not_found(what: str, said: str, choices: list[Thing]) -> str:
    names = ", ".join(sorted({t.name for t in choices})[:30])
    return f"No {what} is called anything like {said!r}." + (f" There are: {names}." if names else "")


def set_state(hue: Hue, home: Home, target: str, *, on=None, brightness=None, colour: str = "",
              kelvin=None, transition=None) -> str:
    """Change one room, zone or light; what changed, in a line."""
    thing, candidates = match(target, home.targets())
    if thing is None:
        return _ambiguous("light, room or zone", target, candidates) if candidates else \
            _not_found("light, room or zone", target, home.targets())
    return change(hue, home, thing, on=on, brightness=brightness, colour=colour, kelvin=kelvin,
                  transition=transition)


def change(hue: Hue, home: Home, thing: Thing, *, on=None, brightness=None, colour: str = "",
           kelvin=None, transition=None) -> str:
    """Change one room, zone or light already found; what changed, in a line."""
    if on is None and brightness is None and not colour and kelvin is None:
        return "Say what to change: on or off, brightness, colour or colour temperature."
    if colour:
        try:
            parsed = parse_colour(colour)
        except ValueError as exc:
            return str(exc)
        if parsed[0] == "kelvin":
            kelvin, colour = parsed[1], ""
    lights = {t.id: t for t in home.lights}
    members = [lights[i].data["raw"] for i in (thing.data["lights"] if thing.kind != "light" else [thing.id])
               if i in lights]
    body: dict = {}
    said: list[str] = []
    if brightness is not None:
        try:
            b = max(0.0, min(100.0, float(brightness)))
        except (TypeError, ValueError):
            return "Brightness is a number from 0 to 100."
        if b <= 0:
            on = False
        else:
            body["dimming"] = {"brightness": b}
            said.append(f"{round(b)}%")
            on = True if on is None else on
    if colour:
        coloured = [m for m in members if m.get("color")]
        if not coloured:
            return f"{thing.label()} cannot show colours: it has no colour lights."
        gamuts = {gamut_of(m) for m in coloured}
        gamut = gamuts.pop() if len(gamuts) == 1 else GAMUTS["C"]
        xy = clamp_to_gamut(parsed[1], gamut)
        body["color"] = {"xy": {"x": round(xy[0], 4), "y": round(xy[1], 4)}}
        said.append(parsed[2])
        on = True if on is None else on
    if kelvin is not None:
        whites = [m for m in members if m.get("color_temperature")]
        if not whites:
            return f"{thing.label()} cannot change its colour temperature."
        try:
            schema = (whites[0].get("color_temperature") or {}).get("mirek_schema") or {}
            mirek = kelvin_to_mirek(float(kelvin), schema)
        except (TypeError, ValueError) as exc:
            return str(exc) or "A colour temperature is a number of kelvin, such as 2700."
        body["color_temperature"] = {"mirek": mirek}
        said.append(f"{round(1_000_000 / mirek / 50) * 50} K")
        on = True if on is None else on
    if on is not None:
        body["on"] = {"on": bool(on)}
        if not on:
            body.pop("dimming", None)
            body.pop("color", None)
            body.pop("color_temperature", None)
            said = []
    if transition is not None:
        try:
            ms = int(max(0.0, min(3600.0, float(transition))) * 1000)
            body["dynamics"] = {"duration": ms}
        except (TypeError, ValueError):
            return "A transition is a number of seconds."
    if thing.kind == "light":
        hue.clip("PUT", f"/light/{thing.id}", body)
    else:
        if not thing.data.get("grouped_light"):
            return f"{thing.label()} has no lights Rouh can change together."
        hue.clip("PUT", f"/grouped_light/{thing.data['grouped_light']}", body)
    head = "on" if body.get("on", {}).get("on") else "off" if "on" in body else ""
    parts = [p for p in [head] + said if p]
    over = f", over {body['dynamics']['duration'] / 1000:g} s" if "dynamics" in body and body["dynamics"]["duration"] else ""
    return f"{thing.name}: {', '.join(parts)}{over}."


def scene(hue: Hue, home: Home, name: str, room: str = "", transition=None) -> str:
    """Activate a scene by its name, in a room or zone when one is said."""
    pool = home.scenes
    where = None
    if room:
        where, candidates = match(room, home.rooms + home.zones)
        if where is None:
            return _ambiguous("room or zone", room, candidates) if candidates else \
                _not_found("room or zone", room, home.rooms + home.zones)
        pool = [s for s in pool if s.data["group"] == where.id]
    found, candidates = match(name, pool)
    if found is None:
        if candidates:
            return (f"More than one scene fits {name!r}: "
                    + "; ".join(f"{c.name} in {c.data['room'] or 'no room'}" for c in candidates)
                    + ". Say which room.")
        return _not_found("scene" + (f" in {where.name}" if where else ""), name, pool)
    body: dict = {"recall": {"action": "active"}}
    if transition is not None:
        try:
            body["recall"]["duration"] = int(max(0.0, min(3600.0, float(transition))) * 1000)
        except (TypeError, ValueError):
            return "A transition is a number of seconds."
    hue.clip("PUT", f"/scene/{found.id}", body)
    return f"{found.name} is on in {found.data['room'] or 'its room'}."


def all_off(hue: Hue, home: Home, transition=None) -> str:
    """Every light off: the home's own grouped_light, or each room's when there is none."""
    body: dict = {"on": {"on": False}}
    if transition is not None:
        try:
            body["dynamics"] = {"duration": int(max(0.0, min(3600.0, float(transition))) * 1000)}
        except (TypeError, ValueError):
            return "A transition is a number of seconds."
    if home.everything:
        hue.clip("PUT", f"/grouped_light/{home.everything}", body)
        return "Every light is off."
    done = 0
    for r in home.rooms:
        if r.data.get("grouped_light"):
            hue.clip("PUT", f"/grouped_light/{r.data['grouped_light']}", body)
            done += 1
    return f"Every light is off ({done} room{'' if done == 1 else 's'})."


def _onoff(value):
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    t = str(value).strip().lower()
    if t in ("on", "true", "yes", "1"):
        return True
    if t in ("off", "false", "no", "0"):
        return False
    return None


def run(who, args: dict) -> str:
    """The `hue` tool for a turn: list, set, scene or all_off. A sentence or a few lines."""
    conn = connection(who.user_id, who.org_id)
    if conn is None or not conn.access_sealed:
        return (f"Philips Hue is not connected. ‹Owner› connects it in Settings, Connections, Philips Hue "
                f"({PAGE}).")
    if conn.lapsed_at:
        return lapsed_line(conn.lapsed_said)
    action = str(args.get("action") or "list").strip().lower().replace(" ", "_")
    hue = Hue(conn)
    try:
        home = read_home(hue)
        if action == "list":
            return describe(home, hue.conn.bridge_name)
        if action == "set":
            target = str(args.get("target") or "").strip()
            if not target:
                return "Say which light, room or zone (target)."
            return set_state(hue, home, target, on=_onoff(args.get("on")), brightness=args.get("brightness"),
                             colour=str(args.get("colour") or args.get("color") or ""),
                             kelvin=args.get("kelvin"), transition=args.get("transition"))
        if action == "scene":
            name = str(args.get("scene") or "").strip()
            if not name:
                return "Say which scene."
            return scene(hue, home, name, str(args.get("target") or args.get("room") or ""),
                         args.get("transition"))
        if action in ("all_off", "alloff", "off"):
            return all_off(hue, home, args.get("transition"))
        return "The actions are list, set, scene and all_off."
    except Lapsed as exc:
        return str(exc) or lapsed_line()
    except NotSetUp as exc:
        return str(exc)
    except HueError as exc:
        return str(exc)


# --- the Home page -----------------------------------------------------------------------------
#
# Petar, 17 October 2026: "chat is not going to cut it. Very cumbersome. I need interface and
# quick access". The Home page (`/home`, `homepage.js`, `rouh/web/home.py`) shows every room and
# zone as a tile and changes them by their ids, never by a name matched loosely: what was pressed
# is what is changed.

#: How long the home's shape (its rooms, their lights and grouped_lights, the scenes) is used for
#: a change before it is read again. The page reads it every 12 seconds while it is open.
SHAPE_FOR = 120.0
_SHAPES: dict[int, tuple[float, Home]] = {}
_RID = re.compile(r"^[A-Za-z0-9-]{1,64}$")


def xy_to_hex(x: float, y: float) -> str:
    """CIE xy as the sRGB colour a screen can show of it, at full brightness."""
    y = max(float(y), 1e-6)
    big_x, big_z = x / y, (1.0 - x - y) / y
    r = big_x * 3.2406 - 1.5372 - big_z * 0.4986
    g = -big_x * 0.9689 + 1.8758 + big_z * 0.0415
    b = big_x * 0.0557 - 0.2040 + big_z * 1.0570
    top = max(r, g, b, 1e-6)

    def srgb(c: float) -> int:
        c = max(0.0, c / top)
        c = 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055
        return round(max(0.0, min(1.0, c)) * 255)
    return "#%02x%02x%02x" % (srgb(r), srgb(g), srgb(b))


def mirek_to_hex(mirek: float) -> str:
    """A white of `mirek` as an sRGB colour (Tanner Helland's fit of the black body)."""
    import math

    t = max(1000.0, min(40000.0, 1_000_000 / max(float(mirek), 1.0))) / 100
    r = 255.0 if t <= 66 else 329.698727446 * (t - 60) ** -0.1332047592
    g = 99.4708025861 * math.log(t) - 161.1195681661 if t <= 66 else 288.1221695283 * (t - 60) ** -0.0755148492
    b = 255.0 if t >= 66 else (0.0 if t <= 19 else 138.5177312231 * math.log(t - 10) - 305.0447927307)
    return "#%02x%02x%02x" % tuple(round(max(0.0, min(255.0, c))) for c in (r, g, b))


def _light_view(t: Thing) -> dict:
    raw = t.data.get("raw") or {}
    on = bool((raw.get("on") or {}).get("on"))
    ct = raw.get("color_temperature") or {}
    xy = (raw.get("color") or {}).get("xy") or {}
    mode, tint = "", ""
    if ct.get("mirek_valid") and ct.get("mirek"):
        mode, tint = "white", mirek_to_hex(ct["mirek"])
    elif raw.get("color") and xy.get("x") is not None:
        mode, tint = "colour", xy_to_hex(float(xy["x"]), float(xy["y"]))
    schema = ct.get("mirek_schema") or {}
    return {"id": t.id, "name": t.name, "on": on,
            "brightness": (raw.get("dimming") or {}).get("brightness") if raw.get("dimming") else None,
            "dims": bool(raw.get("dimming")), "colour": bool(raw.get("color")),
            "white": bool(raw.get("color_temperature")), "mode": mode, "tint": tint,
            "mirek": ct.get("mirek") if mode == "white" else None,
            "mirek_min": schema.get("mirek_minimum"), "mirek_max": schema.get("mirek_maximum")}


def _group_view(g: Thing, lights: dict, scenes: list[Thing]) -> dict:
    members = [_light_view(lights[i]) for i in g.data["lights"] if i in lights]
    lo = [m["mirek_min"] for m in members if m["mirek_min"]]
    hi = [m["mirek_max"] for m in members if m["mirek_max"]]
    lit = [m for m in members if m["on"]]
    return {"id": g.id, "kind": g.kind, "name": g.name, "on": bool(g.data["on"]),
            "brightness": g.data.get("brightness"), "lights": members,
            "scenes": [{"id": s.id, "name": s.name, "active": bool(s.data["active"])} for s in scenes],
            "colour": any(m["colour"] for m in members), "white": any(m["white"] for m in members),
            "dims": any(m["dims"] for m in members),
            "mirek_min": max(lo) if lo else None, "mirek_max": min(hi) if hi else None,
            "tints": [m["tint"] for m in lit if m["tint"]][:3]}


def home_view(home: Home) -> dict:
    """The home as the Home page draws it: rooms, then zones, then lights in no room, each with
    its real state, its scenes and its lights. Never a token or the key."""
    lights = {t.id: t for t in home.lights}
    scenes_of: dict[str, list[Thing]] = {}
    for s in home.scenes:
        scenes_of.setdefault(s.data["group"], []).append(s)
    placed = {i for r in home.rooms for i in r.data["lights"]}
    return {"rooms": [_group_view(g, lights, scenes_of.get(g.id, [])) for g in home.rooms],
            "zones": [_group_view(g, lights, scenes_of.get(g.id, [])) for g in home.zones],
            "loose": [_light_view(t) for t in home.lights if t.id not in placed],
            "everything": bool(home.everything or home.rooms)}


def _usable(who):
    """This person's connection, or why the page cannot show their lights."""
    conn = connection(who.user_id, who.org_id)
    if conn is None or not conn.access_sealed:
        raise NotSetUp("Philips Hue is not connected.")
    if conn.lapsed_at:
        raise Lapsed(lapsed_line(conn.lapsed_said))
    if not conn.key_sealed:
        raise NotSetUp("Philips Hue is not linked to the bridge yet.")
    return conn


def page_home(who) -> dict:
    """The Home page's read of the whole home, the 429 not waited out (`Limited`)."""
    hue = Hue(_usable(who), wait_out=False)
    home = read_home(hue)
    _SHAPES[hue.conn.id] = (time.monotonic(), home)
    return {"bridge": hue.conn.bridge_name, **home_view(home)}


def _shape(hue: Hue) -> Home:
    kept = _SHAPES.get(hue.conn.id)
    if kept and time.monotonic() - kept[0] < SHAPE_FOR:
        return kept[1]
    home = read_home(hue)
    _SHAPES[hue.conn.id] = (time.monotonic(), home)
    return home


def page_change(who, args: dict) -> str:
    """One press on the Home page: `{"kind": "room"|"zone"|"light", "id", "on"?, "brightness"?,
    "colour"? (#rrggbb), "kelvin"?}`, `{"scene": id}` or `{"all_off": true}`. What changed."""
    hue = Hue(_usable(who))
    home = _shape(hue)
    if args.get("all_off"):
        return all_off(hue, home)
    if args.get("scene"):
        sid = str(args["scene"])
        found = next((s for s in home.scenes if s.id == sid), None) if _RID.match(sid) else None
        if found is None:
            raise Refused("That scene is not on the bridge any more.")
        hue.clip("PUT", f"/scene/{found.id}", {"recall": {"action": "active"}})
        return f"{found.name} is on in {found.data['room'] or 'its room'}."
    kind, rid = str(args.get("kind") or ""), str(args.get("id") or "")
    pool = {"room": home.rooms, "zone": home.zones, "light": home.lights}.get(kind)
    thing = next((t for t in pool if t.id == rid), None) if pool is not None and _RID.match(rid) else None
    if thing is None:
        raise Refused("That is not on the bridge any more.")
    colour = str(args.get("colour") or "")
    if colour and not _HEX.match(colour.lower()):
        raise Refused("A colour is a hex code such as #ff8800.")
    on = args.get("on")
    said = change(hue, home, thing, on=on if isinstance(on, bool) else None,
                  brightness=args.get("brightness"), colour=colour, kelvin=args.get("kelvin"))
    if not said.startswith(thing.name + ":"):
        # `change` says what it could not do as a sentence of its own.
        raise Refused(said)
    return said
