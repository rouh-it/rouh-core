#!/usr/bin/env bash
#
# land.sh - the one way work reaches main, and the only thing allowed to push.
#
# Several jobs finishing at once is ordinary, and without care each of them
# can finish good work and push none of it: work already on main from an
# earlier attempt collides with itself, and work that touched the same files as
# a run that landed meanwhile collides with that. Each of those is recoverable,
# and this is the ladder that recovers them, in order:
#
#   0  Nothing to replay. The target is already an ancestor of this branch:
#                        nobody landed anything while the job worked, so the
#                        work sits on the target and a push is a fast-forward.
#                        Rewriting every commit to put it where it already is
#                        is waste, and on a branch holding a merge it is worse
#                        than waste: a rebase flattens, and a flattened merge
#                        collides with itself.
#   1  Already landed?   Compared by patch, not by text: git cherry and
#                        patch-id against the remote's main. Work that is
#                        already there drops its duplicate and reports success.
#                        A retried job that already landed needs only this.
#   2  One at a time.    An exclusive lock round the whole fetch, rebase, check
#                        and push, so two jobs never land at the same moment
#                        and the second rebases onto a main that has stopped
#                        moving. Released on every exit path, failure included.
#   3  Rebase with memory. rerere on, diff3 conflict style, autostash, written
#                        into the repository's own config, so a conflict
#                        resolved once resolves itself the next time. These runs
#                        retry the same work, so that is not a nicety.
#   4  Real conflict.    Handed back to the worker that wrote the code, which
#                        still holds its own context and its own worktree. The
#                        run does not end. It is given both sides and told to
#                        reconcile the intent rather than the text, and it must
#                        pass its live browser proof again before it may push.
#   5  Worker gone.      Redo rather than untangle: a fresh job from the
#                        current main with the old message, the old diff and
#                        what landed in the meantime. Rouh starts that; this
#                        script writes the record it is started from.
#   6  Twice failed, or both sides rewrote the same thing: ROUH MERGES IT.
#                        Rouh resolves merge clashes itself and the person
#                        is not asked. The rebase is stopped at the
#                        collision and Rouh's merge pass (rouh/merge_pass.py),
#                        one Claude Code pass given both diffs, both sides'
#                        commit messages and the run's brief, writes the
#                        version that keeps both intents. It is checked - no
#                        marker left, every file it wrote still parses - and
#                        then the usual checks before every push prove it and
#                        it lands like any other work. --merge goes straight
#                        to this rung.
#   7  Opposite intents. When the merge pass finds that the two sides truly
#                        want opposite things - one deletes or reverses what
#                        the other adds, and both cannot hold - Rouh settles
#                        that too: it takes the side its merge pass
#                        recommends, and the landing's last sentence, which is
#                        the job's report, says what it kept and why. Only
#                        when the side it would drop holds words the person
#                        wrote themselves - a commit of Rouh's saver, which
#                        carries their own edits in place to main - does this
#                        stop and ask them, with one JSON record
#                        holding both diffs, both commit messages, the
#                        conflicting files, the name of the pre-resolution
#                        branch, the question in one line, Rouh's
#                        recommendation and `needs_person` "his_words".
#
# Three things are never a question for anybody, whichever rung is reached:
#
#   - Notes kept by adding to them, such as a shared.md (ROUH_UNION_PATHS).
#     Where they collide both sides are kept, one after the other, with git's
#     union merge, before anything else is tried.
#
#   - A generated file. The workspace task list, workspace/_tasks.md, is made
#     out of Rouh's database ("Rouh saves the task list, made again out of the
#     database") and nobody writes it. Where it collides it is taken as the
#     target has it, and Rouh's saver writes it again from the database on its
#     next pass (rouh/saving.py). ROUH_GENERATED_PATHS names them.
#   - A replay that stops without a single colliding file. That is git failing
#     for some other reason, and it is reported as an error with git's own
#     words. A rebase with no committer name once stopped this way and was
#     put to the person as a "clash"; a committer is now always given (the
#     author of the work).

# And before every push, whichever rung got there: one number, one task. A
# landing that would put a task number or an object id on a second folder under
# workspace/ is refused with exit 1, `duplicate: true`, and the sentence naming
# both folders and the next free number (`rouh/numbering.py`).
#
# Nothing is ever discarded. Before any resolution the work exactly as the job
# wrote it is put on a branch of its own, land/pre/<run>/<attempt>, and that
# branch is never deleted, so every attempt is recoverable with one checkout.
#
# LANDING INCLUDES DEPLOYING, and that is the seventh rung.
#
# A push that is left for something else to deploy can sit on main for hours
# while the machine goes on serving the commit before it: the work is correct,
# nothing on the screen changes, and nobody can tell it landed. A change is done
# when it is committed, merged to main AND deployed, so the deploy is this
# script's own last step:
#
#   7  Deploy, and check. After the push succeeds this runs the same deploy
#      `deploy_myself` runs - update-all.sh out of Rouh's own checkout, the
#      one program first and Rouh second - detached, so the restart cannot
#      kill the job that started it, and then waits for both services to
#      answer their health pages with the commit that was just pushed. Only
#      then is it a success. A deploy that fails or rolls back is a failure of
#      the landing, not a success with a note, and the JSON says so.
#
# One deploy happens at a time: update-all.sh takes an exclusive lock of its
# own, which every way of starting a deploy goes through, so a landing waits
# for a deploy already in flight rather than racing it.
#
# AND THE ONE REASON NOT TO DEPLOY, which is rung 7a.
#
# Since the assistant workspace was merged in at workspace/, this repository
# holds content as well as code: notes, task folders and built pages that the
# server's jobs write into all day. Neither service imports or runs any
# of it. Deploying on a paragraph would restart both of them for something no
# process would read differently, all night. So before the deploy, each service
# is asked what it is serving, and what differs between that and the commit
# just pushed is looked at: content only, and both checkouts are moved onto it
# with nothing restarted; one path outside CONTENT_PATHS, and it is an ordinary
# code deploy. The files always move, because Rouh serves what is under
# workspace/ off its own checkout on every request. It fails safe every way it
# can, and says out loud which way it decided. The section headed
# "Step 7a: the content guard" is the whole of the rule.
#
# What it prints: human lines on stderr, and one JSON object as the last line of
# stdout, always, whatever happened. Callers read the JSON. Three of its fields
# are the whole of what happened to the work, and the last line always says
# which of them it was, in words a person can read out loud:
#
#   landed: true,  deployed: true    pushed to main and deployed, naming the commit
#   landed: true,  deployed: false   pushed to main and NOT live, with the reason
#   landed: false                    nothing was pushed
#
# `deploy` says which of those it was in one word, and `content` is the one
# worth knowing about: the commit moved only content, so both checkouts were
# moved onto it and neither service was restarted, and it is live because the
# files are what is read.
#
# Exit codes, which are the interface:
#
#   0   landed and deployed, already on main and live, or nothing to land
#   10  a real conflict, handed back to the worker; `handback` in the JSON is
#       what to tell it, and the record is written
#   11  it needs the person: the two sides want opposite things. The record is
#       written, `conflict` names it, and `recommend` is Rouh's pick
#   12  the person parked it; nothing moved and nothing was lost
#   13  it is on main and it is not live: the deploy failed, rolled back, or
#       could not be started. `deploy_reason` says which
#   1   something else went wrong, with `reason` saying what
#
# Usage:
#
#   ./land.sh                            land this checkout's work on main
#   ./land.sh --run 08bba92a             say which job it is, for the record
#   ./land.sh --answer 1                 carry out the person's pick
#   ./land.sh --answer 1 --no-push       replay it and stop, so the worker can
#                                        prove the result in a browser first
#   ./land.sh --path ../other-checkout   land a checkout somewhere else
#   ./land.sh --from <sha>               say what the branch was made from, so work
#                                        whose own commit is already on main is
#                                        reported as landed rather than as nothing
#   ./land.sh --merge                    on a collision, go straight to Rouh's
#                                        own merge pass (rung 6)
#   ./land.sh --no-deploy                push and stop there, for a machine that
#                                        serves nothing. It says it is not live.
#   ./land.sh --deploy-wait 420          how long the deploy gets to come up
#
#   ROUH_CONTENT_PATHS='docs/'           what counts as content rather than
#                                        code, space separated. Everything else
#                                        is code and deploys. Blank is the
#                                        workspace's folder, when the repository
#                                        being landed holds one as a folder
#   ROUH_GENERATED_PATHS='_tasks.md'     files made by a program, taken as
#                                        the target has them where they collide
#   ROUH_WORKSPACE=<dir>                 the live workspace, which a landing
#                                        of the workspace's own repository moves
#                                        onto what it pushed
#   ROUH_MERGE_PASS=0                    never run Rouh's merge pass: a collision
#                                        that reaches rung 6 goes back to the
#                                        worker instead
#   ROUH_LAND_FIT_ONLY=1                 fit the work onto the target and push
#                                        it only to that target, with none of
#                                        the checks before a push: the protected
#                                        core checks it next. How a run in the
#                                        containers fits its work onto the code
#                                        that runs before proposing it, with a
#                                        scratch repository as the target
#                                        (bin/rouh-land, CONTAINERS.md
#                                        creator.merge-runs)
#
# Two kinds of repository are landed here, and it tells them apart by what is
# at the top of the branch. Rouh's code is deployed: both services onto the
# commit, as below. The person's workspace, a repository of its own with
# `_migration-map.json` at its top, runs nothing, so its
# landing is the same ladder with a different last step: the live workspace is
# moved onto the commit and nothing is restarted (`move_workspace`).
#
# There is no test step here and that is deliberate: this repository has no
# committed tests and no suite to run, and the proof of a change is the worker's
# own, driven in a real browser before it calls this. --check <command> is for a
# repository that does have one command worth running under the lock.

# Not -e. git says no as a matter of course here - a rebase that conflicts, a
# push that is refused, a ref that is not there - and every one of those noes is
# read and handled. -e would turn the ones this script exists to handle into a
# silent exit with no JSON and no record.
set -uo pipefail

# In the containers every Rouh instance runs, a run is in the worker, which may write neither the
# workspace's main nor Rouh's code: its work is handed to the core, or to the protected core, by
# bin/rouh-land, which takes these same arguments and answers in the same shape. So `./land.sh`
# from a run there, which every brief says, does that (ROUH_LAND_THROUGH, deploy/stack/compose.yml).
if [ -n "${ROUH_LAND_THROUGH:-}" ] && [ -x "${ROUH_LAND_THROUGH}" ] && [ "${ROUH_LAND_FIT_ONLY:-0}" != "1" ]; then
  exec "$ROUH_LAND_THROUGH" "$@"
fi

SELF_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)

REPO=""
TARGET="main"
REMOTE="origin"
RUN=""
TITLE=""
# Every setting is read as ROUH_<name> and then as the JARVIS_<name> it was
# called before the rename: the server's `.env` and its systemd drop-ins still
# say the old one, and no deploy writes either of them. `rouh/config.py`,
# `update-all.sh` and `deploy/rouh.sh` read both the same way. RENAME.md says why.
setting() {                       # setting NAME DEFAULT
  local new="$1" old="JARVIS_${1#ROUH_}" said
  said="${!new:-}"
  [ -n "$said" ] || said="${!old:-}"
  printf '%s' "${said:-$2}"
}

LAND_DIR="$(setting ROUH_LAND_DIR /srv/rouh-land)"
BESIDE=""
WAIT="900"
ANSWER=""
CONFLICT=""
CHECK=""
AUTOSTASH="0"
NO_PUSH="0"
QUIET="0"
BRIEF=""
FROM=""
#: Straight to Rouh's own merge pass on a collision, whatever the attempt.
MERGE="0"
#: Whether Rouh's merge pass may run at all. Off, rung 6 hands back instead.
MERGE_PASS="$(setting ROUH_MERGE_PASS 1)"
#: Files a program makes, never anybody: taken as the target has them where
#: they collide, and made again by whatever makes them. Space separated, each a
#: path in the repository or a shell pattern.
GENERATED_PATHS="$(setting ROUH_GENERATED_PATHS _tasks.md)"
#: Files that are notes kept by adding to them, where both sides are kept, one
#: after the other, wherever they collide (git's union merge), because notes
#: kept by adding to them lose nothing by keeping both. Space separated shell
#: patterns.
UNION_PATHS="$(setting ROUH_UNION_PATHS '*shared.md *shared-notes.md *quest-notebook.md *.log')"

# --------------------------------------------------------------------------
# The deploy, which is the other half of landing
#
# Everything here is an environment variable with the server's own value as its
# default, so a check of your own can point the whole of it at two throwaway
# health pages and a stand-in deploy script and still run every line.
# --------------------------------------------------------------------------

#: Whether a successful push is followed by a deploy. --no-deploy turns it off,
#: and then the answer says plainly that the work is on main and not live.
DEPLOY="1"
#: Rouh's own checkout, which is where the deploy script is read from. The
#: one program's checkout is one of the two things a deploy moves, so the
#: script is never taken from there.
DEPLOY_APP="$(setting ROUH_APP_DIR /var/www/rouh/app)"
#: The deploy itself: both services, one commit, the one program first. The
#: same script `deploy_myself` runs (rouh/one_deploy.py).
DEPLOY_SCRIPT="$(setting ROUH_DEPLOY_SCRIPT "")"
#: The branch this machine serves. Landing anything else is landing, and is
#: never a reason to move a live service onto it.
DEPLOY_BRANCH="$(setting ROUH_DEPLOY_BRANCH main)"
#: How long the two services get to come up answering with the new commit. A
#: restart and a health check is twenty seconds each on a good day, a pip run
#: for changed requirements is the only slow step, and a deploy already in
#: flight has to finish before this one starts.
DEPLOY_WAIT="$(setting ROUH_DEPLOY_WAIT 420)"
#: Once the script has exited saying it worked, how much longer a service gets
#: to be answering with the new commit before this calls it a failure.
DEPLOY_SETTLE="$(setting ROUH_DEPLOY_SETTLE 30)"
#: The two health pages, and the field in each that names the commit it is
#: serving. These are the only thing this script believes: a deploy script
#: that exits 0 is a claim, and a service answering with the commit is not.
ROUH_HEALTH="${ROUH_HEALTH_URL-${JARVIS_HEALTH_URL-http://127.0.0.1:8021/healthz}}"
ONE_HEALTH="${ONE_HEALTH_URL-http://127.0.0.1:8031/one/healthz}"
#: The paths in this repository that are content and not code, space separated.
#: Everything under them is something a person or one of the server's jobs wrote
#: down; nothing under them is imported or run by either service, so moving the
#: serving checkout across them changes no behaviour and is not worth a
#: restart. The files still move. Anything not listed here is code. See
#: `only_content` and `move_content`.
CONTENT_PATHS="$(setting ROUH_CONTENT_PATHS "")"
#: The workspace Rouh serves, when it is a repository of its own: what a landing
#: of that repository moves onto the commit it pushed. The same setting Rouh
#: reads (`rouh/config.py`), by either of its names.
LIVE_WORKSPACE="$(setting ROUH_WORKSPACE "$(setting ROUH_ASSISTANT_REPO /var/www/rouh/workspace)")"

usage() { sed -n '3,/^# There is no test step/p' "${BASH_SOURCE[0]}" | sed '$d' >&2; exit 2; }

