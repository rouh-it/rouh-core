"""rouh.land, with its release changed by one character after it was signed: what a tampered or
substituted release looks like to install.sh. Everything else is passed on as rouh.land serves it."""
import json, sys, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def get(path):
    req = urllib.request.Request("https://rouh.land" + path, headers={"User-Agent": "rouh-proof-176-24"})
    with urllib.request.urlopen(req) as r:
        return r.read()


class H(BaseHTTPRequestHandler):
    def do_GET(self):
        body = get(self.path)
        if self.path.startswith("/mac/release/stable.json"):
            env = json.loads(body)
            env["payload"] = env["payload"].replace('"channel":"stable"', '"channel":"stablE"', 1)
            body = json.dumps(env).encode()
        self.send_response(200)
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1])), H).serve_forever()
