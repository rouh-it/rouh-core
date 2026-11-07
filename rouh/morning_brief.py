"""The morning brief: one short page to start the day with, made every morning.

Petar, 29 September 2026 (fr_c01a16e51a05): "Make a morning brief please. Do
the best you can with the tools you have. ... Calendar is primary importance.
Maybe news. YouTube. On ai? Important piece of world news. Weather. Whatever
else you could think of. Figure out where I will get it. Link in telegram to
html page? Can I get through it on the sidebar? Options in settings?"

And the same day, once he had read the first one (fr_a2b5a77d76b3): "Move the
weather on top. I only need two days calendar - today and tomorrow. For world
news make those 3 pieces, the most significant. For ai news, please scan
YouTube videos from my favorite channels: Matt wolf, Matthew berman, the ai
grid. Transcribe and then crunch for 3 -5 items".

So it is, in this order:

1. **Weather** - today where the person is, from Open-Meteo, which needs no
   key. The place is the person's shared location; with none, the weather says so.
2. **Calendar** - today and tomorrow, and nothing further out. Read from the
   person's own Google account, every calendar it can see
   (`google_api.Calendar.events`), exactly as "what do I have tomorrow" is. A
   day with nothing on it still says so, so nothing looks missed.
3. **World** - three stories from BBC News' world feed: the three a model
   reading the whole feed judges the most significant of the day, or the
   newsroom's own first three when no model can be asked (`_world`).
4. **AI** - what the person's own YouTube channels said since the last brief
   (Matt Wolfe, Matthew Berman and The AI Grid until changed): each new
   video's captions (`rouh/youtube.py`) read by a model and condensed into
   three to five items, each naming its channel and linking to its video
   (`_ai`). A channel with nothing new is left out without a word.
5. **Inbox** and **reminders** - how much unread mail came in overnight and
   from whom, and what Rouh was asked to say or do yesterday, today and
   tomorrow, today the one made most of, as Birthdays are (`_reminders`).
6. **Today in history** - last, as Petar asked on 30 September 2026
   (fr_05fbc0c5754b): "'Today in history,' picked for your interests (Ordered
   by decreasing significance)", and since 19 October 2026 (fr_a1b47c17f8cf:
   "It is fairly uninteresting to me ... it needs to be targeted") for the
   topics the person picks with the gear at the right of the section's
   heading (`HISTORY_TOPICS`), and topics of their own such as "Steve Jobs",
   each looked for in Wikipedia's articles (`_found_for`). Up to eight things
   that happened on this date, out of Wikipedia's "On this day" (`_history`),
   each picked by a model only when it belongs to one of the topics, named
   with it and ordered most significant first. With no topics picked there
   are no events, only a line asking for them (`save_topics`).
7. **Report** - drawn right after the reminders: what ran while the person
   slept, as Petar asked on 5 October 2026: first one plain paragraph about last night's Synapse attempt (the
   idea, whether it worked, which measures moved and by how much, whether it
   was kept, and any decision that is his, with its options), or that it
   failed or did not start; then everything else scheduled that ran since the
   last brief, each with what it found or did, left out when nothing ran
   (`_report`, read again every time the page opens, `report_again`). Since
   18 October 2026 what is about Rouh and repeats - the nightly runs - is in
   neither Clockwork nor the Report: Petar sees it in his notifications.
8. **Birthdays** - right before the doodle, as Petar asked on 30 September
   2026 (fr_d3ea4a374d50): yesterday's, today's and tomorrow's, from his
   contacts and the birthdays on his calendars, each person once
   (`rouh/birthdays.py`). A calendar birthday with no contact behind it can be
   linked to one from the page, and reads as that contact from then on.
9. **Needs you in Slack** - drawn right after the mail, as Petar asked on 16 October 2026: what
   waits on him in Slack since the last brief, each line who, where, a few words of what they
   asked, how long it has waited and a link to it in Slack (`rouh/slack_brief.py`). Only what he
   must act on, judged by a model; anything he has answered or reacted to since is dropped, again
   every time the page opens (`slack_brief.again`). With nothing waiting, or no Slack of his,
   there is no section.
10. **Dad joke** - right after the doodle, as Petar asked on 20 October
   2026 (fr_6fb4aad2f62c): "do not invent jokes, get them from somewhere.
   preferably rated high, rather than random." One joke from Reddit's
   r/dadjokes, the highest voted of the week that the person was not shown in
   the last `JOKE_DAYS` days, word for word, setup and punchline, with a link
   to the post (`_joke`). It is the same all day, and with Reddit not
   answering there is no section.

The weather, the calendar, the inbox and the reminders are what their source
said, with no model in between. The world stories and the events in history
are their source's own words, only picked by a model; the AI items are a model's
words, each tied to the video it came from. A section whose source cannot be
reached says so in a line (`note`) and the rest of the brief is made
regardless.

**Where it is.** The page is the Morning brief row in the sidebar, at
`/brief` (`briefpage.js`), which shows the newest brief there is at once and
never makes one by being opened (fr_e7c51081dc50, 9 October 2026: "anytime I
visit that page I see the last generated routine"); before seven that is
yesterday's, and the page says so. Update makes today's, doing again only the
work whose inputs are new since the brief before it (`make`). **When.** Every morning at the person's time (07:00 until changed, on
their own clock), `Mornings` makes it afresh and, for the person whose phone
the Telegram bot reaches (`telegram.phone_owner`), sends a few lines and the
link. Both are settings of the person's own, on the Settings page under
Morning brief: on or off, the time, and the YouTube channels. The place the
weather is for is not one of them: it is wherever the Location card at the
top of Settings says the person is (`rouh/location.py`), so there is one
place in Rouh and not two (`weather_place`).

**Whose.** A brief is one person's: every row carries `user_id` and `org_id`
and every query names both (`AGENTS.md`, "Whose data is it").
"""
from __future__ import annotations

import asyncio
import html
import json
import logging
import os
import re
import time
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta

import httpx

from . import birthdays, clock, slack_brief

log = logging.getLogger("rouh.morning_brief")

#: The person's own settings row (`models.UserSetting`) the brief keeps.
SETTING = "morning_brief"

#: What a person's brief is until they change it. No place: the weather is
#: for their location or it says there is none (`weather_place`).
DEFAULTS = {"on": True, "time": "07:00", "place": "", "lat": None, "lon": None}

#: What the weather says when nobody has said where they are.
NO_PLACE = ("No location is set, so there is no weather. Share your location in Settings, "
            "under Location, and the next brief has it.")

#: The YouTube channels the AI news is read from until the person names theirs:
#: none. The first owner's three favourites (29 September 2026) were the
#: default for everybody until 20 October 2026; they are in his own settings
#: now, and a new owner starts with an empty list (SETUP.md).
CHANNELS: list[dict] = []
MOST_CHANNELS = 8

#: Which way the brief's parts are kept. A brief kept in an older shape is not
#: drawn, rather than drawn with parts missing; the page says to press Update.
SHAPE = 4

#: How late a brief that could not go at its time (Rouh was down, or being
#: deployed) is still worth sending. After that it waits for Update.
LATE = 3 * 3600

#: The sources, each overridable so a test world can stand in for it.
WEATHER_URL = os.environ.get("ROUH_BRIEF_WEATHER_URL", "https://api.open-meteo.com/v1/forecast")
WORLD_FEED = os.environ.get("ROUH_BRIEF_WORLD_FEED", "https://feeds.bbci.co.uk/news/world/rss.xml")
#: A channel's newest videos, as YouTube's own feed of them. No key needed.
CHANNEL_FEED = os.environ.get("ROUH_BRIEF_CHANNEL_FEED",
                              "https://www.youtube.com/feeds/videos.xml")
CHANNEL_PAGE = os.environ.get("ROUH_BRIEF_CHANNEL_PAGE", "https://www.youtube.com/")
#: Wikipedia's "On this day", which the month and the day are put after
#: ("/09/30"). No key needed.
HISTORY_FEED = os.environ.get("ROUH_BRIEF_HISTORY_FEED",
                              "https://en.wikipedia.org/api/rest_v1/feed/onthisday/all")
#: r/dadjokes' most voted posts of a span ("?t=week"), as Reddit's own Atom
#: feed of them. No key needed; Reddit's JSON refuses a server, its feed does not.
JOKE_FEED = os.environ.get("ROUH_BRIEF_JOKE_FEED", "https://www.reddit.com/r/dadjokes/top/.rss")

#: What each source is called on the page, so every section says where it came from.
SOURCES = {"birthdays": birthdays.SOURCE, "calendar": "Google Calendar", "weather": "Open-Meteo", "world": "BBC News",
           "ai": "YouTube", "mail": "Gmail", "reminders": "Clockwork",
           "history": "Wikipedia", "report": "Rouh's own records", "joke": "r/dadjokes on Reddit"}

SECONDS = 12.0
MOST_A_DAY = 20
#: How many world stories there are, and how many of the feed's are read to
#: pick them from.
WORLD_STORIES = 3
WORLD_POOL = 30
#: The AI news: how many items, how many new videos a channel gives at most,
#: how much of each transcript the model reads, and how far back "since the
#: last brief" may reach (a day at least, three at most, two with no last one).
AI_ITEMS = (3, 5)
#: Today in history: up to this many events, and as few as belong to the topics.
TOPIC_EVENTS = 8
#: The person's own topics: how many, how long each, how many of Wikipedia's
#: articles are read for each, and how many of what is found in them are kept.
MOST_CUSTOM = 6
CUSTOM_CHARS = 60
CUSTOM_ARTICLES = 4
CUSTOM_FOUND = 6
#: Wikipedia's own search and articles, for the person's own topics. No key needed.
WIKI_API = os.environ.get("ROUH_BRIEF_WIKI_API", "https://en.wikipedia.org/w/api.php")
#: How long the history pool may be, in characters, for the model to read.
POOL_CHARS = 60_000

#: The dad joke: how many days back a joke is not told again, and the spans
#: of r/dadjokes' top posts read for it, the week's first and the month's
#: when every one of the week's has been told or left out.
JOKE_DAYS = 60
JOKE_SPANS = (("week", "this week"), ("month", "this month"))
#: How long a joke may be to be one, and the words that make a post not one
#: for a morning page (the subreddit is "wholesome, some are not").
JOKE_CHARS = 400
JOKE_CRUDE = re.compile(
    r"\b(fuck\w*|shit\w*|sex|sexy|sexual\w*|porn\w*|dicks?|cocks?|puss(y|ies)|cum|cumming|bitch\w*|rap(e|ed|ist)|"
    r"penis\w*|vagina\w*|boobs?|tits?|nipples?|asshole\w*|orgasm\w*|condoms?|nazi\w*|"
    r"hitler|n[i1]gg\w*|horny|blowjob\w*|erection\w*|viagra|masturbat\w*|"
    r"testicles?|scrotum)\b", re.I)

#: The topics Today in history can be picked for, in the order the gear's box
#: lists them (fr_a1b47c17f8cf, 19 October 2026: "a wide array of topics ...
#: birthdays of famous people, historical events, inventions, technology ...
#: and many more"). `kinds` are which of Wikipedia's lists for the day are read
#: for it: its events, the people born and who died on it, and its holidays.
HISTORY_TOPICS = [
    {"id": "births", "name": "Birthdays of famous people", "kinds": ["births"]},
    {"id": "deaths", "name": "Famous people who died", "kinds": ["deaths"]},
    {"id": "events", "name": "Major historical events", "kinds": ["events"]},
    {"id": "inventions", "name": "Inventions and discoveries", "kinds": ["events", "births"]},
    {"id": "technology", "name": "Technology and computing", "kinds": ["events", "births"]},
    {"id": "science", "name": "Science", "kinds": ["events", "births"]},
    {"id": "space", "name": "Space exploration", "kinds": ["events"]},
    {"id": "medicine", "name": "Medicine and health", "kinds": ["events", "births"]},
    {"id": "business", "name": "Business and companies", "kinds": ["events", "births"]},
    {"id": "economy", "name": "Economy and money", "kinds": ["events"]},
    {"id": "politics", "name": "Politics and leaders", "kinds": ["events"]},
    {"id": "wars", "name": "Wars and battles", "kinds": ["events"]},
    {"id": "rights", "name": "Human rights and social change", "kinds": ["events"]},
    {"id": "exploration", "name": "Exploration and travel", "kinds": ["events"]},
    {"id": "transport", "name": "Cars, trains and flight", "kinds": ["events"]},
    {"id": "architecture", "name": "Buildings and architecture", "kinds": ["events"]},
    {"id": "art", "name": "Art and design", "kinds": ["events", "births"]},
    {"id": "music", "name": "Music", "kinds": ["events", "births"]},
    {"id": "film", "name": "Film and television", "kinds": ["events", "births"]},
    {"id": "books", "name": "Books and writers", "kinds": ["events", "births"]},
    {"id": "sport", "name": "Sport", "kinds": ["events", "births"]},
    {"id": "religion", "name": "Religion and philosophy", "kinds": ["events"]},
    {"id": "nature", "name": "Nature and disasters", "kinds": ["events"]},
    {"id": "royalty", "name": "Kings, queens and empires", "kinds": ["events"]},
    {"id": "ancient", "name": "Ancient and medieval history", "kinds": ["events"]},
    {"id": "holidays", "name": "Holidays and observances", "kinds": ["holidays"]},
]
TOPIC_NAMES = {one["id"]: one["name"] for one in HISTORY_TOPICS}

