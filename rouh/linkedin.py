"""LinkedIn research: find the person, let the person pick, then harvest the profile.

Petar, 26 September 2026 (fr_c833dc724c62): "I would like to add a new tool -
LinkedIn research. This tool has already been written and is available on our
hr service ... So what we need is another extra piece of functionality that
looks up various people and shows me on screen available data to pick which
person is the correct one that we should research and harvest. Basically image
of the face, name, and whatever quick information for job is accessible in
case multiple people with the same name or we don't have exact name match."

So there are two steps, and the second never happens without the first
having been answered by him:

1. **Search** (:func:`search`). A name, and whatever he knows besides - a
   place, a company, a job title, a school - goes to HarvestAPI's LinkedIn
   Profile Search by Name, in its Short mode: a page of up to ten people, each
   with a face (when LinkedIn shows one), a name, the headline under the name,
   which is nearly always "role at company", where they are and the address of
   their profile. That is drawn as a card of candidates (:func:`picker_card`,
   the ``people`` block), numbered, each with a Research button.
2. **Harvest** (:func:`harvest`), once he has picked, by pressing Research or
   by saying which one. The same two HarvestAPI actors the HR project runs
   (``dashboard/services/enrichment_service.py`` on another server, where this was
   first written): the full profile, and the latest posts. That is drawn as a
   card of its own (:func:`profile_card`, the ``profile`` block), laid out as
   the HR project's Lookup page lays out a person: who they are, About,
   Experience, Education, Skills, and their posts, with the little that page
   leaves out and a researcher wants (certifications, languages,
   recommendations).

A LinkedIn address he already has skips the first step.

**Whose words a post is.** The posts actor lists what the person posted and
what they reposted, mixed, and a plain repost carries the original's words as
its own ``content``: on 5 October 2026 one person's repost of somebody else's
"#OpenToWork" post came back with ``author`` the other person and
``repostedBy`` her, and Rouh said she was looking for work. So every item is given its relation to the person
(:func:`relation`): their own post, a repost with no comment of their own, a
repost with their own comment, a comment, a like or another reaction on
somebody else's post, or "authorship unknown" when LinkedIn did not say. Never
"own post" by default. The original author's name and words are kept apart
from theirs, on the card and in what the model reads.

**Their comments and reactions** are not in that listing at all. HarvestAPI
sells them as two more actors, Profile Comments and Profile Reactions, at
$0.002 an item (5 October 2026), so a harvest reads the latest `ACTIVITY` of
each, about a cent between them, beside the profile ($0.004) and the posts
($0.002 each).

**One search is three.** Measured on 26 September 2026: the same search for
"Alex Ivanov", asked three times, came back with ten people twice and three
people once, and "John Smith" came back with three different people every one
of five times. LinkedIn answers a logged-out search with a short page about
half the time. So :func:`search` asks three times side by side, at $0.004 a
page, and keeps everybody who came back once, the fullest answer first.

**The press is the server's.** A press on Research names the card and a
number and nothing else (``card_pick`` over the socket, :func:`pick`). Which
profile that is, is read out of the card as the server stored it, from a
token only the server can sign, and only for the person it was drawn for -
the rule `rouh/asking.py` set for every card that does something. The press
harvests at once rather than asking the model to, so what a button does never
depends on what a model decides, and the conversation is told afterwards in a
note from Rouh's own software, with the profile in it, so the assistant can
talk about the person and knows not to harvest them a second time.

**The key** is the HR project's own Apify token, ``APIFY_API_TOKEN``, copied
into ``/var/www/rouh/.env`` on 26 September 2026 without being read. It is
Apify's own name for it, as ``YOUTUBE_API_KEY`` is Google's. HarvestAPI sells
these scrapers through Apify, so an Apify token is a HarvestAPI key. It goes
in a header and never in an address, so no log line that prints an address
can carry it (`rouh/redaction.py` masks its shape as a net under that).

Everything here reads public profiles. Nothing signs in as anybody and
nothing is written anywhere but the cards, except where a list was drawn as the
candidates for one of the person's contacts (`meeting_people.candidates_block`):
the one he picks is then kept on that contact too, as their online research.
"""
from __future__ import annotations

import asyncio
import logging
import re
import secrets
import time
import unicodedata
from dataclasses import dataclass, field
from typing import Awaitable, Callable
from urllib.parse import quote, unquote, urlsplit

import httpx

from . import artifacts

log = logging.getLogger("rouh.linkedin")

#: The HarvestAPI actors, as Apify names them.
SEARCH_ACTOR = "harvestapi/linkedin-profile-search-by-name"
PROFILE_ACTOR = "harvestapi/linkedin-profile-scraper"
POSTS_ACTOR = "harvestapi/linkedin-profile-posts"
COMMENTS_ACTOR = "harvestapi/linkedin-profile-comments"
REACTIONS_ACTOR = "harvestapi/linkedin-profile-reactions"

#: The profile scraper's mode, which is its price written into its name. Email
#: search is the other one, at two and a half times the price, and nobody asked
#: for it.
PROFILE_MODE = "Profile details no email ($4 per 1k)"

#: Where Apify is. A test world points `ROUH_APIFY_URL` at its stand-in
#: (`rouh/testing/fake_apify.py`).
APIFY_URL = "https://api.apify.com"

#: The two blocks this module draws, as `renderBlock` in static/app.js knows
#: them. Only this module makes either: the model's own cards have them taken
#: off (`strip`), because a people block is a row of buttons that spend money.
PEOPLE, PROFILE = "people", "profile"

#: What the picker's token is signed for, so a token signed for anything else
#: in Rouh can never be read as one of these.
SALT = "rouh.linkedin"

#: How long a list of candidates may be pressed. A press only ever reads a
#: public profile, so a list from a fortnight ago doing it is no harm, and a
#: person does come back to research somebody later.
MAX_AGE = 30 * 24 * 3600

#: How many times one search is asked, side by side (see the module's text).
TRIES = 3

#: How many candidates a card shows unless asked for more, and the most.
LIMIT, MOST = 8, 10

#: How many of their posts a harvest reads. The HR project reads the actor's
#: own default, which is ten.
POSTS = 10

