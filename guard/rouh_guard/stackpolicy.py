"""The stack check: what a Rouh's own stack file may ask for (task 98, step 98-23).

Since 24 October 2026 a Rouh's stack file is its own (``/code/deploy/stack/compose.yml``): it may
swap its database, add a service, give a container more memory, and no update replaces it. What
it may not do is reach past the walls. So before a stack file is applied, the app that applies it
(Rouh for Mac, in Swift: ``StackPolicy.swift``; on Linux ``deploy/container/linux_stack.py``, which
runs this file out of the release's guard image, pinned by digest, with no network) runs
``docker compose config`` - which prints the file with every setting filled in - and holds the
result to an allow-list (``guard/policy/stack-policy.json``). Anything not on it is refused, each
with one plain sentence:

* privileged; host network, pid, ipc, userns or cgroup; seccomp or apparmor unconfined (any
  security_opt but no-new-privileges); devices; sysctls; capabilities beyond today's list;
* bind mounts, the Docker socket, image mounts, and volumes that are really binds (a driver or
  driver options, or an external volume);
* a published port on anything but 127.0.0.1;
* any change to the protected core's services (guard-init, guard, keyproxy, code-install,
  checkdb, worker-perms) or to the walls' networks, and a protected volume mounted where it was not;
* a build that is not a plain Dockerfile on top of the release's base, with no extra rights;
* anything that reads a file of the machine into the stack while Compose resolves it: ``include``,
  ``extends`` and ``label_file`` (refused in the stack file's own text, with the YAML escapes and
  tags that could spell them otherwise), and an ``env_file`` other than the release's own settings
  file or a file in the stack's own folder. Compose folds all four into the resolved file, so the
  resolved file alone cannot show them (task 158, proved on Compose 2.38.2 and 5.6.0); both apps
  resolve with ``--no-env-resolution`` so an ``env_file`` stays visible, and on Linux the Rouh's own
  stack is resolved in a sealed container that sees nothing of the machine (linux_stack.py).

The protected parts are compared with the release's own stack file, resolved the same way
(``reference``), so the Rouh can change everything else and nothing of those.

    python3 stackpolicy.py check --stack DIR --env-file stack.env --env-file release.env \\
        --reference REFERENCE.yml [--policy stack-policy.json]

prints each refusal and exits 1, or says the stack may be applied and exits 0; an allow-list of a
format other than 1 is refused too. Then, on Linux, linux_stack.py starts it. Standard library only.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
#: Settings refused with a sentence of their own rather than as unknown.
SAID_ON_ITS_OWN = {"privileged", "pid", "ipc", "userns_mode", "cgroup", "uts", "devices", "sysctls", "env_file"}
#: Ways a YAML file can spell a key without writing it out: escapes that make letters, an escaped
#: line break that joins two halves, and tags (``!!binary``, a verbatim ``!<...>``, a %TAG directive).
HIDDEN = [(re.compile(r"\\[xuU]|\\\r?\n"), "spells something with a backslash escape"),
          (re.compile(r"!!|!<|^%TAG", re.M), "uses a YAML tag")]
BOMS = (b"\xef\xbb\xbf", b"\xff\xfe", b"\xfe\xff")
POLICY = HERE / "policy" / "stack-policy.json"


def load_policy(path: Path | None = None) -> dict:
    """The allow-list, refused unless it is of format 1, the only one this check knows: a policy
    of a newer format may mean something this check would not hold a stack to (Rouh for Mac's
    StackPolicy.policy says the same)."""
    p = json.loads((path or POLICY).read_text())
    if not isinstance(p, dict) or p.get("format") != 1:
        raise SystemExit("the stack check's allow-list is not of format 1, the one this check knows")
    return p


def _mode(v: dict) -> str:
    return "ro" if v.get("read_only") else "rw"


def _froms(dockerfile: str) -> list[str]:
    """Every image a Dockerfile builds FROM, with build-args left as they are."""
    out, stages = [], set()
    for line in dockerfile.splitlines():
        m = re.match(r"^\s*FROM\s+(?:--platform=\S+\s+)?(\S+)(?:\s+AS\s+(\S+))?\s*$", line, re.I)
        if m:
            src = m.group(1)
            out.append("" if src.lower() in stages else src)
            if m.group(2):
                stages.add(m.group(2).lower())
    return out


def _dockerfile_problems(build: dict, base: str, stack_dir: Path | None) -> list[str]:
    ctx = Path(str(build.get("context") or ""))
    if stack_dir is None:
        return ["a service is built from a Dockerfile, and there is no stack folder to read it from"]
    try:
        ctx.resolve().relative_to(stack_dir.resolve())
    except ValueError:
        return [f"a build reaches outside the stack's own folder ({ctx})"]
    df = (ctx / str(build.get("dockerfile") or "Dockerfile")).resolve()
    try:
        df.relative_to(stack_dir.resolve())
        text = df.read_text()
    except (ValueError, OSError):
        return [f"its Dockerfile is not in the stack's own folder ({df.name})"]
    out = []
    froms = [f for f in _froms(text) if f]
    if not froms:
        out.append(f"{df.name} builds from nothing this check can name")
    for f in froms:
        if f not in (base, "${ROUH_BASE_IMAGE}", "$ROUH_BASE_IMAGE"):
            out.append(f"{df.name} builds FROM {f}, and a Rouh's own image is built only on its base")
    for line in text.splitlines():
        if re.match(r"^\s*RUN\b.*--(network|security)=", line, re.I):
            out.append(f"{df.name} asks for {line.strip()[:60]}, which a build here never gets")
    return out


def text_problems(data: bytes, words: list[str]) -> list[str]:
    """What the stack file's own text asks for that its resolved form no longer shows."""
    if b"\0" in data or data.startswith(BOMS):
        return ["the stack file is not plain UTF-8 text"]
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return ["the stack file is not plain UTF-8 text"]
    out = [f"the stack file uses {w!r}, which reads another file of the machine into it" for w in words if w in text]
    out += [f"the stack file {why}, which could hide a key this check refuses" for rx, why in HIDDEN if rx.search(text)]
    return out