#: What the gear's box offers as examples of a topic of one's own: a person, a
#: company, a field, a place, a band and a sport.
CUSTOM_EXAMPLES = ["Steve Jobs", "Apple", "Artificial intelligence", "Japan",
                   "The Beatles", "Formula 1"]
VIDEOS_A_CHANNEL = 2
TRANSCRIPT_CHARS = 24_000
SINCE_LEAST, SINCE_MOST, SINCE_FIRST = 24 * 3600, 72 * 3600, 48 * 3600
#: How long a model is given to pick the stories or condense the videos.
MODEL_SECONDS = 180.0
TIME = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")

#: WMO weather codes, as a word and a picture.
WEATHER_WORDS = {
    0: ("Clear", "☀️"), 1: ("Mostly clear", "🌤️"), 2: ("Partly cloudy", "⛅"),
    3: ("Overcast", "☁️"), 45: ("Fog", "🌫️"), 48: ("Freezing fog", "🌫️"),
    51: ("Light drizzle", "🌦️"), 53: ("Drizzle", "🌦️"), 55: ("Heavy drizzle", "🌧️"),
    56: ("Freezing drizzle", "🌧️"), 57: ("Freezing drizzle", "🌧️"),
    61: ("Light rain", "🌦️"), 63: ("Rain", "🌧️"), 65: ("Heavy rain", "🌧️"),
    66: ("Freezing rain", "🌧️"), 67: ("Freezing rain", "🌧️"),
    71: ("Light snow", "🌨️"), 73: ("Snow", "🌨️"), 75: ("Heavy snow", "❄️"),
    77: ("Snow grains", "🌨️"), 80: ("Light showers", "🌦️"), 81: ("Showers", "🌧️"),
    82: ("Violent showers", "⛈️"), 85: ("Snow showers", "🌨️"), 86: ("Heavy snow showers", "❄️"),
    95: ("Thunderstorms", "⛈️"), 96: ("Thunderstorms with hail", "⛈️"),
    99: ("Thunderstorms with hail", "⛈️"),
}


class Refused(ValueError):
    """A setting that cannot be kept, in words the page shows as they are."""


# --- the person's settings --------------------------------------------------


def settings_of(who) -> dict:
    """This person's brief settings, with the defaults filled in."""
    from .models import UserSetting

    out = dict(DEFAULTS, channels=[dict(one) for one in CHANNELS], topics=[], custom=[])
    if who is None:
        return out
    value = (UserSetting.objects
             .filter(user_id=str(who.user_id), org_id=who.org_id or "", name=SETTING)
             .values_list("value", flat=True).first())
    try:
        held = json.loads(value) if value else {}
    except (TypeError, ValueError):
        held = {}
    if isinstance(held, dict):
        if isinstance(held.get("on"), bool):
            out["on"] = held["on"]
        if TIME.match(str(held.get("time") or "")):
            out["time"] = held["time"]
        if isinstance(held.get("channels"), list):
            out["channels"] = [
                {"name": str(one.get("name") or one["id"])[:80], "id": one["id"],
                 "handle": str(one.get("handle") or "")[:80]}
                for one in held["channels"][:MOST_CHANNELS]
                if isinstance(one, dict) and CHANNEL_ID.match(str(one.get("id") or ""))]
        out["topics"] = [one for one in held.get("topics") or [] if one in TOPIC_NAMES]
        out["custom"] = _custom_list(held.get("custom"))
    out.update(weather_place(who))
    return out


def weather_place(who) -> dict:
    """Where the weather is for: the person's own location, as {place, lat, lon}.

    The one the Location card at the top of Settings keeps (`location.get`).
    Until 30 September 2026 the brief kept a place of its own, typed into a
    "Weather for" box on its Settings card, and never read the location: a city
    was typed there on 29 September, before a trip, the Location card came the
    next day and said another, and the brief went on giving the first city's
    weather (fr_5d364b8f6ed5). That box and that place are gone,
    and whatever an old row still holds under "place" is not read. With no
    location kept, the place is empty and the weather says so (`NO_PLACE`),
    rather than being quietly for somewhere else.
    """
    from . import location

    kept = location.get(who)
    if kept is None or _number(kept.get("lat")) is None or _number(kept.get("lon")) is None:
        return {"place": "", "lat": None, "lon": None}
    lat, lon = float(kept["lat"]), float(kept["lon"])
    # The place is worked out from the point and can be missing; then the
    # point is what it is for, as the Location card itself shows it.
    place = str(kept.get("place") or "").strip()[:120] or f"{lat:.2f}, {lon:.2f}"
    return {"place": place, "lat": lat, "lon": lon}


def channel_lines(channels) -> str:
    """The channels as the Settings box shows them: one a line, by handle."""
    return "\n".join(one.get("handle") or CHANNEL_PAGE + "channel/" + one["id"]
                      for one in channels)


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


async def save_settings(who, sent: dict) -> dict:
    """Keep what the Settings card sent: {on, time, channels}. What was kept.

    The channels are a line each, a handle or a link, and each new one is
    looked up on YouTube (`find_channel`) and kept by its id and its own name.
    Refused, with the reason, when the time is not a time or a channel cannot
    be found. A place is not the brief's to keep (`weather_place`), so one
    sent is not read.
    """
    from asgiref.sync import sync_to_async

    held = await sync_to_async(settings_of)(who)
    on = sent.get("on", held["on"])
    if not isinstance(on, bool):
        raise Refused("On or off is yes or no.")
    at = str(sent.get("time", held["time"]) or "").strip()
    if not TIME.match(at):
        raise Refused("The time is a time of day, such as 07:00.")
    kept = {"on": on, "time": at, "channels": held["channels"],
            "topics": held["topics"], "custom": held["custom"]}
    if "channels" in sent:
        kept["channels"] = await _channels_from(sent.get("channels"), held["channels"])
    await sync_to_async(_put)(who, kept)
    return {**kept, **{k: held[k] for k in ("place", "lat", "lon")}}


def _custom_list(sent) -> list[str]:
    """The person's own topics, each one line, tidied, each once, as many as are kept."""
    out, seen = [], set()
    for one in sent if isinstance(sent, list) else []:
        words = " ".join(str(one or "").split())[:CUSTOM_CHARS]
        if words and words.lower() not in seen:
            seen.add(words.lower())
            out.append(words)
    return out[:MOST_CUSTOM]


async def save_topics(who, sent: dict, *, day: str = "") -> dict:
    """Keep the topics Today in history is picked for: {topics, custom}.

    `topics` are ids of `HISTORY_TOPICS` and `custom` the person's own, such
    as "Steve Jobs". When `day` is the day of a brief the person has, its Today
    in history is picked again for them at once and put into it, so the box
    the topics were chosen in shows what they give. What was kept, and that
    part when there is one.
    """
    from asgiref.sync import sync_to_async

    topics, custom = sent.get("topics"), sent.get("custom")
    if not isinstance(topics, list) or not isinstance(custom, list):
        raise Refused("The topics are a list, and so are your own.")
    unknown = [str(one) for one in topics if one not in TOPIC_NAMES]
    if unknown:
        raise Refused(f"{unknown[0][:40]!r} is not one of the topics.")
    if len(custom) > MOST_CUSTOM:
        raise Refused(f"You can keep {MOST_CUSTOM} topics of your own at most.")
    held = await sync_to_async(settings_of)(who)
    held_row = {k: held[k] for k in ("on", "time", "channels")}
    held_row["topics"] = [one["id"] for one in HISTORY_TOPICS if one["id"] in topics]
    held_row["custom"] = _custom_list(custom)
    await sync_to_async(_put)(who, held_row)
    out = {"topics": held_row["topics"], "custom": held_row["custom"]}
    brief = await sync_to_async(kept)(who, day) if day else None
    if brief is not None:
        settings = {**held, **out}
        on = date.fromisoformat(brief["day"])
        async with _http() as http:
            try:
                part = await _history(http, who, settings, on)
            except Exception:
                log.exception("the morning brief's history failed")
                part = {"ok": False, "note": "The history part of the brief could not be made."}
        part["source"] = SOURCES["history"]
        await sync_to_async(_put_part)(who, brief["day"], "history", part)
        out["history"] = part
    return out


def _put(who, kept: dict) -> None:
    from .models import UserSetting

    UserSetting.objects.bulk_create(
        [UserSetting(user_id=str(who.user_id), org_id=who.org_id or "", name=SETTING,
                     value=json.dumps(kept, ensure_ascii=False), updated_at=time.time())],
        update_conflicts=True, unique_fields=["user_id", "name"],
        update_fields=["org_id", "value", "updated_at"])


CHANNEL_ID = re.compile(r"^UC[A-Za-z0-9_-]{22}$")
_CHANNEL_IN = re.compile(r"(?:youtube\.com/)?(?:channel/)?(UC[A-Za-z0-9_-]{22})\b")
_HANDLE_IN = re.compile(r"(?:youtube\.com/)?(@[\w.\-]{3,40})")


async def _channels_from(sent, held: list[dict]) -> list[dict]:
    """The channels the Settings box sent, a handle or a link a line, looked up."""
    lines = sent if isinstance(sent, list) else str(sent or "").splitlines()
    lines = [str(line).strip() for line in lines if str(line).strip()]
    if len(lines) > MOST_CHANNELS:
        raise Refused(f"The AI news reads {MOST_CHANNELS} channels at most.")
    known = {}
    for one in held + CHANNELS:
        known.setdefault(one["id"], one)
        if one.get("handle"):
            known.setdefault(one["handle"].lower(), one)
    out, seen = [], set()
    for line in lines:
        by_id, by_handle = _CHANNEL_IN.search(line), _HANDLE_IN.search(line)
        key = by_id.group(1) if by_id else by_handle.group(1).lower() if by_handle else ""
        if not key:
            raise Refused(f"{line[:60]!r} is not a YouTube channel. Give its @handle, such "
                          "as @mreflow, or its link.")
        found = known.get(key) or await find_channel(by_id.group(1) if by_id
                                                     else by_handle.group(1))
        if found["id"] not in seen:
            seen.add(found["id"])
            out.append(found)
    return out


async def find_channel(which: str) -> dict:
    """A YouTube channel by its handle ("@mreflow") or its id, as {name, id, handle}."""
    from . import youtube

    path = which if which.startswith("@") else "channel/" + which
    try:
        async with httpx.AsyncClient(timeout=SECONDS, follow_redirects=True,
                                     headers={"User-Agent": youtube.USER_AGENT,
                                              "Accept-Language": "en-US,en;q=0.9"},
                                     cookies=youtube.CONSENT_COOKIES) as http:
            got = await http.get(CHANNEL_PAGE + path)
    except httpx.HTTPError:
        raise Refused("YouTube could not be reached just now to look the channels up. "
                      "Try again in a moment.")
    found = re.search(r'"externalId":"(UC[A-Za-z0-9_-]{22})"', got.text)
    if got.status_code == 404 or not found:
        raise Refused(f"No YouTube channel {which} was found.")
    name = re.search(r'<meta property="og:title" content="([^"]*)"', got.text)
    handle = re.search(r'"vanityChannelUrl":"https?://www\.youtube\.com/(@[^"]+)"', got.text)
    return {"name": html.unescape(name.group(1)) if name else which, "id": found.group(1),
            "handle": handle.group(1) if handle else (which if which.startswith("@") else "")}


# --- making one -------------------------------------------------------------


def _http() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=SECONDS, follow_redirects=True,
                             headers={"User-Agent": "Rouh morning brief (+https://rouh.ai)"})


def _day_words(day: date, today: date) -> str:
    gap = (day - today).days
    if gap == 0:
        return "Today"
    if gap == 1:
        return "Tomorrow"
    return f"{day.strftime('%A')} {day.day} {day.strftime('%B')}"


def _hhmm(value) -> str:
    return value.strftime("%H:%M") if isinstance(value, datetime) else ""


def _seconds(value, zone) -> float | None:
    if isinstance(value, datetime):
        return value.timestamp()
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day, tzinfo=zone).timestamp()
    return None


def _an_event(one: dict, today: date, zone) -> dict:
    start, end = one.get("start"), one.get("end")
    day = start.astimezone(zone).date() if isinstance(start, datetime) else start
    if isinstance(start, datetime):
        start = start.astimezone(zone)
    if isinstance(end, datetime):
        end = end.astimezone(zone)
    return {
        "title": one.get("title") or "(no title)",
        "all_day": bool(one.get("all_day")),
        "start": _hhmm(start), "end": _hhmm(end),
        "day": day.isoformat() if isinstance(day, date) else "",
        "day_words": _day_words(day, today) if isinstance(day, date) else "",
        "starts_at": _seconds(start, zone) if not one.get("all_day") else None,
        "ends_at": _seconds(end, zone) if not one.get("all_day") else None,
        "where": (one.get("where") or "")[:160],
        "video": one.get("video") or "",
        "link": one.get("link") or "",
        "calendar": one.get("calendar") or "",
        "response": one.get("my_response") or "",
        # What the event opens to on the page (fr_1da7cddc045b): the ids to
        # read it again and answer it by, its words, and who is invited.
        "id": one.get("id") or "",
        "calendar_id": one.get("calendar_id") or "",
        **event_details(one),
    }


