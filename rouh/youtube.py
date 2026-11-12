"""YouTube, for research: what was actually said in a video, and which videos exist.

Two halves, and they fail in different ways, so they are kept apart.

**Transcripts.** There is no official API for them. What there is, is the watch
page: YouTube builds it with a large blob of JSON called
``ytInitialPlayerResponse`` inlined in the HTML, and inside that blob is
``captions.playerCaptionsTracklistRenderer.captionTracks`` - one entry per
caption track, each with a ``baseUrl`` that serves the timed text. So getting a
transcript is: fetch the page, find the blob, pick a track, fetch the track,
parse it. That is :func:`fetch_transcript`, and it climbs a ladder.

  1. A plain HTTP request with a browser's user agent and a consent cookie.
     Fast, cheap, and the whole answer wherever YouTube is not suspicious.
  2. Still no browser: the same video asked for through the address YouTube
     gives the Android app's player, which is handed the same caption track
     with no proof-of-origin token on it. **This is what works from this
     server**, and it was found by measuring rather than by reading: from a
     datacentre address ``/api/timedtext`` answers 200 with an empty body to
     everything else, including a real Chromium and the video player's own
     request, and answers this one whole.
  3. A real headless Chromium, when both of those are turned away. YouTube's bot
     wall answers a plain request with a page that has no player response in
     it at all, or with a player response whose ``playabilityStatus`` says to
     sign in. A browser gets past that because it is one. The caption track is
     fetched *from inside the page*, with ``fetch``, so the request carries
     the page's own cookies and headers rather than ours.
  4. The page's own Show transcript button, when even a browser's fetch of the
     track comes back empty. The button is pressed and the panel is read,
     which is exactly what a person does. It costs precision: the panel prints
     when each line starts and not how long it lasts, and it chooses its own
     track rather than taking one, so which track it showed is decoded from
     the button's own parameters (:func:`panel_track`) rather than assumed.

Three different failures come back as three different answers, because "this
video has no subtitles" and "YouTube would not let us in" and "that video is
private" need three different sentences out loud:
:class:`NoTranscript`, :class:`Blocked` and :class:`NotAvailable`.

**Search.** This one does have an API, so it uses it: ``search.list`` for the
ids and ``videos.list`` for the duration and the view count, which
``search.list`` does not return. The key is ``YOUTUBE_API_KEY`` in the
environment, the same place every other secret on this machine comes from. It
costs 100 units of a 10,000 unit daily allowance per call, so running out is an
ordinary Tuesday and gets a sentence of its own rather than "search failed".
With no key at all there is a scrape of the results page, which is clearly
second best and says so in what it returns.

Everything here reads. Nothing signs in as anybody, nothing posts, and nothing
is written anywhere but the store it is handed (`rouh/youtube_store.py`, every
transcript Rouh has made, in its database) or a script's cache directory.
"""
from __future__ import annotations

import asyncio
import contextlib
import html as html_module
import importlib
import json
import logging
import os
import re
import shutil
import tempfile
import time
from dataclasses import dataclass, field
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx

log = logging.getLogger("rouh.youtube")

#: What a browser says it is. YouTube serves a different, thinner page to
#: anything that admits to being a script, and the thinner page has no player
#: response in it.
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
)

#: The two cookies that mean "the consent dialog has been answered". Without
#: them a request from a European address is redirected to consent.youtube.com
#: and never sees a watch page at all. They are not a login and carry nothing
#: about anybody: SOCS is the modern one, CONSENT the old one.
CONSENT_COOKIES = {"SOCS": "CAISAiAD", "CONSENT": "YES+cb.20210328-17-p0.en+FX+000"}

#: A voice turn is waiting on this, so it cannot take a minute.
CONNECT_SECONDS = 8.0
READ_SECONDS = 20.0
#: The browser fallback is slower by nature: a whole page, with its scripts.
BROWSER_SECONDS = 45.0

#: The ceiling on what one call puts into the conversation. A forty minute
#: video is around 40,000 characters of speech, which is most of a context
#: window spent on one answer, so it is cut and the cut is said out loud with
#: the timestamp to continue from.
DEFAULT_MAX_CHARS = 12_000
#: The most a caller may raise that to. Past this it is not a transcript in a
#: turn any more, it is a file.
CEILING_MAX_CHARS = 60_000

#: How many results a search may ask for, and what it gives unasked.
DEFAULT_RESULTS = 10
MAX_RESULTS = 25

#: How long a cached transcript is believed. A video's subtitles do change -
#: an auto track is replaced by a human one, an uploader fixes a name - but
#: not inside a fortnight, and the cache is what stops the same lecture being
#: fetched four times in one conversation.
CACHE_SECONDS = 14 * 24 * 3600

#: YouTube's Data API v3, or a stand-in's in a test world and the stack test
#: (`rouh/testing/fake_youtube.py`), so a search there never reaches YouTube.
YOUTUBE_API = os.environ.get("ROUH_YOUTUBE_API", "https://www.googleapis.com/youtube/v3").rstrip("/")


# ---------------------------------------------------------------------------
# What can go wrong, said apart
# ---------------------------------------------------------------------------


class YouTubeTrouble(RuntimeError):
    """Something went wrong and the message is safe to say out loud."""


class NotAVideo(YouTubeTrouble):
    """That was not a YouTube address and there was no video id in it."""


class NotAvailable(YouTubeTrouble):
    """The video is private, age-gated, removed, or was never there."""


class Blocked(YouTubeTrouble):
    """YouTube turned us away: a consent wall, a bot check, a rate limit."""


class NoTranscript(YouTubeTrouble):
    """The video is fine and really has no captions at all."""


class Unreachable(YouTubeTrouble):
    """The network did not answer. Nothing is known either way."""


class NoKey(YouTubeTrouble):
    """There is no YouTube API key: the owner adds one in Anatomy, Connections, Keys."""


class OutOfQuota(YouTubeTrouble):
    """The day's YouTube API allowance is spent."""


# ---------------------------------------------------------------------------
# Addresses
# ---------------------------------------------------------------------------

#: A video id is eleven characters of YouTube's own base64 alphabet. Anchored
#: everywhere it is used, because a looser pattern happily reads eleven
#: characters out of the middle of a channel name.
_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")

#: The forms that are a path rather than a query parameter: youtu.be/<id>,
#: /shorts/<id>, /live/<id>, /embed/<id>, /v/<id>.
_IN_PATH = re.compile(r"^/(?:shorts|live|embed|v|e)/([A-Za-z0-9_-]{11})")


