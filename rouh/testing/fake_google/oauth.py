"""Oauth registration for the Google stand-in."""
from __future__ import annotations

from . import (
    ACCESS_TOKEN,
    ACCOUNT_EMAIL,
    ACCOUNT_ID,
    AS_ACCESS,
    Form,
    HTMLResponse,
    JSONResponse,
    READ_ONLY_ACCOUNTS,
    REFRESH_TOKEN,
    RENEWED_ACCESS_TOKEN,
    RO_ACCESS,
    RO_REFRESH,
    RedirectResponse,
    Request,
    SIGN_IN_SCOPES,
    _asks_read_only,
    _asks_sign_in,
    _page,
    _read_only_account,
    _read_only_chooser,
    _sign_in_chooser,
    html,
    json,
    urllib,
)


def _oauth_routes(app, world, seen, codes, redirect, client_id, client_secret):
    # --- the consent screen --------------------------------------------------

    @app.get("/o/oauth2/v2/auth", response_class=HTMLResponse)
    async def consent(request: Request):
        query = dict(request.query_params)
        seen["consent"].append(query)
        asked = query.get("redirect_uri", "")
        if asked != redirect:
            # Exactly what Google does when the address is not registered.
            return HTMLResponse(_page(
                "Error 400: redirect_uri_mismatch",
                f"<p>The redirect URI in the request, <code>{html.escape(asked)}</code>, "
                f"does not match a registered redirect URI.</p>"), status_code=400)
        if query.get("client_id") != client_id:
            return HTMLResponse(_page(
                "Error 401: invalid_client",
                "<p>The OAuth client was not found.</p>"), status_code=401)
        state = query.get("state", "")
        if _asks_read_only(query.get("scope", "")):
            return HTMLResponse(_read_only_chooser(state, query.get("scope", "")))
        if _asks_sign_in(query.get("scope", "")):
            return HTMLResponse(_sign_in_chooser(state, query.get("scope", ""),
                                                 query.get("login_hint", "")))
        allow = "/decide?" + urllib.parse.urlencode({"answer": "allow", "state": state,
                                                     "scope": query.get("scope", "")})
        cancel = "/decide?" + urllib.parse.urlencode({"answer": "cancel", "state": state})
        return HTMLResponse(_page(
            "Choose an account",
            f"<p>Rouh wants to access your Google Account "
            f"<strong>{ACCOUNT_EMAIL}</strong>.</p>"
            f"<p class=\"scopes\">{html.escape(query.get('scope', ''))}</p>"
            f"<a id=\"allow\" href=\"{html.escape(allow)}\">Allow</a> "
            f"<a id=\"cancel\" href=\"{html.escape(cancel)}\">Cancel</a>"))

    @app.get("/decide")
    async def decide(answer: str = "cancel", state: str = "", scope: str = "",
                     account: str = "", as_email: str = "", as_name: str = "",
                     as_verified: str = ""):
        if answer == "allow" and as_email.strip():
            # Signing in as somebody other than the connected account, chosen
            # or typed on the sign-in chooser (`_sign_in_chooser`).
            code = "fake-as-code-" + str(len(codes) + 1)
            codes[code] = "as:" + json.dumps({
                "email": as_email.strip(), "name": as_name.strip(),
                "verified": as_verified in ("1", "true", "on")})
            back = redirect + "?" + urllib.parse.urlencode(
                {"code": code, "state": state, "scope": scope})
            return RedirectResponse(back, status_code=303)
        if answer == "allow" and account in READ_ONLY_ACCOUNTS:
            # A read-only mailbox: what was asked for, plus anything a test
            # set with `/_read_only_grant` to stand a wider grant in front of Rouh.
            granted = [one for one in scope.split() if one] + list(world["ro_extra"])
            code = "fake-ro-code-" + str(len(codes) + 1)
            codes[code] = f"ro:{account}:" + " ".join(granted)
            back = redirect + "?" + urllib.parse.urlencode(
                {"code": code, "state": state, "scope": " ".join(granted)})
            return RedirectResponse(back, status_code=303)
        if answer == "allow":
            # Granted is what was asked for, narrowed to what this Google is
            # willing to hand over. That is how a person can end up holding a
            # grant older than what Rouh now asks for.
            asked = [one for one in scope.split() if one]
            granted = [one for one in asked if one in world["grant"]] or list(world["grant"])
            code = "fake-code-" + str(len(codes) + 1)
            codes[code] = " ".join(granted)
            back = redirect + "?" + urllib.parse.urlencode(
                {"code": code, "state": state, "scope": " ".join(granted)})
        else:
            back = redirect + "?" + urllib.parse.urlencode(
                {"error": "access_denied", "state": state})
        return RedirectResponse(back, status_code=303)

    # --- the exchanges --------------------------------------------------------

    @app.post("/token")
    async def token(grant_type: str = Form(""), code: str = Form(""),
                    refresh_token: str = Form(""), client_id_in: str = Form("", alias="client_id"),
                    client_secret_in: str = Form("", alias="client_secret"),
                    redirect_uri: str = Form("")):
        seen["token"].append({"grant_type": grant_type, "client_id": client_id_in,
                              "redirect_uri": redirect_uri,
                              "secret_matched": client_secret_in == client_secret,
                              "code": code, "had_refresh_token": bool(refresh_token)})
        if client_id_in != client_id or client_secret_in != client_secret:
            return JSONResponse(
                {"error": "invalid_client", "error_description": "Unauthorized"},
                status_code=401)
        if grant_type == "authorization_code":
            if redirect_uri != redirect:
                return JSONResponse(
                    {"error": "redirect_uri_mismatch",
                     "error_description": "Bad Request"}, status_code=400)
            if code not in codes:
                return JSONResponse(
                    {"error": "invalid_grant", "error_description": "Bad Request"},
                    status_code=400)
            granted = codes.pop(code)
            if granted.startswith("as:"):
                token_for = f"{AS_ACCESS}{len(world['signed_in_as']) + 1}"
                world["signed_in_as"][token_for] = json.loads(granted[3:])
                return JSONResponse({"access_token": token_for, "expires_in": 3600,
                                     "token_type": "Bearer", "scope": " ".join(SIGN_IN_SCOPES)})
            if granted.startswith("ro:"):
                _ro, account, scopes = granted.split(":", 2)
                # What this account's token may do, which is what decides
                # whether a send made with it is refused.
                world["ro_scopes"][account] = scopes.split()
                return JSONResponse({
                    "access_token": f"{RO_ACCESS}{account}",
                    "refresh_token": f"{RO_REFRESH}{account}",
                    "expires_in": 3600, "token_type": "Bearer", "scope": scopes})
            # What the token about to be handed out may do, which is what the
            # calendar addresses check it against.
            world["token_scopes"] = granted.split()
            return JSONResponse({
                "access_token": ACCESS_TOKEN, "refresh_token": REFRESH_TOKEN,
                "expires_in": 3600, "token_type": "Bearer",
                "scope": granted,
            })
        if grant_type == "refresh_token" and refresh_token.startswith(RO_REFRESH):
            account = refresh_token[len(RO_REFRESH):]
            if account not in READ_ONLY_ACCOUNTS or account in world["ro_withdrawn"]:
                return JSONResponse(
                    {"error": "invalid_grant", "error_description": "Token has been expired "
                                                                    "or revoked."},
                    status_code=400)
            return JSONResponse({"access_token": f"{RO_ACCESS}{account}-renewed",
                                 "expires_in": 3600, "token_type": "Bearer"})
        if grant_type == "refresh_token":
            if refresh_token != REFRESH_TOKEN:
                return JSONResponse(
                    {"error": "invalid_grant", "error_description": "Token revoked"},
                    status_code=400)
            return JSONResponse({"access_token": RENEWED_ACCESS_TOKEN,
                                 "expires_in": 3600, "token_type": "Bearer"})
        return JSONResponse({"error": "unsupported_grant_type"}, status_code=400)

    @app.post("/revoke")
    async def revoke(token: str = Form("")):
        seen["revoke"] += 1
        seen["revoked"].append(token[:40])
        return JSONResponse({})

    @app.get("/userinfo")
    async def userinfo(request: Request):
        bearer = (request.headers.get("authorization") or "").removeprefix("Bearer ").strip()
        signed_in = world["signed_in_as"].get(bearer)
        if signed_in:
            name = signed_in["name"]
            return JSONResponse({"email": signed_in["email"], "name": name,
                                 "given_name": name.partition(" ")[0],
                                 "family_name": name.partition(" ")[2],
                                 "sub": "1088" + str(abs(hash(signed_in["email"])))[:17],
                                 "email_verified": signed_in["verified"]})
        account = _read_only_account(request)
        if account:
            one = READ_ONLY_ACCOUNTS[account]
            return JSONResponse({"email": one["email"], "sub": one["sub"],
                                 "email_verified": True})
        return JSONResponse({"email": ACCOUNT_EMAIL, "sub": ACCOUNT_ID,
                             "email_verified": True})
