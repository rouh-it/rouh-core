"""A stand-in for Stripe's API, so Payments' Stripe half can be driven with nothing real.

The same idea as `fake_apify.py`: a real HTTP server in front of the real client
(`payments.Stripe`), so what a check proves is what went over the wire. It speaks
enough of Stripe's form-encoded API, in its shapes, for what Rouh does with a
restricted key:

- ``POST /v1/products``, ``/v1/prices`` and ``/v1/payment_links``, which make one
  and answer it, metadata and all;
- ``POST /v1/webhook_endpoints`` and ``DELETE /v1/webhook_endpoints/<id>``, which
  keep the endpoint and answer its signing secret once, as Stripe does;
- ``GET /v1/balance`` and ``GET /v1/payment_intents``;
- ``POST /v1/refunds``, refused with Stripe's own permission error, because the
  restricted key Rouh is told to make has no access to refunds.

A key that does not start ``rk_test_`` is refused with Stripe's own 401.

``POST /_pay {"link": "plink_..."}`` is somebody paying through a payment link: a
``checkout.session.completed`` event is signed with the endpoint's secret, exactly as
Stripe signs one, and posted to every endpoint made. ``{"forged": true}`` signs it
with the wrong secret, so a check can see it refused. ``GET /_calls`` lists every
call, oldest first.

Point ``ROUH_STRIPE_API_BASE`` at it.

    python -m rouh.testing.fake_stripe --port 8099
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import itertools
import json
import secrets
import time
import urllib.error
import urllib.request

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

_ids = itertools.count(1)


def _id(prefix: str) -> str:
    return f"{prefix}_test{next(_ids):04d}{secrets.token_hex(4)}"


def _unflatten(form) -> dict:
    """Stripe's ``line_items[0][price]=x`` back into nested values."""
    out: dict = {}
    for key, value in form.items():
        parts = key.replace("]", "").split("[")
        node = out
        for part, nxt in zip(parts, parts[1:] + [None]):
            if nxt is None:
                node[part] = value
            else:
                node = node.setdefault(part, {})
    return out


def sign(secret: str, payload: bytes, at: int | None = None) -> str:
    at = int(time.time()) if at is None else at
    sig = hmac.new(secret.encode(), f"{at}.".encode() + payload, hashlib.sha256).hexdigest()
    return f"t={at},v1={sig}"


