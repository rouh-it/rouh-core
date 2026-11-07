"""Drive: finding, reading, writing, uploading and sharing files, and shared
drives and their members.
"""
from __future__ import annotations

import asyncio
import json
import mimetypes
import os
import urllib.parse
import uuid
from typing import TYPE_CHECKING

from ..google_oauth import DRIVE_SCOPE, SHARED_DRIVES_NEED, SHARED_DRIVE_SCOPES
from ..tenancy import Identity
from .common import CannotDoThat, GoogleSaidNo, MAX_FILES, SeveralOfThose, UPLOAD_SECONDS

if TYPE_CHECKING:
    from .clients import GoogleClients


#: What Drive calls a folder, and what a Google Doc is. Both are needed by name
#: often enough to be worth naming here rather than inline.
FOLDER_TYPE = "application/vnd.google-apps.folder"
DOC_TYPE = "application/vnd.google-apps.document"

#: The fields asked for whenever one file is looked at. Naming them keeps the
#: answer small and keeps what this returns stable when Drive adds more.
FILE_FIELDS = "id,name,mimeType,modifiedTime,webViewLink,parents,trashed,size"

#: The fields behind a row of a search or a folder listing: what a person reads
#: off the screen, and the id the next call takes.
LISTING_FIELDS = ("files(id,name,mimeType,modifiedTime,webViewLink,"
                  "owners(displayName,emailAddress))")

#: A Google Doc, Sheet or Slides has no bytes of its own, so reading one means
#: asking Drive to export it. Plain text for a document; comma-separated for a
#: sheet, which is the one form both a person and a model can read.
EXPORT_AS = {
    DOC_TYPE: "text/plain",
    "application/vnd.google-apps.spreadsheet": "text/csv",
    "application/vnd.google-apps.presentation": "text/plain",
}

#: The most of a file that is read into a spoken turn. A whole book of a
#: document is not an answer, and it is not something anybody wants read out.
MAX_FILE_CHARS = 200_000

#: The most Drive will take as one `multipart/related` body. Above it, a file
#: goes up as a resumable session instead: Drive says where to send the bytes
#: and they go in a request of their own. Google's own number, not ours.
MULTIPART_LIMIT = 5 * 1024 * 1024

#: The most of this machine's disk one call may put into Drive: one file, and
#: a whole folder of them. A voice turn should not be able to start an hour of
#: uploading by accident, and a cap with a number in it is something a person
#: can be told.
MAX_UPLOAD_BYTES = 64 * 1024 * 1024
MAX_TREE_FILES = 200
MAX_TREE_BYTES = 256 * 1024 * 1024

#: Drive's own name for the top of My Drive. It is a real folder id as far as
#: every query is concerned, so "what is in my Drive" is the same request as
#: "what is in this folder" with this in it.
MY_DRIVE_ROOT = "root"

#: Listing a folder is not a search. The person asked what is in one place, so
#: the whole of a real folder has to be able to fit, which is why these are
#: higher than `MAX_FILES`: that caps a search, where twenty five best matches
#: is an answer, and a folder with forty things in it that reports thirty is
#: wrong rather than shortened.
FOLDER_LISTED = 50
MAX_FOLDER_LISTED = 200

#: The most shared drives one call asks for. Google's own ceiling on
#: `drives.list` is 100 and it coerces anything above it, so this is Google's
#: number rather than ours.
MAX_SHARED_DRIVES = 100


