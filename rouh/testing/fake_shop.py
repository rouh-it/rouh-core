"""A stand-in website for the browser to open, so Rouh's browsers can be driven end to end with
nothing real (the stack test, tests/stack/checks_browser.py).

- ``/``: one big button, at the same place on every screen, that says on the page when it was
  pressed, so a click on the page's picture can be seen to have reached the page.
- ``/wall``: what a site behind a bot check does to a fetcher. The stand-in model's web_fetch is
  Python's urllib (`fake_model.fetch_page`), which is answered 403; a browser gets the page.
- ``/signup``: a sign-up form (an email and a new password), which keeps what it is sent;
  ``/_signups`` says what it was sent.
"""
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse

FRONT = """<!doctype html><html><head><meta charset="utf-8"><title>Stack test shop</title>
<style>body{margin:0;font:20px sans-serif} #press{position:absolute;left:0;top:0;width:400px;
height:200px;font-size:28px} #said{position:absolute;left:0;top:240px}</style></head><body>
<button id="press" onclick="document.getElementById('said').textContent='Pressed by the person'">
Press here</button><p id="said">Nobody has pressed it yet</p></body></html>"""

SIGNUP = """<!doctype html><html><head><meta charset="utf-8"><title>Join the stack test shop</title>
</head><body><h1>Make an account</h1><form method="post" action="/signup">
<label>Email <input name="email" type="email" autocomplete="email"></label>
<label>Password <input name="password" type="password" autocomplete="new-password"></label>
<button type="submit">Create account</button></form></body></html>"""

WALL = ("<!doctype html><title>Behind the wall</title><h1>Behind the wall</h1>"
        "<p>Only a real browser reads the stack test's hidden sentence.</p>")


def build_app() -> FastAPI:
    app = FastAPI()
    signups: list[dict] = []

    @app.get("/", response_class=HTMLResponse)
    def front():
        return FRONT

    @app.get("/wall", response_class=HTMLResponse)
    def wall(request: Request):
        if "python" in request.headers.get("user-agent", "").lower():
            return HTMLResponse("<h1>Access denied</h1>", status_code=403)
        return WALL

    @app.get("/signup", response_class=HTMLResponse)
    def signup_page():
        return SIGNUP

    @app.post("/signup", response_class=HTMLResponse)
    async def signup(request: Request):
        form = await request.form()
        signups.append({"email": str(form.get("email") or ""), "password": str(form.get("password") or "")})
        return "<!doctype html><title>Welcome aboard</title><h1>Welcome aboard</h1>"

    @app.get("/_signups")
    def seen():
        return JSONResponse({"signups": signups})

    return app
