#!/bin/bash
# Run one command as root, in a checkout of Rouh, with exactly the environment the live Rouh has.
#
#   deploy/with-rouh-env.sh <checkout> <command> [args...]
#   deploy/with-rouh-env.sh ~/my-checkout "$ROUH_VENV/bin/python" manage.py synapse_chat_recall
#
# The environment is copied from the running Rouh service's process (its settings file and its
# drop-ins), so the command reaches the same database and the same model keys, and nobody has to
# read the settings file to do it. It is how a nightly Synapse worker measures a branch against
# live Synapse Master (read only) without deploying it (rouh/synapse/nightly_brief.md). Nothing is
# printed of the environment itself.
#
#   ROUH_SERVICE   the systemd service Rouh runs as, `rouh` unless the installation says otherwise
#
# Reading another process's environment needs root, so a caller that is not root goes through
# `sudo -n`, which has to be allowed to run bash without asking for a password.
set -euo pipefail
if [ "$#" -lt 2 ]; then
    echo "usage: $0 <checkout> <command> [args...]" >&2
    exit 2
fi

# Every setting is read as ROUH_<name> and then as the JARVIS_<name> it was
# called before the rename, the same way deploy/rouh.sh reads them.
setting() {                       # setting NAME DEFAULT
  local new="$1" old="JARVIS_${1#ROUH_}" said
  said="${!new:-}"
  [ -n "$said" ] || said="${!old:-}"
  printf '%s' "${said:-$2}"
}
service="$(setting ROUH_SERVICE rouh)"

# In the containers there is no systemd and no Rouh service to copy from: the worker is kept off the
# database network on purpose and holds no password, so there is no environment here that reaches the
# live database. Said plainly, at once, instead of "System has not been booted with systemd" on every
# call (the nightly Synapse attempts #47 to #51, 1 to 5 November 2026). In the core itself a command
# already has Rouh's environment: docker compose exec core python manage.py <command>.
if [ ! -d /run/systemd/system ] || ! command -v systemctl >/dev/null 2>&1; then
    echo "with-rouh-env.sh: this machine has no systemd, so this is a Rouh in containers and there is no" >&2
    echo "service environment to copy. A run in the worker cannot reach the live database from here (by design;" >&2
    echo "how a job may reach it is the owner's Decision 422). From the machine itself:" >&2
    echo "  docker compose exec core python manage.py <command>" >&2
    exit 4
fi

dir=$(cd "$1" && pwd)
shift
pid=$(systemctl show -p MainPID --value "$service")
if [ -z "$pid" ] || [ "$pid" = "0" ]; then
    echo "$service.service is not running, so there is no environment to copy" >&2
    exit 3
fi
as_root=(sudo -n)
[ "$(id -u)" = 0 ] && as_root=()
exec "${as_root[@]}" env -i PID="$pid" DIR="$dir" bash -c '
    while IFS= read -r -d "" kv; do export "$kv"; done < "/proc/$PID/environ"
    unset PID
    cd "$DIR"
    export PYTHONPATH="$DIR"
    # Root reading a checkout another user owns: without this git refuses it as "dubious ownership",
    # and a command that records which code it ran would record it as "unknown".
    export GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=safe.directory GIT_CONFIG_VALUE_0="$DIR"
    unset DIR
    exec "$@"' bash "$@"
