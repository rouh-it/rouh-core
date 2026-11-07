#!/usr/bin/env bash
#
# Update both services on this machine, from one commit, in one run.
#
#   ./update-all.sh             put the one program and Rouh on origin/main
#   ./update-all.sh --to <ref>  put both on a particular commit or branch
#   ./update-all.sh --files-only   move both checkouts' files and restart nothing
#   ./update-all.sh --to <sha> --workspace <dir>
#                               move the live workspace, a repository of its
#                               own, onto <sha> of its own origin; nothing
#                               restarts, and neither service's checkout moves
#
# This is what a deploy is. There are two services in this one repository -
# the one program out of its checkout (ONE_APP_DIR), and Rouh out of its own
# (ROUH_APP_DIR) - and two update paths that never call each other can leave
# them on different commits, with nothing on any screen saying the two have
# come apart. One entry point is the fix: whatever starts a deploy starts this,
# and both services move.
#
# Three things it does that neither half could do on its own.
#
#   1. **One commit for both.** origin/main is resolved once, here, and handed
#      to each half. Two halves each fetching for themselves is two answers on
#      a busy afternoon, and two services on two different commits is the bug
#      this whole script exists to stop.
#   2. **The one program first, Rouh last.** Updating Rouh restarts the
#      process that is speaking, so anything left after it is not reached. By
#      the time Rouh goes, the other half has already finished and said how
#      it went.
#   3. **One sentence at the end, whatever happened.** A half that failed is
#      named, in the log and in the outcome file Rouh reads when it comes
#      back up, so a deploy where one service moved and the other did not can
#      never be reported as a deploy that worked.
#   4. **Files without a restart, for a commit that is only content.** Since
#      the assistant workspace was merged in at `workspace/`, this repository
#      holds the person's tasks, notes and pages as well as the code, and
#      Rouh serves those files off the checkout it is deployed in. So a
#      commit that moves only `workspace/` still has to reach the disk, and
#      must not restart anything: a paragraph typed at two in the morning is
#      not worth an outage, and a paragraph nobody can read is not worth
#      landing. `--files-only` is that: both checkouts are fast-forwarded and
#      neither service is touched, and it refuses outright if one single path
#      outside CONTENT_PATHS differs, because then the processes really do have
#      to move. `land.sh` decides which of the two it wants and says which it
#      chose; this refuses either way round rather than trusting it.
#      A workspace that is a repository of its own, beside the code rather
#      than inside it, is moved by its landings with
#      `--workspace` instead (`land.sh`, `move_workspace`): the same lock,
#      the same forced checkout, and no question of content against code,
#      because nothing in that repository is code.
#   5. **One deploy at a time.** An exclusive lock round the whole of it, taken
#      before anything is fetched and held until the last half has finished, so
#      two deploys started seconds apart queue instead of racing over the same
#      two checkouts. It waits rather than refusing: the second one is
#      somebody's work going live. `land.sh` deploys what it lands, so two
#      runs finishing together is an ordinary afternoon.
#
# Neither half is reimplemented here. `one/deploy/update.sh` is the one
# program's and `deploy/rouh.sh` is Rouh's, and both of them still do their
# own fetch, their own import check, their own restart and their own rollback.
# This is the order, the commit and the report.
#
# **This is the only deploy.** Running one half on its own moves one service
# and leaves the other on the commit before, with nothing saying so. So the
# halves are out of the way under names nobody types, and both refuse to run
# unless this script sets ROUH_DEPLOY_HALF. There is no wrong script to reach
# for.
#
# Everything it needs is a setting (deploy/installation.env.example lists them)
# with a default of its own, so an installation in other folders says where,
# and a check of your own can point it at two throwaway checkouts with
# stand-ins for systemctl and still run every line of it.
set -euo pipefail

