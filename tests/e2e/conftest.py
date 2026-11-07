"""A real browser, against the real app, started on this machine.

Every test in this folder gets a Chromium page from `pytest-playwright` and a
server to point it at. Two apps live in this repository and both have a page,
so there are two fixtures that start one:

- `rouh_app` is Rouh itself, on a free port, with its own empty data
  directory, its own throwaway PostgreSQL (`rouh/testing/postgres.py`), and one
  account made in it by the same admin command a person would use, so the
  sign-in the person goes through every day is the one the tests go through
  too.
- `rouh_with_tree` is Rouh serving a copy of this repository's own
  `workspace/`, which is the tree the workspace was reshaped into: projects
  that own projects and tasks, with a `.object.json` in every object folder.
  The task browser draws that one from the database rather than from the
  folders, so it is the world for anything about the hierarchy. The copy is a
  git checkout of its own, because moving an object moves its folder with
  `git mv`, and a stand-in for the model sits in front of it, because a card
  filed into a task as its next numbered step is drawn by one.
- `one_app` is the one program in the throwaway world `one/tests/dev_server.py`
  already builds: its own git remote, its own workspace, a stand-in for Claude
  Code, and its own socket.
- `one_deploy_world` is all three at once and one thing more: a one program
  served out of a checkout a test can move, a `main` to move it onto, and a
  Rouh paired with it that can deploy it. It is for the button under the
  version mark, which cannot be proved by anything that does not really restart
  a program into different code.
- `two_chip_world` is a Rouh with a checkout of its own and a one program with
  a checkout of its own, so each of the top bar's two version marks can be made
  to say an update is waiting without touching the other service.

Neither is given an Anthropic or an ElevenLabs key, and the keys that happen to
be in the environment of whoever runs the suite are taken out of it. So nothing
here costs a token or reaches the network, and a test that starts needing one
fails loudly rather than quietly spending money.

Both fixtures are for the whole session: starting a server takes a few seconds
and nothing a test does to one leaks into the next in a way that matters. The
browser context is not shared - Playwright gives every test a fresh one, so
cookies and localStorage always start empty.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest

#: The repository root: two levels up from tests/e2e.
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from one.tests import strays  # noqa: E402  (needs ROOT on the path first)
from rouh.testing import postgres  # noqa: E402
from rouh.testing.browser import INSTALLATION, name_the_owner  # noqa: E402

#: The account every test copy of Rouh is given, made the way a person makes
#: one: `python manage.py account add`. There is no way to turn the sign-in
#: off, on a test machine or anywhere else, so there is nothing else to do.
USERNAME = "alex"
PASSWORD = "correct-horse-battery-staple-42"

#: How long a server gets to answer its health check before the suite gives up.
#: Generous, because a busy server can be slow to import and this is not a
#: measurement of anything.
START_SECONDS = 60


def free_port() -> int:
    """A port nothing is listening on, so two suites can run at once."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def clean_env(*prefixes: str) -> dict[str, str]:
    """The environment with this machine's own settings and keys taken out.

    A test must not depend on what the person running it happens to have
    exported, and must never pick up a real API key by accident.

    Telegram is the one that is put somewhere rather than taken away. Its
    settings are a file path, and taking the path out leaves the default, which
    on this server is the real bot's real key: a suite that reached it would
    text the owner on their own phone every time somebody ran it. So every server a
    test starts is pointed at a file that is not there and at an address that
    answers nothing, and a test that wants to watch a message go out says so.
    """
    drop = ("ANTHROPIC_API_KEY", "ELEVENLABS_API_KEY", "OPENAI_API_KEY", "OPENAI_BASE_URL",
            "APIFY_API_TOKEN", "VOYAGE_API_KEY", "VOYAGE_ENDPOINT")
    env = {
        k: v for k, v in os.environ.items()
        if k not in drop and not any(k.startswith(p) for p in prefixes)
    }
    env["ROUH_TELEGRAM_FILE"] = "/nonexistent/no-telegram.json"
    env["ROUH_TELEGRAM_API_BASE"] = "http://127.0.0.1:1/no-telegram"
    # And a person's own Telegram account, which makes a group for each fork
    # (`rouh/telegram_account.py`), at the stand-in's address that answers
    # nothing, so no world ever signs anybody in at Telegram.
    env["ROUH_TELEGRAM_ACCOUNT_URL"] = "http://127.0.0.1:1/no-telegram-account"
    # And Stripe, at an address that answers nothing, so a key typed into
    # Payments in a world never reaches Stripe (`rouh/payments.py`).
    env["ROUH_STRIPE_API_BASE"] = "http://127.0.0.1:1/no-stripe"
    # And Cloudflare, likewise, with no token carried over from the environment, so a
    # token typed into Settings, Cloudflare in a world never reaches Cloudflare.
    env["ROUH_CLOUDFLARE_API"] = "http://127.0.0.1:1/no-cloudflare"
    env.pop("CLOUDFLARE_ROUH_IS_TOKEN", None)
    # And Slack and the Philips Hue cloud, at addresses that answer nothing, so a token typed into
    # Settings in a world never reaches Slack, and Connect never sends anybody to Hue's sign-in.
    env["ROUH_SLACK_API"] = "http://127.0.0.1:1/no-slack"
    env["ROUH_HUE_API"] = "http://127.0.0.1:1/no-hue"
    # And the Dreamehome cloud, so an email and password typed into Settings never reach Dreame.
    env["ROUH_DREAME_API"] = "http://127.0.0.1:1/no-dreame"
    # And rouh.land, where the model standard is fetched from and the day's counts of how each
    # model did would go (`rouh/modelstandard.py`, `rouh/modeloutcomes.py`): nothing a world
    # does reaches it. A world that wants a standard points this at a stand-in of its own.
    env["ROUH_MODEL_STANDARD_URL"] = "http://127.0.0.1:1/no-rouh-it/standard.json"
    env["ROUH_MODEL_OUTCOMES_URL"] = "http://127.0.0.1:1/no-rouh-it/outcomes"
    env["ROUH_MODEL_OUTCOMES_SEND"] = "0"
    # And the rule defaults a new Rouh takes in from rouh.land (`rouh/ruledefaults.py`): a world starts with the
    # two it would have offline, unless ROUH_TEST_RULE_DEFAULTS_URL points it at a stand-in of its own.
    env["ROUH_RULE_DEFAULTS_URL"] = os.environ.get("ROUH_TEST_RULE_DEFAULTS_URL",
                                                   "http://127.0.0.1:1/no-rouh-it/rules.json")
    # And the installation's own settings, which are blank until an installer
    # sets them (`rouh/config.py`, SETUP.md): Rouh's own mailbox, the address
    # its letters come from and the clock a person starts on, the same in every
    # world (`rouh/testing/browser.py`, `INSTALLATION`). A world sets its own
    # public address beside its port.
    env.update(INSTALLATION)
    return env


