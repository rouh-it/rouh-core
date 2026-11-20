"""Slides registration for the Google stand-in (`rouh/google_api/slides.py`).

A deck is seeded by a test with ``POST /_deck`` ``{"id", "name", "slides": [{"id", "title", "text",
"notes"}], "modifiedTime"?, "lastModifyingUser"?, "parents"?}``: it becomes a Google Slides file in
Drive, its words are what Drive's export and a full-text search find, and
``GET /v1/presentations/<id>`` sends it the way the Slides API does, each slide with its elements
and its notes page. ``GET /v1/presentations/<id>/pages/<slide>/thumbnail`` answers with the address
of a picture of the slide, drawn here as an SVG with the slide's title and words.
"""
from __future__ import annotations

import html

from . import ACCOUNT_EMAIL, JSONResponse, Request, Response, _owner_permission

PRESENTATION = "application/vnd.google-apps.presentation"


def _text(words: str) -> dict:
    return {"textElements": [{"textRun": {"content": line + "\n"}}
                             for line in str(words or "").splitlines()]}


def _as_slides_api(deck: dict) -> dict:
    slides = []
    for one in deck["slides"]:
        sid = one["id"]
        elements = []
        if one.get("title"):
            elements.append({"objectId": f"{sid}_t",
                             "shape": {"placeholder": {"type": "TITLE"}, "text": _text(one["title"])}})
        if one.get("text"):
            elements.append({"objectId": f"{sid}_b",
                             "shape": {"placeholder": {"type": "BODY"}, "text": _text(one["text"])}})
        notes_id = f"{sid}_n"
        notes = {"objectId": notes_id, "shape": {"placeholder": {"type": "BODY"}}}
        if one.get("notes"):
            notes["shape"]["text"] = _text(one["notes"])
        slides.append({"objectId": sid, "pageElements": elements,
                       "slideProperties": {"notesPage": {
                           "notesProperties": {"speakerNotesObjectId": notes_id},
                           "pageElements": [notes]}}})
    return {"presentationId": deck["id"], "title": deck["name"],
            "revisionId": deck.get("revision") or "r1", "slides": slides}


def deck_text(deck: dict) -> str:
    """What Drive's own export of a deck gives: every slide's words and notes, run together."""
    parts = []
    for one in deck["slides"]:
        parts.extend(w for w in (one.get("title"), one.get("text"), one.get("notes")) if w)
        parts.append("")
    return "\n".join(parts)


