"""Slack: Rouh's own Slack app in the person's workspace, its tokens, and every message it can see.

Petar, 16 October 2026: "I need you to evesdrop on my slack. Full integration. You should be able
to talk to people and be added to channels. Ideally we also want personal messages directly to me
to be readable by you. Let's set this up." He owns the workspace.

**The app.** An internal app of the one workspace, never distributed: an internal app keeps Slack's
Tier 3 limits on `conversations.history` and `conversations.replies` (the one-a-minute limit is
only for apps sold outside the Marketplace). It is made from Rouh's own manifest (`manifest`) by one
press in Settings, Connections, Slack, which opens Slack's "Create an app" with it filled in
(`create_url`). It has a bot user, Rouh, and Socket Mode, so Slack's events come to Rouh over a
socket Rouh opens and nothing on this server has to be reachable from outside.

**Three tokens**, typed into that page and nowhere else, each checked with Slack before it is kept
and sealed with `encryption.SecretBox`, as the Cloudflare tokens are (`rouh/cloudflare.py`). None
ever goes through a chat, a model, a tool result, a log line or an error message; the page shows
only that each is set and its last four characters.

- The **bot token** (xoxb-) is the app's: it reads the channels Rouh is a member of, the direct
  messages people send to Rouh, and posts as Rouh.
- The **user token** (xoxp-) is the person's own, with read scopes only (`USER_SCOPES`): it reads
  their own direct messages and group direct messages and nothing else. A user token that could
  write anything is refused, so Rouh can never post as them.
- The **app-level token** (xapp-, `connections:write`) opens the Socket Mode connection.

**Whose.** The app, its bot token and its app-level token are the organisation's (`org_id`); the
user token, and what it reads, are the one person's who connected it (`user_id`), and every kept
message names both. Messages between other people that the person is not in are never asked for:
the user token is only ever used to list and read the person's own direct messages
(`USER_KINDS`), and Slack itself refuses it anything else.

**What is kept** (`SlackMessage`): every message in every conversation Rouh can see, by
conversation, with who wrote it (their name, and the contact in Synapse Master their Slack address
belongs to), when, its thread, its words and the names of its files. An edit in Slack changes the
kept copy; a deletion removes it. `rouh/slack_listen.py` keeps it in step, from Slack's events and
a first look back over the last 90 days; `master_items` hands it to Synapse Master, one item per
conversation per day, as long chats are kept there.

**The person's own direct messages** read with their user token are theirs only (`private`): never
quoted in Slack, in mail or on a page for anybody else unless they ask, kept in Synapse as special
so only they can read them, and marked as theirs wherever a tool shows them.

`ROUH_SLACK_API` points every call at a stand-in (`rouh/testing/fake_slack.py`).
"""
from __future__ import annotations

import hashlib
import html
import json
import logging
import os
import re
import threading
import time
import urllib.parse

from . import clock, owner
from .encryption import box as _box

log = logging.getLogger("rouh.slack")

#: Slack's Web API, or a stand-in's in a test world.
API = os.environ.get("ROUH_SLACK_API", "https://slack.com/api").rstrip("/")
PAGE = "/settings/slack"
TIMEOUT = 20
#: How far back the first look reads each conversation. Petar, 16 October 2026: 90 days, not 30.
#: A connection whose finished look back covered fewer days is read back once more for these.
BACKFILL_DAYS = 90
#: The longest Rouh waits on one Retry-After before giving that call up.
RETRY_MOST = 300

APP_NAME = "Rouh"
APP_ABOUT = "Rouh, ‹owner›'s assistant: reads the channels it is in and answers what is asked of it."

#: What the bot may do: read the channels it is in and the messages people send it, know who
#: people are (their address too, to find their contact), and post as Rouh.
BOT_SCOPES = ("channels:read", "channels:history", "channels:join", "groups:read", "groups:history",
              "im:read", "im:history", "im:write", "mpim:read", "mpim:history", "chat:write",
              "users:read", "users:read.email", "reactions:read", "files:read", "app_mentions:read")
#: What the person's own token may do: read their own direct messages, and know who people are.
#: Nothing that writes: Rouh never posts as them.
USER_SCOPES = ("im:read", "im:history", "mpim:read", "mpim:history", "users:read")
#: Slack grants these to every user token by itself, and they can only read whose the token is.
IMPLICIT_USER_SCOPES = ("identify",)
BOT_EVENTS = ("message.channels", "message.groups", "message.im", "message.mpim", "app_mention",
              "member_joined_channel", "channel_created")
USER_EVENTS = ("message.im", "message.mpim")

#: The kinds of conversation the person's own token is ever used for.
USER_KINDS = ("im", "mpim")
#: What each kind is called.
KIND_WORDS = {"channel": "channel", "group": "private channel", "im": "direct message",
              "mpim": "group direct message"}

#: The message subtypes kept: what a person or a bot wrote. A join, a topic change and the like are
#: Slack's own notes and are not kept.
KEPT_SUBTYPES = ("", "file_share", "thread_broadcast", "bot_message", "me_message")

_PREFIX = {"bot": "xoxb-", "user": "xoxp-", "app": "xapp-"}
_TOKEN = re.compile(r"^xox[bp]-[A-Za-z0-9-]{10,250}$|^xapp-[A-Za-z0-9-]{10,250}$")
TOKEN_WORDS = {"bot": "bot token", "user": "your user token", "app": "app-level token"}


class Refused(ValueError):
    """Said to the person as it is. Never holds a token or any part of one but its last four."""


class NotSetUp(LookupError):
    """Slack is not connected, or not far enough for this: what to do about it, in a sentence."""


class SlackError(Exception):
    """Slack said no, or could not be reached: Slack's own error code and words, never a token."""

    def __init__(self, error: str, said: str = "") -> None:
        super().__init__(said or error)
        self.error = error


# --- the manifest ---------------------------------------------------------------------------


def manifest() -> dict:
    """The app as Slack's manifest describes it: a bot user named Rouh, Socket Mode, and exactly
    the scopes and events above. Interactivity is off: Rouh only reads and writes messages."""
    return {
        "_metadata": {"major_version": 1, "minor_version": 1},
        "display_information": {"name": APP_NAME, "description": owner.say(APP_ABOUT)[:140],
                                "background_color": "#1d1f24"},
        "features": {
            "app_home": {"home_tab_enabled": False, "messages_tab_enabled": True,
                         "messages_tab_read_only_enabled": False},
            "bot_user": {"display_name": APP_NAME, "always_online": True},
        },
        "oauth_config": {"scopes": {"bot": list(BOT_SCOPES), "user": list(USER_SCOPES)}},
        "settings": {
            "event_subscriptions": {"bot_events": list(BOT_EVENTS), "user_events": list(USER_EVENTS)},
            "interactivity": {"is_enabled": False},
            "org_deploy_enabled": False,
            "socket_mode_enabled": True,
            "token_rotation_enabled": False,
        },
    }