#: How many of their latest comments, and of their latest reactions, a harvest
#: reads: $0.002 each, so the two together are about a cent.
ACTIVITY = 3

#: How the person whose profile it is stands to one post (:func:`relation`),
#: and how that is said, on the card and to the model, word for word.
OWN, REPOST, QUOTE, COMMENTED, LIKED, REACTED, OTHER, UNKNOWN = (
    "own", "repost", "quote", "commented", "liked", "reacted", "other", "unknown")
LABELS = {
    OWN: "own post",
    REPOST: "reposted, no comment of their own",
    QUOTE: "reposted with own comment",
    COMMENTED: "commented on",
    LIKED: "liked",
    REACTED: "reacted to",
    OTHER: "somebody else's post, listed without saying why",
    UNKNOWN: "authorship unknown",
}

#: LinkedIn's names for a reaction other than a like, as its activity lines
#: say them ("Sam Rivera celebrates this") and as its buttons do.
_REACTIONS = (("celebrates", "Celebrate"), ("supports", "Support"), ("loves", "Love"),
              ("finds this insightful", "Insightful"), ("finds this funny", "Funny"),
              ("is curious about", "Curious"))

#: How long Apify may take, in seconds. A search page comes back in three to
#: ten; a profile in three or four and its posts in six (measured on 26
#: September 2026), so these are for a bad day, not a normal one.
SEARCH_TIMEOUT, HARVEST_TIMEOUT = 90, 150

#: What is kept of the long parts of a profile, so a card stays a card.
ABOUT_MAX, DESCRIPTION_MAX, POST_MAX, RECOMMENDATION_MAX = 4000, 1500, 1500, 800

#: What the model is handed of a whole profile at most.
TEXT_MAX = 14000


class Trouble(Exception):
    """Something between here and LinkedIn that can be said in one sentence."""


class NotFound(Trouble):
    """LinkedIn has no profile at that address."""


# --- Apify ---------------------------------------------------------------


class Apify:
    """Run one of Apify's actors and hand back what it found.

    ``run-sync-get-dataset-items`` does the whole of it in one request: start
    the run, wait for it, and answer with the items it put in its dataset.
    """

    def __init__(self, token: str, base: str = APIFY_URL, transport=None) -> None:
        self.token = token or ""
        self.base = (base or APIFY_URL).rstrip("/")
        self._transport = transport

    def ready(self) -> bool:
        return bool(self.token)

    async def run(self, actor: str, body: dict, timeout: float) -> list[dict]:
        url = f"{self.base}/v2/acts/{actor.replace('/', '~')}/run-sync-get-dataset-items"
        try:
            async with httpx.AsyncClient(timeout=timeout + 30,
                                         transport=self._transport) as client:
                answer = await client.post(
                    url, params={"timeout": int(timeout)}, json=body,
                    headers={"Authorization": f"Bearer {self.token}"})
        except httpx.TimeoutException as exc:
            raise Trouble("LinkedIn took too long to answer through Apify.") from exc
        except httpx.HTTPError as exc:
            log.warning("apify: %s did not answer: %s", actor, type(exc).__name__)
            raise Trouble("Apify, which reads LinkedIn for Rouh, could not be "
                          "reached.") from exc
        if answer.status_code in (401, 403):
            raise Trouble("Apify refused this Rouh's token. The owner replaces it in Anatomy, "
                          "Connections, Keys, never in a chat.")
        if answer.status_code == 402:
            raise Trouble("The Apify account has run out of credit, so HarvestAPI "
                          "would not run.")
        if answer.status_code == 408:
            raise Trouble("LinkedIn took too long to answer through Apify.")
        if answer.status_code >= 400:
            raise Trouble(f"Apify answered {answer.status_code}: {_apify_said(answer)}")
        try:
            items = answer.json()
        except ValueError as exc:
            raise Trouble("Apify answered with something that was not a list of "
                          "results.") from exc
        if not isinstance(items, list):
            raise Trouble(f"Apify answered without a list of results: {_apify_said(answer)}")
        return [item for item in items if isinstance(item, dict)]


def _apify_said(answer: httpx.Response) -> str:
    """Apify's own words about an error, short."""
    try:
        said = (answer.json().get("error") or {}).get("message") or ""
    except (ValueError, AttributeError):
        said = answer.text
    return " ".join(str(said).split())[:200] or "no reason given"


# --- addresses -------------------------------------------------------------

#: A LinkedIn profile's own part of an address: /in/<this>.
_IN = re.compile(r"/in/([^/?#\s]+)", re.IGNORECASE)

#: A bare public identifier, as the profile scraper also takes one.
_BARE = re.compile(r"^[A-Za-z0-9%_.\-]{3,100}$")


def slug_of(said: str) -> str:
    """The profile's identifier out of anything that names one, or "".

    The HR project's `normalize_linkedin_slug`, with a bare identifier allowed
    too: "linkedin.com/in/jane-doe/", "https://www.linkedin.com/in/Jane-Doe?x=1",
    "http://uk.linkedin.com/in/jane-doe/details/experience" and "jane-doe" are
    all "jane-doe".
    """
    text = str(said or "").strip()
    if not text:
        return ""
    found = _IN.search(urlsplit(text if "://" in text else "https://" + text).path)
    if found:
        return _clean_slug(found.group(1))
    if "/" not in text and "." not in text.strip(".") and _BARE.match(text):
        return _clean_slug(text)
    return ""


def _clean_slug(slug: str) -> str:
    # Lower-cased, as the HR project does, with any non-ASCII identifier
    # (LinkedIn has Cyrillic ones) kept as LinkedIn writes it in an address.
    return quote(unquote(slug).strip().lower(), safe="-_.~")


def profile_url(said: str) -> str:
    """The canonical address of the profile anything names, or ""."""
    slug = slug_of(said)
    return f"https://www.linkedin.com/in/{slug}/" if slug else ""


# --- the search ------------------------------------------------------------


@dataclass
class Found:
    """What one search found, and what it was asked."""

    people: list[dict]
    asked: str
    #: How many of the tries answered at all, of `TRIES`.
    answered: int = 0
    #: Why the others did not.
    troubles: list[str] = field(default_factory=list)


