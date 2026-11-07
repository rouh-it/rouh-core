"""Drive registration for the Google stand-in."""
from __future__ import annotations

from . import (
    FOLDER_TYPE,
    JSONResponse,
    PlainTextResponse,
    Request,
    Response,
    _a_file,
    _document_text,
    _owner_permission,
    _read_multipart,
    _refused,
    _what_arrived,
)


def _drive_routes(app, world, seen, note, made_up, file_named, drive_named, holding_permissions):
    # --- Drive ------------------------------------------------------------------

    @app.get("/drive/v3/files")
    async def files(request: Request, q: str = "", corpora: str = "", driveId: str = "",
                    includeItemsFromAllDrives: str = "", orderBy: str = ""):
        seen["api"].append(str(request.url))
        found = [f for f in world["files"] if not f.get("trashed")]
        # A shared drive is only in the answer when the caller said it handles
        # one, which is exactly what Drive itself does: without
        # includeItemsFromAllDrives a shared drive's files are not returned.
        if includeItemsFromAllDrives != "true":
            found = [f for f in found if not f.get("driveId")]
        if corpora == "drive":
            found = [f for f in found if f.get("driveId") == driveId]
        elif corpora in ("", "user"):
            # The default body of items: My Drive and what is shared with the
            # person. A shared drive's own files are in it only because
            # includeItemsFromAllDrives widened it above.
            pass
        if "' in parents" in q:
            parent = q.split("'", 1)[1].split("' in parents", 1)[0].replace("\\'", "'")
            found = [f for f in found if parent in (f.get("parents") or [])]
        if "name = '" in q:
            want = q.split("name = '", 1)[1].split("'", 1)[0].replace("\\'", "'")
            found = [f for f in found if f["name"] == want]
        elif "fullText contains '" in q:
            # A search of the name or the words inside, as `Drive.search` asks: a deck's words
            # are what its export gives (`slides.deck_text`), a file's its content.
            want = q.split("contains '", 1)[1].split("'", 1)[0].replace("\\'", "'").lower()
            found = [f for f in found if want in f["name"].lower()
                     or want in str(f.get("content") or "").lower()]
        elif "contains '" in q:
            want = q.split("contains '", 1)[1].split("'", 1)[0].replace("\\'", "'").lower()
            found = [f for f in found if want in f["name"].lower()]
        if "mimeType = '" in q:
            kind = q.split("mimeType = '", 1)[1].split("'", 1)[0]
            found = [f for f in found if f["mimeType"] == kind]
        # Deliberately the wrong way round for a listing: the answer comes back
        # oldest first and files before folders, so a test that sees folders
        # first and newest first is seeing Rouh's own ordering rather than a
        # list that happened to arrive sorted.
        if orderBy:
            found = sorted(found, key=lambda f: (f["mimeType"] == FOLDER_TYPE,
                                                 f.get("modifiedTime", "")))
        return JSONResponse({"files": found})

    @app.get("/drive/v3/drives")
    async def shared_drives(request: Request, pageSize: int = 10):
        """The shared drives this account can see. Its own endpoint, because a
        shared drive is not a folder in anybody's Drive."""
        seen["api"].append(str(request.url))
        if not world["grant_sees_shared_drives"]:
            return JSONResponse(
                {"error": {"code": 403, "message": "Insufficient Permission",
                           "errors": [{"reason": "insufficientPermissions"}],
                           "status": "PERMISSION_DENIED"}}, status_code=403)
        return JSONResponse({"drives": world["drives"][:pageSize]})

    @app.get("/drive/v3/files/{file_id}")
    async def one_file(file_id: str, request: Request, alt: str = ""):
        seen["api"].append(str(request.url))
        found = file_named(file_id)
        if found is None:
            return JSONResponse({"error": {"message": "File not found: " + file_id}},
                                status_code=404)
        if alt == "media":
            # A file seeded or uploaded with bytes that are not text (a PDF, a Word file)
            # comes back as those very bytes (Files in Drive read, `rouh/drive_files.py`).
            held = world.setdefault("blobs", {}).get(file_id)
            if held is not None:
                return Response(content=held, media_type=found.get("mimeType") or "application/octet-stream")
            return PlainTextResponse(found.get("content", ""))
        return JSONResponse(found)

    # A file of any kind with its own bytes, seeded by a test:
    # POST /_file {"id"?, "name", "mimeType", "base64", "parents"?}.
    @app.post("/_file")
    async def seed_file(request: Request):
        import base64

        got = await request.json()
        data = base64.b64decode(str(got.get("base64") or ""))
        made = _a_file(str(got.get("id") or made_up("file")), str(got.get("name") or "file"),
                       str(got.get("mimeType") or "application/octet-stream"),
                       list(got.get("parents") or ["root"]))
        made.update(_what_arrived(data))
        made["size"] = str(len(data))
        world["files"] = [f for f in world["files"] if f["id"] != made["id"]] + [made]
        world.setdefault("blobs", {})[made["id"]] = data
        return JSONResponse(made)

    # Drive's files.copy (A copy made when asked, `rouh/drive_copy.py`): the file again under a
    # new id, a Google Doc's or a deck's own content copied with it, so the copy can be changed.
    @app.post("/drive/v3/files/{file_id}/copy")
    async def copy_file(file_id: str, request: Request):
        import copy as copying

        seen["api"].append(str(request.url))
        found = file_named(file_id)
        if found is None or found.get("trashed"):
            return JSONResponse({"error": {"message": "File not found: " + file_id}}, status_code=404)
        body = await request.json()
        kind = "doc" if found.get("mimeType") == "application/vnd.google-apps.document" else "file"
        made = copying.deepcopy(found)
        made["id"] = made_up(kind)
        made["name"] = str(body.get("name") or ("Copy of " + str(found.get("name") or "")))
        made["parents"] = list(body.get("parents") or found.get("parents") or ["root"])
        made["permissions"] = [_owner_permission()]
        link = str(found.get("webViewLink") or "")
        made["webViewLink"] = link.replace(file_id, made["id"]) if file_id in link else \
            "https://drive.example.test/" + made["id"]
        world["files"].append(made)
        if file_id in world["documents"]:
            document = copying.deepcopy(world["documents"][file_id])
            document["documentId"] = made["id"]
            document["title"] = made["name"]
            world["documents"][made["id"]] = document
        if file_id in world.get("decks", {}):
            deck = copying.deepcopy(world["decks"][file_id])
            deck["id"], deck["name"] = made["id"], made["name"]
            world["decks"][made["id"]] = deck
        if file_id in world.get("blobs", {}):
            world["blobs"][made["id"]] = world["blobs"][file_id]
        note("file copied", {"from": file_id, "id": made["id"], "name": made["name"],
                             "parents": made["parents"]})
        return JSONResponse(made)

    @app.get("/drive/v3/files/{file_id}/export")
    async def export_file(file_id: str, mimeType: str = "text/plain"):
        document = world["documents"].get(file_id)
        if document is not None:
            return PlainTextResponse(_document_text(document))
        found = file_named(file_id)
        if found is not None and "content" in found:
            # A sheet, exported as the comma-separated text it holds.
            return PlainTextResponse(found["content"])
        return JSONResponse({"error": {"message": "File not found: " + file_id}},
                            status_code=404)

    # --- A document's saved versions and comments (`Drive.revisions`, `Drive.comments`) ---
    # Seeded by a test with POST /_doc_history {"file", "revisions": [{id, modifiedTime,
    # lastModifyingUser, text}], "comments": [...]}; each version's words come back from its
    # export link, as Drive's own exportLinks do.

    @app.post("/_doc_history")
    async def doc_history(request: Request):
        got = await request.json()
        file_id = str(got.get("file") or "")
        world.setdefault("revisions", {})[file_id] = list(got.get("revisions") or [])
        world.setdefault("comments", {})[file_id] = list(got.get("comments") or [])
        return JSONResponse({"ok": True})

    # Who last changed a file and when (`Drive.last_change`), seeded by a test with
    # POST /_file_meta {"file", "modifiedTime", "lastModifyingUser": {displayName, emailAddress}}.
    @app.post("/_file_meta")
    async def file_meta(request: Request):
        got = await request.json()
        found = file_named(str(got.get("file") or ""))
        if found is None:
            return JSONResponse({"error": {"message": "File not found"}}, status_code=404)
        for key in ("modifiedTime", "lastModifyingUser"):
            if key in got:
                found[key] = got[key]
        return JSONResponse({"ok": True})

    @app.get("/drive/v3/files/{file_id}/revisions")
    async def revisions(file_id: str, request: Request):
        seen["api"].append(str(request.url))
        if file_named(file_id) is None:
            return JSONResponse({"error": {"message": "File not found: " + file_id}},
                                status_code=404)
        base = str(request.base_url).rstrip("/")
        out = [{k: v for k, v in one.items() if k != "text"}
               | {"exportLinks": {"text/plain": f"{base}/_revision/{file_id}/{one['id']}"}}
               for one in world.get("revisions", {}).get(file_id, [])]
        return JSONResponse({"revisions": out})

    @app.get("/_revision/{file_id}/{revision_id}")
    async def revision_text(file_id: str, revision_id: str):
        for one in world.get("revisions", {}).get(file_id, []):
            if str(one.get("id")) == revision_id:
                return PlainTextResponse(one.get("text") or "")
        return JSONResponse({"error": {"message": "Revision not found"}}, status_code=404)

    @app.get("/drive/v3/files/{file_id}/comments")
    async def comments(file_id: str, request: Request):
        seen["api"].append(str(request.url))
        return JSONResponse({"comments": world.get("comments", {}).get(file_id, [])})

    # A new comment on a file (`Drive.add_comment`), kept with the file's comments as Drive
    # keeps it, and in `seen["comments_made"]` for a test to read back from /_seen.
    @app.post("/drive/v3/files/{file_id}/comments")
    async def add_comment(file_id: str, request: Request):
        seen["api"].append(str(request.url))
        if file_named(file_id) is None:
            return JSONResponse({"error": {"message": "File not found: " + file_id}},
                                status_code=404)
        got = await request.json()
        held = world.setdefault("comments", {}).setdefault(file_id, [])
        made = {"id": f"made-{len(held) + 1}",
                "author": {"displayName": "Rouh", "emailAddress": "rouh@example.test"},
                "content": got.get("content") or "", "createdTime": "2026-10-26T08:00:00Z",
                "resolved": False, "replies": []}
        held.append(made)
        seen.setdefault("comments_made", []).append({"file": file_id, "content": made["content"]})
        return JSONResponse(made)

    @app.get("/drive/v3/files/{file_id}/comments/{comment_id}")
    async def one_comment(file_id: str, comment_id: str, request: Request):
        seen["api"].append(str(request.url))
        for one in world.get("comments", {}).get(file_id, []):
            if str(one.get("id")) == comment_id:
                return JSONResponse(one)
        return JSONResponse({"error": {"message": "Comment not found: " + comment_id}},
                            status_code=404)

    # A reply to a comment (`Drive.reply_to_comment`), kept on the comment as Drive keeps it,
    # and in `seen["replies"]` for a test to read back from /_seen.
    @app.post("/drive/v3/files/{file_id}/comments/{comment_id}/replies")
    async def reply_to_comment(file_id: str, comment_id: str, request: Request):
        seen["api"].append(str(request.url))
        got = await request.json()
        for one in world.get("comments", {}).get(file_id, []):
            if str(one.get("id")) == comment_id:
                made = {"id": f"reply-{len(one.get('replies') or []) + 1}",
                        "author": {"displayName": "Rouh", "emailAddress": "rouh@example.test"},
                        "content": got.get("content") or "", "createdTime": "2026-10-25T08:00:00Z"}
                one.setdefault("replies", []).append(made)
                if got.get("action") == "resolve":
                    one["resolved"] = True
                seen.setdefault("replies", []).append(
                    {"file": file_id, "comment": comment_id, "content": made["content"],
                     "action": got.get("action") or ""})
                return JSONResponse(made)
        return JSONResponse({"error": {"message": "Comment not found: " + comment_id}},
                            status_code=404)

    @app.patch("/drive/v3/files/{file_id}")
    async def change_file(file_id: str, request: Request,
                          addParents: str = "", removeParents: str = ""):
        found = file_named(file_id)
        if found is None:
            return JSONResponse({"error": {"message": "File not found: " + file_id}},
                                status_code=404)
        try:
            body = await request.json()
        except Exception:
            body = {}
        if body.get("name"):
            found["name"] = body["name"]
            note("file renamed", {"id": file_id, "name": found["name"]})
        if body.get("trashed"):
            found["trashed"] = True
            note("file binned", {"id": file_id, "name": found["name"]})
        if addParents:
            found["parents"] = [one for one in found.get("parents", [])
                                if one not in removeParents.split(",")]
            found["parents"].append(addParents)
            note("file moved", {"id": file_id, "into": addParents})
        return JSONResponse(found)

    # --- who can see it: Drive's permissions resource ------------------------

    @app.post("/_drive_rules")
    async def drive_rules(request: Request):
        """`{"create": false}` stands an organisation that does not let this account
        make shared drives in front of Rouh; `{"outside": false}` one that keeps
        everybody outside example.com out of its shared drives."""
        body = await request.json()
        for key in ("create", "outside"):
            if key in body:
                world["drive_rules"][key] = bool(body[key])
        return JSONResponse(world["drive_rules"])

    @app.post("/drive/v3/drives")
    async def make_shared_drive(request: Request, requestId: str = ""):
        """A new shared drive, its maker its first Manager. One per `requestId`,
        as Drive keeps it: the same one again is refused as a duplicate."""
        seen["api"].append(str(request.url))
        body = await request.json()
        if not requestId:
            return _refused("Required parameter: requestId", 400, "required")
        if any(one.get("request_id") == requestId for one in world["drives"]):
            return _refused("A shared drive with this requestId already exists.", 409,
                            "duplicate")
        if not world["drive_rules"]["create"]:
            return _refused("The user does not have sufficient permissions for this file.",
                            403, "insufficientFilePermissions")
        made = {"id": made_up("0A-drive"), "name": str(body.get("name") or "Untitled"),
                "request_id": requestId}
        world["drives"].append(made)
        drive_named(made["id"])
        note("shared drive made", {"id": made["id"], "name": made["name"]})
        return JSONResponse({"kind": "drive#drive", "id": made["id"], "name": made["name"]})

    @app.get("/drive/v3/drives/{drive_id}")
    async def one_shared_drive(drive_id: str, request: Request):
        seen["api"].append(str(request.url))
        found = drive_named(drive_id)
        if found is None:
            return _refused("Shared drive not found: " + drive_id, 404, "notFound")
        return JSONResponse({"id": found["id"], "name": found["name"]})

    @app.patch("/drive/v3/files/{file_id}/permissions/{permission_id}")
    async def change_permission(file_id: str, permission_id: str, request: Request):
        found = holding_permissions(file_id)
        held = next((one for one in (found or {}).get("permissions") or []
                     if one.get("id") == permission_id), None)
        if held is None:
            return _refused("Permission not found: " + permission_id, 404, "notFound")
        body = await request.json()
        was = held.get("role")
        held["role"] = body.get("role") or was
        note("permission changed", {"id": file_id, "email": held.get("emailAddress", ""),
                                    "role": held["role"], "was": was})
        return JSONResponse(held)

    @app.get("/drive/v3/files/{file_id}/permissions")
    async def who_can_see(file_id: str, request: Request):
        seen["api"].append(str(request.url))
        found = holding_permissions(file_id)
        if found is None:
            return JSONResponse({"error": {"message": "File not found: " + file_id}},
                                status_code=404)
        return JSONResponse({"permissions": list(found.get("permissions") or [])})

    @app.post("/drive/v3/files/{file_id}/permissions")
    async def share_file(file_id: str, request: Request,
                         sendNotificationEmail: str = "true", emailMessage: str = ""):
        found = holding_permissions(file_id)
        if found is None:
            return JSONResponse({"error": {"message": "File not found: " + file_id}},
                                status_code=404)
        body = await request.json()
        address = str(body.get("emailAddress") or "")
        if (file_id.startswith("0A-drive") or found in world["drives"]) and address and \
                not address.lower().endswith("@example.com") and \
                not world["drive_rules"]["outside"]:
            note("shared drive member refused", {"id": file_id, "email": address})
            return _refused(
                "Bad Request. User message: \"This shared drive does not allow people "
                "outside of Example Co to be added.\"", 403,
                "teamDriveDomainUsersOnlyRestriction")
        made = {"id": made_up("perm"), "type": body.get("type") or "user",
                "role": body.get("role") or "reader"}
        if body.get("emailAddress"):
            made["emailAddress"] = body["emailAddress"]
        found.setdefault("permissions", []).append(made)
        note("shared drive member added" if found in world["drives"] else "file shared",
             {"id": file_id, "name": found.get("name", ""),
                             "type": made["type"], "role": made["role"],
                             "email": made.get("emailAddress", ""),
                             "notified": sendNotificationEmail == "true",
                             "message": emailMessage})
        return JSONResponse(made)

    @app.delete("/drive/v3/files/{file_id}/permissions/{permission_id}")
    async def unshare_file(file_id: str, permission_id: str):
        found = file_named(file_id)
        if found is None:
            return JSONResponse({"error": {"message": "File not found: " + file_id}},
                                status_code=404)
        before = list(found.get("permissions") or [])
        found["permissions"] = [one for one in before if one.get("id") != permission_id]
        if len(found["permissions"]) == len(before):
            return JSONResponse({"error": {"message": "Permission not found: "
                                                      + permission_id}}, status_code=404)
        note("file unshared", {"id": file_id, "name": found.get("name", ""),
                               "permission": permission_id})
        # Drive answers a delete with no content at all.
        return Response(status_code=204)

    @app.post("/drive/v3/files")
    async def make_file(request: Request):
        """A file with no bytes: which in Drive is exactly what a folder is."""
        body = await request.json()
        made = _a_file(made_up("folder" if body.get("mimeType") == FOLDER_TYPE else "file"),
                       body.get("name") or "",
                       body.get("mimeType") or "application/octet-stream",
                       list(body.get("parents") or ["root"]))
        world["files"].append(made)
        note("folder made" if made["mimeType"] == FOLDER_TYPE else "file made",
             {"id": made["id"], "name": made["name"], "parents": made["parents"]})
        return JSONResponse(made)

    @app.post("/upload/drive/v3/files")
    async def upload(request: Request, uploadType: str = "multipart"):
        """A new file's bytes. Multipart while it is small, resumable above that.

        Resumable is two requests, the way Drive really does it: this one
        agrees to the upload and answers with a `Location` and no body at all,
        and the bytes arrive at that address afterwards.
        """
        if uploadType == "resumable":
            metadata = await request.json()
            session = made_up("session")
            world["sessions"][session] = dict(metadata)
            return Response(status_code=200, headers={
                "Location": str(request.url.replace(
                    path="/upload/drive/v3/sessions/" + session, query=""))})
        metadata, data, media_type = _read_multipart(await request.body())
        made = _kept(metadata, data, media_type)
        return JSONResponse(made)

    @app.put("/upload/drive/v3/sessions/{session}")
    async def finish_upload(session: str, request: Request):
        """The bytes of a resumable upload, at the address Drive gave for them."""
        metadata = world["sessions"].pop(session, None)
        if metadata is None:
            return JSONResponse({"error": {"message": "Upload session not found."}},
                                status_code=404)
        data = await request.body()
        media_type = request.headers.get("content-type", "application/octet-stream")
        if "file_id" in metadata:
            return JSONResponse(_replaced(metadata.pop("file_id"), metadata, data,
                                          media_type))
        return JSONResponse(_kept(metadata, data, media_type))

    def _kept(metadata: dict, data: bytes, media_type: str) -> dict:
        """One uploaded file, remembered by what really arrived."""
        made = _a_file(made_up("file"), metadata.get("name") or "",
                       metadata.get("mimeType") or media_type,
                       list(metadata.get("parents") or ["root"]))
        made.update(_what_arrived(data))
        world["files"].append(made)
        if not made["content"]:
            world.setdefault("blobs", {})[made["id"]] = data
        note("file written", {"id": made["id"], "name": made["name"],
                              "content": made["content"], "parents": made["parents"],
                              "mimeType": made["mimeType"], "size": made["size"],
                              "sha256": made["sha256"]})
        return made

    def _replaced(file_id: str, metadata: dict, data: bytes, media_type: str) -> dict:
        found = file_named(file_id)
        if found is None:
            return {"error": {"message": "File not found: " + file_id}}
        if metadata.get("name"):
            found["name"] = metadata["name"]
        found.update(_what_arrived(data))
        note("file replaced", {"id": file_id, "name": found["name"],
                               "content": found["content"], "size": found["size"],
                               "sha256": found["sha256"]})
        return found

    @app.patch("/upload/drive/v3/files/{file_id}")
    async def overwrite(file_id: str, request: Request, uploadType: str = "multipart"):
        found = file_named(file_id)
        if found is None:
            return JSONResponse({"error": {"message": "File not found: " + file_id}},
                                status_code=404)
        if uploadType == "resumable":
            metadata = await request.json()
            session = made_up("session")
            world["sessions"][session] = dict(metadata, file_id=file_id)
            return Response(status_code=200, headers={
                "Location": str(request.url.replace(
                    path="/upload/drive/v3/sessions/" + session, query=""))})
        metadata, data, media_type = _read_multipart(await request.body())
        return JSONResponse(_replaced(file_id, metadata, data, media_type))
