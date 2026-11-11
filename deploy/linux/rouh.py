#!/usr/bin/env python3
"""rouh: the owner's command for Rouh on a Linux server (task 176, step 176-24).

Installed as /usr/local/bin/rouh by https://rouh.land/install.sh. A thin layer over
deploy/container/linux_stack.py (the signed releases, the stack check, the go-back) and Docker
Compose, so there is one engine and this only says it in plain words.

    rouh status                  is it running, which release, its address, updates, backups, its AI
    rouh setup                   the first run, in this terminal (again, if it was not finished)
    rouh open                    a one-time sign-in link: your domain, rouh.page, or an SSH tunnel
    rouh update [--off|--on]     update now; or turn the nightly update off or on
    rouh back                    back to the release before
    rouh logs [PART] [-f]        the last lines of Rouh's parts (core by default)
    rouh backup [--list|--restore NAME]
                                 a copy of the database now; the copies there are; put one back
    rouh domain NAME | --off     your own domain, with HTTPS from Let's Encrypt
    rouh relay URL | --default | --off
                                 the relay a Connected Rouh's phone address goes through
    rouh doctor                  checks this server and says what to fix
    rouh uninstall               Keep my data (recommended) or Wipe my data

Add --debug to any of them for the technical detail (commands and their output).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import common  # noqa: E402
from common import (BOLD, CORE, DIM, NO, OK, RESET, WARN, Api, Stop, ask, can_ask, code_status,  # noqa: E402
                    compose, core_healthy, has_stack, heading, kept_dir, name, need_docker, ps, release, rouh_dir,
                    run, say, set_settings, setting, settings_file, setup_code, stack_tool, user_name, yes)

VERSION = "1"
UNIT = "rouh-update"
UNIT_DIR = Path(os.environ.get("ROUH_UNIT_DIR") or "/etc/systemd/system")
BIN = Path(os.environ.get("ROUH_BIN") or "/usr/local/bin/rouh")
LOG = lambda: rouh_dir() / "logs" / "update.log"  # noqa: E731
HOSTNAME = re.compile(r"^(?=.{4,253}$)([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")


def sudo(args: list[str], **kw) -> subprocess.CompletedProcess:
    return run(args if os.getuid() == 0 else ["sudo", *args], **kw)


def systemd() -> bool:
    return shutil.which("systemctl") is not None and Path("/run/systemd/system").is_dir()


# --- status ----------------------------------------------------------------------------------------


def _state() -> dict:
    """What the core's setup API says now, or {} when it cannot be asked."""
    try:
        return Api(setup_code()).state()
    except Stop:
        return {}


def timer_state() -> tuple[bool, str]:
    if not systemd():
        return False, "this machine has no systemd to run the nightly update"
    on = run(["systemctl", "is-enabled", f"{UNIT}.timer"], timeout=20).returncode == 0
    nxt = (run(["systemctl", "show", f"{UNIT}.timer", "-p", "NextElapseUSecRealtime", "--value"], timeout=20).stdout or b"").decode().strip()
    return on, nxt


def last_update() -> str:
    f = LOG()
    if not f.is_file():
        return "none yet"
    lines = [line for line in f.read_text(errors="replace").splitlines() if line.startswith("== ")]
    return lines[-1][3:] if lines else "none yet"


def plan_nudge(state: dict) -> str:
    """While no plan is connected, every status and doctor says so (Petar: the plan is "optional but
    highly recommended")."""
    if not state.get("owner"):
        return ""
    if (state.get("plan") or {}).get("on_plan") or (state.get("codex") or {}).get("on_plan"):
        return ""
    return ("No plan is connected: Rouh's agents run on your API key, billed by use, which costs much more. "
            "Connect a Claude or ChatGPT plan with: rouh setup")


def cmd_status(a) -> int:
    need_docker()
    if not has_stack():
        say("Rouh is not installed on this machine yet: curl -fsSL https://rouh.land/install.sh | sh")
        return 1
    seen = ps()
    running = core_healthy(seen)
    r = release()
    st = _state() if running else {}
    born = st.get("born") or {}
    if running and st.get("step") == "done":
        say(f"{OK} Rouh {name(born.get('name', ''))} is running.")
    elif running:
        say(f"{WARN} Rouh is running, and its setup is not finished: rouh setup")
    elif seen:
        say(f"{NO} Rouh is not running: " + ", ".join(f"{k} {v.get('State')}" for k, v in seen.items() if v.get("State") != "running")[:200])
    else:
        say(f"{NO} Rouh is stopped. Start it: rouh update")
    if st.get("kind"):
        say(f"  Kind:        {'Connected Rouh' if st['kind'] == 'connected' else 'Independent Rouh'}")
    if st.get("address"):
        say(f"  Address:     {st['address']}" + ("" if st.get("reachable") else " (not answering from outside yet)"))
    if setting("ROUH_DOMAIN"):
        say(f"  Own domain:  https://{setting('ROUH_DOMAIN')}")
    if r and not r.get("bad"):
        say(f"  Release:     base {r['level']} (release {r['version']}), signature checked")
    elif r:
        say(f"  {NO} Release:  the release file here does not check out. rouh doctor")
    on, nxt = timer_state()
    say("  Updates:     " + (f"every night between 03:00 and 05:00, after a backup; next {nxt}" if on else
                              "nightly update is off (rouh update --on)") + f"; last: {last_update()}")
    backups = _backups()
    say(f"  Backups:     {len(backups)} nightly copies" + (f", newest {backups[-1]}" if backups else ""))
    ports = "127.0.0.1:" + common.port() + " (this machine only)"
    if setting("ROUH_DOMAIN") and "edge" in seen:
        ports += ", 80 and 443 for " + setting("ROUH_DOMAIN")
    say(f"  Open ports:  {ports}")
    keys = st.get("keys") or {}
    if st.get("owner"):
        works = [k.title() if k != "openai" else "OpenAI" for k, v in keys.items() if v == "ok"]
        say(f"  AI:          API key: {', '.join(works) + ' works' if works else 'none works yet (rouh setup)'}"
            + ("; plan: " + ("Claude" if (st.get("plan") or {}).get("on_plan") else "ChatGPT") + " connected"
               if not plan_nudge(st) else ""))
        nudge = plan_nudge(st)
        if nudge:
            say(f"  {WARN} {nudge}")
    return 0 if running else 1


