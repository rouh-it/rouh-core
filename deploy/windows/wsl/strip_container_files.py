#!/usr/bin/env python3
"""A docker export on stdin, as a WSL root file system on stdout: the same tar, without what only a
container has. /.dockerenv makes systemd (and Rouh's own checks) believe they run inside Docker;
/etc/hostname, /etc/hosts and /etc/resolv.conf are Docker's, and WSL writes its own (wsl.conf)."""
import sys
import tarfile

DROP = {".dockerenv", "etc/hostname", "etc/hosts", "etc/resolv.conf"}

src = tarfile.open(fileobj=sys.stdin.buffer, mode="r|")
dst = tarfile.open(fileobj=sys.stdout.buffer, mode="w|", format=tarfile.PAX_FORMAT)
kept = dropped = 0


def plain(name: str) -> str:
    while name.startswith("./"):
        name = name[2:]
    return name.lstrip("/")


for m in src:
    if plain(m.name) in DROP:
        dropped += 1
        continue
    dst.addfile(m, src.extractfile(m) if m.isreg() else None)
    kept += 1
dst.close()
print(f"root file system: {kept} entries, {dropped} of the container's own left out", file=sys.stderr)
