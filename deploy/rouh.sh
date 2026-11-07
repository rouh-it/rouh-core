#!/usr/bin/env bash
#
# Rouh's half of a deploy. **Not a deploy, and not to be run on its own.**
#
# A deploy is `update-all.sh` at the root of the repository, and it is the only
# one. It resolves one commit, moves the one program first and Rouh last, and
# refuses to report success unless both halves moved. This file is what it runs
# for the Rouh half, and `one/deploy/update.sh` is what it runs for the other.
#
# Running only this half moves Rouh and leaves the one program behind, so the
# two can end up on different versions with nothing saying so. That is why
# `update-all.sh` exists at all, why this file is out of the way under a name
# nobody would type by mistake, and why it refuses to run unless
# `update-all.sh` started it.
#
# To move Rouh, run `update-all.sh`. If Rouh is the only one behind it will
# say "Rouh is already at <commit>, nothing to do" for the other half and
# move only what needs moving, so there is never a reason to reach past it.
#
#   ROUH_DEPLOY_HALF=update-all    the marker `update-all.sh` sets. Without it
#                                  this script stops before touching anything.
#   --no-pull                      restart with whatever is in the working tree
#   --to <ref>                     go to a specific commit or branch
#
# This is what Rouh runs on itself, so it has to assume the thing calling it
# is about to be killed. It never restarts in the foreground: it hands the work
# to a detached process, so the answer "I am restarting now" can still be spoken
# before the process that would have spoken it goes away.
#
# The rollback is the point. A change that fails to import, fails to bind, or
# answers /healthz with anything but ok is undone automatically and the previous
# commit is restored. Rouh breaking itself and staying broken is the one
# failure nobody can recover from by asking Rouh.
set -euo pipefail

# Half of a deploy, never the whole of one. `update-all.sh` sets this; a person
# typing this path does not, and gets the one sentence that says what to run.
if [ "${ROUH_DEPLOY_HALF:-${JARVIS_DEPLOY_HALF:-}}" != "update-all" ]; then
  echo "This is only Rouh's half of a deploy, and running it alone leaves the one program behind." >&2
  echo "A deploy is: sudo bash $(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/update-all.sh" >&2
  exit 2
fi

# Every setting is read as ROUH_<name> and then as the JARVIS_<name> it was
# called before the rename, because an installation's settings file and its
# systemd drop-ins may still say the old one and no deploy writes either of
# them. `rouh/config.py` reads both the same way, and RENAME.md says why.
# deploy/installation.env.example lists every setting with its default.
setting() {                       # setting NAME DEFAULT
  local new="$1" old="JARVIS_${1#ROUH_}" said
  said="${!new:-}"
  [ -n "$said" ] || said="${!old:-}"
  printf '%s' "${said:-$2}"
}

APP="$(setting ROUH_APP_DIR /var/www/rouh/app)"
HEALTH="$(setting ROUH_HEALTH_URL http://127.0.0.1:8021/healthz)"
LOG="$(setting ROUH_UPDATE_LOG /var/www/rouh/logs/update.log)"
# The deployment's own venv, its service, and the command that restarts it.
# Each is a setting with a default, so an installation in other folders says
# where, and the whole of this script can be run against a throwaway checkout
# with a stand-in for systemctl, the way `one/deploy/update.sh` already can.
VENV="$(setting ROUH_VENV /var/www/rouh/.venv)"
SERVICE="$(setting ROUH_SERVICE rouh)"
SYSTEMCTL="$(setting ROUH_SYSTEMCTL systemctl)"
#: How long Rouh gets to answer after a restart before this decides the new
#: code is bad and puts the old one back. Forty-five seconds since the move to
#: Django: the first start after a deploy opens the database and indexes the
#: workspace before it answers, and a slow start rolled back is an outage of
#: its own.
WAIT="$(setting ROUH_WAIT 45)"
#: The service's own settings file, which systemd reads for it. The database
#: step below runs with it too, so it sees exactly what the service will see.
ENV_FILE="$(setting ROUH_ENV_FILE /var/www/rouh/.env)"
#: Whether the database step runs as a transient systemd unit with the
#: service's own environment ("unit"), or straight from this script ("here",
#: for a check of your own with a stand-in for systemctl).
PREDEPLOY_AS="$(setting ROUH_PREDEPLOY_AS unit)"
# One line for Rouh itself to read when it comes back up: the word "failed"
# and a sentence, written on every path that does not end in the new code
# running. Without it the card on the task list can only go by which commit is
# answering afterwards, and a rollback lands back on the commit it started
# from, which looks exactly like a restart that changed nothing. Rouh passes
# this path in; by hand it falls back to the data directory beside the app.
OUTCOME="$(setting ROUH_UPDATE_OUTCOME "$(setting ROUH_DATA_DIR /var/www/rouh/data)/self-update-outcome")"
PULL=1
TARGET=""

while [ $# -gt 0 ]; do
  case "$1" in
    --no-pull) PULL=0 ;;
    --to) TARGET="$2"; shift ;;
    *) echo "unknown flag: $1" >&2; exit 2 ;;
  esac
  shift
