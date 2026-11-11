"""The page's own files: where they are, what address each is served at, and
the view that serves them.

Every front-end file lives in `rouh/static/` and is served at
``/a/<hash>/<name>``, where the hash is a short hash of that one file's own
content, taken when the process starts. An address therefore names one exact
set of bytes for ever, and is served with a year's immutable caching: the
browser, Cloudflare and anything in between may keep it without asking again.
A deploy that changes one file changes that file's address and no other, so a
phone that has Rouh cached downloads what changed and nothing else, and the
page itself, which is never cached, names the new addresses at once - no hard
refresh, and no stale bundle.

Until 5 October 2026 the hash was one stamp over every file's size and mtime,
so any deploy at all gave every file a new address and every visit after it
downloaded the whole page again, two and a half megabytes of it. This is
Django's ManifestStaticFilesStorage idea without its build step: no
collectstatic, nothing written anywhere, the hashes worked out in memory when
the process starts, which is when the files can change.

An address whose hash is not the file's current one - an open tab from before
a deploy asking for a file it was told about then, or one made up - is still
answered with the current file, so an open tab keeps working, but with
``no-store``, so nothing anywhere keeps the new bytes under the old name.

The build as a whole (`ASSETS`) is a hash of every file's hash and of the page's
templates. The page carries it in ``<meta name="rouh-build">`` and the server
names it on every connect, which is how an open tab knows Rouh has been
updated under it (`noteBuild` in app.js).

The page itself is a Django template (`rouh/templates/rouh/index.html`), and
names a file with ``{% asset "app.js" %}`` (`rouh/templatetags/rouh_assets.py`).
A script that loads another file by name - the microphone worklet, the speech
model - is rewritten as it is served (`fingerprint`), because a script is not
a template, and the rewritten bytes are what its hash is taken over.
"""
from __future__ import annotations

import hashlib
import mimetypes
import os
import re

from django.http import Http404, HttpResponse

from .common import file_response

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC = os.path.join(HERE, "static")
TEMPLATES = os.path.join(HERE, "templates", "rouh")


def _every_file() -> dict[str, str]:
    """Every file under rouh/static, by its path relative to it ("app.js",
    "askai/askai.js"), skipping dotfiles."""
    found = {}
    for folder, dirs, files in os.walk(STATIC):
        dirs[:] = sorted(d for d in dirs if not d.startswith((".", "__")))
        for name in files:
            if name.startswith("."):
                continue
            path = os.path.join(folder, name)
            found[os.path.relpath(path, STATIC).replace(os.sep, "/")] = path
    return found


#: Every file that can be served, by its name under rouh/static.
FILES = _every_file()

#: The files a script may name, which are the ones `fingerprint` rewrites: the
#: ones at the top of rouh/static, as they always were.
ASSET_NAMES = sorted(n for n in FILES if "/" not in n)

#: The kinds whose text is rewritten to point at other files' addresses: the
#: scripts, and the web app manifest, which names its icons.
REWRITTEN_KINDS = (".js", ".mjs", ".webmanifest")


def _rewritten(name: str) -> bool:
    # The ONNX runtime locates its own .wasm and .mjs through the paths vad.js
    # gives it, not through a string in its source, and rewriting names inside
    # its minified bundle would only corrupt it.
    # Nor three.js (`rouh/static/three/`), which names no file of ours and is
    # served exactly as it was published, bar the imports its README describes.
    return (os.path.splitext(name)[1] in REWRITTEN_KINDS
            and not os.path.basename(name).startswith("ort")
            and not name.startswith("three/"))


#: One pass over a script for every name it might mention, in each of the
#: shapes a reference takes - ``"app.js"``, ``"./app.js"``, ``"../app.js"`` (from
#: a module in rouh/static/app/), ``"/static/app.js"``, ``"static/app.js"`` - in
#: either quote. Longest names first, so ``ort.min.mjs``
#: is never read as a shorter name that happens to end it.
_REFERENCE = re.compile(
    r"""(["'])(?:\./|\.\./|/static/|static/)?("""
    + "|".join(re.escape(n) for n in sorted(ASSET_NAMES, key=len, reverse=True))
    + r")\1") if ASSET_NAMES else None

