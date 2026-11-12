"""The keys and settings of the services this Rouh uses, typed into Settings, never into a chat or a file.

Petar, 12 November 2026, when a new Mac Rouh told its owner to edit ``stack.env`` for Telegram:
"this should be done for all such integrations and connections. we should be able to save it in
there. in the settings. just like the cloudflare setup, you paste the code there, not in the chat
and not in the file on the computer directly".

So every service that needed a line in the settings file (``stack.env`` on a Mac, ``.env`` on a
server, `deploy/stack/settings.env.example`) has its fields in Anatomy, Connections, Keys
(`rouh/web/service_keys.py`, `keyspage.js`), built the way Cloudflare's page is (`rouh/cloudflare.py`):

- **Typed there, and nowhere else.** A value leaves the page in one POST, straight to the core.
  It is never in a chat, a model's prompt, a tool result, a log line, an event or an answer: the
  page is told whether a secret is set, its last four and when, and is shown back only what is no
  secret (a chat id, an address, a voice).
- **Checked first, where the service has a way to ask.** Each service asks its own API whether the
  values work (`Service.check`) before anything is kept; a refusal says what is wrong in words and
  keeps nothing. A secret left empty when the others are changed keeps the one already kept.
- **Sealed, and the organisation's.** One row per value, `ServiceKey`, sealed with this instance's
  key, keyed by the organisation, which is this installation's own (`DEFAULT_ORG_ID`): these are
  the installation's services, the way its settings file was, and only that organisation's
  administrators change them.
- **Taken up at once, with no Stop and Start.** Every place that uses one of these reads it when
  it calls, from the process's settings (`config`) or its environment, so `apply` puts what is
  kept there - a kept value wins over the settings file's, and a value taken away gives the
  settings file's back - on every save, at start (`runtime.startup`) and in a command's own
  process (`manage.py`). A service that holds something built from its key gets it again
  (`Service.after`).

The settings file still works as it always did, beneath what is kept here: an installer may
keep writing it. Nothing in this module gives the worker, a job or the model a way to read or
write any of it.
"""
from __future__ import annotations

import asyncio
import inspect
import logging
import os
import re
import subprocess
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

log = logging.getLogger("rouh.service_keys")

PAGE = "/anatomy/connections/keys"
#: The organisation whose values the installation uses.
HOLD_SECONDS = 30.0
TIMEOUT = 15.0


class Refused(ValueError):
    """Not saved, with why in words a person can read: never a value that was typed."""


@dataclass(frozen=True)
class Field:
    name: str                     # the settings file's own name for it
    label: str
    secret: bool = True
    required: bool = True
    placeholder: str = ""
    hint: str = ""
    config: str = ""              # the attribute of `config` that holds it, if any


@dataclass(frozen=True)
class Service:
    id: str
    name: str
    what: str                     # what Rouh does with it, one line
    steps: tuple = ()             # where to get it, step by step
    fields: tuple = ()
    check: Callable | None = None  # (values) -> (values, said); raises Refused
    after: Callable | None = None  # () -> None: rebuild what was made from the old values
    page: str = ""                # a page of its own that sets it instead (Telegram)
    restart: str = ""             # what still waits for a restart, if anything
    links: tuple = field(default_factory=tuple)


# --- the checks: each asks the service itself, and says nothing of what was typed -------------

def _scrub(text: str, values: dict) -> str:
    for v in values.values():
        if v and len(v) >= 6:
            text = text.replace(v, "…")
    return text


def _http(method: str, url: str, **kw):
    import httpx

    try:
        return httpx.request(method, url, timeout=TIMEOUT, **kw)
    except httpx.HTTPError as exc:
        # The kind only: httpx puts the address, which may hold a key, in its words.
        raise Refused(f"The service could not be reached from this Rouh ({type(exc).__name__}). "
                      "Nothing was saved; try again in a moment.") from None