#: The halves, read from beside this script, which is Rouh's copy of this
#: repository and never the one program's. The program's checkout is one of
#: the things being moved, and a script that rewrites itself half way through
#: runs half of one version and half of another.
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Every setting is read as ROUH_<name> and then as the JARVIS_<name> it was
# called before the rename: the server's `.env` and its systemd drop-ins still
# say the old one, and no deploy writes either of them. `rouh/config.py` and
# `deploy/rouh.sh` read both the same way. RENAME.md says why.
setting() {                       # setting NAME DEFAULT
  local new="$1" old="JARVIS_${1#ROUH_}" said
  said="${!new:-}"
  [ -n "$said" ] || said="${!old:-}"
  printf '%s' "${said:-$2}"
}

ROUH_HALF="$(setting ROUH_UPDATE_SCRIPT "$HERE/deploy/rouh.sh")"
ONE_HALF="$(setting ROUH_ONE_DEPLOY_SCRIPT "$HERE/one/deploy/update.sh")"

#: Rouh's own checkout. It is where the target commit is resolved, because
#: it is the checkout this script is deployed inside and the one whose remote
#: a deploy follows.
APP="$(setting ROUH_APP_DIR /var/www/rouh/app)"
LOG="$(setting ROUH_UPDATE_LOG /var/www/rouh/logs/update.log)"
#: One line for Rouh itself to read when it comes back up. The same file
#: `update.sh` writes, read by `rouh/self_update.py`, and the reason this
#: script writes it as well: a deploy where the one program failed and Rouh
#: succeeded would otherwise come back up looking like a deploy that worked.
OUTCOME="$(setting ROUH_UPDATE_OUTCOME "$(setting ROUH_DATA_DIR /var/www/rouh/data)/self-update-outcome")"

#: The one program's own checkout, which `one/deploy/update.sh` moves for
#: itself on an ordinary deploy and which is moved here on a content one.
ONE_APP="${ONE_APP_DIR:-/srv/one/app}"

#: What in this repository is content rather than code: nothing under it is
#: imported or run by either service, so moving a checkout across it changes no
#: behaviour and is not worth a restart. The same list `land.sh` keeps, said
#: again here because `--files-only` refuses on its own rather than trusting
#: its caller.
#: Blank is the workspace's folder, when Rouh's checkout still holds one.
CONTENT_PATHS="$(setting ROUH_CONTENT_PATHS "")"
if [ -z "$CONTENT_PATHS" ] && [ -f "$APP/workspace/_migration-map.json" ]; then
  CONTENT_PATHS="workspace/"
fi

WANT=""
FILES_ONLY=""
WORKSPACE=""

while [ $# -gt 0 ]; do
  case "$1" in
    --to) WANT="$2"; shift ;;
    --files-only) FILES_ONLY=1 ;;
    --workspace) WORKSPACE="$2"; shift ;;
    *) echo "unknown flag: $1" >&2; exit 2 ;;
  esac
  shift
done

mkdir -p "$(dirname "$LOG")" 2>/dev/null || true
say() { echo "[$(date -Is)] both: $*" | tee -a "$LOG"; }
# Never fatal: a data directory that cannot be written is no reason to abandon
# a deploy, and this script runs under set -e.
note() {
  mkdir -p "$(dirname "$OUTCOME")" 2>/dev/null || true
  printf '%s\n' "$*" > "$OUTCOME" 2>/dev/null || true
}
# Every line of the one program's output into the log, named, so one log read
# in order says which service said what. Its half prints and does not write to
# a log of its own; Rouh's writes to this one itself.
echoed() { while IFS= read -r line; do say "  $1: $line"; done; }
# The last thing a half said, which is what it said went wrong. Both halves
# end every failing path with one plain sentence, and `update.sh` stamps its
# lines with the time, which is no use in a sentence read out loud.
last_sentence() {
  printf '%s\n' "$1" | grep -v '^[[:space:]]*$' | tail -n 1 \
    | sed -E 's/^\[[^]]*\] ?((rouh|jarvis): )?//'
}

