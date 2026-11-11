"""CONTAINERS.md: Rouh's updates (rouh/code_update.py, task 140, step 140-18).

The stack's Rouh is made an older one: its code says it came from a release (.git/rouh-installed.json,
as a first start writes it), it gets two genes of its own - one the release does not touch, one that
changes the same line of README.md the release changes - and a stand-in for rouh.land (port 9021 of
the stand-ins, `ROUH_CODE_RELEASE_URL` and `ROUH_CODE_TARBALL` in settings.env) serves a newer release
built from that same code, as GitHub's tarball of a commit is (`git archive`, which names its commit).

    updates.press   Update to the newest Rouh, pressed on Meta, Changes: the release's files come in,
                    the gene is kept, the clashing gene's file stays as it was and is named, the
                    protected core makes it an undo point, Rouh starts again, and General says so
    updates.ride    Ride along, for a Connected Rouh: a second release is taken by itself at a quiet
                    moment, with no press
"""
from __future__ import annotations

import json
import time

import smoke
from smoke import Failed, Stack, check, expect

CODE = "git -c safe.directory='*' -C /code"
SERVE = "/tmp/release"
_DONE: dict = {}


def _release(s: Stack, n: int, script: str) -> str:
    """A release built in the stand-ins from this Rouh's first commit (n=1) or the release before,
    served at standins:9021; its commit."""
    r = s.run("standins", f"""set -e
cd /tmp
if [ ! -d rel ]; then
  git clone -q /tmp/git/rouh-core.git rel
  cd rel && git checkout -q -B release "$(git rev-list --max-parents=0 HEAD)" && cd ..
fi
cd rel
{script}
git add -A
git -c user.name=Rouh -c user.email=rouh@localhost commit -q -m "Stack release {n}"
sha=$(git rev-parse HEAD)
mkdir -p {SERVE}/mac/code {SERVE}/tarball
git archive --format=tar.gz --prefix=rouh-core-$sha/ $sha > {SERVE}/tarball/$sha
python3 - "$sha" <<'PY'
import json, sys, os
sha = sys.argv[1]
path = "{SERVE}/mac/code/release.json"
old = json.load(open(path)) if os.path.exists(path) else {{"recent": []}}
row = {{"commit": sha, "version": 20261112000000 + {n}, "released_at": "2026-11-1{n}T03:00:00Z",
       "live_since": "2026-11-1{n - 1}T03:00:00Z", "notes": ["Stack release {n}"]}}
json.dump({{"ok": True, **row, "recent": [row] + old.get("recent", [])}}, open(path, "w"))
PY
if ! (exec 3<>/dev/tcp/127.0.0.1/9021) 2>/dev/null; then
  nohup python3 -m http.server 9021 --directory {SERVE} >/tmp/release-server.log 2>&1 &
  sleep 1
fi
echo "$sha"
""", timeout=180)
    if r.returncode:
        raise Failed(f"the stand-in release {n} could not be made: {(r.stderr or r.stdout)[-600:]}")
    return r.stdout.strip().splitlines()[-1]


def _again(fn, limit: float = 300):
    """fn(), tried again while Rouh is starting again (an update or a gene going live restarts it)."""
    end = time.time() + limit
    while True:
        try:
            return fn()
        except (OSError, ValueError) as e:
            if time.time() > end:
                raise Failed(f"Rouh did not answer for {int(limit)} s: {e}") from None
            time.sleep(5)


def _updates(s: Stack, look: bool = False) -> dict:
    def one():
        code, body, _ = s.get("/api/settings/updates" + ("?look=1" if look else ""))
        if code in (502, 503, 504):
            raise OSError(f"it answered {code}")
        expect(code == 200, f"/api/settings/updates answered {code}: {body[:300]}")
        return json.loads(body)
    return _again(one)


def _post_again(s: Stack, path: str, body: dict) -> dict:
    from checks_nightly import _post

    return _again(lambda: _post(s, path, body))


