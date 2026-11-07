#!/usr/bin/env bash
#
# Bring the one program on this machine up to what is on main, and restart it.
#
#   bash one/deploy/update.sh
#
# This is the whole of "deploy the one program", and it is deliberately smaller
# than one/deploy/install.sh beside it. It touches three things: the program's
# own checkout, its packages, and its service. install.sh owns the users, the
# sudo rules, the workspace's page server and the rest of the machine, and none
# of those have any business changing because somebody pressed a button in a
# browser.
#
# **This is half of a deploy, and it is the half that is only this program.**
# It never touches Rouh: the two are separate services with separate
# checkouts, and a person who asks for the one program to catch up is not
# asking to be restarted themselves. What updates both is `update-all.sh` at
# the root of this repository, which runs this script first and Rouh's
# `update.sh` second, both on the one commit it resolved, because updating
# Rouh restarts the process that is speaking and nothing after it is
# reached. Every deploy that has to leave neither service behind goes through
# that script; this one stays for the button under the version chip, which is
# the person asking for this program and no other.
#
# Rouh runs this as root when the version chip in its top bar is pressed
# (rouh/one_deploy.py), `update-all.sh` runs it as the first half of a
# deploy, and a person can run it by hand. Everything it needs is an
# environment variable with the server's value as its default, so a test can
# point it at a throwaway checkout and a stand-in for systemctl and still run
# every line of it.
#
# What it does, in order, and it stops at the first thing that does not work:
#
#   1. fetch main from the checkout's remote, or go to the commit ONE_TARGET
#      names when a combined deploy has already resolved one;
#   2. fast-forward the checkout onto it, refusing rather than throwing away
#      anything that is only here;
#   3. install the packages, but only when one/requirements.txt is one of the
#      things that changed;
#   4. import the new code before anything restarts, because a syntax error
#      caught here costs nothing and the same error caught by systemd costs an
#      outage;
#   5. restart the service;
#   6. wait for the program to answer its own health check, and put the old
#      commit back and restart again if it does not.
set -euo pipefail

APP=${ONE_APP_DIR:-/srv/one/app}
VENV=${ONE_VENV:-/srv/one/venv}
SERVICE=${ONE_SERVICE:-one.service}
SYSTEMCTL=${ONE_SYSTEMCTL:-systemctl}
HEALTH=${ONE_HEALTH_URL:-http://127.0.0.1:8031/one/healthz}
REMOTE=${ONE_REMOTE:-origin}
BRANCH=${ONE_BRANCH:-main}

#: How long the program gets to answer after a restart before this decides the
#: new code is bad and puts the old one back. A test that is proving what
#: happens when it never answers turns it down; nothing else should touch it.
WAIT=${ONE_WAIT:-20}

#: The commit to go to, when something else has already decided. `update-all.sh`
#: resolves origin/main once and hands the same commit to both services, so
#: that a deploy cannot leave them on two different commits because main moved
#: between one fetch and the next. Blank, which is what a person running this
#: by hand gets, means whatever `main` is when the fetch below happens.
TARGET_WANTED=${ONE_TARGET:-}

# Every message is one plain sentence, because the last line this prints is
# what a person reads in the browser when it goes wrong.
say() { echo "$*"; }
die() { echo "$*" >&2; exit 1; }

[ -d "$APP/.git" ] \
  || die "There is no git checkout of the one program at $APP, so there is nothing to update."
# Before anything moves, not after: the new code is imported before the service
# is restarted, and a checkout already fast-forwarded with no way to check it is
# the worst place to stop.
[ -x "$VENV/bin/python" ] \
  || die "There is no Python for the one program at $VENV/bin/python, so nothing can be checked before it is started."

# Rouh runs as root out of a checkout owned by another user, and git refuses
# to answer at all about a repository it thinks belongs to somebody else unless
# the path is named as expected.
git_() { git -c "safe.directory=$APP" -C "$APP" "$@"; }

# Every later step reads the checkout it is standing in: the import check must
# find the new code and not a copy of the program installed somewhere else.
cd "$APP"

BEFORE=$(git_ rev-parse HEAD) || die "Could not read which commit $APP is on."
say "the one program is at ${BEFORE:0:7}"

git_ fetch -q "$REMOTE" "$BRANCH" \
  || die "Could not fetch $BRANCH from $REMOTE, so there is nothing new to go to."
if [ -n "$TARGET_WANTED" ]; then
  TARGET=$(git_ rev-parse --verify --quiet "${TARGET_WANTED}^{commit}") \
    || die "The one program's checkout at $APP has no commit ${TARGET_WANTED:0:7} in it, even after fetching $BRANCH from $REMOTE, so it cannot be put on the same commit as Rouh."
else
  TARGET=$(git_ rev-parse FETCH_HEAD)
fi

if [ "$BEFORE" = "$TARGET" ]; then
  # Pressing the button twice, or pressing it after somebody else has already
  # done it, is allowed to mean the same as pressing it once.
  if [ -n "$TARGET_WANTED" ]; then
    say "already at ${TARGET:0:7}, which is the commit this deploy is going to; nothing to do"
  else
    say "already at ${TARGET:0:7}, which is the newest commit on $BRANCH; nothing to do"
  fi
  exit 0
fi

rollback() {
  git_ reset --hard -q "$BEFORE" || true
  die "$*"
}

git_ merge --ff-only -q "$TARGET" \
  || die "The checkout at $APP cannot be fast-forwarded to ${TARGET:0:7}. It holds a change that is only there, so a person has to look before anything is thrown away."
AFTER=$(git_ rev-parse HEAD)
say "moved to ${AFTER:0:7}"

# Packages only when they actually changed. A pip run on every deploy adds
# tens of seconds to something a person is watching.
if ! git_ diff --quiet "$BEFORE" "$AFTER" -- one/requirements.txt; then
  say "one/requirements.txt changed, installing"
  "$VENV/bin/pip" install -q --disable-pip-version-check -r "$APP/one/requirements.txt" \
    || rollback "The one program's packages would not install, so it has been put back to ${BEFORE:0:7}."
fi

say "checking the new code imports"
PYTHONPATH="$APP" "$VENV/bin/python" -c "import one.program, one.cli" \
  || rollback "The new code does not import, so the one program has been put back to ${BEFORE:0:7} and never restarted."

say "restarting $SERVICE"
"$SYSTEMCTL" restart "$SERVICE" \
  || rollback "Restarting $SERVICE failed, so the checkout has been put back to ${BEFORE:0:7}."

if [ -n "$HEALTH" ]; then
  ok=0
  for _ in $(seq 1 "$WAIT"); do
    if curl -fsS --max-time 4 "$HEALTH" >/dev/null 2>&1; then ok=1; break; fi
    sleep 1
  done
  if [ "$ok" != 1 ]; then
    git_ reset --hard -q "$BEFORE" || true
    "$SYSTEMCTL" restart "$SERVICE" || true
    die "The one program did not answer $HEALTH within ${WAIT} seconds, so it has been put back to ${BEFORE:0:7} and restarted."
  fi
fi

say "the one program is serving ${AFTER:0:7}"
