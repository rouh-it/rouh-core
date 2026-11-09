"""How busy this machine is, in the few numbers a page can show every few seconds.

`server_health` in tools.py already answers this question for the model, in
prose, with disk and uptime and the running version alongside. This is the
other shape of the same question: three small numbers, cheap enough to ask for
on a timer, for the orb to draw itself against - the rings on the 96 px circle
in the corner and the readout in the corner of the orb opened over the whole
screen. One endpoint answers both (`/api/machine/load` in rouh/web/views.py), so a page
with the circle and the open orb on it polls once, not twice.

Three numbers, and a fourth when there is something to say about it - memory
held by working files nothing is using any more (`leftovers_section`):

- **CPU, as a percentage.** Not the load average: a load of 4 means nothing
  without knowing how many CPUs this box has, and a ring drawn from it is
  drawn from a number that can go past its own end. This is the share of the
  last interval every CPU spent doing something, out of /proc/stat, which is
  what `top` shows and what a person means by "how busy is it".
- **How many processes are running**, which is how many folders /proc has with
  a number for a name.
- **Memory used and total**, from /proc/meminfo, counting MemAvailable as free
  so a healthy Linux box with a warm page cache does not read as full. This is
  the only memory the orb draws a ring for. There used to be another number, what Rouh
  and the one program held between them, read from their control groups for
  a ring of its own inside this one; Petar had that ring taken away on 11
  October 2026 (fr_73b8a5917def), and nothing else read it, so it is no
  longer collected.

And the machine's storage, for the outermost ring (`disk_section`): how full
the disk Rouh runs on is, the very reading `server_health` gives the model, so
the ring and what Rouh says out loud are one answer. A disk fills over hours,
not seconds, so one reading serves every tab for a minute.

And one more, only while it is true: **whether this machine is running on its
battery** (`power_section`). A machine on a UPS watched by NUT,
the Network UPS Tools daemon, and when the mains goes the orb shows a small red
plug at its top right until it comes back.

Every reader has a fallback for a machine without /proc - a laptop - and
`snapshot` reports a reader that fails rather than raising, so one dead number
never takes the others off the screen with it.
"""
from __future__ import annotations

import logging
import os
import socket
import subprocess
import threading
import time
from pathlib import Path

log = logging.getLogger("rouh.machine_load")

#: How long to watch the CPU for when there is no earlier sample to measure
#: against. /proc/stat counts since boot, so a single reading says how busy the
#: machine has been since it was turned on, which is not a number anybody wants
#: on a screen. The first caller waits this long for a second reading; every
#: caller after that is measured against the one before it and waits for
#: nothing.
FIRST_SAMPLE = 0.12

#: Two readings this close together are noise rather than a measurement, so a
#: caller that lands on the heels of another takes a fresh short sample too.
MIN_SPAN = 0.05

#: Everything below shares one pair of counters, so two tabs polling at once
#: cannot each take half of the other's interval.
_LOCK = threading.Lock()
_last: tuple[float, float, float] | None = None      # busy, total, when


def _cpu_times() -> tuple[float, float]:
    """(busy, total) jiffies since boot, off the first line of /proc/stat.

    iowait is idle: the CPU was waiting on a disk, not working. Counting it as
    busy makes a machine that is merely reading a big file look pinned.
    """
    with open("/proc/stat") as fh:
        fields = [float(x) for x in fh.readline().split()[1:]]
    total = sum(fields)
    idle = fields[3] + (fields[4] if len(fields) > 4 else 0.0)
    return total - idle, total


def cpu_percent() -> float:
    """How busy every CPU has been since the last time this was asked.

    0 to 100, one decimal place. On a machine with no /proc/stat the load
    average over one minute stands in for it, spread over the CPUs there are.
    """
    global _last
    try:
        with _LOCK:
            now = _cpu_times()
            at = time.monotonic()
            was = _last
            if was is None or at - was[2] < MIN_SPAN or now[1] <= was[1]:
                time.sleep(FIRST_SAMPLE)
                was = (now[0], now[1], at)
                now, at = _cpu_times(), time.monotonic()
            _last = (now[0], now[1], at)
            span = now[1] - was[1]
            if span <= 0:
                return 0.0
            return round(max(0.0, min((now[0] - was[0]) / span * 100.0, 100.0)), 1)
    except OSError:
        one = os.getloadavg()[0]
        return round(max(0.0, min(one / (os.cpu_count() or 1) * 100.0, 100.0)), 1)


def process_count() -> int:
    """How many processes exist right now."""
    try:
        return sum(1 for name in os.listdir("/proc") if name.isdigit())
    except OSError:
        out = subprocess.run(["ps", "-A", "-o", "pid="], capture_output=True,
                             text=True, timeout=5)
        return sum(1 for line in out.stdout.splitlines() if line.strip())