async def search(apify: Apify, first: str, last: str, *, location: str = "",
                 company: str = "", title: str = "", school: str = "", exact: bool = True,
                 limit: int = LIMIT) -> Found:
    """Everybody on LinkedIn by this name who fits what else was said.

    Raises `Trouble` only when every try failed; a search that found nobody
    comes back with nobody in it, which is its own answer.
    """
    first, last = _one_line(first), _one_line(last)
    body: dict = {"profileScraperMode": "Short", "firstName": first, "lastName": last,
                  "strictSearch": bool(exact), "maxPages": 1}
    for key, value in (("locations", location), ("currentCompanies", company),
                       ("currentJobTitles", title), ("schools", school)):
        if _one_line(value):
            body[key] = [_one_line(value)]
    asked = " · ".join(v for v in (f"{first} {last}".strip(), _one_line(title),
                                   _one_line(company), _one_line(location),
                                   _one_line(school)) if v)
    started = time.monotonic()
    answers = await asyncio.gather(
        *(apify.run(SEARCH_ACTOR, body, SEARCH_TIMEOUT) for _ in range(TRIES)),
        return_exceptions=True)
    pages = [a for a in answers if isinstance(a, list)]
    troubles = [a for a in answers if isinstance(a, BaseException)]
    if not pages:
        first_trouble = troubles[0] if troubles else Trouble("Nothing came back.")
        if isinstance(first_trouble, Trouble):
            raise first_trouble
        raise Trouble(f"The search failed ({type(first_trouble).__name__}).")
    # The fullest answer first: it is LinkedIn's own order for the most people,
    # and the short answers only add whoever it left out.
    pages.sort(key=len, reverse=True)
    people = merged(pages)
    # Whoever has exactly the name asked for goes ahead of whoever only looks
    # like it, keeping LinkedIn's order within each.
    wanted = _folded(f"{first} {last}")
    people.sort(key=lambda p: 0 if wanted and wanted in _folded(p["name"]) else 1)
    limit = max(1, min(int(limit or LIMIT), MOST))
    log.info("linkedin search: %d people from %d of %d tries in %.1fs",
             len(people), len(pages), TRIES, time.monotonic() - started)
    return Found(people[:limit], asked, len(pages),
                 [str(t) or type(t).__name__ for t in troubles])


def merged(pages: list[list[dict]]) -> list[dict]:
    """Everybody on these pages once, in the order they first came.

    The same person on two pages is not always the same row: LinkedIn showed
    three faces of ten to one ask and seven of the same ten to the next (26
    September 2026). So whatever one answer left blank - the picture, above
    all - is taken from another that had it.
    """
    by_slug: dict[str, dict] = {}
    for page in pages:
        for item in page:
            person = candidate(item)
            if person is None:
                continue
            had = by_slug.get(person["slug"])
            if had is None:
                by_slug[person["slug"]] = person
                continue
            for key, value in person.items():
                if value and not had.get(key):
                    had[key] = value
    return list(by_slug.values())


def candidate(item: dict) -> dict | None:
    """One short profile from a search, as the card and the model want it."""
    url = profile_url(str(item.get("linkedinUrl") or item.get("publicIdentifier") or ""))
    if not url:
        return None
    slug = slug_of(url)
    name = _one_line(item.get("name")) or _one_line(
        f"{item.get('firstName') or ''} {item.get('lastName') or ''}")
    return {
        "name": name or unquote(slug),
        "headline": _one_line(item.get("position") or item.get("headline")),
        "location": _location(item.get("location")),
        "photo": _picture(item.get("photo") or item.get("pictureUrl")
                          or item.get("profilePicture"), 200),
        "url": url,
        "slug": slug,
    }


# --- the harvest -----------------------------------------------------------


async def harvest(apify: Apify, said: str, *, posts: bool = True) -> dict:
    """The whole profile at an address, and their latest posts, side by side.

    Raises `NotFound` when LinkedIn has nobody there and `Trouble` when the
    profile could not be read. Posts that could not be read are said on the
    profile rather than failing it: the profile is what was asked for.
    """
    url = profile_url(said)
    if not url:
        raise Trouble("That is not a LinkedIn profile address.")
    started = time.monotonic()
    work = [apify.run(PROFILE_ACTOR, {"profileScraperMode": PROFILE_MODE, "urls": [url]},
                      HARVEST_TIMEOUT)]
    if posts:
        work += [apify.run(POSTS_ACTOR, {"targetUrls": [url], "maxPosts": POSTS},
                           HARVEST_TIMEOUT),
                 apify.run(COMMENTS_ACTOR, {"profiles": [url], "maxItems": ACTIVITY},
                           HARVEST_TIMEOUT),
                 apify.run(REACTIONS_ACTOR, {"profiles": [url], "maxItems": ACTIVITY},
                           HARVEST_TIMEOUT)]
    got = await asyncio.gather(*work, return_exceptions=True)
    found = got[0]
    if isinstance(found, BaseException):
        if isinstance(found, Trouble):
            raise found
        raise Trouble(f"The profile could not be read ({type(found).__name__}).")
    item = next((i for i in found if _is_profile(i)), None)
    if item is None:
        raise NotFound(f"LinkedIn has no profile at {url}.")
    posts_said = activity_said = ""
    post_items: list[dict] = []
    activity_items: list[dict] = []
    if posts:
        if isinstance(got[1], BaseException):
            posts_said = f"Their posts could not be read: {got[1]}"
        else:
            post_items = got[1]
        unread = [g for g in got[2:] if isinstance(g, BaseException)]
        activity_items = [i for g in got[2:] if isinstance(g, list) for i in g]
        if unread:
            activity_said = f"Some of their comments and reactions could not be read: {unread[0]}"
    log.info("linkedin harvest: one profile, %d posts and %d comments and reactions in "
             "%.1fs", len(post_items), len(activity_items), time.monotonic() - started)
    return profile(item, post_items, url=url, posts_said=posts_said, posts_read=posts,
                   activity=activity_items, activity_said=activity_said)


def _is_profile(item: dict) -> bool:
    return bool(item.get("firstName") or item.get("lastName") or item.get("headline")
                or item.get("publicIdentifier")) and not item.get("error")