class Drive:
    """The connected Drive: finding files, reading them, and writing them back."""

    def __init__(self, clients: GoogleClients, who: Identity) -> None:
        self._clients = clients
        self._who = who

    def _url(self, path: str) -> str:
        return self._clients.base("drive") + "/drive/v3" + path

    def _upload_url(self, path: str) -> str:
        return self._clients.base("drive") + "/upload/drive/v3" + path

    #: On every call, so a file in a shared drive is found, read and written
    #: too - which is where an organisation's real documents live.
    #: `supportsAllDrives` is the one Drive refuses a write without;
    #: `includeItemsFromAllDrives` is the one a listing returns nothing from a
    #: shared drive without. Both are on everything that takes them.
    SHARED = {"supportsAllDrives": "true", "includeItemsFromAllDrives": "true"}

    @staticmethod
    def _within(drive_id: str) -> dict:
        """The two parameters that point a listing at one shared drive.

        Drive's default is `corpora=user`, which is My Drive and what has been
        shared with the person and nothing else. `corpora=drive` with the
        drive's own id is the only way to ask a shared drive itself, and Drive
        refuses the first without the second.
        """
        if not drive_id:
            return {}
        return {"corpora": "drive", "driveId": drive_id}

    def _needs_for(self, drive_id: str) -> dict:
        """What a call touching a shared drive has to be allowed to do.

        Nothing extra for My Drive: that is the connection Rouh has always
        had. A shared drive is the one Google will not show to a `drive.file`
        grant at all, so the refusal happens here, before the request, with a
        sentence about pressing Connect rather than a 403 in a spoken turn.
        """
        if not drive_id:
            return {}
        return {"needs_scope": SHARED_DRIVE_SCOPES, "without_it": SHARED_DRIVES_NEED}

    async def search(self, text: str, limit: int = 10, *, only_type: str = "",
                     drive_id: str = "") -> list[dict]:
        """Files whose name or contents match, newest change first.

        The apostrophe in a name like "Alex's plan" ends Drive's own quoting
        if it is not doubled, and the query is then a syntax error rather than
        a search. That is the only escaping Drive's language needs.

        `drive_id` narrows the whole search to one shared drive. Without it the
        search is what it has always been: My Drive and everything shared with
        the person.
        """
        want = max(1, min(int(limit or 10), MAX_FILES))
        term = _drive_quote(text)
        if term:
            clause = f"(name contains '{term}' or fullText contains '{term}') and trashed = false"
        else:
            clause = "trashed = false"
        if only_type:
            clause += f" and mimeType = '{only_type}'"
        body = await self._clients.call(
            self._who, "GET", self._url("/files"),
            params={
                "q": clause,
                "pageSize": want,
                "orderBy": "modifiedTime desc",
                "fields": LISTING_FIELDS,
                **self.SHARED,
                **self._within(drive_id),
            },
            **self._needs_for(drive_id),
        )
        return [_a_listed_file(one) for one in (body.get("files") or [])]

    async def children(self, folder_id: str = "", *, limit: int = FOLDER_LISTED,
                       folders_only: bool = False, drive_id: str = "") -> list[dict]:
        """What is directly inside one folder. A listing, not a search.

        This is the question `search` cannot answer and never could: "what is
        in the root of my Drive" has no text to match, and matching nothing
        returns the whole Drive in whatever order it comes. Drive's own answer
        is the `in parents` operator, so this asks for exactly the children of
        one folder and nothing deeper.

        `folder_id` left out is the top of My Drive, which is what a person
        means by "my Drive" when they name no folder. Inside a shared drive the
        top is the drive's own id, because to Drive a shared drive **is** its
        root folder.

        Folders first, then files, each newest change first. Drive's own
        `orderBy=folder,modifiedTime desc` asks for that ordering, and it is
        sorted again here rather than trusted: the ordering is what makes the
        answer readable out loud, and a page of files with one folder buried in
        the middle of it is the failure this is guarding against.
        """
        where = folder_id or drive_id or MY_DRIVE_ROOT
        want = max(1, min(int(limit or FOLDER_LISTED), MAX_FOLDER_LISTED))
        clause = f"'{_drive_quote(where)}' in parents and trashed = false"
        if folders_only:
            clause += f" and mimeType = '{FOLDER_TYPE}'"
        body = await self._clients.call(
            self._who, "GET", self._url("/files"),
            params={
                "q": clause,
                "pageSize": want,
                "orderBy": "folder,modifiedTime desc",
                "fields": LISTING_FIELDS,
                **self.SHARED,
                **self._within(drive_id),
            },
            **self._needs_for(drive_id),
        )
        found = [_a_listed_file(one) for one in (body.get("files") or [])]
        # Two passes rather than one clever key. Python's sort is stable, so
        # the second one keeps the order the first put things in within each
        # group: newest change first inside the folders, and again inside the
        # files.
        found.sort(key=lambda one: one["modified"], reverse=True)
        found.sort(key=lambda one: one["mime_type"] != FOLDER_TYPE)
        return found[:want]

    async def shared_drives(self, limit: int = MAX_SHARED_DRIVES) -> list[dict]:
        """Every shared drive this account can see, by name and by id.

        Its own endpoint rather than a query over files: a shared drive is not
        a folder in anybody's Drive, so nothing in `files.list` has ever
        mentioned one. Google will only answer this for a connection granted
        `drive` or `drive.readonly`, which is why the refusal is checked for
        before the request goes out.
        """
        want = max(1, min(int(limit or MAX_SHARED_DRIVES), MAX_SHARED_DRIVES))
        body = await self._clients.call(
            self._who, "GET", self._url("/drives"),
            params={"pageSize": want, "fields": "drives(id,name)"},
            needs_scope=SHARED_DRIVE_SCOPES, without_it=SHARED_DRIVES_NEED)
        return [{"id": one.get("id") or "", "name": one.get("name") or ""}
                for one in (body.get("drives") or []) if one.get("id")]

    async def shared_drive_id(self, name_or_id: str) -> str:
        """One shared drive, named the way a person names it or given as an id.

        The same three looks `folder_id` does, and for the same reason: a name
        that fits two shared drives is a choice the person makes rather than
        one this guesses at. Every shared drive the account can see fits in one
        answer, so this matches against that list rather than asking Google to
        match for it.
        """
        wanted = (name_or_id or "").strip()
        if not wanted:
            return ""
        every = await self.shared_drives()
        exact = [one for one in every if one["name"].lower() == wanted.lower()]
        if len(exact) == 1:
            return exact[0]["id"]
        if exact:
            raise SeveralOfThose(
                _pick_one(wanted, exact, "shared drive", "that this account can see"))
        close = [one for one in every if wanted.lower() in one["name"].lower()]
        if len(close) == 1:
            return close[0]["id"]
        if close:
            raise SeveralOfThose(
                _pick_one(wanted, close, "shared drive", "that this account can see"))
        by_id = [one for one in every if one["id"] == wanted]
        if by_id:
            return by_id[0]["id"]
        raise GoogleSaidNo(
            f"There is no shared drive called {wanted!r} that this account can see, "
            f"and it is not the id of one either. list_shared_drives says which "
            f"there are.")

    async def metadata(self, file_id: str) -> dict:
        found = await self._clients.call(
            self._who, "GET", self._url("/files/" + urllib.parse.quote(file_id)),
            params={"fields": FILE_FIELDS, **self.SHARED})
        return {
            "id": found.get("id") or file_id,
            "name": found.get("name") or "",
            "type": _kind(found.get("mimeType") or ""),
            "mime_type": found.get("mimeType") or "",
            "modified": found.get("modifiedTime") or "",
            "link": found.get("webViewLink") or "",
            "parents": list(found.get("parents") or []),
            "trashed": bool(found.get("trashed")),
            "size": int(found.get("size") or 0),
        }

    async def folders(self, clause: str, *, drive_id: str = "") -> list[dict]:
        """Folders matching one clause of Drive's query language, never trashed."""
        found = await self._clients.call(
            self._who, "GET", self._url("/files"),
            params={"q": f"mimeType = '{FOLDER_TYPE}' and {clause} and trashed = false",
                    "pageSize": MAX_FILES,
                    "fields": "files(id,name,webViewLink,modifiedTime)",
                    **self.SHARED, **self._within(drive_id)},
            **self._needs_for(drive_id))
        return [{"id": one.get("id") or "", "name": one.get("name") or "",
                 "link": one.get("webViewLink") or "",
                 "modified": one.get("modifiedTime") or ""}
                for one in (found.get("files") or []) if one.get("id")]

    async def folders_named(self, name: str, *, drive_id: str = "") -> list[dict]:
        """Every folder with exactly this name. More than one is the point."""
        return await self.folders(f"name = '{_drive_quote(name)}'", drive_id=drive_id)

    async def folder_id(self, name_or_id: str, *, drive_id: str = "") -> str:
        """A folder, named the way a person names it or given as an id.

        Empty for "wherever it goes by default", which is what Drive does with
        no parent: the root of My Drive.

        Three looks, in order, and the reason there are three is that a folder
        used to be "found" by handing its name to Drive as an id, which came
        back as "File not found" while the folder was sitting there:

        1. the exact name, which is what a person says;
        2. the name as part of a longer one, so "Plans" finds "2026 Plans";
        3. the value taken at its word as an id, checked with one lookup so a
           wrong one is a sentence about a folder rather than Google's own
           wording about a file.

        A name that fits more than one folder raises `SeveralOfThose` with all
        of them in it. Choosing between two folders called Plans is the
        person's to make, and making it quietly is how a file is lost.

        `drive_id` looks inside one shared drive instead of My Drive, so a
        folder called Plans on the Finance drive is found there rather than
        being confused with the one at home.
        """
        wanted = (name_or_id or "").strip()
        if not wanted:
            return ""
        exact = await self.folders_named(wanted, drive_id=drive_id)
        if len(exact) == 1:
            return exact[0]["id"]
        if exact:
            raise SeveralOfThose(_pick_one(wanted, exact))
        close = await self.folders(f"name contains '{_drive_quote(wanted)}'",
                                   drive_id=drive_id)
        if len(close) == 1:
            return close[0]["id"]
        if close:
            raise SeveralOfThose(_pick_one(wanted, close))
        try:
            about = await self.metadata(wanted)
        except GoogleSaidNo:
            raise GoogleSaidNo(
                f"There is no folder called {wanted!r} in that Drive, and it is not the "
                f"id of one either. Make it with create_drive_folder, or find the right "
                f"name with search_drive.") from None
        if about["mime_type"] != FOLDER_TYPE:
            raise GoogleSaidNo(
                f"{about['name']!r} is a {about['type']}, not a folder, so nothing can "
                f"be put inside it.")
        return about["id"]

    async def create_folder(self, name: str, parent_id: str = "") -> dict:
        """A real folder in Drive. A folder is a file whose type says so."""
        wanted = (name or "").strip()
        if not wanted:
            raise GoogleSaidNo("A folder needs a name.")
        metadata: dict = {"name": wanted, "mimeType": FOLDER_TYPE}
        if parent_id:
            metadata["parents"] = [parent_id]
        made = await self._clients.call(
            self._who, "POST", self._url("/files"),
            params={"fields": FILE_FIELDS, **self.SHARED}, json_body=metadata)
        return {"id": made.get("id") or "", "name": made.get("name") or wanted,
                "link": made.get("webViewLink") or "", "folder_id": parent_id}

    async def read(self, file_id: str, *, files: bool = False) -> dict:
        """The text of a file: exported for a Google type, downloaded otherwise.

        `files`, while Files in Drive read is on (`rouh/drive_files.py`), reads a PDF, Word,
        Excel or PowerPoint file's words out of its bytes too, and says which it was as
        `extracted`."""
        from .. import drive_files

        about = await self.metadata(file_id)
        mime = about["mime_type"]
        if files and mime not in EXPORT_AS and drive_files.readable(about):
            text = await drive_files.text_of(lambda: self.download(file_id), about)
            return {**about, "text": text[:MAX_FILE_CHARS],
                    "extracted": drive_files.kind_of(about)}
        if mime in EXPORT_AS:
            text = await self._clients.call(
                self._who, "GET",
                self._url("/files/" + urllib.parse.quote(file_id) + "/export"),
                params={"mimeType": EXPORT_AS[mime]}, want_text=True)
        elif mime.startswith("text/") or mime in ("application/json", "text/csv"):
            text = await self._clients.call(
                self._who, "GET", self._url("/files/" + urllib.parse.quote(file_id)),
                params={"alt": "media", **self.SHARED}, want_text=True)
        else:
            # Rouh's own answer, not Google's: Drive said perfectly well what
            # the file is, and it is not something with words to read out.
            raise CannotDoThat(
                f"{about['name']!r} is a {about['type']} and there is no way to read it "
                f"as text.")
        return {**about, "text": (text or "")[:MAX_FILE_CHARS]}

    async def download(self, file_id: str) -> bytes:
        """A file's own bytes, as Drive keeps them (Files in Drive read, `rouh/drive_files.py`)."""
        return await self._clients.call(
            self._who, "GET", self._url("/files/" + urllib.parse.quote(file_id)),
            params={"alt": "media", **self.SHARED}, want_bytes=True, seconds=120)

    async def write(self, name: str, content: str, *, folder_id: str = "",
                    file_id: str = "", mime_type: str = "text/plain") -> dict:
        """Put a file into Drive, or replace the contents of one that is there.

        One multipart body, which is how Drive takes a file and its name in a
        single request. Anything else is two round trips and a window in which
        a file exists with no contents.
        """
        metadata: dict = {}
        if name:
            metadata["name"] = name
        if file_id:
            where = self._upload_url("/files/" + urllib.parse.quote(file_id))
            method = "PATCH"
        else:
            where = self._upload_url("/files")
            method = "POST"
            if folder_id:
                metadata["parents"] = [folder_id]
        body, boundary = _multipart(metadata, content, mime_type)
        answer = await self._clients.call(
            self._who, method, where,
            params={"uploadType": "multipart", "fields": FILE_FIELDS, **self.SHARED},
            content=body, content_type=f"multipart/related; boundary={boundary}")
        return {"id": answer.get("id") or file_id,
                "name": answer.get("name") or name,
                "link": answer.get("webViewLink") or "",
                "replaced": bool(file_id)}

    async def upload(self, name: str, data: bytes, *, folder_id: str = "",
                     file_id: str = "", mime_type: str = "") -> dict:
        """A file's real bytes, from this machine's disk into Drive.

        The difference from `write` is the whole point of it: `write` takes a
        string that has been through the model, so a photograph, a PDF or a
        zip cannot survive the trip. This takes the bytes as they are on disk
        and Drive gets exactly them.

        Two ways up, and which one is used is Drive's rule rather than a
        choice: a `multipart/related` body while the file is small, and a
        resumable session above `MULTIPART_LIMIT`, which is the only way
        anything larger goes in at all.
        """
        kind = mime_type or "application/octet-stream"
        metadata: dict = {}
        if name:
            metadata["name"] = name
        if file_id:
            where, method = self._upload_url("/files/" + urllib.parse.quote(file_id)), "PATCH"
        else:
            where, method = self._upload_url("/files"), "POST"
            if folder_id:
                metadata["parents"] = [folder_id]
        if len(data) > MULTIPART_LIMIT:
            answer = await self._resumable(where, method, metadata, data, kind)
        else:
            body, boundary = _multipart(metadata, data, kind)
            answer = await self._clients.call(
                self._who, method, where,
                params={"uploadType": "multipart", "fields": FILE_FIELDS, **self.SHARED},
                content=body, content_type=f"multipart/related; boundary={boundary}",
                seconds=UPLOAD_SECONDS)
        return {"id": answer.get("id") or file_id,
                "name": answer.get("name") or name,
                "link": answer.get("webViewLink") or "",
                "mime_type": answer.get("mimeType") or kind,
                "bytes": len(data),
                "replaced": bool(file_id)}

    async def import_html(self, name: str, document: str, *, file_id: str = "",
                          folder_id: str = "") -> dict:
        """An HTML document made into a Google Doc, or put into the Google Doc `file_id`.

        Drive does the converting when the media is HTML and the file is a Google Doc: headings,
        lists, tables, bold and links come across as a document's own. Replacing keeps the
        document's id and link (`rouh/page_gdoc.py`)."""
        metadata: dict = {"name": name} if name else {}
        if file_id:
            where = self._upload_url("/files/" + urllib.parse.quote(file_id))
            method = "PATCH"
        else:
            where, method = self._upload_url("/files"), "POST"
            metadata["mimeType"] = "application/vnd.google-apps.document"
            if folder_id:
                metadata["parents"] = [folder_id]
        body, boundary = _multipart(metadata, document, "text/html")
        answer = await self._clients.call(
            self._who, method, where,
            params={"uploadType": "multipart", "fields": FILE_FIELDS, **self.SHARED},
            content=body, content_type=f"multipart/related; boundary={boundary}",
            seconds=UPLOAD_SECONDS)
        return {"id": answer.get("id") or file_id, "name": answer.get("name") or name,
                "link": answer.get("webViewLink") or "", "replaced": bool(file_id)}

    async def _resumable(self, where: str, method: str, metadata: dict,
                         data: bytes, mime_type: str) -> dict:
        """Drive's two-step upload: agree to it, then send the bytes.

        The first request carries only the name and where it goes, and Drive
        answers with a `Location` header - an address that stands for this one
        upload and nothing else. The bytes go there in one request. Splitting
        them into chunks would buy the ability to carry on after a broken
        connection, and cost a state machine; a retry of the whole thing is
        what this does instead, which is right up to the cap it enforces.
        """
        session = await self._clients.call(
            self._who, method, where,
            params={"uploadType": "resumable", "fields": FILE_FIELDS, **self.SHARED},
            json_body=metadata, want_location=True,
            more_headers={"X-Upload-Content-Type": mime_type,
                          "X-Upload-Content-Length": str(len(data))})
        return await self._clients.call(
            self._who, "PUT", session, content=data, content_type=mime_type,
            seconds=UPLOAD_SECONDS)

    async def copy(self, file_id: str, name: str, *, parent: str = "") -> dict:
        """Drive's own copy of a file, everything in it kept (A copy made when asked,
        `rouh/drive_copy.py`): {id, name, type, mime_type, link}."""
        body: dict = {"name": name}
        if parent:
            body["parents"] = [parent]
        made = await self._clients.call(
            self._who, "POST", self._url("/files/" + urllib.parse.quote(file_id) + "/copy"),
            params={"fields": FILE_FIELDS, "supportsAllDrives": "true"}, json_body=body)
        return {"id": made.get("id") or "", "name": made.get("name") or name,
                "type": _kind(made.get("mimeType") or ""), "mime_type": made.get("mimeType") or "",
                "link": made.get("webViewLink") or ""}

    async def rename(self, file_id: str, name: str) -> dict:
        answer = await self._clients.call(
            self._who, "PATCH", self._url("/files/" + urllib.parse.quote(file_id)),
            params={"fields": FILE_FIELDS, **self.SHARED}, json_body={"name": name})
        return {"id": answer.get("id") or file_id, "name": answer.get("name") or name,
                "link": answer.get("webViewLink") or "",
                "type": _kind(answer.get("mimeType") or ""),
                "mime_type": answer.get("mimeType") or ""}

    async def move(self, file_id: str, folder_id: str) -> dict:
        """Into another folder. Drive moves by changing parents, not by copying.

        A folder moves exactly the same way, with everything inside it, because
        to Drive a folder is a file whose type says folder.
        """
        about = await self.metadata(file_id)
        if file_id == folder_id:
            raise GoogleSaidNo(
                f"{about['name'] or file_id!r} cannot be moved into itself.")
        answer = await self._clients.call(
            self._who, "PATCH", self._url("/files/" + urllib.parse.quote(file_id)),
            params={"addParents": folder_id,
                    "removeParents": ",".join(about["parents"]),
                    "fields": FILE_FIELDS, **self.SHARED})
        return {"id": answer.get("id") or file_id, "name": answer.get("name") or about["name"],
                "link": answer.get("webViewLink") or "", "folder_id": folder_id,
                "type": _kind(answer.get("mimeType") or about["mime_type"]),
                "mime_type": answer.get("mimeType") or about["mime_type"]}

    async def trash(self, file_id: str) -> dict:
        """Into the bin. Drive keeps it for thirty days, so this is undoable.

        A folder goes the same way and takes everything inside it with it,
        which is why the tool above says so out loud.
        """
        answer = await self._clients.call(
            self._who, "PATCH", self._url("/files/" + urllib.parse.quote(file_id)),
            params={"fields": FILE_FIELDS, **self.SHARED}, json_body={"trashed": True})
        return {"id": answer.get("id") or file_id, "name": answer.get("name") or "",
                "type": _kind(answer.get("mimeType") or ""),
                "mime_type": answer.get("mimeType") or "", "trashed": True}

    # --- who can see it ------------------------------------------------------
    #
    # Sharing is its own resource in Drive - a file has a list of permissions
    # hanging off it - and every call below needs the whole `drive` scope.
    # `drive.file` and `drive.readonly` can read and write a file and still not
    # touch who it is shared with, so `needs_scope` is on every one of them and
    # the refusal happens before the request rather than as a 403 in the middle
    # of a spoken turn.

    async def permissions(self, file_id: str) -> list[dict]:
        """Who can open this file, and what each of them may do with it."""
        body = await self._clients.call(
            self._who, "GET",
            self._url("/files/" + urllib.parse.quote(file_id) + "/permissions"),
            params={"fields": PERMISSION_FIELDS, "pageSize": 100, **self.SHARED},
            needs_scope=DRIVE_SCOPE)
        return [_a_permission(one) for one in (body.get("permissions") or [])]

    async def revisions(self, file_id: str) -> list[dict]:
        """The saved versions of a file, oldest first: when, who, and where to export each.

        A Google Doc keeps its versions in Drive's revisions, each with its time, who made it
        and an export link per format; only a Google file has export links, and an ordinary
        file's revisions are its uploads. Read only (`rouh/doc_changes.py`).
        """
        out: list[dict] = []
        page = ""
        for _ in range(20):
            params = {"fields": "nextPageToken,revisions(id,modifiedTime,"
                                "lastModifyingUser(displayName,emailAddress),exportLinks)",
                      "pageSize": 200}
            if page:
                params["pageToken"] = page
            body = await self._clients.call(
                self._who, "GET",
                self._url("/files/" + urllib.parse.quote(file_id) + "/revisions"), params=params)
            for one in body.get("revisions") or []:
                user = one.get("lastModifyingUser") or {}
                out.append({"id": str(one.get("id") or ""), "at": one.get("modifiedTime") or "",
                            "who": user.get("displayName") or user.get("emailAddress") or "",
                            "email": user.get("emailAddress") or "",
                            "export": (one.get("exportLinks") or {}).get("text/plain") or ""})
            page = body.get("nextPageToken") or ""
            if not page:
                break
        return out

    async def revision_text(self, export_link: str) -> str:
        """The words of one saved version, from the export link Drive gave for it."""
        text = await self._clients.call(self._who, "GET", export_link, want_text=True)
        return (text or "")[:MAX_FILE_CHARS]

    async def comments(self, file_id: str) -> list[dict]:
        """The comments on a file, with the words they are on, their replies and whether resolved."""
        out: list[dict] = []
        page = ""
        for _ in range(10):
            params = {"fields": "nextPageToken,comments(id,author(displayName,emailAddress,me),"
                                "content,createdTime,modifiedTime,resolved,deleted,anchor,"
                                "quotedFileContent(value),replies(author(displayName,me),content,"
                                "createdTime,deleted))", "pageSize": 100}
            if page:
                params["pageToken"] = page
            body = await self._clients.call(
                self._who, "GET",
                self._url("/files/" + urllib.parse.quote(file_id) + "/comments"), params=params)
            for one in body.get("comments") or []:
                if one.get("deleted"):
                    continue
                author = one.get("author") or {}
                out.append({
                    "id": one.get("id") or "",
                    "who": author.get("displayName") or author.get("emailAddress") or "",
                    "me": bool(author.get("me")),
                    "words": one.get("content") or "",
                    "on": ((one.get("quotedFileContent") or {}).get("value") or ""),
                    "at": one.get("createdTime") or "", "changed": one.get("modifiedTime") or "",
                    "resolved": bool(one.get("resolved")),
                    # Where it is pinned, as Google keeps it: in a deck it names the slide's id
                    # (`rouh/decks.py`).
                    "anchor": str(one.get("anchor") or ""),
                    "replies": [{"who": (r.get("author") or {}).get("displayName") or "",
                                 "me": bool((r.get("author") or {}).get("me")),
                                 "words": r.get("content") or "", "at": r.get("createdTime") or ""}
                                for r in one.get("replies") or [] if not r.get("deleted")]})
            page = body.get("nextPageToken") or ""
            if not page:
                break
        return out

    async def last_change(self, file_id: str) -> dict:
        """When a file was last changed and by whom (`rouh/doc_last_changed.py`).

        ``{"at", "who", "email", "me"}``: Drive's own `modifiedTime` and `lastModifyingUser`,
        where `me` is whether that was this Google account itself.
        """
        found = await self._clients.call(
            self._who, "GET", self._url("/files/" + urllib.parse.quote(file_id)),
            params={"fields": "modifiedTime,lastModifyingUser(displayName,emailAddress,me)",
                    "supportsAllDrives": "true"})
        user = found.get("lastModifyingUser") or {}
        return {"at": found.get("modifiedTime") or "", "who": user.get("displayName") or "",
                "email": user.get("emailAddress") or "", "me": bool(user.get("me"))}

    async def add_comment(self, file_id: str, words: str) -> dict:
        """A new comment on a file, from this Google account (`rouh/doc_comment.py`).

        Not anchored to a passage: Drive's API cannot anchor a comment in a Google Doc, so the
        words it is about are written into the comment itself by the caller.
        """
        made = await self._clients.call(
            self._who, "POST", self._url("/files/" + urllib.parse.quote(file_id) + "/comments"),
            params={"fields": "id,author(displayName,emailAddress),content,createdTime"},
            json_body={"content": words})
        author = made.get("author") or {}
        return {"id": made.get("id") or "", "words": made.get("content") or "",
                "as": author.get("emailAddress") or author.get("displayName") or ""}

    async def reply_to_comment(self, file_id: str, comment_id: str, words: str, *,
                               resolve: bool = False) -> dict:
        """Answer one comment on a file, and resolve it when asked (`rouh/doc_comments.py`).

        The comment is read first, so a wrong id is said as one rather than answered, and so
        the answer can say whose comment it was and what it was on.
        """
        base = "/files/" + urllib.parse.quote(file_id) + "/comments/" + urllib.parse.quote(comment_id)
        had = await self._clients.call(
            self._who, "GET", self._url(base),
            params={"fields": "id,author(displayName),quotedFileContent(value),resolved,deleted"})
        if had.get("deleted"):
            raise GoogleSaidNo(f"The comment {comment_id} was deleted.")
        body: dict = {"content": words}
        if resolve:
            body["action"] = "resolve"
        made = await self._clients.call(
            self._who, "POST", self._url(base + "/replies"),
            params={"fields": "id,author(displayName,emailAddress),content"}, json_body=body)
        author = made.get("author") or {}
        return {"id": made.get("id") or "", "who": (had.get("author") or {}).get("displayName") or "",
                "on": (had.get("quotedFileContent") or {}).get("value") or "",
                "as": author.get("emailAddress") or author.get("displayName") or ""}

    async def share_with_link(self, file_id: str, role: str = "reader") -> dict:
        """Anyone who has the URL can open it, with no sign-in and no invitation.

        This is the one that cannot be half-done: from here on the link is the
        permission, so whoever it is forwarded to has it too. The tool above
        says that out loud before it calls this.
        """
        role = _a_role(role)
        made = await self._clients.call(
            self._who, "POST",
            self._url("/files/" + urllib.parse.quote(file_id) + "/permissions"),
            params={"fields": PERMISSION_FIELDS_ONE, **self.SHARED},
            json_body={"type": "anyone", "role": role},
            needs_scope=DRIVE_SCOPE)
        about = await self.metadata(file_id)
        return {"id": file_id, "name": about["name"], "link": about["link"],
                "role": role, "permission_id": made.get("id") or ""}

    async def share_with_person(self, file_id: str, email: str, role: str = "reader",
                                *, notify: bool = True, message: str = "") -> dict:
        """Give one named address access, by their Google account.

        `notify` is Google's own invitation mail, sent from the person's own
        account. Off, the access is granted silently and whoever it is has to
        be told some other way - which is what Rouh is usually about to do
        itself, in a message of its own.
        """
        role = _a_role(role)
        address = (email or "").strip()
        if not address or "@" not in address:
            raise GoogleSaidNo(f"{email!r} is not an email address to share with.")
        params = {"fields": PERMISSION_FIELDS_ONE,
                  "sendNotificationEmail": "true" if notify else "false",
                  **self.SHARED}
        if notify and message:
            params["emailMessage"] = message
        made = await self._clients.call(
            self._who, "POST",
            self._url("/files/" + urllib.parse.quote(file_id) + "/permissions"),
            params=params,
            json_body={"type": "user", "role": role, "emailAddress": address},
            needs_scope=DRIVE_SCOPE)
        # No metadata lookup here, unlike `share_with_link`: sharing with five
        # people would be five round trips for the same answer, and the caller
        # that wants the link asks for it once when it is finished.
        return {"id": file_id, "email": address, "role": role,
                "notified": bool(notify), "permission_id": made.get("id") or ""}

    async def stop_link_sharing(self, file_id: str) -> dict:
        """Private again: take away the anyone-with-the-link permission.

        Only that one. The people who were named on the file keep their access,
        because "stop the link working" and "throw everybody off it" are
        different instructions and only one of them was given.
        """
        held = await self.permissions(file_id)
        taken = [one for one in held if one["kind"] == "anyone"]
        for one in taken:
            await self._clients.call(
                self._who, "DELETE",
                self._url("/files/" + urllib.parse.quote(file_id) + "/permissions/"
                          + urllib.parse.quote(one["id"])),
                params=dict(self.SHARED), needs_scope=DRIVE_SCOPE)
        about = await self.metadata(file_id)
        return {"id": file_id, "name": about["name"], "link": about["link"],
                "removed": len(taken)}

    # --- making a shared drive, and who is in it -------------------------------
    #
    # A shared drive's members are permissions on the drive's own id, which is
    # also the id of its root folder, so the same permissions resource as a
    # file's answers for it, with `supportsAllDrives`. What differs is the
    # roles: a shared drive's Manager is Drive's `organizer`, and the other
    # four are `DRIVE_MEMBER_ROLES`. Every one of these needs the whole
    # `drive` scope, which Rouh has always asked for (`google_oauth.SCOPES`).

    async def create_shared_drive(self, name: str) -> dict:
        """Make a shared drive. Whoever this connection is becomes its first Manager.

        Google makes one per `requestId`, so a request that is sent twice -
        a retry after a timeout - makes one drive rather than two. A drive of
        the very same name that this account can already see is not made
        again: two drives called Legal is the mistake worth refusing, and the
        answer says it was already there (`made` is False).
        """
        wanted = " ".join((name or "").split())
        if not wanted:
            raise CannotDoThat("Say what to call the shared drive.")
        if len(wanted) > 100:
            raise CannotDoThat("A shared drive's name is 100 characters at most.")
        every = await self.shared_drives()
        held = [one for one in every if one["name"].lower() == wanted.lower()]
        if len(held) == 1:
            return dict(held[0], made=False)
        if held:
            raise SeveralOfThose(
                _pick_one(wanted, held, "shared drive", "that this account can see"))
        made = await self._clients.call(
            self._who, "POST", self._url("/drives"),
            params={"requestId": uuid.uuid4().hex, "fields": "id,name"},
            json_body={"name": wanted},
            needs_scope=DRIVE_SCOPE, without_it=CANNOT_MAKE_A_SHARED_DRIVE)
        if not made.get("id"):
            raise GoogleSaidNo("Google did not say which drive it made.")
        return {"id": made["id"], "name": made.get("name") or wanted, "made": True}

    async def drive_members(self, drive_id: str) -> list[dict]:
        """Who is in a shared drive, and as what (`_a_permission`, with `role` Drive's own)."""
        await self._settles(drive_id)
        return await self.permissions(drive_id)

    async def _settles(self, drive_id: str) -> None:
        """Wait the moment a just-made shared drive takes to answer for its members.

        Drive can answer "not found" for a second or two after `drives.create`
        has said yes. Three looks, a second apart; after that a refusal is a
        real one and is left to the call that follows.
        """
        for wait in (1.0, 2.0, 0.0):
            try:
                await self._clients.call(
                    self._who, "GET", self._url("/drives/" + urllib.parse.quote(drive_id)),
                    params={"fields": "id"}, needs_scope=DRIVE_SCOPE)
                return
            except GoogleSaidNo as exc:
                if exc.status != 404 or not wait:
                    return
                await asyncio.sleep(wait)

    async def add_drive_member(self, drive_id: str, email: str, role: str = "organizer", *,
                               notify: bool = True, held: list[dict] | None = None) -> dict:
        """Put one person in a shared drive as `role`, or change the role they have.

        Someone already in it at that role is left alone (`did` "already");
        someone in it at another is moved to this one (`did` "changed"),
        because "make Sam a Manager" about somebody who is a Viewer means
        that; anybody else is added (`did` "added"), with Google's own
        invitation mail when `notify`. `held` is the drive's members already
        read, so adding four people reads them once.

        A refusal is raised as `MemberRefused`, with a sentence that says what
        stood in the way - mostly the organisation's own sharing rules, which
        nothing here can or should get round.
        """
        role = drive_role(role)
        address = (email or "").strip()
        if not address or "@" not in address or " " in address:
            raise MemberRefused(f"{email!r} is not an email address.")
        if held is None:
            held = await self.drive_members(drive_id)
        there = next((one for one in held
                      if (one.get("email") or "").lower() == address.lower()), None)
        try:
            if there is not None and there["role"] == role:
                return {"email": address, "role": role, "did": "already",
                        "permission_id": there["id"]}
            if there is not None:
                await self._clients.call(
                    self._who, "PATCH",
                    self._url("/files/" + urllib.parse.quote(drive_id) + "/permissions/"
                              + urllib.parse.quote(there["id"])),
                    params={"fields": PERMISSION_FIELDS_ONE, **self.SHARED},
                    json_body={"role": role}, needs_scope=DRIVE_SCOPE)
                return {"email": address, "role": role, "did": "changed", "was": there["role"],
                        "permission_id": there["id"]}
            made = await self._clients.call(
                self._who, "POST",
                self._url("/files/" + urllib.parse.quote(drive_id) + "/permissions"),
                params={"fields": PERMISSION_FIELDS_ONE,
                        "sendNotificationEmail": "true" if notify else "false", **self.SHARED},
                json_body={"type": "user", "role": role, "emailAddress": address},
                needs_scope=DRIVE_SCOPE)
        except GoogleSaidNo as exc:
            raise MemberRefused(member_refusal(address, exc)) from None
        return {"email": address, "role": role, "did": "added", "notified": bool(notify),
                "permission_id": made.get("id") or ""}