@dataclass
class App:
    """A server the tests drive a browser at."""

    #: Where the page is, with no trailing slash: "http://127.0.0.1:8123/one".
    url: str
    #: Everything the process wrote, for when a test fails and someone has to
    #: find out why.
    log: Path
    process: subprocess.Popen
    #: The one program's socket, for the `one` command. None for Rouh.
    socket_path: str | None = None
    #: The folder holding the server's data, for a test that wants to look.
    data: Path | None = None
    #: The workspace this Rouh serves under /workspace/, where there is one.
    #: None on a machine with no assistant workspace to borrow the index
    #: generator from, which is what the task browser is drawn by.
    workspace: Path | None = None
    #: The folder everything this server made lives in. `stop` reaps whatever
    #: is still running under it, which is how a run's holder and the agent on
    #: its terminal are put away: both are in sessions of their own and
    #: stopping the program does not touch them.
    folder: Path | None = None

    def at(self, path: str) -> str:
        return self.url.rstrip("/") + "/" + path.lstrip("/")

    def tail(self, lines: int = 60) -> str:
        try:
            return "\n".join(self.log.read_text(errors="replace").splitlines()[-lines:])
        except OSError:
            return "(no log)"


def start(name: str, argv: list[str], env: dict[str, str], health: str, url: str,
          folder: Path, cwd: Path | None = None, **extra) -> App:
    """Start a server, wait for its health check, and hand back an `App`.

    Anything that goes wrong while it is coming up is raised with the server's
    own output attached: a fixture that fails with "connection refused" and
    nothing else costs half an hour.
    """
    log = folder / f"{name}.log"
    handle = log.open("w")
    process = subprocess.Popen(argv, cwd=str(cwd or ROOT), env=env, stdout=handle,
                               stderr=subprocess.STDOUT)
    strays.watch(folder)
    app = App(url=url, log=log, process=process, folder=folder, **extra)
    deadline = time.monotonic() + START_SECONDS
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"{name} stopped while starting up:\n\n{app.tail()}")
        try:
            httpx.get(health, timeout=2.0).raise_for_status()
            return app
        except Exception:
            time.sleep(0.25)
    stop(app)
    raise RuntimeError(
        f"{name} did not answer {health} within {START_SECONDS}s:\n\n{app.tail()}")


def stop(app: App) -> None:
    """Stop the server, and everything it started and let go of.

    Stopping the program is not enough on its own. The one program starts each
    run's terminal detached on purpose, so that a deploy can restart the
    program and every run carry on, which means a fixture that only terminates
    the program leaves a holder and an agent behind for as long as the machine
    is up. `strays.reap` is the other half of `start`.
    """
    app.process.terminate()
    try:
        app.process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        app.process.kill()
        app.process.wait(timeout=15)
    # A Rouh's database goes with it, and before the reaper looks: the
    # cluster's processes live under the world's folder and are not strays.
    if app.data is not None:
        postgres.stop_world(app.data.parent)
    if app.folder is not None:
        stopped = strays.reap(app.folder)
        if stopped:
            print("\n" + strays.report(stopped, str(app.folder)))


@pytest.fixture(scope="session", autouse=True)
def _nothing_is_left_running(tmp_path_factory):
    """The backstop, for what a fixture's own teardown cannot catch.

    `stop` reaps the folder of every server it started. This catches the rest:
    a test killed before its teardown ran, a fixture that starts a server some
    other way, a folder pytest made rather than `start`. The whole session's
    temporary folder is claimed, so one sweep covers every test in it.
    """
    strays.watch(tmp_path_factory.getbasetemp())
    yield
    stopped = strays.reap(*strays.watched())
    if stopped:
        print("\n" + strays.report(stopped, "this test session's folders"))


# ---------------------------------------------------------------------------
# The browser
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def browser_type_launch_args(browser_type_launch_args):
    """Chromium with a microphone and a camera that are not real.

    Rouh's page asks for the microphone the moment the voice is woken, and a
    headless browser with no answer to that question hangs there. These flags
    make the browser say yes and hand over a generated signal, so the press
    that wakes the voice can be given in a test exactly as a person gives it.
    """
    return {
        **browser_type_launch_args,
        "args": [
            *browser_type_launch_args.get("args", []),
            "--use-fake-ui-for-media-stream",
            "--use-fake-device-for-media-stream",
            "--autoplay-policy=no-user-gesture-required",
        ],
    }


@pytest.fixture(scope="session")
def browser_context_args(browser_context_args):
    """Permission granted up front, and a window the size of a laptop screen.

    The page lays itself out by width - below about 900 pixels it folds the
    columns away - so a test that checks a column must run at a width where
    there are columns.
    """
    return {
        **browser_context_args,
        "permissions": ["microphone"],
        "viewport": {"width": 1400, "height": 900},
    }


# ---------------------------------------------------------------------------
# Rouh
# ---------------------------------------------------------------------------

#: What the projects in the small workspace below are called. A project's title
#: is not its folder name, which is why `objecttree.ensure_sidecars` is told
#: them rather than guessing.
#: The two at the top are Work and Personal, and the second one's folder is
#: still `private`: a title is what a person reads and a folder is an address
#: (`objectindex.COLUMNS`, RENAME.md). `misc` is here because it is what a task
#: the filing model cannot place falls back to (`rouh/filing.py`).
PROJECTS = {"work": "Work", "private": "Personal",
            "work/prices": "Pricing", "private/home": "Home",
            "private/misc": "Miscellaneous"}


#: The step file of a task built the new way: one markdown file that is both
#: the page and the source. The fences are the blocks the canvas already draws.
STEP_MD = """---
task: 12.the-rail
step: 12-02
title: Two permanent stores is the bug
state: decided
---

## The decision

The task folder is the record, and the canvas is a view of it.

:::stat
label: Permanent stores
value: one
hint: down from two
:::

:::list
- A thread is the unit
- A thread that is a task IS that task
:::
"""


