"""A stand-in for YouTube's Data API v3, so YouTube search can be driven with nothing real.

The same idea as `fake_stripe.py`: a real HTTP server in front of the real client
(`rouh/youtube.py`, `search_api`), so what a check proves is what went over the wire. It
speaks the two calls a search makes, in their shapes:

- ``GET /search?part=snippet&q=...&type=video&key=...``: three made-up videos about
  whatever was asked, newest first;
- ``GET /videos?part=contentDetails,statistics&id=a,b,c&key=...``: each one's length and
  view count, which search.list leaves out.

A key other than ``KEY`` is refused with the API's own 400, ``keyInvalid``. ``GET /_calls``
lists every call, oldest first, with what it asked for.

Point ``ROUH_YOUTUBE_API`` at it and give ``YOUTUBE_API_KEY`` the stand-in's key.

    python -m rouh.testing.fake_youtube --port 8098
"""
from __future__ import annotations

import argparse
import hashlib
import time

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

#: The one key this stand-in takes.
KEY = "AIza-test-key-not-a-real-one"


def _video_id(query: str, n: int) -> str:
    """An id shaped like YouTube's, eleven characters, the same for the same question."""
    return hashlib.sha256(f"{query}:{n}".encode()).hexdigest()[:11]


def build_app() -> FastAPI:
    app = FastAPI()
    calls: list[dict] = []

    def refused(request: Request):
        if request.query_params.get("key") == KEY:
            return None
        return JSONResponse({"error": {"code": 400, "message": "API key not valid. Please pass a valid API key.",
                                       "errors": [{"reason": "keyInvalid", "message": "Bad Request"}]}},
                            status_code=400)

    @app.get("/search")
    async def search(request: Request):
        calls.append({"path": "/search", "q": request.query_params.get("q", ""), "at": time.time()})
        no = refused(request)
        if no is not None:
            return no
        query = request.query_params.get("q", "")
        count = min(int(request.query_params.get("maxResults") or 3), 3)
        return {"kind": "youtube#searchListResponse", "items": [
            {"kind": "youtube#searchResult",
             "id": {"kind": "youtube#video", "videoId": _video_id(query, n)},
             "snippet": {"title": f"{query.title()}, part {n}", "channelTitle": "Example Channel",
                         "publishedAt": f"2026-10-{20 - n:02d}T09:00:00Z",
                         "description": f"Part {n} of a made-up series about {query}."}}
            for n in range(1, count + 1)]}

    @app.get("/videos")
    async def videos(request: Request):
        ids = [one for one in request.query_params.get("id", "").split(",") if one]
        calls.append({"path": "/videos", "id": ids, "at": time.time()})
        no = refused(request)
        if no is not None:
            return no
        return {"kind": "youtube#videoListResponse", "items": [
            {"id": one, "contentDetails": {"duration": f"PT{4 + n}M30S"},
             "statistics": {"viewCount": str(1000 * (n + 1))}} for n, one in enumerate(ids)]}

    @app.get("/_calls")
    async def seen():
        return calls

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=8098)
    args = parser.parse_args()
    import uvicorn

    uvicorn.run(build_app(), host="127.0.0.1", port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