#: What Drive is asked to say back about a permission. `displayName` is only
#: there for a person Google can name; the link permission has none, which is
#: why `_a_permission` falls back to the kind of thing it is.
PERMISSION_FIELDS = ("permissions(id,type,role,emailAddress,displayName,domain,"
                     "allowFileDiscovery)")
PERMISSION_FIELDS_ONE = "id,type,role,emailAddress,displayName,domain"

#: The three things somebody can be allowed to do, and the words for them.
#: Drive has others - owner, organizer - which are read back but never handed
#: out from here, because giving a file away is not a thing to do by voice.
ROLES = ("reader", "commenter", "writer")
ROLE_WORDS = {"reader": "read", "commenter": "comment on", "writer": "edit",
              "owner": "own", "fileOrganizer": "organise", "organizer": "organise"}


#: A shared drive's roles, by the words Google Drive's own screen uses for
#: them, and Drive's name for each. Manager is the one that can add and take
#: people off, change the drive's settings and delete it.
DRIVE_MEMBER_ROLES = {"manager": "organizer", "content manager": "fileOrganizer",
                      "contributor": "writer", "commenter": "commenter", "viewer": "reader"}
DRIVE_ROLE_WORDS = {drive: words for words, drive in DRIVE_MEMBER_ROLES.items()}