#: Each file's hash, and the rewritten bytes of the ones that are rewritten.
_HASH: dict[str, str] = {}
_BODY: dict[str, bytes] = {}
_BUSY: set[str] = set()


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:10]


def body(name: str) -> bytes:
    """What is served for a file: its bytes, or for a script its rewritten text."""
    if name in _BODY:
        return _BODY[name]
    with open(FILES[name], "rb") as fh:
        raw = fh.read()
    if not _rewritten(name):
        return raw
    _BODY[name] = fingerprint(raw.decode("utf-8")).encode("utf-8")
    return _BODY[name]


def file_hash(name: str) -> str:
    """The hash in one file's address: of what is served for it, so a script's
    hash moves when a file it names moves.

    Two files naming each other would have no fixed point; the second of them
    is hashed on its own bytes instead, which is still one name for one
    content, and the first then names it at an address answered without
    caching. No file here does that.
    """
    if name in _HASH:
        return _HASH[name]
    if name in _BUSY:
        with open(FILES[name], "rb") as fh:
            return _digest(fh.read())
    _BUSY.add(name)
    try:
        if _rewritten(name):
            got = _digest(body(name))
        else:
            h = hashlib.sha256()
            with open(FILES[name], "rb") as fh:
                for part in iter(lambda: fh.read(1 << 20), b""):
                    h.update(part)
            got = h.hexdigest()[:10]
    finally:
        _BUSY.discard(name)
    _HASH[name] = got
    return got


def address(name: str) -> str:
    """Where one file is served, with its own content's hash in it."""
    if name not in FILES:
        # A name the template asks for that is not there: an address that
        # answers 404, rather than a page that will not render at all.
        return f"/a/missing/{name}"
    return f"/a/{file_hash(name)}/{name}"


#: The folder of the page's own modules (app.js and rouh/static/app/).
MODULES = "app/"


def module_addresses() -> list[str]:
    """The hashed address of app.js and of every module under rouh/static/app/."""
    return [address(name) for name in ["app.js", *_modules()]]


def _modules() -> list[str]:
    """The modules under rouh/static/app/: its .js files, and not the .d.ts
    files beside them, which are types for the checker and nothing a browser
    loads (tools/typecheck)."""
    return sorted(n for n in FILES if n.startswith(MODULES) and n.endswith(".js"))


def import_map() -> str:
    """The import map that resolves ``import ... from 'app/socket.js'`` to that
    module's hashed address, as JSON safe inside a ``<script>`` element.

    The modules name each other by these bare names rather than by relative
    paths, because a relative path is resolved against the importing module's
    own address, and with each module under a hash of its own there is no one
    folder they share. With the names mapped here, no module's text contains
    another's hash, so changing one module changes one address.
    """
    import json

    imports = {name: address(name) for name in _modules()}
    imports.update(_three())
    return json.dumps({"imports": imports}, indent=1).replace("</", "<\\/")


#: The folder three.js is vendored in, for the 3D orb (`rouh/static/three/README.md`).
THREE = "three/"


def _three() -> dict[str, str]:
    """three.js by the names its own add-ons import it by: ``three`` for the
    library and ``three/addons/...`` for each add-on, each at its own hashed
    address. Only the 3D orb asks for them, and only once it knows this
    browser can draw in WebGL, so none of them is preloaded."""
    out = {}
    for name in sorted(FILES):
        if not name.startswith(THREE) or not name.endswith(".js"):
            continue
        if name == THREE + "three.module.min.js":
            out["three"] = address(name)
        elif name.startswith(THREE + "addons/"):
            out[name] = address(name)
    return out