while [ "$#" -gt 0 ]; do
  case "$1" in
    --path)       REPO="${2:-}"; shift 2 ;;
    --target)     TARGET="${2:-}"; shift 2 ;;
    --remote)     REMOTE="${2:-}"; shift 2 ;;
    --run)        RUN="${2:-}"; shift 2 ;;
    --title)      TITLE="${2:-}"; shift 2 ;;
    --land-dir)   LAND_DIR="${2:-}"; shift 2 ;;
    --beside)     BESIDE="${2:-}"; shift 2 ;;
    --wait)       WAIT="${2:-}"; shift 2 ;;
    --answer)     ANSWER="${2:-}"; shift 2 ;;
    --conflict)   CONFLICT="${2:-}"; shift 2 ;;
    --check)      CHECK="${2:-}"; shift 2 ;;
    --brief)      BRIEF="${2:-}"; shift 2 ;;
    --from)       FROM="${2:-}"; shift 2 ;;
    --autostash)  AUTOSTASH="1"; shift ;;
    --merge)      MERGE="1"; shift ;;
    --no-push)    NO_PUSH="1"; shift ;;
    --no-deploy)  DEPLOY="0"; shift ;;
    --deploy-wait) DEPLOY_WAIT="${2:-}"; shift 2 ;;
    --deploy-script) DEPLOY_SCRIPT="${2:-}"; shift 2 ;;
    --quiet)      QUIET="1"; shift ;;
    -h|--help)    usage ;;
    *)            echo "land.sh: I do not know the option $1" >&2; usage ;;
  esac
done

REPO="${REPO:-$PWD}"

say() { [ "$QUIET" = "1" ] || printf 'land.sh: %s\n' "$*" >&2; }

# Everything temporary this run made, thrown away however it ends.
SCRATCH=""
cleanup() { [ -n "$SCRATCH" ] && rm -rf -- "$SCRATCH"; }
trap cleanup EXIT
SCRATCH=$(mktemp -d 2>/dev/null) || SCRATCH=""
tmpfile() { printf '%s/%s' "$SCRATCH" "$1"; }

# --------------------------------------------------------------------------
# Talking to git, and to the module that words the question
# --------------------------------------------------------------------------

g() { git -C "$REPO" "$@"; }
gq() { git -C "$REPO" "$@" 2>/dev/null; }

# rouh/conflicts.py holds the wording of the question, the four choices and
# what a worker is told. It is beside this script, imports nothing but the
# standard library, and is reached by this script's own location, so landing a
# checkout of any other repository still gets the same words.
PY=""
for candidate in python3 python3.12 python3.11; do
  if command -v "$candidate" >/dev/null 2>&1; then PY="$candidate"; break; fi
done

conflicts() {
  [ -n "$PY" ] || return 127
  PYTHONPATH="$SELF_DIR${PYTHONPATH:+:$PYTHONPATH}" \
    ROUH_LAND_DIR="$LAND_DIR" "$PY" -m rouh.conflicts "$@"
}

# One JSON object, always, as the last line of stdout. Built by python so that a
# reason holding a quote, a newline or a stray backslash cannot make the answer
# unreadable, which is exactly the kind of thing git's own words are full of.
# A value of `@<path>` is read from that file as text, `lines@<path>` is that
# file as an array of its non-blank lines, `json:<text>` is already JSON, and
# `true`, `false` and a plain number arrive as themselves rather than as
# strings, because every caller reads `landed` as a boolean.
#
# **A long value goes in by path and never on the command line.** Linux caps a
# single argument at 128 KiB, and a landing that moves a few thousand files
# builds a `files=json:[...]` argument larger than that: python is never
# started, `finish` prints nothing, and a landing that really pushed and really
# deployed ends with "Argument list too long" and no answer at all for whatever
# was reading one. That is what `lines@` is for, and
# it is why the list is handed over as a path rather than as a string.
finish() {
  local code="$1"; shift
  if [ -n "$PY" ]; then
    "$PY" - "$@" <<'PYEOF'
import json, sys
out = {}
for pair in sys.argv[1:]:
    key, _, value = pair.partition("=")
    if value.startswith("@"):
        try:
            with open(value[1:], encoding="utf-8", errors="replace") as fh:
                out[key] = fh.read()
        except OSError:
            out[key] = ""
        continue
    if value.startswith("lines@"):
        try:
            with open(value[6:], encoding="utf-8", errors="replace") as fh:
                out[key] = [line.rstrip("\n") for line in fh if line.strip()]
        except OSError:
            out[key] = []
        continue
    if value.startswith("json:"):
        try:
            out[key] = json.loads(value[5:])
            continue
        except ValueError:
            out[key] = value[5:]
            continue
    if value in ("true", "false"):
        out[key] = value == "true"
    elif value.lstrip("-").isdigit():
        out[key] = int(value)
    else:
        out[key] = value
print(json.dumps(out))
PYEOF
  else
    printf '{"state": "error", "landed": false, "reason": "no python3 here to answer with"}\n'
  fi
  exit "$code"
}

fail() { say "$1"; finish 1 state=error landed=false "reason=$1"; }

# --------------------------------------------------------------------------
# The checkout
# --------------------------------------------------------------------------

[ -d "$REPO" ] || fail "there is no directory $REPO"
gq rev-parse --git-dir >/dev/null || fail "$REPO is not a git checkout"

BRANCH=$(gq symbolic-ref --short HEAD || true)
[ -n "$BRANCH" ] || fail "this checkout is not on a branch, so there is nothing to land"
[ "$BRANCH" != "$TARGET" ] || fail "this checkout is on $TARGET itself; a job works on a branch of its own"

# A rebase somebody else began is never touched: aborting a rebase this script
# did not start is exactly the kind of tidying that loses an afternoon's work.
GITDIR=$(gq rev-parse --absolute-git-dir)
if [ -d "$GITDIR/rebase-merge" ] || [ -d "$GITDIR/rebase-apply" ]; then
  fail "a rebase is already in progress in $REPO. Finish it or abort it, then run this again"
fi

# Who this landing is for: the id the caller gave, otherwise the one already on
# the end of the branch name (rouh/... and one/... branches both end with it),
# otherwise the folder's name.
if [ -z "$RUN" ]; then
  RUN=$(printf '%s' "$BRANCH" | sed -n 's/.*-\([0-9a-f]\{6,\}\)$/\1/p')
fi
[ -n "$RUN" ] || RUN=$(basename -- "$REPO")
RUN=$(printf '%s' "$RUN" | tr -c 'A-Za-z0-9._-' '-' | cut -c1-40)
[ -n "$TITLE" ] || TITLE="$RUN"

# Where the record goes beside the run: the run's own folder when it has one.
if [ -z "$BESIDE" ]; then
  if [ -d "$REPO/.one" ]; then BESIDE="$REPO/.one"
  elif [ -d "$REPO/.rouh" ]; then BESIDE="$REPO/.rouh"
  fi
fi

TARGET_REF="$REMOTE/$TARGET"

# What is being landed: Rouh's code, which deploys, or a workspace, which is
# the person's own tree and runs nothing. A workspace has its map at its top.
KIND="code"
gq cat-file -e "HEAD:_migration-map.json" && KIND="workspace"
# A repository that still holds the workspace as a folder of its own - as
# Rouh's code repository once did - counts that folder as content,
# and the folder is wherever the map is. Said for this landing, so a setting
# that names other content still wins.
if [ -z "$CONTENT_PATHS" ] && [ "$KIND" = "code" ]; then
  for candidate in workspace; do
    gq cat-file -e "HEAD:$candidate/_migration-map.json" && CONTENT_PATHS="$candidate/"
  done
  [ -n "$CONTENT_PATHS" ] && GENERATED_PATHS="$GENERATED_PATHS ${CONTENT_PATHS}_tasks.md"
fi

# --------------------------------------------------------------------------
# A branch from before the split
#
# Rouh's code and the person's workspace were once one repository, and were
# split: the code went on as rouh-it/rouh-core and the workspace as a private
# repository of its own, both with a history that starts at the split. A
# branch made before then - a run that was working while it happened, or one
# left open and given a follow-up later - shares no history with either, and
# without this it would be refused with "shares no history", its work stuck on
# a branch nobody lands.
#
# So it is carried over: what it changed under `workspace/` becomes a commit
# of the workspace's own repository, what it changed anywhere else a commit of
# the code, each made on the target as it is now and landed by this same
# script, which deploys the code and moves the live workspace. The commit it
# was made from is the one its caller names (--from), else where it meets the
# last commit of the old repository, which the switch-over wrote into
# $LAND_DIR/split. Nothing is lost on any path: each part is kept on a branch
# land/carried/<run> in a folder under $LAND_DIR/carried, which stays when a
# part does not land, and the run's own branch is left exactly as it was.
# --------------------------------------------------------------------------

carry_over() {
  local split="" from="" msg="" stamp="" keep="" ws_url="" ws_dir="" code_dir="" out="" ws_json="" code_json="" n=""
  local -a inner=()
  split=$(tr -dc '0-9a-f' <"$LAND_DIR/split" 2>/dev/null | cut -c1-40)
  [ -n "$split" ] || return 1
  from=""
  if gq cat-file -e "$split^{commit}"; then
    from=$(gq merge-base HEAD "$split")
  fi
  if [ -z "$from" ] && [ -n "$FROM" ] && gq cat-file -e "$FROM^{commit}"; then
    from=$(gq rev-parse "$FROM^{commit}")
  fi
  [ -n "$from" ] || return 1
  # Only a branch of the old repository, which held the workspace as a folder.
  gq cat-file -e "$from:workspace/_migration-map.json" || return 1
  # What the old repository already had by the split, by patch, is in both new
  # ones already: a run that landed before the switch and is given a follow-up
  # after it must not carry its landed work over a second time. The rest is
  # laid on `from` in a scratch branch, and that is what is carried.
  local tip="" own="" c
  tip=$(gq rev-parse HEAD)
  if gq cat-file -e "$split^{commit}"; then
    own=$(gq cherry "$split" HEAD "$from" | awk '$1 == "+" {print $2}')
    if [ -z "$own" ]; then
      finish 0 state=nothing landed=false deployed=false commits=0 \
        "reason=everything on this branch was already in the old repository when it was split, so it is in the new ones; nothing was pushed"
    fi
    tip=$(gq rev-parse "$from")
    local tree=""
    for c in $own; do
      tree=$(git -C "$REPO" merge-tree --write-tree --merge-base "$c^" "$tip" "$c" 2>/dev/null) \
        || fail "its commit ${c:0:7} does not lay on what the old repository had cleanly; its work is still on $BRANCH"
      tip=$(git -C "$REPO" -c user.name=Rouh -c user.email=rouh@localhost commit-tree \
        "$(printf '%s\n' "$tree" | head -1)" -p "$tip" -m "$(gq log -1 --format=%B "$c")") \
        || fail "its commit ${c:0:7} could not be laid on the split; its work is still on $BRANCH"
    done
  fi
  n=$(gq rev-list --count "$from..$tip" | tr -d ' ')
  if [ "${n:-0}" = "0" ]; then
    finish 0 state=nothing landed=false deployed=false commits=0 \
      "reason=nothing new to land, so nothing was pushed and nothing was deployed"
  fi
  say "this branch was made before the code and the workspace became two repositories, so its $n commits are carried over to each"
  stamp=$(date -u +%Y%m%dT%H%M%SZ)
  keep="$LAND_DIR/carried/$RUN-$stamp"
  ( umask 000; mkdir -p "$LAND_DIR/carried" ) 2>/dev/null
  chmod 1777 "$LAND_DIR/carried" 2>/dev/null || true
  mkdir -p "$keep" || fail "nowhere to carry this branch's work over in ($keep)"
  msg="$keep/message"
  {
    printf 'Carried over from %s, made before the split (%s)\n\n' "$BRANCH" "$(gq rev-parse --short HEAD)"
    gq log --reverse --format='%B' "$from..$tip"
  } >"$msg"
  # The inner landings take the lock themselves.
  flock -u 9 2>/dev/null; exec 9<&-
  inner=(--run "$RUN" --title "$TITLE" --land-dir "$LAND_DIR" --target "$TARGET" --quiet)
  [ "$DEPLOY" = "1" ] || inner+=(--no-deploy)
  export GIT_AUTHOR_NAME="$(gq log -1 --format=%an HEAD)" GIT_AUTHOR_EMAIL="$(gq log -1 --format=%ae HEAD)"
  export GIT_COMMITTER_NAME="${GIT_COMMITTER_NAME:-$GIT_AUTHOR_NAME}" GIT_COMMITTER_EMAIL="${GIT_COMMITTER_EMAIL:-$GIT_AUTHOR_EMAIL}"

  if ! gq diff --quiet "$from" "$tip" -- workspace; then
    ws_url=$(git -c "safe.directory=$LIVE_WORKSPACE" -C "$LIVE_WORKSPACE" remote get-url origin 2>/dev/null)
    [ -n "$ws_url" ] || fail "its workspace part has nowhere to go: there is no live workspace repository at $LIVE_WORKSPACE to take the address from. Its work is still on $BRANCH"
    ws_dir="$keep/workspace"
    git clone -q --filter=blob:none "$ws_url" "$ws_dir" 2>"$keep/clone.err" \
      || fail "the workspace ($ws_url) could not be cloned to carry this branch over: $(tail -1 "$keep/clone.err"). Its work is still on $BRANCH"
    gq diff --binary --relative=workspace "$from" "$tip" -- workspace >"$keep/workspace.patch"
    git -C "$ws_dir" checkout -q -B "land/carried/$RUN" "origin/$TARGET"
    git -C "$ws_dir" apply --index -3 "$keep/workspace.patch" 2>"$keep/apply.err" \
      || fail "its workspace part does not apply to the workspace's $TARGET: $(tail -1 "$keep/apply.err"). Its work is still on $BRANCH, and the patch is $keep/workspace.patch"
    git -C "$ws_dir" commit -q -F "$msg" \
      || fail "its workspace part could not be committed in $ws_dir. Its work is still on $BRANCH"
    ws_json=$(bash "$SELF_DIR/land.sh" --path "$ws_dir" "${inner[@]}" | tail -n 1)
    say "the workspace part: $(printf '%s' "$ws_json" | "$PY" -c 'import json,sys; print(json.load(sys.stdin).get("reason",""))' 2>/dev/null)"
  fi
  if ! gq diff --quiet "$from" "$tip" -- . ':(exclude)workspace' ':(exclude).gitmodules'; then
    code_dir="$keep/code"
    g worktree add -q -B "land/carried/$RUN" "$code_dir" "$TARGET_REF" 2>"$keep/worktree.err" \
      || fail "a checkout of $TARGET could not be made to carry its code over: $(tail -1 "$keep/worktree.err"). Its work is still on $BRANCH"
    gq diff --binary "$from" "$tip" -- . ':(exclude)workspace' ':(exclude).gitmodules' >"$keep/code.patch"
    git -C "$code_dir" apply --index -3 "$keep/code.patch" 2>"$keep/apply-code.err" \
      || fail "its code does not apply to $TARGET: $(tail -1 "$keep/apply-code.err"). Its work is still on $BRANCH, and the patch is $keep/code.patch"
    git -C "$code_dir" commit -q -F "$msg" \
      || fail "its code could not be committed in $code_dir. Its work is still on $BRANCH"
    code_json=$(bash "$SELF_DIR/land.sh" --path "$code_dir" "${inner[@]}" | tail -n 1)
    say "the code part: $(printf '%s' "$code_json" | "$PY" -c 'import json,sys; print(json.load(sys.stdin).get("reason",""))' 2>/dev/null)"
  fi
  out=$("$PY" - "$ws_json" "$code_json" "$keep" <<'PYEOF'
import json, sys
parts = []
for name, raw in (("the workspace", sys.argv[1]), ("the code", sys.argv[2])):
    if not raw.strip():
        continue
    try:
        got = json.loads(raw)
    except ValueError:
        got = {"landed": False, "reason": "it said nothing that could be read"}
    parts.append((name, got))
landed = bool(parts) and all(g.get("landed") for _, g in parts)
code = [g for n, g in parts if n == "the code"]
deployed = all(g.get("deployed") for _, g in parts) if landed else False
reason = "; ".join(f"{n}: {g.get('reason') or ('landed' if g.get('landed') else 'not landed')}" for n, g in parts)
out = {"state": "carried" if landed else "error", "landed": landed, "deployed": deployed,
       "carried": True, "kept": sys.argv[3],
       "sha": (code[0].get("sha") if code else (parts[0][1].get("sha") if parts else "")) or "",
       "reason": ("carried over to the two repositories it became: " + reason) if parts else
                 "nothing to carry over"}
print(json.dumps(out))
PYEOF
)
  printf '%s\n' "$out"
  [ -n "$code_dir" ] && g worktree remove --force "$code_dir" 2>/dev/null
  # The same three ends as any landing: live, landed and not live, or not landed.
  case "$out" in
    *'"landed": true'*'"deployed": true'*) exit 0 ;;
    *'"landed": true'*) exit 13 ;;
  esac
  exit 1
}

