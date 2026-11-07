"""A stand-in for iCloud's CardDAV, so Apple Contacts can be driven for real.

Rouh's side of CardDAV is only worth testing if the requests really go out
over HTTP, as XML, with a real Basic authorisation header, and really come
back as the multistatus bodies iCloud sends. A mock inside the process proves
none of that. So this is a real HTTP server that speaks the part of CardDAV
iCloud speaks, laid out the way iCloud lays it out:

    PROPFIND /                                    current-user-principal
    PROPFIND /1234567890/principal/                addressbook-home-set, on another host
    PROPFIND /1234567890/carddavhome/              the home, and the book inside it
    PROPFIND /1234567890/carddavhome/card/         every card and its ETag (Depth 1)
    REPORT   .../card/   sync-collection           what changed since a token
    REPORT   .../card/   addressbook-multiget      the cards themselves
    PUT      .../card/<uid>.vcf                    If-Match / If-None-Match: *
    DELETE   .../card/<uid>.vcf                    If-Match

What is iCloud's and was measured, on 24 September 2026, is copied exactly: a
wrong Apple ID or app-specific password is a 401 with an empty body and
``WWW-Authenticate: X-MobileMe-AuthToken realm="Newcastle", Basic
realm="Newcastle"``, and the root asked with no credentials at all is a 404.
The home is named on a different host from the one that was asked, as iCloud
names ``p52-contacts.icloud.com``: here that is ``localhost`` where Rouh was
pointed at ``127.0.0.1``, so following an absolute address across hosts is
exercised and not assumed. What was not measured is written from RFC 6352
and RFC 6578 and is strict about them: both REPORTs refuse anything but
``Depth: 0``, a stale sync token is a 403 carrying ``valid-sync-token``, a
removed card is a response with a 404 status and no propstat, and a card
changed on the way in (this adds a REV line, as a server may) is answered
without an ETag, so Rouh has to read back what was really kept.

A few addresses beginning with an underscore stand in for the rest of the
world and are not CardDAV: ``/_phone`` edits or deletes a card as the iPhone
would, which is how a conflict is made; ``/_password`` changes the password
that is accepted, which is how one is revoked; ``/_expire`` makes every sync
token stale; ``/_options`` makes sync-collection page its answers, or not
exist at all; ``/_state`` and ``/_seen`` say what it holds and what it was
asked.

    python -m rouh.testing.fake_carddav --port 8098
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import re
import time
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

#: Whose iCloud this is. The world owner's Apple ID, because their account's
#: address is what the Settings box suggests (`rouh/testing/browser.py`,
#: `OWNER`), and a password in the shape Apple issues.
APPLE_ID = "alex@example.com"
APP_PASSWORD = "wxyz-abcd-efgh-ijkl"

#: The account's number, as iCloud puts it in every address.
DSID = "1234567890"
#: The other host the home is named on, as iCloud names a partition host. ``localhost`` beside
#: a Rouh pointed at ``127.0.0.1``; the stack test names a sibling of the host the core reaches
#: this at (`tests/stack/standins.py`).
PARTITION = {"host": "localhost"}

#: iCloud's own answer to credentials it does not accept.
REFUSAL_HEADERS = {
    "WWW-Authenticate": 'X-MobileMe-AuthToken realm="Newcastle", Basic realm="Newcastle"',
}

D, C = "{DAV:}", "{urn:ietf:params:xml:ns:carddav}"
MULTI = ('<?xml version="1.0" encoding="UTF-8"?>\n<multistatus xmlns="DAV:" '
         'xmlns:card="urn:ietf:params:xml:ns:carddav" '
         'xmlns:cs="http://calendarserver.org/ns/">{}</multistatus>')

_PHOTO = base64.b64encode(hashlib.sha256(b"a portrait").digest() * 12).decode()


def _card(lines: list[str]) -> str:
    """A card as iCloud writes one: CRLF, folded at 75 octets."""
    from rouh.vcard import fold

    return "".join(fold(line) + "\r\n" for line in ["BEGIN:VCARD", "VERSION:3.0", *lines,
                                                    "PRODID:-//Apple Inc.//iPhone OS 26.0//EN",
                                                    "END:VCARD"])


#: The address book it starts with. Written the way an iPhone writes them:
#: TYPE parameters one per value, Apple's `item` groups with X-ABLabel for a
#: label Apple has no TYPE for, a birthday with no year as 1604, a group card
#: that is not a person, a Cyrillic name, a folded photo.
SEED = {
    "A1F2C3D4-0001-4000-8000-000000000001": [
        "N:Park;Nina;;;", "FN:Nina Park", "ORG:Paywell;",
        "TEL;type=CELL;type=VOICE;type=pref:+359 888 123 456",
        "item1.TEL;type=VOICE:+44 20 7946 0000", "item1.X-ABLabel:_$!<Work>!$_",
        "EMAIL;type=INTERNET;type=WORK;type=pref:nina@paywell.test",
        "BDAY;VALUE=date:1985-03-12",
        "NOTE:Met at the Lisbon fintech meetup\\, spring 2025.",
        "UID:A1F2C3D4-0001-4000-8000-000000000001",
    ],
    "A1F2C3D4-0002-4000-8000-000000000002": [
        "N:Doyle;Chris;;;", "FN:Chris Doyle", "ORG:Harbor Bank;Board",
        "TEL;type=IPHONE;type=CELL;type=VOICE:+359 878 555 010",
        "EMAIL;type=INTERNET;type=HOME:chris@harbor.test",
        "BDAY;X-APPLE-OMIT-YEAR=1604;VALUE=date:1604-07-04",
        "UID:A1F2C3D4-0002-4000-8000-000000000002",
    ],
    "A1F2C3D4-0003-4000-8000-000000000003": [
        "N:Димитров;Иван;;;", "FN:Иван Димитров", "ORG:Пример ООД;",
        "TEL;type=CELL;type=VOICE:0887 44 55 66",
        f"PHOTO;ENCODING=b;TYPE=JPEG:{_PHOTO}",
        "UID:A1F2C3D4-0003-4000-8000-000000000003",
    ],
    "A1F2C3D4-0004-4000-8000-000000000004": [
        "N:Hart;Lena;;;", "FN:Lena Hart",
        "item1.TEL:+49 30 1234 5678", "item1.X-ABLabel:Studio",
        "EMAIL;type=INTERNET:lena@hartdesign.test",
        "item2.ADR;type=WORK:;;Torstrasse 1;Berlin;;10119;Germany",
        "item2.X-ABADR:de",
        "NOTE:Designer. Did the Rouh icon\\; invoice via the studio.\\nPrefers WhatsApp.",
        "UID:A1F2C3D4-0004-4000-8000-000000000004",
    ],
    "A1F2C3D4-0005-4000-8000-000000000005": [
        "N:;;;;", "FN:City Plumbing", "ORG:City Plumbing;",
        "TEL;type=MAIN:+359 2 987 6543", "X-ABShowAs:COMPANY",
        "UID:A1F2C3D4-0005-4000-8000-000000000005",
    ],
    "A1F2C3D4-0006-4000-8000-000000000006": [
        "N:Álvarez;José;;;", "FN:José Álvarez",
        "EMAIL;type=INTERNET;type=WORK:jose@alvarez.test",
        "UID:A1F2C3D4-0006-4000-8000-000000000006",
    ],
    # The world's owner, as an iPhone keeps a card today: the picture at an address on the photo host
    # (here this server, `/_photos/`, asked with the same sign-in as iCloud's), with the part the phone
    # shows kept as X-ABCROP-RECTANGLE; addresses labelled by TYPE, by Apple's own X-ABLabel and by one
    # the person made up.
    "A1F2C3D4-0008-4000-8000-000000000008": [
        "N:Morgan;Alex;;;", "FN:Alex Morgan", "ORG:Morgan Studio;",
        "EMAIL;type=INTERNET;type=HOME;type=pref:alex@example.com",
        "EMAIL;type=INTERNET;type=WORK:alex@morgan-studio.test",
        "item1.EMAIL;type=INTERNET:alex.morgan@gmail.test", "item1.X-ABLabel:_$!<Other>!$_",
        "item2.EMAIL;type=INTERNET:alex@icloud.test", "item2.X-ABLabel:iCloud",
        "item3.EMAIL;type=INTERNET:press@morgan-studio.test", "item3.X-ABLabel:Press desk",
        "TEL;type=CELL;type=VOICE;type=pref:+44 7700 900 123",
        "PHOTO;X-ABCROP-RECTANGLE=ABClipRect_1&420&40&400&400&aGFzaA==;VALUE=uri:"
        "{photos}/_photos/alex-morgan.jpg",
        "UID:A1F2C3D4-0008-4000-8000-000000000008",
    ],
    "A1F2C3D4-0007-4000-8000-000000000007": [
        "N:Family", "FN:Family", "X-ADDRESSBOOKSERVER-KIND:group",
        "X-ADDRESSBOOKSERVER-MEMBER:urn:uuid:A1F2C3D4-0002-4000-8000-000000000002",
        "UID:A1F2C3D4-0007-4000-8000-000000000007",
    ],
}


def _with_host(data: str, request: Request) -> str:
    """A card as served: its picture's address on this server, as the phone would have it."""
    if "{photos}" not in data.replace("\r\n ", ""):
        return data
    from rouh.vcard import fold, unfold

    lines = [ln.replace("{photos}", f"http://{PARTITION['host']}:{request.url.port}") for ln in unfold(data)]
    return "".join(fold(ln) + "\r\n" for ln in lines)