def _healthy(s: Stack, limit: float = 600) -> None:
    end = time.time() + limit
    while time.time() < end:
        try:
            code, body, _ = s.get("/healthz", cookie=False)
        except OSError:
            code, body = 0, ""
        if code == 200 and '"ok":true' in body.replace(" ", ""):
            return
        time.sleep(5)
    raise Failed("Rouh did not answer again after the update")


def _until_updated(s: Stack, want: str, limit: float, why: str) -> dict:
    end = time.time() + limit
    last: dict = {}
    while time.time() < end:
        try:
            last = _updates(s)
        except (Failed, OSError, ValueError):
            time.sleep(5)
            continue
        if (last.get("current") or {}).get("commit") == want and not last.get("pending") and not last.get("busy"):
            return last
        if (last.get("last") or {}).get("ok") is False and (last["last"].get("release") == want):
            raise Failed(f"{why}: it did not update: {last['last'].get('said')}")
        time.sleep(10)
    raise Failed(f"{why}: still {json.dumps({k: last.get(k) for k in ('current', 'busy', 'pending', 'last', 'why_not', 'ride')})[:900]}; "
                 f"the guard said: {s.logs('guard', 40)[-900:]}")


def _general_says(s: Stack, words: str, limit: float = 180) -> str:
    end = time.time() + limit
    while time.time() < end:
        out = s.manage(f"""
from rouh.models.memory import TranscriptMessage
from rouh.models.objects import ChatMessage
said = [m.content for m in TranscriptMessage.objects.filter(session_id="conversation", content__contains={words!r}).order_by("-id")[:1]]
said += [m.body for m in ChatMessage.objects.filter(chat_id="conversation", body__contains={words!r}).order_by("-seq")[:1]]
print(said[0][:2000] if said else "")
""").strip()
        if out:
            return out
        time.sleep(5)
    raise Failed(f"General never said {words!r}")


def _older(s: Stack) -> str:
    """This Rouh made an older one with two genes of its own; the release it came from."""
    root = s.run("core", f"{CODE} rev-list --max-parents=0 HEAD").stdout.split()[0]
    came_from = "c0ffee" + root[6:]
    r = s.run("core", f"""set -e
printf '{{"commit": "{came_from}", "named_by": "the stack test"}}\\n' > /code/.git/rouh-installed.json
rm -rf /tmp/genes && git -c safe.directory='*' clone -q /code /tmp/genes && cd /tmp/genes
mkdir -p docs && printf 'A gene of this Rouh own.\\n' > docs/stack-gene.md && git add -A
git -c user.name=Rouh -c user.email=rouh@localhost commit -q -m "A gene of its own" -m "Gene: stack-keep"
sed -i '1s/.*/# Rouh (this Rouh own words)/' README.md && git add -A
git -c user.name=Rouh -c user.email=rouh@localhost commit -q -m "Its own words at the top" -m "Gene: stack-clash"
{CODE} fetch -q /tmp/genes +HEAD:refs/proposals/stack-genes
{CODE} rev-parse refs/proposals/stack-genes
""", user="10001:10001", env={"HOME": "/tmp"})
    expect(r.returncode == 0, f"the genes could not be made: {(r.stderr or r.stdout)[-400:]}")
    genes = r.stdout.strip().splitlines()[-1]
    got = s.manage(f"""
from rouh import guardface
print(guardface.ask("propose", commit={genes!r}, why="the stack test's two genes", by="the stack test", timeout=1800.0))
""", timeout=1900)
    expect("'ok': True" in got, f"the genes did not go live: {got[-600:]}")
    # Rouh starts again on them once the answers in progress are over: let it, then wait for it.
    time.sleep(30)
    _healthy(s)
    return came_from