def profile(item: dict, posts: list[dict], *, url: str = "", posts_said: str = "",
            posts_read: bool = True, activity: list[dict] | None = None,
            activity_said: str = "") -> dict:
    """A harvested profile, as the card draws it and the model reads it."""
    url = profile_url(str(item.get("linkedinUrl") or item.get("publicIdentifier") or "")) \
        or url
    name = _one_line(f"{item.get('firstName') or ''} {item.get('lastName') or ''}") \
        or _one_line(item.get("name")) or unquote(slug_of(url))
    owner = Owner(slug_of(url), {str(v) for v in (item.get("id"), item.get("profileId"),
                                                  item.get("urn")) if v}, name)
    return {
        "block": PROFILE,
        "source": "linkedin",
        "url": url,
        "slug": slug_of(url),
        "name": name,
        "headline": _one_line(item.get("headline")),
        "location": _location(item.get("location")),
        "photo": _picture(item.get("profilePicture") or item.get("photo"), 400),
        "facts": _facts(item),
        "about": _text(item.get("about"), ABOUT_MAX),
        "experience": [e for e in (_job(j) for j in _items(item.get("experience"))[:25]) if e],
        "education": [e for e in (_school(s) for s in _items(item.get("education"))[:15]) if e],
        "skills": _skills(item),
        "certifications": [c for c in (_certificate(c) for c in
                                       _items(item.get("certifications"))[:20]) if c],
        "languages": [x for x in (_language(x) for x in _items(item.get("languages"))) if x],
        "recommendations": [r for r in (_recommendation(r) for r in
                                        _items(item.get("receivedRecommendations"))[:10]) if r],
        "posts": _posts(posts, owner),
        "posts_read": bool(posts_read),
        "posts_said": posts_said,
        "activity": _activity(activity or [], owner),
        "activity_said": activity_said,
        "harvested": time.time(),
    }


def _facts(item: dict) -> list[str]:
    """The short things that tell one person from another at a glance."""
    out = []
    connections = _number(item.get("connectionsCount"))
    if connections is not None:
        # LinkedIn stops counting out loud at 500, and says "500+".
        out.append(f"{connections:,}{'+' if connections == 500 else ''} connections")
    followers = _number(item.get("followerCount"))
    if followers is not None:
        out.append(f"{followers:,} followers")
    for key, said in (("openToWork", "Open to work"), ("hiring", "Hiring"),
                      ("verified", "Verified"), ("premium", "Premium"),
                      ("influencer", "Top Voice"), ("creator", "Creator")):
        if _true(item.get(key)):
            out.append(said)
    since = str(item.get("registeredAt") or "")[:4]
    if since.isdigit():
        out.append(f"On LinkedIn since {since}")
    return out


def _job(job: dict) -> dict | None:
    title = _one_line(job.get("position") or job.get("title"))
    company = _one_line(job.get("companyName"))
    if not title and not company:
        return None
    return {
        "title": title,
        "company": company,
        "company_url": _address(job.get("companyLinkedinUrl")),
        "logo": _picture(job.get("companyLogo"), 100),
        "location": _one_line(job.get("location")),
        "kind": " · ".join(v for v in (_one_line(job.get("employmentType")),
                                       _one_line(job.get("workplaceType"))) if v),
        "dates": _span(job.get("startDate"), job.get("endDate")),
        "duration": _one_line(job.get("duration")),
        "description": _text(job.get("description"), DESCRIPTION_MAX),
    }


def _school(school: dict) -> dict | None:
    name = _one_line(school.get("schoolName") or school.get("school"))
    if not name:
        return None
    return {
        "school": name,
        "degree": " · ".join(v for v in (_one_line(school.get("degree")),
                                         _one_line(school.get("fieldOfStudy"))) if v),
        "dates": _one_line(school.get("period")) or _span(school.get("startDate"),
                                                          school.get("endDate")),
        "logo": _picture(school.get("schoolLogo"), 100),
    }


def _skills(item: dict) -> list[str]:
    names = [_one_line(s.get("name") if isinstance(s, dict) else s)
             for s in _items(item.get("skills"))]
    top = item.get("topSkills")
    if not any(names) and top:
        names = [_one_line(s) for s in (top if isinstance(top, list)
                                        else re.split(r"\s*[•,]\s*", str(top)))]
    return list(dict.fromkeys(n for n in names if n))[:50]


def _certificate(cert: dict) -> dict | None:
    title = _one_line(cert.get("title") or cert.get("name"))
    if not title:
        return None
    return {"title": title, "by": _one_line(cert.get("issuedBy")),
            "when": _one_line(cert.get("issuedAt"))}


def _language(lang) -> str:
    if isinstance(lang, dict):
        name = _one_line(lang.get("name") or lang.get("title"))
        level = _one_line(lang.get("proficiency") or lang.get("subtitle"))
        return f"{name} ({level})" if name and level else name
    return _one_line(lang)


def _recommendation(rec: dict) -> dict | None:
    text = _text(rec.get("description") or rec.get("text"), RECOMMENDATION_MAX)
    if not text:
        return None
    return {"by": _one_line(rec.get("givenBy")), "by_url": _address(rec.get("givenByLink")),
            "headline": _one_line(rec.get("givenByHeadline")),
            "when": _one_line(rec.get("givenAt")), "text": text}


@dataclass
class Owner:
    """Whose profile it is, as a post's author is compared with them."""

    slug: str
    ids: set = field(default_factory=set)
    name: str = ""


def _is_owner(person, owner: Owner) -> bool | None:
    """Whether `person` (an author, an actor, a reposter) is the profile's owner.

    None when it says nothing to tell by. The identifier or the address first,
    then LinkedIn's own id, and the name only when there is nothing else.
    """
    if not isinstance(person, dict) or not person:
        return None
    if str(person.get("type") or "") == "company" or person.get("universalName"):
        return False
    slug = slug_of(str(person.get("publicIdentifier") or "")) \
        or slug_of(str(person.get("linkedinUrl") or ""))
    if slug and owner.slug and not slug.lower().startswith("acoa"):
        return slug == owner.slug
    ids = {str(v) for v in (person.get("id"), person.get("profileId"), person.get("urn")) if v}
    if ids and owner.ids:
        return bool(ids & owner.ids)
    name = _folded(person.get("name") or "")
    if name and owner.name:
        return name == _folded(owner.name)
    return None


