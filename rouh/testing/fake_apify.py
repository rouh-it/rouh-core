"""A stand-in for Apify's HarvestAPI scrapers, so LinkedIn research can be driven.

The same idea as `fake_brevo.py`: a real HTTP server in front of the real
client (`rouh/linkedin.py`), so what a check proves is what went over the wire.
Nothing here reaches LinkedIn, and nobody in it is real: every person, company
and post is made up from the name that was asked for, the same way every time.

It answers ``POST /v2/acts/<actor>/run-sync-get-dataset-items`` for the five
actors Rouh runs, in the shapes HarvestAPI really answers in (measured against
the real ones on 26 September 2026), and refuses a request whose bearer token
is not the one it was started with, with Apify's own 401.

- **The search** answers the way LinkedIn does to a logged-out search, which is
  unevenly: the first ask of a name gets three people, the second the whole
  page, the third three from the end. Rouh asks three times and keeps
  everybody (`linkedin.TRIES`), so a card with the whole page on it is what
  proves that works. A last name of ``Nobody`` finds nobody at all.
- **The profile** is a whole one for anybody the search could have found. An
  identifier starting ``gone-`` is Apify's own answer for a profile that is
  not there.
- **The posts** are five, one of each kind: their own, a plain repost of
  somebody else's (the shape that once made a stranger's #OpenToWork read as
  theirs), an old plain share with a picture, a repost with their own comment,
  and one with no author at all. Their comments and reactions are one comment,
  one like and one Celebrate.

Faces and logos are drawn here too (``/_face/<id>.svg``, ``/_logo/<name>.svg``),
and one person in four has no picture, as on LinkedIn, so the initials that
stand in for one are seen as well.

``GET /_calls`` lists every run asked for, oldest first, for a check that
wants to know what was harvested and how often.

Point ``ROUH_APIFY_URL`` at it and give Rouh ``APIFY_API_TOKEN`` = `KEY`.
`rouh/testing/browser.py` does both for the ``talking`` world.

    python -m rouh.testing.fake_apify --port 8097
"""
from __future__ import annotations

import argparse
import hashlib
import html
import time
from collections import Counter

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

#: The token this stand-in accepts, and the one the talking world is given.
KEY = "apify_api_test0not0a0real0one"

COMPANIES = ["Sintra Labs", "Northwind Logistics", "Blue Harbor Bank", "Kvadrat Studio",
             "Atlantic Data Works", "Orbit Payments", "Mura Health", "Helios Energy",
             "Cedar & Co", "Estrela Robotics"]
ROLES = ["Head of Engineering", "Product Manager", "Senior Accountant", "Founder",
         "Data Scientist", "Marketing Director", "UX Designer", "Sales Lead",
         "Chief Technology Officer", "Recruiter"]
PLACES = ["Lisbon, Portugal", "Porto, Portugal", "London, England, United Kingdom",
          "Berlin, Germany", "Faro, Portugal", "Vienna, Austria", "Toronto, Ontario, Canada",
          "Lisbon Metropolitan Area", "Amsterdam, North Holland, Netherlands", "Portugal"]
SCHOOLS = ["University of Lisbon", "Technical University of Lisbon",
           "Nova School of Business and Economics", "Catholic University of Portugal"]
COLOURS = ["#2f6f9f", "#8a4fbf", "#2e8b6a", "#b5663a", "#a33f5a", "#4a5fc1", "#6b7d2a",
           "#337b88", "#9c4a2f", "#5d5d8f"]


def _n(text: str) -> int:
    return int(hashlib.sha256(text.encode()).hexdigest()[:8], 16)


def _slug(first: str, last: str, i: int) -> str:
    base = "-".join(w for w in f"{first} {last}".lower().split() if w)
    return f"{base}-{(_n(base) + i * 7919) % 90000 + 10000}"


def people_for(first: str, last: str, *, company: str = "", location: str = "",
               title: str = "") -> list[dict]:
    """Everybody by this name, as a search page of short profiles, ten at most."""
    if last.strip().lower() == "nobody":
        return []
    seed = _n(f"{first} {last}".lower())
    out = []
    for i in range(10):
        k = (seed + i) % 10
        works = company or COMPANIES[k]
        role = title or ROLES[(k * 3 + i) % 10]
        place = location or PLACES[(k + 2 * i) % 10]
        out.append({"i": i, "first": first, "last": last, "role": role, "company": works,
                    "place": place, "slug": _slug(first, last, i), "face": i % 4 != 3})
    # A filter is a narrower page, as it is on LinkedIn.
    return out[:3] if (company or title) else out