def _paths(env_file) -> list[str]:
    items = env_file if isinstance(env_file, list) else [env_file] if env_file else []
    return [str(i.get("path") if isinstance(i, dict) else i) for i in items]


def check(resolved: dict, reference: dict, policy: dict | None = None, *, base: str = "",
          stack_dir: Path | None = None, text: bytes | None = None) -> list[str]:
    """Every refusal for this resolved stack file, in plain sentences; empty when it may be applied.
    text is the stack file as written (read from stack_dir/compose.yml when not given)."""
    p = policy or load_policy()
    out: list[str] = []
    if text is None and stack_dir is not None:
        try:
            text = (stack_dir / "compose.yml").read_bytes()
        except OSError:
            out.append("the stack folder has no compose.yml to read")
    if text is not None:
        out += text_problems(text, p.get("refused_words", []))
    services = resolved.get("services") or {}
    ref_services = reference.get("services") or {}
    nets = resolved.get("networks") or {}
    ref_nets = reference.get("networks") or {}
    vols = resolved.get("volumes") or {}
    base = base or str((ref_services.get("core") or {}).get("image") or "")

    for key in resolved:
        if key not in p["top_level"] and not key.startswith("x-"):
            out.append(f"the stack file has {key!r} at its top, which is not allowed (only services, networks and volumes)")

    # The walls' networks, exactly as released; any other network is internal and plain.
    for name in p["protected_networks"]:
        if name not in ref_nets:
            continue
        if nets.get(name) != ref_nets[name]:
            out.append(f"the network {name!r} is not as released: it is one of the walls")
    for name, n in nets.items():
        if name in p["protected_networks"]:
            continue
        for k in n:
            if k not in p["network_keys"]:
                out.append(f"the network {name!r} sets {k!r}, which is not allowed")
        if n.get("external"):
            out.append(f"the network {name!r} is outside the stack (external)")
        if n.get("driver") and n["driver"] not in p["network_drivers"]:
            out.append(f"the network {name!r} uses the driver {n['driver']!r}")
        if not n.get("internal"):
            out.append(f"the network {name!r} is not internal: a network of the Rouh's own has no way out")
        if (n.get("ipam") or {}) not in ({},):
            out.append(f"the network {name!r} sets its addresses (ipam), which is not allowed")

    # Volumes: plain named volumes only.
    for name, v in vols.items():
        for k in v:
            if k not in p["volume_keys"]:
                out.append(f"the volume {name!r} sets {k!r}, which can make it a folder of the machine's own")
        if v.get("driver") and v["driver"] not in p["volume_drivers"]:
            out.append(f"the volume {name!r} uses the driver {v['driver']!r}")

    for name in p["required_services"]:
        if name in ref_services and name not in services:
            out.append(f"the service {name!r} is gone, and it is one the stack cannot run without")

    for name, s in services.items():
        where = f"the service {name!r}"
        if name in p["protected_services"]:
            if s != ref_services.get(name):
                out.append(f"{where} is not as released: it is part of the protected core")
            continue
        ref = ref_services.get(name) or {}
        for k in s:
            if k not in p["service_keys"] and k not in SAID_ON_ITS_OWN:
                out.append(f"{where} sets {k!r}, which is not allowed")
        for k in p["pinned"].get(name, []):
            if s.get(k) != ref.get(k):
                out.append(f"{where} changes its {k}, which is the protected core's to say")
        if s.get("privileged"):
            out.append(f"{where} asks to be privileged")
        mode = s.get("network_mode")
        if mode is not None and mode not in p["network_modes"]:
            out.append(f"{where} asks for network_mode {mode!r}")
        for k in ("pid", "ipc", "userns_mode", "cgroup", "uts"):
            if s.get(k):
                out.append(f"{where} asks for {k} {s[k]!r}")
        if s.get("devices"):
            out.append(f"{where} asks for devices")
        if s.get("sysctls"):
            out.append(f"{where} asks for kernel settings (sysctls)")
        released = _paths(ref.get("env_file"))
        for path in _paths(s.get("env_file")):
            inside = stack_dir is not None and Path(path).resolve().is_relative_to(stack_dir.resolve())
            if path not in released and not inside:
                out.append(f"{where} reads {path} into its settings (env_file), a file outside its own folder")
        for opt in s.get("security_opt") or []:
            if opt not in p["security_opt"]:
                out.append(f"{where} asks for security_opt {opt!r}")
        for cap in s.get("cap_add") or []:
            c = str(cap).upper().removeprefix("CAP_")
            if c not in p["cap_add"]:
                out.append(f"{where} asks for the capability {c}")
        drv = (s.get("logging") or {}).get("driver")
        if drv and drv not in p["logging_drivers"]:
            out.append(f"{where} sends its log through {drv!r}")
        if s.get("restart") and str(s["restart"]).split(":")[0] not in p["restart"]:
            out.append(f"{where} asks for restart {s['restart']!r}")

        # Networks: the walls' own are joined only by their own; the Rouh's own are internal.
        for net in (s.get("networks") or {}):
            only = p["network_only"].get(net)
            if only is not None and name not in only:
                out.append(f"{where} joins {net!r}, which only {', '.join(only)} may")

        # Mounts.
        for v in s.get("volumes") or []:
            kind = v.get("type")
            src = str(v.get("source") or "")
            if kind not in p["volume_types"]:
                why = "the Docker socket" if "docker.sock" in src or "docker.sock" in str(v.get("target")) else \
                      f"{'an' if str(kind)[:1] in 'aeiou' else 'a'} {kind} mount" + (f" of {src}" if src else "")
                out.append(f"{where} mounts {why}; only named volumes are allowed")
                continue
            if kind == "volume":
                if src not in vols:
                    out.append(f"{where} mounts {src!r}, which is not one of the stack's named volumes")
                    continue
                rule = p["protected_volumes"].get(src)
                if rule is not None:
                    want = rule.get(name)
                    if want is None:
                        out.append(f"{where} mounts {src!r}, which only {', '.join(rule)} may")
                    elif want == "ro" and _mode(v) != "ro":
                        out.append(f"{where} mounts {src!r} so it can write it; it may only read it")
                if (v.get("volume") or {}).get("subpath") and rule is not None:
                    out.append(f"{where} mounts part of {src!r}")
        # Ports, on this machine only.
        for port in s.get("ports") or []:
            ip = str(port.get("host_ip") or "") if isinstance(port, dict) else ""
            if port.get("published") if isinstance(port, dict) else True:
                if ip not in p["published_host_ips"]:
                    out.append(f"{where} publishes a port on {ip or 'every address'}; only 127.0.0.1 is allowed")

        # Images and builds.
        build = s.get("build")
        if build is not None:
            for k in build:
                if k not in p["build_keys"]:
                    out.append(f"{where} builds with {k!r}, which is not allowed")
            out += [f"{where}: {why}" for why in _dockerfile_problems(build, base, stack_dir)]
        elif name in p["base_image_services"] and s.get("image") != base:
            out.append(f"{where} runs {s.get('image')!r}; it runs on the release's base, or on an image built on it")
    return out