stop() { say "$1"; note "failed $2"; exit 1; }

# --- one deploy at a time ---------------------------------------------------
#
# Every way of starting a deploy on this machine ends up here: `deploy_myself`,
# the deploy that follows a landed change, `land.sh`'s own last step, and a
# person running this by hand. None of them knew about the others, and two of
# them at once is two git fetches, two fast-forwards and two systemctl calls
# over the same two checkouts. `land.sh` deploys what it lands, so two runs
# finishing seconds apart is exactly the ordinary afternoon that would race.
#
# So the lock lives here rather than in any one caller: a lock only one of them
# took would not be a lock. It waits rather than refusing, because the second
# deploy is somebody's work going live and a refusal would leave it on main
# unserved, which is the whole thing this is for.
#
# The file is in the same directory as the landing lock, for the same reason
# that one is there: the users that deploy - the one Rouh runs as, and the one
# every run of the one program runs as - may share nothing else they can both
# open. It is opened for reading, which is all flock needs, and which is the
# only way a world-writable sticky directory lets one of those users open the
# other's file on a kernel with `fs.protected_regular` on.
DEPLOY_LOCK_DIR="$(setting ROUH_LAND_DIR /srv/rouh-land)"
DEPLOY_LOCK="$(setting ROUH_DEPLOY_LOCK "$DEPLOY_LOCK_DIR/deploy.lock")"
DEPLOY_LOCK_WAIT="$(setting ROUH_DEPLOY_LOCK_WAIT 300)"

if mkdir -p "$DEPLOY_LOCK_DIR" 2>/dev/null; then
  chmod 1777 "$DEPLOY_LOCK_DIR" 2>/dev/null || true
  [ -e "$DEPLOY_LOCK" ] || ( umask 000; : >"$DEPLOY_LOCK" ) 2>/dev/null || true
  chmod 666 "$DEPLOY_LOCK" 2>/dev/null || true
fi
if [ -r "$DEPLOY_LOCK" ] && exec 8<"$DEPLOY_LOCK"; then
  if flock -w "$DEPLOY_LOCK_WAIT" 8; then
    say "holding the deploy lock"
  else
    say "another deploy held the lock for more than ${DEPLOY_LOCK_WAIT}s, so this one did not start"
    note "failed another deploy was already running and had not finished, so neither service was updated"
    exit 1
  fi
else
  # Never a reason to refuse to deploy: a machine that cannot keep a lock file
  # is still a machine whose services have to move.
  say "could not open $DEPLOY_LOCK, so this deploy is not holding the deploy lock"
fi

# --- the live workspace, a repository of its own ------------------------------
#
# Its own repository, its own origin and its own commit, so nothing below this
# applies to it: no half is started, Rouh's checkout is not fetched, and the
# commit is resolved in the workspace. Untracked files are left alone, the way
# they are on a deploy, which keeps a folder Rouh made and has not saved yet.
if [ -n "$WORKSPACE" ]; then
  [ -n "$WANT" ] || { say "--workspace needs --to <commit>"; exit 2; }
  wg=(git -c "safe.directory=$WORKSPACE" -C "$WORKSPACE")
  if [ "$("${wg[@]}" rev-parse --show-toplevel 2>/dev/null)" != "$(cd "$WORKSPACE" 2>/dev/null && pwd -P)" ]; then
    say "$WORKSPACE is not a repository of its own, so the workspace was not moved"
    exit 1
  fi
  if ! out="$("${wg[@]}" fetch --quiet origin 2>&1)"; then
    printf '%s\n' "$out" | echoed workspace
    say "git fetch origin failed in $WORKSPACE, so the workspace was not moved"
    exit 1
  fi
  if ! "${wg[@]}" rev-parse --verify -q "${WANT}^{commit}" >/dev/null 2>&1; then
    say "$WORKSPACE has no commit ${WANT:0:7}, even after fetching, so it was not moved"
    exit 1
  fi
  if [ "$("${wg[@]}" rev-parse HEAD 2>/dev/null)" = "$("${wg[@]}" rev-parse "${WANT}^{commit}")" ]; then
    say "the workspace is already at ${WANT:0:7}"
    exit 0
  fi
  # On its branch, so the live workspace says what it is a copy of; it never
  # commits for itself (Rouh's saves are made in a checkout of their own).
  if ! out="$("${wg[@]}" checkout --quiet --force -B main "$WANT" 2>&1)"; then
    printf '%s\n' "$out" | echoed workspace
    say "the workspace at $WORKSPACE could not be moved to ${WANT:0:7}"
    exit 1
  fi
  "${wg[@]}" branch --quiet --set-upstream-to=origin/main main >/dev/null 2>&1 || true
  say "the workspace at $WORKSPACE holds ${WANT:0:7}, nothing restarted"
  exit 0