def _short(p: dict, base: str) -> dict:
    item = {"id": f"ACoAA{_n(p['slug']):010d}", "name": f"{p['first']} {p['last']}",
            "position": f"{p['role']} at {p['company']}",
            "location": {"linkedinText": p["place"]},
            "linkedinUrl": f"https://www.linkedin.com/in/{p['slug']}",
            "publicIdentifier": p["slug"]}
    if p["face"]:
        item["photo"] = f"{base}/_face/{p['slug']}.svg"
    return item


def _person(slug: str) -> dict | None:
    """Who is behind an identifier the search made up: name, role, place."""
    parts = slug.rsplit("-", 1)
    if len(parts) != 2 or not parts[1].isdigit():
        return None
    words = parts[0].split("-")
    if len(words) < 2:
        return None
    first, last = words[0].title(), " ".join(words[1:]).title()
    for p in people_for(first, last):
        if p["slug"] == slug:
            return p
    return None


def _picture(url: str) -> dict:
    return {"url": url,
            "sizes": [{"url": url, "width": w, "height": w} for w in (800, 400, 200, 100)]}


def full_profile(slug: str, base: str) -> dict:
    p = _person(slug)
    if p is None:
        # Somebody asked for by an address rather than found: made up the same way.
        seed = _n(slug)
        p = {"first": "Alex", "last": "Stone", "role": ROLES[seed % 10],
             "company": COMPANIES[seed % 10], "place": PLACES[seed % 10], "slug": slug,
             "face": True, "i": seed % 10}
    k = _n(p["slug"])
    before = COMPANIES[(k + 3) % 10]
    first_job = COMPANIES[(k + 5) % 10]

    def logo(name: str) -> dict:
        return _picture(f"{base}/_logo/{name.replace(' ', '_').replace('&', 'and')}.svg")

    def page(name: str) -> str:
        return f"https://www.linkedin.com/company/{name.lower().replace(' ', '-')}/"

    profile = {
        "id": f"ACoAA{k:010d}", "publicIdentifier": p["slug"],
        "linkedinUrl": f"https://www.linkedin.com/in/{p['slug']}",
        "firstName": p["first"], "lastName": p["last"],
        "headline": f"{p['role']} at {p['company']}",
        "openToWork": False, "hiring": p["i"] % 3 == 0, "premium": p["i"] % 2 == 0,
        "influencer": False, "verified": True,
        "location": {"linkedinText": p["place"], "countryCode": "BG"},
        "registeredAt": f"{2008 + k % 12}-03-14T10:00:00.000Z",
        "topSkills": "Leadership • Strategy",
        "connectionsCount": 300 + k % 900, "followerCount": 320 + k % 2400,
        "about": (f"I lead {p['role'].lower()} work at {p['company']}, where we build things "
                  "people rely on every day.\n\nBefore that I spent six years at "
                  f"{before}, growing a team from three people to forty. I care about clear "
                  "writing, fair hiring and shipping small things often.\n\nOutside work: "
                  "mountains, film photography and a very old dog."),
        "experience": [
            {"position": p["role"], "location": p["place"], "employmentType": "Full-time",
             "workplaceType": "Hybrid", "companyName": p["company"],
             "companyLinkedinUrl": page(p["company"]),
             "companyLogo": logo(p["company"]), "duration": "2 yrs 4 mos",
             "description": ("Leading a group of 24 across three teams. Set up the hiring "
                             "loop, the planning rhythm and the on-call rota; cut the time "
                             "from idea to release from six weeks to two.\n\nOwn the budget "
                             "and the roadmap for the whole product line, and report to the "
                             "board every quarter on both."),
             "startDate": {"month": "May", "year": 2024, "text": "May 2024"},
             "endDate": {"text": "Present"}},
            {"position": "Team Lead", "location": "Lisbon",
             "employmentType": "Full-time", "companyName": before,
             "companyLinkedinUrl": page(before),
             "companyLogo": logo(before), "duration": "6 yrs",
             "description": "Grew the team from three people to forty.",
             "startDate": {"month": "Apr", "year": 2018, "text": "Apr 2018"},
             "endDate": {"month": "Apr", "year": 2024, "text": "Apr 2024"}},
            {"position": "Junior Analyst", "companyName": first_job,
             "companyLogo": logo(first_job), "duration": "3 yrs",
             "startDate": {"year": 2015, "text": "2015"},
             "endDate": {"year": 2018, "text": "2018"}},
        ],
        "education": [
            {"schoolName": SCHOOLS[k % 4], "degree": "Master's degree",
             "fieldOfStudy": "Computer Science", "period": "2010 - 2015",
             "schoolLogo": logo("school")},
            {"schoolName": "St Julian's School, Lisbon", "period": "2005 - 2010"},
        ],
        "skills": [{"name": s} for s in ("Leadership", "Hiring", "Product Strategy", "Python",
                                          "Public Speaking", "Budgeting", "Mentoring", "SQL")],
        "certifications": [{"title": "Certified Scrum Master", "issuedBy": "Scrum Alliance",
                            "issuedAt": "Issued Jan 2021"}],
        "languages": [{"name": "Portuguese", "proficiency": "Native or bilingual proficiency"},
                      {"name": "English", "proficiency": "Full professional proficiency"}],
        "receivedRecommendations": [
            {"givenBy": "Marta Silva", "givenAt": "March 3, 2023",
             "givenByLink": "https://www.linkedin.com/in/marta-silva-00000",
             "givenByHeadline": "COO at " + before,
             "description": (f"{p['first']} is the calmest person in any room. They made our "
                             "hiring fair and our releases boring, which is the highest "
                             "praise I have.")}],
    }
    if p["face"]:
        profile["profilePicture"] = _picture(f"{base}/_face/{p['slug']}.svg")
        profile["photo"] = f"{base}/_face/{p['slug']}.svg"
    return profile


