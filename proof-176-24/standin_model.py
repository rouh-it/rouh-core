"""A stand-in for Anthropic's API, on 0.0.0.0:18080, so a real install's key check gets a real answer
with no real key: GET /v1/models, POST /v1/messages (plain or streamed). A key with WRONG in it is
refused as Anthropic refuses an unknown key. Standard library only. Task 176, step 176-24 (proof)."""
import json, sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LOG = open(sys.argv[1] if len(sys.argv) > 1 else "standin.log", "a", buffering=1)


class H(BaseHTTPRequestHandler):
    def _key_bad(self):
        k = self.headers.get("x-api-key") or self.headers.get("authorization", "")
        if "WRONG" in k:
            self._json(401, {"type": "error", "error": {"type": "authentication_error", "message": "invalid x-api-key"}})
            return True
        return False

    def _json(self, code, doc):
        b = json.dumps(doc).encode()
        self.send_response(code)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        LOG.write(f"GET {self.path}\n")
        if self._key_bad():
            return
        self._json(200, {"data": [{"type": "model", "id": m, "display_name": m, "created_at": "2026-01-01T00:00:00Z"}
                                  for m in ("claude-haiku-4-5", "claude-sonnet-4-5", "claude-opus-5-5")],
                         "has_more": False, "first_id": "claude-haiku-4-5", "last_id": "claude-opus-5-5"})

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("content-length") or 0)) or b"{}")
        LOG.write(f"POST {self.path} {json.dumps(body)[:2000]}\n")
        if self._key_bad():
            return
        model = body.get("model", "claude-haiku-4-5")
        msg = {"id": "msg_standin", "type": "message", "role": "assistant", "model": model,
               "content": [{"type": "text", "text": "OK"}], "stop_reason": "end_turn", "stop_sequence": None,
               "usage": {"input_tokens": 5, "output_tokens": 1}}
        if not body.get("stream"):
            return self._json(200, msg)
        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.end_headers()
        start = {**msg, "content": [], "stop_reason": None, "usage": {"input_tokens": 5, "output_tokens": 0}}
        for ev, data in (("message_start", {"type": "message_start", "message": start}),
                         ("content_block_start", {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}}),
                         ("content_block_delta", {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "OK"}}),
                         ("content_block_stop", {"type": "content_block_stop", "index": 0}),
                         ("message_delta", {"type": "message_delta", "delta": {"stop_reason": "end_turn", "stop_sequence": None}, "usage": {"output_tokens": 1}}),
                         ("message_stop", {"type": "message_stop"})):
            self.wfile.write(f"event: {ev}\ndata: {json.dumps(data)}\n\n".encode())
        self.wfile.flush()

    def log_message(self, *a):
        pass


ThreadingHTTPServer(("0.0.0.0", 18080), H).serve_forever()