# --- open --------------------------------------------------------------------------------------------


def cmd_open(a) -> int:
    need_docker()
    import wizard

    if not core_healthy():
        raise Stop("Rouh is not running. Start it: rouh update")
    st = code_status()
    if not st.get("owner"):
        say("Rouh has no owner yet. Set it up first:")
        return cmd_setup(a)
    wizard.open_rouh(Api(setup_code()))
    return 0


def cmd_setup(a) -> int:
    need_docker()
    import wizard

    if not core_healthy():
        say("Waiting for Rouh to be ready…")
        end = time.monotonic() + 600
        while not core_healthy():
            if time.monotonic() > end:
                raise Stop("Rouh is not running. Start it: rouh update")
            time.sleep(5)
    return wizard.run_wizard()


# --- update, and the nightly timer -------------------------------------------------------------------


def _verified_code_commit() -> tuple[str, int]:
    """rouh.land's newest tested commit of rouh-core, its signature checked with the key this
    checkout trusts (mac_release.py): (commit, version)."""
    sys.path.insert(0, str(CORE / "deploy" / "container"))
    import mac_release

    try:
        got = mac_release._get("/mac/code/newest.json")
        payload = mac_release._signed(got["record"])
    except (mac_release.FetchError, KeyError, ValueError, TypeError) as e:
        raise Stop(f"rouh.land's newest tested code could not be checked ({e}); nothing changed")
    commit = str(payload.get("commit") or "")
    if payload.get("kind") != "rouh-code-pass" or payload.get("branch") != "main" or not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise Stop("rouh.land's newest tested code is not a record this trusts; nothing changed")
    return commit, int(payload.get("version") or 0)


def update_updater() -> None:
    """The updater itself (this checkout) brought to rouh.land's newest tested, signed commit,
    forward only, before the update runs, so the nightly update is always the signed code's."""
    if not (CORE / ".git").is_dir() or os.environ.get("ROUH_KEEP_UPDATER") == "1":
        return
    commit, version = _verified_code_commit()
    here = (run(["git", "-C", str(CORE), "rev-parse", "HEAD"], timeout=30).stdout or b"").decode().strip()
    held = rouh_dir() / "releases" / "updater.json"
    before = json.loads(held.read_text()).get("version", 0) if held.is_file() else 0
    if here == commit or version < before:
        return
    say(f"The updater: to the newest tested Rouh code, {commit[:10]}")
    run(["git", "-C", str(CORE), "fetch", "-q", "--depth", "1", "origin", commit], timeout=600, check=True)
    run(["git", "-C", str(CORE), "checkout", "-q", "--force", commit], timeout=120, check=True)
    now = (run(["git", "-C", str(CORE), "rev-parse", "HEAD"], timeout=30).stdout or b"").decode().strip()
    if now != commit:
        raise Stop("the updater did not land on the signed commit; nothing else changed")
    held.write_text(json.dumps({"commit": commit, "version": version, "at": int(time.time())}) + "\n")
    install_cli()


def cmd_update(a) -> int:
    if a.off or a.on:
        return timer(on=bool(a.on))
    need_docker()
    log = LOG()
    log.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    stamp = time.strftime("%Y-%m-%d %H:%M")
    if a.nightly:
        # The timer's run: everything into the log, and one line for rouh status.
        with open(log, "a") as out:
            out.write(f"\n-- {stamp} nightly update\n")
        try:
            update_updater()
        except Stop as e:
            with open(log, "a") as out:
                out.write(f"== {stamp}: not updated: {e}\n")
            return 1
        with open(log, "a") as out:
            r = subprocess.run([sys.executable, str(common.STACK_TOOL), "--dir", str(rouh_dir()), "update"],
                               stdout=out, stderr=subprocess.STDOUT, timeout=7200)
            out.write(f"== {stamp}: " + ("up to date or updated, every part healthy" if r.returncode == 0 else
                                         "the update did not go through; Rouh stays on the release before") + "\n")
        _trim(log)
        return r.returncode
    update_updater()
    r = stack_tool("update")
    with open(log, "a") as out:
        out.write(f"== {stamp}: " + ("updated by hand" if r.returncode == 0 else "the update by hand did not go through") + "\n")
    return r.returncode