def _owner(slug: str) -> dict:
    """The author block HarvestAPI gives a post by the person at `slug`."""
    p = _person(slug)
    name = f"{p['first']} {p['last']}" if p else "Alex Stone"
    return {"id": f"ACoAA{_n(slug):010d}", "universalName": None, "publicIdentifier": slug,
            "type": "profile", "name": name,
            "linkedinUrl": f"https://www.linkedin.com/in/{slug}?miniProfileUrn=x"}


def _stranger(name: str) -> dict:
    slug = "-".join(name.lower().split()) + "-55555"
    return {"id": f"ACoAA{_n(slug):010d}", "universalName": None, "publicIdentifier": slug,
            "type": "profile", "name": name,
            "linkedinUrl": f"https://www.linkedin.com/in/{slug}?miniProfileUrn=y"}


def _when(at: int) -> dict:
    return {"timestamp": at, "date": time.strftime("%Y-%m-%dT%H:%M:%S.000Z",
                                                   time.gmtime(at / 1000))}


def posts_for(slug: str, base: str) -> list[dict]:
    """Five items, one of each kind the posts actor really lists (5 October 2026):
    their own post; a plain repost of somebody else's, which carries that
    person's words as its ``content`` with ``repostedBy`` them; an older plain
    share, theirs with no words and the original under ``repost``; a repost
    with their own comment; and one that says nothing about who wrote it."""
    k = _n(slug)
    day = 24 * 3600 * 1000
    now = int(time.time() * 1000)
    me = _owner(slug)
    out = []
    for i in range(5):
        at = now - (i * 9 + k % 5 + 1) * day
        post = {"type": "post", "id": str(7400000000000000000 + k + i),
                "linkedinUrl": f"https://www.linkedin.com/posts/{slug}_post-{i}",
                "author": me, "content": "",
                "postedAt": dict(_when(at), postedAgoShort=f"{(i * 9 + k % 5 + 1)}d"),
                "postImages": [], "header": {"text": None},
                "engagement": {"likes": 12 + (k + i * 17) % 90, "comments": (k + i) % 9}}
        if i == 0:
            post["content"] = ("We are hiring two engineers in Lisbon. Small team, real "
                               "problems, no heroics. Write to me if that sounds like you.")
        elif i == 1:
            post.update(author=_stranger("Elena Marinova"),
                        linkedinUrl="https://www.linkedin.com/posts/elena-marinova_opentowork",
                        content=("Hi everyone! I am looking for a new role in product design "
                                 "and would love your support. #OpenToWork"),
                        repostedBy={"name": me["name"], "publicIdentifier": slug,
                                    "linkedinUrl": me["linkedinUrl"]},
                        repostedAt=_when(at),
                        header={"text": f"{me['name']} reposted this"})
        elif i == 2:
            post["repost"] = {"author": {"name": "Sintra Labs", "type": "company",
                                         "universalName": "sintra-labs"},
                              "content": "Our spring meetup is on 14 May. Talks, coffee and "
                                         "a very long table.",
                              "postImages": [{"url": f"{base}/_logo/meetup.svg"}]}
        elif i == 3:
            post["content"] = "Proud of the team for shipping the new payments flow this week."
            post["repost"] = {"author": {"name": "Orbit Payments", "type": "company",
                                         "universalName": "orbit-payments"},
                              "content": "Today we launch one-tap payments across Portugal."}
        else:
            del post["author"]
            post["content"] = ("Three things I learned running our first offsite:\n\n"
                               "1. Fewer slides.\n2. Longer walks.\n"
                               "3. Write the decisions down before dinner.")
        out.append(post)
    return out