async def _check_telegram(v: dict) -> tuple[dict, str]:
    from . import telegram_bot
    from .config import config

    try:
        username, chat = await telegram_bot.check(v.get("ROUH_TELEGRAM_BOT_TOKEN", ""),
                                                  v.get("ROUH_TELEGRAM_CHAT_ID", ""), config.telegram_api_base)
    except telegram_bot.Refused as exc:
        raise Refused(str(exc)) from None
    return {**v, "ROUH_TELEGRAM_CHAT_ID": chat}, (f"@{username} wrote to chat {chat}" if username
                                                    else f"the bot wrote to chat {chat}")


def _after_telegram() -> None:
    from . import telegram_bot

    telegram_bot.forget_held()


def _check_voice(v: dict) -> tuple[dict, str]:
    from . import speech

    r = _http("GET", speech.API + "/voices", headers={"xi-api-key": v["ELEVENLABS_API_KEY"]})
    if r.status_code in (401, 403):
        raise Refused("ElevenLabs did not accept that key. Copy it again from elevenlabs.io, "
                      "Developers, API Keys.")
    if r.status_code >= 400:
        raise Refused(f"ElevenLabs answered {r.status_code}. Nothing was saved.")
    voices = {str(x.get("voice_id")): str(x.get("name") or "") for x in (r.json().get("voices") or [])}
    want = v.get("ROUH_VOICE_ID", "")
    if want and voices and want not in voices:
        some = ", ".join(f"{n} ({i})" for i, n in list(voices.items())[:4])
        raise Refused(f"That voice id is not one of this account's voices. Some it has: {some}.")
    return v, f"the key works{', with the voice ' + voices[want] if want in voices else ''}"


def _check_voyage(v: dict) -> tuple[dict, str]:
    from .synapse import ai

    r = _http("POST", ai.voyage_url(v.get("VOYAGE_ENDPOINT", "")),
              headers={"Authorization": "Bearer " + v["VOYAGE_API_KEY"]},
              json={"input": ["check"], "model": ai.VOYAGE_MODELS[0], "input_type": "query",
                    "output_dimension": ai.EMBED_DIMS})
    if r.status_code in (401, 403):
        raise Refused("Voyage AI did not accept that key. Copy it again from dashboard.voyageai.com, API keys.")
    if r.status_code >= 400:
        raise Refused(f"Voyage AI answered {r.status_code}. Nothing was saved.")
    return v, "the key made a vector"


def _check_youtube(v: dict) -> tuple[dict, str]:
    from . import youtube

    # The key in Google's header, never in the address, which httpx writes to the log.
    r = _http("GET", youtube.YOUTUBE_API + "/videos", params={"part": "id", "id": "jNQXAC9IVRw"},
              headers={"X-goog-api-key": v["YOUTUBE_API_KEY"]})
    if r.status_code in (400, 401, 403):
        raise Refused("Google did not accept that key for the YouTube Data API. In console.cloud.google.com, "
                      "turn on YouTube Data API v3 for its project and copy the key again.")
    if r.status_code >= 400:
        raise Refused(f"YouTube answered {r.status_code}. Nothing was saved.")
    return v, "the key reads YouTube"


def _check_apify(v: dict) -> tuple[dict, str]:
    from .config import config

    r = _http("GET", (config.apify_url or "https://api.apify.com").rstrip("/") + "/v2/users/me",
              headers={"Authorization": "Bearer " + v["APIFY_API_TOKEN"]})
    if r.status_code in (401, 403):
        raise Refused("Apify did not accept that token. Copy it again from console.apify.com, Settings, "
                      "API & Integrations.")
    if r.status_code >= 400:
        raise Refused(f"Apify answered {r.status_code}. Nothing was saved.")
    who = str(((r.json() or {}).get("data") or {}).get("username") or "")
    return v, f"the token is {who}'s" if who else "the token works"


def _after_apify() -> None:
    try:
        from . import linkedin, runtime
        from .config import config
    except Exception:  # noqa: BLE001 - outside the server there is nothing to rebuild
        return
    tools = getattr(runtime, "tools", None)
    if tools is None:
        return
    token = config.apify_api_token
    tools.apify = linkedin.Apify(token, config.apify_url or linkedin.APIFY_URL) if token else None
    if tools.apify is not None:
        tools._linkedin_tools()        # a name already declared is left as it is