#: Said when Google will not make a shared drive for this account. Both
#: reasons it gives are a grant or a rule, never a fault in the request.
CANNOT_MAKE_A_SHARED_DRIVE = (
    "Google would not make a shared drive for this account. Either the Google connection "
    "was not given full Drive access - open Settings and press Connect Google to grant "
    "it - or the organisation does not let this account create shared drives, which a "
    "Google Workspace administrator changes in the Admin console under Apps, Google "
    "Workspace, Drive and Docs, Sharing settings, Shared drive creation. An account that "
    "is not part of a Google Workspace cannot have shared drives at all.")


class MemberRefused(RuntimeError):
    """One person could not be put in a shared drive. The words are said as they are."""


def drive_role(role: str) -> str:
    """Drive's own name for a shared drive role said in any of its words, or a refusal."""
    wanted = " ".join((role or "manager").replace("_", " ").split()).lower()
    if wanted in DRIVE_MEMBER_ROLES:
        return DRIVE_MEMBER_ROLES[wanted]
    if wanted in {one.lower() for one in DRIVE_ROLE_WORDS}:
        return next(one for one in DRIVE_ROLE_WORDS if one.lower() == wanted)
    if wanted in ("admin", "administrator", "owner", "organiser"):
        return "organizer"
    if wanted in ("editor", "edit"):
        return "writer"
    if wanted in ("reader", "read"):
        return "reader"
    raise MemberRefused(f"{role!r} is not a role on a shared drive. It is Manager, Content "
                        "manager, Contributor, Commenter or Viewer.")


