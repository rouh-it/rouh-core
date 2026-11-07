"""Stand one of the harness's worlds up and leave it running, for a browser.

There are no committed browser tests in this repository any more. A feature
proves itself by a real browser being driven at it live, over Playwright MCP,
by whoever built it. That still needs a real app to point the browser at, and
building one by hand is exactly the mistake `tests/e2e/conftest.py` already
stops anybody making: a free port, a data directory of its own, an account made
by the real admin command, no API keys, nothing that reaches the network, and
everything torn down afterwards.

So this is the same worlds, out of the same fixtures, standing still instead of
being handed to a test:

    .venv-e2e/bin/python -m tests.e2e.serve rouh

It prints the address and the sign-in, and then waits. Stop it with Ctrl-C, or
by sending its own process id a TERM, and every server it started is stopped
and every folder it made is thrown away.

The worlds are the fixtures, by their fixture names, and `--list` names them.
`conftest.py` is not copied here and is not touched: this asks it for the same
fixture functions pytest asks it for, so a world can never drift away from the
one a fixture builds.
"""
from __future__ import annotations

import argparse
import inspect
import os
import shutil
import signal
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests.e2e import conftest  # noqa: E402  (needs ROOT on the path first)

#: The one world that is not a fixture in conftest.py. `rouh/testing/browser.py`
#: starts a Rouh with a stand-in for the model in front of it
#: (`rouh/testing/fake_model.py`) and, with the voice, one for ElevenLabs
#: too, so a reply really is worked out and really is spoken, with no key and
#: nothing reaching the network. conftest.py's Rouh has no model at all, which
#: is right for anything that does not need an answer and useless for anything
#: that does.
TALKING = "talking"
#: The same, with the stand-in for OpenAI given its key, so Luna answers:
#: in General, whose own model it is, and anywhere it is picked.
TALKING_LUNA = "talking_luna"
#: The same, with one provider's key alone, or all four (Petar, 24 October 2026: "An install
#: with only one provider's key must work end to end"). Google's and xAI's stand-in is
#: `rouh/testing/fake_compat.py`; a Google or xAI key typed into Settings reaches it too.
PROVIDER_WORLDS = {
    "talking_openai": dict(luna=True, anthropic=False),
    "talking_google": dict(anthropic=False, google=True),
    "talking_xai": dict(anthropic=False, xai=True),
    "talking_nokeys": dict(anthropic=False),
    "talking_all": dict(luna=True, google=True, xai=True),
    # A fresh install of the containers, before its first run (`rouh/web/firstrun.py`).
    "first_run": dict(first_run=True, anthropic=False),
}

#: The worlds worth standing up by hand, and what each one is for. Every name
#: is a fixture in conftest.py; nothing here describes a world of its own.
WORLDS = {
    "rouh_app": "Rouh on its own, with a small workspace and no one program.",
    "rouh_with_tree": "Rouh serving this checkout's workspace/, which is the tree.",
    "one_app": "The one program in its throwaway world.",
    "rouh_with_one": "Rouh paired with a one program that is really running.",
    "two_chip_world": "Rouh and the one program, each out of a checkout of its own.",
    "one_deploy_world": "A one program that can really be deployed, and a Rouh to do it.",
    TALKING: ("Rouh with stand-ins for the model, the voice and iCloud's contacts, so it "
              "really answers."),
    TALKING_LUNA: "The same, with OpenAI's key, so Luna answers (General's own model).",
    "talking_openai": "talking with OpenAI's key alone: no Anthropic key.",
    "talking_google": "talking with Google's key alone (the stand-in's), no Anthropic or OpenAI key.",
    "talking_xai": "talking with xAI's key alone (the stand-in's), no Anthropic or OpenAI key.",
    "talking_nokeys": "talking with no provider's key at all: type Google's or xAI's into Anatomy, Rouh Land Account, Models.",
    "talking_all": "talking with all four providers' keys: Anthropic, OpenAI, Google and xAI.",
    "codex_signin_world": ("Rouh's Codex sign-in page (/setup/codex) and a one program that signs Codex in; "
                           "touch <its files>/codex-signin*/codex-home/fake-approve to approve a code. "
                           "ROUH_TEST_REAL_CODEX=/usr/local/bin/codex gets a real code from OpenAI."),
    "first_run": ("a fresh install of the containers: no owner, no key; open the setup address it prints. "
                  "A pasted key with WRONG in it is refused, NOCREDIT has no credit."),
}