def _check_brevo(v: dict) -> tuple[dict, str]:
    from .config import config

    sender = v.get("ROUH_MAIL_FROM", "")
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", sender):
        raise Refused("Give the address Rouh's letters come from, such as rouh@example.com.")
    r = _http("GET", str(config.brevo_url or "https://api.brevo.com").rstrip("/") + "/v3/account",
              headers={"api-key": v["ROUH_BREVO_API_KEY"], "accept": "application/json"})
    if r.status_code in (401, 403):
        raise Refused("Brevo did not accept that key. Make one in app.brevo.com, Settings, SMTP & API, API keys.")
    if r.status_code >= 400:
        raise Refused(f"Brevo answered {r.status_code}. Nothing was saved.")
    return v, f"the key works; letters come from {sender}"


def _check_meetings(v: dict) -> tuple[dict, str]:
    url = re.sub(r"/api/v1/?$", "", v["MEETING_LIBRARY_URL"].strip().rstrip("/"))
    if not url.startswith("https://") and not url.startswith("http://127.0.0.1"):
        raise Refused("The library's address starts with https://.")
    # The change list: the one thing a library's service key may always read, as the sync does.
    r = _http("GET", url + "/api/v1/changes", params={"since": 0, "limit": 1},
              headers={"Authorization": "Bearer " + v["MEETING_LIBRARY_KEY"], "Accept": "application/json"})
    if r.status_code in (401, 403):
        raise Refused("The meeting library did not accept that key.")
    if r.status_code >= 400:
        raise Refused(f"The meeting library answered {r.status_code} at that address. Nothing was saved.")
    return {**v, "MEETING_LIBRARY_URL": url}, "the library answered with that key"


