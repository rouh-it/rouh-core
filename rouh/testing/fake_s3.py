"""A stand-in for Cloudflare R2 (S3's API), so the weekly copy off the machine can be sent, listed,
fetched and pruned with the real client (boto3, `rouh/offsite.py`) and read back by a check.

Path-style addressing, as `rouh/offsite.py` asks for: ``/<bucket>/<key>``. It answers what the
weekly copy uses - PutObject, the three steps of a multipart upload, HeadObject, GetObject (with
a Range), ListObjectsV2 and DeleteObject - and keeps every object in memory with its metadata. A
request whose signature names another access key id than the one it was started with is refused
with S3's own 403, because keys copied down wrong are the failure worth standing in for. The
signature itself is not checked.

``GET /_objects`` says, as JSON, every object (its size, SHA-256 and metadata) and which access key
ids reached it, for a check; ``GET /_raw/<bucket>/<key>`` hands one back whole.

    python -m rouh.testing.fake_s3 --port 9019
"""
from __future__ import annotations

import argparse
import hashlib
import html
import re
import time
import uuid

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

#: The access key id this stand-in takes, and the one the stack test's settings file gives Rouh.
KEY_ID = "stack-test-key-id"


def _xml(body: str, status: int = 200) -> Response:
    return Response('<?xml version="1.0" encoding="UTF-8"?>\n' + body, status_code=status, media_type="application/xml")


def _error(code: str, message: str, status: int) -> Response:
    return _xml(f"<Error><Code>{code}</Code><Message>{html.escape(message)}</Message></Error>", status)


def _http_date(ts: float) -> str:
    return time.strftime("%a, %d %b %Y %H:%M:%S GMT", time.gmtime(ts))


def _iso(ts: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(ts))


