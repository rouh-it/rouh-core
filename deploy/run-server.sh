#!/bin/sh
#
# What systemd starts. **Installed outside the checkout**, beside it (for
# example /var/www/rouh/run-server.sh next to the checkout at
# /var/www/rouh/app), and this is the copy to install from.
#
# It exists because of one thing only: a deploy that fails is rolled back to
# the commit before it, and a unit file naming a module by hand cannot be
# rolled back with it. The package was once `jarvis/` and is `rouh/` now, so an
# ExecStart that named either one would have made every rollback across the
# rename come up dead. This asks the checkout instead.
#
# It can go once nothing on main still has a `jarvis/` to roll back to, which
# is a decision to take with RENAME.md open, not a tidy-up.
#
# Everything else - the port, the host, the ping timings - is here rather than
# in the unit so that there is one place to read it. The folders, the port and
# the host are settings (deploy/installation.env.example), read from the
# service's environment.
set -eu

APP="${ROUH_APP_DIR:-${JARVIS_APP_DIR:-/var/www/rouh/app}}"
VENV="${ROUH_VENV:-${JARVIS_VENV:-/var/www/rouh/.venv}}"
PORT="${ROUH_PORT:-${JARVIS_PORT:-8021}}"
HOST="${ROUH_HOST:-${JARVIS_HOST:-127.0.0.1}}"

cd "$APP"
if [ -d rouh ]; then
  MODULE=rouh.server:app
elif [ -d jarvis ]; then
  MODULE=jarvis.server:app
else
  echo "run-server.sh: there is no rouh/ and no jarvis/ in $APP" >&2
  exit 1
fi

exec "$VENV/bin/python" -m uvicorn "$MODULE" \
  --host "$HOST" --port "$PORT" \
  --ws-ping-interval 20 --ws-ping-timeout 20