def _activity_of(said: str) -> tuple[str, str]:
    """What an activity line ("X reposted this", "X likes this") says they did."""
    line = _one_line(said).lower()
    if not line.endswith(" this"):
        return "", ""
    if line.endswith("reposted this"):
        return REPOST, ""
    if line.endswith("commented on this"):
        return COMMENTED, ""
    if line.endswith("likes this"):
        return LIKED, ""
    for verb, button in _REACTIONS:
        if line.endswith(f"{verb} this"):
            return REACTED, button
    return "", ""


def relation(post: dict, owner: Owner) -> dict:
    """How the profile's owner stands to one item of the posts actor.

    What HarvestAPI says, measured on 5 October 2026: their own post has them
    as ``author``; a plain repost has the original's ``author`` and words, with
    ``repostedBy`` them and a ``header`` of "<them> reposted this"; a repost
    with their own comment has them as ``author``, their comment as
    ``content`` and the original under ``repost``; a ``repost`` with no
    ``content`` of theirs is a plain repost too (LinkedIn's older shares).
    Anything that says none of this is "authorship unknown", never their own.
    """
    author = post.get("author") if isinstance(post.get("author"), dict) else {}
    repost = post.get("repost") if isinstance(post.get("repost"), dict) else {}
    header = post.get("header") if isinstance(post.get("header"), dict) else {}
    did, reaction = _activity_of(header.get("text") or "")
    by_owner = _is_owner(author, owner)
    content = _text(post.get("content"), POST_MAX)
    out = {"relation": UNKNOWN, "text": "", "original_author": "",
           "original_author_url": "", "original_is_owner": False, "original_text": "",
           "reaction": ""}

    def original(person: dict, words) -> None:
        out["original_is_owner"] = _is_owner(person, owner) is True
        out["original_author"] = _one_line(person.get("name")) if person else ""
        out["original_author_url"] = _address(
            (person or {}).get("linkedinUrl")).split("?")[0] if person else ""
        out["original_text"] = _text(words, POST_MAX)

    reposted_by = post.get("repostedBy") if isinstance(post.get("repostedBy"), dict) else {}
    if reposted_by or did == REPOST:
        if reposted_by and _is_owner(reposted_by, owner) is False:
            original(author, post.get("content"))
            out["relation"] = OTHER if author else UNKNOWN
        elif by_owner is True and not repost:
            out.update(relation=OWN, text=content)
        else:
            out["relation"] = REPOST
            if repost:
                original(repost.get("author") or {}, repost.get("content"))
            else:
                original(author, post.get("content"))
        return out
    if repost:
        if by_owner is True:
            out.update(relation=QUOTE if content else REPOST, text=content)
            original(repost.get("author") or {}, repost.get("content"))
        else:
            # Somebody's repost, and nothing says it is theirs.
            original(author, post.get("content"))
            out["relation"] = OTHER if by_owner is False else UNKNOWN
        return out
    if did in (COMMENTED, LIKED, REACTED) and by_owner is not True:
        original(author, post.get("content"))
        out.update(relation=did, reaction=reaction)
        return out
    if by_owner is True:
        out.update(relation=OWN, text=content)
        return out
    original(author, post.get("content"))
    out["relation"] = OTHER if by_owner is False else UNKNOWN
    return out


def label(post: dict) -> str:
    """How one post stands to the profile's owner, in the words both cards and
    the model are given: "own post", "reposted with own comment", ..."""
    kind = post.get("relation")
    if kind not in LABELS:
        return ""
    said = LABELS[kind]
    if kind in (OWN, UNKNOWN):
        return said
    author = "themselves" if post.get("original_is_owner") else (
        post.get("original_author") or "an author LinkedIn did not name")
    if kind in (COMMENTED, LIKED, REACTED):
        said += f" a post by {author}"
        return said + (f" ({post['reaction']})" if kind == REACTED and post.get("reaction")
                       else "")
    return said + f"; original post by {author}"


def _stamp(value) -> float:
    if not isinstance(value, dict):
        return 0.0
    return float(_number(value.get("timestamp")) or 0)


def _posts(items: list[dict], owner: Owner | None = None) -> list[dict]:
    """Their posts and reposts, newest first, each saying whose words it is."""
    owner = owner or Owner("")

    def when(post: dict) -> float:
        return _stamp(post.get("repostedAt")) or _stamp(post.get("postedAt"))

    out = []
    for post in sorted((p for p in items if isinstance(p, dict)), key=when, reverse=True):
        rel = relation(post, owner)
        if not rel["text"] and not rel["original_text"]:
            continue
        repost = post.get("repost") if isinstance(post.get("repost"), dict) else {}
        posted = post.get("repostedAt") if isinstance(post.get("repostedAt"), dict) \
            else post.get("postedAt") if isinstance(post.get("postedAt"), dict) else {}
        ago = (post.get("postedAt") or {}).get("postedAgoShort") \
            if isinstance(post.get("postedAt"), dict) else ""
        engagement = post.get("engagement") if isinstance(post.get("engagement"), dict) else {}
        pictures = [_picture(p, 400) for p in _items(post.get("postImages")
                                                     or repost.get("postImages"))]
        out.append(dict(rel, **{
            "label": "",
            "date": str(posted.get("date") or "")[:10],
            "ago": _one_line(ago),
            "likes": _number(engagement.get("likes")) or 0,
            "comments": _number(engagement.get("comments")) or 0,
            "url": _address(post.get("linkedinUrl")),
            "images": [p for p in pictures if p][:3],
        }))
        out[-1]["label"] = label(out[-1])
    return out[:POSTS]