fi

[ -d "$APP/.git" ] \
  || stop "there is no git checkout of Rouh at $APP, so nothing was deployed" \
          "there is no checkout of Rouh at $APP, so neither service was updated"
# Before either half is started, not between them: a deploy that has moved one
# service and cannot even find the script for the other is the worst place to
# stop. A file move starts neither half, so it does not need either of them.
if [ -z "$FILES_ONLY" ]; then
  for half in "$ONE_HALF" "$ROUH_HALF"; do
    [ -f "$half" ] \
      || stop "there is no update script at $half, so nothing was deployed" \
              "there is no update script at $half, so neither service was updated"
  done
fi

# --- the commit both halves are going to, resolved once ---------------------

# Rouh can be running as root out of a checkout owned by another user, and
# git refuses to answer at all about a repository it thinks belongs to
# somebody else unless the path is named as expected.
git_() { git -c "safe.directory=$APP" -C "$APP" "$@"; }

cd "$APP"
if ! fetched="$(git_ fetch --quiet origin 2>&1)"; then
  say "git fetch origin failed in $APP, so nothing was deployed"
  say "  remote: $(git_ remote get-url origin 2>/dev/null || echo 'unknown')"
  printf '%s\n' "$fetched" | echoed git
  note "failed could not fetch from origin, so neither service was updated"
  exit 1
fi

# `origin/<ref>` before `<ref>`, because "--to main" means the main that was
# just fetched and not whatever the local branch happens to be standing on.
REF="${WANT:-main}"
TARGET=""
for candidate in "origin/$REF" "$REF"; do
  if TARGET="$(git_ rev-parse --verify --quiet "${candidate}^{commit}")"; then break; fi
done
if [ -z "$TARGET" ]; then
  say "there is no commit $REF in $APP, so nothing was deployed"
  note "failed there is no commit $REF here, so neither service was updated"
  exit 1
fi
SHORT="${TARGET:0:7}"

# Never backwards. `land.sh` asks whether its commit is live before it waits
# for the lock, so a landing that queued behind a newer one arrives asking for
# a commit Rouh has already gone past. Deploying it would put Rouh back onto the
# older build and restart it for nothing new (the one program would stay put,
# since its half only fast-forwards), and the next deploy would restart it
# again. A commit Rouh already holds is the newer commit's deploy, so both go
# to that one.
AT_NOW="$(git_ rev-parse HEAD)"
if [ "$AT_NOW" != "$TARGET" ] && git_ merge-base --is-ancestor "$TARGET" "$AT_NOW" 2>/dev/null; then
  say "Rouh is already at ${AT_NOW:0:7}, which holds $SHORT, so nothing goes back to it"
  TARGET="$AT_NOW"
  SHORT="${TARGET:0:7}"
fi
say "both services are going to $SHORT"

# --- files only: move the checkouts, restart nothing -------------------------

#: Whether one path is content rather than code.
is_content() {
  local path="$1" prefix
  for prefix in $CONTENT_PATHS; do
    [ -n "$prefix" ] || continue
    case "$path" in "$prefix"*) return 0 ;; esac
  done
  return 1
}

