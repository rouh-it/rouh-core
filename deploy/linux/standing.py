"""The host's own login for the switch on the Permissions page, put in by Rouh's setup (task 191).

Petar, 20 November 2026: "why do we need to update rouh-open? this should be a default
functionality for all rouhs that get setup from scratch". The switch (`rouh/unrestricted.py`)
hands the owner's own runs, while it is Unrestricted, five things: the internet, GitHub as the
owner, and the ssh of the owner's servers. On a Linux server the one server every Rouh has is the
machine it runs on, so `rouh` (install and every update, by hand or at night) makes that one ready
by itself, with nothing to run on a Mac:

1. the worker's standing key, ``~/.ssh/jobs-standing`` in its home volume, made if it is not there;
2. one line of that key for the account that installed Rouh, from the key proxy's network only
   (``from=`` the stack's egress subnet), with no end, written by `deploy/grants/servers/rouh-jobs-keys`
   ``standing`` into ``/etc/ssh/rouh-standing/<account>``, a root-owned file sshd reads beside the
   account's own keys and which no close, lock or prune of a timed key ever writes;
3. the host in ``standing_access.json`` in the keys volume (its address on that network and its
   ssh port), so the key proxy lets the owner's Unrestricted runs, and nobody else's, reach it;
4. ``Host rouh-host`` in the worker's ssh settings, so a run reaches it as ``ssh rouh-host``.

The key proxy gives it to nobody while the switch is Restricted, and to no run that is not the
owner's own (`guard/rouh_guard/keyproxy.py`). It is skipped, and says why, when sudo would ask a
password (the nightly update then leaves it for the next ``rouh update`` in a terminal), when the
settings file says ``ROUH_STANDING_HOST=0``, or when the owner turned the host off with
``rouh-grant standing revoke`` (an entry that is ``off`` is never turned back on here).
"""
from __future__ import annotations

import getpass
import ipaddress
import json
import re
import subprocess
from pathlib import Path

import common
from common import CORE, compose, run, setting

HELPER = CORE / "deploy" / "grants" / "servers" / "rouh-jobs-keys"
KEY_LINE = re.compile(r"^(ssh-ed25519) ([A-Za-z0-9+/]+=*)(?: \S+)?$")
ALIAS = "rouh-host"

# Run in the core's container, as the core's own user: the host's entry merged into the record the
# key proxy reads, the rest of it kept. Prints "off" when the owner turned the host off.
MERGE = r"""
import json, os, sys, time
path = "/keys/standing_access.json"
address, port = sys.argv[1], int(sys.argv[2])
try:
    data = json.load(open(path))
except (OSError, ValueError):
    data = {}
data = data if isinstance(data, dict) else {}
servers = [e for e in data.get("servers") or [] if isinstance(e, dict)]
mine = [e for e in servers if e.get("item") == "host"]
if any(e.get("off") for e in mine):
    print("off"); sys.exit(0)
keep = [e for e in servers if e.get("item") != "host"]
entry = {"name": "host", "item": "host", "addresses": [address], "ports": [port], "off": False,
         "since": int((mine[0] if mine else {}).get("since") or time.time()), "source": "rouh-setup"}
if mine and mine[0].get("addresses") == [address] and mine[0].get("ports") == [port]:
    print("same"); sys.exit(0)
data.update(format=1, written=int(time.time()), servers=keep + [entry])
data.setdefault("github", None)
tmp = path + ".setup.new"
with open(tmp, "w") as fh:
    json.dump(data, fh, indent=1)
try:
    os.chown(tmp, -1, 10002)  # the key proxy's group (deploy/stack/compose.yml)
except OSError:
    pass
os.chmod(tmp, 0o640)
os.replace(tmp, path)
print("written")
"""

SSH_BLOCK = """# >>> rouh-host, written by Rouh's setup (deploy/linux/standing.py): this machine itself,
# reached through the key proxy only by the owner's own runs while Permissions is Unrestricted.
Host {alias}
  HostName {address}
  Port {port}
  User {user}
  IdentityFile ~/.ssh/jobs-standing
  IdentitiesOnly yes
# <<< rouh-host
"""


def _out(r: subprocess.CompletedProcess) -> str:
    return ((r.stdout or b"") + (r.stderr or b"")).decode(errors="replace").strip()


