"""What every part of the `rouh` command shares: where things are, Docker, the settings file, the
setup API, and how words are drawn in a terminal (task 176, step 176-25).

Standard library only, Python 3.12: a Linux server has nothing else of Rouh's outside its
containers. Everything that touches Rouh goes through Docker Compose with the stack file
linux_stack.py chose (``~/rouh/stack/stack.json``), or through the core's setup API on
127.0.0.1, with the setup code read out of the core by ``docker compose exec`` (never from a log).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
#: The updater's checkout, rouh-core: the folder above deploy/.
CORE = HERE.parents[1]
STACK_TOOL = CORE / "deploy" / "container" / "linux_stack.py"
PROJECT = os.environ.get("ROUH_STACK_PROJECT", "rouh")
ROUH_LAND = (os.environ.get("ROUH_LAND") or "https://rouh.land").rstrip("/")
DEBUG = os.environ.get("ROUH_DEBUG", "") not in ("", "0")


def home() -> Path:
    return Path(os.environ.get("HOME") or Path.home())


def rouh_dir() -> Path:
    return Path(os.environ.get("ROUH_DIR") or home() / "rouh").expanduser()


def kept_dir() -> Path:
    return Path(os.environ.get("ROUH_KEPT_DIR") or home() / "rouh-kept").expanduser()


def settings_file() -> Path:
    return rouh_dir() / ".env"


# --- words in a terminal ----------------------------------------------------------------------------

def _colour() -> bool:
    return sys.stdout.isatty() and os.environ.get("TERM", "") not in ("", "dumb") and "NO_COLOR" not in os.environ


C = _colour()
RESET = "\033[0m" if C else ""
BOLD = "\033[1m" if C else ""
DIM = "\033[2m" if C else ""
#: The Rouh's name, in orange, as on every setup screen since step 176-15 (#ff9a4d).
ORANGE = ("\033[38;2;255;154;77m" if os.environ.get("COLORTERM") in ("truecolor", "24bit") else "\033[38;5;215m") if C else ""
GREEN = "\033[32m" if C else ""
RED = "\033[31m" if C else ""
YELLOW = "\033[33m" if C else ""
OK = f"{GREEN}✓{RESET}" if C else "[ok]"
NO = f"{RED}✗{RESET}" if C else "[no]"
WARN = f"{YELLOW}!{RESET}" if C else "[!]"


def say(*lines: str) -> None:
    for line in lines or ("",):
        print(line, flush=True)


def heading(text: str) -> None:
    say("", f"{BOLD}{text}{RESET}")


def name(text: str) -> str:
    """A Rouh's name, in orange where the terminal draws colour."""
    return f"{ORANGE}{BOLD}{text}{RESET}" if text else text


def debug(text: str) -> None:
    if DEBUG:
        print(f"{DIM}  · {text}{RESET}", file=sys.stderr, flush=True)


class Stop(Exception):
    """The command ends here, with this said to the person."""


def qr(rows: list[str]) -> str:
    """A QR code drawn with half blocks, two rows of the code to one line of the terminal, dark on
    light whatever the terminal's own colours (a phone's camera needs the light border)."""
    if not rows:
        return ""
    rows = rows + ["0" * len(rows[0])] if len(rows) % 2 else rows
    out = []
    for top, bottom in zip(rows[::2], rows[1::2]):
        line = ""
        for a, b in zip(top, bottom):
            line += {("1", "1"): " ", ("1", "0"): "▄", ("0", "1"): "▀", ("0", "0"): "█"}[(a, b)]
        out.append("  " + line)
    return "\n".join(out)


# --- the keyboard, which under curl | sh is the terminal itself ---------------------------------------

_TTY = None


class _Terminal:
    """/dev/tty, opened twice: a terminal cannot be one text file read and written (it is not seekable)."""

    def __init__(self):
        self.r = open("/dev/tty", "r", encoding="utf-8", errors="replace")
        self.w = open("/dev/tty", "w", buffering=1, encoding="utf-8", errors="replace")

    def fileno(self) -> int:
        return self.r.fileno()

    def readline(self) -> str:
        return self.r.readline()

    def write(self, text: str) -> None:
        self.w.write(text)

    def flush(self) -> None:
        self.w.flush()


