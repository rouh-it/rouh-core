"""CONTAINERS.md: the narrow way from runs to the owner's own servers.

The stack test's settings list one server, the stand-ins' echo on 2222 (ROUH_KEYPROXY_ALLOW),
which stands in for the owner's own ssh server: what reaches it comes back upper case.
"""
from __future__ import annotations

import smoke
from smoke import Stack, check, expect


@check("runs.ssh")
def runs_ssh(s: Stack) -> None:
    """ssh in the worker goes through the key proxy; the listed server is reached, and an
    unlisted port or server is refused."""
    r = s.run("worker", "ssh -G sites.example.com | grep -i '^proxycommand'")
    expect("rouh-connect" in r.stdout, f"ssh in the worker does not go through the key proxy: {r.stdout or r.stderr}")
    r = s.run("worker", "printf 'hello server' | timeout 20 rouh-connect standins 2222")
    expect("HELLO SERVER" in r.stdout, f"the listed server was not reached: {(r.stdout + r.stderr)[-300:]}")
    for host, port in (("standins", 2223), ("example.com", 22)):
        r = s.run("worker", f"printf x | timeout 20 rouh-connect {host} {port}; echo exit=$?")
        expect("exit=0" not in r.stdout and "refused" in r.stderr,
               f"{host}:{port}, not listed, was not refused: {(r.stdout + r.stderr)[-300:]}")


#: What the stack test opens a GitHub grant with: a stand-in, never a token of anybody's. Put
#: together here so the whole of it is in no file: a copy of this one sits in the worker's home
#: (the workspace), and the check that the worker cannot see the token searches there.
STACK_TOKEN = "ghp_" + "stackTestStandIn0123456789"
GRANT = ("ROUH_GRANT_KEYS_DIR=/keys ROUH_GRANT_LOG=/tmp/rouh-grant.log ROUH_GRANT_GITHUB_API=http://standins:9020 "
         "ROUH_GRANT_LIB=/tmp/rouh-grant-lib ROUH_GRANT_STATE=/tmp/rouh-grant-state "
         "ROUH_GRANT_USED_LOG=/tmp/rouh-grant-used.log python3 /code/deploy/grants/host/rouh-grant")
#: Moves every end time in the keys volume's grants to the past, as if the hours had gone by.
ENDED = """python3 - <<'PY'
import json, os, re
for name in ("github_grant.json", "keyproxy_allow_timed", "keyproxy_grants.json"):
    p = "/keys/" + name
    if not os.path.exists(p):
        continue
    os.chmod(p, 0o640)
    text = open(p).read()
    if name == "keyproxy_grants.json":
        g = json.loads(text)
        for one in g.get("grants") or []:
            one["until"] = 1
        text = json.dumps(g)
    elif name.endswith(".json"):
        g = json.loads(text); g["until"] = 1; text = json.dumps(g)
    else:
        text = re.sub(r"^(\\S+) \\d+", r"\\1 1", text, flags=re.M)
    open(p, "w").write(text)
PY"""


def _github(s: Stack, how: str) -> dict:
    """What the stand-in for GitHub was sent, for one request the worker made through the key proxy."""
    r = s.run("worker", how + " -sS --max-time 20 -D /tmp/gh-head -H 'Authorization: token worker-own' "
                              "-H 'Cookie: user_session=worker' ; echo; grep -i '^x-rouh-github-grant' /tmp/gh-head")
    lines = r.stdout.strip().splitlines()
    import json
    try:
        got = json.loads(lines[0])
    except (ValueError, IndexError):
        raise AssertionError(f"the stand-in for GitHub was not reached: {(r.stdout + r.stderr)[-300:]}")
    got["grant"] = lines[-1].split(":", 1)[-1].strip() if len(lines) > 1 else ""
    return got