def event_silos(who, events: list[dict]) -> None:
    """Each event's silos, as the chips the page draws (`rouh/silos.py`): its label in Synapse Master when
    Synapse keeps it, else its calendar's rule. Nothing when neither says, or when it cannot be read."""
    try:
        from . import silos
        from .synapse import db

        uid, oid = str(who.user_id), str(who.org_id)
        keys = [f"gcal:{e['calendar_id']}:{e['id']}" for e in events if e.get("id") and e.get("calendar_id")]
        kept = {str(r["source_key"]): list(r["silos"] or []) for r in db.rows(
            "SELECT i.source_key, i.silos FROM synapse.item i JOIN synapse.dataset d ON d.id = i.dataset_id "
            "WHERE d.master AND d.user_id = %s AND d.org_id = %s AND i.source = 'gcal' AND i.deleted_at IS NULL "
            "AND i.source_key = ANY(%s)", (uid, oid, keys))} if keys else {}
        for e in events:
            got = kept.get(f"gcal:{e.get('calendar_id')}:{e.get('id')}")
            if not got and e.get("calendar_id"):
                got = silos.expand(uid, oid, silos.of_calendar(uid, oid, e["calendar_id"])[0])
            if got:
                e["silos"] = silos.chips(uid, oid, got)
    except Exception:  # noqa: BLE001 - drawn without them
        log.exception("the events' silos could not be read")


#: The most of an event's description the brief keeps, and of its guests.
MOST_DESCRIPTION = 4000
MOST_GUESTS = 60


def event_details(one: dict) -> dict:
    """An event's words and people, as the brief's open event shows them."""
    guests = [{"name": g.get("name") or "", "email": g.get("email") or "",
               "response": g.get("response") or "needsAction",
               "organiser": bool(g.get("organiser")), "optional": bool(g.get("optional")),
               "me": bool(g.get("this_calendar"))}
              for g in one.get("guests") or [] if not g.get("resource")]
    return {"description": (one.get("description") or "")[:MOST_DESCRIPTION],
            "organiser": one.get("organiser") or "",
            "organiser_name": one.get("organiser_name") or "",
            "mine": bool(one.get("mine")),
            "guests": guests[:MOST_GUESTS], "more_guests": max(0, len(guests) - MOST_GUESTS),
            "repeats": bool(one.get("series"))}


async def _calendar(who, services, today: date, zone, raw: dict | None = None) -> dict:
    """Today's events and tomorrow's, and nothing after. Declined ones are left out.

    Both days are always there, each with its own words, so an empty one is
    said to be empty rather than missing. The words are only "Today" and
    "Tomorrow", with no date (fr_854ef3f9eb57, 1 October 2026: "Label: Today
    (without the date) ... Tomorrow (without the date)").

    `raw`, when given, is filled with each event as Google gave it, by
    (calendar id, event id), which is what What to raise reads (`_raises`).
    """
    if services is None:
        return {"ok": False, "note": "Google is not connected. Connect it in Settings to see "
                                     "your calendar here."}
    first = datetime(today.year, today.month, today.day, tzinfo=zone)
    try:
        got = await services.calendar.events(first, first + timedelta(days=2),
                                             limit=2 * MOST_A_DAY + 20)
    except Exception as exc:
        return {"ok": False, "note": _google_trouble(exc, "calendar")}
    events = [_an_event(one, today, zone) for one in got.get("events") or []
              if one.get("my_response") != "declined"]
    await asyncio.to_thread(event_silos, who, events)
    if raw is not None:
        raw.update({(one.get("calendar_id") or "", one.get("id") or ""): one
                    for one in got.get("events") or [] if one.get("id")})
    tomorrow = today + timedelta(days=1)
    # An all-day event that started before today and is still going is today's.
    todays = [one for one in events if one["day"] <= today.isoformat()]
    tomorrows = [one for one in events if one["day"] == tomorrow.isoformat()]
    for day in (todays, tomorrows):
        # By the moment, not the clock words: one still going from last night
        # starts at "23:00" and comes first, not last.
        day.sort(key=lambda one: (not one["all_day"], one["starts_at"] or 0))
    return {"ok": True, "today": todays[:MOST_A_DAY], "tomorrow": tomorrows[:MOST_A_DAY],
            "today_words": "Today",
            "tomorrow_words": "Tomorrow",
            "calendars": len(got.get("calendars") or []),
            "trouble": list(got.get("trouble") or [])[:3]}


async def _calendar_and_raises(who, services, today: date, zone,
                               before: dict | None = None) -> dict:
    """The calendar, with What to raise worked out for each meeting on it now.

    Petar, 8 October 2026 (fr_5fb00def9d2d): "the analysis for the event
    should be generated once at the brief creation and saved and just
    displayed. First so I don't have to wait every time I open it, but also
    so I dint get different version every time." Until then it was worked out
    when a meeting was opened, after its mail was read again, and one new
    email in between made a new one. So it is made here, with the brief, and
    kept on each event as `raise`; the page draws what is kept and never asks.

    `before` is the calendar of the brief made before this one (`make`, its `base`): a
    meeting already on it keeps what was worked out for it, as it was, and only
    a meeting that is new is worked out (fr_e7c51081dc50, 9 October 2026: "if
    we have the same events in calendar, no extra calendar work or research or
    what to raise should done").
    """
    raw: dict = {}
    part = await _calendar(who, services, today, zone, raw=raw)
    if part.get("ok"):
        _carry_raises(before, part)
    if part.get("ok") and services is not None:
        await _raises(who, services, part, raw)
    return part


async def _raises(who, services, part: dict, raw: dict) -> None:
    """What to raise at every meeting of the part, kept on each as `raise`.

    One a meeting, however many calendars it is on. A meeting with nobody from
    outside is kept as having nothing (`people: []`), so the page knows without
    asking. One that could not be worked out just now, or with the feature
    switched off, is left without, and the page asks for it the once when the
    meeting is opened (`raise_kept`, `keep_raise`).
    """
    from . import meeting_brief
    from .meeting_prep import event_key

    meetings: dict[str, list[dict]] = {}
    for one in (part.get("today") or []) + (part.get("tomorrow") or []):
        event = raw.get((one.get("calendar_id") or "", one.get("id") or ""))
        if event is not None:
            meetings.setdefault(event_key(event), []).append(one)

    async def work_out(shown: list[dict]) -> None:
        had = next((one["raise"] for one in shown if isinstance(one.get("raise"), dict)
                    and not redo_raise(one["raise"])), None)
        if had is not None:
            # Worked out already, for the brief before: kept as it was.
            for one in shown:
                one["raise"] = had
            return
        event = raw[(shown[0]["calendar_id"], shown[0]["id"])]
        try:
            made = await meeting_brief.make(who, event, services=services)
        except Exception:
            log.exception("what to raise at %r could not be made with the brief",
                          event.get("title"))
            return
        if meeting_brief.settled(made):
            for one in shown:
                one["raise"] = made

    await asyncio.gather(*(work_out(shown) for shown in meetings.values()))


def redo_raise(made) -> bool:
    """Whether a kept What to raise is asked for again rather than drawn: one whose Slack
    lines were chosen under an older rule (`meeting_slack.stale`), one made before Slack was
    read with the mail (`meeting_brief.stale`), or one that read nothing (`meeting_brief.unread`)."""
    from . import meeting_brief, meeting_slack

    return meeting_slack.stale(made) or meeting_brief.stale(made) or meeting_brief.unread(made)


def _same_event(one: dict, calendar_id: str, event_id: str) -> bool:
    return one.get("id") == event_id and one.get("calendar_id") == calendar_id


def raise_kept(who, day: str, calendar_id: str, event_id: str) -> dict | None:
    """What to raise at one meeting, as the day's kept brief has it, or None, as for one whose
    Slack lines were chosen under an older rule or that read nothing (`redo_raise`)."""
    brief = kept(who, day) or {}
    cal = brief.get("calendar") or {}
    for one in (cal.get("today") or []) + (cal.get("tomorrow") or []):
        if (_same_event(one, calendar_id, event_id) and isinstance(one.get("raise"), dict)
                and not redo_raise(one["raise"])):
            return one["raise"]
    return None


def keep_raise(who, day: str, calendar_id: str, event_id: str, made: dict) -> None:
    """What to raise at one meeting, put on it in the day's kept brief.

    For a meeting the brief was made without one for: added to the calendar
    since, or made before What to raise was made with the brief. Once kept it
    is what is drawn, every time, unless it read nothing (`redo_raise`), and the same
    answer again is not written again.
    """
    def put(brief: dict) -> bool:
        cal = brief.get("calendar") or {}
        hit = False
        for one in (cal.get("today") or []) + (cal.get("tomorrow") or []):
            if _same_event(one, calendar_id, event_id) and one.get("raise") != made and (
                    not isinstance(one.get("raise"), dict) or redo_raise(one["raise"])):
                one["raise"] = made
                hit = True
        return hit

    _change(who, day, put)


def replace_raise(who, day: str, calendar_id: str, event_id: str, before: dict,
                  made: dict) -> bool:
    """What to raise at one meeting, made again with his correction, put over `before`.

    On the meeting itself, and on the same meeting where it is on another of his
    calendars too, which carries the same reading (`_raises`). Whether it was there.
    """
    was = (before or {}).get("made_at")
    hits: list[bool] = []

    def put(brief: dict) -> bool:
        cal = brief.get("calendar") or {}
        hit = False
        for one in (cal.get("today") or []) + (cal.get("tomorrow") or []):
            held = one.get("raise")
            if _same_event(one, calendar_id, event_id) or (
                    was and isinstance(held, dict) and held.get("made_at") == was):
                one["raise"] = made
                hit = True
        hits.append(hit)
        return hit

    _change(who, day, put)
    return any(hits)


def drop_stale_raises(brief: dict) -> None:
    """What to raise taken off each meeting whose Slack lines were chosen under an older rule
    or that read nothing (`redo_raise`), in the brief as it is sent to the page, which then
    asks for it."""
    cal = brief.get("calendar") or {}
    for one in (cal.get("today") or []) + (cal.get("tomorrow") or []):
        if redo_raise(one.get("raise")):
            one.pop("raise", None)


def _carry_raises(before: dict | None, part: dict) -> dict:
    """The calendar read again, with what was worked out for each meeting kept on it."""
    kept_raises = {}
    for one in ((before or {}).get("today") or []) + ((before or {}).get("tomorrow") or []):
        # One whose Slack lines were chosen under an older rule, or that read nothing, is left
        # off, so it is worked out again (`redo_raise`): the mail's reading comes back from
        # what was kept.
        if isinstance(one.get("raise"), dict) and not redo_raise(one["raise"]):
            kept_raises[(one.get("calendar_id"), one.get("id"))] = one["raise"]
    for one in (part.get("today") or []) + (part.get("tomorrow") or []):
        got = kept_raises.get((one.get("calendar_id"), one.get("id")))
        if got is not None:
            one["raise"] = got
    return part


#: The answers the brief's open event can give an invitation, and how each is said.
ANSWERS = {"accepted": "Going", "declined": "Not going", "tentative": "Maybe"}


def _event_ids(calendar_id, event_id) -> tuple[str, str]:
    calendar_id, event_id = str(calendar_id or "").strip(), str(event_id or "").strip()
    if not calendar_id or not event_id or len(calendar_id) > 300 or len(event_id) > 300:
        raise Refused("That event is not one the brief can find.")
    return calendar_id, event_id


def _services(who, google):
    if google is None:
        raise Refused("Google is not set up here, so the calendar cannot be read.")
    return google(who)


async def event_whole(who, *, google, zone, calendar_id, event_id) -> dict:
    """One event of the brief's calendar, read again from Google, whole.

    What it opens to when pressed (fr_1da7cddc045b, 30 September 2026: "click
    any event and get a modal ... all the details for the events, including
    the description, the people who are invited, and the ability to confirm
    or reject my presence"). Read again rather than taken from the kept brief,
    so the answers are the ones Google has now.
    """
    from .google_api import GoogleSaidNo

    calendar_id, event_id = _event_ids(calendar_id, event_id)
    zone = zone or clock.zone_of(who)
    with clock.person(who, zone):
        services = _services(who, google)
        try:
            one = await services.calendar.event(calendar_id, event_id)
        except GoogleSaidNo as exc:
            raise Refused(_google_trouble(exc, "event")) from exc
        today = datetime.now(zone).date()
        return _an_event(one, today, zone)