def tty():
    """The terminal to ask on: /dev/tty, which still works when this runs under ``curl ... | sh``."""
    global _TTY
    if _TTY is None:
        try:
            _TTY = _Terminal()
        except OSError:
            _TTY = False
    return _TTY or None


def can_ask() -> bool:
    return tty() is not None and os.environ.get("ROUH_NO_TTY", "") in ("", "0")


def ask(prompt: str, *, default: str = "", hidden: bool = False) -> str:
    t = tty()
    if t is None:
        raise Stop("This needs a terminal to answer in. Run it again in a terminal, or over SSH.")
    if hidden:
        import termios

        fd = t.fileno()
        old = termios.tcgetattr(fd)
        new = termios.tcgetattr(fd)
        new[3] &= ~termios.ECHO
        try:
            t.write(prompt)
            t.flush()
            termios.tcsetattr(fd, termios.TCSADRAIN, new)
            got = t.readline()
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)
            t.write("\n")
        if got == "":
            raise Stop("The terminal closed.")
        return got.rstrip("\n")
    t.write(prompt)
    t.flush()
    got = t.readline()
    if got == "":
        raise Stop("The terminal closed.")
    return got.strip() or default


def yes(prompt: str, default: bool = True) -> bool:
    mark = "[Y/n]" if default else "[y/N]"
    while True:
        got = ask(f"{prompt} {mark} ").lower()
        if not got:
            return default
        if got in ("y", "yes"):
            return True
        if got in ("n", "no"):
            return False
        say("Type y or n.")


def choose(prompt: str, options: list[tuple[str, str]], default: str) -> str:
    """One of options [(key, words)]; the key or the first letter of a key, Enter for the default."""
    keys = [k for k, _ in options]
    while True:
        got = ask(prompt).strip().lower()
        if not got:
            return default
        for k in keys:
            if got == k or got == k[0]:
                return k
        say("Type " + " or ".join(k[0] for k in keys) + ", or press Enter for " + default + ".")


# --- running things --------------------------------------------------------------------------------

def run(args: list[str], *, input: bytes | None = None, timeout: float = 600, check: bool = False,
        capture: bool = True, env: dict | None = None) -> subprocess.CompletedProcess:
    debug(" ".join(args))
    r = subprocess.run(args, input=input, capture_output=capture, timeout=timeout, env=env)
    if check and r.returncode:
        said = ((r.stderr or b"") + (r.stdout or b"")).decode(errors="replace").strip() if capture else ""
        raise Stop(f"{' '.join(args[:3])} failed" + (f": {said[-400:]}" if said else ""))
    return r


def docker_ok() -> bool:
    return shutil.which("docker") is not None and run(["docker", "info", "--format", "{{.ID}}"], timeout=30).returncode == 0


def in_docker_group() -> bool:
    import grp
    import pwd

    try:
        me = pwd.getpwuid(os.getuid()).pw_name
        return me in grp.getgrnam("docker").gr_mem
    except KeyError:
        return False


def need_docker() -> None:
    """Docker answers, or this command goes on through ``sg docker`` (a user just added to the
    docker group by the installer, before they signed out and in), or says plainly why not."""
    if docker_ok():
        return
    if os.environ.get("ROUH_VIA_SG") != "1" and in_docker_group() and shutil.which("sg"):
        import shlex

        cmd = " ".join(shlex.quote(a) for a in [sys.executable, *sys.argv])
        os.environ["ROUH_VIA_SG"] = "1"
        os.execvp("sg", ["sg", "docker", "-c", cmd])
    if shutil.which("docker") is None:
        raise Stop("Docker is not installed. Install Rouh again: curl -fsSL https://rouh.land/install.sh | sh")
    raise Stop("Docker does not answer. Check it with: sudo systemctl status docker")


# --- the settings file -----------------------------------------------------------------------------

def read_settings() -> dict[str, str]:
    out: dict[str, str] = {}
    f = settings_file()
    if not f.is_file():
        return out
    for line in f.read_text().splitlines():
        m = re.match(r"^([A-Z_][A-Z0-9_]*)=(.*)$", line)
        if m:
            out[m.group(1)] = m.group(2).strip()
    return out