def create_url() -> str:
    """Slack's "Create an app" with Rouh's manifest already filled in: one press makes the app."""
    return ("https://api.slack.com/apps?new_app=1&manifest_json="
            + urllib.parse.quote(json.dumps(manifest(), separators=(",", ":")), safe=""))


# --- talking to Slack -----------------------------------------------------------------------


class Client:
    """Slack's Web API with one token. Every call is a form POST with the token as a Bearer header,
    as Slack takes for every method. A 429 is waited out for as long as its Retry-After says, up to
    `RETRY_MOST` seconds a time, and the call made again."""

    def __init__(self, token: str, *, api: str | None = None) -> None:
        self._token = token
        self.api = (api or API).rstrip("/")
        #: The scopes Slack said the token has, from the last answer that said.
        self.scopes: tuple[str, ...] = ()

    def __repr__(self) -> str:
        return f"slack.Client({self._token[:5]}…)"

    def call(self, method: str, **params) -> dict:
        import httpx

        data = {k: (json.dumps(v) if isinstance(v, (dict, list)) else str(v))
                for k, v in params.items() if v is not None and v != ""}
        tries = 0
        while True:
            tries += 1
            try:
                r = httpx.post(f"{self.api}/{method}", data=data, timeout=TIMEOUT,
                               headers={"Authorization": f"Bearer {self._token}"})
            except httpx.HTTPError as exc:
                raise SlackError("unreachable", f"Slack could not be reached ({type(exc).__name__})") from None
            if r.status_code == 429:
                wait = _retry_after(r.headers.get("Retry-After"))
                if tries > 6 or wait > RETRY_MOST:
                    raise SlackError("ratelimited", f"Slack is limiting {method}; tried {tries} times")
                log.info("slack: %s is rate limited; waiting %s s as Retry-After says", method, wait)
                time.sleep(wait)
                continue
            try:
                out = r.json()
            except ValueError:
                raise SlackError(f"http_{r.status_code}", f"Slack answered {method} with HTTP {r.status_code}") from None
            said = r.headers.get("x-oauth-scopes")
            if said is not None:
                self.scopes = tuple(s.strip() for s in said.split(",") if s.strip())
            if not isinstance(out, dict) or not out.get("ok"):
                error = str((out or {}).get("error") or "unknown_error") if isinstance(out, dict) else "unknown_error"
                raise SlackError(error, f"Slack said {error} to {method}")
            return out

    def pages(self, method: str, key: str, *, most: int = 0, **params):
        """Every item of a listing, page by page with its cursor."""
        cursor, seen = "", 0
        while True:
            got = self.call(method, **params, **({"cursor": cursor} if cursor else {}))
            for one in got.get(key) or []:
                yield one
                seen += 1
                if most and seen >= most:
                    return
            cursor = str(((got.get("response_metadata") or {}).get("next_cursor")) or "")
            if not cursor:
                return


def _retry_after(value) -> float:
    try:
        return max(1.0, float(value))
    except (TypeError, ValueError):
        return 30.0


# --- the box and the row --------------------------------------------------------------------

def _model():
    from .models import SlackConnection

    return SlackConnection


def connection(org_id: str):
    """The organisation's Slack app, or None."""
    return _model().objects.filter(org_id=str(org_id)).first() if org_id else None


def connections() -> list:
    """Every organisation's app that has tokens to listen with."""
    return list(_model().objects.exclude(app_sealed="").exclude(bot_sealed=""))


def _org(org_id: str | None) -> str:
    """Whose Slack: the one given, the speaker's, the only person's. Never a guess between two."""
    if org_id:
        return str(org_id)
    from .tenancy import Tenancy, speaker

    who = speaker() or Tenancy().only_person()
    if who is None:
        raise NotSetUp("Whose Slack? Nobody is speaking.")
    return who.org_id


def token(conn, which: str) -> str:
    """One kept token, opened, for Rouh's own code to call Slack with: never shown or said."""
    sealed = getattr(conn, f"{which}_sealed", "") if conn is not None else ""
    if not sealed:
        raise NotSetUp(f"Slack's {TOKEN_WORDS[which]} is not set. It is added in Settings, "
                       f"Connections, Slack ({PAGE}).")
    return _box().open_(sealed)


def bot(conn) -> Client:
    return Client(token(conn, "bot"))


def user_client(conn) -> Client | None:
    """The person's own token, for their own direct messages only; None when it is not set."""
    return Client(token(conn, "user")) if conn is not None and conn.user_sealed else None


def _set(conn_id: int, **fields) -> None:
    fields["updated_at"] = time.time()
    _model().objects.filter(id=conn_id).update(**fields)


def note_listening(org_id: str, state: str, said: str = "", **more) -> None:
    """How listening goes, for the page: "connecting", "listening", "waiting" or "off"."""
    _model().objects.filter(org_id=str(org_id)).update(listening=state, listening_said=said[:300],
                                                      updated_at=time.time(), **more)


# --- the page: checking and keeping tokens --------------------------------------------------


def _admin(who) -> None:
    if not getattr(who, "is_admin", False):
        raise Refused("Only an administrator of this organisation connects Slack.")


def _clean(which: str, value) -> str:
    text = str(value or "").strip()
    if text.lower().startswith("bearer "):
        text = text[7:].strip()
    if not text:
        return ""
    if not text.startswith(_PREFIX[which]) or not _TOKEN.match(text):
        raise Refused(f"That is not a {TOKEN_WORDS[which]}: it starts {_PREFIX[which]}. Nothing was saved.")
    return text


def _check_bot(value: str) -> dict:
    c = Client(value)
    try:
        got = c.call("auth.test")
    except SlackError as exc:
        raise Refused(f"Slack does not accept that bot token ({exc.error}). Nothing was saved.") from None
    if not got.get("bot_id"):
        raise Refused("That token is not a bot token: copy the Bot User OAuth Token. Nothing was saved.")
    missing = [s for s in BOT_SCOPES if c.scopes and s not in c.scopes]
    if missing:
        raise Refused("That bot token is missing " + _and(missing) + ". Install the app again from "
                      "its OAuth & Permissions page, then copy the new token. Nothing was saved.")
    return {"team_id": str(got.get("team_id") or ""), "team_name": str(got.get("team") or ""),
            "team_url": str(got.get("url") or ""), "bot_user_id": str(got.get("user_id") or ""),
            "bot_name": str(got.get("user") or APP_NAME)}