async def answer_event(who, *, google, zone, calendar_id, event_id, response) -> dict:
    """Answer an invitation on the brief: going, not going or maybe.

    Sent to Google as this calendar's own answer, with the organiser told, as
    pressing Yes or No in Google Calendar does. The brief kept for today is
    changed to match, so it says the new answer after a reload too. What the
    event is now comes back.
    """
    from .google_api import CannotDoThat, GoogleSaidNo

    if response not in ANSWERS:
        raise Refused("An invitation is answered going, not going or maybe.")
    calendar_id, event_id = _event_ids(calendar_id, event_id)
    zone = zone or clock.zone_of(who)
    with clock.person(who, zone):
        services = _services(who, google)
        try:
            _before, after, _changes = await services.calendar.change(
                calendar_id, event_id, response=response, notify=True)
        except CannotDoThat as exc:
            raise Refused(str(exc)) from exc
        except GoogleSaidNo as exc:
            raise Refused(_google_trouble(exc, "event")) from exc
        today = datetime.now(zone).date()
        event = _an_event(after, today, zone)
    from asgiref.sync import sync_to_async

    await sync_to_async(_answered_in_kept)(who, today.isoformat(), calendar_id, event_id,
                                           event["response"])
    return event


def _answered_in_kept(who, day: str, calendar_id: str, event_id: str, response: str) -> None:
    from .models import MorningBrief

    rows = MorningBrief.objects.filter(user_id=str(who.user_id), org_id=who.org_id or "", day=day)
    for row in rows:
        try:
            brief = json.loads(row.data)
        except (TypeError, ValueError):
            continue
        cal = brief.get("calendar") or {}
        hit = False
        for one in (cal.get("today") or []) + (cal.get("tomorrow") or []):
            if one.get("id") == event_id and one.get("calendar_id") == calendar_id:
                one["response"] = response
                for guest in one.get("guests") or []:
                    if guest.get("me"):
                        guest["response"] = response
                hit = True
        if hit:
            MorningBrief.objects.filter(pk=row.pk).update(
                data=json.dumps(brief, ensure_ascii=False))


def _google_trouble(exc, what: str) -> str:
    from .google_oauth import NeedsReconnect, NotConnected

    if isinstance(exc, NotConnected):
        return "Google is not connected. Connect it in Settings to see your " + what + " here."
    if isinstance(exc, NeedsReconnect):
        return "Google has withdrawn the connection. Connect it again in Settings."
    log.warning("the morning brief could not read the %s: %s", what, exc)
    said = re.sub(r"\s+", " ", str(exc)).strip()[:220]
    return f"Your {what} could not be read just now" + (f": {said}" if said else ".")


async def _weather(http, settings: dict, zone) -> dict:
    """Today where the person is: now, the high and low, rain, and the light."""
    if settings.get("lat") is None or settings.get("lon") is None:
        return {"ok": False, "no_place": True, "note": NO_PLACE}
    try:
        got = await http.get(WEATHER_URL, params={
            "latitude": settings["lat"], "longitude": settings["lon"],
            "current": "temperature_2m,apparent_temperature,weather_code,wind_speed_10m",
            "hourly": "precipitation_probability,weather_code",
            "daily": "weather_code,temperature_2m_max,temperature_2m_min,"
                     "precipitation_probability_max,sunrise,sunset",
            "timezone": zone.key, "forecast_days": 1})
        got.raise_for_status()
        body = got.json()
        daily = body["daily"]
        current = body.get("current") or {}
        code = int(daily["weather_code"][0])
    except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as exc:
        log.warning("the morning brief could not read the weather: %s", exc)
        return {"ok": False, "note": "The weather could not be read just now."}
    words, picture = WEATHER_WORDS.get(code, ("", "🌡️"))
    now_code = current.get("weather_code")
    now_words = WEATHER_WORDS.get(int(now_code), ("", ""))[0] if now_code is not None else ""
    # When rain is first likely from here on, which is what an umbrella hangs on.
    rain_from = ""
    hours = (body.get("hourly") or {}).get("time") or []
    chances = (body.get("hourly") or {}).get("precipitation_probability") or []
    this_hour = datetime.now(zone).strftime("%Y-%m-%dT%H:00")
    for at, chance in zip(hours, chances):
        if at >= this_hour and chance is not None and chance >= 50:
            rain_from = at[11:16]
            break

    def whole(value):
        return round(value) if isinstance(value, (int, float)) else None

    return {"ok": True, "place": settings["place"],
            "at": [settings["lat"], settings["lon"]], "words": words, "picture": picture,
            "high": whole(daily["temperature_2m_max"][0]),
            "low": whole(daily["temperature_2m_min"][0]),
            "rain": whole((daily.get("precipitation_probability_max") or [None])[0]),
            "rain_from": rain_from,
            "now": whole(current.get("temperature_2m")),
            "feels": whole(current.get("apparent_temperature")),
            "now_words": now_words,
            "wind": whole(current.get("wind_speed_10m")),
            "sunrise": str((daily.get("sunrise") or [""])[0])[11:16],
            "sunset": str((daily.get("sunset") or [""])[0])[11:16]}


def _text(node, tag: str) -> str:
    found = node.find(tag)
    return html.unescape((found.text or "").strip()) if found is not None and found.text else ""


def headlines(feed: str, most: int = 3) -> list[dict]:
    """The first stories of an RSS feed, in the order the newsroom put them."""
    root = ET.fromstring(feed)
    out = []
    for item in root.iter("item"):
        title = _text(item, "title")
        if not title:
            continue
        link = _text(item, "link").split("?at_medium")[0]
        out.append({"title": title, "summary": _text(item, "description")[:400],
                    "link": link, "when": _text(item, "pubDate")})
        if len(out) >= most:
            break
    return out


# --- asking a model ---------------------------------------------------------


async def _ask(who, purpose: str, system: str, text: str, max_tokens: int) -> dict | None:
    """One question to the model the Models page has for the morning brief, whichever
    company's it is (`rouh/llm.py`), answered with one JSON object.

    None when its model cannot be asked here, or its answer had no object in it;
    raises when it could not be reached, which the caller turns into a line on the page.
    """
    from . import llm

    try:
        got = await llm.ask("morning_brief", system=system,
                            messages=[{"role": "user", "content": text}], max_tokens=max_tokens,
                            who=who, org_id=(who.org_id if who is not None else None) or None,
                            purpose=purpose, timeout=MODEL_SECONDS, read_only=True)
    except llm.Cannot:
        return None
    found = re.search(r"\{.*\}", got.text, re.S)
    try:
        got = json.loads(found.group(0)) if found else None
    except ValueError:
        got = None
    return got if isinstance(got, dict) else None


# --- the world ----------------------------------------------------------------

#: The first words of what the model picking the world stories is told, which
#: is also how the stand-in for the model knows it (`rouh/testing/fake_model.py`).
WORLD_ASK = "You pick the world news for a morning brief."

WORLD_SYSTEM = WORLD_ASK + f"""

You are given the stories in BBC News' world feed, numbered, in the order the
newsroom put them. Pick the {WORLD_STORIES} most significant of the day: the
ones that matter most to the most people and that someone who reads nothing
else today should know about - wars and peace, elections and governments
falling, disasters, the economy, decisions that change many lives. Prefer
significance over recency, three different stories over three angles on one,
and a reported story over a "Watch:" clip of the same thing. The newsroom's
order is a hint, not the answer.

Answer with one JSON object and nothing else: {{"picked": [n, n, n]}}, the
numbers of the stories, most significant first."""


#: How the world stories say they were picked by the newsroom, not by a model.
NEWSROOM = "the newsroom's own order"


def _story_id(one: dict) -> str:
    return one.get("link") or one.get("title") or ""


async def _world(http, who, before: dict | None = None) -> dict:
    """The three most significant stories in the BBC's world news today.

    The feed's own headlines and summaries, as they are. A model reads the
    whole feed and picks which three (`WORLD_SYSTEM`); with no model to ask,
    or no usable answer, they are the newsroom's own first three.

    `before` is the world part of the brief made before this one (`make`, its `base`).
    When the feed has no story in it that was not in the feed then, the
    stories picked then are kept exactly as they were and no model is asked
    (fr_e7c51081dc50: "if the same articles are in the search, no need to
    extract and summarize them"). The stories it read are kept as `pool`.
    """
    try:
        got = await http.get(WORLD_FEED)
        got.raise_for_status()
        pool = headlines(got.text, WORLD_POOL)
    except (httpx.HTTPError, ET.ParseError) as exc:
        log.warning("the morning brief could not read the world news: %s", exc)
        return {"ok": False, "note": "The world news could not be read just now."}
    if not pool:
        return {"ok": False, "note": "The world news feed had no stories in it."}
    ids = [_story_id(one) for one in pool]
    was = before or {}
    if (was.get("ok") and was.get("stories") and isinstance(was.get("pool"), list)
            and set(ids) <= set(was["pool"])
            and (was.get("picked_by") != NEWSROOM or len(pool) <= WORLD_STORIES)):
        return {k: v for k, v in was.items() if k != "source"}
    picked, by = [], NEWSROOM
    if len(pool) > WORLD_STORIES:
        listed = "\n\n".join(f"{n}. {one['title']}\n{one['summary']}"
                               for n, one in enumerate(pool, 1))
        try:
            said = await _ask(who, "brief_world", WORLD_SYSTEM, listed, 4000)
        except Exception as exc:
            log.warning("the morning brief could not have the world news picked: %s", exc)
            said = None
        for n in (said or {}).get("picked") or []:
            if isinstance(n, int) and 1 <= n <= len(pool) and pool[n - 1] not in picked:
                picked.append(pool[n - 1])
        if len(picked) >= WORLD_STORIES:
            by = "the most significant, picked from " + str(len(pool)) + " stories"
        else:
            picked = []
    stories = (picked or pool)[:WORLD_STORIES]
    return {"ok": True, "stories": stories, "picked_by": by, "pool": ids}


# --- AI, from the person's YouTube channels -----------------------------------

#: The first words of what the model condensing the videos is told, which is
#: also how the stand-in for the model knows it (`rouh/testing/fake_model.py`).
AI_ASK = "You write the AI news for a morning brief."

AI_SYSTEM = AI_ASK + f"""

You are given the transcripts of the newest videos from YouTube channels about
AI that the reader follows, each numbered, with its channel and title. Condense
them into {AI_ITEMS[0]} to {AI_ITEMS[1]} items of news: distinct developments -
a new model, a product, a research result, a deal, a policy - not one item per
video. When several videos cover the same thing, make it one item and credit
the video that covers it best. Leave out sponsor reads, channel housekeeping
and speculation with nothing new in it. Rank the items by how much they matter.

Each item has a headline of at most twelve words, a summary of one to three
plain sentences with the concrete facts (names, numbers, what changed), and
the number of the video it came from.

Answer with one JSON object and nothing else:
{{"items": [{{"headline": "...", "summary": "...", "video": n}}]}}"""


#: What the model is told when only some of the videos are new: the items
#: already written for the others stay as they are, and it writes the new ones.
AI_MORE_SYSTEM = AI_ASK + """

Some of the reader's newest videos were condensed into the brief already, and
those items stay exactly as they are; their headlines come first, under
"Already in the brief". You are given the transcripts of the videos that are
new since, each numbered, with its channel and title. Write items only for what
is new in these videos: 1 to 3 items of news, distinct developments - a new
model, a product, a research result, a deal, a policy - and nothing that is
already in the brief. Leave out sponsor reads, channel housekeeping and
speculation with nothing new in it. Rank the items by how much they matter.

Each item has a headline of at most twelve words, a summary of one to three
plain sentences with the concrete facts (names, numbers, what changed), and
the number of the video it came from.

Answer with one JSON object and nothing else:
{"items": [{"headline": "...", "summary": "...", "video": n}]}. When there
is nothing new worth an item, answer {"items": []}."""

#: The most items the new videos add to the ones kept, and the most there are.
AI_MORE_ITEMS, AI_MOST_ITEMS = 3, 8


def _feed_videos(feed: str, channel: dict, since: float) -> list[dict]:
    """A channel's new videos out of its feed, newest first, Shorts left out."""
    atom = "{http://www.w3.org/2005/Atom}"
    out = []
    for entry in ET.fromstring(feed).iter(atom + "entry"):
        link = entry.find(atom + "link")
        href = link.get("href", "") if link is not None else ""
        if "/shorts/" in href or "watch?v=" not in href:
            continue
        stamp = _text(entry, atom + "published")
        try:
            at = datetime.fromisoformat(stamp).timestamp()
        except ValueError:
            continue
        if at < since:
            continue
        out.append({"id": href.split("watch?v=")[1][:11], "title": " ".join(_text(entry, atom + "title").split()),
                    "channel": channel["name"], "link": href, "at": at})
    out.sort(key=lambda one: -one["at"])
    return out[:VIDEOS_A_CHANNEL]


async def _channel(http, channel: dict, since: float) -> list[dict]:
    got = await http.get(CHANNEL_FEED, params={"channel_id": channel["id"]})
    got.raise_for_status()
    return _feed_videos(got.text, channel, since)


async def _transcript(video: dict, store) -> str:
    from . import youtube

    found = await youtube.fetch_transcript(video["id"], store=store, use_browser=False)
    return found.text


def _since_words(since: float, zone) -> str:
    at = datetime.fromtimestamp(since, zone)
    return f"{at.strftime('%A')} {at.strftime('%H:%M')}"


def _names(names: list[str]) -> str:
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " or " + names[-1]