#: Google's reasons for keeping somebody out of a shared drive that are the
#: organisation's own sharing rules rather than anything wrong with the ask.
OUTSIDE_NOT_ALLOWED = {"teamDriveDomainUsersOnlyRestriction", "domainUsersOnlyRestriction",
                       "shareOutNotPermitted", "shareInNotPermitted",
                       "teamDriveTeamMembersOnlyRestriction", "publishOutNotPermitted",
                       "sharingOutsideDomainNotPermitted"}


def member_refusal(address: str, exc: GoogleSaidNo) -> str:
    """Why `address` could not be put in a shared drive, as somebody can act on it."""
    reason = getattr(exc, "reason", "") or ""
    said = str(exc).rstrip(".")
    if reason in OUTSIDE_NOT_ALLOWED:
        return (f"{address} was not added: the organisation's Google Workspace rules do not "
                "let this shared drive have people from outside the organisation (Google "
                f"said: {said}). A Workspace administrator can allow it in the Admin "
                "console under Apps, Google Workspace, Drive and Docs, Sharing settings; "
                "a Manager can then turn on the drive's own setting that lets people "
                "outside the organisation in.")
    if reason in ("cannotShareTeamDriveWithNonGoogleAccounts", "invalidSharingRequest"):
        return (f"{address} was not added: it is not a Google account, and a shared drive "
                f"takes only Google accounts (Google said: {said}). They can make one for "
                "that address at accounts.google.com, or be added by a Google address of "
                "theirs.")
    if reason in ("insufficientFilePermissions", "insufficientPermissions") or exc.status == 403:
        return (f"{address} was not added: Google refused it (Google said: {said}). Only a "
                "Manager of a shared drive can add people to it, and the organisation's "
                "sharing rules can stop it too.")
    return f"{address} was not added: {said}."


