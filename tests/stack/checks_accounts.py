"""CONTAINERS.md: the accounts the owner connects, each through its stand-in.

Nobody's real Google, Apple ID, Slack, Hue, Dreame, Cloudflare, Stripe or meeting library is
reached from the stack test: each is a stand-in (tests/stack/standins.py), reached by the core
as `standins` and, for the two sign-in pages a browser is sent to, Google's and Hue's, at the
ports the test publishes. The owner's part is done as the owner does it: Settings in a real
Chromium, signed in, where a page has to be pressed (Google's and Hue's consent, Apple's form),
and otherwise the API the Settings page posts to, with its own cookie and CSRF token. Then the
tools are called through the stand-in model, and the stand-ins say what reached them.

A webhook is what an outside service posts to a Rouh's public address, which a Rouh in the
containers is given by rouh.land's relay: here it is posted to the published port, as the relay
would hand it on.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import shlex
import time
import urllib.request

from smoke import Failed, Stack, check, expect

from checks_tools import fine, post, signed_in, wait_until

CARDDAV, APIFY, VOYAGE, STRIPE, CLOUDFLARE, SLACK = 9004, 9006, 9007, 9008, 9009, 9010
HUE, DREAME, VOICE, GOOGLE, MEETINGS = 9011, 9012, 9013, 9015, 9016

#: What each stand-in takes (rouh/testing/fake_*.py).
GOOGLE_CLIENT = ("stack-test-client.apps.googleusercontent.com", "stack-test-client-secret")
APPLE = ("alex@example.com", "wxyz-abcd-efgh-ijkl")
SLACK_TOKENS = {"bot": "xoxb-1000-stand-in-bot-token-aaaa", "user": "xoxp-1000-stand-in-owner-reads-cccc",
                "app": "xapp-1-A0ROUH-1000-stand-in-app-eeee"}
HUE_APP = {"client_id": "rouhhuestandinclient", "client_secret": "stand-in-hue-secret-7f3a",
           "app_id": "rouh-stand-in"}
DREAME_ACCOUNT = ("alex@example.com", "stand-in-dreame-password-41")
CLOUDFLARE_ZONE = ("example.com", "0f1e2d3c4b5a69788796a5b4c3d2e1f0",
                   "cfstand-first-zone-everything-0000000000000aaaa")
STRIPE_KEY = "rk_test_stacktest0not0a0real0one"
MEETING_SECRET = "stack-test-meeting-hook-secret"


# --- Google -------------------------------------------------------------------------------------

_GOOGLE: dict = {}


def google(s: Stack) -> dict:
    """Connect Google once, as an administrator and then the person do it: the organisation's
    client typed into Settings, Connect Google pressed, Allow pressed on the consent page."""
    if _GOOGLE:
        if _GOOGLE.get("error"):
            raise Failed(_GOOGLE["error"])
        return _GOOGLE
    try:
        with signed_in(s) as pg:
            pg.goto(s.url + "/settings/email")
            pg.wait_for_selector("#googleClientId", state="visible", timeout=60000)
            pg.fill("#googleClientId", GOOGLE_CLIENT[0])
            pg.fill("#googleClientSecret", GOOGLE_CLIENT[1])
            # The save answered before Connect is pressed: a Connect pressed while it is still on its
            # way starts the consent for no client, which is what made this flaky.
            with pg.expect_response(lambda r: "/api/settings/google/client" in r.url and r.request.method == "POST",
                                    timeout=30000):
                pg.click("#googleSaveClient")
            pg.wait_for_selector("text=Your organisation's Google app is saved", timeout=30000)
            pg.wait_for_selector("#googleConnect:not([disabled])", state="visible", timeout=30000)
            pg.click("#googleConnect")
            pg.wait_for_selector("#allow", timeout=30000)
            pg.click("#allow")
            pg.wait_for_url(re.compile("^" + re.escape(s.url)), timeout=60000)
            pg.wait_for_selector("#googleAccount", state="visible", timeout=60000)
            pg.screenshot(path=str(s.out / "google-connected.png"))
            _GOOGLE["account"] = pg.inner_text("#googleAccount")
        code, body, _ = s.get("/api/settings/google")
        expect(code == 200 and '"connection"' in body, f"/api/settings/google answered {code}: {body[:300]}")
        _GOOGLE["settings"] = json.loads(body)
        expect((_GOOGLE["settings"].get("connection") or {}), f"Google is not connected: {body[:400]}")
    except Exception as e:  # noqa: BLE001 - every check that needs Google says the same
        _GOOGLE["error"] = f"connecting Google: {e}"
        raise Failed(_GOOGLE["error"]) from None
    return _GOOGLE


@check("google.connect")
def google_connect(s: Stack) -> None:
    got = google(s)
    expect("@" in got.get("account", ""), f"Settings shows no Google account: {got}")
    seen = s.standin(GOOGLE, "/_seen")
    expect(seen.get("consent"), "the stand-in's consent page was never asked")


@check("google.mail")
def google_mail(s: Stack) -> None:
    """The inbox read and a letter sent, through the stand-in's Gmail."""
    google(s)
    got = fine("read_recent_mail", s.tool("read_recent_mail", {"limit": 5}))
    expect("Launch lighting plan" in got, f"read_recent_mail did not read the stand-in's inbox: {got[:400]}")
    got = fine("send_mail", s.tool("send_mail", {"to": "sam@example.test", "subject": "Hello from the stack test",
                                                 "body": "Sent from the containers."}))
    sent = s.standin(GOOGLE, "/_seen").get("sent") or []
    expect(any(m.get("subject") == "Hello from the stack test" for m in sent),
           f"the letter did not reach the stand-in's Gmail: {got[:400]}")


