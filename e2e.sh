#!/usr/bin/env bash
#
# The browser environment: the venv, the browser, and a real app to drive.
#
# There are no committed tests in this repository at all. A feature proves
# itself: a real browser driven at it live, over Playwright MCP, by whoever
# built it, and a Python check they write, run and throw away. AGENTS.md says
# how.
#
# What is left here is the part that was always the valuable part, and it is
# kept working:
#
#   ./e2e.sh                     build .venv-e2e and the browser, and say so
#   ./e2e.sh serve               stand Rouh up and hold it, for a browser
#   ./e2e.sh serve --list        name the worlds tests/e2e/conftest.py builds
#   ./e2e.sh serve one_deploy_world      stand one of the others up
#   ./e2e.sh visual              the screenshot comparisons (--update: new baselines)
#   ./e2e.sh tests/e2e/whatever.py       a test file you wrote yourself
#
# Anything else after ./e2e.sh still goes straight to pytest, so a throwaway
# test you write while you are working runs the same way it always did. Nothing
# this does reaches the network or spends a token.
set -euo pipefail
cd "$(dirname "$0")"

# Nothing started from here ever lands into the server's own landing directory.
# A conflict record written there is a question read out to the owner, and on 18
# October 2026 six were: the one program's old tests, brought back from history
# by a nightly run and run through here, landed into /srv/rouh-land and reached
# the owner as real decisions. So every test, world and check this starts gets a
# landing directory of its own, unless it was already given one that is not the
# server's. (rouh/conflicts.py refuses such a record as well; this is the first
# of the two locks.)
real_land=$(realpath -m /srv/rouh-land)
said_land="${ROUH_LAND_DIR:-${JARVIS_LAND_DIR:-/srv/rouh-land}}"
if [ "$(realpath -m "$said_land")" = "$real_land" ]; then
  ROUH_LAND_DIR=$(mktemp -d "${TMPDIR:-/tmp}/rouh-land-XXXXXX")
  JARVIS_LAND_DIR="$ROUH_LAND_DIR"
  export ROUH_LAND_DIR JARVIS_LAND_DIR
fi

VENV=.venv-e2e
REQ=tests/e2e/requirements.txt
STAMP="$VENV/.installed-from"

python_for_venv() {
  # The interpreter pyenv names in .python-version (3.12.14, what the server
  # runs), when pyenv has it; otherwise whatever 3.12 is on the PATH.
  if command -v pyenv >/dev/null 2>&1 && p="$(pyenv which python3.12 2>/dev/null)"; then
    echo "$p"; return
  fi
  for p in "$HOME/.pyenv/versions/$(cat .python-version 2>/dev/null)/bin/python3" python3.12; do
    command -v "$p" >/dev/null 2>&1 && { echo "$p"; return; }
  done
  echo "no python 3.12 found: pyenv install $(cat .python-version 2>/dev/null)" >&2
  exit 1
}

# uv installs, as it does for the project itself (pyproject.toml); pip when a
# machine has no uv yet.
install() {
  if command -v uv >/dev/null 2>&1; then
    uv pip install --quiet --python "$VENV/bin/python" "$@"
  else
    "$VENV/bin/python" -m pip install --quiet "$@"
  fi
}

if [ ! -x "$VENV/bin/python" ]; then
  echo "e2e: making $VENV"
  if command -v uv >/dev/null 2>&1; then
    uv venv --quiet --python "$(python_for_venv)" "$VENV"
  else
    "$(python_for_venv)" -m venv "$VENV"
    "$VENV/bin/python" -m pip install --quiet --upgrade pip
  fi
fi

# Reinstall only when the requirements have actually changed.
want=$(cat "$REQ" rouh/requirements.txt one/requirements.txt | sha256sum | cut -d' ' -f1)
if [ "$(cat "$STAMP" 2>/dev/null || true)" != "$want" ]; then
  echo "e2e: installing $REQ (a few minutes the first time)"
  install -r "$REQ"
  # Only Chromium. It lands in ~/.cache/ms-playwright and is skipped once it is
  # there, so this is fast on every run but the first.
  #
  # A download Playwright has no build for does not stop the run. The pinned
  # version refuses outright on a distribution newer than it knows about - "does
  # not support chromium on ubuntu26.04-x64" - and with `set -e` that took the
  # whole run down before anything had started, on a machine whose
  # ~/.cache/ms-playwright already had the browser. So it is said out loud and
  # the run carries on: if there really is no browser here, whatever wanted one
  # says so itself.
  "$VENV/bin/python" -m playwright install chromium || \
    echo "e2e: playwright would not install chromium here - using whatever is already in ~/.cache/ms-playwright"
  echo "$want" > "$STAMP"
fi

# `./e2e.sh serve ...` stands one of conftest.py's worlds up and holds it, which
# is what a browser driven over MCP needs pointing at.
if [ "${1:-}" = "serve" ]; then
  shift
  exec "$VENV/bin/python" -m tests.e2e.serve "$@"
fi

# `./e2e.sh visual` is the screenshot comparisons, the one committed suite
# (tests/e2e/visual/conftest.py says why). `--update` takes new baselines on
# purpose; anything else goes to pytest, so `-k brief` picks one screen.
if [ "${1:-}" = "visual" ]; then
  shift
  args=()
  for a in "$@"; do
    if [ "$a" = "--update" ]; then export ROUH_VISUAL_UPDATE=1; else args+=("$a"); fi
  done
  exec "$VENV/bin/python" -m pytest tests/e2e/visual "${args[@]}"
fi

# Nothing asked for, and no test files to collect: this was the build, and the
# next step is a browser, not pytest.
if [ "$#" -eq 0 ] && ! ls tests/e2e/test_*.py >/dev/null 2>&1; then
  cat <<'DONE'

e2e: the venv and the browser are ready, and there are no committed tests to
     run. That is deliberate: every feature is proved by whoever builds it,
     with a real browser over Playwright MCP and a check of their own that is
     run and then thrown away.

     ./e2e.sh serve            Rouh, up and held, with an account to sign in
     ./e2e.sh serve --list     the other worlds conftest.py can build

     AGENTS.md, under "How a change is proved", has the whole sequence.

DONE
  exit 0
fi

# A file or folder named runs alone. Collecting tests/e2e beside it would also
# run the screenshot comparisons, two minutes of them, with every throwaway test.
for arg in "$@"; do
  if [ -e "${arg%%::*}" ]; then
    exec "$VENV/bin/python" -m pytest "$@"
  fi
done
exec "$VENV/bin/python" -m pytest tests/e2e "$@"