def _a_role(role: str) -> str:
    """One of the three roles, or a refusal that lists them."""
    wanted = (role or "reader").strip().lower()
    if wanted not in ROLES:
        raise GoogleSaidNo(
            f"{role!r} is not a level of access I can give. It is reader, "
            f"commenter or writer.")
    return wanted


def can(role: str) -> str:
    """What holding a role lets somebody do, as a person would say it."""
    return ROLE_WORDS.get((role or "").lower(), role or "open")


def _a_permission(one: dict) -> dict:
    """One row of "who can see this", named the way a person names people."""
    kind = one.get("type") or ""
    email = one.get("emailAddress") or ""
    if kind == "anyone":
        who = "anyone with the link"
    elif kind == "domain":
        who = "everybody at " + (one.get("domain") or "that domain")
    else:
        who = one.get("displayName") or email or kind or "somebody"
    return {"id": one.get("id") or "", "who": who, "kind": kind,
            "role": one.get("role") or "", "email": email}


def _a_listed_file(found: dict) -> dict:
    """One row of a search or a folder listing, named the way a person names it.

    Drive's own field names stop here: everything above this reads `name`,
    `type`, `owner` and `modified`, so a change in what Drive calls something
    is one line rather than a sweep.
    """
    owners = found.get("owners") or []
    owner = ""
    if owners:
        owner = owners[0].get("displayName") or owners[0].get("emailAddress") or ""
    return {
        "id": found.get("id") or "",
        "name": found.get("name") or "",
        "type": _kind(found.get("mimeType") or ""),
        "mime_type": found.get("mimeType") or "",
        "owner": owner,
        "modified": found.get("modifiedTime") or "",
        "link": found.get("webViewLink") or "",
    }