def resolve(stack: Path, env_files: list[str], project: str = "rouh") -> dict:
    cmd = ["docker", "compose", "--project-name", project, "-f", str(stack)]
    for e in env_files:
        cmd += ["--env-file", e]
    r = subprocess.run(cmd + ["config", "--format", "json"], capture_output=True, text=True)
    if r.returncode:
        raise SystemExit(f"docker compose could not read the stack file: {r.stderr.strip()[-400:]}")
    return json.loads(r.stdout)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="stackpolicy.py", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check")
    c.add_argument("--stack", required=True, help="the folder of the Rouh's own stack file (compose.yml)")
    c.add_argument("--reference", required=True, help="the release's own stack file")
    c.add_argument("--env-file", action="append", default=[])
    c.add_argument("--policy")
    c.add_argument("--resolved", help="an already resolved stack file (JSON), instead of running docker compose")
    c.add_argument("--resolved-reference")
    a = ap.parse_args(argv)
    stack = Path(a.stack)
    got = json.loads(Path(a.resolved).read_text()) if a.resolved else resolve(stack / "compose.yml", a.env_file)
    ref = json.loads(Path(a.resolved_reference).read_text()) if a.resolved_reference else resolve(Path(a.reference), a.env_file)
    problems = check(got, ref, load_policy(Path(a.policy) if a.policy else None), stack_dir=stack)
    if not (stack / "compose.yml").is_file():
        problems = problems or ["the stack folder has no compose.yml to read"]
    for line in problems:
        print(f"refused: {line}")
    if problems:
        print(f"The stack file was not applied: {len(problems)} thing{'s' if len(problems) != 1 else ''} in it "
              "are not allowed.")
        return 1
    print("The stack file may be applied.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