@check("google.calendar")
def google_calendar(s: Stack) -> None:
    google(s)
    got = fine("list_calendar_events", s.tool("list_calendar_events", {}))
    expect("calendar" in got.lower() or "event" in got.lower(), f"list_calendar_events: {got[:400]}")
    tomorrow = time.strftime("%Y-%m-%dT10:00", time.localtime(time.time() + 86400))
    text, _ = s.say("Put it in my calendar. TOOL create_calendar_event "
                    + json.dumps({"title": "Stack test meeting", "start": tomorrow, "minutes": 30}))
    expect("Traceback" not in text, text[:400])
    events = s.standin(GOOGLE, "/_seen").get("events")
    expect("Stack test meeting" in json.dumps(events),
           f"the event did not reach the stand-in's calendar: {text[:400]}")


@check("google.drive")
def google_drive(s: Stack) -> None:
    google(s)
    got = fine("search_drive", s.tool("search_drive", {"text": "Homepage"}))
    expect("homepage copy" in got.lower(), f"search_drive did not find the stand-in's document: {got[:400]}")
    got = fine("read_doc", s.tool("read_doc", {"document": "Homepage copy"}))
    expect("Traceback" not in got and len(got) > 80, f"read_doc: {got[:400]}")


# --- iCloud contacts -----------------------------------------------------------------------------

@check("contacts.icloud")
def contacts_icloud(s: Stack) -> None:
    """Settings, Apple: the Apple ID and an app-specific password typed in and checked with
    iCloud's stand-in; then a contact found."""
    with signed_in(s) as pg:
        pg.goto(s.url + "/settings/apple")
        pg.wait_for_selector("#appleId", state="visible", timeout=60000)
        pg.fill("#appleId", APPLE[0])
        pg.fill("#applePassword", APPLE[1])
        pg.click("#appleConnect")
        pg.wait_for_selector("#appleState", state="visible", timeout=60000)
        pg.screenshot(path=str(s.out / "apple-connected.png"))
    got = fine("search_contacts", s.tool("search_contacts", {"query": "a", "refresh_first": True}))
    expect("not connected" not in got.lower(), f"search_contacts: {got[:400]}")


# --- new mail, and Gmail's push ------------------------------------------------------------------

TOPIC = "projects/rouh-stand-in/topics/gmail-alerts"
_ALERTS: dict = {}