def _drive_quote(text: str) -> str:
    """One value inside Drive's query language, with its two escapes applied."""
    return (text or "").strip().replace("\\", "\\\\").replace("'", "\\'")


def _multipart(metadata: dict, content: str | bytes, mime_type: str) -> tuple[bytes, str]:
    """A `multipart/related` body: the file's name and its bytes in one request.

    Text written by the assistant arrives here as a string and is sent as UTF-8.
    A file off this machine's disk arrives as the bytes it really is, and no
    charset is claimed for it: saying UTF-8 about a PNG is how a photograph
    lands in Drive corrupted.
    """
    boundary = "rouh-" + uuid.uuid4().hex
    if isinstance(content, str):
        data, said = content.encode("utf-8"), f"{mime_type}; charset=UTF-8"
    else:
        data, said = content or b"", mime_type
    parts = [
        f"--{boundary}\r\nContent-Type: application/json; charset=UTF-8\r\n\r\n"
        f"{json.dumps(metadata)}\r\n".encode(),
        f"--{boundary}\r\nContent-Type: {said}\r\n\r\n".encode(),
        data,
        f"\r\n--{boundary}--\r\n".encode(),
    ]
    return b"".join(parts), boundary


def _pick_one(wanted: str, found: list[dict], thing: str = "folder",
              where: str = "in that Drive") -> str:
    """The sentence for a name that fits several things, with all of them in it.

    Every candidate by its id, because the id is what the next call takes, and
    its link, because that is what settles which one a person meant. Never a
    guess: the whole failure this prevents is a file put quietly into the wrong
    one of two folders with the same name.
    """
    lines = [f"{one['name']!r} - id {one['id']}"
             + (f" - {one['link']}" if one.get("link") else "")
             for one in found[:MAX_FILES]]
    return (f"There is more than one {thing} called {wanted!r} {where}, so I have "
            f"not guessed. Say which one by its id:\n" + "\n".join(lines))