def _slides_routes(app, world, seen, note, file_named):
    world.setdefault("decks", {})

    @app.post("/_deck")
    async def seed_deck(request: Request):
        got = await request.json()
        deck_id = str(got.get("id") or "")
        slides = [{"id": str(s.get("id") or f"p{i}"), "title": str(s.get("title") or ""),
                   "text": str(s.get("text") or ""), "notes": str(s.get("notes") or "")}
                  for i, s in enumerate(got.get("slides") or [], start=1)]
        deck = {"id": deck_id, "name": str(got.get("name") or "Untitled"), "slides": slides,
                "revision": str(got.get("revision") or "r1")}
        world["decks"][deck_id] = deck
        found = file_named(deck_id)
        if found is None:
            found = {"id": deck_id, "mimeType": PRESENTATION, "parents": got.get("parents") or ["root"],
                     "trashed": False, "owners": [{"displayName": "Alex Morgan",
                                                    "emailAddress": ACCOUNT_EMAIL}],
                     "permissions": [_owner_permission()]}
            world["files"].append(found)
        found.update({"name": deck["name"], "content": deck_text(deck),
                      "modifiedTime": got.get("modifiedTime") or "2026-10-29T12:00:00Z",
                      "webViewLink": f"https://docs.google.com/presentation/d/{deck_id}/edit"})
        if got.get("lastModifyingUser"):
            found["lastModifyingUser"] = got["lastModifyingUser"]
        note("deck seeded", {"id": deck_id, "slides": len(slides)})
        return JSONResponse({"ok": True})

    @app.get("/v1/presentations/{deck_id}")
    async def read_deck(deck_id: str, request: Request):
        seen["api"].append(str(request.url))
        deck = world["decks"].get(deck_id)
        if deck is None:
            return JSONResponse({"error": {"code": 404, "message": "Requested entity was not found."}},
                                status_code=404)
        return JSONResponse(_as_slides_api(deck))

    @app.post("/v1/presentations/{deck_id}:batchUpdate")
    async def batch_update(deck_id: str, request: Request):
        """Enough of the Slides batchUpdate to be read back: replaceAllText (all slides or some),
        deleteText and insertText on a slide's speaker notes, and createSlide, duplicateObject,
        updateSlidesPosition and deleteObject (Written into a deck,
        `rouh/slide_write.py`). Each really changes the deck held here."""
        deck = world["decks"].get(deck_id)
        if deck is None:
            return JSONResponse({"error": {"code": 404, "message": "Requested entity was not found."}},
                                status_code=404)
        body = await request.json()
        note("deck edited", {"id": deck_id, "requests": body.get("requests") or []})
        replies = []
        for one in body.get("requests") or []:
            if "replaceAllText" in one:
                ask = one["replaceAllText"]
                find = str((ask.get("containsText") or {}).get("text") or "")
                put = str(ask.get("replaceText") or "")
                pages = set(ask.get("pageObjectIds") or [])
                changed = 0
                for slide in deck["slides"]:
                    if pages and slide["id"] not in pages:
                        continue
                    for field in ("title", "text"):
                        changed += slide[field].count(find) if find else 0
                        slide[field] = slide[field].replace(find, put) if find else slide[field]
                replies.append({"replaceAllText": {"occurrencesChanged": changed}})
            elif "createSlide" in one:
                ask = one["createSlide"]
                made = {"id": str(ask.get("objectId") or f"p{len(deck['slides']) + 1}x"), "title": "",
                        "text": "", "notes": ""}
                for m in ask.get("placeholderIdMappings") or []:
                    kind = (m.get("layoutPlaceholder") or {}).get("type")
                    made["boxes"] = {**made.get("boxes", {}), str(m.get("objectId")): "title" if kind == "TITLE" else "text"}
                at = ask.get("insertionIndex")
                at = len(deck["slides"]) if at is None else int(at)
                if not 0 <= at <= len(deck["slides"]):
                    return JSONResponse({"error": {"code": 400, "message": "Invalid requests: insertionIndex out of range."}},
                                        status_code=400)
                deck["slides"].insert(at, made)
                replies.append({"createSlide": {"objectId": made["id"]}})
            elif "duplicateObject" in one:
                ask = one["duplicateObject"]
                src = next((x for x in deck["slides"] if x["id"] == ask.get("objectId")), None)
                if src is None:
                    return JSONResponse({"error": {"code": 400, "message": "Invalid requests: the object could not be found."}},
                                        status_code=400)
                made = {**src, "id": str((ask.get("objectIds") or {}).get(src["id"]) or src["id"] + "_copy"), "boxes": {}}
                deck["slides"].insert(deck["slides"].index(src) + 1, made)
                replies.append({"duplicateObject": {"objectId": made["id"]}})
            elif "updateSlidesPosition" in one:
                ask = one["updateSlidesPosition"]
                ids = list(ask.get("slideObjectIds") or [])
                at = int(ask.get("insertionIndex") or 0)
                moving = [x for x in deck["slides"] if x["id"] in ids]
                if len(moving) != len(ids) or not 0 <= at <= len(deck["slides"]):
                    return JSONResponse({"error": {"code": 400, "message": "Invalid requests: updateSlidesPosition."}},
                                        status_code=400)
                before = sum(1 for x in deck["slides"][:at] if x["id"] in ids)
                rest = [x for x in deck["slides"] if x["id"] not in ids]
                deck["slides"] = rest[:at - before] + sorted(moving, key=lambda x: ids.index(x["id"])) + rest[at - before:]
                replies.append({})
            elif "deleteObject" in one:
                target = one["deleteObject"].get("objectId")
                if not any(x["id"] == target for x in deck["slides"]):
                    return JSONResponse({"error": {"code": 400, "message": "Invalid requests: the object could not be found."}},
                                        status_code=400)
                deck["slides"] = [x for x in deck["slides"] if x["id"] != target]
                replies.append({})
            elif "insertText" in one and any(str(one["insertText"].get("objectId")) in (x.get("boxes") or {})
                                             for x in deck["slides"]):
                ask = one["insertText"]
                box = str(ask.get("objectId"))
                slide = next(x for x in deck["slides"] if box in (x.get("boxes") or {}))
                slide[slide["boxes"][box]] += str(ask.get("text") or "")
                replies.append({})
            elif "deleteText" in one or "insertText" in one:
                ask = one.get("deleteText") or one.get("insertText")
                target = str(ask.get("objectId") or "")
                slide = next((x for x in deck["slides"] if f"{x['id']}_n" == target), None)
                if slide is None:
                    return JSONResponse({"error": {"code": 400, "message":
                                         f"Invalid requests: the object ({target}) could not be found."}},
                                        status_code=400)
                if "deleteText" in one:
                    if not slide["notes"]:
                        return JSONResponse({"error": {"code": 400, "message":
                                             "Invalid requests[0].deleteText: The object has no text."}},
                                            status_code=400)
                    slide["notes"] = ""
                else:
                    at = int(ask.get("insertionIndex") or 0)
                    slide["notes"] = slide["notes"][:at] + str(ask.get("text") or "") + slide["notes"][at:]
                replies.append({})
            else:
                replies.append({})
        found = file_named(deck_id)
        if found is not None:
            found["content"] = deck_text(deck)
        deck["revision"] = "r" + str(int(str(deck.get("revision") or "r1").lstrip("r") or 1) + 1)
        return JSONResponse({"presentationId": deck_id, "replies": replies})

    @app.get("/v1/presentations/{deck_id}/pages/{page_id}/thumbnail")
    async def thumbnail(deck_id: str, page_id: str, request: Request):
        seen["api"].append(str(request.url))
        deck = world["decks"].get(deck_id)
        if deck is None or not any(s["id"] == page_id for s in deck["slides"]):
            return JSONResponse({"error": {"code": 404, "message": "Requested entity was not found."}},
                                status_code=404)
        base = str(request.base_url).rstrip("/")
        return JSONResponse({"width": 800, "height": 450,
                             "contentUrl": f"{base}/_thumb/{deck_id}/{page_id}.svg"})

    @app.get("/_thumb/{deck_id}/{page_id}.svg")
    async def thumb_picture(deck_id: str, page_id: str):
        deck = world["decks"].get(deck_id) or {"slides": []}
        slide = next((s for s in deck["slides"] if s["id"] == page_id), None)
        if slide is None:
            return Response(status_code=404)
        lines = [line for line in slide["text"].splitlines() if line][:6]
        body = "".join(f'<text x="48" y="{170 + 40 * i}" font-size="26" fill="#334">'
                       f'{html.escape(line[:60])}</text>' for i, line in enumerate(lines))
        svg = ('<svg xmlns="http://www.w3.org/2000/svg" width="800" height="450" viewBox="0 0 800 450">'
               '<rect width="800" height="450" fill="#f6f4ee"/><rect width="800" height="12" fill="#2f6f5e"/>'
               f'<text x="48" y="100" font-size="40" font-weight="bold" fill="#123">'
               f'{html.escape(slide["title"][:40])}</text>{body}</svg>')
        return Response(svg, media_type="image/svg+xml")