def comments_for(slug: str) -> list[dict]:
    """Their latest comment, as the Profile Comments actor answers."""
    at = int(time.time() * 1000) - 2 * 24 * 3600 * 1000
    return [{"id": "7408878906923077632", "commentary": "Congratulations, well deserved!",
             "createdAt": _when(at)["date"], "createdAtTimestamp": at,
             "linkedinUrl": "https://www.linkedin.com/feed/update/urn:li:ugcPost:1?commentUrn=c",
             "engagement": {"likes": 2, "comments": 0},
             "actor": dict(_owner(slug), author=False),
             "post": {"id": "1", "author": _stranger("Ivo Kolev"),
                      "linkedinUrl": "https://www.linkedin.com/posts/ivo-kolev_new-job",
                      "content": "I am delighted to share that I have joined Helios Energy "
                                 "as head of research."}}]


def reactions_for(slug: str) -> list[dict]:
    """Their latest reactions, as the Profile Reactions actor answers."""
    me = _owner(slug)
    out = []
    for i, (verb, who, text) in enumerate((
            ("likes", "Petya Ilieva", "Ten years at Mura Health today. Thank you all."),
            ("celebrates", "Ivo Kolev", "I am delighted to share that I have joined Helios "
                                        "Energy as head of research."))):
        at = int(time.time() * 1000) - (3 + i) * 24 * 3600 * 1000
        out.append({"id": str(7474900942845571072 + i), "action": f"{me['name']} {verb} this",
                    "createdAt": _when(at)["date"], "createdAtTimestamp": at,
                    "actor": {"id": me["id"], "linkedinUrl": me["linkedinUrl"]},
                    "post": {"id": str(i), "author": _stranger(who), "content": text,
                             "linkedinUrl": f"https://www.linkedin.com/posts/x_{i}",
                             "engagement": {"likes": 40 + i, "comments": 3}}})
    return out


def _svg(letters: str, colour: str, square: bool = False) -> Response:
    shape = ('<rect width="200" height="200" rx="28"' if square
             else '<circle cx="100" cy="100" r="100"') + f' fill="{colour}"/>'
    body = (f'<svg xmlns="http://www.w3.org/2000/svg" width="200" height="200" '
            f'viewBox="0 0 200 200">{shape}'
            + ('' if square else
               '<circle cx="100" cy="82" r="38" fill="#ffffff" fill-opacity="0.22"/>'
               '<ellipse cx="100" cy="178" rx="64" ry="46" fill="#ffffff" fill-opacity="0.22"/>')
            + f'<text x="100" y="{118 if square else 112}" font-family="sans-serif" '
              f'font-size="{64 if square else 56}" font-weight="700" fill="#ffffff" '
              f'text-anchor="middle">{html.escape(letters)}</text></svg>')
    return Response(body, media_type="image/svg+xml",
                    headers={"Cache-Control": "public, max-age=86400"})