def _check_user(value: str) -> dict:
    c = Client(value)
    try:
        got = c.call("auth.test")
    except SlackError as exc:
        raise Refused(f"Slack does not accept that user token ({exc.error}). Nothing was saved.") from None
    if got.get("bot_id"):
        raise Refused("That is a bot token, not your user token: copy the User OAuth Token. Nothing was saved.")
    extra = [s for s in c.scopes if s not in USER_SCOPES and s not in IMPLICIT_USER_SCOPES]
    if extra:
        raise Refused("That user token can do more than read your own direct messages ("
                      + _and(extra) + "). Rouh never acts as you, so make it with only "
                      + _and(list(USER_SCOPES)) + ". Nothing was saved.")
    missing = [s for s in USER_SCOPES if c.scopes and s not in c.scopes]
    if missing:
        raise Refused("That user token is missing " + _and(missing) + ". Nothing was saved.")
    return {"team_id": str(got.get("team_id") or ""), "slack_user_id": str(got.get("user_id") or ""),
            "slack_user_name": str(got.get("user") or "")}


def _check_app(value: str) -> None:
    try:
        Client(value).call("apps.connections.open")
    except SlackError as exc:
        if exc.error in ("invalid_auth", "not_authed", "missing_scope", "not_allowed_token_type"):
            raise Refused("Slack does not accept that app-level token for Socket Mode ("
                          f"{exc.error}). Make one with the connections:write scope. Nothing was saved.") from None
        raise Refused(f"Slack could not check that app-level token ({exc.error}). Nothing was saved.") from None


def save(who, *, bot_token: str = "", user_token: str = "", app_token: str = "") -> dict:
    """Check each token given with Slack and keep it, sealed; or refuse them all, saying why."""
    _admin(who)
    given = {"bot": _clean("bot", bot_token), "user": _clean("user", user_token),
             "app": _clean("app", app_token)}
    bot_token = user_token = app_token = ""
    if not any(given.values()):
        raise Refused("Paste a token first.")
    m = _model()
    row = m.objects.filter(org_id=who.org_id).first()
    fields: dict = {}
    if given["bot"]:
        fields.update(_check_bot(given["bot"]))
    team = fields.get("team_id") or (row.team_id if row is not None else "")
    if given["user"]:
        found = _check_user(given["user"])
        if team and found["team_id"] != team:
            raise Refused("That user token is for another Slack workspace than Rouh's bot. Nothing was saved.")
        fields.update(slack_user_id=found["slack_user_id"], slack_user_name=found["slack_user_name"])
        fields.setdefault("team_id", found["team_id"])
    if given["app"]:
        _check_app(given["app"])
    if row is not None and fields.get("team_id") and row.team_id and fields["team_id"] != row.team_id:
        raise Refused(f"That token is for another workspace than the one connected ({row.team_name}). "
                      "Disconnect first to move Rouh to another workspace. Nothing was saved.")
    now = time.time()
    for which, value in given.items():
        if value:
            fields[f"{which}_sealed"] = _box().seal(value)
            fields[f"{which}_last4"] = value[-4:]
    given = {}
    fields.update(saved_at=now, checked_at=now, updated_at=now, user_id=str(who.user_id))
    if row is None:
        row = m.objects.create(org_id=who.org_id, made_at=now, **fields)
    else:
        m.objects.filter(id=row.id, org_id=who.org_id).update(**fields)
    log.info("slack: tokens checked and saved for org %s by user %s", who.org_id, who.user_id)
    return public(who)


def check(who) -> tuple[dict, str]:
    """Each kept token asked of Slack again. (the page, what was found wrong or "")."""
    _admin(who)
    row = connection(who.org_id)
    if row is None:
        raise Refused("Slack is not connected.")
    wrong = []
    for which, test in (("bot", _check_bot), ("user", _check_user), ("app", _check_app)):
        if getattr(row, f"{which}_sealed"):
            try:
                test(token(row, which))
            except Refused as exc:
                wrong.append(str(exc).replace(" Nothing was saved.", ""))
    _set(row.id, checked_at=time.time())
    return public(who), " ".join(wrong)


def remove(who) -> dict:
    """Forget every token. They still work at Slack until the app is removed there."""
    _admin(who)
    _model().objects.filter(org_id=who.org_id).update(
        bot_sealed="", bot_last4="", user_sealed="", user_last4="", app_sealed="", app_last4="",
        listening="off", listening_said="Disconnected in Settings.", updated_at=time.time())
    log.info("slack: tokens removed for org %s by user %s", who.org_id, who.user_id)
    return public(who)


def _when(ts) -> str:
    from . import clock

    return clock.moment(ts).strftime("%-d %b %Y, %H:%M") if ts else ""


def _and(items: list) -> str:
    items = [str(i) for i in items]
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1] if items else ""


def counts(org_id: str) -> dict:
    from .models import SlackConversation, SlackMessage

    return {"conversations": SlackConversation.objects.filter(org_id=org_id).filter(
                _readable_q()).count(),
            "messages": SlackMessage.objects.filter(org_id=org_id).count()}


def _readable_q():
    from django.db.models import Q

    return Q(is_member=True) | Q(private=True)


def public(who) -> dict:
    """Everything the page shows, for the person's organisation. Never a token."""
    row = connection(who.org_id)
    base = {"admin": bool(getattr(who, "is_admin", False)), "create_url": create_url(),
            "bot_scopes": list(BOT_SCOPES), "user_scopes": list(USER_SCOPES)}
    if row is None:
        return {**base, "connected": False, "tokens": {k: None for k in _PREFIX}}
    tokens = {k: ({"last4": getattr(row, f"{k}_last4")} if getattr(row, f"{k}_sealed") else None)
              for k in _PREFIX}
    mine = str(row.user_id) == str(who.user_id)
    return {
        **base,
        "connected": bool(row.bot_sealed and row.app_sealed),
        "tokens": tokens,
        "team": row.team_name, "team_url": row.team_url, "bot": row.bot_name,
        "for": row.slack_user_name if row.user_sealed else "",
        "for_you": mine,
        "saved": _when(row.saved_at),
        "listening": row.listening or "", "listening_said": row.listening_said,
        "since": _when(row.connected_at) if row.listening == "listening" else "",
        "heard": _when(row.heard_at),
        "backfill": {**(row.backfill or {}),
                     "finished": _when((row.backfill or {}).get("finished_at"))},
        **counts(who.org_id),
    }