def _trim(log: Path, keep: int = 2000) -> None:
    lines = log.read_text(errors="replace").splitlines()
    if len(lines) > keep:
        log.write_text("\n".join(lines[-keep:]) + "\n")


def units() -> dict[str, str]:
    me = user_name()
    return {
        f"{UNIT}.service": f"""[Unit]
Description=Rouh's nightly update: the newest signed release, after a backup, going back by itself if unhealthy
Documentation=https://rouh.land/start/?for=linux
After=network-online.target docker.service
Wants=network-online.target

[Service]
Type=oneshot
User={me}
Environment=HOME={common.home()}
Environment=ROUH_DIR={rouh_dir()}
ExecStart={BIN} update --nightly
Nice=10
TimeoutStartSec=3h
""",
        f"{UNIT}.timer": """[Unit]
Description=Rouh's nightly update, at a random time between 03:00 and 05:00

[Timer]
OnCalendar=*-*-* 03:00:00
RandomizedDelaySec=2h
FixedRandomDelay=true
Persistent=true

[Install]
WantedBy=timers.target
""",
    }


def timer(on: bool) -> int:
    if not systemd():
        raise Stop("This machine has no systemd, so nothing can run the nightly update. Run rouh update yourself, "
                   "or from cron: 0 3 * * * rouh update --nightly")
    if on:
        for fname, text in units().items():
            tmp = rouh_dir() / f".{fname}"
            tmp.write_text(text)
            sudo(["install", "-m", "0644", str(tmp), str(UNIT_DIR / fname)], timeout=60, check=True)
            tmp.unlink()
        sudo(["systemctl", "daemon-reload"], timeout=60, check=True)
        sudo(["systemctl", "enable", "--now", f"{UNIT}.timer"], timeout=60, check=True)
        _, nxt = timer_state()
        say(f"{OK} Nightly update is on: every night between 03:00 and 05:00 (this server's time), after a backup. Next: {nxt}")
    else:
        sudo(["systemctl", "disable", "--now", f"{UNIT}.timer"], timeout=60)
        say(f"{OK} Nightly update is off. Rouh updates only when you run rouh update. Turn it back on: rouh update --on")
    return 0


def install_cli() -> None:
    """/usr/local/bin/rouh, a two-line launcher for this checkout's rouh.py."""
    launcher = f"#!/bin/sh\n# Rouh's owner command (rouh-core, deploy/linux/rouh.py). Made by install.sh.\nexec {sys.executable} {CORE}/deploy/linux/rouh.py \"$@\"\n"
    if BIN.is_file() and BIN.read_text() == launcher:
        return
    tmp = rouh_dir() / ".rouh-launcher"
    tmp.write_text(launcher)
    sudo(["install", "-m", "0755", str(tmp), str(BIN)], timeout=60, check=True)
    tmp.unlink()


# --- back, logs, backup --------------------------------------------------------------------------------


def cmd_back(a) -> int:
    need_docker()
    return stack_tool("back").returncode


def cmd_logs(a) -> int:
    need_docker()
    part = a.part or "core"
    if part not in common.services():
        raise Stop(f"Rouh has no part called {part}. Its parts: {', '.join(sorted(common.services()))}")
    args = ["logs", "--no-log-prefix", "--tail", str(a.lines)] + (["--follow"] if a.follow else []) + [part]
    return subprocess.run(compose(*args)).returncode


def _backups() -> list[str]:
    r = run(compose("exec", "-T", "backup", "/opt/rouh-guard/bin/rouh-backup", "list"), timeout=60)
    return [x.strip() for x in (r.stdout or b"").decode(errors="replace").splitlines() if x.strip().endswith(".dump")]


def cmd_backup(a) -> int:
    need_docker()
    if a.list:
        got = _backups()
        say(*(got or ["No nightly copies yet."]))
        return 0
    if a.restore:
        say(f"Putting the database back as it was in {a.restore}. Rouh stops for a moment.")
        if can_ask() and not yes("Go on?", default=False):
            return 1
        return stack_tool("restore", a.restore).returncode
    r = run(compose("exec", "-T", "backup", "/opt/rouh-guard/bin/rouh-backup", "now"), timeout=7200)
    said = (r.stdout or b"").decode(errors="replace").strip() or (r.stderr or b"").decode(errors="replace").strip()
    say(f"{OK if r.returncode == 0 else NO} {said.splitlines()[-1] if said else ''}")
    return r.returncode


# --- your own domain, and the relay ------------------------------------------------------------------


def _resolves(host: str) -> set[str]:
    try:
        return {i[4][0] for i in socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)}
    except socket.gaierror:
        return set()