#: Shorter names for the two everybody wants.
#: "jarvis" is what the first of these was called until 22 September 2026
#: and is kept so that a command anybody has in their fingers still works.
ALIASES = {"rouh": "rouh_app", "jarvis": "rouh_app", "one": "one_app"}


class _Temps:
    """What `tmp_path_factory` is, as far as these fixtures ever ask."""

    def __init__(self, root: Path) -> None:
        self._root = root
        self._made = 0

    def mktemp(self, name: str, numbered: bool = True) -> Path:
        self._made += 1
        folder = self._root / f"{name}{self._made}"
        folder.mkdir(parents=True)
        return folder


class _Fixtures:
    """Just enough of pytest to run a fixture outside of a test.

    A fixture is a plain function that asks for other fixtures by the names of
    its arguments, and a fixture that tears something down is a generator that
    yields once. That is the whole of what conftest.py uses, so that is the
    whole of what this does: resolve arguments by name, remember what each one
    made, and close the generators in the opposite order at the end.
    """

    def __init__(self, temps: _Temps) -> None:
        self._made: dict[str, object] = {"tmp_path_factory": temps}
        self._open: list = []

    def get(self, name: str):
        if name in self._made:
            return self._made[name]
        func = getattr(conftest, name, None)
        if func is None:
            raise SystemExit(f"serve: {name} is not a fixture in conftest.py")
        # pytest wraps a fixture so that calling it directly is an error; the
        # function underneath is the one that builds the thing.
        func = getattr(func, "__wrapped__", func)
        kwargs = {arg: self.get(arg) for arg in inspect.signature(func).parameters}
        made = func(**kwargs)
        if inspect.isgenerator(made):
            self._open.append(made)
            made = next(made)
        self._made[name] = made
        return made

    def close(self) -> None:
        for generator in reversed(self._open):
            try:
                next(generator)
            except StopIteration:
                pass
            except Exception as error:  # the next one still deserves its turn
                print(f"serve: tearing down: {error!r}", file=sys.stderr)
        self._open.clear()


def _addresses(name: str, world) -> list[tuple[str, str]]:
    """What a browser can be pointed at in this world, in the order to try."""
    apps = []
    if getattr(world, "base_url", None):
        apps.append((name, world.base_url))
    for label in ("rouh", "one", "app"):
        app = getattr(world, label, None)
        if getattr(app, "url", None):
            apps.append((label, app.url))
    if getattr(world, "url", None):
        apps.append((name, world.url))
    return apps


def _talking_world(folder: Path, luna: bool = False, **keys):
    """Rouh with a model in front of it, out of `rouh/testing/browser.py`.

    The same generator every browser test used to be handed, opened by hand:
    one `next` to start everything, one more to take it all down again.
    """
    from rouh.testing import accounts, browser

    generator = browser.start(folder, with_voice=True, luna=luna, **keys)
    return generator, next(generator), (accounts.USERNAME, accounts.PASSWORD)