async def _ai(http, who, channels: list[dict], since: float, zone, before: dict | None) -> dict:
    """What the person's own AI channels on YouTube said since the last brief.

    Each channel's new videos (Shorts left out) since `since`, each video's
    captions, and one model reading them all into three to five items
    (`AI_SYSTEM`), each with the channel and a link to its video.

    `before` is the brief made before this one (`make`, its `base`). An item it has for a
    video that is still among the new ones is kept exactly as it was, and the
    model is asked only about videos it had not read (`AI_MORE_SYSTEM`), so
    the same videos are never condensed twice (fr_e7c51081dc50). Captions are
    kept in Rouh's database with every other transcript (`rouh/youtube_store.py`),
    so a video already read is not fetched again either.
    """
    out = {"ok": True, "items": [], "videos": [], "notes": [],
           "channels": [one["name"] for one in channels], "since": since,
           "since_words": _since_words(since, zone)}
    if not channels:
        return {**out, "ok": False, "note": "No YouTube channels are chosen for the AI news. "
                                            "Add them in Settings, under Morning brief."}
    found = await asyncio.gather(*(_channel(http, one, since) for one in channels),
                                 return_exceptions=True)
    videos, unread = [], []
    for channel, got in zip(channels, found):
        if isinstance(got, BaseException):
            log.warning("the morning brief could not read %s's videos: %s", channel["name"], got)
            unread.append(channel["name"])
        else:
            videos += got
    if unread:
        out["notes"].append(f"{_names(unread)} could not be read on YouTube just now.")
    if len(unread) == len(channels):
        return {**out, "ok": False, "note": "YouTube could not be reached just now, so there "
                                            "is no AI news from your channels."}
    if not videos:
        return {**out, "ok": False,
                "note": f"No new videos from {_names(out['channels'])} since "
                        f"{out['since_words']}."}
    from . import youtube_store

    store = youtube_store.Store.of(who)
    said = await asyncio.gather(*(_transcript(one, store) for one in videos), return_exceptions=True)
    heard = []
    for video, text in zip(videos, said):
        video = {k: video[k] for k in ("id", "title", "channel", "link", "at")}
        video["transcript"] = not isinstance(text, BaseException) and bool(text)
        out["videos"].append(video)
        if video["transcript"]:
            heard.append((video, text))
        else:
            log.warning("the morning brief could not fetch the transcript of %s: %s",
                        video["id"], text)
    if not heard:
        return {**out, "ok": False,
                "note": "The transcripts of the new videos could not be fetched, so they "
                        "could not be condensed. Here they are to watch."}
    if len(heard) < len(videos):
        missed = len(videos) - len(heard)
        out["notes"].append(f"{missed} of the {len(videos)} new videos had no transcript to "
                            "read, so " + ("it is" if missed == 1 else "they are")
                            + " only listed below.")
    ids = sorted(video["id"] for video, _text_ in heard)
    kept = (before or {}).get("ai") or {}
    links = {video["link"] for video, _text_ in heard}
    held = [one for one in kept.get("items") or [] if one.get("link") in links]
    read_then = set(kept.get("heard") or []) if held else set()
    fresh = [(video, text) for video, text in heard if video["id"] not in read_then]
    if held and not fresh:
        return {**out, "items": held, "heard": ids}
    if held:
        # Only the new videos are read by the model; what it wrote is added.
        already = "\n".join(f"- {one['headline']}" for one in held)
        listed = f"=== Already in the brief\n{already}\n\n" + "\n\n".join(
            f"=== Video {n}: {video['channel']} - {video['title']}\n{text[:TRANSCRIPT_CHARS]}"
            for n, (video, text) in enumerate(fresh, 1))
        try:
            answer = await _ask(who, "brief_ai", AI_MORE_SYSTEM, listed, 16000)
        except Exception as exc:
            log.warning("the morning brief could not have the new videos condensed: %s", exc)
            answer = None
        added = _ai_items(answer, fresh)[:AI_MORE_ITEMS]
        if answer is None:
            out["notes"].append("The newest videos could not be condensed just now, so they "
                                "are only listed below.")
        # Only what was read is counted as read: a video that could not be
        # condensed now is asked about again next time.
        done = sorted(read_then & set(ids)) if answer is None else ids
        return {**out, "items": (held + added)[:AI_MOST_ITEMS], "heard": done}
    listed = "\n\n".join(
        f"=== Video {n}: {video['channel']} - {video['title']}\n{text[:TRANSCRIPT_CHARS]}"
        for n, (video, text) in enumerate(heard, 1))
    try:
        answer = await _ask(who, "brief_ai", AI_SYSTEM, listed, 16000)
    except Exception as exc:
        log.warning("the morning brief could not have the videos condensed: %s", exc)
        return {**out, "ok": False, "note": "The videos could not be condensed just now. "
                                            "Here they are to watch.", "heard": ids}
    if answer is None:
        return {**out, "ok": False, "note": "No model could be asked to condense the videos. "
                                            "Here they are to watch.", "heard": ids}
    items = _ai_items(answer, heard)[:AI_ITEMS[1]]
    if not items:
        return {**out, "ok": False, "note": "The videos could not be condensed just now. "
                                            "Here they are to watch.", "heard": ids}
    return {**out, "items": items, "heard": ids}


def _ai_items(answer: dict | None, heard: list[tuple[dict, str]]) -> list[dict]:
    """The model's items, each tied to the video it names by its number in `heard`."""
    items = []
    for one in (answer or {}).get("items") or []:
        n = one.get("video") if isinstance(one, dict) else None
        headline = " ".join(str((one or {}).get("headline") or "").split())[:160]
        if not (isinstance(n, int) and 1 <= n <= len(heard) and headline):
            continue
        video = heard[n - 1][0]
        items.append({"headline": headline,
                      "summary": " ".join(str(one.get("summary") or "").split())[:700],
                      "channel": video["channel"], "title": video["title"],
                      "link": video["link"]})
    return items


# --- today in history ----------------------------------------------------------

#: The first words of what the model picking the events is told, which is also
#: how the stand-in for the model knows it (`rouh/testing/fake_model.py`).
HISTORY_ASK = "You pick today in history for a morning brief."

HISTORY_SYSTEM = HISTORY_ASK + f"""

You are given things that happened on today's date in past years, numbered,
each with its year and, in brackets, what kind of thing it is: an event, a
birth, a death, a holiday, or a sentence found in a Wikipedia article about one
of the reader's own topics. After them are the reader's topics.

Pick only what truly belongs to one of the reader's topics, at most
{TOPIC_EVENTS}, and none at all when nothing does: an event that merely
happened on the day is not enough. A sentence found for one of the reader's own
topics belongs to it only when it says something that happened on this date
that is about that topic. Spread the picks across the topics rather than
giving one topic every place, and leave out anything grim with nothing to
learn from it. Order them by how much each mattered, the most significant
first - not by year.

Answer with one JSON object and nothing else:
{{"picked": [{{"n": 12, "topic": "Music"}}, ...]}}, each the number of the thing
and the name of the reader's topic it belongs to, written exactly as the topic
is listed."""

#: How Today in history says the model picked its events.
HISTORY_PICKED = "Picked for your topics from "

#: How each of Wikipedia's lists for the day is named to the model.
KIND_WORDS = {"events": "event", "births": "birth", "deaths": "death", "holidays": "holiday"}


def _year_of(value) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _day_lists(body: dict) -> dict[str, list[dict]]:
    """Wikipedia's lists for the day, each thing in them as {year, text, link, kind}.

    `events` is its own selection first, then the rest of its events. The link
    is the thing's own article where it names one (a title with a year in it,
    such as "2009 Sumatra earthquakes"), or else the first thing it links to;
    for a birth or a death, the person's. A holiday has no year.
    """
    def one(item, kind) -> dict | None:
        year, text = _year_of(item.get("year")), " ".join(str(item.get("text") or "").split())
        if (year is None and kind != "holidays") or not text:
            return None
        pages = [page for page in item.get("pages") or [] if isinstance(page, dict)]
        if kind in ("births", "deaths"):
            # The person, not the article about the year.
            own = next((page for page in pages
                        if not re.fullmatch(r"(AD[ _])?\d{1,4}([ _]BC)?", str(page.get("title")))),
                       pages[0] if pages else {})
        else:
            own = next((page for page in pages if re.search(r"\d{3,4}", str(page.get("title")))),
                       pages[0] if pages else {})
        link = (((own.get("content_urls") or {}).get("desktop") or {}).get("page") or "")
        return {"year": year, "text": text[:400], "kind": kind,
                "link": link if link.startswith("https://") else ""}

    def all_of(key, kind) -> list[dict]:
        found = [one(item, kind) for item in body.get(key) or [] if isinstance(item, dict)]
        return [item for item in found if item]

    out = {kind: all_of(kind, kind) for kind in ("births", "deaths", "holidays")}
    selected = all_of("selected", "events")
    seen = {item["text"] for item in selected}
    out["events"] = selected + [item for item in all_of("events", "events")
                                if item["text"] not in seen]
    return out


_SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(])")


async def _found_for(http, topic: str, today: date) -> list[dict]:
    """What Wikipedia's articles say happened on this date about one of the person's own topics.

    Wikipedia is searched for the topic beside the date written either way
    ("October 19" or "19 October"), and each of the first articles it finds is
    read for sentences that give the date with a year after it ("On October
    19, 2011, Apple employees held a private memorial service for Jobs"). Each
    is Wikipedia's own sentence, its year and a link to its article, as
    {year, text, link, kind, topic}; whether it is about the topic is the
    model's to judge (`HISTORY_SYSTEM`). Nothing, rather than an error, when
    Wikipedia cannot be read.
    """
    month, day = today.strftime("%B"), today.day
    said = re.compile(rf"\b(?:{month} {day},?|{day} {month},?)\s+(?:in\s+)?(\d{{3,4}})\b")
    try:
        got = await http.get(WIKI_API, params={
            "action": "query", "list": "search", "format": "json", "srlimit": CUSTOM_ARTICLES,
            "srprop": "", "srsearch": f'"{topic}" ("{month} {day}" OR "{day} {month}")'})
        got.raise_for_status()
        titles = [str(one.get("title") or "") for one in
                  ((got.json().get("query") or {}).get("search") or []) if isinstance(one, dict)]
    except (httpx.HTTPError, ValueError, AttributeError) as exc:
        log.warning("the morning brief could not search Wikipedia for %r: %s", topic, exc)
        return []
    out, seen = [], set()
    for title in [one for one in titles if one][:CUSTOM_ARTICLES]:
        try:
            got = await http.get(WIKI_API, params={
                "action": "query", "prop": "extracts", "explaintext": 1, "format": "json",
                "redirects": 1, "titles": title})
            got.raise_for_status()
            pages = (got.json().get("query") or {}).get("pages") or {}
            text = str(next(iter(pages.values()), {}).get("extract") or "")
        except (httpx.HTTPError, ValueError, AttributeError) as exc:
            log.warning("the morning brief could not read %r on Wikipedia: %s", title, exc)
            continue
        link = "https://en.wikipedia.org/wiki/" + title.replace(" ", "_")
        for line in text.splitlines():
            if not line.strip() or line.lstrip().startswith("="):
                continue
            for sentence in _SENTENCE_END.split(line.strip()):
                found = said.search(sentence)
                year = int(found.group(1)) if found else 0
                words = " ".join(sentence.split())
                if not found or year > today.year or words in seen or len(words) < 25:
                    continue
                seen.add(words)
                out.append({"year": year, "text": words[:400], "link": link,
                            "kind": "custom", "topic": topic})
                if len(out) >= CUSTOM_FOUND:
                    return out
    return out


def _chosen(settings: dict) -> dict:
    return {"topics": list(settings.get("topics") or []), "custom": list(settings.get("custom") or [])}