def mail_alerts_on(s: Stack) -> dict:
    """New mail turned on as the Settings card does it: the organisation's Pub/Sub topic (made
    in the stand-in's console, Gmail allowed to publish to it), then On for the owner's inbox,
    which asks Gmail to watch it."""
    if _ALERTS:
        return _ALERTS
    google(s)
    _standin_post(s, GOOGLE, "/_pubsub", {"topic": TOPIC, "publisher": True, "push": ""})
    code, said = post(s, "/api/settings/mail-alerts/topic", {"topic": TOPIC})
    expect(code == 200, f"the Pub/Sub topic was refused: {code} {said}")
    code, said = post(s, "/api/settings/mail-alerts/on", {})
    expect(code == 200, f"New mail could not be turned on: {code} {said}")
    address = re.search(r"https?://[^\"' ]+/hooks/gmail/[A-Za-z0-9_\-]+", json.dumps(said))
    expect(address, f"the card shows no push address: {json.dumps(said)[:400]}")
    _ALERTS["address"] = address.group(0)
    return _ALERTS


def _push(s: Stack, path: str) -> int:
    """Pub/Sub's push of Gmail's note, as it reaches the public address."""
    history = s.standin(GOOGLE, "/_seen").get("history_id")
    data = base64.b64encode(json.dumps({"emailAddress": "alex.morgan@example.com",
                                        "historyId": history}).encode()).decode()
    body = json.dumps({"message": {"data": data, "messageId": str(history), "message_id": str(history)},
                       "subscription": TOPIC.replace("/topics/", "/subscriptions/") + "-push"}).encode()
    req = urllib.request.Request(s.url + path, data=body, method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


def _in_the_log(s: Stack, subject: str) -> bool:
    code, body, _ = s.get("/settings/mail-alerts/log")
    return code == 200 and subject in body


@check("mail.push")
def mail_push(s: Stack) -> None:
    """New mail lands in the stand-in's inbox with its note lost on the way; then Pub/Sub's push
    is posted to the hook's public address (the published port, as the relay hands it on), and
    the message reaches Rouh. An address nobody holds is a 404."""
    on = mail_alerts_on(s)
    path = "/" + on["address"].split("://", 1)[1].split("/", 1)[1]
    _standin_post(s, GOOGLE, "/_deliver", {"from": "Sam Example <sam@example.test>",
                                           "subject": "Stack test pushed mail", "text": "Pushed to Rouh.",
                                           "quiet": True})
    expect(_push(s, "/hooks/gmail/not-a-real-token") == 404, "a push to an address nobody holds was taken")
    got = _push(s, path)
    expect(got in (200, 202, 204), f"the push was answered {got}")
    wait_until(lambda: _in_the_log(s, "Stack test pushed mail"), "the pushed mail never reached Rouh's log", 120)


@check("mail.alerts")
def mail_alerts(s: Stack) -> None:
    """New mail turned on in Settings makes Gmail's watch on the inbox, and a new message is
    read and handled by Rouh, on its log."""
    mail_alerts_on(s)
    watch = s.standin(GOOGLE, "/_seen").get("watch") or {}
    expect(watch.get("topic") == TOPIC, f"Gmail was not asked to watch the inbox: {watch}")
    mail_push(s)


# --- the voice -------------------------------------------------------------------------------------

@check("voice.speak")
def voice_speak(s: Stack) -> None:
    """Spoken replies on, as the page's speaker button does it; an answer is spoken through the
    stand-in for ElevenLabs and its audio reaches the page."""
    s.socket()
    s.ws.send(json.dumps({"type": "set_mode", "voice_reply": True}))
    s.wait_for(lambda m: m.get("type") == "mode", 30)
    s.ws.send(json.dumps({"type": "text", "text": "Say something for the stack test"}))
    frames, started, end = 0, False, time.time() + 120
    try:
        while time.time() < end:
            try:
                raw = s.ws.recv(timeout=max(0.1, end - time.time()))
            except TimeoutError:
                break
            if isinstance(raw, bytes):
                frames += 1
                continue
            m = json.loads(raw)
            started = started or m.get("type") == "audio_start"
            if m.get("type") == "audio_end" or (m.get("type") == "error" and m.get("fatal") is not False):
                break
    finally:
        s.ws.send(json.dumps({"type": "set_mode", "voice_reply": False}))
        s.wait_for(lambda m: m.get("type") == "mode", 30)
        s.ws.close()
        s.ws = None
    expect(started and frames, f"no spoken audio reached the page (audio_start {started}, {frames} frames)")
    r = s.run("standins", "cat /tmp/standins/spoken/*.json 2>/dev/null")
    expect("Say something for the stack test" in r.stdout, f"the stand-in for ElevenLabs was not asked to say it: {r.stdout[-300:]}")


# --- Slack, Hue, the robot vacuum, Cloudflare -----------------------------------------------------

@check("slack")
def slack(s: Stack) -> None:
    """Settings, Slack: Rouh's app's three tokens, checked with Slack's stand-in and sealed; then
    Rouh listening on Slack's Socket Mode and the workspace's conversations listed."""
    code, said = post(s, "/api/settings/slack/tokens", SLACK_TOKENS)
    expect(code == 200, f"Settings, Slack refused the tokens: {code} {said}")
    got = wait_until(lambda: (lambda t: "" if "sees no conversations" in t or "not listening" in t else t)(
        s.tool("slack_channels", {})), "Rouh never listed Slack's conversations", 90)
    expect("not connected" not in fine("slack_channels", got).lower(), f"slack_channels: {got[:400]}")
    expect(s.standin(SLACK, "/_sockets"), "Rouh never opened Slack's Socket Mode")


def _standin_post(s: Stack, port: int, path: str, body: dict | None = None) -> str:
    """A stand-in's own control, from inside the stack (it answers on the standins network)."""
    r = s.run("core", "python -c " + shlex.quote(
        "import json, sys, urllib.request\n"
        f"req = urllib.request.Request('http://standins:{port}{path}', data=json.dumps({body or {}!r}).encode(),"
        " headers={'content-type': 'application/json'}, method='POST')\n"
        "sys.stdout.write(urllib.request.urlopen(req, timeout=10).read().decode())\n"))
    expect(r.returncode == 0, f"the stand-in on {port} did not take {path}: {r.stderr[-300:]}")
    return r.stdout


@check("hue")
def hue(s: Stack) -> None:
    """Settings, Hue: the organisation's Hue app, then Connect, Allow on Hue's sign-in page in a
    real Chromium, and the bridge's link button; then the lights listed."""
    code, said = post(s, "/api/settings/hue/app", HUE_APP)
    expect(code == 200, f"Settings, Hue refused the app: {code} {said}")
    _standin_post(s, HUE, "/_press_button")
    with signed_in(s) as pg:
        pg.goto(s.url + "/auth/hue/start")
        pg.wait_for_selector("button[value=allow]", timeout=30000)
        pg.click("button[value=allow]")
        pg.wait_for_url(re.compile("^" + re.escape(s.url)), timeout=60000)
        pg.wait_for_load_state()
        pg.screenshot(path=str(s.out / "hue-connected.png"))
    code, body, _ = s.get("/api/settings/hue")
    if '"linked": true' not in body.replace(" ", "").replace(":true", ": true"):
        post(s, "/api/settings/hue/link", {})
    got = fine("hue", s.tool("hue", {"action": "list"}))
    expect("not connected" not in got.lower() and "light" in got.lower(), f"hue list: {got[:400]}")


@check("vacuum")
def vacuum(s: Stack) -> None:
    """Settings, Dreame: the Dreamehome account typed in and checked with the cloud's stand-in."""
    code, said = post(s, "/api/settings/dreame/connect", {"account": "dreamehome", "email": DREAME_ACCOUNT[0],
                                                          "password": DREAME_ACCOUNT[1], "region": "auto"})
    expect(code == 200, f"Settings, Dreame refused the account: {code} {said}")
    got = fine("vacuum", wait_until(lambda: (lambda t: "" if "not connected" in t.lower() else t)(
        s.tool("vacuum", {"action": "status"})), "the robot never answered", 60))
    expect("batter" in got.lower(), f"vacuum status: {got[:400]}")


@check("cloudflare")
def cloudflare(s: Stack) -> None:
    """Settings, Cloudflare: a zone and its token, checked with Cloudflare's stand-in and sealed;
    then the zone's DNS records read with it, and its Email Routing, with the MX records in its way;
    its Origin CA certificates listed, and one named record deleted (a record not there refused)."""
    zone, account, token = CLOUDFLARE_ZONE
    post(s, "/api/settings/cloudflare/zone", {"zone": zone, "account_id": account})
    code, said = post(s, "/api/settings/cloudflare/token", {"zone": zone, "token": token, "account_id": account})
    expect(code == 200, f"Settings, Cloudflare refused the token: {code} {said}")
    got = fine("cloudflare", s.tool("cloudflare", {"action": "records", "zone": zone}))
    expect(zone in got and "record" in got.lower(), f"cloudflare records: {got[:400]}")
    # Not through fine(): its "is off" guard is for a tool that is not set up, and the stand-in's
    # zone rightly starts with Email Routing off, so it failed every Tests on main from 6996939e.
    got = s.tool("cloudflare", {"action": "email_routing_status", "zone": zone})
    expect(not any(w in got for w in ("Traceback", "not available", "not set up", "isn't set up")), f"cloudflare email_routing_status: {got[:600]}")
    expect("Email Routing is" in got and "would be removed" in got, f"cloudflare email_routing_status: {got[:600]}")
    got = fine("cloudflare", s.tool("cloudflare", {"action": "origin_certificates", "zone": zone}))
    expect(zone in got and "Origin CA certificate" in got, f"cloudflare origin_certificates: {got[:400]}")
    gone = {"type": "TXT", "name": f"_dmarc.{zone}", "content": "v=DMARC1; p=none; rua=mailto:dmarc@example.com"}
    got = s.tool("cloudflare", {"action": "dns_delete", "zone": zone, "record": {**gone, "content": "v=DMARC1; p=reject"}})
    expect("nothing was deleted" in got, f"cloudflare dns_delete of a record that is not there: {got[:400]}")
    got = fine("cloudflare", s.tool("cloudflare", {"action": "dns_delete", "zone": zone, "record": gone}))
    expect(f"deleted TXT _dmarc.{zone}" in got and "make it again" in got, f"cloudflare dns_delete: {got[:400]}")


# --- Stripe ------------------------------------------------------------------------------------------

_STRIPE: dict = {}


@check("stripe")
def stripe(s: Stack) -> None:
    """Payments: the restricted key typed in and checked with Stripe's stand-in; then its state."""
    if not _STRIPE:
        code, said = post(s, "/api/payments/stripe", {"key": STRIPE_KEY})
        expect(code == 200, f"Payments refused the Stripe key: {code} {said}")
        _STRIPE["key"] = True
    got = fine("stripe", s.tool("stripe", {"action": "status"}))
    expect("no key" not in got.lower(), f"stripe status: {got[:400]}")


def _stripe_sign(secret: str, payload: bytes) -> str:
    at = int(time.time())
    return f"t={at},v1=" + hmac.new(secret.encode(), f"{at}.".encode() + payload, hashlib.sha256).hexdigest()


@check("stripe.webhook")
def stripe_webhook(s: Stack) -> None:
    """Payments makes its webhook with Stripe's stand-in, which keeps the signing secret. An event
    signed with it and posted to the hook's public address (the published port, as the relay
    hands it on) is taken and the owner told on the phone; a forged one is refused."""
    stripe(s)
    code, said = post(s, "/api/payments/webhook", {})
    expect(code == 200, f"Payments could not make Stripe's webhook: {code} {said}")
    hooks = (s.standin(STRIPE, "/_calls") or {}).get("hooks") or []
    expect(hooks, "Stripe's stand-in was never asked for a webhook")
    hook = hooks[-1]
    path = "/" + hook["url"].split("://", 1)[1].split("/", 1)[1]
    expect(path.startswith("/hooks/stripe/"), f"the webhook's address is not Rouh's hook: {hook['url']}")
    event = {"id": "evt_stacktest", "object": "event", "type": "checkout.session.completed",
             "data": {"object": {"id": "cs_stacktest", "object": "checkout.session", "payment_intent": "pi_stacktest",
                                 "amount_total": 4200, "currency": "eur", "payment_status": "paid", "metadata": {},
                                 "customer_details": {"email": "buyer@example.test"}}}}
    payload = json.dumps(event).encode()

    def deliver(secret: str) -> int:
        req = urllib.request.Request(s.url + path, data=payload, method="POST", headers={
            "Content-Type": "application/json", "Stripe-Signature": _stripe_sign(secret, payload)})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return r.status
        except urllib.error.HTTPError as e:
            return e.code

    expect(deliver("whsec_forged") == 400, "a forged Stripe event was not refused")
    got = deliver(hook["secret"])
    expect(got == 200, f"the signed Stripe event was answered {got}")
    from checks_messages import _wait_phone

    _wait_phone(s, "Money came in")


# --- LinkedIn, Synapse, the meeting library -----------------------------------------------------------

@check("linkedin")
def linkedin(s: Stack) -> None:
    got = fine("linkedin_search", s.tool("linkedin_search", {"first_name": "Jane", "last_name": "Doe"}))
    expect("linkedin.com/in/" in got, f"linkedin_search: {got[:400]}")
    expect(s.standin(APIFY, "/_calls"), "the stand-in for Apify was never called")


@check("synapse")
def synapse(s: Stack) -> None:
    """A note kept in Synapse Master with its vectors (Voyage's stand-in), then found by meaning."""
    master = "Synapse Master"
    got = fine("synapse_add", s.tool("synapse_add", {"text": "The stack test keeps the blue door key under the mat",
                                                     "dataset": master}))
    expect("stored" in got.lower(), f"synapse_add: {got[:400]}")
    got = wait_until(lambda: (lambda t: t if "blue door" in t.lower() else "")(
        s.tool("synapse_find", {"query": "where is the key to the blue door", "dataset": master})),
        "synapse_find never found it", 90)
    fine("synapse_find", got)
    vectors = s.standin(VOYAGE, "/_state")
    expect(vectors.get("texts") and not vectors.get("refused"), f"Voyage's stand-in made no vectors: {vectors}")


MEETING = {"id": "stack-1", "title": "Stack test planning", "started_at": "2026-10-28T09:00:00Z",
           "ended_at": "2026-10-28T09:30:00Z", "language": "en",
           "summary": "The stack test planned three pilots for December.",
           "participants": [{"name": "Alex Morgan", "email": "alex@example.com", "attended": "took_part"}],
           "speakers": [{"label": "A", "name": "Alex Morgan", "email": "alex@example.com", "confirmed": True}],
           "segments": [{"segment_id": "s1", "speaker": "A", "start_ms": 0, "end_ms": 4000,
                         "text": "We plan three pilots for December."}], "webhook": False}


@check("install.meeting-library")
def install_meeting_library(s: Stack) -> None:
    """The core reads the library's address, key and webhook secret from the settings file."""
    said = s.manage("from rouh.synapse.sources import meetings; import json; "
                    "c = meetings.settings(); print(json.dumps({'url': c['url'], 'missing': c['missing']}))")
    got = json.loads(said.strip().splitlines()[-1])
    expect(not got["missing"] and got["url"].startswith("http"), f"the meeting library's settings: {got}")


def _meeting_hook(s: Stack, body: bytes, secret: str) -> int:
    stamp = str(int(time.time()))
    sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    req = urllib.request.Request(s.url + "/api/hooks/meeting-library", data=body, method="POST", headers={
        "Content-Type": "application/json", "X-Library-Signature": "sha256=" + sig,
        "X-Library-Timestamp": stamp, "X-Library-Event": "meeting.changed"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


_MEETING: dict = {}


def meeting_heard(s: Stack) -> dict:
    """A meeting made in the library's stand-in, and its signed webhook posted to Rouh's public
    address (the published port, as the relay hands it on), forged first and then real."""
    if not _MEETING:
        made = json.loads(_standin_post(s, MEETINGS, "/_meeting", MEETING))
        body = json.dumps({"event": "meeting.changed", "meeting_id": made["meeting"]["id"],
                           "revision": made["meeting"]["revision"], "state": made["meeting"]["state"],
                           "sent_at": int(time.time())}).encode()
        _MEETING["forged"] = _meeting_hook(s, body, "not-the-secret")
        _MEETING["status"] = _meeting_hook(s, body, MEETING_SECRET)
    return _MEETING


@check("meetings.webhook")
def meetings_webhook(s: Stack) -> None:
    got = meeting_heard(s)
    expect(got["forged"] == 401, f"a forged webhook was answered {got['forged']}")
    expect(got["status"] == 200, f"the signed webhook was answered {got['status']}")


@check("meetings")
def meetings(s: Stack) -> None:
    """The meeting the webhook named, read from the library into Synapse, found by meeting_search."""
    meeting_heard(s)
    got = wait_until(lambda: (lambda t: t if "stack test planning" in t.lower() else "")(
        s.tool("meeting_search", {"query": "pilots for December"})), "meeting_search never found the meeting", 240)
    fine("meeting_search", got)