# --------------------------------------------------------------------------
# Step 3, before anything else: rebase with memory
#
# Written into this repository's config rather than passed on a command line, so
# it holds for the worker's own git too and so a resolution recorded once is
# found again. rerere keeps its cache in the repository's common git directory,
# so a resolution recorded in one worktree is reused in every worktree of the
# same repository, which is the case that matters here: each job has a worktree
# of its own and they retry the same work.
# --------------------------------------------------------------------------

g config rerere.enabled true
g config rerere.autoupdate true
g config merge.conflictstyle diff3
g config rebase.autostash true

# A rebase writes commits, and a commit needs a committer. Rouh's saver lands
# as root in a checkout with no name configured, and without one every replay
# it needs stops at "Committer identity unknown" - which would be written down
# as a clash and put to the person. The committer of a
# replayed commit is only the one who moved it, so where none is set it is the
# author of the work being landed.
if ! gq var GIT_COMMITTER_IDENT >/dev/null; then
  GIT_COMMITTER_NAME=$(gq log -1 --format=%an HEAD)
  GIT_COMMITTER_EMAIL=$(gq log -1 --format=%ae HEAD)
  export GIT_COMMITTER_NAME="${GIT_COMMITTER_NAME:-Rouh}"
  export GIT_COMMITTER_EMAIL="${GIT_COMMITTER_EMAIL:-rouh@localhost}"
  say "no committer is set here, so the replay is committed as $GIT_COMMITTER_NAME <$GIT_COMMITTER_EMAIL>"
fi

# --------------------------------------------------------------------------
# Step 2: one at a time
#
# The lock is a file descriptor held by this process, so it is released when
# this process ends, however it ends: a clean landing, a conflict, a failure, a
# kill. There is no unlock to forget and no path that can skip one.
# --------------------------------------------------------------------------

LOCK="$LAND_DIR/land.lock"

# The lock is opened for reading, not for writing, and that is not a detail.
# flock needs no write access, and a kernel with `fs.protected_regular` on (most
# Linux systems) refuses to open another user's file for writing inside a
# world-writable sticky directory. The users that land work - the one Rouh's own crew runs as, and
# the one every run of the one program runs as - need not share a group, so
# whichever of them created the file, the other would be refused: opened for
# writing it gives "Permission denied", opened for reading it gives the lock.
# Readability is checked before the `exec`, and the `exec` carries no
# redirection of its own. `exec 9<file 2>/dev/null` looks like it silences one
# command and does not: an exec with nothing but redirections applies them to
# this shell for the rest of its life, so that one would have sent every line
# this script says afterwards to /dev/null. It did, until it was watched.
open_the_lock_file() {
  local where="$1"
  [ -e "$where" ] || ( umask 000; : >"$where" ) 2>/dev/null
  chmod 666 "$where" 2>/dev/null || true
  [ -r "$where" ] || return 1
  exec 9<"$where" || return 1
  LOCK="$where"
  return 0
}

take_the_lock() {
  mkdir -p "$LAND_DIR/conflicts" 2>/dev/null
  # Sticky and world-writable, like /tmp: anybody may add a file, nobody may
  # remove anybody else's. Only root can make it under /srv, which the deploy
  # and Rouh's own start both do (`update-all.sh`, `rouh/conflicts.py`).
  chmod 1777 "$LAND_DIR" "$LAND_DIR/conflicts" 2>/dev/null || true
  if ! open_the_lock_file "$LAND_DIR/land.lock"; then
    # No file, but the directory is there and readable: lock the directory
    # itself. It is the same one lock for everybody, which is the whole of what
    # is being asked of it.
    if [ -r "$LAND_DIR" ] && exec 9<"$LAND_DIR"; then
      LOCK="$LAND_DIR"
      say "locking $LAND_DIR itself; its lock file could not be opened"
    else
      # Nowhere at all. Under /tmp rather than no lock: two jobs landing in the
      # same second is the failure this exists to stop, and one lock shared by
      # everything that can reach /tmp is better than none.
      LAND_DIR="${TMPDIR:-/tmp}/rouh-land"
      mkdir -p "$LAND_DIR" 2>/dev/null || fail "nowhere to keep the landing lock"
      chmod 1777 "$LAND_DIR" 2>/dev/null || true
      open_the_lock_file "$LAND_DIR/land.lock" || fail "cannot hold a landing lock anywhere"
      say "using $LOCK for the lock"
    fi
  fi
  flock -w "$WAIT" 9 \
    || fail "another landing held the lock for more than ${WAIT}s, so this one did not start"
  say "holding the landing lock"
}

fetch_target() {
  local err rc
  err=$(g fetch -q "$REMOTE" "$TARGET" 2>&1); rc="$?"
  if [ "$rc" != "0" ]; then
    say "could not fetch $TARGET_REF: $(printf '%s' "$err" | tr '\n' ' ' | cut -c1-200)"
    return 1
  fi
  return 0
}

# Moving the branch without ever overwriting work nobody committed. --keep
# updates only the files that differ between here and there and refuses outright
# if one of those has local changes, which is what a job that deliberately left
# a failed change uncommitted needs: a --hard here would delete it.
move_to() {
  local where="$1"
  g reset -q --keep "$where" 2>/dev/null && return 0
  say "could not move this checkout to $where without overwriting uncommitted work, so it was left where it is"
  return 1
}

# One number, one task. Asked right before every push, of main as it is and
# main as it would be, so it holds whoever wrote the commit: a task number or an
# object id that this landing would put on a second folder stops it here, with
# the sentence saying which folders and what to do (`rouh/numbering.py`).
# Without it two jobs started together can each make "the next" task.
# Nothing is pushed, nothing is thrown away: the work stays on this branch.
numbers_guard() {
  local said
  [ -n "$PY" ] || return 0
  said=$(PYTHONPATH="$SELF_DIR${PYTHONPATH:+:$PYTHONPATH}" \
    "$PY" -m rouh.numbering check --repo "$REPO" --before "$TARGET_REF" --after HEAD)
  [ "$?" = "0" ] && return 0
  say "$said"
  finish 1 state=error landed=false duplicate=true "reason=$said"
}

# A box handed to a job is never committed. Asked right before every push, of
# every commit about to be pushed, not only of the end result: a box's file
# added in one commit and deleted in the next is still in the history. A job is
# handed a box as a file at .secrets/box-<number> in its own folder (rouh/boxes.py,
# "Handing a box to a job"), with a .gitignore of `*` beside it, so only a run
# that forced it in gets here; nothing is pushed, and the work stays on its branch.
secrets_guard() {
  local found said
  found=$(gq log --format= --name-only "$TARGET_REF..HEAD" 2>/dev/null \
    | grep -E '(^|/)\.secrets(/|$)' | sort -u | head -3 | paste -sd ',' -)
  [ -n "$found" ] || return 0
  said="Nothing was pushed: a commit about to be pushed holds a box handed to a job ($found). A box's file in .secrets is never committed; take it out of the branch's history and land again."
  say "$said"
  finish 1 state=error landed=false secrets=true "reason=$said"
}

# The page's types. Asked right before every push, beside one number, one task,
# of work that touches the page's code: app.js, its modules in
# rouh/static/app/, or the type checker's own settings. `tsc --noEmit` over
# the page has to pass before anything lands (tools/typecheck/check.sh), so a
# field misspelt in a WebSocket message
# or a card block stops here, with the errors, rather than reaching a screen.
# What is checked is the commit about to be pushed, not the worktree.
# Nothing is pushed and nothing is thrown away: the work stays on this branch.
TYPED_PATHS=(rouh/static/app.js rouh/static/app rouh/static/vad.d.ts tsconfig.json tools/typecheck)
types_guard() {
  local changed said rc typed first errors
  gq cat-file -e HEAD:tools/typecheck/check.sh || return 0
  changed=$(gq diff --name-only "$TARGET_REF" HEAD -- "${TYPED_PATHS[@]}")
  [ -n "$changed" ] || return 0
  say "checking the page's types, since this changes $(printf '%s' "$changed" | head -1)"
  typed=$(mktemp -d 2>/dev/null) || fail "nowhere to check the page's types"
  gq archive HEAD -- "${TYPED_PATHS[@]}" | tar -x -C "$typed" 2>/dev/null
  said=$("$typed/tools/typecheck/check.sh" "$typed" 2>&1); rc="$?"
  rm -rf -- "$typed"
  # tsc names files relative to wherever it ran; the copy's folder means nothing.
  said=$(printf '%s' "$said" | sed "s#[^ (]*$(basename "$typed")/##g")
  if [ "$rc" = "0" ]; then
    say "the page's types check"
    return 0
  fi
  first=$(printf '%s\n' "$said" | grep -m1 . || true)
  errors=$(printf '%s\n' "$said" | grep -c 'error TS' || true)
  if [ "$errors" = "1" ]; then errors="1 error"; else errors="$errors errors"; fi
  said="Nothing was pushed: the page's type check (tools/typecheck/check.sh) did not pass, $errors. The first: $first"
  say "$said"
  finish 1 state=error landed=false types=false "reason=$said"
}

# The mail replay. Asked right before every push, beside the page's types, of
# work that touches how Rouh handles mail and messages from trusted contacts.
# A case that regresses stops a landing: `python -m rouh.mail_replay` judges
# every real case kept in
# rouh/testing/mail_replay.json, ask by ask, against the outcome it must have,
# and fails if any module but the outbox can send to a contact (MAIL.md, D9).
# It needs nothing but the standard library and the commit about to be pushed.
MAIL_PATHS=(rouh/mail_cases.py rouh/mail_ledger.py rouh/mail_outbox.py rouh/mail_replay.py
  rouh/mail_turn.py rouh/mail_alerts.py rouh/grants.py rouh/trusted.py rouh/reminders.py
  rouh/telegram_guests.py rouh/telegram_chat.py rouh/case_dry_run.py rouh/case_fixes.py
  rouh/case_trace.py rouh/decision_sources.py rouh/testing/mail_replay.json
  rouh/management/commands/case_follow_up.py rouh/clockwork_grants.py rouh/timekeeper.py
  rouh/case_actions.py rouh/capabilities.py rouh/capabilities.lock.json rouh/capability_grants.py
  rouh/genes/manifests)
mail_guard() {
  local changed said rc copy last first
  gq cat-file -e HEAD:rouh/mail_replay.py || return 0
  [ -n "$PY" ] || return 0
  changed=$(gq diff --name-only "$TARGET_REF" HEAD -- "${MAIL_PATHS[@]}")
  [ -n "$changed" ] || return 0
  say "replaying the mail cases, since this changes $(printf '%s' "$changed" | head -1)"
  copy=$(mktemp -d 2>/dev/null) || fail "nowhere to replay the mail cases"
  gq archive HEAD -- rouh ':!rouh/static' ':!rouh/templates' | tar -x -C "$copy" 2>/dev/null
  said=$(cd "$copy" && "$PY" -m rouh.mail_replay 2>&1); rc="$?"
  rm -rf -- "$copy"
  last=$(printf '%s\n' "$said" | grep . | tail -1)
  if [ "$rc" = "0" ]; then
    say "the mail replay: $last"
    return 0
  fi
  first=$(printf '%s\n' "$said" | grep -m1 '^FAIL' || printf '%s' "$last")
  said="Nothing was pushed: the mail replay (python -m rouh.mail_replay) did not pass: ${last%.}. The first: $first"
  say "$said"
  finish 1 state=error landed=false mail=false "reason=$said"
}

# The LLM service. Asked right before every push, beside the mail replay, of work
# that touches Rouh's Python. Every call to a model goes through the model the
# Models page selects for it, with no exceptions, and this keeps it that way:
# `python -m rouh.llmguard` fails on a model client made past rouh/llmlog.py, a model
# asked past the LLM service, or a model named in code. Standard library only.
llm_guard() {
  local changed said rc copy last first
  gq cat-file -e HEAD:rouh/llmguard.py || return 0
  [ -n "$PY" ] || return 0
  changed=$(gq diff --name-only "$TARGET_REF" HEAD -- 'rouh/*.py' 'rouh/**/*.py')
  [ -n "$changed" ] || return 0
  say "checking every model call goes through the LLM service, since this changes $(printf '%s' "$changed" | head -1)"
  copy=$(mktemp -d 2>/dev/null) || fail "nowhere to check the model calls"
  gq archive HEAD -- rouh ':!rouh/static' ':!rouh/templates' | tar -x -C "$copy" 2>/dev/null
  said=$(cd "$copy" && "$PY" -m rouh.llmguard 2>&1); rc="$?"
  rm -rf -- "$copy"
  last=$(printf '%s\n' "$said" | grep . | tail -1)
  if [ "$rc" = "0" ]; then
    say "the LLM service: $last"
    return 0
  fi
  first=$(printf '%s\n' "$said" | grep -m1 '^FAIL' || printf '%s' "$last")
  said="Nothing was pushed: a model is asked or named past the LLM service (python -m rouh.llmguard): ${last%.}. The first: $first"
  say "$said"
  finish 1 state=error landed=false llm=false "reason=$said"
}

# The old server's layout. Asked right before every push of work that touches Rouh's code, the one
# program or bin/: since the move to containers (31 October 2026) code that called systemd or read
# /var/www/rouh failed there quietly, so every such mention is listed with why it is right
# (`python -m rouh.hostguard`, rouh/hostpaths.json). Standard library only.
host_guard() {
  local changed said rc copy last first
  gq cat-file -e HEAD:rouh/hostguard.py || return 0
  [ -n "$PY" ] || return 0
  changed=$(gq diff --name-only "$TARGET_REF" HEAD -- rouh one bin)
  [ -n "$changed" ] || return 0
  copy=$(mktemp -d 2>/dev/null) || fail "nowhere to check the old server's layout"
  gq archive HEAD -- rouh one bin ':!rouh/static' | tar -x -C "$copy" 2>/dev/null
  said=$(cd "$copy" && "$PY" -m rouh.hostguard 2>&1); rc="$?"
  rm -rf -- "$copy"
  last=$(printf '%s\n' "$said" | grep . | tail -1)
  if [ "$rc" = "0" ]; then
    say "the old server's layout: $last"
    return 0
  fi
  first=$(printf '%s\n' "$said" | grep -m1 '^FAIL' || printf '%s' "$last")
  said="Nothing was pushed: code names the old server's layout without saying why (python -m rouh.hostguard): $first"
  say "$said"
  finish 1 state=error landed=false hosts=false "reason=$said"
}

