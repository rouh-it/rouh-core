"""Deploying: both services at once, and the one program from its mark alone.

Two deploys live here, because they are the same job done to two services and
keeping them apart cost a day on 14 September.

:func:`start_deploy` is **the** deploy. It runs ``update-all.sh``, which puts
the one program and Rouh on the same commit, the one program first because
updating Rouh restarts the process that asked for it. ``deploy_myself`` and
the deploy that follows a landed change both go through it, and that is the
whole point of it: until 19 September 2026 the automatic deploy ran Rouh's
update script and nothing else, so Rouh reached 7596716 while the one program
sat four commits behind on 6edd106, and no screen anywhere said so.

:class:`Deployer` is the one program on its own, started by the button under
its version mark. It stays as it is: a person pressing that button is asking
for that program and is not asking to be restarted themselves.

The mark beside the voice icon on the top bar already says when the one program
serving this machine is answering from a different commit than the one waiting
on ``origin/main`` in its own checkout (``one_version.py``). Saying so and
leaving the person to go and find a terminal is half an answer, so the panel
behind the mark carries a button, and this is what the button does.

One command: ``one/deploy/update.sh``, out of Rouh's own checkout, run as
root because that is what Rouh runs as. It fetches ``main`` into the one
program's checkout, fast-forwards onto it, installs packages only when
``one/requirements.txt`` was one of the things that changed, imports the new
code before anything restarts, restarts ``one.service`` and waits for the
program to answer its own health check, putting the old commit back if it does
not. Every one of those decisions belongs in the script, where a person can
read it and run it by hand; this file starts it, stops two of them running at
once, and turns whatever happened into one sentence a browser can show.

Rouh is never deployed by :class:`Deployer`, and the button under the mark
is the only thing left that uses it on its own. Everything that has to move
both services goes through :func:`start_deploy` above, which runs a script
that runs this one first and Rouh's second.

The work is started and then let go of: the browser is told the deploy has
begun, and the result reaches every open tab down the websocket when it is
done. A restart plus a health check is twenty seconds on a good day, which is
longer than a proxy in front of Rouh is willing to hold a request open, and a
person whose deploy worked should never be shown a timeout because of it.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import time

from .config import config

log = logging.getLogger("rouh.one_deploy")


class AlreadyDeploying(RuntimeError):
    """A deploy was asked for while one was still running."""


#: The deploy, inside Rouh's own checkout: both services, one commit.
#: `deploy/rouh.sh` is only Rouh's half of this and is what it runs
#: second; nothing starts either half by itself any more, and both refuse to
#: run without the marker this script sets.
DEPLOY_SCRIPT = "update-all.sh"

#: How long after one is started another is refused here. This is the cheap
#: half of stopping two deploys at once: the second one's work is on main and
#: the first one's fetch takes it anyway, so within two minutes there is
#: nothing for it to do. The half that actually holds the line is the exclusive
#: lock inside ``update-all.sh``, which every way of starting a deploy goes
#: through, including ``land.sh``'s own last step since 21 September 2026; a
#: deploy started while another is running waits for it there rather than
#: racing it over the same two checkouts.
AGAIN_AFTER = 120.0

#: When the last Rouh update was started, by this process.
_last_update = 0.0


def deploy_script(cfg=config) -> str:
    """The script that puts both services on the newest code, wherever it is."""
    return cfg.deploy_script or os.path.join(cfg.app_dir, DEPLOY_SCRIPT)


def start_deploy(cfg=config, to: str | None = None) -> dict:
    """Start both services going onto the newest code, and let go of it.

    The one program is brought up first and Rouh second - that order is
    ``update-all.sh``'s, not this function's - so one call here is the whole
    deploy and neither service can be left behind.

    Detached on purpose, and this is the whole reason it is a function of its
    own: the process calling it is the process being restarted, so anything
    that waited for the result would be killed before it could report, and the
    person would hear nothing at all. Raises if the script is not there, if it
    will not start, or if one is already going, all of which are things to say
    out loud rather than things to swallow.

    It is also where the card for the deploy is written down, and returned, so
    that both ways Rouh restarts onto its own code - the voice asking for it,
    and a run of the one program landing a change - put the same row on the
    task list, and the Rouh that comes up afterwards finishes it. See
    ``rouh/self_update.py``: a card whose job is killed by the very restart
    it announced cannot report its own result, so nothing in this process ever
    will.
    """
    import subprocess

    from . import self_update

    global _last_update
    since = time.monotonic() - _last_update
    if _last_update and since < AGAIN_AFTER:
        raise AlreadyDeploying(
            f"Rouh started deploying {since:.0f} seconds ago and is still going; "
            "that deploy fetches main, so it takes this change with it.")
    script = deploy_script(cfg)
    if not os.path.exists(script):
        raise FileNotFoundError(f"there is no update script at {script}")
    argv = ["setsid", "--fork", "bash", script] + (["--to", str(to)] if to else [])
    subprocess.Popen(argv, cwd=cfg.app_dir, start_new_session=True,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL,
                     # Where to write down how it went, and where the data
                     # directory is, said out loud rather than left to whatever
                     # the service happens to have been started with.
                     env={**os.environ,
                          "ROUH_DATA_DIR": cfg.data_dir,
                          "ROUH_UPDATE_OUTCOME": self_update.outcome_path()})
    _last_update = time.monotonic()
    return self_update.begin(to)


#: The one program's half, inside Rouh's own checkout of this repository.
#: Rouh's copy rather than the one program's on purpose: the program's
#: checkout is the thing being moved, and a script that rewrites itself half
#: way through is how the 14 September deploy ran half of one version and half
#: of another.
SCRIPT = "one/deploy/update.sh"

#: How long the whole thing gets. The script's own health check gives up after
#: twenty seconds, and installing packages is the only step that can be slow,
#: so anything past this is stuck rather than working.
SECONDS = 300

#: How much of the script's output is kept for the page. The last line is the
#: sentence a person is shown; the rest is there for whoever has to find out
#: why afterwards.
LINES = 40

BUSY = ("The one program is already being deployed. Wait for that to finish "
        "before starting another.")


def _tail(text: str, lines: int = LINES) -> str:
    return "\n".join(text.strip().splitlines()[-lines:])


def _last_sentence(text: str, fallback: str) -> str:
    """The last thing the script said, which is what it said went wrong.

    Every failing path in the script ends by printing one plain sentence, so
    this is the sentence rather than a fragment of a stack trace.
    """
    for line in reversed(text.strip().splitlines()):
        if line.strip():
            return line.strip()
    return fallback


class Deployer:
    """The one deploy of the one program that may be running at a time."""

    def __init__(self, cfg=config) -> None:
        self.cfg = cfg
        #: True from the moment a deploy is accepted until the script has
        #: finished, so a second press is answered rather than obeyed.
        self.busy = False

    def script(self) -> str:
        return self.cfg.one_deploy_script or os.path.join(self.cfg.app_dir, SCRIPT)

    def environment(self) -> dict[str, str]:
        """What the script is run with.

        Rouh's own environment, so the settings systemd gives this service
        are the settings the script gets, plus the one thing Rouh is sure
        about: which checkout the one program is served from.
        """
        return {**os.environ, "ONE_APP_DIR": self.cfg.one_app_dir}

    def start(self) -> "asyncio.Task[dict]":
        """Begin a deploy, and hand back the work so somebody can wait on it.

        The flag is set here rather than inside the task on purpose. Two
        presses a hundredth of a second apart both reach this before either
        task has had a chance to run, and the second of them has to be refused
        rather than start a second git fetch over the top of the first.
        """
        if self.busy:
            raise AlreadyDeploying(BUSY)
        self.busy = True
        return asyncio.ensure_future(self._guarded())

    async def _guarded(self) -> dict:
        try:
            return await self._deploy()
        finally:
            self.busy = False

    async def _deploy(self) -> dict:
        """Deploy the one program, and say in one sentence how it went.

        Never raises: a deploy that fails is an answer to give the person, not
        an error to hand to a stack trace.
        """
        script = self.script()
        if not os.path.exists(script):
            return {"ok": False, "log": "",
                    "error": f"There is no update script at {script}, "
                             "so I cannot deploy the one program."}
        log.info("deploying the one program: %s against %s", script, self.cfg.one_app_dir)
        try:
            process = await asyncio.create_subprocess_exec(
                "bash", script,
                cwd=self.cfg.app_dir,
                env=self.environment(),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
        except OSError as exc:
            log.exception("the one program's update script would not start")
            return {"ok": False, "log": "",
                    "error": f"The update script would not start: {exc}"}
        try:
            out, _ = await asyncio.wait_for(process.communicate(), SECONDS)
        except asyncio.TimeoutError:
            with contextlib.suppress(ProcessLookupError):
                process.kill()
            await process.wait()
            log.error("the one program's deploy did not finish within %ss", SECONDS)
            return {"ok": False, "log": "",
                    "error": f"The deploy did not finish within {SECONDS} seconds "
                             "and was stopped. The one program may need a person."}
        text = (out or b"").decode("utf-8", "replace")
        if process.returncode == 0:
            log.info("the one program was deployed: %s", _last_sentence(text, ""))
            return {"ok": True, "log": _tail(text), "error": ""}
        log.error("deploying the one program failed (%s):\n%s", process.returncode, _tail(text))
        return {"ok": False, "log": _tail(text),
                "error": _last_sentence(
                    text, f"The deploy failed and said nothing (exit {process.returncode}).")}