def _release_has_edge() -> bool:
    ref = rouh_dir() / "stack" / "reference.yml"
    return ref.is_file() and re.search(r"(?m)^  edge:\s*$", ref.read_text()) is not None


def cmd_domain(a) -> int:
    need_docker()
    if a.off:
        if not setting("ROUH_DOMAIN"):
            say("No domain of your own is on.")
            return 0
        old = setting("ROUH_DOMAIN")
        set_settings(ROUH_DOMAIN=None, ROUH_PUBLIC_HOSTS=_hosts_without(old), ROUH_CSRF_TRUSTED_ORIGINS=_origins_without(old),
                     ROUH_EDGE_ACME_CA=None, ROUH_EDGE_ACME_ROOT_B64=None)
        subprocess.run(["docker", "rm", "--force", f"{common.PROJECT}-edge-1"], capture_output=True)
        r = stack_tool("apply")
        _recreate_core()
        say(f"{OK} {old} is off: ports 80 and 443 are closed again.")
        return r.returncode
    host = (a.name or "").strip().lower().rstrip(".")
    if host.startswith(("http://", "https://")):
        host = host.split("//", 1)[1].split("/", 1)[0]
    if not HOSTNAME.match(host) or host.endswith((".rouh.page", ".local", ".localhost")):
        raise Stop(f"{host or 'That'} is not a domain name Rouh can get a certificate for. Give it as rouh.example.com.")
    st = code_status()
    if not st.get("owner"):
        raise Stop("A domain is turned on only once Rouh has its owner, so nobody can reach an unclaimed Rouh. First: rouh setup")
    if not _release_has_edge():
        raise Stop("The release this Rouh runs has no part for an own domain yet. It comes with a newer release: "
                   "rouh update, then try again.")
    say(f"Checking that {host} points at this server…")
    mine, theirs = common.public_ip(), _resolves(host)
    if not theirs:
        raise Stop(f"{host} does not resolve yet. At your DNS provider, add an A record for {host} pointing at "
                   f"{mine or 'this server'}, wait a few minutes, then run this again.")
    if mine and mine not in theirs:
        raise Stop(f"{host} points at {', '.join(sorted(theirs))}, and this server is {mine} on the internet. "
                   f"Change the A record for {host} to {mine} (a Cloudflare record must be grey, DNS only), then run this again.")
    for p in (80, 443):
        if _listening(p):
            raise Stop(f"Something on this server already listens on port {p}. Stop it first: Rouh's own domain needs 80 and 443.")
    say(f"{OK} {host} points at this server{' (' + mine + ')' if mine else ''}.")
    set_settings(ROUH_DOMAIN=host, ROUH_PUBLIC_HOSTS=_hosts_with(host), ROUH_CSRF_TRUSTED_ORIGINS=_origins_with(host))
    # A test: Let's Encrypt's staging service, or another (Pebble) with its own root certificate.
    ca = "https://acme-staging-v02.api.letsencrypt.org/directory" if a.staging else (a.acme_ca or "")
    root = ""
    if a.acme_root:
        import base64

        root = base64.b64encode(Path(a.acme_root).read_bytes()).decode()
    set_settings(ROUH_EDGE_ACME_CA=ca, ROUH_EDGE_ACME_ROOT_B64=root)
    say("Starting the edge part, which gets a certificate from Let's Encrypt…")
    r = stack_tool("apply")
    _recreate_core()
    seen = ps()
    if r.returncode or (seen.get("edge") or {}).get("State") != "running":
        set_settings(ROUH_DOMAIN=None, ROUH_PUBLIC_HOSTS=_hosts_without(host), ROUH_CSRF_TRUSTED_ORIGINS=_origins_without(host))
        stack_tool("apply")
        _recreate_core()
        raise Stop("The edge part did not start, so the domain is off again and ports 80 and 443 stay closed. "
                   "rouh logs edge says why.")
    end = time.monotonic() + 180
    while time.monotonic() < end:
        if _https_answers(host, staging=bool(a.staging or a.acme_ca), root=a.acme_root):
            say(f"{OK} https://{host} answers, with its own certificate.")
            say("Sign in there: rouh open")
            return 0
        time.sleep(6)
    say(f"{WARN} https://{host} does not answer yet. Let's Encrypt may still be checking; rouh logs edge says more.")
    return 1


def _https_answers(host: str, staging: bool = False, root: str | None = None) -> bool:
    """https://HOST/healthz answers 200. A test's certificate is not one a browser trusts: then the
    certificate is not checked here (the proof checks it against the test service's own root)."""
    import ssl

    ctx = ssl.create_default_context()
    if staging:
        ctx.check_hostname, ctx.verify_mode = False, ssl.CERT_NONE
    try:
        with urllib.request.urlopen(f"https://{host}/healthz", timeout=10, context=ctx) as r:
            return r.status == 200
    except OSError:
        return False


def _listening(p: int) -> bool:
    r = run(["ss", "-Hltn", f"sport = :{p}"], timeout=10) if shutil.which("ss") else None
    return bool(r is not None and r.returncode == 0 and (r.stdout or b"").strip())


def _list(key: str) -> list[str]:
    return [x for x in setting(key).split(",") if x]