# The gene contract. Asked right before every push, beside the mail replay, of
# work that touches the gene registry, the page's markup or its script.
# The navigation is drawn from one registry of genes, one manifest per gene
# (GENES.md), and this check fails when a link is added outside it or a
# manifest has no valid group:
# `python -m rouh.genes` reads every gene manifest, the page and its script, and
# tries itself on broken copies. Standard library only.
GENE_PATHS=(rouh/genes rouh/templates/rouh/index.html rouh/templates/rouh/_nav_row.html
  rouh/static/app rouh/static/app.js)
genes_guard() {
  local changed said rc copy last first
  gq cat-file -e HEAD:rouh/genes/__main__.py || return 0
  [ -n "$PY" ] || return 0
  changed=$(gq diff --name-only "$TARGET_REF" HEAD -- "${GENE_PATHS[@]}")
  [ -n "$changed" ] || return 0
  say "checking the gene contract, since this changes $(printf '%s' "$changed" | head -1)"
  copy=$(mktemp -d 2>/dev/null) || fail "nowhere to check the gene contract"
  # rouh/capabilities.py checks a manifest's capabilities (CAPABILITIES.md); standard library only.
  gq archive HEAD -- rouh/__init__.py rouh/genes rouh/capabilities.py rouh/capabilities.lock.json \
    rouh/templates/rouh rouh/static | tar -x -C "$copy" 2>/dev/null
  said=$(cd "$copy" && "$PY" -m rouh.genes 2>&1); rc="$?"
  rm -rf -- "$copy"
  last=$(printf '%s\n' "$said" | grep . | tail -1)
  if [ "$rc" = "0" ]; then
    say "the gene contract: $last"
    return 0
  fi
  first=$(printf '%s\n' "$said" | grep -m1 '^FAIL' || printf '%s' "$last")
  said="Nothing was pushed: the gene contract (python -m rouh.genes) does not hold: ${last%.}. The first: $first"
  say "$said"
  finish 1 state=error landed=false genes=false "reason=$said"
}

# Every file belongs to a gene. Asked right before every push, of every change.
# There is no plumbing that is not a gene: every file of
# Rouh is owned by one or more genes in rouh/genes/owners.json, so that every
# change is written into the history of the genes whose files it touched
# (GENES.md, "Every file belongs to a gene"). A change that adds or changes a
# file no gene owns stops here, naming the file, until the map gives it one.
# The workspace is the person's own work, not Rouh, and is never asked about.
# Standard library only; the map and its checker are the commit's own.
owners_guard() {
  local said rc copy
  gq cat-file -e HEAD:rouh/genes/owners.py || return 0
  [ -n "$PY" ] || return 0
  copy=$(mktemp -d 2>/dev/null) || fail "nowhere to check which gene each file belongs to"
  gq archive HEAD -- rouh/genes | tar -x -C "$copy" 2>/dev/null
  : >"$copy/rouh/__init__.py"
  said=$(cd "$copy" && "$PY" -m rouh.genes.owners changed --repo "$REPO" --before "$TARGET_REF" --after HEAD 2>/dev/null); rc="$?"
  rm -rf -- "$copy"
  if [ "$rc" = "0" ]; then
    say "$said"
    return 0
  fi
  said="Nothing was pushed: $(printf '%s\n' "$said" | grep -m1 . || printf 'the gene ownership map could not be read')"
  say "$said"
  finish 1 state=error landed=false owners=false "reason=$said"
}

# The design standard. Asked right before every push of work that changes the screen:
# rouh/static/, rouh/templates/, one/static/ (Petar, 7 November 2026, task 169). Every
# change a person sees follows one design process in two tiers (rouh/design_standard.py),
# and the run keeps its record with tools/design/record.py in .design/record.json of
# its own checkout, never committed. A change to the screen stops here when the record
# is missing, a journey was missed, the check of the real screens at 1440 and 390 px
# found a fault (sideways scroll, cut text, a covering panel, a page that draws almost
# nothing, a script error, a broken image, a request to another site), a full-tier
# design still has a critic blocker, or the screen's files changed after the check. A
# commit line "Design: none - <why>" says a change to those files shows nothing new.
# Standard library only; nothing is pushed and nothing is thrown away.
design_guard() {
  local said rc copy
  gq cat-file -e HEAD:rouh/design_standard.py || return 0
  [ -n "$PY" ] || return 0
  [ "$(setting ROUH_DESIGN_GUARD 1)" = "1" ] || return 0
  copy=$(mktemp -d 2>/dev/null) || fail "nowhere to check the design record"
  mkdir -p "$copy/rouh" && : >"$copy/rouh/__init__.py"
  gq show HEAD:rouh/design_standard.py >"$copy/rouh/design_standard.py" 2>/dev/null
  said=$(cd "$copy" && "$PY" -m rouh.design_standard check --repo "$REPO" --before "$TARGET_REF" \
    --after HEAD --record "$REPO/.design/record.json" 2>&1); rc="$?"
  rm -rf -- "$copy"
  if [ "$rc" = "0" ]; then
    say "$(printf '%s\n' "$said" | grep . | tail -1)"
    return 0
  fi
  said="Nothing was pushed: $(printf '%s\n' "$said" | grep . | tail -1)"
  say "$said"
  finish 1 state=error landed=false design=false "reason=$said"
}

# How a gene says it was used. Asked right before every push of work that touches
# Rouh's Python or the gene registry. A gene's trial counts the times its own
# code says it was used, which never adds up for a gene whose code never says
# it. So every gene with a switch declares its use
# signals, and its code reports each named one through evolution.used(switch,
# event): `python -m rouh.genes.signals` fails on a gene that declares none, an
# event declared and never reported, or one reported and never declared
# (GENES.md, "How a gene says it was used"). Standard library only.
signals_guard() {
  local changed said rc copy last first
  gq cat-file -e HEAD:rouh/genes/signals.py || return 0
  [ -n "$PY" ] || return 0
  changed=$(gq diff --name-only "$TARGET_REF" HEAD -- 'rouh/*.py' 'rouh/**/*.py' rouh/genes)
  [ -n "$changed" ] || return 0
  say "checking how each gene says it was used, since this changes $(printf '%s' "$changed" | head -1)"
  copy=$(mktemp -d 2>/dev/null) || fail "nowhere to check how the genes say they were used"
  gq archive HEAD -- rouh ':!rouh/static' ':!rouh/templates' | tar -x -C "$copy" 2>/dev/null
  said=$(cd "$copy" && "$PY" -m rouh.genes.signals 2>&1); rc="$?"
  rm -rf -- "$copy"
  last=$(printf '%s\n' "$said" | grep . | tail -1)
  if [ "$rc" = "0" ]; then
    say "the use signals: $last"
    return 0
  fi
  first=$(printf '%s\n' "$said" | grep -m1 '^FAIL' || printf '%s' "$last")
  said="Nothing was pushed: a gene does not say how it was used (python -m rouh.genes.signals): ${last%.}. The first: $first"
  say "$said"
  finish 1 state=error landed=false signals=false "reason=$said"
}

# The stack test. Asked before the lock is taken, of work that touches what only
# the containers can show: the stack file, the images, the protected core, the
# stack test itself, the libraries. This machine has no Docker, so it hands the
# work as it is to GitHub on a branch of its own, stack-check/<run>, where
# .github/workflows/stack-tests.yml brings the real stack up on Intel and Arm,
# built from it, and checks every feature CONTAINERS.md says works; the result
# comes back on the branch stack-checks, read over the same access this pushes
# with. A failure stops the landing, with the run to read; nothing is pushed to
# the target and nothing is thrown away. Before the lock, because it takes the
# better part of an hour and every other landing would wait on it. Everything
# else is checked the same way after it lands, by "Tests on main", whose record
# is what a new Rouh installs (Petar, 29 October 2026: a change that breaks a
# feature in the containers fails).
STACK_PATHS=(deploy/stack deploy/container guard tests/stack CONTAINERS.md pyproject.toml uv.lock
  one/requirements.txt mcp-servers.json .github/workflows/stack-tests.yml .github/workflows/main-tests.yml)
STACK_GUARD="$(setting ROUH_STACK_GUARD 1)"
STACK_WAIT="$(setting ROUH_STACK_WAIT 7200)"
stack_result() {                 # stack_result SHA: prints the result's JSON, or fails
  g fetch -q "$REMOTE" "+refs/heads/stack-checks:refs/remotes/$REMOTE/stack-checks" 2>/dev/null
  gq show "$REMOTE/stack-checks:results/$1.json"
}
stack_guard() {
  local changed sha branch deadline said ok run err
  [ "$STACK_GUARD" = "1" ] && [ "$NO_PUSH" != "1" ] && [ -n "$PY" ] || return 0
  gq cat-file -e HEAD:tests/stack/run.sh || return 0
  g fetch -q "$REMOTE" "$TARGET" 2>/dev/null || return 0
  changed=$(gq diff --name-only "$(gq merge-base HEAD "$TARGET_REF")" HEAD -- "${STACK_PATHS[@]}")
  [ -n "$changed" ] || return 0
  sha=$(gq rev-parse HEAD)
  if ! said=$(stack_result "$sha"); then
    branch="stack-check/${RUN:-$(printf '%s' "$sha" | cut -c1-12)}"
    say "this changes the containers' side ($(printf '%s' "$changed" | head -1)), so the stack test runs first, at GitHub, on $branch"
    err=$(g push -q -f "$REMOTE" "HEAD:refs/heads/$branch" 2>&1) || {
      said="Nothing was pushed: the work could not be handed to the stack test ($(printf '%s' "$err" | tr '\n' ' ' | cut -c1-200))"
      say "$said"; finish 1 state=error landed=false stack=false "reason=$said"; }
    deadline=$(( $(date +%s) + STACK_WAIT ))
    until said=$(stack_result "$sha"); do
      if [ "$(date +%s)" -ge "$deadline" ]; then
        g push -q "$REMOTE" ":refs/heads/$branch" 2>/dev/null
        said="Nothing was pushed: the stack test of $(printf '%s' "$sha" | cut -c1-12) did not finish in ${STACK_WAIT}s (Actions, Stack test, branch $branch)"
        say "$said"; finish 1 state=error landed=false stack=false "reason=$said"
      fi
      sleep 60
    done
    g push -q "$REMOTE" ":refs/heads/$branch" 2>/dev/null
  fi
  ok=$(printf '%s' "$said" | "$PY" -c 'import json,sys; print("yes" if json.load(sys.stdin).get("ok") else "no")' 2>/dev/null)
  run=$(printf '%s' "$said" | "$PY" -c 'import json,sys; r=json.load(sys.stdin); print(r.get("run") or r.get("where") or "")' 2>/dev/null)
  if [ "$ok" = "yes" ]; then
    say "the stack test passed ($run)"
    return 0
  fi
  said="Nothing was pushed: the stack test failed, so a feature CONTAINERS.md says works does not work in the containers with this change: $run"
  say "$said"
  finish 1 state=error landed=false stack=false "reason=$said"
}

# Which run landed which commits, so the gene log can say where each change was
# asked for: the person's words in a chat, their feedback, the nightly run (GENES.md).
# Taken right before the push, while the target still names what was there, and
# written by `landed_and` once the push is through. One line a landing:
# the time, the run and its commits, in $LAND_DIR/landed.tsv, which Rouh reads.
LANDING_COMMITS=""
note_landing() {
  LANDING_COMMITS=$(gq rev-list --reverse "$TARGET_REF..HEAD" | tr '\n' ' ')
}
keep_landing() {
  [ -n "$LANDING_COMMITS" ] && [ -d "$LAND_DIR" ] || return 0
  printf '%s\t%s\t%s\n' "$(date +%s)" "$RUN" "${LANDING_COMMITS% }" >>"$LAND_DIR/landed.tsv" 2>/dev/null || true
  chmod 0666 "$LAND_DIR/landed.tsv" 2>/dev/null || true
  LANDING_COMMITS=""
}

# --------------------------------------------------------------------------
# Step 7: the deploy
#
# A commit on main that nothing is serving is not done. A landing that pushed,
# said "landed" and left the deploy to whatever might notice could leave its
# commit on main unserved for hours while the person looked at the one before
# it. So the push is not the end of a landing.
#
# Three things this has to get right, and all three of them are why it is
# written out here rather than being one line that calls a script.
#
#   1. **It must survive its own deploy.** The job running this is very often
#      a run of the one program, and the deploy restarts that program and then
#      Rouh. So the deploy is handed to a detached session of its own, with
#      its output and its exit code going to files: nothing about it depends on
#      this process still being here a minute from now.
#   2. **It must not believe the deploy.** A script exiting 0 is a claim. The
#      only thing worth believing is a service answering its own health page
#      with the commit that was pushed, which is what `live` asks, over and
#      over, until it is true or the time is up.
#   3. **One at a time.** The lock is inside update-all.sh, because every way
#      of starting a deploy on this machine goes through that script - this,
#      `deploy_myself`, and the deploy that follows a landed change - and a
#      lock that only this script took would not be a lock at all.
#
# It is also careful about when there is nothing to deploy. A checkout of
# another repository, a landing onto a branch this machine does not serve, or a
# machine with no Rouh deployment on it at all are all answered with a plain
# sentence saying the work is on the target and not live, and none of them is
# reported as a deploy that worked.
# --------------------------------------------------------------------------

#: Set by `deploy_it`: whether the commit is being served, one word for what
#: happened, and the sentence that says it.
DEPLOYED="false"
DEPLOY_STATE="none"
DEPLOY_SAID=""
#: Where this landing's deploy wrote its output, its outcome and its exit code,
#: so a failure names somewhere a person can go and read the whole of it.
DEPLOY_DIR=""

# What a service says it is serving, out of its own health page: the short
# commit, or nothing at all when it does not answer. Not answering is ordinary
# here - it is what a service looks like for the second it is restarting.
serving() {
  local body
  body=$(curl -fsS --max-time 5 "$1" 2>/dev/null) || return 1
  [ -n "$PY" ] || return 1
  SERVING_KEY="$2" "$PY" -c '
import json, os, sys
try:
    got = json.load(sys.stdin)
except Exception:
    raise SystemExit(1)
said = got.get(os.environ["SERVING_KEY"])
print(str(said or "")[:40])
' <<<"$body" 2>/dev/null
}

# Whether what a service is serving holds the commit that was pushed: that
# commit exactly, or one after it. Another job may land while this deploy is on
# its way, and a build that carries this work is a build that serves it.
holds() {
  local said="$1" want="$2"
  [ -n "$said" ] || return 1
  case "$want" in "$said"*) return 0 ;; esac
  gq rev-parse --verify -q "${said}^{commit}" >/dev/null || return 1
  gq merge-base --is-ancestor "$want" "$said" >/dev/null 2>&1
}

# Both services, answering with the commit. A health page named as empty is a
# service this machine does not have, and is not waited for.
live() {
  local want="$1" pair url key said
  for pair in "$ROUH_HEALTH|revision" "$ONE_HEALTH|commit"; do
    url="${pair%%|*}"; key="${pair##*|}"
    [ -n "$url" ] || continue
    said=$(serving "$url" "$key") || return 1
    holds "$said" "$want" || return 1
  done
  return 0
}