def status_line(who) -> str:
    """What a tool may say about the connection, in a sentence or two."""
    d = public(who)
    if not d["tokens"]["bot"]:
        return f"Slack is not connected. ‹Owner› connects it in Settings, Connections, Slack ({PAGE})."
    out = [f"Rouh's Slack app is in the {d['team'] or 'connected'} workspace as @{d['bot'] or 'Rouh'}"]
    out.append(f"reading {d['for']}'s own direct messages too" if d["for"] else
               "without ‹owner›'s user token, so not ‹his› own direct messages")
    said = {"listening": f"listening since {d['since']}", "connecting": "connecting",
            "waiting": f"not listening ({d['listening_said'] or 'waiting to try again'})",
            "off": "not listening"}.get(d["listening"], "not listening yet")
    return (", ".join(out) + f"; {said}. It keeps {d['messages']} message"
            f"{'' if d['messages'] == 1 else 's'} from {d['conversations']} conversation"
            f"{'' if d['conversations'] == 1 else 's'}.")


# --- who people are -------------------------------------------------------------------------

_PEOPLE_LOCK = threading.Lock()
#: How long a person's name and address are trusted before Slack is asked again.
PERSON_FRESH = 86400.0


def person(conn, slack_id: str, client: Client | None = None, *, fresh: bool = False):
    """Somebody in the workspace, from what is kept or from Slack's `users.info`, with the contact
    their Slack address is in Synapse Master. None for no id."""
    from .models import SlackPerson

    slack_id = str(slack_id or "").strip()
    if not slack_id or conn is None:
        return None
    row = SlackPerson.objects.filter(org_id=conn.org_id, team_id=conn.team_id, slack_id=slack_id).first()
    if row is not None and not fresh and time.time() - row.updated_at < PERSON_FRESH:
        return row
    try:
        got = (client or bot(conn)).call("users.info", user=slack_id).get("user") or {}
    except (SlackError, NotSetUp) as exc:
        log.info("slack: who %s is could not be read: %s", slack_id, exc)
        return row
    profile = got.get("profile") or {}
    name = str(profile.get("display_name") or got.get("real_name") or got.get("name") or slack_id)
    real = str(got.get("real_name") or profile.get("real_name") or name)
    email = str(profile.get("email") or "").strip().lower()
    # The person already carrying the member comes first: one the owner linked them to by hand
    # (`synapse.aka`), whatever address their Slack profile gives.
    contact_id, contact_name = _contact_carrying(conn, slack_id)
    if not contact_id:
        contact_id, contact_name = _contact_of(conn, email) if email else ("", "")
    if not contact_id and not got.get("is_bot") and not got.get("deleted"):
        contact_id, contact_name = _contact_by_name(conn, slack_id, real)
    fields = {"name": name[:200], "real_name": real[:200], "email": email[:254],
              "is_bot": bool(got.get("is_bot")), "deleted": bool(got.get("deleted")),
              "contact_id": contact_id, "contact_name": contact_name, "updated_at": time.time()}
    with _PEOPLE_LOCK:
        SlackPerson.objects.update_or_create(org_id=conn.org_id, team_id=conn.team_id, slack_id=slack_id,
                                             defaults=fields)
    row = SlackPerson.objects.filter(org_id=conn.org_id, team_id=conn.team_id, slack_id=slack_id).first()
    tie(conn, row)
    return row


def _master(conn):
    from .synapse import db, master

    if not db.ready():
        return None
    return master.of(str(conn.org_id), str(conn.user_id))


def tie(conn, one) -> str:
    """The member put on their contact in Synapse Master as one of its identifiers: their Slack id, shown as
    @Tomek, and the names they go by in Slack, so the contact is one person in Slack, the mail and the
    meetings. What it did: 'added', 'had', '' when there is nobody to tie them to, or the id of another
    contact the member is already on (then nothing moves: two contacts with one member are his to merge)."""
    if one is None or not one.contact_id or one.is_bot:
        return ""
    try:
        from .synapse import people

        ds = _master(conn)
        if ds is None:
            return ""
        return people.carry_slack(people.home_id(ds), one.contact_id, team=conn.team_id, slack_id=one.slack_id,
                                  display=one.name, real=one.real_name)
    except Exception:  # noqa: BLE001 - a member not tied is still a member
        log.exception("slack: a member could not be put on their contact")
        return ""


def tie_all(conn) -> dict:
    """Every member Rouh keeps, tied to their contact as `person` ties one it reads afresh: by the address
    Slack gives, else surely by name (`_contact_by_name`). {tied, already, untied, clash}."""
    from .models import SlackPerson

    out = {"tied": 0, "already": 0, "untied": 0, "clash": 0}
    for one in SlackPerson.objects.filter(org_id=conn.org_id, team_id=conn.team_id, is_bot=False, deleted=False):
        if not one.contact_id:
            found = _contact_of(conn, one.email) if one.email else ("", "")
            if not found[0]:
                found = _contact_by_name(conn, one.slack_id, one.real_name or one.name)
            if found[0]:
                one.contact_id, one.contact_name = found
                SlackPerson.objects.filter(pk=one.pk).update(contact_id=found[0], contact_name=found[1])
        said = tie(conn, one)
        out[{"added": "tied", "had": "already", "": "untied"}.get(said, "clash")] += 1
    return out


def _contact_carrying(conn, slack_id: str) -> tuple[str, str]:
    """The person in Synapse Master who carries this member as one of their identifiers, or ("", "")."""
    try:
        from .synapse import people

        ds = _master(conn)
        if ds is None:
            return "", ""
        scope = people.home_id(ds)
        pid = people.find(scope, "slack", people.slack_value(conn.team_id, slack_id))
        return (str(pid), str((people.get(scope, pid) or {}).get("title") or "")) if pid else ("", "")
    except Exception:  # noqa: BLE001 - no Master yet
        log.exception("slack: the person carrying a member could not be looked for")
        return "", ""


def _contact_by_name(conn, slack_id: str, real: str) -> tuple[str, str]:
    """For a member Slack gives no address for: the contact already carrying their Slack id, else the one
    contact their full name surely is (`people.sure_by_name`: one person by that name, Tomek being Tomasz,
    with an address at the company of a channel they write in). Anybody less sure is never tied: they are
    flagged as likely the same on the contacts (`people.flag_same_name`), for his pick in Synapse."""
    try:
        from .synapse import people

        ds = _master(conn)
        if ds is None:
            return "", ""
        scope = people.home_id(ds)
        pid = people.find(scope, "slack", people.slack_value(conn.team_id, slack_id))
        if not pid:
            pid, _maybe = people.sure_by_name(scope, real, _companies_of(conn, slack_id))
        if not pid:
            return "", ""
        return str(pid), str((people.get(scope, pid) or {}).get("title") or "")
    except Exception:  # noqa: BLE001 - no Master yet: no contact, never no message
        log.exception("slack: a member's contact could not be looked for by name")
        return "", ""