done

mkdir -p "$(dirname "$LOG")"
# Named, because this log holds both halves of a deploy now: `update-all.sh`
# writes into it and so does the one program's half, and a line that does not
# say which service it is about is a line somebody has to guess at.
say() { echo "[$(date -Is)] rouh: $*" | tee -a "$LOG"; }
# Never fatal: a data directory that cannot be written is no reason to abandon
# an update, and this script runs under set -e.
note() {
  mkdir -p "$(dirname "$OUTCOME")" 2>/dev/null || true
  printf '%s\n' "$*" > "$OUTCOME" 2>/dev/null || true
}

cd "$APP"
BEFORE="$(git rev-parse HEAD)"
say "updating from $BEFORE"

if [ "$PULL" = 1 ]; then
  # A fetch that fails has to say why. It used to run --quiet under set -e, so a
  # key GitHub would not accept, or a GitHub nobody could reach, ended the update
  # with nothing in the log and nothing on the screen - and this script is called
  # by a detached process, so there is no terminal left to have printed it to.
  # Keep git's own stderr, write every line of it to the log, and name the remote.
  if ! fetch_err="$(git fetch --quiet origin 2>&1)"; then
    say "git fetch origin failed, staying at $BEFORE"
    note "failed could not fetch from origin, still on $BEFORE"
    say "  remote: $(git remote get-url origin 2>/dev/null || echo 'unknown')"
    printf '%s\n' "$fetch_err" | while IFS= read -r line; do say "  git: $line"; done
    exit 1
  fi
  if [ -n "$TARGET" ]; then
    # Exactly the commit that was asked for, and nothing near it. This is how
    # `update-all.sh` hands both services the one commit it resolved, so a
    # guess here would be two services on two different commits - the whole
    # failure that script exists to stop. `origin/<ref>` before `<ref>`,
    # because "--to main" means the main that was just fetched.
    want=""
    for candidate in "origin/$TARGET" "$TARGET"; do
      if want="$(git rev-parse --verify --quiet "${candidate}^{commit}")"; then break; fi
    done
    if [ -z "$want" ]; then
      say "there is no commit $TARGET here, staying at $BEFORE"
      note "failed there is no commit $TARGET in $APP, so Rouh was not updated"
      exit 1
    fi
    git reset --hard --quiet "$want"
  else
    git reset --hard --quiet "origin/$(git rev-parse --abbrev-ref HEAD)" 2>/dev/null \
      || git reset --hard --quiet "origin/main"
  fi
elif [ -n "$TARGET" ]; then
  git checkout --quiet "$TARGET"
fi

AFTER="$(git rev-parse HEAD)"
say "now at $AFTER"

# Dependencies only when they actually changed. A pip run on every restart adds
# ten seconds to something that is meant to feel immediate.
if ! git diff --quiet "$BEFORE" "$AFTER" -- rouh/requirements.txt jarvis/requirements.txt \
     pyproject.toml uv.lock 2>/dev/null; then
  say "requirements changed, installing"
  # The package was once called `jarvis/`, so a rollback to a commit from
  # before the rename has the file under the other name.
  REQS=rouh/requirements.txt
  [ -f "$REQS" ] || REQS=jarvis/requirements.txt
  # uv when the machine has it, which is what the project is managed with
  # since the move to Django (pyproject.toml, uv.lock); pip otherwise. Either
  # way it only adds and upgrades - nothing is removed from the venv - so a
  # rollback to the commit before still finds everything it imports.
  if command -v uv >/dev/null 2>&1; then
    install_reqs() { uv pip install -q --python "$VENV/bin/python" -r "$REQS"; }
  else
    install_reqs() { "$VENV/bin/pip" install -q -r "$REQS"; }
  fi
  install_reqs >>"$LOG" 2>&1 || {
    say "install failed, rolling back"
    note "failed the new requirements would not install, rolled back"
    git reset --hard --quiet "$BEFORE"; exit 1
  }
  # Playwright's browser is not pip's to install, so it is asked for here,
  # once, whenever the requirements move. It lands in this user's
  # ~/.cache/ms-playwright and is skipped in a second when it is already
  # there. **Never fatal.** The only thing that needs it is the fallback path
  # of the YouTube transcript tool, which says plainly that there is no
  # browser here rather than failing, and a browser download that will not
  # run on this distribution is no reason to roll a whole deploy back.
  #
  # PLAYWRIGHT_HOST_PLATFORM_OVERRIDE is not a nicety. The pinned Playwright
  # has no build named for a distribution newer than it knows and refuses
  # outright - "does not support chromium on <distribution>" - so without it
  # there is no browser at all. Named as the newest distribution it does know,
  # it takes the fallback build, which runs on the newer ones too.
  # ROUH_PLAYWRIGHT_PLATFORM says another.
  if "$VENV/bin/python" -c "import playwright" 2>/dev/null; then
    PLAYWRIGHT_HOST_PLATFORM_OVERRIDE="$(setting ROUH_PLAYWRIGHT_PLATFORM ubuntu22.04-x64)" \
      "$VENV/bin/python" -m playwright install chromium >>"$LOG" 2>&1 \
      || say "playwright would not install chromium here; the YouTube fallback will say so"
  fi