def _portrait() -> bytes:
    """A wide picture with a background, the face off to one side: what the crop and the round frame are
    for. 1200 by 600, a blue backdrop, and a face whose middle is at 620 across and 360 down, which is
    the middle of the crop the card keeps (420 across, 40 up from the bottom, 400 square)."""
    import io

    from PIL import Image, ImageDraw

    image = Image.new("RGB", (1200, 600), (40, 70, 140))
    draw = ImageDraw.Draw(image)
    for y in range(600):
        draw.line([(0, y), (1200, y)], fill=(40, 70 + y // 10, 140 + y // 8))
    draw.ellipse([520, 230, 720, 470], fill=(236, 196, 160))           # the face
    draw.ellipse([505, 200, 735, 330], fill=(70, 50, 40))              # hair
    draw.ellipse([570, 320, 595, 345], fill=(40, 40, 40))              # eyes
    draw.ellipse([645, 320, 670, 345], fill=(40, 40, 40))
    draw.arc([585, 370, 655, 420], 20, 160, fill=(150, 60, 60), width=6)
    draw.rectangle([0, 0, 300, 600], fill=(200, 140, 40))              # something else in the picture
    out = io.BytesIO()
    image.save(out, "JPEG", quality=90)
    return out.getvalue()


def _uid_of(data: str) -> str:
    found = re.search(r"^UID:(.+?)\r?$", data, re.MULTILINE)
    return found.group(1).strip() if found else ""


class Book:
    """The one address book, with every change numbered so tokens mean something."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.rev = 0
        #: Bumped by /_expire: a token from an earlier generation is stale.
        self.generation = 1
        self.cards: dict[str, dict] = {}         # name -> {"data", "etag", "rev"}
        self.tombstones: dict[str, int] = {}     # name -> rev it went at
        self.page = 0                            # 0: sync-collection answers whole
        self.sync_collection = True
        for uid, lines in SEED.items():
            self.put(uid + ".vcf", _card(lines))

    def put(self, name: str, data: str) -> dict:
        self.rev += 1
        etag = '"C=' + str(self.rev) + "@U=" + hashlib.md5(data.encode()).hexdigest()[:12] + '"'
        self.cards[name] = {"data": data, "etag": etag, "rev": self.rev}
        self.tombstones.pop(name, None)
        return self.cards[name]

    def remove(self, name: str) -> None:
        self.rev += 1
        self.cards.pop(name, None)
        self.tombstones[name] = self.rev

    def token(self, rev: int | None = None) -> str:
        return f"HwoQEgwAAA{self.generation:04d}{self.rev if rev is None else rev:08d}AA=="

    def rev_of(self, token: str) -> int | None:
        """The change a token stands for, or None when it is not one still honoured."""
        found = re.fullmatch(r"HwoQEgwAAA(\d{4})(\d{8})AA==", token or "")
        if not found or int(found.group(1)) != self.generation:
            return None
        return int(found.group(2))

    def by_uid(self, uid: str) -> str | None:
        for name, card in self.cards.items():
            if _uid_of(card["data"]) == uid:
                return name
        return None


def build(apple_id: str = APPLE_ID, password: str = APP_PASSWORD) -> FastAPI:
    app = FastAPI()
    book = Book()
    state = {"apple_id": apple_id, "password": password}
    seen: list[dict] = []

    def home_url(request: Request) -> str:
        # Another host, as iCloud's partition hosts are.
        port = request.url.port
        return f"http://{PARTITION['host']}:{port}/{DSID}/carddavhome/"

    def book_path() -> str:
        return f"/{DSID}/carddavhome/card/"

    def signed_in(request: Request) -> bool | None:
        raw = request.headers.get("authorization", "")
        if not raw.lower().startswith("basic "):
            return None
        try:
            user, _, secret = base64.b64decode(raw[6:]).decode().partition(":")
        except (ValueError, UnicodeDecodeError):
            return False
        return user.lower() == state["apple_id"].lower() and secret == state["password"]

    def multistatus(parts: list[str], status: int = 207) -> Response:
        return Response(MULTI.format("".join(parts)), status_code=status,
                        media_type="application/xml; charset=utf-8")

    def response(href: str, props: str, missing: str = "") -> str:
        out = f"<response><href>{escape(href)}</href>"
        if props:
            out += f"<propstat><prop>{props}</prop><status>HTTP/1.1 200 OK</status></propstat>"
        if missing:
            out += (f"<propstat><prop>{missing}</prop>"
                    "<status>HTTP/1.1 404 Not Found</status></propstat>")
        return out + "</response>"

    def asked_for(body: bytes) -> set[str]:
        try:
            root = ET.fromstring(body or b"<x/>")
        except ET.ParseError:
            return set()
        prop = root.find(f"{D}prop")
        return {child.tag for child in prop} if prop is not None else set()

    # --- the rest of the world ---------------------------------------------------

    @app.get("/_photos/{name}")
    async def _photos(name: str, request: Request):
        """A contact's picture on the photo host, behind the same sign-in as the cards."""
        if not signed_in(request):
            return Response(status_code=401, headers=REFUSAL_HEADERS)
        if name != "alex-morgan.jpg":
            return Response(status_code=404)
        return Response(_portrait(), media_type="image/jpeg")

    @app.get("/_state")
    async def _state():
        return {"apple_id": state["apple_id"], "rev": book.rev,
                "cards": [{"name": n, "uid": _uid_of(c["data"]), "etag": c["etag"],
                           "data": c["data"]} for n, c in sorted(book.cards.items())]}

    @app.get("/_seen")
    async def _seen():
        return seen

    @app.post("/_reset")
    async def _reset():
        book.reset()
        seen.clear()
        state["password"] = password
        return {"ok": True}

    @app.post("/_password")
    async def _password(request: Request):
        state["password"] = (await request.json()).get("password", "")
        return {"ok": True}

    @app.post("/_expire")
    async def _expire():
        # Every token handed out so far, including the newest, is now stale.
        book.generation += 1
        return {"ok": True}

    @app.post("/_options")
    async def _options(request: Request):
        said = await request.json()
        book.page = int(said.get("page", book.page) or 0)
        book.sync_collection = bool(said.get("sync_collection", book.sync_collection))
        return {"ok": True, "page": book.page, "sync_collection": book.sync_collection}

    @app.post("/_phone")
    async def _phone(request: Request):
        """An edit made on the iPhone: set lines by name, or delete the card."""
        said = await request.json()
        name = book.by_uid(said.get("uid", ""))
        if name is None:
            return JSONResponse({"error": "no such card"}, status_code=404)
        if said.get("delete"):
            book.remove(name)
            return {"ok": True, "deleted": name}
        lines = book.cards[name]["data"].replace("\r\n ", "").split("\r\n")
        for key, value in (said.get("set") or {}).items():
            lines = [ln for ln in lines if not re.match(rf"^{re.escape(key)}[;:]", ln, re.IGNORECASE)]
            if value:
                lines.insert(len(lines) - 2, f"{key}:{value}")
        from rouh.vcard import fold

        data = "".join(fold(ln) + "\r\n" for ln in lines if ln)
        card = book.put(name, data)
        return {"ok": True, "etag": card["etag"]}

    # --- CardDAV --------------------------------------------------------------------

    @app.api_route("/{path:path}", methods=["PROPFIND", "REPORT", "PUT", "DELETE", "GET"])
    async def dav(path: str, request: Request):
        where = "/" + path
        body = await request.body()
        who = signed_in(request)
        seen.append({"method": request.method, "path": where,
                     "host": request.headers.get("host", ""),
                     "depth": request.headers.get("depth"),
                     "if_match": request.headers.get("if-match"),
                     "if_none_match": request.headers.get("if-none-match"),
                     "signed_in": bool(who), "at": time.time()})
        if who is None and where == "/":
            return Response(status_code=404)
        if not who:
            return Response(status_code=401, headers=REFUSAL_HEADERS)
        if where == "/.well-known/carddav":
            return Response(status_code=301, headers={"Location": "/"})
        method = request.method
        depth = request.headers.get("depth", "")

        if method == "PROPFIND":
            wanted = asked_for(body)
            if where == "/":
                return multistatus([response("/", "<current-user-principal><href>"
                                             f"/{DSID}/principal/</href>"
                                             "</current-user-principal>")])
            if where == f"/{DSID}/principal/":
                props = ""
                if f"{C}addressbook-home-set" in wanted:
                    props += (f"<card:addressbook-home-set><href>{home_url(request)}</href>"
                              "</card:addressbook-home-set>")
                if f"{D}displayname" in wanted:
                    props += "<displayname>Alex Morgan</displayname>"
                return multistatus([response(where, props)])
            if where == f"/{DSID}/carddavhome/":
                parts = [response(where, "<resourcetype><collection/></resourcetype>")]
                if depth == "1":
                    parts.append(response(book_path(), "<resourcetype><collection/>"
                                          "<card:addressbook/></resourcetype>"
                                          "<displayname>card</displayname>"))
                return multistatus(parts)
            if where == book_path():
                parts = [response(where, "<resourcetype><collection/><card:addressbook/>"
                                  f"</resourcetype><sync-token>{book.token()}</sync-token>"
                                  f"<cs:getctag>{book.rev}</cs:getctag>")]
                if depth == "1":
                    for name, card in sorted(book.cards.items()):
                        parts.append(response(book_path() + name,
                                              f"<getetag>{escape(card['etag'])}</getetag>"
                                              "<getcontenttype>text/vcard</getcontenttype>"))
                return multistatus(parts)
            return Response(status_code=404)

        if method == "REPORT":
            if where != book_path():
                return Response(status_code=404)
            if depth != "0":
                return Response("Depth must be 0 for this report", status_code=400)
            try:
                root = ET.fromstring(body)
            except ET.ParseError:
                return Response(status_code=400)
            if root.tag == f"{D}sync-collection":
                if not book.sync_collection:
                    return Response(status_code=403)
                token = (root.findtext(f"{D}sync-token") or "").strip()
                since = 0
                if token:
                    since = book.rev_of(token)
                    if since is None or since > book.rev:
                        return Response(
                            '<?xml version="1.0" encoding="UTF-8"?>\n<error xmlns="DAV:">'
                            "<valid-sync-token/></error>", status_code=403,
                            media_type="application/xml; charset=utf-8")
                items = [(c["rev"], n, c) for n, c in book.cards.items() if c["rev"] > since]
                if token:
                    items += [(r, n, None) for n, r in book.tombstones.items() if r > since]
                items.sort(key=lambda item: item[0])
                more = bool(book.page) and len(items) > book.page
                if more:
                    items = items[:book.page]
                parts = []
                for _rev, name, card in items:
                    if card is None:
                        parts.append(f"<response><href>{book_path()}{name}</href>"
                                     "<status>HTTP/1.1 404 Not Found</status></response>")
                    else:
                        parts.append(response(book_path() + name,
                                              f"<getetag>{escape(card['etag'])}</getetag>"))
                if more:
                    parts.append(f"<response><href>{book_path()}</href>"
                                 "<status>HTTP/1.1 507 Insufficient Storage</status>"
                                 "<error><number-of-matches-within-limits/></error></response>")
                upto = items[-1][0] if (more and items) else book.rev
                parts.append(f"<sync-token>{book.token(upto)}</sync-token>")
                return multistatus(parts)
            if root.tag == f"{C}addressbook-multiget":
                parts = []
                for href in root.findall(f"{D}href"):
                    name = (href.text or "").rsplit("/", 1)[-1]
                    card = book.cards.get(name)
                    if card is None:
                        parts.append(f"<response><href>{escape(href.text or '')}</href>"
                                     "<status>HTTP/1.1 404 Not Found</status></response>")
                        continue
                    parts.append(response(book_path() + name,
                                          f"<getetag>{escape(card['etag'])}</getetag>"
                                          f"<card:address-data>{escape(_with_host(card['data'], request))}"
                                          "</card:address-data>"))
                return multistatus(parts)
            return Response(status_code=400)

        if not where.startswith(book_path()) or where == book_path():
            return Response(status_code=405)
        name = where[len(book_path()):]
        held = book.cards.get(name)

        if method == "GET":
            if held is None:
                return Response(status_code=404)
            return Response(held["data"], media_type="text/vcard; charset=utf-8",
                            headers={"ETag": held["etag"]})

        if method == "PUT":
            if "text/vcard" not in request.headers.get("content-type", ""):
                return Response(status_code=415)
            data = body.decode("utf-8")
            if "BEGIN:VCARD" not in data or not _uid_of(data):
                return Response(status_code=400)
            match = request.headers.get("if-match")
            none_match = request.headers.get("if-none-match")
            if match is not None and (held is None or match.strip() != held["etag"]):
                return Response(status_code=412)
            if none_match == "*" and held is not None:
                return Response(status_code=412)
            other = book.by_uid(_uid_of(data))
            if other is not None and other != name:
                return Response('<?xml version="1.0" encoding="UTF-8"?>\n<error xmlns="DAV:" '
                                'xmlns:card="urn:ietf:params:xml:ns:carddav">'
                                '<card:no-uid-conflict/></error>', status_code=403,
                                media_type="application/xml; charset=utf-8")
            # Kept with a REV line of the server's own, so it is not what was
            # sent, and so there is no ETag in the answer (RFC 6352 5.3.4).
            lines = [ln for ln in data.replace("\r\n ", "").split("\r\n")
                     if ln and not ln.upper().startswith("REV:")]
            lines.insert(len(lines) - 1,
                         "REV:" + time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
            from rouh.vcard import fold

            book.put(name, "".join(fold(ln) + "\r\n" for ln in lines))
            return Response(status_code=201 if held is None else 204)

        if method == "DELETE":
            if held is None:
                return Response(status_code=404)
            match = request.headers.get("if-match")
            if match is not None and match.strip() != held["etag"]:
                return Response(status_code=412)
            book.remove(name)
            return Response(status_code=204)
        return Response(status_code=405)

    return app


def main() -> None:
    import uvicorn

    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--apple-id", default=APPLE_ID)
    ap.add_argument("--password", default=APP_PASSWORD)
    args = ap.parse_args()
    uvicorn.run(build(args.apple_id, args.password), host="127.0.0.1", port=args.port,
                log_level="warning")


if __name__ == "__main__":
    main()