def _companies_of(conn, slack_id: str) -> list[str]:
    """The company words of the channels a member writes in: "brightfield" for #brightfield-northwind."""
    from .models import SlackConversation, SlackMessage

    cids = set(SlackMessage.objects.filter(org_id=conn.org_id, team_id=conn.team_id, author_id=slack_id)
               .values_list("channel_id", flat=True).distinct()[:50])
    words: list[str] = []
    for c in SlackConversation.objects.filter(org_id=conn.org_id, team_id=conn.team_id, channel_id__in=cids):
        for w in re.split(r"[^a-z0-9]+", str(c.name or "").lower()):
            if len(w) >= 3 and w not in words:
                words.append(w)
    return words


def _contact_of(conn, email: str) -> tuple[str, str]:
    """The person's contact this address belongs to, by its id and name, or ("", "")."""
    try:
        from .people import People

        found = People().by_address(str(conn.user_id), str(conn.org_id), email)
    except Exception:  # noqa: BLE001 - no Master yet: no contact, never no message
        return "", ""
    return (found[0].id, found[0].name) if found else ("", "")


def name_of(conn, slack_id: str) -> str:
    one = person(conn, slack_id)
    return (one.real_name or one.name) if one is not None else str(slack_id or "")


def linked_senders(user_id: str, org_id: str, addresses) -> list[str]:
    """The Slack accounts in the connected workspace whose confirmed address is one of these, as a
    case names a sender who wrote on Slack: "slack:<id>" (`trusted.Trusted.slack`)."""
    from .models import SlackPerson

    want = sorted({str(a).strip().lower() for a in addresses or () if str(a).strip()})
    conn = connection(org_id)
    if not want or conn is None or not conn.team_id or str(conn.user_id) != str(user_id):
        return []
    return [SENDER + s for s in SlackPerson.objects.filter(
        org_id=org_id, team_id=conn.team_id, email__in=want, is_bot=False, deleted=False)
        .values_list("slack_id", flat=True)]


#: How a case names a sender who wrote on Slack, and how its message id starts.
SENDER = "slack:"
CASE_PREFIX = "slack:"


def on_slack(case_or_message_id) -> bool:
    """Whether a case (or its message id) came on Slack."""
    mid = case_or_message_id if isinstance(case_or_message_id, str) else \
        str(getattr(case_or_message_id, "message_id", "") or "")
    return mid.startswith(CASE_PREFIX)


# --- conversations --------------------------------------------------------------------------


def kind_of(info: dict) -> str:
    if info.get("is_im"):
        return "im"
    if info.get("is_mpim"):
        return "mpim"
    if info.get("is_private") or info.get("is_group"):
        return "group"
    return "channel"


def keep_conversation(conn, info: dict, *, private: bool = False, member: bool | None = None):
    """A conversation as Slack described it, kept or brought up to date."""
    from .models import SlackConversation

    cid = str(info.get("id") or "")
    if not cid:
        return None
    kind = kind_of(info)
    if private and kind not in USER_KINDS:
        return None     # the person's token reads only their own direct messages
    other = str(info.get("user") or "") if kind == "im" else ""
    if kind == "im":
        name = name_of(conn, other) if other else "a direct message"
    elif kind == "mpim":
        name = _mpim_name(str(info.get("name") or ""), info.get("purpose"))
    else:
        name = str(info.get("name") or cid)
    fields = {"user_id": str(conn.user_id), "kind": kind, "name": name[:200],
              "is_archived": bool(info.get("is_archived")),
              "topic": str(((info.get("topic") or {}).get("value")) or "")[:500],
              "other_id": other, "updated_at": time.time()}
    row = SlackConversation.objects.filter(org_id=conn.org_id, team_id=conn.team_id, channel_id=cid).first()
    if private:
        # Seen through the person's own token. One the bot sees too - Rouh's own direct message
        # with them - stays the bot's: everybody in it knows Rouh is there.
        if row is not None and not row.private:
            SlackConversation.objects.filter(id=row.id).update(**fields)
            return SlackConversation.objects.get(id=row.id)
        flags = {"is_member": False, "private": True}
    else:
        member_now = bool(info.get("is_member")) if member is None else member
        flags = {"is_member": bool(member_now) or kind in USER_KINDS, "private": False}
    if row is None:
        return SlackConversation.objects.create(org_id=conn.org_id, team_id=conn.team_id, channel_id=cid,
                                                **flags, **fields)
    SlackConversation.objects.filter(id=row.id).update(**flags, **fields)
    return SlackConversation.objects.get(id=row.id)


def _mpim_name(name: str, purpose) -> str:
    # "mpdm-alex--sam--jordan-1" is how Slack names a group direct message.
    if name.startswith("mpdm-"):
        people = [p for p in re.sub(r"-\d+$", "", name[5:]).split("--") if p]
        return "group: " + ", ".join(people)
    return name or "a group direct message"


def conversation(conn, channel_id: str, *, hint: str = ""):
    """A conversation by its id: kept, or asked of Slack - the bot's first, and the person's own
    token only for one of their own direct messages. None when neither can see it."""
    from .models import SlackConversation

    row = SlackConversation.objects.filter(org_id=conn.org_id, team_id=conn.team_id,
                                           channel_id=channel_id).first()
    if row is not None:
        return row
    try:
        info = bot(conn).call("conversations.info", channel=channel_id).get("channel") or {}
        return keep_conversation(conn, info)
    except SlackError as exc:
        if exc.error not in ("channel_not_found", "not_in_channel", "missing_scope"):
            log.info("slack: conversation %s could not be read with the bot: %s", channel_id, exc.error)
    except NotSetUp:
        return None
    mine = user_client(conn)
    if mine is None or (hint and hint not in USER_KINDS):
        return None
    try:
        info = mine.call("conversations.info", channel=channel_id).get("channel") or {}
    except SlackError:
        return None
    return keep_conversation(conn, info, private=True)


def members(conn, channel_id: str, *, most: int = 1000) -> list[str]:
    """Everybody in a conversation, by Slack id, as Slack says now (`conversations.members`), the
    bots and Rouh's own included. SlackError when Slack would not say."""
    return [str(m) for m in bot(conn).pages("conversations.members", "members", channel=channel_id,
                                             limit=200, most=most) if m]


def conversation_label(row) -> str:
    """A conversation in words: "#general", "the private channel #board", "your direct message
    with Sam", "Rouh's direct message with Sam"."""
    if row is None:
        return "a conversation"
    if row.kind == "channel":
        return f"#{row.name}"
    if row.kind == "group":
        return f"the private channel #{row.name}"
    whose = "your" if row.private else "Rouh's"
    if row.kind == "im":
        return f"{whose} direct message with {row.name}"
    return f"{whose} {row.name.replace('group: ', 'group direct message with ')}"


# --- messages -------------------------------------------------------------------------------


def ts_float(ts) -> float:
    try:
        return float(ts)
    except (TypeError, ValueError):
        return 0.0