def build_app() -> FastAPI:
    app = FastAPI()
    state = {"products": {}, "prices": {}, "links": {}, "hooks": {}, "intents": [], "calls": []}

    def refused(status: int, message: str, kind: str = "invalid_request_error"):
        return JSONResponse({"error": {"type": kind, "message": message}}, status_code=status)

    def key_of(request: Request) -> str:
        import base64

        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("basic "):
            try:
                return base64.b64decode(auth[6:]).decode().split(":")[0]
            except Exception:
                return ""
        return auth[7:] if auth.lower().startswith("bearer ") else ""

    @app.middleware("http")
    async def check_key(request: Request, call_next):
        if request.url.path.startswith("/v1/"):
            state["calls"].append({"method": request.method, "path": request.url.path,
                                   "at": time.time()})
            if not key_of(request).startswith("rk_test_"):
                return refused(401, "Invalid API Key provided.")
        return await call_next(request)

    @app.post("/v1/products")
    async def products(request: Request):
        form = _unflatten(await request.form())
        if not form.get("name"):
            return refused(400, "Missing required param: name.")
        made = {"id": _id("prod"), "object": "product", "name": form["name"],
                "description": form.get("description"), "metadata": form.get("metadata") or {}}
        state["products"][made["id"]] = made
        return made

    @app.post("/v1/prices")
    async def prices(request: Request):
        form = _unflatten(await request.form())
        if form.get("product") not in state["products"]:
            return refused(400, f"No such product: '{form.get('product')}'")
        made = {"id": _id("price"), "object": "price", "product": form["product"],
                "currency": form.get("currency"), "unit_amount": int(form.get("unit_amount") or 0),
                "recurring": form.get("recurring"), "metadata": form.get("metadata") or {}}
        state["prices"][made["id"]] = made
        return made

    @app.post("/v1/payment_links")
    async def links(request: Request):
        form = _unflatten(await request.form())
        items = form.get("line_items") or {}
        first = (items.get("0") or {}) if isinstance(items, dict) else {}
        if first.get("price") not in state["prices"]:
            return refused(400, f"No such price: '{first.get('price')}'")
        ident = _id("plink")
        made = {"id": ident, "object": "payment_link", "url": f"https://buy.stripe.com/test_{ident[-8:]}",
                "active": True, "metadata": form.get("metadata") or {},
                "line_items": [{"price": first["price"], "quantity": int(first.get("quantity") or 1)}]}
        state["links"][ident] = made
        return made

    @app.post("/v1/webhook_endpoints")
    async def hooks(request: Request):
        form = _unflatten(await request.form())
        if not str(form.get("url") or "").startswith(("http://", "https://")):
            return refused(400, "Invalid URL.")
        made = {"id": _id("we"), "object": "webhook_endpoint", "url": form["url"],
                "enabled_events": list((form.get("enabled_events") or {}).values()),
                "secret": "whsec_" + secrets.token_hex(16), "status": "enabled"}
        state["hooks"][made["id"]] = made
        return made

    @app.delete("/v1/webhook_endpoints/{ident}")
    async def hook_gone(ident: str):
        state["hooks"].pop(ident, None)
        return {"id": ident, "object": "webhook_endpoint", "deleted": True}

    @app.get("/v1/balance")
    async def balance():
        paid = sum(p["amount"] for p in state["intents"])
        return {"object": "balance", "available": [{"amount": 0, "currency": "usd"}],
                "pending": [{"amount": paid, "currency": "usd"}]}

    @app.get("/v1/payment_intents")
    async def intents():
        return {"object": "list", "data": list(reversed(state["intents"]))[:20], "has_more": False}

    @app.post("/v1/refunds")
    async def refunds():
        return refused(403, "The provided key does not have the required permissions for this "
                            "endpoint. Having the 'rak_refund_write' permission would allow this "
                            "request to continue.", "invalid_request_error")

    @app.post("/_pay")
    async def pay(request: Request):
        """Somebody pays through a payment link: the signed event goes to every endpoint."""
        body = await request.json()
        link = state["links"].get(str(body.get("link") or ""))
        if link is None:
            return refused(404, "No such payment link.")
        price = state["prices"][link["line_items"][0]["price"]]
        amount = price["unit_amount"] * link["line_items"][0]["quantity"]
        intent = {"id": _id("pi"), "object": "payment_intent", "amount": amount,
                  "amount_received": amount, "currency": price["currency"], "status": "succeeded",
                  "created": int(time.time()), "metadata": link["metadata"]}
        state["intents"].append(intent)
        event = {"id": _id("evt"), "object": "event", "type": "checkout.session.completed",
                 "created": int(time.time()),
                 "data": {"object": {"id": _id("cs"), "object": "checkout.session",
                                     "payment_link": link["id"], "payment_intent": intent["id"],
                                     "amount_total": amount, "currency": price["currency"],
                                     "payment_status": "paid", "metadata": link["metadata"],
                                     "customer_details": {"email": body.get("email") or "buyer@example.com"}}}}
        payload = json.dumps(event).encode()
        said = []
        for hook in state["hooks"].values():
            secret = "whsec_forged" if body.get("forged") else hook["secret"]
            req = urllib.request.Request(hook["url"], data=payload, method="POST", headers={
                "Content-Type": "application/json", "Stripe-Signature": sign(secret, payload)})
            try:
                with urllib.request.urlopen(req, timeout=20) as r:
                    said.append({"url": hook["url"], "status": r.status})
            except urllib.error.HTTPError as exc:
                said.append({"url": hook["url"], "status": exc.code})
            except Exception as exc:  # noqa: BLE001 - said back to the check
                said.append({"url": hook["url"], "error": str(exc)})
        return {"event": event["id"], "intent": intent["id"], "amount": amount, "delivered": said}

    @app.get("/_calls")
    async def calls():
        return {"calls": state["calls"], "hooks": list(state["hooks"].values()),
                "links": list(state["links"].values())}

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=8099)
    args = parser.parse_args()
    import uvicorn

    uvicorn.run(build_app(), host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