def setting(key: str, default: str = "") -> str:
    return read_settings().get(key, default) or default


def set_settings(**values: str | None) -> None:
    """Changes or adds each key in the settings file, keeping every other line and comment. None
    removes the key's value (it is kept, empty, so the example's comment above it still says what
    it is)."""
    f = settings_file()
    lines = f.read_text().splitlines() if f.is_file() else []
    for key, value in values.items():
        if value is not None and not re.fullmatch(r"[A-Za-z0-9_.,:/@+=-]*", value):
            raise Stop(f"{key} cannot hold {value!r}: only letters, digits and . , : / @ + = - _ are allowed.")
        line = f"{key}={value or ''}"
        for i, old in enumerate(lines):
            if old.startswith(f"{key}="):
                lines[i] = line
                break
        else:
            lines.append(line)
    tmp = f.with_name(".env.new")
    tmp.write_text("\n".join(lines) + "\n")
    os.chmod(tmp, 0o600)
    tmp.replace(f)


# --- the stack -------------------------------------------------------------------------------------

def stack_file() -> Path:
    return rouh_dir() / "stack" / "stack.json"


def release_env() -> Path:
    return rouh_dir() / "stack" / "release.env"


def has_stack() -> bool:
    return stack_file().is_file() and release_env().is_file()


def compose(*args: str) -> list[str]:
    cmd = ["docker", "compose", "--project-name", PROJECT, "-f", str(stack_file()),
           "--env-file", str(settings_file()), "--env-file", str(release_env())]
    if setting("ROUH_DOMAIN"):
        cmd += ["--profile", "edge"]
    return cmd + list(args)


def services() -> dict:
    try:
        return json.loads(stack_file().read_text()).get("services") or {}
    except (OSError, ValueError):
        return {}


def ps() -> dict:
    r = run(compose("ps", "--all", "--format", "json"), timeout=60)
    text = (r.stdout or b"").decode(errors="replace").strip()
    if r.returncode or not text:
        return {}
    rows = json.loads(text) if text.startswith("[") else [json.loads(x) for x in text.splitlines() if x.strip()]
    return {row.get("Service"): row for row in rows}


def core_healthy(seen: dict | None = None) -> bool:
    seen = ps() if seen is None else seen
    c = seen.get("core") or {}
    return c.get("State") == "running" and c.get("Health") == "healthy"


def release() -> dict | None:
    """The release in use, its signature checked again (mac_release.check_release)."""
    f = rouh_dir() / "releases" / "current.json"
    if not f.is_file():
        return None
    sys.path.insert(0, str(CORE / "deploy" / "container"))
    import mac_release

    try:
        return mac_release.check_release(json.loads(f.read_bytes()))
    except (ValueError, KeyError, json.JSONDecodeError):
        return {"bad": True}


def stack_tool(*args: str, capture: bool = False, timeout: float = 7200) -> subprocess.CompletedProcess:
    return run([sys.executable, str(STACK_TOOL), "--dir", str(rouh_dir()), *args], capture=capture, timeout=timeout)


# --- the core's setup API --------------------------------------------------------------------------

def port() -> str:
    return setting("ROUH_PORT", "8420")


def local_url(path: str = "/") -> str:
    return f"http://127.0.0.1:{port()}{path}"


def core_exec(*args: str, timeout: float = 120) -> subprocess.CompletedProcess:
    """A command in the core, as Rouh's own user (10001), the way Rouh itself runs there: a file it
    writes (a new setup code) stays Rouh's, not root's."""
    return run(compose("exec", "-T", "--user", "10001:10001", "core", *args), timeout=timeout)


#: A Rouh's code is its own and no update overwrites it, so a Rouh installed before 11 November 2026
#: has no `manage.py setup_code`: then the code is read from its file and written afresh by Python
#: in the core, with the same rules (step 176-25).
OLDER_READ = "import sys; sys.stdout.write(open('/data/first-run-code').read().strip())"
OLDER_RENEW = ("import os, secrets, tempfile; p = '/data/first-run-code'; c = secrets.token_urlsafe(18); "
               "fd, t = tempfile.mkstemp(dir='/data'); os.write(fd, (c + '\\n').encode()); os.close(fd); "
               "os.chmod(t, 0o600); os.replace(t, p); print(c)")