def _hosts_with(h: str) -> str:
    return ",".join(dict.fromkeys(_list("ROUH_PUBLIC_HOSTS") + [h]))


def _hosts_without(h: str) -> str:
    return ",".join(x for x in _list("ROUH_PUBLIC_HOSTS") if x != h)


def _origins_with(h: str) -> str:
    return ",".join(dict.fromkeys(_list("ROUH_CSRF_TRUSTED_ORIGINS") + [f"https://{h}"]))


def _origins_without(h: str) -> str:
    return ",".join(x for x in _list("ROUH_CSRF_TRUSTED_ORIGINS") if x != f"https://{h}")


def _recreate_core() -> None:
    """The core and the worker read the settings file when they are made: made again, they read it now."""
    run(compose("up", "--detach", "--no-deps", "--force-recreate", "core", "worker"), timeout=900)
    end = time.monotonic() + 600
    while not core_healthy() and time.monotonic() < end:
        time.sleep(5)


def cmd_relay(a) -> int:
    """Which relay a Connected Rouh's phone address goes through: rouh.land's (rouh.page) by default,
    or one the owner runs (rouh-it/rouh-relay; INSTALL-LINUX.md, "A relay of your own")."""
    need_docker()
    if a.off:
        set_settings(ROUH_RELAY="0")
        say(f"{OK} The relay is off: this Rouh has no phone address. rouh relay --default turns rouh.land's back on.")
    elif a.default:
        set_settings(ROUH_RELAY="", ROUH_RELAY_URL="", ROUH_RELAY_DOMAIN="")
        say(f"{OK} The relay is rouh.land's: addresses on rouh.page.")
    elif a.url:
        url = a.url.strip()
        if not re.fullmatch(r"https://[a-z0-9.-]+(:\d+)?(/[A-Za-z0-9._/-]*)?", url):
            raise Stop("Give the relay's claim address, starting https://, such as https://relay.example.com/relay/")
        dom = (a.domain or "").strip().lower()
        if dom and not HOSTNAME.match(dom):
            raise Stop("--domain is the relay's domain for addresses, such as rouh.example.com")
        set_settings(ROUH_RELAY="", ROUH_RELAY_URL=url if url.endswith("/") else url + "/", ROUH_RELAY_DOMAIN=dom)
        say(f"{OK} The relay is {url}{' (addresses on ' + dom + ')' if dom else ''}. A Rouh already Connected claims its "
            "address there the next time it starts.")
    else:
        url = setting("ROUH_RELAY_URL")
        say("The relay: " + ("off" if setting("ROUH_RELAY") == "0" else (url or "rouh.land's (rouh.page)")))
        return 0
    _recreate_core()
    return 0


# --- doctor ------------------------------------------------------------------------------------------