def egress() -> tuple[str, str] | None:
    """(the egress network's gateway, which is this machine on it; its subnet), or None."""
    r = run(["docker", "network", "inspect", f"{common.PROJECT}_egress", "--format", "{{json .IPAM.Config}}"], timeout=30)
    if r.returncode:
        return None
    try:
        for c in json.loads(r.stdout or b"[]") or []:
            gw, net = str(c.get("Gateway") or ""), str(c.get("Subnet") or "")
            if gw and net and ipaddress.ip_address(gw).version == 4:
                ipaddress.ip_network(net)
                return gw, net
    except (ValueError, TypeError, AttributeError):
        return None
    return None


def sshd_port() -> int:
    r = run(["sudo", "-n", "sshd", "-T"], timeout=30)
    for line in _out(r).splitlines():
        k, _, v = line.partition(" ")
        if k.lower() == "port" and v.strip().isdigit():
            return int(v.strip())
    return 22


def worker_key() -> tuple[str, str] | None:
    """(type, body) of the worker's standing key, made first if it is not there yet."""
    r = run(compose("exec", "-T", "worker", "sh", "-c",
                    'k="$HOME/.ssh/jobs-standing"; mkdir -p "$HOME/.ssh" && chmod 700 "$HOME/.ssh"; '
                    '[ -s "$k.pub" ] || ssh-keygen -q -t ed25519 -N "" -C rouh-jobs-standing -f "$k" </dev/null; '
                    'cat "$k.pub"'), timeout=60)
    m = KEY_LINE.match(_out(r).splitlines()[-1].strip()) if r.returncode == 0 and _out(r) else None
    return (m.group(1), m.group(2)) if m else None


def worker_ssh(address: str, port: int, user: str) -> bool:
    """Our block at the top of the worker's ssh settings, in place of an earlier one of ours."""
    block = SSH_BLOCK.format(alias=ALIAS, address=address, port=port, user=user)
    script = ('c="$HOME/.ssh/config"; touch "$c"; '
              'sed -e "/^# >>> rouh-host/,/^# <<< rouh-host/d" "$c" > "$c.rest" && '
              'cat - "$c.rest" > "$c.new" && chmod 600 "$c.new" && mv "$c.new" "$c"; rm -f "$c.rest"')
    r = run(compose("exec", "-T", "worker", "sh", "-c", script), input=block.encode(), timeout=60)
    return r.returncode == 0


def ensure() -> str:
    """Make the host's own login ready for the switch, or say in words why it was left."""
    if setting("ROUH_STANDING_HOST") == "0":
        return "The host's login for the switch: off in the settings file (ROUH_STANDING_HOST=0)."
    user = getpass.getuser()
    if user == "root" or not re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}", user):
        return "The host's login for the switch: skipped, Rouh was not installed by an account of its own."
    if not HELPER.is_file():
        return "The host's login for the switch: waits for a newer updater (rouh update brings it)."
    if run(["sudo", "-n", "true"], timeout=20).returncode:
        return "The host's login for the switch: waits for sudo. Run rouh update in a terminal once."
    net = egress()
    if net is None:
        return "The host's login for the switch: the stack's network was not found; rouh doctor says why."
    gateway, subnet = net
    key = worker_key()
    if key is None:
        return "The host's login for the switch: the worker's standing key could not be read; rouh logs worker says why."
    ktype, kbody = key
    r = run(["sudo", "-n", "env", f"ROUH_JOBS_KEYS_USER={user}", "bash", str(HELPER), "standing", "host",
             subnet, ktype, kbody, "rouh-jobs-standing"], timeout=120)
    if r.returncode:
        return "The host's login for the switch: not written: " + (_out(r).splitlines() or ["?"])[-1]
    port = sshd_port()
    m = run(compose("exec", "-T", "-u", "10001:10002", "core", "python", "-c", MERGE, gateway, str(port)), timeout=60)
    said = _out(m).splitlines()[-1] if _out(m) else ""
    if said == "off":
        return "The host's login for the switch: you turned it off (rouh-grant standing revoke), so it stays off."
    if m.returncode or said not in ("written", "same"):
        return "The host's login for the switch: the keys volume could not be written: " + (said or "?")
    worker_ssh(gateway, port, user)
    return (f"The host's login for the switch: ready. Your own runs reach this machine as {user} "
            f"(ssh {ALIAS}) only while Permissions is Unrestricted.")


def main() -> int:
    print(ensure())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