fi

# Import the code before restarting anything. A syntax error caught here costs
# nothing; the same error caught by systemd costs an outage and a restart loop.
# Whichever package this checkout has: `rouh/`, or `jarvis/` on a commit from
# before the rename, which is what a rollback across the rename lands on.
# RENAME.md says when the second half can go.
CHECK=rouh.server
[ -d rouh ] || CHECK=jarvis.server
if ! "$VENV/bin/python" -c "import sys; sys.path.insert(0,'$APP'); import $CHECK" 2>>"$LOG"; then
  say "the new code does not import, rolling back to $BEFORE"
  note "failed the new code does not import, rolled back"
  git reset --hard --quiet "$BEFORE"
  exit 1
fi

# Nothing in the new code asks a model past the log that the usage and cost
# screens are added up from (`rouh/llmlog.py`, "Nothing asks a model past the
# log"): no call to a model outside the service that tracks usage and pricing.
# Only on a commit that has the check.
if [ -d rouh ] && grep -q "^def strays" rouh/llmlog.py 2>/dev/null; then
  if ! strays="$("$VENV/bin/python" -m rouh.llmlog 2>&1)"; then
    printf '%s\n' "$strays" >>"$LOG"
    said="$(printf '%s\n' "$strays" | head -n 1)"
    say "the new code asks a model past the usage log ($said), rolling back to $BEFORE"
    note "failed the new code asks a model past the usage log, rolled back: $said"
    git reset --hard --quiet "$BEFORE"
    exit 1
  fi
fi

# The database, before the restart, for a checkout that is a Django project
# (`manage.py predeploy`): made if this machine has none yet, migrated, the
# data moved out of SQLite the first time, and the owner's password delivered
# the first time - with the old service still serving until the one moment
# the data has to stop moving. If any of it fails, the old commit goes back and
# the old service is started again, whatever state this left it in.
if [ -f manage.py ]; then
  say "preparing the database"
  predeploy=("$VENV/bin/python" manage.py predeploy --service "$SERVICE" --systemctl "$SYSTEMCTL")
  if [ "$PREDEPLOY_AS" = "unit" ] && command -v systemd-run >/dev/null 2>&1; then
    # A transient unit with the service's own environment: its settings file
    # and every Environment= line its drop-ins add, so the data directory, the
    # encryption key and the public address are the ones the service uses.
    # systemd prints a value with a space in it quoted ("ROUH_STT_KEYTERMS=Claude
    # Code,..."), so the line is split the way a shell would read it, never on
    # every space: split on every space, a value with a space in it would be cut
    # in two and the deploy would fail.
    unit_env=()
    while IFS= read -r pair; do
      # And handed back quoted, because systemd-run reads Environment= as a
      # list of assignments separated by spaces.
      pair="${pair//\\/\\\\}"
      [ -n "$pair" ] && unit_env+=(-p "Environment=\"${pair//\"/\\\"}\"")
    done < <("$SYSTEMCTL" show -p Environment --value "$SERVICE" 2>/dev/null \
             | python3 -c 'import shlex, sys; print("\n".join(shlex.split(sys.stdin.read())))')
    predeploy=(systemd-run --quiet --wait --pipe --collect
               -p "EnvironmentFile=-$ENV_FILE" -p "WorkingDirectory=$APP"
               "${unit_env[@]}" "${predeploy[@]}")
  fi
  if ! "${predeploy[@]}" >>"$LOG" 2>&1; then
    said="$(tail -n 1 "$LOG" | sed -E 's/^CommandError: //')"
    say "the database step failed, rolling back to $BEFORE: $said"
    note "failed the new code's database step failed, rolled back: $said"
    git reset --hard --quiet "$BEFORE"
    "$SYSTEMCTL" restart "$SERVICE"
    exit 1
  fi
  say "the database is ready"
fi

say "restarting"
"$SYSTEMCTL" restart "$SERVICE"

ok=0
for i in $(seq 1 "$WAIT"); do
  sleep 1
  if curl -fsS --max-time 4 "$HEALTH" 2>/dev/null | grep -q '"ok": *true'; then ok=1; break; fi
done

if [ "$ok" = 1 ]; then
  say "healthy at $AFTER"
  exit 0
fi

say "unhealthy after ${WAIT}s, rolling back to $BEFORE"
# Written before the rollback restart, because that restart is the Rouh that
# reads it: it is the one that has to say the deploy failed rather than that it
# happened.
note "failed the new code was not healthy, rolled back"
git reset --hard --quiet "$BEFORE"
"$SYSTEMCTL" restart "$SERVICE"
for i in $(seq 1 "$WAIT"); do
  sleep 1
  if curl -fsS --max-time 4 "$HEALTH" 2>/dev/null | grep -q '"ok": *true'; then
    say "rolled back and healthy"; exit 1
  fi
done
say "ROLLED BACK AND STILL UNHEALTHY - needs a person"
exit 2