@check("runs.github")
def runs_github(s: Stack) -> None:
    """GitHub through the key proxy's timed grant (deploy/grants/): with none open a worker's request
    reaches GitHub with nothing added and its own credential taken off; while one is open the
    owner's token is added (a bearer for the API, a password for git), whether the request came
    as http through the proxy or, as gh sends it, with GitHub's name as its Host; after its end
    nothing is added again; and the token is in no log and nowhere the worker can read."""
    api = "curl http://api.github.com/user"
    git = "curl http://github.com/acme/demo.git/info/refs?service=git-upload-pack"
    host = "curl -H 'Host: api.github.com' http://keyproxy:8080/repos/acme/demo"
    s.run("core", f"{GRANT} github revoke")
    got = _github(s, api)
    expect(got["authorization"] == "" and got["cookie"] == "" and got["grant"] == "none",
           f"with no grant, the request reached GitHub as: {got}")
    r = s.run("core", f"printf '%s\\n' {STACK_TOKEN} | {GRANT} github set 1")
    expect(r.returncode == 0 and "open" in r.stdout, f"rouh-grant github set: {(r.stdout + r.stderr)[-300:]}")
    got = _github(s, api)
    expect(got["authorization"] == f"Bearer {STACK_TOKEN}" and got["host"] == "api.github.com"
           and got["grant"].startswith("open until"), f"with a grant open, the API request reached GitHub as: "
                                                        f"{ {**got, 'authorization': got['authorization'][:12]} }")
    import base64
    got = _github(s, git)
    expect(got["authorization"] == "Basic " + base64.b64encode(f"x-access-token:{STACK_TOKEN}".encode()).decode(),
           f"git's request did not carry the token as a password: {got['request']} {got['authorization'][:10]}")
    got = _github(s, host)
    expect(got["authorization"] == f"Bearer {STACK_TOKEN}" and got["request"].startswith("GET /repos/acme/demo"),
           f"a request named by its Host (as gh sends it) was not given the token: {got['request']}")
    r = s.run("worker", f"ls /keys 2>&1; grep -rl {STACK_TOKEN} /home/rouh /run/one /tmp 2>/dev/null | head -3; true")
    expect("No such file" in r.stdout and STACK_TOKEN not in r.stdout and "/" not in r.stdout.replace("/keys", ""),
           f"the worker can see the GitHub token: {r.stdout[-300:]}")
    s.run("core", ENDED)
    got = _github(s, api)
    expect(got["authorization"] == "" and got["grant"] == "ended", f"after its end, the request reached GitHub as: "
                                                                  f"{ {**got, 'authorization': got['authorization'][:12]} }")
    s.run("core", f"{GRANT} prune")
    r = s.run("core", "ls /keys")
    expect("github_grant.json" not in r.stdout, f"the prune did not delete the ended grant: {r.stdout}")
    logs = s.logs("keyproxy", 2000) + s.run("core", "cat /tmp/rouh-grant.log").stdout
    expect(STACK_TOKEN not in logs and base64.b64encode(f"x-access-token:{STACK_TOKEN}".encode()).decode() not in logs,
           "the GitHub token is in a log")


#: Every IPv4 address of the container it runs in, comma separated, loopback left out.
CORE_ADDRESSES = """python3 - <<'PY'
import re
t = open('/proc/net/fib_trie').read()
print(','.join(sorted(set(re.findall(r'\\|-- ([0-9.]+)\\n\\s+/32 host LOCAL', t)) - {'127.0.0.1'})))
PY"""


def _reach(s: Stack, host: str, port: int) -> bool:
    """Whether a worker reaches host:port through the key proxy (the stand-ins' echo says it back)."""
    r = s.run("worker", f"printf 'hello {port}' | timeout 20 rouh-connect {host} {port}; echo exit=$?")
    return f"HELLO {port}" in r.stdout