def _memory_totals() -> tuple[int, int]:
    """(total, free) bytes of this machine's memory, from /proc/meminfo.

    Its own function because two readers want it and neither may be the other
    one's way of getting it: `leftovers_section` needs the same total to
    measure the loose files against, and if it asked `memory_section` for it
    then one unreadable file would take two numbers off the screen instead of
    one.

    MemAvailable, not MemFree. MemFree counts the page cache as used and so
    makes every healthy Linux box sound like it is out of memory.
    """
    try:
        with open("/proc/meminfo") as fh:
            values = {}
            for line in fh:
                name, _, rest = line.partition(":")
                number = rest.split()
                if number:
                    values[name] = int(number[0]) * 1024      # the file is in kB
        return values["MemTotal"], values.get("MemAvailable", values["MemFree"])
    except Exception:
        out = subprocess.run(["free", "-b"], capture_output=True, text=True, timeout=5)
        fields = out.stdout.splitlines()[1].split()
        return int(fields[1]), int(fields[-1])


def memory_section() -> dict:
    """What memory is in this machine and how much of it is spoken for."""
    total, free = _memory_totals()
    used = max(total - free, 0)
    return {
        "total_bytes": total,
        "used_bytes": used,
        "free_bytes": free,
        "percent_used": round(used / total * 100, 1) if total else 0.0,
    }


#: How long a leftover world may sit in the scratch filesystem before it counts
#: as loose. The same ceiling the one program's reaper sweeps on
#: (``ONE_SCRATCH_AFTER``), read from the environment so the number drawn here
#: and the number acted on there can never be two different numbers.
def _scratch_after() -> float:
    try:
        return float(os.environ.get("ONE_SCRATCH_AFTER") or 6 * 3600)
    except ValueError:
        return 6 * 3600.0


def leftovers_section() -> dict | None:
    """Memory held by working files that nothing is using any more.

    On this machine ``/tmp`` is a tmpfs: a filesystem that lives in memory and
    nowhere else. Proving a change fills it - the harness stands a whole world
    up under ``tempfile.mkdtemp`` for every world it serves - and none of it is
    given back when the run ends, because ending a run frees processes and not
    files. On 22 September 2026 that was 7.9 GB of this machine's memory in
    folders belonging to runs whose checkouts had been deleted days earlier,
    and nothing anywhere could see it: the orb drew it as part of the memory
    in use with no way to tell it from work being done.

    So it has a line of its own. What is drawn is the part the one program's
    reaper would delete - old enough, and held open by nobody - which is memory
    that is certainly going to come back, as opposed to a world a browser is
    being driven at this second. A line that reads zero is a machine with
    nothing to reclaim; a line that grows is the leak visible before it hurts.

    The rules come from ``one/reaper.py`` rather than being written again here,
    because the number on this screen has to be the number the sweep acts on.
    None where there is no such filesystem to read - a laptop, where /tmp is a
    disk and a leftover folder costs nothing that matters.

    Walking /tmp costs about a third of a second of Python, and every open tab
    asks every three seconds: with three tabs open that was a third of what
    the server could do, spent counting files, and the conversation a page was
    opening waited behind it (23 October 2026). What is left over changes over
    minutes, so one count serves every tab for `LEFTOVERS_FRESH` seconds.
    """
    global _leftovers
    with _LEFTOVERS_LOCK:
        now = time.monotonic()
        if _leftovers and now - _leftovers[0] < LEFTOVERS_FRESH:
            return _leftovers[1]
        found = _leftovers_now()
        _leftovers = (time.monotonic(), found)
        return found


#: How long one count of /tmp's leftovers is the answer (`leftovers_section`).
LEFTOVERS_FRESH = 60.0
_leftovers: tuple[float, dict | None] | None = None
_LEFTOVERS_LOCK = threading.Lock()


def _leftovers_now() -> dict | None:
    try:
        from one import reaper
    except Exception:
        return None
    where = Path(os.environ.get("ONE_SCRATCH_TMP") or "/tmp")
    found = reaper.scratch_report(where, _scratch_after())
    if not found.get("tmpfs"):
        return None           # on disk: real, and not memory, so not this ring
    total, _ = _memory_totals()
    found["percent_used"] = round(found["loose_bytes"] / total * 100, 1) if total else 0.0
    return found


#: The UPS NUT watches, and the command that asks it. Both can be pointed
#: elsewhere: a test world points ROUH_UPSC at a stand-in that answers
#: "OB DISCHRG", so the plug can be seen without anybody unplugging anything.
UPS_NAME = os.environ.get("ROUH_UPS") or "ups@localhost"
UPSC = os.environ.get("ROUH_UPSC") or "upsc"

#: Every tab polls every three seconds; one answer serves them all for this long.
POWER_FRESH = 2.0
_power: tuple[float, dict | None] | None = None
_POWER_LOCK = threading.Lock()


