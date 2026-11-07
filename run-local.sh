#!/usr/bin/env bash
# Run Rouh on the laptop against the same code that runs on the server.
#
# The interpreter is pyenv's (.python-version), the packages are uv's
# (pyproject.toml, uv.lock), and the database is PostgreSQL, as on the server.
# The laptop's own PostgreSQL is used by default - a database called `rouh`
# owned by you, reached over its local socket - and ROUH_DB_* point it
# anywhere else (rouh/config.py). With no PostgreSQL at all, `ROUH_LOCAL_PG=1`
# makes a cluster of its own in .local-data/pg, the way the browser
# environment does for every world it stands up.
#
# The keys come from the assistant workspace's .env, read in place, as they
# always have been: nothing secret is copied into this repository.
set -euo pipefail
cd "$(dirname "$0")"
command -v uv >/dev/null || { echo "run-local: install uv first (https://docs.astral.sh/uv/)" >&2; exit 1; }
uv sync --quiet --frozen
ENV_FILE="${ROUH_ENV_FILE:-$HOME/www/assistant/.env}"
[ -f "$ENV_FILE" ] && { set -a; . "$ENV_FILE"; set +a; }
export ROUH_DATA_DIR="${ROUH_DATA_DIR:-$PWD/.local-data}"
mkdir -p "$ROUH_DATA_DIR"

if [ "${ROUH_LOCAL_PG:-0}" = "1" ]; then
  eval "$(.venv/bin/python - <<'PY'
import os, shlex, sys
sys.path.insert(0, ".")
from rouh.testing import postgres
cluster = postgres.start(os.path.join(os.environ["ROUH_DATA_DIR"], "pg"))
for k, v in cluster.env().items():
    print(f"export {k}={shlex.quote(v)}")
PY
)"
else
  export ROUH_DB_HOST="${ROUH_DB_HOST:-/tmp}" ROUH_DB_USER="${ROUH_DB_USER:-$USER}"
  export ROUH_DB_PASSWORD_FILE="${ROUH_DB_PASSWORD_FILE:-$ROUH_DATA_DIR/no-password.json}"
  createdb "${ROUH_DB_NAME:-rouh}" 2>/dev/null || true
fi
.venv/bin/python manage.py migrate --noinput

# There is no way to turn the gate off, on the laptop or anywhere else, so the
# laptop gets an account of its own. `ensure` makes one the first time and
# prints its password once; after that it says nothing and the password you
# wrote down still works. `passwd` changes it:
#
#   .venv/bin/python manage.py account passwd "$ROUH_LOCAL_USER"
#
export ROUH_LOCAL_USER="${ROUH_LOCAL_USER:-${USER:-owner}}"
.venv/bin/python manage.py account ensure "$ROUH_LOCAL_USER"
export ROUH_PORT="${ROUH_PORT:-8021}"
# The address the laptop's Rouh is opened at, unless the environment file names
# one: links it writes to itself open here, never on another installation.
export ROUH_PUBLIC_URL="${ROUH_PUBLIC_URL:-http://127.0.0.1:$ROUH_PORT}"
exec .venv/bin/python -m uvicorn rouh.server:app --host 127.0.0.1 --port "$ROUH_PORT" "$@"