def _check_workspace(v: dict) -> tuple[dict, str]:
    from urllib.parse import quote, urlsplit, urlunsplit

    remote = v["ROUH_WORKSPACE_REMOTE"].strip()
    token = v.get("ROUH_WORKSPACE_REMOTE_TOKEN", "")
    if not remote.startswith("https://"):
        raise Refused("Give the repository's https address, such as https://github.com/you/workspace.git.")
    url = remote
    if token:
        parts = urlsplit(remote)
        url = urlunsplit(parts._replace(netloc=f"x-access-token:{quote(token, safe='')}@{parts.hostname}"))
    try:
        r = subprocess.run(["git", "ls-remote", "--heads", url], capture_output=True, text=True, timeout=30,
                           env={**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_ASKPASS": "true"})
    except (OSError, subprocess.TimeoutExpired):
        raise Refused("The repository could not be reached from this Rouh. Nothing was saved.") from None
    if r.returncode != 0 and re.search(r"(?i)could not resolve|failed to connect|connection refused|timed out",
                                       r.stderr or ""):
        raise Refused("The repository could not be reached from this Rouh. Check its address. Nothing was saved.")
    if r.returncode != 0:
        raise Refused("The repository did not let Rouh in with that token. It needs Contents: read and "
                      "write on that one repository.")
    return v, "the repository answered"


def _check_offsite(v: dict) -> tuple[dict, str]:
    from . import offsite

    if bool(v.get("ROUH_OFFSITE_RECIPIENT")) == bool(v.get("ROUH_OFFSITE_PASSPHRASE")):
        raise Refused("Give one of the two to lock the copies with: an age public key (age1...) or a "
                      "long passphrase. Nothing is sent unlocked.")
    recipient = v.get("ROUH_OFFSITE_RECIPIENT", "")
    if recipient and not recipient.startswith("age1"):
        raise Refused("An age public key starts with age1.")
    s = {"endpoint": v["ROUH_OFFSITE_ENDPOINT"], "bucket": v["ROUH_OFFSITE_BUCKET"],
         "key_id": v["ROUH_OFFSITE_KEY_ID"], "secret": v["ROUH_OFFSITE_SECRET"]}
    try:
        offsite.client(s).list_objects_v2(Bucket=s["bucket"], MaxKeys=1)
    except Exception as exc:  # noqa: BLE001 - its words, never the keys
        raise Refused("The bucket did not let Rouh in with those keys "
                      f"({type(exc).__name__}). They need Object Read & Write on that bucket.") from None
    return v, "the bucket answered"


SERVICES: tuple[Service, ...] = (
    Service("telegram", "Telegram bot", "The bot Rouh writes to your phone with, and you write to Rouh through.",
            fields=(Field("ROUH_TELEGRAM_BOT_TOKEN", "Bot token", placeholder="123456789:AAH..."),
                    Field("ROUH_TELEGRAM_CHAT_ID", "Chat id", secret=False, required=False,
                          placeholder="Found by itself")),
            check=_check_telegram, after=_after_telegram, page="/anatomy/connections/telegram"),
    Service("voice", "Voice (ElevenLabs)", "Rouh hears you and speaks its answers.",
            steps=("In elevenlabs.io, open Developers, API Keys, and make a key.",
                   "Paste it here. A voice id is optional: George is the voice without one."),
            fields=(Field("ELEVENLABS_API_KEY", "API key", placeholder="sk_...", config="elevenlabs_api_key"),
                    Field("ROUH_VOICE_ID", "Voice id", secret=False, required=False,
                          placeholder="JBFqnCBsd6RMkjVDRZzb", config="voice_id")),
            check=_check_voice),
    Service("voyage", "Search by meaning (Voyage AI)", "Synapse finds what you mean, not only your words.",
            steps=("In dashboard.voyageai.com, open API keys and make one.",),
            fields=(Field("VOYAGE_API_KEY", "API key", placeholder="pa-...", config="voyage_api_key"),
                    Field("VOYAGE_ENDPOINT", "Address, for a MongoDB Atlas key", secret=False, required=False,
                          placeholder="Voyage AI's own", config="voyage_endpoint")),
            check=_check_voyage),
    Service("youtube", "YouTube search", "Rouh searches YouTube and reads its videos.",
            steps=("In console.cloud.google.com, turn on YouTube Data API v3, then Credentials, Create "
                   "credentials, API key.",),
            fields=(Field("YOUTUBE_API_KEY", "API key", placeholder="AIza...", config="youtube_api_key"),),
            check=_check_youtube),
    Service("apify", "LinkedIn look-ups (Apify)", "Rouh looks people up on LinkedIn before you meet them.",
            steps=("In console.apify.com, open Settings, API & Integrations, and copy the personal API token.",),
            fields=(Field("APIFY_API_TOKEN", "API token", placeholder="apify_api_...", config="apify_api_token"),),
            check=_check_apify, after=_after_apify),
    Service("brevo", "Rouh's own letters (Brevo)", "Pages shared by email and password resets, sent from Rouh's address.",
            steps=("In app.brevo.com, open Settings, SMTP & API, API keys, and make one.",
                   "Add the address the letters come from as a sender there, then give it here."),
            fields=(Field("ROUH_BREVO_API_KEY", "API key", placeholder="xkeysib-..."),
                    Field("ROUH_MAIL_FROM", "Letters come from", secret=False, placeholder="rouh@example.com",
                          config="mail_from"),
                    Field("ROUH_MAIL_FROM_NAME", "Their name", secret=False, required=False, placeholder="Rouh",
                          config="mail_from_name")),
            check=_check_brevo),
    Service("meetings", "Meeting library", "Your meetings' transcripts and summaries, read into Synapse.",
            fields=(Field("MEETING_LIBRARY_URL", "Address", secret=False, placeholder="https://notes.example.com"),
                    Field("MEETING_LIBRARY_KEY", "Key", placeholder="ml_..."),
                    Field("MEETING_LIBRARY_WEBHOOK_SECRET", "Webhook secret", required=False)),
            check=_check_meetings),
    Service("workspace", "Your workspace's own repository", "Your tasks and pages kept in a private repository "
            "of yours as well, level both ways.",
            steps=("Make a private repository, and a fine-grained token with Contents: read and write on it alone.",),
            fields=(Field("ROUH_WORKSPACE_REMOTE", "Repository", secret=False,
                          placeholder="https://github.com/you/workspace.git"),
                    Field("ROUH_WORKSPACE_REMOTE_TOKEN", "Token", required=False, placeholder="github_pat_...")),
            check=_check_workspace),
    Service("offsite", "Weekly copy off this machine", "Once a week, an encrypted copy of everything, sent to "
            "Cloudflare R2 or any S3 bucket.",
            steps=("Make a bucket, and an API token for it with Object Read & Write, that bucket only.",
                   "Lock the copies with an age public key whose private half you keep elsewhere, or a long "
                   "passphrase you also keep elsewhere."),
            fields=(Field("ROUH_OFFSITE_ENDPOINT", "Endpoint", secret=False,
                          placeholder="https://<account>.r2.cloudflarestorage.com"),
                    Field("ROUH_OFFSITE_BUCKET", "Bucket", secret=False, placeholder="rouh-backups"),
                    Field("ROUH_OFFSITE_KEY_ID", "Access key id"),
                    Field("ROUH_OFFSITE_SECRET", "Secret access key"),
                    Field("ROUH_OFFSITE_RECIPIENT", "age public key", secret=False, required=False,
                          placeholder="age1..."),
                    Field("ROUH_OFFSITE_PASSPHRASE", "Or a passphrase", required=False)),
            check=_check_offsite),
)
BY_ID = {s.id: s for s in SERVICES}
NAMES = {f.name: (s, f) for s in SERVICES for f in s.fields}

#: The settings file's own values, as this process started with them, beneath what is kept here.
_FILE = {name: (os.environ.get(name) or "").strip() for name in NAMES}
_HELD: dict = {}
_LOCK = threading.Lock()


# --- the rows -------------------------------------------------------------------------------

def _org() -> str:
    from .tenancy import DEFAULT_ORG_ID

    return DEFAULT_ORG_ID


def _rows(fresh: bool = False) -> dict:
    """{name: (sealed, last4, saved_at)}, held briefly: `stored` is asked on every message sent."""
    now = time.monotonic()
    with _LOCK:
        held = _HELD.get("rows")
        if held and not fresh and now - held[0] < HOLD_SECONDS:
            return held[1]
    got: dict = {}
    try:
        from .models import ServiceKey

        for r in ServiceKey.objects.filter(org_id=_org()).values("name", "value_sealed", "last4", "saved_at"):
            got[r["name"]] = (r["value_sealed"], r["last4"], r["saved_at"])
    except Exception:                       # no database, or not yet migrated: the settings file's only
        log.debug("the service keys could not be read", exc_info=True)
        return {}
    with _LOCK:
        _HELD["rows"] = (now, got)
    return got


def stored(name: str) -> str:
    """The value kept in Settings for this name, or "" for none. For Rouh's own server code only:
    never into a prompt, a tool result, a log line or a message."""
    sealed = (_rows().get(name) or ("",))[0]
    if not sealed:
        return ""
    try:
        from .encryption import box

        return box().open_(sealed)
    except Exception:  # noqa: BLE001 - said without the value
        log.warning("the kept value of %s could not be opened with this Rouh's key", name)
        return ""


def value(name: str) -> str:
    """What this Rouh uses: the value kept in Settings, else the settings file's."""
    return stored(name) or _FILE.get(name, "")


def apply() -> None:
    """Every kept value into this process's settings and environment, and the settings file's back
    for one taken away. What each service reads when it calls, so nothing has to start again."""
    from .config import config

    from . import redaction

    with _LOCK:
        _HELD.pop("rows", None)
    redaction.hold([value(n) for n, (_s, f) in NAMES.items() if f.secret])
    for name, (_svc, f) in NAMES.items():
        v = value(name)
        if v:
            os.environ[name] = v
        else:
            os.environ.pop(name, None)
        if f.config:
            if v or f.required:
                setattr(config, f.config, v)
            else:
                # An optional one with nothing anywhere goes back to its built-in default.
                setattr(config, f.config, _DEFAULTS.get(f.config, v))


#: The built-in defaults of the optional settings, read once before anything is applied.
_DEFAULTS: dict = {}


def _remember_defaults() -> None:
    from .config import config

    for _s, f in NAMES.values():
        if f.config and f.config not in _DEFAULTS:
            _DEFAULTS[f.config] = getattr(config, f.config, "")


def _admin(who) -> None:
    from .tenancy import DEFAULT_ORG_ID

    if not getattr(who, "is_admin", False) or str(getattr(who, "org_id", "")) != DEFAULT_ORG_ID:
        raise Refused("Only an administrator of this Rouh's own organisation changes its keys.")


def _source(name: str) -> str:
    return "page" if _rows().get(name) else "settings_file" if _FILE.get(name) else ""


def _when(ts) -> str:
    if not ts:
        return ""
    from . import clock

    return clock.moment(ts).strftime("%-d %b %Y, %H:%M")


def _checks() -> dict:
    try:
        from .models import ServiceCheck

        return {r["service"]: r for r in ServiceCheck.objects.filter(org_id=_org()).values(
            "service", "checked_at", "ok", "said")}
    except Exception:  # noqa: BLE001
        return {}


def public(who) -> dict:
    """Everything the page shows. Never a secret: that it is set, its last four and when."""
    rows = _rows(fresh=True)
    checks = _checks()
    out = []
    for s in SERVICES:
        fields = []
        for f in s.fields:
            row = rows.get(f.name)
            src = _source(f.name)
            shown = {"name": f.name, "label": f.label, "secret": f.secret, "required": f.required,
                     "placeholder": f.placeholder, "hint": f.hint, "source": src, "set": bool(src),
                     "saved": _when(row[2]) if row else ""}
            if f.secret:
                shown["last4"] = row[1] if row else ""
            else:
                shown["value"] = value(f.name)
            fields.append(shown)
        c = checks.get(s.id) or {}
        out.append({"id": s.id, "name": s.name, "what": s.what, "steps": list(s.steps), "page": s.page,
                    "restart": s.restart, "fields": fields,
                    "set": all(x["set"] for x in fields if x["required"]),
                    "from_page": any(x["source"] == "page" for x in fields),
                    "check": {"at": _when(c.get("checked_at")), "ok": c.get("ok"), "said": c.get("said") or ""}
                    if c else None})
    return {"admin": bool(getattr(who, "is_admin", False)), "services": out}


def status_line() -> str:
    """What a tool may say of them: which are set and from where, never a value."""
    parts = []
    for s in SERVICES:
        req = [f for f in s.fields if f.required]
        if all(value(f.name) for f in req):
            parts.append(f"{s.name}: set" + (" in Settings" if any(_rows().get(f.name) for f in s.fields)
                                             else " in the settings file"))
        else:
            parts.append(f"{s.name}: not set")
    return ("; ".join(parts) + f". The owner sets each in Anatomy, Connections, Keys ({PAGE}); Telegram's bot "
            "also on Anatomy, Connections, Telegram, and the model keys (Anthropic, OpenAI, Google, xAI) in Anatomy, "
            "Behaviour, Models. Each is pasted there, checked and used at once, with nothing to restart: never in a "
            "chat, never in a box, never by editing stack.env or any other file. Never ask for a key in a message.")


# --- saving ---------------------------------------------------------------------------------

def _clean(f: Field, text) -> str:
    v = str(text or "").strip()
    return "".join(v.split()) if f.secret else v


async def _run(check: Callable, values: dict):
    if inspect.iscoroutinefunction(check):
        return await check(values)
    return await asyncio.to_thread(check, values)


def _record(service: str, ok: bool | None, said: str) -> None:
    from .models import ServiceCheck

    ServiceCheck.objects.update_or_create(org_id=_org(), service=service,
                                          defaults={"checked_at": time.time(), "ok": ok, "said": said[:300]})


async def save(who, service: str, typed: dict) -> dict:
    """Check a service's values with the service, then keep them sealed and take them up at once;
    or refuse, saying why, and keep nothing. A secret left empty keeps the one already kept."""
    _admin(who)
    s = BY_ID.get(str(service or ""))
    if s is None:
        raise Refused("There is no such service here.")
    typed = typed if isinstance(typed, dict) else {}
    values: dict = {}
    for f in s.fields:
        v = _clean(f, typed.get(f.name))
        if not v and f.secret:
            v = await asyncio.to_thread(value, f.name)
        values[f.name] = v
    missing = [f.label for f in s.fields if f.required and not values[f.name]]
    if missing:
        raise Refused(f"Give the {' and the '.join(missing).lower()} first. Nothing was saved.")
    said = ""
    if s.check is not None:
        try:
            values, said = await _run(s.check, values)
        except Refused as exc:
            # Nothing is kept, the last check included: what is used now has not changed.
            log.info("the %s settings were refused by the service's check", s.id)
            raise Refused(_scrub(str(exc), values)) from None
        except Exception as exc:  # noqa: BLE001 - never says what was typed
            log.warning("the %s check failed (%s)", s.id, type(exc).__name__)
            raise Refused("The check could not be made. Nothing was saved; try again in a moment.") from None
    await asyncio.to_thread(_keep, who, s, values, said)
    values.clear()
    typed.clear()
    return {**(await asyncio.to_thread(public, who)), "said": f"{s.name} is set: {said}." if said
            else f"{s.name} is set."}


def _keep(who, s: Service, values: dict, said: str) -> None:
    from .encryption import box
    from .models import ServiceKey

    now = time.time()
    for f in s.fields:
        v = values.get(f.name, "")
        if v:
            ServiceKey.objects.update_or_create(
                org_id=_org(), name=f.name,
                defaults={"value_sealed": box().seal(v), "last4": v[-4:] if f.secret else "",
                          "saved_by": str(who.user_id), "saved_at": now})
        else:
            ServiceKey.objects.filter(org_id=_org(), name=f.name).delete()
    _record(s.id, True if s.check else None, said)
    apply()
    if s.after:
        try:
            s.after()
        except Exception:  # noqa: BLE001 - kept all the same; the log says what did not follow
            log.exception("what %s holds could not be made again with its new values", s.id)
    log.info("the %s settings were saved in Settings by user %s", s.id, who.user_id)


async def check_again(who, service: str) -> dict:
    """Ask the service again with what this Rouh uses now. Kept whatever it says."""
    _admin(who)
    s = BY_ID.get(str(service or ""))
    if s is None or s.check is None:
        raise Refused("That one has nothing to check.")
    values = {f.name: await asyncio.to_thread(value, f.name) for f in s.fields}
    if any(f.required and not values[f.name] for f in s.fields):
        raise Refused(f"{s.name} is not set, so there is nothing to check.")
    try:
        _v, said = await _run(s.check, values)
        ok, line = True, said
    except Refused as exc:
        ok, line = False, _scrub(str(exc), values)
    except Exception as exc:  # noqa: BLE001
        ok, line = False, f"the check could not be made ({type(exc).__name__})"
    values.clear()
    await asyncio.to_thread(_record, s.id, ok, line)
    return {**(await asyncio.to_thread(public, who)), "said": f"{s.name}: {line}.", "passed": ok}


def remove(who, service: str) -> dict:
    """Forget what was kept for a service here. The settings file's, if it has one, is used again."""
    _admin(who)
    s = BY_ID.get(str(service or ""))
    if s is None:
        raise Refused("There is no such service here.")
    from .models import ServiceCheck, ServiceKey

    ServiceKey.objects.filter(org_id=_org(), name__in=[f.name for f in s.fields]).delete()
    ServiceCheck.objects.filter(org_id=_org(), service=s.id).delete()
    apply()
    if s.after:
        try:
            s.after()
        except Exception:  # noqa: BLE001
            log.exception("what %s holds could not be made again", s.id)
    log.info("the %s settings were removed from Settings by user %s", s.id, who.user_id)
    return public(who)


def start() -> None:
    """At start, and in a command's own process: what is kept, taken up."""
    _remember_defaults()
    try:
        from . import telegram_bot

        telegram_bot.carry_over()
    except Exception:  # noqa: BLE001
        log.debug("nothing carried over for Telegram", exc_info=True)
    apply()
    for s in SERVICES:
        if s.after:
            try:
                s.after()
            except Exception:  # noqa: BLE001
                log.debug("what %s holds was not made again at start", s.id, exc_info=True)

