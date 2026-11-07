"""CONTAINERS.md: Rouh's own nightly work, started from Clockwork as the night would start it.

Each job is a row of Rouh's own scheduled work on the Clockwork page; pressing Try it now there
(`/api/reminders/act`, `try`) starts it exactly as its time would. A job's run works in the worker
and reaches Rouh with the worker's key, and lands through the protected core (`self.improve`).
"""
from __future__ import annotations

import json
import time
import urllib.request

import smoke
from smoke import Failed, Stack, check, expect


def _csrf(s: Stack) -> str:
    for part in s.cookie.split(";"):
        name, _, value = part.strip().partition("=")
        if name == "rouh_csrftoken":
            return value
    return ""


def _post(s: Stack, path: str, body: dict) -> dict:
    req = urllib.request.Request(s.url + path, data=json.dumps(body).encode(), method="POST",
                                 headers={"Cookie": s.cookie, "Content-Type": "application/json",
                                          "X-CSRFToken": _csrf(s), "Origin": s.url, "Referer": s.url + "/clockwork"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read() or b"{}")


def _row(s: Stack, title: str) -> dict:
    code, body, _ = s.get("/api/reminders")
    expect(code == 200, f"/api/reminders answered {code}")
    rows = [r for r in json.loads(body).get("reminders", []) if r.get("title") == title]
    expect(rows, f"there is no row {title!r} on Clockwork: {[r.get('title') for r in json.loads(body).get('reminders', [])]}")
    return rows[0]


def _nightly_row(s: Stack, title: str) -> dict:
    """The nightly feature run's row, as its own page shows it (`/api/evolution/nightly`)."""
    code, body, _ = s.get("/api/evolution/nightly")
    expect(code == 200, f"/api/evolution/nightly answered {code}")
    row = json.loads(body).get("schedule") or {}
    expect(row.get("id") and row.get("title") == title, f"the nightly page has no row {title!r}: {row}")
    return row


def try_job(s: Stack, title: str, limit: float = 180, row_of=None) -> str:
    """Try it now, and what the row then says it did."""
    _row_of = row_of or _row
    row = _row_of(s, title)
    before = (row.get("fired") or 0, row.get("last_said") or "")
    got = _post(s, "/api/reminders/act", {"id": row["id"], "act": "try"})
    expect(got.get("ok"), f"Try it now on {title!r}: {got}")
    end = time.time() + limit
    while time.time() < end:
        row = _row_of(s, title)
        now = (row.get("fired") or 0, row.get("last_said") or "")
        if now != before and now[1]:
            return now[1]
        time.sleep(5)
    raise Failed(f"{title!r} said nothing after Try it now: {row}")


_BAD = ("could not", "cannot", "failed", "traceback", "refused", "not reach", "no one program", "403")


@check("nightly.refactor")
def nightly_refactor(s: Stack) -> None:
    said = try_job(s, "Nightly code refactoring run")
    expect(not any(b in said.lower() for b in _BAD), f"the nightly refactoring run: {said[:300]}")


@check("nightly.synapse")
def nightly_synapse(s: Stack) -> None:
    """Synapse's nightly experiment, for a person with a Synapse Master: the Master made as an
    administrator makes it (`manage.py synapse_master make`), Rouh started again, and its row
    then on Clockwork, started by Try it now."""
    import subprocess

    owner = s.manage("from rouh.models import User\n"
                     "print(User.objects.filter(is_active=True, is_guest=False).order_by('date_joined').first().pk)").strip().splitlines()[-1]
    r = s.run("core", f"cd /code && python manage.py synapse_master make --user {owner}", timeout=300)
    expect(r.returncode == 0, f"the Synapse Master could not be made: {(r.stderr or r.stdout)[-300:]}")
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
    end = time.time() + 120
    found = []
    while time.time() < end and not found:
        code, body, _ = s.get("/api/reminders")
        titles = [r.get("title") for r in json.loads(body).get("reminders", [])] if code == 200 else []
        found = [t for t in titles if t and "synapse" in t.lower() and "dream" not in t.lower()]
        time.sleep(5)
    expect(found, f"Synapse's nightly experiment is not on Clockwork: {titles}")
    said = try_job(s, found[0])
    expect(not any(b in said.lower() for b in _BAD), f"Synapse's nightly experiment: {said[:300]}")


smoke.LAST.add("nightly.synapse")
smoke.LIMIT.update({"nightly.synapse": 900, "nightly.feature": 420})


@check("nightly.callbacks", "nightly.case-fix")
def nightly_callbacks(s: Stack) -> None:
    """The nightly runs' own tools (`nightly_*`, `refactor_done`, `case_fix_*`) answer a run in the
    worker: each address is reached with the worker's key, and asks who the run is."""
    r = s.py("worker", """
import json, urllib.request
key = json.load(open("/run/one/rouh-worker.json"))
opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
for path in ("nightly", "refactoring", "casefix"):
    req = urllib.request.Request(key["url"] + "/internal/" + path, method="POST",
        data=json.dumps({"job": "stacktest", "action": "whoami", "args": {}}).encode(),
        headers={"Content-Type": "application/json", "X-Rouh-Worker-Key": key["token"]})
    try:
        code = opener.open(req, timeout=20).status
    except urllib.error.HTTPError as e:
        code = e.code
    print(path, code)
""")
    lines = dict(line.split() for line in r.stdout.splitlines() if len(line.split()) == 2)
    expect(lines and all(code != "403" for code in lines.values()),
           f"a nightly run's tools are refused from the worker: {r.stdout or r.stderr}")


@check("nightly.feature")
def nightly_feature(s: Stack) -> None:
    """The nightly feature run, once its home task is in the workspace, as it is set up there."""
    s.chat = ""
    s.tool("make_a_task", {"title": "Nightly Rouh feature run"})
    out = s.manage("from rouh import nightly_feature, telegram\n"
                   "from rouh.tenancy import Tenancy\n"
                   "import time\n"
                   "for _ in range(30):\n"
                   "    if nightly_feature.task_folder(): break\n"
                   "    time.sleep(2)\n"
                   "print('row', nightly_feature.ensure(telegram.phone_owner(Tenancy())) is not None)", timeout=180)
    expect("row True" in out, f"the nightly feature run's row could not be made: {out[-300:]}")
    # Its row is off Clockwork's list since the Incubator (7f6c3960), and is the nightly page's
    # schedule (`rouh/web/nightly_run.py`), which Try it now still acts on by its id.
    said = try_job(s, "Nightly Rouh feature run", row_of=_nightly_row)
    expect(not any(b in said.lower() for b in _BAD), f"the nightly feature run: {said[:300]}")