_MENTION = re.compile(r"<@([UWB][A-Z0-9]+)(?:\|([^>]*))?>")
_CHANNEL = re.compile(r"<#([CGD][A-Z0-9]+)(?:\|([^>]*))?>")
_LINK = re.compile(r"<((?:https?|mailto):[^|>]+)(?:\|([^>]*))?>")
_SPECIAL = re.compile(r"<!(here|channel|everyone)(?:\|[^>]*)?>")


def plain(conn, text: str) -> str:
    """Slack's message text as a person reads it: @names, #channels and links written out."""
    from .models import SlackConversation

    text = str(text or "")

    def who(m):
        return "@" + (m.group(2) or name_of(conn, m.group(1)))

    def where(m):
        if m.group(2):
            return "#" + m.group(2)
        row = SlackConversation.objects.filter(org_id=conn.org_id, channel_id=m.group(1)).first()
        return "#" + (row.name if row is not None else m.group(1))

    def link(m):
        url, label = m.group(1), m.group(2)
        url = url[7:] if url.startswith("mailto:") else url
        return f"{label} ({url})" if label and label != url else url

    text = _MENTION.sub(who, text)
    text = _CHANNEL.sub(where, text)
    text = _LINK.sub(link, text)
    text = _SPECIAL.sub(lambda m: "@" + m.group(1), text)
    return html.unescape(text)


def mentions(text: str, slack_id: str) -> bool:
    """Whether a message's raw text mentions this member."""
    return bool(slack_id) and any(m.group(1) == slack_id for m in _MENTION.finditer(str(text or "")))


def keep_message(conn, conv, m: dict, *, client: Client | None = None) -> tuple[object | None, bool]:
    """One message as Slack gave it, kept: (the row, whether it is new). One whose subtype is a
    note of Slack's own, or that is in a conversation the person's token may not read, is not kept."""
    from django.db import IntegrityError, transaction

    from .models import SlackMessage

    if conv is None or not m.get("ts"):
        return None, False
    if conv.private and conv.kind not in USER_KINDS:
        return None, False
    subtype = str(m.get("subtype") or "")
    if subtype not in KEPT_SUBTYPES:
        return None, False
    author = str(m.get("user") or m.get("bot_id") or "")
    one = person(conn, m.get("user"), client) if m.get("user") else None
    author_name = ((one.real_name or one.name) if one is not None else
                   str(m.get("username") or (m.get("bot_profile") or {}).get("name") or author or "somebody"))
    files = [str(f.get("name") or f.get("title") or "a file")[:200] for f in m.get("files") or []
             if isinstance(f, dict)]
    by_rouh = bool(conn.bot_user_id) and (
        str(m.get("user") or "") == conn.bot_user_id
        or str((m.get("bot_profile") or {}).get("user_id") or "") == conn.bot_user_id)
    fields = {
        # A thread's first message carries its own ts as thread_ts, as Slack gives it.
        "user_id": str(conn.user_id), "thread_ts": str(m.get("thread_ts") or ""),
        "reply_count": int(m.get("reply_count") or 0),
        "author_id": author, "author_name": author_name[:200],
        "contact_id": one.contact_id if one is not None else "",
        "contact_name": one.contact_name if one is not None else "",
        "text": plain(conn, m.get("text") or "")[:40000], "files": files, "subtype": subtype,
        "at": ts_float(m["ts"]), "edited_at": ts_float((m.get("edited") or {}).get("ts")),
        "private": bool(conv.private), "by_rouh": by_rouh, "updated_at": time.time(),
    }
    found = SlackMessage.objects.filter(org_id=conn.org_id, team_id=conn.team_id,
                                        channel_id=conv.channel_id, ts=str(m["ts"])).first()
    if found is not None:
        SlackMessage.objects.filter(id=found.id).update(**fields)
        return SlackMessage.objects.get(id=found.id), False
    try:
        with transaction.atomic():
            return SlackMessage.objects.create(org_id=conn.org_id, team_id=conn.team_id,
                                               channel_id=conv.channel_id, ts=str(m["ts"]),
                                               made_at=time.time(), **fields), True
    except IntegrityError:
        return SlackMessage.objects.filter(org_id=conn.org_id, team_id=conn.team_id,
                                           channel_id=conv.channel_id, ts=str(m["ts"])).first(), False


def forget_message(conn, channel_id: str, ts: str) -> int:
    """A message deleted in Slack, removed here."""
    from .models import SlackMessage

    return SlackMessage.objects.filter(org_id=conn.org_id, team_id=conn.team_id, channel_id=channel_id,
                                       ts=str(ts)).delete()[0]


# --- reading, for Rouh's tools --------------------------------------------------------------


def _conversations_q(conn):
    from .models import SlackConversation

    return SlackConversation.objects.filter(org_id=conn.org_id, team_id=conn.team_id)


def channels(conn, *, everything: bool = False) -> list[dict]:
    """The conversations Rouh can see, members first: each with its kind, whether Rouh is in it,
    whether it is the person's own, and how many messages are kept."""
    from django.db.models import Count, Max

    from .models import SlackMessage

    kept = {r["channel_id"]: r for r in SlackMessage.objects.filter(org_id=conn.org_id, team_id=conn.team_id)
            .values("channel_id").annotate(n=Count("id"), last=Max("at"))}
    out = []
    for c in _conversations_q(conn).order_by("kind", "name"):
        if not everything and c.is_archived:
            continue
        k = kept.get(c.channel_id) or {}
        out.append({"id": c.channel_id, "name": conversation_label(c), "kind": KIND_WORDS.get(c.kind, c.kind),
                    "rouh_in_it": bool(c.is_member), "yours_only": bool(c.private),
                    "kept": int(k.get("n") or 0), "last": _when(k.get("last")) if k.get("last") else "",
                    "topic": c.topic})
    out.sort(key=lambda r: (not r["rouh_in_it"] and not r["yours_only"], r["name"].lower()))
    return out


def _names(text: str, words: list[str]) -> bool:
    """Whether every word starts a word of the text: "petr" is Mila Petrova, never Kopetrova."""
    low = str(text or "").lower()
    return all(re.search(r"(?<![a-z0-9])" + re.escape(w), low) for w in words)


