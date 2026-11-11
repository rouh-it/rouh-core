"""The guard's socket: the changes contract, one line of JSON a request and one a reply.

    {"op": "status"}                          the core's version, contracts, undo point, doctor
    {"op": "points"}                          every undo point, newest first
    {"op": "propose", "commit", "why"}        check a commit of /code; if it passes, run it
    {"op": "undo", "point"}                   put /code back to an undo point
    {"op": "verify", "who"}                   the start scripts ask: may this /code run?
    {"op": "gene", "fn", ...}                 the signature checks on a shared gene
    {"op": "upstream"}                        the Creator Rouh's push (upstream.py): on or off, its
                                              key's public half, what was pushed; "fetch": true
                                              fetches rouh-core first, "key": true makes the key
    {"op": "push_branch", "commit", "branch"} the Creator Rouh's 00:40 base level, checked, pushed

A reply is {"ok": true, ...}, or {"ok": false, "refused": "<a sentence>"} when the core says no,
or {"ok": false, "error": "<a sentence>"} when it could not do it. Within contract 1 an op or a
field is only ever added. The socket is in the guard-run volume, which only the core mounts; the
worker, where other people's code runs, cannot reach it.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
from pathlib import Path

from . import CONTRACTS, VERSION

log = logging.getLogger("rouh-guard")

#: The largest request line taken: a gene's artifact, base64, and a little more.
MOST_LINE = 64 * 1024 * 1024

GENE_FNS = ("key_of", "verify_pem", "url_ok", "fetch", "sigstore_check", "unpack")


def _gene(req: dict) -> dict:
    from . import geneverify as g

    fn = req.get("fn")
    if fn not in GENE_FNS:
        return {"ok": False, "refused": f"there is no gene check called {str(fn)[:40]!r}"}
    kw = {}
    for k, v in req.items():
        if k in ("op", "fn", "contract"):
            continue
        kw[k[:-4] if k.endswith("_b64") else k] = base64.b64decode(v) if k.endswith("_b64") else v
    try:
        value = getattr(g, fn)(**kw)
    except g.Refused as exc:
        return {"ok": False, "refused": str(exc)}
    except TypeError as exc:
        return {"ok": False, "refused": f"the gene check {fn} was asked wrongly: {exc}"}
    if isinstance(value, (bytes, bytearray)):
        return {"ok": True, "value_b64": base64.b64encode(bytes(value)).decode()}
    if fn == "unpack":
        return {"ok": True, "files_b64": {p: base64.b64encode(b).decode() for p, b in value.items()}}
    return {"ok": True, "value": value}


class Server:
    def __init__(self, path: str, changes=None, doctor=None, upstream=None):
        self.path = path
        self.changes = changes
        self.doctor = doctor
        self.upstream = upstream

    def status(self) -> dict:
        out = {"ok": True, "version": VERSION, "contracts": CONTRACTS,
               "features": {"master_changes": 1, "database_rehearsal": 1}}
        if self.changes is not None:
            out.update(self.changes.status())
        if self.doctor is not None:
            out["doctor"] = self.doctor.status()
        if self.upstream is not None:
            out["upstream"] = self.upstream.status()
        return out

    async def answer(self, req: dict) -> dict:
        op = req.get("op")
        contract = req.get("contract", 1)
        if contract not in CONTRACTS["changes"]:
            return {"ok": False, "refused": f"this protected core speaks changes contract "
                                            f"{', '.join(map(str, CONTRACTS['changes']))}, not {contract}"}
        if op == "status":
            return self.status()
        if op == "gene":
            return await asyncio.to_thread(_gene, req)
        if op == "database_inventory":
            from . import database_update

            return {"ok": True, **await asyncio.to_thread(database_update.inventory)}
        if self.changes is None:
            return {"ok": False, "error": "this protected core keeps no undo points here"}
        if op == "points":
            return {"ok": True, "points": self.changes.points()}
        if op == "propose":
            return await self.changes.propose(str(req.get("commit") or ""), str(req.get("why") or "")[:500],
                                              by=str(req.get("by") or "the Rouh")[:80], update=req.get("update"))
        if op == "undo":
            return await self.changes.undo(req.get("point"), by=str(req.get("by") or "the Rouh")[:80])
        if op == "verify":
            return await self.changes.verify(str(req.get("who") or "")[:20])
        if op in ("upstream", "push_branch"):
            up = self.upstream
            if up is None or not up.on:
                return {"ok": False, "refused": "this Rouh pushes nowhere: only the Creator Rouh sets ROUH_GUARD_UPSTREAM"}
            if op == "push_branch":
                return await up.push_branch(str(req.get("commit") or ""), str(req.get("branch") or ""),
                                            str(req.get("why") or "")[:300])
            out = {"ok": True}
            if req.get("key"):
                out["key"] = await asyncio.to_thread(up.make_key)
            if req.get("fetch"):
                if not up.key.is_file():
                    return {"ok": False, "refused": "the protected core has no key for rouh-core yet (rouh-guard upstream-key)"}
                async with up.lock:
                    got = await asyncio.to_thread(up.fetch)
                if not got["ok"]:
                    return got
            out.update(up.status())
            return out
        return {"ok": False, "refused": f"there is no {str(op)[:40]!r} in the changes contract"}

    async def _client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            while True:
                line = await reader.readline()
                if not line:
                    break
                try:
                    req = json.loads(line)
                    if not isinstance(req, dict):
                        raise ValueError
                except ValueError:
                    reply = {"ok": False, "error": "a request is one line of JSON"}
                else:
                    try:
                        reply = await self.answer(req)
                    except Exception as exc:  # noqa: BLE001 - said, never a dropped connection
                        log.exception("the request %s broke", req.get("op"))
                        reply = {"ok": False, "error": f"the protected core broke on it: {type(exc).__name__}"}
                writer.write((json.dumps(reply, ensure_ascii=False) + "\n").encode())
                await writer.drain()
        except (ConnectionError, asyncio.LimitOverrunError, ValueError):
            pass
        finally:
            writer.close()

    async def serve(self) -> None:
        p = Path(self.path)
        p.parent.mkdir(parents=True, exist_ok=True)
        if p.exists() or p.is_symlink():
            p.unlink()
        server = await asyncio.start_unix_server(self._client, path=str(p), limit=MOST_LINE)
        os.chmod(p, 0o666)
        log.info("the protected core %s answers on %s", VERSION, p)
        async with server:
            await server.serve_forever()