def _activity(items: list[dict], owner: Owner) -> list[dict]:
    """Their latest comments and reactions on posts, from the two activity actors.

    A comment item has ``commentary`` (their words) and the ``post`` it is on;
    a reaction item has ``action`` ("Sam Rivera likes this") and
    the ``post``. Anything by somebody other than them is left out.
    """
    out = []
    for item in (i for i in items if isinstance(i, dict)):
        if _is_owner(item.get("actor"), owner) is False:
            continue
        post = item.get("post") if isinstance(item.get("post"), dict) else {}
        author = post.get("author") if isinstance(post.get("author"), dict) else {}
        if "commentary" in item:
            kind, reaction, mine = COMMENTED, "", _text(item.get("commentary"), POST_MAX)
            engagement = item.get("engagement") if isinstance(item.get("engagement"),
                                                              dict) else {}
            url = _address(item.get("linkedinUrl"))
        else:
            kind, reaction = _activity_of(item.get("action") or "")
            if kind not in (LIKED, REACTED):
                continue
            mine = ""
            engagement = post.get("engagement") if isinstance(post.get("engagement"),
                                                              dict) else {}
            url = _address(post.get("linkedinUrl"))
        theirs = _text(post.get("content"), POST_MAX)
        if not mine and not theirs:
            continue
        row = {
            "relation": kind, "reaction": reaction, "text": mine,
            "original_author": _one_line(author.get("name")),
            "original_author_url": _address(author.get("linkedinUrl")).split("?")[0],
            "original_is_owner": _is_owner(author, owner) is True,
            "original_text": theirs,
            "date": str(item.get("createdAt") or "")[:10],
            "stamp": float(_number(item.get("createdAtTimestamp")) or 0),
            "ago": "",
            "likes": _number(engagement.get("likes")) or 0,
            "comments": _number(engagement.get("comments")) or 0,
            "url": url, "images": [],
        }
        row["label"] = label(row)
        out.append(row)
    out.sort(key=lambda r: r.pop("stamp"), reverse=True)
    return out[:2 * ACTIVITY]


# --- the two cards ---------------------------------------------------------


def picker_card(found: Found, who, chat: str, *, person: str = "") -> dict:
    """The card of candidates, with a Research button on each, signed for `who`.

    `person` is the contact these are candidates for, in `who`'s Synapse Master: a press then
    also keeps the profile on that contact (`meeting_people.keep_picked`), which is how a
    meeting guest Rouh could not be sure of is picked from their contact card.
    """
    sealed = {"u": getattr(who, "user_id", ""), "o": getattr(who, "org_id", ""), "c": chat or "",
              "urls": [p["url"] for p in found.people], "n": secrets.token_hex(4)}
    if person:
        sealed["p"] = str(person)
    token = _signer().dumps(sealed, salt=SALT, compress=True)
    name = found.asked.split(" · ")[0]
    count = len(found.people)
    return {
        "title": f"Which {name}?",
        "description": (f"{count} {'person' if count == 1 else 'people'} on LinkedIn for "
                        f"{found.asked}, to pick the one to research"),
        "blocks": [{"block": PEOPLE, "source": "linkedin", "query": found.asked,
                    "token": token, "people": found.people, "picked": {}}],
    }


def profile_card(data: dict) -> dict:
    """The card a harvested profile is drawn on."""
    about = " - ".join(v for v in (data.get("headline"), data.get("location")) if v)
    return {
        "title": data.get("name") or "A LinkedIn profile",
        "description": ("the LinkedIn profile of " + (data.get("name") or "somebody")
                        + (f", {about}" if about else "") + ", harvested in full"),
        "blocks": [dict(data)],
    }


def strip(blocks) -> list:
    """Blocks the model wrote, with anything only this module may draw taken off."""
    return [b for b in (blocks or [])
            if not (isinstance(b, dict)
                    and str(b.get("block") or "").lower() in (PEOPLE, PROFILE))]


def people_of(spec: dict | None) -> tuple[int, dict | None]:
    """Where the people block is on a card, and the block."""
    for at, b in enumerate((spec or {}).get("blocks") or []):
        if isinstance(b, dict) and b.get("block") == PEOPLE:
            return at, b
    return -1, None


# --- what the model reads ----------------------------------------------------


def picker_text(found: Found, number) -> str:
    """The candidates as the model is told them: numbered, as the card numbers them."""
    lines = []
    for n, p in enumerate(found.people, 1):
        bits = [p["name"]] + [p[k] for k in ("headline", "location") if p.get(k)]
        lines.append(f"{n}. " + " - ".join(bits) + f" ({p['url']})")
    return "\n".join(lines)


def profile_text(data: dict) -> str:
    """A harvested profile as text, for the model to talk about."""
    out = [" - ".join(v for v in (data.get("name"), data.get("headline")) if v)]
    head = [v for v in [data.get("location")] + list(data.get("facts") or []) if v]
    if head:
        out.append(" · ".join(head))
    out.append(data.get("url") or "")
    if data.get("about"):
        out += ["", "About:", data["about"]]
    if data.get("experience"):
        out += ["", "Experience:"]
        for job in data["experience"]:
            when = ", ".join(v for v in (job.get("dates"), job.get("duration")) if v)
            line = "- " + ", ".join(v for v in (job.get("title"), job.get("company")) if v)
            if when:
                line += f" ({when})"
            if job.get("location"):
                line += f", {job['location']}"
            out.append(line)
            if job.get("description"):
                out.append("  " + _shorter(job["description"], 500))
    if data.get("education"):
        out += ["", "Education:"]
        out += ["- " + ", ".join(v for v in (s.get("school"), s.get("degree"), s.get("dates"))
                                 if v) for s in data["education"]]
    if data.get("skills"):
        out += ["", "Skills: " + ", ".join(data["skills"])]
    if data.get("certifications"):
        out += ["", "Certifications: " + "; ".join(
            ", ".join(v for v in (c.get("title"), c.get("by"), c.get("when")) if v)
            for c in data["certifications"])]
    if data.get("languages"):
        out += ["", "Languages: " + ", ".join(data["languages"])]
    if data.get("recommendations"):
        out += ["", f"Recommendations received ({len(data['recommendations'])}):"]
        out += [f"- {r.get('by') or 'Somebody'} ({r.get('when') or 'undated'}): "
                f"{_shorter(r['text'], 300)}" for r in data["recommendations"]]
    who = data.get("name") or "the person"
    if data.get("posts"):
        out += ["", f"Latest posts and reposts ({len(data['posts'])}). Only an item "
                    f"marked [own post] is {who}'s own writing, and in an item marked "
                    "[reposted with own comment] only the words after \"their comment\" "
                    "are; every other word below is the original author's, named on the "
                    "item. LinkedIn's posts listing holds only what they posted or "
                    "reposted; their comments and reactions follow it."]
        out += [_post_line(post) for post in data["posts"]]
    elif data.get("posts_said"):
        out += ["", data["posts_said"]]
    elif data.get("posts_read"):
        out += ["", "No posts or reposts of theirs were found."]
    if data.get("activity"):
        out += ["", f"Their latest comments and reactions on posts ({len(data['activity'])}), "
                    "newest first. The posts are not theirs unless it says so:"]
        out += [_post_line(post) for post in data["activity"]]
    elif data.get("activity_said"):
        out += ["", data["activity_said"]]
    return _shorter("\n".join(out), TEXT_MAX)