def cmd_doctor(a) -> int:
    problems = 0

    def good(text):
        say(f"{OK} {text}")

    def bad(text, fix=""):
        nonlocal problems
        problems += 1
        say(f"{NO} {text}" + (f"\n    {DIM}Fix:{RESET} {fix}" if fix else ""))

    def note(text):
        say(f"{WARN} {text}")

    heading("Rouh's doctor: checking this server")
    cores = os.cpu_count() or 0
    (good if cores >= 4 else note if cores >= 2 else bad)(f"{cores} processor cores" + ("" if cores >= 4 else " (4 recommended)"))
    mem = _mem_gb()
    (good if mem >= 8 else note if mem >= 4 else bad)(f"{mem} GB of memory" + ("" if mem >= 8 else " (8 GB recommended)"))
    free = shutil.disk_usage(rouh_dir() if rouh_dir().exists() else common.home()).free // 2**30
    (good if free >= 20 else bad)(f"{free} GB free disk", "free some disk: Rouh needs 15 GB at least, 64 GB to run well")
    (good if sys.version_info >= (3, 12) else bad)(f"Python {sys.version.split()[0]} for the updater",
                                                    "install Rouh again; it brings Python 3.12")
    if not common.docker_ok() and not common.in_docker_group():
        bad("Docker does not answer", "sudo systemctl start docker")
        return 1
    need_docker()
    good("Docker answers: " + (run(["docker", "compose", "version", "--short"], timeout=20).stdout or b"").decode().strip())
    r = release()
    if r is None:
        bad("No release in use", "rouh update")
    elif r.get("bad"):
        bad("The release in use does not check out against the key this updater trusts", "rouh update")
    else:
        good(f"Release {r['version']} (base {r['level']}): its signature checks out")
    seen = ps()
    down = [k for k, v in seen.items() if v.get("State") != "running" and k not in ("worker-perms", "guard-init", "code-install")]
    (good if seen and not down else bad)("Every part of Rouh runs" if seen and not down else
                                         "Not running: " + ", ".join(down or ["everything"]), "rouh update, then rouh logs PART")
    on, nxt = timer_state()
    (good if on else note)(f"Nightly update on (next {nxt})" if on else "Nightly update is off: rouh update --on")
    if "not" in last_update():
        note(f"The last update: {last_update()}. rouh logs, and {LOG()}")
    listening = _listeners()
    outside = [x for x in listening if not x.startswith(("127.", "[::1]", "::1"))]
    good("Listening only on this machine: " + ", ".join(listening) if not outside else
         "Listening: " + ", ".join(listening))
    if outside:
        note("Something listens to the outside: " + ", ".join(outside)
             + (". 80 and 443 are Rouh's own domain; Docker's published ports go round ufw, which is intended here."
                if setting("ROUH_DOMAIN") else ""))
    ufw = run(["sudo", "-n", "ufw", "status"], timeout=20) if shutil.which("ufw") else None
    if ufw is not None and ufw.returncode == 0 and b"inactive" in (ufw.stdout or b""):
        note("The firewall (ufw) is off. Rouh needs no port open to the outside. If nothing else protects this server: "
             "sudo ufw allow OpenSSH && sudo ufw enable")
    logs = run(compose("logs", "--no-log-prefix", "core"), timeout=120)
    try:
        code = setup_code()
    except Stop:
        code = ""
    (bad if code and code.encode() in (logs.stdout or b"") else good)(
        "The live setup code is in Rouh's logs" if code and code.encode() in (logs.stdout or b"") else
        "The setup code is in no log", "rouh setup (it writes a new one)")
    st = _state()
    if st.get("expired"):
        note("The setup code expired before an owner was made: rouh setup makes a new one")
    if st.get("owner"):
        (good if any(v == "ok" for v in (st.get("keys") or {}).values()) else bad)(
            "An AI key works" if any(v == "ok" for v in (st.get("keys") or {}).values()) else "No AI key works", "rouh setup")
        nudge = plan_nudge(st)
        (note if nudge else good)(nudge or "A plan runs Rouh's agents")
        if st.get("kind") == "connected":
            (good if st.get("reachable") else note)(
                f"{st.get('address')} answers from the internet" if st.get("reachable") else
                f"{st.get('address') or 'The phone address'} does not answer from outside yet: {st.get('relay_said') or 'the relay is connecting'}")
    elif seen:
        note("Rouh has no owner yet: rouh setup")
    relay = setting("ROUH_RELAY_URL")
    if relay:
        good(f"A relay of your own: {relay}")
    for host in ("rouh.land", "ghcr.io", "github.com"):
        (good if _reaches(host) else bad)(f"Reaches {host}", f"check this server's internet connection and DNS for {host}")
    if setting("ROUH_DOMAIN"):
        d = setting("ROUH_DOMAIN")
        (good if _https_answers(d) else bad)(f"https://{d} answers with a valid certificate", "rouh logs edge")
    say("", f"{OK} Nothing to fix." if not problems else f"{problems} thing{'s' if problems > 1 else ''} to fix, above.")
    return 0 if not problems else 1


def _mem_gb() -> int:
    try:
        kb = int(next(line.split()[1] for line in Path("/proc/meminfo").read_text().splitlines() if line.startswith("MemTotal:")))
        return (kb + 524288) // 1048576
    except (OSError, StopIteration, ValueError):
        return 0


def _listeners() -> list[str]:
    r = run(["ss", "-Hltn"], timeout=10) if shutil.which("ss") else None
    if r is None or r.returncode:
        return []
    out = []
    for line in (r.stdout or b"").decode().splitlines():
        parts = line.split()
        if len(parts) >= 4 and not parts[3].endswith(":22"):
            out.append(parts[3])
    return sorted(set(out))


def _reaches(host: str) -> bool:
    try:
        with socket.create_connection((host, 443), timeout=8):
            return True
    except OSError:
        return False


# --- uninstall, and bring back -----------------------------------------------------------------------

KEEP_WORDS = ["Keep my data (recommended)",
              "Saves a checked copy of everything that makes this Rouh itself: its memory database, your workspace,",
              "its own code, its identity and keys, its undo points and its agents' sign-ins, into ~/rouh-kept.",
              "Then removes Rouh. Install Rouh again and choose Bring back your Rouh: it comes back as itself."]
WIPE_WORDS = ["Wipe my data",
              "Removes Rouh and everything it knows: its memory, your workspace in it, its code and its keys.",
              "This cannot be undone. A Connected Rouh's rouh.land account and registration are not deleted."]