async def _history(http, who, settings: dict, today: date, before: dict | None = None) -> dict:
    """What happened on this date that belongs to the person's topics, most significant first.

    The topics are the ones picked with the gear on the section
    (`HISTORY_TOPICS`, `save_topics`), and topics of the person's own, each
    looked for in Wikipedia's articles (`_found_for`). With none picked there
    are no events, and the page asks for topics instead (`choose`), as Petar
    asked on 19 October 2026 (fr_a1b47c17f8cf: "If I haven't selected a topic,
    I don't get events, instead I get a prompt to select my topic of
    interest"). Otherwise a model reads Wikipedia's "On this day" lists that
    the topics need, and what was found for the person's own, and picks only
    what belongs to a topic, each named with its topic (`HISTORY_SYSTEM`):
    Wikipedia's own words, with its year and a link. As few as belong, and
    none is said so; with no model to ask, nothing is guessed and the page says
    so.

    `before` is the brief made before this one (`make`, its `base`): when it is
    today's and its events were picked for the same topics, they are kept
    exactly as they were (fr_e7c51081dc50).
    """
    chosen = _chosen(settings)
    words = f"{today.day} {today.strftime('%B')}"
    if not chosen["topics"] and not chosen["custom"]:
        return {"ok": True, "choose": True, "events": [], "words": words, **chosen}
    was = (before or {}).get("history") or {}
    if ((before or {}).get("day") == today.isoformat() and was.get("ok")
            and str(was.get("picked_by") or "").startswith(HISTORY_PICKED)
            and was.get("topics") == chosen["topics"] and was.get("custom") == chosen["custom"]):
        return {k: v for k, v in was.items() if k != "source"}
    try:
        got = await http.get(f"{HISTORY_FEED}/{today.month:02d}/{today.day:02d}")
        got.raise_for_status()
        lists = _day_lists(got.json())
    except (httpx.HTTPError, ValueError, AttributeError) as exc:
        log.warning("the morning brief could not read today in history: %s", exc)
        return {"ok": False, **chosen,
                "note": "Today in history could not be read from Wikipedia just now."}
    # Each topic reads only the lists it needs; a topic of one's own may be
    # anything, so it reads them all but the holidays.
    kinds = {kind for one in HISTORY_TOPICS if one["id"] in chosen["topics"] for kind in one["kinds"]}
    if chosen["custom"]:
        kinds |= {"events", "births", "deaths"}
    pool, seen = [], set()
    for topic in chosen["custom"]:
        for one in await _found_for(http, topic, today):
            if one["text"] not in seen:
                seen.add(one["text"])
                pool.append(one)
    for kind in ("events", "births", "deaths", "holidays"):
        if kind in kinds:
            pool.extend(one for one in lists.get(kind) or [] if one["text"] not in seen)
    names = [TOPIC_NAMES[one] for one in chosen["topics"]] + chosen["custom"]
    by_name = {name.lower(): name for name in names}
    if not pool:
        return {"ok": True, "events": [], "words": words, **chosen,
                "picked_by": HISTORY_PICKED + "nothing: Wikipedia had nothing for today's date"}
    lines, used = [], 0
    for n, one in enumerate(pool, 1):
        kind = f"found for {one['topic']}" if one["kind"] == "custom" else KIND_WORDS[one["kind"]]
        line = f"{n}. {one['year'] if one['year'] is not None else 'every year'} [{kind}]: {one['text']}"
        used += len(line) + 1
        if used > POOL_CHARS:
            break
        lines.append(line)
    topics_said = "\n".join(f"- {name}" for name in names)
    try:
        said = await _ask(who, "brief_history", HISTORY_SYSTEM,
                          f"On {words}:\n\n" + "\n".join(lines)
                          + f"\n\n=== The reader's topics\n\n{topics_said}", 4000)
    except Exception as exc:
        log.warning("the morning brief could not have today in history picked: %s", exc)
        said = None
    if said is None or not isinstance(said.get("picked"), list):
        return {"ok": False, **chosen, "words": words,
                "note": "The events for your topics could not be picked just now. Update tries again."}
    picked, taken = [], set()
    for one in said["picked"]:
        n = one.get("n") if isinstance(one, dict) else None
        if not isinstance(n, int) or isinstance(n, bool) or not 1 <= n <= len(lines) or n in taken:
            continue
        name = by_name.get(str(one.get("topic") or "").strip().lower())
        if name is None:
            continue
        taken.add(n)
        event = {k: v for k, v in pool[n - 1].items() if k in ("year", "text", "link")}
        picked.append({**event, "topic": name})
        if len(picked) >= TOPIC_EVENTS:
            break
    return {"ok": True, "events": picked, "words": words, **chosen,
            "picked_by": HISTORY_PICKED + f"{len(lines)} things that happened on this date"}


_ATOM = "{http://www.w3.org/2005/Atom}"
#: The post's own words in Reddit's feed: its body, between these marks,
#: before the "submitted by" line Reddit adds.
_JOKE_BODY = re.compile(r'<div class="md">(.*?)</div>', re.S)
_JOKE_ID = re.compile(r"/comments/([a-z0-9]+)/")


def _joke_text(markup: str) -> str:
    """A post's body as its own words: paragraphs a line each, tags gone, nothing reworded."""
    paras = re.findall(r"<p>(.*?)</p>", markup, re.S) or [markup]
    lines = [html.unescape(re.sub(r"<[^>]+>", "", one)).strip() for one in paras]
    return "\n".join(line for line in lines if line)


def jokes(feed: str) -> list[dict]:
    """r/dadjokes' top posts in their feed's order, most voted first, each a joke or nothing.

    A post is a joke when it is words alone, short and fit for a morning page:
    one with a picture or a link in it, a long story or a word in `JOKE_CRUDE`
    is left out rather than cut or cleaned up.
    """
    out = []
    for entry in ET.fromstring(feed).findall(f"{_ATOM}entry"):
        anchor = entry.find(f"{_ATOM}link")
        link = anchor.get("href") or "" if anchor is not None else ""
        found = _JOKE_ID.search(link)
        setup = _text(entry, f"{_ATOM}title")
        # The body as Reddit's own markup, its entities still in it (`_joke_text`).
        content = entry.findtext(f"{_ATOM}content") or ""
        body = _JOKE_BODY.search(content)
        if not found or not setup:
            continue
        if body is None and "<img" in content:
            continue
        markup = body.group(1) if body else ""
        if "<a " in markup or "<img" in markup or "<table" in markup:
            continue
        punchline = _joke_text(markup) if markup else ""
        if len(setup) + len(punchline) > JOKE_CHARS or JOKE_CRUDE.search(setup + " " + punchline):
            continue
        out.append({"id": found.group(1), "setup": setup, "punchline": punchline,
                    "link": link.split("?")[0]})
    return out


def _jokes_told(who, today: date) -> set[str]:
    """The ids of the jokes this person's briefs told in the last `JOKE_DAYS` days."""
    from .models import MorningBrief

    since = (today - timedelta(days=JOKE_DAYS)).isoformat()
    told = set()
    for data in (MorningBrief.objects.filter(user_id=str(who.user_id), org_id=who.org_id or "",
                                             day__gte=since, day__lt=today.isoformat())
                 .values_list("data", flat=True)):
        try:
            joke = (json.loads(data) or {}).get("joke") or {}
        except (TypeError, ValueError):
            continue
        if joke.get("id"):
            told.add(joke["id"])
    return told


async def _joke(http, who, today: date, before: dict | None = None) -> dict | None:
    """Today's dad joke, from r/dadjokes, or None when there is none to tell.

    Petar, 20 October 2026 (fr_6fb4aad2f62c): "do not invent jokes, get them
    from somewhere. preferably rated high, rather than random." So it is the
    most voted post of r/dadjokes' week (`JOKE_FEED`, in Reddit's own order of
    votes) that this person's briefs have not told in `JOKE_DAYS` days, and the
    month's when the week has none left: its setup is the post's title and its
    punchline the post's own words, exactly as they are there (`jokes`). No
    model is asked anything. Today's brief made again keeps today's joke.
    With Reddit not answering, or nothing to tell, there is no joke and no
    section, and nothing is said about it.
    """
    from asgiref.sync import sync_to_async

    was = (before or {}).get("joke")
    if (before or {}).get("day") == today.isoformat() and was and was.get("ok"):
        return {k: v for k, v in was.items() if k != "source"}
    told = await sync_to_async(_jokes_told)(who, today)
    for span, words in JOKE_SPANS:
        try:
            got = await http.get(JOKE_FEED, params={"t": span, "limit": 50},
                                 headers={"User-Agent": "Rouh morning brief (+https://rouh.land)"})
            got.raise_for_status()
            found = jokes(got.text)
        except (httpx.HTTPError, ET.ParseError) as exc:
            log.warning("the morning brief could not read r/dadjokes: %s", exc)
            return None
        for rank, one in enumerate(found, 1):
            if one["id"] not in told:
                return {"ok": True, **one, "rank": rank, "span": words}
    return None


def _since(who, today: date, zone) -> float:
    """Where "new" starts for the videos: the last brief before today, in bounds."""
    from .models import MorningBrief

    now = time.time()
    last = (MorningBrief.objects
            .filter(user_id=str(who.user_id), org_id=who.org_id or "", day__lt=today.isoformat())
            .order_by("-day").values_list("made_at", flat=True).first())
    if not last:
        return now - SINCE_FIRST
    return min(max(float(last), now - SINCE_MOST), now - SINCE_LEAST)


def _sender(value: str) -> str:
    """The name in "Ana Ivanova <ana@x.test>", or the address when there is no name."""
    value = str(value or "").strip()
    found = re.match(r'^\s*"?([^"<]+?)"?\s*<[^>]+>\s*$', value)
    return (found.group(1) if found else value)[:80]


async def _mail(services) -> dict:
    """How much is unread, and the newest unread mail from the last day."""
    if services is None:
        return {"ok": False, "note": "Google is not connected, so your inbox is not here."}
    try:
        counts, newest = await asyncio.gather(
            services.gmail.inbox_counts(),
            services.gmail.recent(4, "in:inbox is:unread newer_than:1d"))
    except Exception as exc:
        return {"ok": False, "note": _google_trouble(exc, "inbox")}
    return {"ok": True, "unread": counts.get("unread", 0),
            "newest": [{"from": _sender(one.get("from")),
                        "subject": (one.get("subject") or "(no subject)")[:200],
                        "link": "https://mail.google.com/mail/u/0/#inbox/"
                                + (one.get("thread_id") or one.get("id") or "")}
                       for one in newest[:3]]}


def _reminders(who, zone=None) -> dict:
    """Rouh's reminders yesterday, today and tomorrow, each day in time order.

    Petar, 3 October 2026 (fr_3c7faab7e0ce): "Maybe we should include
    reminders as a section in the morning routine and in the doodle? Like
    birthdays- yesterday, today highlighted, and tomorrow". So it is the three
    days Birthdays has (`birthdays.DAYS`), and each reminder is there on
    every one of them it is said: a one-off on the day it is due, or was said
    when it is done; a repeating one on each day its rule falls on, from the
    moment it was made. Each is its one-line title and never its description:
    Petar, 8 October 2026 (fr_b6dabdcc28e2), "my morning brief should have just
    the one liner". A paused one is in the past it was said in and not in
    the future it will not be. Read again every time the page opens
    (`reminders_again`), so one set at noon is in the brief straight away.
    One about Rouh itself that repeats, such as the nightly runs, is not here
    (`reminders.in_brief`, Petar, 18 October 2026): what they did is in the Report.
    """
    from . import reminders

    zone = zone or clock.zone_of(who)
    with clock.person(who, zone):
        now = datetime.now(zone)
        today = now.date()
        days = {key: today + timedelta(days=gap) for key, _words, gap in birthdays.DAYS}
        found: dict[str, list[dict]] = {key: [] for key in days}
        for row in reminders.rows(who):
            if not reminders.in_brief(row):
                continue
            rule = reminders.Rule.of(row)
            for key, day in days.items():
                at = _reminder_on(row, rule, day, now, zone)
                if at is None:
                    continue
                found[key].append({"at": at.timestamp(), "time": at.strftime("%H:%M"),
                                   "what": reminders.title_of(row), "kind": row.kind,
                                   # Made for a trusted contact under their Clockwork grant.
                                   "owner": reminders.owner_name(row),
                                   "repeats": "" if rule.repeat == "once"
                                   else reminders.repeat_words(rule)})
    out = []
    for key, words, _gap in birthdays.DAYS:
        day = days[key]
        out.append({"key": key, "words": words, "date": day.isoformat(),
                    "date_words": f"{day.strftime('%A')} {day.day} {day.strftime('%B')}",
                    "items": sorted(found[key], key=lambda one: one["at"])[:12]})
    return {"ok": True, "days": out}


def _reminder_on(row, rule, day: date, now: datetime, zone) -> datetime | None:
    """When a reminder is said on this day, on the person's clock, or None if it is not."""
    if rule.repeat == "once":
        when = row.next_at if row.state != "done" else row.last_at
        if row.state == "paused" and row.next_at and row.next_at > now.timestamp():
            return None
        at = datetime.fromtimestamp(when, zone) if when else None
        return at if at is not None and at.date() == day else None
    if not rule.fits(day):
        return None
    h, m = rule.hm()
    at = datetime(day.year, day.month, day.day, h, m, tzinfo=zone)
    if at.timestamp() < (row.created_at or 0) - 60:
        return None
    if at <= now and row.state == "paused" and (row.updated_at or 0) < at.timestamp():
        # Paused before then, so it was not said.
        return None
    if at > now and (row.state != "on" or not row.next_at or row.next_at > at.timestamp() + 60):
        # Still to come: only when it is really due then.
        return None
    return at


async def reminders_again(who, *, zone, brief: dict) -> dict:
    """Today's reminders read again and put into the brief as it is handed to the page.

    They are Rouh's own rows, so reading them costs nothing, and a brief made at
    seven would otherwise not have the reminder set at noon.
    """
    from asgiref.sync import sync_to_async

    try:
        part = await sync_to_async(_reminders)(who, zone)
    except Exception:
        log.exception("the morning brief's reminders failed")
        part = {"ok": False, "note": "The reminders part of the brief could not be made."}
    part["source"] = SOURCES["reminders"]
    brief["reminders"] = part
    return part


# --- the Report: what ran while the person slept ---------------------------------------------

#: How long before the last brief a Synapse attempt may have started and still be last night's.
REPORT_SLACK = 6 * 3600