def find_conversation(conn, said: str):
    """A conversation by what somebody would call it: "#general", "general", its id, or a person's
    name for a direct message with them. None when nothing fits; ValueError when several do."""
    said = str(said or "").strip()
    if not said:
        return None
    q = _conversations_q(conn)
    by_id = q.filter(channel_id=said).first()
    if by_id is not None:
        return by_id
    bare = said.lstrip("#").lower()
    named = [c for c in q if c.kind in ("channel", "group") and c.name.lower() == bare]
    if len(named) == 1:
        return named[0]
    words = bare.split()
    people = [c for c in q if c.kind in USER_KINDS and _names(c.name, words)]
    # A person's name means the direct message with them, before a group one they are in; and of
    # the person's own and Rouh's own direct message with them, the person's own.
    ims = [c for c in people if c.kind == "im"]
    if ims:
        people = ims
        mine = [c for c in ims if c.private]
        if len(mine) == 1:
            return mine[0]
    if len(people) == 1:
        return people[0]
    if len(people) > 1:
        raise ValueError("Several conversations fit: " + _and([conversation_label(c) for c in people]) + ".")
    loose = [c for c in q if c.kind in ("channel", "group") and bare in c.name.lower()]
    if len(loose) == 1:
        return loose[0]
    if len(loose) > 1:
        raise ValueError("Several channels fit: " + _and(["#" + c.name for c in loose]) + ".")
    return None


def _line(conn, r, *, with_where: str = "") -> str:
    from . import clock

    moment = clock.moment(r.at)
    when = moment.strftime("%-d %b %H:%M") if moment else ""
    bits = [when, r.author_name + (f" ({r.contact_name})" if r.contact_name and r.contact_name != r.author_name
                                   else "")]
    head = " ".join(b for b in bits if b)
    if with_where:
        head += f" in {with_where}"
    if r.thread_ts and r.thread_ts != r.ts:
        head += " (in a thread)"
    elif r.reply_count:
        head += f" ({r.reply_count} repl{'y' if r.reply_count == 1 else 'ies'})"
    if r.edited_at:
        head += " (edited)"
    text = r.text or ""
    if r.files:
        text += ("\n" if text else "") + "[files: " + ", ".join(r.files) + "]"
    return f"[{r.ts}] {head}: {text}"


def read(conn, *, where: str = "", person_said: str = "", thread: str = "", most: int = 30) -> dict:
    """Messages of one conversation (or one thread of it), or everything one person wrote, newest
    first. {"title", "lines", "private"}; ValueError when what was named is not found."""
    from .models import SlackMessage

    most = max(1, min(int(most or 30), 200))
    q = SlackMessage.objects.filter(org_id=conn.org_id, team_id=conn.team_id)
    title, private = "", False
    conv = None
    if where:
        conv = find_conversation(conn, where)
        if conv is None:
            raise ValueError(f"Rouh sees no conversation called {where}. slack_channels lists them.")
        q = q.filter(channel_id=conv.channel_id)
        title, private = conversation_label(conv), conv.private
    if person_said:
        ids = _people_named(conn, person_said)
        if not ids:
            raise ValueError(f"Nobody called {person_said} has written anything Rouh keeps.")
        q = q.filter(author_id__in=ids)
        title = (title + ", " if title else "") + f"what {person_said} wrote"
    if thread:
        q = q.filter(models_q_thread(thread))
        title += f", the thread {thread}"
    rows = list(q.order_by("-at")[:most])
    names = {}
    if conv is None:
        from .models import SlackConversation

        names = {c.channel_id: (conversation_label(c), c.private) for c in SlackConversation.objects.filter(
            org_id=conn.org_id, channel_id__in={r.channel_id for r in rows})}
    lines = [_line(conn, r, with_where=names.get(r.channel_id, ("", False))[0] if conv is None else "")
             for r in rows]
    return {"title": title or "Slack", "lines": lines,
            "private": private or any(r.private for r in rows), "count": len(rows)}


def models_q_thread(thread_ts: str):
    from django.db.models import Q

    return Q(ts=thread_ts) | Q(thread_ts=thread_ts)


def _people_named(conn, said: str) -> list[str]:
    from .models import SlackPerson

    words = str(said or "").lower().replace("@", "").split()
    if not words:
        return []
    out = []
    for p in SlackPerson.objects.filter(org_id=conn.org_id, team_id=conn.team_id):
        if _names(" ".join([p.name, p.real_name, p.email, p.contact_name]), words):
            out.append(p.slack_id)
    return out


def search(conn, words: str, *, where: str = "", most: int = 30) -> dict:
    """Kept messages holding every word given, newest first, across what Rouh can see."""
    from django.db.models import Q

    from .models import SlackConversation, SlackMessage

    terms = [w for w in re.split(r"\s+", str(words or "").strip()) if w]
    if not terms:
        raise ValueError("Give the words to find.")
    q = SlackMessage.objects.filter(org_id=conn.org_id, team_id=conn.team_id)
    if where:
        conv = find_conversation(conn, where)
        if conv is None:
            raise ValueError(f"Rouh sees no conversation called {where}.")
        q = q.filter(channel_id=conv.channel_id)
    for t in terms:
        q = q.filter(Q(text__icontains=t) | Q(author_name__icontains=t) | Q(files__icontains=t))
    rows = list(q.order_by("-at")[:max(1, min(int(most or 30), 100))])
    names = {c.channel_id: conversation_label(c) for c in SlackConversation.objects.filter(
        org_id=conn.org_id, channel_id__in={r.channel_id for r in rows})}
    return {"lines": [_line(conn, r, with_where=names.get(r.channel_id, "")) for r in rows],
            "private": any(r.private for r in rows), "count": len(rows)}


# --- writing, as Rouh's bot -----------------------------------------------------------------


def to_mrkdwn(text: str) -> str:
    """Rouh's Markdown as Slack writes it: *bold*, <url|links>, and headings as bold lines."""
    text = str(text or "").replace("\r\n", "\n").strip()
    text = re.sub(r"\[([^\]\n]+)\]\((https?://[^)\s]+)\)", r"<\2|\1>", text)
    text = re.sub(r"\*\*(.+?)\*\*", r"*\1*", text)
    text = re.sub(r"(?m)^#{1,6}\s+(.+)$", r"*\1*", text)
    return text


def post_message(conn, *, channel: str, text: str, thread_ts: str = "", kind: str = "message",
                 case_key: str = "", to_said: str = "") -> dict:
    """One message posted as Rouh's bot - never as the person - and written down whole in the sent
    log like every other message Rouh sends. {"channel", "ts"}; SlackError when Slack refused it."""
    from . import sentlog

    # The boundary: what Rouh's bot posts names the owner of this connection, never a mark.
    body = to_mrkdwn(owner.say(text, str(conn.user_id or "") or None))
    if not body:
        raise ValueError("There is nothing to send.")
    client = bot(conn)
    ok, error, ts = True, "", ""
    try:
        got = client.call("chat.postMessage", channel=channel, text=body[:39000],
                          thread_ts=thread_ts or None, unfurl_links="false")
        ts = str(got.get("ts") or "")
        channel = str(got.get("channel") or channel)
    except SlackError as exc:
        ok, error = False, exc.error
        raise
    finally:
        sentlog.record(channel="slack", to=to_said or channel, text=body,
                       message_id=f"slack:{channel}:{ts}" if ts else "", case_key=case_key, kind=kind,
                       user_id=str(conn.user_id), org_id=str(conn.org_id), ok=ok, error=error)
    return {"channel": channel, "ts": ts}