def cmd_uninstall(a) -> int:
    need_docker()
    import kept

    if not can_ask() and not a.yes:
        raise Stop("Uninstall asks what should happen to Rouh's data; run it in a terminal.")
    heading("What should happen to Rouh's data?")
    say("", f"  {BOLD}K  {KEEP_WORDS[0]}{RESET}", *[f"     {x}" for x in KEEP_WORDS[1:]], "",
        f"  {BOLD}W  {WIPE_WORDS[0]}{RESET}", *[f"     {x}" for x in WIPE_WORDS[1:]], "",
        f"{DIM}Either way Docker itself, your other containers and everything else on this server stay.{RESET}", "")
    how = a.how or common.choose("Keep or Wipe? [K/w], or Ctrl-C to cancel: ", [("keep", ""), ("wipe", "")], "keep")
    if how == "wipe" and not a.yes:
        if ask("Type WIPE to remove Rouh and its data for good: ") != "WIPE":
            say("Nothing was removed.")
            return 1
    folder = None
    if how == "keep" and has_stack():
        try:
            folder = kept.save()
        except Stop as e:
            say(f"{NO} The copy did not check out: {e}", "Nothing was removed. Rouh is started again.")
            run(compose("up", "--detach"), timeout=1800)
            return 1
    removed = remove_everything()
    heading("Rouh is removed from this server")
    for line in removed:
        say(f"  · {line}")
    if folder:
        say("", f"{OK} Kept, and checked: {folder}",
            "To bring it back: curl -fsSL https://rouh.land/install.sh | sh, and choose Bring back your Rouh.")
    else:
        say("", "Rouh's data is wiped. A Connected Rouh's rouh.land account is still there; delete it on rouh.land if you want.")
    return 0


def remove_everything() -> list[str]:
    done = []
    if has_stack():
        imgs = set((run(compose("config", "--images"), timeout=120).stdout or b"").decode().split())
        run(compose("down", "--volumes", "--remove-orphans", "--timeout", "30"), timeout=900)
        done.append("Rouh's containers, networks and volumes")
        for img in imgs:
            run(["docker", "image", "rm", img], timeout=300)
        if imgs:
            done.append(f"its {len(imgs)} images")
    left = (run(["docker", "volume", "ls", "-q", "--filter", f"label=com.docker.compose.project={common.PROJECT}"], timeout=60).stdout or b"").decode().split()
    for v in left:
        run(["docker", "volume", "rm", "--force", v], timeout=120)
    if systemd() and (UNIT_DIR / f"{UNIT}.timer").exists():
        sudo(["systemctl", "disable", "--now", f"{UNIT}.timer"], timeout=60)
        sudo(["rm", "-f", str(UNIT_DIR / f"{UNIT}.timer"), str(UNIT_DIR / f"{UNIT}.service")], timeout=60)
        sudo(["systemctl", "daemon-reload"], timeout=60)
        done.append("the nightly update")
    if rouh_dir().exists():
        shutil.rmtree(rouh_dir(), ignore_errors=True)
        done.append(f"{rouh_dir()} (settings, releases, backups)")
    if BIN.exists():
        sudo(["rm", "-f", str(BIN)], timeout=60)
        done.append(str(BIN))
    if (CORE / ".git").is_dir() and CORE.name == "rouh-core":
        shutil.rmtree(CORE, ignore_errors=True)
        done.append(f"{CORE} (the updater)")
    return done


def cmd_bring_back(a) -> int:
    need_docker()
    import kept

    folder = Path(a.folder).expanduser() if a.folder else kept.waiting()
    if folder is None:
        raise Stop(f"There is no kept Rouh in {kept_dir()}.")
    kept.bring_back(folder)
    return 0


def cmd_fingerprint(a) -> int:
    need_docker()
    import kept

    print(json.dumps(kept.fingerprint(), indent=1, sort_keys=True))
    return 0


# --- install: what install.sh hands over to, once Docker and the checkout are in place -----------------


def cmd_install(a) -> int:
    """Settings, Bring back, the command and the timer, the first start, then setup in this terminal."""
    need_docker()
    import kept

    rouh_dir().mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(rouh_dir(), 0o700)
    first = not (rouh_dir() / "releases" / "current.json").is_file()
    back = kept.waiting() if first else None
    if back is not None:
        m = json.loads((back / "manifest.json").read_text())
        heading("A kept Rouh is on this server")
        say(f"Saved {m.get('made', '')}, when Rouh was uninstalled with Keep my data: {m.get('tables')} tables of memory, "
            "your workspace, its code and keys.", "",
            f"  {BOLD}B  Bring back your Rouh{RESET} (recommended): the same Rouh, as itself.",
            f"  {BOLD}F  Start fresh{RESET}: a new Rouh. The kept copy stays in {back}.", "")
        want = "back" if (a.yes or not can_ask()) else common.choose("Bring back or start fresh? [B/f] ", [("back", ""), ("fresh", "")], "back")
        if want != "back":
            back = None
        elif kept.settings_of(back) and not settings_file().is_file():
            shutil.copy2(kept.settings_of(back), settings_file())
    _settings()
    install_cli()
    if back is not None:
        heading("Bringing back your Rouh")
        r = stack_tool("prepare")
        if r.returncode:
            raise Stop("The release could not be got ready to bring your Rouh back into; nothing was changed.")
        kept.bring_back(back)
    heading("Starting Rouh (the first time downloads about 2 GB)")
    r = stack_tool("update")
    if r.returncode:
        raise Stop("Rouh's updater stopped; its words are above.")
    if systemd():
        timer(on=True)
    if not core_healthy():
        say("Waiting for Rouh to be ready (up to 10 minutes)…")
        end = time.monotonic() + 600
        while not core_healthy():
            if time.monotonic() > end:
                raise Stop("Rouh did not get ready in 10 minutes. rouh doctor, and rouh logs, say why.")
            time.sleep(5)
    rel = release() or {}
    say(f"{OK} Rouh is running (base {rel.get('level', '?')}, release {rel.get('version', '?')}, signature checked).")
    if a.no_setup or not can_ask():
        say("", "Next, set your Rouh up in a terminal on this server:", "", f"    {BOLD}rouh setup{RESET}", "")
        return 0
    return cmd_setup(a)