def build_app(key: str = KEY) -> FastAPI:
    app = FastAPI()
    calls: list[dict] = []
    asked: Counter = Counter()

    @app.get("/v2/users/me")
    async def me(request: Request):
        """Who the token is, as Settings, Keys checks it (`rouh/service_keys.py`)."""
        if request.headers.get("authorization") != f"Bearer {key}":
            return JSONResponse({"error": {"type": "user-or-token-not-found",
                                           "message": "User was not found or authentication "
                                                      "token is not valid"}}, status_code=401)
        return JSONResponse({"data": {"id": "fakeUser", "username": "alex-example"}})

    @app.post("/v2/acts/{actor}/run-sync-get-dataset-items")
    async def run(actor: str, request: Request):
        if request.headers.get("authorization") != f"Bearer {key}":
            return JSONResponse({"error": {"type": "user-or-token-not-found",
                                           "message": "User was not found or authentication "
                                                      "token is not valid"}}, status_code=401)
        try:
            body = await request.json()
        except ValueError:
            body = {}
        base = str(request.base_url).rstrip("/")
        calls.append({"at": time.time(), "actor": actor.replace("~", "/"), "input": body})
        if actor == "harvestapi~linkedin-profile-search-by-name":
            first, last = str(body.get("firstName") or ""), str(body.get("lastName") or "")
            found = people_for(first, last,
                               company=(body.get("currentCompanies") or [""])[0],
                               location=(body.get("locations") or [""])[0],
                               title=(body.get("currentJobTitles") or [""])[0])
            query = (first.lower(), last.lower(), repr(sorted(body.items())))
            asked[query] += 1
            turn = asked[query] % 3
            page = found if turn == 2 or len(found) <= 3 else (
                found[:3] if turn == 1 else found[-3:])
            return JSONResponse([_short(p, base) for p in page], status_code=201)
        if actor == "harvestapi~linkedin-profile-scraper":
            out = []
            for url in body.get("urls") or []:
                slug = str(url).rstrip("/").rsplit("/in/", 1)[-1].split("/")[0]
                if slug.startswith("gone-") or not slug:
                    out.append({"element": None, "status": 404, "error": "Profile not found",
                                "originalQuery": {"url": url}})
                else:
                    out.append(dict(full_profile(slug, base), originalQuery={"url": url}))
            return JSONResponse(out, status_code=201)
        if actor == "harvestapi~linkedin-profile-posts":
            out = []
            for url in body.get("targetUrls") or []:
                slug = str(url).rstrip("/").rsplit("/in/", 1)[-1].split("/")[0]
                if not slug.startswith("gone-"):
                    out += posts_for(slug, base)[: int(body.get("maxPosts") or 10)]
            return JSONResponse(out, status_code=201)
        if actor in ("harvestapi~linkedin-profile-comments",
                     "harvestapi~linkedin-profile-reactions"):
            make = comments_for if actor.endswith("comments") else reactions_for
            out = []
            for url in body.get("profiles") or []:
                slug = str(url).rstrip("/").rsplit("/in/", 1)[-1].split("/")[0]
                if not slug.startswith("gone-"):
                    out += make(slug)[: int(body.get("maxItems") or 10)]
            return JSONResponse(out, status_code=201)
        return JSONResponse({"error": {"type": "record-not-found",
                                       "message": f"Actor {actor} was not found"}},
                            status_code=404)

    @app.get("/_face/{slug}.svg")
    async def face(slug: str):
        p = _person(slug)
        name = f"{p['first']} {p['last']}" if p else slug
        letters = "".join(w[0] for w in name.split()[:2]).upper()
        return _svg(letters, COLOURS[_n(slug) % len(COLOURS)])

    @app.get("/_logo/{name}.svg")
    async def logo(name: str):
        words = name.replace("_", " ").split()
        return _svg("".join(w[0] for w in words[:2]).upper() or "?",
                    COLOURS[(_n(name) + 3) % len(COLOURS)], square=True)

    @app.get("/_calls")
    async def listed():
        """Every run asked for, oldest first."""
        return JSONResponse(calls)

    return app


def main() -> None:
    import uvicorn

    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, required=True)
    args = ap.parse_args()
    uvicorn.run(build_app(), host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