# One checkout's files onto $3, with nothing restarted. Refuses, and says why,
# the moment a single path outside CONTENT_PATHS differs: moving code under a
# running process without restarting it is the one thing worse than a restart.
move_files() {
  local dir="$1" name="$2" want="$3" at path out
  if [ ! -d "$dir/.git" ]; then
    say "$name has no checkout at $dir, so nothing of its was moved"
    return 1
  fi
  # Rouh can be running as root out of a checkout owned by another user, and
  # git refuses to answer about a repository it thinks belongs to somebody else
  # unless the path is named as expected. The same line the rest of this script
  # uses for $APP.
  local -a g=(git -c "safe.directory=$dir" -C "$dir")
  if ! out="$("${g[@]}" fetch --quiet origin 2>&1)"; then
    say "$name: git fetch origin failed in $dir"
    printf '%s\n' "$out" | echoed "$name"
    return 1
  fi
  if ! "${g[@]}" rev-parse --verify -q "${want}^{commit}" >/dev/null 2>&1; then
    say "$name: $dir has no commit ${want:0:7}, even after fetching"
    return 1
  fi
  at="$("${g[@]}" rev-parse HEAD)"
  if [ "$at" = "$want" ]; then
    say "$name is already at ${want:0:7}"
    return 0
  fi
  # Both sides of a rename, or a file moved out of the code into workspace/
  # would be named only by where it went, and pass for content.
  while IFS= read -r path; do
    [ -n "$path" ] || continue
    if ! is_content "$path"; then
      say "$name: $path is code, not content, so this is a deploy and not a file move"
      return 1
    fi
  done < <("${g[@]}" diff --no-renames --name-only "$at" "$want" 2>/dev/null)
  # --force, the way the ordinary deploy does it: a tracked file the running
  # service wrote into the checkout is a view of a database row and is written
  # again when it is next read, and a half-moved checkout is worse than a lost
  # copy of one. Untracked files are left alone by both, which is what keeps a
  # step filed into a task and not yet committed.
  if ! out="$("${g[@]}" checkout --quiet --force "$want" 2>&1)"; then
    printf '%s\n' "$out" | echoed "$name"
    say "$name: the checkout at $dir could not be moved to ${want:0:7}"
    return 1
  fi
  say "$name: files moved to ${want:0:7}, nothing restarted"
  return 0
}

if [ -n "$FILES_ONLY" ]; then
  FAILED=""
  move_files "$ONE_APP" "the one program" "$TARGET" || FAILED="the one program"
  move_files "$APP" "Rouh" "$TARGET" || FAILED="${FAILED:+$FAILED and }Rouh"
  if [ -n "$FAILED" ]; then
    say "the files of $FAILED were not moved to $SHORT"
    note "failed $FAILED could not be moved to $SHORT without a restart"
    exit 1
  fi
  say "both checkouts hold $SHORT and neither service was restarted"
  exit 0
fi

# The one directory both services land work through: `land.sh`'s lock and the
# conflict records beside it. Made here because the deploy runs as root and
# may be the only one that can write where it goes, and sticky and
# world-writable like /tmp because the users that land work - the one Rouh's
# own crew runs as, and the one every run of the one program runs as - need not
# share a group. A lock only one of them can open is not a lock, and without
# this each would fall back to its own /tmp and two jobs could land in the same
# second.
LAND_DIR="$(setting ROUH_LAND_DIR /srv/rouh-land)"
if mkdir -p "$LAND_DIR/conflicts" 2>/dev/null; then
  chmod 1777 "$LAND_DIR" "$LAND_DIR/conflicts" 2>/dev/null || true
  # The lock file itself, made by root: a kernel with `fs.protected_regular`
  # on refuses to open another user's file for writing inside a world-writable
  # sticky directory, so one made by either of those users would be
  # a lock only that user could take. land.sh opens it for reading.
  : >>"$LAND_DIR/land.lock" 2>/dev/null || true
  chmod 666 "$LAND_DIR/land.lock" 2>/dev/null || true