def _settings() -> None:
    f = settings_file()
    if not f.is_file():
        shutil.copy2(CORE / "deploy" / "stack" / "settings.env.example", f)
        say(f"Made the settings file {f}.")
    os.chmod(f, 0o600)
    import secrets

    if not setting("POSTGRES_PASSWORD"):
        set_settings(POSTGRES_PASSWORD=secrets.token_hex(32))
    given = os.environ.get("ROUH_INSTALL_CODE", "").strip()
    if given and re.fullmatch(r"[A-Za-z0-9_.-]+", given):
        set_settings(ROUH_INSTALL_CODE=given)
    elif not setting("ROUH_INSTALL_CODE"):
        set_settings(ROUH_INSTALL_CODE="free")
    if not setting("ROUH_SETUP_CODE_HOURS"):
        # A setup code lasts a day while there is no owner; rouh setup writes a new one (step 176-24).
        set_settings(ROUH_SETUP_CODE_HOURS="24")


# -----------------------------------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="rouh", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--debug", action="store_true", help="show the technical detail")
    ap.add_argument("--version", action="version", version=f"rouh {VERSION} (rouh-core {_head()})")
    sub = ap.add_subparsers(dest="cmd", required=True, metavar="COMMAND")
    sub.add_parser("status", help="is Rouh running, and how")
    sub.add_parser("setup", help="the first run, in this terminal")
    sub.add_parser("open", help="a one-time sign-in link")
    u = sub.add_parser("update", help="update now, or turn the nightly update --off or --on")
    g = u.add_mutually_exclusive_group()
    g.add_argument("--off", action="store_true")
    g.add_argument("--on", action="store_true")
    g.add_argument("--nightly", action="store_true", help=argparse.SUPPRESS)
    sub.add_parser("back", help="back to the release before")
    lg = sub.add_parser("logs", help="the last lines of a part (core by default)")
    lg.add_argument("part", nargs="?")
    lg.add_argument("-f", "--follow", action="store_true")
    lg.add_argument("-n", "--lines", type=int, default=100)
    b = sub.add_parser("backup", help="a copy of the database now, --list, or --restore NAME")
    b.add_argument("--list", action="store_true")
    b.add_argument("--restore", metavar="NAME")
    d = sub.add_parser("domain", help="your own domain with HTTPS, or --off")
    d.add_argument("name", nargs="?")
    d.add_argument("--off", action="store_true")
    d.add_argument("--staging", action="store_true", help=argparse.SUPPRESS)
    d.add_argument("--acme-ca", help=argparse.SUPPRESS)
    d.add_argument("--acme-root", help=argparse.SUPPRESS)
    rl = sub.add_parser("relay", help="the relay for a Connected Rouh's phone address")
    rl.add_argument("url", nargs="?")
    rl.add_argument("--domain")
    rl.add_argument("--default", action="store_true")
    rl.add_argument("--off", action="store_true")
    sub.add_parser("doctor", help="check this server, and say what to fix")
    un = sub.add_parser("uninstall", help="remove Rouh: Keep my data, or Wipe my data")
    un.add_argument("--keep", dest="how", action="store_const", const="keep", help=argparse.SUPPRESS)
    un.add_argument("--wipe", dest="how", action="store_const", const="wipe", help=argparse.SUPPRESS)
    un.add_argument("--yes", action="store_true", help=argparse.SUPPRESS)
    bb = sub.add_parser("bring-back", help=argparse.SUPPRESS)
    bb.add_argument("folder", nargs="?")
    sub.add_parser("fingerprint", help=argparse.SUPPRESS)
    ins = sub.add_parser("install", help=argparse.SUPPRESS)
    ins.add_argument("--yes", action="store_true")
    ins.add_argument("--no-setup", action="store_true")
    a = ap.parse_args(argv)
    if a.debug:
        common.DEBUG = True
        os.environ["ROUH_DEBUG"] = "1"
    try:
        return {"status": cmd_status, "setup": cmd_setup, "open": cmd_open, "update": cmd_update, "back": cmd_back,
                "logs": cmd_logs, "backup": cmd_backup, "domain": cmd_domain, "relay": cmd_relay, "doctor": cmd_doctor,
                "uninstall": cmd_uninstall, "bring-back": cmd_bring_back, "fingerprint": cmd_fingerprint,
                "install": cmd_install}[a.cmd](a)
    except Stop as e:
        say(f"{NO} {e}")
        return 1
    except KeyboardInterrupt:
        say("", "Stopped. Run the same command again to carry on.")
        return 130


def _head() -> str:
    r = subprocess.run(["git", "-C", str(CORE), "rev-parse", "--short", "HEAD"], capture_output=True)
    return r.stdout.decode().strip() or "?"


if __name__ == "__main__":
    sys.exit(main())