def fingerprint(text: str) -> str:
    """Point every reference to a front-end file at its hashed address."""
    if _REFERENCE is None:
        return text
    return _REFERENCE.sub(lambda m: f"{m.group(1)}{address(m.group(2))}{m.group(1)}", text)


def _build() -> str:
    """The build as a whole: every file's hash, and the page's templates, which
    are in it because a change to the page alone is still a new page."""
    h = hashlib.sha256()
    for name in sorted(FILES):
        h.update(f"{name}:{file_hash(name)}\n".encode())
    for name in sorted(os.listdir(TEMPLATES)):
        path = os.path.join(TEMPLATES, name)
        if os.path.isfile(path):
            with open(path, "rb") as fh:
                h.update(name.encode() + b":" + fh.read())
    return h.hexdigest()[:10]


#: The build, taken once when the process starts.
ASSETS = _build()


#: The kinds under rouh/static/ that are text. Anything else is read and
#: returned as bytes: the speech model, the wasm runtime, an app icon.
TEXT_ASSETS = (".js", ".mjs", ".css", ".html", ".svg", ".json", ".webmanifest")

KINDS = {
    ".js": "application/javascript; charset=utf-8",
    ".mjs": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".html": "text/html; charset=utf-8",
    ".svg": "image/svg+xml",
    ".json": "application/json",
    # A browser will not read a home screen install out of a file served as
    # anything else, and a manifest that is not read is an app that opens in
    # a browser tab with the address pill still on it.
    ".webmanifest": "application/manifest+json",
    ".png": "image/png",
    # WebAssembly.instantiateStreaming refuses anything else and the runtime
    # then falls back to a slower path, or fails outright.
    ".wasm": "application/wasm",
    ".onnx": "application/octet-stream",
}

#: An address naming the file as it is now: kept for a year, never asked for
#: again. Anything else: the current file, kept nowhere.
FOREVER = "public, max-age=31536000, immutable"
NOT_KEPT = "no-store"


async def asset(request, stamp: str, filename: str):
    """``/a/<hash>/<name>``. The hash is checked: the file's own is cached for
    good, any other is answered with the current file and ``no-store``."""
    if request.method not in ("GET", "HEAD"):
        return HttpResponse(status=405, headers={"Allow": "GET, HEAD"})
    if ".." in filename.split("/") or filename.startswith("/") or "\\" in filename:
        return HttpResponse('{"error":"no"}', status=400, content_type="application/json")
    if filename not in FILES or not os.path.isfile(FILES[filename]):
        return HttpResponse('{"error":"not found"}', status=404,
                            content_type="application/json")
    ext = os.path.splitext(filename)[1]
    kind = KINDS.get(ext) or mimetypes.guess_type(filename)[0] or "application/octet-stream"
    headers = {"Cache-Control": FOREVER if stamp == file_hash(filename) else NOT_KEPT}
    if _rewritten(filename):
        return HttpResponse(body(filename), content_type=kind, headers=headers)
    response = file_response(FILES[filename], kind)
    for name, value in headers.items():
        response[name] = value
    return response


async def static_file(request, path: str):
    """``/static/<path>``: an old bookmark into rouh/static, or the admin's files.

    Kept so a hard-coded address still resolves, and so the Django admin has
    its styles without a separate web server: Rouh's own folder first, then
    whatever Django's apps ship (`django.contrib.staticfiles`).
    """
    from django.contrib.staticfiles import finders

    if request.method not in ("GET", "HEAD"):
        return HttpResponse(status=405, headers={"Allow": "GET, HEAD"})
    if ".." in path.split("/"):
        raise Http404
    found = finders.find(path)
    if not found or not os.path.isfile(found):
        raise Http404
    kind = KINDS.get(os.path.splitext(found)[1]) or mimetypes.guess_type(found)[0] \
        or "application/octet-stream"
    return file_response(found, kind)