def _press(s: Stack) -> None:
    came_from = _older(s)
    _post_again(s, "/api/settings/updates/mode", {"mode": "press"})
    before = _updates(s)
    expect((before.get("current") or {}).get("commit") == came_from, f"this Rouh does not say it came from the old release: {before.get('current')}")
    r1 = _release(s, 1, "mkdir -p docs && printf 'New in release 1.\\n' > docs/stack-release-1.md\n"
                        "sed -i '1s/.*/# Rouh (release 1 words)/' README.md")
    seen = _updates(s, look=True)
    expect((seen.get("newest") or {}).get("commit") == r1, f"the newest release is not the stand-in's: {seen.get('newest')} {seen.get('check_error')}")
    expect(not seen.get("up_to_date") and "Stack release 1" in (seen.get("whats_new") or []),
           f"it does not say what is new: {seen.get('whats_new')}")
    expect(not seen.get("why_not"), f"it says it cannot update: {seen.get('why_not')}")
    started = _post_again(s, "/api/settings/updates/now", {})
    expect(started.get("ok"), f"Update to the newest Rouh: {started}")
    after = _until_updated(s, r1, 1800, "the pressed update")
    time.sleep(20)
    _healthy(s)
    files = s.run("core", "cat /code/docs/stack-release-1.md /code/docs/stack-gene.md; head -1 /code/README.md").stdout
    expect("New in release 1" in files, f"the release's file is not in the code: {files}")
    expect("A gene of this Rouh own" in files, f"the gene of its own was lost: {files}")
    expect("this Rouh own words" in files and "release 1 words" not in files, f"the clashing gene's file was overwritten: {files}")
    kept = (after.get("last") or {}).get("kept") or []
    expect(any(k.get("file") == "README.md" and "the gene stack-clash" in (k.get("genes") or []) for k in kept),
           f"the clashing gene was not named: {after.get('last')}")
    said = _general_says(s, "Rouh updated itself to")
    expect("stack-clash" in said and "README.md" in said, f"General's note does not name the clash: {said}")
    points = s.manage("from rouh import guardface\nprint(guardface.ask('status')['code']['point'])")
    expect("Rouh's update" in points, f"the update is not the undo point that runs: {points[-400:]}")


@check("updates.press")
def updates_press(s: Stack) -> None:
    if "press" in _DONE:
        if _DONE["press"]:
            raise Failed(_DONE["press"])
        return
    try:
        _press(s)
        _DONE["press"] = ""
    except Exception as e:  # noqa: BLE001
        _DONE["press"] = str(e)[:900]
        raise


@check("updates.ride")
def updates_ride(s: Stack) -> None:
    updates_press(s)
    # Ride along is for a Connected Rouh: the stack's first run chose On its own, which asks nobody.
    s.manage("""
from rouh import relay
from rouh.web import firstrun
firstrun._save(relay.owner(), connected=True)
""")
    try:
        r2 = _release(s, 2, "printf 'New in release 2.\\n' > docs/stack-release-2.md")
        _post_again(s, "/api/settings/updates/mode", {"mode": "ride"})
        after = _until_updated(s, r2, 1800, "riding along")
        expect((after.get("last") or {}).get("by") == "riding along", f"it was not the ride along: {after.get('last')}")
        _healthy(s)
        files = s.run("core", "cat /code/docs/stack-release-2.md; head -1 /code/README.md").stdout
        expect("New in release 2" in files and "this Rouh own words" in files, f"after the ride along: {files}")
        _general_says(s, "Rouh updated itself to Rouh of 12 November")
    finally:
        s.manage("""
from rouh import relay
from rouh.web import firstrun
firstrun._save(relay.owner(), connected=False)
""")


# At the very end, before only import.existing (which stops this stack): these change the code that
# runs, which the Creator's checks and Put back, among the last, read as theirs.
smoke.FINAL.update({"updates.press", "updates.ride"})
smoke.LIMIT.update({"updates.press": 3600, "updates.ride": 2700})