def build_workspace(root: Path, *, work_only: bool = False) -> bool:
    """A small workspace for Rouh to serve, in the shape the real one has.

    A tree, because that is the only shape there is since 21 September 2026:
    Work and Personal are projects at the top, a category is a project inside
    one of them, and a task sits under the project that owns it. The task
    browser draws one group per top-level project, so a workspace with one side
    cannot show that at all, and both are here.

    `07.pricing-review` is a task built the old way, one step folder holding an
    `index.html`, which is what nearly every step in the real workspace is.
    `12.the-rail` is a task with one of each, so both kinds of step can be
    driven in one browser: an old page that is framed, and a `step.md` that has
    no built page and whose blocks the canvas draws itself. `19.the-shelves` is
    on the private side.

    The sidecars and the mapping are written by `rouh.objecttree` itself, not
    by hand here, so this world cannot describe a tree the real commands would
    not: a folder is an object because that code says it is, and the database
    is imported from the same `_migration-map.json` the real workspace has.

    Always true. It used to answer False on a machine with no workspace to copy
    the index generator out of, because the browser was the workspace's own
    page; nothing is borrowed any more, so there is nothing to be missing.
    ``work_only`` keeps the same Work fixtures without creating the private side.
    """
    root.mkdir(parents=True, exist_ok=True)
    # No `_categories.json`. It said which task was in which category while the
    # workspace was a flat `tasks/NN.name`; the tree says that by where a task
    # sits, and stage five deleted the file. A world that still wrote one would
    # be standing up a workspace the real one is not.

    task = root / "work" / "prices" / "07.pricing-review"
    (task / "07-01.first-look").mkdir(parents=True)
    (task / "07-01.first-look" / "index.html").write_text(
        "<!doctype html><html><head><title>A first look at the prices</title></head>"
        "<body><h1>A first look at the prices</h1>"
        "<p>Nine seats at forty euros.</p></body></html>", encoding="utf-8")

    rail = root / "work" / "prices" / "12.the-rail"
    (rail / "12-01.what-is-there-today").mkdir(parents=True)
    (rail / "12-02.two-stores").mkdir(parents=True)
    (rail / "12-01.what-is-there-today" / "index.html").write_text(
        "<!doctype html><html><head><title>The columns as they are</title></head>"
        "<body><h1>The columns as they are</h1>"
        "<p>Three regions and a canvas.</p></body></html>", encoding="utf-8")
    (rail / "12-02.two-stores" / "step.md").write_text(STEP_MD, encoding="utf-8")

    # The private side. One task, one old-style step, so the second group of
    # the browser has something in it to be seen beside the first.
    if not work_only:
        shelves = root / "private" / "home" / "19.the-shelves"
        (shelves / "19-01.what-to-buy").mkdir(parents=True)
        (shelves / "19-01.what-to-buy" / "index.html").write_text(
            "<!doctype html><html><head><title>Oak, and how much of it</title></head>"
            "<body><h1>Oak, and how much of it</h1>"
            "<p>Four metres, planed.</p></body></html>", encoding="utf-8")

        # Miscellaneous, with nothing in it. It is the project a task the filing
        # model cannot place goes to (`config.filing_fallback`), and a world
        # without one cannot show that happening at all.
        (root / "private" / "misc").mkdir(parents=True, exist_ok=True)

    # The person's own words about each task, which is what the breadcrumb
    # puts under the name, how far along each is, and what each says about its
    # steps, are not in these files: a task's status, summary and meta are the
    # database's alone (`rouh/taskrecord.py`, `rouh/taskmeta.py`), so they are
    # `TASKS_SAY` and `TASKS_META` below, given to the world's database by
    # `seed_tasks` once it has one. `_tasks.md` is not written here
    # either: Rouh writes it out of the rows (`rouh/tasklist.py`).

    # And what makes it a tree rather than four folders: a `.object.json` in
    # every object folder and one `_migration-map.json` naming all of them,
    # both written by the workspace's own commands.
    from rouh import objecttree

    projects = {k: v for k, v in PROJECTS.items() if not work_only or k == "work" or k.startswith("work/")}
    # No database is behind this workspace yet, so a step is named by its folder.
    objecttree.ensure_sidecars(root, titles=projects, listed=False)
    body = objecttree.build_map(root)
    (root / objecttree.MAP_FILE).write_text(
        json.dumps(body, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return True


#: What `build_workspace`'s three tasks say about themselves: their status and summary,
#: which live in the database since 6 October 2026, as they do on the server.
TASKS_SAY = {
    "work/prices/07.pricing-review": ("in-progress", "What the nine seats cost today.\n"
                                                     "Nothing is open."),
    "work/prices/12.the-rail": ("waiting", "The rail, the canvas and where the record lives.\n"
                                           "Open: whether a loose thread can be promoted."),
    "private/home/19.the-shelves": ("not-started", "Shelves for the back room.\n"
                                                   "Nothing is open."),
}

#: And what each says about its steps: its meta (`rouh/taskmeta.py`).
TASKS_META = {
    "work/prices/07.pricing-review": {
        "steps": {"07-01.first-look": {"description": "Where the money goes today"}}},
    "work/prices/12.the-rail": {
        "steps": {"12-01.what-is-there-today": {"description": "The columns as they are"},
                  "12-02.two-stores": {"description": "Why there is one record"}}},
    "private/home/19.the-shelves": {
        "steps": {"19-01.what-to-buy": {"description": "Oak, and how much of it"}}},
}

#: Run in the world's own environment: each task's status and summary given to its
#: database the way `rouh-task` gives them, by the id in its `.object.json`, so
#: a task with no row yet is answered when it is taken in (`taskrecord.change`).
#: A meta needs the row itself, so the folders are taken in first, as Rouh does
#: when it starts (`conversations.reconcile`).
_SEED_TASKS = r"""
import json, sys
from pathlib import Path
from rouh.project import setup
setup()
from rouh import conversations, taskmeta, taskrecord
root = Path(sys.argv[1])
for rel, (status, summary) in json.loads(sys.argv[2]).items():
    side = json.loads((root / rel / ".object.json").read_text(encoding="utf-8"))
    taskrecord.change(rel, status=status, summary=summary, by="the harness",
                      ident=side["id"], folder=rel)
metas = json.loads(sys.argv[3])
if metas:
    conversations.reconcile(str(root))
for rel, meta in metas.items():
    if (root / rel).is_dir():
        side = json.loads((root / rel / ".object.json").read_text(encoding="utf-8"))
        taskmeta.change_id(side["id"], lambda _was, meta=meta: meta, by="the harness")
"""


def seed_tasks(env: dict[str, str], data: Path, workspace: Path, said: dict | None = None,
               metas: dict | None = None) -> None:
    """The world's tasks given their status, summary and meta, in its own database."""
    done = subprocess.run(
        [sys.executable, "-c", _SEED_TASKS, str(workspace), json.dumps(said or TASKS_SAY),
         json.dumps(TASKS_META if metas is None else metas)],
        cwd=str(ROOT), capture_output=True, text=True, timeout=120,
        env={**env, "ROUH_DATA_DIR": str(data), "ROUH_ASSISTANT_REPO": str(workspace),
             "PYTHONPATH": str(ROOT)},
    )
    if done.returncode != 0:
        raise RuntimeError(f"the tasks could not be seeded:\n{done.stdout}\n{done.stderr}")


def make_account(data: Path, env: dict[str, str], username: str = USERNAME,
                 password: str = PASSWORD) -> None:
    """A database for this world, and one account in it, through the admin command.

    Rouh keeps everything in PostgreSQL, so every world gets a cluster of its
    own, in its own folder, on a socket nothing else can reach
    (`rouh/testing/postgres.py`), with Django's schema migrated into it. `env`
    is given its address, so the server started with it finds the same one.

    The account is made the way a person makes one, not by reaching into the
    database, because the command is the thing the person will actually run on
    the server and it should be exercised by every world that is stood up.
    """
    postgres.for_world(data.parent, env)
    made = subprocess.run(
        [sys.executable, "manage.py", "account", "add", username, "--password", password],
        cwd=str(ROOT), capture_output=True, text=True, timeout=120,
        env={**env, "ROUH_DATA_DIR": str(data)},
    )
    if made.returncode != 0:
        raise RuntimeError(f"the account could not be made:\n{made.stdout}\n{made.stderr}")
    # The owner's name and their organisation's, which the prompts are written
    # with, are an invented person's (`rouh/testing/browser.py`, `OWNER`).
    name_the_owner(str(data), env, username)


@pytest.fixture(scope="session")
def rouh_app(tmp_path_factory) -> App:
    folder = tmp_path_factory.mktemp("rouh")
    port = free_port()
    data = folder / "data"
    data.mkdir()
    env = clean_env("ROUH_", "JARVIS_")
    workspace = folder / "workspace"
    build_workspace(workspace)
    env.update(
        ROUH_DATA_DIR=str(data),
        # The address this world is opened at, so a link Rouh writes to itself opens here.
        ROUH_PUBLIC_URL=f"http://127.0.0.1:{port}",
        # The landing lock and the conflict records (`land.sh`,
        # `rouh/conflicts.py`), in a folder of this world's own. Without it
        # every world would read the real ones, so a live job's question would
        # turn a test's orb red and a test's answer would decide a live job's
        # conflict.
        ROUH_LAND_DIR=str(folder / "land"),
        # The version on the page comes from this checkout, not from whatever
        # is deployed at the default path.
        ROUH_APP_DIR=str(ROOT),
        # A workspace of its own, so the task browser has something to show.
        ROUH_ASSISTANT_REPO=str(workspace),
        # Nothing that reaches out of this process: no tmux worker, no
        # self-update, and a one program that is not there.
        ROUH_DELEGATE="0",
        ROUH_SELF_UPDATE="0",
        ROUH_SHELL="0",
        ROUH_ONE_SOCKET=str(folder / "no-such.sock"),
        ROUH_ONE_TOKEN=str(folder / "no-such.json"),
        # iCloud's contacts at an address that answers nothing, so an Apple ID
        # typed into this world's Settings never reaches Apple.
        # `rouh/testing/fake_carddav.py` is the stand-in; the talking world
        # has one running.
        ROUH_CARDDAV_URL="http://127.0.0.1:1/no-icloud",
        PYTHONUNBUFFERED="1",
    )
    make_account(data, env)
    seed_tasks(env, data, workspace)
    app = start(
        "rouh",
        [sys.executable, "-m", "uvicorn", "rouh.server:app",
         "--host", "127.0.0.1", "--port", str(port), "--log-level", "info"],
        env,
        health=f"http://127.0.0.1:{port}/healthz",
        url=f"http://127.0.0.1:{port}",
        folder=folder,
        data=data,
    )
    app.workspace = workspace
    yield app
    stop(app)


@pytest.fixture(scope="session")
def rouh_with_tree(tmp_path_factory) -> App:
    """Rouh serving this checkout's own `workspace/`, which is the tree.

    `rouh_app` builds a small tree of its own - four folders, three tasks -
    which is enough for most things and costs nothing to stand up. This one is
    the real thing: every task, every step and every built page the person
    actually has, with a `.object.json` in every object folder and a
    `_migration-map.json` at its root, which is what `objectindex.py` draws
    from the database.

    **A copy of this repository's own `workspace/`, and it has to be a copy.**
    Rouh does not only read a workspace: it writes `_tasks.md` out of its rows,
    writes a task's folder out again when its row has one and the disk does
    not (`conversations.write_out`), and moves folders, so a world pointed
    straight at the checkout would change files in it the moment anybody opened
    the task browser. Until 6 October 2026 it also wrote a task's status back
    into a file in its folder, which was measured on 21 September 2026, on five
    files, before this copied anything. Its tasks' statuses, summaries and
    metas are not in the copy: they are the database's (`rouh/taskrecord.py`,
    `rouh/taskmeta.py`), so here every task starts not started, with no
    summary and no steps listed, tags or questions.

    It costs about 140 MB of whatever `/tmp` is, for as long as the world is
    up, and it is the whole workspace because the pages are the point: a page
    here is served with its own pictures put into it.

    **It is a git checkout, and it answers.** Two things were added on 22
    September 2026 because stage four cannot be driven without them. The copy
    is `git init`-ed and committed, because moving an object moves its folder
    with `git mv` so that `git log --follow` keeps working, and a copy that is
    not a checkout would take the plain-rename path and prove the wrong half.
    And `rouh/testing/fake_model.py` stands in front of Anthropic, because a
    card filed into a task as its next numbered step is drawn by the model, and
    a world that cannot answer cannot be driven at that. No key and nothing
    reaching the network either way: the stand-in is a real HTTP server on a
    free port that answers out of what was sent to it.
    """
    folder = tmp_path_factory.mktemp("rouh-tree")
    workspace = folder / "workspace"
    from rouh.testing.workspace_source import source as workspace_source

    shutil.copytree(workspace_source(), workspace, symlinks=True,
                    ignore=shutil.ignore_patterns(".git", "node_modules", "temp",
                                                  "*.sqlite3*"))
    for argv in (["git", "init", "-q"], ["git", "add", "-A"],
                 ["git", "-c", "user.email=world@example.invalid",
                  "-c", "user.name=The harness", "commit", "-qm",
                  "the workspace, as this checkout has it"]):
        subprocess.run(argv, cwd=str(workspace), check=True, capture_output=True)
    port, model_port = free_port(), free_port()
    data = folder / "data"
    data.mkdir()
    requests = folder / "model-requests"
    requests.mkdir()
    env = clean_env("ROUH_", "JARVIS_")
    env.update(
        ROUH_DATA_DIR=str(data),
        # The address this world is opened at, so a link Rouh writes to itself opens here.
        ROUH_PUBLIC_URL=f"http://127.0.0.1:{port}",
        ROUH_LAND_DIR=str(folder / "land"),
        ROUH_APP_DIR=str(ROOT),
        ROUH_ASSISTANT_REPO=str(workspace),
        ROUH_DELEGATE="0",
        ROUH_SELF_UPDATE="0",
        ROUH_SHELL="0",
        ROUH_ONE_SOCKET=str(folder / "no-such.sock"),
        ROUH_ONE_TOKEN=str(folder / "no-such.json"),
        PYTHONUNBUFFERED="1",
    )
    model = start(
        "fake-model",
        [sys.executable, "-m", "rouh.testing.fake_model",
         "--port", str(model_port), "--record", str(requests)],
        env,
        health=f"http://127.0.0.1:{model_port}/openapi.json",
        url=f"http://127.0.0.1:{model_port}",
        folder=folder,
    )
    env.update(
        ANTHROPIC_API_KEY="test-key-not-a-real-one",
        ANTHROPIC_BASE_URL=f"http://127.0.0.1:{model_port}",
        ELEVENLABS_API_KEY="",
        ROUH_VOICE_REPLIES="0",
        ROUH_REALTIME_STT="0",
    )
    make_account(data, env)
    app = start(
        "rouh",
        [sys.executable, "-m", "uvicorn", "rouh.server:app",
         "--host", "127.0.0.1", "--port", str(port), "--log-level", "info"],
        env,
        health=f"http://127.0.0.1:{port}/healthz",
        url=f"http://127.0.0.1:{port}",
        folder=folder,
        data=data,
    )
    app.workspace = workspace
    yield app
    # The model first: both were started in the same folder, so `stop`'s reaper
    # would otherwise find the stand-in still running under it and report it as
    # a stray, which it is not.
    stop(model)
    stop(app)


def sign_in(page, app: App, username: str = USERNAME, password: str = PASSWORD):
    """Through the sign-in and onto the page itself, the way a person does it.

    There is no splash screen behind the sign-in any more: the three columns
    are there at once and the socket opens by itself, so landing on the
    composer is landing on the page.
    """
    page.goto(app.at("/login"))
    # One box first (since 4 November 2026, `rouh/web/auth.py`): a username, not an email, goes
    # straight on to the password.
    page.fill("#email", username)
    page.click("#continueBtn")
    page.wait_for_selector("input[name=password]")
    page.fill("input[name=password]", password)
    page.click("button:has-text('Sign in')")
    page.wait_for_selector("#input")
    return page


@pytest.fixture
def signed_in(page, rouh_app):
    """A page past the sign-in, on Rouh's own page, with the voice asleep.

    Everything on the page works from here except the microphone and the
    speakers, which a browser will not open without a real press. Most tests
    want `started`, which gives that press.
    """
    return sign_in(page, rouh_app)


def wait_until_live(page):
    """Wait until the page says Connected.

    The socket opens with the page now - there is nothing to press first - so
    this is all that "the page is ready" means. It is still worth waiting for:
    the columns are drawn whether or not the socket comes up.
    """
    page.wait_for_function(
        "() => document.getElementById('conn').getAttribute('aria-label')"
        " === 'Connected'",
        timeout=20_000)
    return page


def wake_the_voice(page):
    """Give the press a browser needs before it will start a speaker.

    The microphone is no part of this. Nothing on the page opens one until
    somebody presses the microphone button, holds hold-to-talk or starts
    dictating - see `test_the_microphone_is_only_open_when_asked.py` - so
    there is nothing to press for it here and nothing to wait for. All the
    speakers need is one real press anywhere, and this gives one, on the name
    in the top bar, where nothing happens.

    It waits for the socket too, which is what a caller means by "ready".
    """
    page.click(".brand-name")
    return wait_until_live(page)


def show_the_runs(page):
    """Press the `</>` in the sidebar's header, the way the person does.

    The sidebar shows one list at a time and comes up on the chats, so a test
    about a run presses that half of the switch first. It is a press and not a
    flag on purpose: the switch is part of what the person does to get to the
    runs.
    """
    page.click("#railTabRuns")
    page.wait_for_selector("#tasksList:visible")
    return page


def show_the_threads(page):
    """The other half of `show_the_runs`: the speech bubble beside it."""
    page.click("#railTabThreads")
    page.wait_for_selector("#threadList:visible")
    return page


def turn_the_microphone_on(page):
    """Press the microphone button and wait until a stream is really open.

    For a test that wants a live microphone. Chromium answers the permission
    prompt by itself here (`--use-fake-ui-for-media-stream`).
    """
    page.click("#micBtn")
    page.wait_for_function(
        "() => window.__rouh.mic().ready", timeout=20_000)
    return page


@pytest.fixture
def started(signed_in):
    """A page with Rouh fully awake in it.

    Past the sign-in, live on the websocket, and with the speakers ready the
    way a press readies them. The microphone is shut, because on this page it
    is shut until somebody asks for it. This is where the person spends the
    whole of their time, so it is the fixture most tests want.
    """
    return wake_the_voice(signed_in)


# ---------------------------------------------------------------------------
# The one program
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def one_app(tmp_path_factory) -> App:
    folder = tmp_path_factory.mktemp("one")
    port = free_port()
    world = folder / "world"
    env = clean_env("ONE_")
    env["PYTHONUNBUFFERED"] = "1"
    app = start(
        "one",
        [sys.executable, "-m", "one.tests.dev_server", str(world), str(port)],
        env,
        health=f"http://127.0.0.1:{port}/one/healthz",
        url=f"http://127.0.0.1:{port}/one",
        folder=folder,
        socket_path=str(world / "s.sock"),
        data=world,
    )
    yield app
    stop(app)


def one_env(app: App) -> dict[str, str]:
    """The environment the `one` command needs to reach this program."""
    return {**clean_env("ONE_"), "ONE_SOCKET": app.socket_path or ""}


# ---------------------------------------------------------------------------
# A service's own checkout, and the `main` behind it
# ---------------------------------------------------------------------------
#
# Both version marks in the top bar ask the same two questions about their own
# service: which commit is it answering from, and which commit is `origin/main`
# at in the checkout that service is deployed from. So a test that wants to make
# "a newer commit has been merged but not deployed" happen needs two folders per
# service: an origin standing in for GitHub, and a clone of it standing in for
# /var/www/rouh/app or /srv/one/app.
#
# Both start at the commit this repository is on, which is the commit the
# service under test is really running, so a world that has been left alone
# reads as up to date rather than as an update nobody asked for.


@dataclass
class ServiceRepo:
    """One service's origin and checkout, and the commit both start at."""

    #: What a deploy fetches from, and where a test merges.
    origin: Path
    #: The folder the service is started from: what /srv/one/app stands for.
    checkout: Path
    #: The commit both are at to begin with, which is the commit the running
    #: service reports, because it is this repository's own HEAD.
    base: str

    def nothing_new(self) -> str:
        """Put `main` back at the commit the service is running, and say it.

        Every test says which of the two worlds it wants, so no test depends on
        what the one before it left behind.
        """
        self._rewind()
        return self.base

    def one_commit_ahead(self, what: str = "a commit the service has not got") -> str:
        """Merge one commit into `main`, fetch it, and hand back its commit.

        This is "somebody merged while the old build carried on serving": the
        checkout stays where it is, standing on the commit the running service
        was started from, and `origin/main` moves ahead of it.
        """
        self._rewind()
        (self.origin / "what-changed.txt").write_text(what + "\n")
        subprocess.run(["git", "add", "-A"], cwd=self.origin, check=True)
        subprocess.run(["git", "commit", "-q", "-m", what], cwd=self.origin, check=True)
        return self._fetch()

    def standing_at(self) -> str:
        """The commit the checkout is standing on."""
        return _short(self.checkout, "HEAD")

    def _rewind(self) -> None:
        subprocess.run(["git", "reset", "-q", "--hard", self.base], cwd=self.origin,
                       check=True, capture_output=True, text=True)
        self._fetch()

    def _fetch(self) -> str:
        # The refspec a clone writes down is a forced one, so a `main` that has
        # been moved backwards updates here as well as one moved forwards.
        subprocess.run(["git", "fetch", "-q", "origin"], cwd=self.checkout, check=True)
        return _short(self.checkout, "origin/main")


def _clone(source: Path, into: Path, *, branch: str = "") -> None:
    """A copy of a repository, in a folder of its own.

    `--no-hardlinks` costs a second and buys the suite the right to run
    anywhere. A local clone links the object files rather than copying them,
    and a link to a file somebody else owns is refused outright on a machine
    with `fs.protected_hardlinks` on - which is every Ubuntu. On the server the
    checkouts belong to the deployment and the suite runs as the crew, so every
    test that wanted a repository of its own died on "Operation not permitted"
    before it started.
    """
    argv = ["git", "clone", "-q", "--local", "--no-hardlinks",
            str(source), str(into)]
    if branch:
        argv[3:3] = ["--branch", branch]
    subprocess.run(argv, check=True, capture_output=True, text=True, timeout=120)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=into, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=into, check=True)


def _short(where: Path, ref: str) -> str:
    done = subprocess.run(["git", "rev-parse", "--short=7", ref], cwd=where,
                          check=True, capture_output=True, text=True)
    return done.stdout.strip()


def a_service_repo(folder: Path, name: str) -> ServiceRepo:
    """An origin and a checkout of this repository, for one service.

    A copy of this repository rather than a folder with one file in it, because
    the commit the running service reports is this repository's own HEAD, and a
    checkout that does not contain that commit could never agree with it - which
    is the whole failure the two marks were built to stop.
    """
    origin, checkout = folder / f"{name}-origin", folder / f"{name}-app"
    _clone(ROOT, origin)
    # `main` here, and nothing pointing at GitHub: a fetch in a test must never
    # reach the network, and a remote that is not there would.
    subprocess.run(["git", "checkout", "-q", "-B", "main"], cwd=origin, check=True)
    subprocess.run(["git", "remote", "remove", "origin"], cwd=origin, check=True)
    _clone(origin, checkout, branch="main")
    return ServiceRepo(origin=origin, checkout=checkout, base=_short(checkout, "HEAD"))


@pytest.fixture(scope="session")
def one_repo(tmp_path_factory) -> ServiceRepo:
    """The one program's own checkout, and the `main` behind it.

    This is what the one mark reads to answer "which commit is waiting for this
    program": the clone its service is started from and the clone its deploy
    fetches into.
    """
    return a_service_repo(tmp_path_factory.mktemp("one-repo"), "one")


@pytest.fixture(scope="session")
def rouh_with_one(tmp_path_factory, one_app, one_repo) -> App:
    """Rouh, paired with a one program that is really running.

    `rouh_app` is deliberately started with no one program at all, which is
    the right default for every other test. This one is for the top bar's mark
    for the one program, which has nothing to say until there is a program to
    say it about. The pairing is done with `one pair voice`, which is how the person
    does it - nothing here reaches inside the program to mint a token.
    """
    folder = tmp_path_factory.mktemp("rouh-one")
    token = folder / "voice.json"
    subprocess.run(
        [sys.executable, "-m", "one.cli", "pair", "voice", "--save", str(token)],
        cwd=str(ROOT), check=True, capture_output=True, text=True, timeout=30,
        env=one_env(one_app),
    )
    data = folder / "data"
    data.mkdir()
    workspace = folder / "workspace"
    build_workspace(workspace)
    port = free_port()
    env = clean_env("ROUH_", "JARVIS_", "ONE_")
    env.update(
        ROUH_DATA_DIR=str(data),
        # The address this world is opened at, so a link Rouh writes to itself opens here.
        ROUH_PUBLIC_URL=f"http://127.0.0.1:{port}",
        # The landing lock and the conflict records (`land.sh`,
        # `rouh/conflicts.py`), in a folder of this world's own. Without it
        # every world would read the real ones, so a live job's question would
        # turn a test's orb red and a test's answer would decide a live job's
        # conflict.
        ROUH_LAND_DIR=str(folder / "land"),
        ROUH_APP_DIR=str(ROOT),
        # A workspace of this world's own, and it has to be one. Until 21
        # October 2026 nothing here meant this checkout's own `workspace/`,
        # so anything that wrote a task folder - promoting a chat, filing a
        # card - wrote it into the repository the suite was running out of;
        # on 22 September 2026 a run started from the Start box in this world
        # left `workspace/unfiled/51...` in the checkout. Nothing here is no
        # workspace now (`rouh/config._workspace_root`), and never the real one.
        ROUH_ASSISTANT_REPO=str(workspace),
        ROUH_DELEGATE="0",
        ROUH_SELF_UPDATE="0",
        ROUH_SHELL="0",
        # The one program that is really there, and the checkout the commit it
        # reports is compared against.
        ROUH_ONE_SOCKET=one_app.socket_path or "",
        ROUH_ONE_TOKEN=str(token),
        ROUH_ONE_REPO=str(one_repo.checkout),
        # A deploy started from this Rouh is pointed at a folder that is not
        # a checkout at all, so it fails at its first step and says so. This is
        # where a deploy that cannot work is tested; `one_deploy_world` is
        # where one that works is. Nothing here can reach a real service.
        ROUH_ONE_APP_DIR=str(folder / "not-a-checkout"),
        ONE_SYSTEMCTL="/bin/true",
        ONE_HEALTH_URL="",
        PYTHONUNBUFFERED="1",
    )
    make_account(data, env)
    seed_tasks(env, data, workspace)
    app = start(
        "rouh-with-one",
        [sys.executable, "-m", "uvicorn", "rouh.server:app",
         "--host", "127.0.0.1", "--port", str(port), "--log-level", "info"],
        env,
        health=f"http://127.0.0.1:{port}/healthz",
        url=f"http://127.0.0.1:{port}",
        folder=folder,
        data=data,
    )
    yield app
    stop(app)


# ---------------------------------------------------------------------------
# Two services, two checkouts, two marks
# ---------------------------------------------------------------------------
#
# There are two programs on this machine and they are deployed separately:
# Rouh, out of /var/www/rouh/app, and the one program, out of /srv/one/app.
# The top bar has a mark for each, and each mark compares the commit its own
# service is answering from against the commit `origin/main` is at in that
# service's own checkout.
#
# The top bar used to hold a single pair that compared the one program's running
# commit against the newest commit in Rouh's checkout. That is one service's
# running code against another service's copy of the repository: the two were
# never commits of the same thing, so they could never agree, and every deploy of
# Rouh announced an update for the one program. Proving that is gone needs a
# world where each service has a checkout of its own and a `main` a test can move
# without touching the other.


@dataclass
class TwoChipWorld:
    """Rouh and the one program, each with a checkout of its very own."""

    #: The Rouh serving the page, pointed at both checkouts below.
    rouh: App
    #: What /var/www/rouh/app stands in for. The Rouh above reports the
    #: commit this checkout is standing on as the build that is answering.
    rouh_repo: ServiceRepo
    #: What /srv/one/app stands in for: the one program's own checkout, which is
    #: where its mark reads the commit waiting for it.
    one_repo: ServiceRepo


@pytest.fixture(scope="session")
def two_chip_world(tmp_path_factory, one_app) -> TwoChipWorld:
    """Rouh and the one program, each read out of its own checkout."""
    folder = tmp_path_factory.mktemp("two-chips")
    rouh_repo = a_service_repo(folder, "rouh")
    one_repo = a_service_repo(folder, "one")

    token = folder / "voice.json"
    subprocess.run(
        [sys.executable, "-m", "one.cli", "pair", "voice", "--save", str(token)],
        cwd=str(ROOT), check=True, capture_output=True, text=True, timeout=30,
        env=one_env(one_app),
    )
    data = folder / "data"
    data.mkdir()
    workspace = folder / "workspace"
    build_workspace(workspace)
    port = free_port()
    env = clean_env("ROUH_", "JARVIS_", "ONE_")
    env.update(
        ROUH_DATA_DIR=str(data),
        # The address this world is opened at, so a link Rouh writes to itself opens here.
        ROUH_PUBLIC_URL=f"http://127.0.0.1:{port}",
        # The landing lock and the conflict records (`land.sh`,
        # `rouh/conflicts.py`), in a folder of this world's own. Without it
        # every world would read the real ones, so a live job's question would
        # turn a test's orb red and a test's answer would decide a live job's
        # conflict.
        ROUH_LAND_DIR=str(folder / "land"),
        # Rouh's own checkout: where its mark reads both of its commits.
        ROUH_APP_DIR=str(rouh_repo.checkout),
        # A workspace of this world's own, and it has to be one. With nothing
        # here the configuration falls back to this checkout's own
        # `workspace/` (`rouh/config._workspace_root`), so anything that
        # writes a task folder - promoting a chat, filing a card - writes it
        # into the repository the suite is running out of. That really
        # happened on 22 September 2026: a run started from the Start box in
        # this world left `workspace/unfiled/51.…` in the checkout.
        ROUH_ASSISTANT_REPO=str(workspace),
        ROUH_DELEGATE="0",
        ROUH_SELF_UPDATE="0",
        ROUH_SHELL="0",
        # The one program that is really running, and its own checkout. Nothing
        # says ROUH_ONE_REPO here on purpose: the one mark has to reach for the
        # program's own checkout by itself, because that is what every real
        # machine is, and reading Rouh's instead is the bug being kept out.
        ROUH_ONE_SOCKET=one_app.socket_path or "",
        ROUH_ONE_TOKEN=str(token),
        ROUH_ONE_APP_DIR=str(one_repo.checkout),
        # Nothing here may restart a service. No test in this file presses the
        # deploy button, and if one ever did it would stop at a stand-in.
        ONE_SYSTEMCTL="/bin/true",
        ONE_HEALTH_URL="",
        PYTHONUNBUFFERED="1",
    )
    make_account(data, env)
    seed_tasks(env, data, workspace)
    app = start(
        "rouh-two-chips",
        [sys.executable, "-m", "uvicorn", "rouh.server:app",
         "--host", "127.0.0.1", "--port", str(port), "--log-level", "info"],
        env,
        health=f"http://127.0.0.1:{port}/healthz",
        url=f"http://127.0.0.1:{port}",
        folder=folder,
        data=data,
    )
    yield TwoChipWorld(rouh=app, rouh_repo=rouh_repo, one_repo=one_repo)
    stop(app)


def pairing_code(app: App) -> str:
    """A six-digit code from the program itself, through the `one` command.

    This is how the person does it, so it is how the test does it: nothing
    reaches inside the program to mint a token.
    """
    out = subprocess.run(
        [sys.executable, "-m", "one.cli", "pair", "browser"],
        cwd=str(ROOT), capture_output=True, text=True, timeout=30,
        env={**clean_env("ONE_"), "ONE_SOCKET": app.socket_path or ""},
    )
    found = re.search(r"\b(\d{6})\b", out.stdout)
    if not found:
        raise RuntimeError(f"no pairing code came back:\n{out.stdout}\n{out.stderr}")
    return found.group(1)


# ---------------------------------------------------------------------------
# A one program that can actually be deployed
# ---------------------------------------------------------------------------
#
# The one program's mark says the program answering is on a different commit
# from the one waiting in its own checkout, and the button under it deploys the
# program to catch up. Proving that needs three things no other fixture has: a
# checkout the deploy can move, a `main` somewhere for it to be moved onto, and
# a program really being served from that checkout, so the commit on the mark
# afterwards is a commit that is genuinely running.
#
# So the world is two clones of this repository. `origin` is what a deploy
# fetches from and where a test merges; `checkout` is /srv/one/app's stand-in,
# the folder the program is started from, the folder the mark reads
# `origin/main` out of, and the folder the deploy fast-forwards. The only thing standing in for the real
# machine is systemctl, because a test may not restart a service on the machine
# it is running on: `fake_systemctl.py` restarts the program the fixture
# started instead, from the same checkout, which is what the real one does.


@dataclass
class OneWorld:
    """A one program of its own, with somewhere to deploy it from."""

    #: The program, running, served out of `checkout`.
    one: App
    #: Rouh, paired with it and pointed at both folders.
    rouh: App
    #: The checkout the program is served from: /srv/one/app's stand-in. It is
    #: both where the running commit comes from and where the mark reads the
    #: commit waiting for it, because both halves of a mark come out of one
    #: checkout.
    checkout: Path
    #: Where `main` lives, which is what a deploy fetches.
    origin: Path

    def merge(self, version: str) -> str:
        """Put a new version of the one program on `main`, and say its commit.

        This is "somebody merged while the old program carried on serving",
        which is the situation the button exists for. The version is moved as
        well as the commit, so the program answering after the deploy can be
        asked whether it is genuinely the new code.
        """
        # The whole file, because the whole file is the version: one/__init__.py
        # is a docstring and `__version__`, and the program imports it as it is.
        (self.origin / "one" / "__init__.py").write_text(
            f'"""one, in a world a test made."""\n\n__version__ = "{version}"\n')
        subprocess.run(["git", "add", "-A"], cwd=self.origin, check=True)
        subprocess.run(["git", "commit", "-q", "-m", f"one {version}"],
                       cwd=self.origin, check=True)
        # Fetched into the program's own checkout, because that is where the
        # mark looks: `origin/main` there is what the next deploy would take.
        subprocess.run(["git", "fetch", "-q", "origin"], cwd=self.checkout, check=True)
        return _short(self.checkout, "origin/main")


@pytest.fixture(scope="session")
def one_deploy_world(tmp_path_factory) -> OneWorld:
    """Rouh, a one program it can deploy, and the two folders in between."""
    folder = tmp_path_factory.mktemp("one-deploy")
    origin, checkout = folder / "origin", folder / "checkout"

    # `main` in a copy of this repository, with nothing pointing at GitHub: a
    # deploy in a test must never reach the network, and a fetch of a remote
    # that is not there would.
    _clone(ROOT, origin)
    subprocess.run(["git", "checkout", "-q", "-B", "main"], cwd=origin, check=True)
    subprocess.run(["git", "remote", "remove", "origin"], cwd=origin, check=True)
    # The checkout the program is served from, one fetch away from that.
    _clone(origin, checkout, branch="main")

    world = folder / "world"
    port = free_port()
    log = folder / "one.log"
    plan = folder / "systemctl.json"
    pidfile = folder / "one.pid"
    env = {**clean_env("ONE_"), "PYTHONUNBUFFERED": "1", "PYTHONPATH": str(checkout)}
    argv = [sys.executable, "-m", "one.tests.dev_server", str(world), str(port)]

    # What "restart one.service" means here, written down for the stand-in.
    plan.write_text(json.dumps({
        "argv": argv, "cwd": str(checkout), "env": env,
        "log": str(log), "pidfile": str(pidfile),
    }))
    systemctl = folder / "systemctl"
    systemctl.write_text("#!/bin/sh\nexec {} {} {} \"$@\"\n".format(
        sys.executable, ROOT / "tests" / "e2e" / "fake_systemctl.py", plan))
    systemctl.chmod(0o755)

    one_app = start(
        "one-deployable", argv, env,
        health=f"http://127.0.0.1:{port}/one/healthz",
        url=f"http://127.0.0.1:{port}/one",
        folder=folder, cwd=checkout,
        socket_path=str(world / "s.sock"), data=world,
    )
    # The stand-in stops whatever it is told is running, so it has to be told
    # about the one this fixture started.
    pidfile.write_text(str(one_app.process.pid))

    token = folder / "voice.json"
    subprocess.run(
        [sys.executable, "-m", "one.cli", "pair", "voice", "--save", str(token)],
        cwd=str(ROOT), check=True, capture_output=True, text=True, timeout=30,
        env={**clean_env("ONE_"), "ONE_SOCKET": one_app.socket_path or ""},
    )

    data = folder / "data"
    data.mkdir()
    workspace = folder / "workspace"
    build_workspace(workspace)
    rouh_port = free_port()
    rouh_env = clean_env("ROUH_", "JARVIS_", "ONE_")
    rouh_env.update(
        ROUH_DATA_DIR=str(data),
        # The address this world is opened at, so a link Rouh writes to itself opens here.
        ROUH_PUBLIC_URL=f"http://127.0.0.1:{rouh_port}",
        # The landing lock and the conflict records (`land.sh`,
        # `rouh/conflicts.py`), in a folder of this world's own. Without it
        # every world would read the real ones, so a live job's question would
        # turn a test's orb red and a test's answer would decide a live job's
        # conflict.
        ROUH_LAND_DIR=str(folder / "land"),
        # Where the deploy script is read from: this checkout, which is the one
        # under test. Rouh runs its own copy against the program's checkout,
        # never the program's copy of it.
        ROUH_APP_DIR=str(ROOT),
        # A workspace of this world's own, and it has to be one. With nothing
        # here the configuration falls back to this checkout's own
        # `workspace/` (`rouh/config._workspace_root`), so anything that
        # writes a task folder - promoting a chat, filing a card - writes it
        # into the repository the suite is running out of. That really
        # happened on 22 September 2026: a run started from the Start box in
        # this world left `workspace/unfiled/51.…` in the checkout.
        ROUH_ASSISTANT_REPO=str(workspace),
        ROUH_DELEGATE="0",
        ROUH_SELF_UPDATE="0",
        ROUH_SHELL="0",
        ROUH_ONE_SOCKET=one_app.socket_path or "",
        ROUH_ONE_TOKEN=str(token),
        # The program's own checkout, and nothing else: the commit waiting for
        # it is `origin/main` there, which is what a deploy fetches and
        # fast-forwards onto, and the commit it is running is what the program
        # itself answers. Nothing says ROUH_ONE_REPO, so the mark reaches for
        # the checkout by itself, the way it does on the real machine.
        ROUH_ONE_APP_DIR=str(checkout),
        # What the script is given instead of the machine's own service, its
        # packages and its health check.
        ONE_SYSTEMCTL=str(systemctl),
        ONE_SERVICE="one.service",
        ONE_VENV=sys.prefix,
        ONE_HEALTH_URL=f"http://127.0.0.1:{port}/one/healthz",
        PYTHONUNBUFFERED="1",
    )
    make_account(data, rouh_env)
    seed_tasks(rouh_env, data, workspace)
    rouh = start(
        "rouh-deploying-one",
        [sys.executable, "-m", "uvicorn", "rouh.server:app",
         "--host", "127.0.0.1", "--port", str(rouh_port), "--log-level", "info"],
        rouh_env,
        health=f"http://127.0.0.1:{rouh_port}/healthz",
        url=f"http://127.0.0.1:{rouh_port}",
        folder=folder, data=data,
    )
    yield OneWorld(one=one_app, rouh=rouh, checkout=checkout, origin=origin)
    stop(rouh)
    # Whatever is serving now, which is not the process this fixture started if
    # a test has deployed since.
    try:
        os.kill(int(pidfile.read_text().strip()), signal.SIGTERM)
    except (OSError, ValueError):
        pass
    stop(one_app)


# ---------------------------------------------------------------------------
# Codex's sign-in with a ChatGPT plan
# ---------------------------------------------------------------------------
#
# Petar, 6 November 2026: signing Codex in must be one press and no terminal. The page is
# Rouh's (`rouh/web/codex_signin.py`) and the sign-in is the one program's
# (`one/codex_signin.py`), so this world is both, paired, with the sign-in turned on the way
# the containers' images turn it on, and Codex's folder a throwaway one of its own.
#
# Codex is the stand-in (`one/tests/fake_codex_login.py`) unless ROUH_TEST_REAL_CODEX names
# the real one, whose device sign-in reaches OpenAI for a real code: nobody approves it but a
# person, and an unapproved code expires by itself in 15 minutes. With the stand-in, a code
# is approved by `touch <codex_home>/fake-approve` and refused by `fake-refuse`.


@dataclass
class CodexSignInWorld:
    """Rouh's sign-in page and the one program that signs Codex in."""

    #: The Rouh serving /setup/codex and Settings, Models.
    rouh: App
    #: The one program, which runs Codex's own login.
    one: App
    #: Codex's folder in this world: auth.json is written here, and the stand-in's knobs.
    codex_home: Path


@pytest.fixture(scope="session")
def codex_signin_world(tmp_path_factory) -> CodexSignInWorld:
    real = os.environ.get("ROUH_TEST_REAL_CODEX", "")
    folder = tmp_path_factory.mktemp("codex-signin")
    codex_home = folder / "codex-home"
    codex_home.mkdir(mode=0o700)
    one_port = free_port()
    world = folder / "one-world"
    one_env_ = clean_env("ONE_")
    one_env_.update(PYTHONUNBUFFERED="1", ONE_CLAUDE_SIGNIN="1", CODEX_HOME=str(codex_home))
    if real:
        one_env_["ONE_TEST_CODEX"] = real
    one = start(
        "one-codex-signin",
        [sys.executable, "-m", "one.tests.dev_server", str(world), str(one_port)],
        one_env_,
        health=f"http://127.0.0.1:{one_port}/one/healthz",
        url=f"http://127.0.0.1:{one_port}/one",
        folder=folder, socket_path=str(world / "s.sock"), data=world,
    )
    token = folder / "voice.json"
    subprocess.run(
        [sys.executable, "-m", "one.cli", "pair", "voice", "--save", str(token)],
        cwd=str(ROOT), check=True, capture_output=True, text=True, timeout=30, env=one_env(one),
    )
    data = folder / "data"
    data.mkdir()
    workspace = folder / "workspace"
    build_workspace(workspace)
    keys = folder / "keys"
    keys.mkdir()
    port = free_port()
    env = clean_env("ROUH_", "JARVIS_", "ONE_")
    env.update(
        ROUH_DATA_DIR=str(data),
        ROUH_PUBLIC_URL=f"http://127.0.0.1:{port}",
        ROUH_LAND_DIR=str(folder / "land"),
        ROUH_APP_DIR=str(ROOT),
        ROUH_ASSISTANT_REPO=str(workspace),
        ROUH_DELEGATE="0",
        ROUH_SELF_UPDATE="0",
        ROUH_SHELL="0",
        ROUH_ONE_SOCKET=one.socket_path or "",
        ROUH_ONE_TOKEN=str(token),
        ROUH_ONE_APP_DIR=str(folder / "not-a-checkout"),
        # The sign-in pages, as the core's image turns them on, and a keys folder of its own.
        ROUH_CLAUDE_SIGNIN="1",
        ROUH_KEYS_DIR=str(keys),
        ONE_SYSTEMCTL="/bin/true",
        ONE_HEALTH_URL="",
        PYTHONUNBUFFERED="1",
    )
    make_account(data, env)
    seed_tasks(env, data, workspace)
    rouh = start(
        "rouh-codex-signin",
        [sys.executable, "-m", "uvicorn", "rouh.server:app",
         "--host", "127.0.0.1", "--port", str(port), "--log-level", "info"],
        env,
        health=f"http://127.0.0.1:{port}/healthz",
        url=f"http://127.0.0.1:{port}",
        folder=folder, data=data,
    )
    yield CodexSignInWorld(rouh=rouh, one=one, codex_home=codex_home)
    stop(rouh)
    stop(one)
