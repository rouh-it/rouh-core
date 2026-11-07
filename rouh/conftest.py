"""Keep the tests off the running assistant's data.

`test_session.py` asked for a throwaway database with `os.environ.setdefault`,
which does nothing when the variable is already set - and on the server it
always is, because systemd hands every process `ROUH_DATA_DIR` pointing at the
live one. So the suite either wrote to the assistant's own database or, when it
could not, failed five tests with "attempt to write a readonly database" and
told you nothing about the code.

A conftest is imported before any test module, and therefore before anything
imports `rouh.config` and reads this. Setting it here rather than asking each
test file to remember is the point: a test can only reach the real database by
deliberately undoing this.
"""
from __future__ import annotations

import os
import tempfile

os.environ["ROUH_DATA_DIR"] = tempfile.mkdtemp(prefix="rouh-test-data-")
os.environ.setdefault("ROUH_DELEGATE", "0")
# The one program's socket and Rouh's token for it, pointed where no test
# machine has either, so a test can only reach a program it started itself.
os.environ["ROUH_ONE_SOCKET"] = os.path.join(os.environ["ROUH_DATA_DIR"], "no-one.sock")
os.environ["ROUH_ONE_TOKEN"] = os.path.join(os.environ["ROUH_DATA_DIR"], "no-one-token.json")
# And the Telegram bot, for a harder reason than tidiness: the file this points
# away from is the real one on the server, and a suite that found it would send
# the owner a real message on their real phone every time somebody ran the tests. A
# test that wants to send something points this at a file it wrote itself.
os.environ["ROUH_TELEGRAM_FILE"] = os.path.join(
    os.environ["ROUH_DATA_DIR"], "no-telegram.json")
os.environ.setdefault("ROUH_TELEGRAM_API_BASE", "http://127.0.0.1:1/no-telegram")


def pytest_configure(config):
    """Run every async test, not only the ones someone remembered to mark.

    pytest-asyncio's default mode runs a coroutine test only when it carries
    ``@pytest.mark.asyncio``, and skips the rest with a warning at the end of
    a long run that nobody reads. On 14 September 2026 twelve tests, in
    test_tree.py among others, had been skipped that way on the laptop and on
    the server since they were written. "auto" runs them all.
    """
    if config.pluginmanager.hasplugin("asyncio") and hasattr(config.option, "asyncio_mode"):
        config.option.asyncio_mode = "auto"