def _ups_variables() -> dict[str, str]:
    """Every variable NUT has for the UPS, as `upsc` prints them ("name: value").

    Where there is no `upsc` - a container, which has no NUT of its own - NUT's network protocol is
    spoken here instead, to the upsd ROUH_UPS names (ups@host:port; in the containers the machine's
    own, ups@host.docker.internal, deploy/stack/settings.env.example), which reads the same."""
    import shutil

    if not os.path.isabs(UPSC) and shutil.which(UPSC) is None:
        return _ups_over_network(UPS_NAME)
    out = subprocess.run([UPSC, UPS_NAME], capture_output=True, text=True, timeout=2)
    found = {}
    for line in out.stdout.splitlines():
        name, sep, value = line.partition(":")
        if sep:
            found[name.strip()] = value.strip()
    return found


def _ups_over_network(name: str, timeout: float = 2.0) -> dict[str, str]:
    """`LIST VAR <ups>` to upsd on port 3493 (or the one named), its `VAR <ups> <name> "<value>"`
    lines read until `END LIST VAR`."""
    import shlex

    ups, _, where = name.partition("@")
    host, _, port = (where or "localhost").partition(":")
    found: dict[str, str] = {}
    with socket.create_connection((host, int(port or 3493)), timeout=timeout) as conn:
        conn.sendall(f"LIST VAR {ups}\n".encode())
        buf = b""
        while b"END LIST VAR" not in buf and b"ERR" not in buf[:8]:
            piece = conn.recv(65536)
            if not piece:
                break
            buf += piece
            if len(buf) > 1 << 20:
                break
        conn.sendall(b"LOGOUT\n")
    for line in buf.decode("utf-8", "replace").splitlines():
        if line.startswith("VAR "):
            parts = shlex.split(line)
            if len(parts) >= 4:
                found[parts[2]] = parts[3]
    return found


def power_section() -> dict | None:
    """Whether the machine is on its UPS battery, and how full that is.

    NUT's ups.status is a row of flags: OL on mains, OB on battery, LB once the
    battery is low (and upsmon is about to shut the machine down), with CHRG,
    DISCHRG and others beside them. On battery means OB is among them.

    None whenever there is nothing certain to say - no NUT on this machine, upsd
    not answering, no such UPS, no status - because the orb shows nothing then
    rather than an error. Never raises, and says nothing in the log: on a
    laptop with no NUT this is asked every three seconds.
    """
    global _power
    with _POWER_LOCK:
        now = time.monotonic()
        if _power and now - _power[0] < POWER_FRESH:
            return _power[1]
        answer = None
        try:
            found = _ups_variables()
            flags = found.get("ups.status", "").split()
            if flags:
                charge = None
                try:
                    charge = round(float(found["battery.charge"]))
                except (KeyError, ValueError):
                    pass
                answer = {"on_battery": "OB" in flags, "low": "LB" in flags,
                          "charge": charge, "status": " ".join(flags),
                          "host": socket.gethostname()}
        except Exception:
            answer = None
        _power = (time.monotonic(), answer)
        return answer


#: How long one reading of the disk is the answer. A disk fills over hours; the
#: ring is asked every three seconds by every tab, and once a minute is plenty.
DISK_FRESH = 60.0
_disk: tuple[float, dict] | None = None
_DISK_LOCK = threading.Lock()


def disk_reading(path: str = "/") -> dict:
    """How full the disk under `path` is, read now: the one way of asking.

    `server_health` (tools.py) says it in words off this same reading, and the
    orb's outer ring draws it, so the two can never be two answers.
    """
    import shutil

    try:
        total, used, free = shutil.disk_usage(path)
    except Exception:
        # -B1 prints bytes, so there is no unit suffix to guess at.
        out = subprocess.run(["df", "-B1", path], capture_output=True, text=True, timeout=5)
        fields = out.stdout.splitlines()[1].split()
        total, used, free = int(fields[1]), int(fields[2]), int(fields[3])
    return {
        "path": path,
        "total_bytes": total,
        "used_bytes": used,
        "free_bytes": free,
        "percent_used": round(used / total * 100, 1) if total else 0.0,
    }


def disk_section() -> dict:
    """The disk Rouh runs on, for the orb's outer ring, read at most once a minute."""
    global _disk
    with _DISK_LOCK:
        now = time.monotonic()
        if _disk and now - _disk[0] < DISK_FRESH:
            return _disk[1]
        found = disk_reading("/")
        _disk = (time.monotonic(), found)
        return found


def snapshot() -> dict:
    """The numbers, with whatever could be read.

    A reader that fails leaves its number out and says why under `errors`,
    rather than raising: a machine with no /proc/meminfo should still show its
    CPU, and the page draws whichever numbers it was given.
    """
    out: dict = {"at": time.time(), "cpu_count": os.cpu_count() or 1}
    errors = {}
    for key, collect in (
        ("cpu_percent", cpu_percent),
        ("processes", process_count),
        ("memory", memory_section),
        ("disk", disk_section),
        ("leftovers", leftovers_section),
        ("power", power_section),
    ):
        try:
            out[key] = collect()
        except Exception as exc:
            log.warning("machine load: could not read %s: %s", key, exc)
            out[key] = None
            errors[key] = f"{type(exc).__name__}: {exc}"
    if errors:
        out["errors"] = errors
    return out