# The last thing the deploy said about itself: the one sentence update-all.sh
# leaves in its outcome file, otherwise the last line of its output.
deploy_said() {
  local outcome="$1" log="$2" line=""
  if [ -s "$outcome" ]; then
    line=$(head -n 1 "$outcome" | sed -E 's/^(done|failed) ?//')
  fi
  if [ -z "$line" ] && [ -s "$log" ]; then
    line=$(grep -v '^[[:space:]]*$' "$log" | tail -n 1 | sed -E 's/^\[[^]]*\] ?//')
  fi
  printf '%s' "$(printf '%s' "$line" | tr '\n' ' ' | cut -c1-300)"
}

# Why there is nothing here to deploy onto, or "" when there is. None of these
# is a failure of the work: they are machines and branches this script is being
# run on that serve nothing.
nothing_to_deploy() {
  local url mine theirs
  if [ "$DEPLOY" != "1" ]; then
    printf '%s' "the deploy was turned off for this landing"; return 0
  fi
  if [ "$TARGET" != "$DEPLOY_BRANCH" ]; then
    printf '%s' "$TARGET is not the branch this machine serves"; return 0
  fi
  # Nothing to ask afterwards is nothing to believe. A machine with no health
  # page is a machine where a deploy cannot be proved, and an unproved deploy
  # is never reported as one.
  if [ -z "$ROUH_HEALTH" ] && [ -z "$ONE_HEALTH" ]; then
    printf '%s' "there is no health page here to check a deploy against"; return 0
  fi
  if [ ! -f "$DEPLOY_SCRIPT" ]; then
    printf '%s' "there is no deploy script at $DEPLOY_SCRIPT, so nothing here deploys"; return 0
  fi
  # The services are served out of Rouh's checkout of one repository. A job
  # landing some other repository must never restart them.
  if [ -d "$DEPLOY_APP/.git" ]; then
    url=$(gq remote get-url "$REMOTE")
    mine=$(printf '%s' "$url" | sed -E 's#\.git$##; s#/$##')
    theirs=$(git -c "safe.directory=$DEPLOY_APP" -C "$DEPLOY_APP" remote get-url origin 2>/dev/null \
             | sed -E 's#\.git$##; s#/$##')
    if [ -n "$mine" ] && [ -n "$theirs" ] && [ "$mine" != "$theirs" ]; then
      printf '%s' "$url is not the repository this machine serves"; return 0
    fi
  fi
  printf ''
  return 0
}

# --------------------------------------------------------------------------
# Step 7a: the content guard, which is the one reason not to deploy
#
# A repository can hold the person's workspace at workspace/: task folders,
# notes and built pages that the server's jobs write into all day. Every one
# of those notes is then a commit in the repository Rouh is deployed from, and
# without this a paragraph typed at a terminal at two in the
# morning would fetch, pip-install and restart both services. That is not a
# deploy; it is an outage with a reason, repeated all night.
#
# So the question asked here is not "did the commit change anything" - it
# always did, or there would be nothing to land. It is the narrower one that
# actually decides whether a restart is worth it:
#
#     does any service have to be restarted?
#
# The files move either way. Rouh serves what is under workspace/ off the
# checkout it is deployed in, reading it on every request, so a landing that
# skipped the disk would put the person's own words on main and leave the
# screen showing yesterday's.
#
# Which is answered by comparing what each service says it is serving with the
# commit that was just pushed, and looking at what is different. If everything
# that differs is under CONTENT_PATHS, nothing either service runs has changed
# and the restart would buy nothing, so `update-all.sh --files-only` moves both
# checkouts and touches neither service. If one single path outside them
# differs - a .py, a static file, a shell script, a requirement - it is a code
# deploy and goes down the ordinary road.
#
# Asking the running services rather than looking at this landing's own commits
# is deliberate, and it is the difference between a rule that is right and one
# that is nearly right. A content commit landing on top of somebody else's code
# commit that never went live is still a deploy, because the machine is behind
# on code; this notices, and "were my commits content-only?" would not.
#
# It fails safe, every way it can. A service that does not answer, a commit
# this checkout has never heard of, a machine with no health page: all of them
# fall through to the deploy. The cost of deploying when it was not needed is a
# restart nobody wanted. The cost of skipping one that was needed is a change
# on main that nothing is serving, which this whole script exists to stop.
#
# Both answers are said out loud, because a rule that decides silently is a
# rule nobody can check.
# --------------------------------------------------------------------------

#: Set by `only_content`: the path outside CONTENT_PATHS that made this a code
#: deploy, or the sentence saying nothing but content moved.
CONTENT_WHY=""

#: Set by `move_content` when it could not move the files, and used as the
#: reason the ordinary deploy runs instead.
CONTENT_MOVE_WHY=""

# Move both serving checkouts onto $1 without restarting either service.
#
# `update-all.sh --files-only` is the whole of it, run here rather than
# detached: it restarts nothing, so it cannot kill the process that started it,
# and a landing that waits ten seconds and then says truthfully what is on disk
# is worth more than one that guesses. It takes the same deploy lock every
# other deploy takes, so it queues behind one in flight rather than racing it,
# and it refuses on its own if a single path outside CONTENT_PATHS differs.
move_content() {
  local want="$1" out code
  CONTENT_MOVE_WHY=""
  [ -n "$DEPLOY_SCRIPT" ] || DEPLOY_SCRIPT="$DEPLOY_APP/update-all.sh"
  if [ ! -f "$DEPLOY_SCRIPT" ]; then
    CONTENT_MOVE_WHY="there is no deploy script at $DEPLOY_SCRIPT"
    return 1
  fi
  local -a argv=()
  [ "$(id -u)" = "0" ] || argv+=(sudo -n)
  argv+=(env "ROUH_APP_DIR=$DEPLOY_APP" "ROUH_LAND_DIR=$LAND_DIR"
         "JARVIS_APP_DIR=$DEPLOY_APP" "JARVIS_LAND_DIR=$LAND_DIR"
         bash "$DEPLOY_SCRIPT" --to "$want" --files-only)
  out=$("${argv[@]}" 2>&1)
  code=$?
  if [ "$code" != 0 ]; then
    CONTENT_MOVE_WHY="the files could not be moved without a restart: $(printf '%s' "$out" | tail -n 1)"
    printf '%s\n' "$out" | sed 's/^/    /' >&2
    return 1
  fi
  return 0
}

# Whether one path is content rather than code.
is_content() {
  local path="$1" prefix
  for prefix in $CONTENT_PATHS; do
    [ -n "$prefix" ] || continue
    case "$path" in "$prefix"*) return 0 ;; esac
  done
  return 1
}

# The first path outside CONTENT_PATHS that differs between two commits, or ""
# when everything that differs is content. A commit this checkout does not hold
# is answered with a path-shaped sentence, so the caller deploys. Both sides of
# a rename are listed (--no-renames): a plain --name-only names only where a
# file went, so moving one out of rouh/ into workspace/ looked like content.
first_code_path() {
  local from="$1" to="$2" path
  gq rev-parse --verify -q "${from}^{commit}" >/dev/null 2>&1 || {
    printf '%s' "a commit this checkout has never seen ($from)"; return 0; }
  while IFS= read -r path; do
    [ -n "$path" ] || continue
    is_content "$path" || { printf '%s' "$path"; return 0; }
  done < <(gq diff --no-renames --name-only "$from" "$to" 2>/dev/null)
  printf ''
  return 0
}

# True when every service is already running the code in $1 and the only thing
# this landing moves is content. Sets CONTENT_WHY to the sentence saying why,
# whichever way it went.
only_content() {
  local want="$1" pair url key name said code asked=0 seen=""
  CONTENT_WHY=""
  for pair in "$ROUH_HEALTH|revision|Rouh" "$ONE_HEALTH|commit|the one program"; do
    url="${pair%%|*}"; key="${pair#*|}"; key="${key%%|*}"; name="${pair##*|}"
    [ -n "$url" ] || continue
    said=$(serving "$url" "$key")
    if [ -z "$said" ]; then
      CONTENT_WHY="$name is not answering its health page, so what it is running is unknown"
      return 1
    fi
    code=$(first_code_path "$said" "$want")
    if [ -n "$code" ]; then
      CONTENT_WHY="$name is on ${said:0:7} and $code is code, not content"
      return 1
    fi
    asked=$((asked + 1))
    seen="${seen:+$seen and }$name on ${said:0:7}"
  done
  if [ "$asked" = "0" ]; then
    CONTENT_WHY="there is no health page here to ask what is running"
    return 1
  fi
  CONTENT_WHY="everything it moves is under $CONTENT_PATHS, which no service runs; what is running is $seen"
  return 0
}

# The last step of a workspace's own landing: the live workspace moved onto
# what was pushed, and nothing restarted, because nothing runs what is in it.
# Rouh reads it off the disk on every request, so a landing that did not move
# it would put the words on main and leave the screen showing yesterday's.
# `update-all.sh --workspace` does the move, under the same deploy lock every
# other deploy takes, as root, because the live workspace is Rouh's.
move_workspace() {
  local want="$1" short="${1:0:7}" url mine theirs out code
  local -a argv=()
  DEPLOYED="false"; DEPLOY_STATE="none"; DEPLOY_SAID=""; DEPLOY_DIR=""
  if [ "$DEPLOY" != "1" ]; then
    DEPLOY_SAID="moving the live workspace was turned off for this landing, so $short is on $TARGET and the live workspace was left where it is"
    say "$DEPLOY_SAID"; return 0
  fi
  if [ "$TARGET" != "$DEPLOY_BRANCH" ]; then
    DEPLOY_SAID="$TARGET is not the branch this machine serves, so $short is on $TARGET and the live workspace was not moved"
    say "$DEPLOY_SAID"; return 0
  fi
  if [ ! -e "$LIVE_WORKSPACE/.git" ]; then
    DEPLOY_SAID="there is no live workspace repository at $LIVE_WORKSPACE, so $short is on $TARGET and nothing here serves it"
    say "$DEPLOY_SAID"; return 0
  fi
  url=$(gq remote get-url "$REMOTE")
  mine=$(printf '%s' "$url" | sed -E 's#\.git$##; s#/$##')
  theirs=$(git -c "safe.directory=$LIVE_WORKSPACE" -C "$LIVE_WORKSPACE" remote get-url origin 2>/dev/null \
           | sed -E 's#\.git$##; s#/$##')
  if [ -n "$mine" ] && [ -n "$theirs" ] && [ "$mine" != "$theirs" ]; then
    DEPLOY_SAID="$url is not the workspace this machine serves, so $short is on $TARGET and the live workspace was not moved"
    say "$DEPLOY_SAID"; return 0
  fi
  [ -n "$DEPLOY_SCRIPT" ] || DEPLOY_SCRIPT="$DEPLOY_APP/update-all.sh"
  if [ ! -f "$DEPLOY_SCRIPT" ]; then
    DEPLOY_STATE="not-live"
    DEPLOY_SAID="there is no deploy script at $DEPLOY_SCRIPT to move the live workspace with, so $short is on $TARGET and not live"
    say "$DEPLOY_SAID"; return 0
  fi
  [ "$(id -u)" = "0" ] || argv+=(sudo -n)
  argv+=(env "ROUH_APP_DIR=$DEPLOY_APP" "ROUH_LAND_DIR=$LAND_DIR"
         "JARVIS_APP_DIR=$DEPLOY_APP" "JARVIS_LAND_DIR=$LAND_DIR"
         bash "$DEPLOY_SCRIPT" --to "$want" --workspace "$LIVE_WORKSPACE")
  out=$("${argv[@]}" 2>&1)
  code=$?
  if [ "$code" != 0 ]; then
    DEPLOY_STATE="not-live"
    DEPLOY_SAID="the live workspace could not be moved onto $short: $(printf '%s' "$out" | grep . | tail -n 1)"
    printf '%s\n' "$out" | sed 's/^/    /' >&2
    say "$DEPLOY_SAID"; return 0
  fi
  DEPLOYED="true"; DEPLOY_STATE="content"
  DEPLOY_SAID="the live workspace holds $short and nothing was restarted, because nothing runs what is in it"
  say "$DEPLOY_SAID"
  return 0
}