def _wait_until_stopped() -> None:
    """Hold here until somebody says to stop.

    Waiting on a signal rather than on standard input, because a world is as
    often stood up by a job with no terminal attached as by a person with one,
    and a background process whose input is already at its end would shut down
    the moment it had finished starting.
    """
    stop = threading.Event()
    for name in (signal.SIGINT, signal.SIGTERM):
        signal.signal(name, lambda *_: stop.set())
    stop.wait()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m tests.e2e.serve",
        description="Stand a world from tests/e2e/conftest.py up and hold it.")
    parser.add_argument("world", nargs="?", default="rouh",
                        help="which world to stand up (default: rouh)")
    parser.add_argument("--list", action="store_true", help="name the worlds and stop")
    args = parser.parse_args(argv)

    if args.list:
        for name, what in WORLDS.items():
            print(f"  {name:<18} {what}")
        for short, full in ALIASES.items():
            print(f"  {short:<18} the same as {full}")
        return 0

    name = ALIASES.get(args.world, args.world)
    if name not in WORLDS:
        print(f"serve: no world called {args.world}. --list says what there is.",
              file=sys.stderr)
        return 2

    folder = Path(tempfile.mkdtemp(prefix="e2e-serve-"))
    fixtures = _Fixtures(_Temps(folder))
    talking = None
    try:
        if name in (TALKING, TALKING_LUNA):
            talking, world, (username, password) = _talking_world(folder,
                                                                  luna=name == TALKING_LUNA)
        elif name in PROVIDER_WORLDS:
            talking, world, (username, password) = _talking_world(folder, **PROVIDER_WORLDS[name])
        else:
            world = fixtures.get(name)
            username, password = conftest.USERNAME, conftest.PASSWORD
        print(f"\n{name}: up\n")
        for label, url in _addresses(name, world):
            print(f"  {label:<8} {url}")
        if getattr(world, "setup_url", ""):
            print(f"\n  setup    {world.setup_url}  (the address Rouh for Mac opens; no account yet)")
        else:
            print(f"\n  sign in  {username} / {password}")
        # The stand-in for iCloud's contacts, where the world has one, and the
        # Apple ID and app-specific password it accepts.
        icloud = getattr(world, "icloud", None) or {}
        if icloud:
            print(f"  icloud   {icloud['url']}  {icloud['apple_id']} / {icloud['app_password']}")
        # The stand-in for Brevo, where the world has one: every letter Rouh
        # sends lands in its inbox, with its links live.
        mail = getattr(world, "mail", None) or {}
        if mail:
            print(f"  mail     {mail['inbox']}")
        # The stand-in for Apify's LinkedIn scrapers, where the world has one:
        # every search and harvest Rouh asked it for.
        linkedin = getattr(world, "linkedin", None) or {}
        if linkedin:
            print(f"  linkedin {linkedin['calls']}")
        # The stand-in for Slack, where the world has one: its workspace, its knobs and every call.
        slack = getattr(world, "slack", None) or {}
        if slack:
            print(f"  slack    {slack['url']}  (rouh/testing/fake_slack.py: /_say, /_calls, /_posted)")
        # The stand-in for the Philips Hue cloud: the Hue app it knows, its knobs and every call.
        hue = getattr(world, "hue", None) or {}
        if hue:
            print(f"  hue      {hue['url']}  app {hue['client_id']} / {hue['client_secret']} / {hue['app_id']}"
                  "  (rouh/testing/fake_hue.py: /_calls, /_lights, /_expire, /_lapse, /_ratelimit)")
        # The stand-in for the Dreamehome cloud: the account it knows, its knobs and the robot.
        dreame = getattr(world, "dreame", None) or {}
        if dreame:
            print(f"  dreame   {dreame['url']}  account {dreame['email']} / {dreame['password']}"
                  "  (rouh/testing/fake_dreame.py: /_robot, /_calls, /_expire, /_lapse, /_password, /_captcha,"
                  " /_offline, /_error)")
            if dreame.get("mi_user"):
                print(f"           Mi Home {dreame['mi_user']} / {dreame['mi_password']}, code {dreame['mi_code']},"
                      f" picture {dreame['mi_captcha']}  (/_mi {{two_step, captcha, expire, lapse}})")
        # Where this world keeps its own files: its data directory, its
        # workspace, and the folder land.sh writes its lock and its conflict
        # records into. A drive that has to plant something in one of those, or
        # read one back, needs to be told where they are rather than guessing.
        print(f"  its files {folder}")
        print(f"\n  stop it   kill {os.getpid()}, or Ctrl-C here")
        print("\nDrive it with a real browser over Playwright MCP.\n", flush=True)
        _wait_until_stopped()
    finally:
        print("serve: stopping", flush=True)
        if talking is not None:
            try:
                next(talking)
            except StopIteration:
                pass
        fixtures.close()
        shutil.rmtree(folder, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