@check("runs.proxy-grant")
def runs_proxy_grant(s: Stack) -> None:
    """The owner's timed grants (rouh-proxy-grant, deploy/grants/): `all` reaches a public server on a
    port nothing lists and never a private address; it ends at its end and at `revoke`; a name covers
    the names under it; several open in one command; `servers add` puts a server on the list an open
    servers grant covers at once; `lan` reaches the office network but never a container; and every
    connection a grant let through is in the key proxy's log, by grant. The stand-ins'
    public.stack.test, a.sub.public.stack.test and other.stack.test count as public (compose.test.yml);
    standins itself, and every other container, is private."""
    pub, sub, other = "public.stack.test", "a.sub.public.stack.test", "other.stack.test"
    s.run("core", f"{GRANT} revoke all")
    expect(not _reach(s, pub, 2224), f"{pub}:2224 was reached with no grant open")

    r = s.run("core", f"{GRANT} open all 1")
    expect(r.returncode == 0 and "any public server, any port" in r.stdout, f"rouh-grant open all: {(r.stdout + r.stderr)[-300:]}")
    expect(_reach(s, pub, 2224), f"the all grant did not open {pub}:2224")
    expect(not _reach(s, "standins", 2224), "the all grant reached a private address (standins:2224)")
    r = s.run("worker", "timeout 20 rouh-connect core 8021 </dev/null; echo exit=$?")
    expect("refused" in r.stderr, f"the all grant reached the core: {(r.stdout + r.stderr)[-300:]}")
    r = s.run("core", f"{GRANT} list")
    expect("any public server, any port" in r.stdout and "left" in r.stdout, f"rouh-grant list: {r.stdout[-300:]}")
    expect(f"GRANT all CONNECT {pub}:2224" in s.logs("keyproxy", 400), "the connection the all grant let through is not in the log")
    s.run("core", ENDED)
    expect(not _reach(s, pub, 2224), f"{pub}:2224 was reached after the all grant's end")
    s.run("core", f"{GRANT} open all 1")
    expect(_reach(s, pub, 2224), f"the all grant opened again did not open {pub}:2224")
    s.run("core", f"{GRANT} revoke all")
    expect(not _reach(s, pub, 2224), f"{pub}:2224 was reached after revoke all")

    r = s.run("core", f"{GRANT} open ssh {pub} 1")
    expect(r.returncode == 0 and "ssh" in r.stdout and pub in r.stdout, f"rouh-grant open ssh {pub}: {(r.stdout + r.stderr)[-300:]}")
    expect(_reach(s, sub, 2224), f"the name grant {pub} did not cover {sub}:2224")
    expect(_reach(s, other, 2222), f"the ssh grant did not open {other}:2222")
    expect(not _reach(s, other, 2224), f"{other}:2224 was reached with only ssh and {pub} open")
    expect(f"GRANT name {pub} CONNECT {sub}:2224" in s.logs("keyproxy", 400)
           and f"GRANT ssh CONNECT {other}:2222" in s.logs("keyproxy", 400), "the log does not say which grant let them through")
    s.run("core", f"{GRANT} revoke ssh")
    expect(not _reach(s, other, 2222) and _reach(s, sub, 2224), "revoke ssh did not close ssh alone")
    s.run("core", f"{GRANT} revoke all")

    r = s.run("core", f"{GRANT} servers add {other} 1.1.1.1")
    expect(r.returncode == 0, f"rouh-grant servers add: {(r.stdout + r.stderr)[-300:]}")
    r = s.run("core", f"{GRANT} servers list")
    expect(f"{other} (1.1.1.1)" in r.stdout, f"rouh-grant servers list: {r.stdout[-300:]}")
    s.run("core", f"{GRANT} open servers 1")
    expect(_reach(s, other, 2224), f"the servers grant did not open {other}, which servers add put on the list")
    expect(not _reach(s, pub, 2224), f"the servers grant opened {pub}, which is not on the list")
    s.run("core", f"{GRANT} servers remove {other}")
    expect(not _reach(s, other, 2224), f"{other} was reached after servers remove")
    s.run("core", f"{GRANT} revoke all")

    # The office network: here the stand-ins' network stands in for it, and every address of the
    # core stands in for the containers' networks, which a lan grant never reaches.
    standins = s.run("core", "python3 -c \"import socket; print(socket.gethostbyname('standins'))\"").stdout.strip()
    core_ips = s.run("core", CORE_ADDRESSES).stdout.strip()
    expect(standins.count(".") == 3 and core_ips, f"the stand-ins' address ({standins}) or the core's ({core_ips}) is not known")
    office = standins.rsplit(".", 1)[0] + ".0/24"
    lan = f"ROUH_GRANT_LAN_NETS={office} ROUH_GRANT_LAN_DENY={','.join(a + '/32' for a in core_ips.split(','))} "
    expect(not _reach(s, "standins", 2224), "standins:2224 was reached with no lan grant")
    r = s.run("core", f"{lan}{GRANT} open lan 1")
    expect(r.returncode == 0 and "office network" in r.stdout, f"rouh-grant open lan: {(r.stdout + r.stderr)[-300:]}")
    expect(_reach(s, "standins", 2224), "the lan grant did not open the office network (standins:2224)")
    for host, port in [("core", 8021), *((a, 8021) for a in core_ips.split(",")), ("127.0.0.1", 8080)]:
        r = s.run("worker", f"timeout 20 rouh-connect {host} {port} </dev/null; echo exit=$?")
        expect("refused" in r.stderr, f"the lan grant reached {host}:{port}, a container: {(r.stdout + r.stderr)[-300:]}")
    expect("GRANT lan CONNECT standins:2224" in s.logs("keyproxy", 400), "the lan connection is not in the log")
    s.run("core", f"{lan}{GRANT} revoke all")
    expect(not _reach(s, "standins", 2224), "standins:2224 was reached after the lan grant was closed")
    r = s.run("core", f"{GRANT} log")
    expect(r.returncode == 0, f"rouh-grant log: {(r.stdout + r.stderr)[-300:]}")