def _post_line(post: dict) -> str:
    """One post as the model reads it: when, how it stands to them, whose words."""
    said = label(post)
    if not said:
        # A card harvested before 5 October 2026: only a repost with words of
        # its own was told apart then, so nothing else is anybody's for sure.
        said = (f"reposted; original post by {post['repost_of']}" if post.get("repost_of")
                else LABELS[UNKNOWN])
        post = dict(post, text=post.get("text") if post.get("repost_of") else "",
                    original_text=(post.get("repost_text") if post.get("repost_of")
                                   else post.get("text")) or "",
                    original_author=post.get("repost_of") or "")
    words = []
    if post.get("text"):
        mine = "their own words" if post.get("relation") == OWN else "their comment"
        words.append(f"{mine}: \"{_shorter(_one_line(post['text']), 400)}\"")
    if post.get("original_text"):
        by = post.get("original_author") or "an author LinkedIn did not name (not them)"
        words.append(f"{by} wrote: \"{_shorter(_one_line(post['original_text']), 300)}\"")
    counts = ("" if post.get("relation") in (COMMENTED, LIKED, REACTED) else
              f", {post.get('likes', 0)} likes, {post.get('comments', 0)} comments")
    return (f"- {post.get('date') or post.get('ago') or 'undated'}{counts} "
            f"[{said}]: " + " | ".join(words))


def block_text(block: dict) -> str:
    """One of this module's blocks as markdown, for a card filed as a step.

    Neither is a block a step file can name, so each is written as what reads
    back to something every page draws: the candidates as a list, the profile
    as prose. The words are all kept, which is what a step is for.
    """
    name = str(block.get("block") or "")
    if name == PEOPLE:
        rows = [" | ".join(v for v in (p.get("name"), p.get("headline"), p.get("location"),
                                       p.get("url")) if v)
                for p in block.get("people") or [] if isinstance(p, dict)]
        return (":::list\n" + "".join(f"- {_one_line(r)}\n" for r in rows) + ":::\n"
                if rows else "")
    if name == PROFILE:
        return profile_text(block).replace("\n- ", "\n* ") + "\n"
    return ""


# --- a pick ----------------------------------------------------------------


@dataclass
class Picked:
    """What a pick did, for the socket or the tool that asked."""

    ok: bool
    why: str = ""
    #: Worth pressing again: LinkedIn was slow, not the card wrong.
    again: bool = False
    chat: str = ""
    number: int = 0
    index: int = -1
    person: dict | None = None
    #: The profile harvested, and the card it was drawn on.
    data: dict | None = None
    drawn: dict | None = None
    #: The list of candidates as it now reads, with this one marked.
    picker: dict | None = None
    #: The card this one had been harvested onto already, when it had.
    already: int | None = None
    #: The contact the profile was kept on, by name, when the list was for one.
    kept_on: str = ""


_locks: dict[int, asyncio.Lock] = {}


async def pick(card, index, who, apify: Apify, *,
               draw: Callable[[dict, str], Awaitable[dict | None]], root: str = "") -> Picked:
    """Harvest the person at number `index` (from 0) on card `card`, for `who`.

    Reads the card as the server has it now; checks that its token is one this
    server signed and that it is `who`'s; harvests; hands the profile card to
    `draw`, which puts it on the screen and gives back what it drew; and marks
    the candidate on the list with the number of that card. One card's picks
    are made one at a time, so two presses on the same row harvest once and
    two on different rows both stay marked.
    """
    try:
        number, index = int(card), int(index)
    except (TypeError, ValueError):
        return Picked(False, "That is not a card and a number on it.")
    if not artifacts.enabled():
        return Picked(False, "Cards cannot be answered from here on this machine. "
                             "Say which one to Rouh instead.")
    async with _locks.setdefault(number, asyncio.Lock()):
        spec = await asyncio.to_thread(artifacts.read, number)
        _at, block = people_of(spec)
        if block is None:
            return Picked(False, f"Card {number} is not a list of people to pick from.")
        sealed = _read(block)
        if sealed is None:
            log.warning("card %s carries a list this server did not sign; refused", number)
            return Picked(False, "This list cannot be picked from with a button.")
        if sealed.get("expired"):
            return Picked(False, "This list is too old to press. Ask Rouh to search again.")
        if (getattr(who, "user_id", None), getattr(who, "org_id", None)) != \
                (sealed.get("u"), sealed.get("o")):
            log.warning("card %s was pressed by somebody it does not belong to", number)
            return Picked(False, "This list is not yours to pick from.")
        urls = list(sealed.get("urls") or [])
        people = list(block.get("people") or [])
        if not 0 <= index < len(urls):
            return Picked(False, f"There is no number {index + 1} on card {number}; it "
                                 f"has {len(urls)}.")
        person = people[index] if index < len(people) and isinstance(people[index], dict) \
            else {"url": urls[index], "name": unquote(slug_of(urls[index]))}
        chat = str(sealed.get("c") or "")
        done = (block.get("picked") or {}).get(str(index))
        if done:
            return Picked(True, chat=chat, number=number, index=index, person=person,
                          already=int(done))
        if not apify.ready():
            return Picked(False, "LinkedIn research is not set up on this machine: there "
                                 "is no Apify key.")
        try:
            data = await harvest(apify, urls[index])
        except NotFound as exc:
            # The others on the list are still worth pressing.
            return Picked(False, f"{exc} Nothing was harvested.", again=True, chat=chat,
                          number=number, index=index, person=person)
        except Trouble as exc:
            return Picked(False, f"{exc} Nothing was harvested.", again=True, chat=chat,
                          number=number, index=index, person=person)
        kept_on = ""
        if sealed.get("p"):
            kept_on = await _keep_on_contact(who, str(sealed["p"]), data)
        drawn = await draw(profile_card(data), chat)
        picker = None
        if drawn and drawn.get("card_id") is not None:
            picker = await asyncio.to_thread(_mark, number, index, drawn["card_id"], root,
                                             who=who if kept_on else None,
                                             contact=str(sealed.get("p") or ""))
        return Picked(True, chat=chat, number=number, index=index, person=person, data=data,
                      drawn=drawn, picker=picker, kept_on=kept_on)