#: Extensions Python's own table does not know, or knows differently from the
#: way Drive and a browser treat them.
OUR_TYPES = {
    ".md": "text/markdown", ".markdown": "text/markdown",
    ".yml": "application/yaml", ".yaml": "application/yaml",
    ".webp": "image/webp", ".heic": "image/heic", ".avif": "image/avif",
    ".webm": "video/webm", ".m4a": "audio/mp4", ".opus": "audio/opus",
    ".ts": "text/plain", ".jsx": "text/plain", ".tsx": "text/plain",
    ".sql": "text/plain", ".toml": "text/plain", ".ini": "text/plain",
    ".log": "text/plain", ".env": "text/plain",
}


def type_of(path: str) -> str:
    """What a file is, from its name, in the words a browser and Drive agree on.

    A guess, and deliberately a conservative one: anything unrecognised is
    `application/octet-stream`, which Drive stores byte for byte and never
    tries to be clever with.
    """
    ending = os.path.splitext(path or "")[1].lower()
    if ending in OUR_TYPES:
        return OUR_TYPES[ending]
    guessed, _ = mimetypes.guess_type(path or "")
    return guessed or "application/octet-stream"


def size_said(count: int) -> str:
    """A number of bytes as a person would say it, for a chip and for an ear."""
    if count == 1:
        return "1 byte"
    if count < 1024:
        return f"{count} bytes"
    if count < 1024 * 1024:
        return f"{count / 1024:.0f} KB"
    return f"{count / (1024 * 1024):.1f} MB"


#: Drive's own media types, in the words a person uses for them.
KINDS = {
    DOC_TYPE: "Google Doc",
    "application/vnd.google-apps.spreadsheet": "Google Sheet",
    "application/vnd.google-apps.presentation": "Google Slides",
    FOLDER_TYPE: "Folder",
    "application/pdf": "PDF",
    "image/png": "PNG image",
    "image/jpeg": "JPEG image",
    "text/plain": "Text file",
}


def _kind(mime: str) -> str:
    if mime in KINDS:
        return KINDS[mime]
    if mime.startswith("image/"):
        return "Image"
    if mime.startswith("video/"):
        return "Video"
    if mime.startswith("audio/"):
        return "Audio"
    return mime or "File"