@check("crew.tools")
def crew_tools(s: Stack) -> None:
    """The person's work goes to a run of the one program with the tool Rouh uses for it on the
    server, `assistant_job`, and `check_tasks` says how runs are doing, with no crew."""
    got = s.tool("assistant_job", {"request": "SAY: The stack test's job is done.", "title": "Stack test job"})
    expect("There is no tool" not in got and "Traceback" not in got and "nothing was started" not in got.lower(),
           f"assistant_job: {got[:300]}")
    got = s.tool("check_tasks", {})
    expect("Traceback" not in got, f"check_tasks: {got[:300]}")


@check("tool.shell")
def tool_shell(s: Stack) -> None:
    """Rouh's read-only shell answers, and its commands run in the worker, which holds no key."""
    got = s.tool("run_command", {"command": "ls -a"})
    expect("_migration-map.json" in got or ".git" in got, f"run_command did not read the workspace: {got[:300]}")
    got = s.tool("run_command", {"command": "cat /keys/anthropic_api_key"})
    expect("not-a-real-one" not in got, "run_command read a key")
    got = s.tool("run_command", {"command": "hostname"})
    r = s.run("worker", "hostname")
    expect(r.stdout.strip() and r.stdout.strip() in got, f"run_command did not run in the worker: {got[:200]}")


@check("tool.shell-sandbox")
def tool_shell_sandbox(s: Stack) -> None:
    """Each of the shell's commands runs in a box the kernel holds (rouh/sandbox.py: Landlock in the
    worker), required there, behind the narrowed read-only rules: awk, sed, curl and env are refused
    by the rules, the same commands handed to the worker's shell past them are refused by the
    kernel (no file written, no connection), and reading still works."""
    said = s.tool("server_health", {}).replace("\\", "")
    box = said[said.rfind('"sandbox"'):]
    expect('"on": true' in box and '"kind": "landlock"' in box and '"where": "worker"' in box,
           f"server_health does not say the worker's commands run sandboxed: {box[:400] or said[-400:]}")
    r = s.run("worker", "cat /run/one/sandbox.json")
    expect('"mode": "required"' in r.stdout and '"on": true' in r.stdout, f"the worker's box: {r.stdout or r.stderr}")
    # The rules come first: what does more than read is refused before anything runs.
    for command in ("awk 'BEGIN{system(\"touch /tmp/box-awk\")}'", "sed -n 'w /tmp/box-sed' /etc/hostname",
                    "curl -s http://core:8021/healthz", "env", "find /etc/hostname -fls /tmp/box-find",
                    "git -c core.pager=sh log", "sort -o /tmp/box-sort /etc/hostname"):
        got = s.tool("run_command", {"command": command})
        expect(got.lstrip().startswith("Refused."), f"the read-only rules let {command!r} through: {got[:200]}")
    # Then the box, asked directly in the worker as Rouh's shell runs its stages (one/shell.py), past
    # the rules: the kernel refuses the writes and the connection.
    r = s.run("worker", "touch /tmp/box-unboxed && echo wrote && rm /tmp/box-unboxed", user="10001")
    expect("wrote" in r.stdout, f"the worker's own user cannot write /tmp, so the refusals below prove nothing: {r.stderr}")
    r = s.run("worker", "curl -s -o /dev/null -w '%{http_code}' http://core:8021/healthz", user="10001")
    expect(r.stdout.strip() == "200", f"the worker cannot reach the core itself, so the refusal below proves nothing: {r.stdout}")
    r = s.py("worker", """
import os
from one import shell
for stages in ([["awk", 'BEGIN{system("touch /tmp/box-awk")}']], [["sed", "-n", "w /tmp/box-sed", "/etc/hostname"]],
               [["find", "/etc/hostname", "-fls", "/tmp/box-find"]], [["curl", "-sS", "http://core:8021/healthz"]]):
    print("RAN", stages[0][0], shell.run(stages, cwd="/tmp").strip()[:120])
print("FILES", sorted(f for f in os.listdir("/tmp") if f.startswith("box-")))
""", user="10001")
    expect("FILES []" in r.stdout, f"a command in the box wrote a file: {r.stdout[-600:]} {r.stderr[-300:]}")
    expect('"ok"' not in r.stdout and "RAN curl" in r.stdout, f"a command in the box reached the core: {r.stdout[-600:]}")
    got = s.tool("run_command", {"command": "grep -c rouh /etc/passwd"})
    expect(got.strip().splitlines()[0].strip().isdigit(), f"grep in the box: {got[:200]}")
    got = s.tool("run_command", {"command": "ls /code/rouh/sandbox.py"})
    expect("sandbox.py" in got, f"ls in the box: {got[:200]}")


