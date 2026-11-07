"""A stand-in for Google's and xAI's Chat Completions endpoints, so a Gemini or Grok turn is driven for real.

The same idea as `fake_model.py` and `fake_openai.py`: Rouh asks Google and xAI through
OpenAI's SDK pointed at their OpenAI-compatible endpoints (`rouh/llm.py`, `rouh/compat.py`),
and a test that patched the client would prove only that Rouh meant to send something. So
this is a real HTTP server that speaks enough of `POST .../chat/completions`, streamed or
whole, to be the far end of that SDK, at both providers' paths (`/v1beta/openai/` for
Google, `/v1/` for xAI). Point `ROUH_GOOGLE_BASE_URL` and `ROUH_XAI_BASE_URL` at it and give
Rouh any key; every request body lands in the record directory as `compat-...json`.

How it answers:

- With the model's own name, so a screen shows which model answered: "Gemini 4 Argon here.
  You said: ...". Every reply starts with the turn mark when the instructions ask for one.
- The router's plain question (`modelrouter.PLAIN`) is answered "easy", or "hard" when the
  message says HARD.
- A structured answer (`response_format` with a JSON schema) is `{}` filled with an empty
  value of each required property's type.
- `TOOL name {json}` in the person's words comes back as a real function call, and once the
  tool's result is handed back the answer says what it said. Gemini's thought signature
  (`extra_content`) comes with each call, and a request that hands back a call of this
  server's without its signature is refused with Google's words.
- `SLOWLY` writes the answer a word at a time, for the Stop button. A key that is not
  `test-...` is refused with 401.
- The usage says the first 1,000 tokens of the prompt were read from the cache.

    python -m rouh.testing.fake_compat --port 8099 --record /tmp/requests
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import time

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

from ..config import model_name
from ..turnmarks import FINISHED

TOOL = re.compile(r"TOOL\s+([a-z_][a-z0-9_]*)\s*(\{.*\})?", re.S)
SIGNATURE = "c2lnbmF0dXJlLWZyb20tdGhlLXN0YW5kLWlu"
MARK_INSTRUCTION = next(r["text"] for r in __import__("rouh.ruledefaults", fromlist=["fallback"]).fallback()["rules"]
                        if r["key"] == "turn-marks").strip().splitlines()[0]


def _words(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(str(p.get("text") or "") for p in content if isinstance(p, dict))
    return ""


def _empty(schema: dict):
    kind = (schema or {}).get("type")
    if kind == "object":
        return {k: _empty(v) for k, v in (schema.get("properties") or {}).items()
                if k in (schema.get("required") or [])}
    return {"array": [], "string": "", "integer": 0, "number": 0, "boolean": False}.get(kind)


def answer_of(body: dict) -> dict:
    """What this server says to one request: {"text"} or {"call": (name, args)}."""
    messages = body.get("messages") or []
    system = " ".join(_words(m.get("content")) for m in messages if m.get("role") == "system")
    model = str(body.get("model") or "")
    fmt = body.get("response_format") or {}
    if fmt.get("type") == "json_schema":
        return {"text": json.dumps(_empty((fmt.get("json_schema") or {}).get("schema") or {}))}
    last = messages[-1] if messages else {}
    asked = next((_words(m.get("content")) for m in reversed(messages) if m.get("role") == "user"), "")
    if "Answer with one word: easy" in system:
        return {"text": "hard" if "HARD" in asked else "easy"}
    if last.get("role") == "tool":
        said = str(last.get("content") or "")[:300]
        return {"text": f"{model_name(model)} here. The tool said: {said}"}
    found = TOOL.search(asked)
    if found and body.get("tools") is not None:
        try:
            args = json.loads(found.group(2) or "{}")
        except ValueError:
            args = {}
        return {"call": (found.group(1), args)}
    text = f"{model_name(model)} here. You said: {asked.strip()[:400]}"
    if MARK_INSTRUCTION in system:
        text = FINISHED + " " + text
    return {"text": text}


def refused(body: dict) -> str:
    """What the real APIs would refuse in this request, in their words, or ""."""
    if str(body.get("model") or "").startswith("gemini-"):
        for m in body.get("messages") or []:
            for call in m.get("tool_calls") or []:
                if str(call.get("id") or "").startswith("fake-call-") and not (
                        (call.get("extra_content") or {}).get("google") or {}).get("thought_signature"):
                    return "Function call is missing a thought_signature in functionCall parts."
    for m in body.get("messages") or []:
        if m.get("role") not in ("system", "user", "assistant", "tool"):
            return f"Invalid role: {m.get('role')!r}."
    return ""


def build_app(record_dir: str) -> FastAPI:
    app = FastAPI()
    calls = {"n": 0}

    def record(body: dict, provider: str) -> None:
        name = f"compat-{provider}-{time.time():.6f}-{len(os.listdir(record_dir)):03d}.json"
        with open(os.path.join(record_dir, name), "w") as fh:
            json.dump(body, fh, indent=1)

    async def complete(request: Request, provider: str):
        key = request.headers.get("authorization", "")
        if not key.startswith("Bearer test-"):
            return JSONResponse({"error": {"message": "API key not valid. Please pass a valid API key.",
                                           "code": 401, "status": "UNAUTHENTICATED"}}, status_code=401)
        body = await request.json()
        record(body, provider)
        problem = refused(body)
        if problem:
            return JSONResponse({"error": {"message": problem, "code": 400, "status": "INVALID_ARGUMENT"}},
                                status_code=400)
        got = answer_of(body)
        model = str(body.get("model") or "")
        rid = f"chatcmpl-{int(time.time() * 1000)}"
        prompt = sum(len(_words(m.get("content")).split()) for m in body.get("messages") or []) + 50
        usage = {"prompt_tokens": prompt, "completion_tokens": 40, "total_tokens": prompt + 40,
                 "prompt_tokens_details": {"cached_tokens": min(prompt, 1000) if prompt > 1100 else 0}}
        calls["n"] += 1
        if "call" in got:
            name, args = got["call"]
            call = {"index": 0, "id": f"fake-call-{calls['n']}", "type": "function",
                    "function": {"name": name, "arguments": json.dumps(args)}}
            if provider == "google":
                call["extra_content"] = {"google": {"thought_signature": SIGNATURE}}
            pieces, finish = [], "tool_calls"
        else:
            text = got["text"]
            slow = "SLOWLY" in json.dumps(body.get("messages") or [])[-2000:]
            pieces = re.findall(r"\S+\s*", text) if slow else [text[i:i + 24] for i in range(0, len(text), 24)]
            call, finish = None, "stop"
        if not body.get("stream"):
            message = {"role": "assistant", "content": "".join(pieces) or None}
            if call:
                message["tool_calls"] = [{k: v for k, v in call.items() if k != "index"}]
            return JSONResponse({"id": rid, "object": "chat.completion", "created": int(time.time()),
                                 "model": model, "choices": [{"index": 0, "message": message,
                                                              "finish_reason": finish}], "usage": usage})

        async def events():
            def chunk(delta, finish_reason=None, with_usage=False):
                out = {"id": rid, "object": "chat.completion.chunk", "created": int(time.time()),
                       "model": model, "choices": [{"index": 0, "delta": delta, "finish_reason": finish_reason}]}
                if with_usage:
                    out["usage"] = usage
                return f"data: {json.dumps(out)}\n\n"
            yield chunk({"role": "assistant"})
            for piece in pieces:
                yield chunk({"content": piece})
                await asyncio.sleep(0.25 if "SLOWLY" in json.dumps(body.get("messages") or [])[-2000:] else 0.01)
            if call:
                yield chunk({"tool_calls": [call]})
            yield chunk({}, finish)
            if (body.get("stream_options") or {}).get("include_usage"):
                out = {"id": rid, "object": "chat.completion.chunk", "created": int(time.time()),
                       "model": model, "choices": [], "usage": usage}
                yield f"data: {json.dumps(out)}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(events(), media_type="text/event-stream")

    @app.post("/v1beta/openai/chat/completions")
    async def google(request: Request):
        return await complete(request, "google")

    @app.post("/v1/chat/completions")
    async def xai(request: Request):
        return await complete(request, "xai")

    return app


def main() -> None:
    import uvicorn

    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, required=True)
    ap.add_argument("--record", required=True)
    args = ap.parse_args()
    uvicorn.run(build_app(args.record), host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
