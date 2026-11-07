"""A stand-in for Voyage AI's embeddings API, so Synapse's vectors can be made
for real in a test world with no key and nothing reaching the network.

A real HTTP server speaking `POST /v1/embeddings` the way Voyage documents it
(docs.voyageai.com, "Text embeddings"; MongoDB's `ai.mongodb.com` is the same
API): a bearer key, `input`, `model`, `input_type` and `output_dimension`, an
answer with `data[].embedding` and `data[].index`, `model` and
`usage.total_tokens`. Point `VOYAGE_ENDPOINT` at it and give Rouh `KEY`.

- A vector is letter groups hashed into the numbers asked for, normalised, so
  texts that share words come out close and a passage asked about in its own
  words finds itself. A query is made a little differently from a document,
  as the real model makes them, so the two are close and never equal.
- It refuses what the real API refuses: a wrong key (401, `{"detail": ...}`),
  an unknown model, more than 1,000 texts, a dimension voyage-4 does not have.
- `VOYAGE429 n` in any text answers the next n requests 429 with a
  `retry-after` of one second, the way a key with no payment method is held to
  three requests a minute. `VOYAGEBROKEN` answers 500 every time it is sent.
- `POST /_limit {"n": 3}` does the same as `VOYAGE429 3` from outside.
- Every request lands in the record directory as `voyage-...json`, with its
  headers' names but never their values, and `GET /_state` says how many
  requests, refusals and texts there were.

    python -m rouh.testing.fake_voyage --port 8099 --record /tmp/requests
"""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
import os
import re
import time

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

KEY = "voyage-test-key-not-a-real-one"
MODELS = {"voyage-4": (1024, 256, 512, 2048), "voyage-4-lite": (1024, 256, 512, 2048),
          "voyage-4-large": (1024, 256, 512, 2048)}
LIMIT_LINE = re.compile(r"VOYAGE429\s+(\d+)")

_ids = itertools.count(1)


def vector(text: str, dims: int, query: bool) -> list[float]:
    v = [0.0] * dims
    t = re.sub(r"\s+", " ", (text or "").lower())
    for i in range(len(t) - 2):
        h = int(hashlib.md5(t[i:i + 3].encode()).hexdigest()[:8], 16)
        v[h % dims] += 1.0
    # The query side: one more number, so a question and its own passage are
    # near and never the same.
    v[(7 if query else 11) % dims] += 0.5
    norm = math.sqrt(sum(x * x for x in v)) or 1.0
    return [round(x / norm, 6) for x in v]


def build_app(record: str | None) -> FastAPI:
    app = FastAPI()
    state = {"requests": 0, "refused": 0, "texts": 0, "limit": 0, "models": {}, "input_types": {}}

    def keep(body, headers, status):
        if not record:
            return
        os.makedirs(record, exist_ok=True)
        name = f"voyage-{int(time.time() * 1000)}-{next(_ids):04d}.json"
        with open(os.path.join(record, name), "w") as fh:
            json.dump({"status": status, "header_names": sorted(headers), "body": body}, fh, ensure_ascii=False)

    def refuse(status, detail, body, headers, retry=None):
        state["refused"] += 1
        keep(body, headers, status)
        return JSONResponse(status_code=status, content={"detail": detail},
                            headers={"retry-after": str(retry)} if retry else None)

    @app.get("/_state")
    async def _state():
        return state

    @app.post("/_limit")
    async def _limit(request: Request):
        got = await request.json()
        state["limit"] = int(got.get("n") or 0)
        return {"ok": True, "limit": state["limit"]}

    @app.post("/v1/embeddings")
    async def embeddings(request: Request):
        state["requests"] += 1
        headers = {k.lower() for k in request.headers.keys()}
        try:
            body = await request.json()
        except ValueError:
            return refuse(400, "Request body is not valid JSON.", None, headers)
        if request.headers.get("authorization") != f"Bearer {KEY}":
            return refuse(401, "Provided API key is invalid.", body, headers)
        texts = body.get("input")
        texts = [texts] if isinstance(texts, str) else texts
        if not isinstance(texts, list) or not texts or not all(isinstance(t, str) for t in texts):
            return refuse(400, "input must be a string or a list of strings", body, headers)
        if len(texts) > 1000:
            return refuse(400, "The input list may have at most 1000 items.", body, headers)
        model = body.get("model")
        if model not in MODELS:
            return refuse(400, f"Model {model} is not supported.", body, headers)
        dims = body.get("output_dimension") or 1024
        if dims not in MODELS[model]:
            return refuse(400, f"output_dimension {dims} is not supported for {model}.", body, headers)
        kind = body.get("input_type")
        if kind not in (None, "query", "document"):
            return refuse(400, "input_type must be query, document or null", body, headers)
        joined = "\n".join(texts)
        if "VOYAGEBROKEN" in joined:
            return refuse(500, "Internal server error", body, headers)
        said = LIMIT_LINE.search(joined)
        if said and not state.get("seen_" + said.group(0)):
            state["seen_" + said.group(0)] = True
            state["limit"] = int(said.group(1))
        if state["limit"] > 0:
            state["limit"] -= 1
            return refuse(429, "Rate limit exceeded. Free tier: 3 RPM and 10K TPM.", body, headers, retry=1)
        state["texts"] += len(texts)
        state["models"][model] = state["models"].get(model, 0) + 1
        state["input_types"][str(kind)] = state["input_types"].get(str(kind), 0) + 1
        keep(body, headers, 200)
        return {"object": "list", "model": model,
                "data": [{"object": "embedding", "index": i, "embedding": vector(t, dims, kind == "query")}
                         for i, t in enumerate(texts)],
                "usage": {"total_tokens": max(1, len(joined) // 4)}}

    return app


def main() -> None:
    import uvicorn

    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--record", default=None)
    args = ap.parse_args()
    uvicorn.run(build_app(args.record), host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