# Start the deploy and wait for the commit to be answering. Never fails the
# script: it sets the three variables above and every caller reports them.
deploy_it() {
  local want="$1" short="${1:0:7}" why dir log exitfile outcome code done_at now until_at
  local -a argv=()

  DEPLOYED="false"; DEPLOY_STATE="not-live"; DEPLOY_SAID=""; DEPLOY_DIR=""
  # Here and not inside `nothing_to_deploy`: that one is read through a command
  # substitution, so everything it sets it sets in a subshell of its own. It
  # cost a deploy to find out - the script was handed an empty path and said
  # "bash: : No such file or directory" - and the landing said plainly that the
  # commit was on main and not live, which is the one thing that went right.
  [ -n "$DEPLOY_SCRIPT" ] || DEPLOY_SCRIPT="$DEPLOY_APP/update-all.sh"

  # A workspace is never deployed: it is moved (`move_workspace`).
  if [ "$KIND" = "workspace" ]; then
    move_workspace "$want"
    return 0
  fi

  why=$(nothing_to_deploy)
  if [ -n "$why" ]; then
    DEPLOY_STATE="none"
    DEPLOY_SAID="$why, so $short is on $TARGET and not live"
    say "$DEPLOY_SAID"
    return 0
  fi

  if live "$want"; then
    # Somebody else's deploy already carried it, or this is a landing of work
    # that was on main and live before it ran. Pressing on would be a restart
    # for nothing.
    DEPLOYED="true"; DEPLOY_STATE="already"
    DEPLOY_SAID="both services were already serving $short"
    say "$DEPLOY_SAID"
    return 0
  fi

  # The content guard. Both ways out of it say which way it went and why,
  # because a rule that decides silently is a rule nobody can check.
  if only_content "$want"; then
    # The files still have to move. Nothing **runs** what is under
    # CONTENT_PATHS, which is why nothing is restarted, but Rouh **serves**
    # it: the task browser, every task's pages and the
    # Ask AI drawer's material are all read off `workspace/` in the checkout
    # Rouh is deployed in, on every request. A landing that moved nothing on
    # disk would put the person's own words on main and leave the screen
    # showing yesterday's, with every rung of this script saying it worked.
    if move_content "$want"; then
      DEPLOYED="true"; DEPLOY_STATE="content"
      DEPLOY_SAID="it needed no restart and both checkouts now hold $short: $CONTENT_WHY"
      say "not restarting anything for $short, and moving its files: $CONTENT_WHY"
      return 0
    fi
    # It could not be moved. That is not a reason to leave the work unserved:
    # the ordinary deploy moves the same files and restarts as well, which is a
    # restart nobody wanted rather than a change nobody can see.
    say "the files of $short could not be moved without a restart, so it is deploying"
    CONTENT_WHY="$CONTENT_MOVE_WHY"
  fi
  say "deploying $short: $CONTENT_WHY"

  # Sticky and world-writable, like the rest of this directory and for the same
  # reason: the users that land work here need not share a group, so
  # whichever of them made this folder first, the other still has to
  # be able to put its own deploy's record beside it.
  ( umask 000; mkdir -p "$LAND_DIR/deploys" ) 2>/dev/null
  chmod 1777 "$LAND_DIR/deploys" 2>/dev/null || true
  dir="$LAND_DIR/deploys/$(date -u +%Y%m%dT%H%M%SZ)-$RUN-$$"
  mkdir -p "$dir" 2>/dev/null || dir="$SCRATCH/deploy"
  mkdir -p "$dir" 2>/dev/null || {
    DEPLOY_SAID="nowhere to keep the deploy's own record, so $short was not deployed"
    say "$DEPLOY_SAID"; return 0; }
  chmod 777 "$dir" 2>/dev/null || true
  DEPLOY_DIR="$dir"
  log="$dir/log"; exitfile="$dir/exit"; outcome="$dir/outcome"
  : >"$log" 2>/dev/null || true

  # Root already, or root through sudo: the deploy restarts services and writes
  # into two checkouts nobody else owns. Both users that land work here may.
  [ "$(id -u)" = "0" ] || argv+=(sudo -n)
  # Detached, in a session of its own, because the deploy restarts the very
  # program that started this job.
  #
  # What it is told is said inside the command rather than exported, because
  # sudo throws an environment away and everything here can be pointed
  # somewhere else. A check of its own that aimed this at two throwaway
  # checkouts and then watched sudo drop them would have deployed the real
  # server, which is the one mistake this must not make possible.
  #
  # Its outcome goes to a file of this landing's own rather than to the one
  # Rouh reads for its deploy card: that card belongs to a deploy Rouh
  # started, and a sentence left in it by this one would be answering a
  # question nobody asked.
  argv+=(setsid --fork bash -c '
    ROUH_APP_DIR="$6" ROUH_LAND_DIR="$7" ROUH_UPDATE_OUTCOME="$4" \
    JARVIS_APP_DIR="$6" JARVIS_LAND_DIR="$7" JARVIS_UPDATE_OUTCOME="$4" \
      bash "$1" --to "$2" >>"$3" 2>&1
    printf "%s\n" "$?" >"$5"
  ' land-deploy "$DEPLOY_SCRIPT" "$want" "$log" "$outcome" "$exitfile" \
    "$DEPLOY_APP" "$LAND_DIR")

  say "deploying $short: the one program first, then Rouh"
  if ! "${argv[@]}" >>"$log" 2>&1; then
    DEPLOY_SAID="the deploy would not start: $(deploy_said "$outcome" "$log")"
    say "$DEPLOY_SAID"
    return 0
  fi

  done_at=""
  until_at=$(( $(date +%s) + DEPLOY_WAIT ))
  while : ; do
    if live "$want"; then
      DEPLOYED="true"; DEPLOY_STATE="deployed"
      DEPLOY_SAID="the one program and Rouh are both serving $short"
      say "deployed $short"
      return 0
    fi
    if [ -z "$done_at" ] && [ -s "$exitfile" ]; then
      code=$(tr -dc '0-9' <"$exitfile" 2>/dev/null)
      if [ "${code:-1}" != "0" ]; then
        DEPLOY_SAID="the deploy failed: $(deploy_said "$outcome" "$log")"
        say "$DEPLOY_SAID"
        say "the deploy's own record is in $dir"
        return 0
      fi
      # It says it worked and neither service is answering with the commit
      # yet. Give it the settling time and no more: a deploy that is done and
      # is not being served is a failure however cheerfully it exited.
      done_at=$(date +%s)
      until_at=$(( done_at + DEPLOY_SETTLE ))
    fi
    now=$(date +%s)
    [ "$now" -lt "$until_at" ] || break
    sleep 2
  done

  if [ -n "$done_at" ]; then
    DEPLOY_SAID="the deploy said it had finished and neither service is answering with $short: $(deploy_said "$outcome" "$log")"
  else
    DEPLOY_SAID="the deploy did not bring both services up on $short within ${DEPLOY_WAIT}s: $(deploy_said "$outcome" "$log")"
  fi
  say "$DEPLOY_SAID"
  say "the deploy's own record is in $dir"
  return 0
}

# The end of a landing that put work on the target: deploy it, then say in one
# sentence what became of it. Everything that reports landed work goes through
# this, so there is no path that can say "landed" without saying whether it is
# live.
landed_and() {
  local want="$1" state="$2" what="$3"; shift 3
  # The work is on the target, so every question this run raised on the way
  # is answered, before the deploy rather than after it: a collision it went
  # on to reconcile itself must not stay red (`conflicts.close_for_run`).
  if [ -n "$RUN" ] && [ -d "$LAND_DIR/conflicts" ]; then
    conflicts landed "$RUN" "$want" >/dev/null 2>&1 || true
  fi
  [ "$state" = "landed" ] && keep_landing
  deploy_it "$want"
  if [ "$DEPLOY_STATE" = "content" ]; then
    # Landed, and nothing needed restarting. Not a deploy that failed and not a
    # deploy that happened: the files are on both checkouts and every process
    # that was running is still the right one for them.
    say "$what, and $DEPLOY_SAID"
    finish 0 "state=$state" landed=true deployed=true "deploy=$DEPLOY_STATE" \
      "deploy_reason=$DEPLOY_SAID" "sha=$want" "$@" \
      "reason=$what, and $DEPLOY_SAID"
  fi
  if [ "$DEPLOYED" = "true" ]; then
    say "$what and deployed it: $DEPLOY_SAID"
    finish 0 "state=$state" landed=true deployed=true "deploy=$DEPLOY_STATE" \
      "deploy_reason=$DEPLOY_SAID" "deploy_log=$DEPLOY_DIR" "sha=$want" "$@" \
      "reason=$what and deployed it: $DEPLOY_SAID"
  fi
  say "$what, and it is NOT live: $DEPLOY_SAID"
  finish 13 "state=$state" landed=true deployed=false "deploy=$DEPLOY_STATE" \
    "deploy_reason=$DEPLOY_SAID" "deploy_log=$DEPLOY_DIR" "sha=$want" "$@" \
    "reason=$what, and it is NOT live: $DEPLOY_SAID"
}

# --------------------------------------------------------------------------
# Answering the person's pick
# --------------------------------------------------------------------------

find_record() {
  local want="$1" dir="$LAND_DIR/conflicts" f
  if [ -n "$want" ]; then
    [ -f "$want" ] && { printf '%s' "$want"; return 0; }
    [ -f "$dir/$want.json" ] && { printf '%s' "$dir/$want.json"; return 0; }
    return 1
  fi
  # The newest record for this run, which is the one just asked about.
  for f in $(ls -1t "$dir"/*.json 2>/dev/null); do
    if [ "$(record_field "$f" run)" = "$RUN" ]; then printf '%s' "$f"; return 0; fi
  done
  return 1
}

record_field() {
  [ -n "$PY" ] || return 1
  RECORD_PATH="$1" RECORD_KEY="$2" "$PY" - <<'PYEOF'
import json, os
try:
    with open(os.environ["RECORD_PATH"], encoding="utf-8") as fh:
        print(str(json.load(fh).get(os.environ["RECORD_KEY"]) or ""))
except Exception:
    print("")
PYEOF
}

mark_record() {
  [ -n "$PY" ] || return 0
  RECORD_PATH="$1" RECORD_STATE="$2" RECORD_EXTRA="${3:-}" \
  ROUH_LAND_DIR="$LAND_DIR" PYTHONPATH="$SELF_DIR${PYTHONPATH:+:$PYTHONPATH}" \
    "$PY" - <<'PYEOF'
import json, os
from rouh import conflicts
record = conflicts.read(os.environ["RECORD_PATH"])
if record is not None:
    extra = json.loads(os.environ["RECORD_EXTRA"] or "{}")
    conflicts.set_state(record, os.environ["RECORD_STATE"], **extra)
PYEOF
}

if [ -n "$ANSWER" ]; then
  RECORD=$(find_record "$CONFLICT") || fail "there is no conflict record here to answer"
  case "$ANSWER" in
    1) HOW="mine" ;;
    2) HOW="theirs" ;;
    3) HOW="both" ;;
    4) HOW="park" ;;
    *) fail "the answer has to be 1, 2, 3 or 4; $ANSWER is not one of them" ;;
  esac
  PRE=$(record_field "$RECORD" pre_branch)
  RID=$(record_field "$RECORD" id)
  say "answer $ANSWER ($HOW) to conflict $RID"

  if [ "$HOW" = "park" ]; then
    mark_record "$RECORD" parked '{"choice": 4, "choice_how": "park"}'
    say "parked. Nothing moved, and $PRE still holds the work as the job wrote it"
    finish 12 state=parked landed=false "conflict=$RID" "pre_branch=$PRE" \
      "reason=the person parked it; nothing moved and the work is kept on $PRE"
  fi

  if [ "$HOW" = "both" ]; then
    # Back to the worker: the only thing that can reconcile two intents, and
    # the only thing that can prove the result in a browser afterwards.
    HB=$(tmpfile handback.txt)
    conflicts handback "$RECORD" 3 >"$HB" 2>/dev/null \
      || printf 'Reconcile both sides yourself, keeping both intents, and run ./land.sh again.\n' >"$HB"
    mark_record "$RECORD" answered '{"choice": 3, "choice_how": "both"}'
    say "handed back to the worker to merge both sides"
    finish 10 state=handback landed=false "conflict=$RID" "pre_branch=$PRE" \
      "handback=@$HB" "reason=the person chose to merge both sides, so it is back with the worker"
  fi

  # 1 and 2 are both a replay with one side preferred, starting again from the
  # work exactly as the job wrote it.
  #
  # Which way round -X goes is the one thing here that is easy to get backwards.
  # A rebase checks the target out first and replays your commits onto it, so
  # inside each replayed merge "ours" is the target and "theirs" is your own
  # commit. Taking mine is therefore -X theirs, and taking main's is -X ours.
  STRATEGY="theirs"; [ "$HOW" = "theirs" ] && STRATEGY="ours"

  take_the_lock
  fetch_target || fail "could not fetch $TARGET_REF, so nothing was replayed"
  if [ -n "$PRE" ] && gq rev-parse --verify -q "refs/heads/$PRE" >/dev/null; then
    say "starting again from $PRE, the work as the job wrote it"
    move_to "$PRE" || true
  fi
  ERR=$(GIT_EDITOR=true g rebase -q --empty=drop -X "$STRATEGY" "$TARGET_REF" 2>&1)
  if [ "$?" != "0" ]; then
    g rebase --abort 2>/dev/null
    mark_record "$RECORD" waiting '{"choice": null}'
    say "even taking one side outright would not replay: $ERR"
    finish 11 state=needs-person landed=false "conflict=$RID" "pre_branch=$PRE" \
      "reason=taking one side outright still would not replay, so it is back with you. $(printf '%s' "$ERR" | tr '\n' ' ' | cut -c1-300)"
  fi
  AHEAD=$(gq rev-list --count "$TARGET_REF..HEAD" | tr -d ' ')
  if [ "${AHEAD:-0}" = "0" ]; then
    mark_record "$RECORD" landed "{\"choice\": $ANSWER}"
    say "nothing of the job's work is left over $TARGET: main's version stands"
    finish 0 state=landed landed=false already=true "conflict=$RID" "pre_branch=$PRE" \
      "sha=$(gq rev-parse "$TARGET_REF")" "answered=$ANSWER" \
      "reason=main's version stands; the job's own work is kept on $PRE"
  fi
  FILES_FILE=$(tmpfile files.txt)
  gq diff --name-only "$TARGET_REF..HEAD" >"$FILES_FILE" 2>/dev/null || : >"$FILES_FILE"
  if [ "$NO_PUSH" = "1" ]; then
    # The replay is done and the checkout holds the resolved work on top of the
    # target. Nothing is pushed, because the person picking a side is not the
    # same as anybody having seen the result work: the worker proves it in a
    # browser and then runs land.sh with nothing after it, which pushes.
    mark_record "$RECORD" answered "{\"choice\": $ANSWER, \"replayed\": true}"
    say "replayed, not pushed. Prove it, then run land.sh again to push it"
    finish 0 state=replayed landed=false "conflict=$RID" "pre_branch=$PRE" \
      "answered=$ANSWER" "sha=$(gq rev-parse HEAD)" "files=lines@$FILES_FILE" \
      "reason=replayed onto $TARGET and not pushed, as asked"
  fi
  secrets_guard
  numbers_guard
  types_guard
  mail_guard
  llm_guard
  host_guard
  genes_guard
  owners_guard
  design_guard
  signals_guard
  note_landing
  ERR=$(g push -q "$REMOTE" "HEAD:$TARGET" 2>&1)
  if [ "$?" != "0" ]; then
    finish 1 state=error landed=false "conflict=$RID" \
      "reason=the replay worked and the push was refused: $(printf '%s' "$ERR" | tr '\n' ' ' | cut -c1-200)"
  fi
  SHA=$(gq rev-parse HEAD)
  mark_record "$RECORD" landed "{\"choice\": $ANSWER, \"sha\": \"$SHA\"}"
  say "landed on $TARGET at $(printf '%s' "$SHA" | cut -c1-7)"
  landed_and "$SHA" landed \
    "landed on $TARGET at $(printf '%s' "$SHA" | cut -c1-7) after the person chose $ANSWER" \
    "conflict=$RID" "pre_branch=$PRE" "answered=$ANSWER" \
    "files=lines@$FILES_FILE"
fi

# Fitting only (ROUH_LAND_FIT_ONLY): the target is a scratch repository holding
# the code that runs, and the protected core's own checks come after, so the
# checks before a push, which need the server's own Python, are not run here.
if [ "$(setting ROUH_LAND_FIT_ONLY 0)" = "1" ]; then
  STACK_GUARD="0"
  numbers_guard() { :; }; types_guard() { :; }; mail_guard() { :; }; llm_guard() { :; }; host_guard() { :; }
  genes_guard() { :; }; owners_guard() { :; }; signals_guard() { :; }; design_guard() { :; }
  # Nor the record of collisions Rouh keeps: that is Rouh's Python, and the worker is not Rouh.
  conflicts() { return 0; }
fi

# --------------------------------------------------------------------------
# The ordinary landing
# --------------------------------------------------------------------------

stack_guard
take_the_lock
fetch_target || fail "could not reach $REMOTE, so nothing was landed"

BASE=$(gq merge-base HEAD "$TARGET_REF" | tr -d ' ')
[ -n "$BASE" ] || carry_over || finish 1 state=error landed=false \
  "reason=this branch shares no history with $TARGET"
HEAD_SHA=$(gq rev-parse HEAD)

# What the branch was made from, when the caller knows. It is the difference
# between two things that both look like "no commits to replay": a job that
# committed nothing, and a job whose commits reached the target already, which
# is what "nothing new to land" used to be said about. The first is an answer
# with no change in it; the second is work that is live and must be reported as
# landed, or the deploy that follows a landed change never happens.
COUNT_FROM="$BASE"
if [ -n "$FROM" ] && gq rev-parse --verify -q "$FROM^{commit}" >/dev/null; then
  COUNT_FROM=$(gq rev-parse "$FROM^{commit}")
fi

COMMITS=$(gq rev-list --count "$BASE..HEAD" | tr -d ' ')
if [ "${COMMITS:-0}" = "0" ]; then
  WROTE_SOMETHING=$(gq rev-list --count "$COUNT_FROM..HEAD" | tr -d ' ')
  if [ "${WROTE_SOMETHING:-0}" != "0" ]; then
    say "already on $TARGET as $(printf '%s' "$HEAD_SHA" | cut -c1-7); its own commits are there"
    landed_and "$HEAD_SHA" already \
      "already on $TARGET as $(printf '%s' "$HEAD_SHA" | cut -c1-7)" \
      already=true "commits=$WROTE_SOMETHING"
  fi
  say "nothing new to land"
  finish 0 state=nothing landed=false deployed=false commits=0 \
    "reason=nothing new to land, so nothing was pushed and nothing was deployed"
fi

OWN=$(gq diff --name-only "$BASE..HEAD" | awk -F/ '$1 == ".one" || $1 == ".rouh"')
if [ -n "$OWN" ]; then
  finish 1 state=error landed=false \
    "reason=its commits include a run's own files ($(printf '%s' "$OWN" | tr '\n' ' ' | cut -c1-120)), so nothing was pushed"
fi

# ---- step 1: is it already there, by patch? ------------------------------
#
# `git cherry` marks a commit `-` when the target already holds one with the
# same patch id, whatever its sha, its message or its author date. That is all
# a retried job that already landed needs, and what comparing text cannot do.

NEW_COMMITS=""
OLD_COMMITS=""
while read -r mark sha; do
  case "$mark" in
    +) NEW_COMMITS="${NEW_COMMITS}${sha} " ;;
    -) OLD_COMMITS="${OLD_COMMITS}${sha} " ;;
  esac
done < <(gq cherry "$TARGET_REF" HEAD || true)

if [ -z "$NEW_COMMITS" ] && [ -n "$OLD_COMMITS" ]; then
  # Where on the target the same patch already sits, so this names the commit
  # rather than merely claiming it.
  LAST=$(printf '%s' "$OLD_COMMITS" | awk '{print $NF}')
  WANT=$(gq diff-tree -p --no-color "$LAST" | gq patch-id --stable | cut -d' ' -f1)
  THERE=""
  if [ -n "$WANT" ]; then
    for u in $(gq rev-list "$BASE..$TARGET_REF"); do
      if [ "$(gq diff-tree -p --no-color "$u" | gq patch-id --stable | cut -d' ' -f1)" = "$WANT" ]; then
        THERE="$u"; break
      fi
    done
  fi
  [ -n "$THERE" ] || THERE=$(gq rev-parse "$TARGET_REF")
  # Kept before the duplicates are dropped. Nothing is ever discarded, and
  # "already landed" is a resolution like any other, so it gets a branch too.
  KEEP="land/dropped/$RUN/$(date +%s)"
  g branch -q -f "$KEEP" "$HEAD_SHA" 2>/dev/null || KEEP=""
  move_to "$TARGET_REF" || true
  say "already on $TARGET as $(printf '%s' "$THERE" | cut -c1-7)${KEEP:+; the duplicate is kept on $KEEP}"
  landed_and "$THERE" already \
    "already on $TARGET as $(printf '%s' "$THERE" | cut -c1-7)" \
    already=true "commits=$COMMITS" "dropped=$KEEP"
fi

DROPPED=$(printf '%s' "$OLD_COMMITS" | wc -w | tr -d ' ')
if [ "${DROPPED:-0}" != "0" ]; then
  say "$DROPPED of its commits are already on $TARGET by patch; the replay drops them"
fi

# ---- steps 3 and 4: the replay -------------------------------------------
#
# Unless there is nothing to replay. If the target is already an ancestor of
# this branch then nobody has landed anything since it was made, the work sits
# directly on top of the target, and a push is a fast-forward. Replaying it
# would rewrite every commit for no reason at all.
#
# It is worse than waste for a branch holding a merge. A rebase flattens: it
# takes the commits reachable from HEAD and lays them down one after another,
# and a merge does not survive that. A branch that merges in another history
# would be replayed linearly, the merges inside it reproduced out of the
# context that resolved them, and it would collide with itself - against a main
# that had not moved by a single commit. Nothing would be wrong with the work
# and nothing would have landed to collide with; the replay invents the conflict.
#
# So the ladder gets a rung before its first one: nothing to replay, push what
# is here. Everything below is for a branch that really has fallen behind.

if gq merge-base --is-ancestor "$TARGET_REF" HEAD >/dev/null 2>&1; then
  say "$TARGET has not moved since this branch was made, so there is nothing to replay"
  FILES_FILE=$(tmpfile files.txt)
  gq diff --name-only "$BASE..HEAD" >"$FILES_FILE" 2>/dev/null || : >"$FILES_FILE"
  SHA=$(gq rev-parse HEAD)
  secrets_guard
  numbers_guard
  types_guard
  mail_guard
  llm_guard
  host_guard
  genes_guard
  owners_guard
  design_guard
  signals_guard
  note_landing
  ERR=$(g push -q "$REMOTE" "HEAD:$TARGET" 2>&1)
  if [ "$?" = "0" ]; then
    say "landed on $TARGET at $(printf '%s' "$SHA" | cut -c1-7)"
    landed_and "$SHA" landed \
      "landed on $TARGET at $(printf '%s' "$SHA" | cut -c1-7)" \
      "commits=$COMMITS" "files=lines@$FILES_FILE" fast_forward=true
  fi
  # Somebody landed between the fetch and the push. Fall through: the replay
  # below is exactly what that case needs.
  say "the fast-forward push was refused, so it is fetched and replayed: $(printf '%s' "$ERR" | tr '\n' ' ' | cut -c1-160)"
  fetch_target || fail "could not reach $REMOTE, so nothing was landed"
fi

ATTEMPT=$(( $(gq for-each-ref --format='%(refname)' "refs/heads/land/pre/$RUN/" | wc -l | tr -d ' ') + 1 ))
say "attempt $ATTEMPT, replaying $COMMITS commit(s) onto $TARGET_REF"

ASIDE=""
[ "$AUTOSTASH" = "1" ] && ASIDE="--autostash"

# rerere can resolve the whole of a conflict it has seen before, which stages
# the files and leaves the rebase waiting to be continued. Continuing it is what
# makes "resolved once, resolved for ever" true rather than a setting nobody
# ever benefits from, so the replay is a loop: stop, take every generated file
# as the target has it, ask whether anything is really still unmerged, continue
# when nothing is.

# Whether a path is one a program makes rather than anybody (GENERATED_PATHS).
is_generated() {
  local f="$1" p
  for p in $GENERATED_PATHS; do
    # shellcheck disable=SC2254
    case "$f" in $p) return 0 ;; esac
  done
  return 1
}

unmerged() { gq diff --name-only --diff-filter=U; }

# Whether a path is notes kept by adding to them (UNION_PATHS).
is_union() {
  local f="$1" p
  for p in $UNION_PATHS; do
    # shellcheck disable=SC2254
    case "$f" in $p) return 0 ;; esac
  done
  return 1
}

# Every colliding notes file, with both sides kept: what each side added, one
# after the other, as git's union merge writes it. Only where both sides still
# have the file; a deletion on either side is a real collision and goes on up
# the ladder.
take_union() {
  local f base ours theirs
  while IFS= read -r f; do
    [ -n "$f" ] || continue
    is_union "$f" || continue
    base=$(tmpfile union.base); ours=$(tmpfile union.ours); theirs=$(tmpfile union.theirs)
    gq show ":1:$f" >"$base" || : >"$base"
    gq show ":2:$f" >"$ours" || continue
    gq show ":3:$f" >"$theirs" || continue
    gq merge-file --union -p "$ours" "$base" "$theirs" >"$REPO/$f"
    gq add -- "$f" || continue
    say "$f is notes kept by adding to them, so both sides are kept"
  done < <(unmerged)
}

# Whether settling a clash by dropping one side would lose words the person
# wrote themselves: that side carries a commit of Rouh's saver, which is how an
# edit they made in place - a page, a task's notes - reaches main
# (rouh/saving.py). The task list it saves is generated, and is not their words.
# $1 is the side dropped: "mine" (the job's) or "theirs" (main's). Every other
# clash Rouh settles itself.
drops_his_words() {
  local range
  if [ "$1" = "mine" ]; then range="$BASE..$HEAD_SHA"; else range="$BASE..$TARGET_REF"; fi
  gq log --format=%s "$range" -- $(tr '\n' ' ' <<<"$CONFLICTED") \
    | grep -E '^workspace: Rouh saves' | grep -vq 'the task list, made again out of the database$'
}

# Take one side of every colliding file: "ours" is main with the job's commits
# replayed so far, "theirs" the job's commit being replayed.
take_side() {
  local side="$1" f
  while IFS= read -r f; do
    [ -n "$f" ] || continue
    if gq checkout "--$side" -- "$f"; then
      gq add -- "$f"
    else
      gq rm -q -- "$f" >/dev/null
    fi
  done < <(unmerged)
}

# Every colliding generated file, taken as the target has it. In a rebase
# "ours" is the target with this branch's commits replayed so far, so that is
# --ours. Where the target deleted it, it goes. Whatever made it makes it again
# from its own source of truth, which for the task list is Rouh's saver.
take_generated() {
  local f
  while IFS= read -r f; do
    [ -n "$f" ] || continue
    is_generated "$f" || continue
    if gq checkout --ours -- "$f"; then
      gq add -- "$f"
    else
      gq rm -q -- "$f" >/dev/null
    fi
    say "$f is generated, so it is taken as $TARGET has it and made again afterwards"
  done < <(unmerged)
}

# Carry the stopped rebase on as far as it goes by itself. 0 when it finished;
# 1 when it is stopped at a collision somebody still has to resolve, with
# CONFLICTED naming the files; 2 when it is stopped for any other reason.
carry_on() {
  local rounds=0
  while [ "$rounds" -lt 60 ]; do
    rounds=$(( rounds + 1 ))
    take_generated
    take_union
    CONFLICTED=$(unmerged)
    [ -z "$CONFLICTED" ] || return 1
    gq rev-parse --verify -q REBASE_HEAD >/dev/null || return 2
    if gq diff --cached --quiet; then
      # The resolution left nothing of this commit, which is how a commit that
      # only touched a generated file ends. It is dropped, as --empty=drop does.
      ERR=$(GIT_EDITOR=true g rebase --skip 2>&1); RC="$?"
    else
      ERR=$(GIT_EDITOR=true g rebase --continue 2>&1); RC="$?"
    fi
    [ "$RC" = "0" ] && return 0
    GIT_SAID="$ERR"
  done
  return 2
}

CONFLICTED=""
GIT_SAID=""
REPLAYED="0"
RID=""
ERR=$(GIT_EDITOR=true g rebase -q --empty=drop $ASIDE "$TARGET_REF" 2>&1); RC="$?"
if [ "$RC" = "0" ]; then
  REPLAYED="1"
else
  GIT_SAID="$ERR"
  carry_on; CARRIED="$?"
  [ "$CARRIED" = "0" ] && REPLAYED="1"
fi

if [ "$REPLAYED" = "0" ] && [ -z "$CONFLICTED" ]; then
  # Stopped, and not one file collides: git refused for some other reason. That
  # is not a question for anybody, and it is said with git's own words.
  g rebase --abort 2>/dev/null
  WHY=$(printf '%s' "$GIT_SAID" | grep -v '^hint:' | tr '\n' ' ' | sed 's/  */ /g' | cut -c1-300)
  fail "the replay onto $TARGET_REF stopped without any file colliding, so nothing was pushed and nobody was asked: $WHY"
fi

MERGED="0"
MERGE_OUT=$(tmpfile merge.json); : >"$MERGE_OUT"
MERGE_WHY=""
#: What Rouh settled itself where the two sides wanted opposite things, a line
#: each, for the record and the job's report; and why one clash is the
#: person's after all.
SETTLED_FILE=$(tmpfile settled.txt); : >"$SETTLED_FILE"
HIS_WORDS=""

if [ "$REPLAYED" = "0" ]; then
  # A real conflict. Everything below is about losing nothing, and about telling
  # somebody the truth about it.
  CONF_FILE=$(tmpfile conflicted.txt)
  printf '%s\n' "$CONFLICTED" | sed '/^$/d' >"$CONF_FILE"
  PRE="land/pre/$RUN/$ATTEMPT"
  g branch -q -f "$PRE" "$HEAD_SHA" 2>/dev/null \
    || { say "could not keep $PRE; the work is on $BRANCH at $(printf '%s' "$HEAD_SHA" | cut -c1-7)"; PRE="$BRANCH"; }
  say "the replay collides in: $(tr '\n' ' ' <"$CONF_FILE")"
  say "the work as the job wrote it is kept on $PRE"

  # Did both sides rewrite the same thing? Measured rather than guessed: for
  # each colliding file, how much of the version they both started from each
  # side changed. Two rewrites of one file are not a collision to hand back
  # for a quick fix: they go straight to Rouh's merge pass, which reads both
  # intents whole and keeps both, or says plainly that they cannot both hold.
  #
  # A small file is left out of the half rule on purpose. Half of a three-line
  # file is one line, so every collision in a short file would read as two
  # rewrites. Below this many lines a collision is a collision and the worker
  # that wrote it gets it back first.
  REWRITE_FLOOR=20
  BOTH_REWROTE="false"
  while IFS= read -r f; do
    [ -n "$f" ] || continue
    base_lines=$(gq show "$BASE:$f" | wc -l | tr -d ' ')
    mine_n=$(gq diff --numstat "$BASE" "$HEAD_SHA" -- "$f" | awk '{print $1+$2}')
    theirs_n=$(gq diff --numstat "$BASE" "$TARGET_REF" -- "$f" | awk '{print $1+$2}')
    base_lines=${base_lines:-0}; mine_n=${mine_n:-0}; theirs_n=${theirs_n:-0}
    if [ "$base_lines" = "0" ] && [ "$mine_n" -gt 0 ] && [ "$theirs_n" -gt 0 ]; then
      BOTH_REWROTE="true"; break        # neither had it: both wrote it from nothing
    fi
    [ "$base_lines" -ge "$REWRITE_FLOOR" ] || continue
    half=$(( base_lines / 2 ))
    if [ "$mine_n" -ge "$half" ] && [ "$theirs_n" -ge "$half" ]; then
      BOTH_REWROTE="true"; break
    fi
  done <"$CONF_FILE"

  # Rung 4: the worker that wrote the code gets it back. Rung 6: twice failed,
  # or both sides rewrote the same thing, and Rouh merges it itself.
  STATE="handback"
  if [ "$ATTEMPT" -ge 2 ] || [ "$BOTH_REWROTE" = "true" ] || [ "$MERGE" = "1" ]; then
    STATE="merge"
  fi
  if [ "$STATE" = "merge" ] && { [ "$MERGE_PASS" = "0" ] || [ -z "$PY" ]; }; then
    MERGE_WHY="Rouh's merge pass is switched off here"
    STATE="handback"
  fi

  if [ "$STATE" = "merge" ]; then
    say "Rouh is merging it itself, keeping both sides' intent"
    BRIEF_ARG=$(tmpfile brief-for-merge.txt)
    printf '%s' "$BRIEF" >"$BRIEF_ARG"
    MERGE_ROUNDS=0
    while :; do
      MERGE_ROUNDS=$(( MERGE_ROUNDS + 1 ))
      SAID=$(PYTHONPATH="$SELF_DIR${PYTHONPATH:+:$PYTHONPATH}" ROUH_LAND_DIR="$LAND_DIR" \
        "$PY" -m rouh.merge_pass --repo "$REPO" --base "$BASE" --head "$HEAD_SHA" \
          --target-ref "$TARGET_REF" --brief-file "$BRIEF_ARG" --beside "$BESIDE" \
          --land-dir "$LAND_DIR" 2>/dev/null | tail -n 1)
      printf '%s' "$SAID" >"$MERGE_OUT"
      OUTCOME=$(SAID_JSON="$SAID" "$PY" -c 'import json,os
try: print(json.loads(os.environ["SAID_JSON"]).get("outcome") or "failed")
except Exception: print("failed")')
      if [ "$OUTCOME" != "merged" ]; then
        MERGE_WHY=$(SAID_JSON="$SAID" "$PY" -c 'import json,os
try: print(json.loads(os.environ["SAID_JSON"]).get("why") or "")
except Exception: print("it said nothing readable")')
      fi
      if [ "$OUTCOME" = "opposite" ]; then
        # The two sides want opposite things. Rouh settles that too, on its own
        # merge pass's recommendation, and says what it kept and why in the
        # job's report. The one clash it never settles is one that would drop
        # words the person wrote themselves.
        PICK=$(SAID_JSON="$SAID" "$PY" -c 'import json,os
try: print(int(json.loads(os.environ["SAID_JSON"]).get("recommend") or 2))
except Exception: print(2)')
        PICK_WHY=$(SAID_JSON="$SAID" "$PY" -c 'import json,os
try: print(json.loads(os.environ["SAID_JSON"]).get("recommend_why") or "")
except Exception: print("")')
        if [ "$PICK" = "1" ]; then DROP="theirs"; SIDE="theirs"; KEPT="the job's"
        else DROP="mine"; SIDE="ours"; KEPT="main's"; fi
        if drops_his_words "$DROP"; then
          g rebase --abort 2>/dev/null
          STATE="waiting"
          HIS_WORDS="Keeping $KEPT side of $(tr '\n' ' ' <<<"$CONFLICTED" | sed 's/ *$//') would drop words you wrote yourself, which Rouh saved from your own edit, and the two sides want opposite things: $MERGE_WHY"
          say "the two sides want opposite things, and one holds the owner's own words: $MERGE_WHY"
          break
        fi
        take_side "$SIDE"
        printf 'kept %s side of %s, because %s\n' "$KEPT" "$(tr '\n' ' ' <<<"$CONFLICTED" | sed 's/ *$//')" \
          "${PICK_WHY:-$MERGE_WHY}" >>"$SETTLED_FILE"
        say "the two sides want opposite things, so Rouh kept $KEPT side: ${PICK_WHY:-$MERGE_WHY}"
      elif [ "$OUTCOME" != "merged" ]; then
        g rebase --abort 2>/dev/null
        STATE="handback"
        say "Rouh's merge pass could not finish: $MERGE_WHY"
        break
      else
        say "Rouh merged $(tr '\n' ' ' <<<"$CONFLICTED")"
      fi
      # Staged by the merge pass; carry on, which may stop at the next commit.
      if gq diff --cached --quiet; then
        ERR=$(GIT_EDITOR=true g rebase --skip 2>&1); RC="$?"
      else
        ERR=$(GIT_EDITOR=true g rebase --continue 2>&1); RC="$?"
      fi
      if [ "$RC" = "0" ]; then MERGED="1"; break; fi
      GIT_SAID="$ERR"
      carry_on; CARRIED="$?"
      if [ "$CARRIED" = "0" ]; then MERGED="1"; break; fi
      if [ "$CARRIED" = "2" ] || [ "$MERGE_ROUNDS" -ge 20 ]; then
        MERGE_WHY="the replay stopped again after the merge: $(printf '%s' "$GIT_SAID" | grep -v '^hint:' | tr '\n' ' ' | cut -c1-200)"
        printf '{"outcome": "failed"}' >"$MERGE_OUT"
        g rebase --abort 2>/dev/null
        STATE="handback"
        say "$MERGE_WHY"
        break
      fi
      printf '%s\n' "$CONFLICTED" | sed '/^$/d' >>"$CONF_FILE"
      say "the next commit collides too, in: $(tr '\n' ' ' <<<"$CONFLICTED")"
    done
    [ "$MERGED" = "1" ] && STATE="merged"
  else
    g rebase --abort 2>/dev/null
  fi
  sort -u -o "$CONF_FILE" "$CONF_FILE"

  # The record says what happened whichever way it went. Merged by Rouh, it is
  # written as handed back - nobody's question - and the landing below closes
  # it as landed the moment the work is on the target.
  RECORD_STATE="$STATE"
  [ "$STATE" = "merged" ] && RECORD_STATE="handback"

  [ -n "$PY" ] || finish 11 state=needs-person landed=false "pre_branch=$PRE" \
    "reason=the replay collides and there is no python3 here to write the record with"

  # Both sides, whole, for the record and for whoever reads it next. Every value
  # reaches python through a file or the environment, never interpolated into
  # its source: a commit message with a quote in it would otherwise be a syntax
  # error in the middle of writing down a conflict.
  MINE_DIFF=$(tmpfile mine.diff);    THEIRS_DIFF=$(tmpfile theirs.diff)
  MINE_MSGS=$(tmpfile mine.msgs);    THEIRS_MSGS=$(tmpfile theirs.msgs)
  MINE_FILES=$(tmpfile mine.files);  THEIRS_FILES=$(tmpfile theirs.files)
  SAID_FILE=$(tmpfile git.said);     BRIEF_FILE=$(tmpfile brief.txt)
  PARTS=$(tmpfile parts.json)
  mapfile -t CONF_ARR <"$CONF_FILE"
  gq diff "$BASE..$HEAD_SHA" -- "${CONF_ARR[@]}" >"$MINE_DIFF" || : >"$MINE_DIFF"
  gq diff "$BASE..$TARGET_REF" -- "${CONF_ARR[@]}" >"$THEIRS_DIFF" || : >"$THEIRS_DIFF"
  gq log --format=%s "$BASE..$HEAD_SHA" >"$MINE_MSGS" || : >"$MINE_MSGS"
  gq log --format=%s "$BASE..$TARGET_REF" -- "${CONF_ARR[@]}" >"$THEIRS_MSGS" || : >"$THEIRS_MSGS"
  gq diff --name-only "$BASE..$HEAD_SHA" >"$MINE_FILES" || : >"$MINE_FILES"
  gq diff --name-only "$BASE..$TARGET_REF" >"$THEIRS_FILES" || : >"$THEIRS_FILES"
  printf '%s\n' "$GIT_SAID" >"$SAID_FILE"
  printf '%s' "$BRIEF" >"$BRIEF_FILE"

  L_ID="cf-$RUN-$ATTEMPT" L_RUN="$RUN" L_TITLE="$TITLE" L_REPO="$REPO" L_BRANCH="$BRANCH" \
  L_TARGET="$TARGET" L_TARGET_REF="$TARGET_REF" L_BASE="$BASE" L_HEAD="$HEAD_SHA" \
  L_ATTEMPT="$ATTEMPT" L_PRE="$PRE" L_BOTH="$BOTH_REWROTE" L_STATE="$RECORD_STATE" \
  L_LAND="$SELF_DIR/land.sh" L_BESIDE="$BESIDE" L_PARTS="$PARTS" \
  L_CONF="$CONF_FILE" L_MINE_DIFF="$MINE_DIFF" L_THEIRS_DIFF="$THEIRS_DIFF" \
  L_MINE_MSGS="$MINE_MSGS" L_THEIRS_MSGS="$THEIRS_MSGS" L_MINE_FILES="$MINE_FILES" \
  L_THEIRS_FILES="$THEIRS_FILES" L_SAID="$SAID_FILE" L_BRIEF="$BRIEF_FILE" \
  L_MERGE="$MERGE_OUT" L_SETTLED="$SETTLED_FILE" L_HIS_WORDS="$HIS_WORDS" \
    "$PY" - <<'PYEOF'
import json, os

def lines(key):
    try:
        with open(os.environ[key], encoding="utf-8", errors="replace") as fh:
            return [l.rstrip("\n") for l in fh if l.strip()]
    except OSError:
        return []

def text(key):
    try:
        with open(os.environ[key], encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return ""

brief = text("L_BRIEF").strip()
parts = {
    "id": os.environ["L_ID"],
    "run": os.environ["L_RUN"],
    "title": (brief.splitlines()[0][:120] if brief else os.environ["L_TITLE"]),
    "repo": os.environ["L_REPO"],
    "cwd": os.environ["L_REPO"],
    "branch": os.environ["L_BRANCH"],
    "target": os.environ["L_TARGET"],
    "target_ref": os.environ["L_TARGET_REF"],
    "base": os.environ["L_BASE"],
    "head": os.environ["L_HEAD"],
    "attempt": int(os.environ["L_ATTEMPT"]),
    "pre_branch": os.environ["L_PRE"],
    "files": lines("L_CONF"),
    "both_rewrote": os.environ["L_BOTH"] == "true",
    "git_said": text("L_SAID"),
    "land": os.environ["L_LAND"],
    "state": os.environ["L_STATE"],
    "brief": brief,
    "beside": os.environ["L_BESIDE"] or None,
    "mine": {"diff": text("L_MINE_DIFF"), "messages": lines("L_MINE_MSGS"),
             "files": lines("L_MINE_FILES")},
    "theirs": {"diff": text("L_THEIRS_DIFF"), "messages": lines("L_THEIRS_MSGS"),
               "files": lines("L_THEIRS_FILES")},
}
# What Rouh's own merge pass made of it, when it ran: merged, opposite (with
# its recommendation) or could not finish.
try:
    with open(os.environ["L_MERGE"], encoding="utf-8") as fh:
        merged = json.loads(fh.read() or "{}")
except (OSError, ValueError, KeyError):
    merged = {}
if isinstance(merged, dict) and merged.get("outcome"):
    parts["rouh_merge"] = merged
    if merged.get("outcome") == "opposite":
        parts["opposite_why"] = merged.get("why") or ""
        parts["recommend"] = merged.get("recommend")
        parts["recommend_why"] = merged.get("recommend_why") or ""
# What Rouh settled itself, and the one reason a clash is the person's.
settled = lines("L_SETTLED")
if settled:
    parts["rouh_settled"] = settled
if os.environ.get("L_HIS_WORDS"):
    parts["needs_person"] = "his_words"
    parts["his_words_why"] = os.environ["L_HIS_WORDS"]
with open(os.environ["L_PARTS"], "w", encoding="utf-8") as fh:
    json.dump(parts, fh)
PYEOF

  WROTE=$(conflicts write <"$PARTS")
  if [ -z "$WROTE" ]; then
    finish 11 state=needs-person landed=false "pre_branch=$PRE" \
      "reason=the replay collides and the record could not be written"
  fi
  QUESTION=$(WROTE_JSON="$WROTE" "$PY" -c 'import json,os;print(json.loads(os.environ["WROTE_JSON"]).get("question") or "")')
  RID=$(WROTE_JSON="$WROTE" "$PY" -c 'import json,os;print(json.loads(os.environ["WROTE_JSON"]).get("id") or "")')
  HB=$(tmpfile handback.txt)
  WROTE_JSON="$WROTE" "$PY" -c 'import json,os,sys;sys.stdout.write(json.loads(os.environ["WROTE_JSON"]).get("handback") or "")' >"$HB"

  if [ "$STATE" = "waiting" ]; then
    RECOMMEND=$(SAID_JSON="$(cat "$MERGE_OUT")" "$PY" -c 'import json,os
try: print(json.loads(os.environ["SAID_JSON"]).get("recommend") or "")
except Exception: print("")')
    say "this one needs the person: $QUESTION${RECOMMEND:+ Rouh recommends $RECOMMEND.}"
    finish 11 state=needs-person landed=false "conflict=$RID" "pre_branch=$PRE" \
      "question=$QUESTION" "attempt=$ATTEMPT" "both_rewrote=$BOTH_REWROTE" \
      "files=lines@$CONF_FILE" "recommend=$RECOMMEND" \
      "reason=it collides with $TARGET in a way only the person can decide: $QUESTION"
  fi
  if [ "$STATE" = "handback" ]; then
    say "handing it back to the worker that wrote it"
    finish 10 state=handback landed=false "conflict=$RID" "pre_branch=$PRE" \
      "question=$QUESTION" "attempt=$ATTEMPT" "handback=@$HB" \
      "files=lines@$CONF_FILE" "merge_failed=$MERGE_WHY" \
      "reason=it collides with $TARGET, so it is back with the worker that wrote it${MERGE_WHY:+, because Rouh could not merge it itself: $MERGE_WHY}. Its work is kept on $PRE"
  fi
  say "merged by Rouh; it goes on to the checks and the push like any other work"
fi

# ---- the check, for a repository that has one ----------------------------

if [ -n "$CHECK" ]; then
  say "running the check: $CHECK"
  if ! ( cd "$REPO" && eval "$CHECK" >&2 ); then
    finish 1 state=error landed=false \
      "reason=the replay worked and the check did not: $CHECK"
  fi
fi

# ---- the push -------------------------------------------------------------

# What the push changes on the target, which is the work's own and nothing
# else: HEAD against the target it was replayed onto, never against `$BASE`.
# After a replay `$BASE..HEAD` also holds everything that landed on the target
# meanwhile, and Rouh reads this list as what the run made
# (`conversations.adopt_made_task`): on 30 October 2026 a run landed over
# Rouh's own save of a new task, was taken to have made it, and its chat, a
# fork of another task's chat, became the new task's chat.
FILES_FILE=$(tmpfile files.txt)
gq diff --name-only "$TARGET_REF..HEAD" >"$FILES_FILE" || : >"$FILES_FILE"
SHA=$(gq rev-parse HEAD)
PUSH_ERR=""
for try in 1 2 3; do
  secrets_guard
  numbers_guard
  types_guard
  mail_guard
  llm_guard
  host_guard
  genes_guard
  owners_guard
  design_guard
  signals_guard
  note_landing
  PUSH_ERR=$(g push -q "$REMOTE" "HEAD:$TARGET" 2>&1)
  if [ "$?" = "0" ]; then
    WHAT="landed on $TARGET at $(printf '%s' "$SHA" | cut -c1-7)"
    if [ -s "$SETTLED_FILE" ]; then
      WHAT="$WHAT after Rouh settled its collision with $TARGET itself: it $(paste -sd ';' "$SETTLED_FILE" | sed 's/;/; and it /g')"
    elif [ "$MERGED" = "1" ]; then
      WHAT="$WHAT after Rouh merged its collision with $TARGET itself"
    fi
    say "$WHAT"
    landed_and "$SHA" landed "$WHAT" \
      "commits=$COMMITS" "files=lines@$FILES_FILE" "attempt=$ATTEMPT" \
      "merged_by_rouh=$([ "$MERGED" = "1" ] && echo true || echo false)" \
      ${RID:+"conflict=$RID"}
  fi
  # Somebody landed between the fetch and the push, which the lock makes rare
  # and cannot make impossible: the laptop pushes to this repository too.
  say "the push was refused, so it is fetched and replayed again: $(printf '%s' "$PUSH_ERR" | tr '\n' ' ' | cut -c1-160)"
  fetch_target || break
  ERR=$(GIT_EDITOR=true g rebase -q --empty=drop $ASIDE "$TARGET_REF" 2>&1)
  if [ "$?" != "0" ]; then
    g rebase --abort 2>/dev/null
    break
  fi
  SHA=$(gq rev-parse HEAD)
  gq diff --name-only "$TARGET_REF..HEAD" >"$FILES_FILE" || : >"$FILES_FILE"
done
finish 1 state=error landed=false "commits=$COMMITS" \
  "reason=the push was refused three times: $(printf '%s' "$PUSH_ERR" | tr '\n' ' ' | cut -c1-200)"