OLDER_STATUS = ("from rouh.project import setup; setup(); import json; from rouh.web import firstrun; "
                "u = firstrun.the_owner(); h = firstrun.record(u) if u else {}; "
                "print(json.dumps({'owner': u is not None, 'setup_done': bool(h.get('done_at')) or (u is not None and not h), "
                "'kind': None if 'connected' not in h else ('connected' if h['connected'] else 'independent'), 'code': True, "
                "'expired': False, 'hours': 0}))")


def _older(r: subprocess.CompletedProcess) -> bool:
    return b"Unknown command" in (r.stderr or b"") + (r.stdout or b"")


def setup_code(renew: bool = False) -> str:
    """The setup code, out of the core by ``docker compose exec``: it reaches this terminal and
    nothing else. Renewed when asked (``rouh setup`` always asks), or when it has expired."""
    r = core_exec("python", "manage.py", "setup_code", *(["--renew"] if renew else []))
    if _older(r):
        debug("this Rouh's code has no setup_code; reading its file")
        r = core_exec("python", "-c", OLDER_RENEW if renew else OLDER_READ)
    code = (r.stdout or b"").decode(errors="replace").strip().splitlines()
    if r.returncode or not code or not re.fullmatch(r"[A-Za-z0-9_-]{16,}", code[-1]):
        raise Stop("Rouh's setup code could not be read from the core. Is Rouh running? Try: rouh status")
    return code[-1]


def code_status() -> dict:
    r = core_exec("python", "manage.py", "setup_code", "--status")
    if _older(r):
        r = core_exec("python", "-c", OLDER_STATUS)
    try:
        return json.loads((r.stdout or b"").decode(errors="replace").strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {}


class Api:
    """The first run's JSON API (rouh/web/setup_api.py), as Rouh for Mac calls it."""

    def __init__(self, code: str):
        self.code = code

    def call(self, path: str, body: dict | None = None, *, method: str | None = None, timeout: float = 60) -> tuple[int, dict]:
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(local_url(f"/setup/api/{path}"), data=data, method=method or ("POST" if data else "GET"),
                                     headers={"Authorization": f"Bearer {self.code}", "Accept": "application/json",
                                              **({"Content-Type": "application/json"} if data else {})})
        debug(f"{req.method} /setup/api/{path}")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status, json.loads(r.read() or b"{}")
        except urllib.error.HTTPError as e:
            try:
                return e.code, json.loads(e.read() or b"{}")
            except ValueError:
                return e.code, {"problem": f"Rouh answered {e.code}."}
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            debug(str(e))
            return 0, {"problem": "Rouh is not answering yet. It may still be starting; try again in a moment."}

    def state(self) -> dict:
        status, doc = self.call("state", timeout=90)
        if status != 200:
            raise Stop(doc.get("problem") or "Rouh did not say where setup is.")
        return doc


def public_ip() -> str:
    """This server's address on the internet, as Cloudflare sees it; "" when it cannot be asked."""
    try:
        with urllib.request.urlopen("https://1.1.1.1/cdn-cgi/trace", timeout=8) as r:
            for line in r.read().decode().splitlines():
                if line.startswith("ip="):
                    return line[3:].strip()
    except (OSError, ValueError):
        pass
    return ""


def local_ip() -> str:
    """The address this server reaches the internet from (``ip route get``), which is the one to
    print for an SSH tunnel; a cloud server's first ``hostname -I`` may be a private one."""
    r = run(["ip", "-o", "route", "get", "1.1.1.1"], timeout=10) if shutil.which("ip") else None
    m = re.search(r"\bsrc\s+(\S+)", (r.stdout or b"").decode()) if r is not None and r.returncode == 0 else None
    return m.group(1) if m else ""


def ssh_address() -> str:
    """Where to SSH to from another computer: the public address when this server has it as its
    own, else the one it routes from (a home server behind a router: reach it on the same network)."""
    pub, mine = public_ip(), local_ip()
    if pub and mine and pub == mine:
        return pub
    return mine or pub or (os.uname().nodename)


def user_name() -> str:
    import pwd

    return pwd.getpwuid(os.getuid()).pw_name
