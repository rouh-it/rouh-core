"""A stand-in for Brevo, so a letter Rouh sends can be read and followed.

The same idea as `fake_telegram.py`: a real HTTP server in front of the real
client (`rouh/mailer.py`), so what a check proves is what went over the wire.

It answers Brevo's ``POST /v3/smtp/email`` the way Brevo does - 201 and a
``messageId`` - and refuses a request whose ``api-key`` header is not the one
it was started with, with Brevo's own 401 shape, because a key copied down
wrong is the failure worth standing in for. Every letter it takes is written
down whole.

And it has an inbox a browser can open, ``/inbox``: every letter, newest
first, with its HTML drawn as it would be in a mail program and its links
live. A drive of the invitation is then what a person does - open the mail,
press the link in it - rather than a check reaching into a file for a token.

Point ``ROUH_BREVO_URL`` at it and give Rouh a key file of its own with
``ROUH_BREVO_FILE`` holding `KEY`. `rouh/testing/browser.py` does both for
the ``talking`` world.

    python -m rouh.testing.fake_brevo --port 8096 --record /tmp/mail
"""
from __future__ import annotations

import argparse
import html
import json
import os
import time

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse

#: The key this stand-in accepts, and the one the talking world's key file holds.
KEY = "xkeysib-test-not-a-real-one"


def build_app(record_dir: str | None = None, key: str = KEY) -> FastAPI:
    app = FastAPI()
    kept: list[dict] = []

    @app.get("/v3/account")
    async def account(request: Request):
        """The account the key is, as Settings, Keys checks it (`rouh/service_keys.py`)."""
        if request.headers.get("api-key") != key:
            return JSONResponse({"code": "unauthorized", "message": "Key not found"}, status_code=401)
        return JSONResponse({"email": "owner@example.test", "companyName": "Example"})

    @app.post("/v3/smtp/email")
    async def send(request: Request):
        if request.headers.get("api-key") != key:
            return JSONResponse({"code": "unauthorized", "message": "Key not found"},
                                status_code=401)
        try:
            body = await request.json()
        except ValueError:
            body = {}
        if not isinstance(body, dict) or not body.get("to") or not body.get("sender"):
            return JSONResponse({"code": "missing_parameter",
                                 "message": "sender and to are required"}, status_code=400)
        n = len(kept) + 1
        letter = {"n": n, "at": time.time(), "messageId": f"<{n}.{int(time.time())}@fake-brevo>",
                  **body}
        kept.append(letter)
        if record_dir:
            with open(os.path.join(record_dir, f"{n:04d}.json"), "w", encoding="utf-8") as fh:
                json.dump(letter, fh)
        return JSONResponse({"messageId": letter["messageId"]}, status_code=201)

    @app.get("/letters")
    async def letters():
        """Every letter, oldest first, for a check that would rather read JSON."""
        return JSONResponse(kept)

    @app.get("/inbox", response_class=HTMLResponse)
    async def inbox():
        """Every letter as a mail program would show it, newest first."""
        rows = []
        for letter in reversed(kept):
            to = ", ".join(str(t.get("email") or "") for t in letter.get("to") or [])
            sender = letter.get("sender") or {}
            body = letter.get("htmlContent") or (
                "<pre>" + html.escape(str(letter.get("textContent") or "")) + "</pre>")
            rows.append(
                '<article class="letter">'
                f'<p class="head"><b>{html.escape(str(letter.get("subject") or ""))}</b><br>'
                f'From {html.escape(str(sender.get("name") or ""))} '
                f'&lt;{html.escape(str(sender.get("email") or ""))}&gt; to {html.escape(to)}</p>'
                f'<div class="body">{body}</div></article>')
        page = ("<!doctype html><meta charset='utf-8'><title>Inbox</title>"
                "<style>body{font:15px/1.5 sans-serif;margin:24px;background:#eee}"
                ".letter{background:#fff;margin:0 0 20px;padding:16px;border-radius:8px}"
                ".head{color:#555;border-bottom:1px solid #ddd;padding-bottom:8px}</style>"
                f"<h1>Inbox ({len(kept)})</h1>" + ("".join(rows) or "<p>No letters yet.</p>"))
        return HTMLResponse(page)

    return app


def main() -> None:
    import uvicorn

    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--record", default=None)
    args = ap.parse_args()
    if args.record:
        os.makedirs(args.record, exist_ok=True)
    uvicorn.run(build_app(args.record), host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