def direct_channel(conn, slack_id: str) -> str:
    """Rouh's own direct message with somebody, opened if it is not yet."""
    got = bot(conn).call("conversations.open", users=slack_id).get("channel") or {}
    cid = str(got.get("id") or "")
    if cid:
        keep_conversation(conn, {**got, "is_im": True, "user": slack_id}, member=True)
    return cid


def join(conn, where: str) -> object:
    """Rouh's bot joins a public channel itself (`conversations.join`): only on the person's word."""
    conv = find_conversation(conn, where)
    if conv is None:
        found = [c for c in bot(conn).pages("conversations.list", "channels", types="public_channel",
                                            exclude_archived="true", limit=200)
                 if str(c.get("name") or "").lower() == str(where).lstrip("#").lower()]
        if not found:
            raise ValueError(f"There is no public channel called {where}.")
        conv = keep_conversation(conn, found[0])
    if conv.kind != "channel":
        raise ValueError(f"{conversation_label(conv)} is not a public channel: Rouh can only be invited "
                         "to a private one, by somebody in it.")
    got = bot(conn).call("conversations.join", channel=conv.channel_id).get("channel") or {}
    return keep_conversation(conn, {**got, "id": conv.channel_id, "is_member": True}, member=True)


# --- Synapse Master -------------------------------------------------------------------------

SOURCE = "slack"


def _writers(conn) -> dict[str, dict]:
    """Every member of the workspace Rouh keeps, by their Slack id: {name, email}, the first address of the
    contact they are tied to (`tie`), else the address Slack gives, else none."""
    from .models import SlackPerson

    out, contacts = {}, {}
    for p in SlackPerson.objects.filter(org_id=conn.org_id, team_id=conn.team_id):
        # The contact they are tied to first, so a member the owner linked to a contact by hand
        # (`synapse.aka`) is written as that contact whatever address their Slack profile gives.
        email = ""
        if p.contact_id and not p.is_bot:
            if p.contact_id not in contacts:
                contacts[p.contact_id] = _contact_address(conn, p.contact_id)
            email = contacts[p.contact_id]
        if not email and not p.is_bot:
            email = str(p.email or "").strip().lower()
        out[p.slack_id] = {"name": p.real_name or p.name, "email": email}
    return out


def _contact_address(conn, contact_id: str) -> str:
    try:
        from .synapse import people

        ds = _master(conn)
        ids = people.identities(people.home_id(ds), contact_id) if ds is not None else []
    except Exception:  # noqa: BLE001
        return ""
    return next((x["value"] for x in ids if x["type"] == "email"), "")


def _senders(rows, writers: dict) -> list[str]:
    """Who wrote in a day's messages, each once: "Tomasz Wiśniewski <tomasz@brightfield.example.com>" when Slack
    gives their address, so Synapse links the day to the contact that address is, else their name alone.
    Until 22 October 2026 it was the names alone, which Synapse took for one sender called by the whole
    list (`synapse.people.repair_list_people`)."""
    out: list[str] = []
    for r in rows:
        p = writers.get(r.author_id) or {}
        name = " ".join(str(p.get("name") or r.author_name or "").split())
        name = name.replace("<", "").replace(">", "").replace(",", " ").strip()
        email = p.get("email") or ""
        said = (f"{name} <{email}>" if name else email) if email else name
        if said and said not in out:
            out.append(said)
    return sorted(out)[:40]


def senders_of_days(user_id: str, org_id: str) -> dict[str, list[str]]:
    """Each Slack day's writers as `master_items` gives them now, by the day's key in Master."""
    return {one["source_key"]: one["from"] for one in master_items(user_id, org_id)}


def master_items(user_id: str, org_id: str) -> list[dict]:
    """Every kept conversation as Synapse Master keeps it: one item a day, each with every message
    of that day in order, readable by its owner only, and the person's own direct messages special."""
    from datetime import datetime

    from .models import SlackConversation, SlackMessage

    conn = connection(org_id)
    if conn is None or str(conn.user_id) != str(user_id):
        return []
    # The day a kept message belongs to, as the chats' days are (`synapse/master.py`): the
    # installation's own starting clock. It was one fixed zone, written here, until 20 October 2026.
    zone = clock.DEFAULT
    convs = {c.channel_id: c for c in SlackConversation.objects.filter(org_id=org_id, team_id=conn.team_id)}
    writers = _writers(conn)
    days: dict[tuple[str, str], list] = {}
    for r in SlackMessage.objects.filter(org_id=org_id, team_id=conn.team_id).order_by("at", "ts"):
        if r.channel_id not in convs:
            continue
        day = datetime.fromtimestamp(r.at, zone).date().isoformat()
        days.setdefault((r.channel_id, day), []).append(r)
    out = []
    for (cid, day), rows in sorted(days.items()):
        c = convs[cid]
        lines = []
        for r in rows:
            when = datetime.fromtimestamp(r.at, zone).strftime("%H:%M")
            who = r.author_name + (f" ({r.contact_name})" if r.contact_name and r.contact_name != r.author_name
                                   else "")
            text = r.text + (("\n[files: " + ", ".join(r.files) + "]") if r.files else "")
            lines.append(f"{when} {who}{' (in a thread)' if r.thread_ts and r.thread_ts != r.ts else ''}: {text}")
        text = "\n\n".join(lines)
        digest = hashlib.sha256(text.encode()).hexdigest()[:20]
        item = {"kind": "doc", "source": SOURCE, "source_key": f"slack:{conn.team_id}:{cid}:{day}",
                "title": f"Slack: {conversation_label(c)}, {day}"[:300], "text": text,
                "said_at": datetime.fromtimestamp(rows[0].at, zone).isoformat(),
                "messages": str(len(rows)),
                "from": _senders(rows, writers),
                "slack": {"team": conn.team_id, "workspace": conn.team_name, "channel": cid,
                          "conversation": conversation_label(c), "kind": c.kind, "day": day,
                          "private": bool(c.private), "digest": digest}}
        if c.private:
            item["sensitivity"] = "special"
        out.append(item)
    return out


__all__ = ["API", "BOT_EVENTS", "BOT_SCOPES", "Client", "IMPLICIT_USER_SCOPES", "NotSetUp", "PAGE", "Refused",
           "SENDER", "SlackError", "USER_EVENTS", "USER_SCOPES", "bot", "channels", "check", "connection", "conversation",
           "create_url", "find_conversation", "join", "keep_conversation", "keep_message", "manifest",
           "master_items", "on_slack", "person", "senders_of_days", "tie", "tie_all", "post_message", "public", "read", "remove", "save",
           "search", "status_line"]