def build_app(key_id: str = KEY_ID) -> FastAPI:
    app = FastAPI()
    objects: dict[tuple[str, str], dict] = {}
    uploads: dict[str, dict] = {}
    seen_keys: list[str] = []

    @app.get("/_objects")
    async def listing():
        return JSONResponse({"keys_seen": sorted(set(seen_keys)), "objects": [
            {"bucket": b, "key": k, "bytes": len(o["body"]), "sha256": hashlib.sha256(o["body"]).hexdigest(),
             "metadata": o["meta"], "at": o["at"]} for (b, k), o in sorted(objects.items())]})

    @app.get("/_raw/{bucket}/{key:path}")
    async def raw(bucket: str, key: str):
        o = objects.get((bucket, key))
        return Response(o["body"], media_type="application/octet-stream") if o else Response(status_code=404)

    @app.api_route("/{bucket}", methods=["GET", "HEAD", "PUT"])
    async def bucket_level(bucket: str, request: Request):
        refused = _who(request)
        if refused:
            return refused
        if request.method == "PUT":
            return Response(status_code=200)
        if request.method == "HEAD":
            return Response(status_code=200)
        prefix = request.query_params.get("prefix", "")
        found = sorted((k, o) for (b, k), o in objects.items() if b == bucket and k.startswith(prefix))
        rows = "".join(f"<Contents><Key>{html.escape(k)}</Key><LastModified>{_iso(o['at'])}</LastModified>"
                       f"<ETag>&quot;{o['etag']}&quot;</ETag><Size>{len(o['body'])}</Size>"
                       "<StorageClass>STANDARD</StorageClass></Contents>" for k, o in found)
        return _xml(f'<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/"><Name>{bucket}</Name>'
                    f"<Prefix>{html.escape(prefix)}</Prefix><KeyCount>{len(found)}</KeyCount><MaxKeys>1000</MaxKeys>"
                    f"<IsTruncated>false</IsTruncated>{rows}</ListBucketResult>")

    @app.api_route("/{bucket}/{key:path}", methods=["GET", "HEAD", "PUT", "POST", "DELETE"])
    async def object_level(bucket: str, key: str, request: Request):
        refused = _who(request)
        if refused:
            return refused
        q = request.query_params
        if request.method == "POST" and "uploads" in q:
            uid = uuid.uuid4().hex
            uploads[uid] = {"bucket": bucket, "key": key, "parts": {}, "meta": _meta(request)}
            return _xml(f"<InitiateMultipartUploadResult><Bucket>{bucket}</Bucket><Key>{html.escape(key)}</Key>"
                        f"<UploadId>{uid}</UploadId></InitiateMultipartUploadResult>")
        if request.method == "PUT" and "uploadId" in q:
            up = uploads.get(q["uploadId"])
            if up is None:
                return _error("NoSuchUpload", "no such upload", 404)
            body = await request.body()
            etag = hashlib.md5(body).hexdigest()
            up["parts"][int(q["partNumber"])] = body
            return Response(status_code=200, headers={"ETag": f'"{etag}"'})
        if request.method == "POST" and "uploadId" in q:
            up = uploads.pop(q["uploadId"], None)
            if up is None:
                return _error("NoSuchUpload", "no such upload", 404)
            wanted = [int(n) for n in re.findall(r"<PartNumber>(\d+)</PartNumber>", (await request.body()).decode())]
            body = b"".join(up["parts"][n] for n in wanted)
            etag = hashlib.md5(body).hexdigest() + f"-{len(wanted)}"
            objects[(bucket, key)] = {"body": body, "meta": up["meta"], "etag": etag, "at": time.time()}
            return _xml(f"<CompleteMultipartUploadResult><Bucket>{bucket}</Bucket><Key>{html.escape(key)}</Key>"
                        f"<ETag>&quot;{etag}&quot;</ETag></CompleteMultipartUploadResult>")
        if request.method == "DELETE" and "uploadId" in q:
            uploads.pop(q["uploadId"], None)
            return Response(status_code=204)
        if request.method == "PUT":
            body = await request.body()
            etag = hashlib.md5(body).hexdigest()
            objects[(bucket, key)] = {"body": body, "meta": _meta(request), "etag": etag, "at": time.time()}
            return Response(status_code=200, headers={"ETag": f'"{etag}"'})
        if request.method == "DELETE":
            objects.pop((bucket, key), None)
            return Response(status_code=204)
        o = objects.get((bucket, key))
        if o is None:
            return _error("NoSuchKey", "The specified key does not exist.", 404) if request.method == "GET" \
                else Response(status_code=404)
        headers = {"ETag": f'"{o["etag"]}"', "Last-Modified": _http_date(o["at"]), "Accept-Ranges": "bytes",
                   **{f"x-amz-meta-{k}": v for k, v in o["meta"].items()}}
        body, status = o["body"], 200
        rng = re.fullmatch(r"bytes=(\d+)-(\d*)", request.headers.get("range", ""))
        if rng:
            start = int(rng.group(1))
            end = int(rng.group(2)) if rng.group(2) else len(body) - 1
            headers["Content-Range"] = f"bytes {start}-{end}/{len(body)}"
            body, status = body[start:end + 1], 206
        if request.method == "HEAD":
            return Response(status_code=200, headers={**headers, "Content-Length": str(len(o["body"]))})
        return Response(body, status_code=status, headers=headers, media_type="application/octet-stream")

    def _who(request: Request) -> Response | None:
        auth = request.headers.get("authorization", "")
        m = re.search(r"Credential=([^/]+)/", auth)
        said = m.group(1) if m else ""
        seen_keys.append(said)
        if said != key_id:
            return _error("InvalidAccessKeyId", "The access key id you provided does not exist in our records.", 403)
        return None

    def _meta(request: Request) -> dict:
        return {k[len("x-amz-meta-"):]: v for k, v in request.headers.items() if k.lower().startswith("x-amz-meta-")}

    return app


def main() -> None:
    import uvicorn

    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=9019)
    a = ap.parse_args()
    uvicorn.run(build_app(), host="127.0.0.1", port=a.port, log_level="warning")


if __name__ == "__main__":
    main()
