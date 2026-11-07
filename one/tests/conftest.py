"""Shared helpers for the program's tests.

Unix socket paths are limited to about a hundred characters, and pytest's own
temporary folders on a Mac are longer than that, so anything that makes a
socket gets a short folder under /tmp instead.

Every fixture here also owns what it started. A test that starts a run starts
two real processes - a holder, and an agent on a terminal the holder opened -
and both are meant to outlive the program that asked for them, which in a test
means outliving the test. `strays` is what puts them away; the rules and the
reasoning are in that file.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from one.tests import strays  # noqa: E402  (needs ROOT on the path first)


@pytest.fixture
def short_dir():
    """A folder of this test's own, and nothing of this test's left running.

    The reaping comes before the folder goes, because a holder writes its pid
    into its own folder and that is the cheapest way to find it.
    """
    path = strays.watch(tempfile.mkdtemp(prefix="one-", dir="/tmp"))
    try:
        yield path
    finally:
        strays.reap(path)
        shutil.rmtree(path, ignore_errors=True)


@pytest.fixture(scope="session", autouse=True)
def _nothing_is_left_running(tmp_path_factory):
    """The backstop: at the end of the session, sweep every folder claimed.

    A fixture that reaps its own folder is the defence. This is what catches
    the cases a fixture cannot: a test killed between starting a run and its
    teardown, a fixture added later that forgets, a folder pytest made rather
    than this file. It reaps rather than fails, because a check that leaves the
    machine dirty and then reports a failure has done the worse of the two
    things. `test_no_strays.py` used to fail when this defence stopped working,
    and it went with every other committed test on 20 September 2026, so a check
    you write yourself is what will find it next.
    """
    strays.watch(tmp_path_factory.getbasetemp())
    yield
    stopped = strays.reap(*strays.watched())
    if stopped:
        print("\n" + strays.report(stopped, "this test session's folders"))


def pytest_configure(config):
    os.environ.setdefault("ONE_TESTING", "1")
    # A landing of its own, never the server's. A run in a test lands through
    # land.sh like any other, and a conflict record it writes into
    # /srv/rouh-land is a question read out to the owner: on 18 October 2026 six
    # were. The program passes this on to land.sh (`Settings.land_dir`).
    said = os.environ.get("ROUH_LAND_DIR") or os.environ.get("JARVIS_LAND_DIR") or ""
    if not said or os.path.realpath(said) == os.path.realpath("/srv/rouh-land"):
        os.environ["ROUH_LAND_DIR"] = tempfile.mkdtemp(prefix="one-land-", dir="/tmp")
        os.environ["JARVIS_LAND_DIR"] = os.environ["ROUH_LAND_DIR"]