@check("walls.core-cannot-change-guard")
def core_cannot_change_guard(s: Stack) -> None:
    """The protected core's files are read-only to the core and the worker, whoever runs there."""
    for svc in ("core", "worker"):
        r = s.run(svc, "touch /opt/rouh-guard/bin/rouh-check 2>&1; echo exit=$?", user="10001")
        expect("exit=0" not in r.stdout, f"{svc} could change the protected core's files")
        r = s.run(svc, "touch /opt/rouh-guard/written-by-rouh 2>&1; echo exit=$?", user="10001")
        expect("exit=0" not in r.stdout, f"{svc} could add a file to the protected core")


@check("one.attach-late")
def one_attach_late(s: Stack) -> None:
    """Rouh started before the worker paired with it still finds the one program: the pairing is
    taken away, Rouh started again without it, and the pairing put back."""
    import subprocess
    import time

    s.run("worker", "mv /run/one/voice.json /run/one/voice.json.aside")
    subprocess.run([*s.compose, "restart", "core"], capture_output=True, timeout=300)
    end = time.time() + 400
    time.sleep(10)
    while time.time() < end:
        try:
            code, body, _ = s.get("/healthz", cookie=False)
        except OSError:
            code, body = 0, ""
        if code == 200 and '"ok":true' in body.replace(" ", ""):
            break
        time.sleep(5)
    s.run("worker", "mv /run/one/voice.json.aside /run/one/voice.json")
    s.ws = None
    end = time.time() + 120
    got = ""
    while time.time() < end:
        try:
            got = s.tool("one_runs", {})
            if "There is no tool" not in got:
                return
        except Exception as e:  # noqa: BLE001 - the socket comes back with Rouh
            got = str(e)
            s.ws = None
        time.sleep(10)
    raise AssertionError(f"Rouh did not find the one program after it paired late: {got[:300]}")


smoke.LAST.add("one.attach-late")
smoke.LIMIT.update({"one.attach-late": 600})


@check("machine.ups")
def machine_ups(s: Stack) -> None:
    """The orb's power reading: the UPS NUT watches, read over NUT's own protocol from the core."""
    import json

    code, body, _ = s.get("/api/machine/load")
    expect(code == 200, f"/api/machine/load answered {code}")
    power = json.loads(body).get("power") or {}
    expect(power.get("on_battery") is True and power.get("charge") == 57, f"the UPS was not read: {body[:300]}")


@check("self.gene-grow")
def gene_grow(s: Stack) -> None:
    """A gene drafted and grown: the grow starts a run in a clone of Rouh's code, whose ./land.sh
    hands its work to the protected core in the containers (bin/rouh-land)."""
    import re

    got = s.tool("gene_draft", {"action": "draft", "name": "Stack test gene", "what": "A gene the stack test drafts",
                                "where": "nowhere yet"})
    m = re.search(r"(?:draft|gene)\D{0,20}(\d+)", got, re.I)
    expect(m, f"the draft did not say its number: {got[:300]}")
    got = s.tool("gene_draft", {"action": "grow", "gene": int(m.group(1))})
    expect("Traceback" not in got and "could not" not in got.lower() and "cannot" not in got.lower(),
           f"growing the gene: {got[:300]}")