async def _keep_on_contact(who, pid: str, data: dict) -> str:
    """The profile kept on the contact the list was for; their name, or "" when it was not."""
    from . import meeting_people

    try:
        await meeting_people.keep_picked(who, pid, data)
    except Exception:  # noqa: BLE001 - the profile is still drawn; the contact says nothing changed
        log.exception("a picked LinkedIn profile could not be kept on contact %s", pid)
        return ""
    return data.get("name") or "the contact"


def _mark(number: int, index: int, drawn_as, root: str, *, who=None,
          contact: str = "") -> dict | None:
    """The list of candidates again, saying which of them is on which card now.

    With `who` and `contact`, the list was on that contact's card and the profile was kept on
    them, so the contact above it is drawn again as it now reads, research and face included.
    """
    spec = artifacts.read(number)
    at, block = people_of(spec)
    if block is None:
        return None
    blocks = list(spec.get("blocks") or [])
    blocks[at] = dict(block, picked=dict(block.get("picked") or {}, **{str(index): drawn_as}))
    if who is not None and contact:
        from . import apple_contacts
        from .people import People

        fresh = People().person(str(who.user_id), str(who.org_id), contact)
        for k, b in enumerate(blocks):
            if fresh is not None and isinstance(b, dict) and b.get("block") == "contact" \
                    and str(b.get("contact") or "") == contact:
                blocks[k] = apple_contacts.profile_card(
                    fresh, state=b.get("state") or "shown", status=b.get("status") or "")["blocks"][0]
    return artifacts.revise(number, title=spec.get("title"),
                            description=spec.get("description"), blocks=blocks, root=root)


def picked_note(got: Picked) -> str:
    """What the conversation is told after a press harvested somebody."""
    from . import untrusted

    person = got.person or {}
    who = person.get("name") or "that person"
    card = (got.drawn or {}).get("card_id")
    kept = (" It is kept on their contact in Synapse as their online research, because the "
            "list was the candidates for that contact." if got.kept_on else "")
    return (
        f"the person pressed Research on number {got.index + 1}, {who}, on card "
        f"{got.number}, rather than saying which one, and Rouh harvested that LinkedIn "
        f"profile in full: it is on the screen now as card {card}.{kept} Say in one or two "
        "short sentences who this is and what stands out, and do not read the card out. "
        "Do not harvest them again. The profile:\n"
        + untrusted.wrap(profile_text(got.data or {}), untrusted.SOURCES["linkedin_profile"]))


# --- small things ------------------------------------------------------------


def _signer():
    from django.core import signing

    return signing


def _read(block: dict) -> dict | None:
    signing = _signer()
    try:
        got = signing.loads(str(block.get("token") or ""), salt=SALT, max_age=MAX_AGE)
    except signing.SignatureExpired:
        return {"expired": True}
    except signing.BadSignature:
        return None
    return got if isinstance(got, dict) else None


def _items(value) -> list:
    return [v for v in value if v is not None] if isinstance(value, list) else []


def _one_line(value) -> str:
    return " ".join(str(value if value is not None else "").split())


def _text(value, most: int) -> str:
    """Somebody's words, their lines kept, cut where a card would stop."""
    text = str(value if value is not None else "").replace("\r\n", "\n").strip()
    text = re.sub(r"\n{3,}", "\n\n", text)
    return _shorter(text, most)


def _shorter(text: str, most: int) -> str:
    text = str(text or "")
    if len(text) <= most:
        return text
    cut = text[:most].rsplit(" ", 1)[0].rstrip(" ,;:-")
    return cut + "…"


def _folded(text: str) -> str:
    """Letters only, lower case and without accents, for comparing names."""
    decomposed = unicodedata.normalize("NFKD", str(text or "").lower())
    return " ".join("".join(c for c in decomposed
                            if c.isalnum() or c.isspace()).split())


def _location(value) -> str:
    if isinstance(value, dict):
        return _one_line(value.get("linkedinText") or (value.get("parsed") or {}).get("text"))
    return _one_line(value)


def _address(value) -> str:
    said = str(value or "").strip()
    return said if said.startswith(("https://", "http://")) else ""


def _picture(value, want: int) -> str:
    """The address of a picture, in the size nearest `want` that is at least it."""
    if isinstance(value, str):
        return _address(value)
    if not isinstance(value, dict):
        return ""
    sizes = [s for s in _items(value.get("sizes"))
             if isinstance(s, dict) and _address(s.get("url"))]
    if sizes:
        big_enough = [s for s in sizes if (_number(s.get("width")) or 0) >= want]
        chosen = (min(big_enough, key=lambda s: _number(s.get("width")) or 0) if big_enough
                  else max(sizes, key=lambda s: _number(s.get("width")) or 0))
        return _address(chosen.get("url"))
    return _address(value.get("url"))


def _span(start, end) -> str:
    def said(value) -> str:
        return _one_line(value.get("text")) if isinstance(value, dict) else _one_line(value)

    begun, ended = said(start), said(end)
    return f"{begun} - {ended}" if begun and ended else begun or ended


def _number(value) -> int | None:
    try:
        return int(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _true(value) -> bool:
    return value is True or str(value).strip().lower() == "true"


__all__ = ["Apify", "Found", "LABELS", "NotFound", "Owner", "PEOPLE", "PROFILE", "Picked",
           "Trouble", "block_text", "candidate", "harvest", "label", "people_of", "pick",
           "picked_note",
           "picker_card", "picker_text", "profile", "profile_card", "profile_text",
           "profile_url", "relation", "search", "slug_of", "strip"]
