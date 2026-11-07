"""Docs registration for the Google stand-in."""
from __future__ import annotations

import base64

from . import (
    ACCOUNT_EMAIL,
    JSONResponse,
    Request,
    Response,
    _body,
    _insert_text,
    _owner_permission,
    _replace_text,
    _tabs,
)


def _docs_routes(app, world, seen, note, made_up, file_named):
    # --- Docs ---------------------------------------------------------------------

    @app.post("/v1/documents")
    async def create_document(request: Request):
        body = await request.json()
        document_id = made_up("doc")
        world["documents"][document_id] = {
            "documentId": document_id, "title": body.get("title") or "Untitled",
            "body": {"content": [{"endIndex": 1, "sectionBreak": {}}]},
        }
        world["files"].append({
            "id": document_id, "name": body.get("title") or "Untitled",
            "mimeType": "application/vnd.google-apps.document",
            "modifiedTime": "2026-09-16T12:00:00Z", "parents": ["root"], "trashed": False,
            "webViewLink": f"https://docs.google.com/document/d/{document_id}/edit",
            "owners": [{"displayName": "Alex Morgan", "emailAddress": ACCOUNT_EMAIL}],
            "permissions": [_owner_permission()]})
        note("document made", {"id": document_id, "title": body.get("title") or ""})
        return JSONResponse(world["documents"][document_id])

    @app.get("/v1/documents/{document_id}")
    async def read_document(document_id: str, request: Request, includeTabsContent: str = ""):
        """A document, the way the Docs API sends one.

        With `includeTabsContent=true`, every tab, each nested one under its
        parent, and no `body`. Without it, the first tab's body alone, which is
        all the Docs API ever sends then however many tabs there are: the
        fault read_doc had until 24 September 2026. Anything in Drive that is
        not a document is refused the way the Docs API refuses it.
        """
        seen["api"].append(str(request.url))
        document = world["documents"].get(document_id)
        if document is None:
            if file_named(document_id) is not None:
                return JSONResponse({"error": {
                    "code": 400, "status": "FAILED_PRECONDITION",
                    "message": "This operation is not supported for this document"}},
                    status_code=400)
            return JSONResponse({"error": {"message": "Requested entity was not found."}},
                                status_code=404)
        about = {"documentId": document["documentId"], "title": document.get("title") or ""}
        if includeTabsContent == "true":
            return JSONResponse({**about, "tabs": _tabs(document)})
        return JSONResponse({**about, "body": _body(document)})

    @app.post("/_doc")
    async def seed_document(request: Request):
        """A document with words and pictures, the way the Docs API sends one.

        `{"id", "name", "parts": ["a paragraph", {"picture": "<base64>", "title": "...",
        "description": "..."}, ...]}`: each part is a paragraph, a picture standing in a
        paragraph of its own, at an address served below (Pictures in docs seen,
        `rouh/doc_pictures.py`). `{"drawing": true}` is a picture Google hands no address for.
        """
        got = await request.json()
        document_id = str(got.get("id") or made_up("doc"))
        base = str(request.base_url).rstrip("/")
        content, objects, pictures = [{"endIndex": 1, "sectionBreak": {}}], {}, {}
        for n, part in enumerate(got.get("parts") or [], start=1):
            if isinstance(part, str):
                content.append({"paragraph": {"elements": [{"textRun": {"content": part + "\n"}}]}})
                continue
            if part.get("runs"):
                # A paragraph of runs, some of them suggested edits nobody has accepted yet:
                # `{"runs": [{"text": "..."}, {"text": "...", "insert": "suggest.1"},
                # {"text": "...", "delete": "suggest.2"}]}` (Suggested edits read as
                # suggestions, `rouh/doc_suggestions.py`).
                runs = []
                for run in part["runs"]:
                    one = {"content": str(run.get("text") or "")}
                    if run.get("insert"):
                        one["suggestedInsertionIds"] = [str(run["insert"])]
                    if run.get("delete"):
                        one["suggestedDeletionIds"] = [str(run["delete"])]
                    runs.append({"textRun": one})
                runs.append({"textRun": {"content": "\n"}})
                content.append({"paragraph": {"elements": runs}})
                continue
            object_id = f"kix.pic{n}"
            about = {"title": part.get("title") or "", "description": part.get("description") or ""}
            if not part.get("drawing"):
                pictures[object_id] = base64.b64decode(part.get("picture") or "")
                about["imageProperties"] = {"contentUri": f"{base}/_doc_picture/{document_id}/{object_id}"}
            objects[object_id] = {"objectId": object_id,
                                  "inlineObjectProperties": {"embeddedObject": about}}
            content.append({"paragraph": {"elements": [
                {"inlineObjectElement": {"inlineObjectId": object_id}},
                {"textRun": {"content": "\n"}}]}})
        world["documents"][document_id] = {
            "documentId": document_id, "title": got.get("name") or "Untitled",
            "tabs": [{"tabProperties": {"tabId": "t.0", "title": "Tab 1", "index": 0},
                      "documentTab": {"body": {"content": content}, "inlineObjects": objects}}]}
        world.setdefault("doc_pictures", {})[document_id] = pictures
        if file_named(document_id) is None:
            world["files"].append({
                "id": document_id, "name": got.get("name") or "Untitled",
                "mimeType": "application/vnd.google-apps.document",
                "modifiedTime": "2026-10-30T12:00:00Z", "parents": ["root"], "trashed": False,
                "webViewLink": f"https://docs.google.com/document/d/{document_id}/edit",
                "owners": [{"displayName": "Alex Morgan", "emailAddress": ACCOUNT_EMAIL}],
                "permissions": [_owner_permission()]})
        note("document seeded", {"id": document_id, "pictures": len(pictures)})
        return JSONResponse({"ok": True, "id": document_id})

    @app.get("/_doc_picture/{document_id}/{object_id}")
    async def doc_picture(document_id: str, object_id: str, request: Request):
        seen["api"].append(str(request.url))
        data = (world.get("doc_pictures") or {}).get(document_id, {}).get(object_id)
        if data is None:
            return JSONResponse({"error": {"code": 404, "message": "Not found."}}, status_code=404)
        return Response(content=data, media_type="image/png")

    @app.post("/v1/documents/{document_id}:batchUpdate")
    async def batch_update(document_id: str, request: Request):
        """Enough of batchUpdate to be worth asserting against.

        Only two request kinds, because only two are ever sent: insertText at
        an index, and replaceAllText. Both really change the document this
        holds, so the test that reads it back afterwards is reading the result
        of the request rather than the request repeated.
        """
        document = world["documents"].get(document_id)
        if document is None:
            return JSONResponse({"error": {"message": "Requested entity was not found."}},
                                status_code=404)
        body = await request.json()
        note("document edited", {"id": document_id, "requests": body.get("requests") or []})
        replies = []
        for one in body.get("requests") or []:
            if "insertText" in one:
                _insert_text(document, one["insertText"])
                replies.append({})
            elif "replaceAllText" in one:
                changed = _replace_text(document, one["replaceAllText"])
                replies.append({"replaceAllText": {"occurrencesChanged": changed}})
            else:
                replies.append({})
        return JSONResponse({"documentId": document_id, "replies": replies})