else
  say "could not make $LAND_DIR; land.sh will use a lock under /tmp instead"
fi

# --- the one program, first -------------------------------------------------

ONE_SAID=""
set +e
one_out="$(ONE_TARGET="$TARGET" ROUH_DEPLOY_HALF=update-all JARVIS_DEPLOY_HALF=update-all bash "$ONE_HALF" 2>&1)"
one_code=$?
set -e
printf '%s\n' "$one_out" | echoed one
if [ "$one_code" != 0 ]; then
  ONE_SAID="$(last_sentence "$one_out")"
  [ -n "$ONE_SAID" ] || ONE_SAID="It failed and said nothing (exit $one_code)."
  say "the one program was NOT updated: $ONE_SAID"
  # Written now rather than at the end. Rouh's half restarts Rouh, and the
  # Rouh that comes up reads this file to find out what became of the deploy
  # it announced; a line written after that restart arrives too late to be the
  # answer it reports.
  note "failed the one program was not updated: $ONE_SAID Rouh is being put on $SHORT anyway."
fi

# --- Rouh, last, because this is what takes the process away --------------

ROUH_SAID=""
AT="$(git_ rev-parse HEAD)"
if [ "$AT" = "$TARGET" ]; then
  # Pressing deploy twice, or deploying after somebody else already has, is
  # allowed to mean the same as doing it once.
  say "Rouh is already at $SHORT, nothing to do"
else
  say "Rouh now, onto $SHORT; this restarts the server"
  # Never under a chat answer (Petar, 3 November 2026): Rouh says when the answers in progress
  # are over, holding new turns back after a short grace period, and this waits for that, ten
  # minutes at most (guard/rouh_guard/deploywait.py, rouh/answers_now.py). Never stops the deploy.
  if command -v python3 >/dev/null 2>&1 && [ -f "$HERE/guard/bin/rouh-deploy-wait" ]; then
    python3 -I "$HERE/guard/bin/rouh-deploy-wait" --who rouh --why "update-all.sh onto $SHORT" \
      --dir "$(setting ROUH_DATA_DIR /var/www/rouh/data)/deploy-wait" 2>&1 | echoed rouh || true
  fi
  set +e
  rouh_out="$(ROUH_DEPLOY_HALF=update-all JARVIS_DEPLOY_HALF=update-all bash "$ROUH_HALF" --to "$TARGET" 2>&1)"
  rouh_code=$?
  set -e
  # Not echoed the way the one program's is: Rouh's half writes every line
  # of its own into this same log as it goes, so echoing the copy would print
  # the whole deploy twice, each line under two timestamps.
  if [ "$rouh_code" != 0 ]; then
    ROUH_SAID="$(last_sentence "$rouh_out")"
    [ -n "$ROUH_SAID" ] || ROUH_SAID="It failed and said nothing (exit $rouh_code)."
    say "Rouh was NOT updated: $ROUH_SAID"
  fi
fi

# --- what happened, in one sentence -----------------------------------------

if [ -n "$ONE_SAID" ] && [ -n "$ROUH_SAID" ]; then
  note "failed neither service was updated. The one program: $ONE_SAID Rouh: $ROUH_SAID"
  say "neither service was updated"
  exit 1
fi
if [ -n "$ONE_SAID" ]; then
  note "failed Rouh is on $SHORT, but the one program was not updated: $ONE_SAID"
  say "Rouh is on $SHORT and the one program is not"
  exit 1
fi
if [ -n "$ROUH_SAID" ]; then
  note "failed the one program is on $SHORT, but Rouh was not: $ROUH_SAID"
  say "the one program is on $SHORT and Rouh is not"
  exit 1
fi
note "done the one program and Rouh are both on $SHORT"
say "the one program and Rouh are both on $SHORT"
