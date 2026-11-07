"""The Rouh's side of its protected core: a small client for the guard's socket.

Task 98, step 98-23 (24 October 2026). A Rouh in a container has a protected core beside it, the
``guard`` service of the ``rouh-guard`` image, which it uses and cannot edit (``guard/README.md``).
The Rouh never imports it: it asks over one socket, ``/run/guard/guard.sock`` (``ROUH_GUARD_SOCKET``),
one line of JSON a request and one a reply, the **changes contract**, number 1:

    status                     the core's version and contracts, the undo point that runs, the doctor
    points                     every undo point, newest first
    propose {commit, why}      check a commit of /code and, if it passes, make it the code that runs
    undo {point}               put /code back to an undo point
    gene {fn, ...}             the signature checks on a shared gene (rouh_guard/geneverify.py)

A Rouh with no protected core beside it - the server it runs on, a test world, a checkout - has
no socket. There the gene checks are read from the repository's own ``guard/`` folder, and the
change calls say plainly that there is no protected core here.
"""
from __future__ import annotations

import base64
import json
import os
import socket
import sys
from pathlib import Path

#: The changes contract this client speaks.
CONTRACT = 1


def socket_path() -> str:
    return os.environ.get("ROUH_GUARD_SOCKET", "/run/guard/guard.sock")


class Refused(ValueError):
    """The protected core said no, with the reason as a sentence."""


class Unavailable(RuntimeError):
    """There is no protected core to ask, or it did not answer."""


def here() -> bool:
    """Whether this Rouh has a protected core beside it."""
    return os.path.exists(socket_path())


def ask(op: str, *, timeout: float = 30.0, **fields) -> dict:
    """One request over the socket; the reply, or Refused / Unavailable."""
    path = socket_path()
    if not os.path.exists(path):
        raise Unavailable("This Rouh has no protected core beside it.")
    line = json.dumps({"op": op, "contract": CONTRACT, **fields}, ensure_ascii=False) + "\n"
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            s.connect(path)
            s.sendall(line.encode())
            got = bytearray()
            while not got.endswith(b"\n"):
                chunk = s.recv(1 << 20)
                if not chunk:
                    break
                got.extend(chunk)
    except (OSError, socket.timeout) as exc:
        raise Unavailable(f"The protected core did not answer ({type(exc).__name__}).") from None
    try:
        reply = json.loads(got.decode() or "{}")
    except ValueError:
        raise Unavailable("The protected core's answer could not be read.") from None
    if reply.get("ok"):
        return reply
    if reply.get("refused"):
        raise Refused(str(reply["refused"]))
    raise Unavailable(str(reply.get("error") or "The protected core could not do that."))


# --- the gene checks ---------------------------------------------------------------------------


def _local():
    """The gene checks from the repository's own guard/, where there is no protected core."""
    for root in (Path(__file__).resolve().parents[1] / "guard", Path("/opt/rouh-guard")):
        if (root / "rouh_guard" / "geneverify.py").is_file():
            if str(root) not in sys.path:
                sys.path.insert(0, str(root))
            from rouh_guard import geneverify

            return geneverify
    raise Unavailable("The gene checks are not on this machine: there is no protected core beside "
                      "this Rouh and no guard/ folder in its code.")


def _b64(data: bytes) -> str:
    return base64.b64encode(bytes(data)).decode()


def gene(fn: str, **kw):
    """One of the gene checks, by name: key_of, verify_pem, url_ok, fetch, sigstore_check, unpack.
    Bytes go in and come out as bytes."""
    if not here():
        g = _local()
        try:
            return getattr(g, fn)(**kw)
        except g.Refused as exc:
            raise Refused(str(exc)) from None
    wire = {k + "_b64" if isinstance(v, (bytes, bytearray)) else k: _b64(v) if isinstance(v, (bytes, bytearray)) else v
            for k, v in kw.items()}
    reply = ask("gene", fn=fn, timeout=120.0, **wire)
    if "value_b64" in reply:
        return base64.b64decode(reply["value_b64"])
    if "files_b64" in reply:
        return {p: base64.b64decode(b) for p, b in reply["files_b64"].items()}
    return reply.get("value")