def _report_since(who, today: date) -> float:
    """Where the Report starts: the last brief made before today, or a day ago when there is none."""
    from .models import MorningBrief

    last = (MorningBrief.objects
            .filter(user_id=str(who.user_id), org_id=who.org_id or "", day__lt=today.isoformat())
            .order_by("-day").values_list("made_at", flat=True).first())
    return float(last) if last else time.time() - 24 * 3600


def _synapse_report(who, since: float) -> dict | None:
    """Last night's Synapse attempt in one plain paragraph, or why there was none. None where there is no loop."""
    from . import reminders
    from .synapse import db as synapse_db, improvements, nightly

    if not synapse_db.ready() or not improvements.ready():
        return None
    org, user = str(who.org_id), str(who.user_id)
    improvements.settle(org, user, run_state=nightly.run_state)
    scheduled = reminders.server_row(who, nightly.JOB)
    rows = [r for r in improvements.listing(org, user, 10)
            if r.get("source") != "backfilled" and (improvements.epoch(r.get("started_at")) or 0) >= since - REPORT_SLACK]
    if rows:
        row = rows[0]
        d = row.get("decision") or {}
        return {"number": row["number"], "outcome": row["outcome"],
                "outcome_words": improvements.OUTCOMES.get(row["outcome"], row["outcome"]),
                "idea": row.get("chosen") or "", "paragraph": improvements.paragraph(row),
                "decision": d if d.get("question") and not d.get("answer") else None,
                "address": f"/synapse/improvements/{row['number']}"}
    if scheduled is None:
        return None
    if scheduled.state == "paused":
        words = "The nightly Synapse run is paused, so nothing ran last night. Resume it in Clockwork."
    elif (scheduled.created_at or 0) > since:
        words = ("The nightly Synapse run is new: its first night is tonight at "
                 f"{reminders.Rule.of(scheduled).at_time or nightly.AT}.")
    elif scheduled.last_at and scheduled.last_at >= since and scheduled.last_said:
        words = f"The nightly Synapse run did not start last night: {scheduled.last_said}."
    else:
        words = "The nightly Synapse run did not start last night: Rouh was not running at its time."
    return {"number": None, "outcome": "none", "outcome_words": "Did not run", "idea": "", "paragraph": words,
            "decision": None, "address": "/synapse/improvements"}


def _report(who, since: float, zone=None) -> dict:
    """The Report: last night's Synapse attempt, then everything else scheduled that ran since the last brief.

    What came of a Clockwork item that is about Rouh and repeats is not here, the Synapse
    attempt included (`reminders.in_brief`). Petar, 18 October 2026: "The report with Rouh
    regular changes should also be removed from the morning brief. I can see those in
    notifications, so they don't need to be in the brief." What the people he gave authority
    decided for him, and Mutations' questions, stay.
    """
    from . import decisions, nightly_feature, nightly_refactor, reminders
    from .synapse import nightly

    zone = zone or clock.zone_of(who)
    try:
        loop = reminders.server_row(who, nightly.JOB)
        synapse = _synapse_report(who, since) if loop is None or reminders.in_brief(loop) else None
    except Exception:
        log.exception("the Report's Synapse part could not be read")
        synapse = {"number": None, "outcome": "none", "outcome_words": "Unknown", "idea": "", "decision": None,
                   "paragraph": "Last night's Synapse attempt could not be read just now.", "address": ""}
    ran = []
    for row in reminders.rows(who):
        if (not row.last_at or row.last_at < since or (row.kind == reminders.SERVER and row.job == nightly.JOB)
                or not reminders.in_brief(row)):
            continue
        at = datetime.fromtimestamp(row.last_at, zone)
        one = {"at": row.last_at, "time": at.strftime("%H:%M"),
               "day": "Yesterday" if at.date() < datetime.now(zone).date() else "Today",
               "what": reminders.title_of(row), "kind": row.kind, "said": (row.last_said or "")[:400]}
        if row.kind == reminders.SERVER and row.job == nightly_feature.JOB:
            # The night's one question, Accept or Reject and undo, drawn with its handle
            # under the line, while it waits (`decision_sources.NightlySource`).
            try:
                decisions.sync(who, kinds={"nightly", "genes"})
                # A night whose genes Mutations keeps is asked in its one line.
                one["decision"] = (decisions.newest_waiting(who, "genes")
                                   or decisions.newest_waiting(who, "nightly"))
            except Exception:
                log.exception("the Report's nightly feature decision could not be read")
        if row.kind == reminders.SERVER and row.job == nightly_refactor.JOB:
            # What the night refactored, with an Undo that reverts its commits (Petar, 15 October 2026).
            try:
                one["refactor"] = nightly_refactor.report_of(who, since)
            except Exception:
                log.exception("the Report's refactoring night could not be read")
        ran.append(one)
    ran.sort(key=lambda one: one["at"])
    # What the people he gave authority decided for him since the last brief, what they
    # tried that was not theirs, and what was held for him (`rouh/delegation.py`).
    delegated = []
    try:
        from . import delegation

        for a in delegation.digest(who.user_id, who.org_id, since):
            at = datetime.fromtimestamp(a["at"], zone)
            delegated.append({"time": at.strftime("%H:%M"),
                              "day": "Yesterday" if at.date() < datetime.now(zone).date()
                              else "Today", "name": a["name"], "outcome": a["outcome"],
                              "said": a["said"] or a["why"], "words": a["words"][:400],
                              "why": a["why"] if a["outcome"] != "done" else ""})
    except Exception:
        log.exception("the Report's delegated decisions could not be read")
    # Mutations had a part here, the morning deck's size and the shelf, until the deck was taken
    # out on 19 October 2026 (fr_650809f11685). A trial's result is never brought here (N1).
    return {"ok": True, "since": since, "synapse": synapse, "ran": ran[:20],
            "delegated": delegated}


async def report_again(who, *, zone, brief: dict) -> dict:
    """The Report read again as the brief is handed to the page: a night's run may finish after seven."""
    from asgiref.sync import sync_to_async

    try:
        today = date.fromisoformat(brief["day"])
        since = await sync_to_async(_report_since)(who, today)
        part = await sync_to_async(_report)(who, since, zone)
    except Exception:
        log.exception("the morning brief's report failed")
        part = {"ok": False, "note": "The report part of the brief could not be made."}
    part["source"] = SOURCES["report"]
    brief["report"] = part
    return part


def _first_name(who) -> str:
    """What the page calls the person, by the welcome's own rule ("Hello, Alex")."""
    from .models import User
    from .web.views import _greeting_name

    user = User.objects.filter(pk=who.user_id, org_id=who.org_id).first()
    return _greeting_name(user) if user else ""


#: The parts an Update says changed or not, in the order the page draws them,
#: and how each is named. The reminders and the Report are left out: they are
#: read afresh every time the page opens, so they are never behind.
CHANGES = {"weather": "Weather", "calendar": "Calendar", "slack": "Slack", "world": "World News",
           "ai": "AI", "history": "Today in history", "birthdays": "Birthdays"}

#: What of the weather is the day's forecast, which is what an Update says
#: changed; the reading of the moment (now, feels like, wind) always moves.
WEATHER_DAY = ("ok", "place", "words", "high", "low", "rain", "sunrise", "sunset", "note")


def _changed(before: dict, parts: dict) -> list[str]:
    """Which of `CHANGES` came out other than they were in `before`."""
    def what(key, part):
        part = dict(part or {})
        part.pop("source", None)
        if key == "weather":
            part = {k: part.get(k) for k in WEATHER_DAY}
        if key == "slack":
            # The lines by what waits, not by the verdicts kept to reuse.
            part = [(one.get("key"), one.get("ts")) for one in part.get("items") or []]
        elif key == "ai":
            # The videos by their own ids: an item is what changes the news.
            part = {**{k: part.get(k) for k in ("ok", "items", "note", "notes")},
                    "videos": [one.get("id") for one in part.get("videos") or []]}
        return json.dumps(part, sort_keys=True, ensure_ascii=False, default=str)

    return [key for key in CHANGES if what(key, before.get(key)) != what(key, parts.get(key))]


async def make(who, *, google=None, zone=None, scheduled: bool = False) -> dict:
    """Today's brief for this person, made now, kept, and handed back.

    `google` turns an identity into its Google services (`GoogleClients.for_user`),
    or is None where Google is not set up at all. `zone` is the clock of the
    page asking for it (`zone_for_page`); without one it is the person's last
    known clock, which is what the morning loop has.

    Every part is read again from its source, and the work a model does is
    only done again for what is new since the brief made before this one
    (`make`, its `base`): a meeting already worked out, world news with no story that
    was not there then, videos already condensed and today's history are all
    kept exactly as they were (fr_e7c51081dc50, 9 October 2026: "We don't want
    to generate new content that replaces the old content on the same thing").

    Pressed as Update on a brief already made today, it keeps the time that
    brief was made, and says when it was updated and which parts changed
    (`update`). `scheduled` is the morning loop's: that is the day's brief
    proper, said to be made at its own time.
    """
    from asgiref.sync import sync_to_async

    settings = await sync_to_async(settings_of)(who)
    zone = zone or clock.zone_of(who)
    with clock.person(who, zone):
        today = datetime.now(zone).date()
        before = await sync_to_async(kept)(who, today.isoformat())
        if before is not None and before.get("shape") != SHAPE:
            before = None
        base = before or await sync_to_async(latest)(who)
        since = await sync_to_async(_since)(who, today, zone)
        report_since = await sync_to_async(_report_since)(who, today)
        services = google(who) if google is not None else None
        async with _http() as http:
            (weather, calendar, world, ai, mail, due, history,
             bdays, report, waiting, joke) = await asyncio.gather(
                _weather(http, settings, zone),
                _calendar_and_raises(who, services, today, zone, (base or {}).get("calendar")),
                _world(http, who, (base or {}).get("world")),
                _ai(http, who, settings["channels"], since, zone, base),
                _mail(services), sync_to_async(_reminders)(who, zone),
                _history(http, who, settings, today, base),
                birthdays.make(who, services, today, zone),
                sync_to_async(_report)(who, report_since, zone),
                slack_brief.make(who, report_since, base),
                _joke(http, who, today, before), return_exceptions=True)
    parts = {}
    # What waits on him in Slack is there only when something does (`rouh/slack_brief.py`).
    if isinstance(waiting, BaseException):
        log.error("the morning brief's slack failed", exc_info=waiting)
    elif waiting is not None:
        waiting["source"] = waiting.get("workspace") or "Slack"
        parts["slack"] = waiting
    # So is the dad joke: a joke from r/dadjokes, or no section at all (`_joke`).
    if isinstance(joke, BaseException):
        log.error("the morning brief's joke failed", exc_info=joke)
    elif joke is not None:
        joke["source"] = SOURCES["joke"]
        parts["joke"] = joke
    for key, got in zip(("weather", "calendar", "world", "ai", "mail", "reminders", "history",
                         "birthdays", "report"),
                        (weather, calendar, world, ai, mail, due, history, bdays, report)):
        if isinstance(got, BaseException):
            log.error("the morning brief's %s failed", key, exc_info=got)
            got = {"ok": False, "note": f"The {key} part of the brief could not be made."}
        got["source"] = SOURCES[key]
        parts[key] = got
    now = time.time()
    brief = {"shape": SHAPE, "day": today.isoformat(),
             "day_words": f"{today.strftime('%A')} {today.day} {today.strftime('%B')}",
             "made_at": now, "zone": zone.key,
             "name": await sync_to_async(_first_name)(who),
             "settings": {k: settings[k] for k in ("on", "time", "place")},
             **parts}
    if before is not None and not scheduled:
        brief["made_at"] = before.get("made_at") or now
        brief["updated_at"] = now
        brief["update"] = {"at": now, "since": before.get("updated_at") or before.get("made_at"),
                           "changed": _changed(before, parts)}
    await sync_to_async(_keep)(who, brief)
    return brief


def _keep(who, brief: dict) -> None:
    from .models import MorningBrief

    MorningBrief.objects.bulk_create(
        [MorningBrief(user_id=str(who.user_id), org_id=who.org_id or "", day=brief["day"],
                      made_at=brief["made_at"], data=json.dumps(brief, ensure_ascii=False))],
        update_conflicts=True, unique_fields=["org_id", "user_id", "day"],
        update_fields=["made_at", "data"])


def kept(who, day: str) -> dict | None:
    """The brief this person already has for a day, or None."""
    from .models import MorningBrief

    row = (MorningBrief.objects.filter(user_id=str(who.user_id), org_id=who.org_id or "",
                                       day=day).first())
    if row is None:
        return None
    try:
        brief = json.loads(row.data)
    except (TypeError, ValueError):
        return None
    brief["sent_at"] = row.sent_at
    return brief


def latest(who) -> dict | None:
    """The newest brief this person has, of any day, that the page can draw; or None.

    What the page shows when today's is not made yet (fr_e7c51081dc50,
    9 October 2026: "A morning routine has been generated already by the last
    7am that has passed and I should be seeing the last generation"), and what
    the next one is made on (`make`).
    """
    from .models import MorningBrief

    days = (MorningBrief.objects.filter(user_id=str(who.user_id), org_id=who.org_id or "")
            .order_by("-day").values_list("day", flat=True)[:7])
    for day in days:
        brief = kept(who, day)
        if brief is not None and brief.get("shape") == SHAPE:
            return brief
    return None