def video_id(text: str) -> str:
    """The video id in whatever the person or the model handed over.

    Takes a bare id, a full watch URL with any number of extra parameters, a
    youtu.be short link, a /shorts/, /live/ or /embed/ link, with or without a
    ``?t=90`` on the end, with or without a scheme, and with or without ``www``
    or ``m`` in front of it. Raises :class:`NotAVideo` for anything else,
    rather than guessing: a wrong id is eleven characters of somebody else's
    video, and there is nothing in the answer that would say so.
    """
    raw = str(text or "").strip().strip("<>").strip()
    if not raw:
        raise NotAVideo("Say which video, as a YouTube address or a video id.")
    if _ID.match(raw):
        return raw
    with_scheme = raw if "//" in raw else "https://" + raw.lstrip("/")
    try:
        parts = urlsplit(with_scheme)
    except ValueError:
        raise NotAVideo(f"{raw[:120]!r} is not a YouTube address.") from None
    host = (parts.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    if host.startswith("m."):
        host = host[2:]
    if host not in {"youtube.com", "youtu.be", "youtube-nocookie.com",
                    "music.youtube.com", "youtube.googleapis.com"}:
        raise NotAVideo(f"{raw[:120]!r} is not a YouTube address.")
    # youtu.be/<id>: the whole path is the id.
    if host == "youtu.be":
        candidate = parts.path.strip("/").split("/")[0]
        if _ID.match(candidate):
            return candidate
        raise NotAVideo(f"There is no video id in {raw[:120]!r}.")
    found = _IN_PATH.match(parts.path)
    if found:
        return found.group(1)
    # The ordinary form, and the only one where the id is a query parameter.
    for key in ("v", "video_id"):
        for value in parse_qs(parts.query).get(key, []):
            if _ID.match(value.strip()):
                return value.strip()
    raise NotAVideo(f"There is no video id in {raw[:120]!r}.")


def watch_url(vid: str) -> str:
    return f"https://www.youtube.com/watch?v={vid}"


# ---------------------------------------------------------------------------
# Reading the watch page
# ---------------------------------------------------------------------------

#: Every way the page has been seen to introduce the blob. The brace matching
#: below does the rest, because the blob itself is megabytes of JSON with every
#: kind of nesting and no regular expression should be asked to find its end.
_PLAYER_MARKERS = (
    "ytInitialPlayerResponse = ",
    "ytInitialPlayerResponse=",
    '"ytInitialPlayerResponse":',
)

_DATA_MARKERS = (
    "ytInitialData = ",
    "ytInitialData=",
    'window["ytInitialData"] = ',
    '"ytInitialData":',
)


def _blob(html: str, markers) -> dict:
    """The first JSON object after any of these markers, matched by brace.

    Scanning for the closing brace rather than pattern-matching to it, because
    the object contains strings that contain braces, and strings that contain
    escaped quotes, and a pattern that gets that right is a JSON parser written
    badly. This is the parser's own job, so the scan only has to find where to
    stop.
    """
    for marker in markers:
        at = html.find(marker)
        while at != -1:
            start = html.find("{", at + len(marker))
            if start == -1:
                break
            end = _closing_brace(html, start)
            if end > start:
                try:
                    found = json.loads(html[start:end])
                except ValueError:
                    found = None
                if isinstance(found, dict) and found:
                    return found
            at = html.find(marker, at + len(marker))
    return {}


def _closing_brace(text: str, start: int) -> int:
    """One past the brace that closes the object opening at `start`."""
    depth = 0
    in_string = False
    escaped = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i + 1
    return -1


def player_response(html: str) -> dict:
    """The player response blob out of a watch page's HTML, or an empty dict."""
    return _blob(html or "", _PLAYER_MARKERS)


def initial_data(html: str) -> dict:
    """The other blob, which is what the page draws: search results live here."""
    return _blob(html or "", _DATA_MARKERS)


#: Where a wall lives, as opposed to a video.
_WALL_HOSTS = ("consent.youtube.com", "consent.google.com", "/sorry/index")

#: What a wall says, and only what a wall says. These are deliberately long
#: phrases rather than words. An ordinary watch page mentions consent in its
#: scripts and mentions signing in on every button, so a short pattern here
#: reports "YouTube blocked us" for every video on YouTube - which is a worse
#: failure than the one it is trying to catch, because it is always wrong and
#: always plausible.
_WALL_SIGNS = (
    'action="https://consent.youtube.com/save"',
    "sign in to confirm you",
    "confirm you\u2019re not a bot",
    "confirm you're not a bot",
    "unusual traffic from your computer",
    "our systems have detected unusual traffic",
)


def looks_blocked(html: str, final_url: str = "") -> str:
    """Why this page is a wall, in a sentence, or nothing if it is not one.

    Asked only once the page has turned out to have no player response in it.
    A page that has one is a video, whatever else is written on it, and this
    is not a second opinion on that.
    """
    where = (final_url or "").lower()
    for sign in _WALL_HOSTS:
        if sign in where:
            return ("YouTube answered with its consent page instead of the video, "
                    "which is what it does to a request it does not trust.")
    body = (html or "")[:400_000].lower()
    for sign in _WALL_SIGNS:
        if sign in body:
            if "consent" in sign:
                return ("YouTube answered with its consent page instead of the "
                        "video, which is what it does to a request it does not trust.")
            return "YouTube asked us to prove we are not a bot."
    return ""


def why_unplayable(player: dict) -> str:
    """Why YouTube will not play this, in its own words, or nothing.

    The distinction that matters: ``LOGIN_REQUIRED`` on an age-gated video is
    the video's problem, and ``LOGIN_REQUIRED`` with a bot check in the reason
    is ours, and the caller has to be able to tell them apart.
    """
    status = ((player or {}).get("playabilityStatus") or {})
    state = str(status.get("status") or "").upper()
    if state in ("", "OK"):
        return ""
    reason = str(status.get("reason") or "").strip()
    if not reason:
        sub = status.get("errorScreen") or {}
        reason = json.dumps(sub)[:200] if sub else state.replace("_", " ").lower()
    return reason


# ---------------------------------------------------------------------------
# Caption tracks
# ---------------------------------------------------------------------------


@dataclass
class Track:
    """One caption track offered by the page."""

    url: str
    language_code: str
    name: str
    generated: bool

    @property
    def described(self) -> str:
        kind = "auto-generated" if self.generated else "human-written"
        return f"{self.name or self.language_code} ({kind})"


def caption_tracks(player: dict) -> list[Track]:
    """Every caption track in a player response, in the order YouTube gave."""
    renderer = (((player or {}).get("captions") or {})
                .get("playerCaptionsTracklistRenderer") or {})
    out: list[Track] = []
    for raw in renderer.get("captionTracks") or []:
        url = str(raw.get("baseUrl") or "")
        if not url:
            continue
        name = raw.get("name") or {}
        said = str(name.get("simpleText") or "")
        if not said:
            said = "".join(str(run.get("text") or "") for run in name.get("runs") or [])
        out.append(Track(
            url=url,
            language_code=str(raw.get("languageCode") or ""),
            name=said.strip(),
            # "asr" is automatic speech recognition, which is YouTube's own
            # machine listening to the video. vssId starting "a." says the
            # same thing on pages that leave `kind` out.
            generated=(str(raw.get("kind") or "").lower() == "asr"
                       or str(raw.get("vssId") or "").startswith("a.")),
        ))
    return out


def pick_track(tracks, want: str = "") -> Track:
    """Which track to read, in the order the house rule says.

    A language that was asked for wins outright, and a human-written track in
    that language beats an automatic one. Unasked, the order is: human English,
    automatic English, any human track, any automatic track. English first
    because that is the language the answer will be spoken in and a machine
    translation of a machine transcription is two guesses stacked.

    Raises :class:`NoTranscript` when there are no tracks at all, and when a
    language was asked for and is not among them, which is a different thing
    and says so.
    """
    tracks = list(tracks or [])
    if not tracks:
        raise NoTranscript("this video has no transcript")
    want = str(want or "").strip().lower()
    if want:
        # "en" matches "en", "en-GB" and "en-US"; "en-GB" matches only itself
        # and then falls back to the bare language.
        wanted = [t for t in tracks if t.language_code.lower() == want]
        if not wanted:
            wanted = [t for t in tracks
                      if t.language_code.lower().split("-")[0] == want.split("-")[0]]
        if not wanted:
            offered = ", ".join(sorted({t.language_code or "?" for t in tracks}))
            raise NoTranscript(
                f"this video has no transcript in {want}. It has: {offered}")
        tracks = wanted
    for test in (lambda t: not t.generated and _is_english(t),
                 lambda t: _is_english(t),
                 lambda t: not t.generated,
                 lambda t: True):
        for track in tracks:
            if test(track):
                return track
    raise NoTranscript("this video has no transcript")


def _is_english(track: Track) -> bool:
    return track.language_code.lower().split("-")[0] == "en"


def timedtext_url(url: str, fmt: str = "json3") -> str:
    """The same track address, asked for in one particular format."""
    parts = urlsplit(url)
    query = parse_qs(parts.query, keep_blank_values=True)
    query["fmt"] = [fmt]
    flat = urlencode({k: v[-1] for k, v in query.items()})
    return f"{parts.scheme}://{parts.netloc}{parts.path}?{flat}"


# ---------------------------------------------------------------------------
# Which track the page's own transcript panel is showing
# ---------------------------------------------------------------------------
#
# The panel is opened by a button and filled by YouTube itself, so nothing here
# chooses its track. What there is, is the `params` on the page's own
# `getTranscriptEndpoint`, which says which track the button will fetch. It is
# base64 of a small protocol buffer, and inside it, base64 again, is a second
# one holding two fields: the kind ("asr" for YouTube's machine listening, empty
# for a track a person typed) and the language code.
#
# Twenty lines of protocol buffer reader rather than a dependency, because two
# string fields is all that is ever read and the alternative is reporting
# somebody's Portuguese transcript as English.


def _varint(data: bytes, at: int):
    """One base-128 varint, and where it ended."""
    value, shift = 0, 0
    while at < len(data):
        byte = data[at]
        at += 1
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value, at
        shift += 7
        if shift > 63:
            break
    return None, at


def protobuf_fields(data: bytes) -> dict:
    """Field number to list of values, for a message of strings and numbers."""
    out: dict[int, list] = {}
    at = 0
    while at < len(data):
        key, at = _varint(data, at)
        if key is None:
            break
        field, wire = key >> 3, key & 7
        if wire == 0:
            value, at = _varint(data, at)
            if value is None:
                break
        elif wire == 2:
            length, at = _varint(data, at)
            if length is None or at + length > len(data):
                break
            value, at = data[at:at + length], at + length
        elif wire == 5:
            value, at = data[at:at + 4], at + 4
        elif wire == 1:
            value, at = data[at:at + 8], at + 8
        else:
            break
        out.setdefault(field, []).append(value)
    return out


def _unbase64(text) -> bytes:
    """Base64 in either alphabet, with the padding YouTube leaves off."""
    import base64
    from urllib.parse import unquote

    raw = text.decode("utf-8", "ignore") if isinstance(text, bytes) else str(text or "")
    raw = unquote(raw).strip()
    raw += "=" * (-len(raw) % 4)
    try:
        return base64.urlsafe_b64decode(raw)
    except Exception:
        try:
            return base64.b64decode(raw)
        except Exception:
            return b""


def panel_track(params: str) -> tuple[str, bool]:
    """(language code, auto-generated) for the track the panel will show.

    Empty strings when the blob cannot be read, which is a signal to fall back
    to the first caption track rather than to claim a language.
    """
    outer = protobuf_fields(_unbase64(params))
    nested = (outer.get(2) or [b""])[0]
    inner = protobuf_fields(_unbase64(nested))
    kind = ((inner.get(1) or [b""])[0] or b"").decode("utf-8", "ignore")
    language = ((inner.get(2) or [b""])[0] or b"").decode("utf-8", "ignore")
    return language, kind.lower() == "asr"


# ---------------------------------------------------------------------------
# The two caption formats
# ---------------------------------------------------------------------------


@dataclass
class Cue:
    """One line of speech, and when it was said."""

    start: float
    duration: float
    text: str


def parse_captions(body: str) -> list[Cue]:
    """Cues out of a caption track, whichever of the two formats it is in.

    ``fmt=json3`` is what is asked for and what usually comes back; the old XML
    is what comes back when the ``fmt`` parameter is dropped on the way, which
    happens, so both are read rather than one being assumed.
    """
    text = (body or "").strip()
    if not text:
        return []
    if text[0] == "{":
        return parse_json3(text)
    return parse_xml(text)


def parse_json3(body: str) -> list[Cue]:
    """The JSON format: events, each with segments, each with a piece of text.

    An event with no ``segs`` is a formatting marker rather than speech, and an
    event whose segments are all whitespace is the gap between two sentences.
    Both are dropped: they are not lines, and left in they double the length of
    an automatic transcript with blanks.
    """
    try:
        found = json.loads(body)
    except ValueError:
        return []
    out: list[Cue] = []
    for event in (found or {}).get("events") or []:
        cue = _json3_cue(event)
        if cue is not None:
            out.append(cue)
    return out


def _json3_cue(event: dict) -> Cue | None:
    """One event's speech and millisecond timing, or no cue for a gap."""
    pieces = [str(seg.get("utf8") or "") for seg in event.get("segs") or []]
    said = "".join(pieces).replace("\n", " ").strip()
    if not said:
        return None
    return Cue(
        start=float(event.get("tStartMs") or 0) / 1000.0,
        duration=float(event.get("dDurationMs") or 0) / 1000.0,
        text=_tidy(said),
    )


_TEXT_TAG = re.compile(
    r"<text\b([^>]*)>(.*?)</text>", re.DOTALL | re.IGNORECASE)
_ATTR = re.compile(r'([a-zA-Z_:][-\w:.]*)\s*=\s*"([^"]*)"')


def parse_xml(body: str) -> list[Cue]:
    """The old format: ``<text start="0.5" dur="2.1">what was said</text>``.

    Entities are unescaped twice on purpose. YouTube escapes the caption text
    once for the XML and the caption text itself often already holds an escaped
    apostrophe, so a single pass leaves ``&amp;#39;`` on the screen where the
    word "don't" belongs.
    """
    out: list[Cue] = []
    for attrs, inner in _TEXT_TAG.findall(body or ""):
        cue = _xml_cue(attrs, inner)
        if cue is not None:
            out.append(cue)
    return out


def _xml_cue(attrs: str, inner: str) -> Cue | None:
    """One text node, with XML's entity cleanup and forgiving timing."""
    found = dict(_ATTR.findall(attrs))
    said = html_module.unescape(html_module.unescape(inner))
    said = re.sub(r"<[^>]+>", "", said)
    said = _tidy(said.replace("\n", " "))
    if not said:
        return None
    return Cue(
        start=_float(found.get("start") or found.get("t"), 0.0),
        duration=_float(found.get("dur") or found.get("d"), 0.0),
        text=said,
    )


def _tidy(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _float(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# Times, in and out
# ---------------------------------------------------------------------------

_HMS = re.compile(r"^(?:(\d+):)?(\d{1,2}):(\d{1,2}(?:\.\d+)?)$")
_UNITS = re.compile(r"^(?:(\d+)h)?(?:(\d+)m)?(?:(\d+(?:\.\d+)?)s?)?$", re.IGNORECASE)


def seconds_of(value) -> float | None:
    """A time the model might write, in seconds. None when it wrote nothing.

    Takes 90, "90", "1:30", "01:02:03" and "1h2m3s", because all four turn up:
    the first two from arithmetic, the middle two from a YouTube timestamp read
    off the screen, and the last from a ``?t=`` in a link.
    """
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return max(0.0, float(value))
    raw = str(value).strip().lower()
    if not raw:
        return None
    found = _HMS.match(raw)
    if found:
        hours = int(found.group(1) or 0)
        return float(hours * 3600 + int(found.group(2)) * 60 + float(found.group(3)))
    if raw.replace(".", "", 1).isdigit():
        return max(0.0, float(raw))
    found = _UNITS.match(raw)
    if found and any(found.groups()):
        return float(int(found.group(1) or 0) * 3600
                     + int(found.group(2) or 0) * 60
                     + float(found.group(3) or 0))
    return None


def clock(seconds: float) -> str:
    """Seconds as a timestamp a person would read: 2:05, or 1:02:05."""
    total = int(max(0.0, float(seconds or 0)))
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def _day(at: float) -> str:
    """"22 October 2026", for saying when something was made."""
    day = time.localtime(at)
    return f"{day.tm_mday} {time.strftime('%B %Y', day)}"


def minutes_words(seconds: float) -> str:
    """"about 42 minutes", for saying how long something is."""
    total = float(seconds or 0)
    if total <= 0:
        return "unknown length"
    if total < 90:
        return f"{int(round(total))} seconds"
    if total < 3600:
        return f"{int(round(total / 60))} minutes"
    hours = total / 3600.0
    if abs(hours - round(hours)) < 0.05:
        whole = int(round(hours))
        return f"{whole} hour" if whole == 1 else f"{whole} hours"
    return f"{hours:.1f} hours"


# ---------------------------------------------------------------------------
# A transcript, whole
# ---------------------------------------------------------------------------


@dataclass
class Transcript:
    """Everything one call got back about one video."""

    video_id: str
    title: str = ""
    channel: str = ""
    duration: float = 0.0
    published: str = ""
    description: str = ""
    views: str = ""
    language_code: str = ""
    language_name: str = ""
    generated: bool = False
    cues: list = field(default_factory=list)
    #: How it was got: "http", "phone", "browser", "panel", "cache" or "stored"
    #: (Rouh's database, `rouh/youtube_store.py`). Said in the result, because
    #: a transcript from the cache is a transcript from some minutes ago and one
    #: read off the page's own panel has start times but no line lengths, and
    #: the model should be able to say so if it matters.
    how: str = "http"
    #: When a stored transcript was first made, as a timestamp; 0 otherwise.
    stored_at: float = 0.0

    @property
    def url(self) -> str:
        return watch_url(self.video_id)

    @property
    def text(self) -> str:
        return " ".join(cue.text for cue in self.cues)

    @property
    def spoken_length(self) -> float:
        """How far into the video the last thing said is."""
        if not self.cues:
            return 0.0
        last = self.cues[-1]
        return last.start + max(0.0, last.duration)

    def as_dict(self) -> dict:
        out = {k: getattr(self, k) for k in
               ("video_id", "title", "channel", "duration", "published",
                "description", "views", "language_code", "language_name",
                "generated", "how")}
        out["cues"] = [{"start": c.start, "duration": c.duration, "text": c.text}
                       for c in self.cues]
        return out

    @classmethod
    def from_dict(cls, raw: dict) -> "Transcript":
        raw = dict(raw or {})
        cues = [Cue(start=_float(c.get("start")), duration=_float(c.get("duration")),
                    text=str(c.get("text") or ""))
                for c in raw.pop("cues", []) or []]
        known = {k: raw.get(k) for k in
                 ("video_id", "title", "channel", "published", "description",
                  "views", "language_code", "language_name", "how")}
        return cls(
            video_id=str(known["video_id"] or ""),
            title=str(known["title"] or ""),
            channel=str(known["channel"] or ""),
            duration=_float(raw.get("duration")),
            published=str(known["published"] or ""),
            description=str(known["description"] or ""),
            views=str(known["views"] or ""),
            language_code=str(known["language_code"] or ""),
            language_name=str(known["language_name"] or ""),
            generated=bool(raw.get("generated")),
            cues=cues,
            how=str(known["how"] or "http"),
        )


def details_of(player: dict) -> dict:
    """Title, channel, length, publish date and description, out of the blob."""
    details = (player or {}).get("videoDetails") or {}
    micro = (((player or {}).get("microformat") or {})
             .get("playerMicroformatRenderer") or {})
    published = str(micro.get("publishDate") or micro.get("uploadDate") or "")
    description = str(details.get("shortDescription") or "")
    if not description:
        described = micro.get("description") or {}
        description = str(described.get("simpleText") or "")
    return {
        "video_id": str(details.get("videoId") or ""),
        "title": str(details.get("title") or
                     (micro.get("title") or {}).get("simpleText") or ""),
        "channel": str(details.get("author") or micro.get("ownerChannelName") or ""),
        "duration": _float(details.get("lengthSeconds") or micro.get("lengthSeconds")),
        "published": published[:10],
        "description": description,
        "views": str(details.get("viewCount") or micro.get("viewCount") or ""),
    }


# ---------------------------------------------------------------------------
# Getting one, the plain way
# ---------------------------------------------------------------------------


def _client(client_factory=None) -> httpx.AsyncClient:
    if client_factory is not None:
        return client_factory()
    return httpx.AsyncClient(
        timeout=httpx.Timeout(READ_SECONDS, connect=CONNECT_SECONDS),
        follow_redirects=True,
        headers={
            "User-Agent": USER_AGENT,
            "Accept-Language": "en-US,en;q=0.9",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
        cookies=CONSENT_COOKIES,
    )


#: YouTube's own public InnerTube key, which is in the source of every watch
#: page. Read off the page when it is there and used from here when it is not;
#: it is a constant, not a secret, and it identifies nobody.
PUBLIC_INNERTUBE_KEY = "AIzaSyAO_FJ2SlqU8Q4STEHLGCilw_Y9_11qcW8"

_API_KEY = re.compile(r'"INNERTUBE_API_KEY"\s*:\s*"([A-Za-z0-9_\-]{20,})"')

#: The phone's client, for the request that actually gets the captions here.
#:
#: This is the piece that was found by measuring rather than by reading. From
#: this server YouTube answers `/api/timedtext` with 200 and an empty body -
#: to a plain request, to a real Chromium's request, and to the video player's
#: own request with its proof-of-origin token attached. The same caption track,
#: asked for through the address the Android app's player is given, comes back
#: whole: 125 kilobytes of JSON for a one hour talk. So the watch page is still
#: asked first, because it is the page the brief is written about and it is
#: where the title, the channel and the publish date are, and this is asked
#: second, for the captions alone.
PHONE_CLIENT = {
    "clientName": "ANDROID",
    "clientVersion": "20.10.38",
    "androidSdkVersion": 30,
    "userAgent": ("com.google.android.youtube/20.10.38 (Linux; U; Android 11) gzip"),
    "hl": "en",
}

INNERTUBE_PLAYER = "https://www.youtube.com/youtubei/v1/player"


def innertube_key(html: str) -> str:
    """The key this watch page uses, or YouTube's public one."""
    found = _API_KEY.search(html or "")
    return found.group(1) if found else PUBLIC_INNERTUBE_KEY


async def over_http(vid: str, want_language: str = "", *, client_factory=None) -> Transcript:
    """Strategy one: everything that can be done without starting a browser.

    Two goes at the captions, in one session. The watch page first, which is
    where the title, the channel, the length and the publish date live and
    where the caption tracks are listed. Then, if the track it names is served
    empty - which is what this server gets, every time, and is not an error
    anybody is told about - the phone's player, which is handed the same track
    at an address with no proof-of-origin token on it.

    Raises :class:`Blocked` for a wall, :class:`NotAvailable` for a video that
    is not there or not ours to see, :class:`NoTranscript` when the video
    genuinely has no captions, and :class:`Unreachable` when nothing answered.
    """
    async with _client(client_factory) as http:
        html = await _watch_html(http, vid)
        player = player_response(html)
        if player:
            refused = why_unplayable(player)
            if refused:
                raise _from_reason(refused)

        # `served_empty` is the difference between "there are no captions" and
        # "we were not given the captions there are", and the whole reason
        # both are tracked rather than one boolean.
        served_empty = False
        no_captions: NoTranscript | None = None

        if player:
            try:
                track = pick_track(caption_tracks(player), want_language)
            except NoTranscript as exc:
                no_captions = exc
            else:
                cues = await _caption_cues(http, track, vid)
                if cues:
                    return _assemble(player, track, cues, "http")
                served_empty = True

        phone = await _phone_player(http, vid, innertube_key(html))
        if phone:
            if not player:
                refused = why_unplayable(phone)
                if refused:
                    raise _from_reason(refused)
            try:
                track = pick_track(caption_tracks(phone), want_language)
            except NoTranscript as exc:
                no_captions = no_captions or exc
            else:
                cues = await _caption_cues(http, track, vid)
                if cues:
                    # The watch page's details when there are any, because the
                    # phone's player response has no publish date in it.
                    return _assemble(player or phone, track, cues, "phone")
                served_empty = True

    if no_captions is not None and not served_empty:
        raise no_captions
    if not player and not phone:
        raise Blocked(
            looks_blocked(html) or
            "YouTube served a page with no player data in it, and its phone player "
            "answered with nothing either, which is what it does to a machine it "
            "does not trust.")
    raise Blocked(
        "YouTube listed a caption track and then served it empty - to the watch "
        "page and to the phone player alike - which is how its bot check refuses "
        "this machine.")


async def _watch_html(http, vid: str) -> str:
    """The watch page, or an empty string if it was a wall rather than a page.

    A wall is not raised on here. The phone's player is asked next and does not
    need the page at all, so a page that came back as a consent screen is worth
    carrying on from; only a network that did not answer ends the attempt.
    """
    try:
        page = await http.get(watch_url(vid))
    except httpx.HTTPError as exc:
        raise Unreachable(f"YouTube did not answer ({type(exc).__name__}).") from None
    if page.status_code == 429:
        raise Blocked("YouTube answered 429: too many requests from this machine.")
    if page.status_code >= 400:
        raise Blocked(f"YouTube answered {page.status_code} for that watch page.")
    return page.text


async def _caption_cues(http, track: Track, vid: str) -> list:
    """One caption track, parsed. An empty list for every way of not getting it.

    Empty rather than raised because an empty track is the ordinary case here
    and the caller has another way to try; what it means is decided once, by
    the caller, when every way has been tried.
    """
    try:
        answer = await http.get(timedtext_url(track.url),
                                headers={"Referer": watch_url(vid)})
    except httpx.HTTPError:
        return []
    if answer.status_code >= 400:
        return []
    return parse_captions(answer.text)


async def _phone_player(http, vid: str, key: str) -> dict:
    """The player response the Android app is given. An empty dict if refused."""
    try:
        answer = await http.post(
            f"{INNERTUBE_PLAYER}?key={key}&prettyPrint=false",
            json={"context": {"client": dict(PHONE_CLIENT)}, "videoId": vid,
                  "contentCheckOk": True, "racyCheckOk": True},
            headers={"Content-Type": "application/json",
                     "User-Agent": PHONE_CLIENT["userAgent"],
                     "X-Goog-Api-Format-Version": "2"},
        )
    except httpx.HTTPError:
        return {}
    if answer.status_code >= 400:
        return {}
    try:
        found = answer.json()
    except ValueError:
        return {}
    return found if isinstance(found, dict) else {}


def _from_reason(reason: str) -> YouTubeTrouble:
    """YouTube's own refusal, sorted into ours or the video's.

    The same status means both things. "Sign in to confirm you are not a bot"
    is YouTube refusing this machine; "Sign in to confirm your age" is the
    video being gated. They need different sentences and the only thing that
    tells them apart is the wording.
    """
    said = (reason or "").lower()
    if "bot" in said or "unusual traffic" in said:
        return Blocked(f"YouTube refused us: {reason}")
    return NotAvailable(f"YouTube will not play that video: {reason}")


def _assemble(player: dict, track: Track, cues, how: str) -> Transcript:
    found = details_of(player)
    return Transcript(
        video_id=str(found["video_id"] or ""),
        title=found["title"],
        channel=found["channel"],
        duration=found["duration"],
        published=found["published"],
        description=found["description"],
        views=found["views"],
        language_code=track.language_code,
        language_name=track.name or track.language_code,
        generated=track.generated,
        cues=list(cues),
        how=how,
    )


# ---------------------------------------------------------------------------
# Getting one with a real browser
# ---------------------------------------------------------------------------

#: Read inside the page. `fetch` there carries the page's own cookies and
#: headers, which is the first thing to try once there is a real browser: on a
#: network YouTube is not suspicious of, this is the whole of the fallback.
_FETCH_IN_PAGE = """
async (url) => {
  const answer = await fetch(url, {credentials: 'include'});
  return {status: answer.status, body: await answer.text()};
}
"""

#: Four fields of the player response, not the whole thing. A player response
#: is megabytes of stream manifests and advertising configuration, all of which
#: would be serialised across the bridge out of the browser and thrown away
#: here; these four are everything this module reads.
_PLAYER_IN_PAGE = """
() => {
  const p = window.ytInitialPlayerResponse;
  if (!p) return null;
  return {
    playabilityStatus: p.playabilityStatus || null,
    videoDetails: p.videoDetails || null,
    microformat: p.microformat || null,
    captions: p.captions || null
  };
}
"""

#: The `params` the page's own Show transcript button carries, which says which
#: track the panel is about to fetch. Hunted for rather than read off a path,
#: because YouTube moves the panel about in the data and a path that is one key
#: out returns nothing and says nothing about why.
_PANEL_PARAMS = """
() => {
  let found = null;
  const walk = (node, depth) => {
    if (!node || found || depth > 25) return;
    if (Array.isArray(node)) { node.forEach(x => walk(x, depth + 1)); return; }
    if (typeof node === 'object') {
      if (node.getTranscriptEndpoint && node.getTranscriptEndpoint.params) {
        found = node.getTranscriptEndpoint.params; return;
      }
      for (const key in node) walk(node[key], depth + 1);
    }
  };
  walk(window.ytInitialData, 0);
  return found;
}
"""

#: Press the page's own Show transcript button. Pressed through the DOM rather
#: than with a real pointer because YouTube puts an overlay in front of
#: everything on a first visit and a pointer click waits thirty seconds for it
#: to go away. Nothing on this page is being tested; the button is a way in.
_OPEN_PANEL = """
() => {
  const wanted = Array.from(document.querySelectorAll('button')).find(
    b => /show transcript/i.test((b.getAttribute('aria-label') || '') + ' ' + (b.innerText || '')));
  if (!wanted) return false;
  wanted.click();
  return true;
}
"""

#: One line per segment: the timestamp as it is written on screen, and what was
#: said. This is the panel a person reads, read the same way.
_READ_PANEL = """
() => Array.from(document.querySelectorAll('transcript-segment-view-model')).map(s => {
  const stamp = s.querySelector('[class*="Timestamp"]:not([class*="A11y"])');
  const said = s.querySelector('[role="text"]');
  return [stamp ? stamp.innerText.trim() : '', said ? said.innerText.trim() : ''];
})
"""

#: The panel loads more of itself as it is scrolled on a long video, so it is
#: scrolled to the bottom until it stops growing.
_SCROLL_PANEL = """
() => {
  const panel = document.querySelector(
    'ytd-engagement-panel-section-list-renderer[target-id*="transcript"]');
  if (!panel) return false;
  const box = panel.querySelector('#content') || panel;
  box.scrollTop = box.scrollHeight;
  window.scrollBy(0, 400);
  return true;
}
"""

#: How long the panel is given to fill, and how long the button is waited for.
_PANEL_TRIES = 20
_PANEL_WAIT_MS = 700


async def over_browser(vid: str, want_language: str = "", *,
                       browsers_path: str = "") -> Transcript:
    """Strategy two: a real headless Chromium, with a profile of its own.

    The profile is a fresh temporary directory, thrown away at the end. That is
    not tidiness: several jobs share this machine and two Chromiums pointed at
    one profile directory corrupt it, so nothing here may ever reach for a
    shared one.

    Raises :class:`Unreachable` when Playwright or its browser is not installed
    here, which is a thing the caller has to be able to say plainly rather than
    a stack trace in a voice turn.
    """
    # Asked for here, before a temporary directory is made, so a machine with
    # no Playwright on it says one sentence rather than raising out of the
    # middle of a voice turn. Imported rather than looked up, because the
    # question is whether it can be imported.
    try:
        importlib.import_module("playwright.async_api")
    except ImportError:
        raise Unreachable(
            "the headless browser is not installed for Rouh on this machine, so "
            "there is no way past YouTube's bot check here") from None
    if browsers_path:
        os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", browsers_path)
    profile = tempfile.mkdtemp(prefix="rouh-youtube-")
    try:
        return await asyncio.wait_for(
            _drive_browser(vid, want_language, profile), BROWSER_SECONDS + 30)
    except asyncio.TimeoutError:
        raise Unreachable("the headless browser did not finish in time") from None
    finally:
        shutil.rmtree(profile, ignore_errors=True)


async def _drive_browser(vid: str, want_language: str, profile: str) -> Transcript:
    from playwright.async_api import Error as PlaywrightError
    from playwright.async_api import async_playwright

    from .browsing import CannotBrowse, chromium, remote

    async with async_playwright() as driver:
        browser = None
        try:
            if remote():
                # In the containers: a connection to the browser container, whose
                # contexts are each a profile of their own, in memory, and nobody
                # else's (`browsing.chromium`).
                browser = await chromium(driver)
                context = await browser.new_context(
                    user_agent=USER_AGENT, locale="en-US",
                    viewport={"width": 1400, "height": 1000})
            else:
                # A persistent context pointed at a directory made a moment ago,
                # rather than `launch`, so the profile this uses is named here and
                # is provably nobody else's. Rouh runs as root on a machine where
                # the crew and every run of the one program drive their own
                # browsers, and two Chromiums in one profile directory corrupt it.
                context = await driver.chromium.launch_persistent_context(
                    profile,
                    headless=True,
                    user_agent=USER_AGENT,
                    locale="en-US",
                    viewport={"width": 1400, "height": 1000},
                    args=["--no-sandbox", "--disable-dev-shm-usage",
                          "--disable-blink-features=AutomationControlled"],
                )
        except (PlaywrightError, CannotBrowse) as exc:
            if browser is not None:
                with contextlib.suppress(Exception):
                    await browser.close()
            raise Unreachable(
                "the headless browser would not start here "
                f"({str(exc).splitlines()[0][:160]})") from None
        try:
            await context.add_cookies([
                {"name": name, "value": value, "domain": ".youtube.com", "path": "/"}
                for name, value in CONSENT_COOKIES.items()])
            page = context.pages[0] if context.pages else await context.new_page()
            answer = await page.goto(watch_url(vid),
                                     wait_until="domcontentloaded",
                                     timeout=BROWSER_SECONDS * 1000)
            if answer is not None and answer.status >= 400:
                raise Blocked(f"YouTube answered {answer.status} in the browser too.")
            player = await page.evaluate(_PLAYER_IN_PAGE)
            if not isinstance(player, dict) or not player:
                player = player_response(await page.content())
            if not player:
                raise Blocked(
                    looks_blocked(await page.content(), page.url) or
                    "even in a real browser that page had no player data in it.")
            trouble = why_unplayable(player)
            if trouble:
                raise _from_reason(trouble)
            tracks = caption_tracks(player)
            # No tracks means no captions, in any browser. Said here rather
            # than after twenty seconds of waiting for a panel that will never
            # fill, which is the same answer half a minute later.
            track = pick_track(tracks, want_language)

            # The track's own address first. It costs one request and on a
            # network YouTube is not suspicious of it is the whole answer,
            # with the exact language and the exact timings.
            got = await page.evaluate(_FETCH_IN_PAGE, timedtext_url(track.url))
            cues = parse_captions(str((got or {}).get("body") or ""))
            if cues:
                return _assemble(player, track, cues, "browser")

            # It came back empty, which is how YouTube refuses a caption track
            # to a machine it does not like even inside a real browser. So do
            # what a person does: press Show transcript and read the panel.
            return await _read_panel(page, player, tracks, want_language)
        finally:
            await context.close()
            if browser is not None:
                with contextlib.suppress(Exception):
                    await browser.close()


async def _read_panel(page, player: dict, tracks, want_language: str) -> Transcript:
    """Open the page's own transcript panel and read what is in it.

    This is the last way in and it is the most honest one: it is the feature
    YouTube offers a person on that page, used the way a person uses it. What
    it costs is precision - the panel gives the time each line starts and not
    how long it lasts, so a line's length is taken as the gap to the next one.
    """
    opened = False
    for _ in range(_PANEL_TRIES):
        opened = bool(await page.evaluate(_OPEN_PANEL))
        if opened:
            break
        await page.wait_for_timeout(500)
    if not opened:
        raise Blocked(
            "YouTube served the caption track empty and its own Show transcript "
            "button was not on the page either")

    rows = []
    for _ in range(_PANEL_TRIES):
        await page.wait_for_timeout(_PANEL_WAIT_MS)
        rows = await page.evaluate(_READ_PANEL)
        if rows:
            break
    if not rows:
        raise Blocked(
            "YouTube served the caption track empty and then left its own "
            "transcript panel empty as well")
    # A long video fills its panel as it is scrolled, so it is scrolled until
    # it stops growing rather than trusted to have arrived whole.
    for _ in range(40):
        await page.evaluate(_SCROLL_PANEL)
        await page.wait_for_timeout(350)
        more = await page.evaluate(_READ_PANEL)
        if len(more) <= len(rows):
            rows = more or rows
            break
        rows = more

    cues = cues_from_panel(rows)
    if not cues:
        raise NoTranscript("this video has no transcript")

    # Which track the panel showed, from the button's own parameters, and the
    # first caption track only if those cannot be read. Never the track
    # `pick_track` would have chosen: the panel chooses for itself, and saying
    # English over somebody's Portuguese is the one mistake here that is
    # invisible in the answer.
    language, generated = panel_track(await page.evaluate(_PANEL_PARAMS) or "")
    shown = _track_named(tracks, language, generated)
    if want_language and shown.language_code and not _same_language(
            shown.language_code, want_language):
        offered = ", ".join(sorted({t.language_code or "?" for t in tracks}))
        raise NoTranscript(
            f"YouTube would only give us the {shown.language_code} transcript for "
            f"this video, not {want_language}. It lists: {offered}")
    return _assemble(player, shown, cues, "panel")


def cues_from_panel(rows) -> list[Cue]:
    """Panel rows - a timestamp and a line - as cues with a length each."""
    out: list[Cue] = []
    for stamp, said in rows or []:
        at = seconds_of(stamp)
        said = _tidy(str(said or ""))
        if at is None or not said:
            continue
        if out:
            out[-1].duration = max(0.0, at - out[-1].start)
        out.append(Cue(start=at, duration=0.0, text=said))
    if out:
        # The last line has no next line to measure against. Four seconds is
        # the median length of a caption line and is only ever used to say how
        # far into the video the speech runs.
        out[-1].duration = 4.0
    return out


def _same_language(code: str, want: str) -> bool:
    return (str(code or "").lower().split("-")[0]
            == str(want or "").lower().split("-")[0])


def _track_named(tracks, language: str, generated: bool) -> Track:
    """The track in the list that matches what the panel said it was showing."""
    for track in tracks or []:
        if (_same_language(track.language_code, language)
                and track.generated == generated):
            return track
    for track in tracks or []:
        if _same_language(track.language_code, language):
            return track
    if tracks:
        return tracks[0]
    return Track(url="", language_code=language, name=language, generated=generated)


# ---------------------------------------------------------------------------
# The cache
# ---------------------------------------------------------------------------


def cache_path(directory: str, vid: str, want_language: str) -> str:
    """One file per video and per language asked for.

    Keyed on what was asked for rather than on what came back, because the
    question "the best track you can find" and the question "the German one"
    have different right answers for one video and a cache that cannot tell
    them apart answers the second with the first.
    """
    which = re.sub(r"[^a-z0-9-]", "", str(want_language or "").lower()) or "best"
    return os.path.join(directory, f"{vid}.{which}.json")


def read_cache(directory: str, vid: str, want_language: str) -> Transcript | None:
    """A transcript fetched earlier, if there is a fresh one. Never raises."""
    if not directory:
        return None
    where = cache_path(directory, vid, want_language)
    try:
        if time.time() - os.path.getmtime(where) > CACHE_SECONDS:
            return None
        with open(where, "r", encoding="utf-8") as fh:
            found = Transcript.from_dict(json.load(fh))
    except (OSError, ValueError):
        return None
    if not found.cues:
        return None
    found.how = "cache"
    return found


def write_cache(directory: str, vid: str, want_language: str, found: Transcript) -> None:
    """Keep it for next time. A cache that cannot be written is not an error."""
    if not directory or not found.cues:
        return
    where = cache_path(directory, vid, want_language)
    try:
        os.makedirs(directory, exist_ok=True)
        # Written beside and moved into place, so a turn that is cut off half
        # way through writing leaves no half a transcript for the next one to
        # read back as the whole of a video.
        handle, temporary = tempfile.mkstemp(dir=directory, suffix=".part")
        with os.fdopen(handle, "w", encoding="utf-8") as fh:
            json.dump(found.as_dict(), fh, ensure_ascii=False)
        os.replace(temporary, where)
    except (OSError, ValueError):
        log.debug("could not cache the transcript for %s", vid, exc_info=True)


# ---------------------------------------------------------------------------
# The whole of getting a transcript
# ---------------------------------------------------------------------------


async def fetch_transcript(video: str, *, language: str = "", cache_dir: str = "",
                           store=None, use_browser: bool = True, browsers_path: str = "",
                           client_factory=None) -> Transcript:
    """A transcript, from the store, then plain HTTP, then a real browser.

    `store` is Rouh's database of every video already transcribed
    (`rouh/youtube_store.py`): asked first, with ``await store.find(vid,
    language)``, and given what was got with ``await store.keep(vid, language,
    found)``. A script that loads this file without Django passes `cache_dir`
    instead, a directory of files kept for `CACHE_SECONDS`.

    The fallback is only tried for the failures a browser can actually fix. A
    video with no captions has no captions in Chromium either, and a private
    video is private to a browser too, so both of those come straight back
    rather than costing ten seconds to be told the same thing twice.
    """
    vid = video_id(video)
    if store is not None:
        stored = await store.find(vid, language)
        if stored is not None:
            return stored
    cached = read_cache(cache_dir, vid, language)
    if cached is not None:
        return cached
    try:
        found = await over_http(vid, language, client_factory=client_factory)
    except (NoTranscript, NotAvailable, NotAVideo):
        raise
    except YouTubeTrouble as first:
        if not use_browser:
            raise
        log.info("youtube: plain fetch of %s failed (%s), trying a browser", vid, first)
        try:
            found = await over_browser(vid, language, browsers_path=browsers_path)
        except YouTubeTrouble as second:
            # Both sides, because "the browser is not installed" on its own
            # hides what YouTube actually said, and YouTube's answer on its own
            # hides that the fallback never ran.
            raise type(second)(f"{first} Then the browser: {second}") from None
    if found.cues:
        write_cache(cache_dir, vid, language, found)
        if store is not None:
            await store.keep(vid, language, found)
    return found


# ---------------------------------------------------------------------------
# Rendering one for the conversation
# ---------------------------------------------------------------------------


def render(found: Transcript, *, timestamps: bool = False, start=None, end=None,
           max_chars: int = DEFAULT_MAX_CHARS) -> str:
    """The transcript as the model should read it, with its own size said.

    Never silently cut. When there is more than fits, the last line says how
    much was left and the timestamp to ask for it from, which is the same shape
    as read_workspace saying which line it stopped on.
    """
    max_chars = max(500, min(int(max_chars or DEFAULT_MAX_CHARS), CEILING_MAX_CHARS))
    begin = seconds_of(start)
    finish = seconds_of(end)
    cues = _transcript_span(found.cues, begin, finish)
    head = _transcript_header(found)

    if not cues:
        head.append("")
        head.append("Nothing was said in the span you asked for.")
        return "\n".join(head)

    span_from, span_to = cues[0].start, cues[-1].start + max(cues[-1].duration, 0.0)
    body, cut_at = _body(cues, timestamps, max_chars)
    if begin is not None or finish is not None:
        head.append(f"Showing {clock(span_from)} to {clock(cut_at if cut_at else span_to)}"
                    f" of {clock(found.spoken_length)}.")
    lines = head + ["", body]
    if cut_at is not None:
        lines.append("")
        lines.append(
            f"... cut off at {clock(cut_at)} to keep this a readable size. "
            f"Ask again with start: \"{clock(cut_at)}\" for what comes next, or "
            f"give start and end to read one part of it.")
    return "\n".join(lines)


def _transcript_span(cues, begin: float | None, finish: float | None):
    """The cues selected by the requested start and end boundaries."""
    if begin is not None:
        # Strictly past the moment asked for, so that continuing from the
        # timestamp a cut-off reported starts on the line that did not fit
        # rather than repeating the one that did. A line still being spoken
        # at that moment is kept, which is what makes a mid-sentence start
        # read properly.
        cues = [c for c in cues if c.start + max(c.duration, 0.0) > begin]
    if finish is not None:
        cues = [c for c in cues if c.start <= finish]
    return cues


def _transcript_header(found: Transcript) -> list[str]:
    """The video, whole-transcript size and provenance above the selected speech."""
    whole = " ".join(c.text for c in found.cues)
    head = [
        f"{found.title or 'A YouTube video'} - {found.channel or 'unknown channel'}",
        f"{found.url}  (video id {found.video_id})",
        f"Published {found.published or 'unknown'}, {minutes_words(found.duration)}"
        + (f", {_views_words(found.views)}" if found.views else ""),
        f"Transcript: {found.language_name or found.language_code or 'unknown'}"
        f" [{found.language_code or '?'}], "
        + ("auto-generated by YouTube" if found.generated else "human-written"),
        f"The whole transcript is {len(whole):,} characters, "
        f"{minutes_words(found.spoken_length)} of speech.",
    ]
    if found.how == "stored":
        head.append("Read from Rouh's stored transcripts"
                    + (f", made {_day(found.stored_at)}" if found.stored_at else "")
                    + "; not transcribed again.")
    elif found.how == "cache":
        head.append("Read from Rouh's cache, fetched earlier.")
    elif found.how == "phone":
        head.append(
            "Fetched through YouTube's phone player, because the watch page's own "
            "caption track came back empty.")
    elif found.how == "browser":
        head.append("Fetched with a headless browser; the plain request was turned away.")
    elif found.how == "panel":
        head.append(
            "Read off the video page's own transcript panel in a headless browser, "
            "because YouTube served the caption track empty. The timestamps are the "
            "ones YouTube prints beside each line.")
    return head


def _body(cues, timestamps: bool, max_chars: int):
    """The speech itself, and the timestamp it was cut at, or None if it all fit."""
    out: list[str] = []
    used = 0
    for cue in cues:
        piece = f"[{clock(cue.start)}] {cue.text}" if timestamps else cue.text
        cost = len(piece) + (1 if out else 0)
        if used + cost > max_chars and out:
            return (("\n" if timestamps else " ").join(out), cue.start)
        out.append(piece)
        used += cost
    return (("\n" if timestamps else " ").join(out), None)


def _views_words(views: str) -> str:
    try:
        count = int(str(views).strip())
    except (TypeError, ValueError):
        return ""
    if count >= 1_000_000_000:
        return f"{count / 1_000_000_000:.1f}B views".replace(".0B", "B")
    if count >= 1_000_000:
        return f"{count / 1_000_000:.1f}M views".replace(".0M", "M")
    if count >= 1_000:
        return f"{count / 1_000:.1f}K views".replace(".0K", "K")
    return f"{count} views"


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


@dataclass
class Result:
    """One video a search found."""

    video_id: str
    title: str = ""
    channel: str = ""
    published: str = ""
    duration: float = 0.0
    views: str = ""
    description: str = ""

    @property
    def url(self) -> str:
        return watch_url(self.video_id)


#: What the API calls each ordering, by the word a person would say.
ORDERS = {
    "relevance": "relevance",
    "date": "date",
    "newest": "date",
    "views": "viewCount",
    "viewcount": "viewCount",
    "view_count": "viewCount",
    "rating": "rating",
}


def iso_duration(text: str) -> float:
    """PT1H2M3S, which is how the API says how long a video is, in seconds."""
    found = re.match(r"^P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?$",
                     str(text or "").strip().upper())
    if not found:
        return 0.0
    days, hours, minutes, secs = (int(g or 0) for g in found.groups())
    return float(days * 86400 + hours * 3600 + minutes * 60 + secs)


def published_after(text: str) -> str:
    """A date the model wrote, as the RFC 3339 the API insists on.

    "2026-01-01" is what a model writes and what the API rejects, so the time
    is filled in here rather than the call failing with a 400 nobody can act on.
    """
    raw = str(text or "").strip()
    if not raw:
        return ""
    if re.match(r"^\d{4}-\d{2}-\d{2}$", raw):
        return raw + "T00:00:00Z"
    if re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}", raw):
        return raw if raw.endswith("Z") or "+" in raw[10:] else raw + "Z"
    return raw


def api_trouble(status: int, body: dict) -> YouTubeTrouble:
    """The API's own error, as the one of ours that says what to do about it.

    Quota is the one that matters and the reason this exists: search.list costs
    100 of a 10,000 unit day, so sixty searches empties it, and "we are out of
    YouTube searches until midnight Pacific" is a useful thing to be told where
    "search failed" is not.
    """
    errors = (((body or {}).get("error") or {}).get("errors") or [{}])
    reason = str((errors[0] or {}).get("reason") or "")
    said = str(((body or {}).get("error") or {}).get("message") or "").strip()
    if reason in ("quotaExceeded", "dailyLimitExceeded", "rateLimitExceeded",
                  "userRateLimitExceeded"):
        return OutOfQuota(
            "the day's YouTube API quota is spent. It resets at midnight Pacific "
            "time. A search costs 100 of 10,000 units a day.")
    if reason in ("keyInvalid", "badRequest") and "key" in said.lower():
        return NoKey(f"YouTube refused the API key: {said or reason}")
    if reason in ("forbidden", "accessNotConfigured"):
        return Blocked(
            "YouTube refused the key: the Data API v3 is probably not enabled for "
            f"that Google Cloud project. {said}")
    if status == 404:
        return NotAvailable("YouTube has nothing by that id.")
    return YouTubeTrouble(f"YouTube's API answered {status}: {said or 'no reason given'}")


async def search_api(query: str, key: str, *, limit: int = DEFAULT_RESULTS,
                     order: str = "relevance", after: str = "",
                     client_factory=None) -> list[Result]:
    """search.list for the ids, then videos.list for what search.list omits.

    Two calls, always, and the second is one call for up to fifty ids rather
    than one per video: search.list returns no duration and no view count, and
    a result list without them is not worth much for deciding what to watch.
    """
    if not key:
        raise NoKey("there is no YouTube API key configured on this machine")
    limit = max(1, min(int(limit or DEFAULT_RESULTS), MAX_RESULTS))
    params = {
        "part": "snippet",
        "q": str(query or "").strip(),
        "maxResults": str(limit),
        "type": "video",          # never a channel and never a playlist
        "order": ORDERS.get(str(order or "").strip().lower(), "relevance"),
        "key": key,
    }
    when = published_after(after)
    if when:
        params["publishedAfter"] = when
    async with _client(client_factory) as http:
        found = await _api_get(http, f"{YOUTUBE_API}/search", params)
        ids, by_id = [], {}
        for item in found.get("items") or []:
            vid = str(((item.get("id") or {}).get("videoId") or "")).strip()
            if not vid:
                continue
            snippet = item.get("snippet") or {}
            ids.append(vid)
            by_id[vid] = Result(
                video_id=vid,
                title=html_module.unescape(str(snippet.get("title") or "")),
                channel=str(snippet.get("channelTitle") or ""),
                published=str(snippet.get("publishedAt") or "")[:10],
                description=html_module.unescape(str(snippet.get("description") or "")),
            )
        if not ids:
            return []
        more = await _api_get(http, f"{YOUTUBE_API}/videos", {
            "part": "contentDetails,statistics",
            "id": ",".join(ids),
            "key": key,
        })
    for item in more.get("items") or []:
        result = by_id.get(str(item.get("id") or ""))
        if result is None:
            continue
        result.duration = iso_duration(
            ((item.get("contentDetails") or {}).get("duration") or ""))
        result.views = str((item.get("statistics") or {}).get("viewCount") or "")
    return [by_id[vid] for vid in ids]


async def _api_get(http: httpx.AsyncClient, url: str, params: dict) -> dict:
    try:
        answer = await http.get(url, params=params)
    except httpx.HTTPError as exc:
        raise Unreachable(
            f"YouTube's API did not answer ({type(exc).__name__}).") from None
    try:
        body = answer.json()
    except ValueError:
        body = {}
    if answer.status_code >= 400:
        raise api_trouble(answer.status_code, body)
    return body


# ---------------------------------------------------------------------------
# Search without a key
# ---------------------------------------------------------------------------


def results_from_page(html: str, limit: int = DEFAULT_RESULTS) -> list[Result]:
    """Videos out of a results page's ytInitialData blob.

    The shape is deep and YouTube moves it about, so the walk is a recursive
    hunt for anything called ``videoRenderer`` rather than a path. A path that
    is one key out returns nothing and says nothing about why.
    """
    data = initial_data(html)
    out: list[Result] = []
    seen: set[str] = set()

    def walk(node):
        if len(out) >= limit:
            return
        if isinstance(node, dict):
            renderer = node.get("videoRenderer")
            if isinstance(renderer, dict):
                found = _from_renderer(renderer)
                if found and found.video_id not in seen:
                    seen.add(found.video_id)
                    out.append(found)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(data)
    return out[:limit]


def _runs(node) -> str:
    """The text of one of YouTube's little text objects, in either shape."""
    if not isinstance(node, dict):
        return ""
    if node.get("simpleText"):
        return str(node["simpleText"])
    return "".join(str((run or {}).get("text") or "") for run in node.get("runs") or [])


def _from_renderer(renderer: dict) -> Result | None:
    vid = str(renderer.get("videoId") or "").strip()
    if not _ID.match(vid):
        return None
    views = _runs(renderer.get("viewCountText"))
    digits = re.sub(r"[^0-9]", "", views)
    snippets = renderer.get("detailedMetadataSnippets") or []
    described = _runs((snippets[0] or {}).get("snippetText")) if snippets else ""
    if not described:
        described = _runs(renderer.get("descriptionSnippet"))
    return Result(
        video_id=vid,
        title=_runs(renderer.get("title")),
        channel=_runs((renderer.get("ownerText") or
                       renderer.get("longBylineText") or {})),
        # A results page says "3 weeks ago", not a date. Kept as it is: a
        # made-up date is worse than YouTube's own words.
        published=_runs(renderer.get("publishedTimeText")),
        duration=seconds_of(_runs(renderer.get("lengthText"))) or 0.0,
        views=digits,
        description=described,
    )


#: YouTube's own filters on its results page, as its `sp` parameter: videos
#: only, and videos only from the last day (the morning brief's).
VIDEOS = "EgIQAQ%3D%3D"
VIDEOS_TODAY = "EgQIAhAB"


async def search_scrape(query: str, *, limit: int = DEFAULT_RESULTS,
                        client_factory=None, only: str = VIDEOS) -> list[Result]:
    """The results page, read the way the watch page is read. Second best."""
    address = "https://www.youtube.com/results?" + urlencode(
        {"search_query": str(query or "").strip(), "sp": only}, safe="%")
    async with _client(client_factory) as http:
        try:
            page = await http.get(address)
        except httpx.HTTPError as exc:
            raise Unreachable(f"YouTube did not answer ({type(exc).__name__}).") from None
        if page.status_code >= 400:
            raise Blocked(f"YouTube answered {page.status_code} for that search.")
        found = results_from_page(page.text, limit)
        wall = "" if found else looks_blocked(page.text, str(page.url))
    if not found:
        raise Blocked(wall or
                      "YouTube's results page came back with no videos in it, which "
                      "is what it does to a plain request it does not trust.")
    return found


def render_results(found, *, query: str, scraped: bool = False) -> str:
    """A result list, as lines the model can read out or pick from."""
    if not found:
        return f"YouTube found nothing for {query!r}."
    lines = [f"{len(found)} videos on YouTube for {query!r}"
             + (", scraped from the results page rather than read from the API, so "
                "the view counts and dates are as YouTube wrote them on the page."
                if scraped else ".")]
    for i, item in enumerate(found, 1):
        bits = [item.channel or "unknown channel"]
        if item.published:
            bits.append(item.published)
        if item.duration:
            bits.append(clock(item.duration))
        if item.views:
            bits.append(_views_words(item.views) or item.views)
        lines.append("")
        lines.append(f"{i}. {item.title or '(no title)'}")
        lines.append(f"   {' - '.join(b for b in bits if b)}")
        lines.append(f"   {item.url}  (video id {item.video_id})")
        if item.description:
            lines.append(f"   {_tidy(item.description)[:300]}")
    return "\n".join(lines)