async def birthdays_again(who, *, google, zone, brief: dict | None = None) -> dict:
    """Today's Birthdays read again, and put into today's kept brief.

    After a link is made or taken away, so the brief says the contact's name
    from then on, and for a brief kept before there was a Birthdays section,
    so it has one without the rest being made again.
    """
    from asgiref.sync import sync_to_async

    zone = zone or clock.zone_of(who)
    with clock.person(who, zone):
        today = datetime.now(zone).date()
        services = google(who) if google is not None else None
        try:
            part = await birthdays.make(who, services, today, zone)
        except Exception:
            log.exception("the morning brief's birthdays failed")
            part = {"ok": False, "note": "The birthdays part of the brief could not be made."}
        part["source"] = SOURCES["birthdays"]
    await sync_to_async(_put_part)(who, today.isoformat(), "birthdays", part)
    if brief is not None:
        brief["birthdays"] = part
    return part


async def calendar_again(who, *, google, zone) -> dict:
    """Today's calendar read again from Google, and put into today's kept brief.

    Every time the brief is opened (fr_854ef3f9eb57, 1 October 2026: "every
    time I open this page, the calendar refreshes"), so an event added or moved
    since seven is there without the rest of the brief being made again.
    """
    from asgiref.sync import sync_to_async

    zone = zone or clock.zone_of(who)
    with clock.person(who, zone):
        today = datetime.now(zone).date()
        services = google(who) if google is not None else None
        try:
            part = await _calendar(who, services, today, zone)
        except Exception:
            log.exception("the morning brief's calendar failed")
            part = {"ok": False, "note": "The calendar part of the brief could not be made."}
        part["source"] = SOURCES["calendar"]
    if part.get("ok"):
        # A Google that could not be reached just now leaves the kept one as it was.
        # What to raise at each meeting stays as it was made (`_carry_raises`).
        def put(brief: dict) -> bool:
            brief["calendar"] = _carry_raises(brief.get("calendar"), part)
            return True

        await sync_to_async(_change)(who, today.isoformat(), put)
    return part


async def clock_moved(who, *, google, zone, brief: dict) -> None:
    """A kept brief opened on another clock than it was made on: its calendar read on this one.

    The times on it have to be this device's (fr_294ce26939e7), and until
    8 October 2026 that made the whole brief again, on every switch between
    Petar's phone and his other tab. Now nothing is made again
    (fr_5fb00def9d2d: "let's make this stable"): only the calendar, which is
    read again on every open anyway, is read on this clock, with What to
    raise kept as it was, and the brief says which clock it is on.
    """
    from asgiref.sync import sync_to_async

    part = await calendar_again(who, google=google, zone=zone)
    if not part.get("ok"):
        return
    brief["calendar"] = part
    brief["zone"] = zone.key
    await sync_to_async(_put_part)(who, brief["day"], "zone", zone.key)


def weather_moved(brief: dict, settings: dict) -> bool:
    """Whether a kept brief's weather is for somewhere the person no longer is.

    Its point against the location's, so a brief made before the location
    changed (or before the brief read it at all) is not drawn for the old
    place for the rest of the day.
    """
    weather = brief.get("weather") or {}
    now = [settings.get("lat"), settings.get("lon")]
    if weather.get("ok"):
        return weather.get("at") != now
    # One that said there was no place, now that there is one, and the other way.
    return bool(weather.get("no_place")) != (now[0] is None)


async def weather_again(who, *, zone, brief: dict) -> dict:
    """Today's weather read again for where the person is, and put into today's kept brief."""
    from asgiref.sync import sync_to_async

    settings = await sync_to_async(settings_of)(who)
    zone = zone or clock.zone_of(who)
    with clock.person(who, zone):
        today = datetime.now(zone).date()
        async with _http() as http:
            try:
                part = await _weather(http, settings, zone)
            except Exception:
                log.exception("the morning brief's weather failed")
                part = {"ok": False, "note": "The weather part of the brief could not be made."}
    part["source"] = SOURCES["weather"]
    await sync_to_async(_put_part)(who, today.isoformat(), "weather", part)
    brief["weather"] = part
    brief["settings"] = {**(brief.get("settings") or {}), "place": settings["place"]}
    await sync_to_async(_put_part)(who, today.isoformat(), "settings", brief["settings"])
    return part


def _put_part(who, day: str, key: str, part: dict) -> None:
    def put(brief: dict) -> bool:
        brief[key] = part
        return True

    _change(who, day, put)


def _change(who, day: str, change) -> None:
    """Change the day's kept brief in place: `change(brief)` says whether it did.

    The row is held while it is changed, so the calendar read again as the
    page opens and What to raise kept for a meeting opened at the same moment
    (`keep_raise`) cannot write over each other.
    """
    from django.db import transaction

    from .models import MorningBrief

    with transaction.atomic():
        rows = (MorningBrief.objects.select_for_update()
                .filter(user_id=str(who.user_id), org_id=who.org_id or "", day=day))
        for row in rows:
            try:
                brief = json.loads(row.data)
            except (TypeError, ValueError):
                continue
            if change(brief):
                MorningBrief.objects.filter(pk=row.pk).update(
                    data=json.dumps(brief, ensure_ascii=False))


#: How many past briefs the list of them goes back, at most.
MOST_PAST = 400
DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def past(who, today: str) -> list[dict]:
    """Every brief this person has, newest first: its day, how it is said, when it was made.

    Fr_5fb00def9d2d, 8 October 2026: "There should be a link at the bottom
    that takes me to all previously generated briefs". One a day, as kept.
    """
    from .models import MorningBrief

    rows = (MorningBrief.objects
            .filter(user_id=str(who.user_id), org_id=who.org_id or "")
            .order_by("-day").values_list("day", "made_at")[:MOST_PAST])
    this_year = today[:4]
    out = []
    for day, made_at in rows:
        try:
            on = date.fromisoformat(day)
        except ValueError:
            continue
        words = f"{on.strftime('%A')} {on.day} {on.strftime('%B')}"
        if day[:4] != this_year:
            words += f" {on.year}"
        out.append({"day": day, "words": words, "made_at": made_at, "today": day == today})
    return out


def kept_day(who, day: str) -> dict | None:
    """One day's brief exactly as it was kept, or None. Nothing in it is read again."""
    if not DAY.match(str(day or "")):
        raise Refused("That is not a day a brief can be kept for.")
    return kept(who, day)


def today_of(who, zone=None) -> str:
    return datetime.now(zone or clock.zone_of(who)).date().isoformat()


def zone_for_page(who, name):
    """The clock a brief page is on, from the `X-Time-Zone` it sent, or None.

    Every time in the brief is read on one clock, and it has to be the clock of
    the device it is read on, because that is the clock the person's calendar
    shows them there. The person's own last known clock (`clock.zone_of`) is
    whichever of their devices spoke last: on 29 September 2026, on a trip, the
    person's phone said one zone and another tab kept saying a zone hours
    away, and the brief made on the tab's clock put every event hours off on
    the phone (fr_294ce26939e7). So the page's own
    wins, and is kept as the person's (`clock.remember`) like every page's is.
    """
    zone = clock.zone_named(name)
    if zone is not None:
        clock.remember(who, zone.key)
    return zone


# --- what goes to the phone -------------------------------------------------


def phone_text(brief: dict, link: str) -> str:
    """A few lines for Telegram: the day, the weather, the first thing on it, the link."""
    lines = [f"☀️ Your morning brief, {brief['day_words']}"]
    weather = brief.get("weather") or {}
    if weather.get("ok"):
        place = weather["place"].split(",")[0]
        rain = f", rain likely from {weather['rain_from']}" if weather.get("rain_from") else ""
        lines.append(f"{weather['picture']} {place} {weather['low']}-{weather['high']}°, "
                     f"{weather['words'].lower()}{rain}")
    elif weather.get("no_place"):
        lines.append("🌡️ No weather: no location is set in Settings.")
    cal = brief.get("calendar") or {}
    if cal.get("ok"):
        timed = [one for one in cal.get("today") or [] if not one["all_day"]]
        count = len(cal.get("today") or [])
        if not count:
            lines.append("📅 Nothing on your calendar today.")
        elif timed:
            lines.append(f"📅 {count} today, first at {timed[0]['start']}: {timed[0]['title']}")
        else:
            lines.append(f"📅 Today: {cal['today'][0]['title']}")
    world = brief.get("world") or {}
    if world.get("ok") and world.get("stories"):
        lines.append(f"📰 {world['stories'][0]['title']}")
    synapse = (brief.get("report") or {}).get("synapse") or {}
    if synapse.get("outcome_words"):
        idea = synapse.get("idea") or ""
        lines.append(f"🧪 Synapse last night: {synapse['outcome_words']}"
                     + (f", {idea[:1].lower() + idea[1:80]}" if idea else ""))
    for one in (brief.get("report") or {}).get("ran") or []:
        d = one.get("decision") or {}
        if d.get("number"):
            lines.append(f"🌙 Decision {d['number']}: {d['title'][:90]}. "
                         + " or ".join(o["label"] for o in d.get("options") or []) + "?")
    if link:
        lines.append(link)
    return "\n".join(lines)


# --- every morning ----------------------------------------------------------


class Mornings:
    """The loop that makes each person's brief at their time, and sends the link.

    It wakes once a minute. A person whose brief is on, whose time has come on
    their own clock and whose brief today has not yet been made at its time
    (`sent_at`) gets one made afresh; the person whose phone the bot reaches
    also gets it on Telegram. `sent_at` is written either way, so a restart,
    or a deploy at five past seven, never makes it twice; a brief missed by
    more than `LATE` waits for Update instead of arriving at lunch. It is made
    like Update makes it (`make`): a meeting, a video or a world story already
    worked out for the brief before is kept as it was.
    """

    def __init__(self, *, tenancy, telegram, public_url: str, google=None,
                 mailboxes=None) -> None:
        self.tenancy = tenancy
        #: The read-only mailboxes' round trip (`rouh/mailboxes.py`): each
        #: person's are looked at as their brief is made, so Waiting on others
        #: is there the moment the page opens (`rouh/ghosts.py`).
        self.mailboxes = mailboxes
        self.telegram = telegram
        self.public_url = (public_url or "").rstrip("/")
        self.google = google
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.get_running_loop().create_task(self._run())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
            self._task = None

    async def _run(self) -> None:
        await asyncio.sleep(20)
        while True:
            try:
                await self.beat()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("the morning brief's beat failed")
            await asyncio.sleep(60)

    def link(self) -> str:
        from . import addressing

        return self.public_url + addressing.BRIEF if self.public_url else ""

    def _due(self) -> list:
        """Everybody whose brief is due now and has not gone yet today."""
        from .models import MorningBrief, User

        out = []
        for user in User.objects.filter(is_active=True, is_guest=False).exclude(org_id=""):
            who = self.tenancy.identity_of(str(user.pk))
            if who is None:
                continue
            settings = settings_of(who)
            if not settings["on"]:
                continue
            zone = clock.zone_of(who)
            now = datetime.now(zone)
            hour, minute = (int(part) for part in settings["time"].split(":"))
            at = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if not (at <= now < at + timedelta(seconds=LATE)):
                continue
            went = (MorningBrief.objects
                    .filter(user_id=who.user_id, org_id=who.org_id, day=now.date().isoformat(),
                            sent_at__isnull=False).exists())
            if not went:
                out.append(who)
        return out

    async def beat(self) -> list[str]:
        """One look at the clock. The ids of the people whose brief was made."""
        from asgiref.sync import sync_to_async

        made = []
        for who in await sync_to_async(self._due)():
            began = time.monotonic()
            brief = await make(who, google=self.google, scheduled=True)
            from . import events

            events.emit("schedule.ran", who=who, actor="rouh", source="scheduler",
                        object_type="work", object_id="morning brief",
                        duration_ms=(time.monotonic() - began) * 1000, props={"outcome": "done"})
            if self.mailboxes is not None:
                from . import ghosts
                from .config import config

                try:
                    await ghosts.refresh_all(who, self.mailboxes, config)
                except Exception:
                    log.exception("the ghost list could not be looked at for %s", who.user_id)
            sent = await self._phone(who, brief)
            await sync_to_async(self._mark)(who, brief["day"])
            log.info("made the morning brief for %s%s", who.user_id,
                     " and sent the link to the phone" if sent else "")
            made.append(who.user_id)
        return made

    async def _phone(self, who, brief: dict) -> bool:
        """The brief's few lines and its link: a notice on the person's screen, which goes to
        their phone if it is left there (`rouh/notices.py`)."""
        from . import notices

        said = await notices.phone(phone_text(brief, self.link()), kind="brief", who=who,
                                   key=f"brief:{brief.get('day') or ''}")
        return said is not None

    @staticmethod
    def _mark(who, day: str) -> None:
        from .models import MorningBrief

        MorningBrief.objects.filter(user_id=who.user_id, org_id=who.org_id,
                                    day=day).update(sent_at=time.time())
